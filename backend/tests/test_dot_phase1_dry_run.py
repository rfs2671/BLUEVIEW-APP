"""The DOT Phase 1 dry run end to end, over a SEEDED copy (no production).

backend/scripts/dot_phase1_dry_run.py is run exactly as the operator runs it,
except that its source database is an in-memory one seeded from the recorded
fixtures (tests/fixtures/dot_permits, tests/fixtures/dot_summonses) and its
NYC Open Data reads are answered from those fixtures. The guard is installed
for the run and removed after.

What the run must list, in the first 7 days from Mon 2026-10-26 09:00 New York:
the embargo email + group post (Nov 1), a permit expiry DIGEST (Tuesday 07:00:
two permits, 2 and 7 days left -- the true days), the 3-day reminder due Saturday
Oct 31 HELD over Shabbos and delivered that night, a hearing reminder (7-day),
the pending block-match email, a default email, and -- only with dot_phase1 on
-- the new-summons email. Production's 07:00 run has already gone on Monday
(its system_config markers are in the copy), so the first sync's LATE check
emails at once a permit and a hearing 1 day away (SYNTHETIC), each listed as
"late item (<=1 day), sent at once", and neither is in Tuesday's digest. A test company's project gets
nothing and is listed apart. SYNTHETIC dates are recorded records with their
dates moved into the window.
"""

from __future__ import annotations

import asyncio
import copy
import csv
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402
from lib import dot_sync  # noqa: E402
from scripts import dot_phase1_dry_run as D  # noqa: E402
from tests.async_fake_mongo import AsyncFakeDB  # noqa: E402

HERE = Path(__file__).resolve().parent
A = json.loads((HERE / "fixtures" / "dot_summonses" / "oath_and_nov_links.json").read_text(encoding="utf-8"))
B = json.loads((HERE / "fixtures" / "dot_permits" / "hopkinson_blake_sutter.json").read_text(encoding="utf-8"))
OATH = {r["ticket_number"]: r for r in A["oath"]}
PERMITS = {r["permitnumber"]: r for r in B["segment"]}

UTC = timezone.utc
START = datetime(2026, 10, 26, 13, 0, tzinfo=UTC)          # Mon 09:00 New York
G = "120363000000000999@g.us"


def _iso(d: date) -> str:
    return f"{d.isoformat()}T00:00:00.000"


def summons(t, **kw):
    r = copy.deepcopy(OATH[t])
    r.update(kw)
    return r


def seeded_source():
    """What production might hold: one real company with a confirmed DOT
    setup and a bound GC group, and one test company."""
    db = AsyncFakeDB()
    db.companies.docs += [{"_id": "c1", "name": "Blue Elm Inc"},
                          {"_id": "ct", "name": "test", "is_test": True}]
    setup = {"status": "confirmed", "permittees": [{"name": "BLUE ELM INC.", "norm": "BLUE ELM"}],
             "frontages": [{"boro": "3", "on": "THOMAS S BOYLAND ST", "from": "BLAKE AVE",
                            "to": "SUTTER AVE", "source": "admin", "confirmed": True}]}
    db.projects.docs += [{"_id": "p1", "company_id": "c1", "name": "588 Thomas S Boyland",
                          "address": "588 Thomas S Boyland St, Brooklyn, NY", "dot_setup": setup},
                         {"_id": "pt", "company_id": "ct", "name": "Test job",
                          "address": "588 Thomas S Boyland St, Brooklyn, NY"}]
    db.users.docs += [{"_id": "u1", "company_id": "c1", "role": "admin", "email": "a1@blueelm.test"},
                      {"_id": "u2", "company_id": "c1", "role": "admin", "email": "a2@blueelm.test"},
                      {"_id": "u3", "company_id": "c1", "role": "cp", "email": "cp@blueelm.test"},
                      {"_id": "ut", "company_id": "ct", "role": "admin", "email": "t@test.test"}]
    long_ago = datetime(2026, 9, 1)
    db.source_sync_state.docs += [{"_id": pid, "company_id": c, "sources": {
        s: {"first_synced_at": long_ago, "synced_at": long_ago}
        for s in ("dot_oath", "dot_permits", "dob_violations", "dob_complaints", "dob_permits")}}
        for pid, c in (("p1", "c1"), ("pt", "ct"))]
    # SYNTHETIC: recorded permits with dates moved into the window.
    embargo = {**dot_sync.to_log("dot_permit", PERMITS["B022026215B30"]), "_id": "d1", "project_id": "p1",
               "company_id": "c1", "work_start": "2026-10-20T00:00:00.000",
               "expiration_date": "2026-11-30T23:59:59.000", "work_end": "2026-11-30T23:59:59.000",
               "holiday_waiver": False, "match": {"how": "address", "state": "confirmed"},
               "detected_at": long_ago, "renewed_by": None}
    expiring = {**dot_sync.to_log("dot_permit", PERMITS["B022026215B31"]), "_id": "d2", "project_id": "p1",
                "company_id": "c1", "work_start": "2026-10-01T00:00:00.000",
                "expiration_date": "2026-10-29T23:59:59.000", "work_end": "2026-10-29T23:59:59.000",
                "holiday_waiver": True, "match": {"how": "address", "state": "confirmed"},
                "detected_at": long_ago, "renewed_by": None}
    hearing = {**dot_sync.to_log("dot_violation", summons("0704345548", hearing_date=_iso(date(2026, 11, 2)))),
               "_id": "d3", "project_id": "p1", "company_id": "c1",
               "match": {"how": "address", "state": "confirmed"}, "detected_at": long_ago}
    to_default = {**dot_sync.to_log("dot_violation", summons("0704345557")), "_id": "d4", "project_id": "p1",
                  "company_id": "c1", "match": {"how": "address", "state": "confirmed"}, "detected_at": long_ago}
    # SYNTHETIC: a second expiring permit, 7 days out at the first 07:00 run
    # (Tue; the 14-day window: a catch-up, labelled 7) and 3 days out on
    # Saturday Oct 31 (held over Shabbos).
    saturday = {**expiring, "_id": "d5", "number": "B022026215B32", "raw_id": "dotpermit:B022026215B32",
                "expiration_date": "2026-11-03T23:59:59.000", "work_end": "2026-11-03T23:59:59.000"}
    # SYNTHETIC: a permit ending tomorrow and a hearing tomorrow, after today's
    # 07:00 digest run went in production (its markers, read with the copy).
    late_permit = {**expiring, "_id": "d6", "number": "B022026215B33", "raw_id": "dotpermit:B022026215B33",
                   "expiration_date": "2026-10-27T23:59:59.000", "work_end": "2026-10-27T23:59:59.000"}
    late_hearing = {**dot_sync.to_log("dot_violation", summons("0704345548", ticket_number="0704399003",
                                                               hearing_date=_iso(date(2026, 10, 27)))),
                    "_id": "d7", "project_id": "p1", "company_id": "c1",
                    "match": {"how": "address", "state": "confirmed"}, "detected_at": long_ago}
    db.system_config.docs += [{"_id": f"m_{k}", "key": f"dot:-:{k}_run:-:-:2026-10-26", "value": True}
                              for k in ("expiry", "hearing")]
    db.dot_logs.docs += [embargo, expiring, saturday, late_permit, hearing, late_hearing, to_default,
                         {**embargo, "_id": "dt", "project_id": "pt", "company_id": "ct"}]
    db.notification_preferences.docs.append(
        {"_id": "np1", "user_id": None, "scope": "project", "project_id": "p1", "company_id": "c1",
         "whatsapp_project": {"gc_group_id": G, "gc_group_confirmed": True}})
    db.whatsapp_groups.docs.append({"_id": "g1", "wa_group_id": G, "project_id": "p1", "company_id": "c1",
                                    "group_name": "588 Boyland", "active": True})
    return db


def fixture_fetch():
    """NYC Open Data, answered from the recorded fixtures."""
    async def fetch(dataset, params):
        where = params.get("$where", "")
        if dataset == dot_sync.OATH_DATASET:
            if "violation_location_house" in where:
                return [summons("0704345557", violation_date=_iso(date(2026, 10, 26)),     # SYNTHETIC: new today
                                ticket_number="0704399001"),
                        summons("0704345548", hearing_date=_iso(date(2026, 11, 2))),
                        summons("0704345557", hearing_status="DEFAULTED", hearing_result="DEFAULTED")]
            if "violation_date >=" in where:
                return [summons("0704197771", violation_date=_iso(date(2026, 10, 20)),        # SYNTHETIC
                                hearing_date=_iso(date(2026, 11, 5)), hearing_status="NEW ISSUANCE",
                                balance_due="750", paid_amount="0", compliance_status="Penalty Due")]
            return []
        if dataset == "gsgx-6efw":
            m = re.search(r"permitnumber = '([^']+)'", where)
            num = m.group(1) if m else ""
            sid = "410" if num == "B022026215B31" else "012"
            return [{"permitnumber": num, "stipulationid": sid, "stipulationfulltext": "x"}]
        return []
    return fetch


def run_seeded(out_dir):
    guard = D.Guard()
    guard.install()
    guard.install_app(server)
    try:
        return asyncio.run(D.run_all(server, seeded_source(), out_dir, fetch=fixture_fetch(),
                                     start=START, days=7, env_notes=["(seeded fake; not production)"],
                                     guard=guard)), guard
    finally:
        guard.uninstall()


class TheSeededDryRun(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="dot_dry_run_")
        cls.got, cls.guard = run_seeded(cls.dir)
        cls.rows = list(csv.DictReader(open(os.path.join(cls.dir, "dry_run_rows.csv"), encoding="utf-8")))

    def _kinds(self, run, channel):
        return sorted((r["kind"], r["record"], r["day"]) for r in self.rows
                      if r["run"].startswith(run) and r["channel"] == channel)

    def test_every_kind_the_operator_asked_for(self):
        emails = self._kinds("flags", "email")
        kinds = {k for k, _r, _d in emails}
        for k in ("embargo (no waiver)", "permit expiry", "hearing reminder",
                  "block match: confirm (hearing near)", "summons default/docketed"):
            self.assertIn(k, kinds, emails)
        self.assertNotIn("new summons", kinds)                          # flag off in "production"
        on = {k for k, _r, _d in self._kinds("dot_phase1", "email")}
        self.assertIn("new summons", on)
        emb = [r for r in self.rows if r["kind"] == "embargo (no waiver)" and r["run"].startswith("flags")]
        self.assertEqual({(r["day"], r["recipients"], r["tier"]) for r in emb}, {("2026-11-01", "2", "address")})
        posts = {k for k, _r, _d in self._kinds("flags", "whatsapp")}
        self.assertIn("dot_embargo", posts)

    def test_the_test_company_gets_nothing_and_is_listed_apart(self):
        self.assertFalse(any(r["project_id"] == "pt" for r in self.rows))
        facts = list(csv.DictReader(open(os.path.join(self.dir, "dry_run_projects.csv"), encoding="utf-8")))
        t = [f for f in facts if f["project_id"] == "pt"]
        self.assertEqual({f["test_company"] for f in t}, {"True"})
        self.assertIn("TEST COMPANIES", self.got["text"])

    def test_every_email_and_post_came_from_the_guards_record(self):
        sends = [e for e in self.guard.blocked if e["method"] in ("send_notification", "send_whatsapp_message")]
        n_email = sum(int(r["recipients"]) for r in self.rows if r["channel"] == "email")
        self.assertEqual(n_email, sum(1 for e in sends if e["method"] == "send_notification"))
        self.assertIn("BLOCKED CALLS", self.got["text"])
        self.assertTrue(os.path.exists(os.path.join(self.dir, "dry_run_blocked_calls.csv")))

    def test_permit_expiry_is_one_digest_with_the_true_days(self):
        exp = [r for r in self.rows if r["kind"] == "permit expiry" and r["run"].startswith("flags")]
        tuesday = [r for r in exp if r["day"] == "2026-10-27"]   # the first 07:00 run
        self.assertEqual(len(tuesday), 1, exp)
        self.assertEqual((tuesday[0]["items"], tuesday[0]["record"]), ("2", "B022026215B31 B022026215B32"))
        self.assertIn("B022026215B31 2 day(s) to work end 2026-10-29", tuesday[0]["why"])
        self.assertIn("B022026215B32 7 day(s) to work end 2026-11-03", tuesday[0]["why"])
        self.assertEqual(tuesday[0]["ledger_id"], "dot:p1:expiry_digest:-:-:2026-10-27")

    def test_the_saturday_reminder_is_held_and_listed_when_it_goes(self):
        exp = [r for r in self.rows if r["kind"] == "permit expiry" and r["run"].startswith("flags")]
        sat = [r for r in exp if r["day"] == "2026-10-31"]
        self.assertEqual(len(sat), 1, exp)
        self.assertIn("B022026215B32 3 day(s) to work end 2026-11-03", sat[0]["why"])
        self.assertIn("held for Shabbos/Yom Tov (expiry)", sat[0]["why"])
        at = [e["at"] for e in self.guard.blocked if e["method"] == "send_notification"
              and (e.get("kwargs") or {}).get("permit_renewal_id") == sat[0]["ledger_id"]]
        self.assertTrue(at and all(a.astimezone(D.ny_tz()).hour >= 18 for a in at), at)   # after havdalah

    def test_a_late_item_is_a_row_sent_at_once(self):
        late = sorted((r["kind"], r["record"], r["day"]) for r in self.rows
                      if r["run"].startswith("flags") and r["why"].startswith(D.LATE_REASON))
        self.assertEqual(late, [("hearing reminder", "0704399003", "2026-10-26"),
                                ("permit expiry", "B022026215B33", "2026-10-26")], late)
        r = next(r for r in self.rows if r["record"] == "B022026215B33" and r["run"].startswith("flags"))
        self.assertEqual(r["why"], "late item (<=1 day), sent at once: B022026215B33 1 day(s) to work end 2026-10-27")
        self.assertEqual(r["ledger_id"], "dot:p1:expiry_late:B022026215B33:-:2026-10-26")
        again = [x for x in self.rows if "B022026215B33" in x["record"] and x["run"].startswith("flags")
                 and x["channel"] == "email"]
        self.assertEqual(len(again), 1, again)          # not in a later sync, not in Tuesday's digest

    def test_the_sync_runs_every_two_hours(self):
        at = [a for a, jobs in D.slots(START, 1, 2) if "sync" in jobs]
        self.assertEqual(len(at), 12)
        self.assertEqual(at[0], START + timedelta(hours=2))
        self.assertTrue(any(n == "expiry_late" for n, _r in self.got["runs"][0]["reports"]))

    def test_the_window_is_printed(self):
        self.assertIn("window: Mon 2026-10-26 09:00 -> Mon 2026-11-02 08:00 New York (7 days)", self.got["text"])

    def test_no_confirmed_setup_is_said(self):
        self.assertIn("none confirmed", self.got["text"])           # the test company's job
        self.assertIn("confirmed, 1 frontage(s)", self.got["text"])


class TheStartArgument(unittest.TestCase):

    def test_no_offset_is_new_york(self):
        a = D.parse_args(["out", "--days", "21", "--start", "2026-10-28T06:00"])
        self.assertEqual((a.start, a.days), (datetime(2026, 10, 28, 10, 0, tzinfo=UTC), 21))
        self.assertEqual(D.parse_start("2026-11-07T06:00"), datetime(2026, 11, 7, 11, 0, tzinfo=UTC))  # EST

    def test_an_offset_is_kept(self):
        self.assertEqual(D.parse_start("2026-10-28T06:00Z"), datetime(2026, 10, 28, 6, 0, tzinfo=UTC))
        self.assertEqual(D.parse_start("2026-10-28T06:00-04:00"), datetime(2026, 10, 28, 10, 0, tzinfo=UTC))

    def test_default_is_now(self):
        a = D.parse_args(["out"])
        self.assertLess(abs((a.start - datetime.now(UTC)).total_seconds()), 60)
        self.assertEqual(a.days, 7)

    def test_garbage_is_refused(self):
        import contextlib
        import io
        err = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(err):
            D.parse_args(["out", "--start", "next tuesday"])
        self.assertIn("not an ISO date-time", err.getvalue())


if __name__ == "__main__":
    unittest.main()
