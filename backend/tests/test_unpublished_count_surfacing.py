"""The backlog is only a cost the operator accepted if he can SEE it.

THE RULING THIS SERVES. Nothing reaches the gate tablet until a person picks
that file — no auto-publish, no inherit-from-predecessor. The operator took
that trade with his eyes open and named the failure it creates:

    "An admin who never opens Plans & Files will never see the count, and then
    the tablet silently falls behind instead of silently running ahead."

So the count has to leave the Plans & Files screen. This file pins the two
places it goes and the shape of both.

WHY THE COUNT RIDES ON GET /projects/{id} AND NOT A NEW ENDPOINT. The project
detail screen already calls it once on mount (project/[id].jsx:286) and it is
the screen that carries the FILES row. A dedicated endpoint would be a second
round trip for one integer, and a second thing to keep in sync. But
ProjectResponse IS AN ALLOW-LIST — pydantic drops every undeclared field with
no error anywhere — and this repository has already paid for that once:
dropbox_folder_path, dropbox_last_synced and dropbox_sync were all written by
the server, all undeclared, and the detail endpoint reported every project as
unlinked for as long as that lasted. `ADeclaredFieldOrItIsDropped` below is
that lesson pinned, because a count that is computed and then silently thrown
away is worse than no count: the screen renders "nothing waiting" and it is
wrong.

FAIL-CLOSED, THE SAME WAY THE READ IS. `_site_device_may_read_file` publishes
on `site_visible is True` and nothing else, so a row with no key at all is
withheld from the tablet. The count MUST use the same predicate — `$ne: True`,
not `== False` — or a freshly synced row (which does carry False) would be
counted while a legacy row (which carries no key) would not, and the number on
the screen would disagree with what the tablet can actually read. That
disagreement is the whole bug class this feature exists to prevent.

WHO IS TOLD, AND WHY NOT EVERYONE.
  admin/owner  the count, because PUT /site-device-files is get_admin_user —
               they are the only people who can act on it.
  CP           None. A CP cannot publish. A number he cannot act on is noise
               on a screen he uses every day.
  site device  None, and this one is a disclosure question rather than a noise
               question. The tablet is held by a DOB inspector. "7 files here
               you are not being shown" is a fact about the size of what was
               withheld, and this codebase has already ruled once that a NAME
               is a disclosure (get_document_index_status). A COUNT is a
               smaller one, but it is one, and the tablet has no use for it.

THE NOTIFICATION, AND THE ONE THING THAT MAKES IT HONEST. A notification fires
once and cannot be un-fired; the backlog persists. Those two shapes do not
match, and the fix is not to fire on the CONDITION but on the EVENT that
creates it — the sync that added the rows. `source_id` is the sync RUN id, so:

  * re-dispatching the same run is idempotent (the inbox dedups on
    (user_id, source_kind, source_id));
  * the NEXT sync that brings in unpublished files fires again, because it is
    a different run.

That is the same knob checkin_needs_trade uses with `worker:est_day`, applied
to the unit that actually generated the backlog. A sync that added nothing
unpublished must be silent — otherwise the inbox fills with rows that say
nothing happened, and the admin learns to scroll past the kind.

AND THE WORDING IS PART OF THE CONTRACT, not decoration. Files awaiting
selection are the normal state of a correct system. `TheCopyDoesNotAllegeAFault`
asserts that in both the notification and the screen, because "3 files missing
from site tablets" describes the same integer as "3 files awaiting selection"
and only one of them is true.

    python -m pytest backend/tests/test_unpublished_count_surfacing.py
"""

from __future__ import annotations

import ast
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from bson import ObjectId  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8-sig")
_TREE = ast.parse(_SRC)

PROJECT_ID = "proj1"
COMPANY = "co_a"
FOLDER = "/Site A"

# The name of the field the detail response carries. Named for the state it
# describes rather than for a fault: a file waiting to be chosen is what a
# correct system looks like the morning after a sync.
FIELD = "files_awaiting_site_selection"

ADMIN = {"_id": "u1", "id": "u1", "role": "admin", "company_id": COMPANY,
         "account_status": "approved", "assigned_projects": [PROJECT_ID]}
OWNER = {"_id": "u9", "id": "u9", "role": "owner", "company_id": COMPANY,
         "account_status": "approved", "assigned_projects": [PROJECT_ID]}
CP = {"_id": "u2", "id": "u2", "role": "cp", "company_id": COMPANY,
      "account_status": "approved", "assigned_projects": [PROJECT_ID]}
DEVICE = {"_id": "dev1", "id": "dev1", "role": "site_device", "site_mode": True,
          "company_id": COMPANY, "project_id": PROJECT_ID,
          "assigned_projects": [PROJECT_ID], "account_status": "approved"}

PROJECT = {"_id": PROJECT_ID, "id": PROJECT_ID, "name": "Site A",
           "company_id": COMPANY, "status": "active",
           "dropbox_folder_path": FOLDER}


def _row(name, *, site_visible=None, deleted=False, source="dropbox_sync"):
    rec = {
        "_id": ObjectId(),
        "project_id": PROJECT_ID,
        "company_id": COMPANY,
        "name": name,
        "dropbox_path": f"/site a/plans/{name}",
        "source": source,
    }
    if site_visible is not None:
        rec["site_visible"] = site_visible
    if deleted:
        rec["is_deleted"] = True
    return rec


# One chosen file, one a sync wrote False onto, one legacy row carrying NO key
# at all, and one soft-deleted row. The middle two are the same fact to a
# tablet and must be the same fact to the count.
def _rows():
    return [
        _row("approved.pdf", site_visible=True),
        _row("fresh-from-sync.pdf", site_visible=False),
        _row("legacy-no-key.pdf"),
        _row("removed.pdf", site_visible=False, deleted=True),
    ]


# ---------------------------------------------------------------- fake mongo

class _Result:
    def __init__(self, matched=0, modified=0):
        self.matched_count = matched
        self.modified_count = modified
        self.inserted_id = ObjectId()


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, n=None):
        return list(self._docs) if n is None else list(self._docs)[:n]


def _matches(doc, query):
    """Enough of the Mongo matcher for the predicates these routes use.

    `$ne` is spelled out rather than folded into equality because `$ne: True`
    against an ABSENT key is the exact case this whole file is about, and a
    matcher that quietly got it wrong would make the fail-closed test pass for
    the wrong reason.
    """
    for k, v in query.items():
        actual = doc.get(k)
        if isinstance(v, dict):
            if "$ne" in v and actual == v["$ne"]:
                return False
            if "$in" in v and actual not in v["$in"]:
                return False
            if "$gt" in v and not (actual is not None and actual > v["$gt"]):
                return False
            if "$regex" in v:
                flags = re.I if "i" in (v.get("$options") or "") else 0
                if not re.search(v["$regex"], str(actual or ""), flags):
                    return False
            continue
        if actual != v:
            return False
    return True


class _FilesCollection:
    def __init__(self, docs):
        self.docs = docs
        self.count_queries = []

    def find(self, query=None, *a, **k):
        return _Cursor([d for d in self.docs if _matches(d, query or {})])

    async def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if _matches(d, query or {}):
                return d
        return None

    async def count_documents(self, query=None, *a, **k):
        self.count_queries.append(dict(query or {}))
        return len([d for d in self.docs if _matches(d, query or {})])

    async def insert_one(self, doc, *a, **k):
        res = _Result()
        doc["_id"] = res.inserted_id
        self.docs.append(doc)
        return res

    async def update_one(self, q, u, *a, **k):
        for d in self.docs:
            if _matches(d, q):
                d.update(u.get("$set", {}))
                return _Result(1, 1)
        return _Result(0, 0)

    async def update_many(self, q, u, *a, **k):
        hit = [d for d in self.docs if _matches(d, q)]
        for d in hit:
            d.update(u.get("$set", {}))
        return _Result(len(hit), len(hit))


class _EmptyCollection:
    """Collections these routes touch incidentally. A bare MagicMock is not
    awaitable, which surfaces as a confusing TypeError instead of the empty
    result the test wants."""

    def __init__(self):
        self.inserted = []
        self.updates = []

    def find(self, *a, **k):
        return _Cursor([])

    async def find_one(self, *a, **k):
        return None

    async def count_documents(self, *a, **k):
        return 0

    async def insert_one(self, doc=None, *a, **k):
        self.inserted.append(doc)
        return _Result()

    async def update_one(self, q=None, u=None, *a, **k):
        self.updates.append((q, u))
        return _Result()

    async def update_many(self, q=None, u=None, *a, **k):
        self.updates.append((q, u))
        return _Result()

    async def delete_many(self, *a, **k):
        return _Result()


class _FakeDb:
    def __init__(self, docs, project):
        self.project_files = _FilesCollection(docs)
        self._project = project
        self.projects = _EmptyCollection()

        async def _find_one(q=None, *a, **k):
            return self._project

        self.projects.find_one = _find_one
        self._others = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self.__dict__.setdefault("_others", {}).setdefault(
            n, _EmptyCollection())

    def __getitem__(self, n):
        return getattr(self, n)


class _Ctx:
    """TestClient with `user` authenticated and `db` patched in."""

    def __init__(self, user, docs=None, project=None):
        self.user = user
        # COPIED, not shared. get_project stamps the count onto the project
        # dict it fetched — which is a fresh document out of Mongo in
        # production and a module-level literal here. Handing the same dict to
        # every case let an admin's count survive into the next case and made
        # the CP and site-device assertions read a number nobody had computed
        # for them.
        self.db = _FakeDb(_rows() if docs is None else docs,
                          dict(PROJECT if project is None else project))

    def __enter__(self):
        async def _fake_user():
            return self.user

        server.app.dependency_overrides[server.get_current_user] = _fake_user
        server.app.dependency_overrides[server.get_admin_user] = _fake_user
        self._patch = patch.object(server, "db", self.db)
        self._patch.start()
        self.client = TestClient(server.app)
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        server.app.dependency_overrides.clear()
        return False


# ------------------------------------------------- the field must be declared

class ADeclaredFieldOrItIsDropped(unittest.TestCase):
    """ProjectResponse is an allow-list. An undeclared field is removed from
    the response with no error at any layer — the exact failure that made the
    Sync control unreachable on every linked project."""

    def _project_response_fields(self):
        for node in ast.walk(_TREE):
            if isinstance(node, ast.ClassDef) and node.name == "ProjectResponse":
                return {
                    t.target.id for t in node.body
                    if isinstance(t, ast.AnnAssign)
                    and isinstance(t.target, ast.Name)
                }
        self.fail("ProjectResponse not found in server.py")

    def test_the_count_field_is_declared_on_project_response(self):
        self.assertIn(
            FIELD, self._project_response_fields(),
            f"{FIELD} is computed by get_project but not declared on "
            "ProjectResponse, so pydantic drops it and the screen renders "
            "'nothing waiting' for every project",
        )


# ------------------------------------------------------------ the count itself

class TheCountIsWhatTheTabletCannotRead(unittest.TestCase):

    def test_an_admin_is_told_how_many_files_await_selection(self):
        with _Ctx(ADMIN) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}")
        self.assertEqual(r.status_code, 200, r.text)
        # fresh-from-sync (False) + legacy-no-key (absent). Not the published
        # one, and not the soft-deleted one.
        self.assertEqual(r.json().get(FIELD), 2)

    def test_an_owner_is_told_too(self):
        """`owner` is the role every self-serve signup receives, so an
        admin-only surface that checks only for 'admin' reaches nobody."""
        with _Ctx(OWNER) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}")
        self.assertEqual(r.json().get(FIELD), 2)

    def test_a_row_with_no_site_visible_key_counts_as_awaiting(self):
        """Fail-closed, matching _site_device_may_read_file. A legacy row
        carries no key and the tablet cannot read it; if the count used
        `== False` that file would be invisible on BOTH screens."""
        with _Ctx(ADMIN, docs=[_row("legacy-no-key.pdf")]) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}")
        self.assertEqual(r.json().get(FIELD), 1)

    def test_the_predicate_is_ne_true_not_equals_false(self):
        with _Ctx(ADMIN) as c:
            c.client.get(f"/api/projects/{PROJECT_ID}")
            queries = c.db.project_files.count_queries
        self.assertTrue(queries, "get_project never counted anything")
        q = queries[0]
        self.assertEqual(
            q.get("site_visible"), {"$ne": True},
            "the count must use the same fail-closed predicate the read does",
        )

    def test_soft_deleted_rows_are_not_a_backlog(self):
        """A deleted file is not waiting for anyone. Counting it produces an
        amber number nobody can ever clear."""
        with _Ctx(ADMIN) as c:
            c.client.get(f"/api/projects/{PROJECT_ID}")
            q = c.db.project_files.count_queries[0]
        self.assertEqual(q.get("is_deleted"), {"$ne": True})

    def test_the_count_is_scoped_to_this_project(self):
        with _Ctx(ADMIN) as c:
            c.client.get(f"/api/projects/{PROJECT_ID}")
            q = c.db.project_files.count_queries[0]
        self.assertEqual(q.get("project_id"), PROJECT_ID)

    def test_a_project_with_nothing_waiting_reports_zero_not_null(self):
        """Zero and unknown are different answers and the screen renders them
        differently. An admin whose backlog is empty must be told it is empty."""
        with _Ctx(ADMIN, docs=[_row("approved.pdf", site_visible=True)]) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}")
        self.assertEqual(r.json().get(FIELD), 0)


class OnlyThePeopleWhoCanActAreTold(unittest.TestCase):

    def test_a_cp_is_not_given_a_number_he_cannot_act_on(self):
        """PUT /site-device-files is get_admin_user. A CP cannot publish."""
        with _Ctx(CP) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json().get(FIELD))

    def test_a_site_device_is_not_told_the_size_of_what_was_withheld(self):
        """The tablet is held by a DOB inspector. get_document_index_status
        already ruled that a NAME is a disclosure; a count is a smaller one,
        and the tablet has no use for it either way."""
        with _Ctx(DEVICE) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json().get(FIELD))

    def test_no_count_query_runs_for_a_site_device(self):
        """Not just filtered out of the response — never asked. A count the
        caller may not see is a query nobody should pay for."""
        with _Ctx(DEVICE) as c:
            c.client.get(f"/api/projects/{PROJECT_ID}")
            self.assertEqual(c.db.project_files.count_queries, [])


# ------------------------------------------------------------ the notification

def _fn(name):
    for node in ast.walk(_TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    raise AssertionError(f"{name} not found in server.py")


def _src_of(node):
    return ast.get_source_segment(_SRC, node) or ""


class TheSyncThatCreatedTheBacklogIsWhatSpeaks(unittest.TestCase):
    """A notification fires once and cannot be un-fired; the backlog persists.
    Firing on the EVENT rather than the CONDITION is what reconciles the two."""

    def _sync_src(self):
        return _src_of(_fn("_sync_project_to_r2"))

    def test_the_sync_dispatches_a_notification(self):
        self.assertIn(
            "dispatch_notification", self._sync_src(),
            "_sync_project_to_r2 never tells anyone what it left unpublished",
        )

    def test_the_dedup_key_is_the_run_not_the_project(self):
        """source_id = project_id fires once, ever, and the second sync is
        silent forever. source_id = the run id fires once per sync that
        actually added something."""
        src = self._sync_src()
        m = re.search(r"source_id\s*=\s*([^,\n]+)", src)
        self.assertIsNotNone(m, "no source_id passed to dispatch_notification")
        expr = m.group(1)
        self.assertIn("run_id", expr,
                      f"source_id is {expr!r}; it must be keyed on the sync run")

    def test_the_dispatch_cannot_take_the_sync_down_with_it(self):
        """Every existing call site is inside a try. A file that reached R2 is
        not un-synced because an inbox insert failed."""
        node = _fn("_sync_project_to_r2")
        guarded = False
        for handler in [n for n in ast.walk(node) if isinstance(n, ast.Try)]:
            for sub in ast.walk(handler):
                if isinstance(sub, ast.Call):
                    fname = getattr(sub.func, "attr", getattr(sub.func, "id", ""))
                    if fname == "dispatch_notification":
                        guarded = True
        self.assertTrue(
            guarded, "dispatch_notification is not inside a try/except")

    def test_a_sync_that_published_nothing_new_stays_quiet(self):
        """Guarded on a count of rows this run INSERTED unpublished. A sync
        that only refreshed last_synced_at has created no backlog, and a
        notification that says so teaches admins to ignore the kind."""
        src = self._sync_src()
        self.assertTrue(
            re.search(r"if\s+.*awaiting.*[:>]", src, re.I),
            "the dispatch is not guarded on anything this run added",
        )

    def test_the_count_it_reports_is_what_this_run_added(self):
        """Not the project's whole backlog. 'This sync brought in 3' is a
        cause an admin can act on; 'there are 47' is a status line."""
        node = _fn("_sync_project_to_r2")
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        self.assertIn(
            "awaiting_selection", names,
            "no per-run counter of newly-unpublished rows",
        )


class ADirectUploadDoesNotNotifyTheUploader(unittest.TestCase):
    """The admin who just uploaded the file is standing at the screen. The
    notification exists for files that arrived while nobody was looking."""

    def test_the_upload_route_does_not_dispatch(self):
        for fname in ("upload_project_file", "upload_file_to_project"):
            try:
                node = _fn(fname)
            except AssertionError:
                continue
            self.assertNotIn(
                "dispatch_notification", _src_of(node),
                f"{fname} notifies the person who is already looking at it",
            )


class TheCopyDoesNotAllegeAFault(unittest.TestCase):
    """Files awaiting selection are the normal state of a correct system, not
    a fault. The same integer can be described either way and only one of the
    two descriptions is true."""

    # Words that turn a normal state into an accusation. 'unpublished' is not
    # here: it is the state's actual name and the ruling's own vocabulary.
    FAULT_WORDS = [
        "error", "failed", "failure", "missing", "problem", "broken",
        "invalid", "wrong", "overdue", "violation",
    ]

    def _dispatch_kwargs(self):
        node = _fn("_sync_project_to_r2")
        for call in [n for n in ast.walk(node) if isinstance(n, ast.Call)]:
            fname = getattr(call.func, "attr", getattr(call.func, "id", ""))
            if fname == "dispatch_notification":
                return {kw.arg: kw.value for kw in call.keywords}
        self.fail("no dispatch_notification call in _sync_project_to_r2")

    def test_the_severity_is_not_a_warning(self):
        """info/warning/critical is the vocabulary. A file waiting to be
        chosen is not a warning about anything."""
        val = self._dispatch_kwargs().get("severity")
        self.assertIsNotNone(val, "severity not stated explicitly")
        self.assertEqual(
            getattr(val, "value", None), "info",
            "a file awaiting selection is not a warning",
        )

    def test_neither_the_title_nor_the_message_alleges_a_fault(self):
        kwargs = self._dispatch_kwargs()
        for key in ("title", "message"):
            node = kwargs.get(key)
            self.assertIsNotNone(node, f"{key} not passed")
            text = (ast.get_source_segment(_SRC, node) or "").lower()
            for bad in self.FAULT_WORDS:
                self.assertNotIn(
                    bad, text,
                    f"notification {key} calls a normal state a fault "
                    f"({bad!r})",
                )

    def test_the_message_says_selection_is_the_designed_behaviour(self):
        """Otherwise the reader's first conclusion is that the sync broke."""
        node = self._dispatch_kwargs().get("message")
        text = (ast.get_source_segment(_SRC, node) or "").lower()
        self.assertTrue(
            "never" in text or "not automatic" in text or "chooses" in text
            or "choose" in text,
            "the message does not say that nothing publishes automatically, "
            "so it reads as a report of something going wrong",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
