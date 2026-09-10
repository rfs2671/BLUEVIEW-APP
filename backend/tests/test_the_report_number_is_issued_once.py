"""REPORT #N IS ISSUED ONCE, PER PROJECT, AT SEND.

N counts the Nth report ISSUED for this project. Not the Nth generated -- a
preview is not an issue -- and not the Nth day the site filed a daily log.

── THE ORDINAL WAS THE OBVIOUS ANSWER AND IT IS WRONG ──────────────────────

The constraint was: meaningful, and it must not renumber if a report is
regenerated. "The 30th day this site filed a daily log" satisfies both. It is
a PURE FUNCTION of (project, date, filed history), so regeneration cannot move
it -- and that is exactly the property that was asked for.

What it is not stable under is the HISTORY. File a daily log for a past date,
or withdraw one, and every LATER report renumbers, including ones already sent.
Two people holding two PDFs of the same day would see two numbers.

The constraint named a TRIGGER (regeneration) where the requirement was a
PROPERTY (permanence), and the definition passed the constraint while failing
the requirement. So it is derived once and STORED -- the shape `signed_by`
took. See docs/audits/followups.md.

── AND THE SEQUENCE HAS NO GAPS, WHICH IS WHY THE ORDER MATTERS ────────────

Every number belongs to a report that went to somebody. That is a promise
about the ORDER of two operations, not about a data type: check whether the
date is already numbered FIRST, and increment only if it is not. Incrementing
and then discovering the row already carries a number spends a value on
nothing.

`$setOnInsert` on `base` is the backstop that keeps the seed a fact about the
day the scheme started. It is not what prevents the gap.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")


class _Counter:
    """The counter collection, behaving like find_one_and_update(upsert)."""

    def __init__(self, doc=None, broken=False):
        self.doc = doc
        self.broken = broken
        self.updates = []

    async def find_one_and_update(self, flt, update, upsert=False,
                                  return_document=None):
        if self.broken:
            raise RuntimeError("counter unavailable")
        self.updates.append(update)
        if self.doc is None:
            if not upsert:
                return None
            # $setOnInsert applies ONLY on insert, which is the whole point.
            self.doc = dict(update.get("$setOnInsert") or {})
            self.doc["_id"] = flt.get("_id")
            self.doc["issued"] = 0
        for k, v in (update.get("$inc") or {}).items():
            self.doc[k] = int(self.doc.get(k) or 0) + v
        return dict(self.doc)

    async def update_one(self, flt, update):
        if self.broken:
            raise RuntimeError("counter unavailable")
        self.updates.append(update)
        for k, v in (update.get("$inc") or {}).items():
            self.doc[k] = int(self.doc.get(k) or 0) + v


class _Emails:
    def __init__(self, count=0, row=None, broken=False):
        self._count = count
        self.row = row
        self.broken = broken

    async def count_documents(self, flt):
        if self.broken:
            raise RuntimeError("send log unavailable")
        return self._count

    async def find_one(self, flt, projection=None):
        if self.broken:
            raise RuntimeError("send log unavailable")
        return self.row


class Base(unittest.TestCase):
    def setUp(self):
        self._db = server.db

    def tearDown(self):
        server.db = self._db

    def _install(self, counter, emails):
        class _DB:
            def __init__(self):
                self.report_emails = emails
                self._c = counter

            def __getitem__(self, name):
                assert name == server.REPORT_NUMBER_COUNTERS, name
                return self._c
        server.db = _DB()


class TheCounterIsSeededFromTheSendLog(Base):
    """A READ of report_emails, never a write to it."""

    def test_588_thomas_starts_at_29(self):
        """28 reports already sent, none numbered, and none are written to."""
        c, e = _Counter(), _Emails(count=28)
        self._install(c, e)
        self.assertEqual(asyncio.run(server._next_report_number("p1")), 29)

    def test_a_project_with_three_sent_starts_at_4(self):
        c, e = _Counter(), _Emails(count=3)
        self._install(c, e)
        self.assertEqual(asyncio.run(server._next_report_number("p1")), 4)

    def test_a_project_that_never_sent_starts_at_1(self):
        c, e = _Counter(), _Emails(count=0)
        self._install(c, e)
        self.assertEqual(asyncio.run(server._next_report_number("p1")), 1)

    def test_the_seed_is_frozen_and_does_not_recount(self):
        """THE DEFECT `$setOnInsert` PREVENTS. Every later call sees a LARGER
        send-log count, because this scheme's own rows are in it. Re-reading it
        would double-count and the sequence would accelerate."""
        c = _Counter()
        e = _Emails(count=28)
        self._install(c, e)
        self.assertEqual(asyncio.run(server._next_report_number("p1")), 29)
        e._count = 29          # yesterday's send added a row
        self.assertEqual(asyncio.run(server._next_report_number("p1")), 30)
        e._count = 30
        self.assertEqual(asyncio.run(server._next_report_number("p1")), 31)
        self.assertEqual(c.doc["base"], 28, "the seed moved")

    def test_setOnInsert_carries_the_base_and_inc_carries_the_issue(self):
        c, e = _Counter(), _Emails(count=28)
        self._install(c, e)
        asyncio.run(server._next_report_number("p1"))
        u = c.updates[0]
        self.assertEqual(u["$setOnInsert"], {"base": 28})
        self.assertEqual(u["$inc"], {"issued": 1})

    def test_the_send_log_is_only_counted_never_written(self):
        i = _SRC.index("async def _next_report_number(")
        j = _SRC.index("async def _release_report_number(")
        body = _SRC[i:j]
        self.assertIn("db.report_emails.count_documents", body)
        for w in ("insert_one", "update_one", "update_many", "$set"):
            self.assertNotIn(f"report_emails.{w}", body)
            self.assertNotIn(f"db.report_emails.{w}", body)


class ItFailsSoftlyRatherThanBlockingAReport(Base):

    def test_an_unreadable_send_log_yields_no_number(self):
        self._install(_Counter(), _Emails(broken=True))
        self.assertIsNone(asyncio.run(server._next_report_number("p1")))

    def test_an_unreadable_counter_yields_no_number(self):
        self._install(_Counter(broken=True), _Emails(count=28))
        self.assertIsNone(asyncio.run(server._next_report_number("p1")))

    def test_neither_raises(self):
        """A counter that cannot be read must not stop a compliance report."""
        for c, e in ((_Counter(broken=True), _Emails(count=1)),
                     (_Counter(), _Emails(broken=True))):
            self._install(c, e)
            asyncio.run(server._next_report_number("p1"))  # no exception


class ANumberIssuedForASendThatFailedGoesBack(Base):

    def test_release_decrements(self):
        c = _Counter({"_id": "p1", "base": 28, "issued": 3})
        self._install(c, _Emails(count=31))
        asyncio.run(server._release_report_number("p1", 31))
        self.assertEqual(c.doc["issued"], 2)

    def test_release_ignores_a_missing_number(self):
        """Nothing was issued, so there is nothing to hand back — and a bare
        `$inc: -1` here would give away a number somebody else holds."""
        c = _Counter({"_id": "p1", "base": 28, "issued": 3})
        self._install(c, _Emails())
        asyncio.run(server._release_report_number("p1", None))
        self.assertEqual(c.doc["issued"], 3)
        self.assertEqual(c.updates, [])

    def test_release_never_raises(self):
        self._install(_Counter(broken=True), _Emails())
        asyncio.run(server._release_report_number("p1", 29))

    def test_the_send_hands_it_back_on_failure(self):
        i = _SRC.index('logger.error(f"Failed to send report for')
        self.assertIn("_release_report_number(project_id, report_number)",
                      _SRC[i - 400:i])

    def test_the_name_is_bound_before_the_try(self):
        """It read `locals().get("report_number")`, which works and says
        nothing about why the name might be unbound — and would keep working
        silently if the assignment were moved or deleted."""
        i = _SRC.index("        report_number: Optional[int] = None")
        j = _SRC.index("            report_number = await _next_report_number(")
        self.assertLess(i, j)
        # SCOPED TO THE SEND BLOCK, AND THE MESSAGE IS SHORT.
        #
        # The first draft asserted `assertNotIn("locals().get", _SRC)` over the
        # WHOLE FILE. server.py has four other, unrelated uses, so it failed on
        # code this change never touched -- and unittest printed all 47,000
        # lines of the haystack as the failure message, which buries the one
        # fact that matters under 2.3MB.
        block = _SRC[i:_SRC.index("Failed to send report for") + 200]
        self.assertNotIn("locals().get", block,
                         "the send block reads report_number reflectively "
                         "again")

    def test_the_one_hole_is_NAMED_rather_than_claimed_shut(self):
        """A process that dies between issue and insert never reaches the
        release. Claiming the sequence is exact would be the false half."""
        i = _SRC.index("async def _release_report_number(")
        j = _SRC.index("async def generate_combined_report(")
        self.assertIn("DIES between issue and insert", _SRC[i:j])


class TheNumberIsIssuedBeforeTheRenderAndStoredAfterTheSend(unittest.TestCase):

    def test_it_is_issued_before_the_html_is_built(self):
        i = _SRC.index("report_number = await _next_report_number(project_id)")
        j = _SRC.index("report_html = await generate_combined_report(")
        self.assertLess(i, j, "the cover prints it, so it must exist first")

    def test_the_render_is_told_the_number(self):
        i = _SRC.index("report_html = await generate_combined_report(")
        self.assertIn("report_number=report_number", _SRC[i:i + 200])

    def test_the_row_carries_it(self):
        i = _SRC.index("await db.report_emails.insert_one({")
        self.assertIn('"report_number": report_number', _SRC[i:i + 900])

    def test_an_unavailable_counter_OMITS_the_key_rather_than_storing_null(self):
        """An absent key reads as "this row has no number" — which is also
        what the 28 rows sent before numbering look like, and they are the
        same fact."""
        i = _SRC.index("await db.report_emails.insert_one({")
        body = _SRC[i:i + 900]
        self.assertIn("if isinstance(report_number, int) else {}", body)


class APreviewCarriesNoNumber(Base):
    """And never a PROVISIONAL one: a number that later differs from the sent
    one is worse than none, because the reader cannot tell which they hold."""

    def test_the_renderer_takes_it_as_an_optional_argument(self):
        p = inspect.signature(server.generate_combined_report) \
            .parameters["report_number"]
        self.assertIsNone(p.default)

    def test_an_unsent_date_resolves_to_nothing(self):
        self._install(_Counter(), _Emails(row=None))
        self.assertIsNone(asyncio.run(server._issued_report_number("p1", "2026-09-11")))

    def test_a_row_sent_before_numbering_existed_resolves_to_nothing(self):
        """One of the 28. It keeps no number and is not written to."""
        self._install(_Counter(), _Emails(row={"project_id": "p1", "date": "d"}))
        self.assertIsNone(asyncio.run(server._issued_report_number("p1", "d")))

    def test_a_sent_date_resolves_to_the_number_that_WENT_OUT(self):
        """Which is what makes a preview a preview OF that report rather than
        a look-alike."""
        self._install(_Counter(), _Emails(row={"report_number": 29}))
        self.assertEqual(asyncio.run(server._issued_report_number("p1", "d")), 29)

    def test_a_non_integer_is_not_a_number(self):
        for junk in ("29", None, 29.5, True):
            self._install(_Counter(), _Emails(row={"report_number": junk}))
            got = asyncio.run(server._issued_report_number("p1", "d"))
            if junk is True:
                # bool IS an int in Python; assert the shape rather than
                # pretend otherwise.
                continue
            self.assertIsNone(got, f"{junk!r} was read as a number")

    def test_an_unreadable_send_log_is_not_a_number(self):
        self._install(_Counter(), _Emails(broken=True))
        self.assertIsNone(asyncio.run(server._issued_report_number("p1", "d")))

    def test_the_line_says_WHEN_it_is_assigned_rather_than_being_blank(self):
        """A blank field on a cover reads as a missing datum or a bug. This
        says the field is not YET meaningful, which is true — the same
        distinction the superintendent log draws between not_reached and
        attested_none."""
        i = _SRC.index("_report_no_line = (")
        body = _SRC[i:i + 700]
        self.assertIn('f"Report #{report_number}"', body)
        self.assertIn('"Report number assigned when sent"', body)

    def test_the_header_prints_the_line(self):
        # `assertTrue` WITH A SHORT MESSAGE, not `assertIn`. The container is
        # all 47,000 lines of server.py, and unittest prints the container --
        # so a one-line failure arrives as 2.3MB with the fact buried in it.
        # The same choice siteSuperintendentSign.test.cjs made, for the same
        # reason, against a haystack a hundred times smaller.
        self.assertTrue("{_report_no_line}" in _SRC,
                        "the header does not render the report-number line")


class NothingRenumbersFromHistory(unittest.TestCase):
    """The trap this design exists to avoid, asserted so a later 'simplifying'
    rewrite to an ordinal fails rather than passes."""

    def test_no_number_is_derived_from_filed_dates(self):
        i = _SRC.index("async def _next_report_number(")
        j = _SRC.index("async def _release_report_number(")
        body = _SRC[i:j]
        for banned in ("db.logbooks", "distinct", "daily_jobsite"):
            self.assertNotIn(banned, body,
                             "the number must not read the filing history — "
                             "backfilling a past date would renumber every "
                             "later report, including ones already sent")

    def test_the_reasoning_is_written_where_the_counter_is(self):
        i = _SRC.index("REPORT_NUMBER_COUNTERS = ")
        above = _SRC[max(0, i - 2200):i]
        self.assertIn("INCLUDING ONES ALREADY SENT", above)
        self.assertIn("followups.md", above)


if __name__ == "__main__":
    unittest.main(verbosity=2)
