"""Recovering a photo from the phone that took it, into the entry that lists it.

Operator's ruling, 2026-10-08: build the check-then-recover path. Two filed
daily jobsite logs on 588 Thomas list photos that exist only on the capturing
phone (`upload_pending`, a `file://` path, nothing on the server):

  2026-08-05  three entries, three distinct phone files
  2026-08-24  one entry -- whose phone file is SHARED with two entries that
              already have their images in R2

THE RULES PINNED HERE
  * /pending lists only the author's own stranded entries.
  * /presence records what the phone reports in its OWN collection, never on
    the record, before anything uploads.
  * /recover fills the entry the record already lists, matched by its own path
    AND capture time; keeps the capture time; is not "added after filing";
    says how the photo arrived; audits; enhances by identity.
  * A file shared by several entries is HELD for review, not attached.
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
os.environ.setdefault("APP_BASE_URL", "https://app.test")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

MICHAEL = {"_id": "u-michael", "id": "u-michael", "role": "superintendent",
           "company_id": "c1", "account_status": "approved"}
OTHER = {"_id": "u-other", "id": "u-other", "role": "cp", "company_id": "c1",
         "account_status": "approved"}
U0 = "file:///data/user/0/com.levelog.app/files/logbook_photos/cap_1785935200722_1_19.jpg"
U1 = "file:///data/user/0/com.levelog.app/files/logbook_photos/cap_1785935216326_2_19.jpg"
U2 = "file:///data/user/0/com.levelog.app/files/logbook_photos/1787667899371_0.jpg"
T0 = "2026-08-05T13:06:40.722Z"
JPEG = b"\xff\xd8\xff\xe0" + b"PHOTO-BYTES" * 50


def _aug05():
    return {"_id": "lbA", "project_id": "p588", "date": "2026-08-05",
            "log_type": "daily_jobsite", "status": "submitted", "is_locked": True,
            "created_by": "u-michael", "is_deleted": False,
            "updated_at": "2026-08-27T07:00:01",
            "data": {"activities": [{"photos": [
                {"uri": U0, "timestamp": T0, "upload_pending": True},
                {"uri": U1, "timestamp": "2026-08-05T13:06:56.326Z", "upload_pending": True},
                {"uri": "file:///x/later.jpg", "timestamp": "2026-08-26T11:56:57Z",
                 "original_r2_key": "logbook-photos/p588/cap_9/cap_9.jpg"},
            ]}]}}


def _aug24():
    return {"_id": "lbB", "project_id": "p588", "date": "2026-08-24",
            "log_type": "daily_jobsite", "status": "submitted",
            "created_by": "u-michael", "is_deleted": False,
            "data": {"activities": [{"activity_id": "act_b", "photos": [
                {"uri": U2, "timestamp": "2026-08-24T18:26:18.807Z", "upload_pending": True},
                {"uri": U2, "timestamp": "2026-08-24T18:26:28.159Z", "upload_pending": True,
                 "enhanced_r2_key": "e1", "thumb_r2_key": "t1", "enhance_status": "done"},
                {"uri": U2, "timestamp": "2026-08-24T18:26:42.279Z", "upload_pending": True,
                 "enhanced_r2_key": "e2", "thumb_r2_key": "t2", "enhance_status": "done"},
            ]}]}}


def _someone_elses():
    d = _aug05()
    d["_id"], d["created_by"] = "lbC", "u-third"
    return d


# ── a Mongo faithful enough for dotted paths through arrays ─────────────────

def _values(doc, path):
    vals = [doc]
    for seg in path.split("."):
        nxt = []
        for v in vals:
            if isinstance(v, list):
                if seg.isdigit():
                    i = int(seg)
                    if i < len(v):
                        nxt.append(v[i])
                else:
                    nxt.extend(x.get(seg) for x in v if isinstance(x, dict) and seg in x)
            elif isinstance(v, dict) and seg in v:
                nxt.append(v[seg])
        vals = nxt
    return vals


def _match(doc, q):
    for k, cond in (q or {}).items():
        if k == "$or":
            if not any(_match(doc, c) for c in cond):
                return False
            continue
        vals = _values(doc, k)
        if isinstance(cond, dict):
            if "$exists" in cond and bool(vals) != cond["$exists"]:
                return False
            if "$ne" in cond and cond["$ne"] in vals:
                return False
            continue
        if cond not in vals:
            return False
    return True


def _set(doc, path, value, unset=False):
    parts = path.split(".")
    cur = doc
    for seg in parts[:-1]:
        cur = cur[int(seg)] if isinstance(cur, list) else cur.setdefault(seg, {})
    if unset:
        cur.pop(parts[-1], None)
    else:
        cur[parts[-1]] = value


class _Cur:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        async def g():
            for r in self.rows:
                yield copy.deepcopy(r)
        return g()


class _Coll:
    def __init__(self, rows=()):
        self.rows = [copy.deepcopy(r) for r in rows]
        self.writes = []

    def find(self, q=None, *a, **k):
        return _Cur([r for r in self.rows if _match(r, q)])

    async def find_one(self, q=None, *a, **k):
        for r in self.rows:
            if _match(r, q):
                return copy.deepcopy(r)
        return None

    async def insert_many(self, docs):
        self.rows.extend(copy.deepcopy(d) for d in docs)

    async def update_one(self, q, u, **k):
        self.writes.append((q, u))
        for r in self.rows:
            if _match(r, q):
                for p, v in (u.get("$set") or {}).items():
                    _set(r, p, v)
                for p in (u.get("$unset") or {}):
                    _set(r, p, None, unset=True)
                return type("R", (), {"matched_count": 1})()
        return type("R", (), {"matched_count": 0})()


class _DB:
    def __init__(self):
        self.logbooks = _Coll([_aug05(), _aug24(), _someone_elses()])
        self.photo_recovery_probes = _Coll()


class _Base(unittest.TestCase):
    def setUp(self):
        self.db = _DB()
        self.uploads, self.audits, self.enhanced = [], [], []

        async def audit(action, user_id, rtype, rid, details=None):
            self.audits.append((action, rid, details or {}))

        async def enhance(lid, aid, key):
            self.enhanced.append((lid, aid, key))

        self._p = [
            patch.object(server, "db", self.db),
            patch.object(server, "to_query_id", lambda x: x),
            patch.object(server, "audit_log", audit),
            patch.object(server, "_enhance_appended_photo", enhance),
            patch.object(server, "_r2_client", object()),
            patch.object(server, "R2_BUCKET_NAME", "bucket"),
            patch.object(server, "_upload_to_r2",
                         lambda b, k, ct="": self.uploads.append((k, len(b))) or "url"),
        ]
        for p in self._p:
            p.start()
        self.user = MICHAEL

        async def who():
            return self.user
        server.app.dependency_overrides[server.get_current_user] = who
        server.app.dependency_overrides[server.require_approved] = who
        self.c = TestClient(server.app)

    def tearDown(self):
        server.app.dependency_overrides.clear()
        for p in self._p:
            p.stop()

    def log(self, lid):
        return next(r for r in self.db.logbooks.rows if r["_id"] == lid)

    def recover(self, lid, ai, pi, uri, ts, content=JPEG):
        return self.c.post(f"/api/photo-recovery/{lid}/recover",
                           data={"activity_index": ai, "photo_index": pi,
                                 "uri": uri, "timestamp": ts},
                           files={"file": ("p.jpg", content, "image/jpeg")})


class Pending(_Base):

    def test_lists_only_his_stranded_entries(self):
        items = self.c.get("/api/photo-recovery/pending").json()["items"]
        got = sorted((i["logbook_id"], i["activity_index"], i["photo_index"],
                      i["shares_file"]) for i in items)
        self.assertEqual(got, [("lbA", 0, 0, False), ("lbA", 0, 1, False),
                               ("lbB", 0, 0, True)])

    def test_another_accounts_phone_is_asked_for_nothing(self):
        self.user = OTHER
        self.assertEqual(self.c.get("/api/photo-recovery/pending").json()["items"], [])


class Presence(_Base):

    def test_recorded_in_its_own_collection_and_the_record_is_untouched(self):
        before = copy.deepcopy(self.log("lbA"))
        r = self.c.post("/api/photo-recovery/lbA/presence", json={"reports": [
            {"activity_index": 0, "photo_index": 0, "uri": U0, "timestamp": T0,
             "exists": True, "size": 2000000, "md5": "aa"},
            {"activity_index": 0, "photo_index": 1, "uri": U1, "exists": False}]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"recorded": 2, "present": 1, "missing": 1})
        self.assertEqual(len(self.db.photo_recovery_probes.rows), 2)
        self.assertEqual(self.log("lbA"), before)
        self.assertEqual(self.db.logbooks.writes, [])
        self.assertEqual(self.audits[0][0], "photo_recovery_probe")

    def test_not_his_log_is_a_404(self):
        self.user = OTHER
        r = self.c.post("/api/photo-recovery/lbA/presence", json={"reports": []})
        self.assertEqual(r.status_code, 404)


class Recover(_Base):

    def test_fills_the_listed_entry_and_says_how(self):
        r = self.recover("lbA", 0, 0, U0, T0)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "recovered")
        p = self.log("lbA")["data"]["activities"][0]["photos"][0]
        self.assertTrue(p["original_r2_key"].startswith("logbook-photos/p588/"))
        self.assertEqual(p["recovered_from"], "capturing_device")
        self.assertEqual(p["recovered_by"], "u-michael")
        self.assertIn("recovered_at", p)
        self.assertEqual(p["timestamp"], T0, "the capture time is kept")
        self.assertNotIn("upload_pending", p)
        self.assertNotIn("added_after_filing", p, "it was listed before filing")
        self.assertEqual(self.uploads[0][0], p["original_r2_key"])
        self.assertEqual(self.audits[-1][0], "logbook_photo_recovered")
        self.assertEqual(self.enhanced, [("lbA", None, p["original_r2_key"])])

    def test_nothing_else_on_the_record_moves(self):
        before = copy.deepcopy(self.log("lbA"))
        self.recover("lbA", 0, 0, U0, T0)
        after = self.log("lbA")
        self.assertEqual(after["data"]["activities"][0]["photos"][1:],
                         before["data"]["activities"][0]["photos"][1:])
        self.assertEqual({k: v for k, v in after.items() if k not in ("data", "updated_at")},
                         {k: v for k, v in before.items() if k not in ("data", "updated_at")})

    def test_the_wrong_capture_time_is_refused_before_any_upload(self):
        r = self.recover("lbA", 0, 0, U0, "2026-08-05T00:00:00Z")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.uploads, [])

    def test_the_wrong_path_is_refused(self):
        self.assertEqual(self.recover("lbA", 0, 0, U1, T0).status_code, 409)

    def test_a_second_recovery_of_the_same_entry_is_refused(self):
        self.recover("lbA", 0, 0, U0, T0)
        self.assertEqual(self.recover("lbA", 0, 0, U0, T0).status_code, 409)

    def test_an_entry_that_already_has_its_image_is_refused(self):
        r = self.recover("lbB", 0, 1, U2, "2026-08-24T18:26:28.159Z")
        self.assertEqual(r.status_code, 409)

    def test_not_an_image_is_refused(self):
        r = self.recover("lbA", 0, 0, U0, T0, content=b"not a picture")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.uploads, [])

    def test_someone_elses_log_is_a_404(self):
        self.user = OTHER
        self.assertEqual(self.recover("lbA", 0, 0, U0, T0).status_code, 404)

    def test_a_storage_failure_writes_nothing(self):
        def boom(*a, **k):
            raise RuntimeError("R2 down")
        with patch.object(server, "_upload_to_r2", boom):
            r = self.recover("lbA", 0, 0, U0, T0)
        self.assertEqual(r.status_code, 502)
        self.assertEqual(self.db.logbooks.writes, [])


class ASharedFileIsHeld(_Base):
    """2026-08-24: three entries, one phone file, two already in R2. Which
    picture the file holds cannot be told here -- held for the operator."""

    def test_held_not_attached(self):
        r = self.recover("lbB", 0, 0, U2, "2026-08-24T18:26:18.807Z")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "held_for_review")
        p = self.log("lbB")["data"]["activities"][0]["photos"][0]
        self.assertNotIn("original_r2_key", p)
        self.assertTrue(p["upload_pending"], "still pending: nothing is attached")
        self.assertIn("/recovery/lbB/", p["recovery_candidate_r2_key"])
        self.assertEqual(self.enhanced, [], "nothing is enhanced until it is accepted")
        self.assertEqual(self.audits[-1][0], "logbook_photo_recovery_held")

    def test_and_it_leaves_the_pending_list(self):
        self.recover("lbB", 0, 0, U2, "2026-08-24T18:26:18.807Z")
        items = self.c.get("/api/photo-recovery/pending").json()["items"]
        self.assertNotIn("lbB", {i["logbook_id"] for i in items})


if __name__ == "__main__":
    unittest.main(verbosity=2)
