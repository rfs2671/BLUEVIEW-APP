"""Light fixtures counted by their tags, on local PDFs (lib.plan_light_fixtures).

    python scripts/light_fixture_counts.py SCHEDULE.pdf PAGE  PLANS.pdf PAGE [PAGE ...] [--rows]

ONE DRAWING SET PER RUN: the vocabulary is the set's own LIGHTING SCHEDULE
(SCHEDULE.pdf PAGE), and the printed totals are cross-checked only against
that set's sheets. Prints, per sheet, each drawing's counts per tag, every
refused tag and why, every untagged fixture drawing, and the cross-check;
--rows prints the rows a pass would store (fixture_rows) as JSON. Read-only:
nothing is written anywhere, and nothing here is a counting source for chat.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import plan_light_fixtures as lf  # noqa: E402
from lib.plan_page import PlanPage  # noqa: E402


def main(argv):
    rows_out = "--rows" in argv
    argv = [a for a in argv if a != "--rows"]
    if len(argv) < 4:
        print(__doc__)
        return 2
    sched_pdf, sched_pg, plans, pages = argv[0], int(argv[1]), argv[2], [int(a) for a in argv[3:]]
    sp = PlanPage(sched_pdf, sched_pg)
    sch = lf.schedule_tags(sp.directed_word_boxes)
    print(f"vocabulary ({sched_pdf} p{sched_pg}): {sch.get('tags') or sch.get('why')}")
    results, totals, rows = {}, [], []
    same = Path(sched_pdf).resolve() == Path(plans).resolve()
    for pg in pages:
        p = PlanPage(plans, pg)
        excl = [sch["box"]] if same and pg == sched_pg and sch.get("box") else []
        res = lf.count_sheet(p, sch.get("tags") or [], exclude=excl)
        key = f"p{pg}"
        results[key] = res
        totals += lf.printed_totals(p.directed_word_boxes, sch.get("tags") or [], key)
        print(f"\n{plans} p{pg}" + (f"  REFUSED: {res['refused']}" if res.get("refused") else ""))
        for title, c in res["counts"].items():
            print(f"  {title or '(no drawing title)'}: {c}")
        for t in res["tags"]:
            if t["status"] != "counted":
                print(f"  refused {t['tag']} at {[round(v) for v in t['box']]}: {t['why']}")
        for u in res["untagged"]:
            print(f"  untagged drawing ({'/'.join(u['could_be'])}) at {u['box']}")
    checks = lf.cross_check(results, totals)
    if checks:
        print("\nprinted totals:")
        for c in checks:
            print(f"  {c['where']} {c['tag']}: {c['status']}"
                  + (f" (drawn {c['count']}, printed {c['printed']})" if c.get("count") is not None else "")
                  + (f" - {c['why']}" if c.get("why") else ""))
    if rows_out:
        for key, res in results.items():
            rows += lf.fixture_rows(res, {"file_name": Path(plans).name, "page_number": int(key[1:])},
                                    checks=checks)
        print(json.dumps(rows, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
