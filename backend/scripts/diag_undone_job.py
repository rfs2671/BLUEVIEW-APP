"""A job added or undone by DM, diagnosed on the live database. READ-ONLY.

    railway run python scripts/diag_undone_job.py menahan
    railway run python scripts/diag_undone_job.py "9 menahan" --since 2026-10-12

Prints, for every project whose name or address matches:
  1. PROJECTS  id, company, name, address, created (when, by whom), and its
               deletion state: is_deleted, marked_for_deletion (who, when).
               A second row with the same address means it was added again.
  2. AUDIT     every audit_logs row on those projects, oldest first, New York
               time: the DM add ("whatsapp_dm_action"), the undo
               ("whatsapp_dm_undo"), app creates and deletes -- who, what they
               said, and what changed.
  3. LISTED    whether each one is in the WhatsApp job lists now
               (ACTIVE_PROJECT_FILTER: neither deleted nor marked).

Phone numbers are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

NY = ZoneInfo("America/New_York")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def _safe(v, n=160) -> str:
    return _PHONE.sub("[number]", " ".join(str(v or "").split()))[:n]


def _t(v) -> str:
    if not isinstance(v, datetime):
        return str(v) if v else "-"
    v = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return v.astimezone(NY).strftime("%a %b %d %I:%M:%S %p ET")


async def _who(db, uid) -> str:
    if not uid:
        return "-"
    import server
    try:
        u = await db.users.find_one({"_id": server.to_query_id(str(uid))},
                                    {"name": 1, "full_name": 1, "role": 1})
    except Exception:
        u = None
    if not u:
        return str(uid)
    return f"{u.get('full_name') or u.get('name') or '?'} ({u.get('role') or '?'}, {uid})"


async def main_async(a) -> int:
    import server
    from lib.project_state import ACTIVE_PROJECT_FILTER
    db = server.db
    rx = {"$regex": "(?i)" + re.escape(a.match)}
    projects = await db.projects.find({"$or": [{"name": rx}, {"address": rx}]}).to_list(50)
    print(f"1. PROJECTS matching {a.match!r}: {len(projects)}")
    for p in sorted(projects, key=lambda p: str(p.get("created_at") or "")):
        print(f"   id={p['_id']} company_id={p.get('company_id')}")
        print(f"     name={_safe(p.get('name'))!r} address={_safe(p.get('address'))!r}")
        print(f"     created {_t(p.get('created_at'))} by {await _who(db, p.get('created_by'))}")
        print(f"     is_deleted={bool(p.get('is_deleted'))} "
              f"marked_for_deletion={bool(p.get('marked_for_deletion'))} "
              f"marked {_t(p.get('marked_at'))} by {await _who(db, p.get('marked_by'))}")
    ids = [str(p["_id"]) for p in projects]

    q = {"resource_id": {"$in": ids}}
    if a.since:
        q["timestamp"] = {"$gte": datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc)}
    rows = await db.audit_logs.find(q).sort([("timestamp", 1)]).to_list(500)
    print(f"\n2. AUDIT rows on those projects: {len(rows)}")
    for r in rows:
        d = r.get("details") or {}
        print(f"   {_t(r.get('timestamp'))}  {r.get('action')}  project={r.get('resource_id')}")
        print(f"     by {await _who(db, r.get('user_id'))} via={d.get('via') or '-'}")
        if d.get("said"):
            print(f"     said: {_safe(d.get('said'))!r}")
        for k in ("action", "before", "after", "undo"):
            if d.get(k) not in (None, "", {}):
                print(f"     {k}: {_safe(d.get(k), 300)}")

    print("\n3. LISTED in the WhatsApp job lists now (ACTIVE_PROJECT_FILTER):")
    for pid in ids:
        live = await db.projects.find_one({"_id": server.to_query_id(pid), **ACTIVE_PROJECT_FILTER},
                                          {"_id": 1})
        print(f"   {pid}: {'LISTED' if live else 'hidden'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("match", help="part of the job's name or address, e.g. menahan")
    ap.add_argument("--since", help="only audit rows on or after this date (YYYY-MM-DD, UTC)")
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
