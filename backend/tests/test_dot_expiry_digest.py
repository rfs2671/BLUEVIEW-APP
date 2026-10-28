"""DOT permit expiry reminders: one digest a day, held over Shabbos, true days.

Operator rulings 2026-10-23, after the production dry run:

  1. DIGEST. ONE email per project per day lists every permit due that day,
     grouped by work-end date; the subject says the count. The WhatsApp group
     post follows the same rule: one post per project per day per kind. Each
     permit still has its own ledger row, so nothing sends twice.
  2. SHABBOS / YOM TOV (spec decision 6). A reminder due inside the quiet
     window is HELD to the window's end and sent then -- Saturday 07:00 is sent
     Saturday night after havdalah -- and nothing is ledgered as sent before.
  3. FIRST-PASS CATCH-UP. A permit first seen with 1 day left gets ONE
     reminder saying "1 day"; its ledger key and metadata say 1, never the
     missed 3.

The jobs are the real ones (_dot_permit_expiry_tick, _quiet_queue_tick,
_gc_alerts_tick) over an in-memory db; the sender and the WhatsApp wire are
captured. Permit rows are the recorded B fixture's records with their numbers
and dates changed (SYNTHETIC, said where made). Saturday 2026-11-07's quiet
window is lib/shabbos's own.

CONTROL RUN: on #853's head before this change (268dd087) every test here
fails -- one email per permit, the reminder goes at Saturday 07:00, and the
1-day catch-up is ledgered under the 3-day threshold.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402
from lib import dot_sync, shabbos  # noqa: E402
from tests.test_dot_permits_setup import BY_NUM, _DB, _run  # noqa: E402

UTC = timezone.utc
REC = BY_NUM["B022026215B30"]        # recorded: Blue Elm, 588 Hopkinson


def _at(d: date, hour_utc=12) -> datetime:
    return datetime(d.year, d.month, d.day, hour_utc, 0, tzinfo=UTC)


def _row(num, end: date, **kw):
    """SYNTHETIC: the recorded permit with another number and work end."""
    log = dot_sync.to_log("dot_permit", {**REC, "permitnumber": num,
                                         "issuedworkenddate": f"{end.isoformat()}T23:59:59.000",
                                         "permitstatusshortdesc": "ISSUED & PRINTED"})
    return {**log, "_id": f"r_{num}", "project_id": "p1", "company_id": "c1",
            "match": {"how": "address", "state": "confirmed"}, "renewed_by": None,
            "detected_at": datetime(2026, 9, 1, tzinfo=UTC), **kw}


class _World:
    def __init__(self, rows, shabbos_off=True, first_pass=datetime(2026, 9, 1, tzinfo=UTC)):
        self.db = _DB()
        self.db.companies.docs.append({"_id": "c1", "name": "Blue Elm Inc"})
        self.db.projects.docs.append({"_id": "p1", "company_id": "c1", "name": "588 Thomas S Boyland",
                                      "address": "588 Thomas S Boyland St, Brooklyn, NY"})
        self.db.users.docs.append({"_id": "u1", "company_id": "c1", "role": "admin",
                                   "email": "admin@blueelm.test"})
        self.db.source_sync_state.docs.append({"_id": "p1", "company_id": "c1", "sources": {
            "dot_permits": {"first_synced_at": first_pass, "synced_at": first_pass}}})
        self.db.notification_preferences.docs.append(
            {"_id": "np", "user_id": None, "scope": "project", "project_id": "p1", "company_id": "c1",
             "whatsapp_project": {"chase_shabbos_off": shabbos_off}})
        self.db.dot_logs.docs += rows
        self.send = AsyncMock(return_value={"status": "sent"})

    def _go(self, coro_fn, now):
        with patch.object(server, "db", self.db), \
                patch.object(server, "RESEND_API_KEY", "re_test_key"), \
                patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": ""}), \
                patch("lib.notifications.send_notification", self.send):
            return _run(coro_fn(now=now))

    def expiry(self, now):
        return self._go(server._dot_permit_expiry_tick, now)

    def queue(self, now):
        return self._go(server._quiet_queue_tick, now)

    def late(self, now):
        """The run after each DOT sync (`_dot_sync_job`)."""
        return self._go(lambda now: server._dot_permit_expiry_tick(now=now, late_only=True), now)

    def add(self, row):
        self.db.dot_logs.docs.append(row)

    def emails(self):
        return [c.kwargs for c in self.send.await_args_list if c.kwargs["trigger_type"] == "dot_permit_expiring"]


NUMS = [f"B022026299X{i:02d}" for i in range(1, 17)]


def _ny(d: date, hour: int) -> datetime:
    """A New York wall time (EST: November after the change)."""
    return datetime(d.year, d.month, d.day, hour + 5, 0, tzinfo=UTC)


class LateItems(unittest.TestCase):
    """Operator ruling 2026-10-24: once today's digest has gone, an item with
    <= 1 day left found later is sent AT ONCE, in its own email (the Shabbos
    hold still applies); anything with more days left waits for tomorrow's."""

    TUE = date(2026, 11, 10)

    def test_digest_at_0700_then_a_permit_expiring_tomorrow_found_at_1000_is_one_email_at_1000(self):
        w = _World([_row("A1", self.TUE + timedelta(days=10))])
        w.expiry(_ny(self.TUE, 7))                                  # the 07:00 digest: A1
        self.assertEqual(len(w.emails()), 1)
        w.add(_row("B1", self.TUE + timedelta(days=1)))              # the sync finds B1 at 10:00
        r = w.late(_ny(self.TUE, 10))
        mails = w.emails()
        self.assertEqual(len(mails), 2, [m["subject"] for m in mails])
        late = mails[1]
        self.assertTrue(late["subject"].startswith("1 DOT permit expiring on"), late["subject"])
        self.assertIn("B1", late["text"])
        self.assertIn("(in 1 day):", late["text"])
        self.assertNotIn("A1", late["text"])                         # not the digest again
        self.assertEqual(late["permit_renewal_id"], "dot:p1:expiry_late:B1:-:2026-11-10")
        self.assertEqual(r["late"], 1)
        w.late(_ny(self.TUE, 12))                                   # the next sync: nothing more
        w.expiry(_ny(self.TUE + timedelta(days=1), 7))              # tomorrow's digest: not B1 again
        self.assertFalse(any("B1" in m["text"] for m in w.emails()[2:]))

    def test_a_later_item_with_more_days_waits_for_tomorrows_digest(self):
        w = _World([_row("A2", self.TUE + timedelta(days=10))])
        w.expiry(_ny(self.TUE, 7))
        w.add(_row("C2", self.TUE + timedelta(days=2)))              # 2 days left: can wait
        r = w.late(_ny(self.TUE, 10))
        self.assertEqual((len(w.emails()), r["wait_tomorrow"]), (1, 1))
        w.expiry(_ny(self.TUE + timedelta(days=1), 7))              # tomorrow: in the digest
        self.assertEqual(len(w.emails()), 2)
        self.assertIn("C2", w.emails()[1]["text"])

    def test_before_the_0700_run_the_late_run_sends_nothing(self):
        w = _World([_row("B3", self.TUE + timedelta(days=1))])
        r = w.late(_ny(self.TUE, 5))                                # a 05:00 sync
        self.assertEqual((w.emails(), r.get("skipped")), ([], "before_digest_run"))
        w.expiry(_ny(self.TUE, 7))                                  # the digest takes it
        (m,) = w.emails()
        self.assertEqual(m["permit_renewal_id"], "dot:p1:expiry_digest:-:-:2026-11-10")

    def test_a_late_item_on_shabbos_is_held_to_havdalah(self):
        sat = date(2026, 11, 7)
        w = _World([])                                              # keeps Shabbos (chase_shabbos_off)
        w.expiry(_ny(sat, 7))                                       # nothing due: the run marker only
        w.add(_row("B4", sat + timedelta(days=1)))                  # found Saturday 10:00
        r = w.late(_ny(sat, 10))
        self.assertEqual((w.emails(), r["held"]), ([], 1))
        until = shabbos.quiet_until(_ny(sat, 10))
        w.queue(until - timedelta(minutes=5))
        self.assertEqual(w.emails(), [])
        w.queue(until + timedelta(minutes=1))                       # havdalah: it goes, once
        w.queue(until + timedelta(hours=2))
        (m,) = w.emails()
        self.assertIn("B4", m["text"])
        self.assertIn("(in 1 day):", m["text"])


class ADigestADay(unittest.TestCase):

    def test_sixteen_permits_ending_the_same_day_are_one_email(self):
        w = _World([_row(n, date(2026, 11, 20)) for n in NUMS])
        w.expiry(_at(date(2026, 11, 9)))                 # Monday: 11 days left, all in the 14 window
        w.expiry(_at(date(2026, 11, 9), 18))             # again the same day
        w.expiry(_at(date(2026, 11, 10)))                # next day: still the 14 window
        mails = w.emails()
        self.assertEqual(len(mails), 1, [m["subject"] for m in mails])
        m = mails[0]
        self.assertTrue(m["subject"].startswith("16 DOT permits expiring on 588 Thomas S Boyland / "
                                                "16 permisos del DOT por vencer en"), m["subject"])
        self.assertEqual(m["metadata"]["count"], 16)
        self.assertEqual(sorted(i["permit"] for i in m["metadata"]["items"]), NUMS)
        for n in NUMS:
            self.assertIn(n, m["text"])
        self.assertEqual(m["text"].count("Ends Nov 20, 2026 (in 11 days):"), 1)
        self.assertEqual(m["text"].count("Termina el 20 nov 2026 (en 11 días):"), 1)
        self.assertEqual(m["permit_renewal_id"], "dot:p1:expiry_digest:-:-:2026-11-09")
        led = [d for d in w.db.dot_alert_ledger.docs if d.get("kind") == "permit_expiry"]
        self.assertEqual(len(led), 16)                   # each permit's own row

    def test_grouped_by_work_end_date(self):
        w = _World([_row("B1", date(2026, 11, 20)), _row("B2", date(2026, 11, 20)),
                    _row("B3", date(2026, 11, 23))])
        w.expiry(_at(date(2026, 11, 9)))
        (m,) = w.emails()
        t = m["text"]
        self.assertLess(t.index("Ends Nov 20, 2026 (in 11 days):"), t.index("Ends Nov 23, 2026 (in 14 days):"))
        self.assertTrue(t.index("B2") < t.index("Ends Nov 23"), t)
        self.assertTrue(m["subject"].startswith("3 DOT permits expiring"))


class HeldOverShabbos(unittest.TestCase):

    SAT = date(2026, 11, 7)                              # a real Saturday

    def test_saturday_0700_is_sent_after_havdalah_once(self):
        w = _World([_row("B9", date(2026, 11, 21))])    # 14 days out on Saturday
        sat_7am = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)    # 07:00 EST
        until = shabbos.quiet_until(sat_7am)
        self.assertIsNotNone(until)
        self.assertEqual(until.astimezone(shabbos.NY).date(), self.SAT)      # Saturday night
        self.assertGreaterEqual(until.astimezone(shabbos.NY).hour, 17)
        r = w.expiry(sat_7am)
        self.assertEqual((w.emails(), r["held"]), ([], 1))
        self.assertFalse(any(d.get("kind") == "permit_expiry" for d in w.db.dot_alert_ledger.docs))
        (q,) = w.db.wa_quiet_queue.docs
        self.assertEqual(q["send"]["via"], "dot_digest")
        w.expiry(sat_7am + timedelta(hours=3))            # a second run inside the window: nothing new
        self.assertEqual(len(w.db.wa_quiet_queue.docs), 1)
        w.queue(until - timedelta(minutes=5))
        self.assertEqual(w.emails(), [])
        w.queue(until + timedelta(minutes=1))             # havdalah: it goes
        w.queue(until + timedelta(hours=2))
        w.expiry(datetime(2026, 11, 8, 12, 0, tzinfo=UTC))   # Sunday 07:00
        mails = w.emails()
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0]["metadata"]["items"][0]["permit"], "B9")
        self.assertEqual(mails[0]["permit_renewal_id"], "dot:p1:expiry_digest:-:-:2026-11-07")

    def test_a_project_that_does_not_keep_shabbos_gets_it_at_0700(self):
        w = _World([_row("B9", date(2026, 11, 21))], shabbos_off=False)
        w.expiry(datetime(2026, 11, 7, 12, 0, tzinfo=UTC))
        self.assertEqual(len(w.emails()), 1)


class FirstPassCatchUp(unittest.TestCase):

    def test_one_day_left_at_first_sight_says_one_day(self):
        today = date(2026, 11, 10)
        w = _World([_row("B7", today + timedelta(days=1))], first_pass=_at(today, 6))
        w.expiry(_at(today))
        w.expiry(_at(today + timedelta(days=1)))          # 0 left: same window, nothing more
        (m,) = w.emails()
        self.assertTrue(m["subject"].startswith("1 DOT permit expiring on"), m["subject"])
        self.assertIn("(in 1 day):", m["text"])
        self.assertIn("(en 1 día):", m["text"])
        self.assertNotIn("3 days", m["text"])
        self.assertEqual(m["metadata"]["items"], [{"permit": "B7", "days_left": 1,
                                                    "work_end": "2026-11-11"}])
        (led,) = [d for d in w.db.dot_alert_ledger.docs if d.get("kind") == "permit_expiry"]
        self.assertEqual((led["_id"], led["days_left"], led["bucket"]),
                         ("dot:p1:expiry:B7:1d:2026-11-11", 1, 3))
        self.assertNotIn(":3:", led["_id"])


# ── the WhatsApp group post: one per project per day per kind ───────────────

from tests.test_whatsapp_gc_alerts import (  # noqa: E402
    CO_A, NOON, _Ctx, _confirm, _group_sends, _no_ai, _world as _gc_world,
)
from lib import wa_gc  # noqa: E402


class OneGroupPostADay(unittest.TestCase):

    def test_sixteen_permits_one_post(self):
        exp = (wa_gc.today_et(NOON) + timedelta(days=5)).isoformat()
        db = _gc_world()
        rows = [{"_id": f"d_{n}", "project_id": "proj_a", "company_id": CO_A, "record_type": "dot_permit",
                 "raw_id": f"dotpermit:{n}", "number": n, "issue_date": "2026-10-06",
                 "status": "ISSUED & PRINTED", "description": "Sidewalk", "expiration_date": exp,
                 "link": f"https://data.example/{n}", "detected_at": NOON} for n in NUMS]
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._gc_alerts_tick(NOON))                       # baseline
            db.dot_logs.rows.extend(rows)
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=15)))
            _run(server._gc_alerts_tick(NOON + timedelta(hours=2)))
            texts = [s["message"] for s in _group_sends(c)]
        self.assertEqual(len(texts), 1, texts)
        for n in NUMS:
            self.assertIn(f"#{n}", texts[0])
        self.assertIn("16 DOT permits: expiry reminders.", texts[0])
        self.assertIn("16 permisos del DOT", texts[0])


if __name__ == "__main__":
    unittest.main()
