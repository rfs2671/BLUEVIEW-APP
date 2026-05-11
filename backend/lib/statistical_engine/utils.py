"""Phase V2.3 Commit 1 — Statistical-engine utility module.

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

Plus, **transitionally**, the collection-name constants for the
nyc_* mirror tables. V2.3 Commit 1 removed these from
``schema.py`` per spec, but the four consumer files (baselines.py,
triggers.py, score.py, calibration.py) still reference them by
name. Commit 3 rewrites those consumers to lazy Socrata queries,
at which point these constants are deleted entirely. Until then
they live here as orphans — the Mongo collections behind them
are dropped post-deploy by the operator and queries return empty,
which is the spec-acknowledged failure mode pending Commit 3.
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


# ── Transitional: nyc_* collection-name constants ────────────────
#
# Pre-V2.3 these lived in lib/statistical_engine/schema.py. V2.3
# Commit 1's spec removed them from schema.py because the local
# mirror is being deprecated. But the consumers (baselines.py,
# triggers.py, score.py, calibration.py) still reference these
# names — they're untouched by Commit 1 per spec, and rewritten
# to lazy Socrata queries by Commit 3.
#
# Holding the names here keeps the consumer imports valid. After
# Commit 3 lands, these constants get deleted entirely (the
# rewritten consumers don't reference local-mirror names at all).

NYC_VIOLATIONS_COLLECTION       = "nyc_violations"
NYC_INSPECTIONS_COLLECTION      = "nyc_inspections"
NYC_PERMITS_COLLECTION          = "nyc_permits"
NYC_COMPLAINTS_311_COLLECTION   = "nyc_complaints_311"
NYC_ECB_VIOLATIONS_COLLECTION   = "nyc_ecb_violations"
NYC_HPD_VIOLATIONS_COLLECTION   = "nyc_hpd_violations"
NYC_PLUTO_COLLECTION            = "nyc_pluto"
STATISTICAL_BASELINES_COLLECTION = "statistical_baselines"
INGESTION_STATE_COLLECTION       = "ingestion_state"
