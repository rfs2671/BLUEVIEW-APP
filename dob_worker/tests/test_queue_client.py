"""Queue client BRPOP loop + claim flow."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_DOB_WORKER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DOB_WORKER))


def _run(coro):
    return asyncio.run(coro)


class TestQueuePollOne(unittest.TestCase):

    def test_decodes_brpop_result(self):
        from lib.queue_client import QueueClient
        qc = QueueClient("redis://test")
        # Inject a stub redis so _connect is a no-op.
        qc._redis = MagicMock()
        job_data = {"id": "j1", "type": "bis_scrape", "data": {}}
        qc._redis.brpop = AsyncMock(
            return_value=("levelog:filing-queue", json.dumps(job_data)),
        )

        decoded = _run(qc.poll_one())
        self.assertEqual(decoded["id"], "j1")
        self.assertEqual(decoded["type"], "bis_scrape")

    def test_returns_none_on_brpop_timeout(self):
        from lib.queue_client import QueueClient
        qc = QueueClient("redis://test")
        qc._redis = MagicMock()
        qc._redis.brpop = AsyncMock(return_value=None)
        self.assertIsNone(_run(qc.poll_one()))

    def test_drops_malformed_json(self):
        from lib.queue_client import QueueClient
        qc = QueueClient("redis://test")
        qc._redis = MagicMock()
        qc._redis.brpop = AsyncMock(
            return_value=("k", "{not valid json"),
        )
        self.assertIsNone(_run(qc.poll_one()))


class TestClaimRenewal(unittest.TestCase):

    def test_no_permit_renewal_id_auto_claims(self):
        """bis_scrape jobs don't carry a permit_renewal_id — they're
        not bound to renewal state. Auto-claim by returning True."""
        from lib.queue_client import claim_renewal
        http = MagicMock()
        http.post = AsyncMock()
        result = _run(claim_renewal(
            http, None, backend_url="http://b", worker_id="w1",
        ))
        self.assertTrue(result)
        http.post.assert_not_awaited()

    def test_200_response_returns_true(self):
        from lib.queue_client import claim_renewal
        http = MagicMock()
        http.post = AsyncMock(return_value=MagicMock(status_code=200))
        self.assertTrue(_run(claim_renewal(
            http, "renewal_a", backend_url="http://b", worker_id="w1",
        )))

    def test_409_response_returns_false(self):
        from lib.queue_client import claim_renewal
        http = MagicMock()
        http.post = AsyncMock(return_value=MagicMock(status_code=409))
        self.assertFalse(_run(claim_renewal(
            http, "renewal_a", backend_url="http://b", worker_id="w1",
        )))

    def test_unexpected_status_returns_false(self):
        from lib.queue_client import claim_renewal
        http = MagicMock()
        http.post = AsyncMock(return_value=MagicMock(status_code=500, text="x"))
        self.assertFalse(_run(claim_renewal(
            http, "renewal_a", backend_url="http://b", worker_id="w1",
        )))


if __name__ == "__main__":
    unittest.main()
