"""Attention + chase DRY RUN: a scripted group chat through the real pipeline,
with no real people, no real database and nothing sent.

Windows (PowerShell, from backend\\):
    railway run python scripts\\attention_dry_run.py scripts\\dry_run\\pass3_2026_10.json

macOS / Linux:
    railway run python scripts/attention_dry_run.py scripts/dry_run/pass3_2026_10.json

Options:
    --scripted     no model: each line's expected label is the model's answer
                   (tests the code around the model; what CI runs)
    --json PATH    also write the full report as JSON

WHAT RUNS, AND HOW IT IS ISOLATED
  1. Each message is built in WaAPI's webhook shape -- the raw WhatsApp-Web
     `_data` with quotedMsg / quotedStanzaID / quotedParticipant /
     mentionedIds -- and goes through the webhook's own parser
     (parse_inbound_message) and its own stored-row builder
     (_store_group_message).
  2. The attention worker (_attention_tick) runs every simulated minute:
     cheap filter, the REAL model (unless --scripted; prompt version logged),
     the state engine, the sender map.
  3. The chase worker (_chase_tick) runs at every slot of every scenario day.
  The clock is injected; nothing waits. Everything is written to an
  IN-MEMORY database (tests/_fake_mongo.FakeDb) swapped in for server.db:
  no production collection is read or written. Every send path is replaced
  by a recorder; any call to one is reported and fails the run.

EXIT CODES
  0  every chase entry as expected (line labels are scored, not gating)
  1  a chase entry missing or unexpected
  2  the scenario cannot be run (placeholder, bad file)
  3  something tried to send

SCENARIO FILE (see scripts/dry_run/*.json)
  tz, project {name, address, chase_weekends, send_window},
  senders  {KEY: {name, lid, user: {role}?, people: {person_name, sub_company}?}}
  messages [{from, at: "YYYY-MM-DD HH:MM:SS" (local), text, reply_to: line?,
             mentions: [KEY]?, reply_shape: "stanza" | "missing"?,
             expect: {kind: item|none|state|merged|review|flag|follow_up|part_done,
                      type?, due_text?, owner?, owner_possibly?, of?, also?, to?,
                      into?}}]
  chase    {days: ["YYYY-MM-DD"], expect: [{day, slot, owner: KEY, items: [line]}]}
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))
# Importing server needs these; under `railway run` they are already set.
for _k, _v in {"APP_BASE_URL": "https://app.levelog.com", "DB_NAME": "dry_run",
               "MONGO_URL": "mongodb://localhost:27017",
               "JWT_SECRET": "dry-run-only"}.items():
    os.environ.setdefault(_k, _v)

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

GROUP = "120363099999999901@g.us"
BOT = "15550000000@c.us"
COMPANY = "co_dry_run"
PROJECT = "proj_dry_run"
SEND_PATHS = ("send_whatsapp_message", "send_whatsapp_dm", "_waapi_post_raw",
              "_react_to_message", "_react_or_say")
SOFT_TYPES = {frozenset({"question", "request"})}


class ScenarioError(Exception):
    pass


# ── the scenario ────────────────────────────────────────────────────────────

def load(path: str) -> dict:
    sc = json.loads(Path(path).read_text(encoding="utf-8"))
    if sc.get("placeholder"):
        raise ScenarioError(sc.get("about") or "placeholder scenario: nothing to run yet")
    for i, m in enumerate(sc["messages"], 1):
        m["n"] = i
        if m["from"] not in sc["senders"]:
            raise ScenarioError(f"line {i}: unknown sender {m['from']!r}")
    return sc


def _tz(sc):
    return ZoneInfo(sc.get("tz") or "America/New_York") if ZoneInfo else timezone.utc


def _at(sc, s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=_tz(sc)).astimezone(timezone.utc)


def _jid(sc, key: str) -> str:
    return f"{sc['senders'][key]['lid']}@lid"


def _hash(sc, n: int) -> str:
    return "3EB0" + hashlib.sha1(f"{sc.get('name')}|{n}".encode()).hexdigest()[:16].upper()


def wire_body(sc: dict, m: dict) -> str:
    """The text as WhatsApp delivers it: a native @mention is the person's
    id in the text, not their name."""
    body = m["text"]
    for k in m.get("mentions") or []:
        name = sc["senders"][k]["name"].split(" ")[0]
        body = body.replace(f"@{name}", f"@{sc['senders'][k]['lid']}", 1)
    return body


def payload(sc: dict, m: dict) -> dict:
    """One message as WaAPI posts it: the WhatsApp-Web message with its raw
    `_data`. A reply carries quotedMsg plus quotedStanzaID / quotedParticipant
    at the top of `_data` (reply_shape "missing" drops the ids, as a payload
    without them would)."""
    author = _jid(sc, m["from"])
    h = _hash(sc, m["n"])
    ts = int(_at(sc, m["at"]).timestamp())
    body = wire_body(sc, m)
    mentions = [_jid(sc, k) for k in m.get("mentions") or []]
    mid = {"fromMe": False, "remote": GROUP, "id": h, "participant": author,
           "_serialized": f"false_{GROUP}_{h}_{author}"}
    data = {"id": mid, "body": body, "type": "chat", "t": ts, "from": GROUP,
            "to": BOT, "author": author, "notifyName": sc["senders"][m["from"]]["name"],
            "mentionedJidList": mentions}
    msg = {"id": mid, "body": body, "type": "chat", "timestamp": ts, "from": GROUP,
           "to": BOT, "author": author, "fromMe": False, "hasQuotedMsg": False,
           "mentionedIds": mentions, "_data": data}
    if m.get("reply_to"):
        q = sc["messages"][m["reply_to"] - 1]
        data["quotedMsg"] = {"type": "chat", "body": q["text"]}
        msg["hasQuotedMsg"] = True
        if (m.get("reply_shape") or "stanza") == "stanza":
            data["quotedStanzaID"] = _hash(sc, q["n"])
            data["quotedParticipant"] = {"server": "lid", "user": sc["senders"][q["from"]]["lid"],
                                         "_serialized": _jid(sc, q["from"])}
    return {"event": "message", "instanceId": "dry-run", "data": {"message": msg}}


def world(sc: dict):
    from tests._fake_mongo import FakeDb
    import server
    proj = sc.get("project") or {}
    users, optins, people = [], [], []
    admin_seen = False
    for key, s in sc["senders"].items():
        if s.get("user"):
            uid = f"u_{key.lower()}"
            role = s["user"].get("role", "pm")
            admin_seen |= role == "admin"
            users.append({"_id": uid, "company_id": COMPANY, "name": s["name"], "role": role,
                          "phone": s.get("phone") or "", "account_status": "approved"})
            optins.append({"_id": f"o_{key.lower()}", "user_id": uid, "company_id": COMPANY,
                           "chat_digits": s["lid"], "status": "active"})
        if s.get("people"):
            people.append({"_id": f"m_{key.lower()}", "company_id": COMPANY,
                           "sender_jid": _jid(sc, key), **s["people"]})
    if not admin_seen:
        users.append({"_id": "u_dry_admin", "company_id": COMPANY, "name": "Dry Run Admin",
                      "role": "admin", "account_status": "approved"})
    cols = {
        "projects": [{"_id": PROJECT, "company_id": COMPANY, "name": proj.get("name") or "Dry run",
                      "address": proj.get("address") or proj.get("name") or "Dry run"}],
        "users": users,
        "whatsapp_groups": [{"_id": "g_dry_run", "wa_group_id": GROUP, "project_id": PROJECT,
                             "company_id": COMPANY, "active": True,
                             "group_name": proj.get("group_name") or "Dry run group",
                             "bot_config": server._default_bot_config()}],
        "whatsapp_messages": [],
        "notification_preferences": [{
            "_id": "np_dry", "user_id": None, "project_id": PROJECT, "scope": "project",
            "whatsapp_project": {k: proj[k] for k in ("chase_weekends", "send_window")
                                 if k in proj}}],
    }
    cols[server.WA_OPTINS] = optins
    db = FakeDb(**cols)
    from lib import wa_sender_map
    db[wa_sender_map.COLLECTION].rows.extend(people)
    return db


# ── the model ───────────────────────────────────────────────────────────────

class Scripted:
    """--scripted: answers from each line's expected label (the code around
    the model is what is tested)."""

    def __init__(self, sc):
        self.by_text = {}
        for m in sc["messages"]:
            e = m.get("expect") or {}
            body = wire_body(sc, m)
            items = m.get("model")
            if items is None:
                items = ([{"type": e["type"], "quote": e.get("quote") or body,
                           "due_text": e.get("due_text")}] if e.get("kind") == "item" else [])
            self.by_text[body] = items
        self.calls = 0

    async def __call__(self, messages):
        self.calls += 1
        prompt = messages[-1]["content"]
        target = prompt.split(">>> ", 1)[1].split(": ", 1)[1].strip()
        for text, items in self.by_text.items():
            if text.strip() == target or target.endswith(text.strip()):
                out = [{"summary": text[:60], "owner_text": None, "due_text": None,
                        "importance": "normal", "tags": [], **i} for i in items]
                return {"content": json.dumps({"items": out}),
                        "prompt_tokens": 0, "completion_tokens": 0}
        return {"content": json.dumps({"items": []}), "prompt_tokens": 0, "completion_tokens": 0}


# ── the run ─────────────────────────────────────────────────────────────────

async def run(sc: dict, scripted: bool = False) -> dict:
    import server
    from lib import wa_attention, wa_chase

    db = world(sc)
    sent: List[tuple] = []

    def recorder(name):
        async def _rec(*a, **k):
            sent.append((name, a[:2]))
            return None
        return _rec
    patches = [patch.object(server, "db", db)] + [
        patch.object(server, n, recorder(n)) for n in SEND_PATHS if hasattr(server, n)]
    llm = Scripted(sc) if scripted else None
    if not scripted and not server.OPENAI_API_KEY:
        raise ScenarioError("no OPENAI_API_KEY: run under `railway run`, or pass --scripted")

    msgs = sorted(sc["messages"], key=lambda m: (_at(sc, m["at"]), m["n"]))
    times = [_at(sc, m["at"]) for m in msgs]
    events: List[tuple] = []
    for m, t in zip(msgs, times):
        events.append((t, 0, "msg", m))
    # The attention worker every minute around every message (and the
    # minute after the burst wait).
    ticks = set()
    for t in times:
        base = t.replace(second=0, microsecond=0)
        for i in range(0, 4):
            ticks.add(base + timedelta(minutes=i + 1))
    for t in sorted(ticks):
        events.append((t, 1, "attention", None))
    chase = sc.get("chase") or {}
    for d in chase.get("days") or []:
        day = date.fromisoformat(d)
        for slot, at in wa_chase.SLOTS:
            local = datetime.combine(day, at).replace(tzinfo=_tz(sc))
            events.append(((local + timedelta(minutes=5)).astimezone(timezone.utc), 2, "chase",
                           (d, slot)))
    events.sort(key=lambda e: (e[0], e[1]))

    rows_by_line: Dict[int, dict] = {}
    from bson import ObjectId
    for p in patches:
        p.start()
    try:
        assert server.db is db, "not isolated"
        await server._attention_tick(times[0] - timedelta(minutes=5), llm=llm, probe=False)
        for t, _o, kind, arg in events:
            if kind == "msg":
                parsed = server.parse_inbound_message(payload(sc, arg), vendor="waapi")
                rows_by_line[arg["n"]] = await server._store_group_message(
                    parsed, GROUP, PROJECT, COMPANY, parsed.get("body") or "", t,
                    row_id=ObjectId())
            elif kind == "attention":
                await server._attention_tick(t, llm=llm, probe=False)
            else:
                await server._chase_tick(t)
    finally:
        for p in patches:
            p.stop()
    return {"db": db, "rows": rows_by_line, "sent": sent,
            "model": "scripted" if scripted else wa_attention.MODEL,
            "prompt_version": wa_attention.PROMPT_VERSION,
            "model_calls": llm.calls if llm else None}


# ── what happened, line by line ─────────────────────────────────────────────

def _owner_key(sc, person: Optional[dict]) -> Optional[str]:
    p = person or {}
    jid = str(p.get("jid") or "")
    for key, s in sc["senders"].items():
        if p.get("kind") == "user" and p.get("id") == f"u_{key.lower()}":
            return key
        if p.get("kind") == "sender_map" and p.get("id") == f"m_{key.lower()}":
            return key
        if jid and jid.split("@")[0] == str(s["lid"]):
            return key
    return None


def got_per_line(sc: dict, out: dict) -> Dict[int, dict]:
    items = list(out["db"].attention_items.rows)
    by_mid = {}
    for it in items:
        by_mid.setdefault(it["evidence"]["message_id"], []).append(it)
    line_of = {r["message_id"]: n for n, r in out["rows"].items()}
    got = {}
    for n, row in out["rows"].items():
        mid = row["message_id"]
        mine = [it for it in by_mid.get(mid, []) if it["type"] != "update_review"]
        reviews = [it for it in by_mid.get(mid, []) if it["type"] == "update_review"]
        if mine:
            it = mine[0]
            who = ({"jid": it["evidence"]["sender"] + "@lid"} if it["type"] == "commitment"
                   else it.get("owner"))
            got[n] = {"kind": "item", "type": it["type"],
                      "due_text": (it["history"][0] or {}).get("due_to"),
                      "owner": _owner_key(sc, who),
                      "owner_possibly": bool((it.get("owner") or {}).get("possibly")),
                      "status": it["status"], "id": str(it["_id"])}
            continue
        if reviews:
            got[n] = {"kind": "review", "of": sorted(
                line_of.get(_item_mid(items, c["id"]), 0) for c in reviews[0]["candidates"])}
            continue
        merged_into = [it for it in items if mid in ((it.get("evidence") or {}).get("merged_ids") or [])
                       and it["evidence"]["message_id"] != mid]
        if merged_into:
            got[n] = {"kind": "merged", "into": line_of.get(merged_into[0]["evidence"]["message_id"])}
            continue
        evs = [(it, h) for it in items for h in it.get("history") or []
               if h.get("message_id") == mid and h.get("kind") != "created"]
        if evs:
            it, h = evs[0]
            kind = "state" if h["kind"] == "state" else h["kind"]
            got[n] = {"kind": kind, "of": line_of.get(it["evidence"]["message_id"]),
                      "to": h.get("to"), "also": sorted(
                          line_of.get(i2["evidence"]["message_id"]) for i2, h2 in evs[1:]),
                      "due_text": h.get("due_to")}
            continue
        got[n] = {"kind": "none"}
    return got


def _item_mid(items, iid):
    for it in items:
        if str(it["_id"]) == str(iid):
            return it["evidence"]["message_id"]
    return None


def score_line(want: dict, got: dict) -> tuple:
    """(hard, soft, notes): hard = the label exactly; soft = the right kind of
    thing (a question for a request, the right item with another detail)."""
    notes = []
    wk, gk = want.get("kind"), got.get("kind")
    if wk != gk:
        return False, False, [f"kind {wk} → got {gk}"]
    if wk == "item":
        hard = want.get("type") == got.get("type")
        soft = hard or frozenset({want.get("type"), got.get("type")}) in SOFT_TYPES
        if not hard:
            notes.append(f"type {want.get('type')} → got {got.get('type')}")
        for k in ("due_text", "owner", "owner_possibly"):
            if k in want and want[k] != got.get(k):
                notes.append(f"{k} {want[k]!r} → got {got.get(k)!r}")
                hard = False
        return hard, soft, notes
    if wk in ("state", "flag", "follow_up", "part_done"):
        hard = want.get("of") == got.get("of") and want.get("to", got.get("to")) == got.get("to")
        if want.get("also") is not None and sorted(want["also"]) != got.get("also"):
            notes.append(f"also {want['also']} → got {got.get('also')}")
            hard = False
        if "due_text" in want and want["due_text"] != got.get("due_text"):
            notes.append(f"due {want['due_text']!r} → got {got.get('due_text')!r}")
            hard = False
        if not hard:
            notes.append(f"{wk} of {want.get('of')}→{want.get('to')} got of {got.get('of')}→{got.get('to')}")
        return hard, wk == gk, notes
    if wk == "merged":
        hard = want.get("into") == got.get("into")
        return hard, True, [] if hard else [f"into {want.get('into')} → got {got.get('into')}"]
    if wk == "review":
        hard = sorted(want.get("of") or []) == got.get("of")
        return hard, True, [] if hard else [f"of {want.get('of')} → got {got.get('of')}"]
    return True, True, []


def chase_check(sc: dict, out: dict) -> dict:
    line_of = {r["message_id"]: n for n, r in out["rows"].items()}
    items = {str(it["_id"]): it for it in out["db"].attention_items.rows}
    from lib import wa_chase
    got = []
    for r in out["db"][wa_chase.COLLECTION].rows:
        owner = None
        kind, _, oid = str(r.get("owner_key") or "").partition(":")
        owner = _owner_key(sc, {"kind": kind, "id": oid})
        got.append({"day": r["day"], "slot": r["slot"], "owner": owner,
                    "items": sorted(line_of.get(items[i]["evidence"]["message_id"])
                                    for i in r["item_ids"] if i in items),
                    "text": r.get("text"), "reason": r.get("reason")})
    want = (sc.get("chase") or {}).get("expect") or []

    def key(e):
        return (e["day"], e["slot"], e["owner"], tuple(sorted(e["items"])))
    gk = {key(e): e for e in got}
    wk = {key(e): e for e in want}
    return {"got": got, "missing": [wk[k] for k in wk if k not in gk],
            "unexpected": [gk[k] for k in gk if k not in wk]}


def report(sc: dict, out: dict) -> dict:
    got = got_per_line(sc, out)
    lines = []
    hard = soft = 0
    for m in sc["messages"]:
        want = m.get("expect") or {"kind": "none"}
        g = got.get(m["n"], {"kind": "none"})
        h, s, notes = score_line(want, g)
        hard += h
        soft += s
        lines.append({"n": m["n"], "from": m["from"], "at": m["at"], "text": m["text"],
                      "want": want, "got": g, "hard": h, "soft": s, "notes": notes})
    line_of = {r["message_id"]: n for n, r in out["rows"].items()}
    changes = []
    for it in out["db"].attention_items.rows:
        for h in it.get("history") or []:
            if h.get("kind") == "created":
                continue
            changes.append({"at": h.get("at").isoformat() if isinstance(h.get("at"), datetime) else None,
                            "line": line_of.get(h.get("message_id")),
                            "item_line": line_of.get(it["evidence"]["message_id"]),
                            "kind": h.get("kind"), "from": h.get("from"), "to": h.get("to"),
                            "quote": h.get("quote"), "link": h.get("link"), "note": h.get("note"),
                            "due_to": h.get("due_to")})
    changes.sort(key=lambda c: (c["at"] or "", c["line"] or 0))
    ch = chase_check(sc, out)
    # Counts of the scenario's own lists (not database fields).
    want_chase, missing, unexpected = _expected(sc), ch["missing"], ch["unexpected"]
    return {"scenario": sc.get("name"), "model": out["model"],
            "prompt_version": out["prompt_version"], "model_calls": out["model_calls"],
            "lines": lines, "changes": changes, "chase": ch,
            "score": {"lines": len(lines), "hard": hard, "soft": soft,
                      "chase_expected": len(want_chase),
                      "chase_missing": len(missing),
                      "chase_unexpected": len(unexpected)},
            "sent": [list(map(str, s)) for s in out["sent"]]}


def _expected(sc: dict) -> list:
    return (sc.get("chase") or {}).get("expect") or []


def print_report(r: dict) -> None:
    p = print
    p(f"\n== {r['scenario']} ==  model {r['model']} · prompt {r['prompt_version']}"
      + (f" · {r['model_calls']} calls" if r['model_calls'] is not None else ""))
    p("\nLINES (want → got)")
    for ln in r["lines"]:
        mark = "OK  " if ln["hard"] else ("SOFT" if ln["soft"] else "MISS")
        w, g = ln["want"], ln["got"]
        p(f" {mark} {ln['n']:>2} {ln['from']:<3} {ln['at'][11:16]}  {ln['text'][:58]}")
        p(f"           want {_label(w)}  ·  got {_label(g)}")
        for note in ln["notes"]:
            p(f"           ! {note}")
    p("\nSTATE CHANGES (with evidence)")
    for c in r["changes"] or []:
        p(f"  line {c['line']} → item from line {c['item_line']}: {c['kind']} "
          f"{c['from'] or ''}→{c['to'] or ''}"
          + (f" ({c['note']})" if c["note"] else "") + (f" due {c['due_to']}" if c["due_to"] else "")
          + f"  “{(c['quote'] or '')[:60]}”  [{c['link']}]")
    if not r["changes"]:
        p("  (none)")
    p("\nCHASE (per day and slot)")
    order = {"morning": 0, "midday": 1, "eod": 2, "admin_dm": 3}
    for e in sorted(r["chase"]["got"], key=lambda e: (e["day"], order.get(e["slot"], 9),
                                                      e["owner"] or "")):
        p(f"  {e['day']} {e['slot']:<9} {e['owner'] or '?':<4} lines {e['items']}  "
          f"{(e['text'] or '').splitlines()[0][:60]}")
    if not r["chase"]["got"]:
        p("  (nothing would be chased)")
    for e in r["chase"]["missing"]:
        p(f"  MISSING    {e['day']} {e['slot']} {e['owner']} lines {e['items']}")
    for e in r["chase"]["unexpected"]:
        p(f"  UNEXPECTED {e['day']} {e['slot']} {e['owner']} lines {e['items']}")
    s = r["score"]
    p(f"\nSCORE  lines hard {s['hard']}/{s['lines']} · soft {s['soft']}/{s['lines']}"
      f"  ·  chase {s['chase_expected'] - s['chase_missing']}/{s['chase_expected']} expected,"
      f" {s['chase_unexpected']} unexpected")
    calls = r["sent"]
    if calls:
        p(f"\nSEND PATHS CALLED ({len(calls)}): {calls[:5]}")


def _label(e: dict) -> str:
    k = e.get("kind")
    if k == "item":
        bits = [e.get("type") or "?"]
        if e.get("owner"):
            bits.append(("possibly " if e.get("owner_possibly") else "") + e["owner"])
        if e.get("due_text"):
            bits.append(f"due {e['due_text']}")
        return "item " + ", ".join(bits)
    if k in ("state", "flag", "follow_up", "part_done"):
        return f"{k} line {e.get('of')}" + (f"→{e['to']}" if e.get("to") else "") + (
            f" +{e['also']}" if e.get("also") else "")
    if k == "merged":
        return f"merged into {e.get('into')}"
    if k == "review":
        return f"review of {e.get('of')}"
    return k or "none"


def exit_code(r: dict) -> int:
    if r["sent"]:
        return 3
    if r["chase"]["missing"] or r["chase"]["unexpected"]:
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Attention + chase dry run (nothing sent).")
    ap.add_argument("scenario")
    ap.add_argument("--scripted", action="store_true",
                    help="no model: expected labels are the model's answers")
    ap.add_argument("--json", help="write the full report here")
    a = ap.parse_args(argv)
    import logging
    logging.getLogger("server").setLevel(logging.WARNING)   # the report is the output
    try:
        sc = load(a.scenario)
        out = asyncio.run(run(sc, scripted=a.scripted))
    except ScenarioError as e:
        print(f"cannot run: {e}")
        return 2
    r = report(sc, out)
    print_report(r)
    if a.json:
        Path(a.json).write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
    return exit_code(r)


if __name__ == "__main__":
    sys.exit(main())
