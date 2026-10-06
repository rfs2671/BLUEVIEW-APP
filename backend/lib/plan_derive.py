"""What the takeoff needs to know about a set, derived from the set itself.

    pair_plan_sheets  which mechanical plan goes with which architectural plan
    unit_tags         which apartments a floor has
    widest_door_in    the widest door the set schedules

Each answers or refuses, with the reason. NOTHING IS GUESSED: a floor whose
units cannot be read is a floor the takeoff refuses (plan_emit writes the
refusal as a record), never a floor given its neighbour's units.

Measured on the 588 Boyland set (16 files, 155 current pages), 2026-10-06:

  pairing   six plan pairs, A-100.01/M-100.00 through A-105.01/M-105.00.
            M-106.00 (BULKHEAD) has no partner - A-105.01 is "ROOF AND
            BULKHEAD", and two mechanical sheets are never paired to one
            architectural sheet (ruling). The second consultant's set numbers
            its plans A.1.1-A.1.7 and has no mechanical sheets at all.
  units     the OCCUPANCY table and the APT tags on the plan agree on every
            floor that has units; A-104.00 (mezzanine) has neither; A-105.01
            (roof) has a table whose only row is PASSIVE RECREATION - zero
            units, which is an answer.
  doors     one schedule in the whole set: A-400.00 (titled WINDOW SCHEDULE),
            an EXTERIOR DOOR SCHEDULE drawn as elevations. D1 4'-8" = 56in.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ── pairing ────────────────────────────────────────────────────────────────

#: an NCS plan-series sheet: discipline, type digit 1 (plans), sequence, and
#: the revision suffix (.00, .01) that a reissue changes and pairing ignores
PLAN_SHEET = re.compile(r"^([A-Z])-(1\d\d)\.(\d\d)$")
#: a plan by its title, for a set that does not number its sheets that way
PLAN_TITLE = re.compile(r"\b(FLOOR\s+PLAN|MEZZANINE(\s+FLOOR)?\s+PLAN|ROOF\b.*\bPLAN|"
                        r"BULKHEAD\b.*\bPLAN)\b", re.I)


def pair_plan_sheets(pages: Iterable[dict]) -> dict:
    """{"pairs": [(arch, mech)], "refused": [(page, reason)]}.

    `pages` are CURRENT pages only (a superseded sheet is the caller's to
    drop), each with "sheet_number" and "sheet_title". The key is the
    sequence number with the revision suffix dropped, IN THE PLAN SERIES
    ONLY: by number alone A-200.01 (elevations) would pair with M-200.00
    (HVAC schedules). Two current sheets of one discipline on one number is
    not a pair - both are refused as ambiguous.

    Refused: a plan-series sheet with no partner, and any page TITLED as a
    plan whose number is outside the series (the second consultant's A.1.x)
    - it has no mechanical partner it could ever be paired by number with.
    """
    by_key: Dict[Tuple[str, str], List[dict]] = {}
    refused: List[Tuple[dict, str]] = []
    for p in pages:
        num = (p.get("sheet_number") or "").strip().upper()
        m = PLAN_SHEET.match(num)
        if m and m.group(1) in ("A", "M"):
            by_key.setdefault((m.group(1), m.group(2)), []).append(p)
        elif PLAN_TITLE.search(p.get("sheet_title") or "") and \
                (not num or re.match(r"^A[.\-]", num)):
            # ARCHITECTURAL or unnumbered only: FA-007 is a fire-alarm plan,
            # not an apartment plan missing its partner
            refused.append((p, f"{num or 'unnumbered sheet'} is a plan with no "
                               "mechanical partner by sheet number"))
    pairs = []
    for seq in sorted({k[1] for k in by_key}):
        a, m = by_key.get(("A", seq), []), by_key.get(("M", seq), [])
        for disc, pp in (("A", a), ("M", m)):
            if len(pp) > 1:
                for p in pp:
                    refused.append((p, f"{len(pp)} current {disc}-{seq} sheets: "
                                       "ambiguous, not paired"))
        if len(a) > 1 or len(m) > 1:
            continue
        if a and m:
            pairs.append((a[0], m[0]))
        elif a:
            refused.append((a[0], f"{a[0]['sheet_number']} has no mechanical "
                                  f"partner M-{seq}"))
        elif m:
            refused.append((m[0], f"{m[0]['sheet_number']} has no architectural "
                                  f"partner A-{seq}"))
    return {"pairs": pairs, "refused": refused}


# ── units ──────────────────────────────────────────────────────────────────

#: an apartment tag as these sets print it: 1A, 4D, 12B, PH1
UNIT_TAG = re.compile(r"^(?:[0-9]{1,2}[A-Z]{1,2}|PH[0-9A-Z]{1,3})$")


def _lines(words, tol=4.0):
    ws = sorted(words, key=lambda w: (w[2], w[1]))
    out, cur = [], []
    for w in ws:
        if cur and abs(w[2] - cur[-1][2]) > tol:
            out.append(sorted(cur, key=lambda w: w[1]))
            cur = []
        cur.append(w)
    if cur:
        out.append(sorted(cur, key=lambda w: w[1]))
    return out


def _table_tags(words) -> Tuple[bool, List[str]]:
    """(the sheet has an OCCUPANCY table, the APT tags it lists).

    TAGS ONLY, NEVER AREAS (ruling): the table's area is gross by its own
    header ("200 GROSS WITHIN THE DWELLING UNITS"). It equals the plan's NET
    on this set; that is the set's coincidence, not a rule.

    A ROW CAN SHARE A TEXT LINE WITH A NEIGHBOURING TABLE. On A.1.5 the APT
    4A UPPER row reads "####### ####### APT 4A UPPER ..." because the next
    table's cells sit on the same baseline, so the row is found by "APT
    <tag>" anywhere in a line, not by a line that starts with APT."""
    heads = [w for w in words if w[0].upper().startswith("OCCUPANCY")]
    tags: List[str] = []
    for h in heads:
        below = [w for w in words
                 if h[2] < w[2] < h[2] + 220 and h[1] - 220 < w[1] < h[1] + 260]
        for ln in _lines(below):
            toks = [t for t, _x, _y in ln]
            for i in range(len(toks) - 1):
                if toks[i].upper().rstrip(".") == "APT" and UNIT_TAG.match(toks[i + 1]):
                    if toks[i + 1] not in tags:
                        tags.append(toks[i + 1])
    return bool(heads), tags


def _plan_tags(words, extent, table_top) -> List[str]:
    """The APT tag bubbles on the plan: the word APT with a tag directly
    below it, inside the plan's extent and above the tables."""
    lo, hi = extent
    out: List[str] = []
    for t, x, y in words:
        if t.upper().rstrip(".") != "APT":
            continue
        if not (lo[0] <= x <= hi[0] and lo[1] <= y <= min(hi[1], table_top)):
            continue
        if any(abs(w[2] - y) < 3 and 0 < w[1] - x < 30 and UNIT_TAG.match(w[0])
               for w in words):
            continue                         # "APT 1B 320 SF." - a table row
        below = [w for w in words
                 if UNIT_TAG.match(w[0]) and abs(w[1] - x) < 20 and 0 < w[2] - y < 30]
        if below:
            tag = min(below, key=lambda w: w[2] - y)[0]
            if tag not in out:
                out.append(tag)
    return out


def unit_tags(words: Sequence[Tuple[str, float, float]], corners) -> dict:
    """{"tags", "method", "zero_units", "why"} for one architectural floor.

    The OCCUPANCY table first, the plan's APT tags second (ruling). Both
    present and different is the sheet contradicting itself: refused, never
    picked between. A table with no APT row and no tag on the plan is a
    floor with NO units - a derived answer (A-105.01, the roof). Neither a
    table nor a tag is a floor nothing can be said about: refused."""
    import numpy as np
    pts = np.asarray(corners, dtype=float).reshape(-1, 2)
    extent = (tuple(np.percentile(pts, 1, axis=0)), tuple(np.percentile(pts, 99, axis=0))) \
        if len(pts) else ((float("-inf"),) * 2, (float("inf"),) * 2)
    has_table, table = _table_tags(words)
    table_top = min([w[2] for w in words if w[0].upper().startswith("OCCUPANCY")]
                    or [float("inf")]) - 10
    plan = _plan_tags(words, extent, table_top)
    if table and plan and sorted(table) != sorted(plan):
        return {"tags": None, "method": None, "zero_units": False,
                "why": f"the occupancy table lists {sorted(table)} and the plan "
                       f"tags {sorted(plan)}: the sheet contradicts itself"}
    if table:
        return {"tags": sorted(table), "method": "occupancy_table",
                "zero_units": False, "why": None}
    if plan:
        return {"tags": sorted(plan), "method": "plan_tags",
                "zero_units": False, "why": None}
    if has_table:
        return {"tags": [], "method": "occupancy_table", "zero_units": True,
                "why": None}
    return {"tags": None, "method": None, "zero_units": False,
            "why": "no occupancy table and no unit tags on the sheet"}


# ── doors ──────────────────────────────────────────────────────────────────

FEET_INCHES = re.compile(r"""^(\d{1,2})'-(\d{1,2})(?:\s*(\d)/(\d{1,2}))?"?$""")
DOOR_MARK = re.compile(r"^D\d{1,3}$")


def _inches(text: str) -> Optional[float]:
    m = FEET_INCHES.match(text.strip())
    if not m:
        return None
    v = int(m.group(1)) * 12 + int(m.group(2))
    if m.group(3):
        v += int(m.group(3)) / int(m.group(4))
    return float(v)


def widest_door_in(directed_words: Sequence[Tuple[str, float, float, str]]) -> dict:
    """{"inches", "doors", "why"} - the widest door a door schedule shows.

    THE SCHEDULE ON THIS SET IS DRAWN, NOT TABULATED: A-400.00's EXTERIOR
    DOOR SCHEDULE is one elevation per door, under "NUMBER <D1>". A door's
    width is the horizontal feet-inch dimension in its panel; the vertical
    8'-0" beside it is its height and reads bottom-to-top. Direction is
    what separates them - the largest dimension in a panel is a height.

    No schedule, or a schedule with no readable width, is None: no doorway
    gap is closed and the layer path falls back (plan_space_layers)."""
    words = [(t, x, y, d) for t, x, y, d in directed_words]
    heads = [w for w in words if w[0].upper() == "SCHEDULE"
             and any(v[0].upper() == "DOOR" and abs(v[2] - w[2]) < 4
                     and 0 < w[1] - v[1] < 90 for v in words)]
    if not heads:
        return {"inches": None, "doors": {}, "why": "no door schedule on the sheet"}
    panels = []
    for t, x, y, d in words:
        if t.upper() != "NUMBER" or d != "ltr":
            continue
        mark = [v for v in words if DOOR_MARK.match(v[0]) and abs(v[2] - y) < 4
                and 0 < v[1] - x < 80]
        if mark:
            panels.append((min(mark, key=lambda v: v[1] - x)[0], x, y))
    if not panels:
        return {"inches": None, "doors": {},
                "why": "a door schedule with no NUMBER <Dn> panel to read"}
    panels.sort(key=lambda p: (round(p[2]), p[1]))
    doors: Dict[str, float] = {}
    for mark, x, y in panels:
        right = min([p[1] for p in panels if abs(p[2] - y) < 4 and p[1] > x]
                    or [x + 260])
        widths = [_inches(t) for t, wx, wy, d in words
                  if d == "ltr" and x - 20 <= wx < right - 10 and y < wy < y + 450
                  and _inches(t)]
        if widths:
            doors[mark] = max(widths)
    if not doors:
        return {"inches": None, "doors": {},
                "why": "door panels carry no horizontal width dimension"}
    return {"inches": max(doors.values()), "doors": doors, "why": None}
