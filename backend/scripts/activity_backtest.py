"""How well would each ranking have predicted the activities a crew really logged?

    railway run python scripts\\activity_backtest.py --project 588 [--top 4]

Read-only, like real_report_dry_run.py (every database write is blocked before
the application is imported). Replays the project's filed daily logs: for each
day a crew logged activities, it ranks the chips knowing only the days before,
and counts how many of the activities the crew really logged were in the first
`top` chips -- for the ranking as it was, and for the ranking re-ordered by the
crew's own history (app/scheduling/crew_history.py).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import real_report_dry_run as R  # noqa: E402


async def main(a):
    import server
    from app.scheduling import chip_backtest as BT
    project = await R.find_project(server, a.project, a.company)
    pid = str(project.get("_id"))
    print(f"project: {project.get('name')} | id {pid}")
    logs = await server.db.logbooks.find({"project_id": pid, "log_type": "daily_jobsite",
                                          "is_deleted": {"$ne": True}}).sort([("date", 1)]).to_list(2000)
    res = BT.backtest(logs, project_id=pid, top=a.top, structural_system=project.get("structural_system"))
    o = res["overall"]
    print(f"daily logs read: {', '.join([str(x.get('date'))[:10] for x in logs[:1]] + ['...'] + [str(x.get('date'))[:10] for x in logs[-1:]])}")
    print(f"\\ncrew-days replayed: {o['crew_days']}   activities logged: {o['actual']}   (first {res['top']} chips)")
    print(f"  baseline      {BT.rate(o['baseline_hits'], o['actual'])}  ({o['baseline_hits']} of {o['actual']})")
    print(f"  personalized  {BT.rate(o['personalized_hits'], o['actual'])}  ({o['personalized_hits']} of {o['actual']})")
    print("\\nby trade:")
    for trade, s in sorted(res["by_trade"].items()):
        print(f"  {trade:<28} days {s['crew_days']:>3}  baseline {BT.rate(s['baseline_hits'], s['actual']):>5}  "
              f"personalized {BT.rate(s['personalized_hits'], s['actual']):>5}")
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "activity_backtest.txt"), "w", encoding="utf-8") as f:
        for r in res["rows"]:
            f.write(f"{r['date']} | {r['trade']} | history {r['had_history']} | actual {r['actual']} | "
                    f"baseline {r['baseline_top']} ({r['baseline_hits']}) | personalized {r['personalized_top']} "
                    f"({r['personalized_hits']})\\n")
    print(f"\\nwrote {os.path.join(out, 'activity_backtest.txt')} (one line per crew-day)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backtest the activity-chip ranking on a project's filed logs.")
    ap.add_argument("--project", required=True)
    ap.add_argument("--company", default="")
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "..", "docs", "samples", "real"))
    A = ap.parse_args()
    R.configure_environment()
    R.lock_database()
    asyncio.run(main(A))
