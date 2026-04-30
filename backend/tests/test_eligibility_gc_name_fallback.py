"""MR.7-followup — GC legal name fallback chain.

Operator hit "GC Legal Name required" in production despite the
company having `name`, `gc_business_name`, and `gc_licensee_name`
populated by the BIS scrape. Root cause: the prior fallback chain
in api_check_eligibility was project.gc_legal_name → company.name
only, skipping the BIS-canonical fields entirely AND failing
when company resolved to None.

This commit fixes the chain to:
  1. project.gc_legal_name   (manual override)
  2. company.gc_business_name (BIS-canonical, primary)
  3. company.gc_licensee_name (BIS-canonical alternate)
  4. company.name             (last resort)

The helper _resolve_gc_legal_name in permit_renewal.py is pure —
no IO, no Mongo. We exercise it here against fixture dicts.

Coverage:
  • Each priority level is the chosen winner when higher-priority
    fields are empty.
  • Whitespace-only strings are treated as empty (consistent with
    the .strip() behavior).
  • None / missing companies / None projects don't crash.
  • All-four-empty returns "" (caller raises 400).
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
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


# ── Priority chain ─────────────────────────────────────────────────

class TestResolveGcLegalNamePriority(unittest.TestCase):
    """Each test pins one priority level and clears all higher
    priorities so the test name == the field that should win."""

    def test_priority_1_project_override_wins(self):
        from permit_renewal import _resolve_gc_legal_name
        project = {"gc_legal_name": "Custom Override LLC"}
        company = {
            "gc_business_name": "BIS BUSINESS NAME",
            "gc_licensee_name": "BIS LICENSEE NAME",
            "name": "blueview construction inc",
        }
        self.assertEqual(
            _resolve_gc_legal_name(project, company),
            "Custom Override LLC",
        )

    def test_priority_2_business_name_wins_when_no_override(self):
        from permit_renewal import _resolve_gc_legal_name
        project = {}  # no gc_legal_name override
        company = {
            "gc_business_name": "BLUEVIEW CONSTRUCTION INC",
            "gc_licensee_name": "BLUEVIEW CONSTRUCTION INC",
            "name": "blueview construction",
        }
        self.assertEqual(
            _resolve_gc_legal_name(project, company),
            "BLUEVIEW CONSTRUCTION INC",
        )

    def test_priority_3_licensee_name_wins_when_business_name_empty(self):
        from permit_renewal import _resolve_gc_legal_name
        project = {"gc_legal_name": ""}
        company = {
            "gc_business_name": None,
            "gc_licensee_name": "JANE FILER",
            "name": "Jane's Filing Services",
        }
        self.assertEqual(
            _resolve_gc_legal_name(project, company),
            "JANE FILER",
        )

    def test_priority_4_company_name_last_resort(self):
        from permit_renewal import _resolve_gc_legal_name
        project = None
        company = {
            "gc_business_name": "",
            "gc_licensee_name": None,
            "name": "Customer Typed This Name",
        }
        self.assertEqual(
            _resolve_gc_legal_name(project, company),
            "Customer Typed This Name",
        )

    def test_all_four_empty_returns_empty_string(self):
        from permit_renewal import _resolve_gc_legal_name
        project = {"gc_legal_name": ""}
        company = {
            "gc_business_name": "",
            "gc_licensee_name": "",
            "name": "",
        }
        self.assertEqual(_resolve_gc_legal_name(project, company), "")


# ── Edge cases ─────────────────────────────────────────────────────

class TestResolveGcLegalNameEdges(unittest.TestCase):

    def test_none_project_uses_company_chain(self):
        from permit_renewal import _resolve_gc_legal_name
        company = {"gc_business_name": "ACME GC INC"}
        self.assertEqual(
            _resolve_gc_legal_name(None, company),
            "ACME GC INC",
        )

    def test_none_company_uses_project_only(self):
        from permit_renewal import _resolve_gc_legal_name
        project = {"gc_legal_name": "Project Override"}
        self.assertEqual(
            _resolve_gc_legal_name(project, None),
            "Project Override",
        )

    def test_both_none_returns_empty(self):
        from permit_renewal import _resolve_gc_legal_name
        self.assertEqual(_resolve_gc_legal_name(None, None), "")

    def test_whitespace_only_treated_as_empty(self):
        """Operator typing spaces in the override input should not
        beat a real BIS-canonical name on the company doc."""
        from permit_renewal import _resolve_gc_legal_name
        project = {"gc_legal_name": "   "}
        company = {"gc_business_name": "BIS CANONICAL CO"}
        self.assertEqual(
            _resolve_gc_legal_name(project, company),
            "BIS CANONICAL CO",
        )

    def test_strips_surrounding_whitespace_on_winner(self):
        from permit_renewal import _resolve_gc_legal_name
        project = {"gc_legal_name": "  Padded Name LLC  "}
        company = None
        self.assertEqual(
            _resolve_gc_legal_name(project, company),
            "Padded Name LLC",
        )

    def test_non_string_value_skipped(self):
        """Defensive — Mongo can occasionally surface unexpected
        types (e.g. legacy numeric IDs). Non-strings should fall
        through to the next candidate, not raise."""
        from permit_renewal import _resolve_gc_legal_name
        project = {"gc_legal_name": 12345}  # bad data
        company = {"gc_business_name": "REAL NAME INC"}
        self.assertEqual(
            _resolve_gc_legal_name(project, company),
            "REAL NAME INC",
        )

    def test_missing_keys_treated_as_empty(self):
        from permit_renewal import _resolve_gc_legal_name
        project = {}
        company = {"name": "Fallback"}
        self.assertEqual(
            _resolve_gc_legal_name(project, company),
            "Fallback",
        )


if __name__ == "__main__":
    unittest.main()
