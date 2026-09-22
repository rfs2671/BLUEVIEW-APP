"""Count one equipment type per apartment, from a mechanical sheet, the
architectural sheet under it, and the schedule's closed set of tags.

    run_takeoff(arch_page, mech_page, closed_set, corroborations, unit_tags,
                widest_door_in)

The sheet says where its equipment is by printing a tag beside it, so the
takeoff is LABEL-ANCHORED: an OCR sweep (lib.plan_ocr) finds reads that snap
to the schedule's closed set, the geometry beside each label is the symbol,
the symbol is carried onto the architectural sheet by corner registration,
and plan_space says which apartment holds it.

FAIL-SAFE, in order of priority:
  - a point in a region holding other than one unit tag is REFUSED;
  - outdoors / unenclosed space is never an answer (host-wall probe, else
    refuse); an unnamed, doorless non-unit region is never an answer;
  - no per-unit total is emitted unless the sheet is complete and every
    contributing point came from a single-tag region.

No database access. The caller supplies the pages and the schedule's tags.
"""
from __future__ import annotations

import io
import logging
from collections import Counter
from typing import Dict, Optional, Sequence

import numpy as np
from PIL import Image

from lib import plan_cells as pc
from lib import plan_ocr
from lib import plan_symbols as psym
from lib import plan_tally as ptal
from lib.plan_sheet import PT_PER_INCH, _pts, load_sheet, plan_unit_tags, register
from lib.plan_space import build_space

log = logging.getLogger(__name__)

PPI = PT_PER_INCH
PROBE_MAX_IN = 24.0         # a wall-mounted unit sits IN the wall; further than
                            # any wall on the legend is thick
SWEEP_DPI = 400
SWEEP_STEP_PT = 140
LABEL_SEARCH_IN = 90.0      # how far a tag may sit from its symbol
SYMBOL_SPAN_IN = 60.0       # how far a symbol's own geometry may spread
LABEL_MERGE_IN = 24.0       # two reads this close are one printed label

def tag_only(text, tags, corr):
    """Does this OCR line hold just a tag (plus its rating)?

    THE SAME TAG TEST AS labels_in (operator ruling 2026-09-21): a letter
    token is part of a tag only if its tag-shaped token snaps EXACTLY, or as a
    near miss corroborated by the line's own (rating) - or, with no rating
    column, as labels_in accepts it. Any other letter token of 2+ letters makes
    the line prose. The prefix-match version dropped 1B's kitchen fan read as
    `EE-2(100)` on M-100.00 while labels_in would have accepted it.
    """
    import re as _re
    t = psym.normalise(text)
    toks = _re.findall(r"[A-Z]{2,}", t)
    if not toks:
        return True
    ok = set()
    for m in psym._TAGLIKE.finditer(t):
        tag, d = psym.snap(m.group(0), tags)
        if not tag:
            continue
        if d == 0 or not corr or psym._printed_rating([text], corr) == tag:
            ok.add(m.group(1))
    # labels_in's THIRD branch: a line that snaps to nothing but prints its
    # own (rating) naming one tag is that tag - `EF=2(100)`, `EF+1(50)` on
    # M-103.00, where `=`/`+` stand for the hyphen. Its letters count as the
    # tag's prefix if within one edit of it.
    if corr:
        rt = psym._printed_rating([text], corr)
        if rt:
            head = rt.upper().replace("-", "").rstrip("0123456789")
            ok |= {tok for tok in toks if psym._edit(tok, head) <= 1}
    return all(tok in ok for tok in toks)

def sweep(page, segs):
    """[(text, x, y)] over the drawing, in display points.

    THE CROP IS THE SHEET'S OWN: everything left of the title block's
    full-height rule (plan_cells.title_block_edge), full height. It was a
    fixed 0.20-0.76 x 0.15-0.65 of the page - the same class as the 0.74
    viewport cut that once hid four PTAC units.
    Clips are in page space and results are used as display space, so a
    rotated page is refused rather than read in the wrong frame.
    """
    import fitz
    if page.rotation:
        raise ValueError(f"sweep: page rotation {page.rotation} - clip and "
                         "display frames differ; not handled")
    W, H = page.rect.width, page.rect.height
    edge = pc.title_block_edge(segs, W, H)
    log.info(f"SWEEP CROP  x 0..{edge:.0f} of {W:.0f}   y 0..{H:.0f}")
    out = []
    for x0 in range(0, int(edge), SWEEP_STEP_PT):
        for y0 in range(0, int(H), SWEEP_STEP_PT):
            clip = fitz.Rect(x0, y0, min(x0 + SWEEP_STEP_PT + 20, edge),
                             min(y0 + SWEEP_STEP_PT + 20, H))
            pix = page.get_pixmap(dpi=SWEEP_DPI, clip=clip, annots=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            sx = clip.width / max(pix.width, 1)
            sy = clip.height / max(pix.height, 1)
            for b in plan_ocr._boxes(buf.getvalue()):
                out.append((b[2], x0 + b[0] * sx, y0 + b[1] * sy))
    return out

class Units:
    """Point-in-polygon against the confirmed apartment fills (polys2).

    A POINT IN A WALL BELONGS TO NO APARTMENT - it is a barrier cell. That
    is where a wall-mounted unit's centroid sits, so such a point is probed
    outward along the four axes (the walls here are axis-aligned). Exactly
    one unit reached -> that unit. Two units (a point inside a demising
    wall) or none -> refused. Never the nearer one.
    """

    def __init__(self, regions, lo, cell_pt, refused=(), status=None,
                 tag_pos=None):
        """`regions`: single-tag units only. `refused`: [(mask, tags_held)]
        for regions holding other than one tag - every point in them is
        refused, never assigned (A-101.00 merged-region fail-safe)."""
        self.lo, self.c = lo, cell_pt
        self.lab = None
        shape = next((r.shape for r in regions.values() if r is not None),
                     next((m.shape for m, _h in refused), None))
        self.lab = np.full(shape, "", dtype=object)
        for m, h in refused:
            self.lab[m] = "!" + ",".join(h)
        for t, r in regions.items():
            if r is not None:
                self.lab[r] = t
        self.st = status or {}
        pts = list((tag_pos or {}).values())
        self.centre = (float(np.mean([p[0] for p in pts])),
                       float(np.mean([p[1] for p in pts]))) if pts else None

    def cell(self, x, y):
        return (int((y - self.lo[1]) / self.c), int((x - self.lo[0]) / self.c))

    def at(self, x, y):
        r, c = self.cell(x, y)
        h, w = self.lab.shape
        return self.lab[r, c] if 0 <= r < h and 0 <= c < w else ""

    def _space(self, r, c):
        """(unit key or None, how) for the free cell (r, c)."""
        u = self.lab[r, c]
        if u.startswith("!"):
            return None, f"refused: region holds tags [{u[1:]}]"
        if u:
            return u, None
        pub = self.st.get("public")
        if pub is not None and pub[r, c]:
            return "non-unit:PUBLIC", None
        cl = self.st.get("closed_lab")
        L = int(cl[r, c]) if cl is not None else 0
        name = self.st.get("names", {}).get(L) if cl is not None else None
        # SAFEGUARD (operator ruling 2026-09-22): a non-unit answer needs a
        # printed name or a doorway. An unnamed, doorless region is a gap in
        # the drawing, not a place an item serves -> refuse.
        if not name and L not in self.st.get("door_rooms", set()):
            return None, "refused: unnamed, doorless non-unit region"
        return f"non-unit:{name or 'unnamed'}", None

    def _outdoors(self, r, c):
        cl = self.st.get("closed_lab")
        return (cl is not None and not self.st["grid"][r, c]
                and not self.lab[r, c]
                and int(cl[r, c]) in self.st.get("outdoors", set()))

    def unit_of_normal(self, x, y):
        """HOST-WALL PROBE (operator ruling 2026-09-21).

        In a unit -> that unit. In free non-unit space -> that space, named.
        In a wall -> probe ONLY along the host wall's normal (the axis the
        barrier is thinnest along), toward the interior (the side facing the
        centroid of the unit tags). THE FIRST REGION REACHED WINS, unit or
        not. The old 4-axis probe skipped the bike room a PTAC faces and
        assigned it to 1A, 19in away across a partition.
        """
        g = self.st["grid"]
        r0, c0 = self.cell(x, y)
        h, w = g.shape
        if not (0 <= r0 < h and 0 <= c0 < w):
            return None, "off the grid"
        lim = int(PROBE_MAX_IN * PPI / self.c) + 1
        start_outdoors = False
        if not g[r0, c0]:
            if not self._outdoors(r0, c0):
                u, why = self._space(r0, c0)
                return u, why or ("inside" if not u.startswith("non-unit:") else "inside non-unit space")
            # OUTDOORS IS NEVER AN ANSWER (operator ruling 2026-09-21): a
            # point there - e.g. in a window opening whose glazing is one
            # unpartnered line - goes to the host-wall probe. The host wall
            # is the one owning the nearest barrier cell.
            start_outdoors = True
            best = None
            for k in range(1, lim + 1):
                for rr, cc in ((r0 + k, c0), (r0 - k, c0), (r0, c0 + k), (r0, c0 - k)):
                    if 0 <= rr < h and 0 <= cc < w and g[rr, cc]:
                        best = (rr, cc); break
                if best:
                    break
            if best is None:
                return None, "refused: outdoors, no wall within reach"
            r0w, c0w = best
        else:
            r0w, c0w = r0, c0
        def run(dr, dc):
            n = 0
            for s_ in (1, -1):
                k = 1
                while k <= 4 * lim:
                    rr, cc = r0w + s_ * dr * k, c0w + s_ * dc * k
                    if not (0 <= rr < h and 0 <= cc < w) or not g[rr, cc]:
                        break
                    k += 1
                n += k - 1
            return n
        along_x, along_y = run(0, 1), run(1, 0)
        # the wall runs along its longer extent; the normal is the other axis
        if along_x >= along_y:
            dr, dc, axis = 1, 0, "y"
        else:
            dr, dc, axis = 0, 1, "x"
        if self.centre is None:
            return None, "no unit tags to orient the probe"
        if axis == "y":
            sgn = 1 if self.centre[1] > y else -1
            dname = "S" if sgn > 0 else "N"
        else:
            sgn = 1 if self.centre[0] > x else -1
            dname = "E" if sgn > 0 else "W"
        for k in range(1, lim + 1):
            rr, cc = r0 + sgn * dr * k, c0 + sgn * dc * k
            if not (0 <= rr < h and 0 <= cc < w):
                break
            if not g[rr, cc]:
                if self._outdoors(rr, cc):
                    if start_outdoors:
                        continue          # still crossing the opening
                    return None, "refused: the wall normal ends outdoors"
                u, why = self._space(rr, cc)
                if why:
                    return None, why
                return u, f"wall-normal {dname} {k * self.c / PPI:.0f}in"
        return None, (f"refused: no region within {PROBE_MAX_IN:.0f}in along "
                      "the wall normal" + (" (started outdoors)" if start_outdoors else ""))


def run_takeoff(arch_page, mech_page, closed_set: Sequence[str],
                corroborations: Optional[Dict[str, str]],
                unit_tags: Sequence[str], widest_door_in: Optional[float],
                force_geometry: bool = False) -> dict:
    """The takeoff for one equipment type on one floor."""
    ok, why = plan_ocr.probe()
    if not ok:
        return {"refused": f"no OCR engine ({why})"}
    tags, corr = list(closed_set), dict(corroborations or {})
    if not tags:
        return {"refused": "the schedule has no identifier column, so there "
                           "is no closed set to snap to"}
    arch, mech = load_sheet(arch_page), load_sheet(mech_page)
    reg_ = register(arch, mech)
    dx, dy = reg_["dx"], reg_["dy"]
    unit_labels = plan_unit_tags(arch["corners"], arch["words"], unit_tags) \
        if reg_["usable"] else {}
    units, space = None, {"incomplete": {}, "refused": [], "ratio": {},
                          "method": None, "fallback_reason": None}
    if reg_["usable"]:
        space = build_space(arch_page, unit_tags, widest_door_in, arch,
                            force_geometry)
        units = Units(space["units"], space["lo"], space["cell_pt"],
                      space["refused"], space, space["tags"])

    reads = sweep(mech_page, mech["segs"])
    kept = [r for r in reads if tag_only(r[0], tags, corr)]
    labels = psym.labels_in(kept, tags, merge_pt=_pts(LABEL_MERGE_IN),
                            corroborations=corr)
    recs = []
    for tag, lx, ly in sorted(labels, key=lambda l: (l[2], l[1])):
        pos, n = psym.symbol_at_label((lx, ly), mech["corners"],
                                      _pts(LABEL_SEARCH_IN), _pts(SYMBOL_SPAN_IN))
        if pos is None:
            recs.append({"tag": None, "unit": None, "status": ptal.UNREAD,
                         "how": f"no geometry ({n} pts)", "label_at": (lx, ly)})
            continue
        back = (pos[0] - dx, pos[1] - dy)
        unit, how = units.unit_of_normal(*back) if units else (None, "refused: "
                                                               "registration not usable")
        recs.append({"tag": tag, "unit": unit, "status": ptal.RESOLVED,
                     "how": how,
                     "glyph_status": ("unplaced" if not unit else
                                      "placed-non-unit" if unit.startswith("non-unit:")
                                      else "placed"),
                     "reason": None if unit else how,
                     "label_at": (lx, ly), "symbol_at": tuple(pos),
                     "at_arch": back})

    t = ptal.tally(recs, sorted(unit_labels) if unit_labels else None)
    why_ = []
    if space["incomplete"]:
        why_.append("sheet incomplete: " + "; ".join(
            f"{k} {v}" for k, v in sorted(space["incomplete"].items())))
    ref = [r for r in recs if r.get("glyph_status") == "unplaced"
           and (r.get("reason") or "").startswith("refused: ")]
    if ref:
        why_.append(f"{len(ref)} item(s) refused")
    pu = None if why_ else ptal.per_unit(t)
    unavailable = "; ".join(why_) if why_ else (
        None if pu is not None else "tally withheld the split (unplaced items)")
    return {"records": recs, "total": t.total, "by_tag": t.by_tag,
            "per_unit": pu, "unavailable": unavailable,
            "incomplete": dict(space["incomplete"]),
            "ratio": dict(space["ratio"]), "statement": ptal.statement(t, "unit"),
            "method": space.get("method"),
            "fallback_reason": space.get("fallback_reason"),
            "registration": reg_,
            "labels_by_tag": dict(Counter(t_ for t_, _x, _y in labels))}
