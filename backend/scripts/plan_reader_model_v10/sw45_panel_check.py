# Step: can the SW 4&5 lower panel be upgraded to measured_from_drawing?
# Reuses the quad search of model_export_v09b/strap_count_v09b.py (SET_STEEL_JOIST layer, 'qu' items) and dumps the COORDINATES of the SW4&5 quads,
# groups them into X (pairs sharing a bbox), orders by page y, and draws them over the S-302 elevation so they can be compared with the by-eye reading.
import fitz, json, collections
d = fitz.open('C:/Users/asddd/boyland-pdfs/ST - 7.29.26.pdf'); p = d[11]
BOX = (1740, 1875, 100, 700)
Q = []
for x in p.get_drawings():
    if x.get('layer') != 'SET_STEEL_JOIST': continue
    for it in x['items']:
        if it[0] == 'qu':
            q = it[1]; xs = [q.ul.x, q.ur.x, q.lr.x, q.ll.x]; ys = [q.ul.y, q.ur.y, q.lr.y, q.ll.y]
            bb = (min(xs), max(xs), min(ys), max(ys))
            if BOX[0] <= bb[0] and bb[1] <= BOX[1] and BOX[2] <= bb[2] and bb[3] <= BOX[3]: Q.append((bb, [(round(q.ul.x,1),round(q.ul.y,1)),(round(q.ur.x,1),round(q.ur.y,1)),(round(q.lr.x,1),round(q.lr.y,1)),(round(q.ll.x,1),round(q.ll.y,1))]))
G = collections.defaultdict(list)
for bb, pts in Q: G[(round(bb[0] / 8), round(bb[2] / 8))].append((bb, pts))
Xs = []
for k, v in G.items():
    if len(v) == 2:
        bbs = [a[0] for a in v]; Xs.append(dict(x0=round(min(b[0] for b in bbs), 1), x1=round(max(b[1] for b in bbs), 1), y0=round(min(b[2] for b in bbs), 1), y1=round(max(b[3] for b in bbs), 1), quads=[a[1] for a in v]))
Xs.sort(key=lambda a: a['y0'])
for i, a in enumerate(Xs): a['order_from_top'] = i + 1; a['height_pt'] = round(a['y1'] - a['y0'], 1); a['height_ft_at_0.0741'] = round((a['y1'] - a['y0']) * 0.0741, 2)
json.dump(dict(quads=len(Q), X=Xs), open('work/sw45_panel_check.json', 'w'), indent=1)
print(len(Q), 'quads;', len(Xs), 'X')
for a in Xs: print({k: a[k] for k in ('order_from_top', 'x0', 'x1', 'y0', 'y1', 'height_pt', 'height_ft_at_0.0741')})
# overlay
shape = p.new_shape()
for a in Xs:
    shape.draw_rect(fitz.Rect(a['x0'], a['y0'], a['x1'], a['y1'])); shape.finish(color=(1, 0, 0), width=3)
shape.commit()
clip = fitz.Rect(1700, 80, 1920, 720)
p.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), clip=clip).save('work/sw45_overlay.png')
