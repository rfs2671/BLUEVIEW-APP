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

THREE THINGS THIS FILE DEFENDS, in the order they matter:

1. EVERY STATUTORY GATE READS THE RECORD'S OWN DATE, never datetime.now(). The
   competent-person allowance (item 8) sunsets on 2027-01-01 and item 9 becomes
   the live item. A log filed in 2026 must keep rendering item 8 FOREVER; a rule
   change does not reach back and alter what a filed document says. Asserted in
   both directions and asserted to be date-driven rather than clock-driven.

2. EMPTY IS THE NORMAL STATE, AND THERE ARE THREE KINDS OF IT. Items 4-7 are
   empty most days. "The CS considered this and had nothing to report" is an
   ATTESTATION and is the whole value of the document; "nobody filled this in"
   is a gap; "this system does not capture it" is a scope statement. The OSHA
   register printed one glyph five times in a row meaning four different things,
   and this log must not repeat it.

3. ONE BUILDER, BOTH RENDERERS. The OSHA register and the pre-shift sheet each
   drifted between the per-logbook PDF and the combined report -- the same
   stored document printing different things depending which you asked for --
   and each had to be pulled back. This one starts that way.
"""

import ast
import inspect
import os
import re
import sys
import textwrap
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

try:
    from lib.logbook import superintendent_log as SL  # noqa: E402
except ImportError:  # pragma: no cover — control runs report a count, not one error
    SL = None

SRC = (BACKEND / "server.py").read_text(encoding="utf-8")

FULL = {
    "date": "2026-08-30",
    "cp_name": "M Rivera",
    "data": {
        "presence": {"printed_name": "M Rivera", "arrived_at": "06:40",
                     "departed_at": "15:10", "signature": {"data": "x"}},
        "progress": {"summary": "formwork on the 3rd floor continuing"},
        "cs_activities": {"summary": "walked floors 1-4", "locations": ["3rd floor"]},
        "unsafe_conditions": {"none_to_report": True},
        "orders_given": {"none_to_report": True},
        "dob_actions": {"entries": [{"kind": "SWO", "issued_on": "2026-08-12"}]},
        "incidents": {"none_to_report": True},
        "competent_person": {"name": "J Diaz", "signature": {"data": "y"}},
        "daily_inspection": {"inspected_on": "2026-08-30", "location": "3rd floor",
                             "result": "satisfactory"},
    },
}


def _numbers(html):
    return [int(m.group(1)) for m in re.finditer(r"<strong>(\d+)\.", html)]


class TheElevenItems(unittest.TestCase):
    def test_all_eleven_are_declared(self):
        self.assertEqual([i["number"] for i in SL.ITEMS], list(range(1, 12)))

    def test_each_carries_the_section_it_answers(self):
        for i in SL.ITEMS:
            self.assertTrue(i.get("citation"), i["key"])

    def test_the_four_attestable_items_are_the_ones_empty_most_days(self):
        self.assertEqual(
            SL.ATTESTABLE_KEYS,
            ("unsafe_conditions", "orders_given", "dob_actions", "incidents"))

    def test_incidents_and_adjoining_property_are_ONE_item(self):
        """Adjoining-property damage is a SUBSET of incidents, not a parallel
        question. Splitting it invites a reader to think an empty
        adjoining-property box means the neighbour was checked."""
        keys = [i["key"] for i in SL.ITEMS]
        self.assertIn("incidents", keys)
        self.assertNotIn("adjoining_property", keys)
        self.assertIn("adjoining", SL.ITEMS_BY_KEY["incidents"]["label"].lower())

    def test_arrival_and_departure_are_on_the_presence_item(self):
        self.assertEqual(
            SL.ITEMS_BY_KEY["presence"]["fields"],
            ["printed_name", "signature", "arrived_at", "departed_at"])


class EveryGateReadsTheRECORDS_OwnDate(unittest.TestCase):
    """The rule stated at the top of the module, asserted."""

    def test_item_8_applies_to_a_log_dated_before_the_sunset(self):
        self.assertTrue(SL.item_applies("competent_person", "2026-12-31"))

    def test_item_8_does_NOT_apply_on_or_after_it(self):
        self.assertFalse(SL.item_applies("competent_person", "2027-01-01"))
        self.assertFalse(SL.item_applies("competent_person", "2030-06-01"))

    def test_item_9_is_the_live_item_from_the_sunset(self):
        self.assertFalse(SL.item_applies("cs_changes", "2026-12-31"))
        self.assertTrue(SL.item_applies("cs_changes", "2027-01-01"))

    def test_a_2026_LOG_KEEPS_ITEM_8_FOREVER(self):
        """A filed document must not change what it says when a rule changes.
        This is the assertion the whole date-driven design exists for."""
        html = server._superintendent_log_html(FULL)
        self.assertIn(8, _numbers(html))
        self.assertNotIn(9, _numbers(html))

    def test_and_a_2027_LOG_SHOWS_ITEM_9_INSTEAD(self):
        html = server._superintendent_log_html(dict(FULL, date="2027-03-01"))
        self.assertIn(9, _numbers(html))
        self.assertNotIn(8, _numbers(html))

    def test_the_gate_never_reads_the_clock(self):
        """A gate on datetime.now() would make historical documents change what
        they say, which on a signed statutory record is the worst failure
        available."""
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(SL.item_applies))))
        for clock in ("now(", "today(", "utcnow", "datetime"):
            self.assertNotIn(clock, code)

    def test_an_unreadable_date_RENDERS_the_item_rather_than_dropping_it(self):
        """Dropping a statutory item because a date could not be parsed would
        remove content from a compliance record on the strength of a parsing
        failure. Wrong direction to fail in."""
        for bad in (None, "", "  "):
            self.assertTrue(SL.item_applies("competent_person", bad))


class ThreeKindsOfEmpty(unittest.TestCase):
    """The OSHA register printed one glyph meaning four things. Not here."""

    def test_an_explicit_nothing_to_report_is_an_ATTESTATION(self):
        self.assertEqual(
            SL.item_state("unsafe_conditions", {"unsafe_conditions": {"none_to_report": True}}),
            SL.ATTESTED_NONE)

    def test_a_blank_is_NOT_REACHED_and_is_a_different_fact(self):
        for blank in ({}, {"unsafe_conditions": {}}, {"unsafe_conditions": None}):
            self.assertEqual(SL.item_state("unsafe_conditions", blank),
                             SL.NOT_REACHED)

    def test_content_is_PRESENT(self):
        self.assertEqual(
            SL.item_state("incidents",
                          {"incidents": {"entries": [{"what": "glass", "where": "N wall"}]}}),
            SL.PRESENT)

    def test_an_uncollected_item_is_NOT_COLLECTED_never_an_attestation(self):
        self.assertEqual(SL.item_state("cs_changes", {}, "2027-06-01"),
                         SL.NOT_COLLECTED)
        self.assertEqual(SL.item_state("weekly_meeting", {}), SL.NOT_COLLECTED)

    def test_a_non_attestable_item_can_never_be_ATTESTED_NONE(self):
        """"None to report" is only meaningful where the CS was asked. Setting
        the flag on an item nobody asks about must not manufacture one."""
        self.assertEqual(
            SL.item_state("progress", {"progress": {"none_to_report": True}}),
            SL.NOT_REACHED)

    def test_the_three_states_render_three_different_ways(self):
        html = server._superintendent_log_html(FULL)
        self.assertIn("None to report", html)          # attested
        self.assertIn("attested by", html)             # ...and BY WHOM
        self.assertIn("does not record", html)         # scope
        blank = server._superintendent_log_html(
            {"date": "2026-08-30", "data": {"presence": {"printed_name": "M R"}}})
        self.assertIn(server.NOT_RECORDED, blank)      # gap

    def test_an_attestation_names_who_made_it(self):
        """An unattributed "none" asserts nothing. The value of "no unsafe
        conditions observed" comes entirely from a named person putting their
        name to it."""
        html = server._superintendent_log_html(FULL)
        i = html.index("None to report")
        self.assertIn("Rivera", html[i:i + 200])


class TheSubmitGateRefusesAnUnattestedItem(unittest.TestCase):
    def test_a_blank_attestable_item_blocks_signature(self):
        self.assertEqual(
            sorted(SL.unanswered_attestable({}, "2026-08-30")),
            sorted(SL.ATTESTABLE_KEYS))

    def test_answering_them_all_clears_it(self):
        self.assertEqual(SL.unanswered_attestable(FULL["data"], FULL["date"]), [])

    def test_content_counts_as_answered(self):
        data = dict(FULL["data"])
        data["incidents"] = {"entries": [{"what": "x", "where": "y"}]}
        self.assertEqual(SL.unanswered_attestable(data, FULL["date"]), [])

    def test_the_gate_is_wired_into_the_submit_path(self):
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.create_logbook))))
        self.assertIn("superintendent_unanswered", code)
        self.assertIn("SUBMIT_UNATTESTED_ITEMS", code)

    def test_the_refusal_names_the_items_and_is_a_machine_code(self):
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.create_logbook))))
        self.assertIn("'items': _unanswered", code)

    def test_garbage_data_blocks_rather_than_passing(self):
        """A non-dict is not an exception -- every item is simply NOT_REACHED,
        so the gate blocks. That is the right direction: nothing was attested."""
        self.assertEqual(
            sorted(server.superintendent_unanswered("not a dict", "2026-08-30")),
            sorted(SL.ATTESTABLE_KEYS))

    def test_a_BROKEN_check_does_not_strand_a_CS_with_an_unsignable_log(self):
        """Neither open nor closed. If the check itself RAISES, blocking would
        strand a superintendent on site with a log he cannot sign, and passing
        would let an unattested item through -- so it returns [] and the
        RENDERER still states each item's real state, leaving an unattested
        item visible on the document rather than reading as "none"."""
        from unittest.mock import patch
        with patch.object(server, "unanswered_attestable",
                          side_effect=RuntimeError("boom")):
            self.assertEqual(server.superintendent_unanswered({}, "2026-08-30"), [])

    def test_and_the_document_still_shows_the_gap_in_that_case(self):
        """The half of the argument above that is easy to assert and easy to
        forget: an item nobody answered prints as Not recorded regardless of
        what the submit gate did."""
        html = server._superintendent_log_html(
            {"date": "2026-08-30", "data": {"presence": {"printed_name": "M R"}}})
        self.assertIn(server.NOT_RECORDED, html)


class TheThirdTimingClass(unittest.TestCase):
    def test_it_is_its_own_class_not_a_rename_of_the_other_two(self):
        self.assertEqual(
            server.logbook_timing_class("site_superintendent_log"), "visit")

    def test_it_is_NOT_swept_by_the_overnight_end_of_day_sweep(self):
        """A visit log is frozen when its author signs on departure. An
        overnight sweep would freeze one he had not finished."""
        self.assertNotIn("site_superintendent_log", server.END_OF_DAY_LOG_TYPES)
        self.assertIn("site_superintendent_log", server.VISIT_LOG_TYPES)

    def test_nor_does_it_freeze_the_instant_a_signature_lands(self):
        self.assertFalse(server.is_immediate_preshift("site_superintendent_log"))

    def test_a_major_building_deadline_is_end_of_day(self):
        for cls in ("major_a", "major_b"):
            self.assertEqual(
                server.superintendent_log_deadline({"project_class": cls}),
                "end_of_day")

    def test_an_ordinary_building_deadline_is_departure(self):
        self.assertEqual(
            server.superintendent_log_deadline({"project_class": "regular"}),
            "departure")

    def test_AN_UNASSESSED_PROJECT_FAILS_CLOSED(self):
        """classify_project returns None when nothing was measured, precisely so
        NEVER ASSESSED and MEASURED-AND-FOUND-NON-MAJOR stay different answers.
        get_required_logbooks already fails closed on that None; this follows
        it. End of day is the STRICTER deadline and signing early is never a
        violation."""
        for unassessed in ({}, {"project_class": ""}, {"project_class": None},
                           {"project_class": "junk"}, None):
            self.assertEqual(server.superintendent_log_deadline(unassessed),
                             "end_of_day")

    def test_the_client_is_told_the_real_class(self):
        """This reported "end_of_day" for anything not immediate, which would
        tell the client a visit log is swept overnight. It is not."""
        meta = server.logbook_timing_meta("site_superintendent_log")
        self.assertEqual(meta["timing_class"], "visit")
        self.assertFalse(meta["is_batchable"])
        self.assertFalse(meta["freeze_on_sign"])
        self.assertTrue(meta["deadline_is_project_scoped"])

    def test_the_other_types_are_unchanged(self):
        self.assertEqual(server.logbook_timing_class("daily_jobsite"), "end_of_day")
        self.assertEqual(server.logbook_timing_class("preshift_signin"), "immediate")
        self.assertFalse(
            server.logbook_timing_meta("daily_jobsite")["deadline_is_project_scoped"])


class OneBuilderBothRenderers(unittest.TestCase):
    def test_there_is_exactly_one_definition(self):
        self.assertEqual(SRC.count("def _superintendent_log_html"), 1)

    def test_both_renderers_call_it(self):
        for fn in (server.generate_combined_report,
                   server.generate_single_logbook_html):
            code = ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))
            self.assertIn("_superintendent_log_html", code)

    def test_neither_builds_its_own_item_list(self):
        for fn in (server.generate_combined_report,
                   server.generate_single_logbook_html):
            code = ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))
            self.assertNotIn("unsafe_conditions", code)
            self.assertNotIn("cs_applicable_items", code)

    def test_the_attestation_sits_above_the_signature(self):
        html = server._superintendent_log_html(FULL)
        self.assertLess(html.index("superintendent&#39;s own record"),
                        html.index("Superintendent Signature"))


class TheAttestationSaysWhatTheSignatureClaims(unittest.TestCase):
    def test_it_explains_what_none_to_report_means(self):
        t = server.CS_LOG_ATTESTATION
        self.assertIn("none to report", t.lower())
        self.assertIn("not an absence of information", t)

    def test_it_says_the_times_are_HIS_not_observed(self):
        """Prefilled from sign-in and from completion, both editable. A
        prefilled time presented as observed would be the app asserting
        something only he can."""
        t = server.CS_LOG_ATTESTATION
        self.assertIn("prefilled", t)
        self.assertIn("not observed by this system", t)

    def test_it_names_the_section_and_claims_nothing_further(self):
        t = server.CS_LOG_ATTESTATION
        self.assertIn("3301.13.13", t)
        for overclaim in ("complies", "compliant", "satisfies", "esra", "approved"):
            self.assertNotIn(overclaim, t.lower())

    def test_no_em_dash_entity_reaches_the_sentence(self):
        """AbsentKeyIsStatedTest allows only "&mdash; Not recorded"; an em dash
        used as prose punctuation is indistinguishable from a placeholder once
        it is HTML."""
        self.assertNotIn("&mdash;", server.CS_LOG_ATTESTATION)


class TheRegistryEntry(unittest.TestCase):
    def test_the_type_is_registered_with_its_section(self):
        entry = next(e for e in server.LOGBOOK_TYPE_REGISTRY
                     if e["key"] == "site_superintendent_log")
        self.assertIn("3301.13.13", entry["dob_reference"])
        self.assertEqual(entry["frequency"], "daily")

    def test_it_applies_to_every_building_class(self):
        entry = next(e for e in server.LOGBOOK_TYPE_REGISTRY
                     if e["key"] == "site_superintendent_log")
        self.assertEqual(sorted(entry["applicable_classes"]),
                         ["major_a", "major_b", "regular"])


if __name__ == "__main__":
    unittest.main()
