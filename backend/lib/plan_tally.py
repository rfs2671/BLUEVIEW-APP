"""What a count of located symbols is allowed to claim.

A total is bound to records the way a schedule figure is. The difference is
that a registered glyph is ASSEMBLED — located by geometry, named by a label
read beside it — so a record can exist while not knowing what it is, and a
unit can exist while never having been registered. Neither may be quietly
folded into a number.

── TWO REFUSALS, AND NEITHER IS SILENCE ───────────────────────────────────

A GLYPH THAT DOES NOT KNOW WHAT IT IS cannot be in a total. If one of eight
fans is unread, `8` is not available — but `7` is, because seven records each
resolved to a tag. So the answer is "7 EF-1 located; 1 more EF glyph in 4A
unread": the seven is bound, the remainder is STATED rather than counted, and
nothing rests on a record that could not name itself.

A UNIT THAT WAS NEVER REGISTERED is not a unit with zero. "2 per unit" binds
only across units that were registered and partitioned; for any other the
claim is UNSUPPORTED, which is a different thing from a count of none. A
mechanical sheet whose floor has no architectural plan in the set can still
say "8 EF glyphs on M-103.00" at sheet scope, and must not say which unit.

Both are the same principle as the tiers: the output says how it knows, and
declines the part it does not.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence

#: A glyph that resolved to exactly one tag from the schedule's closed set.
RESOLVED = "resolved"
#: Located, but no label could be read and no rating corroborated it.
UNREAD = "unread"
#: The printed label and the cross-check disagree. Never picked between.
CONTESTED = "contested"
#: A unit in scope that could not be registered or partitioned at all. WRITTEN
#: AS A RECORD, because a unit that produced no records is indistinguishable
#: from a unit containing nothing unless something says which it was.
UNSUPPORTED_UNIT = "unsupported_unit"

UNBOUND_STATUSES = (UNREAD, CONTESTED, UNSUPPORTED_UNIT)


class Tally(NamedTuple):
    total: Optional[int]                 # None when the total may not be claimed
    resolved: int                        # how many records carry a tag
    by_unit: Dict[str, Dict[str, int]]   # unit -> tag -> n, resolved only
    by_tag: Dict[str, int]
    unresolved: List[tuple]              # (unit_or_None, status)
    unsupported_units: List[str]         # in scope, never registered
    placed_units: List[str]

    @property
    def bound(self) -> bool:
        return self.total is not None


def tally(records: Sequence[dict],
          scope_units: Optional[Iterable[str]] = None,
          unregistered_units: Optional[Iterable[str]] = None) -> Tally:
    """Count located symbols, refusing any total that rests on a record
    which does not know what it is or a unit that was never registered.

    Each record: {"tag": str|None, "unit": str|None, "status": ...}.

    `unregistered_units` IS EXPLICIT AND IS NOT DERIVED FROM ABSENCE. A unit
    holding no EF-2 is a unit with no EF-2 — a true count of none. A unit that
    could not be registered is a unit nothing is known about. Deriving the
    second from the first made a tally announce "no registration for 4D" when
    4D was registered perfectly well and simply had its one glyph unread, and
    it would announce the same for any unit that genuinely has none of a tag.
    """
    by_unit: Dict[str, Dict[str, int]] = defaultdict(Counter)
    by_tag: Counter = Counter()
    unresolved: List[tuple] = []
    resolved = 0
    for r in records:
        status = r.get("status") or (RESOLVED if r.get("tag") else UNREAD)
        if status != RESOLVED or not r.get("tag"):
            unresolved.append((r.get("unit"), status))
            continue
        resolved += 1
        by_tag[r["tag"]] += 1
        if r.get("unit"):
            by_unit[r["unit"]][r["tag"]] += 1

    placed = sorted(by_unit)
    scope = sorted(scope_units) if scope_units is not None else placed
    named_unreg = {str(u) for u in (unregistered_units or [])}
    named_unreg |= {str(u) for u, s in unresolved
                    if s == UNSUPPORTED_UNIT and u}
    unsupported = sorted(u for u in scope if u in named_unreg) or \
        sorted(named_unreg)

    total = resolved if (not unresolved and not unsupported) else None
    return Tally(total=total, resolved=resolved,
                 by_unit={u: dict(v) for u, v in by_unit.items()},
                 by_tag=dict(by_tag), unresolved=unresolved,
                 unsupported_units=unsupported, placed_units=placed)


def statement(t: Tally, noun: str = "glyph") -> str:
    """One quotable sentence. The bound part leads; the rest is named.

    Never returns an empty string for a tally with findings in it: an answer
    that declines the total still owes the reader what it does know.
    """
    parts: List[str] = []
    if t.by_tag:
        parts.append("; ".join(f"{n} {tag} located"
                               for tag, n in sorted(t.by_tag.items())))
    elif t.resolved:
        parts.append(f"{t.resolved} {noun}s located")

    if t.unresolved:
        per = Counter(
            (u or "unplaced", s) for u, s in t.unresolved)
        bits = [f"{n} more {noun} in {u} {s}" if u != "unplaced"
                else f"{n} more {noun} {s}, not placed"
                for (u, s), n in sorted(per.items())]
        parts.append("; ".join(bits))

    n_unplaced = unplaced(t)
    if n_unplaced:
        parts.append(
            f"{n_unplaced} of them could not be placed in a unit, so the "
            f"per-unit split is not available — the total still holds")

    if t.unsupported_units:
        parts.append(
            f"no registration for {', '.join(t.unsupported_units)}, so the "
            f"per-unit figure is unsupported there — not zero")

    return ". ".join(p for p in parts if p) + ("." if parts else "")


def unplaced(t: Tally) -> int:
    """Resolved symbols that no unit could be found for.

    They count in the TOTAL — the sheet really does carry them — and they
    must not count in any per-unit figure, because the unit they belong to
    is precisely what is unknown.
    """
    return t.resolved - sum(sum(v.values()) for v in t.by_unit.values())


def per_unit(t: Tally) -> Optional[Dict[str, int]]:
    """Counts per unit, or None when the per-unit claim may not be made.

    THREE WAYS IT MAY NOT BE MADE, and the third was found by fixing a crop.

    A unit in scope that was never registered makes the whole shape
    unsupported: reporting three of four units as "2 each" invites the fourth
    to be read as the same, and it is not known at all.

    An unresolved glyph does the same, for the same reason.

    AND A RESOLVED SYMBOL WITH NO UNIT does it too. Measured: with the sheet
    crop corrected, one of eight exhaust fans could not be placed, and the
    per-unit figure came back {4A: 1, 4B: 2, 4C: 2, 4D: 2} — 4A reading as
    one when the unplaced fan is very likely its second. The total was right
    and the distribution was wrong, which is worse than either being absent.
    """
    if t.unsupported_units or t.unresolved or unplaced(t):
        return None
    return {u: sum(v.values()) for u, v in t.by_unit.items()}


__all__ = ["RESOLVED", "UNREAD", "CONTESTED", "UNSUPPORTED_UNIT",
           "UNBOUND_STATUSES",
           "Tally", "tally", "statement", "per_unit", "unplaced"]
