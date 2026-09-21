"""Tolerances for putting two sheets in one coordinate frame.

WRITTEN BEFORE ANY RESIDUAL WAS COMPUTED, and that ordering is the point. A
tolerance chosen after seeing the error is not a tolerance, it is a
description of the error — the same failure as a threshold tuned until the
eval cases pass. Nothing in this file was derived from a measurement of this
corpus. Every number below comes from the geometry of the drawings or from
what the answer would be used for.

── WHY REGISTRATION IS PLAUSIBLE HERE AT ALL ──────────────────────────────

Read by eye on four sheets of the fourth floor: the discipline sheets carry
the architectural plan as a SCREENED UNDERLAY, and on the stair core the
linework is identical — same runs, same DN 16 / UP 16 markers in the same
four positions, same break symbols, same wall jogs, same door arcs. Not a
redraw that agrees in intent. The same geometry.

So the expected transform between two sheets of one set is TRANSLATION AND
UNIFORM SCALE ONLY. A fit that wants rotation or shear is reporting
something other than the offset between two placements of the same drawing,
and that is a finding rather than a better fit. See `FLAG_ROTATION_DEG`.

── THE CONVERSION EVERY TOLERANCE IS REALLY STATED IN ─────────────────────

A tolerance in pixels is a tolerance in inches whether or not anyone says
so. At 1/4" = 1'-0" rendered at 250 DPI one pixel is 0.192 real inches, so
a "5 pixel" rule is a one-inch rule and a "one pixel" rule is 3/16".

    real inches per pixel = 12 * S / dpi        for a scale of 1/S" = 1'-0"

Numbers below are in REAL INCHES and are converted at the point of use.
"""
from __future__ import annotations

from typing import Optional

# ── scale ──────────────────────────────────────────────────────────────────

PLAN_SCALE_DENOM = 4          # the sheets read so far are all 1/4" = 1'-0"
PLAN_RENDER_DPI = 250         # server._PLAN_RENDER_DPI for a non-detail sheet


def real_inches_per_pixel(dpi: int = PLAN_RENDER_DPI,
                          scale_denom: int = PLAN_SCALE_DENOM) -> float:
    """Real-world inches spanned by one rendered pixel.

    1/S" = 1'-0" means one paper inch is 12*S real inches; a pixel is 1/dpi
    of a paper inch. At the defaults: 0.192 in/px, 5.2 px/in, 62.5 px/ft.
    """
    return (12.0 * scale_denom) / float(dpi)


def inches_to_pixels(inches: float, dpi: int = PLAN_RENDER_DPI,
                     scale_denom: int = PLAN_SCALE_DENOM) -> float:
    return inches / real_inches_per_pixel(dpi, scale_denom)


# ── what an answer is allowed to be used for ───────────────────────────────
#
# THE TOLERANCE BELONGS TO THE QUESTION, NOT TO THE FIT. One registration can
# be good enough to say which room a diffuser is in and nowhere near good
# enough to say whether a duct clears a beam. These three are ordered and the
# ordering is asserted by a test, because the failure mode is a single
# "accuracy" number quoted for every use.

#: WHICH ROOM IS THIS IN — moderate, and only away from boundaries.
#: Interior partitions here are about 4.5-5" (2x4 plus board both faces), and
#: rooms are 8-12 ft across. Six inches is roughly one partition thickness:
#: beyond that a point could sit on the wrong side of a wall. Paired with
#: ROOM_EDGE_EXCLUSION so the claim is never made where it is fragile.
TOL_ROOM_MEMBERSHIP_IN = 6.0

#: A membership claim is REFUSED for any point closer than this to a room
#: boundary. Without it the tolerance above is meaningless: the answer is
#: only robust in the interior, and near a wall the honest output is "too
#: close to call", not a coin flip.
ROOM_EDGE_EXCLUSION_IN = 12.0

#: WHICH SIDE OF THE WALL / DOES THIS PENETRATE IT — tight. Must be well
#: under one partition thickness or the answer inverts. Two inches is under
#: half of 4.5", which keeps a correct answer correct rather than merely
#: likely.
TOL_WALL_SIDE_IN = 2.0

#: CLEARANCE AND CLASH — very tight, and REFUSE is the expected outcome.
#: Code clearances are written in inches (36" egress, fixture clearances,
#: pipe-to-beam), so a half-inch error can flip a compliance answer. This
#: system does not compute clashes today; the number exists so that when
#: someone asks, the answer is measured against it and usually refused.
TOL_CLEARANCE_IN = 0.5

#: Below this, a clash or clearance question is answered "cannot say from the
#: drawings" rather than answered. Refusing is the correct output for a
#: question whose tolerance the registration cannot meet.
CLEARANCE_REFUSE_DEFAULT = True


# ── what counts as a matched anchor ────────────────────────────────────────

#: A candidate correspondence is a MATCH when the post-transform distance
#: between the two points is within this. One inch is about five pixels at
#: the default render — generous against rasterisation and line width, and
#: far tighter than any of the use tolerances above, so a match that only
#: just qualifies still cannot carry a wall-side answer on its own.
ANCHOR_MATCH_RADIUS_IN = 1.0

#: An anchor is a point both drawings place deliberately: a wall corner, a
#: stair nosing end, a shaft corner, a door jamb. NOT a point on a long line,
#: where position along the line is unconstrained and a "match" is an
#: artifact of where the scan happened to sample.
ANCHOR_MUST_BE_CORNER_LIKE = True


# ── registered, or coincidentally close ────────────────────────────────────
#
# RMS ALONE CANNOT TELL THESE APART. Three anchors clustered in one corner
# will fit almost anything with a small residual, and the fit will be wrong
# everywhere else on the sheet. Count and SPREAD are what separate a
# registration from a coincidence, so all four conditions must hold.

#: Enough correspondences that a few bad ones cannot carry the fit.
MIN_ANCHORS = 8

#: The matched anchors must span at least this fraction of the plan's
#: bounding box in BOTH axes. This is the condition that rules out a fit
#: pinned by one corner of the building.
MIN_ANCHOR_SPREAD_FRAC = 0.5

#: Root-mean-square residual over matched anchors.
MAX_RMS_IN = 1.0

#: No single matched anchor may exceed this. An RMS that passes while one
#: anchor is far out means the fit is being averaged into looking correct.
MAX_SINGLE_RESIDUAL_IN = 2.0

#: EXPECTED TRANSFORM IS TRANSLATION + UNIFORM SCALE. A fitted rotation
#: larger than this is a finding, not a fit: over a 70 ft building 0.05 deg
#: is already 0.73 in at the far end, which exceeds TOL_WALL_SIDE_IN.
FLAG_ROTATION_DEG = 0.05

#: Uniform scale means the two axis scales agree to this. Anything worse is
#: non-uniform scaling, which the underlay hypothesis does not allow.
FLAG_SCALE_ANISOTROPY = 0.002


def registration_verdict(n_anchors: int, spread_frac_x: float,
                         spread_frac_y: float, rms_in: float,
                         max_residual_in: float,
                         rotation_deg: float = 0.0,
                         scale_anisotropy: float = 0.0) -> tuple:
    """(verdict, reasons) — 'registered' | 'coincidental' | 'failed'.

    Deliberately returns REASONS rather than a score. A single number invites
    "close enough", and the whole point of the four conditions is that they
    fail for different causes that need different responses.
    """
    reasons = []
    if n_anchors < MIN_ANCHORS:
        reasons.append(f"only {n_anchors} anchors, need {MIN_ANCHORS}")
    if min(spread_frac_x, spread_frac_y) < MIN_ANCHOR_SPREAD_FRAC:
        reasons.append(
            f"anchors span {spread_frac_x:.2f}x{spread_frac_y:.2f} of the "
            f"plan, need {MIN_ANCHOR_SPREAD_FRAC} in both axes")
    if rms_in > MAX_RMS_IN:
        reasons.append(f"RMS {rms_in:.2f}in over {MAX_RMS_IN}in")
    if max_residual_in > MAX_SINGLE_RESIDUAL_IN:
        reasons.append(
            f"worst anchor {max_residual_in:.2f}in over "
            f"{MAX_SINGLE_RESIDUAL_IN}in")
    if abs(rotation_deg) > FLAG_ROTATION_DEG:
        reasons.append(
            f"fitted rotation {rotation_deg:.3f} deg — the underlay should "
            f"need none; investigate before trusting the fit")
    if abs(scale_anisotropy) > FLAG_SCALE_ANISOTROPY:
        reasons.append(
            f"non-uniform scale {scale_anisotropy:.4f} — not consistent with "
            f"the same drawing placed twice")
    if not reasons:
        return "registered", []
    # Residuals fine but the evidence is thin: that is the coincidence case,
    # and it is reported differently because the remedy is more anchors
    # rather than a better fit.
    thin = all("anchors" in r or "span" in r for r in reasons)
    return ("coincidental" if thin else "failed"), reasons


#: Questions answered AT ONE LOCATION. For these the relevant statistic is
#: the WORST residual, not the average.
#:
#: CORRECTION, 2026-09-21, after the first registration run. This function
#: originally compared RMS for every question, which is a proxy substitution
#: of exactly the kind this codebase keeps finding: an aggregate over 562
#: anchors says nothing about the one anchor nearest the thing being asked
#: about. Measured on A-103.00 -> P-103.00: RMS 0.068in, max 0.812in. By RMS
#: that pair clears the 0.5in clearance tolerance; by worst case it does not,
#: and a clash sits at ONE PLACE on the drawing.
#:
#: This is a correction, not a loosening - it makes the test stricter for
#: four of the five question kinds.
POINTWISE_QUESTIONS = frozenset({
    "wall_side", "penetration", "clearance", "clash"})


def usable_for(question_kind: str, rms_in: float,
               max_residual_in: Optional[float] = None) -> bool:
    """Is a registration with these residuals good enough for this question?

    The tolerance belongs to the question, and so does the STATISTIC:

      room_membership   RMS      a bulk property, and already refused within
                                 ROOM_EDGE_EXCLUSION_IN of a boundary, so the
                                 average is the honest summary
      everything else   MAX      answered at one location, where an average
                                 over the whole sheet is not evidence

    A pointwise question with no worst-case supplied is REFUSED rather than
    falling back to RMS. Falling back is how the stricter test gets skipped
    exactly when the caller did not have the number to pass.

    Anything not named is refused rather than defaulted to the loosest.
    """
    limits = {"room_membership": TOL_ROOM_MEMBERSHIP_IN,
              "wall_side": TOL_WALL_SIDE_IN,
              "penetration": TOL_WALL_SIDE_IN,
              "clearance": TOL_CLEARANCE_IN,
              "clash": TOL_CLEARANCE_IN}
    lim = limits.get(question_kind)
    if lim is None:
        return False
    if question_kind in POINTWISE_QUESTIONS:
        if max_residual_in is None:
            return False
        return max_residual_in <= lim
    return rms_in <= lim


__all__ = [
    "PLAN_SCALE_DENOM", "PLAN_RENDER_DPI",
    "real_inches_per_pixel", "inches_to_pixels",
    "TOL_ROOM_MEMBERSHIP_IN", "ROOM_EDGE_EXCLUSION_IN",
    "TOL_WALL_SIDE_IN", "TOL_CLEARANCE_IN", "CLEARANCE_REFUSE_DEFAULT",
    "ANCHOR_MATCH_RADIUS_IN", "ANCHOR_MUST_BE_CORNER_LIKE",
    "MIN_ANCHORS", "MIN_ANCHOR_SPREAD_FRAC", "MAX_RMS_IN",
    "MAX_SINGLE_RESIDUAL_IN", "FLAG_ROTATION_DEG", "FLAG_SCALE_ANISOTROPY",
    "registration_verdict", "usable_for", "POINTWISE_QUESTIONS",
]
