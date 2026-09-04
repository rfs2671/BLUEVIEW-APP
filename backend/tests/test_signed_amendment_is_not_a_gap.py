"""A correction he signed must stop asking him to sign it.

THE DEFECT, EXACTLY. `stale_unsigned_docs` is the raw result of a query whose
selector is `END_OF_DAY type + date < today + not locked + not deleted + not
withdrawn`. It carries NO signature clause. The affirmation test lives in a
different consumer twenty lines down (`stale_unsigned_refs`), and the amendment
loop did not use it -- so a signed, affirmed, submitted amendment was stamped
`amendment_unsigned`, and because that override runs LAST it beat the two
states that do consult the signature.

Confirmed on production 2026-09-04: logbook 6a7f795de9966c6e441b797b,
daily_jobsite 2026-08-14, is_amendment true, status submitted, cp_signature
{timestamp: 2026-09-04T12:04:05.495Z, affirmed: true}, is_locked false. The
signature landed, signature_events carried the matching cp_sign three seconds
later, and the screen still said the correction needed a signature.

WHY IT WAS INVISIBLE FOR WEEKS. The freeze sweep locks an affirmed row at
03:00, which takes it out of the selector, so the banner cleared itself
overnight every time. The window is up to 27 hours and it reopens with every
amendment. Two of the CP's drafts are re-signature attempts on corrections that
had already landed.

Run:  python -m pytest backend/tests/test_signed_amendment_is_not_a_gap.py -q
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

LT, DATE = "daily_jobsite", "2026-08-14"
AFFIRMED = {"paths": [[1, 2]], "affirmed": True,
            "timestamp": "2026-09-04T12:04:05.495Z"}


def _amend(**over):
    doc = {
        "log_type": LT, "date": DATE, "is_amendment": True,
        "amendment_reason": "Headcount corrected from the signed sheet.",
        "created_by_name": "R. Fishman", "cp_signature": None,
    }
    doc.update(over)
    return doc


def _states(gaps):
    return {(g["log_type"], g["date"]): g["state"] for g in gaps}


def _merge(stale=(), unaffirmed=(), inkless=(), refs=None):
    """`refs` defaults to the endpoint's own rule: a stale doc becomes a ref
    only when its signature is NOT affirmed. Passing the real derivation rather
    than a hand-built list keeps the two halves from drifting apart here."""
    stale = list(stale)
    if refs is None:
        refs = [{"log_type": d["log_type"], "date": d["date"]} for d in stale
                if not server._is_affirmed_signature(d.get("cp_signature"))]
    return server.merge_attestation_gaps(
        stale, refs, list(inkless), list(unaffirmed),
    )


# ── THE FIX ───────────────────────────────────────────────────────────────

def test_a_signed_affirmed_amendment_raises_no_gap():
    gaps = _merge(stale=[_amend(cp_signature=AFFIRMED)])
    assert gaps == [], (
        "A correction the CP signed AND affirmed must not appear on the "
        "attestation card at all. This is the row from production."
    )


# ── WHAT MUST NOT REGRESS ─────────────────────────────────────────────────

def test_an_unsigned_amendment_is_still_flagged():
    gaps = _merge(stale=[_amend(cp_signature=None)])
    assert _states(gaps) == {(LT, DATE): "amendment_unsigned"}


def test_an_empty_dict_signature_is_still_flagged():
    """`cp_signature: {}` is the shape a pre-affirmation bundle wrote. It is
    signature-SHAPED and truthy and nobody attested to it."""
    gaps = _merge(stale=[_amend(cp_signature={})])
    assert _states(gaps) == {(LT, DATE): "amendment_unsigned"}


def test_ink_without_affirmation_is_still_flagged():
    gaps = _merge(stale=[_amend(cp_signature={"paths": [[1, 2]]})])
    assert _states(gaps) == {(LT, DATE): "amendment_unsigned"}


def test_the_amendment_annotation_survives_on_an_unsigned_parent():
    """A parent and its child share (log_type, date). If the PARENT is still
    unsigned, its own row is raised -- and must still be able to say the day
    was amended, which is why the meta map is populated for every amendment
    and only the GAP is withheld."""
    gaps = _merge(stale=[_amend(cp_signature=AFFIRMED)],
                  refs=[{"log_type": LT, "date": DATE}])
    assert _states(gaps) == {(LT, DATE): "unsigned"}, \
        "the parent's own deficiency still raises its row"
    assert gaps[0].get("amendment"), \
        "and the row still carries the amendment annotation"
    assert gaps[0]["amendment"]["has_reason"] is True


def test_unaffirmed_still_beats_unsigned():
    gaps = _merge(
        stale=[{"log_type": LT, "date": DATE, "cp_signature": None}],
        unaffirmed=[{"log_type": LT, "date": DATE}],
    )
    assert _states(gaps) == {(LT, DATE): "unaffirmed"}


# ── THE OTHER HALF: THE ROW HAS TO LEAVE THE SELECTOR, NOT JUST THE CARD ──
#
# The guard above stops a signed amendment being SHOWN as a gap. It does not
# stop it MATCHING `stale_unsigned_docs`, which it would go on doing every
# night for as long as it stayed unlocked. Both ship together for that reason.

AFFIRMED_SIG = AFFIRMED
INHERITED_SIG = {"paths": [[1, 2]]}                 # ink, never affirmed here
LEGACY_SIG = "data:image/png;base64,iVBORw0KGgo="   # a bare string
EMPTY_SIG = {}                                      # what production held


def test_a_signed_affirmed_amendment_freezes_on_submit():
    assert server.submit_freezes_record("daily_jobsite", True, AFFIRMED_SIG) is True


def test_an_end_of_day_log_does_not_freeze_on_submit():
    """The sweep closes these, and freezing on submit would seal a narrative
    the CP is still adding to at 9am."""
    assert server.submit_freezes_record("daily_jobsite", False, AFFIRMED_SIG) is False
    assert server.submit_freezes_record("daily_jobsite", None, AFFIRMED_SIG) is False


def test_an_unaffirmed_amendment_never_freezes():
    """A wrongly sealed record cannot be opened. Same bar as the sweep."""
    for sig in (None, EMPTY_SIG, INHERITED_SIG, LEGACY_SIG):
        assert server.submit_freezes_record("daily_jobsite", True, sig) is False, sig


def test_the_two_halves_agree():
    """The predicate that FREEZES and the predicate that RAISES A GAP must be
    complements on an amendment, or a row is either sealed while still being
    asked for, or shown as done while still open."""
    for sig in (None, EMPTY_SIG, INHERITED_SIG, LEGACY_SIG, AFFIRMED_SIG):
        freezes = server.submit_freezes_record("daily_jobsite", True, sig)
        raises = bool(_merge(stale=[_amend(cp_signature=sig)]))
        assert freezes is not raises, (
            f"{sig!r}: freezes={freezes} raises_gap={raises} — the two halves "
            "disagree about the same signature"
        )
