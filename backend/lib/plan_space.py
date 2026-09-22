"""Which apartment each point of an architectural plan belongs to.

PRIMARY: the sheet's own CAD layers (plan_space_layers). FALLBACK: geometry
alone (plan_space_geometry), used when the wall layer is missing, fails
validation, or no door-schedule width bounds a doorway - and the reason is
LOGGED and returned, so an answer always says which path produced it.

Either path returns the same map: `units` (tag -> cell mask, single-tag
regions only), `refused` (regions holding other than one tag - every point in
them is refused, never assigned), `incomplete` (tags with no usable region,
and why), `public`, `closed_lab`, `names`, `outdoors`, `door_rooms`, `grid`,
`lo`, `cell_pt`, `tags`, `ratio` (area / printed NET, informational), plus
`method` and `fallback_reason`.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from lib import plan_space_geometry as geometry
from lib import plan_space_layers as layers
from lib.plan_sheet import load_sheet

log = logging.getLogger(__name__)


def build_space(page, unit_tags: Sequence[str],
                widest_door_in: Optional[float], sheet: Optional[dict] = None,
                force_geometry: bool = False) -> dict:
    """Membership map for one architectural page."""
    sheet = sheet or load_sheet(page)
    if not force_geometry:
        got = layers.build(page, sheet, unit_tags, widest_door_in)
        if "fallback" not in got:
            got["fallback_reason"] = None
            return got
        reason = got["fallback"]
        validation = got.get("validation")
    else:
        reason, validation = "geometry forced by the caller", None
    log.warning("plan_space: CAD layers not used (%s) - falling back to the "
                "geometric pipeline", reason)
    out = geometry.build(page, sheet, unit_tags)
    out["fallback_reason"] = reason
    out["validation"] = validation
    return out
