"""THE OPERATOR IS THE DB FLAG, AND AN EMAIL IN ANOTHER CASE IS TAKEN.

Operator ruling 2026-11-06. On main before this change:

  * is_platform_operator() answered True for any account whose email,
    lowercased, was in PLATFORM_OPERATOR_EMAILS;
  * /auth/register refused a duplicate only on an EXACT, case-sensitive match.

So a public signup as "OPS@levelog.com" (operator: "ops@levelog.com") made a
second account, and that account passed require_operator_404. Asserted here:

  1. is_platform_operator reads the flag only; the email list grants nothing;
  2. driven over ASGI: the case-variant signup is refused, and even a
     case-variant row that already exists gets 404 on an owner route;
  3. every email uniqueness check (register, admin add, owner add, admin edit,
     owner edit) is case-insensitive and refuses with 400, never a 500;
  4. the one-time startup conversion flags the operator only when exactly one
     live account claims the address, and writes nothing when two do.

CONTROL: against origin/main's server.py, sections 1-4 fail
(is_platform_operator grants by email; email_in_use and
run_operator_flag_startup_migration do not exist; the variant signup is 200).
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

from bson import ObjectId  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402

OPS = "ops@levelog.com"
CO = "c0ffee000000000000000001"


def _run(coro):
    return asyncio.run(coro)


def _db(*users):
    db = AsyncFakeDB()
    for u in users:
        db.users.docs.append(dict(u))
    return db


def _user(email, **kw):
    d = {"_id": ObjectId(), "email": email, "name": "x", "role": "admin",
         "company_id": CO, "is_deleted": False, "account_status": "approved"}
    d.update(kw)
    return d


class _Client:
    """server.app over ASGI with the fake db and, optionally, a signed-in user."""

    def __init__(self, db, user=None):
        self.db, self.user = db, user

    def __enter__(self):
        self._patches = [patch.object(server, "db", self.db),
                         patch.object(server, "PLATFORM_OPERATOR_EMAILS", frozenset({OPS}))]
        if self.user is not None:
            async def _me(*a, **k):
                return dict(self.user, id=str(self.user["_id"]))
            self._patches.append(patch.object(server, "get_current_user", _me))
            server.app.dependency_overrides[server.get_current_user] = lambda: dict(
                self.user, id=str(self.user["_id"]))
        for p in self._patches:
            p.start()
        server.app.dependency_overrides[server.check_auth_rate_limit] = lambda: None
        return TestClient(server.app, raise_server_exceptions=False)

    def __exit__(self, *exc):
        server.app.dependency_overrides.clear()
        for p in reversed(self._patches):
            p.stop()


class TheFlagIsTheOnlyTest(unittest.TestCase):

    def test_an_operator_email_without_the_flag_is_not_the_operator(self):
        with patch.object(server, "PLATFORM_OPERATOR_EMAILS", frozenset({OPS})):
            for email in (OPS, "OPS@levelog.com", " Ops@LeveLog.com "):
                with self.subTest(email=email):
                    self.assertFalse(server.is_platform_operator({"email": email, "role": "admin"}))

    def test_the_flag_grants(self):
        self.assertTrue(server.is_platform_operator({"is_platform_operator": True}))
        self.assertFalse(server.is_platform_operator({"is_platform_operator": "true"}))
        self.assertFalse(server.is_platform_operator({}))
        self.assertFalse(server.is_platform_operator(None))


class TheSignupHoleIsClosed(unittest.TestCase):

    BODY = {"password": "newuser1", "name": "Mallory", "role": "owner"}

    def test_a_case_variant_of_an_existing_email_cannot_sign_up(self):
        db = _db(_user(OPS, is_platform_operator=True))
        with _Client(db) as c:
            for email in ("OPS@levelog.com", "Ops@LeveLog.com"):
                with self.subTest(email=email):
                    r = c.post("/api/auth/register", json=dict(self.BODY, email=email))
                    self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(len(db.users.docs), 1, "no second account was written")

    def test_a_variant_row_that_already_exists_is_not_the_operator(self):
        """An account the old hole may already have created."""
        mallory = _user("OPS@levelog.com", registration_source="self_registered")
        db = _db(_user(OPS, is_platform_operator=True), mallory)
        with _Client(db, user=mallory) as c:
            r = c.get("/api/owner/admins")
        self.assertEqual(r.status_code, 404, r.text)

    def test_the_flagged_operator_still_gets_in(self):
        ops = _user(OPS, is_platform_operator=True)
        with _Client(_db(ops), user=ops) as c:
            r = c.get("/api/owner/admins")
        self.assertNotEqual(r.status_code, 404, r.text)

    def test_a_new_address_still_signs_up(self):
        db = _db(_user(OPS, is_platform_operator=True))
        with _Client(db) as c:
            r = c.post("/api/auth/register", json=dict(self.BODY, email="new@example.com"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("is_platform_operator", db.users.docs[-1])


class EveryUniquenessCheckIgnoresCase(unittest.TestCase):

    def test_email_in_use(self):
        bob = _user("Bob@Example.com")
        gone = _user("gone@example.com", is_deleted=True)
        with patch.object(server, "db", _db(bob, gone)):
            self.assertTrue(_run(server.email_in_use("bob@example.com")))
            self.assertTrue(_run(server.email_in_use("  BOB@EXAMPLE.COM ")))
            self.assertTrue(_run(server.email_in_use("GONE@example.com")), "deleted rows count")
            self.assertFalse(_run(server.email_in_use("bob@example.com", exclude_id=bob["_id"])))
            self.assertFalse(_run(server.email_in_use("bob.x@example.com")))
            self.assertFalse(_run(server.email_in_use("b.b@example.com")), "a regex char is literal")
            self.assertFalse(_run(server.email_in_use("")))

    def test_the_writers_call_it(self):
        src = (_HERE.parent / "server.py").read_text(encoding="utf-8")
        for fn in ("async def register(", "async def create_admin_user(",
                   "async def create_admin_with_company(", "async def update_admin_account(",
                   "async def update_admin_user("):
            with self.subTest(fn=fn):
                body = src[src.index(fn):]
                body = body[:body.index("\n@api_router.", 1)]
                self.assertIn("await email_in_use(", body)
                self.assertNotIn('find_one({"email": user_data.email})', body)

    def test_an_admin_edit_to_a_variant_is_400_not_500(self):
        admin = _user("admin@acme.test", role="admin")
        other = _user("Taken@Acme.test", role="worker")
        target = _user("me@acme.test", role="worker")
        db = _db(admin, other, target)
        with _Client(db, user=admin) as c:
            server.app.dependency_overrides[server.get_user_admin] = lambda: dict(
                admin, id=str(admin["_id"]))
            r = c.put(f"/api/admin/users/{target['_id']}", json={"email": "taken@acme.test"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(db.users.docs[2]["email"], "me@acme.test")


class TheBootstrapIsConvertedOnce(unittest.TestCase):

    def _migrate(self, *users):
        db = _db(*users)
        with patch.object(server, "db", db), \
                patch.object(server, "PLATFORM_OPERATOR_EMAILS", frozenset({OPS})):
            out = _run(server.run_operator_flag_startup_migration())
        return db, out

    def test_exactly_one_account_is_flagged(self):
        db, out = self._migrate(_user("Ops@levelog.com"), _user("someone@else.test"))
        self.assertIs(db.users.docs[0].get("is_platform_operator"), True)
        self.assertNotIn("is_platform_operator", db.users.docs[1])
        self.assertEqual(len(out["flagged"]), 1)

    def test_two_case_variants_write_nothing(self):
        with self.assertLogs(server.logger, level="ERROR"):
            db, out = self._migrate(_user(OPS), _user("OPS@levelog.com"))
        self.assertFalse(any("is_platform_operator" in d for d in db.users.docs))
        self.assertEqual(len(out["ambiguous"][OPS]), 2)

    def test_an_already_flagged_operator_is_left_alone(self):
        db, out = self._migrate(_user(OPS, is_platform_operator=True), _user("OPS@levelog.com"))
        self.assertNotIn("is_platform_operator", db.users.docs[1], "the variant is never flagged")
        self.assertEqual(out["already"], [OPS])

    def test_a_deleted_row_is_not_flagged(self):
        db, _ = self._migrate(_user(OPS, is_deleted=True))
        self.assertNotIn("is_platform_operator", db.users.docs[0])

    def test_it_runs_at_startup(self):
        src = (_HERE.parent / "server.py").read_text(encoding="utf-8")
        body = src[src.index("async def startup_event("):]
        self.assertIn("await run_operator_flag_startup_migration()", body)

    def test_it_never_raises(self):
        class Boom:
            def __getattr__(self, n):
                raise RuntimeError("db down")
        with patch.object(server, "db", Boom()), \
                patch.object(server, "PLATFORM_OPERATOR_EMAILS", frozenset({OPS})), \
                self.assertLogs(server.logger, level="ERROR"):
            _run(server.run_operator_flag_startup_migration())


if __name__ == "__main__":
    unittest.main()
