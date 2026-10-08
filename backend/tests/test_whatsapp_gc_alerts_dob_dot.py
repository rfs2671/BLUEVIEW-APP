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
    _permit, _violation, _world,
)

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
           "issue_date": "2026-10-06", "status": "DEFAULT",
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

    P = {"address": "588 Thomas S Boyland St, Brooklyn, NY 11212",
         "nyc_bin": "3082345", "bbl": "3015230001"}

    def _m(self, rec, project=None):
        return dot_sync.match(dot_sync.project_keys(project or self.P),
                              dot_sync.record_keys(rec))

    def test_bin_first(self):
        self.assertEqual(self._m({"bin": "3082345"}), "bin")
        self.assertIsNone(self._m({"bin": "3082346", "bbl": "3015230001"}),
                          "a different BIN is not this building, whatever else matches")

    def test_bbl_from_boro_block_lot(self):
        rec = {"violation_location_borough": "BROOKLYN",
               "violation_location_block_no": "01523", "violation_location_lot_no": "0001"}
        self.assertEqual(self._m(rec), "bbl")
        self.assertIsNone(self._m({**rec, "violation_location_lot_no": "2"}))

    def test_exact_address_only(self):
        p = {"address": "588 Thomas S Boyland St, Brooklyn, NY"}
        ok = {"violation_location_house": "588",
              "violation_location_street_name": "THOMAS S BOYLAND STREET",
              "violation_location_borough": "BROOKLYN"}
        self.assertEqual(self._m(ok, p), "address")
        for bad in ({**ok, "violation_location_house": "586"},
                    {**ok, "violation_location_street_name": "THOMAS BOYLAND ST"},
                    {**ok, "violation_location_borough": "QUEENS"},
                    {"violation_location_street_name": "THOMAS S BOYLAND ST"}):
            with self.subTest(bad):
                self.assertIsNone(self._m(bad, p))

    def test_dot_permit_house_number_field(self):
        p = {"address": "588 Thomas S Boyland St, Brooklyn, NY"}
        rec = {"permithousenumber": "588", "onstreetname": "THOMAS S BOYLAND STREET",
               "boroughname": "BROOKLYN"}
        self.assertEqual(self._m(rec, p), "address")

    def test_staten_island_as_oath_writes_it(self):
        rec = {"violation_location_borough": "STATEN IS",
               "violation_location_block_no": "100", "violation_location_lot_no": "5"}
        self.assertEqual(dot_sync.record_keys(rec)["bbl"], "5001000005")
        self.assertEqual(dot_sync.record_keys(rec)["boro"], "5")

    def test_permit_query_is_narrowed_to_the_address(self):
        pk = dot_sync.project_keys({"address": "10 West 30 Street, Manhattan, NY"})
        q = [x for x in dot_sync.queries(pk) if x["dataset"] == dot_sync.PERMIT_DATASET][0]
        self.assertIn("permithousenumber = '10'", q["params"]["$where"])
        self.assertNotIn("like '%W%'", q["params"]["$where"])

    def test_placeholder_bin_is_no_bin(self):
        self.assertEqual(dot_sync.norm_bin("3000000"), "")

    def test_only_dot_summonses_are_kept(self):
        rec = {"ticket_number": "T1", "issuing_agency": "DEPT OF SANITATION"}
        self.assertIsNone(dot_sync.to_log("dot_violation", rec))
        log = dot_sync.to_log("dot_violation", {**rec, "issuing_agency":
                                                "DEPARTMENT OF TRANSPORTATION"})
        self.assertEqual((log["raw_id"], log["number"]), ("oath:T1", "T1"))


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
        mine = {"ticket_number": "T1", "issuing_agency": "DEPARTMENT OF TRANSPORTATION",
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
        rec = {"ticket_number": "T1", "issuing_agency": "DEPARTMENT OF TRANSPORTATION",
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

    def test_old_dot_summons_is_not_new(self):
        dot = [_dot("D9", detected_at=NOON - timedelta(days=3))]
        self.assertEqual(wa_brief.job_items([], NOON - timedelta(hours=20), NOON, dot), [])


if __name__ == "__main__":
    unittest.main()
