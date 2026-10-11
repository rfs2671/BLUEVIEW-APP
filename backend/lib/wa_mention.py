"""Real WhatsApp @mentions in group posts, the rules in pure code.

WaAPI's send-message tags a person only when BOTH hold:
    "message":  "… @15551234567 …"          (the number, after an @)
    "mentions": ["15551234567@c.us"]         (groups only; ^[0-9]{7,}@c\\.us$)
"@Carlos" alone is plain text: nobody's phone buzzes.

So every group post that names a person (chase nudges, punch sends, any
later one) is built from a TARGET: who it is and, when known, their phone.
`handle()` writes the token -- "@15551234567" when the phone is known, else
"@Carlos" -- and `mentions_for()` lists exactly the numbers whose tokens are
in the text. `check()` refuses a mismatch either way: a number in mentions
with no token in the text, or a token whose number is not in mentions.

Where the phone comes from is server.py's job (a Levelog user's phone, the
People mapping's phone, else WaAPI's get-lid lookup -- batched, 50 ids a
call -- cached per company and refreshed weekly). An unresolved person keeps the plain "@Name": the post
still names them; it just won't notify, and the screens say so.

Nothing here touches the network or the database.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

#: The jid WaAPI accepts in `mentions`.
MENTION_JID = re.compile(r"^[0-9]{7,}@c\.us$")
#: WaAPI's lid <-> phone action: POST …/client/action/get-lid with
#: {"contactIds": [...]}, many ids per call.
LID_ACTION = "get-lid"
#: Ids per get-lid call.
LOOKUP_CHUNK = 50
#: How long a lid -> phone answer (or "no number") is trusted.
LOOKUP_TTL_DAYS = 7
LOOKUP_COLLECTION = "whatsapp_lid_phone"
#: What the screens say beside a mention that will not notify.
NO_NUMBER_NOTE = "mention won't notify (no number)"


def phone(raw: Any) -> Optional[str]:
    """A WhatsApp number from a stored phone or a @c.us jid: digits only,
    with the US country code when it was left off ("(718) 555-0100" ->
    "17185550100"). None when it is not a usable number (or is an @lid)."""
    s = str(raw or "").strip()
    if not s:
        return None
    if "@" in s:
        head, _, dom = s.partition("@")
        if dom.lower() not in ("c.us", "s.whatsapp.net"):
            return None
        s = head
    d = re.sub(r"\D", "", s)
    if len(d) == 10:
        d = "1" + d
    return d if 7 <= len(d) <= 15 else None


def jid(number: str) -> str:
    return f"{number}@c.us"


def handle(name: Any, number: Optional[str]) -> str:
    """The token for one person: "@15551234567" (a real mention) or "@Carlos"."""
    if number:
        return f"@{number}"
    who = " ".join(str(name or "").split()) or "there"
    return f"@{who}"


def target(name: Any, number: Optional[str], source: str = "none") -> Dict[str, Any]:
    """One person a post names: {name, phone, source, handle, resolved}."""
    n = phone(number) if number else None
    return {"name": " ".join(str(name or "").split()), "phone": n,
            "source": source if n else "none", "handle": handle(name, n),
            "resolved": bool(n)}


def tokens(text: str) -> List[str]:
    """The numbers the text @-mentions, in order, once each."""
    seen: List[str] = []
    for m in re.finditer(r"(?<![\w@])@(\d{7,15})(?!\d)", str(text or "")):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def mentions_for(text: str, targets: Iterable[Dict[str, Any]]) -> List[str]:
    """The `mentions` array: the jid of every resolved target whose token is
    in the text, in the order the text names them."""
    known = {t["phone"] for t in targets if t.get("phone")}
    return [jid(n) for n in tokens(text) if n in known]


def check(text: str, mentions: List[str]) -> Optional[str]:
    """None when text and mentions agree; else what is wrong."""
    for m in mentions:
        if not MENTION_JID.match(str(m)):
            return f"bad jid {m!r}"
    nums = [m.split("@")[0] for m in mentions]
    in_text = tokens(text)
    missing = [n for n in nums if n not in in_text]
    if missing:
        return f"mentioned but not in the text: {len(missing)}"
    extra = [n for n in in_text if n not in nums]
    if extra:
        return f"in the text but not mentioned: {len(extra)}"
    return None


def display(text: str, targets: Iterable[Dict[str, Any]]) -> str:
    """The post as a person reads it in the app: each "@<number>" back to
    "@Name" (WhatsApp shows the name; the app never shows the number)."""
    out = str(text or "")
    for t in targets:
        if t.get("phone"):
            out = re.sub(r"(?<![\w@])@" + re.escape(t["phone"]) + r"(?!\d)",
                         "@" + (t.get("name") or "there"), out)
    return out


def sent_ok(resp: Any) -> bool:
    """WaAPI accepted the send: data.status == "success"."""
    data = (resp or {}).get("data") if isinstance(resp, dict) else None
    return isinstance(data, dict) and str(data.get("status") or "").lower() == "success"


def lookup_body(lids: Iterable[str]) -> Dict[str, Any]:
    """WaAPI get-lid's body: {"contactIds": ["<num>@lid", …]}."""
    return {"contactIds": list(lids)}


def chunks(items: List[str], size: int = LOOKUP_CHUNK) -> List[List[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def phones_from_lookup(resp: Any, asked: Iterable[str]) -> Optional[Dict[str, Optional[str]]]:
    """WaAPI get-lid's answer -> {lid: phone or None} for every id asked, or
    None when the call did not succeed (data.status != "success": nothing
    learned, nothing to cache).

    The answer is data.data.contacts = [{"lid": "…@lid", "pn": "<digits>@c.us"}].
    An asked lid with no contact, or a contact with no pn, has no number."""
    if not sent_ok(resp):
        return None
    inner = (resp.get("data") or {}).get("data") or {}
    contacts = inner.get("contacts") if isinstance(inner, dict) else None
    out: Dict[str, Optional[str]] = {str(l): None for l in asked}
    for c in contacts if isinstance(contacts, list) else []:
        if not isinstance(c, dict):
            continue
        lid = str(c.get("lid") or "")
        if lid in out:
            out[lid] = phone(c.get("pn")) if c.get("pn") else None
    return out
