"""The helper that closes the docstring trap, and proof it closes it.

FOUR TIMES on this project an absence assertion has passed because it matched
the PROSE describing the rule instead of the code implementing it:

  * a test asserting server.py's renderers no longer do `.get("company")`,
    satisfied by the comment explaining why they no longer do;
  * `ok(!/rgba\\(/)` on a stylesheet, satisfied by the header sentence "no raw
    hex, rgba() or numeric fontSize";
  * two @media-print assertions, satisfied by the CSS comment "Email clients
    ignore @media print";
  * "this module touches no db.logbooks", satisfied by the docstring saying
    exactly that.

Twice of those four came AFTER the shape was written up. So this is mechanical
now rather than remembered: code_of() strips by default and a test has to ask
for raw=True on purpose.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from tests.source_text import code_of, strip_js, strip_python  # noqa: E402


class ItRemovesWhatMisleads(unittest.TestCase):
    def test_a_docstring_claiming_the_banned_thing_is_gone(self):
        src = '"""Nothing here writes to db.logbooks."""\nX = 1\n'
        self.assertNotIn("db.logbooks", strip_python(src))

    def test_a_hash_comment_too(self):
        self.assertNotIn("db.logbooks", strip_python("# never db.logbooks\nX = 1\n"))

    def test_a_trailing_hash_comment_too(self):
        self.assertNotIn("db.logbooks", strip_python("X = 1  # not db.logbooks\n"))

    def test_single_quoted_docstrings_as_well(self):
        self.assertNotIn("forbidden", strip_python("'''forbidden'''\nX = 1\n"))

    def test_js_block_and_line_comments(self):
        self.assertNotIn("rgba(", strip_js("/* no rgba() here */\nconst a = 1;\n"))
        self.assertNotIn("rgba(", strip_js("// no rgba() here\nconst a = 1;\n"))
        self.assertNotIn("rgba(", strip_js("const a = 1; // no rgba()\n"))


class ItKeepsWhatMatters(unittest.TestCase):
    """The control. A stripper that ate the code would pass everything above
    and assert nothing at all."""

    def test_real_code_survives_python(self):
        out = strip_python('"""doc"""\nawait db.logbooks.find_one({})\n')
        self.assertIn("db.logbooks.find_one", out)

    def test_real_code_survives_js(self):
        self.assertIn("rgba(0,0,0,0.5)",
                      strip_js("/* c */\nconst x = 'rgba(0,0,0,0.5)';\n"))

    def test_an_ordinary_string_is_not_a_docstring(self):
        self.assertIn('"db.logbooks"', strip_python('x = "db.logbooks"\n'))

    def test_a_url_is_not_a_line_comment(self):
        """`//` inside a string is not a comment, and eating it would silently
        shorten the subject of every assertion after it."""
        self.assertIn("https://api.levelog.com",
                      strip_js("const u = 'https://api.levelog.com';\n"))


class ItReadsRealFiles(unittest.TestCase):
    def test_it_resolves_a_backend_path(self):
        self.assertIn("def verify_sentence", code_of("lib/ai/sub_summary.py"))

    def test_and_a_repo_root_path(self):
        self.assertIn("export function", code_of(
            "frontend/src/components/logbookStepper/primitives.jsx"))

    def test_raw_keeps_the_prose_for_assertions_that_are_ABOUT_the_prose(self):
        """Provenance notes are load-bearing in this codebase — "a dead
        duplicate of the answers question" is an assertion worth making."""
        raw = code_of("server.py", raw=True)
        self.assertIn("dead duplicate of the answers", raw)
        self.assertNotIn("dead duplicate of the answers", code_of("server.py"))

    def test_a_missing_file_raises_rather_than_returning_empty(self):
        """An empty subject makes every absence assertion pass — the exact
        failure this file exists to stop."""
        with self.assertRaises(FileNotFoundError):
            code_of("no/such/file.py")


class TheTrapItselfIsReproduced(unittest.TestCase):
    """The proof. The same assertion, on the same file, both ways."""

    FILE = "lib/ai/sub_summary.py"

    def test_raw_gives_the_FALSE_pass(self):
        """sub_summary's docstring says it writes to no db.logbooks. Asserting
        on the raw text finds that sentence and reports a violation that does
        not exist — which is how this was noticed."""
        self.assertIn("db.logbooks", code_of(self.FILE, raw=True))

    def test_stripped_gives_the_TRUE_answer(self):
        self.assertNotIn("db.logbooks", code_of(self.FILE))


if __name__ == "__main__":
    unittest.main()
