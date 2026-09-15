"""A FALSE RED IN THE SAFE-LOOKING DIRECTION.

`scripts/verify_card_downscale.py` answers one question — does 1024 px still
read the card number and the expiry — and its EXIT CODE is the answer. The
docstring says so: "Read the status, not the prose."

WHAT IT ACTUALLY DID. `_norm` compared raw strings with nothing but
whitespace-stripping and upper():

    _norm('')      -> ''
    _norm('null')  -> 'NULL'      # not equal, so: LOST

Both mean THE MODEL READ NOTHING. On the ten-card run of 2026-09-15 that
produced a flagged row on a card whose expiry neither read could see, so a
clean result exited 1 and said "RAISE OSHA_VISION_MAX_EDGE and run this again
before shipping the current bound."

THAT IS THE DANGEROUS DIRECTION FOR A HARNESS TO BE WRONG IN. A false GREEN is
caught by the next person who looks at a card; a false RED trains the operator
to read the prose and ignore the status, which is exactly what the exit code
exists to stop. It also argues for a change (a bigger image, more latency, more
cost) that the evidence does not support.

THE FIX IS THE RULE THAT ALREADY EXISTS. `lib/ocr_text.norm_ocr_str` maps '',
'null', 'none', 'n/a' and friends to None at the boundary where the model's
answer is parsed. The verifier now runs BOTH SIDES through it before comparing,
so "nothing" equals "nothing" and only a real disagreement is a loss.

Run:  python -m pytest backend/tests/test_verify_card_downscale_norm.py -q
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent

# THIS FILE'S OWN PATH SETUP, not a neighbour's. A gate has gone green here
# before on an unrelated module's sys.path insert; both entries are inserted
# unconditionally so running this file ALONE is the same run as running it in
# the suite.
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))

import pytest  # noqa: E402

from lib.ocr_text import norm_ocr_str  # noqa: E402

import verify_card_downscale as vcd  # noqa: E402


# ── THE ARTEFACT THIS FILE IS NAMED FOR ─────────────────────────────────────
@pytest.mark.parametrize("a,b", [
    ("", "null"),          # the exact pair that flagged a clean row
    ("null", ""),          # and in the other order
    (None, "null"),        # a real JSON null against the string
    ("", None),
    ("null", "NULL"),      # case is not a difference either
    ("N/A", "none"),       # two spellings of the same nothing
    (None, "   "),         # whitespace-only is nothing
])
def test_two_ways_of_reading_nothing_are_not_a_disagreement(a, b):
    assert vcd._norm(a) == vcd._norm(b), (a, b)


def test_nothing_normalises_to_none_and_not_to_a_string():
    """Not merely EQUAL — both sides must land on None. An implementation that
    collapsed them to the shared string 'NULL' would pass the test above and
    still be comparing a sentinel against a real read."""
    for raw in ("", "null", "NONE", "n/a", None, "  ", "-"):
        assert vcd._norm(raw) is None, raw


# ── AND A REAL LOSS IS STILL A LOSS ─────────────────────────────────────────
@pytest.mark.parametrize("a,b", [
    ("JU0FMHPJQ1", "JU0FMHPJQ"),    # one character dropped by the downscale
    ("05/35", "35"),                # the Wilmer shape: half the field gone
    ("05/35", None),                # read at full size, lost at 1024
    ("W95MUFUCTS", ""),             # read, then nothing
    ("YHFGZBU4EZ", "null"),         # read, then the model's word for nothing
    ("4YU1RY8KKM", "4YU1RY8KKN"),   # a substitution, not a truncation
])
def test_a_genuine_difference_is_still_a_disagreement(a, b):
    assert vcd._norm(a) != vcd._norm(b), (a, b)


def test_a_real_value_is_never_swallowed_by_the_nullish_rule():
    """The failure mode of over-normalising: a card number that CONTAINS a
    nullish token must survive, because only the WHOLE field being nullish
    means nothing was read."""
    for raw in ("NULL1234AB", "NONEOFYOURS", "NA12345678"):
        assert vcd._norm(raw) is not None, raw
        assert vcd._norm(raw) != vcd._norm("")


def test_case_and_spacing_are_still_not_a_difference():
    """The behaviour `_norm` already had, kept. A stored card may hold any
    case and the model spaces its groups differently between reads."""
    assert vcd._norm("ju0f mhpj q1") == vcd._norm("JU0FMHPJQ1")
    assert vcd._norm(" 05/35 ") == vcd._norm("05/35")


# ── THE RULE HAS ONE ADDRESS ────────────────────────────────────────────────
def test_the_verifier_uses_the_shared_rule_and_does_not_restate_it():
    """A second copy of the nullish token list is a second thing to get wrong.
    `lib/ocr_text.py` exists precisely so the OSHA path and the COI path cannot
    drift; the verifier that JUDGES that path must not drift from it either."""
    src = inspect.getsource(vcd._norm)
    assert "norm_ocr_str" in src, (
        "the verifier is normalising by hand again; use lib/ocr_text"
    )
    assert "_NULLISH" not in src, (
        "the nullish token list has been copied into the verifier; there is "
        "one address for it and it is lib/ocr_text.py"
    )


def test_the_shared_rule_is_the_one_the_boundary_uses():
    """Identity, not similarity: whatever _norm does about nothingness has to
    be norm_ocr_str's answer, so widening the token list in one place widens
    it here too."""
    for raw in ("", "null", "None", "N/A", "nil", "--", "undefined", None):
        assert (vcd._norm(raw) is None) == (norm_ocr_str(raw) is None), raw


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
