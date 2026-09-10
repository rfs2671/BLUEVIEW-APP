"""A SUBCONTRACTOR'S BAND KEEPS ITS PHOTOGRAPHS ON THE SAME SHEET.

THE REPORT, on the live 2026-09-09 report: appended photographs "render in a
single unattributed block after a page break, with the subcontractor's own
photo section left empty above."

── THE DATA WAS NEVER WRONG, WHICH IS WHY THIS IS A LAYOUT TEST ────────────

`append_activity_photo` pushes into `data.activities.$[act].photos` keyed on
`activity_id`, so every appended photograph sits inside its own
subcontractor's row. Measured: 21 appended photographs across five filed logs,
all of them attributed; 8 of the 12 on 2026-09-09, all Arkon Builders. And
there is exactly ONE photo-rendering site in this report, which has always
grouped by activity.

WHAT WAS WRONG IS THAT THE HEADER AND THE GRID WERE BARE SIBLINGS -- a `<p>`
and a `<div>` with no break rule between them, while the print block protects
only `h2, h3, .doc-section-title, .doc-sub-title`. The header stranded at the
foot of one page and the tiles flowed onto the next, and THE HEADER IS THE
ATTRIBUTION. Eight amber "added after filing" captions roughly doubled the
block's height, which is why it surfaced on that date.

── IT IS RENDERED, NOT GREPPED ─────────────────────────────────────────────

`page-break-after: avoid` in the source proves the rule is WRITTEN. It does not
prove WeasyPrint honours it, and this whole defect is about what the renderer
does with two elements near a page boundary. So the assertions below lay out a
real page with WeasyPrint and read where things landed.

`page-break-after: avoid` ON THE HEADER, NOT `page-break-inside: avoid` ON THE
BAND. A band of twelve tiles can be taller than what is left of a page;
forbidding the band to break would push the whole thing overleaf and leave a
hole. The rule that matters is that the header is never the last thing on a
page.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

try:
    from weasyprint import HTML as _WeasyHTML
except Exception:                                   # pragma: no cover
    _WeasyHTML = None


def _page_of(doc, needle):
    """1-based page index carrying `needle` as text, or None."""
    for i, page in enumerate(doc.pages, start=1):
        stack = [page._page_box]
        while stack:
            box = stack.pop()
            txt = getattr(box, "text", None)
            if txt and needle in txt:
                return i
            stack.extend(getattr(box, "children", ()) or ())
    return None


def _pages_with_images(doc):
    """Every 1-based page index that carries at least one replaced box."""
    out = set()
    for i, page in enumerate(doc.pages, start=1):
        stack = [page._page_box]
        while stack:
            box = stack.pop()
            if type(box).__name__ in ("InlineReplacedBox", "BlockReplacedBox"):
                out.add(i)
            stack.extend(getattr(box, "children", ()) or ())
    return out


#: A band placed so its header falls at the very foot of page one. The filler
#: is sized to leave room for the header and nothing else -- which is exactly
#: the condition that produced the report.
def _page(head_style: str) -> str:
    tiles = "".join(
        '<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAA'
        'LAAAAAABAAEAAAIBRAA7" width="160" height="120" '
        'style="width:160px;height:120px;display:inline-block;margin:3px;'
        'page-break-inside:avoid;break-inside:avoid;" />'
        for _ in range(12)
    )
    return f"""<!DOCTYPE html><html><head><style>
      @page {{ size: A4; margin: 12mm; }}
      body {{ margin: 0; font-family: sans-serif; }}
      .filler {{ height: 240mm; background: #eee; }}
    </style></head><body>
      <div class="filler">filler</div>
      <p style="{head_style}">BANDHEADER Arkon Builders</p>
      <div>{tiles}</div>
    </body></html>"""


@unittest.skipIf(_WeasyHTML is None, "weasyprint is not installed")
class WeasyPrintHonoursTheRule(unittest.TestCase):
    """THE CONTROL AND THE FIX, both rendered. Without the pair, a passing
    assertion cannot be told from a layout that never split in the first
    place."""

    HEAD = ("margin:16px 0 6px;font-size:13px;color:#475569;"
            "page-break-after:avoid;break-after:avoid-page;")
    BARE = "margin:16px 0 6px;font-size:13px;color:#475569;"

    def test_the_control_really_does_strand_the_header(self):
        """WITHOUT the rule the header ends up alone, which is the reported
        defect reproduced. If this ever stops failing, the fixture stopped
        exercising the condition and every assertion below is vacuous."""
        doc = _WeasyHTML(string=_page(self.BARE)).render()
        head = _page_of(doc, "BANDHEADER")
        imgs = _pages_with_images(doc)
        self.assertIsNotNone(head, "the fixture did not render its header")
        self.assertNotIn(head, imgs,
                         "the control did not strand the header — the filler "
                         "no longer pushes it to the foot of the page")

    def test_with_the_rule_the_header_travels_with_its_photographs(self):
        doc = _WeasyHTML(string=_page(self.HEAD)).render()
        head = _page_of(doc, "BANDHEADER")
        imgs = _pages_with_images(doc)
        self.assertIsNotNone(head)
        self.assertIn(head, imgs,
                      "the band header is still alone on its page — the "
                      "attribution and the photographs it attributes are on "
                      "different sheets")

    def test_the_band_may_still_BREAK__it_just_may_not_be_orphaned(self):
        """A twelve-tile band can be taller than the space left. Forbidding it
        to break would push the whole band overleaf and leave a hole, so the
        rule is about the HEADER, not the band."""
        self.assertNotIn("page-break-inside:avoid;break-inside:avoid;\">"
                         "{_shots}", _SRC)


class TheRuleIsOnTheHeaderThatIsRendered(unittest.TestCase):
    """The rendered pair above proves WeasyPrint's behaviour on a fixture.
    This proves the report's own header carries the same declaration."""

    def _band(self):
        i = _SRC.index('f\'<p class="band-head"')
        return _SRC[i:i + 700]

    def test_the_band_header_avoids_a_break_after_it(self):
        b = self._band()
        self.assertTrue("page-break-after:avoid" in b,
                        "the band header may be orphaned at a page foot")
        self.assertTrue("break-after:avoid-page" in b,
                        "the modern property is missing; WeasyPrint reads it")

    def test_a_photograph_is_never_split_across_a_sheet(self):
        i = _SRC.index("A PHOTOGRAPH IS NOT SPLIT ACROSS TWO SHEETS")
        self.assertTrue("page-break-inside:avoid" in _SRC[i:i + 300],
                        "a tile can be cut in half by a page boundary")

    def test_the_reason_is_written_where_the_rule_is(self):
        """WHITESPACE-NORMALISED, and the first draft was not.

        The phrase is wrapped across two comment lines as `BARE` / `SIBLINGS`,
        so a plain substring search found nothing and the assertion failed on a
        comment saying exactly what it was looking for. That is §12's
        line-wrap instance -- an assertion about PROSE defeated by formatting
        the author does not control -- reproduced inside a test written in the
        same session that documented it. Reflowing a comment is not a change
        of meaning, so the haystack is flattened before it is searched.
        """
        i = _SRC.index('f\'<p class="band-head"')
        # THE COMMENT MARKER IS PART OF THE FORMATTING TOO. Flattening
        # whitespace alone yields "were bare # siblings", because a wrapped
        # comment carries a `#` on the continuation line -- so the second
        # draft failed for a second formatting reason after the first failed
        # for a line wrap. Both are noise the author did not choose.
        above = re.sub(r"\s*#\s*", " ", _SRC[max(0, i - 2600):i])
        above = " ".join(above.split()).lower()
        self.assertTrue("bare siblings" in above,
                        "the defect this rule fixes is not recorded beside it")


class TheBandCarriesTheGatesCountAndTheLogsAttribution(unittest.TestCase):

    def test_the_count_comes_from_the_gate(self):
        i = _SRC.index("_headcounts = {_norm_company(")
        self.assertTrue("_subs" in _SRC[i:i + 120],
                        "the band count no longer reads the check-in "
                        "headcount")

    def test_worker_count_on_the_log_is_NOT_read(self):
        """It is None on all 110 activity rows in production — it has never
        once been filled in."""
        i = _SRC.index("_headcounts = {_norm_company(")
        j = _SRC.index("_flags = \"\"", i)
        self.assertNotIn('_a.get("worker_count")', _SRC[i:j])

    def test_an_unmatched_company_shows_a_dash_and_says_nothing_more(self):
        i = _SRC.index("_n = _headcounts.get(_norm_company(")
        body = _SRC[i:i + 500]
        self.assertTrue("&mdash;" in body,
                        "an unmatched company does not fall back to a dash")
        for editorial in ("not matched", "no gate", "mismatch", "unknown"):
            self.assertNotIn(editorial, body.lower(),
                             "the band editorialises about a name mismatch; "
                             "the discrepancy belongs on page 1")


class NamesAreMatchedAndNeverNormalised(unittest.TestCase):
    """Folding case and collapsing space is MATCHING. Making two different
    names into one company is not, and both forms are on record."""

    def test_case_and_space_fold(self):
        self.assertEqual(server._norm_company("  Arkon   Builders "),
                         server._norm_company("arkon builders"))

    def test_arkon_is_NOT_arkon_builders(self):
        """One check-in at 588 Thomas carries 'Arkon' and thirty-three carry
        'Arkon Builders'. A prefix match would join them, and that is the UI
        deciding two names are one company."""
        self.assertNotEqual(server._norm_company("Arkon"),
                            server._norm_company("Arkon Builders"))

    def test_no_prefix_or_fuzzy_matching(self):
        i = _SRC.index("def _norm_company(")
        j = _SRC.index("def _headcount_by_sub(")
        body = _SRC[i:j]
        for banned in ("startswith", "in b", "difflib", "SequenceMatcher",
                       "levenshtein"):
            self.assertNotIn(banned, body)

    def test_junk_does_not_throw(self):
        for v in (None, "", 0, 42, ["x"]):
            self.assertIsInstance(server._norm_company(v), str)


class TheDocstringNoLongerClaimsAnEmailConstraint(unittest.TestCase):
    """It is the sentence that would otherwise stop the next person: the
    redesign is only buildable because the email-safe constraint is gone."""

    def test_the_old_claim_survives_only_AS_A_RETRACTION(self):
        """THE FIRST DRAFT BANNED THE SENTENCE AND FAILED ON THE CORRECTION.

        `assertNotIn("Generate email-safe HTML report", d)` is a check that
        cannot discuss its own subject -- §12's third shape -- because the new
        docstring QUOTES the old claim in order to retract it. Which is what
        that section says to do: keep the dead words inside the retraction, so
        the next person grepping for "email-safe" finds the correction rather
        than an empty result that reads as "this was never claimed".

        So the assertion is about the RETRACTION, not the occurrence.
        """
        d = " ".join((server.generate_combined_report.__doc__ or "").split())
        self.assertIn("Generate email-safe HTML report", d,
                      "the old claim was deleted rather than retracted")
        i = d.index("Generate email-safe HTML report")
        self.assertIn("USED TO SAY THE OPPOSITE", d[:i],
                      "the quotation is not marked as a quotation")
        self.assertIn("NONE OF IT IS NOW", d[i:],
                      "the quotation is not marked as retracted")

    def test_it_says_what_actually_renders_it(self):
        d = server.generate_combined_report.__doc__ or ""
        self.assertIn("WeasyPrint", d)
        self.assertIn("RIDES AS A PDF", d)

    def test_it_keeps_the_one_thing_that_is_still_true(self):
        """Photos are absolute URLs because WeasyPrint fetches them over HTTP
        exactly as a mail client would have."""
        d = server.generate_combined_report.__doc__ or ""
        self.assertIn("absolute URLs", d)

    def test_and_it_names_the_boundary_it_may_not_cross(self):
        d = server.generate_combined_report.__doc__ or ""
        self.assertIn("test_report_legal_vs_investor", d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
