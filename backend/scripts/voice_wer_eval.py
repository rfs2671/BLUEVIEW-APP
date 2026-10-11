"""Whisper glossary eval: word error rate on ten construction phrases, without
and with the prompt (lib/voice_glossary.py). Calls OpenAI; writes nothing to
the database.

    # Real recordings (best): a folder with 01.ogg … 10.ogg (any of .ogg .m4a
    # .mp3 .wav .webm), one per phrase in voice_eval/construction_phrases.json,
    # plus es1/es2 for the language guard. WhatsApp voice notes exported as is.
    OPENAI_API_KEY=… python scripts/voice_wer_eval.py --audio-dir ~/voice_eval

    # No recordings: OpenAI text-to-speech reads each phrase (saved into
    # --audio-dir, so a rerun compares the same audio).
    OPENAI_API_KEY=… python scripts/voice_wer_eval.py --audio-dir /tmp/ve --tts

Prints, per phrase: the reference, what Whisper heard without and with the
prompt, and the WER of each; then the totals (word-weighted). The language
guard: the Spanish notes must still be heard as Spanish with the prompt on
(an English prompt can pull Whisper toward English). Exit code 1 when the
prompt makes the total worse or flips a guard note's language.

TTS audio is clean studio speech: it understates what the glossary does for
a site recording. Real voice notes are the number to trust.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

PHRASES = HERE / "voice_eval" / "construction_phrases.json"
EXTS = (".ogg", ".m4a", ".mp3", ".wav", ".webm")


def _find(audio_dir: Path, pid: str):
    for ext in EXTS:
        p = audio_dir / f"{pid}{ext}"
        if p.exists():
            return p
    return None


async def _tts(text: str, key: str) -> bytes:
    from lib.server_http import ServerHttpClient
    async with ServerHttpClient(timeout=60) as c:
        r = await c.post("https://api.openai.com/v1/audio/speech",
                         headers={"Authorization": f"Bearer {key}"},
                         json={"model": "tts-1", "voice": "onyx", "input": text,
                               "response_format": "mp3"})
        r.raise_for_status()
        return r.content


async def main_async(a) -> int:
    from lib import voice_glossary, voice_ingest
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        print("OPENAI_API_KEY is not set")
        return 2
    spec = json.loads(PHRASES.read_text())
    prompt = voice_glossary.build_prompt(**spec["job"])
    print(f"prompt (~{voice_glossary.estimate_tokens(prompt)} tokens est.):\n  {prompt}\n")
    audio_dir = Path(a.audio_dir).expanduser()
    audio_dir.mkdir(parents=True, exist_ok=True)

    async def heard(item, with_prompt):
        path = _find(audio_dir, item["id"])
        if path is None and a.tts:
            path = audio_dir / f"{item['id']}.mp3"
            path.write_bytes(await _tts(item["text"], key))
        if path is None:
            return None
        return await voice_ingest.transcribe_whisper(
            path.read_bytes(), openai_api_key=key,
            prompt=prompt if with_prompt else None)

    tot = {"words": 0, "before": 0.0, "after": 0.0}
    print(f"{'id':<4} {'WER before':>10} {'WER after':>10}  phrase")
    missing = []
    for item in spec["phrases"]:
        before = await heard(item, False)
        if before is None:
            missing.append(item["id"])
            continue
        after = await heard(item, True)
        ref = item["text"]
        wb = voice_glossary.wer(ref, before.transcript)
        wa = voice_glossary.wer(ref, after.transcript)
        n = len(voice_glossary._words(ref))
        tot["words"] += n
        tot["before"] += wb * n
        tot["after"] += wa * n
        print(f"{item['id']:<4} {wb:>10.0%} {wa:>10.0%}  {item['text']}")
        if wb or wa:
            print(f"{'':<27}before: {before.transcript}")
            print(f"{'':<27}after:  {after.transcript}")
    if missing:
        print(f"\nno audio for: {', '.join(missing)} (record them, or pass --tts)")
    if not tot["words"]:
        return 2
    wb, wa = tot["before"] / tot["words"], tot["after"] / tot["words"]
    print(f"\nTOTAL WER  before {wb:.1%}  after {wa:.1%}  "
          f"({'better' if wa < wb else 'worse' if wa > wb else 'same'}; {tot['words']} words)")

    flipped = []
    print("\nLANGUAGE GUARD (must stay Spanish with the prompt)")
    for item in spec.get("language_guard") or []:
        r = await heard(item, True)
        if r is None:
            print(f"  {item['id']}: no audio")
            continue
        ok = (r.language or "").lower().startswith(item["lang"][:2])
        if not ok:
            flipped.append(item["id"])
        print(f"  {item['id']}: heard as {r.language!r} {'ok' if ok else 'FLIPPED'} — {r.transcript}")
    return 1 if (wa > wb or flipped) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audio-dir", required=True)
    ap.add_argument("--tts", action="store_true",
                    help="read missing phrases aloud with OpenAI TTS (saved for reruns)")
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
