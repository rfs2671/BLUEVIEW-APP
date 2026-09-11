"""THE CLOSED SET OF FORMATTERS A SCHEMA MAY NAME.

A schema declaration is DATA. It binds a label to a dotted path and names one
of these. It may not contain a callable, and `schema.validate` refuses one --
because a declaration that can hold code is a renderer again, and a renderer
that lives in a declaration is how thirteen branches of one `if` came to exist.

So this is the escape hatch, and keeping it a NAMED CLOSED SET is what stops
the escape hatch becoming the thing. Adding a formatter is a deliberate act in
this file, reviewed like any other; it is not something a schema author can do
by writing a lambda inline.

EVERY ONE TAKES A VALUE AND RETURNS A STRING. None reads a record, none reaches
for a database, none knows which document it is on. A formatter that needed any
of that would be a primitive, and the difference is the whole seam.
"""

from __future__ import annotations

import html as _html
import re
from datetime import datetime
from typing import Any, Callable, Dict

#: What a field renders when the record has nothing there. NOT the same as a
#: section being empty -- that is declared per section and handled by the
#: engine. This is one cell with no value in a record that otherwise exists.
NOT_RECORDED = "&mdash; Not recorded"

_BOROUGHS = {"1": "Manhattan", "2": "Bronx", "3": "Brooklyn",
             "4": "Queens", "5": "Staten Island"}


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def text(v: Any) -> str:
    """Escaped, and NOT_RECORDED when absent. The default for anything typed."""
    s = _s(v)
    return _html.escape(s) if s else NOT_RECORDED


def raw_text(v: Any) -> str:
    """Escaped, and EMPTY when absent.

    For a cell whose blankness is the record -- an attendee row that nobody
    filled is blank on paper and must be blank here. NOT_RECORDED in that slot
    would print a finding against a row that does not exist.
    """
    return _html.escape(_s(v))


def name(v: Any) -> str:
    """A person's or company's name, first letter up, rest untouched.

    NEVER title-cased. "MQ Steel" and "O'Connor" and "DeLuca" are how people
    and companies spell themselves, and a document that respells a man's name
    is wrong about the one thing it exists to record.
    """
    s = _s(v)
    if not s:
        return NOT_RECORDED
    return _html.escape(s[0].upper() + s[1:])


def sentence(v: Any) -> str:
    """Prose the user typed. First letter up, nothing else touched."""
    s = _s(v)
    if not s:
        return NOT_RECORDED
    return _html.escape(s[0].upper() + s[1:])


def date_long(v: Any) -> str:
    """`2026-09-10` -> `10 September 2026`. The STORED STRING, never a Date.

    Parsing to a datetime and back re-introduces a timezone into a value that
    has none: a filed log's date is a calendar day on a jobsite, not an instant.
    """
    s = _s(v)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return _html.escape(s) if s else NOT_RECORDED
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    try:
        return f"{int(m.group(3))} {months[int(m.group(2)) - 1]} {m.group(1)}"
    except (IndexError, ValueError):
        return _html.escape(s)


def time_of_day(v: Any) -> str:
    """Whatever the man typed, or an ISO instant reduced to its clock time."""
    s = _s(v)
    if not s:
        return NOT_RECORDED
    if "T" in s and len(s) >= 16:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%-I:%M %p")
        except (ValueError, TypeError):
            try:
                return datetime.fromisoformat(s[:19]).strftime("%I:%M %p").lstrip("0")
            except (ValueError, TypeError):
                pass
    return _html.escape(s)


def bbl_borough(v: Any) -> str:
    """Borough from the first digit of a BBL.

    PROVENANCE, BECAUSE THIS IS A LEGAL RECORD: `projects.bbl` is written by an
    address lookup at project creation (`bbl_source`), NOT read off a DOB
    filing. It is the only source the app has for block and lot, and a reader
    should know the difference between a geocoder's answer and a filed one.
    """
    s = re.sub(r"\D", "", _s(v))
    return _BOROUGHS.get(s[:1], NOT_RECORDED) if len(s) == 10 else NOT_RECORDED


def bbl_block(v: Any) -> str:
    """Digits 2-6 of a BBL. See bbl_borough for where the BBL comes from."""
    s = re.sub(r"\D", "", _s(v))
    return str(int(s[1:6])) if len(s) == 10 else NOT_RECORDED


def bbl_lot(v: Any) -> str:
    """Digits 7-10 of a BBL. See bbl_borough for where the BBL comes from."""
    s = re.sub(r"\D", "", _s(v))
    return str(int(s[6:10])) if len(s) == 10 else NOT_RECORDED


def yes_no(v: Any) -> str:
    """A stored boolean. ABSENT IS NOT NO -- it is not recorded, and a
    compliance document that prints "No" for a question nobody answered has
    made a claim nobody made."""
    if v is None or v == "":
        return NOT_RECORDED
    return "Yes" if bool(v) else "No"


#: THE WHOLE SET. A schema may name these and nothing else.
FORMATTERS: Dict[str, Callable[[Any], str]] = {
    "text": text,
    "raw_text": raw_text,
    "name": name,
    "sentence": sentence,
    "date_long": date_long,
    "time_of_day": time_of_day,
    "bbl_borough": bbl_borough,
    "bbl_block": bbl_block,
    "bbl_lot": bbl_lot,
    "yes_no": yes_no,
}
