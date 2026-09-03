"""A CORRECTION NOBODY MEANT TO MAKE HAD NO WAY OUT.

── THE PRODUCTION STATE ────────────────────────────────────────────────────────

Seven unsigned amendment drafts on `daily_jobsite` for ONE project:

    2026-09-02 19:46  draft  parent 6a9824b29bc6408dd7130c48
    2026-08-31 22:41  draft  parent 6a957dba611a543244a9ccba
    2026-08-14 20:24  draft  parent 6a7f1404bb9fdd3a9e6b96ac
    2026-08-14 20:23  draft  parent 6a7f1404bb9fdd3a9e6b96ac
    2026-08-10 20:11  draft  parent 6a79bc469d8cee518e4712d0
    2026-08-10 20:10  draft  parent 6a79bc469d8cee518e4712d0
    2026-08-07 20:36  draft  parent 6a75c6e0050e6e8ae686ea5d

Aug 10 and Aug 14 each have TWO drafts on ONE parent, sixty and twenty-six
seconds apart. A superintendent tapped Amend, nothing on the screen appeared to
change, and he tapped again.

There was no `withdrawn` state, so every one of those rows warns on his
compliance card forever. The only two exits were both wrong:

    SIGN IT    files a correction he may not intend -- and on a FORK, one of
               two competing versions, with nothing recording which he meant.
    DELETE IT  destroys a document. It also refused him outright until #371:
               `delete_logbook` read `current_user["_id"]` on an object where
               `serialize_id` had already deleted that key, so `user_id` was ""
               on every request and no CP could delete his own logbook. That
               fix is on main; this endpoint composes with it rather than
               repeating it, and asserts below that it uses the same accessor.

── WHAT IS BUILT ───────────────────────────────────────────────────────────────

A STATE, NOT A DELETE. `status: "withdrawn"` on the amendment child. Its data,
its reason, its author, its parent link and its timestamps are untouched. What
changes is what it CLAIMS to be.

ATTESTED, in two places, and the pair is the argument:

    ON THE DOCUMENT   withdrawn_by / withdrawn_by_name / withdrawn_at, all
                      server-stamped in the SAME update that sets the state.
                      This is the durable half and it has to be: `audit_log`
                      swallows its own exceptions, so the ledger row can
                      silently fail to exist and leave a state change with
                      nobody's name on it.
    IN audit_log      `logbook_withdraw`, beside the `logbook_amend` row it
                      answers.

NOT a signature_event. That collection's unique index is literally named
`signature_events_one_row_per_signing_act`; its `version` counts the signings
of a document; `create_signature_event` wants `signature_data` and a
`content_snapshot`; and `attach_attestation` exists to capture THE SENTENCE
PRINTED ABOVE A SIGNATURE. A withdrawal has no signature, no sentence above
one, and no content being attested to -- the content is precisely what is being
abandoned. A row there would bump the document's signature version and assert a
signing act that did not happen, which is the fabricated attestation
`ensure_signature_ledger_row` already refuses to mint. Asserted below.

REFUSES A FILED AMENDMENT. `is_locked` or `status == "submitted"` -- the two
clauses `_filed_log` uses, now asked through the ONE predicate they share.

── THE CONSUMERS ───────────────────────────────────────────────────────────────

A state nothing reads is a state that changes nothing. Every selector that
hunts for unfinished work asks what a document is NOT (`is_locked: {$ne: True}`,
`status: {$ne: "submitted"}`) and a withdrawn child satisfies BOTH, so each one
had to be told. Covered here: `open_amendment_head`, `_filed_log`, the
stale-unsigned scan behind `attestation_gaps`, the nightly end-of-day sweep and
its `unsigned_stale_logbook` alert, `unsigned_orientations`, the project list
read every editor makes, and the update/finalize writers that could otherwise
resurrect one.

Run:  python -m pytest backend/tests/test_amendment_withdraw.py -q
"""

import asyncio
import json
import inspect
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402


def code_of(func) -> str:
    """A function's source with comments and its docstring stripped.

    Every source assertion in this file is about what the CODE does. These
    functions carry long explanatory comments that name the very symbols being
    asserted absent, so a plain `getsource` would let the prose answer for the
    implementation -- the exact failure mode of asserting a rule by grepping a
    comment that claims it.
    """
    src = inspect.getsource(func)
    src = re.sub(r'"""(?:.|\n)*?"""', "", src, count=1)
    return "\n".join(line.split("#")[0] for line in src.split("\n"))


T0 = datetime(2026, 8, 14, 20, 23, 11, tzinfo=timezone.utc)

PROJ = {"_id": "projA", "id": "projA", "company_id": "companyA",
        "name": "588 Thomas"}

# The shape get_current_user ACTUALLY hands a handler: `id`, and no `_id`.
# A fixture carrying both keys passes against a broken accessor and proves
# nothing -- the lesson of #371.
SUPER = {"id": "u-super", "role": "superintendent", "company_id": "companyA",
         "account_status": "approved", "full_name": "Michael Cespedes",
         "assigned_projects": ["projA"]}
OTHER_CP = {"id": "u-other", "role": "cp", "company_id": "companyA",
            "account_status": "approved", "full_name": "Colleague CP",
            "assigned_projects": ["projA"]}
ADMIN = {"id": "u-admin", "role": "admin", "company_id": "companyA",
         "account_status": "approved", "full_name": "Admin A",
         "assigned_projects": []}

PARENT_ID = "6a7f1404bb9fdd3a9e6b96ac"

# What SignaturePad.handleConfirm actually emits: vector `paths`, the typed
# name, and a per-document affirmation stamp. Asserted against the SERVER's
# own two predicates rather than a hand-rolled shape, so a fixture cannot
# drift into something the endpoint would refuse in the field.
SIGNATURE = {
    "paths": [[{"x": 1, "y": 2}, {"x": 8, "y": 9}]],
    "signerName": "Michael Cespedes",
    "timestamp": "2026-09-02T19:46:00.000Z",
    "affirmed": True,
    "affirmedAt": "2026-09-02T19:46:00.000Z",
    "affirmedLang": "en",
}

# `data=None` has to stay reachable as a REAL value -- it is the shape a client
# that sends no body at all produces, and the signature refusal is exactly what
# must answer it. So the "give me the ordinary happy path" default cannot be
# None; it is a sentinel.
_UNSET = object()


def _child(_id="child-1", **over):
    """One of the seven. Unsigned, unlocked, is_amendment, with a parent."""
    doc = {
        "_id": _id, "id": _id,
        "project_id": "projA",
        "company_id": "companyA",
        "log_type": "daily_jobsite",
        "date": "2026-08-14",
        "data": {"work_description": "poured slab"},
        "cp_signature": None,
        "status": "draft",
        "is_locked": False,
        "is_amendment": True,
        "parent_logbook_id": PARENT_ID,
        "amendment_reason": "corrected count to 4",
        "created_by": "u-super",
        "created_by_name": "Michael Cespedes",
        "created_at": T0,
        "updated_at": T0,
        "is_deleted": False,
    }
    doc.update(over)
    return doc


def _run(user, doc, data=_UNSET, project=PROJ):
    """Call the real handler against a mock db. Returns (result, state).

    THE DEFAULT BODY CARRIES A SIGNATURE, because a withdrawal is an attested
    act and the endpoint refuses one without ink. Pass `data` explicitly --
    including `data=None` -- to exercise what a body missing it produces.
    """
    if data is _UNSET:
        data = {"signature": SIGNATURE}
    state = {"store": dict(doc), "audits": [], "sig_events": []}

    async def lb_find_one(q, *a, **kw):
        return dict(state["store"])

    async def lb_update_one(q, upd, *a, **kw):
        # The filter is load-bearing: the endpoint guards on
        # status != withdrawn so a second simultaneous tap matches nothing.
        _guard = (q or {}).get("status")
        if _guard == {"$ne": server.WITHDRAWN_STATUS} \
                and state["store"].get("status") == server.WITHDRAWN_STATUS:
            r = MagicMock(); r.matched_count = 0
            return r
        state["store"].update((upd or {}).get("$set") or {})
        r = MagicMock(); r.matched_count = 1
        return r

    async def proj_find_one(q, *a, **kw):
        return dict(project) if project else None

    db = MagicMock()
    db.logbooks.find_one = AsyncMock(side_effect=lb_find_one)
    db.logbooks.update_one = AsyncMock(side_effect=lb_update_one)
    db.projects.find_one = AsyncMock(side_effect=proj_find_one)

    async def fake_audit(action, actor, entity, entity_id, details=None):
        state["audits"].append({"action": action, "actor": actor,
                                "entity_id": entity_id,
                                "details": details or {}})

    async def fake_sig_event(*a, **kw):
        state["sig_events"].append({"args": a, "kwargs": kw})
        return "sig-1"

    with patch.object(server, "db", db), \
         patch.object(server, "audit_log", AsyncMock(side_effect=fake_audit)), \
         patch.object(server, "create_signature_event",
                      AsyncMock(side_effect=fake_sig_event)):
        result = asyncio.run(server.withdraw_amendment(
            logbook_id=doc["_id"], data=data, current_user=user))
    return result, state


# ══ THE ENDPOINT EXISTS AND IS ROUTED ═══════════════════════════════════════

class ThereIsAWayOut(unittest.TestCase):
    def test_the_endpoint_exists(self):
        self.assertTrue(hasattr(server, "withdraw_amendment"),
                        "there is no withdraw endpoint -- the seven drafts "
                        "still have only two exits, both wrong")

    def test_it_is_routed_at_logbooks_id_withdraw(self):
        paths = {getattr(r, "path", "") for r in server.app.routes}
        self.assertIn("/api/logbooks/{logbook_id}/withdraw", paths)

    def test_it_is_a_POST(self):
        for r in server.app.routes:
            if getattr(r, "path", "") == "/api/logbooks/{logbook_id}/withdraw":
                self.assertIn("POST", getattr(r, "methods", set()))
                return
        self.fail("route not found")


# ══ A STATE, NOT A DELETE ═══════════════════════════════════════════════════

class TheDocumentSurvives(unittest.TestCase):
    def test_the_state_is_withdrawn(self):
        out, state = _run(SUPER, _child())
        self.assertEqual(state["store"]["status"], server.WITHDRAWN_STATUS)
        self.assertEqual(out["status"], "withdrawn")

    def test_nothing_is_soft_deleted(self):
        """`is_deleted` is the DELETE flag and it must stay false: a withdrawal
        that set it would be a delete wearing a softer word, and the document
        would stop being readable at all."""
        _, state = _run(SUPER, _child())
        self.assertIsNot(state["store"].get("is_deleted"), True)
        self.assertIsNone(state["store"].get("deleted_at"))

    def test_the_content_is_untouched(self):
        """Data, reason, author, parent link, creation time. All of it is the
        evidence of what was attempted; a withdrawal erases none of it."""
        _, state = _run(SUPER, _child())
        s = state["store"]
        self.assertEqual(s["data"], {"work_description": "poured slab"})
        self.assertEqual(s["amendment_reason"], "corrected count to 4")
        self.assertEqual(s["created_by"], "u-super")
        self.assertEqual(s["created_by_name"], "Michael Cespedes")
        self.assertEqual(s["parent_logbook_id"], PARENT_ID)
        self.assertEqual(s["created_at"], T0)
        self.assertIs(s["is_amendment"], True)

    def test_the_parent_is_never_written(self):
        """Only the child is updated -- by _id, and only the child's id is ever
        passed to update_one."""
        _, _state = _run(SUPER, _child())
        # one update, and it names the child
        self.assertEqual(len(_state["audits"]), 1)
        self.assertEqual(_state["audits"][0]["entity_id"], "child-1")


# ══ ATTESTED: WHO, AND WHEN ═════════════════════════════════════════════════

class TheWithdrawalIsAttested(unittest.TestCase):
    """A withdrawal of a proposed correction to a compliance record is itself
    an act. It must record who did it and when."""

    def test_who(self):
        _, state = _run(SUPER, _child())
        self.assertEqual(state["store"]["withdrawn_by"], "u-super")
        self.assertEqual(state["store"]["withdrawn_by_name"], "Michael Cespedes")

    def test_when_is_SERVER_stamped_and_a_datetime(self):
        """Not the client's clock, and not a string: a device with a wrong
        clock must not be able to date an attestation."""
        before = datetime.now(timezone.utc)
        _, state = _run(SUPER, _child())
        after = datetime.now(timezone.utc)
        at = state["store"]["withdrawn_at"]
        self.assertIsInstance(at, datetime)
        self.assertTrue(before <= at <= after)

    def test_the_actor_is_read_id_FIRST_and_is_never_the_empty_string(self):
        """#371's defect, not repeated. `get_current_user` returns
        `serialize_id(user)`, which DELETES `_id` -- so `current_user["_id"]`
        is absent and an accessor reading it alone records nobody as the
        actor of an attested act."""
        _, state = _run(SUPER, _child())
        self.assertEqual(state["store"]["withdrawn_by"], "u-super")
        self.assertEqual(state["audits"][0]["actor"], "u-super")
        self.assertNotEqual(state["store"]["withdrawn_by"], "")

    def test_the_accessor_is_the_files_established_idiom(self):
        src = code_of(server.withdraw_amendment)
        self.assertIn(
            'str(current_user.get("id") or current_user.get("_id") or "")', src)
        self.assertNotIn('current_user.get("_id", "")', src)

    def test_the_audit_ledger_carries_the_act(self):
        _, state = _run(SUPER, _child())
        self.assertEqual(len(state["audits"]), 1)
        row = state["audits"][0]
        self.assertEqual(row["action"], "logbook_withdraw")
        self.assertEqual(row["details"]["parent_logbook_id"], PARENT_ID)
        self.assertEqual(row["details"]["log_type"], "daily_jobsite")
        self.assertEqual(row["details"]["date"], "2026-08-14")
        # What was PROPOSED, so the ledger tells the whole story.
        self.assertEqual(row["details"]["amendment_reason"],
                         "corrected count to 4")

    def test_a_withdrawal_reason_is_OPTIONAL_and_stored_when_given(self):
        """`amendment_reason` is gated hard because it explains a CHANGE to a
        signed record. This explains the ABSENCE of one, and the amendment's
        own reason is still on the document."""
        _, state = _run(SUPER, _child())
        self.assertIsNone(state["store"].get("withdrawal_reason"))
        _, state2 = _run(SUPER, _child(),
                         data={"reason": "double tap", "signature": SIGNATURE})
        self.assertEqual(state2["store"]["withdrawal_reason"], "double tap")
        self.assertEqual(state2["audits"][0]["details"]["withdrawal_reason"],
                         "double tap")

    def test_the_state_and_the_attestation_land_in_ONE_write(self):
        """Separated, an interruption between them leaves a correction
        withdrawn by nobody."""
        src = inspect.getsource(server.withdraw_amendment)
        self.assertEqual(src.count("db.logbooks.update_one"), 1)

    def test_the_record_can_SAY_it(self):
        out, state = _run(SUPER, _child())
        st = server.withdrawal_state(state["store"])
        self.assertTrue(st["withdrawn"])
        self.assertEqual(st["by_name"], "Michael Cespedes")
        sentence = server.withdrawal_sentence(st)
        self.assertIn("withdrawn", sentence)
        self.assertIn("Michael Cespedes", sentence)
        # And the response hands the client the sentence it just earned.
        self.assertEqual(out.get("withdrawal_sentence"), sentence)

    def test_the_sentence_is_empty_for_a_record_that_was_not_withdrawn(self):
        self.assertEqual(
            server.withdrawal_sentence(server.withdrawal_state(_child())), "")
        self.assertEqual(server.withdrawal_sentence(None), "")

    def test_the_sentence_reads_the_RECORD_never_the_clock(self):
        """An amendment withdrawn in September says the same thing in
        December -- the same rule amendment_sentence follows."""
        doc = _child(status="withdrawn", withdrawn_by_name="Michael Cespedes",
                     withdrawn_at=datetime(2026, 9, 2, 1, 2, 3,
                                           tzinfo=timezone.utc))
        s1 = server.withdrawal_sentence(server.withdrawal_state(doc))
        self.assertIn("2026-09-02", s1)
        self.assertEqual(s1, server.withdrawal_sentence(
            server.withdrawal_state(doc)))

    def test_an_unattributed_withdrawal_READS_as_unattributed(self):
        """A script or a migration that recorded no actor must not be filled
        in with a guess."""
        doc = _child(status="withdrawn",
                     withdrawn_at=datetime(2026, 9, 2, tzinfo=timezone.utc))
        st = server.withdrawal_state(doc)
        self.assertTrue(st["withdrawn"])
        self.assertIsNone(st["by_name"])
        # The "by X" clause is OMITTED, not filled with a placeholder. Asserted
        # as a prefix rather than as the absence of " by ", which would also
        # pass on a sentence that had lost its opening altogether.
        self.assertTrue(
            server.withdrawal_sentence(st).startswith(
                "This proposed correction was withdrawn on 2026-09-02."),
            server.withdrawal_sentence(st))


class ASignatureIsRequired(unittest.TestCase):
    """OPERATOR RULING: "Signature required, as ruled. It is an attested act."

    A withdrawal is a permanent statement about a compliance record -- that a
    proposed correction was abandoned, deliberately, by a named person. The
    ruling is that it is signed for like any other attested act.

    THE INK IS JUDGED BY THE SERVER'S OWN PREDICATES, not by presence. A
    `cp_signature: {}` satisfied every presence gate in this app while every
    document it signed printed UNAFFIRMED; `_has_signature_ink` exists because
    of that. An empty object, an empty `paths` list and an inkless
    `{"affirmed": True}` are all NOT a signature, and each is asserted."""

    def test_a_withdrawal_with_NO_body_at_all_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _run(SUPER, _child(), data=None)
        self.assertEqual(c.exception.status_code, 400)
        self.assertEqual(c.exception.detail["code"],
                         server.WITHDRAW_SIGNATURE_REQUIRED)

    def test_a_body_with_a_reason_but_no_signature_is_refused(self):
        """The shape the PREVIOUS client sent. It must not still work."""
        with self.assertRaises(HTTPException) as c:
            _run(SUPER, _child(), data={"reason": "double tap"})
        self.assertEqual(c.exception.status_code, 400)

    def test_an_EMPTY_OBJECT_is_not_a_signature(self):
        """The shape production actually held."""
        with self.assertRaises(HTTPException) as c:
            _run(SUPER, _child(), data={"signature": {}})
        self.assertEqual(c.exception.status_code, 400)

    def test_an_INKLESS_affirmation_is_not_a_signature(self):
        """`{"affirmed": True}` passes _is_affirmed_signature and fails
        _has_signature_ink. An affirmation over a blank canvas is the one
        shape a pad must never mint, and this endpoint must not accept it."""
        with self.assertRaises(HTTPException) as c:
            _run(SUPER, _child(),
                 data={"signature": {"affirmed": True, "paths": []}})
        self.assertEqual(c.exception.status_code, 400)

    def test_nothing_is_written_when_the_signature_is_missing(self):
        """A refusal that had already flipped the state would be worse than
        no refusal."""
        doc = _child()
        try:
            _run(SUPER, doc, data=None)
        except HTTPException:
            pass
        self.assertEqual(doc["status"], "draft")

    def test_the_refusal_comes_AFTER_the_filed_and_shape_refusals(self):
        """A filed amendment and a non-amendment are refused whatever the
        caller sends, so asking for a signature first would put a pad in front
        of a man to answer a question the server had already settled."""
        with self.assertRaises(HTTPException) as c:
            _run(SUPER, _child(is_locked=True), data=None)
        self.assertEqual(c.exception.status_code, 423)
        with self.assertRaises(HTTPException) as c2:
            _run(SUPER, _child(is_amendment=False), data=None)
        self.assertEqual(c2.exception.status_code, 400)
        self.assertEqual(c2.exception.detail["code"],
                         server.WITHDRAW_NOT_AN_AMENDMENT)

    def test_the_SECOND_TAP_still_needs_no_signature(self):
        """Already withdrawn is a 200 no-op. Demanding ink to change nothing
        would put a pad in front of the exact double-tap this feature exists
        to absorb."""
        out, state = _run(
            SUPER,
            _child(status=server.WITHDRAWN_STATUS, withdrawn_by="u-first",
                   withdrawn_by_name="First Man", withdrawn_at=T0),
            data=None)
        self.assertEqual(state["store"]["withdrawn_by"], "u-first")
        self.assertEqual(state["audits"], [])


class TheAttestationOnTheDocument(unittest.TestCase):
    """WHERE THE SIGNATURE GOES, AND WHY NOT INTO signature_events.

    `signature_events`' unique index is literally named
    `signature_events_one_row_per_signing_act` and its `version` counts the
    signings OF ONE DOCUMENT'S CONTENT. A withdrawal row there would bump the
    document's signature version and assert a signing act on content nobody
    signed -- the fabricated attestation `ensure_signature_ledger_row` exists
    to refuse. The signature is real; the thing it attests to is not the
    content, it is the ABANDONMENT of the content.

    So it lands on the DOCUMENT, in the same `update_one` that sets the state,
    under a field whose shape no signature-ledger reader can mistake for a
    content signing."""

    def test_the_attestation_is_stored_on_the_document(self):
        _, state = _run(SUPER, _child())
        att = state["store"]["withdrawal_attestation"]
        self.assertEqual(att["ink"], SIGNATURE)

    def test_it_carries_the_statement_the_signer_was_shown(self):
        """`attach_attestation` exists elsewhere because a signature with no
        recorded sentence above it attests to nothing nameable. The same rule
        applies here, so the sentence is stored WITH the ink."""
        _, state = _run(SUPER, _child())
        att = state["store"]["withdrawal_attestation"]
        self.assertEqual(att["statement"],
                         server.WITHDRAWAL_ATTESTATION_STATEMENT)
        self.assertTrue(server.WITHDRAWAL_ATTESTATION_STATEMENT.strip())

    def test_the_signer_and_the_time_are_SERVER_stamped(self):
        """The client supplies ink and nothing else that matters. A device
        with a wrong clock must not be able to date an attestation, and a
        client must not be able to name someone else as its signer."""
        before = datetime.now(timezone.utc)
        _, state = _run(SUPER, _child(),
                        data={"signature": dict(SIGNATURE, signerName="Someone Else"),
                              "by": "u-forged", "at": "1999-01-01"})
        after = datetime.now(timezone.utc)
        att = state["store"]["withdrawal_attestation"]
        self.assertEqual(att["by"], "u-super")
        self.assertEqual(att["by_name"], "Michael Cespedes")
        self.assertIsInstance(att["at"], datetime)
        self.assertTrue(before <= att["at"] <= after)

    def test_it_lands_in_the_SAME_write_as_the_state(self):
        """audit_log swallows its own exceptions and cannot be the only
        record. A separate write for the ink could be interrupted and leave a
        withdrawal claiming to be attested with nothing attesting it."""
        src = inspect.getsource(server.withdraw_amendment)
        self.assertEqual(src.count("db.logbooks.update_one"), 1)
        _, state = _run(SUPER, _child())
        # One update carried all four: the state, the who, the when, the ink.
        for f in ("status", "withdrawn_by", "withdrawn_at",
                  "withdrawal_attestation"):
            self.assertIn(f, state["store"])

    def test_it_is_marked_as_a_WITHDRAWAL_and_never_a_content_signing(self):
        _, state = _run(SUPER, _child())
        self.assertEqual(state["store"]["withdrawal_attestation"]["kind"],
                         "withdrawal")

    def test_the_document_gains_NO_field_a_ledger_reader_keys_on(self):
        """THE POSITIVE CONTROL FOR "no reader picks it up". Both readers of a
        LOGBOOK's signature -- ensure_signature_ledger_row and
        sweep_signature_ledger_gaps -- read exactly one field, `cp_signature`.
        The withdrawal must not create one, must not overwrite the null that
        is already there, and must not add any sibling with a name either one
        could reach."""
        _, state = _run(SUPER, _child())
        self.assertIsNone(state["store"]["cp_signature"])
        added = set(state["store"]) - set(_child())
        self.assertEqual(added, {"withdrawn_at", "withdrawn_by",
                                 "withdrawn_by_name", "withdrawal_attestation"})

    def test_the_ledger_derivation_REFUSES_the_withdrawn_document(self):
        """Run the real reader against the real post-withdrawal document. An
        assertion about field names is a claim; this is the reader itself
        declining to mint a row."""
        _, state = _run(SUPER, _child())
        with patch.object(server, "db", MagicMock()):
            got = asyncio.run(server.ensure_signature_ledger_row(
                state["store"], written_by="test"))
        self.assertIsNone(got)

    def test_and_the_control_that_proves_that_check_can_FAIL(self):
        """The recurring defect of this codebase: a check that runs, returns a
        well-formed answer and never reaches its subject. The same reader,
        handed the same document with real ink in `cp_signature`, must get
        PAST the refusal -- otherwise the assertion above proves nothing."""
        _, state = _run(SUPER, _child())
        signed = dict(state["store"], cp_signature=SIGNATURE)
        db = MagicMock()
        db.signature_events.find_one = AsyncMock(return_value={"_id": "e1"})
        with patch.object(server, "db", db):
            got = asyncio.run(server.ensure_signature_ledger_row(
                signed, written_by="test"))
        self.assertIsNotNone(got)

    def test_the_nightly_sweep_cannot_reach_a_withdrawn_document_either(self):
        """It selects `status: "submitted"`. A withdrawn document's status is
        "withdrawn", so it is not in the cursor at all -- and this asserts the
        selector rather than trusting the sentence."""
        src = inspect.getsource(server.sweep_signature_ledger_gaps)
        self.assertIn('"status": "submitted"', src)
        self.assertIn('doc.get("cp_signature")', src)
        self.assertNotIn("withdrawal_attestation", src)

    def test_no_signature_event_is_written(self):
        _, state = _run(SUPER, _child())
        self.assertEqual(state["sig_events"], [])

    def test_the_endpoint_does_not_reach_for_the_ledger_at_all(self):
        """THE CODE, NOT THE PROSE. The docstring argues at length about
        signature_events, so the docstring is stripped before looking -- a
        grep over the whole function would pass on the explanation."""
        src = code_of(server.withdraw_amendment)
        self.assertNotIn("create_signature_event(", src)
        self.assertNotIn("ensure_signature_ledger_row(", src)
        self.assertNotIn("attach_attestation(", src)
        self.assertNotIn("db.signature_events", src)

    def test_the_premise_the_argument_rests_on(self):
        """If signature_events ever stops being one-row-per-signing-act, this
        argument needs revisiting -- so the premise is asserted, not assumed."""
        src = inspect.getsource(server)
        self.assertIn("signature_events_one_row_per_signing_act", src)
        sig = inspect.signature(server.create_signature_event)
        self.assertIn("signature_data", sig.parameters)
        self.assertIn("content_snapshot", sig.parameters)


# ══ REFUSE TO WITHDRAW A FILED AMENDMENT ════════════════════════════════════

class AFiledCorrectionIsARecord(unittest.TestCase):
    """Only an UNSIGNED draft can be withdrawn. `_filed_log` treats `is_locked`
    or `status == "submitted"` as filed, and this asks the same question
    through the predicate they now share."""

    def _refused(self, doc, user=SUPER):
        with self.assertRaises(HTTPException) as c:
            _run(user, doc)
        return c.exception

    def test_a_LOCKED_amendment_is_refused(self):
        e = self._refused(_child(is_locked=True, status="submitted"))
        self.assertEqual(e.status_code, 423)
        self.assertEqual(e.detail["code"], server.WITHDRAW_FILED_AMENDMENT)

    def test_a_SUBMITTED_but_unlocked_amendment_is_refused(self):
        """The END_OF_DAY window: submitted at 6pm, frozen by the sweep at 3am.
        A daily narrative spends every evening in this shape, and it is filed
        the whole time."""
        e = self._refused(_child(status="submitted", is_locked=False))
        self.assertEqual(e.status_code, 423)
        self.assertEqual(e.detail["code"], server.WITHDRAW_FILED_AMENDMENT)

    def test_nothing_is_written_when_a_filed_amendment_is_refused(self):
        doc = _child(is_locked=True)
        try:
            _, state = _run(SUPER, doc)
        except HTTPException:
            return
        self.fail(f"the withdraw went through on a filed amendment: {state}")

    def test_an_ADMIN_is_refused_too(self):
        """A filed correction is a record whoever is asking. The answer must
        not depend on who asks."""
        e = self._refused(_child(is_locked=True), user=ADMIN)
        self.assertEqual(e.status_code, 423)

    def test_a_SIGNED_BUT_UNFILED_draft_is_still_withdrawable(self):
        """Ink on an open draft is not a filed record -- `_filed_log` says so
        in as many words. He signed but never submitted; he may still take it
        back."""
        out, state = _run(SUPER, _child(cp_signature={"paths": [[]]}))
        self.assertEqual(state["store"]["status"], server.WITHDRAWN_STATUS)

    def test_the_filed_predicate_is_SHARED_and_not_a_fourth_copy(self):
        self.assertTrue(server.logbook_is_filed({"is_locked": True}))
        self.assertTrue(server.logbook_is_filed({"status": "submitted"}))
        self.assertFalse(server.logbook_is_filed({"status": "draft"}))
        self.assertFalse(server.logbook_is_filed({"cp_signature": {"x": 1}}))
        self.assertFalse(server.logbook_is_filed(None))
        self.assertIn("logbook_is_filed", inspect.getsource(server._filed_log))


class OnlyAnAmendmentMayBeWithdrawn(unittest.TestCase):
    def test_an_ORIGINAL_is_refused(self):
        """The original IS the day. Withdrawing one would be a delete wearing a
        softer word, and delete already exists with its own rule."""
        original = _child(is_amendment=False, parent_logbook_id=None,
                          amendment_reason=None)
        with self.assertRaises(HTTPException) as c:
            _run(SUPER, original)
        self.assertEqual(c.exception.status_code, 400)
        self.assertEqual(c.exception.detail["code"],
                         server.WITHDRAW_NOT_AN_AMENDMENT)

    def test_a_truthy_but_not_True_flag_is_not_an_amendment(self):
        """`is_amendment: 1` is a shape nobody wrote deliberately -- the same
        `is not True` rule the editors and amendment_state apply."""
        with self.assertRaises(HTTPException) as c:
            _run(SUPER, _child(is_amendment=1))
        self.assertEqual(c.exception.status_code, 400)


# ══ WHO MAY WITHDRAW ════════════════════════════════════════════════════════

class AnyAdminOrCPWithProjectAccess(unittest.TestCase):
    """OPERATOR RULING: "any admin or CP with project access. Not just the
    filer."

    THE FILER MIGHT BE THE PLATFORM OPERATOR. A correction filed on a CP's
    behalf by whoever was helping him would, under an author-only rule, be
    permanently un-withdrawable BY THE CP WHOSE CARD IT WARNS ON. Locking a
    permanent warning behind the person who was helping is the defect, not the
    control.

    THE RECORD IS THE ACCOUNTABILITY, NOT THE RESTRICTION. `withdrawn_by` /
    `withdrawn_by_name` / `withdrawn_at` name who took it back and when, in the
    same write that sets the state, and the attestation now carries his
    signature as well. That is what answers "who did this", and it answers it
    for a wider set of hands than an author check ever could.

    THE SET IS `_authorize_logbook_write`'s, EXACTLY -- admin/owner of the
    project's company, or anyone assigned to the project. Nothing wider: an
    unassigned CP of the right company and an admin of another company are
    both still refused, and this class asserts both rather than assuming the
    shared gate holds.

    WHAT DID NOT WIDEN: the 423 on a FILED amendment, which is asked BEFORE
    any actor question so an admin gets it too, and the 400 on a document that
    is not an amendment."""

    def test_the_author_may(self):
        _, state = _run(SUPER, _child())
        self.assertEqual(state["store"]["status"], server.WITHDRAWN_STATUS)

    def test_an_admin_may(self):
        _, state = _run(ADMIN, _child())
        self.assertEqual(state["store"]["withdrawn_by"], "u-admin")

    def test_an_ASSIGNED_CP_who_is_NOT_the_author_may(self):
        """The ruling, in one line. `created_by` is "u-super"; this is not
        him, is not an admin, and succeeds because he is assigned."""
        _, state = _run(OTHER_CP, _child())
        self.assertEqual(state["store"]["status"], server.WITHDRAWN_STATUS)
        self.assertNotEqual(_child()["created_by"], OTHER_CP["id"])

    def test_and_the_record_names_the_man_who_ACTUALLY_did_it(self):
        """Widening the door is only safe because the record narrows it back
        down to one name. The author's name stays on `created_by_name`; the
        withdrawer's goes on `withdrawn_by_name`, and they are different
        people here."""
        _, state = _run(OTHER_CP, _child())
        self.assertEqual(state["store"]["withdrawn_by"], "u-other")
        self.assertEqual(state["store"]["withdrawn_by_name"], "Colleague CP")
        self.assertEqual(state["store"]["created_by_name"], "Michael Cespedes")
        self.assertEqual(state["audits"][0]["actor"], "u-other")

    def test_an_UNASSIGNED_CP_of_the_right_company_is_still_refused(self):
        """`user_can_act_on_project` admits admin/owner of the company OR a
        user assigned to the project -- a plain CP of the right company with
        no assignment is neither, which is what create_logbook already does."""
        stranger = dict(OTHER_CP, assigned_projects=[])
        with self.assertRaises(HTTPException) as c:
            _run(stranger, _child())
        self.assertEqual(c.exception.status_code, 403)

    def test_an_admin_of_ANOTHER_company_is_still_refused(self):
        """The company scope on the admin branch. This admin belongs to
        companyB; the project is companyA's, and he is assigned to nothing."""
        foreign_admin = dict(ADMIN, company_id="companyB", id="u-admin-b")
        with self.assertRaises(HTTPException) as c:
            _run(foreign_admin, _child())
        self.assertEqual(c.exception.status_code, 403)

    def test_no_author_only_branch_survives_in_the_endpoint(self):
        """THE CODE, NOT THE PROSE -- the docstring discusses the author at
        length. A `created_by` comparison anywhere in the body would be the
        restriction growing back."""
        src = code_of(server.withdraw_amendment)
        self.assertNotIn("created_by", src)

    def test_an_unassigned_superintendent_is_out_before_any_of_it(self):
        """A superintendent is scoped to his assigned projects, exactly as a CP
        is. `_authorize_logbook_write` reaches him first -- its
        `user_can_act_on_project` already refuses an unassigned caller -- so
        the refusal is the tenant gate's, which is why the message is that one
        and not "Not assigned to this project"."""
        unassigned = dict(SUPER, assigned_projects=[])
        with self.assertRaises(HTTPException) as c:
            _run(unassigned, _child())
        self.assertEqual(c.exception.status_code, 403)

    def test_and_the_write_scope_gate_is_carried_anyway(self):
        """Belt and braces, and the same pair every other logbook writer
        carries -- update_logbook calls the second one "subsumed by the
        assigned branch above, and cheap". A rule written once in this file and
        omitted in one endpoint is exactly the drift #338 left behind."""
        src = code_of(server.withdraw_amendment)
        self.assertIn("ROLES_SCOPED_TO_ASSIGNED_PROJECTS", src)
        self.assertIn("_authorize_logbook_write", src)

    def test_another_companys_logbook_is_never_reachable(self):
        """`_authorize_logbook_write` runs first, as it does on the other
        four."""
        foreign = dict(PROJ, company_id="companyB", _id="projB", id="projB")
        with self.assertRaises(HTTPException) as c:
            _run(ADMIN, _child(project_id="projB"), project=foreign)
        self.assertEqual(c.exception.status_code, 403)


class TheSecondTapChangesNothing(unittest.TestCase):
    """THE WHOLE FEATURE EXISTS BECAUSE A MAN TAPPED A BUTTON TWICE. The second
    tap on THIS one must not overwrite the first withdrawal's attested author
    and timestamp, and must not stack a second audit row for one act."""

    ALREADY = dict(_child(), status="withdrawn", withdrawn_by="u-super",
                   withdrawn_by_name="Michael Cespedes",
                   withdrawn_at=T0 + timedelta(minutes=1))

    def test_it_returns_200_and_not_an_error(self):
        out, _ = _run(SUPER, dict(self.ALREADY))
        self.assertEqual(out["status"], "withdrawn")

    def test_the_first_withdrawals_attestation_stands(self):
        _, state = _run(ADMIN, dict(self.ALREADY))
        self.assertEqual(state["store"]["withdrawn_by"], "u-super")
        self.assertEqual(state["store"]["withdrawn_at"], T0 + timedelta(minutes=1))

    def test_no_second_audit_row(self):
        _, state = _run(SUPER, dict(self.ALREADY))
        self.assertEqual(state["audits"], [])

    def test_a_filed_amendment_is_still_refused_before_the_noop(self):
        """The 423 sits AHEAD of the idempotent return, so a filed one never
        gets a 200 by having been withdrawn first."""
        doc = dict(self.ALREADY, is_locked=True)
        with self.assertRaises(HTTPException) as c:
            _run(SUPER, doc)
        self.assertEqual(c.exception.status_code, 423)

    def test_the_update_filter_guards_the_race(self):
        """Two taps in flight at once: the loser's update matches nothing, so
        the winner's name is what stays on it."""
        src = inspect.getsource(server.withdraw_amendment)
        self.assertIn('"status": {"$ne": WITHDRAWN_STATUS}', src)


# ══ THE FORKS ═══════════════════════════════════════════════════════════════

class TwoDraftsOnOneParent(unittest.TestCase):
    """Aug 10 and Aug 14: two children of ONE parent, sixty and twenty-six
    seconds apart. Withdrawing one must leave the other untouched AND still
    selectable -- if it vanished with its twin, the CP would be left with a
    signed log and no idea a correction had ever been proposed."""

    A = _child("fork-a", created_at=T0)
    B = _child("fork-b", created_at=T0 + timedelta(seconds=26))

    def test_before_a_withdrawal_the_newest_is_the_head(self):
        self.assertEqual(
            server.open_amendment_head([self.A, self.B])["_id"], "fork-b")

    def test_withdrawing_the_HEAD_leaves_the_other_selectable(self):
        b_out = dict(self.B, status="withdrawn")
        head = server.open_amendment_head([self.A, b_out])
        self.assertIsNotNone(head)
        self.assertEqual(head["_id"], "fork-a")

    def test_withdrawing_the_OLDER_one_leaves_the_head_alone(self):
        a_out = dict(self.A, status="withdrawn")
        head = server.open_amendment_head([a_out, self.B])
        self.assertEqual(head["_id"], "fork-b")

    def test_withdrawing_BOTH_leaves_no_open_correction(self):
        head = server.open_amendment_head([
            dict(self.A, status="withdrawn"), dict(self.B, status="withdrawn")])
        self.assertIsNone(head)

    def test_the_survivor_is_not_mutated(self):
        """Only the id passed in is written. The mock db serves ONE document,
        so this asserts the endpoint never reaches for a sibling."""
        _, state = _run(SUPER, dict(self.B))
        self.assertEqual(state["store"]["_id"], "fork-b")


class AWithdrawnChildDoesNotBlockTheNextCorrection(unittest.TestCase):
    """The refusal that stops forks must not become the trap it replaced. A
    withdrawn child still counting as open would hold the parent's Amend button
    shut forever, and AMENDMENT_ALREADY_OPEN would keep offering the CP a
    correction he has already taken back."""

    def test_a_withdrawn_child_is_not_an_open_head(self):
        self.assertIsNone(server.open_amendment_head(
            [_child(status="withdrawn")]))

    def test_a_plain_draft_child_still_IS(self):
        """The control: without it, the test above passes for the wrong
        reason."""
        self.assertIsNotNone(server.open_amendment_head([_child()]))

    def test_a_signed_child_still_does_not_block(self):
        """Unchanged behaviour -- a correction that landed is part of the chain
        and the next amendment amends it."""
        self.assertIsNone(server.open_amendment_head(
            [_child(cp_signature={"paths": [[]]})]))

    def test_the_amend_endpoint_also_filters_them_out_of_the_query(self):
        src = inspect.getsource(server.amend_logbook)
        self.assertIn("WITHDRAWN_EXCLUDED", src)


# ══ NOTHING PRINTS A WITHDRAWN CORRECTION ═══════════════════════════════════

class TheReportNeverSelectsOne(unittest.TestCase):
    PARENT = {"_id": "p1", "log_type": "daily_jobsite", "created_at": T0,
              "is_locked": True, "status": "submitted"}

    def test_a_withdrawn_child_never_supersedes_the_signed_parent(self):
        """NEWER than the parent and carrying the lock flag, so the ordering
        would hand it the win: `_filed_log` picks the LATEST filed record. Only
        the withdrawn clause keeps the parent."""
        child = _child(status="withdrawn", is_locked=True,
                       created_at=T0 + timedelta(hours=3))
        got = server._filed_log([self.PARENT, child], "daily_jobsite")
        self.assertEqual(got["_id"], "p1")

    def test_and_the_UNFILED_FALLBACK_is_where_it_would_actually_have_leaked(self):
        """`same_type[0]` is insertion order. On a day whose original was never
        signed, a withdrawn child is a plain member of the list and the report
        could print a correction its own author took back -- to a lender."""
        unsigned_parent = {"_id": "p2", "log_type": "daily_jobsite",
                           "created_at": T0, "status": "draft"}
        withdrawn = _child("c2", status="withdrawn", created_at=T0)
        got = server._filed_log([withdrawn, unsigned_parent], "daily_jobsite")
        self.assertEqual(got["_id"], "p2")

    def test_a_day_with_ONLY_a_withdrawn_document_renders_nothing(self):
        """Better a blank section than a record nobody stands behind."""
        self.assertIsNone(server._filed_log(
            [_child(status="withdrawn")], "daily_jobsite"))

    def test_an_ordinary_unsigned_amendment_is_unchanged(self):
        """The control. `_filed_log` already declined to promote one; this
        change must not have altered that."""
        got = server._filed_log([self.PARENT, _child()], "daily_jobsite")
        self.assertEqual(got["_id"], "p1")


# ══ EVERY COUNTER STOPS COUNTING IT ═════════════════════════════════════════

class TheSelectorsWereAllTold(unittest.TestCase):
    """Each of these asks what a document is NOT -- `is_locked: {$ne: True}` or
    `status: {$ne: "submitted"}` -- and a withdrawn child satisfies both. The
    source is sliced rather than grepped loosely: the clause has to be inside
    the selector, not merely somewhere in the function."""

    def _selector_src(self, func, anchor):
        src = inspect.getsource(func)
        at = src.index(anchor)
        return src[at:at + 900]

    def test_the_stale_unsigned_scan_behind_the_compliance_card(self):
        """The exact selector the seven drafts sat in."""
        s = self._selector_src(server.get_logbook_notifications,
                               "stale_unsigned_docs = await db.logbooks.find")
        self.assertIn("WITHDRAWN_EXCLUDED", s)

    def test_the_unsigned_orientation_count(self):
        """It keys on `status != submitted`, which COLLIDES with the withdrawn
        clause -- spreading the constant in would have replaced the submitted
        test and started counting every filed orientation. Spelled as a
        $nin."""
        s = self._selector_src(server.get_logbook_notifications,
                               "unsigned_orientations = await")
        self.assertIn('"$nin": ["submitted", WITHDRAWN_STATUS]', s)
        # AND THE SPREAD FORM IS USED EXACTLY ONCE IN THE WHOLE FUNCTION -- by
        # `stale_unsigned_docs`, which has no `status` key of its own. Counting
        # it is what would catch somebody "fixing" the orientation selector by
        # adding the constant beside the $nin, where it would silently replace
        # the submitted test and start counting every filed orientation.
        self.assertEqual(
            code_of(server.get_logbook_notifications).count(
                "**WITHDRAWN_EXCLUDED"), 1)

    def test_the_nightly_end_of_day_sweep(self):
        """Undetected, this raises an `unsigned_stale_logbook` compliance alert
        that is deduped on (project, log_type, date) -- so it is written once
        and then sits on the admin's list forever with no action that could
        clear it."""
        s = self._selector_src(server.sweep_stale_end_of_day_logs,
                               "cursor = database.logbooks.find")
        self.assertIn("WITHDRAWN_EXCLUDED", s)

    def test_the_project_list_every_editor_reads(self):
        """The leverage point: twelve client pickers choose the document to
        open out of this response, nine of them through their own inline
        `arr.find((l) => !l.is_locked)`."""
        src = inspect.getsource(server.get_project_logbooks)
        self.assertIn("include_withdrawn", src)
        self.assertIn("WITHDRAWN_EXCLUDED", src)

    def test_but_a_caller_that_ASKS_for_the_whole_chain_gets_it(self):
        """A withdrawal is not a delete: the document is still there for
        anything that wants to see it."""
        sig = inspect.signature(server.get_project_logbooks)
        self.assertIn("include_withdrawn", sig.parameters)
        self.assertIs(sig.parameters["include_withdrawn"].default, False)

    def test_the_single_document_read_never_filtered_by_state(self):
        """`GET /logbooks/{id}` must keep returning a withdrawn document. That
        it survives and stays readable is the whole difference."""
        src = code_of(server.get_logbook)
        self.assertNotIn("**WITHDRAWN_EXCLUDED", src)
        self.assertNotIn("logbook_is_withdrawn(", src)

    def test_the_clause_matches_documents_written_before_it_existed(self):
        """`$ne` matches a MISSING field as well as a different value, so every
        one of the seven -- none of which carries a `status: withdrawn` -- is
        still selected by the detectors until it is actually withdrawn."""
        self.assertEqual(server.WITHDRAWN_EXCLUDED,
                         {"status": {"$ne": "withdrawn"}})


class ItCannotBeResurrected(unittest.TestCase):
    """A withdrawal that only hid the row would be cosmetic. The client still
    holds the id, and `syncPendingDrafts` PUTs a stored draft at app startup
    with no user in the path."""

    def test_update_refuses_a_withdrawn_document(self):
        src = inspect.getsource(server.update_logbook)
        self.assertIn("logbook_is_withdrawn", src)
        self.assertIn("LOGBOOK_WITHDRAWN", src)

    def test_finalize_refuses_one(self):
        src = inspect.getsource(server.finalize_logbook)
        self.assertIn("logbook_is_withdrawn", src)
        self.assertIn("LOGBOOK_WITHDRAWN", src)

    def test_finalize_refuses_it_BEFORE_it_mints_a_ledger_row(self):
        """`ensure_signature_ledger_row` runs ahead of the idempotent return.
        Minting a row for a withdrawn draft would put an attestation in the
        audit trail for a document that is never going to be a record."""
        src = code_of(server.finalize_logbook)
        self.assertLess(src.index("logbook_is_withdrawn(existing)"),
                        src.index("await ensure_signature_ledger_row("))

    def test_the_predicate_is_one_field_and_one_function(self):
        self.assertTrue(server.logbook_is_withdrawn({"status": "withdrawn"}))
        self.assertFalse(server.logbook_is_withdrawn({"status": "draft"}))
        self.assertFalse(server.logbook_is_withdrawn({}))
        self.assertFalse(server.logbook_is_withdrawn(None))


# ══ THE SIMULTANEOUS DOUBLE TAP ═════════════════════════════════════════════
#
# `open_amendment_head` / AMENDMENT_ALREADY_OPEN keys correctly on the parent,
# but it is a READ-then-INSERT with nothing between them. Two genuinely
# simultaneous requests both read "no open child" and both insert -- which is
# the fork on Aug 10 and Aug 14 (sixty and twenty-six seconds apart), and
# nothing in the application layer can close it. The durable fix is the
# database's, in the same shape `signature_events_one_row_per_signing_act`
# already uses: a PARTIAL UNIQUE INDEX over the open-amendment condition.


def _matches_partial_filter(doc, flt):
    """Evaluate a Mongo partialFilterExpression against a document.

    Only the operators a partialFilterExpression is ALLOWED to contain --
    equality, `$type` -- because if the real filter ever grows one this helper
    cannot evaluate, the test must break rather than quietly approximate.

    `{field: null}` matches null OR MISSING, which is Mongo's rule and is the
    whole reason `cp_signature: None` is the right clause for "unsigned".
    """
    for field, cond in flt.items():
        val = doc.get(field, _UNSET)
        if isinstance(cond, dict):
            assert set(cond) == {"$type"}, f"unevaluable clause: {field}={cond}"
            want = cond["$type"]
            assert want == "string", f"unevaluable $type: {want}"
            if not isinstance(val, str):
                return False
        elif cond is None:
            if val is not _UNSET and val is not None:
                return False
        else:
            if val is _UNSET or val != cond:
                return False
    return True


class OneOpenAmendmentPerParentIsTheDatabasesRule(unittest.TestCase):
    """THE INDEX, ITS FILTER, AND WHAT THE FILTER ACTUALLY SELECTS."""

    def test_the_index_is_declared(self):
        self.assertEqual(server.OPEN_AMENDMENT_INDEX_NAME,
                         "logbooks_one_open_amendment_per_parent")
        self.assertEqual(server.OPEN_AMENDMENT_INDEX_KEYS,
                         [("parent_logbook_id", 1)])

    def test_it_is_bootstrapped_with_the_app_and_is_UNIQUE_and_PARTIAL(self):
        """A definition no startup path creates is a comment."""
        src = inspect.getsource(server)
        self.assertIn("OPEN_AMENDMENT_INDEX_NAME", src)
        i = src.index("name=OPEN_AMENDMENT_INDEX_NAME")
        window = src[i - 600:i + 400]
        self.assertIn("_ensure_index_resilient", window)
        self.assertIn("unique=True", window)
        self.assertIn("OPEN_AMENDMENT_PARTIAL_FILTER", window)

    def test_the_filter_selects_an_OPEN_amendment(self):
        """THE POSITIVE CONTROL. A filter that matched nothing would build an
        always-empty index, enforce nothing, and pass every absence assertion
        below -- which is exactly the failure this repo keeps finding."""
        self.assertTrue(_matches_partial_filter(
            _child(), server.OPEN_AMENDMENT_PARTIAL_FILTER))

    def test_and_it_selects_the_child_amend_logbook_ACTUALLY_writes(self):
        """Not the fixture's idea of a child -- the real insert's. The fixture
        and the endpoint could drift apart and the control above would still
        pass."""
        src = inspect.getsource(server.amend_logbook)
        for clause in ('"cp_signature": None', '"status": "draft"',
                       '"is_locked": False', '"is_amendment": True',
                       '"is_deleted": False',
                       '"parent_logbook_id": str(original["_id"])'):
            self.assertIn(clause, src, clause)

    def test_a_WITHDRAWN_child_releases_the_slot(self):
        """This is what makes the index and `open_amendment_head` agree. A
        withdrawn child that still occupied the slot would hold the parent's
        Amend button shut forever -- the dead end withdrawal exists to open."""
        self.assertFalse(_matches_partial_filter(
            _child(status=server.WITHDRAWN_STATUS),
            server.OPEN_AMENDMENT_PARTIAL_FILTER))

    def test_a_FILED_child_releases_it(self):
        for over in ({"status": "submitted"}, {"is_locked": True}):
            self.assertFalse(_matches_partial_filter(
                _child(**over), server.OPEN_AMENDMENT_PARTIAL_FILTER), over)

    def test_a_SIGNED_child_releases_it(self):
        """`open_amendment_head` does not call a signed child open, so the
        index must not either -- or a CP who signed but has not filed would be
        refused an amendment the application layer would have allowed."""
        self.assertFalse(_matches_partial_filter(
            _child(cp_signature=SIGNATURE),
            server.OPEN_AMENDMENT_PARTIAL_FILTER))

    def test_a_SOFT_DELETED_child_releases_it(self):
        self.assertFalse(_matches_partial_filter(
            _child(is_deleted=True), server.OPEN_AMENDMENT_PARTIAL_FILTER))

    def test_an_ORIGINAL_is_never_governed_by_it(self):
        """No parent link, not an amendment. A unique index that reached
        originals would allow exactly one logbook in the collection."""
        self.assertFalse(_matches_partial_filter(
            _child(is_amendment=False, parent_logbook_id=None),
            server.OPEN_AMENDMENT_PARTIAL_FILTER))

    def test_the_index_NEVER_refuses_what_the_application_would_allow(self):
        """THE INVARIANT BETWEEN THE TWO RULES, AND IT IS ONE-DIRECTIONAL.

        The database enforces one definition of "open" and `open_amendment_head`
        reports another. They do not have to be identical, but the index must
        never be the STRICTER of the two -- an index that held a slot the
        application considers free would refuse a CP an amendment for a reason
        no screen could explain and no `open_amendment_head` read would show.

        So: governed-by-the-index IMPLIES open-to-the-application. The converse
        is allowed to fail, and does; the case is named in its own test below.
        """
        shapes = [
            {},
            {"status": server.WITHDRAWN_STATUS},
            {"status": "submitted"},
            {"is_locked": True},
            {"is_deleted": True},
            {"cp_signature": SIGNATURE},
            {"cp_signature": {}},
        ]
        for over in shapes:
            doc = _child(**over)
            by_index = _matches_partial_filter(
                doc, server.OPEN_AMENDMENT_PARTIAL_FILTER)
            by_app = server.open_amendment_head([doc]) is not None
            if by_index:
                self.assertTrue(by_app, over)

    def test_the_ONE_shape_the_index_lets_through_that_the_app_calls_open(self):
        """`cp_signature: {}` -- the shape production actually held.

        `open_amendment_head` asks `not c.get("cp_signature")`, and `not {}` is
        True in Python, so it calls such a child OPEN. The index's clause is
        `cp_signature: null`, which in Mongo matches null OR MISSING and NOT an
        empty object -- so a child in that shape is not governed and a second
        one beside it would not be refused by the database.

        NAMED RATHER THAN CLOSED, and deliberately: this is the direction that
        FAILS OPEN. The application-layer check still catches it on every
        non-simultaneous attempt, exactly as it does today, so the worst case
        is the race staying open for one shape rather than a CP being blocked
        by a rule with no visible cause. Closing it would need `$or`, which a
        partialFilterExpression may not contain."""
        doc = _child(cp_signature={})
        self.assertFalse(_matches_partial_filter(
            doc, server.OPEN_AMENDMENT_PARTIAL_FILTER))
        self.assertIsNotNone(server.open_amendment_head([doc]))

    def test_the_filter_uses_only_operators_a_partial_index_permits(self):
        """MongoDB rejects `$ne`, `$or`, `$not` and `$nin` in a
        partialFilterExpression. A rejected index is swallowed by
        `_ensure_index_resilient` (it logs and returns), so the failure would
        be SILENT and the race would stay open with a test suite saying it was
        closed."""
        for field, cond in server.OPEN_AMENDMENT_PARTIAL_FILTER.items():
            if isinstance(cond, dict):
                self.assertEqual(set(cond), {"$type"}, field)


class TheLOSER_OF_THE_RACE_GETS_THE_OPEN_CHILD(unittest.TestCase):
    """The index turns the second simultaneous insert into a DuplicateKeyError.
    Unhandled, that is a 500 on a button the CP just tapped -- and the whole
    reason this feature exists is a man who tapped a button that appeared to do
    nothing. He must get exactly what he would have got had he arrived a moment
    later: the 409 that hands him the correction that is already open."""

    def _amend(self, children, dup=False):
        """`children` is what the parent's children READ returns.

        THE RACE IS MODELLED, NOT ASSUMED. In a real simultaneous double tap
        BOTH requests read "no open child" -- if this one's first read already
        saw the winner it would raise 409 from the application check and the
        insert would never run, which is a test that returns the right answer
        for the wrong reason. So when `dup` is set the FIRST read is empty (the
        racy read that lets both through) and the RE-read after the duplicate
        key returns the winner.
        """
        state = {"inserted": [], "audits": [], "reads": 0}
        parent = {"_id": PARENT_ID, "id": PARENT_ID, "project_id": "projA",
                  "company_id": "companyA", "log_type": "daily_jobsite",
                  "date": "2026-08-14", "data": {}, "is_locked": True,
                  "status": "submitted", "is_deleted": False}

        async def lb_find_one(q, *a, **kw):
            if q.get("_id") == PARENT_ID:
                return dict(parent)
            for c in children:
                if c["_id"] == q.get("_id"):
                    return dict(c)
            return dict(parent)

        def lb_find(q, *a, **kw):
            state["reads"] += 1
            rows = ([] if (dup and state["reads"] == 1)
                    else [dict(c) for c in children])
            cur = MagicMock()
            cur.to_list = AsyncMock(return_value=rows)
            return cur

        async def lb_insert_one(doc, *a, **kw):
            if dup:
                from pymongo.errors import DuplicateKeyError
                raise DuplicateKeyError(
                    "E11000 duplicate key error collection: db.logbooks "
                    "index: logbooks_one_open_amendment_per_parent")
            state["inserted"].append(doc)
            r = MagicMock(); r.inserted_id = "new-child"
            return r

        db = MagicMock()
        db.logbooks.find_one = AsyncMock(side_effect=lb_find_one)
        db.logbooks.find = MagicMock(side_effect=lb_find)
        db.logbooks.insert_one = AsyncMock(side_effect=lb_insert_one)
        db.projects.find_one = AsyncMock(return_value=dict(PROJ))

        async def fake_audit(*a, **kw):
            state["audits"].append(a)

        with patch.object(server, "db", db), \
             patch.object(server, "audit_log", AsyncMock(side_effect=fake_audit)), \
             patch.object(server, "ensure_signature_ledger_row",
                          AsyncMock(return_value=None)):
            try:
                state["result"] = asyncio.run(server.amend_logbook(
                    logbook_id=PARENT_ID,
                    data={"reason": "corrected the headcount"},
                    current_user=SUPER))
            except HTTPException as e:
                state["exc"] = e
        return state

    def test_the_ordinary_path_still_inserts(self):
        """THE CONTROL. Without this, every assertion below would also pass on
        an amend endpoint that had stopped working entirely."""
        st = self._amend(children=[])
        self.assertEqual(len(st["inserted"]), 1)
        self.assertNotIn("exc", st)

    def test_the_race_path_is_actually_REACHED_by_these_tests(self):
        """THE CONTROL FOR THE THREE BELOW. If the first read saw the winner,
        the application check would raise 409 on its own and the duplicate-key
        handling would never run -- and every assertion below would pass
        against an endpoint that has none. The re-read is the proof: two reads
        means the first one came back empty and the insert was attempted."""
        st = self._amend(children=[_child(_id="winner")], dup=True)
        self.assertEqual(st["reads"], 2)
        self.assertEqual(st["inserted"], [])

    def test_a_duplicate_key_is_NOT_a_500(self):
        st = self._amend(children=[_child(_id="winner")], dup=True)
        self.assertIn("exc", st)
        self.assertEqual(st["exc"].status_code, 409)

    def test_and_it_hands_back_the_child_that_WON(self):
        st = self._amend(children=[_child(_id="winner")], dup=True)
        detail = st["exc"].detail
        self.assertEqual(detail["code"], "AMENDMENT_ALREADY_OPEN")
        self.assertEqual(detail["logbook_id"], "winner")

    def test_the_loser_gets_the_SAME_shape_as_a_late_arrival(self):
        """A client that already knows how to adopt an open correction
        (amendmentAdopt.js) must not need a second code path for the race."""
        late = self._amend(children=[_child(_id="winner")])
        raced = self._amend(children=[_child(_id="winner")], dup=True)
        self.assertEqual(late["exc"].status_code, raced["exc"].status_code)
        self.assertEqual(set(late["exc"].detail), set(raced["exc"].detail))
        self.assertEqual(late["exc"].detail["logbook_id"],
                         raced["exc"].detail["logbook_id"])

    def test_the_endpoint_catches_the_DATABASE_error_and_not_everything(self):
        """A bare `except Exception` around an insert would swallow a genuine
        write failure and report an open correction that does not exist.

        THE EXCEPT CLAUSE, NOT THE IMPORT. A mutation control that replaced
        `except DuplicateKeyError:` with `except ValueError:` left the import
        line untouched, so a test asserting only the name was in the source
        stayed green while the handling was gone."""
        src = code_of(server.amend_logbook)
        self.assertIn("except DuplicateKeyError:", src)
        self.assertNotIn("except Exception", src)


class TheOperatorCanBuildTheIndexByHand(unittest.TestCase):
    """He applies indexes manually against Atlas -- a previous outage was fixed
    that way with no deploy. A script that only exists inside a deploy is a
    script he cannot run."""

    SCRIPT = (Path(server.__file__).resolve().parent
              / "scripts" / "create_open_amendment_index.js")

    def test_the_script_is_versioned_in_the_repo(self):
        self.assertTrue(self.SCRIPT.exists(), str(self.SCRIPT))

    @staticmethod
    def _script_filter(text):
        """The script's PARTIAL_FILTER, parsed into Python.

        PARSED, NOT GREPPED. Asserting that each field NAME appears in the file
        passes on a script whose `status` clause says "submitted" — the two
        definitions would have drifted in the one way that matters and the
        check would still be green."""
        m = re.search(r"const PARTIAL_FILTER = \{(.*?)\n\};", text, re.S)
        assert m, "PARTIAL_FILTER not found in the script"
        body = "{" + m.group(1) + "}"
        # Bare object keys -> JSON keys. `$type` is a key too, so the class is
        # [\w$] and not \w -- \w alone quotes the "type" and orphans the "$".
        body = re.sub(r'([{,]\s*)([\w$]+)\s*:', r'\1"\2":', body)
        body = re.sub(r",(\s*})", r"\1", body)  # trailing commas
        # true / false / null are already JSON literals.
        return json.loads(body)

    def test_it_names_the_SAME_index_the_server_bootstraps(self):
        """Two writers of one index definition. If they drift, the operator
        builds an index the application does not believe in."""
        text = self.SCRIPT.read_text(encoding="utf-8")
        self.assertIn(server.OPEN_AMENDMENT_INDEX_NAME, text)
        self.assertEqual(self._script_filter(text),
                         server.OPEN_AMENDMENT_PARTIAL_FILTER)

    def test_and_the_parse_that_check_depends_on_actually_WORKS(self):
        """THE CONTROL. If `_script_filter` returned `{}` on a file it could
        not read, the comparison above would be `{} == {}`-shaped nonsense
        wearing a green tick."""
        got = self._script_filter(self.SCRIPT.read_text(encoding="utf-8"))
        self.assertEqual(len(got), 6)
        self.assertEqual(got["status"], "draft")
        self.assertEqual(got["parent_logbook_id"], {"$type": "string"})
        self.assertIsNone(got["cp_signature"])

    def test_it_REFUSES_to_build_over_existing_duplicates(self):
        """PRODUCTION HAS THE DUPLICATES THIS INDEX FORBIDS -- Aug 10 and Aug
        14, two open children on one parent each. A unique build against them
        FAILS, and `_ensure_index_resilient` swallows that failure at startup.
        The script must find them and say so instead of leaving the operator
        with a silently absent index."""
        text = self.SCRIPT.read_text(encoding="utf-8")
        self.assertIn("aggregate", text)
        self.assertIn("$group", text)

    def test_it_verifies_the_index_actually_exists_afterwards(self):
        """An empty/zero result is either a finding or a broken check, and
        nothing distinguishes them without a positive control."""
        text = self.SCRIPT.read_text(encoding="utf-8")
        self.assertIn("getIndexes", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
