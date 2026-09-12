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

import inspect
import os
import sys
import typing
import unittest
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

VIEW_TYPES = {v.ReportView, v.BannerView, v.RailCell, v.SummaryView,
              v.ActivityRowView, v.PhotoView, v.BandView, v.CardView,
              v.AttentionView, v.SafetyView, v.CompletenessView,
              v.AdditionalGateView, v.CardState}
PRIMITIVES = {str, int, float, bool}


class TheRendererTakesOnlyViewObjects(unittest.TestCase):

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
        self.assertIn(f".state.missing {{ color: {r.AMBER}", css)
        self.assertIn(f".cnum.owed {{ color: {r.AMBER}", css)
        self.assertIn(f".state.filed {{ color: {r.GREEN}", css)

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
        self.assertIn('"state filed"', page3)


# ══════════════════════════════════════════════════════════════════════════
#  PAGE 2 GEOMETRY
# ══════════════════════════════════════════════════════════════════════════

class ThePhotoBandRules(unittest.TestCase):

    def test_the_column_shapes(self):
        for count, cols in ((1, 1), (2, 2), (3, 3), (4, 2), (5, 3), (9, 3),
                            (10, 4), (12, 4)):
            self.assertEqual(r.photo_columns(count), cols, count)

    def test_four_photographs_are_two_by_two(self):
        self.assertEqual((r.photo_columns(4), r.photo_rows(4)), (2, 2))

    def test_ten_are_four_across(self):
        self.assertEqual(r.photo_columns(10), 4)

    def test_height_is_allocated_by_rows_not_by_count(self):
        """A four-up two-by-two needs twice the height of a four-across row."""
        heights, rows = r.allocate_bands([4, 2], 8.0)
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

    def test_every_card_declares_the_same_height(self):
        """ONE DECLARATION, IN THE STYLESHEET. A per-card inline height is how
        three cards in a row end at three heights."""
        html = r.render_page_3(_view(cards=_cards()))
        self.assertNotIn("height:2.00in", html)
        self.assertIn("height: 2.00in", r.stylesheet())
        self.assertEqual(r.stylesheet().count("height: 2.00in"), 1)

    def test_a_missing_card_gets_a_panel_and_no_fake_thumbnail(self):
        html = r.render_page_3(_view(cards=_cards(n=2, filed=1)))
        self.assertIn("No record filed for August 27", html)
        self.assertEqual(html.count("<img"), 1, "the absent card drew an image")

    def test_a_filed_card_links_and_an_absent_one_does_not(self):
        html = r.render_page_3(_view(cards=_cards(n=2, filed=1)))
        self.assertEqual(html.count("View log"), 1)

    def test_the_denominators_stay_separate(self):
        html = r.render_page_3(_view(cards=_cards()))
        self.assertIn("Required daily logs filed", html)
        self.assertIn("Additional records filed", html)
        self.assertIn("never combined", html)

    def test_cards_flow_three_up(self):
        """COUNTED INSIDE THE GRID. The completeness block is a table too, and
        counting every `<tr>` on the page made seven cards look like four
        rows."""
        html = r.render_page_3(_view(cards=_cards(n=7)))
        grid = html.split('class="grid"')[1].split("</table>")[0]
        self.assertEqual(grid.count("<tr>"), 3, "seven cards should be 3+3+1")


# ══════════════════════════════════════════════════════════════════════════
#  THE BANNER
# ══════════════════════════════════════════════════════════════════════════

class TheBanner(unittest.TestCase):

    def test_pages_1_and_3_carry_it_and_page_2_does_not(self):
        view = _view(acts=[_activity(photos=2)], cards=_cards())
        self.assertIn('class="banner"', r.render_page_1(view))
        self.assertIn('class="banner"', r.render_page_3(view))
        self.assertNotIn('class="banner"', r.render_page_2(view))

    def test_it_is_the_same_block_on_both(self):
        """SAME MARKUP, SO SAME DIMENSIONS. Two banners that merely look alike
        drift the first time one is edited."""
        view = _view(cards=_cards())
        block = r.render_banner(view.banner)
        self.assertIn(block, r.render_page_1(view))
        self.assertIn(block, r.render_page_3(view))

    def test_page_2_carries_a_running_reference_instead(self):
        html = r.render_page_2(_view(acts=[_activity(photos=2)]))
        self.assertIn("Page 2 of 3", html)


# ══════════════════════════════════════════════════════════════════════════
#  PAGINATION
# ══════════════════════════════════════════════════════════════════════════

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
