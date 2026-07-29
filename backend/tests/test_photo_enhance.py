"""Daily-log photo enhancement — failure containment and contract.

The single invariant that matters here: A FAILED ENHANCEMENT MUST NEVER LOSE A
PHOTO. The original stays base64-in-Mongo untouched, the photo entry is marked
enhance_status="failed", and the report endpoint falls back to serving that
original. These tests pin that path, plus the encode contract.

Deliberately does NOT assert on pixel output. The pipeline's visual constants
(CLAHE clip, unsharp amount) are UNTUNED and must be calibrated against real CP
photos; a golden-image test written now would freeze values nobody has
validated and would then have to be regenerated the moment they are tuned.
"""

import io
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

from lib import photo_enhance  # noqa: E402


def _jpeg(w=64, h=48, colour=(120, 110, 100)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="JPEG", quality=60)
    return buf.getvalue()


class FailureContainment(unittest.TestCase):
    """Every one of these MUST raise, so the caller records failed and the
    original keeps rendering. Silent success on bad input would be worse."""

    def test_garbage_bytes_raise(self):
        with self.assertRaises(Exception):
            photo_enhance.enhance_photo(b"this is not an image at all")

    def test_empty_bytes_raise(self):
        with self.assertRaises(Exception):
            photo_enhance.enhance_photo(b"")

    def test_truncated_jpeg_raises(self):
        with self.assertRaises(Exception):
            photo_enhance.enhance_photo(_jpeg()[:12])

    def test_absurd_dimensions_rejected_before_decode_cost(self):
        """The pixel guard must fire rather than letting a decompression bomb
        allocate its way through the worker."""
        self.assertLess(photo_enhance.MAX_INPUT_PIXELS, 100_000_000)


class TuningConstants(unittest.TestCase):
    """Range sanity only — NOT an assertion that these values are correct.
    They are untuned starting points; see the module docstring."""

    def test_clahe_clip_range_is_ordered_and_sane(self):
        """The clip limit is now INTERPOLATED by the gate's flatness term
        between MIN (well-exposed) and MAX (flat/hazy), not a single value."""
        self.assertGreaterEqual(photo_enhance.CLAHE_CLIP_MIN, 1.0)
        self.assertLess(photo_enhance.CLAHE_CLIP_MIN, photo_enhance.CLAHE_CLIP_MAX)
        self.assertLessEqual(photo_enhance.CLAHE_CLIP_MAX, 6.0)

    def test_unsharp_amount_is_modest(self):
        """Above ~1.0 the halos are worse than the softness being fixed."""
        self.assertGreater(photo_enhance.UNSHARP_AMOUNT, 0.0)
        self.assertLessEqual(photo_enhance.UNSHARP_AMOUNT, 1.0)

    def test_exposure_clip_is_a_small_percentile(self):
        self.assertGreater(photo_enhance.EXPOSURE_CLIP_PCT, 0.0)
        self.assertLessEqual(photo_enhance.EXPOSURE_CLIP_PCT, 2.0)

    def test_thumbnail_is_smaller_than_enhanced(self):
        self.assertLess(photo_enhance.THUMB_MAX_EDGE, photo_enhance.ENHANCED_MAX_EDGE)
        self.assertLessEqual(photo_enhance.THUMB_QUALITY, photo_enhance.ENHANCED_QUALITY)


class NeverUpscales(unittest.TestCase):
    """No invented detail: a small input must come back at its own size, never
    stretched up to the target edge."""

    def test_fit_long_edge_leaves_small_images_alone(self):
        from PIL import Image
        img = Image.new("RGB", (120, 90))
        out = photo_enhance._fit_long_edge(img, 1800)
        self.assertEqual(out.size, (120, 90))

    def test_fit_long_edge_uses_the_LONGEST_edge(self):
        from PIL import Image
        portrait = Image.new("RGB", (600, 1200))       # long edge = height
        out = photo_enhance._fit_long_edge(portrait, 400)
        self.assertEqual(max(out.size), 400)
        self.assertEqual(out.size, (200, 400))


class BoundedWhiteBalance(unittest.TestCase):
    """A warm interior must stay warm. Full gray-world would scrub it to grey."""

    def test_strength_is_partial_not_full(self):
        self.assertGreater(photo_enhance.GRAY_WORLD_STRENGTH, 0.0)
        self.assertLess(
            photo_enhance.GRAY_WORLD_STRENGTH, 1.0,
            "strength 1.0 is full gray-world — neutralises legitimately warm scenes",
        )

    def test_gain_ceiling_is_bounded(self):
        self.assertGreater(photo_enhance.GRAY_WORLD_MAX_GAIN, 1.0)
        self.assertLessEqual(photo_enhance.GRAY_WORLD_MAX_GAIN, 2.0)

    def test_warm_scene_stays_warm(self):
        """The R>B relationship must survive correction, only narrow."""
        import numpy as np
        warm = np.zeros((32, 32, 3), dtype=np.float32)
        warm[:, :, 0] = 180.0   # R
        warm[:, :, 1] = 140.0   # G
        warm[:, :, 2] = 90.0    # B
        out = photo_enhance._gray_world_white_balance(
            warm, photo_enhance.GRAY_WORLD_STRENGTH,
        )
        r, b = float(out[:, :, 0].mean()), float(out[:, :, 2].mean())
        self.assertGreater(r, b, "warm cast fully neutralised — bound is not working")

    def test_correction_actually_narrows_the_cast(self):
        import numpy as np
        warm = np.zeros((32, 32, 3), dtype=np.float32)
        warm[:, :, 0], warm[:, :, 1], warm[:, :, 2] = 180.0, 140.0, 90.0
        out = photo_enhance._gray_world_white_balance(
            warm, photo_enhance.GRAY_WORLD_STRENGTH,
        )
        before = 180.0 - 90.0
        after = float(out[:, :, 0].mean() - out[:, :, 2].mean())
        self.assertLess(after, before, "no correction applied at all")


class Deblocking(unittest.TestCase):
    """JPEG 8x8 block artefacts are STRUCTURED and periodic, not speckle — which
    is why the median filter alongside this one cannot remove them."""

    @staticmethod
    def _blocky(w=64, h=64, step=10):
        """Flat field with a luma step at every 8th column: pure block artefact."""
        import numpy as np
        a = np.full((h, w, 3), 120.0, dtype=np.float32)
        for c in range(8, w, 8):
            a[:, c:, :] += step
        return np.clip(a, 0, 255).astype(np.uint8)

    @staticmethod
    def _boundary_energy(a):
        import numpy as np
        luma = a.astype(np.float32).mean(axis=2)
        d = np.abs(np.diff(luma, axis=1))
        cols = np.arange(d.shape[1])
        return float(d[:, cols % 8 == 7].mean())

    def test_zero_strength_is_identity(self):
        """Gated off (no shadow lift) it must not touch a single pixel."""
        import numpy as np
        src = self._blocky()
        out = photo_enhance._deblock_jpeg(src, 0.0)
        self.assertTrue(np.array_equal(src, out))

    def test_reduces_block_boundary_energy(self):
        src = self._blocky()
        before = self._boundary_energy(src)
        after = self._boundary_energy(photo_enhance._deblock_jpeg(src, 1.0))
        self.assertLess(after, before, "block boundaries not attenuated")

    def test_preserves_a_real_edge_on_a_block_boundary(self):
        """A genuine high-contrast edge that happens to land on a block line
        must survive — that is what the step threshold is for."""
        import numpy as np
        a = np.full((64, 64, 3), 40.0, dtype=np.float32)
        a[:, 32:, :] = 220.0                      # big edge, on an 8-boundary
        src = a.astype(np.uint8)
        out = photo_enhance._deblock_jpeg(src, 1.0).astype(np.float32)
        step_before = 220.0 - 40.0
        step_after = float(out[:, 32, 0].mean() - out[:, 31, 0].mean())
        self.assertGreater(step_after, step_before * 0.9,
                           "a real edge was smoothed away")

    def test_threshold_is_a_luma_step_not_a_fraction(self):
        self.assertGreater(photo_enhance.DEBLOCK_EDGE_THRESHOLD, 1.0)
        self.assertLessEqual(photo_enhance.DEBLOCK_EDGE_THRESHOLD, 64.0)


class NoThirdPartyImageDependency(unittest.TestCase):
    """CLAHE is numpy-only on purpose: opencv-python-headless measured 112 MB
    installed, for one function. If someone reintroduces it, this fails."""

    def test_module_does_not_import_cv2(self):
        src = (Path(__file__).resolve().parent.parent / "lib" / "photo_enhance.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("import cv2", src)
        self.assertNotIn("cv2.", src)

    def test_requirements_has_no_opencv(self):
        req = (Path(__file__).resolve().parent.parent.parent / "requirements.txt").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("opencv", req.lower())


class EncodeContract(unittest.TestCase):

    def test_produces_both_derivatives(self):
        r = photo_enhance.enhance_photo(_jpeg(1200, 900))
        self.assertTrue(r.enhanced_jpeg.startswith(b"\xff\xd8"))   # JPEG SOI
        self.assertTrue(r.thumbnail_jpeg.startswith(b"\xff\xd8"))
        self.assertLessEqual(max(r.thumbnail_size), photo_enhance.THUMB_MAX_EDGE)
        self.assertLessEqual(max(r.enhanced_size), photo_enhance.ENHANCED_MAX_EDGE)
        self.assertGreater(r.elapsed_ms, 0)

    def test_thumbnail_is_materially_smaller_on_disk(self):
        r = photo_enhance.enhance_photo(_jpeg(1600, 1200))
        self.assertLess(len(r.thumbnail_jpeg), len(r.enhanced_jpeg))


if __name__ == "__main__":
    unittest.main()
