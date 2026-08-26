"""A submit gate that asks whether a signature EXISTS is not a signature gate.

WHAT IT WAS. Both endpoints tested presence:

    create_logbook   if not data.cp_signature
    update_logbook   if not _eff_sig

In PYTHON `not {}` is True, so those refused None and {} -- and accepted
anything with a key in it. What walked through was the POPULATED inherited
credential. 65 submitted logs on one project carry a signature that attests to
nothing, and every one prints "UNAFFIRMED - inherited signature, not affirmed
for this document" on its PDF. The app gated on one rule and the document
printed another.

(The `!{}` reading that let an EMPTY object through is the JS half, on the
client gates -- signatureAffirmed.js. Different language, different
truthiness. test_the_empty_dict_is_refused_too passes against main for that
reason, and is kept as an anchor rather than a regression.)

WHAT IT IS. Both call _is_affirmed_signature -- the SAME predicate the PDF
renderer (_signature_affirmation_html), the EOD sweep
(sweep_stale_end_of_day_logs) and generate_combined_report already ask. There
is no second definition, and this file asserts that there is not.

THE SHAPE THIS REFUSES, reproduced from production. The CP's cached profile
credential: paths, a signer name, a timestamp from the day he last affirmed
something else, and affirmedLang -- everything except an affirmation of THIS
document.

WHAT IT MUST NOT BREAK, each asserted below:

  drafts              a draft with no signature at all is the normal working
                      state; the refusal is on status == 'submitted' only
  the repair path     a CP fixing one of the existing unaffirmed rows posts
                      cp_signature with affirmed true -- if that were refused,
                      the 65 would be permanently unrepairable
  amendment           a different endpoint, untouched
  the gate            register_and_checkin DOES write a logbook -- a
                      subcontractor orientation -- but as status "draft" with
                      cp_signature None, inserted directly rather than through
                      create_logbook. Neither can reach this gate.

    python backend/tests/test_affirmation_enforced_on_submit.py
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

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402

SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")

ADMIN = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "companyA",
         "account_status": "approved", "assigned_projects": ["projA"]}
PROJECT = {"_id": "projA", "company_id": "companyA", "name": "588 Thomas"}
DATA = {"entries": [{"topic": "ladders"}]}

# ── The exact production shape ───────────────────────────────────────────────
# The CP's cached credential on 2026-08-25: byte-identical paths to the
# 2026-08-19 signature, that day's timestamp frozen on it, affirmedLang left
# behind by a strip that named only two of three fields -- and no affirmation
# of the document being filed.
INHERITED_CREDENTIAL = {
    "paths": [[1, 2], [3, 4]],
    "signerName": "Roy Fishman",
    "timestamp": "2026-08-19T15:01:10.726Z",
    "affirmedLang": "en",
}
EMPTY_DICT = {}
AFFIRMED = {"paths": [[1, 2]], "signerName": "Roy Fishman",
            "affirmed": True, "affirmedAt": "2026-08-26T07:00:00Z"}


def _create(sig, status="submitted", data=DATA):
    body = server.LogbookCreate(project_id="projA", log_type="toolbox_talk",
                                date="2026-08-26", data=data,
                                cp_signature=sig, cp_name="Roy", status=status)
    db = MagicMock()
    db.projects.find_one = AsyncMock(return_value=dict(PROJECT))
    # BEFORE the insert this answers the dedupe lookup (nothing matches, so a
    # new log is created); AFTER it, the read-back. One double returning None
    # to both makes create_logbook return None, and every "passes" assertion
    # then fails for a reason unrelated to the gate.
    inserted = {"yes": False}

    async def _find_one(q, *a, **kw):
        if not inserted["yes"]:
            return None
        return {"_id": "new1", "status": status, "cp_signature": sig}

    async def _insert_one(doc, *a, **kw):
        inserted["yes"] = True
        r = MagicMock(); r.inserted_id = "new1"
        return r

    db.logbooks.find_one = AsyncMock(side_effect=_find_one)
    db.logbooks.count_documents = AsyncMock(return_value=0)
    db.logbooks.insert_one = AsyncMock(side_effect=_insert_one)
    with patch.object(server, "db", db), \
         patch.object(server, "audit_log", AsyncMock()), \
         patch.object(server, "_remember_other_activities", AsyncMock()), \
         patch.object(server, "_enhance_logbook_photos", AsyncMock()):
        return asyncio.run(server.create_logbook(data=body, current_user=ADMIN))


def _update(stored, body_kwargs):
    written = {"yes": False}

    async def find_one(q, *a, **kw):
        return dict(stored)

    async def update_one(q, upd, *a, **kw):
        written["yes"] = True
        r = MagicMock(); r.matched_count = 1
        return r

    db = MagicMock()
    db.logbooks.find_one = AsyncMock(side_effect=find_one)
    db.logbooks.update_one = AsyncMock(side_effect=update_one)
    db.projects.find_one = AsyncMock(return_value=dict(PROJECT))
    body = server.LogbookUpdate(**body_kwargs)
    with patch.object(server, "db", db), \
         patch.object(server, "audit_log", AsyncMock()), \
         patch.object(server, "_remember_other_activities", AsyncMock()):
        asyncio.run(server.update_logbook(logbook_id="lb1", data=body,
                                          current_user=ADMIN))
    return written["yes"]


STORED_DRAFT = {"_id": "lb1", "project_id": "projA", "log_type": "toolbox_talk",
                "date": "2026-08-26", "status": "draft", "is_locked": False,
                "data": DATA, "cp_signature": None}


class TheInheritedCredentialIsRefused(unittest.TestCase):
    """The shape that produced 65 unattested filed logs."""

    def test_create_refuses_it(self):
        with self.assertRaises(HTTPException) as c:
            _create(INHERITED_CREDENTIAL)
        self.assertEqual(c.exception.detail, {"code": "SUBMIT_MISSING_CP_SIGNATURE"})

    def test_update_refuses_it(self):
        """The path the CP actually walks: Save Draft, then Submit as a PUT."""
        with self.assertRaises(HTTPException) as c:
            _update(STORED_DRAFT, {"status": "submitted",
                                   "cp_signature": INHERITED_CREDENTIAL})
        self.assertEqual(c.exception.detail, {"code": "SUBMIT_MISSING_CP_SIGNATURE"})

    def test_it_is_populated_not_empty(self):
        """ANCHOR. This is not the `{}` case -- it has paths, a signer name and
        a timestamp. It looks like a signature in every way except the one that
        matters, which is why presence never caught it."""
        self.assertTrue(INHERITED_CREDENTIAL["paths"])
        self.assertTrue(INHERITED_CREDENTIAL["signerName"])
        self.assertIsNone(INHERITED_CREDENTIAL.get("affirmed"))

    def test_the_empty_dict_is_refused_too(self):
        """ANCHOR, not a regression: the PRESENCE gate already refused this,
        because `not {}` is True in Python. It is the CLIENT gates that `{}`
        walked through. Pinned so the Python behaviour is not later assumed to
        match the JS."""
        with self.assertRaises(HTTPException) as c:
            _create(EMPTY_DICT)
        self.assertEqual(c.exception.detail, {"code": "SUBMIT_MISSING_CP_SIGNATURE"})

    def test_a_bare_string_never_reaches_the_gate(self):
        """A legacy base64 credential is refused EARLIER, by the model:
        LogbookCreate.cp_signature is Optional[Dict]. Pinned so the predicate is
        not credited with a refusal pydantic makes, and so that loosening the
        model fails here rather than silently widening what the gate judges."""
        import pydantic
        with self.assertRaises(pydantic.ValidationError):
            server.LogbookCreate(
                project_id="projA", log_type="toolbox_talk", date="2026-08-26",
                data=DATA, cp_signature="data:image/png;base64,AAA",
                cp_name="Roy", status="submitted",
            )

    def test_affirmed_false_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _create({**INHERITED_CREDENTIAL, "affirmed": False})
        self.assertEqual(c.exception.detail, {"code": "SUBMIT_MISSING_CP_SIGNATURE"})


class DraftsAreUnconstrained(unittest.TestCase):
    """A draft with no signature is the normal working state -- it is most of
    the CP's day."""

    def test_create_a_draft_with_no_signature(self):
        out = _create(None, status="draft")
        self.assertTrue(out)

    def test_create_a_draft_with_an_inherited_credential(self):
        """He has not affirmed yet. That is not an error, it is Tuesday."""
        out = _create(INHERITED_CREDENTIAL, status="draft")
        self.assertTrue(out)

    def test_update_a_draft_with_no_signature(self):
        self.assertTrue(_update(STORED_DRAFT, {"data": {"entries": [{"topic": "x"}]}}))

    def test_update_a_draft_with_an_inherited_credential(self):
        self.assertTrue(_update(STORED_DRAFT,
                                {"cp_signature": INHERITED_CREDENTIAL}))


class TheRepairPathStaysOpen(unittest.TestCase):
    """If this closed, the existing unaffirmed rows would be permanently
    unrepairable -- worse than the hole."""

    STORED_UNAFFIRMED = {
        "_id": "lb1", "project_id": "projA", "log_type": "toolbox_talk",
        "date": "2026-08-19", "status": "submitted", "is_locked": False,
        "data": DATA, "cp_signature": INHERITED_CREDENTIAL,
    }

    def test_affirming_an_existing_unaffirmed_log_passes(self):
        """cp_signature with affirmed true, no data. THE remedy for the 65."""
        self.assertTrue(_update(self.STORED_UNAFFIRMED,
                                {"cp_signature": AFFIRMED}))

    def test_and_it_passes_even_when_the_request_repeats_the_status(self):
        """_eff_sig is the NEW signature, so the gate judges what will be
        stored rather than what is stored."""
        self.assertTrue(_update(self.STORED_UNAFFIRMED,
                                {"cp_signature": AFFIRMED, "status": "submitted"}))

    def test_an_affirmed_submit_passes_on_create(self):
        self.assertTrue(_create(AFFIRMED))

    def test_an_affirmed_submit_passes_on_update(self):
        self.assertTrue(_update(STORED_DRAFT,
                                {"status": "submitted", "cp_signature": AFFIRMED}))


class OnePredicateOnly(unittest.TestCase):
    """The rule has one definition. A second would drift from the PDF."""

    def test_both_gates_call_the_shared_predicate(self):
        for fn in ("async def create_logbook", "async def update_logbook"):
            i = SRC.index(fn)
            nxt = SRC.find("\nasync def ", i + 1)
            body = SRC[i:nxt if nxt > 0 else len(SRC)]
            with self.subTest(fn=fn):
                self.assertIn("not _is_affirmed_signature(", body)

    def test_neither_gate_still_tests_presence(self):
        for fn, expr in (("async def create_logbook", "if not data.cp_signature:"),
                         ("async def update_logbook", "if not _eff_sig:")):
            i = SRC.index(fn)
            nxt = SRC.find("\nasync def ", i + 1)
            body = SRC[i:nxt if nxt > 0 else len(SRC)]
            with self.subTest(fn=fn):
                self.assertNotIn(expr, body)

    def test_there_is_exactly_one_definition(self):
        self.assertEqual(SRC.count("def _is_affirmed_signature("), 1)

    def test_the_readers_still_share_it(self):
        """The PDF renderer, the sweep and the combined report already asked
        this question. The gate now asks the same one."""
        self.assertGreaterEqual(SRC.count("_is_affirmed_signature("), 6)


class UntouchedSurfaces(unittest.TestCase):

    def test_amend_is_a_different_endpoint(self):
        paths = {getattr(r, "path", "") for r in server.app.routes}
        self.assertIn("/api/logbooks/{logbook_id}/amend", paths)

    def test_amend_does_not_gate_on_affirmation(self):
        """A correction to a filed log must not require re-affirming the
        ORIGINAL -- the child carries its own signature."""
        i = SRC.index("async def amend_logbook")
        nxt = SRC.find("\nasync def ", i + 1)
        self.assertNotIn("_is_affirmed_signature", SRC[i:nxt])

    def test_the_gate_path_writes_only_an_UNSIGNED_DRAFT(self):
        """register_and_checkin DOES write a logbook -- a subcontractor
        orientation for the worker who just enrolled. I asserted it did not,
        and that was wrong.

        The invariant that matters is WHAT it writes: `status: "draft"` with
        `cp_signature: None`, carrying the comment "CP must add signature to
        submit". A draft with no signature is exactly the state this change
        leaves unconstrained, so the affirmation gate cannot refuse it.

        It also inserts DIRECTLY rather than calling create_logbook, so it does
        not pass through the gate at all. Both facts are pinned: either one
        changing would put a refusal in front of a man at a turnstile, which
        the standing ruling forbids."""
        i = SRC.index("async def register_and_checkin")
        nxt = SRC.find("\nasync def ", i + 1)
        body = SRC[i:nxt]
        self.assertIn('"status": "draft",  # CP must add signature to submit', body)
        self.assertIn('"cp_signature": None,', body)
        self.assertNotIn("_is_affirmed_signature", body)
        self.assertNotIn("create_logbook(", body)

    def test_submit_checkin_writes_no_logbook_at_all(self):
        i = SRC.index("async def submit_checkin")
        nxt = SRC.find("\nasync def ", i + 1)
        body = SRC[i:nxt]
        self.assertNotIn("db.logbooks.insert_one", body)
        self.assertNotIn("_is_affirmed_signature", body)

    def test_the_gate_routes_are_still_public(self):
        for r in server.app.routes:
            if getattr(r, "path", "") != "/api/checkin/register-and-checkin":
                continue
            names = {d.call.__name__ for d in r.dependant.dependencies
                     if getattr(d, "call", None)}
            self.assertEqual(names & {"get_current_user", "require_approved"}, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
