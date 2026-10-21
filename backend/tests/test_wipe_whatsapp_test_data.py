"""The WhatsApp test-data wipe: what it scopes, a full dry run and execute
against an in-memory database holding two companies, and what it prints.

It is never run against a real database here. Every phone number below is a
fictional 555-01xx number."""

import copy
import io
import os
import re
import sys
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from scripts import wipe_whatsapp_test_data as w  # noqa: E402
from scripts.prod_guard import audited  # noqa: E402
from tests._fake_mongo import matches  # noqa: E402

CO_A = "aaaaaaaaaaaaaaaaaaaaaaaa"
CO_B = "bbbbbbbbbbbbbbbbbbbbbbbb"
PA1, PA2, PB = "a1a1a1a1a1a1a1a1a1a1a1a1", "a2a2a2a2a2a2a2a2a2a2a2a2", "b1b1b1b1b1b1b1b1b1b1b1b1"
UA1, UA2, UA3 = "ua1", "ua2", "ua3"
UB, UB2 = "ub1", "ub2"
GA = "120363000000001111@g.us"        # A's linked group
GA_PEND = "120363000000002222@g.us"   # A's pending group
GS = "120363000000003333@g.us"        # bound to A AND to B: shared
GB = "120363000000009999@g.us"        # B's group
LID_A2 = "999000111222"               # UA2 opted in from a privacy id

#: Every number and id that must never be printed in full.
SECRETS = ("5550100001", "5550100002", "5550100003", "5550100009", "5550107777",
           LID_A2, "120363000000001111", "120363000000002222",
           "120363000000003333", "120363000000009999")


# ── a synchronous in-memory Mongo, enough for this script ──────────────────

class _Res:
    def __init__(self, deleted=0, modified=0):
        self.deleted_count = deleted
        self.modified_count = modified
        self.matched_count = modified


def _unset(doc, dotted):
    parts = dotted.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.get(p) if isinstance(cur, dict) else None
        if cur is None:
            return False
    if isinstance(cur, dict) and parts[-1] in cur:
        del cur[parts[-1]]
        return True
    return False


class _Coll:
    def __init__(self):
        self.rows = []

    def find(self, flt=None, projection=None):
        return [copy.deepcopy(r) for r in self.rows if matches(r, flt or {})]

    def find_one(self, flt=None, projection=None):
        got = self.find(flt)
        return got[0] if got else None

    def count_documents(self, flt):
        return sum(1 for r in self.rows if matches(r, flt or {}))

    def insert_one(self, doc):
        self.rows.append(copy.deepcopy(doc))
        return _Res()

    def delete_many(self, flt):
        before = len(self.rows)
        self.rows = [r for r in self.rows if not matches(r, flt or {})]
        return _Res(deleted=before - len(self.rows))

    def update_many(self, flt, update):
        n = 0
        for r in self.rows:
            if not matches(r, flt or {}):
                continue
            changed = False
            for field in (update.get("$unset") or {}):
                changed |= _unset(r, field)
            n += changed
        return _Res(modified=n)


class _Db:
    def __init__(self):
        self._c = {}

    def __getitem__(self, name):
        return self._c.setdefault(name, _Coll())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def snapshot(self):
        return copy.deepcopy({n: c.rows for n, c in self._c.items() if c.rows})


def _world():
    """Two companies with WhatsApp rows of every kind, plus rows that are not
    WhatsApp's, plus the rows a wipe of A must leave alone."""
    db = _Db()
    db.companies.rows += [{"_id": CO_A, "name": "Alpha Test Builders"},
                          {"_id": CO_B, "name": "Bravo Builders"}]
    db.projects.rows += [{"_id": PA1, "company_id": CO_A, "name": "588 Test St"},
                         {"_id": PA2, "company_id": CO_A, "name": "12 Other Ave"},
                         {"_id": PB, "company_id": CO_B, "name": "B job"}]
    db.users.rows += [
        {"_id": UA1, "company_id": CO_A, "email": "owner@alpha.test", "phone": "(555) 010-0001"},
        {"_id": UA2, "company_id": CO_A, "email": "pm@alpha.test", "phone": "+1 555 010 0002"},
        # The same person works for both companies: this phone is SHARED.
        {"_id": UA3, "company_id": CO_A, "email": "both@alpha.test", "phone": "555-010-0003"},
        {"_id": UB, "company_id": CO_B, "email": "owner@bravo.test", "phone": "555-010-0009"},
        {"_id": UB2, "company_id": CO_B, "email": "both@bravo.test", "phone": "5550100003"},
    ]
    db.whatsapp_groups.rows += [
        {"_id": "ga", "wa_group_id": GA, "company_id": CO_A, "project_id": PA1,
         "group_name": "588 Test St — GC"},
        {"_id": "gs_a", "wa_group_id": GS, "company_id": CO_A, "project_id": PA2,
         "group_name": "Shared yard"},
        {"_id": "gs_b", "wa_group_id": GS, "company_id": CO_B, "project_id": PB,
         "group_name": "Shared yard"},
        {"_id": "gb", "wa_group_id": GB, "company_id": CO_B, "project_id": PB,
         "group_name": "B job group"},
    ]
    db.whatsapp_pending_groups.rows += [
        {"_id": "pa", "group_id": GA_PEND, "company_id": CO_A, "group_name": "New test group"},
        {"_id": "pb", "group_id": "120363000000008888@g.us", "company_id": CO_B}]
    db.whatsapp_link_codes.rows += [
        {"_id": "lc_a", "code": "111111", "project_id": PA1, "company_id": CO_A},
        {"_id": "lc_b", "code": "222222", "project_id": PB, "company_id": CO_B}]
    db.whatsapp_messages.rows += [
        {"_id": "mA1", "group_id": GA, "company_id": CO_A, "project_id": PA1, "body": "x",
         "voice": {"audio_key": "wa-audio/a1/g/mA1.ogg"}},
        {"_id": "mA2", "group_id": GA, "company_id": CO_A, "project_id": PA1, "body": "x",
         "photo": {"key": "wa-group-photos/a/a1/mA2.jpg", "shared": False}},
        {"_id": "mA3", "group_id": GA, "company_id": CO_A, "project_id": PA1, "body": "done",
         "photo": {"key": "wa-photos/a1/msg/mA3.jpg", "shared": True},
         "photo_key": "wa-photos/a1/msg/mA3.jpg"},
        # Its completion photo is ALSO named by a kept row of B.
        {"_id": "mA4", "group_id": GA, "company_id": CO_A, "project_id": PA1, "body": "done",
         "photo_key": "wa-photos/a1/msg/shared.jpg"},
        {"_id": "mA_bot", "group_id": GA, "sender": "bot", "body": "unbound reply"},
        {"_id": "mA_dm_in", "group_id": "15550100001@c.us", "is_dm": True,
         "company_id": CO_A, "user_id": UA1, "body": "hi"},
        {"_id": "mA_dm_bot", "group_id": f"{LID_A2}@lid", "is_dm": True, "sender": "bot",
         "body": "brief"},
        {"_id": "mS_A", "group_id": GS, "company_id": CO_A, "project_id": PA2, "body": "x"},
        {"_id": "mS_B", "group_id": GS, "company_id": CO_B, "project_id": PB, "body": "x"},
        {"_id": "mS_bot", "group_id": GS, "sender": "bot", "body": "x"},
        {"_id": "mB1", "group_id": GB, "company_id": CO_B, "project_id": PB, "body": "x",
         "voice": {"audio_key": "wa-audio/b1/g/mB1.ogg"}},
        {"_id": "mB_dm_bot", "group_id": "15550100009@c.us", "is_dm": True, "sender": "bot"},
        {"_id": "mShared_dm_bot", "group_id": "15550100003@c.us", "is_dm": True,
         "sender": "bot"},
    ]
    db.whatsapp_conversation_state.rows += [
        {"_id": "cs1", "kind": "bot_session", "group_id": GA, "sender": "x"},
        {"_id": "cs2", "kind": "dm_action", "group_id": "15550100001", "sender": ""},
        {"_id": "cs3", "kind": "checklist", "group_id": GA, "company_id": CO_A},
        {"_id": "cs_b", "kind": "dm_action", "group_id": "15550100009", "sender": ""},
        {"_id": "cs_shared", "kind": "dm_action", "group_id": "15550100003", "sender": ""},
        {"_id": "cs_gb", "kind": "unavailable", "group_id": GB},
    ]
    db.whatsapp_dm_answers.rows += [{"_id": "da", "company_id": CO_A, "user_id": UA1},
                                    {"_id": "db", "company_id": CO_B, "user_id": UB}]
    db.whatsapp_voice_events.rows += [{"_id": "ve_a", "company_id": CO_A, "group_id": GA},
                                      {"_id": "ve_b", "company_id": CO_B, "group_id": GB}]
    db.whatsapp_optins.rows += [
        {"_id": "o1", "phone": "15550100001", "user_id": UA1, "company_id": CO_A,
         "chat_id": "15550100001@c.us", "chat_digits": "15550100001", "status": "active"},
        {"_id": "o2", "phone": "15550100002", "user_id": UA2, "company_id": CO_A,
         "chat_id": f"{LID_A2}@lid", "chat_digits": LID_A2, "status": "active"},
        {"_id": "o_stop_a", "phone": "15550100004", "user_id": None, "company_id": None,
         "chat_digits": "15550100001", "status": "opted_out"},
        {"_id": "o_b", "phone": "15550100009", "user_id": UB, "company_id": CO_B,
         "status": "active"},
        {"_id": "o_unknown", "phone": "15550107777", "user_id": None, "company_id": None,
         "status": "opted_out"},
    ]
    db.whatsapp_dm_reply_windows.rows += [{"_id": "15550100001"}, {"_id": "15550100009"},
                                          {"_id": "15550100003"}]
    db.whatsapp_notification_ledger.rows += [
        {"_id": f"{UA1}:-:morning_brief:2026-10-01", "user_id": UA1, "company_id": CO_A},
        {"_id": f"gc:{PA1}:violation:x", "company_id": CO_A, "project_id": PA1},
        {"_id": f"{UB}:-:morning_brief:2026-10-01", "user_id": UB, "company_id": CO_B}]
    db.whatsapp_connect_codes.rows += [{"_id": "c1", "user_id": UA1},
                                       {"_id": "c2", "user_id": UB}]
    db.whatsapp_dm_welcomes.rows += [
        {"_id": UA1, "company_id": CO_A, "welcomed_at": "2026-10-01", "card": True},
        {"_id": UA2, "welcomed_at": "2026-10-01"},          # no company_id: by user id
        {"_id": UB, "company_id": CO_B, "welcomed_at": "2026-10-01", "card": False}]
    db.whatsapp_send_log.rows += [{"_id": "sl1", "group_id": GA}, {"_id": "sl_s", "group_id": GS},
                                  {"_id": "sl_b", "group_id": GB}]
    db.whatsapp_checklists.rows += [{"_id": "ck_a", "project_id": PA1, "company_id": CO_A},
                                    {"_id": "ck_b", "project_id": PB, "company_id": CO_B}]
    db.whatsapp_sender_map.rows += [{"_id": "sm_a", "company_id": CO_A},
                                    {"_id": "sm_b", "company_id": CO_B}]
    db.whatsapp_lid_phone.rows += [{"_id": f"{CO_A}|1@lid"},
                                   {"_id": f"{CO_B}|1@lid", "company_id": CO_B}]
    db.whatsapp_sender_language.rows += [{"_id": "sla", "company_id": CO_A},
                                         {"_id": "slb", "company_id": CO_B}]
    db.voice_daily.rows += [{"_id": f"{CO_A}|2026-10-01", "count": 3},
                            {"_id": f"{CO_B}|2026-10-01", "company_id": CO_B, "count": 1}]
    db.whatsapp_contact_card_log.rows += [{"_id": "15550100002"}, {"_id": "15550107777"}]
    db.wa_quiet_queue.rows += [{"_id": "q_a", "company_id": CO_A, "project_id": PA1},
                               {"_id": "q_b", "company_id": CO_B, "project_id": PB}]
    for c in ("attention_items", "attention_cursors", "attention_metrics", "chase_shadow",
              "upcoming_cursors"):
        db[c].rows += [{"_id": f"{c}_a", "company_id": CO_A, "project_id": PA1, "group_id": GA},
                       {"_id": f"{c}_b", "company_id": CO_B, "project_id": PB, "group_id": GB}]
    db.upcoming_events.rows += [
        {"_id": "ue_chat", "company_id": CO_A, "project_id": PA1, "source": "chat"},
        {"_id": "ue_dm", "company_id": CO_A, "project_id": None, "user_id": UA1, "source": "dm"},
        {"_id": "ue_city", "company_id": CO_A, "project_id": PA1, "source": "city"},
        {"_id": "ue_b", "company_id": CO_B, "project_id": PB, "source": "chat"}]
    db.project_memory.rows += [
        {"_id": "wa:mA1", "company_id": CO_A, "project_id": PA1, "source": "whatsapp"},
        {"_id": "att:1", "company_id": CO_A, "project_id": PA1, "source": "attention"},
        {"_id": "dr:1:general", "company_id": CO_A, "project_id": PA1, "source": "daily_report"},
        {"_id": "wa:mB1", "company_id": CO_B, "project_id": PB, "source": "whatsapp"}]
    db.project_memory_state.rows += [{"_id": "cursor", "wa_id": "mA1", "gc_after": "wa:mA1"}]
    db.punch_items.rows += [
        {"_id": f"{PA1}:P-1", "company_id": CO_A, "project_id": PA1,
         "photo_key": "wa-photos/a1/s1/1.jpg", "extra_photos": ["wa-photos/a1/s1/2.jpg"],
         "completion": {"photo_key": "wa-photos/a1/msg/mA3.jpg"}},
        {"_id": f"{PB}:P-1", "company_id": CO_B, "project_id": PB,
         "photo_key": "wa-photos/b1/s9/1.jpg",
         "completion": {"photo_key": "wa-photos/a1/msg/shared.jpg"}}]
    db.punch_sessions.rows += [
        {"_id": "s1", "company_id": CO_A, "project_id": PA1, "user_id": UA1,
         "items": [{"photo_key": "wa-photos/a1/s1/1.jpg"}],
         "photos": [{"key": "wa-photos/a1/s1/1.jpg"}, {"key": "wa-photos/a1/s1/3.jpg"}]},
        {"_id": "s9", "company_id": CO_B, "project_id": PB, "user_id": UB,
         "items": [{"photo_key": "wa-photos/b1/s9/1.jpg"}]}]
    db.punch_links.rows += [{"_id": "pl_a", "company_id": CO_A, "project_id": PA1},
                            {"_id": "pl_b", "company_id": CO_B, "project_id": PB}]
    db.punch_counters.rows += [{"_id": PA1, "seq": 3}, {"_id": PB, "seq": 1}]
    db.punch_leases.rows += [{"_id": f"walker:{UA1}"}, {"_id": f"walker:{UB}"}]
    db.brief_log.rows += [{"_id": f"{UA1}:2026-10-01", "user_id": UA1, "company_id": CO_A},
                          {"_id": f"{UB}:2026-10-01", "user_id": UB, "company_id": CO_B}]
    db.outbound_failures.rows += [{"_id": "f_a", "company_id": CO_A, "user_id": UA1},
                                  {"_id": "f_b", "company_id": CO_B, "user_id": UB}]
    db.notification_preferences.rows += [
        {"_id": "np_a", "user_id": None, "scope": "project", "project_id": PA1,
         "company_id": CO_A,
         "whatsapp_project": {"gc_group_id": GA, "gc_group_confirmed": True,
                              "gc_declined": [GS], "punch_to": "one", "punch_to_user": UA1,
                              "punch_contacts": {"t1": "sm_a"}, "violation_alerts": False,
                              "send_window": {"mode": "work_hours"}}},
        {"_id": "np_user", "user_id": UA1, "scope": "user", "company_id": CO_A,
         "whatsapp": {"summary_frequency": "daily"}},
        {"_id": "np_b", "user_id": None, "scope": "project", "project_id": PB,
         "company_id": CO_B, "whatsapp_project": {"gc_group_id": GB,
                                                  "gc_group_confirmed": True}}]
    # Not WhatsApp's at all.
    db.checkins.rows += [{"_id": "ci_a", "company_id": CO_A, "project_id": PA1}]
    db.daily_logs.rows += [{"_id": "dl_a", "project_id": PA1}]
    db.audit_logs.rows += [{"_id": "al", "resource_id": PA1}]
    db.whatsapp_config.rows += [{"_id": "cfg_a", "company_id": CO_A}]
    db.whatsapp_company_settings.rows += [{"_id": CO_A, "shabbos_off": True}]
    db.whatsapp_contacts.rows += [{"_id": "wc_a", "company_id": CO_A, "phone": "15550100001"}]
    db.retention_ledger.rows += [{"_id": "rl", "company_id": CO_A}]
    db.vision_calls.rows += [{"_id": "vc", "company_id": CO_A}]
    db.whatsapp_webhook_log.rows += [{"_id": "wh1"}, {"_id": "wh2"}]
    db.whatsapp_audio_probe.rows += [{"_id": "ap1"}]
    return db


#: Company A's R2 objects a correct run deletes.
A_KEYS = {"wa-audio/a1/g/mA1.ogg", "wa-group-photos/a/a1/mA2.jpg", "wa-photos/a1/msg/mA3.jpg",
          "wa-photos/a1/s1/1.jpg", "wa-photos/a1/s1/2.jpg", "wa-photos/a1/s1/1-thumb.jpg",
          "wa-photos/a1/s1/2-thumb.jpg", "wa-photos/a1/s1/3.jpg"}
#: Named by A's message AND by B's kept punch item: never deleted.
SHARED_KEY = "wa-photos/a1/msg/shared.jpg"
B_KEYS = {"wa-audio/b1/g/mB1.ogg", "wa-photos/b1/s9/1.jpg", "wa-photos/b1/s9/1-thumb.jpg"}


class _NotFound(Exception):
    def __init__(self, code="404", status=404):
        super().__init__(code)
        self.response = {"Error": {"Code": code},
                         "ResponseMetadata": {"HTTPStatusCode": status}}


class FakeR2:
    def __init__(self, stored=(), stuck=()):
        self.stored, self.stuck = set(stored), set(stuck)
        self.deleted, self.heads = [], []

    def head_object(self, Bucket, Key):
        self.heads.append(Key)
        if Key not in self.stored:
            raise _NotFound()
        return {}

    def delete_object(self, Bucket, Key):
        if Key not in self.stuck:
            self.stored.discard(Key)
            self.deleted.append(Key)
        return {}

    def delete_objects(self, **kw):
        raise AssertionError("batch delete_objects must not be called")

    def list_objects_v2(self, **kw):
        raise AssertionError("bucket listing must not be called")


def _args(**kw):
    base = dict(email="owner@alpha.test", company=None, leave_groups=False,
                bot_not_in_group=[], waapi_leave_action="leave-group",
                include_global_debug=False, i_know=True, reason="test", session="s")
    base.update(kw)
    return Namespace(**base)


def _run(db, write, args=None, r2=None, leave_ok=True):
    r2 = r2 if r2 is not None else FakeR2(stored=A_KEYS | B_KEYS | {SHARED_KEY})
    left = []

    def leave(action, chat_id):
        left.append(chat_id)
        return (leave_ok(chat_id) if callable(leave_ok) else leave_ok), "http 200"

    buf = io.StringIO()
    with patch.object(w, "_leave_group", leave), \
            patch.object(w, "_r2_target", lambda: (r2, lambda k: "blueview")), \
            redirect_stdout(buf):
        code = w.run(db, write, args or _args())
    return code, buf.getvalue(), left, r2


def _ids(db, coll):
    return {r.get("_id") for r in db[coll].rows}


# ── scope ───────────────────────────────────────────────────────────────────

class TheScope(unittest.TestCase):

    def setUp(self):
        self.s = w.discover(_world(), CO_A)

    def test_groups_linked_pending_and_seen_are_in_scope(self):
        self.assertEqual(set(self.s.groups), {GA, GA_PEND})

    def test_a_group_bound_to_another_company_is_shared_not_scoped(self):
        self.assertEqual(self.s.shared_groups, [GS])

    def test_dm_chats_come_from_optins_profiles_and_its_own_dm_rows(self):
        self.assertIn("15550100001@c.us", self.s.dm_chats)
        self.assertIn(f"{LID_A2}@lid", self.s.dm_chats)
        self.assertIn("5550100002", self.s.dm_digits)       # profile, no country code
        self.assertNotIn("15550100009", self.s.dm_digits)   # B's

    def test_a_phone_also_another_companys_is_shared(self):
        self.assertNotIn("15550100003", self.s.dm_digits)
        self.assertNotIn("15550100003@c.us", self.s.dm_chats)
        self.assertIn("15550100003", self.s.shared_digits)

    def test_every_inventoried_collection_has_a_selector(self):
        got = [c for c, _, _ in w.build_selectors(self.s)]
        self.assertEqual(len(got), len(set(got)), "one selector per collection")
        self.assertEqual(set(got), {
            "whatsapp_messages", "whatsapp_groups", "whatsapp_pending_groups",
            "whatsapp_link_codes", "whatsapp_conversation_state", "whatsapp_dm_answers",
            "whatsapp_voice_events", "whatsapp_optins", "whatsapp_dm_reply_windows",
            "whatsapp_notification_ledger", "whatsapp_connect_codes", "whatsapp_dm_welcomes",
            "whatsapp_send_log",
            "whatsapp_checklists", "whatsapp_sender_map", "whatsapp_lid_phone",
            "whatsapp_sender_language", "voice_daily", "whatsapp_contact_card_log",
            "wa_quiet_queue", "attention_items", "attention_cursors", "attention_metrics",
            "chase_shadow", "upcoming_cursors", "upcoming_events", "project_memory",
            "punch_items", "punch_sessions", "punch_links", "punch_counters",
            "punch_leases", "brief_log", "outbound_failures"})
        self.assertEqual(got[0], "whatsapp_groups", "the bindings go first")

    def test_kept_collections_are_never_selected(self):
        got = {c for c, _, _ in w.build_selectors(self.s, include_global=True)}
        for kept in ("audit_logs", "vision_calls", "retention_ledger", "whatsapp_config",
                     "whatsapp_company_settings", "whatsapp_instance_monitor",
                     "whatsapp_contacts", "project_memory_state", "users", "workers",
                     "notification_preferences"):
            self.assertNotIn(kept, got)

    def test_global_debug_only_with_the_flag(self):
        off = {c for c, _, _ in w.build_selectors(self.s)}
        on = {c: f for c, f, _ in w.build_selectors(self.s, include_global=True)}
        for c in w.GLOBAL_DEBUG:
            self.assertNotIn(c, off)
            self.assertEqual(on[c], {})


class R2Keys(unittest.TestCase):

    def test_owned_keys_only_and_never_one_a_kept_row_names(self):
        db = _world()
        s = w.discover(db, CO_A)
        inv = w.r2_inventory(db, w.build_selectors(s))
        self.assertEqual(inv.delete, A_KEYS)
        self.assertEqual(inv.kept, {SHARED_KEY})

    def test_a_shared_group_photo_is_not_owned_by_the_message(self):
        row = {"photo": {"key": "wa-photos/p/msg/1.jpg", "shared": True}}
        self.assertEqual(w.message_keys(row), [])

    def test_punch_keys_cover_what_the_server_deletes(self):
        """Parity with server._punch_r2_keys, the project delete's list."""
        import server
        db = _world()
        items, sessions = db.punch_items.rows, db.punch_sessions.rows
        ours = {k for r in items for k in w.punch_item_keys(r)}
        ours |= {k for r in sessions for k in w.punch_session_keys(r)}
        self.assertLessEqual(set(server._punch_r2_keys(items, sessions)), ours)
        self.assertEqual(w.punch_thumb_key("a/b.jpg"), server._punch_thumb_key("a/b.jpg"))


# ── a full run ──────────────────────────────────────────────────────────────

class AFullRun(unittest.TestCase):

    def test_the_dry_run_writes_nothing(self):
        db = _world()
        before = db.snapshot()
        code, out, left, r2 = _run(db, False, _args(leave_groups=True))
        self.assertEqual(code, w.OK)
        self.assertEqual(db.snapshot(), before)
        self.assertEqual((left, r2.deleted), ([], []))
        self.assertIn("DRY RUN — nothing was written", out)
        self.assertIn("Alpha Test Builders", out)
        self.assertIn('"588 Test St — GC"', out)
        self.assertIn('"New test group"', out)
        self.assertIn("--include-global-debug", out)
        self.assertIn("project_memory_state: NOT reset", out)

    def test_execute_removes_only_company_As_whatsapp_rows(self):
        db = _world()
        before = db.snapshot()
        code, out, _left, r2 = _run(db, True)
        self.assertEqual(code, w.OK, out)
        self.assertEqual(set(r2.deleted), A_KEYS)
        self.assertEqual(r2.stored, B_KEYS | {SHARED_KEY})

        self.assertEqual(_ids(db, "whatsapp_groups"), {"gs_b", "gb"})
        self.assertEqual(_ids(db, "whatsapp_pending_groups"), {"pb"})
        self.assertEqual(_ids(db, "whatsapp_messages"),
                         {"mS_B", "mS_bot", "mB1", "mB_dm_bot", "mShared_dm_bot"})
        self.assertEqual(_ids(db, "whatsapp_conversation_state"),
                         {"cs_b", "cs_shared", "cs_gb"})
        self.assertEqual(_ids(db, "whatsapp_optins"), {"o_b", "o_unknown"})
        self.assertEqual(_ids(db, "whatsapp_dm_reply_windows"), {"15550100009", "15550100003"})
        self.assertEqual(_ids(db, "whatsapp_contact_card_log"), {"15550107777"})
        self.assertEqual(_ids(db, "whatsapp_send_log"), {"sl_s", "sl_b"})
        self.assertEqual(_ids(db, "whatsapp_lid_phone"), {f"{CO_B}|1@lid"})
        self.assertEqual(_ids(db, "voice_daily"), {f"{CO_B}|2026-10-01"})
        self.assertEqual(_ids(db, "punch_counters"), {PB})
        self.assertEqual(_ids(db, "whatsapp_dm_welcomes"), {UB})
        self.assertEqual(_ids(db, "punch_leases"), {f"walker:{UB}"})
        self.assertEqual(_ids(db, "whatsapp_notification_ledger"),
                         {f"{UB}:-:morning_brief:2026-10-01"})
        # Mixed collections: only the WhatsApp subset.
        self.assertEqual(_ids(db, "upcoming_events"), {"ue_city", "ue_b"})
        self.assertEqual(_ids(db, "project_memory"), {"dr:1:general", "wa:mB1"})
        # Every other company-A WhatsApp row is gone; B's one survives.
        for c, _, _ in w.build_selectors(w.discover(_world(), CO_A)):
            if c in ("upcoming_events", "project_memory"):
                continue
            for r in db[c].rows:
                self.assertNotEqual(r.get("company_id"), CO_A, (c, r))

        # Company B: every row exactly as it was.
        for coll, rows in before.items():
            for r in rows:
                if r.get("company_id") == CO_B or str(r.get("_id")).startswith(CO_B):
                    self.assertIn(r, db[coll].rows, coll)

        # Not WhatsApp's, or kept on purpose: untouched.
        for coll in ("projects", "users", "companies", "checkins", "daily_logs",
                     "whatsapp_config", "whatsapp_company_settings", "whatsapp_contacts",
                     "retention_ledger", "vision_calls", "whatsapp_webhook_log",
                     "whatsapp_audio_probe", "project_memory_state"):
            self.assertEqual(db[coll].rows, before[coll], coll)
        # The audit trail is kept, and grows by the run's summary row.
        self.assertIn("al", _ids(db, "audit_logs"))
        self.assertEqual(len(db.audit_logs.rows), 2)
        self.assertEqual(db.audit_logs.rows[-1]["user_id"], "script:wipe_whatsapp_test_data")

    def test_notification_preferences_lose_only_the_setup_fields(self):
        db = _world()
        before = db.snapshot()
        self.assertEqual(_run(db, True)[0], w.OK)
        prefs = {r["_id"]: r for r in db.notification_preferences.rows}
        self.assertEqual(set(prefs), {"np_a", "np_user", "np_b"}, "no document deleted")
        self.assertEqual(prefs["np_a"]["whatsapp_project"],
                         {"violation_alerts": False, "send_window": {"mode": "work_hours"}})
        old = {r["_id"]: r for r in before["notification_preferences"]}
        self.assertEqual(prefs["np_user"], old["np_user"])
        self.assertEqual(prefs["np_b"], old["np_b"])

    def test_a_second_run_deletes_nothing(self):
        db = _world()
        self.assertEqual(_run(db, True)[0], w.OK)
        after_first = db.snapshot()
        code, out, _, r2 = _run(db, True, r2=FakeR2(stored=B_KEYS | {SHARED_KEY}))
        self.assertEqual(code, w.OK, out)
        self.assertEqual(r2.deleted, [])
        first_audit = after_first.pop("audit_logs")
        now = db.snapshot()
        self.assertEqual(len(now.pop("audit_logs")), len(first_audit) + 1)
        self.assertEqual(now, after_first)

    def test_through_the_audited_handle_every_write_is_recorded(self):
        db = _world()
        code, out, _, _ = _run(audited(db, _args(), w.NAME), True)
        self.assertEqual(code, w.OK, out)
        rows = [r for r in db.audit_logs.rows if r.get("_id") != "al"]
        methods = {r["details"].get("method") for r in rows}
        self.assertIn("delete_many", methods)
        self.assertIn("update_many", methods)
        self.assertTrue(all(r["reason"] == "test" and r["session_id"] == "s" for r in rows))

    def test_a_missing_welcomes_collection_is_zero_rows(self):
        db = _world()
        del db._c["whatsapp_dm_welcomes"]
        code, out, _, _ = _run(db, True)
        self.assertEqual(code, w.OK, out)
        self.assertRegex(out, r"whatsapp_dm_welcomes\s+0\s")

    def test_global_debug_is_wiped_only_with_the_flag(self):
        db = _world()
        self.assertEqual(_run(db, True, _args(include_global_debug=True))[0], w.OK)
        self.assertEqual(db.whatsapp_webhook_log.rows, [])
        self.assertEqual(db.whatsapp_audio_probe.rows, [])

    def test_by_company_id(self):
        db = _world()
        code, out, _, _ = _run(db, False, _args(email=None, company=CO_A))
        self.assertEqual(code, w.OK)
        self.assertIn("--company", out)

    def test_an_unknown_email_refuses(self):
        db = _world()
        before = db.snapshot()
        code, out, _, _ = _run(db, True, _args(email="nobody@x.test"))
        self.assertEqual(code, w.REFUSED)
        self.assertEqual(db.snapshot(), before)

    def test_the_email_match_ignores_case(self):
        code, out, _, _ = _run(_world(), False, _args(email="Owner@Alpha.TEST"))
        self.assertEqual(code, w.OK)
        self.assertIn("Alpha Test Builders", out)


class TheFailures(unittest.TestCase):

    def test_an_object_still_there_after_delete_keeps_every_row(self):
        db = _world()
        before = db.snapshot()
        r2 = FakeR2(stored=A_KEYS, stuck={"wa-audio/a1/g/mA1.ogg"})
        code, out, _, _ = _run(db, True, r2=r2)
        self.assertEqual(code, w.FAILED)
        self.assertEqual(db.snapshot(), before)
        self.assertIn("NO rows were touched", out)

    def test_unconfigured_r2_keeps_every_row(self):
        db = _world()
        before = db.snapshot()
        with patch.object(w, "_r2_target", lambda: (None, None)), \
                redirect_stdout(io.StringIO()):
            code = w.run(db, True, _args())
        self.assertEqual(code, w.FAILED)
        self.assertEqual(db.snapshot(), before)

    def test_a_row_left_in_scope_fails_the_post_check(self):
        db = _world()
        real = _Coll.delete_many

        def leaky(self, flt):
            if self is db.whatsapp_send_log:
                return _Res(deleted=0)
            return real(self, flt)
        with patch.object(_Coll, "delete_many", leaky):
            code, out, _, _ = _run(db, True)
        self.assertEqual(code, w.FAILED)
        self.assertIn("MISMATCH", out)


class LeavingGroups(unittest.TestCase):

    def test_off_by_default(self):
        _code, _out, left, _ = _run(_world(), True)
        self.assertEqual(left, [])

    def test_it_leaves_the_companys_groups_never_a_shared_one(self):
        code, out, left, _ = _run(_world(), True, _args(leave_groups=True))
        self.assertEqual(code, w.OK, out)
        self.assertEqual(set(left), {GA, GA_PEND})

    def test_a_failed_leave_deletes_nothing_and_names_the_rerun(self):
        db = _world()
        before = db.snapshot()
        code, out, left, r2 = _run(db, True, _args(leave_groups=True),
                                   leave_ok=lambda g: g != GA_PEND)
        self.assertEqual(code, w.REFUSED)
        self.assertEqual(set(left), {GA, GA_PEND}, "every leave is tried")
        self.assertEqual(db.snapshot(), before)
        self.assertEqual(r2.deleted, [])
        rerun = [ln for ln in out.splitlines() if ln.startswith("Re-run with")][0]
        self.assertIn("--bot-not-in-group 1111", rerun)
        self.assertNotIn("2222", rerun)

    def test_the_rerun_skips_the_groups_named(self):
        code, out, left, _ = _run(_world(), True,
                                  _args(leave_groups=True, bot_not_in_group=["1111"]))
        self.assertEqual(code, w.OK, out)
        self.assertEqual(left, [GA_PEND])

    def test_a_skip_naming_no_group_is_a_bad_invocation(self):
        code, _out, left, _ = _run(_world(), True,
                                   _args(leave_groups=True, bot_not_in_group=["7"]))
        self.assertEqual(code, w.BAD)
        self.assertEqual(left, [])


class WhatItPrints(unittest.TestCase):

    def test_no_phone_number_chat_id_or_jid_is_printed_in_full(self):
        db = _world()
        outs = [_run(db, False, _args(leave_groups=True))[1]]
        outs.append(_run(_world(), True, _args(leave_groups=True),
                         leave_ok=lambda g: g != GA)[1])
        outs.append(_run(db, True, _args(leave_groups=True))[1])
        outs.append(_run(db, True, _args(leave_groups=True))[1])
        for out in outs:
            for secret in SECRETS:
                self.assertNotIn(secret, out)
            self.assertIsNone(re.search(r"\d{7,}", out), out)

    def test_r2_keys_are_masked(self):
        self.assertEqual(w._mask_key("wa-audio/p/120363000000001111_g.us/m.ogg"),
                         "wa-audio/….ogg")

    def test_last4(self):
        self.assertEqual(w.last4("15550100001@c.us"), "…0001")
        self.assertEqual(w.last4(""), "…")
        self.assertEqual(w.safe_text("Site 15550100001 chat"), "Site …0001 chat")


class TheInvocation(unittest.TestCase):

    def test_the_legacy_flag_alone_is_refused(self):
        with self.assertRaises(SystemExit) as e:
            w.main(["--email", "a@b", "--execute"])
        self.assertEqual(e.exception.code, 2)

    def test_i_know_without_reason_and_session_is_an_error(self):
        with self.assertRaises(SystemExit) as e:
            w.main(["--email", "a@b", "--i-know", "--session", ""])
        self.assertEqual(e.exception.code, 2)

    def test_a_scope_is_required(self):
        with self.assertRaises(SystemExit) as e, \
                patch("sys.stderr", io.StringIO()):
            w.main([])
        self.assertEqual(e.exception.code, 2)

    def test_without_mongo_it_is_a_bad_invocation(self):
        env = dict(os.environ)
        os.environ.pop("MONGO_URL", None)
        try:
            with redirect_stdout(io.StringIO()):
                code = w.main(["--email", "a@b"])
        finally:
            os.environ.clear()
            os.environ.update(env)
        self.assertEqual(code, w.BAD)

    def test_the_docstring_carries_the_operators_commands(self):
        doc = w.__doc__
        self.assertIn(r"railway run python scripts\wipe_whatsapp_test_data.py "
                      r"--email you@company.com", doc)
        self.assertIn(r"railway run python scripts\wipe_whatsapp_test_data.py "
                      r"--email you@company.com --i-know --reason "
                      r'"..." --session <id>', doc)


if __name__ == "__main__":
    unittest.main()
