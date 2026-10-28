"""ONE DOT email per project per day, and no catch-up double reminder.

Operator rulings 2026-10-28:

  1. ONE DIGEST. The holiday embargo, the permit expiry reminders and the
     hearing reminders due on a day are ONE email per project, a section per
     kind (Holiday embargo / Permit expiring / Hearing reminders), English
     then Spanish, each item with its permit or ticket and TRUE days left --
     not one email per kind or per permit. The WhatsApp group gets ONE DOT
     post per project per day the same way. The ledger stays one row per
     item (plus the day's digest row the email is sent under).
  2. CATCH-UP. An item first reminded late (its threshold already passed --
     4 days left in the 14-day window) skips every lower threshold that falls
     within the next 2 days (the 3-day one at 3 days left): no "4 days" then
     "3 days" on consecutive days. Hearings 14/7/1 and the group's DOT permit
     posts 30/14/7/1 the same. The late rule (<= 1 day, sent at once after the
     digest has gone) never sends a skipped threshold.

The jobs are the real ones, driven by the names main already had
(_dot_embargo_alert_job is the 07:00 job; _dot_permit_expiry_tick /
_dot_hearing_tick with late_only=True are what the 2-hourly sync runs;
_quiet_queue_tick; _gc_alerts_tick) over in-memory dbs; the sender and the
WhatsApp wire are captured. Records are the recorded fixtures (B: permit
B022026215B30; A: OATH 0704345548) with numbers and dates changed --
SYNTHETIC, said where made. No phone numbers, no links that skip login.

CONTROL RUN: against origin/main's code (bf370457) the digest, group-post and
catch-up tests here fail -- 7 emails for the 6 + 1 day, one post per embargo
permit, a "3 days" email the day after "4 days".
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402
from lib import dot_sync, shabbos, wa_gc  # noqa: E402
from tests.test_dot_expiry_digest import REC, _World, _row  # noqa: E402
from tests.test_dot_summonses import summons  # noqa: E402
from tests.test_dot_permits_setup import _run  # noqa: E402

UTC = timezone.utc
NOV1 = date(2026, 11, 1)                       # Sunday: the embargo's first reminder day
EMBARGO_NUMS = [f"B022026305E{i:02d}" for i in range(1, 7)]
EXPIRY_NUM = "B022026305X01"
TICKET = "0704399101"


def _ny7(d: date) -> datetime:
    """07:00 New York (EST after Nov 1)."""
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC)


def _embargo_row(num: str):
    """SYNTHETIC: the recorded permit, another number, working Oct 20 - Dec 20,
    no waiver (stipulation 410 absent)."""
    return _row(num, date(2026, 12, 20), holiday_waiver=False, work_start="2026-10-20T00:00:00.000")


def _expiry_row(num: str, end: date, **kw):
    """SYNTHETIC: the recorded permit, another number and work end; it HAS
    the waiver, so only its expiry is due."""
    return _row(num, end, holiday_waiver=True, **kw)


def _hearing_row(ticket: str, hearing: date):
    """SYNTHETIC: recorded summons 0704345548, another ticket and hearing date."""
    log = dot_sync.to_log("dot_violation", summons("0704345548", ticket_number=ticket, hearing=hearing))
    return {**log, "_id": f"h_{ticket}", "project_id": "p1", "company_id": "c1",
            "match": {"how": "address", "state": "confirmed"},
            "detected_at": datetime(2026, 9, 1, tzinfo=UTC)}


class _Day(_World):
    """test_dot_expiry_digest's world, with the OATH first pass done too, and
    the jobs called as production calls them."""

    def __init__(self, rows, **kw):
        super().__init__(rows, **kw)
        first = datetime(2026, 9, 1, tzinfo=UTC)
        self.db.source_sync_state.docs[0]["sources"]["dot_oath"] = {
            "first_synced_at": first, "synced_at": first}

    def job_0700(self, now):
        return self._go(lambda now: _dot_0700(now), now)

    def late(self, now):
        """What `_dot_sync_job` runs after each sync (main: both late ticks)."""
        async def both(now):
            await server._dot_permit_expiry_tick(now=now, late_only=True)
            await server._dot_hearing_tick(now=now, late_only=True)
        return self._go(both, now)

    def all_emails(self):
        return [c.kwargs for c in self.send.await_args_list]

    def item_rows(self):
        return [d for d in self.db.dot_alert_ledger.docs
                if d.get("permit") or d.get("ticket")]


async def _dot_0700(now):
    """The 07:00 New York job, pinned to `now`."""
    from unittest.mock import patch
    real = {n: getattr(server, n) for n in ("_dot_embargo_alert_tick", "_dot_permit_expiry_tick",
                                            "_dot_hearing_tick")}
    digest = getattr(server, "_dot_daily_digest_tick", None)
    patches = [patch.object(server, n, (lambda f: (lambda **kw: f(now=now, **kw)))(f))
               for n, f in real.items()]
    if digest is not None:
        patches.append(patch.object(server, "_dot_daily_digest_tick",
                                    (lambda f: (lambda **kw: f(**{"now": now, **kw})))(digest)))
    for p in patches:
        p.start()
    try:
        await server._dot_embargo_alert_job()
    finally:
        for p in patches:
            p.stop()


def _six_and_one():
    return [_embargo_row(n) for n in EMBARGO_NUMS] + [_expiry_row(EXPIRY_NUM, NOV1 + timedelta(days=14))]


class OneEmailADay(unittest.TestCase):

    def test_six_embargo_and_one_expiry_are_one_email(self):
        w = _Day(_six_and_one(), shabbos_off=False)
        w.job_0700(_ny7(NOV1))
        mails = w.all_emails()
        self.assertEqual(len(mails), 1, [m["subject"] for m in mails])       # one recipient, one email
        m = mails[0]
        self.assertEqual(m["permit_renewal_id"], "dot:p1:dot_digest:-:-:2026-11-01")
        self.assertEqual(m["trigger_type"], "dot_daily_digest")
        self.assertEqual(m["subject"],
                         "DOT today on 588 Thomas S Boyland: 6 permits without a holiday embargo waiver, "
                         "1 permit expiring / DOT hoy en 588 Thomas S Boyland: 6 permisos sin exención del "
                         "embargo navideño, 1 permiso por vencer")
        t = m["text"]
        # English, then Spanish; a section per kind, in order.
        order = ["Holiday embargo\n", "Permit expiring\n", "Embargo navideño\n", "Permiso por vencer\n"]
        at = [t.index(s) for s in order]
        self.assertEqual(at, sorted(at), t)
        self.assertEqual(t.count("Holiday embargo\n"), 1)
        for n in EMBARGO_NUMS:
            self.assertEqual(t.count(f"  {n} · "), 2, n)                 # one EN line, one ES line
        self.assertIn("Embargo: Nov 15, 2026 - Jan 2, 2027 (starts in 14 days)", t)
        self.assertIn("Embargo: 15 nov 2026 - 2 ene 2027 (empieza en 14 días)", t)
        self.assertIn("Ends Nov 15, 2026 (in 14 days):", t)
        self.assertIn("Termina el 15 nov 2026 (en 14 días):", t)
        self.assertIn(f"  {EXPIRY_NUM} · ", t)
        self.assertEqual(m["metadata"]["sections"], {"embargo": 6, "expiry": 1})
        self.assertEqual(len(m["metadata"]["items"]), 7)
        self.assertIn("<h3", m["html"])
        # The ledger: one row per item -- 7 -- each pointing at the one email.
        items = w.item_rows()
        self.assertEqual(len(items), 7, [d["_id"] for d in items])
        self.assertEqual({d["digest"] for d in items}, {"dot:p1:dot_digest:-:-:2026-11-01"})
        self.assertEqual(sorted(d["_id"] for d in items if d.get("permit") in EMBARGO_NUMS),
                         sorted(f"dot:p1:embargo:{n}:2026:2026-11-01" for n in EMBARGO_NUMS))
        self.assertIn(f"dot:p1:expiry:{EXPIRY_NUM}:14d:2026-11-15", [d["_id"] for d in items])
        # A second run the same day sends nothing and writes no row.
        n_rows = len(w.db.dot_alert_ledger.docs)
        w.job_0700(_ny7(NOV1) + timedelta(hours=4))
        w.late(_ny7(NOV1) + timedelta(hours=5))
        self.assertEqual(len(w.all_emails()), 1)
        self.assertEqual(len(w.db.dot_alert_ledger.docs), n_rows)

    def test_hearings_join_the_same_digest(self):
        w = _Day(_six_and_one() + [_hearing_row(TICKET, NOV1 + timedelta(days=7))], shabbos_off=False)
        w.job_0700(_ny7(NOV1))
        (m,) = w.all_emails()
        t = m["text"]
        order = ["Holiday embargo\n", "Permit expiring\n", "Hearing reminders\n",
                 "Embargo navideño\n", "Permiso por vencer\n", "Recordatorios de audiencia\n"]
        at = [t.index(s) for s in order]
        self.assertEqual(at, sorted(at), t)
        self.assertIn("Hearing Nov 8, 2026 (in 7 days):", t)
        self.assertIn("Audiencia el 8 nov 2026 (en 7 días):", t)
        self.assertIn(f"  {TICKET} · ", t)
        self.assertEqual(m["metadata"]["sections"], {"embargo": 6, "expiry": 1, "hearing": 1})
        self.assertTrue(m["subject"].endswith("1 audiencia próxima"), m["subject"])
        self.assertEqual(len(w.item_rows()), 8)
        self.assertIn(f"dot:p1:hearing:{TICKET}:7d:2026-11-08", [d["_id"] for d in w.item_rows()])

    def test_a_late_item_after_the_digest_is_its_own_email_once(self):
        w = _Day(_six_and_one(), shabbos_off=False)
        w.job_0700(_ny7(NOV1))
        w.add(_expiry_row("B022026305L01", NOV1 + timedelta(days=1)))     # the 10:00 sync finds it
        w.add(_hearing_row("0704399102", NOV1 + timedelta(days=1)))
        w.late(_ny7(NOV1) + timedelta(hours=3))
        w.late(_ny7(NOV1) + timedelta(hours=5))
        mails = w.all_emails()
        self.assertEqual(len(mails), 2, [m["subject"] for m in mails])
        late = mails[1]
        self.assertEqual(late["permit_renewal_id"], "dot:p1:dot_late:0704399102+B022026305L01:-:2026-11-01")
        self.assertIn("(in 1 day):", late["text"])
        self.assertIsNone(re.search(r"  B022026305E\d\d · ", late["text"]))   # not the embargo again


class HeldOverShabbos(unittest.TestCase):

    def test_a_saturday_mix_is_held_once_and_sent_whole_after_havdalah(self):
        sat = date(2026, 11, 7)
        w = _Day([_expiry_row(EXPIRY_NUM, sat + timedelta(days=14)),
                  _hearing_row(TICKET, sat + timedelta(days=7))])            # keeps Shabbos
        w.job_0700(_ny7(sat))
        self.assertEqual(w.all_emails(), [])
        self.assertEqual(len(w.db.wa_quiet_queue.docs), 1)                   # one hold, not one per kind
        self.assertEqual(w.item_rows(), [])                                  # nothing ledgered as sent
        until = shabbos.quiet_until(_ny7(sat))
        w.queue(until - timedelta(minutes=5))
        self.assertEqual(w.all_emails(), [])
        w.queue(until + timedelta(minutes=1))
        w.queue(until + timedelta(hours=2))
        (m,) = w.all_emails()
        self.assertEqual(m["metadata"]["sections"], {"expiry": 1, "hearing": 1})
        self.assertGreaterEqual(until.astimezone(shabbos.NY).hour, 17)


class CatchUp(unittest.TestCase):

    def test_caught_up_at_4_days_then_no_3_day_email_next_day(self):
        today = date(2026, 11, 10)
        w = _Day([_expiry_row(EXPIRY_NUM, today + timedelta(days=4))], shabbos_off=False)
        for i in range(5):                                                   # 4, 3, 2, 1, 0 days left
            w.job_0700(_ny7(today + timedelta(days=i)))
            w.late(_ny7(today + timedelta(days=i)) + timedelta(hours=3))
        mails = w.all_emails()
        self.assertEqual(len(mails), 1, [m["text"] for m in mails])
        self.assertIn("Ends Nov 14, 2026 (in 4 days):", mails[0]["text"])
        (row,) = w.item_rows()
        self.assertEqual((row["bucket"], row["days_left"]), (14, 4))

    def test_on_time_14_day_reminder_still_gets_its_3_day_one(self):
        today = date(2026, 11, 10)
        w = _Day([_expiry_row(EXPIRY_NUM, today + timedelta(days=14))], shabbos_off=False)
        for i in (0, 11):
            w.job_0700(_ny7(today + timedelta(days=i)))
        self.assertEqual([(r["bucket"], r["days_left"]) for r in w.item_rows()], [(14, 14), (3, 3)])

    def test_a_hearing_caught_up_at_8_days_skips_the_7_and_keeps_the_1(self):
        today = date(2026, 11, 10)
        w = _Day([_hearing_row(TICKET, today + timedelta(days=8))], shabbos_off=False)
        for i in range(8):
            w.job_0700(_ny7(today + timedelta(days=i)))
        got = sorted((r["bucket"], r["days_left"]) for r in w.item_rows())
        self.assertEqual(got, [(1, 1), (14, 8)])

    def test_the_late_run_never_sends_a_skipped_threshold(self):
        today = date(2026, 11, 10)
        w = _Day([_hearing_row(TICKET, today + timedelta(days=2))], shabbos_off=False)
        w.job_0700(_ny7(today))                                              # 2 days: the 7 window, caught up
        w.job_0700(_ny7(today + timedelta(days=1)))                          # 1 day: within 2 days -> skipped
        w.late(_ny7(today + timedelta(days=1)) + timedelta(hours=3))
        self.assertEqual(len(w.all_emails()), 1)
        self.assertEqual([(r["bucket"], r["days_left"]) for r in w.item_rows()], [(7, 2)])


# ── the WhatsApp group post ─────────────────────────────────────────────────

from tests.test_whatsapp_gc_alerts import (  # noqa: E402
    CO_A, NOON, _Ctx, _confirm, _group_sends, _no_ai, _world as _gc_world,
)

GC_NOV1 = datetime(2026, 11, 1, 16, 0, tzinfo=UTC)          # 11 AM New York, Sunday


def _gc_row(num: str, end: date, waiver: bool):
    """SYNTHETIC: the recorded permit, another number and work end, on the GC
    test world's project."""
    log = dot_sync.to_log("dot_permit", {**REC, "permitnumber": num,
                                         "issuedworkenddate": f"{end.isoformat()}T23:59:59.000",
                                         "issuedworkstartdate": "2026-10-20T00:00:00.000",
                                         "permitstatusshortdesc": "ISSUED & PRINTED"})
    return {**log, "_id": f"g_{num}", "project_id": "proj_a", "company_id": CO_A,
            "holiday_waiver": waiver, "detected_at": datetime(2026, 9, 1, tzinfo=UTC)}


class OneGroupPostADay(unittest.TestCase):

    def test_six_embargo_and_one_expiry_are_one_post(self):
        rows = [_gc_row(n, date(2026, 12, 20), False) for n in EMBARGO_NUMS] \
            + [_gc_row(EXPIRY_NUM, NOV1 + timedelta(days=14), True)]
        db = _gc_world(dot_logs=rows)
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._gc_alerts_tick(datetime(2026, 10, 22, 15, 0, tzinfo=UTC)))     # the baseline
            for h in (0, 1, 3):
                _run(server._gc_alerts_tick(GC_NOV1 + timedelta(hours=h)))
            texts = [s["message"] for s in _group_sends(c)]
        self.assertEqual(len(texts), 1, texts)
        t = texts[0]
        for n in EMBARGO_NUMS + [EXPIRY_NUM]:
            self.assertEqual(t.count(f"#{n}"), 2, n)                         # EN section and ES section
        for s in ("DOT today: 6 permits without a holiday embargo waiver, 1 permit expiring.",
                  "Holiday embargo:", "Permit expiring:", "Ends Nov 15, 2026 (in 14 days):",
                  "DOT hoy: 6 permisos sin exención del embargo navideño, 1 permiso por vencer.",
                  "Embargo navideño:", "Permiso por vencer:", "Termina el 15 nov 2026 (en 14 días):"):
            self.assertIn(s, t)
        self.assertLess(t.index("Permit expiring:"), t.index("DOT hoy:"))
        led = db.whatsapp_notification_ledger.rows
        members = [x for x in led if x.get("status") == "in_digest"]
        self.assertEqual(len(members), 7, [x["_id"] for x in members])
        (day,) = [x for x in led if str(x["_id"]).endswith(":digest:2026-11-01")]
        self.assertEqual(day["_id"], "gc:proj_a:dot_digest:digest:2026-11-01")
        self.assertEqual({x["digest"] for x in members}, {day["_id"]})

    def test_a_dot_permit_post_caught_up_at_8_days_has_no_7_day_post_next_day(self):
        today = wa_gc.today_et(NOON)
        db = _gc_world()
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._gc_alerts_tick(NOON))                                # the baseline
            db.dot_logs.rows.append(_gc_row(EXPIRY_NUM, today + timedelta(days=8), True))
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=15)))       # 8 days: the 14 post
            for d in (1, 2):
                _run(server._gc_alerts_tick(NOON + timedelta(days=d)))
            texts = [s["message"] for s in _group_sends(c) if f"#{EXPIRY_NUM}" in s["message"]]
        self.assertEqual(len(texts), 1, texts)


if __name__ == "__main__":
    unittest.main()
