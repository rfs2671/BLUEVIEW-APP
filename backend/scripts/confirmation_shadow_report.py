"""READ-ONLY: what targeted confirmations would have asked, and how often an
admin marked it right.

    PYTHONUTF8=1 python scripts/confirmation_shadow_report.py [--days 14] [--company <id>]

Reads `confirmation_candidates` and `confirmation_events` (MONGO_URL, DB_NAME)
and prints, for the owner:

  * candidates per job per day;
  * the trigger mix;
  * review precision, Correct / (Correct + Wrong), overall and per trigger,
    with its Wilson interval (lib/benchmark_stats) -- and how many are still
    unreviewed, because a precision over three reviews is not a precision;
  * the would-be message text, one per person per day.

Writes nothing. Every count is over fields require_fields() found on the rows.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))

from lib import confirmation_queue as C  # noqa: E402
from probe_helpers import FieldNotInSample, describe, require_fields  # noqa: E402


def summarize(rows, events):
    """The report's numbers, from rows already read. Pure, so it is tested."""
    require_fields(rows, "project_id", "day", "trigger", "target_user_id", "text", "status")
    by_cand = defaultdict(list)
    if events:
        require_fields(events, "candidate_id", "kind", "at")
        for e in events:
            by_cand[str(e["candidate_id"])].append(e)
    per_job_day = Counter((r["project_id"], r["day"]) for r in rows)
    mix = Counter(r["trigger"] for r in rows)
    cur = {str(r["_id"]): C.current(r, by_cand.get(str(r["_id"]), [])) for r in rows}
    overall = C.precision(c["verdict"] for c in cur.values())
    per_trigger = {t: C.precision(cur[str(r["_id"])]["verdict"] for r in rows if r["trigger"] == t)
                   for t in sorted(mix)}
    statuses = Counter(c["status"] for c in cur.values())
    messages = {}
    for r in sorted(rows, key=lambda r: (r["day"], str(r["target_user_id"]), int(r.get("position") or 0))):
        messages.setdefault((r["day"], str(r["target_user_id"])), r["text"])
    return {"rows": len(rows), "per_job_day": per_job_day, "mix": mix, "overall": overall,
            "per_trigger": per_trigger, "statuses": statuses, "messages": messages}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--company", default=None)
    ap.add_argument("--messages", type=int, default=10, help="how many would-be messages to print")
    args = ap.parse_args()
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test")]
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).date().isoformat()
    q = {"day": {"$gte": since}}
    if args.company:
        q["company_id"] = str(args.company)
    rows = list(db[C.COLLECTION].find(q))
    print(describe(rows, "project_id", "day", "trigger", "target_user_id", "text", "status"))
    if not rows:
        print(f"No candidates since {since}. Mode on this deployment: is {C.MODE_ENV} set to shadow?")
        return 0
    events = list(db[C.EVENTS].find({"candidate_id": {"$in": [r["_id"] for r in rows]}}))
    try:
        s = summarize(rows, events)
    except FieldNotInSample as e:
        print(f"NOT COUNTED: {e}")
        return 1
    print(f"\n{s['rows']} candidates since {since} (status now: {dict(s['statuses'])})")
    print("\nPer job per day:")
    for (pid, day), n in sorted(s["per_job_day"].items(), key=lambda kv: (kv[0][1], kv[0][0])):
        print(f"  {day}  {pid}  {n}")
    print("\nTrigger mix:")
    for t, n in s["mix"].most_common():
        print(f"  {t:30s} {n}")
    print(f"\nReview precision, overall: {s['overall']['text']} ({s['overall']['unreviewed']} unreviewed)")
    for t, p in s["per_trigger"].items():
        print(f"  {t:30s} {p['text']} ({p['unreviewed']} unreviewed)")
    print(f"\nWould-be messages (first {args.messages}):")
    for (day, uid), text in list(s["messages"].items())[:args.messages]:
        print(f"\n--- {day} to {uid} ---\n{text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
