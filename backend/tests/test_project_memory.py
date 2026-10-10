"""Project memory search v1 -- evidence or silence (lib/project_memory.py and
server.py "PROJECT MEMORY")."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import project_memory as pm  # noqa: E402
from scripts import memory_dry_run as dry  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

T0 = datetime(2026, 9, 21, 11, 0, tzinfo=timezone.utc)
SCENARIO = Path(dry.__file__).parent / "memory_eval" / "job_2wk_2026_09.json"
ADMIN = {"id": "u_admin", "_id": "u_admin", "role": "admin", "company_id": "co1",
         "account_status": "approved"}
PM_ON = {"id": "u_pm", "_id": "u_pm", "role": "pm", "company_id": "co1",
         "assigned_projects": ["p1"], "account_status": "approved"}
PM_OFF = {**PM_ON, "assigned_projects": ["p2"]}
CP = {"id": "u_cp", "_id": "u_cp", "role": "cp", "company_id": "co1",
      "assigned_projects": ["p1"], "account_status": "approved"}


def _run(coro):
    return asyncio.run(coro)


def _vec(text):
    return dry.hashed_vector(text)


async def _fake_embed(texts):
    return [_vec(t) for t in texts]


def _msg(i, body, project="p1", company="co1", group="g1@g.us", **over):
    return {"_id": f"r{i}", "group_id": group, "project_id": project, "company_id": company,
            "sender": f"20100000000000{i % 10}", "sender_jid": f"20100000000000{i % 10}@lid",
            "sender_name": "Dave", "body": body, "message_id": f"M{i}",
            "timestamp": T0 + timedelta(minutes=i), "created_at": T0 + timedelta(minutes=i),
            **over}


def _world(msgs=(), logs=(), companies=None):
    return FakeDb(
        companies=companies or [{"_id": "co1"}, {"_id": "co2"}],
        projects=[{"_id": "p1", "company_id": "co1", "name": "120 Atlantic"},
                  {"_id": "p2", "company_id": "co1", "name": "8 Walworth"},
                  {"_id": "p9", "company_id": "co2", "name": "Other GC"}],
        whatsapp_groups=[{"_id": "wg1", "wa_group_id": "g1@g.us", "project_id": "p1",
                          "company_id": "co1", "group_name": "120 Atlantic – Site"}],
        whatsapp_messages=list(msgs), logbooks=list(logs))


def _index(db, runs=5):
    with patch.object(server, "db", db), patch.object(server, "_memory_embed_many", _fake_embed), \
            patch.object(server, "MEMORY_EMBED_PAUSE", 0):
        for _ in range(runs):
            _run(server._memory_index_tick(T0 + timedelta(days=1)))


class TheCheck(unittest.TestCase):
    SOURCES = [{"sid": "S1", "text": "Underpinning pits 1–4 poured this morning, 12 yards"},
               {"sid": "S2", "text": "Owner wants the 3B bedroom window changed to a casement"}]

    def test_a_quote_must_be_in_a_retrieved_source(self):
        raw = [{"text": "Poured Sep 23", "source": "S1", "quote": "pits 1–4 poured this morning"},
               {"text": "Made up", "source": "S1", "quote": "poured on Tuesday at noon"}]
        got = pm.checked_claims(raw, self.SOURCES)
        self.assertEqual([c["text"] for c in got], ["Poured Sep 23"])

    def test_spacing_case_and_curly_quotes_aside(self):
        raw = [{"text": "x", "source": "S2", "quote": "OWNER  wants the 3B bedroom"}]
        self.assertEqual(len(pm.checked_claims(raw, self.SOURCES)), 1)

    def test_the_citation_follows_the_words(self):
        raw = [{"text": "x", "source": "S1", "quote": "changed to a casement"}]
        self.assertEqual(pm.checked_claims(raw, self.SOURCES)[0]["sid"], "S2")

    def test_a_quote_over_200_characters_is_dropped(self):
        long = {"sid": "S3", "text": "a " * 300}
        raw = [{"text": "x", "source": "S3", "quote": "a " * 120}]
        self.assertEqual(pm.checked_claims(raw, [long]), [])

    def test_nothing_left_is_no_source(self):
        self.assertEqual(pm.format_answer([], {}), pm.NO_SOURCE)
        self.assertEqual(pm.NO_SOURCE, "I can't find that in the project history.")

    def test_bad_model_output(self):
        for content in (None, "not json", "[1, 2]", '{"claims": "x"}'):
            self.assertEqual(pm.checked_claims(pm.parse_model(content).get("claims"),
                                               self.SOURCES), [])

    def test_checkbox_groups_are_the_names_ticked(self):
        log = {"data": {"equipment_on_site": {"boom_crane": False, "compressor": True,
                                              "scissor_lift": True},
                        "visitors_deliveries": ["Rebar delivery", "", "DOB inspector"]}}
        e = {x["key"]: x["text"] for x in pm.daily_report_entries(log)}
        self.assertEqual(e["equipment"], "compressor, scissor lift")
        self.assertEqual(e["visitors"], "Rebar delivery, DOB inspector")
        self.assertNotIn("boom", e["equipment"])
        self.assertEqual(pm.daily_report_entries({"data": {"equipment_on_site": {"x": False}}}), [])

    def test_full_story_words(self):
        self.assertTrue(pm.is_full_story("what happened with the storefront?"))
        self.assertTrue(pm.is_full_story("give me the full story on the risers"))
        self.assertFalse(pm.is_full_story("when did we pour underpinning?"))

    def test_daily_report_entries(self):
        log = {"data": {"general_description": "Underpinning pour.",
                        "activities": [{"company": "Solid", "trade": "Concrete",
                                        "work_description": "Poured pits 1-4",
                                        "work_locations": "East wall"},
                                       {"company": "X", "work_description": ""}],
                        "observations": [{"description": "Rebar chairs added"}, {"note": ""}]}}
        e = pm.daily_report_entries(log)
        self.assertEqual([x["key"] for x in e], ["general", "activity:0", "observation:0"])
        self.assertEqual(e[1]["text"], "Poured pits 1-4 (East wall)")


def _src(sid, text, who="Wendy Cho", day="Sep 24", source="whatsapp"):
    return {"sid": sid, "text": text, "who": who, "day_label": day, "source": source,
            "group": "Site", "when": f"{day}, 8:30 AM"}


class Faithful(unittest.TestCase):
    """Who decided is not who posted; a plan stays a plan; one claim per fact."""

    def test_a_relayed_decision_names_the_decider_not_the_poster(self):
        srcs = [_src("S1", "Owner wants the 3B bedroom window changed to a casement")]
        (c,) = pm.checked_claims([{"text": "Wendy Cho wanted the 3B window changed",
                                   "source": "S1", "quote": "Owner wants the 3B bedroom window"}],
                                 srcs)
        self.assertEqual(c["text"], "The owner wanted the 3B window changed")
        self.assertEqual((c["decider"], c["relayed_by"]), ("the owner", "Wendy Cho"))
        out = pm.format_answer([c], {"S1": srcs[0]})
        self.assertTrue(out.startswith("• The owner wanted the 3B window changed "
                                       "(relayed by Wendy Cho, Sep 24)"))

    def test_the_poster_speaking_for_themself_is_the_decider(self):
        srcs = [_src("S1", "I want the 3B window changed to a casement")]
        (c,) = pm.checked_claims([{"text": "Wendy Cho wanted it changed", "source": "S1",
                                   "quote": "I want the 3B window changed"}], srcs)
        self.assertEqual(c["text"], "Wendy Cho wanted it changed")
        self.assertNotIn("relayed_by", c)

    def test_a_name_counts_only_when_it_is_a_person_in_the_records(self):
        self.assertIsNone(pm.relayed_decider("Drawings approved by the architect", "Kevin Shah",
                                             ["Kevin Shah", "Mike Rivera"]))
        self.assertEqual(pm.relayed_decider("Mike approved the panel layout", "Kevin Shah",
                                            ["Kevin Shah", "Mike Rivera"]), "Mike")
        self.assertIsNone(pm.relayed_decider("Mike approved the panel layout", "Kevin Shah", []))

    def test_a_plan_is_never_told_as_done(self):
        srcs = [_src("S1", "Dumpster swap is set for Tuesday 10/6", who="Roy", day="Oct 2"),
                _src("S2", "Eddie we're getting a pump from the rental yard", who="Roy", day="Sep 28")]
        got = pm.checked_claims([
            {"text": "The dumpster was swapped on Tuesday", "source": "S1",
             "quote": "Dumpster swap is set for Tuesday 10/6"},
            {"text": "A pump was acquired from the rental yard", "source": "S2",
             "quote": "we're getting a pump from the rental yard"}], srcs)
        self.assertEqual([c["text"] for c in got],
                         ["Planned, as of Oct 2 — not confirmed as done",
                          "Planned, as of Sep 28 — not confirmed as done"])
        self.assertTrue(all(c["planned"] for c in got))

    def test_done_words_and_plain_plans_are_left_alone(self):
        srcs = [_src("S1", "Pump is here and running, pit should be dry by tomorrow", who="Eddie"),
                _src("S2", "Storefront shop drawings approved with comments. Frame install is "
                           "set for October 12.", who="Kevin"),
                _src("S3", "Dumpster swap is set for Tuesday 10/6", who="Roy")]
        got = pm.checked_claims([
            {"text": "The pump arrived", "source": "S1", "quote": "Pump is here and running"},
            {"text": "The drawings were approved with comments", "source": "S2",
             "quote": "Storefront shop drawings approved with comments"},
            {"text": "A dumpster swap is planned for Tuesday 10/6", "source": "S3",
             "quote": "Dumpster swap is set for Tuesday 10/6"}], srcs)
        self.assertEqual([c["text"] for c in got], ["The pump arrived",
                                                    "The drawings were approved with comments",
                                                    "A dumpster swap is planned for Tuesday 10/6"])

    def test_one_claim_per_fact_with_every_source(self):
        srcs = [_src("S1", "Underpinning pits 1–4 poured this morning, 12 yards", who="Dave"),
                _src("S2", "Poured underpinning pits 1-4 along the east wall", source="daily_report"),
                _src("S3", "Window in 3B changed to a casement", who="Kevin")]
        tally = {}
        got = pm.checked_claims([
            {"text": "Underpinning pits 1-4 were poured on Sep 23", "source": "S1",
             "quote": "Underpinning pits 1–4 poured this morning"},
            {"text": "Underpinning pits 1–4 were poured Sep 23", "source": "S2",
             "quote": "Poured underpinning pits 1-4"},
            {"text": "The 3B window became a casement", "source": "S3",
             "quote": "Window in 3B changed to a casement"},
            {"text": "Made up", "source": "S1", "quote": "poured on Monday at noon"}],
            srcs, report=tally)
        self.assertEqual(len(got), 2)
        self.assertEqual([a["sid"] for a in got[0]["also"]], ["S2"])
        self.assertEqual(tally, {"dropped": 1, "merged": 1, "made_faithful": 0})
        out = pm.format_answer(got, {s["sid"]: s for s in srcs})
        self.assertEqual(out.count("Underpinning pits 1-4 were poured"), 1)
        self.assertIn("Daily report", out)

    def test_several_sources_in_one_claim(self):
        srcs = [_src("S1", "rebar chairs added at F3", who="Dave"),
                _src("S2", "DOB inspector requested additional rebar chairs at footing F3",
                     source="daily_report")]
        (c,) = pm.checked_claims([{"text": "More rebar chairs at F3", "sources": [
            {"source": "S1", "quote": "rebar chairs added at F3"},
            {"source": "S2", "quote": "additional rebar chairs at footing F3"},
            {"source": "S2", "quote": "not in it at all"}]}], srcs)
        self.assertEqual((c["sid"], [a["sid"] for a in c["also"]]), ("S1", ["S2"]))

    def test_timeline_events_on_different_days_stay_apart(self):
        srcs = [_src("S1", "Storefront shop drawings due Friday", who="Kevin", day="Sep 21"),
                _src("S2", "Storefront shop drawings sent", who="Sam", day="Sep 30")]
        got = pm.checked_claims([
            {"text": "Storefront shop drawings", "source": "S1", "quote": "shop drawings due Friday"},
            {"text": "Storefront shop drawings", "source": "S2", "quote": "shop drawings sent"}],
            srcs, timeline=True)
        self.assertEqual([c["date"] for c in got], ["Sep 21", "Sep 30"])


class TheIndex(unittest.TestCase):

    def test_linked_group_messages_only(self):
        db = _world([
            _msg(1, "Underpinning pits poured"),
            _msg(2, "dm text", is_dm=True),
            _msg(3, "bot says hi", sender="bot"),
            _msg(4, "unlinked group text", project=None),
            _msg(5, "   "),
        ])
        _index(db)
        rows = db[pm.COLLECTION].rows
        self.assertEqual([r["_id"] for r in rows], ["wa:r1"])
        self.assertEqual((rows[0]["group_name"], rows[0]["day"]), ("120 Atlantic – Site", "2026-09-21"))
        self.assertIsNotNone(rows[0]["embedding"])
        self.assertTrue(rows[0]["embedded"])

    def test_the_backfill_resumes_and_is_bounded(self):
        db = _world([_msg(i, f"message number {i} about risers") for i in range(1, 8)])
        with patch.object(server, "MEMORY_SCAN_PER_RUN", 3), \
                patch.object(server, "MEMORY_EMBED_PER_RUN", 2), \
                patch.object(server, "MEMORY_EMBED_BATCH", 2):
            _index(db, runs=1)
            self.assertEqual(len(db[pm.COLLECTION].rows), 3)
            self.assertEqual(sum(1 for r in db[pm.COLLECTION].rows if r["embedding"]), 2)
            _index(db, runs=6)
        self.assertEqual(len(db[pm.COLLECTION].rows), 7)
        self.assertTrue(all(r["embedding"] for r in db[pm.COLLECTION].rows))

    def test_many_messages_at_one_instant_do_not_stall_the_cursor(self):
        rows = [_msg(i, f"bulk import line {i}") for i in range(1, 8)]
        for r in rows:
            r["created_at"] = T0                     # all at the same instant
        db = _world(rows)
        with patch.object(server, "MEMORY_SCAN_PER_RUN", 2):
            _index(db, runs=5)
        self.assertEqual(len(db[pm.COLLECTION].rows), 7)

    def test_a_failed_embedding_is_retried(self):
        db = _world([_msg(1, "risers sent")])

        async def down(texts):
            return None
        with patch.object(server, "db", db), patch.object(server, "_memory_embed_many", down):
            rep = _run(server._memory_index_tick(T0))
        self.assertEqual(rep["embed_failed"], 1)
        self.assertIsNone(db[pm.COLLECTION].rows[0]["embedding"])
        self.assertFalse(db[pm.COLLECTION].rows[0]["embedded"])
        _index(db, runs=1)
        self.assertIsNotNone(db[pm.COLLECTION].rows[0]["embedding"])

    def test_daily_reports_and_what_is_gone_is_removed(self):
        log = {"_id": "L1", "project_id": "p1", "company_id": "co1", "log_type": "daily_jobsite",
               "status": "submitted", "date": "2026-09-23", "cp_name": "Roy",
               "updated_at": T0, "data": {"general_description": "Underpinning pour."}}
        db = _world([_msg(1, "risers sent")], [log])
        _index(db)
        self.assertEqual(sorted(r["_id"] for r in db[pm.COLLECTION].rows),
                         ["dr:L1:general", "wa:r1"])
        db.whatsapp_messages.rows.clear()           # retention took the message
        db.logbooks.rows[0]["is_deleted"] = True
        _index(db, runs=1)
        self.assertEqual(db[pm.COLLECTION].rows, [])

    def test_fixture_companies_are_not_indexed(self):
        db = _world([_msg(1, "risers sent")], companies=[{"_id": "co1", "is_test": True}])
        _index(db)
        self.assertEqual(db[pm.COLLECTION].rows, [])


class TheSearch(unittest.TestCase):

    def _db(self):
        db = _world([_msg(1, "Underpinning pits 1-4 poured this morning, 4000 psi"),
                     _msg(2, "Window in 3B changed to a casement"),
                     _msg(3, "Underpinning pour on the other job", project="p2"),
                     _msg(4, "Underpinning poured at another GC", project="p9", company="co2")])
        _index(db)
        return db

    def test_scoped_to_one_project_of_one_company(self):
        db = self._db()
        with patch.object(server, "db", db), patch.object(server, "_memory_embed_many", _fake_embed), \
                patch.dict(server._MEMORY_ATLAS, {"ok": False}):
            rows = _run(server._memory_search("co1", "p1", "underpinning pour"))
            self.assertEqual([r["source_id"] for r in rows][0], "r1")
            self.assertTrue(all(r["project_id"] == "p1" and r["company_id"] == "co1" for r in rows))
            self.assertEqual(_run(server._memory_search("co2", "p1", "underpinning")), [])
            # A date range.
            self.assertEqual(_run(server._memory_search("co1", "p1", "underpinning",
                                                        date_from="2026-09-22")), [])

    def test_an_answer_whose_quotes_are_not_in_the_sources_is_no_source(self):
        db = self._db()

        async def liar(messages):
            return json.dumps({"claims": [{"text": "Poured Monday", "source": "S1",
                                           "quote": "poured Monday at 6am, 5000 psi"}]})
        with patch.object(server, "db", db), patch.object(server, "_memory_embed_many", _fake_embed), \
                patch.dict(server._MEMORY_ATLAS, {"ok": False}):
            got = _run(server._memory_answer("co1", "p1", "when did we pour underpinning?", llm=liar))
        self.assertEqual(got["text"], pm.NO_SOURCE)
        self.assertEqual(got["dropped"], 1)

    def test_a_cited_answer(self):
        db = self._db()

        async def honest(messages):
            assert "Underpinning pits 1-4 poured" in messages[-1]["content"]
            return json.dumps({"claims": [{"text": "Poured on Sep 21", "source": "S1",
                                           "quote": "Underpinning pits 1-4 poured this morning"}]})
        with patch.object(server, "db", db), patch.object(server, "_memory_embed_many", _fake_embed), \
                patch.dict(server._MEMORY_ATLAS, {"ok": False}):
            got = _run(server._memory_answer("co1", "p1", "when did we pour underpinning?", llm=honest))
        self.assertIn("Poured on Sep 21", got["text"])
        self.assertIn("120 Atlantic – Site · Sep 21", got["text"])
        self.assertIn("“Underpinning pits 1-4 poured this morning”", got["text"])


class AtlasOrNot(unittest.TestCase):

    def test_atlas_is_tried_again_later(self):
        db = _world([_msg(1, "risers sent")])
        _index(db)
        with patch.object(server, "db", db), patch.object(server, "_memory_embed_many", _fake_embed), \
                patch.dict(server._MEMORY_ATLAS, {"ok": None, "retry_at": None}):
            rows = _run(server._memory_search("co1", "p1", "risers"))   # FakeDb: no $search
            self.assertEqual([r["source_id"] for r in rows], ["r1"])
            self.assertFalse(server._MEMORY_ATLAS["ok"])
            self.assertIsNotNone(server._MEMORY_ATLAS["retry_at"])

    def test_the_date_span_is_new_york_days(self):
        span = server._memory_span({"day": {"$gte": "2026-09-21", "$lte": "2026-09-21"}})
        self.assertEqual(span["$gte"].isoformat(), "2026-09-21T04:00:00+00:00")
        self.assertEqual(span["$lte"].isoformat(), "2026-09-22T03:59:59.999999+00:00")


class TheTimelineDates(unittest.TestCase):

    def test_tracked_item_history_keeps_to_the_date_range(self):
        def ev(i, day):
            return {"id": f"e{i}", "kind": "state", "to": "rescheduled", "due_to": "Monday",
                    "quote": f"storefront moved {i}",
                    "at": datetime.fromisoformat(f"{day}T15:00:00+00:00")}
        db = FakeDb(attention_items=[{
            "_id": "a1", "company_id": "co1", "project_id": "p1", "type": "commitment",
            "summary": "storefront shop drawings", "topic": ["storefront"],
            "owner": {"name": "Sam"}, "evidence": {"quote": "storefront", "sent_at": T0},
            "history": [ev(1, "2026-08-30"), ev(2, "2026-09-10"), ev(3, "2026-10-02")]}])
        with patch.object(server, "db", db):
            rows = _run(server._memory_attention_sources(
                "co1", "p1", "what happened with the storefront", date_from="2026-09-01",
                date_to="2026-09-30"))
        self.assertEqual([r["_id"] for r in rows], ["att:a1:e2"])


class TheBootLine(unittest.TestCase):
    """[memory] atlas_search=ok|fallback, vector_index=ok|fallback, reason=..."""

    def _check(self, listed, command=None):
        db = FakeDb()

        class Cur:
            def __init__(self, rows):
                self.rows = rows

            async def to_list(self, n=None):
                return list(self.rows)

        calls = []

        def aggregate(pipeline):
            assert pipeline == [{"$listSearchIndexes": {}}]
            return Cur(listed[min(len(calls), len(listed) - 1)])

        async def cmd(c):
            calls.append(c["indexes"][0]["name"])
            if command:
                raise command
        db.project_memory.aggregate = aggregate
        db.command = cmd
        with patch.object(server, "db", db), \
                patch.dict(server._MEMORY_ATLAS, {"ok": None, "line": None}), \
                self.assertLogs("server", level="INFO") as logs:
            st = _run(server._memory_atlas_check(create=True, log=True))
            ok = server._MEMORY_ATLAS["ok"]
        line = [m for m in logs.output if "atlas_search=" in m]
        return st, calls, line, ok

    def test_ready(self):
        ready = [{"name": pm.TEXT_INDEX, "status": "READY", "queryable": True},
                 {"name": pm.VECTOR_INDEX, "status": "READY", "queryable": True}]
        st, calls, line, ok = self._check([ready])
        self.assertEqual((st["atlas_search"], st["vector_index"], st["reason"]), ("ok", "ok", "ready"))
        self.assertEqual(calls, [])
        self.assertTrue(ok)
        self.assertIn("[memory] atlas_search=ok, vector_index=ok, reason=ready", line[0])

    def test_created_on_first_boot_and_still_building(self):
        building = [{"name": pm.TEXT_INDEX, "status": "BUILDING", "queryable": False},
                    {"name": pm.VECTOR_INDEX, "status": "PENDING", "queryable": False}]
        st, calls, line, ok = self._check([[], building])
        self.assertEqual(calls, [pm.TEXT_INDEX, pm.VECTOR_INDEX])
        self.assertEqual((st["atlas_search"], st["vector_index"]), ("fallback", "fallback"))
        self.assertEqual(st["reason"], f"{pm.TEXT_INDEX} created; {pm.VECTOR_INDEX} created; "
                                       f"{pm.TEXT_INDEX} building; {pm.VECTOR_INDEX} pending")
        self.assertNotEqual(ok, True)
        self.assertEqual(len(line), 1)

    def test_not_atlas(self):
        db = FakeDb()                       # no $listSearchIndexes at all
        with patch.object(server, "db", db), \
                patch.dict(server._MEMORY_ATLAS, {"ok": None, "line": None}), \
                self.assertLogs("server", level="INFO") as logs:
            st = _run(server._memory_atlas_check(create=True, log=True))
        self.assertEqual((st["atlas_search"], st["vector_index"]), ("fallback", "fallback"))
        self.assertTrue(st["reason"].startswith("cannot list search indexes ("))
        self.assertTrue(any("[memory] atlas_search=fallback, vector_index=fallback, reason=cannot list"
                            in m for m in logs.output))

    def test_a_create_that_fails_says_why(self):
        st, calls, line, ok = self._check([[]], command=RuntimeError("Atlas Search not enabled"))
        self.assertIn(f"{pm.TEXT_INDEX} not created (RuntimeError Atlas Search not enabled)",
                      st["reason"])
        self.assertIn(f"{pm.VECTOR_INDEX} missing", st["reason"])


class TheDmTool(unittest.TestCase):

    def test_two_questions_in_one_chat_keep_their_own_answers(self):
        self.assertNotEqual(server._memory_dm_key("1@c.us", "M1"), server._memory_dm_key("1@c.us", "M2"))

    def test_offered_in_a_dm_only(self):
        tool = next(t for t in server._AGENT_TOOLS
                    if t["function"]["name"] == "search_project_history")
        self.assertIn("query", tool["function"]["parameters"]["properties"])
        src = Path(server.__file__).read_text()
        self.assertIn('if name == "search_project_history" and (not dm or _memory_disabled()):', src)

    def test_refused_in_a_group(self):
        db = _world()
        with patch.object(server, "db", db):
            out = _run(server._dispatch_agent_tool(
                "search_project_history", {"query": "window"}, project_id="p1",
                group_id="120363000000000001@g.us", company_id="co1", sender="1"))
        self.assertIn("direct message only", out)

    def test_the_checked_answer_goes_out_as_it_is(self):
        db = _world()
        chat = "15550001111@c.us"

        async def fake_agent(**kw):
            await server._dispatch_agent_tool(
                "search_project_history", {"query": "window"}, project_id="p1",
                group_id=chat, company_id="co1", sender="1", reply_to=kw["reply_to"])
            kw["tool_trace"].append({"tool": "search_project_history", "args": {}, "result": "x"})
            return "The window was changed 3 times on 9/24."      # agent rewording: ignored

        async def fake_answer(*a, **k):
            return {"text": "• Changed\n   Wendy · Site · Sep 24: “to a casement”",
                    "claims": [], "sources": [], "mode": "answer"}
        with patch.object(server, "db", db), patch.object(server, "_run_group_agent", fake_agent), \
                patch.object(server, "_memory_answer", fake_answer):
            out = _run(server._dm_answer_job({"company_id": "co1"}, {"_id": "p1"}, chat,
                                              "who changed the window?", "M1"))
        self.assertTrue(out.startswith("• Changed"))


class TheScreen(unittest.TestCase):

    def _db(self):
        msgs = [_msg(i, f"line {i} about the storefront") for i in range(1, 8)]
        db = _world(msgs)
        _index(db)
        db.users.rows += [ADMIN, PM_ON, PM_OFF, CP]
        return db

    def _call(self, db, user, fn, *a, **k):
        with patch.object(server, "db", db), patch.object(server, "_memory_embed_many", _fake_embed), \
                patch.dict(server._MEMORY_ATLAS, {"ok": False}):
            return _run(fn(*a, current_user=user, **k))

    def test_admin_and_assigned_pm_only(self):
        db = self._db()
        out = self._call(db, ADMIN, server.search_project_memory, "p1", q="storefront")
        self.assertTrue(out["results"])
        r = out["results"][0]
        for k in ("id", "source", "who", "group", "when", "text"):
            self.assertIn(k, r)
        self.assertTrue(self._call(db, PM_ON, server.search_project_memory, "p1", q="storefront")["results"])
        for user, code in ((PM_OFF, 403), (CP, 403)):
            with self.assertRaises(HTTPException) as e:
                self._call(db, user, server.search_project_memory, "p1", q="storefront")
            self.assertEqual(e.exception.status_code, code)
        with self.assertRaises(HTTPException):
            self._call(db, ADMIN, server.search_project_memory, "p9", q="storefront")

    def test_context_is_the_message_with_two_before_and_two_after(self):
        db = self._db()
        out = self._call(db, ADMIN, server.project_memory_context, "p1", "wa:r4")
        self.assertEqual([m["id"] for m in out["messages"]],
                         ["wa:r2", "wa:r3", "wa:r4", "wa:r5", "wa:r6"])
        self.assertEqual([m["hit"] for m in out["messages"]], [False, False, True, False, False])
        with self.assertRaises(HTTPException):
            self._call(db, ADMIN, server.project_memory_context, "p2", "wa:r4")


class TheDryRun(unittest.TestCase):

    def test_the_two_week_job_scripted(self):
        sc = dry.load(str(SCENARIO))
        self.assertEqual(len(sc["questions"]), 12)
        out = asyncio.run(dry.run(sc, scripted=True))
        r = dry.report(sc, out)
        self.assertEqual(r["sent"], [])
        bad = [(q["q"], q["notes"]) for q in r["questions"] if q["verdict"] not in ("HARD", "PASS")]
        self.assertEqual(bad, [])
        self.assertEqual(dry.exit_code(r), 0)

    def test_a_missing_source_says_whether_it_was_retrieved(self):
        sc = dry.load(str(SCENARIO))
        q = next(x for x in sc["questions"] if x["q"].startswith("what happened with the storefront"))
        got = {"text": "• x\n   Kevin: “y”", "mode": "timeline", "dropped": 0,
               "sources": [{"sid": "S1", "id": "wa:row_m2"}, {"sid": "S2", "id": "wa:row_m16"}],
               "claims": [{"sid": "S2", "text": "x", "quote": "y", "also": []}]}
        notes = " | ".join(dry.score(sc, q, got)["notes"])
        self.assertIn("m2 retrieved #1 of 2, not cited", notes)
        self.assertIn("m23 not retrieved (top 2)", notes)

    def test_an_answer_to_an_unanswerable_question_fails_the_run(self):
        sc = dry.load(str(SCENARIO))
        q = next(x for x in sc["questions"] if (x["expect"] or {}).get("none"))
        fake = {"text": "The owner picked brushed steel.", "claims": [], "sources": [],
                "mode": "answer"}
        row = dry.score(sc, q, fake)
        self.assertEqual(row["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
