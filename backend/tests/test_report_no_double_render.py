"""A logbook with its own section is not printed a second time.

WHAT THIS CATCHES. generate_combined_report prints a dedicated section for each
log type it knows about, then sweeps everything ELSE into "Additional
Logbooks" -- skipping any type listed in `handled_types`. That set is
hand-maintained, and it is the only thing standing between a named section and
a duplicate. Add a section, forget the set, and the log renders TWICE on a
document a CP signs and DOB may read.

TWO TYPES HAD ALREADY FALLEN THROUGH: fall_protection, and
site_superintendent_log -- the BC 3301.13.13 log, added by #310. Any day
carrying either printed it once under its own heading and again under
Additional Logbooks.

WHY THIS IS ASSERTED STRUCTURALLY RATHER THAN BY RENDERING. The bug is not in
what either section prints; both are correct in isolation. It is in a set
literal drifting away from the sections beside it, and the only durable check
is the one that reads BOTH and compares them. A rendering test would pin the
two types known to be broken today and stay silent on the thirteenth section
somebody adds next year.

THE FAILURE IS SILENT AND PLAUSIBLE-LOOKING, which is why it survived. A
duplicated section is not an error, not a crash, and not obviously wrong to
anyone who has not counted -- it reads as a report that mentions something
twice.
"""

import ast
import inspect
import os
import re
import sys
import textwrap
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

CODE = ast.unparse(ast.parse(textwrap.dedent(
    inspect.getsource(server.generate_combined_report))))

# Every log type the function pulls out for a section of its own.
DEDICATED = set(re.findall(r"_filed_log\(logbooks, ['\"]([a-z_]+)['\"]\)", CODE))

_m = re.search(r"handled_types = \{(.*?)\}", CODE, re.S)
HANDLED = set(re.findall(r"'([a-z_]+)'", _m.group(1))) if _m else set()


class TheTwoListsAgree(unittest.TestCase):
    def test_the_parse_found_both(self):
        """If either regex stops matching, every assertion below passes
        vacuously. Fail loudly instead."""
        self.assertGreaterEqual(len(DEDICATED), 12)
        self.assertGreaterEqual(len(HANDLED), 12)

    def test_every_dedicated_section_is_excluded_from_the_sweep(self):
        """THE ASSERTION. A type with its own section must never also be
        swept into Additional Logbooks."""
        missing = sorted(DEDICATED - HANDLED)
        self.assertEqual(
            missing, [],
            "these log types render TWICE -- once in their own section and "
            f"again under Additional Logbooks: {missing}")

    def test_the_two_that_were_broken_are_named(self):
        """Regression pins. Both shipped renderable and unexcluded."""
        self.assertIn("fall_protection", HANDLED)
        self.assertIn("site_superintendent_log", HANDLED)

    def test_the_superintendent_log_still_HAS_its_own_section(self):
        """The other way to make the sets agree is to delete the section. That
        would silently demote a statutory record to a generic key/value dump."""
        self.assertIn("site_superintendent_log", DEDICATED)
        self.assertIn("fall_protection", DEDICATED)


class TheSweepStillSweeps(unittest.TestCase):
    """PASSES EITHER WAY. The fix must not turn Additional Logbooks off."""

    def test_the_sweep_still_exists(self):
        self.assertIn("additional_logbooks_html", CODE)
        self.assertIn("for logbook in logbooks", CODE)

    def test_an_unknown_type_is_still_printed(self):
        """A type with no dedicated section must still reach the page -- the
        sweep is what keeps a new log from vanishing from the report."""
        self.assertNotIn("some_future_log_type", HANDLED)
        self.assertNotIn("some_future_log_type", DEDICATED)

    def test_handled_types_may_carry_extras(self):
        """subcontractor_orientation is excluded from the sweep without a
        _filed_log lookup, because it is fetched differently. Extra entries are
        harmless; only the missing direction duplicates."""
        self.assertIn("subcontractor_orientation", HANDLED)


if __name__ == "__main__":
    unittest.main()
