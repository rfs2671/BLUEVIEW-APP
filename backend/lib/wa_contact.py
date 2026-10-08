"""The Levelog Assistant contact card, sent in reply to a DM of "contact".

The app's "Save to Contacts" opens WhatsApp with "contact" typed to the
Levelog number (as "Turn on Levelog Assistant" does with START). The bot
answers with its own contact card, which WhatsApp saves in one tap — no
contacts permission, no file, no native module in the app.

Any sender may ask: the number is public. At most one card per sender per
hour (server.py, CONTACT_CARD_EVERY).

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


def waapi_vcard(digits: str) -> Dict[str, Any]:
    """The `vCard` object for WaAPI's client/action/send-vcard.

    WaAPI documents the action (chatId + a vCard object) but its field list
    could not be read when this was written, so the object carries the usual
    names for each part. A request WaAPI refuses falls back to the .vcf as a
    document (server.py), and the log line says which path went out."""
    d = digits_of(digits)
    return {
        "fullName": CONTACT_NAME,
        "displayName": CONTACT_NAME,
        "firstName": FIRST_NAME,
        "lastName": LAST_NAME,
        "organization": ORG,
        "phoneNumber": f"+{d}",
        "vcard": vcard_text(d),
    }
