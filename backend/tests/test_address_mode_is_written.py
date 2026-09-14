"""features.address_mode must reach the document, not just pass validation.

WHAT THIS CAUGHT. The features loop in whatsapp_update_group_config handles
address_mode separately, because it is the one feature that is a string enum
rather than a boolean and would fail the isinstance(v, bool) check that every
other key goes through. That branch ended in `continue` — and the `continue`
jumped past the set_ops line at the bottom of the loop as well as past the type
check it was there to skip.

So a request setting address_mode was read, validated, answered 200, and thrown
away. The value never reached bot_config.

THAT IS THE WORST SHAPE A WRITE BUG CAN TAKE. Nothing in the response, the
logs, or the config panel distinguishes it from success. The symptom surfaces
somewhere else entirely and much later: a bot that goes on ignoring the crew
after somebody has already switched the setting off, with a 200 in the history
to say it was switched.

AND THE SETTING HAD NO OTHER DOOR. GroupConfigPanel renders five feature
toggles and no control for address_mode, so the API was the only supported way
to change it, and the API silently refused. A direct database write was the
only thing that worked.

WHY THIS READS THE SOURCE RATHER THAN CALLING THE ROUTE. The loop is inline in
a route handler behind auth, company scoping and a live db handle. Standing all
that up to prove one assignment exists would test the scaffolding. The defect
was structural — a branch that returns before it writes — so the test is
structural too, and it asserts the property that was violated: every branch of
this loop reaches a set_ops write.
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")


def _features_loop() -> ast.For:
    import server

    src = textwrap.dedent(inspect.getsource(server.whatsapp_update_group_config))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if ast.unparse(node.target) == "(k, v)" and "f.items()" in ast.unparse(node.iter):
            return node
    raise AssertionError("the features loop is no longer shaped as `for k, v in f.items()`")


def _writes_set_ops(nodes) -> bool:
    """True if any statement in `nodes` assigns into set_ops."""
    for n in nodes:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Assign):
                for tgt in sub.targets:
                    if isinstance(tgt, ast.Subscript) and ast.unparse(tgt.value) == "set_ops":
                        return True
    return False


def test_the_address_mode_branch_writes_before_it_continues():
    """The regression itself. Validating a value and then skipping the write
    answers 200 on a change that did not happen."""
    loop = _features_loop()

    branch = None
    for node in loop.body:
        if isinstance(node, ast.If) and "address_mode" in ast.unparse(node.test):
            branch = node
            break
    assert branch is not None, "no address_mode branch in the features loop"

    # Everything up to the `continue` is what actually runs for this key.
    before_continue = []
    for stmt in branch.body:
        if isinstance(stmt, ast.Continue):
            break
        before_continue.append(stmt)

    assert _writes_set_ops(before_continue), (
        "the address_mode branch validates the value and then continues past "
        "the set_ops write at the bottom of the loop — the request is accepted, "
        "answered 200, and discarded"
    )


def test_no_branch_of_the_features_loop_exits_without_writing():
    """The general form, so the next string-valued feature cannot repeat it.

    Any branch that leaves the loop body early (continue, return, break) must
    have written to set_ops first, or it has silently dropped its key."""
    loop = _features_loop()

    offenders = []
    for node in loop.body:
        if not isinstance(node, ast.If):
            continue
        # A branch that raises is a refusal, not a silent drop — that is fine.
        raises = any(isinstance(s, ast.Raise) for s in ast.walk(node))
        exits_early = any(
            isinstance(s, (ast.Continue, ast.Return, ast.Break)) for s in ast.walk(node)
        )
        if not exits_early:
            continue
        reached = []
        for stmt in node.body:
            if isinstance(stmt, (ast.Continue, ast.Return, ast.Break)):
                break
            reached.append(stmt)
        if not _writes_set_ops(reached) and not (raises and not reached):
            if not _writes_set_ops(reached):
                offenders.append(ast.unparse(node.test))

    # The bool type check raises and writes nothing by design; it never
    # reaches a continue, so it is not collected above.
    assert not offenders, (
        f"branches that leave the loop without writing their key: {offenders}"
    )


def test_the_enum_is_still_the_two_values_the_backend_reads():
    """server.py reads features.address_mode with a `or "strict"` fallback and
    compares against "loose". If the accepted set ever drifts, a value can be
    stored that the addressing code silently treats as strict."""
    import server

    src = inspect.getsource(server.whatsapp_update_group_config)
    assert '("strict", "loose")' in src, (
        "the accepted address_mode values changed; check _is_bot_addressed, "
        "which only branches on 'loose'"
    )
