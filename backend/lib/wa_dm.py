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

# ONLY WHAT IS LIVE. The intro names features that exist today and nothing
# planned: GC group alerts (new DOB violations, permit expiry reminders) and
# the confirm-by-DM that picks the GC group. The settings it mentions exist:
# the project's WhatsApp tab (admins). Add a feature here the day it ships.
# The bot is "Levelog Assistant" in every message it sends.
ASSISTANT = "Levelog Assistant"
INTRO_TEXT = (
    "Levelog Assistant here. You're connected. Levelog Assistant posts new "
    "DOB violations and permit expiry reminders to each project's GC WhatsApp "
    "group. If you are your company's main admin, Levelog Assistant will ask "
    "you here which group that is. Admins can turn these alerts on or off in "
    "the app: open the project, then WhatsApp. Reply STOP to turn this off."
)
# EVERY START GETS A REPLY. Each refusal says, in plain words, what to do.
# The one deliberately vague line is NOT_ELIGIBLE_TEXT: an unknown number and
# a role that may not get alerts read the same, so a stranger cannot use
# START to learn who has an account or what role they hold.
NOT_ELIGIBLE_TEXT = (
    "Levelog Assistant here. Levelog Assistant isn't available for this "
    "number. If you use Levelog, open Integrations in the app and tap Turn on "
    "Levelog Assistant."
)
STOP_CONFIRM_TEXT = (
    "Levelog Assistant here. You won't get any more WhatsApp updates. "
    "Reply START to turn them back on."
)
# The sender arrived as a WhatsApp privacy id (@lid), not a phone number, no
# phone could be found for it, and the message carried no connect code.
NEED_APP_TEXT = (
    "Levelog Assistant here. WhatsApp didn't share your phone number with us, "
    "so we can't tell who you are yet. Open Integrations in the Levelog app, "
    "tap Turn on Levelog Assistant, and send the message it prepares."
)
CODE_EXPIRED_TEXT = (
    "Levelog Assistant here. This link expired. Tap Turn on Levelog Assistant "
    "again in the app."
)
WRONG_PHONE_TEXT = (
    "Levelog Assistant here. Send this from the phone number saved on your "
    "Levelog profile, or update that number in Settings first."
)
PHONE_MISSING_TEXT = (
    "Levelog Assistant here. Add your mobile number in Settings in the Levelog "
    "app, then tap Turn on Levelog Assistant again."
)
PHONE_SHARED_TEXT = (
    "Levelog Assistant here. This number is on more than one Levelog account, "
    "so Levelog Assistant can't be turned on. Contact Levelog support."
)
TRY_AGAIN_TEXT = (
    "Levelog Assistant here. Something went wrong on our side. Please send "
    "START again in a minute."
)

# GC group confirm-by-DM (lib/wa_gc.py, server.py _gc_*).
GC_CONFIRM_TEXT = (
    "Levelog Assistant here. Use '{group}' as the GC group for {project}? "
    "Levelog Assistant will post new DOB violations and permit expiry "
    "reminders there. Reply 1 Yes / 2 No"
)
GC_CONFIRMED_TEXT = (
    "Done. Levelog Assistant will post DOB alerts for {project} in '{group}'."
)
GC_DECLINED_TEXT = (
    "OK. Pick the GC group for {project} in the Levelog app: open the project, "
    "then WhatsApp."
)
GC_GONE_TEXT = (
    "That group is no longer linked to {project}, so nothing was changed. "
    "Pick the GC group in the Levelog app: open the project, then WhatsApp."
)

_START_WORDS = frozenset({"start"})
_STOP_WORDS = frozenset({"stop", "parar"})
_PUNCT = re.compile(r"[^\w]+", re.UNICODE)


# The connect code the app puts after START: "START K7Q2MX". Six characters
# of base32 (no 0/1/8/9), so it survives being read aloud or retyped.
CONNECT_CODE_LEN = 6
_CODE_RE = re.compile(r"^[A-Z2-7]{%d}$" % CONNECT_CODE_LEN)


def parse_start_code(body: Optional[str]) -> Optional[str]:
    """The connect code in "START <code>", upper-cased, else None."""
    parts = str(body or "").strip().split()
    if len(parts) != 2 or _PUNCT.sub("", parts[0]).lower() not in _START_WORDS:
        return None
    code = _PUNCT.sub("", parts[1]).upper()
    return code if _CODE_RE.match(code) else None


def parse_dm_command(body: Optional[str]) -> Optional[str]:
    """'start' or 'stop' when the WHOLE message is the keyword, else None.

    "start" inside a sentence is not a command — "start the pour at 7" must
    not subscribe anyone. Punctuation and case are ignored, so "Stop." works.
    "START <connect code>" (what the app's link prepares) is a start too.
    """
    if not body:
        return None
    if parse_start_code(body):
        return "start"
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
    """The chat id for a phone. A value that is already a JID (…@c.us,
    …@lid) is returned unchanged: a reply goes back to the chat the message
    came from, and rebuilding `<digits>@c.us` from a @lid sender's digits
    names a chat that does not exist — the reply vanishes."""
    raw = str(phone or "").strip()
    if "@" in raw:
        return raw
    return f"{phone_digits(raw)}@c.us"


def jid_kind(jid: Optional[str]) -> str:
    """'lid' for a WhatsApp privacy id, 'c.us' for a phone-number id, '' else.
    A bare number is treated as a phone."""
    j = str(jid or "").strip().lower()
    if j.endswith("@lid"):
        return "lid"
    if j.endswith("@c.us") or j.endswith("@s.whatsapp.net"):
        return "c.us"
    return "c.us" if phone_digits(j) and "@" not in j else ""


# Where a WhatsApp-Web payload may carry the sender's real number when the
# sender itself is a @lid. NOT VERIFIED against WaAPI (its docs are not
# reachable from here); every name is tried and the first phone-shaped value
# wins. A value that is itself a @lid is not a phone and is skipped.
PHONE_PAYLOAD_KEYS = ("senderPn", "sender_pn", "participantPn",
                      "participant_pn", "phoneNumber", "phone_number", "pn")


def phone_from_payload(obj, depth: int = 0) -> str:
    """Digits of a phone number named under one of PHONE_PAYLOAD_KEYS anywhere
    in `obj`, else ''."""
    if depth > 6 or obj is None:
        return ""
    if isinstance(obj, dict):
        for key in PHONE_PAYLOAD_KEYS:
            v = obj.get(key)
            if isinstance(v, dict):
                v = v.get("_serialized") or v.get("user")
            if isinstance(v, str) and v.strip() and jid_kind(v) != "lid":
                d = phone_digits(v)
                if 10 <= len(d) <= 15:
                    return d
        for v in obj.values():
            got = phone_from_payload(v, depth + 1)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj[:20]:
            got = phone_from_payload(v, depth + 1)
            if got:
                return got
    return ""


_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"

# A connect code lives this long, and is good for ONE START.
CONNECT_CODE_TTL_SECONDS = 15 * 60


def new_connect_code() -> str:
    """A random connect code. Stored server-side with its owner, a 15-minute
    expiry and a used flag (server.py whatsapp_connect_link); the START that
    carries it is what ties a WhatsApp chat — even a @lid one whose number
    WhatsApp withholds — to the account that asked for it."""
    import secrets
    return "".join(secrets.choice(_B32) for _ in range(CONNECT_CODE_LEN))


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
