"""APPLY THE 2026-09-22 OCR-STRUCTURE MIGRATION ON 588 BOYLAND.

WHAT IT CHANGES, AND NOTHING ELSE
=================================

Two pages, listed in its own plan.json, whose stored schedule differs from
what today's code reads out of the SAME raw table, each checked against the
rendered crop:

  SP-002.00  (grid 3x14, SP - 6.24.26.pdf p2)   1 row -> 2. The sheet prints
      one heading band and two sprinklers: RFC49 16/7 and F1RES44 9/16.
      Stored has one row, with RFC49's data used as the column names (#647).
      56 -> 57 records: the recovered row also gives RFC49 an element.

  P-400.00   (grid 13x6, PL - 6.29.26.pdf p20)  columns FIXTURES | ABBR |
      H.W. | C.W. | WASTE | VENT instead of the note text, and the note joins
      the name. Ten rows either way (#650 rule 4). 53 -> 53 records.

EXCLUDED, DELIBERATELY: P-400.00's storage tank (grid 2x3, same page).
Today's code moves its name into the columns; the stored version is better.
The five other schedules on P-400.00 p20 are not touched.

M-200.00 IS NOT IN THIS MIGRATION. No page in it carries an EF, PTAC or CFM
value; the plan's own pages are the two above.

HOW IT RUNS
===========

Same engine as the #649 migration, same guarantees: it refuses unless the
snapshot files hash to what the plan was built from; it refuses, before any
write, if a page is in neither its snapshot state nor its migrated state; a
page already migrated is skipped; a run cut off mid-page is finished by the
next; and every page is re-read after its write. The gate is prod_guard's
`--i-know --reason --session`, and every write leaves an audit_logs row
naming THIS script.

USAGE (from backend/)
=====================

    railway run --service Blueview2 --environment production -- python -m scripts.migrate_plan_ocr_structure_20260922 --snapshot-dir <dir>
    railway run --service Blueview2 --environment production -- python -m scripts.migrate_plan_ocr_structure_20260922 --snapshot-dir <dir> --i-know --reason "<why>" --session <id>
    railway run --service Blueview2 --environment production -- python -m scripts.migrate_plan_ocr_structure_20260922 --snapshot-dir <dir> --verify
"""
from __future__ import annotations

import sys

from scripts import migrate_plan_discipline_20260921 as engine

NAME = "migrate_plan_ocr_structure_20260922"


def main(argv=None, client=None) -> int:
    return engine.main(argv, client, name=NAME)


if __name__ == "__main__":
    sys.exit(main())
