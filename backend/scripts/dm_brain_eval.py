"""Replay every real DM through the new brain on BOTH DeepInfra models. READ-ONLY.

    railway run python scripts/dm_brain_eval.py --days 30
    railway run python scripts/dm_brain_eval.py --days 30 --email you@company.com --out dm_brain_eval

Needs MONGO_URL / DB_NAME and QWEN_API_KEY (DeepInfra -- the key the vision
calls already use; `railway run` brings all three). The models are
DM_BRAIN_MODEL (default Qwen/Qwen3.8-Flash) and DM_BRAIN_ESCALATE_MODEL
(default Qwen/Qwen3.8-Max). Only DM_BRAIN_MODEL runs unless --models names
more (--models Qwen/Qwen3.8-Flash,Qwen/Qwen3.8-Max compares both).

FIRST, A PREFLIGHT (nothing else runs if it fails, unless --skip-check):
  * GET {base}/models: each model id must be on DeepInfra's list (the Qwen
    3.8 ids it has are printed when one is not);
  * one tiny tool-calling request per model: it must come back as a tool
    call, else that model can't run the brain.

FIXED CASES (FIXED_CASES), each with what is expected and PASS / FAIL checks,
run on each model:
  Tue Oct 20, 9:02 AM:   "Update on 588", "Dot and Akron", "Arkon is framer"
  Tue Oct 20, 12:28 PM:  the walk ("All of the above is for 3rd floor moving
                         up to 4th now", on a walk rebuilt in memory),
                         "How many days hvac worked in 588", the no-deflect rule
  Languages:             a Spanish and a Yiddish DM (the answer in their language)

THEN every answer in whatsapp_dm_answers (the last --days), oldest first: the
question as asked, this DM's messages before it, the answer that went out
then (the old pipeline), and each model's answer -- with the tools it called,
its quality checks, seconds and cost.

QUALITY (per DM, per model; automatic -- the side-by-side is for your eyes):
  answered      not "can't answer" / sent elsewhere, not a failure text
  evidence      every number and id came from the tools (or it said so)
  whole         not cut off (finish "length", an open *, nothing after tools)
  actions       "sent / saved / cancelled / done" only with the tool that did it
  language      the answer is in the language of the question (EN/ES/YI)
plus each fixed case's own checks. COST is DeepInfra's own estimated_cost
from each response's usage (shown as "n/a" if it sends none); SECONDS is the
model time for the whole turn (tool calls included).

NOTHING IS WRITTEN AND NOTHING IS SENT:
  * the database is wrapped read-only (every insert / update / delete is
    dropped and counted -- the count is printed);
  * the brain runs in dry-run: a proposed change, a reminder, a sheet or a
    report says what it WOULD do; no state is stored;
  * WhatsApp sends and reactions are stubbed out.

The tools read the records as they are NOW; compare behavior, not numbers.
Writes <out>/side_by_side.md (for review) and <out>/results.jsonl. Phone
numbers are scrubbed; names are kept (it's your data, for your review).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


class _ReadOnlyCollection:
    _READS = ("find", "find_one", "aggregate", "count_documents", "distinct",
              "estimated_document_count", "list_indexes", "index_information", "name")

    def __init__(self, coll, dropped: list):
        self._c, self._dropped = coll, dropped

    def __getattr__(self, name):
        if name in self._READS:
            return getattr(self._c, name)
        if name.startswith(("insert", "update", "replace", "delete", "find_one_and", "bulk_write",
                            "create_index", "drop")):
            async def _blocked(*a, **k):
                self._dropped.append(f"{self._c.name}.{name}")
                return SimpleNamespace(inserted_id=None, inserted_ids=[], modified_count=0,
                                       matched_count=0, deleted_count=0, upserted_id=None,
                                       acknowledged=False)
            return _blocked
        return getattr(self._c, name)


class ReadOnlyDb:
    """A motor database that reads and never writes."""

    def __init__(self, db):
        self._db = db
        self.dropped: list = []

    def __getitem__(self, name):
        return _ReadOnlyCollection(self._db[name], self.dropped)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return _ReadOnlyCollection(getattr(self._db, name), self.dropped)


# ── THE FIXED CASES ──────────────────────────────────────────────────────────

FIXED_CASES = [
    {"id": "update_588", "kind": "dm", "when": "Tue Oct 20, 9:02 AM", "said": "Update on 588",
     "old": "588 Update / DOB Status: / Want the full list?",
     "expected": "A real update in a few lines -- who is on site plus at least one more record "
                 "(DOB/DOT, open items, coming up) -- no empty heading, nothing cut."},
    {"id": "dot_and_akron", "kind": "dm", "when": "Tue Oct 20, 9:02 AM", "said": "Dot and Akron",
     "old": "No Dot or Akron sub",
     "expected": "DOT read as the agency (DOT records for the job) and \"Akron\" matched to Arkon "
                 "on the subs list; never \"no Dot or Akron sub\"."},
    {"id": "arkon_framer", "kind": "dm", "when": "Tue Oct 20, 9:02 AM", "said": "Arkon is framer",
     "old": "I don't have that in the records.",
     "expected": "Understood as a fact about the sub: proposes saving Arkon's trade as framing "
                 "(set_sub_trade) and asks for yes; nothing is saved without it."},
    {"id": "walk_location", "kind": "walk", "when": "Tue Oct 20, 12:28-2:08 PM (walk)",
     "said": "All of the above is for 3rd floor moving up to 4th now",
     "old": "Tagged #2-#4 only (the photos since the last text) and added the words as a note.",
     "expected": "Every untagged photo since the last location (here #1-#4) -> 3rd floor; no note; "
                 "the next photos default to 4th floor, and the reply says so."},
    {"id": "hvac_days", "kind": "dm", "when": "Tue Oct 20, 12:28-2:08 PM",
     "said": "How many days hvac worked in 588",
     "old": "... check with the site manager.",
     "expected": "HVAC -> the HVAC sub(s) on 588 -> distinct days on site, with the date range "
                 "(and man-days); never sends them to someone else."},
    {"id": "no_deflect", "kind": "dm", "when": "rule 3",
     "said": "How many days did the elevator guys work on 588",
     "old": "(the rule; the old pipeline answered such questions with 'check with ...')",
     "expected": "Calls the tools that could hold it (sub_attendance with a trade, find_sub) before "
                 "any \"I don't have that\"; never \"check with X\"; a can't-answer says what it "
                 "checked and is logged with the tools tried."},
    {"id": "spanish", "kind": "dm", "when": "language", "said": "¿Cuántos trabajadores hay hoy en 588?",
     "old": "(language case)", "lang": "es",
     "expected": "Today's headcount at 588 from the check-ins, answered in Spanish."},
    {"id": "yiddish", "kind": "dm", "when": "language", "said": "וויפל ארבעטער זענען היינט אויף 588?",
     "old": "(language case)", "lang": "yi",
     "expected": "Today's headcount at 588 from the check-ins, answered in Yiddish (Hebrew letters)."},
]
#: The six that must all PASS before merge.
REQUIRED = ("update_588", "dot_and_akron", "arkon_framer", "walk_location", "hvac_days", "no_deflect")

_EMPTY_HEADING = re.compile(r"^\s*[*_]*[^\n:]{1,40}:[*_]*\s*$", re.MULTILINE)


def _case_checks(case_id: str, reply: str, trace: list) -> Dict[str, bool]:
    """Each fixed DM case's own checks, from the reply and the tools called."""
    from lib import dm_brain
    tools = [t["tool"] for t in trace]
    low = reply.lower()
    if case_id == "update_588":
        return {"who's on site (headcount / who_on_site)": bool({"headcount", "who_on_site"} & set(tools)),
                "at least 2 different tools": len(set(tools)) >= 2,
                "no empty heading": not _EMPTY_HEADING.search(reply),
                "a real answer (2+ lines or 120+ chars)": reply.count("\n") >= 1 or len(reply) >= 120}
    if case_id == "dot_and_akron":
        return {"dot_status called": "dot_status" in tools,
                "Akron read as Arkon": "arkon" in low or bool({"list_subs", "find_sub"} & set(tools)),
                "never 'no Dot or Akron sub'": not re.search(r"no\s+dot\s+or\s+akron|no\s+(?:dot|akron)\s+sub", low)}
    if case_id == "arkon_framer":
        st = [t for t in trace if t["tool"] == "set_sub_trade"]
        return {"set_sub_trade proposed": bool(st),
                "trade is framing": any(re.search(r"fram", str((t.get("args") or {}).get("trade") or ""), re.I)
                                        for t in st),
                "asks for yes": bool(re.search(r"\byes\b|\bconfirm\b", low))}
    if case_id == "hvac_days":
        return {"sub_attendance called": "sub_attendance" in tools,
                "never 'check with X'": not dm_brain.refers_elsewhere(reply),
                "answers with days": bool(re.search(r"\bdays?\b", reply, re.I)) and not dm_brain.cant_answer(reply)}
    if case_id == "no_deflect":
        return {"a tool before any can't-answer": bool(trace) or not dm_brain.cant_answer(reply),
                "never 'check with X'": not dm_brain.refers_elsewhere(reply)}
    if case_id in ("spanish", "yiddish"):
        want = "es" if case_id == "spanish" else "yi"
        return {"headcount from the check-ins": bool({"headcount", "who_on_site", "site_headcount"} & set(tools)),
                f"answered in {'Spanish' if want == 'es' else 'Yiddish'}": dm_brain.language(reply) == want}
    return {}


_ACTING = {"send_sheet": "sent", "send_report": "sent", "resend_my_brief": "sent",
           "cancel_pending_change": "cancelled"}


def _quality(question: str, reply: str, res: dict) -> Dict[str, bool]:
    """The automatic quality checks for any DM."""
    from lib import dm_brain
    did = {_ACTING[t["tool"]] for t in res.get("trace") or []
           if t["tool"] in _ACTING and not t.get("error")}
    return {"answered": bool(reply) and reply not in (dm_brain.FAILED_TEXT, dm_brain.TRUNCATED_TEXT,
                                                       dm_brain.ACTION_UNVERIFIED_TEXT)
            and not dm_brain.cant_answer(reply),
            "evidence": not res.get("unverified"),
            "whole": res.get("stop") != "truncated" and not dm_brain.truncated(reply),
            "actions": all(c in did for c in dm_brain.action_claims(reply)),
            "language": dm_brain.language(question) == dm_brain.language(reply) or not reply}


def _clean(s) -> str:
    from lib import dm_brain
    return dm_brain.redact_phones(str(s or ""))


# ── PREFLIGHT: the ids are on DeepInfra, and they call tools ────────────────

_PING_TOOL = {"type": "function", "function": {
    "name": "ping", "description": "Answer the check. Always call this.",
    "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}}}


async def preflight(client, models: List[str], base: str) -> Dict[str, Any]:
    """{ok, listed: {model: bool}, tools: {model: bool}, qwen38: [ids], error}."""
    out: Dict[str, Any] = {"ok": True, "listed": {}, "tools": {}, "qwen38": [], "error": ""}
    try:
        page = await client.models.list()
        ids = sorted(m.id for m in page.data)
    except Exception as e:
        out.update(ok=False, error=f"GET {base}/models failed: {type(e).__name__}: {e}")
        return out
    out["qwen38"] = [i for i in ids if "qwen3.8" in i.lower()]
    for m in models:
        out["listed"][m] = m in ids
        if not out["listed"][m]:
            out["ok"] = False
            continue
        try:
            r = await client.chat.completions.create(
                model=m, temperature=0, max_tokens=200, tools=[_PING_TOOL], tool_choice="auto",
                messages=[{"role": "user", "content": "This is a check: call the ping tool with ok=true."}])
            calls = r.choices[0].message.tool_calls or []
            out["tools"][m] = bool(calls) and calls[0].function.name == "ping"
        except Exception as e:
            out["tools"][m] = False
            out["error"] += f" {m}: {type(e).__name__}: {e}"
        if not out["tools"][m]:
            out["ok"] = False
    return out


# ── RUNS ─────────────────────────────────────────────────────────────────────

async def _rows(server, days: int, limit: int, user: str = "") -> list:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = {"created_at": {"$gte": since}}
    if user:
        q["user_id"] = user
    rows = await server.db.whatsapp_dm_answers.find(q).sort([("created_at", 1)]).to_list(limit)
    # A confirm or a cancel to the new brain's proposals is not a question.
    return [r for r in rows if r.get("path") not in ("brain_confirm",)]


async def _identity(server, uid: str, cache: dict):
    if uid not in cache:
        optin = await server.db[server.WA_OPTINS].find_one({"user_id": uid, "status": "active"})
        chat = (optin or {}).get("chat_id") or ""
        ident = await server._dm_assistant_identity(chat) if chat else None
        cache[uid] = (chat, ident)
    return cache[uid]


def _one(res: dict, started: float) -> dict:
    """What a model's run shows: the answer, tools, retries, usage."""
    usage = res.get("usage") or {}
    return {"answer": _clean(res.get("reply") or " | ".join(res.get("sent") or [])),
            "tools": [f"{t['tool']}({json.dumps(t.get('args') or {}, ensure_ascii=False)})"
                      for t in res.get("trace") or []],
            "trace": res.get("trace") or [],
            "rounds": res.get("rounds"), "verify_retries": res.get("retries"),
            "deflect_retries": res.get("deflect_retries"), "unverified": res.get("unverified") or [],
            "stop": res.get("stop"), "models_used": usage.get("models") or [],
            "cut_retries": res.get("cut_retries"), "claim_retries": res.get("claim_retries"),
            "you_retries": res.get("you_retries"), "draft": _clean(res.get("draft") or ""),
            "input_tokens": usage.get("input"), "output_tokens": usage.get("output"),
            "reasoning_tokens": usage.get("reasoning"),
            "cost_usd": usage.get("cost_usd"),
            "seconds": round(time.monotonic() - started, 1)}


async def _dm_run(server, ident: dict, chat: str, question: str, history: list, model: str) -> dict:
    server._DM_MODEL.set(model)
    started = time.monotonic()
    try:
        res = await server._dm_brain_answer(ident, chat, question, history=history,
                                            now=datetime.now(timezone.utc), dry_run=True,
                                            flows=[], active=None)
    finally:
        server._DM_MODEL.set(None)
    return _one(res, started) | {"_res": res}


async def _replay_one(server, row: dict, cache: dict, models: List[str]) -> dict:
    uid = str(row.get("user_id") or "")
    chat, ident = await _identity(server, uid, cache)
    out = {"when": row.get("created_at").isoformat() if row.get("created_at") else "",
           "user": uid[-6:], "question": _clean(row.get("question")),
           "old_path": row.get("path"), "old_answer": _clean(row.get("answer")), "runs": {}}
    if not ident:
        out["skipped"] = "no active opt-in for this person now"
        return out
    at = row.get("created_at")
    if isinstance(at, datetime) and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    history = await server._dm_brain_history(chat, at, before=at)
    q = str(row.get("question") or "").strip()
    while history and str(history[-1].get("sender") or "") != "bot" and \
            str(history[-1].get("body") or "").strip()[:40] == q[:40]:
        history.pop()                                     # the question itself
    out["history_turns"] = len(history)
    for m in models:
        run = await _dm_run(server, ident, chat, q, history, m)
        res = run.pop("_res")
        run["quality"] = _quality(q, res.get("reply") or "", res)
        run.pop("trace", None)
        out["runs"][m] = run
    return out


async def _walk_case(server, ident: dict, case: dict, model: str) -> dict:
    """The walk case: a walk rebuilt in memory, the message read by the walk
    brain on `model`, applied to that copy (the read-only db drops every
    write; sends are captured)."""
    from lib import punch
    now = datetime.now(timezone.utc)
    jobs = ident.get("projects") or []
    job = next((p for p in jobs if "588" in str(p.get("name") or p.get("address") or "")),
               jobs[0] if jobs else None)
    items = []
    for n in range(1, 5):
        it = punch.new_item(n, "", photo_key=f"eval/{n}.jpg", message_id=f"eval-{n}", at=now)
        it["captured"] = n
        items.append(it)
    items[0]["text"] = "Cracked tile"                 # a text came after photo #1
    sess = {"_id": "eval-walk", "user_id": ident.get("user_id"), "company_id": ident.get("company_id"),
            "status": "capturing", "items": items, "photos": [], "detail": punch.DEFAULT_DETAIL,
            "project_id": str((job or {}).get("_id") or (job or {}).get("id") or ""),
            "job_name": str((job or {}).get("name") or ""), "group_loc_v2": True,
            "batch_mark": 1, "batch_prev": [1], "loc_mark": 0}
    sent: list = []

    async def _capture(chat, text, *a, **k):
        sent.append(str(text))
    was = server.send_whatsapp_message
    server.send_whatsapp_message = _capture
    server._WALK_BRAIN.set(True)
    server._DM_MODEL.set(model)
    started = time.monotonic()
    try:
        await server._punch_think(ident, sess, "eval@c.us", {}, case["said"], now)
    finally:
        server._WALK_BRAIN.set(False)
        server._DM_MODEL.set(None)
        server.send_whatsapp_message = was
    nxt = punch.new_item(5, "", photo_key="eval/5.jpg", message_id="eval-5", at=now)
    punch.apply_default_location(nxt, sess.get("default_loc"))
    placed = {it["n"]: punch.location_label(it) for it in sess["items"]}
    noted = [it["n"] for it in sess["items"] if it.get("notes")]
    checks = {
        "all four on 3rd floor": all(str(it.get("floor")) == "3" for it in sess["items"]),
        "no note added": not noted,
        "next photos: 4th floor": str((sess.get("default_loc") or {}).get("floor")) == "4",
        "next photo #5 -> 4th floor": str(nxt.get("floor")) == "4",
        "reply says 4th": any("4th" in m for m in sent)}
    return {"answer": _clean("\n".join(sent)) or "(no reply)",
            "detail": "After: " + "; ".join(f"#{n} {lab or '(no place)'}" for n, lab in placed.items())
                      + f"; next photo #5: {punch.location_label(nxt) or '(no place)'}"
                      + (f"; notes on {noted}" if noted else ""),
            "checks": checks, "seconds": round(time.monotonic() - started, 1), "cost_usd": None}


async def _fixed(server, rows: list, cache: dict, email: str, models: List[str]) -> list:
    """Run FIXED_CASES on each model as the person who asked live (their
    logged HVAC question), else --email, else the first replayed person."""
    uid, live_old = "", ""
    hit = await server.db.whatsapp_dm_answers.find_one(
        {"question": {"$regex": "(?i)hvac"}}, sort=[("created_at", -1)])
    if hit:
        uid, live_old = str(hit.get("user_id") or ""), _clean(hit.get("answer"))
    if not uid and email:
        u = await server.db.users.find_one({"email": email.strip().lower()})
        uid = str((u or {}).get("_id") or "")
    if not uid and rows:
        uid = str(rows[0].get("user_id") or "")
    chat, ident = await _identity(server, uid, cache) if uid else ("", None)
    out = []
    for case in FIXED_CASES:
        r = {"id": case["id"], "when": case["when"], "question": case["said"],
             "old_answer": live_old if case["id"] == "hvac_days" and live_old else case["old"],
             "expected": case["expected"], "fixed": True, "required": case["id"] in REQUIRED, "runs": {}}
        for m in models:
            if not ident:
                r["runs"][m] = {"answer": "(skipped: no opted-in person to run it as; pass --email)",
                                "checks": {}, "pass": False}
                continue
            try:
                if case["kind"] == "walk":
                    run = await _walk_case(server, ident, case, m)
                else:
                    run = await _dm_run(server, ident, chat, case["said"], [], m)
                    res = run.pop("_res")
                    run["checks"] = _case_checks(case["id"], res.get("reply") or "", res.get("trace") or [])
                    run["quality"] = _quality(case["said"], res.get("reply") or "", res)
                    run.pop("trace", None)
            except Exception as e:
                run = {"answer": f"(error: {type(e).__name__}: {e})", "checks": {}}
            run["pass"] = bool(run.get("checks")) and all(run["checks"].values())
            r["runs"][m] = run
        out.append(r)
    return out


# ── THE REPORT ───────────────────────────────────────────────────────────────

def _money(v) -> str:
    return "n/a" if v is None else f"${v:.4f}"


def _q(run: dict) -> str:
    q = run.get("quality") or {}
    return f"{sum(q.values())}/{len(q)}" if q else "-"


def _fully_ok(run: dict) -> bool:
    """Every quality check of one run passed (eval results, not a collection)."""
    q = run.get("quality") or {}
    return bool(q) and all(q.values())


def _passed(run: dict) -> bool:
    return bool(run.get("pass"))


def _stats(results: list, fixed: list, models: List[str]) -> List[str]:
    lines = ["| Model | Required fixed cases | All fixed cases | DMs fully OK | Median s | P90 s | "
             "Total cost |", "|---|---|---|---|---|---|---|"]
    for m in models:
        runs = [r["runs"][m] for r in results if m in r.get("runs", {})]
        fruns = [(f, f["runs"].get(m) or {}) for f in fixed]
        secs = sorted(x.get("seconds") or 0 for x in runs + [fr for _, fr in fruns])
        costs = [x.get("cost_usd") for x in runs + [fr for _, fr in fruns] if x.get("cost_usd") is not None]
        ok = len([x for x in runs if _fully_ok(x)])
        req = [_passed(fr) for f, fr in fruns if f["required"]]
        p90 = secs[max(0, int(round(0.9 * len(secs))) - 1)] if secs else 0
        lines.append(f"| {m} | {sum(bool(x) for x in req)}/{len(req)} | "
                     f"{len([fr for _, fr in fruns if _passed(fr)])}/{len(fruns)} | {ok}/{len(runs)} | "
                     f"{statistics.median(secs) if secs else 0:.1f} | {p90:.1f} | "
                     f"{_money(sum(costs)) if costs else 'n/a'} |")
    return lines


def _quote(text: str) -> str:
    return "> " + str(text or "").replace("\n", "\n> ")


def _md(results: list, models: List[str], dropped: list, fixed: Optional[list] = None,
        check: Optional[dict] = None) -> str:
    from lib import dm_brain
    fixed = fixed or []
    lines = [f"# DM brain eval: old vs {' vs '.join(models)} (DeepInfra)", "",
             f"{len(results)} logged DMs + {len(fixed)} fixed cases, replayed "
             f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Tools read today's records; compare "
             f"behavior, not exact numbers. Writes blocked by the read-only wrapper: {len(dropped)}.", ""]
    if check:
        lines += ["## Preflight (DeepInfra)", ""]
        for m in models:
            lines.append(f"- {m}: on /models {'✓' if check['listed'].get(m) else '✗'}, "
                         f"tool calling {'✓' if check['tools'].get(m) else '✗'}")
        if check.get("qwen38"):
            lines.append(f"- Qwen 3.8 ids on DeepInfra: {', '.join(check['qwen38'])}")
        if check.get("error"):
            lines.append(f"- {check['error'].strip()}")
        lines.append("")
    lines += ["## Summary", ""] + _stats(results, fixed, models) + [""]
    if fixed:
        lines += ["## Fixed cases", ""]
        for r in fixed:
            verdicts = ", ".join(f"{m}: {'PASS' if (r['runs'].get(m) or {}).get('pass') else 'FAIL'}"
                                 for m in models)
            lines += [f"### {r['id']}{' (required)' if r['required'] else ''} — {verdicts}", "",
                      f"**Asked:** {r['question']}", "", f"**Expected:** {r['expected']}", "",
                      "**Old** (live):", "", _quote(r.get("old_answer")), ""]
            for m in models:
                run = r["runs"].get(m) or {}
                lines += [f"**{m}** — {'PASS' if run.get('pass') else 'FAIL'} · {run.get('seconds', '-')}s · "
                          f"{_money(run.get('cost_usd'))}", "", _quote(run.get("answer")), ""]
                if run.get("detail"):
                    lines.append(run["detail"])
                if run.get("tools"):
                    lines.append("Tools: " + "; ".join(run["tools"]))
                if run.get("checks"):
                    lines.append("Checks: " + "; ".join(f"{'✓' if ok else '✗'} {k}"
                                                        for k, ok in run["checks"].items()))
                lines.append("")
    cant = [(r, m) for r in results for m in models
            if dm_brain.cant_answer((r.get("runs", {}).get(m) or {}).get("answer"))]
    lines += ["## Can't answer (new)", "",
              f"{len(cant)} new answers say they can't answer or send them elsewhere."
              + (" Each, with the tools it tried:" if cant else ""), ""]
    for r, m in cant:
        run = r["runs"][m]
        lines.append(f"- [{m}] {r['question'][:100]} → {str(run.get('answer'))[:140]} "
                     f"(tools: {', '.join(run.get('tools') or []) or 'none'})")
    lines += ["", "## Replayed DMs", ""]
    for i, r in enumerate(results, 1):
        lines += [f"### {r.get('n', i)}. {r['when'][:16].replace('T', ' ')} — {r['question'][:120]}", "",
                  f"**Old** ({r.get('old_path')}):", "", _quote(r["old_answer"]), ""]
        if r.get("skipped"):
            lines += [f"_(skipped: {r['skipped']})_", ""]
            continue
        for m in models:
            run = r["runs"].get(m) or {}
            q = run.get("quality") or {}
            bad = [k for k, ok in q.items() if not ok]
            lines += [f"**{m}** — quality {_q(run)}{(' (' + ', '.join(bad) + ')') if bad else ''} · "
                      f"{run.get('seconds', '-')}s · {_money(run.get('cost_usd'))} · "
                      f"{run.get('input_tokens') or 0}+{run.get('output_tokens') or 0} tokens", "",
                      _quote(run.get("answer")), ""]
            if run.get("tools"):
                lines.append("Tools: " + "; ".join(run["tools"]))
            retried = [f"{k} ×{run[k + '_retries']}" for k in ("verify", "cut", "claim", "you", "deflect")
                       if run.get(k + "_retries")]
            if retried:
                lines.append(f"_re-asked (same model): {', '.join(retried)}; finish: {run.get('stop')}_")
            lines.append("")
    return "\n".join(lines)


async def main_async(a) -> int:
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        sys.exit("MONGO_URL / DB_NAME are not set — run under `railway run`.")
    if not os.environ.get("QWEN_API_KEY"):
        sys.exit("QWEN_API_KEY (DeepInfra) is not set — run under `railway run`.")
    import server
    from lib import dm_brain
    models = [m.strip() for m in (a.models or dm_brain.MODEL).split(",") if m.strip()]
    check = None
    if not a.skip_check:
        print(f"Preflight: {', '.join(models)} on {dm_brain.API_BASE} …", flush=True)
        check = await preflight(server._dm_brain_client(), models, dm_brain.API_BASE)
        for m in models:
            print(f"  {m}: listed={check['listed'].get(m)} tool_calling={check['tools'].get(m)}")
        if check.get("qwen38"):
            print(f"  Qwen 3.8 ids on DeepInfra: {', '.join(check['qwen38'])}")
        if not check["ok"]:
            print(f"  {check.get('error', '').strip()}")
            sys.exit("Preflight failed: set DM_BRAIN_MODEL / DM_BRAIN_ESCALATE_MODEL (or --models) to ids "
                     "from the list above that call tools. Nothing was run.")
    ro = ReadOnlyDb(server.db)
    server.db = ro

    async def _no_send(*a, **k):
        return None
    server.send_whatsapp_message = _no_send
    server._react_to_message = _no_send

    rows = await _rows(server, a.days, a.limit, a.user)
    numbered = list(enumerate(rows, 1))
    if a.pick:
        want = {int(x) for x in a.pick.split(",") if x.strip().isdigit()}
        numbered = [(i, r) for i, r in numbered if i in want]
    cache: dict = {}
    print(f"Fixed cases ({len(FIXED_CASES)}) on {', '.join(models)} …", flush=True)
    fixed = await _fixed(server, rows, cache, a.email, models)
    for r in fixed:
        print(f"[fixed {r['id']}] " + ", ".join(
            f"{m}: {'PASS' if (r['runs'].get(m) or {}).get('pass') else 'FAIL'}" for m in models), flush=True)
    if a.fixed_only:
        numbered = []
    print(f"{len(numbered)} logged DMs to replay …", flush=True)
    results = []
    for i, row in numbered:
        try:
            r = await _replay_one(server, row, cache, models)
        except Exception as e:
            r = {"when": str(row.get("created_at")), "question": _clean(row.get("question")),
                 "old_path": row.get("path"), "old_answer": _clean(row.get("answer")),
                 "runs": {}, "skipped": f"error: {type(e).__name__}: {e}"}
        r["n"] = i
        results.append(r)
        print(f"[{i}/{len(rows)}] {r['question'][:60]!r}\n   old: {r['old_answer'][:90]!r}" + "".join(
            f"\n   {m.split('/')[-1]}: {str((r['runs'].get(m) or {}).get('answer'))[:90]!r} "
            f"({(r['runs'].get(m) or {}).get('seconds')}s, {_money((r['runs'].get(m) or {}).get('cost_usd'))})"
            for m in models), flush=True)
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in fixed + results),
        encoding="utf-8")
    (outdir / "side_by_side.md").write_text(_md(results, models, ro.dropped, fixed, check), encoding="utf-8")
    print("\n" + "\n".join(_stats(results, fixed, models)))
    print(f"\nWrote {outdir / 'side_by_side.md'} and {outdir / 'results.jsonl'}")
    print(f"Writes blocked: {len(ro.dropped)} {sorted(set(ro.dropped))[:10]}")
    req_fail = [f"{r['id']} on {m}" for r in fixed if r["required"]
                for m in models[:1] if not (r["runs"].get(m) or {}).get("pass")]
    if req_fail:
        print(f"REQUIRED fixed cases failing on {models[0]}: {', '.join(req_fail)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--user", default="", help="only this user id")
    ap.add_argument("--out", default="dm_brain_eval")
    ap.add_argument("--email", default="", help="run the fixed cases as this person (if the live "
                                                 "HVAC question isn't in the log)")
    ap.add_argument("--models", default="", help="comma-separated DeepInfra ids (default: DM_BRAIN_MODEL; "
                                                  "add DM_BRAIN_ESCALATE_MODEL to compare)")
    ap.add_argument("--fixed-only", action="store_true", help="only the fixed cases")
    ap.add_argument("--pick", default="", help="only these logged DMs, by their number in the "
                                                "side-by-side (e.g. 37 or 30,31,32)")
    ap.add_argument("--skip-check", action="store_true", help="skip the /models + tool-calling preflight")
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
