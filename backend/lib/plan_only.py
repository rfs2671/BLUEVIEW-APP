"""A PLAN-ONLY FAMILY: equipment no schedule counts, located on its plan.

Ruling (operator, 2026-10-26), verbatim:

    "Roof drains: plan-only family allowed at sheet scope when a detail/note
    in the set names the object (P-400 detail, SD1-2 note), labeled "located
    on P-206; no schedule lists them". Bind per tag only: RD-1 (roof drain,
    J.R. Smith detention) and RD-2 (overflow). A combined total refuses; the
    render states 2 + 2. SD1-2's "2" is a printed figure for RD-1: agree
    binds, disagree withholds both. Includes rotation-aware sweep + fix for
    SLOPE DN arrows crossing labels."

Every other located family is a mechanical schedule with an identifier
column (plan_glyph_pass.families). A roof drain is on no such schedule: on
588 Boyland the drains are drawn on P-206.00 (the roof sanitary & storm plan,
/Rotate 270), their tags are what P-400.00's plumbing rough-in table lists
under ABBR (RD-1 ROOF DRAIN, RD-2 OVERFLOW ROOF DRAIN - a list of fixture
types and their pipe sizes, with no quantity), and the set names the object
in P-400.00's ROOF DRAIN DETAIL and in SD1-2's note "2 J.R. Smith Special
Purpose (Model 1010-83) Roof Drains". So:

  - the family exists only while a DETAIL OR NOTE in the set names the object
    (`named_by`); no naming record, no family - at pass time and at question
    time alike;
  - its closed tag set is the tags the set prints for the object
    (`tag_rows`), each with the words that tell it from the others
    ("overflow" for RD-2; RD-1, the bare object, has none and is named only
    by its tag);
  - it is located on the family's plans only (`PLANS`), at sheet scope -
    never placed in a unit or on a floor;
  - a figure binds PER TAG ONLY; a clause counting the family as one total
    refuses (plan_search);
  - a note's printed figure for one tag (`printed`) must agree with the
    located count, or neither is stated.

Rulings 2026-10-28 (operator, verbatim, with the questions they answer):

  13  "The label 'no schedule lists them' isn't literally true: P-400 lists
      RD-1 and RD-2 without a count." - 'yes: "no schedule prints their
      quantity"'. So LABEL.
  14  "Can 'the roof' name where RD-1 and RD-2 are?" - "yes, only the level
      the plan's title names". A figure is still at sheet scope; the one
      level a clause may name is the level printed in the family plan's own
      title (P-206.00 ROOF SANITARY & STORM PLAN: the roof) - plan_search.
  15  "Should 'J.R. Smith', 'detention' or 'controlled-flow' refer to
      RD-1?" - "yes, SD1-2's own words". A candidate (`also`) names a tag
      only where the note that prints that tag's figure prints it itself
      (`also_names`). Measured 2026-10-28: SD1-2 p4 prints "J.R. Smith" and
      "Detention" in RD-1's line; "controlled flow" only in another note
      ("... by means of controlled flow device & roof detention"), which
      names no roof drain - so it names nothing.

What a plan-only family adds to the reader and what it does not: no
database access here. The server hands in records; plan_glyph_pass locates;
plan_search binds.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

#: name -> the object the set must name, and which plans it is drawn on.
#: ONE FAMILY, BY RULING. A plan-only family is allowed where the operator
#: has ruled it; another is a new ruling, not a new row here by inference.
PLAN_ONLY: Dict[str, Dict[str, Any]] = {
    "ROOF DRAINS": {
        "object": ("roof", "drain"),
        # THE ROOF'S STORM PLAN: a P sheet whose printed title names the roof
        # and its storm drainage - "ROOF SANITARY & STORM PLAN" (P-206.00).
        # Not "ROOF FLOOR DOMESTIC WATER & GAS PLANS" (P-105.00), nor a riser
        # diagram (P-302.00 draws the same RD-1/RD-2 a second time).
        "sheet_prefix": "P-",
        "plan_title": re.compile(r"\bROOF\b.*\b(?:STORM|DRAIN(?:AGE)?)\b.*\bPLANS?\b", re.I),
        # OTHER NAMES A TAG MAY GO BY (ruling 15, 2026-10-28): candidates
        # only. Each names a tag only where the note printing that tag's
        # figure prints it (also_names) - never from a vision read, and a
        # candidate the set does not print there names nothing.
        "also": ("J.R. Smith", "detention", "controlled-flow"),
    },
}

#: How the render and every row label the family (ruling 13, 2026-10-28:
#: P-400.00's rough-in table LISTS RD-1 and RD-2, with no quantity column).
LABEL = "located on {sheets}; no schedule prints their quantity"

#: The SLOPE DN fix (plan_takeoff.ink_only): on P-206.00 the labels are black
#: (0), the drain symbols dark grey (~64-80) and the SLOPE DN arrows and their
#: text a lighter grey pen (~160). Everything lighter than this is not read.
INK_BELOW = 120

#: Records that can NAME the object: a detail title or a note. Never a
#: legend entry (A-1xx's FLOOR/AREA/ROOF DRAIN legend glyph), an element count,
#: a schedule (its rows are the tag set, not a naming), a located row, or
#: anything read off the image.
NAMING_TYPES = frozenset({"note", "callout", "text", "dimension"})
_NEVER_TIER = frozenset({"vision_read", "registered_glyph"})

_TAG = re.compile(r"^[A-Z]{1,4}-\d{1,3}[A-Z]?$")


def object_pattern(obj: Sequence[str]) -> "re.Pattern[str]":
    """'roof drain' as printed: words in order, spaces optional (OCR runs
    'OVERFLOWROOFDRAIN' together), plural allowed."""
    return re.compile(r"\s*".join(re.escape(w) for w in obj) + r"s?(?![A-Za-z])", re.I)


def _stem(w: str) -> str:
    w = w.lower()
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def tag_rows(records: Iterable[Dict[str, Any]], obj: Sequence[str]) -> Dict[str, str]:
    """tag -> its description, from every schedule row that prints the object
    beside a tag-shaped cell. A tag described two different ways is dropped:
    the set does not say which it is."""
    rx = object_pattern(obj)
    out: Dict[str, set] = {}
    for r in records or []:
        if r.get("record_type") != "schedule":
            continue
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        for row in payload.get("rows") or []:
            if not isinstance(row, list) or len(row) < 2:
                continue
            cells = [re.sub(r"\s+", " ", str(c or "")).strip() for c in row]
            desc = [c for c in cells if rx.search(c)]
            tags = [c.upper() for c in cells if _TAG.match(c.upper())]
            if len(desc) == 1 and len(tags) == 1:
                out.setdefault(tags[0], set()).add(desc[0].upper())
    return {t: next(iter(d)) for t, d in sorted(out.items()) if len(d) == 1}


def tag_words(tags: Dict[str, str], obj: Sequence[str]) -> Dict[str, List[str]]:
    """tag -> the words that tell it from the family's other tags: its
    description with the object removed, less any word another tag's
    description also carries. RD-2 'OVERFLOW ROOF DRAIN' -> ['overflow'];
    RD-1 'ROOF DRAIN' -> [] (named only by its tag)."""
    rx = object_pattern(obj)
    own = {t: {_stem(w) for w in re.findall(r"[A-Za-z]{3,}", rx.sub(" ", d))}
           for t, d in tags.items()}
    out = {}
    for t, ws in own.items():
        others = set().union(*(v for k, v in own.items() if k != t)) if len(own) > 1 else set()
        out[t] = sorted(ws - others)
    return out


def named_by(records: Iterable[Dict[str, Any]], obj: Sequence[str]) -> List[Dict[str, Any]]:
    """The details and notes in the set that name the object."""
    rx = object_pattern(obj)
    out = []
    for r in records or []:
        if (r.get("record_type") not in NAMING_TYPES or r.get("tier") in _NEVER_TIER):
            continue
        q = re.sub(r"\s+", " ", str(r.get("quote") or "")).strip()
        if rx.search(q):
            sn = str(r.get("sheet_number") or "")
            # where a reader finds it: the sheet number when it is one ('1 OF 1'
            # is what SD1-2's title block reads as), else the file and page
            where = sn if re.match(r"^[A-Z]{1,3}-\d", sn) else f"{r.get('file_name')} p{r.get('page_number')}"
            out.append({"sheet": r.get("sheet_number"), "file": r.get("file_name"),
                        "page": r.get("page_number"), "where": where, "quote": q[:200]})
    return sorted(out, key=lambda n: (str(n["file"]), str(n["page"]), n["quote"]))


def printed_figures(names: Sequence[Dict[str, Any]], tags: Dict[str, str],
                    words: Dict[str, List[str]], obj: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    """tag -> [{"value", "source"}]: a note that prints 'N ... <object>s'.

    A FIGURE IS FOR ONE TAG OR FOR NONE. SD1-2's '2 J.R. Smith ... Roof
    Drains' names the bare object, so it is the figure of the tag whose own
    description is the bare object (RD-1, ROOF DRAIN - ruling 2026-10-26); a
    note carrying another tag's word ('2 overflow roof drains') is that tag's;
    a note that fits no single tag lends nothing."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for n, m, tag in _figures(names, words, obj):
        src = f"{n.get('file') or n.get('sheet')} p{n.get('page')}"
        out.setdefault(tag, []).append({"value": m.group(1), "source": src,
                                        "quote": n["quote"][:120]})
    return out


def _figures(names: Sequence[Dict[str, Any]], words: Dict[str, List[str]],
             obj: Sequence[str]) -> List[tuple]:
    """[(naming, figure match, tag)]: each 'N ... <object>s' a naming prints,
    with the one tag it is for (printed_figures' rule)."""
    rx = re.compile(r"(?<![\w.])(\d{1,3})\s+(.{0,80}?)" + object_pattern(obj).pattern, re.I)
    bare = [t for t, w in words.items() if not w]
    out = []
    for n in names:
        for m in rx.finditer(n["quote"]):
            between = {_stem(w) for w in re.findall(r"[A-Za-z]{3,}", m.group(2))}
            hit = [t for t, w in words.items() if w and set(w) & between]
            tag = hit[0] if len(hit) == 1 else (bare[0] if not hit and len(bare) == 1 else None)
            if tag:
                out.append((n, m, tag))
    return out


def name_pattern(name: str) -> "re.Pattern[str]":
    """A candidate name as printed: its letters and digits in order, with any
    spaces, dots or hyphens between them ('J.R. Smith', 'JR Smith';
    'controlled-flow', 'controlled flow')."""
    parts = re.findall(r"[A-Za-z0-9]+", name)
    return re.compile(r"(?<![A-Za-z0-9])" + r"[\s.\-]*".join(map(re.escape, parts))
                      + r"(?![A-Za-z0-9])", re.I)


def also_names(names: Sequence[Dict[str, Any]], words: Dict[str, List[str]],
               obj: Sequence[str], candidates: Sequence[str]) -> Dict[str, List[str]]:
    """tag -> the candidates (ruling 15) that the note printing the tag's
    figure prints ITSELF. SD1-2 p4's '2 J.R. Smith Special Purpose (Model
    1010-83) Roof Drains @ 3.57gpm @3" Detention' is RD-1's figure, so RD-1
    goes by 'J.R. Smith' and 'detention'; 'controlled-flow' is not in it.
    The notes are namings (named_by): text-layer details and notes, never a
    vision read. A candidate two tags' notes print names neither."""
    found: Dict[str, set] = {}
    for n, _m, tag in _figures(names, words, obj):
        for c in candidates:
            if name_pattern(c).search(n["quote"]):
                found.setdefault(tag, set()).add(c)
    shared = {c for t, cs in found.items() for c in cs
              if any(c in o for u, o in found.items() if u != t)}
    return {t: [c for c in candidates if c in cs and c not in shared]
            for t, cs in sorted(found.items()) if cs - shared}


#: A crossing pen erased from a label leaves a gap in its hyphen, read as two:
#: 'RD--1' on P-206.00's right-hand RD-1 and RD-2 once the SLOPE DN arrow
#: through the dash is gone (plan_takeoff.ink_only).
_SPLIT_HYPHEN = re.compile(r"(?<=[A-Za-z])\s*[-\u2013\u2014]{2,}\s*(?=\d)")


def mend_hyphen(text: str) -> str:
    return _SPLIT_HYPHEN.sub("-", str(text or ""))


def exact_label_reads(reads: Iterable[Sequence[Any]], tags: Sequence[str]) -> List[tuple]:
    """The reads, from any number of sweeps, that print one of `tags`
    EXACTLY (no letter corrected) - with a split hyphen mended.

    A NEAR MISS IS ANOTHER TAG HERE. P-206.00 prints FD-1, a floor drain,
    one letter from RD-1, and no table in the set lists FD-1 for a near miss
    to lose to: snapped with one edit it was counted as a roof drain, and
    the total came out right by cancelling the RD-1 the arrows hid
    (measured 2026-10-26). A plan-only family has no rating column to
    corroborate a near miss, so none is taken; every drain's label is read
    exactly by the plain sweep or the ink-only one."""
    from lib import plan_symbols as psym
    out = []
    for r in reads or []:
        text = mend_hyphen(r[0])
        tag, d = psym.snap(text, tags)
        if tag and d == 0:
            out.append((text,) + tuple(r[1:]))
    return out


def families(records: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """name -> {"tags", "tag_names", "tag_words", "named_by", "printed",
    "also", "object"} for every plan-only family the set allows: it names the object
    in a detail or note, and prints tags for it. A family the set does not
    name is absent - never present and empty."""
    records = list(records or [])
    out = {}
    for name, d in PLAN_ONLY.items():
        names = named_by(records, d["object"])
        tags = tag_rows(records, d["object"])
        if not names or not tags:
            continue
        words = tag_words(tags, d["object"])
        out[name] = {"tags": sorted(tags), "tag_names": tags, "tag_words": words,
                     "named_by": names, "object": " ".join(d["object"]),
                     "printed": printed_figures(names, tags, words, d["object"]),
                     "also": also_names(names, words, d["object"], d.get("also") or ())}
    return out


def is_family_plan(page: Dict[str, Any], name: str) -> bool:
    """The page is one the family is located on (its sheet prefix and title)."""
    d = PLAN_ONLY.get(name) or {}
    sn = str(page.get("sheet_number") or "").strip().upper()
    return bool(d) and sn.startswith(d["sheet_prefix"]) and bool(
        d["plan_title"].search(str(page.get("sheet_title") or "")))


def label(sheets: Iterable[str]) -> str:
    return LABEL.format(sheets=" / ".join(sorted({str(s) for s in sheets if s})) or "its plan")


#: A plain-language query the server runs for the records a family can rest
#: on: anything printing the object (records are then sorted by the rules above).
def record_query(project_id: str, page_ids: Sequence[str]) -> Dict[str, Any]:
    ors = []
    for d in PLAN_ONLY.values():
        pat = r"\s*".join(d["object"])
        ors += [{"quote": {"$regex": pat, "$options": "i"}},
                {"payload.rows": {"$elemMatch": {"$elemMatch": {"$regex": pat, "$options": "i"}}}}]
    return {"project_id": str(project_id), "page_id": {"$in": list(page_ids)},
            "record_type": {"$ne": "glyph"}, "$or": ors}


__all__ = ["PLAN_ONLY", "LABEL", "INK_BELOW", "families", "also_names", "name_pattern", "mend_hyphen", "exact_label_reads", "tag_rows", "tag_words",
           "named_by", "printed_figures", "is_family_plan", "label", "object_pattern",
           "record_query"]
