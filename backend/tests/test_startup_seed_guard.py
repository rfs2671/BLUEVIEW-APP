"""The TEST DATA SEED must never run against production.

It had NO environment check. Its only condition was `if not test_user` — a
question about database STATE, not about environment — so it ran against
production on first boot and would run again on a fresh database, a restored
backup, or a rename.

It has already run. Among the documents it left is a subcontractor with no
`contact_name`, which made GET /admin/subcontractors/{id} raise a pydantic
ValidationError -> 500 for that row.

These assert the guard FAILS CLOSED: absent, empty or misspelled means skip.
There is no value of the environment that means "run" other than an explicit
opt-in.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server as S  # noqa: E402
from tests.source_text import inserted_doc_keys  # noqa: E402

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")
_SEED = _SRC[_SRC.index("# ENV-GATED, AND IT FAILS CLOSED."):]
_SEED = _SEED[:_SEED.index("# 7. Create test project")]


def _enabled(value):
    """The shipped expression, extracted and executed — not a copy of it."""
    line = re.search(
        r'_seed_enabled = os\.environ\.get\("SEED_TEST_DATA", ""\)'
        r'\.strip\(\)\.lower\(\) in \(\s*([^)]*)\)', _SRC, re.S)
    assert line, "the guard expression is not where the test expects it"
    allowed = tuple(re.findall(r'"([^"]+)"', line.group(1)))
    return str(value or "").strip().lower() in allowed


class TheGuardFailsClosed(unittest.TestCase):
    def test_unset_does_not_run(self):
        self.assertFalse(_enabled(None))
        self.assertFalse(_enabled(""))

    def test_whitespace_and_case_do_not_accidentally_enable(self):
        for v in ("  ", "\t", "no", "0", "false", "off", "disabled", "prod",
                  "production", "maybe", "SEED", "yes please"):
            with self.subTest(value=v):
                self.assertFalse(_enabled(v), f"{v!r} must not enable the seed")

    def test_only_an_explicit_opt_in_runs_it(self):
        for v in ("1", "true", "TRUE", " True ", "yes", "on"):
            with self.subTest(value=v):
                self.assertTrue(_enabled(v))

    def test_the_guard_is_checked_before_the_db_lookup(self):
        """A production boot must not even query for the test user."""
        self.assertLess(_SEED.index("_seed_enabled ="),
                        _SEED.index('db.users.find_one({"email": "test@test.com"}'))

    def test_the_insert_branch_requires_the_flag(self):
        """`if not test_user` alone was the whole bug. The flag must be part of
        the condition, not merely computed above it."""
        self.assertIn("if _seed_enabled and not test_user:", _SEED)

    def test_nothing_inside_can_run_without_it(self):
        """Every insert in the block sits under that one condition."""
        body = _SEED[_SEED.index("if _seed_enabled and not test_user:"):]
        self.assertGreater(body.count("insert_one"), 3)
        self.assertNotIn("\n    await db.", body)   # nothing at function indent

    def test_it_says_so_in_the_log(self):
        """Silence on a production boot is indistinguishable from a broken
        guard. It states which state it is in."""
        self.assertIn("TEST DATA SEED skipped", _SEED)


class TheSeededSubcontractorIsValid(unittest.TestCase):
    """The model is right; the seed was the only writer producing an invalid
    document. Fixed at the seed, per ruling."""

    # THE SEEDED DOCUMENT, READ FROM THE AST RATHER THAN A CHARACTER WINDOW.
    #
    # These two tests sliced `_SRC[i:i + 900]` from a marker comment. That is a
    # fixed-size byte budget standing in for a syntactic block, and on
    # 2026-09-04 it broke for the reason it was always going to: somebody added
    # a COMMENT inside the seed call, the budget ran out mid-comment, and two
    # tests reported that the seed "still omits email, contact_name" about a
    # document that carries both. The fields had not moved; the window had.
    #
    # Same family as a line-number pin and as a leftmost `re.search` over a 41k
    # line file — a location standing in for a structure. The dict is a dict,
    # so it is read as one.
    def test_it_now_carries_contact_name(self):
        self.assertIn("contact_name", inserted_doc_keys("subcontractors"))

    def test_the_seeded_document_validates_against_the_response_model(self):
        keys = inserted_doc_keys("subcontractors")
        # NON-EMPTY FIRST. Every "is X missing" assertion below is vacuously
        # satisfied by an empty set, which is exactly how a check that stopped
        # reaching its subject reports success.
        self.assertTrue(keys, "read no keys off the seeded document")
        required = {f for f, inf in S.SubcontractorResponse.model_fields.items()
                    if inf.is_required()} - {"id"}   # id comes from serialize_id
        missing = required - keys
        self.assertEqual(missing, set(), f"seed still omits {missing}")

    def test_the_model_was_NOT_loosened(self):
        """The ruling: fix the seed, not the model. Every real writer goes
        through SubcontractorCreate, which requires these."""
        for f in ("company_name", "contact_name", "email"):
            self.assertTrue(
                S.SubcontractorResponse.model_fields[f].is_required(), f)
            self.assertTrue(
                S.SubcontractorCreate.model_fields[f].is_required(), f)
