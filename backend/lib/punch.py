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
CAPTURE_IDLE_HOURS = 24
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


_ADD_WORDS = re.compile(r"^\s*(?:add(?:\s+(?:a|an|one|item|another))?|also|plus|and also|another(?:\s+one)?)"
                        r"\s*[:\-–,]?\s+(?!(?:photo|pic|picture|to|it|this|that|location|note)\b)(?P<w>\S.{2,})$",
                        re.IGNORECASE | re.DOTALL)


def add_item_words(text: Any) -> Optional[str]:
    """"Add missing access ladder" (a reply to a photo): a NEW item's words
    -- never a note hidden on the photo's item (Tue Oct 13, 12:02 PM). None
    when the message is not one."""
    m = _ADD_WORDS.match(str(text or ""))
    return m.group("w").strip() if m else None


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
    r = room_span(t)
    if r:
        t = t[:r[1]] + " " + t[r[2]:]                   # "3d br": the room is the location's
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


#: A ROOM inside an apartment, its sub-location: "Light fixture broke 3d br"
#: is Apt 3D · bedroom (11:03 PM). EN / ES / YI (Hebrew script and as said).
_ROOMS = [
    ("bedroom", r"br|bdrm|bed\s*room|dormitorio|habitaci[oó]n|rec[aá]mara|cuarto"
                r"|שלאַ?פֿ?צימער|שלאפצימער|shlof\s*tsimer|shlofzimer"),
    ("bathroom", r"bath(?:room)?|bthrm|ba[ñn]o|וואַ?שצימער|באָ?דצימער|vash\s*tsimer|bod\s*tsimer"),
    ("kitchen", r"kitchen|kit|cocina|קיך|kich"),
    ("living room", r"lr|living\s*room|living|sala|וווי?נצימער|וואוינצימער|סאַ?לאָ?ן|salon"),
    ("closet", r"closet|cl[oó]set|armario|שאַ?נק|שאפע|shank"),
    ("terrace", r"terrace|balcony|terraza|balc[oó]n|טעראַ?סע|טעראסע"),
]
_ROOM_ANY = r"(?:" + "|".join(rx for _, rx in _ROOMS) + r")"
_ROOM_LABEL = [(label, re.compile(r"^(?:" + rx + r")$", re.IGNORECASE)) for label, rx in _ROOMS]
_ROOM_AFTER = re.compile(r"\s*(?:,\s*)?(?:(?:in|en)\s+(?:the\s+|el\s+|la\s+)?)?(?P<r>" + _ROOM_ANY + r")(?!\w)",
                         re.IGNORECASE)
_ROOM_BEFORE = re.compile(r"(?<!\w)(?P<r>" + _ROOM_ANY + r")\s*,?\s*$", re.IGNORECASE)
_ROOM_END = re.compile(r"(?<!\w)(?:(?:in|en)\s+(?:the\s+|el\s+|la\s+)?)?(?P<r>" + _ROOM_ANY + r")\s*[.!]*\s*$",
                       re.IGNORECASE)
#: What a room said as the area alone ("kitchen", then "4C") becomes.
ROOM_LABELS = tuple(label for label, _ in _ROOMS)


def _room_label(word: str) -> Optional[str]:
    w = multilang.fold(word).strip() if word else ""
    for label, rx in _ROOM_LABEL:
        if rx.match(w) or rx.match(str(word or "").strip()):
            return label
    return None


def room_span(text: str) -> Optional[Tuple[str, int, int]]:
    """The room next to the caption's unit ("3d br", "br 3d", "4C, in the
    kitchen") or at its very end -- (label, start, end) -- else None. A room
    word elsewhere is words ("Bathroom tile 2b broken": Apt 2B only)."""
    t = str(text or "")
    unit = _LOC_UNIT.search(t) or _BARE_UNIT.search(re.sub(
        r"(?<!\w)(?:floor|fl\.?|piso)\s*\d+", lambda m: " " * len(m.group(0)), t, flags=re.I))
    if not unit:
        return None
    m = _ROOM_AFTER.match(t, unit.end())
    if m:
        return _room_label(m.group("r")), unit.end(), m.end()
    m = _ROOM_BEFORE.search(t[:unit.start()])
    if m:
        return _room_label(m.group("r")), m.start(), unit.start()
    m = _ROOM_END.search(t)
    if m and m.start("r") >= unit.end():
        return _room_label(m.group("r")), m.start(), m.end()
    return None


def read_location(text: str) -> Dict[str, Optional[str]]:
    """{"floor": "4" | "cellar" | None, "area": "Apt 4F" | "lobby" |
    "corridor" | None} from words in English, Spanish or Yiddish; with
    "room": "bedroom" when a room is named with the unit ("3d br")."""
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
    out = {"floor": floor, "area": area}
    if area and area.startswith("Apt "):
        r = room_span(t)
        if r and r[0]:
            out["room"] = r[0]
    return out


def location_state(floor: Optional[str], area: Optional[str]) -> str:
    """"ok" when anything is named -- a floor alone ("1st floor"), a unit,
    a named area, any words ("back of building", "near the gas meter") --
    else "missing". A location is never a blocker (Tue Oct 13, 12:02 PM: a
    45-item walk stuck on "Where on floor 1?"): an item may go out without
    one ("Location: not given")."""
    f = None if floor in (None, "", UNKNOWN) else str(floor)
    a = None if area in (None, "", UNKNOWN) else str(area)
    return "ok" if (f or a) else "missing"


def merge_location(it: dict, loc: Dict[str, Optional[str]]) -> bool:
    """Set what `loc` names on the item (in place). True when it named any."""
    named = False
    if loc.get("floor"):
        it["floor"], named = loc["floor"], True
    if loc.get("area"):
        if str(loc["area"]).startswith("Apt ") and (it.get("area") in ROOM_LABELS
                                                     or it.get("area") in ("kitchen", "bathroom", "bedroom")):
            it["room"] = it["area"]                     # "kitchen", then "4C": Apt 4C · kitchen
        elif not loc.get("room"):
            it.pop("room", None)                        # a new place: its old room is not in it
        it["area"], named = loc["area"], True
    if loc.get("room"):
        it["room"], named = loc["room"], True
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
    if it.get("room") and a != UNKNOWN:
        parts.append(it["room"])
    return " · ".join(parts)


def unit_label(it: dict) -> str:
    """"Apt 3D · bedroom", "Apt 4D", "lobby" (the area, and its room)."""
    a = it.get("area") or UNKNOWN
    if a == UNKNOWN:
        return ""
    return f"{a} · {it['room']}" if it.get("room") else a


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


# ── ONE QUESTION FOR EVERY MISSING LOCATION ─────────────────────────────────

#: Move on without it, at any stage: "just finish", "skip", "ignore that",
#: "send as is", "move on", "." (Tue Oct 13, 12:02 PM: each got the same
#: long prompt again, 5 times).
_ESCAPE = re.compile(
    r"^(?:ok(?:ay)?[,.! ]*)?(?:please\s+)?(?:just\s+)?(?:skip(?:\s+(?:it|that|this|them|all|the rest|locations?))?"
    r"|finish(?:\s+(?:it|up|the walk(?:through)?))?|send(?:\s+it)?\s+(?:as\s+is|without(?:\s+(?:it|them|locations?))?)"
    r"|just send(?:\s+it)?|ignore(?:\s+(?:that|this|it|all that|all of that|them))?(?:\s+and\s+(?:just\s+)?"
    r"(?:finish|send|continue|move on)(?:\s+(?:it|up))?)?|move on|next|continue|keep going|go on|no location"
    r"|none|n/?a|without|leave (?:it|them) blank|blank|salta(?:r)?|sigue|siguiente|ninguno)\W*$|^\W*$")


def is_escape(text: Any) -> bool:
    """'just finish', 'skip', 'ignore that', 'send as is', 'move on', '.'"""
    t = " ".join(str(text or "").lower().split())
    return bool(_ESCAPE.match(t))


SKIP_HINT = "Reply 'skip' to continue without it."


def batch_where_question(missing: List[dict]) -> str:
    """ONE question for every item with no location, then the draft:
    "39 have no location. Reply like '3 rear yard, 5-9 roof, 12 2nd floor',
    or 'all roof', or 'skip' to send without." and the short list."""
    n = len(missing)
    lines = [f"{n} {'has' if n == 1 else 'have'} no location. Reply like "
             "'3 rear yard, 5-9 roof, 12 2nd floor', or 'all roof', or 'skip' to send without."]
    for it in missing:
        words = (it.get("text") or "").strip() or "(no words)"
        if len(words) > 32:
            words = words[:30].rstrip() + "…"
        lines.append(f"#{it.get('n')} {words}")
    return "\n".join(lines)


BATCH_SHORT = "Reply like '3 rear yard, 5-9 roof', 'all roof', or 'skip'."

_ALL_LEAD = re.compile(r"^\s*(?:all|everything|every(?:one| item)?|the rest|rest|todos?|todo|el resto)"
                       r"(?:\s+(?:of\s+)?(?:them|are|is|at|on|in|the))*\s*[:\-–,]?\s*(?P<loc>.+)$",
                       re.IGNORECASE)
_PART = re.compile(r"^\s*#?\s*(?P<a>\d{1,3})(?:\s*(?:-|–|to|thru|through)\s*#?\s*(?P<b>\d{1,3}))?"
                   r"(?:\s*(?:,|and|&)\s*#?\s*(?P<more>\d{1,3}(?:\s*(?:,|and|&)\s*#?\s*\d{1,3})*))?"
                   r"\s*[:\-–.]?\s+(?P<loc>\D.*?)\s*$", re.IGNORECASE)
_LOC_FILLER = re.compile(r"^(?:location(?:\s+is)?|loc|it'?s|its|they'?re|at|on|in|the)\s*[:\-]?\s+"
                         r"|\s+(?:is|are)\s+(?:the\s+)?(?:location|loc)\s*$|\s+(?:location|loc)\s*$",
                         re.IGNORECASE)


#: Words that are not a place, whatever was asked.
_NOT_A_PLACE = re.compile(
    r"^(?:hmm+|hm+|huh|what|wait|ok(?:ay)?|yes|yeah|no|nope|idk|i don'?t know|dunno|no idea|"
    r"not sure|thanks?|thank you|why|how|done|send|help|\?+)[\s?!.]*$", re.IGNORECASE)


def free_location(text: Any) -> Dict[str, Optional[str]]:
    """A location AS TYPED: its floor when one is said ("2nd floor
    interior" -> floor 2, "interior"), a unit as Apt ("4F" -> Apt 4F), and
    every other word kept as the area exactly as written ("Back of building
    is location" -> "Back of building", "rear yard" stays "rear yard").
    Nothing with letters in it: nothing."""
    t = " ".join(str(text or "").split()).strip(" .;,")
    for _ in range(2):
        t = _LOC_FILLER.sub("", t).strip(" .;,")
    if not t or not re.search(r"[^\W\d_]", t) or _NOT_A_PLACE.match(t):
        return {"floor": None, "area": None}
    loc = read_location(t)
    if str(loc.get("area") or "").startswith("Apt "):
        return loc
    floor = loc.get("floor")
    rest = _LOC_FLOOR.sub(" ", t) if floor else t
    rest = " ".join(rest.split()).strip(" ,.-")
    area = rest[:80] if re.search(r"[^\W\d_]{2,}", rest) else None
    return {"floor": floor, "area": area}


_NUMS = r"#?\d{1,3}(?:\s*(?:-|–|to|thru|through)\s*#?\d{1,3})?"
_NUM_LIST = _NUMS + r"(?:\s*(?:,|and|&)\s*" + _NUMS + r")*"
_BATCH_PART = re.compile(
    r"(?:^|(?<=[,;\n]))\s*(?P<nums>" + _NUM_LIST + r")\s*[:\-–.]?\s+"
    r"(?P<loc>.+?)(?=\s*[,;\n]\s*" + _NUM_LIST + r"\s*[:\-–.]?\s+(?!(?:st|nd|rd|th)\b)|\s*$)",
    re.IGNORECASE)


def _numbers(said: str) -> List[int]:
    out: List[int] = []
    for a, b in re.findall(r"#?(\d{1,3})(?:\s*(?:-|–|to|thru|through)\s*#?(\d{1,3}))?", said):
        lo, hi = int(a), int(b or a)
        lo, hi = min(lo, hi), max(lo, hi)
        out += list(range(lo, hi + 1)) if hi - lo < 200 else [lo]
    return out


def parse_batch_where(text: Any, missing_ns: List[int]) -> Optional[Dict[str, Any]]:
    """The answer to batch_where_question: {"skip": True}, or {"set": {n:
    location}} -- "3 rear yard, 5-9 roof, 12 2nd floor", "all roof", "rest
    lobby", "#4 boiler room", "3,4 and 7 cellar". None: not an answer."""
    t = " ".join(str(text or "").split())
    if is_escape(t):
        return {"skip": True}
    m = _ALL_LEAD.match(t)
    if m:
        loc = free_location(m.group("loc"))
        if loc.get("floor") or loc.get("area"):
            return {"set": {n: loc for n in missing_ns}}
    out: Dict[int, Dict[str, Optional[str]]] = {}
    for pm in _BATCH_PART.finditer(t):
        loc = free_location(pm.group("loc"))
        if loc.get("floor") or loc.get("area"):
            for n in _numbers(pm.group("nums")):
                out[n] = loc
    return {"set": out} if out else None


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
    return {**({"room": loc["room"]} if loc.get("room") else {}),
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
    where = unit_label(it) if a != UNKNOWN and re.match(r"(?i)apt\b", a) else location_label(it)
    return (f"Added #{it.get('n')}" + (f" '{words}'" if words else " (photo)")
            + (f" ({where})" if where else "") + ".")


def noted_text(it: dict) -> str:
    """The reply to words typed during capture (never only a 👍, live 588,
    Oct 12): "#3 'Tile chipped' (Apt 4D) — got it. Next photo, or 'done'."."""
    words = (it.get("text") or "").strip()
    if len(words) > 60:
        words = words[:57].rstrip() + "…"
    where = location_label(it)
    return (f"#{it.get('n')}" + (f" '{words}'" if words else "")
            + (f" ({where})" if where else " (where? floor and unit)")
            + " — got it. Next photo, or 'done' (or \"done, send to Chris\").")


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


NOT_GIVEN = "Location: not given"


def floor_label(f: str) -> str:
    if f == UNKNOWN:
        return NOT_GIVEN
    if f.isdigit():
        return f"Floor {f}"
    return f.capitalize()


def place_key(it: dict) -> str:
    """What an item is listed under: its floor; else its area as said
    ("back of building"); else UNKNOWN (Location: not given)."""
    f = it.get("floor") or UNKNOWN
    if f != UNKNOWN:
        return f
    a = it.get("area") or UNKNOWN
    return a if a != UNKNOWN else UNKNOWN


def ordered(items: Iterable[dict]) -> List[dict]:
    """The draft's order -- the numbers follow it: floor, then trade ("?"
    last), then the order the photos came in."""
    def key(it):
        t = it.get("trade") or UNKNOWN
        return (_floor_key(place_key(it)), t == UNKNOWN, t,
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
    where = f" ({unit_label(it)})" if area and area != UNKNOWN and area != it.get("floor") else ""
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
        by_floor.setdefault(place_key(it), []).append(it)
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


def extra_qualities(it: Dict[str, Any]) -> List[Optional[str]]:
    """The quality of each of an item's extra photos (merged in), in order;
    None where none was recorded."""
    n = len(it.get("extra_photos") or [])
    q = list(it.get("extra_quality") or [])[:n]
    return q + [None] * (n - len(q))


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
        if b.get("photo_key"):
            # Each extra photo keeps its own quality (Codex review on #765).
            a["extra_quality"] = extra_qualities(a) + [b.get("photo_quality")]
            a["extra_photos"] = list(a.get("extra_photos") or []) + [b["photo_key"]]
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
        it.pop("room", None)                            # a new place: no old room in it
    return True, f"{e['op']} {e['n']}"


# ── ASSIGNING ────────────────────────────────────────────────────────────────

def assign_text(sugg: Dict[str, Optional[dict]]) -> str:
    lines = ["Who gets what?"]
    for t, p in sorted(sugg.items()):
        lines.append(f"• {t} → {who_label(p)}")
    lines.append(ASSIGN_HINT)
    return "\n".join(lines)


#: "all → Chris" read like "send to everyone" (11:05 PM).
ASSIGN_HINT = ("Reply 'ok', fix one (\"electrical → Mike\"), or send the whole list to one "
               "person (\"whole list → Chris\").")


_ASSIGN = re.compile(r"^\s*([a-z /áéíóúñ]+?)\s*(?:→|->|=>|>|:|=|to)\s*(.+?)\s*$", re.IGNORECASE)


ASSIGN_SHORT = "Reply like 'electrical → Mike', 'all → Chris', or 'to the group'."


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
    r"^\s*(?:send\s+|give\s+)?(?:all\s+items|all\s+of\s+(?:it|them)|all|everything|the\s+whole\s+(?:list|thing)"
    r"|whole\s+list|the\s+(?:whole\s+)?list|todo|todos)\s*(?:items\s*)?"
    r"(?:→|->|=>|>|:|=|to|for|goes\s+to|go\s+to|a|para)\s*(?P<name>.+?)\s*[.!]*\s*$",
    re.IGNORECASE)
#: The job's own WhatsApp group as the target: the whole list posted there,
#: each trade's owner @mentioned where known.
_GROUP = re.compile(
    r"^\s*(?:(?:send|post|put)\s+(?:it\s+|them\s+|everything\s+|all\s+|the\s+(?:whole\s+)?list\s+)?"
    r"|(?:all|everything|the\s+(?:whole\s+)?list|whole\s+list)\s+)?"
    r"(?:(?:to|in|into|on|→|->)\s+)?(?:the\s+|this\s+|our\s+)?(?:gc\s+|job\s+|whatsapp\s+)?group"
    r"(?:\s+chat)?\s*[.!]*\s*$", re.IGNORECASE)
_WHO = re.compile(
    r"^\s*(?:who\s+(?:can|could|do)\s+(?:you|i|it|we)\s+(?:send|give|assign)|who(?:'?s|\s+is)\s+(?:available|there|on\s+(?:this\s+)?job)"
    r"|(?:what\s+are\s+(?:the|my)\s+)?options|list\s+(?:the\s+)?people|who\s+can\s+(?:i|you)\s+pick"
    r"|show\s+(?:me\s+)?(?:the\s+)?people|people|who\s*\?)", re.IGNORECASE)


def parse_assign_reply(text: str) -> Dict[str, Any]:
    """What an answer to "Who gets what?" says:
      {"all": name}            "all → Chris", "everything to Chris GC", "whole list for Chris"
      {"group": True}          "to the group", "post in group", "GC group"
      {"who": True}            "who can you send it to?", "options", "list people"
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
    if _GROUP.match(t):
        return {"group": True}
    if _WHO.match(t):
        return {"who": True}
    m = _ALL.match(t)
    if m:
        if _GROUP.match(m.group("name")):
            return {"group": True}
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


# ── "Done, send to Chris" (live 588, Oct 12, 10:46 AM: only a 👍) ──────────
#
# At any stage after the photos: "send to X", "send it / all / everything /
# the list to X", "everything to X", "done, send to X", with an optional due
# ("asap", "by Fri", "due tomorrow"). The whole list goes to X by DM (the
# missing locations asked first, then the recap; 'ok' sends). "send to the
# group" / "post in group": the same, to the job's group.

_SHORTCUT_LEAD = (r"^\s*(?:(?:ok(?:ay)?|done|finished|listo|that'?s\s+(?:it|all))\s*[,.!:;-]*\s*)?"
                  r"(?:(?:and|then|now)\s+)?(?:please\s+|pls\s+)?")
_SHORTCUT = re.compile(
    _SHORTCUT_LEAD
    + r"(?:(?:send|post|give|forward)\s+(?:it\s+|them\s+|all\s+(?:of\s+(?:it|them)\s+)?|everything\s+"
      r"|the\s+(?:whole\s+)?(?:list|punch\s+list|thing)\s+|whole\s+list\s+)?(?:all\s+)?"
      r"|(?:everything|all\s+of\s+it|the\s+whole\s+list|whole\s+list)\s+)"
    r"(?:to|for|→|->)\s+(?P<rest>.+?)\s*[.!]*\s*$", re.IGNORECASE)
_GROUP_TARGET = re.compile(r"^(?:the\s+|this\s+|our\s+)?(?:gc\s+|job\s+|whatsapp\s+)?group(?:\s+chat)?$",
                           re.IGNORECASE)
# The due at the end: one date word, after an optional "by / due / for / on"
# and "next / this" -- never a word of the name before it (Codex review on
# #765: "John Smith tomorrow" read as John, due "Smith tomorrow").
_DUE_TAIL = re.compile(r"^(?P<who>.+?)(?:\s*,\s*|\s+)"
                       r"(?P<due>(?:(?:by|due|for|on)\s+)?(?:(?:next|this)\s+)?\S+)$", re.IGNORECASE)


def send_shortcut(text: Any) -> Optional[Dict[str, Any]]:
    """{"group": True, "due": words|None} or {"name": "chris", "due": words|None};
    None when the text is not a "send to …"."""
    t0 = re.sub(_SHORTCUT_LEAD, "", str(text or ""), count=1, flags=re.IGNORECASE)
    if _GROUP.match(t0) and re.search(r"\b(?:send|post|put|to|in)\b", t0, re.IGNORECASE):
        return {"group": True, "due": None}                  # "post in group", "to the group"
    m = _SHORTCUT.match(str(text or ""))
    if not m:
        return None
    rest = m.group("rest").strip().strip(".!,")
    due = None
    t = _DUE_TAIL.match(rest)
    if t and due_words(t.group("due")):
        rest, due = t.group("who").strip().strip(","), due_words(t.group("due"))
    if not rest or "?" in rest:
        return None
    if _GROUP_TARGET.match(rest):
        return {"group": True, "due": due}
    if len(rest.split()) > 6:
        return None
    return {"name": rest, "due": due}


#: Words that say WHICH side someone is on: the GC (the company's own users).
ROLE_TAGS = ("gc team", "gc", "general contractor", "super", "superintendent", "pm",
             "project manager", "office", "the office", "us", "team", "foreman")


def split_name(said: str) -> Tuple[str, str]:
    """"Chris from gc." -> ("chris", "gc"); "Mike (Bright)" -> ("mike", "bright");
    "Chris GC" / "Chris GC team" / "the super Chris" -> ("chris", "gc" / "super")."""
    t = multilang.fold(str(said or "")).strip().strip(".!,;")
    t = re.sub(r"^(?:the|to)\s+", "", t)
    m = re.match(r"^(.*?)\s*(?:\(([^)]*)\)|\s(?:from|of|at|with|de|del)\s+(?:the\s+)?(.+))$", t)
    if m:
        return m.group(1).strip(), (m.group(2) or m.group(3) or "").strip()
    for tag in sorted(ROLE_TAGS, key=len, reverse=True):
        m = re.match(r"^(.+?)\s+(?:the\s+)?" + re.escape(tag) + r"$", t) \
            or re.match(r"^(?:the\s+)?" + re.escape(tag) + r"\s+(.+)$", t)
        if m:
            return m.group(1).strip(), tag
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
    if not hits and n and " " in n and not co:
        # "Mike Bright": the first name, and the rest names his company.
        first, rest = n.split(" ", 1)
        n, co = first, rest
        hits = [p for p in people if name_hit(p)]
    if co:
        role = co in ROLE_TAGS
        narrowed = [p for p in hits if co in multilang.fold(p.get("company") or "")
                    or (role and (p.get("kind") == "user"
                                  or multilang.fold(p.get("company") or "") in ("gc", "gc team")))]
        hits = narrowed or ([] if role else hits)
    uniq: Dict[tuple, dict] = {}
    for p in hits:
        uniq.setdefault(_person_key(p), p)
    return sorted(uniq.values(), key=lambda p: (not p.get("on_job"),
                                                multilang.fold(p.get("name") or "")))


def closest_names(name: str, people: List[Dict[str, Any]], k: int = 3) -> List[str]:
    """The k people a name not found is closest to ("Did you mean: …?")."""
    import difflib
    n = split_name(name)[0] or multilang.fold(str(name or ""))
    scored = []
    for p in people:
        full = multilang.fold(p.get("name") or "")
        if not full:
            continue
        first = full.split(" ")[0]
        score = max(difflib.SequenceMatcher(None, n, full).ratio(),
                    difflib.SequenceMatcher(None, n, first).ratio())
        scored.append((-score, not p.get("on_job", True), full, p))
    seen, out = set(), []
    for *_k, p in sorted(scored, key=lambda x: x[:3]):
        label = who_label({**p, "not_on_job": not p.get("on_job", True)})
        if label not in seen:
            seen.add(label)
            out.append(label)
        if len(out) == k:
            break
    return out


def people_text(people: List[Dict[str, Any]], contacts: List[dict], group_name: str) -> str:
    """Who a punch list can go to (4): the company's users, People on this
    job, the subs' punch contacts, and the job's group."""
    users = sorted({f"{p['name']} · GC team" for p in people if p.get("kind") == "user" and p.get("name")})
    on_job = sorted({f"{p['name']} · {p.get('company') or '?'}" for p in people
                     if p.get("kind") != "user" and p.get("on_job") and p.get("name")})
    subs = sorted({f"{c['name']} · {c.get('company') or '?'} ({c.get('trade') or 'punch contact'})"
                   for c in contacts if c.get("name")})
    lines = ["Who can get it:"]
    if users:
        lines.append("Your team: " + "; ".join(users))
    if on_job:
        lines.append("People on this job: " + "; ".join(on_job))
    if subs:
        lines.append("Punch contacts: " + "; ".join(subs))
    lines.append(f"Or the group: \"to the group\" posts the list in {group_name or 'the job group'}"
                 " and @mentions each trade's person.")
    return "\n".join(lines)


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


# ── DUE ──────────────────────────────────────────────────────────────────────
#
# 11:06 PM: "No due date. Asap on all" was ignored and the recap stayed "Due
# Fri" -- the old fixed default (DEFAULT_DUE). Now:
#   ASAP        chased every day from tomorrow
#   no due date never chased; the item is shown open
#   a day       "today", "tomorrow", "Mon", "by Wed", "Oct 20": chased that day
# per trade ("electrical Mon") or for all ("all asap"). The project's
# "Punch items due" setting is the default (ASAP unless changed).

ASAP = "ASAP"
NO_DUE = "no due date"
#: The project setting's choices ("punch_due_default"), and the default.
DUE_DEFAULTS = ("asap", "none", "tomorrow", "fri")
DEFAULT_DUE_SETTING = "asap"
_ASAP = re.compile(r"^(?:asap|a\.s\.a\.p\.?|as\s+soon\s+as\s+possible|urgent|right\s+away|immediately|now"
                   r"|ya|lo\s+antes\s+posible|cuanto\s+antes|urgente|גלייך|תיכף|bald)$", re.IGNORECASE)
_NO_DUE = re.compile(r"^(?:no\s+(?:due\s+)?(?:date|deadline|due)|none|no\s+due\s+date|whenever|no\s+rush"
                     r"|sin\s+fecha|sin\s+prisa|nisht\s+eilig)$", re.IGNORECASE)


def due_default(setting: Any) -> str:
    """The project's default due words ("ASAP" unless set otherwise)."""
    v = str(setting or DEFAULT_DUE_SETTING).lower()
    return {"asap": ASAP, "none": NO_DUE, "tomorrow": "tomorrow", "fri": "Fri"}.get(v, ASAP)


#: Kept for the walks stored with it; new walks use the project's setting.
DEFAULT_DUE = ASAP


def due_words(words: Any) -> Optional[str]:
    """The due words as kept -- "ASAP", "no due date", or a day the date
    readers can read ("Mon", "tomorrow", "by Wed" -> "Wed") -- else None."""
    from lib import wa_attention
    from datetime import datetime, timezone
    w = re.sub(r"^\s*(?:due\s+|by\s+|para\s+(?:el\s+)?|el\s+|on\s+)+", "", str(words or ""),
               flags=re.IGNORECASE).strip(" .!")
    if not w:
        return None
    if _ASAP.match(w):
        return ASAP
    if _NO_DUE.match(w):
        return NO_DUE
    if wa_attention.parse_due(multilang.normalize_when(w), datetime(2026, 1, 5, tzinfo=timezone.utc)):
        return w
    return None


def due_label(words: Any) -> str:
    """"due ASAP", "no due date", "due Fri"."""
    w = str(words or ASAP)
    return NO_DUE if w == NO_DUE else f"due {w}"


def due_date(words: str, sent_at):
    """The day a due answer names (Spanish / Yiddish read as English): ASAP
    is tomorrow (then chased every day); no due date is None."""
    from lib import wa_attention
    from datetime import timedelta
    if words == ASAP:
        return (sent_at + timedelta(days=1)).date()        # a day, as the chase reads due_at
    if words == NO_DUE or not words:
        return None
    return wa_attention.parse_due(multilang.normalize_when(words), sent_at)


#: "the rest" / "everything else": the trades not named; "all": every trade.
_REST_WORDS = (r"(?:everything\s+else|everyone\s+else|all\s+else|all\s+others|the\s+others|others"
               r"|(?:the\s+)?rest|lo\s+dem[aá]s|el\s+resto)")
_ALL_WORDS = (r"(?:" + _REST_WORDS + r"|all\s+items|all\s+of\s+(?:it|them)|all|everything|everyone"
              r"|todos|todo)")


def parse_due_answer(text: str, trades: Iterable[str]) -> Optional[Dict[str, str]]:
    """"asap" / "all asap" / "Asap on all" / "Fri" -> every trade; "electrical
    Mon, paint Fri" -> per trade; "no due date" -> none for all. Each part
    in order, a later one winning ("No due date. Asap on all" -> ASAP).
    Returns {trade: due words} or None when nothing in it reads as a due."""
    ts = [t for t in trades if t != UNKNOWN]
    out: Dict[str, str] = {}
    named: set = set()
    for part in re.split(r"[\n;,]+|\.\s+|\.$", str(text or "")):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^\s*([a-z /áéíóúñ]+?)\s+(?:by\s+|due\s+|para\s+el\s+|el\s+)?(.+)$", part, re.IGNORECASE)
        t = trade_word(m.group(1)) if m else None
        if t and due_words(m.group(2)):
            out[t] = due_words(m.group(2))
            named.add(t)
            continue
        rest = bool(re.match(r"^\s*" + _REST_WORDS + r"\b", part, re.IGNORECASE)
                    or re.search(r"\s(?:on|for|to)\s+" + _REST_WORDS + r"\s*$", part, re.IGNORECASE))
        words = re.sub(r"^\s*" + _ALL_WORDS + r"\s+", "", part, flags=re.IGNORECASE)
        words = re.sub(r"\s+(?:on|for|to)\s+" + _ALL_WORDS + r"\s*$", "", words, flags=re.IGNORECASE)
        d = due_words(words)
        if d:
            for t2 in ts:
                if rest and t2 in named:
                    continue                    # "the rest": not the trades just named
                out[t2] = d
    return out or None


#: Due-ish words: an answer with these that could not be read is asked again.
_DUE_HINT = re.compile(r"\b(?:due|date|deadline|asap|by|today|tomorrow|tonight|week|monday|tuesday|wednesday"
                       r"|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun|fecha|para\s+el)\b",
                       re.IGNORECASE)
DUE_ASK = "Due when? (asap / no date / a day)"


def due_said(text: str) -> bool:
    return bool(_DUE_HINT.search(str(text or "")))


# ── SENDING ──────────────────────────────────────────────────────────────────

def _where(it: dict) -> str:
    return " · ".join(x for x in (floor_label(it["floor"]) if it.get("floor") not in (None, UNKNOWN) else "",
                                  unit_label(it)) if x)


def done_hint(items: List[dict]) -> str:
    """With a real id from THIS list (11:07 PM: it said "done P23")."""
    pid = next((it.get("pid") for it in items if it.get("pid")), "P-1")
    return f"Reply \"done {pid}\" (a photo helps) when each one is finished."


def _list_lines(items: List[dict], mentions: Optional[Dict[str, str]] = None) -> List[str]:
    """Items under their floor, then trade; a trade's owner @mentioned
    beside it when `mentions` names one."""
    lines: List[str] = []
    by_floor: Dict[str, Dict[str, List[dict]]] = {}
    for it in items:
        by_floor.setdefault(place_key(it), {}).setdefault(
            it.get("trade") or UNKNOWN, []).append(it)
    for f in sorted(by_floor, key=_floor_key):
        lines.append(f"*{floor_label(f)}*")
        for t in sorted(by_floor[f], key=lambda x: (x == UNKNOWN, x)):
            who = (mentions or {}).get(t)
            lines.append(f"_{t}_" + (f" {who}" if who else ""))
            for it in by_floor[f][t]:
                u = unit_label(it)
                lines.append(f"• {it['pid']} {it.get('text') or ''}"
                             f"{(' (' + u + ')') if u and u != f else ''}")
    return lines


def group_text(name: str, items: List[dict], due_words: str,
               handle: Optional[str] = None, grouped: bool = False) -> str:
    """One message per assignee: @them, their items, the due. `handle` is
    their token from lib/wa_mention ("@15551234567" mentions them for real);
    without it, "@Name". `grouped`: the items under their floor, then trade."""
    lines = [f"{handle or '@' + name} punch list — {due_label(due_words)}:"]
    if grouped:
        lines.extend(_list_lines(items))
    else:
        for it in items:
            where = _where(it)
            lines.append(f"• {it['pid']} {it.get('text') or ''}{(' (' + where + ')') if where else ''}")
    lines.append(done_hint(items))
    return "\n".join(lines)


def dm_text(job_name: str, items: List[dict], due_words: str) -> str:
    """The whole list, by DM to one person."""
    return "\n".join([f"{job_name} punch list — {due_label(due_words)}:", *_list_lines(items),
                      done_hint(items)])


def full_list_text(job_name: str, items: List[dict], due_words: str,
                   mentions: Dict[str, str]) -> str:
    """The whole list posted in the job's group, each trade's owner
    @mentioned beside it where known."""
    return "\n".join([f"{job_name} punch list — {due_label(due_words)}:",
                      *_list_lines(items, mentions), done_hint(items)])


def recap_text(items: List[dict], assign: Dict[str, Optional[dict]], due: Dict[str, str],
               mode: str = DEFAULT_SEND_MODE, whole: Optional[dict] = None, *,
               target: Optional[str] = None, group_name: str = "",
               default_due: str = ASAP) -> str:
    """The exact send, before it happens: where it goes, who gets which
    numbers, and when. 'ok' sends."""
    live = ordered([it for it in items if it.get("status", "draft") != "dropped"])
    shadow = " (shadow mode: nothing will be sent)" if mode != "live" else ""
    group = group_name or "the job group"

    def nums(ns):
        return ", ".join("#" + str(n) for n in sorted(ns))
    if target == "group":
        owners = sorted({f"{who_label(assign.get(t))} ({t})"
                         for t in {it.get("trade") for it in live} if assign.get(t)})
        head = [f"Ready to post the whole list in {group}{shadow}: {nums(it['n'] for it in live)}",
                ("Mentioning " + "; ".join(owners)) if owners
                else "No one to mention (no trade has a name)."]
    elif whole:
        head = [f"Ready to DM the whole list to {who_label(whole)}{shadow}: "
                f"{nums(it['n'] for it in live)}"]
    else:
        groups: Dict[str, List[int]] = {}
        for it in live:
            groups.setdefault(who_label(assign.get(it.get("trade") or UNKNOWN)), []).append(it["n"])
        head = [f"Ready to post in {group}{shadow}, mentioning each one:",
                " · ".join(f"{k}: {nums(v)}" for k, v in groups.items())]
    by_t: Dict[str, str] = {}
    for it in live:
        by_t[it.get("trade") or UNKNOWN] = due.get(it.get("trade") or UNKNOWN) or default_due
    days = sorted(set(by_t.values()))
    if len(days) <= 1:
        when = due_label(days[0] if days else default_due)
    else:
        counts: Dict[str, int] = {}
        for d in by_t.values():
            counts[d] = counts.get(d, 0) + 1
        rest = max(sorted(counts), key=lambda d: counts[d])     # the one most trades share
        short = lambda d: "no date" if d == NO_DUE else d        # noqa: E731
        when = "due " + ", ".join([f"{t} {short(d)}" for t, d in sorted(by_t.items()) if d != rest]
                                  + [f"the rest {short(rest)}"])
    return "\n".join(head + [capitalize(when), "",
                             "Reply 'ok' to send. Or change it: \"electrical → Mike\", "
                             "\"whole list → Chris\", \"to the group\", \"asap\" / \"electrical Mon\", "
                             "or 'cancel'."])


def destination(b: Dict[str, Any], group_name: str = "", live: bool = False) -> str:
    """"Would DM Chris Weiss (GC team)" / "Would post in 588 Thomas St,
    mentioning Dov Klein" (live: "DM'd …" / "Posted in …")."""
    if b.get("via") == "dm":
        return f"{'DM' + chr(39) + 'd' if live else 'Would DM'} {b.get('who') or b['name']}"
    names = b.get("mentions_named") or ([b["name"]] if b.get("name") else [])
    tail = f", mentioning {', '.join(names)}" if names else ""
    return f"{'Posted' if live else 'Would post'} in {group_name or 'the job group'}{tail}"


def no_numbers(text: Any) -> str:
    """No phone number in anything an admin reads: an "@<number>" mention
    token left in a preview reads "@(WhatsApp contact)". Numbers belong in
    the mention payload only."""
    return re.sub(r"(?<![\w@])@\d{7,15}(?!\d)", "@(WhatsApp contact)", str(text or ""))


def shadow_text(batches: List[Dict[str, Any]], group_name: str = "") -> str:
    """What the walker sees while sends are in shadow: where each message
    WOULD go, and what it would say."""
    lines = ["Punch sends are in shadow mode: nothing was sent."]
    for b in batches:
        lines.append("")
        lines.append(destination(b, group_name) + ":")
        lines.append(no_numbers(b.get("display") or b.get("text") or group_text(
            b["name"], b["items"], b["due_words"], grouped=bool(b.get("grouped")))))
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


_DONE_REF = re.compile(r"^\s*(?:done|finished|fixed|listo|terminado|fartik)\s*#?\s*"
                       r"(?:p-?(?:(?P<code>[a-z0-9]{1,12})-)?)?(?P<seq>\d{1,5})\s*[.!]*\s*$", re.IGNORECASE)


def parse_done_ref(text: str) -> Optional[Tuple[Optional[str], int]]:
    """"done 1", "done #1", "done P1", "done P-588-1" -> (code or None, 1)."""
    m = _DONE_REF.match(str(text or ""))
    if not m:
        return None
    return ((m.group("code") or "").upper() or None), int(m.group("seq"))


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


def reopen_note(text: str) -> Optional[str]:
    """The why after a reopen: "P23 not done — still chipped at the corner"
    -> "Still chipped at the corner"; None when nothing follows."""
    m = _SUPER_NOT.match(str(text or ""))
    if not m:
        return None
    rest = str(text)[m.end():].strip().lstrip("-—–:,;.!").strip()
    return capitalize(rest)[:300] if rest else None


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


# ── A LOCATION FOR A GROUP OF PHOTOS (during the walk) ─────────────────────
#
# Tue Oct 13: a location typed between photos ("all 2nd floor interior",
# "these are all roof", "everything above is cellar", "rest are lobby", or
# just "roof") is for the photos since the previous location message -- not
# the last photo alone. A reply to one photo is that photo; "#12-20 roof" is
# those numbers. The model reads scope and place from loose words (EN / ES /
# YI); the code applies them, never over a place the walker gave one photo.

_GROUP_WORDS = re.compile(
    r"^\s*(?:(?:these|those|they)\s+(?:are|were)\s+(?:all\s+)?|all\s+(?:of\s+)?(?:these|those|them|the above)\s+(?:are\s+)?"
    r"|everything\s+(?:above\s+)?(?:is\s+|was\s+)?|all\s+(?:the\s+)?(?:above\s+)?(?:are\s+|is\s+)?|the\s+rest\s+(?:are\s+|is\s+)?"
    r"|rest\s+(?:are\s+|is\s+)?|above\s+(?:are\s+|is\s+)?|todos?\s+(?:son\s+|en\s+)?|todas?\s+(?:son\s+|en\s+)?"
    r"|estos\s+(?:son\s+)?(?:todos\s+)?|estas\s+(?:son\s+)?(?:todas\s+)?|alle\s+|di\s+alle\s+|אַלע\s+|אלע\s+)"
    r"(?:(?:on|in|at|en|el|la|the)\s+)*", re.IGNORECASE)

LOC_MODEL_PROMPT = (
    "A construction super is sending punch-list photos in WhatsApp, one by one. "
    "Between photos they type or say short messages. Read ONE such message and "
    "answer with a JSON object only: {\"kind\": \"location\" | \"other\", "
    "\"scope\": \"group\" | \"numbers\" | \"last\", \"numbers\": [ints], "
    "\"location\": \"the place, in the words they used\"}. kind is \"location\" "
    "ONLY when the whole message says WHERE (a floor, unit, room or any area: "
    "\"2nd floor interior\", \"roof\", \"rear yard\", \"cellar\", \"piso 3\", "
    "\"אויפן דאך\") and says nothing else about a defect; a defect, a note, a "
    "question or anything else is \"other\". scope: \"numbers\" when it names "
    "photo numbers (\"#12-20 roof\": numbers 12..20); \"last\" only when it "
    "says this one / the last one / this photo; otherwise \"group\" (\"all\", "
    "\"these\", \"everything above\", \"rest\", or a bare place). location: "
    "copy their words for the place, without \"all\", \"these are\", "
    "\"everything above is\"; never translate, never add words."
)


def read_group_location(text: Any) -> Optional[Dict[str, Any]]:
    """The patterns' reading (no model): {"scope": "group" | "numbers",
    "numbers": [...], "location": {...}} for a message that is only a place,
    else None."""
    t = " ".join(str(text or "").split()).strip(" .!")
    if not t:
        return None
    nums = parse_batch_where(t, [])
    if nums and nums.get("set"):
        groups: Dict[str, Any] = {}
        for n, loc in nums["set"].items():
            groups.setdefault("numbers", []).append(n)
            groups["location"] = loc
        return {"scope": "numbers", "numbers": sorted(groups["numbers"]), "location": groups["location"]}
    m = _GROUP_WORDS.match(t)
    if m and m.end() < len(t):
        loc = free_location(t[m.end():])
        if loc.get("floor") or loc.get("area"):
            return {"scope": "group", "numbers": [], "location": loc}
        return None
    # A bare place: a floor, a unit or a named area, and no other words.
    loc = read_location(t)
    if not (loc.get("floor") or loc.get("area")) or len(t.split()) > 5:
        return None
    rest = _LOC_FLOOR.sub(" ", t)
    for _label, rx in _COMMON_RX + _NEEDS_FLOOR_RX:
        rest = rx.sub(" ", rest)
    rest = re.sub(r"(?i)\b(?:on|in|at|the|en|el|la|de|interior|exterior)\b", " ", rest)
    if re.search(r"[^\W\d_]{3,}", rest):
        return None                                  # words beyond the place: a caption / note
    return {"scope": "group", "numbers": [], "location": free_location(t)}


def clean_loc_model(got: Any) -> Optional[Dict[str, Any]]:
    """The model's reading, checked: None unless it is a location with a
    place that reads as one."""
    if not isinstance(got, dict) or got.get("kind") != "location":
        return None
    loc = free_location(got.get("location"))
    if not (loc.get("floor") or loc.get("area")):
        return None
    scope = got.get("scope") if got.get("scope") in ("group", "numbers", "last") else "group"
    nums = [int(n) for n in (got.get("numbers") or []) if isinstance(n, (int, float)) or str(n).isdigit()]
    if scope == "numbers" and not nums:
        scope = "group"
    return {"scope": scope, "numbers": sorted(set(nums)), "location": loc}


def _ordinal(n: str) -> str:
    i = int(n)
    suf = "th" if 10 <= i % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(i % 10, "th")
    return f"{i}{suf}"


def loc_phrase(loc: Dict[str, Optional[str]]) -> str:
    """"2nd floor (interior)", "roof", "2nd floor", "Apt 4F"."""
    f, a = loc.get("floor"), loc.get("area")
    fl = (f"{_ordinal(f)} floor" if f and str(f).isdigit() else (str(f) if f and f != a else ""))
    if fl and a:
        return f"{fl} ({a})"
    return fl or str(a or "")


def numbers_text(ns: List[int]) -> str:
    """"#5–#16", "#3, #5, #7"."""
    ns = sorted(ns)
    if len(ns) > 2 and ns == list(range(ns[0], ns[-1] + 1)):
        return f"#{ns[0]}–#{ns[-1]}"
    return ", ".join(f"#{n}" for n in ns)


def group_confirm(loc: Dict[str, Optional[str]], ns: List[int]) -> str:
    n = len(ns)
    return f"Set {loc_phrase(loc)} for {numbers_text(ns)} ({n} photo{'s' if n != 1 else ''})."


def group_targets(items: List[dict], since_captured: int) -> List[dict]:
    """The photos a group location is for: every live item captured after
    the previous location message, except one whose place the walker gave
    for it (its own caption, a reply, "#n")."""
    return [it for it in items if it.get("status", "draft") != "dropped"
            and (it.get("captured") or 0) > since_captured
            and not (location_ok(it) and it.get("loc_src") != "group")]


def set_group_location(it: dict, loc: Dict[str, Optional[str]]) -> Dict[str, Any]:
    """Set it (from a group message); what it was, for undo."""
    before = {k: it.get(k) for k in ("floor", "area", "room", "loc_src")}
    for k in ("floor", "area", "room"):
        it.pop(k, None)
    merge_location(it, loc)
    it["loc_src"] = "group"
    return {"captured": it.get("captured"), **before}


def repair_group_locations(items: List[dict], undo: Optional[List[dict]] = None
                           ) -> List[Tuple[Dict[str, Optional[str]], List[int]]]:
    """A walk taken before group locations: each location typed between
    photos was put on the photo just before it. Under the rule it is for
    every photo since the previous one: here it is applied to those that
    have none (never over a place). Returns [(location, numbers set)]."""
    out = []
    pending: List[dict] = []
    for it in sorted((i for i in items if i.get("status", "draft") != "dropped"),
                     key=lambda i: i.get("captured") or 0):
        own = _loc(it.get("said") or it.get("text") or "")
        from_message = location_ok(it) and not (own.get("floor") or own.get("area")) \
            and it.get("loc_src") != "group"
        if not location_ok(it):
            pending.append(it)
            continue
        if from_message and pending:
            loc = {k: it.get(k) for k in ("floor", "area", "room") if it.get(k) not in (None, UNKNOWN)}
            ns = []
            for p in pending:
                before = set_group_location(p, loc)
                if undo is not None:
                    undo.append(before)
                ns.append(p["n"])
            out.append((loc, sorted(ns + [it["n"]])))
            pending = []
        elif from_message:
            pending = []
    return out
