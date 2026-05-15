"""Shared fixture helpers for PR #14B cohort-aware peer comparison.

Used by:
  • tests/test_pr14b_cohort.py
  • tests/test_v2_3_baselines.py (TestComputeCohortForProject,
    TestLifecycleNormalization, TestPlutoSelectExtensionPR14B)
  • tests/test_v2_3_prewarm.py (TestAutoClassificationTrigger)

Filename prefix ``_`` so pytest's default collector skips it.

These helpers wrap ``MockSocrataClient.seed(...)`` with the row
shapes PR #14B's production code expects from each dataset. Tests
stay intent-focused — they declare project type + cohort criteria,
not raw SoQL row dicts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ── Dataset IDs PR #14B touches ───────────────────────────────────
# These are NOT yet re-exported from lib.statistical_engine.socrata_client
# (Stage 3 will add them). Until then the fixture pins the IDs literally
# so tests don't depend on Stage 3 having landed first.

DATASET_BIS_JOB_FILINGS = "ic3t-wcy2"
DATASET_C_OF_O_LEGACY   = "bs8b-p36w"
DATASET_DOB_PERMITS     = "rbx6-tga4"  # DOB NOW; also exists in socrata_client


# ── Per-dataset seeders ───────────────────────────────────────────


def seed_dob_now_for_bin(
    socrata,
    *,
    bin: str,
    work_type: str = "General Construction",
    filing_reason: str = "Initial Permit",
    job_description: str = "",
    job_filing_number: Optional[str] = None,
    permit_status: str = "Issued",
    borough: str = "BROOKLYN",
    issued_date: Optional[str] = "2024-01-15",
) -> Dict[str, Any]:
    """Seed one DOB NOW row keyed to ``bin``.

    Default values match an Initial Permit for a General Construction
    project — i.e., what the classifier reads to decide
    ``new_building`` vs ``major_alt_with_enlargement`` vs ``minor_alt``.

    Returns the seeded row dict so tests can mutate it or stash a
    reference.
    """
    row = {
        "bin":               bin,
        "job_filing_number": job_filing_number or f"M{bin[-7:]}",
        "work_type":         work_type,
        "filing_reason":     filing_reason,
        "job_description":   job_description,
        "permit_status":     permit_status,
        "borough":           borough,
        "issued_date":       issued_date,
    }
    socrata.seed(DATASET_DOB_PERMITS, [row])
    return row


def seed_bis_for_bin(
    socrata,
    *,
    bin: str,
    job_number: str,
    job_type: str = "NB",
    building_class: str = "C1",
    borough: str = "BROOKLYN",
    proposed_dwelling_units: Optional[int] = None,
    total_construction_floor_area: Optional[int] = None,
    pre__filing_date: Optional[str] = "2018-03-20",
    job_status: str = "X",
    job_status_descrp: str = "SIGNED OFF",
    fully_permitted: Optional[str] = "2020-11-04",
    latest_action_date: Optional[str] = "2022-03-31",
) -> Dict[str, Any]:
    """Seed one BIS Job Filing row.

    BIS uses ``bin__`` (double underscore) and ``job__`` for its
    identifier columns; mirror that on the seeded row so the
    production code's SoQL matches.
    """
    row = {
        "bin__":          bin,
        "job__":          job_number,
        "job_type":       job_type,
        "building_class": building_class,
        "borough":        borough,
        "job_status":     job_status,
        "job_status_descrp": job_status_descrp,
        "pre__filing_date": pre__filing_date,
        "fully_permitted":  fully_permitted,
        "latest_action_date": latest_action_date,
    }
    if proposed_dwelling_units is not None:
        row["proposed_dwelling_units"] = str(proposed_dwelling_units)
    if total_construction_floor_area is not None:
        row["total_construction_floor_area"] = str(
            total_construction_floor_area
        )
    socrata.seed(DATASET_BIS_JOB_FILINGS, [row])
    return row


def seed_c_of_o_for_job(
    socrata,
    *,
    job_number: str,
    bin_number: str,
    issue_type: str = "Final",
    c_o_issue_date: str = "2022-01-15",
    job_type: str = "NB",
    borough: str = "Brooklyn",
) -> Dict[str, Any]:
    """Seed one legacy C of O row.

    ``issue_type`` defaults to "Final" — the cohort completion
    filter PR #14B uses. Tests verifying the Temporary→Final
    progression seed multiple rows by calling this helper with
    ``issue_type="Temporary"`` first.
    """
    row = {
        "job_number":     job_number,
        "bin_number":     bin_number,
        "issue_type":     issue_type,
        "c_o_issue_date": c_o_issue_date,
        "job_type":       job_type,
        "borough":        borough,
    }
    socrata.seed(DATASET_C_OF_O_LEGACY, [row])
    return row


def make_cohort_fixture(
    socrata,
    *,
    project_type: str,
    n_records: int,
    bin_prefix: str = "100200",
    job_number_prefix: str = "32100",
    borough: str = "BROOKLYN",
    borough_lower: str = "Brooklyn",
    building_class: str = "C1",
    bis_job_type: str = "NB",
    story_count: int = 5,
    dwelling_units: int = 8,
    completed: bool = True,
    c_o_issue_type: str = "Final",
    c_o_issue_date: str = "2024-01-15",
    pre__filing_date: str = "2022-06-01",
) -> List[Dict[str, Any]]:
    """Bulk-seed N BIS Job Filings (+ optional C of O rows) matching
    a cohort filter spec. Convenience for cohort sample-size tests
    where dozens of records need consistent attributes.

    Returns the list of seeded BIS row dicts so tests can iterate
    + inspect.

    BIN values are generated as ``{bin_prefix}{i:04d}``; job numbers
    as ``{job_number_prefix}{i:04d}``. The (BIN, job_number) pair is
    used to seed the optional C of O row.
    """
    rows: List[Dict[str, Any]] = []
    for i in range(n_records):
        bin_ = f"{bin_prefix}{i:04d}"
        job_number = f"{job_number_prefix}{i:04d}"
        row = seed_bis_for_bin(
            socrata,
            bin=bin_,
            job_number=job_number,
            job_type=bis_job_type,
            building_class=building_class,
            borough=borough,
            proposed_dwelling_units=dwelling_units,
            total_construction_floor_area=story_count * 1000,
            pre__filing_date=pre__filing_date,
        )
        rows.append(row)
        if completed:
            seed_c_of_o_for_job(
                socrata,
                job_number=job_number,
                bin_number=bin_,
                issue_type=c_o_issue_type,
                c_o_issue_date=c_o_issue_date,
                job_type=bis_job_type,
                borough=borough_lower,
            )
    return rows
