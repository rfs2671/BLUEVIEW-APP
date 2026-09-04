"""AN INDEX THAT CANNOT BUILD IS A CONSTRAINT THAT IS NOT ENFORCED.

    python -m pytest backend/tests/test_startup_index_integrity.py -q

`logbooks_one_open_amendment_per_parent` has never built. Production holds the
duplicates it forbids (Aug 10 and Aug 14, two open children on one parent
each), the build is rejected with E11000, `_INDEX_CONFLICT_CODES = {85, 86}`
does not contain 11000, so `_ensure_index_resilient` logged ONE warning and
returned -- and startup went green. The race the index exists to close stayed
open, and `amend_logbook`'s `except DuplicateKeyError` has been dead code
reading as a live race guard for the whole time.

E11000 IS NOT AN INDEX EVENT. 85 and 86 say "the spec you asked for disagrees
with the spec that is there" -- a deploy fact, fixed by dropping and
recreating, and correctly invisible. 11000 says "the DATA disagrees with the
rule you are trying to impose". No amount of recreating fixes it, nothing in a
deploy caused it, and the only thing that clears it is a person changing rows.
So it gets its own branch, `error` not `warning`, a compliance_alerts row, and
a name in the health payload.

IT STILL MUST NOT RAISE. startup_event is @app.on_event("startup"): a raise
means two draft children on one parent take the whole API offline for every CP
on every project. Make the STATE visible, not the event.

The same treatment now covers the eight unique builds that were bare awaits in
startup_event. Any one of those meeting duplicate data raised straight out of
the startup handler -- a total outage on a data condition, at the next restart,
with no deploy having changed anything.
"""

from __future__ import annotations

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

from tests.source_text import code_of  # noqa: E402

# raw=True: every assertion below that reads server.py's text is about the
# PROSE — that a finding is written down where the code it describes lives.
RAW = code_of("server.py", raw=True)
TREE = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8-sig"))

AUDIT = BACKEND / "scripts" / "audit_production.py"


def _run(coro):
    return asyncio.run(coro)


def _code_of_fn(name, tree=TREE):
    """A function's source with its docstring removed."""
    node = _fn(name, tree)
    body = list(node.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return chr(10).join(ast.unparse(s) for s in body)


def _fn(name, tree=TREE):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _failing_collection(code, name="logbooks"):
    """A collection whose create_index always fails with `code`."""
    from pymongo.errors import OperationFailure

    coll = MagicMock()
    coll.name = name
    coll.create_index = AsyncMock(
        side_effect=OperationFailure("E11000 duplicate key error", code)
    )
    coll.drop_index = AsyncMock()

    async def _no_indexes():
        return
        yield  # pragma: no cover

    coll.list_indexes = MagicMock(return_value=_no_indexes())
    return coll


class _AlertRecorder:
    """Captures compliance_alerts reads and writes."""

    def __init__(self, existing=None):
        self.existing = existing
        self.inserted = []

    def build_db(self):
        alerts = MagicMock()

        async def find_one(flt):
            self.last_filter = flt
            return self.existing

        async def insert_one(doc):
            self.inserted.append(doc)
            self.existing = doc
            return MagicMock(inserted_id="a1")

        alerts.find_one = AsyncMock(side_effect=find_one)
        alerts.insert_one = AsyncMock(side_effect=insert_one)
        database = MagicMock()
        database.compliance_alerts = alerts
        return database


class E11000GetsItsOwnBranch(unittest.TestCase):
    """The helper's third branch, and the reason it is not the second."""

    def setUp(self):
        server.FAILED_UNIQUE_INDEX_BUILDS.clear()

    tearDown = setUp

    def test_11000_is_not_in_the_index_conflict_set(self):
        # It is not an index event and must never be handled as one: there is
        # no drop-and-recreate that fixes duplicate data.
        self.assertNotIn(11000, server._INDEX_CONFLICT_CODES)

    def test_e11000_on_unique_build_records_the_index_name(self):
        rec = _AlertRecorder()
        coll = _failing_collection(11000)
        with patch.object(server, "db", rec.build_db()):
            _run(server._ensure_index_resilient(
                coll,
                keys=[("parent_logbook_id", 1)],
                name="logbooks_one_open_amendment_per_parent",
                unique=True,
                partialFilterExpression={"is_amendment": True},
            ))
        self.assertIn(
            "logbooks_one_open_amendment_per_parent",
            server.FAILED_UNIQUE_INDEX_BUILDS,
        )

    def test_e11000_writes_a_compliance_alert_row(self):
        rec = _AlertRecorder()
        coll = _failing_collection(11000)
        with patch.object(server, "db", rec.build_db()):
            _run(server._ensure_index_resilient(
                coll,
                keys=[("parent_logbook_id", 1)],
                name="logbooks_one_open_amendment_per_parent",
                unique=True,
            ))
        self.assertEqual(len(rec.inserted), 1)
        row = rec.inserted[0]
        self.assertEqual(row["alert_type"], "unique_index_not_enforced")
        self.assertEqual(
            row["details"]["index_name"],
            "logbooks_one_open_amendment_per_parent",
        )
        self.assertEqual(row["details"]["collection"], "logbooks")
        self.assertIs(row["resolved"], False)

    def test_the_row_is_deduped_on_index_name(self):
        # Follows _flag_unsigned_stale_log: read first, insert only if absent.
        # Every restart re-attempts every index, so an undeduped row would
        # stack one alert per boot on a condition nothing in the app can clear.
        rec = _AlertRecorder()
        db_mock = rec.build_db()
        coll = _failing_collection(11000)
        with patch.object(server, "db", db_mock):
            for _ in range(3):
                coll.create_index.reset_mock()
                coll = _failing_collection(11000)
                _run(server._ensure_index_resilient(
                    coll,
                    keys=[("parent_logbook_id", 1)],
                    name="logbooks_one_open_amendment_per_parent",
                    unique=True,
                ))
        self.assertEqual(len(rec.inserted), 1)
        self.assertIn("details.index_name", rec.last_filter)

    def test_it_is_an_error_not_a_warning(self):
        rec = _AlertRecorder()
        coll = _failing_collection(11000)
        with patch.object(server, "db", rec.build_db()), \
                patch.object(server.logger, "error") as err, \
                patch.object(server.logger, "warning") as warn:
            _run(server._ensure_index_resilient(
                coll,
                keys=[("parent_logbook_id", 1)],
                name="logbooks_one_open_amendment_per_parent",
                unique=True,
            ))
        joined = " ".join(str(c) for c in err.call_args_list)
        self.assertIn(
            "UNIQUE INDEX NOT ENFORCED: logbooks."
            "logbooks_one_open_amendment_per_parent",
            joined,
        )
        # Anchored on the whole sentence, not the index name: the claim is
        # that this FINDING is not reported at warning level, and a bare name
        # would be satisfied by any line that happened to contain it.
        self.assertNotIn(
            "UNIQUE INDEX NOT ENFORCED",
            " ".join(str(c) for c in warn.call_args_list),
        )

    def test_it_does_not_raise(self):
        # startup_event is @app.on_event("startup"). A raise here takes the
        # whole API offline for every CP because two drafts share a parent.
        rec = _AlertRecorder()
        coll = _failing_collection(11000)
        with patch.object(server, "db", rec.build_db()):
            _run(server._ensure_index_resilient(
                coll, keys=[("a", 1)], name="x_unique", unique=True,
            ))  # must simply return

    def test_a_non_unique_build_is_not_a_data_integrity_finding(self):
        # 11000 cannot arise from a non-unique build; if it somehow does, it is
        # not the finding this branch reports and must not raise an alert.
        rec = _AlertRecorder()
        coll = _failing_collection(11000)
        with patch.object(server, "db", rec.build_db()):
            _run(server._ensure_index_resilient(
                coll, keys=[("a", 1)], name="x_plain",
            ))
        self.assertEqual(rec.inserted, [])
        self.assertNotIn("x_plain", server.FAILED_UNIQUE_INDEX_BUILDS)

    def test_a_spec_conflict_still_drops_and_recreates(self):
        # The 85/86 branch is untouched: a spec change must still self-heal.
        from pymongo.errors import OperationFailure

        coll = MagicMock()
        coll.name = "dob_logs"
        calls = {"n": 0}

        async def create_index(keys, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OperationFailure("IndexOptionsConflict", 85)
            return "ok"

        coll.create_index = AsyncMock(side_effect=create_index)
        coll.drop_index = AsyncMock()
        _run(server._ensure_index_resilient(
            coll, keys=[("a", 1)], name="ttl", expireAfterSeconds=1,
        ))
        coll.drop_index.assert_awaited_once()
        self.assertEqual(calls["n"], 2)

    def test_a_later_successful_build_clears_the_recorded_failure(self):
        # The operator withdraws the extra drafts, restarts, the index builds.
        # The health payload must stop reporting it.
        server.FAILED_UNIQUE_INDEX_BUILDS["x_unique"] = "logbooks"
        coll = MagicMock()
        coll.name = "logbooks"
        coll.create_index = AsyncMock(return_value="x_unique")
        _run(server._ensure_index_resilient(
            coll, keys=[("a", 1)], name="x_unique", unique=True,
        ))
        self.assertNotIn("x_unique", server.FAILED_UNIQUE_INDEX_BUILDS)


class HealthReportsTheState(unittest.TestCase):

    def setUp(self):
        server.FAILED_UNIQUE_INDEX_BUILDS.clear()

    tearDown = setUp

    def test_health_names_the_failed_indexes(self):
        server.FAILED_UNIQUE_INDEX_BUILDS["logbooks_one_open_amendment_per_parent"] = "logbooks"
        payload = _run(server.health_check())
        self.assertEqual(
            payload["indexes"]["failed_unique_builds"],
            ["logbooks_one_open_amendment_per_parent"],
        )
        self.assertIs(payload["indexes"]["complete"], False)

    def test_health_is_index_complete_when_nothing_failed(self):
        payload = _run(server.health_check())
        self.assertEqual(payload["indexes"]["failed_unique_builds"], [])
        self.assertIs(payload["indexes"]["complete"], True)

    def test_status_stays_healthy(self):
        # The probe Railway restarts on. A missing index is a data finding for
        # a person to clear, not a reason to cycle a serving process forever.
        server.FAILED_UNIQUE_INDEX_BUILDS["x"] = "y"
        self.assertEqual(_run(server.health_check())["status"], "healthy")


class NoBareUniqueBuildsLeft(unittest.TestCase):
    """The eight that could take the API down at the next restart."""

    EIGHT = [
        ("users", "email"),
        ("workers", "phone"),
        ("nfc_tags", "tag_id"),
        ("subcontractors", "email"),
        ("companies", "name"),
        ("daily_logs", "project_id"),
        ("whatsapp_contacts", "company_id"),
        ("project_files", "project_id"),
    ]

    def _bare_unique_builds(self, fn_name):
        """create_index(..., unique=True) called directly on a collection."""
        found = []
        for node in ast.walk(_fn(fn_name)):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Attribute) and f.attr == "create_index"):
                continue
            for kw in node.keywords:
                if kw.arg == "unique" and getattr(kw.value, "value", None) is True:
                    found.append(ast.unparse(node)[:120])
        return found

    def test_startup_event_has_no_bare_unique_create_index(self):
        self.assertEqual(self._bare_unique_builds("startup_event"), [])

    def test_whatsapp_migrations_have_no_bare_unique_create_index(self):
        self.assertEqual(
            self._bare_unique_builds("run_whatsapp_startup_migrations"), []
        )

    def test_all_eight_are_still_declared_through_the_helper(self):
        # Not merely deleted. Each must still be created, by the resilient
        # helper, under the name Mongo would have generated -- a rename would
        # build a SECOND index beside the live one.
        body = ast.unparse(_fn("startup_event"))
        for coll, key in self.EIGHT:
            with self.subTest(coll=coll):
                self.assertIn(f"db.{coll}" if coll != "project_files" else "db.project_files", body)
                self.assertIn(f"'{key}'", body)

    def test_default_index_names_are_preserved(self):
        body = ast.unparse(_fn("startup_event"))
        for name in (
            "email_1", "phone_1", "tag_id_1", "name_1",
            "project_id_1_date_1", "company_id_1_phone_1",
            "project_id_1_dropbox_path_1",
        ):
            with self.subTest(name=name):
                self.assertIn(f"'{name}'", body)


class WhatsappTryIsSplit(unittest.TestCase):
    """Five migrations under one except is four silently skipped migrations."""

    def test_more_than_one_try_in_the_migration_runner(self):
        tries = [n for n in ast.walk(_fn("run_whatsapp_startup_migrations"))
                 if isinstance(n, ast.Try)]
        self.assertGreaterEqual(len(tries), 4, "still one shared try")

    def test_document_page_index_left_the_whatsapp_function(self):
        # CODE only. The function's docstring says where the block went, and a
        # test that matched the docstring instead of the code would pass with
        # the block still sitting there -- the trap tests/source_text.py exists
        # for.
        body = _code_of_fn("run_whatsapp_startup_migrations")
        self.assertNotIn("db.document_page_index", body)

    def test_document_page_indexes_has_its_own_function(self):
        self.assertTrue(hasattr(server, "ensure_document_page_indexes"))
        body = ast.unparse(_fn("ensure_document_page_indexes"))
        self.assertIn("document_page_index", body)

    def test_startup_awaits_it_separately(self):
        body = ast.unparse(_fn("startup_event"))
        self.assertIn("ensure_document_page_indexes()", body)
        self.assertIn("run_whatsapp_startup_migrations()", body)


class AuditProductionTellsTheTruth(unittest.TestCase):

    def _expected(self):
        """EXPECTED_INDEXES, read by AST rather than by import.

        audit_production.py is a standalone operator script and importing it
        under a synthetic module name trips a dataclass/annotation resolution
        error. The literal is what the test is about, so read the literal.
        """
        tree = ast.parse(AUDIT.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "EXPECTED_INDEXES"
                for t in node.targets
            ):
                return ast.literal_eval(node.value), None
        raise AssertionError("EXPECTED_INDEXES not found")

    def test_removed_dob_ttls_are_no_longer_expected(self):
        # Deliberately removed 2026-07-24 -- detected_at is a sync stamp, not
        # an event date. Expecting them is a standing false positive in the
        # one tool meant to catch a missing index.
        expected, _ = self._expected()
        self.assertNotIn("dob_logs_ttl_short", expected.get("dob_logs", set()))
        self.assertNotIn("dob_logs_ttl_long", expected.get("dob_logs", set()))

    def test_logbooks_open_amendment_index_is_audited(self):
        expected, _ = self._expected()
        self.assertIn(
            "logbooks_one_open_amendment_per_parent",
            expected.get("logbooks", set()),
        )

    def test_signature_events_ledger_index_is_audited(self):
        expected, _ = self._expected()
        self.assertIn(
            "signature_events_one_row_per_signing_act",
            expected.get("signature_events", set()),
        )

    def test_both_collections_are_enumerated(self):
        tree = ast.parse(AUDIT.read_text(encoding="utf-8"))
        body = ast.unparse(_fn("section_indexes", tree))
        self.assertIn("'logbooks'", body)
        self.assertIn("'signature_events'", body)


class TheFindingsAreRecordedWhereTheyLive(unittest.TestCase):
    """raw=True: these assertions ARE about the prose."""

    def test_amend_logbook_duplicate_handler_is_marked_dead(self):
        # The note lives INSIDE the handler, not above the insert -- see
        # its own last paragraph for why.
        i = RAW.find("async def amend_logbook")
        self.assertGreater(i, 0)
        j = RAW.find("except DuplicateKeyError:", i)
        self.assertGreater(j, i, "amend_logbook's handler moved")
        window = RAW[j:j + 3000]
        self.assertIn("HAS NEVER BUILT", window)
        self.assertIn("DEAD CODE THAT READS AS A LIVE RACE", window)

    def test_nightly_tick_shared_try_is_recorded(self):
        i = RAW.find("async def _logbook_nightly_tick():")
        self.assertGreater(i, 0)
        # The note sits immediately ABOVE the def, where a reader meets it
        # before the body it is about.
        window = RAW[max(0, i - 4000):i + 4000]
        self.assertIn("FOUR STAGES UNDER ONE try", window)
        self.assertIn("sweep_stale_end_of_day_logs", window)


if __name__ == "__main__":
    unittest.main()
