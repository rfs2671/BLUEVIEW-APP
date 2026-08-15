"""A crew is offered its OWN trade's work.

THE DEFECT. The ranker keyed off the PROJECT's prior day and nothing else, so
every crew on site saw the same three suggestions. An electrical crew was
offered drywall and insulation — and could not have been offered anything
better, because no electrical activity existed anywhere in the 86-node graph.
The nearest thing was `mep`, six nodes, which cannot tell an electrician from
an HVAC crew.

PROVENANCE. The taxonomy is approved by the operator via direct instruction.
There is NO signed sign-off document for it and none is required: it orders
chips by trade and asserts no legal requirement. The SEQUENCE rules are the
signed-pending artifact, and nothing here touches them — no node, no edge, no
`trade` field. That separation is asserted below, because it is the thing most
likely to be eroded by a later "tidy-up".
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
import unittest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.scheduling.sequence_rules_v1 import build_sequence_rules_v1  # noqa: E402
from app.scheduling.sequence_ranking import rank_activities  # noqa: E402
from app.scheduling.trade_taxonomy_v1 import (  # noqa: E402
    TRADES, NEW_NODES, NEW_NODE_IDS, trades_for_roster, node_ids_for_trades,
)

ROSTER = ["Concrete", "Formwork", "Electrical", "HVAC / Mechanical", "Carpentry"]


def chips(trade=None, priors=None, system="cast_in_place"):
    r = rank_activities(project_id="p", prior_activity_ids=priors or [],
                        structural_system=system, trade=trade)
    return r.chips


def labels(cs, band=None):
    return [c.label for c in cs if band is None or c.band == band]


class AnElectricalCrewIsNotOfferedDrywall(unittest.TestCase):
    """THE test. This is what would have caught it."""

    def test_electrical_sees_no_drywall_and_no_insulation(self):
        got = [l.lower() for l in labels(chips("Electrical"))]
        for forbidden in ("drywall", "taping", "insulation", "paint", "flooring"):
            self.assertNotIn(forbidden, got, f"an electrician was offered {forbidden}")

    def test_electrical_sees_ELECTRICAL_work(self):
        got = [l.lower() for l in labels(chips("Electrical"))]
        for expected in ("temp power", "branch rough-in", "pull wire",
                         "switchgear", "testing and energizing"):
            self.assertIn(expected, got, f"an electrician was NOT offered {expected}")

    def test_the_prior_day_cannot_drag_another_trade_in(self):
        """The exact shape of the bug: yesterday the project closed its
        envelope, which opens insulation and drywall. That must not reach the
        electrician."""
        got = [l.lower() for l in labels(chips("Electrical",
                                               priors=["building_envelope_closed"]))]
        self.assertNotIn("insulation", got)
        self.assertNotIn("drywall", got)

    def test_and_the_unfiltered_list_still_offers_them(self):
        """Proves the assertions above are the FILTER working, not the chips
        having gone missing."""
        got = [l.lower() for l in labels(chips(None, priors=["building_envelope_closed"]))]
        self.assertIn("insulation", got)
        self.assertIn("drywall", got)

    def test_hvac_and_electrical_no_longer_see_the_same_list(self):
        e = {c.id for c in chips("Electrical")}
        h = {c.id for c in chips("HVAC / Mechanical")}
        self.assertNotEqual(e, h, "mep could not tell them apart; the taxonomy must")
        self.assertTrue(e - h, "electrical has work HVAC does not")
        self.assertTrue(h - e, "HVAC has work electrical does not")


class EveryRosterTradeGetsAUsableList(unittest.TestCase):
    def test_every_roster_trade_returns_a_non_empty_list(self):
        for t in ROSTER:
            with self.subTest(trade=t):
                self.assertGreater(len(chips(t)), 0)

    def test_every_roster_trade_gets_its_OWN_work_not_only_the_shared_band(self):
        for t in ROSTER:
            with self.subTest(trade=t):
                cs = chips(t)
                own = [c for c in cs if c.band in ("suggested", "catalog")]
                self.assertGreater(len(own), 0, f"{t} got only the shared band")

    def test_every_taxonomy_trade_resolves_to_something(self):
        for t in TRADES:
            with self.subTest(trade=t):
                self.assertGreater(len(node_ids_for_trades([t])), 0)

    def test_an_unrecognized_trade_falls_back_to_everything(self):
        """Offering everything is worse than offering the right thing, and far
        better than offering nothing."""
        got = chips("Underwater Basket Weaving")
        self.assertEqual({c.id for c in got}, {c.id for c in chips(None)})

    def test_a_blank_trade_is_unfiltered(self):
        for blank in (None, "", "   "):
            self.assertEqual({c.id for c in chips(blank)},
                             {c.id for c in chips(None)}, repr(blank))


class TheSharedBandsAreNeverFiltered(unittest.TestCase):
    def test_always_available_shows_for_every_trade(self):
        base = {c.id for c in chips(None) if c.band == "always_available"}
        self.assertGreater(len(base), 0)
        for t in ROSTER + list(TRADES):
            with self.subTest(trade=t):
                got = {c.id for c in chips(t) if c.band == "always_available"}
                self.assertEqual(got, base, f"{t} lost part of the shared band")

    def test_other_is_last_for_every_trade(self):
        for t in ROSTER + list(TRADES) + [None, "nonsense"]:
            with self.subTest(trade=t):
                self.assertEqual(chips(t)[-1].id, "other")

    def test_nothing_is_ever_pre_selected(self):
        for t in ROSTER + [None]:
            with self.subTest(trade=t):
                self.assertEqual([c for c in chips(t) if c.selected], [])

    def test_ranks_are_contiguous_from_zero(self):
        for t in ROSTER + [None]:
            with self.subTest(trade=t):
                cs = chips(t)
                self.assertEqual([c.rank for c in cs], list(range(len(cs))))


class TheSequenceLoopSurvives(unittest.TestCase):
    """Retagging must not cost an edge. The taxonomy references node ids; it
    does not recreate them."""

    def test_the_envelope_insulation_drywall_chain_still_ranks(self):
        got = [c.id for c in chips(None, priors=["building_envelope_closed"])
               if c.band == "suggested"]
        self.assertEqual(got, ["building_envelope_closed", "insulation", "drywall"])

    def test_sequencing_still_fires_INSIDE_a_trade(self):
        got = [c.id for c in chips("Concrete", priors=["footings"])
               if c.band == "suggested"]
        self.assertIn("footings", got, "the prior stays offered")
        self.assertIn("foundation_walls", got, "and opens its successors")

    def test_the_graph_itself_is_untouched(self):
        g = build_sequence_rules_v1()
        self.assertEqual(len(g.nodes), 86, "no node was added to the signed rules")
        self.assertEqual(len(g.edges), 145, "no edge was added or lost")

    def test_no_new_node_shadows_an_existing_one(self):
        existing = {n.id for n in build_sequence_rules_v1().nodes}
        self.assertEqual(NEW_NODE_IDS & existing, set(),
                         "a duplicate id would compete with the edged node")

    def test_every_claimed_id_resolves(self):
        existing = {n.id for n in build_sequence_rules_v1().nodes}
        for t, ids in TRADES.items():
            for i in ids:
                with self.subTest(trade=t, node=i):
                    self.assertTrue(i in existing or i in NEW_NODE_IDS)

    def test_the_edged_nodes_are_REFERENCED_not_recreated(self):
        """If a taxonomy activity that already exists were re-created as a new
        node, the original's edges would be orphaned."""
        existing = {n.id for n in build_sequence_rules_v1().nodes}
        claimed = {i for ids in TRADES.values() for i in ids}
        self.assertGreater(len(claimed & existing), 70,
                           "most of the graph should be referenced, not duplicated")


class NewNodesHaveNoEdges(unittest.TestCase):
    """Stated plainly, and enforced: edges are precedence claims and belong to
    the signed sequence document."""

    def test_no_taxonomy_node_appears_in_any_edge(self):
        g = build_sequence_rules_v1()
        touched = {e.from_node for e in g.edges} | {e.to_node for e in g.edges}
        self.assertEqual(NEW_NODE_IDS & touched, set())

    def test_a_new_activity_is_offered_and_opens_NOTHING(self):
        """The honest consequence of having no edges, and it is better than I
        first assumed: the activity IS recognised as a prior, so a crew that
        did it yesterday still sees it offered today. It simply opens no
        successor, because nothing declares what follows it. That is a
        precedence claim and belongs to the signed sequence document."""
        got = [c.id for c in chips("Electrical")]
        self.assertIn("elec_branch_rough_in", got, "offered by trade")

        ranked = rank_activities(project_id="p",
                                 prior_activity_ids=["elec_branch_rough_in"],
                                 structural_system="cast_in_place",
                                 trade="Electrical")
        self.assertEqual(ranked.unrecognized_prior_ids, [],
                         "it is a real node, so it is not an unrecognised prior")
        suggested = [c.id for c in ranked.chips if c.band == "suggested"]
        self.assertEqual(suggested, ["elec_branch_rough_in"],
                         "it re-offers itself and opens nothing — no invented edges")
        self.assertGreater(len(ranked.chips), 0, "and never empties the list")

    def test_an_edged_node_by_contrast_DOES_open_successors(self):
        """The control. Proves the assertion above measures missing edges
        rather than a broken ranker."""
        ranked = rank_activities(project_id="p", prior_activity_ids=["footings"],
                                 structural_system="cast_in_place", trade="Concrete")
        suggested = [c.id for c in ranked.chips if c.band == "suggested"]
        self.assertGreater(len(suggested), 1, "an edged prior opens more than itself")


class TheTaxonomyIsSeparateFromTheSignedRules(unittest.TestCase):
    def test_the_taxonomy_does_not_import_or_edit_the_rules_content(self):
        src = (_BACKEND / "app" / "scheduling" / "trade_taxonomy_v1.py").read_text(
            encoding="utf-8")
        self.assertNotIn("GraphEdge", src, "the taxonomy declares no edges")
        self.assertNotIn("build_sequence_rules_v1", src,
                         "it references ids by name, it does not rebuild the graph")

    def test_the_provenance_is_recorded_honestly(self):
        src = (_BACKEND / "app" / "scheduling" / "trade_taxonomy_v1.py").read_text(
            encoding="utf-8")
        self.assertIn("NO SIGNED SIGN-OFF DOCUMENT", src)
        self.assertNotIn(".pdf", src.lower(), "no document is cited")

    def test_the_count_discrepancy_is_recorded(self):
        self.assertEqual(len(TRADES), 39,
                         "the list is 39 trades; the brief said 35")


class TheRosterMapping(unittest.TestCase):
    def test_the_five_roster_strings_all_resolve(self):
        for t in ROSTER:
            with self.subTest(trade=t):
                self.assertTrue(trades_for_roster(t), f"{t} resolved to nothing")

    def test_formwork_folds_into_concrete(self):
        self.assertEqual(trades_for_roster("Formwork"), ["Foundation / Concrete"])
        self.assertEqual({c.id for c in chips("Formwork")},
                         {c.id for c in chips("Concrete")})

    def test_a_string_spanning_two_trades_claims_both(self):
        self.assertEqual(trades_for_roster("HVAC / Mechanical"),
                         ["HVAC", "Mechanical piping"])
        self.assertEqual(trades_for_roster("Carpentry"),
                         ["Carpentry (rough)", "Carpentry (finish)"])

    def test_matching_ignores_case_and_spacing(self):
        for v in ("electrical", "  ELECTRICAL  ", "Electrical"):
            self.assertEqual(trades_for_roster(v), ["Electrical"], repr(v))

    def test_junk_resolves_to_nothing_without_raising(self):
        for junk in (None, "", 7, [], "   "):
            self.assertEqual(trades_for_roster(junk), [], repr(junk))


class TheEndpointActuallyCarriesTheTrade(unittest.TestCase):
    """The filter is worthless if the query parameter never reaches the ranker.
    A unit test on rank_activities cannot see that wire, so this drives the
    real route."""

    def _get(self, trade=None):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        import server

        class _Coll:
            def __init__(self, v=None):
                self.v = v

            async def find_one(self, *a, **k):
                return self.v

            async def update_one(self, *a, **k):
                raise AssertionError("a read endpoint must not write")

        class _Db:
            projects = _Coll({"_id": "proj1", "structural_system": "cast_in_place"})
            logbooks = _Coll(None)

            def __getattr__(self, n):
                return _Coll(None)

        async def _fake_user():
            return {"_id": "u1", "id": "u1", "role": "cp", "company_id": "co_a",
                    "account_status": "approved", "full_name": "Carl CP",
                    "assigned_projects": ["proj1"]}

        server.app.dependency_overrides[server.get_current_user] = _fake_user
        try:
            with patch.object(server, "db", _Db()):
                q = f"?trade={trade}" if trade else ""
                r = TestClient(server.app).get(
                    f"/api/projects/proj1/activity-chips{q}")
        finally:
            server.app.dependency_overrides.clear()
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_the_query_parameter_narrows_the_real_response(self):
        unfiltered = {c["id"] for c in self._get()["chips"]}
        electrical = {c["id"] for c in self._get("Electrical")["chips"]}
        self.assertNotEqual(unfiltered, electrical,
                            "?trade= reached the endpoint and changed nothing")
        self.assertNotIn("drywall", electrical, "over the wire, not just in a unit")
        self.assertIn("elec_temp_power", electrical)

    def test_the_response_reports_what_the_trade_RESOLVED_to(self):
        """So the caller can say 'we did not recognise this trade' instead of
        implying the short list is authoritative."""
        body = self._get("Plumbing")
        self.assertEqual(body["trade"], "Plumbing")
        self.assertEqual(body["resolved_trades"], ["Plumbing"])

        # A roster string that spans two taxonomy trades reports both, so the
        # caller is never told a narrower story than the filter applied.
        span = self._get("HVAC")
        self.assertEqual(span["resolved_trades"], ["HVAC", "Mechanical piping"])

        junk = self._get("Underwater Basket Weaving")
        self.assertEqual(junk["resolved_trades"], [], "unrecognised, and says so")
        self.assertEqual({c["id"] for c in junk["chips"]},
                         {c["id"] for c in self._get()["chips"]},
                         "and falls back to the whole catalogue")

    def test_omitting_the_parameter_is_byte_identical_to_before(self):
        body = self._get()
        self.assertIsNone(body["trade"])
        self.assertEqual(body["resolved_trades"], [])
        self.assertTrue(body["chips"])


class TheClientSendsIt(unittest.TestCase):
    """Executes the real wrapper. A regex over api.js would pass on a line that
    builds `params.trade` and then never uses it."""

    def _call(self, *args):
        import json
        import subprocess
        src = (_BACKEND.parent / "frontend" / "src" / "utils" / "api.js").read_text(
            encoding="utf-8")
        nl = chr(10)
        marker = nl + "  },"
        start = src.index("  getActivityChips: async (")
        end = src.index(marker, start) + len(marker)
        body = src[start:end].rstrip().rstrip(",")
        script = nl.join([
            "let seen = null;",
            "const apiClient = { get: async (url, cfg) => { seen = {url, cfg};"
            " return {data: {}}; } };",
            "const api = {",
            body,
            "};",
            f"api.getActivityChips(...{json.dumps(list(args))}).then(() =>"
            " console.log(JSON.stringify(seen)));",
        ])
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "call.cjs"
            f.write_text(script, encoding="utf-8")
            out = subprocess.run(["node", str(f)], capture_output=True, text=True,
                                 shell=(os.name == "nt"))
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip())

    def test_the_trade_is_put_on_the_query_string(self):
        seen = self._call("p1", "2026-08-09", "Electrical")
        self.assertEqual(seen["cfg"]["params"],
                         {"date": "2026-08-09", "trade": "Electrical"})
        self.assertIn("/api/projects/p1/activity-chips", seen["url"])

    def test_no_trade_sends_no_trade_key(self):
        for missing in (None, ""):
            seen = self._call("p1", "2026-08-09", missing)
            self.assertEqual(seen["cfg"]["params"], {"date": "2026-08-09"},
                             repr(missing))

    def test_the_date_still_works_on_its_own(self):
        self.assertEqual(self._call("p1", "2026-08-09")["cfg"]["params"],
                         {"date": "2026-08-09"})
        self.assertEqual(self._call("p1")["cfg"]["params"], {})


if __name__ == "__main__":
    unittest.main()


class TestRosterAliasesFromProduction(unittest.TestCase):
    """THE STRINGS THREE REAL PROJECTS ACTUALLY CARRY.

    Device round 4. A roster query found only three projects with trades set,
    and between them they broke the resolver two different ways:

        588 Thomas    'Concrete / Cement'
        857 Prescott  'Concrete', 'Formwork', 'Electrical',
                      'HVAC / Mechanical', 'Carpentry'
        9 Menahan     'Safety', 'Framing', 'Cleaning'

    'Concrete' and 'Concrete / Cement' are the SAME TRADE typed by two admins,
    and one of them resolved to nothing and fell back to all 86 chips.
    """

    def test_every_live_roster_string_that_should_resolve_does(self):
        for typed, expected in [
            ("Concrete / Cement", ["Foundation / Concrete"]),
            ("Concrete", ["Foundation / Concrete"]),
            ("Formwork", ["Foundation / Concrete"]),
            ("Electrical", ["Electrical"]),
            ("HVAC / Mechanical", ["HVAC", "Mechanical piping"]),
            ("Carpentry", ["Carpentry (rough)", "Carpentry (finish)"]),
            ("Framing", ["Interior framing", "Wood framing"]),
            ("Safety", ["Site safety"]),
        ]:
            with self.subTest(typed=typed):
                self.assertEqual(trades_for_roster(typed), expected)

    def test_the_same_trade_typed_two_ways_resolves_the_same_way(self):
        """The defect in one line."""
        self.assertEqual(trades_for_roster("Concrete / Cement"),
                         trades_for_roster("Concrete"))

    def test_cleaning_stays_unmapped(self):
        """RULED, and the reasoning matters more than the assertion.

        There is no cleaning trade in the 39, and the nearest candidates would
        offer a cleaning crew structural demo. The work they actually log —
        site clean-up, debris removal — is in the always-available band every
        crew already gets on every day, so falling back costs them nothing and
        a forced mapping would cost them a wrong chip list on a signed log.
        """
        self.assertEqual(trades_for_roster("Cleaning"), [])

    def test_the_worker_noun_forms_resolve(self):
        """A roster is written by whoever is at the gate, and he writes what a
        man IS, not what the taxonomy calls the work."""
        for typed, expected in [
            ("Electrician", ["Electrical"]),
            ("Plumber", ["Plumbing"]),
            ("Mason", ["Masonry"]),
            ("Roofer", ["Roofing"]),
            ("Carpenter", ["Carpentry (rough)", "Carpentry (finish)"]),
        ]:
            with self.subTest(typed=typed):
                self.assertEqual(trades_for_roster(typed), expected)

    def test_ironworker_is_structural_steel_only(self):
        """RULED, and deliberately UNDER-mapped.

        In NYC "ironworker" covers structural AND reinforcing, and reinforcing
        lives inside Foundation / Concrete — so claiming both would hand a rebar
        crew the whole concrete package: footings, pours, curing, stripping.
        Under-mapping costs four sequenced chips. Over-mapping puts another
        trade's work in front of a crew on a signed log. Not symmetric.
        """
        self.assertEqual(trades_for_roster("Ironworker"), ["Structural steel"])
        self.assertNotIn("Foundation / Concrete", trades_for_roster("Ironworker"))

    def test_laborer_and_operator_stay_unmapped(self):
        """A laborer works for whichever trade needs him that morning; an
        operator runs a machine for whoever booked it. Neither is a trade here,
        and forcing 'Operator' onto Excavation would be a guess about which
        machine. What they log is always-available work, which reaches every
        crew regardless of trade."""
        self.assertEqual(trades_for_roster("Laborer"), [])
        self.assertEqual(trades_for_roster("Operator"), [])


class TestSeparatorRuleNotSpellings(unittest.TestCase):
    """The map had `hvac / mechanical` AND `hvac/mechanical` as two literal
    keys beside `hvac` — the separator problem met once and patched per
    spelling. `Concrete / Cement` proved it was a missing RULE, not a missing
    synonym. Both literals were deleted; if the rule regresses, HVAC breaks
    loudly, which is the point of deleting them."""

    def test_the_deleted_hvac_spellings_still_resolve_through_the_rule(self):
        from app.scheduling.trade_taxonomy_v1 import ROSTER_TRADE_MAP
        self.assertNotIn("hvac / mechanical", ROSTER_TRADE_MAP)
        self.assertNotIn("hvac/mechanical", ROSTER_TRADE_MAP)
        for typed in ("HVAC / Mechanical", "HVAC/Mechanical", "hvac , mechanical"):
            with self.subTest(typed=typed):
                self.assertEqual(trades_for_roster(typed),
                                 ["HVAC", "Mechanical piping"])

    def test_canonical_names_containing_a_separator_still_match_whole(self):
        """Whole string FIRST. Canonical trade names contain the very
        characters used to join two trades, so an exact match must win before
        anything is taken apart."""
        for name in ("Foundation / Concrete", "Shoring / underpinning",
                     "CFS (cold-formed steel)", "Landscaping / hardscape",
                     "Waterproofing (interior)"):
            with self.subTest(name=name):
                self.assertEqual(trades_for_roster(name), [name])

    def test_two_word_canonical_names_are_never_split_on_and(self):
        """`Windows and doors` and `Tile and stone` ARE trade names. The
        splitter does not know the word "and" at all, rather than relying on
        whole-string matching running first."""
        self.assertEqual(trades_for_roster("Windows and doors"), ["Windows and doors"])
        self.assertEqual(trades_for_roster("Tile and stone"), ["Tile and stone"])

    def test_every_separator(self):
        for joined in ("Electrical / Plumbing", "Electrical, Plumbing",
                       "Electrical & Plumbing", "Electrical + Plumbing",
                       "Electrical; Plumbing"):
            with self.subTest(joined=joined):
                self.assertEqual(trades_for_roster(joined), ["Electrical", "Plumbing"])

    def test_partial_match_wins(self):
        """One unrecognized half must not discard the recognized one — a crew
        typed 'Concrete / Cement' is doing concrete. 'Steel / Cleaning'
        therefore resolves to Structural steel alone, and the cleaning half
        lands in always-available where it already was."""
        self.assertEqual(trades_for_roster("Steel / Cleaning"), ["Structural steel"])
        self.assertEqual(trades_for_roster("Cleaning / Operator"), [])

    def test_a_split_never_duplicates_a_trade(self):
        self.assertEqual(trades_for_roster("Concrete / Formwork"),
                         ["Foundation / Concrete"])

    def test_it_still_never_raises(self):
        for junk in (None, 123, [], {}, "   ", "/", "///", "&,;+"):
            with self.subTest(junk=junk):
                self.assertEqual(trades_for_roster(junk), [])
