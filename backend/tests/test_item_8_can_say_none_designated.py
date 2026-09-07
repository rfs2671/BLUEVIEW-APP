"""ITEM 8 CAN SAY NOBODY WAS DESIGNATED, AND SAYING SO IS A CLAIM.

Item 8 had exactly two renderings: a name, or "&mdash; Not recorded". There was
no way to record "no competent person was designated -- I was on site myself",
which under BC 3301.13.12 is lawful and on this product's first customer is the
likely answer. So the document could not distinguish

    he did not answer          from        there was nothing to designate

which is the three-kinds-of-empty defect this whole module was built around,
surviving on the ONE collected item that was excluded from it. `attestable` was
False, so `unanswered_attestable` skipped it and both gates let a BC 3301.13.13
log be signed with item 8 blank. The filed 2026-09-04 record is exactly that.

── WHY ITS "NONE" IS NOT THE OTHER FOUR'S ──────────────────────────────────

Items 4 to 7 assert a BARE NEGATIVE. Item 8 cannot, because 3301.13.12 reads:

    The construction superintendent must designate a competent person for each
    job site ... and ensure such competent person is present at the designated
    job site at all times active work occurs WHEN THE CONSTRUCTION
    SUPERINTENDENT IS NOT AT THE SITE.

The absence of a designation is lawful in exactly ONE circumstance. A control
offering a bare "none designated" would file an ADMISSION on one tap, so the
assertion carries the circumstance with it -- in the label he taps, in the line
on the document, and in a new version of the attestation paragraph above his
signature.

── AND IT IS CHECKABLE AGAINST ITEM 1, DELIBERATELY ────────────────────────

Item 1 carries his arrival and departure. If he attests he was present for all
active work and item 1 says 06:45 to 16:30 on a day work ran to 19:00, THE
DOCUMENT CONTRADICTS ITSELF IN FRONT OF THE READER. That is a feature and there
is no gate for it: a client-side check comparing his own two claims would be
the app deciding what happened on a jobsite, which it cannot know. A document
that is internally checkable by a human is worth more than one made consistent
by a rule that hides the disagreement.

── FORWARD-ONLY ────────────────────────────────────────────────────────────

The one filed superintendent log holds `competent_person: {}` and must keep
rendering "&mdash; Not recorded". `item_state` returns NOT_REACHED for an empty
block before and after -- `none_to_report` is absent, not False -- and the
submit gate runs only at create/update, never over a locked record.
"""

from __future__ import annotations

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
from lib.logbook import superintendent_log as SL  # noqa: E402
from lib.logbook.attestations import ATTESTATIONS, HISTORY  # noqa: E402

NONE_LINE = "None designated"
PRESENCE_CLAIM = "present at the job site at all times active work occurred"


def _render(cp_block, **over):
    lb = {
        "date": "2026-09-04",
        "cp_name": "Michael Cespedes",
        "data": {
            "presence": {"printed_name": "Michael Cespedes"},
            "competent_person": cp_block,
        },
    }
    lb["data"].update(over)
    return server._superintendent_log_html(lb)


class TheThirdAnswerExists(unittest.TestCase):

    def test_item_8_is_attestable_now(self):
        self.assertIn("competent_person", SL.ATTESTABLE_KEYS)

    def test_a_tick_resolves_to_attested_none_not_to_a_gap(self):
        self.assertEqual(
            SL.item_state("competent_person",
                          {"competent_person": {"none_to_report": True}},
                          "2026-09-04"),
            SL.ATTESTED_NONE)

    def test_a_name_still_resolves_to_present(self):
        self.assertEqual(
            SL.item_state("competent_person",
                          {"competent_person": {"name": "Wilson Peleaz"}},
                          "2026-09-04"),
            SL.PRESENT)

    def test_and_a_blank_is_still_a_gap(self):
        """The distinction the change exists to create. If a blank had become
        attested_none, the fix would have manufactured the assertion instead of
        enabling it."""
        self.assertEqual(
            SL.item_state("competent_person", {"competent_person": {}},
                          "2026-09-04"),
            SL.NOT_REACHED)


class TheAssertionCarriesItsCondition(unittest.TestCase):
    """A bare "none designated" is an admission: 3301.13.12 makes the absence
    lawful ONLY where he was on site whenever active work occurred."""

    def test_the_document_states_the_presence_claim(self):
        html = _render({"none_to_report": True})
        self.assertIn(NONE_LINE, html)
        self.assertIn(PRESENCE_CLAIM, html)

    def test_it_names_the_man_making_it(self):
        """An unattributed assertion asserts nothing."""
        self.assertIn("Michael Cespedes", _render({"none_to_report": True}))

    def test_it_does_NOT_use_the_generic_none_to_report_wording(self):
        """Four routine negatives and one admission-shaped claim wearing the
        same words is a reader unable to tell which was made."""
        html = _render({"none_to_report": True})
        row = html[html.index("8. Competent person"):]
        row = row[:row.index("</tr>")]
        self.assertNotIn("None to report", row)

    def test_and_the_other_four_KEEP_the_generic_wording(self):
        """The control. A per-item label on every item would be four ways of
        saying the same thing, which is how a reader stops reading them."""
        html = server._superintendent_log_html({
            "date": "2026-09-04", "cp_name": "Michael Cespedes",
            "data": {"presence": {"printed_name": "Michael Cespedes"},
                     "unsafe_conditions": {"none_to_report": True},
                     "orders_given": {"none_to_report": True}}})
        self.assertIn("None to report", html)
        self.assertIn("attested by Michael Cespedes", html)


class TheGateNowDemandsAnAnswer(unittest.TestCase):

    def test_a_blank_item_8_blocks_the_filing(self):
        self.assertIn("competent_person",
                      SL.unanswered_attestable({"competent_person": {}},
                                               "2026-09-04"))

    def test_a_name_satisfies_it(self):
        self.assertNotIn(
            "competent_person",
            SL.unanswered_attestable(
                {"competent_person": {"name": "Wilson Peleaz"}}, "2026-09-04"))

    def test_and_so_does_the_tick(self):
        self.assertNotIn(
            "competent_person",
            SL.unanswered_attestable(
                {"competent_person": {"none_to_report": True}}, "2026-09-04"))

    def test_after_the_sunset_it_stops_being_demanded(self):
        """Item 8 lapses on 2027-01-01 per the DOB Service Notice of
        2025-12-18. A gate that kept demanding it would block every log filed
        from that date over an item that no longer applies."""
        self.assertNotIn(
            "competent_person",
            SL.unanswered_attestable({"competent_person": {}}, "2027-01-02"))


class TheAlreadyFiledRecordIsUNTOUCHED(unittest.TestCase):
    """The 2026-09-04 log holds `competent_person: {}`."""

    def test_it_still_renders_not_recorded(self):
        html = _render({})
        row = html[html.index("8. Competent person"):]
        row = row[:row.index("</tr>")]
        self.assertIn(server.NOT_RECORDED, row)

    def test_and_never_as_an_attestation_nobody_made(self):
        """SCOPED TO ITEM 8's ROW, AND THE FIRST DRAFT WAS NOT.

        It asserted the presence claim was absent from the WHOLE document and
        failed — because the attestation paragraph now explains what item 8's
        tick means, on every superintendent log, whether or not the tick was
        made. That is correct and it is the point of the new version.

        THE PARAGRAPH EXPLAINS WHAT THE CLAIM WOULD MEAN; THE ROW IS WHERE THE
        CLAIM IS MADE. Testing the document as one blob could not tell those
        apart, and the version that mattered — is this record asserting his
        presence? — is the row.
        """
        html = _render({})
        row = html[html.index("8. Competent person"):]
        row = row[:row.index("</tr>")]
        self.assertNotIn(NONE_LINE, row)
        self.assertNotIn(PRESENCE_CLAIM, row)

    def test_the_paragraph_explains_the_tick_even_when_it_was_not_made(self):
        """The other half of that distinction, asserted so the scoping above
        cannot quietly become vacuous. A reader of ANY log filed under this
        version can look up what item 8's "none designated" would have meant."""
        self.assertIn(PRESENCE_CLAIM, _render({}))

    def test_an_absent_flag_is_not_a_false_one(self):
        """`none_to_report` absent and `none_to_report: False` are the same
        state here, and neither is an assertion."""
        for block in ({}, {"none_to_report": False}):
            with self.subTest(block=block):
                self.assertEqual(
                    SL.item_state("competent_person",
                                  {"competent_person": block}, "2026-09-04"),
                    SL.NOT_REACHED)


class TheAttestationParagraphGotANewVersion(unittest.TestCase):
    """EDITING V1 IN PLACE WOULD CHANGE WHAT ALREADY-SIGNED DOCUMENTS SAY THEY
    MEANT. Every signature event stores the version it printed; if the text
    behind that name changed, the record would claim the signer read a sentence
    nobody showed him."""

    KEY = "site_superintendent_log"

    def test_the_current_version_moved(self):
        self.assertEqual(ATTESTATIONS[self.KEY]["version"], "2026-09-06.1")

    def test_it_explains_what_item_8s_tick_means(self):
        text = ATTESTATIONS[self.KEY]["text"]
        self.assertIn("no competent person was designated", text)
        self.assertIn(PRESENCE_CLAIM, text)
        self.assertIn("3301.13.12", text)

    def test_v1_is_still_in_HISTORY_and_still_says_what_it_said(self):
        v1 = HISTORY[f"{self.KEY}/2026-08-31.1"]
        self.assertIn('An item marked &#34;none to report&#34;', v1)
        self.assertNotIn("no competent person was designated", v1)

    def test_v2_is_v1_plus_the_new_sentence_and_nothing_removed(self):
        """The old wording is not merely PRESENT in history — every clause of
        it must still be what a signer of the new version reads, or the two
        versions would describe different documents."""
        v1 = HISTORY[f"{self.KEY}/2026-08-31.1"]
        v2 = HISTORY[f"{self.KEY}/2026-09-06.1"]
        self.assertTrue(v2.startswith(v1))
        self.assertEqual(v2, ATTESTATIONS[self.KEY]["text"])

    def test_both_versions_are_reachable_forever(self):
        for v in ("2026-08-31.1", "2026-09-06.1"):
            with self.subTest(v):
                self.assertIn(f"{self.KEY}/{v}", HISTORY)


class NoGateComparesHisTwoClaims(unittest.TestCase):
    """RECORDED AS A DECISION, NOT LEFT TO BE NOTICED.

    Item 8's tick is checkable against item 1's times on the same page, and if
    they disagree the document contradicts itself in front of the reader. That
    stays. A client- or server-side check comparing his own two claims would be
    the app deciding what happened on a jobsite.
    """

    def test_the_gate_does_not_read_the_presence_times(self):
        import ast
        import inspect
        import textwrap
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(SL.unanswered_attestable))))
        for forbidden in ("arrived_at", "departed_at", "presence"):
            self.assertNotIn(forbidden, code)

    def test_a_contradictory_log_still_files(self):
        """He says he was here throughout AND that he left at 16:30. Both are
        his claims, both are printed, and the reader is the one who notices."""
        self.assertEqual(
            SL.unanswered_attestable({
                "presence": {"arrived_at": "06:45", "departed_at": "16:30"},
                "competent_person": {"none_to_report": True},
                "unsafe_conditions": {"none_to_report": True},
                "orders_given": {"none_to_report": True},
                "dob_actions": {"none_to_report": True},
                "incidents": {"none_to_report": True},
            }, "2026-09-04"),
            [])


class TheSignatureIsSTILLNotCollected(unittest.TestCase):
    """RECORDED, NOT FIXED, per the ruling. BC 3301.13.13 item 8 requires "the
    name of the competent person designated ... ALONG WITH AN ACCOMPANYING
    SIGNATURE OF THE COMPETENT PERSON", plus a reassignment rule this app does
    not model at all. Item 8 now has three reachable states and none of them is
    the complete one the code describes."""

    def test_the_model_still_declares_a_signature_field(self):
        item = SL.ITEMS_BY_KEY["competent_person"]
        self.assertIn("signature", item["fields"])

    def test_and_nothing_on_any_screen_can_produce_one(self):
        """ANCHORED TO THE MOUNT, NOT TO THE WORD.

        `test_absence_literals_are_specific.py` failed this on the bare
        literal, and it was right: a plain "SignaturePad" is satisfied -- or
        BROKEN -- by anything containing it, and this codebase writes
        explanatory comments constantly. A comment in this region saying "no
        SignaturePad here, and here is why" would have failed the test that
        exists to notice a pad being ADDED. `<SignaturePad` is the mount.
        """
        screen = (_BACKEND.parent / "frontend" / "app" / "logbooks"
                  / "site_superintendent_log.jsx").read_text(encoding="utf-8")
        i = screen.index("competentPersonHeading")
        j = screen.index("signHeading", i)
        self.assertNotIn("<SignaturePad", screen[i:j],
                         "if a pad has been mounted here, item 8 can now be "
                         "complete and this file's premise has changed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
