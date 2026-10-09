"""WhatsApp sender mapping: who an unknown group sender is, per company.

Group senders mostly arrive as WhatsApp privacy ids (@lid), which match no
phone on file, so attention items could name nobody. An admin or PM says who
each unknown sender is -- a person's name and their company on the job (one of
the project's subs, or the GC's own team) -- once per company, and every group
of that company uses it.

Stored in `whatsapp_sender_map`:
    {company_id, sender_jid, person_name, sub_company, set_by, set_at}
One row per (company_id, sender_jid). A mapping is never read across
companies: every lookup carries the company.

RAW IDS NEVER LEAVE THE SERVER. The screen gets an opaque `key` per sender
(a hash of company and id) and a label: the sender's WhatsApp display name
when WaAPI sent one, else "Unnamed sender". For a phone sender the last 4
digits may be shown; for an @lid, nothing of the id is.

Pure: no database, no network. server.py reads and writes.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

COLLECTION = "whatsapp_sender_map"

#: The GC's own people, as a company choice beside the project's subs.
GC_TEAM = "GC team"

MAX_NAME = 80
UNNAMED = "Unnamed sender"


def jid_domain(jid: str) -> str:
    raw = str(jid or "")
    return raw.split("@", 1)[1].lower() if "@" in raw else ""


def is_lid(jid: str) -> bool:
    return jid_domain(jid) == "lid"


def sender_key(company_id: Any, jid: str) -> str:
    """The opaque handle the screen uses for a sender. Not reversible, and
    different per company, so a key from one company means nothing in
    another."""
    raw = f"{company_id}|{jid}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def clean_push_name(name: Any) -> str:
    """WaAPI's notifyName, trimmed. Empty when absent or not text."""
    if not isinstance(name, str):
        return ""
    return " ".join(name.split())[:MAX_NAME]


def label(push_name: str, jid: str) -> str:
    """What the screen calls a sender. Never the @lid id, in whole or part."""
    name = clean_push_name(push_name)
    if name:
        return name
    if not is_lid(jid) and jid_domain(jid) in ("c.us", "s.whatsapp.net"):
        digits = "".join(ch for ch in jid.split("@")[0] if ch.isdigit())
        if len(digits) >= 4:
            return f"{UNNAMED} …{digits[-4:]}"
    return UNNAMED


def company_choices(project: Optional[dict]) -> List[str]:
    """The project's active subs (by company name, once each, in roster
    order), then the GC team."""
    out: List[str] = []
    seen = set()
    for row in (project or {}).get("trade_assignments") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").strip().lower() == "inactive":
            continue
        name = " ".join(str(row.get("company") or "").split())
        if name and name.lower() not in seen and name.lower() != GC_TEAM.lower():
            seen.add(name.lower())
            out.append(name)
    out.append(GC_TEAM)
    return out


def validate(person_name: Any, sub_company: Any, choices: List[str]) -> Dict[str, str]:
    """{person_name, sub_company} or ValueError with what to fix.

    The company must be one the screen offered: a project sub or the GC team,
    matched case-insensitively and stored in the roster's spelling."""
    name = " ".join(str(person_name or "").split())
    if not name:
        raise ValueError("Enter the person's name.")
    if len(name) > MAX_NAME:
        raise ValueError(f"Keep the name under {MAX_NAME} characters.")
    want = " ".join(str(sub_company or "").split()).lower()
    match = next((c for c in choices if c.lower() == want), None)
    if not match:
        raise ValueError("Pick the company from the list.")
    return {"person_name": name, "sub_company": match}


def owner_from_map(row: Dict[str, Any]) -> Dict[str, Any]:
    """The resolved-owner fields an attention item carries for a mapped
    sender. `jid`, `source` and `owner_text` stay as the item had them."""
    return {
        "kind": "sender_map",
        "id": str(row.get("_id") or ""),
        "name": row.get("person_name") or "",
        "sub_company": row.get("sub_company") or "",
        "status": "resolved",
        "reason": None,
    }


UNMAPPED_OWNER = {
    "kind": "none", "id": None, "name": "", "sub_company": None,
    "status": "unresolved", "reason": "lid_unmapped",
}


def summarize(rows: Iterable[Dict[str, Any]], group_names: Dict[str, str]
              ) -> Dict[str, Dict[str, Any]]:
    """Message rows -> per sender JID: count, last message time, the groups
    they wrote in, and their most recent display name.

    Rows are whatsapp_messages documents (sender_jid or sender, group_id,
    created_at/timestamp, sender_name). The bot's own rows are skipped."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if str(r.get("sender") or "") == "bot" or r.get("from_me"):
            continue
        jid = _row_jid(r)
        if not jid:
            continue
        at = r.get("created_at") or r.get("timestamp")
        s = out.setdefault(jid, {"jid": jid, "message_count": 0,
                                 "last_message_at": None, "groups": {},
                                 "push_name": "", "_name_at": None})
        s["message_count"] += 1
        gid = str(r.get("group_id") or "")
        if gid:
            s["groups"][gid] = group_names.get(gid) or ""
        if isinstance(at, datetime) and (s["last_message_at"] is None
                                         or _naive(at) > _naive(s["last_message_at"])):
            s["last_message_at"] = at
        name = clean_push_name(r.get("sender_name"))
        if name and isinstance(at, datetime) and (
                s["_name_at"] is None or _naive(at) >= _naive(s["_name_at"])):
            s["push_name"], s["_name_at"] = name, at
        elif name and not s["push_name"]:
            s["push_name"] = name
    for s in out.values():
        s.pop("_name_at", None)
    return out


def _row_jid(r: Dict[str, Any]) -> str:
    jid = str(r.get("sender_jid") or "").strip()
    if "@" in jid:
        return jid
    digits = "".join(ch for ch in str(r.get("sender") or "") if ch.isdigit())
    if not digits:
        return ""
    return f"{digits}@lid" if len(digits) >= 14 else f"{digits}@c.us"


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt
