"""THE VIEW CARRIES NO RAW FIELD, SO A TEMPLATE CANNOT DECIDE MEANING.

The renderer may choose presentation and never meaning. That rule is not
enforced by discipline; it is enforced by the renderer being handed objects
with nothing on them to misread.

SO THE STRONGEST TEST HERE IS STRUCTURAL: walk every view object and refuse a
dictionary, a document, or any of the raw field names a template could
interpret. A `num_workers` reachable from a template is hidden business logic
waiting to happen, and the four production states already found -- an
UNASSIGNED trade, a nameless activity row, a saved empty row, a headcount-only
row -- are exactly the cases where that goes wrong quietly.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.report import model as m  # noqa: E402
from lib.report import view as v  # noqa: E402


def _row(company="Arkon Builders", trade="Framers", worker_id="w1"):
    return {"worker_company": company, "trade": trade, "status": "checked_in",
            "worker_id": worker_id, "worker_name": "A Worker"}


def _activity(company="Arkon Builders", workers="6", where="1st floor",
              photos=None, trade=""):
    return {"company": company, "num_workers": workers,
            "work_locations": where, "trade": trade, "photos": photos or []}


def _model(rows=None, acts=None, missing=None, complete=False,
           weather=("Rainy · 73°F",)):
    gate = m.GateDayState(rows if rows is not None else [_row()])
    activities = [m.ActivityDisplayState(a, i, gate)
                  for i, a in enumerate(acts if acts is not None
                                        else [_activity()])]
    required = ["daily_jobsite", "preshift_signin", "toolbox_talk"]
    due = ["daily_jobsite", "preshift_signin"]
    # `complete` FILES BOTH DUE LOGS, which is what "nothing outstanding"
    # needs. The first draft's default filed one of the two and then asserted
    # no attention block -- the fixture was wrong, not the code, and the test
    # would have been "fixed" by weakening a real assertion.
    if complete:
        filed = list(required)
    elif missing:
        filed = []
    else:
        filed = ["daily_jobsite", "toolbox_talk"]
    return m.ReportDisplayModel(
        project={}, date="2026-08-27", gate=gate, activities=activities,
        safety=m.SafetyState(None),
        required_logs=m.RequiredLogsState(required, due, filed),
        weather=list(weather))


def _build(model, cards=(), summary_body=None, weather=None):
    return v.build(
        model, address="588 Thomas S Boyland Street", city="Brooklyn, NY",
        date_long="August 27, 2026", generated="2026-09-11 12:00:00 ET",
        report_number="Report #___", headline="Framing active",
        summary_body=summary_body, cards=cards, weather=weather,
        photo_url=lambda lb, ai, pi, photo: f"https://x/{lb}/{ai}/{pi}",
        logbook_id="lb1")


# ══════════════════════════════════════════════════════════════════════════
#  NOTHING RAW REACHES A TEMPLATE
# ══════════════════════════════════════════════════════════════════════════

#: Raw DOCUMENT keys. A view field sharing a name with one of these would be
#: a template reading a stored value.
#:
#: `activities` IS NOT ON THE LIST AND WAS, WRONGLY. `ReportView.activities`
#: holds finished row objects, not the stored array of the same name -- the
#: first draft banned the word and refused a legitimate field. The dictionary
#: ban above is what actually protects against the raw array; this list is for
#: scalar keys a template could read and interpret.
BANNED_FIELDS = (
    "num_workers", "work_locations", "worker_company", "check_in_time",
    "enhance_status", "log_type", "is_deleted", "cp_signature",
    "required_logbooks", "project_class", "signins", "worker_trade",
)


def _walk(node, path="view"):
    """Every value reachable from the view, with the path that reached it."""
    yield path, node
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        for f in dataclasses.fields(node):
            yield from _walk(getattr(node, f.name), f"{path}.{f.name}")
    elif isinstance(node, (list, tuple)):
        for i, item in enumerate(node):
            yield from _walk(item, f"{path}[{i}]")


class TheViewIsFinished(unittest.TestCase):

    def setUp(self):
        self.view = _build(_model(acts=[
            _activity(photos=[{"enhance_status": "done"}, {"a": 1}])]))

    def test_no_dictionary_is_reachable(self):
        """A dict is a document, and a template handed a document will read a
        field out of it sooner or later."""
        for path, node in _walk(self.view):
            self.assertNotIsInstance(
                node, dict,
                f"{path} exposes a raw mapping to the renderer")

    def test_no_raw_field_name_is_reachable(self):
        for path, node in _walk(self.view):
            if dataclasses.is_dataclass(node) and not isinstance(node, type):
                names = {f.name for f in dataclasses.fields(node)}
                for banned in BANNED_FIELDS:
                    self.assertNotIn(banned, names, f"{path}.{banned}")

    def test_every_leaf_is_a_finished_value(self):
        allowed = (str, int, bool, type(None), v.CardState)
        for path, node in _walk(self.view):
            if dataclasses.is_dataclass(node) or isinstance(node, (list, tuple)):
                continue
            self.assertIsInstance(node, allowed, f"{path} is {type(node)}")

    def test_the_card_state_is_a_closed_enum_not_a_string(self):
        view = _build(_model(), cards=[{
            "number": 1, "title": "Daily Jobsite Log", "citation": "§3301.2",
            "state": v.CardState.FILED}])
        self.assertIsInstance(view.cards[0].state, v.CardState)


# ══════════════════════════════════════════════════════════════════════════
#  THE RAIL
# ══════════════════════════════════════════════════════════════════════════

class TheRail(unittest.TestCase):

    def test_there_are_exactly_five_cells(self):
        self.assertEqual(len(_build(_model()).rail), 5)

    def test_no_check_ins_is_a_zero_and_says_so(self):
        """ZERO IS AN OBSERVED RESULT for that Eastern-day window. An em dash
        would mean the conclusion is unavailable, which is a different fact."""
        cell = _build(_model(rows=[])).rail[0]
        self.assertEqual(cell.value, "0")
        self.assertIn("No check-ins recorded", cell.notes)

    def test_a_placeholder_trade_is_not_counted_and_is_surfaced(self):
        view = _build(_model(rows=[_row(trade="Framers", worker_id="w1"),
                                   _row(trade="UNASSIGNED", worker_id="w2")]))
        self.assertEqual(view.rail[1].value, "1")
        self.assertTrue(any("pending assignment" in n
                            for n in view.rail[1].notes))

    def test_an_unmapped_location_reaches_the_page(self):
        view = _build(_model(acts=[_activity(where="J")]))
        self.assertIn("J", view.unmapped_locations)
        self.assertTrue(any("Unmapped source value: J" in n
                            for n in view.rail[2].notes))

    def test_safety_not_reported_carries_the_dash_and_the_words(self):
        view = _build(_model())
        self.assertEqual(view.rail[3].value, "—")
        self.assertIn("Not reported", view.rail[3].notes)
        self.assertIn("No safety conclusion", view.safety.note)


# ══════════════════════════════════════════════════════════════════════════
#  SECTIONS COLLAPSE RATHER THAN RESERVE SPACE
# ══════════════════════════════════════════════════════════════════════════

class SectionsCollapse(unittest.TestCase):

    def test_additional_gate_workforce_is_None_when_empty(self):
        self.assertIsNone(_build(_model()).additional_gate)

    def test_and_present_when_a_company_has_no_activity_row(self):
        view = _build(_model(rows=[_row(company="MQ Steel", worker_id="w1"),
                                   _row(company="MQ Steel", worker_id="w2")]))
        self.assertIsNotNone(view.additional_gate)
        self.assertIn("MQ Steel 2", view.additional_gate.line)

    def test_attention_is_None_when_nothing_is_outstanding(self):
        self.assertIsNone(_build(_model(complete=True)).attention)

    def test_and_names_each_outstanding_record(self):
        view = _build(_model(missing=True))
        self.assertEqual(view.attention.outstanding, 2)
        self.assertIn("required records outstanding", view.attention.headline)

    def test_one_outstanding_record_is_singular(self):
        model = _model()
        model.required_logs = m.RequiredLogsState(
            ["a", "b"], ["a", "b"], ["a"], label=lambda t: t.upper())
        view = _build(model)
        self.assertEqual(view.attention.headline,
                         "1 required record outstanding")

    def test_no_bands_when_no_photographs(self):
        self.assertEqual(_build(_model()).bands, ())


# ══════════════════════════════════════════════════════════════════════════
#  ONE STATEMENT, TWO PAGES
# ══════════════════════════════════════════════════════════════════════════

class TheBandCopyIsTheRowCopy(unittest.TestCase):

    def test_the_band_statement_is_the_activity_statement(self):
        model = _model(
            rows=[_row(company="Quality Plumbing", worker_id=f"w{i}")
                  for i in range(5)],
            acts=[_activity(company="Quality Plumbing", workers="7",
                            where="Underground", photos=[{"a": 1}])])
        view = _build(model)
        self.assertEqual(view.bands[0].statement, view.activities[0].statement)
        self.assertEqual(view.bands[0].chip, view.activities[0].chip)
        self.assertIn("7 on daily log", view.bands[0].statement)


class TheRenditionOrderIsExplicitAndLivesHere(unittest.TestCase):

    def test_the_url_builder_is_handed_a_resolved_rendition(self):
        """It chooses nothing. The order is in the view; the server builds an
        address."""
        seen = []

        def url(lb, ai, pi, rendition):
            seen.append(rendition)
            return f"u/{pi}"

        model = _model(acts=[_activity(
            photos=[{"enhance_status": "done"}, {"enhance_status": None}])])
        v.build(model, address="a", city="c", date_long="d", generated="g",
                report_number="r", headline="h", summary_body=None, cards=(),
                photo_url=url, logbook_id="lb1")
        self.assertEqual(seen, ["enhanced", "original"])

    def test_the_enhanced_rendition_is_preferred(self):
        self.assertEqual(v.photo_rendition({"enhance_status": "done"}),
                         "enhanced")

    def test_and_the_original_is_the_fallback(self):
        for photo in ({}, {"enhance_status": None},
                      {"enhance_status": "failed"}, None):
            self.assertEqual(v.photo_rendition(photo), "original", photo)

    def test_the_thumbnail_is_NOT_in_the_order(self):
        """Its absence is the rule. Falling back to it would shrink the
        attachment and quietly cost the construction detail Page 2 was
        redesigned around -- worse photographs for no stated reason."""
        self.assertEqual(v.PHOTO_RENDITIONS, ("clean", "enhanced", "original"))
        self.assertNotIn("thumb", v.PHOTO_RENDITIONS)

    def test_clean_leads_and_is_a_presentation_not_a_different_picture(self):
        """THE OPERATOR'S RULING ON THE CAPTURE PADDING. Two fifths of every
        stored photograph is black -- the camera writes the picture onto a
        phone-screen canvas -- and no grid can fix what is inside the image.
        `clean` is the enhanced rendition with only uniformly near-black edges
        removed; the stored objects are untouched, so the filing keeps the
        frame the camera wrote and the investor page gets the composition."""
        self.assertEqual(v.PHOTO_RENDITIONS[0], "clean")
        self.assertEqual(
            v.photo_rendition({"enhance_status": "done",
                               "enhanced_r2_key": "k"}), "clean")
        self.assertEqual(v.photo_rendition({"original_r2_key": "k"}), "clean")

    def test_a_photo_with_no_r2_object_is_not_asked_to_be_cropped(self):
        """There is nothing for the endpoint to read, so asking for a crop
        would only add a rendition name to a URL that cannot honour it."""
        self.assertEqual(
            v.photo_rendition({"enhance_status": "done"}), "enhanced")
        self.assertEqual(v.photo_rendition({"base64": "x"}), "original")

    def test_every_rendition_it_returns_is_in_the_declared_order(self):
        for photo in ({"enhance_status": "done"}, {}, None, {"x": 1}):
            self.assertIn(v.photo_rendition(photo), v.PHOTO_RENDITIONS, photo)

    def test_the_view_carries_the_rendition_so_it_can_be_asserted(self):
        model = _model(acts=[_activity(photos=[{"enhance_status": "done"}])])
        view = _build(model)
        self.assertEqual(view.bands[0].photos[0].rendition, "enhanced")

    def test_and_carries_clean_when_there_is_an_object_to_crop(self):
        model = _model(acts=[_activity(photos=[
            {"enhance_status": "done", "enhanced_r2_key": "k"}])])
        self.assertEqual(_build(model).bands[0].photos[0].rendition, "clean")


# ══════════════════════════════════════════════════════════════════════════
#  THE SUMMARY
# ══════════════════════════════════════════════════════════════════════════

class TheSummary(unittest.TestCase):

    def test_the_fallback_is_used_when_the_generator_refuses(self):
        view = _build(_model(), summary_body=None)
        self.assertIn("checked in through the gate", view.summary.body)

    def test_a_verified_sentence_replaces_it_and_looks_no_different(self):
        view = _build(_model(), summary_body="A verified sentence.")
        self.assertEqual(view.summary.body, "A verified sentence.")

    def test_the_fallback_names_no_area(self):
        """The rail already says where the work was; naming areas here made
        the sentence read like a field dump."""
        view = _build(_model(acts=[_activity(where="1st floor")]))
        for token in ("L1", "1st floor", "Level 1"):
            self.assertNotIn(token, view.summary.body)

    def test_three_or_more_companies_read_as_a_list(self):
        """FOUND ON PAPER. A bare join printed "AAZ and Arkon Builders and
        Power Direct and Quality Plumbing had recorded workforce activity."
        """
        model = _model(
            rows=[_row(company=c, worker_id=f"w{i}") for i, c in enumerate(
                ("AAZ", "Arkon Builders", "Power Direct"))],
            acts=[_activity(company="AAZ"), _activity(company="Arkon Builders"),
                  _activity(company="Power Direct")])
        body = _build(model).summary.body
        self.assertIn("AAZ, Arkon Builders and Power Direct", body)
        self.assertNotIn("and Arkon Builders and", body)

    def test_two_companies_still_read_as_a_pair(self):
        model = _model(
            rows=[_row(company=c, worker_id=f"w{i}") for i, c in enumerate(
                ("AAZ", "Arkon Builders"))],
            acts=[_activity(company="AAZ"),
                  _activity(company="Arkon Builders")])
        self.assertIn("AAZ and Arkon Builders", _build(model).summary.body)

    def test_the_fallback_separates_matched_from_unmatched_companies(self):
        model = _model(
            rows=[_row(company="Arkon Builders", worker_id="w1")],
            acts=[_activity(company="Arkon Builders"),
                  _activity(company="AAZ", workers="0")])
        body = _build(model).summary.body
        self.assertIn("Arkon Builders had recorded workforce activity", body)
        self.assertIn("AAZ activity was documented without", body)

    def test_both_counts_in_the_sentence_are_written_the_same_way(self):
        """FOUND ON PAPER. It read "Eleven workers checked in through the gate
        across 1 trade" -- one word and one digit in one sentence, on a page a
        lender reads. Either register is defensible; mixing them is not."""
        body = _build(_model(
            rows=[_row(company="Arkon Builders", trade="Framers",
                       worker_id="w1")])).summary.body
        self.assertIn("across one trade", body)
        self.assertNotIn("across 1 trade", body)

    def test_and_a_plural_reads_the_same_way(self):
        body = _build(_model(rows=[
            _row(company="Arkon Builders", trade="Framers", worker_id="w1"),
            _row(company="AAZ", trade="Concrete", worker_id="w2")])).summary.body
        self.assertIn("across two trades", body)

    def test_a_count_past_the_word_list_falls_back_to_digits(self):
        """The helper spells one through twelve. Thirteen trades is not a
        number anybody writes out, and the fallback must not crash or print
        "None"."""
        rows = [_row(company=f"C{i}", trade=f"T{i}", worker_id=f"w{i}")
                for i in range(13)]
        body = _build(_model(rows=rows)).summary.body
        self.assertIn("across 13 trades", body)

    def test_the_closing_line_is_the_ratio_and_nothing_else(self):
        self.assertEqual(_build(_model()).summary.closing,
                         "1 of 2 required daily logs were filed.")


class TheWeatherPanelGetsTheSameResolutionTakenApart(unittest.TestCase):
    """APPROVED VIEW CHANGE, 12 September. The panel on Page 1 sets the
    condition, the temperature and the wind out separately; every other
    surface prints the composed line. Both come from `_weather_parts`, and
    NEITHER IS PARSED OUT OF THE OTHER -- which is the whole reason the helper
    offers two shapes instead of the renderer splitting a sentence.
    """

    class _Parts:
        def __init__(self, condition="", temperature="", wind=""):
            self.condition = condition
            self.temperature = temperature
            self.wind = wind

    def test_the_parts_reach_the_view_and_the_line_still_does(self):
        view = _build(_model(), weather=self._Parts("Cloudy", "73°F", "14 mph"))
        self.assertEqual(view.weather.condition, "Cloudy")
        self.assertEqual(view.weather.temperature, "73°F")
        self.assertEqual(view.weather.wind, "14 mph")
        self.assertEqual(view.weather.line, view.weather_line)

    def test_a_caller_with_no_parts_still_gets_a_panel_to_read(self):
        """THE PAGE HAS ONE THING TO READ, not a view object and a `None` to
        branch on. Without parts the panel carries the line it would have
        printed anyway."""
        view = _build(_model())
        self.assertEqual(view.weather.line, view.weather_line)
        self.assertFalse(view.weather.detailed)

    def test_detailed_is_the_only_question_a_template_may_ask(self):
        """A panel that tested the three fields itself could assemble a
        reading out of whichever happened to be non-empty. It asks whether
        there is a breakdown, and prints the sentence when there is not."""
        self.assertTrue(v.WeatherView("x", condition="Cloudy").detailed)
        self.assertTrue(v.WeatherView("x", temperature="73°F").detailed)
        self.assertFalse(v.WeatherView("— Weather could not be retrieved")
                         .detailed)
        # WIND ALONE IS NOT A READING. The helper never returns it without a
        # condition or a temperature, and a panel headed by a wind speed would
        # be a breakdown of nothing.
        self.assertFalse(v.WeatherView("x", wind="14 mph").detailed)

    def test_the_wind_label_is_the_panels_and_the_value_is_the_records(self):
        self.assertEqual(v.WeatherView("x", wind="14 mph").wind_line,
                         "Wind: 14 mph")
        self.assertEqual(v.WeatherView("x").wind_line, "")


class TheCompletenessDenominatorsStaySeparate(unittest.TestCase):

    def test_they_are_three_numbers_and_never_a_sum(self):
        c = _build(_model()).completeness
        self.assertEqual(c.required_ratio, "1 of 2")
        self.assertEqual(c.additional, 1)
        self.assertEqual(c.outstanding, 1)
        self.assertNotIn("3", c.required_ratio)


if __name__ == "__main__":
    unittest.main(verbosity=2)
