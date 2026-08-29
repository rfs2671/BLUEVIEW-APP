"""The report preview panel stops reading a collection nobody writes.

"Subs 0" on 588 Thomas on 2026-08-28, with sixteen men from five companies
through the gate that morning.

IT WAS NOT ONE FIELD. get_report_preview read `db.daily_logs` -- 92 rows, every
one written in April 2026 by the operator's own kiosk testing, nothing since --
so `find_one` returned None on every request and FIVE fields on that panel were
constants:

    subcontractor_count      0
    daily_log_worker_count   0
    has_daily_log            false
    daily_log_status         null
    daily_log_weather        null

Same collection, same mistake, same fix as the 285 false compliance flags
(#295). `daily_jobsite_filter` is the single definition of the filed daily
record, so this panel and the detectors cannot drift apart again.

COMPANIES, NOT SUBCONTRACTORS. The gate records no GC flag -- nothing on a
check-in row distinguishes a general contractor's own crew from a sub's -- so
the number the data can honestly produce is distinct companies at the gate.
Naming it subcontractors would put the GC's own men in a subcontractor
headcount, which is a different kind of wrong from a miscount.

THE WORKER COUNT IS DELIBERATELY NOT FROM THE GATE. It renders on the
daily-log row beside that log's status, so it must be what that log CLAIMS.
as_daily_log_row makes the same call for the same stated reason.
"""

import ast
import asyncio
import inspect
import os
import sys
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402
from lib.logbook.daily_jobsite_source import daily_jobsite_filter  # noqa: E402


def _code_only(fn) -> str:
    """A function's CODE, with docstring and comments removed.

    Five text-search assertions this session matched the very prose explaining
    the thing they forbid. ast.unparse drops comments; the docstring is dropped
    explicitly. What is left is only what runs.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)):
        node.body = node.body[1:]
    return ast.unparse(node)


PREVIEW = _code_only(server.get_report_preview)


class ItNoLongerReadsTheDeadCollection(unittest.TestCase):
    def test_the_panel_does_not_touch_daily_logs(self):
        self.assertNotIn("db.daily_logs", PREVIEW)

    def test_it_reads_the_filed_daily_jobsite_logbook_instead(self):
        self.assertIn("daily_jobsite_filter", PREVIEW)
        self.assertIn("as_daily_log_row", PREVIEW)

    def test_it_uses_the_shared_definition_rather_than_its_own_query(self):
        """A second hand-written copy of the filter is how the detectors and
        this panel would drift apart again."""
        for clause in ("'log_type': 'daily_jobsite'", '"log_type": "daily_jobsite"'):
            self.assertNotIn(clause, PREVIEW)

    def test_the_shared_filter_scopes_to_the_one_day(self):
        q = daily_jobsite_filter("p1", start="2026-08-28", end="2026-08-28")
        self.assertEqual(q["date"], {"$gte": "2026-08-28", "$lte": "2026-08-28"})
        self.assertEqual(q["log_type"], "daily_jobsite")
        self.assertEqual(q["status"], "submitted")


class CompaniesComeFromTheGate(unittest.TestCase):
    """The same rows the headcount comes from, so the two cannot disagree."""

    def test_the_company_count_reads_checkins(self):
        self.assertIn("db.checkins.find", PREVIEW)

    def test_it_reuses_the_headcount_query(self):
        """One filter object, used for both the count and the companies. Two
        near-identical dicts is how a panel comes to report a headcount and a
        company count over different sets of rows."""
        self.assertEqual(PREVIEW.count("'check_in_time': {'$gte': day_start, '$lt': day_end}"), 1)
        self.assertIn("count_documents(_day_checkins)", PREVIEW)
        self.assertIn("db.checkins.find(_day_checkins", PREVIEW)

    def test_the_projection_carries_no_worker_identity(self):
        """A projection wide enough to carry a name is a projection somebody
        will later render. This one counts companies."""
        for leaked in ("worker_name", "worker_id", "signature"):
            self.assertNotIn(leaked, PREVIEW.split("_companies = set()")[1].split("companies_on_site")[0])

    def test_it_resolves_the_company_through_the_shared_reader(self):
        """`_worker_company` exists because one fact has four field names in
        this database and retyping the or-chain has produced four defects."""
        self.assertIn("_worker_company", PREVIEW)


class TheWordIsCompaniesNotSubcontractors(unittest.TestCase):
    def test_the_response_carries_companies_on_site(self):
        self.assertIn("'companies_on_site': companies_on_site", PREVIEW)

    def test_the_old_key_is_an_alias_of_the_same_number(self):
        """An install older than this deploy reads `subcontractor_count` and
        would render a blank card if the key vanished -- the stranded-device
        problem #294 exists to measure. It is the SAME value, not a second
        count that can drift."""
        self.assertIn("'subcontractor_count': companies_on_site", PREVIEW)

    def test_nothing_still_counts_subcontractor_cards(self):
        self.assertNotIn("subcontractor_cards", PREVIEW)


class TheWorkerCountStaysTheLogsOwnClaim(unittest.TestCase):
    def test_it_comes_from_the_daily_log_not_the_gate(self):
        """It renders beside that log's status, so it must be what the log
        claims. The gate's number under a daily-log heading would be a fresh
        contradiction of the kind this pass exists to remove."""
        self.assertIn("daily_log.get('worker_count', 0) if daily_log else 0", PREVIEW)

    def test_the_headcount_is_still_the_gate(self):
        self.assertIn("'checkin_count': checkin_count", PREVIEW)


class TheCountingRule(unittest.TestCase):
    """Exercised against the real helper, not asserted about in prose."""

    @staticmethod
    def _count(rows):
        seen = set()
        for c in rows:
            name = server._worker_company(c.get("worker_company"), c.get("company"))
            key = " ".join(name.lower().split())
            if key:
                seen.add(key)
        return len(seen)

    def test_sixteen_men_from_five_companies_count_as_five(self):
        names = ["Arkon Builders", "Sanchez Concrete", "Vertex Steel",
                 "Delta Electric", "Iron Works LLC"]
        rows = [{"worker_company": names[i % 5]} for i in range(16)]
        self.assertEqual(self._count(rows), 5)

    def test_case_and_whitespace_are_not_identity(self):
        """A doubled space already printed the same man twice on a production
        pre-shift sheet; the same collapse must not inflate a company count."""
        self.assertEqual(self._count([
            {"worker_company": "Arkon Builders"},
            {"worker_company": "arkon builders"},
            {"worker_company": "Arkon  Builders "},
        ]), 1)

    def test_a_row_naming_no_company_is_not_a_company(self):
        self.assertEqual(self._count([
            {"worker_company": "Arkon"}, {}, {"worker_company": ""},
            {"worker_company": "   "},
        ]), 1)

    def test_an_empty_gate_is_zero_companies(self):
        self.assertEqual(self._count([]), 0)

    def test_it_falls_back_to_the_bare_company_field(self):
        self.assertEqual(self._count([{"company": "Arkon"}]), 1)


if __name__ == "__main__":
    unittest.main()
