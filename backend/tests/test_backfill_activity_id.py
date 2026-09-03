"""THE CREW ROW THAT CANNOT BE REACHED, AND THE ONE THING THAT CAN REACH IT.

THE DEAD END. POST /logbooks/{id}/activity-photo pushes through arrayFilters
keyed on `activity_id` — identity, never position, because an index stops
naming the same row the moment one moves. A crew row that carries no
`activity_id` therefore cannot be reached by any id a client could send, and
the endpoint says so: 409 ACTIVITY_HAS_NO_IDENTITY. Honest, and a dead end on
real historical records.

WHAT THE INVESTIGATION FOUND, and it is what makes a backfill possible at all:

  WHERE THE FIELD COMES FROM. `EMPTY_ACTIVITY` in dailyJobsiteModel.js is the
  only writer of it, added 2026-08-10 (f49ddb5). The BACKEND has never written
  it — the whole of server.py reads `activity_id` in exactly two places, the
  capture-photo R2 key and the append route, and NEITHER renderer prints it. It
  is a row identity, not statutory content: BC 3301.2 asks for crews,
  headcounts, work performed and weather, and none of those move here.

  THE WINDOW IS WIDER THAN THE FIELD. `withActivityIds` — the client-side
  backfill that mints an id for a stored row that has none — landed 2026-08-31
  (2fa1293), three weeks later. So a log HYDRATED and re-saved between those
  dates kept its id-less rows too. Only the two log types that carry
  activities[].photos are affected in practice: daily_jobsite and
  fall_protection.

  AND THE CLIENT-SIDE BACKFILL CANNOT REACH A FILED LOG, which is the whole
  problem: `withActivityIds` runs on hydrate and only reaches the server
  through a save, and a filed log refuses every save (423, or 409
  FILED_LOG_DATA_IMMUTABLE). The rows that need it most are exactly the rows it
  cannot touch.

WHY POSITION IS STILL REFUSED AT REQUEST TIME. An `activity_index` parameter on
the append route would work for the panel that renders `filedLog.data
.activities` in stored order — and would be permanently available to every
other caller, on every log, forever. daily_jobsite.jsx:216-228 records what
that costs: the screen's list is NOT the server's (reconcileCrewsWithRoster
lifts unassigned-worker rows to the tail, commitAddCrew appends after them), so
an index from a client is a photograph on another crew's row of a signed
record. Widening the API permanently to serve a bounded historical set is the
wrong trade. The migration below makes the EXISTING identity path work instead,
and the route keeps "identity, never position" intact.

WHY THE POSITION IS SAFE INSIDE THE MIGRATION. It never crosses the wire. It is
read off the stored array, server-side, on a FILED log — a document whose
`data` no writer may rewrite (that is the guard this whole feature routes
around) — and the write that uses it is pinned to the array it read: same
length, that row still id-less, and the row's own content unchanged.

    python -m pytest tests/test_backfill_activity_id.py -q
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))

import backfill_activity_id as M  # noqa: E402


LB = "6a5f63bc147407d3261df2c7"


def _row(**over):
    r = {"crew_id": "C1", "company": "Kestrel Electric", "num_workers": "4",
         "work_description": "branch rough-in", "work_locations": "3rd floor",
         "photos": []}
    r.update(over)
    return r


def _doc(rows, **over):
    d = {"_id": LB, "project_id": "proj1", "log_type": "daily_jobsite",
         "date": "2026-08-07", "status": "submitted", "is_locked": False,
         "is_deleted": False, "data": {"weather": "Clear", "activities": rows}}
    d.update(over)
    return d


# ══════════════════════════════════════════════════════════════════════════
#  1. WHAT IT WOULD CHANGE
# ══════════════════════════════════════════════════════════════════════════

class ThePlan(unittest.TestCase):

    def test_an_idless_row_is_planned_with_a_derived_id(self):
        plan = M.plan_for_document(_doc([_row(), _row(crew_id="C2")]))
        self.assertIsNone(plan["refusal"])
        self.assertEqual([(s["index"], s["activity_id"]) for s in plan["stamps"]],
                         [(0, f"legacy_{LB}_0"), (1, f"legacy_{LB}_1")])

    def test_the_id_is_DETERMINISTIC(self):
        """A second run must plan the same ids, or a re-run after a partial
        apply would mint a different identity for the same row."""
        doc = _doc([_row(), _row()])
        self.assertEqual(M.plan_for_document(doc)["stamps"],
                         M.plan_for_document(copy.deepcopy(doc))["stamps"])

    def test_a_row_that_ALREADY_has_an_id_is_left_alone(self):
        plan = M.plan_for_document(_doc([
            _row(activity_id="act_1754500000000_0"), _row(),
        ]))
        self.assertEqual([s["index"] for s in plan["stamps"]], [1])
        self.assertEqual(plan["already_identified"], 1)

    def test_null_and_empty_count_as_ABSENT(self):
        """Absence, null and "" are ONE STATE — the same rule the endpoint
        applies when it decides a row has no identity (`str(...).strip()`)."""
        plan = M.plan_for_document(_doc([
            _row(activity_id=None), _row(activity_id=""), _row(activity_id="   "),
        ]))
        self.assertEqual([s["index"] for s in plan["stamps"]], [0, 1, 2])

    def test_a_non_dict_row_is_skipped_not_stamped(self):
        plan = M.plan_for_document(_doc([_row(), "not a row", None]))
        self.assertEqual([s["index"] for s in plan["stamps"]], [0])
        self.assertEqual(plan["unstampable"], 2)

    def test_a_document_with_nothing_to_do_plans_nothing(self):
        plan = M.plan_for_document(_doc([_row(activity_id="act_1")]))
        self.assertEqual(plan["stamps"], [])

    def test_it_is_IDEMPOTENT_over_its_own_output(self):
        """THE PROPERTY THAT MAKES A HAND-RUN SAFE. Apply, then plan again: the
        second pass has nothing left to do."""
        doc = _doc([_row(), _row()])
        for s in M.plan_for_document(doc)["stamps"]:
            doc["data"]["activities"][s["index"]]["activity_id"] = s["activity_id"]
        self.assertEqual(M.plan_for_document(doc)["stamps"], [])


# ══════════════════════════════════════════════════════════════════════════
#  2. THE REFUSALS — A DOCUMENT IT WILL NOT TOUCH
# ══════════════════════════════════════════════════════════════════════════

class ItRefusesRatherThanGuesses(unittest.TestCase):

    def test_a_minted_id_that_COLLIDES_refuses_the_WHOLE_document(self):
        """THE ONE THAT WOULD PUT A PHOTOGRAPH ON THE WRONG CREW. The append
        route pushes through `arrayFilters: [{act.activity_id: X}]`, which
        matches EVERY row carrying X — so two rows sharing an id means one
        photograph landing on both. The document is refused whole, not
        row-by-row: a partial stamp of a document with a collision in it is
        still a document with a collision in it."""
        plan = M.plan_for_document(_doc([
            _row(activity_id=f"legacy_{LB}_1"), _row(),
        ]))
        self.assertEqual(plan["refusal"], "ID_COLLISION")
        self.assertEqual(plan["stamps"], [])

    def test_a_log_that_is_NOT_filed_is_refused(self):
        """Scope. A draft's rows get an id from the ordinary editor the next
        time it is opened and saved (withActivityIds), and its array is live —
        stamping it would be a write fighting the client for no gain. The dead
        end is only a dead end on a record the CP can no longer save."""
        self.assertEqual(
            M.plan_for_document(_doc([_row()], status="draft"))["refusal"],
            "NOT_FILED",
        )

    def test_a_LOCKED_log_is_in_scope_even_with_status_draft(self):
        """The same pair isOpenForEditing asks. An IMMEDIATE type freezes on
        signature; reading only `status` would miss those."""
        plan = M.plan_for_document(
            _doc([_row()], status="draft", is_locked=True))
        self.assertIsNone(plan["refusal"])

    def test_a_soft_deleted_log_is_refused(self):
        self.assertEqual(
            M.plan_for_document(_doc([_row()], is_deleted=True))["refusal"],
            "DELETED",
        )

    def test_a_document_with_no_activities_array_is_refused(self):
        self.assertEqual(
            M.plan_for_document(_doc([], data={"weather": "Clear"}))["refusal"],
            "NO_ACTIVITIES",
        )


# ══════════════════════════════════════════════════════════════════════════
#  3. THE WRITE IS PINNED TO THE ARRAY IT READ
# ══════════════════════════════════════════════════════════════════════════

class _Logbooks:
    """Applies a positional $set only when the filter really matches."""

    def __init__(self, doc):
        self.doc = doc
        self.updates = []

    async def update_one(self, q, u, *a, **k):
        self.updates.append((copy.deepcopy(q), copy.deepcopy(u)))
        rows = ((self.doc.get("data") or {}).get("activities") or [])
        for key, want in q.items():
            if key == "_id":
                if self.doc["_id"] != want:
                    return _R(0)
                continue
            if key == "data.activities":
                if want != {"$size": len(rows)}:
                    return _R(0)
                continue
            parts = key.split(".")
            cur = self.doc
            for p in parts:
                if isinstance(cur, dict):
                    cur = cur.get(p)
                elif isinstance(cur, list) and p.isdigit() and int(p) < len(cur):
                    cur = cur[int(p)]
                else:
                    cur = None
            if isinstance(want, dict) and "$in" in want:
                probe = cur.strip() if isinstance(cur, str) else cur
                if probe not in want["$in"]:
                    return _R(0)
            elif cur != want:
                return _R(0)
        for path, val in (u.get("$set") or {}).items():
            parts = path.split(".")
            cur = self.doc
            for p in parts[:-1]:
                cur = cur[int(p)] if isinstance(cur, list) else cur.setdefault(p, {})
            last = parts[-1]
            if isinstance(cur, list):
                cur[int(last)] = val
            else:
                cur[last] = val
        return _R(1)


class _R:
    def __init__(self, matched):
        self.matched_count = matched
        self.modified_count = matched


class _DB:
    def __init__(self, logbooks):
        self.logbooks = logbooks


def _apply(doc):
    coll = _Logbooks(doc)
    plan = M.plan_for_document(doc)
    out = asyncio.new_event_loop().run_until_complete(
        M.apply_plan(_DB(coll), plan),
    )
    return out, coll


class TheWriteIsNarrowAndPinned(unittest.TestCase):

    def test_it_stamps_exactly_the_rows_it_planned(self):
        doc = _doc([_row(), _row(activity_id="act_9"), _row()])
        out, coll = _apply(doc)
        ids = [r.get("activity_id") for r in doc["data"]["activities"]]
        self.assertEqual(ids, [f"legacy_{LB}_0", "act_9", f"legacy_{LB}_2"])
        self.assertEqual(out["stamped"], 2)

    def test_NOTHING_ELSE_IN_data_MOVES(self):
        """The statutory content the CP attested to, byte for byte."""
        doc = _doc([_row(), _row(crew_id="C2", num_workers="7")])
        before = copy.deepcopy(doc["data"])
        _apply(doc)
        after = copy.deepcopy(doc["data"])
        for rows in (before["activities"], after["activities"]):
            for r in rows:
                r.pop("activity_id", None)
        self.assertEqual(before, after)

    def test_updated_at_is_NOT_moved(self):
        """A system identity backfill is not an edit of the record. Moving
        `updated_at` on every historical log would tell every reader — and
        every sweep that sorts on it — that hundreds of filed records changed
        on the night this was run, which is not true of any of them."""
        doc = _doc([_row()], updated_at="2026-08-07T19:00:00Z")
        _apply(doc)
        self.assertEqual(doc["updated_at"], "2026-08-07T19:00:00Z")
        for _q, u in _Logbooks(doc).updates:
            self.assertNotIn("updated_at", u.get("$set", {}))

    def test_the_act_IS_recorded_on_the_document(self):
        """base64_purged_at's precedent — a stamp the server writes recording
        what it did. Without it the only evidence a signed record was touched
        is this script's stdout."""
        doc = _doc([_row()])
        _apply(doc)
        self.assertIn(M.STAMP_FIELD, doc)

    def test_every_write_is_pinned_to_the_array_it_read(self):
        doc = _doc([_row(), _row()])
        _, coll = _apply(doc)
        row_writes = [(q, u) for q, u in coll.updates
                      if any("activities" in k for k in u.get("$set", {}))]
        self.assertEqual(len(row_writes), 2)
        for q, u in row_writes:
            self.assertEqual(q["data.activities"], {"$size": 2},
                             "the array length is asserted")
            self.assertEqual(len(u["$set"]), 1, "one path, one value")
            path = next(iter(u["$set"]))
            self.assertIn(path, q, "the row being stamped is asserted id-less")
            self.assertEqual(q[path], {"$in": [None, ""]})

    def test_a_row_whose_CONTENT_changed_is_not_stamped(self):
        """THE RACE. The plan was built from a read; if the row is not the row
        that was read, the write must MISS rather than land on whatever is
        there now. Simulated by editing the document between plan and apply."""
        doc = _doc([_row(), _row(crew_id="C2")])
        coll = _Logbooks(doc)
        plan = M.plan_for_document(copy.deepcopy(doc))
        doc["data"]["activities"][0]["company"] = "Someone Else Entirely"
        out = asyncio.new_event_loop().run_until_complete(
            M.apply_plan(_DB(coll), plan))
        self.assertIsNone(doc["data"]["activities"][0].get("activity_id"))
        self.assertEqual(doc["data"]["activities"][1]["activity_id"],
                         f"legacy_{LB}_1")
        self.assertEqual(out["missed"], 1)
        self.assertEqual(out["stamped"], 1)

    def test_a_dry_run_writes_NOTHING(self):
        doc = _doc([_row(), _row()])
        before = copy.deepcopy(doc)
        coll = _Logbooks(doc)
        plan = M.plan_for_document(doc)
        asyncio.new_event_loop().run_until_complete(
            M.apply_plan(_DB(coll), plan, dry_run=True))
        self.assertEqual(doc, before)
        self.assertEqual(coll.updates, [])


# ══════════════════════════════════════════════════════════════════════════
#  4. THE SCRIPT AGREES WITH THE ENDPOINT IT EXISTS TO UNBLOCK
# ══════════════════════════════════════════════════════════════════════════

class ItMatchesTheRoute(unittest.TestCase):

    SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

    def test_EVERY_reader_of_activity_id_lives_in_the_append_route(self):
        """TWO PREMISES OF THE WHOLE DESIGN, asserted as one fact.

        (1) The backend never MINTS an activity_id, so this script is not
            minting a competing identity for a row something else also names.
        (2) No renderer PRINTS one, so stamping a signed record with it is not
            a change to what the CP attested to. Both PDF renderers and the
            combined report read crew_id / company / num_workers /
            work_description / work_locations off a crew row and nothing else.

        Checked by LOCATION, not by count. A count would pass just as happily
        if the append route were deleted and a renderer started printing the
        field; this fails unless every occurrence is inside the one function
        that is allowed to have one.
        """
        import re
        start = self.SRC.index("async def append_activity_photo(")
        end = self.SRC.index("async def _purge_finalized_photo_base64")
        self.assertLess(start, end)
        hits = [m.start() for m in
                re.finditer(r"[\"']activity_id[\"']", self.SRC)]
        # POSITIVE CONTROL: there ARE occurrences. A regex that matched nothing
        # would satisfy every assertion below and prove nothing at all.
        self.assertGreater(len(hits), 0, "no reader found — this check is stale")
        outside = [self.SRC[:h].count("\n") + 1 for h in hits
                   if not (start <= h < end)]
        self.assertEqual(outside, [],
                         f"activity_id is read outside the append route at "
                         f"lines {outside}")

    def test_the_minted_id_survives_the_r2_key_sanitiser(self):
        """The id becomes a path segment in logbook-photos/{project}/{id}/. A
        value the sanitiser rewrites would key the object under a name the row
        does not carry."""
        import server
        ident = M.minted_id(LB, 7)
        self.assertEqual(server._logbook_photo_key_segment(ident), ident)

    def test_the_prefix_cannot_collide_with_a_client_minted_id(self):
        """Client ids are `act_{Date.now()}_{seq}` (dailyJobsiteModel) and
        `fp_{base36}_{seq}` (fallProtectionModel). Neither can start with
        this."""
        self.assertTrue(M.minted_id(LB, 0).startswith("legacy_"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
