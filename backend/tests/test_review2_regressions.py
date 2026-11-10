"""SECOND REVIEW OF THE PROGRESS ENGINE: each reproduced finding, as a test.

The reviewer's scripts (r1-r9) reproduced nine defects on
feat/progress-integrated. Each class below is one finding and fails on that
base; the owner's rules they hold: no fabricated percent / date / approval /
cause; unknown is never not-done; an attributed statement is not a verified
one; no personal data in validation output; no unvalidated automation.

  1  TheReplyReader, LiveNeverReadsAnUndeliveredQuestion   (r1, r9)
  2  LevelsOutsideTheBuilding                              (r5, r6)
  3  ListsOfFloors                                         (r5)
  4  NoNameReachesTheValidationOutput                      (r4)
  5  ABookingIsNotInProgress                               (r2, r6)
  6  OneOrderForTheQuestions                               (r2)
  7  TheReportAndTheAssistantAgree
  8  TheSnapshotIsBounded                                  (r7, r8)
  9  AFrameThatCannotBeReadIsSaid
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "tests"))
sys.path.insert(0, str(_BACKEND / "scripts"))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import confirmation_queue as C  # noqa: E402
from lib import evidence as E  # noqa: E402
from lib import evidence_sources as S  # noqa: E402
from lib import inspection_reports as IR  # noqa: E402
from lib import location_binder as B  # noqa: E402
from lib import progress_report as PR  # noqa: E402
from lib import progress_report_render as R  # noqa: E402
from lib import progress_validation as PV  # noqa: E402
from lib import project_progress as PG  # noqa: E402
from lib import work_state as W  # noqa: E402

TODAY = date(2026, 11, 10)
PID = "p588"
SIX = {"building_stories": 6}


def _server():
    import server
    return server


def _six_frame(spaces=None):
    return B.frame_from(SIX, [], [], spaces or {})


# ── 1. THE REPLY READER, AND LIVE ──────────────────────────────────────────

DONT_KNOW_REPLIES = (
    # English
    "don't know", "dont know", "I don't know", "idk", "IDK", "dunno", "not sure", "nope, not sure", "no idea",
    "no clue", "not a clue", "unsure", "who knows", "can't say", "hard to say", "I'll check", "nobody told me",
    "no one told me", "not that I know", "not that I know of", "not as far as I know", "ask the foreman",
    "yes I don't know", "?",
    # Spanish
    "no sé", "no se", "no lo sé", "no lo se", "no sé si empezaron", "no se si terminaron", "ni idea",
    "no tengo idea", "no tengo ni idea", "quién sabe", "quien sabe", "no estoy seguro", "no estoy segura",
    "no sabemos", "no que yo sepa", "voy a preguntar", "pregúntale al capataz",
)


class TheReplyReader(unittest.TestCase):
    """Finding 1 (r1): "no lo sé", "no clue", "no tengo idea", "no sé si
    empezaron" were read as no / absent / not yet / started."""

    def test_dont_know_is_dont_know_for_every_question(self):
        for trigger in C.TRIGGERS:
            for reply in DONT_KNOW_REPLIES:
                with self.subTest(trigger=trigger, reply=reply):
                    got = C.parse_reply(reply, [{"trigger": trigger}])["answers"]
                    self.assertEqual([a["answer"] for a in got], ["dont_know"])

    def test_dont_know_inside_a_numbered_reply(self):
        qs = [{"trigger": C.START_PASSED}, {"trigger": C.OFF_LEVEL}, {"trigger": C.DONE_UNBACKED}]
        got = C.parse_reply("1 no lo sé, 2 no clue, 3 done", qs)["answers"]
        self.assertEqual([(a["index"], a["answer"]) for a in got], [(1, "dont_know"), (2, "dont_know"), (3, "done")])

    def test_a_yes_and_a_no_together_is_no_answer(self):
        for trigger in (C.OFF_LEVEL, C.START_PASSED, C.DONE_UNBACKED):
            for reply in ("yes, nobody was there", "no, they were there"):
                with self.subTest(trigger=trigger, reply=reply):
                    self.assertEqual(C.parse_reply(reply, [{"trigger": trigger}])["answers"], [])

    def test_plain_answers_still_read(self):
        cases = ((C.OFF_LEVEL, "no one was there", "absent"), (C.OFF_LEVEL, "nadie", "absent"),
                 (C.OFF_LEVEL, "yes they were there", "present"), (C.OFF_LEVEL, "sí", "present"),
                 (C.START_PASSED, "started", "started"), (C.START_PASSED, "todavía no", "not_yet"),
                 (C.DONE_UNBACKED, "listo", "done"), (C.DONE_UNBACKED, "no se terminó", "not_yet"),
                 (C.INSP_PASSED, "passed", "passed"))
        for trigger, reply, want in cases:
            with self.subTest(reply=reply):
                self.assertEqual([a["answer"] for a in C.parse_reply(reply, [{"trigger": trigger}])["answers"]], [want])


class LiveNeverReadsAnUndeliveredQuestion(unittest.TestCase):
    """Finding 1 (r9): a candidate was "sent" when it was only queued (held
    to 7:30), and a reply at 4:00 was read as its answer. And the roles asked
    can never be messaged first (lib/dm_roles), so live must refuse."""

    Q = ("On Mon Nov 9, a photo put duct rough on Floor 3, but that day's log has nobody on Floor 3 (it names "
         "Floor 4). Was a crew on Floor 3 that day?")

    def _db(self, status="sent", events=()):
        from async_fake_mongo import AsyncFakeDB
        db = AsyncFakeDB()
        db.users.docs.append({"_id": "u_cp", "company_id": "co", "role": "cp", "name": "Cal CP",
                              "assigned_projects": ["p1"]})
        db.confirmation_candidates.docs.append({
            "_id": "c1", "day": "2026-11-10", "project_id": "p1", "company_id": "co", "target_user_id": "u_cp",
            "trigger": C.OFF_LEVEL, "thing": "x", "node": "rough_duct", "level": "FLOOR_3", "question": self.Q,
            "options": C.OPTIONS[C.OFF_LEVEL], "position": 1, "status": status})
        db.confirmation_events.docs.extend(events)
        return db

    def _reply(self, db, text, now, messageable=True):
        server = _server()
        sent = AsyncMock(return_value=True)
        roles = (lambda: []) if messageable else C.unmessageable_roles
        with patch.object(server, "db", db), patch.object(server, "send_whatsapp_message", sent), \
                patch.object(C, "unmessageable_roles", roles), \
                patch.dict(os.environ, {C.MODE_ENV: "live", C.LIVE_ENV: "1"}):
            took = asyncio.run(server._confirmation_take_reply(
                {"user_id": "u_cp", "user": {"name": "Cal CP"}}, "c@c.us", text, now=now))
        return took, sent

    def test_live_is_refused_while_the_roles_cannot_be_messaged_first(self):
        self.assertEqual(C.unmessageable_roles(), ["superintendent", "cp"])
        self.assertEqual(C.mode({C.MODE_ENV: "live", C.LIVE_ENV: "1"}), "shadow")
        self.assertTrue("cannot be messaged first" in C.live_refused({C.LIVE_ENV: "1"}))

    def test_the_reviewers_case_is_not_taken(self):
        # 4:00 AM New York; the tick marked it sent at 3:40, the message was held to 7:30.
        now = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
        db = self._db("sent")
        took, sent = self._reply(db, "no lo sé", now, messageable=False)
        self.assertFalse(took)
        took, sent = self._reply(db, "no lo sé", now)
        self.assertFalse(took)                                      # never delivered: no "sent" event
        self.assertEqual(db.confirmation_answers.docs, [])
        sent.assert_not_called()

    def test_a_delivered_question_is_answered_and_an_undelivered_one_is_not(self):
        delivered = datetime(2026, 11, 10, 12, 30, tzinfo=timezone.utc)
        ev = {"candidate_id": "c1", "kind": "sent", "by": "u_cp", "at": delivered}
        # Before the delivery: not taken.
        took, _ = self._reply(self._db("queued", [ev]), "no", datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc))
        self.assertFalse(took)
        # A delivery yesterday is not today's question.
        old = dict(ev, at=delivered - timedelta(days=1))
        took, _ = self._reply(self._db("queued", [old]), "no", datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc))
        self.assertFalse(took)
        # After it: taken, and "no lo sé" is kept as don't know, never absent.
        db = self._db("queued", [ev])
        took, _ = self._reply(db, "no lo sé", datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc))
        self.assertTrue(took)
        self.assertEqual([(a["answer"], a["item"]["claim"]) for a in db.confirmation_answers.docs],
                         [("dont_know", "dont_know")])

    def test_the_queue_marks_sent_only_after_delivering(self):
        from async_fake_mongo import AsyncFakeDB
        server = _server()
        db = self._db("queued")
        now = datetime(2026, 11, 10, 12, 31, tzinfo=timezone.utc)
        db[server.WA_QUIET_QUEUE].docs.append({
            "_id": "q1", "status": "queued", "deliver_after": now - timedelta(minutes=1), "seq": 1, "kind": "confirmation",
            "company_id": "co", "project_id": None,
            "send": {"via": "dm", "user_id": "u_cp", "message": "Good morning", "kind": "confirmation",
                     "window": "2026-11-10", "project_id": None, "confirmation_ids": ["c1"]}})
        for ok, want in ((None, []), ("wamid.1", ["sent"])):
            db.confirmation_events.docs.clear()
            db[server.WA_QUIET_QUEUE].docs[0].update(status="queued", deliver_after=now - timedelta(minutes=1))
            with patch.object(server, "db", db), patch.object(server, "send_whatsapp_dm", AsyncMock(return_value=ok)), \
                    patch.object(server, "_send_failed_alert", AsyncMock()):
                asyncio.run(server._quiet_queue_tick(now))
            with self.subTest(delivered=ok):
                self.assertEqual([e["kind"] for e in db.confirmation_events.docs], want)
        self.assertIsInstance(AsyncFakeDB, type)

    def test_the_shadow_report_says_why_live_was_refused(self):
        import confirmation_shadow_report as SR
        rows = [{"_id": "k1", "project_id": PID, "day": "2026-11-10", "trigger": C.CONFLICT, "target_user_id": "u1",
                 "text": "Good morning", "status": "shadow", "position": 1, "live_refused": C.live_refused({C.LIVE_ENV: "1"})}]
        s = SR.summarize(rows, [])
        self.assertEqual(sum(s["live_refused"].values()), 1)
        self.assertTrue(all("cannot be messaged first" in k for k in s["live_refused"]))


# ── 2. LEVELS OUTSIDE THE BUILDING ─────────────────────────────────────────

class LevelsOutsideTheBuilding(unittest.TestCase):
    """Finding 2 (r5, r6): "3B slab" was Floor 3 done; a 9th-floor pour on a
    six-storey job made a FLOOR_9 row, done_confirmed."""

    def test_a_units_slab_is_never_floor_3_done(self):
        for frame in (None, _six_frame(), _six_frame({"3B": {"levels": []}})):
            with self.subTest(frame=bool(frame)):
                node, claim, levels = S.pour_claim("3B slab", frame)
                self.assertFalse(claim == "done" and "FLOOR_3" in levels, (node, claim, levels))
                self.assertEqual(levels, [])

    def test_every_source_is_bound_to_the_frame(self):
        frame = _six_frame()
        on = TODAY - timedelta(days=2)
        logs = [{"_id": "L9", "log_type": "concrete_operations", "status": "submitted", "date": on.isoformat(),
                 "data": {"pour_location": "9th floor slab"}},
                {"_id": "S9", "log_type": "site_superintendent_log", "status": "submitted", "date": on.isoformat(),
                 "data": {"daily_inspection": {"entries": [{"location": "9th floor", "result": "ok"}]}}}]
        inspections = [{"_id": "i9", "status": IR.ATTESTED, "result": "passed", "validated_result": "passed",
                        "gate": IR.PLUMBING_ROUGH, "levels": ["FLOOR_9"], "reporter_name": "Cal",
                        "created_at": datetime(2026, 11, 9, 15, tzinfo=timezone.utc)}]
        dob = [{"record_type": "job_status", "job_filing_number": "B00999", "job_status": "Signed-off",
                "work_type": "Plumbing", "work_on_floor": "Floor Number(s)-9-SO-1-B1", "raw_dob_id": "d9"}]
        punch = [{"_id": "x", "pid": "P9", "status": "closed", "closed_by": "u", "floor": "9", "closed_at": on.isoformat()}]
        sched = {"activities": [{"id": "A9", "name": "Drywall Floor 9", "actual_finish": on.isoformat()}]}
        acts = [{"date": on, "company": "Arkon", "work": "Drywall", "where": "9th floor", "log_id": "d1"}]
        photos = [{"photo_key": "ph/9.jpg", "kind": "photo", "date": on.isoformat(), "log_id": "d1", "where": "9th floor",
                   "description": "Gypsum board seams taped.", "work": "Drywall", "short": "p9"}]
        items, cov = S.collect(PID, start=TODAY - timedelta(days=30), end=TODAY, activities=acts, photo_index=photos,
                               log_ids={"d1"}, logbooks=logs, inspections=inspections, dob_rows=dob, punch_items=punch,
                               schedule=sched, frame=frame)
        placed = sorted({(i["source"], lv) for i in items for lv in i["levels"]})
        self.assertEqual([p for p in placed if p[1] == "FLOOR_9"], [])
        named = {i["source"] for i in items if "FLOOR_9" in (i.get("candidates") or [])}
        self.assertEqual(named, {"concrete_operations", "superintendent_log", "inspection_reports", "dob_logs",
                                 "punch_items", "schedule_file"})
        self.assertEqual(cov["frame"], "known")

    def test_the_model_never_adds_a_level_the_known_frame_excludes(self):
        node, claim, lv = S.pour_claim("9th floor slab")           # no frame given: the words read alone
        self.assertEqual(lv, ["FLOOR_9"])
        pour = E.item("confirmed", claim, source="concrete_operations", ref="L9", project_id="p", node=node, levels=lv,
                      on=TODAY)
        for frame in (None, _six_frame()):
            with self.subTest(frame=bool(frame)):
                m = PG.build([pour], today=TODAY, project=SIX, frame=frame)
                self.assertEqual([x["level"] for x in m["frame"]["levels"]], [f"FLOOR_{n}" for n in range(1, 7)])
                self.assertNotIn(("FLOOR_9", "superstructure"), m["cells"])
                self.assertEqual([(c["level"], c["node"]) for c in m["outside_frame"]], [("FLOOR_9", "superstructure")])
                self.assertEqual(m["levels_excluded"], ["FLOOR_9"])
                self.assertTrue("exclude" in PG.as_text(m), "the answer says the record names an excluded level")

    def test_an_unknown_frame_marks_levels_from_records_only(self):
        it = E.item("reported", "in_progress", source="daily_log", ref="r", project_id="p", node="drywall",
                    levels=["FLOOR_9"], on=TODAY)
        m = PG.build([it], today=TODAY, project={}, frame={"levels": [], "known": False})
        self.assertEqual([(x["level"], x["records_only"]) for x in m["frame"]["levels"]], [("FLOOR_9", True)])
        self.assertTrue(PG.RECORDS_ONLY in PG.as_text(m), "the answer says the level is from records only")
        m = PG.build([it], today=TODAY, project={"building_stories": 12}, frame=B.frame_from({"building_stories": 12}))
        self.assertEqual([x["records_only"] for x in m["frame"]["levels"] if x["level"] == "FLOOR_9"], [False])

    def test_a_record_whose_level_was_not_placed_is_not_the_buildings(self):
        dob = E.item("verified", "done", source="dob_logs", ref="B9", project_id="p", node="rough_dwv", levels=[],
                     candidates=["FLOOR_9"])
        m = PG.build([dob], today=TODAY, project=SIX)
        self.assertEqual([c["status"] for c in m["building"] if c["node"] == "rough_dwv"], [])
        self.assertEqual([(c["node"], c["status"]) for c in m["place_unknown"]], [("rough_dwv", "done_verified")])


# ── 3. LISTS OF FLOORS ─────────────────────────────────────────────────────

class ListsOfFloors(unittest.TestCase):
    """Finding 3 (r5): "2nd & 3rd floor" bound to Floor 3 alone, "floors 2, 3
    and 4" to Floor 2."""

    CASES = (("2nd & 3rd floor", [2, 3]), ("floors 2, 3 and 4", [2, 3, 4]), ("2 and 3", [2, 3]), ("fl 2/3", [2, 3]),
             ("3rd and 4th floors", [3, 4]), ("2nd and 3rd fl", [2, 3]), ("floors 2 & 3", [2, 3]),
             ("pisos 2 y 3", [2, 3]), ("2, 3", [2, 3]), ("1-4 floors", [1, 2, 3, 4]))

    def test_constrained_never_one_floor(self):
        frame = _six_frame()
        for text, floors in self.CASES:
            want = [f"FLOOR_{n}" for n in floors]
            with self.subTest(text=text):
                b = B.bind(text, frame["levels"])
                self.assertEqual((b["certainty"], b["levels"], b["candidates"]), (B.CONSTRAINED, want, want))
                self.assertEqual(W.places_in(text, frame)["levels"], want)

    def test_no_reader_picks_one_of_them(self):
        for text, floors in self.CASES[:-1]:
            with self.subTest(text=text):
                self.assertIsNone(W.level_asked(text))
                self.assertEqual(W.places_in(text)["levels"], [f"FLOOR_{n}" for n in floors])

    def test_what_is_not_a_list_stays_as_it_was(self):
        for text, want in (("2 and 3 guys", []), ("on 2/3 we poured", []), ("3rd floor", ["FLOOR_3"]),
                           ("floor 3 and 4A", ["FLOOR_3"]), ("2/3", [])):
            with self.subTest(text=text):
                self.assertEqual(W.places_in(text)["levels"], want)


# ── 4. NO NAME REACHES THE VALIDATION OUTPUT ───────────────────────────────

class NoNameReachesTheValidationOutput(unittest.TestCase):
    """Finding 4 (r4): a hearsay row printed "Joe Smith said it", and a later
    unresolved statement printed its quote ("Mike Rossi says ...")."""

    SECRETS = ("Joe Smith", "Joe", "Smith", "Mike Rossi", "Mike", "Rossi", "7185551234", "failed again", "Ana Inspector",
               "Sal Super")

    def test_redact_answer_cleans_every_person_field(self):
        g = {"who": "Cal CP", "inspector": "Ana Inspector", "quote": "passed per Joe", "hearsay_from": "Joe Smith",
             "relayed_from": "Sal Super", "later": [{"who": "Mike Rossi", "quote": "Mike Rossi says it failed again",
                                                     "status": IR.UNRESOLVED, "hearsay_from": "Joe Smith"}]}
        out = PV.redact_answer({"gates": [g], "other_inspections": [dict(g)]}, {"Cal CP": "a CP"})
        flat = json.dumps(out)
        for secret in self.SECRETS:
            with self.subTest(secret=secret):
                self.assertFalse(re.search(rf"\b{re.escape(secret)}\b", flat), secret)
        self.assertEqual(out["gates"][0]["later"][0]["who"], "a person")

    def test_the_e2e_fixture_with_the_reviewers_two_rows(self):
        import copy
        import tests.test_progress_e2e as T
        server = _server()
        db = T.site().db
        rows = db[server.INSPECTION_REPORTS].rows
        att = next(r for r in rows if r["status"] == "attested")
        hearsay = copy.deepcopy(att)
        hearsay.update(_id="rv2_hearsay", gate=IR.ELECTRICAL_ROUGH, hearsay_from="Joe Smith", reporter_name="Cal CP",
                       created_at=att["created_at"] + timedelta(minutes=1))
        later = copy.deepcopy(att)
        later.update(_id="rv2_later", status=IR.UNRESOLVED, result=None, validated_result=None, reporter_name="Cal CP",
                     quote="Mike Rossi says plumbing failed again, his cell 7185551234",
                     created_at=att["created_at"] + timedelta(hours=2))
        rows += [hearsay, later]
        try:
            code, out, cov, ro = T.validation_output(db)
        finally:
            for r in (hearsay, later):
                rows.remove(r)
        self.assertEqual((code, ro.attempts), (0, []))
        # The two rows ARE read: their lines are there, by role.
        self.assertTrue("hearsay: a CP reports that [withheld] said it" in out, "the hearsay line, by role")
        self.assertTrue("a later statement is unresolved: (a CP)" in out, "the later line, by role, no words")
        for secret in self.SECRETS[:8]:
            with self.subTest(secret=secret):
                self.assertFalse(re.search(rf"\b{re.escape(secret)}\b", out + cov, re.I), secret)


# ── 5. A BOOKING IS NOT IN PROGRESS ────────────────────────────────────────

def _it(kind, claim, on=TODAY, said=None, ref="x", levels=("FLOOR_3",), node=IR.PLUMBING_ROUGH, source="inspection_reports"):
    return E.item(kind, claim, source=source, ref=ref, project_id="p", node=node, levels=list(levels), on=on, by="Joe",
                  said_at=said)


class ABookingIsNotInProgress(unittest.TestCase):
    """Finding 5 (r2, r6): status() said "reported" (drawn "Reported: in
    progress") for a booked inspection, a "not yet", a "don't know"."""

    def test_status_says_what_the_items_say(self):
        cases = ((("attested", "scheduled"),), "scheduled_attested"), \
                ((("reported", "scheduled"),), "scheduled_reported"), \
                ((("attested", "not_yet"),), "not_yet_attested"), \
                ((("attested", "blocked"),), "blocked_attested"), \
                ((("attested", "dont_know"),), "unknown"), \
                ((("attested", "absent"),), "unknown"), \
                ((("attested", "in_progress"),), "in_progress_attested"), \
                ((("confirmed", "in_progress"),), "in_progress_confirmed"), \
                ((("observed", "in_progress"),), "in_progress_observed"), \
                ((("reported", "in_progress"),), "reported"), \
                ((("reported", "in_progress"), ("attested", "scheduled")), "reported"), \
                ((("attested", "done"), ("attested", "scheduled")), "done_attested")
        for pairs, want in cases:
            with self.subTest(pairs=pairs):
                self.assertEqual(E.status([_it(k, c, ref=f"r{n}") for n, (k, c) in enumerate(pairs)]), want)

    def test_reported_only_when_a_reported_item_exists(self):
        for kind in E.KINDS:
            for claim in E.CLAIMS:
                if kind in E.NON_FACTS:          # an estimate or an inference is not a fact: below
                    continue
                st = E.status([_it(kind, claim)])
                with self.subTest(kind=kind, claim=claim):
                    self.assertEqual(st == "reported", kind == "reported" and claim in E.WORK_CLAIMS)

    def test_a_valid_inference_never_says_reported_or_done(self):
        signals = [{"source": "logbooks", "ref": "L1", "kind": "reported", "by": "CP"},
                   {"source": "photo_index", "ref": "P1", "kind": "observed", "by": "camera"}]
        for claim in E.INFERRED_CLAIMS:
            inf = E.item("inferred", claim, source="lib/construction_inference", ref="i", project_id="p",
                         node=IR.PLUMBING_ROUGH, levels=["FLOOR_3"], on=TODAY, basis="b", disproof="d",
                         confidence="medium", confidence_rule="r", signals=signals)
            with self.subTest(claim=claim):
                self.assertEqual(E.status([inf]), "unknown")
                self.assertEqual(E.status([inf, _it("attested", "scheduled")]), "scheduled_attested")

    def test_the_report_draws_a_booking_as_booked(self):
        booked = _it("attested", "scheduled", on=TODAY + timedelta(days=7))
        c = PG.cell([booked], "FLOOR_3", IR.PLUMBING_ROUGH, TODAY)
        self.assertEqual((c["status"], R.mark_of(c["status"])), ("scheduled_attested", "booked"))
        self.assertEqual(dict(R.MARKS)["booked"], "Booked (not in progress)")
        self.assertTrue("Booked (not in progress)" in R.floor_legend(), "the legend names the booked mark")
        self.assertTrue("booked is not in progress" in PG.cell_words(c, "Plumbing rough"), PG.cell_words(c, "x"))
        for st in ("not_yet_attested", "blocked_attested"):
            self.assertEqual(R.mark_of(st), "not_yet")
        self.assertIsNone(R.mark_of("unknown"))
        dk = PG.cell([_it("attested", "dont_know")], "FLOOR_3", IR.PLUMBING_ROUGH, TODAY)
        self.assertEqual((dk["status"], dk["bucket"]), ("unknown", "unknown"))


# ── 6. ONE ORDER FOR THE QUESTIONS ─────────────────────────────────────────

class OneOrderForTheQuestions(unittest.TestCase):
    """Finding 6 (r2): an undated "passed" said after a booking, or after a
    failure, was invisible to the questions (they read only dated items)."""

    FRAME = {"project_id": "p", "today": TODAY, "logs_from": date(2026, 10, 7), "logged_levels": {}, "schedule": []}

    def test_an_undated_pass_said_after_the_booking_answers_it(self):
        items = [_it("attested", "scheduled", on=date(2026, 11, 4), ref="b"),
                 _it("attested", "done", on=None, said=datetime(2026, 11, 6, 15), ref="p")]
        self.assertEqual([c["trigger"] for c in C.candidates(items, self.FRAME)], [])
        self.assertEqual(E.status(items), "done_attested")

    def test_an_undated_repass_said_after_the_failure_settles_it(self):
        items = [_it("attested", "done", on=date(2026, 11, 2), ref="p1"),
                 _it("attested", "failed", on=date(2026, 11, 4), ref="f"),
                 _it("attested", "done", on=None, said=datetime(2026, 11, 7, 9), ref="p2")]
        self.assertEqual([c["trigger"] for c in C.candidates(items, self.FRAME)], [])
        self.assertEqual(E.status(items), "done_attested")

    def test_a_failure_said_after_an_undated_pass_is_still_asked(self):
        items = [_it("attested", "done", on=None, said=datetime(2026, 11, 2, 9), ref="p1"),
                 _it("attested", "failed", on=date(2026, 11, 4), ref="f")]
        got = [c for c in C.candidates(items, self.FRAME) if c["trigger"] == C.CONFLICT]
        self.assertEqual(len(got), 1)
        self.assertTrue("date not stated" in got[0]["question"], got[0]["question"])
        # And a booking with nothing after it is still asked.
        self.assertEqual([c["trigger"] for c in C.candidates([_it("attested", "scheduled", on=date(2026, 11, 4))],
                                                             self.FRAME)], [C.INSP_PASSED])


# ── 7. THE REPORT AND THE ASSISTANT AGREE ──────────────────────────────────

class TheReportAndTheAssistantAgree(unittest.TestCase):
    """Finding 7: the report's forecast was built without the model's
    unreadable sources and on a 365-day window, the assistant's on 90."""

    def test_one_window_daily_activity_windowed_standing_records_whole(self):
        server = _server()
        old = TODAY - timedelta(days=200)
        items = [_it("reported", "in_progress", on=old, ref="log", source="daily_log", node="drywall"),
                 _it("confirmed", "done", on=old, ref="pour", source="concrete_operations", node="superstructure"),
                 _it("reported", "in_progress", on=TODAY, ref="new", source="daily_log", node="drywall")]
        _rows, kept, start = server._forecast_window(items, [], TODAY)
        self.assertEqual(sorted(i["ref"] for i in kept), ["new", "pour"])
        self.assertEqual(start, TODAY - timedelta(days=server.WORK_STATE_DAYS - 1))

    def test_the_report_forecast_carries_the_unreadable_sources_and_the_window(self):
        server = _server()
        old = TODAY - timedelta(days=200)
        items = [_it("reported", "in_progress", on=old, ref="log", source="daily_log", node="drywall")]
        sched = {"activities": [{"id": "A1", "name": "Drywall Floor 3", "baseline_finish": "2026-12-01"}]}
        model = PG.build(items, today=TODAY, project=SIX, unreadable=["photo_index"])

        async def fake_progress(project, company_id, *, job="", today=None, keep=None):
            keep.update(items=items, start=TODAY - timedelta(days=364), sources={"schedule": sched, "logbooks": []})
            return model
        seen = {}
        real = server.schedule_forecast.forecast

        def spy(schedule, its, rows, **kw):
            seen.update(items=list(its), unreadable=list(kw.get("unreadable") or ()))
            return real(schedule, its, rows, **kw)
        rep = {"end": TODAY, "start": TODAY - timedelta(days=30), "job": "588"}
        with patch.object(server, "_project_progress", fake_progress), \
                patch.object(server.schedule_forecast, "forecast", spy):
            asyncio.run(server._report_progress(rep, {"_id": PID}, "co", datetime(2026, 11, 10, 20, tzinfo=timezone.utc)))
        self.assertEqual((seen["items"], seen["unreadable"]), ([], ["photo_index"]))
        self.assertTrue("photo index" in rep["forecast"]["unreadable_line"], rep["forecast"])

    def test_the_status_page_and_the_forecast_section_say_what_was_not_read(self):
        model = PG.build([_it("reported", "in_progress", source="daily_log", node="drywall")], today=TODAY,
                         project=SIX, unreadable=["inspection_reports", S.FRAME_UNREADABLE])
        rep = {"start": TODAY - timedelta(days=60), "end": TODAY, "subs": [], "progress_model": model,
               "forecast": {"groups": [{"key": "verified", "label": "v", "lines": ["- x"]}],
                            "unreadable_line": "Could not be read just now: photo index."}}
        page = R._status_by_floor(rep)
        self.assertTrue("Could not be read just now: inspection reports" in page, "the status page names it")
        self.assertTrue("level frame" in page, "the frame is named")
        self.assertTrue("Could not be read just now: photo index." in R._forecast_section(rep), "the forecast says it")


# ── 8. THE SNAPSHOT IS BOUNDED ─────────────────────────────────────────────

class TheSnapshotIsBounded(unittest.TestCase):
    """Finding 8 (r7, r8): a year of a 20-storey job's photos made a 95 MB
    snapshot (MongoDB refuses 16 MB); conflict text kept people's names."""

    def test_a_synthetic_twenty_storey_year(self):
        levels = [f"FLOOR_{n}" for n in range(2, 21)]
        items = []
        for d in range(0, 365, 2):
            for k in range(6):
                items.append(E.item("observed", "in_progress", source="photo_index",
                                    ref=f"v1:companies/co_abcdef123456/projects/proj_0123456789/logs/{d}/{k}_photo.jpg",
                                    project_id="p", node="drywall", levels=levels, on=TODAY - timedelta(days=d),
                                    shared=True))
        m = PG.build(items, today=TODAY, project={"building_stories": 20})
        snap = PR.progress_snapshot(m)
        size = len(json.dumps(snap, default=str))
        self.assertLess(size, PR.SNAPSHOT_MAX_BYTES)
        for key, ev in snap["evidence"].items():
            self.assertLessEqual(len(ev["refs"]), PR.SNAPSHOT_REFS_PER_CELL, key)
        self.assertEqual(snap["evidence"]["FLOOR_5|drywall"]["ref_count"], len(items))
        self.assertLessEqual(len(snap["conflicts"]), PR.SNAPSHOT_MAX_CONFLICTS)
        self.assertEqual(snap["conflict_count"], len(m["conflicts"]))

    def test_no_name_in_the_stored_conflicts(self):
        items = [_it("attested", "done", on=date(2026, 11, 2), ref="p"),
                 E.item("attested", "failed", source="inspection_reports", ref="f", project_id="p",
                        node=IR.PLUMBING_ROUGH, levels=["FLOOR_3"], on=date(2026, 11, 4), by="Mike Rossi")]
        m = PG.build(items, today=TODAY, project=SIX)
        self.assertEqual([c["type"] for c in m["conflicts"]], ["done_then_failed"])
        stored = json.dumps(PR.progress_snapshot(m)["conflicts"])
        for name in ("Joe", "Mike Rossi"):
            self.assertFalse(re.search(rf"\b{name}\b", stored), name)
        self.assertTrue("a named reporter" in stored, stored)


# ── 9. A FRAME THAT CANNOT BE READ IS SAID ─────────────────────────────────

class AFrameThatCannotBeReadIsSaid(unittest.TestCase):
    """Finding 9: a failed _project_place_frame read was an empty frame, so
    places fell back to the words alone ("floor 9" placed on a 6-storey job)
    and nothing said the frame was not read."""

    def test_the_server_records_a_failed_read(self):
        server = _server()

        class Broken:
            def __getattr__(self, name):
                raise RuntimeError("down")

            def __getitem__(self, name):
                raise RuntimeError("down")
        with patch.object(server, "db", Broken()):
            f = asyncio.run(server._project_place_frame("p"))
        self.assertTrue(f.get("unreadable"))
        self.assertEqual((f["levels"], f["known"]), ([], False))

    def test_places_are_constrained_never_guessed(self):
        gone = {"levels": [], "spaces": {}, "known": False, "excluded": {}, "unreadable": True}
        self.assertEqual(W.places_in("floor 9", gone)["levels"], [])
        self.assertEqual(W.places_in("3rd floor", gone)["levels"], [])
        self.assertEqual(S.place_text("9th floor slab", gone)[:2], ([], ["FLOOR_9"]))
        acts = [{"date": TODAY, "company": "Arkon", "work": "Drywall", "where": "floor 9", "log_id": "d1"}]
        items, cov = S.collect(PID, start=TODAY - timedelta(days=7), end=TODAY, activities=acts, frame=gone)
        self.assertEqual([i["levels"] for i in items], [[]])
        self.assertEqual((cov["frame"], cov["unreadable"]), ("frame unreadable", [S.FRAME_UNREADABLE]))

    def test_every_answer_says_so(self):
        m = PG.build([], today=TODAY, project=SIX, unreadable=[S.FRAME_UNREADABLE])
        self.assertTrue("level frame" in PG.as_text(m), PG.as_text(m))

    def test_the_loader_names_it_in_coverage(self):
        server = _server()
        gone = {"levels": [], "spaces": {}, "basis": {}, "known": False, "excluded": {}, "unreadable": True}
        src = {"logbooks": [], "dob_rows": [], "checkins": [], "schedule": None}
        from async_fake_mongo import AsyncFakeDB
        with patch.object(server, "db", AsyncFakeDB()), \
                patch.object(server, "_report_rows", AsyncMock(return_value=src)), \
                patch.object(server, "_photo_place_context", AsyncMock(return_value=({}, {}))), \
                patch.object(server, "_project_place_frame", AsyncMock(return_value=gone)):
            keep = {}
            _items, cov = asyncio.run(server._progress_evidence({"_id": PID}, "co", TODAY - timedelta(days=7), TODAY,
                                                                keep=keep))
        self.assertEqual(cov["unreadable"], [S.FRAME_UNREADABLE])
        self.assertTrue(keep["frame"]["unreadable"])


if __name__ == "__main__":
    unittest.main()
