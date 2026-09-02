"""Per-file site-device visibility — the file is chosen, not the folder.

THE RULING. "A model where adding a file to a folder silently publishes it to
a device an inspector reads is wrong regardless of convenience." Folder
selection (`project.site_device_subfolders` + `_path_is_under_allowed_subfolder`)
is REPLACED, not supplemented: a `site_visible` boolean on each project_files
row is the only thing that publishes a file to a tablet.

WHY A ROW FLAG AND NOT A LIST ON THE PROJECT. The folder list could not
represent a DIRECT UPLOAD at all — `POST /projects/{id}/upload-file` stores
`dropbox_path: ""`, and `_path_is_under_allowed_subfolder("")` returns False on
its first line, so a directly-uploaded drawing was invisible to every tablet
forever with no folder that could ever have included it. That gap is pinned
below (`ADirectUploadCanBeChosen`) because closing it is half the point.

THE THREE ENFORCEMENT POINTS, not one. Before this change the allow-list was a
LISTING filter only. Two retrieval routes ignored it completely:

    GET /projects/{id}/files/{file_id}/content   (stream_project_file)
        checked _same_company_or_403 and nothing else, so any site device could
        stream any file on its own project by id.
    GET /projects/{id}/dropbox-file-url          (get_dropbox_file_url)
        checked project_access_ok and nothing else, then handed back a Dropbox
        get_temporary_link for whatever `file_path` the CALLER named.

"Nothing reaches that tablet without someone choosing it" was false while those
stood, so all three carry the same predicate now. Admins and CPs are unchanged
on every one of them, and that direction is asserted as hard as the refusal is:
a guard that 403s everybody is as broken as one that 403s nobody.

FAIL-CLOSED IS THE DEFAULT. A row with no `site_visible` key, or `False`, or
anything that is not the boolean True, is not published. That is what makes a
newly synced file invisible until an admin picks it, which is the behaviour the
Plans & Files indicator exists to make noticeable.

    python -m pytest backend/tests/test_site_device_file_visibility.py
"""

from __future__ import annotations

import ast
import io
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

# Stable ids so the tests can name a row in a URL.
ID_APPROVED = ObjectId("aaaaaaaaaaaaaaaaaaaaaaa1")
ID_SUPERSEDED = ObjectId("aaaaaaaaaaaaaaaaaaaaaaa2")
ID_DIRECT = ObjectId("aaaaaaaaaaaaaaaaaaaaaaa3")


def _row(oid, name, path, *, site_visible=None, source="dropbox_sync"):
    rec = {
        "_id": oid,
        "project_id": PROJECT_ID,
        "company_id": COMPANY,
        "name": name,
        "dropbox_path": path,
        "r2_key": f"{COMPANY}/{PROJECT_ID}/{name}",
        "r2_url": "",
        "size": 10,
        "modified": "",
        "cache_version": 1,
        "source": source,
    }
    if site_visible is not None:
        rec["site_visible"] = site_visible
    return rec


# One published drawing, one superseded drawing sitting in the SAME Dropbox
# folder (the folder model could not tell them apart — that is the whole
# complaint), and one direct upload the folder model could never reach.
def _rows():
    return [
        _row(ID_APPROVED, "approved.pdf", "/site a/plans/approved.pdf",
             site_visible=True),
        _row(ID_SUPERSEDED, "superseded.pdf", "/site a/plans/superseded.pdf"),
        _row(ID_DIRECT, "field-sketch.pdf", "", source="direct_upload"),
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
    for k, v in query.items():
        if k == "is_deleted":
            if doc.get("is_deleted") is not None:
                return False
            continue
        if isinstance(v, dict) and "$in" in v:
            if doc.get(k) not in v["$in"]:
                return False
            continue
        if isinstance(v, dict) and "$regex" in v:
            flags = re.I if "i" in (v.get("$options") or "") else 0
            if not re.search(v["$regex"], str(doc.get(k) or ""), flags):
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _FilesCollection:
    def __init__(self, docs):
        self.docs = docs
        self.updates = []
        self.last_find_query = None

    def find(self, query=None, *a, **k):
        self.last_find_query = dict(query or {})
        return _Cursor([d for d in self.docs if _matches(d, query or {})])

    async def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if _matches(d, query or {}):
                return d
        return None

    async def update_many(self, q, u, *a, **k):
        self.updates.append((q, u))
        hit = [d for d in self.docs if _matches(d, q)]
        for d in hit:
            d.update(u.get("$set", {}))
        return _Result(len(hit), len(hit))

    async def update_one(self, q, u, *a, **k):
        self.updates.append((q, u))
        for d in self.docs:
            if _matches(d, q):
                d.update(u.get("$set", {}))
                return _Result(1, 1)
        return _Result(0, 0)


class _EmptyCollection:
    """Any collection these routes touch incidentally (document_page_index,
    etc). A bare MagicMock is not awaitable, which surfaces as a confusing
    TypeError rather than the empty result the test actually wants."""

    def find(self, *a, **k):
        return _Cursor([])

    async def find_one(self, *a, **k):
        return None

    async def count_documents(self, *a, **k):
        return 0

    async def update_one(self, *a, **k):
        return _Result()

    async def insert_one(self, *a, **k):
        return _Result()


class _FakeDb:
    def __init__(self, docs, project):
        self.project_files = _FilesCollection(docs)
        self._project = project
        self.projects = MagicMock()

        async def _find_one(q, *a, **k):
            return self._project

        self.projects.find_one = _find_one
        self._others = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self.__dict__.setdefault("_others", {}).setdefault(
            n, _EmptyCollection())


DEVICE = {"_id": "dev1", "id": "dev1", "role": "site_device", "site_mode": True,
          "company_id": COMPANY, "project_id": PROJECT_ID,
          "assigned_projects": [PROJECT_ID], "account_status": "approved"}
ADMIN = {"_id": "u1", "id": "u1", "role": "admin", "company_id": COMPANY,
         "account_status": "approved", "assigned_projects": [PROJECT_ID]}
CP = {"_id": "u2", "id": "u2", "role": "cp", "company_id": COMPANY,
      "account_status": "approved", "assigned_projects": [PROJECT_ID]}

PROJECT = {"_id": PROJECT_ID, "id": PROJECT_ID, "company_id": COMPANY,
           "dropbox_folder_path": FOLDER,
           # Deliberately still on the doc: the migration reads it, the
           # request path must not. A hybrid would pass every other test here.
           "site_device_subfolders": ["Plans"]}


class _Ctx:
    """TestClient with `user` authenticated and `db` patched in."""

    def __init__(self, user, docs=None, project=None):
        self.user = user
        self.db = _FakeDb(docs if docs is not None else _rows(),
                          PROJECT if project is None else project)

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


# ------------------------------------------------------------------- listing

class ASiteDeviceSeesOnlyChosenFiles(unittest.TestCase):

    def test_device_gets_the_chosen_file_only(self):
        with _Ctx(DEVICE) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}/dropbox-files")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([f["name"] for f in r.json()], ["approved.pdf"])

    def test_the_superseded_sibling_in_the_same_folder_is_withheld(self):
        """Both PDFs live under /site a/plans. Folder selection published
        both; that is the exposure the ruling is about."""
        with _Ctx(DEVICE) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}/dropbox-files")
        self.assertNotIn("superseded.pdf", [f["name"] for f in r.json()])

    def test_the_filter_is_pushed_into_the_query_not_applied_after(self):
        """A post-hoc filter under a to_list ceiling drops chosen files
        silently once a project outgrows the page."""
        with _Ctx(DEVICE) as c:
            c.client.get(f"/api/projects/{PROJECT_ID}/dropbox-files")
            q = c.db.project_files.last_find_query
        self.assertEqual(q.get("site_visible"), True)

    def test_a_device_with_nothing_chosen_gets_an_empty_list(self):
        docs = [_row(ID_SUPERSEDED, "superseded.pdf", "/site a/plans/x.pdf")]
        with _Ctx(DEVICE, docs=docs) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}/dropbox-files")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), [])

    def test_an_empty_result_never_falls_through_to_a_live_dropbox_listing(self):
        """`if cached_files:` falls through when the list is empty. For a site
        device that fallback would list Dropbox with no row to authorize any of
        it. dropbox_api_call must not be reached at all."""
        called = []

        async def _boom(*a, **k):
            called.append(a)
            raise AssertionError("live Dropbox listing reached by a site device")

        with _Ctx(DEVICE, docs=[]) as c:
            with patch.object(server, "dropbox_api_call", _boom):
                r = c.client.get(f"/api/projects/{PROJECT_ID}/dropbox-files")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), [])
        self.assertEqual(called, [])

    def test_an_admin_still_sees_every_file(self):
        with _Ctx(ADMIN) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}/dropbox-files")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(
            sorted(f["name"] for f in r.json()),
            ["approved.pdf", "field-sketch.pdf", "superseded.pdf"])

    def test_an_admin_query_is_not_narrowed(self):
        with _Ctx(ADMIN) as c:
            c.client.get(f"/api/projects/{PROJECT_ID}/dropbox-files")
            q = c.db.project_files.last_find_query
        self.assertNotIn("site_visible", q)

    def test_the_listing_reports_the_flag_so_the_admin_screen_can_show_it(self):
        """The Plans & Files indicator is only possible if the field ships."""
        with _Ctx(ADMIN) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}/dropbox-files")
        by_name = {f["name"]: f for f in r.json()}
        self.assertIs(by_name["approved.pdf"]["site_visible"], True)
        self.assertIs(by_name["superseded.pdf"]["site_visible"], False)
        self.assertIs(by_name["field-sketch.pdf"]["site_visible"], False)


class ANewlySyncedFileIsNotPublished(unittest.TestCase):
    """A folder that gains a file does NOT gain a tablet drawing."""

    def test_a_row_with_no_flag_is_invisible(self):
        docs = _rows() + [_row(ObjectId(), "brand-new.pdf",
                               "/site a/plans/brand-new.pdf")]
        with _Ctx(DEVICE, docs=docs) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}/dropbox-files")
        self.assertNotIn("brand-new.pdf", [f["name"] for f in r.json()])

    def test_the_sync_writes_the_flag_false_on_insert(self):
        """Not merely absent — written, so a Mongo query can COUNT what is
        unpublished instead of inferring it from a missing key."""
        fn = _fn("_sync_project_to_r2")
        src = ast.get_source_segment(_SRC, fn) or ""
        self.assertIn("site_visible", src)

    def test_the_sync_does_not_reset_the_flag_on_an_existing_row(self):
        """The update branch does `$set: file_record`. If file_record carried
        site_visible, every re-sync would un-publish everything an admin had
        chosen, and it would look like the tablet 'lost' the drawings."""
        fn = _fn("_sync_project_to_r2")
        assigns = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "file_record"
                    for t in n.targets)
            and isinstance(n.value, ast.Dict)
        ]
        self.assertTrue(assigns, "file_record dict literal not found")
        for a in assigns:
            keys = [k.value for k in a.value.keys if isinstance(k, ast.Constant)]
            self.assertNotIn(
                "site_visible", keys,
                "site_visible in the dict that is $set over an existing row")


class ADirectUploadCanBeChosen(unittest.TestCase):
    """The gap the folder model could not close: dropbox_path is "", so no
    folder rule could ever have published it."""

    def test_it_is_not_published_by_default(self):
        with _Ctx(DEVICE) as c:
            r = c.client.get(f"/api/projects/{PROJECT_ID}/dropbox-files")
        self.assertNotIn("field-sketch.pdf", [f["name"] for f in r.json()])

    def test_once_chosen_it_reaches_the_tablet(self):
        docs = _rows()
        with _Ctx(ADMIN, docs=docs) as c:
            r = c.client.put(
                f"/api/projects/{PROJECT_ID}/site-device-files",
                json={"file_ids": [str(ID_DIRECT)], "visible": True})
        self.assertEqual(r.status_code, 200, r.text)

        with _Ctx(DEVICE, docs=docs) as c:
            r2 = c.client.get(f"/api/projects/{PROJECT_ID}/dropbox-files")
        self.assertIn("field-sketch.pdf", [f["name"] for f in r2.json()])

    def test_the_old_folder_predicate_could_never_have_reached_it(self):
        """Documents the gap rather than trusting the memory of it. The
        predicate now lives in the migration script; it returns False on an
        empty path in its first line."""
        script = _BACKEND / "scripts" / "migrate_site_device_file_visibility.py"
        ns = {"__name__": "_migration_under_test", "__file__": str(script)}
        exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"),
             ns)
        pred = ns["_path_is_under_allowed_subfolder"]
        self.assertFalse(pred("", FOLDER, ["Plans"]))


class ChoosingAFileIsExplicit(unittest.TestCase):

    def test_only_the_named_rows_change(self):
        docs = _rows()
        with _Ctx(ADMIN, docs=docs) as c:
            c.client.put(f"/api/projects/{PROJECT_ID}/site-device-files",
                         json={"file_ids": [str(ID_SUPERSEDED)], "visible": True})
        by_id = {d["_id"]: d for d in docs}
        self.assertIs(by_id[ID_SUPERSEDED]["site_visible"], True)
        self.assertIs(by_id[ID_APPROVED]["site_visible"], True)   # untouched
        self.assertIsNot(by_id[ID_DIRECT].get("site_visible"), True)

    def test_a_file_can_be_withdrawn(self):
        docs = _rows()
        with _Ctx(ADMIN, docs=docs) as c:
            r = c.client.put(f"/api/projects/{PROJECT_ID}/site-device-files",
                             json={"file_ids": [str(ID_APPROVED)],
                                   "visible": False})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIs(docs[0]["site_visible"], False)

    def test_an_id_that_matched_nothing_is_reported_not_swallowed(self):
        stray = str(ObjectId())
        with _Ctx(ADMIN) as c:
            r = c.client.put(f"/api/projects/{PROJECT_ID}/site-device-files",
                             json={"file_ids": [str(ID_DIRECT), stray],
                                   "visible": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json().get("unmatched"), [stray])

    def test_a_malformed_id_is_refused_rather_than_ignored(self):
        with _Ctx(ADMIN) as c:
            r = c.client.put(f"/api/projects/{PROJECT_ID}/site-device-files",
                             json={"file_ids": ["not-an-objectid"],
                                   "visible": True})
        self.assertEqual(r.status_code, 400, r.text)

    def test_visible_must_be_stated(self):
        """No default. The caller says which way it is choosing."""
        with _Ctx(ADMIN) as c:
            r = c.client.put(f"/api/projects/{PROJECT_ID}/site-device-files",
                             json={"file_ids": [str(ID_DIRECT)]})
        self.assertEqual(r.status_code, 400, r.text)

    def test_a_site_device_cannot_publish_to_itself(self):
        with _Ctx(DEVICE) as c:
            del server.app.dependency_overrides[server.get_admin_user]
            r = c.client.put(f"/api/projects/{PROJECT_ID}/site-device-files",
                             json={"file_ids": [str(ID_DIRECT)],
                                   "visible": True})
        self.assertIn(r.status_code, (401, 403), r.text)


# ----------------------------------------------------- the retrieval routes

class _R2:
    """Minimal boto3-shaped double so the admin direction can reach 200."""

    @staticmethod
    def get_object(Bucket=None, Key=None):
        return {"Body": io.BytesIO(b"%PDF-1.4 x"), "ContentType": "application/pdf",
                "ContentLength": 10}


class StreamingRefusesAnUnchosenFile(unittest.TestCase):
    """GET /projects/{id}/files/{file_id}/content — checked company only."""

    def _get(self, user, oid):
        with _Ctx(user) as c:
            with patch.object(server, "_r2_client", _R2), \
                 patch.object(server, "R2_BUCKET_NAME", "bucket"):
                return c.client.get(
                    f"/api/projects/{PROJECT_ID}/files/{oid}/content")

    def test_a_device_is_refused_the_unchosen_file(self):
        self.assertEqual(self._get(DEVICE, ID_SUPERSEDED).status_code, 403)

    def test_a_device_still_gets_the_chosen_file(self):
        r = self._get(DEVICE, ID_APPROVED)
        self.assertEqual(r.status_code, 200, r.text)

    def test_an_admin_still_gets_the_unchosen_file(self):
        r = self._get(ADMIN, ID_SUPERSEDED)
        self.assertEqual(r.status_code, 200, r.text)

    def test_a_cp_still_gets_the_unchosen_file(self):
        r = self._get(CP, ID_SUPERSEDED)
        self.assertEqual(r.status_code, 200, r.text)


class TheUrlRouteRefusesAnUnchosenFile(unittest.TestCase):
    """GET /projects/{id}/dropbox-file-url — checked project access only, then
    returned a Dropbox temporary link for whatever path the caller named."""

    def _get(self, user, path, docs=None):
        with _Ctx(user, docs=docs) as c:
            return c.client.get(
                f"/api/projects/{PROJECT_ID}/dropbox-file-url",
                params={"file_path": path})

    def test_a_device_is_refused_the_unchosen_file(self):
        r = self._get(DEVICE, "/site a/plans/superseded.pdf")
        self.assertEqual(r.status_code, 403, r.text)

    def test_a_device_naming_a_path_with_no_row_is_refused(self):
        """The temporary-link fallback took ANY path — including one outside
        the project folder entirely. With no row there is nothing that could
        have been chosen, so it fails closed."""
        called = []

        async def _boom(*a, **k):
            called.append(a)
            raise AssertionError("get_temporary_link reached by a site device")

        with _Ctx(DEVICE) as c:
            with patch.object(server, "dropbox_api_call", _boom):
                r = c.client.get(
                    f"/api/projects/{PROJECT_ID}/dropbox-file-url",
                    params={"file_path": "/some other project/payroll.pdf"})
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(called, [])

    def test_a_device_still_gets_the_chosen_file(self):
        r = self._get(DEVICE, "/site a/plans/approved.pdf")
        self.assertEqual(r.status_code, 200, r.text)

    def test_an_admin_still_gets_the_unchosen_file(self):
        r = self._get(ADMIN, "/site a/plans/superseded.pdf")
        self.assertEqual(r.status_code, 200, r.text)

    def test_a_cp_still_gets_the_unchosen_file(self):
        r = self._get(CP, "/site a/plans/superseded.pdf")
        self.assertEqual(r.status_code, 200, r.text)


class TheIndexStatusListIsAlsoScoped(unittest.TestCase):
    """GET /projects/{id}/document-index-status hands back no bytes, no r2_key
    and no link — but it NAMES every PDF on the project and gives each file_id.
    A site device can reach it (get_current_user only), so an unpublished
    drawing was listed by name on the tablet even though /content refuses it."""

    def _get(self, user):
        with _Ctx(user) as c:
            with patch.object(server, "_r2_client", None):
                return c.client.get(
                    f"/api/projects/{PROJECT_ID}/document-index-status")

    def test_a_device_is_not_told_the_unchosen_file_exists(self):
        r = self._get(DEVICE)
        self.assertEqual(r.status_code, 200, r.text)
        names = [f["file_name"] for f in r.json().get("files", [])]
        self.assertEqual(names, ["approved.pdf"])

    def test_an_admin_still_sees_every_pdf(self):
        r = self._get(ADMIN)
        self.assertEqual(r.status_code, 200, r.text)
        names = sorted(f["file_name"] for f in r.json().get("files", []))
        self.assertEqual(names, ["approved.pdf", "field-sketch.pdf",
                                 "superseded.pdf"])


# ------------------------------------------------------------- migration

def _migration():
    """Load the migration as a module object without importing motor."""
    script = _BACKEND / "scripts" / "migrate_site_device_file_visibility.py"
    ns = {"__name__": "_migration_under_test", "__file__": str(script)}
    exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), ns)
    return ns


class TheMigrationConvertsFoldersToFiles(unittest.TestCase):
    """"Existing folder selections MUST become explicit file selections
    covering exactly the files they currently cover.\""""

    def setUp(self):
        self.m = _migration()
        self.classify = self.m["classify"]
        self.project = dict(PROJECT)

    def test_a_file_the_tablet_could_see_is_published(self):
        rec = _row(ID_APPROVED, "a.pdf", "/site a/plans/a.pdf")
        self.assertEqual(self.classify(rec, self.project), self.m["PUBLISH"])

    def test_a_file_outside_the_chosen_folder_is_withheld(self):
        rec = _row(ID_APPROVED, "a.pdf", "/site a/invoices/a.pdf")
        self.assertEqual(self.classify(rec, self.project), self.m["WITHHOLD"])

    def test_a_project_that_chose_no_folders_publishes_nothing(self):
        """It saw nothing before; it must see nothing after."""
        proj = {**self.project, "site_device_subfolders": []}
        rec = _row(ID_APPROVED, "a.pdf", "/site a/plans/a.pdf")
        self.assertEqual(self.classify(rec, proj), self.m["WITHHOLD"])

    def test_a_direct_upload_stays_invisible_and_is_its_own_bucket(self):
        """Publishing it would be a silent ADD — no folder could ever have
        published it, so nobody has ever chosen it. Its own bucket because the
        report names these files individually."""
        rec = _row(ID_DIRECT, "sketch.pdf", "", source="direct_upload")
        self.assertEqual(self.classify(rec, self.project), self.m["DIRECT"])

    def test_a_row_already_decided_is_left_alone(self):
        """Idempotence, and it protects a choice an admin made between runs."""
        rec = _row(ID_APPROVED, "a.pdf", "/site a/plans/a.pdf", site_visible=False)
        self.assertEqual(self.classify(rec, self.project), self.m["ALREADY"])

    def test_a_row_with_no_project_is_refused_not_guessed(self):
        rec = _row(ID_APPROVED, "a.pdf", "/site a/plans/a.pdf")
        with self.assertRaises(self.m["Refusal"]):
            self.classify(rec, None)

    def test_a_non_string_path_is_refused_not_coerced(self):
        rec = _row(ID_APPROVED, "a.pdf", "/x/a.pdf")
        rec["dropbox_path"] = 17
        with self.assertRaises(self.m["Refusal"]):
            self.classify(rec, self.project)

    def test_a_non_boolean_flag_is_refused(self):
        rec = _row(ID_APPROVED, "a.pdf", "/site a/plans/a.pdf")
        rec["site_visible"] = "yes"
        with self.assertRaises(self.m["Refusal"]):
            self.classify(rec, self.project)

    def test_every_row_lands_in_exactly_one_bucket(self):
        """The report's counts only mean something if they are exhaustive."""
        buckets = {self.m["PUBLISH"], self.m["WITHHOLD"],
                   self.m["DIRECT"], self.m["ALREADY"]}
        for rec in _rows():
            self.assertIn(self.classify(rec, self.project), buckets)

    def test_dry_run_is_the_default(self):
        """Repo convention, and the one that matters here: a wrong live run
        changes what a tablet shows an inspector."""
        import argparse as _ap
        src = (_BACKEND / "scripts"
               / "migrate_site_device_file_visibility.py").read_text("utf-8")
        tree = ast.parse(src)
        run = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.AsyncFunctionDef) and n.name == "run")
        self.assertIn("execute", [a.arg for a in run.args.args])
        self.assertIn("--execute", src)
        del _ap


# ------------------------------------------------------------- no hybrid

def _fn(name):
    for node in ast.walk(_TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    raise AssertionError(f"{name} not found in server.py")


class ThereIsExactlyOneModel(unittest.TestCase):
    """"Two models for the same question is how a folder rule and a file rule
    end up disagreeing, and the disagreement is invisible until an inspector is
    holding the tablet.\""""

    def test_the_folder_predicate_is_gone_from_the_request_path(self):
        """READ AS CODE, not as text. The replacement helper's docstring names
        the predicate it replaced — a substring check would match that prose
        and pass for the wrong reason (the practice note in followups.md)."""
        defined = {n.name for n in ast.walk(_TREE)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertNotIn("_path_is_under_allowed_subfolder", defined)
        self.assertNotIn("_normalize_subfolder_names", defined)

        called = {n.func.id for n in ast.walk(_TREE)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertNotIn("_path_is_under_allowed_subfolder", called)
        self.assertNotIn("_normalize_subfolder_names", called)

    def test_no_request_handler_reads_the_folder_list(self):
        """Over STRING CONSTANTS and ATTRIBUTE NAMES in the parsed handler,
        not its source text — a substring ban would also match the word where
        it appears in a comment explaining that the field is no longer read."""
        for name in ("get_project_dropbox_files", "stream_project_file",
                     "get_dropbox_file_url", "set_site_device_files"):
            fn = _fn(name)
            literals = {n.value for n in ast.walk(fn)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
            self.assertTrue(
                "site_device_subfolders" not in literals,
                f"{name} still reads the folder list")
            self.assertTrue(
                "site_device_subfolders" not in attrs,
                f"{name} still reads the folder list")

    def test_the_folder_write_endpoint_is_gone(self):
        """Asked of the LIVE ROUTE TABLE. The replacement endpoint's docstring
        names the route it replaced, so a source substring check would match
        the prose and pass without the route being gone."""
        paths = {getattr(r, "path", "") for r in server.app.routes}
        self.assertNotIn(
            "/api/projects/{project_id}/site-device-subfolders", paths)
        self.assertIn("/api/projects/{project_id}/site-device-files", paths)

    def test_the_replacement_carries_both_write_guards(self):
        """It inherits TIER2_SETTINGS duty from the route it replaces:
        require_approved (a pending account spends nothing) and
        require_project_access (fails closed on a company-less caller)."""
        route = next(r for r in server.app.routes
                     if getattr(r, "path", "")
                     == "/api/projects/{project_id}/site-device-files")
        names = {getattr(d.call, "__name__", "")
                 for d in route.dependant.dependencies}
        self.assertIn("require_approved", names)
        self.assertIn("require_project_access", names)

    def test_the_listing_has_no_row_ceiling(self):
        """to_list(5000) capped what a tablet could ever see, independent of
        any filter, and it failed by OMISSION — a short list, no error.

        Asserted over the CALL NODE. The comment that records the old ceiling
        contains the literal `to_list(5000)`, so a text search finds it in the
        prose and passes for the wrong reason."""
        calls = [n for n in ast.walk(_fn("get_project_dropbox_files"))
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "to_list"]
        self.assertTrue(calls, "no to_list call found")
        for c in calls:
            self.assertEqual(len(c.args), 1)
            self.assertIsInstance(c.args[0], ast.Constant)
            self.assertIsNone(c.args[0].value,
                              f"to_list({ast.unparse(c.args[0])}) is a ceiling")


class TheAdminScreenSaysWhatIsUnpublished(unittest.TestCase):
    """"A folder that gains a file after the migration: the new file is NOT
    visible until someone selects it, and the admin screen must SAY SO." An
    explicit model without this degrades into 'nobody notices the new drawing
    is missing.'"""

    SCREEN = (_BACKEND.parent / "frontend" / "app" / "projects" / "[id]"
              / "files.jsx")

    def setUp(self):
        self.src = self.SCREEN.read_text(encoding="utf-8")

    # assertIn against a 1800-line screen prints the whole file on failure.
    def _has(self, needle):
        self.assertTrue(needle in self.src, f"{needle!r} missing from files.jsx")

    def _lacks(self, needle):
        self.assertTrue(needle not in self.src, f"{needle!r} still in files.jsx")

    def test_the_screen_reads_the_flag(self):
        self._has("site_visible")

    def test_the_screen_counts_what_is_not_published(self):
        self._has("unpublishedCount")

    def test_the_screen_names_the_state_in_words_not_only_an_icon(self):
        """A colour or an icon alone is a state an admin has to already know
        how to read. The row says it."""
        self._has("Not on site tablet")

    def test_the_screen_can_publish_a_file(self):
        self._has("setSiteDeviceFiles")

    def test_the_screen_no_longer_offers_folder_selection(self):
        self._lacks("setSiteDeviceSubfolders")
        self._lacks("siteDeviceSelected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
