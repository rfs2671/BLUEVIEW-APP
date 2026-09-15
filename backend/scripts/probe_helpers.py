"""HELPERS FOR PRODUCTION PROBES — so a count on a field nobody stores is an
ERROR, not a confident zero.

WHY THIS EXISTS, MEASURED. Three times in one session a probe asked Mongo for a
field the collection does not have and reported the answer as a finding:

  * `document_page_index.created_at`  -> "0 pages indexed in 30 days".
    The field is `indexed_at`. The collection had 149 rows.
  * `document_page_index.searchable_text` -> "149 rows with EMPTY text".
    There is no such field; the schema stores `keywords`, `sheet_number`,
    `sheet_title`, `discipline`, `floor`.
  * `workers.certifications[].osha_data` -> "the scan captured no class at
    all" for 8 workers. The payload lives on the WORKER document, not the
    certification, and 4 of the 8 had a class the whole time.

Every one returned a clean-looking number. A zero from a missing field is
indistinguishable from a zero from an empty result, and it reads as evidence.

THE RULE: read the keys before you count on them.

    from probe_helpers import sample_keys, require_fields, counted

    rows = await db.document_page_index.find({}).to_list(500)
    print(sample_keys(rows))                    # print them, always
    require_fields(rows, "indexed_at")          # raises if absent
    n = counted(rows, "indexed_at", lambda v: v is None)

These are deliberately SYNCHRONOUS helpers over an already-fetched list rather
than a wrapper around the driver: a probe should hold its sample and be able to
show it, not stream past it.
"""
from typing import Any, Callable, Dict, Iterable, List, Sequence


class FieldNotInSample(KeyError):
    """A field was counted on, and no sampled document carries it."""


def sample_keys(rows: Sequence[Dict[str, Any]], limit: int = 50) -> List[str]:
    """Every key seen across the first `limit` documents, sorted.

    Print this BEFORE any count. It is one line and it is the whole rule.
    """
    seen = set()
    for r in list(rows)[:limit]:
        if isinstance(r, dict):
            seen |= set(r.keys())
    return sorted(seen)


def require_fields(rows: Sequence[Dict[str, Any]], *fields: str,
                   limit: int = 50) -> None:
    """Raise unless every named field appears on at least one sampled doc.

    An empty `rows` raises too: counting a field across nothing is exactly the
    case that produced "0 pages indexed in 30 days".
    """
    if not rows:
        raise FieldNotInSample(
            f"sample is empty; cannot confirm {fields!r} exist. A count here "
            f"would be a zero from an absent collection, not from an absent "
            f"value.")
    present = set(sample_keys(rows, limit))
    missing = [f for f in fields if f not in present]
    if missing:
        raise FieldNotInSample(
            f"{missing!r} on no sampled document. Present keys: "
            f"{sorted(present)!r}. Counting on a missing field returns 0 and "
            f"reads as a finding.")


def counted(rows: Sequence[Dict[str, Any]], field: str,
            predicate: Callable[[Any], bool] = lambda v: True,
            limit: int = 50) -> int:
    """Count documents whose `field` satisfies `predicate` — after proving the
    field exists in the sample. Use this instead of a bare comprehension."""
    require_fields(rows, field, limit=limit)
    return sum(1 for r in rows if isinstance(r, dict) and predicate(r.get(field)))


def describe(rows: Sequence[Dict[str, Any]], *fields: str,
             limit: int = 50) -> str:
    """One printable block: row count, keys, and the null rate per field.

    Intended as the FIRST thing a probe prints about any collection.
    """
    out = [f"rows sampled: {len(rows)}", f"keys: {sample_keys(rows, limit)}"]
    for f in fields:
        try:
            nulls = counted(rows, f, lambda v: v is None, limit=limit)
            out.append(f"  {f}: present, {nulls} null of {len(rows)}")
        except FieldNotInSample:
            out.append(f"  {f}: ABSENT FROM SAMPLE — do not count on it")
    return "\n".join(out)


__all__ = ["FieldNotInSample", "sample_keys", "require_fields", "counted",
           "describe"]
