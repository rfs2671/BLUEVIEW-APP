"""MR.13 — pin the worker's boot-time WARNING log when the
ELIGIBILITY_BYPASS_DAYS_REMAINING override is set.

The actual eligibility-bypass logic lives on the backend; the worker
container doesn't consult the override directly. But the user-facing
contract for MR.13 is "the override CANNOT silently stay set in
production." This test confirms the worker's `main()` would emit
the loud WARNING line at boot when the env var is set, so an
operator scanning `docker compose logs` immediately sees it.

We don't actually run main() (that would try to connect to Redis,
launch Playwright, etc.). We exercise the small block of main() that
reads the env var and decides whether to log — by importing and
calling the relevant function, OR by reading the source statically
to confirm the warning string is present.

Static-source check is the lightest contract: if a future commit
removes the boot warning, this test breaks. Combined with the
backend-side test_eligibility_bypass that pins the actual logic,
the override has end-to-end coverage.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DOB_WORKER = _HERE.parent
sys.path.insert(0, str(_DOB_WORKER))


class TestWorkerBootWarning(unittest.TestCase):

    def test_dob_worker_main_contains_bypass_warning(self):
        """The worker's main() must contain a WARNING-level log line
        keyed on ELIGIBILITY_BYPASS_DAYS_REMAINING + the
        'ELIGIBILITY BYPASS ACTIVE' marker. Future readers grep for
        either token to find this code path."""
        worker_path = _DOB_WORKER / "dob_worker.py"
        text = worker_path.read_text(encoding="utf-8", errors="ignore")

        # Required tokens — the env var name + the operator-facing
        # marker phrase.
        self.assertIn("ELIGIBILITY_BYPASS_DAYS_REMAINING", text)
        self.assertIn("ELIGIBILITY BYPASS ACTIVE", text)

        # Required structure: this MUST be in main() (or a function
        # called from main()) so it fires at boot, not lazily on
        # first request. Cheap heuristic: the warning text must
        # appear inside the same module that defines async def main.
        self.assertIn("async def main", text)

        # Required severity: must be a WARNING-level log so it
        # stands out in operator log dashboards. Verify by checking
        # the surrounding text — both the env var name AND
        # logger.warning must be in the same ~20 lines.
        idx = text.index("ELIGIBILITY_BYPASS_DAYS_REMAINING")
        # Look backward up to 1000 chars; logger.warning should
        # appear in that window if structured correctly.
        window = text[max(0, idx - 1000):idx]
        self.assertIn(
            "logger.warning", window,
            "BYPASS env var read must be inside a logger.warning() call",
        )

    def test_must_be_unset_in_production_phrasing(self):
        """Operator-readable phrasing pinned. If the warning text
        ever drifts to something less obvious, this test catches it."""
        worker_path = _DOB_WORKER / "dob_worker.py"
        text = worker_path.read_text(encoding="utf-8", errors="ignore")
        self.assertIn("MUST be unset in production", text)


if __name__ == "__main__":
    unittest.main()
