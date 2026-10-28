"""The review queue holds takeoff and clash items (Roy, 2026-10-28: the
product is takeoffs + clash detection). Their producers - the takeoff
export's "not verified / refused" lines and the spatial lane's clash pass -
queue them through server._review_queue_takeoff / _review_queue_clash.

  * one item per (project, trade, item, scope, set) / (project, pair, where);
  * the reasons are takeoff_refused and clash, normal priority, and the
    owner's list filters and decides them like any other item;
  * per company, never raising, no phone in full.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import review_queue as rq  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
CO, P = "co_a", "proj_a"


def _run(c):
    return asyncio.run(c)


class Builders(unittest.TestCase):
    def test_takeoff_item(self):
        doc = rq.from_takeoff(CO, P, trade="Doors/windows", item_name="type F doors",
                              scope="Floor 4", track="owner's set",
                              reason="a tag on A-104.00 could not be read",
                              sheets=["A-104.00", "A-104.00"], now=NOW)
        self.assertEqual((doc["kind"], doc["reason"], doc["priority"], doc["status"]),
                         ("takeoff", "takeoff_refused", "normal", "pending"))
        self.assertEqual(doc["project_id"], P)
        self.assertEqual(doc["evidence"]["sheets"], ["A-104.00"])
        self.assertEqual(doc["summary"],
                         "Doors/windows: type F doors (Floor 4 · owner's set) - "
                         "a tag on A-104.00 could not be read")
        same = rq.from_takeoff(CO, P, trade="doors/windows", item_name="Type F doors",
                               scope="floor 4", track="Owner's set", reason="other words",
                               now=NOW)
        self.assertEqual(same["_id"], doc["_id"], "the same line again is one item")
        other = rq.from_takeoff(CO, P, trade="Doors/windows", item_name="type F doors",
                                scope="Floor 5", reason="x", now=NOW)
        self.assertNotEqual(other["_id"], doc["_id"])

    def test_clash_item_either_order(self):
        a = rq.from_clash(CO, P, a="Duct D-12", b="Beam B-3", where="Floor 2, grid C/4",
                          detail="duct bottom below beam bottom", sheets=["M-102.00", "S-102"],
                          now=NOW)
        b = rq.from_clash(CO, P, a="Beam B-3", b="Duct D-12", where="Floor 2, grid C/4", now=NOW)
        self.assertEqual((a["kind"], a["reason"]), ("clash", "clash"))
        self.assertEqual(a["_id"], b["_id"])
        self.assertIn("clashes with", a["summary"])

    def test_nothing_without_what_it_is_about(self):
        self.assertIsNone(rq.from_takeoff(CO, None, trade="t", item_name="i", reason="r", now=NOW))
        self.assertIsNone(rq.from_takeoff(CO, P, trade="", item_name="i", reason="r", now=NOW))
        self.assertIsNone(rq.from_takeoff(CO, P, trade="t", item_name="i", reason=" ", now=NOW))
        self.assertIsNone(rq.from_takeoff(None, P, trade="t", item_name="i", reason="r", now=NOW))
        self.assertIsNone(rq.from_clash(CO, P, a="x", b="", now=NOW))

    def test_no_phone_in_full(self):
        doc = rq.from_takeoff(CO, P, trade="t", item_name="i",
                              reason="call 2125550199 about it", now=NOW)
        self.assertNotIn("2125550199", json.dumps(doc, default=str, ensure_ascii=False))


class ServerEntryPoints(unittest.TestCase):
    def test_queued_once_and_never_raising(self):
        db = FakeDb()
        with patch.object(server, "db", db):
            for _ in range(2):
                self.assertTrue(_run(server._review_queue_takeoff(
                    CO, P, trade="Roof drains", item_name="RD", scope="Roof",
                    reason="the roof plan was not read")))
            self.assertTrue(_run(server._review_queue_clash(
                CO, P, a="Duct D-12", b="Beam B-3", where="Floor 2")))
            self.assertFalse(_run(server._review_queue_takeoff(CO, P, trade="", item_name="x",
                                                               reason="r")))
            self.assertIsNone(_run(server._review_queue_takeoff(CO, P, bogus=1)))
        kinds = sorted(r["kind"] for r in db.review_queue.rows)
        self.assertEqual(kinds, ["clash", "takeoff"])

    def test_the_owner_list_filters_them(self):
        self.assertIn("takeoff", rq.KINDS)
        self.assertIn("clash", rq.KINDS)
        self.assertIn("takeoff_refused", rq.REASONS)
        self.assertIn("clash", rq.REASONS)


if __name__ == "__main__":
    unittest.main()
