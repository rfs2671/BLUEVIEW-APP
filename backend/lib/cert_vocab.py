"""The certification type vocabularies. ONE definition, imported everywhere.

WHY THIS MODULE EXISTS. `SST_CLASS_TYPES` was canonical in server.py with FOUR
members, and two consumers under lib/ each carried a hardcoded THREE-member
copy that dropped SST_TEMPORARY:

    lib/logbook/ll196.py:47          _SST_CERT_TYPES = ("SST_FULL", "SST_LIMITED", "SST_SUPERVISOR")
    lib/statistical_engine/score.py  ("SST_FULL", "SST_LIMITED", "SST_SUPERVISOR")

So a worker holding a temporary SST card was admitted at the gate as a legible
class, counted "missing" on the LL196 attestation PDF, and excluded from the
risk score's expiring count. A document filed with the DOB contradicting the
gate about the same man.

WHY NOT IMPORT FROM server.py. The dependency runs the other way -- server.py
imports lib.logbook.ll196 and lib.statistical_engine.score. A lib module
importing server would be circular, and relying on server's import being
function-level to dodge that would make the whole arrangement depend on where
somebody happens to put an import statement.

So the definition lives here, below both, and server.py imports it too. There
is no copy left to drift.

ADDING A TYPE. Add it here and every consumer sees it in the same deploy. That
is the entire point: the previous arrangement made adding one a three-file
change nobody could be expected to remember.
"""

# SST types that name a SPECIFIC, legible class. A card whose class we could
# read is one of these.
#
# SST_TEMPORARY IS A MEMBER. A temporary card is a real, class-confirmed NYC
# SST credential with an expiry -- it is the shortest-lived, which makes it the
# one most likely to lapse unnoticed, which is exactly why dropping it from the
# risk score's expiring count was the worst place to drop it.
SST_CLASS_TYPES = frozenset({
    "SST_FULL",
    "SST_LIMITED",
    "SST_SUPERVISOR",
    "SST_TEMPORARY",
})

# The class was on the card but OCR could not read it. Recognized as "an SST
# card is present" (satisfies the OSHA baseline) but NEVER as a valid,
# class-confirmed credential -- see the three-state gate in server.py.
SST_UNSPECIFIED = "SST_UNSPECIFIED"

# Every value the gate treats as "a NYC SST card exists on this worker".
RECOGNIZED_SST_TYPES = SST_CLASS_TYPES | {SST_UNSPECIFIED}

OSHA_TYPES = frozenset({"OSHA_10", "OSHA_30", "OSHA_UNSPECIFIED"})

__all__ = [
    "SST_CLASS_TYPES",
    "SST_UNSPECIFIED",
    "RECOGNIZED_SST_TYPES",
    "OSHA_TYPES",
]
