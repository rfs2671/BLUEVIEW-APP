"""SUBMIT_INVALID_DATE — a date field on a FILED log holds a date, or nothing.

THE DEFECT THIS CLOSES was silent. `DateField` handed the stepper `''` for
anything that was not yet a real calendar day, so a CP who typed `13/45/2029`
or stopped at `07/2` saw his text and an error on screen while the RECORD kept
nothing — and a field that already held a good `2029-07-21` was blanked by an
edit he never finished. The log then filed, signed, with a date that reads as
"never recorded".

THE TWO HALVES, and they answer different moments:

  KEPT      the stepper now stores what he typed. Nothing is discarded and no
            good value is overwritten. That half is frontend/src/utils/
            dateEntry.js and dateInput/DateField; its gates are
            dateEntry.test.cjs, logbookDateGate.test.cjs and
            scripts/date-input-behaviour.cjs.
  REFUSED   a SUBMIT carrying a non-empty date that is not a real ISO date is
            refused here, naming the field and quoting the value. Filing is
            the moment a draft becomes a legal record, so that is where the
            refusal belongs; mid-entry the stepper keeps marking rather than
            blocking, so a CP on site is never trapped in a field.

WHICH FIELDS ARE DATES IS DERIVED, NOT LISTED. `lib/legal_render/schema.py`
declares every field with a formatter, and the four typed date fields now name
`date_as_filed` / `date_as_filed_raw` beside the log date's `date_long`. The
gate walks that declaration, so a fifth date field is gated by being declared
-- a hand list in server.py would go stale the day someone adds one.

WHAT THIS GATE IS NOT:

  NOT A COMPLETENESS RULE. Empty passes. `finalize_logbook` rules that
  per-field completeness "belongs to the editors, not to the lock" and that
  stands: this is about a value being WRONG, not about one being missing.
  There are assertions below that an empty and an absent date both file.
  NOT A MIGRATION. An already-filed record holding free text is untouched and
  still renders; the gate applies to a SUBMIT, never to a read or a render.
  There is an assertion below that renders one.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from lib.legal_render import schema as _schema  # noqa: E402
from tests.filed_sheet import logbook as _filed_logbook, render as _render_sheet  # noqa: E402

_FRONTEND = (_BACKEND / ".." / "frontend").resolve()

# The three forms that render DateField, and the field each one binds. Read off
# the JSX at frontend/app/logbooks/*.jsx; asserted against the declaration
# below rather than trusted, because this list is the thing that goes stale.
EXPECTED_TYPED_DATE_FIELDS = {
    "fall_protection": {"data.activities[].manufacture_date"},
    "osha_log": {"data.entries[].expiration"},
    "scaffold_maintenance": {"data.general_info.installation_date",
                             "data.general_info.expiration_date"},
}

_SIG = {"paths": [[1, 2]], "signed_at": "2026-09-09T12:00:00Z",
        "affirmed": True, "affirmedAt": "2026-09-09T12:00:00Z"}


# ── the fake db and the two endpoints, borrowed from the sibling gate ────────
#
# IMPORTED, NOT COPIED. test_submit_requires_signature.py drives the same two
# endpoints with the same fake collection; a second copy of that harness is a
# second thing to keep true about create_logbook. Only helpers are imported --
# no TestCase -- so nothing of that file is collected twice.
from tests.test_submit_requires_signature import (  # noqa: E402
    _FakeDb, _db_for_create, _db_for_update, _post, _put, _user,
)


def _create_body(log_type, data, *, status="submitted", date="2026-09-09"):
    return {
        "project_id": "proj1", "log_type": log_type, "date": date,
        "data": data, "cp_signature": _SIG, "cp_name": "Carl CP",
        "status": status,
    }


def _stored(log_type, data, **extra):
    doc = {
        "_id": "lb1", "project_id": "proj1", "log_type": log_type,
        "date": "2026-09-09", "data": data, "cp_signature": _SIG,
        "cp_name": "Carl CP", "is_locked": False, "status": "draft",
    }
    doc.update(extra)
    return doc


def _fall(date_value):
    """A fall-protection register whose one row would really be filed."""
    return {"activities": [{"worker_name": "WILMER CARRILLO", "result": "Pass",
                            "manufacture_date": date_value}]}


def _osha(date_value):
    return {"entries": [{"worker_name": "WILMER CARRILLO", "company": "aaz",
                         "certification_type": "SST", "card_number": "1111",
                         "expiration": date_value}]}


def _scaffold(date_value, key="installation_date"):
    return {"general_info": {"scaffold_erector": "aaz", key: date_value},
            "answers": {"signs_on_parapets": "yes"}}


# ══ 1. THE POPULATION COMES FROM THE DECLARATION ════════════════════════════

class TheDateFieldsAreDeclaredNotListed(unittest.TestCase):
    """A hand list in server.py goes stale the day a fourth date field is
    added to a form. The schema already says which fields are dates."""

    def test_the_typed_date_fields_are_the_ones_the_forms_bind(self):
        for log_type, paths in EXPECTED_TYPED_DATE_FIELDS.items():
            with self.subTest(log_type=log_type):
                declared = {f["path"] for f in _schema.date_fields(log_type)}
                self.assertTrue(
                    paths <= declared,
                    f"{log_type}: {paths - declared} is bound to a DateField on "
                    f"the screen and is not declared a date on the sheet")

    def test_the_log_date_is_gated_wherever_the_sheet_declares_it(self):
        """`("date", "Date", "date_long")` is the log's own day, and it is a
        date by the SAME declaration -- so it is gated by the same walk rather
        than by an exception for it.

        THE CENSUS IS 11 OF 13, AND THE TWO ARE NAMED. The OSHA register and
        the scaffold maintenance sheet declare no log date at all: neither
        prints one, so there is nothing on those sheets to gate. That is their
        declaration's business, not this gate's -- and the day either sheet
        prints its date, this walk gates it with no change here. Asserted so
        the gap is a recorded fact rather than a surprise.
        """
        declares = {t for t in _schema.SCHEMAS
                    if "date" in {f["path"] for f in _schema.date_fields(t)}}
        self.assertEqual(set(_schema.SCHEMAS) - declares,
                         {"osha_log", "scaffold_maintenance"})
        self.assertEqual(len(declares), 11)

    def test_no_date_field_hides_in_a_scope_the_walk_does_not_read(self):
        """THE WALK'S OWN BLIND SPOT, ASSERTED. `date_fields` reads the
        record's scopes (`first`, `each`, `rows`); a date declared under
        `project` or `context` belongs to another document and would be
        skipped in silence."""
        for log_type, decl in sorted(_schema.SCHEMAS.items()):
            for sec in decl["sections"]:
                if sec.get("scope") not in ("project", "context"):
                    continue
                for _p, label, fmt in (
                        (sec.get("fields") or []) + (sec.get("columns") or [])):
                    self.assertNotIn(
                        fmt, _schema.DATE_FORMATTERS,
                        f"{log_type}: {label!r} is a date in scope "
                        f"{sec.get('scope')!r}, which date_fields does not read")

    def test_a_date_formatter_prints_exactly_what_text_prints(self):
        """The new names are a DECLARATION, not a new rendering. The shed
        permit dates are read against a DOB permit and the word-level diff
        guarding the conversion cannot see digits, so a reformat here would be
        the one change on the sheet no check could catch."""
        from lib.legal_render.formatters import FORMATTERS
        for value in ["2029-07-21", "8/12", "", None, "<b>x</b>", "   "]:
            with self.subTest(value=value):
                self.assertEqual(FORMATTERS["date_as_filed"](value),
                                 FORMATTERS["text"](value))
                self.assertEqual(FORMATTERS["date_as_filed_raw"](value),
                                 FORMATTERS["raw_text"](value))

    def test_the_client_mirror_names_the_same_fields(self):
        """THE PRE-FLIGHT MUST AGREE WITH THE GATE. The device cannot read
        this schema, so frontend/src/utils/logbookDateGate.js repeats the
        population as data -- and a mirror nothing compares is a mirror that
        drifts. Same claim as MAINTENANCE_QUESTIONS being asserted key for
        key against the renderer's copy."""
        src = (_FRONTEND / "src" / "utils" / "logbookDateGate.js").read_text(
            encoding="utf-8")
        # The declaration is DATA -- `{ container, key, labelKey }` entries
        # under a log type -- so it is read with a scanner rather than parsed.
        import re
        blocks = re.findall(
            r"^  (\w+):\s*\[(.*?)^  \],", src, re.S | re.M)
        self.assertTrue(blocks, "no LOGBOOK_DATE_FIELDS entries found")
        mirror = {}
        for log_type, body in blocks:
            body = re.sub(r"//[^\n]*", "", body)
            entries = set()
            for container, key in re.findall(
                    r"container:\s*'([^']*)'.*?key:\s*'([^']+)'", body, re.S):
                entries.add(f"data.{container}[].{key}" if container
                            else f"data.{key}")
            mirror[log_type] = entries
        for log_type, entries in mirror.items():
            with self.subTest(log_type=log_type):
                declared = {f["path"] for f in _schema.date_fields(log_type)
                            if f["path"] != "date"}
                self.assertEqual(
                    entries, declared,
                    f"{log_type}: the client's pre-flight and the server's gate "
                    f"disagree about which fields are dates")
        self.assertEqual(set(mirror), set(EXPECTED_TYPED_DATE_FIELDS))


# ══ 2. WHAT THE GATE ANSWERS, AS A FUNCTION ═════════════════════════════════

class TheGateNamesTheFieldAndQuotesTheValue(unittest.TestCase):

    def test_a_half_typed_date_is_refused_and_quoted(self):
        d = server._submit_invalid_date_detail(
            "fall_protection", _fall("07/2"), "2026-09-09")
        self.assertIsNotNone(d)
        self.assertEqual(d["code"], "SUBMIT_INVALID_DATE")
        self.assertEqual(d["value"], "07/2")
        self.assertEqual(d["field"], "Mfg Date")
        self.assertEqual(d["row"], 1)
        self.assertEqual(d["path"], "data.activities.0.manufacture_date")

    def test_an_impossible_date_is_refused_on_every_form(self):
        for log_type, payload in (
                ("fall_protection", _fall("13/45/2029")),
                ("osha_log", _osha("13/45/2029")),
                ("scaffold_maintenance", _scaffold("13/45/2029")),
                ("scaffold_maintenance", _scaffold("13/45/2029",
                                                   "expiration_date")),
        ):
            with self.subTest(log_type=log_type, payload=payload):
                d = server._submit_invalid_date_detail(
                    log_type, payload, "2026-09-09")
                self.assertIsNotNone(d, f"{log_type} filed 13/45/2029")
                self.assertEqual(d["value"], "13/45/2029")
                self.assertTrue(d["field"], "the refusal names no field")

    def test_legacy_free_text_is_refused_by_the_same_rule(self):
        """An unfiled draft from before the shared field may hold '8/12'. It
        cannot be FILED until it is corrected -- which is the ruling for a
        legal record -- and the refusal quotes it so he knows what to fix."""
        d = server._submit_invalid_date_detail(
            "scaffold_maintenance", _scaffold("8/12"), "2026-09-09")
        self.assertIsNotNone(d)
        self.assertEqual(d["value"], "8/12")
        self.assertEqual(d["field"], "Installation Date")

    def test_a_real_iso_date_passes(self):
        for log_type, payload in (
                ("fall_protection", _fall("2024-03-11")),
                ("osha_log", _osha("2027-03-01")),
                ("scaffold_maintenance", _scaffold("2026-01-31")),
        ):
            with self.subTest(log_type=log_type):
                self.assertIsNone(server._submit_invalid_date_detail(
                    log_type, payload, "2026-09-09"))

    def test_a_date_that_is_shaped_like_iso_but_is_not_a_day_is_refused(self):
        """`2029-02-30` and `2027-02-29` pass a regex and are not days. The
        arithmetic is the same rule the field applies on the device."""
        for bad in ["2029-02-30", "2027-02-29", "2029-13-01", "2029-00-10",
                    "2029-07-00", "2029-07-32"]:
            with self.subTest(bad=bad):
                self.assertIsNotNone(server._submit_invalid_date_detail(
                    "fall_protection", _fall(bad), "2026-09-09"))
        # And the leap day that IS a day.
        self.assertIsNone(server._submit_invalid_date_detail(
            "fall_protection", _fall("2028-02-29"), "2026-09-09"))

    def test_the_year_bound_is_the_field_s_own(self):
        """THE CLIENT AND THE SERVER AGREE, or the pre-flight passes a value
        the gate refuses and the CP meets a refusal his screen called fine.
        dateEntry.js bounds a typed year to 1900-2199 (the bound that makes a
        bare run of eight digits unambiguous); this is that bound."""
        self.assertEqual(
            (server.LOGBOOK_DATE_MIN_YEAR, server.LOGBOOK_DATE_MAX_YEAR),
            (1900, 2199))
        for bad in ["1899-12-31", "2200-01-01", "0229-07-21"]:
            with self.subTest(bad=bad):
                self.assertIsNotNone(server._submit_invalid_date_detail(
                    "fall_protection", _fall(bad), "2026-09-09"))
        for good in ["1900-01-01", "2199-12-31"]:
            with self.subTest(good=good):
                self.assertIsNone(server._submit_invalid_date_detail(
                    "fall_protection", _fall(good), "2026-09-09"))

    def test_empty_and_absent_both_pass(self):
        """THIS GATE IS ABOUT WRONG, NOT MISSING. A manufacture date nobody
        could read off a harness label is legitimately blank, and completeness
        belongs to the editors."""
        for value in ["", "   ", None]:
            with self.subTest(value=value):
                self.assertIsNone(server._submit_invalid_date_detail(
                    "fall_protection", _fall(value), "2026-09-09"))
        no_key = {"activities": [{"worker_name": "WILMER CARRILLO",
                                  "result": "Pass"}]}
        self.assertIsNone(server._submit_invalid_date_detail(
            "fall_protection", no_key, "2026-09-09"))

    def test_a_row_the_sheet_would_not_print_is_not_gated(self):
        """`row_requires` drops a row that names nobody, so its date never
        reaches the document. Refusing a submit over a seed row the CP cannot
        see is a dead end -- the same reason the no-content gate reads the
        renderer's own rule."""
        seeded = {"activities": [{"worker_name": "", "manufacture_date": "07/2"},
                                 {"worker_name": "WILMER CARRILLO",
                                  "result": "Pass"}]}
        self.assertIsNone(server._submit_invalid_date_detail(
            "fall_protection", seeded, "2026-09-09"))

    def test_the_log_s_own_date_is_gated_too(self):
        self.assertIsNotNone(server._submit_invalid_date_detail(
            "fall_protection", _fall("2024-03-11"), "8/12"))

    def test_an_ungated_type_and_a_malformed_body_are_declined(self):
        """A type this walk knows nothing about passes through unchanged, and a
        body that is not a dict is SUBMIT_EMPTY_LOG's business -- the ordering
        every other submit gate keeps."""
        self.assertIsNone(server._submit_invalid_date_detail(
            "no_such_log_type", _fall("07/2"), "07/2"))
        for payload in [None, [], "x", 3]:
            with self.subTest(payload=payload):
                self.assertIsNone(server._submit_invalid_date_detail(
                    "fall_protection", payload, "2026-09-09"))

    def test_a_value_that_is_not_a_string_is_refused_not_crashed(self):
        for weird in [{"a": 1}, ["2029-07-21"], 20290721, True]:
            with self.subTest(weird=weird):
                self.assertIsNotNone(server._submit_invalid_date_detail(
                    "fall_protection", _fall(weird), "2026-09-09"))

    def test_the_quoted_value_cannot_be_a_wall_of_text(self):
        """It is rendered in a toast on a 443px phone. Quoted, and bounded."""
        d = server._submit_invalid_date_detail(
            "fall_protection", _fall("x" * 500), "2026-09-09")
        self.assertIsNotNone(d)
        self.assertLessEqual(len(d["value"]), 64)

    def test_every_offending_field_is_listed_not_only_the_first(self):
        payload = _scaffold("07/2")
        payload["general_info"]["expiration_date"] = "13/45/2029"
        d = server._submit_invalid_date_detail(
            "scaffold_maintenance", payload, "2026-09-09")
        self.assertEqual(len(d["fields"]), 2)
        self.assertEqual({f["value"] for f in d["fields"]},
                         {"07/2", "13/45/2029"})


# ══ 3. THE ENDPOINTS: A SUBMIT IS REFUSED, A DRAFT IS NOT ═══════════════════

class FilingIsWhereItIsRefused(unittest.TestCase):

    def test_create_refuses_a_submit_and_writes_nothing(self):
        db = _db_for_create()
        resp = _post(db, _create_body("fall_protection", _fall("13/45/2029")))
        self.assertEqual(resp.status_code, 400, resp.text)
        detail = resp.json()["detail"]
        self.assertEqual(detail["code"], "SUBMIT_INVALID_DATE")
        self.assertEqual(detail["value"], "13/45/2029")
        self.assertEqual(detail["field"], "Mfg Date")
        self.assertEqual(db.logbooks.inserted, [],
                         "a refused submit must not insert")
        self.assertEqual(db.logbooks.updated, [],
                         "a refused submit must not update")

    def test_create_accepts_the_same_log_as_a_DRAFT(self):
        """MID-ENTRY HE IS NEVER BLOCKED. The steppers mark an unfinished step
        and never gate it; a draft is exactly that state persisted."""
        db = _db_for_create()
        resp = _post(db, _create_body("fall_protection", _fall("13/45/2029"),
                                      status="draft"))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(db.logbooks.inserted), 1)
        self.assertEqual(
            db.logbooks.inserted[0]["data"]["activities"][0]["manufacture_date"],
            "13/45/2029",
            "the draft must keep what he typed -- that is the other half")

    def test_update_refuses_the_path_the_CP_actually_walks(self):
        """Save Draft then Submit arrives as a PUT. A gate on create alone
        would never see it."""
        db = _db_for_update(_stored("scaffold_maintenance", _scaffold("8/12")))
        resp = _put(db, {"status": "submitted"})
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "SUBMIT_INVALID_DATE")
        self.assertEqual(resp.json()["detail"]["value"], "8/12")
        self.assertEqual(db.logbooks.updated, [],
                         "a refused submit must not update")

    def test_update_judges_the_EFFECTIVE_data_not_only_the_request(self):
        """A submit that patches only `status` must be judged on what is
        stored -- and a submit that carries corrected data must pass over a
        stored value that was bad."""
        db = _db_for_update(_stored("osha_log", _osha("07/2")))
        resp = _put(db, {"status": "submitted",
                         "data": _osha("2027-03-01")})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_update_accepts_a_draft_save_carrying_a_half_typed_date(self):
        db = _db_for_update(_stored("osha_log", _osha("")))
        resp = _put(db, {"status": "draft", "data": _osha("07/2")})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_an_amendment_passes_through_the_same_gate(self):
        """A re-submit of a correction is a submit. The amendment child is an
        ordinary editable logbook, so it arrives at this same PUT."""
        child = _stored("fall_protection", _fall("07/2"),
                        is_amendment=True, parent_logbook_id="lb0",
                        amendment_reason="the date was transcribed wrong")
        db = _db_for_update(child)
        resp = _put(db, {"status": "submitted"})
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "SUBMIT_INVALID_DATE")

    def test_finalize_refuses_the_lock_too(self):
        """Finalize is the other way a draft becomes immutable: it sets
        `status: submitted` itself. A gate on the submit endpoints alone would
        leave the CP's own Finalize as the way around it."""
        db = _FakeDb()
        db.projects.set_find_one(lambda q: {"_id": "proj1", "name": "8 W"})
        db.logbooks.set_find_one(
            lambda q: _stored("fall_protection", _fall("07/2")))

        async def _fake_user():
            return _user("cp")

        server.app.dependency_overrides[server.get_current_user] = _fake_user
        try:
            with patch.object(server, "db", db):
                resp = TestClient(server.app).post(
                    "/api/logbooks/lb1/finalize")
        finally:
            server.app.dependency_overrides.clear()
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "SUBMIT_INVALID_DATE")
        self.assertEqual(
            [u for u in db.logbooks.updated if "is_locked" in str(u)], [],
            "a refused finalize must not lock")

    def test_a_signed_submit_with_real_dates_still_files(self):
        """THE GATE MUST NOT COST A CP WHO DID EVERYTHING RIGHT."""
        db = _db_for_create()
        resp = _post(db, _create_body("fall_protection", _fall("2024-03-11")))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(db.logbooks.inserted[0]["is_locked"])


# ══ 4. WHAT IS ALREADY FILED IS NOT TOUCHED ═════════════════════════════════

class AFiledRecordStillRenders(unittest.TestCase):
    """THE GATE APPLIES TO A SUBMIT, NEVER TO A READ. Historical logs holding
    free text are not migrated and not re-gated, so the one thing that must be
    proved is that the document still comes out carrying what was filed."""

    def test_a_scaffold_sheet_prints_a_legacy_installation_date_verbatim(self):
        lb = _filed_logbook("scaffold_maintenance",
                            data=_scaffold("8/12"))
        html = _render_sheet(lb)
        self.assertIn("8/12", html)
        self.assertIn("Installation Date", html)

    def test_a_fall_protection_row_prints_a_legacy_mfg_date_verbatim(self):
        lb = _filed_logbook("fall_protection", data=_fall("07/212029"))
        html = _render_sheet(lb)
        self.assertIn("07/212029", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
