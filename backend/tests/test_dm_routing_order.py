"""DM routing order (live, Mon 7:17 PM).

"Starting a new job I wanna set up" -> "Which job? 1) 588 2) 8 Walworth".
The model missed the request (no address yet), the patterns had no form
without one, and the DM went to the questions assistant, whose job picker
asked "Which job?".

The order, through the REAL DM entry point (_process_whatsapp_message):
  1. active flows (walkthrough, a pending confirm, a pending question);
  2. what they want (a change vs. a question vs. anything else);
  3. "Which job?" ONLY when that needs an existing job and none can be
     inferred (their only job, a job named in the text, or the job picked in
     the last 30 minutes).
A new job never asks "Which job?"; with no address: "Sure — what's the
address?". Every phrasing of the DM-actions spec, with and without its
address / job, with the model unavailable AND with the model missing it.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import dm_actions  # noqa: E402
from tests.test_whatsapp_dm_assistant import (  # noqa: E402
    ADMIN_PHONE, THOMAS, WALWORTH, _Ctx, _Harness, _db, _optin,
)

CHAT = f"{ADMIN_PHONE}@c.us"
ADDRESS_Q = "Sure — what's the address?"

# The add-a-job phrasings of the spec, each with its address and without.
NEW_JOB = [
    ("add 9 menahan", "add a new job"),
    ("we got a new job on 9 menahan st", "we got a new job"),
    ("start tracking 588 thomas boyland", "start tracking a new job"),
    ("nuevo trabajo en 9 menahan", "nuevo trabajo"),
    ("Add 9 Menahan St Brooklyn please", "Add a new job please"),
    ("we just got a new job 1420 fulton st bk", "we just got a new job"),
    ("track 852 e 176 st bronx", "track a new site"),
    ("hey can you add 77 water st 10005", "hey can you add a job"),
    ("agrega 9 menahan", "agrega un trabajo"),
    ("so we picked up a new job 45 Bay Ridge Ave", "so we picked up a new job"),
    (None, "Starting a new job I wanna set up"),              # the live message
    (None, "new project coming, need to set it up"),
    (None, "I have another job to add"),
    # Asked politely is still a request (Codex review on #771).
    (None, "Do you mind adding a new job?"),
    (None, "can you set up a new job for me?"),
]

# The rest of the spec, each with the job it is about (or everything it needs)
# and without: the first reply. "Which job?" only where a job is needed and
# none can be inferred (two jobs here, none named, none picked recently).
OTHER = [
    # (with job / details, expected start)    (without, expected start)
    (("put bright electric on 588 they're the electrician", "Add Bright Electric (Electrical) to 588"),
     ("I want to add a sub", "Which company?")),
    (("put Arkon on 588 as the plumber", "Add Arkon (Plumbing) to 588"),
     ("add a new sub", "Which company?")),
    (("pon a arkon en 588 son los plomeros", "¿Agrego a Arkon (Plumbing) en 588"),
     ("agregar un sub", "¿Qué compañía?")),
    (("chris is our super his number is 718 555 1234", "Save Chris"),
     ("need to add someone", "What's their name?")),
    (("Chris Weiss 718-555-1234 from Arkon", None),
     ("add a new contact", "What's their name?")),
    (("dov handles punch for power direct", None),
     ("set up punch contact", "Which company?")),
    (("punch contact for arkon is chris", None),
     ("change the punch contact", "Which company?")),
    (("stop bugging people on weekends at 588", "Just Shabbos (Fri evening to Sat night), or Sunday too?"),
     ("stop bugging people on weekends", "Which job?")),
    (("start sending punch lists for real at 588", "This makes punch lists really go out"),
     ("start sending punch lists for real", "Which job?")),
]


def _world():
    db = _db()
    _optin(db, "u_admin", ADMIN_PHONE)
    for p in db.projects.rows:
        if p["_id"] == THOMAS:
            p["trade_assignments"] = [{"id": "t1", "company": "Power Direct", "trade": "Electrical"}]
        if p["_id"] == WALWORTH:
            p["trade_assignments"] = [{"id": "t2", "company": "Arkon", "trade": "Drywall"}]
    return db


class _Dm(_Harness):

    def setUp(self):
        super().setUp()
        self.model = None                       # None: the model cannot be asked

    def dm(self, c, *lines):
        """Each line through the webhook as a DM; every reply sent."""
        async def model(text, jobs):
            return self.model(text) if callable(self.model) else self.model

        async def geo(text, size=5):
            label = f"{text.upper()}, {dm_actions.find_borough(text) or 'Brooklyn'}, NY, USA"
            return [{"label": label, "place": dm_actions.pretty_address(label),
                     "borough": dm_actions.find_borough(text) or "Brooklyn",
                     "zip": dm_actions.find_zip(text) or "11201"}]
        out = []
        with patch.object(server, "_dm_action_model", model), \
                patch.object(server, "_dm_geosearch", geo):
            for i, line in enumerate(lines):
                before = len([p for p in c.wire.calls if "message" in p])
                self._send(c, CHAT, line, mid=f"M{len(c.wire.calls)}_{i}")
                out.append([p["message"] for p in c.wire.calls if "message" in p][before:])
        return out


class ANewJobNeverAsksWhichJob(_Dm, unittest.TestCase):

    def check(self, said, with_address):
        with _Ctx(db=_world()) as c:
            (replies,) = self.dm(c, said)
        self.assertEqual(len(replies), 1, replies)                  # one short reply
        reply = replies[0]
        self.assertNotIn("Which job", reply)
        self.assertNotIn("¿Cuál trabajo", reply)
        if with_address:
            self.assertNotEqual(reply, ADDRESS_Q)
            self.assertTrue(reply.startswith(("Found it:", "Lo encontré:")), reply)
        else:
            self.assertIn(reply, (ADDRESS_Q, "Claro, ¿cuál es la dirección?"))
        self.assertEqual(self.agent_calls, [])                     # never the questions assistant

    def test_every_phrasing_with_and_without_an_address(self):
        for model in (None, {"action": "none"}):                   # unavailable / missed it
            for with_addr, without in NEW_JOB:
                for said, has in ((with_addr, True), (without, False)):
                    if said is None:
                        continue
                    with self.subTest(model=model, said=said):
                        self.model = model
                        self.check(said, has)

    def test_the_live_message_then_the_address(self):
        with _Ctx(db=_world()) as c:
            ask, found = self.dm(c, "Starting a new job I wanna set up", "9 menahan st")
        self.assertEqual(ask, [ADDRESS_Q])
        self.assertEqual(found, ["Found it: 9 Menahan St, Brooklyn. Add it as a new job?"])

    def test_when_the_model_reads_it_the_same_question(self):
        self.model = {"action": "add_job"}
        self.check("Starting a new job I wanna set up", False)

    def test_spanish_no_address(self):
        with _Ctx(db=_world()) as c:
            (r,) = self.dm(c, "nuevo trabajo")
        self.assertEqual(r, ["Claro, ¿cuál es la dirección?"])


class EveryOtherRequestFirst(_Dm, unittest.TestCase):

    def first(self, said):
        with _Ctx(db=_world()) as c:
            (replies,) = self.dm(c, said)
        self.assertEqual(len(replies), 1, (said, replies))
        self.assertEqual(self.agent_calls, [], said)               # a request, not a question
        return replies[0]

    def test_with_and_without_the_job(self):
        for model in (None, {"action": "none"}):
            self.model = model
            for (with_job, want_with), (without, want_without) in OTHER:
                with self.subTest(model=model, said=with_job):
                    r = self.first(with_job)
                    self.assertNotIn("Which job", r)
                    if want_with:
                        self.assertTrue(r.startswith(want_with), r)
                with self.subTest(model=model, said=without):
                    r = self.first(without)
                    self.assertTrue(r.startswith(want_without), r)

    def test_codex_771_polite_requests(self):
        for said, want in (("can you add a sub?", "Which company?"),
                           ("would you mind adding someone", "What's their name?"),
                           ("could you set up a punch contact", "Which company?")):
            with self.subTest(said):
                self.assertEqual(self.first(said), want)

    def test_one_short_question_each(self):
        for said, want in (("I want to add a sub", "Which company?"),
                           ("need to add someone", "What's their name?"),
                           ("set up punch contact", "Which company?")):
            with self.subTest(said):
                r = self.first(said)
                self.assertEqual(r, want)
                self.assertLessEqual(len(r.split()), 6)


class WhichJobOnlyWhenNeeded(_Dm, unittest.TestCase):

    def test_a_sub_on_the_job_picked_in_the_last_30_minutes(self):
        db = _world()
        with _Ctx(db=db) as c:
            # A question about 8 Walworth picks it for 30 minutes.
            self._send(c, CHAT, "who's on site at 8 walworth", mid="Q1")
            co, trade = self.dm(c, "I want to add a sub", "Power Direct")
        self.assertEqual(co, ["Which company?"])
        self.assertEqual(trade, ["What trade is Power Direct?"])     # no "Which job?"

    def test_two_jobs_none_named_none_recent_asks(self):
        with _Ctx(db=_world()) as c:
            co, which = self.dm(c, "I want to add a sub", "Power Direct")
        self.assertEqual(co, ["Which company?"])
        self.assertTrue(which[0].startswith("Which job?"), which)

    def test_a_job_named_in_the_text_is_used(self):
        with _Ctx(db=_world()) as c:
            (r,) = self.dm(c, "ok to chase on weekends at 8 walworth")
        self.assertNotIn("Which job", r[0])
        self.assertIn("8 Walworth", r[0])

    def test_a_setting_on_the_job_picked_recently(self):
        with _Ctx(db=_world()) as c:
            self._send(c, CHAT, "who's on site at 588", mid="Q1")
            (r,) = self.dm(c, "ok to chase on weekends")
        self.assertNotIn("Which job", r[0])
        self.assertIn("588", r[0])

    def test_one_job_never_asks(self):
        db = _world()
        for p in db.projects.rows:
            if p["_id"] == WALWORTH:
                p["is_deleted"] = True
        with _Ctx(db=db) as c:
            co, trade = self.dm(c, "I want to add a sub", "Power Direct")
        self.assertEqual(trade, ["What trade is Power Direct?"])


class ActiveFlowsFirst(_Dm, unittest.TestCase):

    def test_a_pending_question_takes_the_answer(self):
        with _Ctx(db=_world()) as c:
            ask, found = self.dm(c, "Starting a new job I wanna set up", "45 main st")
        self.assertEqual(ask, [ADDRESS_Q])
        self.assertTrue(found[0].startswith("Found it: 45 Main St"), found)

    def test_a_pending_confirm_takes_the_yes(self):
        with _Ctx(db=_world()) as c:
            ask, done = self.dm(c, "add 9 menahan", "yes")
        self.assertTrue(ask[0].startswith("Found it: 9 Menahan"), ask)
        self.assertTrue(done[0].startswith("Done"), done)

    def test_the_which_job_menu_still_answers_a_question(self):
        with _Ctx(db=_world()) as c:
            menu = self._send(c, CHAT, "what's open?", mid="Q1")
            answer = self._send(c, CHAT, "2", mid="Q2")
        # A question that needs a job, none named, none recent: the menu --
        # and the pick answers it (never read as a new request).
        self.assertTrue(menu.startswith("Which job?"), menu)
        self.assertEqual(answer, f"answer for {WALWORTH}")

    def test_a_question_is_still_a_question(self):
        with _Ctx(db=_world()) as c:
            self._send(c, CHAT, "any new jobs this week at 588?", mid="Q1")
        self.assertEqual(len(self.agent_calls), 1)


if __name__ == "__main__":
    unittest.main()
