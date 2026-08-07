"""TEN SUBCONTRACTORS x TEN PHOTOS = 100 PHOTOS ON ONE DAILY JOBSITE LOG.

The activity photo cap is 10 per SUBCONTRACTOR, aggregated across every activity
row that names it. A busy day is therefore not 10 photos, it is 10 x however
many subs are on site — and every photo is stored TWICE: as an object in R2 and
inlined as base64 under data.activities[].photos[]. A logbook is one MongoDB
document with a hard 16MB ceiling, and it fails at the worst possible moment:
on the end-of-day save of a signed record, after the CP has done all the work.

So the cap cannot be signed off on the UI accepting the photos. What is measured
here is the DOCUMENT, in bytes, through the real create endpoint and the real
finalize purge:

  • all 100 photos save, across ten distinct subcontractor_ids
  • finalize drops every full-size inline copy once R2 confirms both
    derivatives, and keeps the ~25-40KB thumbnail (server.py:17205) that the
    purge is forbidden to remove
  • the resulting document is comfortably under 16MB

It also pins the constraint that makes the purge non-optional: at the client's
own compression cap (150KB per photo, compressPhoto.js), 100 full-size inline
copies do NOT fit under 16MB. That is the pre-purge peak the CP's last save has
to carry, and it is measured here rather than assumed. If the storage model
changes — a smaller client cap, or base64 stopping being inlined at save — this
is the test that says so and the numbers need re-measuring.
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

from bson import BSON  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


# ── the real numbers ─────────────────────────────────────────────────────

MONGO_MAX_BSON = 16 * 1024 * 1024          # the hard ceiling, 16,777,216 bytes

SUBS = 10
PHOTOS_PER_SUB = 10
TOTAL_PHOTOS = SUBS * PHOTOS_PER_SUB       # 100

# compressPhoto.js caps an upload at 150KB of JPEG. base64 inflates that by 4/3,
# which is the ~200KB per photo the purge docstring cites. This is the WORST
# case a compliant client can produce, and the worst case is the one that has to
# fit.
FULL_JPEG_BYTES = 150 * 1024
FULL_B64 = "A" * (((FULL_JPEG_BYTES + 2) // 3) * 4)

# The retained copy: long edge 400, ~25-40KB (server.py:17205). 32KB is taken as
# the realistic middle of that documented range.
THUMB_JPEG = b"T" * (32 * 1024)
THUMB_B64 = _b64.b64encode(THUMB_JPEG).decode("ascii")

ENH_BYTES = b"E" * 4096


def _r2_keys(ai, pi):
    return (
        f"logbook-photos/proj1/lb1/{ai}-{pi}-enhanced.jpg",
        f"logbook-photos/proj1/lb1/{ai}-{pi}-thumb.jpg",
    )


# ── fakes ────────────────────────────────────────────────────────────────

def _set_path(doc, dotted, value):
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
    def __init__(self, _id="lb1"):
        self.inserted_id = _id
        self.matched_count = 1
        self.modified_count = 1


class _Logbooks:
    """One document, and update_one really applies its dotted paths — so the
    size assertions below are made against the document the endpoints leave
    behind, not against the updates they sent."""

    def __init__(self):
        self.doc = None

    async def find_one(self, query=None, *a, **k):
        # The dedupe read (project_id/log_type/date) must MISS so the create
        # inserts; every later read is by _id and must HIT.
        if query and "_id" in query:
            return self.doc
        return None

    async def count_documents(self, query=None, *a, **k):
        return 0

    async def insert_one(self, doc, *a, **k):
        self.doc = dict(doc)
        self.doc["_id"] = "lb1"
        return _Result()

    async def update_one(self, q, u, *a, **k):
        if self.doc is None:
            return _Result()
        for path, val in (u.get("$set") or {}).items():
            _set_path(self.doc, path, val)
        for path in (u.get("$unset") or {}):
            _unset_path(self.doc, path)
        return _Result()


class _FakeCollection:
    def __init__(self, one=None):
        self.one = one
        self.inserted = []

    async def find_one(self, query=None, *a, **k):
        return self.one

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(doc)
        return _Result("x")

    async def update_one(self, *a, **k):
        return _Result("x")


class _FakeDb:
    def __init__(self, logbooks, project):
        self._c = {
            "logbooks": logbooks,
            "projects": _FakeCollection(one=project),
        }

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection()
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


class _FakeR2:
    """R2 that HAS everything — the only state in which the purge is allowed
    to drop a byte."""

    def __init__(self):
        self.objects = {}
        for ai in range(SUBS):
            for pi in range(PHOTOS_PER_SUB):
                enh, thumb = _r2_keys(ai, pi)
                self.objects[enh] = ENH_BYTES
                self.objects[thumb] = THUMB_JPEG
        self.heads = 0

    def head_object(self, Bucket=None, Key=None, **k):
        self.heads += 1
        if Key not in self.objects:
            raise RuntimeError(f"404 NoSuchKey: {Key}")
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, Bucket=None, Key=None, **k):
        if Key not in self.objects:
            raise RuntimeError(f"404 NoSuchKey: {Key}")
        return {"Body": io.BytesIO(self.objects[Key])}


PROJECT = {
    "_id": "proj1", "name": "Test Tower", "company_id": "co_test",
    "is_deleted": False,
}


def _activities():
    """Ten subcontractors, ten photos each, shaped exactly as the editor sends
    them — including the identity fields the cap buckets on."""
    out = []
    for ai in range(SUBS):
        enh_pref, thumb_pref = _r2_keys(ai, 0)
        photos = []
        for pi in range(PHOTOS_PER_SUB):
            enh, thumb = _r2_keys(ai, pi)
            photos.append({
                "base64": FULL_B64,
                "uri": f"file:///data/user/0/logbook_photos/{ai}_{pi}.jpg",
                "timestamp": "2026-08-07T13:00:00.000Z",
                # What the enhance pass leaves behind on a photo it uploaded.
                "enhance_status": "done",
                "enhanced_r2_key": enh,
                "thumb_r2_key": thumb,
            })
        out.append({
            "activity_id": f"act_1754500000000_{ai}",
            "subcontractor_id": f"srv_{ai:032x}",
            "crew_id": f"C{ai + 1}",
            "company": f"Sub {ai}",
            "num_workers": "4",
            "work_description": "shoring",
            "work_locations": "cellar",
            "photos": photos,
        })
    return out


def _payload():
    return {
        "project_id": "proj1",
        "log_type": "daily_jobsite",
        "date": "2026-08-07",
        "data": {
            "project_address": "1 Test Plaza, Brooklyn NY",
            "weather": "Sunny",
            "general_description": "Shoring and slab prep.",
            "activities": _activities(),
            "equipment_on_site": {"hoist": True},
            "checklist_items": {"fire_safety": True},
            "observations": [],
            "visitors_deliveries": "",
            "time_in": "07:00", "time_out": "15:30", "areas_visited": "Cellar",
        },
        "cp_signature": {"paths": [[1, 2]], "signed_at": "2026-08-07T15:31:00Z"},
        "cp_name": "Casey CP",
        "status": "submitted",
    }


def _client():
    user = {
        "_id": "cp_1", "id": "cp_1", "role": "cp",
        "company_id": "co_test", "account_status": "approved",
        "full_name": "Casey CP", "assigned_projects": ["proj1"],
    }

    async def _fake_user():
        return user

    ov = server.app.dependency_overrides
    ov[server.get_current_user] = _fake_user
    ov[server.require_approved] = _fake_user
    return TestClient(server.app), ov.clear


async def _no_enhance(*a, **k):
    """The enhance pass is fire-and-forget and irrelevant here: the photos
    already carry the keys it would have written."""
    return None


def _bson_size(doc):
    return len(BSON.encode(doc))


def _run_day():
    """Save the 100-photo log, then finalize it. Returns (response, sizes)."""
    logbooks = _Logbooks()
    db = _FakeDb(logbooks, PROJECT)
    r2 = _FakeR2()
    client, cleanup = _client()
    try:
        with patch.object(server, "db", db), \
             patch.object(server, "_enhance_logbook_photos", _no_enhance), \
             patch.object(server, "_r2_client", r2), \
             patch.object(server, "R2_BUCKET_NAME", "bv-bucket"):
            created = client.post("/api/logbooks", json=_payload())
            pre = _bson_size(logbooks.doc) if logbooks.doc else 0
            finalized = client.post("/api/logbooks/lb1/finalize")
            post = _bson_size(logbooks.doc) if logbooks.doc else 0
    finally:
        cleanup()
    return created, finalized, logbooks.doc, pre, post, r2


class HundredPhotoDocumentTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        (cls.created, cls.finalized, cls.doc,
         cls.pre, cls.post, cls.r2) = _run_day()

    # ── the save ─────────────────────────────────────────────────────────

    def test_one_hundred_photos_save_successfully(self):
        self.assertEqual(self.created.status_code, 200, self.created.text[:400])
        photos = [p for a in self.doc["data"]["activities"] for p in a["photos"]]
        self.assertEqual(len(photos), TOTAL_PHOTOS)

    def test_all_ten_subcontractors_survive_the_round_trip(self):
        acts = self.doc["data"]["activities"]
        self.assertEqual(len(acts), SUBS)
        ids = {a["subcontractor_id"] for a in acts}
        self.assertEqual(len(ids), SUBS, "two subs collapsed onto one id")
        self.assertEqual(
            len({a["activity_id"] for a in acts}), SUBS,
            "activity_id must be unique per row",
        )
        self.assertTrue(all(len(a["photos"]) == PHOTOS_PER_SUB for a in acts))

    # ── the purge ────────────────────────────────────────────────────────

    def test_finalize_purges_every_full_size_copy(self):
        self.assertEqual(self.finalized.status_code, 200, self.finalized.text[:400])
        photos = [p for a in self.doc["data"]["activities"] for p in a["photos"]]
        still_full = [p for p in photos if p.get("base64")]
        self.assertEqual(still_full, [], f"{len(still_full)} full-size copies survived")
        self.assertTrue(all("base64_purged_at" in p for p in photos))

    def test_every_photo_keeps_its_thumbnail(self):
        """The purge must never remove the last inline copy."""
        photos = [p for a in self.doc["data"]["activities"] for p in a["photos"]]
        self.assertEqual(len(photos), TOTAL_PHOTOS)
        self.assertTrue(all(p.get("thumb_base64") == THUMB_B64 for p in photos))

    def test_r2_was_asked_about_both_keys_of_every_photo(self):
        """head_object is the only condition that can contradict the writer's
        own account of its work — it has to be asked once per key."""
        self.assertEqual(self.r2.heads, TOTAL_PHOTOS * 2)

    # ── the bytes ────────────────────────────────────────────────────────

    def test_the_finalized_document_is_under_the_16mb_ceiling(self):
        """THE assertion this file exists for. Ten subs at ten photos each,
        measured as BSON, after the purge."""
        self.assertLess(
            self.post, MONGO_MAX_BSON,
            f"finalized 100-photo logbook is {self.post:,} bytes "
            f"(ceiling {MONGO_MAX_BSON:,})",
        )
        # And not by a hair: a real thumbnail can be 40KB rather than 32KB, and
        # a day can carry observations and a signature bitmap on top.
        self.assertLess(
            self.post, MONGO_MAX_BSON // 2,
            f"finalized document {self.post:,} bytes leaves less than half the "
            f"ceiling free — the margin is gone",
        )

    def test_the_purge_reclaims_the_overwhelming_majority_of_the_document(self):
        reclaimed = 1 - (self.post / self.pre)
        self.assertGreater(
            reclaimed, 0.75,
            f"purge reclaimed only {reclaimed:.1%} "
            f"({self.pre:,} -> {self.post:,} bytes)",
        )

    def test_the_pre_purge_peak_at_the_client_cap_does_not_fit(self):
        """WHY THE PURGE IS NOT OPTIONAL, in bytes.

        Every save before finalize carries the full-size base64 for every photo
        (daily_jobsite handleSave re-encodes any photo that has not already been
        purged). At compressPhoto.js's own 150KB cap that is ~200KB per photo,
        so the end-of-day save of a 100-photo day is over the ceiling BEFORE the
        finalize purge runs — this is measured, not assumed.

        Pinned so the constraint is visible: if the client cap changes, or the
        save path stops inlining base64, this test fails and the numbers above
        have to be re-measured rather than quietly inherited.
        """
        self.assertGreater(
            self.pre, MONGO_MAX_BSON,
            f"pre-purge document is {self.pre:,} bytes",
        )
        per_photo_full = self.pre / TOTAL_PHOTOS
        fits = int(MONGO_MAX_BSON // per_photo_full)
        self.assertLess(
            fits, TOTAL_PHOTOS,
            f"pre-purge headroom is {fits} full-size photos "
            f"(~{per_photo_full:,.0f} bytes each); 100 was expected not to fit",
        )
        self.assertGreater(fits, 60, "sanity: the headroom should be dozens, not a handful")


class BucketBudgetArithmeticTest(unittest.TestCase):
    """The cap's cost model, stated in bytes rather than in photos, so a future
    change to either number is checked against the ceiling and not against a
    guess."""

    def test_the_retained_thumbnail_is_inside_the_documented_range(self):
        # server.py:17205 documents the thumbnail as ~25-40KB.
        self.assertGreaterEqual(len(THUMB_JPEG), 25 * 1024)
        self.assertLessEqual(len(THUMB_JPEG), 40 * 1024)

    def test_a_worst_case_thumbnail_still_fits_for_a_hundred_photos(self):
        worst_thumb_b64 = len(_b64.b64encode(b"T" * (40 * 1024)))
        self.assertLess(worst_thumb_b64 * TOTAL_PHOTOS, MONGO_MAX_BSON)

    def test_the_full_size_inline_copy_is_about_200kb(self):
        """The figure _purge_finalized_photo_base64's docstring cites."""
        self.assertGreater(len(FULL_B64), 195 * 1024)
        self.assertLess(len(FULL_B64), 205 * 1024)


if __name__ == "__main__":
    unittest.main()
