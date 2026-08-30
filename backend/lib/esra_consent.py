"""The agreement to sign electronically, and the text of every version of it.

WHY THIS EXISTS. Buildings Bulletin 2024-007 § V.5 requires that "all involved
parties must clearly intend to sign electronically and agree to conduct
transactions electronically". Nothing in this application recorded such an
agreement. The worker-facing gate affirmation is a different thing: it
authorises the use of one captured signature on one day's pre-shift sheet, not
a general consent to conduct business electronically.

IT IS ONE-TIME, AT ACCOUNT SETUP, not a per-entry confirmation. That is the
ordinary ESRA shape and the one a signer will not learn to click through.

THE TEXT IS STORED ON THE RECORD, NOT ONLY ITS VERSION. A consent whose wording
cannot be reconstructed is not evidence. A version pointer alone fails the
moment this file is edited: the pointer would resolve to text the person never
saw. So the consent row carries the FULL TEXT VERBATIM, and this registry keeps
every historical version as well, so a row can be checked against what it
claims to have said.

VERSIONS ARE DATED, NOT NUMBERED. "2026-08-30.1" says when the wording was
settled without anyone having to look it up. A second wording on the same day
increments the suffix.

NOTHING HERE ASSERTS THAT THE CONSENT SATISFIES ESRA OR THE BULLETIN. It
records what a person agreed to and when. Whether that discharges any legal
requirement is a judgment made elsewhere -- see
docs/compliance/esra-bb2024-007-compliance.md, which states plainly that it
does not certify compliance.
"""

from __future__ import annotations

from typing import Dict, Optional

# ── The current wording ──────────────────────────────────────────────────────
#
# WRITTEN TO BE READ BY THE PERSON SIGNING, not by a lawyer. A construction
# superintendent on a tablet at 6am is the reader. Four short paragraphs, each
# making one promise or asking for one:
#
#   1. consent to conduct business electronically   (the bulletin's "agree to
#                                                    conduct transactions
#                                                    electronically")
#   2. intent that the mark IS the signature        (the bulletin's "clearly
#                                                    intend to sign
#                                                    electronically")
#   3. what follows from signing -- that the record is the record and cannot be
#      edited afterwards, which is true of this system and which the signer is
#      entitled to know BEFORE agreeing rather than after
#   4. how to stop, because a consent with no exit is not freely given
#
# Paragraph 3's promise of a copy is one the software can keep: every logbook
# renders to PDF today.
ESRA_CONSENT_VERSION = "2026-08-30.1"

ESRA_CONSENT_TEXT = (
    "I agree to do business electronically with LeveLog and with the company "
    "that gave me this account.\n"
    "\n"
    "I agree that the signature I draw or apply in this application is my "
    "signature, and I intend it to have the same effect as a signature I write "
    "by hand on paper.\n"
    "\n"
    "I understand that the records I sign here are kept as the record of the "
    "work they describe, that I cannot edit a record after I have signed it, "
    "and that I can be given a copy of anything I have signed.\n"
    "\n"
    "I can withdraw this agreement at any time by telling my company "
    "administrator. If I withdraw it, I will be asked to sign on paper instead."
)

# ── Every version ever shown ─────────────────────────────────────────────────
#
# APPEND ONLY. A version that has ever been shown to anyone must stay here
# forever, exactly as it was shown. Editing one retroactively changes what a
# stored consent appears to say, which is the failure this registry prevents.
#
# The check `consent_text_for(row.version) == row.consent_text` is what makes a
# stored row verifiable years later. It can only fail two ways: the row was
# altered, or a version was edited in place. Both are worth knowing about.
ESRA_CONSENT_TEXTS: Dict[str, str] = {
    "2026-08-30.1": ESRA_CONSENT_TEXT,
}


def consent_text_for(version: Optional[str]) -> Optional[str]:
    """The exact wording of a version, or None if this build has never seen it.

    None is a real answer and not an error: a row written by a later build
    naming a version this one does not carry is not corrupt, it is newer. The
    caller decides what to do about that; guessing here would be worse.
    """
    if not version:
        return None
    return ESRA_CONSENT_TEXTS.get(str(version))


def consent_is_current(version: Optional[str]) -> bool:
    """Has this person agreed to the wording in force NOW?

    An older version is NOT current, and that is deliberate rather than strict.
    If the wording changes materially, the previous agreement was to different
    words; treating it as sufficient would let a change of terms take effect
    without anybody agreeing to it. What to DO about a stale consent -- ask
    again, or continue and ask at the next natural moment -- is a product
    decision and is not made here.
    """
    return str(version or "") == ESRA_CONSENT_VERSION


def verify_stored_consent(row: Optional[dict]) -> dict:
    """Check a stored consent row against this build's registry.

    Returns {"ok", "reason", "version", "current"} where `reason` is a machine
    code and never prose:

        MISSING           no row at all
        NO_TEXT           the row stored no wording -- unverifiable by design
        UNKNOWN_VERSION   this build has never carried that version's text
        TEXT_MISMATCH     the stored wording differs from the registry's
        None              the row verifies

    UNKNOWN_VERSION IS NOT A FAILURE OF THE ROW. It reports only that this
    build cannot check it, which is a different fact from the row being wrong,
    and the two must not be reported as one -- the same distinction the OSHA
    register draws between "No findings" and "Not checked".
    """
    if not isinstance(row, dict) or not row:
        return {"ok": False, "reason": "MISSING", "version": None, "current": False}

    version = row.get("consent_version")
    stored = row.get("consent_text")
    current = consent_is_current(version)

    if not stored:
        return {"ok": False, "reason": "NO_TEXT", "version": version,
                "current": current}

    known = consent_text_for(version)
    if known is None:
        return {"ok": False, "reason": "UNKNOWN_VERSION", "version": version,
                "current": current}
    if known != stored:
        return {"ok": False, "reason": "TEXT_MISMATCH", "version": version,
                "current": current}

    return {"ok": True, "reason": None, "version": version, "current": current}
