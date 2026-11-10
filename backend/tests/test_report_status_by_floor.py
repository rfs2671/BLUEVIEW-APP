"""THE LARGER REPORT: THE BUILDING'S STATUS, BY FLOOR, BY SUB, FROM THE ASSISTANT'S MODEL.

The owner, on what the weekly / monthly report must show: the building's actual
status, overall and by subcontractor, floor and activity, with reported,
observed, confirmed / attested, verified and unknown kept apart; no percent
unless a source states it; no cause of delay; unknown never shown as not done;
estimates labelled and apart from the schedule file; every visual readable from
a one-line legend (CHECK / ADVANCED / NEW / DOWN were removed because nobody
could read them).

What is asserted:
  * the status-by-floor page, in the larger report only, is a matrix of
    lib/project_progress.py's cells: one mark per cell with a record, its
    shape from the cell's evidence.status(), an EMPTY cell for unknown, top
    floor first, and a one-line legend and a footnote saying what empty means;
  * the whole-building line shows a DOB sign-off as verified, with its date or
    the fact that the date is not stored;
  * the sub lines under the schedule chart, open on the record and records
    that disagree come from the same model;
  * no percent unless the line names the source that states it;
  * LeveLog's estimates only inside their labelled box;
  * the stored snapshot holds every cell's status and the evidence ids;
  * server.build_project_report renders the model server._project_progress
    returns: the assistant's, not a second build.

CONTROL: against origin/feat/progress-integrated (86e02e5a)'s four source files
(lib/progress_report_render.py, lib/progress_report.py, lib/project_progress.py,
server.py), 21 fail and 0 pass (run 2026-11-10).
"""

from __future__ import annotations

import json
import os
import re
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import evidence as E  # noqa: E402
from lib import forecast as FC  # noqa: E402
from lib import progress_report as P  # noqa: E402
from lib import progress_report_render as RR  # noqa: E402
from lib import project_progress as PPG  # noqa: E402
from tests import progress_588_fixture as PF  # noqa: E402
from tests import report_588 as F  # noqa: E402

PCT = re.compile(r"\d\s?%")


def _items():
    """The 588 progress fixture, plus what it lacks: DOB sign-offs (one with
    no stored date) and a confirmed pour."""
    return PF.items() + [
        E.item("verified", "done", source="dob_logs", ref="B00911223-I1", project_id=PF.PID, node="demolition",
               levels=[], on=date(2026, 6, 18)),
        E.item("verified", "done", source="dob_logs", ref="B00911230-I1", project_id=PF.PID, node="foundation",
               levels=[], on=None),
        E.item("confirmed", "done", source="logbooks", ref="pour-0806", project_id=PF.PID, node="superstructure",
               levels=["FLOOR_1"], on=date(2026, 8, 6), by="Competent person", sub="Metro Concrete"),
        E.item("verified", "done", source="dob_logs", ref="B00911240-I1", project_id=PF.PID, node="superstructure",
               levels=["FLOOR_2"], on=date(2026, 8, 25)),
    ]


def _model(items=None, project=None, schedule=None):
    return PPG.build(_items() if items is None else items, today=PF.TODAY, project=project or PF.PROJECT,
                     schedule=schedule, job="588 Thomas")


def _rep(model=None, forecast=None, **over):
    rep = F.report(**over)
    rep["progress_model"] = _model() if model is None else model
    rep["forecast"] = forecast
    return rep


def _html(rep):
    return RR.render_html([rep], gc="", title="t", now=F.NOW, images={})


def _floor_page(html):
    m = re.search(r"<section class='pg fs'><h2>Status by floor</h2>.*?</section>", html, re.S)
    return m.group(0) if m else ""


def _forecast_with_estimates():
    """A confirmed schedule whose framing has start and done markers on three
    floors (a cycle range) and a start on the fourth (a finish range)."""
    items = _items()
    for lv, s, e in (("FLOOR_1", date(2026, 9, 28), date(2026, 10, 9)), ("FLOOR_2", date(2026, 10, 1), date(2026, 10, 13)),
                     ("FLOOR_3", date(2026, 10, 5), date(2026, 10, 15))):
        items += [PF.said("started", "framing", [lv], s, f"st-{lv}", "x"), PF.said("done", "framing", [lv], e, f"dn-{lv}", "x")]
    items.append(PF.said("started", "framing", ["FLOOR_4"], date(2026, 10, 12), "st-FLOOR_4", "x"))
    sched = F.schedule_doc()
    fc = FC.forecast(sched, items, [], today=F.END, project_id=PF.PID)
    return _model(items, schedule=sched), FC.report_section(fc)


def _signature():
    """Each mark's signature in the matrix SVG (a cell background is fill="#f1f4f8")."""
    return {"verified": f'height="9.2" fill="{RR.NAVY}"', "confirmed": f'r="4.6" fill="{RR.NAVY}"',
            "attested": "<polygon ", "observed": 'fill="#fff" stroke=', "reported": f'rx="1" fill="{RR.MUTED}"',
            "failed": 'stroke="#B42318"'}


class ThePage(unittest.TestCase):

    def test_it_is_in_the_larger_report_only(self):
        rep = _rep()
        self.assertTrue(_floor_page(_html(rep)))
        short = dict(rep, end=rep["start"] + timedelta(days=RR.GANTT_MIN_DAYS - 2))
        self.assertEqual(RR._status_by_floor(short), "")
        self.assertEqual(RR._sub_status(short), "")

    def test_a_mark_per_cell_with_a_record_and_an_empty_cell_for_unknown(self):
        model = _model()
        cols = RR.floor_columns(model)
        svg = RR.floor_matrix_svg(model, cols)
        cells = [model["cells"][(lv["level"], s["id"])] for lv in model["frame"]["levels"] for s in cols]
        SIGNATURE = _signature()
        self.assertEqual(svg.count('fill="#f1f4f8"'), len(cells), "every cell drawn, known or not")
        for kind, sig in SIGNATURE.items():
            with self.subTest(kind=kind):
                want = sum(1 for c in cells if RR.mark_of(c["status"]) == kind)
                self.assertEqual(svg.count(sig), want)
        self.assertTrue(all(sum(1 for c in cells if RR.mark_of(c["status"]) == k) for k in SIGNATURE),
                        "the fixture has every kind of mark")
        unknown = sum(1 for c in cells if c["status"] == "unknown")
        self.assertGreater(unknown, 0)
        self.assertEqual(sum(svg.count(s) for s in SIGNATURE.values()), len(cells) - unknown)

    def test_unknown_is_never_worded_as_not_done(self):
        page = _floor_page(_html(_rep()))
        self.assertIn(RR.UNKNOWN_NOTE, page)
        rest = page.replace(RR.UNKNOWN_NOTE, "")
        self.assertIsNone(re.search(r"not done|not started|incomplete|outstanding|behind|delay", rest, re.I))

    def test_the_legend_is_one_line_of_every_mark(self):
        legend = RR.floor_legend()
        # Every kind of mark the matrix can draw, drawn in the legend (not read off MARKS itself).
        self.assertEqual(legend.count("<span class='lg'>"), 6)
        for kind, sig in _signature().items():
            with self.subTest(kind=kind):
                self.assertIn(sig.replace('height="9.2"', 'height="8.0"').replace('r="4.6"', 'r="4.0"')
                              .replace('rx="1"', 'height="2.6" rx="1"'), legend)
        for _kind, words in RR.MARKS:
            self.assertIn(words, legend)
        self.assertIn("white-space: nowrap", RR.CSS[RR.CSS.index(".mlegend {"):][:60])
        page = _floor_page(_html(_rep()))
        self.assertIn(legend, page)

    def test_top_floor_first_roof_on_top_cellar_at_the_bottom(self):
        model = _model()
        svg = RR.floor_matrix_svg(model, RR.floor_columns(model))
        rows = re.findall(r'font-size="8.5" font-weight="700" fill="[^"]+">([^<]+)<', svg)
        self.assertEqual(rows, ["Roof", "Floor 4", "Floor 3", "Floor 2", "Floor 1", "Cellar"])

    def test_columns_are_steps_on_record_and_the_standard_interior_steps_in_sequence_groups(self):
        model = _model()
        ids = [s["id"] for s in RR.floor_columns(model)]
        self.assertIn("rough_sprinkler", ids, "a conditional step with a record")
        self.assertNotIn("rough_gas", ids, "a conditional step with none")
        self.assertIn("zone_final", ids, "a standard interior step with no record")
        self.assertIn("superstructure", ids, "a site / structure step with a record")
        self.assertNotIn("windows", ids, "a site / structure step with none")
        self.assertEqual(ids[0], "superstructure")
        self.assertLess(ids.index("framing"), ids.index("gate_plumbing_rough"))
        self.assertLess(ids.index("gate_plumbing_rough"), ids.index("drywall"))

    def test_a_tall_job_is_a_list_per_level(self):
        model = _model(project=dict(PF.PROJECT, building_stories=15))
        page = _floor_page(_html(_rep(model=model)))
        self.assertNotIn('<svg class="chart fm"', page)
        self.assertIn("<td class='lv'>Floor 15</td>", page)
        self.assertIn(RR.UNKNOWN_NOTE_LIST, page)


class TheWholeBuilding(unittest.TestCase):

    def test_a_dob_sign_off_is_verified_with_its_date(self):
        html = RR._whole_building(_model())
        self.assertIn("DOB sign-off, Jun 18, 2026 (filing B00911223-I1)", html)
        self.assertIn("DOB sign-off, sign-off date not on the stored record (filing B00911230-I1)", html)
        self.assertEqual(html.count(f'fill="{RR.NAVY}"/></svg>&nbsp;<b>'), 2)

    def test_excavation_with_no_record_is_shown_unknown(self):
        html = RR._whole_building(_model())
        self.assertIn("<b>Excavation / SOE</b> <span class='muted'>no record</span>", html)


class FromTheModel(unittest.TestCase):

    def test_the_sub_lines_under_the_schedule_chart(self):
        rep = _rep()
        html = RR._progress(rep, {})
        self.assertIn("<h3>What the records show, by subcontractor</h3>", html)
        for name, s in rep["progress_model"]["subs"].items():
            with self.subTest(sub=name):
                self.assertIn(RR._e(name), html)
        self.assertIn("On site with no work step on record: Slate Windows.", html)
        arkon = re.search(r"<td class='sn'>Arkon Builders</td><td>(.*?)</td>", html).group(1)
        self.assertIn("<polygon ", arkon, "framing on 1-2 stated done")
        self.assertIn("Floors 1–2", arkon)

    def test_open_on_the_record_and_records_that_disagree(self):
        model = _model()
        page = _floor_page(_html(_rep(model=model)))
        self.assertIn("inspection failed on record: plumbing rough inspection", page)
        self.assertIn(f"<h3>Records that disagree ({len(model['conflicts'])})</h3>", page)
        for c in model["conflicts"][:6]:
            self.assertIn(RR._e(c["what"]), page)

    def test_no_confirmed_schedule_is_one_line(self):
        page = _floor_page(_html(_rep()))
        self.assertIn(RR.NO_SCHEDULE_LINE, page)
        self.assertNotIn("<h2>Schedule status against the confirmed file", _html(_rep()))

    def test_a_model_that_could_not_be_read_is_said_so(self):
        rep = _rep(model={})
        rep["progress_model"], rep["progress_unavailable"] = None, True
        page = RR._status_by_floor(rep)
        self.assertIn("could not be read", page)
        self.assertNotIn('<svg class="chart fm"', page)


class NoPercentUnlessASourceStatesIt(unittest.TestCase):

    def test_none_without_a_schedule(self):
        rep = _rep()
        self.assertIsNone(PCT.search(_floor_page(_html(rep))))
        self.assertIsNone(PCT.search(RR._sub_status(rep)))

    def test_with_a_schedule_every_percent_names_its_source(self):
        model, sec = _forecast_with_estimates()
        html = RR._forecast_section(_rep(model=model, forecast=sec))
        lines = re.findall(r"<li>(.*?)</li>", html)
        with_pct = [ln for ln in lines if PCT.search(ln)]
        self.assertTrue(with_pct, "the fixture's file states percents")
        for ln in with_pct:
            self.assertIn("the file states", ln)


class EstimatesOnlyInTheirBox(unittest.TestCase):

    def test_only_inside_the_labelled_box(self):
        model, sec = _forecast_with_estimates()
        self.assertTrue(sec["estimates"], "the fixture has estimates")
        html = _html(_rep(model=model, forecast=sec, schedule=True))
        box = re.search(r"<div class='estbox'>.*?</ul></div>", html, re.S).group(0)
        self.assertIn("<h4>Estimates: computed by LeveLog, not verified</h4>", box)
        rest = html.replace(box, "")
        self.assertIsNone(re.search(r"ESTIMATE\b", rest))
        for e in sec["estimates"]:
            for k in ("earliest", "latest", "not_before"):
                if e.get(k):
                    with self.subTest(estimate=e["ref"], field=k):
                        self.assertIn(e[k].isoformat(), box)
                        self.assertNotIn(e[k].isoformat(), rest)
        self.assertIn("from 3 levels", box, "the sample size")
        self.assertIn("Basis:", box)
        self.assertNotIn(RR.NO_SCHEDULE_LINE, html)


class TheSnapshot(unittest.TestCase):

    def test_every_cell_status_and_the_evidence_ids_no_words(self):
        model = _model()
        snap = P.snapshot(_rep(model=model))
        json.dumps(snap)
        prog = snap["progress"]
        self.assertEqual(len(prog["cells"]), len(model["cells"]))
        self.assertEqual(prog["cells"]["FLOOR_3|gate_plumbing_rough"], "failed_attested")
        self.assertEqual(prog["cells"]["ROOF|framing"], "unknown")
        ev = prog["evidence"]["FLOOR_3|gate_plumbing_rough"]
        self.assertEqual(ev["refs"], ["wa-1103", "wa-1028"])
        self.assertEqual(ev["decided_by"], "wa-1103")
        self.assertNotIn("ROOF|framing", prog["evidence"])
        self.assertEqual(prog["building"]["demolition"]["status"], "done_verified")
        self.assertEqual(prog["building"]["demolition"]["refs"], ["B00911223-I1"])
        self.assertEqual(len(prog["conflicts"]), len(model["conflicts"]))
        self.assertIn("Arkon Builders", prog["subs"])
        dumped = json.dumps(prog)
        self.assertNotIn('"quote"', dumped)
        for i in _items():
            if i.get("quote"):
                self.assertNotIn(i["quote"], dumped)

    def test_the_forecast_groups_and_estimates_are_stored(self):
        model, sec = _forecast_with_estimates()
        snap = P.snapshot(_rep(model=model, forecast=sec))
        json.dumps(snap)
        self.assertEqual([g["key"] for g in snap["forecast"]["groups"]], ["verified", "file", "reported", "estimate"])
        self.assertEqual(len(snap["forecast"]["estimates"]), len(sec["estimates"]))

    def test_none_when_there_is_no_model(self):
        rep = F.report()
        self.assertIsNone(P.snapshot(rep)["progress"])


class TheServerBuildsFromTheAssistantsModel(unittest.TestCase):
    """build_project_report renders the dict server._project_progress returns:
    the model the assistant's project_status tool answers from."""

    def _build(self, spy):
        os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
        os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
        os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")
        import server
        from tests.test_project_reports import NOW, _Reports
        from tests.test_whatsapp_dm_assistant import THOMAS
        from tests.test_whatsapp_morning_brief import _world
        from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx, _run
        r = _Reports()
        r.setUp()
        db = _world()
        ps = r.patches() + [patch.object(server, "_project_progress", spy(server._project_progress))]
        for p in ps:
            p.start()
        try:
            with _Ctx(db):
                project = _run(db.projects.find_one({"_id": THOMAS}))
                return _run(server.build_project_report(CO_A, [project], date(2026, 10, 1), date(2026, 10, 14),
                                                        now=NOW, by="t", source="dry_run", dry_run=True))
        finally:
            for p in reversed(ps):
                p.stop()

    def test_the_same_model_object(self):
        seen = []

        def spy(real):
            async def wrapped(*a, **k):
                m = await real(*a, **k)
                seen.append((m, k))
                return m
            return wrapped
        got = self._build(spy)
        self.assertEqual(len(seen), 1)
        model, kw = seen[0]
        self.assertIs(got["reports"][0]["progress_model"], model)
        self.assertEqual(kw["today"], date(2026, 10, 14))
        self.assertIn("<h2>Status by floor</h2>", got["html"])
        self.assertEqual(len(got["snapshot"][0]["progress"]["cells"]), len(model["cells"]))

    def test_a_model_that_fails_is_said_so_and_the_report_still_goes(self):
        def spy(_real):
            async def boom(*a, **k):
                raise RuntimeError("mongo down")
            return boom
        got = self._build(spy)
        self.assertTrue(got["snapshot"][0]["progress_unavailable"])
        self.assertIn("could not be read for this report", got["html"])


if __name__ == "__main__":
    unittest.main()
