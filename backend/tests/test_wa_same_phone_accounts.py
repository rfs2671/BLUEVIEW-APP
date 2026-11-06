"""One person, an account in each of several companies, ONE phone.

Roy's ruling (2026-11-06): accounts are company-owned, one per company; the
same person may hold accounts in several companies with the SAME phone, and
all of them are valid. WhatsApp turned such a person away: whatsapp_optins
was unique on phone, START refused a number two live users have ("This
number is on more than one Levelog account"), and the app said "Phone
shared".

THE RULES THESE TESTS HOLD
  * START lists every company account on the number, by its company's real
    name, and the person confirms ONCE ("Reply YES to connect both").
  * NO SILENT SIGN-UP: nothing is connected without that person's YES. NO,
    any other message, or STOP leaves nothing connected.
  * An account that appears on the number later is asked about on the next
    message (which is held, then answered), once; NO is remembered.
  * An opt-in made before this change keeps working, with no re-confirm.
  * A send for one account rides that account's opt-in.
  * A GC "1" / "2" and a "Q3 YES" are never guessed between two companies.
  * Two accounts on the number in ONE company: still refused (the existing
    tests in test_whatsapp_phase1_foundations / test_whatsapp_start_lid).

Nothing reaches the network: WaAPI is the _Wire of the phase-1 tests.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import wa_dm, wa_welcome  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_whatsapp_phase1_foundations import (  # noqa: E402
    ADMIN_PHONE, CO_A, CO_B, _Ctx, _users,
)

CHAT = f"{ADMIN_PHONE}@c.us"
NAME_A, NAME_B = "Acme Builders", "Brick & Co"


def _run(coro):
    return asyncio.run(coro)


def _db(*, b_role="pm", b_phone="+" + ADMIN_PHONE, extra_users=(), optins=()):
    """Ada is an admin at Acme (co_a) and -- same phone -- a PM at Brick
    (co_b), assigned to Brick's job."""
    users = [u for u in _users() if u["_id"] != "u_b"] + [
        {"_id": "u_b", "company_id": CO_B, "role": b_role, "phone": b_phone,
         "name": "Ada at Brick", "assigned_projects": ["proj_b"]}] + list(extra_users)
    return FakeDb(
        unique={server.WA_OPTINS: (("phone", "user_id"),)},
        users=users,
        companies=[{"_id": CO_A, "name": NAME_A}, {"_id": CO_B, "name": NAME_B}],
        projects=[{"_id": "proj_a", "company_id": CO_A, "name": "A",
                   "address": "12 Main St"},
                  {"_id": "proj_b", "company_id": CO_B, "name": "B",
                   "address": "40 Oak Ave"}],
        whatsapp_optins=list(optins),
        # Whoever is connected was welcomed when they connected.
        whatsapp_dm_welcomes=[{"_id": o["user_id"], "company_id": o["company_id"],
                               "welcomed_at": o["opted_in_at"], "card": "vcard"}
                              for o in optins],
    )


def _optin(uid, company, *, at=None, status="active", verified=True):
    return {"_id": f"o_{uid}", "phone": ADMIN_PHONE, "user_id": uid, "company_id": company,
            "chat_id": CHAT, "chat_digits": ADMIN_PHONE, "chat_kind": "c.us",
            "phone_verified": verified, "status": status, "source": "start",
            "opted_in_at": at or datetime(2026, 10, 1, tzinfo=timezone.utc)}


def _dm(body, msg_id):
    return {"event": "message", "data": {"message": {
        "id": {"id": msg_id, "fromMe": False}, "from": CHAT, "body": body, "type": "chat"}}}


class _Assistant:
    """The DM assistant, recorded: what it was asked and as whom. The real
    one runs a model; here only the routing up to it is under test."""

    def __init__(self):
        self.calls = []

    async def reply(self, ident, dm_chat, body, message_id, **kw):
        self.calls.append((ident["user_id"], body))

    async def no_punch(self, *a, **k):
        return False

    async def off(self, *a, **k):
        return False

    def patches(self):
        return [patch.object(server, "_dm_assistant_reply", self.reply),
                patch.object(server, "_punch_dm_turn", self.no_punch),
                patch.object(server, "_dm_brain_on", self.off)]


def _say(c, body, msg_id, assistant=None):
    ps = assistant.patches() if assistant else []
    for p in ps:
        p.start()
    try:
        _run(server._process_whatsapp_message(_dm(body, msg_id)))
    finally:
        for p in reversed(ps):
            p.stop()


def _texts(c):
    return [p["message"] for p in c.wire.calls if "message" in p]


def _active(c):
    return sorted(r["user_id"] for r in c.db[server.WA_OPTINS].rows
                  if r.get("status") == "active")


START_Q = wa_dm.accounts_text("en", "start_confirm", [NAME_A, NAME_B])


class StartListsEveryCompanyAndAsksOnce(unittest.TestCase):

    def test_start_asks_with_the_real_company_names_and_connects_nothing(self):
        with _Ctx(_db()) as c:
            _say(c, "START", "m1")
            self.assertEqual(c.db[server.WA_OPTINS].rows, [])
            self.assertEqual(_texts(c), [START_Q])
        self.assertIn(NAME_A, START_Q)
        self.assertIn(NAME_B, START_Q)
        self.assertIn("Reply YES to connect both", START_Q)

    def test_yes_connects_both_with_one_welcome_and_names_both(self):
        with _Ctx(_db()) as c:
            _say(c, "START", "m1")
            _say(c, "YES", "m2")
            self.assertEqual(_active(c), ["u_admin", "u_b"])
            rows = {r["user_id"]: r for r in c.db[server.WA_OPTINS].rows}
            self.assertEqual({r["phone"] for r in rows.values()}, {ADMIN_PHONE})
            self.assertEqual((rows["u_b"]["company_id"], rows["u_b"]["phone_verified"]),
                             (CO_B, True))
            sent = _texts(c)[1:]
        self.assertEqual(sent, [wa_welcome.welcome_text("Ada Admin", with_card=False),
                                wa_dm.accounts_text("en", "connected", [NAME_A, NAME_B])])

    def test_si_answers_in_spanish(self):
        with _Ctx(_db()) as c:
            _say(c, "START", "m1")
            _say(c, "sí", "m2")
            self.assertEqual(_active(c), ["u_admin", "u_b"])
            self.assertEqual(_texts(c)[-1],
                             wa_dm.accounts_text("es", "connected", [NAME_A, NAME_B]))

    def test_no_connects_nothing(self):
        with _Ctx(_db()) as c:
            _say(c, "START", "m1")
            _say(c, "no", "m2")
            self.assertEqual(_active(c), [])
            self.assertEqual(_texts(c)[-1],
                             wa_dm.accounts_text("en", "declined_start", [NAME_A, NAME_B]))

    def test_another_message_clears_the_question_and_a_later_yes_connects_nothing(self):
        with _Ctx(_db()) as c:
            _say(c, "START", "m1")
            _say(c, "what is this", "m2")
            _say(c, "yes", "m3")
            self.assertEqual(_active(c), [])

    def test_stop_clears_the_question(self):
        with _Ctx(_db()) as c:
            _say(c, "START", "m1")
            _say(c, "STOP", "m2")
            _say(c, "YES", "m3")
            self.assertEqual(_active(c), [])

    def test_one_eligible_account_is_connected_at_once_as_before(self):
        """Brick's account is a CP (no assistant): the admin account alone
        is connected by START, with no question."""
        with _Ctx(_db(b_role="cp")) as c:
            _say(c, "START", "m1")
            self.assertEqual(_active(c), ["u_admin"])
            self.assertEqual(_texts(c), [wa_welcome.welcome_text("Ada Admin", with_card=False)])

    def test_a_connect_code_from_the_proven_number_lists_both_too(self):
        with _Ctx(_db()) as c:
            admin = dict(next(u for u in c.db.users.rows if u["_id"] == "u_admin"), id="u_admin")
            with patch.dict(os.environ, {"WAAPI_DISPLAY_NUMBER": "+15165494475"}):
                url = _run(server.whatsapp_connect_link(current_user=admin))["url"]
            code = url.rsplit("%20", 1)[1]
            _say(c, f"START {code}", "m1")
            self.assertEqual(_active(c), [])
            self.assertEqual(_texts(c), [START_Q])
            _say(c, "yes", "m2")
            self.assertEqual(_active(c), ["u_admin", "u_b"])

    def test_the_yes_is_rechecked_an_account_deleted_meanwhile_is_not_connected(self):
        with _Ctx(_db()) as c:
            _say(c, "START", "m1")
            next(u for u in c.db.users.rows if u["_id"] == "u_b")["is_deleted"] = True
            _say(c, "YES", "m2")
            self.assertEqual(_active(c), ["u_admin"])

    def test_the_hint_is_due_for_a_person_with_accounts_in_two_companies(self):
        with _Ctx(_db()) as c:
            self.assertTrue(_run(server._dm_start_hint_due(CHAT)))


class AnAccountAddedLaterIsAskedAboutOnce(unittest.TestCase):

    def _world(self):
        # Connected for Acme before Brick's account carried the number.
        return _db(optins=[_optin("u_admin", CO_A)])

    def test_the_next_message_asks_about_brick_and_is_held(self):
        a = _Assistant()
        with _Ctx(self._world()) as c:
            _say(c, "how many on site at 12 main", "m1", a)
            self.assertEqual(a.calls, [], "held: asked before anything else")
            self.assertEqual(_texts(c), [wa_dm.accounts_text("en", "later_confirm", [NAME_B])])
            self.assertEqual(_active(c), ["u_admin"])

    def test_yes_connects_brick_and_answers_the_held_message(self):
        a = _Assistant()
        with _Ctx(self._world()) as c:
            _say(c, "how many on site at 12 main", "m1", a)
            _say(c, "yes", "m2", a)
            self.assertEqual(_active(c), ["u_admin", "u_b"])
            self.assertEqual(_texts(c)[-1],
                             wa_dm.accounts_text("en", "connected", [NAME_A, NAME_B]))
            self.assertNotIn(wa_welcome.welcome_text("Ada at Brick", with_card=False), _texts(c),
                             "already talking to the assistant: no second hello")
            self.assertEqual([b for _u, b in a.calls], ["how many on site at 12 main"])

    def test_no_is_remembered_and_the_held_message_is_answered(self):
        a = _Assistant()
        with _Ctx(self._world()) as c:
            _say(c, "how many on site", "m1", a)
            _say(c, "no", "m2", a)
            self.assertEqual(_active(c), ["u_admin"])
            row = next(r for r in c.db[server.WA_OPTINS].rows if r["user_id"] == "u_b")
            self.assertEqual(row["status"], "declined")
            self.assertEqual([b for _u, b in a.calls], ["how many on site"])
            n = len(_texts(c))
            _say(c, "and at 12 main?", "m3", a)
            self.assertEqual(len(_texts(c)), n, "never asked again")
            self.assertEqual([b for _u, b in a.calls][-1], "and at 12 main?")

    def test_passed_over_it_waits_a_day(self):
        a = _Assistant()
        with _Ctx(self._world()) as c:
            _say(c, "how many on site", "m1", a)
            _say(c, "who is at 12 main", "m2", a)
            _say(c, "and now?", "m3", a)
            self.assertEqual(_active(c), ["u_admin"])
            self.assertEqual([b for _u, b in a.calls], ["who is at 12 main", "and now?"])
            self.assertEqual(len([t for t in _texts(c) if "now also has" in t]), 1)

    def test_a_yes_or_a_number_meant_for_something_else_is_never_held(self):
        """"yes" may be the answer to the assistant's own question: it goes
        on, and the new account is asked about on the next message."""
        a = _Assistant()
        with _Ctx(self._world()) as c:
            _say(c, "yes", "m1", a)
            _say(c, "2", "m2", a)
            self.assertEqual([b for _u, b in a.calls], ["yes", "2"])
            self.assertEqual(_texts(c), [])
            _say(c, "how many on site", "m3", a)
            self.assertEqual(_texts(c), [wa_dm.accounts_text("en", "later_confirm", [NAME_B])])

    def test_an_unproven_number_is_not_offered_more_accounts(self):
        """Opted in by a connect code from a @lid chat with no phone: the
        number was never proven, so no other account is offered on it."""
        a = _Assistant()
        with _Ctx(_db(optins=[_optin("u_admin", CO_A, verified=False)])) as c:
            _say(c, "how many on site", "m1", a)
            self.assertEqual(_texts(c), [])
            self.assertEqual(len(a.calls), 1)


class ExistingOptInsKeepWorking(unittest.TestCase):

    def test_a_single_account_optin_from_before_needs_no_reconfirm(self):
        a = _Assistant()
        db = _db(b_phone="+15550002001", optins=[_optin("u_admin", CO_A)])
        with _Ctx(db) as c:
            _run(server._wa_optins_index_migration())
            _say(c, "how many on site", "m1", a)
            self.assertEqual(a.calls, [("u_admin", "how many on site")])
            self.assertEqual(_texts(c), [])
            c.wire.calls.clear()
            out = _run(server.send_whatsapp_dm("u_admin", "x", kind="summary", window="w1"))
            self.assertIsNotNone(out)

    def test_each_account_sends_through_its_own_optin(self):
        """Before: the number's one row named u_admin, so a send for u_b
        was refused (optin_user_mismatch)."""
        db = _db(optins=[_optin("u_admin", CO_A),
                         dict(_optin("u_b", CO_B), _id="o_b")])
        with _Ctx(db) as c:
            for uid in ("u_admin", "u_b"):
                out = _run(server.send_whatsapp_dm(uid, f"for {uid}", kind="summary",
                                                   window="w1"))
                self.assertIsNotNone(out, uid)
            keys = sorted(r["_id"] for r in c.db[server.WA_LEDGER].rows)
            self.assertEqual(keys, ["u_admin:-:summary:w1", "u_b:-:summary:w1"])
            refused = _run(server._dm_send_verdict(
                CHAT, "x", {"user_id": "u_cp", "kind": "k", "window": "w"}))
            self.assertEqual(refused["reason"], "optin_user_mismatch")


class TheIndexMigration(unittest.TestCase):
    """SCHEMA: whatsapp_optins unique (phone) -> unique (phone, user_id)."""

    def _legacy_db(self):
        db = FakeDb(whatsapp_optins=[_optin("u_admin", CO_A)])
        _run(db[server.WA_OPTINS].create_index(
            [("phone", 1)], name="whatsapp_optins_phone_unique", unique=True))
        return db

    def test_before_it_a_second_account_on_the_number_cannot_be_written(self):
        db = self._legacy_db()
        from pymongo.errors import DuplicateKeyError
        with self.assertRaises(DuplicateKeyError):
            _run(db[server.WA_OPTINS].insert_one(dict(_optin("u_b", CO_B), _id="o_b")))

    def test_it_swaps_the_index_keeps_the_rows_and_is_idempotent(self):
        db = self._legacy_db()
        before = [dict(r) for r in db[server.WA_OPTINS].rows]
        with patch.object(server, "db", db):
            first = _run(server._wa_optins_index_migration())
            second = _run(server._wa_optins_index_migration())
        self.assertEqual(first, {"built": True, "dropped_old": True})
        self.assertEqual(second, {"built": True, "dropped_old": False})
        names = set(_run(db[server.WA_OPTINS].index_information()))
        self.assertIn("whatsapp_optins_phone_user_unique", names)
        self.assertNotIn("whatsapp_optins_phone_unique", names)
        self.assertEqual(db[server.WA_OPTINS].rows, before, "no data rewritten")
        _run(db[server.WA_OPTINS].insert_one(dict(_optin("u_b", CO_B), _id="o_b")))
        self.assertEqual(len(db[server.WA_OPTINS].rows), 2)

    def test_a_failed_build_keeps_the_old_index(self):
        db = self._legacy_db()

        async def nothing(*a, **k):
            return None
        with patch.object(server, "db", db), \
                patch.object(server, "_ensure_index_resilient", nothing):
            out = _run(server._wa_optins_index_migration())
        self.assertEqual(out, {"built": False, "dropped_old": False})
        self.assertIn("whatsapp_optins_phone_unique",
                      set(_run(db[server.WA_OPTINS].index_information())))


class TheLines(unittest.TestCase):

    def test_english_and_spanish_for_every_line(self):
        en, es = wa_dm.ACCOUNTS_LINES["en"], wa_dm.ACCOUNTS_LINES["es"]
        self.assertEqual(set(en), set(es))
        for lines in (wa_dm.GC_TWO_OPEN_LINES, wa_dm.SET_Q_PICK_LINES):
            self.assertEqual(set(lines), {"en", "es"})
        for key in ("start_confirm", "later_confirm", "connected", "declined_start",
                    "declined_later"):
            for lang in ("en", "es"):
                one = wa_dm.accounts_text(lang, key, ["A"])
                two = wa_dm.accounts_text(lang, key, ["A", "B"])
                self.assertNotIn("{", one + two, (lang, key))
        self.assertEqual(wa_dm.accounts_text("en", "start_confirm", ["A", "B", "C"]),
                         "Levelog Assistant here. This number has a Levelog account at "
                         "A, B and C. Reply YES to connect all 3, or NO to cancel.")
        self.assertIn("conectarlas también", wa_dm.accounts_text("es", "later_confirm", ["A", "B"]))
        self.assertIn("conectarla también", wa_dm.accounts_text("es", "later_confirm", ["A"]))
        for key in ("start_confirm", "later_confirm"):
            self.assertTrue(wa_dm.accounts_text("en", key, ["A"]).startswith(
                "Levelog Assistant here."))


class GcConfirmAcrossCompanies(unittest.TestCase):
    """Ada is the main admin of BOTH companies (same phone)."""

    def _world(self):
        from tests.test_whatsapp_gc_alerts import _world
        db = _world()
        for u in db.users.rows:
            if u["_id"] == "u_b":
                u["phone"] = "+" + ADMIN_PHONE
        db[server.WA_OPTINS].rows += [_optin("u_admin", CO_A),
                                      dict(_optin("u_b", CO_B), _id="o_b")]
        return db

    def setUp(self):
        from tests._pinned_clock import pin_server_clock
        from tests.test_whatsapp_gc_alerts import NOON
        self.now = pin_server_clock(self, NOON)

    def test_one_question_at_a_time_per_person(self):
        with _Ctx(self._world()) as c:
            r = _run(server._gc_propose_tick(self.now))
            asked = [t for t in _texts(c) if "Reply 1 Yes / 2 No" in t]
        self.assertEqual((r["asked"], r["busy"]), (1, 1))
        self.assertEqual(len(asked), 1)

    def test_1_answers_the_question_on_the_second_account(self):
        from tests.test_whatsapp_gc_alerts import G_B
        with _Ctx(self._world()) as c:
            _run(server._set_whatsapp_project_fields("proj_b", CO_B, {"gc_proposal": {
                "status": "pending", "group_id": G_B, "group_name": "B site",
                "admin_user_id": "u_b", "sent_at": self.now,
                "expires_at": self.now + timedelta(hours=48)}}))
            self.assertTrue(_run(server._handle_gc_confirm_reply(CHAT, "yes")))
            st = _run(server._whatsapp_project_settings("proj_b"))
        self.assertEqual((st["gc_group_id"], st["gc_group_confirmed"]), (G_B, True))

    def test_two_open_at_once_neither_is_guessed(self):
        from tests.test_whatsapp_gc_alerts import G_B, G_GC
        with _Ctx(self._world()) as c:
            for pid, co, g, uid in (("proj_a", CO_A, G_GC, "u_admin"),
                                    ("proj_b", CO_B, G_B, "u_b")):
                _run(server._set_whatsapp_project_fields(pid, co, {"gc_proposal": {
                    "status": "pending", "group_id": g, "group_name": "x",
                    "admin_user_id": uid, "sent_at": self.now,
                    "expires_at": self.now + timedelta(hours=48)}}))
            self.assertTrue(_run(server._handle_gc_confirm_reply(CHAT, "yes")))
            a = _run(server._whatsapp_project_settings("proj_a"))
            b = _run(server._whatsapp_project_settings("proj_b"))
            said = _texts(c)[-1]
        self.assertFalse(a["gc_group_confirmed"] or b["gc_group_confirmed"])
        self.assertEqual((a["gc_proposal"]["status"], b["gc_proposal"]["status"]),
                         ("pending", "pending"))
        self.assertIn("nothing was changed", said)


class SetQuestionCodesAcrossCompanies(unittest.TestCase):
    """Codes are unique per company: Acme and Brick each asked Ada a Q1."""

    def _world(self):
        from lib import plan_set_questions as psq
        db = _db(b_role="pm", optins=[_optin("u_admin", CO_A),
                                      dict(_optin("u_b", CO_B), _id="o_b")])
        for u in db.users.rows:
            if u["_id"] == "u_admin":
                u.update(role="pm", pm_access="full")
        db[psq.COLLECTION].rows += [
            {"_id": "q_a", "project_id": "proj_a", "code": "Q1", "status": psq.OPEN,
             "asked_user_ids": ["u_admin"], "short": "A.1 to A.3", "label": "A.1 to A.3"},
            {"_id": "q_b", "project_id": "proj_b", "code": "Q1", "status": psq.OPEN,
             "asked_user_ids": ["u_b"], "short": "S.1 to S.2", "label": "S.1 to S.2"},
        ]
        return db

    def test_q1_yes_asks_which_job_and_records_nothing(self):
        from lib import plan_set_questions as psq
        with _Ctx(self._world()) as c:
            _say(c, "Q1 YES", "m1")
            qs = {q["_id"]: q for q in c.db[psq.COLLECTION].rows}
            said = _texts(c)
        self.assertEqual((qs["q_a"]["status"], qs["q_b"]["status"]), (psq.OPEN, psq.OPEN))
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].startswith("Q1 is open on more than one job. Which one?"))
        self.assertIn(f"1) 12 Main St ({NAME_A})", said[0])
        self.assertIn(f"2) 40 Oak Ave ({NAME_B})", said[0])

    def test_the_number_records_it_on_that_job_only(self):
        from lib import plan_set_questions as psq
        with _Ctx(self._world()) as c:
            _say(c, "Q1 YES", "m1")
            _say(c, "2", "m2")
            qs = {q["_id"]: q for q in c.db[psq.COLLECTION].rows}
        self.assertEqual(qs["q_a"]["status"], psq.OPEN)
        self.assertEqual((qs["q_b"]["status"], qs["q_b"]["answer"], qs["q_b"]["answered_by"]),
                         (psq.ANSWERED, psq.INCLUDE, "u_b"))

    def test_a_code_in_one_company_only_is_answered_for_the_right_account(self):
        """Brick's Q1 alone: answered as Ada's Brick account (before: only
        the number's one opt-in -- Acme's -- was looked at)."""
        from lib import plan_set_questions as psq
        db = self._world()
        db[psq.COLLECTION].rows = [q for q in db[psq.COLLECTION].rows if q["_id"] == "q_b"]
        with _Ctx(db) as c:
            _say(c, "Q1 no", "m1")
            q = c.db[psq.COLLECTION].rows[0]
        self.assertEqual((q["status"], q["answer"], q["answered_by"]),
                         (psq.ANSWERED, psq.EXCLUDE, "u_b"))


if __name__ == "__main__":
    unittest.main()


class TheAppOverHttp(unittest.TestCase):
    """GET /api/whatsapp/me and POST /api/whatsapp/connect-link through
    server.app: every middleware, the real JWT, only the database replaced
    (tests/async_fake_mongo.py)."""

    def _call(self, *, other_company):
        import httpx
        from bson import ObjectId
        from tests.async_fake_mongo import AsyncFakeDB
        db = AsyncFakeDB()
        co_a, co_b, me_id = ObjectId(), ObjectId(), ObjectId()
        db.companies.docs += [{"_id": co_a, "name": NAME_A}, {"_id": co_b, "name": NAME_B}]
        db.users.docs += [
            {"_id": me_id, "email": "ada@acme.test", "name": "Ada", "role": "admin",
             "company_id": str(co_a), "account_status": "approved", "is_deleted": False,
             "phone": "+" + ADMIN_PHONE},
            {"_id": ObjectId(), "email": "ada@brick.test", "name": "Ada", "role": "pm",
             "company_id": str(co_b if other_company else co_a),
             "account_status": "approved", "is_deleted": False, "phone": ADMIN_PHONE},
        ]
        tok = server.create_token(str(me_id), "ada@acme.test", "admin", company_id=str(co_a))

        async def go():
            transport = httpx.ASGITransport(app=server.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                h = {"Authorization": f"Bearer {tok}"}
                me = await c.get("/api/whatsapp/me", headers=h)
                link = await c.post("/api/whatsapp/connect-link", headers=h)
                return me, link
        with patch.object(server, "db", db), \
                patch.dict(os.environ, {"WAAPI_DISPLAY_NUMBER": "+15165494475"}):
            return _run(go())

    def test_an_account_in_another_company_on_the_number_does_not_block(self):
        me, link = self._call(other_company=True)
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["state"], "not_connected")
        self.assertEqual(link.status_code, 200, link.text)
        self.assertIn("text=START%20", link.json()["url"])

    def test_a_second_account_in_the_same_company_still_does(self):
        me, link = self._call(other_company=False)
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["state"], "phone_shared")
        self.assertEqual(link.status_code, 409)
