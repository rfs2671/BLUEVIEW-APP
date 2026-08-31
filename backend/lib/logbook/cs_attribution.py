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

EVERY PATH THAT SWITCHES A REGISTRATION OFF STAMPS A TIME, and all three are
read here:

    superseded by a new CS    is_active False + deactivated_at   (:16014)
    switched off by an admin  is_active False + deactivated_at   (:16165)
    soft-deleted              is_deleted True  + deleted_at      (:16179)

So the historical question is answerable in every case a live build can
produce:

    registered AFTER the log date        created_at is later
    deactivated BEFORE the log date      it was not active then
    deactivated AFTER the log date       it WAS active then -- the log is
                                         attributed normally
    deleted before / after               same, via deleted_at
    still active                         answerable

UNDETERMINED SURVIVES FOR ONE CASE ONLY: a row switched off before those two
stampers existed, which therefore carries `is_active: False` and no
`deactivated_at`. That set cannot be repaired -- the time it was switched off
was never written down -- so it reports that it cannot be determined rather
than guessing. It does not grow.

AN EARLIER VERSION OF THIS MODULE CLAIMED ONLY THE DELETE PATH STAMPED A TIME.
That was wrong, and wrong in a specific way worth recording: the writers were
INFERRED from the model and the delete endpoint rather than ENUMERATED by
grepping the field. Two of the three stampers were missed, and a permanent
"cannot be determined" was documented on a compliance record for a question the
data could already answer.
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

    # ── Switched off, and WHEN ─────────────────────────────────────────────
    #
    # Both off-switches stamp `deactivated_at`: supersession by a new CS, and
    # an admin setting is_active False. So the question is answerable rather
    # than merely honest about being unanswerable.
    deactivated = _as_date(registration.get("deactivated_at"))
    if day and deactivated:
        if deactivated < day:
            # Not the registered CS on that date. Same answer as a deletion
            # that predates the log: nobody was registered, so nothing is
            # claimed about the signer.
            return {"state": NO_REGISTRATION, "registered_name": None,
                    "registered_licence": None, "signer_name": signer_name,
                    "checked_on": day}
        # Deactivated on or AFTER the log's date, so it WAS active then and the
        # signature is attributed normally. A registration retired last month
        # does not un-describe a log signed while it stood.

    # THE ONE CASE THAT REMAINS UNANSWERABLE, and it cannot grow: a row
    # switched off BEFORE either stamper existed carries is_active False and no
    # deactivated_at. The moment it was switched off was never written down, so
    # nothing can recover it and the check says so rather than guessing.
    if (not registration.get("is_active")
            and not registration.get("deleted_at")
            and not registration.get("deactivated_at")
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
