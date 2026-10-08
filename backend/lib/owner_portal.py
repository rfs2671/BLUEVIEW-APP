"""Owner portal: the pure rules behind company admins and Deleted items.

PLATFORM OPERATOR ONLY. The endpoints in server.py own the gate (404 for
everyone else) and the reads and writes; this module decides, from documents
already read, what a row says and whether a change is allowed. Nothing here
touches the database.

── WHAT "DELETED" MEANS HERE ───────────────────────────────────────────────

  company  `is_deleted: true`.
  user     `is_deleted: true` (written by server._mark_user_deleted).
  project  EITHER `is_deleted: true` (legacy soft delete) OR
           `marked_for_deletion: true` (an admin's delete, Tier 1). Both are
           listed, labeled, because both hide the project from its company.

── DELETED TOGETHER ────────────────────────────────────────────────────────

A delete that hides more than one row stamps every row with the same
`delete_batch_id`; restore brings that batch back. Rows deleted before the
stamp existed carry none and restore only themselves.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List, Optional

KINDS = ("company", "project", "user")

#: What a hard delete would be blocked on until the delete service is fixed.
HARD_DELETE_PENDING = "Pending delete-service fix"


def new_batch_id() -> str:
    return uuid.uuid4().hex


def project_deleted_state(doc: Dict[str, Any]) -> Optional[str]:
    """'deleted' (legacy soft delete), 'marked' (admin marked it), or None."""
    if doc.get("is_deleted") is True:
        return "deleted"
    if doc.get("marked_for_deletion") is True:
        return "marked"
    return None


def deleted_by_of(doc: Dict[str, Any]) -> Optional[str]:
    """Who deleted it, as stored. Projects marked by an admin carry `marked_by`."""
    return doc.get("deleted_by") or doc.get("marked_by") or None


def deleted_at_of(doc: Dict[str, Any]):
    return doc.get("deleted_at") or doc.get("marked_at") or None


def _label(kind: str, doc: Dict[str, Any]) -> str:
    if kind == "project":
        name = (doc.get("name") or "").strip()
        addr = (doc.get("address") or "").strip()
        if name and addr and name != addr:
            return f"{name} — {addr}"
        return name or addr or str(doc.get("_id") or doc.get("id") or "")
    if kind == "user":
        name = (doc.get("name") or doc.get("full_name") or "").strip()
        email = (doc.get("email") or "").strip()
        if name and email:
            return f"{name} ({email})"
        return name or email or str(doc.get("_id") or doc.get("id") or "")
    return (doc.get("name") or "").strip() or str(doc.get("_id") or doc.get("id") or "")


def deleted_row(kind: str, doc: Dict[str, Any], *,
                company_names: Dict[str, str],
                people: Dict[str, str]) -> Dict[str, Any]:
    """One row of the Deleted items tab.

    `company_names` maps company id -> name; `people` maps user id -> a
    display name. A company or person that cannot be resolved is shown by id
    rather than blank, so a missing name never reads as "nobody".
    """
    rid = str(doc.get("_id") or doc.get("id") or "")
    if kind == "company":
        company_id = rid
    else:
        company_id = str(doc.get("company_id") or "")
    by = deleted_by_of(doc)
    state = project_deleted_state(doc) if kind == "project" else "deleted"
    return {
        "kind": kind,
        "id": rid,
        "name": _label(kind, doc),
        "company_id": company_id or None,
        "company_name": (company_names.get(company_id) if company_id else None)
                        or (company_id or None),
        "deleted_by": by,
        "deleted_by_name": (people.get(str(by)) or str(by)) if by else None,
        "deleted_at": deleted_at_of(doc),
        "state": state,
        "role": doc.get("role") if kind == "user" else None,
        "batch_id": doc.get("delete_batch_id"),
        "hard_delete": {"enabled": False, "reason": HARD_DELETE_PENDING},
    }


def sort_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Newest deletion first; rows without a date last."""
    def key(r):
        at = r.get("deleted_at")
        return (at is not None, str(at) if at is not None else "")
    return sorted(rows, key=key, reverse=True)


def is_admin(user: Dict[str, Any]) -> bool:
    return str(user.get("role") or "").strip().lower() == "admin"


def leaves_no_admin(users: Iterable[Dict[str, Any]], user_id: str,
                    new_role: Optional[str] = None) -> bool:
    """Would this change leave the company with no live admin?

    `new_role=None` means the user is being removed. Only live (not deleted)
    users count. A change to a user who is not an admin never trips it.
    """
    uid = str(user_id)
    live = [u for u in users if u.get("is_deleted") is not True]
    target = next((u for u in live if str(u.get("_id") or u.get("id")) == uid), None)
    if target is None or not is_admin(target):
        return False
    if new_role is not None and str(new_role).strip().lower() == "admin":
        return False
    others = [u for u in live
              if is_admin(u) and str(u.get("_id") or u.get("id")) != uid]
    return not others


def user_row(u: Dict[str, Any]) -> Dict[str, Any]:
    """A company user as the operator's company screen shows it. No secrets."""
    return {
        "id": str(u.get("_id") or u.get("id") or ""),
        "name": u.get("name") or u.get("full_name") or "",
        "email": u.get("email") or "",
        "role": u.get("role") or "",
        "phone": u.get("phone") or None,
        "account_status": u.get("account_status"),
        "created_at": u.get("created_at"),
    }


def sort_users(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Admins first, then by name."""
    return sorted(rows, key=lambda r: (r.get("role") != "admin",
                                       (r.get("name") or r.get("email") or "").lower()))


def restore_set(now, operator_id: str) -> Dict[str, Any]:
    return {"is_deleted": False, "updated_at": now,
            "restored_at": now, "restored_by": operator_id}


#: Fields a restore removes, per kind. A project's marked_* go too: restoring
#: a marked project is un-marking it.
RESTORE_UNSET = {
    "company": ("deleted_at", "deleted_by", "delete_batch_id"),
    "user": ("deleted_at", "deleted_by", "delete_batch_id", "deleted_user_ref"),
    "project": ("deleted_at", "deleted_by", "delete_batch_id",
                "marked_by", "marked_at"),
}
