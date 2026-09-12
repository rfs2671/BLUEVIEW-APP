"""WHAT THE RENDERER IS ALLOWED TO SEE.

The renderer may choose presentation and never meaning. The way that rule is
enforced is not discipline: it is that the renderer is handed THESE objects and
nothing else, and none of them carries a field it could misread.

If a template can see `num_workers`, `trade`, `check_in_time` or a raw
`work_locations`, the rule has already been broken -- because the only thing a
template can do with a raw field is decide what it means. Every attribute below
is a finished string or a closed enum. There is no dictionary, no document, no
`None`-that-might-mean-zero, and nothing to compute.

── WHERE THE LINE FALLS ──────────────────────────────────────────────────────

THE RENDERER DECIDES: column count, band height, font size, when a section
collapses, whether four photographs go two-by-two or four across, where a page
break lands.

THIS FILE AND THE MODEL DECIDE: whether zero means missing, whether counts
align, whether sitewide is an area, whether a trade is real, whether a row is
empty, whether safety is clear, which logs are required, and who was inside the
gate day.

── URLS ARE INJECTED, NOT BUILT HERE ─────────────────────────────────────────

`photo_url`, `thumbnail_url` and `document_url` arrive as callables. The base
address is a server concern -- and today it is not even a module constant
there, but the same literal written twice inside two renderers. Building a URL
here would make that three.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional, Sequence, Tuple

from . import location_vocabulary as lv
from . import model as m


class CardState(Enum):
    """A document's standing on the record index. Three, and closed.

    NOT_DUE IS NOT A DEFICIENCY. A weekly or as-needed log is not owed on a
    date it was not owed, and colouring it like a missing one would put amber
    on a page for a document nobody asked for.
    """

    FILED = "filed"
    MISSING = "missing"
    NOT_DUE = "not_due"


@dataclass(frozen=True)
class BannerView:
    wordmark: str
    tagline: str
    document_title: str
    address: str
    city: str
    dateline: str


@dataclass(frozen=True)
class RailCell:
    """One of the five. `value` is already the string to set large."""

    value: str
    label: str
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SummaryView:
    """The executive block.

    `body` IS ALREADY EITHER THE VERIFIED SENTENCE OR THE FALLBACK. The
    renderer cannot tell which, and must not: a template that could ask would
    eventually style them differently, and a reader would learn to discount
    one of them.
    """

    eyebrow: str
    headline: str
    body: str
    closing: str


@dataclass(frozen=True)
class ActivityRowView:
    company: str
    where: str
    statement: str
    chip: str


#: THE RENDITION ORDER FOR THE INVESTOR PDF, MOST FAITHFUL FIRST.
#:
#: This is a print document and the photographic evidence is most of why
#: anybody reads Page 2, so the enhanced rendition is served whenever the
#: pipeline produced one and the original otherwise.
#:
#: THE THUMBNAIL IS NOT IN THIS LIST, AND ITS ABSENCE IS THE RULE. Falling back
#: to it would shrink the attachment and quietly cost the visible construction
#: detail the page was redesigned around -- an optimisation that reads, on the
#: page, as worse photographs for no stated reason. A thumbnail is a legitimate
#: rendition for a card-sized image; it is not a size optimisation for a
#: full-page band.
#:
#: `clean` LEADS, AND IT IS A PRESENTATION RATHER THAN A DIFFERENT PICTURE.
#: The capture path pads every photograph onto a phone-screen canvas with pure
#: black above and below: two fifths of a 1280x2849 original is bar. `clean`
#: serves the enhanced rendition with only uniformly near-black EDGES removed,
#: cached under its own prefix; the stored objects are untouched, and a
#: photograph with no padding -- or one dark enough that cropping would be a
#: judgement -- is served exactly as filed.
#:
#: THE LEGAL RECORD KEEPS THE UNCROPPED PICTURE. That is the whole reason this
#: is a rendition and not a change to the enhancement: the investor report gets
#: the composed image, the filing keeps the frame the camera wrote.
#:
#: The legal renderers keep whatever rendition they already use. This order
#: governs the investor PDF and nothing else.
PHOTO_RENDITIONS: Tuple[str, ...] = ("clean", "enhanced", "original")


def photo_rendition(photo) -> str:
    """The best available rendition for one photograph.

    ORDERED AND EXPLICIT, in the view layer, so a template never chooses which
    image is authoritative and nobody can introduce a size-driven fallback at a
    call site.
    """
    if not isinstance(photo, dict):
        return "original"
    # CLEAN IS ASKED FOR WHENEVER THERE IS AN R2 OBJECT TO CROP. The endpoint
    # decides whether there is anything to remove -- it has the pixels and this
    # layer does not -- and serves the source untouched when there is not.
    if photo.get("enhanced_r2_key") or photo.get("original_r2_key"):
        return "clean"
    if photo.get("enhance_status") == "done":
        return "enhanced"
    return "original"


@dataclass(frozen=True)
class PhotoView:
    """One photograph, as a finished address.

    WHICH RENDITION IS AUTHORITATIVE IS A DATA DECISION, not a layout one, so
    it is made by `photo_rendition` above and arrives here already resolved.
    """

    url: str
    rendition: str = "original"


@dataclass(frozen=True)
class BandView:
    number: int
    company: str
    subtitle: str
    statement: str
    chip: str
    photos: Tuple[PhotoView, ...]

    @property
    def count(self) -> int:
        return len(self.photos)


@dataclass(frozen=True)
class CardView:
    number: int
    title: str
    citation: str
    state: CardState
    facts: Tuple[str, ...] = ()
    thumbnail: Optional[str] = None
    link: Optional[str] = None
    absent_note: str = ""


@dataclass(frozen=True)
class AttentionView:
    outstanding: int
    names: Tuple[str, ...]

    @property
    def headline(self) -> str:
        word = "record" if self.outstanding == 1 else "records"
        return f"{self.outstanding} required {word} outstanding"


@dataclass(frozen=True)
class WeatherView:
    """One day's weather, resolved, in the two shapes a page might want.

    `line` is the composed sentence every other surface prints. The three
    beside it are the SAME resolution taken apart by `_weather_parts`, for the
    panel on Page 1 that sets them out separately.

    `detailed` IS THE ONLY QUESTION A TEMPLATE MAY ASK. When the helper
    returned a whole-line message -- "could not be retrieved", or not recorded
    -- there are no parts, and a panel that tried to lay out three empty
    fields would print a heading over nothing. So the template asks whether
    there is a breakdown to show and prints the line when there is not; it
    does not test the fields itself and cannot assemble a reading from
    whichever of them happens to be non-empty.
    """

    line: str
    condition: str = ""
    temperature: str = ""
    wind: str = ""

    @property
    def detailed(self) -> bool:
        return bool(self.condition or self.temperature)

    @property
    def wind_line(self) -> str:
        """The wind with its label, or nothing. The label is the panel's
        wording and the value is the record's; keeping them apart here is why
        the renderer never has to build a phrase."""
        return f"Wind: {self.wind}" if self.wind else ""


@dataclass(frozen=True)
class SafetyView:
    value: str
    note: str


@dataclass(frozen=True)
class CompletenessView:
    """TWO DENOMINATORS, CARRIED SEPARATELY ALL THE WAY TO THE PAGE.

    They are different questions and they are never combined. A required log is
    owed on this date; an additional record is one the project files without
    being owed it today. Five of seven would be a compliance claim about two
    documents nobody asked for.
    """

    required_ratio: str
    additional: int
    outstanding: int


@dataclass(frozen=True)
class AdditionalGateView:
    line: str
    note: str


@dataclass(frozen=True)
class ReportView:
    banner: BannerView
    rail: Tuple[RailCell, ...]
    summary: SummaryView
    activities: Tuple[ActivityRowView, ...]
    additional_gate: Optional[AdditionalGateView]
    workforce_line: str
    weather_line: str
    weather: WeatherView
    attention: Optional[AttentionView]
    safety: SafetyView
    bands: Tuple[BandView, ...]
    cards: Tuple[CardView, ...]
    completeness: CompletenessView
    evidence_subtitle: str
    generated: str
    date_long: str
    unmapped_locations: Tuple[str, ...] = ()


# ══════════════════════════════════════════════════════════════════════════
#  BUILDING THE VIEW
# ══════════════════════════════════════════════════════════════════════════

WORDMARK = "LEVELOG"
#: STRUCK BY NAME, 12 September, and not replaced with other marketing copy.
#: A report a lender reads is not a place to make a claim about ourselves that
#: the pages do not prove. What stands in its place says what the company
#: does, which the document then demonstrates.
TAGLINE = "Site Oversight & Compliance"
DOCUMENT_TITLE = "Daily Construction Report"


def _words(n: int) -> str:
    return {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six",
            7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten", 11: "Eleven",
            12: "Twelve"}.get(n, str(n))


def _listed(names: Sequence[str]) -> str:
    """A, B and C. NOT "A and B and C", which is what a bare join produced --
    seen on the 31 August page: "AAZ and Arkon Builders and Power Direct and
    Quality Plumbing had recorded workforce activity."
    """
    names = list(names)
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def fallback_summary(model: "m.ReportDisplayModel") -> str:
    """THE DEFENSIBLE SENTENCE, BUILT FROM THE FACTS AND NOTHING ELSE.

    The shipped page runs the verified generator first; this is what it falls
    back to when the verifier refuses, so the WORST case is what you read here.
    Boring and true beats polished and invented on a document a lender relies
    on.

    NO AREA CLAUSE, even though the areas are canonical now. Naming them made
    the sentence read like a field dump, and the rail already says where the
    work was. A summary earns trust by being true, not by citing every column
    it had access to.
    """
    named = [a.company for a in model.activities
             if a.named and a.gate_count]
    unmatched = [a.company for a in model.activities
                 if a.named and not a.gate_count]
    trades = len(model.gate.trades)
    parts = [
        # BOTH NUMBERS IN THE SAME REGISTER. This read "Eleven workers
        # checked in through the gate across 1 trade" -- one word, one digit,
        # in one sentence, on a page a lender reads. `_words` capitalises for
        # the sentence opening, so the mid-sentence use is lowered; above
        # twelve it returns the digits and lowering them changes nothing.
        f"{_words(model.gate.check_ins)} workers checked in through the gate "
        f"across {_words(trades).lower()} "
        f"trade{'' if trades == 1 else 's'}."
    ]
    if named:
        parts.append(_listed(named) + " had recorded workforce activity.")
    if unmatched:
        parts.append(
            ", ".join(unmatched) + " activity was documented without a "
            "corresponding workforce count or matched gate check-in.")
    return " ".join(parts)


def weather_line_of(model: "m.ReportDisplayModel") -> str:
    """The one place the page's weather sentence is decided.

    It was written twice the moment the panel needed the parts as well, which
    is how the two would have drifted."""
    return " · ".join(model.weather) or "Not recorded"


def build(model: "m.ReportDisplayModel", *, address: str, city: str,
          date_long: str, generated: str, report_number: str,
          headline: str, summary_body: Optional[str],
          cards: Sequence[dict], photo_url: Callable,
          logbook_id: str, weather=None) -> ReportView:
    """Project the resolved model onto the objects a template may read.

    `summary_body` is the verified sentence when the generator produced one and
    None when it refused; the fallback is used in its place and the caller
    cannot tell downstream which arrived.
    """
    day = model.day_location()
    rail_value, rail_label, rail_notes = day.rail()

    trade_notes: List[str] = [" · ".join(model.gate.trades)] if model.gate.trades else []
    if model.gate.trades_pending:
        # SURFACED, NOT SILENTLY EXCLUDED. The placeholder is not counted as a
        # trade and the page says that a check-in carried one.
        trade_notes.append(
            f"{model.gate.trades_pending} pending assignment")

    rail = (
        RailCell(str(model.gate.check_ins), "Gate check-ins",
                 () if model.gate.check_ins else ("No check-ins recorded",)),
        RailCell(str(len(model.gate.trades)), "Trades at gate",
                 tuple(trade_notes)),
        RailCell(rail_value, rail_label, tuple(rail_notes)),
        RailCell(model.safety.value, "Safety status",
                 ("Not reported",) if not model.safety.reported else ()),
        RailCell(model.required_logs.ratio, "Required logs filed"),
    )

    activities = tuple(
        ActivityRowView(company=a.company_display,
                        where=a.where or "Area not recorded",
                        statement=a.statement, chip=a.chip)
        for a in model.activities)

    extra = model.additional_gate
    additional = None
    if extra:
        additional = AdditionalGateView(
            line=" · ".join(f"{c} {n}" for c, n in extra),
            note=("Gate check-ins recorded; no corresponding activity was "
                  "documented."))

    bands = []
    for i, a in enumerate(model.bands(), start=1):
        bits = [p for p in (a.trade.title() if a.trade else "",
                            a.where) if p]
        bits.append(f"{len(a.photos)} photograph"
                    + ("" if len(a.photos) == 1 else "s"))
        bands.append(BandView(
            number=i, company=a.company_display, subtitle=" · ".join(bits),
            statement=a.statement, chip=a.chip,
            photos=tuple(
                PhotoView(url=photo_url(logbook_id, a.activity_index, index,
                                        photo_rendition(photo)),
                          rendition=photo_rendition(photo))
                for index, photo in a.photos)))

    card_views = tuple(
        CardView(number=c["number"], title=c["title"], citation=c["citation"],
                 state=c["state"], facts=tuple(c.get("facts") or ()),
                 thumbnail=c.get("thumbnail"), link=c.get("link"),
                 absent_note=f"No record filed for {date_long}")
        for c in cards)

    workforce = " · ".join(
        f"{c} {n}" for c, n in sorted(model.gate.by_company.items(),
                                      key=lambda kv: -kv[1]))
    if workforce:
        workforce += f" · Total {model.gate.check_ins}"

    n_bands = len(bands)
    n_photos = sum(b.count for b in bands)

    return ReportView(
        banner=BannerView(WORDMARK, TAGLINE, DOCUMENT_TITLE, address, city,
                          f"{date_long} · {report_number}"),
        rail=rail,
        summary=SummaryView(
            eyebrow="Executive summary", headline=headline,
            body=summary_body or fallback_summary(model),
            closing=f"{model.required_logs.ratio} required daily logs "
                    f"were filed."),
        activities=activities,
        additional_gate=additional,
        workforce_line=workforce or "No check-ins recorded",
        weather_line=weather_line_of(model),
        # THE PARTS ARE OPTIONAL AND THE LINE IS NOT. A caller with no parts
        # to offer still gets a `WeatherView`, carrying the line it would have
        # printed anyway -- so the panel has one thing to read rather than two
        # and a `None` to branch on.
        weather=(WeatherView(weather_line_of(model), weather.condition,
                             weather.temperature, weather.wind)
                 if weather is not None
                 else WeatherView(weather_line_of(model))),
        attention=(AttentionView(len(model.required_logs.missing),
                                 tuple(model.required_logs.missing_names()))
                   if model.required_logs.missing else None),
        safety=SafetyView(model.safety.value, model.safety.note),
        bands=tuple(bands),
        cards=card_views,
        completeness=CompletenessView(model.required_logs.ratio,
                                      len(model.required_logs.extra),
                                      len(model.required_logs.missing)),
        evidence_subtitle=(
            f"Documented field evidence · {n_photos} photograph"
            + ("" if n_photos == 1 else "s")
            + f" across {n_bands} documented activit"
            + ("y" if n_bands == 1 else "ies")),
        generated=generated,
        date_long=date_long,
        unmapped_locations=tuple(day.unmapped),
    )
