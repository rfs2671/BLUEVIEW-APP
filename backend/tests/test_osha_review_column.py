"""The OSHA register says what it checked, and what it could not.

THE REVIEW COLUMN PRINTED AN EM DASH FOR A CLEAN ROW. Everywhere else in this
file an em dash means "we do not know" -- `_attendee_source_label` says so in
those words, and fall_protection renders "&mdash; Not recorded". The Review
column used that same glyph for its VERIFIED-CLEAN answer, on a table where the
other four columns use it for genuinely-absent data. One row could print an em
dash five times meaning four different things.

WORSE, IT MEANT TWO THINGS AT ONCE. `review_by_key` indexed FLAGGED certs only,
so a miss had two causes the code could not tell apart: the cert is present and
clean, or THE CERT IS NOT THERE AT ALL.

THE JOIN KEY IS UNSTABLE BY CONSTRUCTION, and that is what these tests are
really for. review_by_key is keyed (worker_id, card_number) where the card
number comes from the LIVE worker document and the lookup's comes from the FILED
snapshot. Correct a stored card number and the flag orphans from its row, and
the row printed CLEAN -- the dangerous direction. The card_number validation
pass rewrites malformed numbers on live worker documents, so it manufactures
this case deliberately.

Indexing EVERY live cert rather than only flagged ones closes it per row: a row
whose card number matches no live cert was not checked, whatever it says.

A PER-WORKER FALLBACK WAS REJECTED and is asserted against below. A man holding
a clean OSHA 30 and a flagged SST must not have his correct OSHA 30 row marked
uncertain because a flag exists somewhere on his record.
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

SRC = (BACKEND / "server.py").read_text(encoding="utf-8")


def _code_only(fn) -> str:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)):
        node.body = node.body[1:]
    return ast.unparse(node)


# THE REAL HELPERS, not a copy. An earlier draft of this file reimplemented the
# branch locally, and the control run exposed it: every state test passed
# against pre-fix code, because the copy under test was IN the test. The rule
# now lives in server.py beside _preshift_signature_cell and these call it.
#
# RESOLVED AT CALL TIME, not at import. Binding at module level made the whole
# file fail COLLECTION against pre-fix code -- one error rather than a count of
# which assertions the change is actually load-bearing for. A control run whose
# output is "1 error" cannot tell you what it proved.
def cell(entry, worker_docs):
    # osha_review_index returns FOUR things since finding 5 added class_by_key;
    # the Review cell takes the first three. Unpacked explicitly rather than
    # splatted, so growing the index again cannot silently pass a fourth
    # positional argument into this function.
    review_by_key, known_cards, known_workers, _class =         server.osha_review_index(worker_docs)
    return server.osha_review_cell(
        entry, review_by_key, known_cards, known_workers)


def state(entry, worker_docs):
    """The cell reduced to which of the three states fired."""
    html = cell(entry, worker_docs)
    if "&#9888;" in html:
        return "FLAGGED"
    if "No findings" in html:
        return "No findings"
    if "Not checked" in html:
        return "Not checked"
    raise AssertionError(f"unrecognised review cell: {html!r}")


WORKER = "64f0aa11bb22cc33dd44ee55"


class TheFlagStillFires(unittest.TestCase):
    def test_a_flagged_cert_prints_its_reason(self):
        out = cell(
            {"worker_id": WORKER, "card_number": "JH447TBBXG"},
            [{"_id": WORKER, "certifications": [
                {"card_number": "JH447TBBXG", "needs_review": True,
                 "review_reason": "CLASS_UNVERIFIED"}]}])
        self.assertIn("Class unverified", out)
        self.assertIn("&#9888;", out)


class AClearRowSaysACheckRan(unittest.TestCase):
    def test_a_matching_clean_cert_prints_no_findings(self):
        self.assertEqual(state(
            {"worker_id": WORKER, "card_number": "JH447TBBXG"},
            [{"_id": WORKER, "certifications": [
                {"card_number": "JH447TBBXG", "needs_review": False}]}]), "No findings")

    def test_no_findings_requires_a_cert_to_actually_exist(self):
        """The assertion that stops "No findings" becoming the fall-through
        again. It is earned by a matching live cert, never by a miss."""
        self.assertEqual(state(
            {"worker_id": WORKER, "card_number": "JH447TBBXG"},
            [{"_id": WORKER, "certifications": []}]), "Not checked")


class ARowThisJoinCouldNotReach(unittest.TestCase):
    """Four ways to be unreachable. All are one fact: nobody looked."""

    def test_no_card_number_was_never_looked_up(self):
        """`if cn` short-circuits the lookup entirely -- this row was never
        checked, and used to render the same em dash as a clean one."""
        self.assertEqual(
            state({"worker_id": WORKER, "card_number": ""},
                  [{"_id": WORKER, "certifications": [
                      {"card_number": "X", "needs_review": True}]}]),
            "Not checked")

    def test_no_worker_id_cannot_be_joined(self):
        self.assertEqual(
            state({"worker_id": "", "card_number": "JH447TBBXG"}, []),
            "Not checked")

    def test_a_worker_document_the_lookup_did_not_return(self):
        """A deleted worker, or an id that no longer resolves. The register
        still names him; nothing was checked."""
        self.assertEqual(
            state({"worker_id": WORKER, "card_number": "JH447TBBXG"}, []),
            "Not checked")


class TheOrphanedFlag(unittest.TestCase):
    """THE CASE THE card_number VALIDATION PASS WILL MANUFACTURE.

    A malformed card number is corrected on the live worker document. The filed
    register still carries the old string, so the (worker_id, card_number) join
    misses -- and before this change the row printed clean, silently dropping a
    real flag off a compliance document.
    """

    def test_a_card_number_changed_after_filing_does_not_print_clean(self):
        filed = {"worker_id": WORKER, "card_number": "SST 1234-5678"}   # as filed
        live = [{"_id": WORKER, "certifications": [
            {"card_number": "SST12345678", "needs_review": True,        # corrected
             "review_reason": "CLASS_UNVERIFIED"}]}]
        out = state(filed, live)
        self.assertNotEqual(out, "No findings",
                            "a flag orphaned by a corrected card number printed as clean")
        self.assertEqual(out, "Not checked")

    def test_the_same_holds_when_the_orphaned_cert_was_clean(self):
        """Nothing about this depends on the cert being flagged. The row's card
        number matches no live cert, so the row was not checked either way."""
        self.assertEqual(state(
            {"worker_id": WORKER, "card_number": "SST 1234-5678"},
            [{"_id": WORKER, "certifications": [
                {"card_number": "SST12345678", "needs_review": False}]}]), "Not checked")

    def test_correcting_the_register_too_restores_the_flag(self):
        """The other half: once both sides agree, the flag reappears. If this
        ever fails, the fix has made flags unreachable rather than honest."""
        out = cell(
            {"worker_id": WORKER, "card_number": "SST12345678"},
            [{"_id": WORKER, "certifications": [
                {"card_number": "SST12345678", "needs_review": True,
                 "review_reason": "DUPLICATE_SST"}]}])
        self.assertIn("Duplicate SST", out)


class NoPerWorkerFallback(unittest.TestCase):
    """The approach that was considered and rejected, asserted against."""

    LIVE = [{"_id": WORKER, "certifications": [
        {"card_number": "OSHA30-111", "needs_review": False},
        {"card_number": "SST-222", "needs_review": True,
         "review_reason": "CLASS_UNVERIFIED"},
    ]}]

    def test_a_clean_cert_is_clean_even_when_the_worker_has_another_flag(self):
        """A man holding a clean OSHA 30 and a flagged SST must not have his
        correct OSHA 30 row marked uncertain because a flag exists somewhere
        on his record. Matching on the row's own card number has no such
        failure mode; a per-worker fallback does."""
        self.assertEqual(
            state({"worker_id": WORKER, "card_number": "OSHA30-111"}, self.LIVE),
            "No findings")

    def test_and_the_flagged_one_still_flags(self):
        self.assertIn("Class unverified",
                      cell({"worker_id": WORKER, "card_number": "SST-222"}, self.LIVE))


class TheRendererActuallyCallsIt(unittest.TestCase):
    """The tests above exercise the real helper. This class is what proves the
    RENDERER uses it, rather than keeping a private copy that could drift --
    the failure mode the extraction exists to remove."""

    CODE = None
    CELL = None

    @classmethod
    def setUpClass(cls):
        cls.CODE = _code_only(server.generate_combined_report)
        cls.CELL = _code_only(server.osha_review_cell)

    def test_the_report_calls_the_helper(self):
        self.assertIn("review_cell = osha_review_cell(e, review_by_key, "
                      "known_cards, known_workers)", self.CODE)

    def test_the_report_builds_its_indexes_through_the_helper(self):
        self.assertIn("review_by_key, known_cards, known_workers, "
                      "class_by_key = osha_review_index(worker_docs)",
                      self.CODE)

    def test_the_report_keeps_no_copy_of_the_branch(self):
        """If the decision reappears inline, the two can disagree and only one
        of them is tested."""
        self.assertNotIn("REVIEW_LABELS.get(reason", self.CODE)
        self.assertNotIn("known_cards)", self.CODE.split("osha_review_index")[0])

    def test_every_live_cert_is_indexed_not_only_flagged_ones(self):
        idx = _code_only(server.osha_review_index)
        self.assertIn("known_cards.add((wid, cn))", idx)
        self.assertIn("known_workers.add(wid)", idx)
        # the flagged-only skip still exists, but AFTER the card is recorded
        self.assertLess(idx.index("known_cards.add"), idx.index("needs_review"))

    def test_the_clean_branch_requires_a_matching_live_cert(self):
        self.assertIn("if wid and cn and (wid in known_workers) and "
                      "((wid, cn) in known_cards):", self.CELL)

    def test_the_review_cell_never_falls_through_to_an_em_dash(self):
        """Every other dash in that table means a field was left empty. This
        column's fall-through means a check did not run -- a different fact,
        and the one a reader must not mistake for a clean result."""
        self.assertNotIn("&mdash;", self.CELL)

    def test_the_three_states_are_the_three_this_file_exercises(self):
        for state_text in ("No findings", "Not checked", "&#9888;"):
            self.assertIn(state_text, self.CELL)

    def test_the_other_columns_keep_their_dashes(self):
        """The convention is unchanged where it is correct: an absent card
        number, cert type or expiry is still an em dash."""
        # Cert Type moved to _osha_type_cell when finding 5 gave it the class
        # label. It keeps the SAME convention, at the CALL SITE rather than
        # inside the helper: the two renderers differ on what an empty cell
        # prints, so the helper must not choose for them.
        for col in ('e.get("card_number", "") or "&mdash;"',
                    'e.get("expiration", "") or "&mdash;"',
                    '_osha_type_cell(e, class_by_key) or "&mdash;"'):
            self.assertIn(col, SRC)


class TheRegisterSaysWhatTheSignatureClaims(unittest.TestCase):
    def test_the_attestation_exists(self):
        self.assertTrue(hasattr(server, "OSHA_LOG_ATTESTATION"))

    def test_it_refuses_the_claim_a_reader_would_assume(self):
        """The load-bearing clause. Nothing in the flow inspects a physical
        card, so a signed certification register must not imply one was."""
        t = server.OSHA_LOG_ATTESTATION.lower()
        self.assertIn("does not attest that the physical cards were inspected", t)

    def test_it_says_the_provenance_is_not_recorded(self):
        """ENTRY_KEYS carries no provenance field, so a gate-captured cert and
        a CP-typed one are byte-identical on the filed register. toolbox_talk
        solves this with added_from; this register cannot, so it says so."""
        t = server.OSHA_LOG_ATTESTATION
        self.assertIn("does not distinguish which", t)

    def test_it_corrects_the_signed_column(self):
        """The toggle's own copy is "Signature on file" -- the CP's mark that a
        signature exists elsewhere. The printed header says "Signed" over a
        tick, which reads as an attestation the row does not carry."""
        t = server.OSHA_LOG_ATTESTATION
        self.assertIn("on file elsewhere", t)
        self.assertIn("not a signature given here", t)

    def test_it_claims_no_authority(self):
        """This register's citation is not settled either, and the sentence
        must not supply one the code cannot produce."""
        self.assertIsNone(
            re.search(r"§|\b1926\b|\b3301\b|\bDOB\b|OSHA requires",
                      server.OSHA_LOG_ATTESTATION))

    def test_both_renderers_print_it(self):
        self.assertEqual(SRC.count("+ OSHA_LOG_ATTESTATION_HTML"), 2)

    def test_the_sentence_is_written_once(self):
        self.assertEqual(SRC.count("This register lists the certifications"), 1)


class PlacementIsStillTheDistinction(unittest.TestCase):
    """SCOPE below the signature, ATTESTATION above it -- both directions."""

    @staticmethod
    def _blocks(marker):
        out = []
        for m in re.finditer(re.escape(marker), SRC):
            start = SRC.rfind("_html = (", 0, m.start())
            if start == -1:
                start = SRC.rfind("body_html = (", 0, m.start())
            end = SRC.find("\n        )", m.end())
            assert start != -1 and end != -1, marker
            out.append(SRC[start:end])
        return out

    def test_the_osha_attestation_is_above_the_signature_in_both_renderers(self):
        blocks = self._blocks("+ OSHA_LOG_ATTESTATION_HTML")
        self.assertEqual(len(blocks), 2)
        for b in blocks:
            anchor = "osha_sig" if "osha_sig" in b else "cp_sig_block"
            self.assertLess(b.index("OSHA_LOG_ATTESTATION_HTML"), b.index(anchor),
                            "a signer must see the claim before making it")

    def test_the_fall_protection_scope_notice_stays_below_its_signature(self):
        blocks = self._blocks("+ FALL_PROTECTION_NOTICE")
        self.assertEqual(len(blocks), 2)
        for b in blocks:
            anchor = "cp_sig_block" if "cp_sig_block" in b else "render_signature_html"
            self.assertGreater(b.index("FALL_PROTECTION_NOTICE"), b.index(anchor))


class NothingElseOnTheRegisterMoved(unittest.TestCase):
    def test_the_row_content_rule_is_still_the_shared_one(self):
        """One definition, three consumers: the submit gate, the per-logbook
        PDF and this report. This pair has drifted twice before."""
        self.assertIn('_SUBMIT_ROW_CONTENT_RULES["osha_log"][1]', SRC)

    def test_the_review_labels_are_unchanged(self):
        for reason in ("CLASS_UNVERIFIED", "EXPIRY_IMPLAUSIBLE", "DUPLICATE_SST"):
            self.assertIn(reason, SRC)

    def test_the_column_headers_are_unchanged(self):
        self.assertIn("<th {TH}>Signed</th>", SRC)
        self.assertIn("<th {TH}>Review</th>", SRC)


if __name__ == "__main__":
    unittest.main()
