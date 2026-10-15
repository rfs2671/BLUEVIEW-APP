"""Simple mode shows no trade anywhere (Thu 9:03 AM, 588): the group post
had "_no trade_ @Meilich Friedman" under every floor and the recap named
cleaning, concrete, drywall, hvac and roofing. Simple = floor / area
headings and the items only -- in the draft, "who gets it", the recap, the
due line and the post. The trades are still guessed and stored (a switch
to Detailed shows them); they are never shown."""

from __future__ import annotations

import re
import unittest
from unittest.mock import patch

import server
from lib import punch
from tests.test_punch_walkthrough_2303 import _Live

TRADES = ("cleaning", "concrete", "drywall", "hvac", "roofing", punch.UNKNOWN)
_TRADE_WORD = re.compile(r"\b(?:cleaning|concrete|drywall|hvac|roofing|electrical|plumbing|no trade)\b",
                         re.IGNORECASE)
MEILICH = {"kind": "user", "id": "u1", "name": "Meilich Friedman"}
DOV = {"kind": "sender_map", "id": "m1", "name": "Dov Klein", "company": "Power Direct"}


def _items():
    return [{"n": i, "pid": f"P-588-{i}", "text": f"Item {i}", "floor": str(1 + i % 3),
             "area": punch.UNKNOWN, "trade": t, "status": "draft"}
            for i, t in enumerate(TRADES, 1)]


class TheTexts(unittest.TestCase):

    def test_the_group_recap(self):
        recap = punch.recap_text(_items(), {t: MEILICH for t in TRADES}, {}, target="group",
                                 group_name="588 GC", simple=True)
        self.assertIn("Mentioning Meilich Friedman (GC team)\n", recap)
        self.assertIsNone(_TRADE_WORD.search(recap), recap)

    def test_the_due_line_is_by_person(self):
        assign = {t: (DOV if t == "hvac" else MEILICH) for t in TRADES}
        recap = punch.recap_text(_items(), assign, {"hvac": "Friday"}, simple=True)
        self.assertIsNone(_TRADE_WORD.search(recap), recap)
        self.assertIn("Due Meilich Friedman (GC team) ASAP, Dov Klein (Power Direct) Friday", recap)

    def test_who_gets_it(self):
        whole = punch.assign_text({t: MEILICH for t in TRADES}, simple=True)
        self.assertTrue(whole.startswith("Who gets it?\n• The whole list → Meilich Friedman (GC team)\n"),
                        whole)
        part = punch.assign_text({**{t: MEILICH for t in TRADES}, "hvac": None}, simple=True)
        self.assertIn("• Meilich Friedman (GC team)\n• The rest → who?", part)
        for text in (whole, part, punch.open_trades_question(["hvac", punch.UNKNOWN], simple=True)):
            self.assertIsNone(_TRADE_WORD.search(text), text)

    def test_the_post(self):
        mentions = {t: "@Meilich Friedman" for t in TRADES}
        text = punch.full_list_text("588 Thomas St", _items(), punch.ASAP, mentions, simple=True)
        self.assertIsNone(_TRADE_WORD.search(text), text)
        self.assertEqual(text.count("@Meilich Friedman"), 1)
        heads = [l for l in text.splitlines() if l.startswith(("*", "_"))]
        self.assertTrue(all(l.startswith("*Floor") for l in heads), heads)   # floor headings only

    def test_detailed_still_shows_them(self):
        recap = punch.recap_text(_items(), {t: MEILICH for t in TRADES}, {}, target="group")
        self.assertIn("— cleaning, concrete", recap)


class TheWalk(_Live, unittest.TestCase):
    """A simple walk from the first photo to the post: no trade in any
    message the walker gets, nor in the post (trades guessed: electrical,
    plumbing)."""

    def test_no_trade_anywhere(self):
        self.setting(punch_sends="live")
        posted = []

        async def gpost(gid, text, targets, reply_to=None):
            posted.append(text)
            return True

        async def photo(*a, **k):
            return True
        said = []
        said += self.turn("Bulb burnt 4F", photo=True)
        said += self.turn("Faucet leaking 2D", photo=True)
        self.assertEqual(self.sess().get("detail"), punch.DETAIL_SIMPLE)
        self.assertEqual(sorted(i["trade"] for i in self.sess()["items"]), ["electrical", "plumbing"])
        for text in ("done", "send", "electrical to Dov", "ok", "the rest to Dov", "to the group"):
            said += self.turn(text)
        with patch.object(server, "_group_post", gpost), patch.object(server, "_punch_send_photo", photo):
            said += self.turn("ok")
        self.assertEqual(len(posted), 1, said)
        for text in said + posted:
            self.assertIsNone(_TRADE_WORD.search(text), text)
        self.assertIn("Mentioning Dov Klein (Power Direct)\n", "\n".join(said))


if __name__ == "__main__":
    unittest.main()
