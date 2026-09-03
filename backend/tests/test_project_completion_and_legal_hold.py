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

  4. ABSENCE REFUSES. A project with no recorded completion is not a project
     whose retention period elapsed — it is one whose period is UNKNOWN, and
     the brake bites on the unknown. The way through is a named attestation,
     never a clock. This REPLACES the earlier rule in this file, which let an
     absent date pass; that rule is why an earlier version of these tests
     asserted `test_a_project_with_no_completion_date_purges_as_before`, and
     the assertion below is its deliberate inversion. On merge day NO project
     carries `job_completion_date` — the field ships in this change — so a
     brake that only bit on a recorded completion would have protected nothing
     at all.

  5. THE COMPLETION IS A PAIR. A CO number and a date, together or not at all.
     A partial entry is refused, not stored, in both directions and on
     corrections as well as first entries.
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
    CO_NUMBER_MAX_LEN,
    RETENTION_YEARS,
    co_number_problem,
    has_recorded_completion,
    legal_hold_view,
    no_completion_attestation_view,
    normalize_co_number,
    purge_eligible_at,
    retention_refusal,
)

# A completion is a PAIR everywhere in this file. Spelled once so no test can
# accidentally exercise half of one and call it a recorded completion.
CO = "121234567"


def _completion(date_str, co=CO):
    return {"job_completion_date": date_str, "job_completion_co_number": co}


# What a project must carry to be treated as "no completion, but cleared to
# purge" — the item-2 way through, in the shape a stored document has it.
ATTESTED = {
    "no_completion_attested": True,
    "no_completion_reason": "Permit withdrawn; no work was ever performed.",
    "no_completion_attested_by": "adm1",
}

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
        # UPDATED with the absence rule. This used to assert None — no
        # objection — which made the point about inference but also encoded
        # the old absent-date behaviour. Every one of these fields is a date
        # from 2001, so ANY of them read as a completion would put the project
        # twenty years past its retention period and release the brake. It
        # refuses, and the reason names the missing completion rather than any
        # of them.
        r = retention_refusal(noise, today=TODAY)
        self.assertIsNotNone(r)
        self.assertIn("no recorded job completion", r)
        self.assertNotIn("2001", r)
        self.assertNotIn("2008", r)  # 2001 + seven, had it inferred one


# ── the refusal rule ────────────────────────────────────────────────────────

class TheRefusalRule(unittest.TestCase):
    def test_a_recent_completion_refuses(self):
        r = retention_refusal(_completion("2025-01-01"), today=TODAY)
        self.assertIsNotNone(r)
        self.assertIn("2032-01-01", r)

    def test_a_completion_seven_years_past_does_not_refuse(self):
        self.assertIsNone(retention_refusal(
            _completion("2019-01-01"), today=TODAY))

    def test_the_boundary_day_itself_is_eligible(self):
        """purge_eligible_at is the first day the brake is off, not the last
        day it is on."""
        self.assertIsNone(retention_refusal(
            _completion("2019-09-02"), today=TODAY))
        self.assertIsNotNone(retention_refusal(
            _completion("2019-09-03"), today=TODAY))

    def test_an_unknown_today_refuses_rather_than_releases(self):
        """"I do not know what day it is" is not a reason to destroy a
        compliance history. A caller that omits `today` gets the refusal, not
        the fall-through."""
        for missing in (None, ""):
            with self.subTest(today=missing):
                self.assertIsNotNone(retention_refusal(
                    _completion("2010-01-01"), today=missing))

    def test_a_hold_refuses_on_its_own(self):
        r = retention_refusal({"legal_hold": True}, today=TODAY)
        self.assertIsNotNone(r)
        self.assertIn("hold", r.lower())

    def test_a_hold_outranks_a_fully_elapsed_retention_period(self):
        """The date says purge; the hold says no. The hold wins, and the
        reason names the hold rather than the date."""
        r = retention_refusal(
            dict(_completion("2010-01-01"), legal_hold=True), today=TODAY)
        self.assertIsNotNone(r)
        self.assertIn("hold", r.lower())

    def test_a_hold_is_checked_before_the_absent_completion_rule(self):
        """ORDER, asserted where it can be broken. A held project with no
        completion on record is refused for the HOLD — the reason is shown to
        the person deciding, and "record a CO number" would send them off to
        satisfy a rule that is not the one refusing them."""
        r = retention_refusal(
            {"legal_hold": True, "legal_hold_reason": "Kaplan v. 588 Boyland"},
            today=TODAY)
        self.assertIsNotNone(r)
        self.assertIn("hold", r.lower())
        self.assertNotIn("Certificate of Occupancy", r)

    def test_an_attestation_does_not_lift_a_hold(self):
        """The way through the ABSENCE rule is not a way through anything
        else."""
        r = retention_refusal(
            dict(ATTESTED, legal_hold=True, legal_hold_reason="preservation"),
            today=TODAY)
        self.assertIsNotNone(r)
        self.assertIn("hold", r.lower())

    def test_a_hold_never_expires(self):
        """No age, however great, releases it."""
        for placed in ("2001-01-01", "1994-06-30"):
            with self.subTest(placed=placed):
                self.assertIsNotNone(retention_refusal(
                    {"legal_hold": True, "legal_hold_at": placed}, today=TODAY))

    def test_a_released_hold_stops_refusing_for_the_hold(self):
        """UPDATED for the absence rule. This used to assert that a released
        hold left NOTHING objecting — which was only true because an absent
        completion did not object either. Lifting a hold now returns the
        project to whatever its completion record says, and here that record
        is missing, so something still objects. It is no longer the hold."""
        r = retention_refusal({"legal_hold": False}, today=TODAY)
        self.assertIsNotNone(r)
        # ANCHORED on the hold refusal's opening clause, not on the bare word
        # "hold" — which "stands", "household" or a project named Holden would
        # all satisfy. The claim is that this is not the HOLD's message.
        self.assertNotIn("A legal hold is in force", r)
        # With a completion on record, lifting the hold really does clear it.
        self.assertIsNone(retention_refusal(
            dict(_completion("2010-01-01"), legal_hold=False), today=TODAY))


# ── the absent completion, which is every project alive today ───────────────

class AnAbsentCompletionRefuses(unittest.TestCase):
    """THE ITEM-2 RULE. No project in production carries `job_completion_date`
    — the field ships in this change — so a brake that only bit on a RECORDED
    completion would, on merge day, refuse nothing and leave every existing
    project exactly as hard-deletable as it was before. The absence is what it
    has to bite on."""

    def test_a_project_with_nothing_recorded_is_refused(self):
        r = retention_refusal({}, today=TODAY)
        self.assertIsNotNone(r)
        self.assertIn("no recorded job completion", r)

    def test_the_refusal_names_both_ways_through(self):
        """A refusal an admin cannot act on is a dead end. This one has to say
        what to do, because there is no elapsing out of it."""
        r = retention_refusal({}, today=TODAY)
        self.assertIn("Certificate of Occupancy", r)
        self.assertIn("never completed", r)

    def test_an_unreadable_date_is_an_absent_one_not_a_clearance(self):
        """The hole the old rule left open. `purge_eligible_at` returns None
        for a date it cannot parse, and under the previous reading None meant
        "no objection" — so a document carrying `job_completion_date:
        "sometime in 2019"` was PURGEABLE on the strength of a string nothing
        could read."""
        for junk in ("sometime in 2019", "2020-13-01", "03/01/2020", "", 20200301):
            with self.subTest(junk=junk):
                self.assertFalse(has_recorded_completion(
                    {"job_completion_date": junk}))
                self.assertIsNotNone(retention_refusal(
                    {"job_completion_date": junk}, today=TODAY))

    def test_an_attestation_is_the_way_through(self):
        self.assertIsNone(retention_refusal(dict(ATTESTED), today=TODAY))

    def test_a_withdrawn_attestation_refuses_again(self):
        """It is a standing statement, not a spent token. Withdraw it and the
        project goes back to being one whose retention period is unknown."""
        withdrawn = dict(ATTESTED, no_completion_attested=False)
        self.assertIsNotNone(retention_refusal(withdrawn, today=TODAY))

    def test_the_attestation_never_shortens_a_recorded_period(self):
        """It answers "there is no completion to compute from" and nothing
        else. Against a completion that IS on record, the clock rules — which
        is why it is read below the recorded completion and not above it."""
        both = dict(ATTESTED, **_completion("2025-01-01"))
        r = retention_refusal(both, today=TODAY)
        self.assertIsNotNone(r)
        self.assertIn("2032-01-01", r)

    def test_no_amount_of_time_produces_an_attestation(self):
        """There is no elapsing out of the absence rule. A project marked for
        deletion in 1994 is refused exactly as one marked yesterday."""
        for stamp in ("1994-06-30", "2001-01-01", "2026-09-01"):
            with self.subTest(stamp=stamp):
                self.assertIsNotNone(retention_refusal(
                    {"marked_at": stamp, "created_at": stamp,
                     "updated_at": stamp}, today=TODAY))


# ── the brake on the endpoint that can already destroy records today ────────

class TheHardDeleteRefuses(Base):
    def test_a_project_completed_last_year_cannot_be_purged(self):
        self.set_project(**_completion("2025-06-01"))
        exc = self.purge_refused()
        self.assertEqual(exc.status_code, 409)
        self.assert_nothing_destroyed()

    def test_the_refusal_says_when_it_would_be_eligible(self):
        self.set_project(**_completion("2025-06-01"))
        self.assertIn("2032-06-01", str(self.purge_refused().detail))

    def test_a_held_project_cannot_be_purged(self):
        self.set_project(legal_hold=True, legal_hold_reason="Kaplan v. 588 Boyland")
        exc = self.purge_refused()
        self.assertEqual(exc.status_code, 409)
        self.assert_nothing_destroyed()

    def test_a_held_project_cannot_be_purged_even_long_after_completion(self):
        self.set_project(**_completion("2010-01-01"), legal_hold=True,
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
        self.set_project(**_completion("2010-01-01"))
        out = self.purge()
        self.assertEqual(out["project_id"], PID)
        self.assertEqual(len(self.db.projects.docs), 0)

    def test_a_project_with_no_completion_date_is_now_refused(self):
        """THE DELIBERATE INVERSION, and the reason this change exists.

        This test previously asserted that such a project "purges as before".
        Every project alive today is in exactly this state — `job_completion_
        date` ships in this change and nothing in production carries it — so
        that reading made the brake inert on the day it merged: it would have
        refused nothing, and every existing compliance history would have
        stayed as destroyable as it was. A retention control whose first
        production behaviour is to permit every deletion is not one.

        The endpoint is not disabled. It is gated on a person saying something
        on the record, which is the next test."""
        exc = self.purge_refused()
        self.assertEqual(exc.status_code, 409)
        self.assertIn("no recorded job completion", str(exc.detail))
        self.assert_nothing_destroyed()

    def test_an_attested_never_completed_project_purges(self):
        """The way through, end to end. Not a timeout and not an inference —
        a named admin stated on the record that there is no completion to
        wait from, and only then does the endpoint proceed."""
        self.set_project(**ATTESTED)
        out = self.purge()
        self.assertEqual(out["project_id"], PID)
        self.assertEqual(len(self.db.projects.docs), 0)

    def test_the_attestation_is_still_no_defence_against_a_hold(self):
        self.set_project(**ATTESTED, legal_hold=True,
                         legal_hold_reason="preservation notice")
        self.assertEqual(self.purge_refused().status_code, 409)
        self.assert_nothing_destroyed()

    def test_the_operator_is_not_above_the_absence_rule_either(self):
        """The operator exemption test above covers the hold. This covers the
        rule that now applies to every project in the database."""
        op = {"_id": "op1", "id": "op1", "role": "owner", "company_id": None,
              "is_platform_operator": True, "account_status": "approved"}
        self.assertEqual(self.purge_refused(op).status_code, 409)
        self.assert_nothing_destroyed()


# ── writing the fields ──────────────────────────────────────────────────────

class RecordingCompletion(Base):
    def test_an_admin_can_record_it(self):
        self.update(_completion("2026-08-15"))
        d = self.db.projects.docs[0]
        self.assertEqual(d["job_completion_date"], "2026-08-15")
        self.assertEqual(d["job_completion_co_number"], CO)
        self.assertEqual(d["completed_by"], "adm1")

    def test_the_date_must_be_a_calendar_date_string(self):
        for bad in ("15/08/2026", "2026-8-15", "yesterday", "2026-02-30"):
            with self.subTest(bad=bad):
                self.assertEqual(
                    self.update_refused(_completion(bad)).status_code, 400)

    def test_a_completion_cannot_be_in_the_future(self):
        """A completion is an event that happened. A future date is either a
        typo or a schedule, and both would shorten retention."""
        self.assertEqual(
            self.update_refused(_completion("2099-01-01")).status_code, 400)

    def test_recording_it_is_audit_logged_with_the_previous_value(self):
        self.set_project(**_completion("2026-01-01", co="OLD-1"),
                         completion_source="admin_attested")
        self.update(_completion("2026-08-15", co="NEW-2"))
        entries = [d for d in self.db.audit_logs.docs
                   if d["action"] == "project_completion_set"]
        self.assertEqual(len(entries), 1)
        det = entries[0]["details"]
        self.assertEqual(det["previous"]["job_completion_date"], "2026-01-01")
        self.assertEqual(det["job_completion_date"], "2026-08-15")
        self.assertEqual(entries[0]["user_id"], "adm1")

    def test_the_previous_co_number_is_audited_beside_the_previous_date(self):
        """Nothing in this app verifies a CO number, so the audit trail is the
        only record of what was claimed before someone changed it. A corrected
        number with no trace of the original is the exact shape of the problem
        item 3 was asked about."""
        self.set_project(**_completion("2026-01-01", co="OLD-1"))
        self.update(_completion("2026-08-15", co="NEW-2"))
        det = [d for d in self.db.audit_logs.docs
               if d["action"] == "project_completion_set"][0]["details"]
        self.assertEqual(det["previous"]["job_completion_co_number"], "OLD-1")
        self.assertEqual(det["job_completion_co_number"], "NEW-2")


# ── item 1: the pair ────────────────────────────────────────────────────────

class TheCompletionIsANumberAndADate(Base):
    """The operator's ruling: "a claim about a legal event should carry the
    event's identifier. Number and date, or nothing." A partial entry is
    REFUSED, not stored — asserted in both directions and on corrections as
    well as on first entries."""

    def test_a_date_without_a_number_is_refused(self):
        exc = self.update_refused({"job_completion_date": "2026-08-15"})
        self.assertEqual(exc.status_code, 400)
        self.assertIn("BOTH", str(exc.detail))

    def test_a_number_without_a_date_is_refused(self):
        self.assertEqual(
            self.update_refused({"job_completion_co_number": CO}).status_code,
            400)

    def test_a_refused_partial_stores_neither_half(self):
        """"Refused, not stored" is the ruling's own wording, and a 400 that
        still landed one field would satisfy the status code and break the
        rule."""
        self.update_refused({"job_completion_date": "2026-08-15"})
        d = self.db.projects.docs[0]
        self.assertIsNone(d.get("job_completion_date"))
        self.assertIsNone(d.get("job_completion_co_number"))
        self.assertIsNone(d.get("completed_by"))

    def test_a_correction_must_restate_both(self):
        """Moving the date alone would leave a certificate number describing a
        day it no longer describes — a wrong number living on unchallenged,
        which is the failure the pair exists to prevent."""
        self.set_project(**_completion("2026-01-01"))
        self.assertEqual(
            self.update_refused({"job_completion_date": "2026-08-15"}).status_code,
            400)
        self.assertEqual(
            self.db.projects.docs[0]["job_completion_date"], "2026-01-01")

    def test_the_pair_together_is_accepted(self):
        """The positive control for every refusal above: the same endpoint,
        the same fields, both present — it goes through. Without this, all the
        400s could be one unconditional rejection."""
        self.update(_completion("2026-08-15"))
        self.assertEqual(
            self.db.projects.docs[0]["job_completion_date"], "2026-08-15")

    def test_an_unrelated_edit_still_needs_neither(self):
        """The pair rule must not turn every project rename into a completion
        entry."""
        self.update({"name": "588 Boyland Street"})
        self.assertEqual(self.db.projects.docs[0]["name"], "588 Boyland Street")


class TheCoNumberIsAttestedNotValidated(unittest.TestCase):
    """NO FORMAT IS ENFORCED, and this class is where that decision is pinned
    so a later "tidy-up" cannot quietly add a regex.

    The argument is in co_number_problem()'s docstring: this repo reads the DOB
    CO column under three different spellings across two files
    (`_extract_cofo_fields` accepts `co_number` OR
    `certificate_of_occupancy_number`; `statistical_engine/daily_panel.py`
    asks the same dataset for `c_of_o_issuance_date` / `c_of_o_filing_type`),
    and carries no fixture with a real value. A codebase that cannot agree on
    what a CO record is called is in no position to rule on the shape of the
    value inside it. The failure mode of a guessed regex is an admin holding
    the actual certificate that the app refuses to accept."""

    def test_plausible_real_world_numbers_are_all_accepted(self):
        """Deliberately heterogeneous. Any regex narrow enough to be worth
        writing rejects at least one of these, and none of them is obviously
        not a CO number."""
        for good in ("121234567", "B-123456", "310123456-01", "TCO 2024-1187",
                     "M000123456", "123456789/02", "K 44821", "1234567890123"):
            with self.subTest(good=good):
                self.assertIsNone(co_number_problem(good))

    def test_it_is_stored_exactly_as_entered(self):
        """Not upper-cased, not re-spaced, not stripped of punctuation. Each
        of those rewrites a number a human copied off a certificate, and a
        rewritten identifier is no longer the one on the document."""
        for raw in ("b-123456", "TCO 2024-1187", "310123456-01"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_co_number(f"  {raw}  "), raw)

    def test_blank_is_refused(self):
        """The one thing "attested string" still cannot mean is nothing. The
        ruling is number AND date; whitespace is not a number."""
        for blank in ("", "   ", "\t\n"):
            with self.subTest(blank=blank):
                self.assertIsNotNone(co_number_problem(blank))

    def test_a_non_string_is_refused(self):
        for bad in (None, 121234567, ["121234567"], {"co": "1"}, True):
            with self.subTest(bad=bad):
                self.assertIsNotNone(co_number_problem(bad))

    def test_an_oversized_paste_is_refused(self):
        self.assertIsNone(co_number_problem("X" * CO_NUMBER_MAX_LEN))
        self.assertIsNotNone(co_number_problem("X" * (CO_NUMBER_MAX_LEN + 1)))

    def test_a_multi_line_paste_is_refused(self):
        """An identifier occupies one line. A newline here is a paste of
        something else, and this field may end up in front of a regulator."""
        for bad in ("121234567\nand a second thing", "121\r234", "12\x003456"):
            with self.subTest(bad=bad):
                self.assertIsNotNone(co_number_problem(bad))

    def test_the_module_contains_no_co_number_pattern(self):
        """The rule, written where a future regex would trip over it. Format
        checking a CO number requires a claim about NYC's numbering that
        nothing in this repo can support."""
        src = (_BACKEND / "lib" / "project_retention.py").read_text(
            encoding="utf-8")
        body = src[src.index("def co_number_problem"):]
        body = body[:body.index("def normalize_co_number")]
        for banned in ("re.match(", "re.search(", "re.compile(", "re.fullmatch("):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, body)


class CompletionSourceIsServerSetOnly(Base):
    """`completion_source` is STAMPED, never accepted from the body, and always
    the weakest value.

    That is not a default — it is the only true answer. Nothing in this
    application checks a CO number against anything, so every completion it
    holds is an attestation. Recording "final_co" would assert a verification
    that did not happen, on the field that governs destruction."""

    def test_it_is_stamped_as_attested(self):
        self.update(_completion("2026-08-15"))
        self.assertEqual(
            self.db.projects.docs[0]["completion_source"], "admin_attested")

    def test_a_client_cannot_claim_a_stronger_source(self):
        """UPDATED: this replaces test_the_source_is_recorded_beside_the_value,
        which asserted that a bad source string got a 400. The field is no
        longer accepted at all, so there is nothing to 400 on — the stronger
        assertion is that whatever the client sends is DROPPED and the stamped
        value stands."""
        for claimed in ("final_co", "final_signoff", "vibes"):
            with self.subTest(claimed=claimed):
                self.set_project()
                self.update(dict(_completion("2026-08-15"),
                                 completion_source=claimed))
                self.assertEqual(self.db.projects.docs[0]["completion_source"],
                                 "admin_attested")

    def test_the_default_is_a_member_and_is_the_attested_one(self):
        """VALID_COMPLETION_SOURCES is no longer VALIDATED against — nothing
        writes a source but the default — so it survives as READ vocabulary
        for legacy documents and for the screen's labels. A set nothing checks
        rots, so its contract is asserted here instead: the stamped value is a
        member of it, and it is the weakest member."""
        self.assertIn(server.DEFAULT_COMPLETION_SOURCE,
                      server.VALID_COMPLETION_SOURCES)
        self.assertEqual(server.DEFAULT_COMPLETION_SOURCE, "admin_attested")

    def test_the_screen_can_label_every_source_the_server_may_return(self):
        """The other half of that contract, across the wire. A stored value the
        card has no label for renders as a raw key in front of an admin; a
        label for a value the server can never produce is dead UI. Read out of
        the component's real source so neither side can drift."""
        card = (Path(__file__).resolve().parents[2] / "frontend" / "src"
                / "components" / "ProjectRetentionCard.jsx").read_text(
                    encoding="utf-8")
        block = card[card.index("const SOURCE_LABELS = {"):]
        block = block[:block.index("};")]
        labelled = set(re.findall(r"^\s*(\w+):", block, re.M))
        self.assertEqual(labelled, server.VALID_COMPLETION_SOURCES)

    def test_the_screen_no_longer_offers_a_source_picker(self):
        """The field is not accepted from the body any more, so a picker would
        be a control whose choice the server silently discards — an admin
        selecting "Final C of O" would believe they had recorded a verification
        that never happened."""
        card = (Path(__file__).resolve().parents[2] / "frontend" / "src"
                / "components" / "ProjectRetentionCard.jsx").read_text(
                    encoding="utf-8")
        self.assertIn("SOURCE_LABELS", card)  # positive control
        self.assertNotIn("completion_source:", card)
        self.assertNotIn("setSourceDraft(", card)

    def test_the_update_model_does_not_declare_it(self):
        """The mechanism behind the test above, asserted directly: pydantic
        drops undeclared fields, so this is what makes the claim unforgeable
        rather than merely overwritten."""
        for f in ("completion_source", "completed_by", "legal_hold_by",
                  "legal_hold_at", "no_completion_attested_by",
                  "no_completion_attested_at"):
            with self.subTest(field=f):
                self.assertNotIn(f, server.ProjectUpdate.model_fields)

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


class AttestingThatThereIsNoCompletion(Base):
    """ITEM 2's way through, at the endpoint. Everything here is human-gated,
    named and audited — the same shape as the legal hold, because it is the
    same kind of act: a person putting their name to a statement about whether
    records may be destroyed."""

    NC = {"no_completion_attested": True,
          "no_completion_reason": "Permit withdrawn; no work performed."}

    def test_an_admin_can_attest_with_a_reason(self):
        self.update(self.NC)
        d = self.db.projects.docs[0]
        self.assertIs(d["no_completion_attested"], True)
        self.assertEqual(d["no_completion_reason"],
                         "Permit withdrawn; no work performed.")
        self.assertEqual(d["no_completion_attested_by"], "adm1")
        self.assertIsNotNone(d["no_completion_attested_at"])

    def test_an_attestation_without_a_reason_is_refused(self):
        """This is the only thing that permits the permanent destruction of a
        project with no completion on record, so it is the sentence a
        regulator would be shown. A bare boolean cannot serve that purpose and
        is indistinguishable from a mis-click."""
        self.assertEqual(
            self.update_refused({"no_completion_attested": True}).status_code, 400)
        self.assertEqual(
            self.update_refused({"no_completion_attested": True,
                                 "no_completion_reason": "  "}).status_code, 400)

    def test_a_refused_attestation_unblocks_nothing(self):
        self.update_refused({"no_completion_attested": True})
        self.assertFalse(self.db.projects.docs[0].get("no_completion_attested"))
        self.assertEqual(self.purge_refused().status_code, 409)

    def test_it_cannot_be_attested_against_a_recorded_completion(self):
        """A document asserting both "completed 2025-06-01" and "never
        completed" is a record nobody can rely on, and the reader who most
        needs to rely on it is deciding whether to destroy the history."""
        self.set_project(**_completion("2025-06-01"))
        exc = self.update_refused(self.NC)
        self.assertEqual(exc.status_code, 400)
        self.assertIn("recorded job completion", str(exc.detail))

    def test_it_cannot_be_attested_in_the_same_request_as_a_completion(self):
        self.assertEqual(
            self.update_refused(dict(self.NC, **_completion("2025-06-01"))
                                ).status_code, 400)

    def test_recording_a_completion_supersedes_a_standing_attestation(self):
        """The safe direction, and the only one allowed automatically: the
        attestation refused nothing, the completion starts a seven-year
        refusal, so retiring it here can only TIGHTEN the brake."""
        self.set_project(**ATTESTED)
        self.update(_completion("2025-06-01"))
        d = self.db.projects.docs[0]
        self.assertIs(d["no_completion_attested"], False)
        self.assertEqual(d["no_completion_superseded_by"], "adm1")
        self.assertIsNotNone(d["no_completion_superseded_at"])
        # And the brake is now tighter, not looser.
        self.assertEqual(self.purge_refused().status_code, 409)

    def test_a_supersede_is_not_also_recorded_as_a_withdrawal(self):
        """Two different acts. An earlier draft cleared the flag inside the
        completion branch and then fell through the withdrawal branch,
        stamping the same call as both."""
        self.set_project(**ATTESTED)
        self.update(_completion("2025-06-01"))
        self.assertNotIn("no_completion_withdrawn_by", self.db.projects.docs[0])

    def test_it_can_be_withdrawn(self):
        self.set_project(**ATTESTED)
        self.update({"no_completion_attested": False})
        d = self.db.projects.docs[0]
        self.assertIs(d["no_completion_attested"], False)
        self.assertEqual(d["no_completion_withdrawn_by"], "adm1")
        self.assertIsNotNone(d["no_completion_withdrawn_at"])

    def test_withdrawing_it_keeps_who_attested(self):
        """The trail of a statement made and retracted is the part worth
        keeping — same rule as the lifted legal hold."""
        self.set_project(**dict(ATTESTED, no_completion_attested_by="adm0"))
        self.update({"no_completion_attested": False})
        self.assertEqual(
            self.db.projects.docs[0]["no_completion_attested_by"], "adm0")

    def test_withdrawing_it_re_blocks_the_purge(self):
        """It is a standing statement, not a spent token."""
        self.set_project(**ATTESTED)
        self.update({"no_completion_attested": False})
        self.assertEqual(self.purge_refused().status_code, 409)
        # NOT assert_nothing_destroyed() — that helper also asserts no
        # collection was written at all, and the withdrawal above is itself a
        # write to `projects`. The claim here is that the records SURVIVED the
        # refused purge, which is what these three assertions say.
        self.assertEqual(len(self.db.projects.docs), 1)
        self.assertEqual(len(self.db.dob_logs.docs), 1)
        self.assertEqual(len(self.db.checkins.docs), 1)

    def test_a_false_attestation_survives_the_none_filter(self):
        """Same mechanism the hold depends on. If this ever becomes a filtered
        Optional[bool], an attestation could be made and never withdrawn."""
        self.set_project(**ATTESTED)
        self.update({"no_completion_attested": False})
        self.assertIs(self.db.projects.docs[0]["no_completion_attested"], False)

    def test_a_reason_alone_needs_a_standing_attestation(self):
        self.assertEqual(
            self.update_refused({"no_completion_reason": "because"}).status_code,
            400)

    def test_attesting_is_audit_logged_with_the_previous_value(self):
        self.update(self.NC)
        e = [d for d in self.db.audit_logs.docs
             if d["action"] == "project_no_completion_attestation"]
        self.assertEqual(len(e), 1)
        self.assertIs(e[0]["details"]["no_completion_attested"], True)
        self.assertIs(e[0]["details"]["previous"]["no_completion_attested"], False)
        self.assertEqual(e[0]["details"]["no_completion_reason"],
                         "Permit withdrawn; no work performed.")
        self.assertEqual(e[0]["user_id"], "adm1")

    def test_withdrawing_is_audit_logged_too(self):
        self.set_project(**ATTESTED)
        self.update({"no_completion_attested": False})
        e = [d for d in self.db.audit_logs.docs
             if d["action"] == "project_no_completion_attestation"]
        self.assertEqual(len(e), 1)
        self.assertIs(e[0]["details"]["no_completion_attested"], False)
        self.assertIs(e[0]["details"]["previous"]["no_completion_attested"], True)

    def test_an_unrelated_edit_writes_no_attestation_entry(self):
        self.update({"name": "588 Boyland Street"})
        self.assertEqual(
            [d for d in self.db.audit_logs.docs
             if d["action"] == "project_no_completion_attestation"], [])

    def test_it_is_never_stamped_as_a_side_effect_of_an_unrelated_edit(self):
        self.update({"name": "588 Boyland Street"})
        d = self.db.projects.docs[0]
        self.assertIsNone(d.get("no_completion_attested"))
        self.assertIsNone(d.get("no_completion_attested_by"))


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

    FIELDS = ["job_completion_date", "job_completion_co_number", "completed_by",
              "completion_source", "legal_hold", "legal_hold_reason",
              "legal_hold_by", "legal_hold_at", "purge_eligible_at",
              "no_completion_attested", "no_completion_reason",
              "no_completion_attested_by", "no_completion_attested_at"]

    def test_every_field_is_declared(self):
        declared = set(server.ProjectResponse.model_fields)
        for f in self.FIELDS:
            with self.subTest(field=f):
                self.assertIn(f, declared)

    def test_they_survive_a_round_trip(self):
        doc = {
            "id": PID, "name": "588 Boyland",
            "job_completion_date": "2020-03-01",
            "job_completion_co_number": CO, "completed_by": "adm1",
            "completion_source": "admin_attested", "legal_hold": True,
            "legal_hold_reason": "Kaplan", "legal_hold_by": "adm1",
            "legal_hold_at": "2026-01-01T00:00:00+00:00",
            "purge_eligible_at": "2027-03-01",
            "no_completion_attested": True,
            "no_completion_reason": "Permit withdrawn",
            "no_completion_attested_by": "adm1",
            "no_completion_attested_at": "2026-01-01T00:00:00+00:00",
        }
        out = server.ProjectResponse(**doc).model_dump()
        for f in self.FIELDS:
            with self.subTest(field=f):
                self.assertEqual(out[f], doc[f])

    def test_purge_eligible_at_defaults_to_unknown_not_to_now(self):
        out = server.ProjectResponse(id=PID, name="x").model_dump()
        self.assertIsNone(out["purge_eligible_at"])
        self.assertIs(out["legal_hold"], False)

    def test_an_absent_attestation_reads_as_not_attested(self):
        """The dangerous default is the other way. A legacy document with no
        key must read False — "nobody has stated anything" — rather than None,
        which the screen would have to guess at, or True, which would show a
        purge as cleared that nobody cleared."""
        out = server.ProjectResponse(id=PID, name="x").model_dump()
        self.assertIs(out["no_completion_attested"], False)
        self.assertIsNone(out["no_completion_reason"])
        self.assertIsNone(out["job_completion_co_number"])


class TheResponseComputesEligibility(Base):
    def test_get_project_reports_it_without_storing_it(self):
        self.set_project(marked_for_deletion=False, **_completion("2020-03-01"))
        out = self.loop.run_until_complete(
            server.get_project(project_id=PID, current_user=_admin()))
        self.assertEqual(out.purge_eligible_at, "2027-03-01")
        self.assertNotIn("purge_eligible_at", self.db.projects.docs[0])

    def test_it_is_never_written_by_the_update_path_either(self):
        self.set_project(marked_for_deletion=False)
        self.update(_completion("2020-03-01"))
        self.assertNotIn("purge_eligible_at", self.db.projects.docs[0])

    def test_the_co_number_reaches_the_screen(self):
        """It is an allow-list. An undeclared field is dropped silently, and
        this one is the identifier that makes the date a claim about a
        document rather than an unattributed assertion."""
        self.set_project(marked_for_deletion=False, **_completion("2020-03-01"))
        out = self.loop.run_until_complete(
            server.get_project(project_id=PID, current_user=_admin()))
        self.assertEqual(out.job_completion_co_number, CO)


# ── the review screen the owner purges from ─────────────────────────────────

class ThePendingDeletionReview(Base):
    def test_it_shows_the_completion_date_and_eligibility(self):
        self.set_project(**_completion("2025-06-01"))
        item = self.listing()[0]
        self.assertEqual(item["job_completion_date"], "2025-06-01")
        self.assertEqual(item["job_completion_co_number"], CO)
        self.assertEqual(item["purge_eligible_at"], "2032-06-01")

    def test_it_says_the_purge_would_be_refused_and_why(self):
        self.set_project(**_completion("2025-06-01"))
        item = self.listing()[0]
        self.assertTrue(item["purge_blocked"])
        self.assertIn("2032-06-01", item["purge_block_reason"])

    def test_it_shows_a_hold_with_its_reason(self):
        self.set_project(legal_hold=True, legal_hold_reason="Kaplan v. 588 Boyland")
        item = self.listing()[0]
        self.assertTrue(item["legal_hold"])
        self.assertEqual(item["legal_hold_reason"], "Kaplan v. 588 Boyland")
        self.assertTrue(item["purge_blocked"])

    def test_a_project_with_no_completion_reads_as_blocked(self):
        """UPDATED. This used to be test_an_unblocked_project_says_so_plainly
        and asserted the opposite — the default fixture has no completion, and
        under the old rule that was a clear purge. It is now the refusal, and
        the screen renders the button off this flag, so it must agree."""
        item = self.listing()[0]
        self.assertTrue(item["purge_blocked"])
        self.assertIn("no recorded job completion", item["purge_block_reason"])

    def test_an_attested_project_says_so_plainly_and_names_who(self):
        """The positive control for the blocked assertions above: something in
        this listing does come back unblocked, so `purge_blocked` is being
        computed rather than hardcoded true. And the owner sees WHO cleared it
        — an unblocked button with no name attached is an anonymous permission
        slip on an irreversible action."""
        self.set_project(**ATTESTED)
        item = self.listing()[0]
        self.assertFalse(item["purge_blocked"])
        self.assertIsNone(item["purge_block_reason"])
        self.assertTrue(item["no_completion_attested"])
        self.assertEqual(item["no_completion_attested_by"], "adm1")
        self.assertEqual(item["no_completion_reason"],
                         "Permit withdrawn; no work was ever performed.")

    def test_the_listing_agrees_with_the_endpoint_on_every_state(self):
        """ONE DEFINITION, ASKED TWICE. The screen must never grey out a
        control the server would have allowed, nor offer one it will refuse.
        Checked across all four states rather than on a single fixture, since
        a listing hardcoded to either answer passes any single case."""
        states = [
            ("nothing recorded", {}, True),
            ("attested never completed", dict(ATTESTED), False),
            ("completed recently", _completion("2025-06-01"), True),
            ("completed long ago", _completion("2010-01-01"), False),
        ]
        for label, doc, expect_blocked in states:
            with self.subTest(state=label):
                self.set_project(**doc)
                self.assertEqual(self.listing()[0]["purge_blocked"],
                                 expect_blocked)
                if expect_blocked:
                    self.assertEqual(self.purge_refused().status_code, 409)
                else:
                    self.assertEqual(self.purge()["project_id"], PID)

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

    def test_the_attestation_is_never_granted_by_this_module(self):
        """The way through the absence rule is a PERSON. The module may READ
        `no_completion_attested`; it must never contain the machinery to set
        one, because an attestation the code awards itself is not an
        attestation at all — it is the inference this whole file refuses."""
        src = self._retention_source()
        self.assertIn("no_completion_attested", src)  # positive control
        self.assertEqual([], self._offenders(src, (
            'no_completion_attested"] =', "no_completion_attested'] =",
            'no_completion_attested": True', "no_completion_attested=True",
        )))

    def test_the_absence_refusal_is_not_time_based(self):
        """No age releases it and no age produces it. A future edit that gives
        the absent-completion branch a grace period, a cutoff or a
        "grandfathered before" date trips this."""
        src = self._retention_source()
        branch = src[src.index("if eligible is None:"):]
        branch = branch[:branch.index("# Compared as")]
        self.assertIn("no_completion_attested", branch)  # positive control
        self.assertEqual([], self._offenders(branch, (
            "timedelta", "days", "today", "datetime", "date(",
        )))

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
