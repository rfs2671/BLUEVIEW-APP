"""The agent was answering from a blank slate. Now it is told the facts.

Every failure in the 2026-09-14 live tests had the same shape underneath. The
agent did not know the date, so "last Thursday" was a guess. It did not know
the roster was empty because it was 23:33, so an empty answer read as "nobody
works here". It did not know which sheets exist, so it told a superintendent to
supply a sheet number. And it did not know a CP had reviewed a card, so it
answered from its own prior.

None of that is fixable by adding another instruction. The model was missing
the facts, so the facts are assembled fresh on every message.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402

SRC = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")


def _code_only(fn):
    return "\n".join(l for l in inspect.getsource(fn).split("\n")
                     if not l.lstrip().startswith("#"))


class _Cur:
    def __init__(self, rows):
        self.rows = rows

    def limit(self, n):
        return self

    async def to_list(self, n=None):
        return list(self.rows)


class _Coll:
    def __init__(self, rows=None, one=None):
        self.rows = rows or []
        self.one = one

    async def find_one(self, q=None, proj=None, sort=None):
        return self.one

    def find(self, q=None, proj=None):
        return _Cur(self.rows)

    async def count_documents(self, q):
        return len(self.rows)


def _db(*, checkins_rows=None, last_checkin=None, sheets=None,
        log=None, permits=None):
    class DB:
        projects = _Coll(one={"name": "588 Thomas S Boyland",
                              "address": "588 Thomas S Boyland St",
                              "nyc_bin": "3255362", "company_id": "co"})
        companies = _Coll(one={"name": "Prescott GC"})
        checkins = _Coll(rows=checkins_rows or [], one=last_checkin)
        daily_logs = _Coll(one=log)
        dob_logs = _Coll(rows=permits or [])
        document_page_index = _Coll(rows=sheets or [])
    return DB()


def _block(**kw):
    real = server.db
    server.db = _db(**kw)
    try:
        return asyncio.run(server._agent_context_block(
            "p1", {"who_on_site": True, "plan_queries": True}, "loose"))
    finally:
        server.db = real


# ══════════════════════════════════════════════════════════════════
# The midnight case
# ══════════════════════════════════════════════════════════════════

class AnEmptyRosterIsNotAnEmptySite(unittest.TestCase):
    """Asked at 23:33, "who's on site" answered as though nobody works here.
    Nobody was on site because it was half past eleven at night."""

    def test_the_last_working_day_is_named_when_today_is_empty(self):
        yesterday = server._eastern_now() - timedelta(days=1)
        out = _block(checkins_rows=[], last_checkin={"check_in_time": yesterday})
        self.assertIn("LAST WORKING DAY", out)
        self.assertIn(yesterday.strftime("%Y-%m-%d"), out)

    def test_a_project_that_has_never_had_a_checkin_says_so(self):
        """Distinguishable from "outside working hours", because the honest
        answers differ."""
        out = _block(checkins_rows=[], last_checkin=None)
        self.assertIn("no check-ins on record", out)

    def test_a_working_day_is_a_day_somebody_came_not_a_weekday(self):
        """Sites work Saturdays and stop for weather. A calendar rule would
        confidently name a day nobody was there.

        Asserted POSITIVELY. The first draft checked that "weekday" does not
        appear, and _code_only strips comments but not DOCSTRINGS — so it
        tripped on the sentence above explaining the choice."""
        code = _code_only(server._last_working_day)
        self.assertIn("db.checkins", code)
        self.assertIn("check_in_time", code)
        self.assertIn("sort=", code)

    def test_the_clock_is_eastern(self):
        """A UTC clock reads a New York evening as the next calendar day, so
        "today" would name a day that has not started."""
        self.assertIn("America/New_York", _code_only(server._eastern_now))
        self.assertIn("America/New_York", _block())

    def test_the_stance_tells_it_what_to_do_with_that(self):
        self.assertIn(
            "If today's data is empty because it's outside working hours, "
            "answer for the last working day and say which day",
            server._AGENT_STANCE)


# ══════════════════════════════════════════════════════════════════
# Dates
# ══════════════════════════════════════════════════════════════════

class RelativeDatesResolveAgainstTheContext(unittest.TestCase):
    """A model asked "last Thursday" with no date in its context computes one
    from whatever it believes today is, which is its training cutoff."""

    def test_the_now_line_carries_weekday_date_and_zone(self):
        """All three, because "last Thursday" needs the weekday and the date
        to be resolvable at all."""
        out = _block()
        now = server._eastern_now()
        self.assertIn(now.strftime("%A"), out)
        self.assertIn(now.strftime("%Y-%m-%d"), out)
        self.assertIn("America/New_York", out)

    def test_the_prompt_forbids_the_models_own_sense_of_the_date(self):
        p = server._AGENT_SYSTEM_PROMPT_BASE
        self.assertIn("never against your own sense", p)
        self.assertIn("NOW line", p)

    def test_it_must_state_the_date_it_resolved_to(self):
        """So a wrong reading is visible in the reply rather than silent."""
        self.assertIn("State the date you resolved to",
                      server._AGENT_SYSTEM_PROMPT_BASE)

    def test_tools_receive_a_resolved_date_not_a_phrase(self):
        self.assertIn("pass the resolved YYYY-MM-DD",
                      server._AGENT_SYSTEM_PROMPT_BASE)

    def test_the_log_tool_does_not_parse_english(self):
        """Two date parsers disagreeing is worse than one."""
        code = _code_only(server._handle_daily_log)
        self.assertIn("eastern_today()", code)
        for word in ("yesterday", "last ", "parse"):
            with self.subTest(word=word):
                self.assertNotIn(word, code.lower())


# ══════════════════════════════════════════════════════════════════
# A log is not a drawing
# ══════════════════════════════════════════════════════════════════

class TheLogHasItsOwnHome(unittest.TestCase):
    """"show me OSHA log" reached query_plan, which searched the DRAWING index
    for a safety log, found sheets whose text mentions "log", and sent them.
    The routing was not wrong about the words — the log had no tool, and a
    request with no tool falls to whatever tool will take it."""

    def test_the_tool_exists(self):
        names = [t["function"]["name"] for t in server._AGENT_TOOLS]
        self.assertIn("daily_log", names)

    def test_it_is_dispatched(self):
        self.assertIn('if name == "daily_log":',
                      _code_only(server._dispatch_agent_tool))

    def test_its_description_claims_the_words_that_were_misrouted(self):
        desc = next(t["function"]["description"] for t in server._AGENT_TOOLS
                    if t["function"]["name"] == "daily_log")
        for word in ("OSHA log", "daily log", "jobsite log", "sign-ins"):
            with self.subTest(word=word):
                self.assertIn(word, desc)
        self.assertIn("Never use query_plan for a log", desc)

    def test_the_prompt_bans_query_plan_for_every_non_drawing_subject(self):
        """Stated as an exclusion list rather than a description, because
        "about the drawings" is exactly the judgement a model talks itself
        into."""
        p = server._AGENT_SYSTEM_PROMPT_BASE
        self.assertIn("QUERY_PLAN IS ONLY FOR CONSTRUCTION DRAWINGS", p)
        for subject in ("daily logs", "OSHA logs", "sign-ins", "workers",
                        "permits", "DOB filings", "checklists", "open items"):
            with self.subTest(subject=subject):
                self.assertIn(subject, p)

    def test_it_forbids_the_fallback_that_caused_this(self):
        self.assertIn("do not fall back to query_plan",
                      server._AGENT_SYSTEM_PROMPT_BASE)

    def test_a_missing_log_names_the_day_it_looked_for(self):
        """"No daily log found" leaves the reader unsure which day was
        checked."""
        real = server.db
        server.db = _db(log=None)
        try:
            out = asyncio.run(server._handle_daily_log("p1", "2026-09-11"))
        finally:
            server.db = real
        self.assertIn("2026-09-11", out)


# ══════════════════════════════════════════════════════════════════
# Nobody is asked to name a sheet
# ══════════════════════════════════════════════════════════════════

class TheAgentKnowsWhichSheetsExist(unittest.TestCase):

    def test_the_sheet_index_is_in_the_context(self):
        out = _block(sheets=[{"sheet_number": "A-500.00",
                              "sheet_title": "Wall Types"}])
        self.assertIn("SHEET INDEX", out)
        self.assertIn("A-500.00 — Wall Types", out)

    def test_a_project_with_no_drawings_says_so(self):
        self.assertIn("no drawings indexed", _block(sheets=[]))

    def test_the_index_is_capped_and_says_when_it_bit(self):
        """A silently truncated list must not be mistaken for a complete
        one."""
        many = [{"sheet_number": f"A-{i:03d}", "sheet_title": "x"}
                for i in range(server._SHEET_INDEX_CAP + 5)]
        out = _block(sheets=many)
        self.assertIn("more not listed", out)

    def test_no_reply_asks_the_user_to_supply_a_sheet_number(self):
        """The old copy — "Try a sheet number (A-301, ME-401)" — hands the
        problem back to somebody who does not carry the drawing list in his
        head. Code lines only: the comment above the fix quotes it."""
        code = "\n".join(l for l in SRC.split("\n")
                         if not l.lstrip().startswith("#"))
        self.assertNotIn("Try a sheet number", code)

    def test_the_stance_says_it_outright(self):
        self.assertIn("Never make the user name a sheet", server._AGENT_STANCE)


# ══════════════════════════════════════════════════════════════════
# The stance, and the model that has to hold it
# ══════════════════════════════════════════════════════════════════

class TheStanceIsVerbatimAndFirst(unittest.TestCase):

    EXPECTED = (
        "You are the GC's assistant. You know this project. Answer the question "
        "the person means, not the literal one. If today's data is empty because "
        "it's outside working hours, answer for the last working day and say "
        "which day. Never make the user name a sheet. Never invent policy — if "
        "the data doesn't say, say the data doesn't say. One reply, no follow-up "
        "questions unless the request is genuinely ambiguous."
    )

    def test_it_is_word_for_word(self):
        self.assertIn(self.EXPECTED, server._AGENT_STANCE)

    def test_it_comes_before_the_mechanics(self):
        """A model that reads "answer the question the person means" before it
        reads the routing table routes differently."""
        p = server._AGENT_SYSTEM_PROMPT_BASE
        self.assertLess(p.index("You are the GC's assistant"),
                        p.index("ROUTING"))

    def test_it_is_in_both_prompt_variants(self):
        for clause in (server._AGENT_EXPLICIT_CLAUSE,
                       server._AGENT_NOREPLY_CLAUSE):
            with self.subTest():
                self.assertIn(self.EXPECTED,
                              server._AGENT_SYSTEM_PROMPT_BASE + clause)


class TheAgentRunsOnTheBiggerModel(unittest.TestCase):

    def test_the_group_agent_is_gpt_4o(self):
        self.assertEqual(server.AGENT_MODEL, "gpt-4o")
        self.assertIn('"model": AGENT_MODEL', _code_only(server._run_group_agent))

    def test_the_token_budget_fits_an_answer_with_a_citation(self):
        self.assertEqual(server.AGENT_MAX_TOKENS, 800)

    def test_the_classifiers_stay_on_mini(self):
        """They emit one label from a fixed set or fill a fixed schema. None
        of them reasons, and they run on traffic the agent never sees."""
        for fn in (server.classify_intent, server._detect_material_request,
                   server._parse_plan_query):
            with self.subTest(fn=fn.__name__):
                self.assertIn('"model": "gpt-4o-mini"', inspect.getsource(fn))

    def test_the_agent_names_its_model_once_in_a_constant(self):
        """NOT "the only gpt-4o call in the file" — that was the first draft
        and it was simply false. _handle_material_receipt and the scheduled
        group summary were already on gpt-4o before this change and are outside
        this PR's scope. What matters here is that the agent's model is named
        once, in a constant, so it cannot drift between the two places the
        agent is configured."""
        self.assertEqual(SRC.count('AGENT_MODEL = "gpt-4o"'), 1)
        self.assertIn(
            '"model": AGENT_MODEL', SRC,
            "the agent call no longer reads the model from the constant, so "
            "the two places the agent is configured can drift apart")


class TheAnswerLeadsWithTheAnswer(unittest.TestCase):

    def test_the_shape_is_stated(self):
        p = server._AGENT_SYSTEM_PROMPT_BASE
        self.assertIn("LEAD WITH THE ANSWER", p)
        self.assertIn("CITE THE SOURCE", p)

    def test_the_post_processing_strip_is_still_wired(self):
        """Belt and braces. The prompt asks; the stripper guarantees."""
        self.assertIn("_strip_generic_offer",
                      _code_only(server.send_whatsapp_message))


class TheContextBlockCannotTakeTheReplyWithIt(unittest.TestCase):

    def test_a_failure_degrades_to_the_old_behaviour(self):
        code = _code_only(server._run_group_agent)
        i = code.index("_agent_context_block")
        self.assertIn("except Exception", code[i:i + 400])

    def test_it_is_appended_so_the_static_prefix_stays_cacheable(self):
        """Putting today's roster at the FRONT would change the first token of
        every request and throw the prefix cache away on every call."""
        code = _code_only(server._run_group_agent)
        self.assertIn('f"{system_prompt}\\n\\n{context_block}"', code)

    def test_every_section_is_independently_guarded(self):
        """A section that cannot be read is omitted rather than faked: an
        absent line and a line saying "0" mean different things."""
        code = _code_only(server._agent_context_block)
        self.assertGreaterEqual(code.count("except Exception"), 5)

    def test_it_reads_only_collections_the_app_writes(self):
        """The first draft invented `daily_jobsite_logs` and `permits` from the
        names of the tools. A context block that counts zero because it queried
        a collection nobody writes is worse than none, since the model reports
        the zero as fact."""
        code = _code_only(server._agent_context_block)
        import re
        for coll in set(re.findall(r"db\.([a-z_]+)", code)):
            with self.subTest(collection=coll):
                self.assertGreater(
                    SRC.count(f"db.{coll}"), 1,
                    f"db.{coll} appears only in the context block — invented")


if __name__ == "__main__":
    unittest.main()
