"""THE MECHANICS OF THE GEOMETRY CHECK, AND ONLY THE MECHANICS.

Synthetic warps of a textured image against unrelated textures. A pass here says
ORB, the ratio test and RANSAC are wired correctly. IT SAYS NOTHING ABOUT REAL
JOBSITE PHOTOS, least of all across construction stages: that is unknown until
scripts/photo_relation_benchmark.py has been run on labeled real photos.
"""

from __future__ import annotations

import inspect
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from lib import photo_geometry as G  # noqa: E402


def texture(seed=1, size=(640, 480)):
    """A busy image with hard edges: squares, lines and speckle, seeded."""
    rng = np.random.RandomState(seed)
    w, h = size
    img = np.full((h, w), 128, np.uint8)
    for _ in range(260):
        x, y = int(rng.randint(0, w)), int(rng.randint(0, h))
        s = int(rng.randint(8, 50))
        cv2.rectangle(img, (x, y), (x + s, y + s), int(rng.randint(0, 255)), -1)
    for _ in range(120):
        cv2.line(img, tuple(int(v) for v in rng.randint(0, 640, 2)), tuple(int(v) for v in rng.randint(0, 480, 2)),
                 int(rng.randint(0, 255)), 2)
    return img


def warped(img, shift=60, seed=7):
    """The same picture from another viewpoint: a perspective warp of the plane."""
    h, w = img.shape[:2]
    rng = np.random.RandomState(seed)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = src + np.float32(rng.randint(-shift, shift, (4, 2)))
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=128)


def jpeg(img):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok
    return buf.tobytes()


class Distances:
    def __init__(self, *d):
        self.pair = [types.SimpleNamespace(distance=x) for x in d]


class TheMatch(unittest.TestCase):

    def test_the_same_picture_warped_matches_on_one_geometry(self):
        a = texture()
        got = G.match(a, warped(a))
        self.assertTrue(got["ok"], got)
        self.assertGreater(got["inliers"], 100, got)
        self.assertGreater(got["ratio"], 0.5, got)

    def test_a_steep_angle_still_matches(self):
        a = texture(2)
        got = G.match(a, warped(a, shift=110, seed=3))
        self.assertGreater(got["inliers"], 40, got)

    def test_two_unrelated_textures_find_no_geometry(self):
        got = G.match(texture(1), texture(99))
        self.assertLess(got["inliers"], 15, got)

    def test_the_warped_pair_is_far_apart_from_the_unrelated_pair(self):
        a = texture(3)
        self.assertGreater(G.match(a, warped(a))["inliers"], 8 * max(G.match(a, texture(77))["inliers"], 1))

    def test_jpeg_bytes_work_the_same(self):
        a = texture(4)
        self.assertGreater(G.match(jpeg(a), jpeg(warped(a)))["inliers"], 60)

    def test_it_is_deterministic(self):
        a = texture(5)
        self.assertEqual(G.match(a, warped(a)), G.match(a, warped(a)))

    def test_large_images_are_measured_at_a_bounded_size(self):
        big = np.zeros((2400, 4000), np.uint8)
        self.assertEqual(max(G._gray(big).shape), G.MAX_SIDE)

    def test_what_cannot_be_measured_says_so(self):
        for a, b, why in ((b"", b"", "unreadable"), (b"not an image", b"x", "unreadable"), (None, None, "unreadable"),
                          (np.full((200, 200), 128, np.uint8), np.full((200, 200), 128, np.uint8), "too few")):
            with self.subTest(why=why):
                got = G.match(a, b)
                self.assertEqual((got["ok"], got["inliers"]), (False, 0))
                self.assertIn(why, got["reason"])

    def test_it_never_raises(self):
        with patch.object(G, "_gray", side_effect=RuntimeError("boom")):
            self.assertFalse(G.match(b"x", b"y")["ok"])


class TheRatioTest(unittest.TestCase):

    def test_a_match_clearly_better_than_the_runner_up_is_kept(self):
        self.assertEqual(len(G.ratio_filter([Distances(10, 100).pair])), 1)

    def test_a_match_about_as_good_as_the_runner_up_is_dropped(self):
        self.assertEqual(G.ratio_filter([Distances(90, 100).pair]), [])

    def test_a_match_with_no_runner_up_is_dropped(self):
        self.assertEqual(G.ratio_filter([Distances(10).pair]), [])


class TheVerification(unittest.TestCase):

    def test_scattered_matches_are_not_inliers(self):
        rng = np.random.RandomState(1)
        a = np.float32(rng.randint(0, 600, (100, 2))).reshape(-1, 1, 2)
        b = np.float32(rng.randint(0, 600, (100, 2))).reshape(-1, 1, 2)
        self.assertLess(G.verify(a, b)[0], 30)

    def test_a_true_transform_is_all_inliers(self):
        rng = np.random.RandomState(1)
        a = np.float32(rng.randint(0, 600, (100, 2))).reshape(-1, 1, 2)
        self.assertEqual(G.verify(a, a + np.float32([[12, -7]]))[0], 100)

    def test_outliers_among_true_matches_do_not_spoil_the_fit(self):
        """What RANSAC is for: a plain least-squares fit is dragged off by these."""
        rng = np.random.RandomState(2)
        a = np.float32(rng.randint(0, 600, (100, 2))).reshape(-1, 1, 2)
        b = a + np.float32([[12, -7]])
        b[70:] = np.float32(rng.randint(0, 600, (30, 2))).reshape(-1, 1, 2)
        self.assertGreaterEqual(G.verify(a, b)[0], 70)

    def test_the_result_reports_the_verified_count_not_the_match_count(self):
        a = texture(6)
        with patch.object(G, "verify", return_value=(3, 9)):
            got = G.match(a, warped(a))
        self.assertGreater(got["good"], 20, got)
        self.assertEqual((got["inliers"], got["epipolar_inliers"]), (3, 9))
        self.assertEqual(got["ratio"], round(3 / got["good"], 4))


class HowItIsBuilt(unittest.TestCase):

    def test_opencv_is_imported_lazily(self):
        top = inspect.getsource(G).split("def _gray", 1)[0]
        self.assertNotIn("import cv2\n", top)
        self.assertNotIn("import numpy", top)

    def test_the_docstring_states_what_is_unknown(self):
        self.assertIn("UNKNOWN", G.__doc__)
        self.assertIn("construction stages", G.__doc__)


if __name__ == "__main__":
    unittest.main()
