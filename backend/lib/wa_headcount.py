"""Headcount answers in the DM assistant: from check-in records, never from
the model's memory.

EVIDENCE OR SILENCE. A DM on 2026-10-09 answered "20 workers" an hour after
the brief said 18, then named "the 2 added" twice, differently, at least one
of them invented. A headcount answer is now built only from this turn's
check-in rows:

  * count     how many are on site now, by company (the brief's rule: each
              worker once, under the company of their first check-in today),
              and who came after the brief
  * added     who checked in since <time> (said in the question, else the
              time this person's brief went out today), each with the time
  * list      everyone on site now, with their check-in time
  * challenge "doesn't make sense", "are you sure": the same question,
              read from the records again -- never revised from memory

The model may only rephrase the fixed answer. `verify` then checks every
number and every capitalised word in what it wrote against this turn's
data; anything else and the fixed answer goes out instead.

Pure: no database, no network. server.py reads the rows.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = None

NO_COMPANY = "No company"
MAX_LISTED = 40

COUNT, ADDED, LIST, CHALLENGE = "count", "added", "list", "challenge"

_ADDED_RE = re.compile(
    r"\bwho (?:are|were|is|was) the (?:\d+|two|three|four|five|new|extra) ?"
    r"(?:added|new|extra|more|guys|workers|people)?\b"
    r"|\bwho (?:came|checked in|showed up|arrived|got there|came in|is new)\b"
    r"|\b(?:new|added|extra) (?:guys|workers|people|ones)\b|\bwho'?s new\b"
    r"|\b(?:since|after) (?:the |my |your )?(?:brief|\d{1,2}(?::\d{2})?\s?(?:am|pm)?)\b",
    re.IGNORECASE)
_LIST_RE = re.compile(
    r"\bwho'?s (?:on ?site|there|here|working)\b|\bwho is (?:on ?site|there|here|working)\b"
    r"|\blist (?:the |all )?(?:workers|crew|guys)\b|\bnames\b|\bwhich workers\b",
    re.IGNORECASE)
_COUNT_RE = re.compile(
    r"\bhow many\b|\bworker ?count\b|\bhead ?count\b|\bman ?power\b|\bcrew size\b"
    r"|\bcount on ?site\b|\bupdates? on (?:the )?(?:worker|crew|head|man)",
    re.IGNORECASE)
_CHALLENGE_RE = re.compile(
    r"doesn'?t make sense|does not make sense|doesn'?t add up|does not add up"
    r"|are you sure|that'?s (?:not right|wrong|not true|not correct)|that is wrong"
    r"|\bwrong\b|\byou said\b|\bbefore you said\b|\bcheck again\b",
    re.IGNORECASE)
_ON_SITE_HINT = re.compile(r"\b(workers?|crew|guys|people|on ?site|checked in|men)\b",
                           re.IGNORECASE)


# Card / SST / review questions stay with the who_on_site tool, which carries
# each worker's card state and the CP's decision.
_CARDS_RE = re.compile(r"\b(sst|cards?|osha|cert\w*|cleared|approv\w*|review\w*|"
                       r"expir\w*|flagged|sent home)\b", re.IGNORECASE)


def intent(text: str) -> Optional[str]:
    """COUNT / ADDED / LIST / CHALLENGE, or None (not a headcount question)."""
    t = str(text or "")
    if _CARDS_RE.search(t):
        return None
    if _CHALLENGE_RE.search(t):
        return CHALLENGE
    if _ADDED_RE.search(t) and (_ON_SITE_HINT.search(t) or re.search(
            r"\b(added|new|extra|came|arrived|showed up)\b", t, re.IGNORECASE)):
        return ADDED
    if _COUNT_RE.search(t) and (_ON_SITE_HINT.search(t) or re.search(
            r"\b(count|manpower|head)", t, re.IGNORECASE)):
        return COUNT
    if _LIST_RE.search(t):
        return LIST
    return None


_SINCE_RE = re.compile(r"\b(?:since|after)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
                       re.IGNORECASE)


def parse_since(text: str, now: datetime) -> Optional[datetime]:
    """'since 8', 'after 8:30', 'since 9am' -> today at that New York time
    (a bare 1-6 is PM: 'since 2' on site means 2 PM)."""
    m = _SINCE_RE.search(str(text or ""))
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    elif not ap and 1 <= h <= 6:
        h += 12
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    local = _local(now).replace(hour=h, minute=mi, second=0, microsecond=0)
    return local.astimezone(timezone.utc)


def _local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_ET) if _ET else dt


def clock(dt: Optional[datetime]) -> str:
    """'8:07 AM', New York time."""
    if not isinstance(dt, datetime):
        return ""
    s = _local(dt).strftime("%I:%M %p")
    return s[1:] if s.startswith("0") else s


def _text(v: Any) -> str:
    return " ".join(str(v or "").split())


def workers(checkins: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each worker once, at their first check-in today (the brief's rule):
    [{name, company, at}] in check-in order. No phone numbers."""
    seen, out = set(), []
    for ci in sorted(checkins, key=lambda c: _at(c.get("check_in_time")) or datetime.min.replace(tzinfo=timezone.utc)):
        wid = _text(ci.get("worker_id")) or _text(ci.get("worker_phone")) or _text(ci.get("_id"))
        if not wid or wid in seen:
            continue
        seen.add(wid)
        company = ""
        for k in ("worker_company", "company", "company_name"):
            if ci.get(k):
                company = _text(ci.get(k))
                break
        out.append({"name": _text(ci.get("worker_name")) or "Name not on record",
                    "company": company or NO_COMPANY,
                    "at": _at(ci.get("check_in_time"))})
    return out


def _at(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def summarize(checkins: Iterable[Dict[str, Any]], since: Optional[datetime]) -> Dict[str, Any]:
    """The tool result for one turn: total, by company, every worker with
    their time, and who came after `since`."""
    ws = workers(checkins)
    counts: Dict[str, int] = {}
    for w in ws:
        counts[w["company"]] = counts.get(w["company"], 0) + 1
    by_company = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    added = [w for w in ws if since and w["at"] and w["at"] > since]
    return {"total": len(ws), "by_company": by_company, "workers": ws,
            "since": since, "added": added}


def _who(w: Dict[str, Any]) -> str:
    return f"{w['name']} ({w['company']}) {clock(w['at'])}".strip()


def compose(kind: str, data: Dict[str, Any], job: str, since_label: str = "") -> str:
    """The fixed answer, from the data and nothing else. `since_label`: 'your
    brief at 8:07 AM' or '9:00 AM'."""
    total, by_co = data["total"], data["by_company"]
    breakdown = ", ".join(f"{c} {n}" for c, n in by_co)
    if kind == ADDED:
        if not data.get("since"):
            kind = LIST
        else:
            added = data["added"]
            if not added:
                return f"{job}: nobody checked in after {since_label}. {total} on site now."
            lines = [f"{job}: {len(added)} checked in after {since_label}:"]
            lines += [f"• {_who(w)}" for w in added[:MAX_LISTED]]
            if len(added) > MAX_LISTED:
                lines.append(f"…and {len(added) - MAX_LISTED} more (see the app).")
            lines.append(f"{total} on site now — {breakdown}.")
            return "\n".join(lines)
    if total == 0:
        return f"{job}: nobody has checked in today."
    if kind == LIST:
        lines = [f"{job}: {total} on site now — {breakdown}."]
        lines += [f"• {_who(w)}" for w in data["workers"][:MAX_LISTED]]
        if total > MAX_LISTED:
            lines.append(f"…and {total - MAX_LISTED} more (see the app).")
        return "\n".join(lines)
    out = f"{job}: {total} on site now — {breakdown}."
    if data.get("since"):
        added = data["added"]
        if added:
            out += f"\n{len(added)} checked in after {since_label}: " + \
                ", ".join(_who(w) for w in added[:MAX_LISTED]) + "."
        else:
            out += f"\nNobody new since {since_label}."
    return out


# ── THE CHECK ────────────────────────────────────────────────────────────────

# Words a rephrasing may capitalise without them being a name.
_PLAIN = set("""
there here that these those this since so total today currently right now as
of workers worker people on site at in after before the a an and with from
plus checked check new added no nobody none your brief morning sent count
headcount also including which who they we it i levelog assistant am pm
company companies crew breakdown here's there's that's still only just yes
ok okay sure sorry correct you per by first then latest earlier later list
everyone all one two three four five six seven eight nine ten twelve
note noted again checking checked-in onsite
""".split())


def verify(reply: str, data: Dict[str, Any], job: str, since_label: str = "") -> bool:
    """Every number and every capitalised word in `reply` is in this turn's
    data (or the job's address / the since label). False = send the fixed
    answer instead."""
    allowed_text = " ".join(
        [job, since_label, str(data["total"]), str(len(data.get("added") or []))]
        + [f"{c} {n}" for c, n in data["by_company"]]
        + [f"{w['name']} {w['company']} {clock(w['at'])}" for w in data["workers"]])
    nums = set(re.findall(r"\d+", allowed_text))
    words = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'’.-]*", allowed_text)}
    for n in re.findall(r"\d+", reply or ""):
        if n not in nums:
            return False
    for w in re.findall(r"\b[A-Z][A-Za-z'’.-]*", reply or ""):
        lw = w.lower().strip(".'’")
        if lw not in words and lw not in _PLAIN:
            return False
    return True


PHRASE_PROMPT = (
    "Rewrite this WhatsApp answer for a construction PM so it reads naturally, "
    "in at most 4 short lines. Use ONLY the names, companies, numbers and times "
    "in it. Do not add, drop, round or compute anything. No greeting."
)
