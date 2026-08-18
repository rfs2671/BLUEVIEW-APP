"""THE PHOTOS ON THE REPORT BELONG TO THE DOCUMENT THE REPORT PRINTS.

DEVICE ROUND 6, item 5, which follows from item 4. The amendment mechanism is
where a correction goes missing: the child is created on the server with its
PARENT'S data copied onto it, the CP's edits then live only in the on-device
draft, and _filed_log deliberately refuses to print an unsigned amendment. So
until the amendment is signed the report shows the original, and once it is
signed the report shows the amendment.

BEFORE CALLING THAT THE WHOLE EXPLANATION, the one production read of
`data.activities[].photos[]` has to be checked, because a second, independent
cause would look identical from the outside: if anything served photo bytes off
the ORIGINAL while the report printed the amendment, or recomputed an object
key from the logbook id instead of reading the key stored on the row, then a
filed amendment would render with photos missing no matter what the client did.

There is exactly one such read — get_logbook_activity_photo — and this file
pins its three properties:

  1. the report addresses photos by the id of the document IT PRINTED
  2. that endpoint reads the photos of the document named in the URL
  3. the R2 object key comes off the PHOTO ROW, never from the logbook id

(3) is what makes an amendment work at all: the objects were uploaded under the
parent's id (or under a capture id), the child carries the keys verbatim, and
they keep resolving forever without either scheme knowing about the other.
"""

from __future__ import annotations

import asyncio
import base64
import copy
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

import server  # noqa: E402

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")
_REPORT = _SRC[_SRC.index("async def generate_combined_report"):]
_REPORT = _REPORT[:_REPORT.index("async def get_combined_report(")]

DATE = "2026-08-12"
PROJECT = "p1"

ORIG_BYTES = b"\xff\xd8\xff-original-photo"
AMEND_BYTES = b"\xff\xd8\xff-amended-photo"


def _match(doc, query):
    for k, v in query.items():
        if isinstance(v, dict):
            if "$ne" in v and doc.get(k) == v["$ne"]:
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _Coll:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, projection=None):
        return _Cursor([d for d in self.docs if _match(d, query or {})])

    async def find_one(self, query=None, projection=None, sort=None):
        for d in self.docs:
            if _match(d, query or {}):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, query=None):
        return sum(1 for d in self.docs if _match(d, query or {}))


class _DB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self[n]

    def __getitem__(self, n):
        if n not in self._c:
            self._c[n] = _Coll()
        return self._c[n]


class _FakeR2:
    """Objects by key. Anything not held raises, exactly as boto3 would."""

    def __init__(self, objects):
        self.objects = objects
        self.asked = []

    def get_object(self, Bucket=None, Key=None):   # noqa: N803 — boto3's names
        self.asked.append(Key)
        if Key not in self.objects:
            raise KeyError(Key)

        class _Body:
            def __init__(self, raw):
                self._raw = raw

            def read(self):
                return self._raw

        return {"Body": _Body(self.objects[Key])}


def _jobsite(_id, *, photo_key, locked, status, hour, desc):
    """A daily_jobsite carrying ONE photo whose only surviving copy is an R2
    object. The key is what the row stores — the parent's, on the amendment."""
    return {
        "_id": _id, "project_id": PROJECT, "date": DATE,
        "log_type": "daily_jobsite", "is_deleted": False,
        "is_locked": locked, "status": status,
        "created_at": datetime(2026, 8, 12, hour, tzinfo=timezone.utc),
        "cp_signature": {"affirmed": True}, "cp_name": "Carl CP",
        "data": {"activities": [{
            "crew_id": "C-1", "company": "Kestrel Electric", "trade": "Electrical",
            "num_workers": 2, "work_description": desc, "work_locations": "3rd floor",
            "photos": [{"id": "ph1", "enhanced_r2_key": photo_key,
                        "thumb_r2_key": photo_key, "enhance_status": "done"}],
        }]},
    }


# The objects R2 actually holds. Both were uploaded under the ORIGINAL's id,
# because that is when the photos were taken.
ORIG_KEY = f"logbook-photos/{PROJECT}/lb_original/0-0-enhanced.jpg"


class TheReportAddressesThePhotosOfTheDocumentItPrinted(unittest.TestCase):

    def _report(self, docs):
        db = _DB()
        db.projects.docs = [{"_id": PROJECT, "name": "588 Thomas S Boyland Street",
                             "address": "588 Thomas S Boyland St, Brooklyn"}]
        db.logbooks.docs = docs
        db.checkins.docs = []
        with patch.object(server, "db", db), \
             patch.object(server, "to_query_id", lambda x: x):
            return asyncio.run(server.generate_combined_report(PROJECT, DATE))

    def test_an_unsigned_amendment_leaves_the_originals_photos_on_the_page(self):
        """_filed_log refuses to print an unsigned amendment, and that ruling
        stands — an intention to correct is not a correction. So the photos
        addressed are still the original's."""
        original = _jobsite("lb_original", photo_key=ORIG_KEY, locked=True,
                            status="submitted", hour=9, desc="branch rough-in")
        child = _jobsite("lb_child", photo_key=ORIG_KEY, locked=False,
                         status="draft", hour=16, desc="branch rough-in corrected")
        html = self._report([original, child])
        self.assertIn("/api/reports/logbook-photo/lb_original/", html)
        self.assertNotIn("/api/reports/logbook-photo/lb_child/", html)

    def test_a_FILED_amendment_moves_every_photo_url_onto_the_child(self):
        """One document decides the whole page: the same object supplies the
        activity rows and the photo ids, so the photos can never come from a
        record other than the one being printed."""
        original = _jobsite("lb_original", photo_key=ORIG_KEY, locked=True,
                            status="submitted", hour=9, desc="branch rough-in")
        child = _jobsite("lb_child", photo_key=ORIG_KEY, locked=True,
                         status="submitted", hour=16, desc="branch rough-in corrected")
        html = self._report([original, child])
        self.assertIn("Branch rough-in corrected", html)
        self.assertIn("/api/reports/logbook-photo/lb_child/", html)
        self.assertNotIn("/api/reports/logbook-photo/lb_original/", html)

    def test_every_photo_url_on_the_page_is_built_from_the_SAME_id(self):
        """Page 1 groups photos by subcontractor and page 2 renders them again
        inside the jobsite section. Two builders, one document — if they ever
        resolved separately, one half of the report could address the original
        while the other addressed the amendment."""
        ids = set(re.findall(r"/api/reports/logbook-photo/([^/]+)/", self._report([
            _jobsite("lb_original", photo_key=ORIG_KEY, locked=True,
                     status="submitted", hour=9, desc="branch rough-in"),
            _jobsite("lb_child", photo_key=ORIG_KEY, locked=True,
                     status="submitted", hour=16, desc="corrected"),
        ])))
        self.assertEqual(ids, {"lb_child"})

    def test_the_id_is_taken_from_the_resolved_document_in_source(self):
        """Asserted in source as well, because the behaviour above would also
        pass if a second resolver happened to agree on this fixture."""
        self.assertIn('daily_jobsite = _filed_log(logbooks, "daily_jobsite")', _REPORT)
        self.assertIn('_dj_id = str(daily_jobsite["_id"]) if daily_jobsite else ""',
                      _REPORT)
        self.assertIn('logbook_id = str(daily_jobsite["_id"])', _REPORT)
        # And nothing anywhere reaches for a parent to read photos off.
        self.assertNotIn("parent_logbook_id", _REPORT)


class TheOneReadServesTheDocumentItWasAskedFor(unittest.TestCase):
    """get_logbook_activity_photo — the single production read of
    data.activities[].photos[]. Everything on the report is an <img> pointing
    at it, so if it read anything other than the document in its own URL, the
    printed record and the printed photos would come from two places."""

    def _serve(self, docs, logbook_id, r2, v=""):
        db = _DB()
        db.logbooks.docs = docs
        with patch.object(server, "db", db), \
             patch.object(server, "to_query_id", lambda x: x), \
             patch.object(server, "_r2_client", r2), \
             patch.object(server, "R2_BUCKET_NAME", "bv-bucket"):
            return asyncio.run(server.get_logbook_activity_photo(logbook_id, 0, 0, v))

    def test_each_id_serves_its_OWN_photo(self):
        child_key = f"logbook-photos/{PROJECT}/lb_child/0-0-enhanced.jpg"
        docs = [
            _jobsite("lb_original", photo_key=ORIG_KEY, locked=True,
                     status="submitted", hour=9, desc="branch rough-in"),
            _jobsite("lb_child", photo_key=child_key, locked=True,
                     status="submitted", hour=16, desc="corrected"),
        ]
        r2 = _FakeR2({ORIG_KEY: ORIG_BYTES, child_key: AMEND_BYTES})
        self.assertEqual(self._serve(docs, "lb_original", r2, "enhanced").body,
                         ORIG_BYTES)
        self.assertEqual(self._serve(docs, "lb_child", r2, "enhanced").body,
                         AMEND_BYTES)

    def test_an_amendment_serves_the_object_uploaded_under_its_PARENTS_id(self):
        """THE PROPERTY THE WHOLE AMENDMENT PATH RESTS ON. The photos were
        uploaded when they were taken, so their objects are keyed to the
        original; amend_logbook copies the rows onto the child verbatim. The
        key is READ OFF THE ROW and never rebuilt, so the child's photos serve
        from the parent's objects and nothing is re-uploaded or lost."""
        child = _jobsite("lb_child", photo_key=ORIG_KEY, locked=True,
                         status="submitted", hour=16, desc="corrected")
        r2 = _FakeR2({ORIG_KEY: ORIG_BYTES})
        resp = self._serve([child], "lb_child", r2, "enhanced")
        self.assertEqual(resp.body, ORIG_BYTES)
        self.assertEqual(r2.asked, [ORIG_KEY],
                         "the key was rebuilt from the logbook id instead of read")

    def test_a_capture_scheme_key_is_also_read_verbatim(self):
        """The other key scheme — (project, activity_id, photo_id), minted on
        the device before any logbook exists. Nothing recomputes this either."""
        cap = f"logbook-photos/{PROJECT}/act-1/ph1.jpg"
        doc = _jobsite("lb_child", photo_key=cap, locked=True,
                       status="submitted", hour=16, desc="corrected")
        r2 = _FakeR2({cap: AMEND_BYTES})
        self.assertEqual(self._serve([doc], "lb_child", r2, "enhanced").body,
                         AMEND_BYTES)

    def test_the_inline_last_resort_copy_travels_with_the_row(self):
        """R2 unreachable at read time degrades to the retained thumbnail —
        which is a field on the photo row, so it is copied onto the amendment
        with everything else."""
        doc = _jobsite("lb_child", photo_key=ORIG_KEY, locked=True,
                       status="submitted", hour=16, desc="corrected")
        doc["data"]["activities"][0]["photos"][0]["thumb_base64"] = (
            base64.b64encode(AMEND_BYTES).decode("ascii"))
        resp = self._serve([doc], "lb_child", _FakeR2({}), "enhanced")
        self.assertEqual(resp.body, AMEND_BYTES)

    def test_it_is_the_only_reader(self):
        """One serve path. A second one is how the report and its photos would
        drift apart without either half looking wrong."""
        readers = re.findall(
            r'activities\[activity_index\]\.get\("photos"\)', _SRC)
        self.assertEqual(len(readers), 1)
        self.assertEqual(_SRC.count(
            "@api_router.get(\"/reports/logbook-photo/"
            "{logbook_id}/{activity_index}/{photo_index}\")"), 1)


if __name__ == "__main__":
    unittest.main()
