"""Nothing mints a document owned by nobody — and the gate still never blocks.

Follow-on to the /workers SEV-0 (c4b22d0). That closed the READ and WRITE holes
on existing worker rows. This closes the three paths that CREATE rows with no
tenant at all, in order of how much damage each does.

1. POST /projects  stamped `project_dict["company_id"] = admin.get("company_id")`
   UNCONDITIONALLY, None included. That is not one orphan, it is an ORPHAN
   FACTORY: every worker created at that project's gate reads
   `company_id = project.get("company_id")` and inherits the None, so a single
   mis-stamped project mints unbounded unreachable worker rows.

2. POST /workers  stamped `if company_id:` — a company-less caller silently
   created a worker owned by nobody.

3. POST /workers/register  set no company_id AT ALL, was public and
   unauthenticated, had no caller anywhere in the repo's history, and returned
   an existing worker's id on a global unscoped phone lookup — an enumeration
   oracle. Deleted.

THE RULE THIS MUST NOT BREAK, and the reason half of this file exists:

    An unfilled admin form must never stop a man from working.

The gate derives company_id from the PROJECT, not from the caller, and it is
governed by that standing ruling — FIX 1 exists because a project with no
configured trades used to 409 and a real worker could not check in. So the
refusal belongs at project creation, where a human is at a desk and can finish
onboarding, and NOWHERE on the check-in path. Every assertion in
GateIsUntouched exists to make that a pinned fact rather than an intention.

    python backend/tests/test_company_less_tenancy.py
"""

import ast
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

import server  # noqa: E402

SERVER_SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text(
    encoding="utf-8"
)

ADMIN_A = {"_id": "ua", "id": "ua", "role": "admin", "company_id": "companyA",
           "account_status": "approved"}
# THE HOLE. Default state of every self-registered account: /auth/register sets
# company_id = None outright, and only POST /onboarding/company fills it.
NO_COMPANY = {"_id": "un", "id": "un", "role": "owner", "company_id": None,
              "account_status": "approved"}
# Absent, not None — a legacy row predating the field.
MISSING_COMPANY = {"_id": "um", "id": "um", "role": "admin",
                   "account_status": "approved"}
EMPTY_COMPANY = {"_id": "ue", "id": "ue", "role": "admin", "company_id": "",
                 "account_status": "approved"}


def _call_gate(user):
    return asyncio.run(server.require_company_access(current_user=user))


class TheGateOnTenancyStamping(unittest.TestCase):
    """require_company_access existed and was wired to NOTHING. Now it is the
    single refusal both mint paths share."""

    def test_company_less_owner_refused(self):
        with self.assertRaises(HTTPException) as c:
            _call_gate(NO_COMPANY)
        self.assertEqual(c.exception.status_code, 403)

    def test_absent_company_field_refused(self):
        """`.get()` returning None and the key being absent are the same fact."""
        with self.assertRaises(HTTPException) as c:
            _call_gate(MISSING_COMPANY)
        self.assertEqual(c.exception.status_code, 403)

    def test_empty_string_company_refused(self):
        """"" is falsy and must not pass as a tenant."""
        with self.assertRaises(HTTPException) as c:
            _call_gate(EMPTY_COMPANY)
        self.assertEqual(c.exception.status_code, 403)

    def test_real_company_allowed(self):
        """Over-gate check: the customer is not broken."""
        self.assertEqual(_call_gate(ADMIN_A)["company_id"], "companyA")

    def test_message_names_the_step_that_fixes_it(self):
        """"Contact your administrator" is wrong for a self-serve owner — the
        thing they must do is finish onboarding, and the copy has to say so."""
        with self.assertRaises(HTTPException) as c:
            _call_gate(NO_COMPANY)
        self.assertIn("onboarding", c.exception.detail.lower())


class ProjectCreationRefuses(unittest.TestCase):
    """1 — the orphan factory."""

    def test_route_carries_the_dependency(self):
        found = None
        for r in server.app.routes:
            if getattr(r, "path", "") == "/api/projects" and "POST" in r.methods:
                found = {d.call.__name__ for d in r.dependant.dependencies
                         if getattr(d, "call", None)}
        self.assertIsNotNone(found, "POST /api/projects vanished")
        self.assertIn("require_company_access", found,
                      f"resolved deps {sorted(found)} — the tenancy gate is "
                      f"not among them")

    def test_require_approved_is_still_there(self):
        """The two gates answer different questions — spend, and tenancy.
        Adding one must not displace the other."""
        found = set()
        for r in server.app.routes:
            if getattr(r, "path", "") == "/api/projects" and "POST" in r.methods:
                found = {d.call.__name__ for d in r.dependant.dependencies
                         if getattr(d, "call", None)}
        self.assertIn("require_approved", found)

    def test_the_stamp_itself_refuses_too(self):
        """Defence in depth AT the stamp, because that is where a future edit
        breaks it — and as a real 403, not an assert (python -O strips those
        and an AssertionError would surface as a 500)."""
        i = SERVER_SRC.index("async def create_project(")
        window = SERVER_SRC[i:i + 4000]
        j = window.index('project_dict["company_id"]')
        before = window[:j]
        self.assertIn("if not _company_id:", before,
                      "the stamp is not guarded at the point of stamping")
        self.assertIn("status_code=403", before)
        self.assertNotIn("assert _company_id", before,
                         "an assert is stripped by python -O")

    def test_stamp_is_no_longer_unconditional(self):
        """Scoped to create_project's BODY, not the whole file.

        require_company_access's docstring quotes the defective line verbatim
        to explain what it guards, so a whole-file search matches the
        explanation and passes for the wrong reason. (It also dumps 1.5MB into
        the failure message.) The body is the only place the assertion means
        anything.
        """
        i = SERVER_SRC.index("async def create_project(")
        body = SERVER_SRC[i:i + 4000]
        self.assertNotIn(
            'project_dict["company_id"] = admin.get("company_id")', body,
            "the unconditional stamp is the defect — it must not survive")


class WorkerCreationRefuses(unittest.TestCase):
    """2 — a mint that produced an unreachable row."""

    def test_route_carries_the_dependency(self):
        found = None
        for r in server.app.routes:
            if getattr(r, "path", "") == "/api/workers" and "POST" in r.methods:
                found = {d.call.__name__ for d in r.dependant.dependencies
                         if getattr(d, "call", None)}
        self.assertIsNotNone(found, "POST /api/workers vanished")
        self.assertIn("require_company_access", found)

    def test_stamp_is_unconditional_now(self):
        """Inverted from the project case ON PURPOSE. There the bug was an
        unconditional stamp of a possibly-None value; here it was a CONDITIONAL
        stamp that silently skipped. With the door guarded, stamping
        unconditionally is what makes an orphan impossible."""
        i = SERVER_SRC.index("async def create_worker(")
        window = SERVER_SRC[i:i + 2500]
        self.assertIn('worker_dict["company_id"] = company_id', window)
        self.assertNotIn('if company_id:\n        worker_dict["company_id"]',
                         window)


class RegisterEndpointIsGone(unittest.TestCase):
    """3 — public, unauthenticated, no caller in the repo's entire history."""

    def test_route_is_not_mounted(self):
        paths = {getattr(r, "path", "") for r in server.app.routes}
        self.assertNotIn("/api/workers/register", paths)

    def test_handler_is_deleted_not_just_unrouted(self):
        self.assertFalse(hasattr(server, "register_worker"),
                         "the handler still exists and could be re-decorated")
        self.assertNotIn("async def register_worker", SERVER_SRC)

    def test_the_gate_signup_path_is_untouched(self):
        """Worker self-registration at the gate is a DIFFERENT endpoint and is
        public by design. Deleting the wrong one would break every turnstile."""
        paths = {getattr(r, "path", "") for r in server.app.routes}
        self.assertIn("/api/checkin/register-and-checkin", paths)


class GateIsUntouched(unittest.TestCase):
    """THE NEVER-BLOCK RULE. The thing most likely to break here.

    A refusal anywhere on the check-in path is a worker turned away at a
    turnstile because an admin did not finish a form. These assertions exist so
    that cannot be introduced by someone extending this batch.
    """

    GATE_ROUTES = [
        "/api/checkin/register-and-checkin",
        "/api/checkin/submit",
        "/api/checkin/lookup-worker",
        "/api/checkin/{project_id}/{tag_id}/info",
        "/api/checkin/{project_id}/companies",
    ]

    def test_gate_routes_all_still_mounted(self):
        paths = {getattr(r, "path", "") for r in server.app.routes}
        for p in self.GATE_ROUTES:
            self.assertIn(p, paths, f"gate route disappeared: {p}")

    def test_no_gate_route_carries_the_company_gate(self):
        """require_company_access derives from the CALLER. The gate has no
        authenticated caller — the worker is anonymous — so this dependency
        there would refuse everyone, always."""
        for r in server.app.routes:
            path = getattr(r, "path", "")
            if path not in self.GATE_ROUTES:
                continue
            names = {d.call.__name__ for d in r.dependant.dependencies
                     if getattr(d, "call", None)}
            self.assertNotIn("require_company_access", names,
                             f"{path} would refuse an anonymous worker")
            self.assertNotIn("require_approved", names, f"{path}")

    def test_register_and_checkin_takes_no_auth_dependency(self):
        """Public by design. If it ever acquires one, a man at the gate is
        blocked by an account state he does not have."""
        for r in server.app.routes:
            if getattr(r, "path", "") != "/api/checkin/register-and-checkin":
                continue
            names = {d.call.__name__ for d in r.dependant.dependencies
                     if getattr(d, "call", None)}
            self.assertEqual(
                names & {"get_current_user", "get_admin_user",
                         "require_company_access", "require_approved"},
                set(), f"gate acquired an auth dependency: {sorted(names)}")

    def test_gate_still_derives_company_from_the_project(self):
        """Not from the caller, and not refused when falsy. A legacy project
        with company_id None must still admit the worker — the row is fixed by
        correcting the PROJECT, never by turning the man away."""
        for fn in ("register_and_checkin", "submit_checkin"):
            i = SERVER_SRC.index(f"async def {fn}(")
            end = SERVER_SRC.index("db.checkins.insert_one", i)
            window = SERVER_SRC[i:end]
            self.assertIn('company_id = project.get("company_id")', window,
                          f"{fn} no longer derives company from the project")
            self.assertNotIn("require_company_access", window,
                             f"{fn} acquired the caller-scoped refusal")

    def test_no_new_raise_between_gate_entry_and_the_checkin_insert(self):
        """Pins the REFUSAL COUNT on each gate path.

        A count, not a shape, because the failure mode is someone adding one
        more `raise HTTPException` while tightening tenancy. The existing ones
        are documented input/roster errors; the number going UP is the signal
        worth failing on. If a change legitimately adds or removes one, update
        the number here deliberately and say why in the diff.
        """
        expected = {"register_and_checkin": 5, "submit_checkin": 6}
        tree = ast.parse(SERVER_SRC)
        actual = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in expected:
                actual[node.name] = sum(
                    1 for n in ast.walk(node)
                    if isinstance(n, ast.Raise)
                )
        self.assertEqual(actual, expected,
                         "a refusal was added or removed on a gate path — if "
                         "deliberate, update this pin and justify it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
