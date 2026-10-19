"""The unified progress report, on the 588 fixture (tests/report_588.py).

  * Every number is the records' (counted again here, independently), for the
    period and for the previous period of the same length.
  * The daily logs are read as amended; gate and log headcounts are
    reconciled, never averaged away; blank-company rows are not subs.
  * What the GC keeps internal is NOT in it: chat, commitments, punch items,
    individual workers, free-text observations -- passing them changes
    nothing. Nothing is sent to a language model.
  * Photos: 4-6 at most, real daily-log photos only, no before/after, never
    more than two of one sub.
  * Schedule and financial sections exist only when a person confirmed the
    data; a percent complete is the schedule file's own or nothing.
  * One engine for every cadence: only the chart granularity changes.
  * The facts are storable (the snapshot) and every claim has an evidence id.
"""

from __future__ import annotations

import json
import os
import re
import unittest
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from lib import progress_report as P  # noqa: E402
from lib import progress_report_render as RR  # noqa: E402
from tests import report_588 as F  # noqa: E402

SNAP = os.path.join(os.path.dirname(__file__), "fixtures", "report_588_unified.snap.txt")
NO_GOOD = re.compile(r"man[- ]?days?|\d\s?%|percent", re.IGNORECASE)


def rep(**kw):
    return F.report(**kw)


def counted(checkins, start, end):
    """Workers per day, counted again from the raw check-ins (once a day)."""
    per = defaultdict(lambda: defaultdict(set))
    for c in checkins:
        d = c["check_in_time"].astimezone(F.NY).date()
        if start <= d <= end:
            per[d][c["worker_company"]].add(c["worker_id"])
    return {d: sum(len(v) for v in by.values()) for d, by in per.items()}


class TheNumbersAreTheRecords(unittest.TestCase):

    def test_site_counted_again(self):
        totals = counted(F.checkins(), F.START, F.END)
        site = rep()["site"]
        self.assertEqual(site["worked"], len(totals))
        self.assertEqual(site["avg"], round(sum(totals.values()) / len(totals), 1))
        self.assertEqual((site["peak"], site["peak_day"]), (37, date(2026, 10, 15)))
        self.assertEqual([r["total"] for r in site["table"]], [totals[d] for d in sorted(totals)])

    def test_the_previous_period_is_counted_from_the_same_rows(self):
        totals = counted(F.previous_checkins(), F.PREV_START, F.PREV_END)
        prev = rep()["prev"]
        self.assertEqual(prev["days"], len(totals))
        self.assertEqual(prev["avg"], round(sum(totals.values()) / len(totals), 1))
        self.assertEqual(prev["peak"], max(totals.values()))

    def test_each_sub(self):
        subs = {s["name"]: s for s in rep()["subs"]}
        self.assertEqual(list(subs), ["Arkon Builders", "Quality Plumbing", "Power Direct", "J&G Scaffolding"])
        for name, days in F.CREWS.items():
            s = subs[name]
            self.assertEqual(s["days"], sorted(days))
            self.assertEqual((s["max"], s["avg"]), (max(days.values()), round(sum(days.values()) / len(days), 1)))

    def test_working_days_exclude_a_holiday_nobody_worked(self):
        # Oct 12 (Columbus Day) was worked in the fixture, so it still counts;
        # with nobody there it is not a day the site "missed".
        base = rep()
        self.assertEqual((base["site"]["worked"], base["site"]["possible"]), (10, 10))
        cks = [c for c in F.checkins() if c["check_in_time"].astimezone(F.NY).date() != date(2026, 10, 12)]
        logs = [lg for lg in F.logbooks() if lg["date"] != "2026-10-12"]
        r = rep(**{**F.unified_rows(), "checkins": cks + F.previous_checkins(), "logbooks": logs + F.previous_logbooks()})
        self.assertEqual((r["site"]["worked"], r["site"]["possible"]), (9, 9))
        self.assertIn("Columbus Day (Oct 12)", r["site"]["holidays"])

    def test_working_days_start_with_the_job(self):
        from lib import report_calendar as C
        days = C.working_days(date(2026, 10, 1), date(2026, 10, 9), first_activity=date(2026, 10, 5))
        self.assertEqual(days[0], date(2026, 10, 5))     # not the days before the job began
        self.assertEqual(len(days), 5)

    def test_the_overview_says_only_what_the_numbers_say(self):
        r = rep()
        text = " ".join(r["overview"] + [c["text"] for c in r["changes"]])
        self.assertIn(f"{r['site']['worked']} of {r['site']['possible']} working days", text)
        self.assertIn(f"{r['site']['avg']:g} workers a day", text)
        self.assertIn(f"peak of {r['site']['peak']}", text)
        self.assertIsNone(NO_GOOD.search(text), text)


class TheChangeSinceTheLastPeriod(unittest.TestCase):

    def test_mobilization(self):
        m = rep()["mobilization"]
        self.assertTrue(m["comparable"])
        self.assertEqual({x["name"] for x in m["new"]}, {"Quality Plumbing", "Power Direct"})
        self.assertEqual([x["name"] for x in m["gone"]], ["Metro Demolition"])
        self.assertEqual([(x["name"], x["direction"]) for x in m["changed"]], [("Arkon Builders", "up")])

    def test_what_advanced_and_what_began(self):
        work = {w["name"]: w for w in rep()["work"]}
        arkon = work["Arkon Builders"]["items"][0]
        self.assertEqual((arkon["status"], arkon["floors"], arkon["new_floors"]), ("advanced", [1, 2, 3, 4], [2, 3, 4]))
        self.assertEqual(work["Quality Plumbing"]["items"][0]["status"], "new")
        self.assertEqual(work["J&G Scaffolding"]["items"][0]["status"], "continued")

    def test_a_first_period_asserts_no_change(self):
        # The previous period holds nothing: nobody is "new", nothing
        # "advanced", the workforce did not "rise".
        r = F.report(checkins=F.checkins(), logbooks=F.logbooks())
        self.assertFalse(r["mobilization"]["comparable"])
        self.assertEqual({i["status"] for w in r["work"] for i in w["items"]}, {"reported"})
        self.assertFalse([c for c in r["changes"] if c["src"] in ("G", "L")])
        self.assertNotIn("previous", " ".join(r["overview"]))

    def test_the_chart_compares_by_position_and_follows_the_cadence(self):
        r = rep()
        self.assertEqual(r["grain"], "day")
        self.assertEqual(len(r["site"]["series"]), 14)
        self.assertEqual(len(r["site"]["prev_series"]), 14)
        self.assertEqual([P.bucket_for(n) for n in (7, 14, 21, 22, 90, 125, 126, 365)],
                         ["day", "day", "day", "week", "week", "week", "month", "month"])
        weekly = P.series({date(2026, 10, 5): 10, date(2026, 10, 6): 20, date(2026, 10, 14): 30},
                          [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 14)],
                          date(2026, 10, 5), date(2026, 10, 18), "week")
        self.assertEqual([(b["start"], b["avg"], b["days"]) for b in weekly],
                         [(date(2026, 10, 5), 15.0, 2), (date(2026, 10, 12), 30.0, 1)])


def _head(doc_id, day, workers, *, chain=1, reason=None, competing=0, company="Arkon Builders", extra=None):
    return {"_id": doc_id, "date": day, "_chain_length": chain, "_amendment_reason": reason,
            "_competing": competing, "status": "submitted", "created_at": datetime(2026, 10, 7, tzinfo=timezone.utc),
            "data": {"activities": [{"company": company, "trade": "Framing", "num_workers": workers,
                                     "work_description": "Framing", "work_locations": "Floor 2", "photos": []}],
                     **(extra or {})}}


class TheDaysAreAsAmended(unittest.TestCase):

    def test_an_amended_day_is_read_from_its_amendment_and_says_so(self):
        logs = [lg for lg in F.logbooks() if lg["date"] != "2026-10-06"] + [
            _head("a1", "2026-10-06", 9, chain=2, reason="crew count corrected")]
        r = F.report(logbooks=logs + F.previous_logbooks())
        self.assertIn(date(2026, 10, 6), r["log_set"]["amended"])
        arkon = next(w for w in r["work"] if w["name"] == "Arkon Builders")["items"][0]
        self.assertTrue(arkon["amended"])
        self.assertTrue(any("amended after filing" in n and "Oct 6" in n for n in r["data_notes"]), r["data_notes"])
        ref = next(e for e in r["evidence"] if e["id"] == "L")["refs"]
        self.assertEqual([x["reason"] for x in ref if x["amended"]], ["crew count corrected"])

    def test_two_heads_for_one_day_are_one_day(self):
        a, b = _head("x1", "2026-10-06", 5), _head("x2", "2026-10-06", 7)
        b["created_at"] = datetime(2026, 10, 8, tzinfo=timezone.utc)
        got = P.effective_logs([a, b])
        self.assertEqual(([lg["_id"] for lg in got["items"]], got["duplicates"]), (["x2"], 1))

    def test_competing_corrections_are_named(self):
        r = F.report(logbooks=F.logbooks() + F.previous_logbooks() + [])
        logs = [_head("c1", "2026-10-06", 9, chain=2, competing=1)]
        got = P.effective_logs(logs)
        self.assertEqual(got["competing"], 1)
        r = F.report(logbooks=logs)
        self.assertTrue(any("competing corrections" in n for n in r["data_notes"]))


class GateAndLogsAreReconciled(unittest.TestCase):

    def rows(self, checkins, logs):
        return F.report(checkins=checkins, logbooks=logs, dob_rows=[], dot_rows=[], events=[])

    def gate(self, company, day, n, tag="g"):
        return [{"worker_id": f"{tag}{i}", "worker_company": company, "check_in_time": F._at(day, 7, i)} for i in range(n)]

    def test_a_crew_only_in_the_log_is_counted_from_the_log_and_marked(self):
        d = date(2026, 10, 6)
        r = self.rows([], [_head("l1", d.isoformat(), 6)])
        sub = r["subs"][0]
        self.assertEqual((sub["name"], sub["counts"][d], sub["log_days"]), ("Arkon Builders", 6, 1))
        self.assertTrue(any("no gate check-ins" in n for n in r["data_notes"]), r["data_notes"])

    def test_a_variance_is_counted_not_averaged_away(self):
        d = date(2026, 10, 6)
        r = self.rows(self.gate("Arkon Builders", d, 12), [_head("l1", d.isoformat(), 5)])
        self.assertEqual(r["recon"]["variance"], 1)
        self.assertEqual(r["subs"][0]["counts"][d], 12)                     # the gate's count stands
        self.assertTrue(any("12 checked in, 5 logged" in n for n in r["data_notes"]), r["data_notes"])

    def test_close_counts_agree(self):
        d = date(2026, 10, 6)
        r = self.rows(self.gate("Arkon Builders", d, 12), [_head("l1", d.isoformat(), 11)])
        self.assertEqual((r["recon"]["aligned"], r["recon"]["variance"]), (1, 0))

    def test_unassigned_workers_are_counted_in_the_site_but_are_not_a_sub(self):
        d = date(2026, 10, 6)
        r = self.rows(self.gate("UNASSIGNED", d, 4, "u") + self.gate("Arkon Builders", d, 6), [])
        self.assertEqual([s["name"] for s in r["subs"]], ["Arkon Builders"])
        self.assertEqual(r["site"]["table"][0]["total"], 10)
        self.assertEqual(r["recon"]["unassigned_checkins"], 4)
        self.assertTrue(any("no company assigned" in n for n in r["data_notes"]))

    def test_a_log_row_with_no_company_is_not_a_sub(self):
        d = date(2026, 10, 6)
        r = self.rows(self.gate("Arkon Builders", d, 6), [_head("l1", d.isoformat(), 3, company="")])
        self.assertEqual([s["name"] for s in r["subs"]], ["Arkon Builders"])
        self.assertTrue(any("named no company" in n for n in r["data_notes"]))

    def test_a_sub_named_two_ways_is_one_sub(self):
        d = date(2026, 10, 6)
        r = self.rows(self.gate("Arkon Builders LLC", d, 6), [_head("l1", d.isoformat(), 6, company="Arkon")])
        self.assertEqual(len(r["subs"]), 1)


class WhatTheGcKeepsInternal(unittest.TestCase):
    """Chat, commitments, punch items, individual workers and free-text
    observations are not report material. Passing them changes nothing."""

    def html(self, **kw):
        r = F.report(**kw)
        return r, RR.render_html([r], gc=F.GC, title="t", now=F.NOW, images={})

    def test_passing_the_internal_records_changes_nothing(self):
        plain = F.report()
        internal = F.rows()
        with_internal = F.report(chat=internal.get("chat"), commitments=internal.get("commitments"),
                                 punch_items=internal.get("punch_items"))      # ignored by compute
        self.assertEqual(json.dumps(P.snapshot(plain), sort_keys=True, default=str),
                         json.dumps(P.snapshot(with_internal), sort_keys=True, default=str))

    def test_none_of_it_is_printed(self):
        _, html = self.html()
        for gone in ("Scaffold on the front is up", "bot line", "Send revised electrical shop drawings",
                     "Pressure test risers", "Fire-blocking", "Concrete delivery for stair 2",
                     "Power Direct short 2 workers", "worker 1", "worker 12", "Late commitment",
                     "Punch walkthrough", "P-588"):
            self.assertNotIn(gone, html, gone)
        self.assertIsNone(re.search(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b", html))

    def test_only_structured_inspections_are_reported(self):
        logs = F.logbooks()
        logs[2]["data"]["checklist_items"] = {"perimeter_fence": {"result": "fail", "note": "Gate chained by Mr. Ruiz"},
                                              "fire_safety": {"result": "pass"}, "plans": {"result": "not_walked"}}
        r, html = self.html(logbooks=logs + F.previous_logbooks())
        self.assertEqual((r["inspections"]["walked"], r["inspections"]["failed"]), (2, 1))
        self.assertIn("Perimeter fence", html)
        self.assertNotIn("Mr. Ruiz", html)
        self.assertTrue(any(x["level"] == "high" and "inspection" in x["text"] for x in r["risks"]))

    def test_the_words_never_in_a_report(self):
        r = F.report(schedule=True)
        text = " ".join(r["overview"] + [c["text"] for c in r["changes"]] + [x["text"] for x in r["risks"]])
        self.assertIsNone(NO_GOOD.search(text), text)


class ThePhotographs(unittest.TestCase):

    def test_only_clear_progress_photos_four_to_six_never_a_pair(self):
        r = rep()
        photos = r["photos"]
        self.assertTrue(photos and len(photos) <= P.MAX_PHOTOS)
        self.assertEqual({p["sub"] for p in photos} <= set(F.CREWS), True)
        verdicts = F.verdicts()
        for p in photos:
            self.assertTrue(verdicts[p["key"]]["ok"], p["key"])
            self.assertNotIn("pair", p)
        self.assertFalse([p for p in photos if verdicts[p["key"]]["kind"] in ("people", "document", "blurry")])
        self.assertEqual(len({(p["sub"], p["date"], p["where"]) for p in photos}), len(photos))

    def test_never_more_than_two_of_one_sub(self):
        cands = []
        for i in range(8):
            cands.append({"key": f"k{i}", "date": date(2026, 10, 2) + timedelta(days=i), "sub": "Arkon Builders",
                          "trade": "Framing", "where": f"floor {i}", "words": "Framing", "work": "Framing",
                          "source": "daily log", "log_id": "x"})
        ver = {c["key"]: {"ok": True, "kind": "progress", "score": 5 + i % 3} for i, c in enumerate(cands)}
        self.assertEqual(len(P.pick_photos(cands, ver)), P.MAX_PER_SUB)

    def test_every_sub_is_represented_before_one_gets_two(self):
        cands = []
        for sub, n in (("Arkon Builders", 4), ("Quality Plumbing", 2), ("Power Direct", 2)):
            for i in range(n):
                cands.append({"key": f"{sub}{i}", "date": date(2026, 10, 2) + timedelta(days=i), "sub": sub,
                              "trade": "", "where": f"floor {i}", "words": "x", "work": "x", "source": "daily log",
                              "log_id": "l"})
        ver = {c["key"]: {"ok": True, "kind": "progress", "score": 9 if c["sub"] == "Arkon Builders" else 5}
               for c in cands}
        got = P.pick_photos(cands, ver)
        self.assertEqual({p["sub"] for p in got}, {"Arkon Builders", "Quality Plumbing", "Power Direct"})
        self.assertEqual(len(got), 6)

    def test_the_caption_is_the_logs_words_not_the_models(self):
        verdicts = {k: {**v, "caption": "A MODEL CAPTION"} for k, v in F.verdicts().items()}
        r = F.report()
        got = P.pick_photos(r["photo_candidates"], verdicts)
        self.assertTrue(got and not [p for p in got if "MODEL" in p["caption"]])
        self.assertTrue(any(" — " in p["caption"] for p in got))

    def test_unscreened_photos_are_not_shown(self):
        self.assertEqual(P.pick_photos(rep()["photo_candidates"], {}), [])

    def test_a_photo_without_a_company_is_not_used(self):
        logs = F.logbooks()
        logs[0]["data"]["activities"][0]["company"] = ""
        r = F.report(logbooks=logs + F.previous_logbooks())
        self.assertTrue(all(c["sub"] for c in r["photo_candidates"]))

    def test_the_pdf_has_no_photo_section_without_photos(self):
        r = rep()
        r["photos"] = []
        self.assertNotIn("Visual progress", RR.render_html([r], gc="", title="t", now=F.NOW, images={}))


class TheScheduleIsTheFilesOrNothing(unittest.TestCase):

    def test_without_a_schedule_there_is_no_section_and_no_percent(self):
        r = rep()
        html = RR.render_html([r], gc="", title="t", now=F.NOW, images={})
        self.assertIsNone(r["schedule"])
        self.assertNotIn("Schedule and completion", html)
        self.assertIn("Not provided", html)
        self.assertTrue(any("No confirmed project schedule" in x for x in r["limitations"]))
        self.assertTrue(any(o.startswith("Schedule — no confirmed project schedule") for o in r["overview"]))

    def test_a_confirmed_schedule_reports_its_own_dates_and_counts(self):
        r = rep(schedule=True)
        plan = r["schedule"]
        self.assertTrue(plan["usable"])
        self.assertEqual(plan["counts"], {"activities": 11, "complete": 3, "in_progress": 4, "not_started": 4})
        self.assertEqual((plan["project"]["baseline_finish"], plan["project"]["forecast_finish"],
                          plan["project"]["variance_days"]), (date(2027, 2, 26), date(2027, 3, 12), 14))
        self.assertEqual([m["name"] for m in plan["milestones"]["upcoming"]],
                         ["Rough plumbing inspection", "Framing complete, floors 1-4"])
        html = RR.render_html([r], gc="", title="t", now=F.NOW, images={})
        self.assertIn("Schedule and completion", html)
        self.assertIn("588 Master Schedule.xlsx", html)
        self.assertIn("confirmed by Site PM", html)
        self.assertEqual(r["schedule"]["source_name"], "588 Master Schedule.xlsx")

    def test_no_percent_is_computed_from_activity_percents(self):
        # NEGATIVE CONTROL: the fixture schedule has activity percents (100,
        # 85, 40, 70, 55 ...) and no project summary row. A report that
        # averaged them -- or counted days, workers or photos -- would print a
        # number. It prints none: a percent is the FILE's, or nothing.
        r = rep(schedule=True)
        self.assertIsNone(r["schedule"]["project"]["reported_percent"])
        html = RR.render_html([r], gc="", title="t", now=F.NOW, images={})
        self.assertNotIn("% complete", html.replace("(count, not a percent)", ""))
        text = " ".join(r["overview"])
        self.assertIsNone(re.search(r"\d\s?%", text), text)

    def test_a_percent_the_file_reports_is_attributed_to_the_file(self):
        doc = F.schedule_doc()
        doc["activities"].insert(0, {"id": "P", "wbs": None, "name": "Project", "level": 0, "kind": "summary",
                                     "baseline_start": None, "baseline_finish": None, "current_start": None,
                                     "current_finish": None, "actual_start": None, "actual_finish": None,
                                     "percent_complete": 31.0, "duration_days": None})
        for a in doc["activities"][1:]:
            a["level"] = (a.get("level") or 0) + 1
        r = F.report(schedule=doc)
        self.assertEqual(r["schedule"]["project"]["reported_percent"], 31.0)
        html = RR.render_html([r], gc="", title="t", now=F.NOW, images={})
        self.assertIn("as reported in the schedule file", html)

    def test_an_unreadable_schedule_is_no_schedule(self):
        r = F.report(schedule={"activities": "not a list"})
        self.assertIsNone(r["schedule"])


class TheFinancialsAreProvidedOrAbsent(unittest.TestCase):

    GOOD = {"confirmed": True, "source": "Pay app #4 (G702)", "as_of": "2026-09-30",
            "contract_value": 4_200_000, "approved_changes": 85_000, "billed_to_date": 1_610_000}

    def test_absent_unconfirmed_or_unsourced_figures_are_no_financials(self):
        for bad in (None, {}, {**self.GOOD, "confirmed": False}, {**self.GOOD, "source": ""},
                    {"confirmed": True, "source": "x", "as_of": "2026-09-30"},
                    {**self.GOOD, "as_of": None}):
            self.assertIsNone(P._financials(bad))
        html = RR.render_html([F.report(financials={**self.GOOD, "confirmed": False})], gc="", title="t",
                              now=F.NOW, images={})
        self.assertNotIn("Financial overview", html)

    def test_provided_figures_are_printed_as_provided_and_never_computed(self):
        r = F.report(financials=self.GOOD)
        f = r["financials"]
        self.assertEqual(f["figures"], {"contract_value": 4_200_000, "approved_changes": 85_000,
                                        "billed_to_date": 1_610_000})
        html = RR.render_html([r], gc="", title="t", now=F.NOW, images={})
        self.assertIn("Financial overview", html)
        self.assertIn("$4,200,000", html)
        self.assertNotIn("4,285,000", html)              # no revised contract worked out for them
        self.assertIn("does not calculate", html)


class OneReportAnyPeriod(unittest.TestCase):

    def render_pages(self, r):
        import weasyprint
        doc = weasyprint.HTML(string=RR.render_html([r], gc=F.GC, title="t", now=F.NOW, images={},
                                                    report_id="abc12345-0")).render()
        return len(doc.pages)

    def test_it_renders_in_four_to_six_pages(self):
        try:
            import weasyprint  # noqa: F401
        except Exception:
            self.skipTest("weasyprint not installed")
        self.assertIn(self.render_pages(rep(schedule=True)), (4, 5, 6))
        self.assertLessEqual(self.render_pages(rep()), 5)

    def test_a_week_and_a_quarter_are_the_same_report(self):
        week = F.report(start=date(2026, 10, 9), end=date(2026, 10, 15), kind="weekly")
        quarter = F.report(start=date(2026, 7, 1), end=date(2026, 9, 30), kind="quarterly")
        for r in (week, quarter):
            self.assertEqual(set(r) >= {"overview", "changes", "risks", "site", "prev", "regulatory",
                                        "evidence", "limitations"}, True)
        self.assertEqual((week["grain"], quarter["grain"]), ("day", "week"))
        self.assertEqual(week["prev_start"], date(2026, 10, 2))

    def test_an_empty_period_is_an_honest_one_line(self):
        r = F.report(checkins=[], logbooks=[], dob_rows=[], dot_rows=[], events=[])
        self.assertEqual(r["overview"][0], "No site check-ins or filed crew reports were recorded in this period.")
        self.assertEqual((r["subs"], r["work"], r["site"]["worked"]), ([], [], 0))
        html = RR.render_html([r], gc="", title="t", now=F.NOW, images={})
        self.assertNotIn("Construction progress", html)
        self.assertNotIn("Workforce and site activity", html)


class TheWhatsappMessage(unittest.TestCase):

    def test_short_and_from_the_report_only(self):
        r = rep()
        msg = P.whatsapp_message(r)
        lines = msg.splitlines()
        self.assertEqual(lines[0], f"{r['job']} · {r['period_short']}")
        self.assertTrue(lines[1].startswith("- Site: 4 subs · 10 of 10 days · avg 25 workers/day (previous 11.9)"), lines[1])
        self.assertTrue(any(l.startswith("- Work: ") for l in lines))
        self.assertTrue(any(l.startswith("- Regulatory: ") for l in lines))
        self.assertTrue(msg.endswith(P.ATTACHED_LINE))
        self.assertIsNone(re.search(r"commitment|punch|chat|man-?days|%|https?://", msg), msg)

    def test_the_link_only_as_a_fallback(self):
        msg = P.whatsapp_message(rep(), attached=False, link="https://x/y")
        self.assertTrue(msg.endswith("Full report (PDF): https://x/y"))

    def test_a_stop_work_order_is_the_headline(self):
        rows = F.dob_rows()
        rows[0] = {**rows[0], "current_status": "ACTIVE", "status_history": [rows[0]["status_history"][0]],
                   "previous_status": None, "status_changed_at": None}
        r = F.report(dob_rows=rows)
        self.assertIn("ACTIVE", P.whatsapp_message(r))
        self.assertEqual(r["risks"][0]["level"], "critical")
        self.assertEqual(r["status"]["label"], "Needs attention")


class TheEvidence(unittest.TestCase):

    def test_every_claim_has_a_source_and_the_snapshot_is_storable(self):
        r = rep(schedule=True)
        snap = P.snapshot(r)
        json.dumps(snap)                                      # JSON as it is
        ids = {e["id"] for e in r["evidence"]}
        self.assertTrue({"G", "L", "S"} <= ids)
        self.assertEqual([e["id"] for e in r["evidence"] if e["kind"] == "regulatory"], ["R1", "R2", "R3", "R4", "R5"])
        for c in r["changes"] + r["risks"]:
            self.assertIn(c["src"], ("G", "L", "R", "S", "F"))
        html = RR.render_html([r], gc="", title="t", now=F.NOW, images={}, report_id="abc12345-0000")
        self.assertIn("Evidence index", html)
        self.assertIn("https://a810-bisweb.nyc.gov/example/35123456", html)
        self.assertIn("reference ", html)

    def test_the_regulatory_table_cites_its_evidence_ids(self):
        r = rep()
        html = RR.render_html([r], gc="", title="t", now=F.NOW, images={})
        for rid in ("R1", "R2", "R3"):
            self.assertIn(f">{rid}<", html)

    def test_the_phone_masking_still_holds(self):
        self.assertEqual(P.base.no_phone("Call 718-555-0100"), "Call [number]")


class TheTextSnapshot(unittest.TestCase):
    """The report's wording, snapshotted (REPORT_SNAPSHOT_UPDATE=1 rewrites
    it): a change to what the report SAYS is a diff someone reads."""

    def text(self):
        r = rep(schedule=True)
        out = ["OVERVIEW"] + r["overview"] + ["", "CHANGES"] + [f"[{c['src']}] {c['text']}" for c in r["changes"]]
        out += ["", "RISKS"] + [f"[{x['level']}/{x['src']}] {x['text']}" for x in r["risks"]]
        out += ["", "UPCOMING"] + [f"{u['date']} [{u['src']}] {u['what']}" for u in r["upcoming"]]
        out += ["", "DATA NOTES"] + r["data_notes"] + ["", "LIMITATIONS"] + r["limitations"]
        out += ["", "STATUS", f"{r['status']['label']}: {r['status']['basis']}"]
        return "\n".join(out) + "\n"

    def test_the_wording(self):
        got = self.text()
        if os.environ.get("REPORT_SNAPSHOT_UPDATE") or not os.path.exists(SNAP):
            with open(SNAP, "w", encoding="utf-8") as f:
                f.write(got)
        with open(SNAP, encoding="utf-8") as f:
            self.assertEqual(got, f.read())


if __name__ == "__main__":
    unittest.main()
