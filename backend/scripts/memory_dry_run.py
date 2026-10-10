"""Project memory search DRY RUN: a scripted job's history through the real
indexing, retrieval and answer path, with no real people, no real database
and nothing sent.

Windows (PowerShell, from backend\\):
    railway run python scripts\\memory_dry_run.py scripts\\memory_eval\\job_2wk_2026_09.json

macOS / Linux:
    railway run python scripts/memory_dry_run.py scripts/memory_eval/job_2wk_2026_09.json

Options:
    --scripted     no model and no embeddings API: words hashed into vectors,
                   and each question's expected sources are the "model's"
                   answer -- tests indexing, retrieval and the quote check
                   (what CI runs)
    --json PATH    also write the full report as JSON

WHAT RUNS
  The scenario's group messages and filed daily reports go into an IN-MEMORY
  database (tests/_fake_mongo.FakeDb, swapped in for server.db); the real
  indexer (_memory_index_tick) indexes and embeds them
  (text-embedding-3-small unless --scripted); each question goes through
  _memory_answer: retrieval, the real answer model (gpt-4o), and the verbatim
  quote check. No production collection is read or written; nothing is sent.

SCORE, PER QUESTION
  expect.none        the reply must be "I can't find that in the project
                     history." -- anything else is a FAIL (an answer with no
                     source to it).
  expect.sources     scenario ids (m3, d2:activity:0) that must be cited;
                     HARD when all are cited, SOFT when at least one is.
  expect.contains    words the reply must contain (claims, quotes, sources).
  expect.mode        "timeline" for a full-story question;
  expect.min_entries how many dated entries it needs at least.

EXIT CODES
  0  no FAIL      1  a FAIL      2  the scenario cannot be run
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
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

COMPANY = "co_mem_dry"
PROJECT = "proj_mem_dry"
SEND_PATHS = ("send_whatsapp_message", "send_whatsapp_dm", "_waapi_post_raw",
              "_react_to_message", "_react_or_say")


class ScenarioError(Exception):
    pass


def load(path: str) -> dict:
    try:
        sc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ScenarioError(f"cannot read {path}: {e}")
    for k in ("senders", "messages", "questions"):
        if not sc.get(k):
            raise ScenarioError(f"scenario has no {k}")
    return sc


def _tz(sc):
    return ZoneInfo(sc.get("tz") or "America/New_York") if ZoneInfo else timezone.utc


def _at(sc, s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=_tz(sc)).astimezone(timezone.utc)


def _group_jid(key: str) -> str:
    return f"1203630{int(hashlib.sha1(key.encode()).hexdigest(), 16) % 10**11:011d}@g.us"


def world(sc: dict):
    from tests._fake_mongo import FakeDb
    import server
    from lib import wa_sender_map
    users, optins, people = [], [], []
    for key, s in sc["senders"].items():
        jid = f"{s['lid']}@lid"
        if s.get("user"):
            uid = f"u_{key.lower()}"
            users.append({"_id": uid, "company_id": COMPANY, "name": s["name"],
                          "role": s["user"].get("role", "pm"), "account_status": "approved"})
            optins.append({"_id": f"o_{key.lower()}", "user_id": uid, "company_id": COMPANY,
                           "chat_digits": s["lid"], "status": "active"})
        if s.get("people"):
            people.append({"_id": f"sm_{key.lower()}", "company_id": COMPANY,
                           "sender_jid": jid, **s["people"]})
    proj = sc.get("project") or {}
    groups = sc.get("groups") or {"S": "Dry run group"}
    messages = []
    for m in sc["messages"]:
        s = sc["senders"][m["from"]]
        at = _at(sc, m["at"])
        messages.append({
            "_id": f"row_{m['id']}", "group_id": _group_jid(m.get("group") or "S"),
            "project_id": PROJECT, "company_id": COMPANY, "sender": s["lid"],
            "sender_jid": f"{s['lid']}@lid", "sender_name": s["name"], "body": m["text"],
            "message_id": f"3EB0{m['id']}", "timestamp": at, "created_at": at})
    logs = []
    for d in sc.get("daily_reports") or []:
        by = sc["senders"].get(d.get("by") or "", {})
        when = _at(sc, f"{d['date']} 17:30")
        logs.append({
            "_id": f"log_{d['id']}", "project_id": PROJECT, "company_id": COMPANY,
            "log_type": "daily_jobsite", "status": "submitted", "date": d["date"],
            "cp_name": by.get("name") or "", "created_at": when, "updated_at": when,
            "data": {"general_description": d.get("general") or "",
                     "activities": [{"company": a.get("company"), "trade": a.get("trade"),
                                     "work_description": a.get("work"),
                                     "work_locations": a.get("where")}
                                    for a in d.get("activities") or []],
                     "observations": d.get("observations") or []}})
    cols = {
        "companies": [{"_id": COMPANY, "name": "Dry run GC"}],
        "projects": [{"_id": PROJECT, "company_id": COMPANY,
                      "name": proj.get("name") or "Dry run",
                      "address": proj.get("address") or proj.get("name") or "Dry run"}],
        "users": users,
        "whatsapp_groups": [{"_id": f"g_{k}", "wa_group_id": _group_jid(k), "project_id": PROJECT,
                             "company_id": COMPANY, "active": True, "group_name": name}
                            for k, name in groups.items()],
        "whatsapp_messages": messages,
        "logbooks": logs,
    }
    cols[server.WA_OPTINS] = optins
    db = FakeDb(**cols)
    db[wa_sender_map.COLLECTION].rows.extend(people)
    return db


# ── --scripted: hashed vectors and a model that cites what it was told ──────

def hashed_vector(text: str, dims: int = 256) -> List[float]:
    from lib import project_memory
    v = [0.0] * dims
    for t in project_memory.terms(text):
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        v[h % dims] += 1.0 if (h >> 8) % 2 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def scenario_text(sc: dict, ref: str) -> str:
    """The words a scenario id stands for (m3, d2:activity:0)."""
    from lib import project_memory
    if ":" not in ref:
        return next(m["text"] for m in sc["messages"] if m["id"] == ref)
    did, key = ref.split(":", 1)
    d = next(x for x in sc["daily_reports"] if x["id"] == did)
    log = world_log(d)
    return next(e["text"] for e in project_memory.daily_report_entries(log) if e["key"] == key)


def world_log(d: dict) -> dict:
    return {"data": {"general_description": d.get("general") or "",
                     "activities": [{"company": a.get("company"), "trade": a.get("trade"),
                                     "work_description": a.get("work"),
                                     "work_locations": a.get("where")}
                                    for a in d.get("activities") or []],
                     "observations": d.get("observations") or []}}


class Scripted:
    """The 'model' quotes the expected sources (the first 200 characters of
    each) -- only when retrieval put them in front of it, or the quote check
    drops them."""

    def __init__(self, sc: dict, question: dict):
        self.sc, self.q = sc, question

    async def __call__(self, messages):
        e = self.q.get("expect") or {}
        if e.get("none"):
            return json.dumps({"claims": []})
        block = messages[-1]["content"]
        claims = []
        for ref in e.get("sources") or []:
            words = scenario_text(self.sc, ref)
            quote = words[:200]
            m = re.search(r"\[(S\d+)\][^\n]*\n" + re.escape(words[:60]), block)
            claims.append({"text": " ".join(e.get("contains") or []) or quote,
                           "source": m.group(1) if m else "S0", "quote": quote})
        return json.dumps({"claims": claims})


# ── the run ─────────────────────────────────────────────────────────────────

async def run(sc: dict, scripted: bool = False) -> dict:
    import server
    db = world(sc)
    sent: List[tuple] = []

    def recorder(name):
        async def _rec(*a, **k):
            sent.append((name, a[:2]))
            return None
        return _rec

    patches = [patch.object(server, "db", db), patch.object(server, "MEMORY_EMBED_PAUSE", 0),
               patch.dict(server._MEMORY_ATLAS, {"ok": False})] + [
        patch.object(server, n, recorder(n)) for n in SEND_PATHS if hasattr(server, n)]
    if scripted:
        async def fake_embed(texts):
            return [hashed_vector(t) for t in texts]
        patches.append(patch.object(server, "_memory_embed_many", fake_embed))
    elif not server.OPENAI_API_KEY:
        raise ScenarioError("no OPENAI_API_KEY: run under `railway run`, or pass --scripted")
    for p in patches:
        p.start()
    try:
        for _ in range(50):
            rep = await server._memory_index_tick()
            if not (rep["messages"] or rep["reports"] or rep["embedded"]):
                break
        answers = []
        for q in sc["questions"]:
            llm = Scripted(sc, q) if scripted else None
            got = await server._memory_answer(COMPANY, PROJECT, q["q"], llm=llm)
            answers.append(got)
        return {"db": db, "answers": answers, "sent": sent}
    finally:
        for p in reversed(patches):
            p.stop()


def _ref_of(sc: dict, src: dict) -> Optional[str]:
    """The scenario id a cited source stands for."""
    sid = str(src.get("id") or "")
    if sid.startswith("wa:row_"):
        return sid[len("wa:row_"):]
    m = re.match(r"dr:log_([^:]+):(.+)$", sid)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return None


def score(sc: dict, q: dict, got: dict) -> dict:
    from lib import project_memory
    e = q.get("expect") or {}
    text = got["text"]
    by_sid = {s["sid"]: s for s in got["sources"]}
    cited = sorted({r for r in (_ref_of(sc, by_sid[c["sid"]]) for c in got["claims"]) if r})
    notes = []
    if e.get("none"):
        ok = text == project_memory.NO_SOURCE
        if not ok:
            notes.append("answered a question the records cannot answer")
        return {"q": q["q"], "verdict": "PASS" if ok else "FAIL", "cited": cited,
                "notes": notes, "text": text, "mode": got["mode"]}
    if text == project_memory.NO_SOURCE:
        return {"q": q["q"], "verdict": "MISS", "cited": [], "notes": ["no source found"],
                "text": text, "mode": got["mode"]}
    want = e.get("sources") or []
    hit = [r for r in want if r in cited]
    n_hit, n_want = len(hit), len(want)
    if n_hit < n_want:
        notes.append(f"not cited: {[r for r in want if r not in cited]}")
    low = text.lower()
    missing = [w for w in e.get("contains") or [] if w.lower() not in low]
    if missing:
        notes.append(f"missing words: {missing}")
    if e.get("mode") == "timeline" and got["mode"] != "timeline":
        notes.append("not a timeline")
    claims = got["claims"]
    n_claims = len(claims)
    if n_claims < int(e.get("min_entries") or 1):
        notes.append(f"{n_claims} entries, want {e.get('min_entries')}+")
    hard = not notes
    verdict = "HARD" if hard else ("SOFT" if hit else "MISS")
    return {"q": q["q"], "verdict": verdict, "cited": cited, "notes": notes,
            "text": text, "mode": got["mode"]}


def report(sc: dict, out: dict) -> dict:
    rows = [score(sc, q, a) for q, a in zip(sc["questions"], out["answers"])]
    count = {k: 0 for k in ("HARD", "SOFT", "MISS", "PASS", "FAIL")}
    for row in rows:
        verdict = row.get("verdict")
        count[verdict] = count.get(verdict, 0) + 1
    return {"scenario": sc.get("name"), "questions": rows, "score": count,
            "sent": out["sent"]}


def exit_code(r: dict) -> int:
    if r["sent"]:
        return 3
    return 1 if r["score"]["FAIL"] else 0


def print_report(r: dict, model: str) -> None:
    print(f"\n== {r['scenario']} ==  {model}\n")
    for i, row in enumerate(r["questions"], 1):
        print(f" {row['verdict']:<5} {i:>2}. {row['q']}  [{row['mode']}]")
        for n in row["notes"]:
            print(f"           ! {n}")
        for line in row["text"].splitlines():
            print(f"           {line}")
        print()
    s = r["score"]
    sent = r["sent"]
    n_sent = len(sent)
    print(f"SCORE  answers hard {s['HARD']} · soft {s['SOFT']} · miss {s['MISS']}  ·  "
          f"no-source questions pass {s['PASS']} · FAIL {s['FAIL']}"
          + (f"  ·  SENT {n_sent}" if n_sent else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Project memory dry run (nothing sent).")
    ap.add_argument("scenario")
    ap.add_argument("--scripted", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    import logging
    logging.getLogger("server").setLevel(logging.WARNING)
    try:
        sc = load(a.scenario)
        out = asyncio.run(run(sc, scripted=a.scripted))
    except ScenarioError as e:
        print(f"cannot run: {e}")
        return 2
    r = report(sc, out)
    from lib import project_memory
    print_report(r, "scripted" if a.scripted else
                 f"model {project_memory.ANSWER_MODEL} · {project_memory.EMBED_MODEL}")
    if a.json:
        Path(a.json).write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
    return exit_code(r)


if __name__ == "__main__":
    sys.exit(main())
