"""Where did a WhatsApp message row come from? READ-ONLY.

    railway run python scripts/wa_provenance.py --project 588 --at 2026-10-09T05:20:37Z
    railway run python scripts/wa_provenance.py --since 2026-09-12

A row stored by the live webhook has three marks:
  WEBHOOK  a whatsapp_webhook_log entry (every POST WaAPI makes, kept 30 days)
           received within minutes of the row's created_at that carries the
           row's message_id;
  ON TIME  created_at (when the server stored it) within minutes of
           timestamp (WhatsApp's own time) -- a replay or seeding script
           stores old WhatsApp times at a new created_at, or makes both up;
  SHAPE    the keys _store_group_message always writes.
No script in scripts/ writes whatsapp_messages to the real database (the dry
runs swap in tests/_fake_mongo.FakeDb; attention_replay --apply writes
attention items only), so a row without the WEBHOOK mark needs explaining.

--at       one message, in full: its marks, the webhook log entry, its memory row.
--since    every group row of a REAL company (not is_test) since that day
           without the WEBHOOK mark, and project_memory rows that point at no
           message, at a suspect one, or belong to a test company.
           (Older than 30 days the log is gone: those rows are "unknown".)

Message bodies are cut to 80 characters; phone numbers are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
LOG_DAYS = 30
NEAR = timedelta(minutes=10)
SHAPE_KEYS = ("message_id_serialized", "sender_jid", "from_me", "quoted_body", "mentioned_jids")


def _safe(v, n=80) -> str:
    return _PHONE.sub("[number]", " ".join(str(v or "").split()))[:n]


def _utc(v):
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _t(v) -> str:
    v = _utc(v)
    return v.strftime("%a %b %d %H:%M:%S UTC") if v else str(v)


async def _webhook_hit(db, row):
    """The log entry that delivered this row, or None; 'gone' past 30 days."""
    at = _utc(row.get("created_at"))
    mid = str(row.get("message_id") or "")
    if not at or not mid:
        return None
    if at < datetime.now(timezone.utc) - timedelta(days=LOG_DAYS):
        return "gone"
    logs = await db.whatsapp_webhook_log.find(
        {"received_at": {"$gte": at - NEAR, "$lte": at + NEAR}},
        {"received_at": 1, "raw_body_preview": 1, "raw_body_length": 1}).to_list(5000)
    return next((lg for lg in logs if mid in str(lg.get("raw_body_preview") or "")), None)


def _marks(row, hit) -> dict:
    ca, ts = _utc(row.get("created_at")), _utc(row.get("timestamp"))
    skew = (ca - ts) if ca and ts else None
    return {"webhook": "unknown (log expired)" if hit == "gone" else bool(hit),
            "skew": skew,
            "on_time": skew is not None and abs(skew) <= NEAR,
            "shape_missing": [k for k in SHAPE_KEYS if k not in row]}


async def _find_project(db, hint):
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
        raise SystemExit(f"cannot pick one project for {hint!r}: "
                         + (", ".join(f"{h.get('name')} ({h['_id']})" for h in hits) or "none"))
    return hits[0]


async def one(db, a) -> None:
    import server
    p = await _find_project(db, a.project)
    pid = str(p["_id"])
    at = datetime.fromisoformat(a.at.replace("Z", "+00:00"))
    rows = await db.whatsapp_messages.find(
        {"project_id": {"$in": [pid, server.to_query_id(pid)]},
         "timestamp": {"$gte": (at - timedelta(seconds=2)).replace(tzinfo=None),
                       "$lte": (at + timedelta(seconds=2)).replace(tzinfo=None)}}).to_list(20)
    if not rows:
        print(f"no message of {p.get('name')!r} with WhatsApp time {_t(at)}")
        return
    for r in rows:
        hit = await _webhook_hit(db, r)
        m = _marks(r, hit)
        print(f"ROW {r['_id']}  {_safe(r.get('body'))!r}")
        print(f"   sender_name={r.get('sender_name')!r} company_id={r.get('company_id')} "
              f"message_id={r.get('message_id')} serialized={'yes' if r.get('message_id_serialized') else 'no'}")
        print(f"   timestamp (WhatsApp) {_t(r.get('timestamp'))}")
        print(f"   created_at (stored)  {_t(r.get('created_at'))}   skew {m['skew']}")
        print(f"   WEBHOOK {m['webhook']}"
              + (f"  (log {_t(hit.get('received_at'))}, {hit.get('raw_body_length')} bytes)"
                 if isinstance(hit, dict) else ""))
        print(f"   ON TIME {m['on_time']}   SHAPE missing {m['shape_missing'] or 'none'}")
        if isinstance(hit, dict):
            pv = str(hit.get("raw_body_preview") or "")
            for key in ("event", "type", "notifyName"):
                mm = re.search(rf'"{key}"\s*:\s*("?[^",}}]*"?)', pv)
                if mm:
                    print(f"     payload {key}: {_safe(mm.group(1), 60)}")
            mm = re.search(r'"timestamp"\s*:\s*(\d{9,11})\b', pv)
            if mm:
                print(f"     payload timestamp: {_t(datetime.fromtimestamp(int(mm.group(1)), timezone.utc))}")
        mem = await db.project_memory.find_one({"_id": f"wa:{r['_id']}"},
                                               {"embedding": 0})
        print(f"   memory row: {'yes, indexed_at ' + _t(mem.get('indexed_at')) if mem else 'none'}")
        verdict = ("LIVE WEBHOOK" if m["webhook"] is True and m["on_time"] else
                   "LIVE WEBHOOK, delivered late" if m["webhook"] is True else
                   "NOT FROM THE WEBHOOK (script or manual insert)" if m["webhook"] is False else
                   "unknown (log expired)")
        print(f"   VERDICT: {verdict}")


async def sweep(db, a) -> None:
    from lib import project_memory as pm
    from lib.project_state import fixture_company_ids
    test_cos = await fixture_company_ids(db)
    since = datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc)
    rows = await db.whatsapp_messages.find(
        {"created_at": {"$gte": since.replace(tzinfo=None)}, "is_dm": {"$ne": True},
         "sender": {"$ne": "bot"}, "project_id": {"$nin": [None, ""]}}).to_list(None)
    real = [r for r in rows if str(r.get("company_id") or "") not in test_cos]
    print(f"group rows since {a.since}: {len(rows)} ({len(real)} of real companies; "
          f"test companies {sorted(test_cos) or 'none'})")
    suspect, late, unknown = [], [], 0
    for r in real:
        hit = await _webhook_hit(db, r)
        m = _marks(r, hit)
        if hit == "gone":
            unknown += 1
        elif not hit:
            suspect.append((r, m))
        elif not m["on_time"]:
            late.append((r, m))
    print(f"   from the webhook: {len(real) - len(suspect) - unknown}"
          f" (of which delivered >10 min late: {len(late)}); log expired: {unknown}")
    print(f"   NOT FROM THE WEBHOOK: {len(suspect)}")
    for r, m in suspect[:a.limit]:
        print(f"   - {r['_id']} project={r.get('project_id')} company={r.get('company_id')} "
              f"wa={_t(r.get('timestamp'))} stored={_t(r.get('created_at'))} "
              f"shape_missing={m['shape_missing']} {_safe(r.get('body'))!r}")
    for r, m in late[:a.limit]:
        print(f"   late: {r['_id']} wa={_t(r.get('timestamp'))} stored={_t(r.get('created_at'))}")
    bad = {str(r["_id"]) for r, _ in suspect}
    docs = await db.project_memory.find(
        {"source": pm.SOURCE_WHATSAPP}, {"source_id": 1, "company_id": 1, "project_id": 1,
                                         "text": 1}).to_list(None)
    ids = [d["source_id"] for d in docs]
    import server
    have = set()
    for i in range(0, len(ids), 1000):
        chunk = ids[i:i + 1000]
        have |= {str(x["_id"]) for x in await db.whatsapp_messages.find(
            {"_id": {"$in": [server.to_query_id(c) for c in chunk] + chunk}}, {"_id": 1}).to_list(None)}
    orphan = [d for d in docs if d["source_id"] not in have]
    from_bad = [d for d in docs if d["source_id"] in bad]
    from_test = [d for d in docs if str(d.get("company_id")) in test_cos]
    print(f"\nproject_memory WhatsApp rows: {len(docs)}")
    print(f"   pointing at no message (the indexer removes these): {len(orphan)}")
    print(f"   pointing at a NOT-FROM-THE-WEBHOOK message: {len(from_bad)}")
    print(f"   of a test company: {len(from_test)}")
    for d in (from_bad + orphan)[:a.limit]:
        print(f"   - {d['_id']} project={d.get('project_id')} {_safe(d.get('text'))!r}")


async def main_async(a) -> int:
    import server
    if a.at:
        await one(server.db, a)
    if a.since:
        await sweep(server.db, a)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", help="with --at: project id or part of its name/address")
    ap.add_argument("--at", help="WhatsApp time of the message, e.g. 2026-10-09T05:20:37Z")
    ap.add_argument("--since", help="sweep real-company rows stored since YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=25)
    a = ap.parse_args(argv)
    if not (a.at or a.since) or (a.at and not a.project):
        ap.error("give --project with --at, and/or --since")
    return asyncio.run(main_async(a))


if __name__ == "__main__":
    sys.exit(main())
