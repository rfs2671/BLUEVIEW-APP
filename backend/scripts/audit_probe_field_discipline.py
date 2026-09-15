#!/usr/bin/env python3
"""WHICH PROBES COUNT ON A FIELD NAME THEY NEVER DECLARED.

WHY THIS EXISTS, MEASURED. Four times in ONE session a probe asked a
collection for a field it does not have, got a confident zero, and the zero was
reported as a finding:

    document_page_index.created_at        the field is `indexed_at`.
                                          "0 pages indexed in 30 days" against
                                          a collection holding 149 rows.
    document_page_index.searchable_text   no such field, anywhere.
    workers.certifications[].osha_data    the payload is on the WORKER doc, not
                                          on the certification subdocument.
    gate_failures.device_fingerprint      the field is `fingerprint_id`, so
                                          every device read as `?`.

THE LAST ONE HAPPENED AFTER `probe_helpers.py` WAS WRITTEN, in a script that
printed the collection's keys and then queried different names. A helper nobody
is required to use is a helper that gets skipped precisely when someone is in a
hurry -- which is exactly when a wrong field name is most likely.

So this is the enforcement. `scripts/probe_helpers.py` supplies
`require_fields`, `counted` and `describe`; all three RAISE `FieldNotInSample`
rather than returning a confident zero for a field the sample does not have.
This audit finds the places that count on a field WITHOUT going through them.

WHAT COUNTS AS A VIOLATION -- deliberately narrow, so a hit is real:

    A COUNTING EXPRESSION      len(...), sum(...), Counter(...), or a
                               `.count_documents(...)` call
    OVER A FIELD READ          whose operand reads a document field by a STRING
                               LITERAL key -- `d.get("x")` or `d["x"]`
    THAT THE FILE NEVER        and "x" is never passed to require_fields /
    DECLARED                   counted / describe anywhere in the same file.

AN AST WALK, NOT A GREP, and that is not fussiness: the first f-string defeats
a grep, and `counted(rows, f"{prefix}_at")` is exactly the shape a hurried
probe produces. The tree sees the call; the text does not.

WHAT IT DELIBERATELY DOES NOT FLAG:
  * reads that are not counted -- printing a field, writing it, comparing it;
  * `_id`, and dunder keys, which are never the field a census gets wrong;
  * a dynamic key (an f-string, a variable). It cannot know the name, so it
    cannot know whether the name was declared. Silence here is honest, not
    clearance.

    cd backend
    python scripts/audit_probe_field_discipline.py            # the census
    python scripts/audit_probe_field_discipline.py --list     # file:line rows

EXIT CODE IS THE ANSWER: 0 when no script counts on an undeclared field,
1 when any does. Read the status, not the prose.
"""
from __future__ import annotations

import argparse
import ast
import os
import sys

HELPERS = ("require_fields", "counted", "describe")
COUNTING = ("len", "sum", "Counter")
# Never the field a census gets wrong, and present on every document.
EXEMPT_KEYS = {"_id"}


def _decl_name(node: ast.AST) -> str | None:
    """The bare name of whatever is being called, however it is spelled."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def declared_fields(tree: ast.AST) -> set[str]:
    """Every string literal this file hands to one of the three helpers.

    ANY argument position, deliberately: `counted(rows, "indexed_at")` puts it
    second, `require_fields(rows, "a", "b")` puts it third and fourth, and a
    future helper signature should not silently empty this set.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _decl_name(node.func) in HELPERS:
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    out.add(arg.value)
    return out


def field_reads(node: ast.AST) -> set[str]:
    """String-literal document field keys read anywhere under `node`.

    `d.get("x")` and `d["x"]`. A dynamic key is skipped on purpose -- see the
    module docstring; an unknown name cannot be checked against a declaration.
    """
    out: set[str] = set()
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "get"
                and sub.args
                and isinstance(sub.args[0], ast.Constant)
                and isinstance(sub.args[0].value, str)):
            out.add(sub.args[0].value)
        elif (isinstance(sub, ast.Subscript)
                and isinstance(sub.slice, ast.Constant)
                and isinstance(sub.slice.value, str)):
            out.add(sub.slice.value)
    return out


def counting_nodes(tree: ast.AST):
    """Every expression in this file that turns documents into a NUMBER."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _decl_name(node.func)
        if name in COUNTING or name == "count_documents":
            yield node


def audit_source(src: str, path: str) -> list[tuple[str, int, str]]:
    """Returns [(path, lineno, field)] for every undeclared counted field."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # A file that will not parse is not a clearance. Reported as its own
        # row so it cannot pass as "no violations".
        return [(path, 0, "<unparseable>")]
    declared = declared_fields(tree)
    # The helpers' OWN module defines them; it does not consume them.
    if os.path.basename(path) == "probe_helpers.py":
        return []
    # A SET, because counting expressions NEST: `sum(len(d["photos"]) ...)`
    # matches at `sum` and again at `len`, and one mistake reported twice reads
    # as two mistakes. The census is a number someone acts on.
    hits: set[tuple[str, int, str]] = set()
    for node in counting_nodes(tree):
        for field in field_reads(node):
            if field in EXEMPT_KEYS or field.startswith("__"):
                continue
            if field not in declared:
                hits.add((path, node.lineno, field))
    return sorted(hits, key=lambda h: (h[0], h[1], h[2]))


MESSAGE = """\
A SCRIPT COUNTS ON A FIELD NAME IT NEVER DECLARED.

Four times in one session a probe asked for a field the collection does not
have and reported the confident zero as a finding:

  document_page_index.created_at       the field is `indexed_at` -- "0 pages
                                       indexed in 30 days" against 149 rows
  document_page_index.searchable_text  no such field
  workers.certifications[].osha_data   the payload is on the WORKER document
  gate_failures.device_fingerprint     the field is `fingerprint_id`, so every
                                       device read as `?`

The last one happened AFTER scripts/probe_helpers.py was written, in a script
that printed the collection's keys and then queried different names.

`require_fields`, `counted` and `describe` in scripts/probe_helpers.py RAISE
FieldNotInSample instead of returning a zero nobody can tell from a real one.
Route the count through one of them, or -- if the field genuinely is not a
document field -- read it outside the counting expression.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true",
                    help="print every hit as file:line field")
    ap.add_argument("--dir", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()

    hits: list[tuple[str, int, str]] = []
    files = sorted(f for f in os.listdir(args.dir) if f.endswith(".py"))
    for name in files:
        path = os.path.join(args.dir, name)
        with open(path, encoding="utf-8") as fh:
            hits.extend(audit_source(fh.read(), path))

    print(f"{len(files)} scripts scanned, {len(hits)} undeclared counted "
          f"field(s) in {len({h[0] for h in hits})} file(s)")
    if hits and args.list:
        for path, lineno, field in hits:
            print(f"  {os.path.basename(path)}:{lineno}  {field}")
    if hits:
        print()
        print(MESSAGE)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
