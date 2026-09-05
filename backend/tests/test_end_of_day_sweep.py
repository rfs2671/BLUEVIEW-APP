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


def _sortable(v):
    """A TOTAL order over the values these documents actually carry.

    `date` is a string and `_id` may be a string or an ObjectId, and Python
    refuses to compare across types. Mongo would sort by type bracket and then
    by value; this keeps the same two properties that matter to a paged walk —
    it is total, and it is stable across calls.
    """
    return (v is None, type(v).__name__, str(v))


class _Coll:
    """Applies the sweep's own filter, so a test cannot pass by the fake being
    more permissive than Mongo.

    AND ITS OWN LIMIT. `to_list(n)` used to ignore `n` and hand back every
    matching row, which is the one way this fake WAS more permissive than
    Mongo — and it hid the exact defect the sweep shipped with: an unsorted
    `to_list(1000)` over a selector that stranded rows never leave. Every
    truncation test in this file would have passed against a driver that
    silently dropped the 1001st document. It honours `n`, `skip` and `limit`
    now, so a capped read is visible as a capped read.
    """

    def __init__(self, docs=None):
        self.docs = docs or []
        self.updates = []
        self.inserted = []
        # What the sweep asked to be sorted by, in the order it asked. Recorded
        # rather than asserted here so a test can name the sort key.
        self.sorts = []
        # (skip, limit) per page, so the paging walk is observable.
        self.pages = []

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
        coll = self

        class _Cur:
            def __init__(self):
                self.rows = rows
                self.n_skip = 0
                self.n_limit = None

            def sort(self, spec):
                # Motor/pymongo's list-of-pairs form. Applied right to left so
                # the FIRST pair is the primary key — the same precedence Mongo
                # gives it.
                coll.sorts.append(list(spec))
                for key, direction in reversed(list(spec)):
                    self.rows = sorted(
                        self.rows,
                        key=lambda d, _k=key: _sortable(d.get(_k)),
                        reverse=(direction < 0),
                    )
                return self

            def skip(self, n):
                self.n_skip = int(n or 0)
                return self

            def limit(self, n):
                self.n_limit = int(n or 0) or None
                return self

            async def to_list(self, n=None):
                cap = self.n_limit
                if n is not None:
                    cap = n if cap is None else min(cap, n)
                coll.pages.append((self.n_skip, cap))
                out = self.rows[self.n_skip:]
                return out if cap is None else out[:cap]
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


class AResolvedAlertMustBeContradictableTomorrow(unittest.TestCase):
    """THE DEDUPE KEY OMITTED `resolved`, SO RESOLVING DESTROYED THE RECORD.

    (project, log_type, date) alone matches a RESOLVED row as readily as an
    open one. An admin who resolved the alert — the one action the screen
    offers — permanently suppressed it while the log stayed stranded and
    stayed unfrozen. Resolving destroyed the only surviving statement that the
    log needed fixing.

    THE SELECTOR RE-VERIFIES THE CONDITION EVERY NIGHT, which is what makes
    re-raising honest rather than noise: this sweep only reaches a log that is
    STILL unaffirmed and STILL unfrozen. The moment the CP affirms, the log is
    frozen and leaves the selector for good, and no further alert is raised. So
    a re-raised row is not a duplicate of a handled fact — it is a fresh
    statement that the fact has not changed.

    The same rule is already written a few thousand lines down for
    worker_cert_expiring, with its reasoning: "without it, an admin who
    resolves an alert ... gets a fresh one that same night, and 'resolved'
    decays into 'cleared for one night'". THERE the suppression test is the
    expiry date, because the alert's condition (30 days out) does not change
    when the admin acts. HERE the condition is the log's own state, and the
    admin resolving the row does not change it.
    """

    def test_a_resolved_alert_does_not_suppress_a_still_stranded_log(self):
        db = _DB([_log("a", sig=None)])
        _run(db)
        self.assertEqual(len(db.compliance_alerts.inserted), 1)
        # The one action the admin screen offers.
        db.compliance_alerts.inserted[0]["resolved"] = True
        _run(db)
        self.assertEqual(
            len(db.compliance_alerts.inserted), 2,
            "resolving must not be able to erase a log that is still stranded",
        )
        self.assertIs(db.compliance_alerts.inserted[1]["resolved"], False)

    def test_the_re_raised_row_is_then_deduped_like_any_other(self):
        """One resolve, one new row — not one per night thereafter."""
        db = _DB([_log("a", sig=None)])
        _run(db)
        db.compliance_alerts.inserted[0]["resolved"] = True
        _run(db)
        _run(db)
        _run(db)
        self.assertEqual(len(db.compliance_alerts.inserted), 2)

    def test_the_dedupe_query_names_resolved(self):
        """Asserted on the QUERY as well as the behaviour: the fake dedupes on
        equality, so a future widening that matched resolved rows again would
        have to change this line too."""
        db = _DB([_log("a", sig=None)])
        seen = []
        real = db.compliance_alerts.find_one

        async def spy(q=None, **k):
            seen.append(q)
            return await real(q, **k)
        db.compliance_alerts.find_one = spy
        _run(db)
        self.assertTrue(seen)
        self.assertIs(seen[0].get("resolved"), False)


# NOW is 07:00Z on the 18th = 3am ET. AFFIRMED above is stamped 09:00Z on the
# 17th, which is 22 hours earlier — a signature made in the MORNING of the day
# the log describes, left unfrozen through that whole working day and the
# evening after it.
SIGNED_AT_END_OF_HIS_DAY = {"affirmed": True, "affirmedAt": "2026-08-18T00:30:00Z"}
# 8:30pm ET on the 17th: the ordinary END_OF_DAY case. Six and a half hours
# before the sweep, and nothing is wrong with it.


class ItRecordsAFreezeNobodyElseApplied(unittest.TestCase):
    """THE SWEEP IS THE ONLY WITNESS TO ITS OWN BACKSTOP FIRING.

    Two amendments to the same log, the same day, the same CP: one locked one
    second after its signature via /finalize (`finalized_by` = the user), the
    other waited nineteen hours for this sweep (`finalized_by_name` = "End-of-
    day sweep"). Both are frozen and both look identical on the logbook list.
    NOTHING ON EITHER SIDE RECORDED WHICH — the divergence is only visible if
    somebody thinks to compare `finalized_by` across two rows.

    draftSync's applyRemoteFreeze is where the client half is fixed. This is
    the half that CANNOT BE REVERTED BY AN EDITOR CHANGE: it reads the
    document, so a client that quietly stops applying the freeze is observed
    from the outside rather than trusted to report on itself.

    IT MUST NOT FIRE ON THE ORDINARY CASE. An END_OF_DAY log is supposed to be
    signed and left open — that is the class. A CP who signs at 8:30pm and is
    swept at 3am has done nothing wrong, and an alert on him buries the real
    signal.
    """

    def test_a_log_signed_the_morning_before_raises_the_alert(self):
        db = _DB([_log("a", sig=AFFIRMED)])
        out = _run(db)
        self.assertEqual(out["frozen"], 1)
        self.assertEqual(out["late_freeze"], 1)
        alert = db.compliance_alerts.inserted[0]
        self.assertEqual(alert["alert_type"], "client_freeze_never_arrived")
        self.assertEqual(alert["details"]["log_type"], "daily_jobsite")
        self.assertEqual(alert["details"]["date"], "2026-08-17")
        self.assertEqual(alert["details"]["logbook_id"], "a")
        self.assertEqual(alert["details"]["hours_unfrozen"], 22)
        self.assertIs(alert["resolved"], False)

    def test_it_still_freezes_the_log(self):
        """The alert is an observation about the freeze, never a substitute for
        it. A detector that stopped the backstop would be worse than no
        detector."""
        db = _DB([_log("a", sig=AFFIRMED)])
        _run(db)
        self.assertIs(db.logbooks.docs[0]["is_locked"], True)
        self.assertEqual(db.logbooks.docs[0]["finalized_by"], "system:eod_sweep")

    def test_an_end_of_day_signature_raises_nothing(self):
        db = _DB([_log("a", sig=SIGNED_AT_END_OF_HIS_DAY)])
        out = _run(db)
        self.assertEqual(out["frozen"], 1)
        self.assertEqual(out["late_freeze"], 0)
        self.assertEqual(db.compliance_alerts.inserted, [])

    def test_an_unsigned_stale_log_raises_only_the_unsigned_alert(self):
        """The two detectors describe different obligations and must not both
        speak about one document. An unsigned log owes no freeze at all."""
        db = _DB([_log("a", sig=None), _log("b", sig=EMPTY_SIG)])
        out = _run(db)
        self.assertEqual(out["late_freeze"], 0)
        self.assertEqual(
            {a["alert_type"] for a in db.compliance_alerts.inserted},
            {"unsigned_stale_logbook"},
        )

    def test_a_signature_with_no_parseable_stamp_raises_nothing(self):
        """The alert's entire content is an elapsed time. Raised on a signature
        nobody can date, it would assert a number it invented."""
        for sig in ({"affirmed": True},
                    {"affirmed": True, "affirmedAt": "not a date"},
                    {"affirmed": True, "affirmedAt": None, "timestamp": ""}):
            with self.subTest(sig=sig):
                db = _DB([_log("a", sig=sig)])
                out = _run(db)
                self.assertEqual(out["frozen"], 1, "it is still frozen")
                self.assertEqual(out["late_freeze"], 0)
                self.assertEqual(db.compliance_alerts.inserted, [])

    def test_it_falls_back_to_timestamp_when_affirmedAt_is_absent(self):
        """The same two fields in the same order ensure_signature_ledger_row
        reads, so the two never disagree about when a signature happened."""
        db = _DB([_log("a", sig={"affirmed": True,
                                 "timestamp": "2026-08-17T09:00:00Z"})])
        self.assertEqual(_run(db)["late_freeze"], 1)

    def test_a_re_run_does_not_stack_duplicates(self):
        """Normally unreachable — the freeze removes the document from the
        selector for good — so this pins the dedupe for the one path that CAN
        re-visit it: a freeze write that raised."""
        db = _DB([_log("a", sig=AFFIRMED)])
        real = db.logbooks.update_one

        async def boom(q, u):
            raise RuntimeError("write refused")
        db.logbooks.update_one = boom
        self.assertEqual(_run(db)["late_freeze"], 1)
        self.assertEqual(_run(db)["late_freeze"], 0)
        db.logbooks.update_one = real
        self.assertEqual(len(db.compliance_alerts.inserted), 1)

    def test_a_resolved_alert_does_not_suppress_a_re_verified_one(self):
        """The `resolved: False` clause, for the same reason
        _flag_unsigned_stale_log carries it: resolve is the only action the
        admin screen offers, and without this it erases the record instead of
        closing it."""
        db = _DB([_log("a", sig=AFFIRMED)])

        async def boom(q, u):
            raise RuntimeError("write refused")
        db.logbooks.update_one = boom
        _run(db)
        db.compliance_alerts.inserted[0]["resolved"] = True
        _run(db)
        self.assertEqual(len(db.compliance_alerts.inserted), 2)
        self.assertIs(db.compliance_alerts.inserted[1]["resolved"], False)

    def test_the_dedupe_query_names_resolved(self):
        db = _DB([_log("a", sig=AFFIRMED)])
        seen = []
        real = db.compliance_alerts.find_one

        async def spy(q=None, **k):
            seen.append(q)
            return await real(q, **k)
        db.compliance_alerts.find_one = spy
        _run(db)
        self.assertTrue(seen)
        self.assertIs(seen[0].get("resolved"), False)
        self.assertEqual(seen[0]["alert_type"], "client_freeze_never_arrived")

    def test_it_cannot_stop_the_freeze(self):
        """It is a detector bolted to a backstop. If the alert write fails, the
        lock still has to land."""
        db = _DB([_log("a", sig=AFFIRMED)])

        async def boom(doc):
            raise RuntimeError("alerts unreachable")
        db.compliance_alerts.insert_one = boom
        out = _run(db)
        self.assertEqual(out["frozen"], 1)
        self.assertEqual(out["late_freeze"], 0)
        self.assertIs(db.logbooks.docs[0]["is_locked"], True)

    def test_it_uses_the_runs_own_clock_not_the_wall_clock(self):
        """`now` already decides which day is stale. Reading the wall clock for
        the elapsed-time half would make one sweep disagree with itself about
        when it is happening — and would fire on every log in this file the
        moment the suite is run on a later date."""
        db = _DB([_log("a", sig=AFFIRMED)])
        # Seventeen hours after the signature: inside the window.
        out = _run(db, now=datetime(2026, 8, 18, 2, 0, tzinfo=timezone.utc))
        self.assertEqual(out["late_freeze"], 0)


class TheVisitClassIsOutOfThisSweepsReach(unittest.TestCase):
    """SAID OUT LOUD RATHER THAN LEFT TO BE INFERRED.

    site_superintendent_log is a VISIT log and is not in END_OF_DAY_LOG_TYPES,
    so this sweep never returns one and the late-freeze detector is never
    called for one. That exclusion is deliberate upstream — an overnight sweep
    must not freeze a visit its author has not finished — and it means the
    VISIT version of this defect is INVISIBLE here, and is the worse version:
    there is no second actor at all, so a freeze the client skips is applied by
    nothing and the log stays editable and unlocked while the screen shows it
    signed.

    The detector's docstring has to SAY that rather than imply coverage it does
    not have, which is why the sentence is asserted and not just the behaviour.
    """

    def test_a_visit_log_is_neither_frozen_nor_alerted_on(self):
        db = _DB([_log("v", log_type="site_superintendent_log", sig=AFFIRMED)])
        out = _run(db)
        self.assertEqual(out, {"frozen": 0, "unsigned": 0, "late_freeze": 0})
        self.assertIs(db.logbooks.docs[0]["is_locked"], False)
        self.assertEqual(db.compliance_alerts.inserted, [])

    def test_the_detector_admits_it_does_not_cover_the_visit_class(self):
        # raw=True on purpose, and source_text.py names this as the one case
        # that earns it: the assertion IS about the prose. A detector whose
        # docstring quietly implies it watches all three timing classes is the
        # same defect as the comment this branch exists to correct.
        raw = code_of("server.py", raw=True)
        fn = raw[raw.index("async def _flag_late_client_freeze"):]
        fn = fn[:fn.index("\n    try:")]
        # Whitespace-collapsed: the sentence is wrapped to 79 columns, so a
        # literal match would pin the line breaks rather than the claim.
        flat = " ".join(fn.split())
        self.assertIn("DOES NOT COVER THE VISIT CLASS", flat)
        self.assertIn("site_superin", flat)
        self.assertIn("there is no second actor at all", flat)


class ItPagesRatherThanTruncating(unittest.TestCase):
    """A TIME BOMB WITH NO SYMPTOM.

    The read was `cursor.to_list(1000)` — UNSORTED, and capped. A log that
    fails the per-document affirmed test is flagged and LEFT IN PLACE, so it
    matches the selector again the next night, and the night after, forever.
    Sixty-five such rows exist today.

    At a thousand accumulated strandings the cap is reached by stranded rows
    alone, and correctly signed logs stop being frozen. Nothing raises, nothing
    logs, the job reports success, and end-of-day logs simply stop locking.

    THE SORT IS OLDEST FIRST — `date` ascending, `_id` ascending to break the
    ties, which is what makes it a TOTAL order and therefore a page boundary
    that means something. Two reasons for the direction: the oldest stale log
    has been unfrozen longest and is the one nearest a records request, and if
    a walk is ever cut short — the page ceiling below, a crash, a restart —
    the documents it did not reach are the newest, which are the least exposed
    and are re-swept the following night anyway.
    """

    def test_a_thousand_signed_logs_do_not_stop_the_walk(self):
        db = _DB([_log(f"s{i:05d}", sig=AFFIRMED) for i in range(1200)])
        self.assertEqual(_run(db)["frozen"], 1200)

    def test_stranded_rows_cannot_crowd_out_a_signed_log(self):
        """THE FAILURE ITSELF. A thousand stranded rows are older than
        yesterday's signed narratives — they accumulated — so they sit at the
        head of the walk under ANY honest ordering. Only exhausting the pages
        reaches the signed ones behind them.

        Pre-fix this froze 0 of 5 and reported success."""
        stranded = [_log(f"u{i:05d}", date="2026-07-01", sig=EMPTY_SIG)
                    for i in range(1000)]
        signed = [_log(f"s{i}", date="2026-08-17", sig=AFFIRMED) for i in range(5)]
        db = _DB(stranded + signed)
        out = _run(db)
        self.assertEqual(out["unsigned"], 1000)
        self.assertEqual(
            out["frozen"], 5,
            "a signed log must be frozen no matter how many stranded rows "
            "precede it",
        )

    def test_it_sorts_oldest_first_on_a_total_order(self):
        db = _DB([_log("a", sig=AFFIRMED)])
        _run(db)
        self.assertTrue(db.logbooks.sorts, "the read is sorted")
        self.assertEqual(db.logbooks.sorts[0], [("date", 1), ("_id", 1)])

    def test_every_page_is_bounded(self):
        """Paging, not an unbounded slurp: a nightly job that materialised
        every stale log at once would be one OOM away from the same silence."""
        db = _DB([_log(f"s{i:05d}", sig=AFFIRMED) for i in range(1200)])
        _run(db)
        self.assertTrue(db.logbooks.pages)
        for skip, cap in db.logbooks.pages:
            self.assertIsNotNone(cap, "a page with no limit is not a page")
            self.assertLessEqual(cap, S._EOD_SWEEP_PAGE)

    def test_the_walk_terminates_when_nothing_can_be_frozen(self):
        """THE GUARD AGAINST RUNNING FOREVER, and the reason it is needed: a
        stranded row does not leave the selector, so a walk that re-read from
        the start would re-read the same page forever. The offset carries past
        exactly the documents left behind, so each page visits documents no
        page has visited, and the walk ends after ceil(N / page) reads."""
        db = _DB([_log(f"u{i:04d}", sig=EMPTY_SIG) for i in range(1100)])
        out = _run(db)
        self.assertEqual(out["unsigned"], 1100)
        self.assertEqual(out["frozen"], 0)
        self.assertLessEqual(len(db.logbooks.pages), 1100 // S._EOD_SWEEP_PAGE + 2)

    def test_a_page_ceiling_stops_a_pathological_run_LOUDLY(self):
        """The ceiling is a backstop, not the design — but if it is ever hit
        the job must say so. Silence is the defect being fixed here; a second
        silent cap in its place would be the same bug wearing a page size."""
        db = _DB([_log(f"u{i:05d}", sig=EMPTY_SIG)
                  for i in range(S._EOD_SWEEP_PAGE * 3)])
        with patch.object(S, "_EOD_SWEEP_MAX_PAGES", 2), \
                patch.object(S, "logger") as log:
            out = _run(db)
        self.assertEqual(out["unsigned"], S._EOD_SWEEP_PAGE * 2)
        self.assertTrue(log.error.called, "hitting the ceiling is reported")
        self.assertIn("eod-freeze", str(log.error.call_args))

    def test_the_read_is_no_longer_a_bare_to_list_1000(self):
        """The literal that was the bomb. Named so a revert is legible."""
        src = _CODE[_CODE.index("async def sweep_stale_end_of_day_logs"):]
        src = src[:src.index("async def _flag_unsigned_stale_log")]
        self.assertNotIn("to_list(1000)", src)


class ItSurvivesBadInput(unittest.TestCase):
    """The nightly tick runs unattended. A sweep that threw would take the
    missing-logbook and deficiency detectors down with it."""

    def test_a_read_failure_returns_zeroes_rather_than_raising(self):
        class _Broken:
            def find(self, *a, **k):
                raise RuntimeError("mongo is down")

        class _DBBroken:
            logbooks = _Broken()
        self.assertEqual(_run(_DBBroken()),
                         {"frozen": 0, "unsigned": 0, "late_freeze": 0})

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
