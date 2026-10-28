"""Replay one logged answer on the CURRENT code and diff it. READ-ONLY.

    railway run python scripts/answer_replay.py --company <company id> --id <answer_log id>
    railway run python scripts/answer_replay.py --company <cid> --id <id> --json

Reads the row from answer_log (ONE company's: the read is filtered by
--company, so another company's id is "not found"), asks the same question
again with the same person / job context, and prints what changed:

  * final text      a unified diff, logged vs now
  * records         the plan records (or project-history sources) the model
                    was shown: ids only in the log, only now
  * gate decisions  what the checks decided then and now

BY SURFACE:
  dm     the DM brain (server._dm_brain_answer) in dry_run, exactly as the DM
         eval runs it: as the person (their active opt-in), with that chat's
         history before the logged time, on the logged job. A proposed change,
         a reminder, a sheet says what it WOULD do. The brain's route for the
         person now (on / flag_off / no_key) is printed beside it.
  group  the group agent (server._run_group_agent) on the logged job and group,
         with the group features the row recorded.
  app    the project-history answer (server._memory_answer) on the logged job.

NOTHING IS WRITTEN AND NOTHING IS SENT:
  * the database is wrapped read-only (scripts/dm_brain_eval.ReadOnlyDb:
    every insert / update / delete is dropped and counted -- the count is
    printed); the answer log is never written by a replay;
  * every WhatsApp send path (sends, reactions, typing, sheet images) is
    stubbed out and the WaAPI token is blanked.

The tools read the records as they are NOW: a difference can be the code or
the data. Phone numbers are never printed in full (the log keeps the last 4).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from lib import answer_log  # noqa: E402

#: Every function that could put a message on WhatsApp: replaced for a replay.
SEND_PATHS = ("send_whatsapp_message", "send_whatsapp_dm", "_react_to_message",
              "_dm_send_sheet", "_send_plan_image", "_dm_typing_while",
              "_waapi_post_raw", "_waapi_post_once", "_waapi_send_dm_paced")


def silence(server) -> list:
    """Stub every send path; returns the list each blocked send is noted in."""
    blocked: list = []

    def stub(name):
        async def _blocked(*a, **k):
            blocked.append(name)
            return None
        return _blocked
    for name in SEND_PATHS:
        if hasattr(server, name):
            setattr(server, name, stub(name))
    for token in ("WAAPI_TOKEN", "WAAPI_INSTANCE_ID"):
        if hasattr(server, token):
            setattr(server, token, "")
    return blocked


def _at(row: dict) -> datetime:
    at = row.get("created_at")
    if isinstance(at, datetime):
        return at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


async def _rerun_dm(server, row: dict) -> Dict[str, Any]:
    uid = str(row.get("user_id") or "")
    optin = await server.db[server.WA_OPTINS].find_one({"user_id": uid, "status": "active"})
    chat = (optin or {}).get("chat_id") or ""
    ident = await server._dm_assistant_identity(chat) if chat else None
    if not ident or str(ident.get("company_id")) != str(row.get("company_id")):
        return {"skipped": "no active opt-in for this person in this company now"}
    route = await server._dm_brain_route(ident)
    at = _at(row)
    history = await server._dm_brain_history(chat, at, before=at)
    question = str(row.get("question") or "")
    while history and str(history[-1].get("sender") or "") != "bot" and \
            str(history[-1].get("body") or "").strip()[:40] == question.strip()[:40]:
        history.pop()                                     # the question itself
    pids = row.get("project_ids") or []
    turn = server._answer_turn_begin()
    res = await server._dm_brain_answer(ident, chat, question, history=history,
                                        now=datetime.now(timezone.utc), dry_run=True,
                                        flows=[], active=pids[0] if pids else None)
    final = res.get("reply") or " | ".join(res.get("sent") or [])
    from lib import wa_assistant
    fallback, reason = wa_assistant.answer_outcome("brain", final, None)
    extra = {"stop": res.get("stop"), "unverified": res.get("unverified") or None,
             "verify_retries": res.get("retries"),
             "deflect_retries": res.get("deflect_retries") or None}
    return {"final_text": final, "records": answer_log.records_snapshot(turn["records"]),
            "gates": answer_log.redact(server._dm_gates("brain", extra, fallback, reason)
                                       + turn["gates"]),
            "model": res.get("model"), "route": route[1] if isinstance(route, tuple) else route}


async def _rerun_group(server, row: dict) -> Dict[str, Any]:
    pids = row.get("project_ids") or []
    if not pids:
        return {"skipped": "the logged group answer names no job"}
    features = dict(server._default_bot_config()["features"])
    features.update(row.get("features") or {})
    turn = server._answer_turn_begin()
    trace: list = []
    reply = await server._run_group_agent(
        project_id=pids[0], group_id=row.get("group_id") or "replay@g.us",
        company_id=row.get("company_id"), sender="", body=str(row.get("question") or ""),
        features=features, explicit_mention=True, tool_trace=trace)
    return {"final_text": reply or "", "records": answer_log.records_snapshot(turn["records"]),
            "tools": answer_log.tools_snapshot(trace),
            "gates": answer_log.redact(turn["gates"]), "model": turn.get("model")}


async def _rerun_app(server, row: dict) -> Dict[str, Any]:
    pids = row.get("project_ids") or []
    if not pids:
        return {"skipped": "the logged app answer names no job"}
    p = row.get("params") or {}
    got = await server._memory_answer(str(row.get("company_id")), pids[0],
                                      str(row.get("question") or ""),
                                      p.get("date_from"), p.get("date_to"), phone_view="last4")
    return {"final_text": got.get("text") or "",
            "records": [answer_log.source_snapshot(s) for s in got.get("sources") or []],
            "gates": answer_log.redact(server._memory_gates(got))}


RERUN = {"dm": _rerun_dm, "group": _rerun_group, "app": _rerun_app}


async def replay(server, company_id: str, log_id: str) -> Dict[str, Any]:
    """{found, surface, logged, now, diff} -- or {found: False}. `server` is
    already read-only and silenced (main), or a fake (the tests)."""
    row = await server._answer_log_get(company_id, log_id)
    if not row:
        return {"found": False, "id": log_id}
    surface = row.get("surface") or "dm"
    now = await RERUN.get(surface, _rerun_dm)(server, row)
    if now.get("skipped"):
        return {"found": True, "id": log_id, "surface": surface, "logged": row, "now": now,
                "diff": None}
    now["final_text"] = answer_log.redact(str(now.get("final_text") or "")[:answer_log.MAX_TEXT])
    return {"found": True, "id": log_id, "surface": surface, "logged": row, "now": now,
            "diff": answer_log.diff(row, now)}


def render(out: Dict[str, Any]) -> str:
    if not out.get("found"):
        return f"answer_log {out.get('id')}: not found for this company."
    row, now, d = out["logged"], out["now"], out.get("diff")
    lines = [f"answer_log {out['id']} · {out['surface']} · logged {_at(row).isoformat()} "
             f"on {row.get('code_sha') or '?'}",
             f"question: {row.get('question')}"]
    if now.get("route"):
        lines.append(f"DM brain route for this person now: {now['route']}")
    if not d:
        lines.append(f"not replayed: {now.get('skipped')}")
        return "\n".join(lines)
    lines.append("final text: " + ("SAME" if d["text_same"] else "CHANGED"))
    if not d["text_same"]:
        lines.append(d["text_diff"])
    lines.append("records: " + ("SAME" if d["records_same"] else "CHANGED"))
    if d["records_only_logged"]:
        lines.append("  only in the log: " + ", ".join(d["records_only_logged"]))
    if d["records_only_now"]:
        lines.append("  only now:        " + ", ".join(d["records_only_now"]))
    lines.append("gate decisions: " + ("SAME" if d["gates_same"] else "CHANGED"))
    if not d["gates_same"]:
        lines.append("  logged: " + json.dumps(d["gates_logged"], ensure_ascii=False))
        lines.append("  now:    " + json.dumps(d["gates_now"], ensure_ascii=False))
    return "\n".join(lines)


async def main_async(a) -> int:
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        sys.exit("MONGO_URL / DB_NAME are not set — run under `railway run`.")
    import server
    from scripts.dm_brain_eval import ReadOnlyDb
    ro = ReadOnlyDb(server.db)
    server.db = ro
    blocked = silence(server)
    out = await replay(server, a.company, a.id)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        print(render(out))
    print(f"(writes dropped: {len(ro.dropped)} · sends blocked: {len(blocked)})")
    return 0 if out.get("found") else 1


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--id", required=True, help="the answer_log row id")
    p.add_argument("--company", required=True, help="the company the row belongs to")
    p.add_argument("--json", action="store_true", help="the whole result as JSON")
    return asyncio.run(main_async(p.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
