"""Was the person who signed this log the registered CS for this project?

THE TWO RECORDS NEVER MET. `cs_registrations` holds the DOB designation --
full name, registration number, NYC.ID -- created by an ADMIN for a PROJECT.
`users` holds the account that signs. Nothing connected them, so a signature on
a BC 3301.13.13 log could not be tied to the registration that gives it weight.

THE NUMBER IS A REGISTRATION NUMBER, NOT A LICENCE NUMBER. That is what the DOB
card is printed with, and a field label is part of a compliance record. It was
stored as `license_number` and is now written as `registration_number`;
`registration_number_of` reads EITHER, because nothing migrates. MATCHED_LICENCE
keeps its name -- an internal token nothing prints -- while the sentence this
module renders onto the log says "registration".

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
    """A registration number reduced to a comparison key.

    Mirrors what register_construction_superintendent already stores as
    `license_number_normalized`, so the two sides of the comparison are built
    the same way rather than nearly the same way.
    """
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def registration_number_of(registration) -> str:
    """The number printed on the card, under whichever name it was stored.

    THE CARD SAYS REGISTRATION NUMBER. This system called it a licence number
    and stored it as `license_number`, which on a BC 3301.13.13 log states
    something about the man's credentials that his card does not say.

    NEW NAME FIRST, OLD NAME ALWAYS. Nothing migrates — every row written
    before the rename carries `license_number` and no `registration_number` —
    so a reader that only knew the new name would blank the number on every
    historical registration, and the place it would blank it is the attribution
    sentence on a filed document.

    `or`, NOT `.get(a, .get(b))`: a stored empty string must fall through to
    the other name rather than being taken for an answer.
    """
    reg = registration if isinstance(registration, dict) else {}
    return (str(reg.get("registration_number") or "").strip()
            or str(reg.get("license_number") or "").strip())


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
    # EITHER NAME. See registration_number_of — nothing migrates, so both
    # shapes are live in the collection at the same time.
    reg_lic = registration_number_of(registration) or None

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
        # "REGISTRATION", NOT "LICENCE", AND THE DIFFERENCE IS THE RECORD'S.
        # A construction superintendent's DOB card is printed with a
        # REGISTRATION NUMBER. This sentence is rendered onto a BC 3301.13.13
        # log by both renderers, so calling it a licence there asserts a
        # credential the man does not hold, on the one document where a wrong
        # statement about him costs most.
        #
        # THE CONSTANT KEEPS ITS NAME. MATCHED_LICENCE is an internal state
        # token that nothing prints and several tests import; renaming it
        # changes no record and breaks callers, so it stays as it is.
        by = ("account" if state == MATCHED_ACCOUNT else "registration number")
        tail = f" (registration {lic})" if lic else ""
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


# ── THE CAPABILITY ──────────────────────────────────────────────────────────
#
# The same question this module already answers at READ time, asked at MENU
# time: is this person the registered construction superintendent here?
#
# ONE PREDICATE, TWO CALLERS, AND THAT IS THE POINT. A nav item that decides
# "is he the superintendent" by its own rule would drift from the sentence the
# filed document prints about him. So the menu asks `attribute_signer` -- the
# same function, the same four states, the same date resolution.
#
# TWO STATES QUALIFY, and only two: the account link and the licence match are
# the cases where the system has an affirmative reason to believe this person
# holds the role.
CS_CAPABLE_STATES = (MATCHED_ACCOUNT, MATCHED_LICENCE)


def is_registered_cs(result) -> bool:
    """Does this attribution say the signer IS the registered CS?

    NO_REGISTRATION IS FALSE HERE, AND THAT IS NOT THE SAME CLAIM the read-time
    path makes about it. At read time an absent registration means NOTHING WAS
    CHECKED and must never print as a finding. At menu time the question is
    different -- "should this person be offered the superintendent's log as
    their primary action" -- and "nobody is registered" is not a yes.

    THIS IS SAFE ONLY BECAUSE IT GATES A SHORTCUT. The log stays reachable from
    the CP dashboard for anyone assigned to the project, so a superintendent
    whose registration an admin has not yet filled in loses a menu entry, not
    the ability to record his visit. If this predicate is ever used to REFUSE a
    filing, that reasoning collapses and the module's first rule -- IT NEVER
    BLOCKS -- is broken.
    """
    return isinstance(result, dict) and result.get("state") in CS_CAPABLE_STATES
