"""Two wrong facts that reached customers, fixed at the source.

1. COMPLAINT SUMMARY LABEL. _generate_summary overrode classify_complaint's
   sourced category label with a hand-written CATEGORY_DESCRIPTIONS dict that
   was wrong for all 17 codes it listed. 588 Thomas S Boyland's complaint
   3A41175 is DOB category 05, "Permit - None"; its summary read "work
   contrary to approved plans". The alert emails and the activity feed quote
   ai_summary.

2. ECB PENALTY. _extract_violation_fields read `amount_paid` as the penalty.
   The ECB dataset (6bgk-3dad) spells the imposed penalty `penality_imposed`;
   summons 39558662P -- $1,250 imposed, $0 paid, hearing pending -- was stored
   with penalty_amount "0". Alert templates, the WhatsApp brief and the group
   posts read penalty_amount.

Both are rewritten on the next sync by the in-place refresh (neither field is
in _IN_PLACE_KEEP), quietly: a summary or penalty correction is not a status
change, so it raises no alert.

The two records below are REAL, read from NYC Open Data on 2026-10-25
(eabe-havv complaint 3A41175, 6bgk-3dad summons 39558662P), unabridged except
fields the extractors do not read.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402

COMPLAINT_3A41175 = {
    "complaint_number": "3A41175", "status": "CLOSED", "date_entered": "12/11/2025",
    "house_number": "588", "house_street": "THOMAS S BOYLAND STREET", "zip_code": "11212",
    "bin": "3255362", "community_board": "316", "complaint_category": "05", "unit": "OBM",
    "disposition_date": "02/04/2026", "disposition_code": "C2", "inspection_date": "02/04/2026",
}
ECB_39558662P = {
    "ecb_violation_number": "39558662P", "ecb_violation_status": "ACTIVE", "bin": "3430621",
    "hearing_date": "20261118", "hearing_time": "930", "issue_date": "20260902",
    "severity": "CLASS - 2", "violation_type": "Construction",
    "violation_description": "OBSERVED SIDEWALK SHED INSTALLED AT EXP# 1 UNDER APPLICATION "
                             "#B01409772-WITH LETTER OF INSTALLATION PROVIDED TO GC-CONTRARY TO PLANS",
    "penality_imposed": "1250", "amount_paid": "0", "balance_due": "1250",
    "infraction_code1": "282", "hearing_status": "PENDING",
}
#: The 17 codes the removed dict listed, and what it said for each.
OLD_DICT = {
    "01": "illegal work or work without a permit", "03": "failure to maintain building facade",
    "05": "work contrary to approved plans", "06": "unsafe construction condition",
    "09": "illegal conversion or occupancy", "12": "failure to maintain elevator",
    "14": "demolition without permit", "23": "working without a safety net",
    "28": "illegal curb cut or sidewalk damage", "30": "debris falling from building",
    "45": "unsafe scaffolding or sidewalk shed", "49": "construction noise outside allowed hours",
    "59": "work without required DOB inspection", "63": "illegal fence or retaining wall",
    "71": "crane or derrick safety violation", "83": "failure to safeguard persons or property",
    "91": "building under construction in unsafe condition",
}


class TheComplaintSummary(unittest.TestCase):

    def test_3a41175_says_permit_none_not_contrary_to_plans(self):
        s = server._generate_summary(COMPLAINT_3A41175, "complaint")
        self.assertIn("Permit", s)
        self.assertIn("None", s)
        self.assertNotIn("contrary to approved plans", s.lower())
        self.assertTrue(s.startswith("#3A41175: Complaint: "), s)

    def test_every_code_the_old_dict_listed_now_reads_dobs_own_label(self):
        for code, old in OLD_DICT.items():
            with self.subTest(code):
                rec = {"complaint_number": "X1", "complaint_category": code, "disposition_code": ""}
                label = server.classify_complaint(rec)["category_label"]
                s = server._generate_summary(rec, "complaint")
                self.assertIn(label, s)
                self.assertNotIn(old, s.lower())


class TheEcbPenalty(unittest.TestCase):

    def test_39558662p_is_1250_not_the_0_paid(self):
        self.assertEqual(server._extract_violation_fields(ECB_39558662P)["penalty_amount"], "1250")

    def test_amount_paid_is_never_the_penalty(self):
        self.assertIsNone(server._extract_violation_fields(
            {"ecb_violation_number": "1", "amount_paid": "500"})["penalty_amount"])

    def test_a_zero_imposed_penalty_is_kept_as_zero(self):
        # $0 imposed with a hearing pending is a real value ("set at hearing").
        self.assertEqual(server._extract_violation_fields(
            {**ECB_39558662P, "penality_imposed": "0", "balance_due": "0"})["penalty_amount"], "0")

    def test_other_datasets_names_still_read(self):
        x = server._extract_violation_fields
        self.assertEqual(x({"penalty_imposed": "300"})["penalty_amount"], "300")
        self.assertEqual(x({"penalty_applied": "1000"})["penalty_amount"], "1000")
        self.assertEqual(x({"penalty_balance_due": "75"})["penalty_amount"], "75")


class TheNextSyncCorrectsStoredRows(unittest.TestCase):
    """A row stored before the fix is rewritten by the in-place refresh, and
    the correction is NOT a status change (no alert, no feed resurfacing)."""

    def test_refresh_rewrites_summary_and_penalty_quietly(self):
        now = datetime(2026, 10, 25, 16, 0, tzinfo=timezone.utc)
        fresh = {"current_status": "ACTIVE", "penalty_amount": "1250",
                 "ai_summary": server._generate_summary(COMPLAINT_3A41175, "complaint")}
        stored = {"current_status": "ACTIVE", "penalty_amount": "0",
                  "ai_summary": "#3A41175: Complaint about work contrary to approved plans. No access.",
                  "status_history": [{"status": "ACTIVE"}]}
        update, changed, _legacy = server._plan_in_place_refresh(stored, fresh, now)
        self.assertFalse(changed)
        self.assertEqual(update["penalty_amount"], "1250")
        self.assertNotIn("contrary to approved plans", update["ai_summary"].lower())
        self.assertNotIn("is_seed_transition", update)
        self.assertNotIn("status_changed_at", update)


if __name__ == "__main__":
    unittest.main()
