"""A filed log's content is not rewritable, and the repair path stays open.

THE HOLE. update_logbook's 423 keys on `is_locked`. An END_OF_DAY log is NOT
locked when it is submitted -- sweep_stale_end_of_day_logs freezes it overnight,
and only if its signature is affirmed. So between Submit and the sweep every
daily narrative sits `status: submitted, is_locked: false`, and PUT $set
straight over `data`.

IT HAPPENED. Two daily_jobsite records at 588 Thomas, re-entered and
overwritten on 2026-08-25:

    6a8c4acd  date 2026-08-24  created 13:44 Aug 24  updated 14:28 Aug 25
    6a8d867d  date 2026-08-25  created 12:11         updated 14:24

Both submitted, both unlocked, `$set` on data, no amendment, no version, and no
audit entry -- update_logbook wrote none until a6068ee. A filed DOB record was
replaced and the prior content is not recoverable from the database.

THE PREDICATE, and why each half of it:

    stored status == "submitted"   not the REQUEST's: a draft being submitted
                                   sends data and status together and must pass
    data.data is not None          SCOPE IS LOAD-BEARING. 65 submitted logs on
                                   this project carry an unaffirmed signature
                                   and the only remedy is the CP affirming --
                                   a cp_signature write with data.data None.
                                   A blanket refusal would lock out the repair
                                   for all 65, which is worse than the hole.

NOT is_locked. That is the existing 423 and it is exactly what is missing here.

SCOPE OF THIS PR: this guard only. Not the dashboard badge, not the editor's
unlocked-log lookup, not affirmation enforcement. A test below asserts that
last one's absence so nobody mistakes this for it.

    python backend/tests/test_filed_log_data_immutable.py
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402

ADMIN = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "companyA",
         "account_status": "approved", "assigned_projects": ["projA"]}
CP = {"_id": "u2", "id": "u2", "role": "cp", "company_id": "companyA",
      "account_status": "approved", "assigned_projects": ["projA"]}
PROJECT = {"_id": "projA", "company_id": "companyA", "name": "588 Thomas"}

AFFIRMED = {"paths": "p", "affirmed": True, "affirmedAt": "2026-08-25T12:00:00Z"}
# The production shape: an inherited credential, unaffirmed.
INHERITED = {"paths": "p", "timestamp": "2026-08-19T15:01:10.726Z",
             "affirmedLang": "en"}


def _call(stored, update_body, user=ADMIN):
    """Drive update_logbook against doubles. Returns the captured $set, or
    raises whatever the handler raised."""
    captured = {}
    state = {"written": False}

    async def logbooks_find_one(q, *a, **kw):
        return dict(stored)

    async def logbooks_update_one(q, upd, *a, **kw):
        state["written"] = True
        captured["set"] = upd.get("$set", {})
        r = MagicMock()
        r.matched_count = 1
        return r

    async def projects_find_one(q, *a, **kw):
        return dict(PROJECT)

    db = MagicMock()
    db.logbooks.find_one = AsyncMock(side_effect=logbooks_find_one)
    db.logbooks.update_one = AsyncMock(side_effect=logbooks_update_one)
    db.projects.find_one = AsyncMock(side_effect=projects_find_one)

    body = server.LogbookUpdate(**update_body)
    with patch.object(server, "db", db), \
         patch.object(server, "audit_log", AsyncMock()), \
         patch.object(server, "_remember_other_activities", AsyncMock()):
        asyncio.run(server.update_logbook(
            logbook_id="lb1", data=body, current_user=user,
        ))
    return captured.get("set"), state["written"]


# ── The document that was actually overwritten ──────────────────────────────
FILED_DAILY = {
    "_id": "lb1", "project_id": "projA", "log_type": "daily_jobsite",
    "date": "2026-08-24", "status": "submitted", "is_locked": False,
    "cp_signature": INHERITED,
    "data": {"activities": [{"company": "Vanguard", "work_description": "Deck pour"}]},
}


DRAFT = {
    "_id": "lb1", "project_id": "projA", "log_type": "daily_jobsite",
    "date": "2026-08-25", "status": "draft", "is_locked": False,
    "cp_signature": AFFIRMED,
    "data": {"activities": [{"company": "Vanguard"}]},
}


class TodaysOverwriteIsRefused(unittest.TestCase):
    """The exact shape of 6a8c4acd, reproduced."""

    def test_a_submitted_unlocked_daily_jobsite_refuses_a_data_set(self):
        with self.assertRaises(HTTPException) as c:
            _call(FILED_DAILY, {"data": {"activities": [{"company": "REWRITTEN"}]}})
        self.assertEqual(c.exception.status_code, 409)

    def test_the_machine_code_is_distinguishable(self):
        """The client's correct next action is AMEND, and it cannot say so from
        a generic failure."""
        with self.assertRaises(HTTPException) as c:
            _call(FILED_DAILY, {"data": {"x": 1}})
        self.assertEqual(c.exception.detail, {"code": "FILED_LOG_DATA_IMMUTABLE"})

    def test_nothing_is_written_when_refused(self):
        """A refusal that still wrote would be the same defect with a 409 on
        top of it."""
        try:
            _call(FILED_DAILY, {"data": {"x": 1}})
        except HTTPException:
            pass
        # update_one must never have been reached.
        with self.assertRaises(HTTPException):
            _, written = _call(FILED_DAILY, {"data": {"x": 1}})
            self.assertFalse(written)

    def test_it_does_not_depend_on_is_locked(self):
        """is_locked is False here. The existing 423 cannot fire, which is the
        whole reason this guard exists."""
        self.assertIs(FILED_DAILY["is_locked"], False)
        with self.assertRaises(HTTPException) as c:
            _call(FILED_DAILY, {"data": {"x": 1}})
        self.assertEqual(c.exception.status_code, 409, "got the lock 423, not this guard")

    def test_a_cp_is_refused_too(self):
        """The CP is who re-enters the log. The role branch above must not
        route around this."""
        with self.assertRaises(HTTPException) as c:
            _call(FILED_DAILY, {"data": {"x": 1}}, user=CP)
        self.assertEqual(c.exception.status_code, 409)

    def test_an_immediate_type_is_refused_on_the_same_rule(self):
        """Not scoped to end_of_day. A submitted-unlocked immediate log is an
        older row, and its content is no more rewritable."""
        stored = {**FILED_DAILY, "log_type": "toolbox_talk"}
        with self.assertRaises(HTTPException) as c:
            _call(stored, {"data": {"x": 1}})
        self.assertEqual(c.exception.status_code, 409)


class TheRepairPathStaysOpen(unittest.TestCase):
    """Locking out the remedy for the 65 would be worse than the hole."""

    def test_affirming_a_filed_log_is_allowed(self):
        """cp_signature only, data.data is None. THE ONLY REMEDY for the 65
        unaffirmed submitted rows."""
        setops, written = _call(FILED_DAILY, {"cp_signature": AFFIRMED})
        self.assertTrue(written, "the affirmation repair was refused")
        self.assertIn("cp_signature", setops)

    def test_and_it_does_not_touch_data(self):
        setops, _ = _call(FILED_DAILY, {"cp_signature": AFFIRMED})
        self.assertNotIn("data", setops)

    def test_a_status_only_correction_is_allowed(self):
        setops, written = _call(
            {**FILED_DAILY, "cp_signature": AFFIRMED}, {"status": "submitted"})
        self.assertTrue(written)

    def test_cp_name_only_is_allowed(self):
        setops, written = _call(FILED_DAILY, {"cp_name": "Roy Fishman"})
        self.assertTrue(written)
        self.assertNotIn("data", setops)


class TheOrdinaryFlowIsUntouched(unittest.TestCase):
    """A guard that refuses too much is as wrong as one that refuses nothing."""

    def test_draft_to_submitted_with_data_and_status_together(self):
        """THE ORDINARY SUBMIT. Stored status is draft, so it passes -- this is
        why the predicate reads the STORED status and not the request's."""
        setops, written = _call(
            DRAFT,
            {"data": {"activities": [{"company": "Vanguard", "work_description": "Deck"}]},
             "status": "submitted", "cp_signature": AFFIRMED},
        )
        self.assertTrue(written, "the ordinary draft submit was refused")
        self.assertIn("data", setops)
        self.assertEqual(setops["status"], "submitted")

    def test_editing_a_draft_is_allowed(self):
        setops, written = _call(DRAFT, {"data": {"activities": [{"company": "X"}]}})
        self.assertTrue(written)
        self.assertIn("data", setops)

    def test_a_log_with_no_status_field_is_allowed(self):
        """A legacy row predating `status`. Absent is not 'submitted', and
        refusing it would strand rows nobody can repair."""
        stored = {k: v for k, v in DRAFT.items() if k != "status"}
        setops, written = _call(stored, {"data": {"x": 1}})
        self.assertTrue(written)


class ScopeOfThisChange(unittest.TestCase):
    """This PR is the guard. Nothing else."""

    SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text(
        encoding="utf-8")

    def _body(self):
        i = self.SRC.index("async def update_logbook(")
        return self.SRC[i:self.SRC.index("async def _purge_finalized_photo_base64", i)]

    def test_affirmation_enforcement_HAS_now_landed(self):
        """INVERTED, DELIBERATELY, AND THIS TEST DID ITS JOB.

        It was written to pin that the filed-log guard's PR did NOT add
        affirmation enforcement -- the two were sequenced apart on purpose. It
        failed the moment enforcement landed, which is exactly what a scope pin
        is for. The assertion is inverted rather than deleted so the pairing
        stays visible: this file's guard is about REWRITING a filed log, the
        refusal below is about SUBMITTING one unaffirmed, and they are
        different rules that happen to meet on the same handler.
        """
        with self.assertRaises(HTTPException) as c:
            _call(
                {**DRAFT, "cp_signature": INHERITED},
                {"data": {"x": 1}, "status": "submitted",
                 "cp_signature": INHERITED},
            )
        self.assertEqual(c.exception.detail, {"code": "SUBMIT_MISSING_CP_SIGNATURE"})

    def test_the_existing_lock_423_is_untouched(self):
        body = self._body()
        self.assertIn('status_code=423', body)
        self.assertIn('Create an amendment instead', body)

    def test_the_existing_submit_gates_are_untouched(self):
        body = self._body()
        self.assertIn('"code": "SUBMIT_EMPTY_LOG"', body)
        self.assertIn('"code": "SUBMIT_MISSING_CP_SIGNATURE"', body)

    def test_amend_is_a_different_endpoint_and_still_exists(self):
        paths = {getattr(r, "path", "") for r in server.app.routes}
        self.assertIn("/api/logbooks/{logbook_id}/amend", paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
