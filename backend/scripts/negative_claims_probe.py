"""How many answers in the repo's claim sets assert absence as fact, before
and after lib/dm_negative_claims rewrites them. READ-ONLY, no database.

    python scripts/negative_claims_probe.py
    python scripts/negative_claims_probe.py --show      # each flagged sentence

Claim sets read (every answer text the repo keeps):
  eval/boyland.json                expected answer texts (cases[].expect.text / forbid_text)
  eval/results/*.json              observed answers (results[].render), with the
                                   run's records (results[].lead) as the trace
  tests/fixtures/dm_short_answers.snap.txt   DM headcount answers (no plan tool)
  scripts/dm_eval_replay.py        the live job-agent answers it replays
  tests/fixtures/dm_negative_claims.json     the gate's DM fixtures (10-27 spray foam)

Per file: answers scanned; flagged = absence sentences found (before);
fp? = flagged sentences that carry a sheet number (may be quoting a sheet's
note -- a false-positive candidate for a person to look at); after =
absence sentences left once the answer is rewritten.
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

from lib import dm_negative_claims as gate  # noqa: E402


def _plan_trace(records) -> list:
    """An eval result's lead records as one search_plans call."""
    recs = [{"sheet": r.get("sheet"), "quote": r.get("quote")} for r in records or []
            if isinstance(r, dict) and r.get("sheet")]
    return [{"tool": "search_plans", "args": {}, "result": "", "records": recs}]


def eval_cases(path: Path):
    doc = json.loads(path.read_text())
    for c in doc.get("cases") or []:
        exp = c.get("expect") or {}
        for t in list(exp.get("text") or []) + list(exp.get("forbid_text") or []):
            yield str(t), _plan_trace([]), True


def eval_results(path: Path):
    doc = json.loads(path.read_text())
    for r in doc.get("results") or []:
        if isinstance(r.get("render"), str) and r["render"].strip():
            yield r["render"], _plan_trace(r.get("lead")), True


def snapshot(path: Path):
    """`>>> question` then the answer, blank-line separated."""
    for block in path.read_text().split("\n\n"):
        lines = [x for x in block.split("\n") if x.strip()]
        if lines and lines[0].startswith(">>>"):
            ans = "\n".join(lines[1:])
            if ans:
                yield ans, [{"tool": "headcount", "args": {}, "result": ""}], False


def _module_strings(path: Path) -> dict:
    out = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return out


def replay_answers(path: Path):
    """LIVE_AGENT's answers; names resolved in the script, then in the test
    module it imports WINDOW from."""
    names = {**_module_strings(BACKEND / "tests" / "test_dm_show_sheet.py"),
             **_module_strings(path)}
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "LIVE_AGENT":
            for v in node.value.values:
                text = names.get(v.id) if isinstance(v, ast.Name) else ast.literal_eval(v)
                if isinstance(text, str):
                    yield text, [{"tool": "search_plans", "args": {}, "result": ""}], True


def dm_fixtures(path: Path):
    for c in json.loads(path.read_text()).get("cases") or []:
        trace = c.get("trace") or []
        yield c["answer"], trace, bool(gate.plan_calls(trace))


def claim_sets():
    yield "eval/boyland.json", eval_cases(BACKEND / "eval" / "boyland.json")
    for f in sorted(glob.glob(str(BACKEND / "eval" / "results" / "*.json"))):
        yield "eval/results/" + Path(f).name, eval_results(Path(f))
    yield "tests/fixtures/dm_short_answers.snap.txt", snapshot(
        BACKEND / "tests" / "fixtures" / "dm_short_answers.snap.txt")
    yield "scripts/dm_eval_replay.py", replay_answers(HERE / "dm_eval_replay.py")
    yield "tests/fixtures/dm_negative_claims.json", dm_fixtures(
        BACKEND / "tests" / "fixtures" / "dm_negative_claims.json")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="print each flagged sentence")
    a = ap.parse_args(argv)
    rows, shown = [], []
    for name, answers in claim_sets():
        n = flagged = fp = after = 0
        for text, trace, plans in answers:
            n += 1
            hits = gate.detect(text, plans)
            flagged += len(hits)
            fp += sum(1 for h in hits if gate.quotes_a_sheet(h))
            out, _k = gate.rewrite(text, trace)
            after += len(gate.detect(out, plans))
            if hits:
                shown.append((name, hits, out))
        rows.append((name, n, flagged, fp, after))
    w = max(len(r[0]) for r in rows)
    print(f"{'file'.ljust(w)}  answers  flagged  fp?  after")
    for name, n, flagged, fp, after in rows:
        print(f"{name.ljust(w)}  {n:7d}  {flagged:7d}  {fp:3d}  {after:5d}")
    tot = [sum(r[i] for r in rows) for i in range(1, 5)]
    print(f"{'TOTAL'.ljust(w)}  {tot[0]:7d}  {tot[1]:7d}  {tot[2]:3d}  {tot[3]:5d}")
    if a.show:
        for name, hits, out in shown:
            print(f"\n[{name}]")
            for h in hits:
                print(f"  flagged: {h[:200]}")
            print("  after:   " + out[:400].replace("\n", "\n           "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
