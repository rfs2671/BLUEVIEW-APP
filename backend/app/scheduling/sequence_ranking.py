"""Activity-chip ranking from the sequence_rules_v1 graph.

Pure and total: no DB, no HTTP, no LLM, no I/O. `rank_activities` is the only
entry point and it NEVER raises for bad input — an unrecognized prior activity,
an unknown structural system, a None, a non-string, an empty list all degrade
to a well-formed ranking. That is deliberate: the rules must never be able to
stop a CP from logging a day of work.

The four behavioural guarantees, and where each is enforced:

  1. RANK ORDER ONLY, NEVER PRE-SELECT.
     ActivityChip.selected is Literal[False] (schedule_models.py), so a
     pre-selected chip cannot be constructed. This module never passes the
     field at all.

  2. "OTHER" IS ALWAYS LAST, NEVER BURIED.
     Every band strips OTHER_ACTIVITY_ID (_strip_other), and the chip is
     appended once, unconditionally, after all bands.

  3. RULES NEVER BLOCK.
     Nothing here returns a "disabled" or "hidden" flag, and no caller is told
     an activity is unavailable. Chips are ordered; free text via "Other" is
     always reachable. All rule edges are soft_parallel_open, which the engine
     defines as non-gating (schedule_models.py:9, engine.py:254-258).

  4. CONCURRENT WORK STAYS OFFERED, MULTIPLE ACTIVITIES PER DAY.
     Every recognized prior activity is itself re-emitted in the suggested
     band alongside its successors, so logging framing on Monday leaves both
     framing and MEP rough-in offered on Tuesday, and any number of priors may
     be passed in at once.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

from app.scheduling.schedule_models import ActivityChip, ActivityRanking, SequenceGraph
from app.scheduling.sequence_rules_v1 import (
    ALWAYS_AVAILABLE_IDS,
    ALWAYS_AVAILABLE_ORDER,
    BRANCH_ENTRY_CAST_IN_PLACE,
    BRANCH_ENTRY_CFS,
    COLD_START_IDS,
    FLAG_CAST_IN_PLACE,
    FLAG_CFS,
    OTHER_ACTIVITY_ID,
    OTHER_ENTRY_PREFIX,
    SYSTEM_CAST_IN_PLACE,
    SYSTEM_CFS,
    SYSTEM_UNKNOWN,
    build_sequence_rules_v1,
    successors_by_id,
)

__all__ = [
    "resolve_structural_system",
    "rank_activities",
    "other_entry_chip_id",
    "BRANCH_ENTRY_CAST_IN_PLACE",
    "BRANCH_ENTRY_CFS",
]


def resolve_structural_system(value) -> str:
    """Normalize any input to one of the three system values.

    Anything that is not exactly "cast_in_place" or "cfs" — None, "", a typo,
    a non-string — resolves to "unknown", which offers BOTH loops. There is no
    error path: an unset system is a normal state, not a fault.
    """
    if isinstance(value, str):
        v = value.strip().lower()
        if v in (SYSTEM_CAST_IN_PLACE, SYSTEM_CFS):
            return v
    return SYSTEM_UNKNOWN


def _branch_allowed(node, system: str) -> bool:
    """A node is offered unless it belongs to the loop the project is NOT
    running. Under "unknown" every branch node is offered (both loops)."""
    req = set(getattr(node, "requires", ()) or ())
    if system == SYSTEM_CAST_IN_PLACE and FLAG_CFS in req:
        return False
    if system == SYSTEM_CFS and FLAG_CAST_IN_PLACE in req:
        return False
    return True


def other_entry_chip_id(label: str) -> str:
    """Stable chip id for a remembered free-text "Other" entry."""
    return f"{OTHER_ENTRY_PREFIX}{label.strip()}"


def _clean_ids(values) -> List[str]:
    """Tolerant coercion — drops anything that is not a non-empty string."""
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    out: List[str] = []
    for v in values:
        if isinstance(v, str) and v.strip():
            s = v.strip()
            if s not in out:
                out.append(s)
    return out


def _strip_other(ids: Iterable[str]) -> List[str]:
    """Guarantee #2: no band may contain the "Other" chip."""
    return [i for i in ids if i != OTHER_ACTIVITY_ID]


def rank_activities(
    *,
    project_id: str,
    prior_activity_ids: Optional[Sequence[str]] = None,
    structural_system=None,
    remembered_other_labels: Optional[Sequence[str]] = None,
    graph: Optional[SequenceGraph] = None,
) -> ActivityRanking:
    """Order the activity chips for one project-day.

    prior_activity_ids
        What the project did on the prior day, OR the current state the CP set
        once at setup for an existing project. Empty / all-unrecognized falls
        back to the cold-start set (project start, no history).
    structural_system
        "cast_in_place" | "cfs" | anything else -> "unknown" (both loops).
    remembered_other_labels
        Free-text "Other" entries previously recorded for THIS project. They
        come back as their own chips. This function does not read or write that
        store; the caller supplies the labels.
    """
    g = graph if graph is not None else build_sequence_rules_v1()
    raw_system = structural_system
    system = resolve_structural_system(raw_system)
    system_set = system != SYSTEM_UNKNOWN

    nodes = [n for n in g.nodes if _branch_allowed(n, system)]
    order: Dict[str, int] = {n.id: i for i, n in enumerate(nodes)}
    label_of: Dict[str, str] = {n.id: getattr(n, "scope", n.id) for n in nodes}
    # The node's own trade, carried onto the chip. An InspectionGate has no
    # `trade` attribute at all, so getattr defaults to None rather than
    # inventing one — a gate is not a trade's work.
    trade_of: Dict[str, object] = {n.id: getattr(n, "trade", None) for n in nodes}
    allowed = set(order)
    succ = successors_by_id(g)

    priors = _clean_ids(prior_activity_ids)
    known_priors = [p for p in priors if p in allowed]
    unrecognized = sorted(p for p in priors if p not in allowed)

    # ── band 1: suggested ────────────────────────────────────────────
    suggested: set = set()
    if known_priors:
        # The priors themselves stay offered (concurrent / multi-day work)...
        suggested.update(known_priors)
        # ...plus everything the rules open from them.
        for p in known_priors:
            suggested.update(s for s in succ.get(p, ()) if s in allowed)
    else:
        # Cold start, or every prior was a rule miss: neither raises, both
        # simply fall back to the project-start set.
        suggested.update(c for c in COLD_START_IDS if c in allowed)
    # Always-available chips keep their own pinned band so their position never
    # moves day to day; "Other" is appended last by hand.
    suggested -= ALWAYS_AVAILABLE_IDS
    suggested_ids = _strip_other(sorted(suggested, key=lambda i: (order[i], i)))

    # ── band 2: remembered "Other" entries for this project ──────────
    seen_labels: Dict[str, str] = {}
    for lab in _clean_ids(remembered_other_labels):
        seen_labels.setdefault(lab.casefold(), lab)
    remembered = [seen_labels[k] for k in sorted(seen_labels)]

    # ── band 3: always available — never sequence-gated ──────────────
    always_ids = _strip_other([a for a in ALWAYS_AVAILABLE_ORDER if a in allowed])

    # ── band 4: the rest of the catalogue ────────────────────────────
    placed = set(suggested_ids) | set(always_ids) | {OTHER_ACTIVITY_ID}
    catalog_ids = _strip_other(
        sorted((i for i in allowed if i not in placed), key=lambda i: (order[i], i))
    )

    chips: List[ActivityChip] = []

    def _emit(chip_id: str, label: str, band: str) -> None:
        # trade is looked up, never defaulted to a string: a chip with no node
        # behind it ("Other", a remembered free-text entry) gets None, which
        # says "there is no rule row to read a trade from" rather than implying
        # one was found and was blank.
        chips.append(ActivityChip(id=chip_id, label=label, rank=len(chips),
                                  band=band, trade=trade_of.get(chip_id)))

    for i in suggested_ids:
        _emit(i, label_of[i], "suggested")
    for lab in remembered:
        _emit(other_entry_chip_id(lab), lab, "remembered_other")
    for i in always_ids:
        _emit(i, label_of[i], "always_available")
    for i in catalog_ids:
        _emit(i, label_of[i], "catalog")

    # Guarantee #2, enforced structurally: every band above was stripped of the
    # "Other" id, and it is appended exactly once, here, at the end.
    # Lowercase fallback label: chip labels are lowercase house style
    # (sequence_rules_v1 module docstring), so the defensive default matches
    # the node's own scope rather than reintroducing a capitalized label.
    _emit(OTHER_ACTIVITY_ID, label_of.get(OTHER_ACTIVITY_ID, "other"), "other")

    return ActivityRanking(
        project_id=project_id,
        rules_version=g.version,
        structural_system=system,
        structural_system_set=system_set,
        chips=chips,
        unrecognized_prior_ids=unrecognized,
    )
