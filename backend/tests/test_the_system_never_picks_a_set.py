"""THE SYSTEM NEVER DECIDES WHICH DRAWINGS BELONG TO A SET (ruling 21).

Operator, 2026-10-27: "the system never decides which drawings belong to a
set or which governs. When it's ambiguous: 1. If the project has a PM or SM
on record, ask them through the app/WhatsApp: one question per ambiguity,
naming the sheets and what each would change. Their answer is stored per
project, audit-logged, and applied on the next pass. 2. Until answered, or if
no PM/SM exists: never pick one. Answers state the difference instead, e.g.
'the filed set has 36 type F doors without the A.1.x plans; including them
gives N'. Claims bind only where both readings agree. Apply now to #21
(filed-set door/window building totals)."

MEASURED ON 588 BOYLAND (bv-worktrees/L6_ambiguity_measure.md): the second
architect's A.1.1 ... A.1.7 ("588 THOMAS BOYLAND ST SET_UPDATED .pdf") and the
unnumbered gas-change "Roof Plan" are in the filed track only by default (no
track label). Read by the pass's own reader, A.1.x prints tag for tag what the
filed A-1xx plans print: the filed set has 36 type F doors without them and 72
including them. Every reading agrees on one figure only, type C 1. The PM /
Site Manager on record is one person, reachable by WhatsApp.

Rules under test:
  - never picking a reading: a building figure the readings disagree on
    binds in no reading-less claim;
  - binding only on agreement; a claim naming its reading binds against it;
  - the render states the difference, Roy's form;
  - a question is stored once, never re-opened, and asked once;
  - nothing is sent by the pass, at import or by these tests (WaAPI is
    a recorder that fails the test if reached);
  - the answer is recorded (WhatsApp reply or admin), audit-logged, and
    applied on the next pass.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402
from lib import plan_emit as E  # noqa: E402
from lib import plan_search as S  # noqa: E402

PID = "6a5f63bc147407d3261df2c7"
CID = "c-blueview"
INT, WIN = "INTERIOR DOOR SCHEDULE", "WINDOW SCHEDULE"
TAGS = {INT: list("ABCDEFG"), WIN: ["W1", "W2", "W3"]}
A1X = "588 THOMAS BOYLAND ST SET_UPDATED .pdf"
GAS = "AR - 6.9.26 (Gas change).pdf"


def _psq():
    """On a tree without the rule this is the failure - an assertion, never
    an ImportError."""
    assert importlib.util.find_spec("lib.plan_set_questions") is not None, \
        "no lib.plan_set_questions: the system decides set membership in this tree"
    from lib import plan_set_questions
    return plan_set_questions


def _server_has(*names):
    for n in names:
        assert hasattr(server, n), f"server.{n} is not in this tree"


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


# ── rows, by the real emitter ──────────────────────────────────────────────

def _page(sheet, file_name, page_number, title, track="filed"):
    return {"project_id": PID, "company_id": CID, "file_id": f"f-{file_name}",
            "file_hash": f"h-{file_name}", "file_name": file_name,
            "page_id": f"pg-{file_name}-{page_number}", "page_number": page_number,
            "sheet_number": sheet, "sheet_title": title, "discipline": "AR",
            "drawing_track": track, "drawing_track_label": None}


def _rows(page, family, tags, units=None, mark=None, track="filed"):
    """Opening rows of one family on one page; `units` the floor's apartment
    tags (None: sheet scope, as the pass reads a question's page)."""
    recs = [{"tag": t, "unit": u, "glyph_status": "resolved",
             "placement": "placed" if u else "refused", "reason": None if u else "sheet scope",
             "label_text": t, "label_box": (1, 2, 3, 4), "symbol_bbox": (5, 6, 7, 8),
             "symbol_at": (6, 7), "at_arch": (6, 7), "label_at": (2, 3)} for t, u in tags]
    us = {"tags": units or [], "method": "plan_tags" if units else "sheet_scope",
          "zero_units": False, "multi_level": {u: [] for u in units or []}}
    rows = E.glyph_rows({"records": recs, "method": us["method"],
                         "registration": {"dx": 0.0, "dy": 0.0, "usable": True}},
                        mech=page, arch=page, family=family,
                        pass_key=f"{page['sheet_number']}|openings|{family}", units=us,
                        widest_door={"inches": 40.0}, mech_count=len(recs))
    for r in rows:
        r["payload"].update(kind="opening", track=track)
        if mark:
            r["payload"].update(set_question=mark[0], set_question_label=mark[1])
    return rows


def _refusal(page, mark, track="filed"):
    r = E.sheet_refusal(page, "doors and windows not read: FileNotFoundError",
                        pass_key=f"openings|{page['sheet_number']}", role="opening")
    r["payload"].update(kind="opening", track=track, set_question=mark[0],
                        set_question_label=mark[1])
    return r


def _census(rows, tracks=("filed",)):
    pages = sorted({r["page_id"] for r in rows})
    out = []
    for t in tracks:
        for name in (INT, WIN):
            c = S.glyph_census("family", PID, pages, 0, family=name, tags=TAGS[name],
                               track=t, scope=S.OPENING)
            c["count"] = sum(1 for r in rows if S.glyph_in_census(r, c))
            out.append(c)
        c = S.glyph_census("refusals", PID, pages, 0, track=t, scope=S.OPENING)
        c["count"] = sum(1 for r in rows if S.glyph_in_census(r, c))
        out.append(c)
    return out


def _world(rows, tracks=("filed",)):
    for i, r in enumerate(rows):
        r["ordinal"] = i
    return rows + _census(rows, tracks)


Q1 = ("q-a1x", "the A.1.x plans")
Q2 = ("q-gas", "the unnumbered Roof Plan")
SECOND = _page("A-101.00", "AR - 3.28.25.pdf", 12, "SECOND FLOOR PLAN")
ROOF = _page("A-105.01", "AR - 8.18.26.pdf", 7, "ROOF AND BULKEAD PLAN")
A12 = _page("A.1.2", A1X, 12, "FLOOR PLAN")
A16 = _page("A.1.6", A1X, 16, "FLOOR PLAN")
GROOF = _page(None, GAS, 2, "Roof Plan")


def _filed():
    """The filed set: A-101 (10 F, 8 W1) and the roof (1 C, 2 D)."""
    units = ["2A", "2B", "2C", "2D"]
    f = [("F", u) for u in units for _ in range(2)] + [("F", "2C"), ("F", "2D")]
    return (_rows(SECOND, INT, f, units) + _rows(SECOND, WIN, [("W1", u) for u in units * 2], units)
            + _rows(ROOF, INT, [("C", None), ("D", None), ("D", None)]))


def _a1x(mark=Q1):
    """A.1.2 prints the second floor's tags again; A.1.6 the roof's D twice."""
    f = [("F", None)] * 10
    return (_rows(A12, INT, f, mark=mark) + _rows(A12, WIN, [("W1", None)] * 8, mark=mark)
            + _rows(A16, INT, [("D", None)] * 2, mark=mark))


# ══════════════════════════════════════════════════════════════════════════
# 1. The gate: never pick, bind where the readings agree
# ══════════════════════════════════════════════════════════════════════════

class NeverPickAReading(unittest.TestCase):

    def test_a_figure_the_readings_disagree_on_binds_in_neither_reading(self):
        _psq()
        recs = _world(_filed() + _a1x())
        self.assertFalse(_ok("There are 10 type F doors in the filed set.", recs),
                         "10 is the reading WITHOUT the A.1.x plans: picking it")
        self.assertFalse(_ok("There are 20 type F doors in the filed set.", recs),
                         "20 is the reading WITH them: picking it")
        self.assertFalse(_ok("There are 2 type D doors in the filed set.", recs))
        self.assertFalse(_ok("There are 8 W1 windows in the filed set.", recs))

    def test_a_figure_every_reading_gives_binds(self):
        _psq()
        recs = _world(_filed() + _a1x())
        self.assertTrue(_ok("There is 1 type C door in the filed set.", recs),
                        "type C is on no questioned page: every reading gives 1")

    def test_a_claim_naming_its_reading_binds_against_that_reading(self):
        _psq()
        recs = _world(_filed() + _a1x())
        self.assertTrue(_ok("The filed set has 10 type F doors without the A.1.x plans "
                            "and 20 type F doors including the A.1.x plans.", recs))
        self.assertTrue(_ok("The filed set has 10 type F doors without the A.1.x plans.", recs))
        self.assertTrue(_ok("The filed set has 20 type F doors including the A.1.x plans.", recs))
        self.assertFalse(_ok("The filed set has 20 type F doors without the A.1.x plans "
                             "and 10 type F doors including the A.1.x plans.", recs),
                         "each figure is checked against its own reading")
        self.assertFalse(_ok("The filed set has 20 type F doors without the A.1.x plans.", recs))

    def test_two_questions_a_figure_must_name_every_reading_it_depends_on(self):
        _psq()
        recs = _world(_filed() + _a1x() + _rows(GROOF, INT, [("D", None)] * 2, mark=Q2))
        self.assertFalse(_ok("The filed set has 2 type D doors without the A.1.x plans.", recs),
                         "with the gas-change roof plan it is 4")
        self.assertTrue(_ok("The filed set has 2 type D doors without the A.1.x plans and "
                            "without the unnumbered Roof Plan.", recs))
        self.assertTrue(_ok("The filed set has 10 type F doors without the A.1.x plans.", recs),
                        "the roof plan carries no F: both of its readings give 10")
        self.assertTrue(_ok("There is 1 type C door in the filed set.", recs))

    def test_a_page_that_could_not_be_read_leaves_its_reading_unknown(self):
        _psq()
        recs = _world(_filed() + _a1x() + [_refusal(GROOF, Q2)])
        self.assertFalse(_ok("There is 1 type C door in the filed set.", recs),
                         "the unread roof plan may carry a C: no reading with it is known")
        self.assertTrue(_ok("The filed set has 1 type C door without the unnumbered Roof Plan.",
                            recs))

    def test_an_undecided_book_states_no_building_figure_of_its_own(self):
        """FAIL CLOSED for any reader that does not count the readings: the
        book holding a question's rows gives no building figure at all."""
        _psq()
        book = S.opening_books(_world(_filed() + _a1x())).tracks["filed"]
        self.assertTrue(getattr(book, "questions", None), "the book knows its open question")
        fam = book.families[INT]
        self.assertIsNone(S._building_count(book, fam, ["F"]))
        self.assertIsNone(S._building_count(book, fam, ["C"]))

    def test_floors_and_apartments_are_unmoved(self):
        _psq()
        recs = _world(_filed() + _a1x())
        self.assertTrue(_ok("The second floor has 10 type F doors in the filed set.", recs))
        self.assertTrue(_ok("2C has 3 type F doors in the filed set.", recs))

    def test_a_decided_set_binds_as_before(self):
        recs = _world(_filed())
        self.assertTrue(_ok("There are 10 type F doors in the filed set.", recs))
        self.assertTrue(_ok("There are 2 type D doors in the filed set.", recs))

    def test_an_answered_include_is_ordinary_rows(self):
        _psq()
        recs = _world(_filed() + _a1x(mark=None))
        self.assertTrue(_ok("There are 20 type F doors in the filed set.", recs))
        self.assertFalse(_ok("There are 10 type F doors in the filed set.", recs))


class TheRenderStatesTheDifference(unittest.TestCase):

    def test_roys_form(self):
        _psq()
        text = S.render_opening_evidence(_world(_filed() + _a1x()))
        self.assertIn("type C 1 (the same in every reading)", text)
        self.assertIn("type F: 10 without the A.1.x plans; 20 including the A.1.x plans", text)
        self.assertIn("THE SET IS NOT DECIDED", text)
        self.assertNotIn("Whole building: type F", text, "never one reading's figure alone")

    def test_it_says_the_question_was_not_asked_and_why(self):
        _psq()
        recs = _world(_filed() + _a1x()) + [{
            "_id": "q-a1x", "record_type": "set_question", "code": "Q1", "status": "open",
            "label": f"the A.1.x plans (A.1.1 to A.1.7, {A1X})", "asked": [],
            "unasked_reason": "no PM or Site Manager on record for this project"}]
        text = S.render_opening_evidence(recs)
        self.assertIn("Q1: the A.1.x plans (A.1.1 to A.1.7", text)
        self.assertIn("not asked: no PM or Site Manager on record", text)


# ══════════════════════════════════════════════════════════════════════════
# 2. The pass: a questioned page is read and marked; an answer is applied
# ══════════════════════════════════════════════════════════════════════════

def _fake_floor(tags_by_page):
    def floor_records(pg, run, units=None, unplaced_reason=None):
        if pg is None:
            raise FileNotFoundError("no local copy")
        recs = {n: [] for n in run}
        for t in tags_by_page.get(pg, []):
            fam = next(n for n, f in run.items() if t in f["tags"])
            recs[fam].append({"tag": t, "unit": None, "glyph_status": "resolved",
                              "placement": "refused", "how": unplaced_reason,
                              "reason": unplaced_reason, "label_at": (1, 2),
                              "label_box": (0, 0, 2, 2), "label_text": t,
                              "symbol_at": (3, 4), "symbol_bbox": (2, 3, 4, 5), "at_arch": (3, 4)})
        return {"records": recs, "orphans": [], "legend": [], "untagged": [], "unreadable": []}
    return floor_records


FAMS = {INT: {"tags": TAGS[INT], "kind": "door", "sheet": "A-400.00"},
        WIN: {"tags": TAGS[WIN], "kind": "window", "sheet": "A-400.00"}}


def _openings(answers=None, gas_readable=True):
    from lib import plan_openings as po
    refused = [(A12, "A.1.2 is a plan with no mechanical partner by sheet number"),
               (A16, "A.1.6 is a plan with no mechanical partner by sheet number"),
               (GROOF, "unnumbered sheet is a plan with no mechanical partner by sheet number")]
    pages = {"A.1.2": ["F"] * 10 + ["W1"] * 8, "A.1.6": ["D", "D"], "gas": ["D", "D"]}

    def open_page(p):
        if p is GROOF:
            return "gas" if gas_readable else None
        return p["sheet_number"]
    kw = {"answers": answers} if answers is not None else {}
    with patch.object(po, "floor_records", _fake_floor(pages)):
        return po.run_openings([], open_page, FAMS, track="filed", refused=refused, **kw)


class ThePassReadsAndMarksQuestionedPages(unittest.TestCase):

    def test_one_question_per_file_and_every_row_marked(self):
        psq = _psq()
        out = _openings()
        qs = {q["file_name"]: q for q in out.get("questions") or []}
        self.assertEqual(set(qs), {A1X, GAS})
        self.assertEqual([p["sheet_number"] for p in qs[A1X]["pages"]], ["A.1.2", "A.1.6"])
        self.assertEqual(qs[A1X]["short"], "the A.1.x plans")
        self.assertEqual(qs[GAS]["short"], "the unnumbered Roof Plan")
        marks = {(r["payload"].get(psq.ROW_KEY), r.get("label")) for r in out["rows"]}
        self.assertTrue(all(m[0] in (qs[A1X]["id"], qs[GAS]["id"]) for m in marks),
                        "every row of a questioned page carries its question")
        self.assertEqual(sum(1 for r in out["rows"] if r.get("label") == "F"), 10)
        self.assertFalse(any(S._is_refusal(r) for r in out["rows"]),
                         "a readable questioned page is read, not refused")

    def test_the_question_id_is_stable_across_passes(self):
        psq = _psq()
        a = [q["id"] for q in _openings()["questions"]]
        b = [q["id"] for q in _openings()["questions"]]
        self.assertEqual(a, b)
        other = dict(A12, file_hash="h-changed")
        self.assertNotEqual(psq.question_id(PID, "filed", [A12]), psq.question_id(PID, "filed", [other]))

    def test_an_unreadable_questioned_page_is_a_marked_refusal(self):
        psq = _psq()
        out = _openings(gas_readable=False)
        gid = next(q["id"] for q in out["questions"] if q["file_name"] == GAS)
        ref = [r for r in out["rows"] if S._is_refusal(r)]
        self.assertEqual(len(ref), 1)
        self.assertEqual(ref[0]["payload"].get(psq.ROW_KEY), gid)

    def test_the_answer_is_applied(self):
        psq = _psq()
        ids = {q["file_name"]: q["id"] for q in _openings()["questions"]}
        out = _openings(answers={ids[A1X]: psq.EXCLUDE, ids[GAS]: psq.INCLUDE})
        self.assertFalse(any(r.get("sheet_number") in ("A.1.2", "A.1.6") for r in out["rows"]),
                         "excluded: no row")
        gas = [r for r in out["rows"] if r.get("file_name") == GAS]
        self.assertEqual(len(gas), 2)
        self.assertTrue(all(psq.ROW_KEY not in r["payload"] for r in gas),
                        "included: ordinary rows of the track")

    def test_a_plan_in_the_series_is_no_question(self):
        psq = _psq()
        self.assertFalse(psq.is_membership_ambiguous({"sheet_number": "A-101.00"}))
        self.assertTrue(psq.is_membership_ambiguous({"sheet_number": "A.1.2"}))
        self.assertTrue(psq.is_membership_ambiguous({"sheet_number": None}))


class TheQuestionReadsPlainly(unittest.TestCase):

    def test_the_whatsapp_text(self):
        psq = _psq()
        q = {"code": "Q1", "track": "filed", "file_name": A1X,
             "pages": [{"sheet_number": f"A.1.{i}"} for i in range(1, 8)],
             "figures": [{"family": INT, "tag": "F", "without": 36, "with": 72},
                         {"family": WIN, "tag": "W1", "without": 36, "with": 72}]}
        text = psq.message(q, "588 Thomas S Boyland Street")
        self.assertIn("7 floor plans numbered A.1.1 to A.1.7", text)
        self.assertIn("type F doors: 36 without them, 72 with them", text)
        self.assertIn("W1 windows: 36 without them, 72 with them", text)
        self.assertIn("Reply Q1 YES", text)
        self.assertNotRegex(text, r"[0-9a-f]{16}", "no ids")

    def test_a_bare_yes_is_never_an_answer(self):
        psq = _psq()
        self.assertIsNone(psq.parse_reply("yes"))
        self.assertIsNone(psq.parse_reply("1"))
        self.assertEqual(psq.parse_reply("Q1 YES"), ("Q1", psq.INCLUDE))
        self.assertEqual(psq.parse_reply(" q12 no. "), ("Q12", psq.EXCLUDE))
        self.assertIsNone(psq.parse_reply("Q1 yes and also the roof"))


# ══════════════════════════════════════════════════════════════════════════
# 3. The server: stored once, asked once, answered and audited, never sent
#    by the pass or by these tests
# ══════════════════════════════════════════════════════════════════════════

class _NoWire:
    """WaAPI and the send are recorders: a test that reaches them fails
    unless it expects the one confirmation it checks."""

    def __init__(self):
        self.raw, self.messages, self.dms = [], [], []

    async def post_raw(self, *a, **k):
        self.raw.append(a)
        raise AssertionError("a test reached WaAPI")

    async def message(self, chat_id, text, *a, **k):
        self.messages.append((chat_id, text))
        return {"recorded": True}

    async def dm(self, uid, text, **k):
        self.dms.append((uid, text, k))
        return {"recorded": True}


def _db(pm=True, optin=True):
    from bson import ObjectId
    db = AsyncFakeDB()
    db.projects.docs.append({"_id": ObjectId(PID), "name": "588 Thomas S Boyland Street",
                             "company_id": CID})
    if pm:
        db.users.docs.append({"_id": ObjectId("6a5e1571c7ac7a6451aa2d40"), "role": "pm",
                              "full_name": "Roey Fishman", "company_id": CID,
                              "pm_access": "full", "assigned_projects": [], "phone": "5550008154"})
    db.users.docs.append({"_id": ObjectId("6a5e1571c7ac7a6451aa2d41"), "role": "superintendent",
                          "full_name": "Michael Cespedes", "company_id": CID,
                          "assigned_projects": [PID]})
    return db


PM_ID = "6a5e1571c7ac7a6451aa2d40"


def _detected():
    from lib import plan_set_questions as psq
    q = psq.detect(PID, "filed", [(A12, "x"), (A16, "x")])
    return q


def _run(coro):
    return asyncio.run(coro)


class StoredOnceAskedOnce(unittest.TestCase):

    def _patches(self, db, wire, refusal=None):
        async def reason(uid, kind):
            return refusal
        return [patch.object(server, "db", db),
                patch.object(server, "_waapi_post_raw", wire.post_raw),
                patch.object(server, "send_whatsapp_message", wire.message),
                patch.object(server, "send_whatsapp_dm", wire.dm),
                patch.object(server, "_dm_refusal_reason", reason)]

    def _with(self, db, wire, fn, refusal=None):
        ps = self._patches(db, wire, refusal)
        for p in ps:
            p.start()
        try:
            return _run(fn())
        finally:
            for p in ps:
                p.stop()

    def test_a_question_is_stored_once_and_never_reopened(self):
        psq = _psq()
        _server_has("_store_set_questions")
        db, wire = _db(), _NoWire()
        rows = _a1x(mark=None)
        det = _detected()
        for r in rows:
            r["payload"].update(set_question=det[0]["id"], set_question_label=det[0]["short"])
        self._with(db, wire, lambda: server._store_set_questions(PID, _detected(), rows, "op"))
        coll = db[psq.COLLECTION].docs
        self.assertEqual(len(coll), 1)
        self.assertEqual(coll[0]["status"], psq.OPEN)
        self.assertEqual(coll[0]["code"], "Q1")
        self.assertIn({"family": INT, "tag": "F", "without": 0, "with": 10}, coll[0]["figures"])
        coll[0]["status"] = psq.ANSWERED
        coll[0]["answer"] = psq.EXCLUDE
        self._with(db, wire, lambda: server._store_set_questions(PID, _detected(), rows, "op"))
        self.assertEqual(len(coll), 1)
        self.assertEqual(coll[0]["status"], psq.ANSWERED, "an answered question is never re-opened")
        opened = [a for a in db.audit_logs.docs if a["action"] == "plan_set_question_opened"]
        self.assertEqual(len(opened), 1)
        self.assertEqual(wire.dms + wire.messages + wire.raw, [], "storing sends nothing")

    def test_asked_once_to_the_pm_on_record_never_again(self):
        psq = _psq()
        _server_has("_store_set_questions", "_ask_set_questions")
        db, wire = _db(), _NoWire()
        self._with(db, wire, lambda: server._store_set_questions(PID, _detected(), [], "op"))
        self._with(db, wire, lambda: server._ask_set_questions(PID, "op"))
        self.assertEqual(len(wire.dms), 1)
        uid, text, kw = wire.dms[0]
        self.assertEqual(uid, PM_ID)
        self.assertEqual(kw.get("kind"), psq.WA_KIND)
        self.assertIn("Reply Q1 YES", text)
        self._with(db, wire, lambda: server._ask_set_questions(PID, "op"))
        self.assertEqual(len(wire.dms), 1, "a delivered question is never sent again")
        q = db[psq.COLLECTION].docs[0]
        self.assertEqual(q["asked_user_ids"], [PM_ID])
        self.assertTrue(any(a["action"] == "plan_set_question_asked" for a in db.audit_logs.docs))
        self.assertEqual(wire.raw, [])

    def test_no_pm_or_sm_the_question_is_stored_unasked(self):
        psq = _psq()
        _server_has("_store_set_questions", "_ask_set_questions")
        db, wire = _db(pm=False), _NoWire()
        self._with(db, wire, lambda: server._store_set_questions(PID, _detected(), [], "op"))
        self._with(db, wire, lambda: server._ask_set_questions(PID, "op"))
        self.assertEqual(wire.dms, [], "the superintendent is no PM/SM, and nobody else is")
        q = db[psq.COLLECTION].docs[0]
        self.assertEqual(q["status"], psq.OPEN)
        self.assertIn("no PM or Site Manager on record", q.get("unasked_reason") or "")

    def test_a_pm_who_cannot_be_reached_is_said_not_skipped(self):
        psq = _psq()
        _server_has("_store_set_questions", "_ask_set_questions")
        db, wire = _db(), _NoWire()
        self._with(db, wire, lambda: server._store_set_questions(PID, _detected(), [], "op"))
        self._with(db, wire, lambda: server._ask_set_questions(PID, "op"), refusal="no_optin")
        self.assertEqual(wire.dms, [])
        q = db[psq.COLLECTION].docs[0]
        self.assertIn("Roey Fishman (no_optin)", q.get("unasked_reason") or "")


class TheAnswerIsRecordedAuditedAndApplied(unittest.TestCase):

    def _asked(self):
        psq = _psq()
        _server_has("_store_set_questions", "_handle_set_question_reply", "_record_set_answer")
        db, wire = _db(), _NoWire()
        t = StoredOnceAskedOnce()
        t._with(db, wire, lambda: server._store_set_questions(PID, _detected(), [], "op"))
        t._with(db, wire, lambda: server._ask_set_questions(PID, "op"))
        return psq, db, wire, t

    def test_the_pms_whatsapp_reply_is_the_answer(self):
        psq, db, wire, t = self._asked()

        async def optin(phone):
            return {"user_id": PM_ID, "phone": phone}
        with patch.object(server, "_active_optin_for_phone", optin):
            ok = t._with(db, wire, lambda: server._handle_set_question_reply(
                "15550008154@c.us", "Q1", psq.EXCLUDE))
            again = t._with(db, wire, lambda: server._handle_set_question_reply(
                "15550008154@c.us", "Q1", psq.INCLUDE))
        self.assertTrue(ok)
        self.assertFalse(again, "answered once: a second reply changes nothing")
        q = db[psq.COLLECTION].docs[0]
        self.assertEqual((q["status"], q["answer"], q["answered_by"], q["answered_via"]),
                         (psq.ANSWERED, psq.EXCLUDE, PM_ID, "whatsapp"))
        audit = [a for a in db.audit_logs.docs if a["action"] == "plan_set_question_answered"]
        self.assertEqual(len(audit), 1)
        self.assertEqual((audit[0]["user_id"], audit[0]["details"]["answer"]), (PM_ID, psq.EXCLUDE))
        self.assertEqual(len(wire.messages), 1, "one confirmation, to a recorder")
        self.assertIn("not part of the filed set", wire.messages[0][1])

    def test_someone_not_asked_cannot_answer(self):
        psq, db, wire, t = self._asked()

        async def optin(phone):
            return {"user_id": "someone-else", "phone": phone}
        with patch.object(server, "_active_optin_for_phone", optin):
            ok = t._with(db, wire, lambda: server._handle_set_question_reply(
                "15550001111@c.us", "Q1", psq.INCLUDE))
        self.assertFalse(ok)
        self.assertEqual(db[psq.COLLECTION].docs[0]["status"], psq.OPEN)

    def test_a_pm_who_was_not_asked_cannot_answer(self):
        """A second PM, on record but added after the question was sent, did
        not see it: their "Q1 YES" is not its answer."""
        psq, db, wire, t = self._asked()
        from bson import ObjectId
        late = "6a5e1571c7ac7a6451aa2d42"
        db.users.docs.append({"_id": ObjectId(late), "role": "pm", "full_name": "Late PM",
                              "company_id": CID, "pm_access": "full", "assigned_projects": []})

        async def optin(phone):
            return {"user_id": late, "phone": phone}
        with patch.object(server, "_active_optin_for_phone", optin):
            ok = t._with(db, wire, lambda: server._handle_set_question_reply(
                "15550002222@c.us", "Q1", psq.INCLUDE))
        self.assertFalse(ok)
        self.assertEqual(db[psq.COLLECTION].docs[0]["status"], psq.OPEN)

    def test_the_admin_endpoint_records_and_audits(self):
        psq, db, wire, t = self._asked()
        qid = db[psq.COLLECTION].docs[0]["_id"]
        body = server.PlanSetAnswer(answer="include")
        out = t._with(db, wire, lambda: server.answer_plan_set_question(
            PID, qid, body, current_user={"id": "admin-1", "full_name": "Operator"}))
        self.assertEqual(out["answer"], "include")
        self.assertTrue(any(a["action"] == "plan_set_question_answered" and a["user_id"] == "admin-1"
                            for a in db.audit_logs.docs))

    def test_the_answer_is_applied_on_the_next_pass(self):
        psq = _psq()
        _server_has("_plan_glyph_pass")
        from tests.test_two_drawing_tracks import _raw
        from bson import ObjectId
        db, wire = AsyncFakeDB(), _NoWire()
        proj = ObjectId()
        raw, files = _raw()
        for k, f in files.items():
            db.project_files.docs.append(dict(f, _id=k, project_id=str(proj), is_deleted=False))
        for p in raw:
            db.document_page_index.docs.append(dict(p, project_id=str(proj)))
        a_page = next(p for p in raw if p["_id"] == "ar325#12")
        db.plan_records.docs.append({"project_id": str(proj), "record_type": "schedule",
                                     "page_id": str(a_page["_id"]), "sheet_number": "A-400.00",
                                     "tier": "schedule_cell",
                                     "payload": {"name": WIN, "columns": [{"header": "W1 NUMBER"}],
                                                 "rows": []}})
        db[psq.COLLECTION].docs.append({"_id": "q-a1x", "project_id": str(proj), "status": "answered",
                                        "answer": "exclude", "code": "Q1"})
        seen = []

        def fake_pass(pages, open_page, schedules, door_pages, track="filed", sweeps=None,
                      plan_only=None, opening_schedules=(), set_answers=None):
            seen.append(set_answers)
            return {"rows": [], "summary": {}, "opening_rows": [], "opening_health": [],
                    "set_questions": []}

        async def live(_pid):
            return list(files)

        async def write(_pid, rows):
            return len(rows)

        def no_plan_only(pid, _page_ids):
            return {"project_id": str(pid), "record_type": "no-plan-only-family-here"}
        with patch.object(server, "db", db), patch.object(server, "_live_plan_file_ids", live), \
                patch("lib.plan_glyph_pass.run_pass", fake_pass), \
                patch.object(server, "_glyph_set_health", lambda *a, **k: []), \
                patch.object(server, "_write_glyph_records", write), \
                patch.object(server, "_write_set_health", write), \
                patch.object(server, "send_whatsapp_dm", wire.dm), \
                patch.object(server, "send_whatsapp_message", wire.message), \
                patch.object(server, "_waapi_post_raw", wire.post_raw), \
                patch("lib.plan_only.record_query", no_plan_only):
            _run(server._plan_glyph_pass(str(proj)))
        self.assertTrue(seen and all(s == {"q-a1x": "exclude"} for s in seen),
                        f"the stored answer reaches the pass: {seen}")


class NothingIsSentButByTheOperator(unittest.TestCase):

    def test_the_pass_stores_its_questions_and_sends_nothing(self):
        psq = _psq()
        _server_has("_store_set_questions")
        from tests.test_two_drawing_tracks import _raw
        from bson import ObjectId
        db, wire = _db(), _NoWire()
        raw, files = _raw()
        for k, f in files.items():
            db.project_files.docs.append(dict(f, _id=k, project_id=PID, is_deleted=False))
        for p in raw:
            db.document_page_index.docs.append(dict(p, project_id=PID))
        a_page = next(p for p in raw if p["_id"] == "ar325#12")
        db.plan_records.docs.append({"project_id": PID, "record_type": "schedule",
                                     "page_id": str(a_page["_id"]), "sheet_number": "A-400.00",
                                     "tier": "schedule_cell",
                                     "payload": {"name": WIN, "columns": [{"header": "W1 NUMBER"}],
                                                 "rows": []}})

        def fake_pass(pages, open_page, schedules, door_pages, track="filed", sweeps=None,
                      plan_only=None, opening_schedules=(), set_answers=None):
            return {"rows": [], "summary": {}, "opening_rows": [], "opening_health": [],
                    "set_questions": _detected() if track == "filed" else []}

        async def live(_pid):
            return list(files)

        async def write(_pid, rows):
            return len(rows)

        async def reachable(uid, kind):
            return None                     # were anything to ask, it would go out

        def no_plan_only(pid, _page_ids):
            return {"project_id": str(pid), "record_type": "no-plan-only-family-here"}
        with patch.object(server, "db", db), patch.object(server, "_live_plan_file_ids", live), \
                patch("lib.plan_glyph_pass.run_pass", fake_pass), \
                patch.object(server, "_glyph_set_health", lambda *a, **k: []), \
                patch.object(server, "_write_glyph_records", write), \
                patch.object(server, "_write_set_health", write), \
                patch.object(server, "_dm_refusal_reason", reachable), \
                patch.object(server, "send_whatsapp_dm", wire.dm), \
                patch.object(server, "send_whatsapp_message", wire.message), \
                patch.object(server, "_waapi_post_raw", wire.post_raw), \
                patch("lib.plan_only.record_query", no_plan_only):
            _run(server._plan_glyph_pass(PID))
        self.assertEqual(len(db[psq.COLLECTION].docs), 1, "the pass stored the question")
        self.assertEqual(wire.dms + wire.messages + wire.raw, [], "and sent nothing")

    def test_only_the_named_operator_action_asks(self):
        _psq()
        _server_has("_ask_set_questions")
        src = Path(server.__file__).read_text(encoding="utf-8")
        calls = [m.start() for m in re.finditer(r"(?<![\w])_ask_set_questions\(", src)
                 if not src.startswith("def ", m.start() - 4)]
        self.assertEqual(len(calls), 1, "one call site")
        i = src.index("async def ask_plan_set_questions(")
        self.assertIn("_ask_set_questions(", src[i:i + 900])
        self.assertIn("require_project_admin_access", src[i - 300:i])
        sends = [m.start() for m in re.finditer(r"send_whatsapp_dm\(.{0,200}?psq\.WA_KIND", src, re.S)]
        j = src.index("async def _ask_set_questions(")
        k = src.index("\nasync def ", j + 10)
        self.assertTrue(sends and all(j < s < k for s in sends),
                        "the question is sent from _ask_set_questions alone")


if __name__ == "__main__":
    unittest.main()
