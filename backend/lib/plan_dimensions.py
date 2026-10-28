"""Dimensions as whole values, for the gate (plan_search.answer_is_grounded).

── WHY THE DIGITS WERE NOT ENOUGH ─────────────────────────────────────────
#
# The gate split a dimension into its numbers and checked each one against
# every number the returned records print. Measured 2026-10-25 on 588
# Boyland, asked for the door sizes with A-400.00's door schedule returned:
# "The doors are 3'-5" X 7'-0"." was ALLOWED. Nothing prints 3'-5"; a 3, a 5,
# a 7 and a 0 are each printed somewhere, and that was all the gate asked.
#
# So a dimension in a claim binds only if the WHOLE dimension, normalized, is
# printed in the returned evidence (ruling 2026-10-25):
#
#   - feet-inches, feet, inches, and the same in words (8 feet, 6 inches),
#     normalized to a length, so 12' and 12'-0" and 144" are one value;
#   - "A X B" (and A X B X C) as an ordered whole: 3'-0" X 7'-0" binds only
#     where that pair is printed, never from a 3'-0" here and a 7'-0" there;
#   - the reversed text layer: a run drawn upside down reads back
#     character-reversed, so 7'-0" comes out as "0-'7 (A-400.00, Z-001.01,
#     A-500.00: 36 occurrences). The evidence is read both ways.
#
# A number that is not a dimension is not this module's business; the
# caller keeps checking those as before, and a count is never a dimension.
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

_FT = "'’′"
_IN = "\"”″"
_NUM = r"\d+(?:\.\d+)?"
# 7 1/2, 1/2, 7.5, 7
_LEN = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_FT_WORD = r"(?:feet|foot|ft\.?)(?![A-Za-z])"
_IN_WORD = r"(?:inches|inch|in\.)(?![A-Za-z])"

# One component: feet[-inches], inches, either in words, or a bare number
# (only inside an A X B, where the X is what makes it a dimension).
_COMP = (
    rf"(?:(?P<ft>{_NUM})\s*[{_FT}]"
    rf"(?:\s*-\s*(?P<fin>{_LEN})\s*[{_IN}]?|\s*(?P<fin2>{_LEN})\s*[{_IN}])?"
    rf"|(?P<wft>{_NUM})\s*{_FT_WORD}(?:\s*(?P<wfin>{_LEN})\s*{_IN_WORD})?"
    rf"|(?P<inch>{_LEN})\s*[{_IN}]"
    rf"|(?P<win>{_LEN})\s*{_IN_WORD}"
    rf"|(?P<bare>{_LEN}))"
)
_COMP_RE = re.compile(_COMP, re.I)
_COMP_ANON = re.sub(r"\?P<\w+>", "", _COMP)
_X = r"\s*[xX×]\s*"
# Not part of a name: PTAC-1, M-200.00, 2/3 of a fraction already taken.
_LEAD = r"(?<![A-Za-z0-9.\-/])"
_CHAIN_RE = re.compile(
    _LEAD + rf"(?P<chain>{_COMP_ANON}(?:{_X}{_COMP_ANON})+)", re.I)
_SINGLE_RE = re.compile(
    _LEAD + rf"(?:(?P<ft>{_NUM})\s*[{_FT}]"
    rf"(?:\s*-\s*(?P<fin>{_LEN})\s*[{_IN}]?|\s*(?P<fin2>{_LEN})\s*[{_IN}])?"
    rf"|(?P<wft>{_NUM})\s*{_FT_WORD}(?:\s*(?P<wfin>{_LEN})\s*{_IN_WORD})?"
    rf"|(?P<inch>{_LEN})\s*[{_IN}]"
    rf"|(?P<win>{_LEN})\s*{_IN_WORD})",
    re.I)
# A run the text layer reads back reversed: 7'-0" arrives as "0-'7 and
# 2'-7 1/2" as "2/1 7-'2. The hyphen between the marks is what makes it
# unambiguous; an inch mark before a digit alone could be a quotation.
_REVERSED_RE = re.compile(rf"[{_IN}](\d[\d/ ]*?)\s*-\s*[{_FT}](\d+)")


class Dim(NamedTuple):
    """One length. `unit` is 'in' for a stated unit, '' for a bare number
    inside an A X B; `value` is inches for 'in', the number itself for ''."""
    unit: str
    value: Fraction


def _num(s: Optional[str]) -> Fraction:
    s = (s or "0").strip()
    total = Fraction(0)
    for part in s.split():
        if "/" in part:
            a, b = part.split("/", 1)
            total += Fraction(int(a), int(b)) if int(b) else Fraction(0)
        else:
            total += Fraction(part)
    return total


def _component(m: "re.Match") -> Dim:
    g = m.groupdict()
    if g.get("ft") is not None:
        return Dim("in", _num(g["ft"]) * 12 + _num(g.get("fin") or g.get("fin2")))
    if g.get("wft") is not None:
        return Dim("in", _num(g["wft"]) * 12 + _num(g.get("wfin")))
    if g.get("inch") is not None:
        return Dim("in", _num(g["inch"]))
    if g.get("win") is not None:
        return Dim("in", _num(g["win"]))
    return Dim("", _num(g.get("bare")))


def _chain(text: str) -> Tuple[Dim, ...]:
    parts = [_component(_COMP_RE.fullmatch(p.strip()))
             for p in re.split(_X, text) if _COMP_RE.fullmatch(p.strip())]
    # A bare number takes the unit of a stated neighbour: 6x6" is 6" X 6",
    # and 48x99 Inch is 48" X 99" (the last component reads "99 Inch"). The
    # neighbour's value is already in inches, so whether that unit was feet
    # is read back from the text.
    if not any(p.unit for p in parts):
        return tuple(parts)
    feet_only = bool(re.search(rf"[{_FT}]|{_FT_WORD}", text, re.I)) and not re.search(
        rf"[{_IN}]|{_IN_WORD}", text, re.I)
    scale = 12 if feet_only else 1
    return tuple(p if p.unit else Dim("in", p.value * scale) for p in parts)


class Found(NamedTuple):
    span: Tuple[int, int]
    text: str
    dims: Tuple[Dim, ...]      # one for a single length, two or more for A X B


def find(text: str) -> List[Found]:
    """Every dimension in `text`, chains (A X B) before single lengths, each
    character in at most one."""
    text = text or ""
    out: List[Found] = []
    taken = [False] * (len(text) + 1)
    for m in _CHAIN_RE.finditer(text):
        dims = _chain(m.group("chain"))
        if len(dims) >= 2:
            out.append(Found(m.span(), m.group(0), dims))
            for i in range(*m.span()):
                taken[i] = True
    for m in _SINGLE_RE.finditer(text):
        if any(taken[i] for i in range(*m.span())):
            continue
        out.append(Found(m.span(), m.group(0), (_component(m),)))
    out.sort(key=lambda f: f.span)
    return out


def unreverse(text: str) -> str:
    """`text` with every reversed feet-inches run read the right way round,
    appended (the original stays, so nothing printed is lost)."""
    runs = [m.group(0)[::-1] for m in _REVERSED_RE.finditer(text or "")]
    return (text or "") + ("  " + "  ".join(runs) if runs else "")


def mask_quotation_marks(text: str) -> str:
    """A claim's quotation marks blanked, so the closing mark of "PTAC-1: 21"
    is not read as 21 inches. An inch mark ends a number; a quotation mark
    opens after a space and closes after anything but a number - or after a
    bare number at the end of what it quotes, which is the one ambiguous
    case and is read as the quotation (the claim then states 21, which the
    caller checks as a number)."""
    chars = list(text or "")
    open_ = False
    for i, ch in enumerate(chars):
        if ch in "“":
            open_ = True
            chars[i] = " "
            continue
        if ch not in "\"”":
            continue
        prev = text[i - 1] if i else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if not open_:
            if (not prev or prev.isspace() or prev in "([{:") and nxt and not nxt.isspace():
                open_ = True
                chars[i] = " "
            continue
        if not prev.isdigit():
            open_ = False
            chars[i] = " "
            continue
        j = i - 1
        while j >= 0 and (text[j].isdigit() or text[j] in " /.-"):
            j -= 1
        in_feet = j >= 0 and text[j] in _FT
        if not in_feet and (not nxt or not nxt.isalnum()):
            open_ = False
            chars[i] = " "
    return "".join(chars)


def _same(a: Dim, b: Dim) -> bool:
    if a.unit == b.unit:
        return a.value == b.value
    # A bare number against a stated length: the number as the sheet would
    # print it - inches, or whole feet.
    stated, bare = (a, b) if a.unit else (b, a)
    return bare.value == stated.value or (
        stated.value % 12 == 0 and bare.value == stated.value / 12)


class Evidence(NamedTuple):
    singles: Tuple[Dim, ...]
    chains: Tuple[Tuple[Dim, ...], ...]


def evidence(texts: Iterable[str]) -> Evidence:
    """Every length and every A X B the texts print, the reversed runs read
    the right way round."""
    singles: List[Dim] = []
    chains: List[Tuple[Dim, ...]] = []
    for t in texts:
        for f in find(unreverse(str(t))):
            if len(f.dims) > 1:
                chains.append(f.dims)
            singles.extend(f.dims)
    return Evidence(tuple(set(singles)), tuple(set(chains)))


def supported(found: Found, ev: Evidence) -> bool:
    """A single length binds if any printed length equals it; an A X B binds
    only if that whole A X B, in that order, is printed."""
    if len(found.dims) == 1:
        d = found.dims[0]
        return any(_same(d, e) for e in ev.singles)
    return any(len(c) == len(found.dims) and all(_same(a, b) for a, b in zip(found.dims, c))
               for c in ev.chains)


def record_texts(records: Sequence[Dict[str, Any]], skip) -> List[str]:
    """The printed strings a record set offers as evidence: each quote and
    every scalar of its payload, as `_supported_values` reads them."""
    out: List[str] = []
    for r in records or []:
        if skip(r):
            continue
        out.append(str(r.get("quote") or ""))
        payload = r.get("payload")
        if isinstance(payload, dict):
            for v in payload.values():
                if isinstance(v, (str, int, float)):
                    out.append(str(v))
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, (str, int, float)):
                            out.append(str(item))
                        elif isinstance(item, list):
                            out.extend(str(c) for c in item)
    return out


__all__ = ["Dim", "Found", "Evidence", "find", "unreverse",
           "mask_quotation_marks", "evidence", "supported", "record_texts"]
