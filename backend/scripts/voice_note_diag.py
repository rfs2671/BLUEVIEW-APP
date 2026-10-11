"""What did Whisper hear, and why did the bot answer? READ-ONLY.

    railway run python scripts/voice_note_diag.py --project 588 --at "2026-10-11 14:51"

--at is New York time (or an ISO time with Z). Every voice note stored in the
project's groups within --minutes of it (default 5) is printed with:
  - the transcript as stored (whatsapp_messages.voice / body) and as Whisper
    returned it (whatsapp_voice_events: original, English, language, prompt
    on/off, confidence, rejected reason);
  - whether it says "levelog" (the bot's name: a mention in a group);
  - whether it is an echo of the Whisper prompt (lib/voice_glossary.prompt_echo);
  - whether it is shaped like a question (the once-a-day "say levelog" hint
    fires on an unaddressed question);
  - what the bot posted in the group in the 3 minutes after it.
Then the Whisper prompt this job builds today, and whether it names the bot.

Bodies are cut to 160 characters; phone numbers are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

NY = ZoneInfo("America/New_York")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
AFTER = timedelta(minutes=3)


def _safe(v, n=160) -> str:
    return _PHONE.sub("[number]", " ".join(str(v or "").split()))[:n]


def _utc(v):
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _when(text: str) -> datetime:
    t = text.strip().replace("T", " ")
    if t.endswith("Z"):
        return datetime.fromisoformat(t[:-1]).replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(t).replace(tzinfo=NY).astimezone(timezone.utc)


def verdicts(transcript: str, english: str, prompt: str) -> dict:
    """The three questions about one transcript."""
    import server
    from lib import voice_glossary
    words = english or transcript
    return {"says_levelog": voice_glossary.names_the_bot(transcript)
            or voice_glossary.names_the_bot(english),
            "prompt_echo": voice_glossary.prompt_echo(transcript, prompt),
            "question_shaped": server._looks_like_a_question(words)}


async def main_async(a) -> int:
    import server
    from scripts.wa_provenance import _find_project
    db = server.db
    p = await _find_project(db, a.project)
    at = _when(a.at)
    span = timedelta(minutes=a.minutes)
    groups = [g.get("wa_group_id") for g in await db.whatsapp_groups.find(
        {"project_id": str(p["_id"])}, {"wa_group_id": 1}).to_list(50) if g.get("wa_group_id")]
    print(f"project {p.get('name')} ({p['_id']}); {len(groups)} group(s); "
          f"{at.astimezone(NY):%a %b %d %I:%M %p} NY ± {a.minutes} min\n")
    rows = await db.whatsapp_messages.find(
        {"group_id": {"$in": groups}, "has_audio": True,
         "created_at": {"$gte": at - span, "$lte": at + span}}).to_list(200)
    prompt = await server._voice_prompt(p.get("company_id"), p["_id"]) or ""
    if not rows:
        print("no voice note stored in that window")
    for r in sorted(rows, key=lambda r: _utc(r.get("created_at"))):
        mid = str(r.get("message_id") or "")
        voice = r.get("voice") or {}
        ev = await db.whatsapp_voice_events.find_one({"message_id": mid}) or {}
        tel = ev.get("telemetry") or {}
        said = voice.get("transcript") or ev.get("original_transcript") or ""
        eng = ev.get("english_transcript") or ""
        v = verdicts(said, eng, prompt)
        ca = _utc(r.get("created_at"))
        print(f"── {ca.astimezone(NY):%I:%M:%S %p} NY  message {mid[-8:]}  "
              f"sender …{str(r.get('sender') or '')[-4:]}  skipped={r.get('skipped')}")
        print(f"   stored body:   {_safe(r.get('body'))!r}")
        print(f"   transcript:    {_safe(said)!r}")
        print(f"   english:       {_safe(eng)!r}")
        print(f"   lang={ev.get('language_detected')} conf={voice.get('confidence')} "
              f"dur={voice.get('duration_sec')} prompt_on={tel.get('whisper_prompt')} "
              f"hint={tel.get('whisper_language_hint')} rejected={tel.get('rejected_reason')} "
              f"error={ev.get('error_kind')}")
        print(f"   says 'levelog': {v['says_levelog']}   prompt echo: {v['prompt_echo']}   "
              f"question-shaped: {v['question_shaped']}")
        bot = await db.whatsapp_messages.find(
            {"group_id": r.get("group_id"), "sender": "bot",
             "created_at": {"$gte": ca, "$lte": ca + AFTER}},
            {"body": 1, "created_at": 1}).to_list(20)
        for b in sorted(bot, key=lambda b: _utc(b.get("created_at"))):
            print(f"   bot {_utc(b['created_at']).astimezone(NY):%I:%M:%S %p}: {_safe(b.get('body'))!r}")
        if not bot:
            print("   bot: nothing stored in the 3 minutes after "
                  "(a send is stored only when the send path records it)")
        print()
    from lib import voice_glossary
    print(f"Whisper prompt for this job now (~{voice_glossary.estimate_tokens(prompt)} tokens):")
    print(f"   {_safe(prompt, 2000)}")
    print(f"   names the bot: {voice_glossary.names_the_bot(prompt)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="project id, or part of its name/address")
    ap.add_argument("--at", required=True, help='New York time, "2026-10-11 14:51" (or ISO with Z)')
    ap.add_argument("--minutes", type=int, default=5)
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
