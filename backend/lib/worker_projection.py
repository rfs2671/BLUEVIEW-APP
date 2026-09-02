"""The projection that keeps the base64 card photo out of multi-worker reads.

WHAT IS ON THE DOCUMENT. `workers.osha_card_image` is the full compressed frame
the gate photographed, stored INLINE as a base64 data URL — not a key, not a
URL, the bytes themselves. checkin.html deliberately stores the whole frame
rather than the OCR crop, so it is a phone photo per worker, on a document that
is otherwise a few hundred bytes of name, phone and certifications.

WHAT THAT COSTS, and it is not theoretical. GET /workers returned 500 for every
admin on one company:

    pymongo.errors.OperationFailure: Executor error during find command:
    blueview.workers :: caused by :: Sort exceeded memory limit of 33554432
    bytes, but did not opt in to external sorting.

`.limit(50)` did not help — Mongo must sort the whole matched set first. The
fix there was `WORKER_LIST_FIELDS`, an inclusion projection derived from that
endpoint's three callers. It fixed the one endpoint that had already fallen
over and left every other multi-worker read loading the same photographs.

WHY THIS ONE IS AN EXCLUSION AND WORKER_LIST_FIELDS IS AN INCLUSION. An
inclusion projection has to enumerate what a reader needs, so it is only safe
where the readers are known and few. The readers here are not one screen: the
expiring-cert scan, the nightly cron, three check-in list endpoints, the
assistant's roster listing, the mention search, the LL196 attestation and the
risk score each read a different set of fields, and several pass the whole
document to a shared function (`validate_worker_certifications`) that may grow
its inputs. Naming ONE field to remove cannot break a reader that starts
reading a second field; naming twenty to keep can, silently, at a distance.

SIGNATURE AND SELFIE ARE THE SAME SHAPE AND ARE NOT REMOVED HERE. `signature`
and `selfie_image` are also base64 on this document. They belong in this
projection on the same reasoning, but each has its own readers to check and
neither is what D1/F4 is about; adding them blind is how a projection breaks a
screen. Recorded rather than done.

WHY IT LIVES UNDER lib/. server.py imports lib.logbook.ll196 and
lib.statistical_engine.score, both of which need this — so a lib module
importing server would be circular. Same arrangement, same reason, as
lib/cert_vocab.py: the definition sits below every consumer and is imported
upward, so there is no second copy to drift.

NOT FOR SINGLE-DOCUMENT READS. GET /workers/{id}/osha-card and the flagged
review queue exist to show a human the card. They project it IN, deliberately.
"""

# Mongo rejects a projection that mixes inclusions and exclusions, so this must
# stay exclusion-only. tests/test_worker_card_image_projection.py asserts that.
WORKER_NO_CARD_IMAGE = {"osha_card_image": 0}

__all__ = ["WORKER_NO_CARD_IMAGE"]
