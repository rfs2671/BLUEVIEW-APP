"""WhatsApp sender map: who an unknown (@lid) group sender is, per company.

Pinned:
  * the People list shows this company's unknown senders with group, count,
    last message and WhatsApp display name, and never a raw @lid id;
  * a mapping is per company: company B never sees or uses company A's;
  * the attention engine resolves an owner from the map at extraction time;
  * setting and changing a mapping re-points OPEN items only; clearing it
    puts them back to unresolved; an unmapped sender stays unresolved;
  * nothing is sent to anyone, ever, by any of this.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import wa_sender_map as sm  # noqa: E402
from tests.test_whatsapp_attention import (  # noqa: E402
    CO_A, CO_B, G_A, G_B, LID, MIKE, T0, ADMIN, PM, ADMIN_B,
    _Model, _first_sight, _items, _msg, _run, _tick, _world,
)

LID_2 = "555555555555555"
COMMIT = {"anchors": [{"type": "commitment",
                       "quote": "I'll bring the anchors tomorrow",
                       "due_text": "tomorrow"}]}
PROJ_A = {"_id": "proj_a", "company_id": CO_A, "name": "Main St",
          "trade_assignments": [
              {"id": "t1", "trade": "Electrical", "company": "Bright Electric"},
              {"id": "t2", "trade": "Plumbing", "company": "Flow Plumbing",
               "status": "inactive"},
              {"id": "t3", "trade": "Drywall", "company": "bright electric"}]}
PROJ_B = {"_id": "proj_b", "company_id": CO_B, "name": "B",
          "trade_assignments": [{"id": "t9", "trade": "Steel", "company": "Iron Co"}]}


def _db():
    db = _world()
    db.projects.rows = [dict(PROJ_A), dict(PROJ_B)]
    return db


def _sends():
    sent = []

    async def no_send(*a, **k):
        sent.append((a, k))
    return sent, [patch.object(server, n, no_send)
                  for n in ("send_whatsapp_message", "send_whatsapp_dm",
                            "_waapi_post_raw")]


def _call(db, fn, *args, **kw):
    sent, patches = _sends()
    with patch.object(server, "db", db):
        for p in patches:
            p.start()
        try:
            return _run(fn(*args, **kw)), sent
        finally:
            for p in patches:
                p.stop()


def _people(db, project=PROJ_A, user=ADMIN):
    out, _ = _call(db, server.get_whatsapp_people, project["_id"],
                   project=project, current_user=user)
    return out


def _assign(db, key, name, sub, project=PROJ_A, user=ADMIN):
    return _call(db, server.set_whatsapp_person, project["_id"], key,
                 server.SenderMapBody(person_name=name, sub_company=sub),
                 project=project, current_user=user)


def _owner_item(db):
    return [i for i in _items(db) if i["type"] == "commitment"][0]


class ThePeopleList(unittest.TestCase):

    def test_unknown_senders_with_group_count_last_and_display_name(self):
        db = _db()
        _msg(db, "morning all", sender=LID, jid=f"{LID}@lid",
             sender_name="Carlos B", at=T0)
        _msg(db, "on site", sender=LID, jid=f"{LID}@lid", at=T0 + timedelta(hours=2))
        _msg(db, "hi", sender=LID_2, jid=f"{LID_2}@lid", at=T0 + timedelta(hours=1))
        _msg(db, "i'm mike", sender=MIKE, jid=f"{MIKE}@c.us")      # a known user
        _msg(db, "bot says", sender="bot")
        out = _people(db)
        rows = out["senders"]
        self.assertEqual(len(rows), 2, rows)
        carlos = next(r for r in rows if r["label"] == "Carlos B")
        self.assertEqual(carlos["message_count"], 2)
        self.assertEqual(carlos["groups"], ["Main St Project"])
        self.assertEqual(carlos["last_message_at"],
                         (T0 + timedelta(hours=2)).isoformat())
        self.assertIsNone(carlos["assigned"])
        other = next(r for r in rows if r is not carlos)
        self.assertEqual(other["label"], "Unnamed sender")
        self.assertEqual(out["unassigned"], 2)

    def test_no_raw_lid_anywhere_in_the_response(self):
        db = _db()
        _msg(db, "hello", sender=LID, jid=f"{LID}@lid")
        flat = json.dumps(_people(db))
        self.assertNotIn(LID, flat)
        self.assertNotIn("@lid", flat)
        self.assertNotIn(LID[-4:], flat)

    def test_company_choices_are_active_subs_once_then_gc_team(self):
        self.assertEqual(sm.company_choices(PROJ_A), ["Bright Electric", "GC team"])

    def test_another_company_sees_none_of_these_senders(self):
        db = _db()
        _msg(db, "hello", sender=LID, jid=f"{LID}@lid")       # in company A's group
        self.assertEqual(_people(db, PROJ_B, ADMIN_B)["senders"], [])

    def test_the_key_is_per_company(self):
        self.assertNotEqual(sm.sender_key(CO_A, f"{LID}@lid"),
                            sm.sender_key(CO_B, f"{LID}@lid"))


class AssigningAndTheAttentionEngine(unittest.TestCase):

    def _item_from(self, db, sender=LID):
        _first_sight(db)
        _msg(db, "I'll bring the anchors tomorrow", sender=sender,
             jid=f"{sender}@lid", sender_name="Carlos B")
        _tick(db, _Model(COMMIT), T0 + timedelta(hours=1))
        return _owner_item(db)

    def test_unmapped_stays_unresolved(self):
        db = _db()
        it = self._item_from(db)
        self.assertEqual((it["owner"]["status"], it["owner"]["reason"]),
                         ("unresolved", "lid_unmapped"))

    def test_assigning_backfills_the_open_item_and_sends_nothing(self):
        db = _db()
        self._item_from(db)
        key = _people(db)["senders"][0]["key"]
        (out, sent) = _assign(db, key, "Carlos Baez", "bright ELECTRIC")
        self.assertEqual(sent, [])
        self.assertEqual(out["open_items_updated"], 1)
        self.assertEqual(out["assigned"]["sub_company"], "Bright Electric")
        owner = _owner_item(db)["owner"]
        self.assertEqual((owner["kind"], owner["name"], owner["sub_company"],
                          owner["status"], owner["jid"]),
                         ("sender_map", "Carlos Baez", "Bright Electric",
                          "resolved", f"{LID}@lid"))
        row = db[sm.COLLECTION].rows[0]
        self.assertEqual((row["company_id"], row["sender_jid"], row["set_by"]),
                         (CO_A, f"{LID}@lid", "u_admin"))
        self.assertEqual(len([r for r in db.audit_logs.rows
                              if r["action"] == "whatsapp_sender_map_set"]), 1)

    def test_extraction_after_assignment_resolves_from_the_map(self):
        db = _db()
        _first_sight(db)
        _msg(db, "hello", sender=LID, jid=f"{LID}@lid")
        key = _people(db)["senders"][0]["key"]
        _assign(db, key, "Carlos Baez", "GC team")
        _msg(db, "I'll bring the anchors tomorrow", sender=LID, jid=f"{LID}@lid")
        _, sent = _tick(db, _Model(COMMIT), T0 + timedelta(hours=1))
        self.assertEqual(sent, [])
        owner = _owner_item(db)["owner"]
        self.assertEqual((owner["kind"], owner["name"], owner["sub_company"]),
                         ("sender_map", "Carlos Baez", "GC team"))

    def test_remap_updates_open_items(self):
        db = _db()
        self._item_from(db)
        key = _people(db)["senders"][0]["key"]
        _assign(db, key, "Carlos Baez", "GC team")
        (out, _) = _assign(db, key, "Carlos Baez Jr", "Bright Electric")
        self.assertEqual(out["open_items_updated"], 1)
        owner = _owner_item(db)["owner"]
        self.assertEqual((owner["name"], owner["sub_company"]),
                         ("Carlos Baez Jr", "Bright Electric"))
        self.assertEqual(len(db[sm.COLLECTION].rows), 1)

    def test_only_open_items_are_touched(self):
        db = _db()
        it = self._item_from(db)
        it["status"] = "dismissed"
        key = _people(db)["senders"][0]["key"]
        (out, _) = _assign(db, key, "Carlos Baez", "GC team")
        self.assertEqual(out["open_items_updated"], 0)
        self.assertEqual(_owner_item(db)["owner"]["status"], "unresolved")

    def test_clearing_puts_open_items_back_to_unresolved(self):
        db = _db()
        self._item_from(db)
        key = _people(db)["senders"][0]["key"]
        _assign(db, key, "Carlos Baez", "GC team")
        (out, sent) = _call(db, server.clear_whatsapp_person, "proj_a", key,
                            project=PROJ_A, current_user=ADMIN)
        self.assertEqual(sent, [])
        self.assertIsNone(out["assigned"])
        owner = _owner_item(db)["owner"]
        self.assertEqual((owner["status"], owner["kind"]), ("unresolved", "none"))
        self.assertEqual(db[sm.COLLECTION].rows, [])

    def test_a_pm_can_assign(self):
        db = _db()
        self._item_from(db)
        key = _people(db, user=PM)["senders"][0]["key"]
        (out, _) = _assign(db, key, "Carlos Baez", "GC team", user=PM)
        self.assertEqual(out["assigned"]["person_name"], "Carlos Baez")

    def test_company_must_be_from_the_list_and_name_required(self):
        db = _db()
        self._item_from(db)
        key = _people(db)["senders"][0]["key"]
        for name, sub in (("", "GC team"), ("Carlos", "Some Other Sub"),
                          ("Carlos", "Flow Plumbing")):          # inactive sub
            with self.subTest(name=name, sub=sub):
                with self.assertRaises(HTTPException) as ctx:
                    _assign(db, key, name, sub)
                self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(db[sm.COLLECTION].rows, [])


class CrossCompanyIsolation(unittest.TestCase):

    def test_company_b_cannot_assign_company_a_sender_by_key(self):
        db = _db()
        _msg(db, "hello", sender=LID, jid=f"{LID}@lid")
        key = _people(db)["senders"][0]["key"]
        with self.assertRaises(HTTPException) as ctx:
            _assign(db, key, "Mallory", "Iron Co", project=PROJ_B, user=ADMIN_B)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(db[sm.COLLECTION].rows, [])

    def test_the_same_sender_in_two_companies_maps_separately(self):
        db = _db()
        _msg(db, "hello A", sender=LID, jid=f"{LID}@lid")
        _msg(db, "hello B", group=G_B, project="proj_b", company=CO_B,
             sender=LID, jid=f"{LID}@lid")
        key_a = _people(db)["senders"][0]["key"]
        _assign(db, key_a, "Carlos Baez", "GC team")
        rows_b = _people(db, PROJ_B, ADMIN_B)["senders"]
        self.assertEqual(len(rows_b), 1)
        self.assertIsNone(rows_b[0]["assigned"])

    def test_company_a_mapping_never_resolves_company_b_items(self):
        db = _db()
        _msg(db, "hello A", sender=LID, jid=f"{LID}@lid")
        _assign(db, _people(db)["senders"][0]["key"], "Carlos Baez", "GC team")
        _first_sight(db)
        _msg(db, "I'll bring the anchors tomorrow", group=G_B, project="proj_b",
             company=CO_B, sender=LID, jid=f"{LID}@lid")
        _tick(db, _Model(COMMIT), T0 + timedelta(hours=1))
        b_item = [i for i in _items(db) if i["company_id"] == CO_B][0]
        self.assertEqual(b_item["owner"]["status"], "unresolved")

    def test_backfill_never_touches_another_companys_items(self):
        db = _db()
        _first_sight(db)
        _msg(db, "I'll bring the anchors tomorrow", group=G_B, project="proj_b",
             company=CO_B, sender=LID, jid=f"{LID}@lid")
        _tick(db, _Model(COMMIT), T0 + timedelta(hours=1))
        _msg(db, "hello A", sender=LID, jid=f"{LID}@lid")
        (out, _) = _assign(db, _people(db)["senders"][0]["key"], "Carlos", "GC team")
        self.assertEqual(out["open_items_updated"], 0)
        b_item = [i for i in _items(db) if i["company_id"] == CO_B][0]
        self.assertEqual(b_item["owner"]["status"], "unresolved")


class ScopeOfTheList(unittest.TestCase):

    def _other_project_group(self, db):
        db.projects.rows.append({"_id": "proj_a2", "company_id": CO_A,
                                 "name": "Elm St", "trade_assignments": []})
        db.whatsapp_groups.rows.append(
            {"_id": "g9", "wa_group_id": "120363000000000309@g.us",
             "group_name": "Elm St", "project_id": "proj_a2",
             "company_id": CO_A, "active": True})
        _msg(db, "elm st here", group="120363000000000309@g.us",
             project="proj_a2", sender=LID_2, jid=f"{LID_2}@lid",
             sender_name="Elmo")

    def test_a_pm_sees_only_the_groups_of_the_project_they_opened(self):
        db = _db()
        _msg(db, "main st", sender=LID, jid=f"{LID}@lid", sender_name="Carlos")
        self._other_project_group(db)
        pm_rows = _people(db, user=PM)["senders"]
        self.assertEqual([r["label"] for r in pm_rows], ["Carlos"])
        admin_rows = _people(db)["senders"]
        self.assertEqual(sorted(r["label"] for r in admin_rows), ["Carlos", "Elmo"])

    def test_a_pm_cannot_map_a_sender_from_another_project(self):
        db = _db()
        self._other_project_group(db)
        key = next(r["key"] for r in _people(db)["senders"] if r["label"] == "Elmo")
        with self.assertRaises(HTTPException) as ctx:
            _assign(db, key, "Elmo", "GC team", user=PM)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_a_reused_group_never_shows_the_previous_companys_history(self):
        """Group G_A was company B's before company A linked it."""
        db = _db()
        _msg(db, "old B chatter", company=CO_B, sender=LID_2,
             jid=f"{LID_2}@lid", sender_name="From B")
        _msg(db, "A now", sender=LID, jid=f"{LID}@lid", sender_name="Carlos")
        labels = [r["label"] for r in _people(db)["senders"]]
        self.assertEqual(labels, ["Carlos"])


class TheDisplayName(unittest.TestCase):

    def test_an_id_or_number_as_display_name_is_never_shown(self):
        for bad in ("123456789012345@lid", "+1 (718) 555-0101", "7185550101"):
            with self.subTest(name=bad):
                self.assertEqual(sm.safe_push_name(bad), "")
                self.assertEqual(sm.label(bad, f"{LID}@lid"), "Unnamed sender")
        db = _db()
        _msg(db, "hi", sender=LID, jid=f"{LID}@lid", sender_name=f"{LID}@lid")
        row = _people(db)["senders"][0]
        self.assertIsNone(row["push_name"])
        self.assertNotIn(LID, json.dumps(row))

    def test_webhook_notify_name_is_parsed_and_cleaned(self):
        parsed = server.parse_inbound_message({"data": {"message": {
            "from": G_A, "author": f"{LID}@lid", "body": "hi", "type": "chat",
            "_data": {"notifyName": "  Carlos   B  "}}}})
        self.assertEqual(parsed.get("push_name"), "Carlos B")

    def test_label_never_shows_lid_digits(self):
        self.assertEqual(sm.label("", f"{LID}@lid"), "Unnamed sender")
        self.assertEqual(sm.label("", f"{MIKE}@c.us"), "Unnamed sender …0101")
        self.assertEqual(sm.label("Carlos", f"{LID}@lid"), "Carlos")


if __name__ == "__main__":
    unittest.main()
