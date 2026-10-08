"""WhatsApp Phase 0 — the tenant boundary, the webhook, and the bot's own echo.

Two companies, A and B, each with one project. Every path that can put project
data into a WhatsApp chat is exercised with a group that belongs to A, and the
assertion is always the same shape: nothing of B's comes out, and nothing is
posted that a bad record could have pointed at B.

A bad record is the threat model, not a hypothetical. The code-link path took
`project_id` from the request body with no ownership check until this change,
so a group row naming A's company and B's project could exist today. The
binding resolver must refuse it, and — defence in depth — every reader below
it must refuse it again on its own.

Fixtures are in-memory; no database, no network, no WaAPI.
"""

from __future__ import annotations

import asyncio
import logging
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

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from lib import wa_security  # noqa: E402

NOW = datetime.now(timezone.utc)

CO_A, CO_B = "co_a", "co_b"
PROJ_A = {"_id": "proj_a", "company_id": CO_A, "name": "A Project",
          "address": "1 A Street"}
PROJ_B = {"_id": "proj_b", "company_id": CO_B, "name": "B SECRET PROJECT",
          "address": "99 B SECRET Street", "nyc_bin": "9999999"}
GROUP = "120363000000000001@g.us"
HUMAN = "15550001111"
BOT_NUMBER = "15559998888"
SECRET = "B SECRET"


# ── an in-memory Mongo, enough for these fixtures ─────────────────────────

def _cmp_in(val, options):
    if isinstance(val, list):
        return any(v in options for v in val)
    return val in options


def _matches(doc, query):
    for key, cond in (query or {}).items():
        if key == "$or":
            if not any(_matches(doc, c) for c in cond):
                return False
            continue
        val = doc.get(key)
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            if "$in" in cond and not _cmp_in(val, cond["$in"]):
                return False
            if "$ne" in cond and val == cond["$ne"]:
                return False
            if "$exists" in cond and (key in doc) != bool(cond["$exists"]):
                return False
            if "$gte" in cond and not (val is not None and val >= cond["$gte"]):
                return False
            if "$lt" in cond and not (val is not None and val < cond["$lt"]):
                return False
            if "$lte" in cond and not (val is not None and val <= cond["$lte"]):
                return False
        elif isinstance(val, list) and not isinstance(cond, list):
            if cond not in val:
                return False
        elif val != cond:
            return False
    return True


class _Res:
    def __init__(self, matched=0, modified=0, inserted_id=None):
        self.matched_count = matched
        self.modified_count = modified
        self.inserted_id = inserted_id
        self.deleted_count = matched


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return list(self.rows)

    def __aiter__(self):
        self._it = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Coll:
    def __init__(self, rows=None):
        self.rows = [dict(r) for r in (rows or [])]
        self.reads = 0
        self.inserts = []

    async def find_one(self, query=None, projection=None, *a, **k):
        self.reads += 1
        for r in self.rows:
            if _matches(r, query):
                return dict(r)
        return None

    def find(self, query=None, projection=None, *a, **k):
        self.reads += 1
        return _Cursor([dict(r) for r in self.rows if _matches(r, query)])

    async def count_documents(self, query=None, *a, **k):
        self.reads += 1
        return sum(1 for r in self.rows if _matches(r, query))

    async def insert_one(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", f"id{len(self.rows) + 1}")
        self.rows.append(doc)
        self.inserts.append(doc)
        return _Res(inserted_id=doc["_id"])

    async def update_one(self, query, update, upsert=False, **k):
        for r in self.rows:
            if _matches(r, query):
                r.update(update.get("$set", {}))
                return _Res(1, 1)
        if upsert:
            new = {k2: v for k2, v in (query or {}).items()
                   if not isinstance(v, dict) and not k2.startswith("$")}
            new.update(update.get("$setOnInsert", {}))
            new.update(update.get("$set", {}))
            await self.insert_one(new)
            return _Res(0, 0)
        return _Res(0, 0)

    async def update_many(self, query, update, **k):
        n = 0
        for r in self.rows:
            if _matches(r, query):
                r.update(update.get("$set", {}))
                n += 1
        return _Res(n, n)

    async def delete_one(self, query):
        before = len(self.rows)
        for i, r in enumerate(self.rows):
            if _matches(r, query):
                del self.rows[i]
                break
        return _Res(before - len(self.rows))


class _Db:
    def __init__(self, **collections):
        self.__dict__["_c"] = {k: _Coll(v) for k, v in collections.items()}

    def __getitem__(self, name):
        return self._c.setdefault(name, _Coll())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]


def _group_row(company, project, wa_group_id=GROUP, _id=None, **cfg):
    bot_config = server._default_bot_config()
    bot_config.update(cfg)
    return {"_id": _id or f"grp_{company}_{project}", "wa_group_id": wa_group_id,
            "company_id": company, "project_id": project, "active": True,
            "linked_at": NOW - timedelta(days=30), "bot_config": bot_config}


# Company B's data, sitting under B's project — and, for the defence-in-depth
# cases, one B row that a bad write stamped with A's project id.
def _b_data():
    return dict(
        checkins=[{"project_id": "proj_b", "worker_name": f"{SECRET} worker",
                   "status": "checked_in", "check_in_time": NOW}],
        dob_logs=[
            {"project_id": "proj_b", "company_id": CO_B,
             "record_type": "violation", "description": f"{SECRET} violation",
             "detected_at": NOW},
            {"project_id": "proj_b", "company_id": CO_B,
             "record_type": "permit", "permit_type": f"{SECRET} permit",
             "expiration_date": NOW + timedelta(days=10)},
            # Mis-stamped: A's project id, B's company.
            {"project_id": "proj_a", "company_id": CO_B,
             "record_type": "violation", "description": f"{SECRET} misfiled",
             "detected_at": NOW},
        ],
        daily_logs=[{"project_id": "proj_b", "date": server.eastern_today(),
                     "observations": [{"description": f"{SECRET} obs"}]}],
        logbooks=[{"project_id": "proj_b", "date": server.eastern_today(),
                   "log_type": "daily_jobsite", "data": {"work": SECRET}}],
        material_requests=[{"project_id": "proj_b", "company_id": CO_B,
                            "status": "open", "requested_by_trade": SECRET,
                            "items": [{"name": SECRET, "status": "pending"}],
                            "created_at": NOW}],
        document_page_index=[{"project_id": "proj_b", "sheet_number": "S-1",
                              "sheet_title": SECRET}],
    )


def _run(coro):
    return asyncio.run(coro)


def _recording_send(log):
    async def _send(chat_id, message, reply_to=None, **k):
        log.append((chat_id, message))
        return {"ok": True}
    return _send


def _payload(body, *, from_me=False, author=f"{HUMAN}@c.us", group=GROUP,
             msg_id="M1", event="message"):
    return {"event": event, "data": {"message": {
        "id": {"id": msg_id, "fromMe": from_me,
               "_serialized": f"{str(from_me).lower()}_{group}_{msg_id}"},
        "from": group, "author": author, "body": body, "type": "chat",
        "timestamp": int(NOW.timestamp()),
    }}}


class _NoNetwork:
    """ServerHttpClient stand-in that fails the test if anything calls out."""
    def __init__(self, *a, **k):
        raise AssertionError("no outbound HTTP is allowed on a refused path")


# ══════════════════════════════════════════════════════════════════════════
# The pure rules
# ══════════════════════════════════════════════════════════════════════════

class TheGroupRowsAreClassifiedWithoutGuessing(unittest.TestCase):

    def test_no_rows_is_unlinked(self):
        self.assertEqual(wa_security.classify_group_rows([])[0],
                         wa_security.GROUP_UNLINKED)

    def test_one_complete_row_is_ok(self):
        status, row, _ = wa_security.classify_group_rows(
            [_group_row(CO_A, "proj_a")])
        self.assertEqual(status, wa_security.GROUP_OK)
        self.assertEqual(row["project_id"], "proj_a")

    def test_two_companies_is_duplicate(self):
        status, row, reason = wa_security.classify_group_rows(
            [_group_row(CO_A, "proj_a"), _group_row(CO_B, "proj_b")])
        self.assertEqual(status, wa_security.GROUP_DUPLICATE)
        self.assertIsNone(row)
        self.assertEqual(reason, "multiple_companies")

    def test_one_company_two_projects_is_duplicate(self):
        status, _, reason = wa_security.classify_group_rows(
            [_group_row(CO_A, "proj_a"), _group_row(CO_A, "proj_a2")])
        self.assertEqual(status, wa_security.GROUP_DUPLICATE)
        self.assertEqual(reason, "multiple_projects")

    def test_an_empty_company_or_project_is_invalid(self):
        for co, pr in (("", "proj_a"), (None, "proj_a"), (CO_A, ""), (CO_A, None)):
            with self.subTest(company=co, project=pr):
                self.assertEqual(
                    wa_security.classify_group_rows([_group_row(co, pr)])[0],
                    wa_security.GROUP_INVALID)


class SecurityEventsCarryIdsAndNothingElse(unittest.TestCase):

    def test_unknown_keys_are_dropped(self):
        line = wa_security.format_security_event(
            "x", company_id=CO_A, body="hello SECRET", token="tok",
            message="m", headers={"a": "b"})
        self.assertIn(CO_A, line)
        for leaked in ("hello SECRET", "tok", '"m"', "headers"):
            self.assertNotIn(leaked, line)
        self.assertIn('"timestamp"', line)


# ══════════════════════════════════════════════════════════════════════════
# Item 2 — linking is refused across companies, server-side
# ══════════════════════════════════════════════════════════════════════════

def _user(company=CO_A, role="admin", **extra):
    u = {"_id": f"u_{company}", "id": f"u_{company}", "role": role,
         "company_id": company, "account_status": "approved", "name": "U",
         "email": f"{company}@example.com"}
    u.update(extra)
    return u


def _call(db, method, path, *, user=None, json=None, sent=None, **kw):
    async def _fake_user():
        return user if user is not None else _user()

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db), \
                patch.object(server, "send_whatsapp_message",
                             _recording_send(sent if sent is not None else [])):
            client = TestClient(server.app, raise_server_exceptions=False)
            fn = getattr(client, method)
            return fn(path, json=json, **kw) if json is not None else fn(path, **kw)
    finally:
        server.app.dependency_overrides.clear()


class ACompanyCannotLinkAGroupToAnotherCompanysProject(unittest.TestCase):

    def setUp(self):
        self.db = _Db(projects=[PROJ_A, PROJ_B])

    def test_initiate_with_b_project_is_403_and_mints_no_code(self):
        with self.assertLogs(server.logger, level="WARNING") as logs:
            r = _call(self.db, "post", "/api/whatsapp/group-link/initiate",
                      json={"project_id": "proj_b"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.db.whatsapp_link_codes.inserts, [])
        joined = "\n".join(logs.output)
        self.assertIn("whatsapp_cross_company_link_attempt", joined)
        self.assertIn("proj_b", joined)
        self.assertIn("u_co_a", joined)

    def test_initiate_with_own_project_mints_a_code(self):
        r = _call(self.db, "post", "/api/whatsapp/group-link/initiate",
                  json={"project_id": "proj_a"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.db.whatsapp_link_codes.inserts), 1)

    def test_initiate_with_a_missing_project_is_the_same_403(self):
        r = _call(self.db, "post", "/api/whatsapp/group-link/initiate",
                  json={"project_id": "nope"})
        self.assertEqual(r.status_code, 403)

    def test_verify_with_a_forged_b_project_code_is_403_and_binds_nothing(self):
        """A code row naming A's company and B's project — the shape the old
        initiate could write — must not become a binding."""
        self.db.whatsapp_link_codes.rows.append({
            "_id": "c1", "code": "123456", "project_id": "proj_b",
            "company_id": CO_A, "verified": False, "group_verified": True,
            "group_id": GROUP})
        with self.assertLogs(server.logger, level="WARNING") as logs:
            r = _call(self.db, "post", "/api/whatsapp/group-link/verify",
                      json={"code": "123456", "project_id": "proj_b"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.db.whatsapp_groups.rows, [])
        self.assertIn("whatsapp_cross_company_link_attempt",
                      "\n".join(logs.output))

    def test_pending_link_to_b_project_is_403(self):
        self.db.whatsapp_pending_groups.rows.append({
            "group_id": GROUP, "company_id": CO_A, "status": "pending",
            "added_by_phone": "", "first_seen": NOW, "last_seen": NOW})
        r = _call(self.db, "post",
                  f"/api/whatsapp/pending-groups/{GROUP}/link",
                  json={"project_id": "proj_b"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.db.whatsapp_groups.rows, [])


class AGroupOwnedByOneCompanyCannotBeLinkedByAnother(unittest.TestCase):

    def test_verify_refuses_a_group_active_under_another_company(self):
        db = _Db(projects=[PROJ_A, PROJ_B],
                 whatsapp_groups=[_group_row(CO_B, "proj_b")],
                 whatsapp_link_codes=[{
                     "_id": "c1", "code": "654321", "project_id": "proj_a",
                     "company_id": CO_A, "verified": False,
                     "group_verified": True, "group_id": GROUP}])
        with self.assertLogs(server.logger, level="WARNING") as logs:
            r = _call(db, "post", "/api/whatsapp/group-link/verify",
                      json={"code": "654321", "project_id": "proj_a"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(len(db.whatsapp_groups.rows), 1)
        self.assertIn("whatsapp_duplicate_group_link_attempt",
                      "\n".join(logs.output))

    def test_pending_link_refuses_a_group_active_under_another_company(self):
        db = _Db(projects=[PROJ_A, PROJ_B],
                 whatsapp_groups=[_group_row(CO_B, "proj_b")],
                 whatsapp_pending_groups=[{
                     "group_id": GROUP, "company_id": CO_A,
                     "status": "pending", "added_by_phone": "",
                     "first_seen": NOW, "last_seen": NOW}])
        r = _call(db, "post", f"/api/whatsapp/pending-groups/{GROUP}/link",
                  json={"project_id": "proj_a"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(len(db.whatsapp_groups.rows), 1)


# ══════════════════════════════════════════════════════════════════════════
# Item 2 — every bot-side reader refuses a project its company does not own
# ══════════════════════════════════════════════════════════════════════════

_DATA_COLLECTIONS = ("checkins", "dob_logs", "daily_logs", "logbooks",
                     "material_requests", "document_page_index", "workers")


class EveryReaderRefusesBsProjectForAsGroup(unittest.TestCase):
    """Called with A's company and B's project — what a bad group record
    would hand them. Each must refuse and read none of B's collections."""

    def setUp(self):
        self.db = _Db(projects=[PROJ_A, PROJ_B], **_b_data())
        self.sent = []
        self._patches = [
            patch.object(server, "db", self.db),
            patch.object(server, "send_whatsapp_message",
                         _recording_send(self.sent)),
            patch.object(server, "ServerHttpClient", _NoNetwork),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()

    def _assert_refused(self, out):
        self.assertNotIn(SECRET, str(out))
        for name in _DATA_COLLECTIONS:
            self.assertEqual(self.db[name].reads, 0,
                             f"{name} was read for a project A does not own")

    def test_each_handler(self):
        calls = {
            "who_on_site": lambda: server._handle_who_on_site(
                "proj_b", company_id=CO_A),
            "project_info": lambda: server._handle_project_info(
                "proj_b", company_id=CO_A),
            "dob_status": lambda: server._handle_dob_status(
                "proj_b", company_id=CO_A),
            "active_permits": lambda: server._handle_active_permits(
                "proj_b", company_id=CO_A),
            "daily_log": lambda: server._handle_daily_log(
                "proj_b", None, company_id=CO_A),
            "open_items": lambda: server._handle_open_items(
                "proj_b", company_id=CO_A),
            "material_status": lambda: server._handle_material_status(
                "proj_b", company_id=CO_A),
            "start_permit_renewal": lambda: server._handle_start_permit_renewal(
                "proj_b", GROUP, HUMAN, "", company_id=CO_A),
            "start_checklist": lambda: server._handle_start_checklist(
                "proj_b", GROUP, [{"text": "x"}], HUMAN, company_id=CO_A),
        }
        for name, call in calls.items():
            with self.subTest(handler=name):
                out = _run(call())
                self.assertEqual(out, wa_security.BOT_SCOPE_REFUSAL)
                self._assert_refused(out)

    def test_material_receipt(self):
        with patch.object(server, "OPENAI_API_KEY", "sk-test"):
            out = _run(server._handle_material_receipt(
                "proj_b", "got 10 bags", HUMAN, company_id=CO_A))
        self.assertEqual(out, wa_security.BOT_SCOPE_REFUSAL)
        self._assert_refused(out)

    def test_a_handler_with_no_company_at_all_refuses(self):
        out = _run(server._handle_dob_status("proj_b"))
        self.assertEqual(out, wa_security.BOT_SCOPE_REFUSAL)
        self._assert_refused(out)

    def test_every_agent_tool_through_the_dispatcher(self):
        for t in server._AGENT_TOOLS:
            name = t["function"]["name"]
            with self.subTest(tool=name):
                out = _run(server._dispatch_agent_tool(
                    name, {"question": "x", "subject": "x", "items": [{"text": "x"}]},
                    project_id="proj_b", group_id=GROUP, company_id=CO_A,
                    sender=HUMAN))
                self.assertEqual(out, wa_security.BOT_SCOPE_REFUSAL)
                self._assert_refused(out)
        self.assertEqual(self.sent, [])

    def test_the_plan_sheet_sender_sends_nothing(self):
        _run(server._handle_plan_query("proj_b", GROUP, "S-1",
                                       user_body="show me S-1",
                                       company_id=CO_A))
        self.assertEqual(self.sent, [])
        self._assert_refused("")

    def test_the_context_block_is_empty(self):
        out = _run(server._agent_context_block(
            "proj_b", {}, "loose", company_id=CO_A))
        self.assertEqual(out, "")
        self._assert_refused(out)

    def test_the_agent_does_not_run(self):
        with patch.object(server, "OPENAI_API_KEY", "sk-test"):
            out = _run(server._run_group_agent(
                project_id="proj_b", group_id=GROUP, company_id=CO_A,
                sender=HUMAN, body="levelog who is on site", features={}))
        self.assertIsNone(out)
        self._assert_refused(out)

    def test_checklist_extraction_posts_nothing(self):
        with patch.object(server, "OPENAI_API_KEY", "sk-test"):
            out = _run(server._extract_whatsapp_checklist(
                "proj_b", GROUP, "someone: order drywall", company_id=CO_A))
        self.assertIsNone(out)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.db.whatsapp_checklists.inserts, [])

    def test_material_request_is_not_written(self):
        out = _run(server._create_material_request(
            "proj_b", CO_A, GROUP, "M1", HUMAN,
            {"items": [{"name": "drywall"}]}))
        self.assertEqual(out, {})
        self.assertEqual(self.db.material_requests.inserts, [])


class ACorrectlyBoundGroupStillNeverSeesBsRows(unittest.TestCase):
    """The positive control, and the defence-in-depth case: A's group on A's
    project gets A's data, and a B row mis-stamped with A's project id is
    still filtered out by company."""

    def test_dob_status_filters_by_company(self):
        data = _b_data()
        data["dob_logs"].append({
            "project_id": "proj_a", "company_id": CO_A,
            "record_type": "violation", "description": "A own violation",
            "detected_at": NOW})
        db = _Db(projects=[PROJ_A, PROJ_B], **data)
        with patch.object(server, "db", db):
            out = _run(server._handle_dob_status("proj_a", company_id=CO_A))
        self.assertIn("A own violation", out)
        self.assertNotIn(SECRET, out)


# ══════════════════════════════════════════════════════════════════════════
# Item 2 + 4 — the message path and the scheduled jobs
# ══════════════════════════════════════════════════════════════════════════

class _ProcessHarness:
    def _process(self, db, payload, *, agent_reply="answer"):
        sent, agent_calls = [], []

        async def _agent(**kw):
            agent_calls.append(kw)
            return agent_reply

        async def _no_detect(*a, **k):
            return None

        with patch.object(server, "db", db), \
                patch.object(server, "send_whatsapp_message",
                             _recording_send(sent)), \
                patch.object(server, "_run_group_agent", _agent), \
                patch.object(server, "_detect_material_request", _no_detect), \
                patch.object(server, "ServerHttpClient", _NoNetwork), \
                patch.dict(os.environ, {"WAAPI_DISPLAY_NUMBER": BOT_NUMBER}):
            _run(server._process_whatsapp_message(payload))
        return sent, agent_calls


class AMisBoundGroupGetsNothing(unittest.TestCase, _ProcessHarness):
    """A's group row pointing at B's project: refused at the binding."""

    def test_no_answer_no_storage_neutral_notice(self):
        db = _Db(projects=[PROJ_A, PROJ_B],
                 whatsapp_groups=[_group_row(CO_A, "proj_b")], **_b_data())
        with self.assertLogs(server.logger, level="WARNING") as logs:
            sent, agent_calls = self._process(
                db, _payload("levelog who is on site"))
        self.assertEqual(agent_calls, [])
        self.assertEqual(db.whatsapp_messages.rows, [])
        self.assertEqual(sent, [(GROUP, wa_security.GROUP_UNAVAILABLE_TEXT)])
        self.assertNotIn(SECRET, str(sent))
        self.assertIn("whatsapp_group_project_not_owned", "\n".join(logs.output))


class ADuplicateOwnedGroupIsRefused(unittest.TestCase, _ProcessHarness):

    def _db(self):
        return _Db(projects=[PROJ_A, PROJ_B],
                   whatsapp_groups=[
                       _group_row(CO_A, "proj_a", daily_summary_enabled=True,
                                  checklist_extraction_enabled=True),
                       _group_row(CO_B, "proj_b", daily_summary_enabled=True,
                                  checklist_extraction_enabled=True)],
                   **_b_data())

    def test_no_project_answer_and_one_neutral_notice(self):
        db = self._db()
        with self.assertLogs(server.logger, level="WARNING") as logs:
            sent, agent_calls = self._process(
                db, _payload("levelog what permits", msg_id="M1"))
            sent2, agent_calls2 = self._process(
                db, _payload("levelog who is on site", msg_id="M2"))
        self.assertEqual(agent_calls + agent_calls2, [])
        self.assertEqual(db.whatsapp_messages.rows, [])
        self.assertEqual(sent, [(GROUP, wa_security.GROUP_UNAVAILABLE_TEXT)])
        self.assertEqual(sent2, [], "the notice is at most once a day")
        joined = "\n".join(logs.output)
        self.assertIn("whatsapp_duplicate_group_ownership", joined)
        self.assertIn(CO_A, joined)
        self.assertIn(CO_B, joined)
        self.assertNotIn("levelog what permits", joined)

    def test_the_notice_names_nobody_and_is_bilingual(self):
        text = wa_security.GROUP_UNAVAILABLE_TEXT
        self.assertIn("isn't available", text)
        self.assertIn("no está disponible", text)
        for leaked in (CO_A, CO_B, "proj", "Project"):
            self.assertNotIn(leaked, text)

    def test_no_daily_summary(self):
        db = self._db()
        sent = []
        with patch.object(server, "db", db), \
                patch.object(server, "send_whatsapp_message",
                             _recording_send(sent)), \
                patch.object(server, "ServerHttpClient", _NoNetwork), \
                patch.object(server, "OPENAI_API_KEY", "sk-test"), \
                patch.object(server, "_current_est_time_and_date",
                             lambda: ("17:05", 1, "2026-10-05")):
            _run(server._send_whatsapp_daily_summaries())
        self.assertEqual(sent, [])

    def test_no_checklist_autopost(self):
        db = self._db()
        db.whatsapp_messages.rows.append({
            "group_id": GROUP, "company_id": CO_A, "project_id": "proj_a",
            "sender": HUMAN, "body": "order drywall", "created_at": NOW})
        calls = []

        async def _extract(*a, **k):
            calls.append((a, k))

        with patch.object(server, "db", db), \
                patch.object(server, "_extract_whatsapp_checklist", _extract), \
                patch.object(server, "_current_est_time_and_date",
                             lambda: ("16:05", 1, "2026-10-05")):
            _run(server._run_whatsapp_checklist_extractions())
        self.assertEqual(calls, [])


class ScheduledJobsCarryTheGroupsCompany(unittest.TestCase):

    def test_a_correctly_bound_group_is_extracted_under_its_own_company(self):
        db = _Db(projects=[PROJ_A, PROJ_B],
                 whatsapp_groups=[_group_row(
                     CO_A, "proj_a", checklist_extraction_enabled=True)])
        today_start, _ = server.get_today_range_est()
        db.whatsapp_messages.rows.extend([
            {"group_id": GROUP, "company_id": CO_A, "project_id": "proj_a",
             "sender": HUMAN, "body": "order drywall",
             "created_at": today_start + timedelta(minutes=5)},
            # A row stored under a previous binding of this group to B.
            {"group_id": GROUP, "company_id": CO_B, "project_id": "proj_b",
             "sender": HUMAN, "body": f"{SECRET} chatter",
             "created_at": today_start + timedelta(minutes=6)},
        ])
        calls = []

        async def _extract(project_id, group_id, text, **k):
            calls.append((project_id, group_id, text, k))

        with patch.object(server, "db", db), \
                patch.object(server, "_extract_whatsapp_checklist", _extract), \
                patch.object(server, "_current_est_time_and_date",
                             lambda: ("16:05", 1, "2026-10-05")):
            _run(server._run_whatsapp_checklist_extractions())
        self.assertEqual(len(calls), 1)
        project_id, group_id, text, kw = calls[0]
        self.assertEqual((project_id, kw.get("company_id")), ("proj_a", CO_A))
        self.assertIn("order drywall", text)
        self.assertNotIn(SECRET, text)


# ══════════════════════════════════════════════════════════════════════════
# Item 3 — the webhook authenticates before it reads anything
# ══════════════════════════════════════════════════════════════════════════

GOOD_SECRET = "s" * 48


class TheWebhookRejectsAnUnauthenticatedCaller(unittest.TestCase):

    def _post(self, url, env_secret=GOOD_SECRET):
        db = _Db()
        processed = []

        def _spy(payload):
            processed.append(payload)

            async def _noop():
                return None
            return _noop()

        env = {"WAAPI_WEBHOOK_SECRET": env_secret}
        with patch.object(server, "db", db), \
                patch.object(server, "_process_whatsapp_message", _spy), \
                patch.dict(os.environ, env):
            client = TestClient(server.app, raise_server_exceptions=False)
            r = client.post(url, json=_payload("levelog hi"))
        return r, db, processed

    def test_missing_token_is_401_and_nothing_is_stored_or_processed(self):
        with self.assertLogs(server.logger, level="WARNING") as logs:
            r, db, processed = self._post("/api/whatsapp/webhook")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(db.whatsapp_webhook_log.inserts, [])
        self.assertEqual(processed, [])
        self.assertIn("whatsapp_webhook_rejected", "\n".join(logs.output))
        self.assertIn("missing_token", "\n".join(logs.output))

    def test_wrong_token_is_401(self):
        with self.assertLogs(server.logger, level="WARNING") as logs:
            r, db, processed = self._post(
                "/api/whatsapp/webhook?token=" + "x" * 48)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(db.whatsapp_webhook_log.inserts, [])
        self.assertEqual(processed, [])
        joined = "\n".join(logs.output)
        self.assertIn("bad_token", joined)
        self.assertNotIn("x" * 48, joined)

    def test_an_unset_or_short_secret_rejects_everyone(self):
        for configured in ("", "short-secret"):
            with self.subTest(configured=configured):
                r, db, processed = self._post(
                    f"/api/whatsapp/webhook?token={configured}",
                    env_secret=configured)
                self.assertEqual(r.status_code, 401)
                self.assertEqual(processed, [])

    def test_the_right_token_is_accepted(self):
        r, db, processed = self._post(
            f"/api/whatsapp/webhook?token={GOOD_SECRET}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(db.whatsapp_webhook_log.inserts), 1)
        self.assertEqual(len(processed), 1)
        stored = str(db.whatsapp_webhook_log.inserts[0])
        self.assertNotIn(GOOD_SECRET, stored)

    def test_the_comparison_is_constant_time(self):
        import inspect
        self.assertIn("hmac.compare_digest",
                      inspect.getsource(wa_security.webhook_token_ok))


class TheTokenNeverReachesALogLine(unittest.TestCase):

    def test_the_access_log_argument_is_redacted(self):
        rec = logging.LogRecord(
            "uvicorn.access", logging.INFO, __file__, 1,
            '%s - "%s %s HTTP/%s" %d',
            ("1.2.3.4:5", "POST",
             f"/api/whatsapp/webhook?token={GOOD_SECRET}", "1.1", 200), None)
        server._WEBHOOK_TOKEN_FILTER.filter(rec)
        self.assertNotIn(GOOD_SECRET, rec.getMessage())
        self.assertIn("token=[redacted]", rec.getMessage())

    def test_the_filter_is_on_the_access_logger(self):
        self.assertIn(server._WEBHOOK_TOKEN_FILTER,
                      logging.getLogger("uvicorn.access").filters)

    def test_sentry_scrubs_the_url_and_query(self):
        event = {"request": {
            "url": f"https://x/api/whatsapp/webhook?token={GOOD_SECRET}",
            "query_string": f"token={GOOD_SECRET}", "data": "body"}}
        out = server._sentry_before_send(event, {})
        self.assertNotIn(GOOD_SECRET, str(out))

    def test_redaction_leaves_other_parameters_alone(self):
        self.assertEqual(
            wa_security.redact_query_param("/a?x=1&token=abc&y=2"),
            "/a?x=1&token=[redacted]&y=2")
        self.assertEqual(wa_security.redact_query_param("/a?mytoken=abc"),
                         "/a?mytoken=abc")


# ══════════════════════════════════════════════════════════════════════════
# Item 1 — debug endpoints answer the operator flag and nothing else
# ══════════════════════════════════════════════════════════════════════════

_DEBUG_GETS = (
    "/api/whatsapp/debug/audio-probe", "/api/whatsapp/debug/audio-diag",
    "/api/whatsapp/debug/bot-identifiers",
    "/api/whatsapp/debug/page-index?project_id=proj_a",
    "/api/whatsapp/debug/convo-state-indexes",
    "/api/whatsapp/debug/webhook-log", "/api/whatsapp/debug/waapi-config",
    "/api/whatsapp/debug/recent-messages", "/api/whatsapp/debug/pending-codes",
)


class DebugEndpointsAreOperatorOnly(unittest.TestCase):

    def test_every_debug_route_is_covered(self):
        routes = {r.path for r in server.app.routes
                  if getattr(r, "path", "").startswith("/api/whatsapp/debug/")}
        self.assertEqual(routes, {p.split("?")[0] for p in _DEBUG_GETS})

    def test_a_company_admin_gets_403_everywhere(self):
        db = _Db(projects=[PROJ_A])
        for path in _DEBUG_GETS:
            with self.subTest(path=path):
                r = _call(db, "get", path, user=_user(CO_A, "admin"))
                self.assertEqual(r.status_code, 403)
        r = _call(db, "post", "/api/debug/probe-waapi-endpoints",
                  user=_user(CO_A, "admin"),
                  json={"image_url": "https://x", "group_id": GROUP})
        self.assertEqual(r.status_code, 403)

    def test_the_plan_image_debug_send_cannot_target_another_companys_group(self):
        """It posts a drawing into whatever group id it is handed. Even the
        operator may only target a group bound to THIS project."""
        db = _Db(projects=[PROJ_A, PROJ_B],
                 whatsapp_groups=[_group_row(CO_B, "proj_b")],
                 document_page_index=[{"project_id": "proj_a",
                                       "sheet_number": "A-1"}])
        path = "/api/projects/proj_a/debug/test-plan-image-send"
        body = {"sheet_number": "A-1", "group_id": GROUP}
        for user in (_user(CO_A, "admin"),
                     _user(CO_A, "admin", is_platform_operator=True)):
            with self.subTest(operator=user.get("is_platform_operator", False)):
                sent = []
                r = _call(db, "post", path, user=user, json=body, sent=sent)
                self.assertEqual(r.status_code, 403)
                self.assertEqual(sent, [])

    def test_an_operator_email_without_the_flag_gets_403(self):
        db = _Db(projects=[PROJ_A])
        user = _user(CO_A, "admin", email="ops@levelog.com")
        with patch.object(server, "PLATFORM_OPERATOR_EMAILS",
                          frozenset({"ops@levelog.com"})):
            r = _call(db, "get", "/api/whatsapp/debug/recent-messages",
                      user=user)
        self.assertEqual(r.status_code, 403)

    def test_the_flag_gets_through(self):
        db = _Db(projects=[PROJ_A])
        user = _user(CO_A, "admin", is_platform_operator=True)
        r = _call(db, "get", "/api/whatsapp/debug/recent-messages", user=user)
        self.assertNotEqual(r.status_code, 403)


# ══════════════════════════════════════════════════════════════════════════
# Item 6 — checklist extraction defaults off; stored values are untouched
# ══════════════════════════════════════════════════════════════════════════

class ChecklistExtractionDefaultsOff(unittest.TestCase):

    def test_a_new_group_is_off(self):
        self.assertFalse(server._default_bot_config()["checklist_extraction_enabled"])

    def test_the_read_merge_keeps_a_stored_true_and_defaults_a_missing_one(self):
        on = _group_row(CO_A, "proj_a", _id="g_on", wa_group_id="on@g.us")
        on["bot_config"]["checklist_extraction_enabled"] = True
        legacy = _group_row(CO_A, "proj_a", _id="g_legacy",
                            wa_group_id="legacy@g.us")
        legacy["bot_config"].pop("checklist_extraction_enabled")
        db = _Db(projects=[PROJ_A], whatsapp_groups=[on, legacy])
        r = _call(db, "get", "/api/whatsapp/groups/proj_a")
        self.assertEqual(r.status_code, 200)
        by_id = {g["wa_group_id"]: g["bot_config"] for g in r.json()}
        self.assertTrue(by_id["on@g.us"]["checklist_extraction_enabled"])
        self.assertFalse(by_id["legacy@g.us"]["checklist_extraction_enabled"])
        # Nothing was written to the stored rows by reading them.
        self.assertTrue(db.whatsapp_groups.rows[0]["bot_config"]
                        ["checklist_extraction_enabled"])

    def test_the_job_skips_a_group_with_no_stored_value(self):
        legacy = _group_row(CO_A, "proj_a")
        legacy["bot_config"].pop("checklist_extraction_enabled")
        db = _Db(projects=[PROJ_A], whatsapp_groups=[legacy])
        calls = []

        async def _extract(*a, **k):
            calls.append(1)

        with patch.object(server, "db", db), \
                patch.object(server, "_extract_whatsapp_checklist", _extract), \
                patch.object(server, "_current_est_time_and_date",
                             lambda: ("16:05", 1, "2026-10-05")):
            _run(server._run_whatsapp_checklist_extractions())
        self.assertEqual(calls, [])

    def test_the_panel_shows_the_servers_defaults(self):
        """The panel keeps no defaults of its own (a second copy is how the
        two drifted): it renders the server's effective config, whose
        checklist default is off."""
        src = (Path(__file__).resolve().parents[2] / "frontend" / "src" /
               "components" / "whatsapp" / "GroupConfigPanel.jsx").read_text()
        self.assertNotIn("const DEFAULT_CONFIG", src)
        self.assertIn("useState(() => group?.bot_config || {})", src)
        cfg = server._effective_bot_config({})
        self.assertFalse(cfg["checklist_extraction_enabled"])
        self.assertTrue(cfg["features"]["plan_queries"])


# ══════════════════════════════════════════════════════════════════════════
# Item 7 — critical DOB alert recipients
# ══════════════════════════════════════════════════════════════════════════

class CriticalDobAlertRecipients(unittest.TestCase):

    USERS = [
        {"_id": "1", "company_id": CO_A, "role": "admin", "email": "admin@a"},
        {"_id": "2", "company_id": CO_A, "role": "pm", "email": "pm-on@a",
         "assigned_projects": ["proj_a"]},
        {"_id": "3", "company_id": CO_A, "role": "pm", "email": "pm-off@a",
         "assigned_projects": ["proj_a2"]},
        {"_id": "4", "company_id": CO_A, "role": "cp", "email": "cp@a",
         "assigned_projects": ["proj_a"]},
        {"_id": "5", "company_id": CO_A, "role": "superintendent",
         "email": "super@a", "assigned_projects": ["proj_a"]},
        {"_id": "6", "company_id": CO_A, "role": "owner", "email": "owner@a"},
        {"_id": "7", "company_id": CO_B, "role": "admin", "email": "admin@b"},
        # A PM who moved to B but still lists A's project.
        {"_id": "8", "company_id": CO_B, "role": "pm", "email": "pm@b",
         "assigned_projects": ["proj_a"]},
        {"_id": "9", "company_id": CO_A, "role": "admin", "email": "gone@a",
         "is_deleted": True},
    ]

    def test_admins_of_the_company_and_the_projects_pms_only(self):
        db = _Db(users=self.USERS)
        with patch.object(server, "db", db):
            out = _run(server._critical_dob_alert_recipients(PROJ_A))
        self.assertEqual(sorted(out), ["admin@a", "pm-on@a"])

    def test_the_send_goes_to_exactly_those(self):
        db = _Db(users=self.USERS)
        sent_to = []

        async def _send(_db, **kw):
            sent_to.append(kw["recipient"])
            return {"status": "sent"}

        with patch.object(server, "db", db), \
                patch.object(server, "RESEND_API_KEY", "re_test"), \
                patch("lib.notifications.send_notification", _send):
            _run(server._send_critical_dob_alert(
                PROJ_A, {"record_type": "violation", "raw_dob_id": "v1"}))
        self.assertEqual(sorted(sent_to), ["admin@a", "pm-on@a"])

    def test_the_retired_role_is_gone_from_the_query(self):
        """Code only — the docstring names the old query on purpose."""
        import ast
        import inspect
        import textwrap
        fn = ast.parse(textwrap.dedent(
            inspect.getsource(server._critical_dob_alert_recipients))).body[0]
        fn.body = fn.body[1:]  # drop the docstring
        code = ast.unparse(fn)
        self.assertNotIn("'owner'", code)
        self.assertIn("COMPANY_ADMIN_ROLES", code)


# ══════════════════════════════════════════════════════════════════════════
# Item 8 — the bot does not answer itself
# ══════════════════════════════════════════════════════════════════════════

class TheBotDoesNotAnswerItsOwnMessages(unittest.TestCase, _ProcessHarness):

    def _db(self):
        return _Db(projects=[PROJ_A],
                   whatsapp_groups=[_group_row(CO_A, "proj_a")])

    def test_a_from_me_echo_is_dropped_before_anything(self):
        db = self._db()
        sent, agent_calls = self._process(
            db, _payload("Levelog here. Just ask.", from_me=True,
                         event="message_create"))
        self.assertEqual((sent, agent_calls, db.whatsapp_messages.rows),
                         ([], [], []))

    def test_an_echo_without_the_flag_is_matched_on_the_bots_number(self):
        db = self._db()
        sent, agent_calls = self._process(
            db, _payload("I'm here — say \"levelog\"",
                         author=f"{BOT_NUMBER}@c.us"))
        self.assertEqual((sent, agent_calls, db.whatsapp_messages.rows),
                         ([], [], []))

    def test_a_reply_echoed_back_does_not_start_a_loop(self):
        """The human asks once; the bot's answer comes back as a
        message_create echo carrying the word that addresses it. One answer,
        not two."""
        db = self._db()
        sent, agent_calls = self._process(
            db, _payload("levelog who is on site", msg_id="H1"),
            agent_reply="Levelog: 3 on site")
        self.assertEqual(len(agent_calls), 1)
        self.assertEqual(len(sent), 1)
        echo = _payload(sent[0][1], from_me=True, msg_id="B1",
                        event="message_create",
                        author=f"{BOT_NUMBER}@c.us")
        sent2, agent_calls2 = self._process(db, echo)
        self.assertEqual((sent2, agent_calls2), ([], []))

    def test_the_parser_reports_from_me(self):
        self.assertTrue(server.parse_inbound_message(
            _payload("x", from_me=True))["from_me"])
        self.assertFalse(server.parse_inbound_message(
            _payload("x"))["from_me"])


# ══════════════════════════════════════════════════════════════════════════
# The DM path: one number in two companies reads nothing
# ══════════════════════════════════════════════════════════════════════════

class ADirectMessageFromANumberInTwoCompaniesReadsNothing(unittest.TestCase):

    def test_no_reply_no_classification(self):
        db = _Db(projects=[PROJ_A, PROJ_B], whatsapp_contacts=[
            {"company_id": CO_A, "phone": HUMAN, "user_id": "u_a"},
            {"company_id": CO_B, "phone": f"+{HUMAN}", "user_id": "u_b"}],
            **_b_data())
        sent, classified = [], []

        async def _classify(body):
            classified.append(body)
            return "dob_status"

        dm = {"event": "message", "data": {"message": {
            "id": {"id": "D1", "fromMe": False}, "from": f"{HUMAN}@c.us",
            "body": "dob status", "type": "chat"}}}
        with patch.object(server, "db", db), \
                patch.object(server, "send_whatsapp_message",
                             _recording_send(sent)), \
                patch.object(server, "classify_intent", _classify):
            _run(server._process_whatsapp_message(dm))
        # No opt-in for this chat: the one line every non-eligible sender
        # gets (Levelog Assistant in a DM), and nothing read or classified.
        from lib import wa_assistant
        self.assertEqual(sent, [(f"{HUMAN}@c.us", wa_assistant.NOT_FOR_YOU_TEXT)])
        self.assertEqual(classified, [])
        self.assertNotIn(SECRET, str(sent))

    def test_a_contact_whose_company_is_not_its_users_reads_nothing(self):
        db = _Db(projects=[PROJ_A, PROJ_B],
                 users=[{"_id": "u_b", "company_id": CO_B,
                         "assigned_projects": ["proj_b"]}])
        with patch.object(server, "db", db):
            out = _run(server._find_project_for_contact(
                {"company_id": CO_A, "user_id": "u_b"}))
        self.assertIsNone(out)

    def test_an_assigned_project_of_another_company_is_skipped(self):
        db = _Db(projects=[PROJ_A, PROJ_B],
                 users=[{"_id": "u_a", "company_id": CO_A,
                         "assigned_projects": ["proj_b", "proj_a"]}])
        with patch.object(server, "db", db):
            out = _run(server._find_project_for_contact(
                {"company_id": CO_A, "user_id": "u_a"}))
        self.assertEqual(out, (CO_A, "proj_a"))


if __name__ == "__main__":
    unittest.main()
