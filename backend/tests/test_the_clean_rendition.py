"""THE CROP REMOVES PADDING AND NEVER REMOVES PHOTOGRAPH.

── WHY THIS EXISTS ────────────────────────────────────────────────────────

The capture path writes every photograph onto a phone-screen canvas and centres
the picture in it. Measured on one production record, all three renditions:

    original  1280 x 2849   568 black rows top, 569 bottom   picture 1280 x 1712
    enhanced   809 x 1800   353                354                    809 x 1093
    thumb      180 x  400    78                 78                    180 x  244

Two fifths of every cell on the investor report's evidence page was black. The
operator ruled that the report should present a cropped rendition while the
original evidence is preserved separately, so `?v=clean` trims the padding and
nothing that is stored changes.

── WHAT THE TESTS ARE ACTUALLY FOR ────────────────────────────────────────

A crop on a compliance document's photographs is a claim that what was removed
was not part of the record. So the interesting cases are all the REFUSALS:

  * a photograph with no padding is served byte-for-byte, not re-encoded
  * a dark photograph is not cropped down to its one lit corner
  * a frame that is entirely black stays entirely black
  * anything unreadable is served exactly as filed rather than dropped

The positive case -- bars come off -- is one test. The rest of this file is the
protections, because a crop that is too eager silently edits evidence.
"""

import io
import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402

try:
    from PIL import Image
except Exception as exc:  # pragma: no cover - depends on native libraries
    Image = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _needs_pillow(case):
    if Image is not None:
        return
    if os.environ.get("CI"):
        case.fail(f"Pillow did not import in CI: {_IMPORT_ERROR!r}")
    case.skipTest(f"Pillow unavailable: {_IMPORT_ERROR!r}")


def _jpeg(img) -> bytes:
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=92)
    return out.getvalue()


def _letterboxed(w=400, h=900, bar=250, colour=(120, 160, 200)):
    """A picture of `colour` centred on a black canvas, exactly like capture."""
    img = Image.new("RGB", (w, h), (0, 0, 0))
    img.paste(Image.new("RGB", (w, h - 2 * bar), colour), (0, bar))
    return img


class ThePaddingComesOff(unittest.TestCase):

    def test_the_bars_are_removed_and_the_picture_is_not(self):
        _needs_pillow(self)
        out = server._clean_photo_bytes(_jpeg(_letterboxed()))
        self.assertIsNotNone(out, "a 250px bar at each end was not removed")
        w, h = Image.open(io.BytesIO(out)).size
        self.assertEqual(w, 400, "the crop narrowed a picture that was full width")
        # JPEG RINGING IS WHY THIS IS A BAND AND NOT AN EQUALITY. A hard black
        # edge bleeds a few rows either way under lossy compression; the claim
        # is that ~400 rows of bar went and the ~400 rows of picture stayed.
        self.assertGreater(h, 360, f"the crop ate into the photograph: {h}")
        self.assertLess(h, 440, f"bar was left behind: {h}")

    def test_the_cropped_bytes_are_still_a_readable_jpeg(self):
        _needs_pillow(self)
        out = server._clean_photo_bytes(_jpeg(_letterboxed()))
        im = Image.open(io.BytesIO(out))
        self.assertEqual(im.format, "JPEG")
        im.load()

    def test_side_bars_come_off_too(self):
        """A landscape photograph on a portrait canvas is the same defect
        rotated, and the scan is per-edge rather than top-and-bottom only."""
        _needs_pillow(self)
        img = Image.new("RGB", (900, 400), (0, 0, 0))
        img.paste(Image.new("RGB", (400, 400), (120, 160, 200)), (250, 0))
        out = server._clean_photo_bytes(_jpeg(img))
        self.assertIsNotNone(out)
        w, h = Image.open(io.BytesIO(out)).size
        self.assertLess(w, 460, f"the side bars were left on: {w}")
        self.assertEqual(h, 400)


class AndTheRefusALS(unittest.TestCase):
    """EVERY ONE OF THESE SERVES THE PHOTOGRAPH AS FILED."""

    def test_a_photograph_with_no_padding_is_not_touched_at_all(self):
        """NOT RE-ENCODED EITHER. Returning None means the route streams the
        stored bytes, so a picture that never needed cropping does not lose a
        generation to a cosmetic pass."""
        _needs_pillow(self)
        plain = _jpeg(Image.new("RGB", (400, 900), (120, 160, 200)))
        self.assertIsNone(server._clean_photo_bytes(plain))

    def test_a_hairline_dark_edge_is_encoder_noise_and_is_ignored(self):
        """One or two dark rows off a compressor is not a letterbox, and
        re-encoding the whole corpus for them would be the worse trade."""
        _needs_pillow(self)
        img = Image.new("RGB", (400, 900), (120, 160, 200))
        img.paste(Image.new("RGB", (400, 4), (0, 0, 0)), (0, 0))
        self.assertIsNone(server._clean_photo_bytes(_jpeg(img)))

    def test_a_genuinely_dark_photograph_keeps_its_frame(self):
        """A night shot, or a shaft. Cropping this to the one lit corner would
        be an edit of the record rather than a trim of the canvas."""
        _needs_pillow(self)
        img = Image.new("RGB", (400, 900), (0, 0, 0))
        img.paste(Image.new("RGB", (120, 120), (200, 200, 120)), (140, 390))
        self.assertIsNone(server._clean_photo_bytes(_jpeg(img)))

    def test_an_entirely_black_frame_stays_entirely_black(self):
        _needs_pillow(self)
        self.assertIsNone(
            server._clean_photo_bytes(_jpeg(Image.new("RGB", (400, 900)))))

    def test_bytes_that_are_not_an_image_do_not_raise(self):
        """The route calls this on whatever the bucket returned. An exception
        here would 500 a page instead of printing a photograph."""
        self.assertIsNone(server._clean_photo_bytes(b"not an image"))
        self.assertIsNone(server._clean_photo_bytes(b""))

    def test_a_one_pixel_image_does_not_raise(self):
        _needs_pillow(self)
        self.assertIsNone(server._clean_photo_bytes(_jpeg(
            Image.new("RGB", (1, 1), (10, 10, 10)))))


class TheCropIsAlsoASizeDecision(unittest.TestCase):
    """REMOVING THE BARS REMOVES THE CHEAPEST PART OF THE FILE.

    Flat black compresses to almost nothing, so a naive re-encode of the
    cropped 60% came out LARGER than the source: 152KB in, 230KB out, thirteen
    times over on a heavy day. The report is emailed.
    """

    def test_a_tall_photograph_is_capped_at_a_printable_edge(self):
        """The tallest cell the evidence page draws is 4.40in; at 300dpi that
        is 1320 pixels, so anything above the cap is detail no printer sees."""
        _needs_pillow(self)
        big = _letterboxed(w=1280, h=2849, bar=568)
        out = server._clean_photo_bytes(_jpeg(big))
        w, h = Image.open(io.BytesIO(out)).size
        self.assertLessEqual(max(w, h), server._CLEAN_MAX_EDGE)

    def test_the_aspect_survives_the_cap(self):
        """A resize that changed the shape would crop by another name."""
        _needs_pillow(self)
        out = server._clean_photo_bytes(_jpeg(_letterboxed(1280, 2849, 568)))
        w, h = Image.open(io.BytesIO(out)).size
        self.assertAlmostEqual(w / h, 1280 / 1713, delta=0.02)

    def test_a_photograph_already_under_the_cap_is_not_upscaled(self):
        _needs_pillow(self)
        out = server._clean_photo_bytes(_jpeg(_letterboxed(400, 900, 250)))
        w, h = Image.open(io.BytesIO(out)).size
        self.assertEqual(w, 400, "a small photograph was enlarged")


class TheStoredRecordIsUntouched(unittest.TestCase):
    """THE HALF THAT MAKES THIS A RENDITION AND NOT AN EDIT."""

    def test_the_crop_is_cached_under_its_own_prefix(self):
        key = server._clean_photo_r2_key("logbook-photos/p/lb/0-0-enhanced.jpg")
        self.assertTrue(key.startswith("report-clean/"))
        self.assertIn("logbook-photos/p/lb/0-0-enhanced.jpg", key)

    def test_the_cache_key_carries_a_version(self):
        """So a change to the trim's RULES does not serve the old crop for
        ever. The objects are keyed by source, so a bump costs one re-crop."""
        key = server._clean_photo_r2_key("x/y.jpg")
        self.assertIn(server._CLEAN_VERSION, key)

    def test_two_sources_never_share_a_cached_crop(self):
        a = server._clean_photo_r2_key("logbook-photos/p/lb_a/0-0-enhanced.jpg")
        b = server._clean_photo_r2_key("logbook-photos/p/lb_b/0-0-enhanced.jpg")
        self.assertNotEqual(a, b)

    def test_nothing_here_writes_a_stored_photo_key(self):
        """THE ASSERTION THAT MATTERS. `clean` must never become a mutation of
        the filed evidence, so the three stored keys are read-only to it."""
        import ast
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        lines = src.splitlines(keepends=True)
        for name in ("_clean_crop_box", "_clean_photo_bytes",
                     "_clean_photo_r2_key", "_clean_photo_from_r2"):
            node = next(n for n in ast.walk(tree)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and n.name == name)
            body = "".join(lines[node.lineno - 1:node.end_lineno])
            for stored in ("enhanced_r2_key", "original_r2_key",
                           "thumb_r2_key"):
                self.assertNotIn(
                    f'"{stored}"', body,
                    f"{name} names a stored photo key; the clean rendition "
                    f"must not reach the filed evidence")
            # ANCHORED AS THEY WOULD BE WRITTEN. A bare "update_one" is
            # satisfied or broken by any word containing it; what must be
            # absent is a CALL that reaches the record or the bucket.
            self.assertNotIn("logbooks.update_one(", body, name)
            self.assertNotIn("_r2_client.delete_object(", body, name)

    def test_the_source_ladder_treats_clean_as_a_view_of_enhanced(self):
        photo = {"enhanced_r2_key": "e", "thumb_r2_key": "t",
                 "original_r2_key": "o"}
        self.assertEqual(server._logbook_photo_sources(photo, "clean"),
                         server._logbook_photo_sources(photo, "enhanced"))

    def test_and_the_legal_document_is_not_asked_for_a_cropped_photo(self):
        """The filing keeps the frame the camera wrote. That is the whole
        reason this is a rendition rather than a change to the enhancement."""
        import ast
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        lines = src.splitlines(keepends=True)
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == "generate_single_logbook_html")
        body = "".join(lines[node.lineno - 1:node.end_lineno])
        self.assertNotIn("v=clean", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
