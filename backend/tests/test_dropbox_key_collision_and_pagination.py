"""TWO ROWS MUST NOT SHARE ONE OBJECT, AND A LISTING MUST NOT STOP AT PAGE ONE.

THE COLLISION. R2 keys were built as {company_id}/{project_id}/{filename} with
no path component, while _sync_project_to_r2 lists RECURSIVELY. So
/Approved Plans/plan.pdf and /Permits/plan.pdf in the same project produced two
project_files rows -- kept distinct by the unique index on
(project_id, dropbox_path) -- pointing at ONE R2 object. The second sync
overwrote the first's bytes. Nothing errored, nothing logged, and an inspector
opening "Permits/plan.pdf" got the approved-plans drawing. The index is what
made it invisible: had the rows collided too, the sync would have thrown.

THE MIGRATION RULE. Existing rows keep their existing flat key. Every reader
resolves the object from the STORED r2_key on the row, never by recomputing it
from the name, so a legacy row keeps opening forever with no backfill and no
object ever moved. Only new writes get the folder-scoped shape. The tests below
pin both halves: new writes separate, old rows untouched.

THE PREFIX IS LORE. The project-delete sweep removes objects by the
{company_id}/{project_id}/ prefix. Any new key shape MUST stay under it or
deleting a project would silently orphan its files. Pinned here.

THE PAGINATION. Dropbox's list_folder returns one page and sets has_more with a
cursor. Four of the five listing call sites read data["entries"] once and threw
the rest away. The subfolder picker is the one that stings: site_device_subfolders
is set from exactly that list, so a truncated listing silently limits what a gate
tablet can EVER be approved to see -- an admin cannot tick a box that was never
rendered.

    python -m pytest backend/tests/test_dropbox_key_collision_and_pagination.py
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────

class _Resp:
    """Minimal stand-in for the httpx response dropbox_api_call returns."""

    def __init__(self, payload=None, status_code=200, content=b"%PDF-1.4 bytes"):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self.content = content

    def json(self):
        return self._payload

    @property
    def text(self):
        return str(self._payload)


def _file_entry(path, name=None, content_hash="h1"):
    return {
        ".tag": "file",
        "name": name or path.rsplit("/", 1)[-1],
        "path_lower": path.lower(),
        "path_display": path,
        "content_hash": content_hash,
        "size": 1024,
        "server_modified": "2026-01-01T00:00:00Z",
    }


def _folder_entry(name, path=None):
    return {
        ".tag": "folder",
        "name": name,
        "path_lower": (path or f"/root/{name}").lower(),
        "path_display": path or f"/root/{name}",
        "id": f"id:{name}",
    }


class _SyncHarness:
    """Drives the real _sync_project_to_r2 against fake Dropbox + fake Mongo,
    recording every R2 key written and every project_files row touched."""

    def __init__(self, entries, existing_rows=None, pages=None):
        self.entries = entries
        self.pages = pages          # list of (entries, has_more) for paging tests
        self.existing_rows = existing_rows or []
        self.uploaded_keys = []
        self.inserted = []
        self.updated = []
        self.continue_calls = 0

    # -- fake Dropbox ------------------------------------------------------
    async def dropbox_api_call(self, company_id, method, url, **kwargs):
        if url.endswith("/files/list_folder"):
            if self.pages is not None:
                ents, more = self.pages[0]
                return _Resp({"entries": ents, "has_more": more, "cursor": "c0"})
            return _Resp({"entries": self.entries, "has_more": False, "cursor": ""})
        if url.endswith("/files/list_folder/continue"):
            self.continue_calls += 1
            idx = self.continue_calls
            if self.pages is not None and idx < len(self.pages):
                ents, more = self.pages[idx]
                return _Resp({"entries": ents, "has_more": more, "cursor": f"c{idx}"})
            return _Resp({"entries": [], "has_more": False, "cursor": ""})
        if "files/download" in url:
            return _Resp({}, 200, b"%PDF-1.4 the bytes")
        return _Resp({}, 200)

    # -- fake Mongo --------------------------------------------------------
    def build_db(self):
        h = self

        async def pf_find_one(flt):
            for row in h.existing_rows:
                if (row.get("project_id") == flt.get("project_id")
                        and row.get("dropbox_path") == flt.get("dropbox_path")):
                    return row
            return None

        async def pf_update_one(flt, upd):
            h.updated.append((flt, upd))
            return MagicMock(modified_count=1)

        async def pf_insert_one(doc):
            h.inserted.append(dict(doc))
            return MagicMock(inserted_id=f"new{len(h.inserted)}")

        project_files = MagicMock()
        project_files.find_one = AsyncMock(side_effect=pf_find_one)
        project_files.update_one = AsyncMock(side_effect=pf_update_one)
        project_files.insert_one = AsyncMock(side_effect=pf_insert_one)

        projects = MagicMock()
        projects.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

        runs = MagicMock()
        runs.insert_one = AsyncMock(return_value=MagicMock(inserted_id="run1"))
        runs.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

        db = MagicMock()
        db.project_files = project_files
        db.projects = projects
        db.__getitem__ = MagicMock(return_value=runs)
        return db

    def run(self, project_id="proj1", company_id="co1", folder="/Site"):
        def _capture_upload(file_bytes, r2_key, content_type="application/octet-stream"):
            self.uploaded_keys.append(r2_key)
            return f"https://r2.example/{r2_key}"

        with patch.object(server, "db", self.build_db()), \
             patch.object(server, "dropbox_api_call", AsyncMock(side_effect=self.dropbox_api_call)), \
             patch.object(server, "_upload_to_r2", _capture_upload), \
             patch.object(server, "_r2_client", MagicMock()), \
             patch.object(server, "QWEN_API_KEY", ""), \
             patch.object(server, "to_query_id", lambda x: x):
            asyncio.run(server._sync_project_to_r2(project_id, company_id, folder))
        return self


# ═══════════════════════════════════════════════════════════════════════════
# 1. THE COLLISION
# ═══════════════════════════════════════════════════════════════════════════

class TwoRowsMustNotShareOneObject(unittest.TestCase):

    ENTRIES = [
        _file_entry("/Site/Approved Plans/plan.pdf", content_hash="hA"),
        _file_entry("/Site/Permits/plan.pdf", content_hash="hB"),
    ]

    def test_same_basename_in_different_folders_gets_different_objects(self):
        """THE HEADLINE. Both files are named plan.pdf. Before the fix both
        resolved to co1/proj1/plan.pdf and the second overwrote the first."""
        h = _SyncHarness(self.ENTRIES).run()
        self.assertEqual(len(h.uploaded_keys), 2,
                         f"expected two uploads, got {h.uploaded_keys}")
        self.assertEqual(
            len(set(h.uploaded_keys)), 2,
            "two DIFFERENT files in two DIFFERENT folders were written to ONE "
            f"R2 object: {h.uploaded_keys[0]!r}. The second sync overwrote the "
            "first's bytes and nothing errored.",
        )

    def test_the_rows_were_always_distinct_which_is_what_hid_it(self):
        """The unique index is on (project_id, dropbox_path), so the ROWS never
        collided. Two rows, one object -- no error to notice."""
        h = _SyncHarness(self.ENTRIES).run()
        self.assertEqual(len(h.inserted), 2)
        self.assertEqual(
            {r["dropbox_path"] for r in h.inserted},
            {"/site/approved plans/plan.pdf", "/site/permits/plan.pdf"},
        )

    def test_each_row_points_at_its_own_object(self):
        h = _SyncHarness(self.ENTRIES).run()
        keys = [r["r2_key"] for r in h.inserted]
        self.assertEqual(len(set(keys)), 2,
                         f"two rows still point at one key: {keys}")

    def test_the_key_stays_under_the_project_prefix(self):
        """LOAD-BEARING. hard_delete_project sweeps R2 by the
        {company_id}/{project_id}/ prefix. A key outside it would survive the
        delete as an orphan holding customer drawings."""
        h = _SyncHarness(self.ENTRIES).run()
        for key in h.uploaded_keys:
            self.assertTrue(
                key.startswith("co1/proj1/"),
                f"{key!r} escapes the prefix the project-delete sweep uses",
            )

    def test_the_filename_is_still_the_last_segment(self):
        """Content-type is guessed from the key tail in the streaming path, and
        a human reading an R2 listing needs to see the filename."""
        h = _SyncHarness(self.ENTRIES).run()
        for key in h.uploaded_keys:
            self.assertTrue(key.endswith("/plan.pdf"), key)

    def test_the_key_is_stable_across_syncs(self):
        """A re-sync of unchanged-path/changed-bytes must land on the SAME
        object, or every sync would orphan the last one's bytes."""
        first = _SyncHarness(self.ENTRIES).run().uploaded_keys
        second = _SyncHarness(self.ENTRIES).run().uploaded_keys
        self.assertEqual(first, second, "the key is not deterministic")


class TheHelperIsTheOneSourceOfTheKey(unittest.TestCase):

    def test_a_folder_scoped_key_helper_exists(self):
        self.assertTrue(
            hasattr(server, "_r2_object_key"),
            "no single helper builds the R2 key -- the shape is duplicated at "
            "each call site, which is how the two sites drifted apart",
        )

    def test_distinct_dropbox_paths_never_share_a_key(self):
        k1 = server._r2_object_key("co1", "p1", "plan.pdf", "/site/approved plans/plan.pdf")
        k2 = server._r2_object_key("co1", "p1", "plan.pdf", "/site/permits/plan.pdf")
        self.assertNotEqual(k1, k2)

    def test_the_same_path_always_yields_the_same_key(self):
        p = "/site/approved plans/plan.pdf"
        self.assertEqual(
            server._r2_object_key("co1", "p1", "plan.pdf", p),
            server._r2_object_key("co1", "p1", "plan.pdf", p),
        )

    def test_different_projects_never_share_a_key(self):
        self.assertNotEqual(
            server._r2_object_key("co1", "p1", "plan.pdf", "/a/plan.pdf"),
            server._r2_object_key("co1", "p2", "plan.pdf", "/a/plan.pdf"),
        )

    def test_a_direct_upload_gets_a_unique_object_every_time(self):
        """Direct uploads carry dropbox_path="". The name de-dup only checks
        rows that are not soft-deleted, so re-uploading the name of a
        soft-deleted file reused its key and clobbered the live object."""
        a = server._r2_object_key("co1", "p1", "plan.pdf", "")
        b = server._r2_object_key("co1", "p1", "plan.pdf", "")
        self.assertNotEqual(a, b, "two direct uploads of one name share an object")
        for k in (a, b):
            self.assertTrue(k.startswith("co1/p1/"))
            self.assertTrue(k.endswith("/plan.pdf"))


class ExistingRowsKeepOpening(unittest.TestCase):
    """THE MIGRATION HAZARD. Nothing may rewrite a key or move an object."""

    LEGACY = {
        "_id": "row1",
        "project_id": "proj1",
        "company_id": "co1",
        "name": "plan.pdf",
        "dropbox_path": "/site/approved plans/plan.pdf",
        "dropbox_content_hash": "hA",
        "r2_key": "co1/proj1/plan.pdf",          # the old flat shape
        "r2_url": "https://r2.example/co1/proj1/plan.pdf",
        "cache_version": 3,
    }

    def test_an_unchanged_legacy_row_is_never_rekeyed(self):
        h = _SyncHarness(
            [_file_entry("/Site/Approved Plans/plan.pdf", content_hash="hA")],
            existing_rows=[dict(self.LEGACY)],
        ).run()
        self.assertEqual(h.uploaded_keys, [], "an unchanged file was re-uploaded")
        for _flt, upd in h.updated:
            sets = upd.get("$set", {})
            self.assertNotIn("r2_key", sets,
                             "the legacy key was rewritten -- the object it "
                             "names was NOT moved, so the plan stops opening")

    def test_the_reader_resolves_from_the_stored_key_not_a_recomputed_one(self):
        """This is WHY no backfill is needed: stream_project_file reads
        rec['r2_key'] verbatim, so a legacy flat key and a new folder-scoped
        key both resolve through the same code path."""
        got = {}

        def _get_object(Bucket, Key):
            got["key"] = Key
            body = MagicMock()
            body.read = MagicMock(side_effect=[b"bytes", b""])
            return {"Body": body, "ContentType": "application/pdf",
                    "ContentLength": 5}

        db = MagicMock()
        db.project_files = MagicMock(
            find_one=AsyncMock(return_value=dict(self.LEGACY))
        )
        with patch.object(server, "db", db), \
             patch.object(server, "_r2_client", MagicMock(get_object=_get_object)), \
             patch.object(server, "R2_BUCKET_NAME", "bucket"), \
             patch.object(server, "ObjectId", lambda x: x), \
             patch.object(server, "_same_company_or_403", lambda rec, user: None):
            asyncio.run(server.stream_project_file(
                "proj1", "row1", {"id": "u1", "company_id": "co1"}
            ))
        self.assertEqual(
            got["key"], "co1/proj1/plan.pdf",
            "the legacy object is no longer the one fetched -- existing plans "
            "would stop opening",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 2. THE PAGINATION
# ═══════════════════════════════════════════════════════════════════════════

def _paged_dropbox(pages):
    """pages: list of (entries, has_more). Serves page 0 from list_folder and
    the rest from list_folder/continue."""
    state = {"i": 0}

    async def _call(company_id, method, url, **kwargs):
        if url.endswith("/files/list_folder"):
            state["i"] = 0
            ents, more = pages[0]
            return _Resp({"entries": ents, "has_more": more, "cursor": "c0"})
        if url.endswith("/files/list_folder/continue"):
            state["i"] += 1
            i = state["i"]
            if i < len(pages):
                ents, more = pages[i]
                return _Resp({"entries": ents, "has_more": more, "cursor": f"c{i}"})
            return _Resp({"entries": [], "has_more": False, "cursor": ""})
        if "get_temporary_link" in url:
            return _Resp({"link": "https://dl.example/x"})
        if "files/download" in url:
            return _Resp({}, 200, b"%PDF")
        return _Resp({}, 200)

    return _call


def _swallow_task(coro):
    """create_task stand-in: never schedules the background work."""
    try:
        coro.close()
    except Exception:
        pass
    return MagicMock()


class TheFolderPickerReturnsEveryPage(unittest.TestCase):
    """get_dropbox_folders feeds the folder-selection UI."""

    PAGES = [
        ([_folder_entry("Approved Plans"), _folder_entry("Permits")], True),
        ([_folder_entry("Submittals"), _folder_entry("RFIs")], True),
        ([_folder_entry("Closeout")], False),
    ]

    def _run(self):
        with patch.object(server, "dropbox_api_call",
                          AsyncMock(side_effect=_paged_dropbox(self.PAGES))), \
             patch.object(server, "get_user_company_id", lambda u: "co1"):
            return asyncio.run(server.get_dropbox_folders("", {"id": "u1"}))

    def test_every_folder_across_every_page_is_returned(self):
        names = {f["name"] for f in self._run()}
        self.assertEqual(
            names,
            {"Approved Plans", "Permits", "Submittals", "RFIs", "Closeout"},
            "the listing stopped at the first page -- folders that exist in "
            "Dropbox are simply absent from the picker",
        )


class TheSubfolderPickerReturnsEveryPage(unittest.TestCase):
    """THE ONE THAT LIMITS THE GATE TABLET. site_device_subfolders is set from
    exactly this list; a folder missing here can never be approved."""

    PAGES = [
        ([_folder_entry("Approved Plans")], True),
        ([_folder_entry("Permits")], True),
        ([_folder_entry("Safety")], False),
    ]

    def _run(self):
        db = MagicMock()
        db.projects = MagicMock(find_one=AsyncMock(return_value={
            "_id": "proj1", "company_id": "co1",
            "dropbox_folder_path": "/Site",
            "site_device_subfolders": ["Approved Plans"],
        }))
        with patch.object(server, "db", db), \
             patch.object(server, "dropbox_api_call",
                          AsyncMock(side_effect=_paged_dropbox(self.PAGES))), \
             patch.object(server, "get_user_company_id", lambda u: "co1"), \
             patch.object(server, "project_access_ok", lambda *a, **k: True), \
             patch.object(server, "to_query_id", lambda x: x):
            return asyncio.run(server.list_dropbox_subfolders("proj1", {"id": "u1"}))

    def test_every_subfolder_across_every_page_is_offered(self):
        out = self._run()
        self.assertEqual(
            sorted(out["subfolders"]), ["Approved Plans", "Permits", "Safety"],
            "a subfolder that exists in Dropbox was never rendered as a "
            "checkbox, so the gate tablet can never be approved to see it",
        )


class TheFileListingReturnsEveryPage(unittest.TestCase):

    PAGES = [
        ([_file_entry("/Site/a.pdf")], True),
        ([_file_entry("/Site/b.pdf")], True),
        ([_file_entry("/Site/c.pdf")], False),
    ]

    def _run(self):
        db = MagicMock()
        db.projects = MagicMock(find_one=AsyncMock(return_value={
            "_id": "proj1", "company_id": "co1", "dropbox_folder_path": "/Site",
            "site_device_subfolders": [],
        }))
        cur = MagicMock()
        cur.to_list = AsyncMock(return_value=[])          # no R2 cache yet
        db.project_files = MagicMock(find=MagicMock(return_value=cur))
        with patch.object(server, "db", db), \
             patch.object(server, "dropbox_api_call",
                          AsyncMock(side_effect=_paged_dropbox(self.PAGES))), \
             patch.object(server, "get_user_company_id", lambda u: "co1"), \
             patch.object(server, "project_access_ok", lambda *a, **k: True), \
             patch.object(server, "to_query_id", lambda x: x), \
             patch.object(server.asyncio, "create_task", _swallow_task):
            return asyncio.run(server.get_project_dropbox_files(
                "proj1", {"id": "u1", "role": "admin"}
            ))

    def test_every_file_across_every_page_is_listed(self):
        names = {f["name"] for f in self._run()}
        self.assertEqual(names, {"a.pdf", "b.pdf", "c.pdf"},
                         "the file list stopped at page one")


class TheSyncCountCountsEveryPage(unittest.TestCase):

    PAGES = [
        ([_file_entry("/Site/a.pdf")], True),
        ([_file_entry("/Site/b.pdf")], True),
        ([_file_entry("/Site/c.pdf")], False),
    ]

    def test_the_reported_file_count_covers_every_page(self):
        db = MagicMock()
        db.projects = MagicMock(find_one=AsyncMock(return_value={
            "_id": "proj1", "company_id": "co1", "dropbox_folder_path": "/Site",
        }))
        with patch.object(server, "db", db), \
             patch.object(server, "dropbox_api_call",
                          AsyncMock(side_effect=_paged_dropbox(self.PAGES))), \
             patch.object(server, "get_user_company_id", lambda u: "co1"), \
             patch.object(server, "project_access_ok", lambda *a, **k: True), \
             patch.object(server, "to_query_id", lambda x: x), \
             patch.object(server.asyncio, "create_task", _swallow_task):
            out = asyncio.run(server.sync_project_dropbox("proj1", {"id": "u1"}))
        self.assertEqual(out["file_count"], 3,
                         "the count under-reports -- it saw only page one")


class TheSyncItselfPagesAndIsBounded(unittest.TestCase):

    def test_the_sync_collects_every_page(self):
        pages = [
            ([_file_entry("/Site/x/a.pdf")], True),
            ([_file_entry("/Site/y/b.pdf")], True),
            ([_file_entry("/Site/z/c.pdf")], False),
        ]
        h = _SyncHarness(None, pages=pages).run()
        self.assertEqual(len(h.inserted), 3)

    def test_there_is_a_declared_page_bound(self):
        self.assertTrue(
            hasattr(server, "_DROPBOX_MAX_LIST_PAGES"),
            "the cursor loop has no stated bound -- a Dropbox that always "
            "returns has_more spins the worker forever",
        )
        self.assertIsInstance(server._DROPBOX_MAX_LIST_PAGES, int)
        self.assertGreater(server._DROPBOX_MAX_LIST_PAGES, 1)

    def test_a_server_that_always_says_has_more_still_terminates(self):
        """Pathological / buggy Dropbox. The loop must stop on its own."""
        calls = {"n": 0}

        async def _endless(company_id, method, url, **kwargs):
            if "list_folder" in url:
                calls["n"] += 1
                return _Resp({"entries": [_file_entry(f"/Site/f{calls['n']}.pdf")],
                              "has_more": True, "cursor": "c"})
            if "files/download" in url:
                return _Resp({}, 200, b"%PDF")
            return _Resp({}, 200)

        h = _SyncHarness([])
        with patch.object(server, "db", h.build_db()), \
             patch.object(server, "dropbox_api_call", AsyncMock(side_effect=_endless)), \
             patch.object(server, "_upload_to_r2", lambda b, k, c="": f"u/{k}"), \
             patch.object(server, "_r2_client", MagicMock()), \
             patch.object(server, "QWEN_API_KEY", ""), \
             patch.object(server, "to_query_id", lambda x: x):
            asyncio.run(server._sync_project_to_r2("proj1", "co1", "/Site"))

        self.assertLessEqual(
            calls["n"], server._DROPBOX_MAX_LIST_PAGES + 1,
            f"the cursor loop ran {calls['n']} times against a server that "
            "never stops saying has_more",
        )


if __name__ == "__main__":
    unittest.main()
