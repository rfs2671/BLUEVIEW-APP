"""Put a walkthrough taken under the old rule right (Tue Oct 13, 3:37 PM, 588).

Under the old rule each text became the LAST photo's words (or an item of its
own), so a burst of photos and one text about it left the burst blank. This
reads the walk's messages back from the webhook log (kept 30 days), in the
order they came, and applies each text to its batch under the new rule
(lib/punch_batch.py): the photos since the previous text, or "last N pics".
Items a text made are removed; every photo keeps its number and its P-id;
photos still with no words get a short description from the vision model,
marked (auto); the shadow rows the walk made are deleted; the walk is a draft
again, and nothing is sent. A walk that went out LIVE is never touched.

    railway run python scripts/repair_punch_walk.py --project 588          # dry run: what it would do
    railway run python scripts/repair_punch_walk.py --walk <id> --apply    # do it
    railway run python scripts/repair_punch_walk.py --walk <id> --apply --dm   # and DM the walker the draft
    railway run python scripts/repair_punch_walk.py --walk <id> --dump-events walk.json

--dump-events writes the walk's message order (photos and texts, with times;
never phone numbers) -- the shape tests/test_punch_batch_588.py replays.
Phone numbers are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


async def _pick(db, a):
    from lib import punch
    if a.walk:
        return a.walk
    rx = {"$regex": "(?i)" + re.escape(a.project)}
    projects = await db.projects.find({"$or": [{"name": rx}, {"address": rx}]}).to_list(20)
    ids = [str(p["_id"]) for p in projects]
    walks = await db[punch.SESSIONS].find({"project_id": {"$in": ids}}) \
        .sort("created_at", -1).to_list(10)
    print(f"Walks at {a.project!r} (newest first):")
    for w in walks:
        live = [it for it in w.get("items") or [] if it.get("status", "draft") != "dropped"]
        print(f"  {w['_id']}  {w.get('status'):<9} {len(live):>3} items  "
              f"started {w.get('created_at')}  job={w.get('job_name')!r}")
    return walks[0]["_id"] if walks and a.latest else None


async def main_async(a) -> int:
    import server
    db = server.db
    walk_id = await _pick(db, a)
    if not walk_id:
        print("\nName one with --walk <id> (or --latest).")
        return 2
    sess = await db[server.punch.SESSIONS].find_one({"_id": walk_id})
    if not sess:
        print(f"No walk {walk_id}.")
        return 2
    events = await server._punch_walk_events(sess)
    if a.dump_events:
        rows = [{"kind": e["kind"], "message_id": e["message_id"], "text": e.get("text") or "",
                 "quoted": e.get("quoted") or "",
                 "at": e["at"].isoformat() if isinstance(e.get("at"), datetime) else None}
                for e in events]
        Path(a.dump_events).write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
        print(f"Wrote {len(rows)} events to {a.dump_events}.")
    print(f"\nWalk {walk_id} ({sess.get('job_name')}), {len(events)} messages in the log:")
    out = await server.punch_walk_rebatch(walk_id, apply=a.apply, dm=a.dm, events=events, say=print)
    if not out["ok"]:
        print(f"\nNOT DONE: {out['why']}")
        return 1
    print(f"\n{'Done' if a.apply else 'Dry run'}: kept {out['kept']} photo item(s), removed "
          f"{out['removed']} made by a text, {out['described']} with no words "
          f"{'described' if a.apply else 'to describe'}, {out['rows']} shadow row(s) "
          f"{'deleted' if a.apply else 'to delete'}.\n")
    print(server.punch.no_numbers(out.get("draft") or ""))
    if not a.apply:
        print("\nNothing changed. Run again with --apply to do it (and --dm to send the draft).")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--walk", help="the walk's id")
    ap.add_argument("--project", default="588", help="find walks at this job (name or address)")
    ap.add_argument("--latest", action="store_true", help="the newest walk at --project")
    ap.add_argument("--apply", action="store_true", help="do it (default: dry run)")
    ap.add_argument("--dm", action="store_true", help="DM the walker the corrected draft")
    ap.add_argument("--dump-events", help="write the walk's message order to this JSON file")
    a = ap.parse_args(argv)
    if a.dm and not a.apply:
        ap.error("--dm needs --apply")
    return asyncio.run(main_async(a))


if __name__ == "__main__":
    sys.exit(main())
