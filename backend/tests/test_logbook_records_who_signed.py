"""THE LOGBOOK RECORDS WHICH ACCOUNT SIGNED IT.

Item 8's default names the competent person by resolving an account id off the
CP's filed daily jobsite log. It shipped on `created_by` -- which is stamped
when the DRAFT IS CREATED, not when it is signed. On a shared site device the
man who opens the form and the man who signs it can differ, and that is
precisely the two-competent-persons case the default exists for.

── WHY NOT `finalized_by`, WHICH ALREADY EXISTED ───────────────────────────

Because it was measured before it was trusted. Of 266 submitted logbooks:

    with finalized_by            51
    disagreeing with created_by  29   <- EVERY ONE READS `system:eod_sweep`

`finalized_by` records whoever FROZE the record, and for the two END_OF_DAY
types the freezer is the overnight sweep. A field that answers "who signed"
with a cron job is worse than one that answers nothing, because the wrong name
on a BC 3301.13.12 designation is not questioned.

So `signed_by` is written WHERE THE SIGNATURE ARRIVES -- create and update,
from the authenticated session -- and finalize is left alone.

── FORWARD-ONLY ────────────────────────────────────────────────────────────

Nothing backfills the 266 filed records. `designatedCp.js` keeps `created_by`
as a permanent fallback rather than a transitional one, and this file asserts
no migration.
"""

from __future__ import annotations

import ast
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

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")
SIG = {"paths": [[{"x": 1, "y": 2}]], "signerName": "Michael Cespedes"}
USER = {"id": "6a68b16ebe9c27dedf5cf47f", "name": "Michael Cespedes"}


class OnlyASignatureProducesASigner(unittest.TestCase):

    def test_a_signed_request_records_the_authenticated_account(self):
        self.assertEqual(server._signed_by(SIG, USER),
                         {"signed_by": "6a68b16ebe9c27dedf5cf47f"})

    def test_an_unsigned_draft_records_NOTHING(self):
        """Stamping the account that saved a draft would assert a signer for a
        document nobody has signed -- the absence-read-as-a-claim shape."""
        for empty in (None, {}, "", 0):
            with self.subTest(signature=empty):
                self.assertEqual(server._signed_by(empty, USER), {})

    def test_an_unidentifiable_caller_records_NOTHING(self):
        """No id, no claim. A key with an empty value would be a value."""
        for u in (None, {}, {"name": "no id"}):
            with self.subTest(user=u):
                self.assertEqual(server._signed_by(SIG, u), {})

    def test_the_id_is_stringified(self):
        """An ObjectId here and a string there is the id-spelling split this
        codebase reads both ways; the roster returns strings, so it stores
        one."""
        class _Oid:
            def __str__(self):
                return "abc123"
        self.assertEqual(server._signed_by(SIG, {"id": _Oid()}),
                         {"signed_by": "abc123"})


class ItComesFromTheSessionAndNeverFromTheBody(unittest.TestCase):
    """A client that could name its own signer could file a compliance record
    under somebody else's account."""

    def test_the_helper_takes_current_user_not_the_payload(self):
        src = ast.unparse(ast.parse(_SRC))
        i = src.index("def _signed_by(")
        j = src.index("\ndef ", i + 10)
        body = src[i:j]
        for forbidden in ("data.signed_by", "data.cp_user_id", "payload"):
            self.assertNotIn(forbidden, body)

    def test_every_call_site_passes_current_user(self):
        calls = [ln for ln in _SRC.split("\n") if "_signed_by(" in ln
                 and "def _signed_by" not in ln]
        self.assertGreaterEqual(len(calls), 3,
                                f"only {len(calls)} call sites found; the "
                                "create upsert, create insert and update PUT "
                                "must all stamp it")
        for ln in calls:
            with self.subTest(ln.strip()[:60]):
                self.assertIn("current_user", ln)


class TheThreeSigningPathsAllStampIt(unittest.TestCase):
    """Save-Draft-then-Submit arrives as a PUT, so a stamp on create alone
    would miss most real signings."""

    def _fn(self, name):
        i = _SRC.index(f"async def {name}(")
        j = _SRC.index("\n@api_router", i)
        return _SRC[i:j]

    def test_create_logbook_stamps_it(self):
        self.assertGreaterEqual(self._fn("create_logbook").count("_signed_by("), 2,
                                "both the insert and the upsert branch")

    def test_update_logbook_stamps_it(self):
        """THIS TEST CAUGHT THE STAMP IN THE WRONG FUNCTION.

        The first draft anchored on `update["cp_signature"] = data.cp_signature`
        -- which is in `update_cp_profile`, where the CP's REUSABLE SIGNATURE
        PROFILE is written to his USER document. `signed_by` landed there, on a
        profile update, and nowhere near a logbook. update_logbook's own write
        goes through `_finalize_cp_signature`.

        `assertTrue` with a short message: the haystack is a 300-line function
        and printing it buries the one fact that matters."""
        self.assertTrue("_signed_by(" in self._fn("update_logbook"),
                        "update_logbook does not stamp signed_by — check it "
                        "did not land in update_cp_profile again")

    def test_and_it_is_NOT_stamped_on_the_cp_profile(self):
        """A user's saved signature profile is not a signing event. A
        `signed_by` there would be a field on the wrong document entirely."""
        self.assertNotIn("_signed_by(", self._fn("update_cp_profile"))


class NothingIsBackfilled(unittest.TestCase):

    def test_no_migration_ships_with_this(self):
        i = _SRC.index("def _signed_by(")
        j = _SRC.index("\ndef ", i + 10)
        for bad in ("update_many", "$set: {'signed_by"):
            self.assertNotIn(bad, _SRC[i:j])

    def test_the_client_keeps_created_by_as_a_permanent_fallback(self):
        js = (_BACKEND.parent / "frontend" / "src" / "utils"
              / "designatedCp.js").read_text(encoding="utf-8")
        self.assertIn("ANCHOR_FIELDS = ['signed_by', 'created_by']", js)
        self.assertNotIn("ANCHOR_FIELD =", js)

    def test_and_finalized_by_is_not_among_them(self):
        """ANCHORED AS AN ARRAY ELEMENT, not as a bare word.
        `test_absence_literals_are_specific.py` flagged the bare form, and it
        was right: `finalized_by` appears in this module's own docstring
        explaining WHY it is excluded, so a substring ban would fail on the
        reasoning for the rule it enforces. `'finalized_by'` with its quotes is
        the shape a JS array element actually has."""
        js = (_BACKEND.parent / "frontend" / "src" / "utils"
              / "designatedCp.js").read_text(encoding="utf-8")
        i = js.index("ANCHOR_FIELDS = [")
        decl = js[i:js.index("]", i) + 1]
        self.assertNotIn("'finalized_by'", decl)
        self.assertIn("'signed_by'", decl)


class FinalizeIsLeftAlone(unittest.TestCase):
    """`finalized_by` still records what it always recorded. This change does
    not repurpose it, because 29 of the 51 rows carrying it read
    `system:eod_sweep` and that is a TRUE statement about the freeze."""

    def test_finalize_still_writes_finalized_by(self):
        i = _SRC.index("async def finalize_logbook(")
        j = _SRC.index("\n@api_router", i)
        self.assertIn('"finalized_by": current_user.get("id")', _SRC[i:j])

    def test_and_finalize_does_NOT_write_signed_by(self):
        """The signing request is the right moment; the freeze is not. A
        finalize stamp would name whoever tapped the lock bar, or the sweep."""
        i = _SRC.index("async def finalize_logbook(")
        j = _SRC.index("\n@api_router", i)
        self.assertNotIn("_signed_by(", _SRC[i:j])


if __name__ == "__main__":
    unittest.main(verbosity=2)
