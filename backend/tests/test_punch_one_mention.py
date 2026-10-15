"""Each person @mentioned once, at the top of a group post (Thu 9:03 AM:
"Meilich Friedman (GC team)" listed 6 times, one per trade)."""
import re
import unittest

from lib import punch

MEILICH = {"kind": "user", "id": "u1", "name": "Meilich Friedman"}
DOV = {"kind": "sender_map", "id": "m1", "name": "Dov Klein", "company": "Power Direct"}
TRADES = ("cleaning", "concrete", "drywall", "hvac", "roofing", punch.UNKNOWN)


def _items():
    return [{"n": i, "pid": f"P-588-{i}", "text": f"Item {i}", "floor": str(1 + i % 3),
             "area": punch.UNKNOWN, "trade": t, "status": "draft"}
            for i, t in enumerate(TRADES, 1)]


class OneMention(unittest.TestCase):
    def test_the_recap_names_each_person_once(self):
        recap = punch.recap_text(_items(), {t: MEILICH for t in TRADES}, {}, target="group",
                                 group_name="588 GC")
        self.assertEqual(recap.count("Meilich Friedman"), 1, recap)
        self.assertIn("Mentioning Meilich Friedman (GC team) — cleaning, concrete, drywall, hvac, "
                      "roofing, no trade\n", recap)

    def test_two_people_each_once_with_their_trades(self):
        assign = {t: (DOV if t == "hvac" else MEILICH) for t in TRADES}
        recap = punch.recap_text(_items(), assign, {}, target="group")
        self.assertIn("Mentioning Meilich Friedman (GC team) — cleaning, concrete, drywall, roofing, "
                      "no trade; Dov Klein (Power Direct) — hvac\n", recap)

    def test_the_post_mentions_each_person_once_at_the_top(self):
        mentions = {t: "@Meilich Friedman" for t in TRADES}
        text = punch.full_list_text("588 Thomas St", _items(), punch.ASAP, mentions)
        lines = text.splitlines()
        self.assertEqual(lines[1], "@Meilich Friedman")
        self.assertEqual(text.count("@Meilich Friedman"), 1, text)
        self.assertIsNone(re.search(r"_[\w ]+_ @", text))

    def test_two_people_in_the_post(self):
        mentions = {t: ("@Dov Klein" if t == "hvac" else "@Meilich Friedman") for t in TRADES}
        lines = punch.full_list_text("588", _items(), punch.ASAP, mentions).splitlines()
        self.assertEqual(lines[1:3], ["@Meilich Friedman — cleaning, concrete, drywall, roofing, no trade",
                                      "@Dov Klein — hvac"])

    def test_nobody_to_mention(self):
        lines = punch.full_list_text("588", _items(), punch.ASAP, {}).splitlines()
        self.assertTrue(lines[1].startswith("*"), lines)


if __name__ == "__main__":
    unittest.main()
