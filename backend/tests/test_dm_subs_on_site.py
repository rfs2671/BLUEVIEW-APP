"""Mon 9:01 AM, 588: the companies on site (lib/wa_headcount.SUBS).

  "Update on workers 588"   -> 31 on site ... Arkon Builders 17, Quality
                               Plumbing 6, J&G 4 (+1 more sub).
  "No / What's the +1 sub?" -> "I don't have that in the records."
  "How many subs on site?"  -> the worker headcount again
  "How many companies on site" -> the worker headcount again

A question about the companies is answered with every company on site and
its count, from the check-ins; "the +1 sub" names the ones left out first.
"""

from __future__ import annotations

import re
import unittest
from datetime import timedelta

import server  # noqa: E402
from lib import wa_headcount  # noqa: E402
from tests.test_dm_short_answers import _Site  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, _db, _optin  # noqa: E402
from tests.test_whatsapp_dm_picker_headcount import _et_today  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A  # noqa: E402

# 588 at 9:01: 31 on site, 13 of them after the 8:01 brief.
CREW = [("Arkon Builders", 17), ("Quality Plumbing", 6), ("J&G", 4), ("Power Direct", 4)]
LATE = {"Arkon Builders": 8, "J&G": 4, "Power Direct": 1}
ALL = "4 subs on site at 588 now: Arkon Builders 17, Quality Plumbing 6, J&G 4, Power Direct 4."


def _crew(db):
    n = 0
    for co, count in CREW:
        for i in range(count):
            n += 1
            at = _et_today(8, 30) if i < LATE.get(co, 0) else _et_today(6, 30) + timedelta(minutes=n)
            db.checkins.rows.append({
                "_id": f"c{n}", "project_id": THOMAS, "company_id": CO_A, "worker_id": f"w{n}",
                "worker_name": f"{co.split()[0]} Worker {i + 1}", "worker_company": co,
                "check_in_time": at, "status": "checked_in"})
    db[server.WA_LEDGER].rows.append({
        "_id": "brief1", "user_id": "u_admin", "kind": server.MORNING_BRIEF_KIND,
        "status": "sent", "created_at": _et_today(8, 1)})


class MondayAt588(_Site, unittest.TestCase):
    def setUp(self):
        self.agent_calls, self.llm_calls, self.reactions = [], [], []
        self.db = _db()
        _optin(self.db, "u_admin", ADMIN_PHONE)
        _crew(self.db)
        self.n = 0

    def test_the_conversation(self):
        from tests.test_whatsapp_phase1_foundations import _Ctx
        with _Ctx(db=self.db) as c:
            first = self.say(c, "Update on workers 588")
            plus = self.say(c, "No\nWhat's the +1 sub?")
            subs = self.say(c, "How many subs on site?")
            cos = self.say(c, "How many companies on site")
        self.assertTrue(first.startswith("31 on site at 588 now.\n"
                                         "Arkon Builders 17, Quality Plumbing 6, J&G 4 (+1 more sub)."),
                        first)
        self.assertEqual(plus, "The other sub: Power Direct 4.\n" + ALL)
        self.assertEqual(subs, ALL)
        self.assertEqual(cos, ALL)
        self.assertEqual(self.agent_calls, [])                 # never the job agent
        kinds = [r["tool_data"]["kind"] for r in self.db[server.DM_ANSWERS].rows
                 if r.get("path") == "headcount"]
        self.assertEqual(kinds, ["count", "subs", "subs", "subs"])

    def test_all_jobs_wins_over_the_job_counted_last(self):
        """Codex on #807: after a count at 588, "across all my jobs" is about
        every job, not 588."""
        from unittest.mock import patch
        from tests.test_whatsapp_phase1_foundations import _Ctx
        asked = []

        async def all_jobs(ident, body):
            asked.append(body)
            return "All jobs: 2 subs on site."
        with _Ctx(db=self.db) as c, patch.object(server, "_dm_answer_all", all_jobs):
            self.say(c, "Update on workers 588")
            reply = self.say(c, "how many subs are on site across all my jobs?")
        self.assertEqual(reply, "All jobs: 2 subs on site.")
        self.assertEqual(asked, ["how many subs are on site across all my jobs?"])

    def test_with_the_job_named(self):
        self.assertEqual(self.ask("which subs are on site at 588?"), ALL)
        self.assertEqual(self.ask("how many companies at 588 today"), ALL)

    def test_never_the_model_wording(self):
        """The fixed answer goes out: `verify` checks worker numbers, not a
        count of subs."""
        from tests.test_whatsapp_phase1_foundations import _Ctx
        with _Ctx(db=self.db) as c:
            reply = self.say(c, "how many subs on site at 588", key="k")
        self.assertEqual(reply, ALL)
        self.assertFalse(any(s == wa_headcount.PHRASE_PROMPT for s, _ in self.llm_calls))

    def test_a_recheck_recounts_the_subs(self):
        reply = self.ask("how many subs on site at 588 · are you sure?")
        self.assertEqual(reply, "Rechecked the check-ins.\n" + ALL)


class TheWords(unittest.TestCase):
    def test_subs_questions(self):
        for q in ["What's the +1 sub?", "whats the +2 more subs", "who are the other subs",
                  "How many subs on site?", "How many companies on site", "which subs are here",
                  "what trades are on site today", "how many subcontractors on site at 588",
                  "the rest of the subs?"]:
            self.assertEqual(wa_headcount.intent(q), wa_headcount.SUBS, q)

    def test_not_subs_questions(self):
        for q, kind in [("how many workers on site", wa_headcount.COUNT),
                        ("Update on workers 588", wa_headcount.COUNT),
                        ("how many arkon guys on site", wa_headcount.COUNT),
                        ("who's on site", wa_headcount.LIST),
                        ("list our subs", None), ("do we have a plumber?", None),
                        ("how many subs on site last week", None)]:
            self.assertEqual(wa_headcount.intent(q), kind, q)

    def _data(self, by_co):
        return {"total": sum(n for _, n in by_co), "by_company": by_co, "workers": [],
                "added": [], "since": None}

    def test_compose(self):
        data = self._data([("Arkon", 9), ("Quality", 6), ("Power Direct", 3)])
        self.assertEqual(wa_headcount.compose_subs(data, "588"),
                         "3 subs on site at 588 now: Arkon 9, Quality 6, Power Direct 3.")
        # Nothing was left out: no "other sub" line.
        self.assertEqual(wa_headcount.compose_subs(data, "588", "what's the other sub"),
                         "3 subs on site at 588 now: Arkon 9, Quality 6, Power Direct 3.")
        one = self._data([("Arkon", 2), (wa_headcount.NO_COMPANY, 1)])
        self.assertEqual(wa_headcount.compose_subs(one, "588"),
                         "1 sub on site at 588 now: Arkon 2. Plus 1 with no company on record.")
        self.assertEqual(wa_headcount.compose_subs(self._data([]), "588"),
                         "Nobody has checked in at 588 today.")
        self.assertIsNone(re.search(r"\+\d", wa_headcount.compose_subs(data, "588")))


if __name__ == "__main__":
    unittest.main()
