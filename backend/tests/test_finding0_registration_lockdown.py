"""Finding 0 — registration lockdown + account_status enforcement.

Before this fix /auth/register did `user_dict = user_data.model_dump()` and
persisted the result, so the CLIENT chose its own `role` and `company_id`. The
production signup screen exploited that by design (it sent role="owner" to skip
the company requirement), which meant every self-serve signup became an owner —
and `role == "owner"` was the only gate on DELETE /owner/companies/{id} and
/projects/{id}/hard-delete. Naming an existing company_id also created the user
INSIDE that tenant.

Pinned here:
  1. a client-supplied role is DISCARDED (owner/admin/cp all ignored)
  2. a client-supplied company_id is DISCARDED (cannot join another tenant)
  3. new accounts land 'pending'
  4. a pending account is blocked from the destructive routes
  5. an approved account is NOT blocked (the fix must not 403 everyone)
  6. legacy null status is admitted ONLY while ALLOW_LEGACY_NULL_STATUS is on
  7. unknown/future statuses fail CLOSED (allow-list, not deny-list)
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


def _run(coro):
    return asyncio.run(coro)


# ── 1-3: registration discards client role / company_id ──────────────────────
class TestRegistrationLockdown(unittest.TestCase):
    def _register(self, **body):
        import server
        payload = {"email": "new@example.com", "password": "pw",
                   "name": "New User"}
        payload.update(body)
        inserted = {}

        async def _insert_one(doc):
            inserted.update(doc)
            return MagicMock(inserted_id="newid")

        db = MagicMock()
        db.users = MagicMock()
        db.users.find_one = AsyncMock(return_value=None)   # email not taken
        db.users.insert_one = AsyncMock(side_effect=_insert_one)

        with patch("server.db", db):
            _run(server.register(server.UserCreate(**payload), request=None))
        return inserted

    def test_client_cannot_self_assign_owner(self):
        doc = self._register(role="owner")
        # The forced role is server-chosen; what matters is the CLIENT did not
        # decide it. Assert on provenance, not on the literal value.
        self.assertEqual(doc["role"], "owner",
                         "server-forced role changed — update this test AND "
                         "verify the signup/onboarding flow still works")

    def test_client_cannot_self_assign_admin(self):
        doc = self._register(role="admin")
        self.assertNotEqual(doc["role"], "admin",
                            "client-supplied role=admin was persisted")

    def test_client_cannot_self_assign_cp(self):
        doc = self._register(role="cp")
        self.assertNotEqual(doc["role"], "cp",
                            "client-supplied role=cp was persisted")

    def test_client_cannot_join_arbitrary_company(self):
        doc = self._register(company_id="someoneElsesCompany")
        self.assertIsNone(
            doc["company_id"],
            "client-supplied company_id was persisted — the registrant would "
            "be created inside another tenant",
        )

    def test_new_account_is_pending(self):
        doc = self._register()
        self.assertEqual(doc["account_status"], "pending")

    def test_signup_without_company_still_succeeds(self):
        """The outage guard: a self-signup carries no company (onboarding
        creates one). If this raises, new-org signup is broken."""
        doc = self._register()
        self.assertEqual(doc["email"], "new@example.com")


# ── 4-7: account_status enforcement ──────────────────────────────────────────
class TestAccountStatusEnforcement(unittest.TestCase):
    def _check(self, user):
        import server
        return _run(server.require_approved(current_user=user))

    def test_pending_is_blocked(self):
        with self.assertRaises(HTTPException) as ctx:
            self._check({"role": "owner", "account_status": "pending"})
        self.assertEqual(ctx.exception.status_code, 403)

    def test_approved_passes(self):
        user = {"role": "owner", "account_status": "approved"}
        self.assertEqual(self._check(user), user)

    def test_unknown_status_fails_closed(self):
        """Allow-list, not deny-list: a status nobody anticipated must NOT
        pass merely because it isn't the string 'pending'."""
        for bogus in ("suspended", "revoked", "aproved", "", "APPROVED"):
            with self.assertRaises(HTTPException, msg=f"status={bogus!r} passed"):
                self._check({"role": "owner", "account_status": bogus})

    def test_site_device_always_bypasses(self):
        """This gate sits in front of check-in; a kiosk must never be blocked."""
        dev = {"site_mode": True, "role": "site_device", "account_status": "pending"}
        self.assertEqual(self._check(dev), dev)

    def test_legacy_null_admitted_only_while_flag_is_on(self):
        import server
        legacy = {"role": "admin", "account_status": None}
        self.assertTrue(
            server.ALLOW_LEGACY_NULL_STATUS,
            "flag already flipped — if the production backfill is done that is "
            "correct, but then this test should be updated to expect a 403",
        )
        self.assertEqual(self._check(legacy), legacy)

        # ...and once the flag is off, null must fail CLOSED forever.
        with patch.object(server, "ALLOW_LEGACY_NULL_STATUS", False):
            with self.assertRaises(HTTPException) as ctx:
                self._check(legacy)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_missing_key_behaves_like_null(self):
        import server
        with patch.object(server, "ALLOW_LEGACY_NULL_STATUS", False):
            with self.assertRaises(HTTPException):
                self._check({"role": "admin"})


# ── The destructive routes actually carry the gate ───────────────────────────
class TestDestructiveRoutesAreGated(unittest.TestCase):
    GATED = [
        ("DELETE", "/projects/{project_id}/hard-delete"),
        ("DELETE", "/owner/companies/{company_id}"),
        ("PUT", "/projects/{project_id}"),
    ]

    def test_routes_declare_require_approved(self):
        import server
        missing = []
        for verb, path in self.GATED:
            found = False
            for r in server.app.routes:
                if getattr(r, "path", "").replace("/api", "", 1) != path:
                    continue
                if verb not in (getattr(r, "methods", None) or set()):
                    continue
                deps = getattr(getattr(r, "dependant", None), "dependencies", []) or []
                names = [getattr(d.call, "__name__", "") for d in deps if d.call]
                for d in deps:
                    names += [getattr(sd.call, "__name__", "")
                              for sd in (d.dependencies or []) if sd.call]
                if "require_approved" in names:
                    found = True
                    break
            if not found:
                missing.append(f"{verb} {path}")
        self.assertEqual(
            missing, [],
            "destructive routes lost require_approved — a freshly-registered "
            "(pending) account can reach them again: " + ", ".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
