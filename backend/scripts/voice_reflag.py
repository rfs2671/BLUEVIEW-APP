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
    re-indexed only as Whisper's English of the audio, when there is one),
    and the Attention items made from it marked needs_review (never chased).
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
        res = await db.attention_items.update_many(
            {"evidence.message_row_id": str(r["_id"]), "type": {"$ne": "voice_review"}},
            {"$set": {"needs_review": True, "voice_unreliable": True}})
        print(f"      applied: row flagged, memory doc removed, "
              f"{getattr(res, 'modified_count', 0)} attention item(s) marked for review")
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
