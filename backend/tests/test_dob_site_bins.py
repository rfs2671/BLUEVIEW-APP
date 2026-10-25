"""The job site's other building BINs are fetched too (real 588: BIN 3255362 on
the project, BIN 3430621 where the current filings and two DOB violations are)."""

import asyncio
import unittest
from unittest import mock

from lib import dob_site_bins as S

OWN, SECOND, NEIGHBOUR = "3255362", "3430621", "3999999"


def permit(bin_, job, rt="permit", **kw):
    return {"_record_type": rt, "bin": bin_, "job_filing_number": job, "unique_key": f"{bin_}-{job}", **kw}


class FindingTheSiteBins(unittest.TestCase):

    def test_other_bins_on_returned_records_are_candidates_most_frequent_first(self):
        recs = [permit(OWN, "B01141294-S5"), permit(SECOND, "B01141294-S6"), permit(SECOND, "B23173802-S5"),
                permit(NEIGHBOUR, "B09999999-I1")]
        self.assertEqual(S.candidate_bins(recs, OWN), [SECOND, NEIGHBOUR])
        self.assertEqual(S.candidate_bins(recs, OWN, limit=1), [SECOND])

    def test_placeholders_blanks_and_the_projects_own_bin_are_not_candidates(self):
        recs = [permit(OWN, "B1"), {"_record_type": "violation"}, permit("1000000", "B2"), permit("", "B3")]
        self.assertEqual(S.candidate_bins(recs, OWN), [])

    def test_a_bin_is_part_of_the_site_only_when_it_shares_a_job_with_the_project(self):
        own = [permit(OWN, "B01141294-S5"), permit(OWN, "B01409772-I1")]
        second = [permit(SECOND, "B01141294-S6"), {"_record_type": "violation", "bin": SECOND, "unique_key": "v1"}]
        neighbour = [permit(NEIGHBOUR, "B09999999-I1")]
        self.assertTrue(S.shares_job(own, OWN, second, SECOND))      # same job B01141294, another filing
        self.assertFalse(S.shares_job(own, OWN, neighbour, NEIGHBOUR))

    def test_a_violation_alone_does_not_prove_membership(self):
        own = [permit(OWN, "B01141294-S5")]
        self.assertFalse(S.shares_job(own, OWN, [{"_record_type": "violation", "bin": SECOND, "unique_key": "v"}], SECOND))

    def test_job_suffixes_are_ignored_and_the_bis_job_field_is_read(self):
        self.assertEqual(S.raw_job_base({"_record_type": "permit", "job_filing_number": "b01141294-s5"}), "B01141294")
        self.assertEqual(S.raw_job_base({"_record_type": "permit", "job__": "123456789"}), "123456789")
        self.assertEqual(S.raw_job_base({"_record_type": "violation", "job__": "123456789"}), "")

    def test_only_records_not_already_held_are_new(self):
        have = [permit(OWN, "A")]
        extra = [permit(OWN, "A"), permit(SECOND, "B"), permit(SECOND, "B")]
        self.assertEqual([r["job_filing_number"] for r in S.new_records(have, extra)], ["B"])


class TheSyncUsesIt(unittest.TestCase):

    def run_it(self, found_by_bin, records, fail=False):
        import server

        async def fake(bin_, address="", answered=None):
            if fail:
                raise RuntimeError("down")
            return list(found_by_bin.get(bin_, []))
        with mock.patch.object(server, "_query_dob_apis", fake):
            return asyncio.run(server._with_site_bins("p1", OWN, records, {}))

    def test_the_second_buildings_violations_arrive(self):
        records = [permit(OWN, "B01141294-S5")]
        found = {SECOND: [permit(SECOND, "B01141294-S6"),
                          {"_record_type": "violation", "bin": SECOND, "unique_key": "39558663R"},
                          {"_record_type": "complaint", "bin": SECOND, "unique_key": "3A78809"}]}
        got = self.run_it(found, records + [permit(SECOND, "B01141294-S6")])
        keys = [r.get("unique_key") for r in got]
        self.assertIn("39558663R", keys)
        self.assertIn("3A78809", keys)
        self.assertEqual(len(keys), len(set(keys)))                 # nothing doubled

    def test_a_neighbours_records_are_never_added(self):
        records = [permit(OWN, "B01141294-S5"), permit(NEIGHBOUR, "B09999999-I1")]
        found = {NEIGHBOUR: [permit(NEIGHBOUR, "B09999999-I1"),
                             {"_record_type": "violation", "bin": NEIGHBOUR, "unique_key": "N1"}]}
        got = self.run_it(found, records)
        self.assertNotIn("N1", [r.get("unique_key") for r in got])

    def test_a_failing_fetch_leaves_the_sync_as_it_was(self):
        records = [permit(OWN, "B01141294-S5"), permit(SECOND, "B01141294-S6")]
        self.assertEqual(self.run_it({}, records, fail=True), records)

    def test_a_project_with_no_real_bin_is_left_alone(self):
        import server
        records = [permit(SECOND, "B1")]
        self.assertEqual(asyncio.run(server._with_site_bins("p1", "", records, {})), records)
        self.assertEqual(asyncio.run(server._with_site_bins("p1", "1000000", records, {})), records)
