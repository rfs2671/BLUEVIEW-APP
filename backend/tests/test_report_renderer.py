"""THE RENDERER CHOOSES PRESENTATION AND NEVER MEANING.

Two kinds of test here and no third.

THE INPUT CONTRACT, enforced structurally. `render` takes one argument and it
is a `ReportView`; every helper in the module takes a view object or a
primitive display value. A test walks this module's own signatures and refuses
one that accepts a document, a mapping, or the model. If both a view and a
model were reachable, somebody would reach around the view layer inside a
month and the boundary would be a comment rather than a fact.

VISUAL-STRUCTURAL INVARIANTS, not semantics. Page counts, section collapse,
column shapes, contain-not-crop, equal card rows, a banner on Pages 1 and 3 and
not on Page 2. The meaning is already tested where it is decided.

THE PAGINATION SKIP IS GUARDED, following the pattern this repository already
uses: WeasyPrint's native libraries are absent on at least one authoring
machine, so those cases skip locally -- but `CI` turns the skip into a failure,
because a file that goes green in CI for the reason it exists is worse than no
file.
"""

from __future__ import annotations

import dataclasses
import inspect
import os
import sys
import typing
import unittest
from enum import Enum
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.report import model as m  # noqa: E402
from lib.report import renderer as r  # noqa: E402
from lib.report import view as v  # noqa: E402

try:
    from weasyprint import HTML
except Exception as exc:  # pragma: no cover - depends on native libraries
    HTML = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _needs_weasyprint(case):
    if HTML is not None:
        return
    if os.environ.get("CI"):
        case.fail(f"WeasyPrint did not import in CI: {_IMPORT_ERROR!r}. "
                  f"These are the only cases that count pages, and skipping "
                  f"them here would make this file green for the reason it "
                  f"exists.")
    case.skipTest(f"WeasyPrint unavailable locally: {_IMPORT_ERROR!r}")


# ── FIXTURES ───────────────────────────────────────────────────────────────

def _row(company="Arkon Builders", trade="Framers", worker_id="w1"):
    return {"worker_company": company, "trade": trade, "status": "checked_in",
            "worker_id": worker_id, "worker_name": "A Worker"}


def _activity(company="Arkon Builders", workers="6", where="1st floor",
              photos=0, trade=""):
    return {"company": company, "num_workers": workers, "trade": trade,
            "work_locations": where,
            "photos": [{"n": i} for i in range(photos)]}


#: A 1x1 transparent GIF, so a page can be laid out without a network fetch.
PIXEL = ("data:image/gif;base64,"
         "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def _view(rows=None, acts=None, cards=(), missing=("preshift_signin",),
          filed_all=False):
    gate = m.GateDayState(rows if rows is not None else [_row()])
    activities = [m.ActivityDisplayState(a, i, gate)
                  for i, a in enumerate(acts if acts is not None
                                        else [_activity()])]
    required = ["daily_jobsite", "preshift_signin", "toolbox_talk"]
    due = ["daily_jobsite", "preshift_signin"]
    filed = list(required) if filed_all else [
        t for t in required if t not in missing]
    model = m.ReportDisplayModel(
        project={}, date="2026-08-27", gate=gate, activities=activities,
        safety=m.SafetyState(None),
        required_logs=m.RequiredLogsState(required, due, filed,
                                          label=lambda t: t.replace("_", " ")),
        weather=["Rainy · 73°F", "Wind · 11 mph"])
    return v.build(
        model, address="588 Thomas S Boyland Street", city="Brooklyn, NY",
        date_long="August 27, 2026", generated="Generated 2026-09-11",
        report_number="Report #___", headline="Framing active",
        summary_body=None, cards=cards,
        photo_url=lambda lb, ai, pi, photo: PIXEL, logbook_id="lb1")


def _cards(n=7, filed=5):
    out = []
    for i in range(n):
        state = (v.CardState.FILED if i < filed else v.CardState.MISSING)
        out.append({"number": i + 1, "title": f"Log {i + 1}",
                    "citation": "§3301.2", "state": state,
                    "thumbnail": PIXEL if state is v.CardState.FILED else None,
                    "link": "https://x/1" if state is v.CardState.FILED else None,
                    "facts": ()})
    return out


# ══════════════════════════════════════════════════════════════════════════
#  THE INPUT CONTRACT
# ══════════════════════════════════════════════════════════════════════════

#: WHAT A RENDERER HELPER MAY BE HANDED: anything the view layer declares,
#: and nothing else.
#:
#: DERIVED, NOT RETYPED. This was a list of thirteen names written by hand, and
#: the first view object added after it was written -- `WeatherView`, when the
#: weather panel was given its three values -- failed the check for being
#: absent from the list rather than for being wrong. A hand-kept allowlist of
#: the things a gate permits turns every legitimate addition into a false
#: positive, and a reader who has seen two of those starts adding names without
#: reading the gate.
#:
#: The rule is unchanged and is what the derivation states: a renderer helper
#: takes a VIEW OBJECT or a primitive. A model class, a database document or an
#: activity dict is still refused, because none of them is declared here.
VIEW_TYPES = {obj for obj in vars(v).values()
              if isinstance(obj, type)
              and (dataclasses.is_dataclass(obj) or issubclass(obj, Enum))
              and obj.__module__ == v.__name__}
PRIMITIVES = {str, int, float, bool}


class TheRendererTakesOnlyViewObjects(unittest.TestCase):

    def test_the_derived_list_found_the_view_objects(self):
        """THE VACUITY GUARD ON THE DERIVATION. An empty set makes every
        signature check below pass, and a set that quietly stopped matching
        would look exactly like a renderer that had been cleaned up."""
        self.assertGreaterEqual(len(VIEW_TYPES), 13)
        for named in (v.ReportView, v.BannerView, v.ActivityRowView,
                      v.WeatherView, v.CardState):
            self.assertIn(named, VIEW_TYPES, named)

    def test_and_it_admits_nothing_from_outside_the_view_layer(self):
        """The other direction: a model class imported into `view.py` for a
        type hint must not become something a renderer may be handed."""
        for declared in VIEW_TYPES:
            self.assertEqual(declared.__module__, v.__name__, declared)

    def _functions(self):
        for name, fn in vars(r).items():
            if inspect.isfunction(fn) and fn.__module__ == r.__name__:
                yield name, fn

    def test_render_takes_exactly_one_argument_and_it_is_the_view(self):
        """NOT A VIEW AND A MODEL. If both were available somebody would reach
        around the view layer, and the boundary would stop being a fact."""
        sig = inspect.signature(r.render)
        self.assertEqual(list(sig.parameters), ["view"])
        hints = typing.get_type_hints(r.render)
        self.assertIs(hints["view"], v.ReportView)

    def test_every_page_function_takes_only_the_view(self):
        for name in ("render_page_1", "render_page_2", "render_page_3"):
            fn = getattr(r, name)
            self.assertEqual(list(inspect.signature(fn).parameters), ["view"],
                             name)
            self.assertIs(typing.get_type_hints(fn)["view"], v.ReportView,
                          name)

    def test_no_helper_accepts_anything_but_a_view_or_a_primitive(self):
        """The rule runs downward. A helper taking an activity document 'just
        for convenience' is the renderer deciding meaning again."""
        for name, fn in self._functions():
            hints = typing.get_type_hints(fn)
            for param, annotation in hints.items():
                if param == "return":
                    continue
                origin = typing.get_origin(annotation) or annotation
                args = typing.get_args(annotation)
                candidates = set(args) if args else {origin}
                # A Sequence[X] is allowed when X is allowed.
                candidates = {c for c in candidates
                              if c not in (list, tuple, type(Ellipsis))}
                for c in candidates:
                    self.assertTrue(
                        c in VIEW_TYPES or c in PRIMITIVES,
                        f"{name}({param}: {annotation}) reaches outside the "
                        f"view contract")

    def test_every_public_function_is_annotated(self):
        """AN UNANNOTATED PARAMETER IS A HOLE IN THE CHECK ABOVE, and it would
        pass silently because there is nothing to inspect."""
        for name, fn in self._functions():
            if name.startswith("_"):
                continue
            hints = typing.get_type_hints(fn)
            for param in inspect.signature(fn).parameters:
                self.assertIn(param, hints, f"{name}({param}) is unannotated")

    def test_the_module_does_not_import_the_model(self):
        source = Path(r.__file__).read_text(encoding="utf-8")
        self.assertNotIn("from .model import", source)
        self.assertNotIn("import model", source)


# ══════════════════════════════════════════════════════════════════════════
#  SECTIONS COLLAPSE, NOTHING IS RESERVED
# ══════════════════════════════════════════════════════════════════════════

class NothingIsReserved(unittest.TestCase):

    def test_page_2_is_empty_when_the_day_has_no_photographs(self):
        self.assertEqual(r.render_page_2(_view()), "")

    def test_additional_gate_workforce_leaves_no_heading_behind(self):
        html = r.render_page_1(_view())
        self.assertNotIn("Additional gate workforce", html)

    def test_and_appears_with_its_note_when_there_is_one(self):
        html = r.render_page_1(_view(
            rows=[_row(company="MQ Steel", worker_id="w1")]))
        self.assertIn("Additional gate workforce", html)
        self.assertIn("no corresponding activity was documented", html)

    def test_attention_leaves_no_empty_amber_box(self):
        html = r.render_page_1(_view(filed_all=True))
        self.assertNotIn("required record", html)
        self.assertNotIn('class="abox"', html)

    def test_safety_is_not_left_indented_beside_an_empty_attention_cell(self):
        """FOUND ON PAPER, ON THE 10 SEPTEMBER REPORT, where 5 of 5 required
        logs were filed.

        Attention and Safety share a row: 58% and 42%. With nothing
        outstanding the left cell is empty, and a 58% empty cell is not
        nothing -- it pushes Safety into the middle of the sheet under a
        full-width rule, which reads as a section whose first half failed to
        print. The row collapses to one full-width block instead.
        """
        html = r.render_page_1(_view(filed_all=True))
        self.assertIn('class="sbox"', html, "safety vanished with the row")
        self.assertNotIn('<table class="two">', html,
                         "safety is still in a two-column row with an empty "
                         "cell beside it")

    def test_and_the_row_is_STILL_two_columns_when_there_is_attention(self):
        """The control. Collapsing must not become the only layout."""
        html = r.render_page_1(_view())
        self.assertIn('<table class="two">', html)
        self.assertIn('class="sbox"', html)
        # THE SECTION HEADS, not the words. "Safety status" is also a rail
        # cell at the top of the page and always comes first.
        att = '>Attention</div>'
        saf = '>Safety</div>'
        self.assertIn(att, html)
        self.assertLess(html.index(att), html.index(saf),
                        "safety moved ahead of the outstanding records")


class TheReportNeverAccusesASigner(unittest.TestCase):
    """RESCUED FROM test_report_document_layout.py, WHICH THE REPLACEMENT
    DELETED. The claim outlived the page it was written against.

    The filed document carries an affirmation banner, and when no affirmation
    record exists for it that banner reads UNAFFIRMED. That is an honest
    deficiency ON THE DOCUMENT ITSELF. The investor report must never repeat
    it: the report indexes the filing, and a lender reading "UNAFFIRMED" on a
    summary page has been handed an accusation stripped of the record that
    qualifies it.

    The old ban was on the report EMBEDDING the badge. The report embeds
    nothing now, so this is cheaper to satisfy and worth strictly more: it
    fails the day somebody puts signature status on a record card.

    The second half is the base64 PNG magic prefix. A signature blob pasted in
    as body text is what that sentinel catches, and it is banned here for the
    same reason it is banned on the filed document.
    """

    def test_no_affirmation_badge_reaches_the_report(self):
        html = r.render(_view(rows=[_row(company="MQ Steel", worker_id="w1")]))
        self.assertNotIn("UNAFFIRMED", html)
        self.assertNotIn("AFFIRMED", html)

    def test_no_signature_blob_reaches_the_report(self):
        html = r.render(_view(rows=[_row(company="MQ Steel", worker_id="w1")]))
        self.assertNotIn("iVBORw0KGgo", html)
        self.assertNotIn("data:image/png;base64", html)

    def test_the_view_has_nowhere_to_put_one(self):
        """THE STRUCTURAL HALF. Two absence assertions on one rendered page
        pass on a page that happens not to exercise the branch; a view with no
        signature field cannot grow one by accident."""
        fields = {f.name for f in dataclasses.fields(v.ReportView)}
        for banned in ("signature", "signatures", "affirmation", "affirmed"):
            self.assertNotIn(banned, fields)


# ══════════════════════════════════════════════════════════════════════════
#  THE PALETTE IS A LANGUAGE
# ══════════════════════════════════════════════════════════════════════════

class AmberMeansOwedAndAbsent(unittest.TestCase):
    """ASSERTED ON THE CLASS, NOT THE HEX. The colours live in the stylesheet,
    so a page function emits `class="abox"` and never the value -- the first
    draft looked for the hex in the body and found nothing, which would have
    passed for a page that used amber everywhere."""

    #: Every class the stylesheet paints amber, and the one it paints green.
    AMBER_CLASSES = ('class="abox"', '"state missing"', '"cnum owed"')
    GREEN_CLASSES = ('"state filed"',)

    def test_the_stylesheet_really_paints_these_classes(self):
        """THE ANCHOR. Without it the bans below are looking for nothing."""
        css = r.stylesheet()
        self.assertIn(f".abox {{ border: 1px solid {r.AMBER}", css)
        self.assertIn(f".recstate.missing {{ color: {r.AMBER}", css)
        self.assertIn(f".recrule {{ border-top: 2px solid {r.AMBER}", css)
        self.assertIn(f".cnum.owed {{ color: {r.AMBER}", css)
        self.assertIn(f".recstate.filed {{ color: {r.GREEN}", css)

    def test_a_variance_is_not_amber(self):
        html = r.render_page_1(_view(
            rows=[_row(company="Quality Plumbing", worker_id=f"w{i}")
                  for i in range(5)],
            acts=[_activity(company="Quality Plumbing", workers="7",
                            where="Underground")],
            filed_all=True))
        self.assertIn("Count variance", html)
        for cls in self.AMBER_CLASSES:
            self.assertNotIn(cls, html, cls)

    def test_an_outstanding_record_is(self):
        html = r.render_page_1(_view(filed_all=False))
        self.assertIn('class="abox"', html)

    def test_a_zero_outstanding_is_not_amber(self):
        """A zero set in the colour that means "a record is missing" reads as
        an alarm about nothing, and a palette that cries wolf on a complete day
        is worth less on the day it matters."""
        complete = r.render_page_3(_view(filed_all=True, cards=_cards()))
        self.assertNotIn('"cnum owed"', complete)
        incomplete = r.render_page_3(_view(filed_all=False, cards=_cards()))
        self.assertIn('"cnum owed"', incomplete)

    def test_green_appears_only_for_a_filed_record(self):
        page1 = r.render_page_1(_view(filed_all=True))
        for cls in self.GREEN_CLASSES:
            self.assertNotIn(cls, page1, cls)
        page3 = r.render_page_3(_view(cards=_cards()))
        self.assertIn('"recstate filed"', page3)

    def test_a_record_that_is_not_due_is_not_amber(self):
        """AMBER MEANS REQUIRED TODAY AND ABSENT, and nothing else. A record
        that is not due is not a deficiency, so neither its state nor the
        rule above it takes the colour that says one is owed."""
        cards = _cards(n=2, filed=1)
        cards[1] = dict(cards[1], state=v.CardState.NOT_DUE)
        html = r.render_page_3(_view(cards=cards))
        self.assertIn('"recstate not_due"', html)
        self.assertIn('"recrule not_due"', html)
        self.assertNotIn('"recstate missing"', html)

    def test_and_a_complete_register_shows_no_amber_at_all(self):
        html = r.render_page_3(_view(cards=_cards(n=3, filed=3),
                                     filed_all=True))
        for cls in self.AMBER_CLASSES:
            self.assertNotIn(cls, html, cls)
        self.assertNotIn('"recstate missing"', html)


# ══════════════════════════════════════════════════════════════════════════
#  PAGE 2 GEOMETRY
# ══════════════════════════════════════════════════════════════════════════

class ThePhotoBandRules(unittest.TestCase):

    def test_the_column_shapes(self):
        for count, cols in ((1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 4),
                            (8, 4), (9, 5), (10, 5), (12, 5)):
            self.assertEqual(r.photo_columns(count), cols, count)

    def test_four_photographs_are_ONE_ROW_and_the_reason_reversed(self):
        """IT USED TO BE TWO-BY-TWO, and that was right for the shape the
        photographs used to be. On the old 0.449 capture canvas a single row
        of four was a thin strip. Cropped to 3:4 the trade reverses: a second
        row halves what every row gets, height is the scarce thing, and four
        across at 1.85in wide is larger than two across at 1.5in tall."""
        self.assertEqual((r.photo_columns(4), r.photo_rows(4)), (4, 1))

    def test_and_no_band_is_more_than_five_across(self):
        """Past five a photograph is narrower than the caption above it."""
        for n in (9, 10, 12, 20):
            self.assertLessEqual(r.photo_columns(n), 5, n)
        self.assertEqual(r.photo_columns(10), 5)

    def test_height_is_allocated_by_rows_not_by_count(self):
        """Two rows need twice the height of one, whatever the counts are."""
        heights, rows = r.allocate_bands([9, 2], 8.0)
        self.assertEqual(rows, [2, 1])
        self.assertAlmostEqual(heights[0] / heights[1], 2.0, places=5)

    def test_the_ceiling_stops_one_photograph_becoming_a_slab(self):
        html = r.render_band(_view(acts=[_activity(photos=1)]).bands[0],
                             8.69, 1)
        self.assertIn(f"height:{r.MAX_CELL_IN:.3f}in", html)

    def test_the_floor_stops_a_photograph_becoming_a_thumbnail(self):
        html = r.render_band(_view(acts=[_activity(photos=12)]).bands[0],
                             0.2, 3)
        self.assertIn(f"height:{r.MIN_CELL_IN:.3f}in", html)

    def test_a_photograph_is_bounded_on_BOTH_axes(self):
        """THE GREY FIELD CAME FROM ONLY ONE OF THEM. The cell used to be a
        fraction of the page wide whatever was in it, so a picture that ran
        out of height first sat in 2.6in of field on each side. Both bounds
        are on the image now and the cell is whatever the image turns out to
        be."""
        html = r.render_band(_view(acts=[_activity(photos=4)]).bands[0],
                             3.0, 1)
        self.assertIn("max-height:", html)
        self.assertIn("max-width:", html)

    def test_the_strip_hugs_its_photographs_rather_than_the_page(self):
        css = r.stylesheet()
        block = css[css.index("table.shots {"):]
        block = block[:block.index("}")]
        self.assertIn("width: auto", block)
        self.assertNotIn("width: 100%", block)

    def test_the_width_bound_is_the_columns_share_of_the_page(self):
        """Four across on a 7.4in page is 1.85in less the gaps, and a fifth
        column would make each one narrower."""
        four = r.render_band(_view(acts=[_activity(photos=4)]).bands[0], 9.0, 1)
        five = r.render_band(_view(acts=[_activity(photos=5)]).bands[0], 9.0, 1)

        def widest(html):
            import re
            return max(float(m) for m in
                       re.findall(r"max-width:([0-9.]+)in", html))

        self.assertLess(widest(five), widest(four))
        self.assertLess(widest(four), r.BAND_WIDTH_IN / 4)

    def test_photographs_are_contained_and_never_cropped(self):
        html = r.render_page_2(_view(acts=[_activity(photos=4)]))
        self.assertIn("max-height:", html)
        for banned in ("object-fit", "background-size: cover", "clip-path"):
            self.assertNotIn(banned, html, banned)
        self.assertNotIn("overflow: hidden", r.render_page_2(
            _view(acts=[_activity(photos=4)])))

    def test_the_band_copy_is_the_view_copy_verbatim(self):
        view = _view(rows=[_row(company="Quality Plumbing", worker_id=f"w{i}")
                           for i in range(5)],
                     acts=[_activity(company="Quality Plumbing", workers="7",
                                     where="Underground", photos=4)])
        html = r.render_page_2(view)
        self.assertIn(r.esc(view.bands[0].statement), html)
        self.assertIn(view.activities[0].statement, view.bands[0].statement)


# ══════════════════════════════════════════════════════════════════════════
#  PAGE 3
# ══════════════════════════════════════════════════════════════════════════

class TheRegisterReadsLikeARegister(unittest.TestCase):

    def test_no_record_declares_a_height_of_its_own(self):
        """THE ROWS ARE THE GRID'S, NOT THE RECORDS'.

        Every record used to be a bordered box with a fixed height, so that
        three in a row did not end at three different places. There are no
        boxes now: the records sit in table cells and the cell is what makes
        the row, so an inline height on a record is the old defect returning
        by another name.
        """
        html = r.render_page_3(_view(cards=_cards()))
        self.assertNotIn("height:", html)
        self.assertNotIn('class="card"', html, "the bordered card is back")

    def test_the_document_window_is_declared_once_per_density(self):
        """ONE DECLARATION EACH, IN THE STYLESHEET. A per-record inline
        height is how three thumbnails in a row end at three sizes."""
        # ANCHORED AT THE START OF A RULE. `.doc { height:` is a substring of
        # `.p3.r4 .doc { height:`, so counting it bare found all three.
        css = r.stylesheet()
        nl = chr(10)
        for rule in (nl + ".doc { height:",
                     nl + ".p3.r3 .doc { height:",
                     nl + ".p3.r4 .doc { height:"):
            self.assertEqual(css.count(rule), 1, rule.strip())

    def test_the_evidence_space_of_a_missing_record_keeps_its_height(self):
        """SO THE ROWS STAY ALIGNED. The space is empty -- no box, no panel,
        no outline of a document that was not filed -- but it is still the
        height of a thumbnail, or the record beside it would sit lower."""
        css = r.stylesheet()
        empty = css[css.index(".doc.empty {"):]
        empty = empty[:empty.index("}")]
        self.assertIn("border: none", empty)
        self.assertIn("background: transparent", empty)
        self.assertNotIn("height", empty, "the empty space set its own height")

    def test_a_record_carrying_facts_does_not_overflow_its_row(self):
        """MEASURED ON PAPER. The orientation record carries two fact lines
        under a two-line title, and inside the old fixed-height card it
        printed its link across the block below.

        THE CARDS ARE GONE and the row takes the height of what is in it, so
        the record cannot escape one. What is still worth checking is that the
        page does not: the fact lines are real content and they have to fit.
        """
        _needs_weasyprint(self)
        cards = _cards(n=7)
        cards[4] = dict(cards[4], facts=(
            "18 / 18 current onsite workers have orientation on file",
            "8 acknowledgments filed today"))
        html = r.render_page_3(_view(cards=cards))
        page = HTML(string=_sheet(html)).render()
        self.assertEqual(len(page.pages), 1,
                         "the register spilled onto a second sheet")

    def test_the_special_copy_reaches_the_page_verbatim(self):
        """THE PRE-SHIFT AND ORIENTATION LINES ARE THE RECORD'S OWN FIGURES
        and are printed as they arrive. This page decides sizes, not wording.
        """
        cards = _cards(n=7)
        cards[1] = dict(cards[1], facts=("No workers recorded on the sheet",))
        cards[4] = dict(cards[4], facts=(
            "11 / 11 current onsite workers have orientation on file",
            "16 acknowledgments filed today"))
        html = r.render_page_3(_view(cards=cards))
        for line in ("No workers recorded on the sheet",
                     "11 / 11 current onsite workers have orientation on file",
                     "16 acknowledgments filed today"):
            self.assertIn(r.esc(line), html, line)

    def test_a_missing_card_gets_a_panel_and_no_fake_thumbnail(self):
        html = r.render_page_3(_view(cards=_cards(n=2, filed=1)))
        self.assertIn("No record filed for August 27", html)
        self.assertEqual(html.count("<img"), 1, "the absent card drew an image")

    def test_a_filed_record_links_and_an_absent_one_does_not(self):
        """THE TITLE AND THE EVIDENCE CARRY THE LINK NOW. The repeated
        "View log" line under every card was the third time a reader was told
        the same thing; a record with nothing filed still links to nothing."""
        html = r.render_page_3(_view(cards=_cards(n=2, filed=1)))
        self.assertNotIn("View log", html)
        self.assertEqual(html.count("<a "), 2, "one link on the title and "
                         "one on the evidence, for the filed record only")

    def test_the_denominators_stay_separate(self):
        html = r.render_page_3(_view(cards=_cards()))
        self.assertIn("Required daily logs filed", html)
        self.assertIn("Additional records filed", html)
        self.assertIn("never combined", html)

    def test_records_flow_three_up(self):
        """COUNTED BY RECORD, NOT BY `<tr>`. The totals line is a table too,
        and it is INSIDE the grid -- counting rows finds its row as well and
        makes seven records look like four."""
        html = r.render_page_3(_view(cards=_cards(n=7)))
        rows = [row for row in html.split("<tr") if 'class="rec"' in row]
        self.assertEqual(len(rows), 3, "seven records should be 3+3+1")
        self.assertEqual([row.count('class="rec"') for row in rows],
                         [3, 3, 1])

    def test_a_missing_record_draws_nothing_where_the_document_would_be(self):
        """NOT A DASHED BOX, NOT A GREY PANEL, NOT A DOCUMENT ICON. Each of
        those draws something where nothing was filed, which on a compliance
        register is the one thing the space must not do."""
        html = r.render_page_3(_view(cards=_cards(n=2, filed=1)))
        self.assertIn('class="doc empty"', html)
        self.assertEqual(html.count("<img"), 1, "the absent record drew one")
        # ANCHORED AS A DECLARATION. The bare word appears in the comment
        # that explains why there is no dashed box, and an assertion matching
        # a comment instead of code is satisfied by the prose alone.
        css = r.stylesheet()
        self.assertNotIn("border: 1px dashed", css,
                         "a dashed placeholder is back")

    def test_the_lonely_last_card_gets_the_completeness_beside_it(self):
        """THE OPERATOR'S RECOMPOSITION. Seven cards left one card beside two
        empty cells, with the three completeness figures floating under the
        whole grid as an afterthought. They go in the empty cells: the row
        reads as a row, and the numbers become as prominent as the cards they
        summarise."""
        html = r.render_page_3(_view(cards=_cards(n=7)))
        grid = html[html.index('class="grid"'):]
        self.assertIn('colspan="2"', grid)
        self.assertIn("comp inset", grid)
        # AND IT IS THE SAME BLOCK IN BOTH POSITIONS. An inset that carried
        # different copy would be a second summary.
        self.assertIn("never combined", grid)
        # AND NOT TWICE. The block below the grid is the fallback, not a
        # second copy.
        self.assertEqual(html.count("Document completeness"), 1)

    def test_a_full_last_row_gives_the_totals_a_row_of_their_own(self):
        """SIX RECORDS LEAVES NO SPARE CELL, so the totals line spans a row of
        the register instead of sitting beside one.

        IT IS STILL A ROW OF THE REGISTER, not a block under it. Below the
        grid it carried its own margin, border and padding, and that was what
        put five records on two sheets -- the register had already used the
        page.
        """
        html = r.render_page_3(_view(cards=_cards(n=6)))
        self.assertEqual(html.count("Document completeness"), 1)
        self.assertIn("Required daily logs filed", html)
        grid = html[html.index('class="grid"'):]
        self.assertIn('colspan="3"', grid, "the totals line left the grid")

    def test_one_spare_cell_is_not_enough_to_sit_beside_a_record(self):
        """Eight records leaves ONE empty cell. A record-shaped block of
        numbers in a row of records is the confusion this was meant to remove,
        so the totals take a row rather than squeeze into a column."""
        html = r.render_page_3(_view(cards=_cards(n=8)))
        self.assertEqual(html.count("Document completeness"), 1)
        grid = html[html.index('class="grid"'):]
        self.assertIn('colspan="3"', grid)
        self.assertNotIn('colspan="1"', grid)

    def test_the_totals_row_is_counted_before_the_window_is_sized(self):
        """THE ROW COSTS THE SAME PAGE AS A ROW OF RECORDS. Leaving the layout
        to discover that is what put five records on two sheets: the register
        was sized for two rows and then asked to carry three."""
        self.assertEqual(r.page_3_rows(_cards(n=4)), 2, "4 records inset")
        self.assertEqual(r.page_3_rows(_cards(n=5)), 3, "5 needs a totals row")
        self.assertEqual(r.page_3_rows(_cards(n=6)), 3)
        self.assertEqual(r.page_3_rows(_cards(n=7)), 3, "7 records inset")
        self.assertEqual(r.page_3_rows(_cards(n=11)), 5, "the ceiling")

    def test_the_register_fits_one_sheet_up_to_the_ELEVEN_ceiling(self):
        """THE OPERATOR'S CEILING, MEASURED RATHER THAN ASSUMED.

        COUNTING SHEETS IS NOT ENOUGH and that is the whole reason this test
        looks the way it does. Page 3 is a fixed-height block, and a
        fixed-height block CLIPS rather than paginating: the first version of
        this check reported one sheet for a register whose last row and whose
        footer had fallen off the bottom of it. What is counted is what
        LANDED -- every record, and the footer that closes the page.
        """
        _needs_weasyprint(self)
        for n in range(1, 12):
            with self.subTest(records=n):
                html = r.render_page_3(_view(cards=_cards(n=n, filed=n - 1)))
                page = HTML(string=_sheet(html)).render().pages[0]
                seen = {"rec": set(), "ft": set()}

                def walk(box):
                    el = getattr(box, "element", None)
                    cls = (el.get("class") if el is not None else "") or ""
                    for want in seen:
                        if want in cls.split():
                            # BY ELEMENT, NOT BY BOX: every anonymous block
                            # inside a record inherits its class.
                            seen[want].add(id(el))
                    for child in getattr(box, "children", ()):
                        walk(child)

                walk(page._page_box)
                self.assertEqual(len(seen["rec"]), n,
                                 f"{n - len(seen['rec'])} records fell off "
                                 f"the sheet at density "
                                 f"{r.page_3_density(_cards(n=n))!r}")
                self.assertEqual(len(seen["ft"]), 1,
                                 "the footer fell off the sheet")

    def test_the_window_shrinks_as_the_register_grows(self):
        """AND IT IS MONOTONIC. A register with more in it never gets a taller
        document window than one with less."""
        css = r.stylesheet()

        def window(density):
            nl = chr(10)
            key = (nl + f".p3.{density} .doc {{ height: " if density
                   else nl + ".doc { height: ")
            i = css.index(key) + len(key)
            return float(css[i:css.index("in", i)])

        heights = [window(d) for d in ("", "r3", "r4", "r5")]
        self.assertEqual(heights, sorted(heights, reverse=True), heights)


# ══════════════════════════════════════════════════════════════════════════
#  THE BANNER
# ══════════════════════════════════════════════════════════════════════════

class TheBanner(unittest.TestCase):
    """── PAGE 1 AND PAGE 3 NO LONGER SHARE A HEAD, BY RULING ──────────────

    They did, and the test below said so: one `render_banner` on both, because
    two banners that merely look alike drift the first time one is edited.

    The operator ruled page 1 to a supplied reference on 12 September and
    ruled pages 2 and 3 untouched in the same breath. Those two cannot both
    hold with one shared block, so page 1 now carries a white masthead over a
    navy hero and page 3 carries the banner it already had.

    WHAT REPLACES THE SHARED-BLOCK CHECK is the thing that check was really
    for: the two heads must not disagree about the FACTS. Both read the same
    `BannerView`, and that is asserted below rather than assumed.
    """

    def test_pages_1_and_3_carry_the_same_head_and_page_2_does_not(self):
        """THEY SHARE IT AGAIN, BY RULING. Page 1 was redesigned first and
        page 3 followed on 12 September, so both carry the masthead over the
        hero and `render_banner` has no caller left.

        PAGE 2 STILL CARRIES NEITHER. It is the evidence page and a masthead
        over photographs competes with the only thing that page is for.
        """
        view = _view(acts=[_activity(photos=2)], cards=_cards())
        for page in (r.render_page_1(view), r.render_page_3(view)):
            self.assertIn('class="mh"', page)
            self.assertIn('class="hero"', page)
        page2 = r.render_page_2(view)
        self.assertNotIn('class="mh"', page2)
        self.assertNotIn('class="hero"', page2)

    def test_page_1_carries_a_masthead_over_a_hero_instead(self):
        html = r.render_page_1(_view(cards=_cards()))
        self.assertIn('class="mh"', html)
        self.assertIn('class="hero"', html)
        self.assertNotIn('class="banner"', html)

    def test_both_heads_read_the_SAME_view_object(self):
        """THE HALF THAT MATTERED. Two heads may look different; they may not
        name a different address, city, date or document."""
        view = _view(cards=_cards())
        one = r.render_page_1(view)
        three = r.render_page_3(view)
        for fact in (view.banner.address.upper(), view.banner.city,
                     view.banner.dateline, view.banner.document_title):
            self.assertIn(r.esc(fact), one, fact)
        self.assertIn(r.esc(view.banner.address.upper()), three)
        self.assertIn(r.esc(view.banner.dateline), three)

    def test_the_struck_marketing_line_is_gone_from_the_whole_document(self):
        """NAMED, AND BANNED EVERYWHERE. It was the masthead's second line and
        it is not replaced with other copy of the same kind."""
        html = r.render(_view(cards=_cards()))
        self.assertNotIn("Construction Intelligence for a Higher Standard",
                         html)
        self.assertNotIn("Building Better Together", html)
        self.assertIn("Site Oversight &amp; Compliance", html)

    def test_page_2_carries_a_running_reference_instead(self):
        html = r.render_page_2(_view(acts=[_activity(photos=2)]))
        self.assertIn("Page 2 of 3", html)


# ══════════════════════════════════════════════════════════════════════════
#  PAGINATION
# ══════════════════════════════════════════════════════════════════════════

def _sheet(fragment: str) -> str:
    """One page's markup as a document WeasyPrint can lay out."""
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            f"<style>{r.stylesheet()}</style></head><body>{fragment}"
            "</body></html>")


class ThePageCount(unittest.TestCase):

    def _pages(self, view):
        return len(HTML(string=r.render(view)).render().pages)

    def test_the_reference_day_is_three_pages(self):
        _needs_weasyprint(self)
        view = _view(
            rows=[_row(company="Arkon Builders", worker_id=f"a{i}")
                  for i in range(6)]
            + [_row(company="Quality Plumbing", trade="Plumber",
                    worker_id=f"q{i}") for i in range(5)],
            acts=[_activity(company="AAZ", workers="0", where="First floor",
                            photos=2),
                  _activity(company="Arkon Builders", workers="6", photos=2),
                  _activity(company="Quality Plumbing", workers="7",
                            where="Underground", photos=4)],
            cards=_cards())
        self.assertEqual(self._pages(view), 3)

    def test_the_sparse_day_is_still_three_pages(self):
        _needs_weasyprint(self)
        view = _view(acts=[_activity(photos=1)], cards=_cards())
        self.assertEqual(self._pages(view), 3)

    def test_the_heavy_day_is_still_three_pages(self):
        _needs_weasyprint(self)
        view = _view(
            acts=[_activity(company=f"Co {i}", photos=n)
                  for i, n in enumerate((4, 3, 2, 4))],
            cards=_cards())
        self.assertEqual(self._pages(view), 3)

    def test_a_day_with_no_photographs_is_two_pages(self):
        _needs_weasyprint(self)
        self.assertEqual(self._pages(_view(cards=_cards())), 2)

    def test_page_1_is_ONE_SHEET_on_every_shape_of_day(self):
        """THE INVARIANT THE THREE DENSITIES EXIST TO HOLD.

        Page 1 adapts vertically: generous when a day has little on it, the
        pre-polish spacing when it has a lot. The failure mode is the one
        measured at 8 Prescott Place, where five activities and two
        outstanding records put Attention and Safety alone on a second sheet
        -- a brief that runs to two pages is not a brief.

        COUNTED BY RENDERING, not by arithmetic, because the arithmetic is
        exactly what was wrong: the first pass rolled the paddings back for a
        dense day and left the type sizes grown, and the page still spilled.
        """
        _needs_weasyprint(self)
        # EVERY SHAPE, NOT EVERY COUNT. Whether a day has outstanding records
        # and whether the gate saw anyone the log does not describe each cost
        # about an activity row, and the airiest densities are only reachable
        # without them -- the 10 September record has neither, and it is the
        # one the first tuning missed.
        #
        # SEVEN ACTIVITIES IS THE BOUND, and it is measured rather than
        # chosen: at eight with both extra blocks the page is full and
        # `dense` has nothing left to give. The busiest day in the corpus
        # carries five.
        shapes = [(n, extras) for n in range(0, 8) for extras in (False, True)]
        for n_acts, extras in shapes:
            with self.subTest(activities=n_acts, extras=extras):
                view = _view(
                    acts=[_activity(company=f"Company Number {i}", photos=0)
                          for i in range(n_acts)],
                    rows=([_row(company="Arkon Builders", worker_id="w1")]
                          if extras else []),
                    filed_all=not extras,
                    cards=_cards())
                # WITH THE STYLESHEET. Without it this measured unstyled
                # markup: every height, every padding and the footer's
                # absolute position come from the CSS, so the check passed on
                # a page that does not exist and missed a real overflow on
                # the 10 September record.
                pages = len(HTML(string=_sheet(r.render_page_1(view)))
                            .render().pages)
                self.assertEqual(
                    pages, 1,
                    f"page 1 ran to {pages} sheets with {n_acts} activities "
                    f"at density {r.page_1_density(view)!r}")

    def test_the_density_falls_as_the_page_fills(self):
        """AND IT IS MONOTONIC. A day with more on it never gets more air
        than a day with less, which is the property that makes one rendered
        check per shape enough."""
        order = {"air": 0, "mid": 1, "tight": 2, "dense": 3}
        seen = [order[r.page_1_density(_view(
            acts=[_activity(company=f"C{i}") for i in range(n)],
            rows=[_row(company="Arkon Builders", worker_id="w1")],
            cards=_cards()))] for n in range(0, 9)]
        self.assertEqual(seen, sorted(seen), seen)
        self.assertEqual(seen[-1], 3, "a full day is not at the floor")
        # THE GENEROUS END NEEDS A GENUINELY EMPTY DAY. `_view()` carries an
        # outstanding record and an additional-gate block by default, and each
        # of those is worth about an activity row -- a page with both on it is
        # not a page with room to spare.
        bare = _view(acts=[], rows=[], filed_all=True, cards=_cards())
        self.assertIsNone(bare.attention)
        self.assertIsNone(bare.additional_gate)
        self.assertEqual(r.page_1_density(bare), "air")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ══════════════════════════════════════════════════════════════════════════
#  WHAT MAY NOT BE SPLIT
# ══════════════════════════════════════════════════════════════════════════

class NothingIsStrandedAcrossASheet(unittest.TestCase):
    """CARRIED FORWARD FROM `test_a_band_never_loses_its_photographs.py`, which
    this replaces.

    That file exists because the failure happened on a filed report: a band
    header stranded at the foot of a sheet with its photographs overleaf, and
    THE HEADER IS THE ATTRIBUTION, so eight photographs appeared belonging to
    nobody. The new stylesheet had no break rules at all -- the page-two
    allocation was the only thing keeping a band whole, which is an arithmetic
    assumption of exactly the kind that failed before.
    """

    def test_the_band_header_may_not_end_a_page(self):
        css = r.stylesheet()
        self.assertIn(".bandhead { page-break-after: avoid", css)

    def test_a_photograph_is_never_split(self):
        css = r.stylesheet()
        self.assertIn("table.shots td { page-break-inside: avoid", css)

    def test_a_record_is_one_unit(self):
        """Its state, its evidence and its link are one statement, and the
        register's cards became typographic records when page 3 was
        recomposed -- the rule followed the markup."""
        self.assertIn(".rec { page-break-inside: avoid", r.stylesheet())

    def test_an_activity_row_is_one_unit(self):
        self.assertIn("table.acts tr { page-break-inside: avoid", r.stylesheet())

    def test_the_rule_is_AVOID_AFTER_on_the_header_not_AVOID_INSIDE_the_band(self):
        """A band taller than what is left of a page cannot honour an inside
        rule, and WeasyPrint answers an unsatisfiable one by relocating the
        whole block and leaving a hole. That correction is written in the old
        file and must not be relearned."""
        css = r.stylesheet()
        self.assertNotIn(".bandhead { page-break-inside", css)

    def test_IT_IS_RENDERED_NOT_GREPPED(self):
        """The rules above prove the rule is WRITTEN. This proves WeasyPrint
        honours it: a document forced onto several sheets, with every band
        header checked against the page it landed on."""
        _needs_weasyprint(self)
        view = _view(acts=[_activity(company=f"Co {i}", photos=4)
                           for i in range(6)], cards=_cards())
        pages = HTML(string=r.render(view)).render().pages

        def texts(page):
            out = []

            def walk(box):
                t = getattr(box, "text", None)
                if t:
                    out.append(t)
                for c in getattr(box, "children", None) or ():
                    walk(c)

            walk(page._page_box)
            return out

        companies = [b.company for b in view.bands]
        for i, page in enumerate(pages, 1):
            run = texts(page)
            if not run:
                continue
            last = run[-1].strip()
            self.assertNotIn(
                last, companies,
                f"page {i} ends on a band header, so its photographs are "
                f"overleaf and unattributed")


class TheDocumentRendererListIsCurrent(unittest.TestCase):
    """THE VACUITY GUARD ON THE WHOLE CENSUS IDIOM.

    Nine suites derive "once per renderer" from `tests/document_renderers.py`.
    A list of names that has drifted out of server.py counts nothing and
    passes, which is exactly the failure the derivation was meant to prevent.
    """

    def test_every_named_renderer_exists_and_the_former_one_prints_nothing(self):
        from tests.document_renderers import assert_is_current
        assert_is_current(self)
