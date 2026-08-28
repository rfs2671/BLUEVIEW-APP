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

APP_JSON = BACKEND.parent / "frontend" / "app.json"


class TheFloorIsDerivedNotDuplicated(unittest.TestCase):
    def setUp(self):
        self.expo = json.loads(APP_JSON.read_text(encoding="utf-8"))["expo"]

    def test_it_matches_what_app_json_declares(self):
        self.assertEqual(
            server.CLIENT_MINIMUM_SUPPORTED,
            self.expo["extra"]["minimumSupportedVersion"],
            "the server carries its own copy instead of reading the declaration",
        )

    def test_the_floor_is_not_above_the_shipped_version(self):
        """A floor above the version being shipped marks EVERY install as out
        of date, including the newest one. That is the shape a wrongly-bumped
        floor takes, and it is the one that destroys the signal."""
        def parts(v):
            return [int(p) for p in str(v).split("-")[0].split(".")]
        self.assertLessEqual(
            parts(server.CLIENT_MINIMUM_SUPPORTED), parts(self.expo["version"]),
            f"floor {server.CLIENT_MINIMUM_SUPPORTED} > shipped {self.expo['version']}",
        )

    def test_an_env_override_wins_for_a_deploy_that_cannot_see_the_file(self):
        os.environ["CLIENT_MINIMUM_SUPPORTED"] = "9.9.9"
        try:
            self.assertEqual(server._read_client_minimum_supported(), "9.9.9")
        finally:
            del os.environ["CLIENT_MINIMUM_SUPPORTED"]

    def test_an_unreadable_declaration_is_None_not_a_guess(self):
        """Null reaches the client as "do not judge". A guessed floor would
        accuse installs nobody has assessed."""
        import builtins
        real_open = builtins.open

        def _boom(*a, **k):
            if "app.json" in str(a[0]):
                raise OSError("no such file")
            return real_open(*a, **k)

        builtins.open = _boom
        try:
            self.assertIsNone(server._read_client_minimum_supported())
        finally:
            builtins.open = real_open

    def test_the_bump_rule_is_written_down_where_the_value_is_read(self):
        """app.json is JSON and cannot carry a comment, so the rule lives here.
        A floor nobody knows when to bump is a floor that goes stale."""
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        block = src[src.index("THE BUMP RULE"):src.index("def _read_client_minimum_supported")]
        for required in ("WHO:", "WHEN:", "TO WHAT:", "WHY NOT:"):
            self.assertIn(required, block)
        self.assertIn("native", block.lower())


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
