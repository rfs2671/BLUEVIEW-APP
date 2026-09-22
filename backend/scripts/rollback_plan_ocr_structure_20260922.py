"""ROLL BACK THE 2026-09-22 OCR-STRUCTURE MIGRATION FROM ITS SNAPSHOT.

The two pages it migrated (SP-002.00 p2, P-400.00 p20) go back to the raw
BSON read before it ran: _id, created_at, field order and types byte for
byte. A page still in its snapshot state is skipped; a page in any other
state makes it refuse and write nothing.

Same engine, gate and audit row as the #649 rollback; the rows name THIS
script.

USAGE (from backend/)
=====================

    railway run --service Blueview2 --environment production -- python -m scripts.rollback_plan_ocr_structure_20260922 --snapshot-dir <dir>
    railway run --service Blueview2 --environment production -- python -m scripts.rollback_plan_ocr_structure_20260922 --snapshot-dir <dir> --i-know --reason "<why>" --session <id>
"""
from __future__ import annotations

import sys

from scripts import rollback_plan_discipline_20260921 as engine

NAME = "rollback_plan_ocr_structure_20260922"


def main(argv=None, client=None) -> int:
    return engine.main(argv, client, name=NAME)


if __name__ == "__main__":
    sys.exit(main())
