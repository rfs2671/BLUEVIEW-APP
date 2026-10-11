"""How far a transcript is from what was said: word and character error rate
over normalized text, for English, Spanish and Yiddish. Pure; the voice
evals use it (scripts/voice_wer_eval.py, scripts/voice_lang_eval.py).

NORMALIZED, the same way for the reference and the transcript:
  - Unicode NFKC, lower case, punctuation (¿¡ « » „ “ … ־) dropped.
  - Yiddish: the points are dropped (פּ אַ אָ → פ א א) and the digraph
    ligatures unfolded (װ ױ ײ → וו וי יי). A transcript that spells a word
    without its points is the same word; YIVO and Hasidic spelling differ
    most there. Final letters are kept.
  - Spanish accents are kept: "está" and "esta" are different words.
CER (characters, spaces aside) is the fairer number for Yiddish, where one
spelling difference makes a whole word wrong.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List

# Hebrew points and cantillation (niqqud, the YIVO pasekh/komets/dagesh, rafe).
_POINTS = re.compile("[֑-ׇ]")
_LIGATURES = {"װ": "וו", "ױ": "וי", "ײ": "יי"}
_HEBREW = re.compile("[א-ת]")
_LATIN = re.compile("[a-zA-ZÀ-ɏ]")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", str(text or "")).lower()
    # NFKC decomposes the pointed presentation forms (U+FB1D–FB4F) to letter
    # + point; the points then go.
    t = unicodedata.normalize("NFD", t)
    t = _POINTS.sub("", t)
    t = unicodedata.normalize("NFC", t)
    for k, v in _LIGATURES.items():
        t = t.replace(k, v)
    t = t.replace("’", "'").replace("‘", "'")
    # Words: letters, digits, apostrophes inside a word.
    return " ".join(re.findall(r"[^\W_]+(?:'[^\W_]+)*", t))


def words(text: str) -> List[str]:
    return normalize(text).split()


def _distance(a: List[str], b: List[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def wer(reference: str, hypothesis: str) -> float:
    """(substitutions + deletions + insertions) / words in the reference."""
    ref, hyp = words(reference), words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _distance(ref, hyp) / len(ref)


def cer(reference: str, hypothesis: str) -> float:
    """The same over characters, spaces aside."""
    ref = list(normalize(reference).replace(" ", ""))
    hyp = list(normalize(hypothesis).replace(" ", ""))
    if not ref:
        return 0.0 if not hyp else 1.0
    return _distance(ref, hyp) / len(ref)


def script_of(text: str) -> str:
    """"hebrew", "latin" or "" (no letters): a Yiddish note written back in
    Latin letters (German, a transliteration) was heard as something else."""
    h, l = len(_HEBREW.findall(text or "")), len(_LATIN.findall(text or ""))
    if not h and not l:
        return ""
    return "hebrew" if h >= l else "latin"
