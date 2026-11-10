"""lib/project_progress.py: one status of the whole building from evidence items.

The rules held here, each against the 588-like fixture (tests/progress_588_fixture):
  * no percent anywhere unless a source states it, and then with that source;
  * unknown (no items) is never worded or counted as not done;
  * done needs attested or stronger; a photo or a log row never says done;
  * estimates never decide a status, never support one, never get counted;
  * "open on the record" names no cause;
  * the server's tool and route read the same build, scoped to the company.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from lib import evidence as E  # noqa: E402
from lib import project_progress as PG  # noqa: E402
from tests import progress_588_fixture as FX  # noqa: E402

PCT = re.compile(r"\d+(?:\.\d+)?\s*%")
STATED_PCT = re.compile(r"\b(?:schedule file|requisition|[\w-]+) states \d+(?:\.\d+)?%")
NOT_DONE_WORDS = re.compile(r"\bnot done\b|\bremaining\b|\bincomplete\b|\boutstanding\b|\bto be done\b|\bunfinished\b|"
                            r"\bnot (?:yet )?(?:started|finished|complete)\b", re.I)
CAUSE_WORDS = re.compile(r"\bbecause\b|\bdue to\b|\bcaus\w*\b|\bholding\b|\bholds? up\b|\bheld up\b|\bblock\w*\b|"
                         r"\bdelay\w*\b|\bwaiting (?:on|for)\b|\breason\b|\bbehind\b|\blate\b", re.I)


def _model(items=None, **kw):
    kw.setdefault("project", FX.PROJECT)
    kw.setdefault("job", "588")
    return PG.build(FX.items() if items is None else items, today=FX.TODAY, **kw)


def _all_text(m):
    texts = [PG.as_text(m, "overall")]
    texts += [PG.as_text(m, "sub", s) for s in m["subs"]]
    texts += [PG.as_text(m, "floor", lv["label"]) for lv in m["frame"]["levels"]]
    return texts


class Levels(unittest.TestCase):

    def test_each_level_says_where_it_came_from(self):
        extra = [E.item("reported", "in_progress", source="logbooks", ref="x", project_id="p", node="framing",
                        levels=["MEZZANINE"], on=FX.TODAY)]
        lv = PG.job_levels(FX.PROJECT, ["FLOOR_1", "BULKHEAD"], extra)
        got = {x["level"]: x["sources"] for x in lv}
        self.assertEqual([x["level"] for x in lv],
                         ["CELLAR", "FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4", "MEZZANINE", "ROOF", "BULKHEAD"])
        self.assertEqual(got["FLOOR_1"], ["project_fields", "plan_sheets"])
        self.assertEqual(got["MEZZANINE"], ["evidence"])
        self.assertEqual(got["BULKHEAD"], ["plan_sheets"])

    def test_a_field_nobody_answered_adds_nothing_and_asserts_nothing(self):
        lv = PG.job_levels({"building_stories": None, "has_cellar": None, "has_roof_bulkhead": False})
        self.assertEqual(lv, [])

    def test_an_estimate_does_not_name_a_level(self):
        est = E.item("estimate", "done", source="forecast", ref="f", project_id="p", node="framing",
                     levels=["FLOOR_9"], basis="b")
        self.assertEqual(PG.job_levels({}, (), [est]), [])

    def test_the_overall_text_names_the_frame_and_its_sources(self):
        t = PG.as_text(_model(plan_tokens=["ROOF"]), "overall")
        self.assertIn("6 level(s) x 20 step(s) = 120 level-and-work cells", t)
        self.assertIn("Levels from project fields: Cellar, Floor 1, Floor 2, Floor 3, Floor 4, Roof; plan sheets: Roof", t)
        self.assertIn("not this job's own schedule", t)


class TheFrame(unittest.TestCase):

    def test_every_level_has_every_step(self):
        m = _model()
        self.assertEqual(len(m["cells"]), len(m["frame"]["levels"]) * len(m["frame"]["steps"]))
        self.assertEqual(sum(m["counts"].values()), len(m["cells"]))

    def test_work_nodes_absent_is_tolerated_and_said(self):
        self.assertEqual(_model()["frame"]["work_nodes"], "absent")

    def test_site_steps_another_lane_adds_come_in_their_order(self):
        extra = [{"id": "superstructure", "label": "superstructure", "gate": False, "conditional": False,
                  "trade": "concrete", "after": [], "source": "work_nodes"}]
        seq = PG.steps(None, extra)
        ids = [s["id"] for s in seq]
        self.assertEqual(ids[0], "superstructure")
        self.assertIn("framing", ids)
        self.assertLess(ids.index("framing"), ids.index("drywall"))


class Cells(unittest.TestCase):

    def test_status_is_evidence_status_of_the_cells_items(self):
        m = _model()
        for (lv, n), c in m["cells"].items():
            mine = [i for i in FX.items() if i["node"] == n and lv in i["levels"]]
            self.assertEqual(c["status"], E.status(mine), (lv, n))

    def test_supporting_items_are_strongest_first(self):
        c = _model()["cells"][("FLOOR_1", "framing")]
        self.assertEqual([i["kind"] for i in c["items"]][0], "attested")
        self.assertEqual([i["ref"] for i in c["items"]], ["wa-1009", "L1006:0", "L0922:0", "L0915:0"])
        self.assertEqual((c["first"], c["last"]), (date(2026, 9, 15), date(2026, 10, 9)))
        self.assertEqual(c["subs"], ["Arkon Builders"])

    def test_a_cell_with_no_items_is_unknown(self):
        c = _model()["cells"][("ROOF", "framing")]
        self.assertEqual((c["status"], c["bucket"], c["items"]), ("unknown", "unknown", []))

    def test_done_needs_attested_or_stronger(self):
        on = FX.TODAY
        for kind in ("reported", "observed"):
            with self.subTest(kind=kind):
                i = E.item(kind, "done", source="s", ref="r", project_id="p", node="framing", levels=["FLOOR_1"], on=on)
                c = PG.cell([i], "FLOOR_1", "framing", FX.TODAY)
                self.assertNotEqual(c["bucket"], "done")
        for kind in ("attested", "confirmed", "verified"):
            with self.subTest(kind=kind):
                i = E.item(kind, "done", source="s", ref="r", project_id="p", node="framing", levels=["FLOOR_1"], on=on)
                self.assertEqual(PG.cell([i], "FLOOR_1", "framing", FX.TODAY)["bucket"], "done")

    def test_underway_is_recent_reported_or_observed(self):
        m = _model()
        self.assertEqual(m["cells"][("FLOOR_2", "drywall")]["bucket"], "underway")      # Nov 6
        self.assertEqual(m["cells"][("FLOOR_4", "rough_duct")]["bucket"], "underway")   # photo, Nov 7
        self.assertEqual(m["cells"][("FLOOR_3", "framing")]["bucket"], "not_shown_done")  # last Oct 6

    def test_a_failure_after_a_pass_is_failed(self):
        self.assertEqual(_model()["cells"][("FLOOR_3", "gate_plumbing_rough")]["status"], "failed_attested")

    def test_counts(self):
        m = _model()
        self.assertEqual(m["counts"], {"done": 4, "underway": 5, "not_shown_done": 12, "failed": 1, "unknown": 98})


class NoPercentWithoutASource(unittest.TestCase):

    def test_no_percent_anywhere_on_the_fixture(self):
        m = _model()
        for t in _all_text(m):
            self.assertIsNone(PCT.search(t), t)
        self.assertNotIn("percent", m)
        for c in m["cells"].values():
            self.assertEqual(c["stated_percents"], [])
            self.assertIsNone(c["installed"])

    def test_a_stated_percent_is_shown_with_its_source(self):
        m = _model(schedule=FX.SCHEDULE)
        t = PG.as_text(m, "floor", "2")
        self.assertIn("schedule file states 40%", t)
        for t in _all_text(m):
            for hit in PCT.finditer(t):
                window = t[max(0, hit.start() - 40):hit.end()]
                self.assertRegex(window, STATED_PCT, t)

    def test_design_scope_beside_status_and_installed_unknown(self):
        design = [{"node": "drywall", "level": "FLOOR_2", "qty": 1840, "unit": "sq ft", "item": "gypsum board",
                   "source": "takeoff, A-102"}]
        m = _model(design=design)
        c = m["cells"][("FLOOR_2", "drywall")]
        self.assertEqual(c["design_scope"][0]["qty"], 1840)
        self.assertIsNone(c["installed"])
        t = PG.as_text(m, "floor", "2")
        self.assertIn("design scope 1840 sq ft gypsum board (takeoff, A-102); installed quantity not stated by any source", t)
        self.assertIsNone(PCT.search(t))

    def test_takeoff_lines_need_a_mapping_the_caller_gives(self):
        from lib.plan_takeoff_export import Line
        ln = Line("Doors & windows", "DOOR", "type F", "Floor", "THIRD FLOOR PLAN", 12, "ea", "filed", "A-103", "", "", "")
        self.assertEqual(PG.design_from_takeoff([ln], {}), [])
        got = PG.design_from_takeoff([ln], {"Doors & windows": "finishes"})
        self.assertEqual(got, [{"node": "finishes", "level": "FLOOR_3", "qty": 12, "unit": "ea", "item": "DOOR type F",
                                "source": "takeoff, A-103"}])


class UnknownIsNotNotDone(unittest.TestCase):

    def test_no_text_calls_anything_not_done(self):
        for t in _all_text(_model()):
            self.assertIsNone(NOT_DONE_WORDS.search(t), t)

    def test_unknown_is_said_as_no_record(self):
        t = PG.as_text(_model(), "floor", "roof")
        self.assertIn("No record (unknown means nothing is on record, either way): framing", t)
        self.assertIn("- Roof: no record (unknown means nothing is on record, either way).", PG.as_text(_model(), "overall"))

    def test_unknown_is_its_own_bucket_never_folded_into_not_shown_done(self):
        m = _model()
        for c in m["cells"].values():
            self.assertEqual(c["bucket"] == "unknown", c["item_count"] == 0, (c["level"], c["node"]))


class EstimatesAreNeverFacts(unittest.TestCase):

    def test_an_estimate_changes_no_status_count_or_support(self):
        with_est, without = _model(), _model([i for i in FX.items() if i["kind"] != "estimate"])
        self.assertEqual(with_est["counts"], without["counts"])
        c = with_est["cells"][("FLOOR_3", "drywall")]
        self.assertEqual((c["status"], c["bucket"], c["items"]), ("unknown", "unknown", []))
        self.assertEqual(c["estimates"][0]["label"], "estimate, not a fact")
        for cc in with_est["cells"].values():
            self.assertFalse([i for i in cc["items"] if i["kind"] == "estimate"])
        self.assertEqual(with_est["estimates"], 1)

    def test_an_estimate_is_labelled_where_it_is_shown(self):
        t = PG.as_text(_model(), "floor", "3")
        self.assertIn("(drywall: estimate, not a fact, basis: crew moves between floors)", t)
        self.assertNotRegex(t, r"\bDec 1\b")    # the estimate's date is never printed as a fact


class Bottlenecks(unittest.TestCase):

    def test_the_earliest_open_work_per_level(self):
        m = _model()
        self.assertEqual(m["by_level"]["FLOOR_1"]["bottleneck"]["earliest_open"], "rough_dwv")
        self.assertEqual(m["by_level"]["FLOOR_3"]["bottleneck"]["earliest_open"], "framing")
        gates = {g["node"]: g["bucket"] for g in m["by_level"]["FLOOR_3"]["bottleneck"]["gates"]}
        self.assertEqual(gates["gate_plumbing_rough"], "failed")
        self.assertNotIn("gate_plumbing_rough", {g["node"] for g in m["by_level"]["FLOOR_1"]["bottleneck"]["gates"]})

    def test_the_words_name_no_cause(self):
        m = _model()
        for lv in m["frame"]["levels"]:
            w = PG._bottleneck_words(m, lv["level"])
            self.assertIsNone(CAUSE_WORDS.search(w), w)
        for t in _all_text(m):
            # The closing line is the instruction to the model ("no cause"), not a statement.
            said = t.replace(PG.GUARD, "")
            self.assertIsNone(CAUSE_WORDS.search(said), said)

    def test_the_words_say_open_on_the_record(self):
        self.assertIn("Open on the record: framing, the first step of the standard sequence, has no done record",
                      PG.as_text(_model(), "floor", "3"))


class BySub(unittest.TestCase):

    def test_arkon(self):
        s = _model()["subs"]["Arkon Builders"]
        self.assertEqual(s["levels"], ["FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4"])
        self.assertEqual(s["nodes"], ["framing", "drywall"])
        self.assertEqual((s["first"], s["last"]), (date(2026, 9, 15), date(2026, 11, 6)))
        self.assertEqual(s["presence_days"], 10)
        self.assertEqual([(n["level"], n["node"]) for n in s["next"]][:3],
                         [("CELLAR", "framing"), ("FLOOR_1", "drywall"), ("FLOOR_2", "drywall")])

    def test_presence_only(self):
        m = _model()
        s = m["subs"]["Slate Windows"]
        self.assertEqual((s["work"], s["presence_days"], s["next"]), ([], 5, []))
        self.assertIn("Present on 5 day(s) (gate check-ins), Oct 20 to Oct 24.", PG.as_text(m, "sub", "slate"))

    def test_names_match_by_whole_word(self):
        m = _model()
        self.assertEqual(PG.find_subs(m, "Arkon"), ["Arkon Builders"])
        self.assertEqual(PG.find_subs(m, "Ark"), [])
        self.assertEqual(PG.find_subs(m, "a1"), ["A1"])
        self.assertIn("No sub named", PG.as_text(m, "sub", "Ark"))


class Conflicts(unittest.TestCase):

    def test_the_three_kinds_on_the_fixture(self):
        got = {(c["type"], c["level"], c["node"]) for c in _model()["conflicts"]}
        self.assertEqual(got, {("done_then_failed", "FLOOR_3", "gate_plumbing_rough"),
                               ("before_inspection_record", "FLOOR_2", "drywall"),
                               ("photo_without_log", "FLOOR_4", "rough_duct")})

    def test_a_logged_crew_that_day_is_no_conflict(self):
        more = FX.items() + [FX.rep("BreezCo", "rough_duct", ["FLOOR_4"], FX.d(11, 7), "L1107:3", "Duct")]
        self.assertNotIn("photo_without_log", {c["type"] for c in _model(more)["conflicts"]})

    def test_a_gate_record_first_clears_the_before_inspection_conflict(self):
        early = [FX.said("done", g, ["FLOOR_2"], FX.d(11, 1), f"wa-{g}", "passed on 2")
                 for g in ("gate_plumbing_rough", "gate_sprinkler_hydro", "gate_electrical_rough", "gate_firestopping",
                           "gate_nycecc_insulation")]
        self.assertNotIn("before_inspection_record", {c["type"] for c in _model(FX.items() + early)["conflicts"]})


class Timeline(unittest.TestCase):

    def test_status_changes_by_week_with_their_evidence(self):
        tl = {w["week"]: w["changes"] for w in _model()["timeline"]}
        wk = tl[date(2026, 10, 5)]
        f1 = next(c for c in wk if c["level"] == "FLOOR_1" and c["node"] == "framing")
        self.assertEqual((f1["from"], f1["to"]), ("reported", "done_attested"))
        self.assertEqual(f1["refs"][0], "wa-1009")
        f3 = next(c for c in tl[date(2026, 11, 2)] if c["node"] == "gate_plumbing_rough")
        self.assertEqual((f3["from"], f3["to"]), ("done_attested", "failed_attested"))

    def test_no_estimate_moves_the_timeline(self):
        refs = {r for w in _model()["timeline"] for c in w["changes"] for r in c["refs"]}
        self.assertNotIn("fc-1", refs)


class Json(unittest.TestCase):

    def test_it_serialises(self):
        out = PG.to_json(_model(schedule=FX.SCHEDULE))
        json.dumps(out)
        self.assertIn("FLOOR_1|framing", out["cells"])


# ── THE SERVER ──────────────────────────────────────────────────────────────

import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from lib import dm_roles  # noqa: E402
from tests.test_dm_brain import _Brain  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx  # noqa: E402


def _log(_id, day, *rows):
    return {"_id": _id, "log_type": "daily_jobsite", "project_id": THOMAS, "company_id": CO_A, "date": day,
            "status": "submitted", "data": {"activities": [dict(r) for r in rows]}}


class ThroughTheServer(_Brain):

    def setUp(self):
        super().setUp()
        today = datetime.now(timezone.utc).date()
        day = today.isoformat()
        self.db.logbooks.rows += [
            _log("L1", day, {"company": "Quality Plumbing", "trade": "Plumber", "work_description": "Domestic water rough",
                             "work_locations": "floors 1-4"},
                 {"company": "Arkon Builders", "trade": "Carpentry", "work_description": "Framing", "work_locations": "floor 3"})]
        self.db.checkins.rows += [{"_id": "ck1", "project_id": THOMAS, "worker_company": "Slate Windows",
                                   "check_in_time": datetime.now(timezone.utc)}]
        self.db[server.INSPECTION_REPORTS].rows += [{
            "_id": "ir1", "project_id": THOMAS, "company_id": CO_A, "gate": "gate_plumbing_rough", "levels": ["FLOOR_3"],
            "result": "passed", "status": "attested", "reporter_name": "Ada Admin", "quote": "plumbing rough passed on 3",
            "inspected_on": day, "created_at": datetime.now(timezone.utc)}]

    def _status(self, args, cid=CO_A):
        with _Ctx(db=self.db):
            return asyncio.run(server._dm_project_status({"ident": {"company_id": cid}}, {"id": THOMAS, "label": "588"}, args))

    def test_overall_reads_the_logs_check_ins_and_inspection_reports(self):
        out = self._status({"scope": "overall"})
        self.assertIn("588, from the record as of", out)
        self.assertIn("level-and-work cells", out)
        self.assertIsNone(PCT.search(out))

    def test_by_sub_and_by_floor(self):
        out = self._status({"scope": "sub", "name": "Quality"})
        self.assertIn("Quality Plumbing: records of domestic water rough on Floor 1, Floor 2, Floor 3, Floor 4", out)
        out = self._status({"scope": "sub", "name": "slate windows"})
        self.assertIn("Present on 1 day(s) (gate check-ins)", out)
        out = self._status({"scope": "floor", "name": "3"})
        self.assertIn("plumbing rough inspection: done, attested by Ada Admin via inspection reports", out)

    def test_another_companys_job_is_refused(self):
        self.assertEqual(self._status({"scope": "overall"}, cid="c0ffee000000000000000099"), server.wa_security.BOT_SCOPE_REFUSAL)

    def test_the_tool_is_registered_and_open_to_field_roles(self):
        names = {t["function"]["name"] for t in server._dm_brain_tools()}
        self.assertIn("project_status", names)
        self.assertIn("project_status", server._DM_BRAIN_ONE_JOB)
        self.assertIn("project_status", dm_roles.FIELD_TOOLS)
        for role in ("cp", "superintendent", "pm", "admin"):
            self.assertIsNone(dm_roles.tool_refusal(role, "project_status", {"scope": "overall"}))

    def test_the_route_is_read_only_and_gated(self):
        routes = [r for r in server.app.routes if getattr(r, "path", "") == "/api/projects/{project_id}/progress"]
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].methods, {"GET"})
        deps = {d.call for d in routes[0].dependant.dependencies}
        self.assertTrue({server.require_approved, server.require_project_access} <= deps)

    def test_the_route_is_company_scoped(self):
        with _Ctx(db=self.db):
            out = asyncio.run(server.get_project_progress(THOMAS, {"company_id": CO_A, "role": "admin"}))
            self.assertEqual(out["project_id"], THOMAS)
            self.assertEqual(out["cells"]["FLOOR_3|gate_plumbing_rough"]["status"], "done_attested")
            with self.assertRaises(HTTPException) as e:
                asyncio.run(server.get_project_progress(THOMAS, {"company_id": "c0ffee000000000000000099", "role": "admin"}))
        self.assertEqual(e.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
