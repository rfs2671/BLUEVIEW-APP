"""READ-ONLY. How well can photos of one place be told from photos of another?

Nothing compares photos automatically until this has been run on real, labeled
photos and a threshold has been chosen from what it prints.
(lib/photo_relations.GEOMETRY_MIN_INLIERS stays None until then.)

Step 1, build the candidate pairs:

    railway run --service Blueview2 --environment production \\
        python backend/scripts/photo_relation_benchmark.py candidates "588" --out pairs.csv

Step 2, the owner opens pairs.csv and fills `label` with same or different,
using the two links in each row:

    known_different   interior photos filed under two different single levels.
                      Pre-labeled different. Overwrite anything that is wrong.
    probable_same     the same crew row on the same day. Often the same spot,
                      not always, and EASY: nothing has been built in between.
    same_level_later  one level, days apart. THE CASE THAT MATTERS and the one
                      most likely to fail: construction moved on in between.

Step 3, measure (geometry costs nothing; vision only with both flags):

    railway run ... python backend/scripts/photo_relation_benchmark.py evaluate pairs.csv
    railway run ... python backend/scripts/photo_relation_benchmark.py evaluate pairs.csv --vision --max-calls 40

Prints precision, recall and a confusion table at each threshold. It never writes
to Mongo: the vision calls here are not metered, so the count it prints is the
spend to note down. Rows without a usable label are left out and counted.
"""

import argparse
import asyncio
import csv
import random
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_helpers import require_fields  # noqa: E402
from lib import photo_geometry, progress_report  # noqa: E402
from lib import photo_relations as R  # noqa: E402
from lib import project_report as base  # noqa: E402
from lib import work_state as W  # noqa: E402

KNOWN_DIFFERENT, PROBABLE_SAME, SAME_LEVEL_LATER = "known_different", "probable_same", "same_level_later"
FIELDS = ["pair_id", "candidate_class", "label", "key_a", "key_b", "short_a", "short_b", "log_a", "log_b", "date_a",
          "date_b", "level_a", "level_b", "where_a", "where_b", "sub_a", "sub_b", "shows_a", "shows_b", "link_a", "link_b"]
INLIER_THRESHOLDS = (4, 6, 8, 10, 15, 20, 30, 50, 80, 120)
CONFIDENCE_THRESHOLDS = (0.5, 0.7, 0.9)
INSIDE_VIEWS = ("interior", "basement")
MIN_QUALITY = 4.0
#: Below this per side, a precision or a recall says very little.
FEW_LABELS = 30
PER_GROUP = 3


def _inside(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get("photo_key") and r.get("view") in INSIDE_VIEWS
            and float(r.get("quality") or 0) >= MIN_QUALITY]


def _one_level(row: Dict[str, Any]) -> Optional[str]:
    levels = W.places_in(row.get("where"))["levels"]
    return levels[0] if len(levels) == 1 else None


def _pair(a: Dict[str, Any], b: Dict[str, Any], cls: str) -> Dict[str, Any]:
    first, second = sorted((a, b), key=lambda r: (str(r.get("date")), str(r.get("photo_key"))))
    return {"pair_id": "|".join(sorted((str(a["photo_key"]), str(b["photo_key"])))), "candidate_class": cls,
            "label": "different" if cls == KNOWN_DIFFERENT else "", "key_a": first["photo_key"], "key_b": second["photo_key"],
            "short_a": first.get("short"), "short_b": second.get("short"), "log_a": first.get("log_id"), "log_b": second.get("log_id"),
            "date_a": first.get("date"), "date_b": second.get("date"), "level_a": _one_level(first), "level_b": _one_level(second),
            "where_a": first.get("where"), "where_b": second.get("where"), "sub_a": first.get("sub"), "sub_b": second.get("sub"),
            "shows_a": first.get("description"), "shows_b": second.get("description"), "link_a": "", "link_b": ""}


def _keep(pairs: List[Dict[str, Any]], seen: set, limit: int, rng: random.Random) -> List[Dict[str, Any]]:
    rng.shuffle(pairs)
    out: List[Dict[str, Any]] = []
    for p in pairs:
        if len(out) >= limit:
            break
        if p["pair_id"] not in seen:
            seen.add(p["pair_id"])
            out.append(p)
    return out


def build_candidates(rows: Sequence[Dict[str, Any]], per_class: int = 150, seed: int = 1109) -> List[Dict[str, Any]]:
    """The pairs to label. Seeded: the same photos give the same pairs."""
    rng = random.Random(seed)
    inside = _inside(rows)
    by_level: Dict[str, List[Dict[str, Any]]] = {}
    by_crew: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for r in inside:
        level = _one_level(r)
        if level:
            by_level.setdefault(level, []).append(r)
        by_crew.setdefault((r.get("log_id"), r.get("date"), r.get("sub"), r.get("where"), r.get("work")), []).append(r)
    seen: set = set()
    levels = sorted(by_level)
    different: List[Dict[str, Any]] = []
    for i, la in enumerate(levels):
        for lb in levels[i + 1:]:
            for _ in range(min(per_class, len(by_level[la]) * len(by_level[lb]))):
                a, b = rng.choice(by_level[la]), rng.choice(by_level[lb])
                if a.get("view") == b.get("view"):
                    different.append(_pair(a, b, KNOWN_DIFFERENT))
    same: List[Dict[str, Any]] = []
    for group in by_crew.values():
        for i, a in enumerate(group[:PER_GROUP]):
            for b in group[i + 1:PER_GROUP + 1]:
                if a["photo_key"] != b["photo_key"]:
                    same.append(_pair(a, b, PROBABLE_SAME))
    later: List[Dict[str, Any]] = []
    for group in by_level.values():
        for _ in range(per_class):
            a, b = rng.choice(group), rng.choice(group)
            da, db = base._d(a.get("date")), base._d(b.get("date"))
            if a is not b and a.get("view") == b.get("view") and da and db and abs((db - da).days) >= R.MIN_GAP_DAYS:
                later.append(_pair(a, b, SAME_LEVEL_LATER))
    return _keep(different, seen, per_class, rng) + _keep(same, seen, per_class, rng) + _keep(later, seen, per_class, rng)


def photo_address(logbook: Dict[str, Any], key: str) -> Optional[Tuple[int, int]]:
    """(activity index, photo index) of a photo key in its log, or None."""
    data = logbook.get("data") if isinstance(logbook.get("data"), dict) else {}
    for slot, a in enumerate(data.get("activities") or []):
        if not isinstance(a, dict):
            continue
        for n, p in enumerate(a.get("photos") or []):
            if isinstance(p, dict) and progress_report.photo_key(p, f"{logbook.get('_id') or logbook.get('date')}:{slot}", n) == key:
                return slot, n
    return None


def write_pairs(pairs: Sequence[Dict[str, Any]], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(pairs)


def read_labels(path: str) -> Tuple[List[Dict[str, Any]], int]:
    """(rows labeled same or different, how many were left out)."""
    keep: List[Dict[str, Any]] = []
    left_out = 0
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            label = str(row.get("label") or "").strip().lower()
            if label in ("same", "different") and row.get("key_a") and row.get("key_b"):
                keep.append({**row, "label": label})
            else:
                left_out += 1
    return keep, left_out


def _is_same(row: Dict[str, Any]) -> bool:
    return row["label"] == "same"


def confusion(rows: Sequence[Dict[str, Any]], said_same: Callable[[Dict[str, Any]], bool]) -> Dict[str, Any]:
    """{tp, fp, fn, tn, precision, recall}; a rate is None when it has no denominator."""
    tp = fp = fn = tn = 0
    for r in rows:
        said, truth = said_same(r), _is_same(r)
        tp += said and truth
        fp += said and not truth
        fn += (not said) and truth
        tn += (not said) and not truth
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None}


def _line(name: Any, c: Dict[str, Any]) -> str:
    fmt = lambda v: "-" if v is None else f"{v:.3f}"  # noqa: E731
    return f"  {str(name):>8}  {c['tp']:>4} {c['fp']:>4} {c['fn']:>4} {c['tn']:>4}  {fmt(c['precision']):>9} {fmt(c['recall']):>7}"


def table(title: str, rows: Sequence[Dict[str, Any]], at: Sequence[Any], said: Callable[[Dict[str, Any], Any], bool]) -> List[str]:
    out = [title, f"  {'at':>8}  {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4}  {'precision':>9} {'recall':>7}"]
    out += [_line(t, confusion(rows, lambda r: said(r, t))) for t in at]
    return out


def by_class(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """Median inliers per candidate class: same-day pairs being easy says
    nothing about a pair weeks of construction apart."""
    out = ["By candidate class (median homography inliers, labeled same / different):"]
    classes = sorted({str(r.get("candidate_class")) for r in rows})
    for cls in classes:
        mine = [r for r in rows if str(r.get("candidate_class")) == cls]
        same = [int(r["inliers"]) for r in mine if _is_same(r)]
        other = [int(r["inliers"]) for r in mine if not _is_same(r)]
        med = lambda v: statistics.median(v) if v else "-"  # noqa: E731
        out.append(f"  {cls}: {len(same)} same (median {med(same)}), {len(other)} different (median {med(other)})")
    return out


def report(rows: Sequence[Dict[str, Any]], left_out: int, vision_calls: int) -> List[str]:
    same = sum(1 for r in rows if _is_same(r))
    other = len(rows) - same
    out = [f"Labeled pairs measured: {len(rows)} ({same} same, {other} different). Left out, no usable label: {left_out}."]
    if same < FEW_LABELS or other < FEW_LABELS:
        out.append(f"TOO FEW to set a threshold from: at least {FEW_LABELS} on each side, and they should span several jobs.")
    require_fields(rows, "geometry_ok", "inliers", "epipolar_inliers") if rows else None
    unmeasured = sum(1 for r in rows if not r["geometry_ok"])
    if unmeasured:
        out.append(f"{unmeasured} pair(s) could not be measured (counted as no match).")
    out += table("Geometry, homography inliers (TP: said same and is):", rows, INLIER_THRESHOLDS,
                 lambda r, t: int(r["inliers"]) >= t)
    out += table("Geometry, epipolar inliers:", rows, INLIER_THRESHOLDS, lambda r, t: int(r["epipolar_inliers"]) >= t)
    out += by_class(rows)
    asked = [r for r in rows if r.get("vision_same")]
    if asked:
        out += table(f"Vision on {len(asked)} pair(s) (said yes at confidence; 'unsure' counts as no):", asked,
                     CONFIDENCE_THRESHOLDS, lambda r, t: r["vision_same"] == "yes" and float(r["vision_confidence"]) >= t)
    out.append(f"Vision calls made: {vision_calls}.")
    return out


async def _project(job: str) -> Optional[Dict[str, Any]]:
    import server
    rows = await server.db.projects.find({"is_deleted": {"$ne": True}}, {"name": 1, "address": 1}).to_list(2000)
    require_fields(rows, "name")
    hits = [p for p in rows if job.lower() in f"{p.get('name')} {p.get('address')}".lower()]
    if len(hits) != 1:
        print(f"{len(hits)} jobs match {job!r}: {[p.get('name') for p in hits][:10]}")
        return None
    return hits[0]


async def run_candidates(job: str, out: str, per_class: int, seed: int) -> None:
    import server
    project = await _project(job)
    if not project:
        return
    rows = await server.db[server.PHOTO_INDEX].find({"project_id": str(project["_id"]), "kind": "photo"}).to_list(20000)
    require_fields(rows, "photo_key", "log_id", "view", "quality", "where", "date", "sub", "work", "description", "short")
    pairs = build_candidates(rows, per_class=per_class, seed=seed)
    wanted = {p[f"log_{s}"] for p in pairs for s in "ab"}
    logs = {}
    for log_id in wanted:
        lg = await server.db.logbooks.find_one({"_id": server.to_query_id(str(log_id))}, {"date": 1, "data.activities": 1})
        if lg:
            logs[str(log_id)] = lg
    for p in pairs:
        for s in "ab":
            addr = photo_address(logs.get(str(p[f"log_{s}"])) or {}, p[f"key_{s}"])
            if addr:
                p[f"link_{s}"] = server._report_photo_url(str(p[f"log_{s}"]), addr[0], addr[1], "")
    write_pairs(pairs, out)
    require_fields(pairs, "candidate_class") if pairs else None
    per = Counter(p["candidate_class"] for p in pairs)
    print(f"Job: {project.get('name')}. Index rows read: {len(rows)}. Pairs written to {out}: {dict(per)}.")
    print("Fill `label` with same or different, then run: evaluate", out)


async def measure(pairs: Sequence[Dict[str, Any]], *, vision: bool, max_calls: int) -> Tuple[List[Dict[str, Any]], int]:
    """Each labeled pair measured. Reads only; `vision` costs up to `max_calls`."""
    import server
    keys = sorted({p[f"key_{s}"] for p in pairs for s in "ab"})
    rows = await server.db[server.PHOTO_INDEX].find({"kind": "photo", "photo_key": {"$in": keys}},
                                                    {"photo_key": 1, "log_id": 1, "project_id": 1}).to_list(len(keys) or 1)
    by_key = {r["photo_key"]: r for r in rows}
    out, calls = [], 0
    for p in pairs:
        a, b = by_key.get(p["key_a"]), by_key.get(p["key_b"])
        raw_a = await server._photo_log_bytes(a) if a else None
        raw_b = await server._photo_log_bytes(b) if b else None
        g = await asyncio.to_thread(photo_geometry.match, raw_a, raw_b) if raw_a and raw_b else photo_geometry._empty("photo not found")
        row = {**p, "geometry_ok": g["ok"], "geometry_reason": g["reason"], "inliers": g["inliers"], "ratio": g["ratio"],
               "epipolar_inliers": g["epipolar_inliers"], "epipolar_ratio": g["epipolar_ratio"], "vision_same": "", "vision_confidence": ""}
        if vision and calls < max_calls and raw_a and raw_b:
            calls += 1
            v = await server._photo_compare_call(raw_a, raw_b, a.get("project_id"), meter=False)
            if v:
                row["vision_same"], row["vision_confidence"] = v["same_area"], v["confidence"]
        out.append(row)
    return out, calls


async def run_evaluate(path: str, *, vision: bool, max_calls: int, out_path: Optional[str]) -> None:
    pairs, left_out = read_labels(path)
    rows, calls = await measure(pairs, vision=vision, max_calls=max_calls)
    print("\n".join(report(rows, left_out, calls)))
    if out_path and rows:
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Per-pair results written to {out_path}.")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark same-place photo matching. Read-only.")
    sub = parser.add_subparsers(dest="command", required=True)
    cand = sub.add_parser("candidates")
    cand.add_argument("job")
    cand.add_argument("--out", default="photo_relation_pairs.csv")
    cand.add_argument("--per-class", type=int, default=150)
    cand.add_argument("--seed", type=int, default=1109)
    ev = sub.add_parser("evaluate")
    ev.add_argument("labels")
    ev.add_argument("--vision", action="store_true", help="also ask the paid vision model; requires --max-calls")
    ev.add_argument("--max-calls", type=int, default=0)
    ev.add_argument("--out")
    args = parser.parse_args(argv)
    if args.command == "evaluate" and args.vision and args.max_calls <= 0:
        parser.error("--vision requires --max-calls N (N > 0)")
    return args


def main(argv: Sequence[str]) -> None:
    args = parse_args(argv)
    if args.command == "candidates":
        asyncio.run(run_candidates(args.job, args.out, args.per_class, args.seed))
    else:
        asyncio.run(run_evaluate(args.labels, vision=args.vision, max_calls=args.max_calls, out_path=args.out))


if __name__ == "__main__":
    main(sys.argv[1:])
