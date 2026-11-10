"""Which photos may show the same physical area, and what changed between them.

Ordinary daily photos have no GPS and no per-photo location. So this does NOT
try to compare everything. `pick_pairs` chooses few, targeted pairs, and only
among photos whose place is inferred with sufficient certainty (lib/photo_place)
to ONE level, in one space when one is known, of the same kind of view, room and
work. A photo filed under "floors 1-4" is never a candidate.

A MISS IS UNCONFIRMED, NEVER DIFFERENT. Construction changes how a place looks:
studs become board and most feature points stop existing. So the deterministic
geometry check (lib/photo_geometry) can only ADD support. The same holds for a
vision answer that is not a confident yes. `combine` returns `supported` or
`unconfirmed`, and nothing here ever concludes "different location". Nothing
here removes or weakens a photo's own evidence (its log place, plan-tag text,
description): a comparison is stored beside the photos and read only when it
supports them.

NOTHING RUNS AUTOMATICALLY YET. Floor + trade + general view is not enough to
call two photos one place, and how well geometry or the model tells places apart
has not been measured. `GEOMETRY_MIN_INLIERS` and `VISION_MIN_CONFIDENCE` are
None until scripts/photo_relation_benchmark.py has been run on real labeled
photos. While either is None, `pick_pairs` returns nothing and
PHOTO_RELATIONS_ENABLED alone starts nothing.

A pair is asked of the vision model once and stored by its two photo keys
(`pair_id`). The answer is an AI observation: `same_area` may be "unsure", and
nothing here can prove an inspection, an installed quantity or completion. The
prompt says so and `parse_compare` keeps nothing else. A stored answer is never
rewritten; a later prompt version writes a new row.

Pure: no database, no network.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from lib import photo_place
from lib import project_report as base

PROMPT_VERSION = "v1"
#: Set ONLY from a real benchmark run. None: no automatic comparison at all.
GEOMETRY_MIN_INLIERS: Optional[int] = None
GEOMETRY_MIN_RATIO: float = 0.0
#: The confidence a vision "yes" must reach to count as support. Set ONLY from
#: a real benchmark run.
VISION_MIN_CONFIDENCE: Optional[float] = None
SUPPORTED, UNCONFIRMED = "supported", "unconfirmed"
MIN_QUALITY = 4.0
#: Two photos a day or two apart rarely show a change worth a paid call.
MIN_GAP_DAYS = 3
_COMPARABLE_VIEWS = ("interior", "basement", "roof", "building_front", "building_side_or_rear", "site")

COMPARE_PROMPT = (
    "These are two construction jobsite photos of the same project, the FIRST taken earlier than the SECOND. "
    "Answer in JSON only: {\"same_area\": \"yes\"|\"no\"|\"unsure\", \"confidence\": 0-1, \"changes\": [\"...\"], "
    "\"installed\": [\"...\"], \"possible_rework\": [\"...\"]}. "
    "same_area is yes only when fixed features (openings, columns, walls, pipes, windows) show both photos are the "
    "same physical area, even from a different angle or at a different stage; no when they plainly are not; "
    "otherwise unsure. If same_area is not yes, leave the lists empty. changes: short plain phrases of what is "
    "visibly different in the second photo. installed: materials visibly added. possible_rework: only something "
    "visibly removed or redone. Never say whether anything passed inspection, is complete, is code compliant or "
    "what percent is done. Never guess a floor, a unit or a company.")


def pair_id(key_a: str, key_b: str) -> str:
    a, b = sorted((str(key_a), str(key_b)))
    return f"{PROMPT_VERSION}:{a}|{b}"


def automatic_ready() -> bool:
    """Has a benchmark on real photos set both thresholds?"""
    return GEOMETRY_MIN_INLIERS is not None and VISION_MIN_CONFIDENCE is not None


def geometry_agrees(g: Optional[Dict[str, Any]]) -> bool:
    """Does a lib/photo_geometry.match result clear the benchmarked threshold?
    False, always, when there is no threshold or the images could not be measured."""
    if GEOMETRY_MIN_INLIERS is None or not g or not g.get("ok"):
        return False
    return int(g.get("inliers") or 0) >= GEOMETRY_MIN_INLIERS and float(g.get("ratio") or 0) >= GEOMETRY_MIN_RATIO


def vision_supports(v: Optional[Dict[str, Any]]) -> bool:
    """A confident "yes" from the model, above the benchmarked confidence."""
    return bool(v) and VISION_MIN_CONFIDENCE is not None and v.get("same_area") == "yes" \
        and float(v.get("confidence") or 0) >= VISION_MIN_CONFIDENCE


def combine(vision: Optional[Dict[str, Any]], geometry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{"same_place": supported | unconfirmed, "support": [signals]}.

    Each signal can only add support. A geometry miss, a failed measurement, an
    "unsure" or no answer adds nothing and takes nothing away. When the model
    says "no" while geometry agrees, the two disagree and the pair stays
    unconfirmed. There is no "different" outcome."""
    support = [name for name, ok in (("vision", vision_supports(vision)), ("geometry", geometry_agrees(geometry))) if ok]
    disputed = bool(vision) and vision.get("same_area") == "no"
    return {"same_place": SUPPORTED if support and not disputed else UNCONFIRMED, "support": support}


def _group_key(p: Dict[str, Any]) -> Optional[tuple]:
    place = p.get("place")
    nodes = sorted(set(p.get("nodes") or []) | set(p.get("seen_nodes") or []))
    if not photo_place.is_sufficient(place) or not place.get("level") or not nodes \
            or p.get("view") not in _COMPARABLE_VIEWS:
        return None
    return (p.get("project_id"), place["level"], place.get("space") or "", p.get("view"), nodes[0])


def _same_room(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    ra, rb = (a.get("place") or {}).get("room_type"), (b.get("place") or {}).get("room_type")
    return not ra or not rb or ra == rb


def pick_pairs(photos: Iterable[Dict[str, Any]], done: Iterable[str], budget: int) -> List[Dict[str, Any]]:
    """At most `budget` pairs not yet asked: within each group of photos of one
    inferred place, view and kind of work, the newest photo against the oldest
    and against the one before it. Newest groups first. Nothing until a
    geometry threshold has been measured (see the module docstring)."""
    if not automatic_ready():
        return []
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for p in photos:
        key = _group_key(p)
        if key and float(p.get("quality") or 0) >= MIN_QUALITY and base._d(p.get("date")):
            groups.setdefault(key, []).append(p)
    seen = set(done)
    out: List[Dict[str, Any]] = []
    for rows in sorted(groups.values(), key=lambda g: max(str(p["date"]) for p in g), reverse=True):
        rows = sorted(rows, key=lambda p: (str(p["date"]), str(p.get("photo_key"))))
        newest = rows[-1]
        for other in (rows[0], rows[-2] if len(rows) > 1 else rows[0]):
            if other is newest or (base._d(newest["date"]) - base._d(other["date"])).days < MIN_GAP_DAYS \
                    or not _same_room(other, newest):
                continue
            pid = pair_id(other["photo_key"], newest["photo_key"])
            if pid in seen:
                continue
            seen.add(pid)
            out.append({"pair_id": pid, "first": other, "second": newest})
            if len(out) >= budget:
                return out
    return out


def _phrases(v: Any) -> List[str]:
    if not isinstance(v, list):
        return []
    return [t for t in (base.no_phone(" ".join(str(x).split()))[:120] for x in v) if t][:6]


def parse_compare(said: Any) -> Optional[Dict[str, Any]]:
    """The model's answer, checked; None when unusable. Only "yes" keeps lists."""
    found = re.search(r"\{.*\}", str(said or ""), re.S)
    if not found:
        return None
    try:
        v = json.loads(found.group(0))
    except ValueError:
        return None
    if not isinstance(v, dict):
        return None
    same = str(v.get("same_area") or "").strip().lower()
    if same not in ("yes", "no", "unsure"):
        return None
    try:
        conf = max(0.0, min(1.0, float(v.get("confidence") or 0)))
    except (TypeError, ValueError):
        conf = 0.0
    yes = same == "yes"
    return {"same_area": same, "confidence": conf, "changes": _phrases(v.get("changes")) if yes else [],
            "installed": _phrases(v.get("installed")) if yes else [],
            "possible_rework": _phrases(v.get("possible_rework")) if yes else []}
