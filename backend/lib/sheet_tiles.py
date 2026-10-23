"""A deep-zoom tile pyramid for one PDF page.

WHY THIS EXISTS
===============

The app drew a plan by downloading the whole PDF, parsing it in pdf.js inside a
WebView and painting it on a canvas. A dense CAD sheet exceeds the canvas memory
ceiling, pinch-zoom drops frames, and a 100 MB plan set blocks the first paint
until every byte is on the phone. A tile pyramid turns that into "fetch the few
tiles on screen": a page is rendered ONCE, here, into 512 px WebP tiles at five
zoom levels, and every client (iOS, Android, Web) draws only what it is looking at.

THE PYRAMID
===========

Display space (the page's /Rotate applied, origin top-left, y down: the frame a
person reads, the same one plan_page / plan_text / plan_crop use). At level z the
page's LONG side is Z0_LONG * 2**z pixels (z = 0 -> 1024 px ... z = 4 -> 16384 px,
about 455 dpi on a 36 in sheet); the short side keeps the page's aspect. Tile
(z, x, y) is the TILE x TILE pixel square at column x, row y; edge tiles are
SMALLER, never padded, so a tile's size is always implied by the level's size.

A level that is deeper than the sheet can use is not built: the deepest level is
chosen so the render is at most TARGET_DPI (a letter-size page needs z = 2, not 4).

A tile that is entirely white is NOT stored. The level's `present` bitmap (row
major, least-significant bit first, base64) says which tiles exist, so a client
never requests a blank one. CAD sheets are mostly white; this is most of the
saving.

HOW IT IS RENDERED
==================

pypdfium2 (Apache-2.0/BSD, already pinned in constraints.txt for plan_page) -
NEVER PyMuPDF, which is AGPL-3.0 and was ruled out for the hosted product
(test_plan_text.test_no_agpl_pdf_library). Each level is rendered in BANDS of
BAND_ROWS pixel rows, so a 16384 px level never needs a 700 MB bitmap in memory;
a band is cut into tiles and discarded.

Lower levels are rendered at their own scale (not downsampled from the top), so
a thin line is as crisp at z = 1 as pdfium can draw it.

PURE EXCEPT THE RENDER. Geometry, blank detection and the bitmap are plain
functions with tests that need no PDF; `compile_page` takes callbacks for storage
(`put_tile`, `put_preview`) so the same code writes to R2, to a directory, or to
a test's dict.

Run as a subprocess by the server (a pdfium crash or a memory spike must not take
the API with it):

    python -m lib.sheet_tiles info    <pdf>
    python -m lib.sheet_tiles compile <pdf> <page> <out_dir> [--levels 0-2]
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from lib.pdfium_lock import PDFIUM_LOCK

__all__ = ["TILE", "Z0_LONG", "MAX_Z", "level_geometry", "choose_max_z", "pyramid",
           "is_blank", "present_bitmap", "bit_is_set", "compile_page", "page_sizes", "parse_levels",
           "SCHEMA"]

SCHEMA = 1
TILE = 512
Z0_LONG = 1024            # the page's long side, in pixels, at z = 0
MAX_Z = 4                 # z = 0..4 -> 1024 .. 16384 px
MAX_SIDE = 16384
TARGET_DPI = 400          # a level is built only while it is at most this sharp
BAND_ROWS = 1024          # pixel rows rendered at once (two tile rows)
# A band is at most width x BAND_ROWS pixels, so the biggest bitmap pdfium ever holds is
# 16384 x 1024 x 4 = 64 MB (never the 1 GB+ of a whole 16384 x 16384 level). The cap below
# is the guard: a band that would be larger is cut into fewer rows, or refused.
MAX_BAND_BYTES = 96 * 1024 * 1024
WEBP_QUALITY = 86
PREVIEW_LONG = 512
PREVIEW_QUALITY = 70
BLANK_MIN = 250           # every channel of every pixel at least this: the tile is blank


# ── geometry (pure) ──────────────────────────────────────────────────────────

def choose_max_z(width_pt: float, height_pt: float) -> int:
    """The deepest level worth building for a page this size: the render is no
    sharper than TARGET_DPI and no larger than MAX_SIDE."""
    long_in = max(width_pt, height_pt) / 72.0
    target = max(Z0_LONG, min(MAX_SIDE, long_in * TARGET_DPI))
    return max(0, min(MAX_Z, int(round(math.log2(target / Z0_LONG)))))


def level_geometry(width_pt: float, height_pt: float, z: int) -> Dict[str, Any]:
    """{z, width, height, cols, rows, scale} of level `z`: pixels, tiles, and the
    pdfium scale (pixels per PDF point) that renders it."""
    long_pt = max(width_pt, height_pt)
    long_px = Z0_LONG * (2 ** z)
    scale = long_px / long_pt
    width = max(1, int(round(width_pt * scale)))
    height = max(1, int(round(height_pt * scale)))
    return {"z": z, "width": width, "height": height,
            "cols": -(-width // TILE), "rows": -(-height // TILE), "scale": scale}


def pyramid(width_pt: float, height_pt: float) -> List[Dict[str, Any]]:
    return [level_geometry(width_pt, height_pt, z) for z in range(choose_max_z(width_pt, height_pt) + 1)]


def tile_box(level: Dict[str, Any], x: int, y: int) -> Tuple[int, int, int, int]:
    """(left, top, right, bottom) pixels of tile (x, y) in its level; the edge
    tiles end at the level's edge."""
    return (x * TILE, y * TILE, min((x + 1) * TILE, level["width"]), min((y + 1) * TILE, level["height"]))


# ── blank tiles and the presence bitmap (pure) ───────────────────────────────

def is_blank(im: Any) -> bool:
    """True when every channel of every pixel is at least BLANK_MIN: nothing is
    drawn, so nothing is stored."""
    return all(lo >= BLANK_MIN for lo, _hi in im.convert("RGB").getextrema())


def present_bitmap(cols: int, rows: int, present: Iterable[Tuple[int, int]]) -> str:
    """base64 of a row-major, least-significant-bit-first bitmap: bit (y * cols + x)
    is set when tile (x, y) exists."""
    buf = bytearray(-(-(cols * rows) // 8))
    for x, y in present:
        i = y * cols + x
        buf[i >> 3] |= 1 << (i & 7)
    return base64.b64encode(bytes(buf)).decode("ascii")


def bit_is_set(b64: str, cols: int, x: int, y: int) -> bool:
    raw = base64.b64decode(b64 or "")
    i = y * cols + x
    return (i >> 3) < len(raw) and bool(raw[i >> 3] & (1 << (i & 7)))


def parse_levels(spec: Optional[str], z_max: int) -> List[int]:
    """"0-2" / "3,4" / "all" / None -> the levels asked for, inside 0..z_max."""
    if not spec or spec == "all":
        return list(range(z_max + 1))
    out: List[int] = []
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a), int(b) + 1)
        elif part:
            out.append(int(part))
    return sorted({z for z in out if 0 <= z <= z_max})


# ── the render ───────────────────────────────────────────────────────────────

def _open_pdf(source: Any):
    import pypdfium2 as pdfium          # lazily: the geometry above needs no PDF library
    with PDFIUM_LOCK:
        return pdfium.PdfDocument(source)


def band_rows(width: int) -> int:
    """Pixel rows to render at once for a level `width` pixels wide: BAND_ROWS, or fewer
    (a multiple of TILE) so that width x rows x 4 bytes stays under MAX_BAND_BYTES."""
    fit = (MAX_BAND_BYTES // (max(1, width) * 4)) // TILE * TILE
    if fit < TILE:
        raise ValueError(f"a level {width}px wide cannot be rendered in a {MAX_BAND_BYTES >> 20} MB band")
    return min(BAND_ROWS, fit)


def page_sizes(source: Any) -> List[Tuple[float, float]]:
    """[(width_pt, height_pt)] per page in DISPLAY space (rotation applied)."""
    pdf = _open_pdf(source)
    try:
        out = []
        for i in range(len(pdf)):
            with PDFIUM_LOCK:
                page = pdf[i]
                try:
                    out.append(tuple(float(v) for v in page.get_size()))
                finally:
                    page.close()
        return out
    finally:
        with PDFIUM_LOCK:
            pdf.close()


def _fit(im: Any, width: int, height: int) -> Any:
    """`im` as exactly width x height: cut off what pdfium rounded up, pad white
    what it rounded down. Never resamples."""
    from PIL import Image
    if im.size == (width, height):
        return im
    out = Image.new("RGB", (width, height), (255, 255, 255))
    out.paste(im.crop((0, 0, min(width, im.width), min(height, im.height))), (0, 0))
    return out


def _render_rows(page: Any, level: Dict[str, Any], width_pt: float, height_pt: float, y0: int, y1: int) -> Any:
    """Pixel rows [y0, y1) of `level`, as an RGB image width x (y1 - y0).

    crop is the margin to cut off each page edge, in PDF points, applied to the
    DISPLAY page (rotation first): (left, bottom, right, top)."""
    scale = level["scale"]
    top = max(0.0, y0 / scale)
    bottom = max(0.0, height_pt - y1 / scale)
    if level["width"] * (y1 - y0) * 4 > MAX_BAND_BYTES:
        raise ValueError(f"a {level['width']} x {y1 - y0} band exceeds {MAX_BAND_BYTES >> 20} MB")
    with PDFIUM_LOCK:
        bm = page.render(scale=scale, crop=(0, bottom, 0, top))
        try:
            im = bm.to_pil().convert("RGB")
        finally:
            bm.close()
    return _fit(im, level["width"], y1 - y0)


def _webp(im: Any, quality: int) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="WEBP", quality=quality, method=4)
    return buf.getvalue()


def compile_page(source: Any, page_index: int,
                 put_tile: Callable[[int, int, int, bytes], None],
                 put_preview: Optional[Callable[[bytes, int, int], None]] = None,
                 levels: Optional[Sequence[int]] = None,
                 progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Render one page into its tile pyramid.

    put_tile(z, x, y, webp_bytes) is called for every tile that has anything
    drawn on it. put_preview(webp_bytes, width, height) is called once (when
    `levels` is None or contains 0). progress(done_levels, total_levels).
    Returns the manifest for the levels built:

        {"schema", "tile", "width_pt", "height_pt", "z_max",
         "levels": [{"z", "width", "height", "cols", "rows", "tiles", "present"}],
         "preview": {"width", "height"} | None}
    """
    from PIL import Image
    pdf = _open_pdf(source)
    try:
        if not 0 <= page_index < len(pdf):
            raise IndexError(f"page {page_index} is not in a {len(pdf)}-page document")
        with PDFIUM_LOCK:
            page = pdf[page_index]
        try:
            with PDFIUM_LOCK:
                width_pt, height_pt = (float(v) for v in page.get_size())
            if width_pt <= 0 or height_pt <= 0:
                raise ValueError("page has no size")
            full = pyramid(width_pt, height_pt)
            z_max = len(full) - 1
            want = list(levels) if levels is not None else list(range(z_max + 1))
            built: List[Dict[str, Any]] = []
            for n, z in enumerate(want):
                if not 0 <= z <= z_max:
                    continue
                level = full[z]
                present: List[Tuple[int, int]] = []
                rows_at_once = band_rows(level["width"])
                for y0 in range(0, level["height"], rows_at_once):
                    y1 = min(y0 + rows_at_once, level["height"])
                    band = _render_rows(page, level, width_pt, height_pt, y0, y1)
                    for ty in range(y0 // TILE, -(-y1 // TILE)):
                        for tx in range(level["cols"]):
                            l, t, r, b = tile_box(level, tx, ty)
                            tile = band.crop((l, t - y0, r, b - y0))
                            if is_blank(tile):
                                continue
                            put_tile(z, tx, ty, _webp(tile, WEBP_QUALITY))
                            present.append((tx, ty))
                    del band
                built.append({"z": z, "width": level["width"], "height": level["height"],
                              "cols": level["cols"], "rows": level["rows"], "tiles": len(present),
                              "present": present_bitmap(level["cols"], level["rows"], present)})
                if progress:
                    progress(n + 1, len(want))
            preview = None
            if put_preview and (levels is None or 0 in want):
                scale = PREVIEW_LONG / max(width_pt, height_pt)
                with PDFIUM_LOCK:
                    bm = page.render(scale=scale)
                    try:
                        pim = bm.to_pil().convert("RGB")
                    finally:
                        bm.close()
                put_preview(_webp(pim, PREVIEW_QUALITY), pim.width, pim.height)
                preview = {"width": pim.width, "height": pim.height}
            return {"schema": SCHEMA, "tile": TILE, "width_pt": width_pt, "height_pt": height_pt,
                    "z_max": z_max, "levels": built, "preview": preview}
        finally:
            with PDFIUM_LOCK:
                page.close()
    finally:
        with PDFIUM_LOCK:
            pdf.close()


# ── command line: the server runs this in a subprocess ───────────────────────

def _main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m lib.sheet_tiles")
    sub = ap.add_subparsers(dest="cmd", required=True)
    info = sub.add_parser("info")
    info.add_argument("pdf")
    comp = sub.add_parser("compile")
    comp.add_argument("pdf")
    comp.add_argument("page", type=int)
    comp.add_argument("out")
    comp.add_argument("--levels", default="all")
    args = ap.parse_args(argv)
    if args.cmd == "info":
        sizes = page_sizes(args.pdf)
        print(json.dumps({"pages": [{"width_pt": w, "height_pt": h, "z_max": choose_max_z(w, h)} for w, h in sizes]}))
        return 0
    os.makedirs(args.out, exist_ok=True)

    def put_tile(z: int, x: int, y: int, data: bytes) -> None:
        d = os.path.join(args.out, f"z{z}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{x}_{y}.webp"), "wb") as f:
            f.write(data)

    def put_preview(data: bytes, w: int, h: int) -> None:
        with open(os.path.join(args.out, "preview.webp"), "wb") as f:
            f.write(data)

    z_max = choose_max_z(*page_sizes(args.pdf)[args.page])
    manifest = compile_page(args.pdf, args.page, put_tile, put_preview, levels=parse_levels(args.levels, z_max))
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    print(json.dumps({"ok": True, "levels": [l["z"] for l in manifest["levels"]],
                      "tiles": sum(l["tiles"] for l in manifest["levels"])}))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
