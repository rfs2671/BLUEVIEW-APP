"""A client is not a constraint.

#208 removed the step-1 skip button. Every bundle already installed still has
it, and PATCH /users/me/onboarding-step accepted ANY step from ANY state over
plain HTTP with no precondition beyond membership of VALID_ONBOARDING_STEPS.
Removing an affordance does not remove a state.

TWO TERMINAL STATES, BOTH OF WHICH ASSERT STEP 1 HAPPENED:

  "completed"  claims step 1 ran. Step 1 IS company creation and the only
               writer of company_id, so completed-without-a-company is not a
               state, it is a contradiction. It is also the exact pair a
               pre-existing test asserted as normal (company_id=None,
               step="completed"), which is how the impossible combination
               stayed invisible long enough to trap a live account.

  "skipped"    claimed the user would come back later. For step 1 there was no
               later: _onboarding_in_flight() went False, POST
               /onboarding/company 409'd, _userInOnboarding() stopped
               redirecting, and ALLOWED_USER_FIELDS carries neither company_id
               nor onboarding_step, so no admin and no platform operator could
               repair the account either.

THE REFUSAL IS NARROW ON PURPOSE. A user who HAS a company may write either
value freely - skipping steps 2/3 is a real deferral, finishing is a real
finish. Only the two states that assert step 1 happened are constrained.

NOT ASSERTED HERE, because they were deliberately not built: a
monotonic-forward rule and a role check. Both cheap, neither the trap.

    python backend/tests/test_onboarding_step_preconditions.py
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

NO_COMPANY = {"_id": "u1", "id": "u1", "role": "owner", "company_id": None,
              "onboarding_step": "1"}
MISSING_COMPANY_FIELD = {"_id": "u2", "id": "u2", "role": "owner",
                         "onboarding_step": "1"}
EMPTY_COMPANY = {"_id": "u3", "id": "u3", "role": "owner", "company_id": "",
                 "onboarding_step": "1"}
WITH_COMPANY = {"_id": "u4", "id": "u4", "role": "owner",
                "company_id": "companyA", "onboarding_step": "2"}


def _db():
    async def update_one(q, upd, *a, **kw):
        _db.last_update = upd
        r = MagicMock()
        r.matched_count = 1
        return r
    d = MagicMock()
    d.users.update_one = AsyncMock(side_effect=update_one)
    return d


def _patch_step(user, step):
    _db.last_update = None
    body = server.OnboardingStepUpdate(step=step)
    with patch.object(server, "db", _db()):
        return asyncio.run(
            server.update_onboarding_step(body=body, current_user=user)
        )


class TerminalStatesRequireACompany(unittest.TestCase):
    """The two states that assert step 1 happened."""

    def test_skipped_refused_without_company(self):
        """THE TRAP, at the API rather than in the UI."""
        with self.assertRaises(HTTPException) as c:
            _patch_step(NO_COMPANY, "skipped")
        self.assertEqual(c.exception.status_code, 409)

    def test_completed_refused_without_company(self):
        with self.assertRaises(HTTPException) as c:
            _patch_step(NO_COMPANY, "completed")
        self.assertEqual(c.exception.status_code, 409)

    def test_absent_company_field_refused(self):
        """A legacy row has no key at all; same fact, same refusal."""
        with self.assertRaises(HTTPException) as c:
            _patch_step(MISSING_COMPANY_FIELD, "skipped")
        self.assertEqual(c.exception.status_code, 409)

    def test_empty_string_company_refused(self):
        """"" is falsy everywhere else in the tenancy code; here too."""
        with self.assertRaises(HTTPException) as c:
            _patch_step(EMPTY_COMPANY, "completed")
        self.assertEqual(c.exception.status_code, 409)

    def test_nothing_is_written_when_refused(self):
        """A refusal that still wrote would be worse than no refusal."""
        try:
            _patch_step(NO_COMPANY, "skipped")
        except HTTPException:
            pass
        self.assertIsNone(_db.last_update,
                          "the user document was written despite the 409")

    def test_the_message_names_the_step_that_fixes_it(self):
        with self.assertRaises(HTTPException) as c:
            _patch_step(NO_COMPANY, "skipped")
        self.assertIn("step 1", c.exception.detail.lower())


class TheRefusalStaysNarrow(unittest.TestCase):
    """A guard that refuses too much is as wrong as one that refuses nothing."""

    def test_skipped_allowed_with_a_company(self):
        """Skipping steps 2/3 is a real deferral and must keep working."""
        out = _patch_step(WITH_COMPANY, "skipped")
        self.assertEqual(out["step"], "skipped")

    def test_completed_allowed_with_a_company(self):
        out = _patch_step(WITH_COMPANY, "completed")
        self.assertEqual(out["step"], "completed")
        self.assertIsNotNone(out["completed_at"],
                             "completed still stamps onboarding_completed_at")

    def test_numbered_steps_still_free_without_a_company(self):
        """Steps 1-4 are PROGRESS, not claims that step 1 finished. A
        company-less user advancing through the flow is the normal path and
        must not be refused - that would break onboarding itself."""
        for step in ("1", "2", "3", "4"):
            out = _patch_step(NO_COMPANY, step)
            self.assertEqual(out["step"], step)

    def test_invalid_step_is_still_422_not_409(self):
        """The new guard must not swallow the existing validation, and the two
        codes mean different things: 422 malformed, 409 wrong account state."""
        with self.assertRaises(HTTPException) as c:
            _patch_step(WITH_COMPANY, "banana")
        self.assertEqual(c.exception.status_code, 422)

    def test_invalid_step_checked_before_the_company_rule(self):
        """A company-less user sending nonsense gets 422, not a misleading 409
        about companies."""
        with self.assertRaises(HTTPException) as c:
            _patch_step(NO_COMPANY, "banana")
        self.assertEqual(c.exception.status_code, 422)


class WhatWasDeliberatelyNotBuilt(unittest.TestCase):
    """Pinned so a later reader does not mistake absence for oversight."""

    def test_no_monotonic_forward_rule(self):
        """The frontend legitimately jumps (skip 2 -> 3), so encoding step
        ordering here would make a UX change a backend change."""
        out = _patch_step(WITH_COMPANY, "1")
        self.assertEqual(out["step"], "1")

    def test_no_role_restriction(self):
        """Not the trap. A site device PATCHing its own onboarding step is
        meaningless rather than dangerous."""
        device = {"_id": "d1", "id": "d1", "role": "site_device",
                  "site_mode": True, "company_id": "companyA"}
        out = _patch_step(device, "completed")
        self.assertEqual(out["step"], "completed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
