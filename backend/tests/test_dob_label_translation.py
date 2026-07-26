"""Code→label translation: violation types + complaint category/disposition
fallbacks. Locks the rule: official-sourced labels only; anything unmapped
renders "DOB code: {code}" — never a bare code, never a blank, never guessed.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dob_complaint_codes import (  # noqa: E402
    violation_type_display, get_category_label, get_disposition_label,
    UNVERIFIED_VIOLATION_TYPE_LABELS_PENDING_SOURCE,
)


class ViolationTypeDisplayTest(unittest.TestCase):
    """Violation-type codes have no verified official label → always prefixed."""

    def test_legacy_code_is_prefixed_not_embedded_description(self):
        # 3h2n-5cm9 stores "{CODE}-{DESCRIPTION}   {DEVICE}{REQ}"; the embedded
        # description is unverified and must NOT be shown — only the code.
        self.assertEqual(
            violation_type_display(
                "JVIOS-PRIVATE RESIDENTIAL ELEVATOR                 ELEVATOROPTIONAL"),
            "DOB code: JVIOS",
        )
        self.assertEqual(
            violation_type_display(
                "E-ELEVATOR                                        ELEVATORREQUIRED"),
            "DOB code: E",
        )

    def test_dob_now_bare_code_is_prefixed(self):
        self.assertEqual(violation_type_display("LBLVIO"), "DOB code: LBLVIO")
        self.assertEqual(violation_type_display("E"), "DOB code: E")
        self.assertEqual(violation_type_display("FTC-AEU-HAZ"), "DOB code: FTC-AEU-HAZ")

    def test_ecb_plain_english_passthrough(self):
        # 6bgk-3dad values are DOB's own plain-English field values, not codes.
        self.assertEqual(violation_type_display("Construction"), "Construction")
        self.assertEqual(violation_type_display("Quality of Life"), "Quality of Life")

    def test_blank_in_blank_out(self):
        self.assertEqual(violation_type_display(""), "")
        self.assertEqual(violation_type_display(None), "")

    def test_display_never_synthesizes_a_label_from_the_map(self):
        """VERIFY (c): the display never READS the quarantined map — its output
        is always "DOB code: {code}", "", or the input unchanged (ECB
        pass-through). So for any CODE input the result is prefixed, never a
        label from UNVERIFIED_VIOLATION_TYPE_LABELS_PENDING_SOURCE.

        (ECB values like "Construction" pass through unchanged and may happen to
        equal a quarantined value — that is the input echoed back, not a map
        lookup, so the invariant is 'prefix-or-verbatim', not 'never equals'.)"""
        codes = ["JVIOS-PRIVATE RESIDENTIAL ELEVATOR    ELEVATOROPTIONAL",
                 "E-ELEVATOR    ELEVATORREQUIRED", "LBLVIO", "E", "JVIOS",
                 "LL6291", "FISP", "FTC-AEU-HAZ"]
        unverified = set(UNVERIFIED_VIOLATION_TYPE_LABELS_PENDING_SOURCE.values())
        for raw in codes:
            out = violation_type_display(raw)
            self.assertTrue(out.startswith("DOB code:"), f"{raw!r} → {out!r}")
            self.assertNotIn(out, unverified)
        # ECB / blank: output is the input echoed back (or empty), never synthesized.
        for raw in ("Construction", "Quality of Life", ""):
            out = violation_type_display(raw)
            self.assertTrue(out == raw or out == "", f"{raw!r} → {out!r}")

    def test_never_bare_code_or_blank_for_nonblank(self):
        for raw in ("FTC-AEU-HAZ", "LBLVIO", "E", "ZZ9",
                    "JVIOS-PRIVATE RESIDENTIAL ELEVATOR    ELEVATOROPTIONAL"):
            out = violation_type_display(raw)
            self.assertTrue(out.startswith("DOB code:"), f"not prefixed: {raw!r} → {out!r}")


class ComplaintFallbackTest(unittest.TestCase):
    def test_category_mapped_and_prefixed(self):
        self.assertNotIn("DOB code:", get_category_label("45"))  # Illegal Conversion
        self.assertEqual(get_category_label("ZZ"), "DOB code: ZZ")

    def test_disposition_mapped_and_prefixed(self):
        self.assertNotIn("DOB code:", get_disposition_label("A3"))
        self.assertEqual(get_disposition_label("Q9"), "DOB code: Q9")

    def test_blank_codes_return_blank_not_prefix(self):
        self.assertEqual(get_category_label(""), "")
        self.assertEqual(get_disposition_label(""), "")


if __name__ == "__main__":
    unittest.main()
