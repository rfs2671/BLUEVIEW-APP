# offset_rederive.py (v10c): INDEPENDENT re-derivation of the P-sheet(displayed pt) -> A-frame pt offset recorded as (25.51, 66.04).
# Method: no reference to pitchmap/runs.py. Take the long axis-aligned strokes of the plan underlay on a P sheet (displayed frame) and of the matching A sheet (AR - 3.28.25.pdf, unrotated);
# build length-weighted 1-D profiles of vertical-line x positions and horizontal-line y positions (0.25 pt bins), find the shift maximising the cross-correlation within +/-150 pt.
import fitz, numpy as np, json
def segs(pg, rot):
    V = []; Hh = []
    for p in pg.get_drawings():
        for it in p['items']:
            pts = []
            if it[0] == 'l': pts = [(it[1], it[2])]
            elif it[0] == 're':
                r = it[1]; pts = [(r.tl, r.tr), (r.tr, r.br), (r.br, r.bl), (r.bl, r.tl)]
            for a, b in pts:
                a = fitz.Point(a) * rot; b = fitz.Point(b) * rot
                L = abs(a.x - b.x) + abs(a.y - b.y)
                if L < 20: continue
                if abs(a.x - b.x) < 0.05: V.append((a.x, L))
                elif abs(a.y - b.y) < 0.05: Hh.append((a.y, L))
    return V, Hh
def prof(S, n=2800, b=0.25):
    h = np.zeros(int(n / b))
    for v, L in S:
        i = int(v / b)
        if 0 <= i < len(h): h[i] += L
    return h
def best(hp, ha, maxs=150, b=0.25):
    # shift s such that A = P + s
    bs = None
    for k in range(-int(maxs / b), int(maxs / b) + 1):
        a = np.roll(ha, -k); sc = float((hp * a).sum())
        if bs is None or sc > bs[0]: bs = (sc, k * b)
    return bs
P = fitz.open('C:/Users/asddd/boyland-pdfs/PL - 6.29.26.pdf'); A = fitz.open('C:/Users/asddd/boyland-pdfs/AR - 3.28.25.pdf')
res = {}
for pn, an, nm in [(9, 11, 'P-201 vs A-100'), (10, 12, 'P-202 vs A-101'), (11, 13, 'P-203 vs A-102'), (12, 14, 'P-204 vs A-103'), (13, 15, 'P-205 vs A-104')]:
    vp, hp_ = segs(P[pn - 1], P[pn - 1].rotation_matrix); va, ha_ = segs(A[an - 1], A[an - 1].rotation_matrix)
    sx = best(prof(vp), prof(va)); sy = best(prof(hp_), prof(ha_))
    res[nm] = dict(dx=sx[1], dy=sy[1], nvP=len(vp), nvA=len(va)); print(nm, res[nm], flush=True)
json.dump(res, open('offset_rederive.json', 'w'), indent=1)
