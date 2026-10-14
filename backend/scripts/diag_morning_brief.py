"""Why a morning brief did or did not go out, on the live database.

    railway run python scripts/diag_morning_brief.py                         # everyone, today
    railway run python scripts/diag_morning_brief.py --user "meilich" --date 2026-10-14
    railway run python scripts/diag_morning_brief.py --user "meilich" --resend           # dry run
    railway run python scripts/diag_morning_brief.py --user "meilich" --resend --apply   # send it now

For every active opt-in (or the users matching --user), prints:
  1. WHO      the user, role, DM-eligible, same company as the opt-in.
  2. GATES    send_whatsapp_dm's checks, in its order: opt-in, the opt-in's
              phone still the phone on the profile, WhatsApp prefs on -- the
              first that refuses is the reason (refusals are otherwise silent).
  3. TIME     brief time and weekend setting, whether the tick saw it as due
              at any 10-minute tick of the day, Shabbos / Yom Tov quiet.
  4. LEDGER   the day's ledger row (sending / sent / failed + its error /
              skipped_shabbos). Before the fix a "failed" row stopped every
              later tick that day.
  5. LOG      the day's brief_log row (from this fix on): status, reason,
              error, attempts, history.
  6. COMPOSE  builds the brief now (sends nothing) and prints its first lines,
              or the full traceback when building it fails.

--resend --apply sends today's brief now as a proactive DM (window
"<date>-resend", so it never collides with the morning's ledger key) and
logs it as resent. Phone numbers are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import traceback
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

NY = ZoneInfo("America/New_York")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def _safe(v, n=200) -> str:
    return _PHONE.sub("[number]", " ".join(str(v or "").split()))[:n]


def _t(v) -> str:
    if not isinstance(v, datetime):
        return str(v) if v else "-"
    v = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return v.astimezone(NY).strftime("%a %b %d %I:%M:%S %p ET")


async def _users(db, server, a) -> list:
    if a.user:
        rx = {"$regex": "(?i)" + re.escape(a.user)}
        return await db.users.find({"$or": [{"name": rx}, {"full_name": rx}, {"email": rx}],
                                    "is_deleted": {"$ne": True}}).to_list(20)
    optins = await db[server.WA_OPTINS].find({"status": "active"}).to_list(5000)
    out = []
    for o in optins:
        u = await db.users.find_one({"_id": server.to_query_id(str(o.get("user_id")))})
        out.append(u or {"_id": o.get("user_id"), "name": "(user not found)"})
    return out


async def _one(db, server, user: dict, day: date, now: datetime, a) -> None:
    from lib import wa_brief, wa_dm, wa_facts
    uid = str(user.get("_id"))
    print(f"\n=== {_safe(user.get('full_name') or user.get('name'))} ({uid}) "
          f"role={user.get('role')} company={user.get('company_id')}")
    optin = await db[server.WA_OPTINS].find_one({"user_id": uid, "status": "active"})
    print(f"  WHO     eligible={wa_dm.is_dm_eligible(user)}  active opt-in={bool(optin)}"
          + (f"  same company={server.wa_security.same_company(optin.get('company_id') or user.get('company_id'), user.get('company_id'))}"
             if optin else ""))
    reason = await server._dm_refusal_reason(uid, server.MORNING_BRIEF_KIND)
    print(f"  GATES   {'all pass' if reason is None else 'REFUSED: ' + reason + ' -- ' + wa_facts.REASONS.get(reason, '')}")
    settings = await server._brief_settings(uid)
    start = datetime.combine(day, time(0, 0), tzinfo=NY)
    ticks = [start + timedelta(minutes=10 * i) for i in range(144)]
    due = [t for t in ticks if wa_brief.is_due(t.astimezone(timezone.utc), settings["brief_time"],
                                               settings["brief_weekend"])]
    quiet = await server._shabbos_quiet(user.get("company_id"), None,
                                        (due[0] if due else start).astimezone(timezone.utc))
    print(f"  TIME    brief_time={settings['brief_time']} weekend={settings['brief_weekend']}  "
          f"due {len(due)} ticks" + (f" ({due[0]:%I:%M %p}-{due[-1]:%I:%M %p})" if due else " (never)")
          + f"  shabbos/yom tov quiet={bool(quiet)}")
    key = wa_dm.ledger_key(uid, None, server.MORNING_BRIEF_KIND, day.isoformat())
    led = await db[server.WA_LEDGER].find_one({"_id": key})
    print("  LEDGER  " + ("none" if not led else
                          f"{led.get('status')} created {_t(led.get('created_at'))} finished "
                          f"{_t(led.get('finished_at'))} error={_safe(led.get('error'))}"))
    log = await db[wa_facts.BRIEF_LOG].find_one({"_id": f"{uid}:{day.isoformat()}"})
    print("  LOG     " + ("none" if not log else
                          f"{log.get('status')} reason={log.get('reason')} error={_safe(log.get('error'))} "
                          f"attempts={log.get('attempts', 0)} at {_t(log.get('at'))}"))
    for h in (log or {}).get("history") or []:
        print(f"            {_t(h.get('at'))}  {h.get('status')} {h.get('reason') or ''}")
    print("  STATUS  " + _safe(await server._brief_status_for(uid, day.isoformat(), now), 300))
    try:
        text = await server._brief_for_user(user, now)
        print("  COMPOSE " + ("None -- no jobs" if not text else
                              f"{len(text)} chars: " + _safe(text.splitlines()[0], 120)))
    except Exception:
        text = None
        print("  COMPOSE FAILED:\n" + "".join("            " + ln for ln in
                                               traceback.format_exc().splitlines(True)))
    if a.resend and text:
        if not a.apply:
            print("  RESEND  dry run -- add --apply to send it now")
            return
        sent = await server.send_whatsapp_dm(uid, text, kind=server.MORNING_BRIEF_KIND,
                                             window=f"{day.isoformat()}-resend")
        await server._brief_log(uid, user.get("company_id"), day.isoformat(),
                                "resent" if sent else "failed",
                                reason=None if sent else "send_failed", now=now)
        print(f"  RESEND  {'SENT' if sent else 'NOT SENT -- see GATES / LEDGER above'}")


async def main_async(a) -> int:
    import server
    db = server.db
    now = datetime.now(timezone.utc)
    day = date.fromisoformat(a.date) if a.date else now.astimezone(NY).date()
    users = await _users(db, server, a)
    if not users:
        print("No users matched.")
        return 2
    print(f"Morning brief, {day:%a %b %d %Y} -- {len(users)} user(s)")
    for u in users:
        await _one(db, server, u, day, now, a)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", help="name or email (part of it)")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, New York)")
    ap.add_argument("--resend", action="store_true", help="send today's brief now (with --apply)")
    ap.add_argument("--apply", action="store_true", help="with --resend: really send")
    a = ap.parse_args(argv)
    if a.resend and not a.user:
        ap.error("--resend needs --user")
    return asyncio.run(main_async(a))


if __name__ == "__main__":
    sys.exit(main())
