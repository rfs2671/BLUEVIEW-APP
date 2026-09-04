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
from datetime import datetime, timezone
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


def _render_with_osha(day):
    """Same fake db as _render, plus an osha_log in the logbook list."""
    logbooks = [day["preshift"], day["toolbox"], day["jobsite"], day["osha"]]
    db = _Db(
        projects=_Coll(one={"_id": "p1", "name": "8 Walworth St", "address": "8 Walworth St"}),
        logbooks=_Coll(docs=logbooks),
        daily_logs=_Coll(one=None),
        workers=_Coll(docs=[]),
        checkins=_Coll(docs=[]),
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
        # ANCHORED ON THE SECTION HEADER, not on the bare name. Page 1's
        # compliance line names the required logs too, and it resolves them
        # through LOGBOOK_TYPE_REGISTRY — which used to say "Pre-Shift Safety
        # Meeting", so the first occurrence of this string happened to be the
        # page-2 header. Now that the registry agrees with the renderer the
        # name appears on page 1 as well, and a bare .index() slices from the
        # compliance line into the wrong table. This is section_title's own
        # closing markup, which nothing else emits.
        preshift = self.html[self.html.index(">Pre-Shift Sign-In</td></tr></table>"):]
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
        block = block[:block.index("att_rows +=")]
        self.assertIn('if not str(a.get("name") or "").strip():', block)
        self.assertIn("continue", block)

    def test_the_per_logbook_PDF_skips_one_too(self):
        """DEVICE ROUND 6, item 2. The gate above was applied to the emailed
        report and nowhere else, while its own comment said the pre-shift sheet
        and the OSHA register "already use" it and this table "was the one that
        never got it". The second half was false: render_logbook_html — the
        document an inspector asks for BY NAME — had no name gate on this table
        at all, so one stored talk printed two different attendance records.

        A nameless row there was not blank, either: it carried Present ✓ from
        the CP's mark and Confirmed at gate ✓ from a worker tap, against a man
        the record does not identify."""
        block = _SINGLE[_SINGLE.index('for a in data.get("attendees"'):]
        block = block[:block.index("att_rows +=")]
        self.assertIn('if not str(a.get("name") or "").strip():', block)
        self.assertIn("continue", block)

    def test_preshift_already_skipped_and_still_does(self):
        """It was never the defect on this table — asserted so a later change
        cannot quietly remove the rule the other tables were brought up to."""
        self.assertEqual(_SRC.count('if w.get("name", "").strip():'), 2)

    def test_the_osha_register_drops_a_row_that_names_nobody(self):
        """WIDENED, device round 6 item 1. It skipped a row carrying none of
        five fields — the untouched seed — and printed one carrying a company
        and a card number against no name. A certification register is a list
        of statements about named men, so the name is the rule and the seed
        row (which has no name either) is still dropped by it."""
        branch = _SINGLE[_SINGLE.index('elif log_type == "osha_log":'):]
        branch = branch[:branch.index("elif log_type ==", 10)]
        m = re.search(r"has\(e, k\) for k in\s*\n?\s*\(([^)]*)\)", branch)
        self.assertIsNotNone(m, "the osha row gate is unreadable")
        self.assertEqual(tuple(re.findall(r'"([a-z_]+)"', m.group(1))),
                         ("worker_name",))


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

    def test_nothing_writes_areas_visited(self):
        """The premise, asserted rather than assumed. daily_jobsite.jsx holds
        the state and hydrates it, but no control sets it."""
        screen = (_BACKEND / ".." / "frontend" / "app" / "logbooks"
                  / "daily_jobsite.jsx").resolve().read_text(encoding="utf-8")
        for setter in ("setAreasVisited",):
            calls = re.findall(rf"\b{setter}\(", screen)
            # EXACTLY ONE call site, and it is the hydrate in fetchData. The
            # useState destructure carries no parens so it is not counted. A
            # second caller means a control now writes the field — at which
            # point this fails and the report row should be wired back on.
            self.assertEqual(len(calls), 1,
                             f"{setter} has a writer now — wire the row back on")
            hydrate = re.search(rf"if \(d\.\w+\) {setter}\(", screen)
            self.assertIsNotNone(hydrate, f"{setter}'s only caller is not the hydrate")

    def test_the_two_time_fields_are_gone_from_the_screen_entirely(self):
        """TIME IN / TIME OUT WENT FURTHER THAN THE ROW.

        This class used to assert that all THREE keys still travelled and only
        the display was suppressed. For `areas_visited` that is still the deal.
        For the two times it is not: the state, the payload keys and the
        hydrate lines are DELETED, because a field with no control is not a
        field the log collects, and the CP's own hours belong to item 1 of the
        superintendent log (`presence.arrived_at` / `presence.departed_at`),
        where they are now chosen from a clock and required before it files.

        ASSERTED ON THE SCREEN, not on the renderer, because the renderer is
        allowed to keep reading them — see the class below."""
        screen = (_BACKEND / ".." / "frontend" / "app" / "logbooks"
                  / "daily_jobsite.jsx").resolve().read_text(encoding="utf-8")
        # Comments discuss the removal by name, so read CODE. A prose mention
        # of `setTimeIn` must not keep this green or red on its own.
        code = re.sub(r"/\*[\s\S]*?\*/", "", screen)
        code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
        for gone in ("timeIn", "setTimeIn", "timeOut", "setTimeOut",
                     "time_in:", "time_out:", "d.time_in", "d.time_out"):
            self.assertNotIn(gone, code,
                             f"{gone} survived the deletion in daily_jobsite.jsx")

    def test_the_report_prints_them_only_when_set(self):
        self.assertIn("_pg2_times", _REPORT)
        block = _REPORT[_REPORT.index("_pg2_bits = []"):]
        block = block[:800]
        self.assertIn("if _t_in or _t_out:", block)
        self.assertIn("if _areas:", block)
        self.assertIn('_pg2_times = ("<br />" + "<br />".join(_pg2_bits)) if _pg2_bits else ""', block)

    def test_the_areas_visited_payload_key_is_untouched(self):
        """Display only, for the one key that still travels. The day a control
        is added the row reappears on its own with no renderer change."""
        screen = (_BACKEND / ".." / "frontend" / "app" / "logbooks"
                  / "daily_jobsite.jsx").resolve().read_text(encoding="utf-8")
        self.assertIn("areas_visited: areasVisited", screen)

    def test_BOTH_renderers_print_the_times_only_when_set(self):
        """THE PAIR, ASKED THE SAME QUESTION.

        generate_single_logbook_html printed `Time In: N/A   Time Out: N/A`
        UNCONDITIONALLY on every daily jobsite log ever rendered, while the
        combined report already suppressed the row. With nothing left in the
        app that writes those keys, the single document would have carried a
        permanent N/A forever.

        SUPPRESSED, NOT DELETED, and the reason is the same one that governs
        every other decision on a filed record: a log filed before the U1
        rebuild may carry real times, and removing the row outright would
        change what an already-signed document shows. So both renderers now
        apply one rule — print it when a value is there, print nothing when it
        is not — which is what TheTwoRenderersAgreeOnAnEmptyRow below is about.
        """
        self.assertIn("_t_in = str(data.get(\"time_in\") or \"\").strip()", _SINGLE)
        self.assertIn("if (_t_in or _t_out) else \"\"", _SINGLE)
        self.assertNotIn('data.get("time_in") or "N/A"', _SINGLE)
        self.assertNotIn('data.get("time_out") or "N/A"', _SINGLE)

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


class TheTwoRenderersAgreeOnAnEmptyRow(unittest.TestCase):
    """THE DIVERGENCE, closed. generate_single_logbook_html dropped a seed row;
    generate_combined_report printed it. Same stored register, two documents,
    and the combined one is what the operator emails.

    This pair has drifted TWICE before — weather, then drawings_on_site — so
    the fix is not a matching copy of the rule but the SAME rule: both now
    resolve through _SUBMIT_ROW_CONTENT_RULES, which #125 already enforces at
    submit."""

    def test_the_combined_report_skips_the_seed(self):
        self.assertIn('_SUBMIT_ROW_CONTENT_RULES["osha_log"][1]', _REPORT)
        self.assertIn("_row_has(e, _k) for _k in _osha_content_fields", _REPORT)

    def test_it_does_not_write_a_THIRD_copy_of_the_rule(self):
        """A hand-typed field list here is how it drifts a third time."""
        # ONLY THE GUARD, not the row builder below it — that legitimately
        # names these fields in order to PRINT them.
        # The end anchor moved when the Review decision was extracted into
        # osha_review_cell: the guard is now followed by the call, not by the
        # inline `wid = ...` that used to open the branch. The CLAIM is
        # unchanged -- this region must reference the shared rule, never retype
        # its field list.
        guard = _REPORT[_REPORT.index("_osha_content_fields ="):]
        guard = guard[:guard.index("review_cell = osha_review_cell(")]
        for f in ("worker_name", "certification_type", "card_number", "expiration"):
            self.assertNotIn(f'"{f}"', guard,
                             "the field list is re-typed instead of referenced")
        # And the rule it references is the one #125 enforces at submit.
        self.assertIn("worker_name", str(server._SUBMIT_ROW_CONTENT_RULES["osha_log"][1]))

    def test_both_renderers_now_drop_the_same_row(self):
        """Executed on the real document: a register of one seed row renders no
        certification row at all."""
        seed = {"worker_id": None, "worker_name": "", "company": "",
                "certification_type": "", "card_number": "", "expiration": "",
                "signed": False, "date": "2026-08-14"}
        day = {
            **_DAY_WITH_DUPLICATE,
            "osha": {"_id": "lb_osha", "log_type": "osha_log",
                     "date": "2026-08-12", "data": {"entries": [seed]}},
        }
        html = _render_with_osha(day)
        self.assertIn("OSHA / SST Certification Log", html)
        self.assertIn("No certifications recorded", html)

    def test_a_real_row_still_prints(self):
        real = {"worker_id": "w1", "worker_name": "WILMER CARRILLO",
                "company": "AAZ", "certification_type": "SST Supervisor",
                "card_number": "4YU1RY8KKM", "expiration": "2030-04-01",
                "signed": True, "date": "2026-08-12"}
        html = _render_with_osha({**_DAY_WITH_DUPLICATE,
                                  "osha": {"_id": "lb_osha", "log_type": "osha_log",
                                           "date": "2026-08-12",
                                           "data": {"entries": [real]}}})
        self.assertIn("4YU1RY8KKM", html)
        # Reworded by finding 5: the register prints the class name the card
        # prints. No hours here -- this row joins to no live cert, so nothing
        # says colour determined the class.
        self.assertIn("SST Supervisor", html)


class TheAISentenceStillHasItsFallback(unittest.TestCase):
    """DEFECT 2 — the placeholder rendered instead of the generated line. The
    wiring is intact; what was missing was any way to tell WHY."""

    def test_the_wiring_is_still_there(self):
        # RE-POINTED, not dropped. The report now calls the TRACED variant so
        # it can name which of the four outcomes each row took; the sentence
        # half of the contract is unchanged.
        self.assertIn("from lib.ai.sub_summary import generate_sentence_traced", _REPORT)
        self.assertIn("_gen, _outcome = _gen_sub_sentence(_payload)", _REPORT)
        self.assertIn("_line = _sentence_case(_html.escape(_gen)) if _gen else _facts", _REPORT)

    def test_all_three_outcomes_now_leave_a_trace(self):
        """A missing key was the only one of the three that returned None in
        silence, so a report of plain facts was unreadable as evidence."""
        mod = (_BACKEND / "lib" / "ai" / "sub_summary.py").read_text(encoding="utf-8")
        # The one implementation is now generate_sentence_traced; the plain
        # generate_sentence is a thin wrapper over it, so the branches to check
        # are here.
        gen = mod[mod.index("def generate_sentence_traced("):]
        no_key = gen[:gen.index("try:")]
        self.assertIn("logger.warning", no_key)
        self.assertIn("GEMINI_API_KEY is not set", no_key)
        self.assertIn("logger.error", gen)   # the call failed
        self.assertIn("logger.info", gen)    # the sentence was refused


if __name__ == "__main__":
    unittest.main()


class TestAttendeeProvenanceIsPrinted(unittest.TestCase):
    """WHOSE CLAIM PUT EACH MAN ON THE SHEET — device round 4, ruling C.

    A toolbox talk is a WEEKLY obligation built from a DAILY roster, so the CP
    can now add men who worked earlier in the week. That is a genuinely weaker
    claim than a gate check-in: the gate SAW the first man, and the CP is
    ASSERTING the second. Recording the difference in the payload and then
    printing every row identically would defeat the reason for recording it —
    the stronger claim lending its authority to the weaker, on a signed record
    an inspector reads.

    Rendered, not grepped: this calls the real generate_combined_report.
    """

    def _html(self):
        day = {k: dict(v) for k, v in _DAY_WITH_DUPLICATE.items()}
        day["toolbox"] = {
            **day["toolbox"],
            "data": {"checked_topics": {}, "attendees": [
                {"name": "Gate Man", "company": "AAZ", "added_from": "gate"},
                {"name": "Week Man", "company": "AAZ", "added_from": "weekly_gap"},
                {"name": "Typed Man", "company": "AAZ", "added_from": "manual"},
                {"name": "Legacy Man", "company": "AAZ"},   # filed before the field
            ]},
        }
        return _render(day)

    def test_the_column_exists(self):
        self.assertIn("Added by", self._html())

    def test_the_three_claims_render_differently(self):
        html = self._html()
        for label in ("Gate", "CP &mdash; this week", "CP &mdash; added"):
            self.assertIn(label, html, f"{label} is missing from the sheet")

    def test_a_cp_assertion_is_never_printed_as_a_gate_check_in(self):
        """The one substitution that would matter."""
        html = self._html()
        week_row = html[html.index("Week Man"):]
        week_row = week_row[:week_row.index("</tr>")]
        self.assertIn("this week", week_row)
        self.assertNotIn(">Gate<", week_row)

    def test_an_old_record_is_not_given_a_label_it_never_earned(self):
        """Every attendee filed before `added_from` existed came from the gate
        or from the CP's typing with no way to tell which. An em-dash says we
        do not know; anything else is a guess printed onto a legal record."""
        html = self._html()
        legacy = html[html.index("Legacy Man"):]
        legacy = legacy[:legacy.index("</tr>")]
        self.assertNotIn("Gate", legacy)
        self.assertNotIn("CP ", legacy)
        self.assertIn("&mdash;", legacy)

    def test_the_table_is_not_left_one_column_short(self):
        """A header row wider than its empty-state placeholder renders a
        ragged table on the one document nobody re-renders."""
        # NARROWED. This meant "the toolbox placeholder is not left one column
        # short of its header" and was written as a global ban on colspan 6 —
        # which the pre-shift sheet then legitimately needed when it gained a
        # signature column. Asserted on the toolbox table's own placeholder.
        _tb = _REPORT[_REPORT.index('toolbox = _filed_log'):]
        _tb = _tb[:_tb.index('preshift = _filed_log')]
        self.assertIn('colspan="7"', _tb)
        self.assertNotIn('colspan="6"', _tb)


class TestGroupThreeRendering(unittest.TestCase):
    """Device round 4, group 3 — the two halves that live in the renderer."""

    def _html(self, jobsite_data):
        day = {k: dict(v) for k, v in _DAY_WITH_DUPLICATE.items()}
        day["jobsite"] = {**day["jobsite"],
                          "data": {**day["jobsite"]["data"], **jobsite_data}}
        return _render(day)

    # ── 14. AN EMPTY DESCRIPTION IS NOT A BLANK LABEL ────────────────────────
    def test_an_empty_description_says_it_was_not_recorded(self):
        """`data.get("general_description", "N/A")` returns "" for a stored
        empty string — the default only fires when the KEY is absent. So a log
        whose description was never written printed `Description:` with nothing
        after it: a labelled void on a filed 3301-02, which reads as a document
        that lost something rather than one that recorded nothing.

        The description only lands when the CP has been on the review step to
        see it — deliberately, since he is attesting to that sentence — so an
        empty one is a NORMAL state and the document has to be able to say so.
        """
        html = self._html({"general_description": ""})
        i = html.index("Description:")
        self.assertIn("Not recorded", html[i:i + 200])

    def test_BOTH_renderers_stopped_defaulting_to_a_key_that_is_present(self):
        """The single-log PDF and the combined report each print this line, and
        only one of them is reachable from _render. `.get(key, "N/A")` returns
        "" for a stored empty string — the default fires only when the KEY is
        ABSENT, which it never is once the screen has saved once. So the
        fallback that looked like it was there was doing nothing in both.
        """
        for src, label in ((_SINGLE, "single-log PDF"), (_REPORT, "combined report")):
            with self.subTest(renderer=label):
                self.assertNotIn('general_description", "N/A"', src)
                self.assertIn('general_description") or NOT_RECORDED', src)

    def test_a_written_description_is_untouched(self):
        html = self._html({"general_description": "Rebar and formwork on L4"})
        self.assertIn("Rebar and formwork on L4", html)
        i = html.index("Description:")
        self.assertNotIn("Not recorded", html[i:i + 200])

    # ── 13. "OTHER" IS NOT A PASS/FAIL ITEM ──────────────────────────────────
    def test_other_prints_what_was_inspected_not_a_verdict(self):
        """The other eight name a specific thing, so pass and fail say
        something about it. "Other" names nothing — a green "Passed: Other" on
        a DOB document asserts an unnamed inspection was fine, a claim with no
        subject."""
        html = self._html({"checklist_items": {
            "fall_protections": {"result": "pass", "note": ""},
            "other_checklist": {"result": None, "note": "hoist gate latch"},
        }})
        self.assertIn("Also inspected: hoist gate latch", html)
        self.assertIn("Passed: Fall Protections", html)
        # It must not be listed as unwalked either — it WAS inspected.
        self.assertNotIn("Not inspected: Other", html)

    def test_an_empty_other_prints_nothing_at_all(self):
        """Nothing typed is nothing to report — not an unwalked item, because
        "Other" is not an item anybody walks."""
        html = self._html({"checklist_items": {
            "fall_protections": {"result": "pass", "note": ""},
            "other_checklist": {"result": None, "note": ""},
        }})
        self.assertNotIn("Also inspected", html)
        self.assertNotIn("Not inspected: Other", html)

    def test_a_pass_fail_STORED_ON_OTHER_still_renders(self):
        """An already-filed document does not change because the app later
        learned to record something better. A log filed while Other carried a
        verdict keeps printing that verdict."""
        html = self._html({"checklist_items": {
            "other_checklist": {"result": "fail", "note": "gate left open"},
        }})
        self.assertIn("FAILED", html)
        self.assertIn("gate left open", html)

    def test_the_note_is_escaped(self):
        html = self._html({"checklist_items": {
            "other_checklist": {"result": None, "note": "<script>x</script>"},
        }})
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class TestAmendmentSupersedesOnceSigned(unittest.TestCase):
    """DEVICE ROUND 5, FINDING 19 — the report half.

    `amend_logbook` creates the amendment as a SECOND document sharing
    (project_id, log_type, date). The renderer picked each type with
    `next((l for l in logbooks if ...))` over a query with NO sort, so it
    resolved to whatever Mongo returned first — insertion order, i.e. the
    original. Once a log was amended the correction was invisible on the one
    document that goes to investors and lenders.

    THE RULING: the latest SIGNED record. An unsigned amendment is not a
    correction, it is an intention to correct.
    """

    def _day(self, toolbox_docs):
        """The real renderer, same fake db shape as _render — the toolbox slot
        is replaced with whichever documents the case is about."""
        day = {k: dict(v) for k, v in _DAY_WITH_DUPLICATE.items()}
        db = _Db(
            projects=_Coll(one={"_id": "p1", "name": "8 Walworth St",
                                "address": "8 Walworth St",
                                "project_class": "regular"}),
            logbooks=_Coll(docs=[day["preshift"], day["jobsite"], *toolbox_docs]),
            daily_logs=_Coll(one=None),
            checkins=_Coll(docs=[]),
        )
        with patch.object(server, "db", db):
            return asyncio.run(server.generate_combined_report("p1", "2026-08-12"))

    def _tb(self, _id, *, text, locked, status, created):
        return {
            "_id": _id, "log_type": "toolbox_talk", "date": "2026-08-12",
            "is_locked": locked, "status": status,
            "created_at": datetime(2026, 8, 12, created, tzinfo=timezone.utc),
            "data": {"checked_topics": {}, "location": text,
                     "attendees": [{"name": "Gate Man", "added_from": "gate"}]},
        }

    def test_an_UNSIGNED_amendment_does_not_replace_the_signed_original(self):
        """The case that decided the ruling: a CP taps Amend at 4pm and has not
        finished. Nothing has been corrected yet, and the report must not assert
        that it has."""
        original = self._tb("orig", text="ORIGINAL", locked=True, status="submitted", created=9)
        child = self._tb("child", text="AMENDMENT", locked=False, status="draft", created=16)
        html = self._day([original, child])
        self.assertIn("ORIGINAL", html)
        self.assertNotIn("AMENDMENT", html)

    def test_a_SIGNED_amendment_supersedes_and_the_original_never_returns(self):
        original = self._tb("orig", text="ORIGINAL", locked=True, status="submitted", created=9)
        child = self._tb("child", text="AMENDMENT", locked=True, status="submitted", created=16)
        html = self._day([original, child])
        self.assertIn("AMENDMENT", html)
        self.assertNotIn("ORIGINAL", html)

    def test_insertion_order_does_not_decide_it(self):
        """The whole defect in one assertion: the query has no sort, so the
        renderer must not depend on which document comes back first."""
        original = self._tb("orig", text="ORIGINAL", locked=True, status="submitted", created=9)
        child = self._tb("child", text="AMENDMENT", locked=True, status="submitted", created=16)
        self.assertIn("AMENDMENT", self._day([original, child]))
        self.assertIn("AMENDMENT", self._day([child, original]))

    def test_a_day_with_only_an_unfiled_draft_still_renders_it(self):
        """Unchanged behaviour: nothing filed falls back to the first match
        rather than blanking the section."""
        draft = self._tb("d1", text="ONLY DRAFT", locked=False, status="draft", created=9)
        self.assertIn("ONLY DRAFT", self._day([draft]))

    def test_every_call_site_goes_through_the_resolver(self):
        """Ten hand-written picks is how this pair drifted twice. One resolver,
        and no `next(...)` survives to drift again."""
        # ELEVEN, not ten: the compliance line on page 1 now resolves the
        # project's REQUIRED set through the same resolver the sections below
        # print from (device round 6, item 3), so it cannot call a log missing
        # that page 2 goes on to render. That is one more call site and one
        # fewer place to drift.
        # TWELVE: the fall-protection section joined, and it resolves its
        # document through the same one resolver as every other section.
        # THIRTEEN since the superintendent log (BC 3301.13.13) gained its
        # own section. The count is the claim: EVERY section resolves its
        # document through _filed_log, so none can quietly reach past the
        # amendment resolver and render a superseded original.
        self.assertEqual(_REPORT.count("_filed_log(logbooks,"), 13)
        self.assertNotIn('next((l for l in logbooks', _REPORT)


class TestAiOutcomeIsVisibleToTheAdminOnly(unittest.TestCase):
    """WHY THE AI LINE DID WHAT IT DID — device round 5, B4.

    All four outcomes render the same fallback, so from the page alone a
    refusal, a failure, a missing key and "no model was ever asked" are
    indistinguishable. That is correct for a lender and useless for the person
    who has to fix it — and a diagnosis has now been blocked twice on runtime
    logs the operator cannot reach.
    """

    def _html(self, *, diagnostics):
        day = {k: dict(v) for k, v in _DAY_WITH_DUPLICATE.items()}
        db = _Db(
            projects=_Coll(one={"_id": "p1", "name": "8 Walworth St",
                                "address": "8 Walworth St",
                                "project_class": "regular"}),
            logbooks=_Coll(docs=[day["preshift"], day["toolbox"], day["jobsite"]]),
            daily_logs=_Coll(one=None),
            checkins=_Coll(docs=[]),
        )
        with patch.object(server, "db", db):
            return asyncio.run(server.generate_combined_report(
                "p1", "2026-08-12", diagnostics=diagnostics))

    def test_the_sent_report_never_carries_it(self):
        """The copy that reaches investors and lenders. `diagnostics` defaults
        False and the scheduled send never passes it."""
        html = self._html(diagnostics=False)
        self.assertNotIn("ADMIN VIEW ONLY", html)
        self.assertNotIn("skipped: no key", html)

    def test_the_admin_preview_names_which_of_the_four_happened(self):
        html = self._html(diagnostics=True)
        self.assertIn("ADMIN VIEW ONLY", html)
        # No key is set in the test environment, so this is the skipped branch —
        # and naming it is the whole point.
        self.assertIn("skipped: no key", html)
        self.assertIn("AAZ", html)

    def test_it_says_it_is_not_on_the_sent_report(self):
        """A diagnostic an admin mistakes for part of the document is worse
        than none."""
        self.assertIn("NOT ON THE SENT REPORT", self._html(diagnostics=True))

    def test_the_default_is_off(self):
        """Signature-level, so a new caller gets the safe behaviour without
        knowing this exists."""
        import inspect
        sig = inspect.signature(server.generate_combined_report)
        self.assertIs(sig.parameters["diagnostics"].default, False)

    def test_only_the_preview_endpoints_pass_it_and_only_for_an_admin(self):
        self.assertEqual(_SRC.count("diagnostics=current_user.get(\"role\") in (\"admin\", \"owner\")"), 2)
        # The scheduled send must call it with neither the flag nor a role.
        send = _SRC[_SRC.index("report_html = await generate_combined_report("):]
        self.assertNotIn("diagnostics", send[:200])


class TestPageOneReadsLikeSomethingSentToALender(unittest.TestCase):
    """B5 and B6 — page 1 goes to investors and lenders. Page 2 onward is a
    filing and reads correctly as one."""

    def _html(self, activities):
        day = {k: dict(v) for k, v in _DAY_WITH_DUPLICATE.items()}
        day["jobsite"] = {**day["jobsite"],
                          "data": {**day["jobsite"]["data"], "activities": activities}}
        db = _Db(
            projects=_Coll(one={"_id": "p1", "name": "8 Walworth St",
                                "address": "8 Walworth St",
                                "project_class": "regular"}),
            logbooks=_Coll(docs=[day["preshift"], day["toolbox"], day["jobsite"]]),
            daily_logs=_Coll(one=None),
            checkins=_Coll(docs=[]),
        )
        with patch.object(server, "db", db):
            return asyncio.run(server.generate_combined_report("p1", "2026-08-12"))

    def _crew(self, company, trade, work):
        return {"crew_id": company[:2], "company": company, "trade": trade,
                "num_workers": "4", "work_description": work,
                "work_locations": "1 floor", "photos": []}

    # ── B6 ───────────────────────────────────────────────────────────────
    def test_one_subcontractor_with_two_crews_is_disambiguated_by_trade(self):
        """Both rows were correct — Concrete and Formwork — but a repeated name
        with different work under it reads as a duplicate on a document somebody
        is checking for errors."""
        html = self._html([
            self._crew("Vanguard", "Concrete", "pour slab"),
            self._crew("Vanguard", "Formwork", "strip formwork"),
        ])
        self.assertIn("Concrete", html)
        self.assertIn("Formwork", html)

    def test_a_single_crew_is_NOT_labelled_with_its_trade(self):
        """Only where it disambiguates. The page is a summary, not a schedule,
        and a fact nobody asked for on every row is noise."""
        html = self._html([self._crew("AAZ", "Concrete", "pour slab")])
        work = html[html.index("Work today"):html.index('page-break-after:always')]
        self.assertIn("AAZ", work)
        self.assertNotIn("Concrete", work)

    def test_the_company_is_matched_on_the_SAME_normalisation_as_the_roster(self):
        """"AAZ" and "aaz " are one subcontractor, as they are everywhere else
        on this project."""
        html = self._html([
            self._crew("Vanguard", "Concrete", "pour slab"),
            self._crew("vanguard ", "Formwork", "strip formwork"),
        ])
        self.assertIn("Formwork", html)

    def test_a_crew_with_no_trade_is_not_labelled_with_an_empty_dash(self):
        html = self._html([
            self._crew("Vanguard", "", "pour slab"),
            self._crew("Vanguard", "", "strip formwork"),
        ])
        self.assertNotIn("&mdash; </strong>", html)

    # ── B5 ───────────────────────────────────────────────────────────────
    def test_page_one_body_text_is_larger_than_the_filing(self):
        """Typography only, no layout restructure. Page 2's 13px table is the
        filing's size and stays; page 1's body does not."""
        html = self._html([self._crew("AAZ", "Concrete", "pour slab")])
        # Sliced at the PAGE BREAK, not at a character count: page 2 is the
        # filing and its 13px table is correct there. A fixed-length slice ran
        # past the break and failed on page 2's type, which is the assertion
        # being wrong rather than the page.
        # The BODY, not the shell. The dark header band carries a 13px
        # subtitle that is chrome, not body text, and B5 is about what a lender
        # reads under the heading — so the slice starts at the report title.
        page1 = html[html.index('<h2 style='):
                     html.index('page-break-after:always')]
        self.assertIn("font-size:24px", page1)      # the report title
        self.assertIn("font-size:17px", page1)      # section heads
        self.assertIn("font-size:16px", page1)      # body / per-sub lines
        self.assertNotIn("font-size:13px", page1)   # nothing at filing size
        # 14px was the OLD body size on this page. Asserting only that 16px
        # is PRESENT was not enough: the info box is also 16px, so shrinking
        # the per-sub lines back to 14px left the assertion satisfied. A
        # mutation found that, which is the second time this round that
        # "the string appears somewhere" stood in for "the thing is true".
        self.assertNotIn("font-size:14px", page1)

    def test_the_body_lines_carry_a_line_height(self):
        """Size alone is not readability at paragraph width."""
        html = self._html([self._crew("AAZ", "Concrete", "pour slab")])
        self.assertIn("font-size:16px;line-height:1.6", html)
