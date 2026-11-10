"""Permissions, tenancy and cost on the progress engine (fix/pe-perm).

An independent review reproduced five defects on feat/progress-integrated;
those reproductions are the first three classes below, turned to assert the
fixed behaviour (each one FAILS against origin/feat/progress-integrated):

  * a PENDING account wrote a photo-place confirmation and APPROVED the
    official PROPOSED sequence by DM (the DM never passes require_approved);
  * the two new HTTP routes admitted a CP / superintendent to every project
    of his company (require_project_access's company branch), and a site
    device / kiosk token could write a confirmation;
  * a person with a CP account and a PM account on one phone lost his
    reminders when the CP account was listed first.

The rest hold each fix and what it must keep working: the assigned CP and
the admin still reach both routes, an approved PM still approves, a sign-off
photo still asks "Which company?", and the cost / data fixes (the re-read's
switch and cap, the sign-off read's atomic cap, the permit-expiry alert, the
deletion cascade, the indexes, the eval's CP job list).
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

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import photo_search, vision_meter  # noqa: E402
from tests._fake_mongo import Coll, FakeDb  # noqa: E402

CO_A = "co_a"
CHAT = "15550001003@c.us"


def _run(c):
    return asyncio.run(c)


def _db():
    now = datetime.now(timezone.utc)
    return FakeDb(
        projects=[{"_id": "proj_a", "company_id": CO_A, "name": "A", "address": "1 A St"},
                  {"_id": "proj_a2", "company_id": CO_A, "name": "A2", "address": "2 A St"},
                  {"_id": "proj_b", "company_id": "co_b", "name": "B", "address": "1 B St"}],
        photo_index=[{"_id": "v1:k1", "kind": "photo", "project_id": "proj_a", "company_id": CO_A,
                      "short": "abc123", "photo_key": "k1", "where": "", "date": "2026-11-01"},
                     {"_id": "v1:k2", "kind": "photo", "project_id": "proj_a2", "company_id": CO_A,
                      "short": "def456", "photo_key": "k2", "where": "", "date": "2026-11-01"}],
        whatsapp_messages=[{"group_id": CHAT, "is_dm": True, "sender": "bot",
                            "photo_place_asked": "abc123", "created_at": now, "timestamp": now}],
        proposed_sequences=[{"_id": f"{CO_A}:proj_a", "company_id": CO_A, "project_id": "proj_a",
                             "status": "proposed", "levels": [{"level": "3", "label": "Floor 3", "first_reported": "2026-10-01", "steps": [{"id": "x", "label": "framing", "gate": None, "conditional": False, "first_reported": None}]}], "history": []}],
    )


def _ident(role, status, uid="u1", projects=None, company=CO_A):
    projects = projects if projects is not None else [{"_id": "proj_a", "company_id": company, "name": "A",
                                                       "address": "1 A St"}]
    return {"user": {"_id": uid, "role": role, "company_id": company, "name": "X", "account_status": status},
            "user_id": uid, "company_id": company, "role": role, "projects": projects}


async def _ctx(ident, text, person=None):
    jobs = await server._dm_jobs(ident)
    for j in jobs:
        j["acct"] = ident
    return {"ident": ident, "dm_chat": CHAT, "text": text, "jobs": jobs, "by_id": {j["id"]: j for j in jobs},
            "active": jobs[0]["id"] if jobs else None, "dry_run": False, "sent": [], "used_job": None,
            "person": person, "turn": {"own_text": text}, "field_only": False}


async def _no_evidence(project, cid, days):
    return {"schedule": None}, [], None, None


def _cp(assigned=("proj_a",), role="cp"):
    return {"id": "u_cp", "_id": "u_cp", "role": role, "company_id": CO_A, "account_status": "approved",
            "assigned_projects": list(assigned), "name": "Cal CP"}


ADMIN = {"id": "u_admin", "_id": "u_admin", "role": "admin", "company_id": CO_A, "account_status": "approved",
         "name": "Ada Admin"}
DEVICE = {"id": "dev1", "role": "site_device", "site_mode": True, "project_id": "proj_a", "company_id": CO_A}


# ── THE REVIEW'S REPRODUCTIONS, ASSERTING THE FIX ───────────────────────────

class PendingWrites(unittest.TestCase):

    def test_pending_cp_writes_no_photo_place_confirmation(self):
        db = _db()
        with patch.object(server, "db", db):
            ident = _ident("cp", "pending")
            out = _run(server._dm_brain_exec_one(_run(_ctx(ident, "3")), "confirm_photo_place", {"job": "proj_a"}))
        self.assertEqual(db["photo_place_confirmations"].rows, [], out)
        self.assertIn("isn't approved", out)

    def test_pending_admin_does_not_approve_the_proposed_sequence(self):
        db = _db()
        with patch.object(server, "db", db), patch.object(server, "_schedule_evidence", _no_evidence):
            ident = _ident("admin", "pending")
            out = _run(server._dm_brain_exec_one(_run(_ctx(ident, "approve the sequence")),
                                                 "proposed_sequence", {"job": "proj_a", "approve": True}))
            row = _run(db["proposed_sequences"].find_one({"_id": f"{CO_A}:proj_a"}))
        self.assertEqual((row.get("status"), row.get("approved_by")), ("proposed", None), out)
        self.assertIn("isn't approved", out)


class HttpRouteScope(unittest.TestCase):

    def test_cp_is_refused_an_unassigned_project_on_the_confirmation_route(self):
        db = _db()
        with patch.object(server, "db", db):
            # The route's dependency still admits him (company branch): the
            # handler is what holds him to his assignments.
            self.assertEqual(_run(server.require_project_access("proj_a2", _cp()))["_id"], "proj_a2")
            body = server.PhotoPlaceConfirmation(photo="def456", level="5")
            with self.assertRaises(HTTPException) as e:
                _run(server.confirm_photo_place("proj_a2", body, current_user=_cp()))
        self.assertEqual(e.exception.status_code, 403)
        self.assertEqual(db["photo_place_confirmations"].rows, [])

    def test_a_site_device_may_not_write_a_confirmation(self):
        db = _db()
        with patch.object(server, "db", db):
            _run(server.require_approved(DEVICE))                    # the device passes the approval gate
            _run(server.require_project_access("proj_a", DEVICE))   # and the project gate
            with self.assertRaises(HTTPException) as e:
                _run(server.confirm_photo_place(
                    "proj_a", server.PhotoPlaceConfirmation(photo="abc123", level="roof"), current_user=DEVICE))
        self.assertEqual(e.exception.status_code, 403)
        self.assertEqual(db["photo_place_confirmations"].rows, [])


class MixedPerson(unittest.TestCase):

    def test_pm_with_a_cp_account_listed_first_keeps_his_reminders(self):
        db = _db()
        with patch.object(server, "db", db):
            cp = _ident("cp", "approved", uid="u_cp")
            pm = _ident("admin", "approved", uid="u_pm", company="co_b",
                        projects=[{"_id": "proj_b", "company_id": "co_b", "name": "B", "address": "1 B St"}])
            ctx = _run(_ctx(cp, "remind me friday at 9 to call the inspector", person=[cp, pm]))
            out = _run(server._dm_brain_exec(ctx, "remind_me", {"what": "call the inspector", "date": "2026-11-13"}))
        self.assertNotIn("REFUSED", out)


# ── 1. THE HTTP ROUTES: ASSIGNED PROJECTS, NO DEVICE WRITES, COMPANY SCOPE ───

class ConfirmationRoute(unittest.TestCase):

    def _post(self, user, project="proj_a", photo="abc123"):
        db = _db()
        db["photo_index"].rows.append({"_id": "v1:k3", "kind": "photo", "project_id": "proj_b", "company_id": "co_b",
                                       "short": "b0b0b0", "photo_key": "k3", "where": "", "date": "2026-11-01"})
        with patch.object(server, "db", db):
            doc = _run(server.confirm_photo_place(
                project, server.PhotoPlaceConfirmation(photo=photo, level="3"), current_user=user))
        return doc, db["photo_place_confirmations"].rows

    def test_an_assigned_cp_still_records(self):
        doc, rows = self._post(_cp())
        self.assertEqual((doc["project_id"], doc["by_user_id"], len(rows)), ("proj_a", "u_cp", 1))

    def test_an_unassigned_superintendent_is_refused(self):
        with self.assertRaises(HTTPException) as e:
            self._post(_cp(assigned=(), role="superintendent"))
        self.assertEqual(e.exception.status_code, 403)

    def test_an_admin_records_on_any_job_of_his_company(self):
        doc, rows = self._post(ADMIN, project="proj_a2", photo="def456")
        self.assertEqual((doc["project_id"], len(rows)), ("proj_a2", 1))

    def test_an_assignment_to_another_companys_job_is_not_a_way_in(self):
        with self.assertRaises(HTTPException) as e:
            # proj_b holds a photo with this id: only the company scope refuses.
            self._post(_cp(assigned=("proj_b",)), project="proj_b", photo="b0b0b0")
        self.assertEqual(e.exception.status_code, 404)

    def test_the_route_keeps_its_dependencies(self):
        route = next(r for r in server.app.routes
                     if getattr(r, "path", "") == "/api/projects/{project_id}/photo-place-confirmations")
        deps = {d.call for d in route.dependant.dependencies}
        self.assertTrue({server.require_approved, server.require_project_access} <= deps)


class ProgressRoute(unittest.TestCase):

    def _get(self, user, project="proj_a"):
        db = _db()

        async def model(project_doc, cid, **kw):
            return {"project": str(project_doc.get("_id")), "company": cid}
        with patch.object(server, "db", db), patch.object(server, "_project_progress", model), \
                patch.object(server.project_progress, "to_json", lambda m: dict(m)):
            return _run(server.get_project_progress(project, current_user=user))

    def test_an_unassigned_cp_is_refused(self):
        with self.assertRaises(HTTPException) as e:
            self._get(_cp(), project="proj_a2")
        self.assertEqual(e.exception.status_code, 403)

    def test_an_unassigned_superintendent_is_refused(self):
        with self.assertRaises(HTTPException) as e:
            self._get(_cp(assigned=(), role="superintendent"))
        self.assertEqual(e.exception.status_code, 403)

    def test_an_assigned_cp_and_an_admin_still_read_it(self):
        self.assertEqual(self._get(_cp())["project_id"], "proj_a")
        self.assertEqual(self._get(ADMIN, project="proj_a2")["project_id"], "proj_a2")

    def test_the_kiosk_still_reads_its_own_project(self):
        self.assertEqual(self._get(DEVICE)["project_id"], "proj_a")


# ── 2 & 3. A PENDING ACCOUNT WRITES NOTHING BY DM ───────────────────────────

class ProposedSequenceApproval(unittest.TestCase):

    def _call(self, role, status, text, args, db=None):
        db = db or _db()
        with patch.object(server, "db", db), patch.object(server, "_schedule_evidence", _no_evidence), \
                patch.object(server.progress_plan, "propose_sequence",
                             lambda rows: {"levels": [{"level": "5", "label": "Floor 5", "first_reported": "2026-10-02",
                                                       "steps": [{"id": "x", "label": "framing", "gate": None,
                                                                  "conditional": False, "first_reported": None}]}],
                                           "graph_version": 1}):
            out = _run(server._dm_brain_exec_one(_run(_ctx(_ident(role, status), text)), "proposed_sequence",
                                                 dict(args, job="proj_a")))
        return out, db["proposed_sequences"].rows

    def test_a_pending_admin_viewing_stores_and_rebuilds_nothing(self):
        empty = _db()
        empty["proposed_sequences"].rows = []
        _out, rows = self._call("admin", "pending", "show me the sequence", {}, db=empty)
        self.assertEqual(rows, [], "a view by a pending account inserted a row")
        _out, rows = self._call("admin", "pending", "show me the sequence", {})
        self.assertEqual((rows[0]["levels"][0]["level"], rows[0]["history"]), ("3", []),
                         "a view by a pending account rebuilt the stored one")

    def test_an_approved_admin_still_approves_and_still_stores_on_view(self):
        _out, rows = self._call("admin", "approved", "approve the sequence", {"approve": True})
        self.assertEqual((rows[0]["status"], rows[0]["approved_by"]), ("approved", "u1"))
        empty = _db()
        empty["proposed_sequences"].rows = []
        _out, rows = self._call("pm", "approved", "show me", {}, db=empty)
        self.assertEqual(rows[0]["status"], "proposed")


class PhotoPlaceByDm(unittest.TestCase):

    def test_an_approved_cp_still_records_the_floor(self):
        db = _db()
        with patch.object(server, "db", db):
            out = _run(server._dm_brain_exec_one(_run(_ctx(_ident("cp", "approved"), "3")),
                                                 "confirm_photo_place", {"job": "proj_a"}))
        self.assertEqual(len(db["photo_place_confirmations"].rows), 1, out)


# ── 4. ONE PERSON, A CP ACCOUNT AND A PM ACCOUNT ───────────────────────────

class MixedPersonRouting(unittest.TestCase):

    def setUp(self):
        self.db = _db()
        self.cp = _ident("cp", "approved", uid="u_cp")
        self.pm = _ident("pm", "approved", uid="u_pm", company="co_b",
                         projects=[{"_id": "proj_b", "company_id": "co_b", "name": "B", "address": "1 B St"}])
        self.sent = []

        async def send(chat, text, *a, **k):
            self.sent.append(text)
            return True
        self._ps = [patch.object(server, "db", self.db), patch.object(server, "send_whatsapp_message", send)]
        for p in self._ps:
            p.start()

    def tearDown(self):
        for p in reversed(self._ps):
            p.stop()

    def _route(self, text, **kw):
        return _run(server._dm_route_accounts([self.cp, self.pm], CHAT, text, brain=True, **kw))

    def test_remind_me_goes_to_the_account_that_keeps_reminders(self):
        got = self._route("remind me friday at 9 to call the inspector")
        self.assertEqual(got["ident"]["user_id"], "u_pm")

    def test_a_change_with_no_job_goes_to_the_one_account_that_may_make_it(self):
        got = self._route("add John Smith 718-555-0101 as the foreman")
        self.assertEqual((got or {}).get("ident", {}).get("user_id"), "u_pm", self.sent)
        self.assertEqual(self.sent, [], "a Which company? was asked")

    def test_a_walkthrough_photo_goes_to_the_manager_account(self):
        got = self._route("", has_image=True)
        self.assertEqual((got or {}).get("ident", {}).get("user_id"), "u_pm", self.sent)

    def test_a_sign_off_photo_still_asks_which_company(self):
        got = self._route("plumbing rough sign off floor 3", has_image=True, signoff=True)
        self.assertIsNone(got)
        self.assertEqual(len(self.sent), 1)

    def test_a_change_by_the_brain_runs_as_the_manager_account(self):
        ran = []

        async def as_(ctx, acct, name, args):
            ran.append(acct["user_id"])
            return "ok"
        ctx = _run(_ctx(self.cp, "add a sub", person=[self.cp, self.pm]))
        ctx["jobs"] += [dict(j, acct=self.pm) for j in _run(server._dm_jobs(self.pm))]
        ctx["by_id"] = {j["id"]: j for j in ctx["jobs"]}
        with patch.object(server, "_dm_brain_as", as_):
            _run(server._dm_brain_exec(ctx, "propose_change", {"request": "add a sub"}))
            _run(server._dm_brain_exec(ctx, "my_settings", {}))
        self.assertEqual(ran, ["u_pm", "u_pm"])


# ── 5. THE RE-READ: ITS OWN SWITCH, A DAILY CAP, SKIPPED ROWS MARKED ────────

def _old_row(i, where="floors 1-4"):
    return {"_id": f"v1:k/{i}.jpg", "kind": "photo", "photo_key": f"k/{i}.jpg", "short": f"s{i}", "where": where,
            "date": f"2026-10-{10 + i:02d}", "project_id": "proj_a", "company_id": CO_A, "log_id": "L1"}


class Reread(unittest.TestCase):

    def _go(self, rows, env, budget=50, state=None):
        db = FakeDb(photo_index=list(rows) + ([state] if state else []))
        calls = []

        async def vision(raw, project):
            calls.append(raw)
            return {"view": "interior", "quality": 5.0, "description": "d", "tags": [],
                    "visible_text": ["4A"], "room_type": "kitchen"}

        async def bytes_of(row):
            return b"x"
        report = {}
        with patch.object(server, "db", db), patch.object(server, "_photo_index_call", vision), \
                patch.object(server, "_photo_log_bytes", bytes_of), patch.dict(os.environ, env):
            _run(server._photo_index_reread(budget, report))
        return calls, report, db

    def test_off_by_default(self):
        env = {k: v for k, v in os.environ.items() if k != "PHOTO_INDEX_REREAD_ENABLED"}
        with patch.dict(os.environ, env, clear=True):
            calls, _r, _db = self._go([_old_row(1)], {})
        self.assertEqual(calls, [])

    def test_on_it_reads_and_a_row_it_will_never_read_is_marked_once(self):
        calls, report, db = self._go([_old_row(1), _old_row(2, where="floor 3")],
                                     {"PHOTO_INDEX_REREAD_ENABLED": "1"})
        self.assertEqual((len(calls), report.get("reread")), (1, 1))
        single = next(r for r in db[server.PHOTO_INDEX].rows if r["_id"] == "v1:k/2.jpg")
        self.assertEqual(single.get("reread_skip"), photo_search.PROMPT_V)

    def test_the_daily_cap_holds_across_ticks(self):
        day = vision_meter.eastern_day()
        near = {"_id": server.PHOTO_INDEX_REREAD_STATE, "kind": "state", "day": day,
                "calls": server.PHOTO_INDEX_REREAD_DAILY_CAP - 2}
        calls, _r, db = self._go([_old_row(i) for i in range(1, 6)], {"PHOTO_INDEX_REREAD_ENABLED": "1"}, state=near)
        self.assertEqual(len(calls), 2)
        calls, report, _db = self._go([_old_row(i) for i in range(1, 6)], {"PHOTO_INDEX_REREAD_ENABLED": "1"},
                                      state=next(r for r in db[server.PHOTO_INDEX].rows
                                                 if r["_id"] == server.PHOTO_INDEX_REREAD_STATE))
        self.assertEqual((calls, report.get("reread_capped")), ([], True))

    def test_yesterdays_count_is_not_todays(self):
        old = {"_id": server.PHOTO_INDEX_REREAD_STATE, "kind": "state", "day": "2000-01-01",
               "calls": server.PHOTO_INDEX_REREAD_DAILY_CAP}
        calls, _r, _db = self._go([_old_row(1)], {"PHOTO_INDEX_REREAD_ENABLED": "1"}, state=old)
        self.assertEqual(len(calls), 1)

    def test_the_describe_call_asks_for_at_most_300_tokens(self):
        posted = []

        class _Resp:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": '{"view":"interior","description":"d"}'}}]}

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                posted.append(json)
                return _Resp()

        async def meter(*a, **k):
            return None
        with patch.object(server, "QWEN_API_KEY", "x"), patch.object(server, "ServerHttpClient", _Client), \
                patch.object(server, "_vision_jpeg", lambda raw: (raw, None)), \
                patch.object(server, "record_vision_call", meter):
            _run(server._photo_index_call(b"jpeg", "proj_a"))
        self.assertEqual(posted[0]["max_tokens"], 300)


# ── 6. THE SIGN-OFF READ'S CAP IS ONE ATOMIC WRITE ─────────────────────────

class _Yielding(Coll):
    """A collection whose every read and write gives the loop a turn first,
    as a real driver does: two requests can then interleave between them."""

    async def find_one(self, *a, **k):
        await asyncio.sleep(0)
        return await super().find_one(*a, **k)

    async def update_one(self, *a, **k):
        await asyncio.sleep(0)
        return await super().update_one(*a, **k)


class SignoffCap(unittest.TestCase):

    def test_two_reads_at_once_at_the_last_slot_make_one_call(self):
        db = FakeDb()
        meter = db._c[vision_meter.COLLECTION] = _Yielding(vision_meter.COLLECTION)
        key = vision_meter.meter_key(vision_meter.eastern_day(), "proj_a", server.VISION_INSPECTION_DOC)
        meter.rows.append({"_id": key, "calls": server.INSPECTION_DOC_DAILY_CAP - 1})
        posts = []

        class _Resp:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": "{}"}}]}

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                posts.append(1)
                await asyncio.sleep(0)
                return _Resp()

        async def both():
            return await asyncio.gather(*(server._inspection_doc_read(b"p", "proj_a", datetime.now().date())
                                          for _ in range(2)))
        with patch.object(server, "db", db), patch.object(server, "QWEN_API_KEY", "x"), \
                patch.object(server, "ServerHttpClient", _Client):
            _run(both())
        self.assertEqual(len(posts), 1, "two reads went past a cap with one slot left")
        self.assertEqual(meter.rows[0]["calls"], server.INSPECTION_DOC_DAILY_CAP)

    def test_under_the_cap_it_counts_and_reads(self):
        db = FakeDb()
        with patch.object(server, "db", db):
            self.assertTrue(_run(server._inspection_doc_claim_call("proj_a")))
            self.assertTrue(_run(server._inspection_doc_claim_call("proj_a")))
        (row,) = db[vision_meter.COLLECTION].rows
        self.assertEqual((row["calls"], row["endpoint"]), (2, server.VISION_INSPECTION_DOC))


# ── 6. A SIGNED-OFF PERMIT IS NOT AN EXPIRY ALERT ─────────────────────────

class PermitExpiry(unittest.TestCase):

    def test_a_signed_off_permit_is_not_flagged_expired_and_an_open_one_is(self):
        gone = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        soon = (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat()
        db = FakeDb(dob_logs=[
            {"_id": "p_done", "record_type": "permit", "expiration_date": gone, "permit_status": "Signed-off"},
            {"_id": "p_done_soon", "record_type": "permit", "expiration_date": soon, "permit_status": "Signed-off"},
            {"_id": "p_open", "record_type": "permit", "expiration_date": gone, "permit_status": "Issued"},
            {"_id": "p_soon", "record_type": "permit", "expiration_date": soon, "permit_status": "Issued"}])
        with patch.object(server, "db", db):
            _run(server.check_permit_expirations())
        by = {r["_id"]: r for r in db.dob_logs.rows}
        self.assertNotIn("next_action", by["p_done"])
        self.assertNotIn("next_action", by["p_done_soon"])
        self.assertIn("EXPIRED", by["p_open"]["next_action"])
        self.assertIn("expires in", by["p_soon"]["next_action"])


# ── 6. DELETION CASCADE AND INDEXES ───────────────────────────────────────

class CascadeAndIndexes(unittest.TestCase):

    def test_a_deleted_project_takes_the_progress_engines_rows(self):
        for coll in (server.INSPECTION_REPORTS, server.PHOTO_PLACE_CONFIRMATIONS, server.PHOTO_RELATIONS):
            self.assertIn(coll, server._PROJECT_OWNED_COLLECTIONS)

    def test_the_indexes_match_the_queries(self):
        db = FakeDb()
        with patch.object(server, "db", db):
            _run(server.ensure_whatsapp_phase1_indexes())
        by = {ix["name"]: (c.name, ix["keys"]) for c in db._c.values() for ix in c.indexes}
        self.assertEqual(by["photo_relations_by_place"],
                         (server.PHOTO_RELATIONS, [("project_id", 1), ("level", 1), ("same_place", 1)]))
        self.assertEqual(by["photo_place_confirmations_by_project"][0], server.PHOTO_PLACE_CONFIRMATIONS)
        self.assertEqual(by["photo_index_by_prompt_v"],
                         (server.PHOTO_INDEX, [("kind", 1), ("prompt_v", 1), ("reread_skip", 1)]))


# ── 6. THE EVAL'S "ROLE REPLACED" CP HAS THE CP'S OWN JOBS ─────────────────

class EvalRoleReplaced(unittest.TestCase):

    def test_a_replaced_cp_has_only_the_jobs_assigned_to_that_person(self):
        sys.path.insert(0, str(Path(server.__file__).resolve().parent / "scripts"))
        import dm_brain_eval as ev
        admin = _ident("admin", "approved", uid="u_admin",
                       projects=[{"_id": "proj_a", "company_id": CO_A}, {"_id": "proj_a2", "company_id": CO_A}])
        admin["user"]["assigned_projects"] = ["proj_a2"]
        db = _db()
        with patch.object(server, "db", db):
            _chat, ident, note = _run(ev._as_role(server, admin, "cp", "", {}))
        self.assertEqual([str(p["_id"]) for p in ident["projects"]], ["proj_a2"])
        self.assertEqual(ident["role"], "cp")
        self.assertIn("role replaced by cp", note)


if __name__ == "__main__":
    unittest.main()
