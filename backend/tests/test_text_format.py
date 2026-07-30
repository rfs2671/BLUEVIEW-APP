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


class RendererCapitalizationTest(unittest.TestCase):
    """PR G extension: the per-logbook renderer applies the rules to
    toolbox_talk and preshift_signin (daily_jobsite was covered by PR G)."""

    def _render(self, logbook):
        import asyncio
        from unittest.mock import patch

        class _Coll:
            async def find_one(self, *a, **k):
                return {"name": "Test Tower", "address": "1 St"}

        class _DB:
            projects = _Coll()

        with patch.object(server, "db", _DB()):
            return asyncio.run(server.generate_single_logbook_html(logbook))

    def test_toolbox_talk_capitalization(self):
        html = self._render({
            "log_type": "toolbox_talk", "date": "2026-07-30", "project_id": "p1",
            "cp_name": "ada cp",
            "data": {
                "location": "west cellar", "company_name": "aaz concrete",
                "performed_by": "bob foreman", "meeting_time": "07:00",
                "attendees": [{"name": "juan perez", "company": "aaz concrete", "signed": True}],
            },
        })
        self.assertIn("Juan perez", html)          # short-entry: first char only
        self.assertIn("Aaz concrete", html)        # company capitalized
        self.assertIn("West cellar", html)         # location capitalized
        self.assertIn("Bob foreman", html)         # performed_by capitalized
        self.assertIn("Ada cp", html)              # cp capitalized

    def test_preshift_signin_capitalization_excludes_osha_number(self):
        html = self._render({
            "log_type": "preshift_signin", "date": "2026-07-30", "project_id": "p1",
            "cp_name": "ada cp",
            "data": {
                "company": "aaz concrete", "project_location": "2nd floor",
                "workers": [{"name": "maria lopez", "company": "aaz concrete",
                             "osha_number": "sst12345678"}],
            },
        })
        self.assertIn("Maria lopez", html)
        self.assertIn("2nd floor", html)           # capitalizeFirst leaves a leading digit
        # OSHA number is an identifier — NOT capitalized.
        self.assertIn("sst12345678", html)
        self.assertNotIn("Sst12345678", html)


if __name__ == "__main__":
    unittest.main()
