"""TARGETED CONFIRMATIONS: the few questions worth asking a superintendent or CP.

Pure: no database, no network. server.py (the TARGETED CONFIRMATIONS block)
loads the job's evidence items (lib/evidence.py) and its frame, asks this
module what is genuinely missing or conflicting, and stores what it WOULD ask
in `confirmation_candidates`. SHADOW: nothing is sent until the owner turns it
on (CONFIRMATIONS_MODE, below).

ONLY THESE TRIGGERS. Anything else is never asked.

  conflict_failed_after_pass  sources disagree: a later failure (attested)
                              after an earlier pass of the same work, same
                              level, and nothing since.
  work_off_logged_level       a statement or a photo puts work on a level on a
                              day whose filed log names levels and not that one.
  done_unbacked               a filed log says done, and nothing at observed or
                              above (no photo, no statement, no sign-off) says
                              anything about that work on that level.
  planned_start_passed        a confirmed-schedule activity whose planned start
                              has passed (inside the window the logs were read)
                              with no evidence at all and no actual start.
  gate_unknown                work after an inspection gate is reported on a
                              level, the work before the gate is on record
                              there (so the gate applies), and NOTHING is on
                              record for the gate.
  inspection_date_passed      a booked inspection whose date passed with no
                              outcome on record.

NEVER ASK WHAT A SOURCE ALREADY ANSWERS: each trigger names what would answer
it, and an item that does (any rung) suppresses the question. "Don't know" is
not an answer to anything; "not yet" answers for NOT_YET_FRESH_DAYS.

WHO, HOW OFTEN (plan()): only people who opted in (an active WhatsApp
connection by their own YES), only a superintendent or CP, only on their
assigned jobs; at most MAX_PER_PERSON questions a person a day, in ONE message;
never the same thing twice within REPEAT_DAYS; never on Shabbos / Yom Tov for a
job that keeps it; skipped when the person already wrote about it today.

THE ANSWERS ARE CLOSED: done / not yet / blocked: why / don't know (or the
inspection words, or yes / no), or a voice note. Every question carries "don't
know" and at least one FALSIFIABLE option: an answer that would show the
record (or the premise of the question) wrong. parse_reply() reads replies by
fixed rules, English and Spanish; whatever it cannot read is left for the DM
brain, never guessed. Each answer becomes an `attested` item with the person,
their words and the question (answer_item()); "don't know" is kept as
`dont_know`, never as no.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import evidence as E
from lib import inspection_reports as IR

COLLECTION = "confirmation_candidates"
#: Append-only: sent / answered / dismissed / review rows, one per event. A
#: candidate row is never edited; its current status is its newest event.
EVENTS = "confirmation_events"
#: Append-only: one row per answer, carrying the attested evidence item.
ANSWERS = "confirmation_answers"

MODES = ("off", "shadow", "live")
MODE_ENV = "CONFIRMATIONS_MODE"
#: Live needs this as well. It is set nowhere: turning it on is the owner's.
LIVE_ENV = "CONFIRMATIONS_LIVE_ALLOWED"

MAX_PER_PERSON = 3
REPEAT_DAYS = 7
NOT_YET_FRESH_DAYS = 7
#: A planned start this recent is not yet a question.
START_GRACE_DAYS = 2
#: ... nor one this old (the window the logs were read covers it anyway).
START_LOOKBACK_DAYS = 28
#: When a day's message would go out, New York.
SEND_AT = time(7, 30)
TARGET_ROLES = ("superintendent", "cp")
_ROLE_ORDER = {"superintendent": 0, "cp": 1}

#: queued: handed to the morning queue, NOT delivered. A candidate is "sent"
#: only by an appended "sent" event written after a delivery succeeded
#: (server _confirmation_delivered); a reply is read as an answer only to a
#: question delivered to that person that day.
STATUSES = ("shadow", "queued", "sent", "answered", "dismissed")
VERDICTS = ("correct", "wrong")

CONFLICT, OFF_LEVEL, DONE_UNBACKED = "conflict_failed_after_pass", "work_off_logged_level", "done_unbacked"
START_PASSED, GATE_UNKNOWN, INSP_PASSED = "planned_start_passed", "gate_unknown", "inspection_date_passed"
TRIGGERS = (CONFLICT, OFF_LEVEL, DONE_UNBACKED, START_PASSED, GATE_UNKNOWN, INSP_PASSED)
#: What a question is worth before age: a disagreement first, then an
#: inspection, then the schedule, then a log's word.
WEIGHTS = {CONFLICT: 1.0, INSP_PASSED: 0.9, GATE_UNKNOWN: 0.8, START_PASSED: 0.7,
           DONE_UNBACKED: 0.6, OFF_LEVEL: 0.5}
HALF_LIFE_DAYS = 7.0

#: The five gates an inspection report can name (lib/inspection_reports).
GATES = {IR.PLUMBING_ROUGH: "plumbing rough inspection", IR.ELECTRICAL_ROUGH: "electrical rough inspection",
         IR.SPRINKLER: "sprinkler hydro test", IR.FIRESTOPPING: "firestopping inspection",
         IR.ENERGY: "energy code (insulation) inspection"}
INSPECTION_PREFIX = "inspection:"

# ── MODE ───────────────────────────────────────────────────────────────────


def mode(env: Optional[Dict[str, str]] = None) -> str:
    """off | shadow | live. Default off; anything unknown is off. "live"
    without LIVE_ENV=1, or while the people asked cannot be messaged first
    (unmessageable_roles), is REFUSED and read as shadow: nothing is sent."""
    e = os.environ if env is None else env
    m = str(e.get(MODE_ENV, "") or "").strip().lower()
    if m not in MODES:
        return "off"
    if m == "live" and live_refused(e):
        return "shadow"
    return m


def live_requested(env: Optional[Dict[str, str]] = None) -> bool:
    e = os.environ if env is None else env
    return str(e.get(MODE_ENV, "") or "").strip().lower() == "live"


def unmessageable_roles() -> List[str]:
    """The TARGET_ROLES the bot may not message first. lib/dm_roles (owner
    ruling 2026-11-09): a field role (superintendent, CP) is never messaged
    first, and send_whatsapp_dm refuses them (lib/wa_dm.is_dm_eligible). That
    rule is not changed here: while it holds, live cannot deliver a question,
    so it must not read anyone's DMs as answers either."""
    from lib import wa_dm
    return [r for r in TARGET_ROLES if r not in wa_dm.DM_ELIGIBLE_ROLES or r in wa_dm.DM_NEVER_ROLES]


def live_refused(env: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Why live is refused, or None when it may run."""
    e = os.environ if env is None else env
    if str(e.get(LIVE_ENV, "") or "").strip() != "1":
        return f"live refused: {LIVE_ENV} is not 1"
    blocked = unmessageable_roles()
    if blocked:
        return (f"live refused: the roles asked ({', '.join(blocked)}) cannot be messaged first (lib/dm_roles: a "
                "field role is never messaged first; send_whatsapp_dm refuses them), so no question could be "
                "delivered and no reply may be read as an answer; running as shadow")
    return None


# ── READING ITEMS ──────────────────────────────────────────────────────────

_FACT_EXCLUDE = ("dont_know",)


def _on(i: Dict[str, Any]) -> Optional[date]:
    v = i.get("on")
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def facts(items: Iterable[Dict[str, Any]], today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Items that say something: not an estimate, not "don't know", and a "not
    yet" only while it is fresh."""
    out = []
    for i in items:
        if i.get("kind") == "estimate" or i.get("claim") in _FACT_EXCLUDE:
            continue
        if i.get("claim") == "not_yet" and today is not None:
            d = _on(i)
            if d is None or (today - d).days > NOT_YET_FRESH_DAYS:
                continue
        out.append(i)
    return out


def _about(items: Iterable[Dict[str, Any]], node: Optional[str], level: str) -> List[Dict[str, Any]]:
    return [i for i in items if (node is None or i.get("node") == node) and level in (i.get("levels") or [])]


def _one_level(i: Dict[str, Any]) -> Optional[str]:
    lv = i.get("levels") or []
    return lv[0] if len(lv) == 1 and not i.get("shared") else None


def _ref(i: Dict[str, Any]) -> Dict[str, Any]:
    d = _on(i)
    return {"source": i.get("source"), "ref": i.get("ref"), "kind": i.get("kind"), "claim": i.get("claim"),
            "on": d.isoformat() if d else None, "by": i.get("by"), "quote": i.get("quote")}


def _when(i: Dict[str, Any]) -> Optional[date]:
    """The day THE ONE ORDER (evidence.order_key) puts an item on: its own
    date, else the day it was said. Never printed as the date of the work."""
    k = E.order_key(i)[0]
    return date.fromordinal(k) if k > 0 else None


def _newest(items: Sequence[Dict[str, Any]], n: int = 3) -> List[Dict[str, Any]]:
    """Newest first by evidence.order_key: an undated statement said later is
    later, never hidden behind an earlier dated one."""
    return sorted(items, key=lambda i: (E.order_key(i), str(i.get("ref"))), reverse=True)[:n]


# ── WORDS ──────────────────────────────────────────────────────────────────

def level_words(token: str) -> str:
    from lib.work_state import level_label
    return level_label(token)


def node_words(node: Optional[str], note: Any = None) -> str:
    if not node:
        return "work"
    if node in GATES:
        return GATES[node]
    if node.startswith(INSPECTION_PREFIX):
        return str(note or node[len(INSPECTION_PREFIX):]).strip() or "the inspection"
    from lib.work_state import node_label
    return node_label(node)


def day_words(d: Optional[date]) -> str:
    return f"{d:%a %b} {d.day}" if d else "an earlier day"


def said_words(i: Dict[str, Any]) -> str:
    """An item's day: its own date, or that it states none and when it was said."""
    if _on(i):
        return day_words(_on(i))
    w = _when(i)
    return f"date not stated, said {day_words(w)}" if w else "date not stated"


def _who(i: Dict[str, Any]) -> str:
    if i.get("by"):
        return str(i["by"])
    return {"daily_log": "a filed log", "logbooks": "a filed log", "photo_index": "a photo",
            "superintendent_log": "the superintendent's log", "schedule_file": "the schedule file"}.get(
        str(i.get("source")), "someone")


# ── OPTIONS ────────────────────────────────────────────────────────────────

def _opt(key: str, label: str, falsifiable: bool = False) -> Dict[str, Any]:
    return {"key": key, "label": label, "falsifiable": falsifiable}


DONT_KNOW = _opt("dont_know", "don't know")
OPTIONS = {
    # The premise: the log's "done" may not be so.
    DONE_UNBACKED: [_opt("done", "done"), _opt("not_yet", "not yet", True), _opt("blocked", "blocked: why"), DONT_KNOW],
    # The premise: nothing on record means nothing started.
    START_PASSED: [_opt("started", "started", True), _opt("done", "done", True), _opt("not_yet", "not yet"),
                   _opt("blocked", "blocked: why"), DONT_KNOW],
    # The premise: work went on past an inspection, so it passed.
    GATE_UNKNOWN: [_opt("passed", "passed"), _opt("failed", "failed", True), _opt("not_yet", "not yet", True), DONT_KNOW],
    # The premise: a booked inspection happened on its date.
    INSP_PASSED: [_opt("passed", "passed"), _opt("failed", "failed"), _opt("not_yet", "not done yet", True), DONT_KNOW],
    # The premise: the later failure is the current state.
    CONFLICT: [_opt("passed", "passed", True), _opt("failed", "failed"), DONT_KNOW],
    # The premise: the log is right that nobody was there.
    OFF_LEVEL: [_opt("present", "yes", True), _opt("absent", "no"), DONT_KNOW],
}
INSPECTION_TRIGGERS = (GATE_UNKNOWN, INSP_PASSED, CONFLICT)


def choices_line(trigger: str) -> str:
    return " / ".join(o["label"] for o in OPTIONS[trigger])


# ── THE TRIGGERS ───────────────────────────────────────────────────────────

def _thing(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)


def _score(trigger: str, d: Optional[date], today: date, n_evidence: int) -> float:
    age = max(0, (today - d).days) if d else 30
    return round(WEIGHTS[trigger] * 0.5 ** (age / HALF_LIFE_DAYS) + 0.02 * min(n_evidence, 4), 4)


def _cand(trigger: str, thing: str, project_id: Any, node: Optional[str], level: str, question: str,
          evid: Sequence[Dict[str, Any]], d: Optional[date], today: date, note: Any = None) -> Dict[str, Any]:
    return {"trigger": trigger, "thing": thing, "project_id": str(project_id), "node": node, "level": level,
            "question": question, "options": [dict(o) for o in OPTIONS[trigger]],
            "evidence": [_ref(i) for i in evid], "score": _score(trigger, d, today, len(evid)),
            "subject": node_words(node, note), "inspection": trigger in INSPECTION_TRIGGERS}


def _conflicts(fs: List[Dict[str, Any]], pid: Any, today: date) -> List[Dict[str, Any]]:
    """In THE ONE ORDER (evidence.order_key), as evidence.status reads it: an
    undated re-pass said after the failure is after it, and answers it."""
    out = []
    keys = {(i.get("node"), lv) for i in fs if i.get("node") for lv in i.get("levels") or []}
    for node, lv in sorted(keys, key=str):
        mine = _about(fs, node, lv)
        fails = [i for i in mine if i["claim"] == "failed" and i["kind"] == "attested" and _when(i)]
        if not fails:
            continue
        last = _newest(fails, 1)[0]
        d, at = _when(last), E.order_key(last)
        passes = [i for i in mine if i["claim"] == "done" and E.rank(i["kind"]) <= E.rank("attested")
                  and _when(i) and E.order_key(i) < at]
        if not passes:
            continue
        # Anything said on or after the failure (a re-inspection, a sign-off,
        # an answer) already says where it stands.
        since = [i for i in mine if i is not last and _when(i) and E.order_key(i) >= at
                 and i["claim"] in ("done", "failed", "not_yet", "in_progress")]
        if since:
            continue
        p = _newest(passes, 1)[0]
        q = (f"{node_words(node, last.get('note')).capitalize()} on {level_words(lv)}: {_who(p)} said passed "
             f"({said_words(p)}), {_who(last)} said failed ({said_words(last)}). Where does it stand now?")
        out.append(_cand(CONFLICT, _thing(CONFLICT, node, lv, last.get("ref")), pid, node, lv, q, [last, p], d, today,
                         last.get("note")))
    return out


def _off_level(fs: List[Dict[str, Any]], frame: Dict[str, Any], pid: Any, today: date) -> List[Dict[str, Any]]:
    logged: Dict[date, set] = frame.get("logged_levels") or {}
    seen, out = set(), []
    for i in _newest([i for i in fs if i["kind"] in ("attested", "observed")
                      and i["claim"] in ("in_progress", "started", "present")], 10_000):
        lv, d = _one_level(i), _on(i)
        if not lv or not d or (lv, d) in seen:
            continue
        named = logged.get(d) or set()
        if not named or lv in named:
            continue                     # no log that day, or the log has someone there
        # Answered: someone already said whether a crew was there that day.
        if any(a["claim"] in ("present", "absent") and a["kind"] in ("attested", "confirmed", "verified")
               and lv in (a.get("levels") or []) and _on(a) == d and a.get("source") == "confirmation_answers"
               for a in fs):
            continue
        seen.add((lv, d))
        what = "a photo" if i["kind"] == "observed" else _who(i)
        q = (f"On {day_words(d)}, {what} put {node_words(i.get('node'), i.get('note'))} on {level_words(lv)}, "
             f"but that day's log has nobody on {level_words(lv)} (it names "
             f"{', '.join(level_words(x) for x in sorted(named))}). Was a crew on {level_words(lv)} that day?")
        out.append(_cand(OFF_LEVEL, _thing(OFF_LEVEL, lv, d.isoformat()), pid, i.get("node"), lv, q, [i], d, today))
    return out


def _done_unbacked(fs: List[Dict[str, Any]], pid: Any, today: date) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for i in _newest([i for i in fs if i["kind"] == "reported" and i["claim"] == "done" and i.get("node")], 10_000):
        lv = _one_level(i)
        if not lv or (i["node"], lv) in seen:
            continue
        seen.add((i["node"], lv))
        backed = [a for a in _about(fs, i["node"], lv) if E.rank(a["kind"]) <= E.rank("observed")]
        if backed:
            continue
        d = _on(i)
        q = (f"The {day_words(d)} log says {node_words(i['node'])} is done on {level_words(lv)}; "
             f"no photo, sign-off or statement backs it yet. Is it done?")
        out.append(_cand(DONE_UNBACKED, _thing(DONE_UNBACKED, i["node"], lv), pid, i["node"], lv, q, [i], d, today))
    return out


def _start_passed(fs: List[Dict[str, Any]], frame: Dict[str, Any], pid: Any, today: date) -> List[Dict[str, Any]]:
    out = []
    logs_from: Optional[date] = frame.get("logs_from")
    for a in frame.get("schedule") or []:
        start = a.get("planned_start")
        if not isinstance(start, date) or a.get("actual_start") or not logs_from:
            continue
        if not (logs_from <= start <= today - timedelta(days=START_GRACE_DAYS)):
            continue
        if (today - start).days > START_LOOKBACK_DAYS:
            continue
        for node in a.get("nodes") or []:
            for lv in a.get("levels") or []:
                if _about(fs, node, lv):
                    continue             # any evidence at all answers it
                q = (f"The schedule had {a.get('name') or node_words(node)} starting {day_words(start)}; "
                     f"nothing on record since for {node_words(node)} on {level_words(lv)}. Has it started?")
                ref = {"kind": "confirmed", "claim": "scheduled", "source": "project_schedules",
                       "ref": str(a.get("id") or ""), "on": start, "by": None, "quote": a.get("name")}
                out.append(_cand(START_PASSED, _thing(START_PASSED, a.get("id"), node, lv), pid, node, lv, q,
                                 [ref], start, today))
    return out


def _graph() -> Tuple[Dict[str, Any], Dict[str, List[Tuple[str, str]]]]:
    from lib.work_state import _graph as g
    return g(None)


def _gate_unknown(fs: List[Dict[str, Any]], pid: Any, today: date) -> List[Dict[str, Any]]:
    from lib.work_state import _prerequisites
    nodes, before = _graph()
    after = {}
    for i in fs:
        lv = _one_level(i)
        if (lv and i.get("node") in nodes and i["node"] not in GATES
                and i["claim"] in ("in_progress", "started", "done", "present")):
            after.setdefault((i["node"], lv), []).append(i)
    out, seen = [], set()
    for (node, lv), work in sorted(after.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        for gate in _prerequisites(node, nodes, before):
            if gate not in GATES or (gate, lv) in seen:
                continue
            if _about(fs, gate, lv):
                continue                 # something is on record for the gate
            prior = [p for p, _t in before.get(gate, []) if p not in GATES]
            before_work = [i for p in prior for i in _about(fs, p, lv)]
            if not before_work:
                continue                 # nothing says the building has this system here
            seen.add((gate, lv))
            newest = _newest(work, 2)
            d = _on(newest[0])
            q = (f"{node_words(node).capitalize()} is reported on {level_words(lv)} ({day_words(d)}), but nothing is "
                 f"on record for the {GATES[gate]} there. Has it passed?")
            out.append(_cand(GATE_UNKNOWN, _thing(GATE_UNKNOWN, gate, lv), pid, gate, lv, q,
                             newest + _newest(before_work, 1), d, today))
    return out


def _inspection_passed(fs: List[Dict[str, Any]], pid: Any, today: date) -> List[Dict[str, Any]]:
    out = []
    keys = {(i.get("node"), lv) for i in fs if i["claim"] == "scheduled" and i.get("node")
            for lv in i.get("levels") or []}
    for node, lv in sorted(keys, key=str):
        mine = _about(fs, node, lv)
        booked = [i for i in mine if i["claim"] == "scheduled" and _on(i)]
        if not booked:
            continue
        last = _newest(booked, 1)[0]
        d = _on(last)
        if d >= today:
            continue
        # An outcome dated on or after the booking, or an undated one SAID on
        # or after it (evidence.order_key): "it passed" said Friday answers it.
        outcome = [i for i in mine if i["claim"] in ("done", "failed", "in_progress", "not_yet")
                   and _when(i) and _when(i) >= d]
        if outcome:
            continue
        q = (f"The {node_words(node, last.get('note'))} on {level_words(lv)} was booked for {day_words(d)}; "
             f"no result is on record. How did it go?")
        out.append(_cand(INSP_PASSED, _thing(INSP_PASSED, node, lv, d.isoformat()), pid, node, lv, q, [last], d,
                         today, last.get("note")))
    return out


def candidates(items: Iterable[Dict[str, Any]], frame: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every question worth asking about one job, best first.

    `frame`: {"project_id", "today": date, "logs_from": date (first day of
    logs read), "logged_levels": {date: set(levels the filed log names)},
    "schedule": [{"id", "name", "nodes", "levels", "planned_start": date,
    "actual_start"}] -- the CONFIRMED schedule file only}."""
    today: date = frame["today"]
    pid = frame.get("project_id")
    fs = facts(items, today)
    out = (_conflicts(fs, pid, today) + _inspection_passed(fs, pid, today) + _gate_unknown(fs, pid, today)
           + _start_passed(fs, frame, pid, today) + _done_unbacked(fs, pid, today) + _off_level(fs, frame, pid, today))
    out.sort(key=lambda c: (-c["score"], c["thing"]))
    return out


# ── WHO, WHEN, HOW MANY ────────────────────────────────────────────────────

def send_at(day: date) -> datetime:
    """When a day's message would go out, in UTC."""
    try:
        from zoneinfo import ZoneInfo
        at = datetime.combine(day, SEND_AT).replace(tzinfo=ZoneInfo("America/New_York"))
    except Exception:  # pragma: no cover
        at = datetime.combine(day, SEND_AT).replace(tzinfo=timezone.utc)
    return at.astimezone(timezone.utc)


def eligible(person: Dict[str, Any], project_id: Any) -> Optional[str]:
    """None when this person may be asked about this job; else why not."""
    if str(person.get("role") or "").strip().lower() not in TARGET_ROLES:
        return "role"
    if not person.get("opted_in"):
        return "not_opted_in"
    if str(project_id) not in {str(p) for p in person.get("assigned_projects") or []}:
        return "not_assigned"
    return None


def wrote_about(texts: Iterable[Any], cand: Dict[str, Any]) -> bool:
    """They already wrote today about this work (or this inspection) on this
    level: whole words, by the same readers the work state uses."""
    from lib.work_state import classify, level_said
    node, lv = cand.get("node"), cand.get("level")
    for t in texts:
        s = str(t or "")
        if not s.strip() or not lv or not level_said(lv, s):
            continue
        if node in GATES and node in IR.gates_named(s):
            return True
        if node and node in classify(s, s)[0]:
            return True
        if node is None or (node or "").startswith(INSPECTION_PREFIX):
            return True
    return False


def plan(cands: Sequence[Dict[str, Any]], people: Sequence[Dict[str, Any]], *, day: date,
         history: Sequence[Dict[str, Any]] = (), said_today: Optional[Dict[str, List[Any]]] = None,
         keeps_shabbos: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    """{"messages": [{"user_id", "name", "items": [...]}], "skipped": [{thing,
    project_id, why}]}. `cands` from every job, `people` every person who could
    be asked ({user_id, name, role, opted_in, assigned_projects}), `history`
    earlier candidate rows ({thing, project_id, day, target_user_id, status}),
    `said_today` {user_id: [their words today]}, `keeps_shabbos` {project_id:
    bool}."""
    from lib import shabbos
    at = send_at(day)
    quiet_day = shabbos.is_quiet(at)
    said = said_today or {}
    keeps = keeps_shabbos or {}
    since = day - timedelta(days=REPEAT_DAYS)
    asked = set()
    messaged_today = set()
    for h in history:
        try:
            hd = date.fromisoformat(str(h.get("day"))[:10])
        except ValueError:
            continue
        if h.get("status") not in ("shadow", "queued", "sent", "answered"):
            continue
        if since < hd <= day:
            asked.add((str(h.get("project_id")), h.get("thing")))
        if hd == day:
            messaged_today.add(str(h.get("target_user_id")))
    ordered = sorted(people, key=lambda p: (_ROLE_ORDER.get(str(p.get("role") or "").lower(), 9),
                                            str(p.get("user_id"))))
    load: Dict[str, List[Dict[str, Any]]] = {}
    skipped = []
    for c in sorted(cands, key=lambda c: (-c["score"], c["thing"])):
        pid = str(c["project_id"])

        def skip(why):
            skipped.append({"thing": c["thing"], "project_id": pid, "why": why})
        if (pid, c["thing"]) in asked:
            skip("asked_within_7_days")
            continue
        if quiet_day and keeps.get(pid):
            skip("shabbos_yom_tov")
            continue
        who = [p for p in ordered if eligible(p, pid) is None]
        if not who:
            skip("nobody_opted_in_and_assigned")
            continue
        if any(wrote_about(said.get(str(p["user_id"])) or (), c) for p in who):
            skip("already_wrote_about_it_today")
            continue
        placed = False
        for p in who:
            uid = str(p["user_id"])
            if uid in messaged_today:
                continue
            if len(load.get(uid, [])) >= MAX_PER_PERSON:
                continue
            load.setdefault(uid, []).append(c)
            placed = True
            break
        if not placed:
            skip("daily_cap")
    names = {str(p["user_id"]): p.get("name") or "" for p in people}
    msgs = [{"user_id": uid, "name": names.get(uid, ""), "items": items} for uid, items in load.items() if items]
    return {"messages": msgs, "skipped": skipped, "send_at": at, "quiet_day": quiet_day}


def message_text(name: Any, items: Sequence[Dict[str, Any]], job_names: Optional[Dict[str, str]] = None) -> str:
    """The one message of the day: numbered, each with its closed answers.
    Fixed templates and the record's own facts; no model writes any of it."""
    first = (str(name or "").split() or ["there"])[0]
    jobs = job_names or {}
    n = len(items)
    head = f"Good morning {first}: {'one quick check' if n == 1 else f'{n} quick checks'} on the record."
    lines = [head]
    for k, c in enumerate(items, 1):
        job = jobs.get(str(c["project_id"]))
        lines.append(f"{k}. {f'[{job}] ' if job else ''}{c['question']} ({choices_line(c['trigger'])})")
    eg = [f"\"{k} {c['options'][0]['label']}\"" for k, c in enumerate(items[:2], 1)]
    lines.append("Reply with the number and your answer, e.g. " + ", ".join(eg) + ", or send a voice note.")
    return "\n".join(lines)


def candidate_id(day: date, user_id: Any, project_id: Any, thing: str) -> str:
    raw = f"{day.isoformat()}|{user_id}|{project_id}|{thing}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# ── THE ANSWERS ────────────────────────────────────────────────────────────

def _norm(text: Any) -> str:
    return " ".join(str(text or "").replace("’", "'").split()).casefold()


#: "no se" is "don't know" only when no word follows it ("no se terminó" is
#: "it wasn't finished"), or when "si" does ("no sé si empezaron": I don't
#: know whether). "no lo sé", "ni idea", "no clue", "nobody told me", "not
#: that I know": DON'T KNOW, never a no. Read BEFORE any yes / no.
_DONT_KNOW = re.compile(
    r"\b(?:don'?t know|dont know|do not know|didn'?t know|idk|dunno|not sure|not certain|no idea|no clue|"
    r"not a clue|unsure|beats me|who knows|can'?t say|cannot say|hard to say|i'?ll (?:check|ask|find out)|"
    r"(?:nobody|no one|no-one) told me|not that i know(?: of)?|not as far as i know|"
    r"ni idea|no tengo (?:ni )?idea|no lo s[eé]|no sabemos|no s[eé] si|no sabr[ií]a|"
    r"qui[eé]n sabe|no estoy segur[oa]|no que yo sepa|que yo sepa|voy a preguntar|tengo que preguntar)\b"
    r"|^\W*(?:ask|preg[uú]nta(?:le|les)?)\b|\bno s[eé]\b(?!\s+\w)|^\W*\?+\W*$")
#: Words that put a crew there / say nobody was. A reply carrying both a yes
#: and "nobody", or a no and "they were there", is not one answer.
_PRESENT_WORDS = re.compile(r"\b(?:(?:they|crew|guys|men|people|someone|somebody) (?:was|were)(?: there)?|"
                            r"s[ií] estaban|hab[ií]a gente|s[ií] hab[ií]a)\b")
_ABSENT_WORDS = re.compile(r"\b(?:nobody|no one|no-one|nadie|no crew|not there|wasn'?t anyone|weren'?t there|"
                           r"no estaban|no hab[ií]a)\b")
_BLOCKED = re.compile(r"\b(?:blocked|stuck|held up|on hold|bloquead[oa]s?|detenid[oa]s?|parad[oa]s?)\b\W*(.*)$")
_NOT_YET = re.compile(r"\b(?:not yet|not done|not started|not finished|hasn'?t started|haven'?t started|"
                      r"didn'?t start|did not start|not complete|todav[ií]a no|a[uú]n no|no todav[ií]a|"
                      r"no ha empezado|no han empezado|no empez[oó]|no empezaron|no est[aá] (?:list[oa]|hech[oa]))\b")
_DONE = re.compile(r"\b(?:done|finished|complete|completed|all set|wrapped up|listo|lista|listos|terminad[oa]s?|"
                   r"termin[oó]|terminamos|hech[oa]|acabad[oa]s?|completad[oa]s?|ya est[aá])\b")
_STARTED = re.compile(r"\b(?:started|in progress|underway|under way|ongoing|working on it|"
                      r"empez[oó]|empezamos|empezaron|comenz[oó]|comenzamos|en progreso|en proceso|ya empez\w*)\b")
_YES = re.compile(r"^\W*(?:yes|yeah|yep|yup|y|s[ií]|correct|they were|there was)\b")
_NO = re.compile(r"^\W*(?:no|nope|nah|n|nobody|nadie)\b")
_PERCENT = re.compile(r"\b(\d{1,3})\s?%")
_NEG_NEAR = re.compile(r"\b(?:not|no|isn'?t|wasn'?t|aren'?t|never|nunca)\W+(?:\w+\W+)?$")

_ALLOWED = {
    DONE_UNBACKED: ("done", "not_yet", "blocked", "dont_know", "started", "percent"),
    START_PASSED: ("done", "started", "not_yet", "blocked", "dont_know", "percent"),
    GATE_UNKNOWN: ("passed", "failed", "partial", "not_yet", "dont_know"),
    INSP_PASSED: ("passed", "failed", "partial", "not_yet", "dont_know", "scheduled"),
    CONFLICT: ("passed", "failed", "partial", "dont_know"),
    OFF_LEVEL: ("present", "absent", "dont_know"),
}


def read_answer(segment: Any, trigger: str) -> Optional[Dict[str, Any]]:
    """One answer, read by fixed rules from one question's part of a reply:
    {"answer", "reason"?, "percent"?, "words"}; None when it is not one closed
    answer the question allows (several, none, or another question's)."""
    s = _norm(segment).strip(" .,;:!-")
    if not s:
        return None
    if _DONT_KNOW.search(s):
        found = {"answer": "dont_know"}
    elif trigger in INSPECTION_TRIGGERS:
        read = IR.read_result(s)
        if len(read["results"]) == 1 and not read["unclear"]:
            found = {"answer": read["results"][0]}
        elif not read["results"] and ("not_yet" in read["unclear"] or _NOT_YET.search(s)):
            found = {"answer": "not_yet"}
        else:
            return None
    elif trigger == OFF_LEVEL:
        yes = bool(_YES.search(s)) or bool(_PRESENT_WORDS.search(s))
        no = bool(_NO.search(s)) or bool(_ABSENT_WORDS.search(s))
        if yes and no:
            return None              # "yes, nobody was there": two answers, none read
        if yes:
            found = {"answer": "present"}
        elif no:
            found = {"answer": "absent"}
        else:
            return None
    else:
        hits = []
        b = _BLOCKED.search(s)
        if b:
            hits.append({"answer": "blocked", "reason": b.group(1).strip(" .,;:-") or None})
            s_rest = s[:b.start()]
        else:
            s_rest = s
        if _NOT_YET.search(s_rest):
            hits.append({"answer": "not_yet"})
            s_rest = _NOT_YET.sub(" ", s_rest)
        m = _DONE.search(s_rest)
        if m:
            hits.append({"answer": "not_yet"} if _NEG_NEAR.search(s_rest[:m.start()]) else {"answer": "done"})
        if _STARTED.search(s_rest) and not m:
            hits.append({"answer": "started"})
        p = _PERCENT.search(s_rest)
        if p and not m:
            pct = int(p.group(1))
            if 0 < pct < 100:
                hits.append({"answer": "percent", "percent": float(pct)})
            elif pct == 100:
                hits.append({"answer": "done"})
        if not hits and (_NO.search(s) and _YES.search(s) or _NO.search(s) and _PRESENT_WORDS.search(s)
                         or _YES.search(s) and _ABSENT_WORDS.search(s)):
            return None              # "no, they were there": a yes and a no, neither read
        if not hits and _NO.search(s):
            hits.append({"answer": "not_yet"})
        if not hits and _YES.search(s):
            # "Is it done?" yes: done. "Has it started?" yes: started.
            hits.append({"answer": "done" if trigger == DONE_UNBACKED else "started"})
        kinds = {h["answer"] for h in hits}
        if len(kinds) != 1:
            return None
        found = hits[0]
    if found["answer"] not in _ALLOWED[trigger]:
        return None
    found["words"] = _norm(segment).strip(" ,;")
    return found


_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "first": 1, "second": 2, "third": 3,
              "uno": 1, "dos": 2, "tres": 3, "primero": 1, "segundo": 2, "tercero": 3}
#: A digit mark anywhere a word starts ("1 done 2 not yet"); a spoken one
#: ("one done, two not yet") only at the start, after a stop, or after
#: "number": "no one was there" is not question one.
_MARK = re.compile(r"(?:^|(?<=[\s,;.(]))#?([1-9])\s*[).:\-]?(?=\s|$)"
                   r"|(?:^|(?<=[,;.\n])\s*|\b(?:number|n[uú]mero)\s+)(" + "|".join(_NUM_WORDS)
                   + r")\b\s*[).:\-]?")


def _opens_an_answer(t: str, end: int, trigger: str) -> bool:
    """The words right after a number (up to three, stopping at the next
    number) read as an answer: "2 not yet" opens one, "2 guys" does not."""
    words = []
    for w in t[end:].split():
        if re.match(r"^#?\d", w) or len(words) == 3:
            break
        words.append(w)
    return any(read_answer(" ".join(words[:k]), trigger) for k in range(1, len(words) + 1))


def _marks(t: str, questions: Sequence[Dict[str, Any]]) -> List[Tuple[int, int, int]]:
    """(index, start, end) of each question number, in order. A number not
    above the last one, or one inside a sentence that no answer follows
    ("waiting on 2 guys"), is part of an answer."""
    n = len(questions)
    out: List[Tuple[int, int, int]] = []
    for m in _MARK.finditer(t):
        idx = int(m.group(1)) if m.group(1) else _NUM_WORDS[m.group(2)]
        if not (1 <= idx <= n) or (out and idx <= out[-1][0]):
            continue
        mid_sentence = m.start() > 0 and t[m.start() - 1].isspace() and t[:m.start()].rstrip()[-1:] not in ",;.\n("
        if m.group(1) and mid_sentence and not _opens_an_answer(t, m.end(), questions[idx - 1]["trigger"]):
            continue
        out.append((idx, m.start(), m.end()))
    return out


def parse_reply(text: Any, questions: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """{"answers": [{"index", "answer", ...}], "unread": [indexes not read]}.
    A reply to one question may be bare ("done"); to several, each part opens
    with its number ("1 done, 2 not yet"); "all done" answers every question
    the words fit. Nothing is guessed: what cannot be read stays unread."""
    t = _norm(text)
    n = len(questions)
    answers: Dict[int, Optional[Dict[str, Any]]] = {}
    if n == 1:
        lead = _marks(t, questions)
        answers[1] = read_answer(t[lead[0][2]:] if lead and lead[0][1] == 0 else t, questions[0]["trigger"])
    else:
        marks = _marks(t, questions)
        if marks:
            for k, (idx, _a, end) in enumerate(marks):
                seg = t[end:marks[k + 1][1] if k + 1 < len(marks) else len(t)]
                answers[idx] = read_answer(seg, questions[idx - 1]["trigger"])
        else:
            m = re.match(r"^\W*(?:all|todo|todos|todas)\b(.*)$", t)
            if m:
                for idx, q in enumerate(questions, 1):
                    answers[idx] = read_answer(m.group(1), q["trigger"])
    got = [dict(a, index=i) for i, a in sorted(answers.items()) if a]
    return {"answers": got, "unread": [i for i in range(1, n + 1) if not answers.get(i)]}


#: What an answer says, as an evidence claim. "dont_know" stays dont_know.
_CLAIM = {"done": "done", "started": "started", "percent": "in_progress", "not_yet": "not_yet",
          "blocked": "blocked", "dont_know": "dont_know", "present": "present", "absent": "absent",
          "passed": "done", "failed": "failed", "partial": "in_progress", "scheduled": "scheduled"}


def inspection_check(answer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """An inspection answer through inspection_reports' validation: the result
    is read back from their own words. None for an answer that states no
    result (not yet, don't know)."""
    if answer["answer"] not in IR.RESULTS:
        return None
    return IR.validate_statement(answer["words"], answer["words"], answer["answer"])


def answer_item(cand: Dict[str, Any], answer: Dict[str, Any], *, answer_id: str, person: str,
                on: date, check: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The attested evidence item an answer becomes: the person, their words,
    the question. None for an inspection answer the words do not bear out
    (kept, unresolved, by the caller: no result is stored)."""
    if check is not None and not check.get("agree"):
        return None
    claim = _CLAIM[answer["answer"]]
    note = f"asked: {cand['question']}"
    if answer.get("reason"):
        note += f" | blocked: {answer['reason']}"
    if answer["answer"] == "partial":
        note += " | partly passed"
    node = cand.get("node")
    return E.item("attested", claim, source=ANSWERS, ref=answer_id, project_id=cand["project_id"], node=node,
                  levels=[cand["level"]] if cand.get("level") else [], on=on, by=person,
                  quote=answer["words"], stated_percent=answer.get("percent"), note=note)


_THANKS = {"done": "done", "started": "started", "percent": "in progress", "not_yet": "not yet",
           "blocked": "blocked", "dont_know": "don't know", "present": "a crew was there", "absent": "nobody there",
           "passed": "passed", "failed": "failed", "partial": "partly passed", "scheduled": "booked"}


def ack_text(answers: Sequence[Dict[str, Any]], unread: Sequence[int], unresolved: Sequence[int] = ()) -> str:
    """The one line back. Says what was kept as theirs, and what was not read."""
    bits = [f"{a['index']}: {_THANKS[a['answer']]}" + (f" ({a['percent']:g}%)" if a.get("percent") else "")
            for a in answers if a["index"] not in unresolved]
    out = "Thanks, noted as you said (not verified): " + "; ".join(bits) + "." if bits else ""
    if unresolved:
        out += (" " if out else "") + ("Couldn't read a single result from your words for "
                                       + ", ".join(str(i) for i in unresolved) + "; nothing was recorded for it.")
    if unread:
        out += (" " if out else "") + ("Didn't catch an answer for " + ", ".join(str(i) for i in unread)
                                       + ". Reply with its number and an answer.")
    return out.strip()


# ── SHADOW PRECISION ───────────────────────────────────────────────────────

def current(row: Dict[str, Any], events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """A candidate's status and verdict now: its newest event of each kind."""
    status, verdict, st_at, v_at = row.get("status"), None, None, None
    for e in events:
        at = e.get("at")
        if e.get("kind") in ("sent", "answered", "dismissed") and (st_at is None or (at and at >= st_at)):
            status, st_at = e["kind"], at
        if e.get("kind") == "review" and e.get("verdict") in VERDICTS and (v_at is None or (at and at >= v_at)):
            verdict, v_at = e["verdict"], at
    return {"status": status, "verdict": verdict}


def precision(verdicts: Iterable[Optional[str]]) -> Dict[str, Any]:
    """Correct / (correct + wrong) with its Wilson interval
    (lib/benchmark_stats); unreviewed counted apart."""
    from lib import benchmark_stats as BS
    vs = list(verdicts)
    k = sum(1 for v in vs if v == "correct")
    n = sum(1 for v in vs if v in VERDICTS)
    r = BS.rate(k, n)
    return {"correct": k, "wrong": n - k, "unreviewed": len(vs) - n, "precision": r["rate"],
            "wilson": r["wilson"], "text": BS.fmt(r)}
