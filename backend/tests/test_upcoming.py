"""Upcoming v1: the pure rules (lib/upcoming.py). The worker, the endpoints
and the feed are covered in tests/test_upcoming_server.py; the end-to-end
chat scenario in scripts/upcoming_dry_run.py (TheDryRun below)."""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import upcoming as u  # noqa: E402

# Monday Nov 30 2026, 10:00 New York.
MON = datetime(2026, 11, 30, 15, 0, tzinfo=timezone.utc)


def when(t, at=MON):
    return u.resolve_when(t, at)


class TheDate(unittest.TestCase):

    def test_explicit_days(self):
        for t, want in {
            "Dec 4": date(2026, 12, 4), "December 4th": date(2026, 12, 4),
            "12/4": date(2026, 12, 4), "12/4/26": date(2026, 12, 4),
            "2026-12-04": date(2026, 12, 4), "4th of December": date(2026, 12, 4),
            "Tue 12/8": date(2026, 12, 8), "Jan 5": date(2027, 1, 5),
        }.items():
            self.assertEqual(when(t).get("date"), want, t)

    def test_relative_days(self):
        for t, want in {
            "tomorrow": date(2026, 12, 1), "tmrw": date(2026, 12, 1),
            "today": date(2026, 11, 30), "day after tomorrow": date(2026, 12, 2),
            "Thursday": date(2026, 12, 3), "this Sunday": date(2026, 12, 6),
            "on Wednesday": date(2026, 12, 2), "Tuesday next week": date(2026, 12, 8),
            "in 3 weeks": date(2026, 12, 21), "in two weeks": date(2026, 12, 14),
            "in 10 days": date(2026, 12, 10),
        }.items():
            self.assertEqual(when(t).get("date"), want, t)

    def test_next_weekday_depends_on_the_day_it_is_said(self):
        # Said Mon–Thu: this week's or the week after's? Skipped.
        for day in range(4):                                # Mon Nov 30 .. Thu Dec 3
            at = MON + timedelta(days=day)
            for t in ("next Tue", "next Friday", "next Monday"):
                self.assertEqual(when(t, at).get("skip"), "ambiguous", (t, day))
        # Said Fri–Sun: the coming one.
        fri, sat, sun = (MON + timedelta(days=d) for d in (4, 5, 6))   # Dec 4, 5, 6
        self.assertEqual(when("next Tue", fri)["date"], date(2026, 12, 8))
        self.assertEqual(when("next Friday", fri)["date"], date(2026, 12, 11))
        self.assertEqual(when("next Monday", sat)["date"], date(2026, 12, 7))
        self.assertEqual(when("next Sunday", sun)["date"], date(2026, 12, 13))
        self.assertEqual(when("next Wed at 7am", sun),
                         {"date": date(2026, 12, 9), "time": "07:00"})

    def test_this_or_bare_weekday_is_the_coming_one_not_today(self):
        self.assertEqual(when("this Friday")["date"], date(2026, 12, 4))
        self.assertEqual(when("Friday")["date"], date(2026, 12, 4))
        for t in ("Monday", "this Monday", "on Monday at 9am"):     # said on a Monday
            self.assertEqual(when(t).get("skip"), "ambiguous", t)

    def test_never_guessed(self):
        for t, why in {
            "next week": "vague", "soon": "vague", "end of month": "vague",
            "sometime next month": "vague", "the 5th": "ambiguous",
            "Tue 12/9": "ambiguous",         # 12/9 is a Wednesday
            "Tue or Wed": "ambiguous", "Monday": "ambiguous",   # said on a Monday
            "Dec 4 or Dec 5": "ambiguous", "Nov 20": "past", "7:30": "no_date",
            "": "no_date",
        }.items():
            self.assertEqual(when(t).get("skip"), why, t)

    def test_time_of_day(self):
        for t, want in {
            "Dec 4 at 9am": "09:00", "tomorrow 7am": "07:00", "today at 2pm": "14:00",
            "Dec 4 at 1:30": "13:30", "Dec 4 at 7:30": "07:30", "noon tomorrow": "12:00",
            "Dec 4": None,
        }.items():
            self.assertEqual(when(t).get("time"), want, t)

    def test_new_york_day_of_the_message(self):
        # 11:30pm Sunday in New York is Monday in UTC: "tomorrow" is Monday.
        late_sunday = datetime(2026, 11, 30, 4, 30, tzinfo=timezone.utc)
        self.assertEqual(when("tomorrow", late_sunday)["date"], date(2026, 11, 30))


def _ev(**kw):
    base = {"action": "new", "event_id": None, "kind": "utility", "agency": "Con Ed",
            "title": "Con Ed meter set", "date_text": "Dec 4", "quote": "Con Ed coming Dec 4"}
    base.update(kw)
    return base


class TheChecks(unittest.TestCase):

    def setUp(self):
        self.msg = {"body": "Heads up — Con Ed coming Dec 4 at 9am for the meter set",
                    "sent_at": MON}
        self.open = [{"id": "e1", "title": "Con Ed meter set", "date": "2026-12-04"}]

    def test_a_new_event_with_its_quote_and_day(self):
        got = u.decide(_ev(date_text="Dec 4 at 9am", quote="Con Ed coming Dec 4 at 9am"),
                       self.msg, [])
        self.assertEqual((got["op"], got["date"], got["time"], got["agency"]),
                         ("create", date(2026, 12, 4), "09:00", "Con Ed"))
        self.assertEqual(got["quote"], "Con Ed coming Dec 4 at 9am")

    def test_evidence_or_silence(self):
        self.assertEqual(u.decide(_ev(quote="Con Ed is coming on December 4"), self.msg, [])
                         ["reason"], "quote_not_in_message")
        self.assertEqual(u.decide(_ev(date_text="Dec 5"), self.msg, [])["reason"],
                         "date_not_in_quote")
        self.assertEqual(u.decide(_ev(kind="meeting"), self.msg, [])["reason"],
                         "not_an_event_kind")

    def test_vague_ambiguous_and_past_are_skipped(self):
        for body, dt, why in (("Con Ed coming next week", "next week", "vague"),
                              ("Con Ed coming the 5th", "the 5th", "ambiguous"),
                              ("Con Ed came Nov 20", "Nov 20", "past")):
            got = u.decide(_ev(date_text=dt, quote=body), {"body": body, "sent_at": MON}, [])
            self.assertEqual(got, {"op": "skip", "reason": why}, body)
        # Read later than it was sent: a day already gone by then is past too.
        got = u.decide(_ev(), self.msg, [], now=datetime(2026, 12, 6, 15, tzinfo=timezone.utc))
        self.assertEqual(got["reason"], "past")

    def test_reschedule_and_cancel(self):
        body = "Con Ed moved to Dec 9"
        got = u.decide(_ev(action="reschedule", event_id="e1", date_text="Dec 9",
                           quote=body), {"body": body, "sent_at": MON}, self.open)
        self.assertEqual((got["op"], got["event_id"], got["date"]),
                         ("reschedule", "e1", date(2026, 12, 9)))
        body = "Con Ed cancelled, they'll call to rebook"
        got = u.decide(_ev(action="cancel", event_id="e1", date_text=None,
                           quote="Con Ed cancelled"), {"body": body, "sent_at": MON}, self.open)
        self.assertEqual((got["op"], got["event_id"]), ("cancel", "e1"))

    def test_a_cancel_must_name_an_open_event_and_say_so(self):
        # A bad id, and no open event the words name.
        body = "Elevator inspection cancelled"
        self.assertEqual(u.decide(_ev(action="cancel", event_id="nope", quote=body),
                                  {"body": body, "sent_at": MON}, self.open)["reason"],
                         "cancel_of_unknown_event")
        body = "Con Ed confirmed"
        self.assertEqual(u.decide(_ev(action="cancel", event_id="e1", quote=body),
                                  {"body": body, "sent_at": MON}, self.open)["reason"],
                         "no_cancel_words")

    def test_a_move_of_something_unknown_is_a_new_event(self):
        body = "DOB inspection moved to Dec 9"
        got = u.decide(_ev(action="reschedule", event_id="zzz", kind="inspection", agency="dob",
                           title=None, date_text="Dec 9", quote=body),
                       {"body": body, "sent_at": MON}, self.open)
        self.assertEqual((got["op"], got["agency"], got["title"]),
                         ("create", "DOB", "DOB inspection"))

    def test_parse_events_shape(self):
        got = u.parse_events('{"events": [{"action": "new", "kind": "Crane Pick", '
                             '"quote": "pick Thursday", "date_text": "Thursday"}, '
                             '{"action": "explode", "quote": "x"}, "junk"]}')
        self.assertEqual([(e["action"], e["kind"]) for e in got], [("new", "crane_pick")])
        self.assertEqual(u.parse_events("not json"), [])

    def test_the_cheap_filter(self):
        self.assertTrue(u.worth_a_call("Con Ed coming Dec 4"))
        self.assertTrue(u.worth_a_call("pour is cancelled"))
        self.assertFalse(u.worth_a_call("thanks guys"))
        self.assertFalse(u.worth_a_call("pour went well"))

    def test_one_key_per_job_kind_agency_day(self):
        k = u.event_key("p1", "utility", "Con Ed", date(2026, 12, 4))
        self.assertEqual(k, u.event_key("p1", "utility", "con ed", date(2026, 12, 4)))
        self.assertNotEqual(k, u.event_key("p1", "utility", "Con Ed", date(2026, 12, 9)))


class LiveEvalOct10(unittest.TestCase):
    """The shapes the first live run failed on."""

    def test_the_quote_check_forgives_punctuation_and_spacing_not_words(self):
        body = "FDNY standpipe inspection in 3 weeks"
        self.assertEqual(u.match_quote("FDNY standpipe inspection in 3 weeks.", body), body)
        self.assertEqual(u.match_quote("Elevator inspection next Wednesday at 10 am",
                                       "Elevator inspection next Wednesday at 10am"),
                         "Elevator inspection next Wednesday at 10am")
        self.assertEqual(u.match_quote("“con ed coming dec 4”", "Con Ed coming Dec 4!"),
                         "Con Ed coming Dec 4")
        self.assertIsNone(u.match_quote("Con Ed coming Dec 5", "Con Ed coming Dec 4"))
        self.assertIsNone(u.match_quote("FDNY inspection in 3 weeks", body))    # a word gone

    def test_cancel_phrases(self):
        open_ = [{"id": "p", "title": "3rd floor deck pour", "kind": "pour"}]
        for body in ("3rd floor pour called off", "Pour scrapped", "Pour pushed indefinitely",
                     "pour is not happening", "Pour is off until further notice",
                     "pour won't happen this week"):
            got = u.decide({"action": "cancel", "event_id": "p", "quote": body},
                           {"body": body, "sent_at": MON}, open_)
            self.assertEqual(got["op"], "cancel", body)
            self.assertTrue(u.worth_a_call(body), body)

    def test_a_cancel_or_move_without_an_id_finds_the_event_it_names(self):
        open_ = [{"id": "p", "title": "3rd floor deck pour", "kind": "pour"},
                 {"id": "c", "title": "Con Ed meter set", "kind": "utility"},
                 {"id": "r", "title": "Rebar delivery", "kind": "delivery"}]
        body = "Pump truck cancelled, the pour is off until the weather clears"
        got = u.decide({"action": "cancel", "event_id": None,
                        "quote": "the pour is off until the weather clears"},
                       {"body": body, "sent_at": MON}, open_)
        self.assertEqual((got["op"], got["event_id"]), ("cancel", "p"))
        body = "Con Ed moved to Dec 9"
        got = u.decide({"action": "reschedule", "event_id": "made-up", "kind": "utility",
                        "date_text": "Dec 9", "quote": body}, {"body": body, "sent_at": MON}, open_)
        self.assertEqual((got["op"], got["event_id"]), ("reschedule", "c"))
        # Two events share the words: no guess.
        two = open_ + [{"id": "p2", "title": "Elevator pit pour", "kind": "pour"}]
        body = "pour cancelled"
        self.assertEqual(u.decide({"action": "cancel", "event_id": None, "quote": body},
                                  {"body": body, "sent_at": MON}, two)["reason"],
                         "cancel_of_unknown_event")


class CityRecords(unittest.TestCase):

    def test_a_record_is_one_event_until_its_day_passes(self):
        today = date(2026, 11, 30)
        ev = u.city_event("hearing", "DOT", "oath:123", "2026-12-10T00:00:00.000",
                          "OATH hearing · DOT ticket #123", today)
        self.assertEqual((ev["key"], ev["date"], ev["source"]),
                         ("city:hearing:oath:123", "2026-12-10", "city"))
        self.assertIsNone(u.city_event("hearing", "DOT", "x", "2026-11-01", "t", today))
        self.assertIsNone(u.city_event("hearing", "DOT", "x", None, "t", today))
        self.assertEqual(u.city_event("permit_expiration", "DOB", "y", "12/15/2026", "t",
                                      today)["date"], "2026-12-15")


class WhatPeopleRead(unittest.TestCase):

    def setUp(self):
        self.rows = [
            {"id": "a", "date": "2026-12-04", "time": "09:00", "title": "Con Ed meter set",
             "project_name": "120 Atlantic", "source": "chat", "status": "open"},
            {"id": "b", "date": "2026-12-01", "time": None, "title": "OATH hearing · DOT #9",
             "project_name": "8 Walworth", "source": "city", "status": "open"},
            {"id": "c", "date": "2026-12-02", "title": "x", "source": "chat",
             "status": "dismissed"},
            {"id": "d", "date": "2026-12-20", "title": "far", "source": "chat", "status": "open"},
        ]

    def test_brief_section_is_this_week_sorted(self):
        lines = u.brief_section(self.rows, date(2026, 11, 30))
        self.assertEqual(lines, [
            "Upcoming this week",
            "• Tue Dec 1 — OATH hearing · DOT #9 · 8 Walworth (city record)",
            "• Fri Dec 4, 9am — Con Ed meter set · 120 Atlantic (from chat)"])
        self.assertEqual(u.brief_section([], date(2026, 11, 30)), [])

    def test_at_most_five(self):
        many = [{"id": str(i), "date": "2026-12-01", "title": f"t{i}", "status": "open"}
                for i in range(9)]
        self.assertEqual(len(u.this_week(many, date(2026, 11, 30))), 5)

    def test_day_before_dm(self):
        text = u.day_before_dm(self.rows, date(2026, 12, 4))
        self.assertEqual(text, "Tomorrow, Fri Dec 4:\n• 9am — Con Ed meter set · 120 Atlantic "
                               "(from chat)")
        self.assertEqual(u.day_before_dm(self.rows, date(2026, 12, 5)), "")

    def test_ics_feed(self):
        ics = u.ics_feed(self.rows, "Levelog — Roy", datetime(2026, 11, 30, tzinfo=timezone.utc))
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(ics.endswith("END:VCALENDAR\r\n"))
        self.assertIn("UID:a@levelog-upcoming", ics)
        self.assertIn("DTSTART;TZID=America/New_York:20261204T090000", ics)
        self.assertIn("DTSTART;VALUE=DATE:20261201", ics)
        self.assertNotIn("UID:c@", ics)                    # dismissed
        self.assertTrue(all(len(line.encode()) <= 75 for line in ics.split("\r\n")))


class RemindMe(unittest.TestCase):

    def test_parse(self):
        r = u.parse_reminder("Remind me Dec 4 at 8am to call the inspector", MON)
        self.assertEqual((r["what"], r["date"], r["time"]),
                         ("call the inspector", date(2026, 12, 4), "08:00"))
        r = u.parse_reminder("remind me to order rebar tomorrow", MON)
        self.assertEqual((r["what"], r["date"]), ("order rebar", date(2026, 12, 1)))
        self.assertEqual(u.parse_reminder("remind me to order rebar", MON)["skip"], "no_date")
        self.assertEqual(u.parse_reminder("remind me next week to order rebar", MON)["skip"],
                         "vague")
        self.assertEqual(u.parse_reminder("remind me on the 5th to pay", MON)["skip"],
                         "ambiguous")

    def test_words(self):
        self.assertTrue(u.is_remind_request("Please remind me Friday to call Mike"))
        self.assertFalse(u.is_remind_request("did you remind me?"))
        self.assertTrue(u.is_yes("Yes"))
        self.assertTrue(u.is_no("no"))
        self.assertFalse(u.is_yes("yes but change it"))

    def test_confirm_text(self):
        r = u.parse_reminder("remind me Dec 4 at 8am to call the inspector", MON)
        self.assertEqual(u.confirm_text(r), "Remind you Fri Dec 4, 8am: call the inspector?\n"
                                            "Reply YES to save it, or NO.")


class TheDryRun(unittest.TestCase):
    """scripts/upcoming_dry_run.py, scripted: the real worker and checks, the
    scenario's own model answers. The live run (gpt-4o-mini) is the same
    command without --scripted."""

    def test_the_october_job_scripted(self):
        import asyncio
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import upcoming_dry_run as dry
        sc = dry.load(str(Path(__file__).resolve().parents[1]
                          / "scripts" / "upcoming_eval" / "job_oct_2026.json"))
        r = dry.score(sc, asyncio.run(dry.run(sc, scripted=True)))
        self.assertEqual(r["sent"], [])
        self.assertEqual([(x["case"], x["notes"]) for x in r["rows"] if x["verdict"] == "FAIL"], [])
        self.assertEqual(r["score"], {"HARD": 10, "PASS": 10, "FAIL": 0})
        self.assertEqual(dry.exit_code(r), 0)

    def test_a_wrong_answer_fails_the_run(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import upcoming_dry_run as dry
        sc = dry.load(str(Path(__file__).resolve().parents[1]
                          / "scripts" / "upcoming_eval" / "job_oct_2026.json"))
        fake = {"events": [{"source_ref": "row_m3", "kind": "inspection", "title": "DOB",
                            "date": "2026-10-12", "status": "open"}],
                "sent": [], "calls": 0, "skipped": {}, "prompt_tokens": 0,
                "completion_tokens": 0}
        r = dry.score(sc, fake)
        self.assertEqual(dry.exit_code(r), 1)
        self.assertIn("made DOB on 2026-10-12",
                      next(x for x in r["rows"] if x["case"].startswith("nothing from m3"))["notes"])


class KillSwitch(unittest.TestCase):

    def test_env(self):
        self.assertTrue(u.disabled({"UPCOMING_DISABLED": "1"}))
        self.assertFalse(u.disabled({}))


if __name__ == "__main__":
    unittest.main()
