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

    def test_dob_now_filing_handler_imports_cleanly(self):
        """Post-MR.11: the handler is no longer a stub — it's the
        real Playwright-driven implementation. Smoke test confirms
        the module imports without error and exposes the contract-
        required `handle` async function. Detailed handler behavior
        is covered in test_dob_now_filing_handler.py via mocked
        Playwright fixtures; this test just pins the module-level
        contract so the dispatcher can route to it."""
        from handlers.dob_now_filing import handle
        self.assertTrue(callable(handle))
        # Sanity: the handler signature accepts payload + context.
        # We don't invoke it here — that needs a real keypair and
        # Playwright mock setup which lives in the dedicated test
        # file. This is the routing-table contract check only.

    def test_dob_now_filing_returns_failed_on_missing_credentials(self):
        """Quick smoke that the handler returns a controlled
        HandlerResult (not a raise) when called with an empty
        payload — confirms the entry-point error path is wired,
        without dragging in Playwright mocks."""
        from handlers.dob_now_filing import handle
        from lib.handler_types import HandlerContext
        ctx = HandlerContext(worker_id="w1", http_client=MagicMock())
        result = _run(handle({"permit_renewal_id": "r1"}, ctx))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.detail, "missing_credentials_field")


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

    def test_dob_now_filing_routes_to_real_handler(self):
        """Post-MR.11: dispatcher routes dob_now_filing jobs to the
        real handler. Without a decryptable ciphertext + Playwright
        mocks, the handler bails early with detail=
        missing_credentials_field — but the important assertion
        here is that the dispatch + post-result flow fires once
        with the right job_type, NOT that the handler succeeds.
        Full handler behavior is in test_dob_now_filing_handler.py."""
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
                 "data": {"permit_renewal_id": "r1"}},  # no ciphertext
                context=ctx, breakers=breakers, state=state,
            ))

        self.assertEqual(http.post.await_count, 1)
        payload = http.post.await_args.kwargs["json"]
        self.assertEqual(payload["job_type"], "dob_now_filing")
        # Real handler returns 'failed' with a specific reason now,
        # not 'not_implemented'.
        self.assertEqual(payload["result"]["status"], "failed")
        self.assertEqual(
            payload["result"]["detail"], "missing_credentials_field",
        )

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


# ── MR.11 Bug 1 fix — filing_job_id propagation through post_result

class TestFilingJobIdPropagation(unittest.TestCase):
    """Regression for the MR.11 bug where _dispatch_one extracted
    permit_renewal_id from data but not filing_job_id, so the
    backend's /api/internal/job-result handler couldn't enter its
    filing_jobs branch (which gates on body.filing_job_id presence).
    Outcome: every FilingJob doc stayed at queued/claimed/in_progress
    forever even after the worker reported a terminal result. The
    permit_renewal transitioned correctly via the parallel branch,
    masking the bug.

    The fix: extract filing_job_id alongside permit_renewal_id and
    pass through every post_result call. Tests pin the propagation
    on three branches:
      • mode-refusal post_result
      • unknown-job-type post_result
      • normal-completion post_result"""

    def _make_context(self):
        from lib.handler_types import HandlerContext
        http = MagicMock()
        http.post = AsyncMock(return_value=MagicMock(status_code=200))
        return HandlerContext(worker_id="w1", http_client=http), http

    def test_filing_job_id_passed_on_unknown_job_type_post(self):
        import dob_worker as dw
        from lib.circuit_breaker import BreakerRegistry
        from lib.heartbeat import HeartbeatState

        ctx, http = self._make_context()
        breakers = BreakerRegistry()
        state = HeartbeatState("w1")

        with patch("dob_worker.claim_renewal", new=AsyncMock(return_value=True)):
            _run(dw._dispatch_one(
                {
                    "id": "j_unknown",
                    "type": "mystery",
                    "data": {
                        "permit_renewal_id": "r1",
                        "filing_job_id": "fj_carry_through",
                    },
                },
                context=ctx, breakers=breakers, state=state,
            ))

        self.assertEqual(http.post.await_count, 1)
        payload = http.post.await_args.kwargs["json"]
        self.assertEqual(payload["filing_job_id"], "fj_carry_through")

    def test_filing_job_id_passed_on_mode_refusal_post(self):
        import dob_worker as dw
        from lib.circuit_breaker import BreakerRegistry
        from lib.heartbeat import HeartbeatState

        ctx, http = self._make_context()
        breakers = BreakerRegistry()
        state = HeartbeatState("w1")

        # ELIGIBILITY_REWRITE_MODE is 'off' by default, so dob_now_filing
        # gets mode-refused before reaching the handler.
        with patch.object(dw, "ELIGIBILITY_REWRITE_MODE", "off"):
            _run(dw._dispatch_one(
                {
                    "id": "j_off",
                    "type": "dob_now_filing",
                    "data": {
                        "permit_renewal_id": "r1",
                        "filing_job_id": "fj_off_mode",
                    },
                },
                context=ctx, breakers=breakers, state=state,
            ))

        self.assertEqual(http.post.await_count, 1)
        payload = http.post.await_args.kwargs["json"]
        self.assertEqual(payload["filing_job_id"], "fj_off_mode")
        self.assertEqual(payload["result"]["status"], "failed")

    def test_filing_job_id_passed_on_normal_completion_post(self):
        """Handler runs (real handler returns failed/missing_creds
        because we pass no ciphertext) — the post_result that
        records the terminal outcome MUST carry filing_job_id."""
        import dob_worker as dw
        from lib.circuit_breaker import BreakerRegistry
        from lib.heartbeat import HeartbeatState

        ctx, http = self._make_context()
        breakers = BreakerRegistry()
        state = HeartbeatState("w1")

        with patch.object(dw, "ELIGIBILITY_REWRITE_MODE", "live"), \
             patch("dob_worker.claim_renewal", new=AsyncMock(return_value=True)):
            _run(dw._dispatch_one(
                {
                    "id": "j_live",
                    "type": "dob_now_filing",
                    "data": {
                        "permit_renewal_id": "r1",
                        "filing_job_id": "fj_live_path",
                    },
                },
                context=ctx, breakers=breakers, state=state,
            ))

        self.assertEqual(http.post.await_count, 1)
        payload = http.post.await_args.kwargs["json"]
        self.assertEqual(payload["filing_job_id"], "fj_live_path")

    def test_filing_job_id_absent_in_payload_does_not_break_dispatch(self):
        """Backward compat: jobs without filing_job_id (legacy
        bis_scrape, or anything pre-MR.6) must still dispatch.
        post_result helper accepts filing_job_id=None (default);
        the cloud-side /job-result handler skips the filing_jobs
        branch when the field is absent."""
        import dob_worker as dw
        from lib.circuit_breaker import BreakerRegistry
        from lib.heartbeat import HeartbeatState

        ctx, http = self._make_context()
        breakers = BreakerRegistry()
        state = HeartbeatState("w1")

        with patch("dob_worker.claim_renewal", new=AsyncMock(return_value=True)):
            _run(dw._dispatch_one(
                {
                    "id": "j_legacy",
                    "type": "mystery",
                    "data": {"permit_renewal_id": "r1"},  # no filing_job_id
                },
                context=ctx, breakers=breakers, state=state,
            ))

        self.assertEqual(http.post.await_count, 1)
        payload = http.post.await_args.kwargs["json"]
        # Helper omits the field when filing_job_id is None — so the
        # body should NOT carry a `filing_job_id: null`.
        self.assertNotIn("filing_job_id", payload)


# ── MR.11 Bug 2 fix — fetch_filing_job hits internal-tier endpoint

class TestFetchFilingJobUsesInternalEndpoint(unittest.TestCase):
    """Regression for the MR.11 bug where fetch_filing_job called
    the operator-tier list endpoint
    /api/permit-renewals/{id}/filing-jobs which 401'd on
    X-Worker-Secret. The fix routes through the new internal-tier
    GET /api/internal/filing-jobs/{filing_job_id}."""

    def test_fetch_calls_internal_endpoint_path(self):
        from lib.queue_client import fetch_filing_job

        http = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={
            "_id": "fj_1", "id": "fj_1",
            "cancellation_requested": True,
            "audit_log": [],
        })
        http.get = AsyncMock(return_value=resp)

        result = _run(fetch_filing_job(
            http,
            backend_url="https://api.example.com",
            permit_renewal_id="r1",
            filing_job_id="fj_1",
        ))
        self.assertIsNotNone(result)
        self.assertTrue(result["cancellation_requested"])
        # URL must hit the internal-tier endpoint, NOT the operator-
        # tier list endpoint that 401'd.
        called_url = http.get.await_args.args[0]
        self.assertEqual(
            called_url,
            "https://api.example.com/api/internal/filing-jobs/fj_1",
        )

    def test_fetch_returns_none_on_non_200(self):
        from lib.queue_client import fetch_filing_job

        http = MagicMock()
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "FilingJob not found"
        http.get = AsyncMock(return_value=resp)

        result = _run(fetch_filing_job(
            http,
            backend_url="https://api.example.com",
            permit_renewal_id="r1",
            filing_job_id="fj_missing",
        ))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
