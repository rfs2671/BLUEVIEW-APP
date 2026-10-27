"""Project memory, diagnosed on the live database. READ-ONLY unless --backfill.

    railway run python scripts/memory_diag.py --project 588 --query "core drill"
    railway run python scripts/memory_diag.py --project 588 --query "core drill" --answer
    railway run python scripts/memory_diag.py --project 588 --backfill

Prints, for one project:
  1. INDEX     its group messages vs its project_memory rows: counts, newest
               times, embedded or not, and every indexable message that has
               no memory row (with the indexer's cursor beside it).
  2. INGEST    whether the company is skipped as a test company, and the
               indexer's last run.
  3. ATLAS     $listSearchIndexes (status, queryable), then the exact
               $search and $vectorSearch the server runs for --query, raw
               hits with searchScore / vectorSearchScore; the in-code
               fallback's hits; and what _memory_search returns.
  4. SCOPE     the group's company/job vs the project's, and the last DM
               answers on this project: which company and job they searched.
  --answer     also runs _memory_answer for --question (one model call;
               writes nothing).
  --backfill   upserts the indexable messages that have no memory row
               (project_memory only; the indexer embeds them on its next run).

Phone numbers are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from scripts.probe_helpers import counted  # noqa: E402

_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def _safe(v, n=140) -> str:
    return _PHONE.sub("[number]", " ".join(str(v or "").split()))[:n]


def _t(v) -> str:
    if not isinstance(v, datetime):
        return str(v)
    return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).strftime("%a %b %d %H:%M:%S UTC")


async def _find_project(db, hint: str):
    import server
    try:
        p = await db.projects.find_one({"_id": server.to_query_id(hint)})
        if p:
            return p
    except Exception:
        pass
    rx = {"$regex": re.escape(hint), "$options": "i"}
    hits = await db.projects.find({"$or": [{"name": rx}, {"address": rx}],
                                   "is_deleted": {"$ne": True}}).to_list(10)
    if len(hits) != 1:
        names = ", ".join(f"{h.get('name')} ({h['_id']})" for h in hits) or "none"
        raise SystemExit(f"cannot pick one project for {hint!r}: {names}")
    return hits[0]


async def main_async(a) -> int:
    import server
    from lib import project_memory as pm
    from lib.project_state import fixture_company_ids
    db = server.db
    p = await _find_project(db, a.project)
    pid, pco = str(p["_id"]), str(p.get("company_id") or "")
    print(f"PROJECT  {p.get('name')!r}  id={pid}  company_id={pco}")

    # ── 4 (first: everything below is scoped by it) ────────────────────────
    print("\n4. SCOPE")
    groups = await db.whatsapp_groups.find(
        {"project_id": {"$in": [pid, server.to_query_id(pid)]}}).to_list(20)
    if not groups:
        print("   NO whatsapp_groups row links to this project")
    for g in groups:
        gco = str(g.get("company_id") or "")
        print(f"   group {g.get('group_name')!r} wa={str(g.get('wa_group_id'))[-14:]} "
              f"company_id={gco} {'== project' if gco == pco else '!= PROJECT COMPANY'} "
              f"active={g.get('active')} linked_at={_t(g.get('linked_at'))}")
    gids = [g.get("wa_group_id") for g in groups if g.get("wa_group_id")]
    dms = await db[server.DM_ANSWERS].find(
        {"path": {"$exists": True}}).sort([("created_at", -1)]).limit(200).to_list(None)
    mine = [d for d in dms if str(d.get("project_id") or "") == pid
            or any("project_history" in str(t.get("tool") or "")
                   for t in (d.get("tool_data") or []) if isinstance(t, dict))][:a.dm_rows]
    print(f"   last {len(mine)} DM answer(s) on this job or using search_project_history:")
    for d in mine:
        tools = [t for t in (d.get("tool_data") or []) if isinstance(t, dict)]
        hist = [t for t in tools if t.get("tool") == "search_project_history"]
        print(f"   - {_t(d.get('created_at'))} path={d.get('path')} "
              f"company_id={d.get('company_id')} "
              f"{'(== project)' if str(d.get('company_id')) == pco else '(!= PROJECT COMPANY)'} "
              f"project_id={d.get('project_id')} "
              f"{'(== this job)' if str(d.get('project_id')) == pid else '(OTHER JOB)'}")
        print(f"     Q: {_safe(d.get('question'))}")
        print(f"     A: {_safe(d.get('answer'), 200)}")
        for t in hist:
            print(f"     search_project_history args={_safe(t.get('args'), 200)}")
        if tools and not hist:
            print(f"     tools used: {[t.get('tool') for t in tools]} (NOT search_project_history)")

    # ── 2 ──────────────────────────────────────────────────────────────────
    print("\n2. INGEST")
    test_cos = await fixture_company_ids(db)
    for co in sorted({pco, *[str(g.get("company_id") or "") for g in groups]} - {""}):
        print(f"   company {co}: {'SKIPPED AS A TEST COMPANY (is_test)' if co in test_cos else 'indexed (not a test company)'}")
    state = await db[pm.STATE].find_one({"_id": "cursor"}) or {}
    print(f"   indexer cursor wa_at={_t(state.get('wa_at'))} ran_at={_t(state.get('ran_at'))}"
          f" (runs every {server.MEMORY_INDEX_SECONDS}s; disabled={server._memory_disabled()})")

    # ── 1 ──────────────────────────────────────────────────────────────────
    print("\n1. INDEX")
    mq = {"project_id": {"$in": [pid, server.to_query_id(pid)]}}
    msgs = await db.whatsapp_messages.find(
        mq, {"body": 1, "created_at": 1, "timestamp": 1, "is_dm": 1, "sender": 1,
             "skipped": 1, "project_id": 1, "company_id": 1, "sender_name": 1,
             "voice": 1}).to_list(None)
    idx = [m for m in msgs if pm.indexable_message(m)]
    newest = max((m.get("created_at") for m in msgs if isinstance(m.get("created_at"), datetime)),
                 default=None)
    print(f"   whatsapp_messages: {len(msgs)} rows, {len(idx)} indexable, newest {_t(newest)}")
    off_co = [m for m in idx if str(m.get("company_id") or "") != pco]
    if off_co:
        print(f"   {len(off_co)} indexable row(s) carry another company_id: "
              f"{sorted({str(m.get('company_id')) for m in off_co})}")
    docs = await db.project_memory.find(
        {"project_id": pid}, {"at": 1, "embedded": 1, "company_id": 1, "source": 1,
                              "source_id": 1}).to_list(None)
    wa_docs = [d for d in docs if d.get("source") == pm.SOURCE_WHATSAPP]
    newest_doc = max((d.get("at") for d in docs if isinstance(d.get("at"), datetime)), default=None)
    # Counted through probe_helpers: an absent `embedded` field raises
    # instead of reading as "0 embedded".
    emb = counted(docs, "embedded", bool) if docs else 0
    print(f"   project_memory: {len(docs)} rows ({len(wa_docs)} WhatsApp), newest at "
          f"{_t(newest_doc)}; embedded {emb}, not embedded {len(docs) - emb}")
    doc_cos = sorted({str(d.get("company_id")) for d in docs})
    print(f"   project_memory company_id(s): {doc_cos}")
    have = {str(d.get("source_id")) for d in wa_docs}
    missing = [m for m in idx if str(m["_id"]) not in have]
    print(f"   indexable messages with NO memory row: {len(missing)}")
    for m in sorted(missing, key=lambda m: str(m.get("created_at")))[-10:]:
        behind = (isinstance(state.get("wa_at"), datetime) and isinstance(m.get("created_at"), datetime)
                  and m["created_at"].replace(tzinfo=None) <= state["wa_at"].replace(tzinfo=None))
        print(f"   - {_t(m.get('created_at'))} {'BEHIND CURSOR' if behind else 'ahead of cursor'} "
              f"voice={bool(m.get('voice'))} {_safe(m.get('body'), 90)!r}")
    hits = [m for m in msgs if re.search(re.escape(a.query), str(m.get("body") or ""), re.I)]
    print(f"   messages containing {a.query!r}: {len(hits)}")
    for m in hits[-10:]:
        print(f"   - {_t(m.get('timestamp') or m.get('created_at'))} indexed="
              f"{str(m['_id']) in have} indexable={pm.indexable_message(m)} "
              f"skipped={m.get('skipped')} {_safe(m.get('body'), 120)!r}")

    if a.backfill:
        now = datetime.now(timezone.utc)
        names = {g.get("wa_group_id"): g.get("group_name") or "" for g in groups}
        for m in missing:
            full = await db.whatsapp_messages.find_one({"_id": m["_id"]})
            if str(full.get("company_id") or "") in test_cos:
                continue
            doc = {"_id": f"wa:{full['_id']}",
                   **server._memory_wa_doc(full, names.get(full.get("group_id"), ""))}
            await server._memory_upsert(doc, now)
        print(f"   BACKFILL: upserted {len(missing)} row(s); the indexer embeds them next run")

    # ── 3 ──────────────────────────────────────────────────────────────────
    print("\n3. ATLAS")
    try:
        for r in await db.project_memory.aggregate([{"$listSearchIndexes": {}}]).to_list(None):
            print(f"   index {r.get('name')}: status={r.get('status')} queryable={r.get('queryable')}"
                  f" type={r.get('type')}")
    except Exception as e:
        print(f"   $listSearchIndexes FAILED: {server._memory_err(e)}")
    base = server._memory_filter(pco, pid, None, None)
    filt = [{"equals": {"path": "project_id", "value": pid}},
            {"equals": {"path": "company_id", "value": pco}}]
    try:
        rows = await db.project_memory.aggregate([
            {"$search": {"index": pm.TEXT_INDEX, "compound": {
                "must": [{"text": {"query": a.query, "path": "text"}}], "filter": filt}}},
            {"$limit": 15},
            {"$project": {"text": 1, "at": 1, "score": {"$meta": "searchScore"}}}]).to_list(None)
        print(f"   $search {a.query!r}: {len(rows)} hit(s)")
        for r in rows:
            print(f"   - {r['score']:.3f} {_t(r.get('at'))} {_safe(r.get('text'), 110)!r}")
    except Exception as e:
        print(f"   $search FAILED: {server._memory_err(e)}")
    qv = await server._memory_embed_one(a.query)
    print(f"   query embedding: {'ok' if qv else 'FAILED (no LLM_API_KEY / QWEN_API_KEY, or API error)'}")
    if qv:
        try:
            rows = await db.project_memory.aggregate([
                {"$vectorSearch": {"index": pm.VECTOR_INDEX, "path": "embedding",
                                   "queryVector": qv, "numCandidates": 150, "limit": 15,
                                   "filter": {"project_id": pid, "company_id": pco}}},
                {"$project": {"text": 1, "at": 1,
                              "score": {"$meta": "vectorSearchScore"}}}]).to_list(None)
            print(f"   $vectorSearch {a.query!r}: {len(rows)} hit(s)")
            for r in rows:
                print(f"   - {r['score']:.3f} {_t(r.get('at'))} {_safe(r.get('text'), 110)!r}")
        except Exception as e:
            print(f"   $vectorSearch FAILED: {server._memory_err(e)}")
    words, meaning = await server._memory_code_ranked(base, a.query, qv, 15)
    print(f"   in-code fallback: {len(words)} by words, {len(meaning)} by meaning")
    rows = await server._memory_search(pco, pid, a.question or a.query)
    print(f"   _memory_search({(a.question or a.query)!r}) -> {len(rows)} row(s) "
          f"(atlas state: {server._MEMORY_ATLAS.get('ok')})")
    for r in rows[:8]:
        print(f"   - {_t(r.get('at'))} {_safe(r.get('text'), 110)!r}")

    if a.answer:
        print("\nANSWER")
        got = await server._memory_answer(pco, pid, a.question or a.query)
        sources, claims = got["sources"], got["claims"]
        print(f"   sources={len(sources)} claims={len(claims)} "
              f"dropped={got.get('dropped')} last_mention={bool(got.get('mention'))}")
        print("   " + _safe(got["text"], 600))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="project id, or part of its name/address")
    ap.add_argument("--query", default="core drill")
    ap.add_argument("--question", default="what did we decide about the core drill?")
    ap.add_argument("--answer", action="store_true", help="also run the cited answer (1 model call)")
    ap.add_argument("--backfill", action="store_true",
                    help="WRITE: upsert indexable messages that have no memory row")
    ap.add_argument("--dm-rows", type=int, default=5)
    a = ap.parse_args(argv)
    return asyncio.run(main_async(a))


if __name__ == "__main__":
    sys.exit(main())
