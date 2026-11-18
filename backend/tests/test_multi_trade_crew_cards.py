"""One company, several trades: the crew card reaches all of them, and every
saved activity row says which catalog trade its work belongs to.

THE REPORT (operator, 2026-11-18): "since theres one company doing multiple
stuff {painting sheetrock taping compound framing etc} when i look on the cards
to add sheetrock or stuff like that its nowhere to be added".

WHY IT WAS NOWHERE. A crew card is one (company, trade) of who checked in, and a
worker holds ONE trade per project (worker_project_trades is unique on worker +
project; the headcount depends on that, so it stays). The card fetched the
chips of that one trade, and composeChipBands made every other trade's chip
unreachable from it. The type-ahead fallback searched the UNFILTERED list,
which is the 83 sequence-graph nodes only -- "hang board", "skim coat",
"prime", "first coat" are taxonomy nodes and were in it for no query at all,
and "sheetrock" / "compound" matched no label anywhere.

WHAT THIS PINS:
  * GET activity-chips?trade=&company= adds the company's OTHER rostered trades
    (trade_assignments rows for that company) to the catalog band, after the
    card's own trade; without `company` the response is what it was.
  * catalog=true carries every catalog trade's activities for "More work".
  * the save path stamps `work_trades` on every daily_jobsite activity row,
    server-side, whatever the client sent.

    cd backend && python -m pytest tests/test_multi_trade_crew_cards.py -q
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from app.scheduling import trade_taxonomy_v1 as T  # noqa: E402

COMPANY = "Acme Interiors"
PROJECT = {
    "_id": "proj1", "company_id": "co_a",
    "trade_assignments": [
        {"id": "ta1", "trade": "Framing", "company": COMPANY},
        # A second row for the same company, spelled the way a person types it.
        {"id": "ta2", "trade": "Drywall", "company": "  acme interiors "},
        {"id": "ta3", "trade": "Painting", "company": COMPANY},
        {"id": "ta4", "trade": "Electrical", "company": "Power Direct"},
    ],
}


class _Coll:
    def __init__(self, one=None):
        self._one = one

    async def find_one(self, *a, **k):
        return self._one

    def find(self, *a, **k):
        return self

    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def to_list(self, *a, **k):
        return []

    async def update_one(self, *a, **k):
        return MagicMock(matched_count=1)


class _Db:
    def __init__(self, project):
        self._c = {"projects": _Coll(project), "logbooks": _Coll(None)}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._c.setdefault(n, _Coll(None))

    def __getitem__(self, n):
        return self.__getattr__(n)


def _get(query, project=PROJECT):
    async def _user():
        return {"_id": "u1", "id": "u1", "role": "cp", "company_id": "co_a",
                "account_status": "approved", "full_name": "Carl CP",
                "assigned_projects": ["proj1"]}

    server.app.dependency_overrides[server.get_current_user] = _user
    try:
        with patch.object(server, "db", _Db(project)):
            r = TestClient(server.app).get(
                "/api/projects/proj1/activity-chips", params=query)
    finally:
        server.app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    return r.json()


def _ids(body, band=None):
    return [c["id"] for c in body["chips"] if band is None or c["band"] == band]


class TheCardReachesEveryTradeItsCompanyIsRosteredFor(unittest.TestCase):

    def test_a_framing_crew_of_a_multi_trade_company_is_offered_sheetrock_taping_and_paint(self):
        body = _get({"date": "2026-11-18", "trade": "Framing", "company": COMPANY})
        ids = _ids(body)
        for wanted in ("dry_hang_board", "taping", "dry_skim_coat", "paint_prime", "paint_finish_coat",
                       "interior_framing", "wood_wall_framing"):
            self.assertIn(wanted, ids, wanted)
        # Not another company's trade.
        self.assertNotIn("elec_pull_wire", ids)
        self.assertEqual(body["company_trades"],
                         ["Interior framing", "Wood framing", "Drywall", "Painting"])

    def test_the_cards_own_trade_comes_first(self):
        body = _get({"date": "2026-11-18", "trade": "Framing", "company": COMPANY})
        own = T.node_ids_for_trades(["Interior framing", "Wood framing"])
        catalog = _ids(body, "catalog")
        first_extra = next(i for i, c in enumerate(catalog) if c not in own)
        self.assertTrue(all(c not in own for c in catalog[first_extra:]),
                        "a company-trade chip sorted in among the card's own trade")
        self.assertTrue(all(c in own for c in _ids(body, "suggested")),
                        "the suggested band is the card's own trade only")

    def test_each_chip_says_which_catalog_trade_its_work_counts_toward(self):
        body = _get({"date": "2026-11-18", "trade": "Framing", "company": COMPANY})
        by_id = {c["id"]: c for c in body["chips"]}
        self.assertEqual(by_id["taping"]["work_trade"], "Drywall")
        self.assertEqual(by_id["paint_prime"]["work_trade"], "Painting")
        self.assertEqual(by_id["interior_framing"]["work_trade"], "Interior framing")
        # blocking is claimed by Wood framing, Carpentry (rough) and Interior
        # framing: on this card it is the card's own first-resolved claimant.
        self.assertEqual(by_id["blocking"]["work_trade"], "Interior framing")
        self.assertIn("Carpentry (rough)", by_id["blocking"]["catalog_trades"])
        self.assertEqual(by_id["other"]["catalog_trades"], [])

    def test_without_a_company_the_card_is_exactly_what_it_was(self):
        before = _get({"date": "2026-11-18", "trade": "Framing"})
        self.assertNotIn("taping", _ids(before))
        self.assertEqual(before["company_trades"], [])

    def test_a_company_with_no_roster_rows_adds_nothing(self):
        a = _get({"date": "2026-11-18", "trade": "Framing", "company": "Nobody LLC"})
        b = _get({"date": "2026-11-18", "trade": "Framing"})
        self.assertEqual(_ids(a), _ids(b))

    def test_a_crew_whose_trade_resolves_to_nothing_gets_its_companys_trades(self):
        body = _get({"date": "2026-11-18", "trade": "Laborer", "company": COMPANY})
        ids = _ids(body)
        self.assertIn("taping", ids)
        self.assertNotIn("elec_pull_wire", ids, "fell back to the unfiltered catalogue")


class MoreWorkReachesAnyCatalogTrade(unittest.TestCase):

    def test_catalog_true_carries_every_trade_and_its_activities(self):
        body = _get({"date": "2026-11-18", "trade": "Framing", "catalog": "true"})
        cat = {g["trade"]: g for g in body["trade_catalog"]}
        self.assertEqual(list(cat), list(T.TRADES))
        drywall = [a["id"] for a in cat["Drywall"]["activities"]]
        self.assertIn("dry_spackle_compound", drywall)
        self.assertIn("sheetrock", cat["Drywall"]["aliases"])
        self.assertIn("masilla", cat["Drywall"]["aliases"])
        self.assertIn("metal stud framing",
                      [a["label"] for a in cat["Interior framing"]["activities"]])

    def test_without_catalog_the_response_does_not_carry_it(self):
        self.assertNotIn("trade_catalog", _get({"trade": "Framing"}))


class TheVocabulary(unittest.TestCase):

    def test_drywall_words_resolve(self):
        for w in ("Sheetrock", "sheet rock", "Taping", "Taper", "Tapers", "tape",
                  "Spackle", "Compound", "Plaster"):
            with self.subTest(w=w):
                self.assertEqual(T.trades_for_roster(w), ["Drywall"])

    def test_framing_words_resolve(self):
        self.assertEqual(T.trades_for_roster("Metal stud"), ["Interior framing"])
        self.assertEqual(T.trades_for_roster("Metal studs"), ["Interior framing"])
        self.assertEqual(T.trades_for_roster("Metal framing"),
                         ["Interior framing", "CFS (cold-formed steel)"])
        self.assertEqual(T.trades_for_roster("Wood framing"), ["Wood framing"])

    def test_a_joined_roster_string_claims_every_trade(self):
        self.assertEqual(T.trades_for_roster("Sheetrock / Taping / Painting"),
                         ["Drywall", "Painting"])

    def test_the_new_activities_exist_once_and_have_no_edges(self):
        from app.scheduling.sequence_rules_v1 import build_sequence_rules_v1
        g = build_sequence_rules_v1()
        edged = {e.from_node for e in g.edges} | {e.to_node for e in g.edges}
        for nid, trade in (("dry_spackle_compound", "Drywall"), ("iframe_metal_stud", "Interior framing")):
            with self.subTest(nid=nid):
                self.assertIn(nid, T.TRADES[trade])
                self.assertEqual([n.id for n in T.NEW_NODES].count(nid), 1)
                self.assertNotIn(nid, edged)

    def test_check_in_and_dm_folding_accept_the_words(self):
        from lib import trades as lib_trades
        V = list(server.TRADE_VOCABULARY)
        for said, label in (("sheetrock", "Drywall"), ("spackle", "Drywall"),
                            ("compound", "Drywall"), ("plaster", "Drywall"),
                            ("tape", "Drywall"), ("masilla", "Drywall"),
                            ("metal stud", "Framing"), ("metal framing", "Framing"),
                            ("wood framing", "Framing"), ("painting", "Painting")):
            with self.subTest(said=said):
                self.assertEqual(lib_trades.resolve(said, V), label)

    def test_no_published_trade_was_split_or_renamed(self):
        self.assertNotIn("Sheetrock", server.TRADE_VOCABULARY)
        self.assertNotIn("Taping", server.TRADE_VOCABULARY)


# ── work_trades on the save path ─────────────────────────────────────────────

def _rows(data):
    return data["activities"]


def _row(**k):
    base = {"company": COMPANY, "trade": "Framing", "num_workers": "4",
            "activity_ids": [], "work_description": ""}
    base.update(k)
    return base


class TheDerivation(unittest.TestCase):
    """trade_taxonomy_v1.derive_work_trades -- the one rule both sides run."""

    def test_distinct_in_chip_order(self):
        got = T.derive_work_trades(["taping", "paint_prime", "dry_sand", "interior_framing"],
                                   ["Interior framing", "Wood framing"])
        self.assertEqual(got, ["Drywall", "Painting", "Interior framing"])

    def test_free_text_only_is_the_cards_own_trade(self):
        self.assertEqual(T.derive_work_trades(["other:hung doors"], [], ["Interior framing"]),
                         ["Interior framing"])

    def test_nothing_selected_is_no_work_trade(self):
        self.assertEqual(T.derive_work_trades([], [], ["Interior framing"]), [])

    def test_a_shared_node_goes_to_the_first_claimant_in_context(self):
        self.assertEqual(T.derive_work_trades(["patching"], ["Drywall"]), ["Drywall"])
        self.assertEqual(T.derive_work_trades(["patching"], []), ["Foundation / Concrete"])

    def test_garbage_never_raises(self):
        for junk in (None, "taping", 7, [None, 3, ""], {"a": 1}):
            with self.subTest(junk=junk):
                self.assertIsInstance(T.derive_work_trades(junk, junk, junk), list)


class TheServerStampsWorkTradesOnSave(unittest.TestCase):

    def test_create_stamps_every_row_even_when_the_client_sent_none(self):
        data = {"activities": [
            _row(activity_ids=["interior_framing", "taping", "paint_prime"]),
            _row(activity_ids=["other:moved material"]),
            _row(activity_ids=[]),
            _row(company="Power Direct", trade="Electrician", activity_ids=["mep_rough_in"]),
        ]}
        captured = {}

        async def insert_one(doc, *a, **k):
            captured["doc"] = doc
            return MagicMock(inserted_id="lb_new")

        db = MagicMock()
        db.projects.find_one = AsyncMock(return_value=dict(PROJECT))
        db.logbooks.find_one = AsyncMock(return_value=None)
        db.logbooks.count_documents = AsyncMock(return_value=0)
        db.logbooks.insert_one = AsyncMock(side_effect=insert_one)
        db.logbooks.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        payload = server.LogbookCreate(project_id="proj1", log_type="daily_jobsite",
                                       date="2026-11-18", data=data, status="draft")
        cp = {"_id": "u1", "id": "u1", "role": "cp", "company_id": "co_a",
              "account_status": "approved", "assigned_projects": ["proj1"]}

        async def _noop(*a, **k):
            return None

        with patch.object(server, "db", db), \
                patch.object(server, "to_query_id", lambda v: v), \
                patch.object(server, "_enhance_logbook_photos", _noop), \
                patch.object(server, "_remember_other_activities", _noop), \
                patch.object(server, "_remember_other_locations", _noop), \
                patch.object(server, "audit_log", _noop):
            asyncio.run(server.create_logbook(payload, cp))
        stored = captured.get("doc")
        if stored is None:  # the upsert path
            (_q, upd), _k = db.logbooks.update_one.call_args
            stored = {"data": (upd.get("$set") or {}).get("data")}
        rows = _rows(stored["data"])
        self.assertEqual([r["work_trades"] for r in rows], [
            ["Interior framing", "Drywall", "Painting"],
            ["Interior framing", "Wood framing"],
            [],
            ["Electrical"],
        ])
        self.assertNotIn("work_trades", data["activities"][0],
                         "the caller's payload was mutated")

    def _update(self, stored, data):
        captured = {}

        async def update_one(q, upd, *a, **k):
            captured["set"] = upd.get("$set", {})
            return MagicMock(matched_count=1)

        db = MagicMock()
        db.logbooks.find_one = AsyncMock(return_value=dict(stored))
        db.logbooks.update_one = AsyncMock(side_effect=update_one)
        db.projects.find_one = AsyncMock(return_value=dict(PROJECT))
        admin = {"_id": "u9", "id": "u9", "role": "admin", "company_id": "co_a",
                 "account_status": "approved", "assigned_projects": ["proj1"]}
        with patch.object(server, "db", db), \
                patch.object(server, "audit_log", AsyncMock()), \
                patch.object(server, "_remember_other_activities", AsyncMock()), \
                patch.object(server, "_remember_other_locations", AsyncMock()):
            asyncio.run(server.update_logbook(
                logbook_id="lb1", data=server.LogbookUpdate(data=data), current_user=admin))
        return captured["set"]

    DRAFT = {"_id": "lb1", "project_id": "proj1", "company_id": "co_a",
             "log_type": "daily_jobsite", "date": "2026-11-18", "status": "draft",
             "is_locked": False, "data": {"activities": []}}

    def test_update_overrides_a_wrong_or_foreign_client_value(self):
        s = self._update(self.DRAFT, {"activities": [
            _row(activity_ids=["taping"], work_trades=["Electrical", "Not A Trade"]),
        ]})
        self.assertEqual(s["data"]["activities"][0]["work_trades"], ["Drywall"])

    def test_the_clients_value_decides_a_shared_node(self):
        # patching: Foundation / Concrete and Drywall both claim it. A Framing
        # card has neither as its own trade; the company is rostered for
        # Drywall, so Drywall -- and a client that saw it picked under Drywall
        # agrees.
        s = self._update(self.DRAFT, {"activities": [
            _row(activity_ids=["patching"], work_trades=["Drywall"])]})
        self.assertEqual(s["data"]["activities"][0]["work_trades"], ["Drywall"])

    def test_a_non_daily_log_is_left_alone(self):
        other = dict(self.DRAFT, log_type="toolbox_talk")
        s = self._update(other, {"activities": [_row(activity_ids=["taping"])]})
        self.assertNotIn("work_trades", s["data"]["activities"][0])

    def test_work_trades_appearing_is_not_new_content_on_a_signed_draft(self):
        affirmed = {"paths": "p", "affirmed": True, "affirmedAt": "2026-11-18T12:00:00Z"}
        acts = [_row(activity_ids=["taping"])]
        stored = dict(self.DRAFT, cp_signature=affirmed, data={"activities": acts})
        s = self._update(stored, {"activities": [dict(a) for a in acts]})
        self.assertNotIn("cp_signature", s, "a re-save that only gained work_trades un-affirmed the mark")


if __name__ == "__main__":
    unittest.main()
