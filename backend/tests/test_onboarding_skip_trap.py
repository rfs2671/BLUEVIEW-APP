"""'skipped' was a one-tap permanent trap. This is the way out.

WHAT IT WAS. app/onboarding.jsx step 1 offered "I'll do this later", which
PATCHed onboarding_step="skipped". That state is terminal on both sides:

    _userInOnboarding()      false  -> RouteGuard never redirects here again
    _onboarding_in_flight()  False  -> POST /onboarding/company 409s
    ALLOWED_USER_FIELDS             -> no company_id, no onboarding_step, so no
                                       admin and no platform operator could
                                       repair the account either

So the account could never acquire a company_id through any in-app path, at any
privilege level. Every company-scoped read resolves to the unsatisfiable filter
and every company-scoped write refuses. One tap on the FIRST screen of the
product, permanent — and it is the only in-app route to that state, reachable
exclusively by declining the very step that would have prevented it.

test@ios.com sits in exactly this state in production today.

THE DISCRIMINATOR, which is the whole design question here: how do you re-open
the flow for someone stuck without re-opening it for everyone who finished?

    By the COMPANY, not by the step.

`onboarding_step` is a CLAIM about progress, and it is precisely the field that
lies. `company_id` is the FACT: step 1 is the only writer, and nothing ever
unsets it. Its presence is proof step 1 actually happened. So a finished user
gets False and cannot replay; a stuck user gets True and can finish.

    python backend/tests/test_onboarding_skip_trap.py
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

# ── The populations ──────────────────────────────────────────────────────────

# THE TRAP, as it exists in production on test@ios.com.
SKIPPED_NO_COMPANY = {
    "_id": "u_trap", "id": "u_trap", "email": "test@ios.com", "role": "owner",
    "company_id": None, "onboarding_step": "skipped",
    "account_status": "pending",
}
# Same trap, reached the other way: a legacy row with no step field at all.
NO_STEP_NO_COMPANY = {
    "_id": "u_legacy", "id": "u_legacy", "role": "owner", "company_id": None,
    "account_status": "approved",
}
# Finished properly. MUST NOT be able to replay step 1.
COMPLETED_WITH_COMPANY = {
    "_id": "u_done", "id": "u_done", "role": "owner",
    "company_id": "companyA", "onboarding_step": "completed",
    "account_status": "approved",
}
# Skipped, but HAS a company — skipped steps 2/3, which is legitimate.
SKIPPED_WITH_COMPANY = {
    "_id": "u_ok", "id": "u_ok", "role": "owner", "company_id": "companyA",
    "onboarding_step": "skipped", "account_status": "approved",
}
# The 622 pre-B3 production users: no step field, but they have a company.
PRE_B3_WITH_COMPANY = {
    "_id": "u_pre", "id": "u_pre", "role": "owner", "company_id": "companyB",
    "account_status": "approved",
}
MID_FLIGHT = {
    "_id": "u_mid", "id": "u_mid", "role": "owner", "company_id": None,
    "onboarding_step": "2", "account_status": "approved",
}


class InFlightDiscriminator(unittest.TestCase):
    """Open for the stuck, closed for the finished."""

    def test_skipped_without_company_is_open(self):
        """THE FIX. test@ios.com's exact document."""
        self.assertTrue(server._onboarding_in_flight(SKIPPED_NO_COMPANY))

    def test_no_step_field_without_company_is_open(self):
        """A legacy row is stuck in the same way and deserves the same exit."""
        self.assertTrue(server._onboarding_in_flight(NO_STEP_NO_COMPANY))

    def test_completed_with_company_stays_closed(self):
        """The replay guard the 409 existed for. This must not regress."""
        self.assertFalse(server._onboarding_in_flight(COMPLETED_WITH_COMPANY))

    def test_skipped_WITH_company_stays_closed(self):
        """Skipping steps 2/3 is legitimate and does not re-open the flow —
        the company is what decides, not the word 'skipped'."""
        self.assertFalse(server._onboarding_in_flight(SKIPPED_WITH_COMPANY))

    def test_pre_b3_user_with_company_stays_closed(self):
        """The 622 existing production users must never see this flow."""
        self.assertFalse(server._onboarding_in_flight(PRE_B3_WITH_COMPANY))

    def test_mid_flight_unchanged(self):
        self.assertTrue(server._onboarding_in_flight(MID_FLIGHT))

    def test_empty_string_company_counts_as_no_company(self):
        """"" is falsy everywhere else in the tenancy code; here too."""
        self.assertTrue(server._onboarding_in_flight(
            {"onboarding_step": "completed", "company_id": ""}))


class CompanyLessOwnerCanCompleteStepOne(unittest.TestCase):
    """The end-to-end the whole PR exists for: a trapped account gets out."""

    def _db(self):
        async def companies_find_one(q, *a, **kw):
            return None            # no existing company by that name

        async def companies_insert_one(doc, *a, **kw):
            r = MagicMock()
            r.inserted_id = "newCompany1"
            return r

        async def users_update_one(q, upd, *a, **kw):
            self.user_update = upd
            r = MagicMock()
            r.matched_count = 1
            return r

        db = MagicMock()
        db.companies.find_one = AsyncMock(side_effect=companies_find_one)
        db.companies.insert_one = AsyncMock(side_effect=companies_insert_one)
        db.users.update_one = AsyncMock(side_effect=users_update_one)
        return db

    def _submit(self, user, name="Blueview Builders Inc"):
        self.user_update = None
        body = server.OnboardingCompanyCreate(name=name)
        with patch.object(server, "db", self._db()):
            return asyncio.run(
                server.onboarding_create_company(body=body, current_user=user)
            )

    def test_trapped_account_can_create_its_company(self):
        """onboarding_step='skipped', company_id=None -> it works."""
        out = self._submit(SKIPPED_NO_COMPANY)
        self.assertTrue(out)

    def test_and_the_company_id_is_actually_written_to_the_user(self):
        """Reaching the endpoint is not enough — the LINK is the repair."""
        self._submit(SKIPPED_NO_COMPANY)
        self.assertIsNotNone(self.user_update, "no write to the user doc")
        setops = self.user_update.get("$set", {})
        self.assertEqual(setops.get("company_id"), "newCompany1")
        self.assertEqual(setops.get("company_name"), "Blueview Builders Inc")

    def test_pending_status_does_not_block_it(self):
        """test@ios.com is PENDING. /onboarding/company deliberately carries no
        require_approved, so the Apple reviewer is not gated out of the one
        step that unsticks the account."""
        self.assertEqual(SKIPPED_NO_COMPANY["account_status"], "pending")
        self.assertTrue(self._submit(SKIPPED_NO_COMPANY))

    def test_finished_account_still_cannot_replay(self):
        with self.assertRaises(HTTPException) as c:
            self._submit(COMPLETED_WITH_COMPANY)
        self.assertEqual(c.exception.status_code, 409)

    def test_account_that_already_has_a_company_is_refused(self):
        """Two guards stand here — the flow gate and an explicit
        already-linked check. Either alone would do; both is deliberate."""
        with self.assertRaises(HTTPException) as c:
            self._submit(SKIPPED_WITH_COMPANY)
        self.assertEqual(c.exception.status_code, 409)


class WideningDoesNotLeakIntoTheOtherSteps(unittest.TestCase):
    """/onboarding/project and /onboarding/filing-reps share the gate. They must
    still refuse a company-less caller — widening the gate must not let one mint
    a project or push filing reps."""

    def _src_window(self, fn_name):
        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(
            encoding="utf-8")
        i = src.index(f"async def {fn_name}(")
        return src[i:i + 2500]

    def test_onboarding_project_still_requires_a_company(self):
        w = self._src_window("onboarding_create_project")
        self.assertIn("company_id = current_user.get(\"company_id\")", w)
        self.assertIn("if not company_id:", w)
        self.assertIn("Step 1 must complete", w)

    def test_onboarding_filing_reps_still_requires_a_company(self):
        w = self._src_window("onboarding_add_filing_reps")
        self.assertIn("if not company_id:", w)


if __name__ == "__main__":
    unittest.main(verbosity=2)
