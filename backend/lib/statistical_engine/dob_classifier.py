"""PR #14B — classify an active project into one of five
``dob_project_type`` enum values.

The classifier walks a three-step chain:

  1. **DOB NOW primary** — query the modern DOB NOW Build Permits
     dataset (``rbx6-tga4``) by BIN. If a row is returned, the
     ``work_type`` + ``job_description`` columns decide the type:
       • ``work_type == "Full Demolition"`` → ``full_demo``
       • NB-family keywords in description → ``new_building``
       • enlargement-family keywords      → ``major_alt_with_enlargement``
       • else default                     → ``minor_alt``  (T4 lock)

  2. **BIS fallback** — when DOB NOW returns no rows, query the
     legacy BIS Job Filings dataset (``ic3t-wcy2``). Map BIS
     ``job_type`` codes via ``cohort_config.COHORT_CONFIG[*].bis_job_types``:
       • ``NB`` → ``new_building``
       • ``A1`` → ``major_alt_with_enlargement``
       • ``A2`` / ``A3`` → ``minor_alt``
       • ``DM`` → ``full_demo``

  3. **Unknown** — both sources empty → ``("unknown", snapshot)``
     with an ``unable_to_classify_reason`` marker for the operator.

The classifier ALWAYS persists three fields onto the project doc
(via ``db.projects.update_one``):

    {
        "dob_project_type":    <enum value>,
        "dob_job_snapshot":    <raw row + source marker>,
        "dob_extracted_scope": <parser output or empty dict>,
    }

Returns ``(project_type, snapshot)`` so the caller (the auto-trigger
hook in ``prewarm.py``) can branch without an extra DB read.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from lib.statistical_engine.cohort_config import COHORT_CONFIG
from lib.statistical_engine.dob_now_parser import parse_dob_now_description
from lib.statistical_engine.socrata_client import DATASET_DOB_PERMITS


logger = logging.getLogger(__name__)


# ── Dataset IDs PR #14B adds ──────────────────────────────────────
#
# These join the canonical constants in ``socrata_client.py``. They
# live here for now to keep the diff minimal; a follow-up PR can
# upstream them next to the other dataset IDs.

DATASET_BIS_JOB_FILINGS = "ic3t-wcy2"
DATASET_C_OF_O_LEGACY   = "bs8b-p36w"


# ── Classification signal keywords ────────────────────────────────

_NEW_BUILDING_KEYWORDS = (
    "NEW BUILDING",
    "NEW CONSTRUCTION",
)

_FULL_DEMOLITION_WORK_TYPES = (
    "FULL DEMOLITION",
)


# ── BIS job_type → dob_project_type map (built from COHORT_CONFIG)
#
# The reverse-index of ``COHORT_CONFIG[*].bis_job_types``. Built
# once at import so the classifier doesn't loop over the cohort
# spec on every call.

def _build_bis_to_project_type_map() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for proj_type, spec in COHORT_CONFIG.items():
        for code in spec.get("bis_job_types", ()):
            out[code] = proj_type
    return out


_BIS_JOB_TYPE_TO_PROJECT_TYPE: Dict[str, str] = _build_bis_to_project_type_map()


# ── Public API ────────────────────────────────────────────────────


async def fetch_project_dob_classification(
    socrata,
    project: Dict[str, Any],
    db,
) -> Tuple[str, Dict[str, Any]]:
    """Classify ``project`` into a ``dob_project_type`` enum value.

    Args:
        socrata: ``SocrataClient`` (or ``MockSocrataClient`` in tests).
        project: Mongo project doc; must carry ``_id`` and
            ``nyc_bin``. Other fields are passed through to the
            persisted snapshot for diagnostics.
        db: Mongo db handle. ``db.projects.update_one`` is called
            exactly once to persist the three dob_* fields.

    Returns:
        Tuple ``(project_type, snapshot)``. ``project_type`` is one
        of the five enum values defined in ``COHORT_CONFIG`` plus
        ``"unknown"``. ``snapshot`` is the dict that was written to
        ``dob_job_snapshot`` — useful for diagnostic logging.

    Never raises on missing rows or transient Socrata failures —
    the unclassified case is itself a valid outcome (``"unknown"``).
    """
    project_id = project.get("_id")
    bin_ = project.get("nyc_bin")

    if not bin_:
        return await _persist_and_return(
            db,
            project_id,
            project_type="unknown",
            snapshot={
                "source": "missing_bin",
                "unable_to_classify_reason": (
                    "project doc has no nyc_bin; cannot query "
                    "DOB NOW / BIS"
                ),
                "classified_at": _now_iso(),
            },
            extracted_scope={},
        )

    # ── Step 1: DOB NOW primary ──────────────────────────────────
    project_type, snapshot, extracted_scope = await _classify_via_dob_now(
        socrata, bin_,
    )
    if project_type is not None:
        return await _persist_and_return(
            db, project_id,
            project_type=project_type,
            snapshot=snapshot,
            extracted_scope=extracted_scope,
        )

    # ── Step 2: BIS fallback ─────────────────────────────────────
    project_type, snapshot = await _classify_via_bis(socrata, bin_)
    if project_type is not None:
        return await _persist_and_return(
            db, project_id,
            project_type=project_type,
            snapshot=snapshot,
            extracted_scope={},
        )

    # ── Step 3: Unknown ──────────────────────────────────────────
    return await _persist_and_return(
        db,
        project_id,
        project_type="unknown",
        snapshot={
            "source": "unclassified",
            "unable_to_classify_reason": (
                f"no rows in DOB NOW (rbx6-tga4) or BIS "
                f"(ic3t-wcy2) for bin={bin_!r}"
            ),
            "classified_at": _now_iso(),
        },
        extracted_scope={},
    )


# ── Step 1: DOB NOW classifier ────────────────────────────────────


async def _classify_via_dob_now(
    socrata,
    bin_: str,
) -> Tuple[Optional[str], Dict[str, Any], Dict[str, Any]]:
    """Try classifying via the DOB NOW primary dataset.

    Returns ``(project_type, snapshot, extracted_scope)`` on hit,
    or ``(None, {}, {})`` when no rows match — signal to the caller
    that the BIS fallback path should run next.
    """
    rows = await socrata.query(
        DATASET_DOB_PERMITS,
        where=f"bin = '{bin_}'",
        limit=50,
    )
    if not rows:
        return (None, {}, {})

    row = rows[0]
    work_type   = (row.get("work_type") or "").strip()
    description = (row.get("job_description") or "")
    desc_upper  = description.upper()

    # Parse the description regardless of which branch fires below —
    # the parser output is always persisted as dob_extracted_scope
    # for the cohort builder to read later.
    parsed = parse_dob_now_description(description, work_type=work_type)

    snapshot = {
        "source":            "dob_now_primary",
        "work_type":         work_type,
        "filing_reason":     row.get("filing_reason"),
        "job_description":   description,
        "job_filing_number": row.get("job_filing_number"),
        "permit_status":     row.get("permit_status"),
        "borough":           row.get("borough"),
        "issued_date":       row.get("issued_date"),
        "classified_at":     _now_iso(),
    }

    # 1a. Full Demolition wins by work_type alone.
    if work_type.upper() in _FULL_DEMOLITION_WORK_TYPES:
        return ("full_demo", snapshot, parsed)

    # 1b. NB keywords explicit in description → new_building.
    if any(kw in desc_upper for kw in _NEW_BUILDING_KEYWORDS):
        return ("new_building", snapshot, parsed)

    # 1c. Enlargement-family keywords (without NB keywords) →
    #     major_alt_with_enlargement.
    if parsed.get("enlargement"):
        return ("major_alt_with_enlargement", snapshot, parsed)

    # 1d. Default: minor_alt (T4 safe-broad-bucket lock).
    return ("minor_alt", snapshot, parsed)


# ── Step 2: BIS classifier ────────────────────────────────────────


async def _classify_via_bis(
    socrata,
    bin_: str,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Try classifying via the BIS legacy Job Filings dataset.

    Returns ``(project_type, snapshot)`` on hit, or ``(None, {})``
    when no rows match.
    """
    rows = await socrata.query(
        DATASET_BIS_JOB_FILINGS,
        where=f"bin__ = '{bin_}'",
        limit=50,
    )
    if not rows:
        return (None, {})

    # Pick the first row whose job_type maps to a known enum. Keep
    # the row regardless so diagnostics show what the classifier saw.
    chosen = rows[0]
    for r in rows:
        if (r.get("job_type") or "").upper() in _BIS_JOB_TYPE_TO_PROJECT_TYPE:
            chosen = r
            break

    job_type = (chosen.get("job_type") or "").upper()
    project_type = _BIS_JOB_TYPE_TO_PROJECT_TYPE.get(job_type)

    snapshot = {
        "source":             "bis_fallback",
        "bin":                chosen.get("bin__"),
        "job_number":         chosen.get("job__"),
        "job_type":           job_type,
        "building_class":     chosen.get("building_class"),
        "borough":            chosen.get("borough"),
        "job_status":         chosen.get("job_status"),
        "job_status_descrp":  chosen.get("job_status_descrp"),
        "pre__filing_date":   chosen.get("pre__filing_date"),
        "fully_permitted":    chosen.get("fully_permitted"),
        "latest_action_date": chosen.get("latest_action_date"),
        "classified_at":      _now_iso(),
    }

    if project_type is None:
        # BIS row exists but job_type doesn't map to a known enum.
        # Surface as unknown but keep the snapshot for diagnostics.
        snapshot["unable_to_classify_reason"] = (
            f"BIS job_type {job_type!r} not in cohort config"
        )
        return ("unknown", snapshot)

    return (project_type, snapshot)


# ── Persistence ───────────────────────────────────────────────────


async def _persist_and_return(
    db,
    project_id: Any,
    *,
    project_type: str,
    snapshot: Dict[str, Any],
    extracted_scope: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """Write the three dob_* fields onto the project doc and
    return ``(project_type, snapshot)``.
    """
    try:
        await db.projects.update_one(
            {"_id": project_id},
            {
                "$set": {
                    "dob_project_type":    project_type,
                    "dob_job_snapshot":    snapshot,
                    "dob_extracted_scope": extracted_scope,
                }
            },
        )
    except Exception:  # pragma: no cover — guard against transient DB
        logger.exception(
            "fetch_project_dob_classification: persist failed for "
            "project_id=%r", project_id,
        )
    return (project_type, snapshot)


# ── Helpers ───────────────────────────────────────────────────────


def _now_iso() -> str:
    """Return the current UTC instant as an ISO-8601 string. Helper
    isolates the timestamp source so tests can monkey-patch if needed.
    """
    return datetime.now(timezone.utc).isoformat()
