"""THE DEMO IS A STAGE SET, AND A STAGE SET FAILS BY BEING INCONSISTENT.

Sign-up is demo-only. A demo principal sees the real admin screens rendered
from `lib/demo`'s canned payloads: a project, its logbooks, its crew, a day of
check-ins, its DOB record and its plans list. Nothing is saved and nothing real
is ever reachable.

── WHAT ACTUALLY BREAKS A DEMO ─────────────────────────────────────────────

Not a missing field — a missing field renders blank and a prospect reads it as
"not filled in yet". What breaks a demo is the set DISAGREEING WITH ITSELF, in
the places a prospect clicks:

  * a tile says "5 permits" and the list behind it holds four. The count and
    the rows are two screens, and a prospect who taps the tile sees both;
  * a check-in names a worker who is not on the roster, so the row opens onto
    a 404 on the one screen that proves the gate works;
  * the project claims §3310 major_a and the logbook list is missing two of
    the logs that class requires — on a compliance product, that is the
    product failing its own demo;
  * a real worker's name, a real company id, a live tenant's address. That is
    not a broken demo, that is a disclosure.

So the tests below are not "does the dict have the key". They are the four
invariants above, asserted against the dataset itself. They are unit tests with
no database and no network because the dataset has no database and no network —
that closure is itself asserted here (TheSetIsClosedAndPure).

── AND THE SHAPES ARE THE REAL HANDLERS' SHAPES ────────────────────────────

Derived field-for-field from the handler that serves each screen, then asserted
against the real pydantic response models where one exists. A demo payload that
is *nearly* the real shape is worse than an obviously empty one: pydantic drops
undeclared fields silently (the Dropbox outage in ProjectResponse's own comment
is the precedent), so a near-miss reaches the screen as a blank control nobody
can explain.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.example.invalid")

# THE INSERT IS THIS FILE'S OWN. A gate that inherits a sibling's sys.path
# passes only while that sibling is collected first; run alone under CI's
# command it dies on the import.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402
from lib.demo import dataset as demo_dataset  # noqa: E402
from lib.demo import shaping as demo_shaping  # noqa: E402
from lib.demo import (  # noqa: E402
    DEMO_ANCHOR,
    DEMO_CLOSED_DAY_OFFSETS,
    DEMO_COMPANY_ID,
    DEMO_PROJECT_ID,
    demo_checkins,
    demo_dob_logs,
    demo_dob_summary,
    demo_files,
    demo_logbook_by_id,
    demo_logbooks,
    demo_project,
    demo_project_checkins,
    demo_project_list,
    demo_required_logbooks,
    demo_worker,
    demo_worker_certifications,
    demo_workers,
)

#: A day that is not the anchor, used to prove `today` is actually read.
OTHER_DAY = date(2027, 3, 4)


def _walk(value, path="$"):
    """Every (path, scalar) in a nested structure. The scan the disclosure
    tests run over — a denylist that only checks the top level checks nothing,
    because every name in this dataset is nested at least two deep."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(k, f"{path}.<key>")
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple, set)):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, value


def _everything(today=None):
    """The whole served surface, in one structure, for the sweeps below.

    EVERY SHAPING FUNCTION, not the dataset constants — a value that never
    reaches a response cannot leak, and a value the dataset does not hold but a
    shaping function synthesises (a URL, a project name copied onto a row) is
    exactly what a constants-only scan misses.
    """
    return {
        "project": demo_project(today=today),
        "project_list": demo_project_list(today=today),
        "required_logbooks": demo_required_logbooks(today=today),
        "logbooks": demo_logbooks(today=today, limit=500),
        "workers": demo_workers(today=today, limit=500),
        "worker_details": [demo_worker(w["id"], today=today)
                           for w in demo_workers(today=today, limit=500)["items"]],
        "certifications": [demo_worker_certifications(w["id"], today=today)
                           for w in demo_workers(today=today, limit=500)["items"]],
        "checkins": demo_checkins(today=today, limit=500),
        "project_checkins": demo_project_checkins(today=today),
        "dob_logs": demo_dob_logs(today=today, limit=500),
        "dob_summary": demo_dob_summary(today=today),
        "files": demo_files(today=today),
        "dataset": {
            name: getattr(demo_dataset, name)
            for name in dir(demo_dataset)
            if name.isupper()
        },
    }


class ADemoProjectIsTheClassItClaims(unittest.TestCase):
    """§3310 is the one fact on this project that other facts are derived FROM.

    The demo says major_a. If the measurements beside it do not produce
    major_a, then the required-logbook list, the SSC log and the Concrete
    Safety Manager log are all decorations — and a compliance prospect reading
    the storey count is reading the one number he knows how to check.
    """

    def test_the_claimed_class_is_what_the_measurements_produce(self):
        p = demo_project()
        self.assertEqual(
            server.classify_project(
                p.get("building_stories"),
                p.get("footprint_sqft"),
                p.get("has_full_demolition"),
                p.get("demolition_stories"),
                p.get("building_height"),
            ),
            p.get("project_class"),
        )

    def test_the_class_is_one_the_app_recognises(self):
        self.assertIn(demo_project()["project_class"], server.VALID_PROJECT_CLASSES)
        self.assertTrue(server.classification_assessed(demo_project()))

    def test_required_set_is_the_registry_answer_for_this_project(self):
        p = demo_project()
        self.assertEqual(
            demo_required_logbooks()["required_logbooks"],
            server.get_required_logbooks(p["project_class"], p),
        )

    def test_every_required_type_has_a_logbook(self):
        required = set(demo_required_logbooks()["required_logbooks"])
        present = {row["log_type"] for row in demo_logbooks(limit=500)["items"]}
        self.assertEqual(
            required - present, set(),
            "a required log with no entry is a red tile on the demo's own screen",
        )

    def test_every_daily_required_type_is_filed_on_every_closed_day(self):
        """The closed days must look CLOSED. A daily log missing from a day the
        demo presents as finished is the deficiency the product sells against."""
        rows = demo_logbooks(limit=500)["items"]
        daily = server.daily_required_logbooks(
            demo_required_logbooks()["required_logbooks"])
        self.assertTrue(daily, "the fixture proves nothing if nothing is daily")
        for offset in DEMO_CLOSED_DAY_OFFSETS:
            day = (DEMO_ANCHOR + __import__("datetime").timedelta(days=offset)).isoformat()
            filed = {r["log_type"] for r in rows
                     if r["date"] == day and r["status"] == "submitted"}
            self.assertEqual(
                set(daily) - filed, set(),
                f"unfiled daily log(s) on the closed day {day}",
            )

    def test_a_weekly_log_is_not_filed_every_day(self):
        """Filing a weekly talk five times a week is the 588 Thomas defect,
        staged. The demo must not teach it."""
        rows = [r for r in demo_logbooks(limit=500)["items"]
                if server.logbook_frequency(r["log_type"]) == "weekly"]
        self.assertTrue(rows)
        for log_type in {r["log_type"] for r in rows}:
            dates = [r["date"] for r in rows if r["log_type"] == log_type]
            self.assertLessEqual(len(dates), 1, f"{log_type} filed {len(dates)} times")

    def test_some_are_locked_and_some_are_open(self):
        rows = demo_logbooks(limit=500)["items"]
        self.assertTrue([r for r in rows if r["is_locked"]])
        self.assertTrue([r for r in rows if r["status"] == "draft"])

    def test_the_lock_follows_the_freeze_model(self):
        """is_locked is not a decoration: create_logbook computes it as
        (submitted AND immediate). A demo row that locks an end-of-day log
        would show a CP a document he could not have edited that afternoon."""
        for r in demo_logbooks(limit=500)["items"]:
            self.assertEqual(
                r["is_locked"],
                r["status"] == "submitted" and server.is_immediate_preshift(r["log_type"]),
                f"{r['id']} locked wrongly for its timing class",
            )
            self.assertEqual(r["timing_class"], server.logbook_timing_class(r["log_type"]))


class TheSetCrossReferencesItself(unittest.TestCase):
    """Every id is a link a prospect can click. A dangling one is a 404 on the
    screen that was meant to sell the feature."""

    def test_every_checkin_names_a_worker_that_exists(self):
        worker_ids = {w["id"] for w in demo_workers(limit=500)["items"]}
        for c in demo_checkins(limit=500)["items"]:
            self.assertIn(c["worker_id"], worker_ids)

    def test_every_checkin_name_matches_that_worker(self):
        names = {w["id"]: w["name"] for w in demo_workers(limit=500)["items"]}
        for c in demo_checkins(limit=500)["items"]:
            self.assertEqual(c["worker_name"], names[c["worker_id"]])

    def test_every_row_names_the_demo_project(self):
        buckets = [
            demo_logbooks(limit=500)["items"],
            demo_checkins(limit=500)["items"],
            demo_dob_logs(limit=500)["logs"],
        ]
        for rows in buckets:
            for row in rows:
                self.assertEqual(row["project_id"], DEMO_PROJECT_ID)

    def test_the_preshift_roster_names_workers_that_exist(self):
        """The pre-shift sheet's roster is auto-filled from the gate. A name on
        it that is not on the roster means the two screens disagree about who
        was on site."""
        worker_ids = {w["id"] for w in demo_workers(limit=500)["items"]}
        sheets = [r for r in demo_logbooks(limit=500)["items"]
                  if r["log_type"] == "preshift_signin"]
        self.assertTrue(sheets)
        for sheet in sheets:
            roster = sheet["data"].get("workers") or []
            self.assertTrue(roster, f"{sheet['id']} has an empty roster")
            for row in roster:
                self.assertIn(row.get("worker_id"), worker_ids)

    def test_the_certification_read_names_the_same_worker(self):
        for w in demo_workers(limit=500)["items"]:
            cert = demo_worker_certifications(w["id"])
            self.assertEqual(cert["worker_id"], w["id"])
            self.assertEqual(cert["worker_name"], w["name"])

    def test_every_id_in_the_set_is_unique(self):
        ids = []
        for rows, key in (
            (demo_workers(limit=500)["items"], "id"),
            (demo_logbooks(limit=500)["items"], "id"),
            (demo_checkins(limit=500)["items"], "id"),
            (demo_dob_logs(limit=500)["logs"], "id"),
            (demo_files(), "id"),
        ):
            ids.extend(r[key] for r in rows)
        self.assertEqual(len(ids), len(set(ids)))

    def test_at_least_one_certification_expires_soon(self):
        """The expiry surfaces need something to show, and 'soon' has to be
        relative to the caller's today or the demo goes stale on the shelf."""
        soon = []
        for w in demo_workers(limit=500)["items"]:
            for c in demo_worker_certifications(w["id"])["certifications"]:
                exp = c.get("expiration_date")
                if not exp:
                    continue
                days = (datetime.fromisoformat(str(exp)).date() - DEMO_ANCHOR).days
                if 0 < days <= 30:
                    soon.append((w["id"], c["type"], days))
        self.assertTrue(soon, "nothing expires within 30 days of the anchor")

    def test_no_certification_is_flagged_as_badly_entered(self):
        """card_number_finding is rendered in the register's Review column. A
        demo card that trips it puts 'Unexpected card format' in front of a
        prospect."""
        for w in demo_workers(limit=500)["items"]:
            for c in demo_worker_certifications(w["id"])["certifications"]:
                self.assertIsNone(
                    server.card_number_finding(c),
                    f"{w['id']} {c.get('type')} would render a review flag",
                )


class TheCountsAgreeWithTheRows(unittest.TestCase):
    """The tile and the list behind it are one fact shown twice."""

    def test_dob_summary_matches_the_compliance_rows(self):
        summary = demo_project()["dob_summary"]
        rows = demo_dob_logs(limit=500)["logs"]
        census = {}
        for r in rows:
            census[r["record_type"]] = census.get(r["record_type"], 0) + 1
        self.assertEqual(summary["permits"], census.get("permit", 0))
        self.assertEqual(summary["violations"], census.get("violation", 0))
        self.assertEqual(summary["complaints"], census.get("complaint", 0))
        self.assertEqual(summary["inspections"], census.get("inspection", 0))

    def test_the_seeded_counts_are_still_the_seeded_counts(self):
        """The seed the operator agreed to. Stated as literals here so that
        growing the row set has to be a deliberate act on both sides."""
        self.assertEqual(
            demo_project()["dob_summary"],
            {"permits": 5, "violations": 2, "complaints": 1, "inspections": 8},
        )

    def test_the_portfolio_summary_agrees_with_the_same_rows(self):
        """/projects/dob-summary is a SECOND screen over the same records. It
        counts open violations and complaints; the detail rows carry the
        resolution_state it counts on."""
        totals = demo_dob_summary()["totals"]
        by_project = demo_dob_summary()["by_project"][DEMO_PROJECT_ID]
        rows = demo_dob_logs(limit=500)["logs"]
        closed = {"certified", "dismissed", "paid", "resolved"}
        open_v = len([r for r in rows
                      if r["record_type"] in ("violation", "swo")
                      and (r.get("resolution_state") or "open") not in closed])
        self.assertEqual(totals["open_violations"], open_v)
        self.assertEqual(by_project["open_violations"], open_v)
        self.assertEqual(
            by_project["total_violations"],
            len([r for r in rows if r["record_type"] in ("violation", "swo")]),
        )
        self.assertEqual(
            by_project["total_complaints"],
            len([r for r in rows if r["record_type"] == "complaint"]),
        )
        self.assertEqual(totals["projects_total"], 1)

    def test_pagination_totals_equal_the_row_counts(self):
        for envelope in (demo_logbooks(limit=500), demo_workers(limit=500),
                         demo_checkins(limit=500)):
            self.assertEqual(envelope["total"], len(envelope["items"]))
            self.assertFalse(envelope["has_more"])

    def test_a_short_page_reports_more(self):
        page = demo_workers(limit=2)
        self.assertEqual(len(page["items"]), 2)
        self.assertTrue(page["has_more"])
        self.assertEqual(page["total"], demo_workers(limit=500)["total"])

    def test_the_dob_total_is_the_unpaged_total(self):
        page = demo_dob_logs(limit=3)
        self.assertEqual(len(page["logs"]), 3)
        self.assertEqual(page["total"], len(demo_dob_logs(limit=500)["logs"]))


class NothingHereLooksLikeRealData(unittest.TestCase):
    """The disclosure test. Everything below is a pattern a reviewer can check
    at a glance, because 'it looks made up to me' is not a test."""

    #: Strings from the live tenants and from this repo's own production
    #: identity. None of them may appear anywhere in a demo response.
    DENYLIST = (
        "588 thomas", "588 boyland", "857 prescott", "2@2.com",
        "geovany", "baten", "amaury", "abel alvarez", "marcelino",
        "hernandez pena", "cristian",
        "levelog", "blueview", "dropbox.com", "cityofnewyork.us",
    )

    def test_every_id_is_obviously_fake(self):
        for rows, key in (
            (demo_workers(limit=500)["items"], "id"),
            (demo_logbooks(limit=500)["items"], "id"),
            (demo_checkins(limit=500)["items"], "id"),
            (demo_dob_logs(limit=500)["logs"], "id"),
            (demo_files(), "id"),
        ):
            for r in rows:
                self.assertTrue(
                    str(r[key]).startswith("demo-"),
                    f"id {r[key]!r} is not visibly a demo id",
                )
        self.assertEqual(demo_project()["id"], "demo")
        self.assertEqual(demo_project()["company_id"], DEMO_COMPANY_ID)

    def test_every_company_id_is_the_demo_company(self):
        for path, value in _walk(_everything()):
            if path.endswith(".company_id") and value is not None:
                self.assertEqual(value, DEMO_COMPANY_ID, f"at {path}")

    def test_every_email_is_a_reserved_domain(self):
        found = []
        for path, value in _walk(_everything()):
            if isinstance(value, str) and "@" in value and " " not in value:
                found.append((path, value))
                self.assertTrue(
                    value.endswith("@example.invalid"),
                    f"{value!r} at {path} is not a reserved address",
                )
        self.assertTrue(found, "no address at all — the sweep proves nothing")

    def test_every_phone_is_in_the_fictional_block(self):
        import re
        found = []
        for path, value in _walk(_everything()):
            if path.endswith(".phone") and value:
                found.append(value)
                self.assertRegex(
                    str(value), r"^\+1\d{3}55501\d{2}$",
                    f"{value!r} at {path} is outside the 555-01xx block",
                )
        self.assertTrue(found)

    def test_no_live_tenant_string_appears_anywhere(self):
        for path, value in _walk(_everything()):
            if not isinstance(value, str):
                continue
            low = value.lower()
            for token in self.DENYLIST:
                self.assertNotIn(token, low, f"{token!r} found at {path}")

    def test_the_crew_is_the_frozen_fictional_roster(self):
        """Frozen so that adding a worker is a deliberate act with a reviewer
        on it — which is the only moment a real name gets in."""
        self.assertEqual(
            sorted(w["name"] for w in demo_workers(limit=500)["items"]),
            sorted([
                "Andre Whitfield",
                "Ana Sotelo",
                "Devon Clarke",
                "Kwame Boateng",
                "Luis Ferreira",
                "Piotr Nowak",
            ]),
        )

    def test_every_company_name_says_demo(self):
        for path, value in _walk(_everything()):
            if path.endswith(".company") or path.endswith(".company_name"):
                if value:
                    self.assertIn("Demo", str(value), f"at {path}")

    def test_the_payload_says_it_is_a_demo(self):
        self.assertIs(demo_project()["is_demo"], True)
        self.assertIn("demo", demo_project()["note"].lower())

    def test_no_row_carries_a_real_image_or_object(self):
        """Nothing in a closed set may hold a base64 card photo or an R2 key:
        both are real artefacts and neither can be served from fiction."""
        for path, value in _walk(_everything()):
            self.assertFalse(path.endswith(".r2_key"), f"an R2 key at {path}")
            if path.endswith(".osha_card_image"):
                self.assertIsNone(value, f"a card image at {path}")
            if isinstance(value, str):
                self.assertNotIn("data:image", value, f"embedded image at {path}")


class TheShapesAreTheHandlersShapes(unittest.TestCase):
    """Each payload validated against the model the real handler returns."""

    def test_the_project_validates_against_project_response(self):
        model = server.ProjectResponse(**demo_project())
        self.assertEqual(model.id, DEMO_PROJECT_ID)
        self.assertEqual(model.project_class, "major_a")
        self.assertEqual(model.nyc_bin, "2115914")

    def test_the_project_list_row_validates_too(self):
        items = demo_project_list()["items"]
        self.assertEqual(len(items), 1)
        server.ProjectResponse(**items[0])
        self.assertIn("defcon_tier", items[0])

    def test_workers_validate_against_worker_response(self):
        for w in demo_workers(limit=500)["items"]:
            server.WorkerResponse(**demo_worker(w["id"]))

    def test_the_worker_list_row_carries_only_the_list_fields(self):
        """The list endpoint projects — it does not carry the card image, the
        signature, the certifications or the OSHA data. A demo row that does
        would be the only place in the app where a list row holds them."""
        allowed = {"id", "name", "phone", "company", "trade", "company_id",
                   "status", "is_deleted", "created_at", "updated_at"}
        for row in demo_workers(limit=500)["items"]:
            self.assertEqual(set(row) - allowed, set())

    def test_the_nested_project_rows_validate_against_their_models(self):
        """ProjectResponse declares `gates` and `trade_assignments` as bare
        `List[Dict]`, so pydantic validates NOTHING inside them — which is
        exactly how this demo first carried gates keyed {id, name, tag_id} while
        the app's own `ProjectGate` is {gate_id, label, lat, lng}. A gate row
        keyed differently is a gate /checkin/{project_id}/{gate_id} cannot open,
        and the model that would have said so is never reached from the
        response. So it is reached from here.
        """
        project = demo_project()
        for gate in project["gates"]:
            model = server.ProjectGate(**gate)
            self.assertEqual(model.gate_id, gate["gate_id"])
            self.assertEqual(set(gate), {"gate_id", "label", "lat", "lng"})
        for row in project["trade_assignments"]:
            server.TradeAssignment(**row)

    def test_a_safety_orientation_row_is_the_shape_the_gate_writes(self):
        """`register_and_checkin` writes {project_id, project_name, checklist,
        completed_at}, and `completed_at` is `now.isoformat()` — a STRING. A
        datetime there reads correctly in Python and breaks every client that
        slices ten characters off it."""
        for w in demo_workers(limit=500)["items"]:
            rows = demo_worker(w["id"])["safety_orientations"]
            self.assertTrue(rows)
            for row in rows:
                self.assertEqual(
                    set(row),
                    {"project_id", "project_name", "checklist", "completed_at"})
                self.assertEqual(row["project_id"], DEMO_PROJECT_ID)
                self.assertIsInstance(row["completed_at"], str)
                self.assertIsInstance(row["checklist"], dict)

    def test_the_instant_fields_that_are_datetimes_really_are(self):
        """The other half of the same rule. These are datetimes in Mongo, and a
        string here would be a second, quieter version of the bug above."""
        self.assertIsInstance(demo_project()["created_at"], datetime)
        for row in demo_dob_logs(limit=500)["logs"]:
            self.assertIsInstance(row["detected_at"], datetime)
        for row in demo_checkins(limit=500)["items"]:
            self.assertIsInstance(row["check_in_time"], datetime)
        combined = [f for f in demo_files() if f["index_status"]]
        self.assertTrue(combined)
        self.assertIsInstance(combined[0]["index_status"]["at"], datetime)

    def test_the_orientation_sheet_and_the_roster_record_one_event(self):
        """Devon Clarke's orientation exists twice — as his own sheet and as the
        row on his worker document. Two copies of one attendance that disagree
        are two answers to whether the man was oriented."""
        sheet = [r for r in demo_logbooks(limit=500)["items"]
                 if r["log_type"] == "subcontractor_orientation"][0]
        worker = demo_worker(sheet["data"]["worker_id"])
        self.assertEqual(sheet["data"]["worker_name"], worker["name"])
        self.assertEqual(sheet["data"]["checklist"],
                         worker["safety_orientations"][0]["checklist"])

    def test_checkins_validate_against_checkin_response(self):
        for c in demo_checkins(limit=500)["items"]:
            server.CheckInResponse(**c)

    def test_the_project_checkin_list_is_a_bare_list_with_a_trade(self):
        rows = demo_project_checkins()
        self.assertIsInstance(rows, list)
        for r in rows:
            self.assertIn("worker_trade", r)

    def test_dob_rows_validate_against_dob_log_response(self):
        for row in demo_dob_logs(limit=500)["logs"]:
            server.DOBLogResponse(**row)

    def test_the_dob_envelope_is_the_handlers_envelope(self):
        payload = demo_dob_logs()
        self.assertEqual(
            set(payload),
            {"project_id", "project_name", "nyc_bin", "track_dob_status",
             "total", "logs"},
        )

    def test_list_endpoints_return_the_pagination_envelope(self):
        for envelope in (demo_logbooks(), demo_workers(), demo_checkins(),
                         demo_project_list()):
            self.assertEqual(
                set(envelope), {"items", "total", "limit", "skip", "has_more"})

    def test_required_logbooks_envelope_matches_the_handler(self):
        self.assertEqual(
            set(demo_required_logbooks()),
            {"project_id", "project_class", "classification_assessed",
             "required_logbooks", "activations", "filing", "periods"},
        )

    def test_the_activations_are_the_registry_activations(self):
        self.assertEqual(
            demo_required_logbooks()["activations"],
            server.logbook_activations(demo_project()),
        )

    def test_files_are_a_bare_list_with_the_row_keys(self):
        rows = demo_files()
        self.assertIsInstance(rows, list)
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(
                set(r),
                {"name", "path", "id", "type", "size", "modified", "r2_url",
                 "cache_version", "source", "index_status"},
            )

    def test_a_logbook_row_carries_what_the_editors_read(self):
        for r in demo_logbooks(limit=500)["items"]:
            for key in ("id", "project_id", "project_name", "company_id",
                        "log_type", "date", "data", "status", "is_locked",
                        "timing_class", "instance_seq", "cp_name",
                        "created_by", "created_at", "updated_at", "is_deleted"):
                self.assertIn(key, r, f"{r['id']} missing {key}")

    def test_a_single_logbook_read_returns_the_same_row(self):
        first = demo_logbooks(limit=500)["items"][0]
        self.assertEqual(demo_logbook_by_id(first["id"]), first)

    def test_an_unknown_id_is_not_invented(self):
        self.assertIsNone(demo_logbook_by_id("demo-log-does-not-exist"))
        self.assertIsNone(demo_worker("demo-worker-99"))

    def test_the_filters_the_handler_offers_actually_filter(self):
        rows = demo_logbooks(limit=500)["items"]
        a_type = rows[0]["log_type"]
        a_date = rows[0]["date"]
        by_type = demo_logbooks(log_type=a_type, limit=500)["items"]
        self.assertTrue(by_type)
        self.assertTrue(all(r["log_type"] == a_type for r in by_type))
        by_date = demo_logbooks(date=a_date, limit=500)["items"]
        self.assertTrue(by_date)
        self.assertTrue(all(r["date"] == a_date for r in by_date))


class TheSetIsClosedAndPure(unittest.TestCase):
    """No database, no network, no clock. Asserted over the module's AST rather
    than its text, so a comment explaining the rule cannot satisfy the rule."""

    def _modules(self):
        import lib.demo as pkg
        return [Path(pkg.__file__),
                Path(demo_dataset.__file__),
                Path(demo_shaping.__file__)]

    def test_the_module_never_asks_the_clock(self):
        for path in self._modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    src = ast.unparse(node.func)
                    self.assertNotIn(
                        src, ("datetime.now", "datetime.utcnow", "date.today",
                              "time.time", "datetime.datetime.now"),
                        f"{path.name} reads the clock at line {node.lineno}",
                    )

    def test_the_module_imports_nothing_that_does_io(self):
        banned = ("motor", "pymongo", "httpx", "requests", "boto3", "server",
                  "aiohttp", "urllib")
        for path in self._modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    self.assertNotIn(
                        name.split(".")[0], banned,
                        f"{path.name} imports {name}",
                    )

    def test_nothing_is_async(self):
        """A coroutine here would mean somebody expects it to await something,
        and there is nothing in a closed set to await."""
        for path in self._modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                self.assertNotIsInstance(node, ast.AsyncFunctionDef)

    def test_same_today_gives_the_same_answer(self):
        self.assertEqual(_everything(OTHER_DAY), _everything(OTHER_DAY))

    def test_a_different_today_moves_the_dates(self):
        """Proves `today` is READ. A dataset that ignores it would pass every
        other test in this file and show a prospect a three-month-old day."""
        anchored = demo_logbooks(today=DEMO_ANCHOR, limit=500)["items"]
        moved = demo_logbooks(today=OTHER_DAY, limit=500)["items"]
        self.assertNotEqual(sorted(r["date"] for r in anchored),
                            sorted(r["date"] for r in moved))
        # THE SET, NOT THE SEQUENCE. The weekly talk lands on the Monday of the
        # viewer's own week, so which day it shares with the daily logs — and
        # therefore where it sorts — depends on the weekday being viewed. The
        # documents are the same documents; only their dates moved.
        self.assertEqual(sorted(r["log_type"] for r in anchored),
                         sorted(r["log_type"] for r in moved))

    def test_the_default_today_is_the_anchor(self):
        self.assertEqual(demo_logbooks(), demo_logbooks(today=DEMO_ANCHOR))

    def test_a_caller_cannot_mutate_the_canned_set(self):
        """Every response is built fresh. A shared nested dict handed to a
        route would let one request's serialiser edit the next request's."""
        first = demo_project()
        first["name"] = "mutated"
        first["dob_summary"]["permits"] = 999
        self.assertNotEqual(demo_project()["name"], "mutated")
        self.assertEqual(demo_project()["dob_summary"]["permits"], 5)



if __name__ == "__main__":
    unittest.main()
