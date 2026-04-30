"""Per-GC storage_state isolation + rotation."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DOB_WORKER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DOB_WORKER))


class TestStorageStateLifecycle(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["STORAGE_STATE_DIR"] = str(self.tmp)
        # Force module re-import to pick up env override.
        for k in list(sys.modules):
            if k.startswith("lib.browser_context"):
                del sys.modules[k]

    def test_per_gc_isolation(self):
        from lib import browser_context as bc
        # Same module-level constant reads at first import; reassign
        # for this test against the temp dir.
        bc.STORAGE_STATE_DIR = self.tmp

        # Two distinct GCs each get their own subdirectory.
        bc.save_meta("626198", {"request_count": 1, "license_number": "626198"})
        bc.save_meta("777777", {"request_count": 5, "license_number": "777777"})

        m1 = bc.load_meta("626198")
        m2 = bc.load_meta("777777")
        self.assertEqual(m1["request_count"], 1)
        self.assertEqual(m2["request_count"], 5)
        # Filesystem proves isolation.
        self.assertTrue((self.tmp / "626198" / "meta.json").exists())
        self.assertTrue((self.tmp / "777777" / "meta.json").exists())

    def test_increment_and_rotation_threshold(self):
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp
        bc.ROTATE_AFTER_REQUESTS = 5

        for _ in range(4):
            bc.increment_request_count("626198")
        self.assertFalse(bc.needs_rotation("626198"))
        bc.increment_request_count("626198")  # 5th
        self.assertTrue(bc.needs_rotation("626198"))

    def test_rotate_promotes_current_to_previous(self):
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp
        # Seed a current.json
        cur = self.tmp / "626198" / "current.json"
        cur.parent.mkdir(parents=True, exist_ok=True)
        cur.write_text('{"cookies": []}')
        bc.save_meta("626198", {"request_count": 200, "license_number": "626198"})

        bc.rotate("626198")
        # current.json gone, previous.json present with the same content.
        self.assertFalse(cur.exists())
        prev = self.tmp / "626198" / "previous.json"
        self.assertTrue(prev.exists())
        self.assertIn('"cookies"', prev.read_text())

        # Counter reset.
        meta = bc.load_meta("626198")
        self.assertEqual(meta["request_count"], 0)
        self.assertIsNotNone(meta["last_rotated_at"])

    def test_fall_back_to_previous(self):
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp
        prev = self.tmp / "626198" / "previous.json"
        prev.parent.mkdir(parents=True, exist_ok=True)
        prev.write_text('{"cookies": "prev-only"}')

        result = bc.fall_back_to_previous("626198")
        self.assertTrue(result)
        cur = self.tmp / "626198" / "current.json"
        self.assertTrue(cur.exists())
        self.assertIn("prev-only", cur.read_text())

    def test_fall_back_returns_false_when_no_previous(self):
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp
        self.assertFalse(bc.fall_back_to_previous("never-seen"))


if __name__ == "__main__":
    unittest.main()
