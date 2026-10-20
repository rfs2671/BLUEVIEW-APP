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


class OnlyThisBuildingsRecords(unittest.TestCase):
    """Real 588 data: records for two BINs (3430621 and 3255362) were printed
    together. The address search can return a neighbour's records, so a record
    whose OWN building number is not the project's is left out and LISTED; one
    with no readable building number is kept and counted, never dropped."""

    PROJECT = "3430621"

    def row(self, number, bin_, **kw):
        link = f"https://a810-bisweb.nyc.gov/bisweb/PropertyProfileOverviewServlet?bin={bin_}" if bin_ else None
        base = {"_id": number, "raw_dob_id": f"permit:{number}", "record_type": "permit", "permit_status": "PERMIT ISSUED",
                "job_number": number, "issuance_date": "2026-10-14", "expiration_date": "2026-11-01",
                "detected_at": F.NOW, "dob_link": link, "nyc_bin": self.PROJECT}   # nyc_bin = the PROJECT's, not the record's
        base.update(kw)
        return base

    def test_the_records_own_bin_is_read_not_the_rows_project_bin(self):
        self.assertEqual(RG.row_bin(self.row("B1", "3255362")), "3255362")
        self.assertEqual(RG.row_bin(self.row("B1", None)), "")
        self.assertEqual(RG.row_bin(self.row("B1", None, bin__="3,430,621")), "3430621")
        self.assertEqual(RG.row_bin({"dob_link": "https://x/ComplaintsByAddressServlet?requestid=1&allbin=3430621"}), "3430621")

    def test_another_buildings_record_is_left_out_and_listed(self):
        rows = [self.row("B-MINE", "3430621"), self.row("B-THEIRS", "3255362")]
        got = build(dot_rows=[], dob_rows=rows, project_bins=[self.PROJECT])
        self.assertEqual([x["number"] for x in got["issued"]], ["B-MINE"])
        self.assertEqual([(x["number"], x["bin"]) for x in got["excluded"]], [("B-THEIRS", "3255362")])
        self.assertEqual(got["bins"], [self.PROJECT])

    def test_a_record_with_no_readable_bin_is_kept_and_counted(self):
        got = build(dot_rows=[], dob_rows=[self.row("B-UNKNOWN", None)], project_bins=[self.PROJECT])
        self.assertEqual([x["number"] for x in got["issued"]], ["B-UNKNOWN"])
        self.assertEqual((got["bin_unverified"], got["excluded"]), (1, []))

    def test_an_added_bin_belongs_to_the_site(self):
        rows = [self.row("B-MINE", "3430621"), self.row("B-ANNEX", "3255362")]
        got = build(dot_rows=[], dob_rows=rows, project_bins=[self.PROJECT, "3255362"])
        self.assertEqual(sorted(x["number"] for x in got["issued"]), ["B-ANNEX", "B-MINE"])
        self.assertEqual(got["excluded"], [])

    def test_with_no_project_bin_nothing_is_filtered(self):
        rows = [self.row("A", "3430621"), self.row("B", "3255362")]
        got = build(dot_rows=[], dob_rows=rows, project_bins=[])
        self.assertEqual(len(got["issued"]), 2)
        self.assertEqual(got["excluded"], [])

    def test_the_report_says_what_it_left_out(self):
        from lib import progress_report as P
        rows = [self.row("B-MINE", "3430621"), self.row("B-THEIRS", "3255362"), self.row("B-UNK", None)]
        rep = F.report(dob_rows=rows, project_bins=[self.PROJECT])
        notes = " ".join(rep["data_notes"])
        self.assertIn("left out", notes)
        self.assertIn("3255362", notes)
        self.assertIn("B-THEIRS", notes)
        self.assertIn("no building number", notes)
        self.assertNotIn("B-THEIRS", " ".join(e["number"] for e in rep["regulatory"]["open"] + rep["regulatory"]["issued"]))
        self.assertEqual([e["number"] for e in rep["regulatory"]["excluded"]], ["B-THEIRS"])


class AJobFiledUnderTwoBuildingsIsOneSite(unittest.TestCase):
    """REAL 588 DATA (BIN analysis, Oct 2026): project BIN 3255362; jobs B01141294
    and B01409772 each appear under BIN 3255362 AND BIN 3430621. One DOB job
    can be filed against more than one building of a lot, so 3430621 is part of
    the site -- the first BIN guard excluded nine of its own records, among them
    the permit issued Oct 14 and the one expiring Nov 1."""

    def row(self, number, bin_, status="PERMIT ISSUED", issued="2026-10-14"):
        return {"_id": number + bin_, "raw_dob_id": f"permit:{number}:{bin_}", "record_type": "permit",
                "permit_status": status, "job_number": number, "issuance_date": issued,
                "expiration_date": "2026-11-01", "detected_at": F.NOW, "nyc_bin": "3255362",
                "dob_link": f"https://a810-bisweb.nyc.gov/bisweb/PropertyProfileOverviewServlet?bin={bin_}"}

    def test_the_job_is_the_filing_without_its_suffix(self):
        self.assertEqual(RG.job_base({"job_number": "B01141294-S5", "record_type": "permit"}), "B01141294")
        self.assertEqual(RG.job_base({"job_filing_number": "B01141294-P8", "record_type": "job_status"}), "B01141294")
        self.assertEqual(RG.job_base({"violation_number": "39189039M", "record_type": "violation"}), "")

    def test_a_second_bin_sharing_a_job_with_the_projects_is_part_of_the_site(self):
        rows = [self.row("B01141294-S5", "3255362"), self.row("B01141294-S6", "3430621"),
                self.row("B23173802-S5", "3430621")]          # a record of the same second BIN, a different job
        kept, left, unverified, inferred = RG.split_by_bin(rows, ["3255362"])
        self.assertEqual(inferred, ["3430621"])
        self.assertEqual((len(kept), left), (3, []))          # ALL of 3430621's records are the site's

    def test_a_bin_sharing_no_job_stays_out_and_is_listed(self):
        rows = [self.row("B01141294-S5", "3255362"), self.row("B99999999-I1", "1111111")]
        kept, left, _, inferred = RG.split_by_bin(rows, ["3255362"])
        self.assertEqual((inferred, [x["job_number"] for x in left]), ([], ["B99999999-I1"]))

    def test_the_report_keeps_the_oct_14_permit_and_says_why(self):
        rows = [self.row("B01141294-S5", "3255362", issued="2026-07-15"), self.row("B01141294-S6", "3430621", issued="2026-09-08"),
                self.row("B23173802-S5", "3430621")]
        rep = F.report(dob_rows=rows, dot_rows=[], project_bins=["3255362"])
        self.assertEqual([e["number"] for e in rep["regulatory"]["issued"]], ["B23173802-S5"])
        self.assertEqual(rep["regulatory"]["excluded"], [])
        self.assertTrue(any("3430621" in n and "also appear under this project" in n for n in rep["data_notes"]), rep["data_notes"])
