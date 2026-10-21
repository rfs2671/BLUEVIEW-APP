"""The OLD DM pipeline never says "check with X", and the logs say which
path answered.

Oct 21, live: an admin asked "How many framers in 588" and "Arkon have
workers in 588?" and got "check with ..." -- they ARE the person to check
with. The brain already asks its model again (dm_brain.deflect_note); the
old pipeline (no key, or dm_brain_off) now drops the sentences that send
them elsewhere (dm_brain.no_referral) and, with nothing left, says
"I couldn't find that in Levelog for <job>." -- never a made-up answer.

Evidence lines (no phone, no message text):
  [dm-brain] answered company=... tools=... rounds=... ms=... stop=...
  [dm-old] reason=no_key|flag_off company=...
  [dm-old] deflection removed company=... path=...
  [dm-brain] startup key=set|missing model=...
"""

from __future__ import annotations

import re
import unittest
from unittest.mock import patch

import server  # noqa: E402
from lib import dm_brain  # noqa: E402
from tests.test_dm_brain import FakeLLM, _Brain, resp, text  # noqa: E402
from tests.test_dm_short_answers import _Site  # noqa: E402
from tests.test_whatsapp_dm_assistant import _db, _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, _Ctx  # noqa: E402

REFER = re.compile(r"(?i)\bcheck\s+with\b|\bask\s+(?:your|the)\s+(?:site\s+manager|super|foreman|pm)\b")


class StripReferrals(unittest.TestCase):
    """lib/dm_brain.strip_referrals / no_referral: pure."""

    def test_no_referral_unchanged(self):
        t = "588: 31 on site.\nWant the names?"
        self.assertEqual(dm_brain.strip_referrals(t), t)
        self.assertEqual(dm_brain.no_referral(t, "588"), (t, False))

    def test_only_the_referring_sentence_goes(self):
        t = "Arkon has 17 on site at 588. Check with the site manager about framers."
        self.assertEqual(dm_brain.strip_referrals(t), "Arkon has 17 on site at 588.")
        self.assertEqual(dm_brain.no_referral(t, "588"), ("Arkon has 17 on site at 588.", True))

    def test_a_referring_line_goes_others_stay(self):
        t = "Open items at 588:\n- P-588-1 fire stop\n- Ask your foreman for the rest.\nDOB: clear."
        self.assertEqual(dm_brain.strip_referrals(t),
                         "Open items at 588:\n- P-588-1 fire stop\nDOB: clear.")

    def test_a_bullet_keeps_its_bullet(self):
        t = "- 4 on site. Confirm with the PM before Friday."
        self.assertEqual(dm_brain.strip_referrals(t), "- 4 on site.")

    def test_nothing_left_is_the_fixed_line(self):
        t = "Check with the site manager about framers."
        self.assertEqual(dm_brain.strip_referrals(t), "")
        self.assertEqual(dm_brain.no_referral(t, "588 Thomas S Boyland St"),
                         ("I couldn't find that in Levelog for 588 Thomas S Boyland St.", True))
        self.assertEqual(dm_brain.no_referral(t), ("I couldn't find that in Levelog.", True))
        self.assertEqual(dm_brain.no_referral(t, "  "), ("I couldn't find that in Levelog.", True))

    def test_never_invents(self):
        """What is kept is the model's own words, nothing added."""
        t = "I don't have framer counts. You could text the GC about it."
        out, removed = dm_brain.no_referral(t, "588")
        self.assertTrue(removed)
        self.assertEqual(out, "I don't have framer counts.")
        self.assertFalse(dm_brain.refers_elsewhere(out))

    def test_an_answer_from_the_records_is_kept(self):
        """Codex on #840: "confirm with the Levelog records" answers; nobody
        is sent anywhere, so nothing is removed."""
        for t in ("I can confirm with the Levelog records that 4 workers are on site.",
                  "Verified with the daily log: 12 on site at 588.",
                  "We checked with the sign-ins: Arkon had 6 today."):
            with self.subTest(t=t):
                self.assertEqual(dm_brain.no_referral(t, "588"), (t, False))
        mixed = "I can confirm with the records that 4 are on site. Check with the super for framers."
        self.assertEqual(dm_brain.no_referral(mixed, "588"),
                         ("I can confirm with the records that 4 are on site.", True))

    def test_empty(self):
        self.assertEqual(dm_brain.no_referral(None), ("", False))
        self.assertEqual(dm_brain.strip_referrals(""), "")


class TheOldPathNeverDeflects(_Site, unittest.TestCase):
    """Brain off (no key): the job agent's "Check with the site manager
    about framers." never goes out."""

    def ask_agent(self, reply_text, question="any violations at 588?"):
        async def agent(**kw):
            kw["tool_trace"].append({"tool": "open_items", "result": "none"})
            return reply_text
        with _Ctx(db=self.db) as c, patch.object(server, "DM_BRAIN_API_KEY", ""), \
                patch.object(server, "_run_group_agent", agent), \
                self.assertLogs(server.logger, "INFO") as logs:
            out = self._say(c, question, None, False, None, None)
        return out, "\n".join(logs.output)

    def test_a_pure_deflection_is_the_fixed_line(self):
        out, logs = self.ask_agent("Check with the site manager about framers.")
        self.assertIsNotNone(out)
        self.assertIsNone(REFER.search(out), out)
        self.assertRegex(out, r"^I couldn't find that in Levelog for 588\b")
        self.assertRegex(logs, r"\[dm-old\] reason=no_key company=" + re.escape(CO_A))
        self.assertRegex(logs, r"\[dm-old\] deflection removed company=" + re.escape(CO_A)
                         + r" path=job_agent fallback=yes")
        # No phone and no message text in the evidence lines.
        for line in logs.splitlines():
            if "[dm-old]" in line:
                self.assertIsNone(re.search(r"\d{7,}|" + re.escape(ADMIN_PHONE[-4:]) + r"\b", line), line)
                self.assertIsNone(re.search(r"(?i)framers|violations", line), line)
        log = self.db[server.DM_ANSWERS].rows[-1]
        self.assertIsNone(REFER.search(str(log.get("answer") or log.get("reply") or "")))

    def test_a_partial_deflection_keeps_the_answer(self):
        out, logs = self.ask_agent("No open violations at 588. Check with the site manager about framers.")
        self.assertIsNone(REFER.search(out), out)
        self.assertRegex(out, r"No open violations at 588\.")
        self.assertRegex(logs, r"\[dm-old\] deflection removed .* fallback=no")

    def test_a_clean_answer_logs_no_removal(self):
        out, logs = self.ask_agent("No open violations at 588.")
        self.assertRegex(out, r"No open violations at 588\.")
        self.assertIsNone(re.search(r"\[dm-old\] deflection removed", logs))


class TheRouteReason(unittest.TestCase):
    def test_reasons(self):
        from lib import feature_flags
        mine = {"company_id": CO_A, "user_id": "u_admin"}
        db = _db()
        with _Ctx(db=db), patch.object(server, "DM_BRAIN_API_KEY", ""):
            self.assertEqual(_run(server._dm_brain_route(mine)), (False, "no_key"))
            with self.assertLogs(server.logger, "INFO") as logs:
                self.assertFalse(_run(server._dm_brain_on(mine)))
            self.assertEqual([r.getMessage() for r in logs.records],
                             [f"[dm-old] reason=no_key company={CO_A}"])
        self.assertEqual(_run(server._dm_brain_route(None)), (False, "no_ident"))
        with _Ctx(db=db), patch.object(server, "DM_BRAIN_API_KEY", "k"):
            feature_flags.cache_invalidate()
            self.assertEqual(_run(server._dm_brain_route(mine)), (True, "on"))
            db.feature_flags.rows.append({"_id": "f1", "flag": dm_brain.OFF_FLAG, "enabled_globally": False,
                                          "enabled_for_companies": [CO_A], "enabled_for_users": [],
                                          "enabled_percentage": 0})
            feature_flags.cache_invalidate()
            with self.assertLogs(server.logger, "INFO") as logs:
                self.assertFalse(_run(server._dm_brain_on(mine)))
            self.assertEqual([r.getMessage() for r in logs.records],
                             [f"[dm-old] reason=flag_off company={CO_A}"])
        feature_flags.cache_invalidate()

    def test_brain_on_logs_no_old_line(self):
        from lib import feature_flags
        with _Ctx(db=_db()), patch.object(server, "DM_BRAIN_API_KEY", "k"), \
                patch.object(server.logger, "info") as info:
            feature_flags.cache_invalidate()
            self.assertTrue(_run(server._dm_brain_on({"company_id": CO_A, "user_id": "u_admin"})))
        self.assertEqual([c for c in info.call_args_list if "[dm-old]" in str(c)], [])
        feature_flags.cache_invalidate()


class TheStartupLine(unittest.TestCase):
    def test_key_set_never_printed(self):
        with patch.object(server, "DM_BRAIN_API_KEY", "sk-secret-123"):
            line = server._dm_brain_startup_line()
        self.assertEqual(line, f"[dm-brain] startup key=set model={dm_brain.MODEL}")
        self.assertIsNone(re.search(r"sk-secret-123", line))

    def test_key_missing(self):
        with patch.object(server, "DM_BRAIN_API_KEY", ""):
            self.assertEqual(server._dm_brain_startup_line(),
                             f"[dm-brain] startup key=missing model={dm_brain.MODEL}")

    def test_logged_at_startup(self):
        src = server.startup_event.__code__.co_names
        self.assertIn("_dm_brain_startup_line", src)


class TheBrainAnsweredLine(_Brain):
    def test_one_line_per_brain_answer(self):
        llm = FakeLLM(resp(text("Nothing open there right now.")))
        with _Ctx(db=self.db) as c, self.assertLogs(server.logger, "INFO") as logs:
            sends = self.say(c, "how many on site at 588", llm)
        self.assertEqual(sends, ["Nothing open there right now."])
        lines = [r.getMessage() for r in logs.records if r.getMessage().startswith("[dm-brain] answered")]
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0], r"^\[dm-brain\] answered company=" + re.escape(CO_A)
                         + r" tools=0 rounds=1 ms=\d+ stop=stop$")
        self.assertIsNone(re.search(r"\d{7,}", lines[0]))
        self.assertEqual([r for r in logs.records if r.getMessage().startswith("[dm-old]")], [])


if __name__ == "__main__":
    unittest.main()
