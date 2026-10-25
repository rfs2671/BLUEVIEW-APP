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
            return no_silent_miss(got, unit_tags)
        reason = got["fallback"]
        validation = got.get("validation")
    else:
        reason, validation = "geometry forced by the caller", None
    log.warning("plan_space: CAD layers not used (%s) - falling back to the "
                "geometric pipeline", reason)
    out = geometry.build(page, sheet, unit_tags)
    out["fallback_reason"] = reason
    out["validation"] = validation
    return no_silent_miss(out, unit_tags)


def no_silent_miss(space: dict, unit_tags: Sequence[str]) -> dict:
    """A TAG WITH NO REGION MARKS THE SHEET INCOMPLETE (ruling 2026-10-24).

    The fail-safe already said so for a tag on a wall cell, a merged region
    and an empty one. Two ways out of it were silent, measured 2026-10-24
    on the filed mezzanine A-104.00 and the second set's A.1.5 (8 tags): a
    tag whose label sat outdoors - an occupancy table outside the building -
    joined no room group and simply was not in `units`; and a tag the plan
    never prints is not in `tags` at all. Either way the floor's per-unit
    split went ahead without it. Now every requested tag that ends with no
    unit region, and is not already refused or incomplete, is incomplete,
    with why."""
    units = space.get("units") or {}
    incomplete = space.setdefault("incomplete", {})
    held = {t for r in space.get("refused") or []
            if isinstance(r, (list, tuple)) and len(r) > 1 for t in r[1]}
    found = space.get("tags") or {}
    for t in unit_tags or []:
        if t in units or t in incomplete or t in held:
            continue
        if t not in found:
            incomplete[t] = "not printed on the plan - no label to seed its region"
        else:
            x, y = found[t]
            incomplete[t] = (f"its label at ({round(x)}, {round(y)}) is in no room of the "
                             "plan - outdoors (a table or schedule outside the building) "
                             "or a region no unit owns")
    return space
