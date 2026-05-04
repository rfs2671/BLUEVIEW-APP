"""MR.14 commit 5 — static-source pins for the cleanup migration scripts.

We don't run the migrations against a live cluster here; both
scripts are operator-driven one-shots. The pins ensure the scripts
exist with the documented contract:

  • migrate_clean_stranded_renewals.py — soft-deletes
    permit_renewals where status='needs_insurance' AND
    days_until_expiry > 30 AND not already deleted.
  • migrate_clean_duplicate_projects.py — soft-deletes duplicate
    "638 Lafayette" projects, requires operator-supplied --keep.

The tests pin:
  1. The scripts exist.
  2. Both expose --dry-run and --execute as a mutually-exclusive
     required group.
  3. The target queries scope correctly to non-deleted docs.
  4. The duplicate-project script refuses --execute without --keep.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


SCRIPTS_DIR = _BACKEND / "scripts"
STRANDED_PATH = SCRIPTS_DIR / "migrate_clean_stranded_renewals.py"
DUP_PATH = SCRIPTS_DIR / "migrate_clean_duplicate_projects.py"


class TestStrandedRenewalsScript(unittest.TestCase):

    def test_script_exists(self):
        self.assertTrue(STRANDED_PATH.exists(), str(STRANDED_PATH))

    def test_target_query_excludes_deleted_and_scopes_correctly(self):
        src = STRANDED_PATH.read_text(encoding="utf-8")
        self.assertIn('"status": "needs_insurance"', src)
        self.assertIn('"days_until_expiry": {"$gt": 30}', src)
        self.assertIn('"is_deleted": {"$ne": True}', src)

    def test_soft_delete_marks_with_reason(self):
        src = STRANDED_PATH.read_text(encoding="utf-8")
        self.assertIn('"is_deleted": True', src)
        self.assertIn('"deleted_reason": "mr14_5_stranded_needs_insurance_cleanup"', src)

    def test_mutually_exclusive_required_mode(self):
        src = STRANDED_PATH.read_text(encoding="utf-8")
        self.assertIn("add_mutually_exclusive_group(required=True)", src)
        self.assertIn("--dry-run", src)
        self.assertIn("--execute", src)


class TestDuplicateProjectsScript(unittest.TestCase):

    def test_script_exists(self):
        self.assertTrue(DUP_PATH.exists(), str(DUP_PATH))

    def test_default_duplicate_name_pinned(self):
        src = DUP_PATH.read_text(encoding="utf-8")
        # The 4a anchor name (test_project_list_defaults references it
        # too — same incident).
        self.assertIn(
            'DEFAULT_DUPLICATE_NAME = "638 Lafayette Avenue, Brooklyn, NY, USA"',
            src,
        )

    def test_target_query_excludes_deleted(self):
        src = DUP_PATH.read_text(encoding="utf-8")
        self.assertIn('"is_deleted": {"$ne": True}', src)

    def test_execute_requires_keep_flag(self):
        src = DUP_PATH.read_text(encoding="utf-8")
        # The defensive check: if --execute and not --keep, error +
        # exit code 2.
        self.assertIn("--execute requires --keep", src)

    def test_keep_id_validated_against_candidates(self):
        src = DUP_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "doesn't match any candidate",
            src,
            "Should refuse keep_id that isn't in the candidate cohort.",
        )

    def test_mutually_exclusive_required_mode(self):
        src = DUP_PATH.read_text(encoding="utf-8")
        self.assertIn("add_mutually_exclusive_group(required=True)", src)
        self.assertIn("--dry-run", src)
        self.assertIn("--execute", src)


if __name__ == "__main__":
    unittest.main()
