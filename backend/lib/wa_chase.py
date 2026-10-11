"""Sub chasing v1: the rules, in pure code. SHADOW MODE: nothing here sends.

What would be chased, when, and in what words. The worker in server.py
(`_chase_tick`) reads attention items, applies these rules and records each
nudge it WOULD send in `chase_shadow` for an admin to mark Correct / Wrong
(Project → WhatsApp → Would chase). It never calls a send function.

WHAT IS CHASED (all of these):
- an open or rescheduled commitment or request;
- its owner confirmed: resolved, not "possibly theirs";
- the owner is anyone we can @mention: a sub (mapped in Project → WhatsApp
  → People to one of the project's subs), GC staff (a Levelog user of the
  company, PM, super or admin, or a person mapped to "GC team") and a worker
  who checked in at the project alike. No opt-in is needed: everyone is
  chased the same way, in the group. An owner with no WhatsApp number to
  @mention is listed once a day, every item of theirs that would have been
  chased, "not chased: no WhatsApp number on file";
- an explicit due date the code read from the words ("Friday", "10/12");
- nothing about it flagged for an admin's review, and the item itself not
  marked Wrong (or dismissed) by an admin;
- extracted under prompt att-v1.2 or later.

WHEN, ON THE DUE DAY ONLY (New York): 8:30 morning, 12:30 midday, 3:00 end
of day (NYC sites wrap up around 3:30), each only when nothing came back since
the last nudge. After the end of day nudge, 4:00: a private DM to the company
admins except the owner; an owner who is the only admin gets none. Constants for now; per-company settings later. An item said after a
slot's time is first chased at the next slot. A slot outside the project's
alert hours is not sent; one that comes due later the same day, inside them,
is.

STOP, for the day: any change to the item after its first nudge (done,
rescheduled, cancelled, possibly done, a part done, a flag, a handover).

SKIP ONE SLOT -- the next one only; later slots still run unless the item
changes -- when, since the last nudge (or the last skip), the owner:
  * replies to the nudge or to the item's own message (WhatsApp reply);
  * writes about it: a subject word of the item ("risers by 2");
  * acknowledges, within 15 minutes of a nudge, in a short message ("on it",
    "working on it", "later", "dale", "ya voy", "yo", "shpeter").
Anything else the owner says in the group (other work, other chatter) has
no effect: they may well have forgotten. The skipped slot is recorded with
which rule applied ("skipped midday: replied 'working on it' 9:05").

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

from lib import multilang as ml
from lib import wa_attention_state as was

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
# Who can be chased: a person mapped in People (a sub or "GC team"), a
# company user, or a worker who checked in at the project. Everyone in the
# group, @mentioned.
OWNER_KINDS = ("sender_map", "user", "worker")
# Eligible but nobody to @mention: listed, not chased.
NO_MENTION = "owner_no_mention"
NOT_CHASED = "not_chased"
NO_NUMBER = "no WhatsApp number on file"
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
    if o.get("kind") not in OWNER_KINDS:
        return "owner_not_known"
    due = item.get("due") or {}
    if not due.get("due_text") or not due.get("due_at"):
        return "no_explicit_due"
    if str(due.get("due_at"))[:10] != day.isoformat():
        return "not_due_today"
    if not o.get("jid"):
        # Last, so it means "would be chased today, but nobody to @mention".
        return NO_MENTION
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


def stop_reason(item: Dict[str, Any], nudges: List[Dict[str, Any]]) -> Optional[str]:
    """Why chasing this item stopped for the day (rule 1), or None: any
    change to the item after its first nudge today.

    `nudges`: today's earlier group nudges for this item, any order."""
    times = sorted(t for t in (_at(n.get("at")) for n in nudges) if t)
    if not times:
        return None
    first = times[0]
    for e in item.get("history") or []:
        if not isinstance(e, dict) or e.get("kind") in (None, "created"):
            continue
        at = _at(e.get("at"))
        if at and at > first:
            return f"state_change:{e.get('kind')}"
    return None


# ── THE OWNER'S ANSWER (rule 2) ──────────────────────────────────────────────

#: An ack counts only this soon after a nudge.
ACK_MINUTES = 15
SKIPPED = "skipped"
# "On it", "working on it", "later" (and the Spanish / Yiddish for them):
# a short message that is only that. Plain yeses ("ok", "dale", "yo") are
# wa_attention_state.ack's.
_CHASE_ACK = re.compile(
    r"^\W*(?:(?:i'?m |im |i am )?(?:on it|working on it|on my way|omw|getting to it|will do"
    r"|later|in a bit|soon|shortly|asap|in progress)"
    r"|ya voy|voy|en eso|estoy en eso|trabajando en (?:eso|ello)|ahorita|al rato|mas tarde|luego"
    r"|en camino|ahi voy"
    r"|shpeter|bald|ikh arbet (?:oyf|af) dem|ikh bin (?:oyf|af) dem|bin dran|shoyn bald"
    r"|שפעטער|באלד)"
    r"(?:[\s,.!]+(?:boss|bro|jefe|man|thanks|thx|gracias|today|hoy|haynt))*\W*$")


def _ack_said(body: str) -> bool:
    text = str(body or "").strip()
    if not text or len(text) > 40 or "?" in text:
        return False
    return bool(was.ack(text) or _CHASE_ACK.match(ml.fold(text)))


def item_message_ids(item: Dict[str, Any]) -> set:
    """The ids a reply about the item quotes: its own message, and after a
    handover the message of who took it on."""
    ids = {was.short_id((item.get("evidence") or {}).get("message_id")),
           was.short_id((item.get("chase_quote") or {}).get("message_id"))}
    ids.discard("")
    return ids


def owner_response(item: Dict[str, Any], msg: Dict[str, Any],
                   nudges: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What one message of the owner's says about the item, by rule 2:
    {rule: reply|subject|ack, said, at, word?}; None for anything else (it
    has no effect on the chase -- rule 3).

    `msg`: {body, quoted_message_id, at}. `nudges`: today's group nudges
    for the item (a sent one may carry its WhatsApp `message_id`)."""
    body = str(msg.get("body") or "").strip()
    at = _at(msg.get("at"))
    if not body or not at:
        return None
    said = " ".join(body.split())[:60]
    quoted = was.short_id(msg.get("quoted_message_id"))
    if quoted:
        nudge_ids = {was.short_id(n.get("message_id")) for n in nudges} - {""}
        if quoted in item_message_ids(item) or quoted in nudge_ids:
            return {"rule": "reply", "said": said, "at": at}
    words = was.subject_terms(was.topic_terms(body))
    hit = sorted(words & was.subject_terms(item.get("topic") or ()))
    if hit:
        return {"rule": "subject", "said": said, "at": at, "word": hit[0]}
    if _ack_said(body):
        for n in nudges:
            t = _at(n.get("at"))
            if t and t <= at <= t + timedelta(minutes=ACK_MINUTES):
                return {"rule": "ack", "said": said, "at": at}
    return None


_RULE_WORDS = {"reply": "replied", "subject": "wrote about it", "ack": "acknowledged"}


def skip_text(slot: str, resp: Dict[str, Any]) -> str:
    """The Why line of a skipped slot: "Skipped midday: replied 'working on
    it' 9:05" / "Skipped end of day: wrote about it ('risers') 'risers by
    2' 1:40"."""
    what = _RULE_WORDS.get(resp.get("rule"), "answered")
    if resp.get("rule") == "subject" and resp.get("word"):
        what += f" ('{resp['word']}')"
    return (f"Skipped {SLOT_LABELS.get(slot, slot)}: {what} '{resp.get('said') or ''}' "
            f"{hhmm(resp.get('at'))}. Later slots still run.")


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


def group_text(owner_name: str, items: List[Dict[str, Any]], slot: str,
               handle: Optional[str] = None) -> str:
    """The group message: @owner, a fixed line, the item quote(s). `handle`
    is the owner's token from lib/wa_mention ("@15551234567" for a real
    mention); without it, "@Name"."""
    one, many = _OPENERS[slot]
    who = handle or "@" + (owner_name.strip() or "there")
    lines = [f"{who} {one if len(items) == 1 else many}"]
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


def escalate_to(admins: List[Dict[str, Any]], owner_user_id: Optional[str]) -> List[Dict[str, Any]]:
    """The admins the 4:00 DM goes to: every company admin except the owner.
    An owner who is the only admin: nobody."""
    return [a for a in admins if str(a.get("id")) != str(owner_user_id or "")]


def _join(parts: List[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def reason(slot: str, items: List[Dict[str, Any]], last_nudge: Optional[datetime],
           day: date, chatter_at: Optional[datetime] = None,
           skipped: Optional[str] = None) -> str:
    """Why it fired, for the reviewer. `chatter_at`: the owner wrote since
    the last nudge, about something else (rule 3: no effect). `skipped`: the
    slot skipped since the last nudge (rule 2), now chased again."""
    base = _reason(slot, items, last_nudge, day)
    notes = []
    if skipped:
        notes.append(f"{SLOT_LABELS.get(skipped, skipped)} was skipped after their answer; "
                     "this slot runs")
    if chatter_at:
        notes.append(f"owner wrote at {hhmm(chatter_at)}, not about this item: still chased")
    return base + ("" if not notes else " " + "; ".join(n[0].upper() + n[1:] for n in notes) + ".")


def _reason(slot: str, items: List[Dict[str, Any]], last_nudge: Optional[datetime],
            day: date) -> str:
    dues = sorted({str((it.get("due") or {}).get("due_text") or "") for it in items} - {""})
    # The day itself, then the words that set it: "due today (Sat Oct 10 ·
    # said 'tomorrow')" -- "due today (tomorrow)" read as a contradiction.
    when = f"{day.strftime('%a %b')} {day.day}"
    said_words = ", ".join(f"'{d}'" for d in dues)
    due = f"due today ({when} · said {said_words})" if dues else f"due today ({when})"
    Due = "D" + due[1:]
    if slot == ADMIN:
        return (f"Still no update after the end of day nudge; {due}. "
                "Owner confirmed.")
    if last_nudge:
        return f"{Due}; no update and no answer from the owner about it since the {hhmm(last_nudge)} nudge."
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
        if r.get("slot") == NOT_CHASED or r.get("kind") == SKIPPED:
            continue                    # a listing / a slot not sent, not a nudge
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
