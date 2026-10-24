"""The deterministic checker on the model's plain line (lib/dob_plain_lines).

It refuses a line that names a number, date, money amount, address or party
(person / company) that the DOB text does not contain, and lets a clean line --
or one whose number IS in the text -- through. The source below is the real DOB
text of ECB summons 39558663R (BIN 3430621).
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QWEN_API_KEY", "")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.dob_plain_lines import check_line, check_pair, parse_reply  # noqa: E402

SOURCE = ("BC 3307.2- I OBSERVED JERSEY BARRIERS INSTALLED/OCCUPYING AT STREET AT EXP#1 "
          "-NO DOT PERMIT FOR LANE CLOSURE ON STREET -DOT PERMIT FOR FENCE EXTENSION EXP. "
          "8/26/26 , NO TEMPORARY TRAFFIC DEVICES PROVIDED AS P")


class Rejects(unittest.TestCase):
    def assertRejected(self, line, needle, lang="en"):
        ok, why = check_line(line, SOURCE, lang)
        self.assertFalse(ok, f"accepted: {line!r}")
        self.assertIn(needle, why)

    def test_a_number_not_in_the_text(self):
        self.assertRejected("Three jersey barriers block the street", "number")      # word
        self.assertRejected("Jersey barriers block 5 lanes without a DOT permit", "number 5")
        self.assertRejected("Cinco barreras bloquean la calle sin permiso", "number 'cinco'", "es")

    def test_a_date_not_in_the_text(self):
        self.assertRejected("Barriers placed without permit on 9/2/26", "number")
        self.assertRejected("Barriers placed in September without a DOT permit", "date 'september'")
        self.assertRejected("Barreras colocadas el lunes sin permiso del DOT", "date 'lunes'", "es")

    def test_a_money_amount_not_in_the_text(self):
        self.assertRejected("Fine of $2,500 for barriers without permit", "number 2500")
        self.assertRejected("Barriers without permit; a fine in dollars applies", "money")

    def test_an_address_not_in_the_text(self):
        self.assertRejected("Jersey barriers on Taaffe Place without permit", "taaffe")
        self.assertRejected("Jersey barriers on taaffe place without permit", "address")
        self.assertRejected("Jersey barriers in Brooklyn street without permit", "brooklyn")

    def test_a_party_not_in_the_text(self):
        self.assertRejected("Jersey barriers placed by Blueview without a permit", "Blueview")
        self.assertRejected("Contractor Smith left barriers without a DOT permit", "Smith")
        self.assertRejected("Barriers placed without permit by acme llc", "llc")

    def test_too_long(self):
        self.assertRejected("Jersey barriers were installed in the street without the required DOT "
                            "permit for a lane closure", "words")

    def test_not_json(self):
        self.assertIsNone(parse_reply("Jersey barriers without permit"))
        self.assertFalse(check_pair(None, SOURCE)[0])


class Accepts(unittest.TestCase):
    def test_a_clean_line(self):
        for line, lang in (("Jersey barriers in the street without a DOT lane-closure permit", "en"),
                           ("Barreras Jersey en la calle sin permiso del DOT", "es")):
            ok, why = check_line(line, SOURCE, lang)
            self.assertTrue(ok, f"{line!r}: {why}")

    def test_a_number_that_is_in_the_text(self):
        ok, why = check_line("Barriers at exposure 1 without a DOT permit", SOURCE, "en")
        self.assertTrue(ok, why)
        ok, why = check_line("Fence permit expired 8/26/26; barriers lack DOT permit", SOURCE, "en")
        self.assertTrue(ok, why)

    def test_a_pair_from_a_fenced_reply(self):
        pair = parse_reply('```json\n{"en": "Jersey barriers without a DOT permit", '
                           '"es": "Barreras Jersey sin permiso del DOT"}\n```')
        self.assertEqual(pair["en"], "Jersey barriers without a DOT permit")
        self.assertEqual(check_pair(pair, SOURCE), (True, "ok"))


if __name__ == "__main__":
    unittest.main()
