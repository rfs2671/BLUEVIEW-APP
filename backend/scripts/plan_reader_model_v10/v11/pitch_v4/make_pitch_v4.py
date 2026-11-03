# make_pitch_v4.py (v11, Roy K3 + K4). Inputs: pitch_v3/pitch_runs_v3.csv, pitch_v3/leaf_tag_census.json, bare_tag_locate.json + the by-eye reads recorded below.
# Run: cd pitch_v4 ; PYTHONUTF8=1 python make_pitch_v4.py   (needs C:/Users/asddd/bv-worktrees/pitchmap/runs.py + model_c/now_snapshot.json for the run paths)
# K4 rule (Roy): bind a bare leaf tag by FAMILY only where the P-200..P-205 key notes list exactly one type for that family.
# Key notes were read from the RENDER (PL - 6.29.26.pdf has no text layer for them): keynotes/P200..P205_keynotes.png. P-201..P-205 key-note block md5-identical; P-200 same text.
import csv, json, math, sys, heapq, collections as C
sys.path.insert(0, 'C:/Users/asddd/bv-worktrees/pitchmap'); import runs as RU
OFFS = (25.51, 66.04)   # A-frame = displayed P pt + OFFS (pitch_v3 offset, confirmed)
KEY_NOTES = {1: ('3in SAN DROP, 2in VENT RISE', ['WC-1']), 2: ('2in SAN DROP, 2in VENT RISE', ['KS-1', 'LAV-1', 'LAV-3', 'SH-1', 'SS-1', 'MS-1']), 3: ('3in SAN DROP, 2in VENT RISE', ['FD-1']),
             4: ('2in STAND PIPE, 2in VENT RISE', ['WMB-1']), 5: ('2in STAND PIPE, 2in VENT RISE', ['EDF-1'])}
FAMILY = C.defaultdict(list)
for n, (txt, types) in KEY_NOTES.items():
    for t in types: FAMILY[t.split('-')[0]].append((t, n))
# BT: NOT in any key note (BT-1 appears only on the P-301 riser diagram, 2in label)
LOC = json.load(open('bare_tag_locate.json'))
EYE = {'F1-S-1-KS-1': ('KS', (1120.4, 582.9, 1127.5, 589.0), 'by eye on 7x grid crop'), 'F1-S-4-WC-1': ('WC', (1642.1, 843.6, 1650.0, 849.8), 'by eye on 7x grid crop'),
       'F3-S-1-KS-1': ('KS', (1210.4, 411.6, 1217.5, 418.0), 'by eye on 7x grid crop'), 'MZ-S-3-FD-1': ('FD', (1464.9, 619.7, 1471.8, 625.4), 'by eye on 7x grid crop (OCR also read FD at 1464.0, 618.3)')}
BARE = {}
for i, v in LOC.items():
    if v['hits']:
        h = v['hits'][0]; BARE[i] = (v['family'], (h['x0'], h['y0'], h['x1'], h['y1']), 'rapidocr locator on 6x crop, confirmed by eye')
for i, v in EYE.items(): BARE[i] = v
assert len(BARE) == 9, BARE.keys()
UNMAPPED_BARE_BT = [dict(sheet='P-201.00', level='FLOOR_1', token='BT', x0_P_pt=1073.3, y0_P_pt=743.9, how='rapidocr locator; a bath-tub drain symbol beside it; not one of the 52 mapped leaves (no run mapped to it)'),
                    dict(sheet='P-201.00', level='FLOOR_1', token='BT', x0_P_pt=1628.1, y0_P_pt=694.5, how='rapidocr locator; not one of the 52 mapped leaves (no run mapped to it)')]
R = list(csv.DictReader(open('../pitch_v3/pitch_runs_v3.csv', encoding='utf8'))); CEN = {c['id']: c for c in json.load(open('../pitch_v3/leaf_tag_census.json'))}
V3L = {l['level']: l for l in csv.DictReader(open('../pitch_v3/pitch_lowest_v3.csv', encoding='utf8'))}
FLOOR = ['FLOOR_1', 'FLOOR_2', 'FLOOR_3', 'FLOOR_4', 'MEZZANINE']
census = []; out = []
for r in R:
    fam = r['fixture'].split('-')[0]; types = [t for t, n in FAMILY.get(fam, [])]
    bare = BARE.get(r['id']); num = CEN[r['id']]['numbered_token_nearest']
    if bare:
        assert bare[0] == fam, r['id']
        if len(types) == 1:
            res = 'BOUND_by_family: the key notes list exactly one %s type (%s, key note %d)' % (fam, types[0], FAMILY[fam][0][1]); st = 'tag_printed_without_number_only_%s_type_in_key_notes' % fam
        elif not types:
            res = 'REFUSED: no %s type is listed in any key note; the family rule cannot bind it' % fam; st = 'bare_%s_not_bound_family_not_in_key_notes' % fam
        else:
            res = 'REFUSED: key notes list %d %s types (%s); rule needs exactly one' % (len(types), fam, ', '.join(types)); st = 'bare_%s_not_bound_family_ambiguous' % fam
    else:
        res = 'n/a (numbered tag printed)'; st = 'tag_printed_numbered'
    px, py = CEN[r['id']]['leaf_P_pt']
    census.append(dict(id=r['id'], level=r['level'], sheet=r['sheet'], stack=r['stack'], family=fam, leaf_P_pt='%.1f,%.1f' % (px, py), leaf_A_pt='%.2f,%.2f' % (px + OFFS[0], py + OFFS[1]),
                       tag_form='BARE (no number)' if bare else 'numbered tag printed (read by eye on the crop)', bare_tag_text=fam if bare else '',
                       bare_bbox_P_displayed_pt=','.join('%.1f' % v for v in bare[1]) if bare else '', bare_bbox_A_frame_pt=','.join('%.1f' % (bare[1][k] + OFFS[k % 2]) for k in range(4)) if bare else '', bare_locate_method=bare[2] if bare else '',
                       numbered_tag_also_in_crop=(('%s at P pt %.1f,%.1f, %s pt from the leaf' % tuple(num)) if num else ''), key_note_types_for_family=' | '.join('%s (note %d)' % tn for tn in FAMILY.get(fam, [])) or 'none (family not in any key note)', bind_result=res))
    o = dict(r); o['tag_status_v4'] = st; o['bare_tag'] = 'yes' if bare else 'no'; o['bind_result_v4'] = res
    if bare and len(types) == 1: o['bound_type_v4'] = types[0] + ' (key note %d)' % FAMILY[fam][0][1]
    elif bare: o['bound_type_v4'] = 'NOT BOUND by the family rule; drop size kept at the P-301 riser-diagram BT-1 2in label, as in v10c'
    else: o['bound_type_v4'] = r['fixture'] + ' (numbered tag printed)'
    out.append(o)
print('bare among 52:', len(BARE), dict(C.Counter(CEN[i]['type'] for i in BARE)))
MINV = {'FLOOR_1': 42.1515, 'FLOOR_2': 52.1612, 'FLOOR_3': 61.9758, 'FLOOR_4': 72.1568, 'MEZZANINE': 81.9441}; ALT = {'MEZZANINE': 82.0425}
lowrows = []
for lv in FLOOR:
    rs = [o for o in out if o['level'] == lv]
    hb = min(rs, key=lambda o: float(o['lowest_pt_navd_ft'])); br = min(rs, key=lambda o: float(o['lowest_pt_navd_ft_trunk_bracket']))
    ctl = br
    if lv == 'MEZZANINE':
        sset = 'provisional'; why = 'K3: all drops at 1/4 in/ft (the FD-1 3in branch taken at 1/4 instead of the printed tier 1/8) is an assumption bound; the printed-tier figure 82.0425 is recorded beside it'
    else:
        sset = 'settled_after_K4'; why = 'K4 complete (all 52 leaves checked); the controlling tag is %s' % ('numbered' if ctl['bare_tag'] == 'no' else 'bare, bound by family from the key notes')
        if hb['bare_tag'] == 'yes' and hb['id'] != ctl['id']:
            why += '; the headline-scenario controller %s has a BARE tag the family rule cannot bind (%s); its own minimum %s is above the level minimum, so the level value does not depend on it' % (hb['id'], hb['bind_result_v4'], hb['lowest_pt_navd_ft_trunk_bracket'])
    lowrows.append(dict(level=lv, lowest_point_navd_ft=MINV[lv], printed_tier_alt_navd_ft=ALT.get(lv, ''), range_min=V3L[lv]['range_min'], range_max=V3L[lv]['range_max'], status='derived_from_printed', set_status=sset, set_status_reason=why,
                        controlling_run_for_minimum=ctl['id'], controlling_tag_bare=ctl['bare_tag'], controlling_tag_status=ctl['tag_status_v4'],
                        controlling_run_headline_scenario=hb['id'], headline_controlling_tag_bare=hb['bare_tag'], headline_controlling_tag_status=hb['tag_status_v4'],
                        bare_tags_on_level=';'.join(i for i in BARE if i in {o['id'] for o in rs}) or 'none', ruling_source='roy_pm'))
for fn, rows in (('leaf_tag_census_v4.csv', census), ('pitch_runs_v4.csv', out), ('pitch_lowest_v4.csv', lowrows)):
    with open(fn, 'w', newline='', encoding='utf8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
with open('key_note_families_v4.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.writer(f); w.writerow(['key_note', 'text', 'types_listed', 'sheets'])
    for n, (t, ty) in KEY_NOTES.items(): w.writerow([n, t, ' '.join(ty), 'P-200..P-205 (rendered; P-201..P-205 md5-identical)'])
json.dump(dict(unmapped_bare_BT=UNMAPPED_BARE_BT), open('unmapped_bare_tags.json', 'w'), indent=1)
for l in lowrows: print(l['level'], l['lowest_point_navd_ft'], 'ctl', l['controlling_run_for_minimum'], 'bare' if l['controlling_tag_bare'] == 'yes' else 'numbered', '| headline ctl', l['controlling_run_headline_scenario'], l['headline_controlling_tag_bare'], '|', l['set_status'])
# ------------------------------------------------------------------ run paths (leaf -> stack) from the pitchmap stroke graph; same FIX mapping as pitchmap/build.py
UW = {'FLOOR_1': 42.6408, 'FLOOR_2': 52.6408, 'FLOOR_3': 62.6408, 'FLOOR_4': 72.6408, 'MEZZANINE': 82.4742}
LVL = {'P-201.00': 'FLOOR_1', 'P-202.00': 'FLOOR_2', 'P-203.00': 'FLOOR_3', 'P-204.00': 'FLOOR_4', 'P-205.00': 'MEZZANINE'}
L4 = ['BT-1', 'LAV-1', 'WC-1', 'KS-1']; FIX = {('P-201.00', 'S-1'): L4, ('P-201.00', 'S-4'): ['BT-1', 'WC-1', 'KS-1']}
for s in ('S-1', 'S-2', 'S-3', 'S-4'):
    FIX[('P-202.00', s)] = L4; FIX[('P-204.00', s)] = ['BT-1', 'LAV-1', 'WC-1']
for s in ('S-1', 'S-2'): FIX[('P-203.00', s)] = ['KS-1', 'FD-1', 'BT-1', 'LAV-1', 'WC-1']
for s in ('S-3', 'S-4'): FIX[('P-203.00', s)] = ['BT-1', 'LAV-1', 'WC-1', None]
FIX[('P-205.00', 'S-3')] = ['FD-1']
def preds(rec, start):
    adj = C.defaultdict(list)
    for e in rec['edges']:
        adj[e['na']].append((e['nb'], e['L'])); adj[e['nb']].append((e['na'], e['L']))
    best = None
    for e in rec['edges']:
        d, c, t = RU.dist_pt_seg(start, e['a'], e['b'])
        if best is None or d < best[0]: best = (d, e, t, c)
    d, e, t, c = best; dist = {}; pr = {}; h = [(t * e['L'], e['na'], -1), ((1 - t) * e['L'], e['nb'], -1)]
    while h:
        dd, u, p = heapq.heappop(h)
        if u in dist and dist[u] <= dd: continue
        dist[u] = dd; pr[u] = None if p == -1 else p
        for v, w in adj[u]:
            if v not in dist or dist[v] > dd + w: heapq.heappush(h, (dd + w, v, u))
    return dist, pr, adj, c
byid = {o['id']: o for o in out}; PATHS = {}; ratios = []
for sheet, level in LVL.items():
    for r in RU.run_sheet(sheet, ['sanitary']):
        if not r['leaves']: continue
        fx = FIX.get((sheet, r['stack']))
        if fx is None or len(fx) != len(r['leaves']): continue
        dist, pr, adj, c = preds(r, r['stack_xy'])
        for i, (n, L, pt) in enumerate(r['leaves']):
            f = fx[i]
            if f is None: continue
            rid = '%s-%s-%s' % (level.replace('FLOOR_', 'F').replace('MEZZANINE', 'MZ'), r['stack'], f); o = byid[rid]
            assert abs(float(o['length_ft']) - round(L, 2)) < 0.011 and abs(float(o['leaf_x_ft']) - round(pt[0], 2)) < 0.011, (rid, o['length_ft'], L)
            chain = []; cur = n
            while cur is not None:
                chain.append(tuple(r['nodes'][cur])); cur = pr.get(cur)
            poly = chain + [tuple(c), tuple(r['stack_xy'])]
            pl = sum(math.hypot(poly[k + 1][0] - poly[k][0], poly[k + 1][1] - poly[k][1]) for k in range(len(poly) - 1)); ratios.append((rid, round(pl, 3), round(L, 3)))
            PATHS[rid] = dict(level=level, sheet=sheet, stack=r['stack'], polyline_xy_ft=[[round(x, 4), round(y, 4)] for x, y in poly], polyline_len_ft=round(pl, 4), stroke_len_ft=float(o['length_ft']),
                              branch_len_ft=float(o['branch_len_ft']), trunk_len_ft=float(o['trunk_len_ft']), drop_size_in=int(o['drop_size_in']), fixture=o['fixture'])
assert len(PATHS) == 52, len(PATHS)
json.dump(PATHS, open('pitch_run_paths_v4.json', 'w'))
dev = max(abs(a - b) / b for _, a, b in ratios)
print('52 run paths; max |polyline len - stroke len| / stroke len = %.3f' % dev, [x for x in ratios if abs(x[1] - x[2]) / x[2] > 0.1][:6])
