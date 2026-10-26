"""THE SET SAYS WHAT IT LACKS - AND NO FAMILY IS SKIPPED SILENTLY.

Rulings (operator, 2026-10-26, PR 5), measured on 588 Boyland first:
  - a schedule with no identifier column is recorded "schedule present, no
    identifier column, not reconciled", and every claim about it refuses with
    that reason (the diffuser schedule: its A1/A2 come only from a vision
    read, which is not schedule truth);
  - a plan tag no schedule lists: only that tag's claims refuse; a schedule
    tag never located: "not located"; neither refuses another family;
  - a tag inside a prose note ("DH-1. DUCT HEATER") is a mention: recorded,
    bound to its schedule row, never counted;
  - a sheet counts as REFERENCED only in reference context - "SEE X", "REFER
    TO X", "ON X", a drawing-list row, X inside a callout bubble. Bare
    mentions (ASTM A-446, ASTM C-955, the paint colour OC-152) count for
    nothing, and there is no stoplist. A missing referenced sheet is a
    warning on the referencing sheet;
  - duplicate sheet numbers and a mechanical plan with no architectural
    partner refuse only the claims that depend on them (M-106.00 narrow:
    its sheet-scope totals still bind).
Measured: exactly seven missing sheets (S-204, S-400, FO-101, FO-202, A-600,
EN-003, EN-004); no plan tag outside a schedule; DH-1 the only tag never
located; prose mentions of DH-1, EF-1 and EF-2; zero binding answers change.
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

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402
from lib import plan_search as S  # noqa: E402
from tests.fixture_pdfs import require as require_pdf  # noqa: E402

DIFF = "DIFFUSER & REGISTER SCHEDULE"


def _H():
    try:
        from lib import plan_set_health as H
    except ImportError:
        H = None
    assert H is not None and hasattr(S, "render_set_health"), \
        "the drawing set's health is not read in this tree"
    return H


def _ok(sentence, records):
    return S.answer_is_grounded(sentence, records, intent="count")[0]


# ── references in reference context ───────────────────────────────────────

class ReferenceContext(unittest.TestCase):

    def test_phrases_count(self):
        H = _H()
        for text, ref in (("SEE TYPICAL DETAIL ON S-204", "S-204"), ("NEW CONCRETE FOOTING SEE FO-101", "FO-101"),
                          ("FOR GENERAL NOTES AND TYPICAL DETAILS SEE S-400 DWG'S", "S-400"),
                          ("REFER TO SHEET A-301 FOR SECTIONS", "A-301")):
            self.assertIn(ref, H.text_references(text), text)

    def test_drawing_list_rows_count_only_under_a_drawing_list(self):
        H = _H()
        listed = "DRAWING LIST\n24 A-500\nWALL PARTITION TYPES\n25 A-600\nENLARGED STAIR DETAILS"
        self.assertEqual(H.text_references(listed).get("A-600"), "drawing list")
        self.assertNotIn("A-600", H.text_references("NOTES\n25 A-600\nENLARGED STAIR DETAILS"))

    def test_a_bubble_counts_and_the_same_word_outside_one_does_not(self):
        H = _H()
        circle = {"rect": (100.0, 100.0, 130.0, 130.0),
                  "items": [("c", (0, 0), (0, 0), (0, 0), (0, 0))] * 4}
        self.assertEqual(H.bubble_references([("FO-202", 115.0, 112.0)], [circle]), {"FO-202"})
        self.assertEqual(H.bubble_references([("FO-202", 300.0, 300.0)], [circle]), set())
        square = {"rect": (100.0, 100.0, 130.0, 130.0), "items": [("l", (0, 0), (1, 1))] * 4}
        self.assertEqual(H.bubble_references([("FO-202", 115.0, 112.0)], [square]), set())

    def test_bare_mentions_do_not_count(self):
        H = _H()
        for text in ("FORMED FROM STEEL THAT CONFORMS TO ASTM A-446 WITH A YIELD STRENGTH",
                     "BRIDGING SHALL BE MANUFACTURED PER ASTM SPECIFICATION C-955.",
                     "SUPER WHITE\nOC-152\nSENORA GRAY"):
            self.assertEqual(H.text_references(text), {}, text)

    def test_a_missing_sheet_is_a_warning_on_the_sheet_that_refers_to_it(self):
        H = _H()
        pages = [{"sheet_number": "S-101.00", "raw_text": "SEE S-400 DWG'S. SEE S-102 FOR FRAMING"},
                 {"sheet_number": "S-102.00", "raw_text": ""}]
        (w,) = H.missing_references(pages, {"S-101", "S-102"})
        self.assertEqual((w["kind"], w["sheet"], w["subject"]), (H.MISSING_REFERENCED_SHEET, "S-101.00", "S-400"))


class TheRealSheets(unittest.TestCase):
    """The local PDFs' own text and geometry (fixture PDFs): the seven real
    references are found and the three bare mentions are not."""

    def test_seven_real_three_false(self):
        H = _H()
        import pypdfium2 as pdfium
        from lib.plan_page import PlanPage
        pages = (("ST - 7.29.26.pdf", 3, "S-002.00"), ("ST - 7.29.26.pdf", 5, "S-101.00"),
                 ("ST - 7.29.26.pdf", 12, "S-302.00"), ("AR - 8.18.26.pdf", 1, "T-001.01"),
                 ("588 THOMAS BOYLAND ST SET_UPDATED.pdf", 8, "A.0.8"))
        found = {}
        for fn, n, sn in pages:
            path = str(require_pdf(fn))
            text = pdfium.PdfDocument(path)[n - 1].get_textpage().get_text_range()
            refs = dict(H.text_references(text))
            pg = PlanPage(path, n)
            try:
                for s in H.bubble_references(pg.directed_words, pg.drawings):
                    refs.setdefault(s, "callout bubble")
            finally:
                pg.close()
            for s, how in refs.items():
                found.setdefault(s, set()).add((sn, how))
        for ref, where in (("S-204", ("S-002.00", "phrase")), ("S-400", ("S-101.00", "phrase")),
                           ("FO-101", ("S-302.00", "phrase")), ("FO-202", ("S-101.00", "callout bubble")),
                           ("A-600", ("T-001.01", "drawing list")), ("EN-003", ("T-001.01", "drawing list")),
                           ("EN-004", ("T-001.01", "drawing list"))):
            self.assertIn(where, found.get(ref, set()), (ref, found.get(ref)))
        for bare in ("A-446", "C-955", "OC-152"):
            self.assertNotIn(bare, found, bare)


# ── tags on the mechanical plans ──────────────────────────────────────────

FAMS = {"EXHAUST FAN SCHEDULE": {"tags": ["EF-1", "EF-2"], "sheet": "M-200.00"},
        "DUCT ELECTRIC HEATER": {"tags": ["DH-1"], "sheet": "M-200.00"},
        DIFF: {"tags": [], "sheet": "M-200.00"}}


class TagsOnThePlans(unittest.TestCase):

    def test_a_tag_no_schedule_lists_is_recorded(self):
        H = _H()
        items = H.tag_reads("M-101.00", [("EF-1(50)", 10, 10), ("EF-3", 20, 20), ("EF-3", 30, 30)],
                            {k: v for k, v in FAMS.items() if v["tags"]})
        (o,) = [i for i in items if i["kind"] == H.PLAN_TAG_NOT_IN_SCHEDULE]
        self.assertEqual((o["subject"], o["sheet"]), ("EF-3", "M-101.00"))
        self.assertIn("printed 2 time(s)", o["detail"])

    def test_a_tag_in_prose_is_a_mention_bound_to_its_schedule_row(self):
        H = _H()
        items = H.tag_reads("M-106.00", [("DH-1. DUCT HEATER", 1189, 910), ("DH-1", 5, 5)],
                            {k: v for k, v in FAMS.items() if v["tags"]})
        (m,) = items
        self.assertEqual((m["kind"], m["subject"], m["family"], m["schedule_sheet"]),
                         (H.MENTIONED_UNLOCATED, "DH-1", "DUCT ELECTRIC HEATER", "M-200.00"))

    def test_a_schedule_tag_never_located(self):
        H = _H()
        (n,) = H.not_located({k: v for k, v in FAMS.items() if v["tags"]}, {"EF-1", "EF-2"})
        self.assertEqual((n["kind"], n["subject"]), (H.SCHEDULE_TAG_NOT_LOCATED, "DH-1"))
        self.assertIn("were not located", n["detail"])

    def test_no_family_is_skipped_silently(self):
        H = _H()
        (u,) = H.unreconciled(FAMS)
        self.assertEqual((u["kind"], u["subject"]), (H.FAMILY_NOT_RECONCILED, DIFF))
        self.assertIn("schedule present, no identifier column, not reconciled", u["detail"])


# ── the gate ──────────────────────────────────────────────────────────────

def _health(kind, subject, detail):
    return {"record_type": "set_health", "kind": kind, "subject": subject, "sheet": "M-200.00",
            "detail": detail}


class AFamilyNotReconciledIsNotCounted(unittest.TestCase):

    def test_a_diffuser_claim_refuses_with_the_reason(self):
        H = _H()
        recs = [_health(H.FAMILY_NOT_RECONCILED, DIFF, f"{DIFF}: {H.NOT_RECONCILED}")]
        for s in ("There are 12 diffusers.", "The second floor has 4 registers."):
            self.assertFalse(_ok(s, recs), s)
        self.assertIn(f"{DIFF}: schedule present, no identifier column, not reconciled - "
                      "state no count of these.", S.render_set_health(recs))

    def test_its_printed_quantities_lend_nothing(self):
        """A schedule with no identifier column that DOES print a QTY: today
        its 8 binds "There are 8 A1 diffusers."; it is no closed set, so it
        lends nothing. A mark the PTAC schedule also prints still binds."""
        H = _H()
        diff = {"project_id": "p1", "record_type": "schedule", "tier": "vision_read", "sheet_number": "M-200.00",
                "page_id": "pg", "payload": {"name": DIFF, "columns": [{"header": "SYMBOL", "role": None},
                                                                     {"header": "QTY", "role": "quantity"}],
                                             "rows": [["A1", "8"], ["A2", "4"]]}}
        ptac = {"project_id": "p1", "record_type": "schedule", "tier": "ocr_grid_cell", "sheet_number": "M-200.00",
                "page_id": "pg", "payload": {"name": "ROOMS PTAC UNITS SCHEDULE",
                                             "columns": [{"header": "UNIT NO.", "role": "identifier"},
                                                         {"header": "QTY", "role": "quantity"}],
                                             "rows": [["PTAC-1", "21"]]}}
        recs = [diff, ptac, _health(H.FAMILY_NOT_RECONCILED, DIFF, f"{DIFF}: {H.NOT_RECONCILED}"),
                _health(H.FAMILY_NOT_RECONCILED, "PTAC-1", f"PTAC-1: {H.NOT_RECONCILED}")]
        self.assertFalse(_ok("There are 8 A1 diffusers.", recs))
        self.assertFalse(_ok("There are 4 A2.", recs))
        self.assertTrue(_ok("There are 21 PTAC-1.", recs))

    def test_a_reconciled_family_with_a_shared_word_still_binds(self):
        """An OCR table named "PTAC-1" has no identifier column; the PTAC
        schedule does. A claim naming PTAC-1, or "PTAC units", is the PTAC
        schedule's, and binds as before."""
        H = _H()
        from tests.test_two_drawing_tracks import _world
        recs = _world() + [_health(H.FAMILY_NOT_RECONCILED, "PTAC-1", f"PTAC-1: {H.NOT_RECONCILED}")]
        self.assertTrue(_ok("There are 3 PTAC-1.", recs))
        self.assertTrue(_ok("The first floor has 5 PTAC units.", recs))

    def test_other_health_refuses_nothing_else(self):
        """An unlisted tag, a tag never located, a mention and a missing
        sheet: the reconciled figures bind as before."""
        H = _H()
        from tests.test_two_drawing_tracks import _world
        base = _world()
        recs = base + [_health(H.PLAN_TAG_NOT_IN_SCHEDULE, "PTAC-4", "PTAC-4 is printed 1 time(s) on M-100.00 but no schedule lists it"),
                       _health(H.SCHEDULE_TAG_NOT_LOCATED, "PTAC-9", "PTAC-9: not located"),
                       _health(H.MENTIONED_UNLOCATED, "PTAC-2", "PTAC-2 is mentioned in a note"),
                       _health(H.MISSING_REFERENCED_SHEET, "A-600", "T-001.01 refers to A-600")]
        for s in ("There are 3 PTAC-1.", "The first floor has 5 PTAC units.", "1B has 1 PTAC unit."):
            self.assertEqual(_ok(s, recs), _ok(s, base), s)
            self.assertTrue(_ok(s, recs), s)
        self.assertFalse(_ok("There is 1 PTAC-4.", recs))
        text = S.render_set_health(recs)
        self.assertIn("state no count of PTAC-4", text)
        self.assertIn("warning: T-001.01 refers to A-600", text)


# ── the server assembles it, and hands it to the gate ─────────────────────

class TheServer(unittest.TestCase):

    def test_set_health_is_assembled_from_the_pass(self):
        H = _H()
        tracks = [("filed", [{"_id": "pg-m106", "sheet_number": "M-106.00", "sheet_title": "BULKHEAD HVAC PLANS",
                              "raw_text": "", "file_name": "MH.pdf", "page_number": 8},
                             {"_id": "pg-t", "sheet_number": "T-001.01", "sheet_title": "COVER",
                              "raw_text": "DRAWING LIST\n24 T-001\nCOVER\n25 A-600\nENLARGED STAIR",
                              "file_name": "AR.pdf",
                              "page_number": 1},
                             {"_id": "pg-e1", "sheet_number": "EN-001.00", "file_name": "MH.pdf", "page_number": 12},
                             {"_id": "pg-e2", "sheet_number": "EN-001.00", "file_name": "PL.pdf", "page_number": 21}])]
        sched = [{"name": "DUCT ELECTRIC HEATER", "tier": "ocr_grid_cell", "sheet_number": "M-200.00",
                  "columns": [{"header": "MARK", "role": "identifier"}, {"header": "QTY", "role": "quantity"}],
                  "rows": [["DH-1", "1"]]},
                 {"name": DIFF, "tier": "ocr_grid_cell", "sheet_number": "M-200.00",
                  "columns": [{"header": "", "role": None}, {"header": "MODEL", "role": "model"}],
                  "rows": [["A1", "RSDB"]]}]
        items = server._glyph_set_health(tracks, [], sched, {"pg-m106": [("DH-1. DUCT HEATER", 1189, 910)]})
        kinds = {(i["kind"], str(i["subject"])) for i in items}
        for k in ((H.FAMILY_NOT_RECONCILED, DIFF), (H.MENTIONED_UNLOCATED, "DH-1"),
                  (H.SCHEDULE_TAG_NOT_LOCATED, "DH-1"), (H.MISSING_REFERENCED_SHEET, "A-600"),
                  (H.DUPLICATE_SHEET_NUMBER, "EN-001.00"), (H.MECHANICAL_WITHOUT_ARCHITECTURAL, "M-106.00")):
            self.assertIn(k, kinds, k)

    def test_the_evidence_carries_it_for_a_diffuser_question(self):
        H = _H()
        db = AsyncFakeDB()
        db.plan_records.docs.append({"project_id": "p1", "record_type": "schedule", "page_id": "pg-s",
                                     "sheet_number": "M-200.00", "tier": "ocr_grid_cell",
                                     "payload": {"name": DIFF, "columns": [{"header": "", "role": None}],
                                                 "rows": [["A1"]]}})

        async def pages(_pid):
            return ["pg-s"]
        with patch.object(server, "db", db), patch.object(server, "_glyph_page_ids", pages):
            got = asyncio.run(server._glyph_evidence("p1", "diffusers"))
        self.assertEqual([(g["kind"], g["subject"]) for g in got], [(H.FAMILY_NOT_RECONCILED, DIFF)])
        self.assertFalse(_ok("There are 12 diffusers.", got))


if __name__ == "__main__":
    unittest.main()
