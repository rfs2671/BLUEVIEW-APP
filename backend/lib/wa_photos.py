"""Photos posted in a linked job group, kept.

Every image sent in a group linked to a job is downloaded in full (WhatsApp's
CDN, else WaAPI -- the same capture as punch photos) and stored in R2 under the
company and the job, on its message row (`whatsapp_messages.photo`):

    {"key", "quality" (original / preview), "caption", "sender_company",
     "sender_name", "company_how", "shared", "at", "vision": {ok, kind, score,
     caption}}

  * Never for a group that is not linked to a job: nothing of such a group is
    stored at all (the webhook returns before it).
  * The sender's company comes from the company's own records: a user of the
    company is the GC team; a worker who checked in at this job, the company of
    their check-in; else what People (Project → WhatsApp → People) says.
  * The vision model describes it once, at ingest; the memory search and the
    app read that, never asking again.
  * NEVER IN A PROGRESS REPORT: the report's photos are the daily logs'
    only (each already filed under its sub, day and work). These are for the
    search and the Voice & media log.
  * Kept as the message is: the 7-year job rule (wa_retention), and deleted
    with it (retention, project delete) -- by key.
  * Nothing before deploy: WhatsApp's media expires, so old photos can't be
    had.

Pure: no database, no network.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

PREFIX = "wa-group-photos"
#: The vision call's metering name (lib/vision_meter.py).
VISION_ENDPOINT = "group_photo_describe"


def _safe(v: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(v or "x"))[:80] or "x"


def key(company_id: Any, project_id: Any, message_id: Any) -> str:
    """wa-group-photos/<company>/<job>/<message>.jpg"""
    return f"{PREFIX}/{_safe(company_id)}/{_safe(project_id)}/{_safe(message_id)}.jpg"


def is_group_photo_key(k: Any) -> bool:
    return str(k or "").startswith(PREFIX + "/")


def caption(body: Any) -> str:
    """The words sent with a photo. An image with no caption can arrive with
    its base64 thumbnail as the body: that is not words."""
    b = " ".join(str(body or "").split())
    if len(b) > 200 and " " not in b:
        return ""
    return b[:500]


def doc(photo_key: str, quality: Optional[str], caption_text: str, *, sender_company: str = "",
        sender_name: str = "", company_how: str = "", shared: bool = False, at: Any = None,
        media_ref: Optional[dict] = None) -> Dict[str, Any]:
    return {"key": photo_key, "quality": quality or "original", "caption": caption_text,
            "sender_company": sender_company, "sender_name": sender_name,
            "company_how": company_how, "shared": bool(shared), "at": at,
            "media_ref": media_ref or None, "vision": None}


def search_text(row: Dict[str, Any]) -> str:
    """What the memory search reads for a photo row: its caption, and what
    the vision model saw ("Photo: metal stud framing on the 3rd floor")."""
    p = row.get("photo") or {}
    parts = []
    if p.get("caption"):
        parts.append(p["caption"])
    seen = ((p.get("vision") or {}).get("caption") or "").strip()
    if seen:
        parts.append(f"Photo: {seen}")
    elif p.get("key") and not parts:
        parts.append("Photo")
    return " — ".join(parts)


def owned_keys(row: Dict[str, Any]) -> list:
    """The R2 objects deleting this row deletes: its own group photo (never a
    punch completion photo it shares with a punch item)."""
    p = row.get("photo") or {}
    k = p.get("key")
    return [k] if k and not p.get("shared") and is_group_photo_key(k) else []


def log_row(row: Dict[str, Any], *, who: str, place: str, at: Any, photo_url: str = "") -> Dict[str, Any]:
    """A group photo for Project → WhatsApp → Voice & media log. No phone
    number."""
    p = row.get("photo") or {}
    v = p.get("vision") or {}
    return {"id": str(row.get("_id")), "kind": "photo", "where": "group", "place": place, "at": at,
            "who": who, "company": p.get("sender_company") or "", "caption": p.get("caption") or "",
            "seen": v.get("caption") or "", "quality": p.get("quality"),
            "status": "not_captured" if p.get("failed") or not p.get("key") else "kept",
            "photo_url": photo_url, "forwarded": bool(row.get("forwarded")), "lang": None,
            "audio": False, "message_row_id": str(row.get("_id")), "produced": []}
