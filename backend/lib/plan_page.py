"""One PDF page, read for the spatial plan reader - pypdfium2 + pdfplumber.

PyMuPDF is AGPL-3.0 and was ruled out for a hosted product
(test_plan_text.test_no_agpl_pdf_library). Everything the space and takeoff
steps need from a page comes from here instead, in DISPLAY space (the page's
/Rotate applied, origin top-left, y down - the frame a person reads):

    drawings  every painted path: {"layer", "items", "rect"}
              items are ("l", p, q) straight segments and ("c", p0, c1, c2, p3)
              cubic curves; "layer" is the optional-content (CAD layer) name
              the path is marked with, "" when none; "rect" its bounding box
    words     [(text, x, y)] - each word's centre
    render()  a crop of the page as a PIL image, for OCR

pypdfium2 (Apache-2.0/BSD) is the renderer pdfplumber already depends on;
pdfplumber (MIT) reads the words. Neither is new to requirements.txt.

A path's layer is the "OC" marked-content its object carries; a path inside
a form XObject with no mark of its own takes the form's.
"""
from __future__ import annotations

import ctypes
import math
from typing import List, Optional, Tuple

#: pdfium path segment types (fpdf_edit.h)
_LINETO, _BEZIERTO, _MOVETO = 0, 1, 2


def _u16(fn, *args) -> Optional[str]:
    ln = ctypes.c_ulong()
    buf = (ctypes.c_ushort * 512)()
    if not fn(*args, buf, ctypes.sizeof(buf), ctypes.byref(ln)):
        return None
    return bytes(buf)[:ln.value].decode("utf-16-le").rstrip("\x00")


def _mul(m, n):
    """m then n, as (a, b, c, d, e, f)."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D,
            e * A + f * C + E, e * B + f * D + F)


class PlanPage:
    """A page of a PDF, opened by path and 1-based page number."""

    def __init__(self, path: str, page_number: int):
        import pypdfium2 as pdfium
        self.path, self.page_number = str(path), int(page_number)
        self._doc = pdfium.PdfDocument(self.path)
        self._pg = self._doc[self.page_number - 1]
        self.rotation = int(self._pg.get_rotation()) % 360
        l, b, r, t = self._pg.get_cropbox()
        self._box = (l, b, r, t)
        uw, uh = r - l, t - b
        self.width, self.height = ((uh, uw) if self.rotation in (90, 270)
                                   else (uw, uh))
        self._drawings = None
        self._words = None

    # ── frames ────────────────────────────────────────────────────────────
    def _to_display(self, x: float, y: float) -> Tuple[float, float]:
        """PDF user space -> display space (rotation applied, y down)."""
        l, b, r, t = self._box
        u, v = x - l, t - y                       # unrotated, top-left origin
        W, H = r - l, t - b
        if self.rotation == 90:
            return H - v, u
        if self.rotation == 180:
            return W - u, H - v
        if self.rotation == 270:
            return v, W - u
        return u, v

    # ── drawings ──────────────────────────────────────────────────────────
    @property
    def drawings(self) -> List[dict]:
        if self._drawings is None:
            self._drawings = self._read_drawings()
        return self._drawings

    def _layer_of(self, obj) -> Optional[str]:
        import pypdfium2.raw as R
        for i in range(R.FPDFPageObj_CountMarks(obj)):
            m = R.FPDFPageObj_GetMark(obj, i)
            if _u16(R.FPDFPageObjMark_GetName, m) == "OC":
                return _u16(R.FPDFPageObjMark_GetParamStringValue, m,
                            b"Name") or ""
        return None

    def _read_drawings(self) -> List[dict]:
        import pypdfium2.raw as R
        out: List[dict] = []

        def matrix(obj):
            fm = R.FS_MATRIX()
            if not R.FPDFPageObj_GetMatrix(obj, ctypes.byref(fm)):
                return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            return (fm.a, fm.b, fm.c, fm.d, fm.e, fm.f)

        def walk(obj, parent_m, parent_layer, depth):
            kind = R.FPDFPageObj_GetType(obj)
            own = self._layer_of(obj)
            layer = own if own is not None else parent_layer
            if kind == R.FPDF_PAGEOBJ_FORM:
                if depth >= 15:
                    return
                m = _mul(matrix(obj), parent_m)
                for i in range(R.FPDFFormObj_CountObjects(obj)):
                    walk(R.FPDFFormObj_GetObject(obj, i), m, layer, depth + 1)
                return
            if kind != R.FPDF_PAGEOBJ_PATH:
                return
            fill, stroke = ctypes.c_int(), ctypes.c_int()
            R.FPDFPath_GetDrawMode(obj, ctypes.byref(fill), ctypes.byref(stroke))
            if not fill.value and not stroke.value:
                return                            # an unpainted path draws nothing
            m = _mul(matrix(obj), parent_m)
            d = self._path_items(obj, m)
            if d:
                d["layer"] = layer or ""
                out.append(d)

        pg = self._pg.raw
        for i in range(R.FPDFPage_CountObjects(pg)):
            walk(R.FPDFPage_GetObject(pg, i), (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
                 None, 0)
        return out

    def _path_items(self, obj, m) -> Optional[dict]:
        import pypdfium2.raw as R
        a, b, c, d, e, f = m

        def pt(i):
            seg = R.FPDFPath_GetPathSegment(obj, i)
            x, y = ctypes.c_float(), ctypes.c_float()
            R.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y))
            raw = (x.value, y.value)
            X, Y = a * raw[0] + c * raw[1] + e, b * raw[0] + d * raw[1] + f
            return seg, raw, self._to_display(X, Y)

        n = R.FPDFPath_CountSegments(obj)
        items, pts = [], []
        start = cur = cur_raw = None
        last = None                               # previous op kind
        i = 0
        while i < n:
            seg, raw, p = pt(i)
            kind = R.FPDFPathSegment_GetType(seg)
            if kind == _MOVETO:
                start, cur, cur_raw = p, p, raw
                pts.append(p)
            elif kind == _LINETO:
                # MuPDF's rule, and the ink's: a lineto to the current point
                # draws nothing unless it follows a moveto (then it is a dot).
                if cur is not None and not (raw == cur_raw and last != _MOVETO):
                    items.append(("l", cur, p))
                cur, cur_raw = p, raw
                pts.append(p)
            elif kind == _BEZIERTO and i + 2 < n:
                p1 = p
                _s2, _r2, p2 = pt(i + 1)
                seg, raw3, p3 = pt(i + 2)
                if cur is not None:
                    items.append(("c", cur, p1, p2, p3))
                cur, cur_raw = p3, raw3
                pts += [p1, p2, p3]
                i += 2
            last = kind
            if (R.FPDFPathSegment_GetClose(seg) and start is not None
                    and cur is not None and math.dist(cur, start) > 1e-3):
                items.append(("l", cur, start))
                cur = start
            i += 1
        if not items:
            return None
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        return {"items": items, "rect": (min(xs), min(ys), max(xs), max(ys))}

    # ── words ─────────────────────────────────────────────────────────────
    @property
    def words(self) -> List[Tuple[str, float, float]]:
        """[(text, x, y)], each word's centre in display space.

        A CAD sheet prints dimension strings along the dimension line, so a
        rotated sheet carries text running in all four directions. pdfplumber
        reads non-upright text in ONE assumed direction (top-to-bottom by
        default), which reversed every bottom-to-top string on A-103.00
        (2'-7" -> "7-'2) and split short ones into letters. So each char's
        reading direction is taken from its own matrix, and each direction
        is read as its own group with that direction.

        IN THE ORDER THE SHEET WROTE IT (use_text_flow): a stacked two-line
        tag (SD over CM, 5.6pt apart, boxes overlapping by 1pt) is split into
        letters when chars are re-sorted by position; the content stream
        writes each line whole.
        """
        if self._words is None:
            import pdfplumber
            with pdfplumber.open(self.path) as pdf:
                page = pdf.pages[self.page_number - 1]
                try:
                    self._words = _words_by_direction(page)
                finally:
                    page.close()
        return self._words

    # ── rendering ─────────────────────────────────────────────────────────
    def render(self, clip: Tuple[float, float, float, float], dpi: int):
        """The display-space rectangle `clip` as an RGB PIL image."""
        x0, y0, x1, y1 = clip
        s = dpi / 72.0
        crop = (max(x0, 0.0), max(self.height - y1, 0.0),
                max(self.width - x1, 0.0), max(y0, 0.0))
        bm = self._pg.render(scale=s, crop=crop, draw_annots=False,
                             may_draw_forms=False)
        return bm.to_pil().convert("RGB")

    def close(self):
        try:
            self._pg.close()
        finally:
            self._doc.close()


#: reading direction -> (char_dir, line_dir) for pdfplumber
_DIRS = {"ltr": ("ltr", "ttb"), "rtl": ("rtl", "ttb"),
         "ttb": ("ttb", "rtl"), "btt": ("btt", "ltr")}


def _char_dir(c) -> str:
    """Display-space reading direction of one char, from its matrix.

    pdfminer's char matrix is in its rotated device space (y up), so the
    baseline (a, b) points (a, -b) on the page as displayed (y down)."""
    a, b = float(c["matrix"][0]), float(c["matrix"][1])
    dx, dy = a, -b
    if abs(dx) >= abs(dy):
        return "ltr" if dx >= 0 else "rtl"
    return "ttb" if dy > 0 else "btt"


def _words_by_direction(page) -> List[Tuple[str, float, float]]:
    groups = {}
    for c in page.chars:
        groups.setdefault(_char_dir(c), set()).add(id(c))
    out = []
    for d, ids in groups.items():
        char_dir, line_dir = _DIRS[d]
        sub = page.filter(lambda o, ids=ids: o.get("object_type") != "char"
                          or id(o) in ids)
        for w in sub.extract_words(char_dir=char_dir, line_dir=line_dir,
                                   char_dir_rotated=char_dir,
                                   line_dir_rotated=line_dir,
                                   use_text_flow=True):
            out.append((w["text"], (w["x0"] + w["x1"]) / 2,
                        (w["top"] + w["bottom"]) / 2))
    return out


def open_page(path: str, page_number: int) -> PlanPage:
    return PlanPage(path, page_number)


def seg_length(s) -> float:
    return math.hypot(s[2] - s[0], s[3] - s[1])
