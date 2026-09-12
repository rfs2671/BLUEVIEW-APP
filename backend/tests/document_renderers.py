"""WHICH RENDERERS PRINT A FILED DOCUMENT. ONE LIST, AND THIS IS IT.

Several suites assert that a rule is carried ONCE PER RENDERER: the pre-shift
attestation, the answer labels, the OSHA cert-type cell, the crew-row headcount
helper, the superintendent attribution. Each of them used to say `2` and mean
"both of them".

`generate_combined_report` WAS THE SECOND ONE. The investor report used to embed
the filed documents; it indexes them now and embeds none, so it prints no filed
document and carries no copy of those rules. See
`docs/audits/report-replacement-ledger.md`.

── WHY THIS IS A MODULE AND NOT A CONSTANT IN EACH FILE ─────────────────────

The first pass at the migration put the same tuple in nine files. That turns a
hardcoded-number problem into a duplicated-list problem, which is worse: nine
lists drift, and the day a third renderer appears, eight of them are quietly
wrong while every test still passes.

DERIVED, NOT RETYPED, AND DERIVED IN ONE PLACE.

── THE LIST IS CHECKED AGAINST THE SERVER ───────────────────────────────────

`assert_is_current` proves every name here is really a function in server.py,
so a renderer that is renamed or removed fails loudly instead of leaving a
census that counts something that no longer exists.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Tuple

_BACKEND = Path(__file__).resolve().parents[1]

#: Every renderer that prints a FILED DOCUMENT — a per-logbook legal record an
#: inspector asks for by name. Ordered, and the count is what suites derive.
DOCUMENT_RENDERERS: Tuple[str, ...] = ("generate_single_logbook_html",)

#: The count those suites assert against. One occurrence per renderer.
N_DOCUMENT_RENDERERS = len(DOCUMENT_RENDERERS)

#: Removed from the list, kept for the record so a reader of a census that used
#: to say `2` can see which entry went and look up why.
FORMER_DOCUMENT_RENDERERS: Tuple[str, ...] = ("generate_combined_report",)


def assert_is_current(case) -> None:
    """Every named renderer still exists; every former one no longer prints.

    THE VACUITY GUARD ON THE WHOLE IDIOM. A census derived from a list of names
    that have drifted out of the source counts nothing, and passes.
    """
    source = (_BACKEND / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    for name in DOCUMENT_RENDERERS:
        case.assertIn(name, defined,
                      f"{name} is in DOCUMENT_RENDERERS and not in server.py; "
                      f"every census derived from this list is counting "
                      f"something that no longer exists")

    # THE FORMER ONE MUST STILL EXIST -- it is the investor report and it is
    # very much alive -- but it must no longer PRINT a filed document. The
    # cheapest honest proof is that it no longer calls the per-logbook builders
    # by name.
    for name in FORMER_DOCUMENT_RENDERERS:
        case.assertIn(name, defined, name)
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == name)
        body = ast.get_source_segment(source, node) or ""
        for builder in ("_superintendent_log_html", "rows_table(",
                        "PRESHIFT_ATTESTATION_HTML"):
            case.assertNotIn(
                builder, body,
                f"{name} builds {builder} again, so it prints a filed "
                f"document and belongs back in DOCUMENT_RENDERERS")
