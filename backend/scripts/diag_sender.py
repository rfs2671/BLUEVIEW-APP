"""Who is behind a sender name -- and is it the person asking? READ-ONLY.

    railway run python scripts/diag_sender.py --name meilich --email you@company.com

Answers "is 'Meilich Friedman' me?" for the DM brain's "(you)" mark: the
brain says a voice note is "from you" only when its sender is the asker --
the same user id, or the same phone digits as the asker's DM.

Prints, for every place the name appears in your company:
  * the asker's opt-ins  status, phone last 4, chat kind (c.us / lid)
  * users              name, role, phone last 4, SAME AS ASKER yes/no
  * workers            name, sub, phone last 4, SAME AS ASKER
  * WhatsApp sender map  person name, the sender's last 4, SAME AS ASKER
  * group messages     the latest messages whose WhatsApp name matches:
                       sender last 4, SAME AS ASKER, when, voice or text
and the asker's own DM phone last 4. Phone numbers are never printed in
full. Nothing is written.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from lib import wa_dm  # noqa: E402


def _last4(v) -> str:
    d = wa_dm.phone_digits(str(v or ""))
    return f"…{d[-4:]}" if d else "(none)"


async def run(a) -> int:
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        sys.exit("MONGO_URL / DB_NAME are not set — run under `railway run`.")
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    who = a.email.strip()
    me = await db.users.find_one({"email": who.lower(), "is_deleted": {"$ne": True}} if "@" in who
                                 else {"name": {"$regex": "(?i)" + re.escape(who)}, "is_deleted": {"$ne": True}})
    if not me:
        sys.exit("No user with that email or name.")
    company = str(me.get("company_id") or "")
    optins = await db.whatsapp_optins.find({"user_id": str(me["_id"])}).to_list(10)
    mine = {wa_dm.phone_digits(me.get("phone"))[-10:]} - {""}
    for o in optins:
        if o.get("phone"):
            mine.add(wa_dm.phone_digits(o["phone"])[-10:])
        print(f"Opt-in: status {o.get('status')} · phone {_last4(o.get('phone'))} · chat {o.get('chat_kind') or ''}")
    if not optins:
        print("Opt-in: none for this user")
    print(f"Asker: {me.get('name')} (user …{str(me['_id'])[-6:]}), profile phone {_last4(me.get('phone'))}")
    rx = {"$regex": re.escape(a.name), "$options": "i"}

    def same(v) -> str:
        if str(v or "").endswith("@lid"):
            return "a WhatsApp @lid (no phone to compare)"
        d = wa_dm.phone_digits(str(v or ""))[-10:]
        return "SAME AS ASKER" if d and d in mine else "not the asker"

    print("\nUsers:")
    async for u in db.users.find({"company_id": me.get("company_id"), "name": rx,
                                  "is_deleted": {"$ne": True}}).limit(20):
        is_me = str(u["_id"]) == str(me["_id"])
        print(f"  {u.get('name')} · {u.get('role')} · {_last4(u.get('phone'))} · "
              f"{'SAME AS ASKER (same user)' if is_me else same(u.get('phone'))}")
    print("\nWorkers (checked in):")
    async for w in db.workers.find({"name": rx, "is_deleted": {"$ne": True}}).limit(20):
        if str(w.get("company_id") or "") not in (company, "") and w.get("company_id") != me.get("company_id"):
            continue
        print(f"  {w.get('name')} · {w.get('company') or w.get('company_name') or ''} · "
              f"{_last4(w.get('phone'))} · {same(w.get('phone'))}")
    print("\nWhatsApp sender map:")
    async for m in db.whatsapp_sender_map.find({"company_id": company, "person_name": rx}).limit(20):
        print(f"  {m.get('person_name')} · {_last4(m.get('sender_jid'))} · {same(m.get('sender_jid'))}")
    print("\nLatest group messages from that WhatsApp name:")
    async for r in db.whatsapp_messages.find(
            {"company_id": {"$in": [company, me.get("company_id")]}, "sender_name": rx,
             "is_dm": {"$ne": True}}).sort([("created_at", -1)]).limit(a.limit):
        # (sender_name is the WhatsApp name they set; empty when the name is only in People)
        jid = r.get("sender_jid") or r.get("sender") or ""
        print(f"  {r.get('created_at')} · {r.get('sender_name')} · {_last4(jid)} · {same(jid)} · "
              f"{'voice' if r.get('voice') else 'text'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="the sender name, or part of it")
    ap.add_argument("--email", required=True, help="the asker: login email or name")
    ap.add_argument("--limit", type=int, default=10)
    return asyncio.run(run(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
