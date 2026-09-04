""""null" was a live dedupe key, and it collapsed distinct men.

Two workers whose cards could not be read both arrive carrying the STRING
"null" as a name. It is four characters, it survives `.strip()`, and `_norm_key`
casefolds it to "null" — so both key as ("null", <company>) and the second is
dropped from the roster as a duplicate of the first.

That is the OPPOSITE failure from the one recorded beside it: "null" COLLAPSES
distinct workers, while case and whitespace variance SPLITS one. Same field,
same merge, opposite directions.

SCOPE, AND IT IS DELIBERATELY NARROW. This makes a nullish name take whatever
path a BLANK name already takes at each site — pass 3 skips one outright, the
others let it form a key. It does not change what `_norm_key` does to a
COMPANY, where "" is meaningful and `seen_names_only` depends on it, and it
does not unify the three key rules. Both of those change which workers collapse
on a FILED roster, which is item 7 and is measured before it is decided.

WHAT THIS THEREFORE DOES NOT FIX, stated so nobody reads more into it: two
unnamed rows at the same company still collapse at passes 1, 2 and 4, exactly
as two blank-named rows always have. The token stops impersonating a name; the
policy for a nameless row is unchanged.

Run:  python -m pytest backend/tests/test_worker_name_is_not_a_dedupe_token.py -q
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
import textwrap
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from lib.ocr_text import norm_ocr_str  # noqa: E402

MERGERS = ("get_project_checkins_today", "get_project_daily_headcount")


def _name_assignments(fn_name):
    """Every `name = ...` in the function whose right-hand side reads a
    worker_name, with whether it passes through norm_ocr_str.

    READ FROM THE AST, not counted in the source. Five of these exist across
    two functions and three spellings; a grep for any one spelling finds a
    subset, which is how "three sites" was nearly shipped as the whole set."""
    src = textwrap.dedent(inspect.getsource(getattr(server, fn_name)))
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "name" for t in node.targets):
            continue
        rhs = ast.unparse(node.value)
        if "worker_name" not in rhs:
            continue
        out.append((rhs, "norm_ocr_str" in rhs))
    return out


def test_every_worker_name_read_in_both_mergers_is_normalised():
    total = 0
    for fn in MERGERS:
        found = _name_assignments(fn)
        assert found, f"{fn}: read no worker_name assignment at all"
        for rhs, normalised in found:
            assert normalised, f"{fn}: {rhs}"
        total += len(found)
    # NON-EMPTY IS NOT ENOUGH — the count is the point. Five reads across two
    # functions and three spellings; this was first scoped as "three sites"
    # from the three NORMALISERS, and the reads are what actually matter.
    assert total == 5, f"expected 5 worker_name reads, found {total}"


def test_the_token_no_longer_survives_as_a_name():
    for token in ("null", "NULL", "N/A", "none", "-", "  "):
        assert (norm_ocr_str(token) or "") == "", token
    assert (norm_ocr_str("Jose Ramirez") or "") == "Jose Ramirez"


def test_it_reaches_the_rendered_row_as_unknown_not_as_null():
    """`"worker_name": name or "Unknown"` is the rendered cell. Before this,
    a man whose card would not read appeared on the roster as "null"."""
    # THE FIRST DRAFT OF THIS ASSERTION WAS VACUOUS:
    #
    #     assert (norm_ocr_str("null") or "") or "Unknown" == "Unknown"
    #
    # `==` binds tighter than `or`, so that reads as `"" or True` and is true
    # for every input including the broken one. It passed, and it measured
    # nothing — the same shape as the empty-set rule recorded in followups,
    # one line long. Parenthesised, and given a case it must FAIL on.
    def rendered(raw_name):
        return (norm_ocr_str(raw_name) or "") or "Unknown"

    assert rendered("null") == "Unknown"
    assert rendered("N/A") == "Unknown"
    assert rendered("") == "Unknown"
    assert rendered("Jose Ramirez") == "Jose Ramirez", (
        "the negative case: a real name must NOT become Unknown"
    )


# ── WHAT MUST NOT HAVE MOVED ──────────────────────────────────────────────

def test_the_company_rule_is_untouched():
    """`_norm_key` is nested in get_project_checkins_today and is used for the
    COMPANY half of the key, where "" is meaningful and seen_names_only depends
    on it. Changing it would change which workers collapse on a filed roster."""
    src = inspect.getsource(server.get_project_checkins_today)
    assert 'def _norm_key(v):' in src
    assert 'return " ".join(str(v or "").split()).casefold()' in src, (
        "_norm_key changed — that is item 7, not this"
    )


def test_the_three_key_rules_are_still_three_and_that_is_recorded():
    """NOT A FIX — a guard on the finding. The inline key at the headcount
    merge is a bare `.lower()`, `_norm_key` collapses internal whitespace, and
    `_roster_key` only strips. "Jose  Ramirez" with a double space SPLITS under
    the inline rule and MERGES under _norm_key, so two passes in the same merge
    disagree about whether the same man is the same man.

    Asserted as it stands so unifying them is a deliberate act with a failing
    test in front of it, rather than something that happens quietly."""
    assert _norm_key_rule("Jose  Ramirez") == "jose ramirez"
    assert _inline_rule("Jose  Ramirez") == "jose  ramirez"
    assert _norm_key_rule("Jose  Ramirez") != _inline_rule("Jose  Ramirez"), (
        "the two rules now agree — if that was deliberate, this test should be "
        "deleted along with item 7's finding; if not, one of them moved"
    )
    src = inspect.getsource(server.get_project_daily_headcount)
    assert "worker_key = (name.lower(), company.lower())" in src, (
        "the inline key changed — that is item 7"
    )


def _norm_key_rule(v):
    return " ".join(str(v or "").split()).casefold()


def _inline_rule(v):
    return str(v or "").strip().lower()
