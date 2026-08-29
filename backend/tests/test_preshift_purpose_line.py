"""The pre-shift sheet says what the signature claims.

THE ONLY SHEET IN THE TWELVE THAT PRINTS AN ANSWER WITHOUT ITS QUESTION. The
columns read "Injury" and "PPE" -- two bare nouns over Yes/No -- while the
questions actually asked live in preshift_signin.jsx and never reached the
paper:

    "Injury / Incident last time?"   ->  had_injury
    "Inspected PPE today?"           ->  inspected_ppe

So "Injury: No" on a filed sheet supports at least three readings: no injury
exists, none occurred today, none occurred last shift. On a document that goes
to investors, lenders and inspectors, a reader who cannot find the claim
supplies one.

A SURVEY OF ALL TWELVE FILED SHEETS produced the rule these tests defend: a
sheet is self-describing when it prints the QUESTION next to the ANSWER, or
prose under a heading that names it. Nine of twelve pass -- they are checklists
or narratives, and the check is on the page. fall_protection already carries a
purpose line. Two fail: this one, and osha_log (a signature over other people's
credentials with no statement of what it covers; that one lands with finding 4,
in the PR that decides the Review column's wording).

SCOPE vs ATTESTATION. FALL_PROTECTION_NOTICE states what its log is NOT, and
sits BELOW the signature as a footer qualifying a document already read. This
states what the signature CLAIMS, and sits ABOVE it, because a signer must see
the claim before making it. Both placements are asserted below, in both
directions, so neither drifts into the other's position.

THIS IS NOT A TIMING-CLASS CHANGE. The sheet claims "present at the start of
shift", which is what the existing freeze already implements. The citation is
not settled and nothing here pretends otherwise.
"""

import os
import re
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

SRC = (BACKEND / "server.py").read_text(encoding="utf-8")


class TheSentenceNamesTheQuestions(unittest.TestCase):
    def test_the_attestation_exists(self):
        self.assertTrue(hasattr(server, "PRESHIFT_ATTESTATION"),
                        "the pre-shift sheet still states no claim")

    def test_it_names_the_injury_question_including_which_shift(self):
        """The one the app asks is about the LAST shift. Only saying so
        removes the ambiguity the bare column header creates."""
        t = server.PRESHIFT_ATTESTATION.lower()
        self.assertIn("injury", t)
        self.assertIn("last shift", t)

    def test_it_names_the_ppe_question_including_when(self):
        t = server.PRESHIFT_ATTESTATION.lower()
        self.assertIn("ppe", t)
        self.assertIn("today", t)

    def test_it_ties_the_questions_to_the_columns_they_explain(self):
        """A sentence naming two questions and a table heading two columns are
        only one document if the sentence says which is which."""
        t = server.PRESHIFT_ATTESTATION
        self.assertIn("Injury and PPE columns", t)
        self.assertIn("Signature column", t)

    def test_it_says_the_signature_is_the_workers_own(self):
        """The distinction toolbox_talk draws explicitly in its own renderer:
        a CP-marked roster is not a worker attestation. This sheet is the
        other kind, and must say so."""
        self.assertIn("that worker", server.PRESHIFT_ATTESTATION)

    def test_it_says_what_the_cp_signature_attests(self):
        t = server.PRESHIFT_ATTESTATION.lower()
        self.assertIn("attests", t)
        self.assertIn("roster", t)


class ItNamesQuestionsNotAnswers(unittest.TestCase):
    """A document must not assert a compliance fact its own table contradicts.

    An earlier draft read "confirmed they inspected their PPE", which is false
    on any row answered No -- and inspected_ppe is a three-state field whose
    whole point is that No is a legitimate recorded answer.
    """

    def test_it_does_not_claim_the_ppe_was_inspected(self):
        t = server.PRESHIFT_ATTESTATION.lower()
        for claim in ("confirmed they inspected", "confirmed he inspected",
                      "each worker inspected", "all workers inspected"):
            self.assertNotIn(claim, t)

    def test_it_does_not_claim_there_were_no_injuries(self):
        t = server.PRESHIFT_ATTESTATION.lower()
        for claim in ("no injuries", "no injury or incident occurred",
                      "injury-free", "reported no injuries"):
            self.assertNotIn(claim, t)

    def test_it_asks_rather_than_asserts(self):
        """The verb that makes it a record of questions put, not answers had."""
        self.assertIn("was asked", server.PRESHIFT_ATTESTATION)


class ItClaimsNothingTheCodeDoesNotEnforce(unittest.TestCase):
    """WHERE THE TWO ANSWERS ARE ACTUALLY ENFORCED, and it is not the server.

    The first draft of this class asserted `SUBMIT_INCOMPLETE_WORKER_ANSWERS`
    appeared in server.py. It did -- in the comment written three hours earlier
    to explain this very sentence. No such constant exists anywhere in the
    repo. That is the fourth text-search assertion this session to match its
    own prose, and the first to also invent the thing it was searching for.

    The real gate is client-side, which is exactly why the sentence names
    questions rather than answers.
    """

    SCREEN = (BACKEND.parent / "frontend" / "app" / "logbooks"
              / "preshift_signin.jsx").read_text(encoding="utf-8")

    def test_the_two_answers_are_gated_before_submit(self):
        self.assertIn("answeredBoth", self.SCREEN)
        self.assertIn("w.had_injury != null && w.inspected_ppe != null", self.SCREEN)

    def test_the_write_path_never_reads_the_answers(self):
        """create_logbook gates an immediate submit on a CP signature, on
        content, and on trade detail. It does not look at had_injury or
        inspected_ppe at any point, so a sheet filed by any other caller can
        carry nulls."""
        import ast
        import inspect
        import textwrap
        code = ast.unparse(ast.parse(textwrap.dedent(
            inspect.getsource(server.create_logbook))))
        self.assertIn("SUBMIT_MISSING_CP_SIGNATURE", code,
                      "anchor gone - this test is no longer reading the submit gates")
        for answer in ("had_injury", "inspected_ppe"):
            self.assertNotIn(answer, code)

    def test_the_sentence_says_the_answers_appear_rather_than_that_they_exist(self):
        """An unanswered row renders an em-dash, which reads as no answer, and
        the sentence stays true of it. "appear in" survives that row; "were
        given" would be a claim the server does not enforce, printed over a
        table that can show otherwise."""
        t = server.PRESHIFT_ATTESTATION
        self.assertIn("appear in the Injury and PPE columns", t)
        for overclaim in ("were given", "both answered", "every worker answered"):
            self.assertNotIn(overclaim, t.lower())

    def test_it_cites_no_authority(self):
        """THE CITATION IS NOT SETTLED. The registry already records that
        section 3301 does not name this record; the sentence must not quietly
        supply an authority the code cannot produce.

        Every literal here is word-anchored. A first draft wrote the section
        number as a bare `assertNotIn("3301", t)`, which
        test_absence_literals_are_specific caught in CI: a bare substring ban
        is satisfied -- or broken -- by anything that happens to contain it.
        """
        t = server.PRESHIFT_ATTESTATION
        self.assertIsNone(
            re.search(r"§|\b1926\b|\b3301\b|\bDOB\b|OSHA requires", t))

    def test_the_timing_class_is_untouched(self):
        """The content settles what the sheet IS. It does not settle the
        citation, and a freeze is not moved on an inference."""
        self.assertEqual(server.LOGBOOK_TIMING_CLASS["preshift_signin"], "immediate")


class BothRenderersPrintIt(unittest.TestCase):
    def test_the_sentence_is_written_once(self):
        """One constant, so the app cannot say two different things about what
        a worker signed. The rule FALL_PROTECTION_NOTICE is already under."""
        self.assertEqual(SRC.count("Each worker named below was present"), 1)

    def test_both_renderers_emit_it(self):
        self.assertEqual(SRC.count("+ PRESHIFT_ATTESTATION_HTML"), 2)

    def test_it_sits_directly_above_the_cp_line_at_both_sites(self):
        """Adjacency, not just order. The CP line is not unique in either
        renderer -- it appears once per log type -- so the anchor has to be
        the pairing, and the pairing is what makes the claim read as the one
        the name underneath is making."""
        pairs = re.findall(
            r"\+ PRESHIFT_ATTESTATION_HTML\s*\n\s*\+ bold_para\(\"CP\", "
            r"_capitalize_first\((?:logbook|preshift)\.get\(\"cp_name\", \"N/A\"\)\)\)",
            SRC)
        self.assertEqual(len(pairs), 2,
                         "the attestation is not directly above the CP line at both sites")


class PlacementIsTheDistinction(unittest.TestCase):
    """SCOPE goes below the signature; ATTESTATION goes above it. Asserted in
    both directions so neither drifts into the other's position."""

    @staticmethod
    def _blocks(marker):
        """Every renderer composition containing `marker`, as source text."""
        out = []
        for m in re.finditer(re.escape(marker), SRC):
            start = SRC.rfind("_html = (", 0, m.start())
            end = SRC.find("\n        )", m.end())
            self_check = start != -1 and end != -1
            assert self_check, f"could not bound the block around {marker}"
            out.append(SRC[start:end])
        return out

    def test_the_attestation_is_above_the_cp_signature_in_both_renderers(self):
        blocks = self._blocks("+ PRESHIFT_ATTESTATION_HTML")
        self.assertEqual(len(blocks), 2)
        for b in blocks:
            self.assertLess(b.index("PRESHIFT_ATTESTATION_HTML"), b.index("ps_sig"),
                            "a signer must see the claim before making it")

    def test_the_fall_protection_scope_notice_stays_below_its_signature(self):
        """A footer qualifying a document the reader has already read. If this
        ever flips, the two kinds of purpose line have been confused."""
        blocks = self._blocks("+ FALL_PROTECTION_NOTICE")
        self.assertEqual(len(blocks), 2)
        for b in blocks:
            anchor = "cp_sig_block" if "cp_sig_block" in b else "render_signature_html"
            self.assertGreater(b.index("FALL_PROTECTION_NOTICE"), b.index(anchor))


class NothingElseOnTheSheetMoved(unittest.TestCase):
    def test_every_cell_still_reads_the_stored_row(self):
        for cell in ('w.get("name", "")', 'w.get("had_injury")',
                     'w.get("inspected_ppe")', 'w.get("osha_number", "")',
                     'w.get("company", "")'):
            self.assertIn(cell, SRC, f"{cell} no longer comes from the stored row")

    def test_the_affirmation_overlay_still_runs_in_both_renderers(self):
        self.assertEqual(SRC.count("_preshift_signature_cell(w, _affirm)"), 2)

    def test_the_column_headers_are_unchanged(self):
        self.assertEqual(
            SRC.count('<th {TH}>Injury</th><th {TH}>PPE</th><th {TH}>Signature</th>'), 2)


if __name__ == "__main__":
    unittest.main()
