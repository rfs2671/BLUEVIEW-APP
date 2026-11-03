# ocr_leaf_tags.py (v10c): fixture tag text on P-201..P-205 is outlined; rapidocr on a 4x crop (240 x 140 pt) centred on each of the 52 mapped leaves (pitch_runs_v2.csv). A-frame pt = (751.08 + 18 x_ft, 1109.7 - 18 y_ft); displayed P pt = A - (25.51, 66.04).
# OCR is a locator only: every token that is not clean "TYPE-N" is verified by eye on the saved crop.
import fitz, csv, json, re, numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
eng = RapidOCR(); d = fitz.open('C:/Users/asddd/boyland-pdfs/PL - 6.29.26.pdf'); PG = {'P-201.00': 9, 'P-202.00': 10, 'P-203.00': 11, 'P-204.00': 12, 'P-205.00': 13}
R = list(csv.DictReader(open('../pitch_v2/pitch_runs_v2.csv', encoding='utf8'))); out = []
import os; os.makedirs('leafcrops', exist_ok=True)
for r in R:
    ax, ay = 751.08 + 18 * float(r['leaf_x_ft']), 1109.7 - 18 * float(r['leaf_y_ft']); px, py = ax - 25.51, ay - 66.04
    clip = fitz.Rect(px - 120, py - 70, px + 120, py + 70); pm = d[PG[r['sheet']] - 1].get_pixmap(matrix=fitz.Matrix(4, 4), clip=clip, colorspace=fitz.csRGB)
    a = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, 3); Image.fromarray(a).save('leafcrops/%s.png' % r['id'])
    res, _ = eng(a); toks = [(t, round(float(s), 2), round(clip.x0 + (min(p[0] for p in b)) / 4, 1), round(clip.y0 + (min(p[1] for p in b)) / 4, 1)) for b, t, s in (res or [])]
    out.append(dict(id=r['id'], level=r['level'], sheet=r['sheet'], fixture_from_pitchmap=r['fixture'], leaf_P_pt=[round(px, 1), round(py, 1)], tokens=toks)); print(r['id'], [t[0] for t in toks], flush=True)
json.dump(out, open('ocr_leaf_tags.json', 'w'), indent=1)
