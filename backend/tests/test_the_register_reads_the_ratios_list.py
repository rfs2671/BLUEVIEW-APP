"""TWO LISTS DESCRIBING ONE DAY, AND THEY MUST NOT DISAGREE.

The rail cell, the closing sentence and the completeness block all print one
ratio -- `due_filed of len(due)` -- which counts ONLY the logs this date owed.
`LOGBOOK_TYPE_REGISTRY` declares `toolbox_talk: weekly` and
`subcontractor_orientation: as_needed`, so neither has ever been in that
numerator or that denominator. THE RATIO IS CORRECT AND NOTHING HERE TOUCHES
IT.

THE REGISTER ON PAGE 3 WAS THE OTHER LIST. It iterated `required` -- every type
the project carries, whatever the date owed -- so a weekly or an as-needed type
got a card EVERY SINGLE DAY. On the real 857 Prescott Pl project the Tuesday
report printed a "Tool Box Talk -- Not due today" card and a "Subcontractor
Safety Orientation -- Not due today" card beneath a ratio of "1 of 3", on a day
neither was owed and neither was filed. Five numbered records over a
denominator of three: a reader who counted the register got a different answer
about the day's obligations than the reader who read the number.

WHAT THIS FILE PINS. The register is `due + extra`: the obligations this date
carried, then the records that were filed without being owed. Every row is
therefore either something the day required or a document that exists, and the
two questions stay in the order the completeness block already states them --
required first, additional after, never summed.

AND THE FILED WEEKLY STAYS ON THE PAGE. A toolbox talk filed on the Monday is
still on the Monday's register, still carrying its document, still linked --
it is simply not counted in a ratio that never counted it. A filed compliance
record vanishing from the record index would be a worse defect than the extra
card this replaces.

THE FIXTURES ARE THE PRODUCTION SHAPE. 857 Prescott Pl
(6a7a145e9271db492b9a46ce) requires daily_jobsite, preshift_signin,
toolbox_talk, subcontractor_orientation and osha_log. It filed a toolbox talk
on Monday 2026-08-17 and filed only the daily jobsite log on Tuesday
2026-08-18. Both days are rendered below through the real
`generate_combined_report`.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

PROJECT = "p1"
MONDAY = "2026-08-17"
TUESDAY = "2026-08-18"

#: 857 Prescott Pl's own required set, in its own order.
REQUIRED = ["daily_jobsite", "preshift_signin", "toolbox_talk",
            "subcontractor_orientation", "osha_log"]

#: What that set owes on any given date, read off the registry the same way
#: the report reads it -- DERIVED, so a registry change moves this with it.
_FREQ = {t["key"]: t.get("frequency") for t in server.LOGBOOK_TYPE_REGISTRY}
_LABEL = {t["key"]: (t.get("label") or t["key"])
          for t in server.LOGBOOK_TYPE_REGISTRY}
DUE = [t for t in REQUIRED if _FREQ.get(t) in (None, "daily")]
NOT_DUE = [t for t in REQUIRED if t not in DUE]


# ── A FAKE DATABASE IN THE PRODUCTION SHAPE ────────────────────────────────

class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, *a, **k):
        return list(self._docs)


class _Coll:
    def __init__(self, docs=None, one=None):
        self._docs = docs or []
        self._one = one

    def find(self, *a, **k):
        return _Cursor(self._docs)

    async def find_one(self, *a, **k):
        return self._one

    async def to_list(self, *a, **k):
        return list(self._docs)


class _Db:
    def __init__(self, **colls):
        self._c = colls

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._c.get(n) or _Coll()


def _log(log_type, date, _id=None):
    """A FILED record. `status: submitted` is what filed means for these
    types -- see `logbook_is_filed`."""
    return {"_id": _id or f"lb_{log_type}_{date}", "log_type": log_type,
            "date": date, "status": "submitted",
            "data": {"activities": [], "observations": [],
                     "equipment_on_site": {}, "checklist_items": {}}}


def _render(date, logbooks):
    db = _Db(
        projects=_Coll(one={"_id": PROJECT, "name": "857 Prescott Pl",
                            "address": "857 Prescott Pl, Brooklyn, NY, USA",
                            "project_class": "regular",
                            "required_logbooks": list(REQUIRED)}),
        logbooks=_Coll(docs=logbooks),
        daily_logs=_Coll(one=None),
        workers=_Coll(docs=[]),
        checkins=_Coll(docs=[]),
    )
    with patch.object(server, "db", db):
        return asyncio.run(server.generate_combined_report(PROJECT, date))


#: Monday: the daily jobsite log and a WEEKLY TOOLBOX TALK, both filed.
MONDAY_LOGS = [_log("daily_jobsite", MONDAY), _log("toolbox_talk", MONDAY)]
#: Tuesday: the daily jobsite log and nothing else.
TUESDAY_LOGS = [_log("daily_jobsite", TUESDAY)]


# ── READING THE RENDERED PAGE ──────────────────────────────────────────────

_REC = re.compile(r'<div class="rec">(.*?)(?=<div class="rec">|</td>)', re.S)
_NO = re.compile(r'<div class="recno">(\d+)</div>')
_TITLE = re.compile(r'<div class="rect">(.*?)</div>', re.S)
_STATE = re.compile(r'<div class="recstate ([a-z_]+)">')
_RATIO = re.compile(r'<div class="cnum">(\d+) of (\d+)</div>')
_ADDITIONAL = re.compile(
    r'<div class="cnum">(\d+)</div>\s*<div class="clab">Additional records')


def register(html):
    """Every record on page 3, as (number, title, state, body)."""
    out = []
    for block in _REC.findall(html):
        no, title, state = _NO.search(block), _TITLE.search(block), _STATE.search(block)
        if not (no and title and state):
            continue
        out.append((int(no.group(1)), title.group(1).strip(),
                    state.group(1), block))
    return out


def ratio(html):
    """The (filed, owed) pair the page prints, proved to be printed THREE
    TIMES IN AGREEMENT -- completeness block, closing sentence, rail cell --
    so a test can quote any one of them."""
    m = _RATIO.search(html)
    assert m, "the completeness block printed no required ratio"
    filed, owed = int(m.group(1)), int(m.group(2))
    assert f"{filed} of {owed} required daily logs were filed." in html
    return filed, owed


def additional(html):
    m = _ADDITIONAL.search(html)
    assert m, "the completeness block printed no additional count"
    return int(m.group(1))


# ══════════════════════════════════════════════════════════════════════════

class TheRegisterIsTheListTheRatioReads(unittest.TestCase):
    """THE DEFECT, STATED AS AN EQUALITY.

    The ratio's denominator is a count of obligations. The register is a list
    of records. If the register carries a row for something the denominator
    does not count, the page has told a reader two different things about one
    day.
    """

    @classmethod
    def setUpClass(cls):
        cls.monday = _render(MONDAY, MONDAY_LOGS)
        cls.tuesday = _render(TUESDAY, TUESDAY_LOGS)

    def test_the_fixture_is_the_real_shape(self):
        """GUARD ON THE PREMISE. If the registry ever made toolbox talks
        daily, every assertion below would pass for the wrong reason."""
        self.assertEqual(DUE, ["daily_jobsite", "preshift_signin", "osha_log"])
        self.assertEqual(NOT_DUE, ["toolbox_talk", "subcontractor_orientation"])
        self.assertEqual(_FREQ["toolbox_talk"], "weekly")
        self.assertEqual(_FREQ["subcontractor_orientation"], "as_needed")

    def test_the_ratio_is_untouched_on_both_days(self):
        """THE NUMBER WAS ALWAYS RIGHT. One of three on each day: the daily
        jobsite log filed, the pre-shift sign-in and the OSHA log not. The
        Monday's toolbox talk is not in it and never was."""
        self.assertEqual(ratio(self.monday), (1, 3))
        self.assertEqual(ratio(self.tuesday), (1, 3))

    def test_the_register_counts_the_same_obligations_as_the_ratio(self):
        """THE EQUALITY ITSELF, ON BOTH DAYS.

        Every row that is an obligation -- filed or not filed -- is one the
        denominator counted, and there are exactly as many of them as the
        denominator says.
        """
        for day, html in (("Monday", self.monday), ("Tuesday", self.tuesday)):
            with self.subTest(day=day):
                _, owed = ratio(html)
                obligations = [c for c in register(html)
                               if c[2] in ("filed", "missing")]
                self.assertEqual(
                    len(obligations), owed,
                    f"{day}: the register carries {len(obligations)} "
                    f"obligations under a ratio out of {owed}")
                self.assertEqual([c[1] for c in obligations],
                                 [_LABEL[t] for t in DUE])

    def test_the_ratios_denominator_is_the_leading_run_of_cards(self):
        """AND THEY ARE THE FIRST N, so the numbering itself carries the
        claim: records 01 to N are the day's obligations and anything after
        is the additional column."""
        for day, html in (("Monday", self.monday), ("Tuesday", self.tuesday)):
            with self.subTest(day=day):
                _, owed = ratio(html)
                cards = register(html)
                self.assertEqual([c[0] for c in cards],
                                 list(range(1, len(cards) + 1)))
                self.assertEqual([c[1] for c in cards[:owed]],
                                 [_LABEL[t] for t in DUE])
                for c in cards[:owed]:
                    self.assertIn(c[2], ("filed", "missing"))

    def test_a_type_not_owed_and_not_filed_gets_no_card(self):
        """THE TUESDAY. Neither the weekly toolbox talk nor the as-needed
        orientation was owed, and neither was filed. A row for either is a
        row about nothing -- a record nobody asked for and nobody produced."""
        titles = [c[1] for c in register(self.tuesday)]
        for t in NOT_DUE:
            self.assertNotIn(_LABEL[t], titles)
        self.assertNotIn("Not due today", self.tuesday)


class TheFiledWeeklyStaysOnTheRecord(unittest.TestCase):
    """A FILED COMPLIANCE DOCUMENT DOES NOT DISAPPEAR FROM THE RECORD INDEX.

    That is the failure mode the narrowing must not cause, and it is worse
    than the extra card it replaces: a toolbox talk filed on Monday is a
    document that exists, was signed, and is linked from this page.
    """

    @classmethod
    def setUpClass(cls):
        cls.monday = _render(MONDAY, MONDAY_LOGS)

    def _toolbox(self):
        for c in register(self.monday):
            if c[1] == _LABEL["toolbox_talk"]:
                return c
        self.fail("the toolbox talk filed on Monday is not on Monday's "
                  "register at all")

    def test_it_is_on_the_register(self):
        self._toolbox()

    def test_it_is_outside_the_ratio_and_inside_the_additional_column(self):
        _, owed = ratio(self.monday)
        self.assertGreater(self._toolbox()[0], owed)
        self.assertEqual(additional(self.monday), 1)

    def test_it_is_not_amber(self):
        """NOT A DEFICIENCY. It was not owed; it was filed anyway."""
        self.assertEqual(self._toolbox()[2], "not_due")

    def test_it_does_not_claim_nothing_was_filed(self):
        """THE ABSENCE WORDING BELONGS TO AN ABSENT RECORD. Printing "No
        record filed for 17 August 2026" under a document that WAS filed on
        17 August 2026 is the report contradicting the filing."""
        self.assertNotIn("No record filed", self._toolbox()[3])


if __name__ == "__main__":
    unittest.main()
