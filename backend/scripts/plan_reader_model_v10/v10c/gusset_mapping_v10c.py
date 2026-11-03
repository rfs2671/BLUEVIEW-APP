# gusset_mapping_v10c.py (Roy v10c ruling 4): map the 20 boxes of sw_panel_heights.csv (S-302, ST - 7.29.26.pdf p12) to the panels behind the 168 gussets (gusset_plates.csv, per track).
# Column assignment of boxes to elevations is by page position (overlay work/v10c/s302_boxes.png). Role: top = top-storey X, mid = cut typical middle-storey X above the 2ND FLOOR line (break line),
# bottom = bottom (1st)-storey X, detailA = a box of DETAIL A (not an X panel).
import csv, collections as C
B = list(csv.DictReader(open('sw_panel_heights.csv')))
ELEV = {1: ('SHEAR WALL 6 & 7', 'top'), 2: ('SHEAR WALL 6 & 7', 'mid'), 3: ('SHEAR WALL 6 & 7', 'bottom'), 4: ('SHEAR WALL 1', 'top'), 5: ('SHEAR WALL 1', 'mid'), 6: ('SHEAR WALL 1', 'bottom'),
        7: ('SHEAR WALL 2', 'top'), 8: ('SHEAR WALL 2', 'mid'), 9: ('SHEAR WALL 2', 'bottom'), 10: ('DETAIL A (3/4"=1\'-0")', 'detailA lower part'), 11: ('SHEAR WALL 3 bay 1 (west)', 'top'), 12: ('SHEAR WALL 3 bay 1 (west)', 'mid'),
        13: ('SHEAR WALL 3 bay 1 (west)', 'bottom'), 14: ('DETAIL A (3/4"=1\'-0")', 'detailA upper part'), 15: ('SHEAR WALL 3 bay 2 (east)', 'top'), 16: ('SHEAR WALL 3 bay 2 (east)', 'mid'), 17: ('SHEAR WALL 3 bay 2 (east)', 'bottom'),
        18: ('SHEAR WALL 4 & 5', 'top'), 19: ('SHEAR WALL 4 & 5', 'mid'), 20: ('SHEAR WALL 4 & 5', 'bottom')}
PAN = {('SHEAR WALL 6 & 7', 'top'): ['SW 6 MEZZANINE to ROOF', 'SW 7 MEZZANINE to ROOF'], ('SHEAR WALL 6 & 7', 'bottom'): ['SW 6 FLOOR_1 to FLOOR_2', 'SW 7 FLOOR_1 to FLOOR_2'],
       ('SHEAR WALL 1', 'top'): ['SW 1 MEZZANINE to ROOF'], ('SHEAR WALL 1', 'bottom'): ['SW 1 FLOOR_1 to FLOOR_2'], ('SHEAR WALL 2', 'top'): ['SW 2 MEZZANINE to ROOF'], ('SHEAR WALL 2', 'bottom'): ['SW 2 FLOOR_1 to FLOOR_2'],
       ('SHEAR WALL 3 bay 1 (west)', 'top'): ['SW 3 bay 1 ROOF to BULKHEAD'], ('SHEAR WALL 3 bay 1 (west)', 'bottom'): ['SW 3 bay 1 FLOOR_1 to FLOOR_2'], ('SHEAR WALL 3 bay 2 (east)', 'top'): ['SW 3 bay 2 ROOF to BULKHEAD'],
       ('SHEAR WALL 3 bay 2 (east)', 'bottom'): ['SW 3 bay 2 FLOOR_1 to FLOOR_2'], ('SHEAR WALL 4 & 5', 'top'): ['SW 4 MEZZANINE to ROOF', 'SW 5 MEZZANINE to ROOF'], ('SHEAR WALL 4 & 5', 'bottom'): ['SW 4 FLOOR_1 to FLOOR_2', 'SW 5 FLOOR_1 to FLOOR_2']}
out = []
for b in B:
    n = int(b['n']); el, role = ELEV[n]; pn = PAN.get((el, role), [])
    out.append(dict(box=n, x0=b['x0'], x1=b['x1'], y0=b['y0'], y1=b['y1'], height_ft=b['height_ft_at_0_0741'], member_kinds=b['kinds'], elevation=el, role=role, panels_covered='; '.join(pn), n_panels=len(pn),
                    disposition=('MAPS to %d of the 16 drawn panels' % len(pn)) if pn else ('NOT one of the 16: cut typical middle-storey X (6.77 ft shown above the break line); its storey panel is a schedule panel (26 of 42)' if role == 'mid' else 'NOT an X panel: part of DETAIL A (gusset-plate detail), no panel')))
with open('gusset_mapping_v10c.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
c = C.Counter(o['disposition'].split(':')[0].split(' (')[0] for o in out); print(c, sum(o['n_panels'] for o in out))
for o in out: print(o['box'], o['elevation'], o['role'], o['n_panels'], o['disposition'][:50])
