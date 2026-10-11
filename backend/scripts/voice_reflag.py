"""Re-check stored voice notes with the hallucination rules (Oct 11). DRY RUN
unless --apply.

    railway run python scripts/voice_reflag.py --project 588 --since 2026-10-11
    railway run python scripts/voice_reflag.py --project 588 --since 2026-10-11 --apply

588, Sun Oct 11 2:57 PM: a forwarded Yiddish blessing was stored as "People
speaking in their native language." and the DM assistant quoted it. Notes
stored before the rules (lib/wa_voice.unreliable_reasons) were never
checked. For each transcribed voice row of the project since --since:
  - the words (meta_transcript), and Whisper's scores where the note kept
    them (voice.quality, or the ledger's telemetry), say whether it is what
    was said;
  - with --apply, a note that is not: voice.unreliable + review, skipped
    "voice_unreliable" (no extraction), its project_memory doc removed (it is
    re-indexed only as Whisper's English of the audio, when there is one);
    the Attention items it made or changed (a "done", a new date) marked
    needs_review (never chased) and each change listed to check -- never
    undone here; Upcoming events it made dismissed, events it moved flagged.
Nothing is sent. Transcripts are cut to 80 characters; no phone numbers.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def reasons_for(row: dict, event: dict) -> list:
    from lib import wa_voice
    v = row.get("voice") or {}
    q = v.get("quality") or ((event or {}).get("telemetry") or {}).get("whisper_quality") or {}
    return wa_voice.unreliable_reasons(v.get("transcript") or row.get("body") or "", q)


async def main_async(a) -> int:
    import server
    from scripts.wa_provenance import _find_project, _safe
    db = server.db
    p = await _find_project(db, a.project)
    since = datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc)
    rows = await db.whatsapp_messages.find(
        {"project_id": str(p["_id"]), "has_audio": True, "created_at": {"$gte": since}}
    ).to_list(5000)
    rows = [r for r in rows if r.get("voice") and not r.get("skipped")
            and not (r.get("voice") or {}).get("unreliable")]
    print(f"{p.get('name')}: {len(rows)} transcribed voice note(s) since {a.since}"
          f"{'' if a.apply else ' (dry run)'}")
    flagged = 0
    for r in sorted(rows, key=lambda r: r.get("created_at")):
        ev = await db.whatsapp_voice_events.find_one({"message_id": r.get("message_id")}) or {}
        why = reasons_for(r, ev)
        if not why:
            continue
        flagged += 1
        print(f"  {r['created_at']:%Y-%m-%d %H:%M} UTC  {_safe((r.get('voice') or {}).get('transcript'))!r}")
        print(f"      -> not reliably transcribed: {'; '.join(why)}")
        if not a.apply:
            continue
        await db.whatsapp_messages.update_one({"_id": r["_id"]}, {"$set": {
            "voice.unreliable": why, "voice.review": True,
            "voice.review_reason": "unreliable", "skipped": "voice_unreliable"}})
        await db.project_memory.delete_one({"_id": f"wa:{r['_id']}"})
        rid, mid = str(r["_id"]), str(r.get("message_id") or "")
        # Items it MADE, and items whose state it CHANGED (a "done", a new
        # date): both for a person; the changes are listed, never undone here.
        made = changed = 0
        for it in await db.attention_items.find(
                {"$or": [{"evidence.message_row_id": rid}, {"history.message_row_id": rid}],
                 "type": {"$ne": "voice_review"}}).to_list(500):
            by_it = [h for h in it.get("history") or []
                     if isinstance(h, dict) and h.get("message_row_id") == rid
                     and h.get("kind") not in ("created",)]
            await db.attention_items.update_one({"_id": it["_id"]}, {"$set": {
                "needs_review": True, "voice_unreliable": True}})
            if (it.get("evidence") or {}).get("message_row_id") == rid:
                made += 1
            for h in by_it:
                changed += 1
                print(f"      item {it['_id']}: {h.get('kind')} {h.get('from')} -> {h.get('to')}"
                      f" came from this note -- check it (status now {it.get('status')})")
        # Upcoming events it made are dismissed (no reminder from made-up
        # words); events it moved are flagged for a look.
        now = datetime.now(timezone.utc)
        ev_made = await db.upcoming_events.update_many(
            {"source_ref": rid, "status": "open"},
            {"$set": {"status": "dismissed", "dismissed_by": "voice_reflag",
                      "dismissed_at": now, "dismissed_reason": "voice_unreliable"}})
        ev_moved = await db.upcoming_events.update_many(
            {"history.message_id": mid, "source_ref": {"$ne": rid}} if mid else {"_id": None},
            {"$set": {"needs_review": True, "review_reason": "voice_unreliable"}})
        print(f"      applied: row flagged, memory doc removed, {made} item(s) it made and "
              f"{changed} change(s) it made marked for review, "
              f"{getattr(ev_made, 'modified_count', 0)} event(s) dismissed, "
              f"{getattr(ev_moved, 'modified_count', 0)} event(s) it moved flagged")
    print(f"{flagged} flagged" + ("" if a.apply else " (nothing written; --apply to write)"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="project id, or part of its name/address")
    ap.add_argument("--since", required=True, help="YYYY-MM-DD (UTC)")
    ap.add_argument("--apply", action="store_true", help="write the flags")
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
