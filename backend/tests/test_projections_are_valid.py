"""A projection that mixes an exclusion with inclusions is rejected by MongoDB.

`get_company_roster` passed

    {"password": 0, "_id": 1, "name": 1, "full_name": 1, "email": 1, "role": 1}

and raised `OperationFailure: Cannot do inclusion on field name in exclusion
projection` on EVERY call, since the line was written. 40 events in the week
before the fix, still arriving. The annotation recipient picker returned a 500
to any authenticated user who opened it.

HOW IT SURVIVED A SWEEP THAT WAS LOOKING AT IT. `find_unserved_sorts.py`
classifies a projection by SHAPE and reported this row as "inclusion, base64
excluded" — protected. docs/audits/followups.md recorded that as fact, and a
later pass deferred the fix as "a riskier edit than adding an index" without
checking whether it was already failing.

So this test does not look for one endpoint. It reads EVERY projection literal
in server.py and asserts each is a legal MongoDB projection, because the defect
was never that one person wrote one bad dict — it was that nothing could tell a
malformed projection from a working one.

Run:  python -m pytest backend/tests/test_projections_are_valid.py -q
"""

from __future__ import annotations

import ast
import io
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent

# THE RULE, from MongoDB: a projection is either an inclusion or an exclusion.
# `_id` is the ONLY field that may be excluded inside an inclusion projection.
_ID_IS_EXEMPT = "_id"


def _projection_dicts():
    """Every dict literal passed as a projection to a find/find_one call.

    READ FROM THE AST. A regex over 44k lines would find the braces and not
    know which argument they were, which is how the sweep that already looked
    at this endpoint classified it by shape instead of validating it.
    """
    src = io.open(_BACKEND / "server.py", encoding="utf-8").read()
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = ast.unparse(node.func)
        if not (fn.endswith(".find") or fn.endswith(".find_one")):
            continue
        # find(filter, projection) positionally, or projection=
        cands = list(node.args[1:2])
        cands += [k.value for k in node.keywords if k.arg == "projection"]
        for c in cands:
            if isinstance(c, ast.Dict):
                out.append((node.lineno, fn, c))
    return out


def _verdict(dict_node):
    """(kind, offending_fields). kind is 'inclusion', 'exclusion', 'mixed' or
    'unreadable' — a dict built from variables is not judged here."""
    inc, exc = [], []
    for k, v in zip(dict_node.keys, dict_node.values):
        if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
            return "unreadable", []
        if not isinstance(v, ast.Constant) or not isinstance(v.value, int):
            return "unreadable", []
        (inc if v.value else exc).append(k.value)
    if inc and exc:
        illegal = [f for f in exc if f != _ID_IS_EXEMPT]
        return ("mixed" if illegal else "inclusion"), illegal
    if inc:
        return "inclusion", []
    return "exclusion", []


def test_no_projection_in_server_py_mixes_inclusion_with_exclusion():
    found = _projection_dicts()
    # NON-EMPTY FIRST. Every assertion below is vacuously satisfied by an empty
    # list, which is exactly how a check that stopped reaching its subject
    # reports success.
    assert len(found) > 20, (
        f"only {len(found)} projections read off server.py — the extraction "
        "stopped reaching its subject"
    )

    bad = []
    for line, fn, node in found:
        kind, illegal = _verdict(node)
        if kind == "mixed":
            bad.append(f"server.py:{line} in {fn} excludes {illegal} "
                       "inside an inclusion projection")
    assert not bad, (
        "MongoDB rejects these outright — every call raises OperationFailure "
        "'Cannot do inclusion on field X in exclusion projection':\n  "
        + "\n  ".join(bad)
    )


def test_the_roster_projection_is_the_one_this_was_written_for():
    """Named explicitly so the regression has a home, and so that removing the
    endpoint does not silently remove the coverage."""
    src = io.open(_BACKEND / "server.py", encoding="utf-8").read()
    assert '{"password": 0, "_id": 1, "name": 1' not in src, (
        "get_company_roster is back on the projection MongoDB rejects"
    )
    assert '{"_id": 1, "name": 1, "full_name": 1, "email": 1, "role": 1}' in src


def test_a_mixed_projection_is_actually_detected():
    """The positive control. Without it this file passes by finding nothing —
    the empty-set rule, applied to the detector rather than the data."""
    node = ast.parse('{"password": 0, "name": 1}', mode="eval").body
    assert _verdict(node) == ("mixed", ["password"])
    # And the two legal shapes are NOT flagged.
    assert _verdict(ast.parse('{"name": 1, "email": 1}', mode="eval").body)[0] == "inclusion"
    assert _verdict(ast.parse('{"password": 0}', mode="eval").body)[0] == "exclusion"
    # `_id: 0` beside inclusions is legal and must not be flagged.
    assert _verdict(ast.parse('{"_id": 0, "name": 1}', mode="eval").body)[0] == "inclusion"
