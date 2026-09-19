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


_probe: Optional[Tuple[bool, str]] = None


def probe() -> Tuple[bool, str]:
    """(ok, detail) WITHOUT building the engine. For /health.

    ── WHY THIS IS NOT `available()` ──────────────────────────────────────
    #
    # `available()` constructs RapidOCR, which loads ~15 MB of ONNX weights.
    # /health is what the platform polls, and a probe that blocks for seconds
    # on its first call is a restart loop, which is the one thing that
    # endpoint is written never to cause.
    #
    # Importing the package is enough to catch the failure that actually
    # happened: rapidocr imports cv2, cv2 needs libGL.so.1, and the image
    # carried none — so pip succeeded, the deploy went green, and the reader
    # was dead. The import is where that surfaces, and it is nearly free.
    """
    global _probe
    if _probe is None:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            _probe = (True, "")
        except Exception as e:          # pragma: no cover - environment
            _probe = (False, f"{type(e).__name__}: {e}")
    return _probe


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


def _boxes(image_bytes: bytes) -> List[Tuple[float, float, str, float]]:
    """(centre_x_px, centre_y_px, text, confidence) for everything read.

    THE CONFIDENCE USED TO BE DROPPED HERE. The engine returns it on every
    box and this function discarded item[2], so nothing downstream could tell
    a reading it was sure of from one it was not. Measured on M-200.00's
    contested cell: 0.960 when it read the 9 as a 6, 0.994-0.998 on the reads
    that were right. It is carried and stored as evidence — never as a
    ranking input, because a low score losing to a high one is the tier
    mistake again in a new unit."""
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
            score = float(item[2]) if len(item) > 2 and item[2] is not None else -1.0
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            if text and text.strip():
                out.append((sum(xs) / len(xs), sum(ys) / len(ys), text.strip(), score))
        except Exception:
            continue
    return out


def place_in_grid(boxes: Sequence[Tuple], grid: Dict[str, Any],
                  dpi: int = OCR_DPI) -> Tuple[List[List[str]], int, List[List[float]]]:
    """(table, strays, scores). Each box goes to the cell containing its centre.

    Pure, and separately testable from the engine — this is the half that
    decides which column a value lands in."""
    rows = list(grid["rows"])
    cols = list(grid["cols"])
    x0, y0 = cols[0], rows[0]
    scale = dpi / 72.0
    table = [["" for _ in range(len(cols) - 1)] for _ in range(len(rows) - 1)]
    scores = [[-1.0 for _ in range(len(cols) - 1)] for _ in range(len(rows) - 1)]
    strays = 0
    for box in boxes:
        # A three-tuple is still a box: the callers that build them by hand —
        # the tests that pin which column a value lands in — say nothing about
        # confidence and should not have to.
        px, py, text = box[0], box[1], box[2]
        score = float(box[3]) if len(box) > 3 else -1.0
        cx, cy = x0 + px / scale, y0 + py / scale
        r = next((i for i in range(len(rows) - 1) if rows[i] <= cy < rows[i + 1]), None)
        c = next((j for j in range(len(cols) - 1) if cols[j] <= cx < cols[j + 1]), None)
        if r is None or c is None:
            strays += 1
            continue
        table[r][c] = (table[r][c] + " " + text).strip() if table[r][c] else text
        # A cell built from two boxes is only as good as its worst one.
        scores[r][c] = score if scores[r][c] < 0 else min(scores[r][c], score)
    return table, strays, scores


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


#: The longest a COLUMN HEADING gets. 'AUXILIARYHEATING CAPACITY (KW)' is 30
#: characters and is the longest real heading measured on the 588 Boyland
#: grids; a compliance table's cells run to several hundred. The number is a
#: property of headings, not a tuned threshold: a heading names a column, and
#: a name is short.
_HEADING_CELL_MAX = 40
#: And a heading is a NOUN PHRASE, not a sentence. 'AUXILIARYHEATING CAPACITY
#: (KW)' is three words; 'CALCULATION OF HEATING AND COOLING LOADS' is six and
#: is a provision, not a column name. The character bound alone let that one
#: through at exactly 40 characters, which is how this second property came to
#: be measured rather than the first one widened.
_HEADING_CELL_MAX_WORDS = 4


def _is_heading_row(row: Sequence[str]) -> bool:
    """Is this row a band of COLUMN HEADINGS rather than data?

    ── WHY 'HAS NO NUMBER' WAS THE WRONG QUESTION ─────────────────────────
    #
    # This asked whether any cell was purely a value — 'KW' and 'BTUH' are
    # headings, '900' and '208/1/60' are not. That works for an equipment
    # schedule, whose data rows are mostly numbers, and fails completely for
    # a table of PROSE.
    #
    # MEASURED ON EN-001.00, 2026-09-19, on production's own renderer: the
    # ENERGY CODE TABULAR ANALYSIS yields 15 body rows and the old rule called
    # ALL FIFTEEN headings, because a code-compliance table has no purely
    # numeric cell anywhere — every cell is a citation like 'C403.3.2' or a
    # sentence. `schedule_from_table` then folded fourteen of them into the
    # column headings and returned a one-row schedule with headers like
    # 'NYCECC CITATION C403.1.1'. Nineteen of the corpus's 28 OCR-grid
    # schedules were reduced to a single row that way, including the
    # sprinkler-head schedules on SP-002.00, SP-003.00 and SP-004.00, and
    # FA-001's device matrix — whose merged rows are where the '6 SPRK,
    # TAMPER VALVE' misreading came from.
    #
    # A heading is a NAME for a column: short. That is what is asked now, and
    # the absence of digits is no longer sufficient on its own.
    """
    filled = [c for c in row if c]
    if not filled:
        return False
    if any(_VALUE_CELL.match(c) for c in filled):
        return False
    return all(len(str(c).strip()) <= _HEADING_CELL_MAX
               and len(str(c).split()) <= _HEADING_CELL_MAX_WORDS
               for c in filled)


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
    # ── AT MOST ONE EXTRA BAND, WHATEVER THE PREDICATE SAYS ───────────────
    #
    # A second heading band merges into the first — the 'MOTOR DATA' tier over
    # HP / VOLTS / # on M-200.00's fan schedules. That is ONE extra band; a
    # schedule with three tiers of heading has not been seen and would be
    # worth looking at rather than silently absorbing.
    #
    # This loop used to run while the predicate said heading, and when the
    # predicate was wrong about a table of prose it ate fourteen rows and left
    # one. The bound is the protection, not the predicate: a wrong predicate
    # now costs a single merged row, which is visible in the output, instead
    # of the whole table, which is not.
    merged = 0
    while rest and merged < 1 and _is_heading_row(rest[0]) and len(rest) > 1:
        header = [" ".join(x for x in (a, b) if x).strip()
                  for a, b in zip(header, rest[0] + [""] * len(header))]
        rest = rest[1:]
        merged += 1
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


# What stands in a cell the two reads could not agree on. Deliberately not a
# number and not blank: blank reads as "the sheet says nothing there", and the
# sheet says plenty — we are the ones who cannot read it.
CONTESTED_CELL = "(readings disagree)"


def read_grid(image_bytes: bytes, grid: Dict[str, Any], dpi: int = OCR_DPI
              ) -> Optional[Dict[str, Any]]:
    """One rendered grid crop -> one schedule, or None when nothing read."""
    boxes = _boxes(image_bytes)
    if not boxes:
        return None
    table, strays, scores = place_in_grid(boxes, grid, dpi)
    sched = schedule_from_table(table, grid)
    if sched is not None:
        sched["ocr_boxes"] = len(boxes)
        sched["ocr_strays"] = strays
        sched["cell_scores"] = scores
    return sched


def _same_but_for_spacing(a: str, b: str) -> bool:
    """Are these the same reading, differing only in spacing or punctuation?

    ── A DIGIT NEVER NORMALISES ───────────────────────────────────────────
    #
    # `6` and `9` differ. So do `1,000` and `1000`, and `9` and `9.0` — one is
    # a count and one is a measurement, and a comma is the difference between
    # a thousand and a one. The whole reason a cell is read twice is that a
    # digit disagreement is real, so any cell carrying one is compared exactly
    # and contested if it differs at all.
    #
    # MEASURED ON THE 588 BOYLAND GRIDS, 2026-09-18: of 117 contested cells,
    # 68 carry a digit, 19 differ only in spacing — `AUXILIARYHEATING CAPACITY
    # (KW)` against `AUXILIARYHEATING CAPACITY(KW)` — and 30 differ in
    # substance, with words reordered or characters mangled. Only the 19 are
    # the same reading twice.
    """
    if any(ch.isdigit() for ch in a) or any(ch.isdigit() for ch in b):
        return False
    strip = lambda t: re.sub(r"[^A-Za-z]", "", t).upper()
    return bool(strip(a)) and strip(a) == strip(b)


def read_grid_twice(image_a: bytes, image_b: bytes, grid: Dict[str, Any],
                    dpi: int = OCR_DPI) -> Optional[Dict[str, Any]]:
    """Two renders of one grid. A cell they disagree on is contested, not guessed.

    ── WHY A GRID IS READ TWICE ───────────────────────────────────────────
    #
    # MEASURED ACROSS EVERY READABLE GRID IN THE 588 BOYLAND SET, 2026-09-18:
    # 57 grids, and 30 of them — more than half — read DIFFERENTLY when the
    # crop changed by two pixels. Eleven differed on a NUMBER. The pipeline's
    # crop happens to be two pixels wider than the grid (the pad in
    # _render_pdf_crop), and that is the whole reason M-200.00's PTAC-2 QTY
    # came back 6 where the sheet prints 9.
    #
    # THE PAD IS NOT THE BUG AND REMOVING IT IS NOT THE FIX. The sweep found
    # 197 tokens only the unpadded crop read and 190 only the padded one did —
    # symmetric. Two grids read a different digit in OPPOSITE directions:
    # M-200.00 reads 9 unpadded and 6 padded, FA-001 reads 6 unpadded and 9
    # padded. There is no better geometry to switch to; the engine is simply
    # unstable at this operating point, and a single read cannot tell a stable
    # cell from a coin-flip.
    #
    # So every grid is read at BOTH geometries and the cells are compared. One
    # that agrees is a reading two independent rasterisations produced — worth
    # more than either alone. One that differs is contested, and nothing
    # downstream will state it as a value.
    #
    # No threshold and no confidence cutoff decides this. The confidence is
    # carried because it is evidence a person may want later, and because it
    # separated cleanly on the one cell we can check by eye — but it is not
    # what picks, because picking is the thing being removed.
    """
    boxes_a, boxes_b = _boxes(image_a), _boxes(image_b)
    if not boxes_a and not boxes_b:
        return None
    # The SAME grid rectangle both times, so the two tables have the same shape
    # and a cell can be compared with its own counterpart.
    table_a, strays_a, scores_a = place_in_grid(boxes_a, grid, dpi)
    table_b, strays_b, scores_b = place_in_grid(boxes_b, grid, dpi)

    merged: List[List[str]] = []
    scores: List[List[float]] = []
    contested: List[Dict[str, Any]] = []
    for r in range(len(table_a)):
        row, srow = [], []
        for c in range(len(table_a[r])):
            a = (table_a[r][c] or "").strip()
            b = (table_b[r][c] or "").strip()
            sa, sb = scores_a[r][c], scores_b[r][c]
            if a == b:
                row.append(a)
                srow.append(max(sa, sb))
                continue
            # ONE SIDE READING NOTHING IS NOT A DISAGREEMENT ABOUT A VALUE.
            # A crop two pixels wider catches a glyph the other clipped; that
            # is the padded read finding a '5' where the unpadded found none,
            # and taking the text is strictly better than taking the blank.
            if not a or not b:
                row.append(a or b)
                srow.append(sa if a else sb)
                continue
            if _same_but_for_spacing(a, b):
                # The fuller reading: one crop caught a separator the other
                # dropped, and there is nothing in dispute about the content.
                row.append(a if len(a) >= len(b) else b)
                srow.append(max(sa, sb))
                continue
            row.append(CONTESTED_CELL)
            srow.append(min(sa, sb))
            # THE MARK, NOT THE ROW NUMBER. schedule_from_table strips the
            # title and header rows, so a table coordinate does not survive
            # into the schedule anything downstream sees. The row's first cell
            # is what identifies it there — the same key elements are built on.
            contested.append({"row": r, "col": c,
                              "mark": (table_a[r][0] or table_b[r][0] or "").strip(),
                              "readings": sorted([a, b]),
                              "scores": [sa, sb]})
        merged.append(row)
        scores.append(srow)

    sched = schedule_from_table(merged, grid)
    if sched is None:
        return None
    sched["ocr_boxes"] = max(len(boxes_a), len(boxes_b))
    sched["ocr_strays"] = max(strays_a, strays_b)
    sched["cell_scores"] = scores
    # Recorded against the MERGED table's own coordinates, so a reader does not
    # have to know how schedule_from_table restructured the rows.
    sched["contested_cells"] = contested
    sched["read_twice"] = True

    # ── A SCHEDULE'S NAME IS NOT A PLACE FOR A MARKER ──────────────────────
    #
    # `_title_and_body` rejoins the title band left to right, so a contested
    # cell in that band became part of the name: one grid came out called
    # `DIFFUSER (readings disagree)`. The name is what the schedule is FOUND
    # by — subject terms, the location hint on every element under it — so a
    # marker there corrupts search rather than informing anyone. The readable
    # part is kept, and a flag says the rest could not be read.
    name = sched.get("name") or ""
    if CONTESTED_CELL in name:
        cleaned = " ".join(name.replace(CONTESTED_CELL, " ").split())
        sched["name"] = cleaned
        sched["name_partly_unread"] = True
    return sched


__all__ = ["available", "why_unavailable", "probe", "grid_is_readable", "place_in_grid",
           "read_grid_twice", "CONTESTED_CELL",
           "schedule_from_table", "read_grid", "OCR_DPI", "MAX_GRID_INCHES",
           "MAX_CELLS"]
