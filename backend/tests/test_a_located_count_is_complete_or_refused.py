"""A LOCATED COUNT IS COMPLETE OR REFUSED.

Measured on 588 Boyland 2026-10-06, with the placement pass's 84 rows in
production: search_plans returned 8 records, the glyph rows came back partial,
and the count gate counted what it was handed - "There are 2 EF-1." was
allowed with 16 EF-1 in the database. The rows were deleted (#662) until the
reader is fixed; this is the fix.

What it must hold (operator rulings, 2026-10-06):

  truncation   the gate was only ever tested with zero glyph rows. Every case
               here has MORE ROWS THAN THE LIMIT: 16 EF-1 against limit=8.
  census       a separate count_documents at question time - not carried from
               the pass, not cached, not computed from the fetch it checks. Two
               independent reads of one scope. Shown by a fetch cut short while
               the count is not: the gate refuses.
  scope        a refusal row on the floor refuses the floor; a building total
               with any sheet refused refuses.
  'fan'        names EXHAUST FAN (EF) and FAN SCHEDULE (SAF): the gate answers
               per family or refuses, never a combined total.
  no leak      a glyph row's payload (coordinates, a door width, an RMS) and a
               census's count vouch for no number through any other path.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from lib import plan_emit as E  # noqa: E402
from lib import plan_search as S  # noqa: E402

PID = "p1"
EF, SAF = "EXHAUST FAN SCHEDULE", "FAN SCHEDULE"

FLOORS = {
    "102": ("THIRD FLOOR HVAC PLANS", ["3A", "3B", "3C", "3D"]),
    "103": ("FOURTH FLOOR HVAC PLANS", ["4A", "4B", "4C", "4D"]),
}


def _present():
    for name in ("glyph_book", "glyph_values", "glyph_census", "glyph_in_census",
                 "glyph_family_filter", "glyph_refusal_filter"):
        assert hasattr(S, name), f"plan_search.{name} is not in this tree"


# ── the rows, built by the real emitter ─────────────────────────────────────

def _floor(level, family, placed, status="resolved"):
    """`placed` is [(tag, unit)] - unit None for a symbol not placed."""
    title, units = FLOORS[level]
    mech = {"project_id": PID, "company_id": "c1", "file_id": "f-mh", "file_hash": "h",
            "file_name": "MH.pdf", "page_id": f"pg-m{level}", "page_number": 5,
            "sheet_number": f"M-{level}.00", "sheet_title": title,
            "discipline": "mechanical"}
    arch = {"page_id": f"pg-a{level}", "file_id": "f-ar", "page_number": 4,
            "sheet_number": f"A-{level}.00"}
    result = {"records": [{"tag": t, "unit": u, "glyph_status": status,
                           "placement": "placed" if u else "refused",
                           "label_text": f"{t}(50)", "label_box": (1, 2, 3, 4),
                           "symbol_bbox": (5, 6, 7, 8), "symbol_at": (6, 7),
                           "at_arch": (9, 9), "label_at": (2, 3)}
                          for t, u in placed],
              "method": "layers",
              "registration": {"rms_in": 0.13, "max_in": 0.97, "anchors": 908,
                               "usable": True}}
    return E.glyph_rows(result, mech=mech, arch=arch, family=family,
                        pass_key=f"A-{level}.00|M-{level}.00|{family}",
                        units={"tags": units, "method": "occupancy_table",
                               "zero_units": False},
                        widest_door={"inches": 56.0})


def _refusal(sheet, why, title="MEZZANINE FLOOR HVAC PLANS"):
    return E.sheet_refusal({"project_id": PID, "page_id": f"pg-{sheet}",
                            "page_number": 9, "sheet_number": sheet,
                            "sheet_title": title}, why, pass_key="k")


def _numbered(rows):
    """Unique ordinals per page, as the pass writes them."""
    n = {}
    for r in rows:
        r["ordinal"] = n.get(r["page_id"], 0)
        n[r["page_id"]] = r["ordinal"] + 1
    return rows


def _ef_fourth(per_unit=4):
    """16 EF-1 on the fourth floor: 4 in each of 4 units."""
    return _floor("103", EF, [("EF-1", u) for u in ("4A", "4B", "4C", "4D")
                              for _ in range(per_unit)])


def _pages(rows):
    return sorted({r["page_id"] for r in rows})


def _census(db_rows, pages, families):
    """What count_documents would say - computed from the DATABASE rows, which
    is the point: the census is not the rows in hand."""
    out = []
    for name, tags in families.items():
        c = S.glyph_census("family", PID, pages, 0, family=name, tags=tags)
        out.append(S.glyph_census("family", PID, pages,
                                  sum(S.glyph_in_census(r, c) for r in db_rows),
                                  family=name, tags=tags))
    c = S.glyph_census("refusals", PID, pages, 0)
    out.append(S.glyph_census("refusals", PID, pages,
                              sum(S.glyph_in_census(r, c) for r in db_rows)))
    return out


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


# ── a small Mongo, for the operators these reads use ───────────────────────

def _get(doc, path):
    for part in path.split("."):
        doc = doc.get(part) if isinstance(doc, dict) else None
    return doc


def _match(doc, flt):
    for k, v in flt.items():
        if k == "$or":
            if not any(_match(doc, f) for f in v):
                return False
            continue
        if k == "$and":
            if not all(_match(doc, f) for f in v):
                return False
            continue
        val = _get(doc, k)
        vals = val if isinstance(val, list) else [val]
        if isinstance(v, dict) and any(op.startswith("$") for op in v):
            for op, arg in v.items():
                if op == "$options":
                    continue
                if op == "$in":
                    ok = any(x in arg for x in vals)
                elif op == "$nin":
                    ok = not any(x in arg for x in vals)
                elif op == "$ne":
                    ok = val != arg
                elif op == "$regex":
                    fl = re.I if "i" in v.get("$options", "") else 0
                    ok = any(isinstance(x, str) and re.search(arg, x, fl) for x in vals)
                else:
                    raise AssertionError(f"operator {op} not modelled")
                if not ok:
                    return False
        elif not (val == v or (isinstance(val, list) and v in val)):
            return False
    return True


class _Cur:
    def __init__(self, rows):
        self._rows, self._n = rows, None

    def limit(self, n):
        self._n = n
        return self

    async def to_list(self, n=None):
        cap = min(x for x in (n, self._n, len(self._rows)) if x is not None)
        return [dict(r) for r in self._rows[:cap]]


class _Coll:
    def __init__(self, rows):
        self.rows = rows
        self.counted = []

    def find(self, flt, proj=None):
        return _Cur([r for r in self.rows if _match(r, flt)])

    async def find_one(self, flt, proj=None):
        hits = [r for r in self.rows if _match(r, flt)]
        return dict(hits[0]) if hits else None

    async def count_documents(self, flt):
        self.counted.append(flt)
        return sum(1 for r in self.rows if _match(r, flt))


class _Db:
    def __init__(self, rows):
        self.plan_records = _Coll(rows)

    def __getitem__(self, name):
        assert name == server.PLAN_RECORDS, name
        return self.plan_records


def _schedule(name, tags, page="pg-m001"):
    rows = [[t, "50"] for t in tags]
    return {"project_id": PID, "page_id": page, "sheet_number": "M-001.00",
            "record_type": "schedule", "tier": "ocr_grid", "ordinal": len(tags),
            "quote": f"{name} " + " ".join(tags), "label": "",
            "subject_terms": [name] + list(tags),
            "payload": {"name": name,
                        "columns": [{"header": "TAG", "role": "identifier"},
                                    {"header": "CFM", "role": None}],
                        "rows": rows}}


def _search(db_rows, subject, *, limit=8, fetch_cap=None):
    pages = _pages(db_rows)
    db = _Db(db_rows)

    async def _ids(project_id, **kw):
        return pages

    patches = [patch.object(server, "db", db),
               patch.object(server, "_current_record_page_ids", _ids)]
    if fetch_cap is not None:
        patches.append(patch.object(server, "GLYPH_EVIDENCE_MAX", fetch_cap))
    for p in patches:
        p.start()
    try:
        got = asyncio.run(server.search_plans(PID, subject, intent="count", limit=limit))
    finally:
        for p in reversed(patches):
            p.stop()
    return got, db


def _world(*glyph_rows):
    rows = _numbered([r for rs in glyph_rows for r in rs])
    return [_schedule(EF, ["EF-1", "EF-2"]), _schedule(SAF, ["SAF-1"])] + rows


# ═══════════════════════════════════════════════════════════════════════════

class SixteenAgainstALimitOfEight(unittest.TestCase):
    """The truncation case, through the real search_plans.

    No _present() in three of these, on purpose: on main they run main's own
    search_plans and gate, and fail on what main DOES - return eight and bind
    whatever count of them came back."""

    def test_the_whole_family_comes_back_beyond_the_limit(self):
        got, _db = _search(_world(_ef_fourth()), "EF-1", limit=8)
        ef1 = [r for r in got if r.get("record_type") == "glyph" and r.get("label") == "EF-1"]
        self.assertEqual(len(ef1), 16)

    def test_the_census_is_a_separate_count_documents(self):
        _present()
        got, db = _search(_world(_ef_fourth()), "EF-1", limit=8)
        census = [r for r in got if r.get("record_type") == S.GLYPH_CENSUS]
        fam = [c for c in census if c.get("family") == EF]
        self.assertEqual([c["count"] for c in fam], [16])
        self.assertTrue(any(f.get("$or") == [{"label": {"$in": ["EF-1", "EF-2"]}},
                                             {"payload.family": EF}]
                            for f in db.plan_records.counted),
                        "the census was not asked of the database")

    def test_it_binds_when_every_row_is_in_hand(self):
        got, _db = _search(_world(_ef_fourth()), "EF-1", limit=8)
        self.assertTrue(_ok("There are 16 EF-1 on the fourth floor.", got))
        self.assertTrue(_ok("There are 16 EF-1.", got))        # nothing refused
        self.assertTrue(_ok("Each unit on the fourth floor has 4 EF-1.", got))

    def test_a_partial_count_is_not_a_total(self):
        got, _db = _search(_world(_ef_fourth()), "EF-1", limit=8)
        for n in list(range(1, 16)) + [17]:
            self.assertFalse(_ok(f"There are {n} EF-1.", got), n)
            self.assertFalse(_ok(f"There are {n} EF-1 on the fourth floor.", got), n)


class TheCensusIsNotTheFetch(unittest.TestCase):

    def test_a_fetch_cut_short_refuses(self):
        """The fetch is capped at 8; count_documents is not. If the census
        were computed from the fetch, 8 would read as complete."""
        _present()
        got, _db = _search(_world(_ef_fourth()), "EF-1", limit=8, fetch_cap=8)
        self.assertEqual(sum(1 for r in got if r.get("label") == "EF-1"
                             and r.get("record_type") == "glyph"), 8)
        self.assertFalse(_ok("There are 8 EF-1.", got))
        self.assertFalse(_ok("There are 16 EF-1.", got))
        self.assertFalse(_ok("There are 8 EF-1 on the fourth floor.", got))

    def test_eight_handed_to_the_gate_with_a_census_of_sixteen_refuses(self):
        _present()
        rows = _numbered(_ef_fourth())
        census = _census(rows, _pages(rows), {EF: ["EF-1", "EF-2"]})
        self.assertEqual(census[0]["count"], 16)
        half = rows[:8] + census
        for n in (8, 16, 2):
            self.assertFalse(_ok(f"There are {n} EF-1.", half), n)
            self.assertFalse(_ok(f"There are {n} EF-1 on the fourth floor.", half), n)
        self.assertTrue(_ok("There are 16 EF-1 on the fourth floor.", rows + census))

    def test_rows_with_no_census_bind_nothing(self):
        """What the old gate did: count whatever it was handed."""
        _present()
        rows = _numbered(_ef_fourth())
        self.assertFalse(_ok("There are 16 EF-1.", rows))
        self.assertFalse(_ok("There are 16 EF-1 on the fourth floor.", rows))

    def test_the_mongo_filter_and_the_python_predicate_agree(self):
        """The gate counts rows in hand with glyph_in_census; the database
        counts with the filter. Equal counts prove equal sets only if both
        select the same rows - including the rows they must NOT select."""
        _present()
        rows = _numbered(_ef_fourth(1) + _floor("102", SAF, [("SAF-1", "3A")])
                         + _floor("102", EF, [("EF-2", "3B")], status="unread")
                         + [_refusal("M-104.00", "no units")])
        stray = [dict(rows[0], project_id="p2"), dict(rows[1], page_id="pg-old"),
                 dict(rows[2], tier="vision_read"), dict(rows[3], record_type="element"),
                 dict(rows[0], label="PTAC-1", payload={"family": "PTAC"}),
                 dict(rows[-1], unit="4D")]
        world = rows + stray
        pages = _pages(rows)
        for kind, fam, tags, flt in (
                ("family", EF, ["EF-1", "EF-2"], S.glyph_family_filter(PID, pages, EF, ["EF-1", "EF-2"])),
                ("family", SAF, ["SAF-1"], S.glyph_family_filter(PID, pages, SAF, ["SAF-1"])),
                ("refusals", None, [], S.glyph_refusal_filter(PID, pages))):
            c = S.glyph_census(kind, PID, pages, 0, family=fam, tags=tags)
            by_db = [i for i, r in enumerate(world) if _match(r, flt)]
            by_py = [i for i, r in enumerate(world) if S.glyph_in_census(r, c)]
            self.assertEqual(by_db, by_py, kind + str(fam))
            self.assertTrue(by_db, kind + str(fam))


class ARefusalOnTheFloorRefuses(unittest.TestCase):

    def _records(self, *extra):
        rows = _numbered(_ef_fourth() + list(extra))
        return rows + _census(rows, _pages(rows), {EF: ["EF-1", "EF-2"]})

    def test_a_refused_sheet_on_the_floor_refuses_the_floor(self):
        _present()
        recs = self._records(_refusal("M-103.00", "registration failed",
                                      "FOURTH FLOOR HVAC PLANS"))
        self.assertFalse(_ok("There are 16 EF-1 on the fourth floor.", recs))
        self.assertFalse(_ok("Each unit on the fourth floor has 4 EF-1.", recs))
        self.assertFalse(_ok("4A has 4 EF-1.", recs))

    def test_a_refusal_row_missing_from_hand_refuses_everything(self):
        _present()
        rows = _numbered(_ef_fourth() + [_refusal("M-104.00", "no units")])
        census = _census(rows, _pages(rows), {EF: ["EF-1", "EF-2"]})
        no_refusal = [r for r in rows if not r["unit"].startswith("sheet:")] + census
        self.assertFalse(_ok("There are 16 EF-1 on the fourth floor.", no_refusal))


class ABuildingTotalWithAnySheetRefusedRefuses(unittest.TestCase):

    def test_a_refusal_on_another_floor(self):
        _present()
        rows = _numbered(_ef_fourth() + [_refusal("M-104.00", "A-104.00: no units")])
        recs = rows + _census(rows, _pages(rows), {EF: ["EF-1", "EF-2"]})
        self.assertFalse(_ok("There are 16 EF-1.", recs))
        self.assertFalse(_ok("There are 16 exhaust fans.", recs))
        self.assertFalse(_ok("Each unit has 4 EF-1.", recs))
        # ...while the floor it does not touch still binds
        self.assertTrue(_ok("There are 16 EF-1 on the fourth floor.", recs))
        self.assertFalse(_ok("There are 16 EF-1 on the mezzanine floor.", recs))

    def test_a_refused_sheet_on_no_floor(self):
        """Another architect's A.1.x or an unnumbered page: it belongs to no
        floor, and the building is not complete without it."""
        _present()
        rows = _numbered(_ef_fourth() + [_refusal("A.1.4", "no mechanical partner",
                                                  "FLOOR PLAN")])
        recs = rows + _census(rows, _pages(rows), {EF: ["EF-1", "EF-2"]})
        self.assertFalse(_ok("There are 16 EF-1.", recs))
        self.assertTrue(_ok("There are 16 EF-1 on the fourth floor.", recs))


class FanIsTwoFamiliesAndNeverOneTotal(unittest.TestCase):
    """EF: 8 on the fourth floor (2 per unit). SAF: 2 on the fourth floor."""

    def setUp(self):
        _present()
        ef = _floor("103", EF, [(t, u) for u in ("4A", "4B", "4C", "4D")
                                for t in ("EF-1", "EF-2")])
        saf = _floor("103", SAF, [("SAF-1", "4A"), ("SAF-1", "4C")])
        self.got, _db = _search(_world(ef, saf), "fan", limit=8)

    def test_both_families_are_fetched_for_fan(self):
        fams = {c["family"] for c in self.got
                if c.get("record_type") == S.GLYPH_CENSUS and c["kind"] == "family"}
        self.assertEqual(fams, {EF, SAF})

    def test_fans_alone_binds_neither_and_never_the_sum(self):
        for n in (8, 2, 10):
            self.assertFalse(_ok(f"There are {n} fans on the fourth floor.", self.got), n)
            self.assertFalse(_ok(f"There are {n} fans.", self.got), n)

    def test_each_family_by_its_own_name(self):
        self.assertTrue(_ok("There are 8 exhaust fans on the fourth floor.", self.got))
        self.assertTrue(_ok("There are 2 SAF-1 on the fourth floor.", self.got))
        self.assertTrue(_ok("Each unit on the fourth floor has 2 exhaust fans.", self.got))

    def test_the_combined_figure_never_binds(self):
        for s in ("There are 10 exhaust fans on the fourth floor.",
                  "There are 10 SAF-1 on the fourth floor.",
                  "There are 10 fans on the fourth floor.",
                  "There are 10 EF-1 and SAF-1 on the fourth floor."):
            self.assertFalse(_ok(s, self.got), s)

    def test_the_render_is_per_family(self):
        text = S.render_glyph_evidence(self.got)
        self.assertIn(f"{EF} (EF-1, EF-2):", text)
        self.assertIn(f"{SAF} (SAF-1):", text)
        self.assertNotIn("10", S._values(text))       # never EF + SAF
        self.assertNotIn("0", S._values(text))        # a zero is not a figure


class ScopeIsWhatTheClauseNames(unittest.TestCase):

    def setUp(self):
        _present()
        rows = _numbered(_floor("103", EF, [(t, u) for u in ("4A", "4B", "4C", "4D")
                                            for t in ("EF-1", "EF-2")])
                         + _floor("102", EF, [("EF-1", "3A"), ("EF-1", "3A"),
                                              ("EF-1", "3B")])
                         + [_refusal("M-104.00", "A-104.00: no units")])
        self.recs = rows + _census(rows, _pages(rows), {EF: ["EF-1", "EF-2"]})

    def test_a_unit(self):
        self.assertTrue(_ok("4A has 1 EF-1 and 1 EF-2.", self.recs))
        self.assertTrue(_ok("4A has 2 exhaust fans.", self.recs))
        self.assertFalse(_ok("4A has 8 exhaust fans.", self.recs))

    def test_a_uniform_per_unit_figure_only_where_it_is_uniform(self):
        self.assertTrue(_ok("Each unit on the fourth floor has 2 exhaust fans.", self.recs))
        self.assertFalse(_ok("Each unit on the fourth floor has 8 exhaust fans.", self.recs))
        self.assertFalse(_ok("Each unit on the third floor has 2 EF-1.", self.recs))
        self.assertFalse(_ok("Each unit on the third floor has 1 EF-1.", self.recs))

    def test_a_level_nothing_maps_to_does_not_fall_back(self):
        self.assertFalse(_ok("The ninth floor has 8 exhaust fans.", self.recs))
        self.assertFalse(_ok("Each floor has 8 exhaust fans.", self.recs))
        self.assertFalse(_ok("Apartment 4A on the third floor has 2 exhaust fans.", self.recs))
        self.assertFalse(_ok("9Z has 2 exhaust fans.", self.recs))

    def test_a_cited_plan_sheet_is_the_floor(self):
        self.assertTrue(_ok("There are 4 EF-1 [M-103.00].", self.recs))
        self.assertFalse(_ok("There are 3 EF-1 [M-103.00].", self.recs))
        self.assertTrue(_ok("There are 3 EF-1 on A-102.00.", self.recs))

    def test_an_unplaced_symbol_withholds_the_split_not_the_floor(self):
        rows = _numbered(_floor("103", EF, [("EF-1", u) for u in ("4A", "4B", "4C")]
                                + [("EF-1", None)]))
        recs = rows + _census(rows, _pages(rows), {EF: ["EF-1", "EF-2"]})
        self.assertTrue(_ok("There are 4 EF-1 on the fourth floor.", recs))
        self.assertFalse(_ok("Each unit on the fourth floor has 1 EF-1.", recs))
        self.assertFalse(_ok("4A has 1 EF-1.", recs))


class AGlyphRowVouchesForNothingElse(unittest.TestCase):

    def setUp(self):
        _present()
        rows = _numbered(_ef_fourth())
        self.recs = rows + _census(rows, _pages(rows), {EF: ["EF-1", "EF-2"]})

    def test_its_payload_is_not_a_source_of_numbers(self):
        # 56 is the widest door, 908 the anchors, 50 the printed rating, 16
        # the census; none is about anything an attribute answer could ask.
        for n in (56, 908, 50, 16, 9):
            self.assertFalse(S.answer_is_grounded(f"The door is {n} inches.",
                                                  self.recs)[0], n)
            self.assertFalse(_ok(f"There are {n} doors.", self.recs), n)

    def test_its_tag_is_not_a_vision_label(self):
        self.assertEqual(S.contains_label("Each unit has 4 EF-1.", self.recs), [])

    def test_the_model_is_shown_counts_not_rows(self):
        text = server._render_records_for_model(self.recs, "EF-1")
        self.assertNotIn("EF-1(50)", text)
        self.assertIn("EF-1 16", text)
        self.assertIn("each unit (4A, 4B, 4C, 4D) has 4", text)


if __name__ == "__main__":
    unittest.main()
