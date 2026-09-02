"""THE FLOOR CAN NOW REFUSE — AND WHEN IT IS UNSET IT REFUSES NOTHING.

test_client_version_floor.py pins the value: it is None, and it is not read
across the deploy boundary. This file pins what the value DOES. Until now the
answer was "nothing" — `client_minimum_supported` was reported by /api/version
and rendered as 9pt grey text by two screens, and no request was ever judged
against it. A device on a native build that receives no OTA at all could talk
to a current API indefinitely and the API could not tell.

THE ONE PROPERTY THAT MATTERS MORE THAN THE FEATURE ITSELF: fail open.

This is a compliance app. A CP standing on a jobsite files his day through it.
A floor that is unset, blank, misspelled, set to "latest", set to "v1.3.0", or
set to anything this code cannot parse must let EVERY device through — because
the alternative is a one-character typo in a Railway environment variable
locking every phone in the field out of the product simultaneously, with no
client-side way to recover and no one on site able to do anything about it.
The mechanism is worth having only if it is incapable of that.

So the refusal is written as a single predicate that answers True in exactly
one case — the floor parses, the client's reported version parses, and the
second is below the first — and answers False for every other combination of
inputs there is. Everything below is that sentence, enumerated.

THE FLOOR IS AN ENVIRONMENT VARIABLE, not a file read. On 2026-08-29 deriving
it from frontend/app.json at module scope crash-looped production: the Railway
image contains /app/backend only. An env var is the same "baked in at image
build time" that the outage comment left open, without reaching across the
deploy boundary to get it.
"""

import ast
import inspect
import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

SRC = (BACKEND / "server.py").read_text(encoding="utf-8")


class _FakeRequest:
    """Only the one attribute the gate is allowed to touch."""

    def __init__(self, headers=None):
        self.headers = headers or {}


# ═══════════════════════════════════════════════════════════════════════════
# FAIL OPEN. Read this class first; the feature is subordinate to it.
# ═══════════════════════════════════════════════════════════════════════════

class AMisconfiguredFloorLocksNobodyOut(unittest.TestCase):

    # Deliberately includes versions far below any floor anyone would set,
    # and the empty/None cases a device sends when it cannot say what it is.
    EVERY_KIND_OF_CLIENT = [
        "0.0.1", "0.9.9", "1.0.0", "1.2.0", "1.3.0", "1.3.0-rc1", "9.9.9",
        "", "   ", None, "garbage", "v1.2.0", "1.2.0.0.0",
    ]

    def test_an_unset_floor_refuses_nothing(self):
        """THE STATE THIS SHIPS IN. The mechanism is added and the system
        behaves exactly as it did before, for every client that exists."""
        for reported in self.EVERY_KIND_OF_CLIENT:
            with self.subTest(reported=reported):
                self.assertFalse(
                    server._client_is_below_floor(reported, None),
                    "an unset floor judged a client — a deploy that has not "
                    "configured a minimum must not refuse anyone")

    def test_a_blank_floor_refuses_nothing(self):
        """`CLIENT_MINIMUM_SUPPORTED=` in a Railway variable list, or a value
        someone cleared and left as whitespace."""
        for floor in ["", "   ", "\t", "\n"]:
            for reported in self.EVERY_KIND_OF_CLIENT:
                with self.subTest(floor=repr(floor), reported=reported):
                    self.assertFalse(
                        server._client_is_below_floor(reported, floor))

    def test_an_UNPARSEABLE_floor_refuses_nothing(self):
        """THE TYPO CASE, and the reason this is a test and not a comment.

        Every one of these is a plausible thing for a human to type into a
        deploy console. Not one of them may be read as "a floor above
        everything", which is what a naive string comparison would do — under
        `"1.3.0" < "latest"` every install in the field is below the floor.
        """
        for floor in [
            "latest",           # a word, not a version
            "v1.3.0",           # the tag name, with the v
            "1.3.x",            # a wildcard
            "1.3.0 beta",       # trailing words, which a build suffix is not
            "one.three.zero",
            "current",
            "true",             # someone treated it as a feature toggle
            "-1",
            "1.2.3.4.5",        # too many parts to be a version
            "..",
        ]:
            for reported in self.EVERY_KIND_OF_CLIENT:
                with self.subTest(floor=floor, reported=reported):
                    self.assertFalse(
                        server._client_is_below_floor(reported, floor),
                        f"floor {floor!r} refused client {reported!r}; an "
                        f"unparseable floor must be treated as no floor")

    def test_a_client_that_reports_nothing_is_not_refused(self):
        """A web build, a curl, an integration, an install predating the
        X-Client-Version header. We cannot judge it, so we do not."""
        for reported in [None, "", "   ", "\t"]:
            with self.subTest(reported=reported):
                self.assertFalse(
                    server._client_is_below_floor(reported, "1.3.0"))

    def test_an_unparseable_client_version_is_not_refused(self):
        """Symmetric to the floor: an install we cannot assess is not accused.
        Same rule frontend/src/utils/clientVersion.js already states."""
        for reported in ["garbage", "v1.2.0", "1.2.x", "1.2.3.4.5", "?"]:
            with self.subTest(reported=reported):
                self.assertFalse(
                    server._client_is_below_floor(reported, "1.3.0"))


# ═══════════════════════════════════════════════════════════════════════════
# And when it IS set, it works.
# ═══════════════════════════════════════════════════════════════════════════

class AConfiguredFloorRefusesTheStrandedInstall(unittest.TestCase):

    def test_below_the_floor_is_refused(self):
        for reported in ["1.2.0", "1.2.9", "0.9.9", "1.2"]:
            with self.subTest(reported=reported):
                self.assertTrue(
                    server._client_is_below_floor(reported, "1.3.0"))

    def test_at_the_floor_is_not_below_it(self):
        self.assertFalse(server._client_is_below_floor("1.3.0", "1.3.0"))

    def test_ahead_of_the_floor_is_not_below_it(self):
        for reported in ["1.3.1", "1.4.0", "2.0.0", "1.10.0"]:
            with self.subTest(reported=reported):
                self.assertFalse(
                    server._client_is_below_floor(reported, "1.3.0"))

    def test_a_build_suffix_is_not_a_version_bump(self):
        """A release-channel build of the floor version is AT the floor. The
        frontend already rules this way; a server that ruled the other way
        would refuse the exact build QA is holding."""
        self.assertFalse(server._client_is_below_floor("1.3.0-rc1", "1.3.0"))
        self.assertFalse(server._client_is_below_floor("1.3.0+42", "1.3.0"))

    def test_the_comparison_is_numeric_not_lexicographic(self):
        """`"1.10.0" < "1.9.0"` as strings. That is the whole bug class, and
        it refuses the NEWEST installs while letting old ones through."""
        self.assertFalse(server._client_is_below_floor("1.10.0", "1.9.0"))
        self.assertTrue(server._client_is_below_floor("1.9.0", "1.10.0"))

    def test_a_short_version_is_zero_filled(self):
        self.assertFalse(server._client_is_below_floor("1.3", "1.3.0"))


class TheParserAgreesWithTheFrontendOne(unittest.TestCase):
    """Two implementations of one rule. If they disagree, a device is told it
    is fine by the strip on its own screen and refused by the API, or the
    reverse — and the person debugging that has no reason to suspect two
    parsers. Mirrors frontend/src/utils/clientVersion.js::parseVersion.
    """

    def test_it_parses_what_the_frontend_parses(self):
        for text, expected in [
            ("1.3.0", (1, 3, 0)),
            ("1.3", (1, 3, 0)),
            ("1.3.0-rc1", (1, 3, 0)),
            ("1.3.0+42", (1, 3, 0)),
            ("1.2.3.4", (1, 2, 3, 4)),
            (" 1.3.0 ", (1, 3, 0)),
        ]:
            with self.subTest(text=text):
                self.assertEqual(server._parse_client_version(text), expected)

    def test_it_rejects_what_the_frontend_rejects(self):
        for text in ["", "   ", None, "garbage", "v1.3.0", "1.3.x",
                     "1.2.3.4.5", "..", 130, 1.3]:
            with self.subTest(text=text):
                self.assertIsNone(server._parse_client_version(text))


# ═══════════════════════════════════════════════════════════════════════════
# The gate: where the predicate is applied, and what it returns.
# ═══════════════════════════════════════════════════════════════════════════

class TheGateRefusesWithAnAnswerableStatus(unittest.TestCase):

    def setUp(self):
        self._saved = server.CLIENT_MINIMUM_SUPPORTED

    def tearDown(self):
        server.CLIENT_MINIMUM_SUPPORTED = self._saved

    def test_the_gate_is_silent_when_the_floor_is_unset(self):
        """THE SHIPPED STATE, asserted at the gate and not only at the
        predicate — a fail-open predicate wired into a gate that raises before
        consulting it fails open in theory only."""
        server.CLIENT_MINIMUM_SUPPORTED = None
        for v in ["0.0.1", "1.2.0", "garbage", ""]:
            with self.subTest(v=v):
                # Returns rather than raises. No assertion needed beyond the
                # absence of an exception, which is the whole claim.
                server._enforce_client_version_floor(
                    _FakeRequest({"x-client-version": v}))

    def test_the_gate_is_silent_when_there_is_no_request_at_all(self):
        """get_current_user's `request` parameter is Optional and is None on
        the token= call path. A gate that raised on that would refuse every
        such caller the moment a floor was set."""
        server.CLIENT_MINIMUM_SUPPORTED = "1.3.0"
        server._enforce_client_version_floor(None)

    def test_the_gate_raises_426_for_a_stranded_install(self):
        server.CLIENT_MINIMUM_SUPPORTED = "1.3.0"
        with self.assertRaises(server.HTTPException) as caught:
            server._enforce_client_version_floor(
                _FakeRequest({"x-client-version": "1.2.0"}))
        self.assertEqual(caught.exception.status_code, 426,
                         "426 Upgrade Required — a status the client can "
                         "branch on. 401 would log the user out and 403 "
                         "reads as a permissions problem; both send the "
                         "person holding the phone down the wrong path.")

    def test_the_refusal_names_the_floor_and_what_was_reported(self):
        """A 426 with an opaque body is one more mystery error. The body has
        to be enough for the client to render a sentence and for a support
        thread to end in one message."""
        server.CLIENT_MINIMUM_SUPPORTED = "1.3.0"
        with self.assertRaises(server.HTTPException) as caught:
            server._enforce_client_version_floor(
                _FakeRequest({"x-client-version": "1.2.0"}))
        detail = caught.exception.detail
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail.get("error"), "client_update_required")
        self.assertEqual(detail.get("minimum_supported"), "1.3.0")
        self.assertEqual(detail.get("reported"), "1.2.0")

    def test_the_gate_lets_a_current_install_through(self):
        server.CLIENT_MINIMUM_SUPPORTED = "1.3.0"
        server._enforce_client_version_floor(
            _FakeRequest({"x-client-version": "1.3.0"}))

    def test_a_header_longer_than_the_field_cannot_be_used_to_smuggle(self):
        """The stamp already truncates to 32; the gate reads the same header
        and must not diverge into parsing an unbounded string."""
        server.CLIENT_MINIMUM_SUPPORTED = "1.3.0"
        server._enforce_client_version_floor(
            _FakeRequest({"x-client-version": "1" * 500}))


class TheGateIsWiredIntoTheAuthPath(unittest.TestCase):

    def test_get_current_user_calls_it(self):
        """The single authenticated choke point. Wiring it as middleware
        instead would also catch /api/version and /api/auth/login — the two
        endpoints a refused client needs in order to LEARN it was refused and
        to recover."""
        body = inspect.getsource(server.get_current_user)
        self.assertIn("_enforce_client_version_floor(", body)

    def test_it_is_not_registered_as_middleware(self):
        """Enforced globally, a refused device could not reach /api/version to
        read the floor, could not log in, and would see only opaque failures —
        the exact cascade this is meant to replace."""
        for node in ast.walk(ast.parse(SRC)):
            if isinstance(node, ast.Call):
                called = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                if called.endswith("add_middleware") or called.endswith("middleware"):
                    rendered = ast.unparse(node)
                    self.assertNotIn(
                        "_enforce_client_version_floor(", rendered,
                        "the floor gate is registered as middleware; it must "
                        "run inside get_current_user only")

    def test_version_stays_reachable_without_authentication(self):
        """It is how a refused client discovers WHY. Re-asserted here because
        the enforcement above is what makes it load-bearing rather than
        merely tidy."""
        route = next(r for r in server.app.routes
                     if getattr(r, "path", "") == "/api/version")
        names = [getattr(d.call, "__name__", "")
                 for d in route.dependant.dependencies]
        self.assertNotIn("get_current_user", names)


class ItReachesTheWire(unittest.TestCase):
    """The classes above test the predicate and the gate as functions. This
    one puts a real request through the real app, because "raises
    HTTPException" and "the client receives 426 with a body it can read" are
    different claims and only the second one matters to the phone.

    NO DATABASE IS TOUCHED: the bearer token is deliberately junk, so a
    request that gets past the gate dies at the JWT decode. The two outcomes
    are therefore 426 (gate fired) and 401 (gate did not), which is exactly
    the distinction under test — and it also proves the gate runs BEFORE the
    token work, so a stranded install is told why instead of being handed a
    401 it cannot act on.
    """

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        cls.client = TestClient(server.app)
        # An endpoint that depends on get_current_user and nothing else.
        cls.path = "/api/users/me/onboarding-status"

    def setUp(self):
        self._saved = server.CLIENT_MINIMUM_SUPPORTED

    def tearDown(self):
        server.CLIENT_MINIMUM_SUPPORTED = self._saved

    def _get(self, version):
        headers = {"Authorization": "Bearer not-a-real-token"}
        if version is not None:
            headers["X-Client-Version"] = version
        return self.client.get(self.path, headers=headers)

    def test_an_old_client_is_refused_with_426_when_a_floor_is_set(self):
        server.CLIENT_MINIMUM_SUPPORTED = "1.3.0"
        r = self._get("1.2.0")
        self.assertEqual(r.status_code, 426)
        detail = r.json()["detail"]
        self.assertEqual(detail["error"], "client_update_required")
        self.assertEqual(detail["minimum_supported"], "1.3.0")
        self.assertEqual(detail["reported"], "1.2.0")

    def test_the_refusal_carries_the_floor_as_a_header_too(self):
        """For a client that cannot parse the body — a proxy rewrote it, an
        older build, a curl in a support thread."""
        server.CLIENT_MINIMUM_SUPPORTED = "1.3.0"
        r = self._get("1.2.0")
        self.assertEqual(r.headers.get("x-minimum-client-version"), "1.3.0")

    def test_a_current_client_is_not_refused(self):
        server.CLIENT_MINIMUM_SUPPORTED = "1.3.0"
        self.assertEqual(self._get("1.3.0").status_code, 401)

    def test_WITH_NO_FLOOR_NOTHING_CHANGES(self):
        """THE STATE THIS SHIPS IN, end to end. Every one of these reaches the
        auth path exactly as it did before this change existed."""
        server.CLIENT_MINIMUM_SUPPORTED = None
        for v in ["0.0.1", "1.2.0", "1.3.0", "garbage", "", None]:
            with self.subTest(version=v):
                self.assertEqual(
                    self._get(v).status_code, 401,
                    "an unconfigured floor changed the response")

    def test_a_typo_in_the_floor_does_not_lock_the_field_out(self):
        """The whole point, at the outermost layer: someone types the release
        tag instead of the version into a deploy variable and every phone on
        every jobsite keeps working."""
        for floor in ["latest", "v1.3.0", "1.3.x", "true", ""]:
            with self.subTest(floor=floor):
                server.CLIENT_MINIMUM_SUPPORTED = floor
                self.assertEqual(
                    self._get("1.0.0").status_code, 401,
                    f"floor {floor!r} refused a client over the wire")

    def test_version_is_answered_even_to_a_refused_client(self):
        """How the phone learns what it needs. If the gate ever became global
        this would 426 too, and the refused device would have no way to find
        out anything at all."""
        server.CLIENT_MINIMUM_SUPPORTED = "1.3.0"
        r = self.client.get("/api/version", headers={"X-Client-Version": "1.0.0"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["client_minimum_supported"], "1.3.0")


class TheFloorIsConfiguredNotCompiledIn(unittest.TestCase):

    def test_it_comes_from_the_environment(self):
        """Not a literal in source: raising the floor must be a deploy
        variable change, not a code change that has to be written, reviewed,
        merged and rolled out while stranded phones are in the field."""
        self.assertIn('os.environ.get("CLIENT_MINIMUM_SUPPORTED"', SRC)

    def test_it_is_still_unset_in_this_tree(self):
        """THIS CHANGE SHIPS THE MECHANISM, NOT A VALUE. Setting a floor is a
        separate, deliberate act with a rollout behind it."""
        self.assertIsNone(server.CLIENT_MINIMUM_SUPPORTED)

    def test_no_default_value_is_baked_into_the_call(self):
        """`os.environ.get("CLIENT_MINIMUM_SUPPORTED", "1.3.0")` would ship a
        live floor to every deploy that never set the variable — every
        existing one — which is precisely the lockout this file exists to
        prevent, arriving by default."""
        for node in ast.walk(ast.parse(SRC)):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"):
                continue
            if not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant)
                    and first.value == "CLIENT_MINIMUM_SUPPORTED"):
                continue
            for extra in node.args[1:]:
                self.assertTrue(
                    isinstance(extra, ast.Constant) and extra.value in ("", None),
                    f"a non-empty default floor is compiled in at line "
                    f"{node.lineno}")


if __name__ == "__main__":
    unittest.main()
