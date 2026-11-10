"""Superintendents and CPs in the Levelog Assistant DM (owner ruling, 2026-11-09).

  * They connect with START and are answered, on their ASSIGNED jobs only --
    never every job of the company by role alone.
  * They are never written to first: no brief, reminder or report DM.
  * The server refuses, per call, every tool the ruling reserves to a PM or an
    admin -- changes, company reports, approving a PROPOSED sequence -- even
    when the model calls it; hiding the tool is not the gate.
  * Viewing a PROPOSED sequence as a field role writes nothing.
  * The change flow's last gate refuses them too.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import dm_roles, wa_dm, wa_welcome  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

CO_A, CO_B = "co_a", "co_b"
ADMIN_PHONE = "15550001001"
CP_PHONE = "15550001003"
SUPER_PHONE = "15550001004"
UNKNOWN_PHONE = "15550009999"


def _users():
    return [
        {"_id": "u_admin", "company_id": CO_A, "role": "admin", "phone": "+" + ADMIN_PHONE,
         "name": "Ada Admin", "account_status": "approved"},
        {"_id": "u_cp", "company_id": CO_A, "role": "cp", "phone": "+" + CP_PHONE, "name": "Cal CP",
         "account_status": "approved", "assigned_projects": ["proj_a", "proj_b", "proj_gone"]},
        {"_id": "u_super", "company_id": CO_A, "role": "superintendent", "phone": "+" + SUPER_PHONE,
         "name": "Sue Super", "account_status": "approved"},
    ]


def _db(**extra):
    return FakeDb(
        unique={server.WA_OPTINS: (("phone", "user_id"),)},
        users=_users(),
        projects=[{"_id": "proj_a", "company_id": CO_A, "name": "A", "address": "1 A St"},
                  {"_id": "proj_a2", "company_id": CO_A, "name": "A2", "address": "2 A St"},
                  {"_id": "proj_b", "company_id": CO_B, "name": "B", "address": "1 B St"}],
        **extra)


def _run(coro):
    return asyncio.run(coro)


class _Wire:
    def __init__(self):
        self.calls = []

    async def post_raw(self, url, payload, headers):
        self.calls.append(payload)
        return 200, {"status": "success"}, None


class _Ctx:
    def __init__(self, db=None):
        self.db = db or _db()
        self.wire = _Wire()
        self._ps = [patch.object(server, "db", self.db),
                    patch.object(server, "WAAPI_INSTANCE_ID", "inst"),
                    patch.object(server, "WAAPI_TOKEN", "tok"),
                    patch.object(server, "_waapi_post_raw", self.wire.post_raw),
                    patch.object(wa_dm, "DM_MIN_INTERVAL_SECONDS", 0.0),
                    patch.object(wa_dm, "DM_BACKOFF_SECONDS", (0.0, 0.0, 0.0))]

    def __enter__(self):
        for p in self._ps:
            p.start()
        return self

    def __exit__(self, *a):
        for p in reversed(self._ps):
            p.stop()

    def said(self):
        return [p.get("message") for p in self.wire.calls]


def _payload(phone, body, msg_id="D1", **msg):
    return {"event": "message", "data": {"message": {
        "id": {"id": msg_id, "fromMe": False}, "from": f"{phone}@c.us",
        "body": body, "type": "chat", **msg}}}


def _process(phone, body, msg_id="D1"):
    _run(server._process_whatsapp_message(_payload(phone, body, msg_id)))


def _cp_ident(db_ctx):
    _process(CP_PHONE, "START", "S1")
    found = _run(server._dm_identities(f"{CP_PHONE}@c.us"))
    return found[0] if found else None


# ── PURE ────────────────────────────────────────────────────────────────────

class TheTable(unittest.TestCase):

    def test_who_is_answered_and_who_is_written_to_first(self):
        for role, answered, first in (("admin", True, True), ("pm", True, True), ("PM ", True, True),
                                      ("superintendent", True, False), ("cp", True, False),
                                      ("worker", False, False), ("site_device", False, False),
                                      ("demo", False, False), ("owner", False, False), ("", False, False)):
            u = {"role": role, "company_id": "c"}
            self.assertEqual(wa_dm.is_dm_assistant_eligible(u), answered, role)
            self.assertEqual(wa_dm.is_dm_eligible(u), first, role)
        self.assertFalse(wa_dm.is_dm_assistant_eligible({"role": "cp", "company_id": ""}))
        self.assertFalse(wa_dm.is_dm_assistant_eligible({"role": "cp", "company_id": "c", "is_deleted": True}))

    def test_a_manager_may_call_everything(self):
        for name in list(dm_roles.FIELD_TOOLS) + list(dm_roles.MANAGER_TOOLS):
            for role in ("admin", "pm"):
                self.assertIsNone(dm_roles.tool_refusal(role, name, {"approve": True}), (role, name))

    def test_a_field_role_calls_the_field_tools_only(self):
        for role in ("cp", "superintendent", "CP"):
            for name in dm_roles.FIELD_TOOLS:
                self.assertIsNone(dm_roles.tool_refusal(role, name, {}), (role, name))
            for name in dm_roles.MANAGER_TOOLS:
                out = dm_roles.tool_refusal(role, name, {})
                self.assertTrue(out and out.startswith("REFUSED"), (role, name))
                self.assertIn("PM or an admin", out)

    def test_approving_a_sequence_is_refused_and_viewing_is_not(self):
        self.assertIsNone(dm_roles.tool_refusal("cp", "proposed_sequence", {}))
        self.assertIsNone(dm_roles.tool_refusal("cp", "proposed_sequence", {"approve": False}))
        out = dm_roles.tool_refusal("cp", "proposed_sequence", {"approve": True})
        self.assertIn("approving a sequence", out)
        self.assertFalse(dm_roles.may_approve_sequence("superintendent"))
        self.assertTrue(dm_roles.may_approve_sequence("pm"))

    def test_an_unknown_tool_or_role_is_closed(self):
        self.assertTrue(dm_roles.tool_refusal("cp", "start_permit_renewal", {}))
        self.assertTrue(dm_roles.tool_refusal("worker", "work_status", {}))
        self.assertTrue(dm_roles.tool_refusal(None, "work_status", {}))
        self.assertTrue(dm_roles.change_refusal("cp"))
        self.assertIsNone(dm_roles.change_refusal("admin"))

    def test_the_two_sets_do_not_overlap(self):
        self.assertEqual(dm_roles.FIELD_TOOLS & set(dm_roles.MANAGER_TOOLS), set())


class EveryBrainToolIsClassified(unittest.TestCase):
    """A tool added to the brain without a ruling would be open to nobody
    in the field (closed by default) -- but it must be decided, not forgotten."""

    def test_census(self):
        names = {t["function"]["name"] for t in server._dm_brain_tools()}
        classified = set(dm_roles.FIELD_TOOLS) | set(dm_roles.MANAGER_TOOLS)
        self.assertEqual(sorted(names - classified), [])
        self.assertEqual(sorted(classified - names), [])

    def test_a_field_turn_is_shown_the_field_tools_only(self):
        shown = {t["function"]["name"] for t in server._dm_brain_tools(field=True)}
        self.assertEqual(shown, set(dm_roles.FIELD_TOOLS))
        self.assertNotIn("propose_change", shown)


# ── CONNECTING ──────────────────────────────────────────────────────────────

class Start(unittest.TestCase):

    def test_a_cp_and_a_superintendent_connect_and_get_the_field_welcome(self):
        for phone, uid, name in ((CP_PHONE, "u_cp", "Cal CP"), (SUPER_PHONE, "u_super", "Sue Super")):
            with self.subTest(uid), _Ctx() as c:
                _process(phone, "START")
                rows = c.db[server.WA_OPTINS].rows
                self.assertEqual([(r["user_id"], r["status"]) for r in rows], [(uid, "active")])
                self.assertEqual(c.said(), [wa_welcome.welcome_text(name, with_card=False, field=True)])

    def test_a_second_start_gets_the_field_intro(self):
        with _Ctx() as c:
            _process(CP_PHONE, "START", "S1")
            c.wire.calls.clear()
            _process(CP_PHONE, "START", "S2")
            self.assertEqual(c.said(), [wa_dm.FIELD_INTRO_TEXT])

    def test_an_unknown_number_still_gets_the_neutral_line(self):
        with _Ctx() as c:
            _process(UNKNOWN_PHONE, "START")
            self.assertEqual(c.db[server.WA_OPTINS].rows, [])
            self.assertEqual(c.said(), [wa_dm.NOT_ELIGIBLE_TEXT])

    def test_the_connect_screen_offers_it_without_the_brief(self):
        with _Ctx():
            me = _run(server.whatsapp_me(current_user={"id": "u_cp", **_users()[1]}))
        self.assertTrue(me["eligible"])
        self.assertIsNone(me["brief"])


class TheirJobsOnly(unittest.TestCase):

    def test_assigned_jobs_of_their_own_company_and_nothing_else(self):
        with _Ctx():
            ident = _cp_ident(None)
        self.assertEqual(ident["role"], "cp")
        # proj_a: assigned and theirs. proj_b: assigned, another company's.
        # proj_gone: no such job. proj_a2: theirs, not assigned.
        self.assertEqual([str(p["_id"]) for p in ident["projects"]], ["proj_a"])

    def test_no_assignment_is_no_job_not_every_job(self):
        with _Ctx():
            _process(SUPER_PHONE, "START", "S1")
            ident = _run(server._dm_identities(f"{SUPER_PHONE}@c.us"))[0]
        self.assertEqual(ident["projects"], [])


class NeverWrittenToFirst(unittest.TestCase):

    def test_no_proactive_dm(self):
        with _Ctx() as c:
            _process(CP_PHONE, "START")
            c.wire.calls.clear()
            out = _run(server.send_whatsapp_dm("u_cp", "brief", kind="summary", window="w",
                                               project_id="proj_a"))
        self.assertIsNone(out)
        self.assertEqual(c.wire.calls, [])

    def test_a_field_account_on_an_admins_number_is_not_in_the_brief(self):
        db = _db()
        db.users.rows.append({"_id": "u_cp_b", "company_id": CO_B, "role": "cp",
                              "phone": "+" + ADMIN_PHONE, "name": "Ada as CP",
                              "assigned_projects": ["proj_b"]})
        now = datetime.now(timezone.utc)
        db[server.WA_OPTINS].rows += [
            {"_id": "o1", "phone": ADMIN_PHONE, "user_id": "u_cp_b", "company_id": CO_B,
             "status": "active", "chat_id": f"{ADMIN_PHONE}@c.us", "opted_in_at": now.replace(year=2025)},
            {"_id": "o2", "phone": ADMIN_PHONE, "user_id": "u_admin", "company_id": CO_A,
             "status": "active", "chat_id": f"{ADMIN_PHONE}@c.us", "opted_in_at": now}]
        with _Ctx(db):
            admin = db.users.rows[0]
            accounts = _run(server._brief_accounts(admin))
            lead, companies = _run(server._upcoming_person_account(ADMIN_PHONE))
            # Answered as both when they ask.
            both = _run(server._dm_identities(f"{ADMIN_PHONE}@c.us"))
        self.assertEqual([u["_id"] for u in accounts], ["u_admin"])
        self.assertEqual((lead["user_id"], companies), ("u_admin", [CO_A]))
        self.assertEqual(sorted(i["user_id"] for i in both), ["u_admin", "u_cp_b"])


# ── THE SERVER'S GATE, PER CALL ─────────────────────────────────────────────

def _ctx(ident, text="approve the sequence"):
    jobs = [{"id": str(p["_id"]), "label": p.get("address") or p.get("name"), "project": p, "aliases": []}
            for p in ident.get("projects") or []]
    return {"ident": ident, "dm_chat": f"{CP_PHONE}@c.us", "text": text, "jobs": jobs,
            "by_id": {j["id"]: j for j in jobs}, "active": None, "dry_run": False, "sent": [],
            "used_job": None, "t0": None, "person": None, "turn": {"own_text": text}}


class RefusedPerCall(unittest.TestCase):

    def test_reserved_tools_are_refused_and_write_nothing(self):
        calls = {"propose_change": {"action": "add_sub", "company": "Arkon", "trade": "framing"},
                 "set_sub_trade": {"company": "Arkon", "trade": "framing"},
                 "undo_last_change": {}, "send_report": {"jobs": ["all"], "period": "last week"},
                 "answer_pending_change": {"answer": "1"}, "remind_me": {"what": "x", "date": "2026-12-01"},
                 "dob_status": {}, "list_subs": {}, "resend_my_brief": {}}
        with _Ctx() as c:
            ident = _cp_ident(c)
            c.wire.calls.clear()
            for name, args in calls.items():
                with self.subTest(name):
                    out = _run(server._dm_brain_exec_one(_ctx(ident, "add Arkon as framer"), name, args))
                    self.assertTrue(out.startswith("REFUSED"), out)
            self.assertEqual(c.db[server._DM_STATE].rows, [])
            self.assertEqual(c.wire.calls, [])

    def test_approving_a_sequence_is_refused_by_the_server(self):
        with _Ctx() as c:
            ident = _cp_ident(c)
            c.db[server.PROPOSED_SEQUENCES].rows.append(
                {"_id": f"{CO_A}:proj_a", "company_id": CO_A, "project_id": "proj_a",
                 "status": "proposed", "levels": [], "history": []})
            out = _run(server._dm_brain_exec_one(_ctx(ident), "proposed_sequence",
                                                 {"job": "proj_a", "approve": True}))
            # And the tool itself refuses, behind the gate.
            direct = _run(server._dm_proposed_sequence(_ctx(ident), {"id": "proj_a", "label": "1 A St"},
                                                       {"approve": True}))
            row = c.db[server.PROPOSED_SEQUENCES].rows[0]
        self.assertIn("approving a sequence", out)
        self.assertIn("approving a sequence", direct)
        self.assertEqual(row["status"], "proposed")

    def test_a_field_role_views_a_proposed_sequence_and_nothing_is_stored(self):
        from lib import work_state as W
        rows = [{"date": date(2026, 10, 1), "nodes": ["framing"], "levels": ["FLOOR_3"], "generic": False,
                 "log_id": "l1", "text": "framing 3"}]

        async def evidence(project, company_id, days):
            return {}, rows, date(2026, 11, 9), date(2026, 1, 1)
        with _Ctx() as c, patch.object(server, "_schedule_evidence", evidence):
            ident = _cp_ident(c)
            seen = _run(server._dm_brain_exec_one(_ctx(ident, "show me the sequence"), "proposed_sequence",
                                                  {"job": "proj_a"}))
            self.assertEqual(c.db[server.PROPOSED_SEQUENCES].rows, [])
            admin = dict(ident, role="admin", user_id="u_admin")
            _run(server._dm_proposed_sequence(_ctx(admin, "show me"), {"id": "proj_a", "label": "1 A St"}, {}))
            self.assertEqual(len(c.db[server.PROPOSED_SEQUENCES].rows), 1)   # the control: an admin's view stores it
        self.assertIn("PROPOSED sequence", seen)
        self.assertIn("A PM or an admin can approve it.", seen)
        self.assertNotIn('say "approve the sequence"', seen)
        self.assertTrue(W)

    def test_a_job_they_are_not_assigned_to_is_not_theirs(self):
        with _Ctx() as c:
            ident = _cp_ident(c)
            out = _run(server._dm_brain_exec_one(_ctx(ident, "what's on 3 at 2 A St"), "work_status",
                                                 {"job": "proj_a2", "work": "drywall", "level": "3"}))
        self.assertIn("None of their jobs matches", out)

    def test_an_allowed_tool_passes_the_gate(self):
        with _Ctx() as c:
            ident = _cp_ident(c)
            out = _run(server._dm_brain_exec_one(_ctx(ident, "never mind"), "cancel_pending_change", {}))
        self.assertEqual(out, "Nothing was pending.")


class TheChangeFlowsLastGate(unittest.TestCase):

    def test_a_held_change_is_not_made_for_a_field_role(self):
        done = []

        async def add_sub(ident, p):
            done.append(p)
            return {"kind": "x"}, "Saved."
        with _Ctx() as c, patch.dict(server._DM_DO, {"add_sub": add_sub}):
            ident = _cp_ident(c)
            c.wire.calls.clear()
            _run(server._dm_action_do(ident, f"{CP_PHONE}@c.us", {"action": "add_sub", "lang": "en"}))
            said = c.said()
        self.assertEqual(done, [])
        self.assertEqual(said, [server.DM_FIELD_CHANGE_TEXT])


class TheMessagePath(unittest.TestCase):

    def test_with_the_brain_off_a_field_role_gets_one_line_not_the_admin_pipeline(self):
        with _Ctx() as c, patch.object(server, "DM_BRAIN_API_KEY", ""):
            _process(CP_PHONE, "START", "S1")
            c.wire.calls.clear()
            _process(CP_PHONE, "add a job at 5 Main St", "D2")
            said = c.said()
            self.assertEqual(said, [dm_roles.FIELD_UNAVAILABLE_TEXT])
            self.assertEqual(c.db[server._DM_STATE].rows, [])

    def test_a_photo_that_is_no_sign_off_starts_no_walkthrough(self):
        """A walkthrough sends a punch list to subs: a PM's / admin's flow."""
        walks = []

        async def punch_turn(*a, **k):
            walks.append(a)
            return True
        with _Ctx() as c, patch.object(server, "DM_BRAIN_API_KEY", "k"), \
                patch.object(server, "_punch_dm_turn", punch_turn):
            _process(CP_PHONE, "START", "S1")
            c.wire.calls.clear()
            _run(server._process_whatsapp_message(_payload(CP_PHONE, "", "P1", type="image")))
            said = c.said()
        self.assertEqual(walks, [])
        self.assertEqual(said, [dm_roles.FIELD_PHOTO_TEXT])

    def test_with_the_brain_off_a_photo_gets_the_unavailable_line(self):
        with _Ctx() as c, patch.object(server, "DM_BRAIN_API_KEY", ""):
            _process(CP_PHONE, "START", "S1")
            c.wire.calls.clear()
            _run(server._process_whatsapp_message(_payload(CP_PHONE, "", "P1", type="image")))
            self.assertEqual(c.said(), [dm_roles.FIELD_UNAVAILABLE_TEXT])


if __name__ == "__main__":
    unittest.main()
