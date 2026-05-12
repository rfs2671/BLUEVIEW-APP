"""Phase V2.3 — Statistical-engine utility module.

Holds the small set of helpers that survived the V2.2 local-mirror
removal:

  • ``_construct_bbl_from_components`` — synthesize the canonical
    10-digit NYC BBL from a Socrata row's ``boro``/``block``/``lot``
    triple. Migrated verbatim from the deleted
    ``ingestion.py``. Still needed because the dob_violations
    Socrata dataset (3h2n-5cm9) doesn't ship a pre-joined ``bbl``
    column; whichever code path queries it lazily in V2.3 will
    need this synthesis.

  • ``normalize_bbl`` — strip the ``.0+`` decimal suffix
    PLUTO's Socrata payload uses on numeric columns
    (``"4061730023.00000000"`` → ``"4061730023"``). Renamed
    from V2.2's ``_normalize_bbl_for_storage`` because the
    "for_storage" qualifier no longer applies — V2.3 normalizes
    at query time, not write time.

V2.3 Commit 3: the transitional collection-name constants
(NYC_VIOLATIONS_COLLECTION etc.) that lived here as orphans
between Commits 1-2 have been deleted. The four consumer modules
(baselines.py, triggers.py, score.py, calibration.py) were
rewritten in Commit 3 to use lazy SocrataClient queries and no
longer need any local-mirror collection names.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# ── BBL utilities (canonical V2.2.4 logic preserved) ──────────────


def _construct_bbl_from_components(row: Dict[str, Any]) -> Optional[str]:
    """Construct NYC's canonical 10-digit BBL from a Socrata row's
    boro/block/lot triple. Returns None if any component is
    missing, non-numeric, or out of expected shape.

    BBL formula (canonical NYC convention):
      ``boro_digit + block.zfill(5) + lot.zfill(4)`` → 10 chars.

    Where boro_digit is 1–5 (1=Manhattan, 2=Bronx, 3=Brooklyn,
    4=Queens, 5=Staten Island), block fits in 5 digits, and lot
    fits in 4 digits. Some Socrata datasets (including
    3h2n-5cm9, dob_violations) over-pad the `lot` text field to
    5 chars with a leading zero — we strip and re-pad to 4 to
    produce the canonical 10-char form that matches BBLs stored
    on the other event collections.
    """
    boro = row.get("boro")
    block = row.get("block")
    lot = row.get("lot")
    if not (boro and block and lot):
        return None
    boro_str = str(boro).strip()
    block_str = str(block).strip()
    lot_str = str(lot).strip()
    if not (boro_str.isdigit() and block_str.isdigit() and lot_str.isdigit()):
        return None
    if len(boro_str) != 1 or boro_str not in "12345":
        return None
    # Normalize over-padding (Socrata sometimes ships "00038") by
    # stripping leading zeros, then re-padding to the canonical
    # width. A pure-zero component (e.g. block="0", lot="00")
    # collapses to "" after lstrip — that's a semantically
    # invalid BBL (lot 0 doesn't exist in NYC's tax-lot scheme),
    # so return None instead of producing "boro+00000+0000" which
    # would falsely match other invalid rows.
    block_normalized = block_str.lstrip("0")
    lot_normalized = lot_str.lstrip("0")
    if not block_normalized or not lot_normalized:
        return None
    if len(block_normalized) > 5 or len(lot_normalized) > 4:
        return None
    return f"{boro_str}{block_normalized.zfill(5)}{lot_normalized.zfill(4)}"


def normalize_bbl(bbl: Optional[str]) -> Optional[str]:
    """Strip the trailing ``.0+`` decimal suffix PLUTO's Socrata
    payload uses on numeric columns
    (``"4061730023.00000000"`` → ``"4061730023"``).

    V2.3 rename: was ``_normalize_bbl_for_storage`` in V2.2.4 when
    normalization happened at write-to-mirror time. V2.3 normalizes
    at query/read time instead, so "for_storage" no longer
    applies. Public name (no leading underscore) since lazy-query
    code paths in commits 2+ will import this.

    Defensive — pass-through for any value that's already clean
    or None.
    """
    if not bbl:
        return bbl
    s = str(bbl).strip()
    if "." in s:
        head, _, tail = s.partition(".")
        if tail and head.isdigit() and set(tail) <= {"0"}:
            return head
    return s


# V2.3 Commit 3 deleted the 9 transitional NYC_* /
# STATISTICAL_BASELINES / INGESTION_STATE collection-name
# constants. The four consumer modules now query Socrata
# directly via lib.statistical_engine.socrata_client, so the
# constants have no remaining callers.
