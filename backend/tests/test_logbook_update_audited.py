"""PUT /logbooks/{id} left no trace, and that is what cost four rounds.

create / finalize / amend / delete all wrote an audit entry. update did not --
and it is the ONLY path that bumps `updated_at`, can change `status`, and can
set `is_locked` on an immediate type. A document could go from draft to
SUBMITTED AND FROZEN with nothing recording who did it or when.

WHAT IT COST, concretely. On 2026-08-25 two logs on 588 Thomas
(preshift_signin 12:12:58, toolbox_talk 12:15:05) showed exactly one
`logbook_create` each in the audit trail, and an `updated_at` 3.4s and 5.9s
later. The second write could not be attributed from the trail at all. Every
other writer had to be excluded by reading source -- the freeze sweep (stamps
finalized_by, runs on past dates), photo enhancement (sets photo fields, never
updated_at), the base64 purge, signature-event recording (a different
collection, insert-only) -- to arrive at PUT by elimination rather than by
evidence. One audit row would have named it in seconds.

NO ENFORCEMENT IS ASSERTED HERE. Refusing an unaffirmed submit is a behaviour
change with a live blast radius on an operating jobsite; it belongs in its own
PR after the client-side cause is known. This change only makes the write
visible, and these tests only assert visibility.

    python backend/tests/test_logbook_update_audited.py
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

import server  # noqa: E402

USER = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "companyA",
        "account_status": "approved", "assigned_projects": ["projA"]}
PROJECT = {"_id": "projA", "company_id": "companyA", "name": "588 Thomas"}


def _run(update_body, stored_after):
    """Drive update_logbook against doubles and capture the audit call."""
    captured = {}

    async def fake_audit(action, user_id, resource_type, resource_id, details=None):
        captured["call"] = (action, user_id, resource_type, resource_id, details)

    # BEFORE vs AFTER. update_logbook reads the CURRENT doc first (to authorize,
    # to date-stamp the signature, and to 423 a finalized log) and reads it
    # again after writing. A double that returns the post-write state to the
    # pre-write reads makes an is_locked fixture refuse itself with a 423.
    # The flag flips when the write happens, which is the real ordering.
    state = {"written": False}

    async def logbooks_find_one(q, *a, **kw):
        if state["written"]:
            return dict(stored_after)
        before = dict(stored_after)
        before["is_locked"] = False      # not yet frozen; this write is what freezes it
        before["status"] = "draft"
        # SUBMIT_NO_CONTENT is a separate, real guard: a submit whose effective
        # data is empty is refused before anything is written. These fixtures
        # are about AUDITING, so they carry enough content to get past it
        # rather than silencing it.
        before.setdefault("data", {"entries": [{"topic": "ladders"}]})
        return before

    async def logbooks_update_one(q, upd, *a, **kw):
        state["written"] = True
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
         patch.object(server, "audit_log", fake_audit), \
         patch.object(server, "_remember_other_activities", AsyncMock()):
        asyncio.run(server.update_logbook(
            logbook_id="lb1", data=body, current_user=USER,
        ))
    return captured.get("call")


class UpdateIsAudited(unittest.TestCase):

    def test_an_audit_entry_is_written(self):
        call = _run({"status": "submitted"},
                    {"_id": "lb1", "project_id": "projA", "log_type": "toolbox_talk",
                     "date": "2026-08-25", "status": "submitted",
                     "cp_signature": {"affirmed": True}, "is_locked": True})
        self.assertIsNotNone(call, "PUT /logbooks/{id} still writes no audit entry")

    def test_the_action_names_the_operation(self):
        call = _run({"status": "draft"},
                    {"_id": "lb1", "status": "draft", "cp_signature": None})
        self.assertEqual(call[0], "logbook_update")

    def test_it_records_the_actor(self):
        call = _run({"status": "draft"}, {"_id": "lb1", "status": "draft"})
        self.assertEqual(call[1], "u1")

    def test_it_records_the_logbook_id(self):
        call = _run({"status": "draft"}, {"_id": "lb1", "status": "draft"})
        self.assertEqual((call[2], call[3]), ("logbook", "lb1"))


class WhatTheEntryHasToCarry(unittest.TestCase):
    """The two facts a later reader cannot recover, because the next write
    overwrites both."""

    def test_status_is_recorded(self):
        call = _run({"status": "submitted"},
                    {"_id": "lb1", "status": "submitted", "cp_signature": {"affirmed": True}})
        self.assertEqual(call[4]["status"], "submitted")

    def test_affirmation_is_recorded_and_read_off_the_STORED_doc(self):
        """Not off the request. The entry must describe what was PERSISTED --
        the server stamps cp_signature through _finalize_cp_signature, so the
        request body and the stored value are not the same object."""
        call = _run(
            {"status": "submitted", "cp_signature": {"affirmed": True}},
            # what the DB holds afterwards: unaffirmed, the production shape
            {"_id": "lb1", "status": "submitted",
             "cp_signature": {"affirmedLang": "en", "timestamp": "2026-08-19T15:01:10.726Z"}},
        )
        self.assertIs(call[4]["affirmed"], False,
                      "the entry reported the REQUEST's affirmation, not the "
                      "stored document's")

    def test_affirmed_true_when_the_stored_signature_is_affirmed(self):
        call = _run({"status": "submitted"},
                    {"_id": "lb1", "status": "submitted",
                     "cp_signature": {"affirmed": True}})
        self.assertIs(call[4]["affirmed"], True)

    def test_the_lock_transition_is_recorded(self):
        """An immediate type freezes on submit. Which write froze it is exactly
        what the trail could not answer."""
        call = _run({"status": "submitted"},
                    {"_id": "lb1", "status": "submitted", "is_locked": True,
                     "cp_signature": {"affirmed": True}})
        self.assertIs(call[4]["is_locked"], True)

    def test_log_type_and_date_identify_the_document(self):
        # A signature is present because the server already refuses a submit
        # without one (SUBMIT_MISSING_CP_SIGNATURE). Unaffirmed, which is the
        # production shape and which that guard admits.
        # AFFIRMED: the submit gate refuses an unaffirmed one now, so a
        # fixture that has to REACH the audit call must carry a real signature.
        call = _run({"status": "submitted"},
                    {"_id": "lb1", "log_type": "preshift_signin",
                     "date": "2026-08-25", "status": "submitted",
                     "cp_signature": {"affirmed": True}})
        self.assertEqual(call[4]["log_type"], "preshift_signin")
        self.assertEqual(call[4]["date"], "2026-08-25")


class NothingElseChanged(unittest.TestCase):
    """This PR adds an audit entry. It does not add enforcement."""

    SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text(
        encoding="utf-8")

    def _body(self):
        i = self.SRC.index("async def update_logbook(")
        return self.SRC[i:self.SRC.index("async def _purge_finalized_photo_base64", i)]

    def test_an_unaffirmed_submit_is_NOW_refused(self):
        """INVERTED. It read "enforcement landed -- confirm that was intended".
        It has, and it was: both submit gates now call _is_affirmed_signature
        instead of testing presence.

        The audit entry still records `affirmed` off the STORED doc, which is
        what the assertions below cover. This one only pins that the refusal
        exists, so the two changes cannot be confused for each other."""
        from fastapi import HTTPException as _HTTPException
        with self.assertRaises(_HTTPException) as c:
            _run(
                {"status": "submitted"},
                {"_id": "lb1", "status": "submitted",
                 "cp_signature": {"affirmedLang": "en"}},
            )
        self.assertEqual(c.exception.detail, {"code": "SUBMIT_MISSING_CP_SIGNATURE"})

    def test_the_affirmation_refusal_is_now_here(self):
        """Also inverted. The audit entry and the refusal are separate changes
        that landed in separate PRs; both live in this handler now, and the
        audit entry reports the outcome of the one below it."""
        body = self._body()
        self.assertIn("not _is_affirmed_signature", body)

    def test_the_audit_call_is_after_the_write_not_before(self):
        """It reports what the document BECAME. Auditing before the write would
        record an intention, which is the thing that was already missing."""
        body = self._body()
        self.assertLess(body.index("db.logbooks.update_one"),
                        body.index('audit_log(\n        "logbook_update"'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
