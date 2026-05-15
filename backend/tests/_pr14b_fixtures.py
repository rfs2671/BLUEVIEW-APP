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

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ── Dataset IDs PR #14B touches ───────────────────────────────────
# These are NOT yet re-exported from lib.statistical_engine.socrata_client
# (Stage 3 will add them). Until then the fixture pins the IDs literally
# so tests don't depend on Stage 3 having landed first.

DATASET_BIS_JOB_FILINGS = "ic3t-wcy2"
DATASET_C_OF_O_LEGACY   = "bs8b-p36w"
DATASET_DOB_PERMITS     = "rbx6-tga4"  # DOB NOW; also exists in socrata_client
DATASET_PLUTO           = "64uk-42ks"  # PLUTO; mirrors socrata_client

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
