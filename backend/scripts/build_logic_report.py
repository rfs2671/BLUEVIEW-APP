"""A job's schedule from its scope and the order construction has to follow,
and where the filed daily logs put the job against it. Read-only.

    railway run python scripts\\build_logic_report.py --project 588 --system cfs [--piles] [--units 6]
        [--cycle 7] [--no-sprinkler] [--gas] [--elevator] [--end 2026-11-19] [--start 2026-07-29] [--es]

Prints, for one project (lib/build_logic.py):
  * THE PLAN: the whole job from day one by the logic alone, the chain that
    sets its length, the least it could take with unlimited crews, and what a
    second crew of each trade would buy
  * THE STRUCTURE'S REAL PACE: worked site days from floor to floor, from the logs
  * WHERE THE JOB STANDS: work logged before something it depends on,
    inspections no log mentions, how long trades waited for a ready floor,
    what can start today, and the finish the remaining logic gives

The floors, cellar and bulkhead come from the project; the structural system
and the apartments per floor are not on the project record and are given here.
The durations are the starting table in lib/build_logic.py: assumptions until
the operator corrects them. No model is called and nothing is stored.

Read-only like real_report_dry_run.py: every database write is blocked before
the application is imported.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import real_report_dry_run as R  # noqa: E402


def _span(rows, es):
    for r in rows:
        when = f"{r['forecast_start'] or 'under way'} -> {r['forecast_finish']}"
        yield f"  {(r['es'] if es else r['label'])[:52]:<53} fl {r['floor'] or '-':<3} {r['state']:<7} {when}"


async def main(a):
    import server
    from lib import build_logic as B
    from lib import progress_report as PR
    project = await R.find_project(server, a.project, a.company)
    pid = str(project.get("_id"))
    stories = int(project.get("building_stories") or 0)
    if stories < 1:
        sys.exit(f"{project.get('name')}: the project has no storey count. Nothing to schedule.")
    scope = B.Scope(floors=stories, system=a.system, units_per_floor=a.units, piles=a.piles,
                    cellar=bool(project.get("has_cellar")), bulkhead=bool(project.get("has_roof_bulkhead")),
                    sprinkler=not a.no_sprinkler, gas=a.gas, elevator=a.elevator, cycle_days=a.cycle)
    docs = await server.db.logbooks.find(
        {"project_id": pid, "log_type": "daily_jobsite", "is_deleted": {"$ne": True}},
        {"date": 1, "data.activities": 1, "is_amendment": 1, "parent_logbook_id": 1, "status": 1,
         "is_locked": 1, "log_type": 1, "created_at": 1, "updated_at": 1, "amendment_reason": 1}).to_list(6000)
    heads = []
    for chain in server.collapse_amendment_chains(docs):
        head = chain["head"]
        if server.logbook_is_filed(head) and not server.logbook_is_withdrawn(head):
            heads.append({**head, "_chain_length": chain["length"]})
    logs = PR.effective_logs(heads)["items"]
    rows = PR._log_activities(logs, date(1900, 1, 1), date(2100, 1, 1))
    es = a.es
    print(f"project: {project.get('name')} | company {project.get('company_name') or project.get('company_id')} | id {pid}")
    print(f"scope: {scope.floors} floors, {scope.system}, {scope.units_per_floor:g} apartments a floor, "
          f"flags {sorted(scope.flags() - {scope.system})}")

    p = B.plan(scope)
    print(f"\nTHE PLAN BY THE LOGIC ALONE: {p['days']:g} working days with one crew per trade; "
          f"{p['fastest']:g} is the least the hard rules allow with a crew on every floor.")
    for g in p["second_crew"]:
        print(f"  a second {g['trade']} crew saves {g['days_saved']:g} working days")
    print("  what sets the length: " + " > ".join(B.name(k, es) for k in p["chain"]))
    if a.start:
        cal = B.on_calendar(p, date.fromisoformat(a.start))
        print(f"  from {cal['start_date']} that finishes {cal['finish_date']}")

    if not rows:
        print("\nno filed daily log has a crew row: nothing to hold the plan against.")
        return
    end = date.fromisoformat(a.end) if a.end else max(r["date"] for r in rows)
    m = B.measured_cycle(scope, rows, end)
    print("\nTHE STRUCTURE'S REAL PACE (worked site days from floor to floor, from the logs)")
    for s in m["steps"]:
        print(f"  floor {s['from']} to {s['to']}: {s['days']}")
    print(f"  usual: {m['cycle'] if m['cycle'] is not None else 'not enough floors logged'}")

    st = B.status(scope, rows, end)
    f = B.findings(st, es)
    print(f"\nWHERE THE JOB STANDS ON {st['as_of']}: {st['done']} of {st['of']} activities behind it.")
    for title, key in (("WORK LOGGED BEFORE SOMETHING IT DEPENDS ON", "early"),
                       ("INSPECTIONS AND CHECKS NO LOG MENTIONS (a log is not an inspection record)", "not_on_record"),
                       ("TRADES THAT STARTED AFTER THEIR FLOOR WAS READY", "waited")):
        print(f"\n{title}")
        for line in f[key] or ["nothing"]:
            print(f"  - {line}")
    print("\nCAN START TODAY BY THE LOGIC")
    for line in f["open_now"] or ["nothing"]:
        print(f"  - {line}")
    print(f"\nTHE FINISH THE REMAINING LOGIC GIVES, IF THE TABLE'S DURATIONS HOLD: {st['finish_date']} "
          f"({st['days_left']:g} working days).")
    print("  what sets it: " + " > ".join(B.name(k, es) for k in st["chain"]))
    if a.verbose:
        print("\nEVERY ACTIVITY NOT YET BEHIND THE JOB")
        for line in _span([n for n in st["nodes"] if n["state"] != "done" and (n["trade"] or n["gate"])], es):
            print(line)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--company", default=None)
    ap.add_argument("--system", required=True, choices=["cast_in_place", "cfs", "block_plank"])
    ap.add_argument("--units", type=float, default=6.0, help="apartments per floor")
    ap.add_argument("--cycle", type=float, default=None, help="superstructure working days per floor")
    ap.add_argument("--piles", action="store_true")
    ap.add_argument("--no-sprinkler", action="store_true")
    ap.add_argument("--gas", action="store_true")
    ap.add_argument("--elevator", action="store_true")
    ap.add_argument("--start", default=None, help="put the plan on the calendar from this day (YYYY-MM-DD)")
    ap.add_argument("--end", default=None, help="read the record up to this day (YYYY-MM-DD); default: its last day")
    ap.add_argument("--es", action="store_true", help="findings in Spanish")
    ap.add_argument("--verbose", action="store_true")
    A = ap.parse_args()
    R.configure_environment()
    R.lock_database()
    asyncio.run(main(A))
