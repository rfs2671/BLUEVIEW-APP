"""What a job's own filed logs say about its schedule so far, and how well next
week's crews could have been forecast from them. Read-only.

    railway run python scripts\\site_brain_report.py --project 588 [--end 2026-11-19]

Prints, for one project:
  * each kind of work: worker-days, days worked, usual crew, separate visits,
    working days away, and whether it is on site now  (lib/site_history.py)
  * where the record shows time going: return trips, one-man crews, working
    days with nobody, days at under half the usual head count
  * the forecast for the next five working days, per kind of work, with its
    range                                              (lib/crew_lookahead.py)
  * THE SCORECARD: the same forecast replayed over the job's past weeks, each
    made from the days before it only, and how often the range held

Read-only like real_report_dry_run.py: every database write is blocked before
the application is imported. Daily logs are read the way the progress report
reads them (the filed head of each amendment chain; drafts and withdrawn logs
never count). No model is called and nothing is stored.
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


async def main(a):
    import server
    from lib import crew_lookahead as LA
    from lib import progress_report as PR
    from lib import project_report as base
    from lib import site_history as SH
    project = await R.find_project(server, a.project, a.company)
    pid = str(project.get("_id"))
    docs = await server.db.logbooks.find(
        {"project_id": pid, "log_type": "daily_jobsite", "is_deleted": {"$ne": True}},
        {"date": 1, "data.activities": 1, "data.weather": 1, "is_amendment": 1, "parent_logbook_id": 1, "status": 1,
         "is_locked": 1, "log_type": 1, "created_at": 1, "updated_at": 1, "amendment_reason": 1}).to_list(6000)
    heads = []
    for chain in server.collapse_amendment_chains(docs):
        head = chain["head"]
        if server.logbook_is_filed(head) and not server.logbook_is_withdrawn(head):
            heads.append({**head, "_chain_length": chain["length"]})
    logs = PR.effective_logs(heads)["items"]
    rows = PR._log_activities(logs, date(1900, 1, 1), date(2100, 1, 1))
    if not rows:
        sys.exit(f"{project.get('name')}: no filed daily log has a crew row. Nothing to read.")
    end = date.fromisoformat(a.end) if a.end else max(r["date"] for r in rows)
    weather = {base._d(lg.get("date")): (lg.get("data") or {}).get("weather") for lg in logs}
    print(f"project: {project.get('name')} | company {project.get('company_name') or project.get('company_id')} | id {pid}")
    print(f"filed daily logs read: {len(logs)} ({len(docs)} documents before amendment chains were resolved)")
    s = SH.summary(rows, end)
    print(f"\nTHE JOB SO FAR, {s['first']} to {s['last']}: {s['worked_days']} worked days, "
          f"{s['worker_days_all']:g} worker-days logged ({s['worker_days_installing']:g} on installing work)")
    print(f"  {'kind of work':<28}{'share':>6}{'w-days':>8}{'days':>6}{'crew':>6}{'visits':>7}{'away':>6}  status")
    for t in s["trades"]:
        st = "on site" if t["on_site"] else f"last here {t['since_last']} working days ago"
        print(f"  {t['label'][:27]:<28}{t['share']:>6.0%}{t['worker_days']:>8g}{t['days']:>6}{t['crew']:>6g}"
              f"{t['visit_count']:>7}{t['away']:>6}  {st}")
    print("\nWHERE THE RECORD SHOWS TIME GOING (counts only; the logs do not say why)")
    for f in SH.time_lost(rows, end, weather) or [{"text": "nothing above the thresholds"}]:
        print(f"  - {f['text']}")
    f = LA.predict(rows, end)
    print(f"\nNEXT {f['horizon']} WORKING DAYS ({f['from']} to {f['to']}), worker-days per kind of work")
    if not f["ranged"]:
        print(f"  no ranges yet: {f['misses']} past forecasts to learn from, {LA.MIN_MISSES} needed")
    for t in f["trades"]:
        rng = f"{t['low']:g} to {t['high']:g}" if t["low"] is not None else "no range yet"
        print(f"  {t['label'][:27]:<28} about {t['expected']:>5g}   range {rng}")
    for h in (5, 10):
        sc = LA.score(rows, end, horizon=h)
        if not sc["tries"]:
            print(f"\nSCORECARD, {h} working days ahead: not enough history to replay")
            continue
        print(f"\nSCORECARD, {h} working days ahead: the range held {sc['hits']} of {sc['tries']} times "
              f"({sc['rate']:.0%}) over {sc['weeks']} replayed periods.")
        print(f"  At this sample the true rate could be as low as {sc['floor']:.0%} (95% confidence). "
              f"Target {sc['target']:.0%}.")
        print(f"  Median range width {sc['width']:g} worker-days; median miss of the expected figure "
              f"{sc['miss_share']:g}.")
        print(f"  Labour from kinds of work it had not seen coming: {sc['unseen']:.0f} of {sc['labour']:.0f} worker-days.")
        for c in [c for c in sc["cases"] if not c["hit"]]:
            print(f"    missed {c['as_of']} {c['key']:<18} range {c['low']:g}-{c['high']:g}, actual {c['actual']:g}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--company", default=None)
    ap.add_argument("--end", default=None, help="read the record up to this day (YYYY-MM-DD); default: its last day")
    A = ap.parse_args()
    R.configure_environment()
    R.lock_database()
    asyncio.run(main(A))
