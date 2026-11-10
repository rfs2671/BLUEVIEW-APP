"""SCHEDULE STATUS AND FORECAST (lib/forecast.py): facts, file dates, reported
spans and estimates, kept apart.

Schedule fixtures are REAL-FORMAT files built the way tests/test_schedule_logic.py
and tests/test_schedule_import.py build them (a P6 XER with a TASKPRED table, an
MS Project XML with PredecessorLink, an XLSX with a Predecessors column) and read
through lib/schedule_import.parse_schedule, so the forecast sees what an import
produces. Evidence fixtures are lib/evidence.item at every rung. No real
schedule export exists in this repo: what real P6 / MS Project exports carry
beyond these fixtures is not asserted.
"""

from __future__ import annotations

import io
import re
import unittest
from datetime import date, datetime, timedelta

from lib import evidence as E
from lib import forecast as F
from lib import schedule_import as S

TODAY = date(2026, 11, 9)  # a Monday
P = "p1"


# ── REAL-FORMAT SCHEDULE FILES ─────────────────────────────────────────────

_TASK_F = ["task_id", "proj_id", "wbs_id", "clndr_id", "task_code", "task_name", "task_type", "complete_pct_type",
           "phys_complete_pct", "target_drtn_hr_cnt", "target_start_date", "target_end_date", "early_start_date",
           "early_end_date", "act_start_date", "act_end_date"]
_PRED_F = ["task_pred_id", "task_id", "pred_task_id", "proj_id", "pred_proj_id", "pred_type", "lag_hr_cnt"]

#: (code, name, baseline start, baseline finish, current start, current finish)
PLAN = [("D1", "Drywall Floor 1", "2026-09-01", "2026-09-10", "2026-09-01", "2026-09-10"),
        ("D2", "Drywall Floor 2", "2026-09-11", "2026-09-20", "2026-09-11", "2026-09-21"),
        ("D3", "Drywall Floor 3", "2026-09-21", "2026-10-01", "2026-09-22", "2026-10-02"),
        ("D4", "Drywall Floor 4", "2026-10-02", "2026-10-20", "2026-10-05", "2026-11-03"),
        ("P4", "Prime Floor 4", "2026-10-21", "2026-10-30", "2026-11-05", "2026-11-12")]
#: successor, predecessor, P6 type, lag hours (8h days)
LINKS = [("D2", "D1", "PR_FS", "0"), ("D3", "D2", "PR_FS", "0"), ("D4", "D3", "PR_FS", "0"), ("P4", "D4", "PR_FS", "16")]


def _xer(with_logic=True, pct=None):
    def table(name, fields, rows):
        return "\n".join([f"%T\t{name}", "%F\t" + "\t".join(fields)] + ["%R\t" + "\t".join(r) for r in rows])
    ids = {code: str(900 + i) for i, (code, *_r) in enumerate(PLAN)}
    tasks = []
    for code, name, bs, bf, cs, cf in PLAN:
        t = dict.fromkeys(_TASK_F, "")
        t.update(task_id=ids[code], proj_id="1", wbs_id="10", clndr_id="9", task_code=code, task_name=name,
                 task_type="TT_Task", complete_pct_type="CP_Phys", phys_complete_pct=str((pct or {}).get(code, "")),
                 target_start_date=f"{bs} 08:00", target_end_date=f"{bf} 17:00",
                 early_start_date=f"{cs} 08:00", early_end_date=f"{cf} 17:00")
        tasks.append([t[f] for f in _TASK_F])
    parts = ["ERMHDR\t20.12\t2026-11-02\tProject\tadmin\tdb\tProject Management\tUSD",
             table("PROJECT", ["proj_id", "proj_short_name", "last_recalc_date", "plan_start_date"],
                   [["1", "TWR", "2026-11-02 08:00", "2026-09-01 08:00"]]),
             table("CALENDAR", ["clndr_id", "day_hr_cnt"], [["9", "8"]]),
             table("PROJWBS", ["wbs_id", "proj_id", "parent_wbs_id", "wbs_short_name", "wbs_name", "seq_num"],
                   [["10", "1", "", "TWR", "Tower 12", "1"]]),
             table("TASK", _TASK_F, tasks)]
    if with_logic:
        parts.append(table("TASKPRED", _PRED_F, [["p" + s + p, ids[s], ids[p], "1", "1", k, lag] for s, p, k, lag in LINKS]))
    parts.append("%E")
    return S.parse_schedule("t.xer", "\n".join(parts).encode("utf-8"))


_NS = "http://schemas.microsoft.com/project"


def _msp(with_logic=True):
    uid = {code: i + 1 for i, (code, *_r) in enumerate(PLAN)}
    links = {s: (p, {"PR_FS": "1", "PR_SS": "3"}[k], str(int(lag) // 8 * 4800)) for s, p, k, lag in LINKS}
    tasks = ""
    for code, name, bs, bf, cs, cf in PLAN:
        link = ""
        if with_logic and code in links:
            p, k, lag = links[code]
            link = (f"<PredecessorLink><PredecessorUID>{uid[p]}</PredecessorUID><Type>{k}</Type><LinkLag>{lag}</LinkLag>"
                    "<LagFormat>7</LagFormat></PredecessorLink>")
        tasks += (f"<Task><UID>{uid[code]}</UID><ID>{uid[code]}</ID><Name>{name}</Name><OutlineLevel>1</OutlineLevel>"
                  f"<Start>{cs}T08:00:00</Start><Finish>{cf}T17:00:00</Finish>{link}"
                  f"<Baseline><Number>0</Number><Start>{bs}T08:00:00</Start><Finish>{bf}T17:00:00</Finish></Baseline></Task>")
    raw = (f'<?xml version="1.0" encoding="UTF-8"?><Project xmlns="{_NS}"><Name>t.xml</Name><MinutesPerDay>480</MinutesPerDay>'
           f"<StatusDate>2026-11-02T17:00:00</StatusDate><Tasks>{tasks}</Tasks></Project>").encode()
    return S.parse_schedule("t.xml", raw)


def _xlsx(with_logic=True, pct=None):
    openpyxl = __import__("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    head = ["ID", "Task Name", "Baseline Start", "Baseline Finish", "Start", "Finish"]
    head += ["Predecessors"] if with_logic else []
    head += ["% Complete"] if pct else []
    ws.append(head)
    links = {s: f"{p}FS+{int(lag) // 8}d" if lag != "0" else p for s, p, _k, lag in LINKS}
    d = lambda s: datetime.fromisoformat(s)  # noqa: E731
    for code, name, bs, bf, cs, cf in PLAN:
        row = [code, name, d(bs), d(bf), d(cs), d(cf)]
        row += [links.get(code)] if with_logic else []
        row += [(pct or {}).get(code)] if pct else []
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return S.parse_schedule("t.xlsx", buf.getvalue())


FORMATS = {"xer": _xer, "msp_xml": _msp, "xlsx": _xlsx}


def _ids(doc):
    """MS Project ids are UIDs; map them back to the codes above."""
    names = {name: code for code, name, *_r in PLAN}
    return {a["id"]: names.get(a["name"], a["id"]) for a in doc["activities"]}


# ── EVIDENCE AT EVERY RUNG ─────────────────────────────────────────────────

def ev(kind, claim, level, on, node="drywall", shared=False, levels=None, **kw):
    if kind == "estimate":
        kw.setdefault("basis", "test")
    return E.item(kind, claim, source=f"src_{kind}", ref=f"{kind}-{claim}-{level}-{on}", project_id=P, node=node,
                  levels=levels or [level], on=on, by="Sam Super", shared=shared, **kw)


def three_done():
    """Floors 1-3: attested start and a done at verified / confirmed / attested. Floor 4: started only."""
    return [ev("attested", "started", "FLOOR_1", date(2026, 9, 1)), ev("confirmed", "done", "FLOOR_1", date(2026, 9, 9)),
            ev("attested", "started", "FLOOR_2", date(2026, 9, 12)), ev("attested", "done", "FLOOR_2", date(2026, 9, 22)),
            ev("attested", "in_progress", "FLOOR_3", date(2026, 9, 23)), ev("verified", "done", "FLOOR_3", date(2026, 10, 2)),
            ev("attested", "started", "FLOOR_4", date(2026, 11, 2))]


def fc_of(doc, items=(), rows=()):
    return F.forecast(doc, list(items), list(rows), today=TODAY, project_id=P)


def group(text, key):
    """The lines of one group of status_text."""
    labels = [label for _k, label in F.GROUPS]
    start = text.index(dict(F.GROUPS)[key])
    ends = [text.index(lb) for lb in labels if text.index(lb) > start] + [text.index("Keep these four groups apart")]
    return text[start:min(ends)]


def log_row(day, level, node="drywall"):
    return {"date": day, "nodes": [node], "levels": [level], "generic": False, "sub": "Arkon", "work": "drywall",
            "space": None, "where": "", "log_id": "L", "amended": False}


# ── THE FIXTURES READ AS THEIR FILES SAY ───────────────────────────────────

class RealFormats(unittest.TestCase):

    def test_each_format_carries_the_logic_the_forecast_reads(self):
        for fmt, make in FORMATS.items():
            with self.subTest(fmt=fmt):
                doc = make()
                self.assertEqual(doc["format"], fmt)
                ids = _ids(doc)
                p4 = next(a for a in doc["activities"] if ids[a["id"]] == "P4")
                link = p4["predecessors"][0]
                self.assertEqual((ids[link["id"]], link["type"], link["lag"], link["lag_unit"]), ("D4", "FS", 2.0, "days"))
                self.assertTrue(F.has_logic(doc))

    def test_each_format_without_logic_is_unknown(self):
        for fmt, make in FORMATS.items():
            with self.subTest(fmt=fmt):
                doc = make(with_logic=False)
                self.assertFalse(F.has_logic(doc))
                text = F.status_text(fc_of(doc))
                self.assertIn("The file carries no predecessor logic, so the impact on later work is unknown.", text)
                self.assertEqual(F.estimates(fc_of(doc)), [])

    def test_the_same_answer_from_every_format(self):
        """Ids differ (MS Project uses UIDs); every date, marker and estimate agrees."""
        def strip(doc):
            ids = _ids(doc)
            fc = fc_of(doc, three_done())
            return ([(ids[r["id"]], r["file"]["planned_finish"], r["past_planned_finish_no_done"], bool(r["verified"]["done"]))
                     for r in fc["plan_vs_actual"]],
                    sorted((e["ref"].replace(":", "")[:5], str(e.get("not_before") or e.get("min_days"))) for e in F.estimates(fc)))
        got = {fmt: strip(make()) for fmt, make in FORMATS.items()}
        self.assertEqual(got["xer"][0], got["msp_xml"][0])
        self.assertEqual(got["xer"][0], got["xlsx"][0])
        self.assertEqual(len(got["xer"][1]), len(got["xlsx"][1]))


# ── 1. PLAN VERSUS ACTUAL ─────────────────────────────────────────────────

class PlanVersusActual(unittest.TestCase):

    def setUp(self):
        self.doc = _xer()

    def _row(self, fc, code):
        return next(r for r in fc["plan_vs_actual"] if r["id"] == code)

    def test_baseline_and_current_are_both_the_files_and_never_merged(self):
        r = self._row(fc_of(self.doc), "D4")
        self.assertEqual((r["file"]["baseline_finish"], r["file"]["current_finish"]), ("2026-10-20", "2026-11-03"))
        self.assertEqual((r["file"]["planned_finish"], r["file"]["planned_source"]), (date(2026, 11, 3), "current"))

    def test_each_strong_rung_marks_done(self):
        for kind in ("verified", "confirmed", "attested"):
            with self.subTest(kind=kind):
                r = self._row(fc_of(self.doc, [ev(kind, "done", "FLOOR_4", date(2026, 11, 4))]), "D4")
                self.assertEqual(r["verified"]["done"]["kind"], kind)
                self.assertFalse(r["past_planned_finish_no_done"])

    def test_weaker_rungs_mark_nothing(self):
        for kind in ("observed", "reported", "estimate"):
            with self.subTest(kind=kind):
                items = [ev(kind, "done", "FLOOR_4", date(2026, 11, 4)), ev(kind, "started", "FLOOR_4", date(2026, 10, 6))]
                r = self._row(fc_of(self.doc, items), "D4")
                self.assertEqual((r["verified"]["start"], r["verified"]["done"]), (None, None))
                self.assertTrue(r["past_planned_finish_no_done"])

    def test_reported_spans_are_reports_never_a_finish(self):
        rows = [log_row(date(2026, 10, 6) + timedelta(days=i), "FLOOR_4") for i in range(20)]
        items = [ev("reported", "done", "FLOOR_4", date(2026, 11, 6))]
        fc = fc_of(self.doc, items, rows)
        r = self._row(fc, "D4")
        self.assertEqual((r["reported"]["first"], r["reported"]["last"], r["reported"]["days"]),
                         (date(2026, 10, 6), date(2026, 11, 6), 21))
        self.assertIsNone(r["verified"]["done"])
        self.assertIsNone(r["verified"]["start"])
        self.assertTrue(r["past_planned_finish_no_done"])
        text = F.status_text(fc)
        self.assertIn("Drywall Floor 4 (D4): first reported Oct 6, 2026", group(text, "reported"))
        self.assertNotIn("Drywall Floor 4 (D4):", group(text, "verified"))

    def test_a_failure_after_a_pass_at_the_same_rung_is_not_done(self):
        items = [ev("attested", "done", "FLOOR_4", date(2026, 11, 1)), ev("attested", "failed", "FLOOR_4", date(2026, 11, 3))]
        r = self._row(fc_of(self.doc, items), "D4")
        self.assertIsNone(r["verified"]["done"])
        self.assertEqual(r["verified"]["failed"]["claim"], "failed")

    def test_the_past_planned_finish_line_states_two_records_and_no_cause(self):
        text = F.status_text(fc_of(self.doc))
        self.assertIn("Past the file's planned finish with no done evidence on record (4). Two records side by side, "
                      "not a delay and not a cause:", text)
        self.assertIn("  - Drywall Floor 4 (D4): planned finish 2026-11-03", text)
        self.assertIsNone(re.search(r"(?i)\b(?:delayed|behind schedule|because|caused by|due to)\b", text))

    def test_the_files_own_actual_finish_ends_it(self):
        doc = _xer()
        next(a for a in doc["activities"] if a["id"] == "D4")["actual_finish"] = "2026-11-02"
        self.assertFalse(self._row(fc_of(doc), "D4")["past_planned_finish_no_done"])

    def test_a_generic_activity_is_done_only_when_every_part_is(self):
        doc = {"activities": [{"id": "R", "name": "Rough Plumbing Floor 5", "kind": "task", "current_finish": "2026-11-01",
                               "predecessors": []}]}
        one = fc_of(doc, [ev("attested", "done", "FLOOR_5", date(2026, 10, 30), node="rough_dwv")])
        r = one["plan_vs_actual"][0]
        self.assertIsNone(r["verified"]["done"])
        self.assertEqual((r["verified"]["done_parts"], r["verified"]["parts"]), (1, 2))
        text = F.status_text(one)
        self.assertIn("done on 1 of its 2 parts, not all", text)
        self.assertNotIn("%", text)
        both = fc_of(doc, [ev("attested", "done", "FLOOR_5", date(2026, 10, 30), node="rough_dwv"),
                           ev("attested", "done", "FLOOR_5", date(2026, 10, 31), node="rough_water")])
        self.assertEqual(both["plan_vs_actual"][0]["verified"]["done"]["on"], date(2026, 10, 31))


# ── 2. DOWNSTREAM BY THE FILE'S LOGIC ─────────────────────────────────────

class Downstream(unittest.TestCase):

    def _impact(self, doc, items=()):
        fc = fc_of(doc, items)
        return fc, next(i for i in fc["downstream"]["impacts"] if i["id"] == "P4")

    def test_a_late_activitys_successor_gets_an_estimate_with_its_basis_and_assumption(self):
        fc, i = self._impact(_xer())
        e = i["estimate"]
        self.assertEqual(e["kind"], "estimate")
        # finishes no earlier than Monday Nov 9; FS + 2 working days -> Wed Nov 11, starts the next working day.
        self.assertEqual((e["not_before"], e["planned"], e["shifted"]), (date(2026, 11, 12), date(2026, 11, 5), True))
        self.assertIn("Drywall Floor 4 finishes no earlier than today", e["assumption"])
        self.assertIn("the file's FS link from Drywall Floor 4 (D4) to Prime Floor 4 (P4)", e["basis"])
        text = F.status_text(fc)
        self.assertIn("ESTIMATE: Prime Floor 4 (P4) would start no earlier than 2026-11-12 (file plans 2026-11-05)",
                      group(text, "estimate"))
        self.assertIn("Prime Floor 4 (P4) follows Drywall Floor 4 (D4) by the file's link (FS, lag 2 working days)",
                      group(text, "file"))

    def test_working_days_skip_the_weekend(self):
        self.assertEqual(F._add_working_days(date(2026, 11, 13), 1), date(2026, 11, 16))
        self.assertEqual(F._after_lag(date(2026, 11, 13), 2, "days"), date(2026, 11, 17))
        self.assertEqual(F._after_lag(date(2026, 11, 13), 2, "edays"), date(2026, 11, 15))

    def test_on_a_friday_the_lag_crosses_the_weekend(self):
        friday = date(2026, 11, 13)
        fc = F.forecast(_xer(), [], [], today=friday, project_id=P)
        e = next(i for i in fc["downstream"]["impacts"] if i["id"] == "P4")["estimate"]
        # FS + 2 working days from Fri Nov 13 -> Tue Nov 17; starts the next working day.
        self.assertEqual(e["not_before"], date(2026, 11, 18))

    def test_done_evidence_removes_the_impact(self):
        _fc, = (fc_of(_xer(), [ev("attested", "done", "FLOOR_4", date(2026, 11, 3))]),)
        self.assertNotIn("P4", [i["id"] for i in _fc["downstream"]["impacts"]])

    def test_ss_and_untyped_links_compute_no_date(self):
        for kind, why in (("SS", "hangs off the start"), (None, "no link type")):
            with self.subTest(kind=kind):
                doc = _xer()
                next(a for a in doc["activities"] if a["id"] == "P4")["predecessors"][0]["type"] = kind
                _fc, i = self._impact(doc)
                self.assertIsNone(i["estimate"])
                self.assertIn(why, i["no_estimate"])

    def test_a_percent_or_unitless_lag_computes_no_date(self):
        for unit in ("percent", None):
            with self.subTest(unit=unit):
                doc = _xer()
                next(a for a in doc["activities"] if a["id"] == "P4")["predecessors"][0]["lag_unit"] = unit
                self.assertIsNone(self._impact(doc)[1]["estimate"])

    def test_a_successor_already_started_on_record_is_not_moved(self):
        _fc, i = self._impact(_xer(), [ev("attested", "started", "FLOOR_4", date(2026, 11, 6), node="prime")])
        self.assertIsNone(i["estimate"])

    def test_the_estimate_is_never_written_into_the_files_dates(self):
        doc = _xer()
        before = [dict(a) for a in doc["activities"]]
        fc = fc_of(doc)
        self.assertEqual(doc["activities"], before)
        p4 = next(r for r in fc["plan_vs_actual"] if r["id"] == "P4")
        self.assertEqual(p4["file"]["planned_start"], date(2026, 11, 5))


# ── 3. CYCLE ESTIMATES ─────────────────────────────────────────────────────

class Cycles(unittest.TestCase):

    def _drywall(self, items):
        return next(c for c in fc_of(_xer(), items)["cycles"] if c["node"] == "drywall")

    def test_three_completed_levels_give_a_range_median_sample_and_levels(self):
        c = self._drywall(three_done())
        e = c["estimate"]
        self.assertEqual((e["kind"], e["min_days"], e["max_days"], e["median_days"], e["sample"]), ("estimate", 8, 10, 9, 3))
        self.assertEqual(e["levels_used"], ["FLOOR_1", "FLOOR_2", "FLOOR_3"])
        f = c["finishes"][0]
        self.assertEqual((f["level"], f["earliest"], f["latest"], f["median"]),
                         ("FLOOR_4", date(2026, 11, 10), date(2026, 11, 12), date(2026, 11, 11)))

    def test_fewer_than_three_gives_no_estimate(self):
        items = [i for i in three_done() if "FLOOR_3" not in i["levels"]]
        c = self._drywall(items)
        self.assertIsNone(c["estimate"])
        self.assertEqual((c["no_estimate"], c["sample"], c["finishes"]), (F.NOT_ENOUGH, 2, []))
        text = F.status_text(fc_of(_xer(), items))
        self.assertIn("drywall: not enough completed evidence for an estimate (2 of 4 levels in the file have both a start "
                      "and a done marker; 3 are needed).", text)

    def test_a_level_with_a_done_but_no_start_marker_is_not_a_sample(self):
        items = [i for i in three_done() if not (i["levels"] == ["FLOOR_2"] and i["claim"] == "started")]
        self.assertEqual(self._drywall(items)["sample"], 2)

    def test_reported_and_observed_starts_are_not_start_markers(self):
        items = [i for i in three_done() if not (i["levels"] == ["FLOOR_2"] and i["claim"] == "started")]
        items += [ev("reported", "started", "FLOOR_2", date(2026, 9, 12)), ev("observed", "started", "FLOOR_2", date(2026, 9, 12))]
        self.assertIsNone(self._drywall(items)["estimate"])

    def test_a_statement_about_several_levels_together_is_no_sample(self):
        items = [i for i in three_done() if i["levels"] != ["FLOOR_3"]]
        items += [ev("attested", "started", None, date(2026, 9, 23), shared=True, levels=["FLOOR_3", "FLOOR_5"]),
                  ev("attested", "done", None, date(2026, 10, 2), shared=True, levels=["FLOOR_3", "FLOOR_5"])]
        self.assertIsNone(self._drywall(items)["estimate"])

    def test_crew_counts_and_check_ins_never_move_a_date(self):
        base = F.estimates(fc_of(_xer(), three_done()))
        crowd = [log_row(date(2026, 9, 1) + timedelta(days=i), f"FLOOR_{1 + i % 4}") for i in range(60)]
        noise = [ev("reported", "present", f"FLOOR_{n}", date(2026, 10, n), note="crew of 14") for n in range(1, 5)]
        noise += [ev("observed", "in_progress", f"FLOOR_{n}", date(2026, 10, n + 5)) for n in range(1, 5)]
        noise += [ev("reported", "done", f"FLOOR_{n}", date(2026, 9, 5)) for n in range(1, 5)]
        moved = F.estimates(F.forecast(_xer(), three_done() + noise, crowd, today=TODAY, project_id=P))
        key = lambda es: sorted((e["ref"], str(e.get("not_before")), str(e.get("min_days")), str(e.get("max_days")),  # noqa: E731
                                 str(e.get("earliest")), str(e.get("latest"))) for e in es)
        self.assertEqual(key(base), key(moved))

    def test_a_level_past_its_longest_cycle_gets_no_finish_date(self):
        items = three_done()
        items[-1] = ev("attested", "started", "FLOOR_4", date(2026, 10, 5))
        c = self._drywall(items)
        self.assertEqual(c["finishes"], [])
        self.assertEqual(c["overrun"][0]["level"], "FLOOR_4")
        self.assertIn("no done marker is on record, so no finish estimate is given",
                      F.status_text(fc_of(_xer(), items)))


# ── 4. COMPLETION ──────────────────────────────────────────────────────────

class Completion(unittest.TestCase):

    def test_the_files_latest_finish_is_a_file_fact(self):
        fc = fc_of(_xer(), three_done())
        self.assertTrue(fc["cycles"][0]["finishes"], "a level finish estimate exists, and must not become completion")
        self.assertIsNone(fc["completion"]["estimate"])
        text = F.status_text(fc)
        self.assertIn("- Latest planned finish in the file: 2026-11-12 (current), Prime Floor 4 (P4).", group(text, "file"))
        self.assertIn("no completion forecast", group(text, "estimate"))

    def test_an_estimate_only_when_evidence_covers_the_activity_that_finishes_last(self):
        doc = _xer()
        doc["activities"] = [a for a in doc["activities"] if a["id"] != "P4"]
        fc = fc_of(doc, three_done())
        self.assertEqual(fc["completion"]["last"]["id"], "D4")
        self.assertEqual((fc["completion"]["estimate"]["earliest"], fc["completion"]["estimate"]["latest"]),
                         (date(2026, 11, 10), date(2026, 11, 12)))
        self.assertIn("ESTIMATE, project completion", group(F.status_text(fc), "estimate"))

    def test_the_chain_follows_the_files_links(self):
        self.assertEqual(fc_of(_xer())["completion"]["chain"], ["P4", "D4", "D3", "D2", "D1"])


# ── 5. GROUPS APART ────────────────────────────────────────────────────────

class GroupsApart(unittest.TestCase):

    def test_an_estimate_never_appears_among_facts(self):
        items = three_done() + [ev("estimate", "done", "FLOOR_4", date(2026, 11, 4))]
        fc = fc_of(_xer(), items)
        for r in fc["plan_vs_actual"]:
            for m in (r["verified"]["start"], r["verified"]["done"], r["verified"]["failed"]):
                self.assertTrue(m is None or m["kind"] in F.STRONG)
        text = F.status_text(fc)
        for key in ("verified", "file", "reported"):
            self.assertNotIn("ESTIMATE:", group(text, key))
        self.assertNotIn("src_estimate", text)
        self.assertTrue(all(e["kind"] == "estimate" and e["basis"] for e in F.estimates(fc)))
        sec = F.report_section(fc)
        self.assertEqual([g["key"] for g in sec["groups"]], ["verified", "file", "reported", "estimate"])
        self.assertTrue(all(not ln.startswith("- ESTIMATE") for g in sec["groups"][:3] for ln in g["lines"]))

    def test_no_percent_unless_the_file_states_one(self):
        for fmt, make in FORMATS.items():
            with self.subTest(fmt=fmt):
                self.assertNotIn("%", F.status_text(fc_of(make(), three_done())))

    def test_a_percent_the_file_states_is_labelled_as_the_files(self):
        for make in (_xer, _xlsx):
            with self.subTest(make=make.__name__):
                text = F.status_text(fc_of(make(pct={"D4": 40})))
                self.assertIn("- Drywall Floor 4 (D4): the file states 40% (the file's figure).", group(text, "file"))
                self.assertEqual(text.count("%"), 1)

    def test_the_rule_line_says_what_is_on_record(self):
        self.assertIn("Do not give a forecast, a rate, a percent complete, a delay or a cause: none is on record.",
                      F.status_text(fc_of(_xer(with_logic=False))))
        self.assertIn("Give no forecast, rate or date beyond the ESTIMATE lines", F.status_text(fc_of(_xer(), three_done())))

    def test_the_lookahead_carries_the_status_and_one_rule(self):
        out = F.lookahead_with_status(_xer(), three_done(), [], today=TODAY, days=7, logs_from=date(2026, 8, 12),
                                      project_id=P, job="588")
        self.assertIn("Planned in the next 7 days", out)
        self.assertIn("SCHEDULE STATUS for 588", out)
        self.assertNotIn("No production rate or estimated finish is made", out)
        self.assertEqual(out.count("Keep these four groups apart"), 1)

    def test_an_answer_with_no_evidence_says_so(self):
        text = F.status_text(fc_of(_xer()))
        self.assertIn("- No start or done marker at attested or stronger is on record for any activity in the file.", text)
        self.assertIn("drywall: not enough completed evidence for an estimate", text)


# ── WHAT THE SERVER READS TODAY ────────────────────────────────────────────

class InspectionStatements(unittest.TestCase):

    def _row(self, **kw):
        row = {"_id": "r1", "status": "attested", "gate": "gate_plumbing_rough", "result": "passed", "levels": ["FLOOR_3"],
               "inspected_on": "2026-11-02", "reporter_name": "Sam", "quote": "plumbing rough passed on 3",
               "created_at": datetime(2026, 11, 3)}
        row.update(kw)
        return row

    def test_a_pass_is_an_attested_done_on_the_gate(self):
        (i,) = F.items_from_inspection_reports([self._row()], P)
        self.assertEqual((i["kind"], i["claim"], i["node"], i["levels"], i["on"]),
                         ("attested", "done", "gate_plumbing_rough", ["FLOOR_3"], date(2026, 11, 2)))

    def test_nothing_unresolved_partial_booked_or_ungated_marks_anything(self):
        for kw in ({"status": "unresolved"}, {"status": "document_on_file"}, {"result": "partial"},
                   {"result": "scheduled"}, {"gate": None}, {"levels": []}):
            with self.subTest(kw=kw):
                self.assertEqual(F.items_from_inspection_reports([self._row(**kw)], P), [])

    def test_a_statement_for_several_floors_is_shared(self):
        (i,) = F.items_from_inspection_reports([self._row(levels=["FLOOR_3", "FLOOR_4"])], P)
        self.assertTrue(i["shared"])


if __name__ == "__main__":
    unittest.main()
