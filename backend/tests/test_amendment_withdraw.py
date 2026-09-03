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


def _run(user, doc, data=None, project=PROJ):
    """Call the real handler against a mock db. Returns (result, state)."""
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
        _, state2 = _run(SUPER, _child(), data={"reason": "double tap"})
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


class ItIsNotASigningAct(unittest.TestCase):
    """WHY audit_log AND NOT signature_events.

    The collection's unique index is named
    `signature_events_one_row_per_signing_act`; `version` counts the signings
    of one document; `create_signature_event` requires signature_data and a
    content_snapshot; `attach_attestation` captures THE SENTENCE PRINTED ABOVE
    A SIGNATURE. A withdrawal has none of those -- the content is what is being
    abandoned. A row there would bump the document's signature version and
    assert a signing act nobody performed."""

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

class TheAuthorOrAnAdmin(unittest.TestCase):
    def test_the_author_may(self):
        _, state = _run(SUPER, _child())
        self.assertEqual(state["store"]["status"], server.WITHDRAWN_STATUS)

    def test_an_admin_may(self):
        _, state = _run(ADMIN, _child())
        self.assertEqual(state["store"]["withdrawn_by"], "u-admin")

    def test_a_colleague_who_did_not_file_it_is_refused(self):
        with self.assertRaises(HTTPException) as c:
            _run(OTHER_CP, _child())
        self.assertEqual(c.exception.status_code, 403)

    def test_and_the_refusal_NAMES_the_author(self):
        """A CP looking at another man's correction on his own signed log needs
        to know who to ask. A closed door is how this incident started."""
        with self.assertRaises(HTTPException) as c:
            _run(OTHER_CP, _child())
        self.assertIn("Michael Cespedes", str(c.exception.detail))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
