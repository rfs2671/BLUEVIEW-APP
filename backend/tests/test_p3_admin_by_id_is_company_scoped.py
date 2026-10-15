"""Two admin routes read or wrote a row BY ID with no company scope (security
audit P3, 2026-10-13). Both are used by the admin screens, so they are scoped
to the caller's company rather than moved to the operator:

  GET /admin/cs-registrations/{id}           licence number, phone, NYC ID
                                             email of any tenant's
                                             superintendent. PUT and DELETE
                                             already used
                                             _cs_registration_under_admin; GET
                                             was the one left.
  PUT /admin/compliance-alerts/{id}/resolve  any tenant's alert marked
                                             resolved. The list route already
                                             shows a caller only their own
                                             company's alerts; resolve now
                                             matches it.
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from bson import ObjectId  # noqa: E402

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402

REG = ObjectId()
ALERT = ObjectId()
PLATFORM_ALERT = ObjectId()

ADMIN_A = {"id": "a", "role": "admin", "company_id": "co-a",
           "account_status": "approved"}
ADMIN_B = {"id": "b", "role": "admin", "company_id": "co-b",
           "account_status": "approved"}
OPERATOR = {"id": "op", "role": "owner", "company_id": None,
            "is_platform_operator": True, "account_status": "approved"}


def _db():
    db = AsyncFakeDB()
    db.cs_registrations.docs.append({
        "_id": REG, "company_id": "co-a", "project_id": "p1",
        "license_number": "SECRET-LIC-77", "is_deleted": False})
    db.compliance_alerts.docs.append({
        "_id": ALERT, "company_id": "co-a", "resolved": False})
    db.compliance_alerts.docs.append({
        "_id": PLATFORM_ALERT, "company_id": None, "resolved": False})
    return db


def _run(fn, db):
    with patch.object(server, "db", db):
        try:
            return 200, asyncio.run(fn())
        except server.HTTPException as e:
            return e.status_code, None


class CsRegistrationReadIsCompanyScoped(unittest.TestCase):
    def test_another_companys_admin_cannot_read_it(self):
        st, body = _run(lambda: server.get_cs_registration(str(REG), ADMIN_B), _db())
        self.assertIn(st, (403, 404))
        self.assertNotIn("SECRET-LIC-77", str(body))

    def test_its_own_company_and_the_operator_still_read_it(self):
        for who in (ADMIN_A, OPERATOR):
            st, body = _run(lambda: server.get_cs_registration(str(REG), who), _db())
            self.assertEqual(st, 200, who["id"])
            self.assertIn("SECRET-LIC-77", str(body))


class ResolvingAnAlertIsCompanyScoped(unittest.TestCase):
    def _resolve(self, who, alert_id=ALERT):
        db = _db()
        st, _ = _run(lambda: server.resolve_compliance_alert(str(alert_id), who), db)
        row = next(d for d in db.compliance_alerts.docs if d["_id"] == alert_id)
        return st, row.get("resolved")

    def test_another_companys_admin_is_refused_and_nothing_changes(self):
        self.assertEqual(self._resolve(ADMIN_B)[1], False)
        self.assertIn(self._resolve(ADMIN_B)[0], (403, 404))

    def test_a_company_admin_cannot_resolve_a_platform_alert(self):
        st, resolved = self._resolve(ADMIN_A, PLATFORM_ALERT)
        self.assertIn(st, (403, 404))
        self.assertFalse(resolved)

    def test_its_own_company_and_the_operator_still_resolve(self):
        self.assertEqual(self._resolve(ADMIN_A), (200, True))
        self.assertEqual(self._resolve(OPERATOR), (200, True))
        self.assertEqual(self._resolve(OPERATOR, PLATFORM_ALERT), (200, True))

    def test_an_unknown_alert_is_404(self):
        st, _ = _run(lambda: server.resolve_compliance_alert(str(ObjectId()), ADMIN_A), _db())
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
