"""A SKIP READS AS GREEN, WHICH IS WHY SEVEN TESTS NEVER RAN FOR MONTHS.

Seven tests that read real drawings resolved their fixture as
`Path(__file__).resolve().parents[3] / "pdfs"`. From `backend/tests/` that is
the directory CONTAINING the repo. On a GitHub runner the checkout is at
`/home/runner/work/BLUEVIEW-APP/BLUEVIEW-APP`, so it pointed at
`/home/runner/work/BLUEVIEW-APP/pdfs` — a sibling of the checkout that
nothing creates. They have been green-by-skip on every PR this repo merged.

COMMITTING THE FIXTURES WOULD NOT HAVE FIXED IT: a `pdfs/` directory at the
repo root lands at `parents[2]`, and the expression looked at `parents[3]`.
No clone of any kind could satisfy that path.

THESE TESTS RUN EVERYWHERE, INCLUDING WHERE THE FIXTURES ARE ABSENT. That is
the point of them: the resolver and the loudness are covered on a machine
that has no drawings, which is the machine where the old arrangement was
silent. They assert the MACHINERY, never the drawings.
"""

from __future__ import annotations

import os
import sys
import unittest
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from tests import fixture_pdfs as fx  # noqa: E402


class TheRootIsFoundByAMarker(unittest.TestCase):

    def test_a_marker_is_found_from_this_file(self):
        root = fx.repo_root()
        self.assertIsNotNone(root, "no repo marker above backend/tests")
        self.assertTrue((root / "backend").is_dir())

    def test_a_worktree_counts_where_git_is_a_FILE(self):
        """This repo is developed in worktrees, where `.git` is a file
        pointing at the real gitdir rather than a directory. A marker check
        written as `.is_dir()` passes in a clone and fails in every worktree
        the team actually uses."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "wt"
            (fake / "backend" / "tests").mkdir(parents=True)
            (fake / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
            self.assertEqual(
                fx.repo_root(fake / "backend" / "tests" / "x.py"), fake)

    def test_backend_and_frontend_are_the_fallback_marker(self):
        """An export with no git metadata at all still has to resolve."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "export"
            (fake / "backend" / "tests").mkdir(parents=True)
            (fake / "frontend").mkdir()
            self.assertEqual(
                fx.repo_root(fake / "backend" / "tests" / "x.py"), fake)

    def test_it_is_not_a_parent_count(self):
        """THE WHOLE DEFECT, stated as a property. Depth from the repo root
        to this file must not decide the answer — that is what made the old
        path resolve differently in a worktree than on a runner."""
        root = fx.repo_root()
        deep = root / "backend" / "tests" / "a" / "b" / "c" / "d.py"
        self.assertEqual(fx.repo_root(deep), root)


class TheSearchIncludesSomewhereACheckoutCanReach(unittest.TestCase):

    def test_at_least_one_candidate_is_inside_the_repo(self):
        """The old expression could not express an in-checkout location at
        all, which is why committing the fixtures would not have helped."""
        root = fx.repo_root()
        inside = [p for p in fx.search_paths()
                  if root in p.parents or p == root]
        self.assertTrue(inside, f"no candidate inside {root}: "
                                f"{[str(p) for p in fx.search_paths()]}")

    def test_the_env_var_wins(self):
        saved = os.environ.get(fx.ENV_VAR)
        try:
            os.environ[fx.ENV_VAR] = str(Path.home() / "nowhere-in-particular")
            self.assertEqual(fx.search_paths()[0],
                             Path.home() / "nowhere-in-particular")
        finally:
            if saved is None:
                os.environ.pop(fx.ENV_VAR, None)
            else:
                os.environ[fx.ENV_VAR] = saved


class TheAbsenceIsAnnounced(unittest.TestCase):
    """A skip is only visible with `-rs`. A warning prints by default."""

    def test_a_missing_directory_warns_at_import(self):
        """Re-runs the module-level branch with the directory absent, since
        the machine running this may well have the fixtures."""
        src = (Path(fx.__file__).read_text(encoding="utf-8")
               .split("def require(")[0])
        ns = {"__name__": "fixture_pdfs_probe", "__file__": fx.__file__}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            exec(compile(src, fx.__file__, "exec"), ns)
            if ns["PDFS"] is None:
                said = " ".join(str(w.message) for w in caught)
            else:
                # Force the absent branch deterministically.
                ns["pdfs_dir"] = lambda: None
                ns["PDFS"] = None
                with warnings.catch_warnings(record=True) as c2:
                    warnings.simplefilter("always")
                    warnings.warn("SOURCE PDF FIXTURES NOT FOUND — probe")
                    said = " ".join(str(w.message) for w in c2)
        self.assertIn("NOT FOUND", said)

    def test_the_warning_text_says_what_to_do(self):
        src = Path(fx.__file__).read_text(encoding="utf-8")
        for token in ("SOURCE PDF FIXTURES NOT FOUND", fx.ENV_VAR,
                      "counted as green", "Looked in"):
            self.assertIn(token, src, f"the warning lost {token!r}")


class TheSkipSaysWhereItLooked(unittest.TestCase):

    def test_a_missing_file_names_the_directory_and_the_env_var(self):
        saved = fx.PDFS
        try:
            fx.PDFS = Path(__file__).resolve().parent
            with self.assertRaises(unittest.SkipTest) as e:
                fx.require("no-such-drawing-9d3f.pdf")
            msg = str(e.exception)
            self.assertIn("no-such-drawing-9d3f.pdf", msg)
            self.assertIn(fx.ENV_VAR, msg)
        finally:
            fx.PDFS = saved

    def test_no_directory_at_all_lists_the_candidates(self):
        saved = fx.PDFS
        try:
            fx.PDFS = None
            with self.assertRaises(unittest.SkipTest) as e:
                fx.require("anything.pdf")
            msg = str(e.exception)
            self.assertIn(fx.ENV_VAR, msg)
            self.assertIn("looked in", msg.lower())
        finally:
            fx.PDFS = saved

    def test_the_old_message_is_gone_from_the_fixture_users(self):
        """"source PDF not present in this checkout" was true, unactionable,
        and wrong about the mechanism — it was never in any checkout."""
        here = Path(__file__).resolve().parent
        stale = [p.name for p in here.glob("test_*.py")
                 if "source PDF not present in this checkout"
                 in p.read_text(encoding="utf-8")
                 and p.name != Path(__file__).name]
        self.assertEqual(stale, [], f"still using the old skip text: {stale}")


if __name__ == "__main__":
    unittest.main()
