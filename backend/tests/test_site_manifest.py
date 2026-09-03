"""THE MANIFEST NAMES THE WHOLE APPROVED SET, OR IT SAYS THAT IT DOES NOT.

WHAT THE MANIFEST IS FOR. A fixed Android tablet is bolted to the gate. It has
to hold everything the project has approved it to see -- plans, documents and
submitted logbooks -- fill itself on first connection with nobody preparing it,
and still open all of it after a cold boot with the network down. To do that the
client needs ONE cheap read that names the complete approved set, so it can work
out what is missing, what has changed version, and what is no longer approved.

WHY TRUNCATION IS THE DANGEROUS PART, and why most of this file is about it.
The client's diff rule is "an id the manifest does not name is deleted locally".
That rule is only safe if the manifest is the WHOLE set. The read this manifest
replaces is not:

    GET /logbooks/project/{id}/submitted   ->  .to_list(500)      (server.py)

500 is a silent ceiling. A project past it returns its first 500 rows with
nothing in the response saying so, and no caller could tell a 500-row project
from a truncated 1300-row one. Pointed at a diff-and-delete client that is not a
missing feature, it is a cache shredder: every logbook past the cap reads as
"withdrawn" and the tablet deletes the compliance record a DOB inspector asks
for -- offline, where it cannot be fetched back.

So the manifest is paginated and it declares its own completeness, and BOTH are
asserted here:

  * every page carries `has_more` per section, so the client can walk to the
    end and actually obtain the whole set;
  * `complete` is true ONLY when this single response IS the entire approved
    set -- not on a first page with more behind it, and never on a page reached
    with a non-zero skip.

`complete` is deliberately not derivable from the rows. A client cannot tell a
short page from a complete one by counting, which is exactly how the 500 cap hid
for as long as it did.

THE VISIBILITY RULE IS REUSED, NOT REIMPLEMENTED. Which files a site device may
see is `projects.site_device_subfolders`, applied per-record in Python by
_path_is_under_allowed_subfolder because the comparison is case-insensitive,
relative to a base prefix stored on a different document, and against a list
normalised at read time -- none of which can be pushed into the Mongo query. A
second copy of that rule would be a second thing to get wrong, so the manifest
calls the same helper the listing endpoint calls, and the empty-list
short-circuit ("configured to see nothing" -> sees nothing) is asserted here as
well.

    python -m pytest backend/tests/test_site_manifest.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

SRC = (_BACKEND / "server.py").read_text(encoding="utf-8-sig")

PROJECT_ID = "proj1"
COMPANY_ID = "co1"
FOLDER = "/Projects/588 Thomas"


# ── Minimal async Mongo fakes ────────────────────────────────────────────────
#
# skip()/limit()/sort() are recorded rather than ignored: the whole point of the
# endpoint is that it pages, and a fake that silently returned every row would
# let an unpaginated implementation pass.

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

    def __aiter__(self):
        async def gen():
            for d in await self.to_list():
                yield d
        return gen()


class _FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.find_one_result = None

    async def find_one(self, *_a, **_k):
        r = self.find_one_result
        return r(*_a) if callable(r) else r

    def find(self, *_a, **_k):
        return _FakeCursor(self.docs)

    async def count_documents(self, *_a, **_k):
        return len(self.docs)


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


def _file_row(i, path, *, version=1, size=1000, name=None):
    return {
        "_id": f"f{i}",
        "project_id": PROJECT_ID,
        "company_id": COMPANY_ID,
        "dropbox_path": path,
        "name": name or path.rsplit("/", 1)[-1],
        "size": size,
        "cache_version": version,
        "r2_key": f"k{i}",
    }


def _log_row(i, *, date="2026-08-01", updated=None, submitted=None):
    row = {
        "_id": f"l{i}",
        "project_id": PROJECT_ID,
        "status": "submitted",
        "date": date,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    if submitted is not None:
        row["submitted_at"] = submitted
    if updated is not None:
        row["updated_at"] = updated
    return row


def _site_user():
    return {
        "id": "dev1",
        "role": "site_device",
        "site_mode": True,
        "project_id": PROJECT_ID,
        "company_id": COMPANY_ID,
    }


def _project(subfolders):
    return {
        "_id": PROJECT_ID,
        "name": "588 Thomas",
        "company_id": COMPANY_ID,
        "dropbox_folder_path": FOLDER,
        "site_device_subfolders": list(subfolders),
    }


def _call(*, files=(), logs=(), subfolders=("Approved Plans",),
          user=None, **kwargs):
    """Invoke the handler against a fake db. Returns the response dict."""
    handler = getattr(server, "get_project_manifest", None)
    if handler is None:
        raise AssertionError(
            "server.get_project_manifest does not exist — this tree has no "
            "site manifest endpoint"
        )
    db = _FakeDb(
        projects=_FakeCollection([]),
        project_files=_FakeCollection(list(files)),
        logbooks=_FakeCollection(list(logs)),
    )
    db.projects.find_one_result = _project(subfolders)
    # The handler is called directly rather than through TestClient, so FastAPI
    # never resolves its Query() defaults — pass real numbers for anything the
    # caller did not pin.
    kwargs.setdefault("limit", 1000)
    kwargs.setdefault("files_skip", 0)
    kwargs.setdefault("logbooks_skip", 0)
    original = server.db
    server.db = db
    try:
        return asyncio.run(handler(
            PROJECT_ID,
            current_user=user or _site_user(),
            **kwargs,
        ))
    finally:
        server.db = original


def _route_decorator(path: str) -> str:
    """The whole decorator, not its first line — a route with several
    dependencies is wrapped across lines and a first-line slice would read
    `@api_router.get(` and assert nothing."""
    needle = f'@api_router.get(\n    "{path}"'
    if needle not in SRC:
        needle = f'@api_router.get("{path}"'
    if needle not in SRC:
        raise AssertionError(f"no GET route declared for {path}")
    i = SRC.index(needle)
    end = SRC.index("async def", i)
    return SRC[i:end]


# ═══════════════════════════════════════════════════════════════════════════
# 1. THE ROUTE, AND THE TWO GATES IT MUST CARRY
# ═══════════════════════════════════════════════════════════════════════════

class TheRouteIsGated(unittest.TestCase):
    PATH = "/projects/{project_id}/manifest"

    def test_the_route_exists(self):
        self.assertTrue(hasattr(server, "get_project_manifest"),
                        "no manifest handler on server")

    def test_it_requires_an_approved_account(self):
        self.assertIn("Depends(require_approved)", _route_decorator(self.PATH))

    def test_it_requires_project_access(self):
        """The tablet is pinned to ONE project by project_access_ok's site
        branch. Without this dependency the path parameter alone would decide
        which project's approved set a gate device may enumerate."""
        self.assertIn("Depends(require_project_access)", _route_decorator(self.PATH))


# ═══════════════════════════════════════════════════════════════════════════
# 2. TRUNCATION CANNOT BE MISTAKEN FOR COMPLETENESS
#
#    The most important assertions in this stream. Everything else is a
#    convenience; these are what stand between a paging bug and a tablet that
#    deletes a compliance record underground.
# ═══════════════════════════════════════════════════════════════════════════

class TruncationIsAlwaysDeclared(unittest.TestCase):

    def test_a_whole_small_project_reports_complete(self):
        r = _call(
            files=[_file_row(1, f"{FOLDER}/Approved Plans/a.pdf")],
            logs=[_log_row(1)],
        )
        self.assertTrue(r["complete"])
        self.assertFalse(r["logbooks"]["has_more"])
        self.assertFalse(r["files"]["has_more"])

    def test_more_logbooks_than_the_page_holds_is_NOT_complete(self):
        """The 500-cap defect, reproduced against the new endpoint. A project
        with more submitted logs than one page holds must never answer
        `complete: true` — that answer is what authorises the client to delete."""
        r = _call(logs=[_log_row(i) for i in range(30)], limit=10)
        self.assertEqual(len(r["logbooks"]["rows"]), 10)
        self.assertTrue(r["logbooks"]["has_more"],
                        "a truncated section must say so")
        self.assertFalse(r["complete"],
                         "TRUNCATED MANIFEST REPORTED COMPLETE — this is the "
                         "cache-shredding bug")

    def test_more_files_than_the_page_holds_is_NOT_complete(self):
        r = _call(
            files=[_file_row(i, f"{FOLDER}/Approved Plans/{i}.pdf")
                   for i in range(30)],
            limit=10,
        )
        self.assertTrue(r["files"]["has_more"])
        self.assertFalse(r["complete"])

    def test_a_page_reached_by_skipping_is_never_complete(self):
        """Even the LAST page of a walk is not the whole set. `complete` means
        "this one response is everything", so any non-zero skip forfeits it —
        otherwise a client that fetched only page 2 of 2 would see
        `complete: true` and delete everything on page 1."""
        r = _call(logs=[_log_row(i) for i in range(15)],
                  limit=10, logbooks_skip=10)
        self.assertFalse(r["logbooks"]["has_more"], "page 2 of 2 ends the walk")
        self.assertFalse(r["complete"],
                         "a mid-walk page claimed to be the entire set")

    def test_the_walk_terminates_and_covers_every_row(self):
        """Paging is only a fix if the whole set is actually reachable. Walk it
        the way the client does and assert nothing is skipped or repeated."""
        logs = [_log_row(i) for i in range(47)]
        seen, skip, pages = [], 0, 0
        while True:
            r = _call(logs=logs, limit=10, logbooks_skip=skip)
            seen.extend(row["id"] for row in r["logbooks"]["rows"])
            pages += 1
            if not r["logbooks"]["has_more"]:
                break
            skip += 10
            self.assertLess(pages, 20, "the page walk did not terminate")
        self.assertEqual(len(seen), 47)
        self.assertEqual(len(set(seen)), 47, "a row was served on two pages")

    def test_the_section_reports_its_true_total(self):
        r = _call(logs=[_log_row(i) for i in range(30)], limit=10)
        self.assertEqual(r["logbooks"]["total"], 30,
                         "the total must describe the SET, not the page")

    def test_no_bare_to_list_cap_in_the_manifest_reader(self):
        """The defect this endpoint exists to avoid, asserted as source.

        `.to_list(500)` is how the submitted-logbooks read truncates in
        silence. A manifest built on any bare numeric to_list() cap has the
        same defect however carefully the response is shaped, so the reader is
        required to be limit-driven."""
        start = SRC.index("async def get_project_manifest(")
        nxt = SRC.find("\n@api_router.", start)
        body = SRC[start:nxt if nxt != -1 else len(SRC)]
        bare = re.findall(r"to_list\(\s*(\d+)\s*\)", body)
        self.assertEqual(
            bare, [],
            f"manifest reader has a hard-coded to_list cap: {bare}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3. THE APPROVED SET IS THE SAME SET THE LISTING ENDPOINT SERVES
# ═══════════════════════════════════════════════════════════════════════════

class ItServesExactlyWhatTheDeviceMaySee(unittest.TestCase):

    def test_no_configured_subfolders_means_no_files(self):
        """The safe default, and it must survive into the manifest: a device
        approved for nothing enumerates nothing. If this leaked, the tablet
        would download a project's whole Dropbox."""
        r = _call(
            files=[_file_row(1, f"{FOLDER}/Approved Plans/a.pdf")],
            subfolders=[],
        )
        self.assertEqual(r["files"]["rows"], [])
        self.assertEqual(r["files"]["total"], 0)
        self.assertFalse(r["files"]["has_more"])

    def test_only_files_under_an_allowed_subfolder_are_named(self):
        r = _call(files=[
            _file_row(1, f"{FOLDER}/Approved Plans/ok.pdf"),
            _file_row(2, f"{FOLDER}/Payroll/secret.pdf"),
            _file_row(3, f"{FOLDER}/Approved Plans/deep/also-ok.pdf"),
        ])
        got = {row["id"] for row in r["files"]["rows"]}
        self.assertEqual(got, {"f1", "f3"})

    def test_the_match_is_case_insensitive_like_the_listing(self):
        """Dropbox preserves case in `name` and lowercases `path_lower`; the
        shared helper normalises both sides. Asserted here because a manifest
        that reimplemented the comparison would plausibly get this wrong and
        silently approve nothing."""
        r = _call(files=[_file_row(1, f"{FOLDER.lower()}/approved plans/a.pdf")])
        self.assertEqual([row["id"] for row in r["files"]["rows"]], ["f1"])

    def test_it_calls_the_shared_visibility_helper(self):
        """Source assertion, because a second copy of this rule is a second
        thing to get wrong — and the two copies would drift apart silently."""
        start = SRC.index("async def get_project_manifest(")
        nxt = SRC.find("\n@api_router.", start)
        body = SRC[start:nxt if nxt != -1 else len(SRC)]
        self.assertIn("_path_is_under_allowed_subfolder", body)

    def test_an_admin_sees_the_whole_folder(self):
        """The subfolder rule is a SITE-DEVICE restriction. A CP or admin
        reading the same manifest is not narrowed by it."""
        admin = {"id": "u1", "role": "admin", "company_id": COMPANY_ID}
        r = _call(
            files=[
                _file_row(1, f"{FOLDER}/Approved Plans/a.pdf"),
                _file_row(2, f"{FOLDER}/Payroll/b.pdf"),
            ],
            subfolders=["Approved Plans"],
            user=admin,
        )
        self.assertEqual({row["id"] for row in r["files"]["rows"]}, {"f1", "f2"})

    def test_only_submitted_logbooks_are_named(self):
        """The manifest replaces the SUBMITTED read. A draft is not a filed
        record and must not be pulled onto an inspector-facing device."""
        start = SRC.index("async def get_project_manifest(")
        nxt = SRC.find("\n@api_router.", start)
        body = SRC[start:nxt if nxt != -1 else len(SRC)]
        self.assertIn('"status": "submitted"', body)
        self.assertIn('"is_deleted"', body)


# ═══════════════════════════════════════════════════════════════════════════
# 4. THE ROWS ARE THE ONES THE CLIENT CACHE ALREADY KEYS ON
#
#    The version in a row is not decoration: it is half of the on-disk
#    filename `{id}.{version}.{ext}`. A manifest whose version string differs
#    from the one the screen writes would make the tablet download every file
#    twice and keep both copies for ever.
# ═══════════════════════════════════════════════════════════════════════════

class TheVersionMatchesWhatTheCacheKeysOn(unittest.TestCase):

    def test_a_file_row_carries_id_version_and_size(self):
        r = _call(files=[_file_row(1, f"{FOLDER}/Approved Plans/a.pdf",
                                   version=7, size=4242)])
        row = r["files"]["rows"][0]
        self.assertEqual(row["id"], "f1")
        self.assertEqual(row["v"], 7)
        self.assertEqual(row["s"], 4242)

    def test_a_file_row_carries_its_extension(self):
        """The tablet renders PDFs and nothing else, so the store has to know
        which rows are worth pulling bytes for. The row is the only place that
        can say — a compact manifest carries no filename."""
        r = _call(files=[
            _file_row(1, f"{FOLDER}/Approved Plans/a.pdf"),
            _file_row(2, f"{FOLDER}/Approved Plans/b.DOCX"),
        ])
        by_id = {row["id"]: row for row in r["files"]["rows"]}
        self.assertEqual(by_id["f1"]["e"], "pdf")
        self.assertEqual(by_id["f2"]["e"], "docx", "extension must be folded")

    def test_a_missing_cache_version_reads_as_zero(self):
        """`?? 0` is the client's default for a record with no cache_version,
        and the on-disk name is built from it. The manifest has to agree."""
        row = _file_row(1, f"{FOLDER}/Approved Plans/a.pdf")
        row.pop("cache_version")
        r = _call(files=[row])
        self.assertEqual(r["files"]["rows"][0]["v"], 0)

    def test_a_logbook_version_prefers_updated_at(self):
        """docCache keys a logbook PDF on `updated_at || submitted_at ||
        created_at`, because an amendment bumps updated_at and the corrected
        PDF has to re-download. Same precedence, or the two writers name the
        same file differently."""
        updated = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        submitted = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        r = _call(logs=[_log_row(1, updated=updated, submitted=submitted)])
        self.assertEqual(r["logbooks"]["rows"][0]["v"], updated)

    def test_it_falls_back_to_submitted_then_created(self):
        submitted = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        r = _call(logs=[_log_row(1, submitted=submitted)])
        self.assertEqual(r["logbooks"]["rows"][0]["v"], submitted)

        r2 = _call(logs=[_log_row(1)])
        self.assertEqual(r2["logbooks"]["rows"][0]["v"],
                         datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_a_naive_timestamp_is_marked_utc(self):
        """serialize_id marks naive datetimes UTC before they reach the client,
        so `new Date()` parses them. The manifest writes the SAME string into
        the SAME filename; an unmarked one would be read as local time by the
        screen and produce a second on-disk copy."""
        naive = datetime(2026, 8, 9, 12, 0)
        r = _call(logs=[_log_row(1, updated=naive)])
        v = r["logbooks"]["rows"][0]["v"]
        self.assertEqual(getattr(v, "tzinfo", None), timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════
# 5. THE CLIENT BUILDS DOWNLOAD URLS FROM AN ID; THE SHAPES MUST MATCH
#
#    A compact row carries no url, so the store composes one. That is two
#    copies of a route literal in two languages, which nothing else in this
#    repo would catch — so it is caught here.
# ═══════════════════════════════════════════════════════════════════════════

class TheClientComposesTheRoutesThisServerServes(unittest.TestCase):
    STORE = (_BACKEND.parent / "frontend" / "src" / "utils"
             / "siteManifestStore.js")

    def setUp(self):
        if not self.STORE.exists():
            self.skipTest("site manifest store not present in this tree")
        self.js = self.STORE.read_text(encoding="utf-8")

    def test_the_file_content_path_matches(self):
        self.assertIn("/api/projects/", self.js)
        self.assertIn("/files/", self.js)
        self.assertIn("/content", self.js)
        self.assertIn('f"/api/projects/{project_id}/files/{rec_id}/content"', SRC)

    def test_the_logbook_pdf_path_matches(self):
        self.assertIn("/api/reports/logbook/", self.js)
        self.assertIn("/pdf", self.js)
        self.assertIn('@api_router.get("/reports/logbook/{logbook_id}/pdf")', SRC)

    def test_no_token_is_ever_put_in_a_url(self):
        """docCache sends the JWT in the Authorization header. A url-borne
        token leaks into history, crash logs and the share sheet."""
        self.assertNotIn("token=", self.js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
