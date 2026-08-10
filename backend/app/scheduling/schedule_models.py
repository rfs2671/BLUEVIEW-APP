"""Typed models for the deterministic scheduling spine.

Holds ONLY types. No DB, no LLM, no HTTP, no engine logic. The engine
(engine.py) consumes a ProjectModel (project_model.py) + a SequenceGraph
(graph_v1.py) and produces a Schedule.

Edge types (see engine.py for how each is used):
  - hard_fts            : finish-to-start; gates a phase boundary (blocking).
  - soft_parallel_open  : advisory sibling ordering; does NOT gate a phase.
  - vertical_structural : bottom-up structural dependency between floors; hard.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field


# ── Nodes ────────────────────────────────────────────────────────────
class WorkPackage(BaseModel):
    kind: Literal["work"] = "work"  # discriminator
    id: str
    trade: str
    scope: str
    per_floor: bool = False
    is_structural: bool = False
    zone_scoped: bool = False
    # System flags gating existence, e.g. ["has_sprinkler"]. Node is pruned when
    # any flag is unmet by the ProjectModel.
    requires: List[str] = Field(default_factory=list)


class InspectionGate(BaseModel):
    kind: Literal["gate"] = "gate"  # discriminator
    id: str
    inspection_type: str
    is_special_inspection: bool = False
    zone_scoped: bool = False
    is_global: bool = False
    requires: List[str] = Field(default_factory=list)


# Discriminated union so a persisted SequenceGraph round-trips node types.
SchedNode = Annotated[Union[WorkPackage, InspectionGate], Field(discriminator="kind")]


# ── Edges + graph ────────────────────────────────────────────────────
class GraphEdge(BaseModel):
    from_node: str
    to_node: str
    edge_type: Literal["hard_fts", "soft_parallel_open", "vertical_structural"]


class SequenceGraph(BaseModel):
    version: str
    nodes: List[SchedNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)


# ── Output ───────────────────────────────────────────────────────────
class Phase(BaseModel):
    phase_index: int
    parallel_work: List[str] = Field(default_factory=list)
    required_gates: List[str] = Field(default_factory=list)
    opens_next: List[str] = Field(default_factory=list)


class Schedule(BaseModel):
    project_id: str
    graph_version: str
    phases: List[Phase] = Field(default_factory=list)
    pruned_nodes: List[str] = Field(default_factory=list)
    healed_edges: List[GraphEdge] = Field(default_factory=list)
    generated_at: datetime


# ── Activity-chip ranking output ─────────────────────────────────────
# Produced by sequence_ranking.rank_activities from the sequence_rules_v1
# graph. Ranking ORDERS chips; it never pre-selects, never blocks an entry,
# and never writes to a record.
CHIP_BANDS = ("suggested", "remembered_other", "always_available", "catalog", "other")


class ActivityChip(BaseModel):
    id: str
    label: str
    rank: int  # 0-based position in the emitted chip list
    band: Literal["suggested", "remembered_other", "always_available",
                  "catalog", "other"]
    # NEVER pre-selected. Literal[False] makes a pre-selected chip
    # unconstructible — a caller that tries selected=True gets a
    # ValidationError, so "rank order only" cannot be violated by accident.
    selected: Literal[False] = False
    # The WorkPackage's own `trade`, carried through so the client has a
    # grouping signal. The chip list previously exposed none at all, which left
    # the Daily Jobsite Log unable to summarise a day's work as anything but a
    # list of individual activities.
    #
    # DELIBERATELY `trade` AND NOT A PHASE. A semantic phase ("foundation" vs
    # "superstructure") is domain judgment over 86 nodes, and this graph's own
    # header says RULE CONTENTS PENDING NYC DOB DOMAIN-EXPERT SIGN-OFF — so
    # nobody here gets to decide it. `trade` is already on every node, was set
    # by whoever authored the approved rules, and is therefore reportable
    # without inventing anything.
    #
    # None ONLY for a chip with no node behind it — a remembered free-text
    # "other:<label>" entry. There is no rule row to read a trade from, and an
    # empty string would imply one was looked up and found blank.
    #
    # Note that the "other" escape hatch IS a real node (sequence_rules_v1
    # declares it with trade "gc"), so it reports "gc" like any other. That is
    # accurate about the graph but meaningless as a summary of the day, because
    # the chip stands for whatever the CP typed — so a caller deriving prose
    # from trades must exclude it. It is excluded in
    # frontend/src/utils/dailyJobsiteModel.js (deriveGeneralDescription).
    trade: Optional[str] = None


class ActivityRanking(BaseModel):
    project_id: str
    rules_version: str
    structural_system: Literal["cast_in_place", "cfs", "unknown"]
    # False when the project has no structural system set — the caller needs
    # this to say so in the UI. When False, BOTH superstructure loops are
    # present in `chips`.
    structural_system_set: bool
    chips: List[ActivityChip] = Field(default_factory=list)
    # Prior-day activity ids with no matching rule node. Reported, never raised
    # and never blocking: an unrecognized prior degrades to the cold-start set.
    unrecognized_prior_ids: List[str] = Field(default_factory=list)
