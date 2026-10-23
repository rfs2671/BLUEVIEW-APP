"""DOT Phase 1 A: summonses issued by DOT -- matching, the permit link, and
when they email or post.

THE GAP. Since 2025 only 8% of DOT summonses carry a block and lot and 58% have
no house number (spec v3). The recorded fixture shows both missing keys on the
operator's own block: summons 0704197771 is written "HOPKINSON AVENUE BTWN
BLAKE AVEN" (no house, cut off mid-word), and 0704345548 / 0704345557 ("588
HOPKINSON AVENUE BTWN BLAKE") were written against Blue Elm permits
B022026215B29 / B022026215B24 -- the link ydkf-mpxb records as the inspection's
novnumber.

THE RULES (operator rulings 2026-10-22/23, spec v3 A):
  * match order BBL, address, NOV -> permit (ydkf-mpxb), segment; a different
    BBL stops; a segment match is "needs confirmation", never emailed or posted
    as the project's;
  * a new summons emails only when new to Levelog AND issued by DOT within 2
    days (New York dates; undated = old), and only with the per-company flag
    dot_phase1 (the flag gates new-record emails only);
  * hearing reminders 14/7/1 for confirmed open summonses; ONE email per
    ticket x hearing date for a PENDING block match with a hearing within 14
    days; ONE email per ticket when a confirmed summons CHANGES to DEFAULTED /
    DOCKETED; all of these wait for the project's first DOT pass, flag or not;
  * the WhatsApp group posts follow the same rules.

FIXTURE: tests/fixtures/dot_summonses/oath_and_nov_links.json, recorded from
NYC Open Data on 2026-10-23, unedited. Records marked SYNTHETIC are a recorded
record with its dates (or house number) changed, said where made.

CONTROL RUN: on #853's head (feat/dot-permits-setup, 268dd087) every test here
fails -- lib/dot_summons.py, dot_sync.classify_summons / oath_segment, the
ticks, the routes and the new WhatsApp kinds do not exist. The import is
guarded so each test fails on its own assertion.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("ELIGIBILITY_REWRITE_MODE", "off")

from fastapi import HTTPException  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402

import server  # noqa: E402
import lib.feature_flags as feature_flags  # noqa: E402
from lib import dot_embargo, dot_sync  # noqa: E402
from tests.async_fake_mongo import AsyncFakeCollection, AsyncFakeDB, _Cursor  # noqa: E402

try:
    from lib import dot_summons as S  # noqa: E402
except ImportError:          # #853's head: the control run
    S = None

HERE = Path(__file__).resolve().parent
FIX = json.loads((HERE / "fixtures" / "dot_summonses" / "oath_and_nov_links.json")
                 .read_text(encoding="utf-8"))
OATH = {r["ticket_number"]: r for r in FIX["oath"]}
INSP = FIX["inspections"]
PERMITS_B = {r["permitnumber"]: r for r in json.loads(
    (HERE / "fixtures" / "dot_permits" / "hopkinson_blake_sutter.json").read_text(encoding="utf-8"))["segment"]}
FE = Path(__file__).resolve().parents[2] / "frontend"

UTC = timezone.utc
OCT23 = datetime(2026, 10, 23, 16, 0, tzinfo=UTC)      # noon in New York
TODAY = date(2026, 10, 23)

ADMIN = {"id": "u1", "_id": "u1", "role": "admin", "company_id": "c1", "email": "admin@blueelm.test"}
FULL_PM = {"id": "u4", "_id": "u4", "role": "pm", "pm_access": "full", "company_id": "c1"}
SUPER = {"id": "u3", "_id": "u3", "role": "superintendent", "company_id": "c1"}
CP = {"id": "u2", "_id": "u2", "role": "cp", "company_id": "c1"}

FRONTAGE = {"boro": "3", "on": "THOMAS S BOYLAND ST", "from": "BLAKE AVE", "to": "SUTTER AVE",
            "source": "admin", "confirmed": True}
SETUP = {"status": "confirmed", "permittees": [{"name": "BLUE ELM INC.", "norm": "BLUE ELM"}],
         "frontages": [FRONTAGE]}


def _need():
    if S is None:
        raise AssertionError("lib/dot_summons.py does not exist (#853's head)")


def _run(coro):
    return asyncio.run(coro)


def _at(d: date, hour=12) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, tzinfo=UTC)


def _iso(d: date) -> str:
    return f"{d.isoformat()}T00:00:00.000"


def _days(a: date, b: date):
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def summons(ticket, issued=None, hearing=None, **kw):
    """A recorded summons; SYNTHETIC when `issued` / `hearing` / kw change it."""
    r = copy.deepcopy(OATH[ticket])
    if issued is not None:
        r["violation_date"] = _iso(issued)
    if hearing is not None:
        r["hearing_date"] = _iso(hearing)
    r.update(kw)
    return r


#: SYNTHETIC: 0704345548 (588 Hopkinson, written against Blue Elm permit
#: B022026215B29) with the house number removed -- so only the permit link
#: can match it. 0704197771 issued today: the real block-written summons.
LINKED = summons("0704345548", violation_location_house=None,
                 violation_location_street_name="HOPKINSON AVENUE BTWN BLAKE")
BLOCK = summons("0704197771", issued=TODAY, hearing=date(2026, 11, 4),
                hearing_status="NEW ISSUANCE", balance_due="750", paid_amount="0",
                compliance_status="Penalty Due")
ADDR_TODAY = summons("0704345557", issued=TODAY)


# ── an in-memory db with a real _id uniqueness and upsert ───────────────────

class _Cur(_Cursor):
    async def to_list(self, n=None, length=None):
        return await super().to_list(n)


class _Col(AsyncFakeCollection):
    def find(self, flt=None, projection=None, **kw):
        return _Cur(super().find(flt, projection)._docs)

    async def insert_one(self, doc, **kw):
        if "_id" in doc and any(str(d.get("_id")) == str(doc["_id"]) for d in self.docs):
            raise DuplicateKeyError(f"E11000 duplicate key {doc['_id']}")
        return await super().insert_one(doc, **kw)

    async def update_one(self, flt, update, upsert=False, **kw):
        update = copy.deepcopy(update)
        res = await super().update_one(flt, update, **kw)
        if res.matched_count or not upsert:
            return res
        doc = {k: v for k, v in (flt or {}).items()
               if not k.startswith("$") and not isinstance(v, dict)}
        await self.insert_one(doc)
        return await super().update_one({"_id": doc["_id"]}, update, **kw)


class _DB(AsyncFakeDB):
    def __getitem__(self, name):
        if name not in self._c:
            self._c[name] = _Col(name)
        return self._c[name]


def _fetch(address=(), segment=(), tickets=(), inspections=(), bbl=()):
    """The network, routed on the request."""
    calls = []

    async def fetch(dataset, params):
        where = params.get("$where", "")
        calls.append((dataset, dict(params)))
        if dataset == dot_sync.OATH_DATASET:
            if "ticket_number in" in where:
                want = set(re.findall(r"'(\d+)'", where.split("ticket_number in", 1)[1]))
                return [copy.deepcopy(r) for r in tickets if r["ticket_number"] in want]
            if "violation_location_block_no" in where:
                return copy.deepcopy(list(bbl))
            if "violation_location_house" in where:
                return copy.deepcopy(list(address))
            if "violation_date >=" in where:
                return copy.deepcopy(list(segment))
            return []
        if dataset == getattr(dot_sync, "NOV_DATASET", "ydkf-mpxb"):
            return copy.deepcopy(list(inspections))
        return []
    fetch.calls = calls
    return fetch


def _permit_row(num, **kw):
    """A confirmed, address-matched project permit row from the recorded B fixture."""
    return {**dot_sync.to_log("dot_permit", PERMITS_B[num]), "_id": f"perm_{num}",
            "project_id": "p1", "company_id": "c1", "matched_by": "address",
            "match": {"how": "address", "state": "confirmed"}, "detected_at": OCT23, **kw}


class _Env:
    def __init__(self, flag=True, setup=True):
        feature_flags.cache_invalidate()
        self.db = _DB()
        self.db.companies.docs.append({"_id": "c1", "name": "Blue Elm Inc"})
        self.db.projects.docs.append({"_id": "p1", "company_id": "c1", "name": "588 Thomas S Boyland",
                                      "address": "588 Thomas S Boyland St, Brooklyn, NY",
                                      **({"dot_setup": copy.deepcopy(SETUP)} if setup else {})})
        self.db.users.docs += [dict(ADMIN), dict(CP)]
        if flag:
            self.db.feature_flags.docs.append({"flag": "dot_phase1", "enabled_for_companies": ["c1"]})
        self.send = AsyncMock(return_value={"status": "sent"})

    @property
    def project(self):
        return self.db.projects.docs[0]

    def call(self, fn, *a, **kw):
        with patch.object(server, "db", self.db):
            return _run(fn(*a, **kw))

    def sync(self, now=OCT23, **kw):
        f = _fetch(**kw)
        self.last = f
        return self.call(server._dot_sync_tick, now=now, fetch=f)

    def nov(self, inspections=INSP, now=OCT23):
        return self.call(server._dot_nov_links_tick, now=now, fetch=_fetch(inspections=inspections))

    def _mail(self, fn, now):
        feature_flags.cache_invalidate()
        with patch.object(server, "db", self.db), \
                patch.object(server, "RESEND_API_KEY", "re_test_key"), \
                patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": ""}), \
                patch("lib.notifications.send_notification", self.send):
            return _run(fn(now=now))

    def record_alerts(self, now=OCT23):
        return self._mail(server._dot_summons_record_alert_tick, now)

    def hearing_alerts(self, days):
        return [self._mail(server._dot_hearing_tick, _at(d)) for d in days]

    def emails(self, trigger=None):
        return [c.kwargs for c in self.send.await_args_list
                if trigger is None or c.kwargs["trigger_type"] == trigger]

    def row(self, ticket):
        return next(d for d in self.db.dot_logs.docs if d.get("number") == ticket)

    def board(self, user=ADMIN):
        return self.call(server.get_dot_summonses, "p1", current_user=user, project=self.project)

    def review(self, ticket, decision, user=ADMIN):
        return self.call(server.review_dot_summons, "p1", ticket,
                         body=server.DotSummonsReview(decision=decision),
                         current_user=user, project=self.project)

    def first_pass(self, **kw):
        """The project's first DOT pass (nothing new is ever emailed from it)."""
        r = self.sync(now=OCT23 - timedelta(hours=4), **kw)
        return r


# ═══ Pure rules ═════════════════════════════════════════════════════════════

class TheSegmentParse(unittest.TestCase):

    def test_the_shapes(self):
        p = dot_sync.oath_segment
        self.assertEqual(p("57 STREET BTWN 11 AVENUE AND"), {"on": "57 ST", "from": "11 AVE", "to": ""})
        self.assertEqual(p("57 STREET BTWN 11 AVENUE AND 12 AVENUE"),
                         {"on": "57 ST", "from": "11 AVE", "to": "12 AVE"})
        # real 0704197771: cut off mid-word
        self.assertEqual(p(OATH["0704197771"]["violation_location_street_name"]),
                         {"on": "HOPKINSON AVE", "from": "BLAKE AVEN", "to": ""})
        # real 0704356777: an intersection is not a segment
        self.assertIsNone(p(OATH["0704356777"]["violation_location_street_name"]))
        self.assertIsNone(p("THOMAS S BOYLAND STREET"))                  # no BTWN
        self.assertEqual(p("588 HOPKINSON AVENUE BTWN BLAKE", "588"),
                         {"on": "HOPKINSON AVE", "from": "BLAKE", "to": ""})
        self.assertEqual(p("EAST   98 STREET  BTWN  LINDEN BOULEVARD  AND HEGEMAN AV"),
                         {"on": "E 98 ST", "from": "LINDEN BLVD", "to": "HEGEMAN AVE"})

    def test_the_block_match_through_the_renamed_street_and_a_cut_name(self):
        seg = dot_sync.oath_segment(OATH["0704197771"]["violation_location_street_name"])
        self.assertTrue(dot_sync.summons_segment_matches(FRONTAGE, "3", seg))       # Hopkinson = Boyland
        self.assertTrue(dot_sync.summons_segment_matches(
            FRONTAGE, "3", {"on": "HOPKINSON AVE", "from": "SUTTER", "to": ""}))     # the TO street, 6 chars
        self.assertFalse(dot_sync.summons_segment_matches(
            FRONTAGE, "3", {"on": "HOPKINSON AVE", "from": "SUTTE", "to": ""}))      # 5 chars
        self.assertFalse(dot_sync.summons_segment_matches(FRONTAGE, "4", seg))      # borough
        self.assertFalse(dot_sync.summons_segment_matches(
            FRONTAGE, "3", {"on": "HOPKINSON AVE", "from": "PITKIN AVE", "to": ""}))


class TheMatchOrder(unittest.TestCase):

    PK = dot_sync.project_keys({"address": "588 Thomas S Boyland St, Brooklyn, NY", "bbl": "3015230001"})
    PK_NO_BBL = dot_sync.project_keys({"address": "588 Thomas S Boyland St, Brooklyn, NY"})

    def test_bbl_beats_address_and_a_different_bbl_stops(self):
        c = dot_sync.classify_summons
        same = summons("0704345548", violation_location_block_no="01523", violation_location_lot_no="0001")
        self.assertEqual(c(self.PK, SETUP, same)[:2], ("bbl", "confirmed"))
        other = summons("0704345548", violation_location_block_no="01523", violation_location_lot_no="0002")
        # address, permit link AND block all agree -- the different BBL stops it.
        self.assertIsNone(c(self.PK, SETUP, other, {"0704345548": "B022026215B29"}))

    def test_address_then_permit_then_block(self):
        c = dot_sync.classify_summons
        self.assertEqual(c(self.PK_NO_BBL, SETUP, OATH["0704345548"])[:2], ("address", "confirmed"))
        self.assertEqual(c(self.PK_NO_BBL, SETUP, LINKED, {"0704345548": "B022026215B29"}),
                         ("permit", "confirmed", "B022026215B29"))
        # Without the link it is not even "on your block": DOT cut the cross
        # street to "BLAKE", 5 characters, under the 6-character prefix rule.
        self.assertIsNone(c(self.PK_NO_BBL, SETUP, LINKED))
        self.assertEqual(c(self.PK_NO_BBL, SETUP, BLOCK)[:2], ("segment", "needs_confirmation"))
        self.assertIsNone(c(self.PK_NO_BBL, {}, BLOCK))                     # no setup: no block
        self.assertIsNone(c(self.PK_NO_BBL, SETUP, OATH["0704356777"]))     # intersection
        self.assertIsNone(c(self.PK_NO_BBL, SETUP, OATH["0704345997"]))     # Macon St

    def test_the_summons_model(self):
        log = dot_sync.to_log("dot_violation", OATH["0704345997"])
        self.assertEqual((log["balance_due"], log["penalty_imposed"], log["total_amount"], log["paid_amount"]),
                         (750, 750, 750, 0))
        self.assertEqual(log["charges"], [{"code": "AD3K", "section": "34RCNY", "amount": 750,
                                           "description": "FAILURE TO REPAIR DEFECTIVE STREET CONDITION 12 INCHES OUTWARD"}])
        self.assertEqual((log["issued_on"], log["hearing_time"], log["hearing_location"]),
                         ("2026-09-30", "08:30:00", "BROOKLYN 3"))
        self.assertEqual(dot_sync.default_result(OATH["0703862290"]), "DOCKETED")
        self.assertIsNone(dot_sync.default_result(OATH["0704345548"]))


class TheDates(unittest.TestCase):

    def test_two_days_with_new_york_dates_and_undated(self):
        _need()
        row = {"record_type": "dot_violation", "number": "1", "issued_on": "2026-10-21"}
        late = dot_embargo.ny_date(datetime(2026, 10, 24, 3, 30, tzinfo=UTC))   # 23:30 Oct 23 NY
        early = dot_embargo.ny_date(datetime(2026, 10, 24, 4, 30, tzinfo=UTC))  # 00:30 Oct 24 NY
        self.assertEqual((late, early), (date(2026, 10, 23), date(2026, 10, 24)))
        self.assertTrue(S.recently_issued(row, late))
        self.assertFalse(S.recently_issued(row, early))
        self.assertFalse(S.recently_issued({"record_type": "dot_violation", "number": "1"}, late))

    def test_hearing_thresholds(self):
        _need()
        got = {d: S.hearing_threshold(d) for d in (15, 14, 8, 7, 2, 1, 0, -1)}
        self.assertEqual(got, {15: None, 14: 14, 8: 14, 7: 7, 2: 7, 1: 1, 0: 1, -1: None})


# ═══ Through the real sync, ticks and endpoints ══════════════════════════════

class TheNewSummonsEmail(unittest.TestCase):

    def setUp(self):
        _need()

    def test_the_first_pass_is_silent(self):
        env = _Env()
        env.first_pass(address=[ADDR_TODAY])
        self.assertEqual(env.row("0704345557")["match"]["how"], "address")
        self.assertIs(env.row("0704345557")["first_pass"], True)
        r = env.record_alerts()
        self.assertEqual((env.emails(), r["new_due"]), ([], 0))

    def test_after_the_first_pass(self):
        env = _Env()
        env.first_pass()
        old = summons("0704345548", issued=TODAY - timedelta(days=5))     # SYNTHETIC dates
        env.sync(address=[ADDR_TODAY, old], segment=[BLOCK])
        seg = [p for ds, p in env.last.calls
               if ds == dot_sync.OATH_DATASET and "violation_date >=" in p.get("$where", "")]
        self.assertEqual(len(seg), 1)
        for piece in ("violation_location_borough = 'BROOKLYN'", "like '%BOYLAND%'", "like '%HOPKINSON%'",
                      "violation_date >= '2024-10-23T00:00:00'", "DEPT OF TRAN"):
            self.assertIn(piece, seg[0]["$where"])
        self.assertEqual((seg[0]["$order"], seg[0]["$limit"]), ("violation_date DESC", "400"))
        env.record_alerts()
        env.record_alerts(OCT23 + timedelta(hours=2))                       # once: the ledger
        mails = env.emails("dot_summons_new")
        self.assertEqual([m["metadata"]["ticket"] for m in mails], ["0704345557"])
        m = mails[0]
        self.assertEqual(m["recipient"], "admin@blueelm.test")
        self.assertEqual(m["subject"], "New DOT summons on 588 Thomas S Boyland / "
                                       "Nueva citación del DOT en 588 Thomas S Boyland")
        for piece in ("Issued by DOT: Oct 23, 2026 · Status: NEW ISSUANCE",
                      "Emitido por el DOT: 23 oct 2026 · Estado: NEW ISSUANCE",
                      "ADG3", "Matched by: address", "Vinculada por: dirección"):
            self.assertIn(piece, m["text"], piece)
        self.assertLess(m["text"].index("Issued by DOT"), m["text"].index("Emitido por el DOT"))
        # The block match: listed under Needs confirmation, never emailed.
        b = env.board()
        self.assertEqual([x["number"] for x in b["needs_confirmation"]], ["0704197771"])
        self.assertEqual(env.row("0704197771")["review"]["state"], "pending")
        # "It's ours": confirmed, and still no "new summons" email after the fact.
        env.review("0704197771", "accept")
        env.record_alerts(OCT23 + timedelta(hours=4))
        self.assertEqual([m["metadata"]["ticket"] for m in env.emails("dot_summons_new")], ["0704345557"])
        nums = [x["number"] for x in env.board()["summonses"]]
        self.assertEqual(nums[0], "0704197771")                        # hearing Nov 4: first
        self.assertEqual(sorted(nums), ["0704197771", "0704345548", "0704345557"])

    def test_the_flag_gates_new_record_emails_only(self):
        env = _Env(flag=False)
        env.first_pass()
        near = summons("0704345557", issued=TODAY, hearing=date(2026, 11, 6))   # SYNTHETIC
        env.sync(address=[near])
        r = env.record_alerts()
        self.assertEqual((env.emails("dot_summons_new"), r["flag_off"]), ([], 1))
        env.hearing_alerts([date(2026, 10, 23)])                            # 14 days out
        self.assertEqual([m["metadata"]["threshold"] for m in env.emails("dot_hearing_reminder")], [14])

    def test_nothing_before_the_first_pass(self):
        env = _Env()
        env.db.dot_logs.docs.append({**dot_sync.to_log("dot_violation", ADDR_TODAY), "_id": "x1",
                                     "project_id": "p1", "company_id": "c1",
                                     "match": {"how": "address", "state": "confirmed"},
                                     "detected_at": OCT23})
        r1 = env.record_alerts()
        r2 = env.hearing_alerts([date(2026, 12, 10)])[0]
        self.assertEqual((env.emails(), r1["waiting_sync"], r2["waiting_sync"]), ([], 1, 1))

    def test_a_new_frontage_later_brings_its_records_silently(self):
        env = _Env(setup=False)
        env.first_pass()
        env.project["dot_setup"] = copy.deepcopy(SETUP)                     # confirmed later
        env.sync(segment=[BLOCK])
        env.record_alerts()
        self.assertEqual(env.row("0704197771")["match"]["state"], "needs_confirmation")
        self.assertEqual(env.emails(), [])


class TheHearingReminders(unittest.TestCase):

    def setUp(self):
        _need()
        self.env = _Env()
        self.env.first_pass(address=[OATH["0704345548"]])                   # hearing Dec 24

    def test_14_7_1_once_each(self):
        self.env.hearing_alerts(_days(date(2026, 12, 9), date(2026, 12, 25)))
        mails = self.env.emails("dot_hearing_reminder")
        self.assertEqual([m["metadata"]["threshold"] for m in mails], [14, 7, 1])
        self.assertEqual(mails[0]["permit_renewal_id"], "dot:p1:hearing:0704345548:14:2026-12-24")
        self.assertEqual(mails[0]["subject"], "DOT hearing in 14 days on 588 Thomas S Boyland / "
                                              "Audiencia del DOT en 14 días en 588 Thomas S Boyland")
        self.assertIn("Hearing: Dec 24, 2026", mails[0]["text"])

    def test_a_rescheduled_hearing_gets_fresh_reminders(self):
        env = self.env
        env.hearing_alerts([date(2026, 12, 10)])
        env.sync(now=_at(date(2026, 12, 11)), address=[summons("0704345548", hearing=date(2027, 1, 7))])
        env.hearing_alerts(_days(date(2026, 12, 11), date(2027, 1, 8)))
        self.assertEqual([(m["metadata"]["threshold"], m["metadata"]["hearing_date"])
                          for m in env.emails("dot_hearing_reminder")],
                         [(14, "2026-12-24"), (14, "2027-01-07"), (7, "2027-01-07"), (1, "2027-01-07")])

    def test_a_paid_summons_gets_none(self):
        env = self.env
        env.sync(now=_at(date(2026, 12, 1)), address=[summons(
            "0704345548", hearing_status="PAID IN FULL", balance_due="0", paid_amount="250")])
        env.hearing_alerts(_days(date(2026, 12, 9), date(2026, 12, 24)))
        self.assertEqual(env.emails(), [])


class ThePendingBlockHearing(unittest.TestCase):

    def setUp(self):
        _need()
        self.env = _Env()
        self.env.first_pass(segment=[BLOCK])                                # hearing Nov 4

    def test_one_email_per_hearing_date(self):
        env = self.env
        env.hearing_alerts(_days(date(2026, 10, 15), date(2026, 11, 4)))
        mails = env.emails()
        self.assertEqual([m["trigger_type"] for m in mails], ["dot_summons_pending_hearing"])
        m = mails[0]
        self.assertIn("A DOT summons on your block has a hearing on Nov 4, 2026. Confirm whether it's yours.",
                      m["text"])
        self.assertIn("Una citación del DOT en su cuadra tiene audiencia el 4 nov 2026. Confirme si es suya.",
                      m["text"])
        self.assertEqual(m["permit_renewal_id"], "dot:p1:hearing_pending:0704197771:-:2026-11-04")
        # A new hearing date may send again.
        env.sync(now=_at(date(2026, 11, 5)), segment=[summons(
            "0704197771", issued=TODAY, hearing=date(2026, 11, 18), hearing_status="RESCHEDULED",
            balance_due="750", paid_amount="0", compliance_status="Penalty Due")])
        env.hearing_alerts(_days(date(2026, 11, 5), date(2026, 11, 18)))
        self.assertEqual([m["metadata"]["hearing_date"] for m in env.emails()], ["2026-11-04", "2026-11-18"])

    def test_accepted_gets_the_normal_reminders_rejected_gets_nothing(self):
        env = self.env
        env.review("0704197771", "accept")
        env.hearing_alerts(_days(date(2026, 10, 21), date(2026, 11, 4)))
        self.assertEqual([(m["trigger_type"], m["metadata"].get("threshold")) for m in env.emails()],
                         [("dot_hearing_reminder", 14), ("dot_hearing_reminder", 7),
                          ("dot_hearing_reminder", 1)])
        other = _Env()
        other.first_pass(segment=[BLOCK])
        other.review("0704197771", "reject")
        other.sync(now=OCT23 + timedelta(hours=2), segment=[BLOCK])        # never pending again
        other.hearing_alerts(_days(date(2026, 10, 21), date(2026, 11, 4)))
        self.assertEqual(other.emails(), [])
        self.assertEqual(other.row("0704197771")["match"]["state"], "rejected")


class TheDefaultOrDocketed(unittest.TestCase):

    def setUp(self):
        _need()

    def test_a_change_emails_once(self):
        env = _Env()
        env.first_pass(address=[OATH["0704345548"]])
        dflt = summons("0704345548", hearing_status="DEFAULTED", hearing_result="DEFAULTED")
        env.sync(now=OCT23, address=[dflt])
        env.record_alerts()
        env.sync(now=OCT23 + timedelta(hours=2), address=[summons(
            "0704345548", hearing_status="DOCKETED", hearing_result="DEFAULTED")])
        env.record_alerts(OCT23 + timedelta(hours=2))
        mails = env.emails("dot_summons_default")
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0]["subject"],
                         "DOT summons 0704345548 was marked DEFAULTED on 588 Thomas S Boyland / "
                         "La citación del DOT 0704345548 fue marcada como EN REBELDÍA (DEFAULTED) "
                         "en 588 Thomas S Boyland")
        self.assertEqual(mails[0]["permit_renewal_id"], "dot:p1:summons_default:0704345548:-:-")

    def test_already_defaulted_at_first_sight_or_pending_never(self):
        env = _Env()
        env.first_pass()
        env.sync(address=[summons("0703862290", violation_location_street_name="588 HOPKINSON AVENUE BTWN BLAKE",
                                  violation_location_house="588")])      # SYNTHETIC: real DOCKETED one at 588
        env.sync(now=OCT23 + timedelta(hours=1), segment=[BLOCK])
        env.sync(now=OCT23 + timedelta(hours=2), segment=[summons(
            "0704197771", issued=TODAY, hearing=date(2026, 11, 4), hearing_status="DEFAULTED",
            hearing_result="DEFAULTED")])
        env.record_alerts(OCT23 + timedelta(hours=3))
        self.assertEqual(env.emails("dot_summons_default"), [])


class ThePermitLink(unittest.TestCase):

    def setUp(self):
        _need()

    def test_nov_links_then_a_permit_match(self):
        env = _Env()
        env.db.dot_logs.docs += [_permit_row("B022026215B29"),
                                 _permit_row("B022026215B24", match={"how": "segment_other_permittee",
                                                                     "state": "needs_confirmation"})]
        r = env.nov()
        links = {d["_id"]: d["permit_number"] for d in env.db.dot_nov_permits.docs}
        self.assertEqual(links, {"0704345548": "B022026215B29"})        # the pending permit's: not read
        self.assertEqual((r["requests"], r["links"]), (1, 1))
        env.sync(tickets=[LINKED, summons("0704345557", violation_location_house=None)])
        row = env.row("0704345548")
        self.assertEqual(row["match"], {"how": "permit", "state": "confirmed",
                                        "permit_number": "B022026215B29"})
        tq = [p for ds, p in env.last.calls if "ticket_number in" in p.get("$where", "")]
        self.assertEqual(len(tq), 1)
        self.assertIn("'0704345548'", tq[0]["$where"])
        self.assertNotIn("0704345557", tq[0]["$where"])


class TheEndpoints(unittest.TestCase):

    def setUp(self):
        _need()

    def test_roles_and_reaccepting(self):
        env = _Env()
        env.first_pass(segment=[BLOCK])
        for user in (CP, SUPER):
            with self.subTest(user["role"]), self.assertRaises(HTTPException) as ctx:
                env.review("0704197771", "accept", user=user)
            self.assertEqual(ctx.exception.status_code, 403)
        self.assertFalse(env.board(user=CP)["can_review"])
        env.review("0704197771", "reject", user=FULL_PM)
        self.assertEqual([x["number"] for x in env.board()["rejected"]], ["0704197771"])
        env.review("0704197771", "accept")                               # from the Not-ours list
        self.assertEqual(env.row("0704197771")["match"]["state"], "confirmed")
        with self.assertRaises(HTTPException) as ctx:
            env.review("0704197771", "reject")
        self.assertEqual(ctx.exception.status_code, 409)
        acts = [(a["action"], a["details"]["decision"]) for a in env.db.audit_logs.docs]
        self.assertEqual(acts, [("dot_summons_review", "reject"), ("dot_summons_review", "accept")])

    def test_routes_and_job(self):
        for method, path, write in (("GET", "/api/projects/{project_id}/dot/summonses", False),
                                    ("POST", "/api/projects/{project_id}/dot/summonses/{ticket}/review", True)):
            route = next((r for r in server.app.routes
                          if getattr(r, "path", "") == path and method in getattr(r, "methods", ())), None)
            self.assertIsNotNone(route, path)
            calls = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
            self.assertIn("require_project_access", calls)
            if write:
                self.assertIn("require_approved", calls)
        src = Path(server.__file__).read_text(encoding="utf-8")
        i = src.index("id='dot_nov_links'")
        self.assertTrue("CronTrigger(hour=5, minute=45" in src[i - 200:i], "dot_nov_links is not at 05:45")

    def test_the_board_lists_open_then_settled(self):
        env = _Env()
        env.first_pass(address=[OATH["0704345548"], summons("0704345557", hearing_status="PAID IN FULL",
                                                           balance_due="0", paid_amount="750")])
        b = env.board()
        self.assertEqual([(x["number"], x["settled"]) for x in b["summonses"]],
                         [("0704345548", False), ("0704345557", True)])
        x = b["summonses"][0]
        self.assertEqual((x["how"], x["balance_due"], x["charges"][0]["code"], x["hearing_location"]),
                         ("address", 250, "AD11", OATH["0704345548"].get("scheduled_hearing_location")))


class TheStrings(unittest.TestCase):

    def test_dot_compliance_carries_the_summons_strings_in_en_and_es(self):
        en = (FE / "src" / "i18n" / "en.js").read_text(encoding="utf-8")
        es = (FE / "src" / "i18n" / "es.js").read_text(encoding="utf-8")
        en, es = en[en.index("dotCompliance: {"):], es[es.index("dotCompliance: {"):]
        for key, e, s in (("summonsesTitle", "Summonses", "Citaciones"),
                          ("itsOurs", "It's ours", "Es nuestra"),
                          ("hearingIn", "Hearing in {n} days", "Audiencia en {n} días"),
                          ("summonsOnYourBlock", "On your block: {segment}", "En su cuadra: {segment}")):
            self.assertTrue(f"{key}: " in en and e in en, f"en {key}")
            self.assertTrue(f"{key}: " in es and s in es, f"es {key}")
        panel = (FE / "src" / "components" / "DotCompliancePanel.jsx").read_text(encoding="utf-8")
        self.assertTrue("dobAPI.getDotSummonses(projectId)" in panel, "the panel does not load summonses")
        self.assertTrue("onReviewSummons(x.number, 'accept')" in panel, "no It's-ours action")


# ═══ WhatsApp: the group posts follow the same rules ══════════════════════════

from tests.test_whatsapp_gc_alerts import (  # noqa: E402
    CO_A, _Ctx, _confirm, _group_sends, _no_ai, _world as _gc_world,
)

GC_DAY = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)      # 11 AM ET


def _gc_row(ticket, rec, **kw):
    row = {**dot_sync.to_log("dot_violation", rec), "_id": f"d_{ticket}", "project_id": "proj_a",
           "company_id": CO_A, "detected_at": GC_DAY}
    row.update(kw)
    return row


class TheGroupPosts(unittest.TestCase):

    def setUp(self):
        _need()

    def _ticks(self, db, times, add=None):
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._gc_alerts_tick(times[0]))                       # baselines
            if add:
                db.dot_logs.rows.extend(add)
            for t in times[1:]:
                _run(server._gc_alerts_tick(t))
            return [x["message"] for x in _group_sends(c)]

    def test_new_summons_posts_only_own_matches_issued_within_two_days(self):
        db = _gc_world()
        add = [_gc_row("0704345557", ADDR_TODAY, match={"how": "address", "state": "confirmed"}),
               _gc_row("0704345548", summons("0704345548", issued=TODAY - timedelta(days=5)),
                       match={"how": "address", "state": "confirmed"}),
               _gc_row("0704197771", BLOCK, match={"how": "segment", "state": "needs_confirmation"}),
               _gc_row("0703862290", summons("0703862290", issued=TODAY),
                       match={"how": "segment", "state": "confirmed"})]          # accepted block match
        texts = self._ticks(db, [GC_DAY, GC_DAY + timedelta(minutes=15), GC_DAY + timedelta(hours=2)], add)
        self.assertEqual(sum("#0704345557" in t for t in texts), 1, texts)   # own match, today: once
        for gone in ("#0704345548",     # 5 days old
                     "#0703862290"):    # an ACCEPTED block match never posts as new
            self.assertFalse(any(gone in t for t in texts), (gone, texts))
        # The pending block match's only post is the hearing one, never "new".
        self.assertFalse(any("#0704197771" in t and "New DOT summons" in t for t in texts), texts)

    def test_hearing_pending_and_default_posts(self):
        db = _gc_world()
        conf = _gc_row("0704345548", summons("0704345548", hearing=date(2026, 11, 6)),
                       match={"how": "address", "state": "confirmed"})
        pend = _gc_row("0704197771", BLOCK, match={"how": "segment", "state": "needs_confirmation"})
        dflt = _gc_row("0704356777", summons("0704356777", hearing_result="DEFAULTED"),
                       match={"how": "address", "state": "confirmed"},
                       default_event={"result": "DEFAULTED", "at": GC_DAY})
        texts = self._ticks(db, [GC_DAY, GC_DAY + timedelta(minutes=15), GC_DAY + timedelta(hours=1)],
                            [conf, pend, dflt])
        self.assertTrue(any("DOT hearing in 14 days (Nov 6, 2026)" in t and "Audiencia del DOT en 14 días" in t
                            for t in texts), texts)
        self.assertTrue(any("A DOT summons on your block has a hearing on Nov 4, 2026" in t
                            and "Confirme si es suya" in t for t in texts), texts)
        self.assertTrue(any("This DOT summons was marked DEFAULTED" in t and "EN REBELDÍA" in t
                            for t in texts), texts)
        self.assertEqual(sum("#0704197771" in t for t in texts), 1)       # the pending one: once


if __name__ == "__main__":
    unittest.main()
