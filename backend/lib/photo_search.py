"""Search a job's daily-log photos by what they show.

Every filed daily-log photo is read ONCE by the vision model and described in
plain words (`INDEX_PROMPT`). The description, a few search words and where the
photo sits are stored; a search reads only that, so finding a photo costs no
vision call and needs no image. The WhatsApp assistant (find_photos /
send_photos) is the first reader.

Why a pass of its own and not report_photo_verdicts: that judge answers "does
this prove construction progress?". It stores a kind, a score, a trade and a
100-character caption, and its prompt forbids naming a location, so nothing
it stores can tell the front of a building from an interior wall.

Pure functions only: no database, no network.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from lib import progress_report
from lib import project_report as base

VIEWS = ("building_front", "building_side_or_rear", "roof", "interior", "basement",
         "site", "detail", "document", "other")

#: Written on every row as `prompt_v`. A row read before this existed has none:
#: `visible_text` and `room_type` were never asked of it.
PROMPT_V = 2

#: What room the picture shows, when that can be told. Evidence about a photo,
#: never a location: every apartment on every floor has a bathroom.
ROOM_TYPES = ("apartment", "bathroom", "kitchen", "corridor", "stairwell", "elevator", "lobby",
              "mechanical_room", "storage", "cellar", "roof", "exterior", "other", "unknown")

INDEX_PROMPT = (
    "Describe this construction jobsite photo so a project manager can find it later by searching "
    "words. Answer in JSON only: {\"view\": \"building_front\"|\"building_side_or_rear\"|\"roof\"|"
    "\"interior\"|\"basement\"|\"site\"|\"detail\"|\"document\"|\"other\", \"quality\": 0-10, "
    "\"description\": \"...\", \"tags\": [\"...\"], \"visible_text\": [\"...\"], \"room_type\": \"...\"}. "
    "view: building_front is the building's street face seen from outside, from the street or the "
    "sidewalk. building_side_or_rear is an outside face that is plainly not the street face. roof is "
    "taken on the roof. interior is inside the building above ground. basement is below ground or a "
    "cellar. site is the yard, excavation or equipment with no building face in view. detail is a "
    "close-up of one item. document is paper, a screen or a drawing. If you cannot tell which outside "
    "face it is, use building_side_or_rear. "
    "quality: how good this is to show an owner or insurer: sharp, well lit, wide, unobstructed = 8-10; "
    "partial or cluttered = 4-7; blurry, dark or a finger over the lens = 0-3. "
    "description: one or two plain sentences of ONLY what is visible: what is built, the materials, "
    "the stage of the work (for example \"Six-story concrete frame with formwork stripped, sidewalk "
    "shed along the street\"). Never a person's name, a number, a date or an address unless it is "
    "legible in the photo. tags: up to 10 single search words for what is visible. "
    "visible_text: ONLY place markings you can actually read in this photo: door tags, unit or apartment "
    "numbers, floor numbers sprayed or taped on a wall, column or slab, room signs. Copy each exactly as "
    "written. Leave out anything blurry, cut off or partly hidden. Never work a floor or a unit out from "
    "how the place looks, and never guess. If there is none, []. "
    "room_type: one of " + "|".join(ROOM_TYPES) + "; unknown when you cannot plainly tell.")

#: Words a view answers to, so "front of the building" finds a building_front
#: photo whether or not its description says "front".
VIEW_WORDS = {
    "building_front": "front facade exterior outside street elevation face sidewalk",
    "building_side_or_rear": "side rear back exterior outside elevation facade",
    "roof": "roof rooftop top",
    "interior": "interior inside floor",
    "basement": "basement cellar foundation",
    "site": "site yard excavation outside",
    "detail": "detail closeup",
    "document": "document paper drawing",
    "other": "",
}

#: Words that say nothing about what a photo shows.
_NOISE = frozenset("""
a an and any are at be can do for from get give good got have i in is it its me my nice of on or our
pic pics picture pictures photo photos image images shot shots show see send some that the their them
there this those to up us want was we were what where which with you your building job site project
""".split())


def short_id(key: str) -> str:
    """The id a person's assistant uses for a photo: stable across turns."""
    return hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:8]


def parse_index(said: Any) -> Optional[Dict[str, Any]]:
    """The model's answer as {view, quality, description, tags, visible_text,
    room_type}, or None when it said nothing usable (such a photo is tried
    again, never stored blank). An answer without the two newer fields is still
    a description: they come back empty, never invented."""
    found = re.search(r"\{.*\}", str(said or ""), re.S)
    if not found:
        return None
    try:
        v = json.loads(found.group(0))
    except ValueError:
        return None
    if not isinstance(v, dict):
        return None
    description = base.no_phone(" ".join(str(v.get("description") or "").split()))[:300]
    if not description:
        return None
    view = str(v.get("view") or "").strip().lower()
    try:
        quality = max(0.0, min(10.0, float(v.get("quality") or 0)))
    except (TypeError, ValueError):
        quality = 0.0
    raw_tags = v.get("tags") if isinstance(v.get("tags"), list) else []
    tags = [t for t in (base.no_phone(str(x)).strip().lower()[:30] for x in raw_tags) if t][:10]
    raw_text = v.get("visible_text") if isinstance(v.get("visible_text"), list) else []
    visible = [t for t in (base.no_phone(str(x)).strip()[:40] for x in raw_text) if t][:8]
    room = str(v.get("room_type") or "").strip().lower()
    return {"view": view if view in VIEWS else "other", "quality": quality,
            "description": description, "tags": tags, "visible_text": visible,
            "room_type": room if room in ROOM_TYPES else "unknown"}


def log_photo_rows(logbook: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Each photo of a daily log with the crew row it was filed under:
    [{key, photo, log_id, date, sub, where, work}]. Keyed by the one
    definition the report uses (progress_report.log_photos)."""
    by_key = {p["key"]: p for p in progress_report.log_photos(logbook)}
    data = logbook.get("data") if isinstance(logbook.get("data"), dict) else {}
    out, seen = [], set()
    for slot, a in enumerate(data.get("activities") or []):
        if not isinstance(a, dict):
            continue
        for n, p in enumerate(a.get("photos") or []):
            if not isinstance(p, dict):
                continue
            key = progress_report.photo_key(p, f"{logbook.get('_id') or logbook.get('date')}:{slot}", n)
            if key and key in by_key and key not in seen:
                seen.add(key)
                out.append({**by_key[key], "sub": base.no_phone(str(a.get("company") or ""))[:80],
                            "where": base.no_phone(str(a.get("work_locations") or a.get("work_location") or ""))[:80],
                            "work": base.no_phone(str(a.get("work_description") or ""))[:160]})
    return out


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _words(text: Any) -> List[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", str(text or "").lower())]


def query_words(what: Any) -> List[str]:
    return list(dict.fromkeys(w for w in _words(what) if w not in _NOISE))


def search(rows: List[Dict[str, Any]], what: Any = None, *, limit: int = 12) -> List[Dict[str, Any]]:
    """The rows that match `what`, best first: most of the asked words found,
    then the better photo, then the newer. With no words: the best photos.
    A document, or a photo too poor to show, comes up only when it was asked
    for by a word."""
    words = query_words(what)
    scored = []
    for r in rows:
        hay = set(_words(" ".join([str(r.get("description") or ""), " ".join(r.get("tags") or []),
                                   VIEW_WORDS.get(str(r.get("view") or ""), ""),
                                   str(r.get("sub") or ""), str(r.get("where") or ""),
                                   str(r.get("work") or "")])))
        hits = sum(1 for w in words if w in hay)
        if words and not hits:
            continue
        if not words and (r.get("view") == "document" or float(r.get("quality") or 0) < 4):
            continue
        scored.append((hits, float(r.get("quality") or 0), str(r.get("date") or ""), r))
    scored.sort(key=lambda x: x[:3], reverse=True)
    return [x[3] for x in scored[:limit]]
