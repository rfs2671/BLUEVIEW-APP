"""Reading a schedule the text layer cannot read.

WHAT THIS IS FOR
================

M-200.00 prints seven schedules and hands the text layer not one character
from any of them. It is NOT a scan: 8,046 vector paths, 0 images. The
mechanical engineer exports with text converted to curves, so the letterforms
are outlines and the character codes are gone. Measured across the sets on
588 Boyland, 15 of 56 schedule-shaped grids are invisible this way — and it is
per-consultant, not per-project. JPW flattens; the architect does not. That is
why an entire discipline was unanswerable while its title blocks read fine.

THE THREE THINGS THAT MAKE THIS ACCURATE
========================================

1. THE GRID COMES FROM THE VECTORS, NOT FROM A MODEL. `plan_text.ruled_grids`
   finds the rectangles from the ruling lines. Nothing infers table structure,
   so a value cannot land in the wrong column.

2. ONE CALL PER TABLE, NOT PER PAGE. Measured on M-200.00, 2026-09-16, same
   engine, same sheet:

       whole sheet @150 dpi, one pass   12.6s   14/24 truth cells
       whole sheet @300 dpi, 24 tiles    112s   all spot checks
       the grid, one call @400 dpi       8.6s   42/42

   The detector downscales its input to a fixed maximum side, so a 5,400-pixel
   sheet crushes the schedule text to nothing. A 36x24 drawing must never be
   handed to OCR whole.

3. BOXES ARE PLACED BY COORDINATE. Each returned box goes to the cell whose
   rectangle contains its centre. On the PTAC schedule: 77 boxes, 77 placed,
   0 strays.

WHAT GOING WIDER COSTS
======================

Reading the whole crop in one go instead of placing into cells gave, on the
same page at the same resolution:

    PTH15.3K   for  PTH153K
    14.000     for  14,000
    13.700     for  13,700

A comma read as a period is a thousand-fold error in a capacity, produced with
nothing to signal it, and more resolution did not fix it. That is why
TIER_OCR_GRID exists and is not simply "OCR ran": what predicts whether the
number is right is that a deterministic rectangle bounded the read.

LOCAL ONLY
==========

RapidOCR / PP-OCRv4 ONNX, on the container's CPU. Sealed construction drawings
do not leave the machine, and the local engine already scores 100% on the
hardest sheet in the corpus, so there is nothing a cloud table API would buy.

THE ENGINE IS OPTIONAL. A container without it indexes exactly as it does
today: `available()` is False, no grid is read, and nothing fails.
"""

from __future__ import annotations

import io
import logging
import re
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Render resolution for a grid crop. 400 dpi on a schedule cell is ~40px of
# cap height, which is where the comma stops being read as a period.
OCR_DPI = 400
# A grid bigger than this is not a schedule — it is a drawing with rules in it,
# and rendering it at 400 dpi is how the indexer runs out of memory.
MAX_GRID_INCHES = 30.0
MAX_CELLS = 600

_engine = None
_engine_lock = threading.Lock()
_engine_failed = ""


def available() -> bool:
    """Whether OCR can run here at all. False is a normal state, not an error:
    the indexer then writes exactly what it writes today."""
    return _load() is not None


def why_unavailable() -> str:
    _load()
    return _engine_failed


def _load():
    global _engine, _engine_failed
    if _engine is not None or _engine_failed:
        return _engine
    with _engine_lock:
        if _engine is not None or _engine_failed:
            return _engine
        try:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
            logger.info("plan OCR engine ready (rapidocr-onnxruntime)")
        except Exception as e:                      # pragma: no cover - env
            _engine_failed = f"{type(e).__name__}: {e}"
            logger.warning("plan OCR unavailable: %s", _engine_failed)
    return _engine


def grid_is_readable(grid: Dict[str, Any]) -> Tuple[bool, str]:
    """(ok, why not). A guard on SIZE, before anything is rendered — a page
    frame mistaken for a schedule would be a 36-inch render at 400 dpi."""
    x0, y0, x1, y1 = grid["bbox"]
    w_in, h_in = (x1 - x0) / 72.0, (y1 - y0) / 72.0
    if w_in <= 0 or h_in <= 0:
        return False, "empty box"
    if w_in > MAX_GRID_INCHES or h_in > MAX_GRID_INCHES:
        return False, f"{w_in:.0f}x{h_in:.0f}in is a drawing, not a schedule"
    cells = (len(grid.get("rows") or []) - 1) * (len(grid.get("cols") or []) - 1)
    if cells <= 0:
        return False, "no cells"
    if cells > MAX_CELLS:
        return False, f"{cells} cells"
    return True, ""


def _boxes(image_bytes: bytes) -> List[Tuple[float, float, str]]:
    """(centre_x_px, centre_y_px, text) for everything the engine read."""
    eng = _load()
    if eng is None or not image_bytes:
        return []
    try:
        import numpy as np
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        res, _elapsed = eng(np.asarray(img))
    except Exception as e:
        logger.warning("OCR read failed: %r", e)
        return []
    out = []
    for item in (res or []):
        try:
            box, text = item[0], item[1]
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            if text and text.strip():
                out.append((sum(xs) / len(xs), sum(ys) / len(ys), text.strip()))
        except Exception:
            continue
    return out


def place_in_grid(boxes: Sequence[Tuple[float, float, str]], grid: Dict[str, Any],
                  dpi: int = OCR_DPI) -> Tuple[List[List[str]], int]:
    """(table, strays). Each box goes to the cell containing its centre.

    Pure, and separately testable from the engine — this is the half that
    decides which column a value lands in."""
    rows = list(grid["rows"])
    cols = list(grid["cols"])
    x0, y0 = cols[0], rows[0]
    scale = dpi / 72.0
    table = [["" for _ in range(len(cols) - 1)] for _ in range(len(rows) - 1)]
    strays = 0
    for px, py, text in boxes:
        cx, cy = x0 + px / scale, y0 + py / scale
        r = next((i for i in range(len(rows) - 1) if rows[i] <= cy < rows[i + 1]), None)
        c = next((j for j in range(len(cols) - 1) if cols[j] <= cx < cols[j + 1]), None)
        if r is None or c is None:
            strays += 1
            continue
        table[r][c] = (table[r][c] + " " + text).strip() if table[r][c] else text
    return table, strays


def _title_and_body(table: List[List[str]]) -> Tuple[str, List[List[str]]]:
    """A schedule's first row is often its name in one merged cell, which the
    column rules cut into pieces. Rejoined left to right, and only when the
    row has nothing under it to suggest it is data."""
    if not table:
        return "", []
    first = table[0]
    filled = [c for c in first if c]
    # A title the column rules did NOT cut up: one cell spanning the table.
    # Without this it merges into the header and every column is renamed
    # 'EXHAUST FAN SCHEDULE TAG'.
    if len(filled) == 1 and len(table) > 2:
        return re.sub(r"\s+", " ", filled[0]).strip(), table[1:]
    if len(filled) >= 2 and len(table) > 1:
        joined = " ".join(filled)
        # A title reads as words; a data row reads as values.
        if not re.search(r"\d", joined) or len(filled) < len(first) * 0.5:
            return re.sub(r"\s+", " ", joined).strip(), table[1:]
    return "", table


# A cell that is a VALUE rather than a heading. 'KW' and 'BTUH' are headings;
# '900', '0.6' and '208/1/60' are not.
_VALUE_CELL = re.compile(r"^[\d.,/\-]+$")


def _is_heading_row(row: Sequence[str]) -> bool:
    filled = [c for c in row if c]
    return bool(filled) and not any(_VALUE_CELL.match(c) for c in filled)


def schedule_from_table(table: List[List[str]], grid: Dict[str, Any]
                        ) -> Optional[Dict[str, Any]]:
    """The same shape `schedules_from_tables` produces, marked `ocr_grid`.

    `source` is what tiers it. It is never "table_finder": a cell nothing in
    the page text can confirm must not be indistinguishable from one that was.

    ── THE THREE SHAPES A PRINTED SCHEDULE ACTUALLY TAKES ─────────────────
    #
    # All three are on M-200.00, and an earlier version of this function
    # dropped three of its seven schedules by assuming only the first:
    #
    #   header then data      DIFFUSER & REGISTER, WALL ELECTRIC UNIT HEATER
    #   a blank band, or a    FAN SCHEDULE, EXHAUST FAN SCHEDULE — the
    #   two-tier header       'MOTOR DATA' band sits over HP / VOLTS / #
    #   no header at all      C408 MAINTENANCE, one row under its title
    #
    # None of that is guessed at: a heading row is one with no cell that is
    # purely a value, which is a property of the printed row.
    """
    name, body = _title_and_body(table)
    body = [r for r in body if any(c for c in r)]
    if not body:
        return None
    header = list(body[0])
    rest = body[1:]
    # A second heading band merges into the first, while data still follows it.
    while rest and _is_heading_row(rest[0]) and len(rest) > 1:
        header = [" ".join(x for x in (a, b) if x).strip()
                  for a, b in zip(header, rest[0] + [""] * len(header))]
        rest = rest[1:]
    if not rest:
        # Everything under the title was one row: it is the data, and this
        # schedule prints no column headings at all.
        return {"name": name or "", "columns": [], "rows": [header],
                "bbox": [float(v) for v in grid["bbox"]], "source": "ocr_grid"}
    if not any(header):
        return None
    return {
        "name": name or "",
        "columns": header,
        "rows": rest,
        "bbox": [float(v) for v in grid["bbox"]],
        "source": "ocr_grid",
    }


def read_grid(image_bytes: bytes, grid: Dict[str, Any], dpi: int = OCR_DPI
              ) -> Optional[Dict[str, Any]]:
    """One rendered grid crop -> one schedule, or None when nothing read."""
    boxes = _boxes(image_bytes)
    if not boxes:
        return None
    table, strays = place_in_grid(boxes, grid, dpi)
    sched = schedule_from_table(table, grid)
    if sched is not None:
        sched["ocr_boxes"] = len(boxes)
        sched["ocr_strays"] = strays
    return sched


__all__ = ["available", "why_unavailable", "grid_is_readable", "place_in_grid",
           "schedule_from_table", "read_grid", "OCR_DPI", "MAX_GRID_INCHES",
           "MAX_CELLS"]
