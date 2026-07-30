"""PR G — display-time capitalization helpers (report/PDF renderer side).

_capitalize_first (short entry) and _sentence_case (prose) must capitalize for
professionalism WITHOUT mutating the rest of what the user typed, and must match
the frontend capitalizeFirst / sentenceCase.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


class CapitalizeFirstTest(unittest.TestCase):
    def test_capitalizes_first_letter_only(self):
        self.assertEqual(server._capitalize_first("aaz concrete"), "Aaz concrete")

    def test_preserves_rest_exactly(self):
        # Interior caps / acronyms are NOT reformatted.
        self.assertEqual(server._capitalize_first("aBC iNc"), "ABC iNc")
        self.assertEqual(server._capitalize_first("3rd floor"), "3rd floor")

    def test_leading_whitespace_preserved(self):
        self.assertEqual(server._capitalize_first("  hello"), "  Hello")

    def test_empty_and_none(self):
        self.assertEqual(server._capitalize_first(""), "")
        self.assertEqual(server._capitalize_first(None), "")


class SentenceCaseTest(unittest.TestCase):
    def test_first_letter(self):
        self.assertEqual(server._sentence_case("poured slab today"), "Poured slab today")

    def test_capital_after_terminal_punct(self):
        self.assertEqual(
            server._sentence_case("poured slab. cured overnight. stripped forms."),
            "Poured slab. Cured overnight. Stripped forms.",
        )
        self.assertEqual(server._sentence_case("done! next?"), "Done! Next?")

    def test_rest_preserved(self):
        # An interior acronym stays as typed; only sentence starts change.
        self.assertEqual(
            server._sentence_case("checked PPE. all OK."),
            "Checked PPE. All OK.",
        )

    def test_empty_and_none(self):
        self.assertEqual(server._sentence_case(""), "")
        self.assertEqual(server._sentence_case(None), "")


if __name__ == "__main__":
    unittest.main()
