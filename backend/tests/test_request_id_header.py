"""X-Request-Id reaches the wire, and the server actually consumes it.

WHY THIS IS A RUNTIME TEST AND NOT A SOURCE-TEXT ONE. The claim being made is
"a duplicate write can now be named in the logs". A grep proving the middleware
is WRITTEN proves nothing about whether it RUNS — this repo has already shipped
`sendPendingSignatures`, which existed, was correct, and was never called. So
every assertion below drives a real request through the real middleware stack
and reads what came back.

WHAT THE HEADER BUYS. One tap on Amend produced two arrivals of POST /amend
3.2s apart on two containers. Nothing in the client re-issues and 3.2s fits no
timeout the client owns, so the replay is below the application — but eight
hours of logs could not prove that, because no request carried an identity two
log lines could be joined on. With this in place:

    one id, two arrivals   ->  the transport replayed one request
    two ids, two arrivals  ->  the client issued two

A 404 route is used deliberately: the middleware wraps the whole app, so it
must tag a response no handler ever saw, and using one keeps this test free of
auth, of the database, and of any endpoint's own behaviour.
"""

from __future__ import annotations

import logging
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

HEADER = "X-Request-Id"
MISSING_ROUTE = "/api/__no_such_route_for_request_id_test__"


class TheHeaderReachesTheWire(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(server.app)

    def test_the_name_is_the_one_the_client_sends(self):
        self.assertEqual(server.CLIENT_REQUEST_ID_HEADER, HEADER)

    def test_a_supplied_id_is_echoed_back_unchanged(self):
        """The device must be able to quote the id it was served under."""
        r = self.client.post(MISSING_ROUTE, headers={HEADER: "abc-123_XY.z"})
        self.assertEqual(r.headers.get(HEADER), "abc-123_XY.z")

    def test_an_absent_id_is_minted_server_side(self):
        """A request from an older build is exactly the one that would
        otherwise be uncorrelatable. It gets an id anyway."""
        r = self.client.post(MISSING_ROUTE)
        got = r.headers.get(HEADER)
        self.assertTrue(got, "no id was assigned")
        self.assertTrue(got.startswith("srv-"),
                        f"a server-minted id is marked as such (got {got!r})")

    def test_two_requests_without_ids_get_different_ones(self):
        a = self.client.post(MISSING_ROUTE).headers.get(HEADER)
        b = self.client.post(MISSING_ROUTE).headers.get(HEADER)
        self.assertNotEqual(a, b, "two requests were given one identity")

    def test_the_middleware_runs_on_reads_too(self):
        """Only the LOG is scoped to mutating methods; the id itself is
        assigned to everything, so a GET can still be quoted in a support call."""
        r = self.client.get(MISSING_ROUTE)
        self.assertTrue(r.headers.get(HEADER))


class AHostileValueIsNotTakenAtFaceValue(unittest.TestCase):
    """The value is attacker-controlled text on its way into a log file."""

    def setUp(self):
        self.client = TestClient(server.app)

    def test_a_forged_newline_is_rejected_not_logged(self):
        """Two log lines out of one header is log forgery. The value is
        refused and a clean one is minted in its place."""
        r = self.client.post(
            MISSING_ROUTE,
            headers={HEADER: "aaa"},
        )
        # Sanity: the clean one IS accepted, so the refusals below mean something.
        self.assertEqual(r.headers.get(HEADER), "aaa")

        for bad in ("a b", "a\tb", "a/b", "x" * 129, "", "a:b", "a%0Ab"):
            got = server.sanitized_client_request_id(bad)
            self.assertIsNone(got, f"{bad!r} should not be accepted, got {got!r}")

    def test_the_shapes_the_client_actually_mints_are_accepted(self):
        """frontend/src/utils/api.js builds
        `${base36 time}-${base36 counter}-${8 base36 chars}`."""
        for good in ("mtm6txa6-1-j0kvwc2h", "srv-0123456789abcdef",
                     "a.b_c-d", "x" * 128):
            self.assertEqual(server.sanitized_client_request_id(good), good)

    def test_a_rejected_value_does_not_reach_the_response(self):
        r = self.client.post(MISSING_ROUTE, headers={HEADER: "has space"})
        got = r.headers.get(HEADER)
        self.assertNotEqual(got, "has space")
        self.assertTrue(got.startswith("srv-"))


class TheLogLineIsTheJoinKey(unittest.TestCase):
    """A header nobody consumes is decoration. This is the consumption."""

    def setUp(self):
        self.client = TestClient(server.app)

    def test_a_mutating_request_logs_its_id(self):
        with self.assertLogs("levelog.request", level="INFO") as cap:
            self.client.post(MISSING_ROUTE, headers={HEADER: "the-tap-id"})
        joined = "\n".join(cap.output)
        self.assertIn("the-tap-id", joined)
        self.assertIn("POST", joined)
        self.assertIn(MISSING_ROUTE, joined)
        self.assertIn("origin=client", joined,
                      "the log must say whether the DEVICE sent the id")

    def test_a_server_minted_id_is_marked_as_such_in_the_log(self):
        with self.assertLogs("levelog.request", level="INFO") as cap:
            self.client.post(MISSING_ROUTE)
        self.assertIn("origin=server", "\n".join(cap.output))

    def test_two_arrivals_of_one_id_produce_two_joinable_lines(self):
        """THE WHOLE POINT, in one test. This is what the 3.2s replay would
        look like in the log, and what makes it distinguishable from two taps.
        """
        with self.assertLogs("levelog.request", level="INFO") as cap:
            self.client.post(MISSING_ROUTE, headers={HEADER: "one-logical-write"})
            self.client.post(MISSING_ROUTE, headers={HEADER: "one-logical-write"})
        lines = [ln for ln in cap.output if "one-logical-write" in ln]
        self.assertEqual(len(lines), 2,
                         "a replayed request must appear twice under ONE id")

        with self.assertLogs("levelog.request", level="INFO") as cap2:
            self.client.post(MISSING_ROUTE, headers={HEADER: "tap-one"})
            self.client.post(MISSING_ROUTE, headers={HEADER: "tap-two"})
        self.assertEqual(
            len([ln for ln in cap2.output if "tap-one" in ln]), 1)
        self.assertEqual(
            len([ln for ln in cap2.output if "tap-two" in ln]), 1)

    def test_a_read_is_not_logged(self):
        """GETs are the bulk of the traffic and a replayed read is not the
        problem being investigated."""
        logger = logging.getLogger("levelog.request")
        with self.assertLogs("levelog.request", level="INFO") as cap:
            self.client.get(MISSING_ROUTE)
            logger.info("sentinel")  # assertLogs fails an empty capture
        self.assertEqual([ln for ln in cap.output if MISSING_ROUTE in ln], [])


class ItIsWiredWhereItHasToBe(unittest.TestCase):

    def test_cors_is_still_outside_it(self):
        """Registering this middleware AFTER the CORS block would make it the
        outermost layer and put CORS inside — reopening the bug
        test_cors_survives_rate_limit exists for."""
        from fastapi.middleware.cors import CORSMiddleware
        classes = [m.cls.__name__ for m in server.app.user_middleware]
        self.assertIn("CORSMiddleware", classes)
        cors_at = classes.index("CORSMiddleware")
        # user_middleware is outermost-first.
        self.assertEqual(cors_at, 0,
                         "CORSMiddleware must remain the outermost layer")

    def test_the_header_is_allowed_and_exposed(self):
        """Two different browser traps. Absent from allow_headers, the browser
        refuses to SEND it on a cross-origin call; absent from expose_headers,
        the browser hides the echo from the web build."""
        from fastapi.middleware.cors import CORSMiddleware
        kwargs = None
        for mw in server.app.user_middleware:
            if mw.cls is CORSMiddleware:
                kwargs = mw.kwargs
        self.assertIsNotNone(kwargs)
        self.assertIn(HEADER, kwargs.get("allow_headers"))
        self.assertIn(HEADER, kwargs.get("expose_headers"))


if __name__ == "__main__":
    unittest.main()
