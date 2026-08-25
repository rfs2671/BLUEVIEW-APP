"""Tenant isolation — the /workers surface.

SEV-0, 2026-08-25. The project surface was closed in two batches (reads, then
the 25 writes). The WORKER surface was never done, and it was worse: three of
its routes had no ownership check of any kind, and the two that did used the
short-circuiting shape

    company_id = get_user_company_id(current_user)
    if company_id and worker.get("company_id") != company_id:
        raise HTTPException(403, ...)

which PASSES when the caller's company_id is falsy. What was reachable by any
authenticated account with no company:

    GET    /workers                          every tenant's roster
    GET    /workers/{id}                     any worker
    PUT    /workers/{id}                     rename / re-phone any worker
    DELETE /workers/{id}                     soft-delete any worker
    GET    /workers/{id}/certifications      any worker's SST/OSHA evidence
    POST   /workers/{id}/certifications      forge a cleared cert
    DELETE /workers/{id}/certifications/{i}  strip a cert
    GET    /workers/{id}/osha-card           `None != None` is False, so it fell
                                             through to the "has a check-in"
                                             branch and queried it with a None
                                             company_id, which matches orphans
    POST   /admin/certifications/scan-expiring   every tenant's blocked workers

A falsy company_id is the DEFAULT account state, not an edge case: self-serve
registration sets it to None and a company is attached only by POST
/onboarding/company. Opening self-registration to trial users is what made this
urgent.

READ and WRITE are asserted as DIFFERENT rules, because collapsing them would
either break the gate or leave the write side open:

  WRITE  same company only. A site device must never rename or delete a worker,
         and "he checked in on my job" is grounds to read his card, not to edit
         another tenant's record.
  READ   same company, OR the provisioned site device, OR a company holding a
         check-in for this worker. The last two already existed on osha-card and
         the kiosk depends on them.

Four directions per rule, because a guard that 403s everyone is as broken as one
that 403s nobody:

  1. cross-company caller   -> 403
  2. own-company admin      -> works
  3. no-company caller      -> 403          (the actual hole)
  4. site device / check-in -> read yes, write no

Plus a WIRING pin that walks the live FastAPI dependant tree, so a right-looking
decorator that never took effect still fails.

    python backend/tests/test_workers_tenant_isolation.py
"""

import asyncio
import os
import re
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

# ── Fixtures ─────────────────────────────────────────────────────────────────

WORKER_A = {"_id": "wA", "company_id": "companyA", "name": "Luis Ramos"}
WORKER_B = {"_id": "wB", "company_id": "companyB", "name": "Marek Nowak"}
# A row created before company_id was stamped, or by the public
# /workers/register endpoint which never sets one. Absence is not authorization
# on EITHER side, so nobody reaches it by company.
WORKER_ORPHAN = {"_id": "wO", "company_id": None, "name": "Unknown Origin"}
WORKERS = {"wA": WORKER_A, "wB": WORKER_B, "wO": WORKER_ORPHAN}

ADMIN_A = {"_id": "ua", "role": "admin", "company_id": "companyA",
           "account_status": "approved"}
ADMIN_B = {"_id": "ub", "role": "admin", "company_id": "companyB",
           "account_status": "approved"}
# `owner` is what every self-serve signup receives — a CUSTOMER role.
OWNER_B = {"_id": "ob", "role": "owner", "company_id": "companyB",
           "account_status": "approved"}
# THE HOLE. Default state of every self-registered account before onboarding.
NO_COMPANY = {"_id": "un", "role": "admin", "company_id": None,
              "account_status": "approved"}
# Provisioned for projA only.
DEVICE_A = {"_id": "dev1", "site_mode": True, "role": "site_device",
            "project_id": "projA", "company_id": "companyA"}
# Different tenant, but worker B checked in on one of its jobs.
GC_C = {"_id": "uc", "role": "admin", "company_id": "companyC",
        "account_status": "approved"}

# Check-ins that exist. (worker_id, project_id, company_id)
CHECKINS = [
    {"worker_id": "wB", "project_id": "projA", "company_id": "companyA"},
    {"worker_id": "wB", "project_id": "projC", "company_id": "companyC"},
]


def _db():
    async def find_worker(q, *a, **kw):
        w = WORKERS.get(q.get("_id"))
        return dict(w) if w else None

    async def find_checkin(q, *a, **kw):
        for c in CHECKINS:
            if all(c.get(k) == v for k, v in q.items()):
                return c
        return None

    # update_one has to behave, or the WRITE routes 500 on the mock before they
    # reach the point this test is about. A 500 would "fail" against the
    # pre-fix build for the wrong reason; we want a clean 200 there, so the
    # diff between builds is 200-vs-403 and nothing else.
    async def update_one(q, upd, *a, **kw):
        res = MagicMock()
        res.matched_count = 1
        res.modified_count = 1
        return res

    db = MagicMock()
    db.workers.find_one = AsyncMock(side_effect=find_worker)
    db.workers.update_one = AsyncMock(side_effect=update_one)
    db.checkins.find_one = AsyncMock(side_effect=find_checkin)
    return db


def _assert_access(worker_id, user, write=False):
    """Run the real gate against the doubles."""
    with patch.object(server, "db", _db()):
        return asyncio.run(
            server._assert_worker_access(worker_id, user, write=write)
        )


passed = 0
failed = 0


class WorkerWriteGate(unittest.TestCase):
    """Same company, and nothing else."""

    # ---- direction 1: cross-company blocked, both ways ----
    def test_cross_company_admin_blocked(self):
        with self.assertRaises(HTTPException) as c:
            _assert_access("wB", ADMIN_A, write=True)
        self.assertEqual(c.exception.status_code, 403)

    def test_cross_company_admin_blocked_reverse(self):
        with self.assertRaises(HTTPException) as c:
            _assert_access("wA", ADMIN_B, write=True)
        self.assertEqual(c.exception.status_code, 403)

    def test_cross_company_owner_blocked(self):
        """`owner` is a customer role, not a platform one."""
        with self.assertRaises(HTTPException) as c:
            _assert_access("wA", OWNER_B, write=True)
        self.assertEqual(c.exception.status_code, 403)

    # ---- direction 2: own company still works ----
    def test_own_company_admin_allowed(self):
        self.assertEqual(_assert_access("wA", ADMIN_A, write=True)["_id"], "wA")

    # ---- direction 3: THE HOLE — absence is not authorization ----
    def test_no_company_caller_blocked(self):
        with self.assertRaises(HTTPException) as c:
            _assert_access("wA", NO_COMPANY, write=True)
        self.assertEqual(c.exception.status_code, 403)

    def test_no_company_caller_blocked_on_orphan_worker(self):
        """Two missing companies must not compare EQUAL — the osha-card bug."""
        with self.assertRaises(HTTPException) as c:
            _assert_access("wO", NO_COMPANY, write=True)
        self.assertEqual(c.exception.status_code, 403)

    def test_admin_cannot_write_orphan_worker(self):
        with self.assertRaises(HTTPException) as c:
            _assert_access("wO", ADMIN_A, write=True)
        self.assertEqual(c.exception.status_code, 403)

    # ---- direction 4: the read-only paths must NOT grant writes ----
    def test_site_device_cannot_write(self):
        """A kiosk shows a card. It never renames or deletes a worker."""
        with self.assertRaises(HTTPException) as c:
            _assert_access("wB", DEVICE_A, write=True)
        self.assertEqual(c.exception.status_code, 403)

    def test_checkin_does_not_grant_write(self):
        """GC_C holds a check-in for wB. That is read evidence, not ownership."""
        with self.assertRaises(HTTPException) as c:
            _assert_access("wB", GC_C, write=True)
        self.assertEqual(c.exception.status_code, 403)

    def test_missing_worker_is_404_not_403(self):
        with self.assertRaises(HTTPException) as c:
            _assert_access("nope", ADMIN_A, write=True)
        self.assertEqual(c.exception.status_code, 404)


class WorkerReadGate(unittest.TestCase):
    """Same company, plus the two operational paths the gate must not break."""

    def test_cross_company_read_blocked(self):
        with self.assertRaises(HTTPException) as c:
            _assert_access("wA", ADMIN_B)
        self.assertEqual(c.exception.status_code, 403)

    def test_no_company_read_blocked(self):
        with self.assertRaises(HTTPException) as c:
            _assert_access("wA", NO_COMPANY)
        self.assertEqual(c.exception.status_code, 403)

    def test_own_company_read_allowed(self):
        self.assertEqual(_assert_access("wA", ADMIN_A)["_id"], "wA")

    # ---- the kiosk must keep working ----
    def test_site_device_reads_worker_on_its_project(self):
        """wB checked in on projA; DEVICE_A is provisioned for projA."""
        self.assertEqual(_assert_access("wB", DEVICE_A)["_id"], "wB")

    def test_site_device_blocked_for_worker_not_on_its_project(self):
        with self.assertRaises(HTTPException) as c:
            _assert_access("wO", DEVICE_A)
        self.assertEqual(c.exception.status_code, 403)

    # ---- the GC compliance-review path must keep working ----
    def test_company_with_checkin_may_read(self):
        """GC_C holds a check-in for wB, whose record belongs to companyB."""
        self.assertEqual(_assert_access("wB", GC_C)["_id"], "wB")

    def test_company_without_checkin_blocked(self):
        with self.assertRaises(HTTPException) as c:
            _assert_access("wA", GC_C)
        self.assertEqual(c.exception.status_code, 403)


class ListEndpointFailsClosed(unittest.TestCase):
    """`if company_id:` returned EVERY tenant's roster to a no-company caller."""

    def _query_for(self, user):
        captured = {}

        async def fake_paginated(coll, query, **kw):
            captured["q"] = query
            return {"items": [], "total": 0}

        with patch.object(server, "paginated_query", fake_paginated):
            asyncio.run(server.get_workers(current_user=user, limit=50, skip=0))
        return captured["q"]

    def test_own_company_filters_to_that_company(self):
        self.assertEqual(self._query_for(ADMIN_A).get("company_id"), "companyA")

    def test_no_company_gets_an_unsatisfiable_filter(self):
        q = self._query_for(NO_COMPANY)
        self.assertIsNone(q.get("_id", "MISSING"),
                          "a caller with no company must get `_id: None`, an "
                          "unsatisfiable filter — not an unfiltered query")

    def test_no_company_filter_is_not_company_id_none(self):
        """`company_id: None` MATCHES the orphan rows. It is not a fix."""
        q = self._query_for(NO_COMPANY)
        self.assertNotIn("company_id", q,
                         "filtering on company_id: None would return exactly "
                         "the orphan workers this is meant to keep out of reach")


class Wiring(unittest.TestCase):
    """The decorator text can be right while the dependency never took effect."""

    GATED = {
        ("GET", "/api/workers/{worker_id}"): "require_worker_access",
        ("PUT", "/api/workers/{worker_id}"): "require_worker_write_access",
        ("DELETE", "/api/workers/{worker_id}"): "require_worker_write_access",
        ("GET", "/api/workers/{worker_id}/certifications"): "require_worker_access",
        ("POST", "/api/workers/{worker_id}/certifications"): "require_worker_write_access",
        ("DELETE", "/api/workers/{worker_id}/certifications/{cert_index}"): "require_worker_write_access",
    }

    def test_every_worker_id_route_carries_its_gate(self):
        found = {}
        for r in server.app.routes:
            path = getattr(r, "path", "")
            if not path.startswith("/api/workers/{worker_id}"):
                continue
            names = {d.call.__name__ for d in r.dependant.dependencies
                     if getattr(d, "call", None)}
            for m in r.methods:
                found[(m, path)] = names

        for key, gate in self.GATED.items():
            self.assertIn(key, found, f"route vanished: {key}")
            self.assertIn(gate, found[key],
                          f"{key[0]} {key[1]} resolved deps {sorted(found[key])} "
                          f"— {gate} is not among them")

    def test_no_worker_id_route_is_ungated(self):
        """Catches a NEW {worker_id} route added without a gate."""
        ungated = []
        for r in server.app.routes:
            path = getattr(r, "path", "")
            if not path.startswith("/api/workers/{worker_id}"):
                continue
            names = {d.call.__name__ for d in r.dependant.dependencies
                     if getattr(d, "call", None)}
            if not names & {"require_worker_access", "require_worker_write_access"}:
                # osha-card calls _assert_worker_access inline, because it also
                # needs current_user for its own role restriction. Pinned by
                # source below rather than by the dependant tree.
                if path.endswith("/osha-card"):
                    continue
                ungated.append(f"{sorted(r.methods)} {path}")
        self.assertEqual(ungated, [],
                         f"{{worker_id}} routes with no tenant gate: {ungated}")

    def test_osha_card_calls_the_shared_gate(self):
        src = Path(__file__).resolve().parent.parent / "server.py"
        body = src.read_text(encoding="utf-8")
        i = body.index('async def get_worker_osha_card(')
        j = body.index('@api_router.get("/workers/{worker_id}"', i)
        window = body[i:j]
        self.assertIn("_assert_worker_access(worker_id, current_user)", window,
                      "osha-card must delegate tenancy to the shared gate")
        self.assertNotIn("if worker_company != company_id:", window,
                         "the direct != comparison treats two Nones as a match")


class EndToEndThroughTheApp(unittest.TestCase):
    """The proof, as a real request.

    The classes above call the gate directly, so against a build that HAS NO
    GATE they error on the missing attribute — which proves the function is
    absent, not that the hole was reachable. These drive the actual ASGI app
    with an authenticated no-company caller and assert the response code. On
    the pre-fix build they return 200/success; that is the vulnerability, in
    the shape an attacker would have used.
    """

    def _client(self, user):
        from fastapi.testclient import TestClient
        server.app.dependency_overrides[server.get_current_user] = lambda: user
        server.app.dependency_overrides[server.get_admin_user] = lambda: user
        return TestClient(server.app, raise_server_exceptions=False)

    def tearDown(self):
        server.app.dependency_overrides.clear()

    def _run(self, user, method, path, **kw):
        with patch.object(server, "db", _db()):
            c = self._client(user)
            return getattr(c, method)(path, **kw)

    # ---- direction 3, over the wire: the account state that made this SEV-0 --
    def test_no_company_get_is_refused(self):
        r = self._run(NO_COMPANY, "get", "/api/workers/wA")
        self.assertEqual(r.status_code, 403, r.text[:300])

    def test_no_company_put_is_refused(self):
        r = self._run(NO_COMPANY, "put", "/api/workers/wA",
                      json={"name": "OVERWRITTEN"})
        self.assertEqual(r.status_code, 403, r.text[:300])

    def test_no_company_delete_is_refused(self):
        r = self._run(NO_COMPANY, "delete", "/api/workers/wA")
        self.assertEqual(r.status_code, 403, r.text[:300])

    # ---- direction 1, over the wire ----
    def test_cross_company_put_is_refused(self):
        r = self._run(ADMIN_B, "put", "/api/workers/wA",
                      json={"name": "OVERWRITTEN"})
        self.assertEqual(r.status_code, 403, r.text[:300])

    def test_cross_company_delete_is_refused(self):
        r = self._run(ADMIN_B, "delete", "/api/workers/wA")
        self.assertEqual(r.status_code, 403, r.text[:300])

    def test_cross_company_certifications_read_is_refused(self):
        r = self._run(ADMIN_B, "get", "/api/workers/wA/certifications")
        self.assertEqual(r.status_code, 403, r.text[:300])

    def test_no_company_osha_card_is_refused(self):
        """osha-card already refused THIS one, and the fix must not regress it.

        Its old check was `worker_company != company_id` -> True here (a real
        company vs None), so it fell through to the check-in branch and found
        nothing. Narrower than the other routes, and still closed.
        """
        r = self._run(NO_COMPANY, "get", "/api/workers/wA/osha-card")
        self.assertEqual(r.status_code, 403, r.text[:300])

    def test_no_company_osha_card_on_orphan_worker_is_refused(self):
        """WHERE osha-card actually leaked: both sides missing a company.

        `None != None` is False, so the guard was skipped entirely and the card,
        OSHA number, orientations and signature were returned. It needs BOTH the
        caller and the worker to be company-less, which is exactly the pair
        self-registration plus the public /workers/register produces.
        """
        r = self._run(NO_COMPANY, "get", "/api/workers/wO/osha-card")
        self.assertEqual(r.status_code, 403, r.text[:300])

    # ---- direction 2, over the wire: the customer is not broken ----
    def test_own_company_get_still_works(self):
        r = self._run(ADMIN_A, "get", "/api/workers/wA")
        self.assertEqual(r.status_code, 200, r.text[:300])


class ScanExpiringFailsClosed(unittest.TestCase):
    """A per-worker COMPLIANCE VERDICT for every tenant is the worst leak here."""

    def test_source_uses_the_unsatisfiable_filter(self):
        src = Path(__file__).resolve().parent.parent / "server.py"
        body = src.read_text(encoding="utf-8")
        i = body.index("async def scan_expiring_certifications(")
        window = body[i:i + 1400]
        self.assertIn('query["_id"] = None', window)
        self.assertIn("is_platform_operator(admin)", window)
        self.assertNotIn("query = {}", window)


if __name__ == "__main__":
    unittest.main(verbosity=2)
