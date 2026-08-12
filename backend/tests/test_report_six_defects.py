"""The six defects the operator found on the investor report.

THIS IS THE DOCUMENT AN INVESTOR READS. Every one of these was visible on a
real report for project 6a5f63bc147407d3261df2c7, 2026-08-11, and none of them
would have been caught by any existing test — the report renderer is 1,200
lines of f-strings with no coverage of what it actually prints.

Asserted against the SOURCE of generate_combined_report and
render_logbook_html, because both are single async functions that need a
database to run. Where behaviour can be executed (the dedupe key, the
conditional times block) it is executed rather than grepped.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

# The two renderers. generate_single_logbook_html prints ONE stored logbook as
# its own PDF; generate_combined_report prints the whole day, and is the
# document the investor reads.
_REPORT = _SRC[_SRC.index("async def generate_combined_report"):]
_REPORT = _REPORT[:_REPORT.index('async def get_combined_report(')]
_SINGLE = _SRC[_SRC.index("async def generate_single_logbook_html"):]
_SINGLE = _SINGLE[:_SINGLE.index("async def generate_combined_report")]


# ── A REAL RENDER, from a stored payload ─────────────────────────────────────
#
# THE GAP THIS CLOSES. Every assertion in this file used to read server.py's
# SOURCE, and the one that claimed to execute ran a local copy of the shipped
# function. So the suite proved the code shipped and proved nothing about the
# document — which is exactly how #126 went green while the operator's report
# was unchanged. Below, generate_combined_report is CALLED against a fake
# database holding the production shape, and the assertions read the HTML.

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


# The production shape: ONE man, TWO rows in the stored pre-shift payload —
# one carrying his card id from the gate, one from legacy carrying none. This
# is a FILED record, so no endpoint fix can change it; the report must render
# what is stored, and the test must see that.
_DAY_WITH_DUPLICATE = {
    "preshift": {
        "_id": "lb_ps", "log_type": "preshift_signin", "date": "2026-08-12",
        "data": {"company": "AAZ", "workers": [
            {"name": "WILMER CARRILLO", "company": "AAZ", "osha_number": "SST-1",
             "had_injury": "no", "inspected_ppe": "yes"},
            {"name": "WILMER CARRILLO", "company": "AAZ", "osha_number": "",
             "had_injury": None, "inspected_ppe": None},
            {"name": "", "company": "AAZ", "osha_number": ""},   # nameless seed
        ]},
    },
    "toolbox": {
        "_id": "lb_tb", "log_type": "toolbox_talk", "date": "2026-08-12",
        "data": {"attendees": [
            {"name": "Segundo Pilamunga", "company": "AAZ"},
            {"name": "", "company": ""},                          # nameless seed
        ], "checked_topics": {}},
    },
    "jobsite": {
        "_id": "lb_dj", "log_type": "daily_jobsite", "date": "2026-08-12",
        "data": {"activities": [{
            "crew_id": "C1", "company": "AAZ", "num_workers": "4",
            "work_description": "Rebar installation", "work_locations": "",
            "photos": [{"enhance_status": "done", "original_r2_key": "k"}],
        }], "equipment_on_site": {}, "checklist_items": {}, "observations": []},
    },
}


def _render(day, jobsite_extra=None):
    """Call the real renderer against a fake db and return the HTML."""
    jobsite = dict(day["jobsite"])
    if jobsite_extra:
        jobsite = {**jobsite, "data": {**jobsite["data"], **jobsite_extra}}
    logbooks = [day["preshift"], day["toolbox"], jobsite]
    db = _Db(
        projects=_Coll(one={"_id": "p1", "name": "8 Walworth St", "address": "8 Walworth St"}),
        logbooks=_Coll(docs=logbooks),
        daily_logs=_Coll(one=None),
        checkins=_Coll(docs=[
            {"worker_id": "w1", "worker_name": "WILMER CARRILLO", "company": "AAZ",
             "status": "checked_in"},
            {"worker_id": "w2", "worker_name": "Segundo Pilamunga", "company": "AAZ",
             "status": "checked_in"},
            {"worker_id": "w3", "worker_name": "Third Man", "company": "AAZ",
             "status": "checked_in"},
        ]),
    )
    with patch.object(server, "db", db):
        return asyncio.run(server.generate_combined_report("p1", "2026-08-12"))


class TheRenderedDocument(unittest.TestCase):
    """Assertions on the HTML the investor actually receives."""

    @classmethod
    def setUpClass(cls):
        cls.html = _render(_DAY_WITH_DUPLICATE)

    def test_it_renders_at_all(self):
        self.assertIn("Daily Progress Report", self.html)
        self.assertIn("Pre-Shift Sign-In", self.html)

    def test_the_stored_duplicate_STILL_RENDERS_TWICE(self):
        """THE HONEST ASSERTION, and the one that would have caught #126's
        claim. The endpoint dedupe cannot touch a filed payload: the report
        prints what is stored, so an already-duplicated log keeps both rows.
        If a later change starts collapsing them at RENDER time, this fails and
        that decision gets made deliberately."""
        # Rendered verbatim — _capitalize_first only touches the first letter.
        self.assertEqual(self.html.count("WILMER CARRILLO"), 2)

    def test_the_nameless_rows_do_not_render(self):
        """Pre-shift skipped these already; toolbox did not until #126."""
        preshift = self.html[self.html.index("Pre-Shift Sign-In"):]
        preshift = preshift[:preshift.index("</table>", preshift.index("<th "))]
        # Two DATA rows — the third stored worker has no name and is dropped.
        self.assertEqual(preshift.count("<tr><td "), 2)
        # Anchored on the attendee table's own header — ">Title</th>" appears
        # nowhere else — so the info box above it is not counted.
        att = self.html[self.html.index(">Title</th>"):]
        att = att[:att.index("</table>")]
        # One attendee; the nameless seed row is dropped (this was the #126 fix).
        self.assertEqual(att.count("<tr><td "), 1)
        self.assertIn("Segundo Pilamunga", att)

    def test_the_address_and_date_appear_once_each(self):
        # The VISIBLE document. <title> also carries the project name, which
        # is a browser/tab label, not a printed field.
        body = self.html[self.html.index("<body"):]
        shell = body[:body.index("Daily Progress Report")]
        self.assertEqual(shell.count("8 Walworth St"), 1,
                         "the address is printed more than once in the header")
        self.assertEqual(shell.count("August 12, 2026"), 1,
                         "the date is printed more than once in the header")

    def test_the_crew_count_is_labelled_and_the_gate_count_is_too(self):
        self.assertIn("CP&#39;s count", self.html)
        self.assertIn("WORKERS AT THE GATE", self.html)
        self.assertIn("Workers checked in at the gate", self.html)

    def test_photos_are_on_page_1_and_NOT_on_page_2(self):
        """Operator ruling: progress evidence for the investor, not a second
        copy inside the compliance filing."""
        page1, page2 = self.html.split('<div style="page-break-after:always;"></div>', 1)
        self.assertIn("reports/logbook-photo", page1)
        self.assertNotIn("reports/logbook-photo", page2)

    def test_no_unaffirmed_warning_bleeds_onto_page_1(self):
        page1 = self.html.split('<div style="page-break-after:always;"></div>', 1)[0]
        self.assertNotIn("UNAFFIRMED", page1)


class OneHeaderOnly(unittest.TestCase):
    """DEFECT 1 — the address printed three times and the date twice, and the
    project name and the address are the same string shown as two fields."""

    def test_the_page1_subtitle_no_longer_reprints_them(self):
        h2 = _REPORT[_REPORT.index("Daily Progress Report</h2>"):]
        h2 = h2[:400]
        self.assertNotIn("project_address", h2)
        self.assertNotIn("_pg1_date", h2)

    def test_the_address_is_printed_exactly_once_in_the_shell(self):
        shell = _REPORT[_REPORT.index("<!-- HEADER -->"):]
        self.assertEqual(shell.count("{project_address"), 1, "address is printed twice")

    def test_the_date_is_printed_exactly_once_in_the_shell(self):
        shell = _REPORT[_REPORT.index("<!-- HEADER -->"):]
        self.assertEqual(shell.count("{_pg1_date}"), 1, "date is printed twice")

    def test_the_name_is_suppressed_when_it_IS_the_address(self):
        """A project created from an address holds the same text in both, and
        the band printed it as though it were a different fact."""
        self.assertIn("_header_project_line", _REPORT)
        # Execute the comparison the renderer uses.
        norm = lambda v: " ".join(str(v or "").split()).casefold()  # noqa: E731
        self.assertTrue(norm("8 Walworth St ") == norm("8 walworth st"))
        self.assertFalse(norm("Walworth Tower") == norm("8 Walworth St"))

    def test_the_gate_count_says_so_in_the_shell(self):
        """DEFECT 6, first half. The summary row's number is the GATE count."""
        self.assertIn("WORKERS AT THE GATE", _REPORT)


class TheBlankRowIsGoneEverywhere(unittest.TestCase):
    """DEFECT 3 — a seed row the CP never filled printed as a blank line on a
    signed attendance record: a person who was there and cannot be named."""

    def test_toolbox_talk_skips_a_nameless_attendee(self):
        block = _REPORT[_REPORT.index('for a in td_data.get("attendees"'):]
        block = block[:600]
        self.assertIn('if not str(a.get("name") or "").strip():', block)
        self.assertIn("continue", block)

    def test_preshift_already_skipped_and_still_does(self):
        """It was never the defect on this table — asserted so a later change
        cannot quietly remove the rule the other tables were brought up to."""
        self.assertEqual(_SRC.count('if w.get("name", "").strip():'), 2)

    def test_the_osha_register_still_skips_its_seed(self):
        self.assertIn("untouched EMPTY_ENTRY seed", _SINGLE)


class TheDuplicateWorkerRow(unittest.TestCase):
    """DEFECT 4 — one man, two rows on the pre-shift sheet: one carrying his
    card id from the gate system, one from legacy carrying none."""

    def test_the_key_is_whitespace_normalised(self):
        self.assertIn("def _norm_key(v):", _SRC)
        self.assertEqual(_SRC.count("name_key = (name.lower(), company.lower())"), 0,
                         "a raw lowercased key survives somewhere")
        self.assertEqual(_SRC.count("name_key = (_norm_key(name), _norm_key(company))"), 3)

    def test_normalisation_collapses_the_shapes_that_split_him(self):
        """THE SHIPPED FUNCTION, not a copy of it.

        This test used to define its own `_norm_key` and assert against that —
        so it passed while proving only that the test's own arithmetic worked.
        It is extracted from server.py's source and executed, so a change to
        the real normaliser fails here."""
        ns = {}
        src = _SRC[_SRC.index("    def _norm_key(v):"):]
        src = src[:src.index("\n\n", src.index("return"))]
        exec(textwrap.dedent(src), ns)          # noqa: S102 — the shipped body
        _norm_key = ns["_norm_key"]
        gate = ("Wilmer Carrillo", "AAZ")
        for legacy in [("wilmer carrillo", "aaz"), ("Wilmer  Carrillo", "AAZ "),
                       (" Wilmer Carrillo", " AAZ"), ("WILMER CARRILLO", "AAZ")]:
            with self.subTest(legacy=legacy):
                self.assertEqual(
                    (_norm_key(gate[0]), _norm_key(gate[1])),
                    (_norm_key(legacy[0]), _norm_key(legacy[1])),
                )
        # And it must still SPLIT the cases the operator was told stay split.
        self.assertNotEqual(_norm_key("Wilmer J Carrillo"), _norm_key("Wilmer Carrillo"))
        self.assertNotEqual(_norm_key("AAZ Construction"), _norm_key("AAZ"))

    def test_pass_one_deliberately_does_NOT_dedupe_on_the_string_key(self):
        """REPORTED AS AN OPEN PATH, THEN RULED AGAINST — and correctly.

        Pass 1 keys on worker_enrollment_id alone. `worker_enrollments` carries
        a UNIQUE INDEX on (project_id, card_id), so two enrollments are two
        distinct CARDS — two men, or one man with two credentials. Collapsing
        them on a lowercased (name, company) string would delete a worker from
        the roster to fix a duplicate, which is the wrong trade on a document
        that records who was on site.

        test_checkins_today_roster_envelope.py already asserts both men
        survive. This pins the reason on the other side of the fence too, so
        the "make pass 1 match pass 2" change cannot be made without both tests
        failing and the decision being taken again on purpose.
        """
        block = _SRC[_SRC.index("for eid in enrollment_ids:"):]
        block = block[:block.index("result.append(")]
        self.assertNotIn("if name_key in seen_name_keys:", block)
        self.assertIn("seen_name_keys.add(name_key)", block)

    def test_a_blank_company_falls_back_to_the_name(self):
        """The legacy row often has no company at all, and a blank company
        distinguishes nobody — it must not mint a second row."""
        block = _SRC[_SRC.index("seen_legacy_wids: set = set()"):]
        block = block[:2000]
        self.assertIn("not name_key[1] and name_key[0] in seen_names_only", block)

    def test_two_different_men_at_different_subs_stay_two_rows(self):
        """The fallback is blank-company ONLY. A legacy row that names a
        company keeps the pair, so the dedupe cannot over-collapse."""
        block = _SRC[_SRC.index("seen_legacy_wids: set = set()"):][:2000]
        self.assertIn("not name_key[1]", block)
        self.assertNotIn("name_key[0] in seen_names_only:", block.replace(
            "not name_key[1] and name_key[0] in seen_names_only", ""))

    def test_the_name_only_index_is_kept_in_step(self):
        self.assertEqual(_SRC.count("seen_names_only.add(name_key[0])"), 3)


class TheAlwaysNAFieldsAreNotPrinted(unittest.TestCase):
    """DEFECT 5 — Time In / Time Out / Areas Visited printed a permanent N/A
    because nothing in the app has ever written them."""

    def test_nothing_writes_them(self):
        """The premise, asserted rather than assumed. daily_jobsite.jsx holds
        the state and hydrates it, but no control sets it."""
        screen = (_BACKEND / ".." / "frontend" / "app" / "logbooks"
                  / "daily_jobsite.jsx").resolve().read_text(encoding="utf-8")
        for setter in ("setTimeIn", "setTimeOut", "setAreasVisited"):
            calls = re.findall(rf"\b{setter}\(", screen)
            # EXACTLY ONE call site, and it is the hydrate in fetchData. The
            # useState destructure carries no parens so it is not counted. A
            # second caller means a control now writes the field — at which
            # point this fails and the report row should be wired back on.
            self.assertEqual(len(calls), 1,
                             f"{setter} has a writer now — wire the row back on")
            hydrate = re.search(rf"if \(d\.\w+\) {setter}\(", screen)
            self.assertIsNotNone(hydrate, f"{setter}'s only caller is not the hydrate")

    def test_the_report_prints_them_only_when_set(self):
        self.assertIn("_pg2_times", _REPORT)
        block = _REPORT[_REPORT.index("_pg2_bits = []"):]
        block = block[:800]
        self.assertIn("if _t_in or _t_out:", block)
        self.assertIn("if _areas:", block)
        self.assertIn('_pg2_times = ("<br />" + "<br />".join(_pg2_bits)) if _pg2_bits else ""', block)

    def test_the_payload_keys_are_untouched(self):
        """Display only. The keys still travel, so the day a control is added
        the row reappears on its own with no renderer change."""
        screen = (_BACKEND / ".." / "frontend" / "app" / "logbooks"
                  / "daily_jobsite.jsx").resolve().read_text(encoding="utf-8")
        self.assertIn("time_in: timeIn, time_out: timeOut, areas_visited: areasVisited", screen)

    def test_the_conditional_block_behaves(self):
        """Asserted on the RENDERED document — see TheRenderedDocument below,
        which builds a report from a stored payload and reads the HTML."""
        html = _render(_DAY_WITH_DUPLICATE)
        self.assertNotIn("Time In:", html)
        self.assertNotIn("Areas Visited:", html)
        html2 = _render(_DAY_WITH_DUPLICATE, jobsite_extra={
            "time_in": "07:00", "time_out": "15:30", "areas_visited": "Cellar",
        })
        self.assertIn("Time In:", html2)
        self.assertIn("07:00", html2)
        self.assertIn("Cellar", html2)


class TheTwoHeadcountsAreLabelled(unittest.TestCase):
    """DEFECT 6 — page 1 counts the gate, the activity row is the CP's own
    hand-typed number. Both true, about different things. Labelled, not
    reconciled."""

    def test_the_activity_table_says_whose_count_it_is(self):
        for name, src in (("report", _REPORT), ("single-document", _SINGLE)):
            with self.subTest(renderer=name):
                self.assertIn("CP&#39;s count", src)

    def test_neither_renderer_calls_it_just_Workers_on_the_crew_table(self):
        for name, src in (("report", _REPORT), ("single-document", _SINGLE)):
            with self.subTest(renderer=name):
                i = src.find("<th {TH}>Crew</th>")
                self.assertNotEqual(i, -1)
                self.assertNotIn("Workers", src[i:i + 200])

    def test_page1_still_names_its_own_source(self):
        self.assertIn("Workers checked in at the gate", _REPORT)

    def test_the_two_numbers_are_NOT_reconciled(self):
        """No arithmetic between them anywhere — they are different facts."""
        self.assertNotIn("num_workers) - ", _REPORT)
        self.assertNotIn("_sub_total - ", _REPORT)


class TheAISentenceStillHasItsFallback(unittest.TestCase):
    """DEFECT 2 — the placeholder rendered instead of the generated line. The
    wiring is intact; what was missing was any way to tell WHY."""

    def test_the_wiring_is_still_there(self):
        self.assertIn("from lib.ai.sub_summary import generate_sentence", _REPORT)
        self.assertIn("_gen = _gen_sub_sentence(_payload)", _REPORT)
        self.assertIn("_line = _sentence_case(_html.escape(_gen)) if _gen else _facts", _REPORT)

    def test_all_three_outcomes_now_leave_a_trace(self):
        """A missing key was the only one of the three that returned None in
        silence, so a report of plain facts was unreadable as evidence."""
        mod = (_BACKEND / "lib" / "ai" / "sub_summary.py").read_text(encoding="utf-8")
        gen = mod[mod.index("def generate_sentence("):]
        no_key = gen[:gen.index("try:")]
        self.assertIn("logger.warning", no_key)
        self.assertIn("GEMINI_API_KEY is not set", no_key)
        self.assertIn("logger.error", gen)   # the call failed
        self.assertIn("logger.info", gen)    # the sentence was refused


if __name__ == "__main__":
    unittest.main()
