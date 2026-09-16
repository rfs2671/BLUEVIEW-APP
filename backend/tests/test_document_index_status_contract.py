"""document-index-status keeps the field names the re-index script reads.

The script and the endpoint are the two halves of one contract and they live in
different languages, so nothing links them. On 2026-09-16 the display broke for
a whole re-index and the first suspicion was the endpoint; it was not, but
there was no test on either side that could have said so.

scripts/tests/test-status-display.ps1 holds the client half, against the same
recorded response this reads. This is the server half: the endpoint keeps
emitting the keys that response carries.
"""

import inspect
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[2]
           / "scripts" / "fixtures" / "document-index-status.json")

# What scripts/get-page-index.ps1 reads off every file entry.
READ_BY_THE_SCRIPT = ("file_id", "file_name", "total_pages", "indexed_pages",
                      "queue_status", "index_status", "queue")


class TheRecordedResponse(unittest.TestCase):

    def setUp(self):
        self.recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_it_is_a_real_run_of_this_project(self):
        for state in ("complete", "mid_run"):
            with self.subTest(state=state):
                files = self.recorded[state]["files"]
                self.assertEqual(len(files), 16)
                self.assertTrue(all(f["file_name"] for f in files))

    def test_the_mid_run_snapshot_is_the_one_that_broke(self):
        files = self.recorded["mid_run"]["files"]
        done = sum(int(f["indexed_pages"] or 0) for f in files)
        total = sum(int(f["total_pages"] or 0) for f in files)
        self.assertEqual((done, total), (37, 129),
                         "the 09-16 display showed 0/0 while the server had this")

    def test_every_entry_carries_what_the_script_reads(self):
        for state in ("complete", "mid_run"):
            for f in self.recorded[state]["files"]:
                with self.subTest(state=state, file=f["file_name"]):
                    for key in READ_BY_THE_SCRIPT:
                        self.assertIn(key, f)


class TheEndpointStillEmitsThem(unittest.TestCase):
    """Source-level, because the handler is wrapped in FastAPI dependencies.
    A rename shows up here before it reaches a re-index at 09:12."""

    def setUp(self):
        self.src = inspect.getsource(server.get_document_index_status)

    def test_the_per_file_keys(self):
        for key in READ_BY_THE_SCRIPT:
            with self.subTest(key=key):
                self.assertIn(f'"{key}":', self.src)

    def test_the_response_is_keyed_files(self):
        self.assertIn('"files": files_out', self.src)

    def test_pages_fall_back_to_the_file_row_when_the_job_has_no_total(self):
        # pages_total is None from the moment a job is enqueued until the
        # worker reaches it, so without this fallback a queued file reports
        # 0 pages and the progress line reads 0/0 for real.
        self.assertIn('job.get("pages_total") or fr.get("page_count")', self.src)

    def test_a_file_with_no_job_still_reports(self):
        self.assertIn('"indexed" if indexed else "not_queued"', self.src)


class TheClientHalfRuns(unittest.TestCase):
    """scripts/tests/test-status-display.ps1, from the backend suite, so the
    two halves of the contract fail together. Skipped where no PowerShell
    exists; the GitHub runners all carry pwsh."""

    def test_the_display_test_passes(self):
        import shutil
        import subprocess
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("no PowerShell on this machine")
        script = (Path(__file__).resolve().parents[2]
                  / "scripts" / "tests" / "test-status-display.ps1")
        r = subprocess.run(
            [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0, (r.stdout or "") + (r.stderr or ""))


if __name__ == "__main__":
    unittest.main()
