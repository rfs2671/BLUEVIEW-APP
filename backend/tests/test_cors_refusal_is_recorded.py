"""A refused preflight is recorded, and the health payload names the header.

WHAT THIS IS FOR. Between 2026-08-28 and 2026-09-04 the web build asked to send
`X-Client-Version` on every request, this server answered `400 Disallowed CORS
headers`, and Chrome declined to send the request at all — every endpoint,
login included. Nothing recorded it. `/api/version` returned 200 the whole time
because the process was up; the suite was green because no test preflighted;
the mount smoke reported 37/37 clean because route interception deletes the
preflight before Chromium issues one.

THE REFUSAL HAPPENS IN THIS PROCESS. It needs no DSN, no client
instrumentation, no quota and no browser to observe — which makes it the
cheapest detector available and the one that would have gone red on day one.

WHAT IS ASSERTED, AND WHAT DELIBERATELY IS NOT. The recorder must never change
what the caller receives: a refusal still refuses, an allowed preflight still
passes, and the status codes are asserted on real responses through the real
middleware rather than by reading the subclass. The DECISION is Starlette's and
is not re-derived here; only the naming of which header was refused is ours.

Run:  python -m pytest backend/tests/test_cors_refusal_is_recorded.py
"""

from __future__ import annotations

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
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

OURS = "https://www.levelog.com"
NOT_OURS = "https://scanner.example"
PATH = "/api/auth/login"


class Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        server.CORS_PREFLIGHT_REJECTIONS.clear()
        # The alert write is fire-and-forget against Mongo. Replace it with a
        # recorder so the threshold and the dedupe can be asserted without a
        # database, and so a test run never writes a compliance row.
        self.alerts = []
        self._real = server._flag_cors_preflight_refused

        async def _capture(header, origin, count):
            self.alerts.append((header, origin, count))

        server._flag_cors_preflight_refused = _capture

    def tearDown(self):
        server._flag_cors_preflight_refused = self._real
        server.CORS_PREFLIGHT_REJECTIONS.clear()

    def preflight(self, headers, origin=OURS, method="POST"):
        return self.client.options(PATH, headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        })


class TheRecorderDoesNotChangeTheAnswer(Base):
    """Observability that alters behaviour is not observability."""

    def test_an_allowed_preflight_still_passes_and_records_nothing(self):
        resp = self.preflight("content-type, authorization, x-client-version")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(server.CORS_PREFLIGHT_REJECTIONS, {})
        self.assertEqual(self.alerts, [])

    def test_a_refused_preflight_still_refuses(self):
        resp = self.preflight("content-type, x-not-allowed-anywhere")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Disallowed CORS", resp.text)


class ItNamesTheHeader(Base):
    """"a header was refused" is not actionable; the name is."""

    def test_the_refused_header_is_recorded_by_name(self):
        self.preflight("content-type, x-not-allowed-anywhere")
        self.assertIn("x-not-allowed-anywhere", server.CORS_PREFLIGHT_REJECTIONS)
        row = server.CORS_PREFLIGHT_REJECTIONS["x-not-allowed-anywhere"]
        self.assertEqual(row["count"], 1)
        self.assertIn(OURS, row["origins"])

    def test_an_allowed_header_alongside_a_refused_one_is_not_blamed(self):
        self.preflight("content-type, authorization, x-not-allowed-anywhere")
        self.assertEqual(list(server.CORS_PREFLIGHT_REJECTIONS),
                         ["x-not-allowed-anywhere"])

    def test_the_outage_header_would_have_been_named(self):
        """The exact seven-day condition, with X-Client-Version taken off the
        list the middleware is holding."""
        cors = [m for m in server.app.user_middleware
                if isinstance(m.cls, type) and issubclass(m.cls, CORSMiddleware)]
        self.assertEqual(len(cors), 1)
        # Reach the LIVE middleware instance, not the registration kwargs — the
        # thing that refuses is the built stack.
        inst = self._live_cors_instance()
        original = list(inst.allow_headers)
        try:
            inst.allow_headers = [h for h in original if h != "x-client-version"]
            resp = self.preflight("content-type, x-client-version")
            self.assertEqual(resp.status_code, 400)
            self.assertIn("x-client-version", server.CORS_PREFLIGHT_REJECTIONS)
        finally:
            inst.allow_headers = original

    def _live_cors_instance(self):
        app = server.app.middleware_stack
        seen = 0
        while app is not None and seen < 50:
            if isinstance(app, CORSMiddleware):
                return app
            app = getattr(app, "app", None)
            seen += 1
        self.fail("no CORSMiddleware instance in the built stack")


class OnlyOurOwnOriginsRaiseAnAlert(Base):
    """A refused preflight from a host we do not own is a scanner. Counted so
    the health payload never hides it; never alerted, so it cannot page."""

    def test_a_foreign_origin_is_counted_but_never_alerts(self):
        for _ in range(server.CORS_PREFLIGHT_ALERT_THRESHOLD + 3):
            self.preflight("x-not-allowed-anywhere", origin=NOT_OURS)
        row = server.CORS_PREFLIGHT_REJECTIONS["x-not-allowed-anywhere"]
        self.assertGreater(row["count"], server.CORS_PREFLIGHT_ALERT_THRESHOLD)
        self.assertEqual(row["from_our_origins"], 0)
        self.assertEqual(self.alerts, [])

    def test_our_origin_alerts_once_the_threshold_is_crossed(self):
        n = server.CORS_PREFLIGHT_ALERT_THRESHOLD
        for _ in range(n - 1):
            self.preflight("x-not-allowed-anywhere")
        self.assertEqual(self.alerts, [], "alerted below the threshold")
        self.preflight("x-not-allowed-anywhere")
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(self.alerts[0][0], "x-not-allowed-anywhere")

    def test_it_alerts_ONCE_however_long_the_outage_runs(self):
        """The dedupe that FAILED_UNIQUE_INDEX_BUILDS exists to demonstrate:
        every blocked page-load re-triggers this, so an undeduped writer would
        produce thousands of rows during exactly the outage it reports."""
        for _ in range(server.CORS_PREFLIGHT_ALERT_THRESHOLD * 4):
            self.preflight("x-not-allowed-anywhere")
        self.assertEqual(len(self.alerts), 1)


class TheHealthPayloadSaysIt(Base):
    """The question nobody could ask for seven days: is the browser being
    refused permission to talk to this server."""

    def test_clean_when_nothing_has_been_refused(self):
        body = self.client.get("/api/health").json()
        self.assertTrue(body["cors"]["clean"])
        self.assertEqual(body["cors"]["refused_from_our_origins"], [])
        self.assertIn("X-Client-Version", body["cors"]["allow_headers"])

    def test_not_clean_and_named_once_our_origin_is_refused(self):
        self.preflight("x-not-allowed-anywhere")
        body = self.client.get("/api/health").json()
        self.assertFalse(body["cors"]["clean"])
        self.assertIn("x-not-allowed-anywhere",
                      body["cors"]["refused_from_our_origins"])

    def test_status_stays_healthy_so_this_is_not_a_restart_loop(self):
        """Same rule the index section follows: cycling the process does not
        add a header to a list, so flipping `status` would take the API down
        for a condition a restart cannot fix."""
        self.preflight("x-not-allowed-anywhere")
        body = self.client.get("/api/health").json()
        self.assertEqual(body["status"], "healthy")

    def test_a_scanner_is_visible_but_not_in_the_alerting_list(self):
        self.preflight("x-not-allowed-anywhere", origin=NOT_OURS)
        body = self.client.get("/api/health").json()
        self.assertTrue(body["cors"]["clean"])
        self.assertIn("x-not-allowed-anywhere", body["cors"]["refused_any_origin"])


class TheListIsNamedOnce(unittest.TestCase):
    """Three readers — the registration, the recorder and the health payload —
    must not be able to disagree about what is allowed."""

    def test_the_registration_uses_the_named_list(self):
        for mw in server.app.user_middleware:
            if isinstance(mw.cls, type) and issubclass(mw.cls, CORSMiddleware):
                self.assertIs(mw.kwargs.get("allow_headers"),
                              server.CORS_ALLOW_HEADERS)
                return
        self.fail("no CORS middleware registered")

    def test_the_registered_class_is_the_counting_one(self):
        """Or the refusal is silent again, which is the whole finding."""
        cls = [m.cls for m in server.app.user_middleware
               if isinstance(m.cls, type) and issubclass(m.cls, CORSMiddleware)]
        self.assertEqual(cls, [server.CountingCORSMiddleware])


if __name__ == "__main__":
    unittest.main(verbosity=2)
