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
COUNTERS = "punch_counters"

STATUSES = ("draft", "open", "ready_to_check", "closed", "dropped")
LIVE = ("open",)                       # what the chase engine chases
SEND_MODES = ("shadow", "live")
DEFAULT_SEND_MODE = "shadow"
DRAFT_REMIND_HOURS = 24
UNKNOWN = "?"

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


def new_item(n: int, words: str, *, photo_key: Optional[str], message_id: str,
             voice: Optional[dict] = None, at: Any = None) -> Dict[str, Any]:
    """One captured item: the photo, its words EXACTLY as written or said,
    and what the words name (or "?")."""
    w = str(words or "").strip()
    return {
        "n": n,
        "text": w,
        "photo_key": photo_key,
        "message_id": message_id,
        "voice": voice or None,
        "captured": n,                  # the order it came in; `n` follows the draft
        "floor": read_floor(w) or UNKNOWN,
        "area": read_area(w) or UNKNOWN,
        "trade": read_trade(w) or UNKNOWN,
        "at": at,
    }


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


def renumber(items: List[dict]) -> List[dict]:
    """Numbers follow the list: 1, 2, 3 … in the order the draft shows."""
    for i, it in enumerate(ordered(items), 1):
        it["n"] = i
    return items


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
    area = it.get("area")
    where = f" ({area})" if area and area != UNKNOWN and area != it.get("floor") else ""
    return f"{it['n']}. {marker(it)} {words}{where} — {trade}".replace("  ", " ")


def draft_text(job_name: str, items: List[dict], sent_mode: str = DEFAULT_SEND_MODE) -> str:
    """The draft the walker sees: by floor, then trade, numbered."""
    live = [it for it in items if it.get("status", "draft") != "dropped"]
    renumber(live)
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
        items.append({**new_item(next_n, e["text"], photo_key=None, message_id=""), "added": True})
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
        it["trade"] = e["trade"]
    elif e["op"] == "drop":
        it["status"] = "dropped"
    elif e["op"] == "floor":
        it["floor"] = e["floor"]
    elif e["op"] == "area":
        it["area"] = e["area"]
    return True, f"{e['op']} {e['n']}"


# ── ASSIGNING ────────────────────────────────────────────────────────────────

def suggest_assignees(trades: Iterable[str], people: List[Dict[str, Any]]) -> Dict[str, Optional[dict]]:
    """trade -> the one company/person on this job for it (from check-ins and
    People), or None when there is none or more than one."""
    out: Dict[str, Optional[dict]] = {}
    for t in trades:
        if t == UNKNOWN:
            continue
        hits = [p for p in people if t in (p.get("trades") or [])]
        # One per company: two people of the same company are one choice.
        by_co: Dict[str, dict] = {}
        for p in hits:
            by_co.setdefault(multilang.fold(p.get("company") or p.get("name") or ""), p)
        out[t] = next(iter(by_co.values())) if len(by_co) == 1 else None
    return out


def assign_text(sugg: Dict[str, Optional[dict]]) -> str:
    lines = ["Who gets what?"]
    for t, p in sorted(sugg.items()):
        lines.append(f"• {t} → {p['name']}{(' (' + p['company'] + ')') if p.get('company') else ''}"
                     if p else f"• {t} → ?")
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


def pick_person(name: str, people: List[Dict[str, Any]]) -> Optional[dict]:
    """The one person / company a name means (first name, full name or company)."""
    n = multilang.fold(name).strip()
    if not n:
        return None
    hits = [p for p in people
            if n in (multilang.fold(p.get("name") or ""), multilang.fold(p.get("company") or ""))
            or multilang.fold(p.get("name") or "").split(" ")[:1] == [n]]
    uniq = {id(p): p for p in hits}
    return next(iter(uniq.values())) if len(uniq) == 1 else None


def due_date(words: str, sent_at):
    """The day a due answer names (Spanish / Yiddish read as English)."""
    from lib import wa_attention
    return wa_attention.parse_due(multilang.normalize_when(words), sent_at)


DUE_QUESTION = "Due Fri for all, or by trade? (e.g. \"Fri\", or \"electrical Mon, paint Fri\")"


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
        words = re.sub(r"^\s*(?:all|todo|todos|everything)\s+", "", part, flags=re.IGNORECASE)
        if wa_attention.parse_due(multilang.normalize_when(words), probe):
            for t2 in ts:
                out.setdefault(t2, words)
    return out or None


# ── SENDING ──────────────────────────────────────────────────────────────────

def group_text(name: str, items: List[dict], due_words: str) -> str:
    """One message per assignee: @them, their items, the due day."""
    lines = [f"@{name} punch list — due {due_words}:"]
    for it in items:
        where = " · ".join(x for x in (floor_label(it["floor"]) if it.get("floor") not in (None, UNKNOWN) else "",
                                        it.get("area") if it.get("area") not in (None, UNKNOWN) else "") if x)
        lines.append(f"• {it['pid']} {it.get('text') or ''}{(' (' + where + ')') if where else ''}")
    lines.append("Reply \"done P23\" (a photo helps) when each one is finished.")
    return "\n".join(lines)


def shadow_text(batches: List[Dict[str, Any]]) -> str:
    """What the walker sees while sends are in shadow: what WOULD be posted."""
    lines = ["Punch sends are in shadow mode: nothing was posted. Would send:"]
    for b in batches:
        lines.append("")
        lines.append(group_text(b["name"], b["items"], b["due_words"]))
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
    if m and ("punch" in t.lower() or m.group("floor") or m.group("job")):
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
