"""NO ADMIN ROUTE REACHES ANOTHER TENANT.

The census (2026-10-25, every route in the app's own route table behind an
admin-level gate - 127, read handler by handler where no scoping showed):
twelve admin routes let ANY company's admin act beyond their own company.
Ten are platform-wide - no company's at all - and belong to the operator;
three read or write one record BY ID with no company check.

  platform-wide -> require_operator_404 (everyone else: 404)
    GET/POST/PATCH/DELETE /admin/feature-flags[/{flag}]
    GET  /admin/risk-score/calibration      POST /admin/risk-score/weights
    POST /admin/run-phase-inference         GET  /admin/_sentry_test
    GET  /permit-renewals/health-status     (added 2026-10-25)
  by id -> the operator, or an admin of the record's own company (404)
    GET  /admin/cs-registrations/{id}
    PUT  /admin/compliance-alerts/{id}/resolve
    GET  /admin/users/{id}                  (added 2026-10-25)

Every request below goes through the real app: middleware, JWT, the route's
own dependencies, its handler. On main, a company-B admin gets 2xx (or the
Sentry probe's deliberate 500) from every one of them - the control.

And the platform's own still reach what they use: the BLUEVIEW admin sets a
drawing set's track and starts the plan rebuild; the operator starts the
rebuild and reaches the platform-wide routes.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import httpx  # noqa: E402
from bson import ObjectId  # noqa: E402

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB, matches  # noqa: E402

CO_A, CO_B = "co-bluview", "co-other"
PROJ_A, FILE_A = ObjectId(), ObjectId()
USER_A, REG_A, ALERT_A = ObjectId(), ObjectId(), ObjectId()
ACCOUNTS = {"a": ("a@bluview.test", "pw-a-12345"), "b": ("b@other.test", "pw-b-12345"),
            "op": ("op@platform.test", "pw-op-12345")}

#: (method, path, json body) - the platform-wide routes
PLATFORM_WIDE = (
    ("GET", "/api/admin/feature-flags", None),
    ("POST", "/api/admin/feature-flags", {"flag": "new_flag"}),
    ("PATCH", "/api/admin/feature-flags/f1", {"enabled_globally": True}),
    ("DELETE", "/api/admin/feature-flags/f1", None),
    ("GET", "/api/admin/risk-score/calibration", None),
    ("POST", "/api/admin/risk-score/weights", {"trigger_kind": "k", "prior": 0.5}),
    ("POST", "/api/admin/run-phase-inference", None),
    ("GET", "/api/admin/_sentry_test", None),
    ("GET", "/api/permit-renewals/health-status", None),
)
#: company A's records, by id
BY_ID = (
    ("GET", f"/api/admin/cs-registrations/{REG_A}", None),
    ("PUT", f"/api/admin/compliance-alerts/{ALERT_A}/resolve", None),
    ("GET", f"/api/admin/users/{USER_A}", None),
)


def _db():
    db = AsyncFakeDB()
    db.projects.docs.append({"_id": PROJ_A, "company_id": CO_A, "name": "588 Boyland",
                             "status": "active", "is_deleted": False})
    db.project_files.docs.append({"_id": FILE_A, "project_id": str(PROJ_A), "company_id": CO_A,
                                  "name": "Owners set - 6.9.26.pdf", "is_deleted": False})
    for key, co, op, uid in (("a", CO_A, False, USER_A), ("b", CO_B, False, ObjectId()),
                             ("op", None, True, ObjectId())):
        email, pw = ACCOUNTS[key]
        db.users.docs.append({"_id": uid, "email": email, "name": email,
                              "password": server.hash_password(pw),
                              "role": "owner" if op else "admin", "company_id": co,
                              "is_platform_operator": op, "phone": "+15550000000",
                              "account_status": "approved", "is_deleted": False})
    db.cs_registrations.docs.append({"_id": REG_A, "company_id": CO_A, "is_deleted": False,
                                     "license_number": "SST-1", "phone": "+15551111111"})
    db.compliance_alerts.docs.append({"_id": ALERT_A, "company_id": CO_A, "resolved": False})
    db.feature_flags.docs.append({"_id": ObjectId(), "flag": "f1", "enabled_globally": False,
                                  "enabled_for_companies": [CO_A], "enabled_for_users": [],
                                  "enabled_percentage": 0, "description": ""})
    db.system_config.docs.append({"key": "dob_now_health_check", "status": "ok", "issues": []})

    async def delete_one(flt, **_k):           # the fake has none; the flag route uses it
        hit = [d for d in db.feature_flags.docs if matches(d, flt)][:1]
        for d in hit:
            db.feature_flags.docs.remove(d)
        return type("R", (), {"deleted_count": len(hit)})()
    db.feature_flags.delete_one = delete_one
    return db


async def _as(who, calls):
    db = _db()
    out = {}

    async def no_pass(*_a, **_k):
        return {}

    async def no_inference(*_a, **_k):
        return {"n_phase_updated": 0}
    with patch.object(server, "db", db), patch.object(server, "_plan_glyph_pass", no_pass), \
            patch("lib.ai.phase_inference.run_weekly_phase_inference", no_inference):
        if hasattr(server, "auth_rate_limiter") and hasattr(server.auth_rate_limiter, "requests"):
            server.auth_rate_limiter.requests.clear()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app, raise_app_exceptions=False),
                                     base_url="http://t") as c:
            email, pw = ACCOUNTS[who]
            r = await c.post("/api/auth/login", json={"email": email, "password": pw})
            assert r.status_code == 200, r.text
            h = {"Authorization": f"Bearer {r.json()['token']}"}
            for method, path, body in calls:
                r = await c.request(method, path, json=body, headers=h)
                out[(method, path)] = r.status_code
    return out, db


def _run(who, calls):
    return asyncio.run(_as(who, calls))


class AnotherCompanysAdminIsRefused(unittest.TestCase):
    """One method per class of route; every route in it is asserted."""

    def test_the_platform_wide_routes_are_the_operators(self):
        got, db = _run("b", PLATFORM_WIDE)
        for (method, path, _b) in PLATFORM_WIDE:
            self.assertEqual(got[(method, path)], 404, (method, path, got[(method, path)]))
        # and nothing moved: the flag is still there, still off
        (f,) = [d for d in db.feature_flags.docs if d["flag"] == "f1"]
        self.assertFalse(f["enabled_globally"])

    def test_another_tenants_records_by_id(self):
        got, db = _run("b", BY_ID)
        for (method, path, _b) in BY_ID:
            # 404 (the id is not confirmed), or the CS-registration helper's
            # existing 403 - refused either way
            self.assertIn(got[(method, path)], (403, 404), (method, path, got[(method, path)]))
        (alert,) = db.compliance_alerts.docs
        self.assertFalse(alert["resolved"])


class ThePlatformsOwnStillReachWhatTheyUse(unittest.TestCase):

    def test_the_bluview_admin_sets_the_track_and_starts_the_rebuild(self):
        got, db = _run("a", (
            ("PUT", f"/api/projects/{PROJ_A}/files/{FILE_A}/drawing-track",
             {"track": "post_co", "label": "the owner's post-CO set, 6/9/26"}),
            ("POST", f"/api/projects/{PROJ_A}/plan-glyphs/run", None)))
        self.assertEqual(set(got.values()), {200}, got)
        (f,) = db.project_files.docs
        self.assertEqual(f.get("drawing_track"), "post_co")

    def test_the_bluview_admin_reads_their_own_records(self):
        got, _db_ = _run("a", BY_ID)
        self.assertEqual(set(got.values()), {200}, got)

    def test_the_operator_starts_the_rebuild_and_reaches_the_platform_routes(self):
        """REACHES = past the gate: not 401, 403 or 404. The weights route's
        422 is its own body check on a trigger kind this fake does not know.
        Left out: the Sentry probe (raises by design) and the DOB NOW health
        route, whose module captured the real database at registration - its
        gate is the same require_operator_404 the others here pass."""
        skip = {"/api/admin/_sentry_test", "/api/permit-renewals/health-status"}
        calls = ((("POST", f"/api/projects/{PROJ_A}/plan-glyphs/run", None),)
                 + tuple(c for c in PLATFORM_WIDE if c[1] not in skip))
        got, _db_ = _run("op", calls)
        for k, code in got.items():
            self.assertNotIn(code, (401, 403, 404), (k, code))
        self.assertEqual(got[("POST", f"/api/projects/{PROJ_A}/plan-glyphs/run")], 200)


if __name__ == "__main__":
    unittest.main()
