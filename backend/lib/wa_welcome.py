"""The Levelog Assistant welcome: the first thing a person ever gets from it.

Sent once per person (server.py _dm_welcome_claim, keyed by user id), in
place of the short intro on their first START; their contact card follows
it. A repeat START gets wa_dm.INTRO_TEXT as before.

ONLY WHAT IS LIVE. Every line names something the DM brain or the DM
handlers do today (server.py _DM_BRAIN_JOB_TOOLS / _DM_BRAIN_EXTRA_TOOLS,
_punch_dm_turn, lib/dm_brain.py SYSTEM_PROMPT):
  * on site / headcount / a sub's days   who_on_site, headcount, sub_attendance
  * daily log, open items                daily_log, open_items
  * DOB / DOT, permits, hearings         dob_status, dot_status, active_permits
  * plan question, "show me" a sheet     query_plan / search_plans, send_sheet
  * project report PDF                   send_report
  * photos start a punch list            _punch_dm_turn
  * add a job / sub / person, a trade,   propose_change, set_sub_trade,
    remind me -- confirmed with "yes"    remind_me
  * English / Spanish / Yiddish, voice   SYSTEM_PROMPT, the DM voice path
  * GC group DOB alerts                  the GC group alerts (lib/wa_gc.py)
Add a line the day a feature ships; take one out the day it goes.

Written for people on a job site, not for techies: plain words, short lines.
Not a wa_dm *_TEXT constant: it opens with their name, not "Levelog".

Pure; server.py sends it.
"""

from __future__ import annotations

from typing import Optional

from lib.punch_link import first_name

_BODY = (
    "You're connected. I'm your Levelog Assistant — text me like you'd text "
    "the office.\n"
    "\n"
    "Ask me about any job:\n"
    "• Who's on site, headcount, how many days a sub worked\n"
    "• The daily log and open items\n"
    "• DOB / DOT violations, permits, hearings\n"
    "• A plan question, or \"show me\" a sheet\n"
    "• A project report PDF (\"send me September for 588\")\n"
    "• Send me photos to start a punch list\n"
    "\n"
    "I can set things up too — \"add a job\", \"add Arkon as framer\", "
    "\"remind me Friday to call the inspector\". Just reply yes to confirm.\n"
    "\n"
    "I also post new DOB violations to each job's GC WhatsApp group.\n"
    "English, Spanish or Yiddish, text or voice note."
)
_CARD_LINE = "Save my contact below 👇"
_STOP_LINE = "Reply STOP anytime to turn me off."


def welcome_text(name: Optional[str], *, with_card: bool = True) -> str:
    """"Hey <first name> 👋" and what they can do. `with_card`: the contact
    card follows, so the text points at it."""
    first = first_name(name or "")
    hey = f"Hey {first} 👋" if first else "Hey there 👋"
    tail = f"{_CARD_LINE}\n{_STOP_LINE}" if with_card else _STOP_LINE
    return f"{hey}\n{_BODY}\n{tail}"
