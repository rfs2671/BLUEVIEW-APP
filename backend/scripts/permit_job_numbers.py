"""dob_logs permit rows and their `job_number`: count (READ-ONLY, default)
and, only where the number is unambiguous, backfill.

WHY. The brief's "mute B<permit>" command looks a permit up by
`dob_logs.job_number`, and the brief's daily expired-permit line groups
permits by it (lib/wa_brief.base_job). `job_number` is written by
server._extract_permit_fields for every permit dataset the sync polls
(tests/test_permit_job_number_is_written.py), but rows written before that
function existed, or by another writer, may lack it. This script says how
many, by source, before anyone relies on it.

    python backend/scripts/permit_job_numbers.py              # count: read-only
    python backend/scripts/permit_job_numbers.py --backfill   # what WOULD be written
    python backend/scripts/permit_job_numbers.py --backfill \\
        --i-know --reason '<why>' --session <id>              # write (audited)

COUNT reads only: count/find with a projection, and one explain() of the
brief's per-project query. No index is created or dropped.

BACKFILL writes `job_number` ONLY where `raw_dob_id` names it exactly
(recover_job_number): "permit:B00736381-I1" -> "B00736381-I1", a BIS
"121234567:PL" -> "121234567". Anything else is listed and left alone - a
guess would put a permit on the wrong job. Every write goes through
prod_guard.audited (actor "script:permit_job_numbers", reason, session).

Reads MONGO_URL / DB_NAME from the environment; never prints them. Prints
no customer data: counts, sources and raw_dob_id SHAPES only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_guard import (  # noqa: E402
    add_guard_args, audited, check_guard, refuse_legacy_flag,
)

NAME = "permit_job_numbers"

#: A job number as DOB writes one: a DOB NOW filing (borough letter, digits,
#: an optional filing suffix: B00736381-I1) or a BIS job (digits).
_JOB = re.compile(r"^(?:[A-Z]\d{6,10}(?:-[A-Z]{1,2}\d{1,3})?|\d{6,10})$")


def shape(raw_dob_id: Any) -> str:
    """The raw_dob_id's SHAPE (never its value): how the row was keyed."""
    s = str(raw_dob_id or "")
    if not s:
        return "none"
    if s.startswith("permit:"):
        rest = s[len("permit:"):]
        return "permit:<job>" if _JOB.match(rest) else "permit:<other>"
    head = s.split(":", 1)[0]
    if ":" in s and _JOB.match(head):
        return "<job>:<work>"
    return "other"


def recover_job_number(raw_dob_id: Any) -> Optional[str]:
    """The job number raw_dob_id names EXACTLY, else None (never a guess)."""
    s = str(raw_dob_id or "")
    if s.startswith("permit:") and _JOB.match(s[len("permit:"):]):
        return s[len("permit:"):]
    head = s.split(":", 1)[0]
    if ":" in s and not s.startswith("permit:") and _JOB.match(head):
        return head
    return None


def _missing(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def tally(rows) -> Dict[Tuple[str, str], Counter]:
    """{(source, raw_dob_id shape): Counter(total, missing, recoverable,
    not_upper, deleted)} over permit rows {dataset, raw_dob_id, job_number,
    is_deleted}."""
    out: Dict[Tuple[str, str], Counter] = {}
    for r in rows:
        key = (str(r.get("dataset") or "unstamped"), shape(r.get("raw_dob_id")))
        c = out.setdefault(key, Counter())
        c["total"] += 1
        if r.get("is_deleted"):
            c["deleted"] += 1
        jn = r.get("job_number")
        if _missing(jn):
            c["missing"] += 1
            if recover_job_number(r.get("raw_dob_id")):
                c["recoverable"] += 1
        elif str(jn) != str(jn).upper():
            c["not_upper"] += 1
    return out


def report(t: Dict[Tuple[str, str], Counter]) -> str:
    cols = ("total", "missing", "recoverable", "not_upper", "deleted")
    lines = [f"{'source':<14}{'raw_dob_id shape':<18}" + "".join(f"{c:>12}" for c in cols)]
    grand = Counter()
    for (src, shp), c in sorted(t.items()):
        grand.update(c)
        lines.append(f"{src:<14}{shp:<18}" + "".join(f"{c[k]:>12}" for k in cols))
    lines.append(f"{'ALL':<14}{'':<18}" + "".join(f"{grand[k]:>12}" for k in cols))
    return "\n".join(lines)


_PERMITS = {"record_type": "permit"}
_FIELDS = {"dataset": 1, "raw_dob_id": 1, "job_number": 1, "is_deleted": 1}


def main(args) -> int:
    mongo_url, db_name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        sys.exit("Set MONGO_URL and DB_NAME in the environment first.")
    from pymongo import MongoClient
    client = MongoClient(mongo_url)
    db = client[db_name]
    rows = list(db.dob_logs.find(_PERMITS, _FIELDS))
    t = tally(rows)
    print(f"dob_logs permit rows: {len(rows)}\n")
    print(report(t))

    # The brief reads a project's rows by project_id (server._brief_job);
    # the renewal / current-job rules then run in memory. Show the plan.
    busiest = db.dob_logs.aggregate([{"$match": _PERMITS},
                                     {"$group": {"_id": "$project_id", "n": {"$sum": 1}}},
                                     {"$sort": {"n": -1}}, {"$limit": 1}])
    top = next(iter(busiest), None)
    if top:
        plan = db.dob_logs.find({"project_id": top["_id"],
                                 "record_type": {"$in": ["permit", "violation"]},
                                 "is_deleted": {"$ne": True}}).explain()
        win = (plan.get("queryPlanner") or {}).get("winningPlan") or {}
        stages = []
        while win:
            stages.append(win.get("stage") + (f"({win['indexName']})" if win.get("indexName") else ""))
            win = win.get("inputStage") or {}
        print(f"\nbrief query plan (busiest project, {top['n']} permit rows): "
              f"{' <- '.join(stages)}")

    if not args.backfill:
        print("\nRead-only: nothing written.")
        return 0
    execute = check_guard(args)
    wdb = audited(db, args, NAME) if execute else db
    todo = [r for r in rows if _missing(r.get("job_number"))]
    fix = [(r["_id"], recover_job_number(r.get("raw_dob_id"))) for r in todo]
    ok = [(i, jn) for i, jn in fix if jn]
    print(f"\nBACKFILL ({'EXECUTE' if execute else 'DRY-RUN'}): {len(todo)} missing, "
          f"{len(ok)} recoverable from raw_dob_id, {len(todo) - len(ok)} left alone "
          f"(raw_dob_id names no job exactly).")
    if execute:
        n = 0
        for _id, jn in ok:
            res = wdb.dob_logs.update_one(
                {"_id": _id, "record_type": "permit",
                 "$or": [{"job_number": None}, {"job_number": ""},
                         {"job_number": {"$exists": False}}]},
                {"$set": {"job_number": jn, "job_number_backfilled": True}})
            n += res.modified_count
        print(f"Wrote job_number on {n} row(s).")
    else:
        print("Nothing written. Add --i-know --reason '<why>' --session <id> to write.")
    client.close()
    return 0


if __name__ == "__main__":
    refuse_legacy_flag()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backfill", action="store_true",
                    help="Report (and with --i-know, write) the recoverable job_numbers.")
    add_guard_args(ap)
    a = ap.parse_args()
    if a.i_know and not a.backfill:
        sys.exit("--i-know only applies with --backfill; the count is read-only.")
    check_guard(a)
    sys.exit(main(a))
