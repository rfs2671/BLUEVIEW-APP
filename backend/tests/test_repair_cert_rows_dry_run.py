"""THE DRY RUN, AS A TEST, BECAUSE A CONSOLE RUN IS NOT REPEATABLE.

`backend/scripts/repair_cert_rows_from_stored_read.py` needs MONGO_URL and an
Atlas connection to report. Its PLANNER does not: `plan_for_worker` is pure, so
the plan for a given document is a fact this file can assert rather than a
paragraph in a PR body that nobody can re-derive next month.

── WHAT THESE FIXTURES ARE, EXACTLY ────────────────────────────────────────

Worker 6a9576da611a543244a9ccac is VERBATIM: his `osha_data`, his
`certifications[0]` and his R2 card key are copied from the production
document, field for field.

THE OTHER FIVE ARE NOT WHOLE DOCUMENTS AND MUST NOT BE READ AS ONE. What was
measured about them is the set of REFUSED RAW EXPIRY STRINGS -- `illegible`,
`05/35`, `10272029` (Juan Lopez), `null`, `062427` -- each with
`EXPIRY_UNPARSEABLE` and `needs_review: true`. The rows below carry those
strings on rows built to the shape the scanner writes. So the assertions here
are about WHAT THE PLANNER DOES WITH EACH STRING, which is the question the
dry run has to answer, and NOT a claim about those five men's other fields.

A live dry run against Atlas is still the thing that reports the real six rows,
and it is what an operator should read before passing `--i-know`.

Run:  python -m pytest backend/tests/test_repair_cert_rows_dry_run.py -q
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))

import server  # noqa: E402
import repair_cert_rows_from_stored_read as repair  # noqa: E402

NOW = datetime(2026, 9, 18, 14, 0, tzinfo=timezone.utc)

ANGEL = {
    "_id": "6a9576da611a543244a9ccac",
    "name": "Angel Lopez",
    "osha_number": "RUQ24T3LVF",
    "osha_card_r2_key": "worker-osha-cards/6a9576da611a543244a9ccac/card.jpg",
    "osha_data": {
        "name": "Angel Lopez", "sst_number": "RUQ24T3LVF", "card_type": "SST",
        "card_class": "Worker", "issued": "03/01/2026",
        "expiration": "03/01/2031", "card_dominant_color": "BLUE",
        "card_color_confidence": "high", "card_color_conditions": [],
    },
    "certifications": [{
        "type": "SST_FULL", "card_number": None, "issue_date": None,
        "expiration_date": None, "verified": False, "needs_review": False,
        "review_reason": None, "expiration_raw_rejected": None,
        "extraction_completeness": 0.0, "class_source": "color_and_text",
        "card_color_seen": None,
    }],
}


def _rejected(name, raw, card_number="JH447TBBXG", sst_type="SST_FULL"):
    """A row in the shape the scanner writes when the expiry gate refused a
    value: the raw string kept, the flag up, the reason named."""
    return {
        "_id": f"id_{name.replace(' ', '_').lower()}",
        "name": name,
        "osha_number": card_number,
        "osha_data": {"name": name, "sst_number": card_number,
                      "card_type": "SST", "card_class": "Worker",
                      "expiration": raw},
        "certifications": [{
            "type": sst_type, "card_number": card_number, "issue_date": None,
            "expiration_date": None, "verified": False, "needs_review": True,
            "review_reason": "EXPIRY_UNPARSEABLE",
            "expiration_raw_rejected": raw, "extraction_completeness": 0.75,
            "class_source": "text_only", "card_color_seen": None,
        }],
    }

THE_FIVE = [
    _rejected("Juan Lopez", "10272029"),
    _rejected("Worker B", "illegible"),
    _rejected("Worker C", "05/35"),
    _rejected("Worker D", "null"),
    _rejected("Worker E", "062427"),
]


def _plan(worker):
    plans = repair.plan_for_worker(worker, NOW)
    assert len(plans) == 1, plans
    return plans[0]


class AngelsRowIsRepairedFromHisOwnDocument(unittest.TestCase):

    def setUp(self):
        self.p = _plan(ANGEL)

    def test_it_is_in_scope_because_the_row_says_nothing(self):
        self.assertTrue(self.p["fault_before"])
        self.assertIn("review_reason", self.p["fault_before"])

    def test_the_expiry_comes_from_his_stored_read(self):
        self.assertEqual(self.p["raw"], "03/01/2031")
        self.assertEqual(self.p["raw_from"], "worker.osha_data.expiration")
        self.assertEqual(self.p["after"]["expiration_date"],
                         datetime(2031, 3, 1, tzinfo=timezone.utc))

    def test_the_card_number_too(self):
        self.assertIsNone(self.p["before"]["card_number"])
        self.assertEqual(self.p["after"]["card_number"], "RUQ24T3LVF")

    def test_the_verdict_is_RE_DERIVED_and_the_row_comes_out_clean(self):
        """Through `evaluate_cert_expiry` and `derive_cert_review`, so the
        plausibility ceiling and the `exp <= issue` check both had their say on
        03/01/2031 against an issue date of 03/01/2026 and passed it."""
        self.assertFalse(self.p["after"]["needs_review"])
        self.assertIsNone(self.p["after"]["review_reason"])
        self.assertEqual(self.p["after"]["extraction_completeness"], 1.0)
        self.assertEqual(self.p["after"]["sst_state"], "valid")

    def test_the_invariant_closes_on_it(self):
        self.assertIsNone(self.p["fault_after"])

    def test_and_his_card_image_BECOMES_UNREPLACEABLE(self):
        """STATED, NOT INHERITED. `card_image_may_be_replaced` reads
        `needs_review or expiration_date is None`; clearing both flips it. He
        HAS an image -- 431358 bytes in R2 -- so unlike backfill_iso_expiry's
        twelve, this run really does move the predicate for him. It is the
        right outcome (his row will describe exactly that photograph) and
        DELETE /workers/{id}/osha-card-image remains the audited correction."""
        self.assertTrue(self.p["img_before"])
        self.assertFalse(self.p["img_after"])
        self.assertTrue(self.p["img_locks"])

    def test_the_write_is_a_targeted_set_not_a_row_replacement(self):
        self.assertEqual(self.p["action"], "recover")
        self.assertEqual(set(self.p["set"]), {
            "card_number", "issue_date", "expiration_date",
            "expiration_raw_rejected", "needs_review", "review_reason",
            "extraction_completeness"})
        self.assertNotIn("type", self.p["set"])
        self.assertNotIn("class_source", self.p["set"])
        self.assertNotIn("verified", self.p["set"])


class TheFiveThatSaidWhy(unittest.TestCase):
    """They recorded their reason, which is the CORRECT behaviour, so four of
    the five are untouched. The fifth changed because the PARSER changed."""

    def test_juans_expiry_is_recovered_by_the_widened_parser(self):
        p = _plan(THE_FIVE[0])
        self.assertEqual(p["raw"], "10272029")
        self.assertEqual(p["raw_from"], "row.expiration_raw_rejected")
        self.assertEqual(p["after"]["expiration_date"],
                         datetime(2029, 10, 27, tzinfo=timezone.utc))
        self.assertFalse(p["after"]["needs_review"])
        self.assertIsNone(p["after"]["expiration_raw_rejected"])
        self.assertEqual(p["action"], "recover")

    def test_the_other_four_are_LEFT_and_keep_their_reason(self):
        for w in THE_FIVE[1:]:
            with self.subTest(worker=w["name"]):
                p = _plan(w)
                self.assertEqual(p["action"], "leave", p["raw"])
                self.assertEqual(p["set"], {})
                self.assertIsNone(p["after"]["expiration_date"])
                self.assertEqual(p["after"]["review_reason"],
                                 "EXPIRY_UNPARSEABLE")
                self.assertTrue(p["after"]["needs_review"])
                self.assertEqual(p["after"]["expiration_raw_rejected"], p["raw"])
                self.assertIsNone(p["fault_after"])

    def test_none_of_them_was_unsound_to_begin_with(self):
        """THE CONTROL on `fault_before`. If the checker reported every row as
        unsound, Angel's finding would mean nothing."""
        for w in THE_FIVE:
            with self.subTest(worker=w["name"]):
                self.assertIsNone(_plan(w)["fault_before"])


class WhatItRefusesToTouch(unittest.TestCase):

    def test_a_VERIFIED_row_is_skipped(self):
        w = dict(ANGEL)
        w["certifications"] = [dict(ANGEL["certifications"][0], verified=True)]
        p = _plan(w)
        self.assertEqual(p["action"], "skip-verified")
        self.assertEqual(p["set"], {})

    def test_a_row_naming_a_DIFFERENT_CARD_gets_no_stored_expiry(self):
        """`osha_data` is the LATEST scan and need not be the scan this row
        came from. Reading an expiry out of it for a different card number
        would attribute one card's life to another card's number."""
        w = dict(ANGEL)
        w["certifications"] = [dict(ANGEL["certifications"][0],
                                    card_number="4YU1RY8KKM")]
        p = _plan(w)
        self.assertEqual(p["raw_from"], "different-card")
        self.assertIsNone(p["after"]["expiration_date"])
        self.assertEqual(p["after"]["card_number"], "4YU1RY8KKM")

    def test_but_it_still_makes_that_row_SAY_WHY(self):
        """The expiry is refused and the row is repaired anyway -- because the
        defect being closed is "no expiry AND no reason", and the reason half is
        answerable without the date."""
        w = dict(ANGEL)
        w["certifications"] = [dict(ANGEL["certifications"][0],
                                    card_number="4YU1RY8KKM")]
        p = _plan(w)
        self.assertTrue(p["fault_before"])
        self.assertIsNone(p["fault_after"])
        self.assertTrue(p["after"]["needs_review"])
        self.assertEqual(p["after"]["review_reason"], "EXPIRY_MISSING")

    def test_a_row_that_is_already_sound_and_complete_is_out_of_scope(self):
        """THE SELECTOR'S OTHER HALF. The query is deliberately wider than the
        rule, so `row_is_in_scope` is what keeps a clean row out -- and a
        planner that returned a plan for every row would rewrite the database."""
        w = dict(ANGEL)
        w["certifications"] = [dict(
            ANGEL["certifications"][0], card_number="RUQ24T3LVF",
            expiration_date=datetime(2031, 3, 1, tzinfo=timezone.utc),
            extraction_completeness=1.0)]
        self.assertEqual(repair.plan_for_worker(w, NOW), [])

    def test_an_expiry_past_the_ceiling_comes_back_REFUSED(self):
        """A RECOVERED DATE CAN BE REFUSED AGAIN, and that is the point of
        re-deriving rather than assigning. 2040 is fourteen years out; the
        class-aware plausibility ceiling rejects it, and the row is left
        flagged EXPIRY_IMPLAUSIBLE instead of quietly storing a card that would
        read valid for fourteen years."""
        w = dict(ANGEL)
        w["osha_data"] = dict(ANGEL["osha_data"], expiration="03/01/2040")
        p = _plan(w)
        self.assertIsNone(p["after"]["expiration_date"])
        self.assertEqual(p["after"]["review_reason"], "EXPIRY_IMPLAUSIBLE")
        self.assertTrue(p["after"]["needs_review"])
        self.assertIsNone(p["fault_after"])

    def test_amendment_C_is_honoured(self):
        """Two unverified SST rows on one worker are both flagged by the
        builder. Clearing one in isolation would quietly undo that."""
        w = dict(ANGEL)
        w["certifications"] = [
            dict(ANGEL["certifications"][0]),
            {"type": "SST_SUPERVISOR", "card_number": "RUQ24T3LVF",
             "expiration_date": None, "verified": False, "needs_review": True,
             "review_reason": "DUPLICATE_SST", "expiration_raw_rejected": None,
             "class_source": "text_only"},
        ]
        for p in repair.plan_for_worker(w, NOW):
            self.assertTrue(p["after"]["needs_review"], p)


class TheGuardAndTheShortcut(unittest.TestCase):

    SRC = (Path(__file__).resolve().parent.parent / "scripts"
           / "repair_cert_rows_from_stored_read.py").read_text(encoding="utf-8")

    def test_the_planner_never_assigns_the_flag_by_hand(self):
        """THE SHORTCUT THAT PARKED PR #530, closed by reading the AST rather
        than by trusting the docstring. Any literal assignment of
        `needs_review` / `review_reason` to a constant inside the planner is the
        cure that is not one -- with ONE exception, Amendment C's
        `needs_review = True`, which raises the flag and never lowers it.
        """
        tree = ast.parse(self.SRC)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "plan_for_worker")
        bad = []
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not (isinstance(target, ast.Name)
                        and target.id in ("needs_review", "review_reason")):
                    continue
                if isinstance(node.value, ast.Constant) and node.value.value is True:
                    continue      # Amendment C: raises the flag, never lowers it
                if isinstance(node.value, ast.Constant):
                    bad.append(f"line {node.lineno}: "
                               f"{target.id} = {node.value.value!r}")
        self.assertEqual(bad, [], "the flag is assigned by hand: " + "; ".join(bad))

    def test_it_goes_through_the_SHARED_gate(self):
        """Not a re-implementation of the rules. Both names have to appear in
        the CODE, not in the prose -- the docstring says it too, and a test
        that matched the docstring would be checking the claim."""
        from tests.source_text import code_of
        code = code_of("scripts/repair_cert_rows_from_stored_read.py")
        self.assertIn("evaluate_cert_expiry(", code)
        self.assertIn("derive_cert_review(", code)
        self.assertIn("cert_row_fault(", code)
        # AND IT NEVER RE-CLASSIFIES. The row's class was decided from an image
        # this script cannot see.
        #
        # ANCHORED ON THE CALL, not the bare word. `assertNotIn` against a
        # string bans a SUBSTRING, so a bare `"resolve_card_class"` would also
        # be satisfied -- or broken -- by any name that merely contains it, and
        # what is forbidden here is CALLING it. See
        # test_absence_literals_are_specific, which fails on the bare form.
        self.assertNotIn("resolve_card_class(", code)

    def test_it_is_dry_run_by_default_and_legacy_flags_are_refused(self):
        self.assertIn("refuse_legacy_flag(", self.SRC)
        self.assertIn("check_guard(args)", self.SRC)
        self.assertIn("= audited(", self.SRC)

    def test_the_prod_writer_census_accepts_it(self):
        """The derived census in test_every_prod_writer_is_guarded.py is the
        real gate; this asserts it SEES this file, so a green census is not
        green because the walk missed it."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import test_every_prod_writer_is_guarded as census
        writers = census._scripts_that_write()
        self.assertIn("repair_cert_rows_from_stored_read.py", writers,
                      "the census does not see this script's writes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
