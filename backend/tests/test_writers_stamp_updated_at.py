"""A writer that mutates a synced document without stamping `updated_at`
makes the change marker lie, and nothing anywhere fails.

THE CONTRACT THIS ENFORCES. A gate tablet reconciles its offline cache against
server state using `updated_at` on `project_files`, `logbooks` and `projects`.
For that to work the field has to mean one thing:

    updated_at is the time this document last changed.

A writer that changes content without moving it does not break a test, does not
log an error, and does not fail the sync. It just leaves a tablet holding
content the server no longer has, with no event that will ever correct it. The
sync is a precondition away from shipping; this is what has to be true first.

THE ONE THAT PROVES THE SHAPE. `_purge_finalized_photo_base64` rewrites the
photos of a FILED COMPLIANCE RECORD — swapping full-size base64 for a thumb and
`$unset`-ing the original — in a fire-and-forget background task that runs just
AFTER finalize already bumped `updated_at`. A tablet syncing on that bump gets
the pre-purge document. The post-purge content never moves the marker again, so
the tablet keeps serving full-size photos that do not exist server-side. That is
the whole class: a late, out-of-band write riding behind somebody else's stamp.

WHAT THIS TEST IS. A RATCHET, like `test_reads_without_writers.py` beside it.
It does not claim every allowed write is correct; it claims that a NEW writer
cannot enter these three collections without either stamping the marker or
saying in writing why it must not. Both directions fail:

  * a new unstamped writer fails `test_every_writer_stamps_updated_at`
  * an allowance that stopped being reported fails
    `test_the_allowlist_has_not_gone_stale` — the allowlist shrinking is the
    good outcome and should be recorded rather than drift unnoticed

WHEN THIS FAILS, add the stamp. Reach for the allowlist only when stamping
would be WRONG — meaning the write records that nothing changed — and write the
reason down. An allowance without a reason is how a check like this rots into a
list nobody dares touch.

OPAQUE vs MISSING. The sweep reports a write it cannot read (a comprehension, a
spread, a name assigned twice) as OPAQUE rather than assuming it innocent. An
OPAQUE write that really does stamp is better FIXED into a readable shape than
allowlisted — `update_scaffold_info` was exactly that, and making the stamp
explicit was a smaller change than explaining it here forever.
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

import find_writers_without_updated_at as sweep  # noqa: E402


# ── the allowlist ───────────────────────────────────────────────────────────
#
# Keyed by (file, enclosing function, exact fields written). The key is that
# narrow ON PURPOSE: an allowance covers ONE write, not a function forever. Add
# a field to an allowed `$set` and the entry stops matching, the ratchet speaks
# up, and somebody looks at it again.
#
# EVERY ENTRY MUST STATE WHY STAMPING WOULD BE WRONG. Not why it is
# inconvenient — why it would be incorrect. `test_every_allowance_states_a_reason`
# enforces that a reason exists; only review enforces that it is a real one.

ALLOWLIST = {
    # THE DROPBOX "FILE UNCHANGED" BRANCH. Reached only when the stored
    # `dropbox_content_hash` equals the hash Dropbox just reported — i.e. the
    # file provably did NOT change. The write records "we looked, and it is
    # still the same", which is what `last_synced_at` means and why it is the
    # only field set.
    #
    # Stamping `updated_at` here would make EVERY file in the project look
    # changed on EVERY sync run, and the tablet would re-download the entire
    # file list on every poll — permanently, since the condition that triggers
    # it is the file being unchanged. That is not churn at the margin; it is
    # the sync never converging. The correct marker is already stamped by the
    # new/changed branch a few lines below, which writes the full record
    # including `updated_at`.
    ("server.py", "_sync_project_to_r2", ("last_synced_at",)):
        "unchanged-file branch: content hash matched, so nothing changed. "
        "Stamping would re-emit every file on every poll, forever.",
}


class TheRatchet(unittest.TestCase):
    def setUp(self):
        self.rows = sweep.findings()
        self.keys = {sweep.key_of(r) for r in self.rows}

    def test_every_writer_stamps_updated_at(self):
        offenders = sorted(
            f"{r['file']}:{r['line']} {r['collection']}.{r['method']} "
            f"in {r['function']}() [{r['verdict']}] writes "
            f"{', '.join(r['fields'])}"
            for r in self.rows if sweep.key_of(r) not in ALLOWLIST
        )
        self.assertEqual(offenders, [], (
            f"{len(offenders)} writer(s) mutate a synced collection without a "
            "provable updated_at. A tablet reconciling on that marker will "
            "hold stale content and never be told. Add the stamp; allowlist "
            "only a write that records that NOTHING changed:\n  "
            + "\n  ".join(offenders)
        ))

    def test_the_allowlist_has_not_gone_stale(self):
        gone = sorted(k for k in ALLOWLIST if k not in self.keys)
        self.assertEqual(gone, [], (
            "these allowances are no longer reported — good, if the writer was "
            "removed or now stamps. Record it by deleting the entry. If the "
            "write merely MOVED or gained a field, the allowance has silently "
            "stopped covering it and the new shape needs a fresh look: "
            f"{gone}"
        ))

    def test_every_allowance_states_a_reason(self):
        """An entry with no reason is indistinguishable from an unexamined one."""
        for key, reason in ALLOWLIST.items():
            self.assertTrue(
                isinstance(reason, str) and len(reason.strip()) >= 40,
                f"allowlist entry {key} needs a real reason, got {reason!r}",
            )


class TheSweepStillWorks(unittest.TestCase):
    """A ratchet that has quietly stopped detecting anything passes forever.

    These assert the MECHANISM, not the findings. The failure guarded against
    is the sweep being broken by a refactor — a renamed db handle, a collection
    reached through a variable — after which it reports a clean bill of health
    on a codebase it can no longer see.
    """

    def setUp(self):
        self.sites = sweep.write_sites()

    def test_it_still_sees_the_writes(self):
        """If `_collection_of` breaks, this is the only thing that notices."""
        self.assertGreaterEqual(len(self.sites), 50, (
            "the sweep found almost no writes to project_files/logbooks/"
            "projects. It is far more likely that collection detection broke "
            f"than that the writers vanished. Found: {len(self.sites)}"
        ))
        for coll in sweep.SYNCED_COLLECTIONS:
            self.assertTrue(
                any(s["collection"] == coll for s in self.sites),
                f"no writes seen to {coll} at all — detection is broken",
            )

    def test_it_can_tell_stamped_from_unstamped(self):
        """Both verdicts must actually occur. A pass that calls everything
        STAMPED is as useless as one that calls everything MISSING."""
        verdicts = {s["verdict"] for s in self.sites}
        self.assertIn("STAMPED", verdicts, "nothing reads as stamped")
        stamped = [s for s in self.sites if s["verdict"] == "STAMPED"]
        self.assertGreater(len(stamped), 25, (
            "almost nothing reads as stamped — stamp detection has broken, "
            f"which would make every finding below it noise. Got {len(stamped)}"
        ))

    def test_it_still_finds_the_case_it_was_built_for(self):
        """The Dropbox unchanged branch is the one write we know must be
        reported and must NOT be fixed. It is therefore a perfect canary: if
        detection breaks it disappears, and if somebody 'fixes' it the
        allowlist goes stale. Either way a test fails."""
        hit = [r for r in sweep.findings()
               if sweep.key_of(r) == ("server.py", "_sync_project_to_r2",
                                      ("last_synced_at",))]
        self.assertEqual(len(hit), 1, (
            "the unchanged-file branch is no longer detected as an unstamped "
            f"write. Found: {hit}"
        ))

    def test_a_stamp_under_set_counts(self):
        """The commonest shape in the codebase by far — `{"$set": {...,
        "updated_at": now}}`. If this stopped counting, dozens of correct
        writers would be reported and the list would become unreadable."""
        import ast
        tree = ast.parse(
            'db.logbooks.update_one({"_id": x},'
            ' {"$set": {"a": 1, "updated_at": now}})'
        )
        call = tree.body[0].value
        scope = sweep.Scope(tree, "<test>")
        stamped, opaque, _ = sweep._classify(call.args[1], scope, is_update=True)
        self.assertTrue(stamped)
        self.assertFalse(opaque)

    def test_an_unstamped_set_is_caught(self):
        import ast
        tree = ast.parse(
            'db.logbooks.update_one({"_id": x}, {"$set": {"a": 1}})'
        )
        call = tree.body[0].value
        scope = sweep.Scope(tree, "<test>")
        stamped, opaque, fields = sweep._classify(
            call.args[1], scope, is_update=True)
        self.assertFalse(stamped)
        self.assertFalse(opaque)
        self.assertEqual(fields, ["a"])

    def test_an_unreadable_payload_is_opaque_not_innocent(self):
        """The direction that matters. A write the pass cannot read must never
        come back STAMPED — that is the one error a ratchet cannot have."""
        import ast
        tree = ast.parse(
            'db.logbooks.update_one({"_id": x},'
            ' {"$set": {f"{f}.{k}": v for k, v in patch.items()}})'
        )
        call = tree.body[0].value
        scope = sweep.Scope(tree, "<test>")
        stamped, opaque, _ = sweep._classify(call.args[1], scope, is_update=True)
        self.assertFalse(stamped)
        self.assertTrue(opaque)


if __name__ == "__main__":
    unittest.main()
