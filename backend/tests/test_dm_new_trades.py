"""A trade not on the company's list (DM add a sub).

The trade list feeds the daily-work -> next-day prediction, so a new trade
must be addable -- and a known one never added twice:
  * a synonym ("electricians", "sheetrock", "plomero") is the known label;
  * an unknown one ("Dance") -> "Dance isn't on your trade list — did you
    mean: <3 closest>? Or add 'Dance' as a new trade?";
  * "add it" puts it in the company's trade table (company_trades, the list
    the app's picker and the prediction read), audited; a number or a name
    picks a suggestion instead.
Through the real DM entry point.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import trades  # noqa: E402
from tests.test_dm_routing_order import _Dm, _world  # noqa: E402
from tests.test_whatsapp_dm_assistant import CO_A, THOMAS, _Ctx  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

V = list(server.TRADE_VOCABULARY)


def _run(coro):
    return asyncio.run(coro)


class TheList(unittest.TestCase):

    def test_every_synonym_names_a_published_label(self):
        self.assertEqual(set(trades.SYNONYMS.values()) - set(V), set())

    def test_synonyms(self):
        for said, label in (("they're the electricians", "Electrical"), ("electrician", "Electrical"),
                            ("plumber", "Plumbing"), ("plomero", "Plumbing"), ("sheetrock", "Drywall"),
                            ("tapers", "Drywall"), ("painters", "Painting"), ("HVAC", "HVAC / Mechanical"),
                            ("mechanical", "HVAC / Mechanical"), ("carpenters", "Framing"),
                            ("iron workers", "Steel / Ironwork"), ("sprinkler guys", "Sprinkler"),
                            ("windows", "Glazing"), ("Electrical", "Electrical"), ("masons", "Masonry")):
            with self.subTest(said):
                self.assertEqual(trades.resolve(said, V), label)

    def test_unknown_gets_three_closest(self):
        self.assertIsNone(trades.resolve("Dance", V))
        self.assertEqual(len(trades.closest("Dance", V)), 3)
        self.assertEqual(trades.closest("tile", V), ["Flooring", "Masonry", "Drywall"])

    def test_add_words(self):
        for said in ("add it", "Add it", "yes add", "add Dance as a new trade", "new trade", "agrégalo"):
            with self.subTest(said):
                self.assertTrue(trades.is_add(said))
        for said in ("no", "Painting", "2", "the second one"):
            with self.subTest(said):
                self.assertFalse(trades.is_add(said))

    def test_a_known_trade_is_never_added(self):
        db = FakeDb(company_trades=[], audit_logs=[])
        with patch.object(server, "db", db):
            for said in ("electrician", "sheetrock", "Plumbing"):
                _run(server._company_trade_add(CO_A, said, "u1", "test"))
            self.assertEqual(db.company_trades.rows, [])
            self.assertEqual(_run(server._company_trade_add(CO_A, "dance", "u1", "test")), "Dance")
            self.assertEqual(_run(server._company_trade_add(CO_A, "DANCE", "u1", "test")), "Dance")
        self.assertEqual(len(db.company_trades.rows), 1)
        self.assertEqual(len([a for a in db.audit_logs.rows if a["action"] == "company_trade_add"]), 1)

    def test_codex_773_one_row_when_two_add_it_at_once(self):
        # Both read the list before either wrote: the unique index on
        # (company_id, key) refuses the second insert; it is not an error,
        # and only the add that happened is audited.
        import inspect
        from pymongo.errors import DuplicateKeyError
        src = inspect.getsource(server.startup_event)
        self.assertIn('keys=[("company_id", 1), ("key", 1)]', src)
        self.assertIn('name="company_trade_key", unique=True', src)
        db = FakeDb(company_trades=[], audit_logs=[])

        async def raced(*a, **k):
            raise DuplicateKeyError("E11000 duplicate key error collection: company_trades")
        with patch.object(server, "db", db), \
                patch.object(db.company_trades, "update_one", raced):
            self.assertEqual(_run(server._company_trade_add(CO_A, "dance", "u2", "test")), "Dance")
        self.assertEqual(db.audit_logs.rows, [])


class InTheDm(_Dm, unittest.TestCase):

    def roster(self, db):
        return [r for r in next(p for p in db.projects.rows if p["_id"] == THOMAS)["trade_assignments"]
                if r.get("status") != "inactive"]

    def test_an_unknown_trade_added_then_the_sub(self):
        db = _world()
        with _Ctx(db=db) as c:
            ask, offer, confirm, done = self.dm(
                c, "put dance co on 588", "Dance", "add it", "yes")
        self.assertEqual(ask, ["What trade is Dance Co?"])
        near = trades.closest("Dance", V)
        self.assertEqual(offer, [f"Dance isn't on your trade list — did you mean: {near[0]}, {near[1]} "
                                 f"or {near[2]}? Or add 'Dance' as a new trade?"])
        self.assertEqual(confirm, ["Add Dance Co (Dance) to 588 Thomas S Boyland St?"])
        self.assertTrue(done[0].startswith("Done"), done)
        self.assertIn(("Dance Co", "Dance"), [(r["company"], r["trade"]) for r in self.roster(db)])
        (row,) = db.company_trades.rows
        self.assertEqual((row["company_id"], row["label"], row["via"]), (CO_A, "Dance", "whatsapp_dm"))
        (a,) = [a for a in db.audit_logs.rows if a.get("action") == "company_trade_add"]
        self.assertEqual(a["details"]["trade"], "Dance")

    def test_a_suggestion_by_number(self):
        db = _world()
        near = trades.closest("Dance", V)
        with _Ctx(db=db) as c:
            _a, _o, confirm = self.dm(c, "put dance co on 588", "Dance", "2")
        self.assertEqual(confirm, [f"Add Dance Co ({near[1]}) to 588 Thomas S Boyland St?"])
        self.assertEqual(db.company_trades.rows, [])

    def test_a_synonym_goes_straight_to_the_question(self):
        db = _world()
        with _Ctx(db=db) as c:
            (r,) = self.dm(c, "put bright electric on 588 they're the electricians")
            (r2,) = self.dm(c, "no")
            ask, r3 = self.dm(c, "put walls inc on 588", "sheetrock")
        self.assertEqual(r, ["Add Bright Electric (Electrical) to 588 Thomas S Boyland St?"])
        self.assertEqual(r3, ["Add Walls Inc (Drywall) to 588 Thomas S Boyland St?"])
        self.assertEqual(db.company_trades.rows, [])

    def test_once_added_it_is_on_the_list(self):
        db = _world()
        with _Ctx(db=db) as c:
            self.dm(c, "put dance co on 588", "Dance", "add it", "yes")
            ask, r = self.dm(c, "put tango llc on 588", "dance")
        self.assertEqual(r, ["Add Tango Llc (Dance) to 588 Thomas S Boyland St?"])
        self.assertEqual(len(db.company_trades.rows), 1)

    def test_the_app_picker_gets_it(self):
        db = _world()
        with _Ctx(db=db) as c:
            self.dm(c, "put dance co on 588", "Dance", "add it", "yes")
            out = _run(server.get_trade_vocabulary(
                next(u for u in db.users.rows if u["_id"] == "u_admin")))
        self.assertEqual(out["company"], ["Dance"])
        self.assertEqual(out["trades"], V)

    def test_another_company_never_sees_it(self):
        db = _world()
        db.company_trades.rows.append({"company_id": "other_co", "key": "dance", "label": "Dance"})
        with _Ctx(db=db) as c:
            _a, offer = self.dm(c, "put dance co on 588", "Dance")
        self.assertIn("isn't on your trade list", offer[0])


if __name__ == "__main__":
    unittest.main()
