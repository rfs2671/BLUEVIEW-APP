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

import contextlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple
from unittest.mock import patch


# ── Dataset IDs PR #14B touches ───────────────────────────────────
# These are NOT yet re-exported from lib.statistical_engine.socrata_client
# (Stage 3 will add them). Until then the fixture pins the IDs literally
# so tests don't depend on Stage 3 having landed first.

DATASET_BIS_JOB_FILINGS = "ic3t-wcy2"
DATASET_C_OF_O_LEGACY   = "bs8b-p36w"
DATASET_DOB_PERMITS     = "rbx6-tga4"  # DOB NOW; also exists in socrata_client
DATASET_PLUTO           = "64uk-42ks"  # PLUTO; mirrors socrata_client

# PR #15A — Predictive Inference Engine source datasets.
# 6bgk-3dad ECB Violations: target dataset for outcome_violation_d.
#   ``issue_date`` is YYYYMMDD numeric (8-digit text), parsed via
#   existing ``_parse_socrata_yyyymmdd`` helper. Severity enum:
#   {CLASS - 1, CLASS - 2, Hazardous, CLASS - 3, Non-Hazardous,
#   Unknown}. Locked severity filter: IN ('CLASS - 1', 'CLASS - 2',
#   'Hazardous') — 3 included, 3 excluded.
# eabe-havv DOB Complaints: source for SWO state machine AND
#   complaint_velocity_14d BIN-keyed source. ``date_entered`` and
#   ``disposition_date`` are MM/DD/YYYY text, parsed via existing
#   ``_parse_bis_mdy_date``. SWO disposition codes: A8 (close work
#   = issue SWO), A1 (issue work-stop), A9 (vacate / clear),
#   B1 (rescind). Last-disposition-wins state machine.
DATASET_DOB_ECB_VIOLATIONS = "6bgk-3dad"
DATASET_DOB_COMPLAINTS     = "eabe-havv"
DATASET_311                = "erm2-nwe9"  # same as DATASET_COMPLAINTS_311 in socrata_client

# PR #14E (Q2 lock) — DOB NOW C of O dataset, the Modern cohort
# source. Carries job_type + c_of_o_filing_type + bbl + bin inline.
# Field format note: c_of_o_issuance_date is "MM/DD/YY HH:MM:SS AM/PM"
# (per Stage 1 Task 1 schema discovery), NOT ISO — production code
# uses _parse_pkdm_date helper to read.
DATASET_DOB_C_OF_O      = "pkdm-hqz6"


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
    approved_date: Optional[str] = "2024-01-10T00:00:00.000",
) -> Dict[str, Any]:
    """Seed one DOB NOW row keyed to ``bin``.

    Default values match an Initial Permit for a General Construction
    project — i.e., what the classifier reads to decide
    ``new_building`` vs ``major_alt_with_enlargement`` vs ``minor_alt``.

    PR #14D fixture defaults (§8.4 lock):
      • ``job_filing_number`` defaults to ``B{bin[-7:]}-I1`` (was
        ``M{bin[-7:]}``) so the row matches PR #14D's classifier
        ``LIKE '%-I1'`` filter.
      • ``work_type`` stays ``General Construction`` — already
        scope-carrying per Q4 lock.
      • NEW ``approved_date`` default required for PR #14D's
        ``ORDER BY approved_date ASC`` in the classifier query.

    Returns the seeded row dict so tests can mutate it or stash a
    reference.
    """
    row = {
        "bin":               bin,
        "job_filing_number": job_filing_number or f"B{bin[-7:]}-I1",
        "work_type":         work_type,
        "filing_reason":     filing_reason,
        "job_description":   job_description,
        "permit_status":     permit_status,
        "borough":           borough,
        "issued_date":       issued_date,
        "approved_date":     approved_date,
    }
    socrata.seed(DATASET_DOB_PERMITS, [row])
    return row


def seed_menahan_realistic_dob_now(socrata) -> Dict[str, Any]:
    """PR #14D — seed the 5 actual DOB NOW rows from Menahan
    BIN 3325703 (verbatim from operator's curl probe of rbx6-tga4
    during Stage 1 investigation).

    Per T3 lock: this fixture is the canonical "real data, real
    classification" canary. Two tests use it:
      • ``test_pr14b_cohort.py::test_menahan_real_data_classifies_as_major_alt_with_enlargement``
        — pins the classifier picks B00736930-I1 General Construction
        and returns ``major_alt_with_enlargement``.
      • ``test_pr14c_wiring.py::test_menahan_real_data_full_pipeline_classifies_correctly``
        — pins the full pipeline (classifier + cohort + cache).

    Rows seeded:
      1. B00834550-I1 / Construction Fence / approved 2023-04-04
         — auxiliary; filtered by scope-carrying preference
      2. B00736930-I1 / General Construction / approved 2022-10-07
         — THE scope-carrying row (VERTICAL AND HORIZONTAL
         ENLARGEMENT → classifier picks major_alt_with_enlargement)
      3. B00736930-S4 / Foundation / approved 2024-03-15
         — Renewal; filtered by -I1 suffix filter
      4. B00736930-S5 / Support of Excavation / approved 2024-04-01
         — Renewal; filtered by -I1 suffix filter
      5. B01252711-I1 / Sidewalk Shed / approved 2025-07-15
         — auxiliary; filtered by scope-carrying preference

    Returns metadata dict for test assertions.
    """
    rows = [
        # 1 — Auxiliary (would be filtered by scope preference).
        {
            "bin":               "3325703",
            "job_filing_number": "B00834550-I1",
            "work_type":         "Construction Fence",
            "filing_reason":     "Initial Permit",
            "job_description": (
                "HEREBY FILING FENCE APPLICATION IN CONJUNCTION TO "
                "JOB #B00736930-I1"
            ),
            "permit_status":     "Issued",
            "borough":           "BROOKLYN",
            "issued_date":       "2023-04-04",
            "approved_date":     "2023-04-04T00:00:00.000",
        },
        # 2 — THE scope-carrying row.
        {
            "bin":               "3325703",
            "job_filing_number": "B00736930-I1",
            "work_type":         "General Construction",
            "filing_reason":     "Initial Permit",
            "job_description": (
                "PROPOSED ALTERATION TYPE 1 TO EXISTING 2 STORY + "
                "CELLAR BUILDING. VERTICAL AND HORIZONTAL "
                "ENLARGEMENT. PROPOSED 4-STORY+CELLAR+MEZZ "
                "RESIDENTIAL USE BUILDING."
            ),
            "permit_status":     "Issued",
            "borough":           "BROOKLYN",
            "issued_date":       "2022-10-07",
            "approved_date":     "2022-10-07T00:00:00.000",
        },
        # 3 — Renewal (filtered by -I1 suffix).
        {
            "bin":               "3325703",
            "job_filing_number": "B00736930-S4",
            "work_type":         "Foundation",
            "filing_reason":     "Renewal Permit Without Changes",
            "job_description":   "FOUNDATION WORK PER PLANS.",
            "permit_status":     "Issued",
            "borough":           "BROOKLYN",
            "issued_date":       "2024-03-15",
            "approved_date":     "2024-03-15T00:00:00.000",
        },
        # 4 — Renewal (filtered by -I1 suffix).
        {
            "bin":               "3325703",
            "job_filing_number": "B00736930-S5",
            "work_type":         "Support of Excavation",
            "filing_reason":     "Renewal Permit Without Changes",
            "job_description": (
                "SUPPORT OF EXCAVATION WORK PER PLANS."
            ),
            "permit_status":     "Issued",
            "borough":           "BROOKLYN",
            "issued_date":       "2024-04-01",
            "approved_date":     "2024-04-01T00:00:00.000",
        },
        # 5 — Auxiliary (filtered by scope preference even
        #     though it has -I1).
        {
            "bin":               "3325703",
            "job_filing_number": "B01252711-I1",
            "work_type":         "Sidewalk Shed",
            "filing_reason":     "Initial Permit",
            "job_description": (
                "INSTALLATION OF HEAVY DUTY SIDEWALK SHED AND PIPE "
                "SCAFFOLDING. NO CHANGE IN USE, OCCUPANCY OR EGRESS."
            ),
            "permit_status":     "Issued",
            "borough":           "BROOKLYN",
            "issued_date":       "2025-07-15",
            "approved_date":     "2025-07-15T00:00:00.000",
        },
    ]
    socrata.seed(DATASET_DOB_PERMITS, rows)
    return {
        "bin":              "3325703",
        "expected_type":    "major_alt_with_enlargement",
        "scope_row_job":    "B00736930-I1",
        "auxiliary_jobs":   ["B00834550-I1", "B01252711-I1"],
        "renewal_jobs":     ["B00736930-S4", "B00736930-S5"],
    }


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


# ── PR #14E: Modern cohort source (DOB NOW C of O = pkdm-hqz6) ────


def _pkdm_co_issuance_date_mdy(
    months_ago: int,
    *, now: Optional[datetime] = None,
) -> str:
    """PR #14E — convert a relative-to-now offset (in months) into
    pkdm-hqz6's ``MM/DD/YY HH:MM:SS AM/PM`` format.

    Used by ``make_modern_cohort_fixture`` to seed cohort rows at
    deterministic times relative to a test ``now``. The 36mo cohort
    window in production reads from the cohort builder's ``now``
    arg; this helper produces strings the production code's
    ``_parse_pkdm_date`` helper will read.
    """
    base = now or datetime(2026, 5, 15, tzinfo=timezone.utc)
    target = base - timedelta(days=30 * months_ago)
    # MM/DD/YY  HH:MM:SS AM/PM (single space — production
    # _parse_pkdm_date tolerates 1+ spaces via \s+ per §7.7).
    return target.strftime("%m/%d/%y %I:%M:%S %p")


def seed_pkdm_co_for_bin(
    socrata,
    *,
    bin: str,
    bbl: str,
    job_type: str = "NEW BUILDING",
    c_of_o_filing_type: str = "Final",
    c_of_o_issuance_date_mdy: str = "01/15/24 12:00:00 AM",
    submitted_date: Optional[str] = "2023-06-01T00:00:00",
    borough: str = "BROOKLYN",
    application_number: Optional[str] = None,
    job_filing_name: Optional[str] = None,
    number_of_dwelling_units: Optional[str] = None,
) -> Dict[str, Any]:
    """PR #14E — seed one pkdm-hqz6 (DOB NOW C of O) row.

    Mirrors ``seed_bis_for_bin`` / ``seed_dob_now_for_bin`` patterns.
    Defaults match a Final C of O for a NEW BUILDING in Brooklyn.

    Per Stage 1 Task 1 schema discovery, the dataset's enum vocab:
      • c_of_o_filing_type: Final / Initial / Renewal With Change /
        Renewal Without Change (production filter uses
        ``IN ('Final', 'Initial')``)
      • job_type: NEW BUILDING / New Building (case variants —
        production query must match BOTH per Risk 3 lock) /
        ALTERATION TYPE 1 / Alteration CO / etc.
      • c_of_o_issuance_date: ``MM/DD/YY HH:MM:SS AM/PM`` — NOT ISO.

    Returns the seeded row dict for test mutation/reference.
    """
    row = {
        "bin":                  bin,
        "bbl":                  bbl,
        "job_type":             job_type,
        "c_of_o_filing_type":   c_of_o_filing_type,
        "c_of_o_status":        "CO Issued",
        "c_of_o_issuance_date": c_of_o_issuance_date_mdy,
        "submitted_date":       submitted_date,
        "borough":              borough,
        "application_number":   application_number or f"CO-{bin[-7:]}",
        "job_filing_name":      job_filing_name or bin,
    }
    if number_of_dwelling_units is not None:
        row["number_of_dwelling_units"] = str(number_of_dwelling_units)
    socrata.seed(DATASET_DOB_C_OF_O, [row])
    return row


# Map dob_project_type → pkdm-hqz6 job_type values that the
# Modern cohort query should match.
_PROJECT_TYPE_TO_PKDM_JOB_TYPES = {
    "new_building": ("NEW BUILDING", "New Building"),
    "major_alt_with_enlargement": ("ALTERATION TYPE 1",),
    "minor_alt": ("Alteration CO",),
    # full_demo intentionally absent — pkdm-hqz6 has no DEMOLITION
    # job_type (C of O is for OCCUPANCY; demolished buildings don't
    # get C of O). full_demo stays on BIS-only path (Q4 lock).
}


def make_modern_cohort_fixture(
    socrata,
    *,
    project_type: str,
    n_records: int,
    bin_prefix: str = "300300",
    bbl_prefix: str = "300301",
    job_filing_number_prefix: str = "B005",
    borough: str = "BROOKLYN",
    borough_pluto: str = "BK",
    building_class: str = "C1",
    numfloors: int = 4,
    yearbuilt: int = 2020,
    c_of_o_filing_type: str = "Final",
    months_ago: int = 12,
    permit_issued_date_iso: str = "2022-06-15T00:00:00.000",
    job_type_override: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """PR #14E — bulk-seed Modern cohort for N peers.

    Seeds 3 dataset rows per peer:
      1. ``pkdm-hqz6`` — Final/Initial C of O (the cohort discovery
         row). c_of_o_issuance_date derived from ``months_ago``
         relative to ``now`` (default 12mo back from 2026-05-15
         = within typical 36mo window).
      2. ``64uk-42ks`` (PLUTO) — bbl + bldgclass + numfloors +
         yearbuilt (the target-state filter target).
      3. ``rbx6-tga4`` (DOB NOW Permits) — Signed-off permit with
         ``issued_date`` + ``approved_date`` (for the Q6 lifecycle
         cross-join to compute permit_issued_date for cohort
         members).

    ``project_type`` selects the pkdm-hqz6 ``job_type`` written:
      new_building              → "NEW BUILDING"
      major_alt_with_enlargement → "ALTERATION TYPE 1"
      minor_alt                 → "Alteration CO"
      (full_demo intentionally not supported — full_demo cohort
       sources from BIS DM only per Q4 lock. Use
       ``make_cohort_fixture(project_type="full_demo", ...)``.)

    Pass ``job_type_override`` to test case-variant matching
    (Risk 3): e.g., job_type_override="New Building" to verify
    case-insensitive job_type matching in the cohort query.

    Returns the list of seeded (bin, bbl) metadata dicts for test
    iteration/assertion.
    """
    if project_type not in _PROJECT_TYPE_TO_PKDM_JOB_TYPES:
        raise ValueError(
            f"make_modern_cohort_fixture: project_type "
            f"{project_type!r} has no Modern path. full_demo uses "
            f"BIS DM only (Q4 lock); use make_cohort_fixture."
        )

    primary_job_type = (
        job_type_override
        or _PROJECT_TYPE_TO_PKDM_JOB_TYPES[project_type][0]
    )
    c_of_o_issuance_date_mdy = _pkdm_co_issuance_date_mdy(
        months_ago, now=now,
    )

    rows: List[Dict[str, Any]] = []
    for i in range(n_records):
        bin_ = f"{bin_prefix}{i:04d}"
        bbl_ = f"{bbl_prefix}{i:04d}"
        job_no = f"{job_filing_number_prefix}{i:05d}"

        # 1. pkdm-hqz6 row (cohort discovery).
        seed_pkdm_co_for_bin(
            socrata, bin=bin_, bbl=bbl_,
            job_type=primary_job_type,
            c_of_o_filing_type=c_of_o_filing_type,
            c_of_o_issuance_date_mdy=c_of_o_issuance_date_mdy,
            borough=borough,
        )
        # 2. PLUTO row (target-state filter).
        # PR #14G: seed with .00000000 suffix on bbl and .0000000
        # on numfloors/yearbuilt to mirror production PLUTO format
        # (Socrata ships those columns as numeric-float text). If
        # production code drops _normalize_pluto_bbl, the dict-lookup
        # in pluto_by_bbl mis-keys and the cohort returns 0 rows.
        socrata.seed(DATASET_PLUTO, [{
            "bbl": f"{bbl_}.00000000",
            "borough": borough_pluto,
            "bldgclass": building_class, "landuse": "01",
            "block": "3040", "lot": f"{i:04d}",
            "zipcode": "11221", "cd": "304",
            "yearbuilt": f"{yearbuilt}.0000000",
            "unitsres": "8", "unitstotal": "8",
            "numfloors": f"{numfloors}.0000000",
            "bldgarea": "8000", "lotarea": "2500",
        }])
        # 3. rbx6-tga4 row (Q6 lifecycle cross-join for
        #    permit_issued_date).
        socrata.seed(DATASET_DOB_PERMITS, [{
            "bin":               bin_,
            "bbl":               bbl_,
            "job_filing_number": f"{job_no}-I1",
            "work_type":         "General Construction",
            "filing_reason":     "Initial Permit",
            "job_description":   "",
            "permit_status":     "Signed-off",
            "borough":           borough,
            "issued_date":       permit_issued_date_iso.split("T")[0],
            "approved_date":     permit_issued_date_iso,
        }])
        rows.append({
            "bin": bin_, "bbl": bbl_,
            "job_filing_name": bin_,
            "job_type": primary_job_type,
        })
    return rows


# ── PR #15A: Predictive Inference Engine fixtures ─────────────────


def seed_ecb_violation_for_bin(
    socrata,
    *,
    bin: str,
    issue_date: str = "20240115",          # YYYYMMDD numeric (production format)
    severity: str = "CLASS - 1",           # exact match to enum (in locked filter set)
    ecb_violation_number: Optional[str] = None,
    ecb_violation_status: str = "ACTIVE",
    violation_type: str = "Construction",
    boro: str = "3",                       # Brooklyn = 3
    block: str = "03040",
    lot: str = "0024",
    hearing_date: Optional[str] = None,
    aggravated_level: str = "NO",
    respondent_house_number: str = "9",
    respondent_street: str = "MENAHAN STREET",
) -> Dict[str, Any]:
    """PR #15A — seed one 6bgk-3dad ECB Violation row.

    Defaults match a Brooklyn CLASS-1 construction violation —
    i.e., a "severe" violation that the locked WHERE filter
    ``severity IN ('CLASS - 1', 'CLASS - 2', 'Hazardous')`` will
    include in ``outcome_violation_d`` calculation.

    Per Stage 1 curl-verified schema:
      • ``issue_date`` is YYYYMMDD numeric text (8 digits, e.g.
        ``"20240115"``). Parser: ``_parse_socrata_yyyymmdd`` already
        in baselines.py.
      • ``severity`` enum exact: {CLASS - 1, CLASS - 2, Hazardous,
        CLASS - 3, Non-Hazardous, Unknown}. Locked filter passes
        the first 3 only.
      • ``bin`` plain 7-digit string (production format).

    Returns the seeded row dict so tests can mutate or stash it.
    """
    row = {
        "bin":                       bin,
        "boro":                      boro,
        "block":                     block,
        "lot":                       lot,
        "ecb_violation_number":      (
            ecb_violation_number or f"V{bin[-6:]}{issue_date[-4:]}"
        ),
        "ecb_violation_status":      ecb_violation_status,
        "issue_date":                issue_date,
        "hearing_date":              hearing_date or issue_date,
        "severity":                  severity,
        "violation_type":            violation_type,
        "aggravated_level":          aggravated_level,
        "respondent_house_number":   respondent_house_number,
        "respondent_street":         respondent_street,
    }
    socrata.seed(DATASET_DOB_ECB_VIOLATIONS, [row])
    return row


def seed_swo_disposition_for_bin(
    socrata,
    *,
    bin: str,
    complaint_number: str,
    date_entered: str = "01/15/2024",       # MM/DD/YYYY (production format)
    disposition_code: str = "A8",           # SWO-relevant: A8/A1/A9/B1
    disposition_date: Optional[str] = None, # MM/DD/YYYY
    inspection_date: Optional[str] = None,  # MM/DD/YYYY
    complaint_category: str = "1B",
    status: str = "CLOSED",
    community_board: str = "304",           # 3-digit string (production format)
    house_number: Optional[str] = None,
    house_street: Optional[str] = None,
    zip_code: str = "11221",
) -> Dict[str, Any]:
    """PR #15A — seed one eabe-havv DOB Complaint row with SWO
    disposition for the active SWO state machine.

    Locked SWO disposition codes (Stage 2.A T1 lock):
      • A8 — Close work (active SWO issued)
      • A1 — Issue work-stop (active SWO issued)
      • A9 — Vacate (clears active SWO)
      • B1 — Rescind (clears active SWO)

    Per Stage 1 curl-verified schema:
      • ``date_entered`` + ``disposition_date`` are MM/DD/YYYY text
        (e.g. ``"01/15/2024"``). Parser: ``_parse_bis_mdy_date``
        already in baselines.py (PR #14F helper).
      • ``bin`` plain 7-digit text.
      • ``community_board`` 3-digit string format (1st digit = boro
        code: 1=MN, 2=BX, 3=BK, 4=QN, 5=SI).
    """
    if disposition_code not in ("A1", "A8", "A9", "B1"):
        # Allow defensive use for non-SWO codes too (caller can
        # override); the panel state-machine code filters to these
        # 4 codes when computing active_swo_flag.
        pass
    row = {
        "bin":                bin,
        "complaint_number":   complaint_number,
        "date_entered":       date_entered,
        "disposition_code":   disposition_code,
        "disposition_date":   disposition_date or date_entered,
        "inspection_date":    inspection_date,
        "complaint_category": complaint_category,
        "status":             status,
        "community_board":    community_board,
        "house_number":       house_number or "9",
        "house_street":       house_street or "MENAHAN STREET",
        "zip_code":           zip_code,
    }
    socrata.seed(DATASET_DOB_COMPLAINTS, [row])
    return row


def make_daily_panel_fixture(
    db,
    *,
    project_id: str,
    cohort_members: List[Dict[str, Any]],  # [{bbl, bin, segment}]
    panel_window_days: int = 30,
    cur_now: Optional[datetime] = None,
    outcomes_random_seed: int = 42,
    schema_version: str = "pr15a_v1",
) -> List[Dict[str, Any]]:
    """PR #15A — bulk-insert deterministic daily_panels rows into the
    test ``db.daily_panels`` collection stub.

    For each cohort member × each day in the panel window, emits one
    row with:
      • Zero-default x_features (caller can override per-row before
        feeding to assertions).
      • ``outcome_violation_d`` toggled via a seeded ``random.Random``
        so test runs are reproducible.
      • ``outcome_violation_d_to_d_plus_7`` set to ``None`` for the
        trailing 7 days per Stage 2.A T5 lock (right-censoring).
      • ``sample_weight`` 1.0 for ``"modern"`` segment, 0.4 for
        ``"legacy"`` per Lock B.

    Returns the list of inserted rows so tests can assert against
    the data shape directly.
    """
    panel_built_at = cur_now or datetime(2026, 5, 15, tzinfo=timezone.utc)
    rng = random.Random(outcomes_random_seed)
    rows: List[Dict[str, Any]] = []
    for member in cohort_members:
        bbl = member["bbl"]
        bin_ = member["bin"]
        segment = member.get("segment", "modern")
        sample_weight = 1.0 if segment == "modern" else 0.4
        for day_offset in range(panel_window_days):
            day_dt = panel_built_at - timedelta(
                days=panel_window_days - 1 - day_offset,
            )
            day_calendar_date = day_dt.strftime("%Y-%m-%d")
            outcome_d = rng.random() < 0.05  # 5% positive base rate
            # T5 right-censoring: last 7 days can't know outcome.
            if day_offset >= panel_window_days - 7:
                outcome_d_to_d7 = None
            else:
                outcome_d_to_d7 = (rng.random() < 0.15)
            row = {
                "project_id":          project_id,
                "cohort_member_bbl":   bbl,
                "cohort_member_bin":   bin_,
                "cohort_segment":      segment,
                "sample_weight":       sample_weight,
                "day_in_lifecycle":    day_offset,
                "day_calendar_date":   day_calendar_date,
                "x_features": {
                    "active_swo_flag":              0,
                    "complaint_velocity_14d":       0,
                    "days_since_last_violation":    90,
                    "derived_lifecycle_stage_pct":  0.20,
                    "district_caseload_proxy_days": 7.0,
                },
                "outcome_violation_d":              outcome_d,
                "outcome_violation_d_to_d_plus_7":  outcome_d_to_d7,
                "built_at":                         panel_built_at,
                "panel_schema_version":             schema_version,
            }
            rows.append(row)
    if rows and getattr(db, "daily_panels", None) is not None:
        # _StubDailyPanels.insert_many extends self.docs.
        try:
            import asyncio
            coro = db.daily_panels.insert_many(rows)
            if asyncio.iscoroutine(coro):
                asyncio.get_event_loop().run_until_complete(coro)
        except Exception:
            # Synchronous stub fallback.
            for r in rows:
                db.daily_panels.docs.append(r)
    return rows


def seed_validation_ledger_entries(
    db,
    *,
    project_id: str,
    n_entries: int,
    prediction_timestamps: Optional[List[datetime]] = None,
    brier_distribution: Optional[List[float]] = None,
    target_horizon_days: int = 7,
    observed_outcomes: Optional[List[Optional[bool]]] = None,
    predicted_probabilities: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    """PR #15A — bulk-insert prediction_validation_ledger entries.

    Per Stage 2.A T7 lock: one canonical entry per
    (project_id, calendar_date). Tests for the upsert path call
    this helper to seed historical entries, then assert on the
    rolling-30d Brier aggregation.

    All list args, when provided, must have length ``n_entries``.
    ``observed_outcomes`` may include ``None`` for unscored entries.
    """
    if prediction_timestamps is None:
        base = datetime(2026, 5, 15, tzinfo=timezone.utc)
        prediction_timestamps = [base - timedelta(days=i) for i in range(n_entries)]
    if brier_distribution is None:
        brier_distribution = [0.10] * n_entries
    if observed_outcomes is None:
        observed_outcomes = [True] * n_entries
    if predicted_probabilities is None:
        predicted_probabilities = [0.30] * n_entries

    rows: List[Dict[str, Any]] = []
    for i in range(n_entries):
        ts = prediction_timestamps[i]
        rows.append({
            "project_id":              project_id,
            "prediction_timestamp":    ts,
            "target_horizon_days":     target_horizon_days,
            "target_horizon_at":       ts + timedelta(days=target_horizon_days),
            "calendar_date":           ts.strftime("%Y-%m-%d"),
            "predicted_probability":   predicted_probabilities[i],
            "observed_outcome":        observed_outcomes[i],
            "scored_at":               (
                ts + timedelta(days=target_horizon_days)
                if observed_outcomes[i] is not None else None
            ),
            "brier_score_delta":       (
                brier_distribution[i]
                if observed_outcomes[i] is not None else None
            ),
            "model_coefficients_hash": "sha1_test_hash",
        })
    if rows and getattr(db, "prediction_validation_ledger", None) is not None:
        for r in rows:
            db.prediction_validation_ledger.docs.append(r)
    return rows


@contextlib.contextmanager
def mock_nightly_cron_trigger(
    *,
    cur_now: datetime,
) -> Iterator[Dict[str, Any]]:
    """PR #15A — context manager that freezes ``datetime.now(tz=UTC)``
    and captures calls to the nightly cron functions.

    Yields a captures dict with:
      • ``compute_daily_panel_calls`` — list of (args, kwargs) tuples
      • ``provenance_checksum_calls`` — list of cohort_member_provenance
        lists passed to the checksum helper
      • ``prewarm_calls`` — list of (db, project_id) tuples

    Stage 3 implementation must expose:
      • ``lib.statistical_engine.daily_panel.compute_daily_panel``
      • ``lib.statistical_engine.daily_panel._provenance_checksum``
      • ``lib.statistical_engine.prewarm.prewarm_peer_stats`` (existing)
    """
    captures: Dict[str, List[Any]] = {
        "compute_daily_panel_calls":   [],
        "provenance_checksum_calls":   [],
        "prewarm_calls":                [],
    }

    # Patch datetime.now(tz=UTC) in baselines + daily_panel namespaces
    # so any code reading "today" gets the frozen instant.
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cur_now if tz is None else cur_now.astimezone(tz)

    patches = []
    try:
        # Best-effort patches — module may not exist at Stage 2.B
        # (daily_panel.py defers to Stage 3). Tests that need the
        # capture-dict at red phase can still introspect via the
        # yielded ``captures`` after asserting ImportError.
        import importlib
        for mod_name in (
            "lib.statistical_engine.daily_panel",
            "lib.statistical_engine.baselines",
            "lib.statistical_engine.prewarm",
        ):
            try:
                mod = importlib.import_module(mod_name)
            except ImportError:
                continue
            if hasattr(mod, "datetime"):
                p = patch.object(mod, "datetime", _FrozenDatetime)
                patches.append(p)
                p.start()
        yield captures
    finally:
        for p in patches:
            try:
                p.stop()
            except Exception:
                pass
