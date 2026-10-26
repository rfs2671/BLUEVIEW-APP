"""dm_eval, Oct 20: 3 of 32 answers were check_failed -- the model's
headcount wording was thrown away and the fixed text went out. The drafts
were never stored, so nobody could see which check threw them away.

Now:
  * the rejected draft and WHY (wa_headcount.check: word, number,
    company_count, on_site_count, since_count, too_long) are logged on the
    answer row, and dm_eval shows them (scrubbed, names masked);
  * the subs answer, fixed by design (#807), is not a fallback
    (it was counted as no_model_wording);
  * plain rewordings that are true are no longer thrown away: "so far",
    "need the names?", "Arkon's 12", a time written "09:01".
  * a wrong fact is still thrown away, in every one of those shapes.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import server  # noqa: E402
from lib import dm_eval, wa_headcount  # noqa: E402
from scripts import dm_eval as script  # noqa: E402
from tests.test_dm_eval import FAKE_DIGITS  # noqa: E402
from tests.test_dm_short_answers import CHAT, _Site, _payload  # noqa: E402
from tests.test_dm_subs_on_site import ALL, _crew  # noqa: E402
from tests.test_whatsapp_dm_assistant import _db, _optin, _run  # noqa: E402
from tests.test_whatsapp_dm_picker_headcount import _et_today  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, _Ctx  # noqa: E402

JOB = "588 588 Thomas S Boyland St"


def _data():
    data = wa_headcount.summarize([], None)
    data.update(total=12, by_company=[("Arkon", 9), ("J&G", 3)], since=_et_today(9, 1),
                workers=[{"name": "Luis Ortega", "company": "Arkon", "at": _et_today(6, 30)}],
                added=[{"name": "Luis Ortega", "company": "Arkon", "at": _et_today(9, 5)}])
    return data


class TheCheck(unittest.TestCase):
    def test_true_rewordings_pass(self):
        """Each of these was thrown away before: "far", "need", "Arkon's",
        "09"."""
        for draft in ("12 on site at 588 so far.",
                      "12 on site at 588. Need the names?",
                      "12 on site at 588: Arkon's 9, J&G 3.",
                      "1 came in since 09:01.",
                      "1 arrived since 09:01."):
            self.assertIsNone(wa_headcount.check(draft, _data(), JOB), draft)
            self.assertTrue(wa_headcount.verify(draft, _data(), JOB), draft)

    def test_wrong_facts_are_still_thrown_away_with_the_reason(self):
        for draft, why in (("12 on site at 588 so far, Juan Lopez too.", "word"),
                           ("13 on site at 588 so far.", "number"),
                           ("12 on site: Arkon's 3, J&G 9.", "company_count"),
                           ("Need the names? 3 on site at 588.", "on_site_count"),
                           ("9 came in since 09:01.", "since_count"),
                           # Codex on #821: the arrival words are counts too.
                           ("9 arrived since 09:01.", "since_count"),
                           ("9 joined since 09:01.", "since_count"),
                           ("9 showed up since 09:01.", "since_count"),
                           ("12 on site at 588, 08:05 latest.", "number")):
            self.assertEqual(wa_headcount.check(draft, _data(), JOB), why, draft)
            self.assertFalse(wa_headcount.verify(draft, _data(), JOB), draft)


class TheLog(_Site, unittest.TestCase):
    """The 588 crew of Mon 9:01 AM (31 on site); the model's rewording is
    `draft`."""

    def setUp(self):
        self.agent_calls, self.llm_calls, self.reactions = [], [], []
        self.db = _db()
        _optin(self.db, "u_admin", ADMIN_PHONE)
        _crew(self.db)
        self.n = 0

    def _ask(self, question, draft):
        async def dm_llm(system, user_text):
            self.llm_calls.append((system, user_text))
            return draft if system == wa_headcount.PHRASE_PROMPT else "general"

        async def react(*a, **k):
            return True

        async def scope(body):
            return "project"
        with _Ctx(db=self.db) as c, patch.object(server, "_dm_llm", dm_llm), \
                patch.object(server, "_react_to_message", react), \
                patch.object(server, "_dm_scope", scope), \
                patch.object(server, "LLM_API_KEY", "k"):
            _run(server._process_whatsapp_message(_payload(CHAT, question, "m1")))
            sends = [p["message"] for p in c.wire.calls if "message" in p]
        return sends[-1], self.db[server.DM_ANSWERS].rows[-1]

    def test_a_thrown_away_draft_is_logged_with_why(self):
        reply, row = self._ask("How many workers on site at 588?",
                               "31 on site at 588 now — Arkon Builders 6.")
        self.assertTrue(reply.startswith("31 on site at 588 now.\nArkon Builders 17"), reply)
        self.assertEqual((row["fallback"], row["reason"], row["wording"]),
                         (True, "check_failed", "fixed_after_check_failed"))
        self.assertEqual(row["rejected"], "31 on site at 588 now — Arkon Builders 6.")
        self.assertEqual(row["check"], "company_count")

    def test_a_too_long_draft_says_so(self):
        _reply, row = self._ask("How many workers on site at 588?",
                                "31 on site at 588 now. " * 40)
        self.assertEqual((row["reason"], row["check"]), ("check_failed", "too_long"))

    def test_a_true_plain_draft_goes_out(self):
        draft = "31 on site at 588 so far. Need the names?"
        reply, row = self._ask("How many workers on site at 588?", draft)
        self.assertEqual(reply, draft)
        self.assertEqual((row["fallback"], row["reason"]), (False, "phrased"))
        self.assertNotIn("rejected", row)

    def test_the_subs_answer_is_not_a_fallback(self):
        reply, row = self._ask("How many subs on site at 588?", "anything")
        self.assertEqual(reply, ALL)
        self.assertEqual((row["fallback"], row["reason"], row["wording"]),
                         (False, "fixed_by_design", "fixed_by_design"))


class TheEval(unittest.TestCase):
    ROW = {"user_id": "u1", "path": "headcount", "fallback": True, "reason": "check_failed",
           "question": "how many on site", "answer": "31 on site at 588 now.",
           "rejected": f"31 on site, Arkon Worker 3 at {FAKE_DIGITS}", "check": "word",
           "tool_data": {"workers": [{"name": "Arkon Worker 3", "company": "Arkon Builders"}]},
           "created_at": "2026-10-20T13:01:00+00:00"}

    def test_the_report_shows_the_draft_and_why(self):
        rows = script.anonymise([self.ROW])
        self.assertNotIn("Arkon Worker 3", rows[0]["rejected"])
        self.assertEqual(rows[0]["check"], "word")
        report = dm_eval.score(rows)
        [x] = report["check_failed_examples"]
        self.assertEqual((x["question"], x["check"]), ("how many on site", "word"))
        self.assertNotIn(FAKE_DIGITS, x["rejected"])
        text = dm_eval.render(report)
        self.assertIn("CHECK FAILED", text)
        self.assertIn("rejected: 31 on site", text)

    def test_an_old_row_says_not_logged(self):
        old = {k: v for k, v in self.ROW.items() if k not in ("rejected", "check")}
        text = dm_eval.render(dm_eval.score(script.anonymise([old])))
        self.assertIn("(not logged before this change)", text)


if __name__ == "__main__":
    unittest.main()
