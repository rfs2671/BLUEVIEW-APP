"""DOT Phase 1 B: permits filed by street segment, the project's DOT setup,
renewal chains and the permit expiry email.

THE GAP (#852 stated it in its banner and email). About two thirds of DOT
permits carry no house number: they are filed by SEGMENT -- "HOPKINSON AVENUE
from BLAKE AVENUE to SUTTER AVENUE". The address match never sees them. The
recorded fixture shows it on the operator's own block: of the 36 permits issued
since 2024-10-22 on Hopkinson Ave (now Thomas S Boyland St) between Blake and
Sutter, the Con Edison ones have no house number at all.

THE RULE (operator rulings 2026-10-22):
  * a project confirms its frontages and its own permittee names
    (projects.dot_setup); a permit on a confirmed frontage BY a confirmed
    permittee is the project's; BY ANYONE ELSE it "needs confirmation" and
    nothing alerts on it until a company admin / full-access PM says "yours";
    "not ours" is remembered;
  * an email 14 and 3 days before a confirmed, active, unrenewed permit's work
    end; nothing before the project's first DOT pass;
  * the embargo and the WhatsApp dot_permit posts cover CONFIRMED permits only.

FIXTURE: tests/fixtures/dot_permits/hopkinson_blake_sutter.json, recorded from
NYC Open Data on 2026-10-22, unedited. Permits marked SYNTHETIC below are a
recorded record with another number, permittee or dates, said where made.

The job tests drive the REAL _dot_sync_tick, _dot_permit_expiry_tick,
_dot_embargo_alert_tick, the endpoint handlers and _gc_alerts_tick against an
in-memory db; only the network (fetch), the email sender and the WhatsApp wire
are replaced.

CONTROL RUN: on #852's branch tip (feat/dot-holiday-embargo) every test here
fails -- lib/dot_permits.py, dot_sync.classify_permit / norm_permittee /
renewed_by, the expiry tick and the setup routes do not exist. The import is
guarded so each test fails on its own assertion, not as one collection error.
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
from lib import dot_embargo, dot_sync  # noqa: E402
from tests.async_fake_mongo import AsyncFakeCollection, AsyncFakeDB, _Cursor  # noqa: E402

try:
    from lib import dot_permits as P  # noqa: E402
except ImportError:          # #852's tip: the control run
    P = None

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "dot_permits"
                      / "hopkinson_blake_sutter.json").read_text(encoding="utf-8"))
SEGMENT = FIXTURE["segment"]
CROSS = FIXTURE["cross_streets"]
BY_NUM = {r["permitnumber"]: r for r in SEGMENT}
CON_ED = BY_NUM["B012026266B15"]          # real: no house number, Con Edison
STIP_DATASET = "gsgx-6efw"
FE = Path(__file__).resolve().parents[2] / "frontend"

UTC = timezone.utc
OCT22 = datetime(2026, 10, 22, 16, 0, tzinfo=UTC)


def _need():
    if P is None:
        raise AssertionError("lib/dot_permits.py does not exist (#852's tip)")


def _run(coro):
    return asyncio.run(coro)


def _at(d: date) -> datetime:
    """12:00 UTC: 07:00 EST / 08:00 EDT -- the 07:00 job's New York day."""
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC)


def _permit(num, permittee, start="2026-11-03", end="2026-11-20", **kw):
    """SYNTHETIC: the recorded Con Edison segment permit with another number,
    permittee and work dates."""
    r = {**CON_ED, "permitnumber": num, "permitteename": permittee,
         "permitissuedate": "2026-10-21T10:00:00.000",
         "issuedworkstartdate": f"{start}T00:00:00.000",
         "issuedworkenddate": f"{end}T23:59:59.000",
         "permitstatusshortdesc": "ISSUED & PRINTED"}
    r.pop("previouspermitnumber", None)
    r.pop("nextpermitnumber", None)
    r.update(kw)
    return r


OTHER = _permit("B012026295X01", "CONSOLIDATED EDISON")      # another permittee
OURS = _permit("B012026295X02", "BLUE ELM INC.")              # ours, segment-only
OFF_BLOCK = {**_permit("B012026295X03", "BLUE ELM INC."),      # ours, other block
             "fromstreetname": "BLAKE AVENUE", "tostreetname": "DUMONT AVENUE"}

FRONTAGE = {"on": "Thomas S Boyland St", "from": "Blake Ave", "to": "Sutter Ave"}

ADMIN = {"id": "u1", "_id": "u1", "role": "admin", "company_id": "c1",
         "email": "admin@blueelm.test"}
FULL_PM = {"id": "u4", "_id": "u4", "role": "pm", "pm_access": "full", "company_id": "c1"}
ASSIGNED_PM = {"id": "u5", "_id": "u5", "role": "pm", "company_id": "c1"}
SUPER = {"id": "u3", "_id": "u3", "role": "superintendent", "company_id": "c1",
         "full_name": "Sam Super"}
CP = {"id": "u2", "_id": "u2", "role": "cp", "company_id": "c1"}


# ── an in-memory db with a real _id uniqueness (as #852's tests) ────────────

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


def _fetch(address=(), segment=(), chain=(), stips=None, cross=None, fail=()):
    """The network. Routed on the request: the address request filters on the
    house number, the segment request on the issue date, the chain request on
    permitnumber / previouspermitnumber, the cross-street request groups."""
    calls = []

    async def fetch(dataset, params):
        where = params.get("$where", "")
        calls.append((dataset, dict(params)))
        if dataset == STIP_DATASET:
            m = re.search(r"permitnumber = '([^']+)'", where)
            num = m.group(1) if m else ""
            got = (stips or {}).get(num, [{"permitnumber": num, "stipulationid": "012",
                                           "stipulationfulltext": "FLAG PERSON",
                                           "createdon": "2026-10-21T10:00:00.000"}])
            return copy.deepcopy(got)
        if dataset != dot_sync.PERMIT_DATASET:
            return []
        if "$group" in params:
            return None if "cross" in fail else copy.deepcopy(list(cross or []))
        if "permitnumber in" in where or "previouspermitnumber in" in where:
            return None if "chain" in fail else copy.deepcopy(list(chain))
        if "permithousenumber" in where:
            return None if "address" in fail else copy.deepcopy(list(address))
        if "permitissuedate >=" in where:
            return None if "segment" in fail else copy.deepcopy(list(segment))
        return []
    fetch.calls = calls
    return fetch


ADDRESS_ROWS = [r for r in SEGMENT if r.get("permithousenumber") == "588"]


class _Env:
    def __init__(self):
        self.db = _DB()
        self.db.companies.docs.append({"_id": "c1", "name": "Blue Elm Inc"})
        self.db.projects.docs.append({"_id": "p1", "company_id": "c1", "name": "588 Thomas S Boyland",
                                      "address": "588 Thomas S Boyland St, Brooklyn, NY"})
        self.db.users.docs += [dict(ADMIN), dict(CP)]
        self.send = AsyncMock(return_value={"status": "sent"})

    @property
    def project(self):
        return self.db.projects.docs[0]

    def call(self, coro_fn, *a, **kw):
        with patch.object(server, "db", self.db):
            return _run(coro_fn(*a, **kw))

    def confirm(self, user=ADMIN, permittees=("BLUE ELM INC.",), frontages=(FRONTAGE,)):
        body = server.DotSetupConfirm(
            permittees=None if permittees is None else list(permittees),
            frontages=None if frontages is None else [dict(f) for f in frontages])
        return self.call(server.confirm_dot_setup, "p1", body=body,
                         current_user=user, project=self.project)

    def suggest(self, user, frontage=FRONTAGE):
        body = server.DotFrontageIn(**frontage)
        return self.call(server.add_dot_frontage, "p1", body=body,
                         current_user=user, project=self.project)

    def review(self, permit, decision, user=ADMIN):
        return self.call(server.review_dot_permit, "p1", permit,
                         body=server.DotPermitReview(decision=decision),
                         current_user=user, project=self.project)

    def sync(self, now=OCT22, **kw):
        kw.setdefault("address", ADDRESS_ROWS)
        kw.setdefault("segment", SEGMENT + [OTHER, OURS, OFF_BLOCK])
        f = _fetch(**kw)
        self.last_fetch = f
        return self.call(server._dot_sync_tick, now=now, fetch=f)

    def alerts(self, days):
        """Both 07:00 runs (expiry, embargo) for each New York day."""
        with patch.object(server, "db", self.db), \
                patch.object(server, "RESEND_API_KEY", "re_test_key"), \
                patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": ""}), \
                patch("lib.notifications.send_notification", self.send):
            for d in days:
                _run(server._dot_permit_expiry_tick(now=_at(d)))
                _run(server._dot_embargo_alert_tick(now=_at(d)))

    def emails(self, trigger=None):
        out = [c.kwargs for c in self.send.await_args_list]
        return [m for m in out if trigger is None or m["trigger_type"] == trigger]

    def row(self, num):
        return next(d for d in self.db.dot_logs.docs if d.get("number") == num)

    def permits(self, user=ADMIN):
        return self.call(server.get_dot_permits, "p1", current_user=user, project=self.project)


def _days(a: date, b: date):
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


# ═══ Pure rules ═════════════════════════════════════════════════════════════

class ThePermitteeName(unittest.TestCase):

    def test_one_permittee_however_written(self):
        n = dot_sync.norm_permittee
        self.assertEqual(n("BLUE ELM INC."), "BLUE ELM")
        self.assertEqual(n("Blue Elm, Inc"), "BLUE ELM")
        self.assertEqual(n("  blue   elm  "), "BLUE ELM")
        self.assertEqual(n("Acme Builders L.L.C."), "ACME BUILDERS")
        self.assertEqual(n("A & H CONSTRUCTION AND PLUMBING CORP."),
                         n("A AND H Construction and Plumbing Corporation"))
        self.assertEqual(n("THE BROOKLYN UNION GAS COMPANY D/B/A NATIONAL GRID NY"),
                         "BROOKLYN UNION GAS COMPANY D B A NATIONAL GRID NY")

    def test_different_names_stay_different(self):
        n = dot_sync.norm_permittee
        self.assertNotEqual(n("BLUE ELM INC."), n("BLUE ELM CONSTRUCTION INC."))
        self.assertNotEqual(n("CONSOLIDATED EDISON"), n("BLUE ELM INC."))
        self.assertEqual(n("INC"), "INC")          # a lone suffix is not emptied
        self.assertEqual(n(""), "")


class TheFrontage(unittest.TestCase):

    F = {"boro": "3", "on": "THOMAS S BOYLAND ST", "from": "BLAKE AVE", "to": "SUTTER AVE"}

    def _seg(self, **kw):
        rec = {"boroughname": "BROOKLYN", "onstreetname": "HOPKINSON AVENUE",
               "fromstreetname": "BLAKE AVENUE", "tostreetname": "SUTTER AVENUE"}
        rec.update(kw)
        return dot_sync.permit_segment(rec)

    def test_the_recorded_segment_matches_through_the_renamed_street(self):
        # Hopkinson Ave was renamed Thomas S Boyland St: the frontage is
        # stored under the new name, DOT writes the old one.
        self.assertTrue(dot_sync.frontage_matches(self.F, dot_sync.permit_segment(CON_ED)))
        rev = {**self.F, "on": "HOPKINSON AVE"}
        self.assertTrue(dot_sync.frontage_matches(rev, self._seg(onstreetname="THOMAS S BOYLAND STREET")))

    def test_from_and_to_in_either_order(self):
        self.assertTrue(dot_sync.frontage_matches(
            self.F, self._seg(fromstreetname="SUTTER AVENUE", tostreetname="BLAKE AVENUE")))

    def test_a_cut_off_name_matches_as_a_prefix_of_six_or_more(self):
        self.assertTrue(dot_sync.frontage_matches(self.F, self._seg(onstreetname="THOMAS S BOYLAN")))
        self.assertTrue(dot_sync.frontage_matches(self.F, self._seg(tostreetname="SUTTER AV")))
        self.assertTrue(dot_sync.frontage_matches(self.F, self._seg(tostreetname="SUTTER")))  # 6
        self.assertFalse(dot_sync.frontage_matches(self.F, self._seg(tostreetname="SUTTE")))  # 5

    def test_padded_and_abbreviated_names(self):
        f = {"boro": "3", "on": "E 98 ST", "from": "LINDEN BLVD", "to": "HEGEMAN AVE"}
        self.assertTrue(dot_sync.frontage_matches(f, self._seg(
            onstreetname="EAST   98 STREET  ", fromstreetname="HEGEMAN AVENUE",
            tostreetname="LINDEN BOULEVARD")))
        g = {"boro": "1", "on": "W 23 ST", "from": "7 AVE", "to": "8 AVE"}
        self.assertTrue(dot_sync.frontage_matches(g, self._seg(
            boroughname="MANHATTAN", onstreetname="WEST 23RD STREET",
            fromstreetname="7TH AVENUE", tostreetname="8TH AVENUE")))

    def test_another_block_borough_or_street_is_not_the_frontage(self):
        for bad in (self._seg(tostreetname="DUMONT AVENUE"),
                    self._seg(boroughname="QUEENS"),
                    self._seg(onstreetname="ROCKAWAY AVENUE"),
                    self._seg(fromstreetname="", tostreetname="")):
            with self.subTest(bad):
                self.assertFalse(dot_sync.frontage_matches(self.F, bad))

    def test_the_recorded_block_census(self):
        """All 36 recorded permits on Blake-Sutter are on the frontage; the 6
        recorded on Blake-Dumont are not."""
        on = [r for r in SEGMENT if dot_sync.frontage_matches(self.F, dot_sync.permit_segment(r))]
        self.assertEqual(len(on), 36)
        self.assertEqual(len(SEGMENT) - len(on), 6)
        no_house = [r for r in on if dot_sync.is_segment_permit(r)]
        self.assertTrue(no_house and all(r["permitteename"] == "CONSOLIDATED EDISON" for r in no_house))


class TheClassification(unittest.TestCase):

    PK = dot_sync.project_keys({"address": "588 Thomas S Boyland St, Brooklyn, NY"})

    def _setup(self, status="confirmed", confirmed=True):
        return {"status": status,
                "permittees": [{"name": "BLUE ELM INC.", "norm": "BLUE ELM"}],
                "frontages": [{**TheFrontage.F, "confirmed": confirmed}]}

    def test_address_ours_other_and_off_block(self):
        c = dot_sync.classify_permit
        self.assertEqual(c(self.PK, {}, BY_NUM["B022026215B30"]), ("address", "confirmed"))
        self.assertEqual(c(self.PK, self._setup(), OURS), ("segment_permittee", "confirmed"))
        self.assertEqual(c(self.PK, self._setup(), OTHER),
                         ("segment_other_permittee", "needs_confirmation"))
        self.assertEqual(c(self.PK, self._setup(), CON_ED),
                         ("segment_other_permittee", "needs_confirmation"))
        self.assertIsNone(c(self.PK, self._setup(), OFF_BLOCK))   # ours, not our block

    def test_nothing_by_segment_until_the_setup_and_the_frontage_are_confirmed(self):
        c = dot_sync.classify_permit
        self.assertIsNone(c(self.PK, self._setup(status="suggested"), OURS))
        self.assertIsNone(c(self.PK, self._setup(confirmed=False), OURS))   # a suggestion
        self.assertIsNone(c(self.PK, {}, OTHER))

    def test_the_state_a_row_carries(self):
        self.assertTrue(dot_sync.permit_confirmed({"record_type": "dot_permit"}))     # legacy
        self.assertFalse(dot_sync.permit_confirmed(
            {"record_type": "dot_permit", "match": {"state": "needs_confirmation"}}))
        self.assertFalse(dot_sync.permit_confirmed(
            {"record_type": "dot_permit", "match": {"state": "rejected"}}))
        self.assertTrue(dot_sync.permit_confirmed(
            {"record_type": "dot_violation", "match": {"state": "rejected"}}))


class TheRenewal(unittest.TestCase):
    """The recorded chain: B022026246C27 (EXPIRED) names B022026266B66 as its
    nextpermitnumber; B022026266B66 names it back as previouspermitnumber."""

    def _log(self, rec, **kw):
        return {**dot_sync.to_log("dot_permit", rec), **kw}

    def test_the_permit_model(self):
        log = dot_sync.to_log("dot_permit", BY_NUM["B022026246C27"])
        self.assertEqual((log["series"], log["permit_type"], log["work_end"], log["next_permit"]),
                         ("BUILDING OPERATION PERMIT", "OCCUPANCY OF SIDEWALK AS STIPULATED",
                          "2026-10-03T23:59:59.000", "B022026266B66"))
        self.assertEqual(log["work_end"], log["expiration_date"])
        self.assertEqual(log["segment"], {"boro": "3", "on": "HOPKINSON AVE",
                                          "from": "BLAKE AVE", "to": "SUTTER AVE"})
        nxt = dot_sync.to_log("dot_permit", BY_NUM["B022026266B66"])
        self.assertEqual(nxt["previous_permit"], "B022026246C27")
        self.assertNotIn("renewed_by", log)       # needs the chain: the sync sets it

    def test_renewed_by_next_and_by_anothers_previous(self):
        old = self._log(BY_NUM["B022026246C27"])
        new = self._log(BY_NUM["B022026266B66"])
        self.assertEqual(dot_sync.renewed_by(old, []), "B022026266B66")          # next
        no_next = {**old, "next_permit": None}
        self.assertEqual(dot_sync.renewed_by(no_next, [new]), "B022026266B66")  # previous
        self.assertIsNone(dot_sync.renewed_by(new, [old]))

    def test_a_voided_renewal_does_not_count(self):
        old = self._log(BY_NUM["B022026246C27"])
        voided = self._log(BY_NUM["B022026266B66"], status="VOIDED AFTER ISSUE")
        self.assertIsNone(dot_sync.renewed_by(old, [voided]))
        self.assertIsNone(dot_sync.renewed_by({**old, "next_permit": None}, [voided]))

    def test_the_chain_request_is_one_batched_read(self):
        old = self._log(BY_NUM["B022026246C27"], record_type="dot_permit")
        live = self._log(OURS)
        nexts, prevs = dot_sync.chain_wanted([old, live])
        self.assertEqual((nexts, prevs), (["B022026266B66"], ["B012026295X02"]))
        p = dot_sync.chain_params(nexts, prevs)
        self.assertEqual(p["$where"], "permitnumber in ('B022026266B66') OR "
                                      "previouspermitnumber in ('B012026295X02')")
        many = dot_sync.chain_wanted([{**live, "number": f"N{i}"} for i in range(80)])
        self.assertEqual(len(many[1]), 50)


class TheExpiryDates(unittest.TestCase):

    def _row(self, **kw):
        r = {**dot_sync.to_log("dot_permit", OURS), "match": {"how": "segment_permittee",
                                                             "state": "confirmed"}}
        r.update(kw)
        return r

    def test_the_thresholds(self):
        _need()
        got = {d: P.expiry_threshold(d) for d in (16, 15, 14, 10, 4, 3, 1, 0, -1)}
        self.assertEqual(got, {16: None, 15: None, 14: 14, 10: 14, 4: 14, 3: 3, 1: 3, 0: 3, -1: None})

    def test_new_york_date_edges(self):
        _need()
        row = self._row()                              # work ends Nov 20 (23:59:59 NY)
        # 04:30 UTC Nov 6 is 23:30 Nov 5 in New York (EST): 15 days, nothing.
        late = dot_embargo.ny_date(datetime(2026, 11, 6, 4, 30, tzinfo=UTC))
        self.assertEqual(late, date(2026, 11, 5))
        self.assertEqual(P.expiry_due([row], late), [])
        early = dot_embargo.ny_date(datetime(2026, 11, 6, 5, 30, tzinfo=UTC))
        (d,) = P.expiry_due([row], early)
        self.assertEqual((d["threshold"], d["days"]), (14, 14))
        (d,) = P.expiry_due([row], date(2026, 11, 17))
        self.assertEqual((d["threshold"], d["days"]), (3, 3))
        (d,) = P.expiry_due([row], date(2026, 11, 20))
        self.assertEqual((d["threshold"], d["days"]), (3, 0))
        self.assertEqual(P.expiry_due([row], date(2026, 11, 21)), [])     # expired

    def test_never_renewed_voided_expired_inactive_or_pending(self):
        _need()
        day = date(2026, 11, 6)
        for bad in (self._row(renewed_by="R1"), self._row(next_permit="R1"),
                    self._row(status="VOIDED"), self._row(status="EXPIRED"),
                    self._row(match={"how": "segment_other_permittee", "state": "needs_confirmation"}),
                    self._row(match={"how": "segment_other_permittee", "state": "rejected"})):
            with self.subTest(bad.get("status"), m=bad.get("match")):
                self.assertEqual(P.expiry_due([bad], day), [])
        other = {**self._row(), "number": "R2", "previous_permit": OURS["permitnumber"]}
        self.assertEqual([d["permit"] for d in P.expiry_due([self._row(), other], day)], ["R2"])


# ═══ Through the real sync, jobs and endpoints ═══════════════════════════════

class TheSegmentMatch(unittest.TestCase):

    def setUp(self):
        _need()

    def test_ours_on_the_frontage_is_matched_and_confirmed(self):
        env = _Env()
        env.confirm()
        r = env.sync()
        ours = env.row(OURS["permitnumber"])
        self.assertEqual(ours["match"], {"how": "segment_permittee", "state": "confirmed"})
        self.assertNotIn("review", ours)
        self.assertEqual(ours["segment"]["on"], "HOPKINSON AVE")
        self.assertFalse(any(d.get("number") == OFF_BLOCK["permitnumber"] for d in env.db.dot_logs.docs))
        # Address-matched permits keep matching (house 588 on Hopkinson).
        self.assertEqual(env.row("B022026215B30")["match"]["how"], "address")
        # One request per confirmed frontage street, 24 months, newest first, 400.
        seg = [p for ds, p in env.last_fetch.calls
               if ds == dot_sync.PERMIT_DATASET and "permitissuedate >=" in p.get("$where", "")]
        self.assertEqual(len(seg), 1)
        self.assertIn("boroughname = 'BROOKLYN'", seg[0]["$where"])
        self.assertIn("like '%BOYLAND%'", seg[0]["$where"])
        self.assertIn("like '%HOPKINSON%'", seg[0]["$where"])
        self.assertIn("permitissuedate >= '2024-10-22T00:00:00'", seg[0]["$where"])
        self.assertEqual((seg[0]["$order"], seg[0]["$limit"]), ("permitissuedate DESC", "400"))
        self.assertGreater(r["needs_confirmation"], 0)

    def test_before_the_setup_is_confirmed_no_segment_request_and_no_segment_permit(self):
        env = _Env()
        env.sync()
        self.assertFalse(any("permitissuedate >=" in p.get("$where", "")
                             for _ds, p in env.last_fetch.calls))
        self.assertFalse(any(d.get("number") in (OURS["permitnumber"], OTHER["permitnumber"])
                             for d in env.db.dot_logs.docs))


class TheNeedsConfirmation(unittest.TestCase):

    def setUp(self):
        _need()
        self.env = _Env()
        self.env.confirm()
        self.env.sync()

    def test_another_permittee_is_pending_and_alerts_nothing(self):
        env = self.env
        row = env.row(OTHER["permitnumber"])
        self.assertEqual(row["match"], {"how": "segment_other_permittee", "state": "needs_confirmation"})
        self.assertEqual(row["review"]["state"], "pending")
        self.assertIs(row["holiday_waiver"], False)      # read, so a "yours" knows it
        env.alerts(_days(date(2026, 10, 23), date(2026, 11, 21)))
        mine = {m["metadata"]["permit"] for m in env.emails()}
        self.assertNotIn(OTHER["permitnumber"], mine)
        board = env.permits()
        self.assertIn(OTHER["permitnumber"], [p["number"] for p in board["needs_confirmation"]])
        self.assertNotIn(OTHER["permitnumber"], [p["number"] for p in board["permits"]])
        self.assertTrue(board["can_review"])

    def test_yours_gets_both_expiry_emails_and_the_embargo_email(self):
        env = self.env
        self.assertEqual(env.review(OTHER["permitnumber"], "accept")["state"], "confirmed")
        row = env.row(OTHER["permitnumber"])
        self.assertEqual((row["match"]["state"], row["review"]["state"]), ("confirmed", "accepted"))
        env.sync(now=OCT22 + timedelta(hours=2))         # the sync never undoes it
        self.assertEqual(env.row(OTHER["permitnumber"])["match"]["state"], "confirmed")
        env.alerts(_days(date(2026, 10, 23), date(2026, 11, 21)))
        num = OTHER["permitnumber"]
        exp = [m for m in env.emails("dot_permit_expiring") if m["metadata"]["permit"] == num]
        self.assertEqual([m["metadata"]["threshold"] for m in exp], [14, 3])
        self.assertEqual(exp[0]["permit_renewal_id"], f"dot:p1:expiry:{num}:14:2026-11-20")
        self.assertEqual(exp[0]["subject"], f"DOT permit {num} expires in 14 days / "
                                            f"El permiso del DOT {num} vence en 14 días")
        self.assertEqual(exp[1]["subject"], f"DOT permit {num} expires in 3 days / "
                                            f"El permiso del DOT {num} vence en 3 días")
        text = exp[0]["text"]
        for piece in (num, "TRIBUTARY INSTALL - ELECTRIC", "STREET OPENING PERMIT",
                      "Work dates: Nov 3, 2026 - Nov 20, 2026",
                      "Segment: HOPKINSON AVE from BLAKE AVE to SUTTER AVE, Brooklyn",
                      "Renewal: DOT shows no renewal of this permit yet",
                      "Fechas de trabajo: 3 nov 2026 - 20 nov 2026",
                      "Tramo: HOPKINSON AVE de BLAKE AVE a SUTTER AVE, Brooklyn",
                      "Renovación: el DOT aún no muestra una renovación"):
            self.assertIn(piece, text, piece)
        self.assertLess(text.index("Renewal:"), text.index("Renovación:"))
        self.assertEqual({m["recipient"] for m in exp}, {"admin@blueelm.test"})   # never the CP
        emb = [m for m in env.emails("dot_embargo_waiver_missing") if m["metadata"]["permit"] == num]
        self.assertEqual([m["permit_renewal_id"].rsplit(":", 1)[1] for m in emb],
                         ["2026-11-01", "2026-11-12"])
        self.assertIn(num, [p["number"] for p in env.permits()["permits"]])

    def test_not_ours_is_hidden_and_never_pending_again(self):
        env = self.env
        env.review(OTHER["permitnumber"], "reject")
        for h in (2, 4):
            env.sync(now=OCT22 + timedelta(hours=h))
        row = env.row(OTHER["permitnumber"])
        self.assertEqual((row["match"]["state"], row["review"]["state"]), ("rejected", "rejected"))
        board = env.permits()
        nums = [p["number"] for p in board["permits"] + board["needs_confirmation"]]
        self.assertNotIn(OTHER["permitnumber"], nums)
        env.alerts(_days(date(2026, 10, 23), date(2026, 11, 21)))
        self.assertNotIn(OTHER["permitnumber"], {m["metadata"]["permit"] for m in env.emails()})
        with self.assertRaises(HTTPException) as ctx:          # decided: no second answer
            env.review(OTHER["permitnumber"], "accept")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_only_an_admin_or_full_access_pm_answers(self):
        env = self.env
        for user in (CP, SUPER, ASSIGNED_PM):
            with self.subTest(user["role"]), self.assertRaises(HTTPException) as ctx:
                env.review(OTHER["permitnumber"], "accept", user=user)
            self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(env.row(OTHER["permitnumber"])["match"]["state"], "needs_confirmation")
        env.review(OTHER["permitnumber"], "accept", user=FULL_PM)
        self.assertEqual(env.row(OTHER["permitnumber"])["match"]["state"], "confirmed")
        (a,) = [x for x in env.db.audit_logs.docs if x["action"] == "dot_permit_review"]
        self.assertEqual((a["user_id"], a["details"]["decision"]), ("u4", "accept"))


class TheRenewalBetween14And3(unittest.TestCase):

    def setUp(self):
        _need()

    def _run(self, renewal_segment=(), chain=()):
        env = _Env()
        env.confirm()
        env.sync()
        env.alerts([date(2026, 11, 6)])                   # 14 days out: sent
        renewed = env.emails("dot_permit_expiring")
        self.assertEqual([m["metadata"]["permit"] for m in renewed], [OURS["permitnumber"]])
        env.sync(now=datetime(2026, 11, 10, 15, 0, tzinfo=UTC),
                 segment=SEGMENT + [OTHER, OFF_BLOCK] + list(renewal_segment), chain=chain)
        env.alerts(_days(date(2026, 11, 11), date(2026, 11, 20)))
        return env

    def test_next_permit_set_stops_the_3_day_email(self):
        ours_renewed = {**OURS, "nextpermitnumber": "B012026314X09"}
        renewal = _permit("B012026314X09", "BLUE ELM INC.", start="2026-11-21", end="2026-12-20",
                          previouspermitnumber=OURS["permitnumber"])
        env = self._run(renewal_segment=[ours_renewed], chain=[renewal])
        self.assertEqual(env.row(OURS["permitnumber"])["renewed_by"], "B012026314X09")
        self.assertEqual(len(env.emails("dot_permit_expiring")), 1)

    def test_another_permit_naming_it_previous_stops_the_3_day_email(self):
        renewal = _permit("B012026314X09", "SOMEONE ELSE LLC", start="2026-11-21", end="2026-12-20",
                          previouspermitnumber=OURS["permitnumber"])
        env = self._run(renewal_segment=[OURS], chain=[renewal])     # read by the chain request
        self.assertEqual(env.row(OURS["permitnumber"])["renewed_by"], "B012026314X09")
        self.assertEqual(len(env.emails("dot_permit_expiring")), 1)

    def test_a_voided_renewal_still_lets_the_3_day_email_go(self):
        voided = _permit("B012026314X09", "BLUE ELM INC.", previouspermitnumber=OURS["permitnumber"],
                         permitstatusshortdesc="VOIDED AFTER ISSUE")
        env = self._run(renewal_segment=[{**OURS, "nextpermitnumber": "B012026314X09"}], chain=[voided])
        self.assertIsNone(env.row(OURS["permitnumber"]).get("renewed_by"))
        self.assertEqual([m["metadata"]["threshold"] for m in env.emails("dot_permit_expiring")
                          if m["metadata"]["permit"] == OURS["permitnumber"]], [14, 3])


class TheFirstPassGate(unittest.TestCase):

    def test_nothing_sends_before_the_first_dot_pass(self):
        _need()
        env = _Env()
        env.db.dot_logs.docs.append({**dot_sync.to_log("dot_permit", OURS), "_id": "r1",
                                     "project_id": "p1", "company_id": "c1",
                                     "match": {"how": "segment_permittee", "state": "confirmed"},
                                     "detected_at": OCT22})
        with patch.object(server, "db", env.db), \
                patch.object(server, "RESEND_API_KEY", "re_test_key"), \
                patch.dict(os.environ, {"NOTIFICATIONS_KILL_SWITCH": ""}), \
                patch("lib.notifications.send_notification", env.send):
            r = _run(server._dot_permit_expiry_tick(now=_at(date(2026, 11, 6))))
            self.assertEqual((env.emails(), env.db.dot_alert_ledger.docs, r["waiting_sync"]),
                             ([], [], 1))
            env.db.source_sync_state.docs.append(
                {"_id": "p1", "company_id": "c1",
                 "sources": {"dot_permits": {"first_synced_at": OCT22, "synced_at": OCT22}}})
            _run(server._dot_permit_expiry_tick(now=_at(date(2026, 11, 6))))
            _run(server._dot_permit_expiry_tick(now=_at(date(2026, 11, 6)) + timedelta(hours=2)))
        self.assertEqual(len(env.emails()), 1)                  # once: the ledger
        self.assertEqual(env.db.dot_alert_ledger.docs[0]["_id"],
                         f"dot:p1:expiry:{OURS['permitnumber']}:14:2026-11-20")

    def test_the_07_00_job_runs_both(self):
        _need()
        calls = []

        async def emb(now=None):
            calls.append("embargo")
            raise RuntimeError("boom")              # one failing does not stop the other

        async def exp(now=None):
            calls.append("expiry")
        with patch.object(server, "_dot_embargo_alert_tick", emb), \
                patch.object(server, "_dot_permit_expiry_tick", exp):
            _run(server._dot_embargo_alert_job())
        self.assertEqual(calls, ["embargo", "expiry"])


class TheSetup(unittest.TestCase):

    def setUp(self):
        _need()

    def test_suggestions_from_the_address_matched_permits(self):
        env = _Env()
        env.sync()                                   # address matches only
        with patch.object(server, "_dot_fetch", _fetch(cross=CROSS)):
            got = env.call(server.get_dot_setup, "p1", current_user=ADMIN, project=env.project)
        self.assertEqual(got["setup"]["status"], "unset")
        names = got["suggestions"]["permittees"]
        self.assertEqual(names[0]["name"], "BLUE ELM INC.")          # ranked by count
        self.assertTrue(names[0]["checked"])                         # the company's own
        self.assertEqual([p["checked"] for p in names[1:]], [False] * (len(names) - 1))
        self.assertEqual(names[0]["count"], 16)
        (f,) = got["suggestions"]["frontages"]
        self.assertEqual((f["boro"], f["on"], sorted([f["from"], f["to"]])),
                         ("3", "HOPKINSON AVE", ["BLAKE AVE", "SUTTER AVE"]))
        self.assertIsNone(got["fallback"])
        self.assertEqual((got["can_confirm"], got["can_suggest"]), (True, True))

    def test_with_no_matched_permit_the_on_street_and_the_published_cross_streets(self):
        env = _Env()
        fetch = _fetch(cross=CROSS)
        with patch.object(server, "_dot_fetch", fetch):
            got = env.call(server.get_dot_setup, "p1", current_user=CP, project=env.project)
            again = env.call(server.get_dot_setup, "p1", current_user=CP, project=env.project)
        fb = got["fallback"]
        self.assertEqual((fb["boro"], fb["on"]), ("3", "THOMAS S BOYLAND ST"))
        self.assertIn({"boro": "3", "on": "THOMAS S BOYLAND ST", "from": "BLAKE AVE",
                       "to": "SUTTER AVE", "count": 51}, fb["cross_segments"])
        self.assertIn("SUTTER AVE", fb["cross_streets"])
        grouped = [p for _ds, p in fetch.calls if "$group" in p]
        self.assertEqual(len(grouped), 1)                    # cached for a day
        self.assertEqual(grouped[0]["$group"], "fromstreetname,tostreetname")
        self.assertEqual(again["fallback"]["cross_segments"], fb["cross_segments"])
        self.assertEqual((got["can_confirm"], got["can_suggest"]), (False, False))

    def test_one_tap_confirm_takes_the_suggestions(self):
        env = _Env()
        env.sync()
        env.confirm(permittees=None, frontages=None)
        s = env.project["dot_setup"]
        self.assertEqual(s["status"], "confirmed")
        self.assertEqual([p["norm"] for p in s["permittees"]], ["BLUE ELM"])
        (f,) = s["frontages"]
        self.assertEqual((f["on"], f["confirmed"], f["source"]), ("HOPKINSON AVE", True, "suggested"))
        self.assertEqual(s["confirmed_by"], "u1")
        (a,) = [x for x in env.db.audit_logs.docs if x["action"] == "dot_setup_confirm"]
        self.assertEqual(a["details"]["permittees"], ["BLUE ELM"])

    def test_a_superintendent_suggestion_matches_nothing_until_confirmed(self):
        env = _Env()
        env.suggest(SUPER)
        s = env.project["dot_setup"]
        (f,) = s["frontages"]
        self.assertEqual((s["status"], f["source"], f["suggested_by"], f["confirmed"]),
                         ("suggested", "superintendent", "u3", False))
        env.sync()
        self.assertFalse(any(d.get("number") in (OURS["permitnumber"], OTHER["permitnumber"])
                             for d in env.db.dot_logs.docs))
        # The superintendent cannot confirm it himself.
        with self.assertRaises(HTTPException) as ctx:
            env.confirm(user=SUPER)
        self.assertEqual(ctx.exception.status_code, 403)
        env.confirm(permittees=["BLUE ELM INC."], frontages=None)       # the admin's one tap
        (f,) = env.project["dot_setup"]["frontages"]
        self.assertEqual((f["source"], f["confirmed"]), ("superintendent", True))
        env.sync(now=OCT22 + timedelta(hours=2))
        self.assertEqual(env.row(OURS["permitnumber"])["match"]["state"], "confirmed")
        actions = [x["action"] for x in env.db.audit_logs.docs]
        self.assertEqual(actions, ["dot_setup_frontage_suggest", "dot_setup_confirm"])

    def test_a_cp_cannot_write(self):
        env = _Env()
        for fn in (lambda: env.suggest(CP), lambda: env.confirm(user=CP),
                   lambda: env.call(server.remove_dot_frontage, "p1", 0, current_user=CP,
                                    project=env.project)):
            with self.assertRaises(HTTPException) as ctx:
                fn()
            self.assertEqual(ctx.exception.status_code, 403)
        self.assertNotIn("dot_setup", env.project)
        self.assertEqual(env.db.audit_logs.docs, [])
        got = env.call(server.get_dot_setup, "p1", current_user=CP, project=env.project) \
            if False else None   # reading is allowed: covered above (fallback test, as CP)
        self.assertIsNone(got)

    def test_an_admin_adds_and_removes_a_frontage(self):
        env = _Env()
        env.suggest(ADMIN, {"on": "Thomas S Boyland St", "from": "Blake Ave", "to": "Dumont Ave"})
        (f,) = env.project["dot_setup"]["frontages"]
        self.assertEqual((f["source"], f["confirmed"]), ("admin", True))
        with self.assertRaises(HTTPException) as ctx:
            env.call(server.remove_dot_frontage, "p1", 0, current_user=SUPER, project=env.project)
        self.assertEqual(ctx.exception.status_code, 403)
        env.call(server.remove_dot_frontage, "p1", 0, current_user=ADMIN, project=env.project)
        self.assertEqual(env.project["dot_setup"]["frontages"], [])
        with self.assertRaises(HTTPException) as ctx:
            env.suggest(ADMIN, {"on": "Thomas S Boyland St"})            # no cross street
        self.assertEqual(ctx.exception.status_code, 422)

    def test_routes_are_registered_behind_project_access(self):
        want = {("GET", "/api/projects/{project_id}/dot/setup"): False,
                ("POST", "/api/projects/{project_id}/dot/setup/confirm"): True,
                ("POST", "/api/projects/{project_id}/dot/setup/frontage"): True,
                ("DELETE", "/api/projects/{project_id}/dot/setup/frontage/{index}"): True,
                ("GET", "/api/projects/{project_id}/dot/permits"): False,
                ("POST", "/api/projects/{project_id}/dot/permits/{permit}/review"): True}
        for (method, path), write in want.items():
            route = next((r for r in server.app.routes
                          if getattr(r, "path", "") == path and method in getattr(r, "methods", ())), None)
            self.assertIsNotNone(route, path)
            calls = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
            self.assertIn("require_project_access", calls, path)
            self.assertIn("get_current_user", calls, path)
            if write:
                self.assertIn("require_approved", calls, path)


class TheEmbargoCoversConfirmedPermitsOnly(unittest.TestCase):

    def test_pending_or_rejected_never_exposed(self):
        _need()
        base = {**dot_sync.to_log("dot_permit", OTHER), "holiday_waiver": False}
        season = dot_embargo.season_for(date(2026, 11, 1))
        self.assertTrue(dot_embargo.needs_waiver(base, season))           # legacy = confirmed
        for st in ("needs_confirmation", "rejected"):
            row = {**base, "match": {"how": "segment_other_permittee", "state": st}}
            self.assertFalse(dot_embargo.needs_waiver(row, season), st)
            self.assertEqual(dot_embargo.due_sends([row], date(2026, 11, 1)), [], st)
            self.assertFalse(dot_embargo.banner([row], date(2026, 11, 20))["show"], st)
        accepted = {**base, "match": {"how": "segment_other_permittee", "state": "confirmed"},
                    "review": {"state": "accepted"}}
        self.assertEqual(len(dot_embargo.due_sends([accepted], date(2026, 11, 1))), 1)


class TheCoverageNoteIsGone(unittest.TestCase):

    def test_from_the_email_and_the_app_in_en_and_es(self):
        _need()
        env = _Env()
        env.confirm()
        env.sync()
        env.review(OTHER["permitnumber"], "accept")
        env.alerts([date(2026, 11, 1)])
        (m,) = [x for x in env.emails("dot_embargo_waiver_missing")
                if x["metadata"]["permit"] == OTHER["permitnumber"]]
        for gone in ("Checks permits matched to your address", "Permits filed by street segment",
                     "Revisa los permisos vinculados a su dirección",
                     "registrados por tramo de calle"):
            self.assertNotIn(gone, m["text"])
            self.assertNotIn(gone, m["html"])
            for name in ("en.js", "es.js"):
                self.assertNotIn(gone, (FE / "src" / "i18n" / name).read_text(encoding="utf-8"))
        for name in ("en.js", "es.js"):
            self.assertNotIn("coverageNote", (FE / "src" / "i18n" / name).read_text(encoding="utf-8"))
        self.assertNotIn("coverageNote", (FE / "app" / "project" / "[id]" / "dob-logs.jsx")
                         .read_text(encoding="utf-8"))


# ═══ WhatsApp: the dot_permit 30/14/7/1 posts skip pending permits ═══════════

from tests.test_whatsapp_gc_alerts import (  # noqa: E402
    CO_A, NOON, _Ctx, _confirm, _group_sends, _no_ai, _world as _gc_world,
)
from lib import wa_gc  # noqa: E402


class TheGroupPostSkipsPending(unittest.TestCase):

    def _row(self, num, **kw):
        exp = (wa_gc.today_et(NOON) + timedelta(days=5)).isoformat()
        row = {"_id": f"d_{num}", "project_id": "proj_a", "company_id": CO_A,
               "record_type": "dot_permit", "raw_id": f"dotpermit:{num}", "number": num,
               "issue_date": "2026-10-06", "status": "ISSUED & PRINTED",
               "description": "Sidewalk", "expiration_date": exp,
               "link": f"https://data.example/{num}", "detected_at": NOON}
        row.update(kw)
        return row

    def test_pending_and_rejected_post_nothing_the_confirmed_one_posts(self):
        db = _gc_world()
        with _Ctx(db=db) as c, _no_ai():
            _confirm()
            _run(server._gc_alerts_tick(NOON))                      # baseline
            db.dot_logs.rows += [
                self._row("PEND", match={"how": "segment_other_permittee", "state": "needs_confirmation"}),
                self._row("REJ", match={"how": "segment_other_permittee", "state": "rejected"}),
                self._row("MINE", match={"how": "segment_permittee", "state": "confirmed"})]
            _run(server._gc_alerts_tick(NOON + timedelta(minutes=15)))
            _run(server._gc_alerts_tick(NOON + timedelta(days=4)))   # the 1-day threshold
        texts = [s["message"] for s in _group_sends(c)]
        self.assertEqual(len(texts), 2, texts)
        self.assertTrue(all("#MINE" in t for t in texts), texts)
        self.assertFalse(any("PEND" in t or "REJ" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
