"""The second producer of the "null" chain, and nobody knew it was live.

`POST /enrollment/parse_card` in card_audit.py does the same job as
`upload_osha_card` in server.py — photograph a card, ask a VLM to read it — and
carried the same defect, authored separately:

    its prompt says "If a field is not visible, set it to null"
    it did a bare `json.loads(txt)` and used the result
    `full_legal_name` flows to /enrollment/complete and into worker_enrollments

Two independent implementations of one defect, in two files, neither written
with knowledge of the other.

IT WAS MISSED BY THE OCR ENUMERATION. Twelve vision call sites were swept for
this rule on 2026-09-04 and this one was not among them, because it lives on a
router four of whose six routes are shadowed by server.py — so it read as dead.
The accident that hides it from a reviewer hid it from the sweep. That is the
sharpest form of a check that could not reach its subject: the subject was
concealed by something unrelated to the check.

Run:  python -m pytest backend/tests/test_parse_card_null_boundary.py -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import card_audit  # noqa: E402
from lib.ocr_text import norm_ocr_str  # noqa: E402

norm = card_audit._normalised_card


def test_the_string_null_does_not_become_a_legal_name():
    assert norm({"full_legal_name": "null"})["full_legal_name"] == ""


def test_every_nullish_token_on_every_string_field():
    for field in ("card_id", "full_legal_name", "expiration_date",
                  "issuing_course_provider"):
        for token in ("null", "NULL", "None", "n/a", "N/A", "-", "undefined", "  "):
            assert norm({field: token})[field] == "", (field, token)


def test_a_real_reading_survives_and_is_stripped():
    got = norm({"card_id": "  ABC12345  ", "full_legal_name": " Jose Ramirez ",
                "card_type": "SST", "issuing_course_provider": "NYC DOB"})
    assert got["card_id"] == "ABC12345"
    assert got["full_legal_name"] == "Jose Ramirez"
    assert got["card_type"] == "SST"
    assert got["issuing_course_provider"] == "NYC DOB"


def test_card_type_falls_back_to_the_enum_not_to_none():
    """Every reader downstream compares card_type against CardType. A None
    there would be a second shape for all of them to handle."""
    for bad in (None, "null", "", "N/A"):
        assert norm({"card_type": bad})["card_type"] == card_audit.CardType.UNKNOWN.value


def test_the_shape_is_fixed_whatever_the_model_sent():
    """A response_model cannot be used — this route returns HTMLResponse — so
    the shape is pinned where the JSON is parsed instead."""
    expected = {"card_id", "full_legal_name", "expiration_date", "card_type",
                "issuing_course_provider"}
    assert set(norm({}).keys()) == expected
    assert set(norm({"surprise": "x", "full_legal_name": "Jose"}).keys()) == expected
    for junk in (None, [], "text", 7):
        assert set(norm(junk).keys()) == expected, junk


def test_all_three_construction_sites_go_through_it():
    """parse_card builds `parsed` three ways — no VLM configured, a successful
    read, and an exception. All three must produce the same normalised shape or
    the correction form downstream gets two."""
    import ast
    import inspect
    import textwrap
    src = textwrap.dedent(inspect.getsource(card_audit.enrollment_parse_card))
    tree = ast.parse(src)
    assigns = [ast.unparse(n.value) for n in ast.walk(tree)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "parsed"
                       for t in n.targets)]
    # FOUR, not three: `parsed = {}` initialises it before the try, so that a
    # raise before any branch still leaves the name bound. The three that
    # BUILD a reading are what must be normalised.
    assert len(assigns) == 4, f"expected 4 `parsed =` sites, found {assigns}"
    builders = [r for r in assigns if r != "{}"]
    assert len(builders) == 3, builders
    for rhs in builders:
        assert "_normalised_card" in rhs, rhs


def test_it_shares_the_rule_with_the_osha_path():
    """Two OCR paths that disagree about what "null" means is exactly the drift
    lib/ocr_text.py exists to prevent."""
    assert card_audit.norm_ocr_str is norm_ocr_str
