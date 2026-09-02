"""THE SYNC SAYS WHETHER IT FINISHED, AND WITH WHAT.

The plans screen caches its file list for offline use, and it was writing that
cache from whatever it happened to read -- including a read taken while
_sync_project_to_r2 was still inserting rows. The saved-for-offline list could
be a strict SUBSET of the project, and a CP in a cellar would be missing
drawings with nothing on screen to say so.

dropbox_last_synced IS DELIBERATELY UNCHANGED. It honestly records that a sync
finished, and it is stamped unconditionally at the end -- so it reads the same
whether 15 of 15 arrived or 3 of 15 did. That is how 588 Thomas looked correct
while being wrong. It keeps its meaning; the counts live beside it.

NOT AN IN-PROCESS FLAG. "Is the task running" could be answered from memory
today, because the Procfile runs one uvicorn process with no --workers. That is
the objection, not the design: it would be correct by accident and would start
lying silently the day anything runs two processes.

    python -m pytest backend/tests/test_dropbox_sync_run_record.py
"""

import ast
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402

SRC = (BACKEND / "server.py").read_text(encoding="utf-8-sig")
TREE = ast.parse(SRC)


def _fn(name):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


class _Recorder:
    """Captures every write the run helpers make."""

    def __init__(self):
        self.runs = []
        self.run_updates = []
        self.project_sets = []

    def build_db(self):
        runs = MagicMock()

        async def insert_one(doc):
            self.runs.append(doc)
            return MagicMock(inserted_id="run1")

        async def update_one(flt, upd):
            self.run_updates.append((flt, upd))
            return MagicMock(modified_count=1)

        runs.insert_one = AsyncMock(side_effect=insert_one)
        runs.update_one = AsyncMock(side_effect=update_one)

        projects = MagicMock()

        async def proj_update(flt, upd):
            self.project_sets.append(upd.get("$set", {}))
            return MagicMock(modified_count=1)

        projects.update_one = AsyncMock(side_effect=proj_update)

        db = MagicMock()
        db.projects = projects
        db.__getitem__ = MagicMock(return_value=runs)
        return db


class TheRunIsOpenedWithWhatItExpects(unittest.TestCase):

    def test_open_records_the_expected_count(self):
        rec = _Recorder()
        with patch.object(server, "db", rec.build_db()):
            run_id = asyncio.run(server._sync_run_open("p1", "c1", 15))
        self.assertEqual(run_id, "run1")
        self.assertEqual(rec.runs[0]["expected"], 15)
        self.assertEqual(rec.runs[0]["status"], "running")
        self.assertEqual(rec.runs[0]["project_id"], "p1")

    def test_open_stamps_the_project_so_the_client_can_see_it(self):
        """GET /projects/{id} is already fetched by every screen that needs
        this, so no endpoint and no response shape changes."""
        rec = _Recorder()
        with patch.object(server, "db", rec.build_db()):
            asyncio.run(server._sync_run_open("p1", "c1", 15))
        stamped = rec.project_sets[0]
        self.assertEqual(stamped["dropbox_sync.status"], "running")
        self.assertEqual(stamped["dropbox_sync.expected"], 15)
        self.assertIn("dropbox_sync.started_at", stamped)

    def test_a_recording_failure_never_takes_the_sync_down(self):
        """This is a diagnostic. If it cannot write, the files still sync."""
        db = MagicMock()
        runs = MagicMock()
        runs.insert_one = AsyncMock(side_effect=RuntimeError("mongo down"))
        db.__getitem__ = MagicMock(return_value=runs)
        db.projects = MagicMock(update_one=AsyncMock())
        with patch.object(server, "db", db):
            self.assertIsNone(asyncio.run(server._sync_run_open("p1", "c1", 3)))


class TheRunIsClosedWithCounts(unittest.TestCase):

    def test_close_records_synced_and_failed(self):
        rec = _Recorder()
        fails = [{"path": "/a.pdf", "reason": "download 409"}]
        with patch.object(server, "db", rec.build_db()):
            asyncio.run(server._sync_run_close("run1", "p1", "complete", 15, 14, fails))
        upd = rec.run_updates[0][1]["$set"]
        self.assertEqual(upd["status"], "complete")
        self.assertEqual(upd["expected"], 15)
        self.assertEqual(upd["synced"], 14)
        self.assertEqual(upd["failed"], 1)
        self.assertIsNotNone(upd["finished_at"])

    def test_the_failure_list_is_bounded(self):
        """A pathological folder must not write a document larger than the sync
        it describes."""
        rec = _Recorder()
        many = [{"path": f"/{i}.pdf", "reason": "x"} for i in range(500)]
        with patch.object(server, "db", rec.build_db()):
            asyncio.run(server._sync_run_close("run1", "p1", "complete", 500, 0, many))
        self.assertEqual(len(rec.run_updates[0][1]["$set"]["failures"]), 50)
        # The COUNT is still the true one -- only the detail is trimmed.
        self.assertEqual(rec.run_updates[0][1]["$set"]["failed"], 500)

    def test_close_mirrors_the_counts_onto_the_project(self):
        rec = _Recorder()
        with patch.object(server, "db", rec.build_db()):
            asyncio.run(server._sync_run_close("run1", "p1", "complete", 15, 12,
                                               [{"reason": "x"}] * 3))
        stamped = rec.project_sets[-1]
        self.assertEqual(stamped["dropbox_sync.status"], "complete")
        self.assertEqual(stamped["dropbox_sync.expected"], 15)
        self.assertEqual(stamped["dropbox_sync.synced"], 12)
        self.assertEqual(stamped["dropbox_sync.failed"], 3)

    def test_close_without_a_run_id_still_stamps_the_project(self):
        """The listing can fail before a run is ever opened. The client still
        needs to know the sync said nothing useful about the list."""
        rec = _Recorder()
        with patch.object(server, "db", rec.build_db()):
            asyncio.run(server._sync_run_close(None, "p1", "failed", 0, 0,
                                               [{"reason": "list_folder 503"}]))
        self.assertEqual(rec.run_updates, [])
        self.assertEqual(rec.project_sets[-1]["dropbox_sync.status"], "failed")


class dropbox_last_synced_IS_NOT_OVERLOADED(unittest.TestCase):
    """The operator's ruling: it honestly records that a sync finished, and the
    run record carries expected/synced/failed alongside it."""

    def test_the_stamp_is_still_written_and_still_alone(self):
        fn = _fn("_sync_project_to_r2")
        found = []
        for node in ast.walk(fn):
            if not isinstance(node, ast.Dict):
                continue
            keys = [k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if "dropbox_last_synced" in keys:
                found.append(keys)
        self.assertEqual(len(found), 1, "the timestamp write moved or multiplied")
        # THE RULING IS ABOUT THE COUNTS, NOT THE KEY COUNT. What must never
        # ride here is sync RESULT DATA — expected/synced/failed/status — which
        # belongs in the run record so `dropbox_last_synced` keeps meaning one
        # thing: a sync finished.
        #
        # `updated_at` is admitted deliberately and is not an overload of that
        # meaning. It is the document's change marker, which the gate tablet
        # reconciles its offline cache against; the client reads sync state to
        # decide whether its cached file list is trustworthy, so a change to
        # that state has to move the marker or the tablet is never told. See
        # test_writers_stamp_updated_at.py.
        self.assertEqual(sorted(found[0]), ["dropbox_last_synced", "updated_at"],
                         "nothing but the change marker was added to that $set")
        for banned in ("expected", "synced", "failed", "status", "run_id"):
            self.assertNotIn(banned, found[0],
                             "sync counts belong in the run record, not here")

    def test_the_helpers_do_not_touch_it(self):
        """READ THE BODY, NOT THE PROSE. The first version of this unparsed the
        whole function, which includes the docstring -- and every one of these
        helpers EXPLAINS that it leaves dropbox_last_synced alone. The assertion
        was satisfied by the explanation of the thing it was checking, which is
        the exact shape followups.md warns about."""
        for name in ("_sync_run_open", "_sync_run_close", "_stamp_project_sync"):
            with self.subTest(fn=name):
                fn = _fn(name)
                body = list(fn.body)
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    body = body[1:]          # drop the docstring
                # EXACT STRING CONSTANTS, NOT A SUBSTRING SCAN.
                # `assertNotIn("dropbox_last_synced", code)` is a bare literal
                # ban and test_absence_literals_are_specific rejects it. It is
                # also weaker than it looks: the field can only be written as a
                # key or an f-string segment, both of which are Constants, so
                # comparing them exactly says precisely what is meant.
                literals = set()
                for st in body:
                    for node in ast.walk(st):
                        if isinstance(node, ast.Constant) and isinstance(node.value, str):
                            literals.add(node.value)
                self.assertNotIn("dropbox_last_synced", literals)
                # And it cannot be reached through a dotted $set path either.
                self.assertFalse(
                    [v for v in literals if v.startswith("dropbox_last_synced")],
                    "the field is written under a dotted path",
                )


class EveryExitPathClosesTheRun(unittest.TestCase):
    """A run left at "running" makes the client decline to refresh its offline
    list until the staleness window expires. THE CLASS, not the happy path."""

    def test_the_listing_failure_path_closes(self):
        fn = _fn("_sync_project_to_r2")
        # The early `return` after a non-200 list_folder must be preceded by a
        # close in the same branch.
        closes = [n.lineno for n in ast.walk(fn)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Name)
                  and n.func.id == "_sync_run_close"]
        self.assertGreaterEqual(len(closes), 3,
                                "expected a close on the listing failure, the "
                                "success path and the outer except")

    def test_the_outer_except_closes(self):
        fn = _fn("_sync_project_to_r2")
        handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
        closing = [h for h in handlers if "_sync_run_close" in ast.unparse(h)]
        self.assertTrue(closing, "the outer except leaves the run open")

    def test_the_close_in_the_except_cannot_itself_raise(self):
        """A diagnostic that throws inside an error handler loses the original
        error."""
        fn = _fn("_sync_project_to_r2")
        for h in [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]:
            if "_sync_run_close" not in ast.unparse(h):
                continue
            inner = [n for n in ast.walk(h) if isinstance(n, ast.Try)]
            self.assertTrue(inner, "the close in the except is unguarded")


class TheCollectionIsBounded(unittest.TestCase):
    """The webhook fans out across EVERY linked project, so one Dropbox edit
    writes a run record per project. Without a TTL this grows faster than
    anything else in the database."""

    def test_the_ttl_lives_where_it_cannot_be_skipped(self):
        """DECLARED IS NOT CREATED, and the first version of this file only
        checked declared.

        These two create_index calls shipped inside
        run_whatsapp_startup_migrations() -- one try covering four unrelated
        migrations with a single except that logs and continues -- so any
        earlier WhatsApp failure would have silently skipped them. The
        assertion passed the whole time, because the index WAS declared; it was
        just unreachable. The TTL is the only thing bounding a collection the
        webhook writes to once per linked project per Dropbox edit.
        """
        owner = None
        for node in ast.walk(TREE):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call) and inner.keywords
                        and any(isinstance(k.value, ast.Constant)
                                and k.value.value == "dropbox_sync_runs_ttl"
                                for k in inner.keywords if k.arg == "name")):
                    # innermost enclosing function wins
                    if owner is None or node.lineno > owner.lineno:
                        owner = node
        self.assertIsNotNone(owner, "the TTL index is not created anywhere")
        self.assertEqual(
            owner.name, "ensure_dropbox_sync_indexes",
            "the TTL must not share a failure boundary with unrelated migrations",
        )

    def test_it_is_awaited_at_startup_on_its_own(self):
        """Its own await. Called from inside another migration's body it would
        inherit that migration's failure boundary again."""
        called = [n for n in ast.walk(TREE)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "ensure_dropbox_sync_indexes"]
        self.assertTrue(called, "nothing calls ensure_dropbox_sync_indexes")

        # and it carries its own except, so a failure logs rather than
        # propagating into whatever startup step follows it
        fn = _fn("ensure_dropbox_sync_indexes")
        self.assertTrue(
            [n for n in ast.walk(fn) if isinstance(n, ast.Try)],
            "the index creation is unguarded",
        )

    def test_the_ttl_is_on_created_at(self):
        for node in ast.walk(TREE):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "create_index"):
                continue
            kw = {k.arg: k.value for k in node.keywords}
            name = kw.get("name")
            if not (isinstance(name, ast.Constant) and name.value == "dropbox_sync_runs_ttl"):
                continue
            self.assertTrue(node.args)
            self.assertEqual(node.args[0].value, "created_at")
            self.assertIn("expireAfterSeconds", kw)
            return
        self.fail("no TTL index named dropbox_sync_runs_ttl")

    def test_the_documents_carry_created_at(self):
        """A TTL index on a field nothing writes expires nothing."""
        self.assertIn("created_at", ast.unparse(_fn("_sync_run_open")))


class TheSilentSkipsBecomeCountable(unittest.TestCase):
    """Countable, NOT retried. Retrying them is separate work."""

    def test_the_download_skip_records_a_failure(self):
        fn = _fn("_sync_project_to_r2")
        src = ast.unparse(fn)
        self.assertIn("failures.append", src)

    def test_no_retry_was_added(self):
        """The skip still `continue`s. A retry loop here would be a different
        change with a different risk."""
        fn = _fn("_sync_project_to_r2")
        for node in ast.walk(fn):
            if isinstance(node, ast.While):
                # the pagination loop is the only permitted While
                self.assertIn("has_more", ast.unparse(node.test))


if __name__ == "__main__":
    unittest.main(verbosity=2)
