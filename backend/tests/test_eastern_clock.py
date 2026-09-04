"""A stored instant is not a wall clock, and the roster printed it as one.

THE DEFECT. `_roster_clock` took a check-in stored as `2026-08-11T10:47:05Z`,
parsed it (correctly, tz-aware, UTC), and then called `.strftime("%I:%M %p")`
on it WITHOUT converting. strftime formats whatever zone the datetime is
already in, so the UTC instant printed as "10:47 AM" — four hours ahead of the
6:47 AM EDT the man actually walked through the gate. Every toolbox-talk
attendance roster on every report since the field existed carries that error,
on a document a DOB inspector reads.

THE RULING. The stored instant never changed; the wrong string was a bug's
output, not a statement anybody made. So every document, old and new, renders
correctly from unchanged data. No migration.

WHY THIS FILE RENDERS HTML. `eastern_date` has had a docstring calling itself
"the only date source" since it was written, and a source-text test would have
passed the whole time this bug shipped — the code parsed, the code formatted,
nothing looked wrong. The only test that catches "converted to the wrong zone"
is one that reads the string the document actually prints. So the primary
assertions here drive the real renderers and read their output.

The source-text assertions are AST-keyed, on the expression and not on a line
number. Location-keyed source pins have failed three times this week in this
repo (see memory: leftmost regex source tests) — a declaration added earlier in
the file breaks a test about a later one, and this file must not join them.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

DATE = "2026-08-11"
PROJECT = "proj_clock"

# THE FIXTURE INSTANT. 10:47:05 UTC on an August day is 6:47 AM EDT (UTC-4).
# Both strings are load-bearing: "6:47 AM" is what must print, and "10:47" is
# the bug's output, which must appear nowhere on the document.
STORED_INSTANT = "2026-08-11T10:47:05Z"
CORRECT = "6:47 AM"
WRONG = "10:47"


# ══════════════════════════════════════════════════════════════════════════
#  Harness — a fake db, the real renderers
# ══════════════════════════════════════════════════════════════════════════

def _match(doc, query):
    for k, v in (query or {}).items():
        if isinstance(v, dict):
            if "$ne" in v and doc.get(k) == v["$ne"]:
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _Coll:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, projection=None):
        return _Cursor([d for d in self.docs if _match(d, query)])

    async def find_one(self, query=None, projection=None, sort=None):
        for d in self.docs:
            if _match(d, query):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, query=None):
        return sum(1 for d in self.docs if _match(d, query))


class _DB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self[n]

    def __getitem__(self, n):
        if n not in self._c:
            self._c[n] = _Coll()
        return self._c[n]


TOOLBOX = {
    "_id": "lb_tb", "project_id": PROJECT, "date": DATE,
    "log_type": "toolbox_talk", "is_deleted": False,
    "cp_name": "Carl CP", "cp_signature": {"affirmed": True},
    "data": {
        "location": "gate", "company_name": "AAZ", "performed_by": "Carl CP",
        "meeting_time": "07:30 AM", "checked_topics": {"hard_hats": True},
        "attendees": [{
            "name": "wilmer carrillo", "title": "foreman", "company": "aaz",
            # THE STORED INSTANT, exactly as the gate writes it
            # (toolboxTalkModel.buildAttendees: time = c.check_in_time).
            "time": STORED_INSTANT,
            "signed": True, "added_from": "gate",
        }],
    },
}


class _RenderBase(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.db = _DB()
        self.db.projects.docs = [{
            "_id": PROJECT, "name": "588 Thomas S Boyland Street",
            "address": "588 Thomas S Boyland St, Brooklyn",
            "project_class": "regular",
        }]
        self.db.logbooks.docs = [copy.deepcopy(TOOLBOX)]
        self._orig = {"db": server.db, "tqid": server.to_query_id}
        server.db = self.db
        server.to_query_id = lambda x: x

    def tearDown(self):
        server.db = self._orig["db"]
        server.to_query_id = self._orig["tqid"]
        self.loop.close()

    def rendered(self):
        """The combined report, named so the absence-literal scanner can see
        that it is a string -- see test_absence_literals_are_specific."""
        return self.loop.run_until_complete(
            server.generate_combined_report(PROJECT, DATE))

    def rendered_single(self, logbook):
        """The per-logbook PDF. Same naming rule as `rendered` above."""
        return self.loop.run_until_complete(
            server.generate_single_logbook_html(logbook))

    def _rendered_body(self, html):
        """The document WITHOUT its generated-on footer.

        The footer prints the wall-clock time of the render itself, so at 10:47
        on any morning a whole-document assertNotIn("10:47") would fail on a
        correct document. Excluding it keeps the absence assertion honest
        rather than flaky — and the footer's own conversion has its own test
        below.
        """
        i = html.index("<!-- FOOTER -->")
        return html[:i]


# ══════════════════════════════════════════════════════════════════════════
#  THE GUARD — what the document prints
# ══════════════════════════════════════════════════════════════════════════

class TheRosterPrintsNewYorkTime(_RenderBase):
    """The one kind of test that would have caught this."""

    def test_the_combined_report_prints_6_47_AM_not_10_47(self):
        body = self._rendered_body(self.rendered())
        self.assertIn(CORRECT, body,
                      "the roster does not print the New York time of the check-in")
        self.assertNotIn(WRONG, body,
                         "the stored UTC instant is printed as if it were a wall clock")

    def test_and_it_says_which_zone(self):
        """A time with no zone on a legal record is the shape that let this
        bug live: nothing on the page said what "10:47" was a time IN."""
        body = self._rendered_body(self.rendered())
        self.assertIn("6:47 AM EDT", body)

    def test_the_per_logbook_pdf_prints_it_the_same_way(self):
        """Two renderers print this roster. One record must not read 6:47 on
        the emailed report and 10:47 on the document an inspector asks for by
        name — that pairing has had to be pulled back twice on this file."""
        html = self.rendered_single(copy.deepcopy(TOOLBOX))
        body = html[:html.index("Generated on ")]
        self.assertIn(CORRECT, body)
        self.assertNotIn(WRONG, body)

    def test_a_winter_instant_reads_EST(self):
        """The same instant-of-day in January is 5:47 AM EST. Hard-coding -4
        would pass every August test and be wrong for five months of the year."""
        self.db.logbooks.docs[0]["data"]["attendees"][0]["time"] = \
            "2026-01-14T10:47:05Z"
        self.db.logbooks.docs[0]["date"] = DATE  # the report still asks for Aug
        body = self._rendered_body(self.rendered())
        self.assertIn("5:47 AM EST", body)

    def test_an_unanchored_wall_clock_string_still_falls_back_to_itself(self):
        """`weeklyGapAttendee` writes `time: ''` and older rosters hold typed
        strings like "07:15". Those carry NO zone and cannot be converted; the
        renderer must print them rather than a parse error, exactly as before.
        """
        self.db.logbooks.docs[0]["data"]["attendees"][0]["time"] = "07:15"
        body = self._rendered_body(self.rendered())
        self.assertIn("07:15", body)


class TheFooterSaysWhenInNewYorkTime(_RenderBase):
    """"Generated on ... UTC" is a stored instant rendered to a user too."""

    def test_the_generated_on_line_carries_an_eastern_zone(self):
        html = self.rendered()
        footer = html[html.index("<!-- FOOTER -->"):]
        self.assertIn("automatically generated on", footer)
        self.assertTrue(
            "EDT" in footer or "EST" in footer,
            f"the footer names no Eastern zone: {footer[:400]}")
        self.assertNotIn(" UTC", footer,
                         "the footer still prints a UTC clock to a New York reader")


# ══════════════════════════════════════════════════════════════════════════
#  THE HELPER — one owner for every user-facing time conversion
# ══════════════════════════════════════════════════════════════════════════

class EasternClockOwnsTheConversion(unittest.TestCase):
    def test_it_converts_a_utc_instant(self):
        self.assertEqual(server.eastern_clock(STORED_INSTANT), "6:47 AM EDT")

    def test_it_accepts_a_datetime_as_well_as_a_string(self):
        self.assertEqual(
            server.eastern_clock(
                datetime(2026, 8, 11, 10, 47, 5, tzinfo=timezone.utc)),
            "6:47 AM EDT")

    def test_an_instant_already_in_eastern_is_left_where_it_is(self):
        self.assertEqual(
            server.eastern_clock(datetime(2026, 8, 11, 6, 47,
                                          tzinfo=ZoneInfo("America/New_York"))),
            "6:47 AM EDT")

    def test_it_REFUSES_a_naive_datetime(self):
        """THE WHOLE POINT. Silently passing a naive datetime through is how
        this bug happened: a value with no zone got formatted as though its
        digits were New York's."""
        with self.assertRaises(ValueError):
            server.eastern_clock(datetime(2026, 8, 11, 10, 47, 5))

    def test_it_REFUSES_a_naive_iso_string(self):
        with self.assertRaises(ValueError):
            server.eastern_clock("2026-08-11T10:47:05")

    def test_it_REFUSES_a_bare_wall_clock(self):
        with self.assertRaises(ValueError):
            server.eastern_clock("07:15")

    def test_it_REFUSES_nothing_at_all(self):
        for bad in (None, "", "   ", 0):
            with self.assertRaises(ValueError):
                server.eastern_clock(bad)

    def test_the_offset_follows_the_date_not_a_constant(self):
        self.assertEqual(server.eastern_clock("2026-01-14T10:47:05Z"),
                         "5:47 AM EST")
        self.assertEqual(server.eastern_clock("2026-07-14T10:47:05Z"),
                         "6:47 AM EDT")

    def test_midnight_and_noon_read_as_people_write_them(self):
        self.assertEqual(server.eastern_clock("2026-08-11T04:00:00Z"),
                         "12:00 AM EDT")
        self.assertEqual(server.eastern_clock("2026-08-11T16:00:00Z"),
                         "12:00 PM EDT")

    def test_the_hour_carries_no_leading_zero(self):
        self.assertEqual(server.eastern_clock("2026-08-11T13:05:00Z"),
                         "9:05 AM EDT")


class EasternDatetimeIsItsSibling(unittest.TestCase):
    def test_it_names_the_day_and_the_time_and_the_zone(self):
        self.assertEqual(server.eastern_datetime(STORED_INSTANT),
                         "August 11, 2026 at 6:47 AM EDT")

    def test_the_day_is_the_NEW_YORK_day(self):
        """01:30 UTC on the 12th is 9:30 PM EDT on the 11th. Printing the UTC
        calendar day here is the same class of error `eastern_date` exists to
        stop — a document stamped tomorrow."""
        self.assertEqual(server.eastern_datetime("2026-08-12T01:30:00Z"),
                         "August 11, 2026 at 9:30 PM EDT")

    def test_it_refuses_the_same_things_its_sibling_refuses(self):
        with self.assertRaises(ValueError):
            server.eastern_datetime(datetime(2026, 8, 11, 10, 47))

    def test_no_day_is_zero_padded(self):
        """'%-d' is a glibc extension and this module is imported on Windows,
        so the day is interpolated rather than formatted."""
        self.assertEqual(server.eastern_datetime("2026-08-05T16:00:00Z"),
                         "August 5, 2026 at 12:00 PM EDT")


class RosterClockIsNowJustACallToIt(unittest.TestCase):
    def test_it_converts(self):
        self.assertEqual(server._roster_clock(STORED_INSTANT), "6:47 AM EDT")

    def test_nothing_is_still_an_em_dash(self):
        self.assertEqual(server._roster_clock(""), "&mdash;")
        self.assertEqual(server._roster_clock(None), "&mdash;")

    def test_an_unconvertible_value_falls_back_to_itself(self):
        self.assertEqual(server._roster_clock("07:15"), "07:15")


# ══════════════════════════════════════════════════════════════════════════
#  SOURCE — keyed on the EXPRESSION, never on a line number
# ══════════════════════════════════════════════════════════════════════════

# PARSED RAW, then unparsed. `code_of` strips every triple-quoted literal,
# including ones used as dict VALUES further down server.py, which leaves a
# string that is no longer valid Python. The AST is a stronger form of the same
# discipline anyway: it drops comments outright, and the helper below drops the
# docstring, so an assertion here can only ever match CODE. That is the trap
# tests/source_text.py exists to close, closed a different way.
_TREE = ast.parse((_BACKEND / "server.py").read_text(encoding="utf-8"))


def _rendered_fn(name):
    """The function's CODE, with its docstring removed and no comments."""
    for node in ast.walk(_TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body = body[1:]
            return "\n".join(ast.unparse(s) for s in body)
    raise AssertionError(f"{name} is gone from server.py")


class TheConversionHasExactlyOneOwner(unittest.TestCase):
    """Asserted by walking the AST for the CALL, so this test does not care
    where in the file anything sits."""

    def test_roster_clock_calls_eastern_clock(self):
        body = _rendered_fn("_roster_clock")
        self.assertIn("eastern_clock", body)

    def test_roster_clock_formats_NOTHING_itself(self):
        """The bug in one line: `.strftime(...)` on a value nobody converted.
        A renderer that formats a time itself has opted out of the helper."""
        body = _rendered_fn("_roster_clock")
        # ANCHORED ON THE CALL. `assertNotIn("strftime", ...)` bans eight
        # characters, so a variable named `strftime_fmt` would break a correct
        # build and the fix reached for under pressure is deleting the
        # assertion. The claim is that this function CALLS neither.
        self.assertNotIn(".strftime(", body)
        self.assertNotIn(".fromisoformat(", body)

    def test_eastern_clock_goes_through_the_new_york_zone(self):
        clock = _rendered_fn("eastern_clock")
        helper = _rendered_fn("_as_eastern_instant")
        self.assertIn("America/New_York", clock + helper)

    def test_eastern_clock_raises_rather_than_passing_a_naive_value_through(self):
        helper = _rendered_fn("_as_eastern_instant")
        self.assertIn("tzinfo", helper)
        self.assertIn("raise ValueError", helper)

    def test_no_renderer_formats_a_clock_by_hand_any_more(self):
        """The four call sites that printed a time: both roster columns and
        both "generated on" footers. Any `%I:%M` left inside the two report
        renderers is a fifth conversion nobody owns."""
        for name in ("generate_combined_report", "generate_single_logbook_html"):
            body = _rendered_fn(name)
            self.assertNotIn("%I:%M", body,
                             f"{name} still formats a clock of its own")


if __name__ == "__main__":
    unittest.main()
