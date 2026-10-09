"""Attention regression fixtures, replayed through the worker in CI.

  tests/fixtures/attention/pass1_2026_10.json        pass 1 (solo, 17 lines)
  tests/fixtures/attention/pass2_2026_10.json        pass 2 (two senders)
  tests/fixtures/attention/state_script_2026_10.json the 25-line state-update
                                                     script + ambiguity cases

Each line carries the label it should get. A line is replayed as a stored
group message (a reply, a file, a serialized id where the fixture says so),
the worker runs, and every label is checked:

  item       a new item: type, due as said, owner (a commitment is its
             sender's), the ask it answers, topic words
  none       no item, no state change quoting it
  state      the item from line `of` (and `also`) moved to `to`, the change
             quoting this line (or its file) -- evidence or silence
  part_done  this sender's part of an ask made of everyone; the ask stays open
  follow_up  a chase on line `of`, not a new item
  flag       for an admin on line `of`; nothing changed
  merged     one message with line `into` (same sender, under a minute)

then each item's final status. The model is scripted (the expected labels,
plus the wrong answers the passes actually got) so what is tested is the code
around it. scripts/attention_fixture_eval.py runs the lines on the real model.
Nothing is ever sent.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from lib import wa_attention as wa  # noqa: E402
from lib import wa_attention_state as was  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from unittest.mock import patch  # noqa: E402
from tests.test_whatsapp_attention import (  # noqa: E402
    ADMIN, ADMIN_B, G_A, PM, T0, _first_sight, _items, _msg, _run, _tick, _world,
)

DIR = Path(__file__).parent / "fixtures" / "attention"
PASS1 = json.loads((DIR / "pass1_2026_10.json").read_text())
PASS2 = json.loads((DIR / "pass2_2026_10.json").read_text())
SCRIPT = json.loads((DIR / "state_script_2026_10.json").read_text())

SENDERS = {k: f"1718555{1000 + i:04d}" for i, k in enumerate("ABCDGP")}


class _ScriptedModel:
    """Answers from the fixture: the expected item for an item line, the
    line's `model` when it says what the model got wrong, `model_if` when the
    answer depends on what the prompt carried."""

    def __init__(self, lines):
        self.lines = lines
        self.calls = []

    def _answer(self, ln, prompt):
        if "model_if" in ln:
            cond = ln["model_if"]
            ok = all(p in prompt for p in cond["prompt_has"])
            return cond["then"] if ok else cond["else"]
        if "model" in ln:
            return ln["model"]
        e = ln["expect"]
        if e["kind"] != "item":
            return []
        return [{"type": e["type"], "quote": e.get("quote") or ln["body"],
                 "summary": ln["body"][:60], "owner_text": e.get("owner_text"),
                 "due_text": e.get("due_text"), "importance": "high", "tags": []}]

    async def __call__(self, messages):
        prompt = messages[-1]["content"]
        target = prompt.split(">>> ", 1)[1].split(": ", 1)[1]
        self.calls.append(target)
        for ln in self.lines:
            if (ln.get("model_match") or ln["body"]) == target:
                items = [{"summary": "", "owner_text": None, "due_text": None,
                          "importance": "normal", "tags": [], **it}
                         for it in self._answer(ln, prompt)]
                return {"content": json.dumps({"items": items}),
                        "prompt_tokens": 1500, "completion_tokens": 150}
        return {"content": json.dumps({"items": []}),
                "prompt_tokens": 1200, "completion_tokens": 10}


def replay(lines):
    """All lines through the worker in one run, as they were sent."""
    db = _world()
    _first_sight(db)
    rows = {}
    for ln in lines:
        at = T0 + timedelta(seconds=ln["at"] if "at" in ln else ln["n"] * 60)
        mid = f"3EB0{ln['n']:04d}{id(lines) % 10000:04d}"
        kw = {"message_id": (f"false_{G_A}_{mid}_{SENDERS[ln['from']]}@c.us"
                             if ln.get("serialized_id") else mid),
              "timestamp": at}
        if ln.get("reply_to"):
            q = lines[ln["reply_to"] - 1]
            kw["quoted_message_id"] = was.short_id(rows[q["n"]]["message_id"])
            kw["quoted_author"] = SENDERS[q["from"]] + "@c.us"
        if ln.get("file"):
            kw["media_type"] = "document"
            kw["file_name"] = ln["file"]
        rows[ln["n"]] = _msg(db, ln["body"], sender=SENDERS[ln["from"]], at=at, **kw)
    model = _ScriptedModel(lines)
    last = max(r["created_at"] for r in rows.values())
    report, sends = _tick(db, model, last + timedelta(minutes=5))
    return {"db": db, "rows": rows, "model": model, "report": report,
            "sends": sends, "items": list(_items(db))}


class _FixtureChecks:
    """The checks every fixture gets. Subclasses set LINES and FINAL."""

    LINES: list = []
    FINAL: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.out = replay(cls.LINES)
        cls.items = cls.out["items"]
        cls.by_msg = {it["evidence"]["message_id"]: it for it in cls.items}

    def _item_of(self, n):
        it = self.by_msg.get(self.out["rows"][n]["message_id"])
        self.assertIsNotNone(it, f"no item from line {n}")
        return it

    def _events_quoting(self, n):
        row = self.out["rows"][n]
        return [(it, e) for it in self.items for e in it.get("history") or []
                if e.get("message_id") == row["message_id"] and e["kind"] != "created"]

    def _quote_of(self, ln):
        return ln["expect"].get("evidence") or ln["body"]

    def test_nothing_is_sent(self):
        self.assertEqual(self.out["sends"], [])

    def test_every_line(self):
        lines = {ln["n"]: ln for ln in self.LINES}
        for n, ln in lines.items():
            e = ln["expect"]
            with self.subTest(line=n, body=ln["body"]):
                kind = e["kind"]
                if kind == "item":
                    it = self._item_of(n)
                    self.assertEqual(it["type"], e["type"])
                    # As said when it was made (a later reschedule moves `due`).
                    self.assertEqual(it["history"][0]["due_to"], e.get("due_text"))
                    if e.get("owner"):
                        self.assertEqual(it["evidence"]["sender"], SENDERS[e["owner"]])
                    if e.get("owner_text"):
                        self.assertEqual(it["owner"]["owner_text"], e["owner_text"])
                    if e.get("links"):
                        self.assertEqual(it["parent_id"], str(self._item_of(e["links"])["_id"]))
                    for w in e.get("topic_has") or []:
                        self.assertIn(w, it["topic"])
                    if e.get("quote"):
                        self.assertEqual(it["evidence"]["quote"], e["quote"])
                    self.assertEqual(it["importance"], e.get("importance", "normal"))
                elif kind == "none":
                    self.assertNotIn(self.out["rows"][n]["message_id"], self.by_msg)
                    self.assertEqual(self._events_quoting(n), [])
                elif kind == "merged":
                    self.assertNotIn(self.out["rows"][n]["message_id"], self.by_msg)
                    into = self._item_of(e["into"])
                    self.assertIn(self.out["rows"][n]["message_id"],
                                  into["evidence"]["merged_ids"])
                else:
                    self.assertNotIn(self.out["rows"][n]["message_id"], self.by_msg,
                                     "an update is not a new item")
                    targets = [e["of"]] + list(e.get("also") or [])
                    for t in targets:
                        it = self._item_of(t)
                        evs = [ev for ev in it["history"]
                               if ev.get("message_id") == self.out["rows"][n]["message_id"]]
                        self.assertEqual(len(evs), 1, f"line {t} has no event from line {n}")
                        ev = evs[0]
                        # EVIDENCE OR SILENCE: the words (or the file) that did it.
                        self.assertEqual(ev["quote"], self._quote_of(ln))
                        self.assertTrue(ev["verified"])
                        self.assertIsNone(ev["review"])
                        if kind == "state":
                            self.assertEqual((ev["kind"], ev["to"]), ("state", e["to"]))
                        else:
                            self.assertEqual(ev["kind"], kind)
                        if e.get("note"):
                            self.assertEqual(ev.get("note"), e["note"])
                    if kind == "state" and e["to"] == "rescheduled":
                        it = self._item_of(e["of"])
                        rs = [h for h in it["history"] if h.get("to") == "rescheduled"][0]
                        self.assertEqual(rs["due_to"], e["due_text"])
                        self.assertIsNotNone(rs["due_from"], "the old date is kept")
                        self.assertEqual(it["due"]["due_text"], e["due_text"])
                        self.assertEqual(it["due"]["due_at"], rs["due_to_at"])
                    if kind == "part_done":
                        self.assertEqual(self._item_of(e["of"])["status"], "open")
                    if kind == "flag":
                        self.assertTrue(self._item_of(e["of"]).get("needs_review"))

    def test_final_states(self):
        for n, status in self.FINAL.items():
            with self.subTest(line=n):
                self.assertEqual(self._item_of(int(n))["status"], status)

    def test_no_item_from_a_line_without_one(self):
        want = {self.out["rows"][ln["n"]]["message_id"] for ln in self.LINES
                if ln["expect"]["kind"] == "item"}
        self.assertEqual(set(self.by_msg), want)

    def test_never_high_without_stated_urgency(self):
        for it in self.items:
            self.assertEqual(it["importance"], "normal", it["evidence"]["quote"])


class Pass1(_FixtureChecks, unittest.TestCase):
    LINES, FINAL = PASS1["lines"], PASS1["final"]

    def test_the_inspection_line_is_not_an_issue(self):
        self.assertEqual(self.out["report"]["dropped_not_issue"], 1)

    def test_the_lines_pass_1_lost_reach_the_worker(self):
        # Pass 1 never read lines 12, 14 and 17 (the cheap filter).
        for n in (12, 14, 17):
            self.assertIn(self.LINES[n - 1]["body"], self.out["model"].calls)


class Pass2(_FixtureChecks, unittest.TestCase):
    LINES, FINAL = PASS2["lines"], PASS2["final"]

    def test_the_reply_defines_the_topic(self):
        it = self._item_of(2)
        self.assertEqual(it["summary"], "Sleeve layout by Friday")
        self.assertNotIn("caulk", it["topic"])

    def test_two_take_care_of_it_messages_are_two_items(self):
        # "Gonna take care of it Friday" and "I'll take care of it" are not
        # one item for sharing "take care".
        self.assertEqual(self.out["report"]["deduped"], 0)

    def test_np_tomorrow_is_one_model_call(self):
        self.assertIn("Np\nTomorrow", self.out["model"].calls)
        self.assertNotIn("Np", self.out["model"].calls)
        self.assertNotIn("Tomorrow", self.out["model"].calls)


class StateScript(_FixtureChecks, unittest.TestCase):
    LINES, FINAL = SCRIPT["lines"], SCRIPT["final"]

    def test_reschedule_keeps_the_history(self):
        it = self._item_of(2)
        kinds = [(h["kind"], h["to"]) for h in it["history"]]
        self.assertEqual(kinds, [("created", "open"), ("state", "rescheduled"),
                                 ("follow_up", None), ("state", "done")])
        rs = it["history"][1]
        self.assertEqual((rs["due_from"], rs["due_to"]), ("tomorrow morning", "Monday"))
        self.assertEqual(it["due"]["due_text"], "Monday")

    def test_certs_part(self):
        it = self._item_of(22)
        self.assertEqual([p["sender"] for p in it["parts_done"]], [SENDERS["C"]])


def _scenario(i):
    sc = SCRIPT["scenarios"][i]
    return type(f"Scenario{i + 1}", (_FixtureChecks, unittest.TestCase),
                {"LINES": sc["lines"], "FINAL": sc["final"], "__doc__": sc["name"]})


Scenario1 = _scenario(0)
Scenario2 = _scenario(1)
Scenario3 = _scenario(2)


class TheRules(unittest.TestCase):
    """The pure checks the fixtures rest on."""

    def test_every_line_with_something_to_record_reaches_the_model(self):
        for ln in PASS1["lines"] + SCRIPT["lines"]:
            if ln["expect"]["kind"] in ("item",) and ln["body"]:
                self.assertIsNotNone(wa.filter_reason({"body": ln["body"]}), ln["body"])

    def test_noise_costs_nothing(self):
        for body in ("Great, another rain day, love this job",
                     "Why does this always happen to us", "Thanks guys"):
            self.assertIsNone(wa.filter_reason({"body": body}), body)

    def test_severity_only_as_stated(self):
        for ln in PASS1["lines"] + PASS2["lines"] + SCRIPT["lines"]:
            self.assertEqual(wa.importance("high", ln["body"])["importance"], "normal",
                             ln["body"])
        self.assertEqual(wa.importance("normal", "URGENT need the lift now")["importance"],
                         "high")

    def test_nothing_in_the_scripts_is_a_problem(self):
        for ln in PASS1["lines"] + PASS2["lines"] + SCRIPT["lines"]:
            self.assertFalse(wa.names_a_problem(ln["body"]), ln["body"])

    def test_due_dates_the_code_reads(self):
        sent = T0                                   # Thursday Oct 8, 10 AM ET
        self.assertEqual(wa.parse_due("by tomorrow", sent), date(2026, 10, 9))
        self.assertEqual(wa.parse_due("by Friday EOD", sent), date(2026, 10, 9))
        self.assertEqual(wa.parse_due("7am Thursday", sent), date(2026, 10, 15))
        self.assertEqual(wa.parse_due("by the 15th", sent), date(2026, 10, 15))
        self.assertIsNone(wa.parse_due("later", sent))

    def test_what_an_update_says(self):
        cases = {
            "Sent this morning": "done", "Sent mine": "done", "done": "done",
            "Never mind the load calcs, owner changed scope": "cancel",
            "Actually risers will be Monday, engineer is out": "reschedule",
            "Wednesday is not happening. Gonna take care of it Friday": "reschedule",
            "I'll send them tomorrow morning": None, "Will do": None,
            "is it done?": None, "I'll have it done by Friday": None,
            "I have them, sending now": None,
        }
        for body, kind in cases.items():
            got = was.classify(body)
            self.assertEqual(got and got["kind"], kind, body)
        self.assertEqual(was.classify("", has_file=True)["kind"], "done")
        self.assertEqual(was.classify("Wednesday is not happening. Gonna take care of it "
                                      "Friday")["due_text"], "Friday")

    def test_serialized_ids_match_the_short_one(self):
        self.assertEqual(was.short_id(f"false_{G_A}_3EB0ABC_17185550101@c.us"), "3EB0ABC")
        self.assertEqual(was.short_id("3EB0ABC"), "3EB0ABC")


class TheWorkerKeepsUp(unittest.TestCase):

    def test_it_runs_every_minute(self):
        self.assertEqual(server.ATTENTION_TICK_SECONDS, 60)

    def test_a_burst_still_being_typed_waits_one_run(self):
        db = _world()
        _first_sight(db)
        at = T0 + timedelta(hours=1)
        _msg(db, "Np", at=at)
        model = _ScriptedModel([])
        report, _ = _tick(db, model, at + timedelta(seconds=30))
        self.assertEqual((report["held"], model.calls), (1, []))
        _msg(db, "Tomorrow", at=at + timedelta(seconds=40))
        _tick(db, model, at + timedelta(seconds=150))
        self.assertEqual(model.calls, ["Np\nTomorrow"])

    def test_the_run_reports_its_lag(self):
        run = replay(PASS2["lines"])
        self.assertIn("max_lag_seconds", run["report"])
        self.assertIn("held", run["report"])



class TheTimelineOnTheReviewScreen(unittest.TestCase):
    """Each state change is shown with its words and marked Correct / Wrong
    on its own."""

    @classmethod
    def setUpClass(cls):
        cls.out = replay(SCRIPT["lines"])
        cls.db = cls.out["db"]
        cls.riser = next(it for it in cls.out["items"]
                         if it["evidence"]["quote"] == "Yeah I'll send them tomorrow morning")

    def _get(self, status="open", user=ADMIN):
        with patch.object(server, "db", self.db):
            return _run(server.get_project_attention("proj_a", status=status,
                                                     current_user=user))

    def _review(self, event_id, verdict, user=ADMIN, item=None):
        with patch.object(server, "db", self.db):
            return _run(server.review_project_attention_event(
                "proj_a", str((item or self.riser)["_id"]), event_id,
                {"verdict": verdict}, current_user=user))

    def test_closed_items_and_their_timeline(self):
        out = self._get("closed")
        v = next(i for i in out["items"] if i["quote"] == "Yeah I'll send them tomorrow morning")
        self.assertEqual([(h["kind"], h["to"]) for h in v["history"]],
                         [("created", "open"), ("state", "rescheduled"),
                          ("follow_up", None), ("state", "done")])
        rs = v["history"][1]
        self.assertEqual((rs["quote"], rs["due_from"], rs["due_to"], rs["link"]),
                         ("Actually risers will be Monday, engineer is out",
                          "tomorrow morning", "Monday", "owner_topic"))
        self.assertNotIn(SENDERS["B"], json.dumps(v))
        open_quotes = {i["quote"] for i in self._get("open")["items"]}
        self.assertNotIn("Yeah I'll send them tomorrow morning", open_quotes)
        self.assertIn("Everyone send insurance certs by the 15th", open_quotes)

    def test_correct_and_wrong_per_change(self):
        ev = self.riser["history"]
        v = self._review(ev[1]["id"], "correct")
        self.assertEqual(v["history"][1]["verdict"], "correct")
        v = self._review(ev[3]["id"], "wrong")
        self.assertEqual([h["verdict"] for h in v["history"]],
                         [None, "correct", None, "wrong"])
        sp = self._get("all")["state_precision"]
        self.assertEqual((sp["rescheduled"]["correct"], sp["done"]["wrong"]), (1, 1))
        # A verdict records; it does not undo the change.
        self.assertEqual(v["status"], "done")

    def test_refusals(self):
        ev = self.riser["history"]
        for user, code in ((PM, 403), (ADMIN_B, 404)):
            with self.assertRaises(HTTPException) as e:
                self._review(ev[1]["id"], "correct", user=user)
            self.assertEqual(e.exception.status_code, code)
        for event_id, verdict, code in ((ev[1]["id"], "dismissed", 422),
                                        (ev[0]["id"], "correct", 404),   # creation
                                        ("nope", "correct", 404)):
            with self.assertRaises(HTTPException) as e:
                self._review(event_id, verdict)
            self.assertEqual(e.exception.status_code, code)



class ReviewFindings(unittest.TestCase):
    """Codex review of #709."""

    def _world_with(self, lines):
        out = replay(lines)
        return out["db"], {it["evidence"]["quote"]: it for it in out["items"]}

    def test_an_update_and_a_new_ask_in_one_message(self):
        lines = [
            {"n": 1, "from": "D", "body": "C, need the load calcs by Friday",
             "expect": {"kind": "item", "type": "request", "due_text": "by Friday"}},
            {"n": 2, "from": "D",
             "body": "Never mind the load calcs; send the revised schedule by Friday",
             "expect": {"kind": "none"},
             "model": [{"type": "request", "quote": "send the revised schedule by Friday",
                        "summary": "Send revised schedule", "due_text": "by Friday"},
                       {"type": "request", "quote": "Never mind the load calcs",
                        "summary": "Load calcs no longer needed"}]},
        ]
        db, items = self._world_with(lines)
        self.assertEqual(items["C, need the load calcs by Friday"]["status"], "cancelled")
        self.assertIn("send the revised schedule by Friday", items)        # kept
        self.assertNotIn("Never mind the load calcs", items)                # the update itself

    def test_a_failed_state_write_is_retried_once(self):
        lines = [
            {"n": 1, "from": "A", "body": "B, can you send the riser dimensions by Friday?",
             "expect": {"kind": "item", "type": "request", "due_text": "by Friday"}},
            {"n": 2, "from": "B", "body": "I'll send the riser dimensions Friday",
             "expect": {"kind": "item", "type": "commitment", "due_text": "Friday"}},
        ]
        out = replay(lines)
        db = out["db"]
        at = T0 + timedelta(hours=1)
        _msg(db, "Actually risers will be Monday", sender=SENDERS["B"], at=at,
             message_id="RESCHED1")
        col = db[server.ATTENTION_ITEMS]
        real = col.update_one
        calls = {"n": 0}

        async def flaky(q, u, **k):
            if "$push" in u and calls["n"] == 0:
                calls["n"] += 1
                raise RuntimeError("mongo down")
            return await real(q, u, **k)

        model = _ScriptedModel(lines)
        with patch.object(col, "update_one", flaky):
            report, _ = _tick(db, model, at + timedelta(minutes=5))
        self.assertEqual(report["write_failed"], 1)
        _tick(db, model, at + timedelta(minutes=6))       # the retry
        it = next(i for i in _items(db) if i["type"] == "commitment")
        moves = [h for h in it["history"] if h.get("message_id") == "RESCHED1"]
        self.assertEqual(len(moves), 1)
        self.assertEqual((it["status"], it["due"]["due_text"]), ("rescheduled", "Monday"))

    def test_an_issue_in_other_words_is_kept(self):
        self.assertFalse(wa.is_schedule_update("Inspection found exposed live wires"))
        self.assertTrue(wa.is_schedule_update("Inspection moved to Tuesday 10am"))
        self.assertFalse(wa.is_schedule_update("Pour pushed to Friday, pump broke"))
        lines = [{"n": 1, "from": "A", "body": "Inspection found exposed live wires",
                  "expect": {"kind": "item", "type": "issue"}}]
        _, items = self._world_with(lines)
        self.assertEqual(items["Inspection found exposed live wires"]["type"], "issue")

    def test_a_review_never_loses_an_entry_the_worker_adds_meanwhile(self):
        out = replay(SCRIPT["lines"])
        db = out["db"]
        col = db[server.ATTENTION_ITEMS]
        it = next(i for i in out["items"]
                  if i["evidence"]["quote"] == "Yeah I'll send them tomorrow morning")
        real = col.find_one
        late = {"id": "late01", "kind": "flag", "to": None, "review": None}

        async def read_then_worker_appends(q, *a, **k):
            doc = await real(q, *a, **k)
            stored = next(r for r in col.rows if r["_id"] == it["_id"])
            if late not in stored["history"]:
                stored["history"].append(dict(late))  # the worker, between read and write
            return doc

        with patch.object(server, "db", db), \
                patch.object(col, "find_one", read_then_worker_appends):
            _run(server.review_project_attention_event(
                "proj_a", str(it["_id"]), it["history"][1]["id"], {"verdict": "correct"},
                current_user=ADMIN))
        stored = next(r for r in col.rows if r["_id"] == it["_id"])
        self.assertIn("late01", [h["id"] for h in stored["history"]])
        self.assertEqual(stored["history"][1]["review"]["verdict"], "correct")


if __name__ == "__main__":
    unittest.main()
