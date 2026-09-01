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


class AStripperThatDeletesCodeIsWorseThanNoStripper(unittest.TestCase):
    """The block-comment regex ate live code, and absence tests went quiet.

    `_BLOCK` was `/\\*[\\s\\S]*?\\*/` applied before line comments, so a `//`
    comment CONTAINING the characters `/*` opened a block that ran to the next
    `*/` anywhere in the file. Found in CpNav.js:

        // Its active rule is "any /logbooks/*", which now includes ...

    which swallowed the entire nav-item map.

    WHY THIS CLASS EXISTS SEPARATELY FROM THE ONES ABOVE. Those check that
    prose is REMOVED. These check that code is KEPT, and that is the direction
    with the silent failure: a deletion makes assertIn fail loudly, and makes
    assertNotIn — 617 of them, across 20 files — pass while asserting nothing.
    """

    def test_a_line_comment_containing_a_block_opener_eats_nothing(self):
        src = (
            'const a = 1;\n'
            '// its rule is "any /logbooks/*", which now includes the child\n'
            'const BANNED = shouldNotSurvive();\n'
            '{/* an ordinary jsx comment */}\n'
            'const b = 2;\n'
        )
        out = strip_js(src)
        self.assertIn("const BANNED = shouldNotSurvive();", out,
                      "the code between the two was deleted")
        self.assertIn("const b = 2;", out)
        self.assertNotIn("any /logbooks/*", out, "the comment itself still goes")
        self.assertNotIn("an ordinary jsx comment", out)

    def test_the_failure_was_a_SILENT_pass_not_a_loud_one(self):
        # The shape that matters: an absence assertion over a region a stray
        # `/*` had blanked would pass with the banned call sitting right there.
        src = (
            '// see /docs/*.md\n'
            'db.logbooks.deleteMany({});\n'
            '/* real comment */\n'
        )
        self.assertIn("db.logbooks.deleteMany", strip_js(src),
                      "an assertNotIn over this would have passed vacuously")

    def test_comment_markers_inside_strings_are_not_comments(self):
        src = (
            "const url = 'https://x.test/a';\n"
            'const glob = "/logbooks/*";\n'
            'const tpl = `a /* not a comment */ b`;\n'
            'const KEPT = 1;\n'
        )
        out = strip_js(src)
        self.assertIn("https://x.test/a", out)
        self.assertIn('"/logbooks/*"', out)
        self.assertIn("a /* not a comment */ b", out)
        self.assertIn("const KEPT = 1;", out)

    def test_a_regex_literal_is_not_a_comment(self):
        # `/[//]/` and `/x*/` both contain comment markers. Treating either as
        # a comment deletes the rest of the line — code, again.
        src = (
            'const re = /[//]/;\n'
            'const KEPT_A = 1;\n'
            'const star = /a*/;\n'
            'const KEPT_B = 2;\n'
        )
        out = strip_js(src)
        self.assertIn("const KEPT_A = 1;", out)
        self.assertIn("const KEPT_B = 2;", out)

    def test_line_numbers_survive_a_block_comment(self):
        # Failure messages quote line numbers; a stripper that collapses them
        # sends the reader to the wrong place.
        src = 'a\n/* one\ntwo\nthree */\nb\n'
        self.assertEqual(strip_js(src).count("\n"), src.count("\n"))

    def test_the_real_file_that_found_it(self):
        nav = code_of("frontend/src/components/CpNav.js")
        self.assertIn("setShowCheckinQr(true)", nav)
        self.assertIn("item.path === CHECKIN_QR_ACTION", nav)


if __name__ == "__main__":
    unittest.main()
