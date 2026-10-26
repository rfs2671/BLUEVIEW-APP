"""SET HEALTH: what the drawing set says about its own completeness.

Rulings (operator, 2026-10-26, PR 5). Each item is RECORDED, and refuses
only the claims that depend on what it names:

  family_not_reconciled   a schedule with no identifier column. Its rows
                          are no closed tag set, so nothing can be checked
                          against the plans. "schedule present, no
                          identifier column, not reconciled" - every claim
                          about that family refuses with this reason, and no
                          family is ever skipped silently. (On 588 Boyland:
                          the diffuser schedule - its A1/A2 come only from a
                          vision read, which is not schedule truth.)
  plan_tag_not_in_schedule  a tag printed on a mechanical plan that no
                          schedule lists. Only that tag's claims refuse.
  schedule_tag_not_located  a schedule tag no mechanical plan shows as a
                          symbol: "not located" (the DH-1 wording). Refuses
                          nothing else.
  mentioned_unlocated     a schedule tag inside a prose note ("DH-1. DUCT
                          HEATER"): recorded, bound to its schedule row,
                          never counted or placed.
  missing_referenced_sheet  a sheet referenced IN REFERENCE CONTEXT - "SEE X",
                          "REFER TO X", "ON X", a row of the set's drawing
                          list, or X inside a detail/section callout bubble -
                          that is not in the current set. A warning on the
                          referencing sheet; bare mentions (ASTM A-446, the
                          paint colour OC-152) count for nothing, and there is
                          no stoplist of codes.
  duplicate_sheet_number  two current pages of one track print one number.
  mechanical_without_architectural  a mechanical plan with no architectural
                          partner: its per-apartment placement is refused
                          (sheet-scope floor and building totals still bind -
                          ruling 2026-10-07; M-106.00 narrow, 2026-10-26).

Measured 2026-10-26 on 588 Boyland: the reference rule finds exactly the
seven real missing sheets (S-204, S-400, FO-101, FO-202, A-600, EN-003,
EN-004) and none of ASTM A-446 / C-955 / OC-152; no plan tag outside a
schedule; DH-1 the only schedule tag never located; prose mentions of DH-1,
EF-1 and EF-2.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

COLLECTION = "plan_set_health"

FAMILY_NOT_RECONCILED = "family_not_reconciled"
PLAN_TAG_NOT_IN_SCHEDULE = "plan_tag_not_in_schedule"
SCHEDULE_TAG_NOT_LOCATED = "schedule_tag_not_located"
MENTIONED_UNLOCATED = "mentioned_unlocated"
MISSING_REFERENCED_SHEET = "missing_referenced_sheet"
DUPLICATE_SHEET_NUMBER = "duplicate_sheet_number"
MECHANICAL_WITHOUT_ARCHITECTURAL = "mechanical_without_architectural"

NOT_RECONCILED = "schedule present, no identifier column, not reconciled"

# ── references in reference context ───────────────────────────────────────

_X = r"([A-Z]{1,3})-(\d{3})(?:\.(\d{2}))?(?![0-9])"
_PHRASE = re.compile(r"\b(?:SEE|REFER\s+TO|ON)\s+(?:SHEETS?\s+|DWGS?\.?\s+|DRAWINGS?\s+)?" + _X)
_LIST_HEAD = re.compile(r"\b(DRAWING\s+(LIST|INDEX)|SHEET\s+(LIST|INDEX)|LIST\s+OF\s+DRAWINGS)\b")
_LIST_ROW = re.compile(r"(?<![A-Z0-9.\-/])(\d{1,3})\s+" + _X + r"\b")
_TOKEN = re.compile(r"^" + _X + r"$")


def sheet_stem(sheet_number: Any) -> Optional[str]:
    """'S-101.00' -> 'S-101'; None for a page with no plan-shaped number."""
    m = re.match(r"^\s*([A-Z]{1,3})-(\d{3})", str(sheet_number or "").upper())
    return f"{m.group(1)}-{m.group(2)}" if m else None


def text_references(text: str) -> Dict[str, str]:
    """{sheet stem: how it is referenced} from a page's text: "SEE X" /
    "REFER TO X" / "ON X" phrasing, and the rows of a drawing list.

    A DRAWING LIST IS A NUMBERED SEQUENCE: on a page headed as one, "n X"
    counts when the numbers run - n-1 or n+1 is another row. Line breaks
    are not relied on: the stored text puts each row on its own line, while
    a PDF text layer may run the whole list together."""
    t = (text or "").upper()
    out = {f"{m.group(1)}-{m.group(2)}": "phrase" for m in _PHRASE.finditer(t)}
    if _LIST_HEAD.search(t):
        rows = [(int(m.group(1)), f"{m.group(2)}-{m.group(3)}") for m in _LIST_ROW.finditer(t)]
        nums = {n for n, _s in rows}
        for n, s in rows:
            if n - 1 in nums or n + 1 in nums:
                out.setdefault(s, "drawing list")
    return out


def callout_bubbles(drawings: Iterable[dict]) -> List[Tuple[float, float, float, float]]:
    """Detail/section callout bubbles: closed paths of curves, roughly round,
    10-80 pt across (plan_page drawings)."""
    out = []
    for d in drawings or []:
        if sum(1 for it in d.get("items") or [] if it[0] == "c") < 4:
            continue
        x0, y0, x1, y1 = d["rect"]
        w, h = x1 - x0, y1 - y0
        if 10 <= w <= 80 and 10 <= h <= 80 and 0.75 <= w / h <= 1.33:
            out.append((x0, y0, x1, y1))
    return out


def bubble_references(words: Iterable[Tuple], drawings: Iterable[dict]) -> Set[str]:
    """Sheet stems printed INSIDE a callout bubble (directed_words)."""
    bubbles = callout_bubbles(drawings)
    out = set()
    for w in words or []:
        text, x, y = w[0], w[1], w[2]
        m = _TOKEN.match(str(text).strip().upper())
        if m and any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in bubbles):
            out.add(f"{m.group(1)}-{m.group(2)}")
    return out


def missing_references(pages: Sequence[dict], present: Set[str],
                       open_page: Optional[Callable[[dict], Any]] = None) -> List[dict]:
    """A warning per (referencing sheet, missing sheet). `pages` carry
    raw_text; `open_page` (when given) lets callout bubbles be read from the
    page's geometry - a page that cannot be opened is read by its text alone."""
    found: Dict[Tuple[str, str], str] = {}
    for p in pages:
        src = p.get("sheet_number") or f"{p.get('file_name')} p{p.get('page_number')}"
        own = sheet_stem(p.get("sheet_number"))
        refs = dict(text_references(p.get("raw_text") or ""))
        if open_page is not None:
            pg = None
            try:
                pg = open_page(p)
                for s in bubble_references(pg.directed_words, pg.drawings):
                    refs.setdefault(s, "callout bubble")
            except Exception:                   # a page that cannot be read: text only
                pass
            finally:
                if pg is not None and hasattr(pg, "close"):
                    pg.close()
        for s, how in refs.items():
            if s != own and s not in present:
                found.setdefault((str(src), s), how)
    return [{"kind": MISSING_REFERENCED_SHEET, "sheet": src, "subject": s,
             "detail": f"{src} refers to {s} ({how}); {s} is not in the current set"}
            for (src, s), how in sorted(found.items())]


# ── tags read on the mechanical plans ─────────────────────────────────────

_STANDALONE_TAG = re.compile(r"^([A-Z]{1,5}-\d{1,3}[A-Z]?)(?:\(\d+\))?\.?$")
_INNER_TAG = re.compile(r"(?<![A-Z0-9])([A-Z]{1,5}-\d{1,3}[A-Z]?)(?![0-9A-Z])")


def tag_reads(sheet: str, reads: Iterable[Tuple], families: Dict[str, dict]) -> List[dict]:
    """From one mechanical plan's sweep: tags printed there that no schedule
    lists (standalone, tag-shaped reads), and schedule tags inside prose -
    a read that carries a tag and at least two other words."""
    owner = {t: (n, f.get("sheet")) for n, f in families.items() for t in f.get("tags") or []}
    orphans: Dict[str, int] = {}
    out = []
    for r in reads or []:
        text = str(r[0]).strip().upper()
        m = _STANDALONE_TAG.match(text)
        if m:
            if m.group(1) not in owner:
                orphans[m.group(1)] = orphans.get(m.group(1), 0) + 1
            continue
        words = re.findall(r"[A-Z]{2,}", text)
        for t in _INNER_TAG.findall(text):
            if t in owner and len([w for w in words if w not in t]) >= 2:
                name, sched = owner[t]
                out.append({"kind": MENTIONED_UNLOCATED, "sheet": sheet, "subject": t,
                            "family": name, "schedule_sheet": sched,
                            "at": [round(float(r[1]), 1), round(float(r[2]), 1)],
                            "detail": f"{t} is mentioned in a note on {sheet} "
                                      f"({str(r[0]).strip()!r}); a mention, never counted"})
    for t, n in sorted(orphans.items()):
        out.append({"kind": PLAN_TAG_NOT_IN_SCHEDULE, "sheet": sheet, "subject": t,
                    "detail": f"{t} is printed {n} time(s) on {sheet} but no schedule lists it"})
    return out


def unreconciled(families: Dict[str, dict]) -> List[dict]:
    """A schedule with no identifier column: never skipped silently."""
    return [{"kind": FAMILY_NOT_RECONCILED, "sheet": f.get("sheet"), "subject": n,
             "detail": f"{n}: {NOT_RECONCILED}"}
            for n, f in sorted(families.items()) if not f.get("tags")]


def not_located(families: Dict[str, dict], located: Set[str]) -> List[dict]:
    """Schedule tags no mechanical plan shows as a symbol."""
    return [{"kind": SCHEDULE_TAG_NOT_LOCATED, "sheet": f.get("sheet"), "subject": t,
             "family": n, "detail": f"{t} ({n}): the schedule lists it; its symbols "
                                    f"were not located"}
            for n, f in sorted(families.items()) for t in f.get("tags") or [] if t not in located]


def duplicates(track: str, pages: Sequence[dict]) -> List[dict]:
    seen: Dict[str, List[str]] = {}
    for p in pages:
        sn = str(p.get("sheet_number") or "").strip().upper()
        if sn:
            seen.setdefault(sn, []).append(f"{p.get('file_name')} p{p.get('page_number')}")
    return [{"kind": DUPLICATE_SHEET_NUMBER, "sheet": sn, "subject": sn, "track": track,
             "detail": f"{sn} is current twice on the {track} track: {', '.join(v)}"}
            for sn, v in sorted(seen.items()) if len(v) > 1]


def unpaired_mechanical(track: str, unpaired: Sequence[dict]) -> List[dict]:
    return [{"kind": MECHANICAL_WITHOUT_ARCHITECTURAL, "sheet": p.get("sheet_number"),
             "subject": p.get("sheet_number"), "track": track,
             "detail": f"{p.get('sheet_number')} has no architectural partner: its symbols "
                       f"are counted at sheet scope; no per-apartment figure"}
            for p in unpaired or []]


def dedupe(items: Iterable[dict]) -> List[dict]:
    out, seen = [], set()
    for it in items:
        k = (it.get("kind"), str(it.get("sheet")), str(it.get("subject")), it.get("track"))
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out
