"""Chasing's two rest-day switches per job (replacing "Chase on weekends").

  * "Shabbos / Yom Tov off": nobody chased from one hour before NYC
    candle-lighting on Friday (or erev Yom Tov) through one hour after
    nightfall at its end -- computed, no network.
  * "Sundays off": nobody chased on Sunday.

The old switch carries over to both (on -> both off false). Over DM:
"stop chasing on shabbos" / "no chasing weekends" asks once "Just Shabbos
(Fri evening to Sat night), or Sunday too?"; "shabbos only", "sundays too",
"whole weekend" set it straight away.
"""

from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import dm_actions, shabbos, wa_chase  # noqa: E402
from tests.test_whatsapp_chase import _Base, _item, _run  # noqa: E402

ASK = "Just Shabbos (Fri evening to Sat night), or Sunday too?"


def _ny(y, mo, d, h, mi=0):
    """A New York wall-clock time, as an aware datetime."""
    return datetime(y, mo, d, h, mi, tzinfo=shabbos.NY)


def _clock(dt):
    return dt.astimezone(shabbos.NY).strftime("%a %b %-d %-I:%M %p")


class TheTimes(unittest.TestCase):
    """New York candle-lighting and nightfall (Hebcal's: sunset - 18 min,
    sunset + 42 min), within a couple of minutes."""

    def near(self, got, h, m):
        want = got.astimezone(shabbos.NY).replace(hour=h, minute=m, second=0, microsecond=0)
        self.assertLess(abs((got - want).total_seconds()), 150, _clock(got))

    def test_candles_and_nightfall(self):
        self.near(shabbos.candle_lighting(date(2026, 12, 18)), 16, 12)    # Fri Dec 18, 4:12 PM
        self.near(shabbos.nightfall(date(2026, 12, 19)), 17, 13)          # Sat Dec 19
        self.near(shabbos.candle_lighting(date(2026, 10, 16)), 17, 58)    # Fri Oct 16
        self.near(shabbos.candle_lighting(date(2026, 6, 19)), 20, 13)     # Fri Jun 19

    def test_the_yom_tov_days(self):
        self.assertEqual(shabbos.yom_tov_days(2026), (
            date(2026, 4, 2), date(2026, 4, 3), date(2026, 4, 8), date(2026, 4, 9),       # Pesach
            date(2026, 5, 22), date(2026, 5, 23),                                         # Shavuot
            date(2026, 9, 12), date(2026, 9, 13),                                         # Rosh Hashana
            date(2026, 9, 21),                                                            # Yom Kippur
            date(2026, 9, 26), date(2026, 9, 27), date(2026, 10, 3), date(2026, 10, 4)))  # Sukkot, ShA
        self.assertEqual(shabbos.yom_tov_days(2025)[:2], (date(2025, 4, 13), date(2025, 4, 14)))
        self.assertIn(date(2025, 10, 2), shabbos.yom_tov_days(2025))                    # YK 5786
        self.assertIn(date(2027, 10, 11), shabbos.yom_tov_days(2027))                   # YK 5788


class TheQuietWindow(unittest.TestCase):

    def test_friday_3pm_and_4pm_in_december(self):
        # Fri Dec 18 2026: candles 4:12 PM, so quiet from 3:12 PM.
        self.assertFalse(shabbos.is_quiet(_ny(2026, 12, 18, 15, 0)))     # 3 PM: still chasing
        self.assertFalse(shabbos.is_quiet(_ny(2026, 12, 18, 15, 10)))
        self.assertTrue(shabbos.is_quiet(_ny(2026, 12, 18, 15, 15)))
        self.assertTrue(shabbos.is_quiet(_ny(2026, 12, 18, 16, 0)))      # 4 PM: quiet

    def test_friday_3pm_and_4pm_in_october(self):
        # Fri Oct 16 2026: candles 5:58 PM, so 3 and 4 PM are before the hour.
        self.assertFalse(shabbos.is_quiet(_ny(2026, 10, 16, 15, 0)))
        self.assertFalse(shabbos.is_quiet(_ny(2026, 10, 16, 16, 0)))
        self.assertTrue(shabbos.is_quiet(_ny(2026, 10, 16, 17, 0)))

    def test_saturday_night_after_nightfall(self):
        # Sat Dec 19 2026: nightfall about 5:13 PM, quiet until about 6:13 PM.
        self.assertTrue(shabbos.is_quiet(_ny(2026, 12, 19, 12, 0)))
        self.assertTrue(shabbos.is_quiet(_ny(2026, 12, 19, 17, 30)))     # after nightfall, < 1 h
        self.assertTrue(shabbos.is_quiet(_ny(2026, 12, 19, 18, 5)))
        self.assertFalse(shabbos.is_quiet(_ny(2026, 12, 19, 18, 20)))    # an hour after: back on
        self.assertFalse(shabbos.is_quiet(_ny(2026, 12, 19, 21, 0)))

    def test_a_yom_tov_weekday(self):
        # Yom Kippur, Mon Sep 21 2026: from Sun 5:40 PM to Mon about 8:39 PM.
        self.assertFalse(shabbos.is_quiet(_ny(2026, 9, 20, 17, 30)))
        self.assertTrue(shabbos.is_quiet(_ny(2026, 9, 20, 17, 45)))
        self.assertTrue(shabbos.is_quiet(_ny(2026, 9, 21, 8, 35)))       # Monday morning
        self.assertTrue(shabbos.is_quiet(_ny(2026, 9, 21, 15, 5)))
        self.assertFalse(shabbos.is_quiet(_ny(2026, 9, 22, 8, 35)))      # Tuesday
        self.assertFalse(shabbos.is_quiet(_ny(2026, 9, 18, 12, 35)))     # the Friday before: noon

    def test_two_days_of_yom_tov_into_shabbos_is_one_stretch(self):
        # Pesach 2026: Thu Apr 2 + Fri Apr 3, then Shabbos Apr 4.
        start, end = shabbos.window(date(2026, 4, 3))
        self.assertEqual(_clock(start)[:10], "Wed Apr 1 ")
        self.assertEqual(_clock(end)[:10], "Sat Apr 4 ")
        self.assertTrue(shabbos.is_quiet(_ny(2026, 4, 3, 12, 0)))        # the Friday, Yom Tov
        self.assertTrue(shabbos.is_quiet(_ny(2026, 4, 2, 23, 0)))

    def test_sunday(self):
        self.assertTrue(shabbos.is_sunday(_ny(2026, 12, 20, 0, 5)))
        self.assertTrue(shabbos.is_sunday(_ny(2026, 12, 20, 23, 55)))
        self.assertFalse(shabbos.is_sunday(_ny(2026, 12, 21, 0, 5)))
        self.assertFalse(shabbos.is_sunday(_ny(2026, 12, 19, 23, 55)))


class TheTwoSwitches(unittest.TestCase):

    SAT, SUN = _ny(2026, 12, 19, 12, 35), _ny(2026, 12, 20, 12, 35)
    MON_YK = _ny(2026, 9, 21, 12, 35)

    def test_defaults_and_the_old_switch(self):
        self.assertEqual(wa_chase.rest_days({}), {"chase_shabbos_off": True, "chase_sundays_off": True})
        self.assertEqual(wa_chase.rest_days({"chase_weekends": True}),
                         {"chase_shabbos_off": False, "chase_sundays_off": False})
        self.assertEqual(wa_chase.rest_days({"chase_weekends": False}),
                         {"chase_shabbos_off": True, "chase_sundays_off": True})
        # The new ones win over the old.
        self.assertEqual(wa_chase.rest_days({"chase_weekends": True, "chase_sundays_off": True}),
                         {"chase_shabbos_off": False, "chase_sundays_off": True})

    def test_each_switch_alone(self):
        shab_only = {"chase_shabbos_off": True, "chase_sundays_off": False}
        sun_only = {"chase_shabbos_off": False, "chase_sundays_off": True}
        self.assertEqual(wa_chase.quiet(self.SAT, shab_only), "shabbos")
        self.assertIsNone(wa_chase.quiet(self.SUN, shab_only))
        self.assertEqual(wa_chase.quiet(self.MON_YK, shab_only), "shabbos")
        self.assertIsNone(wa_chase.quiet(self.SAT, sun_only))
        self.assertEqual(wa_chase.quiet(self.SUN, sun_only), "sunday")
        self.assertIsNone(wa_chase.quiet(self.MON_YK, sun_only))
        self.assertIsNone(wa_chase.quiet(_ny(2026, 12, 21, 12, 35), {}))           # a Monday


class TheChaseTick(_Base):
    """The worker: shadow rows only when not quiet (nothing is ever sent)."""

    def setUp(self):
        super().setUp()
        self.settings = {}
        self.db.notification_preferences.rows.append({
            "_id": "np", "user_id": None, "project_id": "proj_a", "scope": "project",
            "whatsapp_project": self.settings})

    def tick(self, *ats, due):
        """One item due `due`, the worker at each of `ats`: the slots chased."""
        self.db[wa_chase.COLLECTION].rows = []
        self.db.attention_items.rows = []
        _item(self.db, due={"due_text": "today", "due_at": due},
              evidence={"sent_at": (ats[0] - timedelta(hours=3)).astimezone(timezone.utc)})
        for at in ats:
            self.chase(at.astimezone(timezone.utc))
        return [r["slot"] for r in self.rows()]

    def test_friday_3pm_and_4pm_in_december(self):
        # 3:05 PM: before the hour before candles (3:12 PM) -- chased.
        # 4:05 PM: Shabbos -- the admin is not DM'd.
        fri = (_ny(2026, 12, 18, 15, 5), _ny(2026, 12, 18, 16, 5))
        self.assertEqual(self.tick(*fri, due="2026-12-18"), ["eod"])
        self.settings["chase_shabbos_off"] = False
        self.assertEqual(self.tick(*fri, due="2026-12-18"), ["eod", "admin_dm"])

    def test_friday_in_october_the_whole_day(self):
        fri = (_ny(2026, 10, 16, 15, 5), _ny(2026, 10, 16, 16, 5))
        self.assertEqual(self.tick(*fri, due="2026-10-16"), ["eod", "admin_dm"])

    def test_yom_kippur_monday(self):
        self.assertEqual(self.tick(_ny(2026, 9, 21, 12, 35), due="2026-09-21"), [])
        self.assertEqual(self.tick(_ny(2026, 9, 22, 12, 35), due="2026-09-22"), ["midday"])

    def test_sunday(self):
        self.assertEqual(self.tick(_ny(2026, 12, 20, 12, 35), due="2026-12-20"), [])
        self.settings["chase_sundays_off"] = False
        self.assertEqual(self.tick(_ny(2026, 12, 20, 12, 35), due="2026-12-20"), ["midday"])

    def test_saturday_night_after_nightfall(self):
        # Sat Dec 19: nightfall about 5:13 PM; no slot runs that late, so the
        # next chase is Sunday's (Sundays off) -> Monday morning.
        self.settings["chase_sundays_off"] = False
        self.assertEqual(self.tick(_ny(2026, 12, 19, 16, 5), due="2026-12-19"), [])
        self.assertEqual(self.tick(_ny(2026, 12, 20, 8, 35), due="2026-12-19"), ["morning"])

    def test_the_report_says_why(self):
        with patch.object(server, "db", self.db):
            _item(self.db, due={"due_text": "today", "due_at": "2026-12-20"})
            report = _run(server._chase_tick(now=_ny(2026, 12, 20, 12, 35).astimezone(timezone.utc)))
        self.assertGreaterEqual(report["sunday_off"], 1)


class TheMigration(_Base):

    def row(self, wp):
        self.db.notification_preferences.rows.append({
            "_id": f"np{len(self.db.notification_preferences.rows)}", "user_id": None,
            "project_id": f"p{len(self.db.notification_preferences.rows)}", "scope": "project",
            "whatsapp_project": dict(wp)})

    def migrate(self):
        with patch.object(server, "db", self.db):
            return _run(server._chase_rest_days_migration())

    def test_weekend_on_and_off_to_both(self):
        self.row({"chase_weekends": True})
        self.row({"chase_weekends": False, "violation_alerts": False})
        self.row({"violation_alerts": True})                               # never set: defaults
        self.row({"chase_weekends": True, "chase_shabbos_off": True, "chase_sundays_off": False})
        self.assertEqual(self.migrate(), 2)
        wps = [r["whatsapp_project"] for r in self.db.notification_preferences.rows]
        self.assertEqual((wps[0]["chase_shabbos_off"], wps[0]["chase_sundays_off"]), (False, False))
        self.assertEqual((wps[1]["chase_shabbos_off"], wps[1]["chase_sundays_off"]), (True, True))
        self.assertFalse(wps[1]["violation_alerts"])
        self.assertNotIn("chase_shabbos_off", wps[2])
        self.assertEqual((wps[3]["chase_shabbos_off"], wps[3]["chase_sundays_off"]), (True, False))
        self.assertEqual(self.migrate(), 0)                                # once

    def test_after_the_588_one_at_startup(self):
        import inspect
        src = inspect.getsource(server.run_whatsapp_startup_migrations)
        self.assertLess(src.index("_chase_weekends_for_588_thomas()"),
                        src.index("_chase_rest_days_migration()"))


class TheDm(unittest.TestCase):
    """Through the real DM entry point."""

    def setUp(self):
        from tests.test_dm_routing_order import _Dm
        self.h = type("H", (_Dm, unittest.TestCase), {"runTest": lambda s: None})()
        self.h.setUp()

    def tearDown(self):
        self.h.tearDown()

    def talk(self, *lines, settings=None):
        from tests.test_dm_routing_order import _world
        from tests.test_whatsapp_dm_assistant import THOMAS, _Ctx
        db = _world()
        db.notification_preferences.rows.append({
            "_id": "np588", "user_id": None, "project_id": THOMAS, "scope": "project",
            "whatsapp_project": dict(settings or {})})
        self.db = db
        with _Ctx(db=db) as c:
            out = self.h.dm(c, *lines)
        return [r[0] if len(r) == 1 else r for r in out]

    def wp(self):
        from tests.test_whatsapp_dm_assistant import THOMAS
        r = [r for r in self.db.notification_preferences.rows if r.get("project_id") == THOMAS]
        return (r[-1].get("whatsapp_project") or {}) if r else {}

    def rest(self):
        return wa_chase.rest_days(self.wp())

    ALL_ON = {"chase_weekends": True}                   # chasing every day

    def test_ambiguous_asks_once(self):
        for said in ("stop chasing on shabbos at 588", "no chasing weekends at 588",
                     "stop bugging people on weekends at 588", "no chasing on yom tov at 588"):
            for answer, want in (("just shabbos", (True, False)), ("sunday too", (True, True)),
                                 ("1", (True, False)), ("2", (True, True)), ("both", (True, True)),
                                 ("no", (True, False)), ("yes", (True, True))):
                with self.subTest(said=said, answer=answer):
                    ask, done = self.talk(said, answer, settings=self.ALL_ON)
                    self.assertEqual(ask, ASK)
                    self.assertTrue(done.startswith("Done — at 588"), done)
                    self.assertEqual(tuple(self.rest().values()), want)

    def test_clear_requests_set_straight_away(self):
        for said, want, reply in (
                ("no chasing on shabbos only at 588", (True, False),
                 "no chasing over Shabbos and Yom Tov; Sundays are on"),
                ("no chasing sundays at 588", (False, True),
                 "no chasing on Sundays; Shabbos and Yom Tov are on"),
                ("no chasing the whole weekend at 588", (True, True),
                 "no chasing over Shabbos, Yom Tov or Sundays"),
                ("stop chasing on shabbos and sundays too at 588", (True, True),
                 "no chasing over Shabbos, Yom Tov or Sundays")):
            with self.subTest(said):
                (done,) = self.talk(said, settings=self.ALL_ON)
                self.assertEqual(done, f"Done — at 588 Thomas S Boyland St, {reply}.")
                self.assertEqual(tuple(self.rest().values()), want)

    def test_back_on(self):
        (done,) = self.talk("ok to chase on sundays at 588")
        self.assertEqual(tuple(self.rest().values()), (True, False))
        self.assertIn("Sundays are on", done)

    def test_already_so(self):
        (r,) = self.talk("no chasing the whole weekend at 588")     # both off by default
        self.assertTrue(r.startswith("Already set — at 588"), r)

    def test_undo_puts_both_back(self):
        ask, done, undone = self.talk("no chasing weekends at 588", "sunday too", "undo",
                                      settings={"chase_shabbos_off": False, "chase_sundays_off": True})
        self.assertTrue(undone.startswith("Undone"), undone)
        self.assertEqual(tuple(self.rest().values()), (False, True))

    def test_a_non_answer_then_a_drop(self):
        ask, again, dropped = self.talk("no chasing weekends at 588", "hmm", "never mind",
                                        settings=self.ALL_ON)
        self.assertEqual(ask, ASK)
        self.assertEqual(tuple(self.rest().values()), (False, False))      # nothing changed

    def test_spanish(self):
        (ask,) = self.talk("no molestar los fines de semana en 588", settings=self.ALL_ON)
        self.assertEqual(ask, dm_actions.say("es", "rest_ask"))

    def test_the_answers(self):
        for said, want in (("just shabbos", "shabbos"), ("shabbos only", "shabbos"), ("1", "shabbos"),
                           ("no sunday", "shabbos"), ("sundays too", "both"), ("both", "both"),
                           ("whole weekend", "both"), ("2", "both"), ("los dos", "both"),
                           ("what?", None), ("588", None)):
            with self.subTest(said):
                self.assertEqual(dm_actions.rest_choice(said), want)


if __name__ == "__main__":
    unittest.main()
