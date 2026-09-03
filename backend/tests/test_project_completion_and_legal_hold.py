"""Completion date, legal hold, and the brake they put on the Tier 2 purge.

WHAT THIS PROTECTS. `DELETE /projects/{id}/hard-delete` physically destroys a
project's entire compliance history — every dob_log, checkin, logbook, signature
event and stored image. Today it asks only "are you the owner, and is this your
company's project?" Nothing asks whether the law still requires those records to
exist. ESRA BB2024-007 §V.4 wants seven years past job completion, and the
compliance doc records the gap in as many words: "Retention — 7 years
post-completion. Not computable. No job-completion date exists."

So this file is about a BRAKE. Every assertion below is either "the purge
refused" or "the purge refused AND destroyed nothing" — never "the purge
happened sooner". Retention here can only ever prevent a deletion.

THE THREE THINGS THAT MUST NOT DRIFT:

  1. ABSENCE IS NOT A DATE. `job_completion_date` is written by a human who
     asserts it, and by nothing else. No inference from `updated_at` (which
     moves when an NFC tag is minted), from `last_dob_sync_at`, or from last
     activity. The dob_logs TTL incident is the precedent and it is asserted
     here as source: two indexes keyed on `detected_at` — when the app FIRST
     SAW a record, not when the event happened — would have destroyed a 2019
     violation and a 2026 violation on the same day.

  2. NOTHING AUTOMATED EVER ACTS ON THIS. `purge_eligible_at` is computed for
     the response and stored nowhere. There is no scheduler, no TTL index, no
     `expireAfterSeconds`. A date that is seven years past does not cause a
     deletion; it merely stops refusing one.

  3. A HOLD NEVER EXPIRES. It is cleared by a human or not at all, and while it
     is set the purge refuses regardless of any date.
"""

from __future__ import annotations

import asyncio
import copy
import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.pop("PLATFORM_GATES_ENFORCED", None)

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib.project_retention import (  # noqa: E402
    RETENTION_YEARS,
    legal_hold_view,
    purge_eligible_at,
    retention_refusal,
)

PID = "6a5f63bc147407d3261df2c7"
OTHER = "6a5f63bc147407d3261df2c8"

# "Today" for every date assertion in this file. Pinned so the suite does not
# start failing seven years from now for reasons unrelated to the code.
TODAY = "2026-09-02"


# ── mongo double ────────────────────────────────────────────────────────────

def _match(doc, query):
    for k, v in query.items():
        if k == "$or":
            if not any(_match(doc, sub) for sub in v):
                return False
            continue
        if isinstance(v, dict):
            if "$ne" in v and doc.get(k) == v["$ne"]:
                return False
            if "$in" in v and doc.get(k) not in v["$in"]:
                return False
            if "$regex" in v and not re.search(v["$regex"], str(doc.get(k) or "")):
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _Coll:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.deleted = []       # every delete filter this collection received
        self.updated = []       # every (filter, update) pair

    def find(self, query=None, projection=None):
        return _Cursor([d for d in self.docs if _match(d, query or {})])

    async def find_one(self, query, projection=None, sort=None):
        for d in self.docs:
            if _match(d, query):
                return copy.deepcopy(d)
        return None

    async def delete_many(self, query):
        self.deleted.append(query)
        keep = [d for d in self.docs if not _match(d, query)]
        n = len(self.docs) - len(keep)
        self.docs[:] = keep
        return type("R", (), {"deleted_count": n})()

    async def delete_one(self, query):
        return await self.delete_many(query)

    async def update_many(self, query, update=None, *a, **k):
        self.updated.append((query, update))
        return type("R", (), {"modified_count": 0})()

    async def update_one(self, query, update=None, *a, **k):
        self.updated.append((query, update))
        n = 0
        for d in self.docs:
            if _match(d, query):
                d.update((update or {}).get("$set", {}))
                n = 1
                break
        return type("R", (), {"modified_count": n, "matched_count": n})()

    async def insert_one(self, doc, *a, **k):
        self.docs.append(copy.deepcopy(doc))
        return type("R", (), {"inserted_id": "x"})()

    async def count_documents(self, query=None):
        return sum(1 for d in self.docs if _match(d, query or {}))


class _DB:
    def __init__(self):
        self._c = {}

    def _mk(self, n):
        if n not in self._c:
            self._c[n] = _Coll()
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._mk(n)

    def __getitem__(self, n):
        return self._mk(n)

    def touched(self):
        """Every collection that received a delete or an update."""
        return {n for n, c in self._c.items() if c.deleted or c.updated}


def _proj(**over):
    d = {
        "_id": PID, "name": "588 Boyland", "address": "588 Boyland St",
        "company_id": "coA", "status": "active",
        "is_deleted": False, "marked_for_deletion": True,
        "marked_at": "2026-08-01", "marked_by": "admin1",
    }
    d.update(over)
    return d


def _owner(company="coA"):
    return {"_id": f"own_{company}", "id": f"own_{company}", "role": "owner",
            "company_id": company, "email": f"owner@{company}.test",
            "account_status": "approved"}


def _admin(company="coA"):
    return {"_id": "adm1", "id": "adm1", "role": "admin",
            "company_id": company, "email": "admin@coA.test",
            "account_status": "approved"}


class Base(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.db = _DB()
        self.db.projects.docs = [_proj()]
        # Something destroyable in each of the two collections the review
        # screen counts, so "nothing was destroyed" is a real assertion and
        # not a vacuous one over empty collections.
        self.db.dob_logs.docs = [{"project_id": PID, "record_type": "violation"}]
        self.db.checkins.docs = [{"project_id": PID, "worker_id": "w1"}]
        self._orig = {"db": server.db, "tqid": server.to_query_id,
                      "r2": server._r2_client}
        server.db = self.db
        server.to_query_id = lambda x: x
        server._r2_client = None

    def tearDown(self):
        server.db = self._orig["db"]
        server.to_query_id = self._orig["tqid"]
        server._r2_client = self._orig["r2"]
        self.loop.close()

    def set_project(self, **over):
        self.db.projects.docs = [_proj(**over)]

    def purge(self, user=None):
        return self.loop.run_until_complete(
            server.hard_delete_project(project_id=PID, owner=user or _owner()))

    def purge_refused(self, user=None):
        with self.assertRaises(HTTPException) as c:
            self.purge(user)
        return c.exception

    def update(self, payload, user=None):
        return self.loop.run_until_complete(server.update_project(
            project_id=PID,
            project_data=server.ProjectUpdate(**payload),
            admin=user or _admin(),
        ))

    def update_refused(self, payload, user=None):
        with self.assertRaises(HTTPException) as c:
            self.update(payload, user)
        return c.exception

    def listing(self, user=None):
        out = self.loop.run_until_complete(
            server.list_pending_deletion_projects(owner=user or _owner()))
        return out["items"]

    def assert_nothing_destroyed(self):
        """The whole point. A refusal that still deleted is not a refusal."""
        self.assertEqual(len(self.db.projects.docs), 1,
                         "the project document itself was destroyed")
        self.assertEqual(len(self.db.dob_logs.docs), 1,
                         "compliance history was destroyed by a refused purge")
        self.assertEqual(len(self.db.checkins.docs), 1,
                         "check-ins were destroyed by a refused purge")
        self.assertEqual(self.db.touched(), set(),
                         f"a refused purge still wrote to {self.db.touched()}")


# ── the arithmetic ──────────────────────────────────────────────────────────

class TheSevenYearClock(unittest.TestCase):
    def test_seven_years_is_the_statutory_number(self):
        self.assertEqual(RETENTION_YEARS, 7)

    def test_absent_completion_date_is_not_a_date(self):
        """The soft-delete purge skips rows with no deleted_at rather than
        guessing one. Same rule: no assertion means no computable eligibility,
        forever — never "eligible now"."""
        self.assertIsNone(purge_eligible_at({}))
        self.assertIsNone(purge_eligible_at({"job_completion_date": None}))
        self.assertIsNone(purge_eligible_at({"job_completion_date": ""}))

    def test_it_is_seven_years_past_the_asserted_date(self):
        self.assertEqual(
            purge_eligible_at({"job_completion_date": "2020-03-01"}),
            "2027-03-01")

    def test_a_leap_day_completion_rounds_toward_holding_longer(self):
        """2027-02-29 does not exist. A brake resolves the ambiguity by
        retaining a day longer, never by releasing a day early."""
        self.assertEqual(
            purge_eligible_at({"job_completion_date": "2020-02-29"}),
            "2027-03-01")

    def test_garbage_is_not_silently_treated_as_eligible(self):
        for bad in ("not-a-date", "2020-13-01", "03/01/2020", "2020-3-1", 20200301):
            with self.subTest(bad=bad):
                self.assertIsNone(purge_eligible_at({"job_completion_date": bad}))

    def test_it_never_reads_any_field_but_the_asserted_one(self):
        """The dob_logs TTL incident in one assertion: a clock keyed on when we
        first saw a thing, rather than when it happened."""
        noise = {
            "updated_at": "2001-01-01", "last_dob_sync_at": "2001-01-01",
            "created_at": "2001-01-01", "marked_at": "2001-01-01",
            "detected_at": "2001-01-01", "status": "active",
        }
        self.assertIsNone(purge_eligible_at(noise))
        self.assertIsNone(retention_refusal(noise, today=TODAY))


# ── the refusal rule ────────────────────────────────────────────────────────

class TheRefusalRule(unittest.TestCase):
    def test_a_recent_completion_refuses(self):
        r = retention_refusal({"job_completion_date": "2025-01-01"}, today=TODAY)
        self.assertIsNotNone(r)
        self.assertIn("2032-01-01", r)

    def test_a_completion_seven_years_past_does_not_refuse(self):
        self.assertIsNone(retention_refusal(
            {"job_completion_date": "2019-01-01"}, today=TODAY))

    def test_the_boundary_day_itself_is_eligible(self):
        """purge_eligible_at is the first day the brake is off, not the last
        day it is on."""
        self.assertIsNone(retention_refusal(
            {"job_completion_date": "2019-09-02"}, today=TODAY))
        self.assertIsNotNone(retention_refusal(
            {"job_completion_date": "2019-09-03"}, today=TODAY))

    def test_a_hold_refuses_on_its_own(self):
        r = retention_refusal({"legal_hold": True}, today=TODAY)
        self.assertIsNotNone(r)
        self.assertIn("hold", r.lower())

    def test_a_hold_outranks_a_fully_elapsed_retention_period(self):
        """The date says purge; the hold says no. The hold wins, and the
        reason names the hold rather than the date."""
        r = retention_refusal(
            {"job_completion_date": "2010-01-01", "legal_hold": True},
            today=TODAY)
        self.assertIsNotNone(r)
        self.assertIn("hold", r.lower())

    def test_a_hold_never_expires(self):
        """No age, however great, releases it."""
        for placed in ("2001-01-01", "1994-06-30"):
            with self.subTest(placed=placed):
                self.assertIsNotNone(retention_refusal(
                    {"legal_hold": True, "legal_hold_at": placed}, today=TODAY))

    def test_a_released_hold_does_not_refuse(self):
        self.assertIsNone(retention_refusal({"legal_hold": False}, today=TODAY))


# ── the brake on the endpoint that can already destroy records today ────────

class TheHardDeleteRefuses(Base):
    def test_a_project_completed_last_year_cannot_be_purged(self):
        self.set_project(job_completion_date="2025-06-01")
        exc = self.purge_refused()
        self.assertEqual(exc.status_code, 409)
        self.assert_nothing_destroyed()

    def test_the_refusal_says_when_it_would_be_eligible(self):
        self.set_project(job_completion_date="2025-06-01")
        self.assertIn("2032-06-01", str(self.purge_refused().detail))

    def test_a_held_project_cannot_be_purged(self):
        self.set_project(legal_hold=True, legal_hold_reason="Kaplan v. 588 Boyland")
        exc = self.purge_refused()
        self.assertEqual(exc.status_code, 409)
        self.assert_nothing_destroyed()

    def test_a_held_project_cannot_be_purged_even_long_after_completion(self):
        self.set_project(job_completion_date="2010-01-01", legal_hold=True,
                         legal_hold_reason="preservation notice")
        self.purge_refused()
        self.assert_nothing_destroyed()

    def test_the_operator_is_not_above_the_brake(self):
        """Cross-tenant scoping has an operator exemption. Retention does not:
        the record is owed to a regulator, not to a tenant."""
        op = {"_id": "op1", "id": "op1", "role": "owner", "company_id": None,
              "is_platform_operator": True, "account_status": "approved"}
        self.set_project(legal_hold=True, legal_hold_reason="preservation notice")
        self.purge_refused(op)
        self.assert_nothing_destroyed()

    def test_the_brake_precedes_the_r2_sweep(self):
        """R2 objects have no DB rows and the sweep is by prefix — if the
        refusal came after it, the photographs would already be gone."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        body = src[src.index("async def hard_delete_project"):]
        body = body[:body.index("# ==================== PROJECT NFC TAGS")]
        self.assertLess(
            body.index("retention_refusal"), body.index("_r2_delete_prefix"),
            "the retention brake must refuse before any storage sweep")

    def test_a_fully_elapsed_project_still_purges(self):
        """The brake is a brake. Once seven years have passed it stops
        objecting; it does not then cause anything."""
        self.set_project(job_completion_date="2010-01-01")
        out = self.purge()
        self.assertEqual(out["project_id"], PID)
        self.assertEqual(len(self.db.projects.docs), 0)

    def test_a_project_with_no_completion_date_purges_as_before(self):
        """Every project alive today is in this state. The brake refuses on a
        RECORDED completion; it does not convert the absence of a record into
        a permanent lock on the owner's only cleanup path."""
        out = self.purge()
        self.assertEqual(out["project_id"], PID)
        self.assertEqual(len(self.db.projects.docs), 0)


# ── writing the fields ──────────────────────────────────────────────────────

class RecordingCompletion(Base):
    def test_an_admin_can_record_it(self):
        self.update({"job_completion_date": "2026-08-15",
                     "completion_source": "final_co"})
        d = self.db.projects.docs[0]
        self.assertEqual(d["job_completion_date"], "2026-08-15")
        self.assertEqual(d["completion_source"], "final_co")
        self.assertEqual(d["completed_by"], "adm1")

    def test_the_date_must_be_a_calendar_date_string(self):
        for bad in ("15/08/2026", "2026-8-15", "yesterday", "2026-02-30"):
            with self.subTest(bad=bad):
                self.assertEqual(
                    self.update_refused({"job_completion_date": bad}).status_code,
                    400)

    def test_a_completion_cannot_be_in_the_future(self):
        """A completion is an event that happened. A future date is either a
        typo or a schedule, and both would shorten retention."""
        self.assertEqual(
            self.update_refused({"job_completion_date": "2099-01-01"}).status_code,
            400)

    def test_the_source_is_recorded_beside_the_value(self):
        """bbl_source / classification_source precedent — provenance travels
        with the assertion, so a later reader can weigh it."""
        self.assertEqual(
            self.update_refused({"job_completion_date": "2026-08-15",
                                 "completion_source": "vibes"}).status_code,
            400)

    def test_recording_it_is_audit_logged_with_the_previous_value(self):
        self.set_project(job_completion_date="2026-01-01",
                         completion_source="final_co")
        self.update({"job_completion_date": "2026-08-15",
                     "completion_source": "final_co"})
        entries = [d for d in self.db.audit_logs.docs
                   if d["action"] == "project_completion_set"]
        self.assertEqual(len(entries), 1)
        det = entries[0]["details"]
        self.assertEqual(det["previous"]["job_completion_date"], "2026-01-01")
        self.assertEqual(det["job_completion_date"], "2026-08-15")
        self.assertEqual(entries[0]["user_id"], "adm1")

    def test_an_unrelated_edit_writes_no_completion_audit_entry(self):
        self.update({"name": "588 Boyland Street"})
        self.assertEqual(
            [d for d in self.db.audit_logs.docs
             if d["action"] == "project_completion_set"], [])

    def test_it_is_never_stamped_as_a_side_effect_of_an_unrelated_edit(self):
        """updated_at moves when an NFC tag is minted. That must never become
        a completion assertion."""
        self.update({"name": "588 Boyland Street"})
        self.assertIsNone(self.db.projects.docs[0].get("job_completion_date"))
        self.assertIsNone(self.db.projects.docs[0].get("completed_by"))


class PlacingALegalHold(Base):
    def test_an_admin_can_place_one_with_a_reason(self):
        self.update({"legal_hold": True, "legal_hold_reason": "Kaplan v. 588 Boyland"})
        d = self.db.projects.docs[0]
        self.assertIs(d["legal_hold"], True)
        self.assertEqual(d["legal_hold_reason"], "Kaplan v. 588 Boyland")
        self.assertEqual(d["legal_hold_by"], "adm1")
        self.assertIsNotNone(d["legal_hold_at"])

    def test_a_hold_without_a_reason_is_refused(self):
        """An unexplained hold is indistinguishable from a mistake, and it
        never expires on its own."""
        self.assertEqual(self.update_refused({"legal_hold": True}).status_code, 400)
        self.assertEqual(
            self.update_refused({"legal_hold": True,
                                 "legal_hold_reason": "   "}).status_code, 400)

    def test_placing_one_is_audit_logged(self):
        self.update({"legal_hold": True, "legal_hold_reason": "preservation notice"})
        e = [d for d in self.db.audit_logs.docs if d["action"] == "project_legal_hold"]
        self.assertEqual(len(e), 1)
        self.assertIs(e[0]["details"]["legal_hold"], True)
        self.assertIs(e[0]["details"]["previous"]["legal_hold"], False)

    def test_releasing_one_is_attributable(self):
        self.set_project(legal_hold=True, legal_hold_reason="preservation notice",
                         legal_hold_by="adm0", legal_hold_at="2026-01-01")
        self.update({"legal_hold": False})
        d = self.db.projects.docs[0]
        self.assertIs(d["legal_hold"], False)
        self.assertEqual(d["legal_hold_released_by"], "adm1")
        self.assertIsNotNone(d["legal_hold_released_at"])
        e = [x for x in self.db.audit_logs.docs if x["action"] == "project_legal_hold"]
        self.assertIs(e[0]["details"]["legal_hold"], False)

    def test_releasing_one_keeps_who_placed_it(self):
        """The trail of a hold that was placed and lifted must survive the
        lifting."""
        self.set_project(legal_hold=True, legal_hold_reason="preservation notice",
                         legal_hold_by="adm0", legal_hold_at="2026-01-01")
        self.update({"legal_hold": False})
        self.assertEqual(self.db.projects.docs[0]["legal_hold_by"], "adm0")

    def test_a_false_hold_survives_the_none_filter(self):
        """update_project drops None values, so `legal_hold: False` must be
        distinguishable from "not mentioned" — otherwise a hold could be
        placed and never lifted through this path."""
        self.set_project(legal_hold=True, legal_hold_reason="x")
        self.update({"legal_hold": False})
        self.assertIs(self.db.projects.docs[0]["legal_hold"], False)


# ── the response, which is an allow-list ────────────────────────────────────

class TheResponseDeclaresEverythingItAdds(unittest.TestCase):
    """An undeclared field is dropped silently. That has already caused one
    outage (the Dropbox sync button was unreachable on every linked project),
    and here it would mean a screen showing "no hold" on a held project."""

    FIELDS = ["job_completion_date", "completed_by", "completion_source",
              "legal_hold", "legal_hold_reason", "legal_hold_by",
              "legal_hold_at", "purge_eligible_at"]

    def test_every_field_is_declared(self):
        declared = set(server.ProjectResponse.model_fields)
        for f in self.FIELDS:
            with self.subTest(field=f):
                self.assertIn(f, declared)

    def test_they_survive_a_round_trip(self):
        doc = {
            "id": PID, "name": "588 Boyland",
            "job_completion_date": "2020-03-01", "completed_by": "adm1",
            "completion_source": "final_co", "legal_hold": True,
            "legal_hold_reason": "Kaplan", "legal_hold_by": "adm1",
            "legal_hold_at": "2026-01-01T00:00:00+00:00",
            "purge_eligible_at": "2027-03-01",
        }
        out = server.ProjectResponse(**doc).model_dump()
        for f in self.FIELDS:
            with self.subTest(field=f):
                self.assertEqual(out[f], doc[f])

    def test_purge_eligible_at_defaults_to_unknown_not_to_now(self):
        out = server.ProjectResponse(id=PID, name="x").model_dump()
        self.assertIsNone(out["purge_eligible_at"])
        self.assertIs(out["legal_hold"], False)


class TheResponseComputesEligibility(Base):
    def test_get_project_reports_it_without_storing_it(self):
        self.set_project(marked_for_deletion=False,
                         job_completion_date="2020-03-01")
        out = self.loop.run_until_complete(
            server.get_project(project_id=PID, current_user=_admin()))
        self.assertEqual(out.purge_eligible_at, "2027-03-01")
        self.assertNotIn("purge_eligible_at", self.db.projects.docs[0])

    def test_it_is_never_written_by_the_update_path_either(self):
        self.set_project(marked_for_deletion=False)
        self.update({"job_completion_date": "2020-03-01"})
        self.assertNotIn("purge_eligible_at", self.db.projects.docs[0])


# ── the review screen the owner purges from ─────────────────────────────────

class ThePendingDeletionReview(Base):
    def test_it_shows_the_completion_date_and_eligibility(self):
        self.set_project(job_completion_date="2025-06-01")
        item = self.listing()[0]
        self.assertEqual(item["job_completion_date"], "2025-06-01")
        self.assertEqual(item["purge_eligible_at"], "2032-06-01")

    def test_it_says_the_purge_would_be_refused_and_why(self):
        self.set_project(job_completion_date="2025-06-01")
        item = self.listing()[0]
        self.assertTrue(item["purge_blocked"])
        self.assertIn("2032-06-01", item["purge_block_reason"])

    def test_it_shows_a_hold_with_its_reason(self):
        self.set_project(legal_hold=True, legal_hold_reason="Kaplan v. 588 Boyland")
        item = self.listing()[0]
        self.assertTrue(item["legal_hold"])
        self.assertEqual(item["legal_hold_reason"], "Kaplan v. 588 Boyland")
        self.assertTrue(item["purge_blocked"])

    def test_an_unblocked_project_says_so_plainly(self):
        item = self.listing()[0]
        self.assertFalse(item["purge_blocked"])
        self.assertIsNone(item["purge_block_reason"])

    def test_the_scale_indicators_still_travel(self):
        """The screen's existing job is to show what a purge destroys; the
        retention fields are added beside that, not in place of it."""
        item = self.listing()[0]
        self.assertEqual(item["dob_logs_count"], 1)
        self.assertEqual(item["checkins_count"], 1)


# ── what must NOT have been built ───────────────────────────────────────────

class NothingAutomatedActsOnThis(unittest.TestCase):
    """The ruling is that a purge is human-gated, always. These assertions are
    the ruling, written where a future change would trip over them."""

    def _retention_source(self):
        return (_BACKEND / "lib" / "project_retention.py").read_text(encoding="utf-8")

    def _offenders(self, src, banned):
        """All of them at once, so one run names every violation rather than
        stopping at the first."""
        return [b for b in banned if b in src]

    def test_the_retention_module_creates_no_index(self):
        self.assertEqual([], self._offenders(
            self._retention_source(),
            ("expireAfterSeconds", "create_index(", "ensure_index(")))

    def test_the_retention_module_schedules_nothing(self):
        """Code tokens, not prose — the module is free to SAY it schedules
        nothing, and must not contain the machinery to."""
        self.assertEqual([], self._offenders(self._retention_source(), (
            "add_job(", "create_task(", "import asyncio",
            "AsyncIOScheduler", "BackgroundScheduler",
            "CronTrigger", "IntervalTrigger")))

    def test_the_retention_module_deletes_nothing(self):
        """It answers a question. It cannot act — it has no database handle."""
        self.assertEqual([], self._offenders(self._retention_source(), (
            "delete_one(", "delete_many(", ".drop(", "update_one(",
            "update_many(", "await db", "db.projects")))

    def test_no_ttl_index_was_added_anywhere(self):
        """The dob_logs TTL indexes are being REMOVED (runbook 2026-07-24).
        Nothing in this change may add another."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        window = src[src.index("async def hard_delete_project"):][:12000]
        self.assertEqual([], self._offenders(window, ("expireAfterSeconds",)))

    def test_the_soft_delete_purge_knobs_are_untouched(self):
        """SOFT_DELETE_* is a separate, already-reasoned retention decision.
        This change does not ride on it, and must not quietly re-tune it."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertIn("SOFT_DELETE_PURGE_ENABLED", src)
        retention = (_BACKEND / "lib" / "project_retention.py").read_text(
            encoding="utf-8")
        self.assertEqual([], self._offenders(retention, (
            "SOFT_DELETE_PURGE_ENABLED", "SOFT_DELETE_RETENTION_DAYS",
            "SOFT_DELETE_COLLECTIONS")))


class TheCrossProjectResidueIsHeld(Base):
    """A worker's records survive as long as ANY project he worked needs them,
    so nothing here may purge on one project's clock."""

    UNTOUCHABLE = ["workers", "users", "certificates_of_insurance",
                   "esra_consents", "esra_consent_declines"]

    def test_the_retention_path_names_none_of_the_shared_collections(self):
        src = (_BACKEND / "lib" / "project_retention.py").read_text(encoding="utf-8")
        self.assertEqual([], [c for c in self.UNTOUCHABLE if c in src])

    def test_a_refused_purge_does_not_pull_a_worker_orientation(self):
        """The existing purge $pulls this project from every worker. A refusal
        must not have got that far."""
        self.set_project(legal_hold=True, legal_hold_reason="x")
        self.purge_refused()
        self.assertEqual(self.db.workers.updated, [])
        self.assertEqual(self.db.users.updated, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
