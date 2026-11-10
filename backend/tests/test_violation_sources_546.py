"""546 Saratoga, 2026-11-10: violations and summonses, source by source.

Two failures, measured that day:

1. ONE DEAD DATASET CLOSED ALL VIOLATION MONITORING. The violations source is
   four Open Data datasets. 3usq-5cid (the COVID stop-work set, nothing after
   2020-05-28) answered HTTP 400 on every pass. A source counted as synced only
   when EVERY request for it answered, so `dob_violations` never first-synced
   for 546, and every violation, stop-work and order alert to the project's
   group waited forever. Fixed in lib/source_sync: per-dataset state, a source
   opens when ANY of its datasets answers, and a row is judged against the
   first sync of the dataset that produced it.

2. NO SAME-DAY SUMMONS SOURCE. The operator reported ten ECB/OATH summonses
   issued that afternoon:
       039561781P 039561782R 039561783Z 039561786Y 039561787X
       039561788H 039561789J 039561790R 039561791Z 039561792K
   At 21:55 UTC none was in BIS (by number or in either BIN's ECB list), Open
   Data 6bgk-3dad, OATH jz4z-kudi, or the BIS complaint pages, and DOB NOW was
   down. The BIS ECB list is what DOB updates as it enters a summons, so the
   watcher now reads it per BIN (lib/bis_violations).

The pages under tests/fixtures/bis_complaints/ are the real BIS pages fetched
2026-11-10. The end-to-end test for the ten summonses runs on the real page
BIS serves once it lists them (captured by the read-only tracker); until then
it SKIPS and says so.
"""

from __future__ import annotations

import asyncio
import copy
import glob
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib import bis_violations as bv  # noqa: E402
from lib import complaint_watch as cw  # noqa: E402
from lib import source_sync  # noqa: E402

FIX = _HERE / "fixtures" / "bis_complaints"
NOW = datetime(2026, 11, 10, 21, 55, tzinfo=timezone.utc)
TEN = ["039561781P", "039561782R", "039561783Z", "039561786Y", "039561787X",
       "039561788H", "039561789J", "039561790R", "039561791Z", "039561792K"]
BINS = {"3255205", "3423445"}


def page(name):
    return (FIX / name).read_text(encoding="latin-1")


class EcbListParsing(unittest.TestCase):
    def test_the_546_ecb_list_is_read_completely(self):
        e = bv.parse_ecb_list(page("ecb_3255205.html"))
        self.assertEqual((e["bin"], e["total_issued"], e["total_open"], len(e["rows"]), e["complete"]),
                         ("3255205", 19, 2, 19, True))
        self.assertEqual(sorted(r["ecb_number"] for r in e["rows"] if r["active"]), ["39556258Y", "39556260N"])
        top = e["rows"][0]
        self.assertEqual((top["ecb_number"], top["severity"], top["unit"], top["balance_due"], top["issue_date"]),
                         ("39556260N", "CLASS - 2", "CONSTRUCTION SAFETY COMPLIANCE", 1000.0, "2026-07-07"))

    def test_the_rear_bin_is_its_own_list(self):
        e = bv.parse_ecb_list(page("ecb_3423445.html"))
        self.assertEqual((e["bin"], [r["ecb_number"] for r in e["rows"]]), ("3423445", ["35716973H"]))

    def test_an_oath_ticket_and_its_ecb_number_are_one_summons(self):
        self.assertEqual([bv.normalize_violation_number(n) for n in TEN],
                         [n[1:] for n in TEN])
        self.assertEqual(bv.normalize_violation_number("39556258Y"), "39556258Y")


class TheTenWereNotPublishedAt2155(unittest.TestCase):
    """Evidence, not a guess: the real ECB list for both BINs at 21:4x UTC holds
    none of the ten. LeveLog could not have ingested what no source listed."""

    def test_none_of_the_ten_is_on_either_bins_ecb_list(self):
        listed = {r["ecb_number"] for f in ("ecb_3255205.html", "ecb_3423445.html")
                  for r in bv.parse_ecb_list(page(f))["rows"]}
        self.assertEqual(listed & {bv.normalize_violation_number(n) for n in TEN}, set())


class OneDeadDatasetNoLongerClosesTheSource(unittest.TestCase):
    PASS = {"violation": True, "swo": False,                 # 3usq-5cid 400'd
            "ds:855j-jady": True, "ds:3h2n-5cm9": True, "ds:6bgk-3dad": True, "ds:3usq-5cid": False,
            "complaint": True, "ds:eabe-havv": True}

    def test_the_old_all_or_nothing_rule_closed_violations(self):
        self.assertNotIn("dob_violations", source_sync.answered_sources(self.PASS))

    def test_any_answering_dataset_opens_its_source(self):
        self.assertIn("dob_violations", source_sync.answered_sources_by_dataset(self.PASS))
        self.assertEqual(source_sync.answered_datasets(self.PASS)["3usq-5cid"], False)

    def test_a_storage_failure_still_closes_the_source(self):
        self.assertNotIn("dob_violations", source_sync.answered_sources_by_dataset(self.PASS, {"violation"}))

    def test_a_real_pass_with_3usq_down_marks_violations_synced(self):
        import server
        from tests.test_dob_query_columns_all_datasets import _Ctx, _Resp, _SchemaClient

        class _Down(_SchemaClient):
            async def get(self, url, params=None, **kw):
                if "3usq-5cid" in url:
                    return _Resp(400, {"message": "query.soql.no-such-column"})
                return await super().get(url, params=params, **kw)

        client, answered = _Down(), {}
        with patch("server.ServerHttpClient", lambda *a, **k: _Ctx(client)):
            asyncio.run(server._query_dob_apis("3255205", "546 SARATOGA AVENUE, Brooklyn, NY", answered))
        synced = source_sync.answered_sources_by_dataset(answered) & set(source_sync.DOB_SOURCES)
        self.assertIn("dob_violations", synced)
        self.assertFalse(source_sync.answered_datasets(answered)["3usq-5cid"])
        self.assertTrue(source_sync.answered_datasets(answered)["6bgk-3dad"])


class DatasetGate(unittest.TestCase):
    FIRST = {"6bgk-3dad": NOW - timedelta(days=1)}

    def test_a_row_after_its_datasets_first_sync_posts(self):
        rec = {"dataset": "6bgk-3dad", "detected_at": NOW}
        self.assertEqual(source_sync.dataset_gate(rec, self.FIRST), "post")

    def test_a_row_from_its_datasets_first_sync_is_history(self):
        rec = {"dataset": "6bgk-3dad", "detected_at": NOW - timedelta(days=2)}
        self.assertEqual(source_sync.dataset_gate(rec, self.FIRST), "baseline")

    def test_a_row_from_a_failing_dataset_waits_alone(self):
        state = {"datasets": {"855j-jady": {"last_error_at": NOW}, "6bgk-3dad": {"first_synced_at": NOW - timedelta(days=1)}}}
        failing = source_sync.dataset_failing(state)
        self.assertEqual(failing, {"855j-jady"})
        self.assertEqual(source_sync.dataset_gate({"dataset": "855j-jady", "detected_at": NOW}, self.FIRST, failing), "wait")
        self.assertEqual(source_sync.dataset_gate({"dataset": "6bgk-3dad", "detected_at": NOW}, self.FIRST, failing), "post")

    def test_a_dataset_with_no_record_yet_defers_to_the_source_gate(self):
        self.assertEqual(source_sync.dataset_gate({"dataset": "855j-jady", "detected_at": NOW}, {}), "post")

    def test_complaints_and_permits_are_not_gated_here(self):
        self.assertEqual(source_sync.dataset_gate({"dataset": "eabe-havv", "detected_at": NOW}, {}), "post")


class SummonsDecision(unittest.TestCase):
    ROW = {"ecb_number": "39561781P", "active": True, "severity": "CLASS - 2",
           "unit": "CONSTRUCTION SAFETY COMPLIANCE", "issue_date": "2026-11-10", "hearing_status": "PENDING"}

    def test_a_new_class_2_summons_alerts_high(self):
        d = cw.summons_decision(self.ROW, bin_="3255205", project_bins=BINS, first_sync=False,
                                already_alerted=False, now=NOW)
        self.assertEqual((d["alert"], d["priority"], d["late"]), (True, "high", False))

    def test_class_1_is_critical(self):
        d = cw.summons_decision(dict(self.ROW, severity="CLASS - 1"), bin_="3255205", project_bins=BINS,
                                first_sync=False, already_alerted=False, now=NOW)
        self.assertEqual(d["priority"], "critical")

    def test_todays_summons_alerts_even_on_a_first_sync(self):
        d = cw.summons_decision(self.ROW, bin_="3255205", project_bins=BINS, first_sync=True,
                                already_alerted=False, now=NOW)
        self.assertTrue(d["alert"])

    def test_july_history_is_baseline_on_a_first_sync(self):
        row = bv.parse_ecb_list(page("ecb_3255205.html"))["rows"][0]
        d = cw.summons_decision(row, bin_="3255205", project_bins=BINS, first_sync=True,
                                already_alerted=False, now=NOW)
        self.assertFalse(d["alert"])
        self.assertTrue(d["reason"].startswith("baseline"))

    def test_wrong_property_and_duplicate(self):
        self.assertFalse(cw.summons_decision(self.ROW, bin_="3255362", project_bins=BINS, first_sync=False,
                                             already_alerted=False, now=NOW)["alert"])
        self.assertFalse(cw.summons_decision(self.ROW, bin_="3255205", project_bins=BINS, first_sync=False,
                                             already_alerted=True, now=NOW)["alert"])

    def test_the_message(self):
        d = cw.summons_decision(self.ROW, bin_="3255205", project_bins=BINS, first_sync=False,
                                already_alerted=False, now=NOW)
        en = cw.render_summons_alert(self.ROW, d, project_name="546 Saratoga Ave")
        es = cw.render_summons_alert(self.ROW, d, project_name="546 Saratoga Ave", lang="es")
        self.assertIn("39561781P", en)
        self.assertIn("ECBQueryByNumberServlet?ecbin=39561781P", en)
        self.assertIn("Certificado de Corrección", es)


def _captured_page_with_the_ten():
    """The real BIS ECB page for BIN 3255205 once it lists the ten (saved by
    the read-only tracker), copied into fixtures. None until DOB enters them."""
    hits = sorted(glob.glob(str(FIX / "ecb_3255205_with_10_*.html")))
    return hits[-1] if hits else None


@unittest.skipUnless(_captured_page_with_the_ten(),
                     "BIS had not listed the ten 546 summonses (checked 2026-11-10 21:55 UTC); "
                     "this runs on the real page once the tracker captures it")
class TheTenEndToEnd(unittest.TestCase):
    def test_each_of_the_ten_is_stored_once_shown_and_emailed_once(self):
        import server
        from tests.test_bis_complaint_watch_flow import _DB, PROJECT, _BIS, _seed
        real = Path(_captured_page_with_the_ten()).read_text(encoding="latin-1")

        class _WithTen(_BIS):
            async def get(self, url, **kw):
                if "ECBQueryByLocationServlet" in url and "allbin=3255205" in url:
                    self.urls.append(url)
                    from tests.test_bis_complaint_watch_flow import _Resp
                    return _Resp(200, real)
                return await super().get(url, **kw)

        db, emails = _seed(), []
        db.source_sync_state.docs[0].setdefault("watch", {})["bis_ecb"] = {"bins_first_synced": ["3255205"]}

        async def fake_send(project, doc, source="dob", *, event):
            emails.append((doc.get("raw_dob_id"), event))
            return True
        with patch.object(server, "db", db), patch.object(server, "_send_critical_dob_alert_throttled", fake_send):
            asyncio.run(server.run_bis_complaint_watch_for_project(copy.deepcopy(PROJECT), _WithTen(),
                                                                   mode="live", now=NOW))
        want = {bv.normalize_violation_number(n) for n in TEN}
        rows = [d for d in db.dob_logs.docs if d.get("raw_dob_id") in want]
        self.assertEqual(sorted(d["raw_dob_id"] for d in rows), sorted(want))
        self.assertTrue(all(d["record_type"] == "violation" and d["dataset"] == "bis-ecb" for d in rows))
        self.assertEqual(sorted(n for n, _ in emails if n in want), sorted(want))


if __name__ == "__main__":
    unittest.main()


class TheGroupAlertNoLongerWaitsOnADeadDataset(unittest.TestCase):
    """The GC tick end to end, 546's exact state: every violation dataset
    answers except 3usq-5cid, on every pass. A violation found by a later
    pass must post; the history from the first pass must not."""

    def test_a_new_ecb_violation_posts_while_3usq_keeps_failing(self):
        import server
        from tests import test_whatsapp_gc_alerts_dob_dot as h
        from unittest.mock import AsyncMock

        def raw_ecb(n, issued):
            return {"_id_field": "ecb_violation_number", "_record_type": "violation",
                    "_dataset": "6bgk-3dad", "ecb_violation_number": f"3955{n:04d}Y",
                    "issue_date": issued, "ecb_violation_status": "ACTIVE",
                    "violation_type": "Construction", "bin": "3012345"}

        def sync(records):
            async def query(nyc_bin, address="", answered=None):
                if answered is not None:
                    for k, ok in (("violation", True), ("swo", False), ("complaint", True), ("permit", True),
                                  ("ds:6bgk-3dad", True), ("ds:855j-jady", True), ("ds:3h2n-5cm9", True),
                                  ("ds:3usq-5cid", False), ("ds:eabe-havv", True), ("ds:rbx6-tga4", True)):
                        answered[k] = answered.get(k, True) and ok
                return [dict(r) for r in records]
            with patch.object(server, "_query_dob_apis", query), \
                    patch.object(server, "_send_critical_dob_alert_throttled", AsyncMock()):
                return h._run(server.run_dob_sync_for_project(dict(h.DobWaitsForTheFirstSync.PROJECT)))

        db = h._world(source_sync_state=[])
        history = [raw_ecb(i, "20260915") for i in range(5)]
        with h._Ctx(db=db) as c, h._no_ai():
            h._confirm()
            sync(history)
            h._run(server._gc_alerts_tick(h.NOON + timedelta(minutes=15)))
            h._run(server._gc_alerts_tick(h.NOON + timedelta(minutes=30)))
            self.assertEqual(h._group_sends(c), [], "history from the first pass must not post")
            sync(history + [raw_ecb(99, "20261007")])
            h._run(server._gc_alerts_tick(h.NOON + timedelta(minutes=45)))
        texts = [s["message"] for s in h._group_sends(c)]
        self.assertEqual(len(texts), 1, texts)
        self.assertIn("39550099Y", texts[0])
