"""backend/scripts/dob_wrong_facts_report.py is READ ONLY: its lock refuses
every pymongo write before any server is contacted (#869). CONTROL: with the
lock not installed the same writes are attempted against the (unreachable)
server instead of being refused -- every assertion below fails."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo import MongoClient  # noqa: E402
from pymongo.collection import Collection  # noqa: E402

from scripts import dob_wrong_facts_report as R  # noqa: E402

LOCK_OFF = os.environ.get("DOB_REPORT_LOCK_OFF") == "1"


class TheReportCannotWrite(unittest.TestCase):

    def setUp(self):
        self.saved = {w: Collection.__dict__[w] for w in R._WRITES if w in Collection.__dict__}
        if not LOCK_OFF:
            R.lock_writes()

    def tearDown(self):
        for w, fn in self.saved.items():
            setattr(Collection, w, fn)

    def test_every_write_is_refused_without_touching_a_server(self):
        col = MongoClient("mongodb://127.0.0.1:9", connect=False,
                          serverSelectionTimeoutMS=50)["prod"]["dob_logs"]
        for name, call in (("insert_one", lambda: col.insert_one({"_id": 1})),
                           ("update_one", lambda: col.update_one({"_id": 1}, {"$set": {"x": 1}}, upsert=True)),
                           ("find_one_and_update", lambda: col.find_one_and_update({"_id": 1}, {"$set": {"x": 1}})),
                           ("bulk_write", lambda: col.bulk_write([])),
                           ("delete_many", lambda: col.delete_many({}))):
            with self.subTest(name):
                with self.assertRaises(R.ReadOnlyViolation):
                    call()


if __name__ == "__main__":
    unittest.main()
