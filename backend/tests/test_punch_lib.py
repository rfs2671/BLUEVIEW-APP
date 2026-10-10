"""lib/punch.py: walkthrough -> punch list, the pure rules."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import punch as p  # noqa: E402


def _items(texts, voice_at=()):
    return [p.new_item(i + 1, t, photo_key=f"k{i}", message_id=f"m{i}",
                       voice={"lang": "es"} if i in voice_at else None)
            for i, t in enumerate(texts)]


class Starting(unittest.TestCase):

    def test_start_phrases(self):
        self.assertEqual(p.start_request("starting walkthrough at 588"), {"job": "588"})
        self.assertEqual(p.start_request("Start walk-through"), {"job": None})
        self.assertEqual(p.start_request("empezando recorrido en 588"), {"job": "588"})
        self.assertIsNone(p.start_request("the walkthrough went fine"))

    def test_which_job(self):
        projects = [{"_id": "a", "name": "588 Thomas St"}, {"_id": "b", "name": "8 Walworth St"}]
        self.assertEqual(p.match_project("588", projects)[0]["_id"], "a")
        self.assertEqual(p.match_project("walworth", projects)[0]["_id"], "b")
        self.assertEqual(p.match_project(None, projects), (None, "several"))
        self.assertEqual(p.match_project(None, projects[:1])[0]["_id"], "a")
        self.assertEqual(p.match_project("99", projects), (None, "none"))

    def test_ids(self):
        self.assertEqual(p.job_code({"name": "588 Thomas St"}), "588")
        self.assertEqual(p.job_code({"name": "Main St", "job_number": "J-12"}), "J-12")
        self.assertEqual(p.punch_id("588", 23), "P-588-23")
        self.assertEqual(p.parse_pid("P23 ok", "588"), ("588", 23))
        self.assertEqual(p.parse_pid("done P-588-7"), ("588", 7))


class ReadingACaption(unittest.TestCase):

    def test_trade_floor_area(self):
        it = p.new_item(1, "6th floor apt 6B outlet cover missing", photo_key="k", message_id="m")
        self.assertEqual((it["floor"], it["area"], it["trade"]), ("6", "Apt 6B", "electrical"))
        es = p.new_item(2, "piso 6 falta pintura en el pasillo", photo_key="k", message_id="m")
        self.assertEqual((es["floor"], es["area"], es["trade"]), ("6", "hallway", "paint"))

    def test_unknown_is_kept_and_marked(self):
        it = p.new_item(1, "stain on ceiling", photo_key="k", message_id="m")
        self.assertEqual((it["floor"], it["trade"], it["text"]), ("?", "?", "stain on ceiling"))
        two = p.new_item(1, "outlet next to the leaking pipe", photo_key="k", message_id="m")
        self.assertEqual(two["trade"], "?")          # two trades named: the walker says

    def test_trade_words(self):
        for w, t in (("electrical", "electrical"), ("elec", "electrical"), ("plomero", "plumbing"),
                     ("sheetrock", "drywall"), ("painter", "paint")):
            self.assertEqual(p.trade_word(w), t, w)


class TheDraft(unittest.TestCase):

    def test_grouped_numbered_marked(self):
        items = _items(["6th floor apt 6B outlet cover missing", "Floor 6 kitchen faucet leaking",
                        "door closer broken 5th floor", "stain on ceiling 5th fl",
                        "piso 6 falta pintura"], voice_at=(4,))
        text = p.draft_text("588 Thomas", items)
        self.assertTrue(text.startswith("588 Thomas · walkthrough · 5 items (draft)"))
        self.assertLess(text.index("*Floor 5*"), text.index("*Floor 6*"))
        self.assertIn("📷🎤 piso 6 falta pintura", text)
        self.assertIn("1 needs a trade", text)
        self.assertIn("'send'", text)
        # Numbers follow the draft's order.
        import re
        nums = [int(m.group(1)) for m in re.finditer(r"^(\d+)\. ", text, re.M)]
        self.assertEqual(nums, [1, 2, 3, 4, 5])


class Edits(unittest.TestCase):

    def test_parse(self):
        self.assertEqual(p.parse_edit("2 → electrical"), {"op": "trade", "n": 2, "trade": "electrical"})
        self.assertEqual(p.parse_edit("4 -> doors")["trade"], "doors")
        self.assertEqual(p.parse_edit("drop 6"), {"op": "drop", "n": 6})
        self.assertEqual(p.parse_edit("merge 5 and 4"), {"op": "merge", "a": 4, "b": 5})
        self.assertEqual(p.parse_edit("add: exit sign out floor 3"),
                         {"op": "add", "text": "exit sign out floor 3"})
        self.assertEqual(p.parse_edit("move 3 to floor 6"), {"op": "floor", "n": 3, "floor": "6"})
        self.assertIsNone(p.parse_edit("hello"))
        self.assertEqual(len(p.parse_edits("2 → electrical\ndrop 6")), 2)

    def test_apply(self):
        items = _items(["outlet floor 6", "stain on ceiling", "faucet floor 6"])
        p.renumber(items)
        n_stain = next(it["n"] for it in items if it["text"] == "stain on ceiling")
        self.assertTrue(p.apply_edit(items, {"op": "trade", "n": n_stain, "trade": "paint"}, next_n=4)[0])
        self.assertEqual(next(it for it in items if it["text"] == "stain on ceiling")["trade"], "paint")
        a, b = sorted(it["n"] for it in items if it["floor"] == "6")
        p.apply_edit(items, {"op": "merge", "a": a, "b": b}, next_n=4)
        live = [it for it in items if it.get("status") != "dropped"]
        self.assertEqual(len(live), 2)
        p.apply_edit(items, {"op": "add", "text": "exit sign"}, next_n=4)
        self.assertEqual(items[-1]["text"], "exit sign")
        self.assertEqual(p.apply_edit(items, {"op": "drop", "n": 99}, next_n=5), (False, "no item 99"))


class AssignAndDue(unittest.TestCase):

    PEOPLE = [{"name": "Mike Rivera", "company": "Bright Electric", "trades": ["electrical"]},
              {"name": "Jose Zarate", "company": "Quality Plumbing", "trades": ["plumbing"]},
              {"name": "Patricia Lee", "company": "Quality Plumbing", "trades": ["plumbing"]},
              {"name": "Ana", "company": "A Paint", "trades": ["paint"]},
              {"name": "Bo", "company": "B Paint", "trades": ["paint"]}]

    def test_one_company_per_trade(self):
        s = p.suggest_assignees(["electrical", "plumbing", "paint", "?"], self.PEOPLE)
        self.assertEqual(s["electrical"]["name"], "Mike Rivera")
        self.assertEqual(s["plumbing"]["company"], "Quality Plumbing")   # one company
        self.assertIsNone(s["paint"])                                       # two: the walker says
        self.assertNotIn("?", s)
        self.assertIn("paint → ?", p.assign_text(s))

    def test_fixing_and_picking(self):
        self.assertEqual(p.parse_assign("paint → Bo"), [("paint", "Bo")])
        self.assertEqual(p.pick_person("Bo", self.PEOPLE)["company"], "B Paint")
        self.assertEqual(p.pick_person("mike", self.PEOPLE)["name"], "Mike Rivera")
        self.assertIsNone(p.pick_person("nobody", self.PEOPLE))

    def test_one_due_question(self):
        self.assertEqual(p.parse_due_answer("Fri", ["electrical", "paint"]),
                         {"electrical": "Fri", "paint": "Fri"})
        self.assertEqual(p.parse_due_answer("electrical Mon, paint Fri", ["electrical", "paint"]),
                         {"electrical": "Mon", "paint": "Fri"})
        self.assertEqual(p.parse_due_answer("el viernes", ["paint"]), {"paint": "el viernes"})
        self.assertIsNone(p.parse_due_answer("soon", ["paint"]))         # never guessed


class SendingAndClosing(unittest.TestCase):

    def test_group_and_shadow_text(self):
        its = [{"pid": "P-588-1", "text": "outlet cover", "floor": "6", "area": "Apt 6B"}]
        g = p.group_text("Mike Rivera", its, "Fri")
        self.assertTrue(g.startswith("@Mike Rivera punch list — due Fri:"))
        self.assertIn("P-588-1 outlet cover (Floor 6 · Apt 6B)", g)
        sh = p.shadow_text([{"name": "Mike Rivera", "items": its, "due_words": "Fri", "photos": 1}])
        self.assertTrue(sh.startswith("Punch sends are in shadow mode: nothing was posted"))

    def test_closing_words(self):
        self.assertTrue(p.sub_done("done P23"))
        self.assertTrue(p.sub_done("P23 listo"))
        self.assertFalse(p.sub_done("is P23 done?"))
        self.assertEqual(p.super_verdict("P23 ok"), "closed")
        self.assertEqual(p.super_verdict("P-588-23 not done"), "reopened")
        self.assertIsNone(p.super_verdict("P23 looks rough"))

    def test_queries(self):
        self.assertEqual(p.parse_query("what's open on 6 at 588?"),
                         {"q": "open", "floor": "6", "job": "588"})
        self.assertEqual(p.parse_query("who closed P23?"), {"q": "who_closed", "pid": "P23"})
        self.assertEqual(p.parse_query("show P23 photo"), {"q": "photo", "pid": "P23"})
        self.assertIsNone(p.parse_query("what's the weather"))
        txt = p.open_text("588 Thomas", [
            {"pid": "P-588-1", "text": "outlet", "status": "open", "floor": "6", "seq": 1,
             "assignee": {"name": "Mike"}},
            {"pid": "P-588-2", "text": "paint", "status": "closed", "floor": "6", "seq": 2},
            {"pid": "P-588-3", "text": "faucet", "status": "ready_to_check", "floor": "6", "seq": 3}], "6")
        self.assertEqual(txt.splitlines(), ["588 Thomas · 2 open on floor 6:",
                                            "• P-588-1 outlet — Mike",
                                            "• P-588-3 faucet (ready to check)"])


if __name__ == "__main__":
    unittest.main()
