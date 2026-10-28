"""Does the negative-claims gate (lib/dm_negative_claims) change any NUMBER
an answer gives? READ-ONLY, no database. Roy's merge bar for the gate:

  (a) zero numeric binding changes across every claim set
      (equipment, doors/windows, RD, areas -- and the rest);
  (b) the only changes are absence claims rewritten to "Not found in the
      sheets I searched: ..." (or the not-searched line);
  (c) the 10-27 spray-foam case passes.

    python scripts/negative_claims_bindings.py

For every stored plan answer (eval/results/*.json, results[].render, with
that run's lead records as the turn's search_plans trace):
  numbers  = the multiset of numbers in the answer, before and after the
             gate, the gate's own lines ("Not found in the sheets I
             searched", "Closest detail") left out of "after";
  values   = each case's expect.values found in the answer before, and
             whether each is still there after;
  changed  = answers whose text the gate changed at all, and whether every
             change is an absence sentence replaced (b).
(c) scores the eval/boyland-dm-2026-10-27.json spray-foam case
(lib/dm_answer_eval) on the gated 10-27 answer and on a right answer.
"""

from __future__ import annotations

import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

from lib import dm_answer_eval as de  # noqa: E402
from lib import dm_negative_claims as gate  # noqa: E402

#: Roy's claim sets, by eval/boyland.json case id. Anything else is "other".
SETS = {
    "equipment": {"ptac-count", "ptac-make-and-model", "wall-heater-count",
                  "duct-heater-capacity", "exhaust-fan-models", "diffuser-manufacturer",
                  "ac-type", "packaged-terminal-air-conditioners", "ptac-2-contested",
                  "elevator", "sprinklered", "exhaust-fans-per-unit-fourth-floor",
                  "exhaust-fans-in-duplex-4a", "vent-fan-count-not-stated"},
    "doors/windows": {"door-size"},
    "RD": {"roof-drain-count"},
    "areas": {"passive-recreation-area", "roof-occupancy-load", "ceiling-height"},
}
NUM = re.compile(r"(?<![\w.])\d+(?:[.,/]\d+)*(?![\w])")
GATE_LINE = re.compile(r"^(?:%s|Closest detail:|%s)" % (
    re.escape(gate.NOT_FOUND_PREFIX), re.escape(gate.NOT_SEARCHED_TEXT)))

# The 10-27 answer as it was sent (the 10-27 thread), and a right answer --
# its quote is FIXTURE TEXT, not read off the sheet.
LIVE_1027 = "Nothing on the drawings calls for spray foam on the 5th floor ceiling."
RIGHT_1027 = ("The 5th floor is the Mezzanine (A-104.00); its ceiling is the roof assembly. "
              "A-302.00 detail 4 (ROOF ASSEMBLY DETAIL) gives the insulation: "
              "\"FIXTURE TEXT: ROOF INSULATION\".")
TRACE_1027 = [{"tool": "search_plans", "args": {}, "result": "",
               "records": [{"sheet": "A-302.00", "quote": "FIXTURE TEXT: ROOF ASSEMBLY DETAIL"},
                           {"sheet": "A-104.00", "quote": "FIXTURE TEXT: MEZZANINE PLAN"}]}]


def set_of(case_id: str) -> str:
    return next((k for k, ids in SETS.items() if case_id in ids), "other")


def numbers(text: str, drop_gate_lines: bool = False) -> Counter:
    lines = [ln for ln in str(text or "").split("\n")
             if not (drop_gate_lines and GATE_LINE.match(ln.strip()))]
    return Counter(NUM.findall("\n".join(lines)))


def _trace(lead) -> list:
    return [{"tool": "search_plans", "args": {}, "result": "",
             "records": [{"sheet": r.get("sheet"), "quote": r.get("quote")}
                         for r in lead or [] if isinstance(r, dict) and r.get("sheet")]}]


def values_of(case: dict) -> list:
    out = []
    for v in (case.get("expect") or {}).get("values") or []:
        out.append(str(v))
    return out


def only_absence_changed(before: str, after: str, plans: bool = True) -> bool:
    """(b): every sentence the gate removed was an absence claim, and every
    line it added is its own."""
    def sents(t):
        return [s.strip() for ln in t.split("\n") for s in gate._sentences(ln) if s.strip()]
    b, a = sents(before), sents(after)
    removed = [s for s in b if s not in a]
    added = [s for s in a if s not in b]
    return (all(gate.is_absence_claim(s, plans) for s in removed)
            and all(GATE_LINE.match(s) or s.startswith(gate.NOT_FOUND_PREFIX) for s in added))


def bindings() -> dict:
    cases = {c["id"]: c for c in json.loads(
        (BACKEND / "eval" / "boyland.json").read_text())["cases"]}
    per = {}
    for f in sorted(glob.glob(str(BACKEND / "eval" / "results" / "*.json"))):
        for r in json.loads(Path(f).read_text()).get("results") or []:
            text = r.get("render")
            if not isinstance(text, str) or not text.strip():
                continue
            s = per.setdefault(set_of(r.get("id", "")), Counter())
            after, n = gate.rewrite(text, _trace(r.get("lead")))
            s["answers"] += 1
            s["refusals"] += r.get("kind") == "absent"
            s["numbers_before"] += sum(numbers(text).values())
            s["numbers_after"] += sum(numbers(after, drop_gate_lines=True).values())
            s["numeric_changes"] += numbers(text) != numbers(after, drop_gate_lines=True)
            vals = [v for v in values_of(cases.get(r.get("id"), {})) if v in numbers(text)]
            s["values_before"] += len(vals)
            s["values_after"] += sum(1 for v in vals if v in numbers(after, True))
            s["text_changed"] += after != text
            s["rewritten"] += n
            s["non_absence_changes"] += (after != text) and not only_absence_changed(text, after)
    return per


def spray_foam() -> dict:
    suite = de.load_suite(str(BACKEND / "eval" / "boyland-dm-2026-10-27.json"))
    case = next(c for c in suite["cases"] if c["id"] == "spray-foam-5th-floor-ceiling")
    out = {}
    for name, ans in (("10-27 answer as sent", LIVE_1027), ("a right answer", RIGHT_1027)):
        gated, _n = gate.rewrite(ans, TRACE_1027)
        res = de.score_answer(case, gated, ["search_plans"])
        out[name] = {"gated": gated, "outcome": res["outcome"],
                     "forbidden_hit": [k for k, ok in res["checks"].items()
                                       if k.startswith("forbid") and not ok],
                     "missing": [k for k, ok in res["checks"].items()
                                 if not k.startswith("forbid") and not ok]}
    return out


def main(argv=None) -> int:
    per = bindings()
    cols = ("answers", "refusals", "numbers_before", "numbers_after", "numeric_changes",
            "values_before", "values_after", "text_changed", "rewritten", "non_absence_changes")
    print("claim set      " + "  ".join(c.replace("_", " ") for c in cols))
    tot = Counter()
    for name in ("equipment", "doors/windows", "RD", "areas", "other"):
        s = per.get(name, Counter())
        tot.update(s)
        print(f"{name:<14} " + "  ".join(f"{s[c]:>{len(c)}d}" for c in cols))
    print(f"{'TOTAL':<14} " + "  ".join(f"{tot[c]:>{len(c)}d}" for c in cols))
    print("\n10-27 spray-foam case (eval/boyland-dm-2026-10-27.json):")
    for name, r in spray_foam().items():
        print(f"  {name}: {r['outcome']}  forbidden hit: {r['forbidden_hit'] or 'none'}  "
              f"missing: {r['missing'] or 'none'}")
        print("    gated: " + r["gated"].replace("\n", "\n           "))
    bad = tot["numeric_changes"] or tot["non_absence_changes"]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
