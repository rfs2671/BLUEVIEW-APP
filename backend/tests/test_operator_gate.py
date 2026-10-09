"""Every platform-operator route answers 404 to everyone else. CI fails if not.

THE INVENTORY. Every route under /api/owner/, /api/debug/ and
/api/whatsapp/debug/, plus the operator routes listed in OPERATOR_ROUTES, must
carry `require_operator_404` as its FIRST dependency (so nothing else -- an
approval gate, a project lookup -- can answer 401/403 before it). And every
route that carries it must be in the inventory, so the list cannot go stale
silently.

THE BEHAVIOUR. For each route, over HTTP: no token, a bad token and a
signed-in non-operator (an admin, and an account with the retired "owner"
role) all get 404. The operator gets through (one positive control, so a 404
cannot come from a mistyped path).

THE SHADOW GATE IS GONE. `require_platform_operator`, PLATFORM_GATES_ENFORCED,
`get_platform_operator_user`, `require_company_scope` and the inline
`role != "owner"` / 403 operator checks no longer exist.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.test")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from bson import ObjectId  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from scripts import platform_gate_log_report as report  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

OPERATOR_PREFIXES = ("/api/owner/", "/api/debug/", "/api/whatsapp/debug/")

#: Operator-only routes outside those prefixes.
OPERATOR_ROUTES = {
    ("GET", "/api/projects/pending-deletion"),
    ("GET", "/api/projects/{project_id}/dependencies"),
    ("DELETE", "/api/projects/{project_id}/hard-delete"),
    ("POST", "/api/projects/{project_id}/debug/test-plan-image-send"),
    ("GET", "/api/admin/filing-jobs"),
    ("GET", "/api/admin/notifications"),
    ("POST", "/api/admin/notifications/{notification_id}/resend"),
    ("POST", "/api/admin/migrate-company-data"),
}

#: Under an operator prefix but not an operator route: a company admin's
#: own diagnostic on their own project.
NOT_OPERATOR = {
    ("GET", "/api/projects/{project_id}/debug/indexed-pages"),
}


def _routes():
    for r in server.app.routes:
        if not hasattr(r, "dependant"):
            continue
        for m in sorted(r.methods or ()):
            if m in ("HEAD", "OPTIONS"):
                continue
            yield m, r.path, r


def _is_operator_route(method, path):
    if (method, path) in NOT_OPERATOR:
        return False
    return path.startswith(OPERATOR_PREFIXES) or (method, path) in OPERATOR_ROUTES


def _gated(route):
    def walk(d):
        for x in d.dependencies:
            if x.call is server.require_operator_404:
                return True
            if walk(x):
                return True
        return False
    return walk(route.dependant)


def _first_dep(route):
    deps = route.dependant.dependencies
    return deps[0].call if deps else None


INVENTORY = sorted((m, p) for m, p, r in _routes() if _is_operator_route(m, p))


class InventoryTest(unittest.TestCase):

    def test_the_inventory_is_not_empty(self):
        self.assertGreaterEqual(len(INVENTORY), 40, INVENTORY)
        for want in OPERATOR_ROUTES:
            self.assertIn(want, INVENTORY, f"{want} is listed but not registered")

    def test_every_operator_route_carries_the_404_gate_first(self):
        missing, late = [], []
        for m, p, r in _routes():
            if not _is_operator_route(m, p):
                continue
            if not _gated(r):
                missing.append(f"{m} {p}")
            elif _first_dep(r) is not server.require_operator_404:
                late.append(f"{m} {p} (first: {getattr(_first_dep(r), '__name__', '?')})")
        self.assertEqual(missing, [], "operator routes without require_operator_404")
        self.assertEqual(late, [], "require_operator_404 must be the first dependency")

    def test_every_gated_route_is_in_the_inventory(self):
        stray = [f"{m} {p}" for m, p, r in _routes()
                 if _gated(r) and not _is_operator_route(m, p)]
        self.assertEqual(stray, [], "gated routes missing from the inventory: "
                                    "add them to OPERATOR_ROUTES")


class ShadowGateIsGoneTest(unittest.TestCase):
    SRC = (_BACKEND / "server.py").read_text()

    def test_no_shadow_gate_or_old_gates(self):
        for name in ("require_platform_operator", "get_platform_operator_user",
                     "require_company_scope", "PLATFORM_GATES_ENFORCED",
                     "_require_operator_flag"):
            self.assertFalse(hasattr(server, name), name)
        self.assertNotIn('os.environ.get(\n    "PLATFORM_GATES_ENFORCED"', self.SRC)
        self.assertNotIn('"PLATFORM_GATES_ENFORCED"', self.SRC)

    def test_no_inline_operator_or_owner_role_gates(self):
        self.assertNotIn('detail="Owner access required"', self.SRC)
        self.assertNotIn("Platform operator access required", self.SRC)
        code = [l for l in self.SRC.splitlines() if not l.strip().startswith("#")]
        hits = [l.strip() for l in code
                if re.search(r'get\("role"\)\s*[!=]=\s*"owner"', l)]
        self.assertEqual(hits, [])


def _fill(path):
    return re.sub(r"\{[^}]+\}", str(ObjectId()), path)


class Every404Test(unittest.TestCase):
    """Over HTTP, for every route in the inventory."""

    ADMIN_ID = ObjectId()
    OWNER_ROLE_ID = ObjectId()
    OP_ID = ObjectId()

    def setUp(self):
        self.db = FakeDb(users=[
            {"_id": self.ADMIN_ID, "email": "admin@acme.test", "role": "admin",
             "company_id": "c1", "account_status": "approved"},
            {"_id": self.OWNER_ROLE_ID, "email": "own@acme.test", "role": "owner",
             "company_id": "c1", "account_status": "approved"},
            {"_id": self.OP_ID, "email": "ops@levelog.test", "role": "admin",
             "account_status": "approved", "is_platform_operator": True},
        ])
        self.patch = patch.object(server, "db", self.db)
        self.patch.start()
        self.client = TestClient(server.app, raise_server_exceptions=False)

    def tearDown(self):
        self.patch.stop()

    def _token(self, uid, role):
        return server.create_token(str(uid), "x@x.test", role, company_id="c1")

    def _call(self, method, path, headers):
        return self.client.request(method, _fill(path), headers=headers, json={})

    def _all(self, label, headers):
        wrong = []
        for m, p in INVENTORY:
            r = self._call(m, p, headers)
            if r.status_code != 404:
                wrong.append(f"{m} {p} -> {r.status_code}")
        self.assertEqual(wrong, [], f"{label}: not 404")

    def test_unsigned_gets_404(self):
        self._all("no token", {})

    def test_bad_token_gets_404(self):
        self._all("bad token", {"Authorization": "Bearer not.a.jwt"})

    def test_signed_in_admin_gets_404(self):
        self._all("company admin",
                  {"Authorization": f"Bearer {self._token(self.ADMIN_ID, 'admin')}"})

    def test_retired_owner_role_gets_404(self):
        self._all("role=owner, no operator flag",
                  {"Authorization": f"Bearer {self._token(self.OWNER_ROLE_ID, 'owner')}"})

    def test_the_operator_gets_through(self):
        """Positive control: the same harness, the operator, a real 200."""
        r = self.client.get(
            "/api/owner/deleted",
            headers={"Authorization": f"Bearer {self._token(self.OP_ID, 'admin')}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("items", r.json())


class LogReportTest(unittest.TestCase):
    LOG = [
        '2026-09-20T10:00:00Z WARNING [platform-gate SHADOW] would have blocked '
        "non-operator 'a@acme.test' (role='admin'). Set PLATFORM_GATES_ENFORCED=true ...",
        '2026-09-20T10:00:01Z INFO: 10.0.0.1:0 - "GET /api/owner/companies/'
        '6a5f63bc147407d3261df2c7/filing-reps HTTP/1.1" 200',
        '2026-09-21T09:00:00Z WARNING [platform-gate] blocked non-operator \'b@x.test\'',
        '2026-09-21T09:00:00Z INFO: 10.0.0.2:0 - "GET /api/projects HTTP/1.1" 200',
        '{"timestamp": "2026-09-22T08:00:00Z", "message": "[platform-gate SHADOW] would '
        'have blocked non-operator \'c@x.test\' (role=\'owner\'). ..."}',
    ]

    def test_counts_by_mode_role_route_without_pii(self):
        out = report.tally(self.LOG)
        self.assertEqual(out[("shadow (would have denied)", "admin",
                              "GET /api/owner/companies/{id}/filing-reps")], 1)
        self.assertEqual(out[("enforced (denied)", "(not logged)", "(route unknown)")], 1)
        self.assertEqual(out[("shadow (would have denied)", "owner", "(route unknown)")], 1)
        flat = repr(out)
        for pii in ("@", "10.0.0", "6a5f63bc"):
            self.assertNotIn(pii, flat)

    def test_nothing_found(self):
        self.assertEqual(sum(report.tally(["INFO: started"]).values()), 0)


if __name__ == "__main__":
    unittest.main()
