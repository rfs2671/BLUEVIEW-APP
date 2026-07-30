"""Certification capture integrity — the four defects and the three amendments.

Defects fixed (all were 100% on the live workers):
  (a) a fabricated OSHA row created from the SST card, stamped with the SST
      number; (b) OSHA level keyed off an absent 'course' field → always OSHA_10;
  (c) SST class hardcoded SST_LIMITED (a SUPERVISOR card stored as LIMITED);
  (d) needs_review keyed on number presence, and `if not has_existing_sst` so a
      wrong expiry could never be re-scanned away.

Amendments: A three-state SST gate (valid|unknown|expired, unknown never reads
as valid and is as loud as expired); B one image → at most one cert row; C two
unverified SST rows on one worker both flag.

Tests target the pure builder/validator (no DB), which the endpoint now just
persists — plus the cleanup script's pure planner.
"""

import importlib.util
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402
from server import (  # noqa: E402
    build_worker_certifications,
    validate_worker_certifications,
    SST_EXPIRY_MAX_YEARS,
    SST_UNSPECIFIED,
)

# Import the cleanup script's pure planner by file path.
_spec = importlib.util.spec_from_file_location(
    "audit_fabricated_certs", str(_BACKEND / "scripts" / "audit_fabricated_certs.py")
)
_audit = importlib.util.module_from_spec(_spec)
sys.modules["audit_fabricated_certs"] = _audit
_spec.loader.exec_module(_audit)
plan_for_worker = _audit.plan_for_worker

NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)


def od(**kw):
    """OCR result dict; sensible SST defaults, override per test."""
    base = {
        "name": "Roey Fishman",
        "sst_number": "AH34A98LHB",
        "card_type": "SST",
        "card_class": "LIMITED",
        "issued": "03/11/2019",
        "expiration": "03/11/2029",
    }
    base.update(kw)
    return base


def build(existing, ocr, number="AH34A98LHB", image="b64img"):
    return build_worker_certifications(existing, ocr, number, image, NOW)


def sst_rows(certs):
    return [c for c in certs if str(c.get("type", "")).startswith("SST")]


def osha_rows(certs):
    return [c for c in certs if str(c.get("type", "")).startswith("OSHA")]


def state_of(certs):
    return validate_worker_certifications({"certifications": certs})


class OneImageOneRow(unittest.TestCase):
    def test_sst_only_scan_makes_one_row_no_osha(self):
        certs, _ = build([], od())
        self.assertEqual(len(certs), 1)
        self.assertEqual(len(osha_rows(certs)), 0, "no fabricated OSHA row from an SST scan")
        self.assertEqual(certs[0]["type"], "SST_LIMITED")
        self.assertEqual(certs[0]["card_number"], "AH34A98LHB")

    def test_card_type_misread_as_osha_still_one_row(self):
        # OCR mislabels the card OSHA with no expiry → one OSHA row, no SST.
        certs, _ = build([], od(card_type="OSHA", card_class="10", expiration=None))
        self.assertEqual(len(certs), 1, "one image -> at most one row")
        self.assertEqual(len(osha_rows(certs)), 1)
        self.assertEqual(len(sst_rows(certs)), 0)

    def test_osha_with_expiry_resolves_sst_one_row(self):
        # An expiry means SST even if card_type says OSHA — still exactly one row.
        certs, _ = build([], od(card_type="OSHA", expiration="03/11/2029"))
        self.assertEqual(len(certs), 1)
        self.assertEqual(len(sst_rows(certs)), 1)


class ClassCapture(unittest.TestCase):
    def test_supervisor_stored_as_supervisor_not_limited(self):
        certs, _ = build([], od(card_class="SUPERVISOR"))
        self.assertEqual(certs[0]["type"], "SST_SUPERVISOR")

    def test_illegible_class_is_unspecified_and_unknown_not_valid(self):
        certs, _ = build([], od(card_class=None))
        self.assertEqual(certs[0]["type"], SST_UNSPECIFIED)
        self.assertTrue(certs[0]["needs_review"])
        res = state_of(certs)
        self.assertEqual(res["sst_state"], "unknown", "illegible class must NOT read as valid")
        self.assertTrue(res["cleared"], "flag-but-allow: check-in still succeeds")
        types = {w["type"] for w in res["warnings"]}
        self.assertIn("SST_UNKNOWN", types, "unknown must raise a warning (drives the notification)")


class SanityGate(unittest.TestCase):
    def test_implausible_expiry_suppressed_not_stored(self):
        # Expiry 40 years out — impossible OCR misread.
        certs, _ = build([], od(expiration="03/11/2066"))
        row = sst_rows(certs)[0]
        self.assertIsNone(row["expiration_date"], "bad date must NOT be stored")
        self.assertEqual(row["review_reason"], "EXPIRY_IMPLAUSIBLE")
        self.assertEqual(row["expiration_raw_rejected"], "03/11/2066")
        res = state_of(certs)
        self.assertEqual(res["sst_state"], "unknown")
        self.assertTrue(res["cleared"])
        self.assertIn("SST_UNKNOWN", {w["type"] for w in res["warnings"]})

    def test_expiry_before_issue_rejected(self):
        certs, _ = build([], od(issued="03/11/2019", expiration="03/11/2018"))
        self.assertIsNone(sst_rows(certs)[0]["expiration_date"])
        self.assertEqual(sst_rows(certs)[0]["review_reason"], "EXPIRY_IMPLAUSIBLE")

    def test_expiry_beyond_ceiling_rejected(self):
        # now + (MAX+1) years is past the ceiling.
        exp = f"03/11/{NOW.year + SST_EXPIRY_MAX_YEARS + 1}"
        certs, _ = build([], od(expiration=exp))
        self.assertIsNone(sst_rows(certs)[0]["expiration_date"])

    def test_within_ceiling_kept(self):
        exp = f"03/11/{NOW.year + SST_EXPIRY_MAX_YEARS - 1}"
        certs, _ = build([], od(expiration=exp, card_class="SUPERVISOR"))
        self.assertIsNotNone(sst_rows(certs)[0]["expiration_date"])
        self.assertEqual(state_of(certs)["sst_state"], "valid")


class NeedsReviewCompleteness(unittest.TestCase):
    def test_needs_review_not_keyed_on_number(self):
        # Number reads cleanly but class is illegible → still needs review.
        certs, _ = build([], od(card_class=None), number="CLEAN123")
        self.assertTrue(certs[0]["needs_review"],
                        "needs_review must key on completeness, not number presence")

    def test_missing_name_flags(self):
        certs, _ = build([], od(name=None))
        self.assertTrue(sst_rows(certs)[0]["needs_review"])

    def test_missing_number_flags(self):
        certs, _ = build([], od(sst_number=None), number=None)
        self.assertTrue(sst_rows(certs)[0]["needs_review"])

    def test_complete_scan_not_flagged(self):
        certs, _ = build([], od(card_class="SUPERVISOR", expiration="03/11/2029"))
        self.assertFalse(certs[0]["needs_review"])
        self.assertEqual(certs[0]["review_reason"], None)


class ThreeState(unittest.TestCase):
    def test_valid(self):
        certs, _ = build([], od(card_class="FULL", expiration="03/11/2029"))
        self.assertEqual(state_of(certs)["sst_state"], "valid")

    def test_expired_raises_warning(self):
        certs, _ = build([], od(card_class="FULL", issued="01/01/2016", expiration="03/11/2021"))
        res = state_of(certs)
        self.assertEqual(res["sst_state"], "expired")
        self.assertIn("EXPIRED_SST", {w["type"] for w in res["warnings"]})
        self.assertTrue(res["cleared"])

    def test_unspecified_never_valid_even_with_future_expiry(self):
        # class unknown but expiry fine → still unknown, never valid.
        certs, _ = build([], od(card_class=None, expiration="03/11/2029"))
        self.assertEqual(state_of(certs)["sst_state"], "unknown")


class ReScanCorrection(unittest.TestCase):
    def _flagged_existing(self):
        # A stored SST with a flagged (implausible-suppressed) expiry, like Fishman.
        return [{
            "type": "SST_LIMITED", "card_number": "AH34A98LHB", "issue_date": None,
            "expiration_date": None, "verified": False, "needs_review": True,
            "review_reason": "EXPIRY_IMPLAUSIBLE", "expiration_raw_rejected": "03/11/2022",
        }]

    def test_clean_rescan_corrects_flagged(self):
        certs, _ = build(self._flagged_existing(), od(card_class="LIMITED", expiration="03/11/2029"))
        row = sst_rows(certs)[0]
        self.assertEqual(len(sst_rows(certs)), 1, "corrects in place, no duplicate")
        self.assertIsNotNone(row["expiration_date"])
        self.assertFalse(row["needs_review"])
        self.assertIsNone(row["expiration_raw_rejected"])

    def test_differing_rescan_vs_clean_sets_conflict_no_overwrite(self):
        good = [{
            "type": "SST_LIMITED", "card_number": "AH34A98LHB",
            "expiration_date": datetime(2029, 3, 11, tzinfo=timezone.utc),
            "verified": False, "needs_review": False, "review_reason": None,
        }]
        certs, _ = build(good, od(card_class="LIMITED", expiration="03/11/2027"))
        row = sst_rows(certs)[0]
        self.assertEqual(row["expiration_date"], datetime(2029, 3, 11, tzinfo=timezone.utc),
                         "clean stored value must NOT be overwritten by a differing scan")
        self.assertTrue(row["needs_review"])
        self.assertEqual(row["review_reason"], "EXPIRY_CONFLICT")

    def test_sanity_failing_rescan_never_overwrites(self):
        good = [{
            "type": "SST_LIMITED", "card_number": "AH34A98LHB",
            "expiration_date": datetime(2029, 3, 11, tzinfo=timezone.utc),
            "verified": False, "needs_review": False, "review_reason": None,
        }]
        certs, _ = build(good, od(card_class="LIMITED", expiration="03/11/2099"))  # implausible
        self.assertEqual(sst_rows(certs)[0]["expiration_date"],
                         datetime(2029, 3, 11, tzinfo=timezone.utc))

    def test_verified_cert_never_modified(self):
        verified = [{
            "type": "SST_SUPERVISOR", "card_number": "AH34A98LHB",
            "expiration_date": datetime(2028, 2, 26, tzinfo=timezone.utc),
            "verified": True, "verified_by": "admin1", "needs_review": False,
        }]
        before = [dict(verified[0])]
        certs, _ = build(verified, od(card_class="LIMITED", expiration="03/11/2029"))
        match = [c for c in certs if c.get("verified")]
        self.assertEqual(match[0], before[0], "a verified cert must be byte-identical after any re-scan")


class DuplicateSst(unittest.TestCase):
    def test_misread_number_vs_single_existing_is_conflict_not_duplicate(self):
        # Stronger than a silent duplicate: with ONE existing SST, a misread
        # number falls back to that row and a differing expiry is a CONFLICT,
        # so no second row is created.
        existing = [{
            "type": "SST_LIMITED", "card_number": "OLD-NUM",
            "expiration_date": datetime(2029, 3, 11, tzinfo=timezone.utc),
            "verified": False, "needs_review": False, "review_reason": None,
        }]
        certs, _ = build(existing, od(card_class="LIMITED", expiration="03/11/2030"), number="NEW-NUM")
        rows = sst_rows(certs)
        self.assertEqual(len(rows), 1, "no silent duplicate — folds onto the one SST row")
        self.assertTrue(rows[0]["needs_review"])
        self.assertEqual(rows[0]["review_reason"], "EXPIRY_CONFLICT")

    def test_two_preexisting_unverified_sst_both_flagged(self):
        # Amendment C safety net: two unverified SST rows already coexist (e.g.
        # legacy data). ANY build run flags BOTH so they never sit quietly.
        existing = [
            {"type": "SST_LIMITED", "card_number": "A1",
             "expiration_date": datetime(2029, 3, 11, tzinfo=timezone.utc),
             "verified": False, "needs_review": False, "review_reason": None},
            {"type": "SST_SUPERVISOR", "card_number": "B2",
             "expiration_date": datetime(2030, 1, 1, tzinfo=timezone.utc),
             "verified": False, "needs_review": False, "review_reason": None},
        ]
        # An OSHA scan does not touch the SST rows; the dedup pass flags both.
        certs, _ = build(existing, od(card_type="OSHA", card_class="10", expiration=None), number="OSHANUM")
        rows = sst_rows(certs)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["needs_review"] for r in rows))
        self.assertTrue(all(r["review_reason"] == "DUPLICATE_SST" for r in rows))

    def test_verified_plus_unverified_only_one_unverified_not_flagged_as_dup(self):
        # A verified cert + one unverified is NOT "two unverified" — no DUP flag.
        existing = [
            {"type": "SST_SUPERVISOR", "card_number": "A1",
             "expiration_date": datetime(2028, 2, 26, tzinfo=timezone.utc),
             "verified": True, "needs_review": False, "review_reason": None},
        ]
        certs, _ = build(existing, od(card_class="LIMITED", expiration="03/11/2030"), number="B2")
        unverified = [c for c in sst_rows(certs) if not c.get("verified")]
        self.assertEqual(len(unverified), 1)
        self.assertNotEqual(unverified[0].get("review_reason"), "DUPLICATE_SST")


class FlagButAllow(unittest.TestCase):
    def test_every_failure_case_still_clears(self):
        cases = [
            od(card_class=None),                         # unknown class
            od(expiration="03/11/2066"),                 # implausible expiry
            od(expiration="not-a-date"),                 # unparseable
            od(issued="03/11/2019", expiration="03/11/2018"),  # before issue
            od(name=None, sst_number=None),              # incomplete
        ]
        for c in cases:
            certs, _ = build([], c)
            res = state_of(certs)
            self.assertTrue(res["cleared"], f"check-in must succeed for {c}")


class CleanupPlanner(unittest.TestCase):
    def _fishman(self):
        return {
            "_id": "w1", "name": "Roey Fishman Shelly",
            "created_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
            "certifications": [
                {"type": "OSHA_10", "card_number": "AH34A98LHB", "expiration_date": None},
                {"type": "SST_LIMITED", "card_number": "AH34A98LHB",
                 "expiration_date": datetime(2022, 3, 11, tzinfo=timezone.utc)},
            ],
        }

    def test_drops_fabricated_osha_and_clears_implausible(self):
        new, actions = plan_for_worker(self._fishman())
        self.assertEqual(len(osha_rows(new)), 0, "fabricated OSHA row dropped")
        self.assertEqual(len(sst_rows(new)), 1, "SST row kept — never drops the array")
        sst = sst_rows(new)[0]
        self.assertIsNone(sst["expiration_date"], "2022 (before 2026 capture) cleared")
        self.assertEqual(sst["review_reason"], "EXPIRY_IMPLAUSIBLE")
        self.assertTrue(sst["needs_review"])
        kinds = {a[0] for a in actions}
        self.assertIn("drop_fabricated_osha", kinds)
        self.assertIn("clear_implausible_expiry", kinds)

    def test_class_unverified_flag_when_expiry_ok(self):
        w = {
            "_id": "w2", "name": "Pena",
            "created_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
            "certifications": [
                {"type": "OSHA_10", "card_number": "PENA1", "expiration_date": None},
                {"type": "SST_LIMITED", "card_number": "PENA1",
                 "expiration_date": datetime(2028, 2, 26, tzinfo=timezone.utc)},
            ],
        }
        new, actions = plan_for_worker(w)
        self.assertEqual(len(osha_rows(new)), 0)
        sst = sst_rows(new)[0]
        self.assertEqual(sst["review_reason"], "CLASS_UNVERIFIED")
        self.assertIsNotNone(sst["expiration_date"], "future expiry kept, only class flagged")


if __name__ == "__main__":
    unittest.main()
