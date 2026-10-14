"""P1 of the 2026-10-13 security audit: writes that crossed companies.

  DELETE /admin/users/{id}        role check only. Any company's admin could
                                  soft-delete any account on the platform --
                                  another company's admins, or the operator --
                                  and a soft delete revokes the login.
  POST /checkins/{id}/checkout    any principal, any check-in.
  POST /admin/card-flags/{id}/action, GET /admin/projects/{id}/card-queue
                                  by id, no company scope. DEAD: no caller in
                                  the app, zero rows in all four card-audit
                                  collections in production. Removed.
  GET /a/{annotation_id}          reflected XSS: the path segment went
                                  unescaped into a <script> string and an href
                                  on api.levelog.com (confirmed against
                                  production with a GET, 2026-10-13).
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

CO_A, CO_B = "co-a", "co-b"
PROJ_A = ObjectId()
VICTIM = ObjectId()
CHECKIN = ObjectId()

ADMIN_A = {"id": "adm-a", "role": "admin", "company_id": CO_A,
           "account_status": "approved"}
ADMIN_B = {"id": "adm-b", "role": "admin", "company_id": CO_B,
           "account_status": "approved"}
CP_B = {"id": "cp-b", "role": "cp", "company_id": CO_B,
        "account_status": "approved"}
CP_A = {"id": "cp-a", "role": "cp", "company_id": CO_A,
        "account_status": "approved"}
OPERATOR = {"id": "op", "role": "owner", "company_id": None,
            "is_platform_operator": True, "account_status": "approved"}
DEVICE_A = {"id": "dev-a", "role": "site_device", "site_mode": True,
            "project_id": str(PROJ_A), "company_id": CO_A}
DEVICE_ELSEWHERE = {"id": "dev-x", "role": "site_device", "site_mode": True,
                    "project_id": str(ObjectId()), "company_id": CO_A}


def _db():
    db = AsyncFakeDB()
    db.users.docs.append({"_id": VICTIM, "email": "v@a.test", "role": "admin",
                          "company_id": CO_A, "is_deleted": False})
    db.projects.docs.append({"_id": PROJ_A, "company_id": CO_A,
                             "status": "active", "is_deleted": False})
    db.checkins.docs.append({"_id": CHECKIN, "project_id": str(PROJ_A),
                             "status": "checked_in", "is_deleted": False,
                             "check_in_time": datetime.now(timezone.utc)})
    return db


def _run(coro_fn, db):
    with patch.object(server, "db", db):
        try:
            asyncio.run(coro_fn())
            return 200
        except server.HTTPException as e:
            return e.status_code


class DeleteUserIsHeldToTheCallersCompany(unittest.TestCase):
    def _delete(self, actor):
        db = _db()
        st = _run(lambda: server.delete_admin_user(str(VICTIM), actor), db)
        return st, db.users.docs[0].get("is_deleted")

    def test_another_companys_admin_is_refused_and_nothing_changes(self):
        st, deleted = self._delete(ADMIN_B)
        self.assertEqual(st, 403)
        self.assertFalse(deleted)

    def test_the_users_own_company_admin_still_deletes(self):
        self.assertEqual(self._delete(ADMIN_A), (200, True))

    def test_the_operator_still_deletes(self):
        self.assertEqual(self._delete(OPERATOR), (200, True))

    def test_an_unknown_id_is_404(self):
        db = _db()
        st = _run(lambda: server.delete_admin_user(str(ObjectId()), ADMIN_A), db)
        self.assertEqual(st, 404)


class CheckoutIsHeldToTheCheckinsProject(unittest.TestCase):
    def _checkout(self, actor, checkin_id=None):
        db = _db()
        st = _run(lambda: server.check_out_worker(
            str(checkin_id or CHECKIN), actor), db)
        return st, db.checkins.docs[0].get("status")

    def test_another_companys_user_is_refused_and_nothing_changes(self):
        for actor in (CP_B, ADMIN_B):
            st, status = self._checkout(actor)
            self.assertIn(st, (403, 404), actor["id"])
            self.assertEqual(status, "checked_in", actor["id"])

    def test_a_site_device_for_another_project_is_refused(self):
        st, status = self._checkout(DEVICE_ELSEWHERE)
        self.assertIn(st, (403, 404))
        self.assertEqual(status, "checked_in")

    def test_the_project_still_checks_out(self):
        for actor in (CP_A, ADMIN_A, DEVICE_A):
            self.assertEqual(self._checkout(actor), (200, "checked_out"),
                             actor["id"])

    def test_an_unknown_checkin_is_404(self):
        self.assertEqual(self._checkout(CP_A, ObjectId())[0], 404)


class TheDeadCardAuditAdminRoutesAreGone(unittest.TestCase):
    def test_no_route_serves_them(self):
        paths = {getattr(r, "path", "") for r in server.app.routes}
        for p in ("/api/admin/card-flags/{flag_id}/action",
                  "/api/admin/projects/{project_id}/card-queue"):
            self.assertFalse(p in paths, p)


class TheAnnotationLinkEscapesItsId(unittest.TestCase):
    def _get(self, raw_path):
        async def go():
            t = httpx.ASGITransport(app=server.app)
            async with httpx.AsyncClient(transport=t, base_url="http://t") as c:
                return await c.get(raw_path)
        return asyncio.run(go())

    def test_a_breakout_id_never_reaches_the_page_as_markup(self):
        r = self._get('/a/x%22%3Balert(document.domain)%3B%22')
        self.assertNotIn('alert(document.domain)', r.text)

    def test_an_angle_bracket_id_never_reaches_the_page(self):
        r = self._get('/a/x%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E')
        self.assertNotIn('<img', r.text)

    def test_a_real_id_still_redirects(self):
        oid = str(ObjectId())
        r = self._get(f"/a/{oid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"annotation={oid}", r.text)
        self.assertIn(f"levelog://annotation/{oid}", r.text)


if __name__ == "__main__":
    unittest.main()
