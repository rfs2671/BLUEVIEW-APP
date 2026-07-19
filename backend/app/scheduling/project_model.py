"""Typed per-project structured model for Blueview.

Single responsibility: define the ProjectModel object (and its provenance
metadata) that the aggregator produces and the scheduler will later consume.
This module holds ONLY the types + the controlled vocabulary. No DB access,
no aggregation logic, no HTTP.

Field-sourcing tiers (see aggregator.py for how each is populated):
  - plan_derived    : aggregated from document_page_index, no operator step.
  - plan_seeded     : proposed from plan free-text; MUST be operator-confirmed
                      before it is treated as authoritative (low confidence).
  - operator_declared: asserted by an operator (e.g. a special inspection the
                      plans didn't surface).

Nothing here is sourced from TR1 filings — that data does not exist in the
codebase (confirmed absent). Required special inspections therefore start life
as low-confidence plan-seeded proposals and only become authoritative once an
operator confirms them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── Controlled vocabulary ────────────────────────────────────────────
# Canonical special-inspection types, loosely aligned to NYC BC Chapter 17 /
# TR1 families. Proposals are normalized to these; operator-declared additions
# are validated against this set (unknown types are rejected).
SPECIAL_INSPECTION_VOCAB: tuple = (
    "firestopping",
    "fire_resistant_penetrations",
    "mechanical",
    "sprinkler",
    "standpipe",
    "energy_nycecc",
    "structural_steel",
    "structural_welding",
    "structural_bolting",
    "structural_concrete",
    "masonry",
    "soil_investigation",
    "deep_foundations",
    "fuel_gas_piping",
    "sprayed_fire_resistant_material",
    "post_installed_anchors",
)

# Plan-derived scalar boolean/int fields that carry per-field provenance.
PLAN_DERIVED_SCALARS: tuple = (
    "floors",
    "has_gas",
    "has_sprinkler",
    "has_standpipe",
    "has_elevator",
)


def is_known_special_inspection(inspection_type: str) -> bool:
    return inspection_type in SPECIAL_INSPECTION_VOCAB


# ── Provenance ───────────────────────────────────────────────────────
class FieldProvenance(BaseModel):
    """Where a field's current value came from and whether an operator has
    confirmed it. `evidence_page_ids` are document_page_index row ids that
    support the value."""

    source: Literal["plan_derived", "plan_seeded", "operator_declared"]
    confidence: Literal["high", "low"]
    status: Literal["proposed", "confirmed"]
    evidence_page_ids: List[str] = Field(default_factory=list)
    last_confirmed_by: Optional[str] = None
    last_confirmed_at: Optional[datetime] = None


# ── List-valued sub-objects ──────────────────────────────────────────
class SpecialInspection(BaseModel):
    id: str
    inspection_type: str  # must be a SPECIAL_INSPECTION_VOCAB member
    provenance: FieldProvenance


class Zone(BaseModel):
    id: str
    floors: List[int] = Field(default_factory=list)
    is_tco_phase: bool = False
    provenance: FieldProvenance


# ── Top-level model ──────────────────────────────────────────────────
class ProjectModel(BaseModel):
    project_id: str

    # Plan-derived scalars (provenance in field_provenance, keyed by name).
    floors: int = 0
    has_gas: bool = False
    has_sprinkler: bool = False
    has_standpipe: bool = False
    has_elevator: bool = False

    special_inspections: List[SpecialInspection] = Field(default_factory=list)
    zones: List[Zone] = Field(default_factory=list)

    # Per-scalar-field provenance for the plan-derived scalars above.
    field_provenance: Dict[str, FieldProvenance] = Field(default_factory=dict)

    # Reserved for the scheduler; this PR never sets it.
    graph_version: Optional[str] = None
    aggregated_at: datetime


# ── Endpoint request bodies ──────────────────────────────────────────
class ScalarConfirm(BaseModel):
    field: Literal["floors", "has_gas", "has_sprinkler", "has_standpipe", "has_elevator"]
    # int for `floors`, bool for the has_* flags; validated in the handler.
    value: Any


class ModelConfirmRequest(BaseModel):
    """Operator confirm step. Any subset may be supplied.

    - scalars: confirm (and optionally override) plan-derived scalars.
    - special_inspection_ids: mark existing proposed special inspections confirmed.
    - special_inspection_types: add operator-declared special inspections
      (validated against SPECIAL_INSPECTION_VOCAB; unknown types rejected).
    - zone_ids: mark existing proposed zones confirmed.
    """

    scalars: List[ScalarConfirm] = Field(default_factory=list)
    special_inspection_ids: List[str] = Field(default_factory=list)
    special_inspection_types: List[str] = Field(default_factory=list)
    zone_ids: List[str] = Field(default_factory=list)
