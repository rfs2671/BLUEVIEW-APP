"""The one-shot that gives EXISTING inline photos an R2 object.

Every logbook written before the capture-time upload still holds its photos as
base64 under data.activities[].photos[]. backfill_photo_to_r2.py moves those
bytes into R2 and writes the key. It is an operator-driven script and is NOT
run from CI; what is pinned here is its contract, against fakes:

  • DRY-RUN IS THE DEFAULT — without --execute it uploads nothing and writes
    nothing. A migration whose default is destructive is one keystroke from an
    accident.
  • THE KEY IS CONTENT-ADDRESSED — the same bytes always produce the same key,
    so a re-run overwrites the one object instead of leaving an orphan behind
    for every attempt, including a run that died between upload and write.
  • IT NEVER TOUCHES thumb_base64 — the retained thumbnail is the last inline
    copy a signed record has, and only Track P's purge may write it, from the
    bytes R2 really returns.
  • THE RECLAIM IS DELEGATED — the three purge conditions are not
    reimplemented, because a second implementation of a safety gate is a
    second thing that can be wrong.

Run:  python -m pytest tests/test_photo_r2_backfill.py -q
"""

from __future__ import annotations

import argparse
import base64 as _b64
import io
import os
import sys
import unittest
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

import server  # noqa: E402
from scripts import backfill_photo_to_r2 as bf  # noqa: E402


FULL_BYTES = b"\xff\xd8\xffFULL-SIZE-ORIGINAL" * 4
FULL_B64 = _b64.b64encode(FULL_BYTES).decode("ascii")
THUMB_BYTES = b"THUMBNAIL-BYTES"
THUMB_B64 = _b64.b64encode(THUMB_BYTES).decode("ascii")

OLD_ENH = "logbook-photos/proj1/lb1/0-0-enhanced.jpg"
OLD_THUMB = "logbook-photos/proj1/lb1/0-0-thumb.jpg"


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


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, *a, **k):
        return list(self._docs)


class _Logbooks:
    def __init__(self, docs):
        self.docs = docs
        self.updates = []

    def find(self, *a, **k):
        return _Cursor(self.docs)

    async def find_one(self, *a, **k):
        return self.docs[0] if self.docs else None

    async def update_one(self, q, u, *a, **k):
        self.updates.append(u)
        for doc in self.docs:
            for path, val in (u.get("$set") or {}).items():
                _set_path(doc, path, val)
            for path in (u.get("$unset") or {}):
                _unset_path(doc, path)

        class _R:
            matched_count = 1
            modified_count = 1
        return _R()


class _Db:
    def __init__(self, logbooks):
        self.logbooks = logbooks


class _FakeR2:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts = []
        self.heads = []

    def put_object(self, Bucket=None, Key=None, Body=None, ContentType=None, **k):
        self.puts.append(Key)
        self.objects[Key] = Body
        return {}

    def head_object(self, Bucket=None, Key=None, **k):
        self.heads.append(Key)
        if Key not in self.objects:
            raise RuntimeError(f"404 NoSuchKey: {Key}")
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, Bucket=None, Key=None, **k):
        if Key not in self.objects:
            raise RuntimeError(f"404 NoSuchKey: {Key}")
        return {"Body": io.BytesIO(self.objects[Key])}


def _logbook(photo=None, **overrides):
    doc = {
        "_id": "lb1",
        "project_id": "proj1",
        "log_type": "daily_jobsite",
        "date": "2026-08-07",
        "is_locked": False,
        "data": {"activities": [{
            "activity_id": "act_7", "company": "Acme",
            "photos": [dict(photo if photo is not None else {"base64": FULL_B64})],
        }]},
    }
    doc.update(overrides)
    return doc


def _run(docs, execute=False, r2=None, bucket="bv-bucket"):
    coll = _Logbooks(docs)
    r2 = r2 if r2 is not None else _FakeR2()
    # `server.db` as well as the injected handle: the reclaim delegates to
    # _purge_finalized_photo_base64, which writes through the MODULE-LEVEL db.
    # main() passes server.db for exactly that reason - one handle, one
    # database - so a test that did not model it would be pinning a wiring
    # the script does not have.
    db = _Db(coll)
    with patch.object(server, "db", db), patch.object(server, "_r2_client", r2), \
         patch.object(server, "R2_BUCKET_NAME", bucket):
        stats = asyncio.new_event_loop().run_until_complete(
            bf.run_backfill(db, execute=execute),
        )
    return stats, docs, r2, coll


def _first_photo(doc):
    return doc["data"]["activities"][0]["photos"][0]


# ══════════════════════════════════════════════════════════════════════════

class DryRunIsTheDefaultTest(unittest.TestCase):

    def test_the_signature_default_is_dry_run(self):
        import inspect
        self.assertIs(
            inspect.signature(bf.run_backfill).parameters["execute"].default, False,
        )

    def test_the_cli_flag_is_opt_in(self):
        parser = argparse.ArgumentParser()
        # Mirrors main(); asserted by parsing an EMPTY argv, which is what an
        # operator types when they mean "show me".
        parser.add_argument("--execute", action="store_true")
        self.assertFalse(parser.parse_args([]).execute)
        self.assertTrue(parser.parse_args(["--execute"]).execute)

    def test_main_defines_execute_as_a_store_true_flag(self):
        src = (Path(bf.__file__)).read_text(encoding="utf-8")
        self.assertIn('"--execute", action="store_true"', src)

    def test_a_dry_run_uploads_nothing_and_writes_nothing(self):
        stats, docs, r2, coll = _run([_logbook()], execute=False)
        self.assertEqual(stats["photos_to_upload"], 1)
        self.assertEqual(stats["uploaded"], 0)
        self.assertEqual(r2.puts, [])
        self.assertEqual(coll.updates, [])
        self.assertEqual(_first_photo(docs[0])["base64"], FULL_B64)
        self.assertNotIn("original_r2_key", _first_photo(docs[0]))


class UploadTest(unittest.TestCase):

    def test_it_uploads_the_inline_bytes_and_writes_the_key(self):
        stats, docs, r2, _ = _run([_logbook()], execute=True)
        photo = _first_photo(docs[0])
        key = photo["original_r2_key"]
        self.assertEqual(stats["uploaded"], 1)
        self.assertEqual(r2.objects[key], FULL_BYTES)
        self.assertTrue(key.startswith("logbook-photos/proj1/act_7/"))
        self.assertIn("backfilled_to_r2_at", photo)

    def test_the_key_is_the_capture_scheme(self):
        _, docs, _, _ = _run([_logbook()], execute=True)
        key = _first_photo(docs[0])["original_r2_key"]
        self.assertEqual(
            key,
            server._logbook_capture_photo_r2_key(
                "proj1", "act_7", bf.photo_backfill_id(FULL_B64),
            ),
        )

    def test_it_falls_back_to_the_logbook_id_for_a_row_with_no_activity_id(self):
        """Rows predate activity_id. Still not a POSITION — a reorder must not
        rename the object."""
        doc = _logbook()
        doc["data"]["activities"][0].pop("activity_id")
        _, docs, _, _ = _run([doc], execute=True)
        self.assertTrue(
            _first_photo(docs[0])["original_r2_key"].startswith(
                "logbook-photos/proj1/lb1/",
            ),
        )

    def test_the_id_is_content_addressed(self):
        self.assertEqual(bf.photo_backfill_id(FULL_B64), bf.photo_backfill_id(FULL_B64))
        self.assertNotEqual(bf.photo_backfill_id(FULL_B64), bf.photo_backfill_id("OTHER"))

    def test_a_second_run_creates_no_second_object(self):
        """The crash-resume case: same bytes, same key, one object."""
        docs = [_logbook()]
        _, docs, r2, _ = _run(docs, execute=True)
        first_key = _first_photo(docs[0])["original_r2_key"]
        stats2, docs, r2b, _ = _run(docs, execute=True, r2=r2)
        self.assertEqual(stats2["uploaded"], 0)
        self.assertEqual(stats2["skipped_already_keyed"], 1)
        self.assertEqual(list(r2.objects), [first_key])

    def test_a_photo_with_no_inline_copy_is_left_alone(self):
        """Already migrated, already purged, or captured straight to R2."""
        stats, _, r2, _ = _run(
            [_logbook({"original_r2_key": "logbook-photos/proj1/act_7/cap_1.jpg"})],
            execute=True,
        )
        self.assertEqual(stats["skipped_no_inline_copy"], 1)
        self.assertEqual(r2.puts, [])

    def test_an_undecodable_inline_copy_is_counted_not_dropped(self):
        stats, docs, r2, _ = _run([_logbook({"base64": "!!!not base64!!!"})],
                                  execute=True)
        self.assertEqual(stats["uploaded"], 0)
        self.assertEqual(r2.puts, [])
        self.assertEqual(_first_photo(docs[0])["base64"], "!!!not base64!!!")

    def test_a_failed_upload_never_writes_a_key(self):
        """A key naming an object that does not exist is worse than no key: the
        serving ladder would try it first and the photo would 404 through a
        rung that reads as present."""
        class _Broken(_FakeR2):
            def put_object(self, **k):
                raise RuntimeError("R2 unreachable")
        stats, docs, _, coll = _run([_logbook()], execute=True, r2=_Broken())
        self.assertEqual(stats["upload_failed"], 1)
        self.assertEqual(coll.updates, [])
        self.assertNotIn("original_r2_key", _first_photo(docs[0]))

    def test_execute_refuses_to_run_with_no_r2(self):
        with self.assertRaises(SystemExit):
            _run([_logbook()], execute=True, r2=None, bucket="")


class ReclaimIsDelegatedTest(unittest.TestCase):

    def test_an_unfinalized_log_is_never_purged(self):
        """Track P's contract: the inline copy is reclaimed at FINALIZE. An
        editable log keeps it, exactly as it does in production today."""
        stats, docs, _, _ = _run([_logbook()], execute=True)
        self.assertEqual(stats["reclaim_skipped_not_finalized"], 1)
        self.assertEqual(stats["inline_copies_reclaimed"], 0)
        self.assertEqual(_first_photo(docs[0])["base64"], FULL_B64)

    def test_a_finalized_photo_that_satisfies_the_three_conditions_is_reclaimed(self):
        photo = {
            "base64": FULL_B64, "enhance_status": "done",
            "enhanced_r2_key": OLD_ENH, "thumb_r2_key": OLD_THUMB,
        }
        r2 = _FakeR2({OLD_ENH: b"E", OLD_THUMB: THUMB_BYTES})
        stats, docs, r2, _ = _run(
            [_logbook(photo, is_locked=True)], execute=True, r2=r2,
        )
        out = _first_photo(docs[0])
        self.assertEqual(stats["inline_copies_reclaimed"], 1)
        self.assertNotIn("base64", out)
        # Written by THE PURGE, from the bytes R2 returned — not by this script.
        self.assertEqual(out["thumb_base64"], THUMB_B64)
        self.assertEqual(set(r2.heads), {OLD_ENH, OLD_THUMB})

    def test_a_photo_r2_cannot_confirm_keeps_its_inline_copy(self):
        photo = {
            "base64": FULL_B64, "enhance_status": "done",
            "enhanced_r2_key": OLD_ENH, "thumb_r2_key": OLD_THUMB,
        }
        stats, docs, _, _ = _run(
            [_logbook(photo, is_locked=True)], execute=True, r2=_FakeR2(),
        )
        self.assertEqual(stats["inline_copies_reclaimed"], 0)
        self.assertEqual(_first_photo(docs[0])["base64"], FULL_B64)

    def test_an_unenhanced_photo_keeps_its_inline_copy(self):
        stats, docs, _, _ = _run([_logbook(is_locked=True)], execute=True)
        self.assertEqual(stats["inline_copies_reclaimed"], 0)
        self.assertEqual(_first_photo(docs[0])["base64"], FULL_B64)

    def test_the_script_calls_track_p_rather_than_reimplementing_it(self):
        calls = []
        real = server._purge_finalized_photo_base64

        async def _spy(logbook_id, doc):
            calls.append(logbook_id)
            return await real(logbook_id, doc)

        with patch.object(server, "_purge_finalized_photo_base64", _spy):
            _run([_logbook(is_locked=True)], execute=True)
        self.assertEqual(calls, ["lb1"])

    def test_the_script_itself_never_writes_thumb_base64(self):
        """Source-level, because the property is 'no code path here can'."""
        src = Path(bf.__file__).read_text(encoding="utf-8")
        writes = [
            ln for ln in src.splitlines()
            if "thumb_base64" in ln and not ln.lstrip().startswith("#")
            and "NEVER" not in ln
        ]
        self.assertEqual(writes, [], f"thumb_base64 is touched: {writes}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
