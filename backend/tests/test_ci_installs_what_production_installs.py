"""CI INSTALLS THE STACK PRODUCTION RUNS, OR IT TESTS A DIFFERENT ONE.

    python -m pytest backend/tests/test_ci_installs_what_production_installs.py

── WHAT THIS EXISTS TO CATCH, MEASURED ─────────────────────────────────────

#651 pinned the OCR stack in `backend/constraints.txt` (onnxruntime 1.30.0,
opencv-python 4.14.0.94, pypdfium2 5.13.0) and the Dockerfile hands it to pip
with `-c`. Nothing else did. `tests.yml` and `backend-import-smoke.yml` ran a
bare `pip install -r requirements.txt`, and none of the three is named in
requirements.txt -- they arrive through rapidocr-onnxruntime and pdfplumber --
so CI took whatever PyPI's newest was that morning.

That stopped being hypothetical on 2026-10-04, when pypdfium2 5.14.0 shipped:
from then on every backend suite ran on 5.14.0 while production rendered on
5.13.0. A green suite was a statement about a library the deploy does not
contain.

The resolution checks had the same hole from the other side. The workflow and
the pre-commit hook dry-ran requirements.txt WITHOUT the constraints, so a
pin that conflicts with a requirement -- the exact C2 -> C2.1 failure they
exist for -- resolved green in both and failed only in the Docker build. And
neither ran at all when constraints.txt was the file that changed.

── WHAT WOULD PROVE THIS TEST WRONG ────────────────────────────────────────

It reads text, not runs. The evidence is a CI log: the "Install backend
dependencies" step of `tests` and `backend-import-smoke` must list
`pypdfium2-5.13.0` and `opencv-python-4.14.0.94` among what it installed. If
a log shows any other version and this file is green, an install has reached
CI by a route these patterns do not see (a composite action, a script, a
`uv pip`).

── DERIVED, NOT LISTED ─────────────────────────────────────────────────────

The installs are every `install ... -r` command in every workflow and in the
hook, so a new job that installs requirements is covered the day it is added.
The two that ran the backend's code are named as well, so the census cannot
pass by finding nothing.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
HOOK = ROOT / ".githooks" / "pre-commit"
CONSTRAINTS = "backend/constraints.txt"


def _code(text: str) -> str:
    """The commands, not the prose: comment lines dropped, continuations joined."""
    lines = [l for l in text.splitlines() if not l.lstrip().startswith("#")]
    return re.sub(r"\\\n\s*", " ", "\n".join(lines))


def _requirement_installs(path: Path) -> list:
    """Every `pip install` that reads a requirements file, as one line each."""
    return [l.strip() for l in _code(path.read_text(encoding="utf-8")).splitlines()
            if re.search(r"\binstall\b", l) and re.search(r"\s-r\s", l)]


def _python_minor_of_the_image() -> str:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    m = re.search(r"(?m)^FROM python:(\d+\.\d+)-", text)
    assert m, "the Dockerfile's base image is not a python:X.Y image"
    return m.group(1)


class EveryInstallCarriesTheConstraints(unittest.TestCase):

    def test_every_requirements_install_in_ci_and_the_hook_is_constrained(self):
        census = {}
        for path in sorted(WORKFLOWS.glob("*.y*ml")) + [HOOK]:
            for cmd in _requirement_installs(path):
                census.setdefault(path.name, []).append(cmd)
        bare = [(name, cmd) for name, cmds in census.items() for cmd in cmds
                if f"-c {CONSTRAINTS}" not in cmd]
        self.assertEqual(bare, [], "these install the OCR stack unpinned")

    def test_the_census_reaches_the_jobs_that_run_the_backend(self):
        # A pattern that matched nothing would pass the test above vacuously.
        for name in ("tests.yml", "backend-import-smoke.yml",
                     "check-requirements.yml", "pre-commit"):
            path = HOOK if name == "pre-commit" else WORKFLOWS / name
            self.assertTrue(_requirement_installs(path), f"no install found in {name}")

    def test_the_constraints_file_is_where_the_flag_points(self):
        self.assertTrue((ROOT / CONSTRAINTS).is_file())


class TheResolutionCheckWorkflow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = (WORKFLOWS / "check-requirements.yml").read_text(encoding="utf-8")

    def _paths(self):
        on = self.text.split("\non:", 1)[1].split("\njobs:", 1)[0]
        listed = on.split("pull_request:", 1)[1].split("paths:", 1)[1]
        out = set()
        for line in listed.splitlines()[1:]:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            m = re.match(r"-\s*'([^']+)'", s)
            if not m:
                break
            out.add(m.group(1))
        self.assertTrue(out, "no pull_request paths found")
        return out

    def test_it_runs_when_the_constraints_change(self):
        self.assertIn(CONSTRAINTS, self._paths())

    def test_it_runs_when_it_changes_itself(self):
        # A change to the check must prove itself on its own PR.
        self.assertIn(".github/workflows/check-requirements.yml", self._paths())

    def test_it_resolves_on_the_image_s_python(self):
        m = re.search(r"python-version:\s*'([\d.]+)'", self.text)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), _python_minor_of_the_image())


class TheHookFiresOnTheConstraints(unittest.TestCase):

    def _trigger(self):
        text = HOOK.read_text(encoding="utf-8")
        body = text.split("check_requirements() {", 1)[1]
        m = re.search(r"grep -qE '([^']+)'", body)
        self.assertIsNotNone(m, "check_requirements has no grep -qE trigger")
        return re.compile(m.group(1))

    def test_constraints_staged_runs_the_check(self):
        self.assertTrue(self._trigger().search(CONSTRAINTS))

    def test_requirements_staged_still_runs_it(self):
        for path in ("requirements.txt", "backend/requirements.txt"):
            self.assertTrue(self._trigger().search(path), path)

    def test_an_unrelated_file_still_takes_the_fast_path(self):
        for path in ("backend/server.py", "docs/constraints.txt",
                     "backend/constraints.txt.bak", "frontend/requirements.txt"):
            self.assertFalse(self._trigger().search(path), path)


if __name__ == "__main__":
    unittest.main()
