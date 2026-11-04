"""AN ANSWERED SET QUESTION CAN BE AMENDED, WITH THE OLD ANSWER KEPT (Roy, 10-31).

Q2 (the gas-change file's unnumbered Roof Plan, id ea33f26741467e17) was
answered 'replaces' against pages of AR 8.18.26 - a set the office has since
ruled out of the model. The answer route records an OPEN question only (409
otherwise), so the answer could not be pointed at the March roof (AR 3.28.25
p16, A-105.00) except by writing the database by hand.

POST .../plan-set-questions/{id}/amend (company admin; never the operator,
never a WhatsApp reply):
  - only an ANSWERED question of this project;
  - a reason, kept;
  - the new answer is validated exactly as a first answer is (the same
    lib.plan_set_questions rules), against the pages as the OTHER answers
    leave them - this question's own old answer is not applied while its
    replacement is checked;
  - nothing is stored when anything is refused;
  - the old answer (who, when, what) goes onto `history`, never overwritten;
  - audited as plan_set_question_amended (old and new);
  - the pass reads the new answer only.
The first answer, the include / exclude / replaces semantics, the WhatsApp
path and lib.plan_set_questions are unchanged (the last class).
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402
from tests.test_the_system_never_picks_a_set import (  # noqa: E402
    A1XF, AR325, AR818, CID, FILES5, GASF, PID, ROY, _answered_q1, _question, _raw5, _repl)

ACTOR = {"id": "admin-1", "full_name": "Roy", "role": "admin", "company_id": CID}
REASON = "AR 8.18.26 is an unapproved prep set; the gas change replaces the 3.28.25 roof"
#: Roy's new answer: the gas roof plan stands in for AR 3.28.25's roof plan
NEW = [_repl("gas#2", AR325, 16, "A-105.00")]


def _run(coro):
    return asyncio.run(coro)


def _present():
    assert hasattr(server, "_amend_set_answer"), \
        "an answered drawing-set question cannot be amended in this tree"


def _old_q2():
    """Q2 as production holds it: answered 'replaces' against 8.18.26's pages."""
    from lib import plan_set_questions as psq
    q = _question(GASF, 1)
    got, errs = psq.validate_replacements(q, ROY, _live_track(live=set(FILES5)), _raw5())
    assert not errs, errs
    return dict(q, status="answered", answer="replaces", replacements=got,
                answered_by="pm-1", answered_by_name="Roey Fishman", answered_via="admin",
                answered_at="2026-10-30T12:00:20", asked=[], asked_user_ids=[],
                project_id=PID, company_id=CID)


def _live_track(live, decisions=()):
    got = server._glyph_track_pages(_raw5(), FILES5, live, decisions=list(decisions))
    return {t: ps for t, ps in got}["filed"]


#: the live files once AR 8.18.26 is ignored
LIVE_NO_818 = set(FILES5) - {AR818}


def _world(extra=(), q2=True):
    db = AsyncFakeDB()
    for fid, f in FILES5.items():
        db.project_files.docs.append(dict(f, _id=fid, project_id=PID, is_deleted=False))
    for p in _raw5():
        db.document_page_index.docs.append(dict(p, project_id=PID))
    docs = list(extra)
    if q2:
        old = _old_q2()
        docs.append({k: v for k, v in old.items() if k != "id"})
    for d in docs:
        db["plan_set_questions"].docs.append(d)
    return db


def _patched(db, live):
    async def live_ids(_pid):
        return list(live)
    return [patch.object(server, "db", db), patch.object(server, "_live_plan_file_ids", live_ids)]


def _amend(db, qid, answer, replacements=None, reason=REASON, live=LIVE_NO_818, actor="admin-1"):
    ps = _patched(db, live)
    for p in ps:
        p.start()
    try:
        return _run(server._amend_set_answer(PID, qid, answer, actor, reason=reason, name="Roy",
                                             replacements=[dict(r) for r in replacements]
                                             if replacements else None))
    finally:
        for p in ps:
            p.stop()


def _route(db, qid, body, live=LIVE_NO_818, user=ACTOR):
    ps = _patched(db, live)
    for p in ps:
        p.start()
    try:
        return _run(server.amend_plan_set_question(PID, qid, body, current_user=user))
    finally:
        for p in ps:
            p.stop()


def _body(**kw):
    return server.PlanSetAmend(**dict(dict(answer="replaces", replacements=NEW, reason=REASON), **kw))


def _q(db, qid="ea33"):
    return next(d for d in db["plan_set_questions"].docs if d["_id"] == qid or d.get("code") == "Q2")


class Q2IsRePointedAtTheMarchRoof(unittest.TestCase):

    def test_the_amendment_stores_the_new_replacement_keyed_to_the_march_roof(self):
        _present()
        db = _world()
        qid = _old_q2()["_id"]
        out = _route(db, qid, _body())
        self.assertEqual((out["status"], out["answer"]), ("answered", "replaces"))
        q = _q(db)
        self.assertEqual(len(q["replacements"]), 1)
        r = q["replacements"][0]
        self.assertEqual((r["page_id"], r["page_number"], r["sheet_title"]), ("gas#2", 2, "Roof Plan"))
        self.assertEqual(r["takes_sheet_number"], "A-105.00", "the unnumbered roof takes the March number")
        self.assertEqual((r["replaces"]["file_id"], r["replaces"]["page_number"],
                          r["replaces"]["sheet_number"]), (AR325, 16, "A-105.00"))
        self.assertEqual(q["answered_via"], "admin")
        self.assertEqual(q["amended_reason"], REASON)

    def test_the_old_answer_is_kept_in_history(self):
        _present()
        db = _world()
        old = _old_q2()
        _amend(db, old["_id"], "replaces", NEW)
        q = _q(db)
        self.assertEqual(len(q["history"]), 1)
        h = q["history"][0]
        self.assertEqual(h["answer"], "replaces")
        self.assertEqual(sorted(r["replaces"]["sheet_number"] for r in h["replacements"]),
                         ["A-100.01", "A-105.01"], "the 8.18.26 replacements, as they were")
        self.assertEqual((h["answered_by_name"], h["answered_via"], h["answered_at"]),
                         ("Roey Fishman", "admin", "2026-10-30T12:00:20"))
        self.assertEqual(h["reason"], REASON)
        self.assertEqual(h["superseded_by"], "admin-1")
        self.assertIsNotNone(h["superseded_at"])

    def test_it_is_audited_with_the_old_and_the_new(self):
        _present()
        db = _world()
        _amend(db, _old_q2()["_id"], "replaces", NEW)
        rows = [a for a in db.audit_logs.docs if a["action"] == "plan_set_question_amended"]
        self.assertEqual(len(rows), 1)
        d = rows[0]["details"]
        self.assertEqual(d["reason"], REASON)
        self.assertEqual(d["from"]["answer"], "replaces")
        self.assertEqual(len(d["from"]["replacements"]), 2)
        self.assertEqual(d["to"]["replacements"][0]["replaces"]["sheet_number"], "A-105.00")
        self.assertFalse([a for a in db.audit_logs.docs if a["action"] == "plan_set_question_answered"],
                         "an amendment is not recorded as a first answer")

    def test_the_pass_reads_the_new_answer_and_not_the_old(self):
        """The stored decisions go through the pass's own reader and applier:
        the gas roof takes A-105.00 in the March roof's place, 3.28.25's roof
        page is out, the gas first floor governs by date, nothing of 8.18.26."""
        _present()
        db = _world(extra=[dict(_answered_q1(), project_id=PID, company_id=CID)])
        _amend(db, _old_q2()["_id"], "replaces", NEW)

        async def go():
            return await server._set_decisions(PID)
        with patch.object(server, "db", db):
            decisions = _run(go())
        notes = []
        got = server._glyph_track_pages(_raw5(), FILES5, LIVE_NO_818, decisions=decisions, notes=notes)
        ids = {p["_id"]: p.get("sheet_number") for p in dict(got)["filed"]}
        self.assertEqual(ids.get("gas#2"), "A-105.00")
        self.assertNotIn("ar325#16", ids, "the March roof leaves; the gas roof takes its place")
        self.assertEqual(ids.get("gas#1"), "A-100.00", "the gas first floor governs by date")
        self.assertNotIn("ar325#11", ids)
        self.assertFalse([i for i in ids if i.startswith("ar818#")], "8.18.26 is nowhere")
        self.assertEqual(sorted((n["code"], n["applied"]) for n in notes),
                         [("Q1", True), ("Q2", True)])

    def test_the_old_answer_alone_would_have_been_dropped_whole_without_8_18_26(self):
        """Why the amendment is needed: the stored answer names pages that are
        no longer in the model, so the pass would drop it (said, not applied)."""
        _present()
        notes = []
        server._glyph_track_pages(_raw5(), FILES5, LIVE_NO_818, decisions=[_old_q2()], notes=notes)
        self.assertEqual([n["applied"] for n in notes], [False])

    def test_the_first_floor_entry_is_refused_it_is_not_a_current_page(self):
        """Roy's reading also had 'gas p1 (A-100.00) replaces 3.28.25 A-100.00'.
        Inside the filed track the gas A-100.00 (6.9.26) already supersedes the
        March A-100.00 by date, so the March page is not a CURRENT page and the
        validator (unchanged) refuses naming it; the result is the same without
        the entry. Nothing is stored when it is sent."""
        _present()
        from fastapi import HTTPException
        db = _world()
        both = NEW + [_repl("gas#1", AR325, 11, "A-100.00")]
        with self.assertRaises(HTTPException) as cm:
            _route(db, _old_q2()["_id"], _body(replacements=both))
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIn("not one current page", cm.exception.detail)
        self.assertEqual(len(_q(db)["replacements"]), 2, "the old answer is untouched")
        self.assertNotIn("history", _q(db))


class EachRuleHasItsRefusal(unittest.TestCase):

    def test_only_an_answered_question_is_amended(self):
        _present()
        from fastapi import HTTPException
        for status in ("open", "withdrawn"):
            db = _world()
            _q(db)["status"] = status
            self.assertIsNone(_amend(db, _old_q2()["_id"], "replaces", NEW), status)
            with self.assertRaises(HTTPException) as cm:
                _route(db, _old_q2()["_id"], _body())
            self.assertEqual(cm.exception.status_code, 409, status)
            self.assertNotIn("history", _q(db))

    def test_another_projects_question_is_not_reached(self):
        _present()
        db = _world()
        _q(db)["project_id"] = "another-project"
        self.assertIsNone(_amend(db, _old_q2()["_id"], "replaces", NEW))

    def test_a_reason_is_required(self):
        _present()
        for bad in ("", "  ", "ab"):
            db = _world()
            with self.assertRaises(ValueError):
                _amend(db, _old_q2()["_id"], "replaces", NEW, reason=bad)
            self.assertNotIn("history", _q(db))
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            server.PlanSetAmend(answer="replaces", replacements=NEW)

    def test_an_unchanged_answer_is_refused(self):
        _present()
        db = _world()
        same = [_repl("gas#2", AR818, 7, "A-105.01"), _repl("gas#1", AR818, 6, "A-100.01")]
        with self.assertRaises(ValueError) as cm:
            _amend(db, _old_q2()["_id"], "replaces", same, live=set(FILES5))
        self.assertIn("unchanged", str(cm.exception))
        self.assertNotIn("history", _q(db))

    def test_a_replacement_the_pages_do_not_support_stores_nothing(self):
        _present()
        db = _world()
        for bad in ([_repl("gas#2", AR325, 16, "A-105.01")],      # wrong sheet number
                    [_repl("gas#1", AR325, 12, "A-101.00")],      # a different floor sequence
                    [_repl("nope", AR325, 16, "A-105.00")],       # no such replacing page
                    [_repl("gas#2", AR818, 7, "A-105.01")]):      # a page of an ignored file
            with self.assertRaises(ValueError, msg=str(bad)):
                _amend(db, _old_q2()["_id"], "replaces", bad)
        q = _q(db)
        self.assertEqual(len(q["replacements"]), 2)
        self.assertNotIn("history", q)
        self.assertFalse(db.audit_logs.docs)

    def test_the_replacement_is_checked_as_the_other_answers_leave_the_pages(self):
        """With 8.18.26 still in the model the old Q2 applies, so 8.18.26's roof
        is already replaced and no longer a current page; an amendment that
        changes only the first-floor entry must still be checkable, because this
        question's own old answer is not applied while it is validated."""
        _present()
        db = _world()
        only_roof = [_repl("gas#2", AR818, 7, "A-105.01")]
        out = _amend(db, _old_q2()["_id"], "replaces", only_roof, live=set(FILES5))
        self.assertEqual([r["replaces"]["sheet_number"] for r in out["replacements"]], ["A-105.01"])

    def test_the_other_answers_are_still_applied_while_it_is_checked(self):
        _present()
        db = _world(extra=[dict(_answered_q1(), project_id=PID, company_id=CID)])

        async def go():
            return (await server._set_decisions(PID, skip=_old_q2()["_id"]),
                    await server._set_decisions(PID))
        with patch.object(server, "db", db):
            skipping, everything = _run(go())
        self.assertEqual(sorted(d["code"] for d in everything), ["Q1", "Q2"])
        self.assertEqual([d["code"] for d in skipping], ["Q1"])

    def test_a_second_writer_between_the_read_and_the_write_stores_nothing(self):
        _present()
        from lib import plan_set_questions as psq
        db = _world()
        qid = _old_q2()["_id"]
        real = psq.validate_replacements

        def racing(*a, **k):
            _q(db)["answered_at"] = "2026-10-31T09:00:00"     # someone amended meanwhile
            return real(*a, **k)
        with patch.object(psq, "validate_replacements", racing):
            self.assertIsNone(_amend(db, qid, "replaces", NEW))
        self.assertNotIn("history", _q(db))
        self.assertFalse(db.audit_logs.docs)

    def test_the_history_grows_it_is_never_overwritten(self):
        _present()
        db = _world()
        qid = _old_q2()["_id"]
        _amend(db, qid, "replaces", NEW, reason="first amendment")
        _amend(db, qid, "exclude", None, reason="second amendment")
        q = _q(db)
        self.assertEqual([h["reason"] for h in q["history"]], ["first amendment", "second amendment"])
        self.assertEqual([h["answer"] for h in q["history"]], ["replaces", "replaces"])
        self.assertEqual(len(q["history"][0]["replacements"]), 2, "the oldest answer is still whole")
        self.assertEqual(q["history"][1]["replacements"][0]["replaces"]["sheet_number"], "A-105.00")
        self.assertEqual(q["answer"], "exclude")
        self.assertNotIn("replacements", q, "an exclude carries no replacements")
        self.assertEqual(q["status"], "answered")

    def test_replacements_belong_to_the_answer_replaces_only(self):
        _present()
        from pydantic import ValidationError
        db = _world()
        with self.assertRaises(ValueError):
            _amend(db, _old_q2()["_id"], "exclude", NEW)
        with self.assertRaises(ValidationError):
            server.PlanSetAmend(answer="include", replacements=NEW, reason=REASON)
        with self.assertRaises(ValidationError):
            server.PlanSetAmend(answer="replaces", reason=REASON)


class OnlyTheOfficeAmends(unittest.TestCase):

    def test_the_platform_operator_is_refused_in_the_handler(self):
        _present()
        from fastapi import HTTPException
        db = _world()
        with self.assertRaises(HTTPException) as cm:
            _route(db, _old_q2()["_id"], _body(),
                   user={"id": "op", "is_platform_operator": True, "role": "owner"})
        self.assertEqual(cm.exception.status_code, 403)
        self.assertNotIn("history", _q(db))

    def test_a_whatsapp_reply_cannot_amend(self):
        """A reply finds OPEN questions only; the amended one is answered, so
        'Q2 YES' reads back the stored answer and changes nothing."""
        _present()
        from lib import plan_set_questions as psq
        db = _world()
        _amend(db, _old_q2()["_id"], "replaces", NEW)
        before = dict(_q(db))
        with patch.object(server, "db", db):
            self.assertIsNone(_run(server._record_set_answer(PID, _old_q2()["_id"], "include", "pm",
                                                             via="whatsapp")))
        self.assertEqual(_q(db), before)
        text = psq.status_text(dict(_q(db), answered_by_name="Roy"))
        self.assertIn("A-105.00", text)
        self.assertNotIn("A-105.01", text)

    def test_the_first_answer_route_still_refuses_an_answered_question(self):
        _present()
        from fastapi import HTTPException
        db = _world()
        ps = _patched(db, LIVE_NO_818)
        for p in ps:
            p.start()
        try:
            with self.assertRaises(HTTPException) as cm:
                _run(server.answer_plan_set_question(
                    PID, _old_q2()["_id"], server.PlanSetAnswer(answer="replaces", replacements=NEW),
                    current_user=ACTOR))
        finally:
            for p in ps:
                p.stop()
        self.assertEqual(cm.exception.status_code, 409)

    def test_the_company_gate_is_the_answer_routes(self):
        """Same dependencies as .../answer (the company's own gate - never the
        operator's), by the route table."""
        _present()
        def route(suffix):
            hits = [r for r in server.api_router.routes if hasattr(r, "methods")
                    and r.path.endswith("/plan-set-questions/{question_id}/" + suffix)
                    and "POST" in r.methods]
            self.assertEqual(len(hits), 1, suffix)
            return hits[0]
        ans, am = route("answer"), route("amend")

        def deps(r):
            return sorted(getattr(d.call, "__name__", str(d.call)) for d in r.dependant.dependencies)
        self.assertEqual(deps(ans), deps(am))

    def test_over_http_another_companys_admin_and_the_operator_are_refused(self):
        """Through server.app (real middleware and JWT, fake database): the
        question stays exactly as it was, no history, no audit row."""
        _present()
        from tests.test_the_system_never_picks_a_set import _http, _opworld
        db, pid = _opworld()
        q = db["plan_set_questions"].docs[0]
        q.update(status="answered", answer="exclude", answered_by="x", answered_at="2026-10-30")
        before = dict(q)
        path = f"/api/projects/{pid}/plan-set-questions/q-a1x/amend"
        body = {"answer": "include", "reason": "changed my mind"}
        for who, pw in (("b@b.test", "pw-b-123"), ("op@x.test", "pw-op-123")):
            got, _w = _run(_http(db, who, pw, [("POST", path, body)]))
            self.assertEqual(got[("POST", path)][0], 403, (who, got))
        self.assertEqual(db["plan_set_questions"].docs[0], before)
        self.assertFalse([a for a in db.audit_logs.docs if a["action"] == "plan_set_question_amended"])
        got, _w = _run(_http(db, "a@a.test", "pw-a-123", [("POST", path, body)]))
        self.assertEqual(got[("POST", path)][0], 200, got)
        self.assertEqual(db["plan_set_questions"].docs[0]["answer"], "include")
        self.assertEqual(db["plan_set_questions"].docs[0]["history"][0]["answer"], "exclude")

    def test_the_list_route_shows_the_history(self):
        _present()
        db = _world()
        _amend(db, _old_q2()["_id"], "replaces", NEW)
        ps = _patched(db, LIVE_NO_818)
        for p in ps:
            p.start()
        try:
            async def peopleless(pid):
                return {"name": "588"}, []
            with patch.object(server, "_set_question_people", peopleless):
                out = _run(server.list_plan_set_questions(PID, current_user=ACTOR))
        finally:
            for p in ps:
                p.stop()
        q = out["questions"][0]
        self.assertEqual(len(q["history"]), 1)
        self.assertEqual(q["amended_reason"], REASON)
        self.assertEqual(q["replacements"][0]["replaces"]["sheet_number"], "A-105.00")


class NothingElseMoved(unittest.TestCase):
    """A first answer is recorded as before; the pairing rules are the module's."""

    def test_a_first_answer_to_an_open_question_is_recorded_as_before(self):
        _present()
        old = _old_q2()
        open_q = {k: v for k, v in old.items() if k not in
                  ("answer", "replacements", "answered_by", "answered_by_name", "answered_via",
                   "answered_at")}
        open_q["status"] = "open"
        db = _world(q2=False, extra=[open_q])
        ps = _patched(db, set(FILES5))
        for p in ps:
            p.start()
        try:
            doc = _run(server._record_set_answer(PID, old["_id"], "replaces", "admin-1", via="admin",
                                                 replacements=[dict(r) for r in ROY]))
        finally:
            for p in ps:
                p.stop()
        self.assertEqual((doc["status"], doc["answer"]), ("answered", "replaces"))
        self.assertNotIn("history", doc)
        self.assertEqual([a["action"] for a in db.audit_logs.docs], ["plan_set_question_answered"])

    def test_include_exclude_replaces_are_the_three_answers(self):
        from lib import plan_set_questions as psq
        self.assertEqual(psq.ANSWERS, ("include", "exclude", "replaces"))


if __name__ == "__main__":
    unittest.main()
