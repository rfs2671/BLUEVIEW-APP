"""The code -> plain-label tables (lib/dob_plain_labels).

Pins:
  * every row, EN and ES, is a non-empty line of at most 12 words;
  * every code the test fixtures carry (complaint category 21) and every code
    on the real 588 Thomas S Boyland records (complaint categories 05, 12, 45,
    85, 8A; ECB infraction codes 1P3, 282, 2P7) is in the table;
  * OATH's "B" prefix is stripped (B282 -> 282);
  * an unknown code gets NO label: code_label is None and the card falls to
    the generic line -- nothing is guessed;
  * a BIS violation-type code (unverified, quarantined in
    dob_complaint_codes) never reaches a label through this table;
  * the "MISCELLANEOUS VIOLATIONS" codes are marked broad.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QWEN_API_KEY", "")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import dob_plain_labels as L  # noqa: E402
from lib import dob_plain_lines  # noqa: E402


def _complaint(cat, **kw):
    return {"record_type": "complaint", "complaint_type": cat, "dataset": "eabe-havv",
            "raw_dob_id": "3A00001", **kw}


def _ecb(code, desc="OBSERVED SIDEWALK SHED CONTRARY TO PLANS AT EXP 1", **kw):
    return {"record_type": "violation", "dataset": "6bgk-3dad", "ecb_status": "ACTIVE",
            "infraction_code": code, "description": desc, "raw_dob_id": "39500000X", **kw}


class TableRows(unittest.TestCase):
    def test_every_row_is_a_short_line_in_both_languages(self):
        for name, table in (("complaint", L.COMPLAINT_CATEGORY_LABELS),
                            ("ecb", L.ECB_INFRACTION_LABELS)):
            self.assertGreater(len(table), 40, name)
            for code, row in table.items():
                for lang in ("en", "es"):
                    text = row[lang]
                    self.assertTrue(text.strip(), f"{name} {code} {lang} is blank")
                    self.assertLessEqual(L.word_count(text), L.MAX_WORDS,
                                         f"{name} {code} {lang}: {text!r}")
                    self.assertNotIn("\n", text)

    def test_complaint_codes_come_from_the_sourced_category_map(self):
        # Every complaint row restates a code dob_complaint_codes transcribed
        # from DOB's complaint_category.pdf -- none is a code from nowhere.
        from dob_complaint_codes import DOB_CATEGORY_CODES
        stray = sorted(set(L.COMPLAINT_CATEGORY_LABELS) - set(DOB_CATEGORY_CODES))
        self.assertEqual(stray, [])

    def test_fixture_and_real_record_codes_are_covered(self):
        for cat in ("21", "05", "12", "45", "85", "8A"):
            self.assertIsNotNone(L.code_label(_complaint(cat)), cat)
        for code in ("1P3", "282", "2P7"):
            self.assertIsNotNone(L.code_label(_ecb(code)), code)
        self.assertEqual(L.code_label(_complaint("05"))["en"], "Work without a permit")
        self.assertEqual(L.code_label(_ecb("282"))["es"],
                         "El trabajo no coincide con los planos aprobados")

    def test_oath_prefix_is_stripped(self):
        self.assertEqual(L.ecb_code("B282"), "282")
        self.assertEqual(L.ecb_code(" b1p3 "), "1P3")
        self.assertEqual(L.code_label(_ecb("B282")), L.code_label(_ecb("282")))

    def test_miscellaneous_codes_are_broad(self):
        for code in ("2P7", "1P7", "106", "206"):
            self.assertTrue(L.code_label(_ecb(code)).get("broad"), code)
        self.assertFalse(L.code_label(_ecb("282")).get("broad"))
        self.assertTrue(L.code_label(_complaint("99")).get("broad"))


class UnknownCodesInventNothing(unittest.TestCase):
    def test_unknown_complaint_category(self):
        row = _complaint("ZZ")
        self.assertIsNone(L.code_label(row))
        line, src = dob_plain_lines.line_for_read(row)
        self.assertEqual(src, "fallback")
        self.assertEqual(line, {"en": "DOB complaint — see DOB text",
                                "es": "Queja del DOB — vea el texto del DOB"})

    def test_unknown_ecb_code(self):
        row = _ecb("9Z9")
        self.assertIsNone(L.code_label(row))
        line, src = dob_plain_lines.line_for_read(row)
        self.assertEqual(src, "fallback")
        self.assertEqual(line["en"], "ECB violation — see DOB text")

    def test_bis_violation_type_code_gets_no_label(self):
        # "LL6291" sits in UNVERIFIED_VIOLATION_TYPE_LABELS_PENDING_SOURCE as
        # "Local Law 62/91 — Boilers"; that label must not surface here.
        row = {"record_type": "violation", "dataset": "3h2n-5cm9", "violation_type": "LL6291",
               "description": "FAILURE TO FILE BOILER INSPECTION", "raw_dob_id": "123"}
        self.assertIsNone(L.code_label(row))
        line, _ = dob_plain_lines.line_for_read(row)
        self.assertNotIn("Local Law", line["en"])

    def test_no_code_at_all(self):
        self.assertIsNone(L.code_label(_complaint("")))
        self.assertIsNone(L.code_label(_ecb("")))


class DobText(unittest.TestCase):
    def test_complaint_text_is_the_official_wording(self):
        text = L.dob_text(_complaint("05", disposition_code="I2"))
        self.assertIn("Permit — None", text)
        self.assertIn("No Violation Warranted", text)

    def test_ecb_text_is_the_description_and_section(self):
        row = _ecb("282", section_law_description="28-105.12.2    WRK DOESN'T CONFORM")
        self.assertEqual(L.dob_text(row),
                         "OBSERVED SIDEWALK SHED CONTRARY TO PLANS AT EXP 1 — 28-105.12.2 WRK DOESN'T CONFORM")

    def test_a_dob_complaint_has_no_free_text(self):
        self.assertEqual(L.free_text(_complaint("05")), "")
        self.assertTrue(L.free_text(_ecb("2P7")))


if __name__ == "__main__":
    unittest.main()
