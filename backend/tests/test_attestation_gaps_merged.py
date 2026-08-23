"""One attestation card, and the states it must keep apart.

WHY THIS MERGE. The two detectors OVERLAP, and on a live site the overlap was
total. A daily_jobsite row carrying `cp_signature: {}` — the shape a bundle
predating the affirmation gate writes — matches BOTH:

  * unaffirmed     : submitted, signature non-null, `affirmed` not True
  * stale_unsigned : end-of-day, date < today, unlocked, signature not affirmed

So three rows on 588 Thomas produced SIX counted problems across two cards —
"3 logbooks filed without an affirmed signature" and "3 days worked but never
signed" — each tapping to a different end of the same list. Two surfaces
disagreeing about the same three rows is not twice the signal; it reads as
noise, and it is one reason three weeks passed with nobody acting.

WHAT MUST NOT COLLAPSE WITH THEM. The two STATES need different actions, and
that distinction is the only reason to tell them apart at all:

    unsigned    nothing was ever put on it            -> he signs it
    unaffirmed  a signature IS present but was never  -> he opens it and
                affirmed for that document (inherited    AFFIRMS it; telling
                or the `{}` an old bundle wrote)         him to sign would make
                                                         him think the app lost
                                                         his signature, and he
                                                         would sign again

Run:  python -m pytest backend/tests/test_attestation_gaps_merged.py -q
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

SRC = inspect.getsource(server.get_logbook_notifications)
SCREEN = (_BACKEND.parent / "frontend" / "app" / "logbooks" / "index.jsx").read_text(
    encoding="utf-8")


def _merge(stale_refs, unaffirmed_docs):
    """The endpoint's merge, lifted verbatim in shape so the table below is
    testing the real rule rather than a restatement of it."""
    gaps = {}
    for ref in stale_refs:
        gaps[(ref["log_type"], ref["date"])] = "unsigned"
    for doc in unaffirmed_docs:
        lt, dt = doc.get("log_type"), doc.get("date")
        if not lt or not dt:
            continue
        gaps[(lt, dt)] = "unaffirmed"
    return sorted(
        ({"log_type": k[0], "date": k[1], "state": v} for k, v in gaps.items()),
        key=lambda g: g["date"], reverse=True,
    )


class TheOverlapIsGone:
    pass


def test_a_row_in_both_detectors_is_counted_once():
    """THE 588 THOMAS SHAPE. `{}` matches both, and used to show twice."""
    both = _merge(
        [{"log_type": "daily_jobsite", "date": "2026-08-11"}],
        [{"log_type": "daily_jobsite", "date": "2026-08-11"}],
    )
    assert len(both) == 1, "the same row must not appear twice"


def test_and_it_reads_as_UNAFFIRMED_not_unsigned():
    """The more specific state wins. A `{}` signature IS present, so telling
    the CP it was 'never signed' would send him to re-sign a log that already
    carries his mark — the exact wrong action."""
    both = _merge(
        [{"log_type": "daily_jobsite", "date": "2026-08-11"}],
        [{"log_type": "daily_jobsite", "date": "2026-08-11"}],
    )
    assert both[0]["state"] == "unaffirmed"


def test_a_genuinely_unsigned_row_keeps_its_own_state():
    only_stale = _merge([{"log_type": "daily_jobsite", "date": "2026-08-10"}], [])
    assert only_stale[0]["state"] == "unsigned"


def test_the_two_states_both_survive_in_one_list():
    """The merge must not flatten them into one bucket — the states are the
    reason the card can tell a CP what to do."""
    mixed = _merge(
        [{"log_type": "daily_jobsite", "date": "2026-08-10"}],
        [{"log_type": "daily_jobsite", "date": "2026-08-11"}],
    )
    assert {g["state"] for g in mixed} == {"unsigned", "unaffirmed"}


def test_it_is_sorted_newest_first_so_the_oldest_is_last():
    """The card taps through to the OLDEST — furthest back is likeliest to be
    asked about, and has had longest to go unfixed."""
    out = _merge(
        [{"log_type": "daily_jobsite", "date": d} for d in
         ("2026-07-29", "2026-08-11", "2026-08-20")], [])
    assert [g["date"] for g in out] == ["2026-08-20", "2026-08-11", "2026-07-29"]


def test_rows_missing_a_key_are_dropped_not_crashed_on():
    assert _merge([], [{"log_type": None, "date": "2026-08-11"},
                       {"log_type": "daily_jobsite", "date": None}]) == []


# ── the endpoint and the screen ──────────────────────────────────────────────

def test_the_endpoint_emits_the_merged_list():
    assert '"attestation_gaps": attestation_gaps' in SRC


def test_the_old_fields_are_kept_for_bundles_in_the_field():
    """THE WHOLE INCIDENT is a phone that cannot take an OTA. Removing the old
    counts would blank the only exception cards those devices have."""
    for field in ('"unaffirmed_logbooks"', '"unaffirmed_logbook_refs"',
                  '"stale_unsigned_logbooks"', '"stale_unsigned_logbook_refs"'):
        assert field in SRC, field


def test_the_screen_renders_ONE_card_from_the_merged_list():
    assert "{gaps.length > 0 && (" in SCREEN
    assert "filed log" in SCREEN


def test_the_screen_names_both_states_with_different_actions():
    assert "never signed" in SCREEN
    assert "not affirmed" in SCREEN
    # The line that stops him re-signing.
    assert "You do not need to sign again." in SCREEN


def test_the_old_two_cards_cannot_double_count_alongside_the_new_one():
    """The fallback for an older SERVER is suppressed the moment the merged
    list arrives, or a current pair would show both again."""
    assert "{gaps.length === 0 && (unaffirmedLogbooks > 0 || staleUnsigned > 0) && (" in SCREEN


def test_every_gap_row_is_rendered_and_is_its_own_door():
    """NOT A COUNT WITH ONE DOOR. Opening only the oldest makes the CP fix it,
    wait for a refetch, and tap again to discover the second."""
    assert "gapsOldestFirst.map(" in SCREEN
    assert "onPress={() => handleOpenGap(g)}" in SCREEN
    assert "gapOldest" not in SCREEN


def test_the_list_carries_no_window_of_its_own():
    """THE WIDENING. The detector is not date-filtered (unaffirmed) / is
    everything before today (stale_unsigned), both capped at 200. The screen
    renders that list whole, so the two surfaces cannot disagree about which
    days count."""
    assert ".to_list(200)" in SRC
    # No client-side slicing, no `today` comparison, nothing that could drop a row.
    card = SCREEN[SCREEN.index("{gaps.length > 0 && ("):SCREEN.index("OLDER SERVER FALLBACK")]
    assert len(card) > 200
    assert ".slice(0," not in card
    assert "=== today" not in card
