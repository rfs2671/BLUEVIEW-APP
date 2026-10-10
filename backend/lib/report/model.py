"""THE SEMANTIC AUTHORITY FOR THE INVESTOR REPORT.

If the renderer ever has to decide what a zero means, or whether a company was
on site, or whether "no incidents" may be said, THIS BOUNDARY HAS FAILED. The
renderer's whole job is layout and typography; every judgement about what the
records support is made here, once, and both pages consume the same answer.

That is not tidiness. Page 1 and Page 2 each describe the same activity row,
and the only structural guarantee that they cannot disagree is that neither
computes anything.

── PURE, AND DELIBERATELY SO ─────────────────────────────────────────────────

Nothing here imports `server`, opens a database, or reads a clock. It takes
documents and returns resolved state. Two reasons, and the second is the one
that matters: `server` imports this module, so importing it back would be a
cycle -- and a model that needs a database to be tested is a model whose edge
cases get tested once, by hand, on whatever day somebody happened to look.

The Eastern-day window is computed by `server.get_day_range_est` and PASSED IN.
A second copy of that arithmetic living here is exactly the drift this file
exists to prevent, and the repository has been bitten by that twice.

── THE CLOSED SETS ───────────────────────────────────────────────────────────

Both the workforce reconciliation and the location shape are enums, not
free-form branching spread through templates. A sixth state cannot be invented
at a call site, and a test asserts that every member is reachable -- so a
member added without a rule fails loudly rather than silently choosing copy.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import location_vocabulary as lv


def _clean(value) -> str:
    return " ".join(str(value or "").split())


#: The gate writes this when a worker's subcontractor was not on the project
#: roster at check-in. IT IS A DATABASE PLACEHOLDER, NOT A CONTRACTOR AND NOT
#: A TRADE, and it arrives in both fields: one row on production carries it as
#: a company and one as a trade.
PLACEHOLDER = "UNASSIGNED"

#: What an activity row says when the daily log names no company. NOT dropped:
#: a row carrying a description or a photograph is evidence whether or not
#: somebody filled the company field, and deleting it would remove work from
#: the record to tidy a heading.
UNNAMED_CONTRACTOR = "Contractor not recorded"


def is_placeholder(value) -> bool:
    return _clean(value).upper() == PLACEHOLDER


def proper_case(value) -> str:
    """"Plumber" for "plumber"; "HVAC / Mechanical" left alone.

    ONLY AN ALL-LOWERCASE WORD IS TOUCHED. A word carrying any capital was
    spelled that way by somebody -- "HVAC", "BreezCo" -- and re-casing it
    would be the report correcting a name it does not own.
    """
    return " ".join(w[:1].upper() + w[1:] if w.islower() else w
                    for w in _clean(value).split(" "))


# ══════════════════════════════════════════════════════════════════════════
#  THE FIVE WORKFORCE RECONCILIATION STATES
# ══════════════════════════════════════════════════════════════════════════

class Reconciliation(Enum):
    """How the conducting party's crew count and the gate relate.

    TWO INDEPENDENT SOURCES, each either present or absent, and the
    both-present case splits on whether they agree. That is five, it is
    exhaustive by construction, and `reconcile` has a branch for each.

    MEASURED ACROSS 59 DAILY LOGS ON PRODUCTION:

        ALIGNED    64      counts agree
        VARIANCE   25      counts differ
        LOG_ONLY   11      a count on the log, nobody at the gate
        GATE_ONLY  19      people at the gate, no count on the log
        NEITHER     1      no count and nobody at the gate

    A VARIANCE IS NOT A DEFICIENCY. Twenty-five of eighty-nine comparable rows
    disagree, and a conducting party who counts seven men on his crew and a
    turnstile that recorded five are each reporting something real. The report
    does not decide which is correct; it says what each source holds. Every one
    of these states is therefore neutral in the palette -- amber belongs to a
    record that is owed and absent, and nothing else.
    """

    ALIGNED = "aligned"
    VARIANCE = "variance"
    LOG_ONLY = "log_only"
    GATE_ONLY = "gate_only"
    NEITHER = "neither"


#: THERE IS NO CHIP ANY MORE. Each row carried a badge naming its state --
#: "Counts aligned", "Count variance", "Count not recorded" -- beneath the
#: statement that already prints both numbers. Removed by ruling 2026-10-10:
#: the numbers are the record, and a badge grading them was the report
#: commenting on the record. The state survives because it is what chooses
#: the statement's wording.


def reconcile(log_count: Optional[int], gate_count: int) -> Reconciliation:
    """The state, from the two counts. `None` means NOT RECORDED, not zero."""
    if log_count is not None and gate_count:
        return (Reconciliation.ALIGNED if log_count == gate_count
                else Reconciliation.VARIANCE)
    if log_count is not None:
        return Reconciliation.LOG_ONLY
    if gate_count:
        return Reconciliation.GATE_ONLY
    return Reconciliation.NEITHER


def reconciliation_statement(state: Reconciliation, log_count: Optional[int],
                             gate_count: int) -> str:
    """The sentence. THE NUMBERS ARE NEVER SUPPRESSED where they exist.

    A recorded seven against nobody at the gate prints the seven: saying
    "workforce count recorded" instead throws away the only number on the row.
    """
    if state in (Reconciliation.ALIGNED, Reconciliation.VARIANCE):
        return f"{log_count} on daily log · {gate_count} gate check-ins"
    if state is Reconciliation.LOG_ONLY:
        return f"{log_count} on daily log · 0 matched gate check-ins"
    if state is Reconciliation.GATE_ONLY:
        return f"Workforce count not recorded · {gate_count} gate check-ins"
    return "Workforce count not recorded · No gate check-ins matched"


def log_headcount(activity: Any) -> Optional[int]:
    """The crew count the conducting party recorded, or None if he recorded none.

    ZERO AND NOT-RECORDED ARE DIFFERENT CLAIMS AND BOTH ARE FALSY IN PYTHON.
    A stored "0" is the conducting party saying nobody from that company
    worked. An empty string is the question never answered. On a compliance
    document those are not interchangeable, and `if not num_workers` collapses
    them.

    MEASURED ACROSS ALL 112 ACTIVITY ROWS ON PRODUCTION:

        106  a positive integer
          5  an empty string   -> not recorded
          1  the literal "0"   -> a recorded zero

    THE ONE RECORDED ZERO IS AAZ ON 2026-08-27, which is the row the whole
    distinction was raised about: the conducting party recorded ZERO while
    filing two photographs of AAZ framing. That is a stronger and different
    statement than "not recorded", and it is the one row anybody was looking
    at when the softer wording would have shipped.
    """
    if not isinstance(activity, dict) or "num_workers" not in activity:
        return None
    raw = activity.get("num_workers")
    if raw is None:
        return None
    text = str(raw).strip()
    return int(text) if text.isdigit() else None


# ══════════════════════════════════════════════════════════════════════════
#  THE LOCATION SHAPE
# ══════════════════════════════════════════════════════════════════════════

class LocationShape(Enum):
    """What the rail's third cell is entitled to say. Five, and closed."""

    AREAS = "areas"
    AREAS_AND_SITEWIDE = "areas_and_sitewide"
    SITEWIDE_ONLY = "sitewide_only"
    UNMAPPED_ONLY = "unmapped_only"
    NONE_RECORDED = "none_recorded"


def location_shape(resolution: "lv.Resolution") -> LocationShape:
    if resolution.areas:
        return (LocationShape.AREAS_AND_SITEWIDE if resolution.sitewide
                else LocationShape.AREAS)
    if resolution.sitewide:
        return LocationShape.SITEWIDE_ONLY
    if resolution.unmapped:
        return LocationShape.UNMAPPED_ONLY
    return LocationShape.NONE_RECORDED


# ══════════════════════════════════════════════════════════════════════════
#  THE FOUR RESOLVED OBJECTS
# ══════════════════════════════════════════════════════════════════════════

class GateDayState:
    """Everything the access system saw inside one Eastern day.

    THE WINDOW IS PASSED IN, ALREADY APPLIED. The rows handed to this object
    are the query result; it does not filter by date, because the only correct
    filter is `check_in_time` between the Eastern day's bounds and that
    arithmetic lives in one place. Slicing a UTC timestamp to ten characters
    puts a man who badges in at half past nine in the evening on tomorrow's
    report, and that mistake has already been made in a probe here.
    """

    __slots__ = ("rows", "check_ins", "by_company", "trades",
                 "trades_pending", "on_site")

    def __init__(self, rows: Sequence[dict], display_company=None):
        display = display_company or (lambda s: s)
        self.rows = list(rows)
        # CHECK-INS, NOT PEOPLE. The rail says "gate check-ins" because that is
        # what this counts: one row is one badge event.
        self.check_ins = len(self.rows)

        counts: Dict[str, int] = {}
        for row in self.rows:
            raw = _clean(row.get("worker_company"))
            if not raw:
                continue
            # `UNASSIGNED` IS A PLACEHOLDER, NOT A CONTRACTOR -- a worker whose
            # subcontractor was not on the roster at check-in. The headcount
            # stays visible and only the label changes, which is the rule the
            # server's own helper already carries.
            counts[display(raw)] = counts.get(display(raw), 0) + 1
        self.by_company = counts

        # A PLACEHOLDER IS NOT A TRADE, AND THE RAIL COUNTS TRADES.
        #
        # One row on production carries UNASSIGNED here, and on 2026-08-16 it
        # made the rail read six trades where five were recorded. It is
        # excluded from the count and REPORTED SEPARATELY rather than dropped:
        # silently improving the number is the thing this report does not do,
        # and the man is still counted among the check-ins either way.
        #
        # PROPER CASE, AND ONE ENTRY PER TRADE. The rail lists them now, one
        # per line, so "plumber" and "Plumber" from two check-ins would print
        # as two trades; they are one, spelled as the roster spells it.
        every = [_clean(r.get("trade")) for r in self.rows
                 if _clean(r.get("trade"))]
        named: Dict[str, str] = {}
        for t in every:
            if not is_placeholder(t):
                named.setdefault(t.casefold(), proper_case(t))
        self.trades = sorted(named.values(), key=str.casefold)
        self.trades_pending = len([t for t in every if is_placeholder(t)])

        # DISTINCT PEOPLE STILL ON SITE, which is a different number from
        # check-ins and is used for orientation coverage rather than the rail.
        people = set()
        for row in self.rows:
            if row.get("status") != "checked_in":
                continue
            key = str(row.get("worker_id") or "") or \
                ("name:" + _clean(row.get("worker_name")).lower())
            if key.strip() and key != "name:":
                people.add(key)
        self.on_site = len(people)

    def count_for(self, company: str) -> int:
        return self.by_company.get(company, 0)


class ActivityDisplayState:
    """One activity row, fully resolved. The renderer reads attributes only."""

    __slots__ = ("company", "company_display", "trade", "location",
                 "log_count", "gate_count", "reconciliation", "statement",
                 "photos", "activity_index", "description", "named",
                 "folded_indices")

    def __init__(self, activity: dict, index: int, gate: GateDayState,
                 display_company=None, overrides=None, renderable=None,
                 folded: Sequence[Tuple[int, dict]] = (),
                 company: Optional[str] = None):
        display = display_company or (lambda s: s)
        keep = renderable or (lambda p: True)
        # THE ROW, AND ANY GATE-BUILT ROWS FOLDED INTO IT -- see
        # `fold_unnamed_rows`. With nothing folded every line below reads the
        # one row exactly as it always did.
        members: List[Tuple[int, dict]] = [(index, activity)] + list(folded)

        self.activity_index = index
        self.folded_indices = [i for i, _ in folded]
        self.company = _clean(company if company is not None
                              else activity.get("company"))
        self.named = bool(self.company)
        # NEVER PRINTED NOW: `ReportDisplayModel` drops a row that is still
        # unnamed after the fold. The label stays so the object is never
        # half-built.
        self.company_display = (display(self.company) if self.company
                                else UNNAMED_CONTRACTOR)
        descriptions: List[str] = []
        for _, row in members:
            d = _clean(row.get("work_description"))
            if d and d not in descriptions:
                descriptions.append(d)
        self.description = "; ".join(descriptions)
        self.trade = next((_clean(r.get("trade")) for _, r in members
                           if _clean(r.get("trade"))), "")
        self.location = lv.resolve([r.get("work_locations") for _, r in members],
                                   overrides=overrides)
        # A FOLDED ROW'S MEN ARE THIS COMPANY'S MEN. The count is the sum of
        # what was recorded, and None only when nothing was -- a recorded "1"
        # beside a blank is still one man on the log.
        counts = [c for c in (log_headcount(r) for _, r in members)
                  if c is not None]
        self.log_count = sum(counts) if counts else None
        self.gate_count = gate.count_for(self.company_display)
        self.reconciliation = reconcile(self.log_count, self.gate_count)
        self.statement = reconciliation_statement(
            self.reconciliation, self.log_count, self.gate_count)
        # (stored activity index, stored photo index, photo). BOTH STORED,
        # because the photo endpoint reads data.activities[ai].photos[pi] -- an
        # index into a filtered list serves a different photograph than the
        # one laid out, and a folded row's photographs live under ITS index.
        self.photos: List[Tuple[int, int, dict]] = [
            (ai, pi, p) for ai, row in members
            for pi, p in enumerate(row.get("photos") or [])
            if isinstance(p, dict) and keep(p)]

    @property
    def substantive(self) -> bool:
        """Whether this row records anything at all.

        A SEED ROW IS NOT AN ACTIVITY. Three rows on production carry no
        company, no description, no location, no count and no photograph --
        they are the editor's empty row, saved. Rendering one puts a heading
        reading "Contractor not recorded" over nothing, which invents a
        deficiency out of a blank form.

        A ROW WITH ANY SUBSTANCE RENDERS, including the six that carry only a
        headcount. That number is a record of men on the job and dropping it
        to tidy the page would delete them.
        """
        return bool(self.company or self.description or self.photos
                    or self.log_count is not None
                    or self.location.located)

    @property
    def shape(self) -> LocationShape:
        return location_shape(self.location)

    @property
    def where(self) -> str:
        """The long form for a row, or nothing.

        THE RECORDED STRING IS NO LONGER THE FALLBACK. It printed whatever the
        table could not read -- on 2026-10-05 "3rd Floor, 4th Floor" verbatim
        under a heading that otherwise speaks in canonical areas. Unreadable
        is omitted, by ruling.
        """
        return self.location.prose()


def _company_key(value) -> str:
    return _clean(value).casefold()


def _checkin_company(row: dict) -> str:
    """The sub a check-in row names, or "" -- never the placeholder."""
    for field in ("worker_company", "company"):
        c = _clean(row.get(field))
        if c and not is_placeholder(c):
            return c
    return ""


def fold_unnamed_rows(rows: Sequence[Any], checkins: Sequence[dict]
                      ) -> List[Tuple[int, dict, List[Tuple[int, dict]],
                                      Optional[str]]]:
    """Each activity row, with the day's company-less gate rows folded in.

    THE DEFECT, 588 Thomas, 2026-10-05. Three new BreezCo hires badged in with
    no company or trade. The CP's daily log built its crews from the gate at
    13:12, so each became a one-man row with no company; at 13:18 the CP
    assigned all three to BreezCo on their check-ins, and the filed log never
    learned it. The report printed three "Contractor not recorded" rows and
    BreezCo at 1 when it had 4.

    SO A ROW WITH NO COMPANY IS LOOKED UP IN THAT DAY'S CHECK-INS, by the
    worker ids the gate put on it (and the names, for a row that carries only
    names). When every man on it resolves to ONE company, the row folds into
    the first row the log has for that company, or -- when the log has none --
    becomes that company's row. A row whose men resolve to two companies, or
    to none, stays unnamed, and `ReportDisplayModel` drops it (ruled: no
    render, no count).

    THE FILED LOG IS NOT CHANGED. This is the report reading the gate's later
    answer; the upstream fix -- the log picking up the assignment itself -- is
    a separate change.

    Returns (stored index, row, folded [(stored index, row)], company or None)
    in log order. `company` is set only on a row that became a company's row.
    """
    by_id: Dict[str, str] = {}
    by_name: Dict[str, str] = {}
    for c in checkins or []:
        company = _checkin_company(c)
        if not company:
            continue
        if str(c.get("worker_id") or "").strip():
            by_id[str(c["worker_id"]).strip()] = company
        name = _clean(c.get("worker_name")).casefold()
        if name:
            by_name[name] = company

    indexed = [(i, r) for i, r in enumerate(rows or []) if isinstance(r, dict)]
    out: List[list] = []
    first_named: Dict[str, int] = {}
    for i, row in indexed:
        if _clean(row.get("company")):
            first_named.setdefault(_company_key(row.get("company")), len(out))
            out.append([i, row, [], None])

    for i, row in indexed:
        if _clean(row.get("company")):
            continue
        ids = [str(w).strip() for w in (row.get("worker_ids") or [])
               if str(w or "").strip()]
        names = [_clean(n).casefold() for n in (row.get("worker_names") or [])
                 if _clean(n)]
        found = ([by_id.get(w, "") for w in ids] if ids
                 else [by_name.get(n, "") for n in names])
        companies = {_company_key(c): c for c in found if c}
        if found and all(found) and len(companies) == 1:
            key, company = next(iter(companies.items()))
            if key in first_named:
                out[first_named[key]][2].append((i, row))
                continue
            first_named[key] = len(out)
            out.append([i, row, [], company])
            continue
        out.append([i, row, [], None])

    out.sort(key=lambda g: g[0])
    return [tuple(g) for g in out]


def resolve_activities(rows: Sequence[Any], gate: GateDayState,
                       **kwargs) -> List[ActivityDisplayState]:
    """The activity rows the report lays out, after the fold."""
    return [ActivityDisplayState(row, index, gate, folded=folded,
                                 company=company, **kwargs)
            for index, row, folded, company in fold_unnamed_rows(rows, gate.rows)]


class SafetyState:
    """Whether today's records support a safety conclusion.

    THEY USUALLY DO NOT, AND SAYING SO IS THE PRODUCT. The conclusion is
    computed from the superintendent's log; when that log is not filed there is
    no conclusion, and "no incidents were reported" is a claim the record does
    not make. Not-reported and none are different facts and this object refuses
    to collapse them.
    """

    __slots__ = ("reported", "status", "source_log_filed")

    def __init__(self, superintendent_log: Optional[dict],
                 status: Optional[str] = None):
        self.source_log_filed = bool(superintendent_log)
        self.reported = bool(superintendent_log) and bool(status)
        self.status = status if self.reported else None

    @property
    def value(self) -> str:
        return self.status if self.reported else "—"

    @property
    def note(self) -> str:
        if self.reported:
            return ""
        return ("No safety conclusion is available from today’s source "
                "records.")


class RequiredLogsState:
    """Filed against owed, with the denominator fixed by the project.

    TWO DENOMINATORS AND THEY ARE NEVER COMBINED. A required log is owed on
    this date; an additional record is one the project files without being owed
    it today. "5 of 7" would be a compliance claim about two records nobody
    asked for.
    """

    __slots__ = ("required", "due", "filed", "missing", "extra", "label")

    def __init__(self, required: Sequence[str], due: Sequence[str],
                 filed: Iterable[str], label=None):
        self.label = label or (lambda t: t)
        self.required = list(required)
        self.due = list(due)
        filed_set = set(filed)
        self.filed = [t for t in self.required if t in filed_set]
        self.missing = [t for t in self.due if t not in filed_set]
        self.extra = [t for t in self.required
                      if t not in self.due and t in filed_set]

    @property
    def due_filed(self) -> int:
        return len([t for t in self.due if t in set(self.filed)])

    @property
    def ratio(self) -> str:
        return f"{self.due_filed} of {len(self.due)}"

    def missing_names(self) -> List[str]:
        return [self.label(t) for t in self.missing]

    def register(self) -> List[str]:
        """THE TYPES THE RECORD INDEX PRINTS -- OFF THE SAME FIELDS AS THE RATIO.

        THE REGISTER USED TO ITERATE `required` AND THE RATIO COUNTS `due`,
        which are not the same list on any project that carries a weekly or an
        as-needed type. On 857 Prescott Pl the Tuesday report printed five
        numbered records -- including a "Tool Box Talk" and a "Subcontractor
        Safety Orientation", neither owed and neither filed -- under a ratio of
        "1 of 3". Two lists describing one day, disagreeing about what the day
        required, and a reader who counted the register got a different answer
        from the reader who read the number.

        SO THE REGISTER IS DERIVED HERE, from the fields the ratio is derived
        from, and the disagreement stops being a thing anybody has to remember:
        there is one object and both answers come out of it.

        `due` FIRST, THEN `extra`, AND THE ORDER IS THE CLAIM. Records 1..N are
        the obligations this date carried -- exactly the ratio's denominator --
        and everything after is a record filed without being owed, which is the
        figure the completeness block already prints beside the ratio and
        never sums with it.

        WHAT IS DROPPED IS THE ROW ABOUT NOTHING: a type that was not owed
        today and was not filed either. That is the only row that leaves, and
        it described neither an obligation nor a document.

        WHAT IS NOT DROPPED IS A FILED RECORD. A toolbox talk filed on Monday
        is on Monday's register, carrying its document and its link, because a
        filed compliance record disappearing from the record index would be a
        worse defect than the card this replaces. It is simply outside a ratio
        that never counted it.

        Both halves are filtered out of `required`, so the project's own
        ordering survives within each.
        """
        return self.due + self.extra


# ══════════════════════════════════════════════════════════════════════════
#  WHAT BOTH PAGES CONSUME
# ══════════════════════════════════════════════════════════════════════════

class ReportDisplayModel:
    """The one object the renderer is handed.

    PAGE 2 NEVER CALLS GATE LOGIC. It reads `activities`, the same list Page 1
    reads, and the count statement on a photograph band is the identical string
    the activity row prints -- not a recomputation that happens to agree today.
    """

    __slots__ = ("project", "date", "gate", "activities", "safety",
                 "required_logs", "weather", "additional_gate",
                 "seed_rows_dropped", "unnamed_rows_dropped")

    def __init__(self, project: dict, date: str, gate: GateDayState,
                 activities: Sequence[ActivityDisplayState],
                 safety: SafetyState, required_logs: RequiredLogsState,
                 weather: Sequence[str]):
        self.project = project or {}
        self.date = date
        self.gate = gate
        # SEED ROWS ARE DROPPED HERE, ONCE, AND COUNTED. The renderer never
        # sees them, so it cannot accidentally draw one; the count is kept so
        # that "the log had four rows and the report shows three" has an
        # answer other than a shrug.
        every = list(activities)
        substantive = [a for a in every if a.substantive]
        self.seed_rows_dropped = len(every) - len(substantive)
        # AND A ROW STILL WITHOUT A COMPANY AFTER THE FOLD IS DROPPED TOO --
        # no render, no count, ruled 2026-10-10. Counted separately, so the
        # two reasons a log row is missing from the page stay distinguishable.
        self.activities = [a for a in substantive if a.named]
        self.unnamed_rows_dropped = len(substantive) - len(self.activities)
        self.safety = safety
        self.required_logs = required_logs
        self.weather = [w for w in weather if w]

        # ADDITIONAL GATE WORKFORCE: people the access system saw for whom the
        # log describes no work. NOT a sixth activity state -- by definition
        # there is no documented activity, so it cannot live under a heading
        # that says there is. 19 rows across the corpus, so it is common.
        # MATCHED ON THE REAL NAME, NOT THE PLACEHOLDER LABEL. An unnamed
        # activity row does not claim any gate company, so a company at the
        # gate with no row still belongs in Additional Gate Workforce.
        named = {a.company_display for a in self.activities if a.named}
        self.additional_gate = [(c, n) for c, n in
                                sorted(gate.by_company.items(),
                                       key=lambda kv: -kv[1])
                                if c not in named]

    def day_location(self) -> "lv.Resolution":
        """The rail's third cell: the DAY's areas, not one row's.

        THE UNION OF WHAT THE ROWS PRODUCED, rather than a second pass over the
        raw strings. Re-resolving here would mean the table is consulted twice
        with two chances to disagree, and a row and the rail could then name
        different areas for the same string. A floor recorded on three rows is
        one area because the tokens are a set.
        """
        areas, sitewide, unmapped, located, mapped = set(), False, [], 0, 0
        for a in self.activities:
            areas.update(a.location.areas)
            sitewide = sitewide or a.location.sitewide
            unmapped.extend(a.location.unmapped)
            located += a.location.located
            mapped += a.location.mapped
        return lv.Resolution(
            areas=[t for t in lv.DISPLAY_ORDER if t in areas],
            sitewide=sitewide,
            unmapped=sorted(set(unmapped), key=str.lower),
            located=located, mapped=mapped)

    def bands(self) -> List[ActivityDisplayState]:
        """Page 2's evidence bands: the activity rows that have photographs.

        A BAND WITH NO PHOTOGRAPH IS NOT EVIDENCE, and Page 2 is only evidence.
        """
        return [a for a in self.activities if a.photos]
