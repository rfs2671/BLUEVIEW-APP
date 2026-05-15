"""PR #14B Stage 2.B — project schema dob_* fields tests.

TestProjectDobFields (4 tests) — verifies the Pydantic
``ProjectCreate`` + ``ProjectUpdate`` models accept the three new
PR #14B fields:

  • dob_project_type — enum: new_building / major_alt_with_enlargement
    / minor_alt / full_demo / unknown
  • dob_job_snapshot — dict (free-form DOB NOW row capture)
  • dob_extracted_scope — dict (parsed scope from job_description)

Plus round-trip behavior: setting via direct DB write surfaces
through the API GET response under the same keys.

Tests 1-2 cover Pydantic validation (synchronous, no FastAPI test
client required). Tests 3-4 cover round-trip via direct
``serialize_id`` invocation (the function ``GET /projects/{id}``
uses) to avoid mounting the entire FastAPI app inside this test
file.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Any, Dict

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


# ─── Lazy imports — Pydantic model + serializer ───────────────────

from server import ProjectCreate, serialize_id  # noqa: E402


# Probe: does ProjectCreate already accept dob_project_type? It
# doesn't pre-Stage-3 — the model defines a strict field list.
# Pydantic v2 default rejects extra fields with
# ConfigDict(extra='ignore') OR silently drops them. Either way
# the tests below assert the post-Stage-3 contract.
def _has_field(model_cls, field_name: str) -> bool:
    """Check whether a Pydantic model declares the named field."""
    try:
        fields = getattr(model_cls, "model_fields", None) or getattr(
            model_cls, "__fields__", None,
        ) or {}
        return field_name in fields
    except Exception:
        return False


HAS_DOB_PROJECT_TYPE_FIELD = _has_field(ProjectCreate, "dob_project_type")


# ──────────────────────────────────────────────────────────────────


class TestProjectDobFields(unittest.TestCase):
    """Stage 3 adds three optional fields to ``ProjectCreate``:

      dob_project_type:  Optional[Literal[
          'new_building', 'major_alt_with_enlargement',
          'minor_alt', 'full_demo', 'unknown',
      ]] = None
      dob_job_snapshot:   Optional[Dict[str, Any]] = None
      dob_extracted_scope: Optional[Dict[str, Any]] = None

    These tests pin that contract.
    """

    def _require_field(self, field_name: str):
        if not _has_field(ProjectCreate, field_name):
            self.fail(
                f"ProjectCreate Pydantic model missing field "
                f"{field_name!r}. Stage 3: add to ProjectCreate + "
                f"ProjectUpdate at server.py:1272-1320."
            )

    def test_project_create_accepts_dob_project_type_field(self):
        """Test 25 — ProjectCreate accepts dob_project_type with a
        valid enum value."""
        self._require_field("dob_project_type")
        proj = ProjectCreate(
            name="Test Project",
            dob_project_type="new_building",
        )
        self.assertEqual(
            getattr(proj, "dob_project_type", None),
            "new_building",
            "dob_project_type didn't round-trip through ProjectCreate",
        )

    def test_project_create_rejects_invalid_dob_project_type(self):
        """Test 26 — invalid enum value raises ValidationError.

        Uses pydantic.ValidationError; both Pydantic v1 + v2 raise
        a subclass thereof when a Literal-constrained field receives
        an unknown value.
        """
        self._require_field("dob_project_type")
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            ProjectCreate(
                name="Test Project",
                dob_project_type="bogus_value",
            )

    def test_project_dob_job_snapshot_round_trip_via_serialize_id(self):
        """Test 27 — direct DB write of dob_job_snapshot survives
        ``serialize_id`` (the helper that GET /projects/{id} uses
        to shape the response).
        """
        self._require_field("dob_job_snapshot")
        # Synthesize a project doc as Mongo would return it.
        doc = {
            "_id": "test_proj_id",
            "name": "Test",
            "dob_job_snapshot": {
                "work_type": "General Construction",
                "filing_reason": "Initial Permit",
                "job_description": "NEW BUILDING 5-STORY",
                "source": "dob_now_primary",
            },
        }
        serialized = serialize_id(dict(doc))
        self.assertIn("dob_job_snapshot", serialized)
        self.assertEqual(
            serialized["dob_job_snapshot"]["work_type"],
            "General Construction",
        )

    def test_project_dob_extracted_scope_round_trip_via_serialize_id(self):
        """Test 28 — same as test 27 for dob_extracted_scope."""
        self._require_field("dob_extracted_scope")
        doc = {
            "_id": "test_proj_id",
            "name": "Test",
            "dob_extracted_scope": {
                "story_count": 5,
                "dwelling_units": 8,
                "use_type": "residential",
                "enlargement": False,
                "extracted_at": "2026-05-14T12:00:00Z",
            },
        }
        serialized = serialize_id(dict(doc))
        self.assertIn("dob_extracted_scope", serialized)
        self.assertEqual(serialized["dob_extracted_scope"]["story_count"], 5)
        self.assertEqual(serialized["dob_extracted_scope"]["use_type"], "residential")


if __name__ == "__main__":
    unittest.main()
