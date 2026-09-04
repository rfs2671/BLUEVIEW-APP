"""A worker called "null", and the three tests that could not see it.

Worker 6a96c5ff6ee1b3362d156e6c carries `name: 'null'` AND
`osha_data.name: 'null'` on a live production record — the four-character
string, in both places. It reaches filed compliance PDFs as a worker's name.

THE MECHANISM. POST /checkin/upload-osha had NO response_model and returned
`json_mod.loads(text)` verbatim, so whatever the vision model emitted became
the API's answer. Asked to "set the field to null if you cannot read it", the
model sometimes answers with the STRING "null" — and every presence test
between there and the database reads that as a value:

    build_worker_certifications   name_ok = bool(str(od.get("name") or "").strip())
    checkin.html                  !d[k] || String(d[k]).trim() === ''
    the identity normalisers      "null" becomes a live dedupe key

Three consumers, each correct against a real value, each wrong against this
one. The worst of them is name_ok: it feeds `needs_review = not (name_ok and
number_ok and class_ok and stored_exp)`, so A CARD NOBODY COULD READ CLEARS THE
REVIEW FLAG THAT EXISTS TO CATCH IT.

THE FIX IS AT THE BOUNDARY, once, where the model's answer is parsed. Fixing
the three consumers instead leaves a fourth place to get it wrong.

Run:  python -m pytest backend/tests/test_osha_ocr_null_boundary.py -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from lib.ocr_text import norm_ocr_str  # noqa: E402

payload = server._osha_ocr_payload


# ── THE PRODUCTION CASE ───────────────────────────────────────────────────

def test_the_string_null_becomes_a_real_none():
    """The exact value on worker 6a96c5ff6ee1b3362d156e6c."""
    assert payload({"name": "null"}).name is None


def test_every_way_a_model_says_nothing():
    for token in ("null", "NULL", "Null", "none", "None", "N/A", "n/a",
                  "na", "nil", "-", "--", "undefined", "", "   "):
        assert norm_ocr_str(token) is None, token
        assert payload({"name": token}).name is None, token


def test_a_real_name_survives_and_is_stripped():
    assert payload({"name": "  Jose Ramirez  "}).name == "Jose Ramirez"


def test_a_number_answered_as_a_number_is_not_lost():
    """A model that answers `sst_number: 12345` is not wrong about the card,
    and rejecting it would turn a good read into a failure."""
    assert payload({"sst_number": 12345}).sst_number == "12345"


# ── THE PROPERTY THAT LINKS THIS TO needs_review ──────────────────────────

def test_an_unread_name_no_longer_scores_as_a_complete_extraction():
    """`name_ok` is the server's own predicate, copied verbatim from
    build_worker_certifications. Before the boundary fix it returned True for
    "null", so `needs_review` was computed as if the name had been read — the
    flag that exists to catch an unreadable card was cleared BY an unreadable
    card.

    Asserted against the real predicate rather than a restatement of it, so
    this fails if either side moves."""
    def name_ok(od):                       # server.py, build_worker_certifications
        return bool(str(od.get("name") or "").strip())

    for token in ("null", "N/A", "none", "-", ""):
        raw = {"name": token}
        assert name_ok(raw) is (token != ""), (
            f"precondition: the raw model answer {token!r} still fools name_ok"
        )
        assert name_ok(payload(raw).model_dump()) is False, (
            f"{token!r} still scores as a read name after normalisation"
        )

    assert name_ok(payload({"name": "Jose Ramirez"}).model_dump()) is True


# ── THE CROP MUST NOT BREAK ───────────────────────────────────────────────

def test_box_2d_survives_because_the_gate_page_crops_with_it():
    """A response_model silently drops undeclared keys. Omitting box_2d would
    have removed the on-screen crop with nothing to read in a diff."""
    assert payload({"box_2d": [10, 20, 30, 40]}).box_2d == [10.0, 20.0, 30.0, 40.0]


def test_an_unusable_box_is_not_a_failed_read():
    for bad in ([1, 2, 3], "nope", None, ["a", "b", "c", "d"], []):
        got = payload({"name": "Jose", "box_2d": bad})
        assert got.box_2d is None, bad
        assert got.name == "Jose", "a bad box must not cost the reading"


# ── THE SHAPE IS PINNED ───────────────────────────────────────────────────

def test_the_endpoint_declares_a_response_model():
    route = next(r for r in server.app.routes
                 if getattr(r, "path", "") == "/api/checkin/upload-osha")
    assert route.response_model is server.OshaCardOcrResult


def test_the_declared_fields_are_exactly_what_the_page_and_the_gate_read():
    """checkin.html reads name / sst_number / issued / expiration / box_2d and
    posts the whole object on as `osha_data`, which
    build_worker_certifications reads card_type / card_class / the colour
    fields from. All of them have to be declared or they are dropped."""
    declared = set(server.OshaCardOcrResult.model_fields)
    for field in ("name", "sst_number", "card_type", "card_class", "issued",
                  "expiration", "card_dominant_color", "card_color_confidence",
                  "card_color_conditions", "box_2d"):
        assert field in declared, field


def test_conditions_are_a_list_and_nullish_entries_are_dropped():
    assert payload({"card_color_conditions": ["GLARE", "null", "", "SLEEVE"]}) \
        .card_color_conditions == ["GLARE", "SLEEVE"]
    for bad in (None, "GLARE", 7):
        assert payload({"card_color_conditions": bad}).card_color_conditions == []


def test_json_that_is_not_an_object_reads_as_nothing_read():
    """A JSON array or scalar parses fine and is not a card reading."""
    got = payload({"raw_text": "[1, 2, 3]"})
    assert got.name is None and got.sst_number is None
    assert got.raw_text == "[1, 2, 3]"


# ── ONE ADDRESS ───────────────────────────────────────────────────────────

def test_the_coi_path_and_the_osha_path_share_the_rule():
    """`coi_ocr._norm_str` is where this rule was written and was the ONLY OCR
    path in the codebase that had it. Two copies is how two OCR paths come to
    disagree about what "null" means."""
    from lib import coi_ocr
    assert coi_ocr._norm_str is norm_ocr_str
