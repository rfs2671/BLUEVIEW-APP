"""Full-size photo base64 purge, and the readers that have to survive it.

Activity photos are stored TWICE — as objects in R2, and inlined as base64
under data.activities[].photos[]. The inline copy was never removed, and
base64 inflates the 150KB client-side cap to ~200KB per photo, which is what
walks a logbook toward MongoDB's 16MB ceiling. It fails on the end-of-day save
of a signed record, after the CP has already done the work.

So the full-size inline copy is dropped at FINALIZE. Two halves are tested here
and neither is optional:

  THE PURGE — three conditions, all required: enhance_status == "done", both
  R2 keys present, and a live head_object on BOTH. The first two record what
  the enhance pass BELIEVED; only head_object asks R2 what it HAS. Anything
  short of all three and the base64 stays, permanently. The thumbnail base64
  written in its place is never purged under any condition — a small photo
  beats no photo on a signed legal record.

  THE READERS — the serving endpoint and the daily report both used to key off
  `photo.get("base64")`. Left alone, the endpoint would 404 a purged photo and
  the report would silently OMIT it, which reads as "no photos taken" on a day
  photos were taken: a false compliance record, and worse than a broken image.
"""

from __future__ import annotations

import base64 as _b64
import io
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import asyncio  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
#  Fakes
# ══════════════════════════════════════════════════════════════════════════

FULL_BYTES = b"FULL-SIZE-ORIGINAL-JPEG-BYTES" * 8
ENH_BYTES = b"ENHANCED-JPEG-BYTES" * 8
THUMB_BYTES = b"THUMBNAIL-JPEG-BYTES"

FULL_B64 = _b64.b64encode(FULL_BYTES).decode("ascii")
THUMB_B64 = _b64.b64encode(THUMB_BYTES).decode("ascii")

ENH_KEY = "logbook-photos/proj1/lb1/0-0-enhanced.jpg"
THUMB_KEY = "logbook-photos/proj1/lb1/0-0-thumb.jpg"


def _set_path(doc, dotted, value):
    """Apply a Mongo dotted path against the in-memory document."""
    parts = dotted.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def _unset_path(doc, dotted):
    parts = dotted.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    cur.pop(parts[-1], None)


class _Result:
    def __init__(self, _id="x"):
        self.inserted_id = _id
        self.matched_count = 1
        self.modified_count = 1


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, *a, **k):
        return list(self._docs)


class _FakeCollection:
    """Records writes AND applies them, so a test can assert on the document
    the purge actually leaves behind rather than on the update it sent."""

    def __init__(self, name):
        self.name = name
        self.docs = []
        self.updated = []
        self.inserted = []

    async def find_one(self, query=None, *a, **k):
        return self.docs[0] if self.docs else None

    def find(self, query=None, *a, **k):
        return _Cursor(self.docs)

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(dict(doc))
        return _Result()

    async def update_one(self, q, u, *a, **k):
        self.updated.append((q, u))
        for doc in self.docs:
            for path, val in (u.get("$set") or {}).items():
                _set_path(doc, path, val)
            for path in (u.get("$unset") or {}):
                _unset_path(doc, path)
        return _Result()


class _FakeDb:
    def __init__(self):
        self._c = {}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection(n)
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


class _FakeR2:
    """R2 as the purge sees it: an object either IS there or it is not."""

    def __init__(self, objects):
        self.objects = dict(objects)
        self.heads = []
        self.gets = []

    def head_object(self, Bucket=None, Key=None, **k):
        self.heads.append(Key)
        if Key not in self.objects:
            raise RuntimeError(f"404 NoSuchKey: {Key}")
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, Bucket=None, Key=None, **k):
        self.gets.append(Key)
        if Key not in self.objects:
            raise RuntimeError(f"404 NoSuchKey: {Key}")
        return {"Body": io.BytesIO(self.objects[Key])}


FULL_R2 = {ENH_KEY: ENH_BYTES, THUMB_KEY: THUMB_BYTES}


def _photo(**overrides):
    p = {
        "base64": FULL_B64,
        "uri": "file:///data/user/0/cap_1.jpg",
        "enhance_status": "done",
        "enhanced_r2_key": ENH_KEY,
        "thumb_r2_key": THUMB_KEY,
    }
    p.update(overrides)
    return {k: v for k, v in p.items() if v is not None}


def _logbook(photos=None, **overrides):
    doc = {
        "_id": "lb1",
        "project_id": "proj1",
        "company_id": "co_a",
        "log_type": "daily_jobsite",
        "date": "2026-08-07",
        "cp_signature": {"paths": [[1, 2]], "signed_at": "2026-08-07T12:00:00Z"},
        "cp_name": "Casey CP",
        "data": {
            "activities": [{
                "crew_id": "C1", "company": "Acme", "num_workers": 3,
                "work_description": "shoring", "work_locations": "cellar",
                "photos": [dict(p) for p in (photos if photos is not None else [_photo()])],
            }],
        },
    }
    doc.update(overrides)
    return doc


def _db_with(doc):
    db = _FakeDb()
    db.logbooks.docs = [doc]
    return db


def _run_purge(doc, r2=None, bucket="bv-bucket"):
    db = _db_with(doc)
    with patch.object(server, "db", db), \
         patch.object(server, "_r2_client", r2), \
         patch.object(server, "R2_BUCKET_NAME", bucket):
        loop = asyncio.new_event_loop()
        try:
            n = loop.run_until_complete(
                server._purge_finalized_photo_base64("lb1", doc)
            )
        finally:
            loop.close()
    return n, doc, db


def _first_photo(doc):
    return doc["data"]["activities"][0]["photos"][0]


# ══════════════════════════════════════════════════════════════════════════
#  THE PURGE — the three conditions
# ══════════════════════════════════════════════════════════════════════════

class PurgeConditionsTest(unittest.TestCase):

    def test_all_three_conditions_met_purges_the_full_size_copy(self):
        n, doc, _ = _run_purge(_logbook(), _FakeR2(FULL_R2))
        photo = _first_photo(doc)
        self.assertEqual(n, 1)
        self.assertNotIn("base64", photo, "full-size base64 survived the purge")
        self.assertIn("base64_purged_at", photo)

    def test_the_retained_thumbnail_is_the_bytes_r2_actually_holds(self):
        """Not a re-encode of anything local: the last copy is materialised
        from what R2 returns, so it cannot be a copy of something absent."""
        _, doc, _ = _run_purge(_logbook(), _FakeR2(FULL_R2))
        self.assertEqual(_first_photo(doc)["thumb_base64"], THUMB_B64)
        self.assertEqual(_b64.b64decode(_first_photo(doc)["thumb_base64"]), THUMB_BYTES)

    def test_thumbnail_is_written_in_the_same_update_that_drops_the_original(self):
        """No instant where the photo has neither copy."""
        _, _, db = _run_purge(_logbook(), _FakeR2(FULL_R2))
        self.assertEqual(len(db.logbooks.updated), 1)
        _q, u = db.logbooks.updated[0]
        self.assertIn("data.activities.0.photos.0.thumb_base64", u["$set"])
        self.assertIn("data.activities.0.photos.0.base64", u["$unset"])

    # ── condition 1 ──────────────────────────────────────────────────────

    def test_enhance_status_failed_is_not_purged(self):
        n, doc, db = _run_purge(
            _logbook([_photo(enhance_status="failed", enhance_error="boom")]),
            _FakeR2(FULL_R2),
        )
        self.assertEqual(n, 0)
        self.assertEqual(_first_photo(doc)["base64"], FULL_B64)
        self.assertEqual(db.logbooks.updated, [])

    def test_enhance_status_absent_is_not_purged(self):
        n, doc, _ = _run_purge(
            _logbook([_photo(enhance_status=None)]), _FakeR2(FULL_R2),
        )
        self.assertEqual(n, 0)
        self.assertEqual(_first_photo(doc)["base64"], FULL_B64)

    # ── condition 2 ──────────────────────────────────────────────────────

    def test_missing_thumb_key_is_not_purged(self):
        n, doc, _ = _run_purge(
            _logbook([_photo(thumb_r2_key=None)]), _FakeR2(FULL_R2),
        )
        self.assertEqual(n, 0)
        self.assertEqual(_first_photo(doc)["base64"], FULL_B64)

    def test_missing_enhanced_key_is_not_purged(self):
        n, doc, _ = _run_purge(
            _logbook([_photo(enhanced_r2_key=None)]), _FakeR2(FULL_R2),
        )
        self.assertEqual(n, 0)
        self.assertEqual(_first_photo(doc)["base64"], FULL_B64)

    # ── condition 3: what R2 HAS, not what the writer believed ───────────

    def test_status_done_but_enhanced_object_missing_is_not_purged(self):
        """enhance_status is the writer's own account of its work. head_object
        is the only condition that can contradict it."""
        r2 = _FakeR2({THUMB_KEY: THUMB_BYTES})
        n, doc, db = _run_purge(_logbook(), r2)
        self.assertEqual(n, 0)
        self.assertEqual(_first_photo(doc)["base64"], FULL_B64)
        self.assertEqual(db.logbooks.updated, [])

    def test_status_done_but_thumb_object_missing_is_not_purged(self):
        r2 = _FakeR2({ENH_KEY: ENH_BYTES})
        n, doc, _ = _run_purge(_logbook(), r2)
        self.assertEqual(n, 0)
        self.assertEqual(_first_photo(doc)["base64"], FULL_B64)

    def test_both_keys_are_head_checked(self):
        r2 = _FakeR2(FULL_R2)
        _run_purge(_logbook(), r2)
        self.assertEqual(set(r2.heads), {ENH_KEY, THUMB_KEY})

    def test_r2_unreachable_purges_nothing(self):
        """A dead R2 is indistinguishable from a missing object, and both mean
        the proof was not obtained."""
        class _Dead:
            def head_object(self, **k):
                raise ConnectionError("R2 unreachable")

            def get_object(self, **k):
                raise ConnectionError("R2 unreachable")

        n, doc, db = _run_purge(_logbook(), _Dead())
        self.assertEqual(n, 0)
        self.assertEqual(_first_photo(doc)["base64"], FULL_B64)
        self.assertEqual(db.logbooks.updated, [])

    def test_no_r2_client_at_all_purges_nothing(self):
        n, doc, db = _run_purge(_logbook(), None)
        self.assertEqual(n, 0)
        self.assertEqual(_first_photo(doc)["base64"], FULL_B64)
        self.assertEqual(db.logbooks.updated, [])

    def test_no_bucket_configured_purges_nothing(self):
        n, doc, _ = _run_purge(_logbook(), _FakeR2(FULL_R2), bucket="")
        self.assertEqual(n, 0)
        self.assertEqual(_first_photo(doc)["base64"], FULL_B64)

    # ── the thumbnail is never the thing that gets removed ───────────────

    def test_thumbnail_base64_is_never_unset_on_any_path(self):
        cases = [
            (_logbook(), _FakeR2(FULL_R2)),
            (_logbook(), _FakeR2({THUMB_KEY: THUMB_BYTES})),
            (_logbook([_photo(enhance_status="failed")]), _FakeR2(FULL_R2)),
            (_logbook([_photo(base64=None, thumb_base64=THUMB_B64)]), _FakeR2(FULL_R2)),
            (_logbook([_photo(thumb_base64=THUMB_B64)]), _FakeR2(FULL_R2)),
        ]
        for i, (doc, r2) in enumerate(cases):
            with self.subTest(case=i):
                _, out, db = _run_purge(doc, r2)
                for _q, u in db.logbooks.updated:
                    for path in (u.get("$unset") or {}):
                        self.assertFalse(
                            path.endswith("thumb_base64"),
                            "the last-resort copy was unset",
                        )

    def test_an_already_purged_photo_keeps_its_thumbnail(self):
        doc = _logbook([_photo(base64=None, thumb_base64=THUMB_B64)])
        n, out, db = _run_purge(doc, _FakeR2(FULL_R2))
        self.assertEqual(n, 0)
        self.assertEqual(_first_photo(out)["thumb_base64"], THUMB_B64)
        self.assertEqual(db.logbooks.updated, [], "purged twice")

    def test_purge_is_idempotent_across_repeated_runs(self):
        doc = _logbook()
        r2 = _FakeR2(FULL_R2)
        first, doc, _ = _run_purge(doc, r2)
        second, doc, db2 = _run_purge(doc, r2)
        self.assertEqual((first, second), (1, 0))
        self.assertEqual(_first_photo(doc)["thumb_base64"], THUMB_B64)
        self.assertEqual(db2.logbooks.updated, [])

    def test_existing_thumbnail_is_not_refetched(self):
        """Re-downloading would be harmless but pointless; more importantly the
        retained copy is never overwritten by a later fetch."""
        r2 = _FakeR2(FULL_R2)
        _, doc, _ = _run_purge(
            _logbook([_photo(thumb_base64="SENTINEL")]), r2,
        )
        self.assertEqual(_first_photo(doc)["thumb_base64"], "SENTINEL")
        self.assertEqual(r2.gets, [])

    # ── keys come off the photo, never recomputed from position ──────────

    def test_keys_are_read_from_the_photo_not_derived_from_indices(self):
        """Activity rows can be reordered after upload. A key recomputed from
        (ai, pi) would then point at a DIFFERENT photo's object, and the purge
        would 'prove' the wrong file."""
        odd_enh = "logbook-photos/proj1/lb1/7-3-enhanced.jpg"
        odd_thumb = "logbook-photos/proj1/lb1/7-3-thumb.jpg"
        r2 = _FakeR2({odd_enh: ENH_BYTES, odd_thumb: THUMB_BYTES})
        n, doc, _ = _run_purge(
            _logbook([_photo(enhanced_r2_key=odd_enh, thumb_r2_key=odd_thumb)]), r2,
        )
        self.assertEqual(n, 1)
        self.assertEqual(set(r2.heads), {odd_enh, odd_thumb})
        positional = server._logbook_photo_r2_key("proj1", "lb1", 0, 0, "enhanced")
        self.assertNotIn(positional, r2.heads)

    # ── per-photo independence ───────────────────────────────────────────

    def test_one_unprovable_photo_does_not_block_its_siblings(self):
        other_enh = "logbook-photos/proj1/lb1/0-1-enhanced.jpg"
        other_thumb = "logbook-photos/proj1/lb1/0-1-thumb.jpg"
        doc = _logbook([
            _photo(),                                              # provable
            _photo(enhanced_r2_key=other_enh, thumb_r2_key=other_thumb),
        ])
        n, out, _ = _run_purge(doc, _FakeR2(FULL_R2))   # only photo 0's objects
        photos = out["data"]["activities"][0]["photos"]
        self.assertEqual(n, 1)
        self.assertNotIn("base64", photos[0])
        self.assertEqual(photos[1]["base64"], FULL_B64)


# ══════════════════════════════════════════════════════════════════════════
#  THE TRIGGER — finalize, after the lock
# ══════════════════════════════════════════════════════════════════════════

def _finalize(doc, r2, bucket="bv-bucket"):
    db = _db_with(doc)
    user = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "co_a",
            "full_name": "Ada Admin", "assigned_projects": ["proj1"]}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db), \
             patch.object(server, "_r2_client", r2), \
             patch.object(server, "R2_BUCKET_NAME", bucket):
            resp = TestClient(server.app).post("/api/logbooks/lb1/finalize")
    finally:
        server.app.dependency_overrides.clear()
    return resp, doc, db


class FinalizeTriggersPurgeTest(unittest.TestCase):

    def test_finalize_locks_and_purges(self):
        resp, doc, db = _finalize(_logbook(), _FakeR2(FULL_R2))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(doc.get("is_locked"))
        self.assertNotIn("base64", _first_photo(doc))
        self.assertEqual(_first_photo(doc)["thumb_base64"], THUMB_B64)

    def test_purge_runs_after_the_lock_is_set(self):
        """Order matters: the record is immutable BEFORE any byte is dropped."""
        _resp, _doc, db = _finalize(_logbook(), _FakeR2(FULL_R2))
        paths = [list((u.get("$set") or {})) for _q, u in db.logbooks.updated]
        self.assertIn("is_locked", paths[0])
        self.assertTrue(
            any(k.endswith("thumb_base64") for p in paths[1:] for k in p),
            f"no purge update followed the lock: {paths}",
        )

    def test_finalize_still_succeeds_when_r2_cannot_confirm(self):
        """A finalize that worked must never report failure over a storage
        optimisation — and the bytes stay, which is the safe direction."""
        resp, doc, _ = _finalize(_logbook(), _FakeR2({}))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(doc.get("is_locked"))
        self.assertEqual(_first_photo(doc)["base64"], FULL_B64)

    def test_finalize_survives_a_purge_that_raises(self):
        class _Exploding:
            def head_object(self, **k):
                raise MemoryError("not a normal failure")

        resp, doc, _ = _finalize(_logbook(), _Exploding())
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(doc.get("is_locked"))
        self.assertEqual(_first_photo(doc)["base64"], FULL_B64)

    def test_an_already_locked_log_is_not_re_purged(self):
        doc = _logbook(is_locked=True)
        resp, out, db = _finalize(doc, _FakeR2(FULL_R2))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(db.logbooks.updated, [])
        self.assertEqual(_first_photo(out)["base64"], FULL_B64)


# ══════════════════════════════════════════════════════════════════════════
#  READER 1 — the public serving endpoint
# ══════════════════════════════════════════════════════════════════════════

def _serve(doc, r2, v=None, bucket="bv-bucket"):
    db = _db_with(doc)
    url = "/api/reports/logbook-photo/lb1/0/0" + (f"?v={v}" if v else "")
    with patch.object(server, "db", db), \
         patch.object(server, "_r2_client", r2), \
         patch.object(server, "R2_BUCKET_NAME", bucket):
        return TestClient(server.app).get(url)


PURGED = _photo(base64=None, thumb_base64=THUMB_B64,
                base64_purged_at=datetime(2026, 8, 7, tzinfo=timezone.utc))


class ServingLadderTest(unittest.TestCase):

    def test_purged_photo_still_serves_the_thumbnail_derivative(self):
        resp = _serve(_logbook([dict(PURGED)]), _FakeR2(FULL_R2), v="thumb")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, THUMB_BYTES)

    def test_purged_photo_still_serves_the_enhanced_derivative(self):
        resp = _serve(_logbook([dict(PURGED)]), _FakeR2(FULL_R2), v="enhanced")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, ENH_BYTES)

    def test_missing_enhanced_object_falls_through_to_the_thumb_object(self):
        """The old ladder tried one key and then the original. With the
        original purged that was a 404 on a photo R2 could still have served."""
        resp = _serve(_logbook([dict(PURGED)]),
                      _FakeR2({THUMB_KEY: THUMB_BYTES}), v="enhanced")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, THUMB_BYTES)

    def test_r2_entirely_gone_falls_through_to_the_retained_thumbnail(self):
        """The rung the whole purge rests on. R2 unreachable at READ time must
        degrade to a small photo, never to no photo."""
        resp = _serve(_logbook([dict(PURGED)]), _FakeR2({}), v="enhanced")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, THUMB_BYTES)

    def test_no_r2_client_falls_through_to_the_retained_thumbnail(self):
        resp = _serve(_logbook([dict(PURGED)]), None, v="thumb")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, THUMB_BYTES)

    def test_purged_photo_with_no_variant_serves_the_thumbnail_not_a_404(self):
        resp = _serve(_logbook([dict(PURGED)]), None)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, THUMB_BYTES)

    def test_unpurged_original_request_still_serves_the_untouched_original(self):
        """`?v=` means ORIGINAL. Serving an enhanced render under it would make
        the editor's 'Original' lightbox label a lie."""
        resp = _serve(_logbook(), _FakeR2(FULL_R2))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, FULL_BYTES)

    def test_failed_enhance_still_renders_from_its_original(self):
        doc = _logbook([_photo(enhance_status="failed",
                               enhanced_r2_key=None, thumb_r2_key=None)])
        resp = _serve(doc, _FakeR2({}), v="enhanced")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, FULL_BYTES)

    def test_a_photo_with_no_copies_at_all_is_the_only_404(self):
        doc = _logbook([{"uri": "file:///gone.jpg"}])
        resp = _serve(doc, _FakeR2(FULL_R2), v="thumb")
        self.assertEqual(resp.status_code, 404)

    def test_out_of_range_indices_still_404(self):
        db = _db_with(_logbook())
        with patch.object(server, "db", db), \
             patch.object(server, "_r2_client", _FakeR2(FULL_R2)), \
             patch.object(server, "R2_BUCKET_NAME", "bv-bucket"):
            c = TestClient(server.app)
            self.assertEqual(c.get("/api/reports/logbook-photo/lb1/9/0").status_code, 404)
            self.assertEqual(c.get("/api/reports/logbook-photo/lb1/0/9").status_code, 404)


class PhotoSourceLadderUnitTest(unittest.TestCase):

    def test_renderable_on_an_r2_key_alone(self):
        self.assertTrue(server._logbook_photo_is_renderable(
            {"enhanced_r2_key": ENH_KEY, "thumb_r2_key": THUMB_KEY},
        ))

    def test_renderable_on_the_retained_thumbnail_alone(self):
        self.assertTrue(server._logbook_photo_is_renderable({"thumb_base64": THUMB_B64}))

    def test_not_renderable_with_no_copies(self):
        self.assertFalse(server._logbook_photo_is_renderable({"uri": "file:///x.jpg"}))
        self.assertFalse(server._logbook_photo_is_renderable({}))
        self.assertFalse(server._logbook_photo_is_renderable(None))

    def test_the_retained_thumbnail_is_always_the_last_rung(self):
        photo = dict(PURGED)
        for v in ("", "thumb", "enhanced", "nonsense"):
            with self.subTest(v=v):
                srcs = server._logbook_photo_sources(photo, v)
                self.assertEqual(srcs[-1], ("b64", THUMB_B64))


# ══════════════════════════════════════════════════════════════════════════
#  READER 2 — the emailed daily report
# ══════════════════════════════════════════════════════════════════════════

def _report(photos):
    db = _FakeDb()
    db.projects.docs = [{"_id": "proj1", "name": "5 Beekman", "address": "5 Beekman St"}]
    db.logbooks.docs = [_logbook(photos)]
    loop = asyncio.new_event_loop()
    try:
        with patch.object(server, "db", db):
            return loop.run_until_complete(
                server.generate_combined_report("proj1", "2026-08-07")
            )
    finally:
        loop.close()


class ReportEmitGateTest(unittest.TestCase):

    def test_a_purged_photo_is_still_emitted(self):
        """It used to emit only `if photo.get("base64")`. A purged photo would
        not render broken — it would VANISH, and the report would read as no
        photos taken on a day photos were taken."""
        html = _report([dict(PURGED)])
        self.assertIn("/api/reports/logbook-photo/lb1/0/0?v=thumb", html)
        self.assertIn("/api/reports/logbook-photo/lb1/0/0?v=enhanced", html)

    def test_a_photo_with_only_r2_keys_and_no_inline_copy_is_emitted(self):
        html = _report([_photo(base64=None)])
        self.assertIn("/api/reports/logbook-photo/lb1/0/0", html)

    def test_an_unpurged_photo_is_still_emitted(self):
        html = _report([_photo(enhance_status=None,
                               enhanced_r2_key=None, thumb_r2_key=None)])
        self.assertIn("/api/reports/logbook-photo/lb1/0/0", html)

    def test_a_photo_with_no_copies_is_not_emitted(self):
        html = _report([{"uri": "file:///gone.jpg"}])
        self.assertNotIn("/api/reports/logbook-photo/lb1/0/0", html)

    def test_the_url_shape_did_not_change(self):
        html = _report([dict(PURGED)])
        self.assertIn(
            "https://api.levelog.com/api/reports/logbook-photo/lb1/0/0?v=thumb", html,
        )


if __name__ == "__main__":
    unittest.main()
