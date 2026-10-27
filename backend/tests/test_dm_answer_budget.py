"""A DM answer has a budget: one "still checking" line, then a give-up.

Owner's decision, Oct 27 (after a 588 answer took seven minutes): "typing…"
until the whole answer is ready -- no partial answers. From the DM's receipt:

  * nothing sent by DM_SLOW_NOTICE_SECONDS (45 s): exactly one line, "Still
    checking the drawings.", and typing goes on;
  * at DM_GIVE_UP_SECONDS (120 s): the turn is cancelled, "Couldn't finish
    that one, try again" goes, and the operators get the #877-style alert
    with the turn's timeline (no full phone number, nobody's words);
  * an answer that finishes after the notice is sent as usual; one that
    races the give-up wins, and the give-up line is not sent;
  * the answer row's timing.budget says which: ok / slow_notice / gave_up.

The clock and the wait are fakes (server._dm_budget_clock / _dm_budget_wait):
no test sleeps for real.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

import server  # noqa: E402
from tests.test_dm_brain import FakeLLM, resp, text, use  # noqa: E402
from tests.test_dm_short_answers import CHAT  # noqa: E402
from tests.test_dm_turn_timing import _Timed  # noqa: E402
from tests.test_whatsapp_dm_assistant import _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import _Ctx  # noqa: E402

NOTICE = server.DM_SLOW_NOTICE_TEXT
GAVE_UP = server.DM_GAVE_UP_TEXT


class _Clock:
    """A fake budget clock. The answer is held until the clock reaches
    `finish_at` (seconds after the start; None: never)."""

    def __init__(self, finish_at=None):
        self.t = 0.0
        self.finish_at = finish_at
        self.gate = None
        self.waits = []

    def now(self):
        return self.t

    async def hold(self):
        """What the fake model awaits: the clock reaching finish_at."""
        if self.gate is None:
            self.gate = asyncio.Event()
        await self.gate.wait()

    async def wait(self, task, seconds):
        self.waits.append(seconds)
        target = self.t + seconds + 1e-6
        # (+0.05: the real seconds the turn had already waited at the start)
        if self.finish_at is not None and self.t < self.finish_at <= target + 0.05:
            if self.gate is None:
                self.gate = asyncio.Event()
            if abs(self.finish_at - server.DM_GIVE_UP_SECONDS) < 1e-3:
                # THE RACE: the answer becomes ready in the very tick the
                # deadline is reached -- the waiter returns without yielding.
                self.t = target
                self.gate.set()
                return
            self.t = self.finish_at
            self.gate.set()
            for _ in range(50):
                if task.done():
                    return
                await asyncio.sleep(0)
            return
        self.t = target


class _HeldLLM(FakeLLM):
    """The scripted model; its LAST call waits for the fake clock."""

    def __init__(self, clock, *script):
        super().__init__(*script)
        self.clock = clock
        self.kwargs = []

    async def create(self, **kw):
        self.kwargs.append(dict(kw))
        if len(self.script) == 1:
            await self.clock.hold()
        return await super().create(**kw)


def _patched(clock, alerts):
    async def alert(key, trigger_type, subject, text_, metadata, tag="x"):
        alerts.append({"key": key, "trigger": trigger_type, "subject": subject,
                       "text": text_, "metadata": metadata})
    return [patch.object(server, "_dm_budget_clock", clock.now),
            patch.object(server, "_dm_budget_wait", clock.wait),
            patch.object(server, "DM_SLOW_NOTICE_SECONDS", 45.0),
            patch.object(server, "DM_GIVE_UP_SECONDS", 120.0),
            patch.object(server, "_operator_alert", alert)]


class _Budget(_Timed):

    def run_brain(self, finish_at, script=None):
        clock = _Clock(finish_at)
        llm = _HeldLLM(clock, *(script or (resp(use("headcount", {"job": "588"})),
                                           resp(text("588: 31 on site right now.")))))
        alerts = []
        ps = _patched(clock, alerts)
        for p in ps:
            p.start()
        try:
            wire = self.ask("how many at 588", llm, typing_every=1000)
        finally:
            for p in reversed(ps):
                p.stop()
        msgs = [p["message"] for a, p in wire.actions if a == "send-message"]
        return msgs, self.row(), alerts, llm, wire


class TheBrainPath(_Budget):

    def test_an_answer_at_10_s_has_no_notice(self):
        msgs, row, alerts, _llm, _w = self.run_brain(10.0)
        self.assertEqual(msgs, ["588: 31 on site right now."])
        self.assertEqual(row["timing"]["budget"], "ok")
        self.assertEqual(alerts, [])

    def test_an_answer_at_60_s_comes_after_one_notice(self):
        msgs, row, alerts, _llm, wire = self.run_brain(60.0)
        self.assertEqual(msgs, [NOTICE, "588: 31 on site right now."])
        self.assertEqual(row["timing"]["budget"], "slow_notice")
        self.assertEqual(row["answer"], "588: 31 on site right now.")
        self.assertEqual(alerts, [])
        # typing again right after the notice, stopped only before the answer
        acts = [a for a, _ in wire.actions]
        notice_at = [i for i, (a, p) in enumerate(wire.actions)
                     if a == "send-message" and p["message"] == NOTICE][0]
        self.assertEqual(acts[notice_at + 1], "send-typing")
        self.assertLess(notice_at, acts.index("send-stop-typing"))

    def test_never_finishing_gives_up_once_with_the_timeline(self):
        msgs, row, alerts, _llm, _w = self.run_brain(None)
        self.assertEqual(msgs, [NOTICE, GAVE_UP])
        self.assertEqual(row["timing"]["budget"], "gave_up")
        self.assertEqual(row["stop"], "gave_up")
        self.assertEqual(row["answer"], GAVE_UP)
        self.assertEqual(len(alerts), 1)
        (a,) = alerts
        self.assertEqual(a["trigger"], "dm_turn_gave_up")
        # the timeline: what ran before it was cancelled, and when
        t = a["metadata"]["timing"]
        for k in ("received_at", "queue_ms", "rounds", "sends", "first_send_ms"):
            self.assertTrue(k in t, k)
        self.assertEqual(t["budget"], "gave_up")
        self.assertEqual([r["round"] for r in t["rounds"]], [1])
        self.assertEqual([x["tool"] for x in a["metadata"]["tools"]], ["headcount"])
        self.assertEqual([x["action"] for x in t["sends"]], ["send-message", "send-message"])
        self.assertTrue("Model round 1:" in a["text"])
        self.assertTrue("Tool headcount (round 1)" in a["text"])
        self.assertTrue("First send:" in a["text"])
        # the chat by its last 4 only; nobody's words
        digits = server.wa_dm.phone_digits(CHAT)
        self.assertFalse(digits in a["text"] + str(a["metadata"]))
        self.assertTrue(f"dm…{digits[-4:]}" in a["text"])
        self.assertFalse("how many at 588" in a["text"] + str(a["metadata"]))

    def test_the_race_is_won_by_the_answer(self):
        msgs, row, alerts, _llm, _w = self.run_brain(120.0)
        self.assertEqual(msgs, [NOTICE, "588: 31 on site right now."])
        self.assertEqual(row["timing"]["budget"], "slow_notice")
        self.assertEqual(alerts, [])

    def test_something_already_sent_means_no_notice(self):
        """A tool's own send before 45 s is "something sent": no notice."""
        clock = _Clock(None)
        sends = [{"at": 0.0, "action": "send-message", "ok": True}]

        async def never():
            await clock.hold()
        msgs = []

        async def send(chat, message, *a, **k):
            msgs.append(message)

        async def typing(*a, **k):
            return True
        with patch.object(server, "_dm_budget_clock", clock.now), \
                patch.object(server, "_dm_budget_wait", clock.wait), \
                patch.object(server, "send_whatsapp_message", send), \
                patch.object(server, "_wa_typing", typing):
            async def go():
                return await server._dm_await_budget(asyncio.ensure_future(never()), "c", 0.0, sends)
            self.assertEqual(_run(go()), ("gave_up", None))
        self.assertEqual(msgs, [])

    def test_the_model_call_timeout_is_within_the_budget(self):
        _msgs, _row, _a, llm, _w = self.run_brain(10.0)
        for kw in llm.kwargs:
            self.assertTrue(0 < kw["timeout"] <= server.DM_MODEL_CALL_SECONDS, kw["timeout"])
        with patch.object(server, "DM_GIVE_UP_SECONDS", 5.0):
            clock = _Clock(1.0)
            llm = _HeldLLM(clock, resp(text("Nothing open at 588.")))
            with patch.object(server, "_dm_budget_clock", clock.now), \
                    patch.object(server, "_dm_budget_wait", clock.wait):
                self.ask("what's open at 588", llm, typing_every=1000)
        self.assertTrue(0 < llm.kwargs[0]["timeout"] <= 5.0, llm.kwargs[0]["timeout"])


class TheModelCallInsideTheDeadline(unittest.TestCase):

    def test_past_the_deadline_no_call_is_made(self):
        llm = FakeLLM(resp(text("x")))
        token = server._DM_DEADLINE.set(server._time.monotonic() - 1)
        try:
            with self.assertRaises(server._DmBudgetSpent):
                _run(server._dm_brain_create(llm, model="m", messages=[]))
        finally:
            server._DM_DEADLINE.reset(token)
        self.assertEqual(llm.calls, [])

    def test_no_retry_past_the_deadline(self):
        import httpx
        import openai
        calls = []

        class Down:
            def __init__(self):
                self.chat = self
                self.completions = self

            async def create(self, **kw):
                calls.append(kw["timeout"])
                raise openai.APIConnectionError(request=httpx.Request("POST", "http://x"))
        token = server._DM_DEADLINE.set(server._time.monotonic() + 1.2)
        try:
            with self.assertRaises(openai.APIConnectionError):
                _run(server._dm_brain_create(Down(), model="m", messages=[]))
        finally:
            server._DM_DEADLINE.reset(token)
        self.assertEqual(len(calls), 1)                  # 1.2 s left: no room for a retry
        self.assertTrue(calls[0] <= 1.2)

    def test_the_client_retries_are_off_inside_a_turn(self):
        seen = []

        class Sdk(FakeLLM):
            def with_options(self, **kw):
                seen.append(kw)
                return self
        llm = Sdk(resp(text("x")))
        token = server._DM_DEADLINE.set(server._time.monotonic() + 100)
        try:
            _run(server._dm_brain_create(llm, model="m", messages=[]))
        finally:
            server._DM_DEADLINE.reset(token)
        self.assertEqual(seen, [{"max_retries": 0}])

    def test_the_old_paths_http_timeout_is_capped(self):
        self.assertEqual(server._dm_call_timeout(40.0), 40.0)          # outside a turn
        token = server._DM_DEADLINE.set(server._time.monotonic() + 10)
        try:
            self.assertTrue(server._dm_call_timeout(40.0) <= 10)
        finally:
            server._DM_DEADLINE.reset(token)


class TheOldPath(unittest.TestCase):

    def answer(self, finish_at):
        clock = _Clock(finish_at)
        msgs, alerts, rows = [], [], []

        async def answer():
            await clock.hold()
            return "6 workers on site at 588."

        async def send(chat, message, *a, **k):
            msgs.append(message)
            sends = server._DM_SENDS.get()
            if sends is not None:
                sends.append({"at": server._time.monotonic(), "action": "send-message", "ok": True})

        async def log(*a, **k):
            rows.append((a, k))
        ps = _patched(clock, alerts)
        with _Ctx() as _c, patch.object(server, "send_whatsapp_message", send), \
                patch.object(server, "_dm_log_answer", log):
            for p in ps:
                p.start()
            try:
                async def go():
                    await server._dm_send_answer(
                        "15550001234@c.us", "M1", answer(),
                        log=({"company_id": "co1"}, "p1", "how many at 588", "job_agent",
                             [{"tool": "headcount", "args": {"job": "588"}, "round": 1,
                               "t_ms": 900, "ms": 300}]),
                        styled=True)
                _run(go())
            finally:
                for p in reversed(ps):
                    p.stop()
        return msgs, alerts, rows

    def test_10_s(self):
        msgs, alerts, rows = self.answer(10.0)
        self.assertEqual(msgs, ["6 workers on site at 588."])
        self.assertEqual(rows[-1][1]["timing"]["budget"], "ok")
        self.assertEqual(alerts, [])

    def test_60_s(self):
        msgs, alerts, rows = self.answer(60.0)
        self.assertEqual(msgs, [NOTICE, "6 workers on site at 588."])
        self.assertEqual(rows[-1][1]["timing"]["budget"], "slow_notice")
        self.assertEqual(alerts, [])

    def test_never(self):
        msgs, alerts, rows = self.answer(None)
        self.assertEqual(msgs, [NOTICE, GAVE_UP])
        (a, k), = rows
        self.assertEqual((a[3], a[4], k["timing"]["budget"]), (GAVE_UP, "job_agent", "gave_up"))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["metadata"]["path"], "job_agent")
        self.assertEqual(alerts[0]["metadata"]["chat"], "dm…1234")
        self.assertTrue("Tool headcount (round 1)" in alerts[0]["text"])
        self.assertFalse("15550001234" in alerts[0]["text"] + str(alerts[0]["metadata"]))
        self.assertFalse("how many at 588" in alerts[0]["text"] + str(alerts[0]["metadata"]))
        self.assertEqual(alerts[0]["metadata"]["tools"],
                         [{"tool": "headcount", "round": 1, "t_ms": 900, "ms": 300}])

    def test_race(self):
        msgs, alerts, rows = self.answer(120.0)
        self.assertEqual(msgs, [NOTICE, "6 workers on site at 588."])
        self.assertEqual(alerts, [])


class TheAlertGoesThroughTheModelDownPath(unittest.TestCase):
    """_dm_turn_gave_up uses the same sender as #877's _agent_model_down."""

    def test_one_email_per_operator_keyed_by_the_message(self):
        sent = []

        async def notify(db, **kw):
            sent.append(kw)

        async def ops():
            return ["ops@example.com"]
        timing = {"received_at": None, "queue_ms": 5, "rounds": [], "sends": [],
                  "first_send_ms": None, "budget": "gave_up"}
        with patch("lib.notifications.send_notification", notify), \
                patch.object(server, "_waapi_monitor_recipients", ops):
            _run(server._dm_turn_gave_up({"company_id": "co1"}, "15550001234@c.us",
                                         "brain", timing, [], "M9"))
        (kw,) = sent
        self.assertEqual((kw["permit_renewal_id"], kw["trigger_type"], kw["recipient"]),
                         ("dm_turn_gave_up:M9", "dm_turn_gave_up", "ops@example.com"))
        self.assertTrue("Budget: gave_up" in kw["text"])


if __name__ == "__main__":
    unittest.main()
