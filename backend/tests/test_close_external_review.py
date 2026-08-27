"""The last two review items: /auth/me's shape, and PDF rendering off the loop.

1. GET /auth/me returned dict(current_user) with ONE key deleted by name. The
   password hash never reached the client -- the field is `password` at every
   writer and the deletion covers both principal shapes -- so the reported
   finding was false. The REAL risk is the second secret: anything else stored
   on a user or device document would ship, with nothing to stop it.

   IT IS A DENYLIST, NOT response_model=UserResponse, and that is a considered
   refusal. /auth/me serves TWO shapes, and a site device has NO email and NO
   name -- UserResponse requires both, so the model would 500 every site device
   on boot, and silently strip site_mode / project_id / project_name /
   onboarding_step / full_name for the users it did not 500. AuthContext calls
   this endpoint on every session start and branches on site_mode.

   That is the WorkerResponse incident: a model demanding a field the writers
   never record, turning a working read into an unhandled 500.

2. Three on-demand PDF endpoints called weasyprint INLINE on the event loop.
   The scheduled path already offloads and says why -- "doing it inline would
   stall the once-a-minute scheduler for every other project due this tick" --
   and these three were what it did not cover.

    python backend/tests/test_close_external_review.py
"""

import ast
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402

SRC = (BACKEND / "server.py").read_text(encoding="utf-8-sig")
TREE = ast.parse(SRC)

USER = {
    "id": "u1", "email": "cp@example.com", "name": "Casey", "role": "cp",
    "company_id": "companyA", "company_name": "Vanguard",
    "full_name": "Casey Park", "first_name": "Casey", "display_name": "Casey P",
    "onboarding_step": "2", "assigned_projects": ["projA"],
    "account_status": "approved", "phone": "5551234567",
    "password": "$2b$12$hashedhashedhashed",
}
# NO email, NO name. This is what get_current_user's site_mode branch returns.
DEVICE = {
    "id": "d1", "role": "site_device", "site_mode": True,
    "project_id": "projA", "project_name": "588 Thomas",
    "project": {"id": "projA"}, "device_name": "North Gate",
    "username": "gate-a", "company_id": "companyA",
    "password": "$2b$12$devicehash",
}


def _me(principal):
    return asyncio.run(server.get_me(current_user=principal))


class TheHashNeverLeaves(unittest.TestCase):

    def test_a_users_password_is_removed(self):
        self.assertNotIn("password", _me(USER))

    def test_a_site_devices_password_is_removed(self):
        """Both principal shapes go through the same filter."""
        self.assertNotIn("password", _me(DEVICE))

    def test_the_input_is_not_mutated(self):
        """A dict comprehension, not a del on the caller's object.
        get_current_user's return is reused downstream in the same request."""
        principal = dict(USER)
        _me(principal)
        self.assertIn("password", principal)


class TheSECONDSecretIsCoveredToo(unittest.TestCase):
    """The real finding. The old code deleted ONE key by name, so anything else
    stored on a principal would have shipped."""

    def test_every_denylisted_field_is_stripped(self):
        loaded = {**USER, **{k: "SECRET" for k in server._PRINCIPAL_PRIVATE_FIELDS}}
        out = _me(loaded)
        for field in server._PRINCIPAL_PRIVATE_FIELDS:
            with self.subTest(field=field):
                self.assertNotIn(field, out)

    def test_the_denylist_names_the_obvious_suspects(self):
        for field in ("password", "reset_token", "refresh_token", "mfa_secret",
                      "api_key", "client_secret"):
            self.assertIn(field, server._PRINCIPAL_PRIVATE_FIELDS, field)

    def test_it_is_immutable(self):
        """A module-level set a request handler could mutate is a way to turn
        the filter off at runtime."""
        self.assertIsInstance(server._PRINCIPAL_PRIVATE_FIELDS, frozenset)


class NothingTheCLIENTReadsIsStripped(unittest.TestCase):
    """WHY THIS IS NOT A RESPONSE MODEL. AuthContext calls /auth/me on every
    session start; anything dropped here breaks a boot path."""

    def test_a_user_keeps_every_field_the_app_reads(self):
        out = _me(USER)
        for field in ("id", "email", "name", "role", "company_id", "company_name",
                      "full_name", "first_name", "display_name",
                      "onboarding_step", "assigned_projects", "account_status",
                      "phone"):
            with self.subTest(field=field):
                self.assertIn(field, out)

    def test_a_site_device_keeps_its_site_mode_fields(self):
        """UserResponse declares NONE of these, so a response model would strip
        them and site mode would never start."""
        out = _me(DEVICE)
        for field in ("site_mode", "project_id", "project_name", "project",
                      "device_name", "role"):
            with self.subTest(field=field):
                self.assertIn(field, out)

    def test_a_site_device_has_NO_email_or_name_to_give(self):
        """The fact that makes UserResponse impossible here: it requires both."""
        self.assertNotIn("email", DEVICE)
        self.assertNotIn("name", DEVICE)
        required = [n for n, f in server.UserResponse.model_fields.items()
                    if f.is_required()]
        self.assertIn("email", required)
        self.assertIn("name", required)

    def test_UserResponse_would_reject_a_site_device(self):
        """Stated as an executable fact rather than an argument. This is the
        500 the model would have produced on every gate tablet boot."""
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            server.UserResponse(**{k: v for k, v in DEVICE.items()
                                   if k != "password"})

    def test_the_route_carries_no_response_model(self):
        for r in server.app.routes:
            if getattr(r, "path", "") == "/api/auth/me" and "GET" in (r.methods or set()):
                self.assertIsNone(getattr(r, "response_model", None))
                return
        self.fail("/api/auth/me disappeared")

    def test_the_refusal_is_explained_in_the_source(self):
        """A future reader will try to add the model. The reason it is absent
        has to be where they look."""
        i = SRC.index("async def get_me(")
        body = SRC[i:i + 3000]
        self.assertIn("site device", body.lower())
        self.assertIn("UserResponse", body)


def _fn(name):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


OFFLOADED = ["export_logbook", "get_single_logbook_pdf", "get_combined_report_pdf"]


class PDFRenderingIsOffTheEventLoop(unittest.TestCase):

    def test_no_handler_calls_write_pdf_inline(self):
        """Read as CODE. The comments explain the change and name write_pdf, so
        a substring check would match the explanation."""
        for name in OFFLOADED:
            with self.subTest(fn=name):
                for node in ast.walk(_fn(name)):
                    if not isinstance(node, ast.Await):
                        continue
                # An inline call is a .write_pdf() that is NOT inside the
                # thread-offloaded helper.
                inline = []
                for node in ast.walk(_fn(name)):
                    if (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "write_pdf"):
                        inline.append(node.lineno)
                helper_lines = set()
                for node in ast.walk(_fn(name)):
                    if isinstance(node, ast.FunctionDef) and node.name == "_render_pdf":
                        helper_lines |= set(
                            range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1))
                stray = [ln for ln in inline if ln not in helper_lines]
                self.assertEqual(stray, [], f"{name}: write_pdf still on the loop")

    def test_each_awaits_asyncio_to_thread(self):
        for name in OFFLOADED:
            with self.subTest(fn=name):
                calls = [ast.unparse(n.func) for n in ast.walk(_fn(name))
                         if isinstance(n, ast.Call)]
                self.assertIn("asyncio.to_thread", calls)

    def test_each_handler_is_async(self):
        """`await` in a sync def is a SyntaxError, so this would not import --
        but naming it keeps the requirement visible if one is ever converted."""
        for name in OFFLOADED:
            with self.subTest(fn=name):
                self.assertIsInstance(_fn(name), ast.AsyncFunctionDef)

    def test_it_matches_the_scheduled_path(self):
        """The pattern was already correct in one place. These three now use
        the same shape rather than a second invention."""
        scheduled = SRC.index("doing it inline would stall")
        self.assertIn("asyncio.to_thread(_render_pdf", SRC[scheduled:scheduled + 900])

    def test_the_error_handling_is_unchanged(self):
        """asyncio.to_thread re-raises in the awaiting frame, so the existing
        try/except still catches a weasyprint failure. A 500 must stay a 500."""
        for name in OFFLOADED:
            with self.subTest(fn=name):
                handlers = [h for n in ast.walk(_fn(name))
                            if isinstance(n, ast.Try) for h in n.handlers]
                self.assertTrue(handlers, f"{name} lost its except block")

    def test_every_weasyprint_call_in_the_file_is_offloaded(self):
        """THE CLASS, not the three. A fourth inline render added later fails
        here."""
        offloaded_helpers = set()
        for node in ast.walk(TREE):
            if isinstance(node, ast.FunctionDef) and node.name in ("_render_pdf",
                                                                   "_default_pdf_renderer"):
                offloaded_helpers |= set(
                    range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1))
        stray = []
        for node in ast.walk(TREE):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "write_pdf"
                    and node.lineno not in offloaded_helpers):
                stray.append(node.lineno)
        self.assertEqual(stray, [], f"inline write_pdf at {stray}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
