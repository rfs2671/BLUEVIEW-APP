"""WHATSAPP GROUP ALERTS FOLLOW THE EMAIL'S RULES (operator ruling 2026-10-22).

The GC group alerts post once ever per item from a ledger. They now follow
lib/dob_alert_gate, like the DOB alert email:

  * a record NEW to Levelog posts only if DOB dated it within 2 days;
  * an update never posts -- except one that issued a Stop Work Order or a
    vacate order (kind "order");
  * the first sync of a newly added BIN is silent -- except ONE summary per
    project per new BIN listing only its open records, with their DOB dates,
    in English and Spanish (kind "bin_added").

Driven through the real _gc_alerts_tick (send window, bot switch, ledger,
baseline per kind) with the group harness of test_whatsapp_gc_alerts; only the
WhatsApp transport and the AI wording are faked. Today is 2026-10-07 (NOON).
"""

from __future__ import annotations

import unittest
from datetime import timedelta

import server  # noqa: F401  (imported by the harness too)
from tests.test_whatsapp_gc_alerts import (  # noqa: E402
    NOON, _Ctx, _group_sends, _no_ai, _violation, _world,
)
from tests.test_whatsapp_gc_alerts_dob_dot import _complaint, _first_run, _run  # noqa: E402

SECOND = "3430621"


def _new_bin_rows():
    """What #829's first fetch of BIN 3430621 stored for 588 Thomas S
    Boyland, as the sync now flags it: from that BIN, on its first pass."""
    first = {"site_bin": SECOND, "bin_first_pass": True}
    return [
        _complaint("3A78809", complaint_number="3A78809", complaint_date="2026-09-02",
                   complaint_status="CLOSED", current_status="CLOSED",
                   closed_date="2026-09-02", **first),
        _violation("39558662P", violation_number="39558662P", violation_date="20260902",
                   status="ACTIVE", current_status="ACTIVE", resolution_state="open", **first),
        _violation("39558663R", violation_number="39558663R", violation_date="20260902",
                   status="RESOLVE", current_status="RESOLVE", resolution_state="resolved",
                   **first),
    ]


class _Base(unittest.TestCase):

    def _ticks(self, rows, *, extra=None, ticks=2, seed=()):
        db = _world(dob_logs=list(seed))
        with _Ctx(db=db) as c, _no_ai():
            _first_run(db)
            self.assertEqual(_group_sends(c), [], "precondition: the baseline posts nothing")
            db.dob_logs.rows.extend(rows)
            if extra:
                extra(db)
            for i in range(ticks):
                _run(server._gc_alerts_tick(NOON + timedelta(minutes=10 * (i + 1))))
            return [s["message"] for s in _group_sends(c)]


class ANewlyAddedBin(_Base):

    def test_one_summary_and_nothing_else(self):
        msgs = self._ticks(_new_bin_rows())
        self.assertEqual(len(msgs), 1, msgs)
        m = msgs[0]
        self.assertIn(f"Now also tracking BIN {SECOND} for this job.", m)
        self.assertIn("Open items found: 1", m)
        self.assertIn("• Violation 39558662P · Received by DOB: Sep 2, 2026 · Status: ACTIVE", m)
        self.assertIn(f"Ahora también seguimos el BIN {SECOND} de esta obra.", m)
        self.assertIn("Pendientes abiertos: 1", m)
        self.assertIn("• Infracción 39558662P · Recibido por el DOB: 2 sep 2026 · Estado: ACTIVE", m)
        self.assertNotIn("3A78809", m, "closed: not listed")
        self.assertNotIn("39558663R", m, "resolved: not listed")
        self.assertNotIn("New DOB", m)

    def test_the_summary_posts_once(self):
        msgs = self._ticks(_new_bin_rows(), ticks=4)
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn(f"Now also tracking BIN {SECOND}", msgs[0])

    def test_a_bin_with_nothing_open_still_gets_its_one_line(self):
        rows = [r for r in _new_bin_rows() if r["raw_dob_id"] != "39558662P"]
        msgs = self._ticks(rows)
        self.assertEqual(len(msgs), 1)
        self.assertIn("No open items found.", msgs[0])
        self.assertIn("No hay pendientes abiertos.", msgs[0])


class NewRecordsOnAnExistingBin(_Base):

    def test_entered_today_posts_once(self):
        msgs = self._ticks([_violation("T1", violation_date="2026-10-07")])
        self.assertEqual(len(msgs), 1)
        self.assertIn("New DOB violation", msgs[0])

    def test_entered_five_days_ago_and_first_seen_today_posts_nothing(self):
        self.assertEqual(self._ticks([_violation("T2", violation_date="2026-10-02")]), [])

    def test_undated_posts_nothing(self):
        self.assertEqual(self._ticks([_violation("T3", violation_date=None)]), [])


class Updates(_Base):

    def test_a_status_update_posts_nothing(self):
        # The record is known (stored before the baseline); only its change
        # is new -- ACTIVE -> HEARING, still 'Action', which used to post.
        msgs = self._ticks([_violation(
            "U1", _id="v_U1b", violation_date="2026-10-07", status="HEARING",
            current_status="HEARING", previous_status="ACTIVE", severity="Action",
            status_changed_at=NOON + timedelta(minutes=1))],
            seed=[_violation("U1", violation_date="2026-10-07")])
        self.assertEqual(msgs, [])

    def test_an_update_that_issues_a_stop_work_order_posts_once(self):
        db_rows = [_complaint("O1", complaint_date="2026-09-20",
                              order_issued={"kind": "swo", "at": NOON})]
        msgs = self._ticks(db_rows, ticks=3)
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("🔴 Main St", msgs[0])
        self.assertIn("DOB issued a stop-work order.", msgs[0])
        self.assertIn("Complaint #CO1", msgs[0])

    def test_an_update_that_issues_a_vacate_order_posts_once(self):
        msgs = self._ticks([_complaint("O2", complaint_date="2026-09-20",
                                       order_issued={"kind": "vacate", "at": NOON})])
        self.assertEqual(len(msgs), 1)
        self.assertIn("DOB issued a vacate order.", msgs[0])

    def test_an_order_stamped_a_week_ago_posts_nothing(self):
        self.assertEqual(self._ticks([_complaint(
            "O3", complaint_date="2026-09-20",
            order_issued={"kind": "swo", "at": NOON - timedelta(days=7)})]), [])


if __name__ == "__main__":
    unittest.main()
