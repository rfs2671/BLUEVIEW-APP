"""A filed log cannot be put back to draft, edited, and re-filed under the
signature that was given for different content (security audit C1 / P2).

WHAT WAS OPEN. update_logbook wrote `update["status"] = data.status` with no
check on which way the status moved, and the only filed-log guard
(FILED_LOG_DATA_IMMUTABLE) fires when the request carries `data`. So, for an
end-of-day log that is filed but not yet locked by the nightly sweep:

  1. PUT {"status": "draft"}          no data -> no guard -> status is draft
  2. PUT {"data": <new content>}      stored status is draft -> accepted;
                                      cp_signature untouched, still affirmed
  3. PUT {"status": "submitted"}      _eff_sig falls back to the stored,
                                      affirmed signature -> filed again

and the ledger kept one row, hashed over the OLD content. Step 3 is optional:
the sweep seals any log carrying an affirmed signature. PUT also took
{"status": "withdrawn"}, skipping /withdraw's rules.

THE RULING: refuse any status change away from a stored "submitted"; accept
only known values; if data changes on a signed draft, clear `affirmed` so it
needs a fresh signature.

Production, read 2026-10-13: all 433 affirmed logs are `submitted`, zero are
affirmed drafts -- so clearing `affirmed` touches no flow anyone uses.
"""

import asyncio
import copy
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
PROJECT = {"_id": "projA", "company_id": "companyA", "name": "588 Thomas"}

SIGNED = {"paths": "M0 0 L9 9", "affirmed": True,
          "affirmedAt": "2026-10-13T12:00:00Z", "signerName": "R Ruiz"}
FRESH = {"paths": "M1 1 L8 8", "affirmed": True,
         "affirmedAt": "2026-10-13T17:00:00Z", "signerName": "R Ruiz"}
ORIGINAL = {"activities": [{"company": "Vanguard", "work_description": "Deck pour"}]}
REWRITTEN = {"activities": [{"company": "Vanguard", "work_description": "NOTHING HAPPENED"}]}


def _filed():
    return {"_id": "lb1", "project_id": "projA", "log_type": "daily_jobsite",
            "date": "2026-10-13", "status": "submitted", "is_locked": False,
            "cp_signature": dict(SIGNED), "signed_by": "u2",
            "data": copy.deepcopy(ORIGINAL)}


def _signed_draft():
    d = _filed()
    d["status"] = "draft"
    return d


class _Store:
    """One logbook; every $set lands on it, as Mongo would."""

    def __init__(self, doc):
        self.doc = doc

    def db(self):
        async def find_one(q, *a, **kw):
            return copy.deepcopy(self.doc)

        async def update_one(q, upd, *a, **kw):
            for k, v in (upd.get("$set") or {}).items():
                cur = self.doc
                parts = k.split(".")
                for p in parts[:-1]:
                    cur = cur.setdefault(p, {})
                cur[parts[-1]] = copy.deepcopy(v)
            r = MagicMock()
            r.matched_count = 1
            return r

        async def projects_find_one(q, *a, **kw):
            return dict(PROJECT)

        db = MagicMock()
        db.logbooks.find_one = AsyncMock(side_effect=find_one)
        db.logbooks.update_one = AsyncMock(side_effect=update_one)
        db.projects.find_one = AsyncMock(side_effect=projects_find_one)
        return db

    def put(self, body):
        """Returns 200, or (status, code) of the refusal."""
        with patch.object(server, "db", self.db()), \
             patch.object(server, "audit_log", AsyncMock()), \
             patch.object(server, "_remember_other_activities", AsyncMock()), \
             patch.object(server, "ensure_signature_ledger_row", AsyncMock()), \
             patch.object(server, "_note_signature_of_another_account", AsyncMock()), \
             patch.object(server, "_refuse_if_not_the_superintendent", AsyncMock()):
            try:
                asyncio.run(server.update_logbook(
                    logbook_id="lb1", data=server.LogbookUpdate(**body),
                    current_user=ADMIN))
                return 200
            except HTTPException as e:
                d = e.detail
                return (e.status_code, d.get("code") if isinstance(d, dict) else d)


class TheThreeStepChainIsBroken(unittest.TestCase):
    def test_the_old_signature_never_ends_up_over_new_content(self):
        s = _Store(_filed())
        s.put({"status": "draft"})
        s.put({"data": REWRITTEN})
        s.put({"status": "submitted"})
        bad = (s.doc["data"] == REWRITTEN
               and s.doc["status"] == "submitted"
               and (s.doc.get("cp_signature") or {}).get("affirmed") is True)
        self.assertFalse(bad, f"re-filed under the old signature: {s.doc}")
        self.assertEqual(s.doc["data"], ORIGINAL)


class AFiledLogNeverLeavesSubmitted(unittest.TestCase):
    def test_a_status_only_downgrade_is_refused_and_nothing_moves(self):
        s = _Store(_filed())
        self.assertEqual(s.put({"status": "draft"}),
                         (409, "FILED_LOG_DATA_IMMUTABLE"))
        self.assertEqual(s.doc["status"], "submitted")

    def test_withdrawn_through_PUT_is_refused_on_a_filed_log(self):
        s = _Store(_filed())
        st = s.put({"status": "withdrawn"})
        self.assertNotEqual(st, 200)
        self.assertEqual(s.doc["status"], "submitted")

    def test_resubmitting_a_filed_log_unchanged_is_still_accepted(self):
        """A drain that replays status 'submitted' with no data is idempotent,
        not a downgrade."""
        self.assertEqual(_Store(_filed()).put({"status": "submitted"}), 200)


class OnlyKnownStatusesAreAccepted(unittest.TestCase):
    def test_withdrawn_through_PUT_is_refused_even_on_a_draft(self):
        """/withdraw has its own rules (amendments only, signed); PUT must not
        be a way round them."""
        d = _signed_draft()
        d["cp_signature"] = None
        s = _Store(d)
        self.assertEqual(s.put({"status": "withdrawn"}), (422, "LOGBOOK_STATUS_UNKNOWN"))
        self.assertEqual(s.doc["status"], "draft")

    def test_an_unknown_status_is_refused(self):
        d = _signed_draft()
        d["cp_signature"] = None
        for bad in ("Submitted", "locked", "approved", ""):
            s = _Store(copy.deepcopy(d))
            self.assertEqual(s.put({"status": bad}), (422, "LOGBOOK_STATUS_UNKNOWN"), bad)


class EditingASignedDraftNeedsAFreshSignature(unittest.TestCase):
    def test_new_data_clears_affirmed(self):
        s = _Store(_signed_draft())
        self.assertEqual(s.put({"data": REWRITTEN}), 200)
        self.assertIs(s.doc["cp_signature"].get("affirmed"), False)

    def test_resending_the_SAME_signature_with_new_data_still_clears_it(self):
        """Every editor re-sends cp_signature on every save; an old mark sent
        again is not a fresh one."""
        s = _Store(_signed_draft())
        s.put({"data": REWRITTEN, "cp_signature": dict(SIGNED)})
        self.assertIs(s.doc["cp_signature"].get("affirmed"), False)

    def test_and_it_cannot_then_be_filed_without_signing_again(self):
        s = _Store(_signed_draft())
        s.put({"data": REWRITTEN})
        self.assertEqual(s.put({"status": "submitted"}),
                         (400, "SUBMIT_MISSING_CP_SIGNATURE"))

    def test_nor_in_one_request_with_the_stale_signature(self):
        s = _Store(_signed_draft())
        self.assertEqual(
            s.put({"data": REWRITTEN, "cp_signature": dict(SIGNED),
                   "status": "submitted"}),
            (400, "SUBMIT_MISSING_CP_SIGNATURE"))
        self.assertEqual(s.doc["status"], "draft")

    def test_a_FRESH_signature_with_the_new_data_files(self):
        s = _Store(_signed_draft())
        self.assertEqual(s.put({"data": REWRITTEN, "cp_signature": dict(FRESH),
                                "status": "submitted"}), 200)
        self.assertEqual(s.doc["status"], "submitted")
        self.assertIs(s.doc["cp_signature"].get("affirmed"), True)

    def test_unchanged_data_keeps_the_signature(self):
        """The submit request re-sends the same data; that is not an edit."""
        s = _Store(_signed_draft())
        s.put({"data": copy.deepcopy(ORIGINAL), "cp_signature": dict(SIGNED)})
        self.assertIs(s.doc["cp_signature"].get("affirmed"), True)


class OrdinaryDraftingIsUntouched(unittest.TestCase):
    def test_an_unsigned_draft_still_takes_edits_and_files(self):
        d = _signed_draft()
        d["cp_signature"] = None
        s = _Store(d)
        self.assertEqual(s.put({"data": REWRITTEN, "status": "draft"}), 200)
        self.assertEqual(s.put({"cp_signature": dict(FRESH),
                                "status": "submitted"}), 200)
        self.assertEqual(s.doc["status"], "submitted")


if __name__ == "__main__":
    unittest.main()
