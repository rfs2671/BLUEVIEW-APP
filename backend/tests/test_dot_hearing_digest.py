"""DOT hearing reminders: one digest a day, true days left, held over Shabbos.

Operator rulings 2026-10-23 (the #855 half of the fixes the production dry
run asked for):

  1. DIGEST. ONE email per project per day lists every hearing reminder due,
     grouped by hearing date, the subject saying the count; one GC group post
     per project per day for the dot_hearing kind. Each hearing keeps its own
     ledger row.
  2. SHABBOS / YOM TOV. A hearing reminder due inside the quiet window is held
     to its end and sent then, exactly once.
  3. CATCH-UP. A hearing first seen 2 days out (inside the 7-day window) gets
     ONE reminder saying "2 days"; ledger key and metadata say 2, never 7.

Real jobs (_dot_sync_tick, _dot_hearing_tick, _quiet_queue_tick,
_gc_alerts_tick) over an in-memory db; recorded OATH records from
tests/fixtures/dot_summonses with their dates (and one ticket number) changed
-- SYNTHETIC, said where made.

CONTROL RUN: on #855's head before this change (0437e245) every test here
fails -- one email per hearing, labelled with the threshold, sent at Saturday
07:00, and one group post per hearing.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402
from lib import dot_sync, shabbos  # noqa: E402
from tests.test_dot_summonses import OATH, _Env, _run, summons  # noqa: E402

UTC = timezone.utc
#: SYNTHETIC: a third summons at 588 (0704345557's record, another ticket).
THIRD = summons("0704345557", ticket_number="0704399002", hearing=date(2026, 12, 28))


def _items(env):
    return [(i, m) for m in env.emails("dot_hearing_reminder") for i in m["metadata"]["items"]]


class ADigestADay(unittest.TestCase):

    def test_three_hearings_on_two_dates_are_one_email(self):
        env = _Env()
        env.first_pass(address=[OATH["0704345548"], OATH["0704345557"], THIRD])
        env.hearing_alerts([date(2026, 12, 14)])           # Monday: 10 and 14 days out
        env.hearing_alerts([date(2026, 12, 14)])           # again the same day
        mails = env.emails("dot_hearing_reminder")
        self.assertEqual(len(mails), 1, [m["subject"] for m in mails])
        m = mails[0]
        self.assertEqual(m["subject"], "3 DOT hearings coming up on 588 Thomas S Boyland / "
                                       "3 audiencias del DOT próximas en 588 Thomas S Boyland")
        t = m["text"]
        self.assertLess(t.index("Hearing Dec 24, 2026 (in 10 days):"), t.index("Hearing Dec 28, 2026 (in 14 days):"))
        self.assertLess(t.index("0704345557"), t.index("Hearing Dec 28"))
        self.assertGreater(t.index("0704399002"), t.index("Hearing Dec 28"))
        self.assertIn("Audiencia el 24 dic 2026 (en 10 días):", t)
        self.assertEqual(sorted((i["ticket"], i["days_left"]) for i, _m in _items(env)),
                         [("0704345548", 10), ("0704345557", 10), ("0704399002", 14)])
        led = [d for d in env.db.dot_alert_ledger.docs if d.get("kind") == "hearing"]
        self.assertEqual(len(led), 3)


class LateHearings(unittest.TestCase):
    """Operator ruling 2026-10-24: after today's digest, a hearing <= 1 day
    away found later goes at once, in its own email; the rest wait."""

    MON = date(2026, 12, 14)

    def _late(self, env, now):
        return env._mail(lambda now: server._dot_hearing_tick(now=now, late_only=True), now)

    def test_digest_at_0700_then_a_hearing_tomorrow_found_at_1000_is_one_email_at_1000(self):
        env = _Env()
        a = summons("0704345548", hearing=self.MON + timedelta(days=10))          # SYNTHETIC dates
        env.first_pass(address=[a])
        env.hearing_alerts([self.MON])                                          # 07:00 EST: the digest
        self.assertEqual(len(env.emails("dot_hearing_reminder")), 1)
        b = summons("0704345557", hearing=self.MON + timedelta(days=1))
        env.sync(now=datetime(2026, 12, 14, 14, 30, tzinfo=UTC), address=[a, b])   # the 09:30 sync finds b
        r = self._late(env, datetime(2026, 12, 14, 15, 0, tzinfo=UTC))           # 10:00 EST
        mails = env.emails("dot_hearing_reminder")
        self.assertEqual(len(mails), 2, [m["subject"] for m in mails])
        late = mails[1]
        self.assertIn("0704345557", late["text"])
        self.assertIn("(in 1 day):", late["text"])
        self.assertNotIn("0704345548", late["text"])
        self.assertEqual(late["permit_renewal_id"], "dot:p1:hearing_late:0704345557:-:2026-12-14")
        self.assertEqual(r["late"], 1)
        self._late(env, datetime(2026, 12, 14, 17, 0, tzinfo=UTC))               # the next sync: nothing
        self.assertEqual(len(env.emails("dot_hearing_reminder")), 2)

    def test_a_later_hearing_further_out_waits_and_none_before_0700(self):
        env = _Env()
        b = summons("0704345557", hearing=self.MON + timedelta(days=1))
        env.first_pass(address=[b])
        r = self._late(env, datetime(2026, 12, 14, 10, 0, tzinfo=UTC))           # 05:00 EST sync
        self.assertEqual((env.emails("dot_hearing_reminder"), r.get("skipped")), ([], "before_digest_run"))
        env.hearing_alerts([self.MON])                                          # the digest takes b
        self.assertEqual(len(env.emails("dot_hearing_reminder")), 1)


class CatchUp(unittest.TestCase):

    def test_two_days_out_at_first_sight_says_two_days(self):
        env = _Env()
        env.first_pass(address=[summons("0704345548", hearing=date(2026, 12, 16))])   # SYNTHETIC date
        env.hearing_alerts([date(2026, 12, 14)])
        (m,) = env.emails("dot_hearing_reminder")
        self.assertIn("Hearing Dec 16, 2026 (in 2 days):", m["text"])
        self.assertNotIn("7 days", m["text"])
        self.assertEqual(m["metadata"]["items"], [{"ticket": "0704345548", "days_left": 2,
                                                    "hearing_date": "2026-12-16"}])
        (led,) = [d for d in env.db.dot_alert_ledger.docs if d.get("kind") == "hearing"]
        self.assertEqual((led["_id"], led["days_left"], led["bucket"]),
                         ("dot:p1:hearing:0704345548:2d:2026-12-16", 2, 7))


class HeldOverShabbos(unittest.TestCase):

    def test_saturday_0700_is_sent_after_havdalah_once(self):
        env = _Env()
        env.first_pass(address=[summons("0704345548", hearing=date(2026, 11, 8))])    # Sunday; SYNTHETIC
        sat_7am = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
        until = shabbos.quiet_until(sat_7am)
        self.assertEqual(until.astimezone(shabbos.NY).date(), date(2026, 11, 7))
        with patch.object(server, "db", env.db), \
                patch.object(server, "RESEND_API_KEY", "re_test_key"), \
                patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": ""}), \
                patch("lib.notifications.send_notification", env.send):
            r = _run(server._dot_hearing_tick(now=sat_7am))
            self.assertEqual([m["subject"] for m in env.emails()], [])     # nothing at 07:00
            self.assertEqual(r.get("held"), 1)
            _run(server._quiet_queue_tick(now=until - timedelta(minutes=5)))
            self.assertEqual(env.emails(), [])
            _run(server._quiet_queue_tick(now=until + timedelta(minutes=1)))
            _run(server._quiet_queue_tick(now=until + timedelta(hours=1)))
            _run(server._dot_hearing_tick(now=datetime(2026, 11, 8, 12, 0, tzinfo=UTC)))
        mails = env.emails("dot_hearing_reminder")
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0]["permit_renewal_id"], "dot:p1:hearing_digest:-:-:2026-11-07")
        self.assertIn("(in 1 day):", mails[0]["text"])


from tests.test_whatsapp_gc_alerts import (  # noqa: E402
    CO_A, _Ctx, _confirm, _group_sends, _no_ai, _world as _gc_world,
)

GC_DAY = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)      # Friday 11 AM ET


class OneGroupPostADay(unittest.TestCase):

    def test_three_hearings_one_post(self):
        db = _gc_world()
        tickets = ("0704345548", "0704345557", "0704399002")
        rows = [{**dot_sync.to_log("dot_violation", summons(
                    "0704345548", ticket_number=t, hearing=date(2026, 10, 30))),      # SYNTHETIC
                 "_id": f"d_{t}", "project_id": "proj_a", "company_id": CO_A,
                 "match": {"how": "address", "state": "confirmed"}, "detected_at": GC_DAY}
                for t in tickets]
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._gc_alerts_tick(GC_DAY))
            db.dot_logs.rows.extend(rows)
            _run(server._gc_alerts_tick(GC_DAY + timedelta(minutes=15)))
            _run(server._gc_alerts_tick(GC_DAY + timedelta(hours=1)))
            texts = [s["message"] for s in _group_sends(c)]
        hearing_posts = [t for t in texts if "hearing" in t.lower()]
        self.assertEqual(len(hearing_posts), 1, texts)
        for t in tickets:
            self.assertIn(f"#{t}", hearing_posts[0])
        self.assertIn("3 DOT hearings coming up.", hearing_posts[0])
        self.assertIn("Hearing Oct 30, 2026 (in 7 days) / Audiencia el 30 oct 2026 (en 7 días)",
                      hearing_posts[0])


if __name__ == "__main__":
    unittest.main()
