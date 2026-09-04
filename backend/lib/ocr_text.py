"""The one rule for what a vision model's string field actually contains.

A VLM asked to "set the field to null if you cannot read it" answers in JSON,
and JSON has a null. It does not always use it. `"null"`, `"None"`, `"N/A"` and
`"-"` are all things these models return AS STRING VALUES, and every one of
them is truthy in Python and in JavaScript.

WHAT THAT COST HERE. Worker `6a96c5ff6ee1b3362d156e6c` carries
`name: 'null'` and `osha_data.name: 'null'` — the four-character string, in
both places, on a live production record. It reaches filed compliance PDFs as
a worker called "null". Worse, it satisfies every presence test between the
model and the database:

    server.py   name_ok = bool(str(od.get("name") or "").strip())
                -> True, so `needs_review` is computed as if the name were read.
                A card nobody could read CLEARS the review flag that exists to
                catch exactly that.

    checkin.html  ocrMissingCriticalFields: !d[k] || String(d[k]).trim() === ''
                -> "null" is truthy and trims to "null", so a total OCR
                failure scores as a COMPLETE read and the worker is never
                asked to retake the photo.

    normalisers   "null" is a live dedupe key: two unreadable cards collapse
                to one worker, which is the opposite failure from the case
                variance that SPLITS one worker into two.

Three independent consumers, each correct against a real value and each wrong
against this one, because none of them could tell "the model said null" from
"the model said the word null".

THE RULE BELONGS AT THE BOUNDARY, not at the three consumers. A value that was
never read must arrive as None, once, where the model's answer is parsed —
otherwise every future reader is a fourth place to get it wrong.

`coi_ocr._norm_str` has had this rule since the COI path was written and is the
only OCR path in this codebase that carried it. This module is that same
function with one address, so the OSHA path and the COI path cannot drift —
the same reason `lib/cert_vocab.py` exists.
"""

from __future__ import annotations

from typing import Optional

# LOWERCASED, and compared after strip(). These are the tokens observed from
# the models this project actually calls, plus the two spellings of "nothing"
# that any JSON-emitting model produces. Adding one is cheap; the cost of a
# missing one is a string that reads as data.
_NULLISH = {"null", "none", "n/a", "na", "nil", "-", "--", "undefined"}


def norm_ocr_str(v) -> Optional[str]:
    """A model's string field, or None when it did not read one.

    None for: an actual None, an empty or whitespace-only string, and any of
    the _NULLISH tokens above regardless of case. Everything else is returned
    stripped.

    NON-STRINGS ARE COERCED, deliberately. A model that answers `sst_number:
    12345` as a JSON number is not wrong about the card, and rejecting it would
    turn a good read into a failure. `str()` first, then the same rule.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in _NULLISH:
        return None
    return s


__all__ = ["norm_ocr_str"]
