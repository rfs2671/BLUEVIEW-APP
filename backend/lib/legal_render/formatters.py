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
#:
#: THE LITERAL EM DASH, NOT `&mdash;`, AND THE SAME BYTES AS server.py's
#: NOT_RECORDED. The two must be one string: a test strips the sanctioned
#: phrase and then bans `&mdash;` outright, so an entity-escaped copy reads as
#: an unsanctioned placeholder to the very check that exists to catch invented
#: values. server.py carries a comment at the old local copy's grave saying
#: there were two of these once; this is not the place to make it two again.
NOT_RECORDED = "— Not recorded"

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


def datetime_stamp(v: Any) -> str:
    """`2026-08-07T13:22:04Z` -> `2026-08-07 13:22:04`.

    THE STORED INSTANT, READABLE, NOT REINTERPRETED. The old orientation PDF
    printed exactly this and a test names the string, which is the field-set
    rule doing its job: appearance may change, the recorded value may not.
    """
    s = _s(v)
    if not s:
        return NOT_RECORDED
    return _html.escape(s[:19].replace("T", " "))


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


def sub_company(v: Any) -> str:
    """A subcontractor, with the roster sentinel shown as the pending state.

    UNASSIGNED IS A PLACEHOLDER, NOT A COMPANY. It is written at the gate when
    a worker's sub was not on the project roster at check-in, and an inspector
    reading "UNASSIGNED" on a filed document reads a real firm by that name.

    THE ROW AND ITS HEADCOUNT STAY. Only the label changes: a pending row is
    better than a dropped worker, which is the constraint this rule was
    written under and has not stopped being true.
    """
    s = _s(v)
    if not s or s.upper() == "UNASSIGNED":
        return _html.escape("Pending assignment")
    return _html.escape(s)


#: The whole-line messages. Both mean "there is no reading", for different
#: reasons, and neither is assembled from parts.
WEATHER_UNAVAILABLE = "— Weather could not be retrieved"


def weather_parts(v: Any):
    """(line, condition, temperature, wind) for one day's stored weather.

    ── THE ONE RESOLUTION, AND IT USED TO LIVE IN server.py ─────────────

    Moved here rather than copied: the engine cannot import server, and a
    weather sentence composed in two places is exactly the drift that took two
    banners off ninety-two filed records. `server._weather_parts` now calls
    this and keeps its own name and NamedTuple, so every existing caller and
    the source-count test that pins the pair are untouched.

    THE FETCH STATE WINS over whatever the other fields hold. A temperature
    printed beside "could not be retrieved" is two claims about one reading,
    so on that day no parts are offered at all.

    ALL THREE PARTS ARE EMPTY WHENEVER THE LINE IS A WHOLE-LINE MESSAGE, so a
    surface that prints the fields prints nothing on exactly the days the line
    says there is nothing, and cannot assemble a reading out of pieces this
    function refused.
    """
    d = v if isinstance(v, dict) else {}
    state = _s(d.get("weather_fetch_state")).lower()
    if state in ("offline", "error"):
        return (WEATHER_UNAVAILABLE, "", "", "")
    condition = _s(d.get("weather"))
    temperature = _s(d.get("weather_temp"))
    body = " ".join(p for p in (condition, temperature) if p)
    if not body:
        return (NOT_RECORDED, "", "", "")
    wind = _s(d.get("weather_wind"))
    line = f"{body} — Wind: {wind}" if wind else body
    return (line, condition, temperature, wind)


def weather_line(v: Any) -> str:
    """The composed sentence, for a field bound to the record's `data` map.

    A FORMATTER OF ONE VALUE, which is the contract this file keeps: the value
    it is handed is the data map itself, not a record and not a context. It
    reads four keys off that one value and returns a string.
    """
    return _html.escape(weather_parts(v)[0])


def toggle_list(v: Any) -> str:
    """The ticked keys of a sparse toggle map, as a sentence.

    "NONE" AND "NOT RECORDED" ARE DIFFERENT ANSWERS and this is the one place
    the distinction is drawn for these maps. A map that EXISTS with nothing
    ticked is a man who was asked about each item and said no to all of them:
    that is None. A map that is absent is a form that never asked him, and
    claiming None there would put an answer in his mouth.

    The editors seed these as {} and write a key only when he taps it, so an
    absent key is untouched rather than a silent no -- which is why only the
    true ones are listed and the false ones are not listed as refusals.
    """
    if not isinstance(v, dict):
        return NOT_RECORDED
    on = [str(k).replace("_", " ").title() for k, val in v.items() if val]
    if not on:
        return _html.escape("None") if v else NOT_RECORDED
    return _html.escape(", ".join(on))


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
    "datetime_stamp": datetime_stamp,
    "time_of_day": time_of_day,
    "bbl_borough": bbl_borough,
    "bbl_block": bbl_block,
    "bbl_lot": bbl_lot,
    "yes_no": yes_no,
    "sub_company": sub_company,
    "weather_line": weather_line,
    "toggle_list": toggle_list,
}
