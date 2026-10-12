"""A job by its street name alone (the gap after the 7:17 PM fix).

"at walworth", "the menahan job", "boyland", "walwroth st": matched against
the company's active jobs, typos allowed, "st"/"street" and no house number.
One match: that job. Several: "Which one? 1) 8 Walworth St 2) 120 Walworth St".
ONE matcher (wa_assistant.find_jobs) for the questions assistant and every DM
action -- tested through the real DM entry point.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import wa_assistant  # noqa: E402
from tests.test_dm_routing_order import CHAT, _Dm, _world  # noqa: E402
from tests.test_whatsapp_dm_assistant import CO_A, THOMAS, WALWORTH, _Ctx  # noqa: E402

W120, MENAHAN, WATER = "proj_w120", "proj_men", "proj_water"


def _streets():
    db = _world()
    db.projects.rows.extend([
        {"_id": W120, "company_id": CO_A, "name": "Walworth North",
         "address": "120 Walworth St, Brooklyn, NY",
         "trade_assignments": [{"id": "t3", "company": "Arkon", "trade": "Drywall"}]},
        {"_id": MENAHAN, "company_id": CO_A, "name": "Menahan",
         "address": "9 Menahan St, Brooklyn, NY", "trade_assignments": []},
        {"_id": WATER, "company_id": CO_A, "name": "Seaport Tower",
         "address": "77 Water St, New York, NY", "trade_assignments": []},
    ])
    return db


def _jobs():
    return [{"id": pid, "label": wa_assistant.street_label({"address": a}),
             "aliases": wa_assistant.job_aliases({"address": a})}
            for pid, a in ((THOMAS, "588 Thomas S Boyland St, Brooklyn"),
                           (WALWORTH, "8 Walworth St, Brooklyn"),
                           (W120, "120 Walworth St, Brooklyn"),
                           (MENAHAN, "9 Menahan St, Brooklyn"),
                           (WATER, "77 Water St, New York"))]


class TheMatcher(unittest.TestCase):

    def test_by_street_alone_fuzzy(self):
        f = lambda t: sorted(wa_assistant.find_jobs(t, _jobs()))  # noqa: E731
        cases = {
            "at walworth": sorted([WALWORTH, W120]),
            "the menahan job": [MENAHAN],
            "boyland": [THOMAS],
            "boyland street": [THOMAS],
            "walwroth st": sorted([WALWORTH, W120]),          # a transposition
            "menhan": [MENAHAN],                              # a letter missing
            "boylan": [THOMAS],
            "8 walworth": [WALWORTH],                         # the number decides
            "120 walworth street": [W120],
            "588": [THOMAS],
            "at water": [WATER], "water st": [WATER], "the water job": [WATER],
        }
        for said, want in cases.items():
            with self.subTest(said):
                self.assertEqual(f(said), want)

    def test_not_a_job(self):
        for said in ("is the water leak fixed", "water damage on 3", "did thomas check in",
                     "how many workers today", "worth it", "since 8:07", "main thing is safety"):
            with self.subTest(said):
                self.assertEqual(wa_assistant.find_jobs(said, _jobs()), [])

    def test_the_key_word(self):
        self.assertEqual(wa_assistant.street_key("588 Thomas S Boyland St"), "boyland")
        self.assertEqual(wa_assistant.street_key("8 Walworth St"), "walworth")
        self.assertEqual(wa_assistant.street_key("852 E 176 St"), "")

    def test_one_matcher_everywhere(self):
        import inspect
        self.assertIn("wa_assistant.find_jobs", inspect.getsource(server._dm_find_jobs))
        self.assertIn("wa_assistant.find_jobs", inspect.getsource(server._dm_assistant_reply))
        self.assertIn("find_jobs", inspect.getsource(wa_assistant.job_named))


class TheQuestionPath(_Dm, unittest.TestCase):

    def test_one_match_answers_for_it(self):
        for said, pid in (("what's open at the menahan job", MENAHAN),
                          ("whats open at boyland", THOMAS),
                          ("what's open at boylnd", THOMAS)):
            with self.subTest(said):
                self.agent_calls.clear()
                with _Ctx(db=_streets()) as c:
                    self._send(c, CHAT, said, mid="Q1")
                self.assertEqual(self.agent_calls[-1]["project_id"], pid)

    def test_several_ask_which_one_and_the_pick_answers(self):
        with _Ctx(db=_streets()) as c:
            menu = self._send(c, CHAT, "what's open at walworth", mid="Q1")
            answer = self._send(c, CHAT, "2", mid="Q2")
        self.assertEqual(menu, "Which one? 1) 8 Walworth St 2) 120 Walworth St")
        self.assertEqual(answer, f"answer for {W120}")

    def test_an_everyday_word_is_not_a_job(self):
        with _Ctx(db=_streets()) as c:
            menu = self._send(c, CHAT, "is the water leak fixed", mid="Q1")
        self.assertTrue(menu.startswith("Which job?"), menu)        # not 77 Water St


class EveryDmAction(_Dm, unittest.TestCase):

    def test_a_setting_by_street(self):
        with _Ctx(db=_streets()) as c:
            (r,) = self.dm(c, "ok to chase on weekends at menahan")
        self.assertEqual(r, ["Remind people on weekends too at 9 Menahan St?"])

    def test_a_setting_on_a_shared_street_asks_which_one(self):
        with _Ctx(db=_streets()) as c:
            which, ask = self.dm(c, "ok to chase on weekends at walworth", "2")
        self.assertEqual(which, ["Which one?\n1) 8 Walworth St\n2) 120 Walworth St"])
        self.assertEqual(ask, ["Remind people on weekends too at 120 Walworth St?"])

    def test_a_sub_by_street_with_a_typo(self):
        with _Ctx(db=_streets()) as c:
            (r,) = self.dm(c, "put bright electric on boylnd as the electrician")
        self.assertEqual(r, ["Add Bright Electric (Electrical) to 588 Thomas S Boyland St?"])

    def test_a_sub_on_the_menahan_job(self):
        with _Ctx(db=_streets()) as c:
            (r,) = self.dm(c, "put bright electric on the menahan job they're the electrician")
        self.assertEqual(r, ["Add Bright Electric (Electrical) to 9 Menahan St?"])

    def test_a_punch_contact_narrowed_by_street(self):
        # Arkon is on 8 Walworth and 120 Walworth: "120 walworth" decides.
        with _Ctx(db=_streets()) as c:
            (r,) = self.dm(c, "dov handles punch for arkon at 120 walworth")
        self.assertNotIn("Which", r[0])

    def test_a_punch_contact_on_a_shared_street_asks(self):
        with _Ctx(db=_streets()) as c:
            (r,) = self.dm(c, "dov handles punch for arkon at walworth")
        self.assertEqual(r, ["Which one?\n1) 8 Walworth St\n2) 120 Walworth St"])

    def test_a_new_job_on_a_known_street_is_still_a_new_job(self):
        with _Ctx(db=_streets()) as c:
            (r,) = self.dm(c, "add 30 walworth st")
        self.assertNotIn("Which", r[0])
        self.assertTrue(r[0].startswith("Found it:"), r)


if __name__ == "__main__":
    unittest.main()
