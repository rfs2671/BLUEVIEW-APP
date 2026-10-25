"""The other BINs of a job site, found from the records themselves.

One DOB job can be filed against more than one building of a lot, and a building
keeps its own BIN: the real 588 Thomas S Boyland job's permits sit under BIN
3255362 (stored on the project) and BIN 3430621. The DOB sync asked about the
project's single BIN, so records filed only under the second one never arrived:
the 2026-10 probe found two DOB violations (39558663R, 39558662P) and a complaint
(3A78809) under 3430621 that no report could show.

The rule is the report's own (lib/report_regulatory.split_by_bin): a BIN is part
of the site when one of ITS jobs is also a job under the project's BIN. A BIN that
shares no job with the project is a neighbour's and is never fetched. Pure: no
DB, no HTTP.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

__all__ = ["raw_bin", "raw_job_base", "candidate_bins", "shares_job", "new_records", "MAX_EXTRA_BINS"]

MAX_EXTRA_BINS = 2          # extra BINs asked about per project per sync
_JOB_BASE = re.compile(r"^[A-Za-z]?\d{8,9}")


def raw_bin(rec: Dict[str, Any]) -> str:
    """A dataset record's own 7-digit BIN ('' when it has none)."""
    for k in ("bin", "bin__", "bin_number"):
        v = re.sub(r"\D", "", str(rec.get(k) or ""))
        if v:
            return v
    return ""


def _real(b: str) -> bool:
    return len(b) == 7 and not b.endswith("000000")


def raw_job_base(rec: Dict[str, Any]) -> str:
    """The job a permit / filing belongs to, without its filing suffix."""
    if rec.get("_record_type") not in ("permit", "job_status"):
        return ""
    m = _JOB_BASE.match(str(rec.get("job_filing_number") or rec.get("job__") or "").strip().upper())
    return m.group(0) if m else ""


def candidate_bins(records: Iterable[Dict[str, Any]], own_bin: str, limit: int = MAX_EXTRA_BINS) -> List[str]:
    """Other real BINs the project's returned records carry, most frequent first."""
    own = re.sub(r"\D", "", str(own_bin or ""))
    votes: Dict[str, int] = {}
    for r in records or []:
        if not isinstance(r, dict):
            continue
        b = raw_bin(r)
        if _real(b) and b != own:
            votes[b] = votes.get(b, 0) + 1
    return [b for b, _ in sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))][:limit]


def shares_job(own_records: Iterable[Dict[str, Any]], own_bin: str, other_records: Iterable[Dict[str, Any]],
               other_bin: str) -> bool:
    """True when a job filed under `other_bin` is also filed under the project's BIN."""
    own = re.sub(r"\D", "", str(own_bin or ""))
    mine = {raw_job_base(r) for r in own_records or [] if isinstance(r, dict) and raw_bin(r) == own}
    mine.discard("")
    return any(raw_job_base(r) in mine for r in other_records or []
               if isinstance(r, dict) and raw_bin(r) == other_bin and raw_job_base(r))


def _key(rec: Dict[str, Any]) -> str:
    ident = str(rec.get(rec.get("_id_field", "unique_key"), ""))
    return f"{rec.get('_record_type')}|{rec.get('_collapsed_permit_id') or ''}|{ident}"


def new_records(have: Iterable[Dict[str, Any]], extra: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """`extra` records not already in `have` (same type and id)."""
    seen = {_key(r) for r in have or [] if isinstance(r, dict)}
    out: List[Dict[str, Any]] = []
    for r in extra or []:
        if isinstance(r, dict) and _key(r) not in seen:
            seen.add(_key(r))
            out.append(r)
    return out
