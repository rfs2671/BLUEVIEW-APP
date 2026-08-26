"""An empty signature is UNSIGNED, and it does not fall off the screen.

THE DEFECT. attestation_gaps selected unaffirmed rows with

    "cp_signature": {"$ne": None},

and `{}` is not null in Mongo. So a row holding an EMPTY signature -- the shape
an old bundle wrote -- was reported as "signed but not affirmed", and the CP was
told to open it and "tap your signature to affirm it. You do not need to sign
again." There was no signature to tap. The pad then offered AFFIRM over an empty
canvas and stamped `affirmed: True` onto nothing, which printed
"AFFIRMED for this document" in green on a DOB filing.

WHY A THIRD SELECTOR AND NOT AN EDITED SECOND. Requiring ink in the unaffirmed
query removes inkless rows from it, and the stale pass cannot catch what falls
out: it is scoped to END_OF_DAY types on a PAST date. An inkless toolbox_talk,
or a daily_jobsite dated today, would match neither selector and vanish from
attestation_gaps entirely -- a filed, unsigned DOB record with nothing on any
screen pointing at it. Making a wrong label disappear is not fixing it.

PREVENTION ONLY. Production counts at the time of writing were both zero: no
row reclassifies and no affirmed-but-inkless attestation exists. Nothing here
remediates; it stops the shape being minted and stops it being mislabelled if
one ever is.

WHAT THIS FILE CANNOT PROVE. TheTwoFormsAgree below evaluates the Mongo clauses
with a matcher written HERE, so it proves the Python predicate and this reading
of the clauses agree. It does not prove Mongo reads them the same way -- that
needs a live server. The matcher is deliberately tiny and handles only the three
clause forms actually used, so what it asserts stays legible.

    python backend/tests/test_signature_ink_predicate.py
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402


# ── The shapes, named once ──────────────────────────────────────────────────
EMPTY = {}
NO_STROKES = {"paths": []}
CREDENTIAL_ONLY = {"signerName": "Roy Fishman", "timestamp": "2026-08-19T15:01:10.726Z"}
# The forged shape: affirmed, and containing nothing.
AFFIRMED_INKLESS = {"signerName": "Roy Fishman", "affirmed": True,
                    "affirmedAt": "2026-08-26T12:00:00Z"}
INHERITED = {"paths": [[{"x": 1, "y": 2}]], "signerName": "Roy Fishman",
             "timestamp": "2026-08-19T15:01:10.726Z"}
AFFIRMED = {**INHERITED, "affirmed": True, "affirmedAt": "2026-08-26T12:00:00Z"}
RASTER = {"data": "iVBORw0KGgo="}
LEGACY_STRING = "iVBORw0KGgo="

INKLESS = [None, EMPTY, NO_STROKES, CREDENTIAL_ONLY, AFFIRMED_INKLESS,
           {"data": ""}, "", {"paths": "not-a-list"}]
INKED = [INHERITED, AFFIRMED, RASTER, LEGACY_STRING]


class ThePredicate(unittest.TestCase):

    def test_an_empty_object_has_no_ink(self):
        """THE CASE THAT COST. `{}` is truthy in JS and is not null in Mongo, so
        it satisfied every presence check in the app."""
        self.assertFalse(server._has_signature_ink(EMPTY))

    def test_an_empty_stroke_list_has_no_ink(self):
        """Not "a signature with no strokes" -- no signature. canConfirm
        requires paths.length > 0, so a confirmed one always has at least one."""
        self.assertFalse(server._has_signature_ink(NO_STROKES))

    def test_a_name_and_a_stamp_are_not_a_signature(self):
        """The exact object handleAffirm used to build out of {}, and the one
        the PDF printed as AFFIRMED in green."""
        self.assertFalse(server._has_signature_ink(AFFIRMED_INKLESS))

    def test_nothing_has_no_ink(self):
        self.assertFalse(server._has_signature_ink(None))

    def test_vector_paths_are_ink(self):
        self.assertTrue(server._has_signature_ink(INHERITED))

    def test_a_base64_raster_is_ink(self):
        self.assertTrue(server._has_signature_ink(RASTER))

    def test_a_bare_base64_string_is_ink(self):
        """render_signature_html treats `isinstance(sig, str)` as an image."""
        self.assertTrue(server._has_signature_ink(LEGACY_STRING))

    def test_an_empty_string_is_not(self):
        self.assertFalse(server._has_signature_ink(""))

    def test_a_non_list_paths_is_not_ink(self):
        """_signature_paths_to_svg iterates it, so anything else is not a
        signature the renderer could draw."""
        self.assertFalse(server._has_signature_ink({"paths": "not-a-list"}))


class InkAndAffirmationAreDifferentQuestions(unittest.TestCase):
    """Both are required, and they fail for different reasons."""

    def test_ink_without_affirmation(self):
        self.assertTrue(server._has_signature_ink(INHERITED))
        self.assertFalse(server._is_affirmed_signature(INHERITED))

    def test_affirmation_without_ink(self):
        """NEITHER PREDICATE ALONE IS ENOUGH. This shape passes the affirmation
        gate and prints green; only the ink question refuses it."""
        self.assertTrue(server._is_affirmed_signature(AFFIRMED_INKLESS))
        self.assertFalse(server._has_signature_ink(AFFIRMED_INKLESS))

    def test_a_real_affirmed_signature_satisfies_both(self):
        self.assertTrue(server._has_signature_ink(AFFIRMED))
        self.assertTrue(server._is_affirmed_signature(AFFIRMED))


def _clause_matches(clause, sig):
    """Evaluate ONE of the three clause forms in _SIGNATURE_HAS_INK_CLAUSES
    against a candidate cp_signature. Deliberately handles only those forms --
    it is a reading of the query, not a Mongo implementation."""
    if "cp_signature.paths.0" in clause:
        return isinstance(sig, dict) and isinstance(sig.get("paths"), list) and len(sig["paths"]) > 0
    if "cp_signature.data" in clause:
        return isinstance(sig, dict) and isinstance(sig.get("data"), str) and sig["data"] != ""
    if "cp_signature" in clause:
        return isinstance(sig, str) and sig != ""
    raise AssertionError(f"unrecognised clause: {clause}")


def _query_says_ink(sig):
    return any(_clause_matches(c, sig) for c in server._SIGNATURE_HAS_INK_CLAUSES)


class TheTwoFormsAgree(unittest.TestCase):
    """The rule is written twice -- once in Python, once in query language --
    and the only defence against drift is a test that reads both."""

    def test_there_are_exactly_three_clauses(self):
        """A fourth added to one form and not the other is the drift this
        catches. If a shape is added, this number moves deliberately."""
        self.assertEqual(len(server._SIGNATURE_HAS_INK_CLAUSES), 3)

    def test_they_agree_on_every_inkless_shape(self):
        for sig in INKLESS:
            with self.subTest(sig=sig):
                self.assertFalse(server._has_signature_ink(sig))
                self.assertFalse(_query_says_ink(sig))

    def test_they_agree_on_every_inked_shape(self):
        for sig in INKED:
            with self.subTest(sig=sig):
                self.assertTrue(server._has_signature_ink(sig))
                self.assertTrue(_query_says_ink(sig))


# ── Driving the real endpoint ───────────────────────────────────────────────
PROJECT = {"_id": "projA", "id": "projA", "company_id": "companyA", "name": "588 Thomas"}
CP = {"_id": "u2", "id": "u2", "role": "cp", "company_id": "companyA",
      "account_status": "approved", "assigned_projects": ["projA"]}


def _notifications(logbooks):
    """Run get_logbook_notifications over a fake logbooks collection.

    The fake evaluates the selector clauses this module actually uses, so the
    classification below is the endpoint's own, not a restatement of it."""

    def matches(q, doc):
        for k, v in q.items():
            if k == "$or":
                if not any(_clause_matches(c, doc.get("cp_signature")) for c in v):
                    return False
            elif k == "$nor":
                if any(_clause_matches(c, doc.get("cp_signature")) for c in v):
                    return False
            elif k == "project_id":
                if doc.get("project_id") != v:
                    return False
            elif k == "status":
                if isinstance(v, dict) and "$ne" in v:
                    if doc.get("status") == v["$ne"]:
                        return False
                elif doc.get("status") != v:
                    return False
            elif k == "is_deleted":
                if doc.get("is_deleted") is True:
                    return False
            elif k == "is_locked":
                if doc.get("is_locked") is True:
                    return False
            elif k == "log_type":
                if isinstance(v, dict) and "$in" in v:
                    if doc.get("log_type") not in v["$in"]:
                        return False
                elif doc.get("log_type") != v:
                    return False
            elif k == "date":
                if isinstance(v, dict) and "$lt" in v:
                    if not (doc.get("date") or "") < v["$lt"]:
                        return False
            elif k == "cp_signature.affirmed":
                sig = doc.get("cp_signature")
                affirmed = sig.get("affirmed") if isinstance(sig, dict) else None
                if isinstance(v, dict) and "$ne" in v and affirmed == v["$ne"]:
                    return False
            elif k == "checked_in_at":
                return False           # the checkins query; no rows needed
        return True

    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        def sort(self, *a, **kw):
            return self

        async def to_list(self, n):
            return self.rows[:n]

    def find(q, projection=None):
        return Cursor([dict(d) for d in logbooks if matches(q, d)])

    async def count_documents(q):
        return len([d for d in logbooks if matches(q, d)])

    db = MagicMock()
    db.logbooks.find = find
    db.logbooks.count_documents = AsyncMock(side_effect=count_documents)
    db.checkins.find = lambda q, projection=None: Cursor([])
    db.workers.find_one = AsyncMock(return_value=None)
    db.projects.find_one = AsyncMock(return_value=dict(PROJECT))

    with patch.object(server, "db", db), \
         patch.object(server, "eastern_date", lambda: "2026-08-26"), \
         patch.object(server, "_get_worker_project_trade", AsyncMock(return_value=None)):
        return asyncio.run(server.get_logbook_notifications(
            project_id="projA", current_user=CP, _proj=PROJECT,
        ))


def _row(log_type, date, sig, status="submitted", is_locked=False):
    return {"_id": f"{log_type}-{date}", "project_id": "projA", "log_type": log_type,
            "date": date, "status": status, "is_locked": is_locked,
            "cp_signature": sig}


def _state(result, log_type, date):
    for g in result["attestation_gaps"]:
        if g["log_type"] == log_type and g["date"] == date:
            return g["state"]
    return None


class AnInklessRowIsUnsignedAndStaysVisible(unittest.TestCase):
    """The regression the third selector exists to prevent."""

    def test_an_inkless_immediate_type_is_reported(self):
        """NEITHER OTHER SELECTOR REACHES IT. The stale pass is END_OF_DAY
        only, and requiring ink drops it from the unaffirmed query -- so
        without the third selector this row is on no screen at all."""
        r = _notifications([_row("toolbox_talk", "2026-08-25", EMPTY)])
        self.assertEqual(_state(r, "toolbox_talk", "2026-08-25"), "unsigned")

    def test_an_inkless_end_of_day_row_dated_TODAY_is_reported(self):
        """The stale pass requires date < today, so today's row falls through
        it as well."""
        r = _notifications([_row("daily_jobsite", "2026-08-26", EMPTY)])
        self.assertEqual(_state(r, "daily_jobsite", "2026-08-26"), "unsigned")

    def test_it_is_UNSIGNED_not_unaffirmed(self):
        """The whole point. `unaffirmed` deep-links to "tap your signature to
        affirm it. You do not need to sign again" -- over an empty pad."""
        r = _notifications([_row("preshift_signin", "2026-08-25", EMPTY)])
        self.assertNotEqual(_state(r, "preshift_signin", "2026-08-25"), "unaffirmed")

    def test_the_forged_shape_is_reported_as_unsigned(self):
        """affirmed: True with no ink. It passes _is_affirmed_signature, so
        every affirmation-based selector calls it finished; only ink refuses."""
        r = _notifications([_row("toolbox_talk", "2026-08-25", AFFIRMED_INKLESS)])
        self.assertEqual(_state(r, "toolbox_talk", "2026-08-25"), "unsigned")

    def test_a_null_signature_on_a_filed_log_is_reported(self):
        """A submitted log with no signature field is unsigned by the plainest
        reading. The stale pass already surfaced this for end-of-day rows; the
        third selector extends it to the types and dates it could not reach."""
        r = _notifications([_row("toolbox_talk", "2026-08-25", None)])
        self.assertEqual(_state(r, "toolbox_talk", "2026-08-25"), "unsigned")

    def test_a_DRAFT_is_not_reported(self):
        """The selector is about FILED records. An unfinished draft is not a
        deficiency, it is work in progress -- and refusing to say so is how an
        unfilled form stops a man from working."""
        r = _notifications([_row("toolbox_talk", "2026-08-25", EMPTY, status="draft")])
        self.assertIsNone(_state(r, "toolbox_talk", "2026-08-25"))

    def test_a_deleted_row_is_not_reported(self):
        row = _row("toolbox_talk", "2026-08-25", EMPTY)
        row["is_deleted"] = True
        r = _notifications([row])
        self.assertIsNone(_state(r, "toolbox_talk", "2026-08-25"))


class RealInkStillReadsAsUnaffirmed(unittest.TestCase):
    """A guard that over-reaches is as wrong as one that reaches nothing. The
    inherited-credential case is what the affirm copy was written for."""

    def test_an_inherited_credential_is_unaffirmed_not_unsigned(self):
        r = _notifications([_row("toolbox_talk", "2026-08-25", INHERITED)])
        self.assertEqual(_state(r, "toolbox_talk", "2026-08-25"), "unaffirmed")

    def test_a_raster_credential_too(self):
        r = _notifications([_row("toolbox_talk", "2026-08-25", RASTER)])
        self.assertEqual(_state(r, "toolbox_talk", "2026-08-25"), "unaffirmed")

    def test_an_affirmed_row_is_no_gap_at_all(self):
        r = _notifications([_row("toolbox_talk", "2026-08-25", AFFIRMED)])
        self.assertIsNone(_state(r, "toolbox_talk", "2026-08-25"))
        self.assertEqual(r["attestation_gaps"], [])

    def test_unaffirmed_still_wins_over_unsigned_for_an_inked_row(self):
        """An inked-but-unaffirmed END_OF_DAY row on a past date matches the
        stale pass AND the unaffirmed pass. The more specific state wins --
        unchanged behaviour, pinned because the third selector inserts a new
        writer between them."""
        r = _notifications([_row("daily_jobsite", "2026-08-24", INHERITED)])
        self.assertEqual(_state(r, "daily_jobsite", "2026-08-24"), "unaffirmed")

    def test_the_two_states_do_not_collide_on_one_row(self):
        """Ink partitions them: an inkless row cannot reach the unaffirmed
        query, and an inked one cannot reach the third selector."""
        rows = [_row("toolbox_talk", "2026-08-25", EMPTY),
                _row("preshift_signin", "2026-08-25", INHERITED)]
        r = _notifications(rows)
        self.assertEqual(_state(r, "toolbox_talk", "2026-08-25"), "unsigned")
        self.assertEqual(_state(r, "preshift_signin", "2026-08-25"), "unaffirmed")


class TheLegacyFieldsStillAnswer(unittest.TestCase):
    """Bundles in the field read these. This whole incident exists because a
    two-week-old phone cannot take an OTA."""

    def test_the_old_fields_are_still_returned(self):
        r = _notifications([_row("toolbox_talk", "2026-08-25", INHERITED)])
        for key in ("unaffirmed_logbooks", "unaffirmed_logbook_refs",
                    "stale_unsigned_logbooks", "stale_unsigned_logbook_refs",
                    "attestation_gaps"):
            self.assertIn(key, r)

    def test_an_inkless_row_no_longer_inflates_the_unaffirmed_count(self):
        """It moves OUT of that count. Production held zero such rows, so no
        live number changes -- but the direction is the point."""
        r = _notifications([_row("toolbox_talk", "2026-08-25", EMPTY)])
        self.assertEqual(r["unaffirmed_logbooks"], 0)

    def test_an_inked_unaffirmed_row_still_counts(self):
        r = _notifications([_row("toolbox_talk", "2026-08-25", INHERITED)])
        self.assertEqual(r["unaffirmed_logbooks"], 1)


class ScopeOfThisChange(unittest.TestCase):
    """The third PR is sequenced separately and this pins that it has not
    landed here."""

    SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text(
        encoding="utf-8")

    def test_is_affirmed_signature_does_NOT_yet_require_ink(self):
        """INVERT WHEN THE THIRD PR LANDS. Requiring ink there changes what the
        PDF prints and what the submit gate accepts, and it has to move on the
        client in the SAME DEPLOY -- signatureAffirmed.js states the mirror
        invariant. Zero rows are affected today, so it can be sequenced rather
        than rushed."""
        self.assertTrue(server._is_affirmed_signature(AFFIRMED_INKLESS))

    def test_the_renderer_still_prints_an_inkless_affirmation_as_affirmed(self):
        """The consequence that third PR closes, stated as a fact rather than
        left implied."""
        html = server._signature_affirmation_html(AFFIRMED_INKLESS)
        self.assertIn("AFFIRMED for this document", html)

    def test_the_two_predicates_are_neighbours_in_the_source(self):
        """They are one rule in two halves and are read together. Separating
        them is how the query and the function drift."""
        i = self.SRC.index("def _is_affirmed_signature")
        j = self.SRC.index("def _has_signature_ink")
        k = self.SRC.index("_SIGNATURE_HAS_INK_CLAUSES = [")
        self.assertLess(i, j)
        self.assertLess(j, k)
        self.assertLess(k - i, 4000, "the ink rule drifted away from its twin")

    def test_the_mirror_is_named_in_the_docstring(self):
        body = self.SRC[self.SRC.index("def _has_signature_ink"):]
        body = body[:body.index("_SIGNATURE_HAS_INK_CLAUSES = [")]
        self.assertIn("signatureAffirmed.js", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
