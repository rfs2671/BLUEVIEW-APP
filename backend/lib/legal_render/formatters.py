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
from datetime import datetime, timezone  # noqa: F401
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


def _as_eastern_instant(when) -> datetime:
    """A stored instant, MOVED to New York — or ValueError, never a guess.

    THIS LIVED IN server.py AND THE ENGINE CANNOT REACH server.py. A renderer
    that prints a check-in time needs the conversion, `lib/legal_render` must
    never import the app, and the alternative -- a second copy of the rule
    beside the first -- is the failure this migration keeps finding. So the
    rule moved DOWN to the library and `server` imports it; there is one
    definition and every caller, old branch and engine alike, is on it.

    `eastern_date` calls itself "the only date source" and that rule was simply
    never extended to TIMES. Nothing owned the clock, so `_roster_clock` parsed
    a check-in stored as `2026-08-11T10:47:05Z` — correctly, tz-aware, UTC —
    and then called `.strftime("%I:%M %p")` straight on it. strftime formats
    whatever zone the datetime is already in, so the roster on a signed
    §3301.12.3 attendance record printed 10:47 for a man who walked through the
    gate at 6:47 AM EDT. Four hours, on every report since the field existed.

    IT REFUSES RATHER THAN PASSES THROUGH, and that is the whole design. A
    naive datetime is a value that has NOT said what zone it is in; treating
    its digits as New York's is precisely the assumption that produced the bug,
    and doing it silently is what let the bug live. So a caller with an
    unanchored value gets an exception and has to decide what to do about it —
    `roster_clock` prints the raw string, because an unanchored wall clock on
    an old roster is a fact about the record and not something to invent a zone
    for.

    Accepts a datetime or an ISO-8601 string (trailing 'Z' included). Returns
    an aware datetime in America/New_York; DST is the zone's business, never a
    hard-coded -4 or -5.
    """
    from zoneinfo import ZoneInfo
    if isinstance(when, datetime):
        dt = when
    else:
        text_ = str(when).strip() if when is not None else ""
        if not text_:
            raise ValueError("not an instant: nothing to convert")
        try:
            dt = datetime.fromisoformat(text_.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"not an instant: {when!r}") from exc
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"not an instant — no timezone on {when!r}")
    return dt.astimezone(ZoneInfo("America/New_York"))


def eastern_clock(when) -> str:
    """The NEW YORK wall-clock time for an instant, as '6:47 AM EDT'.

    THE ONLY TIME SOURCE, the way `eastern_date` is the only date source. Every
    user-facing time conversion goes through here; a renderer that formats a
    clock itself has opted out of the one place DST is handled.

    THE STRING CARRIES ITS ZONE. "10:47" said nothing about what it was a time
    in, which is why nobody could see it was wrong by looking at it. "6:47 AM
    EDT" can be checked against the record by anyone holding both.

    Raises ValueError on anything that is not an anchored instant — see
    `_as_eastern_instant`.
    """
    return _as_eastern_instant(when).strftime("%I:%M %p %Z").lstrip("0")


def roster_clock(v: Any) -> str:
    """A roster row's check-in time, IN NEW YORK.

    The toolbox roster carries the §3301.12.3 required fields (name, title,
    company, date/time); this renders the time for the sheet, and it is a
    FORMATTER rather than a helper because the engine's declaration names it.

    IT USED TO PRINT THE UTC DIGITS — see `_as_eastern_instant` for the four
    hours that cost. `eastern_clock` owns that conversion and no other renderer
    does it.

    AN UNANCHORED VALUE IS PRINTED AS ITSELF. `weeklyGapAttendee` writes
    `time: ''` and older rosters hold typed wall-clock strings like "07:15".
    Those carry no zone, so there is nothing to convert -- `eastern_clock`
    refuses them rather than guessing, and they print exactly as they always
    did. Never a parse error onto a legal record.

    EM-DASH FOR NOTHING, NOT `NOT_RECORDED`. This is a roster cell, and the
    branch printed an em-dash; a row whose time the gate never wrote is blank
    on the paper rather than carrying a finding against the man in it.
    """
    if not v:
        return "&mdash;"
    try:
        return eastern_clock(v)
    except Exception:
        return _html.escape(str(v)[:16])


#: The three provenances the app records, and nothing else.
_ATTENDEE_SOURCES = {
    "gate": "Gate",
    "weekly_gap": "CP &mdash; this week",
    "manual": "CP &mdash; added",
}


def attendee_source(v: Any) -> str:
    """WHOSE CLAIM PUT THIS MAN ON THE SHEET.

    Three provenances, recorded by the app as `added_from`:

      'gate'         he checked in TODAY - the gate says he was on site
      'weekly_gap'   he worked this WEEK; the CP is asserting he attended
      'manual'       the CP typed him in; the app knows nothing about him

    A toolbox talk is a WEEKLY obligation built from a DAILY roster, so the CP
    can now add men who worked earlier in the week. That is a genuinely weaker
    claim than a gate check-in, and a signed attendance record that renders the
    two identically is the stronger one lending its authority to the weaker -
    which is the whole reason the field is stored.

    AN OLD RECORD HAS NO `added_from`. Every attendee filed before the field
    existed came from the gate or from the CP's own typing with no way to tell
    which, and inventing a label for those would be the same false confidence
    this column exists to remove. They read as an em-dash: we do not know, and
    the record says so.

    A KEY THIS MAP DOES NOT HOLD READS THE SAME WAY. `text` would have printed
    the stored token -- a filed attendance record with `weekly_gap` under a
    column headed "Added by" -- and an unknown fourth provenance is exactly as
    unknown as an absent one. The set is closed on purpose.
    """
    return _ATTENDEE_SOURCES.get(_s(v).lower(), "&mdash;")


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

    ── AN EMPTY MAP IS THE SEEDED ONE, AND THIS GOT IT BACKWARDS ──────────

    The sentence above is what this was written to do and `if v else` is not
    how it did it. `{}` is FALSY, so the seeded map -- the exact case the
    paragraph describes -- fell to "not recorded" alongside the absent one,
    and the two answers the docstring separates were printed the same.

    IT REACHED FILED DOCUMENTS. The daily jobsite branch printed
    `equip_list or "None"`, so 32 of its 59 filed records said "Equipment:
    None"; after that conversion the same 32 said "Equipment on Site — Not
    recorded". The old-against-new word diff DID list `none` as lost on 32
    records and it was read past, which is the second time a conversion's
    finding has been in the report and not in the reader.

    ABSENCE IS STILL ABSENCE. One daily record carries no `equipment_on_site`
    key at all and the branch printed None for it too, because `.get(key, {})`
    folds the two together before the renderer ever sees them. That one record
    changes, deliberately: the form did not ask, and a sheet that answers for
    it is the thing this function exists to refuse.
    """
    if not isinstance(v, dict):
        return NOT_RECORDED
    on = [str(k).replace("_", " ").title() for k, val in v.items() if val]
    if not on:
        return _html.escape("None")
    return _html.escape(", ".join(on))

#: The spellings this product actually stores. Pre-shift writes the
#: lowercase words; other forms write booleans.
_YES_WORDS = {"yes", "y", "true", "1"}
_NO_WORDS = {"no", "n", "false", "0"}


def answer(v: Any) -> str:
    """Yes, No, or whatever the man actually answered.

    THREE ANSWERS AND AN ABSENCE, which is a different shape from `yes_no`:
    this is for a field whose stored value is the ANSWER ITSELF rather than a
    flag, so "N/A" is a third thing he chose and not a missing value.

    UNRECOGNISED VALUES ARE RETURNED AS WRITTEN. A form that grows a fourth
    option must print it, not fall back to one of the three -- and a renderer
    guessing at a compliance answer is the defect this whole file exists to
    refuse.
    """
    if v is None:
        return NOT_RECORDED
    if isinstance(v, bool):
        return "Yes" if v else "No"
    s = _s(v)
    if not s:
        return NOT_RECORDED
    low = s.lower()
    if low in _YES_WORDS:
        return "Yes"
    if low in _NO_WORDS:
        return "No"
    return _html.escape(s)


def raw_name(v: Any) -> str:
    """A name or a short entry, capitalised, and BLANK when there is none.

    ── THREE AGENTS ASKED FOR THIS UNDER THREE NAMES ───────────────────

    `name_or_blank` for a pre-shift company and an OSHA worker, `raw_name` for
    a toolbox attendee, `raw_sentence` for a fall-protection defect column. One
    rule: `name`'s capitalisation with `raw_text`'s empty.

    WHY NEITHER EXISTING ONE WILL DO. `raw_text` keeps the blank and drops the
    capitalisation, so a man's firm prints as he typed it, lower case, on a
    filed record. `name` capitalises and prints the not-recorded phrase -- and
    in a DEFECT column on a row that passed, or a company column the CP left
    blank on purpose, that phrase is a finding against a row that has none.

    A ROW IS THE RECORD. Its blank cells are not absences the document should
    remark on; the row being there is the claim.
    """
    s = _s(v)
    if not s:
        return ""
    return _html.escape(s[0].upper() + s[1:])


def fire_watch_default(v: Any) -> str:
    """A fire-watch end time, LABELLED AS THE COMPUTED DEFAULT IT IS.

    THE EDITOR CAPTURES NO REAL FIRE-WATCH END. `hotWorkModel.calcFireWatchEnd`
    derives it as work end + 30 minutes, and nobody on site is asked for it. So
    a bare "14:30" under a heading reading "Fire Watch Until" is a watch-until
    somebody set, on an FDNY 3504 permit, and FDNY can require 60.

    THE BRANCH SAID SO AND THE FIRST DECLARATION DID NOT. Bound to
    `time_of_day` the qualifier came off the permit and the old-against-new
    comparison reported `default` and `min` as words the old sheet had. The
    request was filed with the declaration; this is it.

    ABSENT READS AS ABSENT, not as a default of nothing. A permit with no work
    end has no derived watch-until either, and printing "(default: work end +
    30 min)" beside nothing would assert a computation that did not happen.
    """
    s = _s(v)
    if not s:
        return NOT_RECORDED
    return (f'{_html.escape(s)} <span style="color:#94a3b8;">'
            f'(default: work end + 30 min)</span>')


def pass_fail(v: Any) -> str:
    """A tri-state verdict. NULL IS NOT A PASS AND NEVER A FAIL.

    REQUESTED BY TWO AGENTS for two types -- a concrete slump test and a
    fall-protection equipment check -- and `yes_no` was the nearest fit for
    both. It is not close enough: a FAILED slump on a filed BC 3315 record
    would print "No", which is the same defect `inspection_log`'s docstring is
    about, one form over.

    "Fail" and "No" are not the same word on a compliance document. One is a
    verdict on a test; the other is an answer to a question.
    """
    if v is None:
        return NOT_RECORDED
    if isinstance(v, bool):
        return "Pass" if v else "Fail"
    s = _s(v)
    if not s:
        return NOT_RECORDED
    low = s.lower()
    if low in _YES_WORDS or low == "pass":
        return "Pass"
    if low in _NO_WORDS or low == "fail":
        return "Fail"
    return _html.escape(s)


def affirmation_note(v: Any) -> str:
    """How many workers affirmed at the gate, as a sentence.

    A FACT ABOUT A DIFFERENT RECORD, and it says so. The sheet states how many
    affirmations are on file for the day; it never puts an affirmation beside
    a named man's row, because the stored roster does not carry one. That
    distinction is the whole reason this is a footer count and not a column --
    a per-row claim here once accused every worker on every filed sheet.

    ZERO OMITS THE SECTION RATHER THAN REACHING THIS. `requires` tests
    `_get(...) or ""`, and `0 or ""` is empty -- so a day with no affirmations
    prints no heading at all, instead of a heading over a line saying none.
    """
    try:
        n = int(v)
    except (TypeError, ValueError):
        return NOT_RECORDED
    if n <= 0:
        return NOT_RECORDED
    return ("%d worker%s affirmed their sign-in at the gate for this date."
            % (n, "" if n == 1 else "s"))


def inspection_result(v: Any) -> str:
    """A fall-protection equipment verdict. NULL IS NOT A PASS.

    THREE OUTCOMES AND AN ABSENCE, and two of them are adverse. "Removed from
    service" must never collapse into "Fail": one says the harness failed a
    check, the other says it is off the site. An inspector reading a filed
    register needs to know which, and a renderer that folds them has decided
    something the CP recorded differently.

    THE ADVERSE ONES ARE EMPHASISED, in the same weight `inspection_log` uses
    for a failed item -- not a second spelling of emphasis, the same one.
    """
    if v is None:
        return NOT_RECORDED
    s = _s(v)
    if not s:
        return NOT_RECORDED
    low = s.lower()
    if low in ("pass", "passed", "ok"):
        return "Pass"
    if low in ("fail", "failed"):
        return "<strong>Fail</strong>"
    if "removed" in low:
        return "<strong>Removed from service</strong>"
    return _html.escape(s)


def vibration_status(v: Any) -> str:
    """Whether a monitored reading crossed its threshold.

    BOUND TO THE DATA MAP, like `weather_line`, because the answer needs three
    keys: the threshold, the current reading, and the flag that says the
    comparison was made.

    BOTH READINGS AND THE FLAG, OR NOTHING. A status derived from one of them
    is this renderer doing arithmetic on a compliance record. If the record
    does not carry the comparison, the sheet says it was not recorded rather
    than computing one.
    """
    d = v if isinstance(v, dict) else {}
    threshold = _s(d.get("vibration_threshold"))
    current = _s(d.get("vibration_current"))
    if not threshold or not current or "vibration_over_threshold" not in d:
        return NOT_RECORDED
    over = bool(d.get("vibration_over_threshold"))
    reading = _html.escape(f"{current} against {threshold}")
    return (f"<strong>Over threshold</strong> &mdash; {reading}" if over
            else f"Within threshold &mdash; {reading}")


def tick_or_blank(v: Any) -> str:
    """A tick, or nothing. NEVER "No", and never the not-recorded phrase.

    FOR A COLUMN WHERE THE ROW IS THE RECORD. The OSHA register's Signed
    column says a signature is on file; an empty cell says nothing, which is
    correct, because the register's claim is about the certifications listed
    and not about who signed what.

    "No" THERE WOULD BE AN ASSERTION THE CP NEVER MADE -- the document stating
    that a named man's signature is NOT on file. And the not-recorded phrase
    would be a finding against a row that has none. Both are claims; a blank
    cell is the absence of one.
    """
    if isinstance(v, bool):
        return "&#10003;" if v else ""
    s = _s(v)
    if not s:
        return ""
    return "&#10003;" if s.lower() in _YES_WORDS else ""


def yes_no(v: Any) -> str:
    """A stored boolean. ABSENT IS NOT NO -- it is not recorded, and a
    compliance document that prints "No" for a question nobody answered has
    made a claim nobody made.

    ── IT INVERTED EVERY STORED "no", AND NOTHING HAD BOUND IT YET ──────

    The body was `"Yes" if bool(v) else "No"`, and `bool("no")` is True.
    Pre-shift stores its injury and PPE answers as the lowercase STRINGS 'yes'
    and 'no' -- 329 rows in production, not one boolean -- so binding this
    formatter there would have printed **Yes** under a column headed Injury
    for every man who reported none, on 49 filed compliance records, on a
    sheet that looked entirely normal.

    Caught by a schema agent censusing the stored values before declaring the
    field, which is the only reason it was caught at all: no shipped schema
    had bound it, so no test could have failed.

    A STRING IS NOT A BOOLEAN AND IS NOT COERCED AS ONE. The spellings this
    product stores are read; anything else is returned as the record wrote it,
    because a renderer that guesses at a compliance answer is worse than one
    that quotes it.
    """
    if v is None:
        return NOT_RECORDED
    if isinstance(v, bool):
        return "Yes" if v else "No"
    s = _s(v)
    if not s:
        return NOT_RECORDED
    low = s.lower()
    if low in _YES_WORDS:
        return "Yes"
    if low in _NO_WORDS:
        return "No"
    return _html.escape(s)


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
    # Three agents asked for `raw_name` under three names, and two for
    # `pass_fail`. `answer` is the three-state string `yes_no` refuses
    # to coerce.
    "answer": answer,
    "raw_name": raw_name,
    "pass_fail": pass_fail,
    "fire_watch_default": fire_watch_default,
    "tick_or_blank": tick_or_blank,
    "inspection_result": inspection_result,
    "vibration_status": vibration_status,
    "affirmation_note": affirmation_note,
    "sub_company": sub_company,
    "weather_line": weather_line,
    "toggle_list": toggle_list,
    "roster_clock": roster_clock,
    "attendee_source": attendee_source,
}
