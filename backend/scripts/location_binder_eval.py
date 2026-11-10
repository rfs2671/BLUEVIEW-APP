"""READ-ONLY. How often lib/location_binder places a real location string right,
and how often it abstains, per source, for ONE job.

Step 1, dump every DISTINCT location string the job holds, with its count, per
source, to a CSV whose label columns are EMPTY (the binder's own answer is NOT
in the file, so a labeler is not anchored on it), and the project's frame (its
levels and plan tags, from server._project_place_frame) beside it:

    railway run --service Blueview2 --environment production \\
        python backend/scripts/location_binder_eval.py dump --project 588 --out locs.csv

    sources: log_row (crew rows' work_locations), pour_location (concrete logs),
    punch_floor / punch_area (punch items), photo_where / photo_visible_text
    (photo index), dob_work_on_floor (DOB NOW Build permits for the project's
    BIN, read from NYC Open Data, public; --no-dob skips it: dob_logs does not
    store the field)

Step 2, a person fills `true_levels` (tokens such as FLOOR_3, ROOF, CELLAR,
several joined by |, or bare numbers 1|2|3) and `true_space` (a plan tag such as
3B, or EXTERIOR). "-" in both says no place can be read from the text. A row
with both columns blank is not scored.

Step 3, score. Offline: no database, only the CSV and the frame file:

    python backend/scripts/location_binder_eval.py score locs.csv --frame locs.frame.json

    precision  right / answered (everything the binder claimed is true)
    coverage   answered / rows whose label names a place
    abstain    abstentions / labeled rows
    each with its 95% Wilson interval (lib/benchmark_stats), per source and
    overall, over DISTINCT strings: repeats of one string are not independent
    trials. Occurrence-weighted rates are printed as points, without intervals.

No names and no phone numbers: no person, company or worker field is read; a
phone number or email inside a string is masked; a photo's legible text is kept
only when it has a digit or a place word (a brand or a name on a sign is
dropped and counted). Nothing is written to the database: every write method
of the drivers raises before the application is imported.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_helpers import FieldNotInSample, describe, require_fields  # noqa: E402
from lib import benchmark_stats as S  # noqa: E402
from lib import location_binder as B  # noqa: E402

COLUMNS = ("source", "text", "count", "true_levels", "true_space")
_PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_PLACE_WORD = re.compile(r"\b(?:floor|flr|fl|level|lvl|roof|cellar|basement|mezz\w*|bulkhead|apt|unit|room|rm|stair\w*"
                         r"|corridor|hall\w*|lobby|ground|piso|s[oó]tano|techo|exterior|facade|outside)\b", re.I)


def scrub(text: Any) -> str:
    return " ".join(_EMAIL.sub("[email]", _PHONE.sub("[phone]", str(text or ""))).split())


# ── STEP 1: DUMP ───────────────────────────────────────────────────────────

def _present(rows: Sequence[Dict[str, Any]], name: str, *fields: str) -> List[str]:
    """The fields a source's sample actually carries. An absent field is
    reported, never counted as zero."""
    print(f"[{name}]\n{describe(rows, *fields)}")
    out = []
    for f in fields:
        try:
            require_fields(rows, f)
            out.append(f)
        except FieldNotInSample:
            print(f"  {name}.{f}: ABSENT, this source is not read")
    return out


def _keep(rows: Sequence[Dict[str, Any]], name: str, *fields: str) -> List[Dict[str, Any]]:
    """The rows, cut to the fields their sample carries; [] when none."""
    if not rows:
        print(f"[{name}] 0 rows")
        return []
    keep = _present(rows, name, *fields)
    return [{f: r.get(f) for f in keep} for r in rows] if keep else []


def collect(log_rows: Iterable[Dict[str, Any]], pour_rows: Iterable[Dict[str, Any]],
            punch_rows: Iterable[Dict[str, Any]], photo_rows: Iterable[Dict[str, Any]],
            dob_values: Iterable[Any]) -> Tuple[Dict[Tuple[str, str], int], int]:
    """({(source, text): count}, visible-text items dropped as not a place)."""
    counts: Dict[Tuple[str, str], int] = defaultdict(int)
    dropped = 0

    def add(source: str, value: Any) -> None:
        t = scrub(value)
        if t:
            counts[(source, t)] += 1

    for lg in log_rows:
        for a in ((lg.get("data") or {}).get("activities") or []):
            if isinstance(a, dict):
                add(B.LOG_ROW, a.get("work_locations"))
    for lg in pour_rows:
        add(B.POUR_LOCATION, (lg.get("data") or {}).get("pour_location"))
    for p in punch_rows:
        add(B.PUNCH_FLOOR, p.get("floor"))
        add(B.PUNCH_AREA, p.get("area"))
    for ph in photo_rows:
        add(B.PHOTO_WHERE, ph.get("where"))
        for item in (ph.get("visible_text") if isinstance(ph.get("visible_text"), list) else []):
            if re.search(r"\d", str(item)) or _PLACE_WORD.search(str(item)):
                add(B.PHOTO_VISIBLE_TEXT, item)
            elif str(item).strip():
                dropped += 1
    for v in dob_values:
        add(B.DOB_WORK_ON_FLOOR, v)
    return dict(counts), dropped


def write_dump(counts: Dict[Tuple[str, str], int], out: str) -> None:
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for (source, text), n in sorted(counts.items(), key=lambda kv: (B.SOURCES.index(kv[0][0]), -kv[1], kv[0][1])):
            w.writerow([source, text, n, "", ""])


def frame_for_file(frame: Dict[str, Any]) -> Dict[str, Any]:
    """The frame as stored beside the CSV: levels, tag keys and their levels,
    and the basis. No sheet titles, no names."""
    return {"levels": frame.get("levels") or [], "known": bool(frame.get("known")),
            "basis": frame.get("basis") or {}, "excluded": frame.get("excluded") or {},
            "spaces": {k: {"levels": list((v or {}).get("levels") or [])} for k, v in (frame.get("spaces") or {}).items()}}


async def run_dump(a: argparse.Namespace) -> int:
    import real_report_dry_run as R
    R.configure_environment()
    R.lock_database()
    import server
    project = await R.find_project(server, a.project, a.company)
    pid = str(project.get("_id"))
    print(f"project id {pid}")
    db = server.db
    alive = {"project_id": pid, "is_deleted": {"$ne": True}}
    logs = await db.logbooks.find({**alive, "log_type": "daily_jobsite"}, {"data.activities.work_locations": 1}).to_list(20000)
    pours = await db.logbooks.find({**alive, "log_type": "concrete_operations"}, {"data.pour_location": 1}).to_list(20000)
    punch_rows = await db.punch_items.find({"project_id": pid}, {"floor": 1, "area": 1}).to_list(50000)
    photos = await db.photo_index.find({"project_id": pid, "kind": "photo"}, {"where": 1, "visible_text": 1}).to_list(50000)
    # Each source is read only for the fields its sample carries.
    logs = _keep(logs, "logbooks daily_jobsite", "data")
    pours = _keep(pours, "logbooks concrete_operations", "data")
    punch_rows = _keep(punch_rows, "punch_items", "floor", "area")
    photos = _keep(photos, "photo_index", "where", "visible_text")
    dob: List[Any] = []
    bin_ = str(project.get("nyc_bin") or "").strip()
    if not a.no_dob and bin_:
        try:
            got = R._soda_get("rbx6-tga4", {"bin": bin_, "$select": "work_on_floor", "$limit": "2000"})
        except Exception as e:
            print(f"[dob] NYC Open Data not read ({type(e).__name__}): the DOB source is left out, not zero")
            got = []
        dob = [r.get("work_on_floor") for r in _keep(got, "DOB NOW Build permits (rbx6-tga4)", "work_on_floor")]
    elif not a.no_dob:
        print("[dob] the project has no BIN on record, so DOB work_on_floor is not read")
    counts, dropped = collect(logs, pours, punch_rows, photos, dob)
    frame = await server._project_place_frame(pid)
    write_dump(counts, a.out)
    frame_path = a.frame or re.sub(r"\.csv$", "", a.out) + ".frame.json"
    with open(frame_path, "w", encoding="utf-8") as fh:
        json.dump(frame_for_file(frame), fh, indent=1, sort_keys=True)
    per: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    for (source, _t), n in counts.items():
        per[source][0] += 1
        per[source][1] += n
    print(f"\nwrote {a.out}: distinct strings / occurrences per source")
    for source in B.SOURCES:
        if source in per:
            print(f"  {source}: {per[source][0]} / {per[source][1]}")
    print(f"  photo legible text dropped as not a place (no digit, no place word): {dropped}")
    tags = frame["spaces"]          # the frame is not a document; read outside the count
    print(f"wrote {frame_path}: levels {', '.join(frame['levels']) or '(none)'}; plan tags {len(tags)}; "
          f"known from the project or its plans: {frame['known']}")
    for lv in frame["levels"]:
        print(f"  {lv}: {', '.join(frame['basis'].get(lv) or [])}")
    for lv, why in sorted((frame.get("excluded") or {}).items()):
        print(f"  excluded {lv}: {why}")
    return 0


# ── STEP 3: SCORE ──────────────────────────────────────────────────────────

def score(rows: Iterable[Dict[str, Any]], frame: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{source or "ALL": {labeled, with_place, answered, right, wrong, abstain,
    precision, coverage, abstain_rate, weighted}} over labeled rows."""
    tally: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if not B.is_labeled(r.get("true_levels"), r.get("true_space")):
            continue
        res = B.bind(r.get("text"), frame.get("levels"), frame.get("spaces"), source=r.get("source") or B.FREE_TEXT)
        verdict = B.judge(res, r.get("true_levels"), r.get("true_space"))
        place = B.has_place(r.get("true_levels"), r.get("true_space"))
        try:
            n = max(1, int(r.get("count") or 1))
        except ValueError:
            n = 1
        for key in (str(r.get("source") or B.FREE_TEXT), "ALL"):
            t = tally.setdefault(key, {"labeled": 0, "with_place": 0, "answered": 0, "answered_with_place": 0,
                                       "right": 0, "wrong": 0, "abstain": 0, "w": defaultdict(int)})
            t["labeled"] += 1
            t["with_place"] += place
            t["answered"] += verdict != B.ABSTAIN
            t["answered_with_place"] += verdict != B.ABSTAIN and place
            t[verdict] += 1
            t["w"]["labeled"] += n
            t["w"]["answered"] += n * (verdict != B.ABSTAIN)
            t["w"]["right"] += n * (verdict == B.RIGHT)
            t["w"]["abstain"] += n * (verdict == B.ABSTAIN)
    for t in tally.values():
        t["precision"] = S.rate(t["right"], t["answered"])
        t["coverage"] = S.rate(t["answered_with_place"], t["with_place"])
        t["abstain_rate"] = S.rate(t["abstain"], t["labeled"])
        w = t.pop("w")
        t["weighted"] = {"precision": (w["right"] / w["answered"]) if w["answered"] else None,
                         "abstain": (w["abstain"] / w["labeled"]) if w["labeled"] else None}
    return tally


def wilson_text(r: Dict[str, Any]) -> str:
    if not r["n"]:
        return f"{r['k']}/0 (no rate)"
    lo, hi = r["wilson"]
    return f"{r['k']}/{r['n']} = {r['rate']:.3f} (95% Wilson {lo:.3f}-{hi:.3f})"


def report(tally: Dict[str, Dict[str, Any]]) -> str:
    out = []
    for key in [s for s in B.SOURCES if s in tally] + ["ALL"]:
        if key not in tally:
            continue
        t = tally[key]
        wp, wa = t["weighted"]["precision"], t["weighted"]["abstain"]
        out.append(f"{key}: {t['labeled']} labeled, {t['right']} right, {t['wrong']} wrong, {t['abstain']} abstained")
        out.append(f"  precision {wilson_text(t['precision'])}")
        out.append(f"  coverage  {wilson_text(t['coverage'])}")
        out.append(f"  abstain   {wilson_text(t['abstain_rate'])}")
        out.append("  by occurrence (points only): precision "
                   + (f"{wp:.3f}" if wp is not None else "n/a") + ", abstain " + (f"{wa:.3f}" if wa is not None else "n/a"))
    return "\n".join(out) if out else "no labeled rows: fill true_levels / true_space first"


def run_score(a: argparse.Namespace) -> int:
    frame_path = a.frame or re.sub(r"\.csv$", "", a.labels) + ".frame.json"
    with open(frame_path, encoding="utf-8") as fh:
        frame = json.load(fh)
    with open(a.labels, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    print(report(score(rows, frame)))
    return 0


def main(argv: Sequence[str] = ()) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump", help="every distinct location string of one job, label columns empty")
    d.add_argument("--project", required=True, help="a name / address match, or the id")
    d.add_argument("--company", default="")
    d.add_argument("--out", default="locations.csv")
    d.add_argument("--frame", default="", help="where to write the frame (default <out>.frame.json)")
    d.add_argument("--no-dob", action="store_true", help="do not read DOB NOW Build permits from NYC Open Data")
    s = sub.add_parser("score", help="precision, coverage and abstain rate of a labeled dump")
    s.add_argument("labels")
    s.add_argument("--frame", default="", help="the frame file (default <labels>.frame.json)")
    a = ap.parse_args(list(argv) or None)
    if a.cmd == "dump":
        return asyncio.run(run_dump(a))
    return run_score(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
