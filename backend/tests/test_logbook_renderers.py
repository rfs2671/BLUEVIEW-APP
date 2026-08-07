"""The eight logbook types that rendered a BLANK per-logbook record, the
phantom crew_name, and the admin-only failed-photo count.

WHAT WAS WRONG
  generate_single_logbook_html branched on three log types — daily_jobsite,
  toolbox_talk, preshift_signin. Everything else fell to the `else` and
  emitted one line, "Status: submitted". So the per-logbook HTML/PDF for
  hot_work, crane_operations, excavation_monitoring, concrete_operations,
  scaffold_maintenance, ssc_daily_safety_log, osha_log and
  subcontractor_orientation carried no content at all — a DOB inspector
  opening a hot work permit saw an empty document.

  Separately, that renderer read act.crew_name, a key NOTHING in the repo
  writes. The CP types crew_id (daily_jobsite.jsx EMPTY_ACTIVITY, auto-seeded
  C1/C2/...), which generate_combined_report already read correctly.

WHAT IS ASSERTED
  Per type: the REAL payload keys render, taken from the editor that writes
  them — not from a hand-copied list, and not invented.

  ABSENCE: a key the CP never filled must render NOTHING. Every renderer is
  driven twice, once with a full payload and once with a sparse one, and the
  sparse pass asserts the placeholders ("N/A", "Not recorded", em-dash rows)
  do NOT appear. On a compliance record a placeholder claims the question was
  asked and left blank, which is a different statement than "not captured".

  The admin surface: get_report_preview counts photos stamped
  enhance_status="failed", and still 403s a non-admin.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
#  Harness
# ══════════════════════════════════════════════════════════════════════════

class _ProjectsColl:
    async def find_one(self, *a, **k):
        return {"name": "Test Tower", "address": "1 Test St"}


class _RenderDb:
    projects = _ProjectsColl()


def render(logbook: dict) -> str:
    """Drive the real renderer. Only db.projects is touched by it."""
    with patch.object(server, "db", _RenderDb()):
        return asyncio.run(server.generate_single_logbook_html(logbook))


def doc(log_type: str, data: dict, **overrides) -> dict:
    d = {
        "_id": "lb1",
        "project_id": "proj1",
        "log_type": log_type,
        "date": "2026-08-07",
        "status": "submitted",
        "cp_name": "ada cp",
        "data": data,
    }
    d.update(overrides)
    return d


def body_of(html: str) -> str:
    """Everything between the section title and the footer — the rendered
    RECORD, with the page chrome (header, title, footer) excluded so a
    placeholder assertion cannot be fooled by boilerplate."""
    start = html.find("<tr><td style=\"padding:24px 40px;background-color:#ffffff;\"")
    end = html.find("Generated on")
    return html[start:end] if start >= 0 and end > start else html


# The strings that must NEVER appear for a key the CP did not fill.
PLACEHOLDERS = ["N/A", "Not recorded", "&mdash;", "No data available"]


def assert_no_placeholders(case: unittest.TestCase, html: str, label: str):
    body = body_of(html)
    for p in PLACEHOLDERS:
        case.assertNotIn(
            p, body,
            f"{label}: rendered the placeholder {p!r} for a key the payload "
            f"does not carry — that tells an inspector the CP was asked and "
            f"left it blank.\n{body}",
        )


def assert_not_the_blank_fallback(case: unittest.TestCase, html: str, log_type: str):
    """The old `else` branch emitted exactly one line: Status: <status>."""
    body = body_of(html)
    case.assertNotIn(
        "<strong style=\"color:#0A1929;\">Status:</strong> submitted", body,
        f"{log_type} still falls through to the bare status-line fallback",
    )
    case.assertGreater(
        len(re.sub(r"<[^>]+>", "", body).strip()), 80,
        f"{log_type} rendered almost nothing: {body!r}",
    )


# ══════════════════════════════════════════════════════════════════════════
#  Payloads — the keys the EDITORS write, cited
# ══════════════════════════════════════════════════════════════════════════

# frontend/app/logbooks/hot_work.jsx:189-199 ; PRECAUTION_ITEMS :28-36
HOT_WORK_FULL = {
    "work_type": "Welding",
    "location": "west cellar",
    "worker_name": "bob welder",
    "worker_cert_number": "FDNY-P99-1234",
    "start_time": "08:00",
    "end_time": "12:00",
    "fire_watch_end_time": "12:30",
    "fire_watch_name": "carl watch",
    "precautions": {
        "area_cleared": True,
        "fire_extinguisher_present": True,
        "sprinklers_operational": False,
        "combustibles_covered": True,
        "fire_watch_assigned": True,
        "ventilation_adequate": True,
        "permit_posted": True,
    },
}

# frontend/app/logbooks/crane_operations.jsx:174-181 ; :24-40 ; :42-47
CRANE_FULL = {
    "crane_type": "tower crane",
    "crane_id": "TC-14",
    "operator_name": "dana operator",
    "operator_license": "NYC-CO-8821",
    "pre_operation_checklist": {"wire_ropes": True, "brakes": True, "outriggers": False},
    "load_entries": [
        {"time": "09:15", "description": "steel beam pick", "load_weight": "4200", "radius": "60"},
        {"time": "", "description": "", "load_weight": "", "radius": ""},
    ],
}

# frontend/app/logbooks/excavation_monitoring.jsx:184-194 ; :27-31 ; :180-183
EXCAVATION_FULL = {
    "excavation_depth": "14",
    "soil_type": "Hard Clay",
    "adjacent_buildings": [
        {"address": "12 elm street", "baseline_reading": "0.00",
         "current_reading": "0.35", "delta": "0.35"},
        {"address": "", "baseline_reading": "", "current_reading": "", "delta": ""},
    ],
    "vibration_threshold": "0.50",
    "vibration_current": "0.62",
    "vibration_over_threshold": True,
    "protection_system": "Shoring",
    "groundwater_observed": True,
    "atmospheric_testing": False,
}

# frontend/app/logbooks/concrete_operations.jsx:171-179 ; :26-31 ; :33-37
CONCRETE_FULL = {
    "pour_location": "level 3 slab",
    "concrete_supplier": "ready mix co",
    "mix_design": "4000PSI-A2",
    "volume_ordered": "45",
    "slump_tests": [
        {"time": "10:05", "value": "4.5", "pass": True},
        {"time": "13:40", "value": "6.0", "pass": False},
        {"time": "", "value": "", "pass": None},
    ],
    "formwork_checklist": {"shores_plumb": True, "no_gaps": False},
    "weather_conditions": "Clear",
    "temperature": "68",
}

# frontend/app/logbooks/scaffold_maintenance.jsx:194 ; :27-36 ; :41-61 ; :63
SCAFFOLD_FULL = {
    "general_info": {
        "scaffold_erector": "ace scaffold",
        "renters_name": "hudson builders",
        "permit_number": "SH-2026-114",
        "installation_date": "2026-05-01",
        "expiration_date": "2027-05-01",
        "phone": "212-555-0143",
        "scaffold_height": "48",
        "num_platforms": "3",
        "shed_type": "Heavy",
    },
    "answers": {"signs_on_parapets": "YES", "lights_working": "NO", "deck_clean": "N/A"},
}

# frontend/app/logbooks/ssc_daily_safety_log.jsx:192-206
SSC_FULL = {
    "project_address": "1 test street",
    "ssp_number": "SSP-4471",
    "weather": "Clear",
    "site_conditions": "dry and clear.",
    "safety_violations_observed": "none observed.",
    "corrective_actions_taken": "reset the guardrail.",
    "incidents_reported": True,
    "incident_details": "minor hand laceration.",
    "workers_on_site_count": "37",
    "safety_meetings_held": True,
    "fire_protection_in_place": True,
    "housekeeping_satisfactory": False,
    "ppe_compliance": True,
}

# frontend/app/logbooks/osha_log.jsx:200 ; EMPTY_ENTRY :28-37
OSHA_FULL = {
    "entries": [
        {"worker_id": "w1", "worker_name": "juan perez", "company": "aaz concrete",
         "certification_type": "SST Supervisor", "card_number": "SST-88213",
         "expiration": "2027-03-01", "signed": True, "date": "2026-08-07"},
        {"worker_id": None, "worker_name": "", "company": "",
         "certification_type": "", "card_number": "", "expiration": "", "signed": False},
    ],
}

# frontend/app/logbooks/subcontractor_orientation.jsx:472-483 ; :49-87
# backend/server.py:9900-9912 writes the same field names from the kiosk.
ORIENTATION_FULL = {
    "worker_id": "manual_1",
    "worker_name": "ann worker",
    "worker_company": "hudson builders",
    "worker_trade": "carpenter",
    "osha_number": "SST-55110",
    "orientation_number": "OR-9",
    "checklist": {"hard_hats": True, "fall_protection_required": True, "housekeeping": False},
    "completed_at": "2026-08-07T13:22:04.000Z",
    "worker_signature": None,
    "language_provided": "en",
}


# ══════════════════════════════════════════════════════════════════════════
#  1 — the eight types render their REAL keys
# ══════════════════════════════════════════════════════════════════════════

class EightTypesRenderTest(unittest.TestCase):
    """Each assertion names a value that can ONLY appear if the renderer read
    the key the editor writes. A renderer reading a wrong key renders nothing
    and fails here."""

    def test_hot_work(self):
        html = render(doc("hot_work", HOT_WORK_FULL))
        assert_not_the_blank_fallback(self, html, "hot_work")
        for expect in ("Welding", "West cellar", "Bob welder", "FDNY-P99-1234",
                       "08:00", "12:00", "Carl watch", "12:30",
                       "Area Cleared of Combustibles (35 ft)",
                       "Sprinklers Operational", "Permit Posted at Location"):
            self.assertIn(expect, html, f"hot_work lost {expect!r}")
        # sparse-map semantics: present-and-False is an explicit No.
        self.assertRegex(html, r"Sprinklers Operational</td><td[^>]*>No<")
        # the derived fire-watch time is labelled as the default it is
        self.assertIn("default: work end + 30 min", html)

    def test_crane_operations(self):
        html = render(doc("crane_operations", CRANE_FULL))
        assert_not_the_blank_fallback(self, html, "crane_operations")
        for expect in ("Tower crane", "TC-14", "Dana operator", "NYC-CO-8821",
                       "Wire Ropes Inspected", "Brakes Functional",
                       "Outriggers Deployed", "09:15", "Steel beam pick",
                       "4200", "60"):
            self.assertIn(expect, html, f"crane lost {expect!r}")
        # an untouched EMPTY_LOAD_ENTRY seed is not a lift and is not a row
        self.assertEqual(html.count("<tr><td"), html.count("<tr><td"))
        self.assertNotIn("Load Chart Available", html)   # key absent from the map

    def test_excavation_monitoring(self):
        html = render(doc("excavation_monitoring", EXCAVATION_FULL))
        assert_not_the_blank_fallback(self, html, "excavation_monitoring")
        for expect in ("14", "Hard Clay", "Shoring", "0.50", "0.62",
                       "12 elm street".capitalize(), "0.35", "Over threshold"):
            self.assertIn(expect, html, f"excavation lost {expect!r}")
        # booleans are captured values, so both render
        self.assertIn("Groundwater Observed", html)
        self.assertIn("Atmospheric Testing", html)

    def test_concrete_operations(self):
        html = render(doc("concrete_operations", CONCRETE_FULL))
        assert_not_the_blank_fallback(self, html, "concrete_operations")
        for expect in ("Level 3 slab", "Ready mix co", "4000PSI-A2", "45",
                       "Clear", "68", "10:05", "4.5", "Pass", "13:40", "6.0",
                       "Fail", "Shores Plumb", "No Gaps"):
            self.assertIn(expect, html, f"concrete lost {expect!r}")
        self.assertNotIn("Bracing Adequate", html)       # key absent from the map

    def test_scaffold_maintenance(self):
        html = render(doc("scaffold_maintenance", SCAFFOLD_FULL))
        assert_not_the_blank_fallback(self, html, "scaffold_maintenance")
        for expect in ("Ace scaffold", "Hudson builders", "SH-2026-114",
                       "2026-05-01", "2027-05-01", "212-555-0143", "48", "3",
                       "Heavy", "Are the signs on the parapets?",
                       "Are the lights working?",
                       "Is the deck clean and free of debris?"):
            self.assertIn(expect, html, f"scaffold lost {expect!r}")
        # an N/A the CP CHOSE is a real answer and survives
        self.assertRegex(html, r"Is the deck clean and free of debris\?</td><td[^>]*>N/A<")
        self.assertNotIn("Are pipe clamps tight?", html)  # unanswered

    def test_ssc_daily_safety_log(self):
        html = render(doc("ssc_daily_safety_log", SSC_FULL))
        assert_not_the_blank_fallback(self, html, "ssc_daily_safety_log")
        for expect in ("1 test street".capitalize(), "SSP-4471", "Clear", "37",
                       "Incidents Reported", "PPE Compliance",
                       "Housekeeping Satisfactory", "Dry and clear.",
                       "None observed.", "Reset the guardrail.",
                       "Minor hand laceration."):
            self.assertIn(expect, html, f"ssc lost {expect!r}")
        # the caveat that a rendered No may be an untouched default
        self.assertIn("default to \"No\" if not explicitly set", html)

    def test_osha_log(self):
        html = render(doc("osha_log", OSHA_FULL))
        assert_not_the_blank_fallback(self, html, "osha_log")
        for expect in ("Juan perez", "Aaz concrete", "SST Supervisor",
                       "SST-88213", "2027-03-01"):
            self.assertIn(expect, html, f"osha lost {expect!r}")

    def test_subcontractor_orientation(self):
        html = render(doc("subcontractor_orientation", ORIENTATION_FULL))
        assert_not_the_blank_fallback(self, html, "subcontractor_orientation")
        for expect in ("Ann worker", "Hudson builders", "Carpenter",
                       "SST-55110", "OR-9", "en", "2026-08-07 13:22:04",
                       "Hard hats required at all times on site",
                       "Fall protection required at 6 ft and above",
                       "Keep work area clean at all times"):
            self.assertIn(expect, html, f"orientation lost {expect!r}")
        # worker_signature is written as null on manual entries — an
        # unattested acknowledgment must never read as complete.
        self.assertIn("UNSIGNED", html)
        self.assertNotIn("Inspect harness before each use", html)  # not in map

    def test_kiosk_orientation_checklist_shape_also_renders(self):
        """The kiosk writes {checked, checked_at} and keys the map by the
        item's FULL ENGLISH SENTENCE (backend/checkin.html:674-687,
        1574-1579). Title-casing that key turned a compliance line into
        nonsense, so an unknown sentence key renders verbatim."""
        sentence = "Site-specific hazards and hazardous activities have been reviewed"
        html = render(doc("subcontractor_orientation", {
            "worker_name": "kiosk worker",
            "checklist": {sentence: {"checked": True, "checked_at": "2026-08-07T08:00:00Z"}},
        }))
        self.assertIn(sentence, html)
        self.assertNotIn("Site-Specific Hazards And Hazardous", html)


# ══════════════════════════════════════════════════════════════════════════
#  2 — an ABSENT key renders NOTHING
# ══════════════════════════════════════════════════════════════════════════

SPARSE = {
    # one captured key each, everything else genuinely never filled
    "hot_work": {"work_type": "Cutting"},
    "crane_operations": {"crane_id": "TC-14"},
    "excavation_monitoring": {"soil_type": "Sand"},
    "concrete_operations": {"pour_location": "pier 2"},
    "scaffold_maintenance": {"general_info": {"permit_number": "SH-1"}},
    "ssc_daily_safety_log": {"ssp_number": "SSP-1"},
    "osha_log": {"entries": [{"worker_name": "solo worker"}]},
    "subcontractor_orientation": {"worker_name": "solo worker"},
}


class AbsentKeyRendersNothingTest(unittest.TestCase):

    def test_no_placeholder_for_any_unfilled_key(self):
        for log_type, data in SPARSE.items():
            with self.subTest(log_type=log_type):
                html = render(doc(log_type, data, cp_name=None))
                assert_no_placeholders(self, html, log_type)

    def test_the_one_captured_key_still_renders(self):
        """The absence rule must not be satisfied by rendering nothing at
        all — each sparse payload's single real value is still there."""
        expected = {
            "hot_work": "Cutting",
            "crane_operations": "TC-14",
            "excavation_monitoring": "Sand",
            "concrete_operations": "Pier 2",
            "scaffold_maintenance": "SH-1",
            "ssc_daily_safety_log": "SSP-1",
            "osha_log": "Solo worker",
            "subcontractor_orientation": "Solo worker",
        }
        for log_type, value in expected.items():
            with self.subTest(log_type=log_type):
                self.assertIn(value, render(doc(log_type, SPARSE[log_type], cp_name=None)))

    def test_empty_seed_rows_are_dropped_not_rendered_blank(self):
        """Every row editor seeds one EMPTY_* row. An untouched seed is not a
        record line and must not appear as an empty row."""
        cases = [
            ("crane_operations", {"load_entries": [{"time": "", "description": "",
                                                    "load_weight": "", "radius": ""}]}),
            ("concrete_operations", {"slump_tests": [{"time": "", "value": "", "pass": None}]}),
            ("excavation_monitoring", {"adjacent_buildings": [{"address": "",
                                                               "baseline_reading": "",
                                                               "current_reading": ""}]}),
            ("osha_log", {"entries": [{"worker_name": "", "company": "",
                                       "certification_type": "", "card_number": "",
                                       "expiration": "", "signed": False}]}),
        ]
        for log_type, data in cases:
            with self.subTest(log_type=log_type):
                body = body_of(render(doc(log_type, data, cp_name=None)))
                # A data table always carries header cells; the section title
                # is a <table> with none, so <th matches only a real table.
                self.assertNotIn("<th ", body,
                                 f"{log_type} rendered a table for seed rows only")

    def test_excavation_over_threshold_is_suppressed_without_both_readings(self):
        """The flag is meaningless without a reading — a bare "Within
        threshold" over no measurement is a finding the CP never made."""
        html = render(doc("excavation_monitoring", {
            "vibration_over_threshold": False, "soil_type": "Rock",
        }, cp_name=None))
        self.assertNotIn("Within threshold", html)
        self.assertNotIn("Over threshold", html)

    def test_concrete_null_pass_never_renders_as_fail(self):
        html = render(doc("concrete_operations", {
            "slump_tests": [{"time": "11:00", "value": "5.0", "pass": None}],
        }, cp_name=None))
        self.assertIn("11:00", html)
        self.assertNotIn("Fail", html)
        self.assertNotIn("Pass", html)

    def test_orientation_absent_signature_key_says_nothing(self):
        """Present-and-empty is UNSIGNED. ABSENT is silence — the two are
        different facts about the record."""
        html = render(doc("subcontractor_orientation",
                          {"worker_name": "ann worker"}, cp_name=None))
        self.assertNotIn("UNSIGNED", html)
        self.assertNotIn("Worker Acknowledgment", html)

    def test_the_fallback_branch_still_exists_for_a_genuinely_unknown_type(self):
        """The eight are handled; an unknown type still degrades, it does not
        raise."""
        html = render(doc("some_future_type", {"a": 1}))
        self.assertIn("Some Future Type", html)


# ══════════════════════════════════════════════════════════════════════════
#  3 — crew_id, not the phantom crew_name
# ══════════════════════════════════════════════════════════════════════════

class CrewIdTest(unittest.TestCase):

    DAILY = {
        "weather": "Clear",
        "general_description": "shoring the cellar.",
        "activities": [{
            "crew_id": "C3", "company": "aaz concrete", "num_workers": 6,
            "work_description": "poured slab", "work_locations": "cellar",
        }],
    }

    def test_crew_id_renders(self):
        html = render(doc("daily_jobsite", self.DAILY))
        self.assertIn("C3", html)

    def test_a_document_carrying_only_crew_name_renders_no_crew(self):
        """Proof the reader moved: crew_name has no writer, so a doc that
        somehow carries it must NOT be read."""
        data = dict(self.DAILY)
        data["activities"] = [{**self.DAILY["activities"][0]}]
        data["activities"][0].pop("crew_id")
        data["activities"][0]["crew_name"] = "PHANTOM"
        self.assertNotIn("PHANTOM", render(doc("daily_jobsite", data)))

    def test_no_reader_of_crew_name_is_left_anywhere_in_the_renderers(self):
        """Comments stripped first — the fix is DOCUMENTED in prose next to
        both readers, and a prose mention is not a read."""
        src = Path(server.__file__).read_text(encoding="utf-8")
        code = "\n".join(re.sub(r"#.*$", "", line) for line in src.splitlines())
        self.assertNotIn("crew_name", code,
                         "something in server.py still reads the phantom crew_name")

    def test_combined_report_still_reads_crew_id(self):
        """The reference reader that was already correct must stay correct."""
        src = Path(server.__file__).read_text(encoding="utf-8")
        block_start = src.index("async def generate_combined_report")
        block = src[block_start:]
        self.assertIn('act.get("crew_id"', block)


# ══════════════════════════════════════════════════════════════════════════
#  4 — the admin-only failed-photo count
# ══════════════════════════════════════════════════════════════════════════

class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, *a, **k):
        return list(self._docs)

    def sort(self, *a, **k):
        return self


class _Coll:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    async def find_one(self, *a, **k):
        return self.docs[0] if self.docs else None

    def find(self, *a, **k):
        return _Cursor(self.docs)

    async def count_documents(self, *a, **k):
        return len(self.docs)


class _PreviewDb:
    def __init__(self, logbooks):
        self.projects = _Coll([{"_id": "proj1", "name": "Test Tower",
                                "company_id": "co_a", "report_send_time": "18:00",
                                "report_email_list": []}])
        self.logbooks = _Coll(logbooks)
        self.daily_logs = _Coll([])
        self.checkins = _Coll([])
        self.report_emails = _Coll([])


def photo(status):
    p = {"uri": "file:///cap.jpg", "thumb_base64": "abc"}
    if status:
        p["enhance_status"] = status
        if status == "failed":
            p["enhance_error"] = "R2 upload timed out"
    return p


def logbook_with(photos, log_type="daily_jobsite"):
    return {
        "_id": "lb1", "project_id": "proj1", "log_type": log_type,
        "date": "2026-08-07", "status": "submitted", "cp_name": "Ada CP",
        "cp_signature": {"paths": [[1, 2]]},
        "updated_at": datetime(2026, 8, 7, tzinfo=timezone.utc),
        "data": {"activities": [{"crew_id": "C1", "photos": photos}]},
    }


def preview(logbooks, role="admin", company_id="co_a"):
    db = _PreviewDb(logbooks)
    user = {"_id": "u1", "id": "u1", "role": role, "company_id": company_id,
            "full_name": "Ada Admin", "assigned_projects": ["proj1"]}

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db):
            return TestClient(server.app).get(
                "/api/reports/project/proj1/preview/2026-08-07")
    finally:
        server.app.dependency_overrides.clear()


class FailedPhotoCountTest(unittest.TestCase):

    def test_failed_photos_are_counted_for_an_admin(self):
        resp = preview([logbook_with([photo("done"), photo("failed"), photo("failed")])])
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["failed_photo_count"], 2)
        self.assertEqual(body["logbooks"][0]["failed_photo_count"], 2)

    def test_zero_when_every_photo_enhanced(self):
        resp = preview([logbook_with([photo("done"), photo("done")])])
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["failed_photo_count"], 0)

    def test_a_photo_with_no_enhance_status_is_not_a_failure(self):
        """Pending / never-enhanced is not the same as failed."""
        resp = preview([logbook_with([photo(None), photo("pending")])])
        self.assertEqual(resp.json()["failed_photo_count"], 0)

    def test_counts_sum_across_logbooks(self):
        resp = preview([
            logbook_with([photo("failed")]),
            logbook_with([photo("failed"), photo("done")], log_type="toolbox_talk"),
        ])
        body = resp.json()
        self.assertEqual(body["failed_photo_count"], 2)
        self.assertEqual([lb["failed_photo_count"] for lb in body["logbooks"]], [1, 1])

    def test_a_logbook_with_no_activities_does_not_raise(self):
        lb = logbook_with([])
        lb["data"] = {}
        resp = preview([lb])
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["failed_photo_count"], 0)

    def test_the_endpoint_still_403s_a_non_admin(self):
        for role in ("cp", "worker", "subcontractor"):
            with self.subTest(role=role):
                resp = preview([logbook_with([photo("failed")])], role=role)
                self.assertEqual(resp.status_code, 403, resp.text)
                self.assertNotIn("failed_photo_count", resp.text)

    def test_an_admin_from_another_company_still_403s(self):
        resp = preview([logbook_with([photo("failed")])], company_id="co_b")
        self.assertEqual(resp.status_code, 403, resp.text)
        self.assertNotIn("failed_photo_count", resp.text)


if __name__ == "__main__":
    unittest.main()
