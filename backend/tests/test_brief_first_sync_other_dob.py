"""Morning brief: job filings, C of O, facade, boiler and elevator rows wait
for their own source's first sync (lib/source_sync.py), like violations,
complaints and permits. Nothing a source's first sync stored is "new" or a
"change"; before that first sync the source gives no item at all."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import source_sync, wa_brief  # noqa: E402

NOW = datetime(2026, 10, 8, 11, 5, tzinfo=timezone.utc)
SINCE = NOW - timedelta(days=1)
STORED = NOW - timedelta(hours=1)          # when the change row was stored

# record_type → (its source, its number field)
CASES = {
    "job_status": (source_sync.DOB_JOB_FILINGS, "job_number"),
    "cofo": (source_sync.DOB_COFO, "job_number"),
    "facade_fisp": (source_sync.DOB_FACADE, "filing_number"),
    "boiler": (source_sync.DOB_BOILER, "tracking_number"),
    "elevator": (source_sync.DOB_ELEVATOR, "device_number"),
}


def _changed(rt, num_field):
    """A record DOB moved PENDING → ON HOLD (needs action): two rows."""
    base = {"project_id": "p1", "company_id": "c1", "record_type": rt,
            "raw_dob_id": f"{rt}:1", num_field: "N-1", "severity": "Action"}
    return [
        {**base, "_id": "a", "current_status": "PENDING",
         "previous_status": None, "detected_at": STORED - timedelta(hours=2)},
        {**base, "_id": "b", "current_status": "ON HOLD",
         "previous_status": "PENDING", "detected_at": STORED,
         "status_changed_at": STORED},
    ]


def _all(at):
    return {s: at for s in source_sync.SOURCES}


class EachSourceWaitsForItsFirstSync(unittest.TestCase):

    def _check(self, rt):
        src, num_field = CASES[rt]
        rows = _changed(rt, num_field)

        def items(synced):
            return [i["text"] for i in wa_brief.job_items(rows, SINCE, NOW, (), synced)]

        # The row is a real change: with the source synced before it, it shows.
        shown = items(_all(STORED - timedelta(hours=3)))
        self.assertEqual(len(shown), 1, shown)
        self.assertIn("N-1 changed PENDING → ON HOLD", shown[0])
        # Stored by the source's first sync: never new, never a change.
        self.assertEqual(items(_all(STORED + timedelta(minutes=5))), [])
        # The source not yet synced (every other one is): no item at all.
        others = {s: STORED - timedelta(hours=3) for s in source_sync.SOURCES if s != src}
        self.assertEqual(items(others), [])

    def test_job_filings(self):
        self._check("job_status")

    def test_certificate_of_occupancy(self):
        self._check("cofo")

    def test_facade(self):
        self._check("facade_fisp")

    def test_boiler(self):
        self._check("boiler")

    def test_elevator(self):
        self._check("elevator")


class SourcesAndFallback(unittest.TestCase):

    def test_each_record_type_has_its_own_dob_source(self):
        for rt, (src, _f) in CASES.items():
            self.assertEqual(source_sync.RECORD_SOURCE[rt], src)
            self.assertIn(src, source_sync.DOB_SOURCES)
        self.assertEqual(len({s for s, _f in CASES.values()}), len(CASES))

    def test_a_dob_sync_pass_counts_them(self):
        answered = {"job_status": True, "cofo": False, "facade_fisp": True,
                    "boiler": True, "elevator": True}
        self.assertEqual(source_sync.answered_sources(answered, ["boiler"]),
                         {source_sync.DOB_JOB_FILINGS, source_sync.DOB_FACADE,
                          source_sync.DOB_ELEVATOR})

    def test_existing_projects_use_first_poll(self):
        old = source_sync.LEGACY_FIRST_POLL_BEFORE - timedelta(days=100)
        got = source_sync.first_synced(None, {"first_poll_completed_at": old})
        for src, _f in CASES.values():
            self.assertEqual(got[src], old)

    def test_no_gc_kind_reads_them(self):
        """GC group alerts collect only violation / complaint / SWO / permit
        rows; if a kind ever reads these record types it needs a source."""
        self.assertFalse(set(source_sync.KIND_SOURCE.values())
                         & {s for s, _f in CASES.values()})


if __name__ == "__main__":
    unittest.main()
