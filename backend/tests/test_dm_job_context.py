"""Which job, before ever asking (Thu 9:03-9:05 AM, after the 588 walk was
sent in shadow mode):

  9:03 "Was it sent to the GC team group chat?"      -> "Which job?"
  9:04 "The list" (a reply to the 588 shadow message) -> "Which job?" again

The job is read from, in order: (a) the message replied to, (b) the walk
going on or just finished (2 h), (c) the job named in this DM in the last
30 min, (d) the only job the question could be about (a punch question: the
job with the latest punch activity). Asked only when still unknown, and then
with the likely one first ("Which job — 588 …? Or another:")."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import server  # noqa: E402
from lib import punch, wa_assistant, wa_facts  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, WALWORTH, _run  # noqa: E402
from tests.test_whatsapp_dm_picker_headcount import CHAT, _Chat  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx  # noqa: E402

#: The bot's 9:01 message, as it was sent (shortened).
SHADOW = ("Punch sends are in shadow mode: nothing was sent.\n\n"
          "Would post in 588 GC team, mentioning Meilich Friedman:\n"
          "588 THOMAS S BOYLAND STREET punch list — due ASAP:\n*Cellar*\n• P-588-6 Cellar")
ASKED = "Was it sent to the GC team group chat?"


def _ago(**kw):
    return datetime.now(timezone.utc) - timedelta(**kw)


class _Walk(_Chat):
    def walk(self, project=THOMAS, at=None, status="sent"):
        at = at or _ago(minutes=2)
        self.db[punch.SESSIONS].rows.append({
            "_id": f"w_{project}", "user_id": "u_admin", "company_id": CO_A,
            "project_id": project, "status": status, "updated_at": at, "sent_at": at})
        for i in range(3):
            self.db[punch.COLLECTION].rows.append({
                "_id": f"p_{project}_{i}", "project_id": project, "company_id": CO_A,
                "walk_id": f"w_{project}", "pid": f"P-588-{6 + i}", "status": "open",
                "sent_via": "group_list", "send_mode": "shadow",
                "assignee": {"kind": "user", "id": "u_m", "name": "Meilich Friedman"},
                "created_at": at, "updated_at": at})

    def bot_said(self, body, at):
        self.db.whatsapp_messages.rows.append({
            "_id": f"b{len(self.db.whatsapp_messages.rows)}", "group_id": CHAT, "is_dm": True,
            "sender": "bot", "body": body, "created_at": at})

    def asked_about(self):
        return [c["project_id"] for c in self.agent_calls]


class TheThursdaySequence(_Walk, unittest.TestCase):

    def test_the_exact_sequence(self):
        self.walk()
        self.bot_said(SHADOW, _ago(minutes=2))
        with _Ctx(db=self.db) as c:
            first = self.say(c, ASKED)                                         # 9:03
            second = self.say(c, "The list", quoted=SHADOW, from_bot=True)     # 9:04
        self.assertEqual(first, f"answer for {THOMAS}")                       # never "Which job?"
        self.assertEqual(second, f"answer for {THOMAS}")
        self.assertEqual(self.asked_about(), [THOMAS, THOMAS])

    def test_a_menu_already_open_is_answered_by_the_reply(self):
        # The second half as it happened: a "Which job?" menu open, then a
        # reply to the 588 list. It picks 588 and answers the first question.
        with _Ctx(db=self.db) as c:
            menu = self.say(c, "Any news from the site?")
            self.assertTrue(menu.startswith("Which job"), menu)
            reply = self.say(c, "The list", quoted=SHADOW, from_bot=True)
        self.assertEqual(reply, f"answer for {THOMAS}")
        self.assertEqual(self.agent_calls[0]["body"], "Any news from the site?")


class TheRules(_Walk, unittest.TestCase):

    def test_a_replied_to_message_comes_first(self):
        self.walk()                                       # (b) says 588 ...
        with _Ctx(db=self.db) as c:
            reply = self.say(c, "Any updates?", quoted="8 Walworth St: 3 open items", from_bot=True)
        self.assertEqual(reply, f"answer for {WALWORTH}")   # ... (a) says Walworth

    def test_the_walk_just_finished(self):
        self.walk(at=_ago(minutes=110))
        with _Ctx(db=self.db) as c:
            self.assertEqual(self.say(c, "How many photos were there?"), f"answer for {THOMAS}")

    def test_a_walk_over_2_hours_ago_is_not_the_job(self):
        self.walk(at=_ago(hours=3))
        with _Ctx(db=self.db) as c:
            menu = self.say(c, "How is the inspection going?")
        # Not a punch question: asked -- the walk's job is no longer the job.
        self.assertTrue(menu.startswith("Which job"), menu)

    def test_the_job_named_in_the_last_30_minutes(self):
        self.bot_said("8 Walworth St: 2 on site now.", _ago(minutes=20))
        with _Ctx(db=self.db) as c:
            self.assertEqual(self.say(c, "Any violations?"), f"answer for {WALWORTH}")

    def test_a_punch_question_is_the_job_with_the_latest_punch_activity(self):
        self.walk(project=WALWORTH, at=_ago(days=2))
        self.walk(project=THOMAS, at=_ago(hours=5))
        with _Ctx(db=self.db) as c:
            self.assertEqual(self.say(c, ASKED), f"answer for {THOMAS}")

    def test_asked_with_the_likely_one_first_and_yes_picks_it(self):
        self.bot_said("588 Thomas S Boyland St: 18 on site.", _ago(minutes=90))
        with _Ctx(db=self.db) as c:
            menu = self.say(c, "Any news from the site?")
            self.assertEqual(menu, "Which job — 588 Thomas S Boyland St? Or another: "
                                   "1) 588 Thomas S Boyland St 2) 8 Walworth St")
            self.assertEqual(self.say(c, "yes"), f"answer for {THOMAS}")
        self.assertEqual(self.agent_calls[0]["body"], "Any news from the site?")

    def test_still_unknown_is_asked_plainly(self):
        with _Ctx(db=self.db) as c:
            menu = self.say(c, "Any news from the site?")
        self.assertEqual(menu, "Which job? 1) 588 Thomas S Boyland St 2) 8 Walworth St")


class AChange(_Walk, unittest.TestCase):
    """A change (lib/dm_actions) takes its job by the same rules -- never
    from the topic alone: that job is offered first."""

    def _ident(self):
        projects = [p for p in self.db.projects.rows
                    if p["company_id"] == CO_A and not p.get("is_deleted")]
        return {"user_id": "u_admin", "company_id": CO_A, "projects": projects}

    def test_the_walk_just_finished_is_the_job(self):
        self.walk()
        p = {"action": "job_setting", "lang": "en", "said": "stop chasing on sundays"}
        with _Ctx(db=self.db):
            got = _run(server._dm_pick_job(self._ident(), CHAT, p))
        self.assertEqual(str(got["_id"]), THOMAS)

    def test_the_message_replied_to_is_the_job(self):
        p = {"action": "job_setting", "lang": "en", "said": "stop chasing on sundays",
             "quoted": "8 Walworth St: 2 on site now."}
        with _Ctx(db=self.db):
            got = _run(server._dm_pick_job(self._ident(), CHAT, p))
        self.assertEqual(str(got["_id"]), WALWORTH)

    def test_the_punch_job_is_offered_first_not_taken(self):
        self.walk(at=_ago(hours=5))
        p = {"action": "set_punch_contact", "lang": "en", "said": "punch contact for the list"}
        with _Ctx(db=self.db) as c:
            got = _run(server._dm_pick_job(self._ident(), CHAT, p))
            asked = [x["message"] for x in c.wire.calls if "message" in x][-1]
        self.assertIsNone(got)
        self.assertTrue(asked.startswith("Which job — 588 Thomas S Boyland St? Or another:\n"
                                         "1) 588 Thomas S Boyland St\n2) 8 Walworth St"), asked)
        self.assertTrue(p["_likely_first"])


class Pure(unittest.TestCase):
    JOBS = [{"id": THOMAS, "label": "588 Thomas S Boyland St", "aliases": []},
            {"id": WALWORTH, "label": "8 Walworth St", "aliases": []}]

    def test_the_job_in_a_text(self):
        for text in (SHADOW, "• P-588-6 Cellar", "at 588"):
            with self.subTest(text):
                self.assertEqual(wa_assistant.job_in_text(text, self.JOBS), THOMAS)
        self.assertIsNone(wa_assistant.job_in_text(
            "Which job? 1) 588 Thomas S Boyland St 2) 8 Walworth St", self.JOBS))
        self.assertIsNone(wa_assistant.job_in_text("The list", self.JOBS))
        # Two jobs named (one by a one-digit house number) is no job.
        self.assertIsNone(wa_assistant.job_in_text("588 is done, now 8 Walworth St", self.JOBS))

    def test_a_punch_question(self):
        for t in (ASKED, "The list", "what's open on P-588-6", "did the walkthrough go out"):
            with self.subTest(t):
                self.assertTrue(wa_assistant.about_punch(t))
        self.assertFalse(wa_assistant.about_punch("how many on site?"))

    def test_named_recently(self):
        now = datetime.now(timezone.utc)
        rows = [{"body": "8 Walworth St: 2 on site", "created_at": now - timedelta(minutes=40)},
                {"body": "588 Thomas S Boyland St: 18", "created_at": now - timedelta(minutes=10)},
                {"body": "Which job? 1) 588 Thomas S Boyland St 2) 8 Walworth St",
                 "created_at": now - timedelta(minutes=1)}]
        self.assertEqual(wa_assistant.named_recently(rows, self.JOBS, now), THOMAS)
        # The menu names both jobs: never the job (the 588 row before it is).
        self.assertIsNone(wa_assistant.named_recently(rows[2:], self.JOBS, now))
        self.assertIsNone(wa_assistant.named_recently(rows[:1], self.JOBS, now))
        self.assertEqual(wa_assistant.named_recently(rows[:1], self.JOBS, now, 3600), WALWORTH)

    def test_the_menu_header(self):
        jobs, header = wa_assistant.likely_first(self.JOBS, WALWORTH)
        self.assertEqual([j["id"] for j in jobs], [WALWORTH, THOMAS])
        self.assertEqual(header, "Which job — 8 Walworth St? Or another:")
        self.assertTrue(wa_assistant.is_menu_message(wa_assistant.menu_text(jobs, header)))
        self.assertEqual(wa_assistant.likely_first(self.JOBS, None)[1], "Which job?")


class WasItSent(unittest.TestCase):
    """The punch facts say how the last list went out."""

    def test_shadow(self):
        now = datetime(2026, 10, 15, 13, 5, tzinfo=timezone.utc)
        rows = [{"walk_id": "w", "status": "open", "sent_via": "group_list", "send_mode": "shadow",
                 "created_at": datetime(2026, 10, 15, 13, 1, tzinfo=timezone.utc)}] * 47
        self.assertIn("Last list: 47 items, today 9:01 AM — shadow mode: nothing was actually "
                      "sent (it would have been posted in the job's group chat).",
                      wa_facts.punch_text(rows, now, job="588"))

    def test_live_dm(self):
        now = datetime(2026, 10, 15, 13, 5, tzinfo=timezone.utc)
        rows = [{"walk_id": "w", "status": "open", "sent_via": "dm", "send_mode": "live",
                 "assignee": {"name": "Chris Weiss"},
                 "created_at": datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)}]
        self.assertEqual(wa_facts.last_list_line(rows, now),
                         "Last list: 1 item, yesterday 4:00 PM — DM'd to Chris Weiss.")

    def test_nothing_sent_says_nothing(self):
        self.assertEqual(wa_facts.last_list_line([{"status": "open"}], datetime.now(timezone.utc)), "")


if __name__ == "__main__":
    unittest.main()
