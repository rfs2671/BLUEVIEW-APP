"""What Whisper is told to expect: a construction glossary and the job's own
names, passed as Whisper's `prompt`. Pure rules, no database.

WHY (588, Oct 11, live): "I'll send the window shop drawings tomorrow" came
back as "Windows sharp drive". Whisper's prompt is the documented way to
steer spelling toward known words: it reads it as text that came before the
audio. It is not an instruction and it is not fed to the assistant.

THE PROMPT
  "Construction site voice note. Terms: shop drawings, submittal, … .
   Job: 588 Atlantic Ave. Subs: Rivera Electric, … . People: Meilich, … ."

  - The glossary is fixed (GLOSSARY). The job's terms come from the caller:
    its address/name, its subs (trade roster), and the people of its groups.
  - Whisper reads at most 224 tokens of prompt and drops the START of a
    longer one. The prompt is kept under MAX_TOKENS by an estimate that
    over-counts (estimate_tokens), and the job's terms are cut, never the
    glossary: the newest/most specific go first and the list stops when the
    budget is spent.
  - A term list, not sentences: a sentence in English pulls Whisper toward
    English on a Spanish or Yiddish note; a list of names and trade words
    pulls less (the eval's language guard checks it).
"""

from __future__ import annotations

import math
import re
from typing import Iterable, List, Sequence

#: Whisper's own limit is 224; the estimate below over-counts, and the rest
#: is headroom.
MAX_TOKENS = 200

GLOSSARY = (
    "shop drawings", "submittal", "calcs", "core drill", "rebar", "sheetrock",
    "sleeves", "risers", "fire stopping", "SST", "DOB", "TCO", "punch list",
    "inspection", "pour", "formwork", "scaffolding", "sidewalk shed", "hoist",
    "CMU", "slab", "footings", "underpinning", "waterproofing", "framing",
    "ductwork", "sprinkler", "standpipe", "elevator", "facade", "curtain wall",
    "window", "RFI", "change order", "super", "foreman", "GC", "MEP",
    "concrete", "dumpster", "crane", "permit",
)

_HEAD = "Construction site voice note."


_PIECE = re.compile(r"[A-Za-z]+|\d+|\s+|.")


def estimate_tokens(text: str) -> int:
    """An upper bound on Whisper's (GPT-2 BPE) token count, offline: a word
    is one token per 5 letters (at least one), a digit run per 3 digits,
    every other non-space character one token, and a non-Latin letter two
    (Hebrew and accented letters split into bytes)."""
    n = 0
    for p in _PIECE.findall(text or ""):
        if p.isspace():
            continue
        if p.isascii() and p.isalpha():
            n += max(1, math.ceil(len(p) / 5))
        elif p.isdigit():
            n += max(1, math.ceil(len(p) / 3))
        else:
            n += 1 if p.isascii() else 2
    return n


def _clean_terms(terms: Iterable[str], skip: Sequence[str] = ()) -> List[str]:
    seen = {s.lower() for s in skip}
    out = []
    for t in terms or []:
        # Words only: no emoji or symbols (they spend tokens and say nothing),
        # no commas (they would split one name into two terms).
        t = re.sub(r"[^\w\s'&.\-]+", " ", str(t or ""))
        t = " ".join(t.replace("_", " ").split())[:60].strip(" .-")
        if len(t) < 2 or t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
    return out


def build_prompt(job: Iterable[str] = (), subs: Iterable[str] = (),
                 people: Iterable[str] = (), max_tokens: int = MAX_TOKENS) -> str:
    """The prompt for one note: the glossary, then as many of the job's
    terms as fit -- the job itself, then its subs, then its people."""
    base = f"{_HEAD} Terms: {', '.join(GLOSSARY)}."
    budget = max_tokens - estimate_tokens(base)
    parts = []
    taken = set(g.lower() for g in GLOSSARY)
    for label, terms in (("Job", job), ("Subs", subs), ("People", people)):
        kept: List[str] = []
        for t in _clean_terms(terms, skip=list(taken)):
            line = f" {label}: {', '.join(kept + [t])}."
            if estimate_tokens(line) > budget:
                break
            kept.append(t)
            taken.add(t.lower())
        if kept:
            line = f" {label}: {', '.join(kept)}."
            budget -= estimate_tokens(line)
            parts.append(line)
    return base + "".join(parts)


# ── THE EVAL'S MEASURE ───────────────────────────────────────────────────────
# (lib/voice_metrics: the same normalization for English, Spanish, Yiddish.)

def _words(text: str) -> List[str]:
    from lib import voice_metrics
    return voice_metrics.words(text)


def wer(reference: str, hypothesis: str) -> float:
    from lib import voice_metrics
    return voice_metrics.wer(reference, hypothesis)
