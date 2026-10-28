"""THE OPERATOR REACHES A PROJECT'S ADMIN ACTIONS - AUDITED - AND NOBODY ELSE
GAINS ANYTHING.

The platform operator's account carries no company and no assigned projects,
so project_access_ok refused it on every project route: the plan-reader
rebuild (POST /projects/{id}/plan-glyphs/run) answered him 403 and had to be
triggered from a tenant admin's session (measured 2026-10-10).

Ruling (operator, 2026-10-23, option 2):
  - a SEPARATE project gate for admin actions, require_project_admin_access:
    the ordinary rule, or the operator; never a branch in project_access_ok,
    which decides ~117 routes and cannot tell an admin action from a read;
  - ONLY the routes whose bodies take no company from the person acting -
    the operator has none, and the other eleven would write records that
    belong to no tenant (a separate change, company from the project);
  - plan-index/{file}/retry joins them: its in-body operator check never ran,
    because the project gate before it refused the operator;
  - every operator use writes an audit row - and if the row cannot be written
    the request is refused;
  - a non-operator from another company gets 403 on all of them.
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
from fastapi.routing import APIRoute  # noqa: E402

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402

CO_A, CO_B = "co-a", "co-b"
PROJ_A = ObjectId()
FILE_A = ObjectId()

#: the eleven admin routes whose bodies stamp the ACTOR's company on what they
#: write or read - NOT opened to the operator by this change (measured
#: 2026-10-23); held here so a later edit cannot open one by accident
ACTOR_COMPANY_ROUTES = (
    ("POST", "/api/projects/{project_id}/nfc-tags"),
    ("POST", "/api/admin/site-devices"),
    ("POST", "/api/projects/{project_id}/site-devices"),
    ("POST", "/api/admin/cs-registrations"),
    ("POST", "/api/admin/checklists/{checklist_id}/assign"),
    ("GET", "/api/projects/{project_id}/dropbox-subfolders"),
    ("PUT", "/api/projects/{project_id}/site-device-subfolders"),
    ("PUT", "/api/projects/{project_id}/dob-config"),
    ("POST", "/api/projects/{project_id}/reindex-document"),
    ("POST", "/api/projects/{project_id}/reindex-all"),
)


#: THE RULED LIST, written out (operator rulings 2026-10-23 and 2026-10-27):
#: the routes that admit the platform operator, and no other.
RULED_ROUTES = (
    ("PUT", "/api/projects/{project_id}"),
    ("DELETE", "/api/projects/{project_id}/nfc-tags/{tag_id}"),
    ("GET", "/api/projects/{project_id}/site-devices"),
    ("POST", "/api/projects/{project_id}/safety-staff"),
    ("GET", "/api/projects/{project_id}/whatsapp/people"),
    ("PUT", "/api/projects/{project_id}/whatsapp/people/{key}"),
    ("PUT", "/api/projects/{project_id}/whatsapp/people/{key}/language"),
    ("DELETE", "/api/projects/{project_id}/whatsapp/people/{key}"),
    ("POST", "/api/projects/{project_id}/plan-glyphs/run"),
    ("POST", "/api/projects/{project_id}/plan-index/{file_id}/retry"),
    # ruling 33, 2026-10-27: drawing-set questions, "view + ask only" - the
    # operator never answers one (.../{question_id}/answer is not here)
    ("GET", "/api/projects/{project_id}/plan-set-questions"),
    ("POST", "/api/projects/{project_id}/plan-set-questions/ask"),
)


def _present():
    assert hasattr(server, "require_project_admin_access"), \
        "no project gate admits the operator on an admin action in this tree"


def _deps(dependant) -> set:
    out = set()
    for d in dependant.dependencies:
        out.add(getattr(d.call, "__name__", type(d.call).__name__))
        out |= _deps(d)
    return out


def _routes():
    return {(m, r.path): _deps(r.dependant) for r in server.app.routes
            if isinstance(r, APIRoute) for m in r.methods}


class TheGateIsCarriedExactlyWhereRuled(unittest.TestCase):
    """Read from the app's own route table - the call sites, not the source."""

    def test_every_listed_route_carries_it_and_not_the_old_gate(self):
        _present()
        routes = _routes()
        for key in server.OPERATOR_PROJECT_ADMIN_ROUTES:
            self.assertIn(key, routes, key)
            self.assertIn("require_project_admin_access", routes[key], key)
            self.assertNotIn("require_project_access", routes[key], key)

    def test_the_ruled_list_is_the_twelve(self):
        _present()
        self.assertEqual(len(RULED_ROUTES), 12)
        self.assertEqual(set(server.OPERATOR_PROJECT_ADMIN_ROUTES), set(RULED_ROUTES))
        self.assertEqual(len(server.OPERATOR_PROJECT_ADMIN_ROUTES), 12)
        self.assertNotIn(("POST", "/api/projects/{project_id}/plan-set-questions/{question_id}/answer"),
                         server.OPERATOR_PROJECT_ADMIN_ROUTES, "view + ask only: never answer")

    def test_no_other_route_carries_it(self):
        _present()
        carrying = {k for k, d in _routes().items() if "require_project_admin_access" in d}
        self.assertEqual(carrying, set(server.OPERATOR_PROJECT_ADMIN_ROUTES))

    def test_the_project_delete_and_the_actor_company_routes_are_not_opened(self):
        _present()
        routes = _routes()
        for key in ACTOR_COMPANY_ROUTES + (("DELETE", "/api/projects/{project_id}"),):
            self.assertIn(key, routes, key)
            self.assertNotIn("require_project_admin_access", routes[key], key)
            self.assertNotIn(key, server.OPERATOR_PROJECT_ADMIN_ROUTES, key)

    def test_every_listed_route_also_carries_a_rank_gate(self):
        _present()
        routes = _routes()
        for key in server.OPERATOR_PROJECT_ADMIN_ROUTES:
            self.assertTrue(routes[key] & {"get_admin_user", "get_project_admin_user"}, key)


def _db(fail_audit=False):
    db = AsyncFakeDB()
    db.projects.docs.append({"_id": PROJ_A, "company_id": CO_A, "name": "Tower",
                             "status": "active", "is_deleted": False})
    db.project_files.docs.append({"_id": FILE_A, "project_id": str(PROJ_A),
                                  "company_id": CO_A, "name": "set.pdf", "is_deleted": False})
    for email, pw, role, co, op in (("a@a.test", "pw-a-123", "admin", CO_A, False),
                                    ("b@b.test", "pw-b-123", "admin", CO_B, False),
                                    ("op@x.test", "pw-op-123", "owner", None, True)):
        db.users.docs.append({"_id": ObjectId(), "email": email, "name": email,
                              "password": server.hash_password(pw), "role": role,
                              "company_id": co, "is_platform_operator": op,
                              "account_status": "approved", "is_deleted": False})
    if fail_audit:
        async def boom(*_a, **_k):
            raise RuntimeError("audit store down")
        db.audit_logs.insert_one = boom
    return db


def _path(template):
    return (template.replace("{project_id}", str(PROJ_A)).replace("{file_id}", str(FILE_A))
            .replace("{tag_id}", "tag-1").replace("{key}", "k-1")
            .replace("{user_id}", str(ObjectId())))


async def _requests(db, email, pw, keys):
    out = {}
    with patch.object(server, "db", db):
        if hasattr(server, "auth_rate_limiter") and hasattr(server.auth_rate_limiter, "requests"):
            server.auth_rate_limiter.requests.clear()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                     base_url="http://t") as c:
            r = await c.post("/api/auth/login", json={"email": email, "password": pw})
            assert r.status_code == 200, r.text
            tok = r.json()["token"]
            for method, template in keys:
                r = await c.request(method, _path(template), json={},
                                    headers={"Authorization": f"Bearer {tok}"})
                out[(method, template)] = (r.status_code, r.text[:200])
    return out


class ANonOperatorFromAnotherCompanyIsRefused(unittest.TestCase):

    def test_403_on_every_one(self):
        """Real requests through the app (middleware, JWT, the route's own
        dependencies). The two account routes the ruling counts among the
        eleven already admit the operator and hold everyone else to the
        target's company; they are held here too."""
        _present()
        keys = list(server.OPERATOR_PROJECT_ADMIN_ROUTES) + [
            ("PUT", "/api/admin/users/{user_id}"),
            ("POST", "/api/admin/users/{user_id}/assign-projects")]
        db = _db()
        got = asyncio.run(_requests(db, "b@b.test", "pw-b-123", keys))
        for key, (status, body) in got.items():
            # an account route cannot find a user in company B's tenant: 403 or 404
            want = (403, 404) if "/admin/users/" in key[1] else (403,)
            self.assertIn(status, want, f"{key}: {status} {body}")
        self.assertEqual([r for r in db.audit_logs.docs
                          if r.get("action") == "operator_project_admin_access"], [])


class EveryOperatorUseIsAudited(unittest.TestCase):

    def test_the_operator_passes_the_gate_and_one_row_is_written_per_request(self):
        _present()
        db = _db()
        keys = [("GET", "/api/projects/{project_id}/site-devices"),
                ("GET", "/api/projects/{project_id}/whatsapp/people")]
        got = asyncio.run(_requests(db, "op@x.test", "pw-op-123", keys))
        for key, (status, body) in got.items():
            self.assertNotIn(status, (401, 403, 404), f"{key}: {status} {body}")
        rows = [r for r in db.audit_logs.docs if r.get("action") == "operator_project_admin_access"]
        self.assertEqual(len(rows), 2)
        for r, (method, template) in zip(rows, keys):
            self.assertEqual(r["resource_id"], str(PROJ_A))
            self.assertEqual(r["details"]["company_id"], CO_A)
            self.assertEqual((r["details"]["method"], r["details"]["path"]),
                             (method, _path(template)))
            self.assertNotIn(r["user_id"], ("", "UNATTRIBUTED"))

    def test_no_audit_row_no_access(self):
        _present()
        db = _db(fail_audit=True)
        got = asyncio.run(_requests(db, "op@x.test", "pw-op-123",
                                    [("GET", "/api/projects/{project_id}/site-devices")]))
        (status, body), = got.values()
        self.assertEqual(status, 503, body)

    def test_the_rebuild_is_reached(self):
        """The case that started this: plan-glyphs/run answered the operator
        403. The pass itself is stubbed - only the gate is under test."""
        _present()
        db = _db()

        async def no_pass(_pid):
            return {}
        with patch.object(server, "_plan_glyph_pass", no_pass):
            got = asyncio.run(_requests(db, "op@x.test", "pw-op-123",
                                        [("POST", "/api/projects/{project_id}/plan-glyphs/run")]))
        (status, body), = got.values()
        self.assertEqual(status, 200, body)
        self.assertEqual(len([r for r in db.audit_logs.docs
                              if r.get("action") == "operator_project_admin_access"]), 1)

    def test_the_owning_company_admin_is_unchanged_and_not_audited_as_operator(self):
        _present()
        db = _db()
        got = asyncio.run(_requests(db, "a@a.test", "pw-a-123",
                                    [("GET", "/api/projects/{project_id}/site-devices")]))
        (status, body), = got.values()
        self.assertNotIn(status, (401, 403, 404), body)
        self.assertEqual([r for r in db.audit_logs.docs
                          if r.get("action") == "operator_project_admin_access"], [])


if __name__ == "__main__":
    unittest.main()
