"""Run a plan-question suite against a project's live index. READ-ONLY.

    railway run python -m scripts.plan_eval --suite eval/boyland.json
    railway run python -m scripts.plan_eval --suite eval/boyland.json \\
        --out ../eval-results/boyland.json

WHAT IT DOES
============

1. Reads the corpus the suite was written against and REFUSES to score a
   different one. The suite carries a baseline — page count, current-page
   count, record count, and the newest write in each — and any difference
   means a sync or upload has written into the project since. A corpus that is
   partly one version of the writer and partly another cannot be scored as
   either, so the answer to drift is a fresh pass, not a caveat.

2. Builds the known-stale index over every record on the project and checks
   each class against the count the suite expects.

3. Calls `server.search_plans` — the shipped function, the one the agent calls
   — once per case, and scores what comes back with lib/plan_eval.

4. Reads the baseline again at the end. A write that landed DURING the run
   invalidates it just as much as one before.

WHAT IT NEVER DOES
==================

Write to the database. There is not one write call in this file, and
tests/test_every_prod_writer_is_guarded.py would say so if there were. The only
file it writes is the local results file named by --out.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from scripts.probe_helpers import describe, require_fields  # noqa: E402


def _stamp(v):
    return None if v is None else str(v)


async def observe(server, pid: str) -> dict:
    """The corpus as it stands, in the baseline's own terms.

    "Current" is decided by the server's own _live_plan_file_ids and
    _current_page_filter — the same two calls search_plans makes — rather than
    a second implementation of them here that could drift."""
    db = server.db
    live = await server._live_plan_file_ids(pid)
    base = {"project_id": pid}
    pages = await db.document_page_index.find(
        base, {"indexed_at": 1, "file_id": 1}).to_list(None)
    require_fields(pages, "indexed_at", "file_id")
    current = await db.document_page_index.count_documents(
        {**base, **server._current_page_filter(live)})
    newest_page = await db.document_page_index.find_one(
        base, {"indexed_at": 1}, sort=[("indexed_at", -1)])
    newest_rec = await db.plan_records.find_one(
        base, {"created_at": 1}, sort=[("created_at", -1)])
    return {
        "pages": await db.document_page_index.count_documents(base),
        "current_pages": current,
        "records": await db.plan_records.count_documents(base),
        "newest_page_indexed_at": _stamp((newest_page or {}).get("indexed_at")),
        "newest_record_created_at": _stamp((newest_rec or {}).get("created_at")),
    }


async def run(args) -> int:
    from lib import plan_eval as pe

    suite = pe.load_suite(args.suite)
    proj = suite["project"]
    pid = proj["id"]

    # The shipped search. Importing server does not start the app: routes are
    # registered and no startup hook runs.
    import server

    db = server.db
    cases = suite["cases"]
    print(f"suite  {args.suite}  ({len(cases)} cases)")
    print(f"project {proj.get('name')}  {pid}\n")

    before = await observe(server, pid)
    drift = pe.check_baseline(proj["baseline"], before)
    print("corpus :", before)
    if drift:
        print("\nREFUSING: the corpus is not the one this suite was written for.")
        for d in drift:
            print("   ", d)
        print("A sync or upload has written into the project. Re-index the whole "
              "project and record a new baseline; do not score a mixed corpus.")
        return 3

    records = await db.plan_records.find(
        {"project_id": pid}, {"embedding": 0}).to_list(None)
    print(describe(records, "record_type", "tier", "source", "page_id", "ordinal"))
    require_fields(records, "page_id", "record_type", "ordinal", "tier")
    stale = pe.stale_index(records)
    census = Counter(stale.values())
    expected = proj.get("stale") or {}
    print("\nknown-stale census (marked, not scored):")
    census_drift = []
    for cls in pe.STALE_CLASSES:
        got = census.get(cls, 0)
        want = expected.get(cls)
        flag = "" if want is None or want == got else f"   <-- suite expects {want}"
        if flag:
            census_drift.append(f"{cls}: expected {want}, found {got}")
        print(f"   {cls:46} {got:4}{flag}")

    known = pe.known_failure_classes(suite)
    results = []
    for case in cases:
        returned = await server.search_plans(
            pid, case["subject"], intent=case.get("intent") or "")
        r = pe.score_case(case, returned, stale)
        r["known_failure"] = known.get(case["id"])
        results.append(r)

    after = await observe(server, pid)
    moved = pe.check_baseline(before, after)

    summary = pe.summarise(results)
    print("\n" + "=" * 78)
    for r in results:
        mark = {"pass": "PASS ", "fail": "FAIL ", "stale": "STALE"}[r["outcome"]]
        lead = r["lead"][0] if r["lead"] else {}
        tag = ""
        if r.get("known_failure"):
            tag = (f"  [known: {r['known_failure']}]" if r["outcome"] == "fail"
                   else f"  [known {r['known_failure']} no longer fails]")
        print(f"{mark} {r['id']:28} {str(lead.get('sheet')):11} "
              f"{str(lead.get('tier')):14} n={r['checks'].get('returned')}{tag}")
        for why in r["reasons"]:
            print(f"        - {why}")
        for s in r["stale"]:
            print(f"        ~ stale: {s}")
    print("=" * 78)
    print(json.dumps(summary, indent=2))
    for lim in suite.get("known_limits") or []:
        print(f"known limit: {lim}")
    for k in suite.get("known_failures") or []:
        print(f"known failure class: {k['class']} ({k.get('status', 'open')}) "
              f"cases={k.get('cases')}")

    if moved:
        print("\nINVALID: the corpus moved DURING the run:")
        for d in moved:
            print("   ", d)
    if census_drift:
        print("\nNOTE: the stale census does not match the suite:")
        for d in census_drift:
            print("   ", d)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            # The suite file MOVES — cases were migrated into it when the
            # matcher was deleted, and more will be. A result names the case
            # set it actually scored, so an old record stays a record of its
            # own run instead of being read against a suite it never saw.
            "suite": args.suite,
            "suite_cases": [c["id"] for c in suite["cases"]],
            "project": pid,
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "corpus_before": before, "corpus_after": after,
            "valid": not moved,
            "stale_census": dict(census), "stale_census_drift": census_drift,
            "summary": summary, "results": results,
        }, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {out}")
    return 3 if moved else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if not os.environ.get("MONGO_URL"):
        print("MONGO_URL is not set. Run under `railway run`.")
        return 2
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
