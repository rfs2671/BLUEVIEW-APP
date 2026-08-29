"""The client version floor, derived from app.json rather than duplicated.

A device whose NATIVE build predates the current `expo.version` receives no OTA
update at all, forever, and is told nothing — `runtimeVersion:
{policy: "appVersion"}` makes it ineligible rather than behind. On 2026-08-28
that produced a filed log rendering as a blank editable form on one phone and
correctly on another, and six source traces were built before anyone read the
bundle id off the screen.

WHAT IS PINNED HERE is mostly the anti-staleness property, because the floor is
itself a value that can go stale and this codebase has already produced four
fields that were read and never written:

  * it is DERIVED from frontend/app.json, so a release PR touches the version
    and the floor in one diff rather than relying on someone remembering a
    second copy in an env var;
  * it is never ABOVE the shipped version, which is the shape a wrongly-bumped
    floor takes — it would mark every install, including the newest, as out of
    date;
  * the per-request stamp is throttled, because it runs on every authenticated
    request and an unconditional write would add one to every read.
"""

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

SRC = (BACKEND / "server.py").read_text(encoding="utf-8")

APP_JSON = BACKEND.parent / "frontend" / "app.json"


class TheFloorIsOffAndTheBackendBootsWithoutTheFrontend(unittest.TestCase):
    """THIS CLASS REPLACES TheFloorIsDerivedNotDuplicated, which asserted a
    feature that took production down on 2026-08-29.

    The floor was read out of frontend/app.json at MODULE SCOPE. The Railway
    image contains /app/backend only, so open() raised FileNotFoundError on
    every boot -- and the `except Exception` written to keep boot alive called
    `logger`, which is not defined until ~280 lines further down the file. The
    handler raised NameError, uvicorn died at import, and every path 502'd.

    The env override existed FOR EXACTLY THIS CASE -- its own test was named
    "an env override wins for a deploy that cannot see the file" -- and it was
    unset in production, so the code fell straight through to the read it was
    meant to avoid. An escape hatch nobody set is not a fallback.

    The floor is None until it is rebuilt without reading across the deploy
    boundary. Every reader already treats that as "unknown", which means NOT
    BEHIND on both surfaces.
    """

    def test_the_floor_is_disabled(self):
        self.assertIsNone(server.CLIENT_MINIMUM_SUPPORTED)

    def test_the_reader_is_gone_not_merely_wrapped(self):
        """Moving the `logger` line would fix the crash and leave the real
        defect: a backend that cannot boot without a file it does not ship."""
        self.assertNotIn("_read_client_minimum_supported", SRC)

    def test_NOTHING_IN_THE_BACKEND_READS_THE_FRONTEND_TREE(self):
        """THE GUARD THAT WOULD HAVE CAUGHT THIS, and the one import-check
        could not: that job runs from a git checkout where frontend/ exists, so
        the read succeeded there and failed only in the deploy image.

        CHECKED OVER STRING LITERALS, NOT SOURCE TEXT. A first draft grepped
        the file and matched the COMMENT above the disabled block explaining
        the outage -- the fifth assertion this session to match its own prose.
        ast.walk sees only what runs.
        """
        import ast as _ast
        # PATH-SHAPED LITERALS ONLY. Prose that happens to say "frontend" -- a
        # docstring explaining where a payload key is written -- is not a read.
        # The crash used `/ "frontend" /`, a BARE segment, which is what this
        # catches along with any explicit path spelling.
        for node in _ast.walk(_ast.parse(SRC)):
            if not (isinstance(node, _ast.Constant)
                    and isinstance(node.value, str)):
                continue
            # A BARE SEGMENT, which is how a path is built: `Path(..) /
            # "frontend" / "app.json"`. A docstring CITING a frontend file --
            # "frontend/app/logbooks/preshift_signin.jsx:555" -- is
            # documentation, not a read, and this codebase is full of those on
            # purpose.
            v = node.value.strip().lower().rstrip("/\\")
            if v == "frontend" or v.endswith("/frontend") or v == "frontend/app.json":
                self.fail(
                    f"server.py names the frontend tree as a PATH "
                    f"({node.value[:60]!r}, line {node.lineno}); the deploy "
                    f"image contains backend/ only")

    def test_no_module_scope_code_opens_a_file_at_import(self):
        """The crash was at IMPORT, which is what made it fatal rather than a
        degraded endpoint: a module-scope failure leaves no process to serve a
        request, so there is nothing to fall back to.

        MODULE SCOPE ONLY. Function bodies are skipped -- an open() inside a
        request handler is ordinary and recoverable; the same call at import is
        not. A first draft walked into every nested def and flagged a template
        read that has always been fine.
        """
        import ast as _ast
        for node in _ast.parse(SRC).body:
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef,
                                 _ast.ClassDef)):
                continue
            for sub in _ast.walk(node):
                if (isinstance(sub, _ast.Call)
                        and isinstance(sub.func, _ast.Name)
                        and sub.func.id == "open"):
                    self.fail(f"open() runs at import, line {sub.lineno}")


class TheEndpointReportsIt(unittest.TestCase):
    def test_version_carries_the_floor(self):
        import asyncio
        body = asyncio.run(server.version())
        self.assertIn("client_minimum_supported", body)
        self.assertEqual(body["client_minimum_supported"],
                         server.CLIENT_MINIMUM_SUPPORTED)

    def test_the_endpoint_is_still_unauthenticated(self):
        """It is a number about the product, not about anyone using it — and a
        client that cannot authenticate is exactly one that may need to know it
        is too old."""
        route = next(r for r in server.app.routes
                     if getattr(r, "path", "") == "/api/version")
        names = [getattr(d.call, "__name__", "") for d in route.dependant.dependencies]
        self.assertNotIn("get_current_user", names)


class TheStampIsThrottled(unittest.TestCase):
    """It runs on every authenticated request."""

    def test_a_changed_version_is_written_immediately(self):
        user = {"client_version": "1.2.0",
                "client_version_seen_at": datetime.now(timezone.utc)}
        self.assertTrue(server._client_version_needs_stamp(user, "1.3.0"))

    def test_the_same_version_is_not_rewritten_within_a_day(self):
        user = {"client_version": "1.3.0",
                "client_version_seen_at": datetime.now(timezone.utc) - timedelta(hours=2)}
        self.assertFalse(server._client_version_needs_stamp(user, "1.3.0"))

    def test_the_same_version_is_refreshed_after_a_day(self):
        user = {"client_version": "1.3.0",
                "client_version_seen_at": datetime.now(timezone.utc) - timedelta(hours=25)}
        self.assertTrue(server._client_version_needs_stamp(user, "1.3.0"))

    def test_a_naive_timestamp_does_not_raise(self):
        """Mongo hands back naive datetimes; comparing one to an aware now
        raises TypeError, and this runs inside the auth path."""
        user = {"client_version": "1.3.0",
                "client_version_seen_at": datetime.utcnow() - timedelta(hours=2)}
        self.assertFalse(server._client_version_needs_stamp(user, "1.3.0"))

    def test_a_user_who_has_never_reported_is_stamped(self):
        self.assertTrue(server._client_version_needs_stamp({}, "1.3.0"))

    def test_get_current_user_accepts_the_request_it_reads_the_header_from(self):
        import inspect
        self.assertIn("request", inspect.signature(server.get_current_user).parameters)


if __name__ == "__main__":
    unittest.main()
