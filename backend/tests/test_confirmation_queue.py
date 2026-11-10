"""TARGETED CONFIRMATIONS: only the six triggers, never what a source answers,
the caps, quiet days, opt-in, assigned jobs only, closed answers (English and
Spanish), "don't know" kept, and NOTHING SENT IN SHADOW.

The fixture is one job on Tue Nov 10 2026 holding exactly one case of each
trigger, so every assertion names which case it is about."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "tests"))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import confirmation_queue as C  # noqa: E402
from lib import evidence as E  # noqa: E402
from lib import inspection_reports as IR  # noqa: E402

TODAY = date(2026, 11, 10)          # a Tuesday
FRIDAY = date(2026, 11, 13)
SATURDAY = date(2026, 11, 14)
PID = "p588"
F = "FLOOR_"


def _it(kind, claim, node, level, on, ref, **kw):
    return E.item(kind, claim, source=kw.pop("source", "logbooks"), ref=ref, project_id=PID, node=node,
                  levels=[level] if isinstance(level, str) else level, on=on, **kw)


def fixture_items():
    return [
        # gate_unknown: drywall on 3 after DWV rough on 3, nothing for the plumbing rough inspection.
        _it("reported", "in_progress", "rough_dwv", F + "3", date(2026, 11, 2), "L1", quote="DWV rough-in"),
        _it("reported", "in_progress", "drywall", F + "3", date(2026, 11, 6), "L2", quote="Drywall hanging"),
        # conflict: Jose said passed (Nov 3), Mike said failed (Nov 5), plumbing rough on 2.
        _it("attested", "done", IR.PLUMBING_ROUGH, F + "2", date(2026, 11, 3), "R1", source="inspection_reports",
            by="Jose", quote="plumbing rough passed on 2"),
        _it("attested", "failed", IR.PLUMBING_ROUGH, F + "2", date(2026, 11, 5), "R2", source="inspection_reports",
            by="Mike", quote="plumbing rough failed on 2"),
        # inspection_date_passed: electrical rough on 4 booked for Nov 7.
        _it("attested", "scheduled", IR.ELECTRICAL_ROUGH, F + "4", date(2026, 11, 7), "R3",
            source="inspection_reports", by="Jose", quote="electrical rough booked for Saturday on 4"),
        # done_unbacked: the Nov 7 log says framing complete on 6.
        _it("reported", "done", "framing", F + "6", date(2026, 11, 7), "L3", quote="Framing complete"),
        # work_off_logged_level: a photo puts framing on 7 on Nov 6; that day's log names 2 and 3.
        _it("observed", "in_progress", "framing", F + "7", date(2026, 11, 6), "ph7", source="photo_index",
            quote="metal stud framing"),
    ]


def fixture_frame(today=TODAY):
    return {"project_id": PID, "today": today, "logs_from": date(2026, 10, 7),
            "logged_levels": {date(2026, 11, 6): {F + "2", F + "3"}, date(2026, 11, 2): {F + "3"},
                              date(2026, 11, 7): {F + "6"}},
            # planned_start_passed: drywall on 5 planned to start Nov 4.
            "schedule": [{"id": "A100", "name": "Drywall Floor 5", "nodes": ["drywall"], "levels": [F + "5"],
                          "planned_start": date(2026, 11, 4), "actual_start": None}]}


def by_trigger(cands):
    out = {}
    for c in cands:
        out.setdefault(c["trigger"], []).append(c)
    return out


def person(uid="u1", role="superintendent", opted_in=True, projects=(PID,), name="Ray Santos"):
    return {"user_id": uid, "name": name, "role": role, "opted_in": opted_in, "assigned_projects": list(projects)}


class EachTriggerFiresOnItsCase(unittest.TestCase):
    def setUp(self):
        self.c = by_trigger(C.candidates(fixture_items(), fixture_frame()))

    def test_one_of_each_trigger_and_two_gates(self):
        want = {t: 1 for t in C.TRIGGERS}
        want[C.GATE_UNKNOWN] = 2
        self.assertEqual({k: len(v) for k, v in self.c.items()}, want)

    def test_gate_unknown_names_only_the_gates_dwv_rough_comes_before(self):
        """DWV rough precedes the plumbing rough AND the firestopping gates;
        nothing on 3 precedes electrical, sprinkler or energy: not asked."""
        self.assertEqual({(g["node"], g["level"]) for g in self.c[C.GATE_UNKNOWN]},
                         {(IR.PLUMBING_ROUGH, F + "3"), (IR.FIRESTOPPING, F + "3")})

    def test_conflict_cites_both_statements(self):
        refs = {e["ref"] for e in self.c[C.CONFLICT][0]["evidence"]}
        self.assertEqual(refs, {"R1", "R2"})

    def test_off_level_is_floor_7_on_nov_6(self):
        self.assertEqual(self.c[C.OFF_LEVEL][0]["thing"], f"{C.OFF_LEVEL}|{F}7|2026-11-06")

    def test_every_question_has_dont_know_and_a_falsifiable_option(self):
        for t, cs in self.c.items():
            keys = [o["key"] for o in cs[0]["options"]]
            self.assertIn("dont_know", keys, t)
            self.assertTrue(any(o["falsifiable"] for o in cs[0]["options"]), t)

    def test_best_first(self):
        allc = C.candidates(fixture_items(), fixture_frame())
        self.assertEqual([c["score"] for c in allc], sorted((c["score"] for c in allc), reverse=True))
        # Same age, same evidence: a disagreement outranks a log's word.
        self.assertGreater(C._score(C.CONFLICT, TODAY, TODAY, 1), C._score(C.DONE_UNBACKED, TODAY, TODAY, 1))
        # Older is worth less.
        self.assertGreater(C._score(C.CONFLICT, TODAY, TODAY, 1), C._score(C.CONFLICT, TODAY - timedelta(days=7), TODAY, 1))


class NoQuestionWhenASourceAnswers(unittest.TestCase):
    def _fire(self, extra, frame=None):
        return by_trigger(C.candidates(fixture_items() + extra, frame or fixture_frame()))

    def test_gate_report_answers_gate_unknown(self):
        got = self._fire([_it("attested", "done", IR.PLUMBING_ROUGH, F + "3", date(2026, 11, 5), "R9")])
        self.assertEqual([g["node"] for g in got[C.GATE_UNKNOWN]], [IR.FIRESTOPPING])

    def test_a_reinspection_answers_the_conflict(self):
        got = self._fire([_it("attested", "done", IR.PLUMBING_ROUGH, F + "2", date(2026, 11, 8), "R8")])
        self.assertNotIn(C.CONFLICT, got)

    def test_an_outcome_answers_the_booking(self):
        got = self._fire([_it("attested", "failed", IR.ELECTRICAL_ROUGH, F + "4", date(2026, 11, 7), "R7")])
        self.assertNotIn(C.INSP_PASSED, got)

    def test_a_photo_answers_done_unbacked(self):
        got = self._fire([_it("observed", "in_progress", "framing", F + "6", date(2026, 11, 8), "ph6")])
        self.assertNotIn(C.DONE_UNBACKED, got)

    def test_any_log_answers_planned_start(self):
        got = self._fire([_it("reported", "in_progress", "drywall", F + "5", date(2026, 11, 9), "L9")])
        self.assertNotIn(C.START_PASSED, got)

    def test_a_log_naming_the_level_answers_off_level(self):
        frame = fixture_frame()
        frame["logged_levels"][date(2026, 11, 6)].add(F + "7")
        self.assertNotIn(C.OFF_LEVEL, self._fire([], frame))

    def test_an_actual_start_in_the_file_answers_it(self):
        frame = fixture_frame()
        frame["schedule"][0]["actual_start"] = "2026-11-05"
        self.assertNotIn(C.START_PASSED, self._fire([], frame))

    def test_dont_know_answers_nothing(self):
        got = self._fire([_it("attested", "dont_know", IR.PLUMBING_ROUGH, F + "3", TODAY - timedelta(days=1), "A1",
                              source=C.ANSWERS)])
        self.assertIn(IR.PLUMBING_ROUGH, [g["node"] for g in got[C.GATE_UNKNOWN]])

    def test_not_yet_answers_only_while_fresh(self):
        fresh = _it("attested", "not_yet", "drywall", F + "5", TODAY - timedelta(days=2), "A2", source=C.ANSWERS)
        stale = _it("attested", "not_yet", "drywall", F + "5", TODAY - timedelta(days=9), "A3", source=C.ANSWERS)
        self.assertNotIn(C.START_PASSED, self._fire([fresh]))
        self.assertIn(C.START_PASSED, self._fire([stale]))

    def test_a_planned_start_in_the_grace_days_is_not_asked(self):
        frame = fixture_frame(today=date(2026, 11, 5))
        self.assertNotIn(C.START_PASSED, self._fire([], frame))

    def test_gate_with_no_work_before_it_on_the_level_is_not_asked(self):
        items = [i for i in fixture_items() if i["ref"] != "L1"]
        self.assertNotIn(C.GATE_UNKNOWN, by_trigger(C.candidates(items, fixture_frame())))

    def test_shared_log_row_raises_no_gate_question(self):
        items = [i for i in fixture_items() if i["ref"] != "L2"]
        items.append(_it("reported", "in_progress", "drywall", [F + "3", F + "4"], date(2026, 11, 6), "L2s",
                         shared=True))
        self.assertNotIn(C.GATE_UNKNOWN, by_trigger(C.candidates(items, fixture_frame())))


class WhoAndHowOften(unittest.TestCase):
    def setUp(self):
        self.cands = C.candidates(fixture_items(), fixture_frame())

    def test_at_most_three_a_person_and_one_message(self):
        p = C.plan(self.cands, [person()], day=TODAY)
        self.assertEqual(len(p["messages"]), 1)
        self.assertEqual(len(p["messages"][0]["items"]), C.MAX_PER_PERSON)
        self.assertEqual(sum(1 for s in p["skipped"] if s["why"] == "daily_cap"), len(self.cands) - 3)

    def test_overflow_goes_to_the_next_eligible_person(self):
        p = C.plan(self.cands, [person(), person("u2", role="cp")], day=TODAY)
        self.assertEqual(sorted(len(m["items"]) for m in p["messages"]), [3, 3])
        self.assertEqual([m["user_id"] for m in p["messages"]][0], "u1")   # the superintendent first

    def test_not_opted_in_is_never_asked(self):
        p = C.plan(self.cands, [person(opted_in=False)], day=TODAY)
        self.assertEqual(p["messages"], [])
        self.assertTrue(all(s["why"] == "nobody_opted_in_and_assigned" for s in p["skipped"]))

    def test_only_their_assigned_jobs(self):
        p = C.plan(self.cands, [person(projects=("another_job",))], day=TODAY)
        self.assertEqual(p["messages"], [])

    def test_a_pm_or_admin_is_not_a_target(self):
        self.assertEqual(C.plan(self.cands, [person(role="pm"), person("u3", role="admin")], day=TODAY)["messages"], [])

    def test_never_twice_within_seven_days(self):
        first = C.plan(self.cands, [person()], day=TODAY)
        history = [{"thing": c["thing"], "project_id": PID, "day": TODAY.isoformat(), "target_user_id": "u1",
                    "status": "shadow"} for c in first["messages"][0]["items"]]
        again = C.plan(self.cands, [person()], day=TODAY + timedelta(days=1), history=history)
        asked = {c["thing"] for c in first["messages"][0]["items"]}
        self.assertFalse(asked & {c["thing"] for m in again["messages"] for c in m["items"]})
        later = C.plan(self.cands, [person()], day=TODAY + timedelta(days=7), history=history)
        self.assertTrue(asked & {c["thing"] for m in later["messages"] for c in m["items"]})

    def test_one_message_a_day_even_on_a_rerun(self):
        first = C.plan(self.cands, [person()], day=TODAY)
        history = [{"thing": c["thing"], "project_id": PID, "day": TODAY.isoformat(), "target_user_id": "u1",
                    "status": "shadow"} for c in first["messages"][0]["items"]]
        self.assertEqual(C.plan(self.cands, [person()], day=TODAY, history=history)["messages"], [])

    def test_skip_when_they_already_wrote_about_it_today(self):
        said = {"u1": ["Mike says the plumbing rough failed on the 2nd floor, reinspection Thursday"]}
        p = C.plan(self.cands, [person()], day=TODAY, said_today=said)
        asked = {c["trigger"] for m in p["messages"] for c in m["items"]}
        self.assertNotIn(C.CONFLICT, asked)
        self.assertIn({"thing": [c for c in self.cands if c["trigger"] == C.CONFLICT][0]["thing"],
                       "project_id": PID, "why": "already_wrote_about_it_today"}, p["skipped"])

    def test_writing_about_other_work_does_not_skip(self):
        p = C.plan(self.cands, [person()], day=TODAY, said_today={"u1": ["concrete pour on the roof went fine"]})
        self.assertIn(C.CONFLICT, {c["trigger"] for m in p["messages"] for c in m["items"]})

    def test_never_on_shabbos_for_a_job_that_keeps_it(self):
        p = C.plan(self.cands, [person()], day=SATURDAY, keeps_shabbos={PID: True})
        self.assertTrue(p["quiet_day"])
        self.assertEqual(p["messages"], [])
        self.assertTrue(all(s["why"] == "shabbos_yom_tov" for s in p["skipped"]))

    def test_shabbos_does_not_silence_a_job_that_does_not_keep_it(self):
        self.assertTrue(C.plan(self.cands, [person()], day=SATURDAY, keeps_shabbos={PID: False})["messages"])

    def test_a_weekday_is_not_quiet(self):
        self.assertFalse(C.plan(self.cands, [person()], day=FRIDAY, keeps_shabbos={PID: True})["quiet_day"])


class TheAnswers(unittest.TestCase):
    Q = [{"trigger": C.DONE_UNBACKED}, {"trigger": C.GATE_UNKNOWN}, {"trigger": C.OFF_LEVEL}]

    def _ans(self, text, qs=None):
        return {a["index"]: a["answer"] for a in C.parse_reply(text, qs or self.Q)["answers"]}

    def test_numbered_english(self):
        self.assertEqual(self._ans("1 done, 2 passed, 3 no"), {1: "done", 2: "passed", 3: "absent"})

    def test_spanish(self):
        self.assertEqual(self._ans("1 todavía no, 2 pasó, 3 sí"), {1: "not_yet", 2: "passed", 3: "present"})
        self.assertEqual(self._ans("uno listo, dos falló, tres nadie"), {1: "done", 2: "failed", 3: "absent"})
        self.assertEqual(self._ans("1 bloqueado esperando al electricista"), {1: "blocked"})

    def test_dont_know_is_kept_never_no(self):
        for said in ("1 don't know", "1 no sé", "1 not sure", "1 idk", "1 ni idea", "1 no idea"):
            self.assertEqual(self._ans(said), {1: "dont_know"}, said)

    def test_no_se_with_a_verb_after_is_not_dont_know(self):
        self.assertEqual(self._ans("no se terminó", [{"trigger": C.DONE_UNBACKED}]), {1: "not_yet"})

    def test_negated_done_is_not_done(self):
        self.assertEqual(self._ans("1 not done"), {1: "not_yet"})
        self.assertEqual(self._ans("1 it isn't done"), {1: "not_yet"})

    def test_blocked_keeps_why_and_a_number_inside_it(self):
        got = C.parse_reply("1 blocked: waiting on 2 guys, 2 failed", self.Q)["answers"]
        self.assertEqual(got[0]["reason"], "waiting on 2 guys")
        self.assertEqual((got[1]["index"], got[1]["answer"]), (2, "failed"))

    def test_a_percent_is_kept_as_stated(self):
        got = C.parse_reply("1 60%", self.Q)["answers"][0]
        self.assertEqual((got["answer"], got["percent"]), ("percent", 60.0))

    def test_two_answers_for_one_question_are_not_read(self):
        self.assertEqual(self._ans("1 done not yet"), {})

    def test_a_yes_to_an_inspection_question_is_not_a_result(self):
        self.assertEqual(self._ans("yes", [{"trigger": C.GATE_UNKNOWN}]), {})

    def test_bare_answer_to_one_question(self):
        self.assertEqual(self._ans("listo", [{"trigger": C.START_PASSED}]), {1: "done"})
        self.assertEqual(self._ans("no one was there", [{"trigger": C.OFF_LEVEL}]), {1: "absent"})

    def test_voice_transcript_spoken_numbers(self):
        self.assertEqual(self._ans("number one done, number two not yet, three yes"),
                         {1: "done", 2: "not_yet", 3: "present"})

    def test_unread_are_listed(self):
        self.assertEqual(C.parse_reply("1 done", self.Q)["unread"], [2, 3])


class AnswersBecomeAttestedItems(unittest.TestCase):
    def setUp(self):
        self.c = by_trigger(C.candidates(fixture_items(), fixture_frame()))

    def test_item_carries_person_words_and_question(self):
        cand = self.c[C.DONE_UNBACKED][0]
        a = C.parse_reply("not yet", [cand])["answers"][0]
        it = C.answer_item(cand, a, answer_id="a1", person="Ray Santos", on=TODAY)
        self.assertEqual((it["kind"], it["claim"], it["by"], it["quote"]), ("attested", "not_yet", "Ray Santos", "not yet"))
        self.assertIn(cand["question"], it["note"])
        self.assertEqual(it["levels"], [F + "6"])

    def test_dont_know_is_stored_as_dont_know(self):
        cand = self.c[C.START_PASSED][0]
        a = C.parse_reply("no sé", [cand])["answers"][0]
        self.assertEqual(C.answer_item(cand, a, answer_id="a2", person="R", on=TODAY)["claim"], "dont_know")

    def test_inspection_answer_goes_through_validation(self):
        cand = self.c[C.GATE_UNKNOWN][0]
        a = C.parse_reply("pasó", [cand])["answers"][0]
        check = C.inspection_check(a)
        self.assertTrue(check["agree"])
        self.assertEqual(C.answer_item(cand, a, answer_id="a3", person="R", on=TODAY, check=check)["claim"], "done")

    def test_an_unresolved_inspection_answer_stores_no_result(self):
        cand = self.c[C.GATE_UNKNOWN][0]
        a = {"answer": "passed", "words": "passed but failed the second part"}
        check = C.inspection_check(a)
        self.assertFalse(check["agree"])
        self.assertIsNone(C.answer_item(cand, a, answer_id="a4", person="R", on=TODAY, check=check))

    def test_an_answer_makes_the_question_go_away(self):
        cand = self.c[C.START_PASSED][0]
        a = C.parse_reply("started", [cand])["answers"][0]
        it = C.answer_item(cand, a, answer_id="a5", person="R", on=TODAY)
        again = by_trigger(C.candidates(fixture_items() + [it], fixture_frame()))
        self.assertNotIn(C.START_PASSED, again)


class TheMode(unittest.TestCase):
    def test_default_off(self):
        self.assertEqual(C.mode({}), "off")
        self.assertEqual(C.mode({C.MODE_ENV: "bogus"}), "off")

    def test_live_is_refused_without_the_allow_variable(self):
        self.assertEqual(C.mode({C.MODE_ENV: "live"}), "shadow")
        self.assertEqual(C.mode({C.MODE_ENV: "live", C.LIVE_ENV: "true"}), "shadow")
        # Review 2: the roles asked (superintendent, CP) are never messaged
        # first (lib/dm_roles), so even allowed, live is refused and says why.
        self.assertEqual(C.mode({C.MODE_ENV: "live", C.LIVE_ENV: "1"}), "shadow")
        self.assertIn("cannot be messaged first", C.live_refused({C.LIVE_ENV: "1"}))
        # Were the rule ever ruled otherwise, the allow variable alone decides.
        with patch.object(C, "unmessageable_roles", lambda: []):
            self.assertEqual(C.mode({C.MODE_ENV: "live", C.LIVE_ENV: "1"}), "live")

    def test_the_allow_variable_is_set_nowhere_in_the_repo(self):
        root = _BACKEND.parent
        hits = []
        for p in list(root.glob("*.toml")) + list(root.glob("*.yml")) + list(root.glob("*.json")) \
                + list(root.glob("Procfile")) + list(root.glob("Dockerfile")) + list((root / ".github").rglob("*.yml")):
            if C.LIVE_ENV in p.read_text(encoding="utf-8", errors="ignore"):
                hits.append(str(p))
        self.assertEqual(hits, [])


class MessageWords(unittest.TestCase):
    def test_numbered_with_closed_answers(self):
        cands = C.candidates(fixture_items(), fixture_frame())[:3]
        text = C.message_text("Ray Santos", cands, {PID: "588 Boyland"})
        self.assertTrue(text.startswith("Good morning Ray: 3 quick checks"))
        self.assertIn("1. [588 Boyland] ", text)
        self.assertIn("(passed / failed / don't know)", text)


# ── THE SERVER: SHADOW SENDS NOTHING ───────────────────────────────────────

def _server():
    import server
    return server


class ShadowSendsNothing(unittest.TestCase):
    def _run_tick(self, mode, env_extra=None, messageable=False):
        from async_fake_mongo import AsyncFakeDB
        server = _server()
        if messageable:
            # A hypothetical ruling that lets the bot message these roles first.
            with patch.object(C, "unmessageable_roles", lambda: []):
                return self._run_tick(mode, env_extra)
        db = AsyncFakeDB()
        db.projects.docs.append({"_id": PID, "company_id": "c1", "name": "588 Boyland", "status": "active"})
        db.users.docs.append({"_id": "u1", "company_id": "c1", "role": "superintendent", "name": "Ray Santos",
                              "assigned_projects": [PID]})
        db[server.WA_OPTINS].docs.append({"user_id": "u1", "company_id": "c1", "status": "active",
                                          "phone": "15551230000", "chat_id": "15551230000@c.us"})
        boom = AsyncMock(side_effect=AssertionError("a send in shadow mode"))
        env = {C.MODE_ENV: mode, **(env_extra or {})}
        with patch.object(server, "db", db), patch.dict(os.environ, env), \
                patch.object(server, "_confirmation_inputs", AsyncMock(return_value=(fixture_items(), fixture_frame()))), \
                patch.object(server, "unattended_project_filter", AsyncMock(return_value={})), \
                patch.object(server, "_shabbos_applies", AsyncMock(return_value=True)), \
                patch.object(server, "send_whatsapp_dm", boom), patch.object(server, "send_whatsapp_message", boom), \
                patch.object(server, "_quiet_or_send", boom), patch.object(server, "_group_post", boom), \
                patch.object(server, "_quiet_enqueue", AsyncMock()) as enq:
            report = asyncio.run(server._confirmations_tick(datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)))
        return report, db, enq, boom

    def test_shadow_stores_rows_and_calls_no_send_or_queue(self):
        report, db, enq, boom = self._run_tick("shadow")
        self.assertEqual(report["mode"], "shadow")
        self.assertEqual(report["rows"], 3)
        rows = db.confirmation_candidates.docs
        self.assertEqual({r["status"] for r in rows}, {"shadow"})
        self.assertEqual({r["target_user_id"] for r in rows}, {"u1"})
        enq.assert_not_called()
        boom.assert_not_called()

    def test_live_without_the_allow_variable_is_shadow(self):
        report, db, enq, _ = self._run_tick("live")
        self.assertEqual(report["mode"], "shadow")
        enq.assert_not_called()

    def test_off_reads_nothing(self):
        report, db, enq, _ = self._run_tick("off")
        self.assertEqual((report["rows"], db.confirmation_candidates.docs), (0, []))

    def test_live_allowed_queues_one_message_for_the_morning(self):
        report, db, enq, boom = self._run_tick("live", {C.LIVE_ENV: "1"}, messageable=True)
        self.assertEqual(enq.call_count, 1)
        self.assertEqual(enq.call_args.kwargs["until"], C.send_at(TODAY))
        boom.assert_not_called()
        # Queued is not sent: "sent" comes only from a delivery.
        self.assertEqual({r["status"] for r in db.confirmation_candidates.docs}, {"queued"})

    def test_live_allowed_but_the_roles_cannot_be_messaged_is_shadow_and_says_why(self):
        report, db, enq, boom = self._run_tick("live", {C.LIVE_ENV: "1"})
        self.assertEqual(report["mode"], "shadow")
        self.assertIn("cannot be messaged first", report["live_refused"])
        enq.assert_not_called()
        self.assertTrue(all("cannot be messaged first" in r["live_refused"] for r in db.confirmation_candidates.docs))

    def test_a_rerun_the_same_day_adds_nothing(self):
        from async_fake_mongo import AsyncFakeDB  # noqa: F401
        server = _server()
        report, db, _enq, _boom = self._run_tick("shadow")
        n = len(db.confirmation_candidates.docs)
        with patch.object(server, "db", db), patch.dict(os.environ, {C.MODE_ENV: "shadow"}), \
                patch.object(server, "_confirmation_inputs", AsyncMock(return_value=(fixture_items(), fixture_frame()))), \
                patch.object(server, "unattended_project_filter", AsyncMock(return_value={})), \
                patch.object(server, "_shabbos_applies", AsyncMock(return_value=True)):
            again = asyncio.run(server._confirmations_tick(datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)))
        self.assertEqual((again["rows"], len(db.confirmation_candidates.docs)), (0, n))

    def test_a_job_with_an_unreadable_source_is_not_asked_about(self):
        """"Nothing on record" from a source we could not read is our
        blindness, not the job's: no question at all."""
        from async_fake_mongo import AsyncFakeDB
        server = _server()
        db = AsyncFakeDB()
        db.projects.docs.append({"_id": PID, "company_id": "c1", "status": "active"})
        db.users.docs.append({"_id": "u1", "company_id": "c1", "role": "superintendent", "assigned_projects": [PID]})
        db[server.WA_OPTINS].docs.append({"user_id": "u1", "company_id": "c1", "status": "active"})
        with patch.object(server, "db", db), patch.dict(os.environ, {C.MODE_ENV: "shadow"}),                 patch.object(server, "_progress_evidence", AsyncMock(return_value=([], {"unreadable": ["photo_index"]}))),                 patch.object(server, "unattended_project_filter", AsyncMock(return_value={})):
            report = asyncio.run(server._confirmations_tick(datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)))
        self.assertEqual((report["rows"], report["skipped"].get("job_not_read")), (0, 1))

    def test_a_reply_in_shadow_is_left_to_the_brain(self):
        server = _server()
        with patch.dict(os.environ, {C.MODE_ENV: "shadow"}):
            self.assertFalse(asyncio.run(server._confirmation_take_reply({"user_id": "u1"}, "c@c.us", "1 done")))

    def test_the_reply_hook_comes_before_the_field_role_refusal(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        body = src[src.index("async def _dm_assistant_reply("):]
        self.assertLess(body.index("await _confirmation_take_reply("), body.index("dm_roles.FIELD_UNAVAILABLE_TEXT"))


class LiveReplyIsRecorded(unittest.TestCase):
    """With live allowed (as only the owner could set it), an answer is an
    attested item, an inspection answer an inspection report, an event."""

    def test_answers_recorded_and_acknowledged(self):
        from async_fake_mongo import AsyncFakeDB
        server = _server()
        db = AsyncFakeDB()
        cands = C.candidates(fixture_items(), fixture_frame())
        plumbing = [g for g in by_trigger(cands)[C.GATE_UNKNOWN] if g["node"] == IR.PLUMBING_ROUGH]
        pick = [plumbing[0], by_trigger(cands)[C.START_PASSED][0]]
        for pos, c in enumerate(pick, 1):
            db.confirmation_candidates.docs.append({
                "_id": f"k{pos}", "day": TODAY.isoformat(), "project_id": PID, "company_id": "c1",
                "target_user_id": "u1", "trigger": c["trigger"], "node": c["node"], "level": c["level"],
                "question": c["question"], "options": c["options"], "status": "queued", "position": pos})
            # Delivered at 7:30 New York (the queue appends "sent" after delivering).
            db.confirmation_events.docs.append({"candidate_id": f"k{pos}", "project_id": PID, "company_id": "c1",
                                                "kind": "sent", "by": "u1",
                                                "at": datetime(2026, 11, 10, 12, 30, tzinfo=timezone.utc)})
        sent = AsyncMock()
        with patch.object(server, "db", db), patch.dict(os.environ, {C.MODE_ENV: "live", C.LIVE_ENV: "1"}), \
                patch.object(C, "unmessageable_roles", lambda: []), \
                patch.object(server, "send_whatsapp_message", sent):
            took = asyncio.run(server._confirmation_take_reply(
                {"user_id": "u1", "user": {"name": "Ray Santos"}}, "1555@c.us", "1 passed, 2 no sé",
                now=datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)))
        self.assertTrue(took)
        answers = {a["candidate_id"]: a for a in db.confirmation_answers.docs}
        self.assertEqual(answers["k1"]["item"]["claim"], "done")
        self.assertEqual(answers["k2"]["item"]["claim"], "dont_know")
        self.assertEqual(answers["k2"]["answer"], "dont_know")
        reports = db[server.INSPECTION_REPORTS].docs
        self.assertEqual([(r["gate"], r["result"], r["status"]) for r in reports],
                         [(IR.PLUMBING_ROUGH, "passed", IR.ATTESTED)])
        # The two deliveries and the two answers.
        self.assertEqual([e["kind"] for e in db.confirmation_events.docs], ["sent", "sent", "answered", "answered"])
        self.assertIn("not verified", sent.call_args.args[1])


class TheShadowReport(unittest.TestCase):
    def test_precision_with_wilson_and_unreviewed_apart(self):
        sys.path.insert(0, str(_BACKEND / "scripts"))
        import confirmation_shadow_report as R
        rows = [{"_id": f"k{i}", "project_id": PID, "day": "2026-11-10", "trigger": t, "target_user_id": "u1",
                 "text": "Good morning Ray", "status": "shadow", "position": i}
                for i, t in enumerate([C.CONFLICT, C.CONFLICT, C.GATE_UNKNOWN], 1)]
        at = datetime(2026, 11, 10, tzinfo=timezone.utc)
        events = [{"candidate_id": "k1", "kind": "review", "verdict": "correct", "at": at},
                  {"candidate_id": "k2", "kind": "review", "verdict": "correct", "at": at},
                  {"candidate_id": "k2", "kind": "review", "verdict": "wrong", "at": at + timedelta(minutes=1)}]
        s = R.summarize(rows, events)
        self.assertEqual((s["overall"]["correct"], s["overall"]["wrong"], s["overall"]["unreviewed"]), (1, 1, 1))
        self.assertIn("Wilson", s["overall"]["text"])
        self.assertEqual(s["mix"][C.CONFLICT], 2)
        self.assertEqual(list(s["messages"].values()), ["Good morning Ray"])

    def test_it_refuses_to_count_on_an_absent_field(self):
        sys.path.insert(0, str(_BACKEND / "scripts"))
        import confirmation_shadow_report as R
        from probe_helpers import FieldNotInSample
        with self.assertRaises(FieldNotInSample):
            R.summarize([{"_id": "k", "project_id": PID, "day": "2026-11-10"}], [])


if __name__ == "__main__":
    unittest.main()
