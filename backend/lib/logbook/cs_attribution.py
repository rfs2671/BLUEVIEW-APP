"""Was the person who signed this log the registered CS for this project?

THE TWO RECORDS NEVER MET. `cs_registrations` holds the DOB designation --
full name, licence number, NYC.ID -- created by an ADMIN for a PROJECT.
`users` holds the account that signs. Nothing connected them, so a signature on
a BC 3301.13.13 log could not be tied to the licence that gives it weight.

Bulletin 2024-007 sec V.7 requires that individuals who sign electronic records
be VERIFIED. It says nothing about licences -- the word does not appear in it --
so this is not the bulletin's requirement being met. It is the question the
document should be able to answer about itself.

── IT NEVER BLOCKS ─────────────────────────────────────────────────────────────

A missing registration must never stop a superintendent recording his visit.
The visit happened; the obligation to record it does not wait on an admin
typing a form. Everything here DESCRIBES; nothing refuses.

── FOUR STATES, AND THE FOURTH IS THE POINT ────────────────────────────────────

    MATCHED_ACCOUNT      the signer's user id is on the registration
    MATCHED_LICENCE      no id link, but the licence numbers agree
    NOT_REGISTERED_CS    a registration exists and the signer is not it
    NO_REGISTRATION      none exists -- NOTHING WAS CHECKED

An absent registration is NOT evidence the signer is wrong. Collapsing the
fourth into the third would print a finding against a superintendent because
an admin never filled a form -- the shape that produced 285 false compliance
flags, landing on the one document where a false finding costs most.

MATCHED_ACCOUNT and MATCHED_LICENCE are also kept apart deliberately. "Bound to
this account" and "the numbers a human typed twice agree" are different
strengths of evidence, and this codebase has been bitten four times by
string-keyed identity -- _norm_key's doubled space printing one man twice, four
spellings of which sub employs a worker, "Companies 1", and _worker_company
existing at all. Reporting them as one claim would make the stronger statement
on the weaker basis.

── RESOLVED AGAINST THE LOG'S OWN DATE ─────────────────────────────────────────

Same rule as item_applies and the pre-shift affirmation overlay: a filed
document must not change what it says because the world moved on.

AND AN HONEST LIMIT, stated rather than papered over. A registration has
`is_active` -- a CURRENT-STATE BOOLEAN -- plus created_at, updated_at, and
deleted_at on soft-delete. It has NO validity period. So of the four historical
questions, three are answerable and one is not:

    registered AFTER the log date      answerable -- created_at is later
    registered before, still active    answerable
    registered before, since DELETED   answerable -- deleted_at bounds it
    registered before, since merely
      DEACTIVATED (is_active False)    NOT ANSWERABLE. Only the delete path
                                       stamps a timestamp; switching a
                                       registration off erases when it was on.

The unanswerable case reports that it could not be determined rather than
guessing. Adding `deactivated_at` would close it and is recorded as not built.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

MATCHED_ACCOUNT = "matched_account"
MATCHED_LICENCE = "matched_licence"
NOT_REGISTERED_CS = "not_registered_cs"
NO_REGISTRATION = "no_registration"
REGISTERED_LATER = "registered_later"
UNDETERMINED = "undetermined"


def normalise_licence(value) -> str:
    """A licence number reduced to a comparison key.

    Mirrors what register_construction_superintendent already stores as
    `license_number_normalized`, so the two sides of the comparison are built
    the same way rather than nearly the same way.
    """
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _as_date(value) -> Optional[str]:
    """A YYYY-MM-DD string from a datetime or a string, or None."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.date().isoformat()
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else None


def attribute_signer(signer, registration, log_date=None) -> Dict:
    """What this document can say about who signed it.

    `signer` is the user row (or the log's stored signer block); `registration`
    is the project's CS registration, or None. Returns:

        {"state", "registered_name", "registered_licence", "signer_name",
         "checked_on"}

    PURE. No I/O, so the rule is unit-testable and the caller owns the reads.
    """
    signer = signer if isinstance(signer, dict) else {}
    signer_name = (signer.get("name") or signer.get("full_name")
                   or signer.get("printed_name") or "")

    if not isinstance(registration, dict) or not registration:
        # NOTHING WAS CHECKED. Not a finding against anybody.
        return {"state": NO_REGISTRATION, "registered_name": None,
                "registered_licence": None, "signer_name": signer_name,
                "checked_on": log_date}

    reg_name = registration.get("full_name")
    reg_lic = registration.get("license_number")

    # ── Did the registration even exist on the log's date? ──────────────────
    day = _as_date(log_date)
    created = _as_date(registration.get("created_at"))
    if day and created and created > day:
        # A registration that postdates the entry cannot describe who was the
        # CS when it was signed. Saying "matched" here would be an anachronism.
        return {"state": REGISTERED_LATER, "registered_name": reg_name,
                "registered_licence": reg_lic, "signer_name": signer_name,
                "checked_on": day}

    deleted = _as_date(registration.get("deleted_at"))
    if day and deleted and deleted < day:
        return {"state": NO_REGISTRATION, "registered_name": None,
                "registered_licence": None, "signer_name": signer_name,
                "checked_on": day}

    # A registration switched off without being deleted carries no timestamp,
    # so on a PAST date it cannot be said whether it was active. Today's logs
    # are unaffected: is_active is current and the date is now.
    if (not registration.get("is_active")
            and not registration.get("deleted_at")
            and day and created and created < day):
        return {"state": UNDETERMINED, "registered_name": reg_name,
                "registered_licence": reg_lic, "signer_name": signer_name,
                "checked_on": day}

    # ── Who signed ─────────────────────────────────────────────────────────
    signer_id = str(signer.get("id") or signer.get("_id") or "")
    reg_uid = str(registration.get("user_id") or "")
    if signer_id and reg_uid and signer_id == reg_uid:
        return {"state": MATCHED_ACCOUNT, "registered_name": reg_name,
                "registered_licence": reg_lic, "signer_name": signer_name,
                "checked_on": day}

    signer_lic = normalise_licence(
        signer.get("cs_license_number") or signer.get("license_number"))
    reg_key = (registration.get("license_number_normalized")
               or normalise_licence(reg_lic))
    if signer_lic and reg_key and signer_lic == normalise_licence(reg_key):
        # CORROBORATION, NOT BINDING. Two humans typed the same string; that is
        # weaker than an account link and is reported as its own state.
        return {"state": MATCHED_LICENCE, "registered_name": reg_name,
                "registered_licence": reg_lic, "signer_name": signer_name,
                "checked_on": day}

    return {"state": NOT_REGISTERED_CS, "registered_name": reg_name,
            "registered_licence": reg_lic, "signer_name": signer_name,
            "checked_on": day}


def attribution_sentence(result) -> str:
    """One sentence for the document, in the app's own voice.

    A FACT, NEVER AN ACCUSATION. There are legitimate reasons a signer is not
    the registered CS -- and from 2027-01-01 the alternate licensed
    superintendent is one of them -- so the sentence states what the system
    knows and stops.
    """
    r = result if isinstance(result, dict) else {}
    who = str(r.get("signer_name") or "").strip() or "the superintendent"
    reg = str(r.get("registered_name") or "").strip()
    lic = str(r.get("registered_licence") or "").strip()
    state = r.get("state")

    if state == MATCHED_ACCOUNT or state == MATCHED_LICENCE:
        by = ("account" if state == MATCHED_ACCOUNT else "licence number")
        tail = f" (licence {lic})" if lic else ""
        return (f"Signed by {who}, the construction superintendent registered "
                f"for this project{tail}. Matched by {by}.")
    if state == NOT_REGISTERED_CS:
        named = f" is {reg}" if reg else " is recorded under another name"
        return (f"Signed by {who}. The construction superintendent registered "
                f"for this project{named}.")
    if state == REGISTERED_LATER:
        return (f"Signed by {who}. The construction superintendent registration "
                f"for this project was created after this date, so it does not "
                f"describe who held the role when this log was signed.")
    if state == UNDETERMINED:
        return (f"Signed by {who}. Whether the registered construction "
                f"superintendent held the role on this date could not be "
                f"determined from the record.")
    return (f"Signed by {who}. No construction superintendent is registered "
            f"for this project in this system.")
