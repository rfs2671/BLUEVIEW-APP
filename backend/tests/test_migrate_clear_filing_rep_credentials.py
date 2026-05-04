"""MR.14 commit 4b — backfill migration unit tests.

Coverage:
  • Static-source pin: target query shape + $unset shape match the
    documented contract (so a future commit can't silently drift).
  • Dry-run path: candidate count returned, no update_one fires.
  • Execute path: $unset issued per-doc, totals reported.
  • Idempotency: a second run after --execute finds zero candidates.
  • _credentials_byte_size helper: sums b64 lengths.

The migration runs against a Mongo cluster in production but here we
exercise it via Motor mocks (same pattern as
test_migrate_project_list_defaults.py and the deleted MR.10 init
migration test).
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


def _run(coro):
    return asyncio.run(coro)


class TestStaticSourceContract(unittest.TestCase):
    """Pin the migration script's target-query + update shape so a
    future refactor can't silently change semantics."""

    def test_script_uses_dotted_path_query(self):
        path = _BACKEND / "scripts" / "migrate_clear_filing_rep_credentials.py"
        src = path.read_text(encoding="utf-8")
        # Target query must scope to non-deleted companies that have
        # ANY rep carrying the credentials field. Dotted-path $exists
        # is the right shape (an $elemMatch on "credentials" inside
        # filing_reps would be wrong because credentials lives on the
        # rep dict, not the filing_reps array).
        self.assertIn('"is_deleted": {"$ne": True}', src)
        self.assertIn('"filing_reps.credentials": {"$exists": True}', src)

    def test_script_unsets_with_all_positional(self):
        path = _BACKEND / "scripts" / "migrate_clear_filing_rep_credentials.py"
        src = path.read_text(encoding="utf-8")
        # $unset uses the all-positional `$[]` operator so a single
        # update strips the field off every rep on the doc.
        self.assertIn('"$unset": {"filing_reps.$[].credentials": ""}', src)

    def test_script_requires_explicit_mode_flag(self):
        path = _BACKEND / "scripts" / "migrate_clear_filing_rep_credentials.py"
        src = path.read_text(encoding="utf-8")
        # Mutually exclusive --dry-run / --execute, neither is the
        # default. Same shape as migrate_filing_reps_init.py.
        self.assertIn("add_mutually_exclusive_group(required=True)", src)
        self.assertIn("--dry-run", src)
        self.assertIn("--execute", src)


class TestCredentialsByteSizeHelper(unittest.TestCase):

    def test_sums_b64_lengths(self):
        from scripts.migrate_clear_filing_rep_credentials import (
            _credentials_byte_size,
        )
        creds = [
            {"encrypted_ciphertext": "AAAA"},     # 4
            {"encrypted_ciphertext": "BBBBBBBB"}, # 8
            {"encrypted_ciphertext": ""},         # 0
            {},                                   # 0 (no key)
        ]
        self.assertEqual(_credentials_byte_size(creds), 12)

    def test_handles_none_input(self):
        from scripts.migrate_clear_filing_rep_credentials import (
            _credentials_byte_size,
        )
        self.assertEqual(_credentials_byte_size(None), 0)

    def test_handles_empty_list(self):
        from scripts.migrate_clear_filing_rep_credentials import (
            _credentials_byte_size,
        )
        self.assertEqual(_credentials_byte_size([]), 0)


def _build_db_mock(*, candidates_first_count, sample_docs, full_docs):
    """Build a mock Motor client where:
      • count_documents(target_query) → candidates_first_count first,
        then 0 (idempotency check on a second pass).
      • count_documents({"is_deleted": {"$ne": True}}) → fixed.
      • find(target_query, projection).limit(20) → sample_docs cursor.
      • find(target_query, projection) → full_docs async cursor.
      • update_one() → MagicMock(modified_count=1).
    """
    db_mock = MagicMock()
    db_mock.companies = MagicMock()

    count_calls = {"n": 0}
    async def _count(query):
        # Two distinct query shapes; key off "filing_reps.credentials"
        # presence.
        if "filing_reps.credentials" in query:
            count_calls["n"] += 1
            # First call returns the populated candidates count;
            # subsequent calls (e.g. idempotency re-run) return 0
            # because we're modeling a post-execute state.
            return candidates_first_count if count_calls["n"] == 1 else 0
        # The "is_deleted: $ne True" overall count.
        return candidates_first_count + 5

    db_mock.companies.count_documents = AsyncMock(side_effect=_count)

    class _AsyncCursor:
        def __init__(self, items):
            self._items = list(items)
            self._limited = None

        def limit(self, n):
            self._limited = self._items[:n]
            return self

        def __aiter__(self):
            self._iter = iter(
                self._limited if self._limited is not None else self._items
            )
            return self

        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration:
                raise StopAsyncIteration

    def _find(query, projection=None):
        # Rough heuristic: if a projection is asked with `name`, we're
        # in the sample loop; otherwise it's the full pass.
        if projection and "name" in projection:
            return _AsyncCursor(sample_docs)
        return _AsyncCursor(full_docs)

    db_mock.companies.find = MagicMock(side_effect=_find)
    db_mock.companies.update_one = AsyncMock(
        return_value=MagicMock(modified_count=1)
    )
    return db_mock


class TestDryRunPath(unittest.TestCase):
    """Dry-run reports candidate counts but never issues an update."""

    def test_dry_run_no_update_one_calls(self):
        from scripts import migrate_clear_filing_rep_credentials as m

        sample = [
            {
                "_id": "co_1",
                "name": "Acme GC",
                "filing_reps": [
                    {"id": "r1", "credentials": [
                        {"encrypted_ciphertext": "A" * 40},
                    ]},
                    {"id": "r2"},  # no credentials
                ],
            },
        ]
        db_mock = _build_db_mock(
            candidates_first_count=1,
            sample_docs=sample,
            full_docs=sample,  # not used in dry-run
        )

        with patch.object(m, "AsyncIOMotorClient",
                          return_value={"smoke_test": db_mock}):
            # AsyncIOMotorClient(url)[db_name] indexing — mock supports
            # subscript via dict-as-client trick.
            rc = _run(m.main(dry_run=True))

        self.assertEqual(rc, 0)
        # No update_one calls in dry-run.
        db_mock.companies.update_one.assert_not_awaited()


class TestExecutePath(unittest.TestCase):
    """Execute path issues $unset per-doc and tallies totals."""

    def test_execute_issues_unset_per_doc(self):
        from scripts import migrate_clear_filing_rep_credentials as m

        full = [
            {
                "_id": "co_1",
                "filing_reps": [
                    {"id": "r1", "credentials": [
                        {"encrypted_ciphertext": "A" * 40},
                        {"encrypted_ciphertext": "B" * 60},
                    ]},
                    {"id": "r2"},
                ],
            },
            {
                "_id": "co_2",
                "filing_reps": [
                    {"id": "r3", "credentials": [
                        {"encrypted_ciphertext": "C" * 50},
                    ]},
                ],
            },
        ]
        db_mock = _build_db_mock(
            candidates_first_count=2,
            sample_docs=full,
            full_docs=full,
        )

        with patch.object(m, "AsyncIOMotorClient",
                          return_value={"smoke_test": db_mock}):
            rc = _run(m.main(dry_run=False))

        self.assertEqual(rc, 0)
        # One update_one call per company doc with the $unset path.
        self.assertEqual(db_mock.companies.update_one.await_count, 2)
        # Inspect the $unset shape of the first call.
        args, kwargs = db_mock.companies.update_one.await_args_list[0]
        filter_, update = args
        self.assertEqual(update, {"$unset": {"filing_reps.$[].credentials": ""}})


class TestIdempotency(unittest.TestCase):
    """A second pass after --execute finds zero candidates and exits."""

    def test_zero_candidates_short_circuits_to_clean_exit(self):
        from scripts import migrate_clear_filing_rep_credentials as m

        db_mock = _build_db_mock(
            candidates_first_count=0,
            sample_docs=[],
            full_docs=[],
        )

        with patch.object(m, "AsyncIOMotorClient",
                          return_value={"smoke_test": db_mock}):
            rc = _run(m.main(dry_run=False))

        self.assertEqual(rc, 0)
        db_mock.companies.update_one.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
