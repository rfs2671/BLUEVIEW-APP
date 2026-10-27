"""DOORS AND WINDOWS: COUNTED BY THEIR TAGS, BOUND BY THE EQUIPMENT'S RULES.

Operator, 2026-10-26: "count door/window tags by type on A plans (A-Door/
A-Glaz layers + tags), reconcile both ways with the door/window schedules
(incl. A-400's elevation-style schedule), per apartment/floor/building, same
binding rules as equipment."

MEASURED ON 588 BOYLAND (bv-worktrees/L2_doors_measure.md):
  - the tags are TEXT inside outlines on *|A-DOOR-IDEN / *|A-WINDOW-IDEN;
    the exterior doors D1/D2 are tagged on the WINDOW layer; wall tags
    (W1..W6, a WALL TAGS diamond) are not tags of windows;
  - every plan's legend prints a "W1 WINDOW TAG" key on the window layer;
  - A-400.00 is elevation-style: "NUMBER <tag>" panels, no identifier
    column, no QTY - its records give no closed set until the heads are read;
  - the owner's set draws its post-CO additions on a layer TO REMOVE, so 1A's
    new door F and closet G took E's bath door as their symbol (one symbol,
    three tags), and its mezzanine draws four bath doors with no tag;
  - filed 2C: B1 F3 G1 W1 2 W2 1, every one by its own symbol; the entrance
    B's tag sits in the doorway, its door swings into 2C.

Rules under test, each the equipment's: located per unit / floor / building;
a printed QTY lends nothing; per drawing track - a set-named claim binds only
that track, an unqualified claim only when the tracks agree; a figure that
cannot be completed refuses; set health names what the set lacks; a lettered
type is never named by the article "a".
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402
from lib import plan_emit as E  # noqa: E402
from lib import plan_search as S  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

PID = "p1"
INT, EXT, WIN = "INTERIOR DOOR SCHEDULE", "EXTERIOR DOOR SCHEDULE", "WINDOW SCHEDULE"
TAGS = {INT: list("ABCDEFG"), EXT: ["D1", "D2"], WIN: ["W1", "W2", "W3"]}
LABEL = "the owner's post-CO set, 6/9/26"

#: A-400.00's three schedule records as production holds them (read-only
#: probe 2026-10-26, company BLUEVIEW CONSTRUCTION INC): transposed panels.
A400 = [
    {"name": WIN, "tier": "schedule_cell", "sheet_number": "A-400.00",
     "columns": [{"header": "W1 NUMBER", "role": None}, {"header": "", "role": None},
                 {"header": "W2 NUMBER", "role": None}, {"header": "", "role": None},
                 {"header": "W3 NUMBER", "role": None}, {"header": "", "role": None}],
     "rows": [["TYPE", "CASMENT", "TYPE", "CASMENT", "TYPE", "DOUBLE HUNG"],
              ["LOCATION", "REFER TO PLAN", "LOCATION", "REFER TO PLAN", "LOCATION", "REFER TO PLAN"]]},
    {"name": INT, "tier": "schedule_cell", "sheet_number": "A-400.00",
     "columns": [{"header": h, "role": None} for h in
                 ("NUMBER A", "", "NUMBER B", "", "NUMBER C", "", "NUMBER D", "", "NUMBER E", "")],
     "rows": [["STAIRS EXIT DOOR", "", "APARTMENT ENTRANCE", "", "STORAGE AND MECHANICAL RM.", "",
               "INSULATED METAL SELF CLOSING", "", "INTERIOR ADA DOOR", ""],
              ["SIZE", "3'-0\" X 7'-0\"", "SIZE", "3'-0\" X 7'-0\"", "SIZE", "3'-0\" X 7'-0\"",
               "SIZE", "3'-0\" X 7'-0\"", "SIZE", "3'-0\" X 6'-8\""],
              ["", "", "", "", "", "", "NUMBER F", "", "NUMBER G", ""]]},
    {"name": EXT, "tier": "schedule_cell", "sheet_number": "A-400.00",
     "columns": [{"header": "D1 NUMBER", "role": None}, {"header": "", "role": None},
                 {"header": "D2 NUMBER", "role": None}, {"header": "", "role": None}],
     "rows": [["TYPE", "INSWING", "TYPE", "INSWING"], ["LOCATION", "ENTRANCE", "LOCATION", "ENTRANCE"]]},
]


def _present():
    """On a tree without the doors-and-windows pass this is the failure -
    an assertion, never an ImportError."""
    assert importlib.util.find_spec("lib.plan_openings") is not None, \
        "no lib.plan_openings: door and window tags are not read in this tree"
    assert hasattr(S, "opening_books") and hasattr(S, "render_opening_evidence"), \
        "the count gate has no door/window books in this tree"


def _P():
    _present()
    from lib import plan_openings
    return plan_openings


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


# ── rows, by the real emitter, as run_openings writes them ────────────────

FLOORS = {"101": ("SECOND FLOOR PLAN", ["2A", "2B", "2C", "2D"]),
          "100": ("FIRST FLOOR PLAN", ["1A", "1B", "1C", "1D"]),
          "103": ("FOURTH FLOOR PLAN", ["4A"]),
          "104": ("MEZZANINE PLAN", ["4A"])}


def _rows(track, level, family, placed, multi=None, unread=0):
    """One track's opening rows of one family on A-{level}.00. `placed` is
    [(tag, unit)] - unit None for a tag whose placement was refused."""
    title, units = FLOORS[level]
    page = {"project_id": PID, "company_id": "c1", "file_id": f"f-{track}", "file_hash": "h",
            "file_name": f"{track}.pdf", "page_id": f"pg-a{level}-{track}", "page_number": 4,
            "sheet_number": f"A-{level}.00", "sheet_title": title, "discipline": "architectural",
            "drawing_track": track, "drawing_track_label": LABEL if track == "post_co" else None}
    recs = [{"tag": t, "unit": u, "glyph_status": "resolved",
             "placement": ("placed" if u and not u.startswith("non-unit:") else
                           "placed-non-unit" if u else "refused"),
             "reason": None if u else "refused: contested", "label_text": t,
             "label_box": (1, 2, 3, 4), "symbol_bbox": (5, 6, 7, 8), "symbol_at": (6, 7),
             "at_arch": (6, 7), "label_at": (2, 3)} for t, u in placed]
    recs += [{"tag": None, "unit": None, "glyph_status": "unread", "placement": None,
              "reason": "a door symbol no tag names", "label_text": "", "label_box": None,
              "symbol_bbox": (5, 6, 7, 8), "symbol_at": (6, 7), "at_arch": None,
              "label_at": None} for _ in range(unread)]
    rows = E.glyph_rows({"records": recs, "method": "layers",
                         "registration": {"dx": 0.0, "dy": 0.0, "usable": True}},
                        mech=page, arch=page, family=family,
                        pass_key=f"A-{level}.00|openings|{family}",
                        units={"tags": units, "method": "plan_tags", "zero_units": False,
                               "multi_level": multi if multi is not None else {u: [] for u in units}},
                        widest_door={"inches": 40.0}, mech_count=len(recs))
    for r in rows:
        r["payload"].update(kind="opening", track=track)
    return rows


def _refusal(track, sheet, why):
    page = {"project_id": PID, "company_id": "c1", "file_id": "f-x", "file_hash": "h",
            "file_name": "SET_UPDATED.pdf", "page_id": f"pg-{sheet}-{track}", "page_number": 3,
            "sheet_number": sheet, "sheet_title": "FLOOR PLAN"}
    r = E.sheet_refusal(page, why, pass_key=f"openings|{sheet}", role="opening")
    r["payload"].update(kind="opening", track=track)
    return r


def _numbered(rows):
    for i, r in enumerate(rows):
        r["ordinal"] = i
    return rows


def _census(rows, tracks=("filed", "post_co"), fams=(INT, WIN)):
    """What count_documents says, per track, scope OPENING."""
    pages = sorted({r["page_id"] for r in rows})
    out = []
    for t in tracks:
        for name in fams:
            c = S.glyph_census("family", PID, pages, 0, family=name, tags=TAGS[name],
                               track=t, scope=S.OPENING)
            c["count"] = sum(1 for r in rows if S.glyph_in_census(r, c))
            out.append(c)
        c = S.glyph_census("refusals", PID, pages, 0, track=t, scope=S.OPENING)
        c["count"] = sum(1 for r in rows if S.glyph_in_census(r, c))
        out.append(c)
    return out


def _second_floor(track):
    """2A..2D as measured on both tracks' A-101.00."""
    per = {"2A": "BFFG", "2B": "BFFG", "2C": "BFFFG", "2D": "BFFFG"}
    doors = [(t, u) for u, ts in per.items() for t in ts] + [("A", "non-unit:DN UP")] * 2
    wins = [("W1", u) for u in per for _ in range(2)] + [("W2", "2A"), ("W2", "2C")]
    return _rows(track, "101", INT, doors) + _rows(track, "101", WIN, wins)


def _first_floor(track):
    """A-100: the filed set's D serves the bike room; the owner's set adds
    1A's bedroom door F and closet G, both on a contested symbol."""
    doors = [("A", "non-unit:PUBLIC")] * 2 + [("B", u) for u in ("1A", "1B", "1C", "1D")] \
        + [("E", u) for u in ("1A", "1B", "1C", "1D")] + [("G", "non-unit:PUBLIC")] * 3
    doors += [("D", "non-unit:BIKE ROOM")] if track == "filed" else [("F", None), ("G", None)]
    return _rows(track, "100", INT, doors)


def _duplex(track, mezz_doors=True, unread=0):
    """4A over A-103 and A-104, linked by its stair."""
    lower = _rows(track, "103", INT, [("B", "4A"), ("F", "4A"), ("F", "4A"), ("F", "4A"), ("G", "4A")],
                  multi={"4A": ["stair label UP at (1244, 691) reaches A-104.00"]})
    upper = _rows(track, "104", INT, [("F", "4A")] if mezz_doors else [],
                  multi={"4A": ["linked from A-103.00: stair label UP at (1244, 691)"]}, unread=unread)
    w_low = _rows(track, "103", WIN, [("W1", "4A")] * 2,
                  multi={"4A": ["stair label UP at (1244, 691) reaches A-104.00"]})
    w_up = _rows(track, "104", WIN, [("W1", "4A")] * 2,
                 multi={"4A": ["linked from A-103.00: stair label UP at (1244, 691)"]})
    return lower + upper + w_low + w_up


def _world(*parts, tracks=("filed", "post_co")):
    rows = _numbered([r for p in parts for r in p])
    return rows + _census(rows, tracks)


# ══════════════════════════════════════════════════════════════════════════
# 1. The schedule: an elevation-style schedule's closed set is its panel heads
# ══════════════════════════════════════════════════════════════════════════

class TheScheduleIsItsPanelHeads(unittest.TestCase):

    def test_a400_records_give_the_twelve_types(self):
        P = _P()
        fams = P.families(A400)
        self.assertEqual({n: f["tags"] for n, f in fams.items()},
                         {WIN: ["W1", "W2", "W3"], INT: list("ABCDEFG"), EXT: ["D1", "D2"]})

    def test_the_identifier_column_reading_finds_none_on_them(self):
        """Why the panel reading exists: the records carry no identifier column."""
        _present()
        from lib import plan_symbols as psym
        for s in A400:
            self.assertEqual(psym.closed_set_from_schedule(s["columns"], s["rows"])[0], [])

    def test_a_type_two_schedules_list_counts_in_neither(self):
        P = _P()
        two = [dict(A400[1]), dict(A400[2], columns=[{"header": "NUMBER D1"}, {"header": "NUMBER A"}])]
        fams = P.families(two)
        self.assertNotIn("A", fams[INT]["tags"])
        self.assertNotIn("A", fams[EXT]["tags"])
        self.assertEqual(fams[EXT]["ambiguous"], ["A"])

    def test_a_schedule_not_of_doors_or_windows_is_not_one(self):
        P = _P()
        self.assertEqual(P.families([dict(A400[0], name="TABLE"),
                                     dict(A400[0], name="LIGHTING SCHEDULE")]), {})


# ══════════════════════════════════════════════════════════════════════════
# 2. The plan's tags, read off the fixture pages
# ══════════════════════════════════════════════════════════════════════════

def _page(name, number):
    from lib.plan_page import PlanPage
    return PlanPage(str(require_pdf(name)), number)


class TheTagsAreReadOffThePlan(unittest.TestCase):

    def test_filed_second_floor_tags_by_type(self):
        """AR 3.28.25 p12, A-101.00: 20 door tags, 10 window tags, and the
        legend's W1 key - which is not a window."""
        P = _P()
        from collections import Counter
        tags = P.read_tags(_page("AR - 3.28.25.pdf", 12))
        got = Counter(t["text"] for t in tags if not t["legend"])
        self.assertEqual(dict(got), {"A": 2, "B": 4, "F": 10, "G": 4, "W1": 8, "W2": 2})
        self.assertEqual([t["text"] for t in tags if t["legend"]], ["W1"])

    def test_wall_tags_are_not_window_tags(self):
        """A-500's wall types W1..W6 and partitions P1..P6 print as diamonds
        on WALL TAGS: none of them is read."""
        P = _P()
        texts = {t["text"] for t in P.read_tags(_page("AR - 3.28.25.pdf", 12))}
        self.assertFalse(texts & {"P1", "P2", "P3", "P4", "W4", "W5", "W6"})

    def test_exterior_doors_tagged_on_the_window_layer_are_doors(self):
        """Filed A-100.01 (AR 8.18.26 p6): D1 and D2 sit on A-WINDOW-IDEN."""
        P = _P()
        fams = P.families(A400)
        got = P.floor_records(_page("AR - 8.18.26.pdf", 6), fams, None, "refused: test")
        ext = sorted(r["label_text"] for r in got["records"][EXT])
        self.assertEqual(ext, ["D1", "D2", "D2"])
        self.assertFalse([r for r in got["records"][WIN] if r["label_text"] in ("D1", "D2")])


class OneSymbolOneTag(unittest.TestCase):

    def test_owners_1a_additions_do_not_borrow_the_bath_door(self):
        """Owners set p1, A-100.00: E keeps its bath door; the post-CO F and G
        (drawn on TO REMOVE) are counted, never placed; of the two W1 on 1A's
        west wall, the lower is contested."""
        P = _P()
        fams = P.families(A400)
        got = P.floor_records(_page("Owners set - 6.9.26.pdf", 1), fams, None, "refused: sheet scope")
        by = {}
        for r in got["records"][INT] + got["records"][WIN]:
            by.setdefault(r["label_text"], []).append(r)
        contested = [r for r in by["F"] + by["G"] + by["W1"] + by["E"]
                     if "nearest door/window symbol is" in (r.get("reason") or "")]
        self.assertEqual(sorted(r["label_text"] for r in contested), ["F", "G", "W1"])
        self.assertTrue(all(r["glyph_status"] == "resolved" and r["tag"] for r in contested),
                        "a contested tag still names its type and counts on its floor")
        self.assertTrue(all("E's" in r["reason"] for r in contested if r["label_text"] in "FG"))

    def test_owners_mezzanine_doors_with_no_tag_are_unread(self):
        """Owners set p5, A-104.00: four A-Door symbols, no door tag."""
        P = _P()
        fams = P.families(A400)
        got = P.floor_records(_page("Owners set - 6.9.26.pdf", 5), fams, None, "refused: sheet scope")
        self.assertEqual(len([u for u in got["untagged"] if u["kind"] == "door"]), 4)
        self.assertEqual(len([u for u in got["untagged"] if u["kind"] == "window"]), 0)
        for name in (INT, EXT):
            self.assertEqual(sum(1 for r in got["records"][name] if r["glyph_status"] == "unread"), 4)
        self.assertEqual(sum(1 for r in got["records"][WIN] if r["glyph_status"] == "unread"), 0)


class AnApartmentByItsSymbols(unittest.TestCase):
    """The equipment's placement, on the filed second floor."""

    @classmethod
    def setUpClass(cls):
        # read once for the class - and on a tree without the pass, read
        # nothing, so each test fails on its own assertion (setUp)
        cls.got = None
        try:
            _present()
        except AssertionError:
            return
        from lib import plan_derive as derive
        from lib import plan_openings as P
        from lib.plan_sheet import load_sheet
        from lib.plan_space import build_space
        from lib.plan_takeoff import Units
        pg = _page("AR - 3.28.25.pdf", 12)
        data = load_sheet(pg)
        units = derive.unit_tags(data["words"], data["corners"])
        door = derive.widest_door_in(_page("AR - 3.28.25.pdf", 23).directed_words)
        sp = build_space(pg, units["tags"], door["inches"], data)
        cls.member = Units(sp["units"], sp["lo"], sp["cell_pt"], sp["refused"], sp, sp["tags"])
        cls.got = P.floor_records(pg, P.families(A400), cls.member)

    def setUp(self):
        _present()

    def test_2c_by_eye(self):
        """Rendered and read 2026-10-26: entrance B, foyer-closet F, bath F,
        bedroom F, closet G, W1 x2, W2."""
        from collections import Counter
        recs = [r for rs in self.got["records"].values() for r in rs]
        c = Counter(r["tag"] for r in recs if r["unit"] == "2C")
        self.assertEqual(dict(c), {"B": 1, "F": 3, "G": 1, "W1": 2, "W2": 1})
        self.assertEqual(Counter(r["tag"] for r in recs if r["unit"] == "2A"),
                         Counter({"B": 1, "F": 2, "G": 1, "W1": 2, "W2": 1}))

    def test_the_entrance_is_placed_by_its_door_not_its_tag(self):
        """2C's B tag sits in the doorway on the corridor side; its door swings
        into 2C. The tag's own point is not in 2C."""
        b = [r for r in self.got["records"][INT] if r["tag"] == "B" and r["unit"] == "2C"]
        self.assertEqual(len(b), 1)
        x, y = b[0]["label_at"]
        self.assertNotEqual(self.member.unit_of_normal(x, y)[0], "2C")

    def test_the_stair_doors_belong_to_no_apartment(self):
        a = [r for r in self.got["records"][INT] if r["tag"] == "A"]
        self.assertEqual(len(a), 2)
        self.assertTrue(all(str(r["unit"]).startswith("non-unit:") for r in a))

    def test_every_symbol_has_its_tag(self):
        self.assertEqual(self.got["untagged"], [])
        self.assertEqual(len(self.got["legend"]), 1)


# ══════════════════════════════════════════════════════════════════════════
# 3. The gate: the equipment's binding rules, per drawing track
# ══════════════════════════════════════════════════════════════════════════

class PerApartmentFloorAndBuilding(unittest.TestCase):

    def test_tracks_that_agree_bind_unqualified(self):
        _present()
        recs = _world(_second_floor("filed"), _second_floor("post_co"))
        self.assertTrue(_ok("2C has 3 type-F doors.", recs))
        self.assertTrue(_ok("2A has 2 type F doors.", recs))
        self.assertTrue(_ok("The second floor has 10 type-F doors.", recs))
        self.assertTrue(_ok("The second floor has 10 windows.", recs))
        self.assertTrue(_ok("2C has 3 windows.", recs))
        self.assertTrue(_ok("Each unit on the second floor has 2 W1.", recs))
        self.assertFalse(_ok("2C has 2 type-F doors.", recs))
        self.assertFalse(_ok("The second floor has 11 type-F doors.", recs))

    def test_a_zero_never_binds(self):
        _present()
        recs = _world(_second_floor("filed"), _second_floor("post_co"))
        self.assertFalse(_ok("2B has 0 W2.", recs))
        self.assertFalse(_ok("The second floor has 0 type-C doors.", recs))

    def test_tracks_that_differ_bind_only_named(self):
        """A-100: filed G 3 (D for the bike room), owner G 4."""
        _present()
        recs = _world(_first_floor("filed"), _first_floor("post_co"))
        self.assertFalse(_ok("The first floor has 3 type-G doors.", recs))
        self.assertFalse(_ok("The first floor has 4 type-G doors.", recs))
        self.assertTrue(_ok("The first floor has 3 type-G doors in the filed set.", recs))
        self.assertTrue(_ok("The first floor has 4 type-G doors per the owner's set.", recs))
        self.assertTrue(_ok("The first floor has 4 type-G doors per the owner's post-CO set, 6/9/26.", recs))
        self.assertFalse(_ok("The first floor has 3 type-G doors per the owner's set.", recs))
        # the sets agree on B
        self.assertTrue(_ok("The first floor has 4 type-B doors.", recs))

    def test_a_contested_tag_counts_on_its_floor_but_places_nowhere(self):
        _present()
        recs = _world(_first_floor("post_co"), tracks=("post_co",))
        self.assertTrue(_ok("The first floor has 1 type-F door per the owner's set.", recs))
        self.assertFalse(_ok("1A has 1 type-F door per the owner's set.", recs))
        self.assertTrue(_ok("1A has 1 type-E door per the owner's set.", recs))
        self.assertFalse(_ok("1A has 2 interior doors per the owner's set.", recs),
                         "the family's split waits for every tag to be placed")

    def test_a_duplex_is_the_whole_apartment(self):
        _present()
        recs = _world(_duplex("filed"), tracks=("filed",))
        self.assertTrue(_ok("4A has 4 type-F doors.", recs))
        self.assertTrue(_ok("4A has 4 windows.", recs))
        self.assertFalse(_ok("4A has 3 type-F doors.", recs))

    def test_an_untagged_symbol_refuses_its_floor_and_the_apartment(self):
        """The owner's mezzanine: no door tags, four untagged doors."""
        _present()
        recs = _world(_duplex("filed"), _duplex("post_co", mezz_doors=False, unread=1))
        self.assertTrue(_ok("4A has 4 type-F doors in the filed set.", recs))
        self.assertFalse(_ok("4A has 3 type-F doors per the owner's set.", recs))
        self.assertFalse(_ok("4A has 4 type-F doors.", recs), "the sets do not agree")
        self.assertFalse(_ok("The mezzanine has 1 type-F door per the owner's set.", recs))
        self.assertTrue(_ok("The mezzanine has 1 type-F door in the filed set.", recs))
        # windows are another family: untouched by an untagged door
        self.assertTrue(_ok("4A has 4 windows.", recs))
        self.assertTrue(_ok("The mezzanine has 2 windows per the owner's set.", recs))

    def test_one_untagged_door_beside_located_ones_refuses_floor_and_building(self):
        """The same mezzanine with its F tags located AND one door no tag
        names: the located 1 is no longer the floor's figure, nor 4 the
        building's - that door may be an F. Without it, both bind."""
        _present()
        clean = _world(_duplex("post_co"), tracks=("post_co",))
        self.assertTrue(_ok("The mezzanine has 1 type-F door per the owner's set.", clean))
        self.assertTrue(_ok("There are 4 type-F doors per the owner's set.", clean))
        dirty = _world(_duplex("post_co", unread=1), tracks=("post_co",))
        self.assertFalse(_ok("The mezzanine has 1 type-F door per the owner's set.", dirty))
        self.assertFalse(_ok("There are 4 type-F doors per the owner's set.", dirty))
        self.assertTrue(_ok("The fourth floor has 3 type-F doors per the owner's set.", dirty),
                        "only the floor that holds it")

    def test_a_plan_the_pass_could_not_read_blocks_its_buildings_total(self):
        _present()
        rows = _second_floor("filed") + _second_floor("post_co")
        rows.append(_refusal("filed", "A.1.2", "A.1.2 is a plan with no mechanical partner"))
        recs = _world(rows)
        self.assertFalse(_ok("There are 10 type-F doors in the filed set.", recs))
        self.assertTrue(_ok("There are 10 type-F doors per the owner's set.", recs))
        self.assertFalse(_ok("There are 10 type-F doors.", recs))
        self.assertTrue(_ok("The second floor has 10 type-F doors.", recs),
                        "a sheet outside the plan series blocks no floor")

    def test_two_door_schedules_are_never_added(self):
        _present()
        rows = _second_floor("filed") + _rows("filed", "101", EXT, [("D1", "non-unit:PUBLIC")])
        recs = _numbered(rows) + _census(rows, ("filed",), (INT, EXT, WIN))
        self.assertTrue(_ok("The second floor has 20 interior doors.", recs))
        self.assertFalse(_ok("The second floor has 21 doors.", recs))
        self.assertFalse(_ok("The second floor has 20 doors.", recs))


class TheArticleIsNotATypeA(unittest.TestCase):

    def test_a_names_no_type(self):
        _present()
        self.assertEqual(S._named_opening_tags("A unit has a door and A stair", list("ABCDEFG")), [])
        self.assertEqual(S._named_opening_tags("2 type A doors and 1 B-type", list("ABCDEFG")), ["A", "B"])

    def test_a_sentence_with_an_article_binds_nothing_from_type_a(self):
        """Type A counts 2 on the second floor; "A ... has 2" must not bind it."""
        _present()
        recs = _world(_second_floor("filed"), _second_floor("post_co"))
        self.assertTrue(_ok("The second floor has 2 type-A doors.", recs))
        self.assertFalse(_ok("A stair on the second floor has 2 doors.", recs))
        self.assertFalse(_ok("The second floor has a 2.", recs))

    def test_a_fan_question_fetches_no_door(self):
        _present()
        self.assertEqual(S.opening_families_for("how many fans in a unit", TAGS), {})
        self.assertEqual(set(S.opening_families_for("type B doors", TAGS)), {INT, EXT})


class ThePrintedQtyLendsNothing(unittest.TestCase):

    def test_a_qty_cell_is_no_door_count(self):
        """A door schedule that DID print QTY: the figure is a cross-check, never a count."""
        _present()
        rows = _second_floor("filed")
        recs = _numbered(rows)
        cens = _census(rows, ("filed",))
        for c in cens:
            if c.get("family") == INT:
                c["qty"] = {"F": "12", "G": "4"}
        recs += cens
        self.assertFalse(_ok("There are 12 type-F doors.", recs))
        self.assertTrue(_ok("There are 4 type-G doors.", recs), "QTY agrees: the located 4 stands")
        self.assertFalse(_ok("There are 10 type-F doors.", recs),
                         "a located total that disagrees with the printed QTY refuses")


class KeptApartFromTheEquipment(unittest.TestCase):

    def test_an_opening_refusal_blocks_no_equipment_total(self):
        _present()
        mech = {"project_id": PID, "company_id": "c1", "file_id": "f-mh", "file_hash": "h",
                "file_name": "MH.pdf", "page_id": "pg-m101", "page_number": 5,
                "sheet_number": "M-101.00", "sheet_title": "SECOND FLOOR HVAC PLANS",
                "discipline": "mechanical"}
        ef = E.glyph_rows({"records": [{"tag": "EF-1", "unit": "2A", "glyph_status": "resolved",
                                        "placement": "placed", "label_text": "EF-1",
                                        "label_box": (1, 2, 3, 4), "label_at": (2, 3)}],
                           "method": "layers", "registration": {"usable": True}},
                          mech=mech, arch={"sheet_number": "A-101.00"}, family="EXHAUST FAN SCHEDULE",
                          pass_key="k", units={"tags": ["2A"], "multi_level": {"2A": []}},
                          widest_door={"inches": 40.0})
        rows = _numbered(ef + [_refusal(None, "A-102.00", "unreadable")])
        rows[-1]["payload"].pop("track")
        pages = sorted({r["page_id"] for r in rows})
        recs = list(rows)
        for kind, kw in (("family", {"family": "EXHAUST FAN SCHEDULE", "tags": ["EF-1"]}), ("refusals", {})):
            c = S.glyph_census(kind, PID, pages, 0, **kw)
            c["count"] = sum(1 for r in rows if S.glyph_in_census(r, c))
            recs.append(c)
        self.assertTrue(_ok("There is 1 EF-1.", recs))

    def test_the_filter_and_the_predicate_agree_for_both(self):
        _present()
        from tests.test_a_located_count_is_complete_or_refused import _match
        rows = _numbered(_second_floor("filed") + [_refusal("filed", "A.1.2", "x")])
        eq = dict(rows[0], payload=dict(rows[0]["payload"]))
        eq["payload"].pop("kind")
        eq_ref = dict(rows[-1], payload=dict(rows[-1]["payload"]), ordinal=999)
        eq_ref["payload"].pop("kind")
        world = rows + [eq, eq_ref]
        pages = sorted({r["page_id"] for r in world})
        for scope in (None, S.OPENING):
            for kind, flt, kw in (("family", S.glyph_family_filter(PID, pages, INT, TAGS[INT], scope=scope),
                                   {"family": INT, "tags": TAGS[INT]}),
                                  ("refusals", S.glyph_refusal_filter(PID, pages, scope=scope), {})):
                c = S.glyph_census(kind, PID, pages, 0, scope=scope, **kw)
                by_db = [i for i, r in enumerate(world) if _match(r, flt)]
                by_py = [i for i, r in enumerate(world) if S.glyph_in_census(r, c)]
                self.assertEqual(by_db, by_py, (kind, scope))
                self.assertTrue(by_db, (kind, scope))


class TheRenderSaysOnlyWhatBinds(unittest.TestCase):

    def test_agreeing_figures_once_differing_ones_labelled(self):
        _present()
        recs = _world(_first_floor("filed"), _first_floor("post_co"),
                      _second_floor("filed"), _second_floor("post_co"))
        text = S.render_opening_evidence(recs)
        self.assertIn("2C: type B 1, type F 3, type G 1; 5 in all", text)
        self.assertIn("SECOND FLOOR PLAN [A-101.00]: type A 2, type B 4, type F 10, type G 4; 20 in all", text)
        self.assertIn("per the filed set: FIRST FLOOR PLAN [A-100.00]", text)
        self.assertIn(f"per {LABEL}: FIRST FLOOR PLAN [A-100.00]", text)
        self.assertIn("THE SETS DIFFER", text)
        self.assertNotIn("- FIRST FLOOR PLAN", text, "the first floor differs: never stated unlabelled")

    def test_the_server_shows_it_to_the_model(self):
        _present()
        recs = _world(_second_floor("filed"), _second_floor("post_co"))
        self.assertIn("Door and window tags", server._render_records_for_model(recs, "type F doors"))


class TheServerFetchesAndCensusesThem(unittest.TestCase):

    def test_glyph_evidence_for_a_door_question(self):
        _present()
        db = AsyncFakeDB()
        rows = _numbered(_second_floor("filed"))
        for r in rows:
            r["project_id"] = PID
            db.plan_records.docs.append(dict(r))
        for i, s in enumerate(A400):
            db.plan_records.docs.append({"project_id": PID, "record_type": "schedule",
                                         "page_id": "pg-a400", "sheet_number": "A-400.00",
                                         "tier": s["tier"], "payload": {"name": s["name"],
                                                                         "columns": s["columns"],
                                                                         "rows": s["rows"]}})
        pages = sorted({r["page_id"] for r in rows} | {"pg-a400"})

        async def page_ids(_pid):
            return pages
        with patch.object(server, "db", db), patch.object(server, "_glyph_page_ids", page_ids):
            got = asyncio.run(server._glyph_evidence(PID, "type F doors"))
        cen = [g for g in got if g.get("record_type") == S.GLYPH_CENSUS]
        self.assertTrue(cen and all(c.get("scope") == S.OPENING for c in cen))
        self.assertEqual({c.get("family") for c in cen if c["kind"] == "family"}, {INT, EXT})
        self.assertTrue(_ok("The second floor has 10 type-F doors.", got))
        self.assertFalse(_ok("The second floor has 9 type-F doors.", got))

    def test_the_pass_hands_run_pass_the_door_schedules_and_appends_their_rows(self):
        _present()
        from tests.test_two_drawing_tracks import _raw
        from bson import ObjectId
        db = AsyncFakeDB()
        proj = ObjectId()
        raw, files = _raw()
        for k, f in files.items():
            db.project_files.docs.append(dict(f, _id=k, project_id=str(proj), is_deleted=False))
        for p in raw:
            db.document_page_index.docs.append(dict(p, project_id=str(proj)))
        a_page = next(p for p in raw if p["_id"] == "ar325#12")      # current on the filed track
        db.plan_records.docs.append({"project_id": str(proj), "record_type": "schedule",
                                     "page_id": str(a_page["_id"]), "sheet_number": "A-400.00",
                                     "tier": "schedule_cell",
                                     "payload": {"name": WIN, "columns": A400[0]["columns"],
                                                 "rows": A400[0]["rows"]}})
        seen, written = [], {}

        def fake_pass(pages, open_page, schedules, door_pages, track="filed", sweeps=None,
                      opening_schedules=()):
            seen.append([s["name"] for s in opening_schedules])
            return {"rows": [{"label": "EF-1", "payload": {"track": track}}],
                    "summary": {}, "opening_rows": [{"label": "W1", "payload": {"kind": "opening",
                                                                                 "track": track}}],
                    "opening_health": []}

        async def live(_pid):
            return list(files)

        async def write(_pid, rows):
            written["rows"] = rows
            return len(rows)

        async def write_health(_pid, items):
            return len(items)
        with patch.object(server, "db", db), patch.object(server, "_live_plan_file_ids", live), \
                patch("lib.plan_glyph_pass.run_pass", fake_pass), \
                patch.object(server, "_glyph_set_health", lambda *a, **k: []), \
                patch.object(server, "_write_glyph_records", write), \
                patch.object(server, "_write_set_health", write_health):
            asyncio.run(server._plan_glyph_pass(str(proj)))
        self.assertTrue(seen and all(s == [WIN] for s in seen))
        labels = [r["label"] for r in written["rows"]]
        n = len(seen)
        self.assertEqual(labels, ["EF-1"] * n + ["W1"] * n,
                         "every equipment row first, numbered as before; the openings after")


if __name__ == "__main__":
    unittest.main()
