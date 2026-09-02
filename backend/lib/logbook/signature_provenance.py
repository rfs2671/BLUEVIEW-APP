"""WHO WROTE THIS LEDGER ROW, AND WHAT THE ROW CAN AND CANNOT VOUCH FOR.

THE GAP THIS CLOSES. A signature made with no signal produced no ledger row at
all. Every one of recordSignatureEvent's thirteen call sites guards on
`if (docId)`, and offline there is no server id, so the call was SKIPPED --
not failed, skipped, with nothing to observe on either side. draftSync drained
the log hours later carrying `cp_signature` and `status: 'submitted'` and has
never written a signature event. Thirty-three signatures on the live project
are in exactly that state.

The durable answer is to DERIVE the row from the accepted document rather than
to queue it on the device. A client queue is lost with the device; the document
is already durable through logbookDrafts + draftSync, which is proven
machinery, and a row derived from the document cannot go missing separately
from the document it describes.

── WHAT DERIVATION COSTS, AND WHY IT IS WRITTEN DOWN ───────────────────────────

DERIVING LOSES THE DEVICE AND THE IP, AND ONLY THOSE. The signing INSTANT is
not lost: SignaturePad stamps `timestamp`, `affirmed`, `affirmedAt` and
`affirmedLang` INSIDE the signature object at the moment of the stroke
(frontend/src/components/SignaturePad.js), the whole object travels with the
document, and _finalize_cp_signature already treats the client's `affirmedAt`
as the real attestation moment. So a derived row can carry the time the person
actually signed.

The device fingerprint and the IP cannot survive the same way. They are
properties of the REQUEST, and the request that carries a drained document
comes from the device and the network that happened to have signal later --
possibly the same phone on a different network, possibly a different phone
after a reinstall. Recording those as the signing device would be a fabrication
of exactly the kind the ledger exists to prevent.

SO THE LOSS IS RECORDED ON THE ROW, NEVER INFERRED FROM IT. A row that says
nothing about its own provenance is indistinguishable from a contemporaneous
one, and an auditor reading `device` on a derived row would be reading the
sync-time device as if it were the signer's.

── SAME SHAPE AS attestations.PREDATES_CAPTURE, DELIBERATELY ──────────────────

Four states, three recorded and one that can only be inferred from an absence:

    CONTEMPORANEOUS   the signing client wrote this row itself, at signing
                      time, over its own connection. `device` and `ip_address`
                      are the SIGNER'S.
    DERIVED           the server wrote this row from a document it accepted
                      carrying a signature the ledger had no row for. The
                      signing instant is the client's own stamp; the device and
                      the IP are NOT RECORDED, because the only ones available
                      belong to the sync, not to the signing.
    UNDETERMINED      a row was written by a path that did not say. This is
                      what create_signature_event stamps when a caller passes
                      no provenance, and it exists so that omission cannot be
                      mistaken for age: a row with NO key at all reads as
                      PREDATES_MARKING below, and a row written today must
                      never be able to claim that.
    PREDATES_MARKING  no provenance key at all -- the row was written before
                      this existed. NOT recorded by anything: it is what the
                      ABSENCE of the key means, and it is unrepairable, because
                      writing provenance onto an existing audit event would be
                      altering the ledger.

THE 33 STAY AS THEY ARE. They are not backfilled and this module does not
provide a way to backfill them: a reconstructed `content_snapshot` would attest
to content the signer never saw, and /signature-events/verify would then assert
a hash over something nobody signed. An absent row is an honest absence. A
fabricated one is not.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

CONTEMPORANEOUS = "contemporaneous"
DERIVED = "derived_from_document"
UNDETERMINED = "undetermined"
PREDATES_MARKING = "predates_provenance_marking"

# The key the EVENT carries — top level, NOT inside content_snapshot.
#
# THIS IS THE ONE PLACE THIS MODULE DIVERGES FROM attestations.py, AND THE
# DIVERGENCE IS THE POINT. An attestation is part of what the signer was SHOWN,
# so it belongs inside the snapshot and under the content hash. Provenance is a
# statement about the RECORD -- who wrote this row and what it can vouch for --
# and the signer never saw it. Hashing it would make a fact about the ledger
# look like a fact about the document.
EVENT_KEY = "provenance"

# What a row can say about the device and the network the signature came from.
FIDELITY_SIGNER = "signer"       # the request WAS the signing client's
FIDELITY_NOT_RECORDED = "not_recorded"   # the sync's, so deliberately unrecorded

# Where the derived row got its signing instant. Recorded rather than assumed:
# a signature with neither stamp is a real shape (a legacy base64 credential),
# and a row that silently fell back to the sync time would be claiming a
# signing moment nobody recorded.
SIGNED_AT_AFFIRMED_AT = "signature.affirmedAt"
SIGNED_AT_TIMESTAMP = "signature.timestamp"
SIGNED_AT_ABSENT = None


def contemporaneous_provenance(written_by: str = "client") -> Dict:
    """The signing client wrote this row itself. Device and IP are the signer's."""
    return {
        "state": CONTEMPORANEOUS,
        "written_by": written_by,
        "device_fidelity": FIDELITY_SIGNER,
        "ip_fidelity": FIDELITY_SIGNER,
    }


def undetermined_provenance() -> Dict:
    """A row whose writer did not say how it came to be written.

    NOT the same as no key at all, and that difference is the whole reason this
    exists. An absent key means the row predates provenance marking; this means
    the row was written after it and the caller supplied nothing. One is a fact
    about the age of the record, the other is a gap in a current code path.
    """
    return {
        "state": UNDETERMINED,
        "written_by": None,
        "device_fidelity": None,
        "ip_fidelity": None,
    }


def derived_provenance(
    *,
    written_by: str,
    derived_at: datetime,
    signed_at: Optional[datetime],
    signed_at_source: Optional[str],
) -> Dict:
    """The server derived this row from a document it accepted.

    `written_by` names the SERVER PATH that derived it (an endpoint name), so a
    row can be traced to the code that produced it without a deploy archaeology
    exercise. `derived_at` is the instant the server wrote the row -- the sync
    time, kept because it is a real fact, and named so it cannot be mistaken
    for the signing time. `signed_at` is the client's own stamp, and
    `signed_at_source` says which field it came out of, or None when the
    signature carried no stamp at all.
    """
    return {
        "state": DERIVED,
        "written_by": written_by,
        "derived_at": derived_at,
        "signed_at": signed_at,
        "signed_at_source": signed_at_source,
        # THE TWO THINGS THIS ROW CANNOT VOUCH FOR, said out loud.
        "device_fidelity": FIDELITY_NOT_RECORDED,
        "ip_fidelity": FIDELITY_NOT_RECORDED,
    }


def provenance_of(event) -> Dict:
    """What a STORED signature event says about how it came to be written.

    PREDATES_MARKING IS THE ANSWER FOR EVERY ROW WRITTEN BEFORE THIS EXISTED,
    and it is a statement about the RECORD rather than about the signature: the
    absence of the key is not evidence that the row was contemporaneous, nor
    that it was derived. It is unrepairable for the same reason
    attestation_of's PREDATES_CAPTURE is -- writing provenance onto an existing
    audit event would be altering the ledger -- so it is labelled, not fixed.
    """
    block = (event or {}).get(EVENT_KEY) if isinstance(event, dict) else None
    if not isinstance(block, dict):
        return {
            "state": PREDATES_MARKING,
            "written_by": None,
            "device_fidelity": None,
            "ip_fidelity": None,
            "signed_at": None,
            "signed_at_source": None,
        }
    state = block.get("state") or UNDETERMINED
    return {
        "state": state,
        "written_by": block.get("written_by"),
        "device_fidelity": block.get("device_fidelity"),
        "ip_fidelity": block.get("ip_fidelity"),
        "signed_at": block.get("signed_at"),
        "signed_at_source": block.get("signed_at_source"),
    }


def provenance_sentence(result) -> str:
    """One line for a human reading an audit trail.

    Never prose from the server to a screen -- callers own their wording -- but
    the verify endpoint has no client and this is what it reports. Same
    exception, and the same reasoning, as attestation_sentence.
    """
    r = result if isinstance(result, dict) else {}
    state = r.get("state")
    if state == CONTEMPORANEOUS:
        return ("The signing device wrote this row itself. The device and IP "
                "recorded on it are the signer's.")
    if state == DERIVED:
        if r.get("signed_at_source"):
            return ("This row was derived from the signed document when the "
                    "server accepted it, because no row existed for the "
                    "signature. The signing time is the signer's own; the "
                    "device and IP are NOT recorded, because the only ones "
                    "available belong to the sync and not to the signing.")
        return ("This row was derived from the signed document when the server "
                "accepted it. The signature carried no timestamp of its own, "
                "so no signing time is recorded; the device and IP are not "
                "recorded either.")
    if state == UNDETERMINED:
        return "How this row came to be written could not be determined."
    return ("This row predates provenance marking. The absence of a record is "
            "not evidence that the signing device wrote it, or that it did not.")
