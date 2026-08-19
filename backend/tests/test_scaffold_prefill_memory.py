"""A blank field must not erase what the project already remembers.

update_scaffold_info stripped only None, so "" went through and overwrote the
stored value. These fields exist to be remembered — the endpoint's docstring
says so — and a screen posting the whole form with one field blank erased the
permit number, expiry or erector. The next prefill came back blank and the CP
saw a form he had already filled asking again.
"""
import inspect
import re

import server


def _supplied():
    """The predicate as the endpoint actually defines it, executed not grepped."""
    src = inspect.getsource(server.update_scaffold_info)
    m = re.search(r"def _supplied\(v\):\n(?:.*\n)*?\s*return .*\n", src)
    assert m, "the _supplied predicate is no longer where this test reads it"
    body = m.group(0)
    ns = {}
    exec("\n".join(line[4:] if line.startswith("    ") else line
                   for line in body.splitlines()), ns)
    return ns["_supplied"]


def test_a_blank_string_is_not_supplied():
    f = _supplied()
    for blank in ("", "   ", "\t", "\n"):
        assert f(blank) is False, f"{blank!r} would overwrite remembered data"


def test_a_missing_key_is_not_supplied():
    assert _supplied()(None) is False


def test_a_real_value_is_supplied():
    f = _supplied()
    for v in ("PERMIT-123", "2026-01-01", " x ", "0"):
        assert f(v) is True, f"{v!r} was dropped — a real answer must be stored"


def test_false_and_zero_ARE_supplied():
    """The opposite-sign version of the same bug.

    drawings_on_site False, num_platforms 0 and scaffold_erected False are real
    answers. A `bool(v)` filter would drop all three.
    """
    f = _supplied()
    assert f(False) is True, "False was dropped — a CP answering 'no' was ignored"
    assert f(0) is True, "0 was dropped — zero platforms is an answer"


def test_the_endpoint_no_longer_filters_on_none_alone():
    src = inspect.getsource(server.update_scaffold_info)
    assert "if v is not None}" not in src, (
        "the None-only filter is back; \"\" would wipe remembered data again")
    assert "_supplied(v)" in src, "the update is no longer built through the predicate"


def test_updated_at_survives_a_save_that_supplied_nothing():
    """A save with every field blank still records that he looked."""
    src = inspect.getsource(server.update_scaffold_info)
    i = src.index('"updated_at"')
    j = src.index("_supplied(v)")
    assert i < j, "updated_at must be stamped before the filter runs"
    assert _supplied()(server.datetime.now(server.timezone.utc)) is True
