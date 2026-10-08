"""Every photo that reaches a log is enhanced -- not only the ones POST saw.

THE GAP. `_enhance_logbook_photos` was scheduled from POST /logbooks alone. The
CP's real path -- Save Draft, then Submit -- arrives as a PUT; the offline drain
pushes with a PUT; a photo added to a filed log goes through the append route.
None of the three ran it, so a photo that reached a log through any of them
kept its R2 original and nothing else. On 2026-10-08: 134 filed photos on 588
Thomas, and the site kiosk loading each FULL-SIZE ORIGINAL into an 80x60 tile.

Operator's ruling, 2026-10-08: generate thumbnails for them. This file pins the
forward fix (all three paths schedule the pass) and the one-shot backfill.
"""
from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402
from scripts import backfill_photo_thumbnails as BF  # noqa: E402
from tests.source_text import code_of  # noqa: E402

USER = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "companyA",
        "account_status": "approved", "assigned_projects": ["projA"]}
PROJECT = {"_id": "projA", "company_id": "companyA", "name": "588 Thomas"}
ORIG = "logbook-photos/projA/cap_1/cap_1.jpg"
PATCH = {"enhanced_r2_key": ORIG[:-4] + "-enhanced.jpg",
         "thumb_r2_key": ORIG[:-4] + "-thumb.jpg", "enhance_status": "done",
         "thumb_base64": "VEhVTUI="}


# ── PUT schedules the pass ─────────────────────────────────────────────────

def _put(update_body):
    """update_logbook against doubles; returns the recorded enhance calls."""
    calls = []

    async def fake_enhance(logbook_id, project_id, retry_failed=True):
        calls.append((logbook_id, project_id, retry_failed))

    stored = {"_id": "lb1", "project_id": "projA", "log_type": "daily_jobsite",
              "status": "draft", "is_locked": False, "date": "2026-10-08",
              "data": {"activities": [{"photos": [{"original_r2_key": ORIG}]}]}}

    async def find_one(q, *a, **kw):
        return dict(stored)

    async def update_one(q, upd, *a, **kw):
        r = MagicMock()
        r.matched_count = 1
        return r

    db = MagicMock()
    db.logbooks.find_one = AsyncMock(side_effect=find_one)
    db.logbooks.update_one = AsyncMock(side_effect=update_one)
    db.projects.find_one = AsyncMock(return_value=dict(PROJECT))

    async def go():
        await server.update_logbook(
            logbook_id="lb1", data=server.LogbookUpdate(**update_body),
            current_user=USER)
        await asyncio.sleep(0)     # let the scheduled task start

    with patch.object(server, "db", db), \
         patch.object(server, "audit_log", AsyncMock()), \
         patch.object(server, "_remember_other_activities", AsyncMock()), \
         patch.object(server, "_remember_other_locations", AsyncMock()), \
         patch.object(server, "_enhance_logbook_photos", fake_enhance):
        asyncio.run(go())
    return calls


class PutSchedulesThePass(unittest.TestCase):

    def test_a_save_that_carries_data_enhances_its_photos(self):
        calls = _put({"data": {"activities": [{"photos": [{"original_r2_key": ORIG}]}]}})
        self.assertEqual(calls, [("lb1", "projA", False)])

    def test_and_does_not_retry_failures_on_every_autosave(self):
        calls = _put({"data": {"activities": []}})
        self.assertIs(calls[0][2], False)

    def test_a_save_without_data_schedules_nothing(self):
        """No `data` in the request, so no photo can have arrived with it."""
        self.assertEqual(_put({"cp_name": "Casey CP"}), [])


class TheAppendRouteSchedulesIt(unittest.TestCase):
    """49 of the 134 came in through /logbooks/{id}/activity-photo. Pinned on
    the handler's code (comments stripped): driving the route needs a real
    multipart upload into R2, and what matters is that the call is there."""

    def test_the_call_is_in_the_handler(self):
        code = code_of("server.py")
        i = code.index("async def append_activity_photo(")
        j = code.index("\nasync def ", i + 1)
        body = code[i:j]
        self.assertTrue("_enhance_logbook_photos(" in body,
                        "the append route does not schedule the enhance pass")
        self.assertTrue("retry_failed=False" in body,
                        "the append route would retry failed enhances")


# ── the pass itself ────────────────────────────────────────────────────────

def _walk(photos, retry_failed):
    doc = {"_id": "lb1", "data": {"activities": [{"photos": copy.deepcopy(photos)}]}}
    enhanced = []

    def fake_orig(key):
        enhanced.append(key)
        return dict(PATCH)

    db = MagicMock()
    db.logbooks.find_one = AsyncMock(return_value=doc)
    db.logbooks.update_one = AsyncMock()
    with patch.object(server, "db", db), \
         patch.object(server, "to_query_id", lambda x: x), \
         patch.object(server, "_enhance_r2_original_sync", fake_orig):
        asyncio.run(server._enhance_logbook_photos("lb1", "projA",
                                                   retry_failed=retry_failed))
    return enhanced


class RetryFailedIsTheCallersChoice(unittest.TestCase):
    PHOTOS = [{"original_r2_key": "a.jpg", "enhance_status": "failed"},
              {"original_r2_key": "b.jpg"},
              {"original_r2_key": "c.jpg", "enhance_status": "done"}]

    def test_post_still_retries_a_failure(self):
        self.assertEqual(_walk(self.PHOTOS, True), ["a.jpg", "b.jpg"])

    def test_put_and_append_do_not(self):
        self.assertEqual(_walk(self.PHOTOS, False), ["b.jpg"])


# ── the one-shot backfill ──────────────────────────────────────────────────

def _log(**over):
    doc = {"_id": "lb1", "project_id": "projA", "date": "2026-09-24",
           "status": "submitted", "is_deleted": False,
           "data": {"activities": [{"photos": [
               {"original_r2_key": ORIG},                         # needs one
               {"original_r2_key": "x.jpg", "thumb_r2_key": "x-thumb.jpg",
                "enhance_status": "done"},                         # has one
               {"base64": "QUJD"},                                  # not ours
               {"uri": "file:///phone.jpg", "upload_pending": True},  # not ours
           ]}]}}
    doc.update(over)
    return doc


class WhichPhotosItTakes(unittest.TestCase):

    def test_only_captured_photos_with_no_thumbnail(self):
        self.assertEqual(BF.photos_needing_a_thumbnail(_log()),
                         [{"ai": 0, "pi": 0, "original_r2_key": ORIG}])

    def test_an_enhanced_photo_is_left_alone_even_without_a_thumb_key(self):
        doc = _log()
        doc["data"]["activities"][0]["photos"][0]["enhance_status"] = "done"
        self.assertEqual(BF.photos_needing_a_thumbnail(doc), [])


class _Logs:
    def __init__(self, docs, refuse_writes=False):
        self.docs = docs
        self.writes = []
        self.refuse = refuse_writes

    def find(self, q, *a, **k):
        docs = self.docs

        class _C:
            async def to_list(self, n=None):
                return [copy.deepcopy(d) for d in docs]
        return _C()

    async def update_one(self, q, u, **k):
        if self.refuse:
            raise AssertionError("a dry run wrote")
        self.writes.append((q, u))
        r = MagicMock()
        r.matched_count = 1
        return r


class _DB:
    def __init__(self, logs):
        self.logbooks = logs


def _backfill(db, execute, enhance=None):
    r2 = MagicMock()
    r2.head_object = MagicMock(return_value={"ContentLength": 4_200_000})
    with patch.object(server, "_r2_client", r2), \
         patch.object(server, "R2_BUCKET_NAME", "bucket"), \
         patch.object(server, "to_query_id", lambda x: x), \
         patch.object(server, "_enhance_r2_original_sync",
                      enhance or (lambda key: dict(PATCH))):
        return asyncio.run(BF.run(db, execute=execute))


class TheBackfill(unittest.TestCase):

    def test_a_dry_run_writes_nothing_and_reports_the_photo(self):
        stats = _backfill(_DB(_Logs([_log()], refuse_writes=True)), execute=False)
        self.assertEqual(stats["photos"], 1)
        self.assertEqual(stats["original_bytes"], 4_200_000)
        self.assertEqual(stats["enhanced"], 0)

    def test_execute_writes_the_pass_patch_on_that_photos_path_only(self):
        logs = _Logs([_log()])
        stats = _backfill(_DB(logs), execute=True)
        self.assertEqual(stats["enhanced"], 1)
        self.assertEqual(len(logs.writes), 1)
        q, u = logs.writes[0]
        f = "data.activities.0.photos.0"
        # CONDITIONAL: still this original at this position, still no thumb.
        self.assertEqual(q[f"{f}.original_r2_key"], ORIG)
        self.assertEqual(q[f"{f}.thumb_r2_key"], {"$exists": False})
        self.assertEqual(u["$set"][f"{f}.thumb_r2_key"], PATCH["thumb_r2_key"])
        self.assertEqual(u["$set"][f"{f}.enhance_status"], "done")
        # NOTHING OUTSIDE THE PHOTO: the filed record's version does not move.
        self.assertTrue(all(k.startswith(f + ".") for k in u["$set"]))

    def test_a_failed_enhance_is_stamped_like_the_pass_does(self):
        def boom(key):
            raise RuntimeError("undecodable")
        logs = _Logs([_log()])
        stats = _backfill(_DB(logs), execute=True, enhance=boom)
        self.assertEqual(stats["failed"], 1)
        _q, u = logs.writes[0]
        self.assertEqual(u["$set"]["data.activities.0.photos.0.enhance_status"], "failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
