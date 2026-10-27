"""An apartment's or a room's area, checked against the area the plan prints.

Operator's rule (Roy, 2026-10-26): "apartment/room areas, checked against
printed areas on the plans (agree binds, disagree withholds both, like QTY)."

THE TWO FIGURES
  computed  the region the plan reader closes for the apartment
            (plan_space: its rooms, joined through its own doorways), with
            the walls BETWEEN its own rooms, measured in cells and scaled by
            the VERIFIED scale of the viewport whose walls bound it
            (plan_scale). A room is its closed region (doorways sealed).
  printed   the figure the sheet prints INSIDE that region: "NET: 482 SQ.
            FT." in the box beside an APT tag; "<n> SQ. FT." under a room's
            name ("BIKE ROOM / 113 SQ. FT."). Assigned by where it sits,
            never by the nearest tag.

THE RULE (like the schedule's QTY, plan_search._qty_in_clause)
  agrees      within AREA_TOL: both figures bind.
  disagrees   NEITHER binds - the printed figure is withheld too - and the
              disagreement is said.
  no_printed  the sheet prints no area for it: nothing binds; the computed
              figure is never stated on its own.
  refused     no computed figure: the region is not on a viewport whose
              scale verified, spans two drawings, holds two printed figures,
              or was closed at a scale its viewport does not have. Nothing
              is added and nothing withheld: the printed figure binds only as
              it did before this check, through a returned record that
              prints it (an open question to the operator, 2026-10-26: QTY
              ruling (a) would let it stand from the area row alone).
  GROSS       printed in the NET's box, never measured: withheld with its
              NET when the NET disagrees; otherwise untouched.

WHICH PRINTED AREA IS WHICH, MEASURED ON 588 BOYLAND (2026-10-26,
C:/Users/asddd/bv-worktrees/L5_areas_measure.md), 14 A plans, three sets:
  NET    = the floor inside the apartment's perimeter walls, its interior
           partitions included. Every one of the 30 apartments whose region
           is the apartment the NET box describes agrees within 0.21%
           (2A: 482 printed, 481.8 measured). The unit's rooms alone, without
           their partitions, read 2-7% low on every one: that is the walls.
  GROSS  = NOT measured here (a gross line runs to the exterior face and
           the demising centreline; no wall-centreline model exists). It is
           carried, unchecked, and never compared.
  room   = the closed room under the name. BIKE ROOM 113, HWH ROOM 78 and the
           roof's PASSIVE RECREATION 2112 / 1970 agree within 0.3%. A
           BEDROOM 96 is the designer's 12'-0" x 8'-0" rectangle; its closed
           region also holds the strip in front of its closet and measures
           104.5 (+8.9%): disagrees. A closed region holding two printed room
           areas (LIVING AREA + KITCHENETTE, one open space) is no one
           room's: refused.

AREA_TOL is from that measurement and from what the error is made of: see
the constant.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ── constants ──────────────────────────────────────────────────────────────

#: A computed area agrees with a printed one when it is within this fraction
#: of it. FROM THE ERROR BUDGET AND THE MEASUREMENT, NOT FROM A PASS RATE:
#:   - the printed figure is a whole square foot: +-0.5 sf, which is 0.64% of
#:     the smallest printed area on Boyland (HWH ROOM, 78 sf) and 0.2% of the
#:     smallest apartment (1D, 256 sf);
#:   - the region is 2" cells; each straight wall's face lies somewhere in
#:     its cell, half a cell (1") either way of where the edge correction
#:     puts it: about 1% of a 78 sf room's area at one standard deviation,
#:     far less on an apartment (its interior walls are filled, only its
#:     perimeter counts);
#:   - measured: every agreement on Boyland is within 0.27% (34 figures,
#:     apartments and rooms); the nearest disagreement is +8.9% (a BEDROOM
#:     region that includes its closet front), the next +33%.
#: 2% is about seven times the largest measured agreement and under a
#: quarter of the nearest disagreement. Sensitivity, not tuning: every
#: Boyland verdict is the same for any tolerance from 0.3% to 8.8%.
AREA_TOL = 0.02

RECORD_TYPE = "area"
#: Its own collection, like set health: an area row is no plan record, so
#: search never ranks it and the eval's record baseline does not move.
COLLECTION = "plan_areas"
#: 1 (2026-10-26): first version.
AREA_VERSION = 1

AGREES, DISAGREES, NO_PRINTED, REFUSED = "agrees", "disagrees", "no_printed", "refused"
NO_INK = "no ink bounds the region"
NO_DRAWING = "its walls belong to no titled drawing"
APARTMENT, ROOM = "apartment", "room"

_NUM = re.compile(r"^\d[\d,]*(?:\.\d+)?$")
#: A room's name: purely alphabetic words (no "FT.", no "NET:").
_NAME_WORD = re.compile(r"^[A-Z][A-Z/&\-]*$")


# ── what the sheet prints ──────────────────────────────────────────────────

@dataclass
class PrintedArea:
    kind: str                                   # "net" | "gross" | "room"
    value: float                                # square feet
    text: str                                   # as printed: "NET: 482 SQ. FT."
    box: Tuple[float, float, float, float]      # the number's box
    name: str = ""                              # a room's name

    @property
    def at(self) -> Tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2)


def _is_sq_ft(words: Sequence[tuple]) -> int:
    """How many of `words` (left to right) spell SQ. FT. / SF (0 if they do
    not). SQ. IN. is not an area of floor."""
    if not words:
        return 0
    w0 = words[0][0].upper()
    if w0 in ("SF", "SF.", "S.F.", "SQFT", "SQFT.", "SQ.FT."):
        return 1
    if w0 in ("SQ.", "SQ") and len(words) > 1 and words[1][0].upper() in ("FT.", "FT"):
        return 2
    return 0


def printed_areas(word_boxes: Sequence[tuple]) -> List[PrintedArea]:
    """Every area printed on the plan: "<n> SQ. FT." after "NET:" or
    "GROSS:" on its own line, or with nothing before it on its line (a room
    label: its name is the line above). A figure inside a sentence ("STAIR
    AREAS: 71 SQ. FT. AND 71 SQ. FT.") is a note, not a label, and is not
    read. `word_boxes` are plan_page.PlanPage.directed_word_boxes."""
    ltr = [b for b in word_boxes if b[5] == "ltr"]
    out: List[PrintedArea] = []
    for b in ltr:
        if not _NUM.match(b[0]):
            continue
        h = b[4] - b[2]
        if h <= 0:
            continue
        cy = (b[2] + b[4]) / 2
        same = [c for c in ltr if abs((c[2] + c[4]) / 2 - cy) <= 0.4 * h]
        right = sorted([c for c in same if 0 <= c[1] - b[3] <= 1.2 * h], key=lambda c: c[1])
        nxt = [right[0]] if right else []
        if right:
            nxt += sorted([c for c in same if 0 <= c[1] - right[0][3] <= 1.2 * h], key=lambda c: c[1])[:1]
        n_unit = _is_sq_ft(nxt)
        if not n_unit:
            continue
        # The word before it: "NET:" / "GROSS:" sit a tab stop away (1.7
        # heights on Boyland); a word of a sentence one space away (0.3).
        left = [c for c in same if 0 <= b[1] - c[3] <= 3.5 * h]
        prev = max(left, key=lambda c: c[3]) if left else None
        p = prev[0].upper() if prev else ""
        if p not in ("NET:", "GROSS:") and prev is not None and b[1] - prev[3] > 1.2 * h:
            prev, p = None, ""                    # another label on the same baseline
        unit_txt = " ".join(c[0] for c in nxt[:n_unit])
        if p == "NET:":
            out.append(PrintedArea("net", float(b[0].replace(",", "")),
                                   f"{prev[0]} {b[0]} {unit_txt}", tuple(b[1:5])))
        elif p == "GROSS:":
            out.append(PrintedArea("gross", float(b[0].replace(",", "")),
                                   f"{prev[0]} {b[0]} {unit_txt}", tuple(b[1:5])))
        elif prev is None:
            name = _name_above(ltr, b, h)
            text = (f"{name} " if name else "") + f"{b[0]} {unit_txt}"
            out.append(PrintedArea("room", float(b[0].replace(",", "")), text,
                                   tuple(b[1:5]), name=name))
    return out


def _name_above(ltr: Sequence[tuple], b: tuple, h: float) -> str:
    """A room label's name: the alphabetic words of the nearest line above
    the figure, overlapping it."""
    cands = [c for c in ltr if b[2] - 1.6 * h <= c[4] <= b[2] + 0.3 * h
             and c[1] < b[3] + 3 * h and c[3] > b[1] - 3 * h and _NAME_WORD.match(c[0].upper())]
    if not cands:
        return ""
    yb = max(c[4] for c in cands)
    line = sorted([c for c in cands if abs(c[4] - yb) < 0.5 * h], key=lambda c: c[1])
    return " ".join(c[0].upper() for c in line)


# ── the computed figure ────────────────────────────────────────────────────

def _shift(a, k: int, axis: int, sign: int):
    """b[i] = a[i - sign*k] along `axis` (False where it falls off)."""
    import numpy as np
    b = np.zeros_like(a)
    n = a.shape[axis]
    if k >= n:
        return b
    src, dst = [slice(None)] * 2, [slice(None)] * 2
    if sign > 0:
        src[axis], dst[axis] = slice(0, n - k), slice(k, n)
    else:
        src[axis], dst[axis] = slice(k, n), slice(0, n - k)
    b[tuple(dst)] = a[tuple(src)]
    return b


def wall_cells(lab, owned, thick_cells: int):
    """The cells a wall occupies: the barrier cells (label 0), and every
    closed region no unit or common area holds that is narrower than the
    thickest wall everywhere - the strip between a stud wall's two face
    lines, which the room map closes as a region of its own."""
    import numpy as np
    from scipy import ndimage
    free = lab == 0
    st = np.ones((thick_cells, thick_cells), bool)
    for L in np.unique(lab):
        if not L:
            continue
        R = lab == L
        if (R & owned).any():
            continue
        if not ndimage.binary_erosion(R, st).any():
            free |= R
    return free


def with_interior_walls(mask, free, reach: int):
    """The apartment's rooms and the walls BETWEEN them: every wall cell with
    the same apartment on both sides along a row or a column, within `reach`
    cells, through wall only. A perimeter wall has the apartment on one side
    only and is not taken."""
    out = mask.copy()
    for axis in (0, 1):
        hit = {}
        for sign in (1, -1):
            h = mask & False
            path = mask | True
            for k in range(1, reach + 1):
                h |= path & _shift(mask, k, axis, sign)
                path &= _shift(free, k, axis, sign)
            hit[sign] = h
        out |= free & hit[1] & hit[-1]
    return out


def _edges(mask) -> int:
    import numpy as np
    m = mask.astype(np.int8)
    return int(np.abs(np.diff(m, axis=0)).sum() + np.abs(np.diff(m, axis=1)).sum()
               + m[0].sum() + m[-1].sum() + m[:, 0].sum() + m[:, -1].sum())


def region_area_sf(mask, cell_pt: float, pt_per_in: float) -> float:
    """Square feet of a region of cells. A wall's face line falls somewhere
    inside the cell it marks, and that whole cell is barrier: on average the
    region stops half a cell short of the face. So each cell edge on the
    region's boundary adds half a cell (measured: a 2'-0" x 4'-0" closet
    reads 7.0 sf in whole cells, 8.0 with the half cell)."""
    side_in = cell_pt / pt_per_in
    return (int(mask.sum()) + 0.5 * _edges(mask)) * side_in ** 2 / 144.0


def region_viewport(sheet, lo, cell_pt: float, mask):
    """(the viewport whose ink bounds the region, why not). The walls round
    a region are ink of the drawing it is in: the bodies of ink
    (plan_scale.Sheet.labels) on the ring just outside it must be ONE body,
    and a viewport's. An annotation island inside the region (the NET box,
    an APT bubble) is not on the ring and does not matter."""
    import numpy as np
    from scipy import ndimage
    from lib import plan_scale as ps
    ring = ndimage.binary_dilation(mask, iterations=2) & ~mask
    ys, xs = np.nonzero(ring)
    L = sheet.labels
    bodies: Counter = Counter()
    for r, c in zip(ys, xs):
        x, y = lo[0] + (c + 0.5) * cell_pt, lo[1] + (r + 0.5) * cell_pt
        i, j = int(y / ps.CELL_PT), int(x / ps.CELL_PT)
        for k in {int(z) for z in L[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2].ravel() if z}:
            bodies[k] += 1
    if not bodies:
        return None, NO_INK
    if len(bodies) > 1:
        return None, f"its walls are ink of {len(bodies)} separate drawings"
    (k,) = bodies
    v = next((v for v in sheet.viewports if v.body == k), None)
    if v is None:
        return None, NO_DRAWING
    return v, ""


def verdict(computed: Optional[float], printed: Optional[float]) -> str:
    if computed is None:
        return REFUSED
    if printed is None:
        return NO_PRINTED
    return AGREES if abs(computed / printed - 1) <= AREA_TOL else DISAGREES


# ── one floor ──────────────────────────────────────────────────────────────

def floor_areas(page, space: Dict[str, Any], *, scale_sheet=None,
                word_boxes: Optional[Sequence[tuple]] = None,
                thick_in: Optional[float] = None) -> List[Dict[str, Any]]:
    """Every apartment region and every printed room area on one plan, each
    with its computed figure (or why there is none), the figure printed in
    it, and the verdict. `space` is plan_space.build_space's map - the
    regions as they are BEFORE an open-to-below void joins a unit (a void is
    no floor area of the unit beside it)."""
    import numpy as np
    from lib import plan_scale as ps
    from lib.plan_sheet import CELL_IN, PT_PER_INCH, thickest_legend_wall_in

    boxes = page.directed_word_boxes if word_boxes is None else word_boxes
    sheet = ps.read_sheet(page) if scale_sheet is None else scale_sheet
    lab, lo, cell = space["closed_lab"], space["lo"], float(space["cell_pt"])
    units: Dict[str, Any] = space.get("units") or {}
    printed = printed_areas(boxes)
    if thick_in is None:
        try:
            thick_in = thickest_legend_wall_in([(b[0], (b[1] + b[3]) / 2, (b[2] + b[4]) / 2)
                                                for b in boxes])
        except ValueError:
            thick_in = None

    def cell_of(x, y):
        r, c = int((y - lo[1]) / cell), int((x - lo[0]) / cell)
        return (r, c) if 0 <= r < lab.shape[0] and 0 <= c < lab.shape[1] else None

    def scale_for(mask):
        """(pt_per_in, viewport dict, why)."""
        v, why = region_viewport(sheet, lo, cell, mask)
        if v is None:
            return None, None, why
        vd = {"title": v.title, "note": v.scale_text, "verified": v.verified,
              "pt_per_in": v.pt_per_in, "agreeing": v.agreeing}
        if not v.verified:
            return None, vd, f"its viewport ({v.title or 'untitled'}) is not verified: {v.refusal}"
        if abs(v.pt_per_in / PT_PER_INCH - 1) > ps.AGREE_TOL:
            return None, vd, (f"the region was closed assuming 1/4\" = 1'-0\"; its viewport "
                              f"verifies at {v.scale_text}")
        return v.pt_per_in, vd, ""

    owned = space.get("public")
    owned = np.zeros(lab.shape, bool) if owned is None else owned.copy()
    for m in units.values():
        owned |= m
    out: List[Dict[str, Any]] = []
    placed = set()

    # APARTMENTS: the unit region with its own interior walls, against the
    # NET printed inside it.
    for u in sorted(units):
        m = units[u]
        inside = [p for p in printed if p.kind in ("net", "gross")
                  and (cell_of(*p.at) is not None and m[cell_of(*p.at)])]
        nets = [p for p in inside if p.kind == "net"]
        gross = [p for p in inside if p.kind == "gross"]
        placed.update(id(p) for p in inside)
        row: Dict[str, Any] = {"scope": APARTMENT, "unit": u, "name": "",
                               "printed": None, "printed_text": "", "printed_box": None,
                               "gross_printed": gross[0].value if len(gross) == 1 else None,
                               "gross_text": gross[0].text if len(gross) == 1 else "",
                               "computed": None, "viewport": None, "why": ""}
        if len(nets) > 1:
            row.update(why=f"{len(nets)} NET figures are printed inside {u}'s region: "
                           + ", ".join(p.text for p in nets))
        elif nets:
            row.update(printed=nets[0].value, printed_text=nets[0].text,
                       printed_box=[round(v, 1) for v in nets[0].box])
        if not row["why"]:
            if thick_in is None:
                row["why"] = "no wall legend on the sheet: the walls between its rooms cannot be bounded"
            else:
                tc = int(math.ceil(thick_in / CELL_IN))
                free = wall_cells(lab, owned, tc)
                enc = with_interior_walls(m, free, tc + 1)
                ppi, vd, why = scale_for(enc)
                row.update(viewport=vd, why=why)
                if ppi:
                    row["computed"] = round(region_area_sf(enc, cell, ppi), 1)
        out.append(row)

    # A NET figure no apartment region holds: its apartment cannot be named
    # by place, so it is reported and checks nothing.
    for p in printed:
        if p.kind == "net" and id(p) not in placed:
            out.append({"scope": APARTMENT, "unit": None, "name": "", "printed": p.value,
                        "printed_text": p.text, "printed_box": [round(v, 1) for v in p.box],
                        "gross_printed": None, "gross_text": "", "computed": None,
                        "viewport": None,
                        "why": "no apartment region holds this printed figure"})

    # ROOMS: a printed room area against the closed room it sits in. A
    # label is a plan's only inside a titled drawing and off the outdoors:
    # the OCCUPANCY and LIGHT & AIR tables print "<n> SF." rows below the
    # plan, and a table's row is no room.
    titled = [v.drawing_bbox for v in sheet.viewports if v.note is not None]
    outdoors = set(space.get("outdoors") or ())

    def on_a_plan(p):
        x, y = p.at
        rc = cell_of(x, y)
        return (any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in titled)
                and rc is not None and int(lab[rc]) not in outdoors)
    rooms = [p for p in printed if p.kind == "room" and p.name and on_a_plan(p)]
    by_region: Dict[int, List[PrintedArea]] = {}
    for p in rooms:
        rc = cell_of(*p.at)
        L = int(lab[rc]) if rc is not None else 0
        by_region.setdefault(L, []).append(p)
    for L, ps_ in sorted(by_region.items()):
        for p in ps_:
            unit = None
            row = {"scope": ROOM, "unit": None, "name": p.name, "printed": p.value,
                   "printed_text": p.text, "printed_box": [round(v, 1) for v in p.box],
                   "gross_printed": None, "gross_text": "", "computed": None,
                   "viewport": None, "why": ""}
            if not L:
                row["why"] = "the figure sits on no closed room"
            else:
                R = lab == L
                unit = next((u for u, m in units.items() if (m & R).any()), None)
                row["unit"] = unit
                ppi, vd, why = scale_for(R)
                if vd is None and why in (NO_INK, NO_DRAWING):
                    continue                    # a table's cell, not a room of a plan
                row.update(viewport=vd, why=why)
                if len(ps_) > 1:
                    row["why"] = (f"its closed room holds {len(ps_)} printed room areas ("
                                  + ", ".join(q.text for q in ps_) + ") - it is no one room's")
                elif ppi:
                    row["computed"] = round(region_area_sf(R, cell, ppi), 1)
            out.append(row)
    for r in out:
        r["status"] = verdict(r["computed"], r["printed"])
        if r["computed"] is not None and r["printed"]:
            r["diff_pct"] = round(100 * (r["computed"] / r["printed"] - 1), 2)
        else:
            r["diff_pct"] = None
    return out


# ── rows ───────────────────────────────────────────────────────────────────

#: the citation fields an area row carries from its page (as plan_emit)
CITE = ("project_id", "company_id", "file_id", "file_hash", "file_name",
        "page_id", "page_number", "sheet_number", "sheet_title", "discipline")


def area_rows(results: Iterable[Dict[str, Any]], page: Dict[str, Any], *,
              track: Optional[str] = None) -> List[Dict[str, Any]]:
    """One row per apartment and printed room area of one plan."""
    rows = []
    for i, r in enumerate(results):
        rows.append({
            **{k: page.get(k) for k in CITE},
            "record_type": RECORD_TYPE,
            "ordinal": i,
            "unit": r.get("unit"),
            "quote": r.get("printed_text") or "",
            "status": r["status"],
            "payload": {
                "scope": r["scope"], "name": r.get("name") or "",
                "printed_sf": r.get("printed"), "printed_box": r.get("printed_box"),
                "computed_sf": r.get("computed"), "diff_pct": r.get("diff_pct"),
                "gross_printed_sf": r.get("gross_printed"), "gross_text": r.get("gross_text") or "",
                "viewport": r.get("viewport"), "why": r.get("why") or "",
                "tolerance": AREA_TOL, "track": track,
                "drawing_track": page.get("drawing_track"),
                "drawing_track_label": page.get("drawing_track_label"),
                "area_version": AREA_VERSION,
            },
        })
    return rows


# ══════════════════════════════════════════════════════════════════════════
# The gate and the render
# ══════════════════════════════════════════════════════════════════════════

#: A question about an area: these words in the subject fetch the area rows.
_AREA_SUBJECT = re.compile(
    r"\b(?:area|areas|square|sq|sf|footage|size|sizes|big|net|gross|apartment|apartments|"
    r"apt|apts|unit|units|room|rooms|bedroom|bedrooms|living|kitchen|kitchenette|den|studio)\b",
    re.I)

#: An area figure in a claim: a number with an area unit.
AREA_UNIT = re.compile(
    r"\b(?:sq\.?\s*(?:ft|feet|foot)\.?|s\.?f\.?|sqft|square\s+(?:feet|foot|ft))(?![A-Za-z])|ft\s*(?:2|²)\b|ft²",
    re.I)

#: A room name that is only a word of the question ("the AREA of 2A") never
#: makes a clause about a room.
_GENERIC_NAMES = frozenset({"AREA", "ROOM", "SPACE", "SIZE", "NET", "GROSS", "TOTAL", "FLOOR",
                            "APT", "APARTMENT", "UNIT"})

#: An apartment tag in a claim (plan_search._UNIT_REF).
_UNIT_REF = re.compile(r"(?<![A-Za-z0-9.\-/])(\d{1,2}[A-Z]{1,2})(?![A-Za-z0-9])", re.I)


#: A thousands comma: "1,970".
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


def join_thousands(text: str) -> str:
    """"1,970 sq ft" -> "1970 sq ft": the gate splits clauses at commas."""
    return _THOUSANDS.sub("", text or "")


def is_area_subject(subject: str, attribute: str = "") -> bool:
    return bool(_AREA_SUBJECT.search(f"{subject or ''} {attribute or ''}"))


def is_area_record(r: Dict[str, Any]) -> bool:
    return r.get("record_type") == RECORD_TYPE


def is_area_clause(clause: str) -> bool:
    return bool(AREA_UNIT.search(clause or ""))


def _payload(r):
    return r.get("payload") if isinstance(r.get("payload"), dict) else {}


def _figure(v) -> Optional[str]:
    if v is None:
        return None
    f = float(v)
    return str(int(f)) if f.is_integer() else str(f)


def _row_track(r) -> Optional[str]:
    return _payload(r).get("track")


def figures_in_clause(clause: str, records: Sequence[Dict[str, Any]],
                      tracks: frozenset = frozenset()) -> Tuple[set, set]:
    """(area figures the clause may state, area figures it may not), for a
    clause stating an area. `tracks`: the drawing tracks the clause names
    (plan_search._track_claim) - none named, every track's rows count.

    THE ROWS THE CLAUSE IS ABOUT: those of the apartments it names (2A); of
    those, the room rows whose name it names ("the bedroom in 2A"), else the
    apartment rows. Naming no apartment, the rooms it names anywhere, else
    every row - for what it may NOT state only: a figure withheld for some
    apartment is never stated as an area of nothing in particular.

    Per row:  agrees      -> printed and computed (rounded) may be stated
              disagrees   -> the printed figure may not, nor the GROSS in its box
              refused     -> nothing added, nothing withheld: a printed figure
                             binds only as it did before (a record quotes it)
              no_printed  -> nothing (the computed figure is never added)
    A figure one track withholds is withheld, whatever another allows: two
    tracks that differ bind only a claim that names its set."""
    rows = [r for r in records or [] if is_area_record(r)]
    if tracks:
        rows = [r for r in rows if _row_track(r) in tracks]
    if not rows:
        return set(), set()
    low = (clause or "").lower()
    units = {m.group(1).upper() for m in _UNIT_REF.finditer(clause or "")}
    known = {str(r.get("unit")).upper() for r in rows if r.get("unit")}
    units &= known
    names = {(_payload(r).get("name") or "") for r in rows if _payload(r).get("scope") == ROOM}
    named = {n for n in names if n and n not in _GENERIC_NAMES and re.search(r"\b" + re.escape(n.lower()) + r"\b", low)}
    if units:
        scope = [r for r in rows if str(r.get("unit") or "").upper() in units]
        if named:
            scope = [r for r in scope if _payload(r).get("scope") == ROOM
                     and _payload(r).get("name") in named]
        else:
            scope = [r for r in scope if _payload(r).get("scope") == APARTMENT]
        decide = True
    elif named:
        scope = [r for r in rows if _payload(r).get("scope") == ROOM
                 and _payload(r).get("name") in named]
        decide = True
    else:
        scope, decide = rows, False
    allow, drop = set(), set()
    for r in scope:
        p = _payload(r)
        st = r.get("status")
        printed, computed = _figure(p.get("printed_sf")), p.get("computed_sf")
        if st == AGREES:
            if decide:
                allow.add(printed)
                allow.add(str(int(round(float(computed)))))
        elif st == DISAGREES:
            drop.add(printed)
            # GROSS is printed in the NET's box and never measured: the box
            # is what the region contradicts, so its GROSS is withheld too.
            drop.add(_figure(p.get("gross_printed_sf")))
        # refused / no_printed / an uncontradicted GROSS: nothing added and
        # nothing withheld - a printed figure binds only as it did before,
        # through a returned record that prints it (question 1, 2026-10-26).
    allow.discard(None)
    drop.discard(None)
    return allow - drop, drop


def render_area_evidence(records: Sequence[Dict[str, Any]]) -> str:
    """The area rows as the model is shown them: per apartment and room, what
    is printed, what the region measures, and which figure may be stated."""
    rows = [r for r in records or [] if is_area_record(r)]
    if not rows:
        return ""
    lines = ["Areas (the area printed on the plan, checked against the region the plan "
             f"closes for it at its viewport's VERIFIED scale; within {AREA_TOL:.0%} they "
             "agree). State an area ONLY where a line below says it may be stated:"]

    def key(r):
        p = _payload(r)
        return (str(r.get("unit") or "~"), p.get("scope") != APARTMENT, p.get("name") or "",
                str(r.get("sheet_number") or ""), str(p.get("track") or ""))
    for r in sorted(rows, key=key):
        p = _payload(r)
        who = (f"{r.get('unit')}" if p.get("scope") == APARTMENT and r.get("unit")
               else f"{p.get('name')}" + (f" in {r.get('unit')}" if r.get("unit") else "")
               if p.get("scope") == ROOM else "an apartment the plan does not name")
        where = str(r.get("sheet_number") or "?")
        label = p.get("drawing_track_label") or ("the filed set" if p.get("track") in (None, "filed")
                                                 else p.get("track"))
        where = f"{where}, {label}"
        kind = "NET" if p.get("scope") == APARTMENT else "area"
        pr, cp = _figure(p.get("printed_sf")), p.get("computed_sf")
        scale = (p.get("viewport") or {}).get("note") or ""
        st = r.get("status")
        if st == AGREES:
            s = (f"{kind} {pr} sq ft printed; the region measures {cp} sq ft at {scale} "
                 f"(verified) - they agree ({p.get('diff_pct'):+.1f}%). May be stated: {pr}.")
        elif st == DISAGREES:
            s = (f"{kind} {pr} sq ft printed, but the region measures {cp} sq ft at {scale} "
                 f"({p.get('diff_pct'):+.1f}%) - they DISAGREE. State NEITHER figure; say the "
                 f"printed area and the drawn region disagree.")
        elif st == NO_PRINTED:
            s = ("no area is printed for it on this sheet. Its measured region is NOT "
                 "stated; say no area is printed.")
        else:
            s = (f"{kind} {pr} sq ft printed, not checked ({p.get('why')})." if pr else
                 f"no area can be measured ({p.get('why')}).")
        if p.get("gross_printed_sf") is not None:
            s += (f" GROSS {_figure(p.get('gross_printed_sf'))} sq ft is printed in the same box: "
                  + ("withheld with it." if st == DISAGREES else "not measured, not checked."))
        lines.append(f"- {who} [{where}]: {s}")
    return "\n".join(lines)


def withheld_note(quote: str, records: Sequence[Dict[str, Any]]) -> str:
    """A suffix for a quoted record line that prints an area the check
    withheld (its unit tag and the figure both in the quote), so the
    fallback render never repeats a withheld figure as if it stood."""
    q = quote or ""
    for r in records or []:
        if not is_area_record(r) or r.get("status") != DISAGREES or not r.get("unit"):
            continue
        fig = _figure(_payload(r).get("printed_sf"))
        if fig and re.search(r"(?<![\d.])" + re.escape(fig) + r"(?![\d])", q.replace(",", "")) \
                and re.search(r"(?<![A-Za-z0-9])" + re.escape(str(r["unit"])) + r"(?![A-Za-z0-9])", q):
            return (f" - the plan's drawn region for {r['unit']} measures "
                    f"{_payload(r).get('computed_sf')} sq ft: this printed area is not confirmed")
    return ""


__all__ = ["AREA_TOL", "RECORD_TYPE", "COLLECTION", "AREA_VERSION",
           "AGREES", "DISAGREES", "NO_PRINTED", "REFUSED", "APARTMENT", "ROOM",
           "PrintedArea", "printed_areas", "wall_cells", "with_interior_walls",
           "region_area_sf", "region_viewport", "verdict", "floor_areas", "area_rows",
           "is_area_subject", "is_area_record", "is_area_clause", "figures_in_clause",
           "render_area_evidence", "withheld_note", "join_thousands"]
