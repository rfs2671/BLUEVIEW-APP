"""Photographs for the report: padding removed, orientation known. Pure PIL.

Real 588 photos arrived with solid black bars above and below the picture
(a portrait frame padded to a fixed canvas). Shown whole -- as they must be,
never cropped -- the bars read as a black band in the report. The bars are
not part of the photograph, so they are trimmed; nothing of the picture is.
"""

from __future__ import annotations

import base64
import io
from typing import Any, Optional

#: A pixel at or below this (0-255) is black padding, not picture.
BLACK = 22
#: Trim only when the picture inside is a real part of the canvas: a night
#: photograph that is simply dark must not be cut down to a speck.
MIN_KEEP = 0.30
#: And only when the padding is worth removing.
MIN_TRIM = 0.04


def trim_black_bars(im: Any) -> Any:
    """`im` without solid-black rows / columns at its edges. The picture's own
    pixels are never touched; an image that is not padded comes back as it was."""
    try:
        gray = im.convert("L")
        mask = gray.point(lambda p: 255 if p > BLACK else 0)
        box = mask.getbbox()
    except Exception:
        return im
    if not box:
        return im
    w, h = im.size
    left, top, right, bottom = box
    kept = ((right - left) * (bottom - top)) / float(w * h)
    trimmed = 1.0 - kept
    if kept < MIN_KEEP or trimmed < MIN_TRIM:
        left, top, right, bottom = 0, 0, w, h          # not padded: only the soft-edge shave below
    box = _shave(gray, (left, top, right, bottom))
    return im if box == (0, 0, w, h) else im.crop(box)


#: An edge line whose AVERAGE brightness is this low is still padding (a
#: compressed black bar leaves a few brighter pixels, a thin dark seam stays
#: after the hard trim): shave it, a few lines at a time.
EDGE_MEAN = 38
MAX_SHAVE = 0.06


def _shave(gray: Any, box):
    from PIL import ImageStat
    left, top, right, bottom = box
    w, h = gray.size
    mx, my = int(w * MAX_SHAVE), int(h * MAX_SHAVE)

    def dark(b):
        return ImageStat.Stat(gray.crop(b)).mean[0] < EDGE_MEAN
    for _ in range(my):
        if bottom - top > 2 and dark((left, bottom - 1, right, bottom)):
            bottom -= 1
        else:
            break
    for _ in range(my):
        if bottom - top > 2 and dark((left, top, right, top + 1)):
            top += 1
        else:
            break
    for _ in range(mx):
        if right - left > 2 and dark((left, top, left + 1, bottom)):
            left += 1
        else:
            break
    for _ in range(mx):
        if right - left > 2 and dark((right - 1, top, right, bottom)):
            right -= 1
        else:
            break
    return (left, top, right, bottom)


def orientation(data_uri: str) -> Optional[str]:
    """"portrait" / "landscape" / "square" of an embedded image, or None."""
    try:
        from PIL import Image
        raw = base64.b64decode(str(data_uri).split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as im:
            w, h = im.size
    except Exception:
        return None
    if abs(w - h) <= 0.08 * max(w, h):
        return "square"
    return "portrait" if h > w else "landscape"
