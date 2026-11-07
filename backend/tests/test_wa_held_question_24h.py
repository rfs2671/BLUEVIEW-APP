"""A HELD QUESTION LAPSES AFTER 24 HOURS, AND THE PERSON IS TOLD.

Roy's ruling, 2026-11-06: a "Which company?" (or any question of ours that
holds a message) expires after 24 hours, not 7 days. On expiry the bot DMs
"Your <item> wasn't saved. Send it again." English only (the bot's replies
stay English). The START "Reply YES" question keeps its 30 minutes.

Time is moved by ageing the stored question row (every datetime on it moved
back), so the same tests read the code before the change: there the row
carries a 7-day expiry, a 25-hour-old question is still open, and nothing
tells the person anything.

CONTROL: against origin/main's server.py and lib/wa_dm.py (ed 2002f3b2),
10 of 11 fail; the START 30-minute test passes there, as it must.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from tests.test_wa_dm_across_companies import NAME_A, NAME_B, _db, _texts, _Turn  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, _Ctx  # noqa: E402

CHAT = f"{ADMIN_PHONE}@c.us"
WHICH = f"Which company is this for?\n1) {NAME_A}\n2) {NAME_B}"


def _run(coro):
    return asyncio.run(coro)


def _rows(c, kind=None):
    rows = c.db[server._DM_STATE].rows
    return [r for r in rows if kind is None or r.get("kind") == kind]


def _age(c, kind, delta):
    """Every datetime on the `kind` question row, moved back by `delta`."""
    for r in _rows(c, kind):
        for k, v in list(r.items()):
            if isinstance(v, datetime):
                r[k] = v - delta
        for q in r.get("queue") or []:
            for k, v in list(q.items()):
                if isinstance(v, datetime):
                    q[k] = v - delta


async def _never_quiet(company_id, project_id=None, now=None):
    return None


def _sweep(now=None, quiet=_never_quiet):
    """One sweep. Shabbos / Yom Tov is pinned OFF unless a test passes its
    own: the real clock would hold every notice on a Friday night."""
    with patch.object(server, "_shabbos_quiet", quiet):
        return _run(server._dm_held_sweep_tick(now=now))


def _lost(text):
    return f'Your message "{text}" wasn\'t saved. Send it again.'


class TheHoldIs24Hours(unittest.TestCase):

    def test_after_24_hours_the_person_is_told_and_it_is_closed(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "add a new job at 9 Menahan St", "m1")
            self.assertEqual(_texts(c), [WHICH])
            _age(c, "dm_acct_pick", timedelta(hours=24, minutes=1))
            self.assertEqual(_sweep(), 1)
            self.assertEqual(_texts(c)[-1], _lost("add a new job at 9 Menahan St"))
            self.assertEqual(_rows(c, "dm_acct_pick"), [], "the question is closed")
            t.say(c, "1", "m2")
        self.assertNotIn("add a new job at 9 Menahan St", [x["body"] for x in t.calls],
                         "a lapsed question never acts on the held message")

    def test_at_23_hours_it_still_holds(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "add a new job at 9 Menahan St", "m1")
            _age(c, "dm_acct_pick", timedelta(hours=23))
            self.assertFalse(_sweep())
            self.assertEqual(_texts(c), [WHICH])
            t.say(c, "1", "m2")
        self.assertEqual([(x["as"], x["body"]) for x in t.calls],
                         [("u_a", "add a new job at 9 Menahan St")])

    def test_told_once(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "add a new job at 9 Menahan St", "m1")
            _age(c, "dm_acct_pick", timedelta(hours=25))
            _sweep()
            _sweep()
            told = [m for m in _texts(c) if "wasn't saved" in m]
        self.assertEqual(len(told), 1)

    def test_writing_after_it_lapsed_tells_them_before_the_new_question(self):
        """Lapsed but the sweep has not run yet: the new held message must not
        queue behind a dead question, and the old one is not dropped silently."""
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "add a new job at 9 Menahan St", "m1")
            _age(c, "dm_acct_pick", timedelta(hours=25))
            t.say(c, "add a new job at 77 Kent Ave", "m2")
            texts = _texts(c)
            self.assertIn(_lost("add a new job at 9 Menahan St"), texts)
            self.assertEqual(texts[-1], WHICH, "the new message is asked, not queued")
            self.assertNotIn(server.wa_dm.PENDING_LINES["en"]["queued"], texts)
            t.say(c, "2", "m3")
        self.assertEqual([(x["as"], x["body"]) for x in t.calls],
                         [("u_b", "add a new job at 77 Kent Ave")])

    def test_every_queued_message_is_named(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "add a new job at 9 Menahan St", "m1")
            t.say(c, "add a new job at 77 Kent Ave", "m2")
            _age(c, "dm_acct_pick", timedelta(hours=25))
            _sweep()
            told = _texts(c)[-1]
        self.assertEqual(told, _lost("add a new job at 9 Menahan St") + "\n"
                         + _lost("add a new job at 77 Kent Ave"))

    def test_asked_in_spanish_told_in_english(self):
        t = _Turn()
        with _Ctx(_db()) as c:
            t.say(c, "agrega un trabajo nuevo en 9 Menahan St para la compañía", "m1")
            self.assertTrue(_texts(c)[-1].startswith("¿Para qué compañía es?"))
            _age(c, "dm_acct_pick", timedelta(hours=25))
            _sweep()
        self.assertEqual(_texts(c)[-1],
                         _lost("agrega un trabajo nuevo en 9 Menahan St para la compañía"))

    def test_over_shabbos_the_notice_waits(self):
        t = _Turn()

        async def quiet(company_id, project_id=None, now=None):
            return (now + timedelta(hours=10)) if str(company_id) == CO_A else None
        with _Ctx(_db()) as c:
            t.say(c, "add a new job at 9 Menahan St", "m1")
            _age(c, "dm_acct_pick", timedelta(hours=25))
            self.assertEqual(_sweep(quiet=quiet), 0)
            self.assertEqual(_texts(c), [WHICH], "nothing sent in the quiet")
            row = _rows(c, "dm_acct_pick")[0]
            self.assertGreater(row["expires_at"], datetime.now(timezone.utc) + timedelta(hours=10),
                               "the row outlives the quiet")
            self.assertEqual(_sweep(), 1)
        self.assertEqual(_texts(c)[-1], _lost("add a new job at 9 Menahan St"))

    def test_an_answer_to_a_q_code_is_named_as_that(self):
        with _Ctx(_db()) as c:
            _run(server._dm_state_set("dm_setq_pick", CHAT, server.HELD_QUESTION_SECONDS,
                                      _hold=True, code="Q3", answer="YES", text=None,
                                      labels=["a", "b"], qids=["q1", "q2"], asked="Which one?",
                                      lang="en", queue=[]))
            _age(c, "dm_setq_pick", timedelta(hours=25))
            _sweep()
        self.assertEqual(_texts(c)[-1], "Your answer to Q3 wasn't saved. Send it again.")

    def test_a_question_asked_before_the_24_hour_rule_gets_its_24_hours(self):
        """A row written by the 7-day code: no hold_until, expires 7 days on."""
        with _Ctx(_db()) as c:
            asked = datetime.now(timezone.utc) - timedelta(hours=25)
            c.db[server._DM_STATE].rows.append({
                "_id": "old", "kind": "dm_acct_pick", "group_id": ADMIN_PHONE, "sender": "",
                "held": "add a new job at 9 Menahan St", "labels": [NAME_A, NAME_B],
                "user_ids": ["u_a", "u_b"], "asked": WHICH, "queue": [],
                "asked_at": asked, "updated_at": asked,
                "expires_at": asked + timedelta(days=7)})
            self.assertEqual(_sweep(), 1)
        self.assertEqual(_texts(c)[-1], _lost("add a new job at 9 Menahan St"))


class WhatStaysAsItWas(unittest.TestCase):

    def test_the_start_yes_question_keeps_30_minutes(self):
        """Ruling 3: the START "Reply YES" question holds no message."""
        with _Ctx(_db()) as c:
            _run(server._ask_accounts(CHAT, [{"_id": "u_a", "company_id": CO_A}], ADMIN_PHONE,
                                      mode="start", phone_verified=True, source="t",
                                      lang="en"))
            row = _rows(c, server.ACCOUNTS_STATE)[0]
        left = row["expires_at"] - datetime.now(timezone.utc)
        self.assertLessEqual(left, timedelta(seconds=server.dm_actions.PENDING_SECONDS))
        self.assertGreater(left, timedelta(minutes=25))
        self.assertNotIn("hold_until", row)

    def test_the_hold_is_24_hours_and_the_sweep_is_scheduled(self):
        self.assertEqual(server.HELD_QUESTION_SECONDS, 24 * 3600)
        src = (Path(server.__file__)).read_text(encoding="utf-8")
        body = src[src.index("async def start_scheduler("):] if "async def start_scheduler(" in src \
            else src
        self.assertIn("_dm_held_sweep_job,", body)
        self.assertIn("id='whatsapp_dm_held_sweep'", body)


if __name__ == "__main__":
    unittest.main()
