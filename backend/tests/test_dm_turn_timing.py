"""A DM answer is timed, and a slow one shows "typing…", never 👀.

Oct 27, 2026, 588 Thomas S Boyland: the owner asked about spray foam on the
5th floor ceiling at 10:36 and got the answer at 10:43, after he sent "?".
Nothing recorded where the seven minutes went: the answer log had the tools
and the model's token count, no clock. Now each DM answer row carries
`timing` -- received_at, queue_ms, wa_lag_ms, every model round and every
send as an offset from the webhook's receipt, and first_send_ms -- and each
tool call in tool_data carries round / t_ms / ms (scripts/dm_thread_timeline.py
prints it).

And the 👀 that went on a question taking over 5 s is gone: on a 7-minute
answer it read as "seen, and not answering". The only signal is WhatsApp's
"typing…" (send-typing, refreshed, then send-stop-typing).
"""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import patch

import server  # noqa: E402
from lib import wa_react  # noqa: E402
from tests.test_dm_brain import FakeLLM, _Brain, resp, text, use  # noqa: E402
from tests.test_dm_short_answers import CHAT, _payload  # noqa: E402
from tests.test_whatsapp_dm_assistant import _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import _Ctx, _Wire  # noqa: E402


class _ActionWire(_Wire):
    """The WaAPI posts with the action each one went to."""

    def __init__(self):
        super().__init__()
        self.actions = []

    async def post_raw(self, url, payload, headers):
        self.actions.append((url.rsplit("/", 1)[-1], dict(payload)))
        return await super().post_raw(url, payload, headers)


class _Slow(FakeLLM):
    """Each model call takes `delay` seconds."""

    def __init__(self, *script, delay=0.0):
        super().__init__(*script)
        self.delay = delay

    async def create(self, **kw):
        await asyncio.sleep(self.delay)
        return await super().create(**kw)


class _Timed(_Brain):

    def ask(self, body, llm, *, received_at=None, typing_every=0.02):
        """One DM through the webhook's task, with the real reaction and
        typing calls going to the wire (nothing patched between)."""
        self.n += 1
        wire = _ActionWire()

        async def on(ident):
            return True
        with _Ctx(db=self.db, wire=wire), \
                patch.object(server, "_dm_brain_on", on), \
                patch.object(server, "_dm_brain_client", lambda: llm), \
                patch.object(server, "DM_TYPING_EVERY_SECONDS", typing_every), \
                patch.object(server, "LLM_API_KEY", None):
            _run(server._process_whatsapp_message(_payload(CHAT, body, f"t{self.n}"),
                                                  received_at=received_at))
        return wire

    def row(self):
        rows = [r for r in self.db[server.DM_ANSWERS].rows if r.get("path") == "brain"]
        return rows[-1]


class NoEyesOnASlowAnswer(_Timed):

    def test_the_working_reaction_is_gone_from_the_map(self):
        self.assertEqual(sorted(wa_react.REACTIONS), ["complete", "done", "praise", "saved", "thanks"])
        self.assertFalse(hasattr(wa_react, "WORKING_AFTER_SECONDS"))

    def test_a_slow_dm_answer_sends_typing_and_never_a_reaction(self):
        llm = _Slow(resp(use("headcount", {"job": "588"})),
                    resp(text("588: 31 on site right now.")), delay=0.15)
        wire = self.ask("how many at 588", llm)
        acts = [a for a, _ in wire.actions]
        self.assertEqual([p for a, p in wire.actions if a == "react-to-message"], [])
        self.assertEqual([p.get("reaction") for _, p in wire.actions if "reaction" in p], [])
        self.assertGreaterEqual(acts.count("send-typing"), 2)          # refreshed while it worked
        self.assertEqual(acts[0], "send-seen")
        # typing stops before the answer goes
        self.assertLess(acts.index("send-stop-typing"), acts.index("send-message"))
        self.assertEqual([p["message"] for a, p in wire.actions if a == "send-message"],
                         ["588: 31 on site right now."])


class TheAnswerLogHasAClock(_Timed):

    def test_rounds_tools_and_first_send_are_timed_from_receipt(self):
        llm = _Slow(resp(use("headcount", {"job": "588"})),
                    resp(text("588: 31 on site right now.")), delay=0.05)
        received = time.time() - 2.0                 # the task began 2 s after the webhook
        self.ask("how many at 588", llm, received_at=received)
        row = self.row()
        t = row["timing"]
        self.assertAlmostEqual(t["received_at"].timestamp(), received, delta=0.01)
        self.assertGreaterEqual(t["queue_ms"], 1900)
        self.assertGreaterEqual(t["brain_start_ms"], t["queue_ms"])
        self.assertEqual([r["round"] for r in t["rounds"]], [1, 2])
        self.assertEqual([r["finish"] for r in t["rounds"]], ["tool_calls", "stop"])
        self.assertEqual([r["tools"] for r in t["rounds"]], [1, 0])
        for r in t["rounds"]:
            self.assertGreaterEqual(r["ms"], 40)
            self.assertGreaterEqual(r["t_ms"], t["brain_start_ms"])
        self.assertLess(t["rounds"][0]["t_ms"], t["rounds"][1]["t_ms"])
        (tool,) = row["tool_data"]
        self.assertEqual((tool["tool"], tool["round"]), ("headcount", 1))
        self.assertGreaterEqual(tool["t_ms"], t["rounds"][0]["t_ms"] + t["rounds"][0]["ms"])
        self.assertIn("ms", tool)
        # the answer's own send, after the last round
        (send,) = [s for s in t["sends"] if s["action"] == "send-message"]
        self.assertTrue(send["ok"])
        self.assertEqual(t["first_send_ms"], send["t_ms"])
        self.assertGreaterEqual(t["first_send_ms"], t["rounds"][1]["t_ms"] + t["rounds"][1]["ms"])
        self.assertIn("wait_ms", send)

    def test_no_phone_in_the_timing(self):
        llm = FakeLLM(resp(text("Nothing open at 588.")))
        self.ask("what's open at 588", llm)
        digits = server.wa_dm.phone_digits(CHAT)
        self.assertEqual([k for k in self.row()["timing"] if digits in str(self.row()["timing"][k])],
                         [])

    def test_a_model_failure_keeps_what_ran_and_how_long(self):
        class Boom(Exception):
            pass

        def fail(kw):
            raise Boom()
        llm = FakeLLM(resp(use("headcount", {"job": "588"})), fail)
        self.ask("how many at 588", llm)
        row = self.row()
        self.assertEqual(row["stop"], "error:Boom")
        self.assertEqual([t["tool"] for t in row["tool_data"]], ["headcount"])
        self.assertEqual([r.get("error") for r in row["timing"]["rounds"]], [None, "Boom"])

    def test_a_retry_says_why_on_its_round(self):
        llm = FakeLLM(resp(use("headcount", {"job": "588"})),
                      resp(text("588: 45 on site right now.")),            # 45 is nowhere
                      resp(text("588: 31 on site right now.")))
        self.ask("how many at 588", llm)
        self.assertEqual([r.get("then") for r in self.row()["timing"]["rounds"]],
                         [None, "verify", None])

    def test_a_refused_reply_is_in_the_sends(self):
        """No window and no opt-in: the reply is refused, and the row says so
        (first_send_ms None) instead of looking like it went."""
        async def refuse(chat_id, message, dm_meta):
            return {"allowed": False, "reason": "no_active_optin"}
        llm = FakeLLM(resp(text("Nothing open at 588.")))
        with patch.object(server, "_dm_send_verdict", refuse):
            self.ask("what's open at 588", llm)
        t = self.row()["timing"]
        self.assertEqual([(s["action"], s["ok"], s.get("refused")) for s in t["sends"]],
                         [("send-message", False, "no_active_optin")])
        self.assertIsNone(t["first_send_ms"])


if __name__ == "__main__":
    unittest.main()
