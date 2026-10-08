"""The Levelog Assistant contact card, sent in reply to a DM of "contact".

The app's "Save to Contacts" opens WhatsApp with "contact" typed to the
Levelog number (as "Turn on Levelog Assistant" does with START). The bot
answers with its own contact card, which WhatsApp saves in one tap — no
contacts permission, no file, no native module in the app.

Any sender may ask: the number is public. Per sender, one card per two
minutes (asking again sooner gets a 👍) and ten a day (server.py,
CONTACT_CARD_COOLDOWN / CONTACT_CARD_DAILY_MAX).

Pure; server.py sends it.
"""

from typing import Any, Dict, Optional

KEYWORD = "contact"
CONTACT_NAME = "Levelog Assistant"
FIRST_NAME = "Levelog"
LAST_NAME = "Assistant"
ORG = "Levelog"
VCF_FILENAME = "levelog-assistant.vcf"


def is_contact_request(body: Optional[str]) -> bool:
    """The whole message is "contact" (any case, surrounding space trimmed)."""
    return str(body or "").strip().lower() == KEYWORD


def digits_of(number: Optional[str]) -> str:
    return "".join(c for c in str(number or "") if c.isdigit())


def display_number(digits: str) -> str:
    """"15165494475" -> "+1 516-549-4475"; other lengths as +<digits>."""
    d = digits_of(digits)
    if len(d) == 11 and d[0] == "1":
        return f"+1 {d[1:4]}-{d[4:7]}-{d[7:]}"
    return f"+{d}" if d else ""


def vcard_text(digits: str) -> str:
    """vCard 3.0, CRLF line endings (iOS is strict)."""
    d = digits_of(digits)
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{LAST_NAME};{FIRST_NAME};;;",
        f"FN:{CONTACT_NAME}",
        f"ORG:{ORG}",
        # waid: WhatsApp opens a chat with this contact from the card.
        f"TEL;type=CELL;type=VOICE;waid={d}:{display_number(d)}",
        "END:VCARD",
    ]
    return "\r\n".join(lines) + "\r\n"


WEBSITE = "https://levelog.com"


def waapi_vcard(digits: str) -> Dict[str, Any]:
    """The `vCard` object for WaAPI's client/action/send-vcard, as its
    OpenAPI spec defines it — WITHOUT `waid`. With it, WhatsApp treats the
    card as a WhatsApp account and offers "Message / View business"; without
    it, the card offers "Add contact", which is the point of Save to
    Contacts."""
    d = digits_of(digits)
    return {
        "internationalnumber": f"+{d}",
        "firstname": FIRST_NAME,
        "lastname": LAST_NAME,
        "displayname": CONTACT_NAME,
        "organization": ORG,
        "website": WEBSITE,
    }


def waapi_succeeded(body: Any) -> bool:
    """WaAPI answers HTTP 200 for failures too: sent only when
    data.status == "success"."""
    if not isinstance(body, dict):
        return False
    # An error in EITHER envelope is a failed action (as WaAPI's own SDK
    # reads it): the outer status, then data.status.
    if str(body.get("status") or "").lower() == "error":
        return False
    data = body.get("data")
    return isinstance(data, dict) and str(data.get("status") or "").lower() == "success"


def waapi_failure(body: Any, err: Optional[str]) -> str:
    """What WaAPI said, for the log: its message and explanation, or the
    HTTP error. Never the chat id or the number."""
    data = body.get("data") if isinstance(body, dict) else None
    if (isinstance(body, dict) and str(body.get("status") or "").lower() == "error"
            and not (isinstance(data, dict) and data.get("status"))):
        bits = [str(body.get(k)) for k in ("message", "explanation") if body.get(k)]
        return "status error" + (": " + " / ".join(bits) if bits else "")
    if isinstance(data, dict) and data.get("status"):
        bits = [str(data.get(k)) for k in ("message", "explanation") if data.get(k)]
        return "status " + str(data.get("status")) + (": " + " / ".join(bits) if bits else "")
    return err or "no response"
