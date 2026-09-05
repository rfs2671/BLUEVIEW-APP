"""The construction superintendent's own log — BC 3301.13.13.

NOT A SECTION OF THE DAILY JOBSITE LOG. It is the CS's statutory record, signed
under his own DOB licence, and only item 2 overlaps with what the CP files.

TWO CAPACITIES, ORDINARILY TWO PEOPLE, AND ONE LICENSED PERSON MAY HOLD BOTH.
An earlier draft of this note said the superintendent "is a different person
from the CP". That is the usual case and it is not a rule: a licensed CS may act
as the competent person for general site operations, and on this product's first
customer he does. What must stay separate is the DOCUMENTS -- two statutory
records, two signatures, two capacities -- never the ACCOUNTS.

ONE ACCOUNT IS BETTER EVIDENCE THAN TWO. `acting_capacity` on a signature event
is derived from the EVENT TYPE, so one user signing the daily jobsite log as
`cp_sign` and this log as `superintendent_sign` produces "Competent Person" and
"Construction Superintendent" from one user_id. Two accounts would put two ids
on one man with nothing in the data saying they are the same person.

SO THE ACCESS GATE KEYS ON THE CS REGISTRATION, NEVER ON `role`. `role ==
"superintendent"` would lock out exactly the dual-capacity user this product
has. `lib/logbook/cs_attribution.py` already answers "is this user the registered
CS for this project" -- by user_id on the registration, or by licence number --
and that is the question to ask.

THE ELEVEN ITEMS are declared once, here, as data. Every consumer -- the editor,
the submit gate, both renderers, the tests -- reads this list rather than its own
copy, because the OSHA register's row rule had to be pulled back into one
definition after the per-logbook PDF and the combined report drifted apart
twice.

── EMPTY IS THE NORMAL STATE ───────────────────────────────────────────────────

Items 4, 5, 6 and 7 are empty most days, and that is not a defect. What IS a
defect is an empty item that does not say WHICH KIND of empty it is. The OSHA
register printed an em dash five times in one row meaning four different things,
and this log must not repeat it. Three states, and they are different facts:

    ATTESTED_NONE   the CS considered this item and had nothing to report.
                    ASSERTED BY HIM, and the document says so in words.
    NOT_REACHED     the visit is open and he has not got to it. Asserted by
                    NOBODY. It must never print as "none".
    NOT_COLLECTED   this system does not capture the item at all. Asserted by
                    the RULE, not a person -- a scope statement, not an
                    attestation.

ATTESTED_NONE is the whole value of the document: an inspector reading "no
unsafe conditions observed" learns something only because a named person put
their name to it. So the four attestable items REQUIRE an explicit nothing-to-
report before the log can be signed, the same shape as the pre-shift sheet
refusing to submit until every worker has both answers.

── EVERY STATUTORY GATE READS THE RECORD'S OWN DATE ────────────────────────────

`item_applies(key, log_date)` takes the DATE OF THE LOG, never datetime.now().

The competent-person allowance in item 8 sunsets on 2027-01-01, after which
item 9 carries the case it covered. A log filed in 2026 must keep rendering
item 8 forever; a rule change does not reach back and alter what a filed
document says. That is the same principle the pre-shift affirmation overlay
follows in resolving against the sheet's date rather than today's, and the same
reason `sst_class_label` refuses to lend a live cert's hours to a row filed
under a different class.

A gate that read `datetime.now()` would make historical documents change what
they say, which on a signed statutory record is the worst failure available.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# ── When the competent-person allowance lapses ──────────────────────────────
#
# A DATE, COMPARED AGAINST THE LOG'S DATE. Item 8 applies to any log dated
# BEFORE this; item 9 is the live item from this date on. Both are declared so
# neither is a magic string at a call site.
COMPETENT_PERSON_SUNSET = "2027-01-01"


# ── The eleven items ────────────────────────────────────────────────────────
#
#   key          stable identifier, stored on the document
#   number       the item's number in BC 3301.13.13, printed
#   label        what the CS and an inspector read
#   citation     the section this item answers, where one is named
#   attestable   True  -> may be "nothing to report", and MUST be answered one
#                        way or the other before signature
#                False -> content or nothing; absence is not an assertion
#   collected    False -> this system does not capture it. Renders as a SCOPE
#                        statement, never as an attestation.
ITEMS: List[Dict] = [
    {
        "key": "presence",
        "number": 1,
        "label": "Superintendent presence",
        "citation": "BC 3301.13.13",
        "attestable": False,
        "collected": True,
        # Arrival and departure are HIS CLAIMS, prefilled from sign-in and from
        # log completion and editable throughout. The daily jobsite log already
        # distinguishes a gate-recorded count from a hand-entered one; the same
        # honesty applies here. A prefilled time presented as observed would be
        # the app asserting something only he can.
        "fields": ["printed_name", "signature", "arrived_at", "departed_at"],
    },
    {
        "key": "progress",
        "number": 2,
        "label": "General progress of work",
        "citation": "BC 3301.13.13",
        "attestable": False,
        "collected": True,
        # THE ONE ITEM THAT OVERLAPS WITH THE CP'S DAILY JOBSITE LOG, and the
        # only one whose PROVENANCE has to be recorded.
        #
        # Today the CP fills the day and the superintendent visits, so item 2
        # is fairly summarised from the CP's record. FROM 2027-01-01 the CS
        # must be present during all active work, and he is then the WITNESS
        # rather than the summariser -- the derivation inverts.
        #
        # So the document says which it was: `source` is "adopted" when the
        # autofill from the CP's log was left as it arrived, and "own" the
        # moment he edits it. An unmarked item 2 cannot tell a reader whether
        # they are reading his observation or a copy of somebody else's, and
        # once the two logs can disagree -- which is exactly what January makes
        # possible -- that difference is the whole finding.
        #
        # RETROFITTING PROVENANCE ONTO FILED RECORDS IS IMPOSSIBLE, which is
        # why the flag ships before the divergence check that will read it.
        "provenance": True,
        "fields": ["summary"],
    },
    {
        "key": "cs_activities",
        "number": 3,
        "label": "Superintendent activities, areas and floors inspected",
        "citation": "BC 3301.13.13",
        "attestable": False,
        "collected": True,
        "fields": ["summary", "locations"],
    },
    {
        "key": "unsafe_conditions",
        "number": 4,
        "label": "Unsafe conditions observed",
        "citation": "BC 3301.13.9",
        "attestable": True,
        "collected": True,
        "fields": ["entries"],          # [{time, location, description}]
    },
    {
        "key": "orders_given",
        "number": 5,
        "label": "Orders and notices given",
        "citation": "BC 3301.13.9",
        "attestable": True,
        "collected": True,
        # A refusal to comply is a fact about a named person and is recorded as
        # one. `correction` is the NATURE of the correction where one was made,
        # not a tick: "corrected" without saying how is not a record of it.
        "fields": ["entries"],          # [{names, refused, follow_up, correction}]
    },
    {
        "key": "dob_actions",
        "number": 6,
        "label": "Violations, stop work orders and summonses",
        "citation": "BC 3301.13.13",
        "attestable": True,
        "collected": True,
        "fields": ["entries"],          # [{kind, issued_on, lifted_on, detail}]
    },
    {
        "key": "incidents",
        "number": 7,
        "label": "Incidents or damage, including to adjoining property",
        "citation": "BC 3301.13.13",
        "attestable": True,
        "collected": True,
        # ONE FIELD. Adjoining-property damage is a SUBSET of incidents, not a
        # parallel question, and splitting it invites a reader to think an
        # empty adjoining-property box means the neighbour was checked.
        "fields": ["entries"],          # [{what, where}]
    },
    {
        "key": "competent_person",
        "number": 8,
        "label": "Competent person",
        "citation": "BC 3301.13.12",
        "attestable": False,
        "collected": True,
        # SUNSETS. See item_applies: this item is rendered on a log dated before
        # COMPETENT_PERSON_SUNSET, forever, and not on one dated after.
        "sunset_on": COMPETENT_PERSON_SUNSET,
        "fields": ["name", "signature"],
    },
    {
        "key": "cs_changes",
        "number": 9,
        "label": "Superintendent changes",
        "citation": "BC 3301.13.13",
        "attestable": False,
        # NOT COLLECTED IN THIS RELEASE, and the document says so rather than
        # rendering an empty item a reader would take for "no change occurred".
        # It needs a SECOND SIGNATURE on a single entry -- the incoming CS signs
        # the change -- and no logbook in this system has a per-entry signature;
        # every one has exactly one document signature. That is a schema change
        # and it is deliberately not made here.
        #
        # BECOMES THE LIVE ITEM AT THE SUNSET, when it carries the case item 8
        # covers today. It must exist before then.
        "collected": False,
        "starts_on": COMPETENT_PERSON_SUNSET,
        "fields": [],
    },
    {
        "key": "weekly_meeting",
        "number": 10,
        "label": "Weekly safety meeting",
        "citation": "BC 3301.13.19",
        "attestable": False,
        # NOT A DAILY FIELD, and this is the reason it is marked separately.
        # The obligation is WEEKLY. A field blank six days in seven teaches the
        # reader that blank is normal here -- and worse, teaches the CS the same,
        # which then bleeds into items 4 to 7 where a blank IS a finding.
        #
        # It renders as a STATUS LINE derived from whether a meeting was
        # recorded in the last seven days OF ACTIVE WORK. Days with no gate
        # check-ins do not count, so a shutdown week cannot manufacture a
        # violation.
        "collected": False,
        "daily": False,
        "fields": [],
    },
    {
        "key": "daily_inspection",
        "number": 11,
        "label": "Daily inspection",
        "citation": "1 RCNY 3301-04(f)",
        "attestable": False,
        "collected": True,
        "fields": ["inspected_on", "location", "result"],
    },
]

ITEMS_BY_KEY: Dict[str, Dict] = {i["key"]: i for i in ITEMS}

# The items that must be answered one way or the other before signature.
ATTESTABLE_KEYS = tuple(i["key"] for i in ITEMS if i.get("attestable"))

# The items this release captures at all.
COLLECTED_KEYS = tuple(i["key"] for i in ITEMS if i.get("collected"))


def item_applies(key: str, log_date: Optional[str]) -> bool:
    """Does this item apply to a log dated `log_date`?

    THE RECORD'S OWN DATE, NEVER TODAY'S. A rule change must not reach back and
    alter what a filed document says, so a 2026 log keeps rendering item 8 after
    the allowance lapses, and a 2027 log does not.

    An unknown or unparseable date returns True: the item is rendered rather
    than silently dropped. Dropping a statutory item because a date could not be
    read would remove content from a compliance record on the strength of a
    parsing failure, which is the wrong direction to fail in.
    """
    item = ITEMS_BY_KEY.get(str(key or ""))
    if not item:
        return False
    date = str(log_date or "").strip()
    if not date:
        return True

    sunset = item.get("sunset_on")
    if sunset and date >= sunset:
        return False
    starts = item.get("starts_on")
    if starts and date < starts:
        return False
    return True


def applicable_items(log_date: Optional[str]) -> List[Dict]:
    """The items that belong on a log of this date, in printed order."""
    return [i for i in ITEMS if item_applies(i["key"], log_date)]


# ── The three empty states ──────────────────────────────────────────────────

# ── Where item 2's text came from ───────────────────────────────────────────
#
# ADOPTED   the autofill from the CP's daily jobsite log, unedited
# OWN       he changed it, so it is his own account of the day
# UNMARKED  a log filed before this flag existed. NOT "adopted": a row that
#           predates the question has not answered it, and guessing would put
#           a provenance on a record nobody recorded one for.
PROVENANCE_ADOPTED = "adopted"
PROVENANCE_OWN = "own"
PROVENANCE_UNMARKED = "unmarked"


def item_provenance(data) -> str:
    """Where item 2's summary came from, as stored.

    Reads only what was RECORDED. It does not compare the text against the
    CP's log to decide -- that would make a filed document's provenance depend
    on a record that can change afterwards, and the whole point of the flag is
    that it was true at the moment of filing.
    """
    block = ((data or {}).get("progress") or {}) if isinstance(data, dict) else {}
    if not isinstance(block, dict):
        return PROVENANCE_UNMARKED
    source = str(block.get("source") or "").strip().lower()
    if source in (PROVENANCE_ADOPTED, PROVENANCE_OWN):
        return source
    return PROVENANCE_UNMARKED


ATTESTED_NONE = "attested_none"
NOT_REACHED = "not_reached"
NOT_COLLECTED = "not_collected"
PRESENT = "present"


def item_state(key: str, data: Optional[dict], log_date: Optional[str] = None) -> str:
    """Which of the four states this item is in on this document.

    THE DISTINCTION THIS FUNCTION EXISTS FOR is between ATTESTED_NONE and
    NOT_REACHED. One is a person's statement that there was nothing to report;
    the other is an absence of any statement at all. Rendering them the same
    way -- an em dash, a blank, the word "None" -- turns a gap in the record
    into an attestation nobody made.
    """
    item = ITEMS_BY_KEY.get(str(key or ""))
    if not item:
        return NOT_COLLECTED
    if not item.get("collected"):
        return NOT_COLLECTED
    if not item_applies(key, log_date):
        return NOT_COLLECTED

    block = ((data or {}).get(key) or {}) if isinstance(data, dict) else {}
    if not isinstance(block, dict):
        return NOT_REACHED

    if _has_content(item, block):
        return PRESENT
    if item.get("attestable") and block.get("none_to_report") is True:
        return ATTESTED_NONE
    return NOT_REACHED


def _has_content(item: Dict, block: Dict) -> bool:
    """Does this item's block carry anything the CS actually entered?"""
    for field in item.get("fields") or []:
        value = block.get(field)
        if isinstance(value, (list, tuple)):
            if any(_row_has_content(v) for v in value):
                return True
        elif isinstance(value, str):
            if value.strip():
                return True
        elif isinstance(value, dict):
            if any(str(v or "").strip() for v in value.values()):
                return True
        elif isinstance(value, bool):
            # A BOOLEAN IS AN ANSWER, INCLUDING False.
            # This read `value not in (None, "", False)`, so an item whose only
            # field was False had "no content", resolved to NOT_REACHED, and
            # rendered "— Not recorded" on a BC 3301.13.13 record the
            # superintendent HAD answered. The renderer had the same bug one
            # level down; fixing that alone changed nothing, because this
            # check refused the block before the renderer ever saw it.
            return True
        elif value not in (None, "", False):
            return True
    return False


def _row_has_content(row) -> bool:
    if isinstance(row, dict):
        # `str(v or "")` turns False and 0 into "" and drops them, for the same
        # reason as above. A finding row whose only answer is "not corrected"
        # is a row with content.
        return any(isinstance(v, bool) or str(v or "").strip()
                   for v in row.values())
    return bool(str(row or "").strip())


def unanswered_attestable(data: Optional[dict], log_date: Optional[str] = None) -> List[str]:
    """Attestable items in NOT_REACHED — the ones blocking signature.

    An empty list means every attestable item has either content or an explicit
    nothing-to-report. THE SUBMIT GATE READS THIS: the value of "no unsafe
    conditions observed" on a compliance record comes entirely from a named
    person having put their name to it, so the log cannot be signed while one
    of them is merely blank.
    """
    return [
        key for key in ATTESTABLE_KEYS
        if item_applies(key, log_date)
        and item_state(key, data, log_date) == NOT_REACHED
    ]
