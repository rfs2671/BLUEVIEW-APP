"""ONE-TIME CLEANUP: re-run the attention state engine over a project's
group messages since a date, so items the engine of the time left open
("Just sent, check ur email" on Oct 9 never closed the door hardware ask)
are closed, moved or cancelled as today's engine reads them.

    railway run python scripts/attention_replay.py --project 588 --since 2026-10-09
    railway run python scripts/attention_replay.py --project 588 --since 2026-10-09 --apply

Without --apply it is a DRY RUN: the project's messages, items and people are
copied into an in-memory database (tests/_fake_mongo.FakeDb), the replay runs
there, and every change it WOULD make is printed. Nothing is written.
With --apply the same replay runs against the real database.

Either way nothing is sent: every send path is replaced by one that fails the
run. Nothing new is extracted (no model call): only state changes to items
that already exist, each by a message said after the item.

Exit: 0 ran, 2 cannot run (no database, no such project, ambiguous), 3 tried
to send.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

SEND_PATHS = ("send_whatsapp_message", "send_whatsapp_dm", "_waapi_post_raw",
              "_react_to_message", "_react_or_say")


class Sent(Exception):
    pass


async def _find_project(db, hint: str):
    """By id, else the one project whose name or address contains `hint`."""
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


async def _copy(real, project, since):
    """The project's slice of the database, in memory."""
    import server
    from tests._fake_mongo import FakeDb
    from lib import wa_sender_map
    pid, cid = str(project["_id"]), str(project.get("company_id") or "")
    cfilter = server._company_id_filter(cid)

    async def rows(coll, q):
        return await real[coll].find(q).to_list(100000)
    cols = {
        "projects": [project],
        "whatsapp_groups": await rows("whatsapp_groups", {"project_id": pid}),
        "whatsapp_messages": await rows("whatsapp_messages", {
            "project_id": pid, "created_at": {"$gte": since - timedelta(days=30)}}),
        "attention_items": await rows("attention_items", {"project_id": pid}),
        "users": await rows("users", {"company_id": cfilter}),
        "checkins": await rows("checkins", {"project_id": pid}),
        "punch_items": await rows("punch_items", {"project_id": pid}),
    }
    db = FakeDb(**cols)
    db[wa_sender_map.COLLECTION].rows.extend(await rows(wa_sender_map.COLLECTION, {"company_id": cid}))
    db[server.WA_OPTINS].rows.extend(await rows(server.WA_OPTINS, {"company_id": cfilter}))
    return db


async def main_async(a) -> int:
    import server
    tz = ZoneInfo("America/New_York") if ZoneInfo else timezone.utc
    since = datetime.fromisoformat(a.since).replace(tzinfo=tz).astimezone(timezone.utc)
    real = server.db
    project = await _find_project(real, a.project)
    db = real if a.apply else await _copy(real, project, since)

    def refuse(name):
        async def _r(*x, **k):
            raise Sent(name)
        return _r
    patches = [patch.object(server, "db", db)] + [
        patch.object(server, n, refuse(n)) for n in SEND_PATHS if hasattr(server, n)]
    for p in patches:
        p.start()
    try:
        out = await server._attention_replay_state(str(project["_id"]), since)
    except Sent as e:
        print(f"STOPPED: something tried to send ({e}). Nothing more was done.")
        return 3
    finally:
        for p in patches:
            p.stop()
    mode = "APPLIED" if a.apply else "DRY RUN (nothing written)"
    print(f"{mode}: {project.get('name')} · messages since {a.since} replayed: {out['messages']}")
    if not out["items"]:
        print("No item would change." if not a.apply else "No item changed.")
    for c in out["items"]:
        what = (f"{c['from']} → {c['to']}" if c['from'] != c['to']
                else f"{c['to']}, {' + '.join(c.get('events') or c.get('changed') or [])}")
        print(f"  {c['type']:<10} {what}  “{c['summary'][:70]}”")
        if c["because"]:
            print(f"             because: “{c['because'][:90]}” ({c['at']})")
    hints = out.get("open_with_done_after") or []
    if hints:
        print(f"\nStill open, but the owner said done/sent later in words that don't name it "
              f"({len(hints)}) -- not closed (a guess); close or keep in Attention:")
        for h in hints:
            print(f"  {h['status']:<10} “{h['summary'][:70]}”")
            print(f"             later: “{h['said'][:90]}” ({h['at']})")
    if not a.apply and out["items"]:
        print("\nRe-run with --apply to make these changes.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Re-run the attention state engine (one-time cleanup).")
    ap.add_argument("--project", required=True, help="project id, or text in its name/address (e.g. 588)")
    ap.add_argument("--since", required=True, help="YYYY-MM-DD, New York")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if not os.environ.get("MONGO_URL"):
        print("No MONGO_URL: run under `railway run`.")
        return 2
    import logging
    logging.getLogger("server").setLevel(logging.WARNING)
    try:
        return asyncio.run(main_async(a))
    except SystemExit as e:
        print(f"Cannot run: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
