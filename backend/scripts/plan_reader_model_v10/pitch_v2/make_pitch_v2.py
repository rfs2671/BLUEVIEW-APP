# pitch_v2/make_pitch_v2.py: pitch_runs_v2.csv = pitchmap/pitch_runs.csv + key-note citations (sheet, displayed-page pt, A-frame pt) + FLOOR_3 provisional/larger drop; KS tag crops for FLOOR_3.
import csv, json, fitz, numpy as np
from PIL import Image, ImageDraw, ImageFont
PDF = 'C:/Users/asddd/boyland-pdfs/PL - 6.29.26.pdf'; OFF = (25.51, 66.04)   # P-sheet -> A-frame offset as recorded in pitchmap/REPORT.md item 7 (not re-derived here)
X0, Y0 = 751.08, 1109.7                                                       # pitchmap/runs.py: A-frame pt = (X0 + 18*x_ft, Y0 - 18*y_ft)
d = fitz.open(PDF); pg = d[10]
# --- key notes (text is outlined, no text layer): bbox per note from pixel rows of the render, displayed page pt (page is /Rotate 270; pt as shown on screen)
clip = fitz.Rect(1630, 1440, 1995, 1722); S = 4
pm = pg.get_pixmap(matrix=fitz.Matrix(S, S), clip=clip, colorspace=fitz.csGRAY); a = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width); dark = a < 128
col = dark[:, :int(60 * S)].sum(axis=1); rows = np.where(col > 0)[0]; blocks = []; st = pv = rows[0]
for r in rows[1:]:
    if r - pv > 6: blocks.append((st, pv)); st = r
    pv = r
blocks.append((st, pv)); circ = [(clip.y0 + b0 / S, clip.y0 + b1 / S) for b0, b1 in blocks if (b1 - b0) / S > 9]
assert len(circ) == 5, circ
tops = [c[0] - 1 for c in circ] + [1708]; NB = {}
for i in range(5):
    y0 = tops[i]; y1 = tops[i + 1] - (8 if i < 4 else 0); sub = dark[int((y0 - clip.y0) * S):int((y1 - clip.y0) * S)]
    xs = np.where(sub.any(axis=0))[0]; ys = np.where(sub.any(axis=1))[0]
    NB[i + 1] = [round(clip.x0 + xs.min() / S, 1), round(y0 + ys.min() / S, 1), round(clip.x0 + xs.max() / S, 1), round(y0 + ys.max() / S, 1)]
json.dump(NB, open('key_note_bboxes_P203_displayed_pt.json', 'w'))
def A(b): return [round(b[0] + OFF[0], 1), round(b[1] + OFF[1], 1), round(b[2] + OFF[0], 1), round(b[3] + OFF[1], 1)]
NOTE = {'WC-1': 1, 'KS-1': 2, 'LAV-1': 2, 'FD-1': 3}
# identical key-note region on P-201..P-205 (checked by md5 of the 4x render: all five equal)
import hashlib
hs = set()
for pn in (9, 10, 11, 12, 13): hs.add(hashlib.md5(d[pn - 1].get_pixmap(matrix=fitz.Matrix(S, S), clip=clip, colorspace=fitz.csGRAY).samples).hexdigest())
assert len(hs) == 1, hs
SHEETPAGE = {'P-201.00': 9, 'P-202.00': 10, 'P-203.00': 11, 'P-204.00': 12, 'P-205.00': 13}
R = list(csv.DictReader(open('C:/Users/asddd/bv-worktrees/pitchmap/pitch_runs.csv', encoding='utf8')))
out = []
for r in R:
    f = r['fixture']
    if f in NOTE:
        n = NOTE[f]; ref = 'key note %d on %s (PL - 6.29.26.pdf p%d)' % (n, r['sheet'], SHEETPAGE[r['sheet']]); pb = NB[n]; ab = A(pb)
    else:
        ref = 'P-301.00 riser diagram label (not a key note); coordinates NOT captured (outlined text)'; pb = ab = ''
    r['key_note_ref'] = ref; r['key_note_bbox_P_displayed_pt'] = pb; r['key_note_bbox_A_frame_pt'] = ab
    r['wc1_conflict'] = 'key note 1 prints 3" drop; P-301 prints 4" on the branch: both in the 3"-or-larger tier (1/8 in/ft), no number changes' if f == 'WC-1' else ''
    d1, d2 = float(r['drop_in']), float(r['drop_in_if_trunk_2in'])
    if r['level'] == 'FLOOR_3':
        r['level_status'] = 'provisional'; r['drop_in_used'] = max(d1, d2); r['lowest_pt_navd_ft_used'] = round(min(float(r['lowest_pt_navd_ft']), float(r['lowest_pt_navd_ft_trunk_bracket'])), 4)
        r['used_rule'] = 'FLOOR_3 provisional (KS tag number clipped): LARGER of headline and trunk-2in drop'
    else:
        r['level_status'] = 'derived_from_printed'; r['drop_in_used'] = d1; r['lowest_pt_navd_ft_used'] = r['lowest_pt_navd_ft']; r['used_rule'] = 'headline (trunk 1/8)'
    out.append(r)
w = csv.DictWriter(open('pitch_runs_v2.csv', 'w', newline='', encoding='utf8'), fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
# --- crops of the FLOOR_3 KS-1 leaves (the two 14.4-14.6 ft branches), 300 dpi, labelled
def crop(name, xft, yft, label):
    ax, ay = X0 + 18 * xft, Y0 - 18 * yft; px, py = ax - OFF[0], ay - OFF[1]
    box = fitz.Rect(px - 120, py - 60, px + 120, py + 60)
    s = 300 / 72; p = pg.get_pixmap(matrix=fitz.Matrix(s, s), clip=box); p.save('_tmp.png')
    im = Image.open('_tmp.png').convert('RGB'); W, H = im.size; pad = 175; can = Image.new('RGB', (W, H + pad), 'white'); can.paste(im, (0, pad)); dr = ImageDraw.Draw(can)
    try: ft = ImageFont.truetype('arial.ttf', 18)
    except Exception: ft = ImageFont.load_default()
    L = ['%s' % label, 'PL - 6.29.26.pdf p11, sheet P-203.00 THIRD FLOOR SANITARY & STORM PLAN, 300 dpi',
         'crop box, displayed P-sheet pt x %.0f-%.0f, y %.0f-%.0f (A-frame = P + (25.51, 66.04): x %.0f-%.0f, y %.0f-%.0f)' % (box.x0, box.x1, box.y0, box.y1, box.x0 + OFF[0], box.x1 + OFF[0], box.y0 + OFF[1], box.y1 + OFF[1]),
         'leaf end (pitchmap) A-frame ft (%.2f, %.2f) = A pt (%.1f, %.1f) = P pt (%.1f, %.1f), crop centre' % (xft, yft, ax, ay, px, py),
         'red ticks every 10 pt of displayed P-sheet pt; read the KS tag number by eye']
    for i, t in enumerate(L): dr.text((8, 6 + i * 28), t, fill='black', font=ft)
    for k in range(int(box.x0 // 10 + 1) * 10, int(box.x1), 10):
        x = (k - box.x0) * s; dr.line([(x, pad), (x, pad + 14)], fill='red', width=2)
        if k % 20 == 0: dr.text((x + 2, pad + 14), str(k), fill='red', font=ft)
    for k in range(int(box.y0 // 10 + 1) * 10, int(box.y1), 10):
        y = pad + (k - box.y0) * s; dr.line([(0, y), (14, y)], fill='red', width=2)
        if k % 20 == 0: dr.text((16, y - 10), str(k), fill='red', font=ft)
    can.save(name); print(name, can.size, box)
crop('F3_KS_tag_crop_S2_leaf.png', 27.73, 0.67, 'FLOOR_3 KS-1 leaf of stack S-2 (F3-S-2-KS-1, 15.92 ft)')
crop('F3_KS_tag_crop_S1_leaf.png', 27.66, 34.71, 'FLOOR_3 KS-1 leaf of stack S-1 (F3-S-1-KS-1, 15.86 ft)')
import os; os.remove('_tmp.png')
print(NB)
