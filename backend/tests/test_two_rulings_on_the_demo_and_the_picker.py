"""Two operator rulings, each closing a gap the surrounding change left open.

    python -m pytest backend/tests/test_two_rulings_on_the_demo_and_the_picker.py

── RULING 1: A DEMO PRINCIPAL SAVES NOTHING, INCLUDING THE STAMP ───────────

`demo_guard` refuses by HTTP METHOD. `_record_client_version` fires from inside
`get_current_user`, on a GET, below that boundary entirely — a fire-and-forget
`db.users.update_one` that stamps which install is on the other end. So the one
write that survived "nothing is saved" was the one nobody auditing *writes*
would look at, because it lives on a *read* path.

The test is written from the demo side rather than the telemetry side: the
question is not "does this helper have a guard" but "does a demo GET leave a
mark". A test that asserted the former would pass over a second stamp added
somewhere else tomorrow.

── RULING 2: THE PICKER ASKS A DIFFERENT QUESTION FROM THE ROSTER ──────────

`ADMIN_MANAGED_ROLES` is right for User Management — admins belong to the
platform operator — but it narrowed all three callers of `adminUsersAPI.getAll`,
and one of them is a PICKER: `app/admin/superintendent.jsx` links the
construction superintendent of a job, and its own comment records why it needs
everyone ("Michael is role 'cp' and IS the construction superintendent"). A
company admin who is also the CS on his own job became unlinkable.

THE ASSERTION THAT MATTERS HERE IS THE NEGATIVE ONE. An opt-in that widened the
TENANT scope as well as the role scope would turn a UI convenience into a
cross-tenant read, and it would look identical on the screen that asked for it.
So the widening is pinned in both directions: roles yes, company never.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_rulings")

import server  # noqa: E402


def _run(coro):
    """`asyncio.run`, NOT `get_event_loop().run_until_complete`.

    The latter passes alone and fails in a suite: once any other module has
    called `asyncio.run` (TestClient does), the thread has no current loop and
    `get_event_loop()` raises "There is no current event loop". This file was
    written with it and went green alone, then failed eight tests deep in a
    full run -- an isolation bug in the test, reported as a defect in the
    product it was pointed at.

    Each call gets a fresh loop, so anything that must run in the SAME loop as
    the code under test (a fire-and-forget `create_task`) has to be awaited
    inside one coroutine rather than across two calls.
    """
    return asyncio.run(coro)


# ── RULING 1 ────────────────────────────────────────────────────────────────


class ADemoGetLeavesNoStamp(unittest.TestCase):
    """`_record_client_version` must not fire for a demo principal."""

    def _call_get_current_user(self, role):
        """Drive the real `get_current_user` and report whether the stamp fired.

        THE STAMP IS FIRE-AND-FORGET (`asyncio.create_task`), so the way to
        observe it is to patch the coroutine it schedules, not to wait on it.
        Waiting would be a race, and a race that passes on a fast machine is
        the kind of green this repo has been burned by.
        """
        uid = "6a68b16ebe9c27dedf5cf47f"
        doc = {
            "_id": server.to_query_id(uid), "id": uid,
            "email": "someone@example.com", "name": "Someone",
            "role": role, "company_id": "c1",
            "account_status": "approved",
            "client_version": "0.0.1",
        }
        db = MagicMock()
        db.users = MagicMock()
        db.users.find_one = AsyncMock(return_value=dict(doc))

        request = MagicMock()
        request.headers = {"x-client-version": "9.9.9"}

        token = server.create_token(uid, doc["email"], role)

        orig_db = server.db
        server.db = db
        try:
            with patch.object(server, "_record_client_version",
                              new=AsyncMock()) as stamp:
                async def _drive():
                    await server.get_current_user(
                        request=request, credentials=None, token=token)
                    # SAME LOOP, deliberately: the stamp is scheduled with
                    # `create_task`, so it only ever starts on the loop that
                    # scheduled it. Yielding from a second `asyncio.run` would
                    # count zero every time and the test would pass by accident.
                    await asyncio.sleep(0)
                _run(_drive())
                return stamp.await_count + stamp.call_count
        finally:
            server.db = orig_db

    def test_a_demo_principal_is_not_stamped(self):
        self.assertEqual(
            self._call_get_current_user(server.ROLE_DEMO), 0,
            "a demo GET wrote client_version — 'nothing is saved' is false")

    def test_a_real_account_IS_still_stamped(self):
        """THE OTHER HALF, AND IT IS NOT A FORMALITY.

        The cheapest way to pass the test above is to break the stamp for
        everyone, and the admin surface that answers "whose phone is stranded"
        would go quietly blank — a loud feature becoming a silent one, which is
        the trade this repo's own comment at the call site warns about.
        """
        self.assertGreater(
            self._call_get_current_user("cp"), 0,
            "the stamp stopped firing for real accounts too")

    def test_the_decision_reads_the_document_not_the_claim(self):
        """A promoted demo carries "demo" in its JWT for up to 30 days, because
        `_reissue_token_if_stale` copies claims forward. If this read the claim,
        a paying customer's install would stop being stamped for a month."""
        uid = "6a68b16ebe9c27dedf5cf47f"
        doc = {
            "_id": server.to_query_id(uid), "id": uid,
            "email": "promoted@example.com", "name": "Promoted",
            "role": "cp",                      # the DOCUMENT says cp
            "company_id": "c1", "account_status": "approved",
            "client_version": "0.0.1",
        }
        db = MagicMock()
        db.users = MagicMock()
        db.users.find_one = AsyncMock(return_value=dict(doc))
        request = MagicMock()
        request.headers = {"x-client-version": "9.9.9"}
        # the TOKEN still says demo
        token = server.create_token(uid, doc["email"], server.ROLE_DEMO)

        orig_db = server.db
        server.db = db
        try:
            with patch.object(server, "_record_client_version",
                              new=AsyncMock()) as stamp:
                async def _drive():
                    await server.get_current_user(
                        request=request, credentials=None, token=token)
                    await asyncio.sleep(0)
                _run(_drive())
                self.assertGreater(
                    stamp.await_count + stamp.call_count, 0,
                    "a promoted account was judged by its stale token claim")
        finally:
            server.db = orig_db


# ── RULING 2 ────────────────────────────────────────────────────────────────


class TheOptInWidensRolesAndNeverCompany(unittest.TestCase):
    """`include_all_roles` may drop the role clause. It may not touch tenancy."""

    def _query_for(self, *, operator, company_id, include_all_roles):
        """The MONGO QUERY the route builds, captured from the real handler.

        Asserting on the query rather than on returned rows is deliberate: the
        rows are whatever the double was told to hold, and would agree with any
        filter at all. The query is the thing under test.
        """
        captured = {}

        # ASYNC, because `paginated_query` is — patch.object gives an
        # AsyncMock for an async target, and a sync side_effect returning a
        # coroutine would be awaited once and hand the handler the coroutine
        # itself. That failure reads as "'coroutine' object has no attribute
        # 'get'" inside the product, which looks like a product bug.
        async def _paginated(coll, query, **kw):
            captured["query"] = query
            return {"items": [], "total": 0, "limit": kw.get("limit", 50),
                    "skip": kw.get("skip", 0), "has_more": False}

        user = {"_id": "u1", "id": "u1", "email": "a@b.c", "role": "admin",
                "company_id": company_id, "account_status": "approved"}
        if operator:
            user["is_platform_operator"] = True

        with patch.object(server, "paginated_query", side_effect=_paginated):
            _run(server.get_admin_users(
                current_user=user, limit=50, skip=0,
                include_all_roles=include_all_roles))
        return captured["query"]

    def test_the_default_still_hides_admins(self):
        q = self._query_for(operator=False, company_id="c1",
                            include_all_roles=False)
        self.assertEqual(q.get("company_id"), "c1")
        self.assertEqual(q.get("role"), {"$in": list(server.ADMIN_MANAGED_ROLES)},
                         "User Management stopped applying the ruling")

    def test_the_opt_in_drops_the_role_clause(self):
        q = self._query_for(operator=False, company_id="c1",
                            include_all_roles=True)
        self.assertNotIn("role", q,
                         "include_all_roles did not widen the roles")

    def test_the_opt_in_NEVER_widens_the_company(self):
        """The negative this whole parameter has to earn."""
        q = self._query_for(operator=False, company_id="c1",
                            include_all_roles=True)
        self.assertEqual(
            q.get("company_id"), "c1",
            "include_all_roles reached outside the caller's company — "
            "a UI convenience became a cross-tenant read")

    def test_a_caller_with_no_company_still_sees_nobody(self):
        """The unsatisfiable filter must survive the opt-in. An orphan account
        asking for 'all roles' must not be handed the platform."""
        q = self._query_for(operator=False, company_id=None,
                            include_all_roles=True)
        self.assertEqual(q.get("_id"), None)
        self.assertNotIn("company_id", q)

    def test_the_operator_is_unchanged_either_way(self):
        for flag in (False, True):
            q = self._query_for(operator=True, company_id="c1",
                                include_all_roles=flag)
            self.assertNotIn("company_id", q)
            self.assertNotIn("role", q)


class TheCallersAreWhatTheRulingNamed(unittest.TestCase):
    """The picker opts in; the roster does not.

    A census over the three call sites, because the defect this fixes was
    exactly that one change moved all three at once.
    """

    ROOT = Path(__file__).resolve().parent.parent.parent / "frontend"

    def _src(self, rel):
        return (self.ROOT / rel).read_text(encoding="utf-8")

    def test_the_superintendent_picker_opts_in(self):
        src = self._src("app/admin/superintendent.jsx")
        self.assertIn("includeAllRoles: true", src,
                      "the screen that links a CS cannot see an admin CS")

    def test_user_management_does_not(self):
        src = self._src("app/admin/users.jsx")
        self.assertNotIn("includeAllRoles", src,
                         "the management roster opted out of the ruling")

    def test_the_default_is_false_at_the_client_too(self):
        src = self._src("src/utils/api.js")
        self.assertIn("includeAllRoles = false", src,
                      "the client default would undo the ruling for everyone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
