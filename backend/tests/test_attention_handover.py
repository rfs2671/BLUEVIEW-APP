"""Handover, and closing an item from the asking side: the pure rules
(lib/wa_attention_state.py). The worker around them is covered by the dry
run scenarios (tests/test_attention_dry_run.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import wa_attention_state as was  # noqa: E402

PAT, JOSE, ROY, KEV, ANA = "1001", "1002", "1003", "1004", "1005"


def _c(id_, type_="commitment", owner="", requester="", topic=(), parent_id="",
       owner_ref=None, owner_name="", possibly=False, status="open", key=None):
    return {"id": id_, "type": type_, "status": status, "owner": owner,
            "requester": requester, "key": key or f"K{id_}", "parent_key": "",
            "parent_id": parent_id, "topic": set(topic), "multi": False,
            "owner_ref": owner_ref, "owner_name": owner_name, "owner_possibly": possibly}


class TheWords(unittest.TestCase):

    def test_done_by_someone_else(self):
        for text, want in {
            "Never mind the panel confirm, Mike already did": ("done", "mike"),
            "Mike already did it": ("done", "mike"),
            "Jose sent them": ("done", "jose"),
            "Never mind, already sent": ("done", ""),
            "Never mind the fire stopping, already counted": ("cancel", None),
            "Never mind the load calcs": ("cancel", None),
        }.items():
            cls = was.classify(text)
            self.assertEqual((cls["kind"], was.doer(text)), want, text)
        for mine in ("I already sent the panel", "We already sent it", "I've already done it",
                     "Never mind, I already sent it"):
            self.assertIsNone(was.doer(mine), mine)
            self.assertFalse((was.classify(mine) or {}).get("by_other"), mine)
        self.assertIsNone(was.doer("I did"))
        self.assertIsNone(was.doer("Yes did"))
        self.assertIsNone(was.classify("Mike will do it tomorrow"))

    def test_who_is_out(self):
        for text, want in {
            "Patricia's out sick, I'll send the risers Friday": "patricia",
            "Patricia’s out today, I got it": "patricia",
            "Mike can't make it, I'll take the walkthrough": "mike",
            "covering for Jose on the sleeves": "jose",
            "Patricia is out today": None,                  # nobody takes it on
            "the pump is out, I will get another": None,
            "he's out, I'll do it": None,
        }.items():
            self.assertEqual(was.handover_name(text), want, text)


class OwnSubject(unittest.TestCase):
    """A commitment that names what it is about never borrows an earlier
    ask's subject (live eval Oct 10, busy line 31)."""

    def test_own_subject(self):
        for text, want in {
            "I'll send the updated logistics plan Thursday": {"logistic", "plan"},
            "I'll send the RTU startup report Thursday": {"rtu", "startup", "report"},
            "Lift is mine, 7am Thursday": {"lift"},
            "Np": set(), "I'll take care of it": set(),
            "Sunday. I'll keep u posted": set(), "Sure I'll get it before 8am": set(),
        }.items():
            self.assertEqual(was.own_subject(text), want, text)


class Handover(unittest.TestCase):

    def setUp(self):
        self.ask = _c("a1", "request", owner=PAT, requester=ROY, topic={"riser", "drawing"},
                      owner_ref="sender_map:p")
        self.hers = _c("c1", owner=PAT, topic={"riser", "drawing"}, parent_id="a1",
                       owner_ref="sender_map:p")
        self.upd = {"sender": JOSE, "sender_ref": "sender_map:j", "named_ref": "sender_map:p",
                    "own_terms": {"riser", "sick"}, "same_company": False}

    def test_by_subject(self):
        acts = was.decide_handover(self.upd, [self.ask, self.hers])
        self.assertEqual([(a["item_id"], a["action"]) for a in acts], [("c1", "handover")])

    def test_same_company_and_her_only_item(self):
        acts = was.decide_handover({**self.upd, "own_terms": {"sick"}, "same_company": True},
                                   [self.ask, self.hers])
        self.assertEqual([(a["item_id"], a["action"], a["link"]) for a in acts],
                         [("c1", "handover", "only_open")])

    def test_neither_flags_the_item_and_its_ask(self):
        acts = was.decide_handover({**self.upd, "own_terms": {"sick"}}, [self.ask, self.hers])
        self.assertEqual([(a["item_id"], a["action"], a["note"]) for a in acts],
                         [("c1", "flag", "possible_handover"), ("a1", "flag", "possible_handover")])

    def test_two_of_hers_and_no_subject_is_one_review(self):
        other = _c("c2", owner=PAT, topic={"sleeve"}, owner_ref="sender_map:p")
        acts = was.decide_handover({**self.upd, "own_terms": {"sick"}, "same_company": True},
                                   [self.ask, self.hers, other])
        self.assertEqual(len(acts), 1)
        self.assertEqual((acts[0]["action"], acts[0]["kind"], sorted(acts[0]["item_ids"])),
                         ("review", "handover", ["c1", "c2"]))

    def test_nothing_of_hers_or_herself(self):
        self.assertEqual(was.decide_handover(self.upd, []), [])
        self.assertEqual(was.decide_handover({**self.upd, "sender_ref": "sender_map:p"},
                                             [self.hers]), [])


class FromTheAskingSide(unittest.TestCase):

    def setUp(self):
        self.ask = _c("a5", "request", requester=KEV, topic={"panel", "delivery"})
        self.chen = _c("c6", owner="2001", topic={"panel", "delivery"}, parent_id="a5",
                       owner_name="Mike Chen", possibly=True)
        self.rivera = _c("c7", owner="2002", topic={"panel", "coming"}, parent_id="a5",
                         owner_name="Mike Rivera")
        self.cuts = _c("c25", owner="2002", topic={"lighting", "cut", "sheet", "mike"},
                       owner_name="Mike Rivera")
        self.items = [self.ask, self.chen, self.rivera, self.cuts]
        text = "Never mind the panel confirm, Mike already did"
        self.upd = {"kind": "done", "by_other": True, "doer": "mike",
                    "own_terms": was.topic_terms(text), "terms": was.topic_terms(text),
                    "previous_key": "", "reply_key": ""}

    def _done(self, **over):
        return {(a["item_id"], a.get("to"), a.get("by"))
                for a in was.decide({**self.upd, **over}, self.items)}

    def test_gc_staff_close_it_by_subject(self):
        self.assertEqual(self._done(sender=ROY, sender_gc=True),
                         {("c7", "done", "gc_staff"), ("a5", "done", "gc_staff")})

    def test_the_asker_closes_it(self):
        self.assertEqual(self._done(sender=KEV),
                         {("c7", "done", "requester"), ("a5", "done", "requester")})

    def test_a_sub_who_did_not_ask_cannot(self):
        self.assertEqual(self._done(sender=ANA), set())

    def test_only_when_the_words_say_someone_else_did_it(self):
        # "I sent the panel schedule" from GC staff is their own doing, not
        # the sub's commitment.
        self.assertEqual(self._done(sender=ROY, sender_gc=True, by_other=False, doer=None),
                         set())

    def test_never_by_the_message_before_or_the_one_open(self):
        upd = {**self.upd, "own_terms": set(), "terms": {"panel"},
               "previous_key": "Kc7", "sender": ROY, "sender_gc": True}
        self.assertEqual(was.decide(upd, [self.ask, self.rivera]), [])

    def test_gc_staff_call_off_anyones_ask_by_subject(self):
        acts = was.decide({"kind": "cancel", "sender": ROY, "sender_gc": True,
                           "own_terms": {"panel"}, "terms": {"panel"},
                           "previous_key": "", "reply_key": ""}, [self.ask, self.rivera])
        self.assertEqual({(a["item_id"], a["to"], a["by"]) for a in acts},
                         {("a5", "cancelled", "gc_staff"), ("c7", "cancelled", "gc_staff")})

    def test_a_sub_cannot_call_off_someone_elses_ask(self):
        self.assertEqual(was.decide({"kind": "cancel", "sender": ANA, "own_terms": {"panel"},
                                     "terms": {"panel"}, "previous_key": "", "reply_key": ""},
                                    [self.ask, self.rivera]), [])


if __name__ == "__main__":
    unittest.main()
