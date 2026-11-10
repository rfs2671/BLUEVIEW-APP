"""READ-ONLY. How well can photos of one place be told from photos of another?

Nothing compares photos automatically, and no photo lends its place, until this
has been run on real photos labeled BY A PERSON and the thresholds have been set
from what it prints (lib/photo_relations.GEOMETRY_MIN_INLIERS and
VISION_MIN_CONFIDENCE, lib/photo_place.LEND_MIN_INLIERS all stay None until then).

Step 1, build candidate pairs. `label` is EMPTY on every row; `candidate_kind` is
only why the pair was picked, never an answer:

    railway run --service Blueview2 --environment production \\
        python backend/scripts/photo_relation_benchmark.py candidates "588" --out pairs.csv

    different_level           interior photos filed under two different single levels
    same_crew_day             one crew row, one day: often the same spot, and easy
    same_level_across_stages  one level, days apart, spread over the construction
                              stages of each photo's row (framing, rough-in, board,
                              finish): THE CASE THAT MATTERS
    same_line_other_floor     HARD NEGATIVE: one apartment line on two floors (3B, 4B)
    similar_room_same_floor   HARD NEGATIVE: one level, the same kind of room, in two
                              different units or for two different crews

Step 2, a person fills `label` with same or different (or unsure). Nothing else
is scored, and a row without a label is never scored.

Step 3, measure. Geometry costs nothing; vision only with both flags:

    railway run ... python backend/scripts/photo_relation_benchmark.py evaluate pairs.csv --fp-ceiling 0.02
    railway run ... python backend/scripts/photo_relation_benchmark.py evaluate pairs.csv --vision --max-calls 40 --fp-ceiling 0.02

A SIGNAL THAT DOES NOT MATCH SAYS "UNCONFIRMED", NEVER "DIFFERENT": construction
changes how a place looks. So the two errors are reported apart: a same-place
FALSE POSITIVE (said same, a person says different) is the one that would put a
photo in the wrong place; a MISSED same-place match only leaves a photo without
extra support. Each is given as a count and a rate, per signal (geometry,
vision, combined) and per construction-stage gap. The verdict "would enable"
needs a false-positive ceiling the owner sets (--fp-ceiling); without one, no
verdict is printed.

It never writes to Mongo. Its vision calls are not metered (a meter is a write),
so the count it prints is the spend to note down.
"""

import argparse
import asyncio
import csv
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_helpers import FieldNotInSample, counted, require_fields  # noqa: E402
from lib import photo_geometry, progress_report  # noqa: E402
from lib import photo_place  # noqa: E402
from lib import photo_relations as R  # noqa: E402
from lib import project_report as base  # noqa: E402
from lib import work_state as W  # noqa: E402

DIFFERENT_LEVEL, SAME_CREW_DAY, ACROSS_STAGES = "different_level", "same_crew_day", "same_level_across_stages"
SAME_LINE_OTHER_FLOOR, SIMILAR_ROOM_SAME_FLOOR = "same_line_other_floor", "similar_room_same_floor"
KINDS = (DIFFERENT_LEVEL, SAME_CREW_DAY, ACROSS_STAGES, SAME_LINE_OTHER_FLOOR, SIMILAR_ROOM_SAME_FLOOR)
FIELDS = ["pair_id", "candidate_kind", "label", "stage_a", "stage_b", "stage_gap", "key_a", "key_b", "short_a", "short_b",
          "log_a", "log_b", "date_a", "date_b", "level_a", "level_b", "space_a", "space_b", "room_a", "room_b",
          "where_a", "where_b", "sub_a", "sub_b", "shows_a", "shows_b", "link_a", "link_b"]
LABELS = ("same", "different")
NOT_SCORED = ("", "unsure")
STAGES = ("framing", "rough_in", "board", "finish")
NODE_STAGE = {"framing": 0, "rough_dwv": 1, "rough_water": 1, "rough_duct": 1, "rough_sprinkler": 1, "rough_gas": 1,
              "rough_electric": 1, "rough_lowvolt": 1, "insulation": 1, "drywall": 2, "ceiling_drop": 2,
              "prime": 3, "mep_trim": 3, "finishes": 3}
INLIER_THRESHOLDS = (4, 6, 8, 10, 15, 20, 30, 50, 80, 120)
CONFIDENCE_THRESHOLDS = (0.5, 0.7, 0.9)
INSIDE_VIEWS = ("interior", "basement")
MIN_QUALITY = 4.0
#: Below this per side, a rate says very little and no verdict is given.
FEW_LABELS = 30
PER_GROUP = 3
_UNIT = re.compile(r"^(\d{1,2})([A-Z])$")


# ── WHAT EACH PHOTO IS ─────────────────────────────────────────────────────

def _inside(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get("photo_key") and r.get("view") in INSIDE_VIEWS
            and float(r.get("quality") or 0) >= MIN_QUALITY]


def _one_level(row: Dict[str, Any]) -> Optional[str]:
    levels = W.places_in(row.get("where"))["levels"]
    return levels[0] if len(levels) == 1 else None


def stage_of(row: Dict[str, Any]) -> Optional[int]:
    """The construction stage the photo's crew row names, or None when it names
    none or several."""
    stages = set()
    for phrase in progress_report.work_phrases(row.get("work")):
        stages |= {NODE_STAGE[n] for n in W.classify(phrase, row.get("sub"))[0] if n in NODE_STAGE}
    return stages.pop() if len(stages) == 1 else None


def unit_of(row: Dict[str, Any]) -> Optional[str]:
    """One apartment the row names, or that is legible in the photo."""
    units = {photo_place.tag_key(t) for t in [W.places_in(row.get("where"))["space"] or ""] + list(row.get("visible_text") or [])}
    units = {u for u in units if _UNIT.match(u)}
    return units.pop() if len(units) == 1 else None


def _room(row: Dict[str, Any]) -> Optional[str]:
    room = str(row.get("room_type") or "")
    return room if room and room != "unknown" else None


# ── THE CANDIDATE PAIRS ────────────────────────────────────────────────────

def _pair(a: Dict[str, Any], b: Dict[str, Any], kind: str) -> Dict[str, Any]:
    first, second = sorted((a, b), key=lambda r: (str(r.get("date")), str(r.get("photo_key"))))
    sa, sb = stage_of(first), stage_of(second)
    out = {"pair_id": "|".join(sorted((str(a["photo_key"]), str(b["photo_key"])))), "candidate_kind": kind, "label": "",
           "stage_a": STAGES[sa] if sa is not None else "", "stage_b": STAGES[sb] if sb is not None else "",
           "stage_gap": abs(sb - sa) if sa is not None and sb is not None else "unknown", "link_a": "", "link_b": ""}
    for s, r in (("a", first), ("b", second)):
        out.update({f"key_{s}": r["photo_key"], f"short_{s}": r.get("short"), f"log_{s}": r.get("log_id"),
                    f"date_{s}": r.get("date"), f"level_{s}": _one_level(r), f"space_{s}": unit_of(r),
                    f"room_{s}": _room(r), f"where_{s}": r.get("where"), f"sub_{s}": r.get("sub"),
                    f"shows_{s}": r.get("description")})
    return out


def _take(pairs: List[Dict[str, Any]], seen: set, limit: int, rng: random.Random, *, spread_by: str = "") -> List[Dict[str, Any]]:
    """Up to `limit` new pairs. `spread_by`: a field to deal the pairs out by,
    round-robin over its values, so no one value fills the quota."""
    rng.shuffle(pairs)
    buckets: Dict[Any, List[Dict[str, Any]]] = {}
    for p in pairs:
        buckets.setdefault(p.get(spread_by) if spread_by else "", []).append(p)
    order = sorted(buckets, key=str)
    out: List[Dict[str, Any]] = []
    while len(out) < limit and any(buckets[k] for k in order):
        for k in order:
            while buckets[k]:
                p = buckets[k].pop()
                if p["pair_id"] not in seen:
                    seen.add(p["pair_id"])
                    out.append(p)
                    break
            if len(out) >= limit:
                break
    return out


def _gap_ok(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    da, db = base._d(a.get("date")), base._d(b.get("date"))
    return bool(da and db) and abs((db - da).days) >= R.MIN_GAP_DAYS


def build_candidates(rows: Sequence[Dict[str, Any]], per_kind: int = 150, seed: int = 1109) -> List[Dict[str, Any]]:
    """The pairs to label, every `label` empty. Seeded: the same photos give the
    same pairs."""
    rng = random.Random(seed)
    inside = _inside(rows)
    by_level: Dict[str, List[Dict[str, Any]]] = {}
    by_crew: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for r in inside:
        level = _one_level(r)
        if level:
            by_level.setdefault(level, []).append(r)
        by_crew.setdefault((r.get("log_id"), r.get("date"), r.get("sub"), r.get("where"), r.get("work")), []).append(r)
    levels = sorted(by_level)
    found: Dict[str, List[Dict[str, Any]]] = {k: [] for k in KINDS}
    tries = per_kind * 4
    for i, la in enumerate(levels):
        for lb in levels[i + 1:]:
            for _ in range(min(tries, len(by_level[la]) * len(by_level[lb]))):
                a, b = rng.choice(by_level[la]), rng.choice(by_level[lb])
                if a.get("view") == b.get("view"):
                    found[DIFFERENT_LEVEL].append(_pair(a, b, DIFFERENT_LEVEL))
                ua, ub = unit_of(a), unit_of(b)
                if ua and ub and _UNIT.match(ua).group(2) == _UNIT.match(ub).group(2):
                    found[SAME_LINE_OTHER_FLOOR].append(_pair(a, b, SAME_LINE_OTHER_FLOOR))
    for group in by_crew.values():
        for i, a in enumerate(group[:PER_GROUP]):
            for b in group[i + 1:PER_GROUP + 1]:
                if a["photo_key"] != b["photo_key"]:
                    found[SAME_CREW_DAY].append(_pair(a, b, SAME_CREW_DAY))
    for group in by_level.values():
        for _ in range(tries):
            a, b = rng.choice(group), rng.choice(group)
            if a is b or a.get("view") != b.get("view"):
                continue
            if _gap_ok(a, b):
                found[ACROSS_STAGES].append(_pair(a, b, ACROSS_STAGES))
            ua, ub = unit_of(a), unit_of(b)
            other = (ua and ub and ua != ub) or (a.get("log_id"), a.get("sub")) != (b.get("log_id"), b.get("sub"))
            if _room(a) and _room(a) == _room(b) and other:
                found[SIMILAR_ROOM_SAME_FLOOR].append(_pair(a, b, SIMILAR_ROOM_SAME_FLOOR))
    seen: set = set()
    out: List[Dict[str, Any]] = []
    # The hard kinds first: a 3B / 4B pair is also two levels, and it is worth
    # more as a hard negative than as one more easy one.
    for kind in (ACROSS_STAGES, SAME_LINE_OTHER_FLOOR, SIMILAR_ROOM_SAME_FLOOR, SAME_CREW_DAY, DIFFERENT_LEVEL):
        spread = "stage_gap" if kind == ACROSS_STAGES else ""
        out += _take(found[kind], seen, per_kind, rng, spread_by=spread)
    return out


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
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(pairs)


class BadLabel(ValueError):
    """A label that is neither a person's answer nor blank: a typo must not be
    silently left out of the count."""


def read_labels(path: str) -> Tuple[List[Dict[str, Any]], int]:
    """(rows a person labeled same or different, rows not scored: blank or
    unsure). Raises BadLabel on anything else."""
    keep: List[Dict[str, Any]] = []
    not_scored = 0
    with open(path, newline="", encoding="utf-8") as fh:
        for n, row in enumerate(csv.DictReader(fh), 2):
            label = str(row.get("label") or "").strip().lower()
            if label in NOT_SCORED:
                not_scored += 1
            elif label in LABELS and row.get("key_a") and row.get("key_b"):
                keep.append({**row, "label": label})
            else:
                raise BadLabel(f"line {n}: label {row.get('label')!r} is not same, different, unsure or blank")
    return keep, not_scored


# ── THE ARITHMETIC ─────────────────────────────────────────────────────────

def _is_same(row: Dict[str, Any]) -> bool:
    return row["label"] == "same"


def errors(rows: Sequence[Dict[str, Any]], says_same: Callable[[Dict[str, Any]], bool]) -> Dict[str, Any]:
    """The two errors, apart. A row the signal does not call same is
    UNCONFIRMED by it, not called different."""
    same = [r for r in rows if _is_same(r)]
    other = [r for r in rows if not _is_same(r)]
    fp = sum(1 for r in other if says_same(r))
    missed = sum(1 for r in same if not says_same(r))
    return {"false_positives": fp, "different": len(other), "fp_rate": round(fp / len(other), 4) if other else None,
            "missed": missed, "same": len(same), "miss_rate": round(missed / len(same), 4) if same else None}


def _vision_yes(r: Dict[str, Any], c: float) -> bool:
    return r.get("vision_same") == "yes" and float(r.get("vision_confidence") or 0) >= c


def signals(rows: Sequence[Dict[str, Any]]) -> List[Tuple[str, str, Sequence[Dict[str, Any]], Callable[[Dict[str, Any]], bool]]]:
    """(family, setting, rows it saw, says_same). Combined mirrors
    photo_relations.combine: either signal supports, unless the model said no."""
    out = []
    for t in INLIER_THRESHOLDS:
        out.append(("geometry", f"inliers>={t}", rows, lambda r, t=t: int(r["inliers"]) >= t))
    for t in INLIER_THRESHOLDS:
        out.append(("geometry_epipolar", f"epipolar>={t}", rows, lambda r, t=t: int(r["epipolar_inliers"]) >= t))
    asked = [r for r in rows if r.get("vision_same")]
    if asked:
        for c in CONFIDENCE_THRESHOLDS:
            out.append(("vision", f"yes, confidence>={c}", asked, lambda r, c=c: _vision_yes(r, c)))
        for t in INLIER_THRESHOLDS:
            for c in CONFIDENCE_THRESHOLDS:
                out.append(("combined", f"inliers>={t} or yes>={c}", asked,
                            lambda r, t=t, c=c: (int(r["inliers"]) >= t or _vision_yes(r, c)) and r.get("vision_same") != "no"))
    return out


def _rate(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:.3f}"


def verdict(results: Sequence[Tuple[str, str, Sequence[Dict[str, Any]], Dict[str, Any]]], ceiling: Optional[float]) -> List[str]:
    """Per signal family: the setting with the fewest misses whose
    false-positive rate is at or under the owner's ceiling, with enough labels
    on each side. Advice only: nothing reads it."""
    if ceiling is None:
        return ["Verdict: none. Pass --fp-ceiling (the highest same-place false-positive rate you accept) to get one."]
    out = [f"Verdict at a false-positive ceiling of {ceiling}:"]
    for family in dict.fromkeys(f for f, _s, _r, _e in results):
        mine = [(s, e) for f, s, _r, e in results if f == family]
        if not mine or mine[0][1]["same"] < FEW_LABELS or mine[0][1]["different"] < FEW_LABELS:
            out.append(f"  {family}: WOULD NOT ENABLE: fewer than {FEW_LABELS} labeled pairs on a side.")
            continue
        ok = [(s, e) for s, e in mine if e["fp_rate"] is not None and e["fp_rate"] <= ceiling]
        if not ok:
            out.append(f"  {family}: WOULD NOT ENABLE: no setting keeps false positives at or under the ceiling.")
            continue
        s, e = min(ok, key=lambda x: (x[1]["miss_rate"], x[0]))
        out.append(f"  {family}: WOULD ENABLE at {s}: false positives {e['false_positives']}/{e['different']} "
                   f"({_rate(e['fp_rate'])}), missed {e['missed']}/{e['same']} ({_rate(e['miss_rate'])}).")
    return out


def _gap(row: Dict[str, Any]) -> str:
    """0 is a gap (the same stage), not a missing one."""
    v = row.get("stage_gap")
    return "unknown" if v is None or v == "" else str(v)


def by_stage_gap(rows: Sequence[Dict[str, Any]], says_same: Callable[[Dict[str, Any]], bool]) -> List[str]:
    gaps = sorted({_gap(r) for r in rows})
    out = []
    for gap in gaps:
        e = errors([r for r in rows if _gap(r) == gap], says_same)
        out.append(f"      stage gap {gap}: false positives {e['false_positives']}/{e['different']} ({_rate(e['fp_rate'])}), "
                   f"missed {e['missed']}/{e['same']} ({_rate(e['miss_rate'])})")
    return out


def report(rows: Sequence[Dict[str, Any]], not_scored: int, vision_calls: int, *, ceiling: Optional[float] = None) -> List[str]:
    same = sum(1 for r in rows if _is_same(r))
    out = [f"Pairs a person labeled: {len(rows)} ({same} same, {len(rows) - same} different). "
           f"Not scored (blank or unsure): {not_scored}."]
    if same < FEW_LABELS or len(rows) - same < FEW_LABELS:
        out.append(f"TOO FEW to set a threshold from: at least {FEW_LABELS} on each side, and they should span several jobs.")
    if rows:
        require_fields(rows, "geometry_ok", "inliers", "epipolar_inliers", "stage_gap", "candidate_kind")
    unmeasured = sum(1 for r in rows if not r["geometry_ok"])
    if unmeasured:
        out.append(f"{unmeasured} pair(s) could not be measured: counted as unconfirmed by geometry, never as different.")
    out.append("A signal that does not say same says UNCONFIRMED. The two errors, apart:")
    results = []
    for family, setting, seen, says in signals(rows):
        e = errors(seen, says)
        results.append((family, setting, seen, e))
    out.append("  Same-place FALSE POSITIVES (said same, labeled different): would put a photo in the wrong place")
    out += [f"    {f:<18} {s:<28} {e['false_positives']:>4}/{e['different']:<4} rate {_rate(e['fp_rate'])}" for f, s, _r, e in results]
    out.append("  MISSED same-place matches (labeled same, not said same): a photo left without extra support")
    out += [f"    {f:<18} {s:<28} {e['missed']:>4}/{e['same']:<4} rate {_rate(e['miss_rate'])}" for f, s, _r, e in results]
    out.append("  By construction-stage gap (0 = same stage), per signal at its reference setting:")
    for family, setting, seen, says in signals(rows):
        if setting in ("inliers>=15", "epipolar>=15", "yes, confidence>=0.7", "inliers>=15 or yes>=0.7"):
            out.append(f"    {family} {setting}:")
            out += by_stage_gap(seen, says)
    kinds = Counter(str(r.get("candidate_kind")) for r in rows)
    out.append("  Labeled pairs by candidate kind: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
    out += verdict(results, ceiling)
    out.append(f"Vision calls made: {vision_calls}.")
    return out


# ── THE RUNS (read-only) ───────────────────────────────────────────────────

async def _project(job: str) -> Optional[Dict[str, Any]]:
    import server
    rows = await server.db.projects.find({"is_deleted": {"$ne": True}}, {"name": 1, "address": 1}).to_list(2000)
    require_fields(rows, "name")
    hits = [p for p in rows if job.lower() in f"{p.get('name')} {p.get('address')}".lower()]
    if len(hits) != 1:
        print(f"{len(hits)} jobs match {job!r}: {[p.get('name') for p in hits][:10]}")
        return None
    return hits[0]


async def run_candidates(job: str, out: str, per_kind: int, seed: int) -> None:
    import server
    project = await _project(job)
    if not project:
        return
    rows = await server.db[server.PHOTO_INDEX].find({"project_id": str(project["_id"]), "kind": "photo"}).to_list(20000)
    require_fields(rows, "photo_key", "log_id", "view", "quality", "where", "date", "sub", "work", "description", "short")
    try:
        # Every row searched, not a sample: v2 rows may all be recent ones.
        v2 = str(counted(rows, "prompt_v", lambda v: v == 2, limit=len(rows)))
    except FieldNotInSample:
        v2 = "none"            # prompt_v is written only by the v2 read: no row has had one
    pairs = build_candidates(rows, per_kind=per_kind, seed=seed)
    logs = {}
    for log_id in {p[f"log_{s}"] for p in pairs for s in "ab"}:
        lg = await server.db.logbooks.find_one({"_id": server.to_query_id(str(log_id))}, {"date": 1, "data.activities": 1})
        if lg:
            logs[str(log_id)] = lg
    for p in pairs:
        for s in "ab":
            addr = photo_address(logs.get(str(p[f"log_{s}"])) or {}, p[f"key_{s}"])
            if addr:
                p[f"link_{s}"] = server._report_photo_url(str(p[f"log_{s}"]), addr[0], addr[1], "")
    write_pairs(pairs, out)
    if pairs:
        require_fields(pairs, "candidate_kind")
    per = Counter(p["candidate_kind"] for p in pairs)
    print(f"Job: {project.get('name')}. Index rows read: {len(rows)} ({v2} read with the v2 prompt: room type and "
          f"legible text exist only on those). Pairs written to {out}: {dict(per)}.")
    print("Every `label` is empty. Fill it with same, different or unsure, then run: evaluate", out)


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


async def run_evaluate(path: str, *, vision: bool, max_calls: int, out_path: Optional[str], ceiling: Optional[float]) -> int:
    try:
        pairs, not_scored = read_labels(path)
    except BadLabel as e:
        print(f"Refused: {e}.")
        return 2
    if not pairs:
        print(f"Refused: no row has a label a person filled in (same or different). {not_scored} row(s) are blank or unsure, "
              "and an unlabeled row is never scored.")
        return 2
    rows, calls = await measure(pairs, vision=vision, max_calls=max_calls)
    print("\n".join(report(rows, not_scored, calls, ceiling=ceiling)))
    if out_path and rows:
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Per-pair results written to {out_path}.")
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark same-place photo matching. Read-only.")
    sub = parser.add_subparsers(dest="command", required=True)
    cand = sub.add_parser("candidates")
    cand.add_argument("job")
    cand.add_argument("--out", default="photo_relation_pairs.csv")
    cand.add_argument("--per-kind", type=int, default=150)
    cand.add_argument("--seed", type=int, default=1109)
    ev = sub.add_parser("evaluate")
    ev.add_argument("labels")
    ev.add_argument("--vision", action="store_true", help="also ask the paid vision model; requires --max-calls")
    ev.add_argument("--max-calls", type=int, default=0)
    ev.add_argument("--fp-ceiling", type=float, default=None,
                    help="the highest same-place false-positive rate you accept; required for a verdict")
    ev.add_argument("--out")
    args = parser.parse_args(argv)
    if args.command == "evaluate" and args.vision and args.max_calls <= 0:
        parser.error("--vision requires --max-calls N (N > 0)")
    if args.command == "evaluate" and args.fp_ceiling is not None and not 0 <= args.fp_ceiling < 1:
        parser.error("--fp-ceiling is a rate: at least 0 and below 1")
    return args


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    if args.command == "candidates":
        asyncio.run(run_candidates(args.job, args.out, args.per_kind, args.seed))
        return 0
    return asyncio.run(run_evaluate(args.labels, vision=args.vision, max_calls=args.max_calls,
                                    out_path=args.out, ceiling=args.fp_ceiling))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
