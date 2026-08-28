"""A read whose writer does not exist is not allowed to appear unnoticed.

Four instances surfaced in one day — `dropbox_enabled`, `checklist_title`,
`daily_logs.phase` (read by four engines, sent by no client, ever) and
`daily_logs` itself (92 rows, all April test data, called "the
operator-recorded source of truth" by the missing-log detector). Every one was
found by a person noticing an empty screen, weeks or months late, because valid
code that returns nothing does not fail anything.

WHAT THIS TEST IS, AND IS NOT. It is a RATCHET, not a verdict. The sweep cannot
prove a field is dead — a writer may be built in a shape it cannot read
(bulk_write, a comprehension, a variable filter) — so the baseline below is a
list of CANDIDATES, several of which are certainly fine. The property being
enforced is narrow and worth having on its own:

    a new read-without-writer cannot enter the codebase silently

Adding one fails here. Removing one fails here too, and that is deliberate: the
baseline shrinking is the good outcome and should be recorded rather than drift
unnoticed.

WHEN THIS FAILS, do not reach for the baseline first. Ask whether the field is
genuinely written. If it is, and the sweep cannot see the writer, add it with a
one-line note saying which writer and why it is invisible. If it is not, you
have found the next `daily_logs.phase`.
"""

import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import find_reads_without_writers as sweep  # noqa: E402


# Every candidate as of 2026-08-28. Several are certainly writer-invisible
# rather than dead; the list is a ratchet, not an indictment.
BASELINE = {
    ("checkins", "created_by"),
    # THE ONE THIS EXISTS FOR. Accepted by DailyLogCreate, dumped into the
    # insert, filtered on by live_mutation / defcon / peer_cohort / the
    # violation baseline aggregator, and sent by no client that has ever
    # existed. Do not remove this line to make the suite green — removing it
    # means the field is finally written, or the readers are finally gone.
    ("daily_logs", "phase"),
    ("daily_panels", "project_id"),
    ("dob_logs", "complaint_date"),
    ("dob_logs", "expiration_date"),
    ("document_page_index", "file_hash"),
    ("document_page_index", "file_id"),
    ("document_page_index", "index_version"),
    ("document_page_index", "page_number"),
    ("document_page_index", "project_id"),
    ("document_page_index", "sheet_number"),
    ("document_page_index", "sheet_title"),
    ("feature_flags", "flag"),
    ("filing_jobs", "is_deleted"),
    ("filing_jobs", "permit_renewal_id"),
    ("notification_preferences", "project_id"),
    ("notification_preferences", "user_id"),
    ("prediction_validation_ledger", "calendar_date"),
    ("prediction_validation_ledger", "project_id"),
    ("project_files", "is_deleted"),
    ("project_models", "project_id"),
    ("reports", "is_deleted"),
    ("reports", "project_id"),
    ("sequence_graph", "version"),
    ("socrata_ecb_violations_historical", "bin"),
    ("socrata_ecb_violations_historical", "issue_date"),
    ("socrata_permits_historical", "bin"),
    ("socrata_permits_historical", "filing_reason"),
    ("socrata_permits_historical", "issued_date"),
    ("users", "renewal_digest_opt_in"),
    ("users", "renewal_digest_opt_out"),
    ("workers", "created_by"),
    ("workers", "project_id"),
}


class TheRatchet(unittest.TestCase):
    def setUp(self):
        self.rows = sweep.findings()
        self.pairs = {(r["collection"], r["field"]) for r in self.rows}

    def test_no_new_read_without_a_writer(self):
        new = sorted(self.pairs - BASELINE)
        self.assertEqual(new, [], (
            "a query filter reads a field nothing appears to write. Check "
            "whether it is genuinely written before touching the baseline: "
            f"{new}"
        ))

    def test_the_baseline_has_not_silently_shrunk(self):
        gone = sorted(BASELINE - self.pairs)
        self.assertEqual(gone, [], (
            "these are no longer reported — good, if a writer was added or a "
            "dead read was deleted. Record it by removing the line: "
            f"{gone}"
        ))


class TheSweepStillWorks(unittest.TestCase):
    """A ratchet that has quietly stopped detecting anything passes forever.

    These assert the mechanism rather than the findings — the failure this
    guards against is the sweep being broken by a refactor and nobody noticing,
    which is the same shape as everything else in this file.
    """

    def setUp(self):
        self.rows = sweep.findings()

    def test_it_still_finds_the_case_it_was_built_for(self):
        hit = [r for r in self.rows
               if r["collection"] == "daily_logs" and r["field"] == "phase"]
        self.assertEqual(len(hit), 1, "daily_logs.phase is no longer detected")
        self.assertEqual(hit[0]["verdict"], "UNSENT", (
            "phase is ACCEPTED by DailyLogCreate and sent by nobody. A verdict "
            "of UNWRITTEN means the Pydantic leg stopped binding; CLIENT-FED "
            "means the frontend check started matching something unrelated. "
            f"Got: {hit[0]}"
        ))

    def test_it_names_the_readers(self):
        hit = next(r for r in self.rows
                   if (r["collection"], r["field"]) == ("daily_logs", "phase"))
        joined = " ".join(hit["read_at"])
        self.assertIn("live_mutation.py", joined)
        self.assertIn("peer_cohort.py", joined)

    def test_it_does_not_report_fields_that_are_plainly_written(self):
        """The canary. `logbooks.status` and `logbooks.date` are written by
        create_logbook in the same statement style the sweep must understand —
        if these start appearing, the writer detection has broken and every
        finding below them is noise."""
        for field in ("status", "date", "project_id", "log_type"):
            self.assertNotIn(("logbooks", field),
                             {(r["collection"], r["field"]) for r in self.rows})

    def test_a_backfill_counts_as_a_writer_for_the_collections_it_owns(self):
        """socrata_* is read by two engines and written only by
        scripts/socrata_3year_backfill.py. Those rows stay in the baseline
        because the backfill writes them through a shape this pass cannot
        read — not because scripts are excluded. If the exclusion ever comes
        back, far more than three rows appear."""
        socrata = {r["field"] for r in self.rows
                   if r["collection"] == "socrata_permits_historical"}
        self.assertLessEqual(len(socrata), 4, (
            "the socrata candidate list grew — the writers-include-scripts "
            f"rule may have regressed: {sorted(socrata)}"
        ))


if __name__ == "__main__":
    unittest.main()
