"""The DOT Phase 1 dry run end to end, over a SEEDED copy (no production).

backend/scripts/dot_phase1_dry_run.py is run exactly as the operator runs it,
except that its source database is an in-memory one seeded from the recorded
fixtures (tests/fixtures/dot_permits, tests/fixtures/dot_summonses) and its
NYC Open Data reads are answered from those fixtures. The guard is installed
for the run and removed after.

What the run must list, in the first 7 days from Mon 2026-10-26 09:00 New York:
the embargo email + group post (Nov 1), a permit expiry email (3-day), a hearing
reminder (7-day), the pending block-match email, a default email, and -- only
with dot_phase1 on -- the new-summons email. A test company's project gets
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
    db.dot_logs.docs += [embargo, expiring, hearing, to_default,
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

    def test_no_confirmed_setup_is_said(self):
        self.assertIn("none confirmed", self.got["text"])           # the test company's job
        self.assertIn("confirmed, 1 frontage(s)", self.got["text"])


if __name__ == "__main__":
    unittest.main()
