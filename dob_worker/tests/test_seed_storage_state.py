"""MR.11.1 — seed_storage_state.py CLI helper tests.

Pure-function coverage only — we don't import or invoke
Playwright in tests. The async main() that runs the browser
is intentionally not exercised here; that path is operator-
manual by design (see the script's docstring).

Coverage:
  • parse_args: required positional, optional flags
  • output_path_for: composes storage-dir + license + filename;
    rejects path separators in license_number
  • resolve_storage_dir: env-var override path; host vs container
    default selection
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_DOB_WORKER = _HERE.parent
sys.path.insert(0, str(_DOB_WORKER))


# Importing the module is cheap — Playwright is imported inside
# main() (lazy), so test discovery doesn't require it.
from scripts import seed_storage_state as seed  # noqa: E402


class TestParseArgs(unittest.TestCase):

    def test_required_positional(self):
        args = seed.parse_args(["626198"])
        self.assertEqual(args.gc_license_number, "626198")
        self.assertIsNone(args.storage_dir)
        self.assertEqual(args.output_name, "current.json")

    def test_storage_dir_override(self):
        args = seed.parse_args([
            "626198", "--storage-dir", "/tmp/seed-test",
        ])
        self.assertEqual(args.storage_dir, "/tmp/seed-test")

    def test_landing_url_default_is_dob_now(self):
        args = seed.parse_args(["626198"])
        self.assertIn("a810-dobnow.nyc.gov", args.landing_url)

    def test_output_name_override(self):
        args = seed.parse_args(["626198", "--output-name", "alt.json"])
        self.assertEqual(args.output_name, "alt.json")

    def test_missing_positional_exits(self):
        with self.assertRaises(SystemExit):
            seed.parse_args([])


class TestOutputPathFor(unittest.TestCase):

    def test_composes_path_with_storage_dir(self):
        args = seed.parse_args(["626198", "--storage-dir", "/x"])
        path = seed.output_path_for(args)
        # Use Path comparison to be cross-platform-safe.
        expected = Path("/x") / "626198" / "current.json"
        self.assertEqual(path, expected)

    def test_uses_default_storage_dir_when_unset(self):
        args = seed.parse_args(["626198"])
        path = seed.output_path_for(args)
        # Path ends with the GC dir + filename regardless of root.
        self.assertEqual(path.name, "current.json")
        self.assertEqual(path.parent.name, "626198")

    def test_rejects_slash_in_license_number(self):
        args = seed.parse_args(["bad/license", "--storage-dir", "/x"])
        with self.assertRaises(ValueError):
            seed.output_path_for(args)

    def test_rejects_backslash_in_license_number(self):
        args = seed.parse_args(["bad\\license", "--storage-dir", "/x"])
        with self.assertRaises(ValueError):
            seed.output_path_for(args)

    def test_custom_output_name_threaded_through(self):
        args = seed.parse_args([
            "626198",
            "--storage-dir", "/x",
            "--output-name", "previous.json",
        ])
        path = seed.output_path_for(args)
        self.assertEqual(path.name, "previous.json")


class TestResolveStorageDir(unittest.TestCase):
    """MR.11.2 — resolution prefers LEVELOG_AGENT_STORAGE_DIR (the
    HOST-side env var the operator's setup configures), falling
    back to ~/.levelog/agent-storage. STORAGE_STATE_DIR is
    explicitly NOT consulted — it describes the worker's
    in-container path and was the cause of the prior bug where
    the seed script wrote to C:\\storage instead of the home dir."""

    def test_levelog_agent_storage_dir_env_var_wins(self):
        with patch.dict(
            os.environ, {"LEVELOG_AGENT_STORAGE_DIR": "/explicit/host/path"},
        ):
            self.assertEqual(
                seed.resolve_storage_dir(),
                Path("/explicit/host/path"),
            )

    def test_falls_back_to_home_dir_when_no_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEVELOG_AGENT_STORAGE_DIR", None)
            os.environ.pop("STORAGE_STATE_DIR", None)
            result = seed.resolve_storage_dir()
            self.assertEqual(result, seed.DEFAULT_STORAGE_DIR_HOST)

    def test_storage_state_dir_explicitly_ignored(self):
        """Regression for the MR.11.2 bug: a leaked
        STORAGE_STATE_DIR=/storage in the host shell (from sourcing
        dob_worker/.env.local) MUST NOT influence the host-run
        seed script's resolution. Ignore it entirely."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEVELOG_AGENT_STORAGE_DIR", None)
            os.environ["STORAGE_STATE_DIR"] = "/storage"
            result = seed.resolve_storage_dir()
            # Must be the home-dir default, NOT /storage.
            self.assertEqual(result, seed.DEFAULT_STORAGE_DIR_HOST)
            self.assertNotEqual(result, Path("/storage"))


class TestDetectMisplacedLegacySeed(unittest.TestCase):
    """The MR.11.2 fix surfaces a one-shot warning when an old
    /storage path holds a real seeded session that the operator
    needs to relocate manually."""

    def test_returns_none_when_no_legacy_file(self):
        """Use a license number that vanishingly is unlikely to exist
        at the legacy location. The dev machine that hit the original
        bug may still have C:\\storage\\626198\\current.json present;
        a randomized path keeps this test machine-independent."""
        import tempfile
        import uuid
        with tempfile.TemporaryDirectory() as tmp:
            unique = f"never-{uuid.uuid4().hex}"
            new_path = Path(tmp) / unique / "current.json"
            result = seed.detect_misplaced_legacy_seed(unique, new_path)
            self.assertIsNone(result)

    def test_returns_none_when_new_path_already_exists(self):
        """If the operator already moved the file OR successfully
        re-seeded, the new path is non-empty and we don't warn."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            new_path = Path(tmp) / "626198" / "current.json"
            new_path.parent.mkdir(parents=True)
            new_path.write_text('{"cookies": []}')
            result = seed.detect_misplaced_legacy_seed("626198", new_path)
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
