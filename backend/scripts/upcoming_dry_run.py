"""Upcoming dry run: a scripted group chat through the REAL chat worker.

    python scripts/upcoming_dry_run.py scripts/upcoming_eval/job_oct_2026.json
    python scripts/upcoming_dry_run.py --scripted scripts/upcoming_eval/job_oct_2026.json

WHAT RUNS. Every message of the scenario is stored in an in-memory database
(tests._fake_mongo.FakeDb, swapped in for server.db) at the time it was
sent, and server._upcoming_chat_tick runs a minute after each one -- the
cheap filter, the model (gpt-4o-mini, the production call; or with
--scripted, the scenario's own answers), and every check in code
(lib/upcoming.decide). No production collection is read or written;
nothing is sent to anyone.

SCORE.
  expect.events      one row per event the chat should leave behind, keyed by
                     the message that first said it: its kind (any of a
                     list), agency, day, time, status (open / cancelled) and
                     how many times it moved. HARD when every field matches.
  expect.nothing_from  messages that must leave no event behind (vague, an
                     ambiguous day, past, a question, a weekday that is not
                     that date's).
  expect.one_of      a title word or agency that must name exactly one open event (a
                     repeat of the same event is one event).

EXIT CODES
  0  all pass      1  any FAIL      2  the scenario cannot be run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "dry_run_not_used")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "dry-run-only")

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

COMPANY = "co_upc_dry"
PROJECT = "proj_upc_dry"
GROUP = "120363000000000999@g.us"
SEND_PATHS = ("send_whatsapp_message", "send_whatsapp_dm", "_waapi_post_raw",
              "_react_to_message", "_react_or_say")


class ScenarioError(Exception):
    pass


def load(path: str) -> dict:
    try:
        sc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ScenarioError(f"cannot read {path}: {e}")
    for k in ("senders", "messages", "expect"):
        if not sc.get(k):
            raise ScenarioError(f"scenario has no {k}")
    return sc


def _at(sc: dict, s: str) -> datetime:
    tz = ZoneInfo(sc.get("tz") or "America/New_York") if ZoneInfo else timezone.utc
    return datetime.fromisoformat(s).replace(tzinfo=tz).astimezone(timezone.utc)


def world(sc: dict):
    from tests._fake_mongo import FakeDb
    rows = []
    for m in sc["messages"]:
        s = sc["senders"][m["from"]]
        at = _at(sc, m["at"])
        rows.append({"_id": f"row_{m['id']}", "group_id": GROUP, "project_id": PROJECT,
                     "company_id": COMPANY, "sender": s["phone"], "sender_name": s["name"],
                     "body": m["text"], "message_id": f"3EB0{m['id']}", "timestamp": at,
                     "created_at": at, "from_me": False})
    return FakeDb(
        projects=[{"_id": PROJECT, "company_id": COMPANY, "name": sc.get("project", "Dry run")}],
        whatsapp_groups=[{"_id": "g_dry", "wa_group_id": GROUP, "group_name": "Site",
                          "project_id": PROJECT, "company_id": COMPANY, "active": True}],
        whatsapp_messages=[]), rows


class Scripted:
    """The scenario's own answers: `scripted` maps a message id to the
    events a model would return. "$OPEN:<id>" is the id of the event that
    message <id> created."""

    def __init__(self, sc: dict, db):
        self.sc, self.db, self.calls = sc, db, 0

    async def __call__(self, messages):
        self.calls += 1
        target = messages[-1]["content"].split(">>> ", 1)[1]
        for m in self.sc["messages"]:
            if m["text"][:500] in target:
                out = []
                for e in (self.sc.get("scripted") or {}).get(m["id"], []):
                    e = dict(e)
                    eid = str(e.get("event_id") or "")
                    if eid.startswith("$OPEN:"):
                        ref = f"row_{eid.split(':', 1)[1]}"
                        hit = [r for r in self.db.upcoming_events.rows
                               if r.get("source_ref") == ref]
                        e["event_id"] = str(hit[0]["_id"]) if hit else "none"
                    out.append(e)
                return {"content": json.dumps({"events": out}),
                        "prompt_tokens": 0, "completion_tokens": 0}
        return {"content": json.dumps({"events": []}), "prompt_tokens": 0,
                "completion_tokens": 0}


async def run(sc: dict, scripted: bool = False) -> dict:
    import server
    logging.getLogger("server").setLevel(logging.WARNING)   # the per-run lines
    db, rows = world(sc)
    sent = []

    async def no_send(*a, **k):
        sent.append((a, k))

    patches = [patch.object(server, "db", db),
               patch.dict(os.environ, {"UPCOMING_DISABLED": ""})]
    patches += [patch.object(server, name, no_send) for name in SEND_PATHS
                if hasattr(server, name)]
    llm = Scripted(sc, db) if scripted else None
    if not scripted and not server.OPENAI_API_KEY:
        raise ScenarioError("no OPENAI_API_KEY: run with --scripted, or with the key set")
    report = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "skipped": {}}
    trace: list = []
    for p in patches:
        p.start()
    try:
        first = rows[0]["created_at"] - timedelta(minutes=5)
        await server._upcoming_chat_tick(now=first, llm=llm)          # cursor starts
        for row in rows:
            db.whatsapp_messages.rows.append(row)
            rep = await server._upcoming_chat_tick(now=row["created_at"] + timedelta(minutes=1),
                                                   llm=llm, trace=trace)
            for k in ("calls", "prompt_tokens", "completion_tokens"):
                report[k] += rep.get(k, 0)
            for k, v in (rep.get("skipped") or {}).items():
                report["skipped"][k] = report["skipped"].get(k, 0) + v
    finally:
        for p in reversed(patches):
            p.stop()
    report["events"] = db.upcoming_events.rows
    report["sent"] = sent
    report["trace"] = trace
    return report


def _cites(ev: dict, row_id: str) -> bool:
    if ev.get("source_ref") == row_id:
        return True
    if (ev.get("evidence") or {}).get("message_row_id") == row_id:
        return True
    return any(a.get("message_row_id") == row_id for a in ev.get("also_seen") or [])


def score(sc: dict, out: dict) -> dict:
    e = sc["expect"]
    events = out["events"]
    rows = []
    for want in e.get("events") or []:
        ref = f"row_{want['from']}"
        hit = [x for x in events if x.get("source_ref") == ref]
        notes = []
        if not hit:
            notes.append("no event")
        else:
            ev = hit[0]
            kinds = want["kind"] if isinstance(want["kind"], list) else [want["kind"]]
            if ev.get("kind") not in kinds:
                notes.append(f"kind {ev.get('kind')} (want {'/'.join(kinds)})")
            if want.get("agency") and (ev.get("agency") or "").lower() != want["agency"].lower():
                notes.append(f"agency {ev.get('agency')} (want {want['agency']})")
            if ev.get("date") != want["date"]:
                notes.append(f"day {ev.get('date')} (want {want['date']})")
            if "time" in want and ev.get("time") != want["time"]:
                notes.append(f"time {ev.get('time')} (want {want['time']})")
            if ev.get("status") != want.get("status", "open"):
                notes.append(f"status {ev.get('status')} (want {want.get('status', 'open')})")
            moves = 0
            for step in ev.get("history") or []:
                if step.get("action") == "rescheduled":
                    moves += 1
            if moves != want.get("moves", 0):
                notes.append(f"moved {moves}x (want {want.get('moves', 0)})")
        rows.append({"case": f"event from {want['from']}: {want.get('what', '')}",
                     "verdict": "FAIL" if notes else "HARD", "notes": notes,
                     "got": [{k: hit[0].get(k) for k in ("kind", "agency", "title", "date",
                                                          "time", "status")}] if hit else []})
    for mid in e.get("nothing_from") or []:
        ref = f"row_{mid}"
        hit = [x for x in events if _cites(x, ref)]
        text = next(m["text"] for m in sc["messages"] if m["id"] == mid)
        rows.append({"case": f"nothing from {mid}: {text[:60]}",
                     "verdict": "FAIL" if hit else "PASS",
                     "notes": [f"made {x.get('title')} on {x.get('date')}" for x in hit],
                     "got": []})
    for word in e.get("one_of") or []:
        # By agency OR title: the model may title it "Gas service appointment"
        # with agency National Grid.
        live = [x for x in events if x.get("status") == "open"
                and (word.lower() in (x.get("title") or "").lower()
                     or word.lower() == (x.get("agency") or "").lower())]
        rows.append({"case": f"one open '{word}' event",
                     "verdict": "PASS" if len(live) == 1 else "FAIL",
                     "notes": [] if len(live) == 1 else [f"{len(live)} open"], "got": []})
    count = {"HARD": 0, "PASS": 0, "FAIL": 0}
    for r in rows:
        count[r["verdict"]] += 1
    # Per message: what the model said, the date words in and the day out,
    # and what the code did (or why it skipped).
    per_msg = []
    for m in sc["messages"]:
        ref = f"row_{m['id']}"
        steps = [t for t in out.get("trace") or [] if t.get("row_id") == ref]
        if not steps:
            per_msg.append({"id": m["id"], "text": m["text"], "line": "no event from the model"})
        for t in steps:
            if t.get("action") is None:
                per_msg.append({"id": m["id"], "text": m["text"], "line": t["reason"]})
                continue
            res = t.get("resolved") or {}
            got = (res.get("date").isoformat() + (f" {res['time']}" if res.get("time") else "")
                   if res.get("date") else (f"skip:{res['skip']}" if res.get("skip") else "-"))
            what = t["op"] + (f" ({t['reason']})" if t.get("reason") else "")
            per_msg.append({"id": m["id"], "text": m["text"], "line":
                            f"{t['action']} {t.get('kind') or ''} · date {t.get('date_text')!r}"
                            f" -> {got} · {what} · quote {t.get('quote')!r}"})
    return {"scenario": sc.get("name"), "rows": rows, "score": count,
            "sent": out["sent"], "calls": out["calls"], "skipped": out["skipped"],
            "tokens": (out["prompt_tokens"], out["completion_tokens"]), "per_message": per_msg}


def exit_code(r: dict) -> int:
    return 1 if r["score"]["FAIL"] or r["sent"] else 0


def show(r: dict) -> str:
    lines = [f"UPCOMING DRY RUN  {r['scenario']}", ""]
    for row in r["rows"]:
        lines.append(f" {row['verdict']:<5} {row['case']}")
        for g in row["got"]:
            lines.append(f"           {g}")
        for n in row["notes"]:
            lines.append(f"           ! {n}")
    lines += ["", "PER MESSAGE (model -> code)"]
    for p in r.get("per_message") or []:
        lines.append(f"  {p['id']:<4} {p['text'][:58]:<58}  {p['line']}")
    s, sent = r["score"], r["sent"]
    lines += ["", f"skips (code): {r['skipped']}",
              f"model calls {r['calls']} · tokens in/out {r['tokens'][0]}/{r['tokens'][1]}"
              f" · sent {len(sent)}",
              f"SCORE  events hard {s['HARD']} · nothing/one-of pass {s['PASS']} · FAIL {s['FAIL']}"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scenario")
    ap.add_argument("--scripted", action="store_true",
                    help="use the scenario's own answers instead of the model")
    ap.add_argument("--json", help="also write the full result here")
    a = ap.parse_args(argv)
    try:
        sc = load(a.scenario)
        r = score(sc, asyncio.run(run(sc, scripted=a.scripted)))
    except ScenarioError as e:
        print(f"cannot run: {e}", file=sys.stderr)
        return 2
    print(show(r))
    if a.json:
        Path(a.json).write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
    return exit_code(r)


if __name__ == "__main__":
    sys.exit(main())
