"""TWO DRAWING TRACKS: EACH PLACED ON ITS OWN, EACH SYMBOL COUNTED ONCE.

On 588 Boyland the filed AR set governs and the Owner's set (6/9/26) is the
owner's post-CO additions: a second track, not a revision. The index
supersedes across sets by date, so the pass read floors 2 to the mezzanine
from the Owner's set only and the filed set's plans for them were never
read. Measured 2026-10-24: 130 per-apartment answers agree between the
tracks, 2 differ (1A's PTACs: 1 on the filed set, 2 on the Owner's - its
bike room), 44 come from the Owner's set alone.

Rulings (operator, 2026-10-24):
  1. newest page per track; supersession only within a track;
  2. rows carry their track; each mechanical symbol is placed once per track;
  3. floor and building totals count each mechanical symbol ONCE, whatever
     the track; censuses per track; INVARIANT - on every floor, each
     track's placed + unplaced symbols must number the mechanical sheet's
     count, or that floor's totals are refused and it is logged;
  4. per apartment: agree -> stated once; differ -> both stated, each
     labelled; one track only -> that figure, labelled. An unqualified
     claim binds only when the tracks agree; when they differ a claim binds
     only if it names its set and matches it;
  5. EMIT_VERSION 7.
"""
from __future__ import annotations

import asyncio
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

from bson import ObjectId  # noqa: E402

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402
from lib import plan_emit as E  # noqa: E402
from lib import plan_search as S  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

PID = "p1"
PT = "ROOMS PTAC UNITS SCHEDULE"
TAGS = ["PTAC-1", "PTAC-2", "PTAC-3"]
LABEL = "the owner's post-CO set, 6/9/26"
FLOORS = {"100": ("FIRST FLOOR HVAC PLANS", ["1A", "1B", "1C", "1D"]),
          "101": ("SECOND FLOOR HVAC PLANS", ["2A", "2B", "2C", "2D"]),
          "106": ("BULKHEAD HVAC PLANS", [])}
SAF = "FAN SCHEDULE"


def _present():
    assert hasattr(S, "glyph_books") and hasattr(server, "_glyph_track_pages"), \
        "the pass and the gate read one drawing track in this tree"


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


# ── rows, by the real emitter ─────────────────────────────────────────────

def _rows(track, level, placed, mech_count=None, v7=True, family=PT):
    """One track's rows of M-{level}.00, placed against its own A-{level}.
    `placed` is [(tag, unit)] - unit None for a symbol not placed."""
    title, units = FLOORS[level]
    mech = {"project_id": PID, "company_id": "c1", "file_id": "f-mh", "file_hash": "h",
            "file_name": "MH.pdf", "page_id": f"pg-m{level}", "page_number": 5,
            "sheet_number": f"M-{level}.00", "sheet_title": title, "discipline": "mechanical"}
    arch = {"page_id": f"pg-a{level}-{track}", "file_id": f"f-{track}", "page_number": 4,
            "sheet_number": f"A-{level}.00", "drawing_track": track,
            "drawing_track_label": LABEL if track == "post_co" else None}
    result = {"records": [{"tag": t, "unit": u, "glyph_status": "resolved",
                           "placement": "placed" if u else "refused",
                           "reason": None if u else "refused: in a wall",
                           "label_text": t, "label_box": (1, 2, 3, 4), "symbol_bbox": (5, 6, 7, 8),
                           "symbol_at": (6, 7), "at_arch": (9, 9), "label_at": (2, 3)}
                          for t, u in placed],
              "method": "layers", "registration": {"anchors": 900, "usable": True}}
    rows = E.glyph_rows(result, mech=mech, arch=arch, family=family,
                        pass_key=f"A-{level}.00|M-{level}.00|{family}",
                        units={"tags": units, "method": "plan_tags", "zero_units": False,
                               "multi_level": {u: [] for u in units}},
                        widest_door={"inches": 56.0})
    for r in rows:
        r["payload"].pop("mech_count", None)
        if v7:      # as run_pass writes them (EMIT_VERSION 7)
            r["payload"]["track"] = track
            r["payload"]["mech_count"] = len(placed) if mech_count is None else mech_count
    return rows


FILED_100 = [("PTAC-1", "1A"), ("PTAC-3", "non-unit:BIKE ROOM"), ("PTAC-2", "1B"),
             ("PTAC-3", "1C"), ("PTAC-3", "1D")]
OWNER_100 = [("PTAC-1", "1A"), ("PTAC-3", "1A"), ("PTAC-2", "1B"),
             ("PTAC-3", "1C"), ("PTAC-3", "1D")]
FILED_101 = [("PTAC-1", "2A"), ("PTAC-2", "2B"), ("PTAC-1", None), ("PTAC-2", "2D")]
OWNER_101 = [("PTAC-1", "2A"), ("PTAC-2", "2B"), ("PTAC-1", "2C"), ("PTAC-2", "2D")]


def _gc(kind, pages, count, track, **kw):
    """A census as the server writes it: one per drawing track."""
    c = S.glyph_census(kind, PID, pages, count, **kw)
    if track is not None:
        c["track"] = track
    return c


def _census(db_rows, track, short=0):
    """What count_documents says, per track - `short` rows the database
    holds beyond those in hand."""
    pages = sorted({r["page_id"] for r in db_rows})
    c = _gc("family", pages, 0, track, family=PT, tags=TAGS)
    fam = _gc("family", pages, short + sum(S.glyph_in_census(r, c) for r in db_rows), track,
              family=PT, tags=TAGS)
    c = _gc("refusals", pages, 0, track)
    ref = _gc("refusals", pages, sum(S.glyph_in_census(r, c) for r in db_rows), track)
    return [fam, ref]


def _line(render, floor):
    """The render's one PTAC line for `floor` - asserted, so a render that
    has none fails by assertion."""
    got = [l for l in render.splitlines() if floor in l and l.startswith("- ")]
    assert len(got) == 1, f"{len(got)} lines for {floor} in: {render}"
    return got[0]


def _numbered(rows):
    n = {}
    for r in rows:
        r["ordinal"] = n.get(r["page_id"], 0)
        n[r["page_id"]] = r["ordinal"] + 1
    return rows


def _world(*, owner_100=OWNER_100, owner_101=OWNER_101, filed_100=FILED_100,
           filed_101=FILED_101, owner_mech=None, short=None, owner=True):
    rows = _rows("filed", "100", filed_100) + _rows("filed", "101", filed_101)
    if owner:
        rows += (_rows("post_co", "100", owner_100, mech_count=owner_mech)
                 + _rows("post_co", "101", owner_101))
    rows = _numbered(rows)
    recs = list(rows) + _census(rows, "filed", (short or {}).get("filed", 0))
    if owner:
        recs += _census(rows, "post_co", (short or {}).get("post_co", 0))
    return recs


# ── 1. newest page per track; supersession only within a track ────────────

def _raw():
    files = {"ar325": {"name": "AR - 3.28.25.pdf"}, "ar818": {"name": "AR - 8.18.26.pdf"},
             "own": {"name": "Owners set - 6.9.26.pdf", "drawing_track": "post_co",
                     "drawing_track_label": LABEL},
             "mh": {"name": "MH - 7.2.26.pdf"}}
    pages = [("ar325", 11, "A-100.00"), ("ar325", 12, "A-101.00"), ("ar818", 6, "A-100.01"),
             ("own", 1, "A-100.00"), ("own", 2, "A-101.00"),
             ("mh", 2, "M-100.00"), ("mh", 3, "M-101.00"), ("mh", 8, "M-106.00")]
    raw = [{"_id": f"{f}#{n}", "file_id": f, "file_hash": f"h-{f}", "page_number": n,
            "sheet_number": sn, "sheet_title": "PLAN", "superseded_by": None}
           for f, n, sn in pages]
    return raw, files


class SupersessionIsWithinATrack(unittest.TestCase):

    def test_each_track_keeps_its_own_newest_plans(self):
        _present()
        raw, files = _raw()
        got = {t: sorted(p["_id"] for p in ps)
               for t, ps in server._glyph_track_pages(raw, files, set(files))}
        self.assertEqual(got["filed"], ["ar325#12", "ar818#6", "mh#2", "mh#3", "mh#8"])
        self.assertEqual(got["post_co"], ["mh#2", "mh#3", "own#1", "own#2"])

    def test_the_index_rule_alone_would_hide_the_filed_plan(self):
        """The same rule over every set at once - the index - puts the
        Owner's set over the filed A-101.00: why the pass splits first."""
        _present()
        raw, files = _raw()
        losers = server._supersession_winners(raw, [dict(f, _id=k) for k, f in files.items()])
        self.assertEqual(losers.get("ar325#12"), "own")
        self.assertNotIn("ar325#12", [p for p in losers if losers[p] == "ar325"])

    def test_a_mechanical_sheet_goes_only_to_a_track_with_a_plan_for_its_floor(self):
        _present()
        raw, files = _raw()
        post = dict(server._glyph_track_pages(raw, files, set(files)))["post_co"]
        self.assertNotIn("mh#8", [p["_id"] for p in post])        # M-106: no A-106 anywhere


class ThePassRunsOncePerTrack(unittest.TestCase):

    def test_two_calls_one_sweep_cache_one_numbering(self):
        _present()
        db = AsyncFakeDB()
        proj = ObjectId()
        raw, files = _raw()
        for k, f in files.items():
            db.project_files.docs.append(dict(f, _id=k, project_id=str(proj), is_deleted=False))
        for p in raw:
            db.document_page_index.docs.append(dict(p, project_id=str(proj)))
        calls = []

        def fake_pass(pages, open_page, schedules, door_pages, track="filed", sweeps=None):
            calls.append((track, id(sweeps), len(pages)))
            return {"rows": [{"page_id": "pg-m100", "ordinal": i, "payload": {"track": track}}
                             for i in range(3)], "summary": {}}

        written = {}

        async def live(_pid):
            return list(files)

        async def write(_pid, rows):
            written["rows"] = rows
            return len(rows)
        with patch.object(server, "db", db), patch.object(server, "_live_plan_file_ids", live), \
                patch("lib.plan_glyph_pass.run_pass", fake_pass), \
                patch.object(server, "_write_glyph_records", write):
            summary = asyncio.run(server._plan_glyph_pass(str(proj)))
        self.assertEqual([c[0] for c in calls], ["filed", "post_co"])
        self.assertEqual(len({c[1] for c in calls}), 1, "each track swept the sheets again")
        self.assertEqual([r["ordinal"] for r in written["rows"]], list(range(6)))
        self.assertEqual(sorted(summary["tracks"]), ["filed", "post_co"])


# ── 3. totals: each mechanical symbol once; censuses per track ────────────

class TotalsCountEachSymbolOnce(unittest.TestCase):

    def test_floor_and_building_totals(self):
        _present()
        recs = _world()
        self.assertTrue(_ok("The first floor has 5 PTAC units.", recs))
        self.assertFalse(_ok("The first floor has 10 PTAC units.", recs))
        self.assertTrue(_ok("There are 3 PTAC-1.", recs))
        self.assertFalse(_ok("There are 6 PTAC-1.", recs))

    def test_a_named_set_changes_no_total(self):
        _present()
        recs = _world()
        self.assertTrue(_ok("There are 3 PTAC-1 in the filed set.", recs))
        self.assertTrue(_ok("There are 3 PTAC-1 per the owner's post-CO set, 6/9/26.", recs))

    def test_censuses_are_per_track(self):
        _present()
        recs = _world()
        self.assertEqual(sorted(c.get("track") for c in recs
                                if c.get("record_type") == S.GLYPH_CENSUS),
                         ["filed", "filed", "post_co", "post_co"])
        short = _world(short={"post_co": 1})       # a post-CO row not in hand
        self.assertFalse(_ok("There are 3 PTAC-1.", short))
        self.assertFalse(_ok("2A has 1 PTAC unit.", short))
        self.assertTrue(_ok("1B has 1 PTAC unit.", short))       # the filed set's, alone


class ASheetOneTrackDoesNotReadKeepsItsTotal(unittest.TestCase):

    def test_the_bulkhead_fan_counts_on_the_filed_track_alone(self):
        """M-106.00 has no architectural partner on the owner's track, so
        that track locates no SAF-1 - which is not a reason to refuse it."""
        _present()
        base = [r for r in _world() if r.get("record_type") == "glyph"]
        saf = _rows("filed", "106", [("SAF-1", None)], family=SAF)
        rows = _numbered(base + saf)
        recs = list(rows)
        pages = sorted({r["page_id"] for r in rows})
        for t in ("filed", "post_co"):
            recs += _census(rows, t)
            c = _gc("family", pages, 0, t, family=SAF, tags=["SAF-1"])
            recs.append(_gc("family", pages, sum(S.glyph_in_census(r, c) for r in rows), t,
                            family=SAF, tags=["SAF-1"]))
        self.assertTrue(_ok("There is 1 SAF-1.", recs))
        self.assertTrue(_ok("The bulkhead has 1 SAF-1.", recs))


class TheInvariant(unittest.TestCase):
    """On every floor each track's located rows must number the mechanical
    sheet's count; else that floor's totals refuse, and it is logged."""

    def test_a_track_short_of_the_sheet_refuses_that_floors_totals(self):
        _present()
        with self.assertLogs("lib.plan_search", "WARNING") as logs:
            recs = _world(owner_100=OWNER_100[:4], owner_mech=5)
            self.assertFalse(_ok("The first floor has 5 PTAC units.", recs))
            self.assertFalse(_ok("There are 3 PTAC-1.", recs))
            self.assertTrue(_ok("The second floor has 4 PTAC units.", recs))
            # and the short track's own apartments on that floor
            self.assertFalse(_ok("1B has 1 PTAC unit per the owner's set.", recs))
            self.assertTrue(_ok("1B has 1 PTAC unit in the filed set.", recs))
        self.assertTrue(any("4 located on the post_co track against 5" in m
                            for m in logs.output), logs.output)
        line = _line(S.render_glyph_evidence(recs), "FIRST FLOOR")
        self.assertIn("not counted", line)
        self.assertIn("4 located on the post_co track against 5", line)

    def test_tracks_that_disagree_about_the_sheets_count_refuse(self):
        _present()
        recs = _world(owner_mech=6)
        self.assertFalse(_ok("The first floor has 5 PTAC units.", recs))
        self.assertTrue(_ok("The second floor has 4 PTAC units.", recs))    # that floor only

    def test_one_track_is_checked_too(self):
        _present()
        rows = _numbered(_rows("filed", "100", FILED_100, mech_count=6))
        recs = rows + _census(rows, "filed")
        self.assertFalse(_ok("The first floor has 5 PTAC units.", recs))

    def test_rows_before_version_7_are_not_checked(self):
        _present()
        rows = _numbered(_rows("filed", "100", FILED_100, v7=False))
        pages = sorted({r["page_id"] for r in rows})
        recs = list(rows)
        for kind, fam in (("family", PT), ("refusals", None)):
            c = S.glyph_census(kind, PID, pages, 0, family=fam, tags=TAGS if fam else ())
            recs.append(S.glyph_census(kind, PID, pages, sum(S.glyph_in_census(r, c) for r in rows),
                                       family=fam, tags=TAGS if fam else ()))
        self.assertTrue(_ok("The first floor has 5 PTAC units.", recs))


# ── 4. per apartment ──────────────────────────────────────────────────────

class PerApartment(unittest.TestCase):

    def test_agree_binds_with_or_without_a_set_named(self):
        _present()
        recs = _world()
        for s in ("1B has 1 PTAC unit.", "1B has 1 PTAC unit in the filed set.",
                  f"1B has 1 PTAC unit, per {LABEL}."):
            self.assertTrue(_ok(s, recs), s)

    def test_differ_binds_only_a_claim_naming_its_set(self):
        _present()
        recs = _world()
        for s in ("1A has 1 PTAC unit.", "1A has 2 PTAC units.",
                  "1A has 2 PTAC units in the filed set.",
                  "1A has 1 PTAC unit per the owner's post-CO set, 6/9/26."):
            self.assertFalse(_ok(s, recs), s)
        for s in ("1A has 1 PTAC unit in the filed set.",
                  "1A has 2 PTAC units per the owner's set.",
                  f"1A has 2 PTAC units per {LABEL}."):
            self.assertTrue(_ok(s, recs), s)

    def test_a_zero_is_an_answer_so_the_sets_differ(self):
        """1A holds no PTAC-3 on the filed set and one on the owner's: a zero
        is never a bound figure, but it is an answer - not "one track only"."""
        _present()
        recs = _world()
        self.assertFalse(_ok("1A has 1 PTAC-3.", recs))
        self.assertTrue(_ok("1A has 1 PTAC-3 per the owner's set.", recs))
        self.assertFalse(_ok("1A has 1 PTAC-3 in the filed set.", recs))

    def test_one_track_only_binds_its_figure(self):
        _present()
        recs = _world()                    # the filed second floor has an unplaced symbol
        self.assertTrue(_ok("2A has 1 PTAC unit.", recs))
        self.assertTrue(_ok("2A has 1 PTAC unit per the owner's set.", recs))
        self.assertFalse(_ok("2A has 1 PTAC unit in the filed set.", recs))

    def test_a_set_the_project_does_not_have_names_nothing(self):
        _present()
        recs = _world(owner=False)
        self.assertTrue(_ok("1B has 1 PTAC unit.", recs))
        self.assertFalse(_ok("1B has 1 PTAC unit per the owner's set.", recs))

    def test_the_render(self):
        _present()
        text = S.render_glyph_evidence(_world())
        lines = text.splitlines()
        first = _line(text, "FIRST FLOOR")
        self.assertIn("PTAC-1 1, PTAC-2 1, PTAC-3 3; 5 in all", first)    # once, not 10
        self.assertIn("the sets agree: 1B 1, 1C 1, 1D 1", first)
        self.assertIn(f"1A: 1 per the filed set, 2 per {LABEL} - THE SETS DIFFER", first)
        second = _line(text, "SECOND FLOOR")
        self.assertIn(f"2A 1, 2B 1, 2C 1, 2D 1 per {LABEL} only", second)
        self.assertTrue(any("state such a figure only in a sentence naming the set" in l
                            for l in lines))

    def test_agreement_everywhere_renders_as_one_track(self):
        _present()
        both = _world(owner_100=FILED_100, filed_101=OWNER_101)
        one = _world(owner=False, filed_101=OWNER_101)
        pick = lambda recs: [l for l in S.render_glyph_evidence(recs).splitlines()  # noqa: E731
                             if l.startswith("- ")]
        self.assertEqual(pick(both), pick(one))


# ── the real first floor: filed A-100.01 and the Owner's A-100.00 ─────────

class OnTheRealFirstFloor(unittest.TestCase):
    """run_pass per track, end to end, on M-100.00 (MH 7.2.26 p2) with the
    filed A-100.01 (AR 8.18.26 p6) and the Owner's A-100.00 (Owners set p1):
    one sweep, every symbol once per track, and 1A - 1 PTAC on the filed
    set, 2 on the Owner's (its bike room) - answered only with its set."""

    def test_two_tracks_on_real_sheets(self):
        _present()
        from lib.plan_page import PlanPage
        from lib import plan_glyph_pass as G
        from lib import plan_takeoff as T

        def page(fname, n, sheet, title, track="filed", label=None):
            return {"project_id": PID, "company_id": "c1", "file_id": fname, "file_hash": None,
                    "file_name": fname, "page_id": f"{fname}#{n}", "page_number": n,
                    "sheet_number": sheet, "sheet_title": title, "discipline": "AR",
                    "drawing_track": track, "drawing_track_label": label}
        m100 = page("MH - 7.2.26.pdf", 2, "M-100.00", "FIRST FLOOR HVAC PLANS")
        filed = [page("AR - 8.18.26.pdf", 6, "A-100.01", "FIRST FLOOR PLAN"), m100]
        owner = [page("Owners set - 6.9.26.pdf", 1, "A-100.00", "FIRST FLOOR PLAN",
                      "post_co", LABEL), m100]
        a400 = page("AR - 3.28.25.pdf", 23, "A-400.00", "WINDOW SCHEDULE")
        # M-200.00's PTAC schedule as production stores its OCR-grid reading
        sched = [{"name": PT, "tier": "ocr_grid_cell", "sheet_number": "M-200.00",
                  "columns": [{"header": h, "role": r} for h, r in (
                      ("UNIT NO.", "identifier"), ("QTY", "quantity"), ("MAKE", "make"),
                      ("MODEL", "model"), ("ARRANGEMENT", None),
                      ("NET COOLING CAPACITY (BTUH)", None),
                      ("AUXILIARYHEATING CAPACITY (KW)", None),
                      ("NET HEATING CAPACITY(BTUH)", None), ("DEHUMIDIFICATION PTS/HR", None),
                      ("EER", None), ("COP", None), ("VOLTS", None), ("ELEC. MCA A", None),
                      ("MOP A", None), ("NET WEIGHT LBS", None), ("REMARKS", "remarks"))],
                  "rows": [["PTAC-1", "21", "AMANA", "PTH093K", "WALL", "9,000", "2.1", "8,000",
                            "2.0", "12.0", "3.4", "208/1/60", "14.1", "15", "117", "SEE NOTES"],
                           ["PTAC-2", "(readings disagree)", "AMANA", "PTH123K", "WALL", "11,400",
                            "3.0", "10,500", "1.7", "11.1", "3.2", "208/1/60", "19.5", "20", "125",
                            "SEE NOTES"],
                           ["PTAC-3", "11", "AMANA", "PTH153K", "WALL", "14,000", "4.1", "13,700",
                            "4.4", "9.9", "3.0", "208/1/60", "27.6", "30", "130", "SEE NOTES"]]}]
        opened, swept = {}, []
        real_sweep = T.sweep

        def counted_sweep(pg, segs):
            swept.append(1)
            return real_sweep(pg, segs)

        def open_page(p):
            k = (p["file_name"], p["page_number"])
            if k not in opened:
                opened[k] = PlanPage(str(require_pdf(p["file_name"])), p["page_number"])
            return opened[k]
        sweeps, rows = {}, []
        try:
            with patch.object(T, "sweep", counted_sweep):
                for track, pages in (("filed", filed), ("post_co", owner)):
                    rows += G.run_pass(pages, open_page, sched, [a400], track=track,
                                       sweeps=sweeps)["rows"]
        finally:
            for pg in opened.values():
                pg.close()
        for i, r in enumerate(rows):
            r["ordinal"] = i
        self.assertEqual(len(swept), 1, "M-100.00 was swept once per track")
        located = {t: [r for r in rows if r["payload"].get("track") == t
                       and "label_at" in r["payload"]] for t in ("filed", "post_co")}
        counts = {r["payload"]["mech_count"] for rs in located.values() for r in rs}
        self.assertEqual(len(counts), 1, counts)
        (n,) = counts
        for t, rs in located.items():
            self.assertEqual(len(rs), n, t)                  # every symbol once per track
        in_1a = {t: sum(1 for r in rs if r.get("unit") == "1A") for t, rs in located.items()}
        self.assertEqual(in_1a, {"filed": 1, "post_co": 2})
        recs = rows + _census_real(rows, "filed") + _census_real(rows, "post_co")
        self.assertTrue(_ok("1A has 1 PTAC unit in the filed set.", recs))
        self.assertTrue(_ok(f"1A has 2 PTAC units per {LABEL}.", recs))
        self.assertFalse(_ok("1A has 1 PTAC unit.", recs))
        self.assertFalse(_ok("1A has 2 PTAC units.", recs))
        self.assertTrue(_ok(f"The first floor has {n} PTAC units.", recs))
        self.assertFalse(_ok(f"The first floor has {2 * n} PTAC units.", recs))


def _census_real(rows, track):
    pages = sorted({r["page_id"] for r in rows})
    out = []
    for kind, fam, tags in (("family", PT, TAGS), ("refusals", None, ())):
        c = _gc(kind, pages, 0, track, family=fam, tags=tags)
        out.append(_gc(kind, pages, sum(S.glyph_in_census(r, c) for r in rows), track,
                       family=fam, tags=tags))
    return out


if __name__ == "__main__":
    unittest.main()
