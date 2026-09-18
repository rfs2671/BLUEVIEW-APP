"""ANGEL LOPEZ'S CARD WAS READ COMPLETELY AND THE ROW LOST EVERY FIELD OF IT.

── THE ROW, FROM PRODUCTION, 2026-09-18 ────────────────────────────────────

Worker `6a9576da611a543244a9ccac`, created 2026-08-31 12:43:06. His worker
document holds a COMPLETE card read -- name, number, class, colour, issue date
AND expiry -- and a 431358-byte card image in R2. His `certifications[0]`, the
row every screen and every gate actually reads, holds:

    {"type": "SST_FULL", "card_number": null, "issue_date": null,
     "expiration_date": null, "verified": false, "needs_review": false,
     "review_reason": null, "expiration_raw_rejected": null,
     "extraction_completeness": 0.0, ...}

No expiry, NO REJECTION RECORDED, NO REASON, and `needs_review: false` -- so
nothing put him in a queue, nothing told a reviewer what to look at, and the
register reads as though the card was never scanned. He registered 16 days
before the QWEN_MODEL change, so this is not a model failure and not a camera
failure: THE READ WORKED AND THE ROW LOST IT.

── WHY THIRTEEN CHECK-INS NEVER REPAIRED IT ────────────────────────────────

Thirteen, every one with `osha_data_sent = False` -- the returning-worker quick
path sends no card evidence. Two things then happen, and BOTH have to be true
for the row to survive untouched:

  1. `register_and_checkin` falls `osha_number` and `osha_card_image` back to
     the worker's stored values and DOES NOT fall `osha_data` back. So the
     builder ran with `od = {}` thirteen times while a complete stored read sat
     one field away on the same document.
  2. `build_worker_certifications`' dedup guard -- `if existing_sst is None:
     append` -- means an existing SST row is never revisited, and the update
     branch below it refuses to act on a scan that produced no expiry.

Thirteen chances, all skipped by design.

── WHAT NOBODY COULD FIND, AND WHY IT DOES NOT MATTER HERE ─────────────────

`needs_review: false` on that row has no explanation in this repository. Both
the current code and the code live at his registration compute `needs_review =
not (name_ok and number_ok and class_ok and bool(stored_exp))`, which is True
for that row; both repair scripts have never run (0 audit rows); and the dedup
guard prevents a later rebuild. He is a population of ONE -- the only worker in
79 with completeness 0.0 AND needs_review false. Most likely a hand edit in
mongosh, and the repo records a precedent for that.

So the provenance is unexplained and this file does not try to explain it. It
makes the SHAPE UNREACHABLE: a certification row that cannot say why it has no
expiry cannot be written at all, however the fields arrive.

Run:  python -m pytest backend/tests/test_a_row_with_no_expiry_says_why.py -q
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import server  # noqa: E402

# Nine days after the last of his thirteen taps, and inside every ceiling the
# expiry gate applies to his card, so nothing below passes or fails on the
# clock.
NOW = datetime(2026, 9, 18, 14, 0, tzinfo=timezone.utc)

# ── ANGEL'S EXACT SHAPE, VERBATIM ───────────────────────────────────────────
#
# Copied from the production document, not reconstructed. The point of using
# his real values is that every one of them is a field the row was SUPPOSED to
# carry: if a fixture had a nullish name or an unreadable date, a test could
# pass because there was nothing to lose.
ANGEL_OSHA_DATA = {
    "name": "Angel Lopez",
    "sst_number": "RUQ24T3LVF",
    "card_type": "SST",
    "card_class": "Worker",
    "issued": "03/01/2026",
    "expiration": "03/01/2031",
    "card_dominant_color": "BLUE",
    "card_color_confidence": "high",
    "card_color_conditions": [],
}

ANGEL_CERT = {
    "type": "SST_FULL",
    "card_number": None,
    "issue_date": None,
    "expiration_date": None,
    "verified": False,
    "needs_review": False,
    "review_reason": None,
    "expiration_raw_rejected": None,
    "extraction_completeness": 0.0,
    "class_source": "color_and_text",
    "card_color_seen": None,
}

ANGEL_WORKER = {
    "_id": "6a9576da611a543244a9ccac",
    "name": "Angel Lopez",
    "osha_number": "RUQ24T3LVF",
    # THE IMAGE IS IN R2, NOT INLINE. `osha_card_image` is absent on his
    # document; reading only that field reports him as having no card at all,
    # which is the mistake `card_image_may_be_replaced` documents.
    "osha_card_r2_key": "worker-osha-cards/6a9576da611a543244a9ccac/card.jpg",
    "osha_data": dict(ANGEL_OSHA_DATA),
    "certifications": [dict(ANGEL_CERT)],
}


def _angel():
    """A fresh copy. Every test here mutates rows, and a shared dict would let
    one test's repair satisfy the next test's assertion."""
    w = dict(ANGEL_WORKER)
    w["osha_data"] = dict(ANGEL_OSHA_DATA)
    w["certifications"] = [dict(ANGEL_CERT)]
    return w


def _sst(rows):
    return [r for r in rows if str(r.get("type") or "") in server.RECOGNIZED_SST_TYPES]


# ══ (b) A ROW WITH NO EXPIRY AND NO REASON CANNOT BE WRITTEN ═══════════════

class TestTheInvariantIsNamedAndCanFail:
    """The instrument first. A checker that cannot report Angel's own row as
    unsound proves nothing about the rows it passes."""

    def test_angels_stored_row_is_reported_unsound(self):
        fault = server.cert_row_fault(ANGEL_CERT)
        assert fault, "the checker cannot see the row this file is named after"
        assert "expir" in fault.lower()

    def test_a_row_that_says_why_is_sound(self):
        """THE CONTROL. If everything below passes because the checker refuses
        every row, it proves nothing."""
        row = dict(ANGEL_CERT, needs_review=True,
                   review_reason="EXPIRY_UNPARSEABLE",
                   expiration_raw_rejected="illegible")
        assert server.cert_row_fault(row) is None

    def test_an_OSHA_row_has_no_expiry_BY_DESIGN_and_is_sound(self):
        """SCOPE, and it is load-bearing. An OSHA card issued after 2020 is
        LIFETIME: `expiration_date: None` on an OSHA_10 row is the correct
        reading, not a lost one. An invariant that swept those in would flag
        every OSHA row in the database and be deleted by the next reader."""
        assert server.cert_row_fault(
            {"type": "OSHA_10", "expiration_date": None,
             "needs_review": False, "review_reason": None}) is None

    def test_a_rejection_that_kept_nothing_to_correct_from_is_unsound(self):
        """`expiration_raw_rejected` is what a human corrects FROM. A row that
        says EXPIRY_UNPARSEABLE and does not keep the string it refused sends a
        reviewer to look at a value the record no longer holds."""
        assert server.cert_row_fault(
            dict(ANGEL_CERT, needs_review=True,
                 review_reason="EXPIRY_UNPARSEABLE",
                 expiration_raw_rejected=None))

    def test_a_flag_lowered_over_a_missing_expiry_is_unsound(self):
        """Angel's other half: a reason present and the flag DOWN is still a
        row nobody is asked to look at."""
        assert server.cert_row_fault(
            dict(ANGEL_CERT, needs_review=False,
                 review_reason="EXPIRY_MISSING"))


class TestTheGateCannotReturnAnUnsoundVerdict:
    """(b) AT THE CHOKEPOINT. `evaluate_cert_expiry` and `derive_cert_review`
    were extracted so the scanner and the backfill share one gate. The
    invariant lives THERE, so neither caller can be the one that forgets it."""

    def test_no_expiry_at_all_comes_back_with_a_reason(self):
        """THE EXACT CALL THE RETURNING PATH MADE THIRTEEN TIMES. With `od =
        {}` the raw expiry is None, and this returned `(None, False, None)`:
        no expiry, no rejection, NO REASON. That tuple is Angel's row."""
        stored_exp, _suppressed, reason = server.evaluate_cert_expiry(
            None, None, "SST_FULL", NOW)
        assert stored_exp is None
        assert reason == "EXPIRY_MISSING"

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_every_way_of_saying_nothing_says_why(self, raw):
        _e, _s, reason = server.evaluate_cert_expiry(raw, None, "SST_FULL", NOW)
        assert reason == "EXPIRY_MISSING", repr(raw)

    def test_the_review_verdict_cannot_pass_a_missing_expiry_quietly(self):
        needs_review, reason, _c = server.derive_cert_review(
            True, True, True, None, "color_and_text", "EXPIRY_MISSING", None)
        assert needs_review is True
        assert reason == "EXPIRY_MISSING"

    def test_a_MORE_SPECIFIC_reason_still_wins(self):
        """EXPIRY_MISSING IS THE WEAKEST REASON, NOT THE STRONGEST, and this is
        the half that is easy to get wrong. "No expiry was read" is less
        informative than "his answer contradicts the card's colour"; ranked
        above them it would shadow CLASS_CONFLICTED, CLASS_SELF_REPORTED and
        CLASS_UNVERIFIED on every row that has no expiry -- which is most of
        the flagged rows on the live company."""
        _n, reason, _c = server.derive_cert_review(
            True, True, False, None, "color_only", "EXPIRY_MISSING",
            "CLASS_CONFLICTED")
        assert reason == "CLASS_CONFLICTED"
        _n, reason, _c = server.derive_cert_review(
            True, True, False, None, "text_only", "EXPIRY_MISSING", None)
        assert reason == "CLASS_UNVERIFIED"

    def test_a_rejected_raw_value_still_reports_its_own_reason(self):
        """Unchanged, and asserted so the new branch cannot have taken it
        over: a value that ARRIVED and was refused is a different event from a
        field that was never read."""
        assert server.evaluate_cert_expiry("illegible", None, "SST_FULL", NOW) \
            == (None, True, "EXPIRY_UNPARSEABLE")

    def test_the_reason_has_copy_a_reviewer_can_read(self):
        """A produced code with no mapped label renders as the bare "Needs
        review" fallback -- a queue entry the reviewer cannot act on, which is
        the exact failure derive_cert_review's own comment describes."""
        assert "EXPIRY_MISSING" in server.OSHA_REVIEW_LABELS


class TestTheBuilderCannotMintAngelsShape:

    @pytest.mark.parametrize("od", [
        {},                                        # the quick path: no evidence
        {"card_type": "SST"},                      # a card type and nothing else
        {"name": "Angel Lopez", "card_type": "SST", "card_class": "Worker",
         "card_dominant_color": "BLUE"},           # everything BUT the expiry
        {"name": "Angel Lopez", "card_type": "SST", "expiration": "illegible"},
        {"name": "Angel Lopez", "card_type": "SST", "expiration": "2035-05-31"},
    ])
    def test_no_minted_SST_row_has_a_null_expiry_and_no_reason(self, od):
        rows, _not_sst = server.build_worker_certifications(
            [], od, "RUQ24T3LVF", "data:image/jpeg;base64,XX", NOW)
        for row in _sst(rows):
            assert server.cert_row_fault(row) is None, (od, row)

    def test_the_row_the_quick_path_would_have_minted_says_why(self):
        rows, _n = server.build_worker_certifications(
            [], {}, "RUQ24T3LVF", "data:image/jpeg;base64,XX", NOW)
        row = _sst(rows)[0]
        assert row["expiration_date"] is None
        assert row["needs_review"] is True
        assert row["review_reason"] is not None


# ══ (a) THE STORED READ IS EVIDENCE, AND A REBUILD MAY NOT MAKE A ROW WORSE ═

class TestTheStoredReadFallsBack:

    def test_an_empty_submission_is_answered_by_the_stored_read(self):
        """THE FALLBACK THE OTHER TWO FIELDS ALREADY HAD. `osha_number` and
        `osha_card_image` have fallen back to the worker document since Task E;
        `osha_data` never did, which is why `resolved_kind` came out "SST" (the
        stored image made it so) while every FIELD of the card was missing."""
        assert server.merge_stored_card_read({}, ANGEL_OSHA_DATA) == ANGEL_OSHA_DATA
        assert server.merge_stored_card_read(None, ANGEL_OSHA_DATA) == ANGEL_OSHA_DATA

    def test_this_submission_wins_field_by_field(self):
        got = server.merge_stored_card_read(
            {"expiration": "04/01/2032"}, ANGEL_OSHA_DATA)
        assert got["expiration"] == "04/01/2032"      # today's read
        assert got["name"] == "Angel Lopez"           # yesterday's, kept

    @pytest.mark.parametrize("empty", [None, "", "  ", "null", "N/A"])
    def test_a_field_that_says_nothing_does_not_erase_one_that_said_something(
            self, empty):
        """NEVER WORSE, PER FIELD. "null" is the model's own word for "I could
        not read this" and it is a STRING: read as an answer it overwrites a
        good stored value with the word null, which has already reached filed
        compliance PDFs as a worker's name."""
        got = server.merge_stored_card_read(
            {"expiration": empty}, ANGEL_OSHA_DATA)
        assert got["expiration"] == "03/01/2031", repr(empty)

    def test_a_DIFFERENT_CARD_is_not_merged_at_all(self):
        """THE LIMIT OF THE FALLBACK, and the reason it is not just
        `osha_data or worker["osha_data"]`. The stored read is the LATEST scan
        and need not be a scan of the card in his hand. Filling this card's
        blank expiry from a different card's read would attribute one card's
        life to another card's number -- on a §3301 compliance record."""
        other = {"sst_number": "4YU1RY8KKM", "card_type": "SST"}
        got = server.merge_stored_card_read(other, ANGEL_OSHA_DATA)
        assert got == other
        assert "expiration" not in got

    def test_a_MARKER_is_never_inherited(self):
        """`class_source` says HOW a class was arrived at, about ONE
        submission. Inherited, a worker who typed his class once would carry
        `self_reported` on every later scan of the same card -- a real read
        demoted by an old claim -- and a stale marker is evidence about the
        wrong event either way."""
        got = server.merge_stored_card_read(
            {"card_class": "Supervisor"},
            dict(ANGEL_OSHA_DATA, class_source="self_reported"))
        assert "class_source" not in got

    def test_a_marker_on_THIS_submission_survives(self):
        got = server.merge_stored_card_read(
            {"card_class": "Supervisor", "class_source": "self_reported"},
            ANGEL_OSHA_DATA)
        assert got["class_source"] == "self_reported"


class TestAngelsRowIsRepairedByHisOwnRecord:
    """END TO END, through the builder, with his exact stored row as input."""

    def setup_method(self):
        w = _angel()
        self.rows, _n = server.build_worker_certifications(
            list(w["certifications"]),
            server.merge_stored_card_read({}, w["osha_data"]),
            w["osha_number"],
            "data:image/jpeg;base64,STORED",
            NOW,
        )
        self.row = _sst(self.rows)[0]

    def test_it_is_still_ONE_row(self):
        """THE DEDUP GUARD IS NOT REMOVED. Its job -- never mint a second SST
        row for one card -- is right and stays. What changes is that the update
        branch beneath it now has evidence to act on, so "never revisited"
        stops being the same thing as "never repaired"."""
        assert len(_sst(self.rows)) == 1

    def test_the_expiry_his_card_actually_carries_is_stored(self):
        assert self.row["expiration_date"] == datetime(2031, 3, 1, tzinfo=timezone.utc)

    def test_the_card_number_his_worker_document_carries_is_stored(self):
        assert self.row["card_number"] == "RUQ24T3LVF"

    def test_the_flag_is_RE_DERIVED_and_the_row_is_complete(self):
        """NOT HAND-LOWERED. Every field came back through
        `evaluate_cert_expiry` and `derive_cert_review` -- the plausibility
        ceiling and the `exp <= issue` check both had their say on this date
        and passed it. That exact shortcut is what parked PR #530."""
        assert self.row["needs_review"] is False
        assert self.row["review_reason"] is None
        assert self.row["extraction_completeness"] == 1.0

    def test_and_the_gate_now_reads_his_card_as_what_it_is(self):
        assert server._sst_cert_state(self.row, NOW) == "valid"

    def test_so_the_gate_stops_asking_him_to_photograph_it(self):
        """The consequence a worker feels. `worker_needs_card_scan` asked him
        for a photo every single morning of a card that had been read
        correctly, because the row said `unknown`."""
        w = _angel()
        assert server.worker_needs_card_scan(w, NOW) == (True, "CLASS_UNVERIFIED")
        w["certifications"] = self.rows
        assert server.worker_needs_card_scan(w, NOW) == (False, None)


class TestARebuildNeverProducesAWorseRow:

    def test_an_emptier_read_cannot_blank_a_good_stored_row(self):
        """The rule stated the other way round. A returning tap that carries
        nothing must leave a clean row exactly as it is -- not re-derive it
        from the absence."""
        clean = dict(ANGEL_CERT, card_number="RUQ24T3LVF",
                     expiration_date=datetime(2031, 3, 1, tzinfo=timezone.utc),
                     issue_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
                     extraction_completeness=1.0)
        rows, _n = server.build_worker_certifications(
            [clean], {}, "RUQ24T3LVF", "data:image/jpeg;base64,XX", NOW)
        row = _sst(rows)[0]
        assert row["expiration_date"] == datetime(2031, 3, 1, tzinfo=timezone.utc)
        assert row["card_number"] == "RUQ24T3LVF"
        assert row["needs_review"] is False

    def test_an_UNREADABLE_new_expiry_cannot_blank_a_good_stored_one(self):
        clean = dict(ANGEL_CERT, card_number="RUQ24T3LVF",
                     expiration_date=datetime(2031, 3, 1, tzinfo=timezone.utc),
                     extraction_completeness=1.0)
        rows, _n = server.build_worker_certifications(
            [clean], dict(ANGEL_OSHA_DATA, expiration="illegible"),
            "RUQ24T3LVF", "x", NOW)
        assert _sst(rows)[0]["expiration_date"] == datetime(
            2031, 3, 1, tzinfo=timezone.utc)

    def test_a_VERIFIED_row_is_still_never_touched(self):
        """Somebody looked at that card and confirmed it. A rebuild has less
        standing than a re-scan, and a re-scan may not modify it either."""
        confirmed = dict(ANGEL_CERT, verified=True, card_number="RUQ24T3LVF")
        rows, _n = server.build_worker_certifications(
            [confirmed], ANGEL_OSHA_DATA, "RUQ24T3LVF", "x", NOW)
        row = _sst(rows)[0]
        assert row["expiration_date"] is None
        assert row["card_number"] == "RUQ24T3LVF"
        assert len(_sst(rows)) == 1

    def test_a_BLANK_field_may_always_be_filled_from_evidence(self):
        """"NEVER WORSE" IS PER FIELD, AND THAT IS HOW IT RECONCILES WITH
        "MAY BE MADE BETTER". Overwriting a stored value needs the existing
        better-evidence rules (the row unverified AND flagged or expiry-less,
        the scan not suppressed). Filling a field that holds NOTHING needs
        none of them -- there is no answer to lose. Angel's `card_number: null`
        is repaired by this rule even on a tap whose expiry is unreadable."""
        rows, _n = server.build_worker_certifications(
            [dict(ANGEL_CERT)],
            dict(ANGEL_OSHA_DATA, expiration="illegible"),
            "RUQ24T3LVF", "x", NOW)
        assert _sst(rows)[0]["card_number"] == "RUQ24T3LVF"


# ══ (c) A ROW THAT COUNTS THE NUMBER AS PRESENT MUST STORE IT ══════════════

class TestTheCardNumberIsStoredWhereverItWasCounted:
    """`number_ok = bool(osha_number or od["sst_number"])` while
    `card_no = osha_number or None`. Two readings of one field, one line apart:
    the row scores the number as EXTRACTED and stores null. That is the second
    half of Angel's shape, and it is measurable without him."""

    def test_the_number_from_the_card_read_reaches_the_row(self):
        rows, _n = server.build_worker_certifications(
            [], ANGEL_OSHA_DATA, None, "data:image/jpeg;base64,XX", NOW)
        assert _sst(rows)[0]["card_number"] == "RUQ24T3LVF"

    def test_completeness_and_the_stored_number_can_never_disagree(self):
        """THE INVARIANT, NOT THE CASE. Asserting the one input pair proves the
        one input pair; this asserts the identity the two expressions are
        supposed to share."""
        for osha_number, sst_number in (
                ("RUQ24T3LVF", None), (None, "RUQ24T3LVF"),
                ("RUQ24T3LVF", "RUQ24T3LVF"), (None, None),
                (None, "  "), (None, "null")):
            rows, _n = server.build_worker_certifications(
                [], dict(ANGEL_OSHA_DATA, sst_number=sst_number),
                osha_number, "data:image/jpeg;base64,XX", NOW)
            row = _sst(rows)[0]
            counted = row["extraction_completeness"] == 1.0
            assert counted == bool(row["card_number"]), (
                osha_number, sst_number, row)

    def test_it_is_stored_in_the_NORMAL_form(self):
        """One man's one card must not read as two. `normalize_card_number`
        upper-cases because the register and the LL196 attestation do."""
        rows, _n = server.build_worker_certifications(
            [], dict(ANGEL_OSHA_DATA, sst_number="ruq24t3lvf"), None, "x", NOW)
        assert _sst(rows)[0]["card_number"] == "RUQ24T3LVF"


# ══ (f) MANUAL ENTRY STAYS, AND IT IS NEVER MISTAKEN FOR A READ ════════════

class TestATypedCardIsAClaimNotAReading:

    def test_a_manually_entered_card_is_ALWAYS_flagged(self):
        """He typed a number and an expiry off the card face. Both may be
        perfectly right; neither was READ. Today they land on a row
        indistinguishable from an OCR read of the same card."""
        rows, _n = server.build_worker_certifications(
            [], {"name": "Amaury Ayala", "sst_number": "CKALD4CRD7",
                 "card_type": "SST", "card_class": "Worker",
                 "expiration": "06/24/2027", "manual_entry": True},
            "CKALD4CRD7", None, NOW)
        row = _sst(rows)[0]
        assert row["needs_review"] is True
        assert row["review_reason"] is not None
        assert row["class_source"] == server.CLASS_SOURCE_SELF_REPORTED

    def test_a_typed_card_can_never_read_as_a_valid_credential(self):
        rows, _n = server.build_worker_certifications(
            [], {"name": "Amaury Ayala", "sst_number": "CKALD4CRD7",
                 "card_type": "SST", "card_class": "Worker",
                 "expiration": "06/24/2027", "manual_entry": True},
            "CKALD4CRD7", None, NOW)
        assert server._sst_cert_state(_sst(rows)[0], NOW) == "unknown"

    def test_and_he_is_asked_to_scan_it_on_his_NEXT_check_in(self):
        """THE EXISTING PATH, REUSED. #554 built `worker_needs_card_scan` and
        the returning screen's two controls for exactly this; a second prompt
        would be a second answer to one question."""
        rows, _n = server.build_worker_certifications(
            [], {"name": "Amaury Ayala", "sst_number": "CKALD4CRD7",
                 "card_type": "SST", "expiration": "06/24/2027",
                 "manual_entry": True}, "CKALD4CRD7", None, NOW)
        needs, why = server.worker_needs_card_scan({"certifications": rows}, NOW)
        assert needs is True
        assert why == "CLASS_UNVERIFIED"

    def test_an_OCR_READ_of_the_same_card_is_NOT_demoted(self):
        """THE CONTROL. If the marker demoted everything, the flag would mean
        nothing and the review queue would be the whole workforce."""
        rows, _n = server.build_worker_certifications(
            [], ANGEL_OSHA_DATA, "RUQ24T3LVF", "x", NOW)
        assert _sst(rows)[0]["needs_review"] is False


class TestARegistrationWithNoCardEvidenceIsRefused:
    """SERVER-SIDE, because `POST /checkin/register-and-checkin` reads
    `osha_card_image`, `osha_data` and `osha_number` with plain `data.get(...)`
    and raises nothing when all three are absent. The gate page's own guard is
    the only thing that has ever asked."""

    def test_no_image_and_nothing_typed_is_no_evidence(self):
        assert server.registration_card_evidence(None, None, None) is None
        assert server.registration_card_evidence(None, {}, "") is None
        assert server.registration_card_evidence(
            None, {"card_type": "SST"}, None) is None

    def test_a_photo_alone_is_evidence(self):
        assert server.registration_card_evidence(
            "data:image/jpeg;base64,XX", None, None) == "image"

    def test_a_typed_number_alone_is_evidence(self):
        assert server.registration_card_evidence(
            None, None, "RUQ24T3LVF") == "manual"
        assert server.registration_card_evidence(
            None, {"sst_number": "RUQ24T3LVF"}, None) == "manual"

    def test_a_typed_EXPIRY_alone_is_evidence(self):
        """`hasManualCardDetails()` accepts EITHER a number or an expiration,
        and the server must accept exactly what the page offers or a worker who
        followed the instructions on the screen is refused by the API."""
        assert server.registration_card_evidence(
            None, {"expiration": "06/24/2027"}, None) == "manual"

    @pytest.mark.parametrize("nullish", ["null", "N/A", "none", "  "])
    def test_the_models_word_for_nothing_is_not_evidence(self, nullish):
        assert server.registration_card_evidence(
            None, {"sst_number": nullish}, nullish) is None

    def test_the_endpoint_actually_ASKS(self):
        """A predicate nothing calls is a rule nobody enforces. Read from the
        stripped source so the assertion cannot be satisfied by a comment
        saying the call is there."""
        from tests.source_text import code_of
        src = code_of("server.py")
        assert "registration_card_evidence(" in src
        assert src.count("registration_card_evidence(") >= 2, (
            "declared and never called")
