"""Per-project, per-source "first sync done" — the gate for anything that
says "new".

A project's records arrive from a source (a DOB or DOT dataset family) on
that source's first sync. Until then the project has nothing of that kind,
so a GC baseline taken then records nothing, and the first sync's rows —
the project's whole history — would post as new. Every consumer that says
"new" (GC group alerts, the morning brief) therefore:

  * ignores a source until the project's first sync of it is done, and
  * treats nothing stored by that first sync as new.

State: one `source_sync_state` row per project,
  {_id: project_id, company_id, sources: {<source>: {first_synced_at,
   synced_at}}}
written by the DOB and DOT syncs after a pass in which every request for
that source answered and every record was stored. first_synced_at is set
once and kept.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Set

DOB_VIOLATIONS = "dob_violations"
DOB_COMPLAINTS = "dob_complaints"
DOB_PERMITS = "dob_permits"
DOB_JOB_FILINGS = "dob_job_filings"
DOB_COFO = "dob_cofo"
DOB_FACADE = "dob_facade"
DOB_BOILER = "dob_boiler"
DOB_ELEVATOR = "dob_elevator"
DOT_OATH = "dot_oath"
DOT_PERMITS = "dot_permits"
DOB_SOURCES = (DOB_VIOLATIONS, DOB_COMPLAINTS, DOB_PERMITS, DOB_JOB_FILINGS,
               DOB_COFO, DOB_FACADE, DOB_BOILER, DOB_ELEVATOR)
SOURCES = DOB_SOURCES + (DOT_OATH, DOT_PERMITS)

# Stored record_type → its source. A stop-work order comes from the DOB
# violation datasets and the SWO dataset; both count as dob_violations.
RECORD_SOURCE = {
    "violation": DOB_VIOLATIONS, "swo": DOB_VIOLATIONS,
    "complaint": DOB_COMPLAINTS,
    "permit": DOB_PERMITS,
    "job_status": DOB_JOB_FILINGS,
    "cofo": DOB_COFO,
    "facade_fisp": DOB_FACADE,
    "boiler": DOB_BOILER,
    "elevator": DOB_ELEVATOR,
    "dot_violation": DOT_OATH,
    "dot_permit": DOT_PERMITS,
}

# GC alert kind (lib/wa_alerts.KIND_SWITCH) → its source.
KIND_SOURCE = {
    "violation": DOB_VIOLATIONS, "violation_status": DOB_VIOLATIONS,
    "swo": DOB_VIOLATIONS, "swo_rescinded": DOB_VIOLATIONS,
    "complaint": DOB_COMPLAINTS,
    "permit": DOB_PERMITS, "permit_status": DOB_PERMITS,
    "dot_violation": DOT_OATH,
    "dot_permit": DOT_PERMITS,
}

# Projects first polled before per-source tracking shipped have no state
# rows yet; their DOB history was baselined long ago. For them the
# project's first_poll_completed_at stands in for the DOB sources' first
# sync. A project first polled after this moment needs its own rows.
LEGACY_FIRST_POLL_BEFORE = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)


def as_utc(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, datetime):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def first_synced(state: Optional[Mapping[str, Any]],
                 project: Optional[Mapping[str, Any]] = None
                 ) -> Dict[str, datetime]:
    """{source: first_synced_at} for every source whose first sync is done."""
    out: Dict[str, datetime] = {}
    sources = (state or {}).get("sources") or {}
    for s in SOURCES:
        at = as_utc((sources.get(s) or {}).get("first_synced_at"))
        if at is not None:
            out[s] = at
    legacy = as_utc((project or {}).get("first_poll_completed_at"))
    if legacy is not None and legacy < LEGACY_FIRST_POLL_BEFORE:
        # The earlier wins: once the DOB sync writes this project's rows
        # (stamped at deploy), its markers must not all look stale.
        for s in DOB_SOURCES:
            out[s] = min(out.get(s, legacy), legacy)
    return out


def answered_sources(answered: Mapping[str, bool],
                     failed_types: Iterable[str] = ()) -> Set[str]:
    """Sources fully synced in one DOB/DOT pass.

    `answered` is {record_type: every request for it answered}, holding only
    record types that had at least one request. A source counts when it had
    a request, every one of its record types answered, and no record of it
    failed to store."""
    failed = {RECORD_SOURCE.get(t) for t in failed_types}
    by_source: Dict[str, bool] = {}
    for rt, ok in answered.items():
        s = RECORD_SOURCE.get(rt)
        if s:
            by_source[s] = by_source.get(s, True) and bool(ok)
    return {s for s, ok in by_source.items() if ok and s not in failed}
