"""The sentence printed above a signature, versioned, and what a snapshot says.

THE ASYMMETRY THIS CLOSES. A worker tapping Affirm at a turnstile produces a
signature event carrying the exact sentence he read, in his language, with a
version. The CP signing a filed logbook -- a document that goes to DOB, to
lenders, and to an OATH hearing -- produced an event whose content_snapshot was
the logbook payload and NOTHING about what the signature block said above his
name. The party whose signature carries statutory weight had the weaker record
of what they were agreeing to.

It was not carelessness. The CP's signature event predates the attestations
entirely: when it was written there WAS no sentence above the signature. All
three were added within the same week, as module constants the renderer prints,
and nothing fed them into the snapshot because the snapshot's shape was settled
before they existed.

── VERSIONED, APPEND-ONLY ──────────────────────────────────────────────────────

A snapshot that stored today's wording would be unverifiable the moment the
constant was edited: the stored text would be checkable against nothing. So
every wording ever printed stays in HISTORY, keyed by (log_type, version), and
a stored snapshot can be checked against what it claims to have said. Same shape
as lib/esra_consent.py and PRESHIFT_AFFIRMATION_TEXTS, and for the same reason:
a record whose wording cannot be reconstructed is not evidence.

DATED VERSIONS, NOT NUMBERED. "2026-08-31.1" says when the wording was settled
without anyone having to look it up.

── NINE OF TWELVE TYPES HAVE NO ATTESTATION, AND THE SNAPSHOT SAYS SO ─────────

Only three log types print a sentence above the signature. For the other nine
the snapshot must record that there was NOTHING to capture -- not omit the
field. An absent key cannot distinguish "the document had no attestation" from
"nobody captured it", and every event written before this change is permanently
in that second state. Three recorded states, and one that can only be inferred:

    PRESENT             the document carried a sentence; it is stored verbatim
    NONE_ON_DOCUMENT    this type prints no sentence above the signature
    UNDETERMINED        the log type could not be resolved when signing
    PREDATES_CAPTURE    no attestation key at all -- the event was written
                        before this existed. NOT recorded by anything: it is
                        what the ABSENCE of the key means, and it is
                        unrepairable, because writing the key onto an existing
                        audit event would be altering the ledger.
"""

from __future__ import annotations

from typing import Dict, Optional

PRESENT = "present"
NONE_ON_DOCUMENT = "none_on_document"
UNDETERMINED = "undetermined"
PREDATES_CAPTURE = "predates_capture"

# The key the snapshot carries. Reserved: a client-supplied snapshot is merged
# UNDER it, never over it -- see attach_attestation.
SNAPSHOT_KEY = "attestation"


# ── The current wording, per log type ───────────────────────────────────────
#
# THE TEXT LIVES HERE AND server.py IMPORTS IT. Two copies of a sentence are two
# sentences the moment one is edited, and this one is printed on a compliance
# document and stored in an audit ledger -- the two places a divergence would be
# hardest to notice and worst to explain.
_PRESHIFT_V1 = (
    "Each worker named below was present at the start of shift on this date and "
    "was asked, before starting work, whether there was an injury or incident on "
    "their last shift and whether they inspected their PPE for today. Those "
    "answers appear in the Injury and PPE columns. Each signature in the "
    "Signature column is that worker&#39;s own. The CP&#39;s signature below "
    "attests that this roster and these answers were taken as recorded."
)

_OSHA_V1 = (
    "This register lists the certifications recorded in this system for the "
    "workers who checked in on this date. Certifications are captured at the "
    "gate or entered by the CP, and this document does not distinguish which. "
    "A tick in the Signed column is the CP&#39;s mark that a signature for that "
    "worker is on file elsewhere; it is not a signature given here. The "
    "CP&#39;s signature below attests that this register is a true copy of what "
    "the system held on this date. It does not attest that the physical cards "
    "were inspected."
)

_CS_LOG_V1 = (
    "This is the construction superintendent&#39;s own record for this date, "
    "made under BC 3301.13.13 and signed by the superintendent named below. "
    "An item marked &#34;none to report&#34; is his statement that he "
    "considered that item and had nothing to record; it is not an absence of "
    "information. An item marked Not recorded was not answered. Arrival and "
    "departure times are his own, prefilled from sign-in and from completion "
    "of this log and editable by him; they are not observed by this system."
)

# ── THE CS LOG'S SECOND VERSION ────────────────────────────────────────────
#
# A NEW VERSION, NOT AN EDIT, AND THE DIFFERENCE MATTERS HERE MORE THAN
# ANYWHERE. Item 8 became attestable, and its tick is not the same KIND of
# statement as items 4 to 7's. _CS_LOG_V1 explains one form only:
#
#     An item marked "none to report" is his statement that he considered that
#     item and had nothing to record; it is not an absence of information.
#
# Item 8's tick is a positive claim about where he was, not a statement that
# there was nothing to record. The paragraph above does not cover it, so
# printing it over a document carrying that tick would describe the signer's
# assertion incorrectly.
#
# EDITING _CS_LOG_V1 IN PLACE WOULD CHANGE WHAT ALREADY-SIGNED DOCUMENTS SAY
# THEY MEANT. The stored snapshot on every signature event names a version; if
# the text behind that name changed, the record would claim the signer read a
# sentence nobody showed him. That is the exact failure the append-only
# registry exists to prevent, so V1 stays below, byte for byte, forever.
_CS_LOG_V2 = _CS_LOG_V1 + (
    " Where item 8 records that no competent person was designated, that is "
    "his statement that he was present at the job site at all times active "
    "work occurred, as Section 3301.13.12 requires when no competent person "
    "is designated."
)

ATTESTATIONS: Dict[str, Dict[str, str]] = {
    "preshift_signin": {"version": "2026-08-31.1", "text": _PRESHIFT_V1},
    "osha_log": {"version": "2026-08-31.1", "text": _OSHA_V1},
    "site_superintendent_log": {"version": "2026-09-06.1", "text": _CS_LOG_V2},
}

# ── Every wording ever printed ──────────────────────────────────────────────
#
# APPEND ONLY. A version that has ever been printed on a document somebody
# signed must stay here forever, exactly as it was printed. Editing one
# retroactively changes what a stored snapshot appears to say, which is the
# failure this registry exists to prevent.
HISTORY: Dict[str, str] = {
    f"preshift_signin/2026-08-31.1": _PRESHIFT_V1,
    f"osha_log/2026-08-31.1": _OSHA_V1,
    # V1 STAYS, BYTE FOR BYTE, FOREVER. Every superintendent log signed before
    # item 8 became attestable names this version, and the whole point of the
    # registry is that a stored snapshot can be checked against what it claims
    # to have said.
    f"site_superintendent_log/2026-08-31.1": _CS_LOG_V1,
    f"site_superintendent_log/2026-09-06.1": _CS_LOG_V2,
}


def attestation_text(log_type, version) -> Optional[str]:
    """The exact wording of one version, or None if this build never had it.

    None is a real answer, not an error: a snapshot written by a LATER build
    naming a version this one does not carry is newer, not corrupt. The caller
    decides what to do about that; guessing here would be worse.
    """
    if not log_type or not version:
        return None
    return HISTORY.get(f"{log_type}/{version}")


def attestation_snapshot(log_type) -> Dict:
    """What goes into content_snapshot for a log of this type.

    NEVER RETURNS None AND NEVER OMITS THE KEY. A type with no sentence above
    its signature records NONE_ON_DOCUMENT, because an absent key cannot be
    told apart from an event nobody captured one for -- and nine of the twelve
    types are in that position.
    """
    key = str(log_type or "").strip()
    if not key:
        return {"state": UNDETERMINED, "log_type": None,
                "version": None, "text": None}
    entry = ATTESTATIONS.get(key)
    if not entry:
        return {"state": NONE_ON_DOCUMENT, "log_type": key,
                "version": None, "text": None}
    return {"state": PRESENT, "log_type": key,
            "version": entry["version"], "text": entry["text"]}


def attach_attestation(content_snapshot, log_type) -> Dict:
    """Merge the attestation into a snapshot the CLIENT supplied.

    THE CLIENT'S SNAPSHOT IS NOT TRUSTED WITH THIS. The wording is what the
    signer was shown, and a snapshot whose attestation the client could choose
    is evidence of nothing -- the same reason the gate's affirmation text comes
    from the server and the ESRA consent stores its own copy. Any attestation
    key already present is OVERWRITTEN, deliberately.
    """
    base = dict(content_snapshot) if isinstance(content_snapshot, dict) else {}
    base[SNAPSHOT_KEY] = attestation_snapshot(log_type)
    return base


def attestation_of(event) -> Dict:
    """What a STORED signature event says about the sentence above its signature.

    Returns {"state", "version", "text", "verified"} where `verified` is True
    only when the stored text matches this build's registry for that version.

    PREDATES_CAPTURE IS THE ANSWER FOR EVERY EVENT WRITTEN BEFORE THIS EXISTED,
    and it is a statement about the RECORD rather than about the document: the
    absence of the key is not evidence that the document carried no
    attestation, nor that it carried one. It is unrepairable -- writing the key
    onto an existing audit event would be altering the ledger, which is the one
    thing an audit ledger may not do -- so it is labelled, not fixed.
    """
    snap = ((event or {}).get("content_snapshot") or {}) if isinstance(event, dict) else {}
    block = snap.get(SNAPSHOT_KEY) if isinstance(snap, dict) else None
    if not isinstance(block, dict):
        return {"state": PREDATES_CAPTURE, "version": None, "text": None,
                "verified": False}

    state = block.get("state")
    if state != PRESENT:
        return {"state": state or UNDETERMINED, "version": None,
                "text": None, "verified": False}

    stored = block.get("text")
    known = attestation_text(block.get("log_type"), block.get("version"))
    return {
        "state": PRESENT,
        "version": block.get("version"),
        "text": stored,
        # None means this build cannot check it -- a different fact from the
        # text being wrong, and reported as such rather than as a failure.
        "verified": (stored == known) if known is not None else None,
    }


def attestation_sentence(result) -> str:
    """One line for a human reading an audit trail. Never prose from the server
    to a screen -- callers own their wording -- but the verify endpoint has no
    client and this is what it reports."""
    r = result if isinstance(result, dict) else {}
    state = r.get("state")
    if state == PRESENT:
        v = r.get("verified")
        if v is True:
            return "The wording shown above this signature is stored and verified."
        if v is None:
            return ("The wording is stored, but this build does not carry that "
                    "version and cannot check it.")
        return "The stored wording does not match this build's registry."
    if state == NONE_ON_DOCUMENT:
        return "This document type prints no attestation above its signature."
    if state == UNDETERMINED:
        return "The log type could not be resolved when this was signed."
    return ("This event predates attestation capture. The absence of a stored "
            "wording is not evidence that the document carried one, or that it "
            "did not.")
