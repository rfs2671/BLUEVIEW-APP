"""A walker's walkthroughs, as stored. READ-ONLY.

    railway run python scripts/punch_session_diag.py --since 2026-10-11T22:00:00Z
    railway run python scripts/punch_session_diag.py --since 2026-10-11 --walker roy

For each walkthrough (punch_sessions) started since --since: its status,
job, whether the job was asked, and every item -- the number the walker sees,
its words, floor, area, whether its location is complete, its photo (stored
under the job, or "unassigned" when the job was not known yet), its notes,
and the short id of its photo message (what a reply quotes). Then the DM
assistant's own memory for that chat: the current job and an open "Which
job?" menu. Words are cut to 80 characters; phone numbers are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def item_line(it: dict) -> str:
    from lib import punch
    from scripts.wa_provenance import _safe
    loc = punch.location_label(it) or "none"
    ok = "ok" if punch.location_ok(it) else punch.location_state(it.get("floor"), it.get("area"))
    key = str(it.get("photo_key") or "")
    photo = ("no photo" if not key else
             "photo (unassigned: job not known when it came in)" if "/unassigned/" in key
             else "photo")
    notes = "; ".join(_safe(n.get("text"), 40) for n in it.get("notes") or [])
    return (f"    #{it.get('n')} (came in {it.get('captured')}) {_safe(it.get('text'))!r}"
            f" | floor {it.get('floor')} · area {it.get('area')} -> {loc} [{ok}]"
            f" | trade {it.get('trade')} | {photo}"
            f" | msg …{punch.short_message_id(it.get('message_id'))[-6:]}"
            + (f" | {it.get('status')}" if it.get("status") else "")
            + (f" | notes: {notes}" if notes else ""))


async def main_async(a) -> int:
    import server
    from lib import punch, wa_dm
    from scripts.wa_provenance import _safe, _t
    db = server.db
    since = datetime.fromisoformat(a.since.replace("Z", "+00:00"))
    since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    rows = await db[punch.SESSIONS].find({"created_at": {"$gte": since}}).to_list(200)
    users = {}
    for s in sorted(rows, key=lambda r: r.get("created_at")):
        uid = s.get("user_id")
        if uid not in users:
            u = await db.users.find_one({"_id": server.to_query_id(uid)}) or {}
            users[uid] = u.get("name") or u.get("email") or "?"
        if a.walker and a.walker.lower() not in str(users[uid]).lower():
            continue
        items = s.get("items") or []
        print(f"{_t(s.get('created_at'))}  {users[uid]}  status {s.get('status')}"
              f"  job {s.get('job_name') or '(not known)'}"
              f"  job asked: {bool(s.get('job_asked'))}  last: {_t(s.get('updated_at'))}")
        print(f"  {len(items)} item(s); {len(punch.missing_location(items))} without a location"
              + (f"; asking about #{s.get('asking')}" if s.get("asking") else "")
              + (f"; waiting to place a note: {_safe(s.get('pending_note'), 40)!r}"
                 if s.get("pending_note") else ""))
        for it in items:
            print(item_line(it))
        chat = s.get("chat") or ""
        for kind in ("dm_job", "dm_menu"):
            st = await server._dm_state_get(kind, chat)
            if st:
                what = (f"job {st.get('project_id')}" if kind == "dm_job" else
                        f"question {_safe(st.get('question'), 60)!r}")
                print(f"  assistant {kind}: {what} (until {_t(st.get('expires_at'))})")
        print(f"  chat …{wa_dm.phone_digits(chat)[-4:]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", required=True, help="ISO time or day (UTC)")
    ap.add_argument("--walker", default="", help="part of the walker's name or email")
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
