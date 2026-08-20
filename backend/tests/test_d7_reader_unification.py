"""D7 — the reader-side unification: _worker_company and _has_roster.

WHY THESE HELPERS EXIST. One fact — which sub a man works for — is stored under
four names: `company` (project.trade_assignments, worker_project_trades),
`worker_company` (checkins), `sub_name` (worker_enrollments), and `company_name`
(two report paths). They meet in the three-pass merge behind checkins_today, and
the comment above `_norm_key` records the cost: a trailing or doubled space made
the lowercased (name, company) pair miss and emitted THE SAME MAN TWICE on a
production pre-shift sheet. The same comment notes that pair "has now produced
four separate defects on this project".

WHAT IS ASSERTED HERE. That the collapse did not change behaviour. The helper's
shape was chosen for that: every original site was `(a or b or "").strip()` — an
`or` chain first, ONE strip at the end — so the helper tests truthiness in the
caller's order and strips only the winner. The equivalence tests below are
written as a comparison against that original expression, evaluated inline, so
they cannot drift from the thing they claim to preserve.

THE ONE DECLARED CHANGE. Two report grouping keys (server.py ~26629, ~26664) did
NOT strip before. They do now. A grouping key cannot be SPLIT by stripping, only
merged, and merging two groups that differ only by whitespace is precisely the
documented bug class. Asserted explicitly below rather than left implicit.

WHAT IS DELIBERATELY NOT TOUCHED, and asserted so it stays that way:
  * assign_checkin_trade reads the RAW roster array, inactive rows included, on
    purpose — a CP correcting an old check-in must still be able to pick a sub
    since removed. Changing it is a UX decision about what a CP may select and
    belongs with the mandatory-trade gate.
  * The five `s["worker_company"] = s.get("worker_company") or worker.get(...)`
    lines are WRITES, not reads. This pass is reader-side.

Run:  python -m pytest backend/tests/test_d7_reader_unification.py -q
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

import server  # noqa: E402

SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")


class WorkerCompanyEquivalence(unittest.TestCase):
    """_worker_company must equal `(a or b or ...) or ""` then .strip()."""

    CASES = [
        ("Acme",),
        ("  Acme  ",),
        ("",),
        (None,),
        ("   ",),                       # truthy, wins, strips to "" — as before
        (None, "Beta"),
        ("", "Beta"),
        ("   ", "Beta"),                # the subtle one: whitespace WINS
        ("Acme", "Beta"),
        (None, None, "Gamma"),
        (None, None, None),
        (0, "Beta"),                    # falsy non-string
        (False, None, "Gamma"),
    ]

    @staticmethod
    def _original(candidates):
        """The expression every call site used, verbatim in shape."""
        out = ""
        for v in candidates:
            if v:
                out = v
                break
        return str(out or "").strip()

    def test_matches_the_original_expression_on_every_shape(self):
        for cands in self.CASES:
            with self.subTest(cands=cands):
                self.assertEqual(
                    server._worker_company(*cands),
                    self._original(cands),
                    f"_worker_company{cands} diverged from the or-chain it replaced",
                )

    def test_whitespace_only_wins_and_does_not_fall_through(self):
        """THE ONE CASE THAT WOULD HAVE BEEN A SILENT BEHAVIOUR CHANGE.

        Stripping each candidate BEFORE testing it would let "   " fall through
        to the next one. That is arguably better and is NOT this pass's call.
        """
        self.assertEqual(server._worker_company("   ", "Beta"), "")

    def test_returns_empty_string_never_none(self):
        self.assertEqual(server._worker_company(), "")
        self.assertEqual(server._worker_company(None, None), "")


class RosterPresence(unittest.TestCase):

    def test_active_rows_only(self):
        project = {"trade_assignments": [
            {"trade": "Carpenter", "company": "Acme", "status": "inactive"},
        ]}
        self.assertEqual(server._roster_pairs(project), set())
        self.assertFalse(server._has_roster(project))

    def test_a_live_pair_is_present_and_normalised(self):
        project = {"trade_assignments": [
            {"trade": "  CARPENTER ", "company": " Acme Corp "},
        ]}
        pairs = server._roster_pairs(project)
        self.assertTrue(server._has_roster(project))
        # Normalised through _roster_key, so the strict match and checkin.html's
        # rosterKey() cannot disagree about case or SURROUNDING whitespace.
        self.assertEqual(pairs, {("carpenter", "acme corp")})

    def test_roster_key_does_NOT_collapse_internal_whitespace(self):
        """PINNED BECAUSE THE DOCSTRING OVERCLAIMS, and this test was written
        wrong first because of it.

        `_roster_key` says it makes the frontend and backend agree on "case-only
        edits, leading/trailing whitespace, INTERNAL whitespace, and renames".
        It does `.strip().casefold()` and does not touch internal whitespace, so
        "Acme  Corp" and "Acme Corp" remain two different roster keys.

        Meanwhile `_norm_key` — the checkins_today merge key, added because a
        doubled space emitted the same man twice — DOES collapse it:
        `" ".join(str(v or "").split()).casefold()`.

        So one concept has two normalisations that disagree on exactly the input
        that caused the production defect. Pinned as CURRENT BEHAVIOUR, not
        endorsed: changing _roster_key alters what a man at the turnstile is
        matched against, which is gate behaviour and out of scope here.
        """
        self.assertEqual(server._roster_key("Acme  Corp"), "acme  corp")
        self.assertNotEqual(
            server._roster_key("Acme  Corp"), server._roster_key("Acme Corp"))
        # The other normalisation, on the same input, disagrees.
        self.assertEqual(
            " ".join(str("Acme  Corp").split()).casefold(), "acme corp")

    def test_a_row_missing_either_half_is_not_a_pair(self):
        for row in ({"trade": "Carpenter"}, {"company": "Acme"},
                    {"trade": "", "company": "Acme"}, {}):
            with self.subTest(row=row):
                self.assertFalse(server._has_roster({"trade_assignments": [row]}))

    def test_junk_rows_do_not_raise(self):
        project = {"trade_assignments": ["nonsense", None, 7,
                                         {"trade": "T", "company": "C"}]}
        self.assertTrue(server._has_roster(project))

    def test_missing_and_empty_projects(self):
        for p in (None, {}, {"trade_assignments": None}, {"trade_assignments": []}):
            with self.subTest(p=p):
                self.assertFalse(server._has_roster(p))

    def test_empty_roster_is_not_an_error_state(self):
        """The ruling every consumer obeys: an unfilled admin form must never
        stop a man from working. _has_roster False is a fact, not a failure."""
        self.assertIs(server._has_roster({}), False)


class TheCollapseHappened(unittest.TestCase):
    """Structural: the duplicated logic is gone, not merely wrapped."""

    def test_register_and_checkin_uses_the_helper(self):
        self.assertIn("allowed_pairs = _roster_pairs(project)", SRC)

    def test_the_pair_loop_exists_in_exactly_one_place(self):
        # `_roster_key(t), _roster_key(c)` was the canonical normalisation and
        # must now appear only inside _roster_pairs.
        self.assertEqual(
            SRC.count("pairs.add((_roster_key(t), _roster_key(c)))"), 1)
        self.assertNotIn("allowed_pairs.add((_roster_key(t), _roster_key(c)))", SRC)

    def test_the_or_chain_readers_are_gone(self):
        for gone in (
            '(e.get("sub_name") or "").strip()',
            '(a.get("worker_company") or "").strip()',
            '(c.get("worker_company") or (worker.get("company") if worker else "") or "").strip()',
        ):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, SRC)

    def test_every_reader_now_goes_through_the_helper(self):
        # 8 call sites: 2 enrollment, 2 checkin+worker, 1 activity, 2 report,
        # plus the definition itself is excluded by the `(` in the pattern.
        calls = len(re.findall(r"_worker_company\(", SRC)) - 1  # minus the def
        self.assertGreaterEqual(calls, 7, f"only {calls} sites route through it")


class TheBoundariesHold(unittest.TestCase):
    """What this pass deliberately did NOT change."""

    def test_assign_checkin_trade_still_reads_the_raw_array(self):
        """Inactive rows stay selectable there, by design and by its comment."""
        self.assertIn(
            'for row in (project or {}).get("trade_assignments") or []:', SRC)

    def test_assign_checkin_trade_was_not_routed_through_has_roster(self):
        fn = SRC[SRC.index("async def assign_checkin_trade"):]
        fn = fn[:fn.index("\n@api_router")] if "\n@api_router" in fn else fn
        self.assertNotIn("_has_roster(", fn)
        self.assertNotIn("_roster_pairs(", fn)

    def test_the_five_backfill_writes_are_untouched(self):
        """WRITES, not reads. Routing them would add a strip this pass did not
        rule on; they are the next step, not this one."""
        self.assertEqual(
            SRC.count('s["worker_company"] = s.get("worker_company") or worker.get("company")'),
            5)

    def test_no_mandatory_trade_gate_was_folded_in(self):
        """The gate is wanted and is its own PR. Nothing here may start it."""
        for marker in ("TRADE_REQUIRED", "MANDATORY_TRADE", "trade_required"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, SRC)


class TheDeclaredChange(unittest.TestCase):
    """The report grouping keys now strip. Named, not smuggled."""

    def test_grouping_keys_route_through_the_stripping_helper(self):
        self.assertIn(
            '_worker_company(ci.get("worker_company"), ci.get("company"),', SRC)
        self.assertNotIn(
            '(ci.get("worker_company") or ci.get("company") or ci.get("company_name") or "").lower()',
            SRC)

    def test_stripping_a_grouping_key_can_only_merge_never_split(self):
        """The whole justification, as an assertion: two values that differ only
        by surrounding whitespace now land on ONE key."""
        a = server._worker_company("  Acme Corp  ").lower()
        b = server._worker_company("Acme Corp").lower()
        self.assertEqual(a, b)
        self.assertEqual(a, "acme corp")


if __name__ == "__main__":
    unittest.main(verbosity=2)
