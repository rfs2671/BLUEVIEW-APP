"""A SCHEDULE'S OWN LOGIC, AND WHAT MAY BE SAID FROM IT.

Predecessors used to be thrown away at import. These tests hold four lines:
a link is the file's or it is not there; a file with no logic is unknown, not
"no dependencies"; the standard sequence is never called the job's schedule; and
a PROPOSED sequence stays PROPOSED and out of project_schedules.

Fixtures are built here. No real schedule file exists in this repo: what real
P6 and MS Project exports contain beyond these fixtures is not asserted.
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_dm_brain import FakeLLM, _Brain, last_tool_results, resp, text, use  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx  # noqa: E402
from tests.test_work_state import _act, _holds, _log  # noqa: E402

import server  # noqa: E402
from app.scheduling import engine  # noqa: E402
from lib import progress_plan as PP  # noqa: E402
from lib import schedule_import as S  # noqa: E402
from lib import work_state as W  # noqa: E402

TODAY = date(2026, 11, 9)


def _by_id(doc):
    return {a["id"]: a for a in doc["activities"]}


# ── IMPORT ─────────────────────────────────────────────────────────────────

_TASK_F = ["task_id", "proj_id", "wbs_id", "clndr_id", "task_code", "task_name", "task_type", "complete_pct_type",
           "phys_complete_pct", "target_drtn_hr_cnt", "target_start_date", "target_end_date", "early_start_date",
           "early_end_date", "act_start_date", "act_end_date"]
_PRED_F = ["task_pred_id", "task_id", "pred_task_id", "proj_id", "pred_proj_id", "pred_type", "lag_hr_cnt"]


def _xer(tasks, preds=None, hours="8"):
    def table(name, fields, rows):
        return "\n".join([f"%T\t{name}", "%F\t" + "\t".join(fields)] + ["%R\t" + "\t".join(r) for r in rows])
    parts = ["ERMHDR\t20.12\t2026-10-05\tProject\tadmin\tdb\tProject Management\tUSD",
             table("PROJECT", ["proj_id", "proj_short_name", "last_recalc_date", "plan_start_date"],
                   [["1", "TWR", "2026-10-05 08:00", "2026-01-05 08:00"]]),
             table("CALENDAR", ["clndr_id", "day_hr_cnt"], [["9", hours]]),
             table("PROJWBS", ["wbs_id", "proj_id", "parent_wbs_id", "wbs_short_name", "wbs_name", "seq_num"],
                   [["10", "1", "", "TWR", "Tower 12", "1"]]),
             table("TASK", _TASK_F, tasks)]
    if preds is not None:
        parts.append(table("TASKPRED", _PRED_F, preds))
    parts.append("%E")
    return "\n".join(parts).encode("utf-8")


def _t(internal, code, name):
    base = dict.fromkeys(_TASK_F, "")
    base.update(task_id=internal, proj_id="1", wbs_id="10", clndr_id="9", task_code=code, task_name=name,
                task_type="TT_Task", complete_pct_type="CP_Phys", target_start_date="2026-02-02 08:00",
                target_end_date="2026-03-02 17:00")
    return [base[f] for f in _TASK_F]


def _p(succ, pred, kind="PR_FS", lag="0", pred_proj="1"):
    return ["p" + succ + pred, succ, pred, "1", pred_proj, kind, lag]


class XerLogic(unittest.TestCase):

    TASKS = [_t("901", "A100", "Frame Floor 3"), _t("902", "A200", "Drywall Floor 3")]

    def test_an_internal_task_id_becomes_the_activity_code(self):
        doc = S.parse_schedule("a.xer", _xer(self.TASKS, [_p("902", "901", "PR_SS", "16")]))
        self.assertEqual(_by_id(doc)["A200"]["predecessors"], [{"id": "A100", "type": "SS", "lag": 2.0, "lag_unit": "days"}])

    def test_the_lag_is_on_the_activitys_own_calendar(self):
        doc = S.parse_schedule("a.xer", _xer(self.TASKS, [_p("902", "901", "PR_FS", "20")], hours="10"))
        self.assertEqual(_by_id(doc)["A200"]["predecessors"][0]["lag"], 2.0)

    def test_an_activity_with_no_links_in_a_file_with_logic_is_listed_as_none(self):
        doc = S.parse_schedule("a.xer", _xer(self.TASKS, [_p("902", "901")]))
        self.assertEqual(_by_id(doc)["A100"]["predecessors"], [])

    def test_no_table_is_unknown_not_empty(self):
        doc = S.parse_schedule("a.xer", _xer(self.TASKS))
        self.assertIsNone(_by_id(doc)["A200"]["predecessors"])

    def test_a_link_out_of_the_file_is_counted_never_guessed(self):
        doc = S.parse_schedule("a.xer", _xer(self.TASKS, [_p("902", "901"), _p("902", "555", pred_proj="2")]))
        a = _by_id(doc)["A200"]
        self.assertEqual([p["id"] for p in a["predecessors"]], ["A100"])
        self.assertEqual(a["predecessors_unresolved"], 1)
        self.assertTrue(any("1 predecessor links could not be matched" in w for w in doc["warnings"]))

    def test_a_task_of_another_project_is_no_link_of_this_one(self):
        doc = S.parse_schedule("a.xer", _xer(self.TASKS, [_p("902", "901"), _p("777", "901")]))
        self.assertFalse(any("predecessor links" in w for w in doc["warnings"]))


_NS = "http://schemas.microsoft.com/project"


def _msp(tasks):
    return (f'<?xml version="1.0" encoding="UTF-8"?><Project xmlns="{_NS}"><Name>t.xml</Name><MinutesPerDay>480</MinutesPerDay>'
            f"<StatusDate>2026-10-05T17:00:00</StatusDate><Tasks>{tasks}</Tasks></Project>").encode()


def _mt(uid, name, links=""):
    return (f"<Task><UID>{uid}</UID><ID>{uid}</ID><Name>{name}</Name><OutlineLevel>1</OutlineLevel>"
            f"<Start>2026-02-02T08:00:00</Start><Finish>2026-02-13T17:00:00</Finish>{links}</Task>")


def _ml(uid, kind="1", lag="0", fmt="7", extra=""):
    return (f"<PredecessorLink><PredecessorUID>{uid}</PredecessorUID><Type>{kind}</Type><LinkLag>{lag}</LinkLag>"
            f"<LagFormat>{fmt}</LagFormat>{extra}</PredecessorLink>")


class MspLogic(unittest.TestCase):

    def _b(self, link):
        doc = S.parse_schedule("a.xml", _msp(_mt(1, "A") + _mt(2, "B", link)))
        return _by_id(doc)["2"], doc

    def test_every_link_type_is_kept(self):
        for code, want in (("0", "FF"), ("1", "FS"), ("2", "SF"), ("3", "SS")):
            with self.subTest(code=code):
                self.assertEqual(self._b(_ml(1, code))[0]["predecessors"][0]["type"], want)

    def test_link_lag_is_tenths_of_a_minute(self):
        self.assertEqual(self._b(_ml(1, lag="4800"))[0]["predecessors"][0],
                         {"id": "1", "type": "FS", "lag": 1.0, "lag_unit": "days"})

    def test_elapsed_lag_is_not_called_working_days(self):
        link = self._b(_ml(1, lag="43200", fmt="8"))[0]["predecessors"][0]
        self.assertEqual((link["lag"], link["lag_unit"]), (3.0, "edays"))

    def test_a_percent_lag_is_not_turned_into_days(self):
        link = self._b(_ml(1, lag="5000", fmt="19"))[0]["predecessors"][0]
        self.assertEqual((link["lag"], link["lag_unit"]), (None, "percent"))

    def test_a_missing_type_stays_missing(self):
        el = "<PredecessorLink><PredecessorUID>1</PredecessorUID></PredecessorLink>"
        self.assertIsNone(self._b(el)[0]["predecessors"][0]["type"])

    def test_a_cross_project_link_is_not_matched_to_a_uid_here(self):
        b, doc = self._b(_ml(1, extra="<CrossProject>1</CrossProject>"))
        self.assertEqual(b["predecessors"], [])
        self.assertEqual(b["predecessors_unresolved"], 1)

    def test_a_link_to_a_uid_not_in_the_file_is_counted(self):
        b, doc = self._b(_ml(99))
        self.assertEqual(b["predecessors"], [])
        self.assertTrue(any("predecessor links" in w for w in doc["warnings"]))

    def test_a_task_linked_to_itself_is_not_a_link(self):
        self.assertEqual(self._b(_ml(2))[0]["predecessors_unresolved"], 1)

    def test_no_links_anywhere_is_unknown(self):
        doc = S.parse_schedule("a.xml", _msp(_mt(1, "A") + _mt(2, "B")))
        self.assertIsNone(_by_id(doc)["2"]["predecessors"])


def _csv(rows, header="ID,Task Name,Start,Finish,Predecessors"):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header.split(","))
    for r in rows:
        w.writerow(r)
    return out.getvalue().encode()


def _row(i, name, preds=""):
    return [i, name, "2026-02-02", "2026-02-10", preds]


class TableLogic(unittest.TestCase):

    def _doc(self, *rows, header="ID,Task Name,Start,Finish,Predecessors"):
        return S.parse_schedule("a.csv", _csv(rows, header))

    def test_the_forms_people_write(self):
        cases = (("1FS+3d", {"id": "1", "type": "FS", "lag": 3.0, "lag_unit": "days"}),
                 ("1", {"id": "1", "type": None, "lag": None, "lag_unit": None}),
                 ("1SS", {"id": "1", "type": "SS", "lag": None, "lag_unit": None}),
                 ("1 ff - 2 days", {"id": "1", "type": "FF", "lag": -2.0, "lag_unit": "days"}),
                 ("1SF+1w", {"id": "1", "type": "SF", "lag": 5.0, "lag_unit": "days"}),
                 ("1FS+2ed", {"id": "1", "type": "FS", "lag": 2.0, "lag_unit": "edays"}),
                 ("1FS+50%", {"id": "1", "type": "FS", "lag": 50.0, "lag_unit": "percent"}),
                 ("1: FS 2 days", {"id": "1", "type": "FS", "lag": 2.0, "lag_unit": "days"}),
                 ("1FS+4", {"id": "1", "type": "FS", "lag": 4.0, "lag_unit": None}))
        for cell, want in cases:
            with self.subTest(cell=cell):
                doc = self._doc(_row("1", "A"), _row("2", "B", cell))
                self.assertEqual(_by_id(doc)["2"]["predecessors"], [want])

    def test_several_links_in_one_cell(self):
        doc = self._doc(_row("1", "A"), _row("3", "C"), _row("2", "B", "1;3SS"))
        self.assertEqual([p["id"] for p in _by_id(doc)["2"]["predecessors"]], ["1", "3"])

    def test_an_id_that_looks_like_a_link_is_read_as_the_id(self):
        doc = self._doc(_row("A-100", "A"), _row("AFS", "F"), _row("2", "B", "A-100,AFS"))
        self.assertEqual([p["id"] for p in _by_id(doc)["2"]["predecessors"]], ["A-100", "AFS"])

    def test_a_blank_cell_among_stated_ones_is_none_listed(self):
        doc = self._doc(_row("1", "A"), _row("2", "B", "1"))
        self.assertEqual(_by_id(doc)["1"]["predecessors"], [])

    def test_a_column_nobody_filled_in_is_unknown(self):
        self.assertIsNone(_by_id(self._doc(_row("1", "A"), _row("2", "B")))["2"]["predecessors"])

    def test_without_the_column_it_is_unknown(self):
        raw = "Task Name,Start\nA,2026-02-02\n".encode()
        self.assertIsNone(S.parse_schedule("a.csv", raw)["activities"][0]["predecessors"])

    def test_an_id_two_rows_share_is_not_guessed_between_them(self):
        doc = self._doc(_row("1", "A"), _row("1", "Different A"), _row("2", "B", "1"))
        self.assertEqual(_by_id(doc)["2"]["predecessors"], [])
        self.assertEqual(_by_id(doc)["2"]["predecessors_unresolved"], 1)

    def test_a_garbled_cell_is_counted(self):
        doc = self._doc(_row("1", "A"), _row("2", "B", "see note"))
        self.assertTrue(any("1 predecessor links" in w for w in doc["warnings"]))

    def test_plain_predecessors_beside_only_unique_ids_is_not_read(self):
        # MS Project's Predecessors column names the ID. Against Unique IDs
        # every number would still find a row, and the wrong one.
        doc = self._doc(_row("1", "A"), _row("2", "B", "1"), header="Unique ID,Task Name,Start,Finish,Predecessors")
        self.assertEqual(_by_id(doc)["2"]["predecessors"], [])

    def test_with_both_id_columns_predecessors_read_the_id_column(self):
        raw = _csv([["100", "1", "A", "2026-02-02", "2026-02-10", ""], ["200", "2", "B", "2026-02-02", "2026-02-10", "1"]],
                   "Unique ID,ID,Task Name,Start,Finish,Predecessors")
        self.assertEqual(_by_id(S.parse_schedule("a.csv", raw))["200"]["predecessors"][0]["id"], "100")

    def test_unique_id_predecessors_read_the_unique_id(self):
        raw = _csv([["100", "1", "A", "2026-02-02", "2026-02-10", ""], ["200", "2", "B", "2026-02-02", "2026-02-10", "100"]],
                   "Unique ID,ID,Task Name,Start,Finish,Unique ID Predecessors")
        self.assertEqual(_by_id(S.parse_schedule("a.csv", raw))["200"]["predecessors"][0]["id"], "100")

    def test_a_row_number_beside_dotted_wbs_is_not_a_wbs(self):
        raw = _csv([["1.1", "A", "2026-02-02", "2026-02-10", ""], ["1.2", "B", "2026-02-02", "2026-02-10", "1.1,1"]],
                   "WBS,Task Name,Start,Finish,Predecessors")
        b = _by_id(S.parse_schedule("a.csv", raw))["1.2"]
        self.assertEqual([p["id"] for p in b["predecessors"]], ["1.1"])
        self.assertEqual(b["predecessors_unresolved"], 1)

    def test_a_pdf_is_not_read_for_links(self):
        got = S._table_to_raws([["Task Name", "Start", "Finish", "Predecessors"], ["A", "2026-02-02", "2026-02-03", "1"]],
                               None, need_both_dates=True, read_links=False)
        self.assertIsNone(got[0][0]["preds"])

    def test_xlsx(self):
        openpyxl = __import__("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["ID", "Task Name", "Start", "Finish", "Predecessors"])
        ws.append([1, "A", datetime(2026, 2, 2), datetime(2026, 2, 3), None])
        ws.append([2, "B", datetime(2026, 2, 2), datetime(2026, 2, 3), "1FS+1d"])
        buf = io.BytesIO()
        wb.save(buf)
        doc = S.parse_schedule("a.xlsx", buf.getvalue())
        self.assertEqual(_by_id(doc)["2"]["predecessors"][0], {"id": "1", "type": "FS", "lag": 1.0, "lag_unit": "days"})

    def test_no_existing_field_changes_because_the_column_is_there(self):
        rows = [["1", "Frame", "2026-02-02", "2026-02-10"], ["2", "Board", "2026-02-11", "2026-02-20"]]
        plain = S.parse_schedule("a.csv", _csv(rows, "ID,Task Name,Start,Finish"))
        linked = S.parse_schedule("a.csv", _csv([rows[0] + [""], rows[1] + ["1"]]))
        old_fields = ("id", "wbs", "name", "level", "kind", "baseline_start", "baseline_finish", "current_start",
                      "current_finish", "actual_start", "actual_finish", "percent_complete", "duration_days")
        self.assertEqual([[a[k] for k in old_fields] for a in plain["activities"]],
                         [[a[k] for k in old_fields] for a in linked["activities"]])


# ── TWO WRITERS, ONE COLLECTION ────────────────────────────────────────────

class GeneratedRowsAndBaselines(unittest.TestCase):

    def _db(self, *rows):
        return FakeDb(project_schedules=list(rows))

    BASE = {"_id": "c1", "project_id": "p", "company_id": "x", "status": "confirmed", "doc": {"activities": []}}
    GEN = {"_id": "g1", "project_id": "p", "graph_version": "graph_v1", "phases": [], "generated_at": datetime(2026, 1, 1)}

    def test_a_confirmed_baseline_is_not_the_latest_generated_schedule(self):
        got = asyncio.run(engine.load_latest_schedule(self._db(self.BASE), "p"))
        self.assertIsNone(got, "a person's confirmed file came back as the engine's output")

    def test_the_generated_row_is_still_found(self):
        got = asyncio.run(engine.load_latest_schedule(self._db(self.BASE, self.GEN), "p"))
        self.assertEqual(got["graph_version"], "graph_v1")

    def test_a_draft_or_superseded_file_is_not_found_either(self):
        for status in ("draft", "superseded", "discarded"):
            with self.subTest(status=status):
                self.assertIsNone(asyncio.run(engine.load_latest_schedule(self._db({**self.BASE, "status": status}), "p")))

    def test_a_generated_row_has_no_status_to_be_mistaken_for_confirmed(self):
        from app.scheduling.schedule_models import Schedule
        db = self._db()
        asyncio.run(engine.persist_schedule(db, Schedule(project_id="p", graph_version="graph_v1", generated_at=datetime(2026, 1, 1))))
        self.assertNotIn("status", db.project_schedules.rows[0])


# ── WORK STATE ─────────────────────────────────────────────────────────────

def _sched(**extra):
    return {"data_date": "2026-11-01", "activities": [
        {"id": "A1", "name": "Frame Floor 3", "kind": "task", "baseline_finish": "2026-10-20", "current_finish": "2026-10-25",
         "predecessors": []},
        {"id": "A2", "name": "Electric rough Floor 3", "kind": "task", "current_finish": "2026-11-01",
         "predecessors": [{"id": "A1", "type": "FS", "lag": None, "lag_unit": None}]},
        {"id": "A3", "name": "Drywall Floor 3", "kind": "task", "current_finish": "2026-12-01",
         "predecessors": [{"id": "A2", "type": "SS", "lag": 2.0, "lag_unit": "days"}], **extra},
        {"id": "A4", "name": "Prime Floor 3", "kind": "task", "current_finish": "2026-12-20"},
    ]}


class TheJobsOwnLogic(unittest.TestCase):

    def test_the_answer_uses_the_files_predecessors_and_says_so(self):
        out = W.as_text(_holds(schedule=_sched()))
        self.assertIn("This job's own logic, from its confirmed schedule file: Drywall Floor 3 has 1 predecessor(s):", out)
        self.assertIn("Electric rough Floor 3 (SS, lag 2 working days)", out)
        self.assertNotIn("Work that normally comes first", out)

    def test_each_predecessor_is_set_beside_its_reports(self):
        out = W.as_text(_holds([_act("Electrical wiring", where="floor 3", company="Power Direct", trade="Electric")], schedule=_sched()))
        self.assertIn("reported", out.split("predecessor(s):")[1])
        self.assertIn("Power Direct", out)

    def test_a_stated_empty_list_is_said_as_the_file_listing_none(self):
        ans = W.what_holds("framing", "FLOOR_3", [], [], today=TODAY, schedule=_sched())
        self.assertIn("lists no predecessor for Frame Floor 3", W.as_text(ans))

    def test_a_list_short_of_a_lost_link_says_so(self):
        out = W.as_text(_holds(schedule=_sched(predecessors_unresolved=2)))
        self.assertIn("2 link(s) in the file could not be matched", out)

    def test_an_old_document_with_no_predecessors_is_unknown_not_none(self):
        sched = {"activities": [{"id": "A3", "name": "Drywall Floor 3", "kind": "task", "current_finish": "2026-12-01"}]}
        out = W.as_text(_holds(schedule=sched))
        self.assertIn("unknown, not 'no dependencies'", out)
        self.assertIn("standard sequence, not this job's own", out)
        self.assertNotIn("lists no predecessor", out)
        self.assertNotIn("This job's own logic", out)

    def test_a_plumbing_trim_activity_is_not_the_rough_in(self):
        sched = {"activities": [{"id": "T", "name": "Plumbing Trim Floor 3", "kind": "task"}]}
        self.assertEqual(W._schedule_rows(sched, "rough_water", "FLOOR_3"), [])
        self.assertEqual([a["id"] for a in W._schedule_rows(sched, "mep_trim", "FLOOR_3")], ["T"])

    def test_an_explicit_none_reads_the_same(self):
        sched = {"activities": [{"id": "A3", "name": "Drywall Floor 3", "kind": "task", "predecessors": None}]}
        self.assertEqual(_holds(schedule=sched)["sequence"]["reason"], "no_logic_in_file")

    def test_a_schedule_with_no_such_activity_falls_back_and_says_so(self):
        out = W.as_text(W.what_holds("ceiling_drop", "FLOOR_3", [], [], today=TODAY, schedule=_sched()))
        self.assertIn("no activity for this work on this level", out)
        self.assertIn("standard sequence", out)

    def test_with_no_schedule_the_list_is_still_labelled_standard(self):
        self.assertIn("Work that normally comes first (standard sequence, not this job's own schedule):", W.as_text(_holds()))

    def test_the_inspections_stay_labelled_standard_even_beside_job_logic(self):
        out = W.as_text(_holds(schedule=_sched()))
        self.assertIn("(standard sequence, not this job's own schedule). Levelog holds no inspection results", out)

    def test_a_predecessor_naming_no_level_is_not_matched_to_a_level(self):
        sched = _sched()
        sched["activities"][1]["name"] = "Electric rough"
        out = W.as_text(W.what_holds("drywall", "FLOOR_3", [_act("Electrical wiring", where="floor 3")], [], today=TODAY, schedule=sched))
        self.assertIn("no matching log work or no level in its name", out)

    def test_a_cycle_in_the_file_cannot_hang_it(self):
        sched = _sched()
        sched["activities"][1]["predecessors"] = [{"id": "A3", "type": "FS", "lag": None, "lag_unit": None}]
        self.assertIn("predecessor(s)", W.as_text(_holds(schedule=sched)))


class PastPlannedFinish(unittest.TestCase):

    LOGS_FROM = TODAY - timedelta(days=89)

    def _state(self, acts=(), schedule=None, logs_from=LOGS_FROM):
        return W.package_state("rough_electric", "FLOOR_3", W.evidence_rows(list(acts)), [], schedule or _sched(), TODAY, logs_from)

    def test_it_is_stated_only_as_two_records_side_by_side(self):
        words = W._schedule_words(self._state())
        self.assertIn("past planned finish 2026-11-01 with no report on this level in the logs read", words[0])
        self.assertNotIn("delay", words[0].lower())

    def test_a_report_ends_it(self):
        s = self._state([_act("Electrical wiring", where="floor 3")])
        self.assertFalse(s["schedule"][0]["past_planned_no_report"])

    def test_a_file_actual_finish_ends_it(self):
        sched = _sched()
        sched["activities"][1]["actual_finish"] = "2026-11-01"
        self.assertFalse(self._state(schedule=sched)["schedule"][0]["past_planned_no_report"])

    def test_a_date_before_the_logs_read_cannot_be_said(self):
        s = self._state(logs_from=date(2026, 11, 5))
        self.assertFalse(s["schedule"][0]["past_planned_no_report"])

    def test_no_window_known_says_nothing(self):
        self.assertFalse(self._state(logs_from=None)["schedule"][0]["past_planned_no_report"])

    def test_the_future_is_not_past(self):
        sched = _sched()
        sched["activities"][1]["current_finish"] = "2026-11-20"
        self.assertFalse(self._state(schedule=sched)["schedule"][0]["past_planned_no_report"])


# ── PLAN VERSUS ACTUAL, RATE, LOOKAHEAD (lib/progress_plan.py) ─────────────

def _ev(day, node, *levels, generic=False):
    return {"date": day, "nodes": [node], "levels": list(levels), "generic": generic, "sub": "", "work": "", "space": None,
            "where": "", "log_id": "L", "amended": False}


class PlanVersusActual(unittest.TestCase):

    def test_the_files_dates_beside_the_logs(self):
        rows = [_ev(date(2026, 10, 1), "framing", "FLOOR_3"), _ev(date(2026, 10, 4), "framing", "FLOOR_3")]
        got = PP.plan_vs_actual(_sched(), rows, today=TODAY, logs_from=TODAY - timedelta(days=89))
        a1 = next(r for r in got["rows"] if r["id"] == "A1")
        self.assertEqual((a1["baseline_finish"], a1["current_finish"], a1["first_reported"], a1["last_reported"], a1["report_days"]),
                         ("2026-10-20", "2026-10-25", date(2026, 10, 1), date(2026, 10, 4), 2))
        self.assertFalse(a1["past_planned_no_report"])

    def test_a_report_on_another_floor_is_not_a_report_of_this_activity(self):
        rows = [_ev(date(2026, 10, 1), "rough_electric", "FLOOR_9")]
        got = PP.plan_vs_actual(_sched(), rows, today=TODAY, logs_from=TODAY - timedelta(days=89))
        a2 = next(r for r in got["rows"] if r["id"] == "A2")
        self.assertIsNone(a2["first_reported"])
        self.assertTrue(a2["past_planned_no_report"])

    def test_an_activity_it_cannot_place_is_counted_not_flagged(self):
        sched = {"activities": [{"id": "X", "name": "Survey", "kind": "task", "current_finish": "2026-10-01"}]}
        got = PP.plan_vs_actual(sched, [], today=TODAY, logs_from=date(2026, 8, 1))
        self.assertEqual((got["rows"], got["unmapped"]), ([], 1))

    def test_no_percent_appears(self):
        got = PP.plan_vs_actual(_sched(), [], today=TODAY, logs_from=TODAY - timedelta(days=89))
        self.assertTrue(all("percent" not in k for r in got["rows"] for k in r))


_D = date(2026, 9, 1)


def _worked(level, start, days):
    return [_ev(start + timedelta(days=i), "drywall", level) for i in range(days)]


class TheRate(unittest.TestCase):

    def _three(self):
        return _worked("FLOOR_1", _D, 4) + _worked("FLOOR_2", _D + timedelta(days=10), 5) + _worked("FLOOR_3", _D + timedelta(days=20), 6) \
            + _worked("FLOOR_4", _D + timedelta(days=30), 2)

    def test_three_levels_left_behind_give_a_rate(self):
        self.assertEqual(PP.production_rate("drywall", self._three(), TODAY), {"levels": 3, "days_per_level": 5})

    def test_two_levels_are_unknown(self):
        rows = _worked("FLOOR_1", _D, 4) + _worked("FLOOR_2", _D + timedelta(days=10), 5) + _worked("FLOOR_3", _D + timedelta(days=20), 2)
        self.assertIsNone(PP.production_rate("drywall", rows, TODAY)["days_per_level"])

    def test_a_row_for_several_floors_spoils_those_floors(self):
        rows = self._three() + [_ev(_D, "drywall", "FLOOR_1", "FLOOR_2")]
        self.assertIsNone(PP.production_rate("drywall", rows, TODAY)["days_per_level"])

    def test_a_trade_only_row_spoils_its_floor(self):
        rows = self._three() + [_ev(_D, "drywall", "FLOOR_1", generic=True)]
        self.assertIsNone(PP.production_rate("drywall", rows, TODAY)["days_per_level"])

    def test_the_level_being_worked_is_not_counted(self):
        self.assertEqual(PP.production_rate("drywall", self._three(), TODAY)["levels"], 3)

    def test_a_level_reported_within_the_last_week_is_not_counted(self):
        recent = TODAY - timedelta(days=W.REPORTED_RECENT_DAYS)
        rows = _worked("FLOOR_1", _D, 4) + _worked("FLOOR_2", _D + timedelta(days=10), 5) + [_ev(recent, "drywall", "FLOOR_3"), _ev(TODAY, "drywall", "FLOOR_4")]
        self.assertEqual(PP.production_rate("drywall", rows, TODAY)["levels"], 2)

    def test_the_last_level_with_no_later_work_is_not_counted(self):
        rows = _worked("FLOOR_1", _D, 4) + _worked("FLOOR_2", _D + timedelta(days=10), 5) + _worked("FLOOR_3", _D + timedelta(days=20), 6)
        self.assertEqual(PP.production_rate("drywall", rows, TODAY)["levels"], 2)

    def test_add_workdays_counts_the_start_and_skips_the_weekend(self):
        self.assertEqual(PP._add_workdays(date(2026, 11, 6), 2), date(2026, 11, 9))  # Fri + Mon
        self.assertEqual(PP._add_workdays(date(2026, 11, 7), 1), date(2026, 11, 9))  # Sat starts Mon


class Lookahead(unittest.TestCase):

    def _sched(self):
        return {"data_date": "2026-11-02", "activities": [
            {"id": "S", "name": "Summary", "kind": "summary", "current_start": "2026-11-10", "current_finish": "2026-11-12"},
            {"id": "IN", "name": "Drywall Floor 5", "kind": "task", "current_start": "2026-11-10", "current_finish": "2026-11-20"},
            {"id": "LATER", "name": "Prime Floor 5", "kind": "task", "current_start": "2026-11-20", "current_finish": "2026-11-30"},
            {"id": "FAR", "name": "Finishes", "kind": "task", "current_start": "2026-12-20", "current_finish": "2026-12-30"},
            {"id": "DONE", "name": "Frame Floor 5", "kind": "task", "current_start": "2026-11-10", "current_finish": "2026-11-11", "actual_finish": "2026-11-08"},
            {"id": "OLD", "name": "Base", "kind": "task", "baseline_start": "2026-11-11", "baseline_finish": "2026-11-13"},
            {"id": "NODATE", "name": "Unscheduled", "kind": "task"},
            {"id": "GONE", "name": "Base 2", "kind": "task", "current_start": "2026-10-01", "current_finish": "2026-10-20"},
        ]}

    def _la(self, days=7, rows=()):
        return PP.lookahead(self._sched(), list(rows), today=TODAY, days=days)

    def test_seven_days(self):
        self.assertEqual({i["id"] for i in self._la()["items"]}, {"IN", "OLD"})

    def test_fourteen_days(self):
        self.assertEqual({i["id"] for i in self._la(14)["items"]}, {"IN", "OLD", "LATER"})

    def test_only_seven_or_fourteen(self):
        self.assertEqual(self._la(3)["days"], 7)

    def test_baseline_is_used_only_when_there_is_no_current_and_is_named(self):
        self.assertEqual(next(i for i in self._la()["items"] if i["id"] == "OLD")["planned_source"], "baseline")

    def test_without_evidence_the_rate_is_unknown_and_says_so(self):
        i = next(i for i in self._la()["items"] if i["id"] == "IN")
        self.assertIsNone(i["rate"])
        self.assertIn("Rate unknown", i["rate_words"])

    def test_three_levels_give_a_date_beside_the_files(self):
        i = next(i for i in self._la(rows=TheRate()._three())["items"] if i["id"] == "IN")
        self.assertEqual(i["rate"]["days_per_level"], 5)
        self.assertEqual(i["planned_finish"], date(2026, 11, 20))
        self.assertEqual(i["finish_at_rate"], PP._add_workdays(date(2026, 11, 10), 5))

    def test_a_finish_at_rate_already_past_is_not_given(self):
        sched = {"activities": [{"id": "OLD", "name": "Drywall Floor 8", "kind": "task", "actual_start": "2026-09-01",
                                 "current_start": "2026-11-10", "current_finish": "2026-11-12"}]}
        i = PP.lookahead(sched, TheRate()._three(), today=TODAY, days=7)["items"][0]
        self.assertIsNone(i["finish_at_rate"])
        self.assertIn("nothing on record says it finished", i["rate_words"])

    def test_a_plumbing_trim_activity_gets_the_trim_place(self):
        self.assertEqual(PP.activity_place({"name": "Plumbing Trim Floor 3"})["nodes"], ["mep_trim"])

    def test_two_floors_at_once_gets_no_rate(self):
        sched = {"activities": [{"id": "M", "name": "Drywall Floors 1-2", "kind": "task", "current_start": "2026-11-10", "current_finish": "2026-11-14"}]}
        i = PP.lookahead(sched, TheRate()._three(), today=TODAY, days=7)["items"][0]
        self.assertIsNone(i["rate"])

    def test_the_rate_never_moves_the_files_date(self):
        la = self._la(rows=TheRate()._three())
        self.assertEqual({i["planned_finish"] for i in la["items"]}, {date(2026, 11, 20), date(2026, 11, 13)})

    def test_the_words_state_the_file_and_forbid_the_rest(self):
        out = PP.lookahead_text(self._sched(), [], today=TODAY, days=7, logs_from=date(2026, 8, 1))
        self.assertIn("data date 2026-11-02 (7 days old)", out)
        self.assertIn("Do not give a percent complete, a delay or a cause", out)
        self.assertNotIn("%", out)

    def test_a_past_planned_finish_is_listed_with_no_cause(self):
        sched = {"activities": [{"id": "P", "name": "Drywall Floor 2", "kind": "task", "current_finish": "2026-10-15"}]}
        out = PP.lookahead_text(sched, [], today=TODAY, days=7, logs_from=date(2026, 8, 1))
        self.assertIn("Past the file's planned finish with no report", out)
        self.assertIn("Drywall Floor 2 (P): planned finish 2026-10-15", out)


# ── A PROPOSED SEQUENCE ────────────────────────────────────────────────────

class ProposedSequence(unittest.TestCase):

    def test_levels_are_the_logs_in_the_order_the_logs_name_them(self):
        rows = [_ev(date(2026, 10, 5), "framing", "FLOOR_3"), _ev(date(2026, 10, 1), "framing", "CELLAR"), _ev(date(2026, 10, 1), "framing", "ROOF")]
        self.assertEqual([x["level"] for x in PP.propose_sequence(rows)["levels"]], ["CELLAR", "ROOF", "FLOOR_3"])

    def test_a_level_nobody_reported_is_not_invented(self):
        self.assertEqual([x["level"] for x in PP.propose_sequence([_ev(_D, "framing", "FLOOR_3")])["levels"]], ["FLOOR_3"])

    def test_the_order_is_the_templates_dependency_order(self):
        steps = [s["id"] for s in PP.propose_sequence([_ev(_D, "framing", "FLOOR_3")])["levels"][0]["steps"]]
        for a, b in (("framing", "rough_dwv"), ("rough_dwv", "gate_plumbing_rough"), ("gate_plumbing_rough", "drywall"),
                     ("drywall", "ceiling_drop"), ("prime", "finishes")):
            self.assertLess(steps.index(a), steps.index(b), (a, b))

    def test_whole_building_and_tco_nodes_are_not_a_floors_work(self):
        steps = [s["id"] for s in PP.propose_sequence([_ev(_D, "framing", "FLOOR_3")])["levels"][0]["steps"]]
        for gone in ("blue_card", "gate_gas_final", "tco_zone", "gate_ls_fdny"):
            self.assertNotIn(gone, steps)

    def test_reported_first_dates_are_the_earliest_per_step(self):
        early, late = _ev(date(2026, 10, 2), "framing", "FLOOR_3"), _ev(date(2026, 10, 9), "framing", "FLOOR_3")
        for rows in ([early, late], [late, early]):
            lv = PP.propose_sequence(rows)["levels"][0]
            self.assertEqual(lv["first_reported"], "2026-10-02")
            self.assertEqual(next(s for s in lv["steps"] if s["id"] == "framing")["first_reported"], "2026-10-02")
            self.assertIsNone(next(s for s in lv["steps"] if s["id"] == "drywall")["first_reported"])

    def test_a_conditional_system_is_marked_not_dropped(self):
        steps = PP.propose_sequence([_ev(_D, "framing", "FLOOR_3")])["levels"][0]["steps"]
        self.assertTrue(next(s for s in steps if s["id"] == "rough_sprinkler")["conditional"])

    def test_a_known_absent_system_is_dropped(self):
        steps = PP.propose_sequence([_ev(_D, "framing", "FLOOR_3")], {"has_gas": False})["levels"][0]["steps"]
        self.assertNotIn("rough_gas", [s["id"] for s in steps])

    def test_the_message_is_short_and_says_proposed_and_not_approved(self):
        rows = [_ev(_D + timedelta(days=i), "framing", f"FLOOR_{i + 1}") for i in range(12)]
        out = PP.proposed_text({**PP.propose_sequence(rows), "status": "proposed"}, "588")
        self.assertIn("PROPOSED sequence", out)
        self.assertIn("It is not a schedule.", out)
        self.assertIn("Not approved.", out)
        self.assertLess(len(out), 1300)

    def test_an_approved_one_is_still_called_proposed(self):
        doc = {**PP.propose_sequence([_ev(_D, "framing", "FLOOR_3")]), "status": "approved", "approved_by_name": "Sue", "approved_at": datetime(2026, 11, 2, tzinfo=timezone.utc)}
        out = PP.proposed_text(doc, "588")
        self.assertIn("PROPOSED sequence", out)
        self.assertIn("Approved by Sue on Nov 2.", out)
        self.assertNotIn("Not approved", out)

    def test_it_needs_a_level_to_propose(self):
        out = PP.proposed_text({"levels": [], "status": "proposed"}, "588")
        self.assertIn("nothing to propose", out)
        self.assertIn("PROPOSED", out)

    def test_history_keeps_what_a_rebuild_replaced(self):
        self.assertEqual(PP.history_entry("rebuilt", "u", "pm", "t", replaced=[1])["replaced_levels"], [1])
        self.assertNotIn("replaced_levels", PP.history_entry("approved", "u", "pm", "t"))


class ThroughTheAssistant(_Brain):

    def _seed_logs(self):
        self.db.logbooks.rows.append(_log("L1", {"company": "Arkon", "trade": "Carpentry", "work_description": "Interior framing",
                                                 "work_locations": "floor 3"}))

    def _seed_confirmed(self, doc=None):
        today = datetime.now(timezone.utc).date()
        self.db[server.PROJECT_SCHEDULES].rows.append(
            {"_id": "c1", "company_id": str(CO_A), "project_id": THOMAS, "status": "confirmed",
             "doc": doc or {"data_date": today.isoformat(), "activities": [
                 {"id": "A1", "name": "Drywall Floor 3", "kind": "task",
                  "current_start": (today + timedelta(days=2)).isoformat(), "current_finish": (today + timedelta(days=4)).isoformat()}]}})

    def _call(self, tool, args, said):
        async def go():
            ctx = {"ident": {"company_id": CO_A, "user_id": "u_admin", "role": "admin", "user": {"name": "Ada Admin"}},
                   "text": said}
            return await getattr(server, tool)(ctx, {"id": THOMAS, "label": "588"}, args)
        with _Ctx(db=self.db):
            return asyncio.run(go())

    def _rows(self):
        return self.db[server.PROPOSED_SEQUENCES].rows

    def test_the_tool_is_offered_and_both_one_job_lists_carry_it(self):
        names = {t["name"] for t in server._DM_BRAIN_EXTRA_TOOLS}
        self.assertLessEqual({"proposed_sequence", "schedule_lookahead"}, names)
        for tool in ("proposed_sequence", "schedule_lookahead"):
            self.assertIn(tool, server._DM_BRAIN_ONE_JOB)
        src = Path(server.__file__).read_text(encoding="utf-8")
        body = src[src.index("async def _dm_brain_exec_one("):src.index('if name == "headcount":')]
        self.assertIn('"proposed_sequence"', body)

    def test_showing_it_stores_it_as_proposed_and_nowhere_else(self):
        self._seed_logs()
        out = self._call("_dm_proposed_sequence", {}, "what's the sequence for 588")
        self.assertIn("PROPOSED sequence", out)
        row = self._rows()[0]
        self.assertEqual((row["status"], row["created_by"], row["history"][0]["action"]), ("proposed", "u_admin", "proposed"))
        self.assertEqual(self.db[server.PROJECT_SCHEDULES].rows, [])

    def test_a_person_must_say_approve(self):
        self._seed_logs()
        self._call("_dm_proposed_sequence", {}, "show me")
        out = self._call("_dm_proposed_sequence", {"approve": True}, "looks good, thanks")
        self.assertEqual(self._rows()[0]["status"], "proposed")
        self.assertIn("Not approved", out)

    def test_the_model_alone_cannot_approve(self):
        self._seed_logs()
        self._call("_dm_proposed_sequence", {}, "show me")
        self._call("_dm_proposed_sequence", {"approve": False}, "approve the sequence")
        self.assertEqual(self._rows()[0]["status"], "proposed")

    def test_a_negated_approval_is_not_one(self):
        self._seed_logs()
        self._call("_dm_proposed_sequence", {}, "show me")
        self._call("_dm_proposed_sequence", {"approve": True}, "do not approve that")
        self.assertEqual(self._rows()[0]["status"], "proposed")

    def test_a_substring_is_not_the_word(self):
        self._seed_logs()
        self._call("_dm_proposed_sequence", {}, "show me")
        self._call("_dm_proposed_sequence", {"approve": True}, "reapprovement pending")
        self.assertEqual(self._rows()[0]["status"], "proposed")

    def test_approval_appends_history_and_names_the_person(self):
        self._seed_logs()
        self._call("_dm_proposed_sequence", {}, "show me")
        out = self._call("_dm_proposed_sequence", {"approve": True}, "approve the sequence")
        row = self._rows()[0]
        self.assertEqual((row["status"], row["approved_by"], [h["action"] for h in row["history"]]),
                         ("approved", "u_admin", ["proposed", "approved"]))
        self.assertIn("PROPOSED sequence", out)
        self.assertIn("Approved by Ada Admin", out)

    def test_nothing_shown_means_nothing_to_approve(self):
        self._seed_logs()
        self._call("_dm_proposed_sequence", {"approve": True}, "approve the sequence")
        self.assertEqual(self._rows()[0]["status"], "proposed")

    def test_a_rebuild_keeps_what_it_replaced_and_appends(self):
        self._seed_logs()
        self._call("_dm_proposed_sequence", {}, "show me")
        before = self._rows()[0]["levels"]
        self.db.logbooks.rows.append(_log("L2", {"company": "Arkon", "trade": "Carpentry", "work_description": "Interior framing",
                                                 "work_locations": "roof"}))
        self._call("_dm_proposed_sequence", {}, "show me")
        row = self._rows()[0]
        self.assertEqual([h["action"] for h in row["history"]], ["proposed", "rebuilt"])
        self.assertEqual(row["history"][1]["replaced_levels"], before)

    def test_an_approved_one_is_not_rebuilt(self):
        self._seed_logs()
        self._call("_dm_proposed_sequence", {}, "show me")
        self._call("_dm_proposed_sequence", {"approve": True}, "approve the sequence")
        before = self._rows()[0]["levels"]
        self.db.logbooks.rows.append(_log("L2", {"company": "Arkon", "trade": "Carpentry", "work_description": "Interior framing",
                                                 "work_locations": "roof"}))
        self._call("_dm_proposed_sequence", {}, "show me")
        self.assertEqual(self._rows()[0]["levels"], before)
        self.assertEqual(len(self._rows()[0]["history"]), 2)

    def test_a_job_with_a_confirmed_file_gets_no_proposal(self):
        self._seed_logs()
        self._seed_confirmed()
        out = self._call("_dm_proposed_sequence", {"approve": True}, "approve the sequence")
        self.assertIn("confirmed schedule", out)
        self.assertEqual(self._rows(), [])

    def test_a_draft_file_is_not_a_baseline(self):
        self._seed_logs()
        self.db[server.PROJECT_SCHEDULES].rows.append({"_id": "d1", "company_id": str(CO_A), "project_id": THOMAS, "status": "draft",
                                                       "doc": {"activities": []}})
        self.assertIn("PROPOSED sequence", self._call("_dm_proposed_sequence", {}, "show me"))

    def test_a_dry_run_stores_nothing(self):
        self._seed_logs()
        async def go():
            ctx = {"ident": {"company_id": CO_A, "user_id": "u_admin"}, "text": "show me", "dry_run": True}
            return await server._dm_proposed_sequence(ctx, {"id": THOMAS, "label": "588"}, {})
        with _Ctx(db=self.db):
            asyncio.run(go())
        self.assertEqual(self._rows(), [])

    def test_another_companys_job_is_refused(self):
        async def go():
            ctx = {"ident": {"company_id": "c0ffee000000000000000099", "user_id": "x"}, "text": "approve"}
            return await server._dm_proposed_sequence(ctx, {"id": THOMAS, "label": "588"}, {"approve": True})
        with _Ctx(db=self.db):
            self.assertEqual(asyncio.run(go()), server.wa_security.BOT_SCOPE_REFUSAL)

    def test_it_goes_when_the_project_goes(self):
        self.assertIn(server.PROPOSED_SEQUENCES, server._PROJECT_OWNED_COLLECTIONS)

    def test_the_lookahead_needs_a_confirmed_file(self):
        self.assertIn("No confirmed schedule", self._call("_dm_schedule_lookahead", {"days": 14}, "what's next"))

    def test_the_lookahead_reads_the_confirmed_file(self):
        self._seed_confirmed()
        out = self._call("_dm_schedule_lookahead", {"days": 7}, "what's next")
        self.assertIn("Drywall Floor 3 (A1)", out)
        self.assertIn("Rate unknown", out)

    def test_work_status_gets_the_files_logic_through_the_assistant(self):
        doc = {"data_date": "2026-11-01", "activities": [
            {"id": "A1", "name": "Frame Floor 3", "kind": "task", "predecessors": []},
            {"id": "A2", "name": "Drywall Floor 3", "kind": "task", "current_finish": "2099-01-01",
             "predecessors": [{"id": "A1", "type": "FS", "lag": None, "lag_unit": None}]}]}
        self._seed_confirmed(doc)

        def check(kw):
            self.result = last_tool_results(kw)[0]
            return resp(text("Per the file, framing comes first."))
        llm = FakeLLM(resp(use("work_status", {"job": "588", "work": "drywall", "level": "3"}, "a")), check)
        with _Ctx(db=self.db) as c:
            self.say(c, "What's holding up drywall on Floor 3?", llm)
        self.assertIn("This job's own logic", self.result)
        self.assertIn("Frame Floor 3 (FS)", self.result)


if __name__ == "__main__":
    unittest.main()
