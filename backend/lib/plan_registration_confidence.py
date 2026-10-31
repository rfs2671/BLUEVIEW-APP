"""Registration CONFIDENCE for plan_sheet.register_offset: REPORTING ONLY.

register_offset returns usable=True on three rules (R1 the offset is the exact
census' best peak, R2 the best peak beats the second, R3 >= MIN_ANCHORS) and
compares no ratio. A wrong peak therefore reads "usable": the gas roof
(AR 6.9.26 A-105 vs AR 3.28.25 A-105.00) registered at 31 of 687 anchors with
a best/second margin of 1.10. This module adds two measured floors and nothing
else:

  anchor_fraction = best_peak_anchors / min(corners_arch, corners_other)
      (the smaller sheet is the most that could possibly match; a sheet pair
      that registers correctly puts a large share of the smaller sheet's
      corners on the other sheet's)
  margin          = best_peak_anchors / second_peak_anchors (register_offset's
      own `margin`)

NOT WIRED. Nothing in the pipeline calls this: confidence() is a pure function
of a register_offset result and the two corner counts. A caller that wants the
flag asks for it and records it beside the registration; usable is unchanged
and no row, placement or answer moves. Thresholds are the calibrated
RECOMMENDED / PERMISSIVE pairs from regthresh/REPORT.md, not live gates.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

#: RECOMMENDED (conservative): both floors must hold. Calibrated on 83
#: recorded registrations (regthresh/REPORT.md): every known-wrong peak has
#: margin <= 1.158 and, but for one, fraction <= 0.049; every verified level
#: has margin >= 1.618 and fraction >= 0.120.
MIN_ANCHOR_FRACTION = 0.10
MIN_MARGIN = 1.30
#: PERMISSIVE alternative: the same two floors set just above the worst known
#: wrong peak. Keeps the owner's roof structure registration (0.0895 / 1.514).
PERMISSIVE_MIN_ANCHOR_FRACTION = 0.06
PERMISSIVE_MIN_MARGIN = 1.25


def anchor_fraction(best_peak_anchors: Optional[int], corners_a: int,
                    corners_b: int) -> Optional[float]:
    """best peak anchors over the SMALLER sheet's corner count; None when
    either input is missing or a sheet has no corners."""
    if best_peak_anchors is None:
        return None
    denom = min(int(corners_a or 0), int(corners_b or 0))
    if denom <= 0:
        return None
    return round(float(best_peak_anchors) / denom, 4)


def confidence(reg: Dict[str, Any], corners_a: int, corners_b: int, *,
               min_fraction: float = MIN_ANCHOR_FRACTION,
               min_margin: float = MIN_MARGIN) -> Dict[str, Any]:
    """Would the two floors refuse `reg` (a register_offset result)?

    Returns {"fraction", "margin", "fraction_ok", "margin_ok", "confident",
    "would_refuse", "reasons"}. A registration register_offset already
    refused is would_refuse=True with no reason of its own (it stays refused
    for the reason it carries). An unmeasurable fraction or margin (no
    second peak is margin None) fails OPEN for that floor only when the other
    measurement exists: a missing input is reported, never silently passed -
    `reasons` says "unmeasured". Never mutates `reg`."""
    frac = anchor_fraction(reg.get("best_peak_anchors"), corners_a, corners_b)
    margin = reg.get("margin")
    second = reg.get("second_peak_anchors")
    if margin is None and second == 0 and reg.get("best_peak_anchors"):
        margin = float("inf")           # no second peak at all: infinitely clear
    reasons = []
    frac_ok = frac is not None and frac >= min_fraction
    marg_ok = margin is not None and margin >= min_margin
    if frac is None:
        reasons.append("anchor fraction unmeasured (no corner counts)")
    elif not frac_ok:
        reasons.append(f"anchor fraction {frac:.3f} under {min_fraction:.3f}: "
                       f"{reg.get('best_peak_anchors')} best-peak anchors of "
                       f"{min(corners_a, corners_b)} corners on the smaller sheet")
    if margin is None:
        reasons.append("margin unmeasured")
    elif not marg_ok:
        reasons.append(f"margin {margin:.2f} under {min_margin:.2f} over the second peak")
    already = not reg.get("usable")
    confident = bool(frac_ok and marg_ok)
    return {"fraction": frac, "margin": margin, "fraction_ok": frac_ok,
            "margin_ok": marg_ok, "confident": confident,
            "would_refuse": bool(already or not confident),
            "already_refused": already, "reasons": reasons}


__all__ = ["anchor_fraction", "confidence", "MIN_ANCHOR_FRACTION", "MIN_MARGIN",
           "PERMISSIVE_MIN_ANCHOR_FRACTION", "PERMISSIVE_MIN_MARGIN"]
