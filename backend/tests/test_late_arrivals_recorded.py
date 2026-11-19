"""A worker whose crew is already on the signed Daily Jobsite Log is RECORDED on
it; the CP signs nothing. A crew the log has no card for still opens a correction.

OPERATOR RULING 2026-11-18. #1049 opened a full correction -- cleared signature,
whole log re-signed -- for EVERY worker who checked in after the log was signed.
For a man whose sub and trade are already on the log that is a signature spent
on a headcount: the work the CP described is the sub's work whoever is on it.

THE QUESTION THAT SEPARATES THE TWO CASES is about the signed document: does it
already have a crew card this man belongs on? (lib/late_arrivals.py)

    yes -> `late_arrivals` on the signed log, outside `data`, printed as
           "Arrived after signing". No new document, no signature.
    no  -> the correction #1049 opens, because that crew's WORK has to be
           written and signed by a person.

THESE ARE REQUESTS, NOT UNIT CALLS, for everything that touches the database:
each goes through server.app over ASGI with the real middleware, dependencies and
JWT; only the database is replaced (tests/async_fake_mongo.py). The rule itself
is a pure function and is tested as one.

CONTROL RUN. On #1049's route (every late man opens a correction) the same-sub
scenarios below fail: a second document appears and nothing is recorded.
"""

import asyncio
import copy
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import httpx  # noqa: E402
from bson import ObjectId  # noqa: E402

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402
from lib import late_arrivals as LA  # noqa: E402
from lib.legal_render.primitives import arrived_after_signing  # noqa: E402

CO_A = ObjectId()
CO_B = ObjectId()
PROJ_A = ObjectId()
SIGNED_LOG = ObjectId()
PW = "pw-late-recorded-1"

USERS = {
    "cp_a": {"role": "cp", "company_id": str(CO_A), "assigned_projects": [str(PROJ_A)]},
    "cp_b": {"role": "cp", "company_id": str(CO_B)},
    "owner_none": {"role": "owner", "company_id": None},
}


def _card(company, trade="", ids=("on-the-log",)):
    return {"company": company, "trade": trade, "worker_ids": list(ids),
            "work_description": f"{company} work the CP wrote"}


def _seed(cards, workers):
    db = AsyncFakeDB()
    now = datetime.now(timezone.utc)
    today = server.eastern_today()
    db.companies.docs.append({"_id": CO_A, "name": "Acme GC", "is_deleted": False})
    db.companies.docs.append({"_id": CO_B, "name": "Other GC", "is_deleted": False})
    db.projects.docs.append({"_id": PROJ_A, "company_id": str(CO_A), "name": "Tower",
                             "status": "active", "is_deleted": False})
    db.logbooks.docs.append({
        "_id": SIGNED_LOG, "project_id": str(PROJ_A), "company_id": str(CO_A),
        "project_name": "Tower", "log_type": "daily_jobsite", "date": today,
        "status": "submitted", "is_locked": True,
        "cp_signature": "data:image/png;base64,AAAA", "cp_name": "A Cp",
        "data": {"activities": [dict(c) for c in cards]},
        "created_at": now, "updated_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
        "is_deleted": False,
    })
    for i, (name, company, trade) in enumerate(workers):
        db.checkins.docs.append({
            "_id": ObjectId(), "project_id": str(PROJ_A), "worker_id": f"late-{i}",
            "worker_name": name, "worker_company": company, "worker_trade": trade,
            "status": "checked_in", "check_in_time": now, "is_deleted": False,
        })
    for key, extra in USERS.items():
        db.users.docs.append({
            "_id": ObjectId(), "email": f"{key}@late.test", "name": key,
            "password": server.hash_password(PW), "account_status": "approved",
            "is_deleted": False, **extra,
        })
    return db


async def _run(cards, workers, caller="cp_a", calls=1):
    db = _seed(cards, workers)
    before = copy.deepcopy(db.logbooks.docs[0])
    replies = []
    with patch.object(server, "db", db):
        if hasattr(server.auth_rate_limiter, "requests"):
            server.auth_rate_limiter.requests.clear()
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/api/auth/login",
                             json={"email": f"{caller}@late.test", "password": PW})
            assert r.status_code == 200, (caller, r.status_code, r.text)
            tok = r.json()["token"]
            url = f"/api/logbooks/project/{PROJ_A}/daily-jobsite/late-arrivals"
            for _ in range(calls):
                r = await c.post(url, headers={"Authorization": f"Bearer {tok}"})
                replies.append(r)
    signed = next(d for d in db.logbooks.docs if d["_id"] == SIGNED_LOG)
    amendments = [d for d in db.logbooks.docs if d.get("is_amendment")]
    return {"db": db, "before": before, "signed": signed,
            "amendments": amendments, "replies": replies}


def run(*a, **k):
    return asyncio.run(_run(*a, **k))


class ASameSubWorkerIsRecordedAndNothingIsSigned(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # J&P Plumbing is on the log; a second J&P Plumbing man badges in late.
        cls.out = run([_card("J&P", "Plumbing")],
                      [("Larry Late", "J&P", "Plumbing")], calls=2)

    def test_no_correction_is_opened(self):
        self.assertEqual(self.out["amendments"], [],
                         "a same-sub arrival opened a full correction")
        self.assertEqual(len(self.out["db"].logbooks.docs), 1)

    def test_the_man_is_recorded_on_the_signed_log(self):
        rows = self.out["signed"].get("late_arrivals") or []
        self.assertEqual([r["worker_name"] for r in rows], ["Larry Late"])
        self.assertEqual(rows[0]["company"], "J&P")
        self.assertEqual(rows[0]["trade"], "Plumbing")
        self.assertTrue(rows[0]["checked_in_at"], "the gate time was not kept")

    def test_what_the_cp_signed_is_untouched(self):
        """THE POINT. The signature covers `data` and the status; recording a
        late man moves neither."""
        before, after = self.out["before"], self.out["signed"]
        for field in ("data", "cp_signature", "cp_name", "status", "is_locked",
                      "date", "log_type"):
            with self.subTest(field=field):
                self.assertEqual(after.get(field), before.get(field))

    def test_the_record_says_it_moved(self):
        """`updated_at` is what the tablet's offline copy and the thumbnail are
        keyed on; the sheet now prints something it did not."""
        self.assertGreater(self.out["signed"]["updated_at"], self.out["before"]["updated_at"])

    def test_the_answer_says_nobody_has_to_sign(self):
        for r in self.out["replies"]:
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["late_workers"], [])
            self.assertIsNone(body["amendment_id"])
            self.assertFalse(body["created"])
            self.assertEqual([w["worker_name"] for w in body["recorded_workers"]],
                             ["Larry Late"])

    def test_asking_again_does_not_list_him_twice(self):
        """Two calls were made. A signed record must not carry the same man twice."""
        self.assertEqual(len(self.out["signed"]["late_arrivals"]), 1)

    def test_the_recording_is_audited(self):
        docs = self.out["db"].audit_logs.docs
        self.assertTrue(
            any(d.get("action") == "logbook_late_arrivals_recorded" for d in docs),
            f"no audit row for recording a late arrival; had {[d.get('action') for d in docs]}")


class ACrewTheLogHasNoCardForStillOpensTheCorrection(unittest.TestCase):

    def _assert_correction(self, out, *names):
        self.assertEqual(len(out["amendments"]), 1, "no correction was opened")
        child = out["amendments"][0]
        self.assertTrue(child["amendment_reason"].startswith("Added automatically"))
        for n in names:
            self.assertIn(n, child["amendment_reason"])
        self.assertIsNone(child["cp_signature"], "the correction must be re-signed")
        # And the signed log was not decorated: the correction takes everyone.
        self.assertFalse(out["signed"].get("late_arrivals"))

    def test_a_sub_that_is_not_on_the_log(self):
        out = run([_card("J&P", "Plumbing")], [("Nora New", "Larkin Electric", "Electrical")])
        self._assert_correction(out, "Nora New")
        body = out["replies"][0].json()
        self.assertTrue(body["created"])
        self.assertEqual([w["worker_name"] for w in body["late_workers"]], ["Nora New"])

    def test_a_second_trade_of_a_sub_that_is_on_the_log(self):
        """J&P's plumbers are described. An electrician from J&P is a crew whose
        work nobody wrote."""
        out = run([_card("J&P", "Plumbing")], [("Eli Electric", "J&P", "Electrical")])
        self._assert_correction(out, "Eli Electric")

    def test_two_crews_for_the_sub_and_a_man_with_no_trade(self):
        """Cannot tell which crew he is on, so the CP is asked, not guessed for."""
        out = run([_card("J&P", "Plumbing"), _card("J&P", "Electrical", ids=("x",))],
                  [("Una Unsaid", "J&P", "")])
        self._assert_correction(out, "Una Unsaid")

    def test_a_man_the_gate_could_not_place_under_a_sub(self):
        out = run([_card("J&P", "Plumbing")], [("Wes Whose", "UNASSIGNED", "Plumbing")])
        self._assert_correction(out, "Wes Whose")

    def test_one_new_crew_takes_the_same_sub_men_in_with_it(self):
        """MIXED. The correction reconciles with the gate, so it carries
        everyone; recording one man on the parent as well would list him on two
        documents."""
        out = run([_card("J&P", "Plumbing")],
                  [("Larry Late", "J&P", "Plumbing"), ("Nora New", "Larkin Electric", "Electrical")])
        self._assert_correction(out, "Larry Late", "Nora New")
        self.assertEqual(out["replies"][0].json()["late_workers"].__len__(), 2)


class ANoTradeOnEitherSideIsTheSameCrew(unittest.TestCase):

    def test_a_card_with_no_trade_adopts_the_subs_only_crew(self):
        """The screen's own reconcile does this, so a late man for a one-crew sub
        is not a new crew just because the card never named a trade."""
        out = run([_card("J&P", "")], [("Larry Late", "J&P", "Plumbing")])
        self.assertEqual(out["amendments"], [])
        self.assertEqual(len(out["signed"]["late_arrivals"]), 1)

    def test_a_man_with_no_trade_joins_a_subs_only_crew(self):
        out = run([_card("J&P", "Plumbing")], [("Larry Late", "J&P", "")])
        self.assertEqual(out["amendments"], [])
        self.assertEqual(len(out["signed"]["late_arrivals"]), 1)

    def test_names_compare_without_case_or_stray_spaces(self):
        out = run([_card("J&P  ", "plumbing")], [("Larry Late", "j&p", " Plumbing ")])
        self.assertEqual(out["amendments"], [])


class AnotherTenantRecordsNothing(unittest.TestCase):

    def test_an_outsider_cannot_write_to_a_signed_log(self):
        for caller in ("cp_b", "owner_none"):
            with self.subTest(caller=caller):
                out = run([_card("J&P", "Plumbing")],
                          [("Larry Late", "J&P", "Plumbing")], caller=caller)
                self.assertIn(out["replies"][0].status_code, (403, 404))
                self.assertFalse(out["signed"].get("late_arrivals"))
                self.assertEqual(out["signed"]["updated_at"], out["before"]["updated_at"])


class TheRulePureFunction(unittest.TestCase):

    LOG = {"data": {"activities": [
        {"company": "J&P", "trade": "Plumbing"},
        {"company": "Acme Drywall", "trade": ""},
        {"company": "", "trade": "Laborer"},          # a loose row: nobody's crew
        "not a card",
    ]}}

    def test_table(self):
        cases = [
            # (company, trade, belongs?)
            ("J&P", "Plumbing", True),
            ("J&P", "Electrical", False),       # second trade of a listed sub
            ("J&P", "", True),                  # one crew, he names no trade
            ("Acme Drywall", "Taping", True),   # card names no trade: adopts
            ("Acme Drywall", "", True),
            ("Other Co", "Plumbing", False),    # sub not on the log
            ("", "Plumbing", False),            # nobody to put him under
            ("UNASSIGNED", "Plumbing", False),  # the gate's placeholder
            (None, None, False),
        ]
        for company, trade, want in cases:
            with self.subTest(company=company, trade=trade):
                self.assertIs(LA.has_crew_card(
                    self.LOG, {"company": company, "trade": trade}), want)

    def test_a_loose_row_is_not_a_crew_a_man_can_join(self):
        self.assertEqual(LA.crew_cards(self.LOG),
                         [("j&p", "plumbing"), ("acme drywall", "")])

    def test_a_log_with_no_activities_has_no_card(self):
        for log in ({}, {"data": None}, {"data": {}}, {"data": {"activities": None}}, None):
            with self.subTest(log=log):
                self.assertFalse(LA.has_crew_card(log, {"company": "J&P", "trade": "x"}))

    def test_split_keeps_order(self):
        late = [{"company": "J&P", "trade": "Plumbing", "worker_name": "a"},
                {"company": "Zed", "trade": "", "worker_name": "b"},
                {"company": "J&P", "trade": "", "worker_name": "c"}]
        joins, needs = LA.split_late(self.LOG, late)
        self.assertEqual([w["worker_name"] for w in joins], ["a", "c"])
        self.assertEqual([w["worker_name"] for w in needs], ["b"])


class TheSheetSaysSoBelowTheSignature(unittest.TestCase):

    def test_nothing_is_printed_when_nobody_arrived_late(self):
        self.assertEqual(arrived_after_signing([]), "")
        self.assertEqual(arrived_after_signing(None), "")

    def test_the_block_names_who_and_when_in_new_york(self):
        html = arrived_after_signing([{
            "worker_name": "Larry <b>Late</b>", "company": "J&P", "trade": "Plumbing",
            "checked_in_at": "2026-11-18T19:12:00+00:00"}])
        self.assertIn("Arrived after signing", html)
        self.assertIn("not part of what was attested to", html)
        self.assertIn("J&amp;P", html)
        self.assertIn("2:12 PM EST", html)              # 19:12Z in November
        self.assertNotIn("<b>Late</b>", html)           # escaped, not markup

    def test_a_time_the_gate_never_anchored_prints_as_written(self):
        html = arrived_after_signing([{"worker_name": "A", "company": "B", "trade": "",
                                       "checked_in_at": "15:12"}])
        self.assertIn("15:12", html)


class TheRecordedFieldReachesTheLegalSheet(unittest.TestCase):
    """End to end through the real renderer, not just the primitive."""

    def test_the_legal_pdf_carries_the_block_only_when_there_is_something_to_say(self):
        import test_the_legal_apparatus_markers as M
        plain = M._base("daily_jobsite", general_description="plumbing")
        late = copy.deepcopy(plain)
        late["late_arrivals"] = [{"worker_id": "w1", "worker_name": "Larry Late",
                                  "company": "J&P", "trade": "Plumbing",
                                  "checked_in_at": "2026-09-09T19:12:00+00:00"}]
        self.assertNotIn("Arrived after signing", M._legal(plain))
        html = M._legal(late)
        self.assertIn("Arrived after signing", html)
        self.assertIn("Larry Late", html)
        # BELOW the CP's signature, outside the attestation.
        self.assertGreater(html.index("Arrived after signing"),
                           html.index("Competent Person Signature"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
