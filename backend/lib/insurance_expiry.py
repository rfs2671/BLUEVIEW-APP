"""HOW `companies.gc_insurance_records[].expiration_date` IS READ AND WRITTEN.

── THE DEFECT THIS CLOSES ──────────────────────────────────────────────────

Two readers consume an insurance expiry, and both of them answered `None` for
a string they could not parse:

    lib/renewal_digest.py    `_utc` -> None -> `continue`
    lib/eligibility_v2.py    `_utc` -> None -> the record is not a candidate

`None` is also what an ABSENT date gives, so the two cases were indistinguishable
and the consequence differed only in how quietly it went wrong:

  THE DIGEST sent no T-30/T-14/T-7/T-5/T-0 alert for that policy. Ever. Not a
  late alert — no alert, for the life of the record, and nothing in the run
  said a record had been skipped.

  THE PERMIT EXPIRY dropped the record from the `min()` over GL/WC/DBL/licence/
  issuance+365. When another candidate existed the permit still resolved a
  strategy and read as AUTO_EXTEND, which is the bad shape: not "we don't know",
  but a confident answer computed with a required input missing.

An insurance certificate whose expiry nobody can read is not a company without
insurance. It is a company whose insurance state is UNKNOWN, and the two need
different things done about them.

── WHAT THIS MODULE IS, AND WHAT IT IS NOT ─────────────────────────────────

It holds TWO readers because a reader and a writer are asked different
questions, and giving them one answer would either narrow what already-stored
records are allowed to say or widen what new ones may be written.

  `read_expiry`  FOR THE TWO READERS. Parses with `dateutil`, exactly as the
                 `_utc` helpers it replaces did, so NOTHING already readable
                 becomes unreadable with this deploy. What changes is only that
                 a failure is REPORTED: it logs an error and the result says
                 `unreadable`, distinct from `blank`.

  `normalise_stored_expiry`  FOR A WRITER. Strict: `YYYY-MM-DD`, or eight
                 digits in MMDDYYYY order with the slashes optional. Returns
                 ISO or raises. This is the same acceptance rule as
                 `parseStoredDate` in frontend/src/utils/dateEntry.js, so a
                 value the shared date field showed the admin and a value this
                 accepts are the same set.

IT IS NOT A THIRD CALENDAR. The strict reader validates the day with
`datetime.strptime('%Y-%m-%d')` — the stdlib's own Gregorian rule, which is
what dateEntry.js's month-length table was written to match. There is no leap
year arithmetic in this file to drift from it.

IT IS NOT A CLOCK. Nothing here decides whether a date has passed; that is the
digest's threshold logic and eligibility's `min()`.

IT LIVES IN `lib/` and imports nothing from `server.py`, because server.py
imports lib. That is also why `logbook_date_is_real` (server.py, the
SUBMIT_INVALID_DATE gate) is not called from here: same rule, other direction,
and a test pins the two to one answer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


#: WHAT THE ADMIN IS TOLD. One sentence for every surface — the permit-renewal
#: blocking reasons, the nightly digest row, and the badge on the owner panel
#: and Settings (frontend/src/utils/insuranceExpiry.js holds the same string,
#: and insuranceExpiry.test.cjs reads THIS line to keep them identical). An
#: admin who sees it in the email and then on the screen must be able to tell
#: it is one problem.
INSURANCE_DATE_UNREADABLE = "insurance date unreadable"

#: The year bound the typed field applies (dateEntry.js MIN_YEAR/MAX_YEAR) and
#: the SUBMIT_INVALID_DATE gate applies (server.LOGBOOK_DATE_MIN/MAX_YEAR).
#: Repeated here rather than imported because server.py imports this module;
#: `test_insurance_expiry.py` asserts the three agree.
MIN_YEAR = 1900
MAX_YEAR = 2199

#: How much of a stored value a message quotes. The blocking reason is read on
#: a phone, and this field has held free text.
QUOTE_MAX = 64

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
#: MMDDYYYY with a slash optionally after the MM and optionally after the DD.
#: TWO DIGITS AND A FOUR-DIGIT YEAR, not `\d{1,2}`: '7/2/29' is refused rather
#: than guessed at, because nothing here can tell a dropped digit from a
#: two-digit year, and the digits are never reordered ('21/07/2029' has no
#: month 21 and is NOT re-read as DD/MM). Same rule, same reasons, as
#: `parseStoredDate`.
_LEGACY_US = re.compile(r"^(\d{2})/?(\d{2})/?(\d{4})$")

#: The three types a company carries one record of, with the label an admin
#: reads. Duplicated from eligibility_v2.INSURANCE_TYPES would be two lists to
#: keep in step, so that module imports this one.
INSURANCE_TYPES: List[Tuple[str, str]] = [
    ("general_liability", "General Liability"),
    ("workers_comp",      "Workers' Comp"),
    ("disability",        "Disability"),
]


def quote(value) -> str:
    """A stored value as a message quotes it: verbatim, and bounded."""
    text = value if isinstance(value, str) else repr(value)
    text = text.strip()
    return text if len(text) <= QUOTE_MAX else text[:QUOTE_MAX - 1] + "…"


@dataclass(frozen=True)
class ExpiryRead:
    """What a stored expiry amounts to.

    THREE OUTCOMES, NEVER TWO. `blank` and `unreadable` were one answer before
    this module and that is the whole defect; a caller that cannot act on the
    difference should still be made to say which it is handling.
    """

    raw: str
    at: Optional[datetime]      # UTC-aware, or None
    unreadable: bool

    @property
    def blank(self) -> bool:
        return self.at is None and not self.unreadable

    def __bool__(self) -> bool:
        # NOT DEFINED AS "did we get a date", deliberately. `if read:` reads as
        # the old `if exp:` and would put an unreadable record back on the
        # silent path. A caller must ask `.at`, `.blank` or `.unreadable`.
        raise TypeError(
            "ExpiryRead has three outcomes; test .at, .blank or .unreadable "
            "explicitly rather than its truthiness")


def read_expiry(raw, *, where: str = "") -> ExpiryRead:
    """Read a stored expiry for a READER. Logs an error when it cannot.

    `where` names the record in the log line — "company=<id> general_liability"
    — because a log line saying only that some date somewhere was unreadable
    cannot be acted on.

    ACCEPTANCE IS UNCHANGED from the `_utc` helpers this replaces: `dateutil`,
    naive values treated as UTC. A deploy that suddenly called a stored value
    unreadable would raise alerts about data that is fine, which is the
    opposite of the point.

    A `datetime` already on the record passes through. Mongo can hold one, and
    a BSON date is not a parse failure.
    """
    if raw is None:
        return ExpiryRead(raw="", at=None, unreadable=False)

    if isinstance(raw, datetime):
        at = raw.replace(tzinfo=timezone.utc) if raw.tzinfo is None else raw.astimezone(timezone.utc)
        return ExpiryRead(raw=raw.isoformat(), at=at, unreadable=False)

    text = str(raw).strip()
    if not text:
        return ExpiryRead(raw="", at=None, unreadable=False)

    try:
        from dateutil import parser as dp
        parsed = dp.parse(text)
    except Exception as e:
        # `%r`, and the whole exception: a ParserError stringifies to something
        # useful but a ValueError from a nonsense month does not always, and a
        # log line naming only the type is one step better than silence.
        logger.error(
            "%s: %s %s — %r", INSURANCE_DATE_UNREADABLE,
            f"[{where}]" if where else "[unknown record]", quote(text), e,
        )
        return ExpiryRead(raw=text, at=None, unreadable=True)

    at = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    return ExpiryRead(raw=text, at=at, unreadable=False)


def unreadable_records(company: dict) -> List[Tuple[str, str, str]]:
    """(insurance_type, label, quoted raw) for every record on this company
    whose expiry cannot be read. Empty list when they are all fine.

    DERIVED FROM THE COMPANY'S OWN RECORDS, not from the three known types: a
    record carrying a fourth `insurance_type` still has an expiry that either
    reads or does not, and skipping it here would be a new silence in the place
    the old one was just removed. Its label falls back to the raw type.
    """
    labels = dict(INSURANCE_TYPES)
    out: List[Tuple[str, str, str]] = []
    company_id = str((company or {}).get("_id") or "")
    for rec in (company or {}).get("gc_insurance_records") or []:
        if not isinstance(rec, dict):
            continue
        ins_type = str(rec.get("insurance_type") or "unknown")
        read = read_expiry(
            rec.get("expiration_date"),
            where=f"company={company_id} {ins_type}",
        )
        if read.unreadable:
            out.append((ins_type, labels.get(ins_type, ins_type), quote(read.raw)))
    return out


def unreadable_blocking_reason(company: dict) -> Optional[str]:
    """The sentence the permit-renewal screen shows, or None.

    ONE REASON FOR THE WHOLE COMPANY, listing every affected type. Three
    unreadable records on one company are one thing to go and fix in Settings,
    and three near-identical rows in `blocking_reasons` would push the other
    reasons off a phone screen.
    """
    bad = unreadable_records(company)
    if not bad:
        return None
    named = ", ".join(f'{label} ("{raw}")' for _, label, raw in bad)
    return (
        f"{INSURANCE_DATE_UNREADABLE}: {named}. This is NOT the same as no "
        "insurance on file — the expiry is on the record and cannot be read, "
        "so permit expiry cannot be computed from it. Re-enter the date in "
        "Settings as MM/DD/YYYY."
    )


def normalise_stored_expiry(raw) -> str:
    """A value a WRITER may store, as `YYYY-MM-DD`. Raises `ValueError`.

    THE STORED FORMAT IS ISO, as of this deploy. It sorts, it states its own
    field order, and it is what the shared date field already sends
    (`toStoredDate`). MM/DD/YYYY is still READ everywhere — every active reader
    accepts both, and `scripts/backfill_insurance_expiry_iso.py` converts what
    is already stored — but nothing writes it any more.

    STRICT, and narrower than `read_expiry` on purpose. A reader must live with
    whatever is on the record; a writer decides what goes onto it, and this is
    the last point at which a person can be told the date was not understood.
    Accepting '7/2/29' here would put a guess into a compliance record.

    The message is the one the admin sees, so it names the value and the
    format — not "invalid date".
    """
    if isinstance(raw, datetime):
        return raw.date().isoformat()

    text = "" if raw is None else str(raw).strip()
    if not text:
        raise ValueError("A date is required. Enter it as MM/DD/YYYY.")

    iso = _ISO.match(text)
    us = _LEGACY_US.match(text)
    if iso:
        y, m, d = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
    elif us:
        m, d, y = int(us.group(1)), int(us.group(2)), int(us.group(3))
    else:
        raise ValueError(
            f'"{quote(text)}" is not a date this app can read. '
            "Enter it as MM/DD/YYYY."
        )

    if not MIN_YEAR <= y <= MAX_YEAR:
        raise ValueError(
            f"Check the year — {y:04d} is outside {MIN_YEAR}–{MAX_YEAR}."
        )
    try:
        # THE STDLIB IS THE CALENDAR. 02/30 and 02/29 of a non-leap year are
        # refused here, by the same rule dateEntry.js applies with its month
        # table, without a second copy of that table in this file.
        datetime.strptime(f"{y:04d}-{m:02d}-{d:02d}", "%Y-%m-%d")
    except ValueError:
        raise ValueError(
            f'"{quote(text)}" is not a day that exists. Enter it as MM/DD/YYYY.'
        ) from None
    return f"{y:04d}-{m:02d}-{d:02d}"
