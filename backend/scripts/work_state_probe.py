"""READ-ONLY. What the work-state engine sees on real data, for one job.

    railway run --service Blueview2 --environment production \
        python backend/scripts/work_state_probe.py "588" drywall 3

Prints how much of the logs can be placed and classified, the phrases it cannot
classify (the list to review first), and the answer to the question. It reads
Mongo, calls no vision model, and writes nothing.
"""

import asyncio
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from lib import progress_report, work_state as W  # noqa: E402


async def main(job: str, work: str, level: str) -> None:
    rows = await server.db.projects.find({"is_deleted": {"$ne": True}}, {"name": 1, "address": 1, "company_id": 1,
                                                                         "nyc_bin": 1, "additional_bins": 1}).to_list(2000)
    hits = [p for p in rows if job.lower() in f"{p.get('name')} {p.get('address')}".lower()]
    if len(hits) != 1:
        print(f"{len(hits)} jobs match {job!r}: {[p.get('name') for p in hits][:10]}")
        return
    project, now = hits[0], datetime.now(timezone.utc)
    company = str(project.get("company_id"))
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    start = today - timedelta(days=server.WORK_STATE_DAYS - 1)
    src = await server._report_rows(project, company, start, today, now)
    acts = progress_report._log_activities(src["logbooks"], start, today)
    ev = W.evidence_rows(acts)
    placed = [r for r in ev if r["levels"]]
    single = [r for r in placed if len(r["levels"]) == 1]
    known = [r for r in ev if r["nodes"]]
    print(f"Job: {project.get('name')}  ({start} to {today})")
    print(f"Filed logs: {len(src['logbooks'])}   work phrases: {len(ev)}")
    print(f"  name a level: {len(placed)}   name exactly one level: {len(single)}")
    print(f"  match the sequence: {len(known)}   generic only: {sum(1 for r in known if r['generic'])}")
    print("  levels:", dict(Counter(lv for r in placed for lv in r["levels"]).most_common(20)))
    print("  phrases NOT matched:", Counter(r["work"] for r in ev if not r["nodes"]).most_common(25))
    print("  locations NOT placed:", Counter(r["where"] for r in ev if not r["levels"]).most_common(15))
    pid = str(project["_id"])
    idx = await server.db[server.PHOTO_INDEX].find({"project_id": pid, "kind": "photo"}).to_list(20000)
    photos = W.photo_rows(idx)
    print(f"Photos read: {len(photos)}   filed for exactly one level: {sum(1 for p in photos if len(p['levels']) == 1)}")
    print("  views:", dict(Counter(p.get("view") for p in photos)))
    print(f"Confirmed schedule on file: {bool(src.get('schedule'))}")
    print("-" * 70)
    got = await server._work_state_answer(project, company, work, level, today=today)
    print(W.as_text(got["answer"]) if got["ok"] else got["why"])


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit('usage: work_state_probe.py "<job name or address>" <work> <level>')
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
