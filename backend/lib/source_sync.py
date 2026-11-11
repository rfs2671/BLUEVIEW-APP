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
    "dot_embargo": DOT_PERMITS,
    "dot_hearing": DOT_OATH, "dot_hearing_pending": DOT_OATH, "dot_default": DOT_OATH,
    "order": DOB_VIOLATIONS, "order_lifted": DOB_VIOLATIONS, "bin_added": DOB_VIOLATIONS,
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


# ── PER DATASET (2026-11-10, 546 Saratoga) ────────────────────────────────
# A source used to count as synced only when EVERY request for its record
# types answered. The violations source is four datasets; one of them
# (3usq-5cid, the dead COVID stop-work set) 400'd on every pass, so the source
# never first-synced and every violation, stop-work and order alert for the
# project waited forever behind one obsolete dataset. Now each dataset carries
# its own state, a source opens when ANY of its datasets has answered, and a
# row is judged against the first sync of the DATASET that produced it -- so a
# dataset that fails blocks only itself, and one that recovers later cannot
# post its history as new.
DATASET_SOURCE = {
    "855j-jady": DOB_VIOLATIONS, "3h2n-5cm9": DOB_VIOLATIONS, "6bgk-3dad": DOB_VIOLATIONS,
    "3usq-5cid": DOB_VIOLATIONS, "bis-ecb": DOB_VIOLATIONS,
    "eabe-havv": DOB_COMPLAINTS, "bis": DOB_COMPLAINTS,
    "rbx6-tga4": DOB_PERMITS, "dm9a-ab7w": DOB_PERMITS, "ipu4-2q9a": DOB_PERMITS,
    "w9ak-ipjd": DOB_JOB_FILINGS, "pkdm-hqz6": DOB_COFO, "xubg-57si": DOB_FACADE,
    "52dp-yji6": DOB_BOILER, "e5aq-a4j2": DOB_ELEVATOR,
}
DATASET_KEY = "ds:"


def answered_datasets(answered: Mapping[str, bool]) -> Dict[str, bool]:
    """{dataset_id: every request to it answered} from a pass's `answered`."""
    return {k[len(DATASET_KEY):]: bool(v) for k, v in answered.items() if k.startswith(DATASET_KEY)}


def answered_sources_by_dataset(answered: Mapping[str, bool],
                                failed_types: Iterable[str] = ()) -> Set[str]:
    """Sources with at least one dataset that answered in full this pass (and
    no record of the source that failed to store). One dead dataset no longer
    closes its whole source; answered_sources keeps the old all-or-nothing
    rule for callers that track no datasets (DOT)."""
    failed = {RECORD_SOURCE.get(t) for t in failed_types}
    out = {DATASET_SOURCE[d] for d, ok in answered_datasets(answered).items()
           if ok and d in DATASET_SOURCE}
    return (out | answered_sources(answered, failed_types)) - failed


def dataset_first_synced(state: Optional[Mapping[str, Any]]) -> Dict[str, datetime]:
    """{dataset_id: first_synced_at} from a source_sync_state row."""
    out: Dict[str, datetime] = {}
    for d, row in ((state or {}).get("datasets") or {}).items():
        at = as_utc((row or {}).get("first_synced_at"))
        if at is not None:
            out[d] = at
    return out


def dataset_failing(state: Optional[Mapping[str, Any]]) -> Set[str]:
    """Datasets that have failed and never once answered in full."""
    return {d for d, row in ((state or {}).get("datasets") or {}).items()
            if (row or {}).get("last_error_at") and not (row or {}).get("first_synced_at")}


def dataset_gate(rec: Mapping[str, Any], ds_first: Mapping[str, datetime],
                 failing: Iterable[str] = ()) -> str:
    """'post', 'wait' or 'baseline' for a stored row, by the dataset it came from.

    'wait'      its dataset has failed and never answered in full.
    'baseline'  it was stored by its dataset's first sync: history, not news.
    'post'      stored after that first sync, or a dataset with no per-dataset
                record yet (the source-level gates decide, as before)."""
    d = str(rec.get("dataset") or "")
    if d not in DATASET_SOURCE or DATASET_SOURCE[d] != DOB_VIOLATIONS:
        return "post"
    if d in set(failing):
        return "wait"
    first = ds_first.get(d)
    if first is None:
        return "post"
    det = as_utc(rec.get("detected_at"))
    return "baseline" if det is not None and det <= first else "post"


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
