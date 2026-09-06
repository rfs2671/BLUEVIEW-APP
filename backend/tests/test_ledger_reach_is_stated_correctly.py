"""WHICH SIGNATURES GET A LEDGER ROW, ASSERTED INSTEAD OF DESCRIBED.

Three comments in `server.py` — `ensure_signature_ledger_row`'s docstring and the
call site inside `finalize_logbook` — both said:

    draftSync reaches this line for every signed draft it drains: a signed
    draft is always locally finalized (freezeIfImmediate -> markFinalized for
    the ten immediate types, AN EXPLICIT markFinalized IN THE TWO END-OF-DAY
    EDITORS)

The clause in capitals is the opposite of the truth, and
`test_end_of_day_sweep.py` asserts its ABSENCE by name: it greps the sign
handlers of `daily_jobsite` and `ssc_daily_safety_log` and requires that
`markFinalized(_key)` and `logbooksAPI.finalize(` do NOT appear. The freeze for
those two types is the overnight sweep's job, deliberately.

── THE CLAIM WAS LOAD-BEARING, WHICH IS WHY THIS FILE EXISTS ───────────────

`ensure_signature_ledger_row` is the thing that closes the audit-trail gap for
a signature the client never reported. Its docstring justified its own reach on
that false sentence. In fact, for an END_OF_DAY log signed OFFLINE:

    draft drains with finalized:false -> applyRemoteFreeze skips
    -> /finalize is never called -> this function is never reached
    -> the sweep freezes it hours later with a bare update_one,
       and does not call it either

so that signature gets no ledger row from either actor. The gap survived inside
the explanation of the function written to close it.

── WHAT THIS FILE DOES AND DOES NOT DO ────────────────────────────────────

It asserts the CORRECTED claim and the facts it rests on. A THIRD instance
turned up while writing it -- `sweep_signature_ledger_gaps` told its own reader
the gap "should now be close to empty", which is the same false sentence
setting a DETECTOR'S expectations. A detector nobody investigates when it is
not empty is the worse of the three. It does NOT wire
the sweep to the ledger — that is a change to what the nightly pass writes on a
filed record and it wants its own decision. The gap is recorded in the
docstring and here, not closed.

This is §8: prose asserting a relationship, sitting where the next reader will
trust it, with nothing that fails when the relationship stops holding. The
relationship never held. Now something fails.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
_FRONTEND = _BACKEND.parent / "frontend"

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

#: The two END_OF_DAY editors. Named here rather than derived, because the
#: point of the test is that their behaviour differs from the other ten.
_END_OF_DAY_EDITORS = ("daily_jobsite.jsx", "ssc_daily_safety_log.jsx")


def _docstring_of(name: str) -> str:
    i = _SRC.index(f"async def {name}(")
    j = _SRC.index('"""', i)
    return _SRC[j + 3:_SRC.index('"""', j + 3)]


class TheFalseSentenceIsGone(unittest.TestCase):
    """Anchored on the CLAUSE that was wrong, not on a whole paragraph that
    could be reworded around it."""

    def test_neither_comment_claims_the_end_of_day_editors_mark_finalized(self):
        for bad in ("an explicit markFinalized in the two",
                    "explicit markFinalized in the two end-of-day"):
            self.assertNotIn(bad, _SRC, f"the false clause survives: {bad!r}")

    def test_nor_does_anything_claim_EVERY_signed_draft_reaches_finalize(self):
        """The other half of the sentence. Rewording the first clause while
        keeping this one would leave the guarantee just as wrong."""
        # A CORRECTION MARKER, NOT A FIXED WINDOW. The first draft looked back
        # 400 characters for "used to" and failed on this file's OWN
        # correction, whose disclaimer sits further up than that. A phrase can
        # legitimately appear inside the sentence that retracts it, so the test
        # is "is this occurrence marked as retracted", not "is it near a word".
        markers = ("used to", "was false", 'not "every signed draft"',
                   "opposite of the truth")
        for m in re.finditer(r"every signed draft", _SRC):
            window = _SRC[max(0, m.start() - 1200):m.start() + 300].lower()
            self.assertTrue(
                any(k.lower() in window for k in markers),
                "an uncorrected 'every signed draft' claim remains near "
                f"offset {m.start()}")


class TheCorrectedClaimIsThere(unittest.TestCase):

    def test_the_docstring_names_the_types_that_do_NOT_reach_it(self):
        doc = _docstring_of("ensure_signature_ledger_row")
        self.assertIn("daily_jobsite", doc)
        self.assertIn("ssc_daily_safety_log", doc)

    def test_and_says_the_gap_is_recorded_rather_than_closed(self):
        """A correction that reads like a fix would be worse than the false
        claim: the next person would stop looking."""
        doc = _docstring_of("ensure_signature_ledger_row")
        self.assertIn("NOT FIXED HERE", doc)


class TheTwoFactsItRestsOnAreStillTrue(unittest.TestCase):
    """A corrected comment is a claim like any other. These are the two facts
    that make it true, asserted so the correction cannot rot the way the
    original did."""

    def test_the_end_of_day_editors_really_do_not_mark_finalized_on_sign(self):
        for name in _END_OF_DAY_EDITORS:
            path = _FRONTEND / "app" / "logbooks" / name
            with self.subTest(name):
                self.assertTrue(path.exists(), f"{name} moved")
                src = path.read_text(encoding="utf-8")
                # The sign handler specifically -- markFinalized appears
                # elsewhere in these files (mirroring a server lock on load),
                # and banning it outright would fail on correct code.
                i = src.find("const persistAndPush")
                self.assertGreater(i, 0, "persistAndPush not found")
                j = src.find("const ", i + 10)
                handler = src[i:j if j > i else len(src)]
                self.assertNotIn("markFinalized(_key)", handler)
                self.assertNotIn("logbooksAPI.finalize(", handler)

    def test_the_sweep_freezes_without_writing_a_ledger_row(self):
        """The other actor. If this ever changes, the gap closes and the
        docstring's 'NOT FIXED HERE' becomes the stale claim."""
        i = _SRC.index("async def sweep_stale_end_of_day_logs(")
        j = _SRC.index("\nasync def ", i + 10)
        body = _SRC[i:j]
        self.assertIn("is_locked", body)
        self.assertNotIn("ensure_signature_ledger_row", body)

    def test_finalize_logbook_DOES_write_one(self):
        """The path that is reached, so the corrected claim is not vacuous."""
        i = _SRC.index("async def finalize_logbook(")
        j = _SRC.index("\n@api_router", i)
        self.assertIn("ensure_signature_ledger_row", _SRC[i:j])


if __name__ == "__main__":
    unittest.main(verbosity=2)
