"""Which photos may show the same physical area, and what changed between them.

Ordinary daily photos have no GPS and no per-photo location: the only place
signal is the crew row they were filed under. So this does NOT try to compare
everything. `pick_pairs` chooses few, targeted pairs, and only among photos
filed for ONE level, of the same kind of view and the same kind of work. A
photo filed under "floors 1-4" is never a candidate.

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

from lib import project_report as base

PROMPT_VERSION = "v1"
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


def _group_key(p: Dict[str, Any]) -> Optional[tuple]:
    levels = p.get("levels") or []
    nodes = sorted(set(p.get("nodes") or []) | set(p.get("seen_nodes") or []))
    if len(levels) != 1 or not nodes or p.get("view") not in _COMPARABLE_VIEWS:
        return None
    return (p.get("project_id"), levels[0], p.get("view"), nodes[0])


def pick_pairs(photos: Iterable[Dict[str, Any]], done: Iterable[str], budget: int) -> List[Dict[str, Any]]:
    """At most `budget` pairs not yet asked: within each group of photos of one
    level, view and kind of work, the newest photo against the oldest and
    against the one before it. Newest groups first."""
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
            if other is newest or (base._d(newest["date"]) - base._d(other["date"])).days < MIN_GAP_DAYS:
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
