"""The answer log (lib/answer_log.py, server._answer_log_write): one immutable
row per answer, written from every answer site, read per company only.

  * APPEND-ONLY: nothing in server.py, lib/ or scripts/ updates, replaces or
    deletes a row; one insert, in _answer_log_write.
  * Not swept by the retention purge or the project hard delete (no rule
    covers it; see the report on the branch).
  * The row: question, final text, records as the model saw them, tool
    results (a chat-message tool: a hash only), gate decisions, model, code
    SHA, content hash; no phone in full.
  * Per-company reads.
  * The DM answer site writes it; the replay tool diffs a logged answer
    against the current code (fakes; nothing written, nothing sent).
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import answer_log, wa_retention  # noqa: E402
from scripts import answer_replay  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

CO_A, CO_B = "co_a", "co_b"
PHONE = "+1 (718) 555-0142"
FULL_DIGITS = "17185550142"

#: A write that is not an insert, on the answer log, however it is named.
_MUTATE = re.compile(
    r"(?:\banswer_log|ANSWER_LOG|['\"]answer_log['\"]\]|answer_log\.COLLECTION\])"
    r"\s*\.\s*(update_one|update_many|replace_one|delete_one|delete_many|"
    r"find_one_and_update|find_one_and_replace|find_one_and_delete|bulk_write|drop)\b")


def _run(coro):
    return asyncio.run(coro)


def _sources():
    files = [BACKEND / "server.py"]
    for d in ("lib", "scripts"):
        files += sorted((BACKEND / d).rglob("*.py"))
    return files


class AppendOnly(unittest.TestCase):
    def test_the_pattern_catches_each_mutation_shape(self):
        """A scan that matches nothing proves nothing: each shape, planted."""
        for planted in ('await db.answer_log.update_one({"_id": x}, {})',
                        'await db["answer_log"].delete_many({})',
                        'await db[answer_log.COLLECTION].replace_one({}, {})',
                        'await db.answer_log.find_one_and_update({}, {})'):
            self.assertIsNotNone(_MUTATE.search(planted), planted)
        self.assertIsNone(_MUTATE.search("await db.answer_log.insert_one(row)"))

    def test_nothing_updates_replaces_or_deletes_a_row(self):
        hits = []
        for f in _sources():
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if _MUTATE.search(line):
                    hits.append(f"{f.relative_to(BACKEND)}:{n}")
        self.assertEqual(hits, [])

    def test_one_insert_and_it_is_in_the_one_writer(self):
        tree = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8"))
        writers = []
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(fn):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr.startswith("insert")
                            and ast.unparse(node.func.value) == "db.answer_log"):
                        writers.append(fn.name)
        self.assertEqual(writers, ["_answer_log_write"])
        # Never reached by name around the attribute form the scan reads.
        for f in _sources():
            text = f.read_text(encoding="utf-8")
            self.assertEqual(re.findall(r"db\[\s*(?:answer_log\.COLLECTION|['\"]answer_log['\"])", text),
                             [], str(f))

    def test_every_answer_site_calls_the_writer(self):
        tree = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8"))
        callers = set()
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(fn):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id == "_answer_log_write"):
                        callers.add((fn.name, ast.literal_eval(node.args[0])))
        self.assertEqual(callers, {("_dm_log_answer", "dm"),
                                   ("_process_whatsapp_message", "group"),
                                   ("search_project_memory", "app")})

    def test_the_group_and_app_sites_keep_their_evidence(self):
        """The group send logs the agent's own tool trace; the app logs its
        date range -- each by keyword at its one call."""
        tree = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8"))
        kw = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_answer_log_write"):
                kw[ast.literal_eval(node.args[0])] = {k.arg for k in node.keywords}
        self.assertTrue("tools" in kw["group"])
        self.assertTrue("params" in kw["app"])

    def test_no_purge_sweeps_it(self):
        self.assertEqual([c for c in wa_retention.COLLECTIONS if c == answer_log.COLLECTION], [])
        self.assertEqual([c for c in server._PROJECT_OWNED_COLLECTIONS
                          if c == answer_log.COLLECTION], [])


class TheRow(unittest.TestCase):
    def _write(self, db, **kw):
        with patch.object(server, "db", db), \
                patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "abc1234"}):
            async def go():
                server._answer_turn_begin()
                server._answer_turn_note(
                    records=[{"_id": "r1", "sheet_number": "A-101", "file_id": "f1",
                              "page_number": 3, "page_id": "p3",
                              "quote": "DOOR   D1  3'-0\" x 7'-0\""}],
                    gate={"gate": "plan_answer_gate", "outcome": "grounded"},
                    model="m-turn")
                return await server._answer_log_write(**kw)
            return _run(go())

    def test_a_dm_row_carries_its_evidence_and_no_phone(self):
        db = FakeDb()
        rid = self._write(
            db, surface="dm", question=f"call {PHONE} about D1",
            final_text=f"D1 is 3'-0\" x 7'-0\" (A-101). Ring {PHONE}.",
            company_id=CO_A, user_id="u1", project_ids="p1",
            tools=[{"tool": "search_plans", "args": {"subject": "door D1"},
                    "result": "- DOOR D1 [A-101]", "round": 1},
                   {"tool": "search_project_history", "args": {"q": "door"},
                    "result": "Mike: the door is late"}],
            gates=[{"gate": "dm_brain", "stop": "stop"}], path="brain")
        row = db.answer_log.rows[0]
        self.assertEqual(row["_id"], rid)
        self.assertEqual(row["surface"], "dm")
        self.assertEqual((row["company_id"], row["user_id"], row["project_ids"]),
                         (CO_A, "u1", ["p1"]))
        self.assertEqual(row["final_text"], "D1 is 3'-0\" x 7'-0\" (A-101). Ring […0142].")
        self.assertEqual(row["records"], [{"id": "r1", "sheet": "A-101", "file_id": "f1",
                                           "page_id": "p3", "page": 3,
                                           "text": "DOOR D1 3'-0\" x 7'-0\""}])
        self.assertEqual(row["tools"][0]["result"], "- DOOR D1 [A-101]")
        self.assertEqual(sorted(row["tools"][1]), ["args", "result_chars", "result_sha256", "tool"])
        self.assertEqual([g["gate"] for g in row["gates"]], ["dm_brain", "plan_answer_gate"])
        self.assertEqual((row["model"], row["code_sha"]), ("m-turn", "abc1234"))
        self.assertEqual(row["content_hash"], answer_log.content_hash(row))
        blob = json.dumps({k: v for k, v in row.items() if k not in ("_id", "content_hash")},
                          default=str)
        self.assertIsNone(re.search(FULL_DIGITS[1:], blob))

    def test_the_turn_is_taken_once(self):
        db = FakeDb()
        with patch.object(server, "db", db):
            async def go():
                server._answer_turn_begin()
                server._answer_turn_note(records=[{"_id": "r1", "quote": "x"}])
                await server._answer_log_write("dm", question="q", final_text="a", company_id=CO_A)
                await server._answer_log_write("dm", question="q2", final_text="b", company_id=CO_A)
            _run(go())
        self.assertEqual([len(r["records"]) for r in db.answer_log.rows], [1, 0])

    def test_a_group_asker_is_the_last_four_only(self):
        db = FakeDb()
        self._write(db, surface="group", question="levelog door D1?", final_text="3'-0\"",
                    company_id=CO_A, project_ids="p1", asker_phone="17185550142",
                    group_id="120363000000000001@g.us", path="group_agent")
        row = db.answer_log.rows[0]
        self.assertEqual((row["asker_last4"], row["user_id"]), ("0142", None))
        self.assertEqual(row["group_id"], "120363000000000001@g.us")

    def test_a_failed_insert_never_raises(self):
        class Broken:
            async def insert_one(self, doc):
                raise RuntimeError("down")
        db = SimpleNamespace(answer_log=Broken())
        with patch.object(server, "db", db):
            self.assertIsNone(_run(server._answer_log_write(
                "dm", question="q", final_text="a", company_id=CO_A)))


class PerCompany(unittest.TestCase):
    def test_reads_are_one_companys(self):
        db = FakeDb(answer_log=[
            {"_id": "a1", "company_id": CO_A, "surface": "dm",
             "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc)},
            {"_id": "a2", "company_id": CO_A, "surface": "group",
             "created_at": datetime(2026, 10, 2, tzinfo=timezone.utc)},
            {"_id": "b1", "company_id": CO_B, "surface": "dm",
             "created_at": datetime(2026, 10, 3, tzinfo=timezone.utc)}])
        with patch.object(server, "db", db):
            self.assertEqual(_run(server._answer_log_get(CO_A, "a1"))["_id"], "a1")
            self.assertIsNone(_run(server._answer_log_get(CO_A, "b1")))
            self.assertIsNone(_run(server._answer_log_get(None, "a1")))
            self.assertIsNone(_run(server._answer_log_get("", "a1")))
            self.assertEqual([r["_id"] for r in _run(server._answer_log_rows(CO_A))], ["a2", "a1"])
            self.assertEqual([r["_id"] for r in _run(server._answer_log_rows(CO_A, surface="dm"))],
                             ["a1"])
            self.assertEqual(_run(server._answer_log_rows(None)), [])


class DmSite(unittest.TestCase):
    def test_a_dm_answer_lands_in_both_logs(self):
        db = FakeDb()
        ident = {"user_id": "u1", "company_id": CO_A}
        with patch.object(server, "db", db):
            async def go():
                server._answer_turn_begin()
                server._answer_turn_note(records=[{"_id": "r9", "sheet_number": "M-201",
                                                   "quote": "RTU-1 5 TON"}])
                await server._dm_log_answer(ident, "p1", "rtu size?", "RTU-1 is 5 ton (M-201).",
                                            "brain", tool_data=[{"tool": "search_plans",
                                                                 "args": {}, "result": "x"}],
                                            model="m1", stop="stop", unverified=None,
                                            verify_retries=0)
            _run(go())
        self.assertEqual(len(db.whatsapp_dm_answers.rows), 1)
        row = db.answer_log.rows[0]
        self.assertEqual((row["surface"], row["path"], row["model"]), ("dm", "brain", "m1"))
        self.assertEqual([r["id"] for r in row["records"]], ["r9"])
        self.assertEqual(row["gates"][0]["gate"], "dm_brain")
        self.assertEqual(row["gates"][0]["stop"], "stop")


def _fake_server(row, *, reply="RTU-1 is 5 ton.", records=()):
    db = FakeDb(whatsapp_optins=[{"user_id": "u1", "status": "active", "chat_id": "c@c.us"}])
    turn: dict = {}

    def begin():
        turn.clear()
        turn.update(records=[], gates=[], model=None)
        return turn

    async def get(company_id, log_id):
        return row if row and row["_id"] == log_id and row["company_id"] == company_id else None

    async def brain(ident, chat, question, **kw):
        assert kw["dry_run"] is True
        turn["records"].extend(records)
        return {"reply": reply, "stop": "stop", "retries": 0, "model": "m2", "sent": []}

    async def ident(chat):
        return {"user_id": "u1", "company_id": CO_A}

    async def route(i):
        return True, "on"

    async def history(chat, at, before=None):
        return []
    return SimpleNamespace(db=db, WA_OPTINS="whatsapp_optins", _answer_log_get=get,
                           _answer_turn_begin=begin, _dm_brain_answer=brain,
                           _dm_assistant_identity=ident, _dm_brain_route=route,
                           _dm_brain_history=history, _dm_gates=server._dm_gates)


class Replay(unittest.TestCase):
    ROW = {"_id": "a1", "company_id": CO_A, "surface": "dm", "user_id": "u1",
           "project_ids": ["p1"], "question": "rtu size?", "final_text": "RTU-1 is 3 ton.",
           "records": [{"id": "r1", "sheet": "M-201", "text": "RTU-1 3 TON"}],
           "gates": server._dm_gates("brain", {"stop": "stop", "verify_retries": 0},
                                     False, "answered"),
           "code_sha": "old", "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc)}

    def test_the_diff_names_text_records_and_gates(self):
        fake = _fake_server(self.ROW, records=[{"_id": "r2", "sheet_number": "M-201",
                                                "quote": "RTU-1 5 TON"}])
        out = _run(answer_replay.replay(fake, CO_A, "a1"))
        d = out["diff"]
        self.assertFalse(d["text_same"])
        self.assertEqual(d["text_diff"].splitlines()[-2:], ["-RTU-1 is 3 ton.", "+RTU-1 is 5 ton."])
        self.assertEqual((d["records_only_logged"], d["records_only_now"]), (["r1"], ["r2"]))
        self.assertEqual(out["now"]["route"], "on")
        text = answer_replay.render(out)
        self.assertEqual(text.splitlines()[2], "DM brain route for this person now: on")

    def test_another_companys_id_is_not_found(self):
        out = _run(answer_replay.replay(_fake_server(self.ROW), CO_B, "a1"))
        self.assertEqual(out, {"found": False, "id": "a1"})
        self.assertEqual(answer_replay.render(out), "answer_log a1: not found for this company.")

    def test_same_answer_reads_same(self):
        row = dict(self.ROW, final_text="RTU-1 is 5 ton.",
                   gates=server._dm_gates("brain", {"stop": "stop", "verify_retries": 0},
                                          False, "answered"))
        row["records"] = [{"id": "r2", "sheet": "M-201", "text": "RTU-1 5 TON"}]
        fake = _fake_server(row, records=[{"_id": "r2", "sheet_number": "M-201",
                                           "quote": "RTU-1 5 TON"}])
        from lib import wa_assistant
        fb, why = wa_assistant.answer_outcome("brain", "RTU-1 is 5 ton.", None)
        row["gates"] = server._dm_gates("brain", {"stop": "stop", "verify_retries": 0}, fb, why)
        d = _run(answer_replay.replay(fake, CO_A, "a1"))["diff"]
        self.assertEqual((d["text_same"], d["records_same"], d["gates_same"]), (True, True, True))

    def test_an_app_replay_asks_the_logged_date_range(self):
        row = {"_id": "a2", "company_id": CO_A, "surface": "app", "project_ids": ["p1"],
               "question": "concrete pour", "final_text": "x",
               "params": {"date_from": "2026-10-01", "date_to": "2026-10-07"}}
        asked = []

        async def memory_answer(cid, pid, q, date_from=None, date_to=None, **k):
            asked.append((cid, pid, q, date_from, date_to))
            return {"text": "x", "sources": [], "claims": []}

        async def get(cid, lid):
            return row if cid == CO_A and lid == "a2" else None
        fake = SimpleNamespace(_answer_log_get=get, _memory_answer=memory_answer,
                               _memory_gates=server._memory_gates)
        _run(answer_replay.replay(fake, CO_A, "a2"))
        self.assertEqual(asked, [(CO_A, "p1", "concrete pour", "2026-10-01", "2026-10-07")])

    def test_a_group_replay_records_the_agents_tools(self):
        row = {"_id": "g1", "company_id": CO_A, "surface": "group", "project_ids": ["p1"],
               "question": "who is on site", "final_text": "3 on site", "group_id": "x@g.us"}

        async def agent(**kw):
            kw["tool_trace"].append({"tool": "who_on_site", "args": {}, "result": "3 on site"})
            return "3 on site"

        async def get(cid, lid):
            return row if cid == CO_A else None
        fake = SimpleNamespace(_answer_log_get=get, _run_group_agent=agent,
                               _answer_turn_begin=server._answer_turn_begin,
                               _default_bot_config=server._default_bot_config)
        out = _run(answer_replay.replay(fake, CO_A, "g1"))
        self.assertEqual([t["tool"] for t in out["now"]["tools"]], ["who_on_site"])

    def test_every_send_path_is_stubbed(self):
        async def real(*a, **k):
            raise AssertionError("sent")
        mod = SimpleNamespace(**{n: real for n in answer_replay.SEND_PATHS},
                              WAAPI_TOKEN="t", WAAPI_INSTANCE_ID="i")
        blocked = answer_replay.silence(mod)
        _run(mod.send_whatsapp_message("c", "hi"))
        _run(mod._waapi_post_raw("u", {}, {}))
        self.assertEqual(blocked, ["send_whatsapp_message", "_waapi_post_raw"])
        self.assertEqual((mod.WAAPI_TOKEN, mod.WAAPI_INSTANCE_ID), ("", ""))


if __name__ == "__main__":
    unittest.main()
