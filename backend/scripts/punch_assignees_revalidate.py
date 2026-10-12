"""Open walkthroughs: take off any stored assignee who may not be messaged.
DRY RUN unless --i-know (with --reason and --session: the write leaves an
audit row, scripts/prod_guard.py).

    railway run python scripts/punch_assignees_revalidate.py
    railway run python scripts/punch_assignees_revalidate.py --name Yeyzmar \
        --i-know --reason "clear the 8:31 PM walk's checked-in worker" --session <id>

A walk started before #755 can still hold a worker who only checked in
(588, Oct 11 8:31 PM: "electrical → Yeyzmar B Bate (Power Direct)"). The bot
now checks stored names every time it shows them; this clears them at once.
Each name refused by the recipient rules (a user, People, or a sub's punch
contact -- server._recipient_refusal) becomes "?" for its trade, the whole-list
person is cleared, and a walk at the recap goes back to "Who gets what?".
--name limits it to names containing that text. Nothing is sent.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from prod_guard import add_guard_args, audited, check_guard, refuse_legacy_flag  # noqa: E402

NAME = "punch_assignees_revalidate"


async def main_async(a, db=None, server=None) -> int:
    from lib import punch
    if server is None:
        import server
    if db is None:
        db = server.db
    a.apply = check_guard(a)
    db = audited(db, a, NAME)                 # the write leaves an audit row
    want = (a.name or "").strip().lower()
    walks = await db[punch.SESSIONS].find(
        {"status": {"$in": list(server.PUNCH_STATE_OPEN)}}).to_list(5000)
    changed = 0
    for s in walks:
        sets, unset_whole = {}, False
        for t, p in sorted((s.get("assign") or {}).items()):
            if not p or (want and want not in str(p.get("name") or "").lower()):
                continue
            if await server._recipient_refusal(s.get("company_id"), p, store=db) \
                    == server.RECIPIENT_REFUSED:
                sets[f"assign.{t}"] = None
                print(f"  walk {s['_id']} ({s.get('job_name') or '?'}, {s.get('status')}): "
                      f"{t} → {p.get('name')} [{p.get('kind')}] -> ?")
        w = s.get("whole")
        if w and (not want or want in str(w.get("name") or "").lower()) and \
                await server._recipient_refusal(s.get("company_id"), w, store=db) \
                == server.RECIPIENT_REFUSED:
            unset_whole = True
            print(f"  walk {s['_id']}: all → {w.get('name')} [{w.get('kind')}] -> cleared")
        if not sets and not unset_whole:
            continue
        changed += 1
        if unset_whole:
            sets["whole"] = None
        if s.get("status") in ("recap", "due"):
            sets["status"] = "assign"
        if a.apply:
            await db[punch.SESSIONS].update_one({"_id": s["_id"], "status": s.get("status")},
                                                {"$set": sets})
    print(f"{len(walks)} open walk(s); {changed} with a name taken off"
          + ("" if a.apply else " (dry run: nothing written; --i-know to write)"))
    return 0


def main(argv=None, db=None, server=None) -> int:
    refuse_legacy_flag(argv)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="", help="only names containing this (e.g. Yeyzmar)")
    add_guard_args(ap)
    return asyncio.run(main_async(ap.parse_args(argv), db, server))


if __name__ == "__main__":
    sys.exit(main())
