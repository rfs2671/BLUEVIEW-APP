"""Page 1 — the progress report an investor actually reads.

WHY IT EXISTS. The operator showed the daily report to an investor who had put
$2M in, and got back: "I don't see what was really done today at the job... No
piles installation? Are they done with the piles?" The document was a
compliance filing being sent to someone who needed a progress update. Both
audiences are real, so it is one document with two sections: this page answers
the question, and page 2 onward is the filing, unchanged.

WHAT MUST NEVER APPEAR HERE. Percent complete, which cannot be computed
honestly from taps and is worse than nothing in front of a lender; and anything
about cost or draw status, which this app does not hold.

Headcount is FROM CHECK-INS everywhere on this page, per the operator's ruling.
The hand-entered numbers on the Site Superintendent and SSC logs stay in their
own page-2 sections, where they are that form's record.
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402
from tests.source_text import code_of  # noqa: E402

DATE = "2026-08-11"
PROJECT = "proj1"


def _match(doc, query):
    for k, v in query.items():
        if isinstance(v, dict):
            if "$ne" in v and doc.get(k) == v["$ne"]:
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _Coll:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, projection=None):
        return _Cursor([d for d in self.docs if _match(d, query or {})])

    async def find_one(self, query=None, projection=None, sort=None):
        for d in self.docs:
            if _match(d, query or {}):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, query=None):
        return sum(1 for d in self.docs if _match(d, query or {}))


class _DB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self[n]

    def __getitem__(self, n):
        if n not in self._c:
            self._c[n] = _Coll()
        return self._c[n]


def _checkin(name, company, blocked=False):
    return {"project_id": PROJECT, "date": DATE, "worker_name": name,
            "company": company, "blocked": blocked,
            "check_in_time": "2026-08-11T11:00:00Z"}


def _activity(company, trade, desc, loc, photos=0):
    return {
        "crew_id": "C-1", "company": company, "trade": trade, "num_workers": 2,
        "work_description": desc, "work_locations": loc,
        # enhanced_r2_key / thumb_r2_key are the names the serve ladder reads
        # (_logbook_photo_sources); a photo with neither has no surviving copy
        # and is deliberately skipped rather than rendered as a broken image.
        "photos": [{"id": f"p{i}", "enhanced_r2_key": f"e{i}",
                    "thumb_r2_key": f"t{i}", "enhance_status": "done"}
                   for i in range(photos)],
    }


DAILY_JOBSITE = {
    "_id": "lb_dj", "project_id": PROJECT, "date": DATE,
    "log_type": "daily_jobsite", "is_deleted": False,
    "cp_signature": {"image": "x"}, "cp_name": "Carl CP",
    "data": {
        "weather": "Sunny", "weather_temp": "78F", "weather_fetch_state": "ok",
        "activities": [
            _activity("Kestrel Electric", "Electrical",
                      "branch rough-in", "3rd floor", photos=2),
            _activity("Air Star Mechanical", "HVAC / Mechanical",
                      "ductwork rough", "2nd floor", photos=1),
        ],
        "observations": [{
            "description": "guardrail loose at the east stair",
            "responsible_party": "Kestrel Electric",
            "remedy": "re-secured before end of shift",
        }],
        "checklist_items": {
            "fall_protections": {"result": "fail", "note": "north edge open"},
            "permits": {"result": "pass", "note": ""},
        },
    },
}


class Base(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.db = _DB()
        self.db.projects.docs = [{
            "_id": PROJECT, "name": "588 Thomas S Boyland Street",
            "address": "588 Thomas S Boyland St, Brooklyn",
        }]
        self.db.logbooks.docs = [copy.deepcopy(DAILY_JOBSITE)]
        self.db.checkins.docs = [
            _checkin("A", "Kestrel Electric"), _checkin("B", "Kestrel Electric"),
            _checkin("C", "Air Star Mechanical"),
            _checkin("D", "Air Star Mechanical"), _checkin("E", "Air Star Mechanical"),
        ]
        self._orig = {"db": server.db, "tqid": server.to_query_id}
        server.db = self.db
        server.to_query_id = lambda x: x

    def tearDown(self):
        server.db = self._orig["db"]
        server.to_query_id = self._orig["tqid"]
        self.loop.close()

    def html(self):
        return self.loop.run_until_complete(
            server.generate_combined_report(PROJECT, DATE))

    def page1(self):
        """Everything before the page break — page 2 begins after it."""
        h = self.html()
        i = h.find("page-break-after")
        self.assertGreater(i, -1, "no page break between page 1 and the filing")
        return h[:i]


class ItAnswersTheQuestionThatWasAsked(Base):
    def test_the_project_address_and_a_human_date(self):
        p1 = self.page1()
        self.assertIn("588 Thomas S Boyland Street", p1)
        self.assertIn("588 Thomas S Boyland St, Brooklyn", p1)
        self.assertIn("August 11, 2026", p1)

    def test_the_machine_date_is_not_on_page_1(self):
        self.assertNotIn("2026-08-11", self.page1())

    def test_weather(self):
        self.assertIn("Sunny", self.page1())

    def test_a_line_per_subcontractor_with_what_they_did(self):
        p1 = self.page1()
        for expected in ("Kestrel Electric", "Branch rough-in",
                         "Air Star Mechanical", "Ductwork rough"):
            self.assertIn(expected, p1, expected)

    def test_photos_are_grouped_and_captioned_from_real_data(self):
        p1 = self.page1()
        # <img>, not the URL: each photo emits the URL twice, once in the
        # href to the full size and once in the src of the thumbnail.
        self.assertEqual(p1.count("<img "), 3,
                         "every renderable photo appears exactly once")
        self.assertIn("/api/reports/logbook-photo/lb_dj/", p1)
        self.assertIn("3rd floor", p1)

    def test_what_was_flagged_is_on_the_page(self):
        p1 = self.page1()
        self.assertIn("guardrail loose at the east stair".capitalize(), p1)
        self.assertIn("Failed inspection: Fall Protections", p1)
        self.assertIn("north edge open", p1)

    def test_a_passed_inspection_is_NOT_flagged(self):
        self.assertNotIn("Failed inspection: Permits", self.page1())

    def test_one_line_of_compliance_status(self):
        self.assertIn("All 1 required logs filed and signed.", self.page1())

    def test_an_amendment_does_not_inflate_the_count(self):
        """An amendment is a correction to a filing, not another filing.
        Counting it would report more logs than the day required."""
        amend = copy.deepcopy(DAILY_JOBSITE)
        amend.update({"_id": "lb_amend", "is_amendment": True})
        amend.pop("cp_signature")
        self.db.logbooks.docs.append(amend)
        self.assertIn("All 1 required logs filed and signed.", self.page1())

    def test_a_photo_with_no_surviving_copy_is_SKIPPED(self):
        """Every copy purged. It must vanish rather than render as a broken
        image — a broken image on a progress report reads as evidence that
        failed to load, which is worse than a photo that is simply absent."""
        acts = self.db.logbooks.docs[0]["data"]["activities"]
        acts[0]["photos"] = [{"id": "gone", "enhance_status": "done"}]
        p1 = self.page1()
        self.assertEqual(p1.count('<img '), 1, 'only the intact photo renders')

    def test_an_unsigned_log_says_so_instead(self):
        self.db.logbooks.docs[0].pop("cp_signature")
        self.assertIn("awaiting signature", self.page1())


class HeadcountComesFromCheckIns(Base):
    def test_the_total_is_the_gate_count(self):
        p1 = self.page1()
        self.assertIn("Workers checked in at the gate:", p1)
        self.assertIn(">5", p1.replace(" ", "").replace("\n", ""))

    def test_and_it_breaks_down_by_subcontractor(self):
        p1 = self.page1()
        self.assertIn("Headcount by subcontractor", p1)
        self.assertIn("Kestrel Electric", p1)
        self.assertIn("Air Star Mechanical", p1)

    def test_a_worker_turned_away_at_the_gate_is_not_counted(self):
        """He was refused and did no work; counting him overstates the day."""
        self.db.checkins.docs.append(_checkin("F", "Kestrel Electric", blocked=True))
        p1 = self.page1()
        self.assertIn("Workers checked in at the gate:", p1)
        self.assertNotIn("Workers checked in at the gate:</strong> 6", p1)

    def test_a_worker_with_no_company_is_counted_and_named_honestly(self):
        self.db.checkins.docs.append(_checkin("G", ""))
        p1 = self.page1()
        self.assertIn("Not yet assigned", p1)

    def test_the_UNASSIGNED_sentinel_never_reaches_the_page(self):
        self.db.checkins.docs.append(_checkin("H", "UNASSIGNED"))
        self.assertNotIn("UNASSIGNED", self.page1())


class ItPromisesNothingItCannotKnow(Base):
    """The two things the operator ruled out, asserted rather than assumed."""

    BANNED = ["percent complete", "% complete", "percent_complete",
              "draw", "invoice", "budget", "cost to date", "spend"]

    def test_no_completion_percentage_and_no_money(self):
        p1 = self.page1().lower()
        for term in self.BANNED:
            self.assertNotIn(term, p1, term)

    def test_it_makes_no_completion_claim_about_the_work(self):
        p1 = self.page1().lower()
        for term in ("finished", "wrapping up", "on schedule", "ahead of"):
            self.assertNotIn(term, p1, term)


class PageTwoIsUntouched(Base):
    """The filing is the legal record. Page 1 sits in front of it and changes
    nothing about it."""

    def test_the_logbook_section_still_renders_after_the_break(self):
        h = self.html()
        tail = h[h.find("page-break-after"):]
        self.assertIn("Daily Jobsite Log (NYC DOB 3301-02)", tail)

    def test_page_1_comes_FIRST(self):
        h = self.html()
        self.assertLess(h.find("Daily Progress Report"),
                        h.find("Daily Jobsite Log (NYC DOB 3301-02)"))

    def test_the_payload_keys_the_renderers_read_are_untouched(self):
        code = code_of("server.py")
        for key in ('"activities"', '"observations"', '"checklist_items"',
                    '"weather"', '"work_description"', '"work_locations"'):
            self.assertIn(key, code, key)


class TheDateHelper(unittest.TestCase):
    def test_it_reads_like_a_person_wrote_it(self):
        self.assertEqual(server._report_date_long("2026-08-11"), "August 11, 2026")
        self.assertEqual(server._report_date_long("2026-01-01"), "January 1, 2026")

    def test_no_timezone_is_introduced(self):
        """The string is split, never parsed into a datetime — a UTC parse
        renders the day BEFORE on a phone west of Greenwich, which this
        project has shipped once already."""
        self.assertEqual(server._report_date_long("2026-12-31"), "December 31, 2026")

    def test_junk_degrades_to_itself_rather_than_crashing_a_report(self):
        for junk in ("", "not-a-date", "2026-13-99", None):
            self.assertIsInstance(server._report_date_long(junk), str)


if __name__ == "__main__":
    unittest.main()
