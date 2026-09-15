"""Connecting a WhatsApp group to a project, and the tenant wall around it.

WHAT THE OLD FLOW COST. Linking a group meant knowing that a six-digit code
flow existed, opening the app, generating a code, pasting it into the chat, and
confirming — four steps that begin with knowing about step one. A group nobody
took through those steps got a bare `return` on every message: the bot sat in
the chat, silent, forever, and nothing recorded that it was there.

WHAT MATTERS MOST HERE IS THE TENANT WALL. Getting this wrong does not produce
a 500. It produces one customer's daily log, roster and permit data appearing in
another customer's group chat, with nothing anywhere going red. So the cross-
tenant classes below are the point of the file, and the happy path is the part
that could be re-derived.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

PROJ_A = {"_id": "proj_a", "company_id": "co_a", "name": "588 Thomas S Boyland",
          "address": "588 Thomas S Boyland St, Brooklyn NY"}
PROJ_B = {"_id": "proj_b", "company_id": "co_b", "name": "8 Walworth",
          "address": "8 Walworth St, Brooklyn NY"}


def _matches(doc, query):
    """Enough of Mongo's matcher for these fixtures: equality, $in, $ne, $or."""
    for key, cond in (query or {}).items():
        if key == "$or":
            if not any(_matches(doc, c) for c in cond):
                return False
            continue
        val = doc.get(key)
        if isinstance(cond, dict):
            if "$in" in cond and val not in cond["$in"]:
                return False
            if "$ne" in cond and val == cond["$ne"]:
                return False
        elif val != cond:
            return False
    return True


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return list(self.rows)


class _Coll:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.updates = []

    async def find_one(self, query=None, projection=None, *a, **k):
        for r in self.rows:
            if _matches(r, query):
                return dict(r)
        return None

    def find(self, query=None, projection=None, *a, **k):
        return _Cursor([dict(r) for r in self.rows if _matches(r, query)])

    async def update_one(self, query, update, upsert=False):
        self.updates.append((query, update, upsert))
        target = None
        for r in self.rows:
            if _matches(r, query):
                target = r
                break
        if target is None and upsert:
            target = {}
            target.update({k: v for k, v in (query or {}).items()
                           if not isinstance(v, dict)})
            target.update(update.get("$setOnInsert", {}))
            self.rows.append(target)
        if target is not None:
            target.update(update.get("$set", {}))

            class _R:
                modified_count = 1
            return _R()

        class _R0:
            modified_count = 0
        return _R0()

    async def delete_one(self, query):
        self.rows = [r for r in self.rows if not _matches(r, query)]

        class _R:
            deleted_count = 1
        return _R()


class _Db:
    def __init__(self, pending=None, groups=None, projects=None, contacts=None):
        # Set through __dict__ because __getattr__ below answers for every
        # name that is not already an attribute, and a collection handle is a
        # very convincing stand-in for a list of sent messages.
        self.__dict__["sent"] = []
        self.__dict__["_c"] = {
            server.PENDING_GROUPS: _Coll(pending),
            "whatsapp_groups": _Coll(groups),
            "projects": _Coll(projects if projects is not None
                              else [PROJ_A, PROJ_B]),
            "whatsapp_contacts": _Coll(contacts),
            "whatsapp_conversation_state": _Coll(),
        }

    def __getitem__(self, name):
        return self._c.setdefault(name, _Coll())

    def __getattr__(self, name):
        # Motor exposes collections as attributes, so db.whatsapp_groups and
        # db["whatsapp_groups"] are one thing. Dunder and private names are
        # NOT collections and must raise, or unittest's own introspection
        # walks away with a _Coll.
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]


def _user(role="admin", company="co_a", phone="+15165494475"):
    return {"_id": "u1", "id": "u1", "role": role, "company_id": company,
            "account_status": "approved", "name": "A", "phone": phone}


def _call(db, method, path, *, user=None, json=None):
    async def _fake_user():
        return user if user is not None else _user()

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db), \
             patch.object(server, "send_whatsapp_message",
                          new=_recording_send(db)):
            client = TestClient(server.app)
            fn = getattr(client, method)
            # TestClient.get takes no json kwarg, so it is only passed where
            # there is a body to pass.
            return fn(path, json=json) if json is not None else fn(path)
    finally:
        server.app.dependency_overrides.clear()


def _recording_send(db):
    async def _send(chat_id, message):
        db.__dict__["sent"].append((chat_id, message))
        return {"ok": True}
    return _send


def _sent(db):
    return db.__dict__["sent"]


# ══════════════════════════════════════════════════════════════════
# The tenant wall
# ══════════════════════════════════════════════════════════════════

class ACompanyCannotReachAnotherCompanysProject(unittest.TestCase):

    def setUp(self):
        self.db = _Db(pending=[{
            "group_id": "g1@g.us", "group_name": "Boyland - Framing",
            "company_id": "co_a", "status": "pending", "added_by_phone": "",
            "first_seen": NOW, "last_seen": NOW,
        }])

    def test_linking_to_another_companys_project_is_refused(self):
        """The project id is the CLIENT'S input and the whole tenancy
        decision rests on it, so it is checked against the database rather
        than against anything the client sent alongside it."""
        r = _call(self.db, "post", "/api/whatsapp/pending-groups/g1@g.us/link",
                  json={"project_id": "proj_b"})
        self.assertEqual(r.status_code, 403)

    def test_nothing_was_written_when_it_was_refused(self):
        _call(self.db, "post", "/api/whatsapp/pending-groups/g1@g.us/link",
              json={"project_id": "proj_b"})
        self.assertEqual(self.db["whatsapp_groups"].rows, [])
        self.assertEqual(_sent(self.db), [])

    def test_its_own_project_links_fine(self):
        r = _call(self.db, "post", "/api/whatsapp/pending-groups/g1@g.us/link",
                  json={"project_id": "proj_a"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["project_id"], "proj_a")


class ACompanyCannotSeeAnothersPendingGroups(unittest.TestCase):

    def setUp(self):
        self.db = _Db(pending=[
            {"group_id": "ga@g.us", "group_name": "Boyland", "company_id": "co_a",
             "status": "pending", "added_by_phone": "", "first_seen": NOW,
             "last_seen": NOW},
            {"group_id": "gb@g.us", "group_name": "Walworth", "company_id": "co_b",
             "status": "pending", "added_by_phone": "", "first_seen": NOW,
             "last_seen": NOW},
        ])

    def test_the_list_carries_only_the_callers_company(self):
        body = _call(self.db, "get", "/api/whatsapp/pending-groups").json()
        ids = [p["group_id"] for p in body["pending"]]
        self.assertEqual(ids, ["ga@g.us"])

    def test_the_project_list_is_also_scoped(self):
        body = _call(self.db, "get", "/api/whatsapp/pending-groups").json()
        self.assertEqual([p["id"] for p in body["projects"]], ["proj_a"])

    def test_a_group_it_cannot_see_cannot_be_linked_by_id(self):
        """Guessing another tenant's group id is not a way in — visibility is
        re-checked on the write, not only on the read."""
        r = _call(self.db, "post", "/api/whatsapp/pending-groups/gb@g.us/link",
                  json={"project_id": "proj_a"})
        self.assertEqual(r.status_code, 403)

    def test_a_group_it_cannot_see_cannot_be_ignored_either(self):
        r = _call(self.db, "post", "/api/whatsapp/pending-groups/gb@g.us/ignore")
        self.assertEqual(r.status_code, 404)


class AnUnresolvedGroupBelongsToWhoeverAddedTheBot(unittest.TestCase):
    """A group whose adder we do not recognise has no company. Invisible to
    everyone it would sit there forever; visible to everyone it would leak
    group names across tenants. It is visible to the person who added it."""

    def setUp(self):
        self.db = _Db(pending=[{
            "group_id": "gu@g.us", "group_name": "Boyland", "company_id": None,
            "status": "pending", "added_by_phone": "15165494475",
            "first_seen": NOW, "last_seen": NOW,
        }])

    def test_the_adder_sees_it(self):
        body = _call(self.db, "get", "/api/whatsapp/pending-groups",
                     user=_user(phone="+15165494475")).json()
        self.assertEqual([p["group_id"] for p in body["pending"]], ["gu@g.us"])

    def test_a_colleague_in_the_same_company_does_not(self):
        body = _call(self.db, "get", "/api/whatsapp/pending-groups",
                     user=_user(phone="+17185550000")).json()
        self.assertEqual(body["pending"], [])

    def test_the_phone_is_matched_across_stored_formats(self):
        """Contacts are written as +1XXXXXXXXXX by five of six writers and as
        bare digits by the sixth. The adder's phone comes off a JID with no
        plus, so both spellings have to resolve."""
        body = _call(self.db, "get", "/api/whatsapp/pending-groups",
                     user=_user(phone="(516) 549-4475")).json()
        self.assertEqual([p["group_id"] for p in body["pending"]], ["gu@g.us"])


class OnlyAnOwnerAdminOrCpMayConnectAGroup(unittest.TestCase):

    def setUp(self):
        self.db = _Db(pending=[{
            "group_id": "g1@g.us", "group_name": "Boyland", "company_id": "co_a",
            "status": "pending", "added_by_phone": "", "first_seen": NOW,
            "last_seen": NOW,
        }])

    def test_a_worker_is_refused_everywhere(self):
        u = _user(role="worker")
        for method, path, body in (
            ("get", "/api/whatsapp/pending-groups", None),
            ("post", "/api/whatsapp/pending-groups/g1@g.us/link",
             {"project_id": "proj_a"}),
            ("post", "/api/whatsapp/pending-groups/g1@g.us/ignore", None),
        ):
            with self.subTest(path=path):
                r = _call(self.db, method, path, user=u, json=body)
                self.assertEqual(r.status_code, 403)

    def test_each_permitted_role_is_allowed(self):
        for role in ("owner", "admin", "cp"):
            with self.subTest(role=role):
                r = _call(self.db, "get", "/api/whatsapp/pending-groups",
                          user=_user(role=role))
                self.assertEqual(r.status_code, 200)

    def test_a_caller_with_no_company_is_refused_rather_than_shown_nothing(self):
        """An empty list would read as "no groups". There are groups; this
        caller has no company to scope them to, and saying so is the honest
        answer."""
        r = _call(self.db, "get", "/api/whatsapp/pending-groups",
                  user=_user(company=None))
        self.assertEqual(r.status_code, 400)


# ══════════════════════════════════════════════════════════════════
# Linking
# ══════════════════════════════════════════════════════════════════

class ConnectingAGroup(unittest.TestCase):

    def setUp(self):
        self.db = _Db(pending=[{
            "group_id": "g1@g.us", "group_name": "Boyland - Framing",
            "company_id": "co_a", "status": "pending", "added_by_phone": "",
            "first_seen": NOW, "last_seen": NOW,
        }])
        self.r = _call(self.db, "post",
                       "/api/whatsapp/pending-groups/g1@g.us/link",
                       json={"project_id": "proj_a"})

    def test_the_group_row_is_written_with_default_config(self):
        rows = self.db["whatsapp_groups"].rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["project_id"], "proj_a")
        self.assertTrue(rows[0]["active"])

    def test_the_group_name_is_carried_onto_the_linked_row(self):
        """whatsapp_groups.group_name is read by two API responses and was
        written by nothing before this — always null, everywhere."""
        self.assertEqual(self.db["whatsapp_groups"].rows[0]["group_name"],
                         "Boyland - Framing")

    def test_the_pending_row_is_marked_linked_not_deleted(self):
        row = self.db[server.PENDING_GROUPS].rows[0]
        self.assertEqual(row["status"], "linked")
        self.assertEqual(row["linked_project_id"], "proj_a")

    def test_the_bot_announces_itself_in_the_group(self):
        """Not only manners. WhatsApp routes @mentions by LID, and this server
        learns its own LID only by observing a webhook for a message it sent.
        Until the bot has spoken, a native @Levelog matches nothing."""
        self.assertEqual(len(_sent(self.db)), 1)
        chat, msg = _sent(self.db)[0]
        self.assertEqual(chat, "g1@g.us")
        self.assertIn("588 Thomas S Boyland St", msg)

    def test_the_confirmation_is_bilingual(self):
        _chat, msg = _sent(self.db)[0]
        self.assertIn("Connected to", msg)
        self.assertIn("Conectado a", msg)


class RelinkingClearsTheConversation(unittest.TestCase):
    """whatsapp_conversation_state is keyed by group_id alone and holds a
    half-finished checklist and its candidate assignees. Moved to another
    project that draft names people from the old job."""

    def _db(self, old_project):
        return _Db(
            pending=[{"group_id": "g1@g.us", "group_name": "Boyland",
                      "company_id": "co_a", "status": "pending",
                      "added_by_phone": "", "first_seen": NOW, "last_seen": NOW}],
            groups=[{"company_id": "co_a", "wa_group_id": "g1@g.us",
                     "project_id": old_project, "active": True}],
            projects=[PROJ_A, dict(PROJ_B, company_id="co_a")],
        )

    def test_moving_to_a_different_project_deletes_the_draft(self):
        db = self._db("proj_b")
        # `kind` is part of the row now — see
        # test_conversation_state_holds_more_than_one_row.py for why a bare
        # group_id filter stopped being unambiguous.
        db["whatsapp_conversation_state"].rows.append(
            {"kind": "checklist", "group_id": "g1@g.us",
             "awaiting": "checklist_assignment"})
        _call(db, "post", "/api/whatsapp/pending-groups/g1@g.us/link",
              json={"project_id": "proj_a"})
        self.assertEqual(db["whatsapp_conversation_state"].rows, [])

    def test_relinking_to_the_same_project_leaves_it_alone(self):
        db = self._db("proj_a")
        # `kind` is part of the row now — see
        # test_conversation_state_holds_more_than_one_row.py for why a bare
        # group_id filter stopped being unambiguous.
        db["whatsapp_conversation_state"].rows.append(
            {"kind": "checklist", "group_id": "g1@g.us",
             "awaiting": "checklist_assignment"})
        _call(db, "post", "/api/whatsapp/pending-groups/g1@g.us/link",
              json={"project_id": "proj_a"})
        self.assertEqual(len(db["whatsapp_conversation_state"].rows), 1)


class Ignoring(unittest.TestCase):

    def setUp(self):
        self.db = _Db(pending=[{
            "group_id": "g1@g.us", "group_name": "Boyland", "company_id": "co_a",
            "status": "pending", "added_by_phone": "", "first_seen": NOW,
            "last_seen": NOW,
        }])

    def test_the_row_is_marked_not_removed(self):
        """Deleting it would put the group straight back on the list on its
        next message, which is the opposite of what the person asked for."""
        r = _call(self.db, "post", "/api/whatsapp/pending-groups/g1@g.us/ignore")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.db[server.PENDING_GROUPS].rows), 1)
        self.assertEqual(self.db[server.PENDING_GROUPS].rows[0]["status"],
                         "ignored")

    def test_an_ignored_group_leaves_the_list(self):
        _call(self.db, "post", "/api/whatsapp/pending-groups/g1@g.us/ignore")
        body = _call(self.db, "get", "/api/whatsapp/pending-groups").json()
        self.assertEqual(body["pending"], [])


# ══════════════════════════════════════════════════════════════════
# The suggestion, and the in-chat link
# ══════════════════════════════════════════════════════════════════

class TheListPreFillsWhatItIsSureOf(unittest.TestCase):

    def _db(self, group_name):
        return _Db(pending=[{
            "group_id": "g1@g.us", "group_name": group_name,
            "company_id": "co_a", "status": "pending", "added_by_phone": "",
            "first_seen": NOW, "last_seen": NOW,
        }])

    def test_a_clear_name_is_pre_filled(self):
        body = _call(self._db("Boyland - Framing"), "get",
                     "/api/whatsapp/pending-groups").json()
        self.assertEqual(body["pending"][0]["suggested_project_id"], "proj_a")

    def test_an_unclear_name_leaves_the_dropdown_empty(self):
        body = _call(self._db("Site chat 2"), "get",
                     "/api/whatsapp/pending-groups").json()
        self.assertIsNone(body["pending"][0]["suggested_project_id"])

    def test_a_suggestion_never_links_anything_by_itself(self):
        db = self._db("Boyland - Framing")
        _call(db, "get", "/api/whatsapp/pending-groups")
        self.assertEqual(db["whatsapp_groups"].rows, [])
        self.assertEqual(db[server.PENDING_GROUPS].rows[0]["status"], "pending")

    def test_the_suggestion_cannot_name_another_companys_project(self):
        """The scoring only ever sees this company's projects — the tenant
        scope is resolved by the route, not inside the matcher."""
        db = _Db(pending=[{
            "group_id": "g1@g.us", "group_name": "Walworth crew",
            "company_id": "co_a", "status": "pending", "added_by_phone": "",
            "first_seen": NOW, "last_seen": NOW,
        }])
        body = _call(db, "get", "/api/whatsapp/pending-groups").json()
        self.assertIsNone(body["pending"][0]["suggested_project_id"])


class TheInChatLinkNamesAGroupAndGrantsNothing(unittest.TestCase):

    def setUp(self):
        self.db = _Db(pending=[{
            "group_id": "g1@g.us", "group_name": "Boyland - Framing",
            "company_id": "co_a", "status": "pending", "added_by_phone": "",
            "first_seen": NOW, "last_seen": NOW,
        }])
        self.token = server._mint_group_link_token("g1@g.us")

    def test_a_valid_token_shows_that_one_group(self):
        r = _call(self.db, "get",
                  f"/api/whatsapp/pending-groups/by-token?t={self.token}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["pending"][0]["group_id"], "g1@g.us")

    def test_the_url_carries_no_raw_group_id(self):
        """A @g.us id is an identifier for a real conversation; it should not
        land in browser history or a forwarded link."""
        self.assertNotIn("g.us", self.token)

    def test_a_login_token_is_not_a_group_link(self):
        """Every token this app issues is signed with the same secret, so the
        `kind` claim is what stops one being spent as the other."""
        other = server.create_token("u1", "a@b.c", "admin")
        r = _call(self.db, "get",
                  f"/api/whatsapp/pending-groups/by-token?t={other}")
        self.assertEqual(r.status_code, 404)

    def test_it_still_requires_the_role(self):
        r = _call(self.db, "get",
                  f"/api/whatsapp/pending-groups/by-token?t={self.token}",
                  user=_user(role="worker"))
        self.assertEqual(r.status_code, 403)

    def test_it_still_respects_the_tenant_wall(self):
        """The token names a group. It does not hand over a group belonging to
        somebody else."""
        r = _call(self.db, "get",
                  f"/api/whatsapp/pending-groups/by-token?t={self.token}",
                  user=_user(company="co_b"))
        self.assertEqual(r.status_code, 404)

    def test_an_expired_and_a_forbidden_token_are_indistinguishable(self):
        """Different codes would confirm that a group exists to somebody who
        may not be allowed to know it."""
        a = _call(self.db, "get", "/api/whatsapp/pending-groups/by-token?t=junk")
        b = _call(self.db, "get",
                  f"/api/whatsapp/pending-groups/by-token?t={self.token}",
                  user=_user(company="co_b"))
        self.assertEqual(a.status_code, b.status_code)


# ══════════════════════════════════════════════════════════════════
# The legacy path is kept, per spec
# ══════════════════════════════════════════════════════════════════

class TheSixDigitFlowStillExists(unittest.TestCase):

    def test_both_legacy_routes_are_still_registered(self):
        paths = {r.path for r in server.app.routes if hasattr(r, "path")}
        self.assertIn("/api/whatsapp/group-link/initiate", paths)
        self.assertIn("/api/whatsapp/group-link/verify", paths)

    def test_the_in_chat_code_check_still_runs_before_the_pending_fallback(self):
        """A code pasted into a PENDING group must still link it. If the
        pending fallback returned first, the legacy path would be dead in
        exactly the groups it is needed in."""
        import inspect
        src = inspect.getsource(server._process_whatsapp_message)
        self.assertLess(src.index("whatsapp_link_codes"),
                        src.index("THE PRIMARY FRONT DOOR"))


if __name__ == "__main__":
    unittest.main()
