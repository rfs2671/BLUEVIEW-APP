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


#: Words that say what kind of message it is, never what is wrong:
#: "Correction. 3rd floor interior" -- "Correction" is never a description.
_FILLER = re.compile(
    r"^\s*(?:correction|correct(?:ed|ing)?|sorry|oops|wait|actually|update(?:d)?|edit|fix(?:ed)?|"
    r"my\s+bad|i\s+meant|scratch\s+that|change(?:d)?(?:\s+(?:that|it))?|not\s+that)\b\s*[,.:;!-]*\s*",
    re.IGNORECASE)
#: "Back of building is location", "location: cellar".
_IS_LOCATION = re.compile(r"\s*\b(?:is\s+(?:the\s+)?location|(?:is\s+)?the\s+location)\b\s*$|"
                          r"^\s*(?:the\s+)?location\s*(?:is|:|-)\s*", re.IGNORECASE)


def is_correction(text: Any) -> bool:
    return bool(re.match(r"^\s*(?:correction|correct(?:ed|ing)?|sorry|oops|i\s+meant|scratch\s+that)\b",
                         str(text or ""), re.IGNORECASE))


def strip_filler(text: Any) -> str:
    t = " ".join(str(text or "").split())
    for _ in range(3):
        t2 = _FILLER.sub("", t).strip(" ,.;:-")
        t2 = _IS_LOCATION.sub("", t2).strip(" ,.;:-")
        if t2 == t:
            break
        t = t2
    return t


def _strip_scope(text: str) -> str:
    t = _LAST_N.sub(" ", strip_filler(text))
    t = " ".join(t.split()).strip(" ,.;:-")
    for _ in range(2):
        t = _LEAD.sub("", t).strip(" ,.;:-")
    # Several texts read as one ("Correction. 3rd floor interior" + "Last 3
    # photos") leave sentence breaks: one phrase.
    return strip_filler(re.sub(r"\s*[.;]\s*", " ", t)).strip(" ,.;:-")


#: Place words with no floor: a batch's area, never its description.
_PLACE_ONLY = re.compile(
    r"^(?:(?:the\s+)?(?:inside|outside|interior|exterior|int|ext|indoors?|outdoors?|facade|fa[cç]ade"
    r"|(?:back|front|rear|side|top)(?:\s+(?:of|side\s+of)\s+(?:the\s+)?(?:building|house|bldg|property|lot))?"
    r"|(?:back|front|rear|side)\s*yard|yard|courtyard|alley(?:way)?|driveway|sidewalk|parking(?:\s+lot)?"
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
                           "description": None, "note": None, "correction": is_correction(raw)}
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


_ORD = {"first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5", "sixth": "6",
        "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10"}


def _floor_number(v: Any) -> Optional[str]:
    """"3", "3rd", "third", "3rd floor", "floor 3" -> "3"; else None."""
    t = str(v or "").strip().lower()
    m = re.fullmatch(r"(?:floor\s+)?(\d{1,3})(?:st|nd|rd|th)?(?:\s+(?:floor|fl\.?))?", t)
    if m:
        return m.group(1)
    m = re.fullmatch(r"(\w+)(?:\s+(?:floor|fl\.?))?", t)
    return _ORD.get(m.group(1)) if m else None


def _place_only(text: Any) -> bool:
    """Words that are only a place ("Back of building", "5th floor
    staircase", "Cellar"): a location, never a description."""
    t = strip_filler(text)
    if not t:
        return False
    r = read_batch(t)
    return not r.get("description") and not r.get("note") and bool(r.get("floor") or r.get("area"))


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
    floor = _floor_number(got.get("floor"))
    place = " ".join(str(x) for x in (
        (f"floor {floor}" if floor else got.get("floor")), got.get("area")) if x)
    if place.strip():
        loc = punch.free_location(place)
        out.update(floor=loc.get("floor"), area=loc.get("area"))
    if floor and not out["floor"]:
        out["floor"] = floor
    for k in ("description", "note"):
        v = strip_filler(got.get(k)).strip(" .")
        if v and len(v) <= _MAX_DESC and not _place_only(v):
            out[k] = punch.capitalize(v)
    out["correction"] = is_correction(text)
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

#: Texts this close together, with no photo between them, are one message:
#: "Correction. 3rd floor interior" then "Last 3 photos" (11:52) is ONE
#: annotation for the last 3 photos.
MERGE_SECONDS = 60

#: "Same for the last batch of pics": about OTHER photos, by reference --
#: placed by the model or listed as "couldn't place", never guessed.
_REFERENCE = re.compile(
    r"^\s*(?:(?:the\s+)?same\s+(?:for|as|thing|here|with|on)\b|same\b\s*$|ditto\b|"
    r"(?:also\s+)?(?:the\s+)?same\s+(?:goes\s+)?for\b|those\s+too\b|these\s+too\b)", re.IGNORECASE)

#: A text this soon after "Where is #3 ...?" (and no photo since) answers it.
ANSWER_SECONDS = 10 * 60

#: The assistant asking about ONE item: "Where is #3 'Back of building'?".
_ASKS_ITEM = re.compile(r"\bWhere\s+is\s+#(\d{1,3})\b", re.IGNORECASE)

#: Under this heading in the draft: what could not be put on photos.
UNPLACED_HEADING = punch.UNPLACED_HEADING


def is_reference(text: Any) -> bool:
    return bool(_REFERENCE.search(strip_filler(text) or str(text or "")))


def _ts(at: Any) -> Optional[float]:
    try:
        return at.timestamp()
    except Exception:
        return None


def merge_texts(events: List[Dict[str, Any]], is_command=lambda t: False,
                seconds: int = MERGE_SECONDS) -> List[Dict[str, Any]]:
    """The walker's consecutive texts, each within `seconds` of the one
    before, with no photo or voice note between them, read as one:
    "Correction. 3rd floor interior" + "Last 3 photos" -> one annotation.
    The assistant's own replies in between do not split them (11:52: the bot
    answered between the two) -- unless it ASKED about an item ("Where is
    #3 ...?"): the next text is the answer. A command ("done") or a
    reference ("same for ...") is never merged."""
    out: List[Dict[str, Any]] = []
    last = None                                   # index in `out` of the walker's last text
    for e in events:
        kind = e.get("kind")
        if kind == "bot":
            out.append(dict(e))
            if _ASKS_ITEM.search(e.get("text") or ""):
                last = None
            continue
        prev = out[last] if last is not None else None
        if (kind == "text" and prev is not None
                and not prev.get("voice") and not e.get("voice") and not e.get("quoted")
                and not prev.get("quoted")
                and not is_command(e.get("text") or "") and not is_command(prev.get("text") or "")
                and not is_reference(e.get("text")) and not is_reference(prev.get("text"))):
            a, b = _ts(prev.get("at")), _ts(e.get("at"))
            if a is not None and b is not None and 0 <= b - a <= seconds:
                prev["text"] = (prev.get("text") or "").rstrip(" .") + ". " + (e.get("text") or "").strip()
                prev.setdefault("merged_ids", [prev.get("message_id")]).append(e.get("message_id"))
                prev["at"] = e.get("at")
                continue
        out.append(dict(e))
        last = len(out) - 1 if kind == "text" else None
    return out


#: The assistant confirming a photo when it came in: "#1 'Front' (Facade)",
#: "#15 (Floor 5 · stairs)", "#47 (Floor 7 · bulkhead)". What the walker saw
#: and let stand -- the photo's place at the time, which no later batch
#: text overwrites.
_CONFIRMED = re.compile(
    r"#(\d{1,3})(?:\s+['\u2018\u201c\"]([^'\u2019\u201d\"]{0,80})['\u2019\u201d\"])?\s*\(([^()]{1,60})\)")
_NOT_A_PLACE = re.compile(r"\bphotos?\b|\bpics?\b|^\s*\?\s*$|not\s+given|no\s+location|unknown",
                          re.IGNORECASE)
_LEVELS = ("cellar", "basement", "sub-cellar", "subcellar", "lobby", "ground", "roof", "rooftop",
           "bulkhead", "penthouse", "mezzanine", "attic")


def place_from_label(label: Any) -> Optional[Dict[str, Optional[str]]]:
    """"Floor 5 · stairs" -> floor 5, stairs; "Facade" -> the area Facade;
    "Roof" -> the level roof. None when it is not a place."""
    t = " ".join(str(label or "").split()).strip(" .")
    if not t or _NOT_A_PLACE.search(t):
        return None
    parts = [x.strip() for x in re.split(r"\s*[·•|]\s*", t) if x.strip()]
    head, rest = parts[0], " · ".join(parts[1:]) or None
    m = re.fullmatch(r"(?i)(?:floor|fl\.?)\s*(\w{1,4})", head)
    if m:
        f = _floor_number(m.group(1)) or m.group(1).lower()
        return {"floor": f, "area": rest}
    f = _floor_number(head)
    if f and re.search(r"(?i)\bfloor\b|\d", head):
        return {"floor": f, "area": rest}
    if head.lower() in _LEVELS:
        return {"floor": head.lower(), "area": rest}
    return {"floor": None, "area": head if not rest else f"{head} · {rest}"}


def capture_confirmations(text: Any) -> List[Tuple[int, Optional[str], Dict[str, Optional[str]]]]:
    """[(n, the caption as quoted, its place)] in one assistant message."""
    out = []
    for m in _CONFIRMED.finditer(str(text or "")):
        place = place_from_label(m.group(3))
        if place:
            out.append((int(m.group(1)), m.group(2), place))
    return out


def pin_confirmed(it: dict, place: Dict[str, Optional[str]]) -> None:
    """The place the assistant confirmed for this photo when it came in."""
    # The label is the whole place at that moment: "(Facade)" had no floor.
    it["floor"] = place.get("floor") or punch.UNKNOWN
    it["area"] = place.get("area") or punch.UNKNOWN
    it.pop("room", None)
    it["loc_src"] = "photo"
    it["confirmed"] = True


def own_caption_place(it: dict) -> Optional[Dict[str, Any]]:
    """A photo's own caption read: "Back of building" is its location (the
    description comes from vision, "(auto)"); "Roof missing coping" is Roof
    + "Missing coping". None when the caption has no place in it."""
    words = (it.get("text") or "").strip()
    if not words or it.get("text_auto") or it.get("text_src") in ("batch", "vision", "none"):
        return None
    r = read_batch(words)
    if not (r.get("floor") or r.get("area")):
        return None
    return r


def _apply_own_place(it: dict, r: Dict[str, Any]) -> None:
    # The photo's own caption is its location, as typed ("Backyard", never a
    # canonical "Courtyard"; "5th floor staircase" -> Floor 5 · staircase).
    # A caption with no floor ("Interior") keeps the floor the photo already
    # had (#8 Floor 2 + "Interior" is Floor 2 · interior, never "Interior").
    it["floor"] = r.get("floor") or it.get("floor") or punch.UNKNOWN
    it["area"] = r.get("area") or punch.UNKNOWN
    it.pop("room", None)
    it["loc_src"] = "photo"
    it.setdefault("said", it.get("text"))
    if r.get("description"):
        it["text"] = r["description"]
    elif r.get("note"):
        it["text"] = r["note"]
    else:
        # Only a place: the vision model describes it, marked (auto).
        it.pop("text", None)
        it.pop("text_src", None)


def apply_answer(it: dict, ann: Dict[str, Any], at: Any = None) -> bool:
    """A text answering "Where is #3 ...?": that item only. Its place is
    the item's location (it was asked for); its words fill an empty item."""
    did = False
    if ann.get("floor") or ann.get("area"):
        if ann.get("floor"):
            it["floor"] = ann["floor"]
        if ann.get("area"):
            it["area"] = ann["area"]
            it.pop("room", None)
        it["loc_src"] = "answer"
        did = True
    if ann.get("description"):
        if not _own_words(it):
            it["text"], it["text_src"] = ann["description"], "batch"
            it.pop("text_auto", None)
        else:
            it.setdefault("notes", []).append({"text": ann["description"], "at": at, "src": "answer"})
        did = True
    return did


def replay(items: List[dict], events: List[Dict[str, Any]],
           readings: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """A walk taken under the old rules, put right: its messages in order
    (`events`: {"kind": "photo"|"text"|"voice"|"bot", ...}; texts already
    merged, see merge_texts), each text read (`readings`, by the event's
    index) and applied:
      * to its batch (the photos since the previous text, or "last N");
      * to ONE item when it replies to that photo, or answers the
        assistant's "Where is #3 ...?";
      * "same for ..." (a reference) -- not applied here: returned in
        "references" for the model to place, else listed as unplaced.
    Every item a text made (no photo) is removed; every photo keeps its
    number (and its P-id); words the old rules took from a later text come
    off the photo; a caption that is only a place becomes its location.
    Returns {"items", "removed", "applied": [(text, [n...])], "unmatched",
    "outcome": {event index: str}, "references": [...], "unplaced": [...]}."""
    by_mid = {}
    for it in items:
        if it.get("message_id"):
            by_mid[punch.short_message_id(it["message_id"])] = it
    said_by_id, said_words = {}, {}
    for e in events:
        if e.get("kind") == "text":
            t = " ".join(str(e.get("text") or "").split())
            for mid in e.get("merged_ids") or [e.get("message_id")]:
                said_by_id[punch.short_message_id(mid)] = t
            if not _ADD.match(t):
                said_words[t.lower()] = t
                for part in re.split(r"\.\s+", t):
                    said_words[part.strip(" .").lower()] = part
    removed, keep = [], []
    for it in items:
        if it.get("photo_key") is None and not it.get("photo_failed"):
            t = said_by_id.get(punch.short_message_id(it.get("message_id")))
            words = " ".join(str(it.get("said") or it.get("text") or "").split()).lower()
            made_by_text = (t is not None and not _ADD.match(t)) or (
                t is None and not it.get("added_from") and words.strip(" .") in said_words)
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
        else:
            r = own_caption_place(it)
            if r:
                _apply_own_place(it, r)         # "Back of building": its location
        keep.append(it)
    by_n = {it.get("n"): it for it in keep}
    unmatched: List[str] = []
    applied: List[Tuple[str, List[int]]] = []
    outcome: Dict[int, str] = {}
    references: List[Dict[str, Any]] = []
    batches: List[Dict[str, Any]] = []          # [{"ns", "text", "ann"}], in order
    mark, previous = 0, None
    asking: Optional[int] = None                # "Where is #3 ...?" waiting for its answer
    asked_at: Optional[float] = None
    seen_photos: List[dict] = []
    for i, e in enumerate(events):
        kind = e.get("kind")
        if kind == "photo":
            it = by_mid.get(punch.short_message_id(e.get("message_id")))
            asking = None
            if it is None or it in removed:
                unmatched.append(str(e.get("message_id") or ""))
                outcome[i] = "no item for this photo"
                continue
            seen_photos.append(it)
            outcome[i] = f"#{it.get('n')}"
            continue
        if kind == "bot":
            m = _ASKS_ITEM.search(e.get("text") or "")
            if m:
                asking, asked_at = int(m.group(1)), _ts(e.get("at"))
            got = []
            for n, _said, place in capture_confirmations(e.get("text")):
                it = by_n.get(n)
                if it is not None and not it.get("confirmed"):
                    pin_confirmed(it, place)
                    got.append(f"#{n} {place_label(place.get('floor'), place.get('area'))}")
            if got:
                outcome[i] = "confirmed at capture: " + ", ".join(got)
            continue
        if kind == "voice":
            outcome[i] = "voice note -- no transcript stored, not applied"
            continue
        ann = readings.get(i)
        if not ann:
            outcome[i] = "not read"
            continue
        if ann.get("kind") == "command":
            outcome[i] = "command (not about photos)"
            continue
        if ann.get("kind") == "reference":
            references.append({"i": i, "text": e.get("text") or "", "at": e.get("at"),
                               "batches": [dict(b) for b in batches],
                               "copy": dict(batches[-1]["ann"]) if batches else None})
            outcome[i] = "a reference to other photos -- placed below, or listed as couldn't place"
            continue
        if is_empty(ann):
            outcome[i] = "nothing to apply"
            continue
        quoted = by_mid.get(punch.short_message_id(e.get("quoted"))) if e.get("quoted") else None
        if quoted is not None and quoted in keep:
            # A reply to one photo: that photo only; the batch goes on.
            _undo, changed = apply_batch([quoted], {**ann, "last_n": 1}, e.get("at"))
            applied.append((e.get("text") or "", [it["n"] for it in changed]))
            outcome[i] = f"reply to #{quoted.get('n')}: " + describe(ann)
            continue
        t_at = _ts(e.get("at"))
        if asking is not None and asked_at is not None and t_at is not None \
                and t_at - asked_at > ANSWER_SECONDS:
            asking = None                       # too long after the question
        if asking is not None and asking in by_n:
            # Answering "Where is #3 ...?": #3 only, never a batch (12:02).
            it = by_n[asking]
            apply_answer(it, ann, e.get("at"))
            applied.append((e.get("text") or "", [asking]))
            outcome[i] = f"answer about #{asking}: " + describe(ann)
            continue
        batch = targets(seen_photos, mark, ann.get("last_n"), previous)
        if not batch:
            outcome[i] = "no photos before it"
            continue
        if ann.get("correction"):
            # "Correction ...": its place replaces what any text set before
            # (a photo's own caption and an answer about it still stand).
            for it in batch:
                if it.get("loc_src") not in ("photo", "answer"):
                    it["loc_src"] = "batch"
        _undo, changed = apply_batch(batch, ann, e.get("at"))
        ns = [it["n"] for it in changed]
        applied.append((e.get("text") or "", ns))
        batches.append({"ns": [it["n"] for it in batch], "text": e.get("text") or "", "ann": dict(ann)})
        outcome[i] = (f"{punch.numbers_text(ns)}: " if ns else "nothing changed: ") + describe(ann)
        previous = [it.get("captured") for it in batch]
        mark = max([it.get("captured") or 0 for it in seen_photos] or [mark])
    return {"items": keep, "removed": removed, "applied": applied, "unmatched": unmatched,
            "outcome": outcome, "references": references, "unplaced": []}


def describe(ann: Dict[str, Any]) -> str:
    """"Floor 3 · interior — Missing coping" (what a text says)."""
    bits = [b for b in (place_label(ann.get("floor"), ann.get("area")),
                        ann.get("description"),
                        (f"note: {ann['note']}" if ann.get("note") else None)) if b]
    return " — ".join(bits) or "nothing"


def place_label(floor: Any, area: Any) -> str:
    """"Floor 3 · interior", "Floor 1 · Back of building", "Cellar", ""."""
    return punch.place_label(floor, area)


REFERENCE_PROMPT = (
    "A construction super sent punch-list photos in batches, each batch followed by a text. "
    "Then they sent a text that refers to other photos (\"same for the last batch of pics\"). "
    "You get the batches in order (their photo numbers and text) and that text. Answer with a "
    "JSON object only: {\"photos\": [numbers] | null, \"copy_from\": batch index | null}. "
    "photos: exactly which photo numbers the text is about; copy_from: which batch's words it "
    "says to repeat. If it is not clear which photos are meant, answer {\"photos\": null}. "
    "Never guess."
)


def clean_reference(got: Any, ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The model's placing of a reference, checked: photo numbers that exist
    in the batches, and a batch to copy that exists. None when unclear."""
    if not isinstance(got, dict) or not isinstance(got.get("photos"), list):
        return None
    known = {n for b in ref.get("batches") or [] for n in b.get("ns") or []}
    ns = sorted({int(n) for n in got["photos"] if str(n).isdigit() and int(n) in known})
    if not ns:
        return None
    src = got.get("copy_from")
    bs = ref.get("batches") or []
    if isinstance(src, int) and 0 <= src < len(bs):
        ann = bs[src]["ann"]
    else:
        ann = ref.get("copy")
    if not ann or is_empty(ann):
        return None
    return {"ns": ns, "ann": {**ann, "last_n": None, "correction": False}}


def apply_reference(items: List[dict], placed: Dict[str, Any], at: Any = None) -> List[int]:
    batch = [it for it in items if it.get("n") in placed["ns"]]
    if not batch:
        return []
    _undo, changed = apply_batch(batch, {**placed["ann"], "last_n": len(batch)}, at)
    return [it["n"] for it in changed]


# The walker's answer to "Couldn't place — tell me which photos": photo
# numbers only ("9 10", "photos 9 and 10", "#9-12"), or "skip". Anything
# else is an ordinary draft edit.
_UNPLACED_NUMS = re.compile(
    r"^\s*(?:(?:the\s+)?(?:photos?|pics?|pictures?|items?)\s*)?"
    r"(?P<ns>#?\d{1,3}(?:\s*(?:-|–|to|thru|through)\s*#?\d{1,3})?"
    r"(?:\s*(?:,|and|&|\s)\s*#?\d{1,3}(?:\s*(?:-|–|to|thru|through)\s*#?\d{1,3})?)*)\s*\.?\s*$",
    re.IGNORECASE)
_UNPLACED_SKIP = re.compile(r"^\s*(?:skip|ignore|none|no|leave\s+it|drop\s+it|forget\s+it)\s*[.!]?\s*$",
                            re.IGNORECASE)


def unplaced_entry(label: str, ref: Dict[str, Any]) -> Dict[str, Any]:
    """What a walk keeps of a reference it couldn't place: the line shown,
    and the batch words it would copy (the batch just before it)."""
    copy = ref.get("copy")
    return {"label": label, "copy": dict(copy) if copy else None}


def unplaced_reply(text: Any) -> Optional[Dict[str, Any]]:
    """{"skip": True}, {"ns": [9, 10]}, or None (not an answer)."""
    t = str(text or "")
    if _UNPLACED_SKIP.match(t):
        return {"skip": True}
    m = _UNPLACED_NUMS.match(t)
    if not m:
        return None
    ns = sorted(set(punch._numbers(m.group("ns"))))
    return {"ns": ns} if ns else None


def place_unplaced(items: List[dict], entry: Dict[str, Any], ns: List[int],
                   at: Any = None) -> Tuple[List[int], List[int]]:
    """Apply an unplaced entry's words to the photos the walker named.
    Returns (changed numbers, numbers with no live item)."""
    live = {it.get("n") for it in items if it.get("status", "draft") != "dropped"}
    missing = [n for n in ns if n not in live]
    ann = entry.get("copy")
    ok = [n for n in ns if n in live]
    if not ann or is_empty(ann) or not ok:
        return [], missing
    return apply_reference(items, {"ns": ok, "ann": {**ann, "last_n": None, "correction": False}}, at), \
        missing


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


def set_auto(it: dict, words: Optional[str], error: Optional[str] = None) -> None:
    """The vision model's words on a blank item, marked "(auto)". No words:
    the item stays without a description (shown "(no description)") and
    keeps why -- never a stand-in like "See photo"."""
    if words:
        it["text"] = words
        it["text_auto"] = True
        it["text_src"] = "vision"
        it.pop("vision_error", None)
    else:
        it.pop("text", None)
        it.pop("text_auto", None)
        it["text_src"] = "none"
        it["vision_error"] = error or "no description"
