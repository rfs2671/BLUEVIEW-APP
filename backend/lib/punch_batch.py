"""Photos make items; a text describes the batch (Tue Oct 13, 3:37 PM, 588).

How walkers actually work: a burst of photos, then ONE text about the burst.
Live, 47 items: "Last 8 pics all interior" became photo #13's caption, while
the 7 photos before it stayed blank; "Back of building" and "Cellar" became
the words of single items; 33 photos went out with no words at all.

The rules now:
  1. Only photos make items. A text never makes one, except "add: ...".
  2. A text after photos is about that batch: the photos since the previous
     text -- or, "last N pics ...", exactly the last N photos. Its place
     parts (a floor, an area) are the location; its issue parts are the
     description ("Compound and sheetrock not done", "missing coping"); a
     status with no issue ("All waterproof finished") is a note.
  3. A photo with no words of its own and none from its batch gets a short
     description of what is visible, from the vision model, marked "(auto)"
     and editable -- never a blank item.

Pure: no I/O. The server reads a text (the model, else read_batch here),
picks the photos (targets) and applies it (apply_batch); the walk repair
replays a walk's messages in order through the same rules (replay).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from lib import punch

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
              "fourteen": 14, "fifteen": 15, "twenty": 20}
_PICS = r"(?:pics?|pictures?|photos?|fotos?|images?|shots?|ones)"
_LAST_N = re.compile(
    r"\b(?:the\s+)?(?:last|previous|past|[uú]ltimas?|ultimos?)\s+(?P<n>\d{1,3}|"
    + "|".join(_NUM_WORDS) + r")\s+" + _PICS + r"\b", re.IGNORECASE)
_LEAD = re.compile(r"^\s*(?:(?:in|at|on|en)\s+(?:the\s+|el\s+|la\s+|los\s+|las\s+)?|(?:ok(?:ay)?|so|and|also|well)\s*,?\s+|(?:all\s+of\s+)?(?:that|this|those|these|them|it)\s+(?:was|were|is|are)\s+|(?:these|those|they)\s+(?:are|were)\s+|(?:are|is|were)\s+|all\s+(?:of\s+)?(?:them\s+|these\s+)?"
                   r"(?:are\s+|is\s+)?|everything\s+(?:is\s+)?|todos?\s+|todas?\s+)+", re.IGNORECASE)

#: A status with no issue: a note on the batch, never its description.
_FINE = re.compile(r"\b(?:finished|done|complete[d]?|passed|approved|all\s+set|all\s+good"
                   r"|no\s+issues?|looks?\s+(?:good|fine)|terminad[oa]s?|listo)\b", re.IGNORECASE)
#: A question or an ask, never words about the photos.
_ASK = re.compile(r"\?\s*$|^\s*(?:how|what|when|where|who|why|which|can\s+you|could\s+you|"
                  r"please\s+(?:send|show|cancel|finish)|show\s+me|cancel)\b", re.IGNORECASE)


#: An acknowledgement: nothing about the photos.
_TRIVIAL = re.compile(r"^\W*(?:ok(?:ay)?|k|kk|yes|yeah|yep|no|nope|thanks?|thank\s+you|thx|ty|cool|great|nice"
                      r"|got\s+it|sure|right|alright|👍|🙏|👌)?\W*$", re.IGNORECASE)


def is_trivial(text: Any) -> bool:
    """"ok", "thanks", "👍", "." -- an acknowledgement, never a description."""
    return bool(_TRIVIAL.match(str(text or "").strip()))


def is_ask(text: Any) -> bool:
    """"how many do I have so far?" -- for the assistant, not the photos."""
    return bool(_ASK.search(str(text or "")))
_NOT = re.compile(r"\b(?:not|no|never|isn'?t|aren'?t|wasn'?t|missing|incomplete|unfinished|needs?|"
                  r"without|falta|sin)\b", re.IGNORECASE)


def last_n(text: Any) -> Optional[int]:
    """"last 8 pics", "previous three photos" -> 8, 3; else None."""
    m = _LAST_N.search(str(text or ""))
    if not m:
        return None
    n = m.group("n").lower()
    n = int(n) if n.isdigit() else _NUM_WORDS.get(n)
    return n if n and 1 <= n <= 200 else None


def _strip_scope(text: str) -> str:
    t = _LAST_N.sub(" ", str(text or ""))
    t = " ".join(t.split()).strip(" ,.;:-")
    for _ in range(2):
        t = _LEAD.sub("", t).strip(" ,.;:-")
    return t


#: Place words with no floor: a batch's area, never its description.
_PLACE_ONLY = re.compile(
    r"^(?:(?:the\s+)?(?:inside|outside|interior|exterior|int|ext|indoors?|outdoors?|facade|fa[cç]ade"
    r"|(?:back|front|rear|side|top)(?:\s+(?:of|side\s+of)\s+(?:the\s+)?(?:building|house|bldg|property|lot))?"
    r"|(?:back|front|rear|side)\s+yard|yard|courtyard|alley(?:way)?|driveway|sidewalk|parking(?:\s+lot)?"
    r"|garage|basement|cellar|roof(?:top)?|bulkhead|lobby|hallways?|corridors?|stair(?:s|well|case)?(?:\s+[ab])?"
    r"|boiler\s+room|meter\s+room|mechanical\s+room|elevator\s+(?:pit|room|shaft)|common\s+areas?"
    r"|all\s+units|units?|apartments?|public\s+areas?|amenity|gym|laundry(?:\s+room)?|trash\s+room"
    r"|bathrooms?|kitchens?|bedrooms?|living\s+rooms?)"
    r"(?:\s*(?:,|and|&|/)\s*)?)+$", re.IGNORECASE)


def is_status_note(text: Any) -> bool:
    """"All waterproof finished", "roof done" -- a status, not an issue."""
    t = str(text or "")
    return bool(_FINE.search(t)) and not _NOT.search(t)


def read_batch(text: Any) -> Dict[str, Any]:
    """The words alone (no model): {"last_n", "floor", "area",
    "description", "note"}. The place parts are the location; what is left
    is the description -- or a note when it is a status ("... finished")."""
    raw = " ".join(str(text or "").split())
    out: Dict[str, Any] = {"last_n": last_n(raw), "floor": None, "area": None,
                           "description": None, "note": None}
    rest = _strip_scope(raw)
    if not rest:
        return out
    place = punch.read_group_location(rest)
    if place:                                     # only a place ("2nd floor", "Cellar")
        out.update(floor=place["location"].get("floor"), area=place["location"].get("area"))
        return out
    loc0 = punch.free_location(rest)
    left = punch._LOC_FLOOR.sub(" ", rest) if loc0.get("floor") else rest
    if _PLACE_ONLY.match(" ".join(left.split()).strip(" ,.")):
        # "all interior", "Back of building", "2nd floor interior": the place.
        out.update(floor=loc0.get("floor"), area=loc0.get("area"))
        return out
    loc = punch.read_location(rest)
    words = punch.clean_caption(rest) if (loc.get("floor") or loc.get("area")) else rest
    if loc.get("area") and not str(loc["area"]).startswith("Apt "):
        # "Roof missing coping": the place is the place, not part of the issue.
        words = re.sub(r"(?i)^(?:on\s+(?:the\s+)?|at\s+(?:the\s+)?|in\s+(?:the\s+)?)?"
                       + re.escape(str(loc["area"])) + r"\b\s*[,:-]?\s*", "", words.strip())
    out.update(floor=loc.get("floor"), area=loc.get("area"))
    words = punch.capitalize(words.strip(" ,.;:-")) if words else ""
    if words:
        if is_status_note(words):
            out["note"] = punch.capitalize(_LAST_N.sub(" ", raw).strip(" ,.;:-")) or words
        else:
            out["description"] = words
    return out


BATCH_PROMPT = (
    "A construction super walks a job and sends punch-list photos in WhatsApp, usually a burst "
    "of photos and then ONE text about that burst. Read ONE text and answer with a JSON object "
    "only: {\"kind\": \"annotation\" | \"command\", \"last_n\": int | null, \"floor\": "
    "\"...\" | null, \"area\": \"...\" | null, \"description\": \"...\" | null, \"note\": "
    "\"...\" | null}.\n"
    "kind is \"command\" ONLY when the text tells the assistant to do something with the "
    "walkthrough (finish it, send it, who gets it, cancel, keep it simple, a question); "
    "anything that describes the photos is \"annotation\".\n"
    "last_n: N when it says \"last N pics/photos\", else null.\n"
    "floor: the floor as said (\"2\", \"cellar\", \"roof\", \"lobby\"), else null.\n"
    "area: any other place words, as said (\"interior\", \"back of building\", \"apt 4F\", "
    "\"stair B\"), else null.\n"
    "description: the defect or unfinished work, in their words, short (\"Compound and "
    "sheetrock not done\", \"Missing coping\"), else null. Never put a place in it.\n"
    "note: a status that is NOT a defect (\"All waterproof finished\"), else null.\n"
    "Never translate or add words; copy theirs."
)

_MAX_DESC = 120


def clean_batch_model(got: Any, text: Any) -> Optional[Dict[str, Any]]:
    """The model's reading, checked: None unless it is a JSON object. A
    command comes back {"kind": "command"}. Places must read as places; the
    scope must be what the words say ("last 8" only when they say it)."""
    if not isinstance(got, dict):
        return None
    if got.get("kind") == "command":
        return {"kind": "command"}
    out: Dict[str, Any] = {"kind": "annotation", "last_n": last_n(text), "floor": None,
                           "area": None, "description": None, "note": None}
    place = " ".join(str(x) for x in (
        (f"floor {got['floor']}" if str(got.get("floor") or "").strip().isdigit() else got.get("floor")),
        got.get("area")) if x)
    if place.strip():
        loc = punch.free_location(place)
        out.update(floor=loc.get("floor"), area=loc.get("area"))
    for k in ("description", "note"):
        v = " ".join(str(got.get(k) or "").split()).strip(" .")
        if v and len(v) <= _MAX_DESC:
            out[k] = punch.capitalize(v)
    if out["description"] and is_status_note(out["description"]) and not out["note"]:
        out["note"], out["description"] = out["description"], None
    return out


def is_empty(ann: Dict[str, Any]) -> bool:
    return not any(ann.get(k) for k in ("floor", "area", "description", "note"))


# ── WHICH PHOTOS ─────────────────────────────────────────────────────────────

def photo_items(items: List[dict]) -> List[dict]:
    """The walk's photos, in the order they came in (never a dropped one)."""
    return sorted([it for it in items if it.get("photo_key") is not None or it.get("photo_failed")
                   if it.get("status", "draft") != "dropped"],
                  key=lambda it: it.get("captured") or 0)


def targets(items: List[dict], mark: int, n: Optional[int],
            previous: Optional[List[int]] = None) -> List[dict]:
    """The photos a text is about: the last `n` photos; else every photo
    since the previous text (captured > `mark`); none since -- the previous
    text's photos (`previous`, a second text about the same burst)."""
    photos = photo_items(items)
    if n:
        return photos[-n:]
    since = [it for it in photos if (it.get("captured") or 0) > mark]
    if since:
        return since
    if previous:
        return [it for it in photos if it.get("captured") in previous]
    return photos[-1:]


# ── APPLYING ─────────────────────────────────────────────────────────────────

_SNAP = ("floor", "area", "room", "loc_src", "text", "text_src", "text_auto", "notes",
         "trade", "trade_guess")


def snapshot(it: dict) -> dict:
    """What undo needs to put an item back."""
    return {"captured": it.get("captured"),
            **{k: (list(it[k]) if isinstance(it.get(k), list) else it.get(k)) for k in _SNAP}}


def _own_place(it: dict) -> bool:
    """A place the walker gave this photo (its caption, a reply, "#n")."""
    return it.get("loc_src") == "photo" or (punch.location_ok(it) and it.get("loc_src") != "batch"
                                            and it.get("loc_src") != "group")


def _own_words(it: dict) -> bool:
    return bool((it.get("text") or "").strip()) and not it.get("text_auto") \
        and it.get("text_src") != "batch"


def apply_batch(batch: List[dict], ann: Dict[str, Any], at: Any = None
                ) -> Tuple[List[dict], List[dict]]:
    """Apply one text to its photos (in place). A place the walker gave a
    photo, or its own words, are never overwritten: the batch fills what is
    missing (its words go on a photo that has its own as a note). Returns
    (undo snapshots, the photos it changed)."""
    undo = [snapshot(it) for it in batch]
    changed = []
    place = {"floor": ann.get("floor"), "area": ann.get("area")}
    # The words are for the photos after the last one that came with its own
    # (a caption is a text too): a voice note after a wordless photo is that
    # photo's, never a note on every captioned photo before it. "last N":
    # all N. The place is for the whole batch.
    worded = [i for i, it in enumerate(batch) if _own_words(it)]
    for_words = batch if ann.get("last_n") else (batch[worded[-1] + 1:] if worded else batch)
    for_words = for_words or batch[-1:]
    for it in batch:
        did = False
        if (place["floor"] or place["area"]) and not _own_place(it):
            for k in ("floor", "area"):
                if place[k]:
                    it[k] = place[k]
            if place["area"]:
                it.pop("room", None)
            it["loc_src"] = "batch"
            did = True
        if ann.get("description") and it in for_words:
            if not _own_words(it):
                it["text"] = ann["description"]
                it["text_src"] = "batch"
                it.pop("text_auto", None)
                if (it.get("trade") or punch.UNKNOWN) == punch.UNKNOWN or it.get("trade_guess"):
                    it["trade"], it["trade_guess"] = punch.trade_for(ann["description"])
            else:
                it.setdefault("notes", []).append({"text": ann["description"], "at": at, "src": "batch"})
            did = True
        if ann.get("note") and it in for_words:
            it.setdefault("notes", []).append({"text": ann["note"], "at": at, "src": "batch"})
            did = True
        if did:
            changed.append(it)
    return undo, changed


def restore(items: List[dict], undo: List[dict]) -> List[int]:
    """Put each item back as its snapshot had it. Returns their numbers."""
    ns = []
    for before in undo:
        it = next((i for i in items if i.get("captured") == before.get("captured")), None)
        if not it:
            continue
        for k in _SNAP:
            if k not in before:
                continue
            if before[k] is None:
                it.pop(k, None)
            else:
                it[k] = before[k]
        ns.append(it.get("n"))
    return ns


def confirm(ann: Dict[str, Any], batch: List[dict]) -> str:
    """"Got it — #5–#12 (8 photos): Floor 2 · interior — Compound and
    sheetrock not done." One line."""
    ns = [it["n"] for it in batch]
    bits = []
    where = punch.loc_phrase({"floor": ann.get("floor"), "area": ann.get("area")})
    if where:
        bits.append(where)
    if ann.get("description"):
        bits.append(ann["description"])
    if ann.get("note"):
        bits.append(f"note: {ann['note']}")
    what = " — ".join(bits) if bits else "noted"
    return f"Got it — {punch.numbers_text(ns)} ({len(ns)} photo{'s' if len(ns) != 1 else ''}): {what}."


# ── A WALK REPLAYED (the repair) ─────────────────────────────────────────────

def replay(items: List[dict], events: List[Dict[str, Any]],
           readings: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """A walk taken under the old rules, put right: its messages in order
    (`events`: {"kind": "photo", "message_id"} or {"kind": "text", "text",
    "i"}), each text read (`readings`, by the event's index) and applied
    to its batch. Every item a text made (no photo) is removed; every photo
    item keeps its number (and its P-id); words the old rules took from a
    text are taken back off the photo first. Returns {"items", "removed",
    "applied": [(text, [n...])], "unmatched": [message_id...]}."""
    by_mid = {}
    for it in items:
        if it.get("message_id"):
            by_mid[punch.short_message_id(it["message_id"])] = it
    # The texts by message id, and their words: an item is removed only when
    # a text (or a voice note) that was NOT "add: ..." is shown to have made
    # it -- never an explicit add (Codex on #785).
    said_by_id, said_words = {}, {}
    for e in events:
        if e.get("kind") == "text":
            t = " ".join(str(e.get("text") or "").split())
            said_by_id[punch.short_message_id(e.get("message_id"))] = t
            if not _ADD.match(t):
                said_words[t.lower()] = t
    removed, keep = [], []
    for it in items:
        if it.get("photo_key") is None and not it.get("photo_failed"):
            t = said_by_id.get(punch.short_message_id(it.get("message_id")))
            words = " ".join(str(it.get("said") or it.get("text") or "").split()).lower()
            made_by_text = (t is not None and not _ADD.match(t)) or (
                t is None and not it.get("added_from") and words in said_words)
            if made_by_text:
                removed.append(it)              # a text made it: never an item
                continue
            keep.append(it)                     # "add: ...", or a reply's add: kept
            continue
        if words_came_later(it):
            # Its words were a text sent after it: off the photo, replayed below.
            it.pop("voice", None)
            for k in ("text", "said", "text_src", "text_auto"):
                it.pop(k, None)
            own = punch.short_message_id(it.get("message_id"))
            it["caption_ids"] = [c for c in it.get("caption_ids") or []
                                 if punch.short_message_id(c) == own]
            if it.get("trade_src") != "walker":
                it["trade"], it["trade_guess"] = punch.UNKNOWN, False
            if it.get("loc_src") != "photo":
                for k in ("room", "loc_src"):
                    it.pop(k, None)
                it["floor"] = it["area"] = punch.UNKNOWN
        keep.append(it)
    unmatched: List[str] = []
    applied: List[Tuple[str, List[int]]] = []
    mark, previous = 0, None
    seen_photos: List[dict] = []
    for i, e in enumerate(events):
        if e.get("kind") == "photo":
            it = by_mid.get(punch.short_message_id(e.get("message_id")))
            if it is None or it in removed:
                unmatched.append(str(e.get("message_id") or ""))
                continue
            seen_photos.append(it)
            continue
        ann = readings.get(i)
        if not ann or ann.get("kind") == "command" or is_empty(ann):
            continue
        quoted = by_mid.get(punch.short_message_id(e.get("quoted"))) if e.get("quoted") else None
        if quoted is not None and quoted in keep:
            # A reply to one photo: that photo only; the batch goes on.
            _undo, changed = apply_batch([quoted], {**ann, "last_n": 1}, e.get("at"))
            applied.append((e.get("text") or "", [it["n"] for it in changed]))
            continue
        batch = targets(seen_photos, mark, ann.get("last_n"), previous)
        if not batch:
            continue
        _undo, changed = apply_batch(batch, ann, e.get("at"))
        applied.append((e.get("text") or "", [it["n"] for it in changed]))
        previous = [it.get("captured") for it in batch]
        mark = max([it.get("captured") or 0 for it in seen_photos] or [mark])
    return {"items": keep, "removed": removed, "applied": applied, "unmatched": unmatched}


_ADD = re.compile(r"^\s*add\b", re.IGNORECASE)


def words_came_later(it: dict) -> bool:
    """A photo whose words were a text sent AFTER it (the old rule: the next
    text was the last photo's caption) -- not its own caption."""
    own = punch.short_message_id(it.get("message_id"))
    ids = [punch.short_message_id(c) for c in it.get("caption_ids") or []]
    return bool(it.get("text")) and bool(ids) and own not in ids


def blank(items: List[dict]) -> List[dict]:
    """Live photo items with no words at all: the vision model's to describe."""
    return [it for it in items if it.get("status", "draft") != "dropped"
            and not (it.get("text") or "").strip()]


# ── THE VISION MODEL'S DESCRIPTION ───────────────────────────────────────────

PHOTO_PROMPT = (
    "This is a photo from a construction punch-list walkthrough. In at most 8 words, name the "
    "visible defect or unfinished work, plainly, like a superintendent would (\"Exposed rebar "
    "at slab edge\", \"Missing outlet cover plate\", \"Unfinished drywall taping\"). If nothing "
    "wrong is visible, answer exactly: none. Answer with the words only."
)

#: When the photo cannot be described: still words, never a blank item.
SEE_PHOTO = "See photo"


def clean_description(got: Any) -> Optional[str]:
    """The model's words: at most 8, no quotes or trailing period; None for
    "none" or nothing."""
    t = " ".join(str(got or "").replace("\n", " ").split()).strip(" \"'`.*")
    if not t or t.lower() in ("none", "nothing", "n/a", "no defect", "no defects"):
        return None
    words = t.split()
    if len(words) > 8:
        t = " ".join(words[:8])
    return punch.capitalize(t)


def set_auto(it: dict, words: Optional[str]) -> None:
    """The vision model's words on a blank item, marked "(auto)"."""
    it["text"] = words or SEE_PHOTO
    it["text_auto"] = True
    it["text_src"] = "vision" if words else "none"
