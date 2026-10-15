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

--dump-events writes the walk's message order (photos, texts, voice notes
with their stored transcripts, and the assistant's own messages -- its
capture confirmations among them -- with times) AND its items as stored;
never phone numbers. Saved as backend/tests/fixtures/punch_walk_6a868363.json,
tests/test_punch_walk_6a868363.py replays exactly that walk.

The dry run's vision lines are the real description, or the exact reason
there is none (no key; the R2 keys tried and their errors; WhatsApp media;
the model's HTTP status and body) -- never a stand-in.

The dry run prints every message with what it did (which photos, what
place and words; a voice note's transcript and where it went; "couldn't
place"), runs the vision model on photos with no words (shown "(auto)";
--no-vision skips it), and prints the draft exactly as it would be.
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


_PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")

#: What a dumped item keeps: enough to replay the walk exactly.
_ITEM_KEYS = ("n", "captured", "photo_key", "photo_failed", "message_id", "caption_ids", "text",
              "said", "text_src", "text_auto", "floor", "area", "room", "loc_src", "trade",
              "trade_guess", "trade_src", "status", "added_from", "at")


def _clean(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, str):
        return _PHONE.sub("[number]", v)
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def dump(sess, events, punch):
    """The walk's messages (photos, texts, voice notes with their stored
    transcripts, the assistant's own messages -- its capture confirmations
    among them) and its items as stored. Never a phone number."""
    spoken = {punch.short_message_id(m): (it.get("voice") or {}).get("transcript")
              for it in sess.get("items") or [] if (it.get("voice") or {}).get("transcript")
              for m in [it.get("message_id")] + list(it.get("caption_ids") or []) if m}
    # The short id only: a serialized one ("false_<phone>@c.us_<id>") holds
    # the sender's phone number. The replay matches on the short id.
    sid = punch.short_message_id
    rows = [{"kind": e["kind"], "message_id": sid(e.get("message_id")) or "",
             "text": _clean(e.get("text") or spoken.get(sid(e.get("message_id"))) or ""),
             "quoted": sid(e.get("quoted")) or "",
             "at": e["at"].isoformat() if isinstance(e.get("at"), datetime) else None}
            for e in events]
    items = []
    for it in sess.get("items") or []:
        row = {k: _clean(it[k]) for k in _ITEM_KEYS if k in it}
        if "message_id" in row:
            row["message_id"] = sid(it.get("message_id")) or ""
        if "caption_ids" in row:
            row["caption_ids"] = [sid(c) for c in it.get("caption_ids") or [] if c]
        v = it.get("voice") or {}
        if v.get("transcript"):
            row["voice"] = {"transcript": _clean(v["transcript"]), "lang": v.get("lang")}
        items.append(row)
    return rows, items


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
        rows, items = dump(sess, events, server.punch)
        Path(a.dump_events).write_text(json.dumps(
            {"walk": walk_id, "job_name": sess.get("job_name"), "detail": sess.get("detail"),
             "events": rows, "items": items}, indent=1, ensure_ascii=False) + "\n")
        print(f"Wrote {len(rows)} events and {len(items)} items to {a.dump_events}.")
    print(f"\nWalk {walk_id} ({sess.get('job_name')}), {len(events)} messages in the log:")
    out = await server.punch_walk_rebatch(walk_id, apply=a.apply, dm=a.dm, events=events,
                                          vision=not a.no_vision, say=print)
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
    ap.add_argument("--no-vision", action="store_true",
                    help="dry run without the vision model's descriptions (no vision calls)")
    a = ap.parse_args(argv)
    if a.dm and not a.apply:
        ap.error("--dm needs --apply")
    return asyncio.run(main_async(a))


if __name__ == "__main__":
    sys.exit(main())
