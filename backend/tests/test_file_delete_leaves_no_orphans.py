"""DELETING A FILE REMOVES WHAT INDEXING MADE FROM IT.

THE LEAK. `DELETE /projects/{id}/files/{file_id}` deleted the R2 source object
and the `project_files` row and touched nothing else — so every call left one
`document_page_index` row per page and one rendered image per page behind, for
ever. Production carried 44 such rows across 8 files and 74.6 MB of
unreferenced objects when this was written. An accumulation, not an accident.

AND THEY WERE NOT INERT: the plan-query retriever searches that index, so a
WhatsApp answer could name a sheet, offer its image, and tell a superintendent
to open it in the app — where it did not exist.

THE CORRECT SHAPE ALREADY EXISTED ONE FUNCTION AWAY. `hard_delete_project`
deletes index rows by file id and then sweeps the `plans/{project}/` prefix,
with a comment calling the file_id keying a landmine. The file-level delete was
the outlier that did not.

WHAT THIS FILE HOLDS
  1. index rows go, keyed on file_id
  2. every rendered derivative goes, via ONE prefix sweep — so a derivative
     nobody has thought of yet is covered by construction
  3. neither can fail the deletion: the file must stop appearing
  4. the one orphan still possible — bytes whose row is gone — is RECORDED
     with its key, because a reclaimable object and an unknown one differ only
     by whether anything wrote the key down
  5. an audit entry preserves the fact, which is what a soft delete would have
     been for
"""

import os
import sys
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from tests.source_text import code_of  # noqa: E402

SRC = code_of("server.py")
_I = SRC.index("async def delete_project_file(")
_J = SRC.index("async def dropbox_webhook_challenge(")
BODY = SRC[_I:_J]


class EverythingIndexingMadeIsRemoved(unittest.TestCase):
    def test_index_rows_go_keyed_on_file_id(self):
        self.assertIn(
            'db.document_page_index.delete_many({"file_id": str(file_id)})', BODY)

    def test_one_prefix_sweep_covers_every_derivative(self):
        """page_N.jpg, page_N_thumb.jpg and page_N_base.jpg all live under
        `plans/{project}/{file}/`. Deleting them individually would need this
        function to know every derivative the indexer writes — and it would be
        wrong the day a new one is added. The prefix cannot go stale."""
        self.assertIn('f"plans/{project_id}/{file_id}/"', BODY)
        self.assertIn("_r2_delete_prefix(", BODY)

    def test_it_uses_the_same_helper_hard_delete_project_uses(self):
        """One implementation of "delete every object under a prefix", which
        already paginates past the 1000-key ListObjectsV2 cap and never
        raises."""
        self.assertIn("async def _r2_delete_prefix(", SRC)
        i = SRC.index("async def hard_delete_project(")
        self.assertIn("_r2_delete_prefix(", SRC[i:i + 6000])


class HousekeepingCannotFailTheDeletion(unittest.TestCase):
    """The user's instruction was to remove the file. A storage or index
    failure must not leave it on his screen."""

    def test_the_index_removal_is_guarded(self):
        i = BODY.index("db.document_page_index.delete_many")
        window = BODY[max(0, i - 200):i]
        self.assertIn("try:", window)

    def test_the_row_is_still_deleted_after_the_housekeeping(self):
        self.assertLess(BODY.index("db.document_page_index.delete_many"),
                        BODY.index("db.project_files.delete_one"))
        self.assertLess(BODY.index("_r2_delete_prefix("),
                        BODY.index("db.project_files.delete_one"))

    def test_a_failed_index_removal_names_the_file(self):
        """A log line that cannot be tied to a record is the same problem the
        orphans were."""
        i = BODY.index("index rows NOT removed")
        line = BODY[i:i + 260]
        self.assertIn("file_id=", line)
        self.assertIn("project=", line)


class TheOneRemainingOrphanIsRecorded(unittest.TestCase):
    def test_a_surviving_object_is_logged_with_its_key(self):
        """The `project_files` row goes whether or not R2 accepted the delete.
        That trade is deliberate and produces the only orphan left — bytes with
        no row — so the key has to be written down or nothing can reclaim it."""
        self.assertIn("ORPHANED R2 OBJECT", BODY)
        i = BODY.index("ORPHANED R2 OBJECT")
        self.assertIn("key={r2_key}", BODY[i:i + 300])

    def test_it_is_an_error_not_a_warning(self):
        i = BODY.index("ORPHANED R2 OBJECT")
        self.assertIn("logger.error", BODY[max(0, i - 120):i])


class TheFactSurvivesWithoutTheRow(unittest.TestCase):
    """What a soft delete of the index would have been for. The row itself is a
    derived search artefact that a re-index reconstructs; it attests nothing,
    and keeping it would preserve a pointer to bytes this same call destroyed."""

    def test_an_audit_entry_records_the_deletion(self):
        self.assertIn('"project_file_delete"', BODY)

    def test_the_entry_carries_what_went(self):
        i = BODY.index('"project_file_delete"')
        entry = BODY[i:i + 700]
        for field in ('"name"', '"r2_key"', '"index_rows_deleted"',
                      '"page_objects_deleted"'):
            self.assertIn(field, entry)

    def test_the_audit_cannot_block_the_deletion(self):
        i = BODY.index('"project_file_delete"')
        self.assertIn("try:", BODY[max(0, i - 200):i])

    def test_the_counts_are_returned_to_the_caller(self):
        """Silence about the derivatives is how they accumulated."""
        self.assertIn('"index_rows_deleted": idx_deleted', BODY)
        self.assertIn('"page_objects_deleted": pages_deleted', BODY)


class NoOtherDeletePathHasThisShape(unittest.TestCase):
    """Checked so the fix is known to be complete rather than assumed to be."""

    def test_worker_deletion_is_soft(self):
        i = SRC.index("async def delete_worker(")
        self.assertIn('"is_deleted": True', SRC[i:i + 1200])

    def test_project_soft_delete_removes_nothing(self):
        # INLINE SLICES, not a local `body`: the absence auditor can only prove
        # a haystack is source text when it is a slice of a module-level string,
        # and an assertion it cannot classify goes unaudited.
        i = SRC.index("async def delete_project(")
        self.assertNotIn("db.document_page_index.delete_many(", SRC[i:i + 2500])
        self.assertNotIn("_r2_delete_prefix(", SRC[i:i + 2500])

    def test_project_hard_delete_already_does_both(self):
        i = SRC.index("async def hard_delete_project(")
        body = SRC[i:i + 8000]
        self.assertIn("db.document_page_index.delete_many(", body)
        self.assertIn("_r2_delete_prefix(", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
