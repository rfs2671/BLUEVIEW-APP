"""Workers who check in after the Daily Jobsite Log is signed are put on the
books automatically: the server opens a correction carrying the reason, and the
daily log's own roster reconciliation adds their crews when it is opened.
These pin the pieces that decide WHO is late."""
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


class WhoIsOnTheSignedLog(unittest.TestCase):
    def test_every_crews_worker_ids_count(self):
        log = {"data": {"activities": [
            {"company": "J&P", "worker_ids": ["a", "b"]},
            {"company": "", "worker_ids": ["c"]},
            {"company": "Echo"},
        ]}}
        self.assertEqual(server._daily_log_worker_ids(log), {"a", "b", "c"})

    def test_an_empty_or_missing_log_names_nobody(self):
        self.assertEqual(server._daily_log_worker_ids({}), set())
        self.assertEqual(server._daily_log_worker_ids(None), set())

    def test_the_route_is_registered(self):
        paths = {getattr(r, "path", "") for r in server.app.routes}
        self.assertIn("/api/logbooks/project/{project_id}/daily-jobsite/late-arrivals", paths)


if __name__ == "__main__":
    unittest.main()
