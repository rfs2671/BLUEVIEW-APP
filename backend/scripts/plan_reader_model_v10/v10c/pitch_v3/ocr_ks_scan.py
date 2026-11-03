# ocr_ks_scan.py (v10c): rapidocr over every page of PL - 6.29.26.pdf (text on P-sheets is outlined, no text layer) to find every fixture tag token (KS, BT, LAV, WC, FD ... with or without number).
# Tiles 1100x1100 px at 3x with 150 px overlap; coordinates reported in DISPLAYED page pt (page is /Rotate 270).  OCR is a locator, hits are verified by eye on crops.
import fitz, json, sys, numpy as np
from rapidocr_onnxruntime import RapidOCR
eng = RapidOCR(); d = fitz.open('C:/Users/asddd/boyland-pdfs/PL - 6.29.26.pdf'); S = 3.0; T = 1100; OV = 150
out = []
pages = [int(a) for a in sys.argv[1:]] or range(1, 22)
for pn in pages:
    pg = d[pn - 1]; W, H = pg.rect.width, pg.rect.height; step = (T - OV) / S
    y = 0.0
    while y < H:
        x = 0.0
        while x < W:
            clip = fitz.Rect(x, y, min(x + T / S, W), min(y + T / S, H)); pm = pg.get_pixmap(matrix=fitz.Matrix(S, S), clip=clip, colorspace=fitz.csRGB)
            a = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, 3)
            res, _ = eng(a)
            for box, txt, sc in (res or []):
                xs = [p[0] for p in box]; ys = [p[1] for p in box]
                out.append(dict(page=pn, text=txt, score=round(float(sc), 3), x0=round(x + min(xs) / S, 1), y0=round(y + min(ys) / S, 1), x1=round(x + max(xs) / S, 1), y1=round(y + max(ys) / S, 1)))
            x += step
        y += step
    print('page', pn, len(out), flush=True)
    json.dump(out, open('pitch_v3/ocr_all_pages.json', 'w'))
