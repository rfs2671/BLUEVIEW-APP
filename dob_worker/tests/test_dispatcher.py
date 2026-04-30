"""Dispatcher routing tests — job_type → handler."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_DOB_WORKER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DOB_WORKER))


def _run(coro):
    return asyncio.run(coro)


class TestHandlerRoutingTable(unittest.TestCase):

    def test_handlers_registers_both_known_kinds(self):
        from handlers import HANDLERS
        # HANDLERS is a {job_type: import_path} map — verify both
        # known job types are registered without resolving them
        # (resolution would import bis_scrape's heavy deps).
        self.assertIn("bis_scrape", HANDLERS)
        self.assertIn("dob_now_filing", HANDLERS)
        self.assertEqual(HANDLERS["bis_scrape"], "handlers.bis_scrape:handle")
        self.assertEqual(HANDLERS["dob_now_filing"], "handlers.dob_now_filing:handle")

    def test_get_handler_returns_none_for_unknown_kind(self):
        from handlers import get_handler
        self.assertIsNone(get_handler("mystery"))

    def test_dob_now_filing_stub_returns_not_implemented(self):
        # Direct import bypasses the bis_scrape heavy-deps chain.
        from handlers.dob_now_filing import handle
        from lib.handler_types import HandlerContext
        ctx = HandlerContext(worker_id="w1", http_client=MagicMock())
        result = _run(handle({"permit_renewal_id": "r1"}, ctx))
        self.assertEqual(result.status, "not_implemented")
        self.assertEqual(result.metadata.get("permit_renewal_id"), "r1")


class TestDispatchOne(unittest.TestCase):
    """End-to-end dispatch flow with mocked claim + post_result +
    handler. Verifies the orchestrator routes correctly and posts
    results."""

    def _make_context(self):
        from lib.handler_types import HandlerContext
        http = MagicMock()
        http.post = AsyncMock(return_value=MagicMock(status_code=200))
        return HandlerContext(worker_id="w1", http_client=http), http

    def test_unknown_job_type_posts_failed_result(self):
        import dob_worker as dw
        from lib.circuit_breaker import BreakerRegistry
        from lib.heartbeat import HeartbeatState

        ctx, http = self._make_context()
        breakers = BreakerRegistry()
        state = HeartbeatState("w1")

        with patch("dob_worker.claim_renewal", new=AsyncMock(return_value=True)):
            _run(dw._dispatch_one(
                {"id": "j1", "type": "mystery", "data": {}},
                context=ctx, breakers=breakers, state=state,
            ))

        # /api/internal/job-result was POSTed once with status=failed.
        self.assertEqual(http.post.await_count, 1)
        payload = http.post.await_args.kwargs["json"]
        self.assertEqual(payload["job_type"], "mystery")
        self.assertEqual(payload["result"]["status"], "failed")
        self.assertIn("Unknown job_type", payload["result"]["detail"])

    def test_dob_now_filing_routes_to_stub_handler(self):
        import dob_worker as dw
        from lib.circuit_breaker import BreakerRegistry
        from lib.heartbeat import HeartbeatState

        ctx, http = self._make_context()
        breakers = BreakerRegistry()
        state = HeartbeatState("w1")

        # Force live-mode so the dispatcher doesn't refuse the job.
        with patch.object(dw, "ELIGIBILITY_REWRITE_MODE", "live"), \
             patch("dob_worker.claim_renewal", new=AsyncMock(return_value=True)):
            _run(dw._dispatch_one(
                {"id": "j2", "type": "dob_now_filing",
                 "data": {"permit_renewal_id": "r1"}},
                context=ctx, breakers=breakers, state=state,
            ))

        self.assertEqual(http.post.await_count, 1)
        payload = http.post.await_args.kwargs["json"]
        self.assertEqual(payload["job_type"], "dob_now_filing")
        self.assertEqual(payload["result"]["status"], "not_implemented")

    def test_dob_now_filing_refused_when_not_live(self):
        import dob_worker as dw
        from lib.circuit_breaker import BreakerRegistry
        from lib.heartbeat import HeartbeatState

        ctx, http = self._make_context()
        breakers = BreakerRegistry()
        state = HeartbeatState("w1")

        with patch.object(dw, "ELIGIBILITY_REWRITE_MODE", "shadow"):
            _run(dw._dispatch_one(
                {"id": "j3", "type": "dob_now_filing",
                 "data": {"permit_renewal_id": "r1"}},
                context=ctx, breakers=breakers, state=state,
            ))

        self.assertEqual(http.post.await_count, 1)
        payload = http.post.await_args.kwargs["json"]
        self.assertEqual(payload["result"]["status"], "failed")
        self.assertIn("ELIGIBILITY_REWRITE_MODE", payload["result"]["detail"])

    def test_breaker_open_drops_job(self):
        import dob_worker as dw
        from lib.circuit_breaker import BreakerRegistry
        from lib.heartbeat import HeartbeatState

        ctx, http = self._make_context()
        breakers = BreakerRegistry()
        # Force the breaker open.
        bs = breakers.get("bis_scrape")
        for _ in range(50):
            bs.record(challenged=True)
        state = HeartbeatState("w1")

        _run(dw._dispatch_one(
            {"id": "j4", "type": "bis_scrape", "data": {}},
            context=ctx, breakers=breakers, state=state,
        ))

        # No /job-result post.
        self.assertEqual(http.post.await_count, 0)


if __name__ == "__main__":
    unittest.main()
