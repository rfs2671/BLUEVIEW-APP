"""Heartbeat snapshot shape + retry behavior."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
import unittest.mock
from unittest.mock import AsyncMock, MagicMock

_DOB_WORKER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DOB_WORKER))


def _run(coro):
    return asyncio.run(coro)


class TestHeartbeatSnapshot(unittest.TestCase):

    def test_snapshot_includes_per_job_type_metrics(self):
        from lib.heartbeat import HeartbeatState
        state = HeartbeatState(worker_id="test-worker-1")
        state.jobs_completed["bis_scrape"] = 3
        state.jobs_failed["dob_now_filing"] = 1
        state.circuit_breaker["bis_scrape"] = "open"
        state.challenge_rate_50req["bis_scrape"] = 0.18
        state.queue_depth = 1

        snap = state.snapshot()
        self.assertEqual(snap["worker_id"], "test-worker-1")
        self.assertEqual(snap["queue_depth"], 1)
        self.assertEqual(snap["circuit_breaker"]["bis_scrape"], "open")
        self.assertEqual(snap["challenge_rate_50req"]["bis_scrape"], 0.18)
        self.assertEqual(snap["jobs_completed"]["bis_scrape"], 3)
        self.assertEqual(snap["jobs_failed"]["dob_now_filing"], 1)
        self.assertIn("ts", snap)


class TestHeartbeatRetry(unittest.TestCase):

    def test_retries_on_5xx_then_succeeds(self):
        from lib import heartbeat as hb_mod
        state = hb_mod.HeartbeatState(worker_id="w1")

        # Three responses: 500, 503, 200 — succeed on the 3rd attempt.
        responses = [
            MagicMock(status_code=500, text="boom"),
            MagicMock(status_code=503, text="busy"),
            MagicMock(status_code=200, text="ok"),
        ]
        http_client = MagicMock()
        http_client.post = AsyncMock(side_effect=responses)

        # Patch asyncio.sleep inside the heartbeat module to a yielding
        # no-op so the retry chain runs to completion without real waits
        # but still hands control back to the event loop on every await.
        # (A non-yielding sleep starves the test's poll loop, which is
        # how the prior version of this test ran for ~108 minutes before
        # OOMing.)
        original_sleep = asyncio.sleep

        async def _instant_sleep(_seconds):
            await original_sleep(0)

        async def go():
            with unittest.mock.patch.object(hb_mod.asyncio, "sleep",
                                             new=_instant_sleep):
                task = asyncio.create_task(hb_mod.heartbeat_loop(
                    state, backend_url="http://test",
                    http_client=http_client, interval_seconds=0,
                ))
                # Poll until all 3 mocked responses are consumed, then
                # cancel — before the outer `while True:` re-enters and
                # blows past the side_effect list (which would otherwise
                # spin indefinitely under the broad `except Exception`).
                for _ in range(200):
                    await original_sleep(0)
                    if http_client.post.await_count >= 3:
                        break
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        _run(go())
        # All three responses consumed in order → 3 POSTs.
        self.assertEqual(http_client.post.await_count, 3)


if __name__ == "__main__":
    unittest.main()
