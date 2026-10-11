"""Voice eval harness: real clips + what was said -> WER and CER per language,
for whisper-1 and gpt-4o-transcribe, without and with the glossary prompt
(and the People language hint). Calls OpenAI; writes nothing to the database.

THE FOLDER (one subfolder per language; each clip beside a .txt of the exact
words said, in the language's own spelling — Yiddish in Hebrew letters — and,
for the translation row, a .en.txt of what it means in English):

    clips/
      es/01.ogg  es/01.txt   es/02.opus es/02.txt   …
      yi/01.ogg  yi/01.txt   yi/01.en.txt   …
      en/…                                  (optional)

  .ogg .opus .m4a .mp3 .wav .webm all work (a WhatsApp voice note exported
  as is). Or a clips/manifest.json instead of the .txt files:
      [{"file": "yi/01.ogg", "lang": "yi", "text": "…", "en": "Tomorrow we pour"}]

    OPENAI_API_KEY=… python scripts/voice_lang_eval.py clips/
    OPENAI_API_KEY=… python scripts/voice_lang_eval.py clips/ --hint both --json out.json

THE MATRIX, per clip: model (whisper-1, gpt-4o-transcribe) × glossary prompt
(off, on) × language hint (--hint off | on | both; default both). whisper-1
goes through the production call (lib/voice_ingest.transcribe_whisper).
Plus one more row, "whisper-1 translate": Whisper's translations endpoint,
audio straight to English (lib/voice_ingest.translate_whisper, what a
Yiddish card's English line shows), scored against the clip's .en.txt; a
clip without one is skipped for that row. --verbose prints, for each Yiddish
clip, both lines as the card shows them: what was said and the English.

PER LANGUAGE, per configuration: WER and CER (lib/voice_metrics: points and
ligatures normalized for Yiddish, accents kept for Spanish), how many clips
came back in the wrong language (whisper-1 reports it) or, for Yiddish, in
Latin letters, and how many calls failed. --verbose prints every transcript.

The prompt is the glossary plus --job terms (default: the 588 terms of
voice_eval/construction_phrases.json). It is in English: the "prompt on"
rows show what it does to Spanish and Yiddish notes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

EXTS = (".ogg", ".opus", ".m4a", ".mp3", ".wav", ".webm")
MODELS = ("whisper-1", "gpt-4o-transcribe")
TRANSLATE = "whisper-1 translate"
LANG_NAMES = {"en": "english", "es": "spanish", "yi": "yiddish"}


@dataclass
class Clip:
    id: str
    path: Path
    lang: str
    text: str
    en: Optional[str] = None          # the English reference (.en.txt)


@dataclass
class Result:
    clip: str
    lang: str
    model: str
    prompt: bool
    hint: bool
    ref: str
    hyp: str = ""
    detected: Optional[str] = None
    error: Optional[str] = None
    wer: float = 0.0
    cer: float = 0.0
    wrong_lang: bool = False


def load_clips(root: Path) -> List[Clip]:
    """From manifest.json, else <lang>/<name>.<ext> + <name>.txt. A clip
    without its text is reported and skipped."""
    man = root / "manifest.json"
    if man.exists():
        return [Clip(id=r["file"], path=root / r["file"], lang=r["lang"].lower(), text=r["text"],
                     en=r.get("en"))
                for r in json.loads(man.read_text(encoding="utf-8"))]
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        for f in sorted(p for p in d.iterdir() if p.suffix.lower() in EXTS):
            txt = f.with_suffix(".txt")
            if not txt.exists():
                print(f"  skipped {d.name}/{f.name}: no {txt.name}")
                continue
            en = f.with_suffix(".en.txt")
            out.append(Clip(id=f"{d.name}/{f.name}", path=f, lang=d.name.lower(),
                            text=txt.read_text(encoding="utf-8").strip(),
                            en=en.read_text(encoding="utf-8").strip() if en.exists() else None))
    return out


async def transcribe(model: str, audio: bytes, key: str, prompt: Optional[str],
                     language: Optional[str]) -> Dict[str, Any]:
    """{text, language} from one model."""
    from lib import voice_ingest
    if model == TRANSLATE:
        return {"text": await voice_ingest.translate_whisper(audio, openai_api_key=key),
                "language": "english"}
    if model == "whisper-1":
        r = await voice_ingest.transcribe_whisper(audio, openai_api_key=key, prompt=prompt,
                                                  language=language)
        return {"text": r.transcript, "language": r.language}
    from lib.server_http import ServerHttpClient
    name, mime = voice_ingest.audio_name(audio)
    files = {"file": (name, audio, mime), "model": (None, model),
             "response_format": (None, "json"), "temperature": (None, "0")}
    if prompt:
        files["prompt"] = (None, prompt)
    if language:
        files["language"] = (None, language)
    async with ServerHttpClient(timeout=120) as c:
        resp = await c.post("https://api.openai.com/v1/audio/transcriptions",
                            headers={"Authorization": f"Bearer {key}"}, files=files)
        if resp.status_code != 200:
            raise RuntimeError(f"{model} {resp.status_code}: {resp.text[:200]}")
        return {"text": (resp.json().get("text") or "").strip(), "language": None}


def configs(hint: str) -> List[Dict[str, Any]]:
    hints = {"off": [False], "on": [True], "both": [False, True]}[hint]
    return [{"model": m, "prompt": p, "hint": h}
            for m in MODELS for p in (False, True) for h in hints] + [
        {"model": TRANSLATE, "prompt": False, "hint": False}]


def label(model: str, prompt: bool, hint: bool) -> str:
    if model == TRANSLATE:
        return f"{model:<18} -> English vs .en.txt"
    return (f"{model:<18} prompt {'on ' if prompt else 'off'}  "
            f"hint {'on ' if hint else 'off'}")


def score(rows: List[Result]) -> Dict[str, Any]:
    """WER/CER weighted by each reference's length; wrong-language and failed counts."""
    from lib import voice_metrics
    ok = [r for r in rows if r.error is None]
    wl = [len(voice_metrics.words(r.ref)) for r in ok]
    cl = [len(voice_metrics.normalize(r.ref).replace(" ", "")) for r in ok]
    return {"wer": sum(r.wer * n for r, n in zip(ok, wl)) / (sum(wl) or 1),
            "cer": sum(r.cer * n for r, n in zip(ok, cl)) / (sum(cl) or 1),
            "wrong_lang": len([r for r in ok if r.wrong_lang]),
            "failed": len(rows) - len(ok), "n": len(ok)}


def wrong_language(lang: str, got: Dict[str, Any], translated: bool = False) -> bool:
    """whisper-1 said another language, or a Yiddish note came back in Latin
    letters. For a translation: anything but Latin-letter English."""
    from lib import voice_metrics
    if translated:
        return voice_metrics.script_of(got.get("text") or "") == "hebrew"
    said = (got.get("language") or "").lower()
    if said and lang in LANG_NAMES and not said.startswith(LANG_NAMES[lang][:3]):
        return True
    if lang == "yi" and voice_metrics.script_of(got.get("text") or "") == "latin":
        return True
    return False


def card_lines(clip: Clip, results: List[Result]) -> List[str]:
    """What a Yiddish card shows for this clip, as the production path would
    make it: what was said (whisper-1, glossary prompt on, Yiddish hint when
    run, else off) and Whisper's direct English."""
    def pick(model, prompt, hint):
        return next((r for r in results if r.clip == clip.id and r.model == model
                     and r.prompt == prompt and r.hint == hint and r.error is None), None)
    said = pick("whisper-1", True, True) or pick("whisper-1", True, False) \
        or pick("whisper-1", False, False)
    eng = pick(TRANSLATE, False, False)
    return [f"Said: {said.hyp if said else '—'}",
            f"English: {eng.hyp if eng else '— (no .en.txt, not run)'}"]


async def main_async(a) -> int:
    from lib import voice_glossary, voice_metrics
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        print("OPENAI_API_KEY is not set")
        return 2
    root = Path(a.clips).expanduser()
    clips = load_clips(root)
    if not clips:
        print(f"no clips with text under {root}")
        return 2
    job = json.loads((Path(a.job) if a.job else
                      HERE / "voice_eval" / "construction_phrases.json").read_text())
    job = job.get("job", job)
    prompt = voice_glossary.build_prompt(**job)
    cfgs = configs(a.hint)
    langs = sorted({c.lang for c in clips})
    per_lang = {l: [c for c in clips if c.lang == l] for l in langs}
    jobs = [(c, cfg) for c in clips for cfg in cfgs if cfg["model"] != TRANSLATE or c.en]
    no_en = [c.id for c in clips if not c.en]
    print(f"{len(clips)} clips ({', '.join(f'{l}: {len(v)}' for l, v in per_lang.items())}) "
          f"× {len(cfgs)} configurations = {len(jobs)} calls")
    if no_en:
        print(f"no .en.txt (skipped for '{TRANSLATE}'): {', '.join(no_en)}")
    print(f"prompt (~{voice_glossary.estimate_tokens(prompt)} tokens est.): {prompt}\n")

    sem = asyncio.Semaphore(a.concurrency)
    results: List[Result] = []

    async def one(clip: Clip, cfg: Dict[str, Any]) -> None:
        audio = clip.path.read_bytes()
        hint = clip.lang if cfg["hint"] and clip.lang in LANG_NAMES else None
        translated = cfg["model"] == TRANSLATE
        ref = clip.en if translated else clip.text
        r = Result(clip=clip.id, lang=clip.lang, ref=ref, **cfg)
        async with sem:
            try:
                got = await transcribe(cfg["model"], audio, key,
                                       prompt if cfg["prompt"] else None, hint)
                r.hyp, r.detected = got["text"], got.get("language")
                r.wer = voice_metrics.wer(ref, r.hyp)
                r.cer = voice_metrics.cer(ref, r.hyp)
                r.wrong_lang = wrong_language(clip.lang, got, translated)
            except Exception as e:
                r.error = f"{type(e).__name__}: {str(e)[:160]}"
        results.append(r)

    await asyncio.gather(*(one(c, cfg) for c, cfg in jobs))

    for lang in langs:
        print(f"\n== {LANG_NAMES.get(lang, lang).upper()} ({lang}) — {len(per_lang[lang])} clips")
        print(f"   {'configuration':<42} {'WER':>6} {'CER':>6}  wrong-lang  failed")
        for cfg in cfgs:
            sc = score([r for r in results if r.lang == lang and r.model == cfg["model"]
                        and r.prompt == cfg["prompt"] and r.hint == cfg["hint"]])
            w, c = ((f"{sc['wer']:>6.1%}", f"{sc['cer']:>6.1%}") if sc["n"]
                    else (f"{'—':>6}", f"{'—':>6}"))        # every call failed: no score
            print(f"   {label(**cfg):<42} {w} {c}  {sc['wrong_lang']:>10}  {sc['failed']:>6}")
        if a.verbose:
            for clip in per_lang[lang]:
                print(f"\n   {clip.id}: {clip.text}")
                if lang == "yi":
                    print("     the card:")
                    for line in card_lines(clip, results):
                        print(f"       {line}")
                for r in [r for r in results if r.clip == clip.id]:
                    print(f"     {label(r.model, r.prompt, r.hint):<42} "
                          f"{('ERR ' + r.error) if r.error else r.hyp}")
    errors = [r for r in results if r.error]
    if errors:
        print(f"\n{len(errors)} call(s) failed, e.g. {errors[0].model}: {errors[0].error}")
    if a.json:
        Path(a.json).write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False,
                                           indent=1), encoding="utf-8")
        print(f"\nevery transcript: {a.json}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", help="folder: <lang>/<clip>.ogg + <clip>.txt, or manifest.json")
    ap.add_argument("--hint", choices=("off", "on", "both"), default="both",
                    help="the People language hint: off, on, or both (default)")
    ap.add_argument("--job", help="JSON with job/subs/people for the prompt")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--json", help="write every transcript here")
    ap.add_argument("--verbose", action="store_true", help="print every transcript")
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
