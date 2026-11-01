"""The roof frame: a scale RECORDED per viewport, and the COMPOSED path
P -> 3.28.25 roof -> gas roof (Roy, 11-01 rulings 140 + 3).

-- WHAT WAS WRONG ---------------------------------------------------------

The gas-change roof (AR 6.9.26 p2, A-105.01) is drawn at 5/16 in = 1 ft and
prints no scale note, so plan_scale reads its drawing as an untitled,
unscaled viewport. register_offset is a TRANSLATION search (the underlay is
the same drawing placed twice); between a 1/4 in sheet and a 5/16 in sheet it
finds the wrong peak (33 of 687 anchors, margin 1.10: the roof140 frame
test). Divide the gas corners by the measured scale ratio first and the same
rule finds 365 anchors, margin 3.23, fraction 0.531 (roof140/REPORT.md).

-- WHAT THIS MODULE HOLDS -------------------------------------------------

1. SCALE_SPANS / scale_check(): seven independent vector spans measured on
   both roofs (wall rectangles, the 100'-0" lot dimension, the 33'-0" and
   28'-10" dimension lines). Their ratio IS the gas roof's scale against the
   3.28.25 roof's 1/4 in. The scale is DERIVED from the drawings, never
   accepted because a registration passed: the conservative pair does not
   discriminate a wrong scale near the right one (1.24 and 1.26 both pass).
2. RECORDS: one ViewportScale per viewport of the three roof pages, each with
   its evidence. "verified" = measured on the drawing; "noted" = a printed
   note with no measured dimension behind it (the 3/32 in bulkhead plan).
   A noted record is NEVER a verified scale and is applied to nothing.
3. compose_route(): P -> reference roof (register_offset, whole sheets) and
   gas roof -> reference roof (register_offset, gas corners / ratio, against
   the roof plan's own region), each link behind the CONSERVATIVE PAIR
   (plan_registration_confidence: anchor fraction >= 0.10, margin >= 1.30).
   The composed registration carries, in `max_in`, the SUM of every link's
   worst-case residual (max, not rms) PLUS the origin ambiguity.
4. roof_position(): a point on a roof page in feet in the shared A-plan frame
   the floors use (X0/Y0 = the first-floor structural envelope), with the same
   worst-case figure.

Nothing here runs unless a caller hands it a roof page: run_stacks takes it as
an optional argument (`via_pages`); with none, every row is what it was.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from lib import plan_registration_confidence as conf

# -- the three roof pages: file hash + page, stable across deploys ----------
REF_FILE, REF_PAGE = "AR - 3.28.25.pdf", 16            # A-105.00, 1/4 in
REF_HASH = "9ed2b2e0d309f18a02fba07c292b62d2"
GAS_FILE, GAS_PAGE = "AR - 6.9.26 (Gas change).pdf", 2  # A-105.01, 5/16 in
GAS_HASH = "474569d58557df9e704cff2b839fdf0a"
OWNER_FILE, OWNER_PAGE = "Owners set - 6.9.26.pdf", 6  # A-105.00 post-CO, 1/4 in
OWNER_HASH = "7031fe0ab675f401310ddc3cb6c2ed44"

REF_PT_PER_FT = 18.0                                    # 1/4 in = 1 ft: 72/4

# -- (1) the scale of the gas roof, from seven spans ------------------------
#: (what was measured, 3.28.25 roof points, gas roof points). The same
#: building shell and the same printed dimensions drawn on both pages, so the
#: ratio of a span is the ratio of the two scales. roof140/scale_evidence.py.
SCALE_SPANS: Tuple[Tuple[str, float, float], ...] = (
    ("inner wall rectangle width (A-Wall)", 1230.0, 1540.1),
    ("inner wall rectangle height (A-Wall)", 609.0, 762.5),
    ("outer wall rectangle width (A-Wall)", 1260.0, 1577.7),
    ("outer wall rectangle height (A-Wall)", 642.0, 803.7),
    ("100'-0\" LOT dimension line (A-DIM)", 1809.0, 2265.2),
    ("33'-0\" dimension line (A-DIM)", 603.0, 755.1),
    ("28'-10\" dimension line (A-DIM)", 528.0, 661.2),
)
#: every span must sit within this of the mean ratio. The registration's own
#: plateau (363-365 anchors for 1.2515-1.2531) is +/-0.06%; 0.1% is the
#: stated uncertainty (about 1.5 pt over a 1500 pt span = the match radius).
SPAN_TOL = 0.001
MIN_SPANS = 3
MIN_DISTINCT_SPANS = 2        # plan_scale.MIN_DISTINCT: copies are not evidence
SCALE_UNCERTAINTY = 0.001


def measured_ratio() -> float:
    """gas pt per ref pt: the mean of the span ratios."""
    r = [g / a for _n, a, g in SCALE_SPANS]
    return sum(r) / len(r)


def scale_check() -> Dict[str, Any]:
    """The evidence for the gas roof's scale, tested: >= MIN_SPANS spans, at
    least MIN_DISTINCT_SPANS different lengths, every one within SPAN_TOL of
    the mean. `ok` False means the record is not applied."""
    ratios = [g / a for _n, a, g in SCALE_SPANS]
    mean = sum(ratios) / len(ratios)
    spread = max(abs(r / mean - 1) for r in ratios)
    distinct = len({round(a) for _n, a, _g in SCALE_SPANS})
    ok = len(ratios) >= MIN_SPANS and distinct >= MIN_DISTINCT_SPANS and spread <= SPAN_TOL
    return {"ok": ok, "ratio": mean, "spread": spread, "spans": len(ratios),
            "distinct": distinct, "pt_per_ft": REF_PT_PER_FT * mean,
            "uncertainty": SCALE_UNCERTAINTY,
            "min_ratio": min(ratios), "max_ratio": max(ratios)}


# -- (2) one record per viewport --------------------------------------------
@dataclass(frozen=True)
class ViewportScale:
    file_hash: str
    file_name: str
    page_number: int
    sheet: str
    title: str                      # the viewport's printed title ("" = untitled)
    note: str                       # the scale as printed or derived
    pt_per_ft: float
    status: str                     # "verified" | "noted"
    agreeing: int                   # measured spans/dimensions that agree
    basis: str
    anchor_box_pt: Optional[Tuple[float, float, float, float]] = None

    @property
    def pt_per_in(self) -> float:
        return self.pt_per_ft / 12.0

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    def brief(self) -> Dict[str, Any]:
        return {"file_hash": self.file_hash, "file": self.file_name, "page": self.page_number,
                "sheet": self.sheet, "title": self.title, "note": self.note,
                "pt_per_ft": round(self.pt_per_ft, 3), "status": self.status,
                "verified": self.verified, "agreeing": self.agreeing, "basis": self.basis}


def _records() -> Tuple[ViewportScale, ...]:
    chk = scale_check()
    gas_status = "verified" if chk["ok"] else "noted"
    return (
        ViewportScale(REF_HASH, REF_FILE, REF_PAGE, "A-105.00", "ROOF PLAN", '1/4" = 1\'-0"',
                      REF_PT_PER_FT, "verified", 27,
                      "plan_scale: 27 of 33 measured dimensions agree with the printed 1/4 in note; "
                      "outer wall rectangle 70.0 x 35.67 ft",
                      (748.0, 470.3, 2008.0, 1112.3)),
        ViewportScale(REF_HASH, REF_FILE, REF_PAGE, "A-105.00", "BULKHEAD PLAN", '3/32" = 1\'-0"',
                      72.0 * 3 / 32, "noted", 0,
                      "printed note only: 0 dimensions measured in the viewport; the gas roof "
                      "registers to it at 11 of 19 corners (thin), so it is NOT verified and lends nothing"),
        ViewportScale(OWNER_HASH, OWNER_FILE, OWNER_PAGE, "A-105.00", "ROOF PLAN", '1/4" = 1\'-0"',
                      REF_PT_PER_FT, "verified", 34,
                      "plan_scale: 34 of 40 measured dimensions agree with the printed 1/4 in note; "
                      "registers to the 3.28.25 roof at offset (0, 0), 907 of 943 corners",
                      (748.0, 470.3, 2008.0, 1112.3)),
        ViewportScale(OWNER_HASH, OWNER_FILE, OWNER_PAGE, "A-105.00", "BULKHEAD PLAN", '3/32" = 1\'-0"',
                      72.0 * 3 / 32, "noted", 0,
                      "printed note only: 0 dimensions measured in the viewport"),
        ViewportScale(GAS_HASH, GAS_FILE, GAS_PAGE, "A-105.01", "", '5/16" = 1\'-0" (derived)',
                      chk["pt_per_ft"], gas_status, chk["spans"],
                      f"no scale note on the page. {chk['spans']} spans against the 3.28.25 roof "
                      f"give ratio {chk['ratio']:.4f} (every span within {chk['spread']:.2%}), "
                      f"{chk['pt_per_ft']:.2f} pt/ft vs 22.50 nominal, uncertainty "
                      f"+/-{SCALE_UNCERTAINTY:.1%}; registration plateau 1.2515-1.2531",
                      (845.3, 469.7, 2423.0, 1273.4)),
    )


RECORDS: Tuple[ViewportScale, ...] = _records()


def records_for(file_hash: Optional[str], page_number: Optional[int]) -> List[ViewportScale]:
    return [r for r in RECORDS if r.file_hash == file_hash and r.page_number == page_number]


def _in_box(x, y, b, pad=0.0) -> bool:
    return b[0] - pad <= x <= b[2] + pad and b[1] - pad <= y <= b[3] + pad


def scale_record(file_hash: Optional[str], page_number: Optional[int],
                 x: Optional[float] = None, y: Optional[float] = None) -> Optional[ViewportScale]:
    """The VERIFIED record for a point on a roof page (a noted record never
    answers). With no point, the page's only verified record, else None."""
    cands = [r for r in records_for(file_hash, page_number) if r.verified]
    if x is not None and y is not None:
        cands = [r for r in cands if r.anchor_box_pt is None or _in_box(x, y, r.anchor_box_pt, 40.0)]
    return cands[0] if len(cands) == 1 else None


def apply_records(sheet, file_hash: Optional[str], page_number: Optional[int]):
    """plan_scale.Sheet with this page's VERIFIED records applied to the
    viewports that have no verified scale of their own: verified=True,
    pt_per_in, agreeing = the record's measured count, `recorded` = the
    evidence. A viewport already verified on its own dimensions is left alone.
    A noted record is applied to nothing. Returns a new Sheet."""
    from dataclasses import replace
    out = []
    for v in sheet.viewports:
        got = None
        if not v.verified:
            for r in records_for(file_hash, page_number):
                if not r.verified:
                    continue
                if r.title and v.title.strip().upper() == r.title.upper():
                    got = r
                elif (not r.title and not v.title and r.anchor_box_pt
                      and v.drawing_bbox[0] <= r.anchor_box_pt[0]
                      and v.drawing_bbox[1] <= r.anchor_box_pt[1]
                      and v.drawing_bbox[2] >= r.anchor_box_pt[2]
                      and v.drawing_bbox[3] >= r.anchor_box_pt[3]):
                    got = r
        out.append(v if got is None else replace(
            v, verified=True, pt_per_in=got.pt_per_in, agreeing=got.agreeing, refusal="",
            recorded=got.brief()))
    return replace(sheet, viewports=out)


# -- (3) the frame, and the origin ambiguity --------------------------------
#: the shared A-plan frame the floors use: X0 = west edge, Y0 = south edge of
#: the first-floor structural envelope (A-plan page points, y down).
ENVELOPE_PT = (751.08, 472.2, 2005.08, 1109.7)          # 69.67 x 35.42 ft
#: the roof's outer wall rectangle on the 3.28.25 roof (and the owner's)
OUTER_WALL_PT = (748.0, 470.3, 2008.0, 1112.3)          # 70.00 x 35.67 ft


def origin_ambiguity_ft() -> float:
    """How far the roof's frame could sit from the floors': the largest inset
    of the structural envelope inside the roof's outer wall rectangle (the
    drawings do not say which edge of the parapet wall the envelope meets).
    0.17 ft: ruling 3 of 2026-11-01."""
    e, o = ENVELOPE_PT, OUTER_WALL_PT
    return max(e[0] - o[0], e[1] - o[1], o[2] - e[2], o[3] - e[3]) / REF_PT_PER_FT


ORIGIN_AMBIGUITY_FT = 0.17
ORIGIN_AMBIGUITY_IN = ORIGIN_AMBIGUITY_FT * 12.0


def ref_pt_to_ft(x: float, y: float) -> Tuple[float, float]:
    """A point on the 3.28.25 roof (or the owner's: the same frame) in feet,
    east and north of the envelope's south-west corner, as the floors are."""
    return ((x - ENVELOPE_PT[0]) / REF_PT_PER_FT, (ENVELOPE_PT[3] - y) / REF_PT_PER_FT)


def worst_case_in(link_max_in: Sequence[float]) -> Dict[str, Any]:
    """The summed worst case: every link's MAX residual added (not rms), then
    the origin ambiguity."""
    s = float(sum(link_max_in))
    return {"links_in": [round(float(v), 3) for v in link_max_in], "sum_links_in": round(s, 3),
            "origin_ambiguity_in": round(ORIGIN_AMBIGUITY_IN, 3),
            "total_in": round(s + ORIGIN_AMBIGUITY_IN, 3)}


# -- registration links ------------------------------------------------------
def roof_plan_corners(corners) -> np.ndarray:
    """The roof plan's own corners on the 3.28.25 sheet: the page also holds
    the bulkhead plan (top left), a border and a title block
    (roof140/REPORT.md section a): 943 of the page's 968 corners."""
    C = np.asarray(corners, dtype=float).reshape(-1, 2)
    ok = (C[:, 0] >= 30) & (C[:, 1] >= 30) & (C[:, 1] <= 1700) & (C[:, 0] <= 2279)
    bulk = (C[:, 0] < 800) & (C[:, 1] < 405)
    return C[ok & ~bulk]


def link_view(name: str, r: Dict[str, Any], n_a: int, n_b: int) -> Dict[str, Any]:
    """One registration link as a row shows it: the numbers, and the
    conservative pair's verdict (plan_registration_confidence)."""
    c = conf.confidence(r, n_a, n_b)

    def r3(v):
        return None if v is None else round(float(v), 3)
    return {"name": name, "dx": r3(r.get("dx")), "dy": r3(r.get("dy")), "anchors": r.get("anchors"),
            "best_peak_anchors": r.get("best_peak_anchors"),
            "second_peak_anchors": r.get("second_peak_anchors"), "margin": r.get("margin"),
            "fraction": c["fraction"], "corners": [n_a, n_b], "rms_in": r3(r.get("rms_in")),
            "max_in": r3(r.get("max_in")), "usable": bool(r.get("usable")),
            "confident": c["confident"], "accepted": bool(r.get("usable")) and c["confident"],
            "refused": r.get("refused"), "reasons": c["reasons"]}


def gas_to_ref(gas_sheet: dict, ref_sheet: dict, *, ratio: Optional[float] = None,
               register: Optional[Callable] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(register_offset result, link view): the gas roof's corners divided by
    the measured scale ratio, against the 3.28.25 roof plan's own corners.
    other = arch + d, with `other` already at the reference scale."""
    from lib.plan_sheet import register_offset
    register = register or register_offset
    ratio = measured_ratio() if ratio is None else ratio
    A = roof_plan_corners(ref_sheet["corners"])
    B = np.asarray(gas_sheet["corners"], dtype=float).reshape(-1, 2) / ratio
    r = register({"corners": A}, {"corners": B})
    return r, link_view("gas roof (scaled 1/%.4f) -> 3.28.25 roof" % ratio, r, len(A), len(B))


def p_to_ref(p_sheet: dict, ref_sheet: dict, *, register: Optional[Callable] = None,
             name: str = "P sheet") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from lib.plan_sheet import register_offset
    register = register or register_offset
    r = register(ref_sheet, p_sheet)
    n_a = len(np.asarray(ref_sheet["corners"]).reshape(-1, 2))
    n_b = len(np.asarray(p_sheet["corners"]).reshape(-1, 2))
    return r, link_view(f"{name} -> 3.28.25 roof", r, n_a, n_b)


def compose(p_link: Tuple[dict, dict], g_link: Tuple[dict, dict], ratio: float,
            *, scale_ok: bool = True) -> Dict[str, Any]:
    """The composed registration P -> gas roof, shaped like register_offset's
    result so plan_stacks reads it: gas_pt = scale * (P_pt - (dx, dy)).

        P = ref + dp          (P -> reference roof)
        gas/ratio = ref + dg  (gas roof -> reference roof)
        gas = ratio * (P - dp + dg)       so  dx = dp - dg, scale = ratio

    usable only when BOTH links hold the conservative pair and the scale
    evidence holds. max_in is the SUM of the links' worst-case residuals plus
    the origin ambiguity (ruling 3)."""
    (pr, pv), (gr, gv) = p_link, g_link
    why = []
    for v in (pv, gv):
        if not v["accepted"]:
            why.append(f"{v['name']}: " + ("; ".join(v["reasons"]) or v.get("refused") or "refused"))
    if not scale_ok:
        why.append("the gas roof's scale evidence does not hold (scale_check)")
    wc = worst_case_in([pv["max_in"] or 0.0, gv["max_in"] or 0.0])
    worst = min((pv, gv), key=lambda v: v["margin"] if v["margin"] is not None else math.inf)
    have = pr.get("dx") is not None and gr.get("dx") is not None
    return {"dx": float(pr["dx"] - gr["dx"]) if have else None,
            "dy": float(pr["dy"] - gr["dy"]) if have else None,
            "scale": float(ratio),
            "anchors": min(pv["anchors"] or 0, gv["anchors"] or 0),
            # best and second peak of the WEAKEST link (the lowest margin), so
            # the three numbers on the row describe one peak pair
            "best_peak_anchors": worst["best_peak_anchors"],
            "second_peak_anchors": worst["second_peak_anchors"], "margin": worst["margin"],
            "offset_from_best_pt": max(pr.get("offset_from_best_pt") or 0.0,
                                       gr.get("offset_from_best_pt") or 0.0),
            "rms_in": max(pv["rms_in"] or 0.0, gv["rms_in"] or 0.0),
            "max_in": wc["total_in"], "usable": not why and have, "refused": "; ".join(why) or None,
            "composed": {"route": "P -> 3.28.25 roof (A-105.00 p16) -> gas roof (A-105.01 p2)",
                         "ratio": round(float(ratio), 5), "links": [pv, gv],
                         "worst_case": wc, "scale_ok": bool(scale_ok)}}


def compose_route(gas_sheet: dict, p_sheet: dict, ref_sheet: dict, *, p_name: str = "P sheet",
                  cache: Optional[dict] = None, register: Optional[Callable] = None
                  ) -> Dict[str, Any]:
    """P -> 3.28.25 roof -> gas roof, live: both links measured now, both
    behind the conservative pair, the scale from scale_check(). `cache`
    shares the gas link between P sheets."""
    chk = scale_check()
    if cache is not None and "gas" in cache:
        g = cache["gas"]
    else:
        g = gas_to_ref(gas_sheet, ref_sheet, ratio=chk["ratio"], register=register)
        if cache is not None:
            cache["gas"] = g
    p = p_to_ref(p_sheet, ref_sheet, register=register, name=p_name)
    return compose(p, g, chk["ratio"], scale_ok=chk["ok"])


def roof_position(x: float, y: float, frame: str, *, gas_link: Optional[dict] = None,
                  p_link: Optional[dict] = None, ratio: Optional[float] = None) -> Dict[str, Any]:
    """A point in feet in the shared A-plan frame, with its worst case.

    frame "ref" = a point on the 3.28.25 roof or the owner's roof (the same
    frame, offset (0, 0)); "gas" = a point on the gas roof page, brought into
    the reference frame by `gas_link` (a link_view: dx, dy, max_in) and the
    scale ratio; "p" = a point on a P sheet, brought there by `p_link`.
    The worst case adds the max residual of every link used."""
    links = []
    px, py = x, y
    if frame == "p":
        px, py = x - p_link["dx"], y - p_link["dy"]
        links.append(p_link["max_in"])
    elif frame == "gas":
        ratio = measured_ratio() if ratio is None else ratio
        px, py = x / ratio - gas_link["dx"], y / ratio - gas_link["dy"]
        links.append(gas_link["max_in"])
    elif frame != "ref":
        raise ValueError(f"unknown frame {frame!r}")
    fx, fy = ref_pt_to_ft(px, py)
    wc = worst_case_in(links)
    return {"x_ft": round(fx, 3), "y_ft": round(fy, 3), "ref_pt": [round(px, 2), round(py, 2)],
            "worst_case_in": wc["total_in"], "worst_case": wc}


def composable(sheet_number: Optional[str]) -> bool:
    """Only a PLUMBING plan (P-) is composed through the 3.28.25 roof in this
    change. The sprinkler roof rows stay out (SP-004's scale is provisional:
    ruling 3), structure stays behind its own gate (S-106 is 48 of 592, under
    the fraction floor) and the mechanical glyph stage registers by its own
    rule (the shared register_offset there is PR 925)."""
    return str(sheet_number or "").strip().upper().startswith("P-")


def route_for(a_page: Optional[dict]) -> Optional[str]:
    """"gas_roof" when this architectural page is the gas roof (hash + page)."""
    if a_page and a_page.get("file_hash") == GAS_HASH \
            and int(a_page.get("page_number") or 0) == GAS_PAGE:
        return "gas_roof"
    return None


def via_page(pages: Sequence[dict]) -> Optional[dict]:
    """The reference roof page (3.28.25 A-105.00) among `pages`, if present."""
    for p in pages or ():
        if p.get("file_hash") == REF_HASH and int(p.get("page_number") or 0) == REF_PAGE:
            return p
    return None


__all__ = ["RECORDS", "SCALE_SPANS", "ViewportScale", "scale_check", "measured_ratio",
           "scale_record", "records_for", "apply_records", "origin_ambiguity_ft",
           "ORIGIN_AMBIGUITY_FT", "ORIGIN_AMBIGUITY_IN", "worst_case_in", "ref_pt_to_ft",
           "roof_plan_corners", "link_view", "gas_to_ref", "p_to_ref", "compose",
           "compose_route", "roof_position", "route_for", "composable", "via_page", "REF_HASH", "REF_PAGE",
           "GAS_HASH", "GAS_PAGE", "OWNER_HASH", "OWNER_PAGE"]
