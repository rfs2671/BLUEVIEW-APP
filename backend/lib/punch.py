"""Walkthrough -> punch list -> chase, the rules in pure code.

A super walks the job and DMs the assistant: "starting walkthrough at 588",
then photos, each with a caption or a voice note (English, Spanish or
Yiddish). Each photo + its words is ONE item. The assistant answers each with
a 👍 and nothing else. Unknown area or trade is kept and marked "?".

"done" makes a DRAFT, never a final list: grouped by floor/area, then trade,
numbered, 📷 / 🎤 markers, the "?" items called out. The walker fixes it in
words (typed or spoken): "2 → electrical", "drop 6", "merge 4 and 5",
"add: …", "move 3 to floor 6". Then the assistant suggests an assignee per
trade (from the job's check-in companies and People); one due question:
"Due Fri for all, or by trade?". "send" posts one group message per assignee
(@mention, their items, photos) -- or, while the project's "Punch sends" is
SHADOW (the default), shows the walker what it WOULD send and posts nothing.
Sent items enter the attention / chase engine: confirmed owner, due date.

Closing: the sub says "done" (a photo ideally) -> READY TO CHECK, never
closed by the sub. The super: "P23 ok" -> closed, with the completion
evidence; "P23 not done" -> reopened, chasing resumes.

Ids: P-<job>-<seq> ("P-588-23"); "P23" means item 23 of the job in context.

Nothing here touches the network or the database: server.py does that.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lib import multilang

COLLECTION = "punch_items"
SESSIONS = "punch_sessions"
#: One row while a walker's turn runs (any container): the next turn waits.
LEASES = "punch_leases"
LEASE_SECONDS = 30
COUNTERS = "punch_counters"

STATUSES = ("draft", "open", "ready_to_check", "closed", "dropped")
LIVE = ("open",)                       # what the chase engine chases
SEND_MODES = ("shadow", "live")
#: Project setting "Punch list goes to": one message per trade (default), or
#: the whole list to one person.
PUNCH_TO = ("per_trade", "one_person")
DEFAULT_SEND_MODE = "shadow"
DRAFT_REMIND_HOURS = 24
UNKNOWN = "?"
#: Beside an assignee whose @mention would not notify (lib/wa_mention).
NO_NUMBER_NOTE = "mention won't notify (no number)"

# ── STARTING A WALKTHROUGH ───────────────────────────────────────────────────

_START = re.compile(
    r"^\s*(?:start(?:ing)?|begin(?:ning)?|empezando|empiezo|comenzando)\s+"
    r"(?:a\s+|the\s+|el\s+|un\s+)?(?:walk\s*-?\s*through|walk|punch(?:\s*list)?|recorrido)"
    r"(?:\s+(?:at|@|en|for)\s+(?P<job>.+?))?\s*[.!]*\s*$", re.IGNORECASE)


def start_request(text: Any) -> Optional[Dict[str, Optional[str]]]:
    """{"job": "588" | None} for "starting walkthrough at 588", else None."""
    m = _START.match(str(text or ""))
    if not m:
        return None
    job = (m.group("job") or "").strip() or None
    return {"job": job}


def match_project(hint: Optional[str], projects: List[Dict[str, Any]]) -> Tuple[Optional[dict], str]:
    """The one project a hint names ("588" -> "588 Thomas St"), by its number,
    name or address. (project, "") or (None, why): "none" | "several"."""
    if len(projects) == 1 and not hint:
        return projects[0], ""
    if not hint:
        return None, "none" if not projects else "several"
    h = multilang.fold(hint).strip()
    hits = []
    for p in projects:
        name = multilang.fold(f"{p.get('name') or ''} {p.get('address') or ''}")
        num = str(p.get("job_code") or "")
        if h == num.lower() or re.search(r"(?<!\w)" + re.escape(h) + r"(?!\w)", name):
            hits.append(p)
    if len(hits) == 1:
        return hits[0], ""
    return None, "none" if not hits else "several"


#: A walkthrough still capturing ends after this long with nothing from the
#: walker (a draft waits for "send", with its own reminder).
CAPTURE_IDLE_HOURS = 2
#: A job picked in this DM this recently is the walkthrough's job.
JOB_PICK_MINUTES = 30
#: Typed during a walk, words go on the photo sent this recently; older,
#: the walker is asked which photo.
NOTE_LAST_MINUTES = 10
WHICH_PHOTO = "Add to which photo? Reply to it, or send its number (e.g. #2)."
WHERE_HELP = ("e.g. \"4th floor Apt 4F\", \"4F\", or a named area: lobby, roof, cellar, "
              "boiler room, meter room, elevator machine room, stairwell A, corridor + floor. "
              "Or 'drop' to leave it out.")
#: In the draft (and the recap): these send it on.
SEND_WORDS = ("send", "send it", "enviar", "manda", "mandalo", "shik", "done", "ok", "okay",
              "looks good", "look good", "good", "all good", "go", "yes", "listo", "fartik")
DONE_WORDS = ("done", "listo", "fartik", "finished", "that's it", "thats it")
CANCEL_WORDS = ("cancel walkthrough", "cancel", "stop walkthrough", "cancel punch",
                "cancel punch list", "cancel the walkthrough", "cancel the punch list",
                "cancelar", "cancela")


def job_question(projects: List[Dict[str, Any]], label=None) -> str:
    """Asked once, at the first photo, when the job is not known."""
    label = label or (lambda p: str(p.get("name") or p.get("address") or ""))
    opts = "\n".join(f"{i}. {label(p)}" for i, p in enumerate(projects[:8], 1))
    return (f"Which job is this walkthrough for?\n{opts}\n"
            "Reply with the number or street. Keep sending photos meanwhile.")


def pick_job(text: str, projects: List[Dict[str, Any]], *,
             numbered: bool = False) -> Optional[dict]:
    """The job a reply names: "588", "588... Same walkthrough", "Thomas",
    or (numbered) the option's number. None when it names none or several."""
    t = str(text or "").strip()
    if numbered:
        m = re.fullmatch(r"#?\s*(\d)\s*[.)]?", t)
        if m and 1 <= int(m.group(1)) <= min(len(projects), 8):
            return projects[int(m.group(1)) - 1]
    p, _ = match_project(t, projects) if t else (None, "")
    if p:
        return p
    hits = []
    for tok in re.findall(r"[A-Za-z0-9]+", t):
        if len(tok) < 3 and not tok.isdigit():
            continue
        q, _ = match_project(tok, projects)
        if q and q not in hits:
            hits.append(q)
    return hits[0] if len(hits) == 1 else None


def short_message_id(mid: Any) -> str:
    """WhatsApp's own id of a message ("3EB0…"), from WaAPI's serialized
    "false_1718…@c.us_3EB0…" or as is."""
    m = str(mid or "").strip()
    return m.rsplit("_", 1)[-1] if "_" in m else m


def item_for_reply(items: List[dict], quoted_id: Any, quoted_body: Any = "") -> Optional[dict]:
    """The item whose photo (or words) a reply quotes: by the message id,
    else by the quoted caption when exactly one item has those words."""
    live = [it for it in items if it.get("status", "draft") != "dropped"]
    q = short_message_id(quoted_id)
    if q:
        for it in live:
            # Its photo, a photo merged into it, or a message that gave it its
            # words (a reply to "Time wrong" is about the tile photo).
            ids = [it.get("message_id")] + list(it.get("merged") or []) + list(it.get("caption_ids") or [])
            if any(short_message_id(x) == q for x in ids if x):
                return it
    body = " ".join(str(quoted_body or "").split()).lower()
    if body:
        hits = [it for it in live if " ".join(str(it.get("text") or "").split()).lower() == body]
        if len(hits) == 1:
            return hits[0]
    return None


# ── EVERY PHOTO IS ON THE LIST ──────────────────────────────────────────────

_ADD_PHOTO = re.compile(r"^\s*add\s+(?:the\s+)?photo\s*#?\s*(\d{1,3})\s*[:\-–]?\s*(.*)$",
                        re.IGNORECASE | re.DOTALL)


def add_photo_ref(text: str) -> Optional[Tuple[int, str]]:
    """"add photo 3: tile cracked 4F" -> (3, "tile cracked 4F")."""
    m = _ADD_PHOTO.match(str(text or ""))
    return (int(m.group(1)), m.group(2).strip()) if m else None


def orphan_photos(sess: Dict[str, Any]) -> List[Tuple[int, dict]]:
    """(its number in the order photos came, the photo) for every photo of the
    walk that is on no item (live, dropped or merged items all count)."""
    on_items = set()
    for it in sess.get("items") or []:
        for x in [it.get("message_id"), *(it.get("merged") or [])]:
            if x:
                on_items.add(short_message_id(x))
        for k in [it.get("photo_key"), *(it.get("extra_photos") or [])]:
            if k:
                on_items.add(k)
    out = []
    for i, ph in enumerate(sess.get("photos") or [], 1):
        if short_message_id(ph.get("message_id")) not in on_items \
                and (not ph.get("key") or ph.get("key") not in on_items):
            out.append((i, ph))
    return out


def orphan_text(orphans: List[Tuple[int, dict]], fmt_time) -> str:
    lines = [f"Photo at {fmt_time(ph.get('at'))} isn't on the list. Add it? "
             f"(reply: add photo {i}: description)" for i, ph in orphans]
    return "\n".join(lines + ["Or 'done' again to go on without it."])


_TARGET = re.compile(r"^\s*#\s*(\d{1,3})\s*[:\-.,]?\s*(.*)$|^\s*(\d{1,3})\s*[:\-]\s*(.+)$", re.DOTALL)


def target_ref(text: str) -> Optional[Tuple[int, str]]:
    """"#2 4th floor Apt 4F" / "2: lobby" -> (2, the rest)."""
    m = _TARGET.match(str(text or ""))
    if not m:
        return None
    n = m.group(1) or m.group(3)
    rest = (m.group(2) if m.group(1) else m.group(4)) or ""
    return int(n), rest.strip()


def update_item(it: dict, words: str, *, note_at: Any = None) -> str:
    """Words said ABOUT an item (a reply to its photo, "#2 …", a note):
    its location and trade when they name them; its caption when it has
    none; else a note on it. Returns what changed: location|trade|caption|note."""
    w = str(words or "").strip()
    if not w:
        return ""
    loc = read_location(w)
    changed = []
    if merge_location(it, loc):
        changed.append("location")
    tr = read_trade(w)
    if tr and ((it.get("trade") or UNKNOWN) == UNKNOWN or it.get("trade_guess")) and it.get("text"):
        # Words about the item that name a trade ("electrician"): that trade.
        it["trade"], it["trade_guess"] = tr, False
        changed.append("trade")
    rest = w
    if loc.get("floor") or loc.get("area"):
        # Only a location ("2nd floor Apt 2D"): nothing else to keep.
        rest = re.sub(r"(?i)\b(?:the\s+)?(?:\d{1,3}(?:st|nd|rd|th)?\s*(?:floor|fl\.?)|"
                      r"(?:floor|fl\.?|piso|apt\.?|apto|apartment|unit)\s*#?\s*\w+|\d{1,2}[a-z])\b",
                      " ", rest)
        rest = re.sub(r"[\s,.;:-]+", " ", rest).strip()
        if read_location(rest)["area"] == loc.get("area"):
            rest = re.sub(r"(?i)\b" + re.escape(str(loc.get("area") or "")) + r"\b", " ", rest).strip()
    if not it.get("text"):
        it["text"] = clean_caption(w) if loc.get("floor") or loc.get("area") else w
        if (it.get("trade") or UNKNOWN) == UNKNOWN or it.get("trade_guess"):
            it["trade"], it["trade_guess"] = trade_for(w)
        changed.append("caption")
    elif len(rest) > 3 if "location" in changed else bool(rest):
        # Words beyond the location ("2D, and the hinge is loose"): kept.
        it.setdefault("notes", []).append({"text": w, "at": note_at})
        changed.append("note")
    return "+".join(changed)


# ── A CAPTION CORRECTED ──────────────────────────────────────────────────────
#
# 8:31 PM: "Time wrong" (for "Tile wrong"), then "I meant tile" in reply to
# it. That is the caption, fixed -- never a trade or a note on another item.

_CORRECTION = re.compile(
    r"^\s*(?:(?:no,?\s*)?i\s+mean(?:t)?|meant|should\s+(?:be|say|read)|(?:it\s+)?should've\s+been"
    r"|(?:sorry,?\s*)?typo[:,.!]*\s*(?:(?:it\s+)?should\s+be|i\s+meant|it'?s)?|correction[:,]?"
    r"|quise\s+decir|ich\s+mein(?:te)?)\s*[:,-]?\s*(?P<x>.+?)\s*[.!]*\s*$"
    r"|^\s*\*\s*(?P<y>\S.*?)\s*$", re.IGNORECASE)


def correction(text: str) -> Optional[str]:
    """The corrected words of "I meant tile", "should be tile", "typo: tile",
    "*tile" (None when it is not a correction). A bare "typo" is "" (which
    word is not said)."""
    t = str(text or "").strip()
    if re.fullmatch(r"(?i)(?:sorry,?\s*)?typo[.!]*", t):
        return ""
    m = _CORRECTION.match(t)
    if not m:
        return None
    x = (m.group("x") or m.group("y") or "").strip().strip("\"'“”")
    return x or None


def _edits(a: str, b: str) -> int:
    a, b = a.lower(), b.lower()
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def apply_correction(caption: str, fix: str) -> str:
    """"Time wrong" + "tile" -> "Tile wrong": one word replaces the caption's
    closest word (a typo is a word or two letters off); more words, or no
    close word, replace the caption."""
    cap, fix = str(caption or "").strip(), str(fix or "").strip()
    words = cap.split()
    if fix and len(fix.split()) == 1 and words:
        dist = [(_edits(re.sub(r"\W", "", w), fix), i) for i, w in enumerate(words)]
        d, i = min(dist)
        if d <= max(2, len(fix) // 2) and d > 0:
            old = words[i]
            new = fix if not old[:1].isupper() else fix[:1].upper() + fix[1:]
            words[i] = re.sub(r"^\W*\w+", new, old) if re.match(r"^\W*\w", old) else new
            return " ".join(words)
    return capitalize(fix) if fix else cap


def capitalize(text: str) -> str:
    t = str(text or "").strip()
    return t[:1].upper() + t[1:] if t else t


def clean_caption(words: str) -> str:
    """An item's words with the location taken out ("tile cracked 4F" ->
    "Tile cracked": the location is its own field), first letter capital.
    A named area is taken out only at the end ("roof drain clogged" keeps
    its roof)."""
    t = str(words or "")
    for rx in (_LOC_UNIT, _LOC_FLOOR):
        t = rx.sub(" ", t)
    t = re.sub(r"(?<![\w#/.-])\d{1,2}\s?[a-z](?![\w/])", " ", t, flags=re.IGNORECASE)
    tail = re.compile(r"(?:\s+(?:in|at|on|by|en|del|de|al)?\s*(?:the\s+|el\s+|la\s+|los\s+|las\s+)?(?:" + "|".join(
        rx for _, rx in _COMMON + _NEEDS_FLOOR) + r"|stair\s*(?:well|case)?\s+[ab]))\s*$", re.IGNORECASE)
    t = tail.sub("", t)
    t = re.sub(r"\s*[,;:-]+\s*$", "", re.sub(r"\s+", " ", t)).strip(" ,;:-")
    return capitalize(t) if t else capitalize(str(words or ""))


def job_code(project: Dict[str, Any]) -> str:
    """The job's short code for ids: its own code, else the street number of
    its name or address ("588 Thomas St" -> "588"), else 4 id characters."""
    for k in ("job_code", "job_number", "code"):
        v = str(project.get(k) or "").strip()
        if v and re.fullmatch(r"[A-Za-z0-9-]{1,12}", v):
            return v.upper()
    for k in ("name", "address"):
        m = re.match(r"\s*(\d{1,6}[A-Za-z]?)\b", str(project.get(k) or ""))
        if m:
            return m.group(1).upper()
    return re.sub(r"[^A-Za-z0-9]", "", str(project.get("_id") or project.get("id") or "JOB"))[-4:].upper()


def punch_id(code: str, seq: int) -> str:
    return f"P-{code}-{seq}"


_PID = re.compile(r"\bP-?(?:(?P<code>[A-Za-z0-9]{1,12})-)?(?P<seq>\d{1,5})\b", re.IGNORECASE)


def parse_pid(text: str, default_code: Optional[str] = None) -> Optional[Tuple[Optional[str], int]]:
    """"P23" / "P-588-23" -> (code or default, 23)."""
    m = _PID.search(str(text or ""))
    if not m:
        return None
    return ((m.group("code") or default_code or None), int(m.group("seq")))


# ── WHAT A CAPTION SAYS ──────────────────────────────────────────────────────
#
# Floor, area and trade read from the words themselves, in English and
# Spanish (Yiddish crews mostly name trades in English). Nothing guessed: an
# item whose words name no trade is "?" until the walker says.

_TRADES = [
    ("electrical", r"electric\w*|outlets?|receptacles?|switch(?:es)?|light(?:s|ing)?|fixtures?|panel|breakers?|wiring|el[eé]ctric\w*|enchufes?|luz|luces|cables?"),
    ("plumbing", r"plumb\w*|pipes?|leak\w*|faucets?|toilets?|sinks?|drains?|valves?|plomer\w*|tuber[ií]a|fuga|lavamanos|inodoro|grifo"),
    ("hvac", r"hvac|duct\w*|diffusers?|grilles?|thermostats?|vav|rtu|mechanical|a/?c\b|aire acondicionado|ductos?"),
    ("drywall", r"drywall|sheetrock|gyp\w*|tape|taping|spackle|plaster|yeso|tablaroca|paneles? de yeso"),
    ("paint", r"paint\w*|touch[- ]?up|primer|pintur\w*|pintor\w*|retoque"),
    ("carpentry", r"carpent\w*|trim|base ?board|casing|millwork|cabinets?|shel(?:f|ves)|carpinter\w*|gabinetes?|z[oó]calo"),
    ("doors", r"doors?|hardware|hinges?|closers?|locks?|puertas?|bisagras?|cerraduras?"),
    ("flooring", r"floor(?:ing)?\s+(?:tile|finish)|flooring|carpet|lvt|vct|laminate|baldosa|alfombra"),
    ("tile", r"\btile|grout|backsplash|azulejos?|lechada"),
    ("glazing", r"windows?|glass|glazing|storefront|ventanas?|vidrios?"),
    ("fire protection", r"sprinkler\w*|fire alarm|smoke detector|rociadores?|alarma de incendio"),
    ("masonry", r"mason\w*|brick\w*|block|cmu|pointing|ladrillos?|bloques?"),
    ("roofing", r"roof\w*|flashing|techo|impermeabiliz\w*"),
    ("concrete", r"concrete|slab|curb|sidewalk|concreto|hormig[oó]n|losa"),
    ("elevator", r"elevator|ascensor|elevador"),
    ("cleaning", r"clean\w*|debris|garbage|limpi\w*|basura|escombros?"),
]
_TRADES_RX = [(t, re.compile(r"(?<!\w)(?:" + p + r")(?!\w)", re.IGNORECASE)) for t, p in _TRADES]
TRADES = tuple(t for t, _ in _TRADES)
_TRADE_ALIASES = {
    "electric": "electrical", "electrician": "electrical", "elec": "electrical",
    "electricista": "electrical", "plumber": "plumbing", "plomero": "plumbing",
    "plomeria": "plumbing", "mech": "hvac", "mechanical": "hvac", "a/c": "hvac",
    "sheetrock": "drywall", "taper": "drywall", "painter": "paint", "painting": "paint",
    "pintura": "paint", "pintor": "paint", "carpenter": "carpentry", "carpintero": "carpentry",
    "door": "doors", "hardware": "doors", "floors": "flooring", "tiles": "tile",
    "windows": "glazing", "window": "glazing", "sprinkler": "fire protection",
    "sprinklers": "fire protection", "fire": "fire protection", "mason": "masonry",
    "roof": "roofing", "roofer": "roofing", "cleanup": "cleaning", "clean": "cleaning",
    "limpieza": "cleaning",
}

_FLOOR = re.compile(
    r"(?<!\w)(?:(?:floor|fl\.?|level|lvl|piso|planta)\s*#?\s*(?P<a>\d{1,3}|[a-z]{1,2})"
    r"|(?P<b>\d{1,3})(?:st|nd|rd|th)?\s*(?:floor|fl\.?)"
    r"|(?P<c>cellar|basement|roof|bulkhead|lobby|ground|s[oó]tano|azotea|techo))(?!\w)",
    re.IGNORECASE)
_AREA = re.compile(
    r"(?<!\w)(?:(?:apt|apartment|unit|apto|depto)\.?\s*#?\s*(?P<u>[0-9]{1,4}[a-z]?|[a-z]{1,2}\d{0,3})"
    r"|(?P<room>kitchen|bath(?:room)?|bedroom|hallway|corridor|stair(?:well|s)?|lobby|mech(?:anical)? room"
    r"|cocina|ba[ñn]o|pasillo|escalera|habitaci[oó]n|dormitorio))(?!\w)", re.IGNORECASE)


#: A trade GUESSED from what a caption is about (shown "electrical?", the
#: walker overrides it): checked when the words name no trade outright.
_GUESS = [
    ("electrical", r"bulbs?|lamps?|outlets?|switch(?:es)?|fixtures?|receptacles?|sockets?|bombillos?|focos?"),
    ("tile", r"tiles?|grout|backsplash"),
    ("carpentry", r"tables?|cabinets?|doors?|trim|counters?|shel(?:f|ves)|drawers?|base ?boards?|mesas?"),
    ("paint", r"paint\w*|touch[- ]?ups?|scuffs?|marks?"),
    ("plumbing", r"leak\w*|faucets?|drips?|toilets?|sinks?|showers?"),
    ("drywall", r"sheetrock|patch(?:es|ing)?|holes?|cracks? in (?:the )?wall|nail pops?"),
]
_GUESS_RX = [(t, re.compile(r"(?<!\w)(?:" + p + r")(?!\w)", re.IGNORECASE)) for t, p in _GUESS]


def guess_trade(text: str) -> Optional[str]:
    """The one trade what the words are ABOUT suggests (a bulb: electrical; a
    table: carpentry), or None."""
    hits = {t for t, rx in _GUESS_RX if rx.search(str(text or ""))}
    return hits.pop() if len(hits) == 1 else None


def trade_for(text: str) -> Tuple[str, bool]:
    """(trade, guessed) for an item's words: every trade read from a caption
    is a guess the walker can override ("electrical?"); UNKNOWN when none."""
    t = read_trade(text) or guess_trade(text)
    return (t, True) if t else (UNKNOWN, False)


def read_trade(text: str) -> Optional[str]:
    """The one trade the words name, or None (none, or two different)."""
    hits = {t for t, rx in _TRADES_RX if rx.search(str(text or ""))}
    if len(hits) == 1:
        return hits.pop()
    # "outlet in the bathroom ceiling paint": more than one -> the walker says.
    return None


def trade_word(word: str) -> Optional[str]:
    """What the walker typed as a trade ("electrical", "elec", "plomero")."""
    w = multilang.fold(word).strip().rstrip(".")
    if w in TRADES:
        return w
    if w in _TRADE_ALIASES:
        return _TRADE_ALIASES[w]
    return read_trade(w)


def read_floor(text: str) -> Optional[str]:
    m = _FLOOR.search(str(text or ""))
    if not m:
        return None
    v = (m.group("a") or m.group("b") or m.group("c") or "").lower()
    return {"sotano": "cellar", "sótano": "cellar", "azotea": "roof", "techo": "roof",
            "basement": "cellar"}.get(v, v)


def read_area(text: str) -> Optional[str]:
    m = _AREA.search(str(text or ""))
    if not m:
        return None
    if m.group("u"):
        return f"Apt {m.group('u').upper()}"
    room = multilang.fold(m.group("room"))
    return {"cocina": "kitchen", "bano": "bathroom", "bath": "bathroom", "pasillo": "hallway",
            "escalera": "stairs", "habitacion": "bedroom", "dormitorio": "bedroom"}.get(
        room, room)


# ── WHERE AN ITEM IS (required) ──────────────────────────────────────────────
#
# Every punch item needs a location before the draft (588, Oct 11: "Missing
# screw by table" with none). A location is
#   - a floor and a unit: "4th floor Apt 4F", "4F", "fl 4 unit F",
#     "piso 4 apto F" (a unit whose number starts with its floor -- "4F",
#     "12C" -- carries the floor);
#   - a named common area that needs no floor: lobby, elevator machine room,
#     meter room, boiler room, roof, bulkhead, cellar, basement, compactor
#     room, stairwell A/B, mail room, gym, laundry room, bike room, trash
#     room, parking, courtyard, facade, sidewalk;
#   - a corridor / hallway / stairs / landing WITH its floor.
# A room inside an apartment (kitchen, bathroom) or a floor alone is not one.

#: Named areas that need no floor, as said (EN / ES / YI) -> the label.
_COMMON = [
    ("elevator machine room", r"elevator\s+(?:machine\s+)?room|machine\s+room|elevator\s+motor\s+room"
                              r"|cuarto\s+de\s+m[aá]quinas"),
    ("meter room", r"(?:water\s+)?meter\s+room|water\s+main(?:\s+room)?|cuarto\s+de\s+medidores"),
    ("boiler room", r"boiler(?:\s+room)?|cuarto\s+de\s+(?:la\s+)?calderas?|caldera|kesel\s+tsimer"),
    ("compactor room", r"compactor(?:\s+room)?"),
    ("mail room", r"mail\s*room|cuarto\s+de\s+correo|buzones"),
    ("laundry room", r"laundry(?:\s+room)?|lavander[ií]a"),
    ("bike room", r"bike\s+room|bicycle\s+room"),
    ("trash room", r"trash\s+room|garbage\s+room|refuse\s+room|cuarto\s+de\s+basura"),
    ("gym", r"gym|gimnasio|fitness\s+(?:room|center)"),
    ("parking", r"parking(?:\s+(?:lot|garage|level))?|garage|estacionamiento"),
    ("courtyard", r"court\s*yard|back\s*yard|rear\s+yard|patio"),
    ("facade", r"fa[cç]ade|exterior|outside\s+wall|fachada"),
    ("sidewalk", r"sidewalk|acera|banqueta"),
    ("bulkhead", r"bulkhead"),
    ("roof", r"roof(?:top)?|azotea|techo|dach"),
    ("cellar", r"cellar|s[oó]tano|keller|keler"),
    ("basement", r"basement"),
    ("lobby", r"lobby|vest[ií]bulo|loby|entrance\s+hall|entrada"),
]
_COMMON_RX = [(label, re.compile(r"(?<!\w)(?:" + rx + r")(?!\w)", re.IGNORECASE)) for label, rx in _COMMON]
#: A named stairwell ("stairwell A", "stair B", "escalera A"): no floor needed.
_STAIRWELL = re.compile(r"(?<!\w)(?:stair\s*(?:well|case|way)?|stairs|escalera)\s+([ab])(?!\w)", re.IGNORECASE)
#: These need their floor.
_NEEDS_FLOOR = [
    ("corridor", r"corridor|korridor"),
    ("hallway", r"hallway|hall|pasillo"),
    ("stairs landing", r"(?:stairs?\s+)?landing|descanso"),
    ("stairs", r"stair\s*(?:well|case|way)?|stairs|escaleras?|trep"),
]
_NEEDS_FLOOR_RX = [(label, re.compile(r"(?<!\w)(?:" + rx + r")(?!\w)", re.IGNORECASE))
                   for label, rx in _NEEDS_FLOOR]
COMMON_AREAS = tuple(label for label, _ in _COMMON) + ("stairwell A", "stairwell B")
NEEDS_FLOOR = tuple(label for label, _ in _NEEDS_FLOOR)

_LOC_FLOOR = re.compile(
    r"(?<!\w)(?:(?:floor|fl\.?|level|lvl|piso|planta|shtok|shtock)\s*#?\s*(?P<a>\d{1,3})"
    r"|(?P<b>\d{1,3})\s*(?:st|nd|rd|th|er|ter|te)?\s*(?:floor|fl\.?|shtok|shtock|piso))(?!\w)",
    re.IGNORECASE)
_LOC_UNIT = re.compile(
    r"(?<!\w)(?:apartamento|apartment|apto|apt|unit|departamento|depto|dira)(?:\.\s*|\s+|#\s*)#?\s*"
    r"(?P<u>\d{1,3}\s?[a-z]?|[a-z]{1,2}\d{0,3})(?!\w)", re.IGNORECASE)
#: A bare unit: "2D", "4F", "12C" (its floor is its number). Not "2nd", "4x4".
_BARE_UNIT = re.compile(r"(?<![\w#/.-])(?P<f>\d{1,2})\s?(?P<l>[a-z])(?![\w/])", re.IGNORECASE)


def read_location(text: str) -> Dict[str, Optional[str]]:
    """{"floor": "4" | "cellar" | None, "area": "Apt 4F" | "lobby" |
    "corridor" | None} from words in English, Spanish or Yiddish."""
    t = str(text or "")
    floor = area = None
    m = _LOC_FLOOR.search(t)
    if m:
        floor = (m.group("a") or m.group("b")).lstrip("0") or "0"
    u = _LOC_UNIT.search(t)
    if u:
        unit = re.sub(r"\s+", "", u.group("u")).upper()
        if not floor:
            fm = re.match(r"(\d{1,2})[A-Z]$", unit)
            floor = fm.group(1) if fm else None
        if floor and re.fullmatch(r"[A-Z]", unit):
            unit = f"{floor}{unit}"                     # "fl 4 unit F" -> Apt 4F
        area = f"Apt {unit}"
    if not area:
        b = _BARE_UNIT.search(re.sub(r"(?<!\w)(?:floor|fl\.?|piso)\s*\d+", " ", t, flags=re.I))
        if b and not re.match(r"(?:st|nd|rd|th)\b", t[b.end("l") - 1:b.end("l") + 1].lower()):
            unit_floor = b.group("f").lstrip("0") or "0"
            if not floor or floor == unit_floor:
                floor, area = unit_floor, f"Apt {unit_floor}{b.group('l').upper()}"
    if not area:
        sw = _STAIRWELL.search(t)
        if sw:
            area = f"stairwell {sw.group(1).upper()}"
    if not area:
        for label, rx in _COMMON_RX:
            if rx.search(t):
                area = label
                break
    if not area:
        for label, rx in _NEEDS_FLOOR_RX:
            if rx.search(t):
                area = label
                break
    if not area:
        room = read_area(t)          # a room in an apartment: kept, not enough
        if room and not room.startswith("Apt "):
            area = room
    return {"floor": floor, "area": area}


def location_state(floor: Optional[str], area: Optional[str]) -> str:
    """"ok", "needs_floor" (a corridor with no floor), or "missing"."""
    f = None if floor in (None, "", UNKNOWN) else str(floor)
    a = None if area in (None, "", UNKNOWN) else str(area)
    if a and a.startswith("Apt "):
        return "ok" if f else "needs_floor"
    if a and a in COMMON_AREAS:
        return "ok"
    if f and f in ("cellar", "basement", "roof", "bulkhead", "lobby"):
        return "ok"                              # an old item's named floor
    if a and a in NEEDS_FLOOR:
        return "ok" if f and f.isdigit() else "needs_floor"
    return "missing"


def merge_location(it: dict, loc: Dict[str, Optional[str]]) -> bool:
    """Set what `loc` names on the item (in place). True when it named any."""
    named = False
    if loc.get("floor"):
        it["floor"], named = loc["floor"], True
    if loc.get("area"):
        it["area"], named = loc["area"], True
    common = it.get("area") in COMMON_AREAS
    if common and not loc.get("floor") and loc.get("area"):
        it["floor"] = UNKNOWN if it.get("area") not in ("cellar", "basement", "roof",
                                                         "bulkhead", "lobby") else it["area"]
    return named


def location_ok(it: dict) -> bool:
    return location_state(it.get("floor"), it.get("area")) == "ok"


def location_label(it: dict) -> str:
    """"Floor 4 · Apt 4F", "Lobby", "Floor 3 · corridor" (or "")."""
    f, a = it.get("floor") or UNKNOWN, it.get("area") or UNKNOWN
    parts = []
    if f != UNKNOWN and f != a:
        parts.append(floor_label(f))
    if a != UNKNOWN:
        parts.append(a if parts else a[:1].upper() + a[1:])
    return " · ".join(parts)


def where_question(it: dict) -> str:
    """The one question for an item with no (complete) location."""
    words = (it.get("text") or "").strip() or "(no words)"
    if len(words) > 60:
        words = words[:57].rstrip() + "…"
    n = it.get("n")
    if location_state(it.get("floor"), it.get("area")) == "needs_floor":
        return f"Which floor is #{n} '{words}' ({it.get('area')}) on?"
    f = it.get("floor") or UNKNOWN
    if f != UNKNOWN and str(f).isdigit():
        return f"Where on floor {f} is #{n} '{words}'? (the unit, or a named area)"
    return f"Where is #{n} '{words}'? (floor + unit, or a named area)"


def missing_location(items: List[dict]) -> List[dict]:
    """The live items with no complete location, in the order they came in."""
    return sorted((it for it in items if it.get("status", "draft") != "dropped"
                   and not location_ok(it)), key=lambda it: it.get("captured") or 0)


def new_item(n: int, words: str, *, photo_key: Optional[str], message_id: str,
             voice: Optional[dict] = None, at: Any = None) -> Dict[str, Any]:
    """One captured item: the photo, its words as written or said, and what
    the words name (or "?"). A caption that STARTS with its location ("4d
    tile chipped", 10:36 PM) is the location (Apt 4D) and the rest ("Tile
    chipped"); the words as sent are kept in `said`."""
    w = str(words or "").strip()
    loc = _loc(w)
    # The location is its own field: taken out of the words wherever it is
    # ("4d tile chipped", "tile chipped 4d" -> "Tile chipped"), as "add:".
    text = clean_caption(w) if (loc["floor"] or loc["area"]) and w else w
    return {
        "n": n,
        "text": text,
        **({"said": w} if text != w else {}),
        "photo_key": photo_key,
        "message_id": message_id,
        "voice": voice or None,
        "captured": n,                  # the order it came in; `n` follows the draft
        "floor": _loc(w)["floor"] or UNKNOWN,
        "area": _loc(w)["area"] or UNKNOWN,
        "trade": trade_for(w)[0],
        "trade_guess": trade_for(w)[1],
        "at": at,
    }


def added_text(it: dict) -> str:
    """"Added #4 'Tile chipped' (Apt 4D)." -- a photo sent after the walk's
    capture, put on the walk."""
    words = (it.get("text") or "").strip()
    if len(words) > 60:
        words = words[:57].rstrip() + "…"
    a = it.get("area") or UNKNOWN
    where = a if a != UNKNOWN and re.match(r"(?i)apt\b", a) else location_label(it)
    return (f"Added #{it.get('n')}" + (f" '{words}'" if words else " (photo)")
            + (f" ({where})" if where else "") + ".")


def _loc(words: str) -> Dict[str, Optional[str]]:
    loc = read_location(words)
    if not loc["floor"]:
        # A named floor ("lobby", "roof", "cellar") read the old way.
        f = read_floor(words)
        if f and not f.isdigit():
            loc["floor"] = f
    return loc


# ── THE DRAFT ────────────────────────────────────────────────────────────────

def _floor_key(f: str) -> Tuple[int, str]:
    order = {"cellar": -2, "basement": -2, "lobby": 0, "ground": 0, "roof": 999, "bulkhead": 1000}
    if f == UNKNOWN:
        return (2000, "")
    if f.isdigit():
        return (int(f), "")
    return (order.get(f, 500), f)


def floor_label(f: str) -> str:
    if f == UNKNOWN:
        return "Floor ?"
    if f.isdigit():
        return f"Floor {f}"
    return f.capitalize()


def ordered(items: Iterable[dict]) -> List[dict]:
    """The draft's order -- the numbers follow it: floor, then trade ("?"
    last), then the order the photos came in."""
    def key(it):
        t = it.get("trade") or UNKNOWN
        return (_floor_key(it.get("floor") or UNKNOWN), t == UNKNOWN, t,
                it.get("captured") or 0)
    return sorted(items, key=key)


def marker(it: dict) -> str:
    m = []
    if it.get("photo_key"):
        m.append("📷")
    if it.get("voice"):
        m.append("🎤")
    return "".join(m)


def item_line(it: dict) -> str:
    """"3. 📷 Outlet cover missing — electrical" (area shown when known)."""
    words = it.get("text") or "(no words)"
    trade = it.get("trade") or UNKNOWN
    if trade != UNKNOWN and it.get("trade_guess"):
        trade += "?"                       # a guess from the caption: say if wrong
    area = it.get("area")
    where = f" ({area})" if area and area != UNKNOWN and area != it.get("floor") else ""
    return f"{it['n']}. {marker(it)} {words}{where} — {trade}".replace("  ", " ")


def draft_text(job_name: str, items: List[dict], sent_mode: str = DEFAULT_SEND_MODE) -> str:
    """The draft the walker sees: by floor, then trade, each with ITS number
    -- never renumbered once shown, so they may read #1, #4, #2."""
    live = [it for it in items if it.get("status", "draft") != "dropped"]
    need_trade = [it for it in live if (it.get("trade") or UNKNOWN) == UNKNOWN]
    head = f"{job_name} · walkthrough · {len(live)} item{'s' if len(live) != 1 else ''} (draft)"
    lines = [head]
    by_floor: Dict[str, List[dict]] = {}
    for it in ordered(live):
        by_floor.setdefault(it.get("floor") or UNKNOWN, []).append(it)
    for f in sorted(by_floor, key=_floor_key):
        lines.append("")
        lines.append(f"*{floor_label(f)}*")
        by_trade: Dict[str, List[dict]] = {}
        for it in by_floor[f]:
            by_trade.setdefault(it.get("trade") or UNKNOWN, []).append(it)
        for t in sorted(by_trade, key=lambda x: (x == UNKNOWN, x)):
            lines.append(f"_{t if t != UNKNOWN else 'trade ?'}_")
            lines.extend(item_line(it) for it in by_trade[t])
    lines.append("")
    if need_trade:
        nums = ", ".join(str(it["n"]) for it in need_trade)
        lines.append(f"{len(need_trade)} need{'s' if len(need_trade) == 1 else ''} a trade ({nums}).")
    lines.append("Reply to fix (\"2 → electrical\", \"drop 6\", \"merge 4 and 5\", "
                 "\"add: …\", \"move 3 to floor 6\"), or 'send'.")
    return "\n".join(lines)


# ── EDITS ────────────────────────────────────────────────────────────────────

_ARROW = r"(?:→|->|=>|>|to|:|=)"
_EDITS = [
    ("trade", re.compile(r"^\s*#?(\d{1,3})\s*" + _ARROW + r"?\s*(?:trade\s+)?([a-z/ áéíóúñ]+?)\s*$", re.IGNORECASE)),
    ("drop", re.compile(r"^\s*(?:drop|delete|remove|borra|quita|elimina)\s+#?(\d{1,3})\s*$", re.IGNORECASE)),
    ("merge", re.compile(r"^\s*(?:merge|combine|junta|une)\s+#?(\d{1,3})\s*(?:and|&|,|y|\+)\s*#?(\d{1,3})\s*$", re.IGNORECASE)),
    ("add", re.compile(r"^\s*(?:add|agrega|añade)\s*[:\-]\s*(.+)$", re.IGNORECASE | re.DOTALL)),
    ("floor", re.compile(r"^\s*(?:move|mueve|pasa)\s+#?(\d{1,3})\s+(?:to|a|al)\s+(?:floor|fl\.?|piso)\s*(\w{1,8})\s*$", re.IGNORECASE)),
    ("area", re.compile(r"^\s*#?(\d{1,3})\s+(?:is\s+)?in\s+(.+?)\s*$", re.IGNORECASE)),
]


def parse_edit(text: str) -> Optional[Dict[str, Any]]:
    """One edit per line: {"op": trade|drop|merge|add|floor|area, ...}, or
    None when the line is not an edit."""
    t = str(text or "").strip()
    for op, rx in _EDITS:
        m = rx.match(t)
        if not m:
            continue
        if op == "trade":
            trade = trade_word(m.group(2))
            if not trade:
                continue
            return {"op": "trade", "n": int(m.group(1)), "trade": trade}
        if op == "drop":
            return {"op": "drop", "n": int(m.group(1))}
        if op == "merge":
            a, b = int(m.group(1)), int(m.group(2))
            return None if a == b else {"op": "merge", "a": min(a, b), "b": max(a, b)}
        if op == "add":
            return {"op": "add", "text": m.group(1).strip()}
        if op == "floor":
            f = m.group(2).lower()
            return {"op": "floor", "n": int(m.group(1)), "floor": read_floor(f"floor {f}") or f}
        if op == "area":
            return {"op": "area", "n": int(m.group(1)), "area": read_area(m.group(2)) or m.group(2).strip()}
    return None


def parse_edits(text: str) -> List[Dict[str, Any]]:
    """Every line of a message that is an edit ("2 → electrical\\ndrop 6")."""
    return [e for e in (parse_edit(line) for line in re.split(r"[\n;]+", str(text or ""))) if e]


def apply_edit(items: List[dict], e: Dict[str, Any], *, next_n: int) -> Tuple[bool, str]:
    """Apply one edit to the draft's items (in place). (done, note)."""
    by_n = {it["n"]: it for it in items if it.get("status", "draft") != "dropped"}
    if e["op"] == "add":
        cap = max([it.get("captured") or 0 for it in items] or [0]) + 1
        it = new_item(next_n, e["text"], photo_key=None, message_id="")
        it["text"] = clean_caption(e["text"])            # "Tile cracked", Apt 4F its own field
        items.append({**it, "captured": cap, "added": True})
        return True, f"added {next_n}"
    if e["op"] == "merge":
        a, b = by_n.get(e["a"]), by_n.get(e["b"])
        if not a or not b:
            return False, f"no item {e['a'] if not a else e['b']}"
        a["text"] = f"{a.get('text') or ''} / {b.get('text') or ''}".strip(" /")
        a["merged"] = list(a.get("merged") or []) + [b.get("message_id") or ""]
        a["extra_photos"] = list(a.get("extra_photos") or []) + [k for k in [b.get("photo_key")] if k]
        for k in ("floor", "area", "trade"):
            if (a.get(k) or UNKNOWN) == UNKNOWN and (b.get(k) or UNKNOWN) != UNKNOWN:
                a[k] = b[k]
        b["status"] = "dropped"
        return True, f"merged {e['b']} into {e['a']}"
    it = by_n.get(e["n"])
    if not it:
        return False, f"no item {e['n']}"
    if e["op"] == "trade":
        it["trade"], it["trade_guess"] = e["trade"], False
    elif e["op"] == "drop":
        it["status"] = "dropped"
    elif e["op"] == "floor":
        it["floor"] = e["floor"]
    elif e["op"] == "area":
        it["area"] = e["area"]
    return True, f"{e['op']} {e['n']}"


# ── ASSIGNING ────────────────────────────────────────────────────────────────

def assign_text(sugg: Dict[str, Optional[dict]]) -> str:
    lines = ["Who gets what?"]
    for t, p in sorted(sugg.items()):
        lines.append(f"• {t} → {who_label(p)}")
    lines.append("Reply 'ok', or fix one: \"electrical → Mike\".")
    return "\n".join(lines)


_ASSIGN = re.compile(r"^\s*([a-z /áéíóúñ]+?)\s*(?:→|->|=>|>|:|=|to)\s*(.+?)\s*$", re.IGNORECASE)


def parse_assign(text: str) -> List[Tuple[str, str]]:
    """["electrical → Mike", …] -> [(trade, name)]."""
    out = []
    for line in re.split(r"[\n;,]+", str(text or "")):
        m = _ASSIGN.match(line)
        if m:
            t = trade_word(m.group(1))
            if t:
                out.append((t, m.group(2)))
    return out


_ALL = re.compile(
    r"^\s*(?:send\s+)?(?:all|everything|the\s+whole\s+(?:list|thing)|whole\s+list|all\s+of\s+(?:it|them)"
    r"|the\s+(?:whole\s+)?list|todo|todos)\s*(?:items\s*)?(?:→|->|=>|>|:|=|to|goes\s+to|go\s+to|a|para)\s*(?P<name>.+?)\s*[.!]*\s*$",
    re.IGNORECASE)


def parse_assign_reply(text: str) -> Dict[str, Any]:
    """What an answer to "Who gets what?" says:
      {"all": name}            "all → Chris", "send all to Chris", "whole list to Chris"
      {"pairs": [(trade, name)]}  "electrical → Mike; paint → Ana"
      {"fill": name}           "Chris from gc." -- for every trade still "?"
      {"ok": True}             "ok"
      {}                       nothing that names anyone."""
    t = str(text or "").strip()
    if not t:
        return {}
    if t.lower().strip(" .!") in ("ok", "okay", "yes", "si", "sí", "yo", "dale", "👍", "good",
                                  "looks good", "correct"):
        return {"ok": True}
    m = _ALL.match(t)
    if m:
        return {"all": m.group("name")}
    pairs = parse_assign(t)
    if pairs:
        return {"pairs": pairs}
    name = re.sub(r"^\s*(?:give\s+(?:it|them|the\s+rest)\s+to|send\s+(?:it|them|the\s+rest)\s+to"
                  r"|(?:the\s+)?rest\s+(?:to|→|->)|others?\s+(?:to|→|->)|assign\s+(?:to\s+)?|to)\s+",
                  "", t, flags=re.IGNORECASE)
    if re.search(r"[a-z]", name, re.IGNORECASE) and len(name.split()) <= 6 \
            and not re.search(r"\?$", name):
        return {"fill": name}
    return {}


def split_name(said: str) -> Tuple[str, str]:
    """"Chris from gc." -> ("chris", "gc"); "Mike (Bright)" -> ("mike", "bright")."""
    t = multilang.fold(str(said or "")).strip().strip(".!,;")
    m = re.match(r"^(.*?)\s*(?:\(([^)]*)\)|\s(?:from|of|at|with|de|del)\s+(?:the\s+)?(.+))$", t)
    if m:
        return m.group(1).strip(), (m.group(2) or m.group(3) or "").strip()
    return t, ""


def _person_key(p: Dict[str, Any]) -> tuple:
    return (p.get("kind"), p.get("id") or p.get("jid") or p.get("name"))


def name_candidates(name: str, people: List[Dict[str, Any]]) -> List[dict]:
    """Everyone a name can mean: full name, first name (or its start: "Chris"
    for "Christopher"), or the company; "Chris from GC" narrows to the
    Chris whose company says so (the company's users are the GC). This
    job's people (p["on_job"]) first. Never picks: two or more is a
    question for the walker (which_text)."""
    n, co = split_name(name)
    if not n and not co:
        return []

    def name_hit(p):
        full = multilang.fold(p.get("name") or "")
        first = full.split(" ")[:1]
        return bool(n) and (n == full or [n] == first
                            or (len(n) >= 3 and any(w.startswith(n) for w in full.split())))
    hits = [p for p in people if name_hit(p)]
    if not hits and n:
        hits = [p for p in people if n == multilang.fold(p.get("company") or "")]
    if co:
        narrowed = [p for p in hits if co in multilang.fold(p.get("company") or "")
                    or (co in ("gc", "general contractor", "us", "office", "the office")
                        and p.get("kind") == "user")]
        hits = narrowed or hits
    uniq: Dict[tuple, dict] = {}
    for p in hits:
        uniq.setdefault(_person_key(p), p)
    return sorted(uniq.values(), key=lambda p: (not p.get("on_job"),
                                                multilang.fold(p.get("name") or "")))


def pick_person(name: str, people: List[Dict[str, Any]]) -> Optional[dict]:
    """The ONE person a name means, or None (none, or more than one)."""
    c = name_candidates(name, people)
    return c[0] if len(c) == 1 else None


def who_label(p: Optional[dict]) -> str:
    """"Chris Lopez (Arkon)", "Chris Lopez (Arkon, not on this job)"."""
    if not p:
        return "?"
    name = (p.get("name") or p.get("company") or "?").strip()
    co = "GC team" if p.get("kind") == "user" else (p.get("company") or "").strip()
    bits = [co] if co and co.lower() != name.lower() else []
    if p.get("not_on_job"):
        bits.append("not on this job")
    return f"{name} ({', '.join(bits)})" if bits else name


def which_text(said: str, options: List[dict]) -> str:
    """"Which Chris? 1) Chris (GC team) 2) Chris Lopez (Arkon)"."""
    first = split_name(said)[0] or str(said or "").strip()
    opts = " ".join(f"{i}) {who_label({**p, 'not_on_job': not p.get('on_job')})}"
                    for i, p in enumerate(options[:9], 1))
    return f"Which {first.title()}? {opts}\nReply with the number."


def pick_choice(text: str, options: List[dict]) -> Optional[dict]:
    """"2" (or "2)") to a which_text question."""
    m = re.fullmatch(r"\s*#?(\d)\s*[.)]?\s*", str(text or ""))
    if m and 1 <= int(m.group(1)) <= min(len(options), 9):
        return options[int(m.group(1)) - 1]
    return None


def due_date(words: str, sent_at):
    """The day a due answer names (Spanish / Yiddish read as English)."""
    from lib import wa_attention
    return wa_attention.parse_due(multilang.normalize_when(words), sent_at)




def parse_due_answer(text: str, trades: Iterable[str]) -> Optional[Dict[str, str]]:
    """"Fri" / "all Friday" -> every trade that day; "electrical Mon, paint
    Fri" -> per trade. Returns {trade: due words} or None. A day the date
    readers cannot read is not accepted. Spanish / Yiddish days read too."""
    from lib import wa_attention
    from datetime import datetime, timezone
    probe = datetime(2026, 1, 5, tzinfo=timezone.utc)
    ts = [t for t in trades if t != UNKNOWN]
    out: Dict[str, str] = {}
    for part in re.split(r"[\n;,]+", str(text or "")):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^\s*([a-z /áéíóúñ]+?)\s+(?:by\s+|para\s+el\s+|el\s+)?(.+)$", part, re.IGNORECASE)
        t = trade_word(m.group(1)) if m else None
        if t and wa_attention.parse_due(multilang.normalize_when(m.group(2)), probe):
            out[t] = m.group(2).strip()
            continue
        words = re.sub(r"^\s*(?:(?:all|everything|everyone)(?:\s+else)?|(?:the\s+)?rest|all\s+others"
                       r"|todo|todos|lo\s+dem[aá]s|el\s+resto)\s+", "", part, flags=re.IGNORECASE)
        if wa_attention.parse_due(multilang.normalize_when(words), probe):
            for t2 in ts:
                out.setdefault(t2, words)
    return out or None


# ── SENDING ──────────────────────────────────────────────────────────────────

def _where(it: dict) -> str:
    return " · ".join(x for x in (floor_label(it["floor"]) if it.get("floor") not in (None, UNKNOWN) else "",
                                  it.get("area") if it.get("area") not in (None, UNKNOWN) else "") if x)


def group_text(name: str, items: List[dict], due_words: str,
               handle: Optional[str] = None, grouped: bool = False) -> str:
    """One message per assignee: @them, their items, the due day. `handle`
    is their token from lib/wa_mention ("@15551234567" mentions them for
    real); without it, "@Name". `grouped` (the whole list to one person):
    the items under their floor, then trade."""
    lines = [f"{handle or '@' + name} punch list — due {due_words}:"]
    if grouped:
        by_floor: Dict[str, Dict[str, List[dict]]] = {}
        for it in items:
            by_floor.setdefault(it.get("floor") or UNKNOWN, {}).setdefault(
                it.get("trade") or UNKNOWN, []).append(it)
        for f in sorted(by_floor, key=_floor_key):
            lines.append(f"*{floor_label(f)}*")
            for t in sorted(by_floor[f], key=lambda x: (x == UNKNOWN, x)):
                lines.append(f"_{t}_")
                for it in by_floor[f][t]:
                    a = it.get("area")
                    lines.append(f"• {it['pid']} {it.get('text') or ''}"
                                 f"{(' (' + a + ')') if a not in (None, UNKNOWN) and a != f else ''}")
    else:
        for it in items:
            where = _where(it)
            lines.append(f"• {it['pid']} {it.get('text') or ''}{(' (' + where + ')') if where else ''}")
    lines.append("Reply \"done P23\" (a photo helps) when each one is finished.")
    return "\n".join(lines)


DEFAULT_DUE = "Fri"


def recap_text(items: List[dict], assign: Dict[str, Optional[dict]], due: Dict[str, str],
               mode: str = DEFAULT_SEND_MODE, whole: Optional[dict] = None) -> str:
    """The exact send, before it happens: who gets which numbers, and when.
    "Chris Weiss (GC team): #2, #3 · Dov Klein (Power Direct): #1" -- 'ok' sends."""
    live = ordered([it for it in items if it.get("status", "draft") != "dropped"])
    groups: Dict[str, Dict[str, Any]] = {}
    for it in live:
        p = whole or assign.get(it.get("trade") or UNKNOWN)
        k = who_label(p)
        groups.setdefault(k, {"nums": [], "dues": set()})
        groups[k]["nums"].append(it["n"])
        groups[k]["dues"].add(due.get(it.get("trade") or UNKNOWN) or DEFAULT_DUE)
    parts = [f"{k}: {', '.join('#' + str(n) for n in sorted(g['nums']))}" for k, g in groups.items()]
    dues = sorted({d for g in groups.values() for d in g["dues"]})
    if len(dues) == 1:
        when = f"due {dues[0]}"
    else:
        by_t = {}
        for it in live:
            by_t[it.get("trade") or UNKNOWN] = due.get(it.get("trade") or UNKNOWN) or DEFAULT_DUE
        counts: Dict[str, int] = {}
        for d in by_t.values():
            counts[d] = counts.get(d, 0) + 1
        rest = max(sorted(counts), key=lambda d: counts[d])     # the day most trades share
        when = "due " + ", ".join([f"{t} {d}" for t, d in sorted(by_t.items()) if d != rest]
                                  + [f"the rest {rest}"])
    head = "Ready to send" + (" (shadow mode: nothing will be posted)" if mode != "live" else "") + ":"
    return "\n".join([head, " · ".join(parts), capitalize(when), "",
                      "Reply 'ok' to send. Or change it: \"electrical → Mike\", \"all → Chris\", "
                      "\"electrical Mon\", or 'cancel'."])


def shadow_text(batches: List[Dict[str, Any]]) -> str:
    """What the walker sees while sends are in shadow: what WOULD be posted."""
    lines = ["Punch sends are in shadow mode: nothing was posted. Would send:"]
    for b in batches:
        lines.append("")
        lines.append(group_text(b["name"], b["items"], b["due_words"], grouped=bool(b.get("grouped"))))
        if b.get("mention_resolved") is False:
            lines.append(f"(@{b['name']}: {NO_NUMBER_NOTE})")
        if b.get("photos"):
            lines.append(f"(+{b['photos']} photo{'s' if b['photos'] != 1 else ''})")
    return "\n".join(lines)


# ── CLOSING ──────────────────────────────────────────────────────────────────

_SUB_DONE = re.compile(r"\b(done|finished|fixed|complete[d]?|listo|terminad[oa]|arreglad[oa]|fartik)\b",
                       re.IGNORECASE)
_SUPER_OK = re.compile(r"^\s*(?:P-?[\w-]*\d+)\s*(?:is\s+)?(ok|okay|good|approved|closed?|bien|aprobado)\s*[.!]*\s*$",
                       re.IGNORECASE)
_SUPER_NOT = re.compile(r"^\s*(?:P-?[\w-]*\d+)\s*(?:is\s+)?(not done|not ok|no|reopen|redo|incomplete|no est[aá]|falta)\b",
                        re.IGNORECASE)


def sub_done(text: str) -> bool:
    """The sub says it is finished ("done P23", "P23 listo")."""
    return bool(_SUB_DONE.search(str(text or ""))) and "?" not in str(text or "")


def super_verdict(text: str) -> Optional[str]:
    """"P23 ok" -> "closed"; "P23 not done" -> "reopened"; else None."""
    t = str(text or "")
    if _SUPER_NOT.match(t):
        return "reopened"
    if _SUPER_OK.match(t):
        return "closed"
    return None


# ── QUERIES (DM) ─────────────────────────────────────────────────────────────

_Q_OPEN = re.compile(r"\bwhat'?s\s+open(?:\s+on\s+(?:floor\s+)?(?P<floor>\w+))?(?:\s+(?:at|on|for)\s+(?P<job>.+?))?\s*\??\s*$",
                     re.IGNORECASE)
_Q_WHO = re.compile(r"\bwho\s+closed\s+(?P<pid>P-?[\w-]*\d+)\s*\??\s*$", re.IGNORECASE)
_Q_PHOTO = re.compile(r"\bshow\s+(?:me\s+)?(?P<pid>P-?[\w-]*\d+)(?:'?s)?\s+photo\s*\??\s*$", re.IGNORECASE)


def parse_query(text: str) -> Optional[Dict[str, Any]]:
    t = str(text or "").strip()
    m = _Q_WHO.search(t)
    if m:
        return {"q": "who_closed", "pid": m.group("pid")}
    m = _Q_PHOTO.search(t)
    if m:
        return {"q": "photo", "pid": m.group("pid")}
    m = _Q_OPEN.search(t)
    # A floor ("what's open on 6 at 588?") or the word punch makes it a punch
    # question; a bare "what's open at 8 walworth" stays the assistant's.
    if m and ("punch" in t.lower() or m.group("floor")):
        f = m.group("floor")
        return {"q": "open", "floor": (read_floor(f"floor {f}") or f.lower()) if f else None,
                "job": (m.group("job") or "").strip() or None}
    return None


def open_text(job_name: str, items: List[dict], floor: Optional[str]) -> str:
    rows = [it for it in items if it.get("status") in ("open", "ready_to_check")
            and (floor is None or it.get("floor") == floor)]
    where = f" on {floor_label(floor).lower()}" if floor else ""
    if not rows:
        return f"Nothing open{where} at {job_name}."
    lines = [f"{job_name} · {len(rows)} open{where}:"]
    for it in sorted(rows, key=lambda r: r.get("seq") or 0):
        st = " (ready to check)" if it.get("status") == "ready_to_check" else ""
        who = f" — {it['assignee']['name']}" if (it.get("assignee") or {}).get("name") else ""
        lines.append(f"• {it['pid']} {it.get('text') or ''}{who}{st}")
    return "\n".join(lines)
