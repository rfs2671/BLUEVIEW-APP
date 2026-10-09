"""Sub chasing v1: the rules, in pure code. SHADOW MODE: nothing here sends.

What would be chased, when, and in what words. The worker in server.py
(`_chase_tick`) reads attention items, applies these rules and records each
nudge it WOULD send in `chase_shadow` for an admin to mark Correct / Wrong
(Project → WhatsApp → Would chase). It never calls a send function.

WHAT IS CHASED (all of these):
- an open or rescheduled commitment or request;
- its owner confirmed: resolved, not "possibly theirs";
- the owner is a SUB: mapped in Project → WhatsApp → People to one of the
  project's subs. GC staff are never chased in a group: a Levelog user of
  the company, or a person mapped to "GC team";
- an explicit due date the code read from the words ("Friday", "10/12");
- nothing about it flagged for an admin's review, and the item itself not
  marked Wrong (or dismissed) by an admin;
- extracted under prompt att-v1.2 or later.

WHEN, ON THE DUE DAY ONLY (New York): 8:30 morning, 12:30 midday, 3:00 end
of day (NYC sites wrap up around 3:30), each only when nothing came back since
the last nudge. After the end of day nudge, 4:00: a private DM to the company
admin. Constants for now; per-company settings later. An item said after a
slot's time is first chased at the next slot. A slot outside the project's
alert hours is not sent; one that comes due later the same day, inside them,
is.

STOP, immediately: any change to the item after its first nudge (done,
rescheduled, cancelled, possibly done, a part done, a flag), or any message
from the owner in that group since the last nudge.

HOW: in the item's own group, @mentioning the owner, quoting the original
message (after a handover, the message of who took it on). At most one nudge per owner per group per slot: their items due
today go in one message. The words are a fixed template and the item's own
quote. No model writes any of it.

WEEKENDS: Saturday and Sunday only for a project with "Chase on weekends" on
(Project → WhatsApp → Levelog Assistant; default off). All four slots.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = None

COLLECTION = "chase_shadow"

MORNING, MIDDAY, EOD, ADMIN = "morning", "midday", "eod", "admin_dm"
# (slot, New York time), in order.
SLOTS = ((MORNING, time(8, 30)), (MIDDAY, time(12, 30)), (EOD, time(15, 0)),
         (ADMIN, time(16, 0)))
GROUP_SLOTS = (MORNING, MIDDAY, EOD)
SLOT_LABELS = {MORNING: "morning", MIDDAY: "midday", EOD: "end of day",
               ADMIN: "admin DM"}

CHASE_TYPES = ("commitment", "request")
CHASE_STATUSES = ("open", "rescheduled")
# Subs only: a company user is GC staff, and so is a person mapped "GC team".
OWNER_KINDS = ("sender_map",)
GC_KINDS = ("user",)
QUOTE_MAX = 200
VERDICTS = ("correct", "wrong")
# Items extracted under an older prompt are never chased.
MIN_PROMPT = "att-v1.2"


def disabled() -> bool:
    """The kill switch: WA_CHASE_DISABLED=1 stops the worker entirely."""
    return str(os.environ.get("WA_CHASE_DISABLED", "")).strip().lower() in (
        "1", "true", "yes", "on")


def local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_ET) if _ET else dt


def today(now: datetime) -> date:
    return local(now).date()


def slot_at(day: date, slot: str) -> datetime:
    """When a slot is on a day, in UTC."""
    t = dict(SLOTS)[slot]
    at = datetime.combine(day, t)
    at = at.replace(tzinfo=_ET) if _ET else at.replace(tzinfo=timezone.utc)
    return at.astimezone(timezone.utc)


def current_slot(now: datetime) -> Optional[str]:
    """The latest slot whose time has come today (New York), else None.
    An earlier slot that was missed is not sent late once a later one is
    due: one nudge per slot, never two at once."""
    t = local(now).time()
    hit = None
    for name, at in SLOTS:
        if t >= at:
            hit = name
    return hit


def chases_on(day: date, settings: Dict[str, Any]) -> bool:
    """Saturday and Sunday only when the project's "Chase on weekends" is
    on (default off). All four slots."""
    return day.weekday() < 5 or bool((settings or {}).get("chase_weekends"))


def owner_key(item: Dict[str, Any]) -> str:
    o = item.get("owner") or {}
    return f"{o.get('kind')}:{o.get('id')}"


def skip_reason(item: Dict[str, Any], day: date) -> Optional[str]:
    """Why this item is not chased today, or None when it is eligible."""
    if item.get("type") not in CHASE_TYPES:
        return "type"
    if item.get("status") not in CHASE_STATUSES:
        return "status"
    if item.get("needs_review"):
        return "flagged_for_review"
    if not _prompt_ok(item):
        return "old_prompt"             # extracted before att-v1.2
    if (item.get("review") or {}).get("verdict") in ("wrong", "dismissed"):
        return "reviewed_wrong"         # an admin rejected the item itself
    o = item.get("owner") or {}
    if o.get("status") != "resolved" or not o.get("id"):
        return "owner_unconfirmed"
    if o.get("possibly"):
        return "owner_possibly"
    if is_gc_staff(o):
        return "gc_staff"
    if o.get("kind") not in OWNER_KINDS:
        return "owner_not_known"
    if not o.get("jid"):
        return "owner_no_mention"
    due = item.get("due") or {}
    if not due.get("due_text") or not due.get("due_at"):
        return "no_explicit_due"
    if str(due.get("due_at"))[:10] != day.isoformat():
        return "not_due_today"
    return None


def is_gc_staff(owner: Dict[str, Any]) -> bool:
    """A company user, or someone mapped in People to "GC team"."""
    from lib import wa_sender_map
    o = owner or {}
    if o.get("kind") in GC_KINDS:
        return True
    return (o.get("kind") == "sender_map" and " ".join(
        str(o.get("sub_company") or "").split()).lower() == wa_sender_map.GC_TEAM.lower())


def _prompt_ok(item: Dict[str, Any]) -> bool:
    from lib import wa_attention
    return wa_attention.prompt_at_least(
        (item.get("extraction") or {}).get("prompt_version"), MIN_PROMPT)


def _at(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def said_at(item: Dict[str, Any]) -> Optional[datetime]:
    return _at((item.get("evidence") or {}).get("sent_at"))


def stop_reason(item: Dict[str, Any], nudges: List[Dict[str, Any]],
                owner_spoke_at: Optional[datetime]) -> Optional[str]:
    """Why chasing this item stopped today, or None.

    `nudges`: today's earlier would-chase rows for this item, any order.
    `owner_spoke_at`: the owner's latest message in the group, if any."""
    times = sorted(t for t in (_at(n.get("at")) for n in nudges) if t)
    if not times:
        return None
    first, last = times[0], times[-1]
    for e in item.get("history") or []:
        if not isinstance(e, dict) or e.get("kind") in (None, "created"):
            continue
        at = _at(e.get("at"))
        if at and at > first:
            return f"state_change:{e.get('kind')}"
    if owner_spoke_at and owner_spoke_at > last:
        return "owner_replied"
    return None


def quoted(item: Dict[str, Any]) -> Dict[str, Any]:
    """The message a nudge quotes: after a handover, the words of who took
    it on ("I'll send the risers Friday"); otherwise the item's own. The
    original stays the item's evidence and history."""
    q = item.get("chase_quote") or {}
    if q.get("quote") and q.get("message_id"):
        return q
    return item.get("evidence") or {}


def quote(item: Dict[str, Any]) -> str:
    q = " ".join(str(quoted(item).get("quote") or "").split())
    return q if len(q) <= QUOTE_MAX else q[:QUOTE_MAX - 1].rstrip() + "…"


def hhmm(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    s = local(dt).strftime("%I:%M")
    return s[1:] if s.startswith("0") else s


_OPENERS = {
    MORNING: ("morning — this is due today:", "morning — these are due today:"),
    MIDDAY: ("checking in — still on for today?", "checking in on these, due today:"),
    EOD: ("end of day — did this get done?", "end of day — did these get done?"),
}


def group_text(owner_name: str, items: List[Dict[str, Any]], slot: str) -> str:
    """The group message: @owner, a fixed line, the item quote(s)."""
    one, many = _OPENERS[slot]
    who = owner_name.strip() or "there"
    lines = [f"@{who} {one if len(items) == 1 else many}"]
    lines += [f"“{quote(it)}”" for it in items]
    return "\n".join(lines)


def admin_text(owner_name: str, group_name: str, items: List[Dict[str, Any]],
               nudged_at: List[datetime]) -> str:
    """The private DM to the company admin after the end of day nudge."""
    who = owner_name.strip() or "The owner"
    where = f" in {group_name}" if group_name else ""
    what = "this" if len(items) == 1 else f"these {len(items)}"
    lines = [f"{who} hasn't answered on {what}, due today{where}:"]
    lines += [f"“{quote(it)}”" for it in items]
    times = [hhmm(t) for t in sorted(nudged_at)]
    if times:
        lines.append("Nudged in the group at " + _join(times) + ".")
    return "\n".join(lines)


def _join(parts: List[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def reason(slot: str, items: List[Dict[str, Any]], last_nudge: Optional[datetime],
           day: date) -> str:
    """Why it fired, for the reviewer."""
    dues = sorted({str((it.get("due") or {}).get("due_text") or "") for it in items} - {""})
    due = f"due today ({', '.join(dues)})" if dues else "due today"
    Due = "D" + due[1:]
    if slot == ADMIN:
        return (f"Still no update after the end of day nudge; {due}. "
                "Owner confirmed.")
    if last_nudge:
        return f"{Due}; no update and no message from the owner since the {hhmm(last_nudge)} nudge."
    said = [hhmm(said_at(it)) for it in items if said_at(it)]
    since = f" since it was said at {said[0]}" if len(said) == 1 else ""
    return f"{Due}; owner confirmed; no update{since}."


def row_id(day: date, group_id: str, okey: str, slot: str) -> str:
    """One row per owner per group per slot per day: a re-run never adds a
    second nudge."""
    return f"{day.isoformat()}|{group_id}|{okey}|{slot}"


def precision(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """correct, wrong, unreviewed, precision = correct / (correct + wrong),
    overall and per slot."""
    def blank():
        return {"correct": 0, "wrong": 0, "unreviewed": 0}
    total, by_slot = blank(), {}
    for r in rows:
        v = (r.get("review") or {}).get("verdict")
        k = v if v in VERDICTS else "unreviewed"
        total[k] += 1
        by_slot.setdefault(r.get("slot") or "other", blank())[k] += 1

    def done(row):
        judged = row["correct"] + row["wrong"]
        row["precision"] = round(row["correct"] / judged, 3) if judged else None
        return row
    return {**done(total), "by_slot": {k: done(v) for k, v in by_slot.items()}}


def digits(jid: str) -> str:
    return re.sub(r"\D", "", str(jid or "").split("@")[0])
