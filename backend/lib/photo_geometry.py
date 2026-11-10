"""Do two images show the same fixed geometry? Deterministic, no API cost.

ORB features, Lowe's ratio test, then RANSAC verification. The numbers it
returns are what a threshold is chosen on:

    inliers / ratio                  matches consistent with one homography:
                                     strict; a flat surface or a turning camera
    epipolar_inliers / epipolar_ratio matches consistent with one fundamental
                                     matrix: a real 3D scene from another spot,
                                     and easier for unrelated images to reach

WHAT THIS IS NOT. It has only been tested on synthetic warps of a textured image
against unrelated textures: that shows the mechanics. HOW WELL IT WORKS ON REAL
JOBSITE PHOTOS IS UNKNOWN, above all across construction stages, where open studs
become board and most of the feature points in the picture stop existing. Nothing
may rely on a threshold here until scripts/photo_relation_benchmark.py has been
run on labeled real photos.

OpenCV is imported inside the functions: it comes in through rapidocr, and an
import here would make every process that merely loads this module pay for it.
CPU-bound: an async caller must use asyncio.to_thread. Never raises.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

MAX_SIDE = 1200
N_FEATURES = 3000
LOWE_RATIO = 0.75
MIN_GOOD = 8
HOMOGRAPHY_PX = 5.0
EPIPOLAR_PX = 3.0
_SEED = 20261109


def _gray(image: Any) -> Any:
    """A grayscale array, its long side at most MAX_SIDE, or None. JPEG bytes
    are decoded with their EXIF orientation applied."""
    import cv2
    import numpy as np
    if isinstance(image, (bytes, bytearray)):
        if not image:
            return None
        img = cv2.imdecode(np.frombuffer(bytes(image), np.uint8), cv2.IMREAD_GRAYSCALE)
    elif isinstance(image, np.ndarray) and image.size:
        img = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    else:
        return None
    if img is None:
        return None
    longest = max(img.shape[:2])
    if longest > MAX_SIDE:
        scale = MAX_SIDE / float(longest)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return img


def ratio_filter(knn: Sequence[Sequence[Any]], ratio: float = LOWE_RATIO) -> List[Any]:
    """Lowe's test: keep a match only when clearly better than the runner-up.
    A feature with no runner-up cannot be judged distinct, so it is dropped."""
    return [p[0] for p in knn if len(p) == 2 and p[0].distance < ratio * p[1].distance]


def _inliers(mask: Any) -> int:
    return int(mask.sum()) if mask is not None else 0


def verify(pts_a: Any, pts_b: Any) -> Tuple[int, int]:
    """(homography inliers, fundamental-matrix inliers) of the matched points."""
    import cv2
    cv2.setRNGSeed(_SEED)
    _h, h_mask = cv2.findHomography(pts_a, pts_b, cv2.RANSAC, HOMOGRAPHY_PX)
    cv2.setRNGSeed(_SEED)
    _f, f_mask = cv2.findFundamentalMat(pts_a, pts_b, cv2.FM_RANSAC, EPIPOLAR_PX, 0.99)
    return _inliers(h_mask), _inliers(f_mask)


def _empty(reason: str, **seen: Any) -> Dict[str, Any]:
    return {"ok": False, "reason": reason, "keypoints": seen.get("keypoints", [0, 0]), "good": seen.get("good", 0),
            "inliers": 0, "ratio": 0.0, "epipolar_inliers": 0, "epipolar_ratio": 0.0}


def match(image_a: Any, image_b: Any) -> Dict[str, Any]:
    """{ok, reason, keypoints, good, inliers, ratio, epipolar_inliers,
    epipolar_ratio} for two images (JPEG/PNG bytes or arrays). ok False: they
    could not be measured, which is not the same as a low score."""
    try:
        import cv2
        import numpy as np
        a, b = _gray(image_a), _gray(image_b)
        if a is None or b is None:
            return _empty("unreadable image")
        orb = cv2.ORB_create(nfeatures=N_FEATURES)
        kp_a, des_a = orb.detectAndCompute(a, None)
        kp_b, des_b = orb.detectAndCompute(b, None)
        seen = [len(kp_a or ()), len(kp_b or ())]
        if des_a is None or des_b is None or min(seen) < 2:
            return _empty("too few features", keypoints=seen)
        good = ratio_filter(cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(des_a, des_b, k=2))
        if len(good) < MIN_GOOD:
            return _empty("too few matches", keypoints=seen, good=len(good))
        pts_a = np.float32([kp_a[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        pts_b = np.float32([kp_b[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        h, f = verify(pts_a, pts_b)
        return {"ok": True, "reason": "", "keypoints": seen, "good": len(good), "inliers": h,
                "ratio": round(h / len(good), 4), "epipolar_inliers": f,
                "epipolar_ratio": round(f / len(good), 4)}
    except Exception as e:
        return _empty(f"{type(e).__name__}")
