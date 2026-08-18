"""SIGN ONCE, FREEZE AT END OF DAY.

END_OF_DAY was described in three places and implemented in none. Both
LOGBOOK_TIMING_CLASS and frontend/src/utils/logbookTiming.js call it the class
that "stays open and accumulating all day" and freezes at the end-of-day sign,
and /logbook-types serves that to clients as `timing_class` / `is_batchable` /
`freeze_on_finalize`. The editors called /finalize the instant the CP signed,
so a log signed at 9am froze at 9am and the only observable difference between
the two timing classes was which code path did the locking.

This is the half that closes the record. Without it the client change would
leave an END_OF_DAY log open forever, which is a worse exposure than freezing it
early — an editable record of a day months gone.

WHAT IT MUST AND MUST NOT DO:

  freeze   an END_OF_DAY type, dated before today in NEW YORK, unlocked, and
           carrying an AFFIRMED signature
  flag     the same log with no affirmed signature — an unfinished obligation,
           not a document to seal
  ignore   everything else, and in particular TODAY's log, which the CP is
           still standing in the middle of
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server as S  # noqa: E402
from tests.source_text import code_of  # noqa: E402

_CODE = code_of("server.py")

AFFIRMED = {"affirmed": True, "affirmedAt": "2026-08-17T09:00:00Z"}
# The shape production actually held: signature-SHAPED, truthy, and nobody
# attested to anything.
EMPTY_SIG = {}


def _log(_id, log_type="daily_jobsite", date="2026-08-17", sig=None, **over):
    doc = {
        "_id": _id, "project_id": "p1", "company_id": "c1",
        "log_type": log_type, "date": date, "is_locked": False,
        "is_deleted": False, "cp_signature": sig,
    }
    doc.update(over)
    return doc


class _Coll:
    """Applies the sweep's own filter, so a test cannot pass by the fake being
    more permissive than Mongo."""

    def __init__(self, docs=None):
        self.docs = docs or []
        self.updates = []
        self.inserted = []

    def find(self, query=None):
        q = query or {}

        def keep(d):
            for k, v in q.items():
                if isinstance(v, dict):
                    if "$in" in v and d.get(k) not in v["$in"]:
                        return False
                    if "$lt" in v and not (str(d.get(k, "")) < v["$lt"]):
                        return False
                    if "$ne" in v and d.get(k) == v["$ne"]:
                        return False
                elif d.get(k) != v:
                    return False
            return True

        rows = [d for d in self.docs if keep(d)]

        class _Cur:
            async def to_list(self, n=None):
                return rows
        return _Cur()

    async def update_one(self, q, update):
        self.updates.append((q, update["$set"]))
        for d in self.docs:
            if d["_id"] == q.get("_id"):
                d.update(update["$set"])

    async def find_one(self, q=None, **k):
        def dig(doc, path):
            """Dotted paths, because the dedupe query uses `details.log_type`.
            A fake that ignored the dot would return None every time and the
            dedupe assertion would pass against a fake that cannot dedupe."""
            cur = doc
            for part in path.split("."):
                if not isinstance(cur, dict):
                    return None
                cur = cur.get(part)
            return cur

        for d in self.inserted:
            if all(dig(d, kk) == vv for kk, vv in (q or {}).items()):
                return d
        return None

    async def insert_one(self, doc):
        self.inserted.append(doc)


class _DB:
    def __init__(self, logs=None):
        self.logbooks = _Coll(logs)
        self.compliance_alerts = _Coll()


NOW = datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc)   # 3am ET on the 18th


def _run(db, now=NOW):
    return asyncio.run(S.sweep_stale_end_of_day_logs(db, now))


class ItFreezesSignedAndStale(unittest.TestCase):

    def test_a_signed_log_from_yesterday_is_frozen(self):
        db = _DB([_log("a", sig=AFFIRMED)])
        out = _run(db)
        self.assertEqual(out["frozen"], 1)
        self.assertIs(db.logbooks.docs[0]["is_locked"], True)
        self.assertEqual(db.logbooks.docs[0]["status"], "submitted")

    def test_it_records_who_closed_it(self):
        """A reader must never be left guessing whether a person closed the
        record. The CP's signature made it eligible; the sweep applied the
        lock, and both facts are on the document."""
        db = _DB([_log("a", sig=AFFIRMED)])
        _run(db)
        doc = db.logbooks.docs[0]
        self.assertEqual(doc["finalized_by"], "system:eod_sweep")
        self.assertEqual(doc["finalized_by_name"], "End-of-day sweep")
        self.assertIsNotNone(doc["finalized_at"])

    def test_both_end_of_day_types_are_swept(self):
        db = _DB([_log("a", sig=AFFIRMED),
                  _log("b", log_type="ssc_daily_safety_log", sig=AFFIRMED)])
        self.assertEqual(_run(db)["frozen"], 2)

    def test_the_type_list_comes_from_the_timing_table(self):
        """Not a hardcoded pair. A third END_OF_DAY type is swept with no
        change here — and an IMMEDIATE one never is, because its signature
        already froze it."""
        self.assertEqual(set(S.END_OF_DAY_LOG_TYPES),
                         {k for k, v in S.LOGBOOK_TIMING_CLASS.items()
                          if v == "end_of_day"})

    def test_it_is_idempotent(self):
        db = _DB([_log("a", sig=AFFIRMED)])
        self.assertEqual(_run(db)["frozen"], 1)
        self.assertEqual(_run(db)["frozen"], 0)


class ItLeavesEverythingElseAlone(unittest.TestCase):

    def test_TODAYS_log_is_untouched(self):
        """The CP is still standing in the middle of it. This is the case the
        Eastern date exists for."""
        db = _DB([_log("a", date="2026-08-18", sig=AFFIRMED)])
        self.assertEqual(_run(db)["frozen"], 0)
        self.assertIs(db.logbooks.docs[0]["is_locked"], False)

    def test_eastern_not_utc(self):
        """At 00:30 UTC on the 18th it is still 20:30 on the 17th in New York,
        so the 17th's log is TODAY'S and must not be swept. A UTC day boundary
        would freeze a record the CP is still writing. Thirteen instances of
        that bug have shipped on this project."""
        db = _DB([_log("a", date="2026-08-17", sig=AFFIRMED)])
        out = _run(db, datetime(2026, 8, 18, 0, 30, tzinfo=timezone.utc))
        self.assertEqual(out["frozen"], 0)
        self.assertIs(db.logbooks.docs[0]["is_locked"], False)

    def test_an_already_locked_log_is_not_re_frozen(self):
        db = _DB([_log("a", sig=AFFIRMED, is_locked=True)])
        self.assertEqual(_run(db)["frozen"], 0)
        self.assertEqual(db.logbooks.updates, [])

    def test_a_deleted_log_is_not_swept(self):
        db = _DB([_log("a", sig=AFFIRMED, is_deleted=True)])
        self.assertEqual(_run(db)["frozen"], 0)

    def test_an_immediate_type_is_never_swept(self):
        """Its signature already froze it; sweeping it would be a second
        authority over a record that is already closed."""
        db = _DB([_log("a", log_type="osha_log", sig=AFFIRMED)])
        self.assertEqual(_run(db)["frozen"], 0)


class AnUnsignedStaleLogIsFlaggedNeverSealed(unittest.TestCase):
    """A CP who signed and left is a different fact from a CP who never signed.
    Freezing the second seals a record nobody attested to."""

    def test_a_log_with_no_signature_is_not_frozen(self):
        db = _DB([_log("a", sig=None)])
        out = _run(db)
        self.assertEqual(out["frozen"], 0)
        self.assertEqual(out["unsigned"], 1)
        self.assertIs(db.logbooks.docs[0]["is_locked"], False)

    def test_an_EMPTY_signature_object_counts_as_unsigned(self):
        """`cp_signature: {}` is what production held — signature-shaped,
        truthy, and an attestation of nothing. The ruling that an unsigned log
        must not be sealed applies to it exactly."""
        db = _DB([_log("a", sig=EMPTY_SIG)])
        out = _run(db)
        self.assertEqual(out["frozen"], 0)
        self.assertEqual(out["unsigned"], 1)

    def test_it_errs_toward_NOT_locking(self):
        """Every shape that is not an affirmed signature is flagged rather than
        frozen. An unfrozen record can still be frozen later; a wrongly sealed
        one cannot be opened."""
        for sig in (None, {}, "data:image/png;base64,iVBOR", {"affirmed": False},
                    {"paths": [[{"x": 1}]]}):
            with self.subTest(sig=sig):
                db = _DB([_log("a", sig=sig)])
                self.assertEqual(_run(db)["frozen"], 0)

    def test_it_raises_a_compliance_alert(self):
        db = _DB([_log("a", sig=None)])
        _run(db)
        self.assertEqual(len(db.compliance_alerts.inserted), 1)
        alert = db.compliance_alerts.inserted[0]
        self.assertEqual(alert["alert_type"], "unsigned_stale_logbook")
        self.assertEqual(alert["details"]["log_type"], "daily_jobsite")
        self.assertEqual(alert["details"]["date"], "2026-08-17")
        self.assertIs(alert["resolved"], False)

    def test_the_alert_says_the_log_is_STILL_EDITABLE(self):
        """The whole point of flagging instead of freezing. An admin who reads
        it as "sealed unsigned" has been told the opposite of what happened."""
        db = _DB([_log("a", sig=None)])
        _run(db)
        self.assertIn("not frozen", db.compliance_alerts.inserted[0]["message"])

    def test_a_nightly_re_run_does_not_stack_duplicates(self):
        db = _DB([_log("a", sig=None)])
        _run(db)
        _run(db)
        self.assertEqual(len(db.compliance_alerts.inserted), 1)


class ItSurvivesBadInput(unittest.TestCase):
    """The nightly tick runs unattended. A sweep that threw would take the
    missing-logbook and deficiency detectors down with it."""

    def test_a_read_failure_returns_zeroes_rather_than_raising(self):
        class _Broken:
            def find(self, *a, **k):
                raise RuntimeError("mongo is down")

        class _DBBroken:
            logbooks = _Broken()
        self.assertEqual(_run(_DBBroken()), {"frozen": 0, "unsigned": 0})

    def test_one_bad_document_does_not_stop_the_rest(self):
        db = _DB([_log("a", sig=AFFIRMED), _log("b", sig=AFFIRMED)])
        calls = {"n": 0}
        real = db.logbooks.update_one

        async def flaky(q, u):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("write failed")
            return await real(q, u)
        db.logbooks.update_one = flaky
        self.assertEqual(_run(db)["frozen"], 1)


class ItIsWiredIntoTheNightlyTick(unittest.TestCase):

    def test_the_3am_tick_calls_it(self):
        """Here rather than a job of its own: this tick already runs at 3am ET,
        already iterates projects, and its own comment gives the reason for the
        hour — it runs after the 24h daily-log writing window closes, which is
        exactly the window a freeze must not run inside."""
        self.assertIn("_swept = await sweep_stale_end_of_day_logs(db)", _CODE)
        tick = _CODE[_CODE.index("async def _logbook_nightly_tick"):]
        tick = tick[:tick.index("scheduler.add_job")]
        self.assertIn("sweep_stale_end_of_day_logs", tick)

    def test_the_hour_is_unchanged(self):
        self.assertIn('CronTrigger(hour=3, minute=0, timezone="America/New_York")',
                      _CODE)

    def test_the_editors_no_longer_finalize_on_a_signature(self):
        """The other half. Without it the sweep would be closing a record the
        client had already closed, and END_OF_DAY would still mean nothing."""
        for screen in ("daily_jobsite", "ssc_daily_safety_log"):
            src = code_of(f"frontend/app/logbooks/{screen}.jsx")
            with self.subTest(screen=screen):
                self.assertNotIn("logbooksAPI.finalize(", src)
                # AND NOT THE LOCAL FREEZE EITHER. Checking only the server
                # call left a mutation alive: re-adding markFinalized alone
                # froze the draft on the device while the server waited for
                # the sweep, so the CP could not add the afternoon and the
                # sweep would find a record it had no part in closing.
                # Scoped to the signature path — markFinalized still appears
                # in fetchData, where a log the SERVER reports as locked is
                # mirrored onto the device. That is reading a freeze, not
                # applying one.
                sign = src[src.index("const persistAndPush"):]
                self.assertNotIn("markFinalized(_key)", sign)


if __name__ == "__main__":
    unittest.main()
