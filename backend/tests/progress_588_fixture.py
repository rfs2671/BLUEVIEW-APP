"""A 588-like job for lib/project_progress.py: cellar, four floors and a roof,
and the subs the real job has. Every item is lib/evidence.py's shape. The words
and dates are made up; the shapes and the mix of rungs are the point:
mostly reported crew rows filed for several floors together, a few attested
statements, one photo, check-ins, one estimate, nothing verified."""

from __future__ import annotations

from datetime import date, timedelta

from lib import evidence as E

PID = "proj_588"
TODAY = date(2026, 11, 10)
PROJECT = {"_id": PID, "name": "588 Thomas", "building_stories": 4, "has_cellar": True,
           "has_roof_bulkhead": True, "has_sub_cellar": None, "has_mezzanine": None}
F1_4 = ["FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4"]
SCHEDULE = {"activities": [{"id": "A100", "name": "Drywall Floor 2", "kind": "task", "percent_complete": 40,
                            "baseline_finish": "2026-11-20"}]}


def d(month: int, day: int) -> date:
    return date(2026, month, day)


def rep(sub, node, levels, on, ref, quote=None):
    return E.item("reported", "in_progress", source="logbooks", ref=ref, project_id=PID, node=node, levels=levels,
                  sub=sub, on=on, quote=quote, shared=len(levels) > 1)


def said(claim, node, levels, on, ref, quote, by="Mike R.", sub=None):
    return E.item("attested", claim, source="whatsapp", ref=ref, project_id=PID, node=node, levels=levels,
                  sub=sub, on=on, by=by, quote=quote, shared=len(levels) > 1)


def photo(sub, node, levels, on, ref, quote):
    return E.item("observed", "in_progress", source="photo_index", ref=ref, project_id=PID, node=node, levels=levels,
                  sub=sub, on=on, quote=quote)


def checkins(sub, first, days):
    return [E.item("reported", "present", source="checkins", ref=f"ck-{sub[:5]}-{first + timedelta(days=k)}",
                   project_id=PID, sub=sub, on=first + timedelta(days=k)) for k in range(days)]


def items():
    out = [
        # Arkon Builders: framing on the four floors together, then a statement for 1 and 2, then drywall on 2.
        rep("Arkon Builders", "framing", F1_4, d(9, 15), "L0915:0", "Framing, studs and track"),
        rep("Arkon Builders", "framing", F1_4, d(9, 22), "L0922:0", "Framing"),
        rep("Arkon Builders", "framing", F1_4, d(10, 6), "L1006:0", "Blocking and framing"),
        said("done", "framing", ["FLOOR_1", "FLOOR_2"], d(10, 9), "wa-1009", "framing done on 1 and 2"),
        rep("Arkon Builders", "drywall", ["FLOOR_2"], d(11, 6), "L1106:0", "Sheetrock"),
        # Quality Plumbing: cellar, then floors 1-3 together; plumbing rough passed on 1; on 3 passed then failed.
        rep("Quality Plumbing", "rough_dwv", ["CELLAR"], d(10, 1), "L1001:1", "Sanitary"),
        rep("Quality Plumbing", "rough_dwv", ["FLOOR_1", "FLOOR_2", "FLOOR_3"], d(10, 13), "L1013:1", "DWV"),
        rep("Quality Plumbing", "rough_water", ["FLOOR_1", "FLOOR_2", "FLOOR_3"], d(10, 20), "L1020:1", "Domestic water rough"),
        said("done", "gate_plumbing_rough", ["FLOOR_1"], d(10, 22), "wa-1022", "plumbing rough passed on 1"),
        said("done", "gate_plumbing_rough", ["FLOOR_3"], d(10, 28), "wa-1028", "plumbing rough passed on 3"),
        said("failed", "gate_plumbing_rough", ["FLOOR_3"], d(11, 3), "wa-1103", "plumbing rough on 3 failed, redo"),
        # Power Direct: electric rough on 1 and 2, recent; electrical rough passed on 1.
        rep("Power Direct", "rough_electric", ["FLOOR_1", "FLOOR_2"], d(11, 4), "L1104:2", "Pulling wire"),
        rep("Power Direct", "rough_electric", ["FLOOR_1", "FLOOR_2"], d(11, 9), "L1109:2", "Conduit"),
        said("done", "gate_electrical_rough", ["FLOOR_1"], d(11, 5), "wa-1105", "electrical rough passed floor 1"),
        # BreezCo: duct on 1; a photo of duct on 4 on a day no log names floor 4.
        rep("BreezCo", "rough_duct", ["FLOOR_1"], d(10, 15), "L1015:3", "Ductwork"),
        photo("BreezCo", "rough_duct", ["FLOOR_4"], d(11, 7), "p7k2", "Sheet-metal duct hung below the deck."),
        # A1: sprinkler on 1-2. Pinnacle: fire alarm on 1.
        rep("A1", "rough_sprinkler", ["FLOOR_1", "FLOOR_2"], d(10, 27), "L1027:4", "Sprinkler branch lines"),
        rep("Pinnacle", "rough_lowvolt", ["FLOOR_1"], d(11, 9), "L1109:5", "Fire alarm rough"),
        # J&P Construction: insulation on 1 (no step of the template).
        rep("J&P Construction", "insulation", ["FLOOR_1"], d(11, 2), "L1102:6", "Spray foam"),
        # A forecast: never a fact.
        E.item("estimate", "done", source="forecast", ref="fc-1", project_id=PID, node="drywall", levels=["FLOOR_3"],
               on=d(12, 1), basis="crew moves between floors"),
    ]
    out += checkins("Arkon Builders", d(10, 27), 10)
    out += checkins("Quality Plumbing", d(10, 20), 4)
    out += checkins("Slate Windows", d(10, 20), 5)
    return out
