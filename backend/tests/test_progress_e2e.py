"""EVIDENCE TO SCHEDULE, END TO END, ON ONE JOB.

One fixture project (588, six stories) driven through the REAL server code on
the fake database (tests/_fake_mongo.FakeDb, as every WhatsApp test): the photo
index sweep, the photo-place confirmation route, the WhatsApp DM brain with the
model scripted (tests/test_dm_brain.FakeLLM), the voice-note and sign-off paths,
the schedule upload and confirm routes, and scripts/progress_validation.py.

CHECKLIST. Covered here:
  [x] filed daily logs over five weeks and floors 3, 4, 5, 9: one crew row
      shared by floors 1-4, an AMENDMENT that moves drywall from floor 4 to 5,
      a WITHDRAWN amendment (its floor-6 duct work is not a report), and a
      DRAFT (its floor-3 drywall is not a report)
  [x] photo index rows made by the real sweep (_photo_index_tick), the vision
      call stubbed per photo: place by log row, floor marking, plan tag
      (plan_records "THIRD FLOOR PLAN"), and a PM's confirmation through the
      route; one row of the older prompt left in the re-read backlog; the
      superseded original's photo and the withdrawn amendment's photo excluded
  [x] inspections told on WhatsApp: "plumbing rough passed on 3" (a CP, text),
      an ambiguous one (a PM, "went alright I guess", the model claiming
      passed), a voice note "hydro didn't pass" (the model claiming passed)
  [x] a sign-off document (photo), stubbed at the vision call and at OCR
  [x] a DOB signed-off filing row (and an approved, not signed-off one)
  [x] a schedule file uploaded through the route (CSV with predecessors and one
      link to a missing id), confirmed through the route by an admin
  [x] a CP and a PM account: the CP views the PROPOSED sequence (nothing
      stored) and is refused approval; the PM views (stored) and approves
  [x] work_status through the brain: the gates read the VALIDATED result only
  [x] the lookahead through the brain: the file's dates, no estimate
  [x] the validation script's numbers on this fixture, the database unchanged,
      no name, email, phone or quote in its output

NOT covered (each needs something this repo cannot hold, or another lane):
  [ ] the real vision model, RapidOCR, Whisper or the real DM model
  [ ] a real P6 XER / MS Project export (the importer's own tests build them)
  [ ] Mongo itself: projections, indexes, $regex flavours (FakeDb is a stand-in)
  [ ] the app screens (the schedule and photo-place routes are called directly,
      without their FastAPI dependencies: require_approved / project access)
  [ ] photo relations and place lending (both disabled until a benchmark)
  [ ] the evidence ladder (lib/evidence.py) as a reader of these sources: no
      server code calls it yet (evidence-sources / progress-model lanes)
  [ ] DOB sign-off ingestion: no code stores `signoff_date`; the fixture row is
      written by hand to show the script counts it
  [ ] forecasting, location binder, confirmations lanes (not merged)
  [ ] PHOTO_INDEX_SLICE_DAYS is raised for the one sweep tick here, so five
      weeks are read in one tick; the slice-by-slice backfill is tested in
      tests/test_photo_search*.py
"""

from __future__ import annotations

import asyncio
import copy
import csv
import io
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
import progress_validation as PVS  # noqa: E402  (scripts/progress_validation.py)
from lib import inspection_reports as IR  # noqa: E402
from lib import photo_search, progress_plan, voice_ingest  # noqa: E402
from lib import progress_validation as PV  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_dm_brain import FakeLLM, last_tool_results, resp, text, use  # noqa: E402
from tests.test_inspection_reports import _FakeHttp, _jpeg  # noqa: E402
from tests.test_whatsapp_dm_assistant import _optin  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, CP_PHONE, PM_PHONE, _Ctx  # noqa: E402

CO = "co_a"
P = "proj_588"
NY = ZoneInfo("America/New_York")
TODAY = datetime.now(timezone.utc).astimezone(NY).date()


def day(n: int) -> str:
    """TODAY + n days, ISO. The server reads the real clock, so the fixture does too."""
    return (TODAY + timedelta(days=n)).isoformat()


ADMIN = {"_id": "u_admin", "id": "u_admin", "company_id": CO, "role": "admin", "phone": "+" + ADMIN_PHONE,
         "name": "Ada Admin", "email": "ada@levelog-fixture.test", "account_status": "approved"}
PM = {"_id": "u_pm", "id": "u_pm", "company_id": CO, "role": "pm", "phone": "+" + PM_PHONE, "name": "Pat PM",
      "email": "pat@levelog-fixture.test", "account_status": "approved", "assigned_projects": [P]}
CP = {"_id": "u_cp", "id": "u_cp", "company_id": CO, "role": "cp", "phone": "+" + CP_PHONE, "name": "Cal CP",
      "account_status": "approved", "assigned_projects": [P]}
PEOPLE = ("Ada Admin", "Pat PM", "Cal CP", "J. Ruiz", "ada@levelog-fixture.test", "pat@levelog-fixture.test",
          ADMIN_PHONE, PM_PHONE, CP_PHONE)


def _crew(company, trade, work, where, *photos):
    return {"company": company, "trade": trade, "num_workers": 4, "work_description": work,
            "work_locations": where, "photos": [{"original_r2_key": k} for k in photos]}


def _log(_id, n, *rows, status="submitted", **kw):
    return {"_id": _id, "log_type": "daily_jobsite", "project_id": P, "company_id": CO, "date": day(n),
            "status": status, "created_at": datetime.now(timezone.utc) + timedelta(days=n),
            "data": {"activities": list(rows)}, **kw}


LOGS = [
    _log("L1", -35, _crew("Arkon Builders", "Framers", "Interior framing, Blocking", "3rd floor", "ph/p1.jpg")),
    _log("L2", -28, _crew("Quality Plumbing", "Plumber", "Domestic water rough, DWV", "floors 1-4",
                          "ph/p2.jpg", "ph/p3.jpg", "ph/p5.jpg", "ph/p6.jpg")),
    _log("L3", -21, _crew("Power Direct", "Electrician", "Electrical wiring", "4th floor", "ph/p4.jpg"),
         _crew("Arkon Builders", "Laborers", "Cleaning", "outer bldg")),
    # Drywall was filed on 4, then AMENDED to 5: the amendment is the record.
    _log("L4", -14, _crew("Arkon Builders", "Tapers", "Drywall", "4th floor", "ph/p7.jpg")),
    _log("L4a", -14, _crew("Arkon Builders", "Tapers", "Drywall, taping", "5th floor", "ph/p8.jpg"),
         is_amendment=True, parent_logbook_id="L4", amendment_reason="wrong floor"),
    # An amendment to floor 6 that was WITHDRAWN: the original stands.
    _log("L5", -7, _crew("BreezCo HVAC", "HVAC", "Ductwork rough", "3rd floor")),
    _log("L5a", -7, _crew("BreezCo HVAC", "HVAC", "Ductwork rough", "6th floor", "ph/p9.jpg"),
         status="withdrawn", is_amendment=True, parent_logbook_id="L5"),
    _log("L6", -3, _crew("Arkon Builders", "Laborers", "MEP rough-in", "floor 9")),
    _log("L7", -2, _crew("Arkon Builders", "Tapers", "Drywall", "3rd floor"), status="draft"),
]

#: What the vision model says of each photo (the paid call is stubbed here).
VISION = {
    "ph/p1.jpg": {"view": "interior", "quality": 8, "description": "Metal stud framing with blocking.", "tags": ["framing"],
                  "visible_text": [], "room_type": "corridor"},
    "ph/p2.jpg": {"view": "interior", "quality": 8, "description": "Copper water piping along open studs.",
                  "tags": ["plumbing"], "visible_text": ["FLOOR 3"], "room_type": "corridor"},
    "ph/p3.jpg": {"view": "interior", "quality": 7, "description": "PVC drain piping in a wall cavity.",
                  "tags": ["plumbing"], "visible_text": ["3A"], "room_type": "bathroom"},
    "ph/p4.jpg": {"view": "interior", "quality": 7, "description": "Electrical wiring pulled through studs.",
                  "tags": ["electrical"], "visible_text": [], "room_type": "apartment"},
    "ph/p5.jpg": {"view": "interior", "quality": 6, "description": "Water lines stubbed out at a wall.",
                  "tags": ["plumbing"], "visible_text": [], "room_type": "kitchen"},
    "ph/p7.jpg": {"view": "interior", "quality": 7, "description": "Gypsum board hung on framing.",
                  "tags": ["drywall"], "visible_text": [], "room_type": "apartment"},
    "ph/p8.jpg": {"view": "interior", "quality": 7, "description": "Gypsum board seams taped.",
                  "tags": ["drywall"], "visible_text": [], "room_type": "apartment"},
    "ph/p9.jpg": {"view": "interior", "quality": 7, "description": "Duct run at a ceiling.", "tags": [],
                  "visible_text": [], "room_type": "corridor"},
}

#: The schedule, as a P6 XER export: (task id, code, name, start, finish).
SCHEDULE = [
    ("901", "A10", "Frame Floor 3", day(-40), day(-30)),
    ("902", "A20", "Plumbing Rough Floor 3", day(-30), day(-20)),
    ("903", "A30", "Electrical Rough Floor 3", day(-25), day(-15)),
    ("904", "A40", "Drywall Floor 3", day(3), day(12)),
    ("905", "A50", "Drywall Floor 4", day(10), day(20)),
    ("906", "A60", "Site logistics", day(-60), day(60)),
]
#: (successor, predecessor, type, lag hours, predecessor's project). 999 is
#: in another project: a link the importer must count, never guess.
LINKS = [("902", "901", "PR_FS", "0", "1"), ("903", "901", "PR_FS", "0", "1"),
         ("904", "902", "PR_FS", "0", "1"), ("904", "903", "PR_SS", "16", "1"),
         ("905", "904", "PR_FS", "0", "1"), ("905", "999", "PR_FS", "0", "2")]
_TASK_F = ["task_id", "proj_id", "wbs_id", "clndr_id", "task_code", "task_name", "task_type", "complete_pct_type",
           "phys_complete_pct", "target_drtn_hr_cnt", "target_start_date", "target_end_date", "early_start_date",
           "early_end_date", "act_start_date", "act_end_date"]
_PRED_F = ["task_pred_id", "task_id", "pred_task_id", "proj_id", "pred_proj_id", "pred_type", "lag_hr_cnt"]


def _schedule_xer() -> bytes:
    def table(name, fields, rows):
        return "\n".join([f"%T\t{name}", "%F\t" + "\t".join(fields)] + ["%R\t" + "\t".join(r) for r in rows])
    tasks = [[tid, "1", "10", "9", code, name, "TT_Task", "CP_Phys", "", "", f"{s} 08:00", f"{f} 17:00",
              f"{s} 08:00", f"{f} 17:00", "", ""] for tid, code, name, s, f in SCHEDULE]
    preds = [["p" + a + b, a, b, "1", proj, kind, lag] for a, b, kind, lag, proj in LINKS]
    return "\n".join([
        f"ERMHDR\t20.12\t{day(-1)}\tProject\tadmin\tdb\tProject Management\tUSD",
        table("PROJECT", ["proj_id", "proj_short_name", "last_recalc_date", "plan_start_date"],
              [["1", "588", f"{day(-1)} 08:00", f"{day(-60)} 08:00"]]),
        table("CALENDAR", ["clndr_id", "day_hr_cnt"], [["9", "8"]]),
        table("PROJWBS", ["wbs_id", "proj_id", "parent_wbs_id", "wbs_short_name", "wbs_name", "seq_num"],
              [["10", "1", "", "588", "Building", "1"]]),
        table("TASK", _TASK_F, tasks), table("TASKPRED", _PRED_F, preds), "%E"]).encode("utf-8")


def _schedule_csv() -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ID", "Task Name", "Start", "Finish", "Predecessors"])
    w.writerows([("10", "Frame Floor 3", day(-40), day(-30), ""), ("20", "Drywall Floor 3", day(3), day(12), "10")])
    return out.getvalue().encode()


def fixture_db() -> FakeDb:
    db = FakeDb(
        unique={server.WA_OPTINS: (("phone", "user_id"),)},
        users=[dict(ADMIN), dict(PM), dict(CP)],
        companies=[{"_id": CO, "name": "Fixture GC"}],
        projects=[{"_id": P, "company_id": CO, "name": "Thomas", "address": "588 Thomas S Boyland St, Brooklyn, NY",
                   "building_stories": 6}],
        logbooks=copy.deepcopy(LOGS),
        plan_records=[{"_id": "pr1", "project_id": P, "unit": "3A", "sheet_title": "THIRD FLOOR PLAN",
                       "sheet_number": "A-103"}],
        dob_logs=[{"_id": "dob1", "project_id": P, "record_type": "job_status", "filing_status": "Signed Off",
                   "signoff_date": day(-60), "job_filing_number": "B00000001-I1"},
                  {"_id": "dob2", "project_id": P, "record_type": "job_status", "filing_status": "Approved",
                   "job_filing_number": "B00000002-I1"}],
    )
    # A photo described before the place prompt existed: no prompt_v, filed
    # for floors 1-4, so the re-read wants it.
    db[server.PHOTO_INDEX].rows.append({
        "_id": "v1:ph/p6.jpg", "kind": "photo", "photo_key": "ph/p6.jpg", "short": photo_search.short_id("ph/p6.jpg"),
        "project_id": P, "company_id": CO, "log_id": "L2", "date": day(-28), "sub": "Quality Plumbing",
        "where": "floors 1-4", "work": "Domestic water rough, DWV", "view": "interior", "quality": 6.0,
        "description": "Pipe hangers on a ceiling slab.", "tags": []})
    for uid, phone in (("u_admin", ADMIN_PHONE), ("u_pm", PM_PHONE), ("u_cp", CP_PHONE)):
        _optin(db, uid, phone)
    return db


def _run(coro):
    return asyncio.run(coro)


def _payload(phone, body, mid, **msg):
    chat = f"{phone}@c.us"
    return {"event": "message", "data": {"message": {
        "id": {"id": mid, "fromMe": False, "_serialized": f"false_{chat}_{mid}"}, "from": chat, "body": body,
        "type": "chat", **msg}}}


class Site:
    """The job, built step by step through the server, once for the module."""

    def __init__(self):
        self.db = fixture_db()
        self.results: dict = {}
        self.n = 0
        with _Ctx(db=self.db) as c:
            self.c = c
            self.sweep()
            self.confirm_photo()
            self.inspections()
            self.signoff()
            self.schedule_draft()
            self.sequence()
            self.confirm_schedule()
            self.questions()

    # ── how a message gets in ──
    def say(self, phone, body, llm, **msg):
        self.n += 1

        async def on(ident):
            return True

        async def react(*a, **k):
            return True
        with patch.object(server, "_dm_brain_on", on), patch.object(server, "_dm_brain_client", lambda: llm), \
                patch.object(server, "_react_to_message", react), patch.object(server, "LLM_API_KEY", None):
            _run(server._process_whatsapp_message(_payload(phone, body, f"m{self.n}", **msg)))

    def tool(self, key, phone, body, name, args):
        """The model calls one tool; its result is kept under `key`."""
        def keep(kw):
            self.results[key] = last_tool_results(kw)[0]
            return resp(text("That is what the records hold for it."))
        self.say(phone, body, FakeLLM(resp(use(name, args)), keep))
        assert key in self.results, f"{key}: the model was never handed the {name} result"

    # ── the steps ──
    def sweep(self):
        calls = []

        async def vision(raw, project_id):
            calls.append(raw.decode())
            return dict(VISION[raw.decode()])

        def photo_bytes(row):
            return str(row["key"]).encode()
        with patch.object(server, "QWEN_API_KEY", "k"), patch.object(server, "_photo_index_call", vision), \
                patch.object(server, "_report_photo_bytes", photo_bytes), \
                patch.object(server, "PHOTO_INDEX_SLICE_DAYS", 60), patch.dict(os.environ, {"PHOTO_INDEX_DISABLED": "0"}):
            self.results["sweep"] = _run(server._photo_index_tick(budget=7))
        self.results["vision_calls"] = sorted(calls)

    def confirm_photo(self):
        short = photo_search.short_id("ph/p5.jpg")
        self.results["confirmed"] = _run(server.confirm_photo_place(
            P, server.PhotoPlaceConfirmation(photo=short, level="2"), current_user=dict(PM)))

    def inspections(self):
        self.tool("cp_plumbing", CP_PHONE, "Plumbing rough passed on 3 at 588", "report_inspection",
                  {"job": "588", "inspection": "plumbing rough", "levels": "3", "result": "passed",
                   "quote": "Plumbing rough passed on 3"})
        # The model claims a pass the words do not state.
        self.tool("pm_ambiguous", PM_PHONE, "Electrical rough on 3 at 588 went alright I guess", "report_inspection",
                  {"job": "588", "inspection": "electrical rough", "levels": "3", "result": "passed",
                   "quote": "Electrical rough on 3 at 588 went alright I guess"})
        said = "Hydro didn't pass on the third floor at 588"

        async def audio(parsed):
            return b"OggS" + b"\x00" * 3996

        async def ingest(audio_bytes, **kw):
            return voice_ingest.VoiceIngestResult(
                ok=True, english_transcript=said, original_transcript=said, language_detected="english",
                no_speech_prob=0.01, confidence=0.95, duration_sec=4.0, telemetry={})

        def keep(kw):
            self.results["cp_voice"] = last_tool_results(kw)[0]
            return resp(text("That is what the records hold for it."))
        llm = FakeLLM(resp(use("report_inspection", {"job": "588", "inspection": "hydro", "levels": "3",
                                                     "result": "passed", "quote": "Hydro didn't pass on the third floor"})),
                      keep)
        with patch.object(server, "download_audio", audio), patch.object(voice_ingest, "process_voice_note", ingest):
            self.say(CP_PHONE, "", llm, type="ptt")

    def signoff(self):
        said = json.dumps({"is_signoff": True, "inspection": "Firestopping", "levels": "Floor 3", "result": "passed",
                           "date": day(-1), "inspector": "J. Ruiz", "quote": "RESULT: APPROVED"})
        self.http = _FakeHttp(said)

        async def image(parsed):
            return _jpeg()

        def upload(data, key, ctype="application/octet-stream"):
            return f"https://r2/{key}"
        with patch.object(server, "download_image", image), patch.object(server, "_upload_to_r2", upload), \
                patch.object(server, "ServerHttpClient", self.http), patch.object(server, "QWEN_API_KEY", "k"), \
                patch.object(server, "_inspection_doc_ocr",
                             lambda page: "FIRESTOPPING SPECIAL INSPECTION\nFLOOR 3\nRESULT: APPROVED"):
            self.say(PM_PHONE, "firestopping sign off 588", FakeLLM(resp(text("brain"))), type="image")
        self.results["signoff_reply"] = [p.get("message") for p in self.c.wire.calls if "message" in p][-1]

    def schedule_draft(self):
        from starlette.datastructures import UploadFile
        up = UploadFile(filename="588.xer", file=io.BytesIO(_schedule_xer()))
        self.results["draft"] = _run(server.upload_baseline_schedule(P, file=up, current_user=dict(ADMIN)))

    def sequence(self):
        """No CONFIRMED schedule yet (a draft only): the PROPOSED sequence applies."""
        self.tool("cp_view", CP_PHONE, "Show me the sequence for 588", "proposed_sequence", {"job": "588"})
        self.results["stored_after_cp_view"] = copy.deepcopy(self.db[server.PROPOSED_SEQUENCES].rows)
        self.tool("cp_approve", CP_PHONE, "Approve the sequence for 588", "proposed_sequence",
                  {"job": "588", "approve": True})
        self.results["stored_after_cp_approve"] = copy.deepcopy(self.db[server.PROPOSED_SEQUENCES].rows)
        self.tool("pm_view", PM_PHONE, "Show me the sequence for 588", "proposed_sequence", {"job": "588"})
        self.tool("pm_approve", PM_PHONE, "Approve the sequence for 588", "proposed_sequence",
                  {"job": "588", "approve": True})

    def confirm_schedule(self):
        self.results["confirmed_schedule"] = _run(server.confirm_baseline_schedule(
            P, self.results["draft"]["id"], server.ScheduleConfirm(reviewed=True), current_user=dict(ADMIN)))

    def questions(self):
        self.tool("admin_status", ADMIN_PHONE, "What's holding up drywall on Floor 3 at 588?", "work_status",
                  {"job": "588", "work": "drywall", "level": "3"})
        self.tool("cp_status", CP_PHONE, "Where is drywall on 5 at 588?", "work_status",
                  {"job": "588", "work": "drywall", "level": "5"})
        self.tool("pm_lookahead", PM_PHONE, "What's on the schedule at 588 for the next two weeks?",
                  "schedule_lookahead", {"job": "588", "days": 14})


_SITE = None


def site() -> Site:
    global _SITE
    if _SITE is None:
        _SITE = Site()
    return _SITE


def validation_output(db):
    """The script, as the owner runs it, on the fixture database."""
    with _Ctx(db=db), PVS.read_only(server) as ro:
        code, out = _run(PVS.job_report(server, "588", today=TODAY))
        cov = _run(PVS.all_jobs_report(server, today=TODAY))
    return code, out, cov, ro


# ══ THE RECORD THE ENGINE READS ═══════════════════════════════════════════

class TheSweepAndThePlaces(unittest.TestCase):

    def test_every_filed_photo_was_described_once_and_nothing_else(self):
        s = site()
        # p6 was already described; p9 sits on a withdrawn amendment.
        self.assertEqual(s.results["vision_calls"],
                         ["ph/p1.jpg", "ph/p2.jpg", "ph/p3.jpg", "ph/p4.jpg", "ph/p5.jpg", "ph/p7.jpg", "ph/p8.jpg"])
        keys = sorted(r["photo_key"] for r in s.db[server.PHOTO_INDEX].rows if r.get("kind") == "photo")
        self.assertNotIn("ph/p9.jpg", keys)
        legacy = next(r for r in s.db[server.PHOTO_INDEX].rows if r["_id"] == "v1:ph/p6.jpg")
        self.assertNotIn("prompt_v", legacy)                       # still waiting for its re-read

    def test_the_confirmation_is_appended_with_who(self):
        s = site()
        (row,) = s.db[server.PHOTO_PLACE_CONFIRMATIONS].rows
        self.assertEqual((row["level"], row["by_user_id"], row["via"]), ("FLOOR_2", "u_pm", "api"))


class InspectionsAreReadBack(unittest.TestCase):

    def rows(self):
        return {r["inspection_as_said"]: r for r in site().db[IR.COLLECTION].rows}

    def test_the_cps_plain_statement_is_attested(self):
        r = self.rows()["plumbing rough"]
        self.assertEqual((r["status"], r["result"], r["gate"], r["levels"], r["reporter_user_id"], r["source"]),
                         (IR.ATTESTED, "passed", IR.PLUMBING_ROUGH, ["FLOOR_3"], "u_cp", "text"))
        self.assertTrue(r["validation"]["agree"])

    def test_the_ambiguous_one_is_kept_with_no_result(self):
        r = self.rows()["electrical rough"]
        self.assertEqual((r["status"], r["result"], r["model_result"]), (IR.UNRESOLVED, None, "passed"))
        self.assertIn("UNRESOLVED", site().results["pm_ambiguous"])

    def test_didnt_pass_in_a_voice_note_is_never_stored_as_passed(self):
        r = self.rows()["hydro"]
        self.assertEqual((r["status"], r["result"], r["source"]), (IR.UNRESOLVED, None, "voice"))
        self.assertEqual(r["validation"]["read"], ["failed"])
        self.assertIn("the words say failed, not passed", site().results["cp_voice"])

    def test_the_signoff_is_a_document_on_file(self):
        r = self.rows()["Firestopping"]
        self.assertEqual((r["status"], r["result"], r["gate"], r["levels"], r["source"]),
                         (IR.DOCUMENT, "passed", IR.FIRESTOPPING, ["FLOOR_3"], "document"))
        self.assertEqual(r["validation"]["source"], "ocr")
        self.assertIn("Kept the sign-off", site().results["signoff_reply"])


class TheProposedSequence(unittest.TestCase):

    def test_a_cp_views_it_and_nothing_is_stored(self):
        s = site()
        self.assertIn("PROPOSED sequence", s.results["cp_view"])
        self.assertIn("A PM or an admin can approve it.", s.results["cp_view"])
        self.assertEqual(s.results["stored_after_cp_view"], [])

    def test_a_cp_cannot_approve_it(self):
        s = site()
        self.assertTrue(s.results["cp_approve"].startswith("REFUSED"), s.results["cp_approve"])
        self.assertIn("approving a sequence", s.results["cp_approve"])
        self.assertEqual(s.results["stored_after_cp_approve"], [])

    def test_a_pm_approves_it_and_it_stays_proposed_in_words(self):
        s = site()
        (row,) = s.db[server.PROPOSED_SEQUENCES].rows
        self.assertEqual((row["status"], row["approved_by"]), ("approved", "u_pm"))
        self.assertEqual([h["action"] for h in row["history"]], ["proposed", "approved"])
        self.assertIn("PROPOSED sequence for", s.results["pm_approve"])
        self.assertIn("Approved by Pat PM", s.results["pm_approve"])
        self.assertEqual([r["status"] for r in s.db[server.PROJECT_SCHEDULES].rows], ["confirmed"])


class WorkStatusThroughTheBrain(unittest.TestCase):

    def test_drywall_on_3_reads_the_records_and_the_validated_gates(self):
        t = site().results["admin_status"]
        # The draft's floor-3 drywall is not a report.
        self.assertIn("Drywall on Floor 3: no report on this level (that does not mean it wasn't done).", t)
        self.assertIn(f"Schedule file, Drywall Floor 3: baseline finish {day(12)}, current finish {day(12)}", t)
        self.assertIn("This job's own logic, from its confirmed schedule file: Drywall Floor 3 has 2 predecessor(s):", t)
        self.assertIn("- Plumbing Rough Floor 3 (FS, lag 0 working days):", t)
        self.assertIn("- Electrical Rough Floor 3 (SS, lag 2 working days):", t)
        self.assertIn("- plumbing rough inspection: passed, reported by Cal CP, not verified", t)
        # The ambiguous report and the "didn't pass" voice note moved nothing.
        self.assertIn("- electrical rough inspection: UNKNOWN, neither passed nor failed", t)
        self.assertIn("- sprinkler inspection / hydro test (if the building has this system): UNKNOWN, neither passed nor failed", t)
        self.assertIn("- firestopping special inspection: sign-off document on file, reported by Pat PM, not verified; "
                      "the document reads passed", t)
        self.assertNotIn("%", t)

    def test_the_amendment_is_the_record_and_the_cp_may_ask(self):
        t = site().results["cp_status"]
        self.assertIn("Drywall on Floor 5: reported", t)
        self.assertIn("by Arkon Builders", t)
        self.assertNotIn("REFUSED", t)

    def test_the_withdrawn_amendment_is_not_a_report(self):
        s = site()
        with _Ctx(db=s.db):
            six = _run(server._dm_work_status({"ident": {"company_id": CO}}, {"id": P, "label": "588"},
                                              {"work": "ductwork", "level": "6"}))
            three = _run(server._dm_work_status({"ident": {"company_id": CO}}, {"id": P, "label": "588"},
                                                {"work": "ductwork", "level": "3"}))
        self.assertIn("Duct rough on Floor 6: no report on this level", six)
        self.assertIn(f"Duct rough on Floor 3: reported {server.work_state._day(TODAY - timedelta(days=7))}, 1 day(s); "
                      "by BreezCo HVAC", three)


class TheLookahead(unittest.TestCase):

    def test_it_states_the_files_dates_and_logic(self):
        t = site().results["pm_lookahead"]
        self.assertIn(f"- Drywall Floor 3 (A40). FILE: planned current {day(3)} to {day(12)}.", t)
        self.assertIn("LOGIC: after Plumbing Rough Floor 3 (FS, lag 0 working days); Electrical Rough Floor 3 (SS, lag 2 working days)", t)
        self.assertIn("1 more link(s) in the file could not be matched", t)
        self.assertIn(f"- Electrical Rough Floor 3 (A30): planned finish {day(-15)}", t)

    def test_no_estimate_is_labelled_as_fact(self):
        t = site().results["pm_lookahead"]
        # The lookahead (the file's dates) carries no estimate at all ...
        look, _, status = t.partition("SCHEDULE STATUS for")
        body = look.split("FILE dates and LOGIC are the confirmed schedule's own")[0]
        for word in ("estimate", "forecast", "at that rate", "per level", "%", "about "):
            self.assertNotIn(word, body.lower())
        # ... and the schedule-status groups after it (lib/forecast.py) name an
        # estimate only inside the labelled ESTIMATES group, or to say none is made.
        self.assertTrue(status, "the lookahead ends with the schedule status groups")
        allowed = ("ESTIMATES (computed by LeveLog, NOT verified", "- ESTIMATE:", "not enough completed evidence for an estimate",
                   "no completion forecast", "Keep these four groups apart")
        loose = [ln for ln in status.splitlines()
                 if ("estimat" in ln.lower() or "forecast" in ln.lower()) and not any(a in ln for a in allowed)]
        self.assertEqual(loose, [], "an estimate outside its labelled group")
        # The lookahead's own no-forecast rule gives way to the status groups'
        # rule (lib/forecast.lookahead_with_status): estimates only as labelled.
        self.assertIn("Keep these four groups apart", status)
        self.assertIn("No production rate or estimated finish is made", progress_plan.LOOKAHEAD_RULE)
        sched = next(r for r in site().db[server.PROJECT_SCHEDULES].rows if r["status"] == "confirmed")["doc"]
        la = progress_plan.lookahead(sched, [], today=TODAY, days=14)
        self.assertEqual([i["id"] for i in la["items"]], ["A60", "A40", "A50"])
        self.assertFalse([k for i in la["items"] for k in i if "estimat" in k or "rate" in k or "forecast" in k])


class TheScheduleUploadRoute(unittest.TestCase):

    def test_the_route_keeps_the_files_own_name(self):
        """The XER above went in as "588.xer" (it used to become "588.xer.pdf")."""
        self.assertEqual(site().results["draft"]["source_name"], "588.xer")

    def test_a_csv_schedule_can_be_uploaded(self):
        """FOUND BY THIS FILE: upload_baseline_schedule ran the name through
        _sanitize_upload_filename, which appends ".pdf" to any name not ending in
        it; a CSV is known only by its extension, so every CSV upload was refused
        with a 422. The route now keeps a schedule file's own extension."""
        from starlette.datastructures import UploadFile
        with _Ctx(db=fixture_db()):
            out = _run(server.upload_baseline_schedule(
                P, file=UploadFile(filename="588.csv", file=io.BytesIO(_schedule_csv())), current_user=dict(ADMIN)))
        self.assertEqual(out["format"], "csv")


# ══ THE VALIDATION SCRIPT ON THIS FIXTURE ═════════════════════════════════

class TheValidationScript(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = site().db
        cls.before = copy.deepcopy({k: v.rows for k, v in cls.db._c.items()})
        cls.code, cls.out, cls.cov, cls.ro = validation_output(cls.db)

    def line(self, label):
        hits = [ln.strip() for ln in self.out.splitlines() if ln.strip().startswith(label + ":")]
        self.assertEqual(len(hits), 1, (label, hits))
        return hits[0][len(label) + 1:].strip()

    def test_it_wrote_nothing_and_called_nothing(self):
        self.assertEqual(self.code, 0)
        self.assertEqual(self.ro.attempts, [])
        self.assertEqual({k: v.rows for k, v in self.db._c.items()}, self.before)

    def test_the_logs_numbers(self):
        self.assertEqual(self.line("filed daily logs (effective heads)"), "6")
        self.assertEqual(self.line("of them amended (an amendment is the record)"), "1")
        self.assertEqual(self.line("crew rows"), "7")
        self.assertEqual(self.line("work phrases"), "10")
        self.assertEqual(self.line("phrases naming any level"), "9/10 (90%)")
        self.assertEqual(self.line("phrases naming exactly one level"), "7/10 (70%)")
        self.assertEqual(self.line("phrases naming several levels (shared)"), "2/10 (20%)")
        self.assertEqual(self.line("phrases naming a level not in the project"), "1/10 (10%)")
        self.assertEqual(self.line("phrases matching the work sequence"), "9/10 (90%)")
        self.assertEqual(self.line("of those, generic only (trade, not part)"), "1/9 (11%)")
        self.assertIn("    Cleaning  x1", self.out)
        self.assertIn("    outer bldg  x1", self.out)

    def test_the_photo_numbers(self):
        self.assertEqual(self.line("indexed photos (this job)"), "8")
        # p7 is on the superseded original: not read.
        self.assertEqual(self.line("of them on the window's filed logs (what work_status reads)"), "7")
        self.assertEqual(self.line("index prompt version mix"), f"{photo_search.PROMPT_V} 7, absent 1")
        self.assertEqual(self.line("re-read backlog (older prompt, row names several levels or none)"),
                         "1 (1 still to be tried, 0 given up after 3 tries)")
        self.assertEqual(self.line("place certainty: exact (confirmed/inferred/lent)"), "6/7 (86%)")
        self.assertEqual(self.line("place certainty: constrained (several levels, none chosen)"), "1/7 (14%)")
        self.assertEqual(self.line("placed to one level using log row"), "3/7 (43%)")
        self.assertEqual(self.line("placed to one level using plan tag"), "1/7 (14%)")
        self.assertEqual(self.line("placed to one level using floor marking"), "1/7 (14%)")
        self.assertEqual(self.line("placed to one level using confirmation"), "1/7 (14%)")
        self.assertEqual(self.line("photo relation rows"), "0")

    def test_the_inspection_numbers(self):
        self.assertEqual(self.line("inspection_reports rows"), "4")
        self.assertEqual(self.line("by status"), "unresolved 2, attested 1, document_on_file 1")
        self.assertEqual(self.line("validated (words agree with the model)"), "2/4 (50%)")
        self.assertEqual(self.line("on a tracked gate"), "4/4 (100%)")
        self.assertEqual(self.line("current (gate, level) reads"), "2: attested_passed 1, document_on_file 1")
        self.assertEqual(self.line("DOB job filings (job_status rows)"), "2")
        self.assertEqual(self.line("of them signed off"), "1")
        self.assertEqual(self.line("sign-off dates"), "1 with signoff_date, 0 without")

    def test_the_schedule_numbers(self):
        self.assertEqual(self.line("confirmed schedule on file"), "True")
        self.assertEqual(self.line("activities (non-summary)"), "6")
        self.assertEqual(self.line("carrying the file's predecessor logic"), "6/6 (100%)")
        self.assertEqual(self.line("unresolved links (left out)"), "1")
        self.assertEqual(self.line("mapped to a work package AND a level"), "5/6 (83%)")
        self.assertEqual(self.line("planned in the next 14 days (lookahead items)"), "3")
        self.assertEqual(self.line("proposed sequence"), "approved")

    def test_the_sample_answers_and_the_readiness(self):
        self.assertIn("  drywall on FLOOR_3:", self.out)
        self.assertIn("plumbing rough inspection: passed, reported by a CP, not verified", self.out)
        self.assertIn("firestopping special inspection: sign-off document on file, reported by a PM", self.out)
        for cap, status in (("work_status by level", "ready"), ("photo place re-read", "needs data"),
                            ("photo comparison (relations)", "blocked"), ("verified sign-off (DOB)", "ready"),
                            ("job's own logic", "ready"), ("forecast / estimated dates", "blocked")):
            row = next(ln for ln in self.out.splitlines() if ln.strip().startswith(cap))
            self.assertIn(f"  {status}", row, row)

    def test_no_name_email_phone_or_quote_is_printed(self):
        for text_ in (self.out, self.cov):
            for secret in PEOPLE + ("Plumbing rough passed on 3", "went alright", "didn't pass", "RESULT: APPROVED"):
                self.assertNotIn(secret.lower(), text_.lower(), secret)
        self.assertIn("[withheld]", self.out)

    def test_every_job_in_one_line_each(self):
        lines = self.cov.splitlines()
        self.assertTrue(lines[0].startswith("PROGRESS COVERAGE  1 live jobs"))
        row = next(ln for ln in lines if ln.startswith(P))
        self.assertIn(CO, row)
        self.assertIn("approved", row)
        self.assertIn(f"jobs per company: {CO} 1", self.cov)


if __name__ == "__main__":
    unittest.main()
