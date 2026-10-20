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
    others = []
    if a.learn_from != "none":
        q = {"is_deleted": {"$ne": True}}
        if a.learn_from == "company":
            q["company_id"] = server._company_id_filter(str(project.get("company_id")))
        peers = [str(p["_id"]) for p in await server.db.projects.find(q, {"_id": 1}).to_list(5000) if str(p["_id"]) != pid]
        for peer in peers:
            rows = await server.db.logbooks.find({"project_id": peer, "log_type": "daily_jobsite",
                                                  "is_deleted": {"$ne": True}}).sort([("date", 1)]).to_list(2000)
            if rows:
                others.append(rows)
        print(f"learning from {a.learn_from}: {', '.join(['projects with logs', str(len(others))])}")
    res = BT.backtest(logs, project_id=pid, top=a.top, structural_system=project.get("structural_system"),
                      other_projects=others)
    o = res["overall"]
    print(f"daily logs read: {', '.join([str(x.get('date'))[:10] for x in logs[:1]] + ['...'] + [str(x.get('date'))[:10] for x in logs[-1:]])}")
    print(f"\ncrew-days replayed: {o['crew_days']}   activities logged: {o['actual']}   (first {res['top']} chips)")
    print(f"  baseline      {BT.rate(o['baseline_hits'], o['actual'])}  ({o['baseline_hits']} of {o['actual']})")
    print(f"  personalized  {BT.rate(o['personalized_hits'], o['actual'])}  ({o['personalized_hits']} of {o['actual']})")
    print("\nby trade:")
    for trade, s in sorted(res["by_trade"].items()):
        print(f"  {trade:<28} days {s['crew_days']:>3}  baseline {BT.rate(s['baseline_hits'], s['actual']):>5}  "
              f"personalized {BT.rate(s['personalized_hits'], s['actual']):>5}")
    ev = res["events"]
    print("\nBY KIND OF ACTIVITY (share of the activities really logged found in the first N chips)")
    for kind in (None, "continuing", "new"):
        h = BT.hit_rates(ev, kind)
        name = {None: "all", "continuing": "continuing (logged on the crew's previous day)",
                "new": "new (not logged on the crew's previous day)"}[kind]
        print(f"  {name}: {h['n']} activities")
        for label, key in (("baseline", "baseline_pos"), ("crew history (shelved)", "personalized_pos"),
                           ("LEARNED next-activity, all lifted", "learned_pos"),
                           ("LEARNED, first 2 kept", "learned_keep2_pos")):
            cells = "  ".join(f"@{n}: {BT.rate(h[f'{key}@{n}'], h['n']):>4}" for n in (4, 6, 8))
            print(f"      {label:<38} {cells}")
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "activity_backtest.txt"), "w", encoding="utf-8") as f:
        for r in res["rows"]:
            f.write(f"{r['date']} | {r['trade']} | history {r['had_history']} | actual {r['actual']} | "
                    f"baseline {r['baseline_top']} ({r['baseline_hits']}) | personalized {r['personalized_top']} "
                    f"({r['personalized_hits']})\n")
    with open(os.path.join(out, "activity_backtest_misses.txt"), "w", encoding="utf-8") as f:
        f.write("activities NOT in the first chips of the LEARNED (keep-2) ranking\n")
        f.write("date | trade | actual (kind) | position in baseline / crew history / learned / learned-keep-2 (0 = first) | the crew's previous day\n")
        for e in ev:
            if e["learned_keep2_pos"] is None or e["learned_keep2_pos"] >= res["top"]:
                f.write(f"{e['date']} | {e['trade']} | {e['label']} ({e['kind']}) | {e['baseline_pos']} / "
                        f"{e['personalized_pos']} / {e['learned_pos']} / {e['learned_keep2_pos']} | {', '.join(e['previous']) or '-'}\n")
    print(f"\nwrote {os.path.join(out, 'activity_backtest.txt')} and activity_backtest_misses.txt")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backtest the activity-chip ranking on a project's filed logs.")
    ap.add_argument("--project", required=True)
    ap.add_argument("--company", default="")
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--learn-from", choices=["none", "company", "all"], default="company",
                    help="whose filed logs teach what comes next: this company's other projects (default), "
                         "every company's (aggregate counts only), or none (this project's own earlier days)")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "..", "docs", "samples", "real"))
    A = ap.parse_args()
    R.configure_environment()
    R.lock_database()
    asyncio.run(main(A))
