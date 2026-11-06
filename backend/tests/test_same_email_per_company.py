"""One email, one account PER COMPANY (Roy, 2026-11-06).

THE RULING. "Same email allowed across companies (one per company). Login with
an email that has several accounts shows a company picker. Email stays unique
within one company." Accounts are company-owned; each company's admin creates
its own.

WHAT WAS THERE. `users.email_1` was a GLOBAL unique index, so bob@x.com could
exist in one company only. Admin "Add user" answered 400 "Email already
registered" for an account in ANY company, and two edit paths had no pre-check
at all, so a duplicate reached the index and came back as a 500.

THESE ARE REQUESTS, NOT UNIT CALLS, wherever a route is involved: server.app
over ASGI, the real middleware and the real JWT, with only the database
replaced. The fake below is tests/async_fake_mongo.py SUBCLASSED to declare
unique indexes and refuse a duplicate the way Mongo does (E11000), so a write
that skips its pre-check produces the 500 it produces in production instead of
quietly succeeding in memory.
"""

import asyncio
import copy
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import httpx  # noqa: E402
import jwt  # noqa: E402
from bson import ObjectId  # noqa: E402
from pymongo.errors import DuplicateKeyError, OperationFailure  # noqa: E402

import server  # noqa: E402
from async_fake_mongo import AsyncFakeCollection, AsyncFakeDB  # noqa: E402
from lib import notifications as N  # noqa: E402


# ── The fake: async_fake_mongo plus unique indexes ─────────────────────────

class _Indexed(AsyncFakeCollection):
    """An AsyncFakeCollection that holds index specs and enforces the unique
    ones on insert and update, as Mongo does. No upsert (the base has none
    either), and nothing else added."""

    def __init__(self, name):
        super().__init__(name)
        self.indexes = {"_id_": {"key": [("_id", 1)], "unique": True}}

    # -- enforcement ---------------------------------------------------------
    @staticmethod
    def _key(doc, keys):
        return tuple(doc.get(k) for k, _ in keys)

    def _check(self, doc, skip_id=None):
        for name, spec in self.indexes.items():
            if name == "_id_" or not spec.get("unique"):
                continue
            mine = self._key(doc, spec["key"])
            for other in self.docs:
                if skip_id is not None and other.get("_id") == skip_id:
                    continue
                if self._key(other, spec["key"]) == mine:
                    raise DuplicateKeyError(
                        f"E11000 duplicate key error index: {name} dup key: {mine}")

    async def insert_one(self, doc, **kw):
        doc.setdefault("_id", ObjectId())
        self._check(doc)
        return await super().insert_one(doc, **kw)

    async def update_one(self, flt, update, upsert=False, **kw):
        assert not upsert, "this fake has no upsert"
        from async_fake_mongo import matches
        for d in self.docs:
            if matches(d, flt):
                after = copy.deepcopy(d)
                for k, v in (update.get("$set") or {}).items():
                    after[k] = v
                for k in (update.get("$unset") or {}):
                    after.pop(k, None)
                self._check(after, skip_id=d.get("_id"))
                break
        return await super().update_one(flt, update, upsert=upsert, **kw)

    # -- index management ----------------------------------------------------
    async def create_index(self, keys, name=None, unique=False, **kw):
        keys = list(keys)
        have = self.indexes.get(name)
        if have is not None:
            if have["key"] == keys and bool(have.get("unique")) == bool(unique):
                return name
            raise OperationFailure("IndexOptionsConflict", code=85)
        if unique:
            seen = set()
            for d in self.docs:
                k = self._key(d, keys)
                if k in seen:
                    raise OperationFailure(f"E11000 duplicate key {name}", code=11000)
                seen.add(k)
        self.indexes[name] = {"key": keys, "unique": bool(unique)}
        return name

    async def drop_index(self, name):
        if name not in self.indexes:
            raise OperationFailure(f"index not found with name [{name}]", code=27)
        del self.indexes[name]

    async def index_information(self):
        return copy.deepcopy(self.indexes)

    def list_indexes(self):
        items = [{"name": n, "key": dict(s["key"]), "unique": s.get("unique")}
                 for n, s in self.indexes.items()]

        class _It:
            def __aiter__(self_inner):
                self_inner._i = iter(items)
                return self_inner

            async def __anext__(self_inner):
                try:
                    return next(self_inner._i)
                except StopIteration:
                    raise StopAsyncIteration
        return _It()


class IndexedFakeDB(AsyncFakeDB):
    def __getitem__(self, name):
        if name not in self._c:
            self._c[name] = _Indexed(name)
        return self._c[name]


# ── The world ──────────────────────────────────────────────────────────────

CO_A, CO_B, CO_C = ObjectId(), ObjectId(), ObjectId()
A, B, C = str(CO_A), str(CO_B), str(CO_C)
PW = "Same-Pass-2026!"
PW_C = "Other-Pass-2026!"
STRONG = "Str0ng!Passw0rd#2026"
STRANGER = "Str4nger!Passw0rd#2026"  # not the operator's
BOB_A, BOB_B, BOB_C = ObjectId(), ObjectId(), ObjectId()
ADMIN_A, ADMIN_B, OPS = ObjectId(), ObjectId(), ObjectId()
AMY_A, GONE_A, PEND = ObjectId(), ObjectId(), ObjectId()
OPS_EMAIL = "ops@levelog.example"

# THE INDEX THE MIGRATION LEAVES IN PRODUCTION: unique per (company, email).
PER_COMPANY = {"key": [("company_id", 1), ("email", 1)], "unique": True}


def _user(_id, email, company, role="cp", password=PW, **extra):
    row = {"_id": _id, "email": email, "name": email.split("@")[0],
           "password": server.hash_password(password), "role": role,
           "company_id": company, "account_status": "approved",
           "is_deleted": False}
    row.update(extra)
    return row


def _seed(indexes=None):
    db = IndexedFakeDB()
    db.users.indexes.update(copy.deepcopy(
        indexes if indexes is not None else {"users_company_email_unique": PER_COMPANY}))
    for _id, name in ((CO_A, "Acme GC"), (CO_B, "Bravo Plumbing"), (CO_C, "Charlie Steel")):
        db.companies.docs.append({"_id": _id, "name": name, "is_deleted": False})
    db.users.docs += [
        # The same person, the same email, in two companies, one password.
        _user(BOB_A, "bob@x.example", A),
        _user(BOB_B, "Bob@X.example", B, role="pm"),
        # ...and in a third company with a DIFFERENT password.
        _user(BOB_C, "bob@x.example", C, password=PW_C),
        _user(ADMIN_A, "admin@acme.example", A, role="admin", password=STRONG),
        _user(ADMIN_B, "admin@bravo.example", B, role="admin", password=STRONG),
        _user(AMY_A, "amy@acme.example", A),
        _user(GONE_A, "gone@acme.example", A, is_deleted=True),
        _user(OPS, OPS_EMAIL, None, role="admin", password=STRONG,
              is_platform_operator=True),
    ]
    return db


def _bearer(uid, email, role, company):
    return {"Authorization":
            f"Bearer {server.create_token(str(uid), email, role, company_id=company)}"}


def _run(scenario, db=None):
    """Run `scenario(client, db)` against server.app with `db` patched in."""
    db = db or _seed()

    async def go():
        with patch.object(server, "db", db), \
                patch.object(server, "PLATFORM_OPERATOR_EMAILS", frozenset({OPS_EMAIL})), \
                patch.dict(os.environ, {"RATE_LIMITS_DISABLED": "1"}):
            server.auth_rate_limiter.reset()
            transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                return await scenario(c, db)
    return asyncio.run(go()), db


def _sub(token):
    return jwt.decode(token, server.JWT_SECRET, algorithms=[server.JWT_ALGORITHM])["sub"]


# ══════════════════════════════════════════════════════════════════════════
# 3. LOGIN
# ══════════════════════════════════════════════════════════════════════════

class LoginWithAnEmailInSeveralCompanies(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        async def s(c, db):
            out = {}
            r = await c.post("/api/auth/login", json={
                "email": "bob@x.example", "password": PW, "company_picker": True})
            out["picker"] = (r.status_code, r.json())
            choices = r.json().get("accounts") or []
            bravo = next((a for a in choices if a.get("company_name") == "Bravo Plumbing"), {})
            r = await c.post("/api/auth/login/choose",
                             json={"choice_token": bravo.get("choice_token", "")})
            out["choose"] = (r.status_code, r.json())
            tok = r.json().get("token", "")
            r = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
            out["me"] = (r.status_code, r.json())
            # The choice token is not a session.
            r = await c.get("/api/auth/me", headers={
                "Authorization": f"Bearer {bravo.get('choice_token', '')}"})
            out["choice_as_session"] = r.status_code
            # A client that cannot show a picker.
            r = await c.post("/api/auth/login", json={"email": "bob@x.example", "password": PW})
            out["old_client"] = (r.status_code, r.text)
            # The third company has a different password: only it matches.
            r = await c.post("/api/auth/login", json={
                "email": "BOB@x.example ", "password": PW_C, "company_picker": True})
            out["third"] = (r.status_code, r.json())
            # Wrong password, and an email nobody has: the same answer.
            r = await c.post("/api/auth/login", json={
                "email": "bob@x.example", "password": "nope-nope", "company_picker": True})
            out["wrong"] = (r.status_code, r.json())
            r = await c.post("/api/auth/login", json={
                "email": "nobody@x.example", "password": "nope-nope", "company_picker": True})
            out["nobody"] = (r.status_code, r.json())
            return out
        cls.out, _ = _run(s)

    def test_two_password_matches_return_a_picker_and_no_session(self):
        status, body = self.out["picker"]
        self.assertEqual(status, 200, body)
        self.assertTrue(body.get("choose_company"))
        self.assertNotIn("token", body)
        names = sorted(a["company_name"] for a in body["accounts"])
        # Charlie Steel has a different password: it is NOT listed.
        self.assertEqual(names, ["Acme GC", "Bravo Plumbing"])
        for a in body["accounts"]:
            self.assertTrue(a["choice_token"])
            self.assertNotIn("token", a)

    def test_the_choice_is_exchanged_for_that_accounts_session(self):
        status, body = self.out["choose"]
        self.assertEqual(status, 200, body)
        self.assertEqual(_sub(body["token"]), str(BOB_B))
        status, me = self.out["me"]
        self.assertEqual((status, me.get("company_id")), (200, B))

    def test_a_choice_token_is_not_a_session_token(self):
        self.assertEqual(self.out["choice_as_session"], 401)

    def test_a_client_without_the_picker_is_told_to_update_not_given_a_token(self):
        status, text = self.out["old_client"]
        self.assertEqual(status, 409, text)
        self.assertNotIn('"token"', text)
        self.assertIn("Update", text)
        self.assertIn("Actualice", text)

    def test_one_password_match_logs_in_as_today_case_insensitively(self):
        status, body = self.out["third"]
        self.assertEqual(status, 200, body)
        self.assertNotIn("choose_company", body)
        self.assertEqual(_sub(body["token"]), str(BOB_C))

    def test_no_enumeration_wrong_password_reads_like_an_unknown_email(self):
        self.assertEqual(self.out["wrong"], self.out["nobody"])
        self.assertEqual(self.out["wrong"][0], 401)


class TheChoiceIsShortLivedAndBound(unittest.TestCase):

    def _choice(self, c, db):
        async def go():
            r = await c.post("/api/auth/login", json={
                "email": "bob@x.example", "password": PW, "company_picker": True})
            return {a["company_name"]: a["choice_token"] for a in r.json()["accounts"]}
        return go()

    def test_an_expired_choice_is_refused(self):
        async def s(c, db):
            now = datetime.now(timezone.utc)
            stale = jwt.encode({"typ": "login_choice", "sub": str(BOB_A), "em": "bob@x.example",
                                "iat": now - timedelta(minutes=20),
                                "exp": now - timedelta(minutes=10)},
                               server._login_choice_key(), algorithm=server.JWT_ALGORITHM)
            r = await c.post("/api/auth/login/choose", json={"choice_token": stale})
            return r.status_code
        status, _ = _run(s)
        self.assertEqual(status, 401)

    def test_a_choice_signed_with_the_session_key_is_refused(self):
        """A session JWT (or anything signed with JWT_SECRET) is not a choice."""
        async def s(c, db):
            forged = server.create_token(str(BOB_A), "bob@x.example", "cp", company_id=A)
            r = await c.post("/api/auth/login/choose", json={"choice_token": forged})
            return r.status_code
        status, _ = _run(s)
        self.assertEqual(status, 401)

    def test_a_choice_dies_when_the_accounts_email_or_password_changes(self):
        async def s(c, db):
            toks = await self._choice(c, db)
            row = next(u for u in db.users.docs if u["_id"] == BOB_A)
            row["email"] = "robert@x.example"
            r1 = await c.post("/api/auth/login/choose", json={"choice_token": toks["Acme GC"]})
            row2 = next(u for u in db.users.docs if u["_id"] == BOB_B)
            row2["password"] = server.hash_password("Changed-Pass-2026!")
            r2 = await c.post("/api/auth/login/choose", json={"choice_token": toks["Bravo Plumbing"]})
            return r1.status_code, r2.status_code
        (s1, s2), _ = _run(s)
        self.assertEqual((s1, s2), (401, 401))

    def test_a_deleted_account_is_neither_listed_nor_chosen(self):
        async def s(c, db):
            toks = await self._choice(c, db)
            next(u for u in db.users.docs if u["_id"] == BOB_B)["is_deleted"] = True
            r1 = await c.post("/api/auth/login/choose", json={"choice_token": toks["Bravo Plumbing"]})
            r2 = await c.post("/api/auth/login", json={
                "email": "bob@x.example", "password": PW, "company_picker": True})
            return r1.status_code, r2.status_code, r2.json()
        (s1, s2, body), _ = _run(s)
        self.assertEqual(s1, 401)
        # One live match left: a plain login, as today.
        self.assertEqual(s2, 200)
        self.assertEqual(_sub(body["token"]), str(BOB_A))

    def test_a_pending_account_still_logs_in_exactly_as_today(self):
        """Login never read account_status; the gate is require_approved on
        cost-bearing routes. The picker must not add or remove a gate."""
        async def s(c, db):
            next(u for u in db.users.docs if u["_id"] == BOB_B)["account_status"] = "pending"
            toks = await self._choice(c, db)
            r = await c.post("/api/auth/login/choose", json={"choice_token": toks["Bravo Plumbing"]})
            me = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"})
            return r.status_code, me.json().get("account_status")
        (status, acct), _ = _run(s)
        self.assertEqual((status, acct), (200, "pending"))


# ══════════════════════════════════════════════════════════════════════════
# 1 + 2. UNIQUENESS: within one company only, and a clean refusal, never a 500
# ══════════════════════════════════════════════════════════════════════════

class AdminAddUser(unittest.TestCase):

    def _create(self, email, who=(ADMIN_A, "admin@acme.example", A)):
        async def s(c, db):
            uid, em, co = who
            r = await c.post("/api/admin/users", headers=_bearer(uid, em, "admin", co), json={
                "email": email, "password": STRONG, "name": "New Person", "role": "cp"})
            return r.status_code, r.text
        return _run(s)

    def test_an_email_used_in_another_company_is_allowed_here(self):
        (status, text), db = self._create("admin@bravo.example")
        self.assertEqual(status, 200, text)
        rows = [u for u in db.users.docs if u["email"].lower() == "admin@bravo.example"]
        self.assertEqual(sorted(str(u["company_id"]) for u in rows), sorted([A, B]))

    def test_an_email_used_in_this_company_is_a_409_in_any_case(self):
        (status, text), db = self._create("  AMY@Acme.EXAMPLE ")
        self.assertEqual(status, 409, text)
        self.assertIn("this company", text)
        self.assertIn("esta empresa", text)

    def test_a_deleted_accounts_email_in_this_company_is_refused(self):
        """DELETED ROWS COUNT within their company, so a restore can never
        produce two accounts with one email in one company."""
        (status, text), _ = self._create("gone@acme.example")
        self.assertEqual(status, 409, text)
        self.assertIn("restore", text.lower())

    def test_the_operators_email_is_not_available_to_a_company_admin(self):
        """is_platform_operator() admits by email (PLATFORM_OPERATOR_EMAILS).
        With email no longer globally unique, an admin who could create that
        address in his own company would mint an operator account."""
        (status, text), db = self._create("OPS@levelog.example")
        self.assertEqual(status, 409, text)
        self.assertEqual(sum(1 for u in db.users.docs
                             if u["email"].lower() == OPS_EMAIL), 1)


class AdminEditUser(unittest.TestCase):

    def _edit(self, target, email):
        async def s(c, db):
            r = await c.put(f"/api/admin/users/{target}",
                            headers=_bearer(ADMIN_A, "admin@acme.example", "admin", A),
                            json={"email": email})
            return r.status_code, r.text
        return _run(s)

    def test_editing_to_an_email_in_this_company_is_a_409_not_a_500(self):
        (status, text), _ = self._edit(AMY_A, "bob@x.example")
        self.assertEqual(status, 409, text)

    def test_editing_to_an_email_used_only_in_another_company_is_allowed(self):
        (status, text), db = self._edit(AMY_A, "admin@bravo.example")
        self.assertEqual(status, 200, text)
        amy = next(u for u in db.users.docs if u["_id"] == AMY_A)
        self.assertEqual(amy["email"], "admin@bravo.example")


class SelfSignup(unittest.TestCase):

    def test_signup_with_an_email_in_a_company_creates_a_no_company_account(self):
        async def s(c, db):
            r1 = await c.post("/api/auth/register", json={
                "email": "bob@x.example", "password": STRONG, "name": "Bob"})
            r2 = await c.post("/api/auth/register", json={
                "email": "BOB@x.example", "password": STRONG, "name": "Bob again"})
            return r1.status_code, r2.status_code, r2.text
        (s1, s2, text2), db = _run(s)
        self.assertEqual(s1, 200)
        # A second company-less account with the same email is the duplicate.
        self.assertEqual(s2, 409, text2)
        self.assertIn("Ya existe", text2)

    def test_a_case_variant_of_the_operators_email_cannot_sign_up(self):
        """ON MAIN THIS SUCCEEDED, AND THE STRANGER REACHED AN OPERATOR ROUTE.
        The index matched exactly, the signup check matched exactly, and
        is_platform_operator() lowercases: a self-serve signup as
        OPS@levelog.example got 200 from GET /api/owner/admins (control run,
        2026-11-06). Only live if PLATFORM_OPERATOR_EMAILS is set."""
        async def s(c, db):
            r = await c.post("/api/auth/register", json={
                "email": "OPS@levelog.example", "password": STRANGER, "name": "Not Roy"})
            out = {"register": r.status_code}
            r = await c.post("/api/auth/login", json={
                "email": "OPS@levelog.example", "password": STRANGER, "company_picker": True})
            out["login"] = r.status_code
            tok = r.json().get("token") or ""
            r = await c.get("/api/owner/admins", headers={"Authorization": f"Bearer {tok}"})
            out["owner_route"] = r.status_code
            return out
        out, db = _run(s)
        self.assertEqual(out["register"], 409)
        self.assertEqual(sum(1 for u in db.users.docs
                             if u["email"].lower() == OPS_EMAIL), 1)
        self.assertEqual(out["owner_route"], 404)


class OwnerPortalPaths(unittest.TestCase):

    def _ops(self):
        return _bearer(OPS, OPS_EMAIL, "admin", None)

    def test_owner_edit_admin_email_to_one_in_its_company_is_a_409_not_a_500(self):
        async def s(c, db):
            r = await c.put(f"/api/owner/admins/{ADMIN_A}", headers=self._ops(),
                            json={"email": "amy@acme.example"})
            return r.status_code, r.text
        (status, text), _ = _run(s)
        self.assertEqual(status, 409, text)

    def test_owner_moving_an_admin_into_a_company_that_has_the_email_is_a_409(self):
        async def s(c, db):
            db.users.docs.append(_user(ObjectId(), "admin@acme.example", B, role="pm"))
            r = await c.put(f"/api/owner/admins/{ADMIN_A}", headers=self._ops(),
                            json={"company_id": B})
            return r.status_code, r.text
        (status, text), _ = _run(s)
        self.assertEqual(status, 409, text)

    def test_owner_create_admin_reusing_a_deleted_email_in_that_company_is_409_not_500(self):
        async def s(c, db):
            r = await c.post("/api/owner/admins", headers=self._ops(), json={
                "name": "G", "email": "gone@acme.example", "password": STRONG,
                "company_name": "Acme GC"})
            return r.status_code, r.text
        (status, text), _ = _run(s)
        self.assertEqual(status, 409, text)

    def test_owner_create_admin_with_an_email_from_another_company_is_allowed(self):
        async def s(c, db):
            r = await c.post("/api/owner/admins", headers=self._ops(), json={
                "name": "Bo", "email": "admin@bravo.example", "password": STRONG,
                "company_name": "Acme GC"})
            return r.status_code, r.text
        (status, text), _ = _run(s)
        self.assertEqual(status, 200, text)

    def test_owner_add_company_admin_creates_here_when_the_email_is_elsewhere(self):
        async def s(c, db):
            r = await c.post(f"/api/owner/companies/{A}/admins", headers=self._ops(), json={
                "email": "Admin@Bravo.example", "name": "Bea", "password": STRONG})
            return r.status_code, r.json()
        (status, body), db = _run(s)
        self.assertEqual(status, 200, body)
        self.assertTrue(body["created"])
        self.assertEqual(sorted(str(u["company_id"]) for u in db.users.docs
                                if u["email"].lower() == "admin@bravo.example"), sorted([A, B]))

    def test_restore_is_refused_only_by_a_live_account_in_the_same_company(self):
        async def s(c, db):
            # A live account elsewhere does not block the restore...
            db.users.docs.append(_user(ObjectId(), "gone@acme.example", B))
            r1 = await c.post(f"/api/owner/deleted/user/{GONE_A}/restore", headers=self._ops())
            return r1.status_code, r1.text
        (status, text), db = _run(s)
        self.assertEqual(status, 200, text)
        self.assertFalse(next(u for u in db.users.docs if u["_id"] == GONE_A)["is_deleted"])

    def test_restore_is_refused_by_a_live_case_variant_in_the_same_company(self):
        async def s(c, db):
            db.users.docs.append(_user(ObjectId(), "GONE@acme.example", A))
            r = await c.post(f"/api/owner/deleted/user/{GONE_A}/restore", headers=self._ops())
            return r.status_code, r.json()
        (status, body), _ = _run(s)
        self.assertEqual((status, body["detail"]["code"]), (409, "EMAIL_IN_USE"))


class OnboardingJoinsAnExistingCompany(unittest.TestCase):

    def test_joining_a_company_that_already_has_this_email_is_a_409(self):
        async def s(c, db):
            uid = ObjectId()
            db.users.docs.append(_user(uid, "amy@acme.example", None, role="admin",
                                       onboarding_step="1"))
            r = await c.post("/api/onboarding/company",
                             headers=_bearer(uid, "amy@acme.example", "admin", None),
                             json={"name": "Acme GC"})
            return r.status_code, r.text, uid
        (status, text, uid), db = _run(s)
        self.assertEqual(status, 409, text)
        self.assertIsNone(next(u for u in db.users.docs if u["_id"] == uid)["company_id"])


# ══════════════════════════════════════════════════════════════════════════
# 1. THE INDEX MIGRATION
# ══════════════════════════════════════════════════════════════════════════

class TheIndexMigration(unittest.TestCase):

    def _migrate(self, extra_rows=()):
        db = IndexedFakeDB()
        db.users.indexes["email_1"] = {"key": [("email", 1)], "unique": True}
        db.users.docs += [
            {"_id": ObjectId(), "email": "a@x.example", "company_id": A},
            {"_id": ObjectId(), "email": "b@x.example", "company_id": B},
            *extra_rows,
        ]

        async def go():
            with patch.object(server, "db", db):
                server.FAILED_UNIQUE_INDEX_BUILDS.pop(server.USERS_COMPANY_EMAIL_INDEX, None)
                return await server.run_user_email_index_migration()
        return asyncio.run(go()), db

    def test_builds_per_company_then_relaxes_the_global_index(self):
        result, db = self._migrate()
        self.assertEqual(result, "per_company")
        idx = db.users.indexes
        self.assertEqual(idx[server.USERS_COMPANY_EMAIL_INDEX], PER_COMPANY)
        self.assertEqual(idx["email_1"], {"key": [("email", 1)], "unique": False})

    def test_is_idempotent(self):
        result, db = self._migrate()

        async def again():
            with patch.object(server, "db", db):
                return await server.run_user_email_index_migration()
        self.assertEqual(asyncio.run(again()), "per_company")
        self.assertFalse(db.users.indexes["email_1"]["unique"])

    def test_a_per_company_build_that_meets_duplicates_keeps_the_global_index(self):
        """Only reachable if email_1 was not actually enforcing (it cannot
        coexist with same-company duplicates). The global index is NOT dropped:
        no window with no email uniqueness at all."""
        dup = [{"_id": ObjectId(), "email": "a@x.example", "company_id": A}]
        # The fake refuses to build per-company over the duplicate; email_1
        # claims unique but these rows predate it (an unenforced index).
        result, db = self._migrate(dup)
        self.assertEqual(result, "kept_global")
        self.assertTrue(db.users.indexes["email_1"]["unique"])
        self.assertNotIn(server.USERS_COMPANY_EMAIL_INDEX, db.users.indexes)
        self.assertIn(server.USERS_COMPANY_EMAIL_INDEX, server.FAILED_UNIQUE_INDEX_BUILDS)
        alerts = [a for a in db.compliance_alerts.docs
                  if a.get("alert_type") == "unique_index_not_enforced"]
        self.assertEqual(len(alerts), 1)


# ══════════════════════════════════════════════════════════════════════════
# 4. EMAIL LOOKUPS THAT ASSUMED ONE ACCOUNT
# ══════════════════════════════════════════════════════════════════════════

class AFieldRoleExclusionIsPerPersonNotPerRow(unittest.TestCase):
    """CP in one company, admin in another, one address. The admin's permit
    reminders must still be sent; find_one picked whichever row came first."""

    def _db(self, rows):
        db = IndexedFakeDB()
        db.users.docs += rows
        return db

    def test_a_cp_here_and_an_admin_there_is_emailed(self):
        db = self._db([
            {"_id": ObjectId(), "email": "dual@x.example", "role": "cp", "company_id": A},
            {"_id": ObjectId(), "email": "dual@x.example", "role": "admin", "company_id": B},
        ])
        self.assertIsNone(asyncio.run(N.recipient_is_field_role(db, "dual@x.example")))

    def test_a_cp_only_is_still_excluded(self):
        db = self._db([
            {"_id": ObjectId(), "email": "cp@x.example", "role": "cp", "company_id": A},
            {"_id": ObjectId(), "email": "cp@x.example", "role": "cp", "company_id": B},
        ])
        self.assertEqual(asyncio.run(N.recipient_is_field_role(db, "cp@x.example")), "cp")


if __name__ == "__main__":
    unittest.main()
