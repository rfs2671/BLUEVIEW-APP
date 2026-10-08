"""A day's photo thumbnails leave the site device's download and arrive when the
sheet is opened.

Operator's ruling, 2026-10-08, on the report that `thumb_base64` -- the ~400px
copy kept inline after finalize -- was the last thing making a day heavy on the
device: 555,232 of the heaviest day's bytes, one daily jobsite log of 13 photos.

  * `view=text&photos=deferred` replaces each photo's `thumb_base64` with
    `thumb_base64_deferred: true` in the day download.
  * `/logbooks/{id}/signature-images?include=photos` serves them, keyed by the
    same path, beside the signature marks; the device stores both on disk.
  * OPT-IN BOTH WAYS. The app build phones run today asks for `view=text` and
    knows nothing of a deferred thumbnail; it must keep getting them inline.
  * NOTHING STORED CHANGES. The inline copy stays on the record as the
    last-resort copy and is still never removed.

Every production photo carrying `thumb_base64` also has an R2 thumbnail
(census 2026-10-08: 205 of 205), so nothing loses its served copy either.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tests.test_images_load_when_the_sheet_is_opened import (  # noqa: E402
    THUMB_B64, DAY, SITE_USER, _FakeDb, _Logbooks, _daily, _docs, _get, _rows,
)

PATH0 = "data.activities.0.photos.0.thumb_base64"


def _daily_two_photos():
    d = _daily()
    d["_id"] = "lb_daily2"
    d["data"]["activities"].append({
        "activity_id": "act_2", "company": "Sub B",
        "photos": [{"original_r2_key": "o1"}, {"thumb_base64": THUMB_B64 + "B"}],
    })
    return d


def _images(docs, logbook_id, include=None):
    logbooks = _Logbooks(docs)
    db = _FakeDb(logbooks)

    async def _fake_user():
        return SITE_USER

    ov = server.app.dependency_overrides
    ov[server.get_current_user] = _fake_user
    q = f"?include={include}" if include else ""
    try:
        with patch.object(server, "db", db):
            r = TestClient(server.app).get(
                f"/api/logbooks/{logbook_id}/signature-images{q}")
    finally:
        ov.clear()
    return r


class TheOptInDayHoldsThumbnailsBack(unittest.TestCase):

    def test_view_text_with_photos_deferred_flags_every_thumbnail(self):
        r, _ = _get([_daily_two_photos()], f"?date={DAY}&view=text&photos=deferred")
        self.assertEqual(r.status_code, 200)
        acts = _rows(r.json())["lb_daily2"]["data"]["activities"]
        p0 = acts[0]["photos"][0]
        self.assertNotIn("thumb_base64", p0)
        self.assertIs(p0.get("thumb_base64_deferred"), True)
        self.assertNotIn("thumb_base64", acts[1]["photos"][1])
        self.assertIs(acts[1]["photos"][1].get("thumb_base64_deferred"), True)

    def test_a_photo_with_no_inline_copy_gets_no_flag(self):
        """Nothing is owed for a photo that never had an inline thumbnail."""
        r, _ = _get([_daily_two_photos()], f"?date={DAY}&view=text&photos=deferred")
        p = _rows(r.json())["lb_daily2"]["data"]["activities"][1]["photos"][0]
        self.assertEqual(p, {"original_r2_key": "o1"})

    def test_the_heavy_bytes_actually_leave_the_body(self):
        r, _ = _get([_daily_two_photos()], f"?date={DAY}&view=text&photos=deferred")
        self.assertNotIn(THUMB_B64, r.text)


class TheAppPhonesRunTodayIsUntouched(unittest.TestCase):
    """OPT-IN. Each of these is a request today's app, or an older one, makes."""

    def test_view_text_alone_keeps_the_thumbnails(self):
        r, _ = _get([_daily()], f"?date={DAY}&view=text")
        p = _rows(r.json())["lb_daily"]["data"]["activities"][0]["photos"][0]
        self.assertEqual(p.get("thumb_base64"), THUMB_B64)
        self.assertNotIn("thumb_base64_deferred", p)

    def test_whole_documents_keep_them(self):
        r, _ = _get([_daily()], f"?date={DAY}")
        p = _rows(r.json())["lb_daily"]["data"]["activities"][0]["photos"][0]
        self.assertEqual(p.get("thumb_base64"), THUMB_B64)

    def test_photos_deferred_without_view_text_keeps_them(self):
        """The flag rides the text view only, like the signature deferral."""
        r, _ = _get([_daily()], f"?date={DAY}&photos=deferred")
        p = _rows(r.json())["lb_daily"]["data"]["activities"][0]["photos"][0]
        self.assertEqual(p.get("thumb_base64"), THUMB_B64)

    def test_the_signature_deferral_is_unchanged_beside_it(self):
        r, _ = _get(_docs(), f"?date={DAY}&view=text&photos=deferred")
        pre = next(v for v in _rows(r.json()).values()
                   if v.get("log_type") == "preshift_signin")
        flagged = [w for w in pre["data"]["workers"] if w.get("worker_signature_deferred")]
        self.assertTrue(flagged, "the signature marks are still deferred")


class NothingStoredChanges(unittest.TestCase):

    def test_the_driver_row_is_not_mutated(self):
        doc = _daily_two_photos()
        before = copy.deepcopy(doc)
        out = server._defer_photo_thumbs(doc)
        self.assertEqual(doc, before)
        self.assertIsNot(out, doc)

    def test_a_record_with_no_thumbnail_is_returned_as_is(self):
        doc = {"data": {"activities": [{"photos": [{"original_r2_key": "o"}]}]}}
        self.assertIs(server._defer_photo_thumbs(doc), doc)


class TheRecordReadServesThemOnRequest(unittest.TestCase):

    def test_include_photos_returns_them_by_path(self):
        r = _images([_daily_two_photos()], "lb_daily2", include="photos")
        self.assertEqual(r.status_code, 200)
        photos = r.json().get("photos")
        self.assertEqual(sorted(photos),
                         [PATH0, "data.activities.1.photos.1.thumb_base64"])
        self.assertEqual(photos[PATH0], THUMB_B64)

    def test_without_include_the_body_is_what_it_was(self):
        r = _images([_daily_two_photos()], "lb_daily2")
        self.assertNotIn("photos", r.json())

    def test_the_paths_match_what_the_day_flagged(self):
        """The address the device drew a photo from is the address it asks
        for -- the protocol's whole contract."""
        day, _ = _get([_daily_two_photos()], f"?date={DAY}&view=text&photos=deferred")
        acts = _rows(day.json())["lb_daily2"]["data"]["activities"]
        flagged = sorted(
            f"data.activities.{ai}.photos.{pi}.thumb_base64"
            for ai, a in enumerate(acts) for pi, p in enumerate(a["photos"])
            if p.get("thumb_base64_deferred"))
        served = sorted(_images([_daily_two_photos()], "lb_daily2",
                                include="photos").json()["photos"])
        self.assertEqual(flagged, served)


if __name__ == "__main__":
    unittest.main(verbosity=2)
