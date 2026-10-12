"""588, Sun Oct 11 10:36 PM: the 8:31 PM walk, still open at "Who gets what?",
got a photo captioned "4d tile chipped". The bot read the caption as a name
("I don't know 4d tile chipped on this job…") and showed again
"electrical → Yeyzmar B Bate (Power Direct)" -- a worker who had only checked
in, stored by the walk before #755.

1. A photo at ANY stage after capture is the next item on the walk: "Added #4
   'Tile chipped' (Apt 4D). Back to: Who gets what?". Never read as a name.
2. Stored names and suggestions are checked against who may be messaged every
   time they are shown; one that may not is "?" again. A one-off script clears
   them from open walks.
3. A caption's location is its own field, wherever it is: "4d tile chipped"
   and "tile chipped 4d" are Apt 4D, "Tile chipped" (the words as sent kept).
4. Numbers never change once shown: a new item takes the next free one.
"""

from __future__ import annotations

import unittest
from datetime import timedelta
from unittest.mock import patch

from tests.test_punch_walkthrough_2031 import CO, NOW, P588, _Walk, _world  # noqa: F401
from tests._fake_mongo import FakeDb
import server
from lib import punch

YEYZMAR = {"kind": "worker", "id": "w1", "name": "Yeyzmar B Bate", "company": "Power Direct",
           "jid": "17185550199@c.us"}
DOV = {"kind": "sender_map", "id": "m_dov", "name": "Dov Klein", "company": "Power Direct",
       "jid": "17185550222@c.us", "not_on_job": False}


def _old_walk(status="assign", assign=None, whole=None):
    """The 8:31 PM walk as stored before #755: three items, Yeyzmar on electrical."""
    items = [{"n": i, "captured": i, "text": t, "floor": f, "area": a, "trade": tr,
              "photo_key": f"k{i}", "message_id": f"m{i}", "at": NOW - timedelta(hours=2)}
             for i, (t, f, a, tr) in enumerate([("Bulb burnt", "4", "Apt 4F", "electrical"),
                                                ("Outlet loose", "4", "Apt 4A", "electrical"),
                                                ("Faucet leaking", "2", "Apt 2D", "plumbing")], 1)]
    return {"_id": "walk831", "user_id": "u_roy", "company_id": CO, "project_id": "p588",
            "chat": "17185550100@c.us", "job_name": "588 Thomas St", "job_code": "588",
            "status": status, "items": items, "photos": [],
            "assign": assign if assign is not None else {"electrical": dict(YEYZMAR),
                                                         "plumbing": None},
            "whole": whole, "created_at": NOW - timedelta(hours=2),
            "updated_at": NOW - timedelta(minutes=30)}


class The1036Photo(_Walk):

    def setUp(self):
        super().setUp()
        self.db[punch.SESSIONS].rows.append(_old_walk())

    def test_exactly_as_sent(self):
        (out,) = self.turn("4d tile chipped", photo=True)
        self.assertTrue(out.startswith("Added #4 'Tile chipped' (Apt 4D). Back to: Who gets what?"),
                        out)
        self.assertNotIn("I don't know", out)
        # The stored worker is taken off, and the walker is told.
        self.assertIn("Taken off: electrical → Yeyzmar B Bate", out)
        self.assertIn("• electrical → ?", out)
        self.assertIn("• tile → ?", out)                 # the new item's trade, asked
        s = self.sess()
        self.assertEqual(s["status"], "assign")
        it = next(i for i in s["items"] if i["captured"] == 4)
        self.assertEqual((it["n"], it["text"], it["floor"], it["area"]),
                         (4, "Tile chipped", "4", "Apt 4D"))
        self.assertEqual(it["said"], "4d tile chipped")
        self.assertIsNone(s["assign"]["electrical"])
        self.assertEqual(len(s["photos"]), 1)
        self.assertEqual(self.assistant, [])

    def test_never_read_as_a_name_however_it_reads(self):
        for caption in ("Chris", "all → Chris", "ok", "send"):
            with self.subTest(caption):
                self.setUp()
                (out,) = self.turn(caption, photo=True)
                self.assertTrue(out.startswith("Added #4"), out)
                self.assertNotEqual(self.sess()["status"], "sent")
                self.assertEqual(self.db[punch.COLLECTION].rows, [])     # nothing sent

    def test_no_location_asks_where_then_back(self):
        (q,) = self.turn("tile chipped", photo=True)
        self.assertEqual(q, "Added #4 'tile chipped'. Where is #4 'tile chipped'? "
                            "(floor + unit, or a named area)")
        self.assertEqual(self.sess()["status"], "locating")
        (out,) = self.turn("4D")
        self.assertTrue(out.startswith("Added #4 'tile chipped' (Apt 4D). Back to: Who gets what?"),
                        out)
        self.assertEqual(self.sess()["status"], "assign")

    def test_no_words_asks_what_then_back(self):
        (q,) = self.turn("", photo=True)
        self.assertEqual(q, 'Added #4 (photo). What is it, and where? (e.g. "4D tile chipped")')
        (out,) = self.turn("4d tile chipped")
        self.assertTrue(out.startswith("Added #4 'Tile chipped' (Apt 4D). Back to: Who gets what?"),
                        out)


class EveryStage(_Walk):

    def _walk(self, **kw):
        self.db[punch.SESSIONS].rows.append(_old_walk(**kw))

    def test_the_draft(self):
        self._walk(status="draft", assign={})
        (out,) = self.turn("2b paint scuff", photo=True)
        # The next free number, shown in its place (Floor 2 first): #4.
        self.assertTrue(out.startswith("Added #4 'Paint scuff' (Apt 2B). Back to: the draft"), out)
        self.assertIn("*Floor 2*\n_paint_\n4. 📷 Paint scuff (Apt 2B)", out)
        self.assertEqual(self.sess()["status"], "draft")

    def test_the_recap_whole_list_takes_it(self):
        chris = {"kind": "user", "id": "u_chris", "name": "Chris Weiss", "company": "GC",
                 "jid": "17185550111@c.us"}
        self._walk(status="recap", assign={"electrical": chris, "plumbing": chris}, whole=chris)
        (out,) = self.turn("4d tile chipped", photo=True)
        self.assertTrue(out.startswith("Added #4 'Tile chipped' (Apt 4D). Back to: the recap"), out)
        self.assertIn("Chris Weiss (GC team): #1, #2, #3, #4", out)
        self.assertEqual(self.sess()["assign"]["tile"]["name"], "Chris Weiss")
        self.assertEqual(self.sess()["status"], "recap")

    def test_the_recap_a_trade_with_someone(self):
        self._walk(status="recap", assign={"electrical": dict(DOV), "plumbing": dict(DOV)})
        (out,) = self.turn("4d outlet cover missing", photo=True)
        self.assertTrue(out.startswith("Added #4 'Outlet cover missing' (Apt 4D). "
                                       "Back to: the recap"), out)
        self.assertIn("Dov Klein (Power Direct): #1, #2, #3, #4", out)

    def test_the_recap_a_new_trade_is_asked(self):
        self._walk(status="recap", assign={"electrical": dict(DOV), "plumbing": dict(DOV)})
        (out,) = self.turn("4d tile chipped", photo=True)
        self.assertTrue(out.startswith("Added #4 'Tile chipped' (Apt 4D). Back to: Who gets what?"),
                        out)
        self.assertIn("• tile → ?", out)
        self.assertEqual(self.sess()["status"], "assign")

    def test_no_trade_goes_to_the_draft(self):
        self._walk(status="assign", assign={"electrical": dict(DOV), "plumbing": dict(DOV)})
        (out,) = self.turn("4d stain on the wall", photo=True)
        self.assertTrue(out.startswith("Added #4 'Stain on the wall' (Apt 4D). Back to: the draft."),
                        out)
        self.assertIn("needs a trade", out)
        self.assertEqual(self.sess()["status"], "draft")


class NumbersNeverChange(_Walk):
    """A number, once shown, is that item for good: a new one takes the next
    free number, the draft shows them by floor and trade (#4, #3, #1, #2),
    and an edit always means the number the walker read."""

    def test_a_floor_2_photo_then_2_to_electrical(self):
        walk = _old_walk(status="draft", assign={})
        walk["items"][1].update(text="Stain on wall", trade=punch.UNKNOWN)   # #2, Floor 4
        self.db[punch.SESSIONS].rows.append(walk)
        (out,) = self.turn("2b paint scuff", photo=True)
        self.assertTrue(out.startswith("Added #4 'Paint scuff' (Apt 2B)."), out)
        import re
        self.assertEqual([int(m.group(1)) for m in re.finditer(r"^(\d+)\. ", out, re.M)],
                         [4, 3, 1, 2])                     # by floor, then trade
        (draft,) = self.turn("2 → electrical")
        items = {it["n"]: it for it in self.sess()["items"]}
        self.assertEqual(items[2]["text"], "Stain on wall")
        self.assertEqual(items[2]["trade"], "electrical")  # the original #2
        self.assertEqual(items[4]["trade"], "paint")       # not the new Floor 2 item
        self.assertEqual(items[1]["text"], "Bulb burnt")
        self.assertIn("2. 📷 Stain on wall (Apt 4A) — electrical", draft)

    def test_drop_and_add_never_reuse_a_number(self):
        self.db[punch.SESSIONS].rows.append(_old_walk(status="draft", assign={}))
        self.turn("drop 3")
        (out,) = self.turn("add: 4c door sticks")
        self.assertIn("4. Door sticks (Apt 4C)", out)      # never #3 again
        (out,) = self.turn("4d tile chipped", photo=True)
        self.assertTrue(out.startswith("Added #5 'Tile chipped' (Apt 4D)."), out)
        self.assertEqual(sorted(it["n"] for it in self.sess()["items"]), [1, 2, 3, 4, 5])

    def test_the_locations_never_renumber(self):
        self.turn("Bulb burnt", photo=True)
        self.turn("Faucet leaking 2D", photo=True)
        (q,) = self.turn("done")
        self.assertIn("#1 'Bulb burnt'", q)
        (draft,) = self.turn("4F")
        import re
        self.assertEqual([int(m.group(1)) for m in re.finditer(r"^(\d+)\. ", draft, re.M)], [2, 1])


class StoredNamesAreCheckedEachTime(_Walk):

    def test_a_recap_holding_the_worker_is_never_sent(self):
        self.db[punch.SESSIONS].rows.append(_old_walk(
            status="recap", assign={"electrical": dict(YEYZMAR), "plumbing": dict(DOV)}))
        (out,) = self.turn("ok")
        self.assertTrue(out.startswith("Taken off: electrical → Yeyzmar B Bate (not in People, "
                                       "your users, or a sub's punch contact)."), out)
        self.assertIn("• electrical → ?", out)
        self.assertEqual(self.sess()["status"], "assign")
        self.assertEqual(self.db[punch.COLLECTION].rows, [])

    def test_a_whole_list_worker_is_cleared(self):
        self.db[punch.SESSIONS].rows.append(_old_walk(
            status="recap", assign={"electrical": dict(YEYZMAR), "plumbing": dict(YEYZMAR)},
            whole=dict(YEYZMAR)))
        (out,) = self.turn("ok")
        self.assertIn("all → Yeyzmar B Bate", out)
        self.assertIsNone(self.sess()["whole"])
        self.assertEqual(self.db[punch.COLLECTION].rows, [])

    def test_a_valid_name_stays(self):
        self.db[punch.SESSIONS].rows.append(_old_walk(
            status="assign", assign={"electrical": dict(DOV), "plumbing": None}))
        (out,) = self.turn("plumbing → Sam")
        self.assertNotIn("Taken off", out)
        self.assertEqual(self.sess()["assign"]["electrical"]["name"], "Dov Klein")

    def test_a_last_assignee_who_was_a_worker_is_not_suggested(self):
        self.db[punch.COLLECTION].rows.append({
            "_id": "p588:P-588-1", "project_id": "p588", "trade": "electrical", "pid": "P-588-1",
            "assigned_at": NOW - timedelta(days=1), "assignee": dict(YEYZMAR)})
        self.turn("Bulb burnt 4F", photo=True)
        self.turn("done")
        (who,) = self.turn("send")
        self.assertIn("electrical → ?", who)
        self.assertNotIn("Yeyzmar", who)


class TheOneOffScript(unittest.TestCase):

    def _run(self, *argv):
        from scripts import punch_assignees_revalidate as s
        db = _world()
        db[punch.SESSIONS].rows.extend([
            _old_walk(status="recap", assign={"electrical": dict(YEYZMAR), "plumbing": dict(DOV)}),
            {**_old_walk(status="sent"), "_id": "done_walk"},           # closed: left alone
            {**_old_walk(status="assign", assign={"plumbing": dict(DOV)}), "_id": "fine_walk"}])
        out = []
        with patch("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a)))), \
                patch.object(server, "db", db):
            s.main(list(argv), db=db, server=server)
        return db, "\n".join(out)

    def test_dry_run_then_guarded_apply(self):
        db, out = self._run("--name", "Yeyzmar")
        self.assertIn("walk walk831 (588 Thomas St, recap): electrical → Yeyzmar B Bate [worker] -> ?",
                      out)
        self.assertIn("2 open walk(s)", out)                                 # "sent" is not open
        self.assertIn("1 with a name taken off (dry run", out)
        walk = db[punch.SESSIONS].rows[0]
        self.assertEqual(walk["assign"]["electrical"]["name"], "Yeyzmar B Bate")   # nothing written
        self.assertEqual(db.audit_logs.rows, [])

        db, out = self._run("--name", "Yeyzmar", "--i-know", "--reason",
                            "clear the 8:31 PM walk's checked-in worker", "--session", "s1")
        walk, closed, fine = db[punch.SESSIONS].rows
        self.assertIsNone(walk["assign"]["electrical"])
        self.assertEqual(walk["assign"]["plumbing"]["name"], "Dov Klein")    # kept
        self.assertEqual(walk["status"], "assign")                           # off the recap
        self.assertEqual(closed["assign"]["electrical"]["name"], "Yeyzmar B Bate")  # not open
        self.assertEqual(fine["assign"]["plumbing"]["name"], "Dov Klein")
        self.assertIn("checked-in worker", str(db.audit_logs.rows))
        with self.assertRaises(SystemExit):
            self._run("--apply")                                             # the old flag


class Captions(unittest.TestCase):

    def test_a_leading_location(self):
        for said, text, floor, area in [
                ("4d tile chipped", "Tile chipped", "4", "Apt 4D"),
                ("4D tile chipped", "Tile chipped", "4", "Apt 4D"),
                ("Apt 4D tile chipped", "Tile chipped", "4", "Apt 4D"),
                ("12a outlet loose", "Outlet loose", "12", "Apt 12A"),
                ("piso 6 falta pintura en el pasillo", "Falta pintura", "6", "hallway"),   # both ends
                ("tile chipped 4d", "Tile chipped", "4", "Apt 4D"),        # at the end too
                ("Faucet leaking 2D", "Faucet leaking", "2", "Apt 2D"),
                ("stain on ceiling 5th fl", "Stain on ceiling", "5", punch.UNKNOWN),
                ("4d", "4d", "4", "Apt 4D"),                               # nothing after it
                ("2x4 stud bent", "2x4 stud bent", punch.UNKNOWN, punch.UNKNOWN)]:
            with self.subTest(said):
                it = punch.new_item(1, said, photo_key=None, message_id="m")
                self.assertEqual((it["text"], it["floor"], it["area"]), (text, floor, area))
                self.assertEqual(it.get("said", said), said)

    def test_the_added_line(self):
        it = punch.new_item(4, "4d tile chipped", photo_key=None, message_id="m")
        self.assertEqual(punch.added_text(it), "Added #4 'Tile chipped' (Apt 4D).")


if __name__ == "__main__":
    unittest.main()
