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

    def test_env_var_wins(self):
        with patch.dict(os.environ, {"STORAGE_STATE_DIR": "/explicit"}):
            self.assertEqual(seed.resolve_storage_dir(), Path("/explicit"))

    def test_host_default_when_no_container_storage(self):
        """When /storage doesn't exist (host machine without
        the worker bind-mount), fall back to the home-dir path."""
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(seed, "DEFAULT_STORAGE_DIR_CONTAINER",
                          Path("/nonexistent-storage-test-path")):
            os.environ.pop("STORAGE_STATE_DIR", None)
            result = seed.resolve_storage_dir()
            # Should land on the home-dir default.
            self.assertEqual(result, seed.DEFAULT_STORAGE_DIR_HOST)

    def test_container_default_when_storage_exists(self):
        """When /storage exists (running inside the worker
        container with the bind-mount), prefer it over the
        home-dir path. Patching a Path instance's .exists is
        rejected by the runtime (Path attrs are read-only), so
        we substitute a fake DEFAULT_STORAGE_DIR_CONTAINER whose
        exists() returns True."""
        class _FakeDir:
            def exists(self):
                return True

        fake = _FakeDir()
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(seed, "DEFAULT_STORAGE_DIR_CONTAINER", fake):
            os.environ.pop("STORAGE_STATE_DIR", None)
            result = seed.resolve_storage_dir()
            self.assertIs(result, fake)


if __name__ == "__main__":
    unittest.main()
