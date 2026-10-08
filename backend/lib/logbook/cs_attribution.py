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

A REGISTRATION IS A DATED SPAN, AND THERE IS NO SWITCH. Operator's ruling,
2026-10-08: once a superintendent is assigned to a project he is its
superintendent until User Management changes his assignment. A registration
exists or it does not. `is_active` is neither read nor written.

It starts at `created_at` and ends at `ended_at` -- stamped when he is
unassigned, or when his replacement is registered. AN ENDED ROW IS NEVER
DELETED: it is what a sheet he signed last month is attributed against. So the
historical question is answerable in every case:

    registered AFTER the log date        created_at is later -> REGISTERED_LATER
    ended BEFORE the log date            it did not describe that day
    ended ON OR AFTER the log date       it DID -- attributed normally
    not ended                            in force

`registration_in_force_on` picks the row for a date from ALL of a project's
rows, so last month's sheet finds last month's superintendent even after he was
replaced. Before this, the caller handed in the project's CURRENT row, and a
sheet signed by a predecessor was checked against his successor's registration.

LEGACY SPELLINGS OF AN END are read as one (`registration_end`): `deactivated_at`
(superseded or switched off) and `deleted_at` (unassigned, which used to
soft-delete). Production held no such row when this changed (census
2026-10-08: one registration, live) -- a guard, not a migration.

UNDETERMINED IS NO LONGER PRODUCED. It existed for a row switched off before
any end was stamped, which `is_active: False` alone could not date. With no
switch there is no such row; the constant and its sentence stay so a caller
holding the name does not break.

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


def registration_end(registration) -> Optional[object]:
    """When this registration stopped describing the project, or None.

    `ended_at` is the one spelling written now. The two legacy ones are read as
    the same fact so a row written before the switch was removed still dates.
    """
    r = registration if isinstance(registration, dict) else {}
    return r.get("ended_at") or r.get("deactivated_at") or r.get("deleted_at")


def registration_in_force_on(rows, log_date, signer_id=None):
    """The registration that described the project on `log_date`.

    PURE. `rows` is EVERY registration the project has ever had -- ended ones
    included, because an ended row is what an old sheet is attributed against.

    Returns, in order of preference:
      * a row in force that day (created on or before it, not ended before it).
        ON A HANDOVER DAY two can be -- the predecessor's end and the
        successor's start share a date -- and both men held the role that day,
        so the one whose account signed is preferred; otherwise the newest.
      * else the EARLIEST row created after it, so the caller reports
        REGISTERED_LATER rather than "nobody";
      * else None: every registration had ended before that day, or there
        never was one.

    A soft-deleted legacy row with no date is skipped: it cannot be placed in
    time, and placing it would be a guess on a statutory record.
    """
    usable = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        if r.get("is_deleted") and not registration_end(r):
            continue
        usable.append(r)
    if not usable:
        return None

    def _key(r):
        return (_as_date(r.get("created_at")) or "",
                str(r.get("created_at") or ""), str(r.get("_id") or ""))

    day = _as_date(log_date)
    if day is None:
        live = [r for r in usable if not registration_end(r)]
        return max(live or usable, key=_key)

    def _in_force(r):
        start = _as_date(r.get("created_at"))
        end = _as_date(registration_end(r))
        return (start is None or start <= day) and (end is None or end >= day)

    in_force = [r for r in usable if _in_force(r)]
    if in_force:
        sid = str(signer_id or "").strip()
        if sid:
            mine = [r for r in in_force if str(r.get("user_id") or "") == sid]
            if mine:
                return max(mine, key=_key)
        return max(in_force, key=_key)
    later = [r for r in usable
             if _as_date(r.get("created_at")) and _as_date(r.get("created_at")) > day]
    if later:
        return min(later, key=_key)
    return None


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

    # ── Ended, and WHEN ────────────────────────────────────────────────────
    #
    # ONE END, WHATEVER IT IS SPELLED. Ended before the log's date: it did not
    # describe that day, so nothing is claimed about the signer. Ended on or
    # after: it DID, and a registration that ended last week does not
    # un-describe a log signed while it stood. There is no switch to consult --
    # `is_active` is not read (operator's ruling, 2026-10-08).
    ended = _as_date(registration_end(registration))
    if day and ended and ended < day:
        return {"state": NO_REGISTRATION, "registered_name": None,
                "registered_licence": None, "signer_name": signer_name,
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
        # "REGISTRATION", NOT "LICENCE". DOB issues a construction
        # superintendent a registration number; the sheet used to call it a
        # licence (defect A2). Corrected on the operator's ruling, 2026-10-08.
        by = ("account" if state == MATCHED_ACCOUNT
              else "registration number")
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


#: The states on which a filing is REFUSED. Exactly one, and the smallness is
#: the design: everything else either affirms the signer or admits the system
#: does not know, and neither is grounds to block a statutory record.
CS_REFUSED_STATES = (NOT_REGISTERED_CS,)


def cs_filing_refused(result) -> bool:
    """Should this signer be REFUSED the superintendent's log?

    A SECOND PREDICATE, NOT A REUSE OF `is_registered_cs`, AND THE MODULE SAYS
    WHY. That one's docstring ends: "If this predicate is ever used to REFUSE a
    filing, that reasoning collapses and the module's first rule -- IT NEVER
    BLOCKS -- is broken." It answers a MENU question, where "nobody is
    registered" is fairly read as "do not offer this shortcut". Reusing it here
    would silently change what it means for its existing caller AND refuse on
    absence, which is the wrong failure -- see below.

    THE ONLY REFUSAL IS `NOT_REGISTERED_CS`: the project HAS said who its
    construction superintendent is, and this is somebody else. That is the
    whole finding. BC 3301.13.13 is the superintendent's own record, and a CP
    signing it files a statutory document attributed to a role the signer does
    not hold.

    EVERY OTHER STATE PASSES, and each for its own reason:

      MATCHED_ACCOUNT   he is the registered CS, bound by account id
      MATCHED_LICENCE   corroborated by licence. Weaker evidence, but it is
                        evidence FOR him, and the document records which.
      NO_REGISTRATION   NOBODY HAS BEEN DESIGNATED. Refusing here would block a
                        log that must be filed before he leaves the site over
                        a field an admin has not filled in -- punishing the
                        superintendent for the office's omission. The gap is
                        instead made VISIBLE: attribution_sentence() prints on
                        the filed document that nothing was checked.
      REGISTERED_LATER  the registration postdates the log. He may well have
                        been the CS on the day; the registration simply cannot
                        speak to it. Refusing would be a finding drawn from a
                        record that says it has none.
      UNDETERMINED      the module's own "this cannot be recovered" state. A
                        refusal built on it would be a guess wearing a gate.

    SO THE FAILURE DIRECTION IS DELIBERATE: this refuses only where there is an
    affirmative reason to, and lets every ambiguity through onto a document
    that states the ambiguity. On a record that must exist before a man leaves
    a jobsite, a wrongly-refused filing is worse than a filed one whose
    attribution line says the signer was not the registered CS.
    """
    return isinstance(result, dict) and result.get("state") in CS_REFUSED_STATES


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
