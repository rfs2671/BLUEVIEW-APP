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

# ── THE FLOOR, AND IT IS NOT A STYLE POINT ────────────────────────────────
#
# Thirty-nine test files assert `src.count(<something>) == N_DOCUMENT_RENDERERS`.
# If this tuple ever empties, every one of those becomes "this string appears
# ZERO times in server.py" -- the exact opposite of what each was written to
# assert -- and all thirty-nine go green saying it.
#
# A CENSUS THAT INVERTS IS WORSE THAN ONE THAT GOES QUIET. A quiet check merely
# stops helping; an inverted one actively certifies the wrong thing, and does it
# in thirty-nine places at once.
#
# THE TUPLE HOLDS ONE NAME TODAY, because the investor report stopped embedding
# the filed documents and its copies went with them. So it is ONE CONVERSION
# from empty, and the type-by-type migration is precisely what would empty it.
#
# The message says what to do, because a floor that fails without saying so gets
# RAISED rather than acted on.
assert DOCUMENT_RENDERERS, (
    "DOCUMENT_RENDERERS is empty, so every `== N_DOCUMENT_RENDERERS` assertion "
    "in the suite now reads 'this string appears zero times' and passes. Do NOT "
    "delete this check and do NOT set the count by hand. Either a renderer was "
    "renamed -- put the new name in the tuple, which is what `assert_is_current` "
    "is for -- or the last hand-written document renderer is genuinely gone, in "
    "which case those assertions have no subject left and the suites that use "
    "them need re-pointing at the declarative engine, one file at a time.")

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
