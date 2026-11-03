# bare_tag_locate.py (v11 K4): locate the bare fixture-tag text found by eye on the 52 leaf crops. OCR = locator only (outlined text, no text layer); the tag was first seen by eye on pitch_v3/leafcrops.
# Window 100 x 60 pt centred on each leaf (displayed P pt), 6x raster, rapidocr; report every token that is exactly the family letters (KS, BT, WC, FD).  PYTHONUTF8=1 python bare_tag_locate.py
import fitz, json, re, numpy as np
from rapidocr_onnxruntime import RapidOCR
eng = RapidOCR(); d = fitz.open('C:/Users/asddd/boyland-pdfs/PL - 6.29.26.pdf'); PG = {'FLOOR_1': 9, 'FLOOR_2': 10, 'FLOOR_3': 11, 'FLOOR_4': 12, 'MEZZANINE': 13}
C = json.load(open('../pitch_v3/leaf_tag_census.json'))
SEEN = {'F1-S-1-KS-1': 'KS', 'F1-S-4-BT-1': 'BT', 'F1-S-4-WC-1': 'WC', 'F1-S-4-KS-1': 'KS', 'F3-S-1-KS-1': 'KS', 'F3-S-1-FD-1': 'FD', 'F3-S-2-KS-1': 'KS', 'F3-S-2-FD-1': 'FD', 'MZ-S-3-FD-1': 'FD'}
out = {}
for r in C:
    if r['id'] not in SEEN: continue
    fam = SEEN[r['id']]; px, py = r['leaf_P_pt']; S = 6; clip = fitz.Rect(px - 50, py - 40, px + 50, py + 40)
    pm = d[PG[r['level']] - 1].get_pixmap(matrix=fitz.Matrix(S, S), clip=clip, colorspace=fitz.csRGB); a = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, 3)
    res, _ = eng(a); hits = []
    for b, t, s in (res or []):
        if re.fullmatch(r'[^A-Z]*' + fam + r'[^A-Z0-9]*', t.upper()) or t.strip().upper() == fam:
            x0 = clip.x0 + min(p[0] for p in b) / S; y0 = clip.y0 + min(p[1] for p in b) / S; x1 = clip.x0 + max(p[0] for p in b) / S; y1 = clip.y0 + max(p[1] for p in b) / S
            hits.append(dict(token=t, x0=round(x0, 1), y0=round(y0, 1), x1=round(x1, 1), y1=round(y1, 1), dist_to_leaf_pt=round(((x0 + x1) / 2 - px) ** 2 + ((y0 + y1) / 2 - py) ** 2, 1) ** .5))
    hits.sort(key=lambda h: h['dist_to_leaf_pt']); out[r['id']] = dict(level=r['level'], family=fam, leaf_P_pt=[px, py], hits=hits); print(r['id'], fam, hits, flush=True)
json.dump(out, open('bare_tag_locate.json', 'w'), indent=1)
