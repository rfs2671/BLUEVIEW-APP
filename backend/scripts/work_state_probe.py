"""READ-ONLY. What the work-state engine sees on real data, for one job.

    railway run --service Blueview2 --environment production \
        python backend/scripts/work_state_probe.py "588" drywall 3

Prints how much of the logs can be placed and classified, the phrases it cannot
classify (the list to review first), and the answer to the question. It reads
Mongo, calls no vision model, and writes nothing.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from probe_helpers import require_fields  # noqa: E402
from lib import progress_report, work_state as W  # noqa: E402


async def main(job: str, work: str, level: str) -> None:
    rows = await server.db.projects.find({"is_deleted": {"$ne": True}}, {"name": 1, "address": 1, "company_id": 1,
                                                                         "nyc_bin": 1, "additional_bins": 1}).to_list(2000)
    require_fields(rows, "name", "address", "company_id")
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
    pid = str(project["_id"])
    idx = await server.db[server.PHOTO_INDEX].find({"project_id": pid, "kind": "photo"}).to_list(20000)
    c = W.coverage(W.evidence_rows(acts), W.photo_rows(idx))
    print(f"Job: {project.get('name')}  ({start} to {today})")
    print(f"Filed logs: {len(src['logbooks'])}   work phrases: {c['phrases']}")
    print(f"  name a level: {c['name_a_level']}   name exactly one level: {c['name_one_level']}")
    print(f"  match the sequence: {c['match_sequence']}   generic only: {c['generic_only']}")
    print("  levels:", c["levels"])
    print("  phrases NOT matched:", c["not_matched"])
    print("  locations NOT placed:", c["not_placed"])
    print(f"Photos read: {c['photos']}   filed for exactly one level: {c['photos_one_level']}")
    print("  views:", c["photo_views"])
    print(f"Confirmed schedule on file: {bool(src.get('schedule'))}")
    print("-" * 70)
    got = await server._work_state_answer(project, company, work, level, today=today)
    print(W.as_text(got["answer"]) if got["ok"] else got["why"])


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit('usage: work_state_probe.py "<job name or address>" <work> <level>')
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
