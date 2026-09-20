"""THE DETECTION WAS NEVER MISSING. THE POSITION WAS.

`test_absence_literals_are_specific.py` caught the same reflex — an
`assertNotIn` against a string with a bare, unanchored literal — FOUR separate
times in one week. Every catch was correct and every catch was late: write the
assertion, push, watch the suite fail, anchor it, push again. A rule that fires
four times on the same author at the same point in the loop is not a knowledge
problem; the check simply ran after the commit instead of before it.

So the scanner moved to `tests/absence_literals.py` and a pre-commit stage
calls it on the STAGED blobs. This file asserts the two properties that make
that move safe:

  1. ONE implementation. The gate's `test_no_unjustified_bare_literal` calls
     `offenders()`, which is the same function the hook's script calls. Two
     copies of a classifier drift, and the drift is silent in the direction
     nobody watches — the hook passing what the gate then fails.

  2. THE SCANNER STILL FINDS THINGS THROUGH THE NEW ENTRY POINT. A path-taking
     `scan()` that quietly returns nothing for a real file would make the hook
     a no-op, which looks exactly like success.

WHAT IS NOT ASSERTED HERE, because it would be theatre: that the git hook is
INSTALLED. `core.hooksPath` is per-clone local config and a test cannot
require a developer's machine to be set up. `scripts/install-hooks.sh` is the
install, and CI's own run of the gate is the backstop for anyone who skips it.
The hook is an early warning; the suite remains the gate.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.absence_literals import offenders, scan

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
_SCRIPT = _BACKEND / "scripts" / "check_absence_literals.py"
_HOOK = _REPO / ".githooks" / "pre-commit"

_OFFENDER = (
    "import unittest\n"
    "class T(unittest.TestCase):\n"
    "    def test_a(self):\n"
    "        html = render_report()\n"
    "        self.assertNotIn('Pass', html)\n"
)
_CLEAN = (
    "import unittest\n"
    "class T(unittest.TestCase):\n"
    "    def test_a(self):\n"
    "        html = render_report()\n"
    "        self.assertNotIn('>Pass<', html)\n"
)


def _write(tmp: str, name: str, body: str) -> Path:
    p = Path(tmp) / name
    p.write_text(body, encoding="utf-8")
    return p


class TheScannerIsOneImplementation(unittest.TestCase):

    def test_the_gate_calls_the_function_the_hook_calls(self):
        """Read off the gate's source, not assumed from the import list.

        An import that nothing calls would let the gate keep a private copy of
        the filter while the hook used the shared one — which is precisely the
        drift this file exists to refuse.
        """
        src = (_BACKEND / "tests"
               / "test_absence_literals_are_specific.py").read_text(
                   encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "test_no_unjustified_bare_literal")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn(
            "offenders", called,
            "the gate must go through offenders() — the hook's code path is "
            "otherwise unproven by any test",
        )

    def test_the_script_imports_rather_than_reimplements(self):
        """No second allowlist, no second anchor set."""
        src = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn("from tests.absence_literals import", src)
        self.assertNotIn("_BARE_BY_DESIGN = ", src)
        self.assertNotIn("_ANCHORS = ", src)


class TheScannerWorksThroughTheNewEntryPoint(unittest.TestCase):

    def test_a_bare_literal_in_a_given_file_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "test_made_up.py", _OFFENDER)
            found = offenders([p])
        self.assertEqual([f.literal for f in found], ["Pass"])

    def test_an_anchored_literal_in_a_given_file_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "test_made_up.py", _CLEAN)
            found = offenders([p])
            _bare, anchored, _u, total = scan([p])
        self.assertEqual([], found)
        self.assertEqual((anchored, total), (1, 1),
                         "the anchored assertion must still be SEEN, not "
                         "merely unflagged — a scanner that classified "
                         "nothing would also report zero offenders")

    def test_the_allowlist_is_keyed_on_basename_so_a_staged_blob_matches(self):
        """The property the hook depends on. It writes each staged blob to a
        temp directory under its own basename; if the allowlist were keyed on
        full path, every justified bare literal would be reported as new."""
        with tempfile.TemporaryDirectory() as tmp:
            # A real justified entry: test_photo_enhance.py may ban "opencv".
            p = _write(tmp, "test_photo_enhance.py",
                       "import unittest\n"
                       "class T(unittest.TestCase):\n"
                       "    def test_a(self):\n"
                       "        src = read_text()\n"
                       "        self.assertNotIn('opencv', src)\n")
            self.assertEqual([], offenders([p]))
            # Same content, different name → not justified there.
            q = _write(tmp, "test_somewhere_else.py",
                       p.read_text(encoding="utf-8"))
            self.assertEqual(["opencv"], [f.literal for f in offenders([q])])


class TheScriptReportsWhatItDid(unittest.TestCase):

    def _run(self, *paths):
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *[str(p) for p in paths]],
            capture_output=True, text=True, cwd=str(_REPO))

    def test_an_offender_exits_one_and_names_the_file_and_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "test_made_up.py", _OFFENDER)
            r = self._run(p)
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("test_made_up.py:5", r.stdout)
        self.assertIn("render_pass_cell(", r.stdout,
                      "the report has to say what anchoring looks like")

    def test_a_clean_file_exits_zero_and_says_what_it_scanned(self):
        """Silence would be indistinguishable from a scan that read nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "test_made_up.py", _CLEAN)
            r = self._run(p)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("1 anchored", r.stdout)

    def test_a_missing_path_is_a_usage_error_not_a_pass(self):
        r = self._run(Path("no_such_file_at_all.py"))
        self.assertEqual(2, r.returncode)


class TheHookRunsBothChecks(unittest.TestCase):
    """The stage was ADDED to the existing hook, not swapped in for it."""

    def test_the_requirements_check_survived(self):
        src = _HOOK.read_text(encoding="utf-8")
        self.assertIn("check_requirements", src)
        self.assertIn("pip install --dry-run", src)

    def test_the_absence_check_is_wired_in(self):
        src = _HOOK.read_text(encoding="utf-8")
        self.assertIn("check_absence_literals", src)
        self.assertIn("backend/scripts/check_absence_literals.py", src)

    def test_neither_check_can_short_circuit_the_other(self):
        """Both run and the exit code is the OR. An early `exit 0` from the
        first stage — which is how the hook was written when it had only one —
        would silently skip the second."""
        src = _HOOK.read_text(encoding="utf-8")
        tail = src[src.index("FAILED=0"):]
        self.assertIn("check_requirements     || FAILED=1", tail)
        self.assertIn("check_absence_literals || FAILED=1", tail)
        self.assertIn('if [ "$FAILED" -ne 0 ]; then', tail)

    def test_it_reads_the_staged_blob_not_the_working_copy(self):
        """This repo stages by hunk routinely, so the working copy of a
        partially staged file is not what is being committed."""
        src = _HOOK.read_text(encoding="utf-8")
        self.assertIn("git cat-file -p", src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
