"""backend/scripts/duplicate_accounts_census.py is READ ONLY, and it groups the
accounts the ruling is about. CONTROL: with CENSUS_LOCK_OFF=1 the lock is not
installed, the same writes are attempted against an unreachable server instead
of being refused, and the guard class fails."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo import MongoClient  # noqa: E402
from pymongo.collection import Collection  # noqa: E402

from scripts import duplicate_accounts_census as C  # noqa: E402

LOCK_OFF = os.environ.get("CENSUS_LOCK_OFF") == "1"


class TheCensusCannotWrite(unittest.TestCase):

    def setUp(self):
        self.saved = {w: Collection.__dict__[w] for w in C._WRITES if w in Collection.__dict__}
        if not LOCK_OFF:
            C.lock_writes()

    def tearDown(self):
        for w, fn in self.saved.items():
            setattr(Collection, w, fn)

    def test_every_write_is_refused_without_touching_a_server(self):
        col = MongoClient("mongodb://127.0.0.1:9", connect=False,
                          serverSelectionTimeoutMS=50)["prod"]["users"]
        for name, call in (("insert_one", lambda: col.insert_one({"_id": 1})),
                           ("update_one", lambda: col.update_one({"_id": 1}, {"$set": {"x": 1}}, upsert=True)),
                           ("find_one_and_update", lambda: col.find_one_and_update({"_id": 1}, {"$set": {"x": 1}})),
                           ("bulk_write", lambda: col.bulk_write([])),
                           ("delete_many", lambda: col.delete_many({}))):
            with self.subTest(name):
                with self.assertRaises(C.ReadOnlyViolation):
                    call()

    def test_the_password_is_never_read(self):
        self.assertNotIn("password", C.USER_FIELDS)


class Grouping(unittest.TestCase):

    def test_emails_match_ignoring_case_and_spaces(self):
        users = [{"_id": 1, "email": "Bob@X.com"}, {"_id": 2, "email": " bob@x.com "},
                 {"_id": 3, "email": "ann@x.com"}]
        self.assertEqual({k: [u["_id"] for u in v]
                          for k, v in C.groups(users, C.email_key, "email").items()},
                         {"bob@x.com": [1, 2]})

    def test_phones_match_on_their_last_ten_digits(self):
        users = [{"_id": 1, "phone": "+1 (917) 555-0100"}, {"_id": 2, "phone": "9175550100"},
                 {"_id": 3, "phone": "555-0100"}, {"_id": 4, "phone": None}]
        self.assertEqual({k: [u["_id"] for u in v]
                          for k, v in C.groups(users, C.phone_key, "phone").items()},
                         {"9175550100": [1, 2]})


if __name__ == "__main__":
    unittest.main()
