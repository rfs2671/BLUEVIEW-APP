"""READ-ONLY. How well can photos of one place be told from photos of another?

Nothing compares photos automatically, and no photo lends its place, until this
has been run on real photos labeled BY TWO PEOPLE and the thresholds have been
set from what it prints (lib/photo_relations.GEOMETRY_MIN_INLIERS and
VISION_MIN_CONFIDENCE, lib/photo_place.LEND_MIN_INLIERS all stay None until then).

THE OWNER'S RULING: 30 negative examples cannot validate a 2% false-positive
ceiling. Every rate is printed with its 95% intervals (exact Clopper-Pearson
and Wilson, lib/benchmark_stats), and "would enable" needs the one-sided upper
bound under the ceiling, enough independently labeled negatives for it, two
projects, three construction-stage gaps among the same-place pairs, and hard
negatives at least a third of the negatives. Otherwise it prints what is missing.

Step 1, plan. Stratified candidate pairs across EVERY project with indexed
photos, sized for the ceiling. Every label column is EMPTY; `candidate_kind` is
only why the pair was picked, never an answer:

    railway run --service Blueview2 --environment production \\
        python backend/scripts/photo_relation_benchmark.py plan --fp-ceiling 0.02 --out pairs.csv

    different_level           interior photos filed under two different single levels
    same_crew_day             one crew row, one day: often the same spot, and easy
    same_level_across_stages  one level, days apart, spread over the construction
                              stages of each photo's row (framing, rough-in, board,
                              finish): THE CASE THAT MATTERS
    same_line_other_floor     HARD NEGATIVE: one apartment line on two floors (3B, 4B)
    similar_room_same_floor   HARD NEGATIVE: one level, the same kind of room, in two
                              different units or for two different crews

Step 2, a contact sheet to label from: pairs side by side, ids only (no names,
no phone numbers, no log text), read from R2 and nothing else:

    railway run ... python backend/scripts/photo_relation_benchmark.py sheet pairs.csv --out sheet.html

Step 3, two people label INDEPENDENTLY, each in their own copy: one fills
`label_a`, the other `label_b`, with same, different or unsure, by sheet_id.
Merge the two columns into one file. Where they disagree, the pair is not scored
until a person writes the answer in `label_resolved` (`sheet --disputed` shows
only those). A pair with one label only is not scored either.

Step 4, measure. Geometry costs nothing; vision only with both flags:

    railway run ... python backend/scripts/photo_relation_benchmark.py evaluate pairs.csv --fp-ceiling 0.02
    railway run ... python backend/scripts/photo_relation_benchmark.py evaluate pairs.csv --vision --max-calls 40 --fp-ceiling 0.02

A SIGNAL THAT DOES NOT MATCH SAYS "UNCONFIRMED", NEVER "DIFFERENT": construction
changes how a place looks. So the two errors are reported apart: a same-place
FALSE POSITIVE (said same, the labels say different) is the one that would put
a photo in the wrong place; a MISSED same-place match only leaves a photo
without extra support. Each is given per signal (geometry, vision, combined)
and per construction-stage gap, project and negative kind (hard or easy).

It never writes to Mongo. Its vision calls are not metered (a meter is a write),
so the count it prints is the spend to note down.
"""

import argparse
import asyncio
import base64
import csv
import html
import io
import math
import random
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_helpers import FieldNotInSample, counted, require_fields  # noqa: E402
from lib import benchmark_stats as S  # noqa: E402
from lib import photo_geometry, progress_report  # noqa: E402
from lib import photo_place  # noqa: E402
from lib import photo_relations as R  # noqa: E402
from lib import project_report as base  # noqa: E402
from lib import work_state as W  # noqa: E402

DIFFERENT_LEVEL, SAME_CREW_DAY, ACROSS_STAGES = "different_level", "same_crew_day", "same_level_across_stages"
SAME_LINE_OTHER_FLOOR, SIMILAR_ROOM_SAME_FLOOR = S.HARD_KINDS
KINDS = (DIFFERENT_LEVEL, SAME_CREW_DAY, ACROSS_STAGES, SAME_LINE_OTHER_FLOOR, SIMILAR_ROOM_SAME_FLOOR)
FIELDS = ["pair_id", "sheet_id", "project_id", "candidate_kind", "label_a", "label_b", "label_resolved",
          "stage_a", "stage_b", "stage_gap", "key_a", "key_b", "short_a", "short_b",
          "log_a", "log_b", "date_a", "date_b", "level_a", "level_b", "space_a", "space_b", "room_a", "room_b",
          "where_a", "where_b", "sub_a", "sub_b", "shows_a", "shows_b", "link_a", "link_b"]
LABEL_COLUMNS = ("label_a", "label_b", "label_resolved")
BadLabel = S.BadLabel
STAGES = ("framing", "rough_in", "board", "finish")
NODE_STAGE = {"framing": 0, "rough_dwv": 1, "rough_water": 1, "rough_duct": 1, "rough_sprinkler": 1, "rough_gas": 1,
              "rough_electric": 1, "rough_lowvolt": 1, "insulation": 1, "drywall": 2, "ceiling_drop": 2,
              "prime": 3, "mep_trim": 3, "finishes": 3}
INLIER_THRESHOLDS = (4, 6, 8, 10, 15, 20, 30, 50, 80, 120)
CONFIDENCE_THRESHOLDS = (0.5, 0.7, 0.9)
REFERENCE_SETTINGS = ("inliers>=15", "epipolar>=15", "yes, confidence>=0.7", "inliers>=15 or yes>=0.7")
INSIDE_VIEWS = ("interior", "basement")
MIN_QUALITY = 4.0
PER_GROUP = 3
#: The plan's split. Hard negatives: half the negatives, over the two hard kinds.
#: Same-place candidates: three quarters across stages, a quarter one crew-day.
HARD_PLAN_SHARE = 0.5
ACROSS_SHARE = 0.75
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
    pid = "|".join(sorted((str(a["photo_key"]), str(b["photo_key"]))))
    out = {"pair_id": pid, "sheet_id": S.sheet_id(pid), "project_id": str(first.get("project_id") or ""),
           "candidate_kind": kind, "label_a": "", "label_b": "", "label_resolved": "",
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


def build_candidates(rows: Sequence[Dict[str, Any]], per_kind: int = 150, seed: Any = 1109) -> List[Dict[str, Any]]:
    """The pairs of ONE project to label, every label empty. Seeded: the same
    photos give the same pairs."""
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


# ── THE PLAN: ACROSS EVERY PROJECT, SIZED FOR THE CEILING ──────────────────

def kind_quotas(ceiling: float, expect_errors: int = 1, overdraw: float = 1.25, same_share: float = 0.5) -> Dict[str, int]:
    """How many candidates of each kind to draw. Negatives: the exact count the
    ceiling needs at `expect_errors` false positives, times `overdraw` (some
    candidates will be labeled same, unsure or disputed). Half of them hard."""
    negatives = math.ceil(S.required_negatives(ceiling, expect_errors) * overdraw)
    hard = math.ceil(negatives * HARD_PLAN_SHARE)
    same = math.ceil(negatives * same_share)
    across = math.ceil(same * ACROSS_SHARE)
    return {DIFFERENT_LEVEL: negatives - hard, SAME_LINE_OTHER_FLOOR: math.ceil(hard / 2),
            SIMILAR_ROOM_SAME_FLOOR: hard // 2, ACROSS_STAGES: across, SAME_CREW_DAY: same - across}


def plan_pairs(rows_by_project: Dict[str, Sequence[Dict[str, Any]]], quotas: Dict[str, int], seed: int = 1109) -> List[Dict[str, Any]]:
    """Each kind's quota spread evenly over the projects that have candidates
    of that kind (lib/benchmark_stats.allocate), and within a project over the
    construction-stage gaps. Seeded per project, so adding a project does not
    reshuffle the others' pools."""
    pools: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    biggest = max(quotas.values() or [0])
    for pid in sorted(rows_by_project):
        cands = build_candidates([{**r, "project_id": pid} for r in rows_by_project[pid]], per_kind=biggest, seed=f"{seed}:{pid}")
        pools[pid] = {k: [p for p in cands if p["candidate_kind"] == k] for k in KINDS}
    rng = random.Random(seed)
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for kind in KINDS:
        share = S.allocate({pid: len(pools[pid][kind]) for pid in pools}, quotas.get(kind, 0))
        for pid in sorted(share, key=str):
            out += _take(list(pools[pid][kind]), seen, share[pid], rng, spread_by="stage_gap")
    return out


def plan_report(pairs: Sequence[Dict[str, Any]], quotas: Dict[str, int], ceiling: float) -> List[str]:
    kinds = S.tally(pairs, lambda p: p["candidate_kind"])
    out = [f"Planned for a false-positive ceiling of {ceiling}: {sum(quotas.values())} pairs; drawn {len(pairs)}."]
    for kind in KINDS:
        got, want = kinds.get(kind, 0), quotas.get(kind, 0)
        out.append(f"  {kind:<26} drawn {got:>4} of {want:<4}" + ("" if got >= want else f"  SHORT by {want - got}"))
    out.append("  By project: " + ", ".join(f"{k} {n}" for k, n in sorted(S.tally(pairs, S.project).items())))
    out.append("  By construction-stage gap: " + ", ".join(f"{k} {n}" for k, n in sorted(S.tally(pairs, S.stage_gap).items())))
    out += [f"  PLAN CANNOT MEET: {m}" for m in S.plan_shortfalls(pairs, ceiling)]
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


def read_labels(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """(rows to score, each with its agreed or resolved `label`; a tally of the
    rest and the labelers' agreement). Raises BadLabel on a typo, or on a file
    without two labeler columns: one person's labels are not scored."""
    keep: List[Dict[str, Any]] = []
    statuses: List[str] = []
    both: List[Tuple[str, str]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        absent = [c for c in ("label_a", "label_b") if c not in (reader.fieldnames or [])]
        if absent:
            raise BadLabel(f"no {' or '.join(absent)} column: two people label each pair independently, "
                           "and one person's labels are never scored")
        for n, row in enumerate(reader, 2):
            status, label = S.resolve(row.get("label_a"), row.get("label_b"), row.get("label_resolved"), line=n)
            a, b = (str(row.get(c) or "").strip().lower() for c in ("label_a", "label_b"))
            both.append((a, b))
            statuses.append(status)
            if status == "scored":
                if not (row.get("key_a") and row.get("key_b")):
                    raise BadLabel(f"line {n}: a labeled pair without key_a and key_b")
                keep.append({**row, "label": label})
    tally = S.tally(statuses, lambda s: s)
    tally["kappa"] = S.cohen_kappa(both)
    return keep, tally


# ── THE ARITHMETIC ─────────────────────────────────────────────────────────

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


def verdict(results: Sequence[Tuple[str, str, Sequence[Dict[str, Any]], Dict[str, Any]]], ceiling: Optional[float]) -> List[str]:
    """Per signal family: of the settings whose one-sided upper bound is under
    the ceiling, the one with the fewest misses, and everything the sample still
    lacks. Advice only: nothing reads it."""
    if ceiling is None:
        return ["Verdict: none. Pass --fp-ceiling (the highest same-place false-positive rate you accept) to get one."]
    out = [f"Verdict at a false-positive ceiling of {ceiling} (one-sided {S.CONFIDENCE:.0%} upper bound):"]
    for family in dict.fromkeys(f for f, _s, _r, _e in results):
        mine = [(n, s, rows, e) for n, (f, s, rows, e) in enumerate(results) if f == family]

        def upper(m: Tuple[int, str, Any, Dict[str, Any]]) -> float:
            return 2.0 if m[3]["fp"]["upper"] is None else m[3]["fp"]["upper"]
        passing = [m for m in mine if upper(m) < ceiling]
        if passing:     # the fewest misses; on a tie the lower bound, then the earlier (looser) setting
            _n, s, rows, e = min(passing, key=lambda m: (m[3]["miss"]["k"], upper(m), m[0]))
        else:
            _n, s, rows, e = min(mine, key=lambda m: (upper(m), m[3]["miss"]["k"], m[0]))
        lacking = S.missing(rows, e["fp"], ceiling, miss=e["miss"])
        if lacking:
            out.append(f"  {family}: WOULD NOT ENABLE. Closest setting {s}: false positives {S.fmt(e['fp'])}. Missing:")
            out += [f"    - {m}" for m in lacking]
            continue
        out.append(f"  {family}: WOULD ENABLE at {s}: false positives {S.fmt(e['fp'])}; missed {S.fmt(e['miss'])}. "
                   f"Chosen among {len(mine)} settings on these same labels: confirm on a fresh sample before setting a constant.")
    return out


def _kappa_line(k: Dict[str, Any]) -> str:
    if not k["n"]:
        return "Labeler agreement: no pair was labeled by both people."
    kappa = "undefined (one answer only)" if k["kappa"] is None else f"{k['kappa']:.3f}"
    return (f"Labeler agreement over {k['n']} pair(s) both labeled: Cohen's kappa {kappa}, "
            f"observed {k['observed']:.3f}, chance {k['chance']:.3f}; {k['n'] - k['agreed']} disagreement(s).")


def report(rows: Sequence[Dict[str, Any]], tally: Dict[str, Any], vision_calls: int, *, ceiling: Optional[float] = None) -> List[str]:
    same = sum(1 for r in rows if S.is_same(r))
    out = [f"Pairs scored (two people agreed, or a person resolved): {len(rows)} ({same} same, {len(rows) - same} different).",
           f"Not scored: blank {tally.get('blank', 0)}, one label only {tally.get('one_label', 0)} (needs a second, "
           f"independent label), unsure {tally.get('unsure', 0)}, disputed {tally.get('disputed', 0)} "
           "(excluded until label_resolved is filled).",
           _kappa_line(tally.get("kappa") or S.cohen_kappa([]))]
    if rows:
        require_fields(rows, "geometry_ok", "inliers", "epipolar_inliers", "stage_gap", "candidate_kind", "project_id")
    unmeasured = sum(1 for r in rows if not r["geometry_ok"])
    if unmeasured:
        out.append(f"{unmeasured} pair(s) could not be measured: counted as unconfirmed by geometry, never as different.")
    out.append("A signal that does not say same says UNCONFIRMED. The two errors, apart, with 95% intervals:")
    sigs = signals(rows)
    results = [(f, s, seen, S.errors(seen, says)) for f, s, seen, says in sigs]
    out.append("  Same-place FALSE POSITIVES (said same, labeled different): would put a photo in the wrong place")
    out += [f"    {f:<18} {s:<28} {S.fmt(e['fp'])}" for f, s, _r, e in results]
    out.append("  MISSED same-place matches (labeled same, not said same): a photo left without extra support")
    out += [f"    {f:<18} {s:<28} {S.fmt(e['miss'])}" for f, s, _r, e in results]
    for name, key in S.STRATA:
        out.append(f"  By {name}, per signal at its reference setting:")
        for family, setting, seen, says in sigs:
            if setting in REFERENCE_SETTINGS:
                out.append(f"    {family} {setting}:")
                for stratum, e in S.by_stratum(seen, says, key):
                    out.append(f"      {name} {stratum}: false positives {S.fmt(e['fp'])}; missed {S.fmt(e['miss'])}")
    c = S.coverage(rows)
    projects = c["projects"]
    out.append(f"  Sample: {c['negatives']} negatives ({c['hard']} hard) from {len(projects)} project(s); "
               f"{c['same']} same-place pairs over stage gaps {', '.join(c['stage_gaps']) or 'none'}.")
    out.append("  Labeled pairs by candidate kind: " + ", ".join(f"{k} {n}" for k, n in sorted(S.tally(rows, S.kind).items())))
    if ceiling is not None:
        out.append(f"  Labeled negatives a ceiling of {ceiling} needs: " + ", ".join(
            f"{S.required_negatives(ceiling, k)} at {k} false positive(s)" for k in (0, 1, 2)))
    out += verdict(results, ceiling)
    out.append(f"Vision calls made: {vision_calls}.")
    return out


# ── THE CONTACT SHEET (R2 reads only) ──────────────────────────────────────

def thumbnail(raw: Optional[bytes], side: int = 360) -> Optional[str]:
    """A small JPEG data URI, upright, or None when the bytes are not an image."""
    if not raw:
        return None
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((side, side))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=70)
    except Exception:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def build_sheet(rows: Sequence[Dict[str, Any]], fetch: Callable[[str], Optional[bytes]], side: int = 360) -> str:
    """Pairs side by side. IDS ONLY: the pair's number and sheet_id, never the
    log text, a name, a company or a phone number. A photo with only an inline
    copy is not in R2 and is shown as missing rather than read from the log."""
    cells = []
    for n, row in enumerate(rows, 1):
        sid = row.get("sheet_id") or S.sheet_id(row.get("pair_id") or f"{row.get('key_a')}|{row.get('key_b')}")
        imgs = []
        for s in "ab":
            key = str(row.get(f"key_{s}") or "")
            uri = None if not key or key.startswith("inline:") else thumbnail(fetch(key), side)
            imgs.append(f'<img src="{uri}" alt="photo {s.upper()}">' if uri else '<div class="none">not in R2</div>')
        cells.append(f'<section><h2>#{n} <code>{html.escape(sid)}</code></h2><div class="two">{"".join(imgs)}</div></section>')
    return ("<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\">"
            "<title>Photo pair sheet</title><style>body{font:14px system-ui;margin:16px;background:#fff;color:#111}"
            "section{margin:0 0 24px}.two{display:flex;gap:8px;flex-wrap:wrap}img{max-width:100%;height:auto}"
            ".none{width:200px;height:150px;display:flex;align-items:center;justify-content:center;background:#eee}"
            "h2{font-size:15px;margin:0 0 6px}</style></head><body>"
            f"<p>{len(rows)} pair(s). Label each by sheet_id: same, different or unsure. Same means the same physical "
            "area, even at another construction stage.</p>" + "".join(cells) + "</body></html>")


def run_sheet(path: str, out: str, *, side: int, disputed: bool, fetch: Optional[Callable[[str], Optional[bytes]]] = None) -> int:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if disputed:
        rows = [r for n, r in enumerate(rows, 2)
                if S.resolve(r.get("label_a"), r.get("label_b"), r.get("label_resolved"), line=n)[0] == "disputed"]
    if fetch is None:
        import server

        def fetch(key: str) -> Optional[bytes]:
            return server._r2_fetch(key)[0]
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(build_sheet(rows, fetch, side))
    print(f"Contact sheet of {len(rows)} pair(s) written to {out}: ids only, photos read from R2.")
    return 0


# ── THE RUNS (read-only) ───────────────────────────────────────────────────

async def run_plan(out: str, *, ceiling: float, expect_errors: int, overdraw: float, same_share: float, seed: int) -> int:
    import server
    projects = await server.db.projects.find({"is_deleted": {"$ne": True}}, {"_id": 1}).to_list(5000)
    live = {str(p["_id"]) for p in projects}
    rows = await server.db[server.PHOTO_INDEX].find({"kind": "photo"}).to_list(500000)
    if not rows:
        print("No indexed photos: nothing to plan from.")
        return 2
    require_fields(rows, "photo_key", "project_id", "log_id", "view", "quality", "where", "date", "sub", "work",
                   "description", "short")
    try:
        # Every row searched, not a sample: v2 rows may all be recent ones.
        v2 = str(counted(rows, "prompt_v", lambda v: v == 2, limit=len(rows)))
    except FieldNotInSample:
        v2 = "none"            # prompt_v is written only by the v2 read: no row has had one
    by_project: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        if str(r.get("project_id")) in live:
            by_project.setdefault(str(r.get("project_id")), []).append(r)
    quotas = kind_quotas(ceiling, expect_errors, overdraw, same_share)
    pairs = plan_pairs(by_project, quotas, seed)
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
    print(f"Index rows read: {len(rows)} over {len(by_project)} live project(s) ({v2} read with the v2 prompt: room "
          f"type and legible text exist only on those). Seed {seed}. Pairs written to {out}.")
    print("\n".join(plan_report(pairs, quotas, ceiling)))
    print("Every label column is empty. Two people fill label_a and label_b independently; then run: evaluate", out)
    return 0


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
        project_id = p.get("project_id") or str((a or b or {}).get("project_id") or "")
        row = {**p, "project_id": project_id, "geometry_ok": g["ok"], "geometry_reason": g["reason"], "inliers": g["inliers"],
               "ratio": g["ratio"], "epipolar_inliers": g["epipolar_inliers"], "epipolar_ratio": g["epipolar_ratio"],
               "vision_same": "", "vision_confidence": ""}
        if vision and calls < max_calls and raw_a and raw_b:
            calls += 1
            v = await server._photo_compare_call(raw_a, raw_b, a.get("project_id"), meter=False)
            if v:
                row["vision_same"], row["vision_confidence"] = v["same_area"], v["confidence"]
        out.append(row)
    return out, calls


async def run_evaluate(path: str, *, vision: bool, max_calls: int, out_path: Optional[str], ceiling: Optional[float]) -> int:
    try:
        pairs, tally = read_labels(path)
    except BadLabel as e:
        print(f"Refused: {e}.")
        return 2
    if not pairs:
        print("Refused: no pair has two agreeing labels (or a resolved one) of same or different. "
              f"{_kappa_line(tally['kappa'])} An unscored pair is never measured.")
        return 2
    rows, calls = await measure(pairs, vision=vision, max_calls=max_calls)
    print("\n".join(report(rows, tally, calls, ceiling=ceiling)))
    if out_path and rows:
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Per-pair results written to {out_path}.")
    return 0


def _rate_arg(parser: argparse.ArgumentParser, v: Optional[float], name: str) -> None:
    if v is not None and not 0 < v < 1:
        parser.error(f"{name} is a rate: above 0 and below 1")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark same-place photo matching. Read-only.")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="stratified candidate pairs across every project, labels empty")
    plan.add_argument("--fp-ceiling", type=float, required=True)
    plan.add_argument("--expect-errors", type=int, default=1,
                      help="false positives to size for: the plan holds enough negatives for the ceiling at this many")
    plan.add_argument("--overdraw", type=float, default=1.25)
    plan.add_argument("--same-share", type=float, default=0.5, help="same-place candidates per negative")
    plan.add_argument("--seed", type=int, default=1109)
    plan.add_argument("--out", default="photo_relation_pairs.csv")
    sheet = sub.add_parser("sheet", help="a local HTML contact sheet of the pairs, ids only, R2 reads only")
    sheet.add_argument("pairs")
    sheet.add_argument("--out", default="photo_relation_sheet.html")
    sheet.add_argument("--side", type=int, default=360)
    sheet.add_argument("--disputed", action="store_true", help="only the pairs the two labelers disagree on")
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
    if args.command in ("evaluate", "plan"):
        _rate_arg(parser, args.fp_ceiling, "--fp-ceiling")
    if args.command == "plan" and (args.expect_errors < 0 or args.overdraw < 1 or args.same_share <= 0):
        parser.error("--expect-errors >= 0, --overdraw >= 1 and --same-share > 0")
    return args


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    if args.command == "plan":
        return asyncio.run(run_plan(args.out, ceiling=args.fp_ceiling, expect_errors=args.expect_errors,
                                    overdraw=args.overdraw, same_share=args.same_share, seed=args.seed))
    if args.command == "sheet":
        return run_sheet(args.pairs, args.out, side=args.side, disputed=args.disputed)
    return asyncio.run(run_evaluate(args.labels, vision=args.vision, max_calls=args.max_calls,
                                    out_path=args.out, ceiling=args.fp_ceiling))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
