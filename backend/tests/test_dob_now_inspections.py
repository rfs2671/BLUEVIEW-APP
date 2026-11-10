"""DOB NOW: Inspections — the 588 plumbing results LeveLog called unavailable.

Verified by hand on 2026-11-10 (intel588-data/public/dob_now_inspections_588.json):
the public portal holds, for plumbing permit B01141294-S5-PL, a PL FLOOR RESULTS
table (21 cells: rough WS / gas / storm passed on 001-004, MEZ and ROF; the 001
underground lines certified; OSP storm underground passed) and three completed
inspections (two certified underground on 2026-09-01, the floors inspection
7755632 passed 2026-11-05). LeveLog read the static page's placeholder "There are
no completed inspections on this record." as a negative, never read the floor
table, searched one BIN, and said the results were "not in public data".

The fixtures are SANITIZED copies of the real pages (tests/fixtures/dob_now/):
no person name, phone or email.
"""

from __future__ import annotations

import os
import re
import unittest
from datetime import date
from unittest.mock import patch

from lib import dob_now_inspections as D
from lib import dob_now_portal as P
from lib import dob_signoffs as DS
from lib import source_coverage as SC
from tests import dob_now_fake as F

S5 = "B01141294S5PL"

#: The fact file's floor table, exactly.
FLOOR_TABLE = {
    "001": {"WS UND GRND": "CERTIFIED", "WS ROUGH": "PASSED", "GAS ROUGH": "PASSED", "ST DRN UND GRND": "CERTIFIED",
            "ST DRN ROUGH": "PASSED"},
    "002": {"WS ROUGH": "PASSED", "GAS ROUGH": "PASSED", "ST DRN ROUGH": "PASSED"},
    "003": {"WS ROUGH": "PASSED", "GAS ROUGH": "PASSED", "ST DRN ROUGH": "PASSED"},
    "004": {"WS ROUGH": "PASSED", "GAS ROUGH": "PASSED", "ST DRN ROUGH": "PASSED"},
    "MEZ": {"WS ROUGH": "PASSED", "GAS ROUGH": "PASSED", "ST DRN ROUGH": "PASSED"},
    "OSP": {"ST DRN UND GRND": "PASSED"},
    "ROF": {"WS ROUGH": "PASSED", "GAS ROUGH": "PASSED", "ST DRN ROUGH": "PASSED"},
}
#: 7755632's own result comment, names removed (fact file).
COMMENT_7755632 = "ATOI:REP; [plumber's representative] JMFGC#1238...... W/S Storm /gas rough & OSP rough pass"


def record(rid):
    return D.parse_record(F.fixture(f"record_{rid}.html"))


def listed(rid):
    return D.parse_inspection_list(F.fixture(f"inspections_{rid}.txt"))


def portal_records(*rids):
    return [{"record_id": r, "record": record(r), "inspections": listed(r)} for r in rids]


ALL = ("B01141294S5PL", "ADV-PL-26-011521", "CERT-ADV-PL-26-010624", "ADV-PL-26-014303", "B23173802S5PL")


# ── (a) the static S5 page ──────────────────────────────────────────────────

class TheStaticPage(unittest.TestCase):
    def test_all_21_floor_cells_exactly_as_the_portal_shows(self):
        rec = record(S5)
        self.assertEqual(rec["record_id"], S5)
        self.assertEqual(rec["record_type"], "Plumbing Permit")
        self.assertEqual(rec["floor_results"], {"PL FLOOR RESULTS": FLOOR_TABLE})
        self.assertEqual(sum(len(c) for c in rec["floor_results"]["PL FLOOR RESULTS"].values()), 21)
        self.assertEqual((rec["proposed_job_start"], rec["expiration"]), ("2026-07-15", "2026-12-03"))
        self.assertEqual(rec["job_description"],
                         "PLUMBING SPECIFICATIONS FILED IN CONJUNCTION WITH GC APPLICATION B01141294-I1")
        self.assertEqual(rec["licensed_firm"], "QUALITY PIPING, INC")
        self.assertEqual(rec["bins"], ["3430621"])
        self.assertIn("Open Space", rec["work_floors"])

    def test_the_placeholder_is_not_a_negative(self):
        """The static page says 'There are no completed inspections' for a
        record that HAS three. From a static page the list is not checked."""
        page = F.fixture(f"record_{S5}.html")
        self.assertIn(D.PLACEHOLDER_COMPLETED, page)
        rec = D.parse_record(page)
        self.assertIs(rec["inspection_list"]["loaded"], False)
        self.assertTrue(rec["inspection_list"]["placeholder_seen"])
        self.assertIn("not checked", rec["inspection_list"]["why"])
        # Fed to the list parser, a static page is still not a checked list.
        lst = D.parse_inspection_list(page)
        self.assertIs(lst["loaded"], False)
        self.assertEqual(lst["completed"], [])

    def test_no_person_name_phone_or_email_is_kept(self):
        for rid in ALL:
            rec = record(rid)
            blob = repr(rec)
            with self.subTest(rid=rid):
                self.assertIsNone(re.search(r"\b\d{3}[\s.-]?\d{3}[\s.-]?\d{4}\b", blob))
                self.assertIsNone(re.search(r"[\w.]+@[\w-]+\.\w+", blob))
        notice = record("ADV-PL-26-014303")["advance_notice"][0]
        # The comment's first line only: the next lines named the person and phone.
        self.assertEqual(notice["request_comment"],
                         "steel sleeve thru foundation wall for combination sanitary Y for storm inside.")

    def test_a_person_is_never_taken_for_the_firm(self):
        page = ("<table role='presentation' id='tbl_licensedps'><tr ><td class='td_child_left'></td>"
                "<td>JOHN DOE <br/>JANE ROE 003052<br/>1 MAIN ST<br/></td></tr></table>")
        self.assertIsNone(D.parse_record(page)["licensed_firm"])

    def test_advance_notices_and_their_results(self):
        old = record("ADV-PL-26-011521")
        self.assertEqual(old["bins"], ["3255362"])
        self.assertEqual(old["request"]["at"], "2026-09-01T08:30")
        self.assertEqual([(n["inspection_type"], n["floor"]) for n in old["advance_notice"]],
                         [("Water and Sanitary-WS-Sanitary Piping-Underground", "001"),
                          ("Storm Drainage-ST-Piping-Underground", "001")])
        cert = record("CERT-ADV-PL-26-010624")
        self.assertEqual(cert["advance_notice_results"], [
            {"id": "3781254", "inspection_type": "Storm Drainage-ST-Piping-Underground", "scheduled": "2026-09-01",
             "floor": "001", "result": "Certified"},
            {"id": "3781253", "inspection_type": "Water and Sanitary-WS-Sanitary Piping-Underground",
             "scheduled": "2026-09-01", "floor": "001", "result": "Certified"}])


# ── (b) the async delta ─────────────────────────────────────────────────────

class TheAsyncDelta(unittest.TestCase):
    def test_the_three_completed_inspections(self):
        lst = listed(S5)
        self.assertIs(lst["loaded"], True)
        self.assertEqual([(c["id"], c["type"], c["result"], c["resulted_at"]) for c in lst["completed"]], [
            ("7681635", "Storm Drainage-ST-Piping-Underground", "Certified", "2026-09-01T08:30"),
            ("7681636", "Water and Sanitary-WS-Sanitary Piping-Underground", "Certified", "2026-09-01T08:30"),
            ("7755632", "PL - Up to 9 Requested Floors", "Pass-Final", "2026-11-05T10:20")])
        self.assertEqual([c["outcome"] for c in lst["completed"]], ["certified", "certified", "pass"])
        self.assertEqual(lst["stated_count"], 3)

    def test_only_the_delta_can_say_a_list_is_empty(self):
        lst = listed("B23173802S5PL")
        self.assertEqual((lst["loaded"], lst["completed"], lst["stated_count"]), (True, [], 0))

    def test_spot_checks(self):
        self.assertEqual([(c["id"], c["spot_check"], c["outcome"], c["resulted_at"])
                          for c in listed("ADV-PL-26-014303")["completed"]],
                         [("7762510", True, "pass", "2026-11-05T16:21")])
        self.assertEqual([(c["id"], c["resulted_at"]) for c in listed("ADV-PL-26-011521")["completed"]],
                         [("7672759", "2026-09-01T09:00")])

    def test_an_error_page_or_redirect_is_not_loaded(self):
        self.assertIs(D.parse_inspection_list(F.fixture_error())["loaded"], False)
        self.assertIs(D.parse_inspection_list(F.delta(("pageRedirect", "", "/Error.aspx")))["loaded"], False)


# ── (c) to evidence ─────────────────────────────────────────────────────────

class ToEvidence(unittest.TestCase):
    def items(self, *rids, comments=None):
        return D.to_evidence(portal_records(*(rids or ALL)), "p588", comments=comments)

    def by_ref(self, items, ref):
        return [i for i in items if i["ref"] == ref]

    def test_7755632_is_a_verified_pass_on_2026_11_05(self):
        items, _cov = self.items(S5)
        [i] = self.by_ref(items, f"{S5}|7755632")
        self.assertEqual((i["kind"], i["claim"], i["on"]), ("verified", "done", date(2026, 11, 5)))
        self.assertIn("not a plumbing sign-off", i["note"])

    def test_the_certified_underground_is_confirmed_not_verified(self):
        items, _cov = self.items(S5)
        for ident in ("7681635", "7681636"):
            [i] = self.by_ref(items, f"{S5}|{ident}")
            with self.subTest(ident=ident):
                self.assertEqual((i["kind"], i["claim"], i["on"], i["node"]),
                                 ("confirmed", "done", date(2026, 9, 1), D.PLUMBING_UNDERGROUND))

    def test_spot_checks_are_verified_and_separate(self):
        items, _cov = self.items("ADV-PL-26-011521", "ADV-PL-26-014303")
        spot = [i for i in items if i["by"] == "DOB (spot check)"]
        self.assertEqual(sorted((i["ref"].split("|")[1], i["on"], i["kind"]) for i in spot), [
            ("7672759", date(2026, 9, 1), "verified"), ("7672759", date(2026, 9, 1), "verified"),
            ("7762510", date(2026, 11, 5), "verified")])
        floor1 = [i for i in spot if i["ref"].startswith("ADV-PL-26-011521")]
        self.assertTrue(all(i["levels"] == ["FLOOR_1"] and i["node"] == D.PLUMBING_UNDERGROUND for i in floor1))

    def test_floor_cells_are_undated_and_placed(self):
        items, cov = self.items(S5)
        cells = [i for i in items if "|PL FLOOR RESULTS|" in i["ref"]]
        self.assertEqual(len(cells), 21)
        self.assertEqual(cov["floor_cells"], 21)
        self.assertTrue(all(i["on"] is None for i in cells))
        self.assertTrue(all("undated" in i["note"] for i in cells))
        rough = [i for i in cells if i["ref"].endswith("ROUGH")]
        self.assertEqual({tuple(i["levels"]) for i in rough},
                         {("FLOOR_1",), ("FLOOR_2",), ("FLOOR_3",), ("FLOOR_4",), ("MEZZANINE",), ("ROOF",)})
        self.assertTrue(all((i["kind"], i["claim"], i["node"]) == ("verified", "done", D.PLUMBING_ROUGH) for i in rough))
        und = [i for i in cells if "UND GRND" in i["ref"] and "|001|" in i["ref"]]
        self.assertEqual({(i["kind"], i["node"]) for i in und}, {("confirmed", D.PLUMBING_UNDERGROUND)})
        [osp] = [i for i in cells if "|OSP|" in i["ref"]]
        self.assertEqual((osp["levels"], osp["space"]), ([], "open space (site)"))

    def test_a_cell_is_dated_only_by_a_link_inference_with_its_basis(self):
        items, cov = self.items(S5, comments={"7755632": COMMENT_7755632})
        cells = [i for i in items if "|PL FLOOR RESULTS|" in i["ref"]]
        linked = [i for i in cells if i["on"] is not None]
        self.assertEqual(cov["linked_cells"], len(linked))
        self.assertEqual(len(linked), 19)        # 18 rough cells + OSP; the 2 certified cells stay undated
        for i in linked:
            self.assertEqual(i["on"], date(2026, 11, 5))
            self.assertTrue(i["basis"].startswith("link inference: inspection 7755632"))
            self.assertIn("the floor table itself carries no date", i["basis"])
        self.assertTrue(all(i["on"] is None for i in cells if "CERTIFIED" in i["quote"]))

    def test_a_failed_result_stays_failed(self):
        page = F.fixture(f"record_{S5}.html").replace(
            "<span class='ACA_SmLabelBolder font11px'>GAS ROUGH:</span></td><td style='width:5px'></td><td "
            "style='vertical-align:top' class='ACA_AlignLeftOrRight'><span class='ACA_SmLabel ACA_SmLabel_FontSize'>"
            "PASSED", "<span class='ACA_SmLabelBolder font11px'>GAS ROUGH:</span></td><td style='width:5px'></td><td "
            "style='vertical-align:top' class='ACA_AlignLeftOrRight'><span class='ACA_SmLabel ACA_SmLabel_FontSize'>"
            "FAILED", 1)
        self.assertIn("FAILED", page)
        delta = F.fixture(f"inspections_{S5}.txt").replace(">Pass-Final <", ">Fail <")
        delta = re.sub(r"^\d+", lambda m: str(int(m.group(0)) - len("Pass-Final") + len("Fail")), delta, count=1)
        recs = [{"record": D.parse_record(page), "inspections": D.parse_inspection_list(delta)}]
        items, _cov = D.to_evidence(recs, "p588", comments={"7755632": COMMENT_7755632})
        [cell] = [i for i in items if i["ref"] == f"{S5}|PL FLOOR RESULTS|001|GAS ROUGH"]
        self.assertEqual((cell["kind"], cell["claim"]), ("verified", "failed"))
        self.assertIsNone(cell["on"])        # a failed cell is never linked to a passing inspection
        [ins] = [i for i in items if i["ref"] == f"{S5}|7755632"]
        self.assertEqual((ins["kind"], ins["claim"]), ("verified", "failed"))

    def test_nothing_claims_a_signoff_or_another_trade(self):
        items, _cov = self.items(comments={"7755632": COMMENT_7755632})
        self.assertTrue(items)
        for i in items:
            with self.subTest(ref=i["ref"]):
                self.assertEqual(i["source"], D.SOURCE)
                self.assertIn(i["node"], (None,) + D.PLUMBING_NODES)
                self.assertFalse(DS.is_signed_off(i["quote"]))
                self.assertIn(D.NOT_SIGNOFF, i["note"])
                self.assertIn(i["kind"], ("verified", "confirmed"))


# ── (d) every BIN of the site ───────────────────────────────────────────────

class EveryBin(unittest.TestCase):
    def test_records_split_across_two_bins_are_deduped_and_the_old_bin_notice_is_found(self):
        res = P.check_bins([F.NEW_BIN, F.OLD_BIN], F.portal())
        ids = [r["record_id"] for r in res["records"]]
        self.assertEqual(sorted(ids), sorted(F.RECORDS))
        self.assertEqual(len(ids), len(set(ids)))
        by = {r["record_id"]: r for r in res["records"]}
        self.assertEqual(sorted(by[S5]["bins_found"]), sorted([F.NEW_BIN, F.OLD_BIN]))
        self.assertEqual(by["ADV-PL-26-011521"]["bins_found"], [F.OLD_BIN])
        self.assertEqual(res["state"], "checked")
        # BIN 3430621 has four records: two result pages were read.
        self.assertEqual(res["searched"][F.NEW_BIN], {"pages": 2, "stated_total": 4, "found": 4})

    def test_a_short_search_read_is_partial_not_checked(self):
        """Live on 2026-11-10 the first pager read 10 of 15 records and the
        result still said 'checked'. Fewer rows than the portal states is a
        partial read: the rest are unread, not absent."""
        res = P.check_bins([F.NEW_BIN], F.portal(one_page=True))
        self.assertEqual(res["searched"][F.NEW_BIN]["found"], 3)
        self.assertEqual(res["state"], "partial")
        self.assertIn({"what": f"BIN {F.NEW_BIN} search", "why": "read 3 of the 4 records the portal lists"},
                      res["unreachable"])
        self.assertEqual(P.coverage_entry(res)["state"], SC.NOT_LOADED)

    def test_the_live_pager_markup_is_read(self):
        page = F.search_delta(F.NEW_BIN, 1)
        self.assertEqual(P.page_links(page), [(2, "ctl00$PlaceHolderMain$dgvPermitList$gdvPermitList$ctl13$ctl03", "")])
        self.assertEqual(P.stated_total(page), 4)
        self.assertEqual(P.grid_panel(page, "x"), "ctl00$PlaceHolderMain$dgvPermitList$updatePanel")

    def test_one_bin_alone_misses_the_old_bin_notice(self):
        res = P.check_bins([F.NEW_BIN], F.portal())
        self.assertNotIn("ADV-PL-26-011521", [r["record_id"] for r in res["records"]])

    def test_site_bins_union_the_project_bins_and_the_lot(self):
        project = {"nyc_bin": "3255362", "additional_bins": ["1000000"]}
        rows = [{"record_type": "permit", "bin": "3255362", "job_number": "B01141294-S5"},
                {"record_type": "permit", "bin": "3430621", "job_number": "B01141294-S4"},
                {"record_type": "permit", "bin": "3999999", "job_number": "B09999999-I1"}]
        self.assertEqual(P.site_bins(project, rows), ["3255362", "3430621"])
        self.assertEqual(P.site_bins({"nyc_bin": "3430621", "additional_bins": ["3255362"]}), ["3430621", "3255362"])

    def test_an_error_page_or_a_challenge_is_unreachable_never_none(self):
        res = P.check_bins([F.NEW_BIN], F.portal(challenge=True))
        self.assertEqual(res["state"], "unreachable")
        self.assertIn("Cloudflare challenge", res["why"])
        self.assertEqual(SC.UNREACHABLE, P.coverage_entry(res)["state"])
        res = P.check_bins([F.NEW_BIN, F.OLD_BIN], F.portal(error_on=("B01141294S5PL",)))
        self.assertEqual(res["state"], "partial")
        self.assertTrue(any("technical difficulties" in u["why"] for u in res["unreachable"]))
        self.assertNotIn(S5, [r["record_id"] for r in res["records"]])

    def test_the_flag_is_off_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(P.FLAG, None)
            self.assertFalse(P.enabled())
        with patch.dict(os.environ, {P.FLAG: "true"}):
            self.assertTrue(P.enabled())


# ── (e) the coverage contract ───────────────────────────────────────────────

class TheCoverageContract(unittest.TestCase):
    def test_none_only_when_every_source_was_checked(self):
        everything = [SC.entry(SC.DOB_OPEN_DATA, SC.CHECKED, as_of="2026-11-10T03:00"),
                      SC.entry(SC.DOB_NOW_INSPECTIONS, SC.CHECKED, as_of="2026-11-10T13:30")]
        said = SC.absence("inspections", everything)
        self.assertTrue(said.startswith("No inspections in any source checked:"))
        self.assertIn("DOB NOW: Inspections", said)
        self.assertIn("read 2026-11-10 13:30", said)

    def test_an_unchecked_source_is_named_and_none_is_not_said(self):
        partial = [SC.entry(SC.DOB_OPEN_DATA, SC.CHECKED, as_of="2026-11-10T03:00"),
                   SC.entry(SC.DOB_NOW_INSPECTIONS, SC.NOT_LOADED, why="the inspection list did not load")]
        said = SC.absence("inspections", partial)
        self.assertIn("Not checked: DOB NOW: Inspections", said)
        self.assertIn("not a finding that there are no inspections", said)
        self.assertFalse(SC.complete(partial))
        self.assertFalse(SC.complete([]))

    def test_bare_absence_is_caught(self):
        self.assertIsNotNone(SC.bare_absence("DOB NOW inspection results are not in public data."))
        self.assertIsNotNone(SC.bare_absence("No inspections on record."))
        self.assertIsNone(SC.bare_absence(SC.absence("inspections", [
            SC.entry(SC.DOB_NOW_INSPECTIONS, SC.NOT_CHECKED, why="reader off")])))


class TheProgressAnswer(unittest.TestCase):
    """project_status: an inspection 'with no record' names what was not checked,
    and the portal's rough passes reach the floors' plumbing rough gate."""

    def test_no_record_is_said_with_the_unchecked_source(self):
        from lib import project_progress as PPG
        model = PPG.build([], today=date(2026, 11, 10), project={"building_stories": 4}, job="588")
        self.assertEqual([s["key"] for s in SC.unchecked(model["inspection_sources"])], [SC.DOB_NOW_INSPECTIONS])
        txt = PPG.as_text(model, "overall")
        self.assertIsNone(SC.bare_absence(txt))
        self.assertRegex(txt, r"Not checked, so inspection results there are unknown \(not absent\): DOB NOW: Inspections")
        model["by_level"]["FLOOR_1"]["bottleneck"]["gates"] = [{"node": "g", "label": "g", "bucket": "unknown",
                                                                 "conditional": False}]
        self.assertRegex(PPG._bottleneck_words(model, "FLOOR_1"),
                         r"1 inspection\(s\) with no record in the sources read \(not checked: DOB NOW: Inspections\)")

    def test_the_portal_rough_passes_reach_the_gate_on_each_floor(self):
        from lib import project_progress as PPG
        items, _cov = D.to_evidence(portal_records(S5), "p588", comments={"7755632": COMMENT_7755632})
        checked = [SC.entry(SC.DOB_NOW_INSPECTIONS, SC.CHECKED, as_of="2026-11-10T13:30")]
        model = PPG.build(items, today=date(2026, 11, 10), project={"building_stories": 4}, job="588",
                          inspection_sources=checked)
        for lv in ("FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4"):
            with self.subTest(level=lv):
                self.assertEqual(model["cells"][(lv, D.PLUMBING_ROUGH)]["status"], "done_verified")


class TheAssistantsAnswer(unittest.TestCase):
    """_handle_dob_status, the tool the assistant calls for 'what inspections
    happened'."""

    def _status(self, *, flag: bool, **fake):
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
                patch.object(server, "_dob_now_portal_reader", lambda: F.portal(**fake), create=True):
            if not flag:
                os.environ.pop(P.FLAG, None)
            out = _run(server._handle_dob_status(THOMAS, company_id=CO_A))
        P.forget()
        return out

    def test_with_the_reader_off_the_answer_names_the_unchecked_source(self):
        out = self._status(flag=False)
        self.assertIsNone(SC.bare_absence(out), out)
        self.assertRegex(out, r"Not checked, so inspections there are unknown \(not absent\): [^\n]*"
                              r"DOB NOW: Inspections \(public portal[^\n]*\(not checked: [^)]*DOB_NOW_PORTAL_ENABLED")

    def test_a_list_that_did_not_load_is_said_not_checked(self):
        out = self._status(flag=True, static_only=True)
        self.assertIsNone(SC.bare_absence(out), out)
        self.assertRegex(out, r"DOB NOW: Inspections \(public portal[^\n]*\(not loaded: ")
        self.assertRegex(out, r"inspection list NOT checked")

    # ── (f) the real-world regression ───────────────────────────────────────
    def test_what_inspections_happened_on_588(self):
        out = self._status(flag=True)
        self.assertIsNone(SC.bare_absence(out), out)
        self.assertRegex(out, r"PL - Up to 9 Requested Floors \(7755632\): Pass-Final — DOB inspection, resulted "
                              r"2026-11-05 10:20")
        self.assertRegex(out, r"Storm Drainage-ST-Piping-Underground \(7681635\): Certified — licensed master plumber "
                              r"self-certification, not a DOB inspection, resulted 2026-09-01 08:30")
        self.assertRegex(out, r"ADV-PL-26-011521 \([^)]*found under BIN 3255362 only\)")
        self.assertRegex(out, r"Spot Check \(7672759\): Spot Check - Pass-Final — DOB spot check, resulted 2026-09-01")
        self.assertRegex(out, r"PL FLOOR RESULTS \(the table carries no dates\): Floor 1: WS UND GRND certified")
        self.assertRegex(out, r"Sources for inspections — checked: [^\n]*DOB NOW: Inspections \(public portal[^\n]*"
                              r"\(read 2026-11-10 13:30 UTC\)")
        self.assertRegex(out, r"none of these is a plumbing sign-off|None of these is a plumbing sign-off")


if __name__ == "__main__":
    unittest.main()
