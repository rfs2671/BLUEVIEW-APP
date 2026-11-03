# make_pitch_v3.py (v10c, Roy ruling 6): single lowest point per level = MINIMUM of the pitch_v2 sensitivity range (stable plateau, all slope assumptions); KS binding for FLOOR_3; run table with updated status.
import csv, json
R = list(csv.DictReader(open('../pitch_v2/pitch_runs_v2.csv', encoding='utf8')))
FLOOR = {'FLOOR_1': 33.37, 'FLOOR_2': 43.37, 'FLOOR_3': 53.37, 'FLOOR_4': 63.37, 'MEZZANINE': 73.37}
MIN = {'FLOOR_1': (42.1515, 'trunk 2in (1/4) bracket, branch as printed'), 'FLOOR_2': (52.1612, 'trunk 2in (1/4) bracket, branch as printed'), 'FLOOR_3': (61.9758, 'trunk 2in (1/4) bracket, branch as printed (KS-1 2in branch)'),
       'FLOOR_4': (72.1568, 'trunk 2in (1/4) bracket, branch as printed'), 'MEZZANINE': (81.9441, 'all drops at 1/4 in/ft (FD-1 3in branch taken at 1/4 instead of the printed-tier 1/8): an assumption bound, not the printed tier')}
RANGE = {'FLOOR_1': (42.1515, 42.2295), 'FLOOR_2': (52.1612, 52.2343), 'FLOOR_3': (61.9758, 62.1416), 'FLOOR_4': (72.1568, 72.2321), 'MEZZANINE': (81.9441, 82.0425)}
L = []
for lv, (v, why) in MIN.items():
    L.append(dict(level=lv, lowest_point_navd_ft=v, range_min=RANGE[lv][0], range_max=RANGE[lv][1], aff_in=round((v - FLOOR[lv]) * 12, 1), status='derived_from_printed', set_status='provisional', min_scenario=why,
                  convention='NOT printed: pipe top at structure underside at the high end, nominal 4 in pipe at the stack end; grades are printed "at least", so each figure is an upper bound on the elevation'))
with open('pitch_lowest_v3.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.DictWriter(f, fieldnames=list(L[0])); w.writeheader(); w.writerows(L)
out = []
for r in R:
    r = dict(r); r['key_note_ref'] = r['key_note_ref']
    if r['fixture'] == 'KS-1' and r['level'] == 'FLOOR_3':
        r['tag_status'] = 'tag_printed_without_number_only_KS_type_in_key'; r['tag_as_printed'] = 'KS'; r['bound_type'] = 'KS-1 (2 in SAN DROP, key note 2)'
        r['level_status'] = 'derived_from_printed'; r['used_rule'] = 'KS bare tag bound as KS-1 (only KS type in any P-sheet key note / schedule); 2 in drop (1/4 in/ft branch tier); not clipped, nothing hidden'
        r['drop_in_used'] = r['drop_in']; r['lowest_pt_navd_ft_used'] = r['lowest_pt_navd_ft']
    elif r['level'] == 'FLOOR_3':
        r['level_status'] = 'derived_from_printed'; r['used_rule'] = 'headline (trunk 1/8); FLOOR_3 provisional flag from pitch_v2 removed (KS bound as KS-1)'; r['drop_in_used'] = r['drop_in']; r['lowest_pt_navd_ft_used'] = r['lowest_pt_navd_ft']
    out.append(r)
with open('pitch_runs_v3.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]) if 'tag_status' in out[0] else sorted({k for o in out for k in o}, key=lambda k: list(out[0]).index(k) if k in out[0] else 999)); 
    ks = sorted({k for o in out for k in o}, key=lambda k: list(R[0]).index(k) if k in R[0] else 999)
    w = csv.DictWriter(f, fieldnames=ks, restval=''); w.writeheader(); w.writerows(out)
print(open('pitch_lowest_v3.csv').read())
