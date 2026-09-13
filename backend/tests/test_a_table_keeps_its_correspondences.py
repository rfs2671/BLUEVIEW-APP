"""A ROW IS A SET OF CORRESPONDENCES, AND THE COMPARISON THREW THEM AWAY.

── THE DEMONSTRATION THAT MADE THIS FILE ──────────────────────────────────

Two pre-shift rosters, identical except that every man's Injury answer and his
PPE answer are exchanged:

    TRUTH, read column by column:
       correct  Injury: ['Yes', 'No']   PPE: ['No', 'Yes']
       swapped  Injury: ['No', 'Yes']   PPE: ['Yes', 'No']

    WHAT THE MIGRATION'S INSTRUMENT REPORTS:
       words lost:   none
       words gained: none

Nothing. On a signed §3301 record that is a man reported as having had an
injury who did not.

`words()` returns a SET of lowercased tokens, so the old-against-new comparison
that has cleared seven conversions cannot see a value move between columns, a
value's COUNT change, or rows and sections reordered. Six types are still to
convert and every one of them has a table.

── WHAT THIS FILE ASSERTS ─────────────────────────────────────────────────

For every declared table: the cell under a named header is the value stored on
the row it belongs to. Read by HEADER, so a column inserted or moved does not
silently shift what is being checked, and per ROW, so a roster of two men whose
answers are exchanged fails.

THIS IS THE CHECK THAT DOES NOT USE THE INSTRUMENT. Four repairs to that
instrument in three sessions, each found by something else; the standing rule
is that every conversion carries at least one check that does not go through
it. For a table, this is that check.

── AND IT IS DERIVED ──────────────────────────────────────────────────────

The census walks the declarations, so a type converted tomorrow is covered the
day it lands rather than the day somebody remembers. A table whose columns this
file cannot build a probe for is NAMED and skipped loudly, never skipped
silently.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from lib import legal_render  # noqa: E402
from lib.legal_render import schema as _schema  # noqa: E402
from tests.filed_sheet import cells, logbook, render  # noqa: E402

#: A value that is recognisable in the output and unique per (row, column), so
#: a cell that picked up the wrong row or the wrong column cannot match by
#: accident. Deliberately not a number: `time_of_day` and the bbl formatters
#: reshape numbers, and a probe that the formatter rewrites proves nothing.
def _probe(row: int, column: int) -> str:
    return f"Rowprobe{row}col{column}"


#: FORMATTERS THAT DO NOT PRINT WHAT THEY ARE GIVEN. Each of these maps its
#: input to a fixed vocabulary -- a date, a clock, a verdict, a tick -- so a
#: probe string cannot survive one, and a column bound to one is checked by the
#: type's own test rather than here. Named rather than guessed at: an
#: unrecognised formatter is a FAILURE below, not a skip.
_RESHAPES = frozenset({
    "date_long", "datetime_stamp", "time_of_day", "roster_clock",
    "bbl_borough", "bbl_block", "bbl_lot", "yes_no", "answer", "pass_fail",
    "tick_or_blank", "toggle_list", "weather_line", "affirmation_note",
    "inspection_result", "vibration_status", "attendee_source",
    "signature_ink", "cp_headcount", "preshift_signature", "osha_cert_type",
})

#: PRINTS WHAT IT IS GIVEN, give or take the first letter's case. A probe
#: survives these, which is what makes the correspondence checkable.
_VERBATIM = frozenset({"text", "raw_text", "name", "raw_name", "sentence",
                       "sub_company"})


def _tables():
    """Every declared table, as (log_type, section)."""
    for log_type in sorted(legal_render.CONVERTED_TYPES):
        for section in _schema.SCHEMAS[log_type]["sections"]:
            if section.get("primitive") == "table" and section.get("columns"):
                yield log_type, section


class EveryDeclaredFormatterIsClassified(unittest.TestCase):
    """THE GUARD ON THE TWO SETS ABOVE. A formatter in neither list would be
    treated as unprobeable by the loop below and its column skipped -- which is
    a check going quiet, in the file written because checks went quiet."""

    def test_every_column_formatter_is_in_exactly_one_list(self):
        for log_type, section in _tables():
            for path, label, fmt in section["columns"]:
                with self.subTest(log_type=log_type, column=label):
                    self.assertEqual(
                        (fmt in _RESHAPES) + (fmt in _VERBATIM), 1,
                        f"{fmt!r} is in neither list (or both). Put it in "
                        f"_VERBATIM if it prints what it is given, in "
                        f"_RESHAPES if it maps onto a fixed vocabulary. Do "
                        f"not leave it out: this file would skip the column.")

    def test_there_are_tables_to_check(self):
        """THE VACUITY GUARD. Every assertion in this file loops over
        `_tables()`, and an empty census passes all of them."""
        found = list(_tables())
        self.assertTrue(
            found,
            "no converted type declares a table, so nothing in this file is "
            "checking anything. If that is because the declarations changed "
            "shape, repoint the census; do not leave it running.")


class ACellBelongsToItsRowAndItsColumn(unittest.TestCase):

    def test_every_probeable_column_reads_its_own_row(self):
        """THE CLAIM. Two rows, each carrying a value unique to (row, column).
        The cell under a header must be that row's value for that column.

        TWO ROWS, NOT ONE, because a one-row table cannot exhibit the failure:
        every wrong answer is also the right one.
        """
        for log_type, section in _tables():
            columns = [(p, lab, f) for p, lab, f in section["columns"]
                       if f in _VERBATIM and p and p != "."]
            required = section.get("row_requires") or []
            with self.subTest(log_type=log_type, section=section["title"]):
                if not columns:
                    self.skipTest(
                        f"{log_type}/{section['title']}: every column is "
                        f"bound to a reshaping formatter, so no probe "
                        f"survives; its cells are checked by that type's "
                        f"own test")
                rows = []
                for r in range(2):
                    row = {}
                    for c, (path, _lab, _f) in enumerate(columns):
                        row[path.split(".")[-1]] = _probe(r, c)
                    for need in required:
                        row.setdefault(need.split(".")[-1], _probe(r, 0))
                    rows.append(row)
                lb = logbook(log_type)
                lb["data"][section["path"].split(".")[-1]] = rows
                html = render(lb)
                for c, (_path, label, _f) in enumerate(columns):
                    got = cells(html, label)
                    self.assertEqual(
                        len(got), 2,
                        f"{log_type}/{label}: expected two rows, got "
                        f"{len(got)}")
                    for r in range(2):
                        self.assertIn(
                            _probe(r, c).lower(), got[r].lower(),
                            f"{log_type}: the cell in row {r + 1} under "
                            f"{label!r} does not carry that row's value for "
                            f"that column. A table that crosses its "
                            f"correspondences is invisible to the "
                            f"old-against-new comparison, which compares a "
                            f"SET of words.")

    def test_the_columns_appear_in_the_declared_order(self):
        """A reader matches a value to a heading by POSITION. Two columns
        exchanged is a document whose every row says something different, and
        the word comparison reports it as identical."""
        import re
        for log_type, section in _tables():
            with self.subTest(log_type=log_type, section=section["title"]):
                html = render(logbook(log_type))
                declared = [lab for _p, lab, _f in section["columns"]]
                if f">{declared[0]}</th>" not in html:
                    self.skipTest(
                        f"{log_type}/{section['title']} drew no table for the "
                        f"standard fixture; its empty state is checked by "
                        f"that type's own test")
                i = html.index(f">{declared[0]}</th>")
                head = html[html.rindex("<tr", 0, i):html.index("</tr>", i)]
                # UNESCAPED. A header carrying an apostrophe renders as
                # `CP&#39;s count`, and a comparison against the declared
                # label dropped it from the list -- which read as a MISSING
                # COLUMN and would have sent the next reader looking for one.
                import html as _h
                rendered = [_h.unescape(re.sub(r"<[^>]+>", "", h)).strip()
                            for h in re.findall(r"<th[^>]*>(.*?)</th>", head,
                                                flags=re.S)]
                rendered = [h for h in rendered if h in declared]
                self.assertEqual(
                    rendered, declared,
                    f"{log_type}/{section['title']}: the columns are not in "
                    f"the order the declaration names them")


if __name__ == "__main__":
    unittest.main(verbosity=2)
