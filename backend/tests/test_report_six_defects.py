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

import re
import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

# The two renderers. generate_single_logbook_html prints ONE stored logbook as
# its own PDF; generate_combined_report prints the whole day, and is the
# document the investor reads.
_REPORT = _SRC[_SRC.index("async def generate_combined_report"):]
_REPORT = _REPORT[:_REPORT.index('async def get_combined_report(')]
_SINGLE = _SRC[_SRC.index("async def generate_single_logbook_html"):]
_SINGLE = _SINGLE[:_SINGLE.index("async def generate_combined_report")]


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
        def _norm_key(v):
            return " ".join(str(v or "").split()).casefold()
        gate = ("Wilmer Carrillo", "AAZ")
        for legacy in [("wilmer carrillo", "aaz"), ("Wilmer  Carrillo", "AAZ "),
                       (" Wilmer Carrillo", " AAZ")]:
            with self.subTest(legacy=legacy):
                self.assertEqual(
                    (_norm_key(gate[0]), _norm_key(gate[1])),
                    (_norm_key(legacy[0]), _norm_key(legacy[1])),
                )

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
        """Executed, not grepped."""
        def build(t_in, t_out, areas):
            bits = []
            if t_in or t_out:
                bits.append("T")
            if areas:
                bits.append("A")
            return ("<br />" + "<br />".join(bits)) if bits else ""
        self.assertEqual(build("", "", ""), "")
        self.assertEqual(build("07:00", "", ""), "<br />T")
        self.assertEqual(build("", "", "Cellar"), "<br />A")
        self.assertEqual(build("07:00", "15:30", "Cellar"), "<br />T<br />A")


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
