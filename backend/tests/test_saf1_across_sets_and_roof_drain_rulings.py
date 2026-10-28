"""SAF-1 ACROSS THE SETS (item 18) AND THE ROOF DRAINS' RULINGS 13, 14, 15.

Rulings (operator, 2026-10-28), verbatim, with the questions they answer:

  18  "18 YES, own PR (SAF-1 bulkhead refusal across sets); stops for Roy
      only if anything other than SAF-1/RD changes."
  13  "The label 'no schedule lists them' isn't literally true: P-400 lists
      RD-1 and RD-2 without a count." - 'yes: "no schedule prints their
      quantity"'.
  14  "Can 'the roof' name where RD-1 and RD-2 are?" - "yes, only the level
      the plan's title names".
  15  "Should 'J.R. Smith', 'detention' or 'controlled-flow' refer to
      RD-1?" - "yes, SD1-2's own words".

Measured on production, read-only, 2026-10-28 (the v9 rows, 459):

  - Asked about SAF-1, search_plans returns the filed track's SAF-1 row on
    M-106.00 (BULKHEAD HVAC PLANS) and its 8 refusal rows, beside a census
    per track: FAN SCHEDULE filed 1, post_co 0; refusals filed 8, post_co 0.
    Read as one book that is "two censuses for one schedule": "The bulkhead
    has 1 SAF-1." refuses. "There is 1 SAF-1." binds only through the
    schedule's QTY cell (1), never the located count.
  - The owner's (post_co) track's pass reads 12 pages: A-100.00..A-105.00
    and M-100.00..M-105.00. NOT M-106.00 - M-106 has no A-106
    (server._glyph_track_pages). The filed track reads it.
  - Asked about "supply air fan" (which also fetches the exhaust fans, rows
    of both tracks), the same claim BINDS: glyph_books already lets a track
    that located none of a family stand aside when both tracks' rows are in
    hand. The answer depended on which other rows came back.
  - SD1-2 p4 prints, in RD-1's line, "J.R. Smith" and "Detention";
    "controlled flow" only in another note, "Roof flow of 0.332cfs will be
    restricted to 0.016cfs by means of controlled flow device & roof
    detention." - which names no roof drain.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_emit as E  # noqa: E402
from lib import plan_search as S  # noqa: E402
from tests.test_roof_drains_count_per_tag import (  # noqa: E402
    FAM, PID, SD12, TAGS, _P, _records as _rd_records, _rows as _rd_rows, _set_records)

FAN = "FAN SCHEDULE"
M106 = {"project_id": PID, "company_id": "c", "file_id": "f-mh", "file_hash": "h",
        "file_name": "MH - 7.2.26.pdf", "page_id": "pg-m106", "page_number": 8,
        "sheet_number": "M-106.00", "sheet_title": "BULKHEAD HVAC PLANS",
        "discipline": "mechanical"}
#: what each track's pass reads (server._glyph_track_pages), as measured
FILED_READS = {"pages": ["pg-a100", "pg-m100", "pg-m105", "pg-m106", "pg-p206"],
               "sheets": ["A-100.01", "M-100.00", "M-105.00", "M-106.00", "P-206.00"]}
OWNER_READS = {"pages": ["pg-a100o", "pg-m100", "pg-m105"],
               "sheets": ["A-100.00", "A-105.00", "M-100.00", "M-105.00"]}
REFUSED = ["A.1.1", "A.1.2", "A.1.3", "A.1.4", "A.1.5", "A.1.6", "A.1.7"]


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


def _saf1_rows():
    res = {"records": [{"tag": "SAF-1", "unit": None, "glyph_status": "resolved",
                        "placement": "refused", "how": "refused: sheet scope",
                        "reason": "refused: M-106.00 has no architectural partner A-106",
                        "label_at": (1189, 900), "label_box": (1170, 894, 1208, 906),
                        "label_text": "SAF-1", "symbol_at": (1189, 930),
                        "symbol_bbox": None, "at_arch": None}]}
    rows = E.glyph_rows(res, mech=M106, arch=None, family=FAN,
                        pass_key=f"filed|M-106.00|{FAN}",
                        units={"tags": [], "method": "sheet_scope", "zero_units": False,
                               "multi_level": {}},
                        widest_door={"inches": 56.0}, mech_count=1)
    for r in rows:
        r["payload"]["track"] = "filed"
    return rows


def _refusals(track="filed"):
    return [{"project_id": PID, "company_id": "c", "page_id": f"pg-{s}", "ordinal": 0,
             "record_type": "glyph", "tier": S._GLYPH_TIER, "sheet_number": s,
             "sheet_title": "FLOOR PLAN", "label": None, "unit": f"sheet:{s}",
             "glyph_status": "unsupported_unit",
             "payload": {"role": "architectural", "family": None, "track": track,
                         "refusal": f"{s} is a plan with no mechanical partner by sheet number"}}
            for s in REFUSED]


def _census(kind, pages, count, track, reads=None, **kw):
    """glyph_census, with what the track reads set as the census carries it
    (glyph_census(reads=) is checked on its own below)."""
    c = S.glyph_census(kind, PID, pages, count, track=track, **kw)
    if reads is not None:
        c["reads"] = {"pages": sorted(reads["pages"]), "sheets": sorted(reads["sheets"])}
    return c


def _saf1_records(owner_reads=OWNER_READS, owner_count=0, owner_refusals=0,
                  filed_reads=FILED_READS, extra_families=()):
    """As search_plans hands a SAF-1 question over on production: the
    family's rows (the filed track's alone), every refusal row, and a census
    of each per track."""
    rows = _saf1_rows() + _refusals()
    pages = sorted({r["page_id"] for r in rows} | {"pg-m100", "pg-a100o"})
    out = list(rows)
    fams = [(FAN, ["SAF-1"], {"SAF-1": "1"})] + list(extra_families)
    for name, tags, qty in fams:
        for track, reads, n in (("filed", filed_reads, None), ("post_co", owner_reads, owner_count)):
            c = _census("family", pages, 0, track, reads, family=name, tags=tags, qty=qty)
            c["count"] = sum(S.glyph_in_census(r, c) for r in rows) if n is None else n
            out.append(c)
    ref = _census("refusals", pages, 0, "filed")
    ref["count"] = sum(S.glyph_in_census(r, ref) for r in rows)
    out += [ref, _census("refusals", pages, owner_refusals, "post_co")]
    return out


# ══════════════════════════════════════════════════════════════════════════
# 18: a track that does not read a sheet does not veto its family total
# ══════════════════════════════════════════════════════════════════════════

class Saf1AcrossTheSets(unittest.TestCase):

    def test_the_bulkhead_has_1_saf1_binds(self):
        recs = _saf1_records()
        for s in ("The bulkhead has 1 SAF-1.", "There is 1 SAF-1.", "SAF-1: 1.",
                  "There is 1 SAF-1 in the filed set.",
                  "The bulkhead has 1 SAF-1 in the filed set."):
            self.assertTrue(_ok(s, recs), s)
        out = S.render_glyph_evidence(recs)
        self.assertIn("BULKHEAD HVAC PLANS [M-106.00]: SAF-1 1", out)
        self.assertIn("SAF-1 1 (agrees with the schedule's QTY 1)", out)
        self.assertNotIn("two censuses", out)

    def test_wrong_figures_and_other_scopes_still_refuse(self):
        recs = _saf1_records()
        self.assertTrue(_ok("The bulkhead has 1 SAF-1.", recs), "the bulkhead figure must bind here")
        for s in ("The bulkhead has 2 SAF-1.", "There are 2 SAF-1.", "The roof has 1 SAF-1.",
                  "The mezzanine has 1 SAF-1.", "The bulkhead has 0 SAF-1.",
                  "There is 1 SAF-1 per the owner's set.", "Each unit has 1 SAF-1."):
            self.assertFalse(_ok(s, recs), s)

    def test_a_track_that_reads_the_sheet_and_counts_none_still_refuses(self):
        """Counting none of a sheet it reads is a difference between the sets,
        not a gap: the rule is about NOT READING, not about zero."""
        self.assertTrue(_ok("The bulkhead has 1 SAF-1.", _saf1_records()))
        by_sheet = {"pages": OWNER_READS["pages"], "sheets": OWNER_READS["sheets"] + ["M-106.00"]}
        by_page = {"pages": OWNER_READS["pages"] + ["pg-m106"], "sheets": OWNER_READS["sheets"]}
        for reads in (by_sheet, by_page):
            recs = _saf1_records(owner_reads=reads)
            for s in ("The bulkhead has 1 SAF-1.", "There is 1 SAF-1 in the filed set."):
                self.assertFalse(_ok(s, recs), (s, reads))
            self.assertIn("two censuses for one schedule", S.render_glyph_evidence(recs))

    def test_a_census_that_does_not_say_what_its_track_reads_refuses(self):
        self.assertTrue(_ok("The bulkhead has 1 SAF-1.", _saf1_records()))
        recs = _saf1_records(owner_reads=None)
        self.assertFalse(_ok("The bulkhead has 1 SAF-1.", recs))

    def test_an_owner_census_of_some_refuses(self):
        """Rows of the family the owner's track holds, and none came back."""
        self.assertTrue(_ok("The bulkhead has 1 SAF-1.", _saf1_records()))
        self.assertFalse(_ok("The bulkhead has 1 SAF-1.", _saf1_records(owner_count=1)))

    def test_the_other_tracks_refusals_must_be_none(self):
        self.assertTrue(_ok("The bulkhead has 1 SAF-1.", _saf1_records()))
        self.assertFalse(_ok("The bulkhead has 1 SAF-1.", _saf1_records(owner_refusals=1)))

    def test_a_family_with_no_rows_is_unchanged(self):
        """DH-1 (M-106.00, read as 'DH-1. DUCT HEATER') has no row on either
        track: nothing lies on a sheet the owner's track does not read, so its
        two censuses stay two. Its QTY binds at building scope, as before."""
        recs = _saf1_records(extra_families=[("DUCT ELECTRIC HEATER", ["DH-1"], {"DH-1": "1"})])
        self.assertTrue(_ok("The bulkhead has 1 SAF-1.", recs), "SAF-1 binds beside it")
        self.assertEqual(S.glyph_books(recs).totals.families["DUCT ELECTRIC HEATER"].why,
                         "two censuses for one schedule")
        self.assertIn("DUCT ELECTRIC HEATER (DH-1): the schedule prints QTY DH-1 1; its symbols "
                      "were not located.", S.render_glyph_evidence(recs))
        self.assertTrue(_ok("There is 1 DH-1.", recs))
        for s in ("The bulkhead has 1 DH-1.", "There are 0 DH-1."):
            self.assertFalse(_ok(s, recs), s)

    def test_the_census_carries_what_its_track_reads(self):
        assert "reads" in inspect.signature(S.glyph_census).parameters, \
            "the census cannot say what a track reads in this tree"
        c = S.glyph_census("family", PID, ["pg-m106"], 0, family=FAN, tags=["SAF-1"],
                           track="post_co", reads=OWNER_READS)
        self.assertEqual(c["reads"], {"pages": sorted(OWNER_READS["pages"]),
                                      "sheets": sorted(OWNER_READS["sheets"])})
        self.assertNotIn("reads", S.glyph_census("refusals", PID, ["pg-m106"], 0, track="filed"))


class TheServerSaysWhatEachTrackReads(unittest.TestCase):
    """server._glyph_evidence, on a fake database shaped as production."""

    def _evidence(self, pages_fn):
        import server
        from tests.async_fake_mongo import AsyncFakeDB
        db = AsyncFakeDB()
        db.plan_records.docs.append({
            "project_id": PID, "record_type": "schedule", "page_id": "pg-m200",
            "sheet_number": "M-200.00", "tier": "ocr_grid_cell",
            "payload": {"name": FAN, "columns": [{"header": "MARK", "role": "identifier"},
                                                 {"header": "QTY", "role": "quantity"}],
                        "rows": [["SAF-1", "1"]]}})
        for r in _saf1_rows() + _refusals():
            db.plan_records.docs.append(dict(r))
        # a row of the owner's track elsewhere: the project has two tracks
        other = dict(_refusals("post_co")[0], page_id="pg-a100o", sheet_number="A-100.00",
                     unit=None, glyph_status="resolved", label="EF-1")
        other["payload"] = dict(other["payload"], family="EXHAUST FAN SCHEDULE", role=None)
        db.plan_records.docs.append(other)

        async def page_ids(_pid):
            return sorted({d["page_id"] for d in db.plan_records.docs} | {"pg-m100"})
        with patch.object(server, "db", db), patch.object(server, "_glyph_page_ids", page_ids), \
                patch.object(server, "_glyph_pages", pages_fn):
            return asyncio.run(server._glyph_evidence(PID, "SAF-1"))

    @staticmethod
    async def _pages(_pid):
        return ([("filed", [{"_id": p, "sheet_number": s} for p, s in
                            zip(FILED_READS["pages"], FILED_READS["sheets"])]),
                 ("post_co", [{"_id": p, "sheet_number": s} for p, s in
                              zip(OWNER_READS["pages"] + [None], OWNER_READS["sheets"])])], {})

    def test_the_bulkhead_figure_binds_through_the_server(self):
        got = self._evidence(self._pages)
        fam = [c for c in got if c.get("record_type") == S.GLYPH_CENSUS and c.get("family") == FAN]
        self.assertEqual(sorted((c["track"], c["count"]) for c in fam), [("filed", 1), ("post_co", 0)])
        owner = next(c for c in fam if c["track"] == "post_co")
        self.assertNotIn("M-106.00", (owner.get("reads") or {}).get("sheets", ["M-106.00"]),
                         "the owner's census does not say what its track reads")
        self.assertTrue(_ok("The bulkhead has 1 SAF-1.", got))

    def test_unknown_reads_refuse_as_before(self):
        self.assertTrue(_ok("The bulkhead has 1 SAF-1.", self._evidence(self._pages)),
                        "with what each track reads, the bulkhead figure binds")

        async def boom(_pid):
            raise RuntimeError("index unreadable")
        got = self._evidence(boom)
        self.assertTrue(all("reads" not in c for c in got if c.get("record_type") == S.GLYPH_CENSUS))
        self.assertFalse(_ok("The bulkhead has 1 SAF-1.", got))
        self.assertEqual(S.glyph_books(got).totals.families[FAN].why, "two censuses for one schedule")


# ══════════════════════════════════════════════════════════════════════════
# The roof drains: rulings 13, 14, 15
# ══════════════════════════════════════════════════════════════════════════

def _rd_two_tracks(set_records=None, rows=None):
    """Roof drains as production hands them over: the filed rows, a census
    per track (the owner's track reads no P sheet), and the naming records."""
    P = _P()
    recs = _rd_records(rows=rows, set_records=set_records)
    fam = P.families(_set_records() if set_records is None else set_records).get(FAM)
    c = next(r for r in recs if r.get("record_type") == S.GLYPH_CENSUS and r.get("family") == FAM)
    recs.append(_census("family", c["page_ids"], 0, "post_co", OWNER_READS,
                        family=FAM, tags=TAGS, plan_only=fam))
    recs.append(_census("refusals", c["page_ids"], 0, "post_co"))
    return recs


class Ruling13TheLabel(unittest.TestCase):

    def test_the_render_says_no_schedule_prints_their_quantity(self):
        P = _P()
        self.assertEqual(P.label(["P-206.00"]), "located on P-206.00; no schedule prints their quantity")
        out = S.render_glyph_evidence(_rd_two_tracks())
        self.assertIn("RD-1 2 + RD-2 2 (located on P-206.00; no schedule prints their quantity)", out)
        self.assertNotIn("no schedule lists them", out)

    def test_the_eval_case_states_it(self):
        suite = json.loads((Path(__file__).resolve().parents[1] / "eval" / "boyland.json")
                           .read_text(encoding="utf-8"))
        case = next(c for c in suite["cases"] if c["id"] == "roof-drain-count")
        self.assertEqual(case["expect"]["located_render"],
                         ["RD-1 2 + RD-2 2", "located on P-206.00; no schedule prints their quantity"])


class Ruling14TheRoofIsThePlansOwnLevel(unittest.TestCase):

    def test_the_roof_binds(self):
        recs = _rd_two_tracks()
        for s in ("The roof has 2 RD-1.", "The roof has 2 RD-2.", "The roof has 2 overflow roof drains.",
                  "The roof level has 2 RD-1.", "On the roof there are 2 RD-1 and 2 RD-2."):
            self.assertTrue(_ok(s, recs), s)

    def test_any_other_level_refuses(self):
        recs = _rd_two_tracks()
        self.assertTrue(_ok("The roof has 2 RD-1.", recs), "the roof must bind here")
        for s in ("The fourth floor has 2 RD-1.", "The mezzanine has 2 RD-1.",
                  "The bulkhead has 2 RD-1.", "The second floor has 2 RD-2.",
                  "The roof and the fourth floor have 2 RD-1.", "The roof has 3 RD-1.",
                  "The roof has 4 roof drains.", "The roof has 2 roof drains.",
                  "Each unit on the roof has 2 RD-1."):
            self.assertFalse(_ok(s, recs), s)

    def test_only_the_level_the_plans_title_prints(self):
        """A plan whose title names no level gives a clause none to name."""
        self.assertTrue(_ok("The roof has 2 RD-1.", _rd_two_tracks()), "the roof must bind here")
        rows = _rd_rows()
        for r in rows:
            r["sheet_title"] = "SANITARY & STORM PLAN"
        recs = _rd_two_tracks(rows=rows)
        self.assertTrue(_ok("There are 2 RD-1.", recs))
        self.assertFalse(_ok("The roof has 2 RD-1.", recs))

    def test_the_render_names_the_one_level(self):
        out = S.render_glyph_evidence(_rd_two_tracks())
        self.assertIn("the only level it may be said of is the roof (its plan's title)", out)


class Ruling15Sd12sOwnWords(unittest.TestCase):

    def test_rd1_goes_by_the_words_its_note_prints(self):
        P = _P()
        fam = P.families(_set_records())[FAM]
        self.assertEqual(fam.get("also"), {"RD-1": ["J.R. Smith", "detention"]},
                         "SD1-2 prints 'J.R. Smith' and 'Detention' in RD-1's line, not 'controlled-flow'")

    def test_those_names_bind_rd1s_figure(self):
        recs = _rd_two_tracks()
        for s in ("There are 2 J.R. Smith roof drains.", "There are 2 JR Smith drains.",
                  "There are 2 detention drains.", "There are 2 detention roof drains.",
                  "The roof has 2 J.R. Smith roof drains."):
            self.assertTrue(_ok(s, recs), s)
        for s in ("There are 3 J.R. Smith roof drains.", "There are 4 detention drains.",
                  "There are 2 controlled-flow roof drains.", "There are 2 controlled flow drains.",
                  "There are 2 special purpose drains.", "The fourth floor has 2 detention drains."):
            self.assertFalse(_ok(s, recs), s)

    def test_the_controlled_flow_note_names_no_drain(self):
        """SD1-2 p3 and p4 print 'controlled flow device & roof detention' in
        a note that names no roof drain: it lends RD-1 no name."""
        P = _P()
        flow = "2. Note: Roof flow of 0.332cfs will be restricted to 0.016cfs by means of " \
               "controlled flow device & roof detention."
        recs = _set_records() + [{"record_type": "note", "tier": "text_layer", "sheet_number": "1 OF 1",
                                  "file_name": "SD1-2 - 4.1.25.pdf", "page_number": 4, "quote": flow}]
        self.assertEqual(P.families(recs)[FAM].get("also"), {"RD-1": ["J.R. Smith", "detention"]})

    def test_a_vision_read_names_nothing(self):
        P = _P()
        seen = {"record_type": "note", "tier": "vision_read", "sheet_number": "F",
                "file_name": "SD1-2 - 4.1.25.pdf", "page_number": 3,
                "quote": "2 controlled-flow roof drains"}
        sets = _set_records() + [seen]
        self.assertEqual(P.families(sets)[FAM].get("also"), {"RD-1": ["J.R. Smith", "detention"]})
        recs = _rd_two_tracks(set_records=sets)
        self.assertTrue(_ok("There are 2 J.R. Smith roof drains.", recs))
        self.assertFalse(_ok("There are 2 controlled-flow roof drains.", recs))

    def test_a_name_counts_only_where_it_is_printed(self):
        """The same candidate, printed by a text-layer note giving RD-1's
        figure, names RD-1 - the rule is what the set prints, not a list."""
        P = _P()
        printed = {"record_type": "note", "tier": "text_layer", "sheet_number": "P-400.00",
                   "file_name": "PL - 6.29.26.pdf", "page_number": 20,
                   "quote": "2 controlled-flow roof drains"}
        sets = _set_records() + [printed]
        self.assertEqual(P.families(sets)[FAM].get("also"),
                         {"RD-1": ["J.R. Smith", "detention", "controlled-flow"]})
        self.assertTrue(_ok("There are 2 controlled-flow roof drains.", _rd_two_tracks(set_records=sets)))

    def test_no_note_no_names(self):
        P = _P()
        self.assertTrue(_ok("There are 2 J.R. Smith roof drains.", _rd_two_tracks()),
                        "with SD1-2's note, its name binds")
        sets = _set_records(note=False)
        self.assertEqual(P.families(sets)[FAM].get("also", {}), {})
        recs = _rd_two_tracks(set_records=sets)
        self.assertTrue(_ok("RD-1: 2.", recs))
        self.assertFalse(_ok("There are 2 J.R. Smith roof drains.", recs))

    def test_the_census_and_the_render_carry_them(self):
        P = _P()
        fam = P.families(_set_records())[FAM]
        c = S.glyph_census("family", PID, ["p206"], 4, family=FAM, tags=TAGS, track="filed",
                           plan_only=fam)
        self.assertEqual(c["plan_only"].get("also"), {"RD-1": ["J.R. Smith", "detention"]})
        self.assertIn("RD-1 (also 'J.R. Smith', 'detention', as its note prints)",
                      S.render_glyph_evidence(_rd_two_tracks()))


class TheRestIsUnchanged(unittest.TestCase):

    def test_roof_drains_bind_per_tag_beside_the_owners_census(self):
        recs = _rd_two_tracks()
        self.assertTrue(_ok("RD-1: 2. RD-2: 2.", recs))
        self.assertFalse(_ok("There are 4 roof drains.", recs))
        self.assertTrue(_ok("The roof has 2 RD-1.", recs), "ruling 14")


if __name__ == "__main__":
    unittest.main()
