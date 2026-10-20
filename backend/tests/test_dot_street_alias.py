"""A street the city renamed is still written with its old name.

Real job: 588 Thomas S Boyland Street. DOT wrote two OATH summonses (0704345548,
0704345557; Sept 29, 2026; respondent the job's GC) for "588 HOPKINSON AVENUE
btwn BLAKE AVENUE and SUTTER AVENUE" -- Hopkinson Avenue is the old name of
Thomas S. Boyland Street -- and the report showed no DOT violations, because
"HOPKINSON AVE" is not "THOMAS S BOYLAND ST". The match stays exact: only the
street's own name, the curated old names, and a project's own aliases.
"""

import unittest

from lib import dot_sync as D

PROJECT = {"address": "588 THOMAS S BOYLAND STREET, Brooklyn, NY, USA", "bbl": "3035400025"}


def oath(**kw):
    rec = {"ticket_number": "0704345548", "issuing_agency": "DEPT OF TRANSPORTATION",
           "violation_location_borough": "BROOKLYN", "violation_location_house": "588",
           "violation_location_street_name": "HOPKINSON AVENUE", "violation_location_block_no": "00000",
           "violation_location_lot_no": "0000", "violation_date": "2026-09-29T00:00:00.000",
           "hearing_date": "2026-12-24T00:00:00.000", "hearing_status": "SCHEDULED"}
    rec.update(kw)
    return rec


class ARenamedStreet(unittest.TestCase):

    def setUp(self):
        self.pk = D.project_keys(PROJECT)

    def test_the_streets_names(self):
        self.assertEqual(self.pk["streets"], ["THOMAS S BOYLAND ST", "HOPKINSON AVE"])
        self.assertEqual(self.pk["street"], "THOMAS S BOYLAND ST")

    def test_the_hopkinson_summons_is_this_projects(self):
        self.assertEqual(D.match("dot_violation", self.pk, oath()), "address")
        self.assertEqual(D.match("dot_violation", self.pk, oath(violation_location_street_name="Hopkinson Ave")), "address")
        self.assertEqual(D.to_log("dot_violation", oath())["number"], "0704345548")

    def test_the_house_number_and_borough_must_still_agree(self):
        self.assertIsNone(D.match("dot_violation", self.pk, oath(violation_location_house="586")))
        self.assertIsNone(D.match("dot_violation", self.pk, oath(violation_location_borough="QUEENS")))

    def test_another_street_is_not_guessed(self):
        self.assertIsNone(D.match("dot_violation", self.pk, oath(violation_location_street_name="HOPKINSON STREET")))
        self.assertIsNone(D.match("dot_violation", self.pk, oath(violation_location_street_name="BLAKE AVENUE")))

    def test_a_different_lot_is_a_different_site_whatever_the_street(self):
        self.assertIsNone(D.match("dot_violation", self.pk, oath(violation_location_block_no="01234",
                                                                  violation_location_lot_no="0007")))
        self.assertEqual(D.match("dot_violation", self.pk, oath(violation_location_block_no="03540",
                                                                 violation_location_lot_no="0025")), "bbl")

    def test_the_permit_request_asks_for_both_names_and_the_match_is_exact(self):
        permit_q = [q for q in D.queries(self.pk) if q["dataset"] == D.PERMIT_DATASET][0]["params"]["$where"]
        self.assertIn("like '%BOYLAND%'", permit_q)
        self.assertIn("like '%HOPKINSON%'", permit_q)
        rec = {"permitnumber": "P1", "boroughname": "BROOKLYN", "permithousenumber": "588", "onstreetname": "HOPKINSON AVENUE"}
        self.assertEqual(D.match("dot_permit", self.pk, rec), "address")
        self.assertIsNone(D.match("dot_permit", self.pk, {**rec, "permithousenumber": "590"}))

    def test_a_project_can_name_its_own_alias(self):
        pk = D.project_keys({"address": "10 Main St, Queens, NY", "street_aliases": ["Old Mill Road"]})
        self.assertEqual(pk["streets"], ["MAIN ST", "OLD MILL RD"])
        self.assertEqual(D.match("dot_violation", pk, oath(violation_location_house="10", violation_location_borough="QUEENS",
                                                           violation_location_street_name="OLD MILL ROAD")), "address")

    def test_a_street_with_no_other_name_is_unchanged(self):
        pk = D.project_keys({"address": "8 Walworth St, Brooklyn, NY"})
        self.assertEqual(pk["streets"], ["WALWORTH ST"])

    def test_the_summons_is_a_dot_violation_the_report_lists(self):
        from lib import report_regulatory as RG
        from tests import report_588 as F
        row = {"_id": "d1", "record_type": "dot_violation", "raw_id": "oath:0704345548", "raw_dob_id": "oath:0704345548",
               "number": "0704345548", "issue_date": "2026-09-29", "status": "SCHEDULED", "detected_at": F.NOW}
        got = RG.build([], [row], F.START, F.END, today=F.END, sync=F.SYNC, now=F.NOW)
        self.assertEqual([e["number"] for e in got["open"]], ["0704345548"])


if __name__ == "__main__":
    unittest.main()
