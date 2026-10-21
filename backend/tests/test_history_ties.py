"""TWO FACTS WITH THE SAME TIMESTAMP COME BACK IN THE ORDER THEY WERE WRITTEN.

WHAT WAS WRONG. Both lookups ordered on the timestamp alone:

  * `_dm_history` / `_dm_brain_history` read a chat newest-first by
    `created_at`, then reversed it. A question and the bot's reply stored in
    the same clock tick came back SWAPPED, and the repeat guard paired an
    answer with the wrong question ("That's what I just sent..." to an answer
    it never sent for that question). On Windows `datetime.now()` ticks at
    ~15.6 ms, so the DM tests failed at random locally; on Linux a tie needs
    two writes in one microsecond, which is rare and not impossible (Mongo
    stores milliseconds).

  * `wa_alerts.status_as_of` broke a timestamp tie by the position a row
    happened to have in the caller's list -- the order of a find() with no
    sort, which Mongo does not promise.

THE FIX. Order on (timestamp, _id). An ObjectId grows with insertion, so a tie
resolves to write order. Each test below INJECTS the same timestamp, so the
tie is reproduced every run instead of one run in three.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from bson import ObjectId  # noqa: E402

import server  # noqa: E402
from lib import wa_alerts  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

CHAT = "15550001001@c.us"
T = datetime(2026, 10, 21, 14, 0, 0, tzinfo=timezone.utc)


def _msgs(*bodies):
    """Rows in WRITE order, every one stamped with the same instant, with
    ObjectIds that grow in that order (as Mongo's do)."""
    out = []
    for sender, body in bodies:
        out.append({"_id": ObjectId(), "group_id": CHAT, "is_dm": True,
                    "sender": sender, "body": body, "created_at": T})
    return out


def _run(coro):
    return asyncio.run(coro)


class TheDmHistoryKeepsWriteOrderOnATie(unittest.TestCase):

    ROWS = [("15550001001", "what's open at 8 walworth?"),
            ("bot", "answer for proj_w"),
            ("15550001001", "?")]

    def _read(self, fn, rows):
        db = FakeDb(whatsapp_messages=rows)
        with patch.object(server, "db", db):
            return _run(fn(CHAT, T + timedelta(minutes=1)))

    def test_dm_history_returns_a_same_instant_question_and_reply_in_write_order(self):
        got = self._read(server._dm_history, _msgs(*self.ROWS))
        self.assertEqual([r["body"] for r in got], [b for _, b in self.ROWS])

    def test_the_brain_history_does_too(self):
        got = self._read(server._dm_brain_history, _msgs(*self.ROWS))
        self.assertEqual([r["body"] for r in got], [b for _, b in self.ROWS])

    def test_order_holds_whatever_order_the_store_hands_them_back(self):
        # The fake returns rows in list order before sorting; feed them
        # shuffled so only the sort can put them right.
        rows = _msgs(*self.ROWS)
        got = self._read(server._dm_history, [rows[2], rows[0], rows[1]])
        self.assertEqual([r["body"] for r in got], [b for _, b in self.ROWS])


class StatusAsOfBreaksATieByRecordId(unittest.TestCase):

    def _rows(self, with_history):
        older, newer = ObjectId(), ObjectId()
        if with_history:
            a = {"_id": older, "status_history": [{"status": "ACTIVE", "at": T}]}
            b = {"_id": newer, "status_history": [{"status": "RESCINDED", "at": T}]}
        else:
            a = {"_id": older, "current_status": "ACTIVE", "detected_at": T}
            b = {"_id": newer, "current_status": "RESCINDED", "detected_at": T}
        return a, b

    def test_diff_rows_at_the_same_instant_resolve_to_the_later_written(self):
        a, b = self._rows(with_history=False)
        self.assertEqual(wa_alerts.status_as_of([a, b], T), "RESCINDED")
        self.assertEqual(wa_alerts.status_as_of([b, a], T), "RESCINDED",
                         "the caller's list order must not decide a tie")

    def test_history_rows_at_the_same_instant_resolve_to_the_later_written(self):
        a, b = self._rows(with_history=True)
        self.assertEqual(wa_alerts.status_as_of([a, b], T), "RESCINDED")
        self.assertEqual(wa_alerts.status_as_of([b, a], T), "RESCINDED")

    def test_within_one_row_a_tie_goes_to_the_later_entry(self):
        # The documented rule, unchanged: the history array is write order.
        row = {"_id": ObjectId(), "status_history": [
            {"status": "ACTIVE", "at": T}, {"status": "RESCINDED", "at": T}]}
        self.assertEqual(wa_alerts.status_as_of(row, T), "RESCINDED")
        self.assertIsNone(wa_alerts.status_as_of(row, T - timedelta(seconds=1)))


class TheFakeHandsOutIdsThatSortLikeMongos(unittest.TestCase):
    """An (x, _id) sort is only write order if ids grow in write order. The
    fake handed out "oid9" then "oid10", and "oid10" < "oid9" as text."""

    def test_generated_ids_sort_in_insertion_order(self):
        db = FakeDb()
        ids = [_run(db.things.insert_one({"n": i})).inserted_id for i in range(12)]
        self.assertEqual(sorted(ids), ids)


if __name__ == "__main__":
    unittest.main()
