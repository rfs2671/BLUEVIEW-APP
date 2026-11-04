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
        # ruling 33: the operator may ask - the operator-admitting, audited gate
        self.assertIn("require_project_admin_access", src[i - 300:i])
        self.assertIn("get_admin_user", src[i:i + 200])
        sends = [m.start() for m in re.finditer(r"send_whatsapp_dm\(.{0,200}?psq\.WA_KIND", src, re.S)]
        j = src.index("async def _ask_set_questions(")
        k = src.index("\nasync def ", j + 10)
        self.assertTrue(sends and all(j < s < k for s in sends),
                        "the question is sent from _ask_set_questions alone")


# ══════════════════════════════════════════════════════════════════════════
# 4. Ruling 33: the operator VIEWS and ASKS; he never ANSWERS. Real requests
#    through server.app (middleware, JWT, each route's own dependencies) over
#    the fake database - the request-level proof harness.
# ══════════════════════════════════════════════════════════════════════════

def _opworld():
    from tests.test_operator_project_admin_access import _db as op_db, PROJ_A, CO_A
    db = op_db()
    db["plan_set_questions"].docs.append({
        "_id": "q-a1x", "project_id": str(PROJ_A), "company_id": CO_A, "code": "Q1",
        "status": "open", "track": "filed", "file_name": A1X, "short": "the A.1.x plans",
        "label": f"the A.1.x plans (A.1.1 to A.1.7, {A1X})",
        "pages": [{"sheet_number": f"A.1.{i}", "page_number": 10 + i, "sheet_title": "FLOOR PLAN"}
                  for i in range(1, 8)],
        "figures": [{"family": INT, "tag": "F", "without": 36, "with": 72}],
        "asked": [], "asked_user_ids": []})
    return db, str(PROJ_A)


async def _http(db, email, pw, calls):
    import httpx
    wire = _NoWire()
    out = {}
    with patch.object(server, "db", db), patch.object(server, "send_whatsapp_dm", wire.dm),             patch.object(server, "send_whatsapp_message", wire.message),             patch.object(server, "_waapi_post_raw", wire.post_raw):
        if hasattr(server, "auth_rate_limiter") and hasattr(server.auth_rate_limiter, "requests"):
            server.auth_rate_limiter.requests.clear()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                     base_url="http://t") as c:
            r = await c.post("/api/auth/login", json={"email": email, "password": pw})
            assert r.status_code == 200, r.text
            h = {"Authorization": f"Bearer {r.json()['token']}"}
            for method, path, body in calls:
                r = await c.request(method, path, json=body, headers=h)
                out[(method, path)] = (r.status_code, r.text)
    return out, wire


class TheOperatorViewsAndAsksButNeverAnswers(unittest.TestCase):

    def _paths(self, pid):
        base = f"/api/projects/{pid}/plan-set-questions"
        return base, base + "/ask", base + "/q-a1x/answer"

    def test_the_operator_views_and_asks_audited(self):
        _psq()
        _server_has("_ask_set_questions")
        db, pid = _opworld()
        view, ask, _answer = self._paths(pid)
        got, wire = _run(_http(db, "op@x.test", "pw-op-123",
                               [("GET", view, None), ("POST", ask, None)]))
        status, body = got[("GET", view)]
        self.assertEqual(status, 200, body)
        self.assertIn("Reply Q1 YES", body, "the exact message text is shown")
        self.assertEqual(got[("POST", ask)][0], 200, got[("POST", ask)][1])
        self.assertEqual(len([r for r in db.audit_logs.docs
                              if r.get("action") == "operator_project_admin_access"]), 2,
                         "every operator use is audited")
        self.assertEqual(wire.raw, [], "nothing reached WaAPI")

    def test_the_operator_is_refused_on_answer(self):
        _psq()
        _server_has("_record_set_answer")
        db, pid = _opworld()
        _view, _ask, answer = self._paths(pid)
        got, _w = _run(_http(db, "op@x.test", "pw-op-123", [("POST", answer, {"answer": "include"})]))
        status, body = got[("POST", answer)]
        self.assertEqual(status, 403, body)
        q = db["plan_set_questions"].docs[0]
        self.assertEqual((q["status"], q.get("answer")), ("open", None))
        self.assertFalse(any(a.get("action") == "plan_set_question_answered"
                             for a in db.audit_logs.docs))

    def test_the_handler_itself_refuses_the_operator(self):
        """Even past the gate: a later change to the route's dependencies
        cannot let the operator answer for a project."""
        _psq()
        _server_has("answer_plan_set_question")
        from fastapi import HTTPException
        db = _db()
        db["plan_set_questions"].docs.append({"_id": "q-a1x", "project_id": PID, "status": "open"})
        with patch.object(server, "db", db):
            with self.assertRaises(HTTPException) as cm:
                _run(server.answer_plan_set_question(
                    PID, "q-a1x", server.PlanSetAnswer(answer="include"),
                    current_user={"id": "op", "is_platform_operator": True, "role": "owner"}))
        self.assertEqual(cm.exception.status_code, 403)
        self.assertEqual(db["plan_set_questions"].docs[0]["status"], "open")

    def test_the_companys_admin_answers_in_app(self):
        _psq()
        _server_has("_record_set_answer")
        db, pid = _opworld()
        _view, _ask, answer = self._paths(pid)
        got, _w = _run(_http(db, "a@a.test", "pw-a-123", [("POST", answer, {"answer": "exclude"})]))
        self.assertEqual(got[("POST", answer)][0], 200, got[("POST", answer)][1])
        q = db["plan_set_questions"].docs[0]
        self.assertEqual((q["status"], q["answer"], q["answered_via"]), ("answered", "exclude", "admin"))

    def test_another_companys_admin_reaches_none_of_them(self):
        _psq()
        db, pid = _opworld()
        view, ask, answer = self._paths(pid)
        got, wire = _run(_http(db, "b@b.test", "pw-b-123",
                               [("GET", view, None), ("POST", ask, None),
                                ("POST", answer, {"answer": "include"})]))
        for k, (status, body) in got.items():
            self.assertEqual(status, 403, f"{k}: {body}")
        self.assertEqual(db["plan_set_questions"].docs[0]["status"], "open")
        self.assertEqual(wire.dms + wire.messages, [])


# ══════════════════════════════════════════════════════════════════════════
# 5. REPLACES (Roy, 10-30): "answers can be IN / NOT IN / REPLACES <sheet>.
#    The yes/no form can't express supersession."
# ══════════════════════════════════════════════════════════════════════════
#
# The gas-change file's Roof Plan (page 2, unnumbered) is the roof plan, and
# A-105.01 of AR - 8.18.26 is not; its page 1 (A-100.00, FIRST FLOOR PLAN) is
# the first floor plan and A-100.01 is not - and page 1 is in NO track today
# (A-100.01 wins by date), so the question, which covers page 2, cannot name
# it. The answer carries an explicit list; the pass applies it to each track's
# pages before anything reads them.

AR325, AR818, GASF, MHF = "ar325", "ar818", "gas", "mh"
A1XF = "a1x"
FILES5 = {AR325: {"name": "AR - 3.28.25.pdf"}, AR818: {"name": "AR - 8.18.26.pdf"},
          GASF: {"name": GAS}, A1XF: {"name": A1X}, MHF: {"name": "MH - 7.2.26.pdf"}}


def _raw5():
    """The filed set as 588 Boyland's index holds it: the March A-100.00 and
    A-105.00 (superseded by date), the 8.18.26 A-100.01 / A-105.01, the
    gas-change A-100.00 (superseded by A-100.01) and its unnumbered Roof
    Plan, the second architect's A.1.1-A.1.7, and the mechanical plans."""
    pages = [(AR325, 11, "A-100.00", "FIRST FLOOR PLAN"), (AR325, 12, "A-101.00", "SECOND FLOOR PLAN"),
             (AR325, 16, "A-105.00", "ROOF AND BULKEAD PLAN"),
             (AR818, 6, "A-100.01", "FIRST FLOOR PLAN"), (AR818, 7, "A-105.01", "ROOF AND BULKEAD PLAN"),
             (AR818, 8, "A-200.01", "FRONT AND REAR ELEVATIONS"),
             (GASF, 1, "A-100.00", "FIRST FLOOR PLAN"), (GASF, 2, None, "Roof Plan"),
             (MHF, 2, "M-100.00", "HVAC FIRST FLOOR PLAN"), (MHF, 3, "M-101.00", "HVAC SECOND FLOOR PLAN"),
             (MHF, 6, "M-105.00", "HVAC ROOF PLAN")]
    pages += [(A1XF, 10 + i, f"A.1.{i}", "FLOOR PLAN") for i in range(1, 8)]
    return [{"_id": f"{f}#{n}", "file_id": f, "file_hash": f"h-{f}", "file_name": FILES5[f]["name"],
             "page_number": n, "sheet_number": sn, "sheet_title": t, "discipline": "AR",
             "superseded_by": None} for f, n, sn, t in pages]


def _psq5():
    """lib.plan_set_questions with the REPLACES answer - an assertion, not an
    AttributeError, on a tree without it."""
    psq = _psq()
    assert hasattr(psq, "REPLACES") and hasattr(psq, "validate_replacements")         and hasattr(psq, "apply_decisions"), "answers are include / exclude only in this tree"
    return psq


def _track(decisions=(), notes=None, raw=None):
    import inspect
    _server_has("_glyph_track_pages")
    assert "decisions" in inspect.signature(server._glyph_track_pages).parameters,         "the track pages do not take the office's answers in this tree"
    got = server._glyph_track_pages(raw or _raw5(), FILES5, set(FILES5), decisions=list(decisions),
                                    notes=notes)
    return {t: ps for t, ps in got}["filed"]


def _ids(pages):
    return {p["_id"]: p.get("sheet_number") for p in pages}


def _question(file_id, n_pages):
    """The question the pass raises for a file, by the real pairing."""
    from lib import plan_derive as derive
    psq = _psq5()
    rows = [dict(p, page_id=p["_id"]) for p in _track()]
    paired = derive.pair_plan_sheets(rows)
    refused = [(p, why) for p, why, role in paired["refused"] if role == derive.ROLE_ARCHITECTURAL]
    qs = [q for q in psq.detect(PID, "filed", refused) if q["file_id"] == file_id]
    assert len(qs) == 1 and len(qs[0]["pages"]) == n_pages, qs
    return dict(qs[0], _id=qs[0]["id"], code="Q1" if file_id == A1XF else "Q2")


def _repl(page_id, file_id, page_number, sheet_number):
    return {"page_id": page_id, "replaces": {"file_id": file_id, "page_number": page_number,
                                             "sheet_number": sheet_number}}


#: Roy's answer: gas p2 replaces A-105.01, gas p1 replaces A-100.01
ROY = [_repl("gas#2", AR818, 7, "A-105.01"), _repl("gas#1", AR818, 6, "A-100.01")]


def _resolved(items=None):
    psq = _psq5()
    q = _question(GASF, 1)
    got, errs = psq.validate_replacements(q, items or ROY, _track(), _raw5())
    assert not errs, errs
    return got


def _answered_q2(items=None):
    return dict(_question(GASF, 1), status="answered", answer="replaces",
                replacements=_resolved(items))


def _answered_q1():
    return dict(_question(A1XF, 7), status="answered", answer="exclude")


class ARepliesAnswerReplacesAPageOfTheTrack(unittest.TestCase):

    def test_today_gas_p1_is_in_no_track_and_the_roof_plan_is_refused(self):
        """The starting point: A-100.01 and A-105.01 win by date; gas p1 is in
        no track; the unnumbered Roof Plan is in the filed track, refused."""
        ids = _ids(_track())
        self.assertIn("ar818#6", ids)
        self.assertIn("ar818#7", ids)
        self.assertNotIn("gas#1", ids)
        self.assertIn("gas#2", ids)

    def test_the_replaced_pages_leave_and_the_replacing_pages_take_their_place(self):
        _psq5()
        ids = _ids(_track([_answered_q2()]))
        self.assertNotIn("ar818#6", ids, "A-100.01 leaves the track")
        self.assertNotIn("ar818#7", ids, "A-105.01 leaves the track")
        self.assertEqual(ids.get("gas#1"), "A-100.00", "gas p1 - in no track before - is in")
        self.assertEqual(ids.get("gas#2"), "A-105.01", "the unnumbered roof plan is paired as the "
                                                       "sheet the office said it replaces")
        self.assertEqual(sum(1 for p in _track([_answered_q2()]) if p["_id"] == "gas#2"), 1,
                         "it left its old place: one entry")

    def test_the_pairing_rules_are_unchanged_and_the_roof_plan_is_no_question_any_more(self):
        from lib import plan_derive as derive
        psq = _psq5()
        pages = [dict(p, page_id=p["_id"]) for p in _track([_answered_q2()])]
        paired = derive.pair_plan_sheets(pages)
        pairs = {(a["_id"], m["_id"]) for a, m in paired["pairs"]}
        self.assertIn(("gas#1", "mh#2"), pairs, "the gas first floor pairs with M-100.00 by number")
        self.assertIn(("gas#2", "mh#6"), pairs, "the gas roof pairs with M-105.00 by number")
        self.assertFalse([p for p, _w, _r in paired["refused"] if p["file_id"] == GASF])
        refused = [(p, w) for p, w, r in paired["refused"] if r == derive.ROLE_ARCHITECTURAL]
        self.assertEqual([q["file_id"] for q in psq.detect(PID, "filed", refused)], [A1XF],
                         "only the A.1.x question is still raised")

    def test_the_title_stays_its_own(self):
        by = {p["_id"]: p for p in _track([_answered_q2()])}
        self.assertEqual(by["gas#2"]["sheet_title"], "Roof Plan")
        self.assertEqual(by["gas#1"]["sheet_title"], "FIRST FLOOR PLAN")
        self.assertEqual(by["gas#2"]["file_name"], GAS)

    def test_the_track_keeps_its_order_and_other_pages(self):
        base = [p["_id"] for p in _track()]
        got = [p["_id"] for p in _track([_answered_q2()])]
        i = base.index("ar818#6")
        self.assertEqual(got[i], "gas#1", "in the replaced page's place")
        self.assertEqual([x for x in got if x not in ("gas#1", "gas#2")],
                         [x for x in base if x not in ("ar818#6", "ar818#7", "gas#2")])

    def test_q1_exclude_and_q2_replaces_apply_together(self):
        notes = []
        ids = _ids(_track([_answered_q1(), _answered_q2()], notes))
        self.assertFalse([i for i in ids if i.startswith("a1x#")], "A.1.1 to A.1.7 are out")
        self.assertEqual((ids.get("gas#1"), ids.get("gas#2")), ("A-100.00", "A-105.01"))
        self.assertNotIn("ar818#6", ids)
        self.assertEqual(sorted((n["code"], n["answer"], n["applied"]) for n in notes),
                         [("Q1", "exclude", True), ("Q2", "replaces", True)])

    def test_exclude_leaves_the_pages_out_of_the_whole_track(self):
        """Before: only the opening rows were left out; the pairing still
        refused the pages (a refusal row each) and the walls step read them."""
        ids = _ids(_track([_answered_q1()]))
        self.assertFalse([i for i in ids if i.startswith("a1x#")])
        self.assertIn("gas#2", ids, "the other question's page is untouched")

    def test_an_include_changes_no_page_list(self):
        got = _ids(_track([dict(_answered_q1(), answer="include")]))
        self.assertEqual(got, _ids(_track()))

    def test_the_input_is_not_changed(self):
        raw = _raw5()
        before = [dict(p) for p in raw]
        _track([_answered_q2()], raw=raw)
        self.assertEqual(raw, before)


class AReplacementIsRefusedWhenAnyPageIsAmbiguous(unittest.TestCase):
    """Nothing is inferred: each rule has its own refusal."""

    def _refused(self, items, track=None, pool=None, question=None, expect=""):
        psq = _psq5()
        got, errs = psq.validate_replacements(question or _question(GASF, 1), items,
                                              track or _track(), pool or _raw5())
        self.assertEqual(got, [], "refused: nothing resolved")
        self.assertTrue(errs, "a reason is given")
        self.assertRegex("; ".join(errs), expect)

    def test_roys_answer_is_accepted(self):
        got = _resolved()
        self.assertEqual([(r["page_id"], r["replaces"]["sheet_number"], r["takes_sheet_number"])
                          for r in got],
                         [("gas#2", "A-105.01", "A-105.01"), ("gas#1", "A-100.01", "A-100.00")])

    def test_no_list(self):
        for none in (None, []):
            self._refused(none, expect="needs the list")

    def test_a_malformed_item(self):
        self._refused([{"page_id": "gas#2"}], expect="needs page_id")
        self._refused([{"replaces": {"file_id": AR818, "page_number": 7, "sheet_number": "A-105.01"}}],
                      expect="needs page_id")

    def test_the_replacing_page_must_exist(self):
        self._refused([_repl("nope", AR818, 7, "A-105.01"), ROY[1]], expect="not a page of this project")

    def test_the_replacing_page_must_be_in_the_questions_file(self):
        self._refused([_repl("ar325#12", AR818, 7, "A-105.01"), ROY[1]],
                      expect="not in the question's file")

    def test_the_replaced_page_must_match_on_file_page_and_sheet(self):
        for bad in (_repl("gas#2", AR818, 7, "A-105.00"),        # wrong sheet number
                    _repl("gas#2", AR818, 9, "A-105.01"),        # wrong page
                    _repl("gas#2", "nope", 7, "A-105.01")):      # wrong file
            self._refused([bad, ROY[1]], expect="not one current page")

    def test_the_replaced_page_must_be_current_in_the_track(self):
        """The March A-105.00 lost to A-105.01 by date: it is in no track."""
        self._refused([_repl("gas#2", AR325, 16, "A-105.00"), ROY[1]], expect="not one current page")

    def test_the_replaced_page_must_be_a_plan_of_the_series(self):
        self._refused([_repl("gas#2", AR818, 8, "A-200.01"), ROY[1]],
                      expect="not an architectural plan of the plan series")

    def test_a_numbered_replacing_page_must_be_the_same_floor_sequence(self):
        raw = _raw5() + [{"_id": "gas#3", "file_id": GASF, "file_hash": "h-gas", "file_name": GAS,
                          "page_number": 3, "sheet_number": "A-101.00",
                          "sheet_title": "SECOND FLOOR PLAN", "discipline": "AR", "superseded_by": None}]
        self._refused([ROY[0], _repl("gas#3", AR818, 6, "A-100.01")], pool=raw,
                      expect="not the same floor sequence")

    def test_the_titles_may_not_name_different_floors(self):
        raw = _raw5()
        raw[[p["_id"] for p in raw].index("gas#1")]["sheet_title"] = "SECOND FLOOR PLAN"
        self._refused(ROY, pool=raw, expect="different floors")

    def test_the_replacing_page_must_be_titled_as_a_plan(self):
        raw = _raw5()
        raw[[p["_id"] for p in raw].index("gas#2")]["sheet_title"] = "Gas riser diagram"
        self._refused(ROY, pool=raw, expect="not titled as a plan")

    def test_a_page_named_twice(self):
        self._refused([ROY[0], _repl("gas#2", AR818, 6, "A-100.01")], expect="named twice")
        extra = {"_id": "gas#3", "file_id": GASF, "file_hash": "h-gas", "file_name": GAS,
                 "page_number": 3, "sheet_number": None, "sheet_title": "Roof Plan",
                 "discipline": "AR", "superseded_by": None}
        self._refused([ROY[0], _repl("gas#3", AR818, 7, "A-105.01")], pool=_raw5() + [extra],
                      expect="named twice")

    def test_every_page_the_question_covers_must_be_decided(self):
        """The question covers gas p2; an answer that names only p1 leaves p2
        refused and asked about - the answer must decide the whole question."""
        self._refused([ROY[1]], expect="no replacement names it")

    def test_two_plans_may_not_end_up_on_one_sequence(self):
        track = _track() + [{"_id": "x#1", "file_id": "x", "file_name": "other.pdf", "page_number": 1,
                             "sheet_number": "A-100.02", "sheet_title": "FIRST FLOOR PLAN"}]
        self._refused(ROY, track=track, expect="share a sequence")


class ARefusedReplacementIsAppliedNowhere(unittest.TestCase):

    def test_all_or_nothing(self):
        """One bad item and none of the question's replacements applies: the
        pages read as before, the note says why."""
        q = _answered_q2()
        q["replacements"] = [q["replacements"][0],
                             dict(q["replacements"][1], replaces=dict(q["replacements"][1]["replaces"],
                                                                      sheet_number="A-100.09"))]
        notes = []
        self.assertEqual(_ids(_track([q], notes)), _ids(_track()))
        self.assertEqual([(n["applied"], "not one current page" in " ".join(n["detail"]))
                          for n in notes], [(False, True)])

    def test_a_replaced_page_that_is_gone_since_the_answer(self):
        raw = [p for p in _raw5() if p["_id"] != "ar818#7"]
        notes = []
        self.assertEqual(_ids(_track([_answered_q2()], notes, raw=raw)), _ids(_track(raw=raw)))
        self.assertFalse(notes[0]["applied"])

    def test_an_unapplied_replacement_is_a_log_line_not_a_pick(self):
        q = _answered_q2()
        q["replacements"][0]["replaces"]["sheet_number"] = "A-105.09"
        with self.assertLogs(level="WARNING") as cm:
            _track([q])
        self.assertTrue(any("NOT applied" in m for m in cm.output), cm.output)


class AReplacesAnswerIsRecordedByTheOfficeOnly(unittest.TestCase):

    def _world(self):
        from bson import ObjectId
        db = AsyncFakeDB()
        db.projects.docs.append({"_id": ObjectId(PID), "name": "588", "company_id": CID})
        for fid, f in FILES5.items():
            db.project_files.docs.append(dict(f, _id=fid, project_id=PID, is_deleted=False))
        for p in _raw5():
            db.document_page_index.docs.append(dict(p, project_id=PID))
        q = _question(GASF, 1)
        doc = {k: v for k, v in q.items() if k != "id"}
        doc.update(project_id=PID, company_id=CID, status="open", asked=[], asked_user_ids=[])
        db["plan_set_questions"].docs.append(doc)
        return db, doc["_id"]

    def _patches(self, db):
        async def live(_pid):
            return list(FILES5)
        return [patch.object(server, "db", db), patch.object(server, "_live_plan_file_ids", live)]

    def _post(self, db, qid, body):
        ps = self._patches(db)
        for p in ps:
            p.start()
        try:
            return _run(server.answer_plan_set_question(PID, qid, body,
                                                        current_user={"id": "admin-1", "full_name": "Roy"}))
        finally:
            for p in ps:
                p.stop()

    def test_the_admin_route_records_the_list_and_audits_it(self):
        _server_has("PlanSetReplacement")
        db, qid = self._world()
        body = server.PlanSetAnswer(answer="replaces", replacements=ROY)
        out = self._post(db, qid, body)
        self.assertEqual(out["answer"], "replaces")
        q = db["plan_set_questions"].docs[0]
        self.assertEqual((q["status"], q["answer"], q["answered_via"]), ("answered", "replaces", "admin"))
        self.assertEqual([(r["page_id"], r["replaces"]["sheet_number"], r["takes_sheet_number"])
                          for r in q["replacements"]],
                         [("gas#2", "A-105.01", "A-105.01"), ("gas#1", "A-100.01", "A-100.00")])
        audit = [a for a in db.audit_logs.docs if a["action"] == "plan_set_question_answered"]
        self.assertEqual(len(audit), 1)
        self.assertEqual(len(audit[0]["details"]["replacements"]), 2, "the replacements are in the audit")
        self.assertEqual(audit[0]["details"]["answer"], "replaces")

    def test_a_replacement_the_pages_do_not_support_is_422_and_stores_nothing(self):
        from fastapi import HTTPException
        _server_has("PlanSetReplacement")
        db, qid = self._world()
        bad = [_repl("gas#2", AR818, 7, "A-105.00"), ROY[1]]
        with self.assertRaises(HTTPException) as cm:
            self._post(db, qid, server.PlanSetAnswer(answer="replaces", replacements=bad))
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIn("not one current page", cm.exception.detail)
        self.assertEqual(db["plan_set_questions"].docs[0]["status"], "open")
        self.assertFalse([a for a in db.audit_logs.docs if a["action"] == "plan_set_question_answered"])

    def test_the_body_must_agree_with_the_answer(self):
        _server_has("PlanSetReplacement")
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            server.PlanSetAnswer(answer="replaces")
        with self.assertRaises(ValidationError):
            server.PlanSetAnswer(answer="include", replacements=ROY)
        server.PlanSetAnswer(answer="exclude")

    def test_a_reply_cannot_record_a_replacement(self):
        psq = _psq5()
        self.assertIn("replaces", psq.ANSWERS)
        db, qid = self._world()
        ps = self._patches(db)
        for p in ps:
            p.start()
        try:
            with self.assertRaises(ValueError):
                _run(server._record_set_answer(PID, qid, "replaces", "pm", via="whatsapp",
                                               replacements=[dict(r) for r in ROY]))
        finally:
            for p in ps:
                p.stop()
        self.assertEqual(db["plan_set_questions"].docs[0]["status"], "open")
        self.assertIsNone(psq.parse_reply("Q2 replaces A-105.01"))
        self.assertEqual(psq.split_reply("Q2 replaces A-105.01")[1], [("Q2", "replaces A-105.01")],
                         "words after a code are a note to confirm, never an answer")

    def test_the_confirmation_says_the_office_records_a_replacement(self):
        psq = _psq5()
        txt = psq.confirm_text(dict(_question(GASF, 1)))
        self.assertIn("replacement", txt)
        self.assertIn("office records", txt)

    def test_an_answered_replacement_reads_back_in_words(self):
        psq = _psq5()
        q = dict(_answered_q2(), answered_by_name="Roy", answered_via="admin",
                 answered_at="2026-10-30T10:00:00")
        txt = psq.status_text(q)
        self.assertIn("A-105.01", txt)
        self.assertIn("A-100.01", txt)
        self.assertIn("replaces", txt)
        self.assertNotIn("not part of", txt)


class TheStoredReplacementReachesThePass(unittest.TestCase):

    def _db(self, answers):
        db = AsyncFakeDB()
        for fid, f in FILES5.items():
            db.project_files.docs.append(dict(f, _id=fid, project_id=PID, is_deleted=False))
        for p in _raw5():
            db.document_page_index.docs.append(dict(p, project_id=PID))
        for q in answers:
            doc = {k: v for k, v in q.items() if k != "id"}
            db["plan_set_questions"].docs.append(dict(doc, project_id=PID, company_id=CID))
        return db

    def _pass(self, db, returns=None):
        _server_has("_plan_glyph_pass")
        seen = {}

        def fake_pass(pages, open_page, schedules, door_pages=(), track="filed", sweeps=None,
                      plan_only=None, opening_schedules=(), set_answers=None, **k):
            seen[track] = {"pages": [(p["page_id"], p["sheet_number"]) for p in pages],
                           "answers": set_answers}
            return {"rows": [], "summary": {}, "opening_rows": [], "opening_health": [],
                    "areas": [], "walls": [], "set_questions": (returns or {}).get(track, [])}

        async def live(_pid):
            return list(FILES5)

        async def write(_pid, rows):
            return len(rows)

        async def company(*a, **k):
            return CID

        async def none(*a, **k):
            return None

        with patch.object(server, "db", db), patch.object(server, "_live_plan_file_ids", live), \
                patch("lib.plan_glyph_pass.run_pass", fake_pass), \
                patch.object(server, "_glyph_set_health", lambda *a, **k: []), \
                patch.object(server, "_write_glyph_records", write), \
                patch.object(server, "_write_set_health", write), \
                patch.object(server, "_write_stack_rows", write), \
                patch.object(server, "_write_area_records", write), \
                patch.object(server, "_write_wall_records", write), \
                patch.object(server, "_project_company_id", company), \
                patch.object(server, "audit_log", none), \
                patch.object(server, "_review_queue_plan_set_question", none), \
                patch("lib.plan_only.record_query", lambda pid, ids: {"project_id": "none"}):
            return _run(server._plan_glyph_pass(PID)), seen

    def test_the_pass_reads_the_replacing_pages_in_the_replaced_ones_places(self):
        db = self._db([_answered_q1(), _answered_q2()])
        summary, seen = self._pass(db)
        filed = dict(seen["filed"]["pages"])
        self.assertEqual(filed.get("gas#1"), "A-100.00")
        self.assertEqual(filed.get("gas#2"), "A-105.01")
        self.assertNotIn("ar818#6", filed)
        self.assertNotIn("ar818#7", filed)
        self.assertFalse([i for i in filed if i.startswith("a1x#")])
        self.assertIn("ar325#12", filed, "the rest of the set is read as before")
        applied = {a["code"]: a["applied"] for a in summary["set_answers"]}
        self.assertEqual(applied, {"Q1": True, "Q2": True})

    def test_the_questions_stay_answered_and_are_not_reopened(self):
        db = self._db([_answered_q1(), _answered_q2()])
        self._pass(db)
        docs = {d["_id"]: d for d in db["plan_set_questions"].docs}
        self.assertEqual(len(docs), 2, "no new question")
        self.assertEqual({d["code"]: (d["status"], d["answer"]) for d in docs.values()},
                         {"Q1": ("answered", "exclude"), "Q2": ("answered", "replaces")})

    def test_a_question_still_raised_after_its_answer_keeps_the_answer(self):
        """Had the replacement not applied, the pass raises the question again;
        the store refreshes nothing and re-opens nothing."""
        db = self._db([_answered_q2()])
        raised = {"filed": [_question(GASF, 1)]}
        raised["filed"][0]["id"] = raised["filed"][0].pop("_id")
        self._pass(db, returns=raised)
        d = db["plan_set_questions"].docs
        self.assertEqual([(x["code"], x["status"], x["answer"]) for x in d], [("Q2", "answered", "replaces")])

    def test_the_census_scope_includes_the_replacing_page(self):
        """The gate counts the rows of the pages the pass read: gas p1 is in no
        track and not current in the index, and its rows must be counted."""
        db = self._db([_answered_q2()])

        async def live(_pid):
            return list(FILES5)

        async def current(_pid):
            return []
        with patch.object(server, "db", db), patch.object(server, "_live_plan_file_ids", live), \
                patch.object(server, "_current_record_page_ids", current):
            ids = _run(server._glyph_page_ids(PID))
        self.assertIn("gas#1", ids)
        self.assertNotIn("ar818#7", ids)

    def test_a_replaces_answer_that_reaches_the_openings_unapplied_reads_as_open(self):
        """If the pass still raises the question (the replacement could not be
        applied), its pages are read as the open reading - never as include."""
        psq = _psq5()
        from lib import plan_openings as O
        refused = [(dict(GROOF, page_id="pg-gas-2", project_id=PID), "no mechanical partner")]
        qid = psq.detect(PID, "filed", refused)[0]["id"]
        seen = []

        def fake_floor(pg, run, member, why=None):
            seen.append(1)
            return {"records": {}, "legend": [], "untagged": 0, "orphans": [], "unreadable": []}
        with patch.object(O, "floor_records", fake_floor):
            out = O.run_openings([], lambda p: object(), {"F": {"tags": ["A"]}}, refused=refused,
                                 answers={qid: "replaces"})
        self.assertTrue(seen, "its page is still read at sheet scope (the open reading)")
        self.assertEqual(out["summary"]["set_questions"][0]["applied"],
                         "open (the replacement was not applied)")


if __name__ == "__main__":
    unittest.main()
