"""Platform operator + cross-tenant admin scoping (STEP 2b/2c/2d).

Three separate holes are pinned here:

  2b PUT /admin/users/{id}   — get_admin_user checks ROLE ONLY, and "password"
     is in ALLOWED_USER_FIELDS. Any admin of any company could therefore set
     any user's password and log in as them. Cross-tenant ACCOUNT TAKEOVER.
  2c PATCH /admin/users/{id}/approve — matched on _id alone, so any approved
     admin could un-gate a user in any company.
  2d hard-delete / DELETE /owner/companies/{id} — gated on role == "owner",
     which is what EVERY self-serve signup receives and which is API-mutable
     via ALLOWED_USER_FIELDS. Now additionally require_platform_operator.

The platform gate ships in SHADOW mode (PLATFORM_GATES_ENFORCED=False): it logs
and allows, so the gates can land BEFORE the operator flag is bootstrapped
without locking the operator out. These tests cover both modes so flipping the
env var is a one-line change with coverage already written.
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

ADMIN_A = {"_id": "a1", "email": "a@acme.test", "role": "admin",
           "company_id": "companyA", "account_status": "approved"}
ADMIN_B = {"_id": "b1", "email": "b@beta.test", "role": "admin",
           "company_id": "companyB", "account_status": "approved"}
USER_B = {"_id": "victim", "name": "Victim", "email": "v@beta.test", "role": "worker",
          "company_id": "companyB", "account_status": "pending"}
USER_A = {"_id": "colleague", "name": "Colleague", "email": "c@acme.test", "role": "worker",
          "company_id": "companyA", "account_status": "pending"}
OPERATOR = {"_id": "op", "email": "ops@levelog.test", "role": "owner",
            "company_id": "companyZ", "account_status": "approved",
            "is_platform_operator": True}


def _run(coro):
    return asyncio.run(coro)


def _db(users):
    async def _find_one(q, *a, **kw):
        return users.get(str(q.get("_id")))
    db = MagicMock()
    db.users = MagicMock()
    db.users.find_one = AsyncMock(side_effect=_find_one)
    db.users.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    db.whatsapp_contacts = MagicMock()
    db.whatsapp_contacts.update_one = AsyncMock()
    return db


ALL_USERS = {u["_id"]: u for u in (ADMIN_A, ADMIN_B, USER_A, USER_B, OPERATOR)}


# ── 2a: the flag is the anchor, and role is NOT ──────────────────────────────
class TestPlatformOperatorHelper(unittest.TestCase):
    def test_flag_grants(self):
        import server
        self.assertTrue(server.is_platform_operator(OPERATOR))

    def test_owner_role_alone_does_not_grant(self):
        """The whole point: role == 'owner' is what every signup gets."""
        import server
        self.assertFalse(server.is_platform_operator(
            {"role": "owner", "email": "someone@example.com"}))

    def test_email_allowlist_grants(self):
        import server
        with patch.object(server, "PLATFORM_OPERATOR_EMAILS",
                          frozenset({"boot@levelog.test"})):
            self.assertTrue(server.is_platform_operator(
                {"role": "worker", "email": "Boot@LeveLog.test"}))

    def test_empty_email_never_matches(self):
        import server
        with patch.object(server, "PLATFORM_OPERATOR_EMAILS", frozenset({""})):
            self.assertFalse(server.is_platform_operator({"email": ""}))
            self.assertFalse(server.is_platform_operator({}))

    def test_flag_is_in_no_allowlist(self):
        """If is_platform_operator ever enters a field allow-list it becomes
        API-settable and stops being a trust anchor."""
        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(
            encoding="utf-8")
        import re
        for m in re.finditer(r"ALLOWED_[A-Z_]*(?:FIELDS|KEYS)\s*=\s*\{([^}]*)\}", src):
            self.assertNotIn("is_platform_operator", m.group(1),
                             "is_platform_operator leaked into an allow-list")


# ── 2b: cross-tenant account takeover ────────────────────────────────────────
class TestAdminUserUpdateScoping(unittest.TestCase):
    def _call(self, actor, target_id, body=None):
        import server
        with patch("server.db", _db(ALL_USERS)), \
             patch("server.to_query_id", lambda v: v), \
             patch("server.hash_password", lambda p: "hashed"), \
             patch("server.normalize_phone", lambda p: p):
            return _run(server.update_admin_user(
                user_id=target_id, user_data=(body or {"name": "x"}), admin=actor))

    def test_admin_cannot_set_password_on_another_companys_user(self):
        with self.assertRaises(HTTPException) as ctx:
            self._call(ADMIN_A, "victim", {"password": "pwned"})
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_cannot_edit_another_companys_user(self):
        with self.assertRaises(HTTPException) as ctx:
            self._call(ADMIN_A, "victim")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_can_edit_own_companys_user(self):
        self._call(ADMIN_A, "colleague")   # must not raise

    def test_platform_operator_can_edit_across_companies(self):
        self._call(OPERATOR, "victim")     # must not raise


# ── 2c: who may un-gate whom ─────────────────────────────────────────────────
class TestApproveScoping(unittest.TestCase):
    def _call(self, actor, target_id):
        import server
        with patch("server.db", _db(ALL_USERS)), \
             patch("server.to_query_id", lambda v: v):
            return _run(server.admin_approve_user(
                user_id=target_id, current_user=actor))

    def test_admin_cannot_approve_another_companys_user(self):
        with self.assertRaises(HTTPException) as ctx:
            self._call(ADMIN_A, "victim")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_can_approve_own_companys_user(self):
        self._call(ADMIN_A, "colleague")

    def test_platform_operator_can_approve_anyone(self):
        """Required: a new org's first user is pending and is the ONLY member
        of that company, so nobody in-company can approve them."""
        self._call(OPERATOR, "victim")

    def test_unknown_target_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            self._call(OPERATOR, "nope")
        self.assertEqual(ctx.exception.status_code, 404)


# ── 2d: the platform gate, both modes ────────────────────────────────────────
class TestPlatformGate(unittest.TestCase):
    """The one operator gate, `require_operator_404`: the operator passes,
    everyone else gets 404. There is no shadow mode and no env flag."""

    def _gate(self, user):
        import server

        async def go():
            async def fake(**kw):
                return user
            with patch.object(server, "get_current_user", fake):
                return await server.require_operator_404(request=None,
                                                         credentials=None)
        return _run(go())

    def test_operator_passes(self):
        self.assertEqual(self._gate(OPERATOR), OPERATOR)

    def test_non_operators_get_404_including_company_owner(self):
        company_owner = {"_id": "o", "email": "o@acme.test", "role": "owner",
                         "company_id": "companyA", "account_status": "approved"}
        for u in (ADMIN_A, company_owner):
            with self.assertRaises(HTTPException) as ctx:
                self._gate(u)
            self.assertEqual(ctx.exception.status_code, 404)

    def test_there_is_no_shadow_mode(self):
        import server
        self.assertFalse(hasattr(server, "PLATFORM_GATES_ENFORCED"))
        self.assertFalse(hasattr(server, "require_platform_operator"))

    def test_destructive_routes_declare_the_platform_gate(self):
        import server
        want = [("DELETE", "/projects/{project_id}/hard-delete"),
                ("DELETE", "/owner/companies/{company_id}")]
        missing = []
        for verb, path in want:
            ok = False
            for r in server.app.routes:
                if getattr(r, "path", "").replace("/api", "", 1) != path:
                    continue
                if verb not in (getattr(r, "methods", None) or set()):
                    continue
                deps = getattr(getattr(r, "dependant", None), "dependencies", []) or []
                if deps and deps[0].call is server.require_operator_404:
                    ok = True
                    break
            if not ok:
                missing.append(f"{verb} {path}")
        self.assertEqual(missing, [],
                         "lost require_operator_404: " + ", ".join(missing))



# ── The over-gating guard: customer owners must keep their own org ───────────
class TestCustomerOwnerNotOverGated(unittest.TestCase):
    """A fix that locks customer owners out of their own organisation is as
    broken as one that lets them into everyone else's. These pin the
    company-owner side of the classification."""

    COMPANY_OWNER = {"_id": "co", "name": "Owner", "email": "own@acme.test",
                     "role": "owner", "company_id": "companyA",
                     "account_status": "approved"}

    def test_company_owner_can_edit_own_company_user(self):
        import server
        with patch("server.db", _db(ALL_USERS)),              patch("server.to_query_id", lambda v: v),              patch("server.hash_password", lambda p: "hashed"),              patch("server.normalize_phone", lambda p: p):
            _run(server.update_admin_user(
                user_id="colleague", user_data={"name": "renamed"},
                admin=self.COMPANY_OWNER))

    def test_company_owner_can_approve_own_company_user(self):
        import server
        with patch("server.db", _db(ALL_USERS)),              patch("server.to_query_id", lambda v: v):
            _run(server.admin_approve_user(
                user_id="colleague", current_user=self.COMPANY_OWNER))

    def test_company_owner_is_not_a_platform_operator(self):
        """Being a customer owner must never confer platform power."""
        import server
        self.assertFalse(server.is_platform_operator(self.COMPANY_OWNER))



# ── 2e: /owner/* classification, both directions ─────────────────────────────
class TestOwnerRouteClassification(unittest.TestCase):
    """Every /owner/* route is platform-operator only, behind
    `require_operator_404`. The filing-reps, authorization and link-gc-license
    routes used to sit behind `require_company_scope` as well as an inline
    operator check; only the owner portal calls them, so the operator gate is
    the whole of it. The full inventory is tests/test_operator_gate.py."""

    def test_every_owner_route_carries_the_operator_gate(self):
        import server

        def walk(d):
            return any(x.call is server.require_operator_404 or walk(x)
                       for x in d.dependencies)
        ungated = [r.path for r in server.app.routes
                   if getattr(r, "path", "").startswith("/api/owner/")
                   and not walk(r.dependant)]
        self.assertEqual(ungated, [], "/owner/* routes without the operator gate")

    def test_require_company_scope_is_gone(self):
        import server
        self.assertFalse(hasattr(server, "require_company_scope"))


if __name__ == "__main__":
    unittest.main()
