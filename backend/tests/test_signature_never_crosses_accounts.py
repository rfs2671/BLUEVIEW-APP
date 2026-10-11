"""ANOTHER ACCOUNT'S SAVED SIGNATURE IS NEVER THIS ACCOUNT'S. Ruled 2026-10-10.

588 Thomas: Shawn (a CP) and Michael (the superintendent) shared a phone. The
app cached the signer's name and drawing under one device-wide key that
survived logout, and wrote it to whoever signed in next. From 2026-09-22
thirty of Michael's filed logs carried Shawn's drawing -- seven under
Michael's name.

The device now keys that cache per account (frontend/src/utils/
cpProfileCache.js). This is the server half, for an app too old to have it:

  - PUT /cp/profile refuses a drawing saved on another account (409
    SIGNATURE_BELONGS_TO_ANOTHER_ACCOUNT), and audits every real change to
    the name, the drawing (by fingerprint) and the title.
  - Filing -- create, the PUT that submits, finalize -- is NEVER refused for
    it. Ruled 2026-10-10: the operator ruled the thirty logs signed properly
    and that nothing may be blocked in the field; a filing-time refusal would
    have refused exactly those thirty. A match is RECORDED as an audit row
    (signature_matches_another_account), judged against the record's SIGNER.
  - Nothing already filed is touched.
"""

from __future__ import annotations

import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from tests.test_submit_requires_signature import (  # noqa: E402
    _FakeDb, _post, _put, _user, _db_for_create, _db_for_update,
)

SHAWN_PATHS = [[{"x": 128.0, "y": 12.1}, {"x": 130.5, "y": 14.0}]]
MICHAEL_PATHS = [[{"x": 40.0, "y": 70.0}, {"x": 41.0, "y": 71.5}]]

# Signed and affirmed for THIS document -- the gate before this one requires it.
SHAWN_MARK = {"paths": SHAWN_PATHS, "signed_at": "2026-10-05T12:00:00Z",
              "affirmed": True, "affirmedAt": "2026-10-05T12:00:00Z",
              "signer_name": "Michael Cespedes"}
MICHAEL_MARK = {**SHAWN_MARK, "paths": MICHAEL_PATHS}

SHAWN_USER = {"_id": "shawn", "name": "shawn",
              "cp_signature": {"paths": SHAWN_PATHS}}


def _with_users(db, users, profile=None):
    """db.users.find_one answers the two questions the server asks of it: the
    helper's (another account whose saved strokes are these), and the profile
    route's (this account's current profile, `profile`)."""
    coll = db.users

    async def find_one(q=None, *a, **k):
        q = q or {}
        if "cp_signature.paths" in q:
            not_id = (q.get("_id") or {}).get("$ne")
            for u in users:
                if (str(u["_id"]) != str(not_id)
                        and (u.get("cp_signature") or {}).get("paths")
                        == q["cp_signature.paths"]):
                    return u
            return None
        return profile
    coll.find_one = find_one
    return db


class TheFingerprint(unittest.TestCase):

    def test_it_is_the_strokes_not_the_stamps(self):
        a = server._signature_drawing_key(SHAWN_MARK)
        b = server._signature_drawing_key({"paths": SHAWN_PATHS, "signer_name": "x",
                                           "affirmed": False})
        self.assertEqual(a, b)
        self.assertNotEqual(a, server._signature_drawing_key(MICHAEL_MARK))

    def test_no_strokes_no_fingerprint(self):
        for sig in (None, {}, {"paths": []}, "x"):
            self.assertIsNone(server._signature_drawing_key(sig))


class ALookupThatCannotRunDoesNotRefuse(unittest.TestCase):
    """A defence, not a precondition: a read failure must not stop a filing."""

    def test_a_failing_read_returns_none_and_is_logged(self):
        import asyncio

        class _Boom:
            async def find_one(self, *a, **k):
                raise RuntimeError("primary stepped down")

        class _Db:
            users = _Boom()

        with patch.object(server, "db", _Db()), \
                self.assertLogs(server.logger, level="WARNING") as logs:
            out = asyncio.run(server._signature_saved_by_another_account(
                SHAWN_MARK, "u1"))
        self.assertIsNone(out)
        self.assertTrue(any("could not run" in m for m in logs.output))

    def test_an_answer_naming_the_signer_himself_is_not_another_account(self):
        import asyncio

        class _Users:
            async def find_one(self, *a, **k):
                return {"_id": "u1", "cp_signature": {"paths": SHAWN_PATHS}}

        class _Db:
            users = _Users()

        with patch.object(server, "db", _Db()):
            self.assertIsNone(asyncio.run(
                server._signature_saved_by_another_account(SHAWN_MARK, "u1")))


class FilingIsRecordedNeverRefused(unittest.TestCase):
    """Ruled 2026-10-10: nothing may be blocked in the field."""

    def setUp(self):
        self.audits = []

        async def _audit(*a, **k):
            self.audits.append(a)
        self._patch = patch.object(server, "audit_log", side_effect=_audit)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def _notes(self):
        return [a for a in self.audits
                if a and a[0] == "signature_matches_another_account"]

    def _code(self, resp):
        detail = resp.json().get("detail") if resp.content else None
        return detail.get("code") if isinstance(detail, dict) else None

    def test_create_with_shawns_drawing_files_and_is_recorded(self):
        db = _with_users(_db_for_create(), [SHAWN_USER])
        resp = _post(db, {"project_id": "proj1", "log_type": "toolbox_talk",
                          "date": "2026-10-05", "status": "submitted",
                          "cp_signature": SHAWN_MARK, "cp_name": "Carl CP",
                          "data": {"meeting_time": "08:00 AM",
                                   "attendees": [{"name": "A"}]}})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(db.logbooks.inserted), 1, "the filing went through")
        notes = self._notes()
        self.assertEqual(len(notes), 1, self.audits)
        _, actor, rtype, _rid, details = notes[0]
        self.assertEqual((actor, rtype), ("u1", "logbook"))
        self.assertEqual(details["other_account"], "shawn")
        self.assertEqual(details["log_type"], "toolbox_talk")

    def test_his_own_drawing_files_with_no_note(self):
        db = _with_users(_db_for_create(), [SHAWN_USER])
        resp = _post(db, {"project_id": "proj1", "log_type": "toolbox_talk",
                          "date": "2026-10-05", "status": "submitted",
                          "cp_signature": MICHAEL_MARK, "cp_name": "Carl CP",
                          "data": {"meeting_time": "08:00 AM",
                                   "attendees": [{"name": "A"}]}})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self._notes(), [])

    def _stored(self, mark, signer="u1"):
        return {"_id": "lb1", "project_id": "proj1", "log_type": "toolbox_talk",
                "date": "2026-10-05", "status": "draft", "is_locked": False,
                "cp_signature": mark, "cp_name": "Carl CP", "signed_by": signer,
                "created_by": signer,
                "data": {"meeting_time": "08:00 AM", "attendees": [{"name": "A"}]}}

    def test_the_put_that_submits_files_and_is_recorded(self):
        db = _with_users(_db_for_update(self._stored(SHAWN_MARK)), [SHAWN_USER])
        resp = _put(db, {"status": "submitted"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotEqual(db.logbooks.updated, [], "the submit was written")
        self.assertEqual(len(self._notes()), 1, self.audits)

    def _finalize(self, db, role="cp"):
        async def _fake_user():
            return _user(role)
        server.app.dependency_overrides[server.get_current_user] = _fake_user
        try:
            with patch.object(server, "db", db):
                return TestClient(server.app).post("/api/logbooks/lb1/finalize")
        finally:
            server.app.dependency_overrides.clear()

    def test_finalize_locks_and_is_recorded(self):
        db = _FakeDb()
        db.projects.set_find_one(lambda q: {"_id": "proj1", "name": "588"})
        db.logbooks.set_find_one(lambda q: self._stored(SHAWN_MARK))
        _with_users(db, [SHAWN_USER])
        resp = self._finalize(db)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue([u for u in db.logbooks.updated if "is_locked" in str(u)],
                        "the finalize locked the log")
        self.assertEqual(len(self._notes()), 1, self.audits)

    def test_an_admin_finalizing_shawns_own_log_writes_no_note(self):
        db = _FakeDb()
        db.projects.set_find_one(lambda q: {"_id": "proj1", "name": "588"})
        db.logbooks.set_find_one(lambda q: self._stored(SHAWN_MARK, signer="shawn"))
        _with_users(db, [SHAWN_USER])
        resp = self._finalize(db, role="admin")
        self.assertNotEqual(resp.status_code, 400, resp.text)
        self.assertEqual(self._notes(), [])

    def test_a_failing_note_does_not_stop_the_filing(self):
        async def _boom(*a, **k):
            # ONLY THE NOTE FAILS. The route's own create audit is not this
            # test's subject.
            if a and a[0] == "signature_matches_another_account":
                raise RuntimeError("audit store down")
        self._patch.stop()
        self._patch = patch.object(server, "audit_log", side_effect=_boom)
        self._patch.start()
        db = _with_users(_db_for_create(), [SHAWN_USER])
        resp = _post(db, {"project_id": "proj1", "log_type": "toolbox_talk",
                          "date": "2026-10-05", "status": "submitted",
                          "cp_signature": SHAWN_MARK, "cp_name": "Carl CP",
                          "data": {"meeting_time": "08:00 AM",
                                   "attendees": [{"name": "A"}]}})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(db.logbooks.inserted), 1)

    def test_no_filing_path_can_raise_for_it(self):
        """The refusal code is gone from the server, so no path can send it."""
        src = open(server.__file__, encoding="utf-8").read()
        self.assertNotIn('"code": "SUBMIT_SIGNATURE_OF_ANOTHER_ACCOUNT"', src)


class TheProfileSave(unittest.TestCase):

    def _put_profile(self, db, body):
        async def _fake_user():
            return _user("cp")
        server.app.dependency_overrides[server.get_current_user] = _fake_user
        try:
            with patch.object(server, "db", db), \
                    patch.object(server, "audit_log") as audit:
                async def _noop(*a, **k):
                    audit.calls.append((a, k))
                audit.calls = []
                audit.side_effect = _noop
                resp = TestClient(server.app).put("/api/cp/profile", json=body)
                return resp, audit.calls
        finally:
            server.app.dependency_overrides.clear()

    def test_another_accounts_drawing_is_refused_and_nothing_is_written(self):
        db = _with_users(_FakeDb(), [SHAWN_USER],
                         profile={"_id": "u1", "cp_name": "Michael Cespedes"})
        resp, audits = self._put_profile(db, {"cp_name": "Michael Cespedes",
                                              "cp_signature": {"paths": SHAWN_PATHS}})
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json()["detail"]["code"],
                         "SIGNATURE_BELONGS_TO_ANOTHER_ACCOUNT")
        self.assertEqual(db.users.updated, [])
        self.assertEqual(audits, [])

    def test_a_real_change_is_audited_with_old_and_new(self):
        db = _with_users(_FakeDb(), [SHAWN_USER],
                         profile={"_id": "u1", "cp_name": "shawn",
                                  "cp_signature": {"paths": SHAWN_PATHS}})
        resp, audits = self._put_profile(db, {"cp_name": "Michael Cespedes",
                                              "cp_signature": {"paths": MICHAEL_PATHS}})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(audits), 1, audits)
        (action, actor, rtype, rid, details), _ = audits[0]
        self.assertEqual((action, actor, rtype, rid),
                         ("cp_profile_update", "u1", "user", "u1"))
        self.assertEqual(details["cp_name"], {"old": "shawn", "new": "Michael Cespedes"})
        self.assertEqual(details["cp_signature"]["old"],
                         server._signature_drawing_key({"paths": SHAWN_PATHS}))
        self.assertEqual(details["cp_signature"]["new"],
                         server._signature_drawing_key({"paths": MICHAEL_PATHS}))

    def test_the_audit_never_stores_the_drawing(self):
        src = inspect.getsource(server.update_cp_profile)
        audit_part = src[src.index("changes = {}"):]
        self.assertNotIn('update["cp_signature"]}', audit_part)
        self.assertIn("_signature_drawing_key(update[\"cp_signature\"])", audit_part)

    def test_an_unchanged_save_writes_no_audit_row(self):
        db = _with_users(_FakeDb(), [SHAWN_USER],
                         profile={"_id": "u1", "cp_name": "Michael Cespedes",
                                  "cp_signature": {"paths": MICHAEL_PATHS}})
        resp, audits = self._put_profile(db, {"cp_name": "Michael Cespedes",
                                              "cp_signature": {"paths": MICHAEL_PATHS}})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(audits, [])


if __name__ == "__main__":
    unittest.main()
