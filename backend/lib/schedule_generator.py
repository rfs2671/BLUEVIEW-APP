"""SCHEDULE GENERATOR: a remaining-work schedule ESTIMATE for a job that will
never upload a schedule, built from the building's own drawings, a STATE of the
work, and assumptions that each say where they came from.

Pure: no database, no network, no clock. The caller hands in the building model
(the drawings lane's building.json shape), the records (crew check-ins, log
phrases), the public inspection record, an optional STATE, and the data date.

WHAT THIS IS, AND WHAT IT NEVER BECOMES (owner rulings, 2026-11-09):
  * An ESTIMATE with its basis. Never a baseline, never a schedule file, never
    a fact. The document says so at its top (`kind`, `is_baseline`), carries
    no baseline_* / current_* / actual_* / planned_* field anywhere (so the
    FILE readers in lib/forecast.py and lib/progress_plan.py find no dates in
    it), and its dates leave it only as evidence items of kind "estimate"
    (`estimate_items`), which lib/forecast never counts as a start or a finish.
  * A PROPOSED sequence, offered for approval, separate from any official
    schedule. Approval would make it the sequence someone agreed to; it would
    still not be a schedule file.
  * Production rates are NOT derived from activity dates, from a crew moving
    between floors, or from photo counts. What is MEASURED from the records is
    crew SIZE (check-ins per day, with the sample size) and two inspection
    request-to-result intervals. Every production rate is an industry
    assumption and is labelled so.

THE NETWORK comes from the building, not a generic template: its zones are
the building's levels; its quantities are the drawing's wall lengths by type,
units, baths, kitchens, PTAC count, doors, windows and roof/facade areas; its
branches exist only when the drawing says the system exists (gas, sprinkler,
roof detention, elevator, standpipe, cellar). Inspections and tests are their
own GATE activities. Every link says whether it is a true prerequisite
(technical or regulatory), a permissible overlap, or a crew (resource) link.

CPM: forward and backward pass on a working-day calendar (Mon-Fri less stated
holidays); weather-sensitive work consumes a stated workable fraction of each
working day by month. Total float is in working days. The critical path is
walked back from the finish through each activity's DRIVING predecessor.
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import evidence as E

ENGINE = "schedule_generator v1"
DOC_KIND = "schedule_estimate"
SCENARIOS = ("fast", "normal", "conservative")
#: the stacked worst case, reported separately as a stress test (not a scenario)
STRESS = "stress"
ALL_RUNS = SCENARIOS + (STRESS,)
#: "derived-report": a figure read from a generated report or snapshot, not
#: from an original record (records/AUDIT.md); never called measured.
TAGS = ("measured", "derived-report", "drawing", "regulatory", "industry-assumption")
STATUSES = ("done", "in_progress", "not_started", "unknown")
EVIDENCE = ("verified_public_record", "reported_log", "derived_report", "operator_statement", "inferred", "no_record")
#: original per-day crew counts needed before a crew size is called measured
MIN_MEASURED_DAYS = 3
LINK_KINDS = ("prerequisite", "overlap", "resource")
LINK_TYPES = ("FS", "SS", "FF")
#: Field-name prefixes a schedule FILE uses (lib/schedule_import.py). None may
#: appear on an estimate, so nothing reads an estimate as a file date.
FILE_FIELD_PREFIXES = ("baseline_", "current_", "actual_", "planned_")
MIN_REMAINING = 0.1
EPS = 1e-9

Act = Dict[str, Any]
Link = Dict[str, Any]


# ═══ CALENDAR ════════════════════════════════════════════════════════════════

class Calendar:
    """Working days from the data date: Monday-Friday less `holidays`. Day
    index 0 is the first working day on or after the data date. Indexes below
    0 are the working days before it."""

    def __init__(self, start: date, holidays: Iterable[date] = ()):
        self.holidays = set(holidays)
        d = start
        while not self.is_working(d):
            d += timedelta(days=1)
        self.origin = d
        self._fwd: List[date] = [d]

    def is_working(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def date(self, i: int) -> date:
        if i < 0:
            d, k = self.origin, 0
            while k > i:
                d -= timedelta(days=1)
                if self.is_working(d):
                    k -= 1
            return d
        while len(self._fwd) <= i:
            d = self._fwd[-1] + timedelta(days=1)
            while not self.is_working(d):
                d += timedelta(days=1)
            self._fwd.append(d)
        return self._fwd[i]

    def index(self, d: date) -> int:
        """Working-day index of `d` (the next working day if `d` is not one)."""
        i = 0
        while self.date(i) < d:
            i += 1
        return i


def advance(start: int, effort: float, cap: Callable[[int], float]) -> int:
    """Exclusive end index: the first index e at which the capacity summed over
    [start, e) reaches `effort`. Effort 0 ends where it starts."""
    if effort <= EPS:
        return start
    acc, i = 0.0, start
    while acc < effort - EPS:
        acc += cap(i)
        i += 1
    return i


def retreat(end: int, effort: float, cap: Callable[[int], float]) -> int:
    """The latest start s with capacity summed over [s, end) reaching `effort`."""
    if effort <= EPS:
        return end
    acc, i = 0.0, end
    while acc < effort - EPS:
        i -= 1
        acc += cap(i)
    return i


# ═══ CPM ═════════════════════════════════════════════════════════════════════

def topo_order(ids: Sequence[str], links: Sequence[Link]) -> List[str]:
    known = set(ids)
    succ: Dict[str, List[str]] = {i: [] for i in ids}
    indeg = {i: 0 for i in ids}
    for l in links:
        if l["from"] not in known or l["to"] not in known:
            raise ValueError(f"link to an unknown activity: {l['from']} -> {l['to']}")
        succ[l["from"]].append(l["to"])
        indeg[l["to"]] += 1
    rank = {i: n for n, i in enumerate(ids)}
    ready = sorted((i for i in ids if indeg[i] == 0), key=rank.get)
    out: List[str] = []
    while ready:
        i = ready.pop(0)
        out.append(i)
        for j in succ[i]:
            indeg[j] -= 1
            if indeg[j] == 0:
                ready.append(j)
                ready.sort(key=rank.get)
    if len(out) != len(ids):
        raise ValueError("the network has a cycle: " + ", ".join(sorted(set(ids) - set(out))[:8]))
    return out


def cpm(acts: Sequence[Act], links: Sequence[Link]) -> Dict[str, Dict[str, Any]]:
    """Forward and backward pass.

    acts: {"id", "effort" (working days of effort, >= 0), "cap" (index ->
    capacity in (0, 1]; default 1), "not_before" (index, default 0),
    "pinned" (True: done, fixed at index 0)}.
    links: {"from", "to", "type" FS|SS|FF, "lag" (working days, >= 0)}.
    Returns per id: es, ef (exclusive), ls, lf, tf (working days), driver
    (the link that set es, or a reason)."""
    by_id = {a["id"]: a for a in acts}
    order = topo_order([a["id"] for a in acts], links)
    into: Dict[str, List[Link]] = {i: [] for i in by_id}
    outof: Dict[str, List[Link]] = {i: [] for i in by_id}
    for l in links:
        into[l["to"]].append(l)
        outof[l["from"]].append(l)
    one = lambda _i: 1.0  # noqa: E731
    r: Dict[str, Dict[str, Any]] = {}
    for j in order:
        a = by_id[j]
        cap = a.get("cap") or one
        d = float(a.get("effort") or 0.0)
        if a.get("pinned"):
            r[j] = {"es": 0, "ef": 0, "driver": "done"}
            continue
        es = int(a.get("not_before") or 0)
        driver: Any = "data date" if not a.get("not_before") else "start constraint"
        ff_min, ff_link = None, None
        for l in into[j]:
            p, lag = r[l["from"]], int(l.get("lag") or 0)
            if l["type"] == "FS":
                v = p["ef"] + lag
            elif l["type"] == "SS":
                v = p["es"] + lag
            else:
                need = p["ef"] + lag
                if ff_min is None or need > ff_min:
                    ff_min, ff_link = need, l
                continue
            if v > es:
                es, driver = v, l
        ef = advance(es, d, cap)
        if ff_min is not None and ef < ff_min:
            es2 = max(es, retreat(ff_min, d, cap))
            if es2 > es:
                es, driver = es2, ff_link
            ef = max(advance(es, d, cap), ff_min)
        r[j] = {"es": es, "ef": ef, "driver": driver}
    finish = max((v["ef"] for v in r.values()), default=0)
    for j in reversed(order):
        a = by_id[j]
        cap = a.get("cap") or one
        d = float(a.get("effort") or 0.0)
        lf, ls_cap = finish, None
        for l in outof[j]:
            if by_id[l["to"]].get("pinned"):
                continue  # done work imposes no requirement (a contradiction is reported elsewhere)
            s, lag = r[l["to"]], int(l.get("lag") or 0)
            if l["type"] == "FS":
                lf = min(lf, s["ls"] - lag)
            elif l["type"] == "SS":
                ls_cap = s["ls"] - lag if ls_cap is None else min(ls_cap, s["ls"] - lag)
            else:
                lf = min(lf, s["lf"] - lag)
        ls = retreat(lf, d, cap)
        if ls_cap is not None and ls_cap < ls:
            ls = ls_cap
            lf = min(lf, advance(ls, d, cap))
        if a.get("pinned"):
            ls, lf = min(ls, 0), min(lf, 0) if lf < 0 else lf
        r[j].update({"ls": ls, "lf": lf, "tf": ls - r[j]["es"]})
    return r


def driving_path(res: Dict[str, Dict[str, Any]], end: str) -> List[str]:
    """From `end` back through each activity's driving predecessor, first
    activity first. Stops at the data date, a start constraint, or a done
    activity."""
    out, cur, seen = [], end, set()
    while cur and cur not in seen:
        seen.add(cur)
        out.append(cur)
        drv = res[cur]["driver"]
        cur = drv["from"] if isinstance(drv, dict) else None
    return list(reversed(out))


# ═══ ASSUMPTIONS ═════════════════════════════════════════════════════════════

def assumption(aid: str, label: str, unit: str, tag: str, fast: Any, normal: Any, cons: Any, *, faster: str,
               basis: str, sample: Optional[Dict[str, Any]] = None, stress: Any = None) -> Dict[str, Any]:
    """`stress` (default: `cons`) is the worst value, used only by the stress
    test; see `coherent_conservative` for how `conservative` is chosen."""
    if tag not in TAGS:
        raise ValueError(f"unknown assumption tag {tag!r}")
    if faster not in ("higher", "lower"):
        raise ValueError("faster must be 'higher' or 'lower'")
    out = {"id": aid, "label": label, "unit": unit, "tag": tag, "faster": faster,
           "values": {"fast": fast, "normal": normal, "conservative": cons,
                      STRESS: cons if stress is None else stress}, "basis": basis}
    if sample is not None:
        out["sample"] = sample
    return out


def monotone(a: Dict[str, Any]) -> bool:
    """fast is never slower than normal, normal never slower than
    conservative, conservative never slower than the stress test."""
    v = a["values"]
    keys = [k for k in ALL_RUNS if k in v]

    def ok(*xs):
        return all((x >= y) if a["faster"] == "higher" else (x <= y) for x, y in zip(xs, xs[1:]))
    if isinstance(v["normal"], dict):
        return all(ok(*[v[s][k] for s in keys]) for k in v["normal"])
    return ok(*[v[s] for s in keys])


#: CONSERVATIVE is ONE plausible adverse story, not every worst case at once:
CONSERVATIVE_STORY = ("A cold winter and slow agencies: exterior and sitework weather at the cold end, every DOB / "
                      "FDNY / DEP / DOT / TCO wait at its long end, one failed first attempt at the DOB electrical "
                      "final and the FDNY fire-alarm test (one extra cycle of that inspection), and trades not yet on "
                      "site mobilizing late. Crews, production rates, utility leads and unknown-scope shares stay at "
                      "normal.")
CONSERVATIVE_ADVERSE = ("weather_exterior", "weather_sitework", "lead_special", "lead_dob_electrical", "lead_fdny_fa",
                        "lead_dob_plumbing", "lead_dep_permit", "lead_dep_inspection", "lead_dot_permit",
                        "lead_gas_auth", "lead_tco", "lead_bpp", "reinspect_factor", "mobilization",
                        "lead_cabinet_delivery")
SCENARIO_STORIES = {
    "fast": "Crews at the highest day seen, short agency waits, a mild winter, unstarted trades on site at once.",
    "normal": "Crews at their average, the measured 7-working-day DOB wait, typical winter, 5-day mobilization.",
    "conservative": CONSERVATIVE_STORY,
    STRESS: "STRESS TEST, not a forecast: every assumption at its worst value simultaneously (crews at 80% of "
            "average, slowest rates, longest leads, worst weather, worst state shares).",
}


def coherent_conservative(assumptions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """conservative = the stress value for the adverse story's assumptions,
    the normal value for everything else."""
    for a in assumptions:
        v = a["values"]
        v.setdefault(STRESS, v["conservative"])
        if a["id"] in CONSERVATIVE_ADVERSE:
            v["conservative"] = v[STRESS]
        else:
            v["conservative"] = v["normal"]
    return assumptions


_MONTHS = range(1, 13)


def _weather(normal: Dict[int, float], step: float = 0.1, lo: float = 0.15, hi: float = 0.9) -> Tuple[dict, dict, dict]:
    fast = {m: round(min(hi, normal[m] + step), 2) for m in _MONTHS}
    cons = {m: round(max(lo, normal[m] - step), 2) for m in _MONTHS}
    return fast, dict(normal), cons


#: Workable fraction of a working day, by month, for exterior work.
_EXTERIOR = {1: 0.30, 2: 0.35, 3: 0.55, 4: 0.75, 5: 0.85, 6: 0.85, 7: 0.85, 8: 0.85, 9: 0.85, 10: 0.80,
             11: 0.60, 12: 0.40}
_SITEWORK = {1: 0.20, 2: 0.25, 3: 0.50, 4: 0.75, 5: 0.85, 6: 0.85, 7: 0.85, 8: 0.85, 9: 0.85, 10: 0.80,
             11: 0.55, 12: 0.30}
ENCLOSED_WEATHER = {m: 0.85 for m in _MONTHS}


def default_assumptions() -> List[Dict[str, Any]]:
    """The industry and regulatory assumptions, each with its basis. Measured
    ones are added by `measured_assumptions`."""
    IA, RG, DR = "industry-assumption", "regulatory", "drawing"
    A = assumption
    out = [
        # ── state treatment ──
        A("remaining_in_progress", "Share of scope left where a log reports the work in progress and nothing measures how much",
          "fraction", IA, 0.3, 0.5, 0.7, faster="lower",
          basis="no record states a percent; the range brackets 'mostly done' to 'mostly left'"),
        A("remaining_unknown", "Share of scope left where no record shows the work at all (state unknown)",
          "fraction", IA, 0.5, 1.0, 1.0, faster="lower",
          basis="absence of a record is not proof the work is not done; only the fast case credits half"),
        A("remaining_operator_done", "Share left where only an operator statement says it is done (not public)",
          "fraction", IA, 0.0, 0.0, 0.2, faster="lower",
          basis="conservative re-verifies an unverified operator statement"),
        A("remaining_inferred_done", "Share left where 'done' is an inference (e.g. later work closes over it)",
          "fraction", IA, 0.0, 0.0, 0.2, faster="lower",
          basis="an inference is never a fact; conservative leaves a fifth to re-open"),
        A("eifs_side_exposed_share", "Share of the side (lot-line) walls that is exposed and gets EIFS", "fraction",
          IA, 0.6, 0.8, 1.0, faster="lower",
          basis="neighbour 586 is a 2-storey brick with cellar (survey on ST T-001), so about 2 of 5 storeys on that "
                "side are covered; the other neighbour's height is not on the drawings"),
        A("facade_eifs_share", "Share of the exterior wall finished in EIFS/stucco (rest brick veneer)", "fraction",
          IA, 1.0, 1.0, 1.0, faster="lower",
          basis="NOT DETERMINABLE from the drawings (legend names brick and stucco; elevations carry no finish "
                "labels). Scenarios use 1.0 because the only facade trade on the roster or in any record is Stucco "
                "(J&P) and no mason appears; the branch 'facade_eifs_share' runs 0.5"),
        A("unknown_neighbour_storeys", "Storeys of the neighbour on the side the drawings do not describe",
          "storeys", IA, 2, 2, 2, faster="higher", stress=0,
          basis="only No. 586 is described (2-storey brick, Z-001); the other side is assumed alike; stress: no "
                "building there, the whole wall is exposed"),
        A("lead_adjoining_access", "Adjoining-owner licence and roof protection before scaffolding from a "
          "neighbour's roof", "working days", IA, 5, 15, 30, faster="lower", stress=60,
          basis="SSP-003/005 plan adjacent-roof protection; licence status unknown; stress: RPAPL 881 petition"),
        A("rate_brick", "Brick veneer on CFS (ties, flashing, brick)", "SF per worker-day", IA, 90, 75, 60,
          faster="higher", basis="mason output"),
        A("crew_masons", "Masons (none on the roster)", "workers", IA, 6, 4, 3, faster="higher",
          basis="no masonry sub on the roster"),
        A("window_avg_sf", "Average window opening deducted from the W1 walls", "SF", IA, 15, 15, 15, faster="higher",
          basis="window sizes are not determinable from the text layer; PTAC opening 5.5 SF each (A-100)"),
        # ── physical limits of this site ──
        A("sf_per_worker", "Floor plate per worker on one floor at once", "SF per worker", IA, 150, 200, 250,
          faster="lower", basis="2,497 SF plate (Z-001), 4 small units + corridor; working-room norm"),
        A("max_trades_per_floor", "Trades working one floor plate at once", "trades", IA, 5, 4, 3, faster="higher",
          basis="4 units of 256-508 SF NET per floor; more trades than units stack in the same rooms"),
        A("stair_carry_per_level", "Extra effort per level above floor 1 for hand-carried material", "fraction per level",
          IA, 0.03, 0.05, 0.08, faster="lower",
          basis="no elevator (GN-004/005); SSP-002 shows a hoist only 'when required by code' and a man-lift only "
                "while the superstructure was erected; windows are in, so board goes up the 2 stairs"),
        # ── production rates (per worker-day, 8 h) ──
        A("rate_framing", "CFS partition framing close-out (track, studs, blocking, door bucks, ceiling drops)",
          "LF partition per worker-day", IA, 25, 20, 15, faster="higher", basis="light-gauge partition framing norms"),
        A("rate_board_hang", "Gypsum board hang", "SF board per worker-day", IA, 600, 500, 400, faster="higher",
          basis="typical hanger-with-helper output on CFS"),
        A("rate_tape", "Tape and finish, 3 coats (level 4)", "SF board per worker-day", IA, 400, 320, 250,
          faster="higher", basis="taper output across all coats"),
        A("min_tape_days", "Tape and finish minimum per zone (coat drying)", "working days", IA, 4, 5, 6,
          faster="lower", basis="three coats with drying time; crew size does not shorten it"),
        A("rate_paint_prime", "Prime and first coat", "SF visible per worker-day", IA, 1800, 1400, 1100,
          faster="higher", basis="spray/roll production"),
        A("rate_paint_final", "Final coat and touch-up", "SF visible per worker-day", IA, 2000, 1600, 1200,
          faster="higher", basis="roll production"),
        A("rate_tile", "Bath floor tile + 6 in base (GN-001 note 23)", "baths per worker-day", IA, 1.6, 1.25, 1.0,
          faster="higher", basis="small bath floors, set and grout"),
        A("rate_flooring", "Vinyl plank flooring", "SF per worker-day", IA, 600, 500, 400, faster="higher",
          basis="floating plank production"),
        A("rate_cabinets", "Kitchenette cabinets", "kitchens per worker-day", IA, 1.33, 1.0, 0.8, faster="higher",
          basis="one small kitchen per installer-day"),
        A("rate_counters", "Quartz counters install", "kitchens per worker-day", IA, 2.5, 2.0, 1.33,
          faster="higher", basis="small kitchenette tops"),
        A("lag_counter_fab", "Counter template to install (fabrication)", "working days", IA, 7, 10, 15,
          faster="lower", basis="fabricator turnaround"),
        A("rate_doors", "Interior doors hung and cased", "doors per worker-day", IA, 8, 6, 4, faster="higher",
          basis="pre-hung doors in CFS openings"),
        A("rate_elec_rough", "Electrical rough", "GSF per worker-day", IA, 125, 100, 83, faster="higher",
          basis="multifamily rough, ~0.01 worker-day per GSF"),
        A("rate_elec_trim", "Electrical trim (devices, fixtures, panels)", "GSF per worker-day", IA, 250, 200, 167,
          faster="higher", basis="~0.005 worker-day per GSF"),
        A("rate_lv_rough", "Fire alarm / smoke-CO / low-voltage rough", "GSF per worker-day", IA, 625, 500, 400,
          faster="higher", basis="~0.002 worker-day per GSF"),
        A("rate_lv_trim", "Fire alarm / low-voltage devices", "GSF per worker-day", IA, 1250, 1000, 833,
          faster="higher", basis="~0.001 worker-day per GSF"),
        A("rate_sprinkler_rough", "NFPA 13R sprinkler branch piping", "GSF per worker-day", IA, 250, 200, 167,
          faster="higher", basis="residential 13R, ~0.005 worker-day per GSF"),
        A("rate_sprinkler_trim", "Sprinkler heads and escutcheons", "GSF per worker-day", IA, 1000, 833, 667,
          faster="higher", basis="concealed residential heads"),
        A("rate_duct", "Bath/kitchen exhaust and corridor duct rough", "fans per worker-day", IA, 2.0, 1.67, 1.33,
          faster="higher", basis="short exhaust runs to exterior"),
        A("rate_ptac_sleeve", "PTAC wall sleeve set, framed and flashed", "sleeves per worker-day", IA, 2.5, 2.0, 1.67,
          faster="higher", basis="through-wall sleeve in CFS opening"),
        A("rate_ptac_set", "PTAC unit set and connected", "units per worker-day", IA, 3.33, 2.5, 2.0,
          faster="higher", basis="plug-in units into installed sleeves"),
        A("rate_plumb_trim", "Plumbing fixture trim", "fixture groups per worker-day", IA, 2.0, 1.67, 1.25,
          faster="higher", basis="bath or kitchen group"),
        A("rate_insulation", "Wall insulation (spray foam / batts)", "SF per worker-day", IA, 700, 600, 500,
          faster="higher", basis="spray rig and batt production"),
        A("rate_eifs", "EIFS full system (board, base, mesh, finish)", "SF per worker-day", IA, 150, 120, 100,
          faster="higher", basis="EIFS applicator output, all coats"),
        A("rate_roofing", "Roofing (insulation, membrane, flashing)", "SF per worker-day", IA, 180, 150, 120,
          faster="higher", basis="low-slope membrane roof"),
        A("rate_coping", "Parapet and bulkhead coping/flashing", "LF per worker-day", IA, 60, 50, 40,
          faster="higher", basis="metal coping"),
        A("rate_windows", "Window set, blocked and sealed", "windows per worker-day", IA, 5, 4, 3, faster="higher",
          basis="residential casement units"),
        A("rate_firestop", "Firestopping penetrations and joints", "GSF per worker-day", IA, 1250, 1000, 800,
          faster="higher", basis="per-floor penetration density of a 4-storey walk-up"),
        A("rate_stairs", "Stair rails, guards and pan fill", "flight-levels per worker-day", IA, 0.6, 0.5, 0.4,
          faster="higher", basis="steel pan stairs with aluminum rails"),
        # ── fixed durations ──
        A("dur_punch_zone", "Punch and clean, per zone", "working days", IA, 3, 4, 6, faster="lower",
          basis="16 small units, 4 per floor"),
        A("dur_roof_mech", "Roof fan (SAF-1), duct heater (DH-1), curbs", "working days", IA, 4, 5, 7,
          faster="lower", basis="M-200 schedule items"),
        A("dur_hwh", "Gas water heater, recirculation pump, flue in the roof HWH room", "working days", IA, 4, 5, 7,
          faster="lower", basis="central DHW per P-400 and the gas change set"),
        A("dur_gas_test", "Gas piping final connections and pressure test", "working days", IA, 1, 2, 3,
          faster="lower", basis="single riser G-1"),
        A("dur_roof_drains", "Controlled-flow roof drains (blue-roof detention) set", "working days", IA, 2, 3, 4,
          faster="lower", basis="2 drains with 3 in detention (SD1-2)"),
        A("dur_ext_doors", "Exterior doors D1/D2", "working days", IA, 2, 2, 3, faster="lower",
          basis="3 doors (A-400 schedule)"),
        A("dur_service_equip", "Electrical service equipment (meter bank, main) in the 1st-floor electric room",
          "working days", IA, 5, 7, 10, faster="lower", basis="16 units + house"),
        A("dur_sprinkler_riser", "Sprinkler riser, combined-service connection, detector check", "working days", IA,
          4, 5, 7, faster="lower", basis="one riser on a 2 in combined service"),
        A("dur_backflow", "RPZ + double-check install and initial test filed", "working days", IA, 1, 2, 3,
          faster="lower", basis="DEP approval #25103445: initial test within 30 days"),
        A("dur_fa_pretest", "Fire-alarm panel programming and contractor pre-test", "working days", IA, 3, 4, 6,
          faster="lower", basis="FA-001..007 riser"),
        A("dur_tab", "Ventilation test and balance", "working days", IA, 2, 3, 5, faster="lower",
          basis="SAF-1 + EF-1/EF-2"),
        A("dur_dhw_startup", "Hot water start-up and recirculation balance", "working days", IA, 1, 2, 3,
          faster="lower", basis="central DHW"),
        A("dur_facade_light", "Facade LED strip under coping", "working days", IA, 1, 2, 3, faster="lower",
          basis="finishes package"),
        A("dur_sewer_conn", "House sewer drill-in connection and backfill", "working days", IA, 3, 4, 6,
          faster="lower", basis="concrete encasement sets 24 h before the core drill (SD1-2)"),
        A("dur_scaffold_strike", "Scaffold and sidewalk shed removal", "working days", IA, 3, 4, 6, faster="lower",
          basis="pipe scaffold + 8 ft shed along the frontage"),
        A("dur_sidewalk", "Sidewalk, curb and street tree (Builders Pavement Plan)", "working days", IA, 4, 5, 8,
          faster="lower", basis="BPP job 340915692"),
        A("dur_street_restore", "Street restoration over the sewer cut", "working days", IA, 1, 2, 3,
          faster="lower", basis="DOT restoration"),
        A("dur_paperwork", "Special/progress inspection reports compiled and filed", "working days", IA, 2, 3, 5,
          faster="lower", basis="TR1/TR8 close-out"),
        A("dur_permit_renewal", "Permit renewal filing", "working days", IA, 1, 1, 2, faster="lower",
          basis="DOB NOW renewal"),
        A("dur_hpd_cert", "HPD smoke/CO certification filed", "working days", IA, 1, 2, 3, faster="lower",
          basis="GN-001: certificate within 10 days of installation (LL 62/81)"),
        A("dur_tr1_closeout", "TR1 structural special inspection close-out (CFS, steel details, adjacent structure)",
          "working days", IA, 3, 5, 10, faster="lower", basis="S-001 special inspection table"),
        # ── inspection / agency / utility leads, request to result ──
        A("lead_special", "Special/progress inspector on call", "working days", IA, 1, 2, 5, faster="lower",
          basis="private agency availability"),
        A("lead_dob_electrical", "DOB electrical inspection request to result", "working days", IA, 5, 8, 15,
          faster="lower", basis="DOB NOW: Inspections Plus not read; no 588 sample"),
        A("lead_fdny_fa", "FDNY fire-alarm acceptance test request to test", "working days", IA, 10, 20, 40,
          faster="lower", basis="FDNY scheduling backlog; the operator's 'fire alarm dob scheduled' (2026-11-10) "
                                "has no date and is not public"),
        A("lead_dep_permit", "DEP site connection (sewer) permit after DOB detention certification", "working days",
          RG, 10, 20, 40, faster="lower",
          basis="DEP condition (SD1-2 p2): no connection permit until DOB certifies the roof detention; "
                "the duration is an assumption"),
        A("lead_dot_permit", "DOT street-opening permit for the sewer cut", "working days", IA, 3, 5, 10,
          faster="lower", basis="prior water/sewer opening permit B012026289B88 ran to 2026-11-01"),
        A("lead_dep_inspection", "DEP connection inspection", "working days", IA, 2, 5, 10, faster="lower",
          basis="DEP results are not public"),
        A("lead_gas_auth", "DOB gas authorization issued after the gas final", "working days", IA, 5, 10, 20,
          faster="lower", basis="DOB to utility notice"),
        A("lead_ng_service", "National Grid gas service line in place (from the data date)", "working days", IA,
          15, 35, 60, faster="lower", basis="status of the service request is unknown; DOT shows only gas REPAIR "
                                            "permits on house 588"),
        A("lead_ng_turn_on", "National Grid meter set and turn-on after authorization", "working days", IA, 5, 10, 20,
          faster="lower", basis="utility appointment"),
        A("lead_coned", "Con Ed permanent service ready to energize (from the data date)", "working days", IA,
          20, 40, 70, faster="lower", basis="application status unknown; electrical permit B01445590 (general "
                                            "wiring and service) issued 2026-08-13"),
        A("dur_coned_energize", "Con Ed energize and set meters", "working days", IA, 2, 3, 5, faster="lower",
          basis="utility appointment"),
        A("lead_tco", "DOB TCO review and inspection after the documents are complete", "working days", IA,
          10, 20, 40, faster="lower", basis="DOB NOW: CO workflow"),
        A("lead_bpp", "Builders Pavement Plan sign-off", "working days", IA, 10, 15, 30, faster="lower",
          basis="DOT/DOB BPP review"),
        A("reinspect_factor", "Extra request-to-result cycles on DOB electrical final, FDNY FA and TCO (a failed "
          "first attempt)", "cycles", IA, 0, 0, 1, faster="lower", basis="first-time pass rates are not measured"),
        A("mobilization", "Mobilization of a trade with no record on site yet", "working days", IA, 0, 5, 10,
          faster="lower", basis="sprinkler (Complete), low voltage (Voltec) and finish trades have no 588 record"),
        A("lead_cabinet_delivery", "Cabinet delivery", "working days", IA, 0, 10, 25, faster="lower",
          basis="order status unknown (Tafisa per SET_UPDATED)"),
        # ── crews with no 588 sample ──
        A("crew_tapers", "Tapers", "workers", IA, 6, 4, 3, faster="higher", basis="no taping sub on the roster"),
        A("crew_painters", "Painters", "workers", IA, 6, 4, 3, faster="higher", basis="no painter on the roster"),
        A("crew_tile", "Tile setters", "workers", IA, 3, 2, 2, faster="higher", basis="no tile sub on the roster"),
        A("crew_flooring", "Flooring installers", "workers", IA, 3, 2, 2, faster="higher",
          basis="no flooring sub on the roster"),
        A("crew_cabinets", "Cabinet/counter installers", "workers", IA, 3, 2, 2, faster="higher",
          basis="no millwork sub on the roster"),
        A("crew_carpenters", "Finish carpenters (doors/trim)", "workers", IA, 3, 2, 2, faster="higher",
          basis="no finish carpenter on the roster"),
        A("crew_firestop", "Firestop installers", "workers", IA, 3, 2, 2, faster="higher",
          basis="no firestop sub on the roster"),
        A("crew_sprinkler", "Sprinkler fitters (Complete, roster only)", "workers", IA, 4, 3, 2, faster="higher",
          basis="Complete is on the roster with no check-in"),
        A("crew_low_voltage", "FA / low-voltage techs (Voltec, roster only)", "workers", IA, 3, 2, 2,
          faster="higher", basis="Voltec is on the roster with no check-in"),
        A("crew_misc_metals", "Stair/rail ironworkers", "workers", IA, 3, 2, 2, faster="higher",
          basis="MQ Steel: 2-3 per day on 2 dated records (09-09, 10-13), too few to measure"),
        # ── shares of a measured crew ──
        A("share_arkon_board", "Share of the framers' crew hanging board while framing closes out", "fraction", IA,
          0.7, 0.6, 0.5, faster="higher", basis="assumes Arkon (Framers) also hangs board; no drywall sub on the roster"),
        A("share_arkon_framing", "Share of the framers' crew on framing close-out", "fraction", IA, 0.4, 0.4, 0.4,
          faster="higher", basis="the rest of the crew"),
        A("share_concurrent", "Share of a company's crew per concurrent activity family", "fraction", IA,
          0.5, 0.5, 0.5, faster="higher", basis="BreezCo runs duct rough and PTAC sleeves at once; split evenly"),
        # ── quantity readings ──
        A("wall_height_ft", "Wall height for board and insulation", "ft", DR, 9.0, 9.0, 9.0, faster="lower",
          basis="10 ft storey (levels 33.37..83.37) less joist depth and drops (operator rule 2026-11-08)"),
        A("ceiling_share", "Rated ceiling board as a share of the floor plate", "fraction", IA, 0.9, 0.9, 0.9,
          faster="lower", basis="1-hr ceiling (A-302) less stairs and shafts"),
        # ── weather ──
        A("weather_exterior", "Workable share of a working day for EIFS, roofing, coping, by month", "fraction",
          IA, *_weather(_EXTERIOR), faster="higher",
          basis="EIFS/roofing need >= 40 F and dry; approximate NYC climate normals, not site-measured"),
        A("weather_sitework", "Workable share of a working day for street/sidewalk concrete and asphalt, by month",
          "fraction", IA, *_weather(_SITEWORK), faster="higher",
          basis="cold-weather concrete and asphalt plant season; approximate NYC normals"),
        A("holidays", "Non-working days", "dates", IA, [], [], [], faster="lower",
          basis="Thanksgiving + day after, Christmas, New Year, Memorial Day, July 4 (observed), Labor Day"),
    ]
    hol = [date(2026, 11, 26), date(2026, 11, 27), date(2026, 12, 25), date(2027, 1, 1), date(2027, 5, 31),
           date(2027, 7, 5), date(2027, 9, 6)]
    out[-1]["values"] = {s: [d.isoformat() for d in hol] for s in ALL_RUNS}
    out[-1]["faster"] = "lower"
    return coherent_conservative(out)


# ═══ MEASURED FROM THE RECORDS ═══════════════════════════════════════════════

#: roster trade words -> role, first match wins ("Water Main" before "Plumb").
TRADE_ROLES: Tuple[Tuple[str, str], ...] = (
    ("water main", "site_utility"), ("framer", "framing"), ("electric", "electrical"), ("plumb", "plumbing"),
    ("hvac", "hvac"), ("mechanical", "hvac"), ("insulation", "insulation"), ("roof", "roofing"),
    ("stucco", "eifs"), ("eifs", "eifs"), ("window", "windows"), ("steel", "misc_metals"), ("iron", "misc_metals"),
    ("scaffold", "scaffold"), ("clean", "cleaning"), ("fire protection", "sprinkler"), ("sprinkler", "sprinkler"),
    ("low voltage", "low_voltage"), ("concrete", "concrete"),
)


def role_of(trade: Any) -> Optional[str]:
    t = str(trade or "").lower()
    for word, role in TRADE_ROLES:
        if word in t:
            return role
    return None


def _num(tok: str) -> Optional[float]:
    try:
        return float(tok)
    except ValueError:
        return None


def _period_end(f: Dict[str, Any]) -> str:
    p = str(f.get("period") or "")
    return p.split("..")[-1] if ".." in p else str(f.get("last") or "")


def _canon_company(name: str, roster: Sequence[str]) -> str:
    """'Arkon' -> 'Arkon Builders' when exactly one roster company starts with it."""
    n = (name or "").strip()
    hits = [c for c in roster if c == n or c.lower().startswith(n.lower() + " ")]
    return hits[0] if len(hits) == 1 else n


def original_ids(audit: Optional[Iterable[Dict[str, Any]]]) -> Optional[set]:
    """Record ids the records audit marks ORIGINAL and not a duplicate. None:
    no audit was given, so nothing can be called original."""
    if audit is None:
        return None
    return {f["rec_id"] for f in audit if f.get("is_original") and not f.get("dup_of")}


def measured_crews(records: Iterable[Dict[str, Any]], audit: Optional[Iterable[Dict[str, Any]]] = None
                   ) -> Dict[str, Dict[str, Any]]:
    """{company: {source, role, trade, avg, peak, days, ...}}.

    MEASURED (source "original") only from ORIGINAL filed daily-log crew rows
    (records/AUDIT.md: is_original and not a duplicate): per company and date
    the largest count printed that day (an amendment raises, never lowers, in
    these records), then the mean and the highest day over at least
    MIN_MEASURED_DAYS dates. Otherwise the report engine's period summary is
    used and labelled "derived_report" (a generated report, unaudited), with
    the original days kept beside it. A COUNT of people per day, never a rate."""
    records = list(records)
    orig = original_ids(audit)  # the audit's own duplicate flags (the README's duplicate_of is backwards in 23 of 25)
    roster: Dict[str, str] = {}
    for r in records:
        f = r.get("fields") or {}
        if f.get("kind") == "roster_row_trade_assignment" and r.get("company"):
            roster[r["company"].strip()] = r.get("trade") or ""
    per_day: Dict[str, Dict[str, Tuple[float, List[str]]]] = {}
    for r in records:
        if orig is None or r.get("id") not in orig:
            continue
        if r.get("type") != "daily_log_activity" or r.get("crew_count") is None or not r.get("date"):
            continue
        comp = _canon_company(r.get("company") or "", list(roster))
        if not comp or comp.lower().startswith("pending"):
            continue
        cur = per_day.setdefault(comp, {}).get(r["date"])
        n_ = float(r["crew_count"])
        ids = (cur[1] if cur else []) + [r["id"]]
        per_day[comp][r["date"]] = (max(n_, cur[0]) if cur else n_, ids)
    derived: Dict[str, Dict[str, Any]] = {}
    for r in records:
        f = r.get("fields") or {}
        comp = (r.get("company") or "").strip()
        if f.get("kind") != "sub_period_summary" or not comp or r.get("origin") == "assistant_claim"                 or r.get("duplicate_of"):
            continue
        avg = f.get("avg_workers", f.get("avg_per_day"))
        peak = f.get("peak", f.get("max"))
        days = f.get("days_on_site")
        if avg is None and f.get("raw_row"):
            toks = str(f["raw_row"]).split()[-5:]
            if len(toks) == 5:
                days, avg, peak = _num(toks[0]), _num(toks[2]), _num(toks[4])
        if avg is None or peak is None or not days:
            continue
        end = _period_end(f)
        cur = derived.get(comp)
        if cur is None or end > cur["period_end"]:
            derived[comp] = {"avg": float(avg), "peak": float(peak), "days": int(days), "period_end": end,
                             "period": f.get("period") or f"{f.get('first')}..{f.get('last')}", "ids": [r.get("id")]}
    out: Dict[str, Dict[str, Any]] = {}
    for comp in sorted(set(roster) | set(per_day) | set(derived)):
        days = per_day.get(comp, {})
        vals = [v[0] for _d, v in sorted(days.items())]
        entry: Dict[str, Any] = {"trade": roster.get(comp, ""), "role": role_of(roster.get(comp, "")),
                                 "original_days": len(vals),
                                 "original_values": {d: v[0] for d, v in sorted(days.items())},
                                 "derived": derived.get(comp)}
        if len(vals) >= MIN_MEASURED_DAYS:
            entry.update({"source": "original", "avg": round(sum(vals) / len(vals), 2), "peak": max(vals),
                          "days": len(vals), "period": f"{min(days)}..{max(days)}",
                          "ids": sorted(i for v in days.values() for i in v[1])})
        elif comp in derived:
            d = derived[comp]
            entry.update({"source": "derived_report", "avg": d["avg"], "peak": d["peak"], "days": d["days"],
                          "period": d["period"], "ids": d["ids"]})
        else:
            entry.update({"source": "none", "avg": None, "peak": None, "days": 0, "period": None, "ids": []})
        out[comp] = entry
    return out


def _working_days_between(a: date, b: date) -> int:
    """Working days after `a` up to and including `b` (Mon-Fri)."""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def measured_inspection_leads(inspections: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Request-to-result working days from the public inspection record:
    the DOB plumbing floor inspection (Pending -> Pass) and the
    self-certification advance notice (opened -> request)."""
    out: Dict[str, Any] = {}
    ins = inspections or {}
    for key, rec in ins.items():
        if not isinstance(rec, dict):
            continue
        for c in rec.get("completed_inspections") or []:
            hist = c.get("status_history") or []
            pend = next((h for h in hist if h and h[0] == "Pending"), None)
            res = next((h for h in hist if h and h[0] == "Pass"), None)
            if pend and res:
                a, b = date.fromisoformat(pend[2][:10]), date.fromisoformat(res[1][:10])
                out["dob_plumbing"] = {"working_days": _working_days_between(a, b), "requested": a.isoformat(),
                                       "resulted": b.isoformat(), "inspection": c.get("id"), "n": 1}
    for n in ins.get("advance_notices") or []:
        if n.get("opened") and n.get("request") and "self_cert" not in out:
            a, b = date.fromisoformat(n["opened"][:10]), date.fromisoformat(n["request"][:10])
            out["self_cert"] = {"working_days": _working_days_between(a, b), "opened": a.isoformat(),
                                "requested": b.isoformat(), "record": n.get("record"), "n": 1}
    return out


def measured_assumptions(crews: Dict[str, Dict[str, Any]], leads: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for comp, c in sorted(crews.items()):
        if not c.get("avg"):
            continue
        avg, peak = c["avg"], max(c["peak"], c["avg"])
        if c["source"] == "original":
            tag, label = "measured", f"Crew size, {comp} ({c['trade'] or 'trade not on roster'})"
            basis = (f"ORIGINAL filed daily-log crew rows on {c['days']} dates ({c['period']}): mean {avg:g}, highest "
                     f"{peak:g} (rows {', '.join(c['ids'][:12])}{' ...' if len(c['ids']) > 12 else ''})")
        else:
            tag = "derived-report"
            label = f"Crew size, {comp} ({c['trade'] or 'trade not on roster'}) - derived-report figure (unaudited)"
            basis = (f"generated report period summary {c['period']} (rows {', '.join(c['ids'])}): {avg:g} per day "
                     f"present over {c['days']} days, highest {peak:g}; NOT an original record. Original filed "
                     f"crew rows: {c['original_days']} date(s) {c['original_values'] or ''}")
        out.append(assumption(
            crew_id(comp), label, "workers on site per day present", tag, peak, avg, avg, faster="higher",
            stress=round(max(1.0, 0.8 * avg), 2),
            basis=basis + ". fast = highest day, normal and conservative = mean, stress = 80% of the mean",
            sample={"n_days": c["days"], "period": c["period"], "record_ids": c["ids"], "source": c["source"]}))
    pl = leads.get("dob_plumbing")
    if pl:
        w = pl["working_days"]
        out.append(assumption(
            "lead_dob_plumbing", "DOB plumbing / sprinkler / gas inspection request to result", "working days",
            "measured", max(1, w - 2), w, w + 5, faster="lower",
            basis=(f"inspection {pl['inspection']} (public DOB NOW record, hand-verified): requested (Pending) "
                   f"{pl['requested']}, resulted {pl['resulted']} = {w} working days; n=1, so fast/conservative are "
                   "+-assumptions around it; reused for sprinkler and gas finals (no sample of their own)"),
            sample={"n": 1, "inspection": pl["inspection"]}))
    return out


def crew_id(company: str) -> str:
    return "crew_" + re.sub(r"[^a-z0-9]+", "_", company.lower()).strip("_")


# ═══ BUILDING FACTS (from the drawings lane's building.json) ════════════════

_ZONE_KEYS = (("FIRST", "L1", "Floor 1", 1), ("SECOND", "L2", "Floor 2", 2), ("THIRD", "L3", "Floor 3", 3),
              ("FOURTH", "L4", "Floor 4", 4), ("FIFTH", "L5", "Floor 5", 5), ("SIXTH", "L6", "Floor 6", 6),
              ("MEZZANINE", "MEZ", "Mezzanine", 99))
#: Board faces per LF of wall, by A-500 type: exterior W types are boarded on
#: the inside only; 2-hr partitions carry 2 layers each side.
BOARD_FACES = {"W1": 1, "W2": 1, "P1": 4, "P2": 4, "P3": 2, "P4": 3, "P5": 3, "P6": 4, "untyped": 2}
PAINT_FACES = {"W1": 1, "W2": 1, "P1": 2, "P2": 2, "P3": 2, "P4": 1, "P5": 1, "P6": 2, "untyped": 2}
EXTERIOR_TYPES = ("W1", "W2")


def _val(node: Any) -> Any:
    return node.get("value") if isinstance(node, dict) and "value" in node else node


def _strings(o: Any) -> Iterable[str]:
    if isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)
    elif isinstance(o, str):
        yield o


def _floats(s: Any) -> List[float]:
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(s or ""))]


def facts_from_building(b: Dict[str, Any]) -> Dict[str, Any]:
    """Zones, quantities and systems the network is built from. Every number
    keeps its drawing basis; anything derived says how."""
    dq = _val(b.get("derived_quantities_per_floor")) or {}
    zones = []
    for key, zid, label, order in _ZONE_KEYS:
        z = dq.get(key)
        if not isinstance(z, dict):
            continue
        zones.append({"id": zid, "label": label, "order": order, "gross_sf": float(z.get("slab_gross_sf") or 0),
                      "units": int(z.get("units") or 0), "baths": int(z.get("baths") or 0),
                      "kitchens": int(z.get("kitchenettes") or 0),
                      "apt_net_sf": [float(x) for x in z.get("apartment_net_sf") or []],
                      "wall_lf": {k: float(v) for k, v in (z.get("wall_LF_filed") or {}).items()},
                      "notes": [n for n in [z.get("notes")] if n]})
    zones.sort(key=lambda z: z["order"])
    warnings = []
    full = [z for z in zones if z["id"] != "MEZ"]
    ref = max(full, key=lambda z: (z["gross_sf"], sum(z["wall_lf"].values()))) if full else None
    for z in zones:
        z["lf_source"] = "drawing"
        if ref and z is not ref and z["gross_sf"] < 0.5 * ref["gross_sf"] \
                and sum(z["wall_lf"].values()) >= 0.9 * sum(ref["wall_lf"].values()):
            k = z["gross_sf"] / ref["gross_sf"]
            z["wall_lf_drawing"] = dict(z["wall_lf"])
            z["wall_lf"] = {t: round(v * k, 1) for t, v in ref["wall_lf"].items()}
            z["lf_source"] = f"scaled from {ref['label']} by floor area ({k:.3f}); drawn LF looks inflated"
            warnings.append(f"{z['label']}: drawn wall LF ({sum(z['wall_lf_drawing'].values()):.0f}) is about "
                            f"{ref['label']}'s on {z['gross_sf']:.0f} SF; quantities use {z['lf_source']}")
    bld = dq.get("BUILDING") or {}
    roof = dq.get("ROOF") or {}
    fpe = b.get("fire_protection_electrical_vertical") or {}
    plumb = b.get("plumbing") or {}
    sprk = str(_val(fpe.get("sprinkler")) or "")
    stand = str(_val(fpe.get("standpipe")) or "")
    gas = str(_val(plumb.get("gas")) or "")
    hold = _val((b.get("site_safety_soe") or {}).get("sewer_connection_hold"))
    other = _val((b.get("inspections") or {}).get("other_third_party_gates")) or []
    det_text = " ".join(str(x) for x in ([hold] + list(other)))
    project = str(_val((b.get("project_type") or {}).get("classification")) or "")
    roof_vals = _floats(roof.get("roof_gross_sf"))
    bulk_vals = _floats(roof.get("bulkhead_gross_sf"))
    footprint = roof_vals[0] if roof_vals else (ref["gross_sf"] if ref else 0.0)
    perimeter = 0.0
    if ref:
        perimeter = sum(ref["wall_lf"].get(t, 0.0) for t in EXTERIOR_TYPES)
    dw = bld.get("door_window_totals_filed") or {}
    doors = sum(int(v) for k, v in dw.items() if re.fullmatch(r"[A-Z]", k))
    ext_doors = sum(int(v) for k, v in dw.items() if re.fullmatch(r"D\d", k))
    windows = sum(int(v) for k, v in dw.items() if re.fullmatch(r"W\d", k))
    n_levels_ext = len(zones)
    neighbours = []
    for txt in _strings(b):
        for m in re.finditer(r'Neighbou?r No\.\s*(\d+)\s+is\s+"?(\d+)\s+STOR', txt, re.I):
            nb = {"number": m.group(1), "storeys": int(m.group(2))}
            if nb not in neighbours:
                neighbours.append(nb)
    return {
        "neighbours": neighbours,
        "zones": zones,
        "systems": {
            "sprinkler": "sprinkler" in sprk.lower() and "wet" in sprk.lower(),
            "standpipe": bool(stand) and not stand.lower().startswith("none"),
            "gas": "gas" in gas.lower() and ("meter" in gas.lower() or "riser" in gas.lower()),
            "elevator": int(bld.get("elevators") or 0) > 0,
            "roof_detention": "detention" in det_text.lower(),
            "cellar": "cellar" in " ".join(z["id"] for z in zones).lower(),
        },
        "building": {"units": int(bld.get("units") or sum(z["units"] for z in zones)),
                     "ptacs": int(bld.get("ptacs") or 0), "stairs": int(bld.get("stairs") or 0),
                     "elevators": int(bld.get("elevators") or 0), "doors": doors, "ext_doors": ext_doors,
                     "windows": windows, "footprint_sf": footprint,
                     "bulkhead_sf": max(bulk_vals) if bulk_vals else 0.0,
                     "exterior_lf_per_level": perimeter, "levels_with_facade": n_levels_ext,
                     "project": project[:160]},
        "warnings": warnings,
    }


def zone_quantities(z: Dict[str, Any], height: float, ceiling_share: float) -> Dict[str, Any]:
    lf = z["wall_lf"]
    board = sum(v * BOARD_FACES.get(t, 2) for t, v in lf.items()) * height + z["gross_sf"] * ceiling_share
    paint = sum(v * PAINT_FACES.get(t, 2) for t, v in lf.items()) * height + z["gross_sf"] * ceiling_share
    partitions = sum(v for t, v in lf.items() if t not in EXTERIOR_TYPES)
    ext = sum(lf.get(t, 0.0) for t in EXTERIOR_TYPES)
    demising = lf.get("P1", 0.0) + lf.get("P2", 0.0)
    floor_sf = sum(z["apt_net_sf"]) * 0.85 + z["gross_sf"] * 0.10 if z["apt_net_sf"] else z["gross_sf"] * 0.75
    return {"board_sf": round(board), "paint_sf": round(paint), "partition_lf": round(partitions, 1),
            "insulation_sf": round((ext + demising) * height), "floor_sf": round(floor_sf),
            "fans": z["baths"] + z["kitchens"], "fixture_groups": z["baths"] + z["kitchens"]}


# ═══ STATE ═══════════════════════════════════════════════════════════════════

def state_entry(status: str, evidence: str, basis: str, *, sources: Sequence[str] = (),
                man_days: Optional[float] = None) -> Dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    if evidence not in EVIDENCE:
        raise ValueError(f"unknown evidence category {evidence!r}")
    out = {"status": status, "evidence": evidence, "basis": basis, "sources": list(sources)}
    if man_days is not None:
        out["man_days"] = round(float(man_days), 1)
    return out


DEFAULT_STATE = state_entry("unknown", "no_record", "no record of this work was read")


def remaining_fraction(st: Dict[str, Any], scn: str, A: Callable[[str, str], Any], *, qty: Optional[float] = None,
                       rate: Optional[float] = None, gate: bool = False) -> Tuple[float, str]:
    """(share of the scope left, how it was decided). A gate or lead is passed
    or not: anything short of done leaves all of it."""
    s, ev = st["status"], st["evidence"]
    if s == "done" and gate and ev != "verified_public_record":
        return 1.0, f"pass not verified ({ev}): an inferred or reported pass is never a passed inspection; pending"
    if s == "done":
        if ev == "operator_statement":
            return float(A("remaining_operator_done", scn)), "done per an operator statement only"
        if ev == "inferred" and not gate:
            return float(A("remaining_inferred_done", scn)), "done by inference only"
        return 0.0, f"done ({ev})"
    if gate or s == "not_started":
        return 1.0, s
    if s == "in_progress":
        md = st.get("man_days")
        if md and qty and rate:
            left = max(MIN_REMAINING, 1.0 - md * rate / qty)
            return round(left, 3), (f"ESTIMATE of work in place: {md:g} man-days (derived-report figure, unaudited) "
                                    f"x assumed rate {rate:g} / {qty:g}; at least {MIN_REMAINING:g} left")
        return float(A("remaining_in_progress", scn)), "in progress, amount unmeasured"
    return float(A("remaining_unknown", scn)), "state unknown"


# ═══ NETWORK ═════════════════════════════════════════════════════════════════

class _Net:
    def __init__(self) -> None:
        self.acts: List[Act] = []
        self.links: List[Link] = []
        self._ids: set = set()
        self.skipped: List[Tuple[str, str]] = []

    def act(self, aid: str, name: str, kind: str, **kw: Any) -> Act:
        if aid in self._ids:
            raise ValueError(f"duplicate activity {aid}")
        self._ids.add(aid)
        a = {"id": aid, "name": name, "kind": kind, "zone": kw.pop("zone", None), "family": kw.pop("family", aid)}
        a.update(kw)
        self.acts.append(a)
        return a

    def has(self, aid: str) -> bool:
        return aid in self._ids

    def link(self, a: str, b: str, kind: str, why: str, *, type: str = "FS", lag: Any = 0,
             scenarios: Sequence[str] = ALL_RUNS, basis: Optional[str] = None) -> None:
        """`basis`: a code section, a drawing note, or 'physical: ...'. A link
        to an activity this building does not have is skipped and recorded."""
        if a not in self._ids or b not in self._ids:
            self.skipped.append((a, b))
            return
        if kind not in LINK_KINDS or type not in LINK_TYPES:
            raise ValueError(f"bad link {a}->{b}: {kind}/{type}")
        if basis is None:
            basis = {"resource": "crew continuity: one crew, one place at a time",
                     "overlap": "physical: the next trade starts once the first area is ready"}.get(kind,
                                                                                                   f"physical: {why}")
        self.links.append({"from": a, "to": b, "type": type, "lag": lag, "kind": kind, "why": why,
                           "basis": basis, "scenarios": list(scenarios)})


def _crew(role_company: Dict[str, str], role: str, fallback: str) -> Tuple[str, Optional[str]]:
    comp = role_company.get(role)
    return (crew_id(comp), comp) if comp else (fallback, None)


COVER_BASIS = "BC 110.3 / 1704: work is inspected before it is covered"


def build_network(facts: Dict[str, Any], role_company: Dict[str, str], measured_ids: set) -> Dict[str, Any]:
    """Activities and links for THIS building. `role_company`: role -> the
    company the roster assigns it; `measured_ids`: crew assumptions that hold a
    measured value (others fall back to industry crews + mobilization)."""
    n = _Net()
    S = facts["systems"]
    B = facts["building"]
    zones = facts["zones"]
    zids = [z["id"] for z in zones]
    H, CS = 9.0, 0.9

    def crew(role: str, fallback: str) -> Dict[str, Any]:
        cid, comp = _crew(role_company, role, fallback)
        if cid not in measured_ids:
            cid = fallback
        return {"crew": cid, "company": comp, "mobilize": cid not in measured_ids}

    def work(aid, name, zone, family, qty, unit, rate, c, *, share=None, weather=None, min_days=None, trade=None,
             basis=""):
        return n.act(aid, name, "work", zone=zone, family=family, trade=trade or family,
                     scope={"quantity": qty, "unit": unit, "basis": basis}, rule="production", rate=rate,
                     crew=c["crew"], company=c["company"], share=share, weather=weather, min_days=min_days,
                     mobilize=c["mobilize"])

    def fixed(aid, name, kind, zone, family, dur, *, c=None, weather=None, authority=None, gate_of=None, basis="",
              trade=None, deadline=None):
        return n.act(aid, name, kind, zone=zone, family=family, trade=trade, rule="fixed", dur=dur,
                     crew=(c or {}).get("crew"), company=(c or {}).get("company"),
                     mobilize=bool(c and c["mobilize"]), weather=weather, authority=authority,
                     gate_of=gate_of or [], scope={"quantity": None, "unit": None, "basis": basis},
                     deadline=deadline)

    def gate(aid, name, zone, family, lead, authority, gate_of, *, basis="", extra=None):
        return n.act(aid, name, "inspection_gate", zone=zone, family=family, trade=None, rule="lead", lead=lead,
                     reinspect=extra, authority=authority, gate_of=gate_of, crew=None, company=None,
                     mobilize=False, scope={"quantity": None, "unit": None, "basis": basis})

    framer = crew("framing", "crew_carpenters")
    elec = crew("electrical", "crew_low_voltage")
    plumber = crew("plumbing", "crew_sprinkler")
    hvac = crew("hvac", "crew_carpenters")
    insul = crew("insulation", "crew_carpenters")
    roofer = crew("roofing", "crew_carpenters")
    eifs = crew("eifs", "crew_carpenters")
    windows = crew("windows", "crew_carpenters")
    metals = crew("misc_metals", "crew_misc_metals")
    site = crew("site_utility", "crew_sprinkler")
    scaffold = crew("scaffold", "crew_carpenters")
    sprk = crew("sprinkler", "crew_sprinkler")
    lv = crew("low_voltage", "crew_low_voltage")
    simple = {r: {"crew": f"crew_{r}", "company": None, "mobilize": True}
              for r in ("tapers", "painters", "tile", "flooring", "cabinets", "carpenters", "firestop")}

    # ── completed scope (kept so the network is the whole building) ──
    fixed("demolition", "Full demolition of the old 2-storey house", "work", "SITE", "demolition", None,
          basis="demolition filing B01075600")
    fixed("soe_excavation", "Excavation and support of excavation", "work", "SITE", "excavation_soe", None,
          basis="SOE filing B01141294-S8")
    fixed("foundation_sog", "Footings, foundation walls, 6 in slab on grade", "work", "FOUNDATION", "foundation",
          None, basis="S-101 6 in SOG; footings top 29.37 (SSP-004)")
    fixed("plumbing_underground", "Underground sanitary/storm + water, floor 1", "work", "FOUNDATION",
          "plumbing_underground", None, basis="P-200")
    gate("gate_plumbing_underground", "Plumbing underground inspection (WS + ST), floor 1", "FOUNDATION",
         "gate_plumbing_underground", "lead_dob_plumbing", "DOB (self-cert + spot check)", ["plumbing_underground"])
    fixed("cfs_superstructure", "CFS bearing walls, 8J12/10J12 joists @16 in, USG panel subfloor, SW1-7 braced "
          "frames, all levels to roof", "work", "STRUCTURE", "superstructure", None,
          basis="S-102..S-106 (CFS); no cast-in-place deck above the SOG")
    n.link("demolition", "soe_excavation", "prerequisite", "a lot is cleared before it is dug")
    n.link("soe_excavation", "foundation_sog", "prerequisite", "dug before founded")
    n.link("foundation_sog", "plumbing_underground", "overlap", "under-slab piping is set in the foundation phase",
           type="SS")
    n.link("plumbing_underground", "gate_plumbing_underground", "prerequisite", "inspect before the slab covers it")
    n.link("foundation_sog", "cfs_superstructure", "prerequisite", "frame bears on the foundation")
    if True:  # site utilities exist on every new building with a service
        fixed("building_sewer_sleeve", "Building sewer sleeve through foundation wall (combination Y)", "work",
              "FOUNDATION", "site_utilities", None, basis="advance notice ADV-PL-26-014303")
        fixed("water_service", "2 in combined water service (domestic + fire) from the 8 in main", "work", "SITE",
              "site_utilities", None, basis="SP-001 new 2 in combined service")
        n.link("foundation_sog", "building_sewer_sleeve", "prerequisite", "sleeve is cast through the wall")

    plumb_rough_levels = zids + ["ROOF"]
    for z in plumb_rough_levels:
        fixed(f"plumbing_rough_{z}", f"Plumbing rough (WS, storm{', gas' if S['gas'] else ''}), {z}", "work", z,
              "plumbing_rough", None, basis="P-201..P-207 stacks")
        gate(f"gate_plumbing_rough_{z}", f"DOB plumbing rough inspection, {z}", z, "gate_plumbing_rough",
             "lead_dob_plumbing", "DOB", [f"plumbing_rough_{z}"])
        n.link("cfs_superstructure", f"plumbing_rough_{z}", "prerequisite", "rough-in runs in the framed walls")
        n.link(f"plumbing_rough_{z}", f"gate_plumbing_rough_{z}", "prerequisite", "inspect what was roughed")

    # ── envelope ──
    roof_sf = B["footprint_sf"] + B["bulkhead_sf"]
    work("roofing", "Roofing: insulation, membrane, flashing (roof + bulkheads)", "ROOF", "roofing", round(roof_sf),
         "SF", "rate_roofing", roofer, weather="weather_exterior",
         basis=f"footprint {B['footprint_sf']:g} SF + bulkhead {B['bulkhead_sf']:g} SF (8.18.26 roof; C8/C9 open)")
    n.link("cfs_superstructure", "roofing", "prerequisite", "membrane goes on the roof deck")
    coping_lf = round(B["exterior_lf_per_level"] + 4 * math.sqrt(max(B["bulkhead_sf"], 1.0)))
    work("roof_coping", "Parapet (42 in) and bulkhead coping and flashing", "ROOF", "roofing", coping_lf, "LF",
         "rate_coping", roofer, weather="weather_exterior",
         basis="exterior wall LF per level (W1+W2) + bulkhead perimeter from its area")
    n.link("roofing", "roof_coping", "prerequisite", "coping laps the membrane flashing")
    if S["roof_detention"]:
        fixed("roof_drains_detention", "Controlled-flow roof drains, blue-roof detention (425 cf)", "work", "ROOF",
              "roof_detention", "dur_roof_drains", c=plumber, basis="SD1-2: 2 drains at 3 in detention")
        n.link("roofing", "roof_drains_detention", "prerequisite", "drains are set in the finished membrane")
    work("windows", "Windows W1/W2/W3 set, blocked, vapour barrier", "ENVELOPE", "windows",
         B["windows"], "windows", "rate_windows", windows, basis="A-400 window schedule, filed counts")
    n.link("cfs_superstructure", "windows", "prerequisite", "windows go in framed openings")
    fixed("exterior_doors", "Exterior doors D1/D2", "work", "ENVELOPE", "exterior_doors", "dur_ext_doors",
          c=windows, basis=f"{B['ext_doors']} doors (A-400)")
    n.link("cfs_superstructure", "exterior_doors", "prerequisite", "framed openings")
    gate("gate_tr8_fenestration", "TR8 IIA3-IIA5: fenestration U-factor/rating, air leakage, areas", "ENVELOPE",
         "gate_tr8", "lead_special", "Progress inspector (TR8)", ["windows", "exterior_doors"],
         basis="GN-001 TR8 list; labels must still be on the units")
    n.link("windows", "gate_tr8_fenestration", "prerequisite", "inspect installed, labelled units")
    n.link("exterior_doors", "gate_tr8_fenestration", "prerequisite", "doors are fenestration")

    total_gsf = sum(z["gross_sf"] for z in zones) or 1.0
    ptacs = B["ptacs"]
    for z in zones:
        z["ptacs"] = round(ptacs * z["gross_sf"] / total_gsf) if ptacs else 0
    if ptacs and zones:
        drift = ptacs - sum(z["ptacs"] for z in zones)
        zones[0]["ptacs"] += drift

    h = H
    eifs_ids: List[str] = []
    ext_lf = B["exterior_lf_per_level"]
    if ext_lf and zones:
        ref = max((z for z in zones if z["id"] != "MEZ"), key=lambda z: z["gross_sf"])
        w1 = ref["wall_lf"].get("W1", 0.0)
        w2 = ref["wall_lf"].get("W2", 0.0)
        levels = facts["building"]["levels_with_facade"]
        height = levels * 10.0 + 3.5  # 10 ft storeys + 42 in parapet
        known = facts["neighbours"]
        elev = []  # (id, label, quantity basis dict, ptac wall, neighbour)
        if w2:
            side = w2 / 2.0
            if known:
                nb = known[0]
                elev.append(("side_known", f"Lot-line side wall above neighbour No. {nb['number']} "
                             f"({nb['storeys']}-storey)", {"lf": side, "height": height, "covered_storeys": nb["storeys"]},
                             False, nb))
            elev.append(("side_other", "Lot-line side wall above the other neighbour (height not on the drawings)",
                         {"lf": side, "height": height, "covered_storeys": "unknown_neighbour_storeys"}, False, None))
        if w1:
            elev.append(("front_rear", "Front and rear (W1 walls: windows and PTAC sleeves)",
                         {"lf": w1, "height": height, "covered_storeys": 0, "openings": True, "windows": B["windows"], "ptacs": B["ptacs"]}, True, None))
        bulk_lf = 4 * math.sqrt(B["bulkhead_sf"]) if B["bulkhead_sf"] else 0.0
        if bulk_lf:
            elev.append(("bulkhead", "Stair/mechanical bulkhead walls (worked from the roof)",
                         {"lf": bulk_lf, "height": 10.0, "covered_storeys": 0}, False, None))
        prev = None
        for eid, label, qb, has_ptac, nb in elev:
            gate(f"gate_air_barrier_{eid}", f"TR8 IIA6 air/water barrier visual before cladding, {eid}", "ENVELOPE",
                 "gate_tr8", "lead_special", "Progress inspector (TR8)", [f"eifs_{eid}"], basis="GN-001 TR8 IIA6")
            n.link("windows", f"gate_air_barrier_{eid}", "prerequisite", "window perimeters sealed to the air barrier",
                   basis="TR8 IIA6 (GN-001): the barrier is inspected complete, including its seals at openings")
            gross = qb["lf"] * qb["height"]
            work(f"eifs_{eid}", f"EIFS: {label}", "ENVELOPE", "eifs", round(qb["lf"] * (qb["height"] - 10.0 * qb[
                "covered_storeys"])) if isinstance(qb["covered_storeys"], int) else round(gross), "SF", "rate_eifs",
                 eifs, weather="weather_exterior",
                 basis=("wall LF x exposed height (covered storeys of the neighbour removed); the finish split is "
                        "not determinable from the drawings (building.json not_determinable), so the EIFS share is "
                        "an assumption with a branch"))
            n.acts[-1]["qty_rule"] = dict(qb, kind="facade")
            n.acts[-1]["qty_factor"] = ["facade_eifs_share"]
            n.link(f"gate_air_barrier_{eid}", f"eifs_{eid}", "prerequisite", "EIFS covers the air barrier",
                   basis="TR8 IIA6 + BC 1704.13: the barrier is seen before EIFS covers it")
            if eid.startswith("side_"):
                fixed(f"adjoining_roof_access_{eid[5:]}", f"Adjoining-owner access + roof protection for the {label}",
                      "regulatory", "SITE", "adjoining_access", "lead_adjoining_access",
                      basis="SSP-003/005 show adjacent-building roof protection; access to a neighbour's roof needs "
                            "the owner's licence (RPAPL 881 if refused)")
                n.link(f"adjoining_roof_access_{eid[5:]}", f"eifs_{eid}", "prerequisite",
                       "the lot-line wall above the neighbour is reached only from its roof",
                       basis="physical: 0 ft side yards (Z-003), lot ~10 in wider than the building; BC 3309 "
                             "protection of adjoining property")
            for r in ("renew_permit_shed", "renew_permit_scaffold"):
                n.link(r, f"eifs_{eid}", "prerequisite", "facade worked from the permitted scaffold/shed",
                       basis="AC 28-105: the scaffold and shed stay under a valid permit while in use")
            if prev:
                n.link(prev, f"eifs_{eid}", "resource", "one EIFS crew moves elevation to elevation")
            prev = f"eifs_{eid}"
            eifs_ids.append(f"eifs_{eid}")
        work("brick_veneer", "Brick veneer where the facade is brick, not EIFS (split not determinable)", "ENVELOPE",
             "brick_veneer", round(sum(e[2]["lf"] * e[2]["height"] for e in elev)), "SF", "rate_brick",
             {"crew": "crew_masons", "company": None, "mobilize": True}, weather="weather_exterior",
             basis="legend names brick and stucco, elevations carry no finish labels; quantity x (1 - EIFS share)")
        n.acts[-1]["qty_factor"] = ["1-facade_eifs_share"]
        n.link("gate_air_barrier_front_rear", "brick_veneer", "prerequisite", "veneer covers the air barrier",
               basis="TR8 IIA6: the barrier is seen before it is covered")
    if eifs_ids:
        gate("gate_eifs_special", "EIFS special inspection close-out (BC 1704.13)", "ENVELOPE", "gate_special",
             "lead_special", "Special inspector (TR1)", eifs_ids, basis="GN-001")
        for e in eifs_ids:
            n.link(e, "gate_eifs_special", "prerequisite", "close-out covers every elevation",
                   basis="BC 1704.13 special inspection of EIFS (GN-001)")
        fixed("facade_lighting", "Facade LED strip under the coping", "work", "ENVELOPE", "facade_lighting",
              "dur_facade_light", c=elec)
        n.link("eifs_front_rear", "facade_lighting", "prerequisite", "fixtures mount on the finished front facade")
        n.link("brick_veneer", "facade_lighting", "prerequisite", "fixtures mount on the finished facade")
        n.link("roof_coping", "facade_lighting", "prerequisite", "strip mounts under the coping")
    gate("gate_air_barrier_test", "TR8 IIA7 whole-building air barrier test", "ENVELOPE", "gate_tr8", "lead_special",
         "Progress inspector (TR8)", ["envelope"], basis="GN-001 TR8 IIA7")
    for a_ in eifs_ids + ["brick_veneer", "windows", "exterior_doors", "roof_coping"]:
        n.link(a_, "gate_air_barrier_test", "prerequisite", "the test needs the whole envelope closed",
               basis="TR8 IIA7 (GN-001): a whole-building test of the closed envelope")

    # ── stairs ──
    if B["stairs"]:
        flights = B["stairs"] * (len(zones))
        work("stairs_complete", f"Stairs A/B: rails, guards, pan fill ({B['stairs']} stairs)", "STAIRS", "stairs",
             flights, "flight-levels", "rate_stairs", metals, basis="GN-004/005: 2 exit stairs, no elevator")
        n.link("cfs_superstructure", "stairs_complete", "prerequisite", "stairs hang off the frame")

    # ── per-zone interior ──
    prev_by_family: Dict[str, str] = {}

    def chain(family: str, aid: str, why: str) -> None:
        p = prev_by_family.get(family)
        if p:
            n.link(p, aid, "resource", why)
        prev_by_family[family] = aid

    for z in zones:
        q = zone_quantities(z, h, CS)
        zid = z["id"]
        z["quantities"] = q
        work(f"framing_close_{zid}", f"Interior framing close-out (partitions, blocking, ceiling drops), {z['label']}",
             zid, "framing", q["partition_lf"], "LF", "rate_framing", framer, share="share_arkon_framing",
             basis=f"partition LF by A-500 type ({z['lf_source']})")
        n.link("cfs_superstructure", f"framing_close_{zid}", "prerequisite", "partitions inside the frame")
        chain("framing", f"framing_close_{zid}", "framers move floor to floor")
        work(f"elec_rough_{zid}", f"Electrical rough, {z['label']}", zid, "elec_rough", z["gross_sf"], "GSF",
             "rate_elec_rough", elec, basis="floor plate")
        work(f"lv_rough_{zid}", f"Fire alarm / smoke-CO / low-voltage rough, {z['label']}", zid, "lv_rough",
             z["gross_sf"], "GSF", "rate_lv_rough", lv, basis="FA-001..007 (devices in units, baths, corridors)")
        if S["sprinkler"]:
            work(f"sprinkler_rough_{zid}", f"NFPA 13R sprinkler rough, {z['label']}", zid, "sprinkler_rough",
                 z["gross_sf"], "GSF", "rate_sprinkler_rough", sprk, basis="SP-001..004")
        work(f"duct_rough_{zid}", f"Exhaust/corridor duct rough (EF-1, EF-2), {z['label']}", zid, "duct_rough",
             q["fans"] + (1 if z["units"] else 0), "fans", "rate_duct", hvac, share="share_concurrent",
             basis="one fan per bath and per kitchen (M-200) + corridor run")
        if z["ptacs"]:
            work(f"ptac_sleeves_{zid}", f"PTAC wall sleeves, {z['label']}", zid, "ptac_sleeves", z["ptacs"], "sleeves",
                 "rate_ptac_sleeve", hvac, share="share_concurrent",
                 basis=f"41 PTACs (M-200) split by floor area ({z['ptacs']} here; per-floor split not on the drawings)")
        work(f"insulation_{zid}", f"Exterior and demising wall insulation, {z['label']}", zid, "insulation",
             q["insulation_sf"], "SF", "rate_insulation", insul, basis="(W1+W2+P1+P2 LF) x wall height")
        rough = [f"elec_rough_{zid}", f"lv_rough_{zid}", f"sprinkler_rough_{zid}", f"duct_rough_{zid}",
                 f"ptac_sleeves_{zid}"]
        for r in rough:
            n.link(f"framing_close_{zid}", r, "overlap", "rough-ins follow framing on the same floor", type="SS",
                   lag=1)
            n.link(f"framing_close_{zid}", r, "prerequisite", "rough-in cannot finish before its walls exist",
                   type="FF", lag=1)
        for fam in ("elec_rough", "lv_rough", "sprinkler_rough", "duct_rough", "ptac_sleeves", "insulation"):
            if n.has(f"{fam}_{zid}"):
                chain(fam, f"{fam}_{zid}", "one crew moves floor to floor")
        n.link(f"ptac_sleeves_{zid}", f"insulation_{zid}", "prerequisite", "sleeves before wall insulation",
               basis="physical: the sleeve is framed into the CFS wall the insulation fills")
        n.link(f"ptac_sleeves_{zid}", "gate_air_barrier_front_rear", "prerequisite",
               "PTAC sleeves penetrate the front/rear air barrier and are sealed before it is inspected",
               basis="TR8 IIA6: the barrier is inspected with its penetrations sealed")
        work(f"firestop_pre_{zid}", f"Firestopping before board: rated penetrations in framing and floor/deck, "
             f"{z['label']}", zid, "firestop_pre", round(z["gross_sf"] * 0.6), "GSF", "rate_firestop",
             simple["firestop"], basis="A-500 UL systems; share of the floor's penetrations concealed by board: 0.6")
        for r in rough + [f"plumbing_rough_{zid}"]:
            n.link(r, f"firestop_pre_{zid}", "prerequisite", "seal penetrations after they exist")
        chain("firestop_pre", f"firestop_pre_{zid}", "one crew moves floor to floor")
        # pre-board gates: TRUE prerequisites of board on that floor
        gate(f"gate_elec_rough_{zid}", f"DOB electrical rough inspection, {z['label']}", zid, "gate_elec_rough",
             "lead_dob_electrical", "DOB Electrical", [f"elec_rough_{zid}", f"lv_rough_{zid}"])
        n.link(f"elec_rough_{zid}", f"gate_elec_rough_{zid}", "prerequisite", "inspect the rough")
        n.link(f"lv_rough_{zid}", f"gate_elec_rough_{zid}", "prerequisite", "FA wiring is electrical work")
        if S["sprinkler"]:
            gate(f"gate_sprinkler_hydro_{zid}", f"Sprinkler hydrostatic test before cover, {z['label']}", zid,
                 "gate_sprinkler_hydro", "lead_special", "Licensed sprinkler contractor test (NFPA 13R)",
                 [f"sprinkler_rough_{zid}"])
            n.link(f"sprinkler_rough_{zid}", f"gate_sprinkler_hydro_{zid}", "prerequisite", "test the installed pipe",
               basis="NFPA 13R / NFPA 13 hydrostatic test before concealment")
        gate(f"gate_firestop_pre_{zid}", f"Firestop special inspection, penetrations concealed by board, {z['label']}",
             zid, "gate_firestop", "lead_special", "Special inspector (BC 1704.27)", [f"firestop_pre_{zid}"])
        n.link(f"firestop_pre_{zid}", f"gate_firestop_pre_{zid}", "prerequisite", "inspect before cover",
               basis="BC 1704.27: penetrations seen before board conceals them")
        # insulation covers wiring and piping: it waits for the ROUGH INSPECTIONS
        n.link(f"gate_elec_rough_{zid}", f"insulation_{zid}", "prerequisite",
               "spray foam conceals the cable in exterior walls", basis=COVER_BASIS)
        n.link(f"gate_plumbing_rough_{zid}", f"insulation_{zid}", "prerequisite",
               "insulation conceals the piping", basis=COVER_BASIS)
        gate(f"gate_tr8_insulation_{zid}", f"TR8 IIA2 insulation placement and R-values, {z['label']}", zid,
             "gate_tr8", "lead_special", "Progress inspector (TR8)", [f"insulation_{zid}"])
        n.link(f"insulation_{zid}", f"gate_tr8_insulation_{zid}", "prerequisite", "inspect before cover",
               basis="BC 110.3.5 / TR8 IIA2 (GN-001)")
        work(f"board_hang_{zid}", f"Gypsum board hang (rated walls and 1-hr ceiling), {z['label']}", zid,
             "board_hang", q["board_sf"], "SF", "rate_board_hang", framer, share="share_arkon_board",
             basis="wall LF x faces by type (2-hr partitions 2 layers each side) x 9 ft + rated ceiling")
        for g in (f"gate_plumbing_rough_{zid}", f"gate_elec_rough_{zid}", f"gate_sprinkler_hydro_{zid}",
                  f"gate_firestop_pre_{zid}", f"gate_tr8_insulation_{zid}"):
            n.link(g, f"board_hang_{zid}", "prerequisite", "nothing is covered before it is inspected",
                   basis=COVER_BASIS)
        n.link(f"duct_rough_{zid}", f"board_hang_{zid}", "prerequisite", "ducts run in the ceiling the board closes")
        chain("board_hang", f"board_hang_{zid}", "one board crew; 20 psf storage limit (S-001) means floor-by-floor "
                                               "stocking")
        gate(f"gate_fire_rated_{zid}", f"Fire-resistance-rated construction progress inspection, {z['label']}", zid,
             "gate_fire_rated", "lead_special", "Progress inspector (BC 110.3.4)", [f"board_hang_{zid}"])
        n.link(f"board_hang_{zid}", f"gate_fire_rated_{zid}", "prerequisite", "layers and fastening seen before tape",
               basis="BC 110.3.4 fire-resistance-rated construction progress inspection (GN-001)")
        work(f"firestop_post_{zid}", f"Firestopping after board: through-board penetrations, rated joints, "
             f"head-of-wall, {z['label']}", zid, "firestop_post", round(z["gross_sf"] * 0.4), "GSF", "rate_firestop",
             simple["firestop"], basis="A-500 UL joint/membrane systems; remaining share 0.4")
        n.link(f"board_hang_{zid}", f"firestop_post_{zid}", "prerequisite", "membrane penetrations exist once board is up")
        chain("firestop_post", f"firestop_post_{zid}", "one crew moves floor to floor")
        gate(f"gate_firestop_{zid}", f"Firestop special inspection, joints and membrane penetrations, {z['label']}",
             zid, "gate_firestop", "lead_special", "Special inspector (BC 1704.27)", [f"firestop_post_{zid}"])
        n.link(f"firestop_post_{zid}", f"gate_firestop_{zid}", "prerequisite", "inspect before tape and paint",
               basis="BC 1704.27: joints and penetrations seen before they are finished over")
        work(f"tape_{zid}", f"Tape and finish, {z['label']}", zid, "tape", q["board_sf"], "SF", "rate_tape",
             simple["tapers"], min_days="min_tape_days", basis="board area")
        n.link(f"gate_fire_rated_{zid}", f"tape_{zid}", "prerequisite", "tape after the rated-assembly inspection",
               basis="BC 110.3.4")
        n.link(f"gate_firestop_{zid}", f"tape_{zid}", "prerequisite", "tape after the firestop inspection",
               basis="BC 1704.27")
        chain("tape", f"tape_{zid}", "one taping crew")
        work(f"prime_{zid}", f"Prime and first coat, {z['label']}", zid, "prime", q["paint_sf"], "SF",
             "rate_paint_prime", simple["painters"], basis="visible wall faces x 9 ft + ceiling")
        n.link(f"tape_{zid}", f"prime_{zid}", "prerequisite", "paint finished board")
        chain("prime", f"prime_{zid}", "one paint crew")
        if z["baths"]:
            work(f"tile_{zid}", f"Bath floor tile and base ({z['baths']} baths), {z['label']}", zid, "tile",
                 z["baths"], "baths", "rate_tile", simple["tile"], basis="GN-001 note 23")
            n.link(f"prime_{zid}", f"tile_{zid}", "prerequisite", "tile after wall prime")
            chain("tile", f"tile_{zid}", "one tile crew")
        if z["kitchens"]:
            fixed_cab = work(f"cabinets_{zid}", f"Kitchenette cabinets ({z['kitchens']}), {z['label']}", zid, "cabinets",
                             z["kitchens"], "kitchens", "rate_cabinets", simple["cabinets"],
                             basis="16 kitchenettes, 4 per floor")
            fixed_cab["delivery"] = "lead_cabinet_delivery"
            n.link(f"prime_{zid}", f"cabinets_{zid}", "prerequisite", "cabinets on primed walls")
            chain("cabinets", f"cabinets_{zid}", "one installer crew")
            work(f"counters_{zid}", f"Quartz counters, {z['label']}", zid, "counters", z["kitchens"], "kitchens",
                 "rate_counters", simple["cabinets"], basis="template after cabinets")
            n.link(f"cabinets_{zid}", f"counters_{zid}", "prerequisite", "template on set cabinets, then fabricate",
                   lag="lag_counter_fab")
        doors_here = round(B["doors"] * z["gross_sf"] / total_gsf)
        if doors_here:
            work(f"doors_trim_{zid}", f"Interior doors and trim ({doors_here}), {z['label']}", zid, "doors_trim",
                 doors_here, "doors", "rate_doors", simple["carpenters"],
                 basis=f"{B['doors']} interior doors (A-400 filed) split by floor area")
            n.link(f"prime_{zid}", f"doors_trim_{zid}", "prerequisite", "trim on primed walls")
            chain("doors_trim", f"doors_trim_{zid}", "one carpentry crew")
        work(f"elec_trim_{zid}", f"Electrical trim, {z['label']}", zid, "elec_trim", z["gross_sf"], "GSF",
             "rate_elec_trim", elec, basis="floor plate")
        n.link(f"prime_{zid}", f"elec_trim_{zid}", "prerequisite", "devices on painted walls")
        chain("elec_trim", f"elec_trim_{zid}", "electricians move floor to floor")
        work(f"lv_trim_{zid}", f"FA / smoke-CO / low-voltage devices, {z['label']}", zid, "lv_trim", z["gross_sf"],
             "GSF", "rate_lv_trim", lv, basis="FA-001..007")
        n.link(f"prime_{zid}", f"lv_trim_{zid}", "prerequisite", "devices on painted ceilings")
        chain("lv_trim", f"lv_trim_{zid}", "one crew")
        if S["sprinkler"]:
            work(f"sprinkler_trim_{zid}", f"Sprinkler heads/escutcheons, {z['label']}", zid, "sprinkler_trim",
                 z["gross_sf"], "GSF", "rate_sprinkler_trim", sprk, basis="concealed residential heads")
            n.link(f"prime_{zid}", f"sprinkler_trim_{zid}", "prerequisite", "cover plates on painted ceilings")
            chain("sprinkler_trim", f"sprinkler_trim_{zid}", "one crew")
        if z["ptacs"]:
            work(f"ptac_set_{zid}", f"PTAC units set ({z['ptacs']}), {z['label']}", zid, "ptac_set", z["ptacs"], "units",
                 "rate_ptac_set", hvac, basis="M-200 PTAC schedule")
            n.link(f"prime_{zid}", f"ptac_set_{zid}", "prerequisite", "units after paint")
            n.link(f"ptac_sleeves_{zid}", f"ptac_set_{zid}", "prerequisite", "unit slides into its sleeve")
            chain("ptac_set", f"ptac_set_{zid}", "one crew")
        if q["fixture_groups"]:
            work(f"plumb_trim_{zid}", f"Plumbing fixture trim ({q['fixture_groups']} groups), {z['label']}", zid,
                 "plumb_trim", q["fixture_groups"], "fixture groups", "rate_plumb_trim", plumber,
                 basis="baths + kitchenettes")
            n.link(f"tile_{zid}", f"plumb_trim_{zid}", "prerequisite", "toilets set on finished tile")
            n.link(f"counters_{zid}", f"plumb_trim_{zid}", "prerequisite", "sinks set in the counters")
            n.link(f"prime_{zid}", f"plumb_trim_{zid}", "prerequisite", "trim on painted walls")
            chain("plumb_trim", f"plumb_trim_{zid}", "plumbers move floor to floor")
        work(f"final_paint_{zid}", f"Final coat and touch-up, {z['label']}", zid, "final_paint", q["paint_sf"], "SF",
             "rate_paint_final", simple["painters"], basis="visible faces")
        for p in (f"doors_trim_{zid}", f"elec_trim_{zid}", f"ptac_set_{zid}", f"lv_trim_{zid}",
                  f"sprinkler_trim_{zid}", f"cabinets_{zid}"):
            n.link(p, f"final_paint_{zid}", "prerequisite", "final coat after trades stop marking walls")
        chain("final_paint", f"final_paint_{zid}", "one paint crew")
        work(f"flooring_{zid}", f"Vinyl plank flooring, {z['label']}", zid, "flooring", q["floor_sf"], "SF",
             "rate_flooring", simple["flooring"], basis="apartment NET x 0.85 + corridor share")
        n.link(f"final_paint_{zid}", f"flooring_{zid}", "prerequisite", "floors last, after paint")
        chain("flooring", f"flooring_{zid}", "one flooring crew")
        fixed(f"punch_clean_{zid}", f"Punch and clean, {z['label']}", "work", zid, "punch_clean", "dur_punch_zone")
        for p in (f"flooring_{zid}", f"plumb_trim_{zid}", f"counters_{zid}"):
            n.link(p, f"punch_clean_{zid}", "prerequisite", "punch the finished floor")

    # ── fire protection ──
    if S["sprinkler"]:
        fixed("sprinkler_riser", "Sprinkler riser + double-check detector on the combined service", "work", "L1",
              "sprinkler_riser", "dur_sprinkler_riser", c=sprk, basis="SP-001 combined 2 in service")
        n.link("water_service", "sprinkler_riser", "prerequisite", "the riser connects to the service")
        for z in zids:
            n.link("sprinkler_riser", f"gate_sprinkler_hydro_{z}", "prerequisite", "hydro pressurises from the riser")
    fixed("backflow_devices", "RPZ (domestic) + DCDA (fire) installed, initial test filed with DEP", "work", "L1",
          "backflow", "dur_backflow", c=plumber, basis="DEP approval #25103445 (2 devices)")
    n.link("water_service", "backflow_devices", "prerequisite", "devices on the live service")
    if S["sprinkler"]:
        n.link("sprinkler_riser", "backflow_devices", "prerequisite", "DCDA sits on the fire line")
        fixed("renew_permit_sprinkler", "Renew sprinkler permit B01141294-S7 (expires 2026-12-03)", "regulatory", "SITE",
              "permit_renewal", "dur_permit_renewal", deadline="2026-12-03", basis="public permit record")
        gate("gate_sprinkler_final", "DOB sprinkler final inspection (flow test, alarms)", "BUILDING",
             "gate_sprinkler_final", "lead_dob_plumbing", "DOB", ["sprinkler"])
        for z in zids:
            n.link(f"sprinkler_trim_{z}", "gate_sprinkler_final", "prerequisite", "final on the trimmed system")
        n.link("backflow_devices", "gate_sprinkler_final", "prerequisite", "flow test through the DCDA")
        n.link("renew_permit_sprinkler", "gate_sprinkler_final", "prerequisite", "no inspection on an expired permit")
    fixed("fa_pretest", "Fire-alarm panel programming and contractor pre-test", "work", "BUILDING", "fa_pretest",
          "dur_fa_pretest", c=lv)
    for z in zids:
        n.link(f"lv_trim_{z}", "fa_pretest", "prerequisite", "every device installed")
    if S["sprinkler"]:
        n.link("sprinkler_riser", "fa_pretest", "prerequisite", "flow and tamper switches on the riser are supervised",
               basis="FA-001 riser: sprinkler alarm points")
    gate("gate_fdny_fa", "FDNY fire-alarm acceptance test", "BUILDING", "gate_fdny_fa", "lead_fdny_fa", "FDNY",
         ["fire_alarm"], extra="reinspect_factor")
    n.link("fa_pretest", "gate_fdny_fa", "prerequisite", "FDNY tests a pre-tested system")
    fixed("hpd_smoke_co", "HPD smoke/CO detector certification (LL 62/81)", "regulatory", "BUILDING", "hpd_cert",
          "dur_hpd_cert", basis="GN-001: certificate within 10 days of installation")
    n.link("fa_pretest", "hpd_smoke_co", "prerequisite", "detectors installed and working")

    # ── electrical service ──
    fixed("elec_service_equipment", "Electrical service equipment (meter bank, main) in the electric room", "work",
          "L1", "elec_service", "dur_service_equip", c=elec, basis="A-100 ELECTRIC room; 41 PTACs at 208/1/60")
    gate("gate_dob_elec_service", "DOB electrical inspection of service equipment", "L1", "gate_elec_service",
         "lead_dob_electrical", "DOB Electrical", ["elec_service_equipment"])
    n.link("elec_service_equipment", "gate_dob_elec_service", "prerequisite", "inspect before the utility energizes")
    fixed("coned_lead", "Con Ed service lead time (application to ready)", "utility", "SITE", "utility_lead",
          "lead_coned", basis="application status unknown")
    fixed("coned_energize", "Con Ed energize permanent service and set meters", "utility", "SITE", "coned",
          "dur_coned_energize")
    n.link("gate_dob_elec_service", "coned_energize", "prerequisite", "utility needs the DOB inspection")
    n.link("coned_lead", "coned_energize", "prerequisite", "utility's own lead time")
    n.link("coned_energize", "fa_pretest", "prerequisite", "the panel runs on the building's light and power service",
           basis="NFPA 72 10.6: primary power from the building service")
    gate("gate_dob_elec_final", "DOB electrical final inspection", "BUILDING", "gate_elec_final",
         "lead_dob_electrical", "DOB Electrical", ["electrical"], extra="reinspect_factor")
    for z in zids:
        n.link(f"elec_trim_{z}", "gate_dob_elec_final", "prerequisite", "final on trimmed work")
    if eifs_ids:
        n.link("facade_lighting", "gate_dob_elec_final", "prerequisite", "exterior lighting included")
    # ── ventilation ──
    fixed("roof_mech", "Roof SAF-1 corridor fan, DH-1 15 kW duct heater, curbs", "work", "ROOF", "roof_mech",
          "dur_roof_mech", c=hvac, basis="M-200 fan and heater schedules")
    n.link("roofing", "roof_mech", "overlap", "curbs flashed into the roof", type="SS", lag=1)
    fixed("ventilation_tab", "Ventilation test and balance (SAF-1, EF-1/EF-2)", "work", "BUILDING", "tab", "dur_tab",
          c=hvac)
    n.link("roof_mech", "ventilation_tab", "prerequisite", "balance installed equipment")
    n.link("coned_energize", "ventilation_tab", "prerequisite", "fans run on permanent power")
    for z in zids:
        n.link(f"final_paint_{z}", "ventilation_tab", "prerequisite", "grilles set after the final coat")
    gate("gate_tr8_final", "TR8 final energy items (IB2, IIC1-IIC6, IID1, ID2)", "BUILDING", "gate_tr8",
         "lead_special", "Progress inspector (TR8)", ["energy"], basis="GN-001 TR8 list (16 items)")
    n.link("ventilation_tab", "gate_tr8_final", "prerequisite", "IB2 ventilation")
    for z in zids:
        n.link(f"ptac_set_{z}", "gate_tr8_final", "prerequisite", "equipment in place", basis="TR8 IB2 (GN-001)")
        n.link(f"elec_trim_{z}", "gate_tr8_final", "prerequisite", "lighting and controls installed",
               basis="TR8 IIC2-IIC5 (GN-001): the installed lighting and controls are inspected")

    # ── gas and hot water ──
    if S["gas"]:
        fixed("hwh_room", "Gas water heater, recirculation pump, flue in the roof HWH room", "work", "ROOF", "hwh",
              "dur_hwh", c=plumber, basis="gas change set: roof HWH ROOM 78 SF; P-400")
        n.link("roofing", "hwh_room", "prerequisite", "room dried in")
        fixed("gas_final_test", "Gas piping final connections and pressure test", "work", "BUILDING", "gas_test",
              "dur_gas_test", c=plumber, basis="riser G-1 (P-303)")
        n.link("hwh_room", "gas_final_test", "prerequisite", "test the connected appliance piping")
        n.link("gate_plumbing_rough_ROOF", "gas_final_test", "prerequisite", "rough passed first")
        fixed("renew_permit_plumbing", "Renew plumbing permit B01141294-S5 (expires 2026-12-03)", "regulatory", "SITE",
              "permit_renewal", "dur_permit_renewal", deadline="2026-12-03", basis="public permit record")
        gate("gate_dob_gas_final", "DOB gas piping final inspection", "BUILDING", "gate_gas_final",
             "lead_dob_plumbing", "DOB", ["gas_final_test"])
        n.link("gas_final_test", "gate_dob_gas_final", "prerequisite", "inspect the tested piping")
        n.link("renew_permit_plumbing", "gate_dob_gas_final", "prerequisite", "no inspection on an expired permit")
        fixed("gas_authorization", "DOB gas authorization to the utility", "regulatory", "BUILDING",
              "gas_authorization", "lead_gas_auth")
        n.link("gate_dob_gas_final", "gas_authorization", "prerequisite", "authorization follows the gas final")
        fixed("ng_service_lead", "National Grid gas service line (lead time)", "utility", "SITE", "utility_lead",
              "lead_ng_service", basis="request status unknown")
        fixed("ng_meter_on", "National Grid meter set and gas turn-on", "utility", "SITE", "ng_turn_on",
              "lead_ng_turn_on")
        n.link("gas_authorization", "ng_meter_on", "prerequisite", "no gas without the authorization",
               basis="NYC FGC / DOB gas authorization required before the utility supplies gas")
        n.link("ng_service_lead", "ng_meter_on", "prerequisite", "service line before the meter")
        fixed("dhw_startup", "Hot water start-up and recirculation balance", "work", "ROOF", "dhw_startup",
              "dur_dhw_startup", c=plumber)
        n.link("ng_meter_on", "dhw_startup", "prerequisite", "fire the heater on utility gas")
    # ── plumbing final and the sewer chain ──
    gate("gate_plumbing_final", "DOB plumbing final inspection", "BUILDING", "gate_plumbing_final",
         "lead_dob_plumbing", "DOB", ["plumbing"])
    for z in zids:
        n.link(f"plumb_trim_{z}", "gate_plumbing_final", "prerequisite", "fixtures set")
    n.link("backflow_devices", "gate_plumbing_final", "prerequisite", "devices tested")
    n.link("renew_permit_plumbing", "gate_plumbing_final", "prerequisite", "no inspection on an expired permit")
    if S["roof_detention"]:
        gate("gate_detention_cert", "DOB certifies the roof detention installed", "ROOF", "gate_detention",
             "lead_dob_plumbing", "DOB", ["roof_drains_detention"],
             basis="SD1-2 p2: DEP issues no sewer connection permit until DOB certifies this")
        n.link("roof_drains_detention", "gate_detention_cert", "prerequisite", "certify what is installed")
        n.link("renew_permit_plumbing", "gate_detention_cert", "prerequisite", "inspection under the plumbing permit")
        fixed("dep_connection_permit", "DEP site connection (sewer) permit", "regulatory", "SITE", "dep_permit",
              "lead_dep_permit")
        n.link("gate_detention_cert", "dep_connection_permit", "prerequisite", "DEP condition: detention first",
               basis="SD1-2 p2: no connection permit until DOB certifies the detention facility")
        fixed("dot_opening_permit", "DOT street-opening permit for the sewer cut", "regulatory", "SITE", "dot_permit",
              "lead_dot_permit", basis="B012026289B88 expired 2026-11-01")
        n.link("dep_connection_permit", "dot_opening_permit", "prerequisite", "DOT opening for a permitted connection")
        fixed("house_sewer_connection", "House sewer drill-in connection to the 60 in combined sewer", "work", "SITE",
              "sewer_connection", "dur_sewer_conn", c=site, weather="weather_sitework",
              basis="SD1-2: 6 in/8 in EHCI drill-in (C4), concrete encasement 24 h before core drill")
        n.link("dot_opening_permit", "house_sewer_connection", "prerequisite", "dig under a permit")
        n.link("building_sewer_sleeve", "house_sewer_connection", "prerequisite", "connect to the sleeve")
        gate("gate_dep_connection", "DEP house connection inspection", "SITE", "gate_dep", "lead_dep_inspection",
             "DEP", ["house_sewer_connection"])
        n.link("house_sewer_connection", "gate_dep_connection", "prerequisite", "inspect before backfill/close")
        fixed("street_restoration", "Street restoration over the sewer cut", "work", "SITE", "street_restoration",
              "dur_street_restore", c=site, weather="weather_sitework")
        n.link("gate_dep_connection", "street_restoration", "prerequisite", "restore after the inspection")

    # ── site protection, sidewalk, permits ──
    fixed("renew_permit_shed", "Renew sidewalk shed permit B01409772 (expires 2026-11-22)", "regulatory", "SITE",
          "permit_renewal", "dur_permit_renewal", deadline="2026-11-22", basis="public permit record")
    fixed("renew_permit_scaffold", "Renew supported scaffold permit B01467559 (expires 2026-12-22)", "regulatory",
          "SITE", "permit_renewal", "dur_permit_renewal", deadline="2026-12-22", basis="public permit record")
    fixed("scaffold_shed_removal", "Strike scaffold and sidewalk shed", "work", "SITE", "scaffold_removal",
          "dur_scaffold_strike", c=scaffold)
    for a in eifs_ids + ["roof_coping", "facade_lighting", "gate_eifs_special"]:
        n.link(a, "scaffold_shed_removal", "prerequisite", "facade finished and inspected before the scaffold goes")
    fixed("sidewalk_bpp", "Sidewalk, curb and street tree (Builders Pavement Plan)", "work", "SITE", "sidewalk",
          "dur_sidewalk", c={"crew": None, "company": None, "mobilize": True}, weather="weather_sitework")
    n.link("scaffold_shed_removal", "sidewalk_bpp", "prerequisite", "the shed stands on the sidewalk")
    gate("gate_bpp", "Builders Pavement Plan sign-off", "SITE", "gate_bpp", "lead_bpp", "DOT / DOB", ["sidewalk_bpp"])
    n.link("sidewalk_bpp", "gate_bpp", "prerequisite", "sign off finished work")
    fixed("renew_permits_gc", "Renew GC, structural and mechanical permits (expire 2027-01-20)", "regulatory", "SITE",
          "permit_renewal", "dur_permit_renewal", deadline="2027-01-20", basis="public permit record")

    # ── close-out ──
    fixed("tr1_closeout", "TR1 structural special inspections close-out (CFS, steel details, adjacent structure)",
          "regulatory", "BUILDING", "tr1_closeout", "dur_tr1_closeout", basis="S-001 special inspection table")
    n.link("cfs_superstructure", "tr1_closeout", "prerequisite", "reports cover the finished frame")
    n.link("stairs_complete", "tr1_closeout", "prerequisite", "steel details include the stairs")
    fixed("inspection_reports", "Special and progress inspection reports compiled and filed (TR1, TR8)", "regulatory",
          "BUILDING", "reports", "dur_paperwork")
    for a in ["tr1_closeout", "gate_eifs_special", "gate_tr8_final", "gate_air_barrier_test", "gate_tr8_fenestration"] \
            + [f"gate_firestop_{z}" for z in zids] + [f"gate_firestop_pre_{z}" for z in zids] \
            + [f"gate_fire_rated_{z}" for z in zids]:
        n.link(a, "inspection_reports", "prerequisite", "a report follows its inspection")
    gate("gate_final_progress", "Final progress inspection (TR1 FINAL, BC 110.5)", "BUILDING", "gate_final_progress",
         "lead_special", "Progress inspector", ["building"], basis="S-001 progress inspection FINAL")
    for z in zids:
        n.link(f"punch_clean_{z}", "gate_final_progress", "prerequisite", "final on finished floors")
    n.link("inspection_reports", "gate_final_progress", "prerequisite", "documents complete")
    gate("gate_tco", "DOB Temporary Certificate of Occupancy", "BUILDING", "gate_tco", "lead_tco", "DOB",
         ["occupancy"])
    tco_basis = {
        "gate_final_progress": "BC 110.5 final inspection (S-001 progress inspection FINAL)",
        "gate_plumbing_final": "AC 28-118: plumbing work signed off for the occupied area",
        "gate_dob_elec_final": "AC 28-118 / NYC Electrical Code: electrical sign-off",
        "gate_sprinkler_final": "BC 903 / AC 28-118: sprinkler system accepted",
        "gate_fdny_fa": "FDNY letter of approval for the fire alarm (FC 907)",
        "gate_tr8_final": "BC 110.3.5: energy progress inspections (TR8) complete",
        "gate_air_barrier_test": "BC 110.3.5: TR8 IIA7 air barrier test",
        "hpd_smoke_co": "GN-001: HPD smoke/CO certificate (LL 62/81)",
        "stairs_complete": "BC 1011: exit stairs complete (2 stairs, no elevator)",
        "renew_permits_gc": "AC 28-105.9: work and inspections under a valid permit",
        "dhw_startup": "HMC 27-2031: hot water to every unit before occupancy",
        "gate_dep_connection": "physical: an occupied building must drain; DEP connection permit condition (SD1-2)",
    }
    for p_, why in tco_basis.items():
        n.link(p_, "gate_tco", "prerequisite", "a TCO needs this", basis=why)
    gate("final_co", "Final Certificate of Occupancy", "BUILDING", "final_co", "lead_tco", "DOB", ["occupancy"])
    n.link("gate_tco", "final_co", "prerequisite", "CO follows the TCO")
    n.link("gate_bpp", "final_co", "prerequisite", "BPP sign-off before the CO",
           basis="Builders Pavement Plan job 340915692 is signed off before the final CO")
    n.link("street_restoration", "final_co", "prerequisite", "street restored")
    zinfo = {z["id"]: (i, z["gross_sf"]) for i, z in enumerate(zones)}
    for a in n.acts:
        if a["zone"] in zinfo and a["kind"] == "work":
            a["lift"], a["zone_sf"] = zinfo[a["zone"]]
    not_applicable = []
    if not S["elevator"]:
        not_applicable.append({"id": "elevator", "why": "no elevator on any plan: 2 exit stairs, no shaft "
                                                         "(GN-004/005); building elevators = 0"})
    if not S["standpipe"]:
        not_applicable.append({"id": "standpipe", "why": "none drawn or required: the building tops out at 50 ft "
                                                          "(60 ft at bulkhead), standpipe starts at 75 ft (SSP-002)"})
    if not S["cellar"]:
        not_applicable.append({"id": "cellar", "why": "no cellar (operator ruling 2026-09-16, DOB filing): crews' "
                                                      "'cellar slab' wording is the slab on grade"})
    not_applicable.append({"id": "superstructure_cycles", "why": "see superstructure_cycles: CFS frame, no deck "
                                                                 "pours, frame complete to the roof"})
    return {"activities": n.acts, "links": n.links, "not_applicable": not_applicable,
            "skipped_links": [{"from": a_, "to": b_} for a_, b_ in n.skipped]}


# ═══ PROVISIONAL STATE FROM THE RECORDS ═════════════════════════════════════

#: report-engine work phrases -> activity family. Whole words; a phrase that
#: names no work here is nothing.
PHRASE_FAMILIES: Tuple[Tuple[str, str], ...] = (
    (r"\binterior framing\b|\bblocking\b|\bceiling drops?\b|\bdoor bucks?\b", "framing_close"),
    (r"\belectrical wiring\b|\bpull wire\b", "elec_rough"),
    (r"\bductwork\b", "duct_rough"),
    (r"\binsulation\b|\bspray foam\b", "insulation"),
    (r"\bstucco\b|\beifs\b", "eifs"),
    (r"\broof insulation\b|\broofing\b", "roofing"),
    (r"\bwindow installation\b|\bvapou?r barrier\b", "windows"),
    (r"\brooftop unit\b|\broof mep\b", "roof_mech"),
    (r"\bmetal stairs?\b", "stairs_complete"),
)
FLOOR_RANGE = re.compile(r"floors?\s+(\d)(?:\s*[–-]\s*(\d))?|floors\s+(\d(?:,\s*\d)+)", re.I)


def _floors_in(text: str) -> List[str]:
    m = FLOOR_RANGE.search(text or "")
    if not m:
        return []
    if m.group(3):
        return [f"L{x.strip()}" for x in m.group(3).split(",")]
    a = int(m.group(1))
    b = int(m.group(2) or a)
    return [f"L{i}" for i in range(a, b + 1)]


def provisional_state(network: Dict[str, Any], records: Sequence[Dict[str, Any]],
                      inspections: Optional[Dict[str, Any]], timeline: Sequence[Dict[str, Any]],
                      crews: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """(state by activity id, notes). Built only from verified public records,
    filed-log phrases, and stated operator words, each tagged as such."""
    ids = {a["id"]: a for a in network["activities"]}
    st: Dict[str, Dict[str, Any]] = {}
    notes: List[str] = []

    def put(aid, entry):
        if aid in ids:
            st[aid] = entry
    # verified public record: sign-offs
    locs = {}
    for r in timeline or []:
        if r.get("kind") == "signoff":
            locs[str(r.get("job_or_permit_no"))] = r.get("date")
    for aid, job, what in (("demolition", "B01075600-I1", "full demolition"),
                           ("soe_excavation", "B01141294-S8", "support of excavation"),
                           ("foundation_sog", "B01141294-S4", "foundation/earthwork")):
        if job in locs:
            put(aid, state_entry("done", "verified_public_record", f"{what} LOC issued {locs[job]} ({job})",
                                 sources=[job]))
    # verified public record: DOB plumbing floor results
    rec = (inspections or {}).get("plumbing_permit_B01141294-S5-PL") or {}
    table = rec.get("floor_results_table_UNDATED") or {}
    pass_id = next((c.get("id") for c in rec.get("completed_inspections") or [] if c.get("result") == "Pass"), None)
    pass_on = next((c.get("resulted", "")[:10] for c in rec.get("completed_inspections") or []
                    if c.get("result") == "Pass"), "")
    level_of = {"001": "L1", "002": "L2", "003": "L3", "004": "L4", "005": "L5", "MEZ": "MEZ", "ROF": "ROOF"}
    for fl, cells in table.items():
        z = level_of.get(fl)
        if not z:
            continue
        rough = [k for k, v in cells.items() if "ROUGH" in k and v == "PASSED"]
        if len(rough) >= 2:
            basis = f"DOB floor results {fl}: {', '.join(rough)} PASSED (inspection {pass_id}, {pass_on})"
            put(f"plumbing_rough_{z}", state_entry("done", "verified_public_record", basis, sources=[str(pass_id)]))
            put(f"gate_plumbing_rough_{z}", state_entry("done", "verified_public_record", basis,
                                                        sources=[str(pass_id)]))
        if any("UND GRND" in k and v in ("CERTIFIED", "PASSED") for k, v in cells.items()) and fl == "001":
            basis = "DOB floor results 001: WS and ST underground CERTIFIED (self-cert 2026-09-01, spot check passed)"
            put("plumbing_underground", state_entry("done", "verified_public_record", basis))
            put("gate_plumbing_underground", state_entry("done", "verified_public_record", basis))
    for n_ in (inspections or {}).get("advance_notices") or []:
        sc = n_.get("dob_spot_check") or {}
        if "sleeve" in str(n_.get("request_comment_verbatim", "")).lower() and "Pass" in str(sc.get("result")):
            put("building_sewer_sleeve", state_entry("done", "verified_public_record",
                                                     f"DOB spot check {sc.get('id')} passed {sc.get('resulted', '')[:10]}: "
                                                     "steel sleeve through foundation wall", sources=[n_.get("record")]))
    if all(st.get(f"gate_plumbing_rough_{z}", {}).get("status") == "done"
           for z in [a["zone"] for a in network["activities"] if a["family"] == "plumbing_rough"]):
        put("cfs_superstructure", state_entry(
            "done", "inferred", "DOB passed plumbing rough on every level through the roof (verified) and roofing was "
                                "reported Oct 29-Nov 3: the frame stands to the roof", sources=[str(pass_id)]))
    # operator statement (not public)
    for r in records:
        if r.get("type") == "inspection_statement" and "water main" in str(r.get("quote") or "").lower():
            put("water_service", state_entry("done", "operator_statement",
                                             f"operator {r.get('date')}: 'water main dob inspection passed' (not in "
                                             "public data; DEP results are not public)", sources=[r.get("id")]))
            notes.append("The operator's 'fire alarm dob scheduled' (2026-11-10) carries no date and no public "
                         "record; the FDNY acceptance gate is scheduled from its lead time instead.")
            break
    # filed-log phrases, latest period (report engine)
    # man-days in place come only from the report engine's period summaries:
    # a derived-report figure (unaudited), labelled so wherever it is used
    man_days_by_company = {c: v["derived"]["avg"] * v["derived"]["days"] for c, v in crews.items()
                           if v.get("derived")}
    seen_trim = False
    for r in records:
        f = r.get("fields") or {}
        if r.get("duplicate_of") or f.get("kind") != "period_work_item" or not r.get("quote"):
            continue
        text = str(r.get("quote"))
        if re.search(r"\btrim out\b|\bfixtures?\b", text, re.I):
            seen_trim = True
            continue
        fam = next((fam for rx, fam in PHRASE_FAMILIES if re.search(rx, text, re.I)), None)
        if not fam:
            continue
        comp = (r.get("company") or "").strip()
        md = man_days_by_company.get(comp)
        basis = (f"generated progress report (derived, unaudited), period {f.get('period') or '?'}: {text!r} by {comp}")
        floors = _floors_in(text)
        if fam in ("roofing", "windows", "roof_mech", "stairs_complete"):
            put(fam, state_entry("in_progress", "derived_report", basis, sources=[r.get("id")],
                                 man_days=md if fam in ("roofing", "windows") else None))
            continue
        if fam == "eifs":
            for a in ids:
                if a.startswith("eifs_"):
                    put(a, state_entry("in_progress", "derived_report", basis, sources=[r.get("id")], man_days=md))
            continue
        for z in floors:
            share = md / len(floors) if (md and fam == "insulation") else None
            put(f"{fam}_{z}", state_entry("in_progress", "derived_report", basis + f" (floor {z[1:]})",
                                          sources=[r.get("id")], man_days=share))
    if seen_trim:
        notes.append("Logs report 'Trim out'/'Fixtures' for Quality Plumbing on floors 1-4 (Oct 27-Nov 9) while no "
                     "board is reported anywhere: read as tub/valve setting during rough, NOT credited as finish trim.")
    eifs_md = [st[a].get("man_days") for a in st if a.startswith("eifs_") and st[a].get("man_days")]
    if eifs_md:
        n_el = len([a for a in ids if a.startswith("eifs_")])
        for a in ids:
            if a.startswith("eifs_") and st.get(a, {}).get("man_days"):
                st[a]["man_days"] = round(st[a]["man_days"] / n_el, 1)
    # gates and finishes with no record: not started is only said where the
    # records cover the period and nothing sequenced before them has passed.
    for a in network["activities"]:
        if a["id"] in st:
            continue
        if a["family"] in ("board_hang", "tape", "prime", "tile", "cabinets", "counters", "doors_trim", "elec_trim",
                           "lv_trim", "sprinkler_trim", "ptac_set", "plumb_trim", "final_paint", "flooring",
                           "punch_clean"):
            st[a["id"]] = state_entry("not_started", "inferred",
                                      "no record of this work in logs through 2026-11-09, and no pre-board inspection "
                                      "is on record for any floor")
        elif a["kind"] == "inspection_gate":
            st[a["id"]] = state_entry("unknown", "no_record", "no public result (electrical, special/progress, FDNY "
                                                               "and DEP results are not public or were not read)")
        else:
            st[a["id"]] = dict(DEFAULT_STATE)
    return st, notes


#: the reconstruction lane's level names and work nodes -> this network.
MODEL_LEVELS = {"FLOOR_1": "L1", "FLOOR_2": "L2", "FLOOR_3": "L3", "FLOOR_4": "L4", "FLOOR_5": "L5",
                "MEZZANINE": "MEZ", "ROOF": "ROOF"}
MODEL_WORK = {"framing": "framing_close", "rough_electric": "elec_rough", "rough_duct": "duct_rough",
              "insulation": "insulation", "gate_plumbing_rough": "gate_plumbing_rough",
              "underground_plumbing": "plumbing_underground", "gate_plumbing_underground": "gate_plumbing_underground",
              "rough_sprinkler": "sprinkler_rough", "rough_lowvolt": "lv_rough", "roofing": "roofing",
              "windows": "windows", "facade_envelope": "eifs"}
MODEL_SYSTEMS = {"electrical": "elec_rough", "hvac": "duct_rough", "sprinkler": "sprinkler_rough"}
MODEL_BUILDING = {"demolition": "demolition", "excavation_soe": "soe_excavation", "foundation": "foundation_sog",
                  "facade_envelope": "eifs", "roofing": "roofing", "windows": "windows"}
#: model status -> (status, evidence). "reported" means a log names the work.
MODEL_STATUS = {
    "done_verified": ("done", "verified_public_record"), "done_confirmed": ("done", "verified_public_record"),
    "done_attested": ("done", "operator_statement"),
    "in_progress_observed": ("in_progress", "reported_log"), "in_progress_reported": ("in_progress", "reported_log"),
    "reported": ("in_progress", "reported_log"),
    "inferred_done_high": ("done", "inferred"), "inferred_done_medium": ("done", "inferred"),
    "inferred_done_low": ("in_progress", "inferred"), "unknown": ("unknown", "no_record"),
}
#: families the model may NOT mark done or started on its own word: a 'mep_trim'
#: report before any board is rough-in, and finish work is sequenced after
#: inspections the record does not show.
NOT_FROM_MODEL = ("mep_trim",)


def state_from_model(model: Dict[str, Any], network: Dict[str, Any],
                     base: Optional[Dict[str, Dict[str, Any]]] = None) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """The reconstruction lane's 588_model.json (current_state) laid over a
    base state. The model can raise or lower a status; a verified public
    record in the base is never lowered by a weaker model category."""
    ids = {a["id"] for a in network["activities"]}
    st = {k: dict(v) for k, v in (base or {}).items()}
    cs = (model or {}).get("current_state") or {}
    applied, unmapped, kept = 0, [], 0
    rank = {e: i for i, e in enumerate(("no_record", "inferred", "reported_log", "operator_statement",
                                        "verified_public_record"))}

    def put(aid: str, raw: str, basis: str) -> None:
        nonlocal applied, kept
        if aid not in ids:
            unmapped.append(aid)
            return
        status, ev = MODEL_STATUS.get(raw, ("unknown", "no_record"))
        cur = st.get(aid)
        if cur and cur["status"] == "done" and rank[cur["evidence"]] > rank[ev]:
            kept += 1
            return
        if cur and status == "unknown" and cur["status"] != "unknown":
            kept += 1
            return
        md = (cur or {}).get("man_days") if status == "in_progress" else None
        st[aid] = state_entry(status, ev, f"588_model.json: {basis} = {raw}", sources=["588_model.json"],
                              man_days=md)
        applied += 1
    for lvl, body in (cs.get("levels") or {}).items():
        z = MODEL_LEVELS.get(lvl)
        if not z:
            continue
        for node, w in (body.get("work") or {}).items():
            fam = MODEL_WORK.get(node)
            if node in NOT_FROM_MODEL or not fam:
                continue
            if fam == "eifs":
                continue  # by elevation, not by floor: taken from the building entry
            if fam in ("roofing", "windows"):
                put(fam, w.get("status", ""), f"{lvl}.work.{node}")
                continue
            put(f"{fam}_{z}", w.get("status", ""), f"{lvl}.work.{node}")
        for sysname, sysv in (body.get("systems") or {}).items():
            fam = MODEL_SYSTEMS.get(sysname)
            if fam:
                put(f"{fam}_{z}", sysv.get("state", ""), f"{lvl}.systems.{sysname}")
        for pre in ((cs.get("closure") or {}).get(lvl) or {}).get("prerequisites") or []:
            g = {"gate_electrical_rough": "gate_elec_rough", "gate_plumbing_rough": "gate_plumbing_rough",
                 "gate_sprinkler_hydro": "gate_sprinkler_hydro", "gate_firestopping": "gate_firestop",
                 "gate_nycecc_insulation": "gate_tr8_insulation"}.get(pre.get("gate"))
            if g:
                put(f"{g}_{z}", pre.get("status", ""), f"closure.{lvl}.{pre.get('gate')}")
    for node, b in (cs.get("building") or {}).items():
        fam = MODEL_BUILDING.get(node)
        if not fam:
            continue
        if fam == "eifs":
            for aid in ids:
                if aid.startswith("eifs_"):
                    put(aid, b.get("status", ""), f"building.{node}")
        else:
            put(fam, b.get("status", ""), f"building.{node}")
    notes = [f"588_model.json: {applied} states applied, {kept} kept from stronger evidence, "
             f"{len(unmapped)} unmapped ({', '.join(sorted(set(unmapped))[:6])})"]
    return st, notes


# ═══ SCHEDULING ═════════════════════════════════════════════════════════════

def _resolver(assumptions: Sequence[Dict[str, Any]], overrides: Optional[Dict[str, Dict[str, Any]]] = None):
    table = {a["id"]: a for a in assumptions}
    ov = overrides or {}

    def A(aid: str, scn: str) -> Any:
        if aid in ov and scn in ov[aid]:
            return ov[aid][scn]
        if aid not in table:
            raise KeyError(f"no assumption {aid!r}")
        return table[aid]["values"][scn]
    return A, table


def _cap_fn(cal: Calendar, profile: Optional[Dict[int, float]]):
    if not profile:
        return None
    cache: Dict[int, float] = {}

    def cap(i: int) -> float:
        if i not in cache:
            cache[i] = float(profile.get(cal.date(i).month, profile.get(str(cal.date(i).month), 1.0)))
        return cache[i]
    return cap


#: Families whose material goes up the stairs by hand (no elevator, no hoist).
STAIR_CARRIED = ("board_hang", "flooring", "tile", "cabinets", "counters", "doors_trim", "ptac_set", "ptac_sleeves")


def zone_crew_cap(a: Act, scn: str, A) -> Optional[float]:
    """Most workers one floor plate holds for one activity."""
    if not a.get("zone_sf"):
        return None
    return max(1.0, float(a["zone_sf"]) / float(A("sf_per_worker", scn)))


def crew_used(a: Act, scn: str, A) -> Optional[float]:
    if not a.get("crew"):
        return None
    crew = float(A(a["crew"], scn))
    if a.get("share"):
        crew *= float(A(a["share"], scn))
    cap = zone_crew_cap(a, scn, A)
    return min(crew, cap) if cap else crew


def _effort(a: Act, st: Dict[str, Any], scn: str, A) -> Tuple[float, float, str]:
    """(effort working days, remaining share, how)."""
    rule = a.get("rule")
    if rule == "production":
        qty = float(a["scope"]["quantity"] or 0)
        qr = a.get("qty_rule")
        if qr and qr.get("kind") == "facade":
            cov = qr["covered_storeys"]
            cov = float(A(cov, scn)) if isinstance(cov, str) else float(cov)
            qty = qr["lf"] * max(0.0, qr["height"] - 10.0 * cov)
            if qr.get("openings"):
                qty -= qr.get("windows", 0) * float(A("window_avg_sf", scn)) + qr.get("ptacs", 0) * 5.5
            qty = max(qty, 0.0)
        qf = a.get("qty_factor")
        for f in ([qf] if isinstance(qf, str) else (qf or [])):
            qty *= (1.0 - float(A(f[2:], scn))) if f.startswith("1-") else float(A(f, scn))
        rate = float(A(a["rate"], scn))
        crew = crew_used(a, scn, A) or 1.0
        rem, how = remaining_fraction(st, scn, A, qty=qty, rate=rate)
        eff = qty * rem / max(crew * rate, EPS)
        if a["family"] in STAIR_CARRIED and a.get("lift"):
            eff *= 1 + float(A("stair_carry_per_level", scn)) * a["lift"]
        if a.get("min_days") and rem > 0:
            eff = max(eff, float(A(a["min_days"], scn)))
        return eff, rem, how
    if rule == "lead":
        rem, how = remaining_fraction(st, scn, A, gate=True)
        lead = float(A(a["lead"], scn))
        if a.get("reinspect"):
            # a failed first attempt costs one more request-to-result cycle at the
            # NORMAL wait (a re-test request), not the long-end wait again
            lead += float(A(a["reinspect"], scn)) * float(A(a["lead"], "normal"))
        return lead * rem + (1 if rem else 0), rem, how
    if rule == "fixed":
        if not a.get("dur"):
            rem, how = ((0.0, f"done ({st['evidence']}); no remaining scope is modelled, so no haircut applies")
                        if st["status"] == "done" else (1.0, st["status"]))
            return 0.0, rem, how
        rem, how = remaining_fraction(st, scn, A, gate=a["kind"] in ("utility", "regulatory"))
        return float(A(a["dur"], scn)) * rem, rem, how
    raise ValueError(f"unknown duration rule {rule!r} on {a['id']}")


def schedule_scenario(network: Dict[str, Any], state: Dict[str, Dict[str, Any]], assumptions: Sequence[Dict[str, Any]],
                      scn: str, data_date: date, overrides: Optional[Dict[str, Dict[str, Any]]] = None, *,
                      level: bool = True, max_rounds: int = 400) -> Dict[str, Any]:
    """CPM for one scenario, then FLOOR-PLATE LEVELLING: on any one floor no
    more than `max_trades_per_floor` work activities and `sf_per_worker` of
    plate per worker at once. Each over-limit start is pushed behind the
    activity on that floor that frees up first (a 'space' link, recorded)."""
    A, _t = _resolver(assumptions, overrides)
    extra: List[Link] = []
    r = _schedule_once(network, state, assumptions, scn, data_date, overrides, extra)
    if not level:
        return r
    started = {a["id"] for a in network["activities"]
               if state.get(a["id"], DEFAULT_STATE)["status"] == "in_progress"}
    zones = sorted({a["zone"] for a in network["activities"] if a.get("zone_sf")})
    for _ in range(max_rounds):
        hit = _first_overload(network, r, zones, scn, A, started)
        if not hit:
            break
        extra.append(hit)
        r = _schedule_once(network, state, assumptions, scn, data_date, overrides, extra)
    r["space_links"] = extra
    return r


def _reaches(links: Sequence[Link], a: str, b: str) -> bool:
    succ: Dict[str, List[str]] = {}
    for l in links:
        succ.setdefault(l["from"], []).append(l["to"])
    stack, seen = [a], set()
    while stack:
        x = stack.pop()
        if x == b:
            return True
        if x in seen:
            continue
        seen.add(x)
        stack += succ.get(x, [])
    return False


def _first_overload(network, r, zones, scn, A, started) -> Optional[Link]:
    max_trades = int(A("max_trades_per_floor", scn))
    acts = r["activities"]
    by_id = {a["id"]: a for a in network["activities"]}
    for z in zones:
        zw = [a for a in network["activities"] if a["zone"] == z and a["kind"] == "work"
              and acts[a["id"]]["effort_days"] > 0 and acts[a["id"]]["start"]]
        cap_w = float(zw[0]["zone_sf"]) / float(A("sf_per_worker", scn)) if zw else 0
        for x in sorted(zw, key=lambda a: (acts[a["id"]]["es"], a["id"])):
            d = acts[x["id"]]["es"]
            live = [a for a in zw if acts[a["id"]]["es"] <= d < acts[a["id"]]["ef"]]
            workers = sum(acts[a["id"]]["crew_used"] or 1.0 for a in live)
            if len(live) <= max_trades and (workers <= cap_w + EPS or len(live) == 1):
                continue
            movable = [a for a in live if a["id"] not in started and acts[a["id"]]["es"] == d]
            if not movable:
                continue
            victim = max(movable, key=lambda a: (acts[a["id"]]["total_float_days"], a["id"]))
            others = sorted((a for a in live if a is not victim), key=lambda a: (acts[a["id"]]["ef"], a["id"]))
            for o in others:
                if not _reaches(r["_links"], victim["id"], o["id"]):
                    return {"from": o["id"], "to": victim["id"], "type": "FS", "lag": 0, "kind": "resource",
                            "why": f"floor-plate limit on {z}: {len(live)} trades / {workers:.0f} workers at once"}
    return None


def _schedule_once(network, state, assumptions, scn, data_date, overrides, extra) -> Dict[str, Any]:
    A, table = _resolver(assumptions, overrides)
    cal = Calendar(data_date, [date.fromisoformat(d) for d in A("holidays", scn)])
    acts, rows = [], {}
    mob = int(A("mobilization", scn))
    for a in network["activities"]:
        st = state.get(a["id"], DEFAULT_STATE)
        eff, rem, how = _effort(a, st, scn, A)
        profile = A(a["weather"], scn) if a.get("weather") else None
        nb = 0
        if a.get("mobilize") and rem > 0 and st["status"] != "in_progress":
            nb = mob
        if a.get("delivery"):
            nb = max(nb, int(A(a["delivery"], scn)))
        pinned = rem <= 0 and st["status"] == "done"
        acts.append({"id": a["id"], "effort": eff, "cap": _cap_fn(cal, profile), "not_before": nb, "pinned": pinned})
        cu = crew_used(a, scn, A)
        rows[a["id"]] = {"effort_days": round(eff, 2), "remaining_share": round(rem, 3), "remaining_how": how,
                         "not_before_days": nb, "crew_used": round(cu, 2) if cu else None}
    links = []
    started = {a["id"] for a in network["activities"]
               if state.get(a["id"], DEFAULT_STATE)["status"] == "in_progress"}
    pinned_ids = {x["id"] for x in acts if x["pinned"]}
    kinds = {a["id"]: a["kind"] for a in network["activities"]}
    for l in list(network["links"]) + list(extra):
        if scn not in l.get("scenarios", ALL_RUNS):
            continue
        lag = l["lag"]
        lag = int(round(float(A(lag, scn)))) if isinstance(lag, str) else int(lag)
        t = l["type"]
        # retained logic: a started activity's open FS PREREQUISITE bounds its
        # FINISH, not its start (it is already under way). A crew (resource)
        # link stays FS: the same crew cannot be in two places.
        if t == "FS" and l["kind"] == "prerequisite" and l["to"] in started and l["from"] not in pinned_ids \
                and kinds.get(l["from"]) != "inspection_gate":
            t = "FF"
        links.append({"from": l["from"], "to": l["to"], "type": t, "lag": lag, "kind": l["kind"]})
    res = cpm(acts, links)
    end_id = "gate_tco" if "gate_tco" in res else max(res, key=lambda k: res[k]["ef"])
    path = [i for i in driving_path(res, end_id) if not next(x for x in acts if x["id"] == i)["pinned"]]
    out_acts = {}
    for a in network["activities"]:
        r, row = res[a["id"]], rows[a["id"]]
        done = r["driver"] == "done"
        row.update({"es": r["es"], "ef": r["ef"], "ls": r["ls"], "lf": r["lf"], "total_float_days": r["tf"],
                    "start": None if done else cal.date(r["es"]).isoformat(),
                    "finish": None if done else cal.date(max(r["es"], r["ef"] - 1)).isoformat(),
                    "late_finish": None if done else cal.date(max(r["ls"], r["lf"] - 1)).isoformat(),
                    "critical": a["id"] in path, "driver": (r["driver"]["from"] if isinstance(r["driver"], dict)
                                                            else r["driver"])})
        out_acts[a["id"]] = row
    tco = res.get("gate_tco")
    co = res.get("final_co")
    return {"scenario": scn, "calendar_origin": cal.origin.isoformat(),
            "tco": cal.date(max(0, tco["ef"] - 1)).isoformat() if tco else None,
            "tco_working_days": tco["ef"] if tco else None,
            "interior_ready": max((out_acts[k]["finish"] for k in out_acts if k.startswith("punch_clean_")
                                   and out_acts[k]["finish"]), default=None),
            "final_co": cal.date(max(0, co["ef"] - 1)).isoformat() if co else None,
            "critical_path": path, "activities": out_acts, "_links": links, "_cal": cal}


# ═══ THE WHOLE ══════════════════════════════════════════════════════════════

OWNER_RULES = (
    "ESTIMATE, not a baseline: never written to project_schedules, never shown as a file date.",
    "PROPOSED sequence, offered for approval, separate from any official schedule.",
    "Production rates are industry assumptions; activity dates, crews moving between floors and photo counts are "
    "not used as a rate. Crew SIZE is MEASURED only from original filed daily-log rows (records/AUDIT.md), with its "
    "sample; report-engine figures are labelled derived-report (unaudited).",
    "An inferred or reported inspection pass is never a passed inspection, in any scenario.",
    "Every assumption carries a tag: measured, derived-report, drawing, regulatory or industry-assumption.",
)

#: links removed or replaced in the review of 2026-11-10 (adversarial review 1, item A).
LINK_REVIEW_REMOVED = (
    {"from": "gate_dob_elec_final", "to": "gate_tr8_final", "why": "no code basis: the TR8 progress inspector does "
     "not wait for the DOB electrical final; replaced by elec_trim_* -> gate_tr8_final (TR8 IIC2-IIC5)"},
    {"from": "elec_rough_*", "to": "insulation_*", "why": "replaced by gate_elec_rough_* -> insulation_*: foam "
     "conceals the cable, so the INSPECTION comes first (BC 110.3)"},
    {"from": "plumbing_rough_*", "to": "insulation_*", "why": "replaced by gate_plumbing_rough_* -> insulation_*"},
    {"from": "firestopping_*", "to": "gate_firestop_* -> board_hang_*", "why": "split: firestop_pre (concealed "
     "penetrations) -> gate_firestop_pre -> board; board -> firestop_post (membrane penetrations, rated joints, "
     "head-of-wall) -> gate_firestop -> tape (BC 1704.27)"},
    {"from": "coned_energize", "to": "gate_dob_elec_final", "why": "no code basis cited"},
    {"from": "gate_bpp", "to": "gate_tco", "why": "conservative-only, no code basis; BPP stays before the final CO"},
    {"from": "scaffold_shed_removal", "to": "gate_tco", "why": "no code basis for the TCO; the shed still precedes the "
     "sidewalk, the BPP sign-off and the final CO"},
    {"from": "dhw_startup", "to": "gate_plumbing_final", "why": "moved to gate_tco (HMC 27-2031 hot water)"},
    {"from": "gate_dep_connection", "to": "gate_plumbing_final", "why": "moved to gate_tco (an occupied building must "
     "drain; DEP condition)"},
    {"from": "punch_clean_*", "to": "ventilation_tab", "why": "replaced by final_paint_* (grilles set after paint)"},
    {"from": "sprinkler_trim_*", "to": "fa_pretest", "why": "replaced by sprinkler_riser (flow/tamper switches are "
     "on the riser)"},
    {"from": "reinspect_factor", "to": "gate_tco", "why": "a re-inspection is one extra cycle of the inspection itself "
     "(kept on the DOB electrical final and FDNY), not a doubling of the TCO review"},
)


def superstructure_cycles(facts: Dict[str, Any], state: Dict[str, Dict[str, Any]],
                          scen: Dict[str, Dict[str, Any]], zones: Sequence[str]) -> Dict[str, Any]:
    frame = state.get("cfs_superstructure", {})
    floor_cycles = {}
    for s, r in scen.items():
        acts = r["activities"]
        floor_cycles[s] = {z: (acts[f"punch_clean_{z}"]["ef"] - acts[f"board_hang_{z}"]["es"])
                           for z in zones if f"board_hang_{z}" in acts}
    return {
        "relevant": False,
        "answer": "No. A 3/5/7-day superstructure cycle does not apply to this building and no concrete cycle is made up.",
        "why": [
            "The frame is cold-formed steel bearing walls with CFS joists @16 in and a 3/4 in USG structural concrete "
            "panel subfloor (S-102/S-106); there is no cast-in-place deck above the 6 in slab on grade, so there is "
            "no pour, cure or reshore cycle to compare.",
            f"Frame state ({frame.get('evidence', 'unknown')}; an inference, not a passed inspection): "
            + (frame.get("basis") or "unknown") + ".",
            "The repeating unit left is the per-floor close-in-to-finish sequence. Its working-day span per floor "
            "(board hang start to punch finish) under each scenario is in floor_cycles_working_days.",
        ],
        "floor_cycles_working_days": floor_cycles,
    }


def _eifs_crew(net) -> Optional[str]:
    return next((a["crew"] for a in net["activities"] if a["family"] == "eifs" and a.get("crew")), None)


def _lever_overrides(lv, net, table):
    ov = {}
    for k, v in lv["overrides"].items():
        k = _eifs_crew(net) if k == "@eifs_crew" else k
        if k in table:
            ov[k] = v
    return ov


LEVERS: Tuple[Dict[str, Any], ...] = (
    {"id": "eifs_one_more_applicator", "lever": "One more EIFS applicator (2 a day, the highest day reported)",
     "overrides": {"@eifs_crew": {"normal": 2.0}},
     "requires": ["J&P sends a second applicator every working day"]},
    {"id": "eifs_staff_and_enclose", "lever": "EIFS to 5 applicators with an enclosed, heated scaffold",
     "overrides": {"@eifs_crew": {"normal": 5.0}, "weather_exterior": {"normal": ENCLOSED_WEATHER}},
     "requires": ["J&P adds ~4 applicators or a second EIFS sub is bought out",
                  "scaffold shrink-wrap/tarps + temporary heat (FDNY permit for propane, or electric heat on temp power)",
                  "sidewalk shed permit renewed by 2026-11-22 and scaffold permit by 2026-12-22",
                  "EIFS special inspector available per elevation (BC 1704.13)"]},
    {"id": "breezco_staff_up", "lever": "BreezCo to 4 mechanics (PTAC sleeves, duct rough, roof fan in parallel)",
     "overrides": {"crew_breezco": {"normal": 4.0}},
     "requires": ["BreezCo commits 3 more mechanics, or the framers take the PTAC sleeves"]},
    {"id": "second_board_tape_crews", "lever": "Second taping crew and a full framer crew on board",
     "overrides": {"crew_tapers": {"normal": 8.0}, "share_arkon_board": {"normal": 0.8}},
     "requires": ["taping sub bought out (none on the roster)", "board stocked floor by floor: 20 psf storage limit "
                  "on the CFS floors (S-001)"]},
    {"id": "utilities_expedited", "lever": "Con Ed and National Grid applications expedited now",
     "overrides": {"lead_coned": {"normal": 20}, "lead_ng_service": {"normal": 15}},
     "requires": ["Con Ed load letter and service layout filed (electrical permit B01445590 is issued)",
                  "National Grid service request + DOB gas authorization path; weekly expediting"]},
    {"id": "inspections_prebooked", "lever": "Book inspections ahead and keep agencies on call",
     "overrides": {"lead_dob_electrical": {"normal": 5}, "lead_fdny_fa": {"normal": 10}, "lead_special": {"normal": 1},
                   "lead_tco": {"normal": 10}},
     "requires": ["readiness walk before each request (measured DOB request-to-result: 7 working days, n=1)",
                  "TR1/TR8 agency retained with standing visits", "FDNY FA test date requested at pre-test"]},
    {"id": "mobilize_unstarted_now", "lever": "Mobilize sprinkler, low-voltage and finish trades now",
     "overrides": {"mobilization": {"normal": 0}, "lead_cabinet_delivery": {"normal": 0}},
     "requires": ["executed subcontracts for Complete (sprinkler) and Voltec (low voltage), tapers, painters, tile, "
                  "flooring, millwork", "submittals approved; cabinets ordered"]},
)


def acceleration(network, state, assumptions, data_date, base: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Each lever on the normal scenario ALONE, and CUMULATIVE (with every
    lever above it)."""
    out = []
    table = {a["id"] for a in assumptions}
    combined: Dict[str, Dict[str, Any]] = {}
    prev = base["tco_working_days"]
    for lv in LEVERS:
        ov = _lever_overrides(lv, network, table)
        if not ov:
            continue
        alone = schedule_scenario(network, state, assumptions, "normal", data_date, ov)
        for k, v in ov.items():
            combined.setdefault(k, {}).update(v)
        cum = schedule_scenario(network, state, assumptions, "normal", data_date, combined)
        out.append({"id": lv["id"], "lever": lv["lever"], "requires": lv["requires"],
                    "changes": {k: v["normal"] if not isinstance(v["normal"], dict) else "enclosed: 0.85 every month"
                                for k, v in ov.items()},
                    "tco_alone": alone["tco"], "working_days_saved_alone": base["tco_working_days"] - alone["tco_working_days"],
                    "tco_cumulative": cum["tco"], "working_days_saved_by_adding": prev - cum["tco_working_days"],
                    "critical_path_after": cum["critical_path"]})
        prev = cum["tco_working_days"]
    return out


#: State unknowns that move the finish, run as two branches each (normal).
BRANCHES: Tuple[Dict[str, Any], ...] = (
    {"id": "electrical_rough", "what": "Electrical rough work and its DOB rough inspection, every floor "
                                       "(DOB NOW: Inspections Plus is not public)",
     "families": ("elec_rough", "gate_elec_rough"),
     "a": ("done", "already roughed and passed (not public)"),
     "b": ("not_started", "rough still to finish and inspection not yet requested")},
    {"id": "sprinkler_rough", "what": "NFPA 13R sprinkler rough and pre-cover hydro (Complete: roster only, no record)",
     "families": ("sprinkler_rough", "gate_sprinkler_hydro", "sprinkler_riser"),
     "a": ("done", "installed and tested, never logged"), "b": ("not_started", "not started")},
    {"id": "fa_low_voltage_rough", "what": "Fire-alarm / smoke-CO / low-voltage rough (Voltec: roster only)",
     "families": ("lv_rough",), "a": ("done", "installed, never logged"), "b": ("not_started", "not started")},
    {"id": "ptac_sleeves", "what": "41 PTAC wall sleeves in the CFS walls (no record)",
     "families": ("ptac_sleeves",), "a": ("done", "set with the windows, never logged"),
     "b": ("not_started", "not started")},
    {"id": "house_sewer", "what": "DEP chain: detention certification, sewer permit, street connection",
     "families": ("gate_detention", "dep_permit", "dot_permit", "sewer_connection", "gate_dep"),
     "a": ("done", "already connected under an earlier permit"), "b": ("not_started", "still ahead")},
)
OVERRIDE_BRANCHES: Tuple[Dict[str, Any], ...] = (
    {"id": "facade_eifs_share", "what": "Facade finish split, brick vs EIFS (not determinable from the drawings)",
     "key": "facade_eifs_share", "a": 1.0, "a_words": "all EIFS/stucco (scenario value)", "b": 0.5,
     "b_words": "half EIFS, half brick veneer by a mason not yet on the roster"},
    {"id": "other_neighbour", "what": "Height of the neighbour on the side the drawings do not describe",
     "key": "unknown_neighbour_storeys", "a": 2, "a_words": "2 storeys, like No. 586 (scenario value)", "b": 0,
     "b_words": "no building: the whole lot-line wall is exposed"},
    {"id": "coned_lead", "what": "Con Ed service lead (application status unknown)", "key": "lead_coned",
     "a": "fast", "b": STRESS},
    {"id": "ng_service_lead", "what": "National Grid gas service (request status unknown)", "key": "lead_ng_service",
     "a": "fast", "b": STRESS},
)


def _with_state(state, net, families, status):
    st = dict(state)
    for a in net["activities"]:
        if a["family"] in families or a["id"] in families:
            st[a["id"]] = state_entry(status, "verified_public_record" if status == "done" else "inferred",
                                      f"BRANCH: assumed {status} to bound an unknown")
    return st


def _branch_row(bid, what, a_words, ra, b_words, rb):
    return {"id": bid, "unknown": what, "if_a": a_words, "tco_if_a": ra["tco"], "if_b": b_words, "tco_if_b": rb["tco"],
            "interior_ready_if_a": ra["interior_ready"], "interior_ready_if_b": rb["interior_ready"],
            "spread_working_days": rb["tco_working_days"] - ra["tco_working_days"]}


def branches(net, state, assumptions, data_date) -> List[Dict[str, Any]]:
    out = []
    worst, best = dict(state), dict(state)
    run = lambda st, ov=None: schedule_scenario(net, st, assumptions, "normal", data_date, ov)  # noqa: E731
    for b in BRANCHES:
        if not any(a["family"] in b["families"] for a in net["activities"]):
            continue
        ra = run(_with_state(state, net, b["families"], b["a"][0]))
        rb = run(_with_state(state, net, b["families"], b["b"][0]))
        best = _with_state(best, net, b["families"], b["a"][0])
        worst = _with_state(worst, net, b["families"], b["b"][0])
        out.append(_branch_row(b["id"], b["what"], b["a"][1], ra, b["b"][1], rb))
    # every gate whose 'pass' is only an inference: passed (if it were verified) vs pending
    for a in net["activities"]:
        st = state.get(a["id"], DEFAULT_STATE)
        if a["kind"] == "inspection_gate" and st["status"] == "done" and st["evidence"] != "verified_public_record":
            ra = run(_with_state(state, net, (a["id"],), "done"))
            out.append(_branch_row(f"inferred_gate:{a['id']}", f"{a['name']} (inferred: {st['basis'][:120]})",
                                   "passed (if it were verified)", ra, "pending (how every scenario treats it)",
                                   run(state)))
    tab = {x["id"]: x for x in assumptions}
    for b in OVERRIDE_BRANCHES:
        if b["key"] not in tab:
            continue
        v = tab[b["key"]]["values"]
        va = v[b["a"]] if isinstance(b["a"], str) else b["a"]
        vb = v[b["b"]] if isinstance(b["b"], str) else b["b"]
        ra, rb = run(state, {b["key"]: {"normal": va}}), run(state, {b["key"]: {"normal": vb}})
        out.append(_branch_row(b["id"], b["what"], b.get("a_words", f"{va}"), ra, b.get("b_words", f"{vb}"), rb))
    out.append(_branch_row("all_state_branches", "every state branch above at once (utility leads at normal)",
                           "all already done", run(best), "all still ahead", run(worst)))
    return out


SENS_EIFS_CREWS = (0.8, 1, 2, 3, 5)
SENS_DOB_WAITS = (5, 7, 10, 15)


def sensitivity(net, state, assumptions, data_date) -> Dict[str, Any]:
    """Normal TCO against the two numbers that decide it most: the EIFS crew
    and the DOB request-to-result wait. No single number decides silently."""
    cid = _eifs_crew(net)
    tab = {a["id"]: a for a in assumptions}
    rows, waits = [], []
    for c in SENS_EIFS_CREWS:
        r = schedule_scenario(net, state, assumptions, "normal", data_date, {cid: {"normal": c}}) if cid else None
        rows.append({"crew": c, "tco": r["tco"] if r else None, "tco_working_days": r["tco_working_days"] if r else None,
                     "note": "0.8 = 1.3 per day present x 6 of 10 days present (derived report)" if c == 0.8 else ""})
    for w in SENS_DOB_WAITS:
        ov = {k: {"normal": w} for k in ("lead_dob_plumbing", "lead_dob_electrical") if k in tab}
        r = schedule_scenario(net, state, assumptions, "normal", data_date, ov)
        waits.append({"working_days": w, "tco": r["tco"], "tco_working_days": r["tco_working_days"]})
    grid = []
    for c in (1, 2, 5):
        for w in (5, 7, 15):
            ov = {k: {"normal": w} for k in ("lead_dob_plumbing", "lead_dob_electrical") if k in tab}
            if cid:
                ov[cid] = {"normal": c}
            r = schedule_scenario(net, state, assumptions, "normal", data_date, ov)
            grid.append({"eifs_crew": c, "dob_wait": w, "tco": r["tco"]})
    return {"eifs_crew_assumption": cid, "eifs_crew_normal": tab[cid]["values"]["normal"] if cid in tab else None,
            "eifs_crew_tag": tab[cid]["tag"] if cid in tab else None,
            "eifs_crew": rows, "dob_wait": waits, "grid": grid}


def state_contradictions(net, state, scen: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Where the state cannot be true as stated. Each is REPORTED, and the
    schedule's resolution is said: done work is kept done (it imposes nothing
    on what is left), work under way still waits for its gate."""
    out = []
    kinds = {a["id"]: a["kind"] for a in net["activities"]}
    names = {a["id"]: a["name"] for a in net["activities"]}
    st = lambda i: state.get(i, DEFAULT_STATE)  # noqa: E731
    for l in net["links"]:
        if l["kind"] != "prerequisite" or l["type"] not in ("FS", "FF"):
            continue
        p, q = st(l["from"]), st(l["to"])
        if q["status"] == "done" and p["status"] != "done":
            out.append({"id": l["to"], "kind": "done_with_open_prerequisite", "open": l["from"],
                        "what": f"{names[l['to']]} is {q['status']} ({q['evidence']}) while its prerequisite "
                                f"{names[l['from']]} is {p['status']}",
                        "resolution": "kept as done; it imposes nothing on the remaining work (no negative float)"})
        p_done_verified = p["status"] == "done" and p["evidence"] == "verified_public_record"
        if q["status"] == "in_progress" and kinds.get(l["from"]) == "inspection_gate" and not p_done_verified:
            out.append({"id": l["to"], "kind": "covering_before_inspection", "open": l["from"],
                        "what": f"{names[l['to']]} is reported under way while {names[l['from']]} is not on record as "
                                "passed: either it was inspected (not public) or work went over it uninspected",
                        "resolution": "the REMAINING work is scheduled after the gate; see the branches"})
    for s, r in scen.items():
        for i, row in r["activities"].items():
            if row["total_float_days"] < 0:
                out.append({"id": i, "kind": "negative_float", "scenario": s, "float": row["total_float_days"],
                            "what": "negative total float", "resolution": "unresolved: reported"})
    seen, uniq = set(), []
    for c in out:
        k = (c["id"], c["kind"], c.get("open"), c.get("scenario"))
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def concurrency(net, r: Dict[str, Any], assumptions, scn: str) -> Dict[str, Any]:
    """Per floor: the most trades and workers on the plate at once, and on
    which day; the whole site's peak headcount."""
    A, _t = _resolver(assumptions)
    acts = r["activities"]
    cal = r["_cal"]
    per_zone: Dict[str, Dict[str, Any]] = {}
    site_peak, site_day = 0.0, None
    horizon = max((x["ef"] for x in acts.values()), default=0)
    work = [a for a in net["activities"] if a["kind"] == "work" and acts[a["id"]]["start"]
            and acts[a["id"]]["effort_days"] > 0]
    for d in range(0, horizon):
        live = [a for a in work if acts[a["id"]]["es"] <= d < acts[a["id"]]["ef"]]
        tot = sum(acts[a["id"]]["crew_used"] or 1.0 for a in live)
        if tot > site_peak:
            site_peak, site_day = tot, d
        for z in {a["zone"] for a in live if a.get("zone_sf")}:
            zl = [x for x in live if x["zone"] == z]
            w = sum(acts[x["id"]]["crew_used"] or 1.0 for x in zl)
            cur = per_zone.get(z)
            if cur is None or (len(zl), w) > (cur["trades"], cur["workers"]):
                per_zone[z] = {"day": cal.date(d).isoformat(), "trades": len(zl), "workers": round(w, 1),
                               "activities": sorted(x["id"] for x in zl)}
    cap_t = int(A("max_trades_per_floor", scn))
    sfpw = float(A("sf_per_worker", scn))
    for z, v in per_zone.items():
        sf = next(a["zone_sf"] for a in net["activities"] if a["zone"] == z and a.get("zone_sf"))
        v["limit_trades"], v["limit_workers"] = cap_t, round(sf / sfpw, 1)
        v["within_limits"] = v["trades"] <= cap_t and v["workers"] <= v["limit_workers"] + 0.05
        if not v["within_limits"]:
            v["why_over"] = "work already under way on this floor (reported in the logs) is not moved by the levelling"
    return {"scenario": scn, "per_floor_peak": per_zone,
            "site_peak_workers": round(site_peak, 1),
            "site_peak_day": cal.date(site_day).isoformat() if site_day is not None else None,
            "space_links_added": len(r.get("space_links") or []),
            "why_feasible": [
                "Exterior work (EIFS, coping, roofing) runs from the pipe scaffold and the roof while interior trades "
                "work inside: separate access, separate space.",
                "On one floor, rough-in trades work in different planes (walls vs ceilings) and different units; the "
                "floor-plate levelling holds each floor to the trade and worker limits, and pushes any extra trade "
                "behind the one that frees the floor first (space links).",
                "Finish trades follow each other floor by floor; board hangers and tapers never share a floor because "
                "the rated-construction inspection sits between them.",
                "Vertical access is the two stairs only (no elevator; no hoist drawn in the SSP), so hand-carried "
                "material carries a per-level effort factor.",
            ]}



def prepare(building, records, inspections=None, timeline=(), audit=None) -> Dict[str, Any]:
    facts = facts_from_building(building)
    crews = measured_crews(records, audit)
    leads = measured_inspection_leads(inspections)
    measured = measured_assumptions(crews, leads)
    defaults = default_assumptions()
    if "lead_dob_plumbing" not in {a["id"] for a in measured}:
        defaults.append(assumption("lead_dob_plumbing", "DOB plumbing/sprinkler/gas inspection request to result",
                                   "working days", "industry-assumption", 5, 7, 12, faster="lower",
                                   basis="no measured sample"))
    assumptions = coherent_conservative(measured + defaults)
    bad = [a["id"] for a in assumptions if not monotone(a)]
    if bad:
        raise ValueError(f"assumptions not ordered fast <= normal <= conservative <= stress: {bad}")
    role_company: Dict[str, str] = {}
    for comp, c in crews.items():
        if c.get("role") and (c.get("avg") or c["role"] not in role_company):
            role_company[c["role"]] = comp
    crew_ids = {a["id"] for a in measured if a["id"].startswith("crew_")}
    net = build_network(facts, role_company, crew_ids)
    known = {a["id"] for a in assumptions}
    for a in net["activities"]:
        if a.get("crew") and a["crew"] not in known:
            a["crew_note"] = f"{a['crew']} has no sample; using crew_carpenters"
            a["crew"] = "crew_carpenters"
    prov, notes = provisional_state(net, records, inspections, timeline, crews)
    if audit is None:
        notes.append("No records audit was given: no crew size is called measured.")
    return {"facts": facts, "crews": crews, "leads": leads, "assumptions": assumptions, "net": net,
            "provisional": prov, "notes": list(facts["warnings"]) + notes}


def generate(building: Dict[str, Any], records: Sequence[Dict[str, Any]], *, data_date: date,
             inspections: Optional[Dict[str, Any]] = None, timeline: Sequence[Dict[str, Any]] = (),
             state: Optional[Dict[str, Dict[str, Any]]] = None, state_source: str = "provisional",
             project: str = "", extras: bool = True, audit: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    p = prepare(building, records, inspections, timeline, audit)
    return assemble(p, state if state is not None else p["provisional"], state_source, data_date, project,
                    extras=extras)


def model_run(building, records, model, *, data_date: date, inspections=None, timeline=(), project="", audit=None,
              model_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The same generator with 588_model.json laid over the provisional state.
    `model_meta` (sha256, mtime) is recorded so a rewritten model is visible."""
    p = prepare(building, records, inspections, timeline, audit)
    st, notes = state_from_model(model, p["net"], p["provisional"])
    doc = assemble(p, st, "provisional + 588_model.json", data_date, project, extras=True)
    changed = sorted(k for k in st if (st[k]["status"], st[k]["evidence"]) !=
                     (p["provisional"].get(k, DEFAULT_STATE)["status"], p["provisional"].get(k, DEFAULT_STATE)["evidence"]))
    return {"present": True, "model": model_meta, "notes": notes, "completion": doc["completion"],
            "stress_test": doc["stress_test"], "critical_path": doc["critical_path"], "branches": doc["branches"],
            "sensitivity": doc["sensitivity"], "next_three_weeks": doc["next_three_weeks"],
            "state_contradictions": doc["state_contradictions"], "acceleration_levers": doc["acceleration_levers"],
            "state_changes_vs_provisional": [
                {"id": k, "provisional": f"{p['provisional'].get(k, DEFAULT_STATE)['status']} "
                                         f"({p['provisional'].get(k, DEFAULT_STATE)['evidence']})",
                 "model": f"{st[k]['status']} ({st[k]['evidence']})", "basis": st[k]["basis"]} for k in changed]}


def assemble(p: Dict[str, Any], state: Dict[str, Dict[str, Any]], state_source: str, data_date: date, project: str,
             *, extras: bool = True) -> Dict[str, Any]:
    facts, crews, leads, assumptions, net = p["facts"], p["crews"], p["leads"], p["assumptions"], p["net"]
    notes = list(p["notes"])
    full_state = {a["id"]: state.get(a["id"], dict(DEFAULT_STATE)) for a in net["activities"]}
    scen = {s: schedule_scenario(net, full_state, assumptions, s, data_date) for s in SCENARIOS}
    stress = schedule_scenario(net, full_state, assumptions, STRESS, data_date)
    normal = scen["normal"]
    zones = [z["id"] for z in facts["zones"]]
    by_id = {a["id"]: a for a in net["activities"]}
    nxt = []
    for aid, r in sorted(normal["activities"].items(), key=lambda kv: (kv[1]["es"], kv[0])):
        if r["start"] is None or r["effort_days"] <= 0 or r["es"] >= 15:
            continue
        a = by_id[aid]
        nxt.append({"id": aid, "name": a["name"], "kind": a["kind"], "zone": a["zone"], "company": a.get("company"),
                    "start": r["start"], "finish": r["finish"], "critical": r["critical"],
                    "total_float_days": r["total_float_days"], "state": full_state[aid]["status"],
                    "evidence": full_state[aid]["evidence"]})
    crit = normal["critical_path"]
    by_company: Dict[str, float] = {}
    for aid in crit:
        c = by_id[aid].get("company") or by_id[aid].get("authority") or by_id[aid]["kind"]
        by_company[c] = round(by_company.get(c, 0.0) + normal["activities"][aid]["effort_days"])
    thin = [{"company": c, "avg": v["avg"], "n_days": v["days"], "source": v["source"]} for c, v in crews.items()
            if v.get("avg") and v["avg"] < 2.5]
    externals = [{"id": a["id"], "name": a["name"], "total_float_days": normal["activities"][a["id"]]["total_float_days"],
                  "effort_days": normal["activities"][a["id"]]["effort_days"]}
                 for a in net["activities"] if a["kind"] in ("utility", "regulatory", "inspection_gate")
                 and normal["activities"][a["id"]]["start"] and normal["activities"][a["id"]]["total_float_days"] <= 10
                 and normal["activities"][a["id"]]["effort_days"] >= 5]
    bottlenecks = {"critical_path_effort_by_party": dict(sorted(by_company.items(), key=lambda kv: -kv[1])),
                   "thin_crews": thin, "agency_and_utility_items_near_critical": externals}
    deadlines = []
    for a in net["activities"]:
        if not a.get("deadline"):
            continue
        for s in SCENARIOS:
            r = scen[s]["activities"][a["id"]]
            deadlines.append({"id": a["id"], "scenario": s, "deadline": a["deadline"], "finish": r["finish"],
                              "meets_deadline": bool(r["finish"] and r["finish"] <= a["deadline"])})
    shed_need = {s: scen[s]["activities"].get("scaffold_shed_removal", {}).get("start") for s in SCENARIOS}
    order = [scen[s]["tco_working_days"] or 0 for s in SCENARIOS] + [stress["tco_working_days"] or 0]
    if not all(x <= y for x, y in zip(order, order[1:])):
        notes.append("WARNING: floor-plate levelling left the scenario finishes out of order: " + str(order))
    contradictions = state_contradictions(net, full_state, dict(scen, **{STRESS: stress}))
    basis_kinds: Dict[str, int] = {}
    for l in net["links"]:
        k = "code/drawing" if not l["basis"].startswith(("physical", "crew continuity")) else l["basis"].split(":")[0]
        basis_kinds[k] = basis_kinds.get(k, 0) + 1
    doc = {
        "kind": DOC_KIND, "is_baseline": False, "status": "ESTIMATE - proposed sequence, not a baseline, not approved",
        "engine": ENGINE, "project": project, "data_date": data_date.isoformat(), "state_source": state_source,
        "rules": list(OWNER_RULES),
        "scenario_definitions": {s: {"story": SCENARIO_STORIES[s],
                                     "adverse": list(CONSERVATIVE_ADVERSE) if s == "conservative" else None}
                                 for s in ALL_RUNS},
        "completion": {s: {"tco": scen[s]["tco"], "final_co": scen[s]["final_co"],
                           "interior_ready": scen[s]["interior_ready"],
                           "tco_working_days": scen[s]["tco_working_days"]} for s in SCENARIOS},
        "stress_test": {"what": SCENARIO_STORIES[STRESS], "tco": stress["tco"], "final_co": stress["final_co"],
                        "interior_ready": stress["interior_ready"], "tco_working_days": stress["tco_working_days"],
                        "critical_path": stress["critical_path"]},
        "critical_path": [{"id": i, "name": by_id[i]["name"], "start": normal["activities"][i]["start"],
                           "finish": normal["activities"][i]["finish"],
                           "effort_days": normal["activities"][i]["effort_days"]} for i in crit],
        "critical_path_by_scenario": {s: scen[s]["critical_path"] for s in SCENARIOS},
        "next_three_weeks": nxt,
        "bottlenecks": bottlenecks,
        "sensitivity": sensitivity(net, full_state, assumptions, data_date) if extras else {},
        "acceleration_levers": acceleration(net, full_state, assumptions, data_date, normal) if extras else [],
        "branches": branches(net, full_state, assumptions, data_date) if extras else [],
        "state_contradictions": contradictions,
        "link_review": {"removed": list(LINK_REVIEW_REMOVED), "basis_counts": basis_kinds,
                        "skipped_links_to_absent_activities": len(net.get("skipped_links") or [])},
        "concurrency": {s: concurrency(net, scen[s], assumptions, s) for s in SCENARIOS},
        "space_links": {s: scen[s].get("space_links") or [] for s in SCENARIOS},
        "superstructure_cycles": superstructure_cycles(facts, full_state, scen, zones),
        "deadline_checks": deadlines,
        "shed_and_scaffold_needed_until": shed_need,
        "assumptions": assumptions,
        "measured": {"crews": crews, "inspection_leads": leads},
        "facts": {"systems": facts["systems"], "building": facts["building"], "neighbours": facts["neighbours"],
                  "zones": [{k: v for k, v in z.items() if k not in ("notes",)} for z in facts["zones"]]},
        "network": {"counts": _counts(net), "not_applicable": net["not_applicable"],
                    "activities": [dict(a, state=full_state[a["id"]],
                                        scenarios={s: scen[s]["activities"][a["id"]] for s in SCENARIOS})
                                   for a in net["activities"]],
                    "links": net["links"]},
        "notes": notes,
    }
    check_not_a_baseline(doc)
    return doc


def _counts(net: Dict[str, Any]) -> Dict[str, Any]:
    kinds: Dict[str, int] = {}
    for a in net["activities"]:
        kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
    lk: Dict[str, int] = {}
    for l in net["links"]:
        lk[l["kind"]] = lk.get(l["kind"], 0) + 1
    return {"activities": len(net["activities"]), "links": len(net["links"]), "by_kind": kinds, "links_by_kind": lk}


def _keys(o: Any) -> Iterable[str]:
    if isinstance(o, dict):
        for k, v in o.items():
            yield str(k)
            yield from _keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _keys(v)


def check_not_a_baseline(doc: Dict[str, Any]) -> None:
    """Raises if the document could be read as a schedule file or a fact."""
    if doc.get("kind") != DOC_KIND or doc.get("is_baseline") is not False:
        raise ValueError("a schedule estimate must say kind=schedule_estimate and is_baseline=False")
    bad = sorted({k for k in _keys(doc.get("network")) if k.startswith(FILE_FIELD_PREFIXES)})
    if bad:
        raise ValueError(f"a schedule estimate may not carry schedule-file fields: {bad}")


def estimate_items(doc: Dict[str, Any], project_id: Any) -> List[Dict[str, Any]]:
    """The completion dates as evidence items of kind 'estimate' (lib/evidence),
    each with its basis. This is the ONLY way a date leaves the document."""
    out = []
    for s in SCENARIOS:
        c = doc["completion"][s]
        if not c["tco"]:
            continue
        it = E.item("estimate", "scheduled", source="lib/schedule_generator", ref=f"tco:{s}", project_id=project_id,
                    node="tco_zone", levels=(), on=date.fromisoformat(c["tco"]),
                    basis=(f"{s} scenario CPM over {doc['network']['counts']['activities']} activities from the "
                           f"building model; data date {doc['data_date']}; state {doc['state_source']}"),
                    note="schedule ESTIMATE, not a baseline and not a schedule file")
        out.append(it)
    return out


def jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, float) and (math.isinf(o) or math.isnan(o)):
        return None
    if callable(o):
        return None
    return o


# ═══ README ═════════════════════════════════════════════════════════════════

def _row(*cells: Any) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


#: the published run before adversarial review 1 (schedule/588_schedule.json, 2026-11-10 09:10)
BEFORE_REVIEW_1 = {"fast": "2027-02-22", "normal": "2027-06-14", "conservative": "2028-02-02"}


def readme(doc: Dict[str, Any]) -> str:
    """A short human summary of the document (the JSON is the record)."""
    c = doc["completion"]
    acts = {a["id"]: a for a in doc["network"]["activities"]}
    tab = {a["id"]: a for a in doc["assumptions"]}
    tags: Dict[str, int] = {}
    for a in doc["assumptions"]:
        tags[a["tag"]] = tags.get(a["tag"], 0) + 1
    sens = doc.get("sensitivity") or {}
    cid = sens.get("eifs_crew_assumption")
    L = [f"# 588 remaining-work schedule - ESTIMATE (data date {doc['data_date']})", "",
         "**An estimate with its basis. Not a baseline, not a schedule file, not approved.** A PROPOSED sequence, "
         "offered for approval, separate from any official schedule. Built by `backend/lib/schedule_generator.py` "
         "(runner `backend/scripts/intel_588_schedule.py`) from the drawings lane's building model, the ORIGINAL "
         "records (records/AUDIT.md), the public inspection record and a STATE. Full detail: `588_schedule.json`.", ""]
    if cid in tab:
        L += [f"**Read this first:** the normal TCO is decided by the EIFS crew, `{cid}` = "
              f"{tab[cid]['values']['normal']:g} per day present, a **{tab[cid]['tag']}** figure "
              f"({tab[cid]['sample'].get('n_days')} days in a generated report, no original crew row). At 2 a day the "
              "normal TCO is " + next((r["tco"] for r in sens["eifs_crew"] if r["crew"] == 2), "?")
              + "; see the sensitivity table.", ""]
    L += [f"Network: {doc['network']['counts']['activities']} activities "
          f"({', '.join(f'{v} {k}' for k, v in doc['network']['counts']['by_kind'].items())}), "
          f"{doc['network']['counts']['links']} links "
          f"({', '.join(f'{v} {k}' for k, v in doc['network']['counts']['links_by_kind'].items())}); every link "
          "carries a basis (" + ", ".join(f"{v} {k}" for k, v in doc["link_review"]["basis_counts"].items()) + "). "
          f"Not applicable: {', '.join(x['id'] for x in doc['network']['not_applicable'])}.", "",
          "## Completion (TCO = DOB Temporary Certificate of Occupancy)", "",
          _row("scenario", "TCO", "final CO", "interior ready", "working days", "before review 1"),
          _row("---", "---", "---", "---", "---", "---")]
    for s in SCENARIOS:
        L.append(_row(s, c[s]["tco"], c[s]["final_co"], c[s]["interior_ready"], c[s]["tco_working_days"],
                      BEFORE_REVIEW_1[s]))
    st = doc["stress_test"]
    L.append(_row("stress test (not a forecast)", st["tco"], st["final_co"], st["interior_ready"],
                  st["tco_working_days"], "(was the conservative)"))
    L += [""] + [f"- **{s}**: {doc['scenario_definitions'][s]['story']}" for s in ALL_RUNS] + [""]
    m = doc.get("model_run") or {}
    if m.get("completion"):
        mm = m["model"] or {}
        L += [f"With `model/588_model.json` (sha256 {str(mm.get('sha256', ''))[:12]}...) laid over the provisional "
              "state: TCO " + ", ".join(f"{s} {m['completion'][s]['tco']}" for s in SCENARIOS)
              + f"; stress {m['stress_test']['tco']}. {len(m['state_changes_vs_provisional'])} state changes vs the "
              "provisional state ("
              + ("same TCO in every scenario" if all(m["completion"][s]["tco"] == c[s]["tco"] for s in SCENARIOS)
                 else "TCO differs, see model_run") + "). " + " ".join(m["notes"]), ""]
    L += ["## Sensitivity (normal TCO)", "",
          _row("EIFS crew per working day", "TCO", ""), _row("---", "---", "---")]
    L += [_row(r["crew"], r["tco"], r["note"]) for r in sens.get("eifs_crew", [])]
    L += ["", _row("DOB request-to-result wait (plumbing and electrical), working days", "TCO"), _row("---", "---")]
    L += [_row(r["working_days"], r["tco"]) for r in sens.get("dob_wait", [])]
    L += ["", "## Critical path (normal)", ""]
    L += [f"- {x['name']} ({x['id']}): {x['start']} to {x['finish']}" for x in doc["critical_path"]]
    L += ["", "By scenario: " + "; ".join(f"{s}: {' > '.join(doc['critical_path_by_scenario'][s][:6])}"
                                          + (" ..." if len(doc['critical_path_by_scenario'][s]) > 6 else "")
                                          for s in SCENARIOS), ""]
    sc = doc["superstructure_cycles"]
    L += ["## Superstructure cycles (3/5/7-day)", "", sc["answer"], ""] + [f"- {w}" for w in sc["why"]] + [""]
    L += ["## State contradictions (reported, not hidden)", ""]
    L += [f"- {x['kind']}: {x['what']}. Resolution: {x['resolution']}." for x in doc["state_contradictions"][:12]]
    if not doc["state_contradictions"]:
        L.append("- none")
    neg = [x for x in doc["state_contradictions"] if x["kind"] == "negative_float"]
    L += [f"- Negative float: {len(neg)} activities.", ""]
    L += ["## Next three weeks (normal)", ""]
    nx = sorted(doc["next_three_weeks"], key=lambda x: (not x["critical"], x["kind"] != "regulatory",
                                                         x["total_float_days"], x["start"]))
    L += [f"- {x['start']}..{x['finish']} {x['name']}{' [CRITICAL]' if x['critical'] else ''} "
          f"(float {x['total_float_days']} wd, state {x['state']} ({x['evidence']}))" for x in nx[:22]]
    L += ["", "## Bottlenecks", ""]
    b = doc["bottlenecks"]
    L += ["- Critical-path effort by party (normal, working days): "
          + ", ".join(f"{k} {v:g}" for k, v in b["critical_path_effort_by_party"].items())]
    L += ["- Thin crews: " + ", ".join(f"{t['company']} {t['avg']:g}/day ({t['source']}, n={t['n_days']})"
                                      for t in b["thin_crews"])]
    L += ["", "## Acceleration levers (normal; alone, then cumulative in this order)", "",
          _row("lever", "TCO alone", "saved alone (wd)", "TCO cumulative", "saved by adding (wd)", "requires"),
          _row("---", "---", "---", "---", "---", "---")]
    for lv in doc["acceleration_levers"]:
        L.append(_row(lv["lever"], lv["tco_alone"], lv["working_days_saved_alone"], lv["tco_cumulative"],
                      lv["working_days_saved_by_adding"], "; ".join(lv["requires"])))
    L += ["", "## Unknown state as branches (normal)", "",
          _row("unknown", "if A", "TCO / interior", "if B", "TCO / interior"), _row("---", "---", "---", "---", "---")]
    for br in doc["branches"]:
        L.append(_row(br["unknown"], br["if_a"], f"{br['tco_if_a']} / {br['interior_ready_if_a']}", br["if_b"],
                      f"{br['tco_if_b']} / {br['interior_ready_if_b']}"))
    cn = doc["concurrency"]["normal"]
    L += ["", "## Concurrency (normal)", "",
          f"Site peak about {round(cn['site_peak_workers'])} workers on {cn['site_peak_day']}. "
          f"{cn['space_links_added']} floor-plate links added by levelling."]
    for s in SCENARIOS:
        over = [z for z, v in doc["concurrency"][s]["per_floor_peak"].items() if not v["within_limits"]]
        if over:
            L.append(f"- {s}: over the floor limit on {', '.join(over)} only where work already under way is not moved.")
    for z, v in cn["per_floor_peak"].items():
        L.append(f"- {z}: {v['trades']} trades / {round(v['workers'])} workers on {v['day']} (limits "
                 f"{v['limit_trades']} / {round(v['limit_workers'])}): {', '.join(v['activities'])}")
    L += [f"- {w}" for w in cn["why_feasible"]]
    L += ["", "## What is measured, derived or assumed", "",
          "Assumptions by tag: " + ", ".join(f"{k} {v}" for k, v in sorted(tags.items())) + "."]
    for a in doc["assumptions"]:
        if a["tag"] in ("measured", "derived-report"):
            L.append(f"- [{a['tag']}] {a['label']}: normal {a['values']['normal']:g}. {a['basis'].split('. fast')[0]}")
    L += ["", "## What changed after review 1 (2026-11-10)", "",
          "Before -> after TCO: " + "; ".join(f"{s} {BEFORE_REVIEW_1[s]} -> {c[s]['tco']}" for s in SCENARIOS)
          + f"; the old conservative (every worst value at once) is now the stress test: {st['tco']}.",
          "- Crews: MEASURED only from original filed daily-log rows (records/audit_flags.jsonl, is_original and not a "
          "duplicate, >= 3 dates): " + ", ".join(a["label"].split(", ", 1)[1].split(" (")[0] for a in doc["assumptions"]
                                                  if a["tag"] == "measured" and a["id"].startswith("crew_"))
          + ". Every other crew is a derived-report figure (unaudited) or an assumption, and says so. The order "
          "in which J&P works the elevations is not on record; one crew works one elevation at a time.",
          "- Sequencing: insulation waits for the DOB electrical and plumbing ROUGH INSPECTIONS on its floor; "
          "firestopping split into pre-board (concealed penetrations, inspected before board) and post-board "
          "(membrane penetrations, rated joints, head-of-wall, inspected before tape); work under way still waits "
          "for its inspect-before-cover gate (remaining work after the gate), and the overlap is reported as a "
          "state contradiction.",
          "- Facade: the brick/EIFS split is a branch; the lot-line wall below neighbour No. 586's 2 storeys gets no "
          "EIFS; the other side's neighbour is an assumption with a branch; adjoining-roof access activities added; "
          "window and PTAC openings deducted; bulkhead walls added.",
          "- Links: every link carries a basis; removed or replaced: "
          + "; ".join(f"{r['from']} -> {r['to']} ({r['why'].split(':')[0]})" for r in doc["link_review"]["removed"])
          + ".",
          "- An inferred or reported inspection pass is never a pass in any scenario; such gates get a "
          "passed/pending branch and keep their '(inferred)' label.",
          "- Conservative is one adverse story (above); a failed inspection adds one re-test cycle at the normal "
          "wait, not a doubled lead; the TCO review is no longer doubled.",
          "- Done work imposes nothing on remaining work, so no negative float; a done activity with an open "
          "prerequisite is reported as a contradiction.", "", "## Notes", ""] + [f"- {n}" for n in doc["notes"]]
    dl = [d for d in doc["deadline_checks"] if d["scenario"] == "normal"]
    L += [f"- Deadline {d['deadline']}: {acts[d['id']]['name']}" for d in dl]
    L += ["", "Re-run: `PYTHONUTF8=1 python backend/scripts/intel_588_schedule.py C:/Users/asddd/bv-worktrees/intel588-data`", ""]
    return "\n".join(L)
