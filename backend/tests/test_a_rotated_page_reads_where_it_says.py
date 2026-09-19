"""A BBOX MUST INDEX THE RENDER IT WILL BE CROPPED FROM.

60% of this project's indexed pages — 78 of 129 — carry /Rotate 270, and the
grid path takes a bbox from pdfplumber (`plan_text`) and hands it to pdftoppm
as device pixels. If those two disagree about where a rectangle is, every
schedule crop on a rotated page reads blank paper, and a blank read is
indistinguishable from a grid with nothing in it.

── WHY THIS TEST EXISTS, WHICH IS NOT THE OBVIOUS REASON ────────────────────

They do not disagree. pdfplumber is correct.

On 2026-09-19 I measured pdfplumber against PyMuPDF's `search_for`, found them
different on all 24 rotated pages probed, and reported eight live pages as
"silently unreadable since OCR shipped". That was wrong. PyMuPDF's `search_for`
returns coordinates in a different space, and I had assumed it was the ground
truth without checking which one matched the artifact both describe.

The check that settles it takes one line, and this is it: crop the RENDER at
pdfplumber's bbox for a word whose text is known, and require the word back.
pdfplumber recovers it; PyMuPDF's bbox for the same word returns blank.

So this is a guard against the CORRECTION, not against the bug. Anyone who
finds the same asymmetry and "fixes" the coordinates toward PyMuPDF will break
every crop on 60% of the corpus, and this test is what stops them.
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

PDFS = Path(__file__).resolve().parents[3] / "pdfs"
#: A rotated page carrying words whose text the text layer also reports, so
#: "what it should say" needs no human in the loop.
ROTATED = ("PL - 6.29.26.pdf", 14)
DPI = 400


def _deps():
    try:
        import fitz  # noqa: F401
        import pdfplumber  # noqa: F401
        from PIL import Image  # noqa: F401
        from lib import plan_ocr  # noqa: F401
    except Exception as e:  # pragma: no cover - environment dependent
        return None, f"{type(e).__name__}: {e}"
    return True, ""


class ABboxIndexesTheRender(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ok, why = _deps()
        if not ok:
            raise unittest.SkipTest(f"renderer/OCR unavailable: {why}")
        cls.pdf = PDFS / ROTATED[0]
        if not cls.pdf.exists():
            raise unittest.SkipTest("source PDF not present in this checkout")
        import fitz
        from PIL import Image
        doc = fitz.open(cls.pdf)
        cls.page = doc[ROTATED[1] - 1]
        pix = cls.page.get_pixmap(dpi=DPI)
        cls.img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        cls.scale = DPI / 72.0

    def _read(self, bbox, pad=8):
        from lib import plan_ocr
        x0, y0, x1, y1 = [float(v) * self.scale for v in bbox]
        box = (max(0, int(x0 - pad)), max(0, int(y0 - pad)),
               min(self.img.width, int(x1 + pad)),
               min(self.img.height, int(y1 + pad)))
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            return ""
        buf = io.BytesIO()
        self.img.crop(box).save(buf, format="PNG")
        try:
            return " ".join(str(b[2]) for b in plan_ocr._boxes(buf.getvalue())
                            if len(b) > 2).upper()
        except Exception:
            return ""

    def test_the_page_really_is_rotated(self):
        """If this fixture ever stops being rotated the test proves nothing,
        so it fails loudly rather than passing vacuously."""
        self.assertEqual(self.page.rotation, 270,
                         "the fixture page is no longer rotated; this test "
                         "can no longer guard what it was written for")

    def test_a_pdfplumber_bbox_crops_to_its_own_word(self):
        """THE CONTROL. Known text in, same text out."""
        import pdfplumber
        with pdfplumber.open(self.pdf) as pdf:
            words = [w for w in pdf.pages[ROTATED[1] - 1].extract_words()
                     if w["text"].strip().upper() == "PARAPET"]
        self.assertTrue(words, "the fixture word is not on the page any more")
        hits = 0
        for w in words[:4]:
            got = self._read((w["x0"], w["top"], w["x1"], w["bottom"]))
            # OCR sometimes splits a word ('PARAPE PET'); the letters are what
            # matter, not the spacing, so compare with spaces removed.
            if "PARAPET" in got.replace(" ", ""):
                hits += 1
        self.assertGreaterEqual(
            hits, 1,
            "a pdfplumber bbox on a rotated page did not crop to its own "
            "word: the coordinate convention no longer indexes the render")

    def test_the_pymupdf_bbox_is_the_one_that_does_not(self):
        """Pins the asymmetry so the next person to find it reads this first
        instead of 'correcting' the shipped convention toward the outlier."""
        hits = self.page.search_for("PARAPET")
        self.assertTrue(hits, "fixture word not found by the other reader")
        got = self._read(tuple(hits[0]))
        # Computed, then asserted as a BOOLEAN. `assertNotIn` on a bare word
        # is a substring check that anything containing the word satisfies or
        # breaks, which test_absence_literals_are_specific bans - and caught
        # here, correctly, on the first full run.
        recovered = "PARAPET" in got.replace(" ", "")
        self.assertFalse(
            recovered,
            "PyMuPDF's search_for bbox now ALSO indexes the render. If that "
            "is genuinely true the two readers agree and this test should be "
            "rewritten — but check the render and the rotation first.")

    def test_the_two_readers_report_different_boxes_here(self):
        """The asymmetry itself, recorded. Not a defect — a fact about the
        two libraries that the comment above explains."""
        import pdfplumber
        with pdfplumber.open(self.pdf) as pdf:
            words = [w for w in pdf.pages[ROTATED[1] - 1].extract_words()
                     if w["text"].strip().upper() == "AD"]
        self.assertTrue(words)
        plumber = (words[0]["x0"], words[0]["top"])
        mupdf = self.page.search_for("AD")
        self.assertTrue(mupdf)
        self.assertGreater(
            abs(plumber[0] - mupdf[0].x0) + abs(plumber[1] - mupdf[0].y0), 5.0,
            "the readers now agree on a rotated page; re-check which one the "
            "render follows before changing anything downstream")


class AnUnrotatedPageIsTheOtherHalfOfTheControl(unittest.TestCase):
    """On an unrotated page the readers DO agree, which is why the problem is
    invisible until a landscape sheet arrives."""

    def test_they_agree_when_there_is_no_rotation(self):
        ok, why = _deps()
        if not ok:
            self.skipTest(f"renderer unavailable: {why}")
        pdf = PDFS / "MH - 7.2.26.pdf"
        if not pdf.exists():
            self.skipTest("source PDF not present in this checkout")
        import fitz
        import pdfplumber
        doc = fitz.open(pdf)
        page = doc[8]
        self.assertEqual(page.rotation, 0, "fixture page is rotated")
        with pdfplumber.open(pdf) as p:
            # A word the TEXT LAYER carries. M-200.00's schedule headings are
            # outlined vector text, so 'SCHEDULE' is not in the layer and the
            # first draft of this test skipped silently on it - a control that
            # does not run is not a control.
            words = [w for w in p.pages[8].extract_words()
                     if w["text"].strip().upper() == "CONTRACTOR"]
        self.assertTrue(words, "fixture word is no longer in the text layer")
        mupdf = page.search_for(words[0]["text"])
        if not mupdf:
            self.skipTest("other reader did not find the word")
        near = any(abs(words[0]["x0"] - m.x0) < 3
                   and abs(words[0]["top"] - m.y0) < 3 for m in mupdf)
        self.assertTrue(near, "the readers disagree on an UNROTATED page, "
                              "which would be a different and worse problem")


if __name__ == "__main__":
    unittest.main()
