"""Schedule history: what the schedules of FINISHED jobs say work really took.

LeveLog's own records cannot yet teach how long work takes (one live job, no
finished one). The schedules of jobs already built can: each activity that
was finished carries the day it really started and the day it really ended.
This module turns one imported schedule (the normalised document of
lib/schedule_import.py) into DURATION SAMPLES, and many jobs' samples into a
range per kind of work. It is a reader, like the importer: it never works out
a value the file does not carry.

The rules this module keeps (each is a test in tests/test_schedule_history.py):

  * A SAMPLE is one finished activity: a row that is not a heading (summary)
    and not a milestone and has BOTH an actual start and an actual finish.
    A missing actual date means no sample. Planned, scheduled and baseline
    dates are never used in place of an actual date, and "100% complete" with
    no dates is not a duration. An actual finish before its start, or after
    the file's own status date, is not a sample either (it is counted).
  * WORKING DAYS are Monday to Friday, both ends counted. Holidays are not
    taken out (the file's calendar is not in the document). The same ruler
    measures the plan and the actual, so their ratio is like for like.
  * THE PLAN an actual is compared with is the baseline dates of that
    activity. With no baseline, the file's scheduled dates are used ONLY when
    the file keeps them apart from the actuals (on at least one finished
    activity they differ): MS Project and P6 overwrite an activity's scheduled
    dates and its duration with the actuals when it is finished, and a "plan"
    that is the actual would report every job as exactly on time. A P6 file's
    original duration is used when its target dates are missing. Otherwise
    there is no plan and no ratio.
  * THE KIND OF WORK comes from lib/progress_stages.py: the same matchers the
    progress board uses on a daily-log line (`families_of`), given the
    activity name as the work and the nearest WBS heading that names a trade
    as the crew. The name's own trade words decide; the heading decides when
    the name has none. The project's own row is not a heading ("Steel Tower"
    is an address, not a trade). No second list of trade words lives here.
        - An activity that names more than one kind of work ("Frame and
          sheetrock", "MEP rough-in", "Rough-in and fixtures") is `several_kinds`:
          its days belong to neither, so it is in no kind's range. So is one
          whose words point two ways: two trades' words in one phrase
          ("Waterproof foundation walls" is flooring's word and the
          foundation's; the board takes whichever comes first, which is a
          guess a duration cannot afford), or a trade word under headings
          that name only other trades ("Piping" under "Sprinkler").
        - Paperwork, buying, deliveries, inspections and tests (submittals,
          shop drawings, "Deliver windows", "Plumbing inspection") are
          `not_building_work`: a schedule is full of them, a daily log never
          is, and a 60-day window order is not 60 days of window work.
        - Anything else the matchers do not recognise is `unclassified`: kept,
          counted, listed by name so the word lists can learn it. Never guessed.
  * FLOORS are the floors the name states, else the floors the nearest heading
    states ("3rd Floor > Framing"), read by the two readers the codebase
    already has (progress_stages.floors_of_text, schedule_plan's single-floor
    reader). Those readers do not understand every spelling ("floors 2, 3 &
    4" reads as floor 2 alone); a name that mentions a floor number they did
    not return gets NO floors (`floors_unclear`), because a third of the
    floors is three times the days per floor. An activity that states no
    floor is never divided by the building's storeys: "Plumbing" may be the
    cellar alone.
  * A RANGE (10th percentile, median, 90th percentile) is given for a kind of
    work only from at least MIN_SAMPLES examples drawn from at least MIN_JOBS
    jobs. Below that the answer is NOT_ENOUGH and no number at all.

A sample (every figure the file does not support is None):

    {"job", "source_name", "sha256", "format", "confidence", "activity_id",
     "name", "wbs_path": [heading, ...], "status", "kind", "kind_label",
     "kinds": [...], "floors": [...], "floors_from": "name"|"wbs"|None,
     "floors_unclear": bool, "actual_start", "actual_finish",
     "actual_working_days", "calendar_days", "planned_working_days",
     "planned_from": "baseline_dates"|"scheduled_dates"|"file_duration"|None,
     "actual_over_planned", "file_duration_days", "days_per_floor",
     "area_sqft", "days_per_1000_sqft", "storeys", "gross_sqft",
     "footprint_sqft", "building_type"}

Pure: no database, no network, no model, no file is opened.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import progress_stages as S
from lib import schedule_plan as P

#: A range is refused below this many examples...
MIN_SAMPLES = 10
#: ...or when they all come from fewer jobs than this: ten floors of one job
#: describe that job, not the next one.
MIN_JOBS = 2
NOT_ENOUGH = "not enough finished examples"
NOT_ENOUGH_ES = "no hay suficientes ejemplos terminados"

CLASSIFIED, SEVERAL, NOT_BUILDING, UNCLASSIFIED = (
    "classified", "several_kinds", "not_building_work", "unclassified")  # fmt: skip
STATUSES = (CLASSIFIED, SEVERAL, NOT_BUILDING, UNCLASSIFIED)

#: The measures a kind of work is summarised by, and the decimals each keeps.
MEASURES: Dict[str, int] = {
    "days_per_floor": 1,       # one finished activity's working days / the floors it states
    "floor_span_days": 1,      # one floor of one job: first start to last finish of that kind
    "days_per_1000_sqft": 2,   # the same activity's days / (its floors x the floor area), area known
    "days_no_floor": 1,        # working days of an activity that states no floor (whole activity)
    "actual_over_planned": 2,  # actual working days / planned working days
}

_NO_SAMPLE = ("no_actual_dates", "no_actual_finish", "no_actual_start", "dates_out_of_order",
              "finish_after_status_date")  # fmt: skip

#: Schedule rows that are not building work. Not a list of trades: a kind of
#: row a daily log never has, so progress_stages has no word for it.
_NOT_BUILDING = re.compile(
    r"\bsubmi(?:t|ssion)|\bshop ?drawings?\b|\bdrawings?\b|\bapprov|\bprocur|\bpurchas"
    r"|\b(?:pre-?)?order(?:s|ed|ing)?\b|\bfabricat|\b(?:long.?)?lead.?time|\bdeliver|\bmobili[sz]"
    r"|\bpermit|\binspect|\bsign.?offs?\b|\breview|\bbuy.?out\b|\baward|\bbid(?:s|ding)?\b|\brfis?\b"
    r"|\bmock.?ups?\b|\bnotice to proceed\b|\bntp\b|\bmeetings?\b|\bsurvey|\btest(?:s|ed|ing)?\b"
    r"|\bcommission",
    re.IGNORECASE,
)
#: "MEP" is three trades. The board's weak word for it is HVAC, which is right
#: for a crew and wrong for "MEP rough-in": the token never decides a kind here.
_MEP = re.compile(r"\bm\.?e\.?p\.?(?:s|fp)?(?![A-Za-z])", re.IGNORECASE)
_MEP_KINDS = ["electrical", "plumbing", "hvac"]

# Floor numbers a name MENTIONS (not a reader: it only vetoes the shared ones).
_N = r"\d{1,2}(?:st|nd|rd|th)?"
_SEP_FEW = r"(?:,|&|/|\band\b)"
_SEP_ANY = r"(?:,|&|/|-|–|\band\b|\bto\b|\bthru\b|\bthrough\b)"
_MENTIONS = (
    re.compile(rf"(?<![A-Za-z])(?:floors?|flrs?|fls?|levels?|lvls?)\.?\s*#?\s*({_N}(?:\s*{_SEP_ANY}\s*{_N})*)", re.I),
    re.compile(rf"(?<![A-Za-z0-9])({_N}(?:\s*{_SEP_ANY}\s*{_N})*)\s*(?:floors|flrs|fls|levels|lvls)(?![A-Za-z])", re.I),
    re.compile(rf"(?<![A-Za-z0-9])({_N}(?:\s*{_SEP_FEW}\s*{_N})*)\s*(?:floor|flr|fl|level|lvl)(?![A-Za-z])", re.I),
    re.compile(r"(?<![A-Za-z0-9])L(\d{1,2})(?![A-Za-z0-9])"),
)
_SYNTHETIC_ID = re.compile(r"^row\d+$")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def working_days(start: date, finish: date) -> int:
    """Monday-to-Friday days from `start` to `finish`, both counted."""
    if finish < start:
        return 0
    weeks, rest = divmod((finish - start).days + 1, 7)
    return weeks * 5 + sum(1 for i in range(rest) if (start.weekday() + i) % 7 < 5)


def floors_of_name(text: Any) -> Tuple[List[int], bool]:
    """(floors, unclear). Floors only as the shared readers return them; when
    the text mentions a floor number they did not return, ([], True)."""
    t = str(text or "")
    found = set(S.floors_of_text(t))
    single = P._floor_of(t)
    if single:
        found.add(single)
    mentioned = {int(n) for rx in _MENTIONS for m in rx.finditer(t) for n in re.findall(r"\d{1,2}", m.group(1))}
    mentioned.discard(0)
    if not mentioned <= found:
        return [], True
    return sorted(found), False


def _plain(name: Any) -> str:
    """A name without its floor, for counting the same work across floors."""
    t = S.FLOOR_RE.sub(" ", str(name or ""))
    for rx in _MENTIONS:
        t = rx.sub(" ", t)
    return " ".join(t.lower().split()).strip(" -–:,.#")


def _trades_named(text: str, *, weak: bool = False) -> List[str]:
    """Every kind of work whose own (STRONG) words are in the text, in the
    board's order; with `weak`, its weak words too."""
    return [key for key, _label, strong, wk in S.FAMILIES
            if (strong and strong.search(text)) or (weak and wk and wk.search(text))]


def classify(name: Any, path: Sequence[str] = ()) -> Tuple[str, List[str]]:
    """(status, kinds) for an activity name under its WBS headings."""
    name = str(name or "")
    if _NOT_BUILDING.search(" > ".join([*path, name])):
        return NOT_BUILDING, []
    mep = bool(_MEP.search(name)) or any(_MEP.search(p) for p in path)
    headings = [_MEP.sub(" ", p) for p in path]
    # the nearest heading that names a trade stands where a crew's trade does
    heading = next((h for h in reversed(headings) if S.crew_family(h)), "")
    over = S.crew_family(heading) if heading else None
    allowed = {k for h in headings for k in _trades_named(h, weak=True)}
    fams = S.families_of({"trade": heading, "company": "", "work": _MEP.sub(" ", name), "work_trades": None})
    found: List[str] = []
    for fam, phrase in fams:
        own = _trades_named(phrase)
        if len(own) > 1:
            found.extend(own)        # two trades' words in one phrase: not picked between
        else:
            found.append(fam)
            if own and over and own[0] not in allowed:
                found.append(over)   # the name says one trade, every heading above it another
    kinds = list(dict.fromkeys(found))
    if len(kinds) == 1:
        return CLASSIFIED, kinds
    if kinds:
        return SEVERAL, kinds
    return (SEVERAL, list(_MEP_KINDS)) if mep else (UNCLASSIFIED, [])


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if v > 0 else None


def job_facts(job: Optional[Dict[str, Any]], doc: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The job's facts as given: a missing or unusable one is None, never filled in."""
    job = job or {}
    doc = doc or {}
    storeys = _num(job.get("storeys"))
    return {
        "name": str(job.get("name") or doc.get("project_name") or doc.get("source_name") or "").strip(),
        "storeys": int(storeys) if storeys and storeys == int(storeys) else None,
        "gross_sqft": _num(job.get("gross_sqft")),
        "footprint_sqft": _num(job.get("footprint_sqft")),
        "building_type": str(job.get("building_type") or "").strip() or None,
    }


def _floor_area(facts: Dict[str, Any]) -> Optional[float]:
    """The area of one floor: the footprint, else gross area / storeys."""
    if facts["footprint_sqft"]:
        return facts["footprint_sqft"]
    if facts["gross_sqft"] and facts["storeys"]:
        return facts["gross_sqft"] / facts["storeys"]
    return None


def _rows_with_headings(acts: List[Dict[str, Any]]) -> Iterable[Tuple[Dict[str, Any], List[str]]]:
    """Each non-summary row with the names of the summary rows it sits under
    (outermost first). The single project row is not a heading."""
    project = P._project_row(acts)
    stack: List[Tuple[int, str]] = []
    for a in acts:
        level = int(a.get("level") or 0)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if a.get("kind") == "summary":
            if a is not project:
                stack.append((level, str(a.get("name") or "")))
            continue
        yield a, [n for _lvl, n in stack]


# ---------------------------------------------------------------------------
# One schedule file -> samples
# ---------------------------------------------------------------------------


def samples_of(doc: Dict[str, Any], job: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The duration samples of one imported schedule (module docstring).

    `job`: {"name", "storeys", "gross_sqft", "footprint_sqft", "building_type"},
    all optional. Returns {"job", "facts", "files", "source_name", "data_date",
    "samples", "counts", "job_finished", "notes"}.
    """
    acts: List[Dict[str, Any]] = list(doc.get("activities") or [])
    facts = job_facts(job, doc)
    floor_area = _floor_area(facts)
    data_date = P._d(doc.get("data_date"))
    rows = list(_rows_with_headings(acts))

    def actuals(a: Dict[str, Any]) -> Tuple[Optional[date], Optional[date]]:
        return P._d(a.get("actual_start")), P._d(a.get("actual_finish"))

    # Does the file keep its scheduled dates apart from its actual dates?
    separate_plan = False
    for a, _path in rows:
        s, f = actuals(a)
        cs, cf = P._d(a.get("current_start")), P._d(a.get("current_finish"))
        if s and f and cs and cf and (cs, cf) != (s, f):
            separate_plan = True
            break

    counts: Dict[str, Any] = {
        "rows": len(acts),
        "summary_rows": sum(1 for a in acts if a.get("kind") == "summary"),
        "milestones": sum(1 for a in acts if a.get("kind") == "milestone"),
        "activities": 0,
        "finished": 0,
        "no_sample": dict.fromkeys(_NO_SAMPLE, 0),
        "by_status": dict.fromkeys(STATUSES, 0),
        "floors_unclear": 0,
    }
    samples: List[Dict[str, Any]] = []
    for a, path in rows:
        if a.get("kind") == "milestone":
            continue
        counts["activities"] += 1
        start, finish = actuals(a)
        if not (start and finish):
            why = "no_actual_dates" if not (start or finish) else ("no_actual_finish" if start else "no_actual_start")
            counts["no_sample"][why] += 1
            continue
        if finish < start:
            counts["no_sample"]["dates_out_of_order"] += 1
            continue
        if data_date and finish > data_date:
            counts["no_sample"]["finish_after_status_date"] += 1
            continue

        name = str(a.get("name") or "")
        status, kinds = classify(name, path)
        kind = kinds[0] if status == CLASSIFIED else None

        floors, unclear = floors_of_name(name)
        floors_from: Optional[str] = "name" if floors else None
        if not floors and not unclear:
            for heading in reversed(path):
                floors, unclear = floors_of_name(heading)
                if floors or unclear:
                    floors_from = "wbs" if floors else None
                    break

        actual_days = working_days(start, finish)
        planned: Optional[float] = None
        planned_from: Optional[str] = None
        bs, bf = P._d(a.get("baseline_start")), P._d(a.get("baseline_finish"))
        cs, cf = P._d(a.get("current_start")), P._d(a.get("current_finish"))
        file_duration = a.get("duration_days") if isinstance(a.get("duration_days"), (int, float)) else None
        if bs and bf and bs <= bf:
            planned, planned_from = working_days(bs, bf), "baseline_dates"
        elif separate_plan and cs and cf and cs <= cf:
            planned, planned_from = working_days(cs, cf), "scheduled_dates"
        elif doc.get("format") == "xer" and file_duration:
            planned, planned_from = float(file_duration), "file_duration"

        area = floor_area * len(floors) if floor_area and floors else None
        samples.append({
            "job": facts["name"],
            "source_name": doc.get("source_name"),
            "sha256": doc.get("sha256"),
            "format": doc.get("format"),
            "confidence": doc.get("confidence"),
            "activity_id": a.get("id"),
            "name": name,
            "wbs_path": list(path),
            "status": status,
            "kind": kind,
            "kind_label": S.LABEL.get(kind) if kind else None,
            "kinds": kinds,
            "floors": floors,
            "floors_from": floors_from,
            "floors_unclear": unclear,
            "actual_start": start.isoformat(),
            "actual_finish": finish.isoformat(),
            "actual_working_days": actual_days,
            "calendar_days": (finish - start).days + 1,
            "planned_working_days": planned,
            "planned_from": planned_from,
            "actual_over_planned": round(actual_days / planned, 3) if planned else None,
            "file_duration_days": file_duration,
            "days_per_floor": round(actual_days / len(floors), 2) if floors else None,
            "area_sqft": area,
            "days_per_1000_sqft": round(actual_days / (area / 1000.0), 2) if area else None,
            "storeys": facts["storeys"],
            "gross_sqft": facts["gross_sqft"],
            "footprint_sqft": facts["footprint_sqft"],
            "building_type": facts["building_type"],
        })  # fmt: skip
        counts["by_status"][status] += 1
        counts["floors_unclear"] += 1 if unclear else 0
    counts["finished"] = len(samples)

    notes: List[str] = []
    if doc.get("confidence") == "extracted":
        notes.append("Read from a PDF table: a person has not checked the extraction.")
    if samples and not any(s["planned_working_days"] for s in samples):
        notes.append("The file keeps no plan apart from its actual dates, so actual / planned is not given.")
    return {
        "job": facts["name"],
        "facts": facts,
        "files": [doc.get("source_name")],
        "source_name": doc.get("source_name"),
        "data_date": doc.get("data_date"),
        "samples": samples,
        "counts": counts,
        "job_finished": counts["activities"] > 0 and counts["finished"] == counts["activities"],
        "notes": notes,
    }


def _same_activity(s: Dict[str, Any]) -> Tuple[Any, ...]:
    aid = str(s.get("activity_id") or "")
    return ("" if _SYNTHETIC_ID.match(aid) else aid, " ".join(s["name"].lower().split()), tuple(s["wbs_path"]))


def merge_updates(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Several files of ONE job (monthly updates) -> one result.

    Each activity is counted once, as the newest file that has it finished
    states it (newest = latest status date, then file name). An activity only
    an older file has is kept. The counts of rows and of what is not finished
    are the newest file's.
    """
    if not results:
        raise ValueError("no files")
    ordered = sorted(results, key=lambda r: (str(r.get("data_date") or ""), str(r.get("source_name") or "")))
    newest = ordered[-1]
    if len(ordered) == 1:
        return newest
    by_key: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for res in ordered:  # oldest first: a later file replaces what an earlier one said
        mine: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = defaultdict(list)
        for s in res["samples"]:
            mine[_same_activity(s)].append(s)
        by_key.update(mine)
    samples = [s for group in by_key.values() for s in group]
    samples.sort(key=lambda s: (s["actual_start"], s["actual_finish"], s["name"]))
    counts = dict(newest["counts"])
    counts["finished"] = len(samples)
    counts["by_status"] = {st: sum(1 for s in samples if s["status"] == st) for st in STATUSES}
    counts["floors_unclear"] = sum(1 for s in samples if s["floors_unclear"])
    notes = list(dict.fromkeys(n for r in ordered for n in r["notes"]))
    notes.append(f"{len(ordered)} files of this job were read; each activity is counted once, from the newest "
                 "file that has it finished.")
    if not all(r.get("data_date") for r in ordered):
        notes.append("Not every file states a status date; where it is missing the files were put in order by name.")
    return {
        "job": newest["job"],
        "facts": newest["facts"],
        "files": [r["source_name"] for r in ordered],
        "source_name": newest["source_name"],
        "data_date": newest["data_date"],
        "samples": samples,
        "counts": counts,
        "job_finished": newest["job_finished"],
        "notes": notes,
    }


def overlapping_jobs(samples: Iterable[Dict[str, Any]], *, min_shared: int = 5) -> List[Dict[str, Any]]:
    """Pairs of jobs that share most of their finished activities (same name,
    same actual dates): almost certainly one job read twice under two names,
    which would count every example twice and pass for two jobs."""
    seen: Dict[str, set] = defaultdict(set)
    for s in samples:
        seen[s["job"]].add((" ".join(s["name"].lower().split()), s["actual_start"], s["actual_finish"]))
    out = []
    jobs = sorted(seen)
    for i, a in enumerate(jobs):
        for b in jobs[i + 1:]:
            shared = len(seen[a] & seen[b])
            if shared >= min_shared and shared * 2 >= min(len(seen[a]), len(seen[b])):
                out.append({"jobs": [a, b], "shared": shared})
    return out


# ---------------------------------------------------------------------------
# Many jobs -> a range per kind of work
# ---------------------------------------------------------------------------


def _percentile(sorted_vals: List[float], p: float) -> float:
    """Linear interpolation between the two nearest values (the usual one)."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * p / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _stat(pairs: List[Tuple[float, str]], digits: int, min_samples: int, min_jobs: int) -> Dict[str, Any]:
    vals = sorted(v for v, _job in pairs)
    out: Dict[str, Any] = {"n": len(vals), "jobs": len({j for _v, j in pairs})}
    if out["n"] < max(1, min_samples) or out["jobs"] < min_jobs:
        out.update(enough=False, note=NOT_ENOUGH, note_es=NOT_ENOUGH_ES)
        return out
    out.update(enough=True, p10=round(_percentile(vals, 10), digits), median=round(_percentile(vals, 50), digits),
               p90=round(_percentile(vals, 90), digits))  # fmt: skip
    return out


def common_names(samples: Iterable[Dict[str, Any]], status: str, top: int = 30,
                 *, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """The most common activity names (floor removed) with this status."""
    c: Counter = Counter()
    for s in samples:
        if s["status"] == status and (kind is None or s["kind"] == kind):
            c[_plain(s["name"]) or s["name"].lower()] += 1
    return [{"name": n, "count": k} for n, k in sorted(c.items(), key=lambda x: (-x[1], x[0]))[:top]]


def unclear_floor_names(samples: Iterable[Dict[str, Any]], top: int = 10) -> List[str]:
    """The most common names whose floor wording the readers did not understand."""
    c: Counter = Counter()
    for s in samples:
        if s["floors_unclear"]:
            c[" ".join(s["name"].lower().split())] += 1
    return [n for n, _k in sorted(c.items(), key=lambda x: (-x[1], x[0]))[:top]]


def summarise(samples: Iterable[Dict[str, Any]], *, min_samples: int = MIN_SAMPLES,
              min_jobs: int = MIN_JOBS) -> Dict[str, Any]:
    """Per kind of work: how many examples, from how many jobs, and for each
    measure in MEASURES the 10th percentile, median and 90th percentile -- or
    NOT_ENOUGH and no number when there are fewer than `min_samples` examples
    or they come from fewer than `min_jobs` jobs. Every kind the progress
    board knows is listed, with or without examples. `ready`: the kind has a
    range of days to forecast from (per floor; or per whole activity for work
    that is not built floor by floor, progress_stages.BUILDING_WIDE)."""
    samples = list(samples)
    by_kind: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in samples:
        if s["status"] == CLASSIFIED and s["kind"]:
            by_kind[s["kind"]].append(s)

    kinds: List[Dict[str, Any]] = []
    too_few: List[str] = []
    for kind in sorted(S.LABEL, key=lambda k: S.ORDER[k]):
        ss = by_kind.get(kind, [])
        pairs: Dict[str, List[Tuple[float, str]]] = {m: [] for m in MEASURES}
        on_floor: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
        for s in ss:
            if s["days_per_floor"] is not None:
                pairs["days_per_floor"].append((s["days_per_floor"], s["job"]))
            if s["days_per_1000_sqft"] is not None:
                pairs["days_per_1000_sqft"].append((s["days_per_1000_sqft"], s["job"]))
            if not s["floors"] and not s["floors_unclear"]:
                pairs["days_no_floor"].append((float(s["actual_working_days"]), s["job"]))
            if s["actual_over_planned"] is not None:
                pairs["actual_over_planned"].append((s["actual_over_planned"], s["job"]))
            if len(s["floors"]) == 1:
                on_floor[(s["job"], s["floors"][0])].append(s)
        for (job, _floor), group in on_floor.items():
            first = min(date.fromisoformat(s["actual_start"]) for s in group)
            last = max(date.fromisoformat(s["actual_finish"]) for s in group)
            pairs["floor_span_days"].append((float(working_days(first, last)), job))
        measures = {m: _stat(pairs[m], digits, min_samples, min_jobs) for m, digits in MEASURES.items()}
        base = kind[:-len("_finish")] if kind.endswith("_finish") else kind
        ready = measures["days_per_floor"]["enough"] or (
            base in S.BUILDING_WIDE and measures["days_no_floor"]["enough"])
        if not ready:
            too_few.append(kind)
        kinds.append({
            "kind": kind,
            "label": S.LABEL[kind],
            "samples": len(ss),
            "jobs": len({s["job"] for s in ss}),
            "from_pdf": sum(1 for s in ss if s.get("confidence") == "extracted"),
            "ready": bool(ready),
            "measures": measures,
            "examples": [x["name"] for x in common_names(ss, CLASSIFIED, 8)],
        })
    return {
        "min_samples": min_samples,
        "min_jobs": min_jobs,
        "jobs": len({s["job"] for s in samples}),
        "samples": len(samples),
        "classified": sum(len(v) for v in by_kind.values()),
        "from_pdf": sum(k["from_pdf"] for k in kinds),
        "kinds": kinds,
        "too_few": too_few,
        "not_summarised": {st: sum(1 for s in samples if s["status"] == st) for st in STATUSES if st != CLASSIFIED},
    }
