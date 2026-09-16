"""A report we generated is not a drawing set.

852 East 176th, measured 2026-09-16:

  Blueview_Report_3846_Bailey_Ave_2026-03-10.pdf
    source        dropbox_sync
    dropbox_path  /testtest/blueview_report_3846_bailey_ave_2026-03-10.pdf
    2 pages, indexed, no sheet number on either

We write the report. A customer saves it into the Dropbox folder their project
is synced from. The sync copies it into Plans & Files like any other PDF, and
the plan indexer reads our own output back in as if it were drawings — onto a
project for a different building than the report is about, because the folder
mapping, not the filename, decides where a synced file lands.

It then sits in the corpus the concept vocabulary is derived from.

Skipped by NAME, before the download. Nothing in the file's contents would
tell us: it is a construction document, and a good one. What disqualifies it
is that we wrote it.
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402


class WhatCountsAsOurOwnReport(unittest.TestCase):

    def test_the_file_that_prompted_this(self):
        self.assertTrue(server.is_generated_report(
            "Blueview_Report_3846_Bailey_Ave_2026-03-10.pdf"))

    def test_however_the_sync_cased_it(self):
        for name in ("blueview_report_3846_bailey_ave_2026-03-10.pdf",
                     "BLUEVIEW REPORT 588 Thomas.pdf",
                     "Blueview-Report-9-Menahan.pdf",
                     "  Blueview_Report_x.pdf"):
            with self.subTest(name=name):
                self.assertTrue(server.is_generated_report(name))

    def test_a_drawing_set_is_not_one(self):
        for name in ("AR - 3.28.25.pdf", "ST (Construction Set) - 1.12.26 (1).pdf",
                     "MH - 7.2.26.pdf", "588 THOMAS BOYLAND ST SET_UPDATED .pdf",
                     "cross connection - 6.13.25.pdf", "", None):
            with self.subTest(name=name):
                self.assertFalse(server.is_generated_report(name))

    def test_a_customers_own_report_is_not_ours(self):
        # The match is anchored at the start: only a file WE named this way.
        for name in ("Structural Report for Blueview Report review.pdf",
                     "2026 Blueview Report Summary.pdf"):
            with self.subTest(name=name):
                self.assertFalse(server.is_generated_report(name))


class TheIndexerRefusesItBeforeSpendingAnything(unittest.TestCase):

    FILE = {"_id": "f1", "name": "Blueview_Report_3846_Bailey_Ave_2026-03-10.pdf",
            "r2_key": "k", "company_id": "c1"}

    def _index(self, rec):
        writes = []

        class _Coll:
            async def update_one(self, q, u, **kw):
                writes.append((q, u))

        class _Db:
            project_files = _Coll()

        downloaded = []

        def _download(*a, **k):
            downloaded.append(a)
            raise AssertionError("the file was fetched from R2")

        with mock.patch.object(server, "db", _Db()), \
                mock.patch.object(server, "QWEN_API_KEY", "k"), \
                mock.patch.object(server, "_r2_client", mock.MagicMock(
                    get_object=_download, download_file=_download)):
            out = asyncio.run(server._index_pdf_file("p1", "c1", dict(rec)))
        return out, writes, downloaded

    def test_it_is_skipped(self):
        out, _w, downloaded = self._index(self.FILE)
        self.assertEqual(out["outcome"], "skipped")
        self.assertEqual(out["reason"], server.GENERATED_REPORT_SKIPPED)
        self.assertEqual(downloaded, [], "it was downloaded before being refused")

    def test_the_file_row_says_why(self):
        _out, writes, _d = self._index(self.FILE)
        self.assertTrue(writes, "nothing was recorded on the file")
        state = writes[0][1]["$set"]["index_status"]
        self.assertEqual(state["state"], server.GENERATED_REPORT_SKIPPED)
        self.assertIn("not a drawing set", state["reason"])

    def test_the_skip_is_visible_to_a_reader(self):
        # _public_index_status is what dropbox-files and document-index-status
        # both hand to the app; a skip nobody can see is a file that looks
        # un-indexed for no stated reason.
        public = server._public_index_status({
            "state": server.GENERATED_REPORT_SKIPPED,
            "reason": "a Blueview report, not a drawing set",
            "at": None})
        self.assertEqual(public["state"], server.GENERATED_REPORT_SKIPPED)
        self.assertIn("not a drawing set", public["reason"])

    def test_the_queue_records_it_as_skipped_not_done(self):
        import inspect
        src = inspect.getsource(server._run_plan_index_job)
        self.assertIn('outcome if outcome in ("done", "skipped", "failed")', src)


class ADrawingSetIsStillIndexed(unittest.TestCase):

    def test_the_gate_lets_it_through(self):
        # It must fail for a REASON PAST the name check — proving the gate did
        # not swallow it. No R2 client here, which is the next refusal.
        with mock.patch.object(server, "QWEN_API_KEY", "k"), \
                mock.patch.object(server, "_r2_client", None):
            out = asyncio.run(server._index_pdf_file(
                "p1", "c1", {"_id": "f2", "name": "AR - 3.28.25.pdf", "r2_key": "k"}))
        self.assertNotEqual(out.get("reason"), server.GENERATED_REPORT_SKIPPED)


if __name__ == "__main__":
    unittest.main()
