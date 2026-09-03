"""A VISIBILITY RULE NOBODY CAN SATISFY IS WORSE THAN A RULE THAT SAYS NO.

Two shipped defects, both in `_path_is_under_allowed_subfolder`, both ending in
the same place: a gate tablet showing an empty screen with no admin action that
could ever fill it.

DEFECT A — A FILE UPLOADED THROUGH THE APP IS INVISIBLE BY CONSTRUCTION.
`upload_project_file` stores `dropbox_path: ""` and an `r2_key`; it never went
near Dropbox, so it has no Dropbox path and never will. The helper opens with

    if not file_path or not allowed_subfolders: return False

so every app-uploaded file on every project answered False for every possible
value of site_device_subfolders. Production has such rows -- `shed-1.pdf` on
588 Thomas S Boyland Street is one. That is not an operator who ticked the
wrong box: the rule is keyed on a path direct uploads do not have, so no box
exists to tick. The fix is not to publish those files, it is to make them
ADDRESSABLE: they answer to a reserved folder name
(`server.APP_UPLOADS_VIRTUAL_FOLDER`) which an admin selects exactly as they
select a real Dropbox subfolder, and until they do, the file stays invisible.
No auto-publish -- asserted below, twice.

DEFECT B — SELECTING THE BASE FOLDER AS ITS OWN SUBFOLDER MATCHED NOTHING.
With the operator's real config

    dropbox_folder_path    = '/588 plans'
    site_device_subfolders = ['588 plans']

the helper strips the base prefix FIRST, so `/588 plans/A-101.pdf` becomes the
relative `A-101.pdf`, which is compared against `588 plans` and matches
nothing. The selection was read as "a folder named 588 plans INSIDE /588 plans"
-- a folder that does not exist. An admin ticking the project's own folder
plainly means everything under it, so that is what it now means.

WHAT THE FIX MUST NOT DO. Widen. The safe default (nothing configured -> the
device sees nothing) and the refusal of a non-selected sibling folder are
asserted here alongside the fixes, because a rule that fails open is a worse
defect than either of the two being repaired.

BOTH ENDPOINTS. The listing endpoint and the manifest call the same helper
deliberately. A manifest that still hid the file would leave the tablet's
offline store empty even with the listing repaired, so every visibility claim
here is asserted through BOTH.

    python -m pytest backend/tests/test_site_device_file_visibility.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

PROJECT_ID = "proj1"
COMPANY_ID = "co1"

# The operator's literal production values for defect B.
OP_FOLDER = "/588 plans"
OP_SUBFOLDER = "588 plans"

# The operator's literal production row for defect A.
SHED_R2_KEY = (
    "6a5e153cc7ac7a6451aa2d32/6a5f63bc147407d3261df2c7/"
    "588 Thomas S Boyland Street shed-1.pdf"
)

# Read through getattr so a PRISTINE tree fails these tests on assertions
# rather than blowing up at import and reporting nothing about the defect.
UPLOADS = getattr(server, "APP_UPLOADS_VIRTUAL_FOLDER", "Uploaded in App")


# ── Minimal async Mongo fakes ────────────────────────────────────────────────
#
# The matcher below understands only the handful of operators these three
# handlers actually issue. It exists rather than a fake that returns every row
# because one of the assertions here is a NEGATIVE one — a project with no
# pathless rows must not be offered the uploads folder — and a count that
# ignored its query would make that assertion vacuous.

def _match(doc, query):
    for key, cond in (query or {}).items():
        val = doc.get(key)
        if isinstance(cond, dict):
            if "$ne" in cond and val == cond["$ne"]:
                return False
            if "$in" in cond and val not in cond["$in"]:
                return False
            if "$nin" in cond and val in cond["$nin"]:
                return False
        elif val != cond:
            return False
    return True


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._skip = 0
        self._limit = None

    def sort(self, *_a, **_k):
        return self

    def skip(self, n):
        self._skip = int(n or 0)
        return self

    def limit(self, n):
        self._limit = int(n or 0) or None
        return self

    async def to_list(self, length=None):
        out = self._docs[self._skip:]
        if self._limit is not None:
            out = out[: self._limit]
        if length is not None:
            out = out[:length]
        return list(out)


class _FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.find_one_result = None

    async def find_one(self, *_a, **_k):
        r = self.find_one_result
        return r(*_a) if callable(r) else r

    def find(self, query=None, *_a, **_k):
        return _FakeCursor([d for d in self.docs if _match(d, query)])

    async def count_documents(self, query=None, *_a, **_k):
        return len([d for d in self.docs if _match(d, query)])


class _FakeDb:
    def __init__(self, **collections):
        self._c = dict(collections)

    def _get(self, name):
        if name not in self._c:
            self._c[name] = _FakeCollection([])
        return self._c[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._get(name)

    def __getitem__(self, name):
        return self._get(name)


# ── Rows ─────────────────────────────────────────────────────────────────────

def _synced_file(i, path):
    """A row written by the Dropbox sync: it has a real dropbox_path."""
    return {
        "_id": f"f{i}",
        "project_id": PROJECT_ID,
        "company_id": COMPANY_ID,
        "dropbox_path": path,
        "name": path.rsplit("/", 1)[-1],
        "size": 1000,
        "cache_version": 1,
        "r2_key": f"k{i}",
        "source": "dropbox_sync",
    }


def _app_upload(i, name="shed-1.pdf", r2_key=SHED_R2_KEY):
    """The production shape of a file uploaded through the app: NO Dropbox
    path at all, and an r2_key that proves the bytes exist."""
    return {
        "_id": f"u{i}",
        "project_id": PROJECT_ID,
        "company_id": COMPANY_ID,
        "dropbox_path": "",
        "name": name,
        "size": 2000,
        "cache_version": 1,
        "r2_key": r2_key,
        "source": "direct_upload",
    }


def _site_user():
    return {
        "id": "dev1",
        "role": "site_device",
        "site_mode": True,
        "project_id": PROJECT_ID,
        "company_id": COMPANY_ID,
    }


def _project(folder, subfolders):
    return {
        "_id": PROJECT_ID,
        "name": "588 Thomas",
        "company_id": COMPANY_ID,
        "dropbox_folder_path": folder,
        "site_device_subfolders": list(subfolders),
    }


def _run(handler_name, *, files, folder, subfolders, user=None, **kwargs):
    handler = getattr(server, handler_name, None)
    if handler is None:
        raise AssertionError(f"server.{handler_name} does not exist")
    db = _FakeDb(
        projects=_FakeCollection([]),
        project_files=_FakeCollection(list(files)),
        logbooks=_FakeCollection([]),
    )
    db.projects.find_one_result = _project(folder, subfolders)
    original = server.db
    server.db = db
    try:
        return asyncio.run(handler(
            PROJECT_ID, current_user=user or _site_user(), **kwargs
        ))
    finally:
        server.db = original


def listing_ids(*, files, folder, subfolders, user=None):
    """Ids the LISTING endpoint serves to this caller."""
    rows = _run("get_project_dropbox_files", files=files, folder=folder,
                subfolders=subfolders, user=user)
    return {str(r.get("id") or "") for r in rows}


def manifest_ids(*, files, folder, subfolders, user=None):
    """Ids the MANIFEST names to this caller."""
    r = _run("get_project_manifest", files=files, folder=folder,
             subfolders=subfolders, user=user,
             limit=1000, files_skip=0, logbooks_skip=0)
    return {row["id"] for row in r["files"]["rows"]}


def both_endpoints_serve(testcase, expected, *, files, folder, subfolders,
                         user=None, msg=""):
    """Every visibility claim is made through BOTH readers. The manifest is
    what fills the tablet's offline store; the listing is what the screen
    renders. A fix present in one and absent from the other still ends in an
    empty gate screen, so neither is asserted alone."""
    testcase.assertEqual(
        listing_ids(files=files, folder=folder, subfolders=subfolders, user=user),
        expected, f"LISTING endpoint: {msg}")
    testcase.assertEqual(
        manifest_ids(files=files, folder=folder, subfolders=subfolders, user=user),
        expected, f"MANIFEST endpoint: {msg}")


# ═══════════════════════════════════════════════════════════════════════════
# 1. DEFECT A — AN APP UPLOAD IS REACHABLE, NOT AUTO-PUBLISHED
# ═══════════════════════════════════════════════════════════════════════════

class AnAppUploadCanBeSelected(unittest.TestCase):

    def test_there_is_a_name_an_admin_can_select_pathless_files_by(self):
        """Defect A is not "the operator ticked the wrong box" — before this
        constant there was no box. The reserved name is the whole mechanism."""
        self.assertTrue(
            hasattr(server, "APP_UPLOADS_VIRTUAL_FOLDER"),
            "no reserved folder name exists, so a file with dropbox_path='' "
            "cannot be selected by any admin action",
        )
        self.assertTrue(str(getattr(server, "APP_UPLOADS_VIRTUAL_FOLDER", "")).strip())

    def test_the_helper_no_longer_refuses_every_pathless_file_outright(self):
        """The literal defect: `if not file_path ... return False` made the
        answer False for every possible configuration."""
        visible = server._path_is_under_allowed_subfolder(
            server._visibility_path_for_record(_app_upload(1)),
            OP_FOLDER, [UPLOADS],
        )
        self.assertTrue(
            visible,
            "an app-uploaded file is invisible under EVERY selection — "
            "there is no admin action that could reveal it",
        )

    def test_selected_the_production_shed_pdf_reaches_the_tablet(self):
        """The operator's real row: dropbox_path '' plus a valid r2_key."""
        both_endpoints_serve(
            self, {"u1"},
            files=[_app_upload(1)],
            folder=OP_FOLDER, subfolders=[UPLOADS],
            msg="shed-1.pdf stayed invisible with its folder selected",
        )

    def test_NOT_selected_it_stays_invisible__no_auto_publish(self):
        """The operator's ruling is "no auto-publish". Reachable is not
        published: with a real Dropbox subfolder ticked and the uploads folder
        NOT ticked, an app upload is still refused."""
        both_endpoints_serve(
            self, set(),
            files=[_app_upload(1)],
            folder=OP_FOLDER, subfolders=["Approved Plans"],
            msg="an app upload published itself into an unrelated selection",
        )

    def test_selecting_the_base_folder_does_not_sweep_in_app_uploads(self):
        """Defect B's fix must not become defect A's back door. An admin who
        ticks the project's Dropbox folder chose what is IN that folder; an app
        upload was never in it and is not implied by that choice."""
        both_endpoints_serve(
            self, {"f1"},
            files=[_synced_file(1, f"{OP_FOLDER}/A-101.pdf"), _app_upload(2)],
            folder=OP_FOLDER, subfolders=[OP_SUBFOLDER],
            msg="ticking the base folder silently published app uploads too",
        )

    def test_a_pathless_row_with_no_bytes_is_not_selectable(self):
        """A row with neither a Dropbox path nor an r2_key names no file. It
        must not be conjured into the uploads folder as a broken entry."""
        orphan = _app_upload(9)
        orphan["r2_key"] = ""
        both_endpoints_serve(
            self, set(),
            files=[orphan], folder=OP_FOLDER, subfolders=[UPLOADS],
            msg="a row with no bytes was offered to the tablet",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 2. DEFECT B — THE BASE FOLDER SELECTED AS ITS OWN SUBFOLDER
# ═══════════════════════════════════════════════════════════════════════════

class SelectingTheBaseFolderMeansEverythingUnderIt(unittest.TestCase):
    """Executed against the operator's literal shipped configuration."""

    def test_a_file_at_the_top_of_the_base_folder_is_visible(self):
        both_endpoints_serve(
            self, {"f1"},
            files=[_synced_file(1, f"{OP_FOLDER}/A-101.pdf")],
            folder=OP_FOLDER, subfolders=[OP_SUBFOLDER],
            msg="/588 plans/A-101.pdf hidden with '588 plans' selected",
        )

    def test_a_file_nested_below_the_base_folder_is_visible(self):
        both_endpoints_serve(
            self, {"f2"},
            files=[_synced_file(2, f"{OP_FOLDER}/structural/S-200.pdf")],
            folder=OP_FOLDER, subfolders=[OP_SUBFOLDER],
            msg="/588 plans/structural/S-200.pdf hidden with '588 plans' selected",
        )

    def test_the_full_base_path_selects_the_same_set(self):
        """An admin (or a script) may name the base by its stored path rather
        than its bare name. _normalize_subfolder_names strips the slashes, so
        the two spellings must land on the same rule."""
        both_endpoints_serve(
            self, {"f1"},
            files=[_synced_file(1, f"{OP_FOLDER}/A-101.pdf")],
            folder=OP_FOLDER, subfolders=[OP_FOLDER],
            msg="the base named by its full path selected nothing",
        )

    def test_it_does_not_reach_outside_the_base_folder(self):
        """"Everything under the base" is bounded by the base. A sibling folder
        that merely shares the prefix is not under it."""
        both_endpoints_serve(
            self, {"f1"},
            files=[
                _synced_file(1, f"{OP_FOLDER}/A-101.pdf"),
                _synced_file(2, "/588 plans archive/old.pdf"),
            ],
            folder=OP_FOLDER, subfolders=[OP_SUBFOLDER],
            msg="a sibling folder sharing the base's prefix leaked",
        )

    def test_a_deeper_base_selected_by_its_leaf_name(self):
        """The base is not always a single path segment."""
        both_endpoints_serve(
            self, {"f1"},
            files=[_synced_file(1, "/Projects/588 plans/A-101.pdf")],
            folder="/Projects/588 plans", subfolders=["588 plans"],
            msg="the base's leaf name did not select the base",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3. THE SAFE DEFAULT SURVIVES BOTH FIXES
#
#    These passed before the fixes and must still pass after. A widening
#    regression here is worse than either defect being repaired.
# ═══════════════════════════════════════════════════════════════════════════

class NothingWidened(unittest.TestCase):

    def test_a_genuinely_below_subfolder_still_works(self):
        both_endpoints_serve(
            self, {"f1", "f3"},
            files=[
                _synced_file(1, f"{OP_FOLDER}/Approved Plans/ok.pdf"),
                _synced_file(2, f"{OP_FOLDER}/Payroll/secret.pdf"),
                _synced_file(3, f"{OP_FOLDER}/Approved Plans/deep/also-ok.pdf"),
            ],
            folder=OP_FOLDER, subfolders=["Approved Plans"],
            msg="the ordinary subfolder rule broke",
        )

    def test_a_file_under_a_non_selected_subfolder_is_still_refused(self):
        both_endpoints_serve(
            self, set(),
            files=[_synced_file(2, f"{OP_FOLDER}/Payroll/secret.pdf")],
            folder=OP_FOLDER, subfolders=["Approved Plans"],
            msg="a non-selected sibling folder leaked to the gate",
        )

    def test_no_subfolders_configured_means_the_device_sees_nothing(self):
        """The safe default, asserted against BOTH kinds of row — a Dropbox
        file and an app upload — because the uploads folder is a new way in."""
        both_endpoints_serve(
            self, set(),
            files=[
                _synced_file(1, f"{OP_FOLDER}/Approved Plans/ok.pdf"),
                _app_upload(2),
            ],
            folder=OP_FOLDER, subfolders=[],
            msg="a device approved for nothing was served files",
        )

    def test_the_helper_itself_refuses_when_nothing_is_configured(self):
        """Asserted at the HELPER, not only through the endpoints.

        Both callers short-circuit on an empty list before the helper is ever
        reached, so an endpoint-level test of the safe default passes even with
        the helper's own `not allowed_subfolders -> False` deleted. That was
        found by a mutation control: inverting the helper's guard to return
        True broke nothing. The rule is defended in depth here, because the
        short-circuits are an optimisation (don't issue the query) and the
        helper is the actual rule."""
        for path in (
            f"{OP_FOLDER}/Approved Plans/a.pdf",
            f"{OP_FOLDER}/A-101.pdf",
            f"/{UPLOADS}/shed-1.pdf",
        ):
            self.assertFalse(
                server._path_is_under_allowed_subfolder(path, OP_FOLDER, []),
                f"an empty selection approved {path}",
            )

    def test_the_match_is_still_case_insensitive(self):
        both_endpoints_serve(
            self, {"f1"},
            files=[_synced_file(1, f"{OP_FOLDER.lower()}/approved plans/a.pdf")],
            folder=OP_FOLDER, subfolders=["Approved Plans"],
            msg="the case-insensitive comparison regressed",
        )

    def test_an_admin_is_not_narrowed_by_any_of_this(self):
        """The subfolder rule is a SITE-DEVICE restriction throughout."""
        admin = {"id": "u1", "role": "admin", "company_id": COMPANY_ID}
        both_endpoints_serve(
            self, {"f1", "f2", "u3"},
            files=[
                _synced_file(1, f"{OP_FOLDER}/Approved Plans/a.pdf"),
                _synced_file(2, f"{OP_FOLDER}/Payroll/b.pdf"),
                _app_upload(3),
            ],
            folder=OP_FOLDER, subfolders=["Approved Plans"], user=admin,
            msg="an admin was narrowed by the site-device rule",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 4. THE SELECTION AN ADMIN MUST MAKE IS ACTUALLY OFFERED
#
#    Defect A is only half repaired by making the file addressable. If the
#    admin screen never offers the name, the rule is still one nobody can
#    satisfy — which is the whole complaint. The subfolder picker is fed by
#    /projects/{id}/dropbox-subfolders, so that is where the name must appear.
# ═══════════════════════════════════════════════════════════════════════════

class TheUploadsFolderIsOfferedToTheAdmin(unittest.TestCase):

    def _subfolders(self, *, files, folder):
        db = _FakeDb(
            projects=_FakeCollection([]),
            project_files=_FakeCollection(list(files)),
        )
        db.projects.find_one_result = _project(folder, [])
        admin = {"id": "a1", "role": "admin", "company_id": COMPANY_ID}
        original = server.db
        server.db = db
        try:
            r = asyncio.run(
                server.list_dropbox_subfolders(PROJECT_ID, current_user=admin)
            )
        finally:
            server.db = original
        return r.get("subfolders") or []

    def test_a_project_with_app_uploads_offers_the_uploads_folder(self):
        self.assertIn(
            UPLOADS, self._subfolders(files=[_app_upload(1)], folder=OP_FOLDER),
            "the admin is never shown the one name that reveals app uploads",
        )

    def test_it_is_offered_even_when_no_dropbox_folder_is_linked(self):
        """A project that has only ever had app uploads has no linked folder,
        and that early return used to answer with an empty list — the exact
        project where every file is invisible."""
        self.assertIn(
            UPLOADS, self._subfolders(files=[_app_upload(1)], folder=""),
            "an unlinked project offers no selectable folder at all",
        )

    def test_a_project_with_no_app_uploads_is_not_offered_a_phantom_folder(self):
        self.assertNotIn(
            UPLOADS,
            self._subfolders(files=[_synced_file(1, f"{OP_FOLDER}/a.pdf")],
                             folder=OP_FOLDER),
            "a folder holding nothing was offered as a choice",
        )


if __name__ == "__main__":
    unittest.main()
