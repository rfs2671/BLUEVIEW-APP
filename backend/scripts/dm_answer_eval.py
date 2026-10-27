"""Score the DM answers a person got against an owner-written suite. OFFLINE.

    railway run python scripts/dm_thread_timeline.py --email roy@company.com \\
        --date 2026-10-27 --json /tmp/dm_2026-10-27.json
    python scripts/dm_answer_eval.py --suite eval/boyland-dm-2026-10-27.json \\
        --timeline /tmp/dm_2026-10-27.json
    python scripts/dm_answer_eval.py --suite eval/boyland-dm-2026-10-27.json \\
        --answers replay.json            # [{"case": id, "answer": "...", "tools": [...]}]

Reads files only: no database, no network, nothing written but --out. Each
case is found in the day's messages by its `match` pattern (every time it
was asked is scored; the case is as good as its worst answer), or taken from
--answers by id. Outcomes: PASS, FAIL, FAILING-PENDING (the right answer is
not fully known yet -- never a pass; see lib/dm_answer_eval) and NOT-ASKED.
Exit code 0 only when every case passed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import dm_answer_eval as de  # noqa: E402

MARK = {"pass": "PASS           ", "fail": "FAIL           ",
        "failing-pending": "FAILING-PENDING", "not-asked": "NOT-ASKED      "}


def run(a, out=print) -> int:
    suite = de.load_suite(a.suite)
    timeline = json.loads(Path(a.timeline).read_text(encoding="utf-8")) if a.timeline else {}
    given = {}
    if a.answers:
        for row in json.loads(Path(a.answers).read_text(encoding="utf-8")):
            given.setdefault(row["case"], []).append(
                {"answer": row.get("answer") or "", "tools": row.get("tools") or [], "asked": "(given)"})
    cases = suite["cases"]
    out(f"suite {a.suite} ({len(cases)} cases)")
    report, outcomes = [], []
    for case in cases:
        turns = given.get(case["id"]) or (de.find_turns(case, timeline) if timeline else [])
        results = [dict(de.score_answer(case, t["answer"], t["tools"]), asked=t.get("asked"),
                        at=t.get("at")) for t in turns] or [de.score_answer(case, None)]
        outcome = de.worst(results)
        outcomes.append(outcome)
        report.append({"id": case["id"], "outcome": outcome, "answers": results})
        out(f"{MARK[outcome]} {case['id']}")
        for r in results:
            if r.get("asked"):
                out(f"    asked: {r['asked']}")
            for why in r["reasons"]:
                out(f"      - {why}")
    summary = de.summarise(outcomes)
    out(json.dumps(summary, indent=2))
    if a.out:
        Path(a.out).write_text(json.dumps({"suite": a.suite, "summary": summary, "cases": report},
                                          indent=2, default=str), encoding="utf-8")
    return 0 if summary["pass"] == summary["cases"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", required=True)
    ap.add_argument("--timeline", help="a dm_thread_timeline.py --json file")
    ap.add_argument("--answers", help='a JSON list of {"case", "answer", "tools"}')
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    if not (a.timeline or a.answers):
        ap.error("--timeline or --answers")
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
