"""DM answers are short (Thu 11:35 AM, 588): "How many arkon workers in 588"
got the whole site -- 37, every sub -- and 9 late arrivals by name.

1. A headcount question naming a sub (fuzzy: "arkon") answers for that sub
   only: "Arkon: 15 on site today at 588." -- also "who from Power Direct is
   here", "is J&G on site".
2. Every DM answer: the first line is the answer; at most 2 more short
   lines; names only when asked ("who", "list", "names"), else "Want the
   names?" (and "yes" sends them); the short job name ("588"); ~300
   characters unless a list or the detail was asked for.
3. The post-check (lib/wa_style.tighten) shortens what is still too long,
   keeping the answer line.

The replies to 20 real phrasings are a snapshot:
tests/fixtures/dm_short_answers.snap.txt (UPDATE_SNAPSHOTS=1 rewrites it).
"""

from __future__ import annotations

import os
import re
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import server  # noqa: E402
from lib import wa_style  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, _db, _optin, _run  # noqa: E402
from tests.test_whatsapp_dm_picker_headcount import CHAT, _Chat, _et_today, _payload  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CO_A, _Ctx  # noqa: E402

SNAPSHOT = Path(__file__).parent / "fixtures" / "dm_short_answers.snap.txt"

# 588 at 11:35: 37 on site; 9 of them came after the 8:07 brief.
CREW = [("Arkon", 15), ("Quality Plumbing", 8), ("Power Direct", 6), ("J&G Plumbing", 4),
        ("Spark Data & Security", 4)]
LATE = {"Arkon": 4, "Quality Plumbing": 2, "Power Direct": 2, "J&G Plumbing": 1}

# The phrasings, as people type them. Each in a fresh chat; "·" chains turns.
PHRASINGS = [
    "How many arkon workers in 588",                      # the live one
    "how many guys from arkon at 588 today",
    "arkon headcount at 588?",
    "how many Quality Plumbing workers at 588",
    "who from Power Direct is here at 588",
    "is J&G on site at 588",
    "is spark data at the site at 588?",
    "any power direct guys on site at 588",
    "is Quality Plumbing on site at 588 · names",
    "How many arkon workers in 588 · yes",
    "how many workers at 588",
    "Any updates on worker count at 588?",
    "manpower at 588 today?",
    "how many came in since the brief at 588",
    "who came in after the brief at 588",
    "who's on site at 588",
    "what's open at 588",                                  # the job agent (long reply)
    "what's open at 588 · yes",
    "list the open items at 588",                          # a list asked: never cut
    "any violations at 588?",                              # the agent, with a preamble
]

LONG_AGENT_REPLY = "\n".join(
    ["Sure! Here's what I found:",
     "12 open items at 588 THOMAS S BOYLAND STREET.",
     "Oldest is 9 days, the fire stop at the cellar."]
    + [f"• P-588-{i} Item {i} — Arkon, due Fri" for i in range(1, 13)])
SHORT_AGENT_REPLY = "Let me check the records...\nNo open violations at 588 Thomas S Boyland St."


def _crew(db):
    rows, n = [], 0
    for co, count in CREW:
        late = LATE.get(co, 0)
        for i in range(count):
            n += 1
            at = _et_today(10, n % 50) if i < late else _et_today(6, 30) + timedelta(minutes=n)
            rows.append({"_id": f"c{n}", "project_id": THOMAS, "company_id": CO_A,
                         "worker_id": f"w{n}", "worker_name": f"{co.split()[0]} Worker {i + 1}",
                         "worker_company": co, "worker_phone": f"17185559{n:03d}",
                         "check_in_time": at, "status": "checked_in"})
    db.checkins.rows.extend(rows)
    db[server.WA_LEDGER].rows.append({
        "_id": "brief1", "user_id": "u_admin", "kind": server.MORNING_BRIEF_KIND,
        "status": "sent", "created_at": _et_today(8, 7)})


class _Site(_Chat):
    def setUp(self):
        self.agent_calls, self.llm_calls, self.reactions = [], [], []
        self.db = _db()
        _optin(self.db, "u_admin", ADMIN_PHONE)
        _crew(self.db)
        self.n = 0

    def say(self, c, body, quoted=None, from_bot=False, llm=None, key=None):
        """One DM; the job agent answers as the live one did -- long, with a
        preamble and the address in capitals."""
        async def agent(**kw):
            self.agent_calls.append(kw)
            reply = SHORT_AGENT_REPLY if "violation" in kw["body"] else LONG_AGENT_REPLY
            kw["tool_trace"].append({"tool": "open_items", "result": reply})   # its records
            return reply
        with patch.object(server, "_run_group_agent", agent):
            return self._say(c, body, quoted, from_bot, llm, key)

    def _say(self, c, body, quoted, from_bot, llm, key):
        self.n += 1
        before = len([p for p in c.wire.calls if "message" in p])

        async def dm_llm(system, user_text):
            self.llm_calls.append((system, user_text))
            return "general"

        async def react(*a, **k):
            return True

        async def scope(body):
            return "project"
        with patch.object(server, "_dm_llm", dm_llm), \
                patch.object(server, "_react_to_message", react), \
                patch.object(server, "_dm_scope", scope), \
                patch.object(server, "LLM_API_KEY", key):
            _run(server._process_whatsapp_message(
                _payload(CHAT, body, f"m{self.n}", quoted, from_bot)))
        sends = [p["message"] for p in c.wire.calls if "message" in p]
        return sends[-1] if len(sends) > before else None

    def ask(self, phrasing):
        """The reply to the last turn of `phrasing` ("a · b": two turns)."""
        reply = None
        with _Ctx(db=self.db) as c:
            for turn in phrasing.split(" · "):
                reply = self.say(c, turn)
        return reply


class TheThursdayQuestion(_Site, unittest.TestCase):

    def test_arkon_only(self):
        reply = self.ask("How many arkon workers in 588")
        self.assertEqual(reply, "Arkon: 15 on site today at 588.\nWant the names?")
        self.assertIsNone(re.search(r"\b37\b|Quality|Power|Worker", reply), reply)
        log = self.db[server.DM_ANSWERS].rows[-1]
        self.assertEqual((log["path"], log["tool_data"]["company"], log["tool_data"]["total"]),
                         ("headcount", "Arkon", 15))

    def test_yes_sends_the_names(self):
        reply = self.ask("How many arkon workers in 588 · yes")
        self.assertTrue(reply.startswith("Arkon: 15 on site at 588 — Arkon Worker"), reply)
        self.assertEqual(reply.count("Arkon Worker"), 15)
        self.assertIsNone(re.search(r"Quality|Power", reply), reply)

    def test_who_from_a_sub_is_here(self):
        reply = self.ask("who from Power Direct is here at 588")
        self.assertTrue(reply.startswith("Power Direct: 6 on site at 588 — Power Worker"), reply)
        self.assertEqual(reply.count("Power Worker"), 6)
        self.assertIsNone(re.search(r"Arkon|Quality", reply), reply)

    def test_is_a_sub_on_site(self):
        self.assertEqual(self.ask("is J&G on site at 588"),
                         "Yes — J&G Plumbing: 4 on site at 588 now.\nWant the names?")

    def test_a_sub_with_nobody_in(self):
        self.db.projects.rows[0].setdefault("trade_assignments", []).append(
            {"id": "a9", "company": "Tri-State Steel", "trade": "steel"})
        with patch.object(server, "_active_assignments",
                          lambda p: [{"company": "Tri-State Steel"}]):
            reply = self.ask("is tri-state on site at 588")
        self.assertEqual(reply, "No — nobody from Tri-State Steel has checked in at 588 today.")


class ReviewFindings(_Site, unittest.TestCase):
    """Codex on #802."""

    def test_a_time_in_the_question_keeps_the_sub(self):
        reply = self.ask("how many Arkon workers came in since 9 at 588")
        self.assertTrue(reply.startswith("Arkon: 4 since 9:00, 15 on site at 588 now."), reply)
        self.assertIsNone(re.search(r"\b37\b|\b9 since", reply), reply)

    def test_who_came_in_names_the_arrivals_only(self):
        reply = self.ask("who from Arkon came in after the brief at 588")
        self.assertTrue(reply.startswith("Arkon: 4 since your 8:07 brief — "), reply)
        self.assertEqual(reply.count("Arkon Worker"), 4)          # the 4 late ones, not 15

    def test_a_recheck_keeps_the_sub(self):
        reply = self.ask("How many arkon workers in 588 · are you sure?")
        self.assertTrue(reply.startswith("Rechecked the check-ins.\nArkon: 15 on site today at 588."),
                        reply)
        self.assertIsNone(re.search(r"\b37\b", reply), reply)

    def test_an_exact_name_wins_over_a_similar_one(self):
        names = ["Power Direct", "Power Electrical"]
        self.assertEqual(wa_style.company_in("how many power direct guys", names), ["Power Direct"])
        self.assertEqual(wa_style.company_in("how many power electrical guys", names),
                         ["Power Electrical"])

    def test_a_short_list_unasked_is_cut_too(self):
        short = "2 open items at 588.\n• P-1 Outlet\n• P-2 Door"
        out, trimmed = wa_style.tighten(short, "anything open at 588?")
        self.assertEqual((out, trimmed), ("2 open items at 588.\n" + wa_style.OFFER_LIST, True))
        many = "\n".join(["One.", "Two.", "Three.", "Four.", "Five."])
        out, trimmed = wa_style.tighten(many, "status?")
        self.assertTrue(trimmed)
        self.assertLessEqual(len(out.splitlines()), wa_style.MAX_LINES + 1)
        self.assertEqual(wa_style.tighten("A.\nB.\nC.", "status?"), ("A.\nB.\nC.", False))


class EveryAnswer(_Site, unittest.TestCase):

    def test_the_snapshot(self):
        got = []
        for phrasing in PHRASINGS:
            self.setUp()
            got.append(f">>> {phrasing}\n{self.ask(phrasing)}\n")
        text = "\n".join(got)
        if os.environ.get("UPDATE_SNAPSHOTS") or not SNAPSHOT.exists():
            SNAPSHOT.write_text(text, encoding="utf-8")
        self.assertEqual(text, SNAPSHOT.read_text(encoding="utf-8"))

    def test_the_rules_hold_for_every_phrasing(self):
        self.assertGreaterEqual(len(PHRASINGS), 15)
        for phrasing in PHRASINGS:
            with self.subTest(phrasing):
                self.setUp()
                reply = self.ask(phrasing)
                last = phrasing.split(" · ")[-1]
                asked = wa_style.asks_for_list(last) or wa_style.wants_more(last)
                first = reply.splitlines()[0]
                self.assertIsNone(re.match(r"(?i)(sure|here'?s|let me|of course|ok)\b", first),
                                  first)
                self.assertIsNone(re.search(r"THOMAS S BOYLAND|Thomas S Boyland St", reply),
                                  reply)                              # "588", never the address
                if not asked:
                    self.assertLessEqual(len(reply), wa_style.MAX_CHARS, reply)
                    self.assertLessEqual(len(reply.splitlines()), wa_style.MAX_LINES + 1, reply)
                    self.assertIsNone(re.search(r"Worker \d", reply), reply)   # no names unasked

    def test_a_long_agent_answer_keeps_its_answer_line(self):
        reply = self.ask("what's open at 588")
        self.assertEqual(reply.splitlines()[0], "12 open items at 588.")
        self.assertTrue(reply.endswith(wa_style.OFFER_LIST), reply)
        self.assertNotIn("•", reply)
        full = self.ask("what's open at 588 · yes")
        self.assertIn("• P-588-12 Item 12", full)
        self.assertTrue(full.startswith("12 open items at 588."), full)       # no preamble

    def test_a_list_asked_for_is_never_cut(self):
        reply = self.ask("list the open items at 588")
        self.assertIn("• P-588-12 Item 12", reply)
        self.assertNotIn("Here's what I found", reply)


class TheRules(unittest.TestCase):
    LABELS = ["588 Thomas S Boyland St", "8 Walworth St"]

    def test_short_job_names(self):
        self.assertEqual([wa_style.short_job(x) for x in self.LABELS + ["120 Walworth St",
                                                                      "Menahan Building"]],
                         ["588", "8 Walworth", "120", "Menahan Building"])
        self.assertEqual(wa_style.shorten_jobs(
            "588 THOMAS S BOYLAND STREET punch list; 8 Walworth St, Brooklyn, NY too", self.LABELS),
            "588 punch list; 8 Walworth too")

    def test_subs_named(self):
        names = ["Arkon Builders", "Quality Plumbing", "Power Direct", "J&G Plumbing"]
        for q, want in (("How many arkon workers in 588", ["Arkon Builders"]),
                        ("is J&G on site", ["J&G Plumbing"]),
                        ("who from Power Direct is here", ["Power Direct"]),
                        ("how many arkn guys", ["Arkon Builders"]),           # a typo
                        ("how many workers on site", []),
                        ("any plumbers here", [])):
            with self.subTest(q):
                self.assertEqual(wa_style.company_in(q, names), want)

    def test_tighten(self):
        long = "\n".join(["37 on site at 588 Thomas S Boyland St now."]
                         + [f"• Worker {i} (Arkon) 6:{i:02d}" for i in range(40)])
        out, trimmed = wa_style.tighten(long, "how many on site", self.LABELS)
        self.assertTrue(trimmed)
        self.assertEqual(out, "37 on site at 588 now.\nWant the full list?")
        same, trimmed = wa_style.tighten(long, "who's on site", self.LABELS)
        self.assertFalse(trimmed)
        self.assertIn("Worker 39", same)
        one_line = "Open: " + ", ".join(f"item {i}" for i in range(80)) + "."
        out, _ = wa_style.tighten(one_line, "what's open")
        self.assertLessEqual(len(out), wa_style.MAX_CHARS)
        self.assertTrue(out.startswith("Open: item 0, item 1"))

    def test_what_takes_the_offer(self):
        for t in ("yes", "Yes please", "names", "the names", "list them", "sure", "full list"):
            self.assertTrue(wa_style.wants_more(t), t)
        # "ok" is a thank-you, not a yes to the offer.
        for t in ("ok", "okay", "yes but how many at 8 walworth tomorrow", "no", "what about permits"):
            self.assertFalse(wa_style.wants_more(t), t)


if __name__ == "__main__":
    unittest.main()
