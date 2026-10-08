"""GC group alerts — full DOB coverage + DOT.

  * New kinds: DOB complaint, stop-work order issued / rescinded, violation
    status change (DOB 'Action' only), permit status change (issued /
    expired / revoked), DOT summons, DOT permit expiring / expired.
  * Each posts once ever; no backfill, PER KIND (a kind added later never
    posts a project's history); per-type switch; send window; bot switch.
  * One format for every alert; AI wording only if every number / date /
    code / amount is in the record, else the template.
  * DOT records matched by BIN, then BBL, then exact address — never fuzzy.
  * Another company's records are never posted.
  * The morning brief carries the new types.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import dot_sync, wa_alerts, wa_brief, wa_gc  # noqa: E402
from tests.test_whatsapp_gc_alerts import (  # noqa: E402
    CO_A, CO_B, G_GC, NOON, NIGHT, _Ctx, _confirm, _group_sends, _no_ai,
    _permit, _violation, _world as _base_world,
)

SYNCED = NOON - timedelta(days=30)


def _world(**extra):
    """proj_a has had its first DOT sync long ago, unless a test says not."""
    extra.setdefault(server.DOT_SYNC_STATE, [
        {"_id": "proj_a", "company_id": CO_A,
         "first_synced_at": SYNCED, "synced_at": SYNCED}])
    return _base_world(**extra)

TODAY = wa_gc.today_et(NOON)


def _run(coro):
    return asyncio.run(coro)


def _complaint(raw, **kw):
    row = {"_id": f"c_{raw}", "project_id": "proj_a", "company_id": CO_A,
           "record_type": "complaint", "raw_dob_id": f"complaint:{raw}",
           "complaint_number": f"C{raw}", "complaint_date": "2026-10-06",
           "complaint_status": "ACTIVE", "current_status": "ACTIVE",
           "category_label": "Work without permit",
           "dob_link": f"https://dob.example/c{raw}", "detected_at": NOON}
    row.update(kw)
    return row


def _swo(raw, **kw):
    row = {"_id": f"s_{raw}", "project_id": "proj_a", "company_id": CO_A,
           "record_type": "swo", "raw_dob_id": f"swo:{raw}",
           "stop_work_order_number": f"SWO{raw}", "violation_date": "2026-10-06",
           "status": "ACTIVE", "current_status": "ACTIVE",
           "description": "Full stop work order",
           "dob_link": f"https://dob.example/s{raw}", "detected_at": NOON}
    row.update(kw)
    return row


def _dot(raw, kind="dot_violation", co=CO_A, pid="proj_a", **kw):
    row = {"_id": f"d_{raw}", "project_id": pid, "company_id": co,
           "record_type": kind, "raw_id": f"oath:{raw}", "number": raw,
           "issue_date": "2026-10-06",
           "status": "ISSUED & PRINTED" if kind == "dot_permit" else "DEFAULT",
           "description": "Sidewalk obstruction",
           "link": f"https://data.example/{raw}", "detected_at": NOON}
    row.update(kw)
    return row


def _first_run(db):
    """Confirm the GC group and run once (the baseline)."""
    _confirm()
    _run(server._gc_alerts_tick(NOON))


class EachNewKindPostsOnce(unittest.TestCase):

    def _posts_once(self, add_rows, collection="dob_logs", expect=()):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _first_run(db)
            self.assertEqual(_group_sends(c), [])
            getattr(db, collection).rows.extend(add_rows)
            r = _run(server._gc_alerts_tick(NOON))
            _run(server._gc_alerts_tick(NOON + timedelta(hours=1)))
            sends = _group_sends(c)
        self.assertEqual(len(sends), 1, sends)
        self.assertEqual(r["posted"], 1)
        msg = sends[0]["message"]
        for piece in expect:
            self.assertIn(piece, msg)
        lines = msg.split("\n")
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith(("🔴 ", "🟠 ")))
        self.assertTrue(lines[3].startswith("Source: "))
        return msg

    def test_complaint(self):
        msg = self._posts_once([_complaint("1")], expect=(
            "🔴 Main St", "New DOB complaint: Work without permit.",
            "Complaint #C1 · Oct 6, 2026 · ACTIVE",
            "Source: DOB · https://dob.example/c1"))
        self.assertNotIn("311", msg)

    def test_a_311_complaint_is_not_a_dob_complaint(self):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _first_run(db)
            db.dob_logs.rows.append(_complaint("2", source="311"))
            _run(server._gc_alerts_tick(NOON))
        self.assertEqual(_group_sends(c), [])

    def test_stop_work_order_issued(self):
        self._posts_once([_swo("1")], expect=(
            "🔴 Main St", "DOB issued a stop-work order: Full stop work order.",
            "Stop-work order #SWO1 · Oct 6, 2026 · ACTIVE"))

    def test_stop_work_order_from_a_violation_dataset(self):
        row = _swo("9", stop_work_order_number=None, violation_number="V-9")
        self._posts_once([row], expect=("Stop-work order #V-9",))

    def test_stop_work_order_rescinded(self):
        db = _world(dob_logs=[_swo("3")])
        with _Ctx(db=db) as c, _no_ai():
            _first_run(db)                              # the SWO is baseline
            db.dob_logs.rows.append(_swo(
                "3", _id="s_3b", status="RESCINDED", current_status="RESCINDED",
                previous_status="ACTIVE", status_changed_at=NOON + timedelta(minutes=5),
                detected_at=NOON + timedelta(minutes=5)))
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=10)))
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=20)))
        sends = _group_sends(c)
        self.assertEqual(len(sends), 1)
        self.assertIn("🟠 Main St\nDOB rescinded the stop-work order.", sends[0]["message"])
        self.assertIn("Stop-work order #SWO3 · Oct 6, 2026 · RESCINDED", sends[0]["message"])

    def test_violation_status_change_only_when_dob_marks_it_action(self):
        db = _world(dob_logs=[_violation("7")])
        with _Ctx(db=db) as c, _no_ai():
            _first_run(db)
            db.dob_logs.rows += [
                _violation("7", _id="v_7b", status="CERTIFIED", current_status="CERTIFIED",
                           previous_status="ACTIVE", severity="Info",
                           status_changed_at=NOON + timedelta(minutes=1)),
                _violation("8", _id="v_8b", status="HEARING", current_status="HEARING",
                           previous_status="ACTIVE", severity="Action",
                           status_changed_at=NOON + timedelta(minutes=1)),
            ]
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=5)))
        texts = [s["message"] for s in _group_sends(c)]
        changes = [t for t in texts if "status changed" in t]
        self.assertEqual(len(changes), 1)
        self.assertIn("Violation status changed: ACTIVE → HEARING.", changes[0])
        self.assertFalse(any("CERTIFIED" in t for t in texts))

    def test_permit_status_change(self):
        exp = (TODAY + timedelta(days=200)).isoformat()
        db = _world(dob_logs=[_permit("40", exp, permit_status="ISSUED",
                                      current_status="ISSUED")])
        with _Ctx(db=db) as c, _no_ai():
            _first_run(db)
            db.dob_logs.rows.append(_permit(
                "40", exp, _id="p_40b", permit_status="REVOKED",
                current_status="REVOKED", previous_status="ISSUED",
                status_changed_at=NOON + timedelta(minutes=1)))
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=5)))
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=9)))
        sends = _group_sends(c)
        self.assertEqual(len(sends), 1)
        self.assertIn("Plumbing permit status changed: ISSUED → REVOKED.", sends[0]["message"])
        self.assertIn("Permit #J40", sends[0]["message"])

    def test_dot_summons(self):
        self._posts_once([_dot("D1")], collection="dot_logs", expect=(
            "🔴 Main St", "New DOT summons: Sidewalk obstruction.",
            "DOT summons #D1 · Oct 6, 2026 · DEFAULT",
            "Source: DOT · https://data.example/D1"))

    def test_dot_permit_thresholds_and_expired(self):
        exp = (TODAY + timedelta(days=5)).isoformat()
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _first_run(db)
            db.dot_logs.rows.append(_dot("P1", kind="dot_permit", raw_id="dotpermit:P1",
                                         expiration_date=exp))
            _run(server._gc_alerts_tick(NOON))
            _run(server._gc_alerts_tick(NOON + timedelta(days=4)))   # 1-day threshold
            _run(server._gc_alerts_tick(NOON + timedelta(days=6)))   # expired
            _run(server._gc_alerts_tick(NOON + timedelta(days=7)))
        texts = [s["message"] for s in _group_sends(c)]
        self.assertEqual(len(texts), 3, texts)
        self.assertIn("DOT permit expires in 5 days", texts[0])
        self.assertIn("DOT permit expires tomorrow", texts[1])
        self.assertIn("DOT permit expired on", texts[2])
        self.assertTrue(all("Source: DOT" in t for t in texts))


class DotWaitsForTheFirstSync(unittest.TestCase):
    """The GC tick runs 4 min after boot, the DOT sync after 8. A DOT
    baseline taken before the project's first sync would record nothing,
    and the sync's rows would then post as new."""

    def _oath(self):
        return {"ticket_number": "T1", "issuing_agency": "DEPT OF TRANSPORTATION",
                "violation_date": "2026-10-06", "hearing_status": "DEFAULT",
                "violation_location_borough": "BROOKLYN",
                "violation_location_block_no": "1523", "violation_location_lot_no": "1"}

    def _db(self, **kw):
        db = _world(**{server.DOT_SYNC_STATE: [], **kw})
        p = next(p for p in db.projects.rows if p["_id"] == "proj_a")
        p.update({"address": "588 Thomas S Boyland St, Brooklyn, NY",
                  "bbl": "3015230001"})
        return db

    def _fetch(self, recs, ok=True):
        async def fetch(dataset, params):
            if not ok:
                return None
            return recs if dataset == dot_sync.OATH_DATASET else []
        return fetch

    def test_gc_tick_before_first_sync_then_sync_posts_nothing(self):
        db = self._db()
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            r = _run(server._gc_alerts_tick(NOON))                  # boot + 4 min
            self.assertEqual(r["dot_waiting_sync"], 1)
            ids = {x["_id"] for x in db[server.WA_LEDGER].rows}
            self.assertNotIn(wa_alerts.kind_baseline_id("proj_a", "dot_violation"), ids)
            _run(server._dot_sync_tick(now=NOON, fetch=self._fetch([self._oath()])))
            self.assertEqual(len(db.dot_logs.rows), 1)
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=15)))
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=30)))
        self.assertEqual(_group_sends(c), [])
        seen = [x for x in db[server.WA_LEDGER].rows if x.get("kind") == "gc_dot_violation"]
        self.assertEqual([x["status"] for x in seen], ["baseline"])

    def test_after_the_first_sync_a_new_summons_posts(self):
        db = self._db()
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._gc_alerts_tick(NOON))
            _run(server._dot_sync_tick(now=NOON, fetch=self._fetch([self._oath()])))
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=15)))
            later = {**self._oath(), "ticket_number": "T2"}
            _run(server._dot_sync_tick(now=NOON + timedelta(hours=2),
                                       fetch=self._fetch([self._oath(), later])))
            _run(server._gc_alerts_tick(NOON + timedelta(hours=2, minutes=15)))
        texts = [s["message"] for s in _group_sends(c)]
        self.assertEqual(len(texts), 1, texts)
        self.assertIn("#T2", texts[0])

    def test_a_failed_sync_is_not_a_first_sync(self):
        db = self._db()
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._dot_sync_tick(now=NOON, fetch=self._fetch([], ok=False)))
            self.assertEqual(db[server.DOT_SYNC_STATE].rows, [])
            db.dot_logs.rows.append(_dot("D1"))
            r = _run(server._gc_alerts_tick(NOON))
        self.assertEqual((r["dot_waiting_sync"], _group_sends(c)), (1, []))

    def test_first_synced_at_is_kept_on_later_syncs(self):
        db = self._db()
        with patch.object(server, "db", db):
            _run(server._dot_sync_tick(now=NOON, fetch=self._fetch([self._oath()])))
            first = db[server.DOT_SYNC_STATE].rows[0]["first_synced_at"]
            _run(server._dot_sync_tick(now=NOON, fetch=self._fetch([self._oath()])))
        row = db[server.DOT_SYNC_STATE].rows[0]
        self.assertEqual((row["first_synced_at"], row["company_id"]), (first, CO_A))
        self.assertGreaterEqual(row["synced_at"], first)

    def test_first_sync_finishing_mid_tick_waits_for_the_next_tick(self):
        """The state is read before the DOT rows: a sync that completes
        between the two reads leaves this tick treating DOT as not synced."""
        db = self._db()
        real = server._gc_project_records

        async def records_then_sync(project_id, company_id):
            out = await real(project_id, company_id)        # snapshot: no rows
            await server._dot_sync_tick(now=NOON, fetch=self._fetch([self._oath()]))
            return out

        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            with patch.object(server, "_gc_project_records", records_then_sync):
                r = _run(server._gc_alerts_tick(NOON))
            self.assertEqual(r["dot_waiting_sync"], 1)
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=15)))
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=30)))
        self.assertEqual(_group_sends(c), [])

    def test_marker_written_before_the_first_sync_is_rebaselined(self):
        """The prod case: #687 wrote DOT markers before any DOT row existed."""
        db = self._db()
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            for k in wa_alerts.DOT_KINDS:
                db[server.WA_LEDGER].rows.append({
                    "_id": wa_alerts.kind_baseline_id("proj_a", k),
                    "kind": "gc_baseline", "project_id": "proj_a",
                    "company_id": CO_A, "status": "baseline",
                    "created_at": NOON - timedelta(hours=1)})
            _run(server._gc_alerts_tick(NOON))          # DOB baseline only
            _run(server._dot_sync_tick(now=NOON, fetch=self._fetch([self._oath()])))
            r = _run(server._gc_alerts_tick(NOON + timedelta(minutes=15)))
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=30)))
        self.assertEqual(_group_sends(c), [])
        self.assertEqual(r["kinds_baselined"], len(wa_alerts.DOT_KINDS))
        marker = next(x for x in db[server.WA_LEDGER].rows if x["_id"]
                      == wa_alerts.kind_baseline_id("proj_a", "dot_violation"))
        self.assertGreater(server._as_utc(marker["created_at"]),
                           server._as_utc(db[server.DOT_SYNC_STATE].rows[0]
                                          ["first_synced_at"]))


class DotPermitStatuses(unittest.TestCase):

    def test_an_already_expired_or_voided_permit_never_alerts(self):
        exp = (TODAY + timedelta(days=5)).isoformat()
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _first_run(db)
            for i, st in enumerate(("EXPIRED", "EXPIRED UNDER GUARANTEE",
                                    "VOIDED AFTER ISSUE", "DELINQUENT - FEES")):
                db.dot_logs.rows.append(_dot(f"X{i}", kind="dot_permit",
                                             raw_id=f"dotpermit:X{i}", status=st,
                                             expiration_date=exp))
            db.dot_logs.rows.append(_dot("Y", kind="dot_permit", raw_id="dotpermit:Y",
                                         status="EXPIRED",
                                         expiration_date=(TODAY - timedelta(days=3)).isoformat()))
            _run(server._gc_alerts_tick(NOON))
            _run(server._gc_alerts_tick(NOON + timedelta(days=10)))
        self.assertEqual(_group_sends(c), [])


class NoBackfill(unittest.TestCase):

    def test_existing_records_of_every_kind_post_nothing(self):
        exp = (TODAY + timedelta(days=5)).isoformat()
        db = _world(dob_logs=[_complaint("1"), _swo("1"), _violation("1")],
                    dot_logs=[_dot("D1"), _dot("P1", kind="dot_permit",
                                               raw_id="dotpermit:P1", expiration_date=exp)])
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            r = _run(server._gc_alerts_tick(NOON))
            _run(server._gc_alerts_tick(NOON + timedelta(hours=1)))
        self.assertEqual(_group_sends(c), [])
        self.assertEqual(r["baselined"], 1)
        self.assertEqual(r["kinds_baselined"], len(wa_alerts.NEW_KINDS))

    def test_a_project_baselined_before_the_new_kinds_posts_no_history(self):
        """The original GC alerts already ran for this project (its marker is
        there); complaints it already had must not post when the new kinds
        arrive — but a new violation still does."""
        db = _world(dob_logs=[_complaint("old")])
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._gc_ledger_insert(wa_gc.baseline_id("proj_a"),
                                          kind="gc_baseline", project_id="proj_a",
                                          company_id=CO_A, status="baseline"))
            _run(server._gc_alerts_tick(NOON))
            self.assertEqual(_group_sends(c), [])
            db.dob_logs.rows += [_complaint("new"), _violation("new")]
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=5)))
        texts = [s["message"] for s in _group_sends(c)]
        self.assertEqual(len(texts), 2)
        self.assertTrue(any("#Cnew" in t for t in texts))
        self.assertFalse(any("#Cold" in t for t in texts))


class SwitchesWindowAndScope(unittest.TestCase):

    def test_a_kind_switched_off_is_seen_not_posted_later(self):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _first_run(db)
            _run(server.patch_project_whatsapp_alerts(
                "proj_a", {"complaint_alerts": False}, _admin(db)))
            db.dob_logs.rows += [_complaint("9"), _violation("9")]
            r = _run(server._gc_alerts_tick(NOON))
            self.assertEqual(r["seen_while_off"], 1)
            _run(server.patch_project_whatsapp_alerts(
                "proj_a", {"complaint_alerts": True}, _admin(db)))
            _run(server._gc_alerts_tick(NOON + timedelta(hours=1)))
        texts = [s["message"] for s in _group_sends(c)]
        self.assertEqual(len(texts), 1)
        self.assertIn("Violation #V9", texts[0])

    def test_every_switch_can_be_set(self):
        db = _world()
        with _Ctx(db=db):
            _confirm()
            out = _run(server.patch_project_whatsapp_alerts(
                "proj_a", {k: False for k in wa_alerts.SWITCHES}, _admin(db)))
        self.assertTrue(all(out[k] is False for k in wa_alerts.SWITCHES))

    def test_send_window_holds_then_sends(self):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _first_run(db)
            _run(server.patch_project_whatsapp_alerts(
                "proj_a", {"send_window": {"mode": "work_hours"}}, _admin(db)))
            db.dot_logs.rows.append(_dot("D7"))
            r = _run(server._gc_alerts_tick(NIGHT))
            self.assertEqual((r["held"], _group_sends(c)), (1, []))
            _run(server._gc_alerts_tick(NIGHT + timedelta(hours=11)))   # 9 AM ET
        self.assertEqual(len(_group_sends(c)), 1)

    def test_another_companys_dot_rows_never_post(self):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _first_run(db)
            db.dot_logs.rows.append(_dot("X1", co=CO_B))
            _run(server._gc_alerts_tick(NOON))
        self.assertEqual(_group_sends(c), [])

    def test_bot_off_group_posts_nothing(self):
        db = _world()
        with _Ctx(db=db) as c, _no_ai():
            _first_run(db)
            g = next(g for g in db.whatsapp_groups.rows if g["wa_group_id"] == G_GC)
            g["bot_config"] = {"bot_enabled": False}
            db.dob_logs.rows.append(_complaint("5"))
            _run(server._gc_alerts_tick(NOON))
            g["bot_config"] = {"bot_enabled": True}
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=5)))
        self.assertEqual(_group_sends(c), [])


def _admin(db):
    return dict(next(u for u in db.users.rows if u["_id"] == "u_admin"),
                id="u_admin", account_status="approved")


class TheChecker(unittest.TestCase):

    def test_invented_values_fall_back_to_the_template(self):
        rec = _complaint("1")
        for invented in ("A DOB complaint about work without a permit, due by October 20, 2026.",
                         "A DOB complaint with a $5,000 fine.",
                         "A DOB complaint under code BC 3301."):
            with self.subTest(invented):
                self.assertEqual(
                    wa_alerts.what_line("complaint", rec, invented, today=TODAY),
                    "New DOB complaint: Work without permit.")

    def test_a_sentence_from_the_record_is_kept(self):
        rec = _complaint("1")
        self.assertEqual(
            wa_alerts.what_line("complaint", rec,
                                "Someone complained to DOB about work without a permit.",
                                today=TODAY),
            "Someone complained to DOB about work without a permit.")

    def test_status_and_date_lines_never_use_ai(self):
        rec = _swo("1", status="RESCINDED")
        self.assertEqual(
            wa_alerts.what_line("swo_rescinded", rec, "Anything at all.", today=TODAY),
            "DOB rescinded the stop-work order.")

    def test_no_number_no_post(self):
        self.assertFalse(wa_alerts.postable("complaint", _complaint("1", complaint_number="")))


class DotMatching(unittest.TestCase):

    P = {"address": "588 Thomas S Boyland St, Brooklyn, NY 11212", "bbl": "3015230001"}
    OATH = {"issuing_agency": "DEPT OF TRANSPORTATION", "ticket_number": "T1",
            "violation_location_borough": "BROOKLYN",
            "violation_location_block_no": "01523", "violation_location_lot_no": "0001",
            "violation_location_house": "588",
            "violation_location_street_name": "THOMAS S BOYLAND STREET"}
    PERMIT = {"permitnumber": "P1", "boroughname": "BROOKLYN",
              "permithousenumber": "588", "onstreetname": "THOMAS S BOYLAND STREET"}

    def _pk(self, project=None):
        return dot_sync.project_keys(project or self.P)

    def test_oath_bbl_first(self):
        self.assertEqual(dot_sync.match("dot_violation", self._pk(), self.OATH), "bbl")
        other_lot = {**self.OATH, "violation_location_lot_no": "0002"}
        self.assertIsNone(dot_sync.match("dot_violation", self._pk(), other_lot),
                          "a different BBL is another lot, whatever the address")

    def test_oath_missing_bbl_parts_fall_back_to_exact_address(self):
        rec = {**self.OATH, "violation_location_block_no": "00000",
               "violation_location_lot_no": "0000"}
        self.assertEqual(dot_sync.oath_keys(rec)["bbl"], "")
        self.assertEqual(dot_sync.match("dot_violation", self._pk(), rec), "address")
        for bad in ({**rec, "violation_location_house": "586"},
                    {**rec, "violation_location_street_name": "THOMAS BOYLAND ST"},
                    {**rec, "violation_location_borough": "QUEENS"}):
            with self.subTest(bad):
                self.assertIsNone(dot_sync.match("dot_violation", self._pk(), bad))

    def test_staten_island_as_oath_writes_it(self):
        rec = {"violation_location_borough": "STATEN IS",
               "violation_location_block_no": "00100", "violation_location_lot_no": "0005"}
        self.assertEqual(dot_sync.oath_keys(rec)["bbl"], "5001000005")
        self.assertEqual(dot_sync.oath_keys(rec)["boro"], "5")

    def test_both_dot_agency_spellings(self):
        for agency in ("DEPT OF TRANSPORTATION", "DEPT OF TRAN"):
            with self.subTest(agency):
                self.assertEqual(dot_sync.to_log("dot_violation", {
                    **self.OATH, "issuing_agency": agency})["number"], "T1")
        for agency in ("DEPT OF SANITATION", "DEPARTMENT OF BUILDINGS", ""):
            with self.subTest(agency):
                self.assertIsNone(dot_sync.to_log("dot_violation", {
                    **self.OATH, "issuing_agency": agency}))

    def test_oath_fields_kept(self):
        log = dot_sync.to_log("dot_violation", {
            **self.OATH, "violation_date": "2026-10-06T00:00:00.000",
            "hearing_status": "PENDING", "hearing_date": "2026-10-20T00:00:00.000",
            "charge_1_code_description": "OBSTRUCTION OF SIDEWALK",
            "penalty_imposed": "0", "balance_due": "0", "compliance_status": "N/A",
            "hearing_result": None})
        self.assertEqual((log["number"], log["status"], log["hearing_date"],
                          log["description"]),
                         ("T1", "PENDING", "2026-10-20T00:00:00.000",
                          "OBSTRUCTION OF SIDEWALK"))

    def test_permit_borough_house_street_all_three(self):
        self.assertEqual(dot_sync.match("dot_permit", self._pk(), self.PERMIT), "address")
        for bad in ({**self.PERMIT, "boroughname": "QUEENS"},
                    {**self.PERMIT, "permithousenumber": "586"},
                    {**self.PERMIT, "onstreetname": "THOMAS BOYLAND ST"},
                    {**self.PERMIT, "boroughname": ""}):
            with self.subTest(bad):
                self.assertIsNone(dot_sync.match("dot_permit", self._pk(), bad))

    def test_segment_permit_never_matches(self):
        seg = {**self.PERMIT, "permithousenumber": "", "fromstreetname": "X",
               "tostreetname": "Y"}
        self.assertTrue(dot_sync.is_segment_permit(seg))
        self.assertIsNone(dot_sync.match("dot_permit", self._pk(), seg))

    def test_permit_fields_kept(self):
        log = dot_sync.to_log("dot_permit", {
            **self.PERMIT, "permitissuedate": "2026-09-01T00:00:00.000",
            "issuedworkenddate": "2026-10-20T00:00:00.000",
            "permitstatusshortdesc": "ISSUED & PRINTED",
            "permittypedesc": "OCCUPANCY OF SIDEWALK", "permitteename": "ACME GC LLC"})
        self.assertEqual((log["number"], log["expiration_date"], log["status"],
                          log["permittee"]),
                         ("P1", "2026-10-20T00:00:00.000", "ISSUED & PRINTED", "ACME GC LLC"))

    def test_active_statuses(self):
        self.assertTrue(dot_sync.permit_is_active("ISSUED & PRINTED"))
        for s in ("EXPIRED", "EXPIRED UNDER GUARANTEE", "VOIDED AFTER ISSUE",
                  "DELINQUENT - FEES", "", None):
            with self.subTest(s):
                self.assertFalse(dot_sync.permit_is_active(s))

    def test_queries_are_narrowed(self):
        qs = dot_sync.queries(self._pk())
        oath_bbl = qs[0]["params"]["$where"]
        self.assertIn("violation_location_block_no = '01523'", oath_bbl)
        self.assertIn("violation_location_lot_no = '0001'", oath_bbl)
        self.assertIn("like 'DEPT OF TRAN%'", oath_bbl)
        permit = [q for q in qs if q["dataset"] == dot_sync.PERMIT_DATASET][0]
        self.assertIn("boroughname = 'BROOKLYN'", permit["params"]["$where"])
        self.assertIn("permithousenumber = '588'", permit["params"]["$where"])

    def test_no_borough_no_permit_query(self):
        pk = dot_sync.project_keys({"address": "588 Thomas S Boyland St"})
        self.assertFalse(any(q["dataset"] == dot_sync.PERMIT_DATASET
                             for q in dot_sync.queries(pk)))


class DotSyncJob(unittest.TestCase):

    def _world(self):
        db = _world()
        p = next(p for p in db.projects.rows if p["_id"] == "proj_a")
        p.update({"address": "588 Thomas S Boyland St, Brooklyn, NY", "bbl": "3015230001"})
        b = next(p for p in db.projects.rows if p["_id"] == "proj_b")
        b.update({"address": "9 Other St, Queens, NY", "bbl": "4000010001"})
        return db

    def test_matches_stores_and_logs_field_names_only(self):
        db = self._world()
        mine = {"ticket_number": "T1", "issuing_agency": "DEPT OF TRANSPORTATION",
                "violation_date": "2026-10-06", "hearing_status": "DEFAULT",
                "violation_location_borough": "BROOKLYN",
                "violation_location_block_no": "1523", "violation_location_lot_no": "1",
                "respondent_last_name": "Q7-RESPONDENT-VALUE-9Z"}
        neighbour = {**mine, "ticket_number": "T2", "violation_location_lot_no": "2"}
        calls, logged = [], []

        async def fetch(dataset, params):
            calls.append(dataset)
            return [mine, neighbour] if dataset == dot_sync.OATH_DATASET else []

        with patch.object(server, "db", db), \
                patch.object(server.logger, "info", lambda m, *a, **k: logged.append(m)):
            r = _run(server._dot_sync_tick(now=NOON, fetch=fetch))
            _run(server._dot_sync_tick(now=NOON + timedelta(hours=2), fetch=fetch))
        rows = db.dot_logs.rows
        self.assertEqual([(x["project_id"], x["number"], x["matched_by"]) for x in rows],
                         [("proj_a", "T1", "bbl")])
        self.assertEqual(rows[0]["company_id"], CO_A)
        self.assertEqual(r["new"], 1)
        field_lines = [m for m in logged if "[dot-sync] fields" in m]
        self.assertTrue(field_lines)
        self.assertIn("respondent_last_name", field_lines[0])
        self.assertNotIn("Q7-RESPONDENT-VALUE-9Z", " ".join(logged))

    def test_status_change_is_kept(self):
        db = self._world()
        rec = {"ticket_number": "T1", "issuing_agency": "DEPT OF TRANSPORTATION",
               "violation_location_borough": "BROOKLYN",
               "violation_location_block_no": "1523", "violation_location_lot_no": "1",
               "hearing_status": "DEFAULT"}

        async def fetch(dataset, params):
            return [rec] if dataset == dot_sync.OATH_DATASET else []

        with patch.object(server, "db", db):
            _run(server._dot_sync_tick(now=NOON, fetch=fetch))
            rec["hearing_status"] = "PAID IN FULL"
            r = _run(server._dot_sync_tick(now=NOON + timedelta(hours=2), fetch=fetch))
        row = db.dot_logs.rows[0]
        self.assertEqual((row["status"], row["previous_status"], r["changed"]),
                         ("PAID IN FULL", "DEFAULT", 1))

    def test_permits_segments_counted_and_permittee_flag(self):
        db = self._world()
        db.companies.rows = [{"_id": CO_A, "name": "Acme GC, LLC"},
                             {"_id": CO_B, "name": "B"}]
        exact = {"permitnumber": "P1", "boroughname": "BROOKLYN",
                 "permithousenumber": "588", "onstreetname": "THOMAS S BOYLAND STREET",
                 "permitstatusshortdesc": "ISSUED & PRINTED",
                 "issuedworkenddate": "2026-10-20T00:00:00.000",
                 "permitteename": "ACME GC LLC"}
        segment = {**exact, "permitnumber": "P2", "permithousenumber": "",
                   "fromstreetname": "A", "tostreetname": "B"}

        async def fetch(dataset, params):
            if dataset == dot_sync.PERMIT_DATASET and "BROOKLYN" in params["$where"]:
                return [exact, segment]
            return []

        with patch.object(server, "db", db):
            r = _run(server._dot_sync_tick(now=NOON, fetch=fetch))
        self.assertEqual(r["segment_permits"], 1)
        self.assertEqual([x["number"] for x in db.dot_logs.rows], ["P1"])
        self.assertTrue(db.dot_logs.rows[0]["permittee_is_company"])

    def test_a_failed_request_stores_nothing(self):
        db = self._world()

        async def fetch(dataset, params):
            return None

        with patch.object(server, "db", db):
            r = _run(server._dot_sync_tick(now=NOON, fetch=fetch))
        self.assertEqual(db.dot_logs.rows, [])
        self.assertGreater(r["failed"], 0)


class TheBrief(unittest.TestCase):

    def test_new_types_with_exact_fields(self):
        since = NOON - timedelta(hours=20)
        now = NOON
        dob = [_swo("3", detected_at=NOON - timedelta(days=5)),
               _swo("3", _id="s_3b", status="RESCINDED", current_status="RESCINDED",
                    previous_status="ACTIVE", status_changed_at=NOON - timedelta(hours=2),
                    detected_at=NOON - timedelta(hours=2)),
               _permit("50", "2027-06-01", permit_status="ISSUED", current_status="ISSUED",
                       detected_at=NOON - timedelta(days=50)),
               _permit("50", "2027-06-01", _id="p_50b", permit_status="EXPIRED",
                       current_status="EXPIRED", previous_status="ISSUED",
                       status_changed_at=NOON - timedelta(hours=3),
                       detected_at=NOON - timedelta(hours=3))]
        dot = [_dot("D1", detected_at=NOON - timedelta(hours=1)),
               _dot("P1", kind="dot_permit", raw_id="dotpermit:P1",
                    expiration_date=(TODAY + timedelta(days=4)).isoformat())]
        texts = [i["text"] for i in wa_brief.job_items(dob, since, now, dot)]
        self.assertIn("🔴 New DOT summons D1, issued Oct 6, DEFAULT. DOT.", texts)
        self.assertTrue(any(t.startswith("🟡 Stop-work order SWO3 changed ACTIVE → RESCINDED")
                            for t in texts), texts)
        self.assertTrue(any(t.startswith("🟡 Permit J50 changed ISSUED → EXPIRED")
                            for t in texts), texts)
        self.assertTrue(any(t.startswith("🟠 DOT permit P1 expires") and t.endswith("DOT.")
                            for t in texts), texts)

    def test_upcoming_oath_hearing(self):
        dot = [_dot("D5", detected_at=NOON - timedelta(days=9),
                    hearing_date="2026-10-20T00:00:00.000"),
               _dot("D6", detected_at=NOON - timedelta(days=9),
                    hearing_date="2026-09-01T00:00:00.000")]
        texts = [i["text"] for i in wa_brief.job_items([], NOON - timedelta(hours=20), NOON, dot)]
        self.assertEqual(texts, ["🟠 OATH hearing Oct 20 · ticket #D5 · DOT."])

    def test_inactive_dot_permit_not_in_brief(self):
        dot = [_dot("P9", kind="dot_permit", raw_id="dotpermit:P9", status="EXPIRED",
                    expiration_date=(TODAY + timedelta(days=4)).isoformat())]
        self.assertEqual(wa_brief.job_items([], NOON - timedelta(hours=20), NOON, dot), [])

    def test_old_dot_summons_is_not_new(self):
        dot = [_dot("D9", detected_at=NOON - timedelta(days=3))]
        self.assertEqual(wa_brief.job_items([], NOON - timedelta(hours=20), NOON, dot), [])


if __name__ == "__main__":
    unittest.main()
