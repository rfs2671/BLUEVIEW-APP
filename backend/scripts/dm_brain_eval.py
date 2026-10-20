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
        "unverified": res.get("unverified") or [], "stop": res.get("stop"),
        "usage": res.get("usage") or {}, "seconds": round(time.monotonic() - started, 1),
        "history_turns": len(history)})
    return out


def _md(results: list, model: str, dropped: list, usage: dict) -> str:
    lines = [f"# DM brain eval: old vs new ({model})", "",
             f"{len(results)} questions, replayed {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. "
             "Tools read today's records; compare behavior, not exact numbers.", "",
             f"Tokens: input {usage['input']:,}, output {usage['output']:,}, cache read "
             f"{usage['cache_read']:,}, cache write {usage['cache_write']:,}. "
             f"Writes blocked by the read-only wrapper: {len(dropped)}.", ""]
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
    print(f"{len(rows)} answers to replay with {dm_brain.MODEL} …", flush=True)
    results, cache = [], {}
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
    (outdir / "results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in results), encoding="utf-8")
    (outdir / "side_by_side.md").write_text(_md(results, dm_brain.MODEL, ro.dropped, total),
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
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
