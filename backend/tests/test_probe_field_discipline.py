"""A HELPER NOBODY IS REQUIRED TO USE GETS SKIPPED WHEN IT MATTERS MOST.

`scripts/probe_helpers.py` exists because FOUR TIMES IN ONE SESSION a probe
asked a collection for a field it does not have, got a confident zero, and the
zero was reported as a finding:

    document_page_index.created_at        the field is `indexed_at`.
                                          "0 pages indexed in 30 days" against
                                          a collection holding 149 rows.
    document_page_index.searchable_text   no such field, anywhere.
    workers.certifications[].osha_data    the payload is on the WORKER doc.
    gate_failures.device_fingerprint      the field is `fingerprint_id`, so
                                          every device read as `?`.

THE FOURTH HAPPENED AFTER THE HELPER WAS WRITTEN, in a script that printed the
collection's keys and then queried different names. That is the whole argument
for this file: `counted`/`require_fields`/`describe` were advisory, and advice
is what a hurried person skips — which is exactly when a wrong field name is
most likely.

`scripts/audit_probe_field_discipline.py` is the enforcement and this file is
its proof. AN AST WALK, NOT A GREP: `counted(rows, f"{prefix}_at")` is the
shape a hurried probe produces and the first f-string defeats a text search.

WHAT THIS FILE ASSERTS, IN THREE PARTS:

  1. THE CHECKER ACTUALLY WORKS. It catches each of the four real incidents
     written as the offending shape, and clears the same code routed through
     the helper. A gate that cannot be shown to fail is not a gate.
  2. THE RULE HOLDS GOING FORWARD. No script outside the measured baseline may
     count on an undeclared field.
  3. THE BASELINE CAN ONLY SHRINK. It is not an allowlist that rots: a file may
     leave it, nothing may join it, and the total may not grow.

STATE THE COUNT. Measured 2026-09-15 over 61 scripts: **17 undeclared counted
fields in 7 files**, listed below. They are NOT swept here — a sweep of seven
unrelated migration and audit scripts inside a card-read PR is how a reviewable
change becomes an unreviewable one. They are repaired on touch, and the shape
of this gate makes that the only direction available.
"""

from __future__ import annotations

import os
import sys
import textwrap
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent

# This file's OWN path setup, not a neighbour's — a gate has gone green in this
# repo on an unrelated module's sys.path insert.
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))

from audit_probe_field_discipline import (                       # noqa: E402
    audit_source, declared_fields, field_reads, main,
)

SCRIPTS = _BACKEND / "scripts"

# ── THE MEASURED BASELINE ──────────────────────────────────────────────────
#
# Derived by running the audit, not typed from memory. Every entry is a real
# pre-existing instance of the class; none is a judgement that the instance is
# acceptable. The gate below lets this set SHRINK and never grow.
BASELINE_FILES = {
    "amend_duplicate_crews_dryrun.py",
    "audit_account_roles.py",
    "backfill_activity_id.py",
    "migrate_clear_filing_rep_credentials.py",
    "migrate_project_list_defaults.py",
    "plan_extract_local.py",
    "wa_corpus_harness.py",
}
BASELINE_COUNT = 17


def _audit(code: str, name: str = "probe_x.py"):
    return audit_source(textwrap.dedent(code), name)


def _live_hits():
    hits = []
    for entry in sorted(os.listdir(SCRIPTS)):
        if not entry.endswith(".py"):
            continue
        path = SCRIPTS / entry
        hits.extend(audit_source(path.read_text(encoding="utf-8"), entry))
    return hits


# ══ 1. THE CHECKER CATCHES THE FOUR REAL INCIDENTS ═════════════════════════
class TheFourIncidentsAreCaught(unittest.TestCase):
    """Each written the way it was actually written when it went wrong."""

    def test_the_index_census_that_reported_zero_against_149_rows(self):
        """`created_at` on a collection whose field is `indexed_at`."""
        hits = _audit("""
            rows = list(db.document_page_index.find({}))
            recent = len([r for r in rows if r.get("created_at")])
            print(recent)
        """)
        self.assertEqual([h[2] for h in hits], ["created_at"])

    def test_a_field_that_exists_nowhere(self):
        hits = _audit("""
            rows = list(db.document_page_index.find({}))
            print(sum(1 for r in rows if r.get("searchable_text")))
        """)
        self.assertEqual([h[2] for h in hits], ["searchable_text"])

    def test_a_payload_read_off_the_wrong_document(self):
        """`osha_data` is on the WORKER, not on the certification subdoc."""
        hits = _audit("""
            print(len([c for c in certs if c["osha_data"]]))
        """)
        self.assertEqual([h[2] for h in hits], ["osha_data"])

    def test_the_one_that_happened_after_the_helper_existed(self):
        """`device_fingerprint`; the field is `fingerprint_id`. This script
        PRINTED the collection's keys and then queried different names, which
        is why printing them is not a substitute for declaring them."""
        hits = _audit("""
            print(sorted(rows[0].keys()))
            n = sum(1 for r in rows if r.get("device_fingerprint"))
        """)
        self.assertEqual([h[2] for h in hits], ["device_fingerprint"])

    def test_count_documents_is_a_count_too(self):
        """The server-side spelling of the same mistake."""
        hits = _audit("""
            n = db.gate_failures.count_documents({"kind": rows[0]["device_fingerprint"]})
        """)
        self.assertEqual([h[2] for h in hits], ["device_fingerprint"])


# ══ 2. AND CLEARS THE SAME CODE ROUTED THROUGH THE HELPER ══════════════════
class GoingThroughTheHelperIsWhatClearsIt(unittest.TestCase):
    """THE CALL SITE, not merely the import. A file that imports
    probe_helpers and then counts by hand is the exact failure this gate is
    named for, so importing must not be what clears it."""

    def test_counted_clears_the_field_it_names(self):
        self.assertEqual(_audit("""
            from probe_helpers import counted
            n = counted(rows, "indexed_at")
        """), [])

    def test_require_fields_clears_every_field_it_names(self):
        self.assertEqual(_audit("""
            from probe_helpers import require_fields
            require_fields(rows, "indexed_at", "sheet_number")
            n = len([r for r in rows if r.get("indexed_at")])
            m = len([r for r in rows if r.get("sheet_number")])
        """), [])

    def test_describe_clears_it_too(self):
        self.assertEqual(_audit("""
            from probe_helpers import describe
            print(describe(rows, "indexed_at"))
            print(sum(1 for r in rows if r["indexed_at"]))
        """), [])

    def test_importing_the_helper_without_calling_it_clears_nothing(self):
        """The fourth incident, exactly: the helper was available and was not
        used. An import is not a declaration."""
        hits = _audit("""
            from probe_helpers import counted, require_fields
            n = len([r for r in rows if r.get("device_fingerprint")])
        """)
        self.assertEqual([h[2] for h in hits], ["device_fingerprint"])

    def test_declaring_one_field_does_not_clear_a_different_one(self):
        hits = _audit("""
            from probe_helpers import require_fields
            require_fields(rows, "indexed_at")
            n = len([r for r in rows if r.get("created_at")])
        """)
        self.assertEqual([h[2] for h in hits], ["created_at"])


# ══ 3. AND IT IS NOT A GREP ════════════════════════════════════════════════
class ItIsATreeWalkAndThatIsLoadBearing(unittest.TestCase):
    def test_a_declaration_inside_an_fstring_call_still_registers(self):
        """`counted(rows, f"...")` — the tree sees the CALL even when it
        cannot see the name, which is the half a text search gets wrong in the
        dangerous direction."""
        tree_fields = declared_fields(__import__("ast").parse(textwrap.dedent("""
            counted(rows, "indexed_at")
            counted(rows, f"{prefix}_at")
        """)))
        self.assertEqual(tree_fields, {"indexed_at"})

    def test_a_dynamic_key_is_skipped_rather_than_guessed(self):
        """It cannot know the name, so it cannot know whether the name was
        declared. Silence here is honest; it is not clearance, and the
        docstring says so where the next reader will look."""
        self.assertEqual(_audit("""
            key = "created_at"
            n = len([r for r in rows if r.get(key)])
        """), [])
        from audit_probe_field_discipline import __doc__ as doc
        self.assertIn("cannot know", doc)

    def test_a_read_that_is_not_counted_is_not_flagged(self):
        """Deliberately narrow. Printing, writing and comparing a field are not
        the mistake; a zero that looks like a real zero is."""
        self.assertEqual(_audit("""
            for r in rows:
                print(r.get("created_at"))
                r["created_at"] = None
        """), [])

    def test_id_is_exempt_and_the_exemption_is_narrow(self):
        self.assertEqual(_audit('n = len([r for r in rows if r["_id"]])'), [])
        hits = _audit('n = len([r for r in rows if r["id"]])')
        self.assertEqual([h[2] for h in hits], ["id"])

    def test_a_file_that_will_not_parse_is_reported_not_cleared(self):
        """A syntax error must never read as 'no violations'."""
        hits = audit_source("def (:", "broken.py")
        self.assertEqual([h[2] for h in hits], ["<unparseable>"])

    def test_nested_counts_report_one_mistake_once(self):
        """`sum(len(d["photos"]) ...)` matches at both calls. The census is a
        number someone acts on, so one mistake must not read as two."""
        hits = _audit('n = sum(len(d["photos"]) for d in rows)')
        self.assertEqual(len(hits), 1, hits)

    def test_field_reads_sees_both_spellings(self):
        import ast as _ast
        got = field_reads(_ast.parse('f(a.get("x"), b["y"])'))
        self.assertEqual(got, {"x", "y"})


# ══ 4. THE LIVE TREE: NOTHING NEW, AND THE BASELINE ONLY SHRINKS ═══════════
class TheRuleHoldsOnTheRealScripts(unittest.TestCase):
    """STATE THE COUNT, FIX ON TOUCH. 17 instances in 7 files as measured on
    2026-09-15. This gate does not demand they be swept; it demands that the
    number never goes UP and that no new file joins them."""

    def test_no_script_outside_the_measured_baseline_violates(self):
        offenders = {os.path.basename(h[0]) for h in _live_hits()}
        new = offenders - BASELINE_FILES
        self.assertEqual(new, set(), (
            f"{sorted(new)} now count on a field they never declared. "
            "Route the count through probe_helpers.counted / require_fields / "
            "describe — see scripts/audit_probe_field_discipline.py for why."
        ))

    def test_the_total_never_grows(self):
        n = len(_live_hits())
        self.assertLessEqual(n, BASELINE_COUNT, (
            f"{n} undeclared counted fields, baseline {BASELINE_COUNT}. "
            "A new one was added to a file that already had some, which the "
            "per-file check above cannot see."
        ))

    def test_the_baseline_is_not_stale_in_the_other_direction(self):
        """A BASELINE THAT NOBODY UPDATES WHEN IT SHRINKS IS SLACK NOBODY CAN
        SEE. If the real number has dropped, this fails and asks for the
        constant to come down with it — so the gate cannot quietly accumulate
        room for a future violation."""
        n = len(_live_hits())
        self.assertEqual(n, BASELINE_COUNT, (
            f"the real count is {n}, the recorded baseline is "
            f"{BASELINE_COUNT}. Lower BASELINE_COUNT (and drop any file that "
            "is now clean from BASELINE_FILES) so the gate stays tight."
        ))

    def test_the_helper_module_itself_is_not_flagged(self):
        """It DEFINES the helpers; it does not consume them."""
        path = SCRIPTS / "probe_helpers.py"
        self.assertEqual(
            audit_source(path.read_text(encoding="utf-8"), str(path)), [])

    def test_the_audit_is_runnable_and_its_exit_code_is_the_answer(self):
        """The CI-facing contract: a command with a status, not prose."""
        argv = sys.argv
        sys.argv = ["audit_probe_field_discipline.py"]
        try:
            rc = main()
        finally:
            sys.argv = argv
        # 1 today, because the baseline is not empty. It is 0 the day the last
        # instance is repaired, and this assertion is what says so out loud.
        self.assertIn(rc, (0, 1))
        self.assertEqual(rc, 1 if BASELINE_COUNT else 0)


if __name__ == "__main__":
    unittest.main()
