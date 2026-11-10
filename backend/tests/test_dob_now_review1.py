"""Adversarial review 1 (section B) of the DOB NOW: Inspections reader, each
finding as a test that failed on ecf64511.

  C1  a failed / unrecognised search reply read as "checked, nothing found",
      and was cached for 6 hours.
  M8  'Did not pass', 'Not Certified', 'Partial Pass' read as pass / done.
  M9  the bare-absence guard was never enforced, and any text with
      'checked:' passed it.
  6   inspection 7755632's own result comment (its details page) was never
      read, so the floor cells could not be linked to its date.
"""

from __future__ import annotations

import os
import re
import unittest
from datetime import date
from unittest.mock import patch

from lib import dob_now_inspections as D
from lib import dob_now_portal as P
from lib import source_coverage as SC
from tests import dob_now_fake as F

S5 = "B01141294S5PL"


# ── C1: only a recognised search reply is a search that was read ───────────

class AFailedSearchIsNeverChecked(unittest.TestCase):
    def test_the_three_bad_replies_are_unreachable_not_checked(self):
        for name, body in F.BAD_SEARCH_REPLIES.items():
            with self.subTest(reply=name):
                res = P.check_bins([F.NEW_BIN], F.portal(search_reply=body))
                self.assertEqual(res["state"], "unreachable")
                self.assertEqual(res["searched"], {})
                self.assertEqual(P.coverage_entry(res)["state"], SC.UNREACHABLE)
                self.assertRegex(res["why"], r"search reply was not recognised")

    def test_one_bad_bin_makes_the_read_partial(self):
        class OneBad(F.FakeSession):
            def post(self, url, data=None, **kw):
                if "CapHome" in url and (data or {}).get(P.BIN_FIELD) == F.OLD_BIN:
                    return F.Resp(F.BAD_SEARCH_REPLIES["error segment"], 200, url)
                return super().post(url, data=data, **kw)
        portal = P.Portal(OneBad(), delay=0, sleep=lambda s: None)
        res = P.check_bins([F.NEW_BIN, F.OLD_BIN], portal)
        self.assertEqual(res["state"], "partial")
        self.assertEqual(P.coverage_entry(res)["state"], SC.NOT_LOADED)

    def test_the_portals_own_no_results_notice_is_a_checked_empty_search(self):
        res = P.check_bins(["3999998"], F.portal())
        self.assertEqual(res["state"], "checked")
        self.assertEqual(res["searched"]["3999998"]["recognised"], "no_results")
        self.assertEqual(res["records"], [])

    def test_the_reply_kinds(self):
        self.assertEqual(P.search_reply_kind(F.search_delta(F.NEW_BIN, 1)), "grid")
        self.assertEqual(P.search_reply_kind(F.no_results_delta()), "no_results")
        self.assertEqual(P.search_reply_kind("22|error|500|An unknown error occurred|"), "not_a_delta")
        self.assertEqual(P.search_reply_kind("5|error|500|Oops!|"), "error")
        self.assertEqual(P.search_reply_kind("5|hiddenField|__VIEWSTATE|vs-xx|"), "unrecognised")

    def test_only_a_checked_read_is_cached(self):
        P.forget()
        try:
            bins = [F.NEW_BIN]
            for state in ("partial", "unreachable", "not_checked"):
                P.remember(bins, {"state": state, "records": []}, at=0.0)
                self.assertIsNone(P.cached(bins, now=1.0), state)
            P.remember(bins, {"state": "checked", "records": []}, at=0.0)
            self.assertEqual(P.cached(bins, now=1.0)["state"], "checked")
            self.assertIn("state=checked", next(iter(P._CACHE)))
        finally:
            P.forget()

    def test_dob_status_never_says_checked_after_a_failed_search(self):
        out = _dob_status(search_reply=F.BAD_SEARCH_REPLIES["a delta with only a hidden field"])
        self.assertRegex(out, r"DOB NOW: Inspections \(public portal[^\n]*\(unreachable: ")
        self.assertIsNone(re.search(r"checked: [^\n]*DOB NOW: Inspections \(public portal[^)]*\) \(read ", out))


# ── M8: a whitelist of pass / certified words ──────────────────────────────

class ResultWords(unittest.TestCase):
    TABLE = {
        "Pass": "pass", "PASSED": "pass", "Pass-Final": "pass", "Spot Check - Pass-Final": "pass",
        "Certified": "certified", "CERTIFIED": "certified",
        "Fail": "fail", "Failed": "fail", "Disapproved": "fail", "Did not pass": "fail", "Not Passed": "fail",
        "Not Pass": "fail", "Did Not Pass-Final": "fail",
        "Partial Pass": "partial", "Pass - Partial": "partial", "Pass (Partial)": "partial",
        "Conditional Pass": "partial", "Pass - Corrections Required": "partial", "Passed with Objections": "partial",
        "Not Certified": "unresolved", "Certification Revoked": "unresolved", "Certification Rescinded": "unresolved",
        "Spot Check - Not Certified": "unresolved", "Cancelled": "unresolved", "No Access": "unresolved",
        "Withdrawn": "unresolved", "Scheduled": "unresolved", "": "unresolved",
    }

    def test_every_word(self):
        for said, want in self.TABLE.items():
            with self.subTest(said=said):
                self.assertEqual(D.outcome(said), want)

    def test_only_pass_and_certified_are_done(self):
        page = F.fixture(f"record_{S5}.html")
        for said in ("Partial Pass", "Not Certified", "Cancelled", "No Access", "Did not pass"):
            with self.subTest(said=said):
                bad = page.replace("WS ROUGH:</span></td><td style='width:5px'></td><td style='vertical-align:top' "
                                   "class='ACA_AlignLeftOrRight'><span class='ACA_SmLabel ACA_SmLabel_FontSize'>PASSED",
                                   "WS ROUGH:</span></td><td style='width:5px'></td><td style='vertical-align:top' "
                                   f"class='ACA_AlignLeftOrRight'><span class='ACA_SmLabel ACA_SmLabel_FontSize'>{said}",
                                   1)
                items, cov = D.to_evidence([{"record": D.parse_record(bad), "inspections": None}], "p")
                cell = [i for i in items if i["ref"] == f"{S5}|PL FLOOR RESULTS|001|WS ROUGH"]
                if D.outcome(said) == "unresolved":
                    self.assertEqual(cell, [])
                    self.assertIn(f"{S5} 001 WS ROUGH: {said}", cov["no_claim"])
                else:
                    self.assertNotEqual(cell[0]["claim"], "done")

    def test_a_self_certification_that_failed_is_never_dob_verified(self):
        page = F.fixture("record_CERT-ADV-PL-26-010624.html").replace(">Certified<", ">Failed<", 1)
        items, _ = D.to_evidence([{"record": D.parse_record(page), "inspections": None}], "p")
        failed = [i for i in items if i["claim"] == "failed"]
        self.assertEqual([(i["kind"], i["by"]) for i in failed],
                         [("confirmed", "licensed master plumber (self-certification)")])


# ── M9: the guard is source-aware and enforced where answers are made ──────

UNCHECKED = [SC.entry(SC.DOB_OPEN_DATA, SC.CHECKED, as_of="2026-11-10T03:00"),
             SC.entry(SC.DOB_NOW_INSPECTIONS, SC.NOT_CHECKED, why="the reader is off")]


class TheGuardNamesTheSameSource(unittest.TestCase):
    def test_a_checked_line_alone_does_not_back_an_absence(self):
        self.assertIsNotNone(SC.bare_absence("No inspections on record.\nSources for inspections — checked: none.",
                                             UNCHECKED))
        self.assertIsNotNone(SC.bare_absence("No inspections on record.\nSources — checked: NYC Open Data.",
                                             UNCHECKED))

    def test_the_review_phrasings_are_absences(self):
        for said in ("There were no plumbing inspections.", "DOB never inspected the plumbing.",
                     "No inspection results exist.", "Plumbing results aren't in public data."):
            with self.subTest(said=said):
                self.assertIsNotNone(SC.bare_absence(said, UNCHECKED))

    def test_naming_the_unchecked_source_with_its_state_backs_it(self):
        said = "No inspections on record in what was checked. Not checked: DOB NOW: Inspections (the reader is off)."
        self.assertIsNone(SC.bare_absence(said, UNCHECKED))
        self.assertIsNone(SC.bare_absence("No inspections on record.", [UNCHECKED[0]]))   # all checked
        self.assertIsNotNone(SC.bare_absence("Not in public data.", [UNCHECKED[0]]))      # never

    def test_dob_status_corrects_an_absence_a_component_lets_through(self):
        """The composed answer, not the helper: a section that says the old
        words goes out corrected."""
        old = ["\nDOB sign-offs: none.", "Not in NYC public data, so not in these records: DOB NOW inspection results.",
               "No inspections on record."]
        with patch("lib.dob_signoffs.signoff_section", lambda rows: list(old)):
            out = _dob_status(flag=False)
        self.assertIsNone(SC.bare_absence(out, UNCHECKED), out)
        self.assertIsNone(re.search(r"not in nyc public data", out, re.I))
        self.assertRegex(out, r"Not checked, so inspections there are unknown \(not absent\): [^\n]*DOB NOW: Inspections")

    def test_project_status_corrects_it_too(self):
        import server
        from lib import project_progress as PPG
        model = PPG.build([], today=date(2026, 11, 10), project={"building_stories": 2}, job="588")
        ctx = {"ident": {"company_id": "co_a"}}

        async def scope(cid, pid):
            return {"_id": pid, "company_id": cid, "name": "588"}

        async def progress(project, cid, job=""):
            return model
        with patch.object(server, "_bot_project_scope", scope), patch.object(server, "_project_progress", progress), \
                patch.object(PPG, "as_text", lambda m, scope="overall", name=None: "No inspections on record."):
            import asyncio
            out = asyncio.run(server._dm_project_status(ctx, {"id": "p588", "label": "588"}, {"scope": "overall"}))
        self.assertIsNone(SC.bare_absence(out, model["inspection_sources"]), out)
        self.assertRegex(out, r"DOB NOW: Inspections \(public portal[^\n]*\(not checked: ")

    def test_the_reply_path_rewrites_a_model_absence(self):
        import server
        tool = _dob_status(flag=False)
        trace = [{"tool": "dob_status", "args": {}, "result": tool[:3000]}]
        out = server._dm_no_negative_claims("Signed off: B01141294-S4. There were no plumbing inspections on 588.",
                                            trace)
        self.assertIn("Signed off: B01141294-S4.", out)
        self.assertRegex(out, r"That is not a finding that none happened: not checked — [^\n]*DOB NOW: Inspections")
        self.assertIsNone(re.search(r"There were no plumbing inspections", out))
        bare = server._dm_no_negative_claims("No inspections happened on 588.", [])
        self.assertEqual(bare, "I haven't checked the inspection sources for that (dob_status reads them).")
        public = server._dm_no_negative_claims("Plumbing results aren't in public data.",
                                               [{"tool": "dob_status", "result": "No inspections in any source checked: x."}])
        self.assertIsNone(re.search(r"public data", public))


# ── 6: the inspection's own details page ───────────────────────────────────

class TheDetailsPage(unittest.TestCase):
    def test_status_history_and_the_comment_without_the_person(self):
        det = D.parse_inspection_detail(F.fixture("detail_7755632.html"))
        self.assertIs(det["loaded"], True)
        self.assertEqual((det["id"], det["name"]), ("7755632", "PL - Up to 9 Requested Floors"))
        self.assertEqual([(h["status"], h["at"]) for h in det["status_history"]], [
            ("Pass-Final", "2026-11-05T10:20"), ("Pass", "2026-11-05T10:20"), ("Scheduled", "2026-11-05T09:50"),
            ("Pending", None), ("Pending", None)])
        self.assertEqual(det["comment"], "W/S Storm /gas rough & OSP rough pass")
        self.assertEqual(det["resulted_at"], "2026-11-05T10:20")
        self.assertEqual(D.clean_comment("ATOI:REP; Some Person ABCD#1234...... rough pass"), "rough pass")
        self.assertIsNone(D.clean_comment("ATOI:REP; Some Person ABCD#1234 rough pass"))
        self.assertIs(D.parse_inspection_detail(F.fixture_error())["loaded"], False)

    def test_the_read_links_the_floor_cells_to_7755632_as_an_inference(self):
        res = P.check_bins([F.NEW_BIN, F.OLD_BIN], F.portal())
        s5 = next(r for r in res["records"] if r["record_id"] == S5)
        self.assertEqual(s5["details"]["7755632"]["comment"], "W/S Storm /gas rough & OSP rough pass")
        items, cov = D.to_evidence(res["records"], "p588")          # no comments handed in
        cells = [i for i in items if "|PL FLOOR RESULTS|" in i["ref"]]
        dated = [i for i in cells if i["on"]]
        self.assertEqual((len(dated), cov["linked_cells"]), (19, 19))
        self.assertTrue(all(i["on"] == date(2026, 11, 5) and i["basis"].startswith("link inference: inspection 7755632")
                            for i in dated))
        self.assertTrue(all(i["on"] is None for i in cells if "CERTIFIED" in i["quote"]))

    def test_no_details_page_means_no_date(self):
        res = P.check_bins([F.NEW_BIN, F.OLD_BIN], F.portal(no_details=True))
        self.assertEqual(res["state"], "checked")
        items, cov = D.to_evidence(res["records"], "p588")
        self.assertEqual(cov["linked_cells"], 0)

    def test_two_inspections_naming_the_same_work_date_nothing(self):
        lst = D.parse_inspection_list(F.fixture(f"inspections_{S5}.txt"))
        twin = dict(lst["completed"][2], id="7999999", resulted_at="2026-11-07T09:00")
        lst = dict(lst, completed=lst["completed"] + [twin], stated_count=4)
        comment = "W/S Storm /gas rough & OSP rough pass"
        items, cov = D.to_evidence([{"record": D.parse_record(F.fixture(f"record_{S5}.html")), "inspections": lst}],
                                   "p", comments={"7755632": comment, "7999999": comment})
        self.assertEqual(cov["linked_cells"], 0)


def _dob_status(*, flag: bool = True, **fake) -> str:
    import server
    from tests.test_whatsapp_dm_assistant import THOMAS, _db, _run
    from tests.test_whatsapp_phase1_foundations import CO_A
    db = _db()
    for p in db.projects.rows:
        if p["_id"] == THOMAS:
            p.update(nyc_bin=F.OLD_BIN, additional_bins=[F.NEW_BIN])
    P.forget()
    env = {P.FLAG: "true"} if flag else {}
    with patch.dict(os.environ, env), patch.object(server, "db", db), \
            patch.object(server, "_dob_now_portal_reader", lambda: F.portal(**fake)):
        if not flag:
            os.environ.pop(P.FLAG, None)
        out = _run(server._handle_dob_status(THOMAS, company_id=CO_A))
    P.forget()
    return out


# ── 5: additional_bins has one writer: a company admin ─────────────────────

class TheListedBins(unittest.TestCase):
    def test_only_real_bins_are_accepted(self):
        import server
        from fastapi import HTTPException
        self.assertEqual(server._valid_additional_bins(["3255362", "3255362", " 3430621 "]), ["3255362", "3430621"])
        self.assertEqual(server._valid_additional_bins([]), [])
        for bad in (["325536"], ["3000000"], ["abc1234"], ["1", "2"], ["3255362"] * 1 + [f"30{i}1234" for i in range(5)]):
            with self.subTest(bad=bad), self.assertRaises(HTTPException):
                server._valid_additional_bins(bad)

    def test_the_field_is_on_the_admin_update(self):
        import server
        self.assertIn("additional_bins", server.ProjectUpdate.model_fields)

    def test_a_listed_bin_still_needs_a_shared_job_in_the_sync(self):
        import asyncio
        import server
        own = [{"_record_type": "permit", "bin": F.OLD_BIN, "job_filing_number": "B01141294-S5", "unique_key": "a"}]
        found = {"3999999": [{"_record_type": "permit", "bin": "3999999", "job_filing_number": "B09999999-I1",
                              "unique_key": "n1"}]}

        async def fake(bin_, address="", answered=None):
            return list(found.get(bin_, []))
        with patch.object(server, "_query_dob_apis", fake):
            got = asyncio.run(server._with_site_bins("p1", F.OLD_BIN, own, {}, listed_bins=["3999999"]))
        self.assertEqual([r["unique_key"] for r in got], ["a"])


if __name__ == "__main__":
    unittest.main()
