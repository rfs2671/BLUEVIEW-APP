"""What do the schedules of finished jobs say work really took?

    python scripts\\schedule_history_report.py "D:\\Finished job schedules" --out "D:\\schedule-history"

Reads every schedule file in a folder (P6 .xer, MS Project .xml, Excel .xlsx,
.csv, PDF tables), takes each finished activity -- one with BOTH an actual
start and an actual finish -- as one example of how long that kind of work
took, and prints, per kind of work, the range across the jobs.

READ-ONLY, AND PRIVATE. The folder is only read. There is no database, no
network and no model here: lib/schedule_import.py reads the file,
lib/schedule_history.py does the arithmetic. The one thing written is a JSON
file in the --out folder, which must be OUTSIDE the repo (the operator's
schedules are not source code and are never committed).

HOW FILES BECOME JOBS. Each folder directly inside the one you name is one
job, named after the folder; several files in it are taken as updates of the
same schedule and each activity is counted once, from the newest file. A file
lying loose in the top folder is a job named by the project name the file
states, else by the file's name.

JOB FACTS (optional). To get days per 1,000 sq ft, put a file named
job_facts.json in the top folder (or pass --facts):

    {"12 Elm St": {"storeys": 6, "gross_sqft": 41000, "footprint_sqft": 6900,
                   "building_type": "residential"}}

Nothing is assumed for a job that is not in it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from lib import schedule_history as H  # noqa: E402
from lib import schedule_import as I  # noqa: E402

FACTS_NAME = "job_facts.json"
_UNSUPPORTED = "Unsupported file."


def _inside_a_repo(path: Path) -> Optional[Path]:
    """The repository `path` is inside (this one or any other), else None."""
    path = path.resolve()
    this_repo = HERE.parent.parent
    if path == this_repo or this_repo in path.parents:
        return this_repo
    for p in (path, *path.parents):
        if (p / ".git").exists():
            return p
    return None


def _load_facts(path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"The job facts file {path} could not be read as JSON: {type(e).__name__}: {e}")
    if not isinstance(raw, dict):
        raise SystemExit(f"The job facts file {path} must be a JSON object of job name -> facts.")
    return {str(k).strip().lower(): v for k, v in raw.items() if isinstance(v, dict)}


def run(folder: Any, out_dir: Any, *, facts: Any = None, min_samples: int = H.MIN_SAMPLES,
        min_jobs: int = H.MIN_JOBS) -> Dict[str, Any]:
    """Read `folder`, write one JSON file into `out_dir`, return what was written."""
    folder, out_dir = Path(folder), Path(out_dir)
    if not folder.is_dir():
        raise SystemExit(f"Not a folder: {folder}")
    repo = _inside_a_repo(out_dir)
    if repo is not None:
        raise SystemExit(f"The output folder must be outside the repo ({repo}): schedules of finished jobs "
                         "are private and are never committed. Name a folder somewhere else.")
    facts_path = Path(facts) if facts else folder / FACTS_NAME
    all_facts = _load_facts(facts_path)

    files_read: List[Dict[str, Any]] = []
    refused: List[Dict[str, Any]] = []
    by_job: Dict[str, List[Dict[str, Any]]] = {}
    job_names: Dict[str, str] = {}
    seen_sha: Dict[str, str] = {}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder)
        shown = rel.as_posix()
        if path.resolve() == facts_path.resolve() or path.name.startswith(("~$", ".")):
            continue
        try:
            size = path.stat().st_size
            if size > I.MAX_BYTES:
                raise I.ScheduleImportError(f"The file is larger than {I.MAX_BYTES // (1024 * 1024)} MB.")
            data = path.read_bytes()
        except I.ScheduleImportError as e:
            refused.append({"file": shown, "reason": str(e)})
            continue
        except OSError as e:
            refused.append({"file": shown, "reason": f"could not be opened ({type(e).__name__}: {e})"})
            continue
        sha = hashlib.sha256(data).hexdigest()
        if sha in seen_sha:
            refused.append({"file": shown, "reason": f"the same file as {seen_sha[sha]}"})
            continue
        try:
            doc = I.parse_schedule(path.name, data)
        except I.ScheduleImportError as e:
            refused.append({"file": shown, "reason": str(e)})
            continue
        seen_sha[sha] = shown
        doc["source_name"] = shown  # which file in the folder, not just its bare name
        job_name = rel.parts[0] if len(rel.parts) > 1 else (doc.get("project_name") or path.stem)
        key = job_name.strip().lower()
        job_names.setdefault(key, job_name.strip())
        res = H.samples_of(doc, dict(all_facts.get(key) or {}, name=job_names[key]))
        by_job.setdefault(key, []).append(res)
        files_read.append({
            "file": shown, "job": job_names[key], "format": doc["format"], "status_date": doc.get("data_date"),
            "activities": res["counts"]["activities"], "finished": res["counts"]["finished"],
            "import_warnings": list(doc.get("warnings") or []),
        })  # fmt: skip

    jobs: List[Dict[str, Any]] = []
    samples: List[Dict[str, Any]] = []
    totals: Dict[str, Any] = {"jobs": 0, "jobs_finished": 0, "activities": 0, "finished": 0, "milestones": 0,
                              "summary_rows": 0, "by_status": dict.fromkeys(H.STATUSES, 0),
                              "no_sample": Counter(), "floors_unclear": 0}  # fmt: skip
    for key in sorted(by_job, key=lambda k: job_names[k].lower()):
        merged = H.merge_updates(by_job[key])
        c = merged["counts"]
        given = {k: v for k, v in merged["facts"].items() if k != "name" and v is not None}
        jobs.append({
            "name": merged["job"], "files": merged["files"], "status_date": merged["data_date"],
            "activities": c["activities"], "finished": c["finished"], "job_finished": merged["job_finished"],
            "milestones": c["milestones"], "by_status": c["by_status"], "no_sample": c["no_sample"],
            "floors_named": sorted({f for s in merged["samples"] for f in s["floors"]}),
            "facts": given, "notes": merged["notes"],
        })  # fmt: skip
        samples.extend(merged["samples"])
        totals["jobs"] += 1
        totals["jobs_finished"] += 1 if merged["job_finished"] else 0
        for k in ("activities", "finished", "milestones", "summary_rows", "floors_unclear"):
            totals[k] += c[k]
        for st in H.STATUSES:
            totals["by_status"][st] += c["by_status"][st]
        totals["no_sample"].update(c["no_sample"])
    totals["no_sample"] = dict(totals["no_sample"])
    unknown_facts = sorted(k for k in all_facts if k not in by_job)

    report: Dict[str, Any] = {
        "made_at": datetime.now().isoformat(timespec="seconds"),
        "folder": str(folder),
        "working_days": "Monday to Friday, both ends counted; holidays are not taken out",
        "files_read": files_read,
        "files_refused": refused,
        "jobs": jobs,
        "totals": totals,
        "same_job_twice": H.overlapping_jobs(samples),
        "job_facts_not_matched": unknown_facts,
        "unclassified_names": H.common_names(samples, H.UNCLASSIFIED, 30),
        "several_kinds_names": H.common_names(samples, H.SEVERAL, 10),
        "not_building_names": H.common_names(samples, H.NOT_BUILDING, 10),
        "floors_unclear_names": [n for n, _k in Counter(
            " ".join(s["name"].lower().split()) for s in samples if s["floors_unclear"]).most_common(10)],
        "summary": H.summarise(samples, min_samples=min_samples, min_jobs=min_jobs),
        "samples": samples,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"schedule_history_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    n = 1
    while target.exists():  # never write over an earlier report
        n += 1
        target = out_dir / f"{target.stem.split('__')[0]}__{n}.json"
    report["written_to"] = str(target)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False)
    return report


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------


def _range(m: Dict[str, Any]) -> str:
    if not m["enough"]:
        return f"{m['note']} ({m['n']} from {m['jobs']} job{'s' if m['jobs'] != 1 else ''})"
    return f"{m['p10']:g} - {m['median']:g} - {m['p90']:g}  ({m['n']} from {m['jobs']} jobs)"


def _facts_words(f: Dict[str, Any]) -> str:
    parts = []
    if f.get("storeys"):
        parts.append(f"{f['storeys']} storeys")
    if f.get("gross_sqft"):
        parts.append(f"{f['gross_sqft']:,.0f} sq ft gross")
    if f.get("footprint_sqft"):
        parts.append(f"{f['footprint_sqft']:,.0f} sq ft footprint")
    if f.get("building_type"):
        parts.append(str(f["building_type"]))
    return ", ".join(parts) or "no job facts given"


def render(report: Dict[str, Any]) -> str:
    """The report in plain words (what main() prints)."""
    t, summ = report["totals"], report["summary"]
    L: List[str] = []
    add = L.append
    add("SCHEDULE HISTORY: what the schedules of finished jobs say work really took")
    add(f"Folder read: {report['folder']}")
    add(f"Files read: {len(report['files_read'])}    Files not used: {len(report['files_refused'])}"
        f"    Jobs: {t['jobs']} ({t['jobs_finished']} with every activity finished)")
    add("")
    add("JOBS")
    if not report["jobs"]:
        add("  No schedule file in this folder could be read.")
    for j in report["jobs"]:
        state = "every activity finished" if j["job_finished"] else f"{j['finished']} of {j['activities']} activities finished"
        add(f"  {j['name']}: {state}; {_facts_words(j['facts'])}")
        add(f"      files: {', '.join(j['files'])}")
        for note in j["notes"]:
            add(f"      note: {note}")
    for pair in report["same_job_twice"]:
        add(f"  CHECK: \"{pair['jobs'][0]}\" and \"{pair['jobs'][1]}\" share {pair['shared']} finished activities with "
            "the same dates. They look like one job read twice; put its files in one folder.")
    if report["job_facts_not_matched"]:
        add(f"  Job facts given for a job that is not here: {', '.join(report['job_facts_not_matched'])}")
    add("")
    add("FILES NOT USED, AND WHY")
    other = [r for r in report["files_refused"] if r["reason"].startswith(_UNSUPPORTED)]
    named = [r for r in report["files_refused"] if not r["reason"].startswith(_UNSUPPORTED)]
    for r in named[:60]:
        add(f"  {r['file']}: {r['reason']}")
    if len(named) > 60:
        add(f"  ... and {len(named) - 60} more (all are in the JSON file)")
    if other:
        exts = Counter(os.path.splitext(r["file"])[1].lower() or "(no extension)" for r in other)
        add(f"  Other files that are not schedule files: {len(other)} ("
            + ", ".join(f"{e} x{n}" for e, n in exts.most_common(12)) + ")")
    if not report["files_refused"]:
        add("  none")
    add("")
    add("ACTIVITIES")
    add(f"  Activities in the schedules (headings left out; milestones left out: {t['milestones']}): {t['activities']}")
    add(f"  Finished, with both an actual start and an actual finish: {t['finished']}   <- the examples")
    ns = t["no_sample"]
    add(f"  Not used: {ns.get('no_actual_dates', 0)} with no actual dates, {ns.get('no_actual_finish', 0)} started "
        f"but not finished, {ns.get('no_actual_start', 0)} with a finish and no start, "
        f"{ns.get('dates_out_of_order', 0)} finished before they started, "
        f"{ns.get('finish_after_status_date', 0)} finished after the file's own status date")
    add(f"  Of the {t['finished']} examples:")
    add(f"      kind of work recognised:                 {t['by_status'][H.CLASSIFIED]}")
    add(f"      not recognised (kept, in no range):      {t['by_status'][H.UNCLASSIFIED]}")
    add(f"      names more than one kind of work:        {t['by_status'][H.SEVERAL]}")
    add(f"      paperwork, buying, deliveries, tests:    {t['by_status'][H.NOT_BUILDING]}")
    add(f"  Examples whose floor wording was not understood (no per-floor figure): {t['floors_unclear']}")
    for title, key in (("THE 30 MOST COMMON NAMES NOT RECOGNISED (floor left out)", "unclassified_names"),
                       ("MOST COMMON NAMES WITH MORE THAN ONE KIND OF WORK", "several_kinds_names"),
                       ("MOST COMMON NAMES TAKEN AS PAPERWORK, BUYING, DELIVERIES OR TESTS", "not_building_names")):
        add("")
        add(title)
        for i, row in enumerate(report[key], 1):
            add(f"  {i:>3}. {row['name']}  (x{row['count']})")
        if not report[key]:
            add("  none")
    if report["floors_unclear_names"]:
        add("")
        add("FLOOR WORDING NOT UNDERSTOOD (examples)")
        for n in report["floors_unclear_names"]:
            add(f"  {n}")
    add("")
    add("SUMMARY BY KIND OF WORK")
    add(f"  A range is printed only with at least {summ['min_samples']} examples from at least {summ['min_jobs']} jobs.")
    add("  A range reads  low - middle - high : 1 time in 10 it took less than low, half the time less than")
    add("  middle, and 9 times in 10 no more than high. Working days are Monday to Friday; holidays are not taken out.")
    blocks = (
        ("days_per_floor", "Working days per floor (one activity, divided by the floors it names)"),
        ("floor_span_days", "Working days for one whole floor (first start to last finish of that kind on the floor)"),
        ("days_per_1000_sqft", "Working days per 1,000 sq ft (only where the job's area was given)"),
        ("days_no_floor", "Working days for one activity that names no floor (the whole activity)"),
        ("actual_over_planned", "Actual days / planned days (1 = as planned, 1.5 = half as long again)"),
    )
    width = max(len(k["label"]) for k in summ["kinds"])
    for key, title in blocks:
        rows = [k for k in summ["kinds"] if k["measures"][key]["n"]]
        add("")
        add(f"  {title}")
        for k in rows:
            add(f"    {k['label']:<{width}}  {_range(k['measures'][key])}")
        if not rows:
            add("    no examples")
    add("")
    add("WHAT WAS COUNTED UNDER EACH KIND OF WORK (its most common names, to check the sorting)")
    for k in summ["kinds"]:
        if k["samples"]:
            add(f"    {k['label']:<{width}}  {k['samples']:>4}  {'; '.join(k['examples'])}")
    if not summ["classified"]:
        add("    nothing")
    ready = [k["label"] for k in summ["kinds"] if k["ready"]]
    none = [k["label"] for k in summ["kinds"] if not k["samples"]]
    few = [f"{k['label']} ({k['samples']} from {k['jobs']} job{'s' if k['jobs'] != 1 else ''})"
           for k in summ["kinds"] if k["samples"] and not k["ready"]]
    add("")
    add(f"ENOUGH TO FORECAST FROM ({len(ready)}): " + (", ".join(ready) or "none"))
    add(f"TOO FEW EXAMPLES ({len(few)}): " + (", ".join(few) or "none"))
    add(f"NO EXAMPLE AT ALL ({len(none)}): " + (", ".join(none) or "none"))
    pdf = sum(k["from_pdf"] for k in summ["kinds"])
    if pdf:
        add(f"  {pdf} of the recognised examples were read from PDF tables, which a person has not checked.")
    add("")
    add(f"Written to: {report['written_to']}")
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Duration examples from the schedules of finished jobs (read-only).")
    ap.add_argument("folder", help="the folder holding the schedule files (one sub-folder per job)")
    ap.add_argument("--out", required=True, help="a folder OUTSIDE the repo for the one JSON file this writes")
    ap.add_argument("--facts", help=f"job facts JSON (default: {FACTS_NAME} in the folder)")
    ap.add_argument("--min-samples", type=int, default=H.MIN_SAMPLES,
                    help=f"fewest examples a range is printed from (default {H.MIN_SAMPLES})")
    ap.add_argument("--min-jobs", type=int, default=H.MIN_JOBS,
                    help=f"fewest jobs those examples must come from (default {H.MIN_JOBS})")
    a = ap.parse_args(argv)
    report = run(a.folder, a.out, facts=a.facts, min_samples=a.min_samples, min_jobs=a.min_jobs)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
