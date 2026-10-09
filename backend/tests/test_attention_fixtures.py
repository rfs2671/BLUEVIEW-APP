"""Attention regression fixtures, replayed through the worker in CI.

  tests/fixtures/attention/pass1_2026_10.json        pass 1 (solo, 17 lines)
  tests/fixtures/attention/pass2_2026_10.json        pass 2 (two senders)
  tests/fixtures/attention/state_script_2026_10.json the 25-line state-update
                                                     script + ambiguity cases
  tests/fixtures/attention/chase_weekend_2026_10.json the weekend chase script,
                                                     then the chase worker

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
  review     an unclear update: ONE review entry naming the items `of`;
             none of them changed

then each item's final status. The model is scripted (the expected labels,
plus the wrong answers the passes actually got) so what is tested is the code
around it. scripts/attention_fixture_eval.py runs the lines on the real model.
Nothing is ever sent.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from lib import wa_attention as wa  # noqa: E402
from lib import wa_attention_state as was  # noqa: E402
from lib import wa_chase  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from unittest.mock import patch  # noqa: E402
from tests.test_whatsapp_attention import (  # noqa: E402
    ADMIN, ADMIN_B, G_A, PM, T0, _first_sight, _items, _msg, _run, _tick, _world,
)

DIR = Path(__file__).parent / "fixtures" / "attention"
PASS1 = json.loads((DIR / "pass1_2026_10.json").read_text())
PASS2 = json.loads((DIR / "pass2_2026_10.json").read_text())
SCRIPT = json.loads((DIR / "state_script_2026_10.json").read_text())
CHASE = json.loads((DIR / "chase_weekend_2026_10.json").read_text(encoding="utf-8"))

SENDERS = {k: f"1718555{1000 + i:04d}" for i, k in enumerate("ABCDGPR")}


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


def replay(lines, base=T0, users=None, people=None):
    """All lines through the worker in one run, as they were sent. `users`:
    speakers who are Levelog users of the company ({key: {name, role}}).
    `people`: speakers mapped in Project → WhatsApp → People
    ({key: {person_name, sub_company}})."""
    db = _world()
    for k, u in (users or {}).items():
        db.users.rows.append({"_id": f"u_{k.lower()}", "company_id": "co_a",
                              "phone": SENDERS[k], **u})
    for k, p in (people or {}).items():
        db.whatsapp_sender_map.rows.append({"_id": f"sm_{k.lower()}", "company_id": "co_a",
                                            "sender_jid": SENDERS[k] + "@c.us", **p})
    _first_sight(db)
    rows = {}
    for ln in lines:
        at = base + timedelta(seconds=ln["at"] if "at" in ln else ln["n"] * 60)
        mid = f"3EB0{ln['n']:04d}{id(lines) % 10000:04d}"
        kw = {"message_id": (f"false_{G_A}_{mid}_{SENDERS[ln['from']]}@c.us"
                             if ln.get("serialized_id") else mid),
              "timestamp": at}
        if ln.get("reply_to"):
            q = lines[ln["reply_to"] - 1]
            kw["quoted_message_id"] = was.short_id(rows[q["n"]]["message_id"])
            kw["quoted_author"] = SENDERS[q["from"]] + "@c.us"
        if ln.get("name"):
            kw["sender_name"] = ln["name"]
        if ln.get("mentions"):
            kw["mentioned_jids"] = [SENDERS[m] + "@c.us" for m in ln["mentions"]]
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
    OWNER_NONE: list = []
    BASE = T0
    USERS: dict = {}
    PEOPLE: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.out = replay(cls.LINES, cls.BASE, cls.USERS, cls.PEOPLE)
        cls.reviews = [it for it in cls.out["items"] if it["type"] == "update_review"]
        cls.items = [it for it in cls.out["items"] if it["type"] != "update_review"]
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
                    if e.get("owner") and it["type"] == "commitment":
                        # A commitment is its sender's.
                        self.assertEqual(it["evidence"]["sender"], SENDERS[e["owner"]])
                    elif e.get("owner"):
                        # An ask is the person it was put to: named by
                        # @mention, or whoever took it on.
                        self.assertEqual(str(it["owner"].get("jid") or "").split("@")[0],
                                         SENDERS[e["owner"]])
                    if "owner_possibly" in e:
                        self.assertEqual(bool(it["owner"].get("possibly")), e["owner_possibly"])
                    if e.get("due_from"):
                        self.assertEqual(it["history"][0]["due_source"], e["due_from"])
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
                elif kind == "review":
                    # An unclear update: ONE review entry naming the items
                    # it could be about; none of them changed.
                    mid = self.out["rows"][n]["message_id"]
                    revs = [r for r in self.reviews if r["evidence"]["message_id"] == mid]
                    self.assertEqual(len(revs), 1)
                    self.assertEqual(revs[0]["update_kind"], e["update"])
                    self.assertEqual(sorted(c["id"] for c in revs[0]["candidates"]),
                                     sorted(str(self._item_of(t)["_id"]) for t in e["of"]))
                    self.assertEqual(revs[0]["evidence"]["quote"], self._quote_of(ln))
                    self.assertEqual(self._events_quoting(n), [])
                    self.assertNotIn(mid, self.by_msg)
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
        for n in self.OWNER_NONE:
            with self.subTest(owner_of=n):
                self.assertFalse(self._item_of(n)["owner"].get("jid"))

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
        # "Sure you got it" is an ack: its topic is the ask it replies to.
        it = self._item_of(2)
        self.assertTrue(it["summary"].startswith("Will do: "))
        self.assertIn("sleeve", it["summary"])
        self.assertNotIn("caulk", it["topic"])

    def test_wednesday_is_not_happening_moves_the_sleeve_commitment(self):
        it = self._item_of(2)
        rs = [h for h in it["history"] if h.get("to") == "rescheduled"][0]
        self.assertEqual((rs["due_from"], rs["due_to"], rs["link"]),
                         ("by Wednesday", "Friday", "reply"))
        # ... and is not a second sleeve commitment.
        sleeves = [i for i in self.items if i["type"] == "commitment" and "sleeve" in i["topic"]]
        self.assertEqual(len(sleeves), 1)
        self.assertEqual(self.out["report"]["restated_update"], 1)

    def test_the_meter_ask_is_possibly_hers(self):
        # Named nobody; "Np / Tomorrow" came right after: possibly hers,
        # for an admin to confirm.
        it = self._item_of(7)
        self.assertEqual((it["owner"]["source"], it["owner"]["possibly"]), ("committed", True))
        self.assertTrue(it["needs_review"])
        flag = [h for h in it["history"] if h["kind"] == "flag"]
        self.assertEqual((flag[0]["note"], flag[0]["quote"]), ("possible_owner", "Np\nTomorrow"))
        # The sleeve ask named her: confirmed, no flag.
        self.assertFalse(self._item_of(1)["owner"].get("possibly"))

    def test_a_failed_owner_write_is_retried(self):
        lines = [
            {"n": 1, "from": "R", "body": "Can you confirm the water meter location with the engineer?",
             "expect": {"kind": "item", "type": "request"}},
            {"n": 2, "from": "P", "body": "I'll confirm the water meter location tomorrow",
             "expect": {"kind": "item", "type": "commitment", "due_text": "tomorrow", "links": 1}},
        ]
        db = _world()
        _first_sight(db)
        for ln in lines:
            _msg(db, ln["body"], sender=SENDERS[ln["from"]],
                 at=T0 + timedelta(minutes=ln["n"]), message_id=f"OWN{ln['n']}")
        col = db[server.ATTENTION_ITEMS]
        real = col.update_one
        failed = []

        async def flaky(q, u, **k):
            if "owner.jid" in q and not failed:
                failed.append(1)
                raise RuntimeError("mongo down")
            return await real(q, u, **k)

        model = _ScriptedModel(lines)
        with patch.object(col, "update_one", flaky):
            report, _ = _tick(db, model, T0 + timedelta(minutes=10))
        self.assertEqual(report["write_failed"], 1)
        req = next(i for i in _items(db) if i["type"] == "request")
        self.assertIsNone(req["owner"].get("jid"))           # not yet
        _tick(db, model, T0 + timedelta(minutes=11))          # the retry
        req = next(i for i in _items(db) if i["type"] == "request")
        self.assertEqual((req["owner"]["jid"], req["owner"]["source"]),
                         (SENDERS["P"] + "@c.us", "committed"))
        self.assertEqual(len([i for i in _items(db) if i["type"] == "commitment"]), 1)

    def test_a_named_owner_is_never_replaced_by_who_answers(self):
        lines = [
            {"n": 1, "from": "R", "mentions": ["P"], "body": "@Patricia can you send the riser layout?",
             "expect": {"kind": "item", "type": "request", "owner": "P"}},
            {"n": 2, "from": "B", "body": "I'll send the riser layout tomorrow",
             "expect": {"kind": "item", "type": "commitment", "owner": "B", "due_text": "tomorrow",
                        "links": 1}},
        ]
        out = replay(lines)
        req = next(i for i in out["items"] if i["type"] == "request")
        self.assertEqual(req["owner"]["jid"], SENDERS["P"] + "@c.us")
        self.assertEqual(req["owner"]["source"], "mention")

    def test_dont_forget_is_not_a_cancel(self):
        for body in ("Don't forget the meter", "I always forget the meter",
                     "Please don't ever forget the meter", "dont forget the permits"):
            self.assertIsNone(was.classify(body), body)
        for body in ("Ok forget it", "Thanks. Forget about the riser layout"):
            self.assertEqual(was.classify(body)["kind"], "cancel", body)
        self.assertEqual(was.classify(self.LINES[9]["body"])["kind"], "cancel")

    def test_two_take_care_of_it_messages_are_two_items(self):
        # "Gonna take care of it Friday" and "I'll take care of it" are not
        # one item for sharing "take care".
        self.assertEqual(self.out["report"]["deduped"], 0)

    def test_np_tomorrow_is_one_commitment_read_by_code(self):
        # One message, and an ack: no model call at all.
        for body in ("Np\nTomorrow", "Np", "Tomorrow", "Sure you got it", "👍"):
            self.assertNotIn(body, self.out["model"].calls)
        self.assertEqual(self.out["report"]["acks"], 2)
        self.assertEqual(self.out["report"]["ack_unaddressed"], 1)    # the 👍


class StateScript(_FixtureChecks, unittest.TestCase):
    LINES, FINAL = SCRIPT["lines"], SCRIPT["final"]

    def test_reschedule_keeps_the_history(self):
        it = self._item_of(2)
        kinds = [(h["kind"], h["to"]) for h in it["history"]]
        # Said right after an ask that named nobody, its subject only that
        # ask's ("them"): possibly B's, flagged (as the ask is).
        self.assertEqual(kinds, [("created", "open"), ("flag", "open"), ("state", "rescheduled"),
                                 ("follow_up", None), ("state", "done")])
        self.assertEqual(it["history"][1]["note"], "possible_subject")
        rs = it["history"][2]
        self.assertEqual((rs["due_from"], rs["due_to"]), ("tomorrow morning", "Monday"))
        self.assertEqual(it["due"]["due_text"], "Monday")

    def test_certs_part(self):
        it = self._item_of(22)
        self.assertEqual([p["sender"] for p in it["parts_done"]], [SENDERS["C"]])


def _scenario(i):
    sc = SCRIPT["scenarios"][i]
    return type(f"Scenario{i + 1}", (_FixtureChecks, unittest.TestCase),
                {"LINES": sc["lines"], "FINAL": sc["final"],
                 "OWNER_NONE": sc.get("owner_none") or [], "__doc__": sc["name"]})


Scenario1 = _scenario(0)
Scenario2 = _scenario(1)
Scenario3 = _scenario(2)
Scenario4 = _scenario(3)


class ChaseWeekend(_FixtureChecks, unittest.TestCase):
    """Fri 3:25-3:43 PM, then the chase worker on Saturday, Sunday and
    Monday (588 Thomas has Chase on weekends on). Only the sleeve shop
    drawings are chased; nothing is sent."""

    LINES, FINAL, USERS = CHASE["lines"], CHASE["final"], CHASE["users"]
    PEOPLE = CHASE["people"]          # Patricia is a sub: GC staff are never chased
    BASE = datetime.fromisoformat(CHASE["base"])

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db = cls.out["db"]
        db.notification_preferences.rows.append({
            "_id": "np_chase", "user_id": None, "project_id": "proj_a", "scope": "project",
            "whatsapp_project": {"chase_weekends": CHASE["chase"]["chase_weekends"]}})
        sent = []

        async def no_send(*a, **k):
            sent.append((a, k))
        cls.chase_rows = {}
        with patch.object(server, "db", db), \
                patch.object(server, "send_whatsapp_message", no_send), \
                patch.object(server, "send_whatsapp_dm", no_send):
            for name in ("saturday", "sunday", "monday"):
                d = date.fromisoformat(CHASE["chase"][name]["date"])
                before = len(db[wa_chase.COLLECTION].rows)
                for slot, at in wa_chase.SLOTS:
                    local = datetime.combine(d, at).replace(tzinfo=wa_chase._ET)
                    _run(server._chase_tick((local + timedelta(minutes=5)).astimezone(timezone.utc)))
                cls.chase_rows[name] = db[wa_chase.COLLECTION].rows[before:]
        cls.chase_sends = sent

    def _chased(self, name):
        ids = {i for r in self.chase_rows[name] for i in r["item_ids"]}
        return sorted(n for n in self.out["rows"]
                      if str((self.by_msg.get(self.out["rows"][n]["message_id"]) or {}).get("_id")) in ids)

    def test_saturday_only_the_sleeve_shop_drawings(self):
        want = CHASE["chase"]["saturday"]
        self.assertEqual(self._chased("saturday"), want["items"])
        self.assertEqual([r["slot"] for r in self.chase_rows["saturday"]], want["slots"])
        first = self.chase_rows["saturday"][0]
        self.assertEqual(first["text"], "@Patricia Lee morning — this is due today:\n"
                                        "“I'll also send the sleeve shop drawings Saturday morning”")

    def test_sunday_and_monday_nothing(self):
        for name in ("sunday", "monday"):
            self.assertEqual(self._chased(name), CHASE["chase"][name]["items"], name)

    def test_the_possible_owner_items_are_flagged_not_chased(self):
        for n in (3, 4, 5, 6):
            it = self._item_of(n)
            self.assertTrue(it["owner"].get("possibly"), n)
            self.assertTrue(it.get("needs_review"), n)
        notes = [h.get("note") for h in self._item_of(4)["history"] if h["kind"] == "flag"]
        self.assertEqual(notes, ["possible_subject"])

    def test_a_time_only_due_takes_the_asks_day_and_keeps_it(self):
        it = self._item_of(2)
        self.assertEqual(it["history"][0]["due_source"], "parent_day")
        rs = [h for h in it["history"] if h.get("to") == "rescheduled"][0]
        self.assertEqual((rs["due_from"], rs["due_to"], rs["due_to_at"]),
                         ("before 8am", "till 11-12", "2026-10-10"))

    def test_a_reply_or_update_is_never_merged(self):
        # 3:39:40 / 3:40:05 / 3:40:50, all Patricia: three messages, each
        # recorded under its own id.
        self.assertEqual(self._item_of(6)["evidence"]["message_id"], self.out["rows"][6]["message_id"])
        self.assertEqual(self._item_of(8)["evidence"]["message_id"], self.out["rows"][8]["message_id"])
        self.assertEqual(len([h for h in self._item_of(2)["history"]
                              if h.get("message_id") == self.out["rows"][7]["message_id"]]), 1)
        merged = [it for it in self.items if it["evidence"].get("merged_ids")]
        self.assertEqual([it["evidence"]["quote"] for it in merged], ["I\nKk"])
        # The reply moved the hardware, not the scaffold said just before it.
        self.assertEqual(self._item_of(6)["due"]["due_text"], "Monday")

    def test_nothing_is_sent_by_the_chase(self):
        self.assertEqual(self.chase_sends, [])


class NamesAndDates(unittest.TestCase):
    """An ask opening with a name; a due date outside the quoted part."""

    USERS = {"R": {"name": "Roy Admin", "role": "admin"},
             "P": {"name": "Patricia Lee", "role": "pm"}}

    def _two(self, ask):
        lines = [
            {"n": 1, "from": "R", "body": ask,
             "expect": {"kind": "item", "type": "request", "due_text": "by Saturday"}},
            # The model quotes only part of it and gives no date.
            {"n": 2, "from": "P", "body": "Sunday. I'll keep u posted",
             "model": [{"type": "commitment", "quote": "I'll keep u posted"}],
             "expect": {"kind": "item", "type": "commitment"}},
        ]
        out = replay(lines, T0, self.USERS)
        req = next(i for i in out["items"] if i["type"] == "request")
        com = next(i for i in out["items"] if i["type"] == "commitment")
        return req, com

    def test_the_due_date_is_read_from_the_whole_message(self):
        _req, com = self._two("can you file the scaffold permit renewal by Saturday?")
        self.assertEqual(com["due"]["due_text"], "Sunday")
        self.assertIsNotNone(com["due"]["due_at"])

    def test_a_name_that_matches_one_person_is_the_owner(self):
        req, com = self._two("Patricia, can you file the scaffold permit renewal by Saturday?")
        self.assertEqual((req["owner"]["kind"], req["owner"]["id"], req["owner"]["source"]),
                         ("user", "u_p", "named"))
        self.assertFalse(req["owner"].get("possibly"))
        self.assertFalse(req.get("needs_review"))
        # Her answer is to an ask put to her: confirmed, no flag.
        self.assertFalse(com["owner"].get("possibly"))
        self.assertFalse(com.get("needs_review"))

    def test_no_match_is_as_before(self):
        req, com = self._two("Zed, can you file the scaffold permit renewal by Saturday?")
        self.assertTrue(req["owner"].get("possibly"))
        self.assertTrue(com["owner"].get("possibly"))

    def test_a_full_name_and_an_answer_from_a_privacy_id(self):
        # Pat PM is a user (phone on file) who posts in the group from an
        # @lid id linked through her opt-in: the same person either way.
        from tests.test_whatsapp_attention import LID_PM
        lines = [
            {"n": 1, "from": "R", "body": "Pat PM, can you file the scaffold permit renewal by Saturday?",
             "expect": {"kind": "item", "type": "request", "due_text": "by Saturday"}},
            {"n": 2, "from": "P", "body": "Sunday. I'll keep u posted",
             "model": [{"type": "commitment", "quote": "Sunday. I'll keep u posted",
                        "due_text": "Sunday"}],
             "expect": {"kind": "item", "type": "commitment"}},
            {"n": 3, "from": "P", "body": "Done, filed it",
             "expect": {"kind": "state", "of": 2, "to": "done"}},
        ]
        db = _world()
        _first_sight(db)
        _msg(db, lines[0]["body"], sender=SENDERS["R"], at=T0 + timedelta(minutes=1))
        for n in (1, 2):
            _msg(db, lines[n]["body"], sender=LID_PM, jid=f"{LID_PM}@lid",
                 at=T0 + timedelta(minutes=2 + n))
        _tick(db, _ScriptedModel(lines), T0 + timedelta(minutes=10))
        req = next(i for i in _items(db) if i["type"] == "request")
        com = next(i for i in _items(db) if i["type"] == "commitment")
        self.assertEqual((req["owner"]["kind"], req["owner"]["id"], req["owner"]["source"]),
                         ("user", "u_pm", "named"))
        self.assertFalse(com["owner"].get("possibly"))
        self.assertFalse(com.get("needs_review"))
        # Her "Done" from the privacy id is the owner's update.
        self.assertEqual((com["status"], req["status"]), ("done", "done"))

    def test_a_mapped_person_by_name(self):
        from lib import wa_sender_map as sm
        lines = [
            {"n": 1, "from": "R", "body": "Jose, can you send the sleeve layout by Friday?",
             "expect": {"kind": "item", "type": "request", "due_text": "by Friday"}},
        ]
        db = _world()
        db[sm.COLLECTION].rows.append({"_id": "m1", "company_id": "co_a",
                                       "sender_jid": "999@lid", "person_name": "Jose Zarate",
                                       "sub_company": "QP"})
        _first_sight(db)
        _msg(db, lines[0]["body"], sender=SENDERS["R"], at=T0 + timedelta(minutes=1))
        _tick(db, _ScriptedModel(lines), T0 + timedelta(minutes=5))
        req = _items(db)[0]
        self.assertEqual((req["owner"]["kind"], req["owner"]["jid"], req["owner"]["source"]),
                         ("sender_map", "999@lid", "named"))


class TheRules(unittest.TestCase):
    """The pure checks the fixtures rest on."""

    def test_time_of_day_without_a_day(self):
        for t in ("before 8am", "by 3pm", "till 11-12", "11:30am", "around 9-10am"):
            self.assertTrue(wa.time_only(t), t)
        for t in ("tomorrow", "Saturday morning", "by Friday 3pm", "", None):
            self.assertFalse(wa.time_only(t), t)
        self.assertEqual(was.classify("Actually give me till 11-12"),
                         {"kind": "reschedule", "due_text": "till 11-12", "time_only": True})
        # A bare range is not a time ("floors 11-12"); a day still wins.
        self.assertIsNone(was.classify("Actually floors 11-12"))
        self.assertEqual(was.classify("Actually Monday morning")["due_text"], "Monday")

    def test_bursts_never_take_a_reply_or_an_update(self):
        t = datetime(2026, 10, 9, 19, 39, 40, tzinfo=timezone.utc)

        def row(body, s, **kw):
            return {"sender": "P", "body": body, "created_at": t + timedelta(seconds=s), **kw}
        rows = [row("Sunday. I'll keep u posted", 0),
                row("Actually give me till 11-12", 25),       # no reply-to stored
                row("I'll also send the sleeve shop drawings", 50),
                row("Np", 70), row("Tomorrow", 80),
                row("thanks", 90, quoted_message_id="X1"),
                row("ok", 100)]
        got = [[r["body"] for r in b] for b in was.bursts(rows)]
        self.assertEqual(got, [["Sunday. I'll keep u posted"], ["Actually give me till 11-12"],
                               ["I'll also send the sleeve shop drawings", "Np", "Tomorrow"],
                               ["thanks"], ["ok"]])
        for body in ("Actually Monday", "Just sent", "sent it", "Never mind the dampers",
                     "nevermind", "Forget it", "Done!"):
            self.assertTrue(was.starts_with_update(body), body)
        for body in ("I sent it", "Sunday", "Is it done?x"):
            self.assertFalse(was.starts_with_update(body), body)

    def test_a_reply_is_the_strongest_link(self):
        cands = [{"id": "a", "key": "K1", "topic": ["riser"]},
                 {"id": "b", "key": "K2", "topic": ["sleeve"]}]
        upd = {"reply_key": "ZZ", "previous_key": "K2", "terms": set(), "own_terms": set()}
        # A reply to something that is no item is not pinned on the message before.
        self.assertNotEqual(was._pick_raw(cands, upd)["link"], "previous")
        self.assertEqual(was._pick_raw(cands, {**upd, "reply_key": "K1"})["items"][0]["id"], "a")

    def test_an_ask_opening_with_a_name(self):
        for body, want in (("B, can you send the riser dimensions?", "b"),
                           ("Mike, can you send the RFI", "mike"),
                           ("Patricia Lee, can you send it?", "patricia lee"),
                           ("Hey guys, who has the key?", None),
                           ("@Patricia: send it", "patricia"),
                           ("Guys, who has the key?", None), ("Hey, can you…", None),
                           ("can you send it", None), ("Mike can you send it", None)):
            self.assertEqual(wa.addressed_name(body), want, body)
        self.assertTrue(wa.prompt_at_least("att-v1.2"))
        self.assertTrue(wa.prompt_at_least("att-v1.10"))
        for v in ("att-v1.1", "att-v0.9", None, "", "v1.2"):
            self.assertFalse(wa.prompt_at_least(v), v)

    def test_i_kk_is_a_yes(self):
        self.assertEqual(was.ack("I\nKk"), {"due_text": None})
        self.assertIsNone(was.ack("I"))

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
        _msg(db, "I'll check the riser layout", at=at)
        model = _ScriptedModel([])
        report, _ = _tick(db, model, at + timedelta(seconds=30))
        self.assertEqual((report["held"], model.calls), (1, []))
        _msg(db, "Tomorrow", at=at + timedelta(seconds=40))
        _tick(db, model, at + timedelta(seconds=150))
        self.assertEqual(model.calls, ["I'll check the riser layout\nTomorrow"])

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
                         [("created", "open"), ("flag", "open"), ("state", "rescheduled"),
                          ("follow_up", None), ("state", "done")])
        rs = v["history"][2]
        self.assertEqual((rs["quote"], rs["due_from"], rs["due_to"], rs["link"]),
                         ("Actually risers will be Monday, engineer is out",
                          "tomorrow morning", "Monday", "owner_topic"))
        self.assertNotIn(SENDERS["B"], json.dumps(v))
        open_quotes = {i["quote"] for i in self._get("open")["items"]}
        self.assertNotIn("Yeah I'll send them tomorrow morning", open_quotes)
        self.assertIn("Everyone send insurance certs by the 15th", open_quotes)

    def test_correct_and_wrong_per_change(self):
        ev = self.riser["history"]
        v = self._review(ev[2]["id"], "correct")
        self.assertEqual(v["history"][2]["verdict"], "correct")
        v = self._review(ev[4]["id"], "wrong")
        self.assertEqual([h["verdict"] for h in v["history"]],
                         [None, None, "correct", None, "wrong"])
        sp = self._get("all")["state_precision"]
        self.assertEqual((sp["rescheduled"]["correct"], sp["done"]["wrong"]), (1, 1))
        # A verdict records; it does not undo the change.
        self.assertEqual(v["status"], "done")

    def test_refusals(self):
        ev = self.riser["history"]
        for user, code in ((PM, 403), (ADMIN_B, 404)):
            with self.assertRaises(HTTPException) as e:
                self._review(ev[2]["id"], "correct", user=user)
            self.assertEqual(e.exception.status_code, code)
        for event_id, verdict, code in ((ev[2]["id"], "dismissed", 422),
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



class ShortAcks(unittest.TestCase):
    """ "Np", "ok", "will do", "👍 tmrw": a yes to the ask put to that
    sender, read by code. A yes to nobody is nothing."""

    def _run(self, lines):
        out = replay(lines)
        return out, {it["evidence"]["quote"]: it for it in out["items"]}

    def _ask(self, n, at, body, **kw):
        return {"n": n, "from": "R", "at": at, "body": body,
                "expect": {"kind": "item", "type": "request"}, **kw}

    def test_addressed_by_name_with_a_date_in_the_ack(self):
        out, items = self._run([
            {"n": 1, "from": "R", "at": 0, "body": "Patricia can you send the damper submittal?",
             "expect": {"kind": "item", "type": "request", "owner_text": "Patricia"}},
            {"n": 2, "from": "B", "at": 60, "body": "Panel schedule is in the folder",
             "expect": {"kind": "none"}},
            {"n": 3, "from": "P", "at": 120, "name": "Patricia R", "body": "👍 tmrw",
             "expect": {"kind": "item", "type": "commitment"}},
        ])
        it = items["👍 tmrw"]
        self.assertEqual(it["type"], "commitment")
        self.assertEqual(it["due"]["due_text"], "tmrw")
        self.assertEqual(it["parent_id"], str(items[
            "Patricia can you send the damper submittal?"]["_id"]))
        self.assertEqual(out["model"].calls.count("👍 tmrw"), 0)

    def test_an_ack_to_nobody_is_nothing(self):
        out, items = self._run([
            {"n": 1, "from": "B", "at": 0, "body": "Panel schedule is in the folder",
             "expect": {"kind": "none"}},
            {"n": 2, "from": "P", "at": 60, "body": "ok", "expect": {"kind": "none"}},
            {"n": 3, "from": "P", "at": 120, "body": "will do", "expect": {"kind": "none"}},
        ])
        self.assertEqual(items, {})
        self.assertEqual(out["report"]["ack_unaddressed"], 2)
        self.assertEqual(out["model"].calls, [])

    def test_an_ask_put_to_someone_else_is_not_theirs_to_ack(self):
        _, items = self._run([
            self._ask(1, 0, "@Bob can you send the riser layout?", mentions=["B"]),
            {"n": 2, "from": "C", "at": 30, "body": "Gas meter is set",
             "expect": {"kind": "none"}},
            {"n": 3, "from": "P", "at": 60, "body": "Np", "expect": {"kind": "none"}},
        ])
        self.assertNotIn("Np", items)

    def test_older_than_30_minutes_is_not_answered_by_an_ack(self):
        _, items = self._run([
            self._ask(1, 0, "@Patricia can you send the sleeve layout?", mentions=["P"]),
            {"n": 2, "from": "C", "at": 60, "body": "Gas meter is set",
             "expect": {"kind": "none"}},
            {"n": 3, "from": "P", "at": 31 * 60, "body": "Np", "expect": {"kind": "none"}},
        ])
        self.assertNotIn("Np", items)

    def test_two_asks_put_to_her_and_no_reply_is_nothing(self):
        _, items = self._run([
            self._ask(1, 0, "@Patricia can you send the sleeve layout?", mentions=["P"]),
            self._ask(2, 60, "@Patricia can you confirm the meter location?", mentions=["P"]),
            {"n": 3, "from": "C", "at": 90, "body": "Gas meter is set",
             "expect": {"kind": "none"}},
            {"n": 4, "from": "P", "at": 120, "body": "Np", "expect": {"kind": "none"}},
        ])
        self.assertNotIn("Np", items)

    def test_a_reply_picks_which_one(self):
        _, items = self._run([
            self._ask(1, 0, "@Patricia can you send the sleeve layout?", mentions=["P"]),
            self._ask(2, 60, "@Patricia can you confirm the meter location?", mentions=["P"]),
            {"n": 3, "from": "P", "at": 120, "body": "will do", "reply_to": 1,
             "expect": {"kind": "item", "type": "commitment"}},
        ])
        self.assertEqual(items["will do"]["parent_id"],
                         str(items["@Patricia can you send the sleeve layout?"]["_id"]))

    def test_rule_2_needs_no_third_person_in_between(self):
        _, items = self._run([
            self._ask(1, 0, "Can you confirm the water meter location?"),
            {"n": 2, "from": "R", "at": 90, "body": "With the MEP engineer",
             "expect": {"kind": "none"}},
            {"n": 3, "from": "P", "at": 180, "body": "np tmrw",
             "expect": {"kind": "item", "type": "commitment"}},
        ])
        # Only who asked wrote in between: still possibly hers.
        req = items["Can you confirm the water meter location?"]
        self.assertTrue(req["owner"]["possibly"])
        self.assertIn("np tmrw", items)

    def test_rule_2_is_10_minutes(self):
        _, items = self._run([
            self._ask(1, 0, "Can you confirm the water meter location?"),
            {"n": 2, "from": "P", "at": 11 * 60, "body": "np", "expect": {"kind": "none"}},
        ])
        self.assertNotIn("np", items)
        self.assertFalse(items["Can you confirm the water meter location?"]["owner"].get("jid"))

    def test_a_reply_is_confident(self):
        _, items = self._run([
            self._ask(1, 0, "Can you confirm the water meter location?"),
            {"n": 2, "from": "P", "at": 60, "body": "np", "reply_to": 1,
             "expect": {"kind": "item", "type": "commitment"}},
        ])
        req = items["Can you confirm the water meter location?"]
        self.assertEqual(req["owner"]["jid"], SENDERS["P"] + "@c.us")
        self.assertFalse(req["owner"]["possibly"])
        self.assertFalse(req.get("needs_review"))

    def test_sarcasm_is_not_a_yes(self):
        for body in ("lol ok", "sure 😂", "haha ok", "Sure lmao", "ok 🙄"):
            self.assertIsNone(was.ack(body), body)

    def test_what_is_an_ack(self):
        for body in ("Np", "ok", "will do", "Np\nTomorrow", "👍 tmrw", "Sure you got it",
                     "np, tomorrow morning", "yes"):
            self.assertIsNotNone(was.ack(body), body)
        for body in ("Lol... Sure", "ok?", "Sure, the riser is in", "thanks guys", "Sent",
                     "I'll send it tomorrow"):
            self.assertIsNone(was.ack(body), body)


if __name__ == "__main__":
    unittest.main()
