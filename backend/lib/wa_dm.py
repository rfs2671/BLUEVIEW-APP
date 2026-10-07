"""WhatsApp direct messages: opt-in, eligibility, the ledger key, pacing.

The pure half. server.py supplies the database reads and the HTTP call; the
rules live here so they can be read and tested without either.

── THE RULE ─────────────────────────────────────────────────────────────────

No proactive direct message to any phone without an ACTIVE opt-in record.
It is enforced inside send_whatsapp_message itself (server.py), so no caller
can route around it. A direct message is allowed for exactly two reasons:

  1. A REPLY. The person messaged the bot in the last few minutes. Their own
     inbound message opens a short reply window (REPLY_WINDOW_SECONDS, at most
     REPLY_WINDOW_MAX_SENDS sends); it is not a flag a caller can pass.
  2. A PROACTIVE send to a phone whose opt-in record is active. Every one of
     these is written to the notification ledger by the send function, keyed
     so the same notification cannot go twice.

── WHO MAY OPT IN ───────────────────────────────────────────────────────────

Company admins and PMs (shown in the app as Site Manager) of that company.
Never CP, superintendent, or workers. Opt-in happens by the person messaging
START from the phone on their user record; STOP or PARAR ends it.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, Optional

# Roles allowed to opt in to proactive direct messages. Compared after strip()
# and lower(), like every other role comparison in server.py.
DM_ELIGIBLE_ROLES = frozenset({"admin", "pm"})
DM_NEVER_ROLES = frozenset({"cp", "superintendent", "worker", "site_device",
                            "demo"})

REPLY_WINDOW_SECONDS = 10 * 60
REPLY_WINDOW_MAX_SENDS = 4

# Seconds between two direct messages from this process. WhatsApp-Web
# gateways are banned for bursts to many individual chats; groups are not
# paced (unchanged behaviour).
DM_MIN_INTERVAL_SECONDS = 2.0
DM_SEND_ATTEMPTS = 3
DM_BACKOFF_SECONDS = (1.0, 2.0, 4.0)

INTRO_TEXT = (
    "Blueview here. You'll get: chat summaries for your projects, alerts when "
    "someone needs your answer, inspection and permit reminders, and new DOB "
    "violations. Change settings in the app. Reply STOP to turn off."
)
NOT_ELIGIBLE_TEXT = (
    "Blueview here. WhatsApp updates aren't available for this number."
)
STOP_CONFIRM_TEXT = (
    "Blueview here. You won't get any more WhatsApp updates. "
    "Reply START to turn them back on."
)

_START_WORDS = frozenset({"start"})
_STOP_WORDS = frozenset({"stop", "parar"})
_PUNCT = re.compile(r"[^\w]+", re.UNICODE)


def parse_dm_command(body: Optional[str]) -> Optional[str]:
    """'start' or 'stop' when the WHOLE message is the keyword, else None.

    "start" inside a sentence is not a command — "start the pour at 7" must
    not subscribe anyone. Punctuation and case are ignored, so "Stop." works.
    """
    if not body:
        return None
    word = _PUNCT.sub("", body.strip()).lower()
    if word in _START_WORDS:
        return "start"
    if word in _STOP_WORDS:
        return "stop"
    return None


def norm_role(role: Optional[str]) -> str:
    return str(role or "").strip().lower()


def is_dm_eligible(user: Optional[dict]) -> bool:
    """A live user of a company, in an eligible role."""
    if not user or user.get("is_deleted"):
        return False
    if not str(user.get("company_id") or "").strip():
        return False
    role = norm_role(user.get("role"))
    return role in DM_ELIGIBLE_ROLES and role not in DM_NEVER_ROLES


# What the Integrations screen shows, one value per situation. Each blocked
# state names the one thing the user must fix; the copy lives in the app
# (frontend/src/utils/whatsappConnect.js), keyed by these strings.
CONNECT_NOT_ELIGIBLE = "not_eligible"
CONNECT_UNAVAILABLE = "unavailable"          # no bot number configured
CONNECT_PHONE_MISSING = "phone_missing"
CONNECT_PHONE_SHARED = "phone_shared"        # START would be refused
CONNECT_RECONNECT = "reconnect_needed"       # opted in from an old phone
CONNECT_CONNECTED = "connected"
CONNECT_NOT_CONNECTED = "not_connected"

# The states in which pressing Connect can work.
CONNECT_ACTIONABLE = frozenset({CONNECT_NOT_CONNECTED, CONNECT_RECONNECT})


def connect_state(*, eligible: bool, bot_configured: bool, has_phone: bool,
                  phone_shared: bool, optin_status: str) -> str:
    """The one state the Integrations screen shows. Ordered: a state is only
    reported when every state above it is clear, so the user is told the
    first thing to fix, not the last.

    `phone_shared` is START's own refusal rule seen from the screen: if any
    other live account carries this number, START cannot tell whose it is
    and opts nobody in. `optin_status` is the latest opt-in row's status,
    with "phone_changed" when that row is active for a phone no longer on
    the user's record."""
    if not eligible:
        return CONNECT_NOT_ELIGIBLE
    if not bot_configured:
        return CONNECT_UNAVAILABLE
    if not has_phone:
        return CONNECT_PHONE_MISSING
    if phone_shared:
        return CONNECT_PHONE_SHARED
    if optin_status == "phone_changed":
        return CONNECT_RECONNECT
    if optin_status == "active":
        return CONNECT_CONNECTED
    return CONNECT_NOT_CONNECTED


def phone_digits(chat_or_phone: Optional[str]) -> str:
    """Digits of a phone or a JID ('15551234567@c.us' -> '15551234567')."""
    head = str(chat_or_phone or "").split("@", 1)[0]
    return re.sub(r"\D", "", head)


def is_group_chat(chat_id: Optional[str]) -> bool:
    return str(chat_id or "").endswith("@g.us")


def dm_chat_id(phone: str) -> str:
    return f"{phone_digits(phone)}@c.us"


def ledger_key(user_id: str, project_id: Optional[str], kind: str,
               window: str) -> str:
    """The dedupe key: one notification of `kind` for this user and project
    per `window` (e.g. '2026-10-07' for daily, '2026-W41' for weekly)."""
    return ":".join([str(user_id or "-"), str(project_id or "-"),
                     str(kind or "-"), str(window or "-")])


def adhoc_window(message: str, day: str) -> str:
    """Window for a proactive send that gave no key: the same text to the
    same person on the same day goes once."""
    digest = hashlib.sha256((message or "").encode("utf-8")).hexdigest()[:16]
    return f"{day}:{digest}"


def is_transient(status_code: Optional[int], exc: Optional[BaseException]) -> bool:
    """Worth retrying: no response at all, 408/425/429, or any 5xx."""
    if exc is not None:
        return True
    if status_code is None:
        return True
    return status_code in (408, 425, 429) or 500 <= status_code < 600


def backoff_for(attempt: int, schedule: Iterable[float] = DM_BACKOFF_SECONDS) -> float:
    sched = list(schedule)
    if not sched:
        return 0.0
    return sched[min(attempt, len(sched) - 1)]
