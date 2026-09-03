"""A PHOTOGRAPH MAY BE ADDED TO A FILED LOG. NOTHING ELSE MAY.

THE RULING. Photographs are not DOB-required daily log content -- BC 3301.2
does not ask for them -- so treating a photo addition as an amendment to a
filed compliance record is wrong on the merits. The statutory content the CP
attested to (crews, headcounts, work performed, weather) stays immutable; a
later photograph of that same work is appended in place, immediately, by
anyone who can already see the log, with no reason given and no count limit,
and `updated_at` moves so a reader knows something changed.

WHY THIS CANNOT GO THROUGH PUT /api/logbooks/{id}. That route refuses every
`data` write once the stored status is "submitted" (409
FILED_LOG_DATA_IMMUTABLE, test_filed_log_data_immutable.py), and that guard is
correct: two daily_jobsite records at 588 Thomas were silently overwritten
through it. A server-side DIFF of the client's blob is not a way around it
either -- the blob is not a faithful echo of the stored document (hydrate
reconciles crews on any submitted-but-unlocked log, and photoForPayload is
lossy and conditional), so "only the photos changed" is not a question the
server can answer by comparing.

THE SHAPE THAT IS SAFE IS ALREADY IN THIS FILE, TWICE.
_purge_finalized_photo_base64 and _enhance_logbook_photos both write into
data.activities[].photos[] on a log that is submitted AND finalized. Both are
legitimate for the same three reasons, and this endpoint inherits all three:

  FIELD-SCOPED     the write names one path under photos[], never `data`
  SERVER-CONSTRUCTED   every value written is minted here, from bytes
  NO CLIENT BLOB   the request carries image bytes and two ids, and nothing
                   else -- no photo object, no `data`, no array index

IDENTITY, NOT POSITION. The push is keyed on `activity_id` through
arrayFilters. An index stops naming the same row the moment one is added,
removed or reordered, and this endpoint is reached hours after the CP stopped
looking at the screen.

AND THE ROWS IT CANNOT REACH. A crew row saved by a build older than
2026-08-10 carries no `activity_id` at all and nothing backfills it, so no id
the client can send will ever match one. Those are REFUSED, by name, rather
than pushed somewhere plausible.

THE STAMP IS THE POINT. A photograph appended after signing is
distinguishable on the record -- added_at / added_by / added_after_filing --
and the report and its PDF SAY SO. Without that the record silently asserts
the photo was in front of the CP when he attested, which is the one claim this
feature must not manufacture.

    python -m pytest tests/test_filed_log_photo_append.py -q
"""

from __future__ import annotations

import asyncio
import ast
import base64 as _b64
import copy
import io
import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

ROUTE = "/api/logbooks/{logbook_id}/activity-photo"
URL = "/api/logbooks/lb1/activity-photo"

# A real, decodable 1x1 JPEG: the magic-byte check and Pillow both accept it.
TINY_JPEG = _b64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwh"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAAR"
    "CAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWG"
    "h4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
    "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iiigD//2Q=="
)
NOT_AN_IMAGE = b"%PDF-1.4\n%\xc3\xa4\xc3\xbc\nnot a photograph at all"

PROJECT = {"_id": "proj1", "name": "588 Thomas S Boyland Street",
           "company_id": "co_test", "is_deleted": False}

CP_USER = {"_id": "cp_1", "id": "cp_1", "role": "cp", "company_id": "co_test",
           "account_status": "approved", "full_name": "Casey CP",
           "assigned_projects": ["proj1"]}

AID = "act_1754500000000_0"
PID = "cap_1754500000000_0_9"
KEY = f"logbook-photos/proj1/{AID}/{PID}.jpg"

# What the CP attested to. Every assertion about immutability is made against
# a deep copy of this, so a stray write anywhere in `data` is visible.
STATUTORY = {
    "weather": {"conditions": "Cloudy", "temp_f": 61},
    "activities": [
        {"activity_id": "act_other", "crew_id": "C1", "company": "Kestrel Electric",
         "trade": "Electrical", "num_workers": "4", "work_description": "branch rough-in",
         "work_locations": "3rd floor", "photos": [{"original_r2_key": "old/a.jpg"}]},
        {"activity_id": AID, "crew_id": "C2", "company": "Acme Shoring",
         "trade": "Concrete", "num_workers": "3", "work_description": "shoring",
         "work_locations": "cellar",
         "photos": [{"original_r2_key": "old/b.jpg", "timestamp": "2026-08-12T13:00:00Z"}]},
    ],
}


def _filed_log(**over):
    doc = {
        "_id": "lb1", "project_id": "proj1", "company_id": "co_test",
        "log_type": "daily_jobsite", "date": "2026-08-12", "is_deleted": False,
        "status": "submitted", "is_locked": False,
        "cp_signature": {"paths": "p", "affirmed": True}, "cp_name": "Casey CP",
        "created_at": datetime(2026, 8, 12, 13, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 8, 12, 19, tzinfo=timezone.utc),
        "data": copy.deepcopy(STATUTORY),
    }
    doc.update(over)
    return doc


# ══════════════════════════════════════════════════════════════════════════
#  Doubles that actually implement the two mongo features this depends on:
#  an $elemMatch precondition, and a $push through arrayFilters.
# ══════════════════════════════════════════════════════════════════════════

class _Result:
    def __init__(self, matched=1, modified=1):
        self.matched_count = matched
        self.modified_count = modified
        self.inserted_id = "x"


def _elem_ok(elem, cond):
    """One $elemMatch clause against one array element."""
    for k, want in cond.items():
        if k == "activity_id":
            if elem.get("activity_id") != want:
                return False
            continue
        if k == "photos.original_r2_key":
            have = [p.get("original_r2_key") for p in (elem.get("photos") or [])
                    if isinstance(p, dict)]
            if isinstance(want, dict) and "$ne" in want:
                if want["$ne"] in have:
                    return False
                continue
            if want not in have:
                return False
            continue
        raise AssertionError(f"double does not model $elemMatch key {k!r}")
    return True


class _Logbooks:
    """Holds one document and applies the update the server really sends."""

    def __init__(self, doc=None):
        self.doc = doc
        self.updates = []

    async def find_one(self, query=None, *a, **k):
        if self.doc is None:
            return None
        q = query or {}
        if "_id" in q and q["_id"] != self.doc["_id"]:
            return None
        return copy.deepcopy(self.doc)

    async def update_one(self, q, u, *a, **kw):
        self.updates.append((copy.deepcopy(q), copy.deepcopy(u), dict(kw)))
        if self.doc is None:
            return _Result(0, 0)
        # precondition
        em = (q.get("data.activities") or {}).get("$elemMatch")
        if em is not None:
            rows = (self.doc.get("data") or {}).get("activities") or []
            if not any(_elem_ok(r, em) for r in rows if isinstance(r, dict)):
                return _Result(0, 0)
        filters = kw.get("array_filters") or []
        for path, val in (u.get("$set") or {}).items():
            if "$[" in path:
                raise AssertionError("double does not model a filtered $set")
            cur = self.doc
            parts = path.split(".")
            for p in parts[:-1]:
                cur = cur.setdefault(p, {})
            cur[parts[-1]] = val
        for path, val in (u.get("$push") or {}).items():
            m = re.fullmatch(r"data\.activities\.\$\[(\w+)\]\.photos", path)
            assert m, f"unexpected $push path {path!r}"
            ident = m.group(1)
            want = None
            for f in filters:
                for fk, fv in f.items():
                    if fk == f"{ident}.activity_id":
                        want = fv
            assert want is not None, f"no arrayFilter bound {ident!r}"
            hit = 0
            for row in (self.doc.get("data") or {}).get("activities") or []:
                if isinstance(row, dict) and row.get("activity_id") == want:
                    row.setdefault("photos", []).append(copy.deepcopy(val))
                    hit += 1
            if not hit:
                return _Result(0, 0)
        return _Result(1, 1)


class _Coll:
    def __init__(self, one=None):
        self.one = one

    async def find_one(self, *a, **k):
        return copy.deepcopy(self.one)

    async def update_one(self, *a, **k):
        return _Result()

    async def insert_one(self, doc, *a, **k):
        return _Result()

    async def count_documents(self, *a, **k):
        return 0


class _DB:
    def __init__(self, logbooks, project=PROJECT):
        self._c = {"logbooks": logbooks, "projects": _Coll(project)}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _Coll()
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


class _FakeR2:
    def __init__(self, objects=None, fail=False):
        self.objects = dict(objects or {})
        self.puts = []
        self.fail = fail

    def put_object(self, Bucket=None, Key=None, Body=None, ContentType=None, **k):  # noqa: N803
        if self.fail:
            raise RuntimeError("R2 unreachable")
        self.puts.append((Key, ContentType, len(Body or b"")))
        self.objects[Key] = Body
        return {}

    def get_object(self, Bucket=None, Key=None, **k):  # noqa: N803
        if Key not in self.objects:
            raise RuntimeError(f"404 NoSuchKey: {Key}")
        return {"Body": io.BytesIO(self.objects[Key])}


def _post(doc, *, r2=None, user=CP_USER, activity_id=AID, photo_id=PID,
          content=TINY_JPEG, declared="image/jpeg", bucket="bv-bucket",
          extra=None, project=PROJECT):
    """Drive the endpoint. Returns (response, logbooks-double)."""
    lb = _Logbooks(doc)
    r2 = _FakeR2() if r2 is None else r2

    async def _fake_user():
        return user

    ov = server.app.dependency_overrides
    ov[server.get_current_user] = _fake_user
    ov[server.require_approved] = _fake_user
    try:
        with patch.object(server, "db", _DB(lb, project)), \
             patch.object(server, "to_query_id", lambda x: x), \
             patch.object(server, "_r2_client", r2), \
             patch.object(server, "R2_BUCKET_NAME", bucket):
            data = {"activity_id": activity_id, "photo_id": photo_id}
            data.update(extra or {})
            c = TestClient(server.app)
            resp = c.post(
                URL, data=data,
                files={"file": (f"{photo_id}.jpg", content, declared)},
            )
    finally:
        ov.clear()
    return resp, lb


def _photos(lb, index=1):
    return ((lb.doc.get("data") or {}).get("activities") or [])[index].get("photos") or []


# ══════════════════════════════════════════════════════════════════════════
#  1. THE APPEND ITSELF
# ══════════════════════════════════════════════════════════════════════════

class APhotoIsAppendedToAFiledLog(unittest.TestCase):

    def test_a_filed_log_accepts_the_photo(self):
        """The whole point. PUT would answer 409 FILED_LOG_DATA_IMMUTABLE for
        this same document; this route is the field-scoped exception."""
        resp, lb = _post(_filed_log())
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(_photos(lb)), 2)
        self.assertEqual(_photos(lb)[1]["original_r2_key"], KEY)

    def test_a_finalized_locked_log_accepts_it_too(self):
        """_purge_finalized_photo_base64 already writes into photos[] on a log
        that is submitted AND locked. A photograph is not an amendment, and
        the lock is about the CP's attested content."""
        resp, lb = _post(_filed_log(is_locked=True))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(_photos(lb)), 2)

    def test_the_bytes_land_in_r2_under_the_capture_key(self):
        r2 = _FakeR2()
        resp, _ = _post(_filed_log(), r2=r2)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([p[0] for p in r2.puts], [KEY])
        self.assertEqual(r2.objects[KEY], TINY_JPEG)

    def test_a_retry_overwrites_the_object_and_does_not_append_twice(self):
        """The key is a pure function of (project, activity, photo), so the
        object is overwritten. The DOCUMENT must be idempotent too, or a
        dropped connection leaves two tiles of one photograph on the record."""
        doc = _filed_log()
        r2 = _FakeR2()
        first, lb = _post(doc, r2=r2)
        self.assertEqual(first.status_code, 200)
        second, lb2 = _post(lb.doc, r2=r2)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(len(_photos(lb2)), 2, "the retry appended a duplicate")
        self.assertEqual(len(r2.objects), 1)

    def test_there_is_no_count_limit(self):
        """The per-subcontractor cap is a client-side capture ergonomic. A
        filed record refusing evidence because a row already holds forty
        photographs is not a rule anyone made."""
        doc = _filed_log()
        doc["data"]["activities"][1]["photos"] = [
            {"original_r2_key": f"old/{i}.jpg"} for i in range(40)
        ]
        resp, lb = _post(doc)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(_photos(lb)), 41)


# ══════════════════════════════════════════════════════════════════════════
#  2. NOTHING ELSE MOVES
# ══════════════════════════════════════════════════════════════════════════

class TheStatutoryContentIsUntouched(unittest.TestCase):

    def test_crews_headcounts_work_and_weather_are_byte_identical_after(self):
        resp, lb = _post(_filed_log())
        self.assertEqual(resp.status_code, 200, resp.text)
        after = lb.doc["data"]
        self.assertEqual(after["weather"], STATUTORY["weather"])
        for i, row in enumerate(after["activities"]):
            for field in ("activity_id", "crew_id", "company", "trade",
                          "num_workers", "work_description", "work_locations"):
                self.assertEqual(
                    row.get(field), STATUTORY["activities"][i].get(field),
                    f"activity {i}.{field} moved",
                )

    def test_the_untargeted_row_gains_nothing(self):
        _, lb = _post(_filed_log())
        self.assertEqual(len(_photos(lb, 0)), 1)

    def test_the_existing_photos_on_the_targeted_row_survive(self):
        _, lb = _post(_filed_log())
        self.assertEqual(_photos(lb)[0], STATUTORY["activities"][1]["photos"][0])

    def test_the_only_data_write_is_the_photos_push(self):
        """Measured on the update the server actually sends, not on the
        result. `data` is never $set; one filtered $push under photos[] is the
        entire footprint inside `data`."""
        _, lb = _post(_filed_log())
        pushes = []
        for _q, u, _kw in lb.updates:
            for path in (u.get("$set") or {}):
                self.assertFalse(
                    path == "data" or path.startswith("data."),
                    f"the update writes {path!r} inside data",
                )
            self.assertEqual(u.get("$unset"), None)
            pushes += list((u.get("$push") or {}).keys())
        self.assertEqual(pushes, ["data.activities.$[act].photos"])

    def test_updated_at_moves_so_a_reader_knows_something_changed(self):
        before = _filed_log()["updated_at"]
        _, lb = _post(_filed_log())
        self.assertGreater(lb.doc["updated_at"], before)

    def test_status_and_the_lock_are_not_touched(self):
        _, lb = _post(_filed_log(is_locked=True))
        self.assertEqual(lb.doc["status"], "submitted")
        self.assertIs(lb.doc["is_locked"], True)


# ══════════════════════════════════════════════════════════════════════════
#  3. IDENTITY, NEVER POSITION
# ══════════════════════════════════════════════════════════════════════════

class ThePushIsKeyedOnIdentity(unittest.TestCase):

    def test_it_reaches_the_named_row_not_the_first_one(self):
        """AID is the SECOND row. An index-keyed push would put a photograph
        of Acme's shoring under Kestrel's electrical rough-in."""
        _, lb = _post(_filed_log())
        self.assertEqual(len(_photos(lb, 0)), 1)
        self.assertEqual(len(_photos(lb, 1)), 2)

    def test_the_update_path_carries_no_numeric_index(self):
        _, lb = _post(_filed_log())
        for _q, u, kw in lb.updates:
            for path in list((u.get("$push") or {})) + list((u.get("$set") or {})):
                self.assertFalse(
                    re.search(r"activities\.\d+", path),
                    f"positional path {path!r}",
                )
            if u.get("$push"):
                self.assertTrue(kw.get("array_filters"), "no arrayFilters used")

    def test_a_row_reordered_between_read_and_write_still_gets_it(self):
        """The read hands back index 1; the write must not depend on that."""
        doc = _filed_log()
        lb = _Logbooks(doc)
        original_find = lb.find_one
        state = {"n": 0}

        async def _reorder_after_read(query=None, *a, **k):
            out = await original_find(query, *a, **k)
            state["n"] += 1
            if state["n"] == 1 and lb.doc:
                lb.doc["data"]["activities"].reverse()
            return out

        lb.find_one = _reorder_after_read

        async def _fake_user():
            return CP_USER

        ov = server.app.dependency_overrides
        ov[server.get_current_user] = _fake_user
        ov[server.require_approved] = _fake_user
        try:
            with patch.object(server, "db", _DB(lb)), \
                 patch.object(server, "to_query_id", lambda x: x), \
                 patch.object(server, "_r2_client", _FakeR2()), \
                 patch.object(server, "R2_BUCKET_NAME", "bv-bucket"):
                resp = TestClient(server.app).post(
                    URL, data={"activity_id": AID, "photo_id": PID},
                    files={"file": ("p.jpg", TINY_JPEG, "image/jpeg")},
                )
        finally:
            ov.clear()
        self.assertEqual(resp.status_code, 200, resp.text)
        row = next(r for r in lb.doc["data"]["activities"]
                   if r.get("activity_id") == AID)
        self.assertEqual(len(row["photos"]), 2)


# ══════════════════════════════════════════════════════════════════════════
#  4. THE ROWS IT CANNOT REACH ARE REFUSED BY NAME
# ══════════════════════════════════════════════════════════════════════════

class ALegacyRowIsRefused(unittest.TestCase):

    def test_a_log_whose_rows_predate_activity_id_is_refused(self):
        """Nothing backfills activity_id, so no id the client sends can ever
        match. Saying that is better than pushing at a plausible index."""
        doc = _filed_log()
        for row in doc["data"]["activities"]:
            row.pop("activity_id")
        resp, lb = _post(doc)
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "ACTIVITY_HAS_NO_IDENTITY")
        self.assertEqual(lb.updates, [])

    def test_that_refusal_stores_nothing_at_all(self):
        doc = _filed_log()
        for row in doc["data"]["activities"]:
            row.pop("activity_id")
        r2 = _FakeR2()
        _post(doc, r2=r2)
        self.assertEqual(r2.puts, [], "bytes were parked for a row it cannot reach")

    def test_an_unknown_id_on_a_modern_log_is_a_plain_404(self):
        """Every row HAS an identity and none of them is this one — a
        different fact, and the client must be able to tell them apart."""
        resp, lb = _post(_filed_log(), activity_id="act_nope")
        self.assertEqual(resp.status_code, 404, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "ACTIVITY_NOT_FOUND")
        self.assertEqual(lb.updates, [])

    def test_a_missing_logbook_is_a_404(self):
        resp, _ = _post(None)
        self.assertEqual(resp.status_code, 404)


# ══════════════════════════════════════════════════════════════════════════
#  5. THE ROW IS MINTED HERE, FROM BYTES
# ══════════════════════════════════════════════════════════════════════════

class TheServerMintsTheRow(unittest.TestCase):

    def test_the_endpoint_accepts_no_photo_object_no_data_and_no_index(self):
        route = next(r for r in server.app.routes
                     if getattr(r, "path", "") == ROUTE)
        names = {f.name for f in route.dependant.body_params}
        self.assertEqual(names, {"activity_id", "photo_id", "file"})

    def test_the_stamps_are_present_and_server_shaped(self):
        _, lb = _post(_filed_log())
        photo = _photos(lb)[1]
        self.assertIs(photo["added_after_filing"], True)
        self.assertEqual(photo["added_by"], "cp_1")
        self.assertEqual(photo["added_by_name"], "Casey CP")
        self.assertIsInstance(photo["added_at"], datetime)
        self.assertEqual(photo["original_r2_key"], KEY)
        self.assertEqual(photo["photo_id"], PID)

    def test_a_client_cannot_forge_the_stamps(self):
        """Extra form fields are not a channel into the row."""
        _, lb = _post(_filed_log(), extra={
            "added_by": "somebody else", "added_after_filing": "false",
            "base64": "AAAA", "enhance_status": "done",
        })
        photo = _photos(lb)[1]
        self.assertEqual(photo["added_by"], "cp_1")
        self.assertIs(photo["added_after_filing"], True)
        self.assertNotIn("base64", photo)
        self.assertNotIn("enhance_status", photo)

    def test_a_draft_is_not_marked_added_after_filing(self):
        """The flag is a fact about the record, not about this route. On a log
        that has not been filed the photograph WAS present at attestation, and
        claiming otherwise would be the same lie in the other direction."""
        resp, lb = _post(_filed_log(status="draft", is_locked=False))
        self.assertEqual(resp.status_code, 200, resp.text)
        photo = _photos(lb)[1]
        self.assertNotIn("added_after_filing", photo)
        self.assertIsInstance(photo["added_at"], datetime)

    def test_the_response_carries_the_row_so_it_can_appear_immediately(self):
        resp, _ = _post(_filed_log())
        body = resp.json()
        self.assertEqual(body["original_r2_key"], KEY)
        self.assertEqual(body["activity_index"], 1)
        self.assertEqual(body["photo_index"], 1)
        self.assertIs(body["photo"]["added_after_filing"], True)


# ══════════════════════════════════════════════════════════════════════════
#  6. THE BYTES DECIDE WHAT THIS IS
# ══════════════════════════════════════════════════════════════════════════

class TheBytesDecide(unittest.TestCase):

    def test_a_pdf_declared_as_a_jpeg_is_refused(self):
        resp, lb = _post(_filed_log(), content=NOT_AN_IMAGE, declared="image/jpeg")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(lb.updates, [])

    def test_a_jpeg_declared_as_text_is_accepted_and_stored_as_a_jpeg(self):
        r2 = _FakeR2()
        resp, _ = _post(_filed_log(), r2=r2, declared="text/plain")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(r2.puts[0][1], "image/jpeg")

    def test_an_empty_upload_is_refused(self):
        resp, lb = _post(_filed_log(), content=b"")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(lb.updates, [])

    def test_an_oversized_upload_is_refused(self):
        big = TINY_JPEG + b"\x00" * (server._LOGBOOK_PHOTO_MAX_BYTES + 1)
        resp, lb = _post(_filed_log(), content=big)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(lb.updates, [])

    def test_blank_ids_are_refused_and_write_nothing(self):
        """A whitespace id reaches the handler and is refused there; a truly
        empty one never survives multipart encoding at all and is refused by
        the framework as missing. Both are 4xx and neither writes."""
        for kwargs in ({"activity_id": "   "}, {"photo_id": "  "},
                       {"photo_id": ""}, {"activity_id": ""}):
            resp, lb = _post(_filed_log(), **kwargs)
            self.assertIn(resp.status_code, (400, 422), f"{kwargs}: {resp.text}")
            self.assertEqual(lb.updates, [])


# ══════════════════════════════════════════════════════════════════════════
#  7. AUTHORIZATION AND STORAGE FAILURE
# ══════════════════════════════════════════════════════════════════════════

class TheGuards(unittest.TestCase):

    def test_the_route_declares_require_approved(self):
        """Cost-bearing: it puts an object in R2 on the platform's bill."""
        src = ast.parse((_BACKEND / "server.py").read_text(encoding="utf-8"))
        found = None
        for node in ast.walk(src):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and dec.args
                        and isinstance(dec.args[0], ast.Constant)
                        and dec.args[0].value == "/logbooks/{logbook_id}/activity-photo"):
                    found = dec
        self.assertIsNotNone(found, "the append route was not found")
        deps = ""
        for kw in found.keywords:
            if kw.arg == "dependencies":
                deps = ast.unparse(kw.value)
        self.assertIn("require_approved", deps)

    def test_the_guard_is_wired_not_merely_written(self):
        route = next(r for r in server.app.routes
                     if getattr(r, "path", "") == ROUTE)

        def _names(dep, seen=None):
            seen = seen if seen is not None else set()
            if dep.call is not None:
                seen.add(getattr(dep.call, "__name__", ""))
            for sub in dep.dependencies:
                _names(sub, seen)
            return seen

        self.assertIn("require_approved", _names(route.dependant))

    def test_it_authorizes_through_authorize_logbook_write(self):
        """The same helper update / finalize / amend use, so this route
        introduces no new authorization concept."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        body = src[src.index('@api_router.post(\n    "/logbooks/{logbook_id}/activity-photo"'):]
        body = body[:body.index("\n@api_router.")]
        self.assertIn("_authorize_logbook_write(logbook_id, current_user)", body)

    def test_a_cross_company_caller_is_refused_and_nothing_is_stored(self):
        outsider = {**CP_USER, "_id": "cp_x", "id": "cp_x",
                    "company_id": "co_other", "assigned_projects": []}
        r2 = _FakeR2()
        resp, lb = _post(_filed_log(), r2=r2, user=outsider)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(r2.puts, [])
        self.assertEqual(lb.updates, [])

    def test_an_assigned_cp_of_another_company_is_admitted(self):
        cp = {**CP_USER, "company_id": "co_contractor", "assigned_projects": ["proj1"]}
        resp, _ = _post(_filed_log(), user=cp)
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_unconfigured_storage_is_a_503_the_device_will_retry(self):
        resp, lb = _post(_filed_log(), bucket="")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(lb.updates, [])

    def test_a_storage_failure_is_a_502_and_writes_no_row(self):
        """No pointer is ever invented: a row naming an object that is not
        there asserts evidence that does not exist."""
        resp, lb = _post(_filed_log(), r2=_FakeR2(fail=True))
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(lb.updates, [])


# ══════════════════════════════════════════════════════════════════════════
#  8. THE RECORD SAYS SO — REPORT AND PDF
# ══════════════════════════════════════════════════════════════════════════

class _RCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _RColl:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, projection=None):
        return _RCursor(self.docs)

    async def find_one(self, query=None, projection=None, sort=None):
        return copy.deepcopy(self.docs[0]) if self.docs else None

    async def count_documents(self, query=None):
        return len(self.docs)


class _RDB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self[n]

    def __getitem__(self, n):
        if n not in self._c:
            self._c[n] = _RColl()
        return self._c[n]


def _report_with(photos):
    doc = {
        "_id": "lb_dj", "project_id": "proj1", "date": "2026-08-12",
        "log_type": "daily_jobsite", "is_deleted": False,
        "is_locked": True, "status": "submitted",
        "created_at": datetime(2026, 8, 12, 13, tzinfo=timezone.utc),
        "cp_signature": {"affirmed": True}, "cp_name": "Casey CP",
        "data": {"activities": [{
            "activity_id": AID, "crew_id": "C1", "company": "Acme Shoring",
            "trade": "Concrete", "num_workers": 3, "work_description": "shoring",
            "work_locations": "cellar", "photos": photos,
        }]},
    }
    db = _RDB()
    db.projects.docs = [{"_id": "proj1", "name": "588 Thomas S Boyland Street",
                         "address": "588 Thomas S Boyland St, Brooklyn"}]
    db.logbooks.docs = [doc]
    db.checkins.docs = []
    with patch.object(server, "db", db), \
         patch.object(server, "to_query_id", lambda x: x):
        return asyncio.run(server.generate_combined_report("proj1", "2026-08-12"))


ATTESTED = {"original_r2_key": "old/b.jpg", "enhance_status": "done"}
APPENDED = {
    "original_r2_key": KEY, "photo_id": PID, "enhance_status": "done",
    "added_after_filing": True, "added_by": "cp_1", "added_by_name": "Casey CP",
    "added_at": datetime(2026, 8, 14, 16, 5, tzinfo=timezone.utc),
}


class TheReportSaysWhichPhotosCameLater(unittest.TestCase):
    """WeasyPrint renders this same HTML, so the report and the PDF are one
    surface. Without the label the record silently asserts that every photo on
    it was in front of the CP when he signed."""

    def test_an_appended_photo_is_labelled(self):
        html = _report_with([dict(ATTESTED), dict(APPENDED)])
        self.assertIn("Added after filing", html)

    def test_the_label_names_who_added_it_and_when(self):
        html = _report_with([dict(ATTESTED), dict(APPENDED)])
        self.assertIn("Casey CP", html)
        self.assertIn("Aug 14, 2026", html)

    def test_a_photo_present_at_signing_carries_no_label(self):
        html = _report_with([dict(ATTESTED)])
        self.assertNotIn("Added after filing", html)

    def test_both_photos_still_render(self):
        html = _report_with([dict(ATTESTED), dict(APPENDED)])
        self.assertEqual(
            html.count("/api/reports/logbook-photo/lb_dj/0/"), 4,
            "two photos, each a thumb src and an enhanced href",
        )

    def test_the_added_by_name_is_escaped(self):
        photo = dict(APPENDED, added_by_name='Casey <script>alert(1)</script>')
        html = _report_with([photo])
        self.assertNotIn("<script>", html)

    def test_a_label_with_no_name_or_time_still_marks_the_photo(self):
        """The flag is the assertion; the attribution is a courtesy."""
        html = _report_with([{"original_r2_key": KEY, "added_after_filing": True}])
        self.assertIn("Added after filing", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
