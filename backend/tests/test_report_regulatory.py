"""DOB/DOT records read as of the period: a lifted SWO is not active, a
resolved violation is not open, an old backlog row is not "new"."""
import unittest

from lib import report_regulatory as RG
from tests import report_588 as F


def build(**kw):
    args = dict(dob_rows=F.dob_rows(), dot_rows=F.dot_rows(), start=F.START, end=F.END, today=F.END,
                sync=F.SYNC, now=F.NOW)
    args.update(kw)
    return RG.build(args.pop("dob_rows"), args.pop("dot_rows"), args.pop("start"), args.pop("end"), **args)


class AsOfThePeriod(unittest.TestCase):
    def test_the_lifted_swo_is_lifted_not_active(self):
        r = build()
        self.assertEqual(r["swo_active"], [])
        self.assertEqual(len(r["swo_lifted"]), 1)

    def test_open_at_period_end_holds_the_open_violation_only(self):
        nums = {x["number"] for x in build()["open"]}
        self.assertIn("35123456", nums)
        self.assertNotIn("29887711", nums)                  # resolved

    def test_the_permit_expiring_soon(self):
        self.assertTrue(build()["expiring"])

    def test_a_backlog_row_from_2019_is_not_issued_in_the_period(self):
        issued = {x["number"] for x in build()["issued"]}
        self.assertFalse(any("2019" in str(x) for x in issued))

    def test_311_complaints_are_not_reported(self):
        rows = F.dob_rows() + [{"_id": "c311", "record_type": "complaint", "source": "311", "raw_dob_id": "311-1",
                                "current_status": "OPEN", "issue_date": F.START.isoformat()}]
        self.assertNotIn("311-1", {x.get("number") for k in ("issued", "open") for x in build(dob_rows=rows)[k]})

    def test_stale_sync_is_disclosed_as_coverage(self):
        cov = build(sync={})["coverage"]
        self.assertNotEqual(cov, build()["coverage"])


if __name__ == "__main__":
    unittest.main()
