# offset_rederive2.py (v10c): 2-D segment-overlap check of the candidate offsets. The 1-D y profile has its strongest peak at dy -143.5 (aliasing of repeated horizontals) and a separate peak at +66.25;
# decide by 2-D agreement: for a candidate (dx, dy) count the length of P axis-aligned strokes (>=40 pt) that land on an A stroke (same orientation, within 0.3 pt across, overlapping >= 50% along).
import fitz, numpy as np, json, collections as C
def segl(pg):
    out = []
    for p in pg.get_drawings():
        for it in p['items']:
            pts = []
            if it[0] == 'l': pts = [(it[1], it[2])]
            elif it[0] == 're':
                r = it[1]; pts = [(r.tl, r.tr), (r.tr, r.br), (r.br, r.bl), (r.bl, r.tl)]
            for a, b in pts:
                a = fitz.Point(a) * pg.rotation_matrix; b = fitz.Point(b) * pg.rotation_matrix
                if abs(a.x - b.x) < 0.05 and abs(a.y - b.y) >= 40: out.append(('v', a.x, min(a.y, b.y), max(a.y, b.y)))
                elif abs(a.y - b.y) < 0.05 and abs(a.x - b.x) >= 40: out.append(('h', a.y, min(a.x, b.x), max(a.x, b.x)))
    return out
def score(Sp, Sa, dx, dy):
    idx = C.defaultdict(list)
    for o, c, l0, l1 in Sa: idx[(o, round(c / 0.5))].append((c, l0, l1))
    tot = hit = 0
    for o, c, l0, l1 in Sp:
        s = dx if o == 'v' else dy; t = dy if o == 'v' else dx; cc = c + (dx if o == 'v' else dy); a0 = l0 + t; a1 = l1 + t; L = l1 - l0; tot += L
        best = 0
        for k in (round(cc / 0.5) - 1, round(cc / 0.5), round(cc / 0.5) + 1):
            for c2, m0, m1 in idx.get((o, k), []):
                if abs(c2 - cc) <= 0.3: best = max(best, min(a1, m1) - max(a0, m0))
        if best >= 0.5 * L: hit += L
    return hit / tot
P = fitz.open('C:/Users/asddd/boyland-pdfs/PL - 6.29.26.pdf'); A = fitz.open('C:/Users/asddd/boyland-pdfs/AR - 3.28.25.pdf')
res = {}
for pn, an, nm in [(9, 11, 'P-201 vs A-100'), (10, 12, 'P-202 vs A-101'), (11, 13, 'P-203 vs A-102'), (12, 14, 'P-204 vs A-103'), (13, 15, 'P-205 vs A-104')]:
    Sp = segl(P[pn - 1]); Sa = segl(A[an - 1])
    cands = {'recorded (25.51, 66.04)': (25.51, 66.04), '1-D top (25.5, -143.5)': (25.5, -143.5), 'identity': (0, 0)}
    # refine around 66: 0.05 steps
    ref = max(((score(Sp, Sa, 25.5, 66.0 + k * 0.05), 66.0 + k * 0.05) for k in range(-10, 11)))
    res[nm] = {k: round(score(Sp, Sa, *v), 4) for k, v in cands.items()}; res[nm]['refined_best_dy_near_66'] = [round(ref[1], 2), round(ref[0], 4)]
    print(nm, res[nm], flush=True)
json.dump(res, open('offset_rederive2.json', 'w'), indent=1)
