"""A FILED COMPLIANCE DOCUMENT CALLED SIGNED MEN UNSIGNED.

`preshift_signin.jsx` persists `signin_id` on every roster row the current gate
produces, and the merge that builds those rows HARDCODES `worker_signature:
None` in two of its three passes — pass 1 with the comment "new system:
frontend uses signin_id", and pass 3 for compliance-alert rows. The app resolves
the image through `GET /api/signatures/{signin_id}`. `_preshift_signature_cell`
only ever read `worker_signature`.

So every man who signed through the gate printed **NO SIGNATURE ON FILE** on a
filed sheet while his signature sat in the card-audit bucket. An inspector
reading that page concludes he did not sign. Three men on one report.

THREE STATES NOW, NOT TWO, AND THE THIRD IS THE POINT:

    image resolved (inline, or fetched via signin_id)  -> the signature
    no signature and NO signin_id                      -> NO SIGNATURE ON FILE
    signin_id present but UNRESOLVED                   -> "on file, image
                                                          unavailable"

The third state exists because a failed lookup is not evidence about a man.
Printing NO SIGNATURE ON FILE there is a finding against a named person drawn
from a query that did not answer — which is the same defect this function's own
docstring already forbids in the affirmation dimension ("that was a finding
against a named man from a field nobody wrote").
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from tests.source_text import code_of  # noqa: E402

_SRC = Path(server.__file__).read_text(encoding="utf-8")
#: comments and docstrings STRIPPED. The bucket assertion below is about
#: what the code reads, and the docstring names the wrong bucket in order
#: to warn about it — asserting over prose matched the warning, not the code.
_CODE = code_of("server.py")
_PNG = "iVBORw0KGgoAAAANSUhEUg"


class TheCellHasThreeStates(unittest.TestCase):
    def test_an_inline_signature_still_renders_the_image(self):
        html = server._preshift_signature_cell({"worker_signature": _PNG})
        self.assertIn("<img", html)
        self.assertIn(_PNG, html)

    def test_a_resolved_signin_id_renders_the_image(self):
        html = server._preshift_signature_cell(
            {"signin_id": "abc", "worker_signature": None}, {"abc": _PNG})
        self.assertIn("<img", html)
        self.assertIn(_PNG, html)
        self.assertNotIn("NO SIGNATURE ON FILE", html)

    def test_no_signature_and_no_signin_id_is_still_the_strong_statement(self):
        """Unchanged, and it must stay unchanged: for a man with nothing
        pointing at a signature, this is the true and useful answer."""
        html = server._preshift_signature_cell({"name": "x"})
        self.assertIn("NO SIGNATURE ON FILE", html)

    def test_an_unresolved_signin_id_does_NOT_say_unsigned(self):
        """THE DEFECT, INVERTED. A signin_id we could not resolve means the
        lookup failed, not that the man failed to sign."""
        html = server._preshift_signature_cell({"signin_id": "abc"}, {})
        self.assertNotIn("NO SIGNATURE ON FILE", html)
        self.assertIn("image unavailable", html)

    def test_an_unresolved_row_still_says_a_signature_exists(self):
        html = server._preshift_signature_cell({"signin_id": "abc"}, None)
        self.assertIn("Signature on file", html)

    def test_a_blank_signin_id_is_not_treated_as_present(self):
        """`signin_id: ""` and `signin_id: None` are absence, not a failed
        lookup — otherwise every legacy row becomes 'unavailable'."""
        for row in ({"signin_id": ""}, {"signin_id": None}, {"signin_id": "  "}):
            self.assertIn("NO SIGNATURE ON FILE",
                          server._preshift_signature_cell(row, {}))

    def test_the_column_still_never_claims_affirmation(self):
        """The rule this function was rewritten for, re-asserted against the
        new state so it cannot be reintroduced through it."""
        for row, res in (({"worker_signature": _PNG}, None),
                         ({"signin_id": "a"}, {"a": _PNG}),
                         ({"signin_id": "a"}, {}),
                         ({}, None)):
            html = server._preshift_signature_cell(row, res)
            self.assertNotIn("NOT AFFIRMED", html)
            self.assertNotIn("Affirmed", html)


class TheResolverIsSafeToCallFromARenderer(unittest.TestCase):
    def test_no_rows_needing_resolution_costs_nothing(self):
        """An all-inline roster must not touch the database at all."""
        out = asyncio.run(
            server._resolve_signin_signatures(
                [{"worker_signature": _PNG}, {"signature": _PNG}]))
        self.assertEqual(out, {})

    def test_an_empty_roster_returns_empty(self):
        for rows in ([], None):
            self.assertEqual(
                asyncio.run(
                    server._resolve_signin_signatures(rows)), {})

    def test_a_row_with_an_inline_signature_is_skipped_even_with_a_signin_id(self):
        out = asyncio.run(
            server._resolve_signin_signatures(
                [{"worker_signature": _PNG, "signin_id": "abc"}]))
        self.assertEqual(out, {})

    def test_it_is_declared_never_to_raise(self):
        body = _SRC[_SRC.index("async def _resolve_signin_signatures("):]
        body = body[:body.index("\ndef _preshift_signature_cell(")]
        self.assertIn("except Exception", body)
        self.assertNotIn("\n        raise", body)

    def test_it_reads_the_card_audit_bucket_not_the_general_one(self):
        """The endpoint says so explicitly; falling through to the general
        bucket would find nothing and read as 'no signature'.

        AGAINST STRIPPED CODE. The first draft asserted over the raw file and
        failed on this function's own docstring, which names the general bucket
        in order to warn against it — the assertion matched the warning instead
        of the code. `code_of` removes comments and docstrings."""
        body = _CODE[_CODE.index("async def _resolve_signin_signatures("):]
        body = body[:body.index("\ndef _preshift_signature_cell(")]
        self.assertIn("CARD_AUDIT_BUCKET_NAME", body)
        self.assertNotIn("R2_BUCKET_NAME", body)

    def test_it_bounds_its_concurrency(self):
        """A sixty-man roster is sixty object reads."""
        body = _SRC[_SRC.index("async def _resolve_signin_signatures("):]
        body = body[:body.index("\ndef _preshift_signature_cell(")]
        self.assertIn("Semaphore(", body)

    def test_it_follows_the_same_chain_as_the_endpoint(self):
        body = _SRC[_SRC.index("async def _resolve_signin_signatures("):]
        body = body[:body.index("\ndef _preshift_signature_cell(")]
        for step in ("db.sign_ins.find(", "db.daily_signatures.find(",
                     "signature_r2_key", "worker_enrollment_id"):
            self.assertIn(step, body)


class BothRenderersResolveTheSameWay(unittest.TestCase):
    """Two renderers print this sheet. A man who reads as signed on one and
    unsigned on the other is worse than one that is wrong on both."""

    def test_both_call_sites_pass_the_resolved_map(self):
        self.assertEqual(
            _SRC.count("_preshift_signature_cell(w, _ps_sigs)"), 2)

    def test_no_call_site_was_left_on_the_old_signature(self):
        self.assertNotIn("_preshift_signature_cell(w)</td>", _SRC)

    def test_both_renderers_resolve_before_their_loop(self):
        self.assertEqual(_SRC.count("await _resolve_signin_signatures("), 2)

    def test_the_resolution_precedes_the_row_loop_in_each(self):
        for anchor in ('_resolve_signin_signatures(workers)',
                       '_resolve_signin_signatures(pd.get("workers", []))'):
            i = _SRC.index(anchor)
            j = _SRC.index("_preshift_signature_cell(w, _ps_sigs)", i)
            self.assertLess(i, j)


if __name__ == "__main__":
    unittest.main(verbosity=2)
