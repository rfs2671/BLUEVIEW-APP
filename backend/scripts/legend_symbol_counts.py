"""Legend symbol counts for sheets of a local PDF. READ-ONLY.

    python scripts/legend_symbol_counts.py "PL - 6.29.26.pdf" --pages 2-15 \\
        --set-legend 1 --set-legend-sheet P-001.00 [--json out.json] [--rows]

For each page: every row of the sheet's own legend (lib.plan_legend_symbols)
matched against every connected object on the sheet, plus - with
--set-legend - the rows of a SYMBOLS LIST page in the same file (P-001.00's
note 1: "GENERAL NOTES, SYMBOLS LIST AND DETAILS ARE APPLICABLE TO ALL
DRAWINGS MARKED P"). Prints, per legend row, the count and where each match
is, or the refusal and why. With --rows, the rows a pass WOULD store
(plan_legend_symbols.legend_count_rows) go into the JSON; nothing is written
to any database, and nothing here reads one.

The CALLER picks plan pages. A riser diagram or a detail sheet draws the same
symbols and is not a plan; pass plan pages only. Text drawn as vectors (JPW's
SHX) is read with lib.plan_ocr's local engine; without it the rows still
count, with empty meanings.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import plan_legend_symbols as pls  # noqa: E402
from lib.plan_page import PlanPage  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_helpers import require_fields  # noqa: E402


def pages_arg(s: str):
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf")
    ap.add_argument("--pages", required=True, help="1-based, e.g. 2-15 or 10,12")
    ap.add_argument("--set-legend", type=int, help="page of a SYMBOLS LIST sheet in this file")
    ap.add_argument("--set-legend-sheet", default="set legend")
    ap.add_argument("--json", help="write the results here")
    ap.add_argument("--rows", action="store_true", help="include the rows a pass would store")
    a = ap.parse_args(argv)
    extra = []
    if a.set_legend:
        extra = pls.set_legend(PlanPage(a.pdf, a.set_legend), a.set_legend_sheet)
    out = {}
    for n in pages_arg(a.pages):
        page = PlanPage(a.pdf, n)
        res = pls.count_sheet(page, extra)
        # the fields counted below are the module's own result keys; say so
        require_fields([res], "legend_boxes", "objects", "rows")
        counted = [r for r in res["rows"] if "refused" not in r]
        if counted:
            require_fields(counted, "matches", "near", "twice")
        print(f"== {Path(a.pdf).name} p{n}: {len(res['legend_boxes'])} legend(s), "
              f"{res['objects']} objects")
        for r in res["rows"]:
            name = f"{r['meaning'][:48]:48s} [{r['src']}]"
            if "refused" in r:
                print(f"   {name} REFUSED: {r['refused']}")
            else:
                print(f"   {name} {len(r['matches'])}"
                      + (f" (+{r['twice']} drawn twice)" if r.get("twice") else "")
                      + (f", {len(r['near'])} near" if r.get("near") else ""))
        out[str(n)] = res
        if a.rows:
            res["would_store"] = pls.legend_count_rows(
                res, {"file_name": Path(a.pdf).name, "page_number": n})
        page.close()
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
