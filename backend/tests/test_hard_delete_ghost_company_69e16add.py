"""The ghost-company hard-delete script: its guards, its selectors, and a full
dry run and execute against an in-memory database.

It is never run against a real database here. What is tested is what decides
whether it may run, what it would touch, and that an execute leaves nothing
of the company behind and nothing of anyone else's missing."""

import copy
import os
import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from scripts import hard_delete_ghost_company_69e16add as h  # noqa: E402
from tests._fake_mongo import matches  # noqa: E402

CO = h.TARGET_COMPANY
P_LAF, P_176, P_BAILEY, P_CONCORD, P_DUPE = h.TARGET_PROJECTS
OTHER_CO = "aaaaaaaaaaaaaaaaaaaaaaaa"
OTHER_P = "bbbbbbbbbbbbbbbbbbbbbbbb"
OTHER_GROUP = "120363000000000999@g.us"
SECOND_GROUP = "120363000000000555@g.us"     # another group of the ghost company
PENDING_GROUP = "120363000000000444@g.us"    # pending, recorded for the company


# ── a synchronous in-memory Mongo, enough for this script ──────────────────

class _Coll:
    def __init__(self):
        self.rows = []

    def find(self, flt=None, projection=None):
        return [copy.deepcopy(r) for r in self.rows if matches(r, flt or {})]

    def count_documents(self, flt):
        return sum(1 for r in self.rows if matches(r, flt or {}))

    def insert_one(self, doc):
        self.rows.append(copy.deepcopy(doc))

    def delete_many(self, flt):
        self.rows = [r for r in self.rows if not matches(r, flt or {})]

    def update_many(self, flt, update):
        for r in self.rows:
            if not matches(r, flt or {}):
                continue
            for field, cond in (update.get("$pull") or {}).items():
                vals = r.get(field) or []
                if isinstance(cond, dict) and "$in" in cond:
                    r[field] = [v for v in vals if v not in cond["$in"]]
                else:
                    r[field] = [v for v in vals
                                if not (isinstance(v, dict) and matches(v, cond))]


class _Db:
    def __init__(self):
        self._c = {}

    def __getitem__(self, name):
        return self._c.setdefault(name, _Coll())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def list_collection_names(self):
        return [n for n, c in self._c.items() if c.rows]


def _world():
    """The ghost company as the operator described it, plus a real company
    whose rows must all survive."""
    db = _Db()
    db.projects.rows += [
        {"_id": P_LAF, "company_id": CO, "name": "638 Lafayette Avenue"},
        {"_id": P_176, "company_id": CO, "name": "852 E 176th St", "is_deleted": True},
        {"_id": P_BAILEY, "company_id": CO, "name": "3846 Bailey Ave", "is_deleted": True},
        {"_id": P_CONCORD, "company_id": CO, "name": "533 Concord Ave", "is_deleted": True},
        {"_id": P_DUPE, "name": "638 Lafayette Avenue"},
        {"_id": OTHER_P, "company_id": OTHER_CO, "name": "Real job"},
    ]
    db.users.rows += [
        {"_id": "u_gone", "company_id": CO, "is_deleted": True, "email": "x@x"},
        {"_id": "u_other", "company_id": OTHER_CO, "email": "o@o",
         "assigned_projects": [OTHER_P, P_LAF]},
    ]
    db.whatsapp_groups.rows += [
        {"_id": h.TARGET_GROUP_DOC, "wa_group_id": h.TARGET_WA_GROUP,
         "company_id": CO, "project_id": P_LAF},
        {"_id": "g2", "wa_group_id": SECOND_GROUP, "company_id": CO,
         "project_id": P_BAILEY},
        {"_id": "g_other", "wa_group_id": OTHER_GROUP, "company_id": OTHER_CO,
         "project_id": OTHER_P},
    ]
    db.whatsapp_pending_groups.rows += [
        {"_id": "pg1", "group_id": PENDING_GROUP, "company_id": CO}]
    db.whatsapp_messages.rows += [
        {"_id": "m1", "group_id": h.TARGET_WA_GROUP, "body": "x"},
        {"_id": "m2", "group_id": SECOND_GROUP, "body": "x"},
        {"_id": "m3", "group_id": PENDING_GROUP, "body": "x"},
        {"_id": "m_other", "group_id": OTHER_GROUP, "body": "x"},
    ]
    db.checkins.rows += [
        {"_id": "c1", "project_id": P_176, "company_id": CO},
        {"_id": "c2", "project_id": P_DUPE},
        {"_id": "c_other", "project_id": OTHER_P, "company_id": OTHER_CO},
    ]
    db.project_files.rows += [
        {"_id": "f1", "project_id": P_LAF, "r2_key": "co/laf/plan.pdf"},
        {"_id": "f_other", "project_id": OTHER_P, "r2_key": "co/other/plan.pdf"},
    ]
    db.document_page_index.rows += [{"_id": "d1", "file_id": "f1"}]
    db.logbooks.rows += [{"_id": "lb1", "project_id": P_CONCORD,
                          "status": "submitted"}]
    db.logbook_thumbnails.rows += [{"_id": "t1", "logbook_id": "lb1",
                                    "thumb_r2_key": "thumbs/lb1.jpg"}]
    db.system_config.rows += [
        {"_id": "s1", "key": f"dob_sync_last:{P_LAF}"},
        {"_id": "s_other", "key": f"dob_sync_last:{OTHER_P}"},
    ]
    db.workers.rows += [{"_id": "w1", "safety_orientations": [
        {"project_id": P_LAF}, {"project_id": OTHER_P}]}]
    db.audit_logs.rows += [{"_id": "a1", "resource_id": P_LAF}]
    return db


def _args(**kw):
    base = dict(bot_not_in_group=[], waapi_leave_action="leave-group",
                i_know=True, reason="test", session="test-session")
    base.update(kw)
    return Namespace(**base)


def _run(db, write, args=None, leave_ok=True, r2_failed=()):
    left = []

    def leave(action, chat_id):
        left.append(chat_id)
        return leave_ok, "http 200" if leave_ok else "http 404"

    with patch.object(h, "_leave_group", leave), \
            patch.object(h, "_r2_delete", lambda keys: list(r2_failed)), \
            patch.object(h, "_r2_listing", lambda prefixes: {}):
        code = h.run(db, write, args or _args())
    return code, left


# ── the invocation guard ───────────────────────────────────────────────────

class TheExecuteGuard(unittest.TestCase):

    def test_a_dry_run_needs_no_ids(self):
        self.assertIsNone(h.validate_execute_args(False, []))

    def test_execute_needs_all_five_ids_exactly(self):
        five = list(h.TARGET_PROJECTS)
        self.assertEqual(len(five), 5)
        self.assertIsNone(h.validate_execute_args(True, five))
        self.assertIsNone(h.validate_execute_args(True, list(reversed(five))))
        self.assertIsNotNone(h.validate_execute_args(True, []))
        self.assertIsNotNone(h.validate_execute_args(True, five[:4]))
        self.assertIsNotNone(h.validate_execute_args(True, five[:2]))
        self.assertIsNotNone(h.validate_execute_args(
            True, five + ["69f90c3209947c4967c8074f"]))

    def test_the_targets_are_the_operators_list(self):
        self.assertEqual(set(h.TARGET_PROJECTS), {
            "69e16adf079abf2b78ee08d4", "69e16adf079abf2b78ee08d6",
            "69e16ade079abf2b78ee08d0", "69e16ade079abf2b78ee08d2",
            "69f8fb5e9429c5be4b2fcb66"})
        self.assertEqual(h.TARGET_COMPANY, "69e16add079abf2b78ee08ce")

    def test_the_legacy_flag_alone_is_refused(self):
        argv = ["--execute"]
        for p in h.TARGET_PROJECTS:
            argv += ["--project", p]
        with self.assertRaises(SystemExit) as e:
            h.main(argv)
        self.assertEqual(e.exception.code, 2)

    def test_execute_without_mongo_is_a_bad_invocation(self):
        argv = ["--execute"]
        for p in h.TARGET_PROJECTS:
            argv += ["--project", p]
        argv += ["--i-know", "--reason", "r", "--session", "s"]
        env = dict(os.environ)
        os.environ.pop("MONGO_URL", None)
        try:
            code = h.main(argv)
        finally:
            os.environ.clear()
            os.environ.update(env)
        self.assertEqual(code, h.BAD)


# ── what it would touch ────────────────────────────────────────────────────

class WhatItWouldTouch(unittest.TestCase):

    def _sel(self, names=("checkins", "audit_logs", "users", "projects")):
        return h.build_selectors(
            project_ids=h.TARGET_PROJECTS, company_id=h.TARGET_COMPANY,
            file_ids=["f1"], logbook_ids=["l1"], renewal_ids=["r1"],
            wa_groups=[h.TARGET_WA_GROUP, SECOND_GROUP],
            group_doc_ids=[h.TARGET_GROUP_DOC, "g2"],
            collection_names=names)

    def test_audit_logs_are_never_deleted(self):
        self.assertNotIn("audit_logs", {c for c, _, _ in self._sel()})

    def test_every_collection_gets_the_project_or_company_filter(self):
        generic = [f for c, f, why in self._sel() if c == "checkins"]
        self.assertEqual(len(generic), 1)
        ors = generic[0]["$or"]
        self.assertIn("project_id", ors[0])
        self.assertIn("company_id", ors[1])

    def test_ids_match_as_string_and_objectid(self):
        vals = h.any_id("project_id", [h.TARGET_PROJECTS[0]])["project_id"]["$in"]
        self.assertEqual(len(vals), 2)
        self.assertEqual(str(vals[1]), h.TARGET_PROJECTS[0])

    def test_the_rows_the_app_cascade_misses_are_covered(self):
        colls = {c for c, _, _ in self._sel()}
        for c in ("plan_records", "plan_index_jobs", "document_page_index",
                  "document_page_chunks", "logbook_thumbnails",
                  "report_number_counters", "system_config",
                  "whatsapp_pending_groups", "whatsapp_send_log",
                  "notification_log", "digest_queue", "filing_jobs"):
            self.assertIn(c, colls)

    def test_every_group_is_in_the_group_keyed_selectors(self):
        msgs = [f for c, f, _ in self._sel() if c == "whatsapp_messages"][0]
        self.assertEqual(set(msgs["group_id"]["$in"]),
                         {h.TARGET_WA_GROUP, SECOND_GROUP})

    def test_r2_keys_are_found_anywhere_in_a_row(self):
        keys = set()
        h.collect_r2_keys({"r2_key": "a/b.pdf", "data": {"activities": [
            {"photos": [{"original_r2_key": "lp/1.jpg", "thumb_r2_key": ""}]}]},
            "page_jpeg_r2_key": "plans/x/1.jpg", "other": "c"}, keys)
        self.assertEqual(keys, {"a/b.pdf", "lp/1.jpg", "plans/x/1.jpg"})


# ── the refusals ───────────────────────────────────────────────────────────

class TheSafetyChecks(unittest.TestCase):

    def _refused(self, db):
        before = {n: len(c.rows) for n, c in db._c.items()}
        code, left = _run(db, True)
        self.assertEqual(code, h.REFUSED)
        self.assertEqual(left, [], "no group may be left on a refusal")
        after = {n: len(c.rows) for n, c in db._c.items() if n in before}
        self.assertEqual(before, after, "a refusal deleted something")
        return h._preflight(db)

    def test_a_companies_document_refuses(self):
        db = _world()
        db.companies.rows.append({"_id": CO, "name": "Ghost"})
        reason, _ = self._refused(db)
        self.assertIn("companies document", reason)

    def test_a_project_not_in_the_list_refuses(self):
        db = _world()
        db.projects.rows.append({"_id": "cccccccccccccccccccccccc",
                                 "company_id": CO, "is_deleted": True})
        reason, facts = self._refused(db)
        self.assertIn("not in the list", reason)
        self.assertEqual(facts["other_projects_of_company"],
                         ["cccccccccccccccccccccccc"])

    def test_a_listed_project_of_another_company_refuses(self):
        db = _world()
        db.projects.rows[1]["company_id"] = OTHER_CO
        reason, _ = self._refused(db)
        self.assertIn(P_176, reason)

    def test_a_listed_project_with_no_company_is_allowed(self):
        db = _world()
        reason, _ = h._preflight(db)
        self.assertIsNone(reason)

    def test_an_active_user_refuses_and_is_listed(self):
        db = _world()
        db.users.rows.append({"_id": "u_live", "company_id": CO,
                              "name": "Still Here", "email": "live@x",
                              "role": "admin"})
        db.users.rows.append({"_id": "u_live2", "company_id": CO,
                              "is_deleted": False, "email": "live2@x"})
        reason, facts = self._refused(db)
        self.assertIn("2 active user(s)", reason)
        self.assertEqual({u["_id"] for u in facts["active_users_of_company"]},
                         {"u_live", "u_live2"})
        self.assertIn("live@x", reason)

    def test_a_deleted_user_does_not_refuse(self):
        reason, _ = h._preflight(_world())   # u_gone is is_deleted: true
        self.assertIsNone(reason)

    def test_a_group_also_bound_elsewhere_refuses(self):
        db = _world()
        db.whatsapp_groups.rows.append({"_id": "g_dup", "wa_group_id": SECOND_GROUP,
                                        "company_id": OTHER_CO,
                                        "project_id": OTHER_P})
        reason, _ = self._refused(db)
        self.assertIn("bound elsewhere", reason)

    def test_every_leave_is_tried_and_the_rerun_names_those_left(self):
        """A leave cannot be undone. One failure must not stop the others
        halfway; the output names what was left so the re-run skips it."""
        import io
        from contextlib import redirect_stdout
        db = _world()
        before = {n: len(c.rows) for n, c in db._c.items()}
        tried = []

        def leave(action, chat_id):
            tried.append(chat_id)
            return (chat_id != SECOND_GROUP), "http 200"

        buf = io.StringIO()
        with patch.object(h, "_leave_group", leave), \
                patch.object(h, "_r2_delete", lambda keys: []), \
                patch.object(h, "_r2_listing", lambda prefixes: {}), \
                redirect_stdout(buf):
            code = h.run(db, True, _args())
        out = buf.getvalue()
        self.assertEqual(code, h.REFUSED)
        self.assertEqual(set(tried), {h.TARGET_WA_GROUP, SECOND_GROUP, PENDING_GROUP})
        self.assertEqual({n: len(c.rows) for n, c in db._c.items()
                          if n in before}, before)
        rerun = [ln for ln in out.splitlines() if ln.startswith("Re-run with")][0]
        self.assertIn(f"--bot-not-in-group {h.TARGET_WA_GROUP}", rerun)
        self.assertIn(f"--bot-not-in-group {PENDING_GROUP}", rerun)
        self.assertNotIn(SECOND_GROUP, rerun)

    def test_a_failed_leave_refuses_before_any_delete(self):
        db = _world()
        before = {n: len(c.rows) for n, c in db._c.items()}
        code, left = _run(db, True, leave_ok=False)
        self.assertEqual(code, h.REFUSED)
        self.assertEqual(len(left), 3)   # every leave is attempted
        self.assertEqual({n: len(c.rows) for n, c in db._c.items()
                          if n in before}, before)

    def test_a_failed_r2_delete_keeps_every_row(self):
        db = _world()
        before = {n: len(c.rows) for n, c in db._c.items()}
        code, _ = _run(db, True, r2_failed=["co/laf/plan.pdf"])
        self.assertEqual(code, h.FAILED)
        self.assertEqual({n: len(c.rows) for n, c in db._c.items()
                          if n in before}, before)


# ── a full run ─────────────────────────────────────────────────────────────

class AFullRun(unittest.TestCase):

    def test_the_dry_run_writes_nothing_and_leaves_no_group(self):
        db = _world()
        before = copy.deepcopy({n: c.rows for n, c in db._c.items()})
        code, left = _run(db, False)
        self.assertEqual(code, h.OK)
        self.assertEqual(left, [])
        self.assertEqual({n: c.rows for n, c in db._c.items() if n in before},
                         before)

    def test_every_group_of_the_company_is_found(self):
        docs, groups = h._discover_groups(_world())
        self.assertEqual(set(groups),
                         {h.TARGET_WA_GROUP, SECOND_GROUP, PENDING_GROUP})
        self.assertEqual(set(docs), {h.TARGET_GROUP_DOC, "g2"})

    def test_execute_deletes_the_company_and_nothing_else(self):
        db = _world()
        code, left = _run(db, True)
        self.assertEqual(code, h.OK)
        self.assertEqual(set(left),
                         {h.TARGET_WA_GROUP, SECOND_GROUP, PENDING_GROUP})
        ids = lambda c: {r.get("_id") for r in db[c].rows}  # noqa: E731
        self.assertEqual(ids("projects"), {OTHER_P})
        self.assertEqual(ids("users"), {"u_other"})
        self.assertEqual(ids("whatsapp_groups"), {"g_other"})
        self.assertEqual(ids("whatsapp_pending_groups"), set())
        self.assertEqual(ids("whatsapp_messages"), {"m_other"})
        self.assertEqual(ids("checkins"), {"c_other"})
        self.assertEqual(ids("project_files"), {"f_other"})
        self.assertEqual(ids("document_page_index"), set())
        self.assertEqual(ids("logbooks"), set())
        self.assertEqual(ids("logbook_thumbnails"), set())
        self.assertEqual(ids("system_config"), {"s_other"})
        # References in rows that survive are pulled, not the rows.
        self.assertEqual(db.users.rows[0]["assigned_projects"], [OTHER_P])
        self.assertEqual(db.workers.rows[0]["safety_orientations"],
                         [{"project_id": OTHER_P}])
        # The audit trail is kept and grows: one row per project + company.
        self.assertIn("a1", ids("audit_logs"))
        self.assertEqual(len(db.audit_logs.rows), 1 + 5 + 1)

    def test_a_group_named_not_a_member_is_skipped(self):
        db = _world()
        code, left = _run(db, True, args=_args(bot_not_in_group=[PENDING_GROUP]))
        self.assertEqual(code, h.OK)
        self.assertNotIn(PENDING_GROUP, left)
        self.assertEqual(len(left), 2)


if __name__ == "__main__":
    unittest.main()
