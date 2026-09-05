"""THE REGISTER STOPS PRESENTING AN UNREAD CARD AS A CREDENTIAL ON FILE.

A worker whose card class could not be read — no number, an expiry suppressed as
unparseable or implausible — appears on the filed OSHA/SST register as
"SST Unspecified / — / —". That row states a class the system never established
and reads as a credential.

THE GATE IS NOT TOUCHED, BY RULING. `has_osha` still counts `SST_UNSPECIFIED`
and `OSHA_UNSPECIFIED`, so such a man is still admitted with a warning. Removing
them would have blocked him on four paths, and the worst was `submit_checkin`
returning 403 on his NEXT check-in from the STORED document — a permanent
lockout produced by a card the app could not read, with no new scan and nothing
he could do. `CARD_NOT_SST` does not fire for an unreadable SST card either, so
`checkin.html` would have told a man holding a card that he has none on file.

TWO CHANGES, BOTH ON THE DOCUMENT SIDE:

1. THE REVIEW COLUMN COULD NOT REACH THE ROWS IT EXISTS FOR.
   `osha_review_index` writes `review_by_key[(wid, cn)]` for every flagged cert
   INCLUDING those with no card number, where `cn` is "". `osha_review_cell`
   read `... if cn else None` and so declined to look up exactly those keys.
   The register's worst rows fell through to grey "Not checked" instead of amber
   "Class unverified" — the column hid its own findings.

2. AN `unverified` MARKER, FROZEN AT THE GATE. Keyed on the check-in's
   `sst_status`, written when the card was read and never recomputed, so the
   register records what was known THEN rather than what a later lookup says.

THE OTHER FILED DOCUMENT ALREADY AGREED. `lib/logbook/ll196.py` sets
`_SST_CERT_TYPES = SST_CLASS_TYPES`, which excludes `SST_UNSPECIFIED`, so the
LL196 DOB attestation has always reported such a man as missing. The OSHA
register was the surface that disagreed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from tests.source_text import code_of  # noqa: E402

_CODE = code_of("server.py")


class TheReviewColumnReachesTheRowsWithNoCardNumber(unittest.TestCase):
    """The bug: indexed under `(wid, "")`, never looked up."""

    WID = "w1"

    def test_a_flagged_cert_with_no_card_number_is_now_reported(self):
        cell = server.osha_review_cell(
            {"worker_id": self.WID, "card_number": ""},
            {(self.WID, ""): "CLASS_UNVERIFIED"}, set(), {self.WID},
        )
        self.assertIn("Class unverified", cell)
        self.assertNotIn("Not checked", cell)

    def test_it_used_to_fall_through_to_not_checked(self):
        """The control, stated as the shape rather than the old code: with no
        entry in the index, the same row must still read 'Not checked'."""
        cell = server.osha_review_cell(
            {"worker_id": self.WID, "card_number": ""}, {}, set(), {self.WID},
        )
        self.assertIn("Not checked", cell)

    def test_a_flagged_cert_WITH_a_number_is_unaffected(self):
        cell = server.osha_review_cell(
            {"worker_id": self.WID, "card_number": "123"},
            {(self.WID, "123"): "EXPIRY_UNPARSEABLE"}, set(), {self.WID},
        )
        self.assertIn("Expiry unreadable", cell)

    def test_THE_PER_WORKER_FALLBACK_IS_STILL_REJECTED(self):
        """THE GUARANTEE THIS CHANGE MUST NOT BREAK, and the reason the old
        guard existed at all: a man holding a clean OSHA 30 and a flagged SST
        must not have his correct row marked uncertain. `(wid, "")` is an EXACT
        key for a cert with no number — it cannot reach a flag stored under a
        different number."""
        cell = server.osha_review_cell(
            {"worker_id": self.WID, "card_number": "clean-30"},
            {(self.WID, ""): "CLASS_UNVERIFIED"},          # a DIFFERENT cert
            {(self.WID, "clean-30")}, {self.WID},
        )
        self.assertIn("No findings", cell)
        self.assertNotIn("Class unverified", cell)

    def test_and_the_reverse_direction_too(self):
        """A no-number row must not pick up a flag filed under a number."""
        cell = server.osha_review_cell(
            {"worker_id": self.WID, "card_number": ""},
            {(self.WID, "999"): "CLASS_UNVERIFIED"}, set(), {self.WID},
        )
        self.assertIn("Not checked", cell)

    def test_a_row_with_no_worker_id_is_still_not_checked(self):
        """There is nothing to key on at all."""
        cell = server.osha_review_cell(
            {"worker_id": "", "card_number": ""},
            {("", ""): "CLASS_UNVERIFIED"}, set(), set(),
        )
        self.assertIn("Not checked", cell)


class TheFiledRowCarriesTheVerdict(unittest.TestCase):
    """The marker is read from the STORED entry, never resolved at print time."""

    def test_an_unverified_row_is_marked_on_the_report(self):
        out = server._osha_type_cell(
            {"certification_type": "SST Unspecified", "unverified": True})
        self.assertIn("UNVERIFIED", out)

    def test_a_normal_row_gains_nothing(self):
        out = server._osha_type_cell(
            {"certification_type": "SST Worker", "unverified": False})
        self.assertNotIn("UNVERIFIED", out)
        self.assertEqual(out, "SST Worker")

    def test_a_row_filed_before_the_field_existed_gains_nothing(self):
        """A filed document shows what was filed."""
        out = server._osha_type_cell({"certification_type": "SST Worker"})
        self.assertNotIn("UNVERIFIED", out)

    def test_only_a_real_true_marks_it(self):
        """`is True`, not truthiness — a legacy string must not be read as a
        verdict about a named man."""
        for v in ("no", 0, "", None, "false"):
            self.assertNotIn(
                "UNVERIFIED",
                server._osha_type_cell({"certification_type": "X", "unverified": v}),
                repr(v))

    def test_an_unverified_row_with_no_label_still_says_something(self):
        out = server._osha_type_cell({"certification_type": "", "unverified": True})
        self.assertIn("UNVERIFIED", out)


class TheGateIsUntouched(unittest.TestCase):
    """Asserted, because the whole ruling turns on it."""

    def test_both_unspecified_types_still_satisfy_the_baseline(self):
        i = _CODE.index("has_osha = bool(")
        block = _CODE[i:i + 400]
        self.assertIn("OSHA_UNSPECIFIED", block)
        self.assertIn("RECOGNIZED_SST_TYPES", block)

    def test_missing_osha_is_still_the_only_hard_block(self):
        i = _CODE.index("def validate_worker_certifications(")
        j = _CODE.index("\ndef ", i + 10)
        body = _CODE[i:j]
        self.assertEqual(body.count("blocks.append("), 1)

    def test_an_unspecified_cert_still_clears(self):
        res = server.validate_worker_certifications(
            {"certifications": [{"type": "SST_UNSPECIFIED"}]})
        self.assertTrue(res["cleared"], "the gate must still admit him")

    def test_and_he_is_reported_as_unknown_rather_than_valid(self):
        res = server.validate_worker_certifications(
            {"certifications": [{"type": "SST_UNSPECIFIED"}]})
        self.assertEqual(res["sst_state"], "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
