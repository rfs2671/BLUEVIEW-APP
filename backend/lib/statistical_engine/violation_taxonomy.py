"""Phase 1 Week 8 PR-A — 10-bucket DOB event taxonomy.

Two classifier surfaces:

  classify_complaint(code)
    Deterministic lookup against ``COMPLAINT_CODE_TO_BUCKET``. The
    eabe-havv dataset's ``complaint_category`` is a 2-char alphanumeric
    code (e.g. ``"45"``, ``"6S"``) — there is no free-text description
    field on the complaint record itself, so the code IS the
    classifier key.

    The lookup table is derived from
    ``backend/dob_complaint_codes.py:DOB_CATEGORY_CODES`` (the
    canonical NYC DOB category reference, sourced from
    https://www.nyc.gov/assets/buildings/pdf/complaint_category.pdf).
    Each existing entry's ``desc`` field is semantically mapped to one
    of the 10 buckets at the bottom of this module.

  classify_violation(violation_type, violation_description)
    Ordered regex against ``f"{violation_type} {violation_description}"
    .upper()``. First match wins; falls through to ``"other"`` on no
    match. Used for the 6bgk-3dad ECB violation dataset which carries
    free-text descriptions like ``"GC FAIL TO FILE CERTIFICATE OF
    CORRECTION..."``.

Both classifiers return one of:

  ``structural_concerns``    — building shaking, collapse, facade cracks
  ``construction_violations``— illegal/no-permit work, AHV, audits
  ``occupancy_violations``   — illegal conversion, SRO, C of O
  ``safety_hazards``         — cranes, scaffolds, falling debris, accidents
  ``environmental``          — asbestos, lead, smoking on site
  ``mep_systems``            — gas, plumbing, electrical, HVAC, elevators
  ``accessibility``          — egress, ADA, fire escape obstruction
  ``zoning``                 — non-conforming, manufacturing in residential
  ``quality_of_life``        — signs, fences, dumpsters, sidewalk obstruction
  ``other``                  — catch-all for unmatched codes / text

Phase 1 Week 8 PR-B will import these to compute
``recent_violation_bucket`` per project (most-recent violation in the
last 90 days, classified via ``classify_violation``).

Module is pure functions + constants — no DB access, no async.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


# ── 10 canonical buckets ──────────────────────────────────────────


BUCKETS: Tuple[str, ...] = (
    "structural_concerns",
    "construction_violations",
    "occupancy_violations",
    "safety_hazards",
    "environmental",
    "mep_systems",
    "accessibility",
    "zoning",
    "quality_of_life",
    "other",
)


# ── Complaint code → bucket lookup ────────────────────────────────
#
# Derived from backend/dob_complaint_codes.py:DOB_CATEGORY_CODES by
# semantic alignment of each code's `desc` field. Every code with a
# non-trivial production volume (top-30 codes covering ~1.8M complaints
# citywide) lands in a specific bucket; lower-volume codes likewise.
# Codes absent from this map → "other" via classify_complaint's
# .get(code, "other") fallback.
#
# Borderline assignments documented inline. Future code additions:
# update this map when DOB publishes new category codes — alpha codes
# like 6S, 4B, etc. expand over time.

COMPLAINT_CODE_TO_BUCKET: Dict[str, str] = {
    # ── structural_concerns ──
    "14": "structural_concerns",   # Excavation undermining adjacent
    "16": "structural_concerns",   # Inadequate support/shoring
    "28": "structural_concerns",   # In danger of collapse
    "30": "structural_concerns",   # Building shaking/structural stability
    "40": "structural_concerns",   # Falling — part of building
    "41": "structural_concerns",   # Falling — part of building in danger
    "43": "structural_concerns",   # Structural stability affected
    "54": "structural_concerns",   # Wall/retaining wall — bulging/cracked
    "84": "structural_concerns",   # Facade defective/cracking
    "93": "structural_concerns",   # Retaining wall safety inspection
    "1K": "structural_concerns",   # Bowstring truss tracking
    "2F": "structural_concerns",   # Building under structural monitoring
    "2K": "structural_concerns",   # Structurally compromised building
    "2L": "structural_concerns",   # Facade LL11/98 unsafe
    "2P": "structural_concerns",   # Facades unit compliance
    "4N": "structural_concerns",   # Retaining wall tracking
    "5B": "structural_concerns",   # Non-compliance lightweight materials
    "5C": "structural_concerns",   # Structural stability impacted new build
    "5D": "structural_concerns",   # Vertical enlargements TPPN 1/00

    # ── construction_violations ──
    "03": "construction_violations",  # Adjacent buildings not protected
    "04": "construction_violations",  # After hours work illegal
    "05": "construction_violations",  # Permit — none
    "06": "construction_violations",  # Change grade/watercourse
    "07": "construction_violations",  # Change watercourse
    "11": "construction_violations",  # Demolition — no permit
    "12": "construction_violations",  # Demolition unsafe/illegal
    "17": "construction_violations",  # Material/personnel hoist no permit
    "19": "construction_violations",  # Mechanical demolition illegal
    "20": "construction_violations",  # Landmark building illegal work
    "46": "construction_violations",  # PA permit none
    "47": "construction_violations",  # PA permit not complied with
    "73": "construction_violations",  # Failure to maintain (catch-all enforcement)
    "83": "construction_violations",  # Contrary to approved plans
    "86": "construction_violations",  # Work contrary to SWO
    "90": "construction_violations",  # Unlicensed/illegal activity
    "2A": "construction_violations",  # Posted notice tampered with
    "2B": "construction_violations",  # Failure to comply with vacate
    "2H": "construction_violations",  # Second Avenue subway construction
    "2N": "construction_violations",  # COVID-19 executive order
    "4B": "construction_violations",  # SEP — professional cert audit
    "4E": "construction_violations",  # Stalled sites tracking
    "4H": "construction_violations",  # V.E.S.T. program enforcement
    "4K": "construction_violations",  # CSC: DM tracking
    "4L": "construction_violations",  # CSC: high-rise tracking
    "4M": "construction_violations",  # CSC: low-rise tracking
    "4P": "construction_violations",  # Legal/padlock tracking
    "4S": "construction_violations",  # Sustainability enforcement
    "4X": "construction_violations",  # AHV permit after hours
    "5F": "construction_violations",  # Compliance inspection
    "5G": "construction_violations",  # Unlicensed work in-progress
    "5H": "construction_violations",  # Illegal activity
    "5J": "construction_violations",  # Multi-agency joint inspection
    "6A": "construction_violations",  # Vesting inspection
    "6C": "construction_violations",  # Homeless shelter — construction
    "6X": "construction_violations",  # Watch list compliance
    "6Y": "construction_violations",  # Local law audits
    "6Z": "construction_violations",  # Training compliance
    "7A": "construction_violations",  # Integrity complaint referral
    "7F": "construction_violations",  # CSE: tracking compliance
    "7G": "construction_violations",  # CSE: sweep
    "7J": "construction_violations",  # Work without permit occupied MD
    "7K": "construction_violations",  # Local Law 188/17 active jobs
    "8A": "construction_violations",  # Construction safety compliance
    "1G": "construction_violations",  # Stalled construction site
    "1U": "construction_violations",  # Special ops compliance
    "1X": "construction_violations",  # Construction enforcement work order
    "1Y": "construction_violations",  # Enforcement work order
    "1Z": "construction_violations",  # Enforcement work order
    "3B": "construction_violations",  # Routine inspection
    "3C": "construction_violations",  # Plan compliance
    "3H": "construction_violations",  # DCP/BSA compliance

    # ── occupancy_violations ──
    "29": "occupancy_violations",  # Building — vacant, open, unguarded
    "31": "occupancy_violations",  # Certificate of Occupancy none/illegal
    "32": "occupancy_violations",  # C of O not complied with
    "33": "occupancy_violations",  # Commercial use — illegal
    "45": "occupancy_violations",  # Illegal Conversion
    "48": "occupancy_violations",  # Residential use illegal
    "51": "occupancy_violations",  # Illegal social club
    "71": "occupancy_violations",  # SRO illegal work
    "72": "occupancy_violations",  # SRO change in occupancy
    "75": "occupancy_violations",  # Adult establishment
    "92": "occupancy_violations",  # Illegal conversion mfg/industrial
    "1A": "occupancy_violations",  # Illegal commercial→dwelling conversion
    "4A": "occupancy_violations",  # Illegal hotel rooms in residential
    "4G": "occupancy_violations",  # Illegal conversion follow-up

    # ── safety_hazards ──
    "01": "safety_hazards",   # Accident — Construction/Plumbing
    "02": "safety_hazards",   # Accident — to public
    "10": "safety_hazards",   # Debris/building falling
    "13": "safety_hazards",   # Elevator FDNY readiness
    "21": "safety_hazards",   # Safety net/guard rail >6-story
    "22": "safety_hazards",   # Safety netting none
    "23": "safety_hazards",   # Sidewalk shed/scaffold inadequate
    "24": "safety_hazards",   # Sidewalk shed none
    "62": "safety_hazards",   # Elevator danger condition
    "64": "safety_hazards",   # Elevator shaft open unguarded
    "67": "safety_hazards",   # Crane no permit/unsafe
    "68": "safety_hazards",   # Crane/scaffold unsafe operations
    "69": "safety_hazards",   # Crane/scaffold unsafe installation
    "70": "safety_hazards",   # Suspension scaffold hanging
    "81": "safety_hazards",   # Elevator accident
    "82": "safety_hazards",   # Boiler accident/explosion
    "87": "safety_hazards",   # Deck safety inspection
    "88": "safety_hazards",   # Safety net/guard rail <6-story
    "89": "safety_hazards",   # Accident — cranes/derricks
    "91": "safety_hazards",   # Site conditions endangering workers
    "1C": "safety_hazards",   # Damage assessment / disaster
    "1E": "safety_hazards",   # Suspended scaffolds dangerous
    "1F": "safety_hazards",   # Failure to comply with annual crane inspection
    "2J": "safety_hazards",   # SANDY building destroyed
    "5A": "safety_hazards",   # Joint FDNY/DOB inspection
    "5E": "safety_hazards",   # Amusement ride accident
    "6V": "safety_hazards",   # Tenant safety inspection
    "6W": "safety_hazards",   # Tenant safety failure to post

    # ── environmental ──
    "1H": "environmental",   # Emergency Asbestos Response
    "1J": "environmental",   # Jewelry/dentistry torch gas piping
    "2C": "environmental",   # Smoking ban — smoking on construction
    "2D": "environmental",   # Smoking signs not observed

    # ── mep_systems ──
    "44": "mep_systems",     # Fireplace/wood stove (fuel-burning appliance)
    "52": "mep_systems",     # Sprinkler system inadequate
    "53": "mep_systems",     # Vent/exhaust illegal
    "56": "mep_systems",     # Boiler fumes/smoke/CO
    "57": "mep_systems",     # Boiler illegal
    "58": "mep_systems",     # Boiler defective
    "59": "mep_systems",     # Electrical wiring defective
    "60": "mep_systems",     # Electrical work improper
    "61": "mep_systems",     # Electrical work unlicensed
    "63": "mep_systems",     # Elevator defective/inoperative
    "65": "mep_systems",     # Gas hook-up/piping illegal
    "66": "mep_systems",     # Plumbing work illegal/no permit
    "76": "mep_systems",     # Plumbing unlicensed/illegal
    "80": "mep_systems",     # Elevator not inspected
    "94": "mep_systems",     # Plumbing defective/leaking
    "96": "mep_systems",     # Unlicensed boiler/electrical/plumbing
    "3A": "mep_systems",     # Unlicensed electrical work
    "6B": "mep_systems",     # Homeless shelter — plumbing
    "6D": "mep_systems",     # Homeless shelter — electrical
    "6M": "mep_systems",     # Elevator multiple devices
    "6S": "mep_systems",     # Elevator single device
    "1D": "mep_systems",     # Con Edison referral (electrical utility)
    "1L": "mep_systems",     # Gas utility referral
    "1V": "mep_systems",     # Electrical enforcement work order
    "1W": "mep_systems",     # Plumbing enforcement work order

    # ── accessibility ──
    "37": "accessibility",   # Egress locked/blocked
    "38": "accessibility",   # Egress exit door not proper
    "39": "accessibility",   # Egress no secondary means
    "77": "accessibility",   # Contrary to LL58/87 handicap access
    "3D": "accessibility",   # Bicycle access waiver elevator safety
    "3E": "accessibility",   # Bicycle access waiver alternate parking
    "3G": "accessibility",   # Restroom non-compliance LL79/16

    # ── zoning ──
    "27": "zoning",          # Auto repair illegal (use group)
    "55": "zoning",          # Zoning non-conforming
    "74": "zoning",          # Illegal commercial/mfg in residential zone
    "7B": "zoning",          # Illegal commercial/mfg in C1/C2

    # ── quality_of_life ──
    "08": "quality_of_life", # Contractor's sign none
    "09": "quality_of_life", # Debris excessive
    "15": "quality_of_life", # Fence none/inadequate
    "18": "quality_of_life", # Material storage unsafe
    "25": "quality_of_life", # Warning signs/lights none
    "26": "quality_of_life", # Watchman none
    "34": "quality_of_life", # Compactor room/refuse chute illegal
    "35": "quality_of_life", # Curb cut/driveway illegal
    "36": "quality_of_life", # Driveway/carport illegal
    "42": "quality_of_life", # Fence illegal
    "49": "quality_of_life", # Storefront sign illegal
    "50": "quality_of_life", # Sign falling danger
    "78": "quality_of_life", # POPS non-compliance
    "79": "quality_of_life", # Lights from parking lot
    "85": "quality_of_life", # Failure to retain water/drainage
    "1B": "quality_of_life", # Illegal tree removal in SNAD
    "2E": "quality_of_life", # Tracking complaint demolition notification
    "2G": "quality_of_life", # Advertising sign/billboard illegal
    "2M": "quality_of_life", # Monopole tracking
    "4J": "quality_of_life", # M.A.R.C.H. program (community hotspots)
    "4W": "quality_of_life", # Woodside settlement project
    "7L": "quality_of_life", # DOHMH tenant protection
    "7N": "quality_of_life", # POPS compliance inspection
}


# ── Violation regex rules (ordered, first-match-wins) ─────────────
#
# Applied against ``f"{violation_type} {violation_description}".upper()``
# for ECB violations from socrata_ecb_violations_historical.
#
# Ordering matters: safety_hazards comes first because crane/scaffold
# accidents are the highest-priority signal even when descriptions
# tangentially mention other systems. Environmental + MEP follow.
# Structural sits mid-order because facade/wall language tends to be
# specific and unambiguous. Quality-of-life comes near the end as it
# catches a lot of mild descriptions (sidewalk, signs).
#
# "other" is the implicit fallback when no rule matches.

VIOLATION_REGEX_RULES: List[Tuple[re.Pattern, str]] = [
    # safety_hazards — accidents, cranes, scaffolds, falling, OSHA
    (
        re.compile(
            r"CRANE|SCAFFOLD|FALLING|FELL FROM|FALL HAZARD|"
            r"COLLAPSE|HOIST|RIGGING|OSHA|ACCIDENT|"
            r"FALLEN|DERRICK|BOOM"
        ),
        "safety_hazards",
    ),
    # environmental — asbestos, lead, dust, smoking
    (
        re.compile(
            r"ASBESTOS|LEAD ABATEMENT|LEAD PAINT|DUST CONTROL|"
            r"DEMOLITION DUST|AIR QUALITY|SMOKING|"
            r"HAZARDOUS MATERIAL|CONTAMIN"
        ),
        "environmental",
    ),
    # mep_systems — electrical, plumbing, gas, HVAC, boiler, elevator,
    # sprinkler, standpipe
    (
        re.compile(
            r"ELECTRIC|GAS LEAK|GAS HOOK|GAS PIPING|"
            r"PLUMB|HVAC|BOILER|ELEVATOR|"
            r"SPRINKLER|STANDPIPE|FIRE PROTECT"
        ),
        "mep_systems",
    ),
    # accessibility — egress, ADA, fire escape
    (
        re.compile(
            r"EGRESS|FIRE ESCAPE|ADA|ACCESSIBILITY|"
            r"HANDICAP|RESTROOM ACCESS"
        ),
        "accessibility",
    ),
    # structural_concerns — building shaking, collapse, facade
    (
        re.compile(
            r"STRUCTUR|FOUNDATION|FACADE|CRACK|SETTLEMENT|"
            r"LOAD BEARING|UNDERPINNING|"
            r"RETAINING WALL|UNDERMINING|SHORING"
        ),
        "structural_concerns",
    ),
    # zoning — non-conforming use, FAR, height, setback
    (
        re.compile(
            r"ZONING|SETBACK|FAR VIOLATION|HEIGHT VIOLATION|"
            r"YARD VIOLATION|NON-CONFORMING USE"
        ),
        "zoning",
    ),
    # occupancy_violations — CO, illegal conversion, SRO
    (
        re.compile(
            r"CERTIFICATE OF OCCUPANCY|C OF O|ILLEGAL OCCUP|"
            r"USE GROUP|SRO|ILLEGAL CONVERSION|"
            r"VACANT BUILDING|HOTEL ROOM"
        ),
        "occupancy_violations",
    ),
    # construction_violations — illegal work, after-hours, permit issues
    (
        re.compile(
            r"WITHOUT PERMIT|NO PERMIT|CONTRARY TO|FAIL TO FILE|"
            r"CORRECTIVE|UNAUTHORIZED|UNLAWFUL|"
            r"STOP WORK|AFTER HOURS|UNLICENSED"
        ),
        "construction_violations",
    ),
    # quality_of_life — sidewalk, signs, fences, dumpsters, debris
    (
        re.compile(
            r"SIDEWALK|SIGN ILLEG|FENCE|DUMPSTER|"
            r"DEBRIS|REFUSE|WATCHMAN|CURB CUT|"
            r"WARNING LIGHT"
        ),
        "quality_of_life",
    ),
]


# ── Public API ────────────────────────────────────────────────────


def classify_complaint(code: Optional[str]) -> str:
    """Classify a DOB complaint by complaint_category code.

    Returns one of the 10 BUCKETS. Falls back to "other" for None,
    empty string, or codes not present in COMPLAINT_CODE_TO_BUCKET.

    Normalization: leading/trailing whitespace stripped + uppercased
    before lookup. Production data is consistently uppercase but
    callers may pass lowercase from manual input.
    """
    if not code:
        return "other"
    key = code.strip().upper()
    if not key:
        return "other"
    return COMPLAINT_CODE_TO_BUCKET.get(key, "other")


def classify_violation(
    violation_type: Optional[str],
    violation_description: Optional[str],
) -> str:
    """Classify a DOB ECB violation by joining the two text fields
    and matching against VIOLATION_REGEX_RULES in order.

    First match wins; falls through to "other" when no rule matches.
    Inputs are uppercased before matching so callers don't need to
    pre-normalize.
    """
    vt = (violation_type or "").upper()
    vd = (violation_description or "").upper()
    text = f"{vt} {vd}".strip()
    if not text:
        return "other"
    for pattern, bucket in VIOLATION_REGEX_RULES:
        if pattern.search(text):
            return bucket
    return "other"
