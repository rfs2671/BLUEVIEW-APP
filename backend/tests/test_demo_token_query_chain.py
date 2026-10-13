"""A stranger's signup token reaches no real record, by header OR by ?token=.

WHAT WAS OPEN (security audit, finding 1, 2026-10-13). Anyone with an email
address could:

  1. POST /api/auth/register   -> a pending `demo` account, no company;
  2. POST /api/auth/login      -> a real JWT (login never read the status);
  3. send it as `?token=<jwt>` instead of an Authorization header.

Both demo middlewares (lib/demo_guard.py, lib/demo_provider.py) read the token
off the HEADER ONLY, saw "no token", and passed the request through.
get_current_user reads `?token=` too, authenticated the demo, and every route
without its own tenant check answered with real data -- or, for
POST /checkins/{id}/checkout, wrote.

THESE ARE REQUESTS, NOT UNIT CALLS. Every one goes through server.app over
ASGI: the real middleware stack, the real dependencies, the real JWT. Only the
database is replaced (tests/async_fake_mongo.py), seeded with one company that
is not the stranger's.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import httpx  # noqa: E402
from bson import ObjectId  # noqa: E402

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402

# A string that exists ONLY in the seeded company's records. If it appears in
# a response to the stranger, a real record was served.
SECRET = "COMPANY-A-PRIVATE-7f3e"

CO_A = ObjectId()
PROJ_A = ObjectId()
EVT = ObjectId()
DLOG = ObjectId()
CHECKIN = ObjectId()


def _seed():
    db = AsyncFakeDB()
    now = datetime.now(timezone.utc)
    db.companies.docs.append({"_id": CO_A, "name": "Acme GC", "is_deleted": False})
    db.projects.docs.append({"_id": PROJ_A, "company_id": str(CO_A),
                             "name": "Tower", "status": "active", "is_deleted": False})
    db.signature_events.docs.append({
        "_id": EVT, "document_type": "logbook", "document_id": "x",
        "content_snapshot": {"note": SECRET}, "signer": {"name": SECRET},
        "is_deleted": False})
    db.daily_logs.docs.append({"_id": DLOG, "project_id": str(PROJ_A),
                               "date": "2026-10-13", "notes": SECRET,
                               "is_deleted": False})
    db.checkins.docs.append({"_id": CHECKIN, "project_id": str(PROJ_A),
                             "status": "checked_in", "check_in_time": now,
                             "is_deleted": False})
    db.users.docs.append({
        "_id": ObjectId(), "email": "admin@acme.test", "name": "A Admin",
        "password": server.hash_password("pw-admin-1"), "role": "admin",
        "company_id": str(CO_A), "account_status": "approved",
        "is_deleted": False})
    db.users.docs.append({
        "_id": ObjectId(), "email": "pending@acme.test", "name": "P Cp",
        "password": server.hash_password("pw-pend-1"), "role": "cp",
        "company_id": None, "account_status": "pending", "is_deleted": False})
    return db


async def _scenario():
    """Returns {label: (status, body_text)} plus the check-in after."""
    db = _seed()
    out = {}
    with patch.object(server, "db", db):
        server.auth_rate_limiter.requests.clear() if hasattr(
            server.auth_rate_limiter, "requests") else None
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://t") as c:
            r = await c.post("/api/auth/register", json={
                "email": "stranger@example.com", "password": "pw-strange-1",
                "name": "Stranger"})
            out["register"] = (r.status_code, r.text)
            r = await c.post("/api/auth/login", json={
                "email": "stranger@example.com", "password": "pw-strange-1"})
            out["login"] = (r.status_code, r.text)
            tok = r.json().get("token") if r.status_code == 200 else ""

            async def both(label, method, path):
                r = await c.request(method, f"{path}?token={tok}")
                out[f"{label} ?token="] = (r.status_code, r.text)
                r = await c.request(method, path,
                                    headers={"Authorization": f"Bearer {tok}"})
                out[f"{label} header"] = (r.status_code, r.text)

            await both("sig-event", "GET", f"/api/signature-events/{EVT}")
            await both("daily-log", "GET", f"/api/daily-logs/{DLOG}")
            await both("checkout", "POST", f"/api/checkins/{CHECKIN}/checkout")

            # A pending account that is NOT a demo (the same refusal must hold)
            r = await c.post("/api/auth/login", json={
                "email": "pending@acme.test", "password": "pw-pend-1"})
            ptok = r.json().get("token")
            r = await c.get(f"/api/signature-events/{EVT}?token={ptok}")
            out["pending sig-event ?token="] = (r.status_code, r.text)
            r = await c.get("/api/auth/me",
                            headers={"Authorization": f"Bearer {ptok}"})
            out["pending /auth/me"] = (r.status_code, r.text)

            # CONTROL: an approved admin of the owning company still reads it.
            r = await c.post("/api/auth/login", json={
                "email": "admin@acme.test", "password": "pw-admin-1"})
            atok = r.json().get("token")
            r = await c.get(f"/api/signature-events/{EVT}",
                            headers={"Authorization": f"Bearer {atok}"})
            out["owner admin sig-event"] = (r.status_code, r.text)
    checkin_after = db.checkins.docs[0]
    return out, checkin_after


class AStrangersSignupReachesNoRealRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, cls.checkin = asyncio.run(_scenario())

    def test_the_signup_and_login_themselves_work(self):
        """Not a refusal of signup: the demo is a product feature."""
        self.assertEqual(self.out["register"][0], 200, self.out["register"])
        self.assertEqual(self.out["login"][0], 200, self.out["login"])

    def test_no_response_to_the_stranger_carries_a_real_record(self):
        for label, (status, body) in self.out.items():
            if label.startswith(("sig-event", "daily-log", "checkout")):
                self.assertNotIn(SECRET, body, f"{label} -> {status}")

    def test_the_query_token_is_answered_as_a_demo_like_the_header(self):
        """The demo layer now SEES a `?token=` demo, so the read gets what the
        header gets: the provider's fiction (or a refusal) -- never the
        handler. Identical answers by either route is the invariant."""
        for what in ("sig-event", "daily-log"):
            q, h = self.out[f"{what} ?token="], self.out[f"{what} header"]
            self.assertEqual(q, h, what)
            self.assertNotIn(SECRET, q[1])

    def test_the_checkout_write_is_refused_by_either_route(self):
        for label in ("checkout ?token=", "checkout header"):
            self.assertNotEqual(self.out[label][0], 200,
                                f"{label} -> {self.out[label]}")
        self.assertEqual(self.checkin.get("status"), "checked_in")
        self.assertNotIn("check_out_time", self.checkin)

    def test_a_pending_non_demo_account_is_refused_too(self):
        st, body = self.out["pending sig-event ?token="]
        self.assertNotEqual(st, 200, body)
        self.assertNotIn(SECRET, body)

    def test_a_pending_account_can_still_learn_it_is_pending(self):
        """/auth/me is on the allow-list: the app reads account_status there
        to route a pending user to the waiting screen."""
        st, body = self.out["pending /auth/me"]
        self.assertEqual(st, 200, body)
        self.assertIn("pending", body)

    def test_CONTROL_the_owning_companys_admin_still_reads_it(self):
        st, body = self.out["owner admin sig-event"]
        self.assertEqual(st, 200, body)
        self.assertIn(SECRET, body)


class TheSecondLayerRefusesWithoutTheMiddlewares(unittest.TestCase):
    """get_current_user itself refuses a demo, so a fourth way to carry a
    token -- or a middleware that failed to install -- is not a hole."""

    def _call(self, user, path):
        db = AsyncFakeDB()
        uid = ObjectId()
        db.users.docs.append(dict(user, _id=uid, is_deleted=False))
        tok = server.create_token(str(uid), user["email"], user["role"])

        class _Url:
            pass

        class _Req:
            url = _Url()
            method = "GET"
            headers = {}
        _Req.url.path = path
        with patch.object(server, "db", db):
            return asyncio.run(server.get_current_user(
                request=_Req(), credentials=None, token=tok))

    DEMO = {"email": "d@x.test", "role": "demo", "account_status": "approved",
            "company_id": None}
    PENDING = {"email": "p@x.test", "role": "cp", "account_status": "pending",
               "company_id": None}
    APPROVED = {"email": "a@x.test", "role": "cp", "account_status": "approved",
                "company_id": "c1"}
    LEGACY = {"email": "l@x.test", "role": "cp", "company_id": "c1"}

    def test_a_demo_is_refused_on_a_real_route_even_when_approved(self):
        with self.assertRaises(server.HTTPException) as cm:
            self._call(self.DEMO, "/api/signature-events/x")
        self.assertEqual(cm.exception.status_code, 403)

    def test_a_pending_account_is_refused(self):
        with self.assertRaises(server.HTTPException) as cm:
            self._call(self.PENDING, "/api/daily-logs/x")
        self.assertEqual(cm.exception.detail, {"error": "account_pending"})

    def test_both_reach_their_own_auth_me(self):
        for u in (self.DEMO, self.PENDING):
            self.assertEqual(self._call(u, "/api/auth/me")["email"], u["email"])

    def test_approved_and_legacy_null_status_are_untouched(self):
        for u in (self.APPROVED, self.LEGACY):
            self.assertEqual(self._call(u, "/api/daily-logs/x")["email"],
                             u["email"])

    def test_the_middleware_reads_the_query_token_too(self):
        from lib import demo_guard

        class _Req:
            headers = {}
            query_params = {"token": "abc"}
        self.assertEqual(demo_guard.bearer_token(_Req()), "abc")

        class _Both:
            headers = {"authorization": "Bearer hdr"}
            query_params = {"token": "abc"}
        self.assertEqual(demo_guard.bearer_token(_Both()), "hdr")


if __name__ == "__main__":
    unittest.main()
