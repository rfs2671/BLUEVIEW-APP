"""Replay every real DM through the new brain, with the REAL model. READ-ONLY.

    railway run python scripts/dm_brain_eval.py --days 30
    railway run python scripts/dm_brain_eval.py --days 30 --out dm_brain_eval   # folder

Needs MONGO_URL / DB_NAME (railway run) and ANTHROPIC_API_KEY (Claude); the
read tools that search project history and drawings also use OPENAI_API_KEY,
as they do live.

For every answer in whatsapp_dm_answers (the last --days), oldest first:
  * the question as it was asked, by the person who asked it;
  * this DM's messages before it (the brain's 20 turns, as they were);
  * the answer that went out then (the old pipeline);
  * the brain's answer now, with the tools it called.

NOTHING IS WRITTEN AND NOTHING IS SENT:
  * the database is wrapped read-only (every insert / update / delete is
    dropped and counted -- the count is printed);
  * the brain runs in dry-run: a proposed change, a reminder, a sheet or a
    report says what it WOULD do; no state is stored;
  * WhatsApp sends and reactions are stubbed out.

The tools read the records as they are NOW (today's check-ins, today's
punch list), not as they were when the question was asked; the "Now" the
model sees is the replay time. Old answers are compared for behavior, not
for the same numbers.

FIXED CASES (FIXED_CASES, shown first in side_by_side.md with what is
expected and a PASS / FAIL check), from Tue Oct 20 12:28-2:08 PM:
  1. walk: "All of the above is for 3rd floor moving up to 4th now" on a walk
     rebuilt in memory (4 photos, a text after #1, no location yet) -- the
     walk brain on the new model;
  2. "How many days hvac worked in 588";
  3. the no-deflect rule: a trade question that may have no answer.
A "Can't answer" section lists every new answer that says it can't answer,
with the tools it tried.

Writes <out>/side_by_side.md (for review) and <out>/results.jsonl. Phone
numbers are scrubbed; names are kept (it's your data, for your review).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
import re

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


FIXED_CASES = [
    {"id": "walk_location", "kind": "walk", "when": "Tue Oct 20, 12:28-2:08 PM (walk)",
     "said": "All of the above is for 3rd floor moving up to 4th now",
     "old": "Tagged #2-#4 only (the photos since the last text) and added the words as a note.",
     "expected": "Every untagged photo since the last location (here #1-#4) -> 3rd floor; no note; "
                 "the next photos default to 4th floor, and the reply says so."},
    {"id": "hvac_days", "kind": "dm", "when": "Tue Oct 20, 12:28-2:08 PM",
     "said": "How many days hvac worked in 588", "find": r"hvac",
     "old": "... check with the site manager.",
     "expected": "HVAC -> the HVAC sub(s) on 588 -> distinct days on site, with the date range "
                 "(and man-days); never sends them to someone else."},
    {"id": "no_deflect", "kind": "dm", "when": "rule 3",
     "said": "How many days did the elevator guys work on 588",
     "old": "(the rule; the old pipeline answered such questions with 'check with ...')",
     "expected": "Calls the tools that could hold it (sub_attendance with a trade, find_sub) before "
                 "any \"I don't have that\"; never \"check with X\"; a can't-answer says what it "
                 "checked and is logged with the tools tried."},
]


def _clean(s) -> str:
    from lib import dm_brain
    return dm_brain.redact_phones(str(s or ""))


async def _rows(server, days: int, limit: int, user: str = "") -> list:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = {"created_at": {"$gte": since}}
    if user:
        q["user_id"] = user
    rows = await server.db.whatsapp_dm_answers.find(q).sort([("created_at", 1)]).to_list(limit)
    # A confirm or a cancel to the new brain's proposals is not a question.
    return [r for r in rows if r.get("path") not in ("brain_confirm",)]


async def _replay_one(server, row: dict, cache: dict) -> dict:
    uid = str(row.get("user_id") or "")
    if uid not in cache:
        optin = await server.db[server.WA_OPTINS].find_one({"user_id": uid, "status": "active"})
        chat = (optin or {}).get("chat_id") or ""
        ident = await server._dm_assistant_identity(chat) if chat else None
        cache[uid] = (chat, ident)
    chat, ident = cache[uid]
    out = {"when": row.get("created_at").isoformat() if row.get("created_at") else "",
           "user": uid[-6:], "question": _clean(row.get("question")),
           "old_path": row.get("path"), "old_answer": _clean(row.get("answer"))}
    if not ident:
        out["new_answer"] = "(skipped: no active opt-in for this person now)"
        return out
    at = row.get("created_at")
    if isinstance(at, datetime) and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    history = await server._dm_brain_history(chat, at, before=at)
    q = str(row.get("question") or "").strip()
    while history and str(history[-1].get("sender") or "") != "bot" and \
            str(history[-1].get("body") or "").strip()[:40] == q[:40]:
        history.pop()                                     # the question itself
    started = time.monotonic()
    res = await server._dm_brain_answer(ident, chat, q, history=history,
                                        now=datetime.now(timezone.utc), dry_run=True,
                                        flows=[], active=None)
    out.update({
        "new_answer": _clean(res.get("reply") or " | ".join(res.get("sent") or [])),
        "tools": [f"{t['tool']}({json.dumps(t.get('args') or {}, ensure_ascii=False)})"
                  for t in res.get("trace") or []],
        "rounds": res.get("rounds"), "verify_retries": res.get("retries"),
        "deflect_retries": res.get("deflect_retries"),
        "unverified": res.get("unverified") or [], "stop": res.get("stop"),
        "usage": res.get("usage") or {}, "seconds": round(time.monotonic() - started, 1),
        "history_turns": len(history)})
    return out


async def _walk_case(server, ident: dict, case: dict) -> dict:
    """The walk case: a walk rebuilt in memory, the message read by the walk
    brain on the new model, applied to that copy (the read-only db drops
    every write; sends are captured)."""
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
    server.send_whatsapp_message = _capture
    server._WALK_BRAIN.set(True)
    started = time.monotonic()
    try:
        await server._punch_think(ident, sess, "eval@c.us", {}, case["said"], now)
    finally:
        server._WALK_BRAIN.set(False)
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
    return {"new_answer": _clean("\n".join(sent)) or "(no reply)",
            "detail": "After: " + "; ".join(f"#{n} {lab or '(no place)'}" for n, lab in placed.items())
                      + f"; next photo #5: {punch.location_label(nxt) or '(no place)'}"
                      + (f"; notes on {noted}" if noted else ""),
            "checks": checks, "seconds": round(time.monotonic() - started, 1)}


async def _dm_case(server, ident: dict, chat: str, case: dict) -> dict:
    from lib import dm_brain
    started = time.monotonic()
    res = await server._dm_brain_answer(ident, chat, case["said"], history=[],
                                        now=datetime.now(timezone.utc), dry_run=True,
                                        flows=[], active=None)
    reply = str(res.get("reply") or "")
    trace = res.get("trace") or []
    tools = [t["tool"] for t in trace]
    if case["id"] == "hvac_days":
        checks = {
            "sub_attendance called": "sub_attendance" in tools,
            "never 'check with X'": not dm_brain.refers_elsewhere(reply),
            "answers with days": bool(re.search(r"\bdays?\b", reply, re.I)) and not dm_brain.cant_answer(reply)}
    else:
        checks = {
            "a tool before any can't-answer": bool(trace) or not dm_brain.cant_answer(reply),
            "never 'check with X'": not dm_brain.refers_elsewhere(reply)}
    return {"new_answer": _clean(reply), "usage": res.get("usage") or {},
            "tools": [f"{t['tool']}({json.dumps(t.get('args') or {}, ensure_ascii=False)})" for t in trace],
            "rounds": res.get("rounds"), "verify_retries": res.get("retries"),
            "deflect_retries": res.get("deflect_retries"), "checks": checks,
            "seconds": round(time.monotonic() - started, 1)}


async def _fixed(server, rows: list, cache: dict, email: str) -> list:
    """Run FIXED_CASES as the person who asked live (their logged HVAC
    question), else --email, else the first replayed person."""
    uid = ""
    live_old = ""
    hit = await server.db.whatsapp_dm_answers.find_one(
        {"question": {"$regex": "(?i)hvac"}}, sort=[("created_at", -1)])
    if hit:
        uid, live_old = str(hit.get("user_id") or ""), _clean(hit.get("answer"))
    if not uid and email:
        u = await server.db.users.find_one({"email": email.strip().lower()})
        uid = str((u or {}).get("_id") or "")
    if not uid and rows:
        uid = str(rows[0].get("user_id") or "")
    optin = await server.db[server.WA_OPTINS].find_one({"user_id": uid, "status": "active"}) if uid else None
    chat = (optin or {}).get("chat_id") or ""
    ident = await server._dm_assistant_identity(chat) if chat else None
    out = []
    for case in FIXED_CASES:
        r = {"id": case["id"], "when": case["when"], "question": case["said"],
             "old_answer": live_old if case["id"] == "hvac_days" and live_old else case["old"],
             "expected": case["expected"], "fixed": True}
        if not ident:
            r["new_answer"] = "(skipped: no opted-in person to run it as; pass --email)"
            out.append(r)
            continue
        try:
            r.update(await (_walk_case(server, ident, case) if case["kind"] == "walk"
                            else _dm_case(server, ident, chat, case)))
        except Exception as e:
            r["new_answer"] = f"(error: {type(e).__name__}: {e})"
        r["pass"] = bool(r.get("checks")) and all(r["checks"].values())
        out.append(r)
    return out


def _md(results: list, model: str, dropped: list, usage: dict, fixed: Optional[list] = None) -> str:
    lines = [f"# DM brain eval: old vs new ({model})", "",
             f"{len(results)} questions, replayed {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. "
             "Tools read today's records; compare behavior, not exact numbers.", "",
             f"Tokens: input {usage['input']:,}, output {usage['output']:,}, cache read "
             f"{usage['cache_read']:,}, cache write {usage['cache_write']:,}. "
             f"Writes blocked by the read-only wrapper: {len(dropped)}.", ""]
    if fixed:
        lines += ["## Fixed cases (Tue Oct 20, 12:28-2:08 PM)", ""]
        for r in fixed:
            verdict = "PASS" if r.get("pass") else "FAIL"
            lines += [f"### {r['id']}: {verdict} — {r['question']}", "",
                      f"**Expected:** {r['expected']}", "",
                      f"**Old** (live):", "", "> " + str(r.get("old_answer") or "").replace("\n", "\n> "), "",
                      "**New**:", "", "> " + str(r.get("new_answer") or "").replace("\n", "\n> "), ""]
            if r.get("detail"):
                lines.append(r["detail"])
            if r.get("tools"):
                lines.append("Tools: " + "; ".join(r["tools"]))
            if r.get("checks"):
                lines.append("Checks: " + "; ".join(f"{'✓' if ok else '✗'} {k}" for k, ok in r["checks"].items()))
            lines.append("")
    from lib import dm_brain
    cant = [r for r in results if dm_brain.cant_answer(r.get("new_answer"))]
    lines += ["## Can't answer (new)", "",
              f"{len(cant)} of {len(results)} new answers say they can't answer or send them elsewhere."
              + (" Each, with the tools it tried:" if cant else ""), ""]
    for r in cant:
        lines.append(f"- {r['question'][:100]} → {str(r.get('new_answer'))[:140]} "
                     f"(tools: {', '.join(r.get('tools') or []) or 'none'})")
    lines += ["", "## Replayed DMs", ""]
    for i, r in enumerate(results, 1):
        lines += [f"## {i}. {r['when'][:16].replace('T', ' ')} — {r['question'][:120]}", "",
                  f"**Old** ({r.get('old_path')}):", "", "> " + r["old_answer"].replace("\n", "\n> "), "",
                  "**New**:", "", "> " + str(r.get("new_answer") or "").replace("\n", "\n> "), ""]
        if r.get("tools"):
            lines.append("Tools: " + "; ".join(r["tools"]))
        meta = [f"{r.get('seconds')}s", f"{r.get('rounds')} rounds"]
        if r.get("verify_retries"):
            meta.append(f"re-asked {r['verify_retries']}x for {r.get('unverified')}")
        lines += ["", "_" + ", ".join(m for m in meta if m and "None" not in m) + "_", ""]
    return "\n".join(lines)


async def main_async(a) -> int:
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        sys.exit("MONGO_URL / DB_NAME are not set — run under `railway run`.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set — add it to the service (or this shell) first.")
    import server
    from lib import dm_brain
    ro = ReadOnlyDb(server.db)
    server.db = ro

    async def _no_send(*a, **k):
        return None
    server.send_whatsapp_message = _no_send
    server._react_to_message = _no_send

    rows = await _rows(server, a.days, a.limit, a.user)
    results, cache = [], {}
    print(f"Fixed cases ({len(FIXED_CASES)}) with {dm_brain.MODEL} …", flush=True)
    fixed = await _fixed(server, rows, cache, a.email)
    server.send_whatsapp_message = _no_send
    for r in fixed:
        print(f"[fixed {r['id']}] {'PASS' if r.get('pass') else 'FAIL'}: {str(r.get('new_answer'))[:120]!r}",
              flush=True)
    print(f"{len(rows)} answers to replay with {dm_brain.MODEL} …", flush=True)
    total = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for i, row in enumerate(rows, 1):
        try:
            r = await _replay_one(server, row, cache)
        except Exception as e:
            r = {"when": str(row.get("created_at")), "question": _clean(row.get("question")),
                 "old_path": row.get("path"), "old_answer": _clean(row.get("answer")),
                 "new_answer": f"(error: {type(e).__name__}: {e})"}
        for k in total:
            total[k] += int((r.get("usage") or {}).get(k) or 0)
        results.append(r)
        print(f"[{i}/{len(rows)}] {r['question'][:60]!r}\n   old: {r['old_answer'][:100]!r}\n"
              f"   new: {str(r.get('new_answer'))[:100]!r}", flush=True)
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    for r in fixed:
        for k in total:
            total[k] += int((r.get("usage") or {}).get(k) or 0)
    (outdir / "results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in fixed + results),
        encoding="utf-8")
    (outdir / "side_by_side.md").write_text(_md(results, dm_brain.MODEL, ro.dropped, total, fixed),
                                            encoding="utf-8")
    print(f"\nWrote {outdir / 'side_by_side.md'} and {outdir / 'results.jsonl'}")
    print(f"Tokens: {total}. Writes blocked: {len(ro.dropped)} {sorted(set(ro.dropped))[:10]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--user", default="", help="only this user id")
    ap.add_argument("--out", default="dm_brain_eval")
    ap.add_argument("--email", default="", help="run the fixed cases as this person (if the live "
                                                 "HVAC question isn't in the log)")
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
