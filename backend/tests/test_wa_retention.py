"""Project-based retention for WhatsApp messages and attention items
(lib/wa_retention.py, server._retention_tick)."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import wa_retention as r  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

NOW = datetime(2026, 10, 10, 7, 0, tzinfo=timezone.utc)     # 3 AM New York


def _run(coro):
    return asyncio.run(coro)


def _world(completion=None, hold=False, test_company=False):
    db = FakeDb()
    db.companies.rows.append({"_id": "co1", "name": "GC", **({"is_test": True} if test_company else {})})
    proj = {"_id": "p1", "company_id": "co1", "name": "588 Thomas"}
    if completion:
        proj["job_completion_date"] = completion
        proj["job_completion_co_number"] = "CO-1"
    if hold:
        proj.update(legal_hold=True, legal_hold_reason="claim")
    db.projects.rows.append(proj)
    old = NOW - timedelta(days=3 * 365)
    for i in range(3):
        db.whatsapp_messages.rows.append({"_id": f"m{i}", "company_id": "co1", "project_id": "p1",
                                          "group_id": "g1", "created_at": old})
    db.attention_items.rows.append({"_id": "a1", "company_id": "co1", "project_id": "p1",
                                    "created_at": old, "history": [{"kind": "created"}]})
    db.chase_shadow.rows.append({"_id": "c1", "company_id": "co1", "project_id": "p1",
                                 "created_at": old})
    return db


def _tick(db, purge=True, now=NOW):
    with patch.object(server, "db", db):
        return _run(server._retention_tick(now, purge=purge))


class TheRule(unittest.TestCase):

    def test_an_open_project_never_expires(self):
        self.assertIsNone(r.project_expires_on({"_id": "p"}))
        self.assertFalse(r.project_expired({"_id": "p"}, "2099-01-01"))

    def test_seven_years_after_completion(self):
        p = {"job_completion_date": "2019-03-01"}
        self.assertEqual(r.project_expires_on(p).isoformat(), "2026-03-01")
        self.assertFalse(r.project_expired(p, "2026-02-28"))
        self.assertTrue(r.project_expired(p, "2026-03-01"))

    def test_a_hold_and_an_unreadable_date_never_expire(self):
        self.assertFalse(r.project_expired({"job_completion_date": "2010-01-01",
                                            "legal_hold": True}, "2026-10-10"))
        self.assertFalse(r.project_expired({"job_completion_date": "sometime 2019"},
                                           "2026-10-10"))
        self.assertFalse(r.project_expired({"job_completion_date": "2010-01-01"}, ""))

    def test_dry_run_is_the_default(self):
        with patch.dict(os.environ, {"RETENTION_PURGE_ENABLED": ""}):
            self.assertFalse(r.purge_enabled())
        with patch.dict(os.environ, {"RETENTION_PURGE_ENABLED": "1"}):
            self.assertTrue(r.purge_enabled())


class TheJob(unittest.TestCase):

    def test_an_open_project_keeps_everything(self):
        db = _world()                                  # no completion date
        rep = _tick(db)
        self.assertEqual((rep["would_expire"], rep["deleted"]), (0, 0))
        self.assertEqual(len(db.whatsapp_messages.rows), 3)
        self.assertEqual(len(db.attention_items.rows), 1)

    def test_seven_years_after_completion_it_all_goes(self):
        db = _world(completion="2019-03-01")           # expired 2026-03-01
        rep = _tick(db)
        self.assertEqual(rep["deleted"], 5)
        self.assertEqual((db.whatsapp_messages.rows, db.attention_items.rows,
                          db.chase_shadow.rows), ([], [], []))
        c = rep["companies"]["co1"]["whatsapp_messages"]
        self.assertEqual((c["would_expire"], c["by_reason"]), (3, {"project_retention": 3}))

    def test_before_seven_years_nothing_goes(self):
        db = _world(completion="2020-03-01")           # expires 2027-03-01
        self.assertEqual(_tick(db)["would_expire"], 0)

    def test_clearing_the_date_cancels_the_expiry(self):
        db = _world(completion="2019-03-01")
        self.assertEqual(_tick(db, purge=False)["would_expire"], 5)
        db.projects.rows[0].pop("job_completion_date")
        rep = _tick(db)
        self.assertEqual((rep["would_expire"], rep["deleted"]), (0, 0))
        self.assertEqual(len(db.whatsapp_messages.rows), 3)

    def test_a_legal_hold_keeps_everything(self):
        db = _world(completion="2010-01-01", hold=True)
        self.assertEqual(_tick(db)["would_expire"], 0)

    def test_dry_run_counts_and_deletes_nothing(self):
        db = _world(completion="2019-03-01")
        rep = _tick(db, purge=False)
        self.assertEqual((rep["mode"], rep["would_expire"], rep["deleted"]), ("dry_run", 5, 0))
        self.assertEqual(len(db.whatsapp_messages.rows), 3)
        (led,) = db[r.LEDGER].rows
        self.assertEqual((led["mode"], led["would_expire"], led["deleted"]), ("dry_run", 5, 0))
        self.assertEqual(led["companies"]["co1"]["attention_items"]["would_expire"], 1)

    def test_unlinked_messages_go_at_24_months(self):
        db = _world()
        db.whatsapp_messages.rows += [
            {"_id": "u_old", "company_id": "co1", "project_id": None,
             "created_at": NOW - timedelta(days=731)},
            {"_id": "u_new", "company_id": "co1", "project_id": None,
             "created_at": NOW - timedelta(days=700)},
            {"_id": "u_nodate", "company_id": "co1", "project_id": ""},
            # The project is gone: unlinked, by its own date.
            {"_id": "gone_old", "company_id": "co1", "project_id": "p_gone",
             "created_at": NOW - timedelta(days=800)},
            {"_id": "gone_new", "company_id": "co1", "project_id": "p_gone",
             "created_at": NOW - timedelta(days=10)},
        ]
        rep = _tick(db)
        left = sorted(m["_id"] for m in db.whatsapp_messages.rows)
        self.assertEqual(left, ["gone_new", "m0", "m1", "m2", "u_new", "u_nodate"])
        self.assertEqual(rep["companies"]["co1"]["whatsapp_messages"]["by_reason"],
                         {"project_gone": 1, "unlinked": 1})

    def test_fixture_companies_are_skipped(self):
        db = _world(completion="2019-03-01", test_company=True)
        rep = _tick(db)
        self.assertEqual((rep["would_expire"], rep["deleted"]), (0, 0))
        self.assertGreater(rep["skipped_test"], 0)
        self.assertEqual(len(db.whatsapp_messages.rows), 3)

    def test_never_more_than_the_nightly_cap(self):
        db = _world(completion="2019-03-01")
        with patch.object(r, "MAX_DELETES_PER_RUN", 2), patch.object(r, "BATCH", 1):
            rep = _tick(db)
        self.assertEqual((rep["deleted"], rep["capped"]), (2, True))
        self.assertEqual(rep["would_expire"], 5)
        rep = _tick(db)                               # the rest the next night
        self.assertEqual(rep["deleted"], 3)


class TheTtlIsGone(unittest.TestCase):

    def test_the_old_ttl_is_dropped_on_boot(self):
        db = FakeDb()
        _run(db.whatsapp_messages.create_index([("created_at", 1)], name="whatsapp_messages_ttl_24m",
                                               expireAfterSeconds=730 * 86400))
        with patch.object(server, "db", db):
            _run(server.ensure_whatsapp_phase1_indexes())
        self.assertFalse([ix for ix in db.whatsapp_messages.indexes if "expireAfterSeconds" in ix])

    def test_the_job_is_nightly_and_leased(self):
        src = Path(server.__file__).read_text()
        self.assertIn("id='whatsapp_retention'", src)
        self.assertIn('CronTrigger(hour=2, minute=45, timezone="America/New_York")', src)


if __name__ == "__main__":
    unittest.main()
