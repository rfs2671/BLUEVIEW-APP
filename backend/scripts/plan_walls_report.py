"""Walls by type for one drawing set, from its PDF. READ-ONLY, LOCAL.

    python -m scripts.plan_walls_report --pdf "AR - 3.28.25.pdf" \\
        --plan 12:A-101.00:"SECOND FLOOR PLAN" --plan 13:A-102.00:"THIRD FLOOR PLAN" \\
        --types 24 --doors 23 --out ../walls-out

For each --plan PAGE:SHEET:TITLE: lib.plan_walls.floor_walls on that page
(scale from lib.plan_scale, apartments from lib.plan_space, the widest door
from the --doors page's schedule), one PNG with every wall coloured by type
(lib.plan_walls.render) and one JSON. Then, over the set: LF per type per
apartment, per floor and for the building, every refused viewport, every
untyped and ambiguous wall, and the plans' tags reconciled with the types
the --types page (A-500) defines - all in <out>/walls.json.

The floor of a plan is the level its TITLE names (lib.plan_walls.floor_of),
never a registration fit. A title naming none ("FLOOR PLAN") gives no floor:
its walls are reported at sheet scope and in no floor's or the building's
figure, and the report says so.

ONE SET PER RUN. Plans of two files are never summed into one building:
which drawings make up the building is ruling 21's question, not this
script's. Run it once per file and compare.

Nothing here touches the database or R2: its only writes are the files in
--out.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))


def _plan_arg(s: str):
    page, sheet, title = (s.split(":", 2) + ["", ""])[:3]
    return int(page), sheet, title


def _where(arg, pdf):
    """(pdf, page) from "PAGE" or "OTHER.pdf:PAGE"; None for None."""
    if arg in (None, ""):
        return None
    s = str(arg)
    if ":" in s and not s.split(":")[-1].strip() == "":
        f, p = s.rsplit(":", 1)
        if f.lower().endswith(".pdf"):
            return f, int(p)
    return pdf, int(s)


def run(pdf: str, plans, types_page=None, doors_page=None, out_dir="walls-out", dpi=100):
    from lib import plan_derive as D
    from lib import plan_scale
    from lib import plan_walls as W
    from lib.plan_page import PlanPage
    from lib.plan_sheet import load_sheet
    from lib.plan_space import build_space

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    doors_at, types_at = _where(doors_page, pdf), _where(types_page, pdf)
    door = D.widest_door_in(PlanPage(*doors_at).directed_words) if doors_at else {"inches": None}
    table = W.partition_types(PlanPage(*types_at).words) if types_at else {}
    sheets = []
    for page_no, sheet_no, title in plans:
        pg = PlanPage(pdf, page_no)
        data = load_sheet(pg)
        units = D.unit_tags(data["words"], data["corners"])
        space = None
        if units.get("tags") and door.get("inches"):
            space = build_space(pg, units["tags"], door["inches"], data)
        res = W.floor_walls(pg, scale_sheet=plan_scale.read_sheet(pg), space=space,
                            widest_door_in=door.get("inches"))
        res.update(page=page_no, sheet=sheet_no, title=title, floor=W.floor_of(title),
                   units=units.get("tags"), apartments_from=space and space.get("method"))
        stem = f"walls_{sheet_no or page_no}"
        res["png"] = W.render(pg, res, str(out / f"{stem}.png"), dpi=dpi, types=table or None,
                              title=f"{Path(pdf).name} p{page_no} {sheet_no} {title} - walls by type")
        (out / f"{stem}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        sheets.append(res)
        refused = res["refused_viewports"]
        logging.info("%s: %s untyped %.1f ambiguous %.1f refused %d", sheet_no, res["by_type"],
                     res["untyped_lf"], res["ambiguous_lf"], len(refused))
    summary = summarize(sheets, table)
    # ANOTHER FILE'S SCHEDULE IS SAID, NEVER IMPLIED (ruling 21: never pick
    # a set): the report names where the door width and the types came from.
    summary["pdf"] = str(pdf)
    summary["door_schedule"] = {"from": doors_at and f"{Path(doors_at[0]).name} p{doors_at[1]}",
                                "other_file": bool(doors_at and Path(doors_at[0]) != Path(pdf)),
                                "widest_door_in": door.get("inches")}
    summary["types_from"] = {"from": types_at and f"{Path(types_at[0]).name} p{types_at[1]}",
                             "other_file": bool(types_at and Path(types_at[0]) != Path(pdf))}
    (out / "walls.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    return summary


def summarize(sheets, table):
    """The set's figures. A floor is counted once: two plans claiming one
    floor are both reported and the floor's figure is refused."""
    from lib import plan_walls as W
    per_floor = defaultdict(list)
    for s in sheets:
        per_floor[s.get("floor")].append(s)
    floors, building, building_ok = {}, Counter(), True
    untyped = ambiguous = 0.0
    no_floor = [s["sheet"] for s in per_floor.pop(None, [])]
    for fl, ss in sorted(per_floor.items()):
        if len(ss) > 1:
            floors[fl] = {"refused": "two plans name this floor: " + ", ".join(s["sheet"] for s in ss)}
            building_ok = False
            continue
        s = ss[0]
        floors[fl] = {"sheet": s["sheet"], "by_type": s["by_type"], "untyped_lf": s["untyped_lf"],
                      "ambiguous_lf": s["ambiguous_lf"],
                      "refused_viewports": [v["title"] for v in s["refused_viewports"]]}
        building.update(s["by_type"])
        untyped += s["untyped_lf"]
        ambiguous += s["ambiguous_lf"]
    apartments = defaultdict(Counter)
    for s in sheets:
        for w in s["walls"]:
            key = w["type"] if w["status"] == W.TYPED else w["status"].upper()
            for scope, lf in (w.get("apartments") or {}).items():
                apartments[scope][key] += lf
    return {
        "floors": floors,
        "plans_with_no_floor": no_floor,
        "building_by_type": ({k: round(v, 2) for k, v in sorted(building.items())} if building_ok
                             else "refused: a floor is claimed by two plans"),
        "building_untyped_lf": round(untyped, 2),
        "building_ambiguous_lf": round(ambiguous, 2),
        "apartments": {k: {t: round(v, 2) for t, v in sorted(c.items())} for k, c in sorted(apartments.items())},
        "types_table": table,
        "reconciliation": W.reconcile({s["sheet"]: [t["text"] for t in s["tags"]] for s in sheets}, table)
        if table else "no wall-type sheet given (--types)",
        "sheets": [{k: s[k] for k in ("sheet", "page", "title", "floor", "by_type", "untyped_lf",
                                      "ambiguous_lf", "refusal", "png")} for s in sheets],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--plan", action="append", type=_plan_arg, required=True,
                    help="PAGE:SHEET:TITLE, e.g. 12:A-101.00:SECOND FLOOR PLAN")
    ap.add_argument("--types", help="page of the wall-type sheet (A-500): PAGE, or OTHER.pdf:PAGE")
    ap.add_argument("--doors", help="page of the door schedule (A-400): PAGE, or OTHER.pdf:PAGE")
    ap.add_argument("--out", default="walls-out")
    ap.add_argument("--dpi", type=int, default=100)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = run(a.pdf, a.plan, a.types, a.doors, a.out, a.dpi)
    print(json.dumps({k: s[k] for k in ("floors", "building_by_type", "building_untyped_lf",
                                        "reconciliation", "door_schedule", "types_from")},
                     indent=1, default=str))


if __name__ == "__main__":
    main()
