"""Verify every refused->bound claim against the crop-read word boxes (crop_a400/words.json, panel regions B from crop_a400/map.py):
the claim's figure must be printed by a word inside that type's OWN panel region. argv: base vgrid, new vgrid, out json [extra claims json]"""
import json, re, sys, fitz
base = json.load(open(sys.argv[1])); new = json.load(open(sys.argv[2]))
W = json.load(open("C:/Users/asddd/bv-worktrees/crop_a400/words.json"))
M = fitz.open("C:/Users/asddd/boyland-pdfs/AR - 3.28.25.pdf")[22].rotation_matrix
B = {'W1':(120,60,410,640),'W2':(410,60,670,640),'W3':(670,60,940,640),'A':(1040,60,1280,660),'B':(1280,60,1510,660),
     'C':(1510,60,1730,660),'D':(1730,60,1960,660),'E':(1960,60,2240,660),'F':(1730,690,1960,1250),'G':(1960,690,2240,1250),
     'D1':(120,720,390,1210),'D2':(390,720,690,1210)}
# the crop-read regions stop above the U / SHGC line of each type: extend those bottoms (same x extent)
for _t, _y in (('W1',662),('W2',662),('W3',662),('D1',1300),('D2',1300)): B[_t] = (B[_t][0], B[_t][1], B[_t][2], _y)
def disp(x):
    r = fitz.Rect(x[:4]) * M; r.normalize(); return r
ws = [(disp(x), x[4]) for x in W]
def fix(s):   # the OCR'd rotated dimension reads backwards: "0-'5 is 5'-0"
    return s[::-1] if s.startswith('"') else s
def panel_words(t):
    R = fitz.Rect(*B[t]); return [(r, s) for r, s in ws if R.contains(fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))]
def norm(f): return re.sub(r"\s+", "", f.rstrip(".")).replace("\u201d", '"')
def verify(t, fig):
    if re.search(r"\sX\s", fig):      # "2'-10\" X 6'-8\"": each printed dimension is a word box of the panel
        parts = [verify(t, q) for q in re.split(r"\sX\s", fig)]
        return (parts[0][0] if all(p[1] for p in parts) else None), [b for p in parts for b in p[1]]
    f = norm(fig); hits = []
    for r, s in panel_words(t):
        s2 = norm(fix(s))
        if s2 == f: hits.append(("exact", s, r))
    if not hits:
        for r, s in panel_words(t):
            s2 = norm(fix(s))
            if re.search(r"(?<![\d.])" + re.escape(f.rstrip('"')) + r"(?![\d])", s2): hits.append(("fragment", s, r))
    kind = hits[0][0] if hits else None
    return kind, [f"{s}@({round(r.x0)},{round(r.y0)},{round(r.x1)},{round(r.y1)})" for _k, s, r in hits[:4]]
key = lambda x: (x["sched"], x["tag"], tuple(x["cell"]), x["fig"], x["claim"])
b = {key(x): x["bound"] for x in base}
flips = [x for x in new if x["bound"] and not b.get(key(x), False)]
lost = [x for x in new if not x["bound"] and b.get(key(x), False)]
out = []
for x in flips:
    kind, boxes = verify(x["tag"], x["fig"])
    out.append({"claim": x["claim"], "type": x["tag"], "figure": x["fig"], "match": kind, "boxes": boxes, "ok": bool(boxes)})
json.dump({"refused_to_bound": out, "bound_to_refused": [x["claim"] for x in lost]}, open(sys.argv[3], "w"), indent=1)
print("refused->bound", len(out), "verified", sum(o["ok"] for o in out), "UNVERIFIED", [(o["claim"]) for o in out if not o["ok"]], "bound->refused", len(lost))
