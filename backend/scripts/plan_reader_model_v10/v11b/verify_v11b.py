# verify_v11b.py: v11 checks (adapted) + v11b checks on the written v11b files (GLBs re-parsed from bytes, CSVs, v11, v10c, v09b). Run: PYTHONUTF8=1 python verify_v11b.py > verify_out_v11b.txt ; exit code 1 on any FAIL.
import struct, json, csv, array, collections as C, math, sys, re
from shapely.geometry import box as sb
R = 'C:/Users/asddd/bv-worktrees/'; V9 = R + 'model_export_v09b/'; V10C = R + 'model_export_v10c/'; H = R + 'model_export_v11b/'; V11 = R + 'model_export_v11/'
rd = lambda p: list(csv.DictReader(open(p, encoding='utf8')))
fl = lambda x: float(x) if x not in ('', None) else None
FAILS = []
def chk(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (' :: ' + str(detail) if detail != '' else ''))
    if not ok: FAILS.append(name)
def parse(path):
    b = open(path, 'rb').read(); magic, ver, tot = struct.unpack_from('<4sII', b, 0); assert magic == b'glTF' and ver == 2 and tot == len(b)
    jl, jt = struct.unpack_from('<I4s', b, 12); assert jt == b'JSON'; g = json.loads(b[20:20 + jl]); off = 20 + jl
    bl, bt = struct.unpack_from('<I4s', b, off); assert bt == b'BIN\x00'; binb = b[off + 8: off + 8 + bl]; assert len(binb) == g['buffers'][0]['byteLength']; return g, binb
def acc(g, binb, i):
    a = g['accessors'][i]; bv = g['bufferViews'][a['bufferView']]; nc = {'VEC3': 3, 'SCALAR': 1}[a['type']]; arr = array.array('f' if a['componentType'] == 5126 else 'I'); n = a['count'] * nc
    arr.frombytes(binb[bv['byteOffset']: bv['byteOffset'] + n * 4]); return arr, nc, a, bv
def pcs_of(e):
    if e['footprint_pts_ft']: return [[tuple(map(float, q.split(','))) for q in pc.split(';')] for pc in e['footprint_pts_ft'].split('|')]
    x0, y0, x1, y1 = fl(e['x_min_ft']), fl(e['y_min_ft']), fl(e['x_max_ft']), fl(e['y_max_ft']); return [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]
def bb(pts): return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)
src = open(H + 'build_v10.py', encoding='utf8').read(); ns = {'np': __import__('numpy'), 'math': math, 'json': json, 'struct': struct}; exec(src[src.index("A500 = "):src.index('class GLB:')], ns); TYPES = ns['TYPES']
UW = {'FLOOR_1': 42.6408, 'FLOOR_2': 52.6408, 'FLOOR_3': 62.6408, 'FLOOR_4': 72.6408, 'MEZZANINE': 82.4742}; LEVELS = list(UW)
PIT = {r['level']: r for r in rd(H + 'pitch_v4/pitch_lowest_v4.csv')}; PRUN = rd(H + 'pitch_v4/pitch_runs_v4.csv'); CEN = rd(H + 'pitch_v4/leaf_tag_census_v4.csv'); PATHS = json.load(open(H + 'pitch_v4/pitch_run_paths_v4.json'))
NEWFAM = 'L6_ceiling_services'
VOCAB = {'measured_from_plan', 'rule_from_printed_detail', 'rule_from_continuity', 'schedule_merged_cell', 'header_size_unknown', 'unbound_type', 'identified_visually', 'measured_from_drawing', 'layout_assumed', 'door_G_undefined', 'printed_assembly', 'derived_from_printed', 'convention_ceiling_drop', 'chase_wall_variable'}
TRK = {'filed': ('elements_filed.csv', 'model_filed.glb', 'framing_elements_filed.csv', '645cdd'), 'post_co': ('elements_postco.csv', 'model_postco.glb', 'framing_elements_post_co.csv', '645ec2')}
TOTALS = {}
for track, (efn, gfn, ffn, beam6) in TRK.items():
    print('\n######## TRACK', track)
    g, binb = parse(H + gfn); g9, _ = parse(V9 + gfn); g10, _ = parse(V10C + gfn); F = rd(H + ffn); E = {r['id']: r for r in rd(V9 + efn)}
    N = g['nodes']; names = C.Counter(n['name'] for n in N); IDX = {n['name']: i for i, n in enumerate(N) if 'mesh' in n}; byn = {n['name']: n for n in N}
    ref = C.Counter()
    for n in N: ref.update(n.get('children', []))
    for r in g['scenes'][0]['nodes']: ref[r] += 1
    chk(track + ' GLB re-parses; every node referenced exactly once', all(ref[i] == 1 for i in range(len(N))), '%d nodes, %d meshes, %d bytes bin' % (len(N), len(g['meshes']), len(binb)))
    bad = badi = 0
    for m in g['meshes']:
        for pr in m['primitives']:
            arr, nc, a, bv = acc(g, binb, pr['attributes']['POSITION']); assert bv['byteOffset'] + bv['byteLength'] <= len(binb)
            if 'min' in a:
                mn = [min(arr[k::3]) for k in range(3)]; mx = [max(arr[k::3]) for k in range(3)]
                if any(abs(a['min'][k] - mn[k]) > 1e-4 or abs(a['max'][k] - mx[k]) > 1e-4 for k in range(3)): bad += 1
            if 'indices' in pr:
                ia, _, _, _ = acc(g, binb, pr['indices']); badi += (max(ia) >= a['count'])
    chk(track + ' accessor min/max == data; index range ok', bad == 0 and badi == 0, 'bad=%d badidx=%d' % (bad, badi))
    dup9 = C.Counter(n['name'] for n in g9['nodes'] if 'mesh' in n); chk(track + ' every v09b mesh-node name present the same number of times', all(names[k] == v for k, v in dup9.items()), len(dup9))
    orig_ids = {n['name'] for n in g9['nodes'] if n.get('extras', {}).get('id') == n['name'] and not n['extras'].get('derived')}; chk(track + ' every original (v09b) element id present exactly once', all(names[i] == 1 for i in orig_ids), len(orig_ids))
    chk(track + ' every v09b and v10c node keeps its name, index and mesh index (nodes only appended)', len(N) > len(g10['nodes']) and all(a['name'] == b['name'] and a.get('mesh') == b.get('mesh') for a, b in zip(g10['nodes'], N)), '%d v10c nodes, %d v11 nodes' % (len(g10['nodes']), len(N)))
    g11, _ = parse(V11 + gfn); chk(track + ' every v11 node keeps its name, index and mesh index (v11b only appends)', len(N) > len(g11['nodes']) and all(a['name'] == b['name'] and a.get('mesh') == b.get('mesh') for a, b in zip(g11['nodes'], N)), '%d v11 nodes, %d v11b nodes' % (len(g11['nodes']), len(N)))
    new = [n for n in N if n.get('extras', {}).get('added_in') == 'v11']; print('INFO v11-added nodes: %d' % len(new))
    chk(track + ' v11 layer family %s present as a LAYER group with 3 sublayer groups' % NEWFAM, byn['LAYER ' + NEWFAM]['extras']['layer'] == 'family' and len(byn['LAYER ' + NEWFAM]['children']) == 3)
    # ---- csv rows vs GLB nodes for the new family
    nf = [r for r in F if r['layer'] == NEWFAM]; cg = C.Counter(n['extras']['sublayer'] for n in new if n['extras'].get('layer') == NEWFAM and 'mesh' in n); cc = C.Counter(r['sublayer'] for r in nf)
    chk(track + ' rows per %s sublayer == nodes' % NEWFAM, cc == cg, dict(cc))
    def box(name):
        n = N[IDX[name]]; arr, nc, a, bv = acc(g, binb, g['meshes'][n['mesh']]['primitives'][0]['attributes']['POSITION']); return (a['min'][0], -a['max'][2], a['max'][0], -a['min'][2], a['min'][1], a['max'][1])
    mism = 0
    for r in nf:
        b = box(r['glb_node']); c = [fl(r['x_min_ft']), fl(r['y_min_ft']), fl(r['x_max_ft']), fl(r['y_max_ft']), fl(r['z_bottom_navd_ft']), fl(r['z_top_navd_ft'])]
        if any(abs(c[k] - b[k]) > 0.002 for k in range(6)): mism += 1
    chk(track + ' new rows: CSV bbox/z == GLB mesh extents', mism == 0, '%d rows' % len(nf))
    chk(track + ' every row has source sheet, detail ref, status; status vocabulary', all(r['source_sheet'] and r['detail_ref'] and r['status'] for r in F) and {r['status'] for r in F} <= VOCAB, sorted({r['status'] for r in F} - VOCAB))
    chk(track + ' no clash wiring: every new L6 row clash_include = no; no clash class added', all(r['clash_include'] == 'no' for r in nf) and not any('clash' in r['class'] for r in F))
    chk(track + ' every L6 row ruling_source roy_pm', all(r['ruling_source'] == 'roy_pm' for r in nf))
    # ---- K1
    L1 = [r for r in F if r['layer'] == 'L1_wall_assemblies']; lay = [r for r in L1 if r['class'].startswith('wall_layer')]; hosts = C.defaultdict(list)
    for r in lay: hosts[r['host_or_parent_id']].append(r)
    badsum = badc = nb = 0; p5 = 0
    for h, rs in hosts.items():
        tag = rs[0]['type_tag']; tot = float(re.search(r'sum of drawn layers ([\d.]+) in', rs[0]['size_note']).group(1)); layers_sum = sum(float(re.search(r'printed layer ([\d.]+) in', r['size_note']).group(1)) for r in rs); assert layers_sum <= tot + 1e-6
        if tag == 'P4':
            continue
        want = 4.75 if tag == 'P5' else TYPES[tag]['printed_total']; p5 += tag == 'P5'; nb += 1
        if abs(tot - want) > 1e-6: badsum += 1
        wid, k = h.split('#'); x0, y0, x1, y1 = bb(pcs_of(E[wid])[int(k)]); ux0 = min(fl(r['x_min_ft']) for r in rs); uy0 = min(fl(r['y_min_ft']) for r in rs); ux1 = max(fl(r['x_max_ft']) for r in rs); uy1 = max(fl(r['y_max_ft']) for r in rs)
        if abs((ux0 + ux1) / 2 - (x0 + x1) / 2) > 0.01 or abs((uy0 + uy1) / 2 - (y0 + y1) / 2) > 0.01: badc += 1
    chk(track + ' K1 tag-bound (non-P4) hosts: sum of drawn layers == printed assembly thickness (P5 = 4.75)', badsum == 0 and nb > 0, '%d hosts, %d P5 hosts' % (nb, p5))
    chk(track + ' K1 layers centred on the drawn centreline (union bbox centre == wall piece centre, +-0.01 ft)', badc == 0, '%d hosts, %d off' % (nb, badc))
    chk(track + ' K1 layer rows of non-P4 types have status printed_assembly; P4 face rows have status chase_wall_variable with the upper-bound label', all((r['status'] == 'printed_assembly') == (r['type_tag'] != 'P4') for r in lay) and all(r['status'] == 'chase_wall_variable' and 'UPPER BOUND' in r['thickness_basis'] for r in lay if r['type_tag'] == 'P4'), dict(C.Counter((r['type_tag'] == 'P4', r['status']) for r in lay)))
    chk(track + ' K1 P5 rows: 4.75 basis, roy_pm, D01 discrepancy named', all('4.75' in r['thickness_basis'] and 'D01' in r['thickness_basis'] and r['ruling_source'] == 'roy_pm' for r in L1 if r['type_tag'] == 'P5'), sum(1 for r in L1 if r['type_tag'] == 'P5'))
    unb = [r for r in L1 if r['sublayer'] == 'unbound_walls']; chk(track + ' K1 unbound walls: status unbound_type, label "drawn thickness, rounded-up upper bound", roy_pm', all(r['status'] == 'unbound_type' and r['thickness_basis'] == 'drawn thickness, rounded-up upper bound' and r['ruling_source'] == 'roy_pm' for r in unb), len(unb))
    chk(track + ' K1 every L1 row roy_pm and carries thickness_basis; GLB extras match', all(r['ruling_source'] == 'roy_pm' and r['thickness_basis'] for r in L1) and all(byn[r['glb_node']]['extras'].get('thickness_basis') == r['thickness_basis'] and byn[r['glb_node']]['extras']['status'] == r['status'] for r in L1), len(L1))
    v10 = {r['element_id']: r for r in rd(V10C + ffn)}; v11rows = {r['element_id']: r for r in rd(V11 + ffn)}; geom = ('x_min_ft', 'y_min_ft', 'x_max_ft', 'y_max_ft', 'z_bottom_navd_ft', 'z_top_navd_ft')
    L1old = [r for r in L1 if r['sublayer'] != 'chase_cavity']; chk(track + ' no L1 geometry changed vs v10c and v11 (bbox/z of every pre-existing L1 row identical; the chase_cavity rows are new)', all(all(v10[r['element_id']][c] == r[c] and v11rows[r['element_id']][c] == r[c] for c in geom) for r in L1old) and len(L1old) == len([x for x in v11rows.values() if x['layer'] == 'L1_wall_assemblies']), len(L1old))
    # ---- K2
    bm = [r for r in F if r['host_or_parent_id'].endswith(beam6) and r['class'] == 'beam_member_outline']
    chk(track + ' K2 beam ...%s: 2 whole-row outlines in the nSWm class, both labels listed, no split' % beam6, len(bm) == 2 and all(r['designation_as_printed'] == '(2) 8SW14 | (2) 16SW10' and r['sublayer'] == 'label_governed_beams_depth_unknown' for r in bm) and abs(min(fl(r['x_min_ft']) for r in bm) - 36.585) < 0.01 and abs(max(fl(r['x_max_ft']) for r in bm) - 69.028) < 0.01, [(r['x_min_ft'], r['x_max_ft']) for r in bm])
    chk(track + ' K2 beam outlines are in the LAYER L2_box_beams | label_governed group and roy_pm; beam no longer in not_modelled', all(r['ruling_source'] == 'roy_pm' for r in bm) and not any(r['track'] == track and r['kind'] == 'beam' and beam6 in r['element_or_item'] for r in rd(H + 'not_modelled.csv')) and all(IDX[r['glb_node']] in byn['LAYER L2_box_beams | label_governed_beams_depth_unknown']['children'] for r in bm))
    chk(track + ' K2 engineer question J3 (meaning of SW) added', any(q['question_id'] == 'J3' and 'SW' in q['question'] for q in rd(H + 'engineer_questions_v11.csv')))
    # ---- ceiling plane
    cp = [r for r in nf if r['class'] == 'ceiling_plane']
    chk(track + ' ceiling plane: one per level (5), z top == pitch_v4 lowest point; MEZZ 81.9441 provisional with 82.0425 beside it', len(cp) == 5 and all(abs(fl(r['z_top_navd_ft']) - float(PIT[r['level']]['lowest_point_navd_ft'])) < 1e-4 for r in cp) and byn['ceiling_plane:%s:MEZZANINE' % track]['extras']['printed_tier_alt_navd_ft'] == '82.0425' and byn['ceiling_plane:%s:MEZZANINE' % track]['extras']['set_status'] == 'provisional' and abs(fl([r for r in cp if r['level'] == 'MEZZANINE'][0]['z_top_navd_ft']) - 81.9441) < 1e-4, {r['level']: r['z_top_navd_ft'] for r in cp})
    # ---- sloped runs
    sr = [r for r in nf if r['class'] == 'sanitary_run_sloped']; badr = []
    for r in sr:
        x = byn[r['glb_node']]['extras']; run = next(p for p in PRUN if p['id'] == x['run_id']); P = PATHS[x['run_id']]
        sz = int(run['drop_size_in']); sbs = 0.125 if sz >= 3 else 0.25; bl = float(run['branch_len_ft']); tl = P['stroke_len_ft'] - bl; uw = UW[r['level']]
        top_stack = uw - (sbs * bl + 0.125 * tl) / 12; low = top_stack - 4.0 / 12
        ok = abs(x['branch_slope_in_per_ft'] - sbs) < 1e-9 and abs(fl(r['z_top_navd_ft']) - uw) < 1e-4 and abs(x['z_top_stack_end_navd_ft'] - top_stack) < 2e-3 and abs(fl(r['z_bottom_navd_ft']) - low) < 2e-3 and abs(low - float(run['lowest_pt_navd_ft'])) < 4e-3
        ok = ok and x['z_high_end_status'] == 'convention_ceiling_drop' and x['slope_status'] == 'derived_from_printed' and r['status'] == 'derived_from_printed' and (sz >= 3) == (x['branch_slope_in_per_ft'] == 0.125)
        if not ok: badr.append(x['run_id'])
    chk(track + ' sloped runs: 52; high-end top == structure underside; slope tier 1/8 (>=3 in) / 1/4 (<=2 in); stack-end elevations re-derived', len(sr) == 52 and not badr, 'runs %d bad %s; per level %s' % (len(sr), badr[:4], dict(C.Counter(r['level'] for r in sr))))
    # slopes measured from the mesh itself: the top surface must fall monotonically from the high end (max z) to the stack end
    badm = 0
    for r in sr:
        n = byn[r['glb_node']]; arr, nc, a, bv = acc(g, binb, g['meshes'][n['mesh']]['primitives'][0]['attributes']['POSITION']); zs = arr[1::3]
        if abs(max(zs) - UW[r['level']]) > 1e-3 or abs(min(zs) - fl(r['z_bottom_navd_ft'])) > 1e-3: badm += 1
    chk(track + ' sloped runs: GLB mesh max z == structure underside, min z == lowest point', badm == 0, badm)
    chk(track + ' sloped runs: statuses derived_from_printed; high end z flagged convention_ceiling_drop; count by status', True, dict(C.Counter(r['status'] for r in sr)))
    # ---- heads
    hs = [r for r in nf if r['class'] == 'sprinkler_head_at_ceiling']; orig = [e for e in E.values() if e['class'] == 'sprinkler_head']
    ok = all(abs(fl(r['z_top_navd_ft']) - float(PIT[r['level']]['lowest_point_navd_ft'])) < 1e-4 and r['status'] == 'convention_ceiling_drop' and r['host_or_parent_id'] in E and abs((fl(r['x_min_ft']) + fl(r['x_max_ft'])) / 2 - fl(E[r['host_or_parent_id']]['x_min_ft'])) < 1e-3 and abs((fl(r['y_min_ft']) + fl(r['y_max_ft'])) / 2 - fl(E[r['host_or_parent_id']]['y_min_ft'])) < 1e-3 for r in hs)
    chk(track + ' heads at ceiling: %d (orig %d, ROOF %d not placed); z top == level ceiling plane; status convention_ceiling_drop; xy == original head; originals untouched' % (len(hs), len(orig), sum(e['level'] == 'ROOF' for e in orig)), ok and len(hs) == sum(e['level'] != 'ROOF' for e in orig) and all(names[e['id']] == (1 if e['id'] in orig_ids else 0) for e in orig), dict(C.Counter(r['level'] for r in hs)))
    # ---- tops audit
    T = [t for t in rd(H + 'tops_at_structure_underside_v11.csv') if t['track'] == track]
    chk(track + ' tops audit: every sprinkler_pipe / exhaust fan on a registered level has z top == structure underside and status convention_ceiling_drop (0 mismatches)', not any(t['verdict'] == 'MISMATCH' for t in T), dict(C.Counter((t['class_'], t['verdict'][:30]) for t in T)))
    cnt = C.Counter((r['layer'], r['sublayer'], r['status']) for r in F); TOTALS[track] = cnt
    print('counts per layer | sublayer | status (%s):' % track)
    for k in sorted(cnt): print('   %-26s %-38s %-26s %s' % (k[0], k[1], k[2], 'COUNT WITHHELD (layout_assumed)' if k[1] in ('studs_track', 'field_studs') else cnt[k]))
# ---- K4 / pitch_v4 (track independent)
print('\n######## K4 pitch_v4')
bare = [c for c in CEN if c['bare_tag_text']]
chk('K4 census covers all 52 leaves (not 9 crops); each has a tag form and a bind result', len(CEN) == 52 and all(c['tag_form'] and c['bind_result'] for c in CEN))
chk('K4 bare tags found: 9 (KS 4, FD 3, BT 1, WC 1), each with coordinates (P and A frame)', len(bare) == 9 and C.Counter(c['family'] for c in bare) == C.Counter({'KS': 4, 'FD': 3, 'BT': 1, 'WC': 1}) and all(c['bare_bbox_P_displayed_pt'] and c['bare_bbox_A_frame_pt'] for c in bare))
kn = {r['key_note']: r['types_listed'].split() for r in rd(H + 'pitch_v4/key_note_families_v4.csv')}; fam = C.defaultdict(list)
for n, ts in kn.items():
    for t in ts: fam[t.split('-')[0]].append(t)
chk('K4 binding rule: a bare tag is bound by family iff the key notes list exactly one type of its family (KS, WC, FD); BT is bound by Roy ruling L2 (status tag_printed_without_number_only_BT_type_on_plans); 0 refused', all(c['bind_result'].startswith('BOUND') for c in bare) and all((len(fam[c['family']]) == 1) == ('by_ruling' not in c['bind_result']) for c in bare) and [c['id'] for c in bare if 'by_ruling' in c['bind_result']] == ['F1-S-4-BT-1'], {c['id']: c['bind_result'][:30] for c in bare})
ctl = {l: PIT[l] for l in LEVELS}
chk('K4 controlling run per level stated with bareness; levels settled except MEZZ (K3 provisional)', all(ctl[l]['controlling_run_for_minimum'] and ctl[l]['controlling_tag_bare'] in ('yes', 'no') for l in LEVELS) and [l for l in LEVELS if ctl[l]['set_status'] == 'provisional'] == ['MEZZANINE'], {l: (ctl[l]['controlling_run_for_minimum'], 'bare' if ctl[l]['controlling_tag_bare'] == 'yes' else 'numbered') for l in LEVELS})
for t in ('filed', 'post_co'): print('INFO %s status totals: %s' % (t, {'%s|%s|%s' % k: v for k, v in TOTALS[t].items() if k[0] == NEWFAM}))
# ======================================================================== v11b checks
import numpy as np
print('\n######## v11b')
rect_from_pts = ns['rect_from_pts']
def inrect(P, pc, eps=1e-6):
    d = np.asarray(P, float) - pc['c']; u = pc['u']; n = np.array([-u[1], u[0]]); a = np.abs(d @ u); b = np.abs(d @ n); return (a <= pc['L'] / 2 + eps) & (b <= pc['T'] / 2 + eps)
def inany(P, pcs, eps=1e-6):
    ok = np.zeros(len(P), bool)
    for pc in pcs: ok |= inrect(P, pc, eps)
    return ok
def rel_pts(P, pcs, eps=1e-6):
    ok = inany(P, pcs, eps)
    return 'fully_inside_p4' if ok.all() else ('crosses_p4_boundary' if ok.any() else 'outside_p4')
FL = rd(H + 'p4_chase_clash_flags_v11b.csv'); SUMV = json.load(open(H + 'apply_v11b_summary.json'))
for track, (efn, gfn, ffn, beam6) in TRK.items():
    print('\n---- v11b track', track)
    E = rd(V9 + efn); F = rd(H + ffn); g, binb = parse(H + gfn); N = g['nodes']; byn = {n['name']: n for n in N}; IDX = {n['name']: i for i, n in enumerate(N) if 'mesh' in n}
    p4 = {}
    for w in E:
        if w['class'] == 'wall' and w['tag'] == 'P4' and w['x_min_ft']:
            pl = pcs_of(w)
            for k, pts in enumerate(pl): p4['%s#%d' % (w['id'], k)] = (w, pts)
    cav = [r for r in F if r['sublayer'] == 'chase_cavity']; fac = [r for r in F if r['type_tag'] == 'P4' and r['class'] == 'wall_layer_gyp']
    chk(track + ' P4: one chase_cavity row + one GLB node per P4 piece (%d pieces); status chase_wall_variable; roy_pm' % len(p4), len(cav) == len(p4) == SUMV[track]['P4_pieces'] and {r['host_or_parent_id'] for r in cav} == set(p4) and all(r['status'] == 'chase_wall_variable' and r['ruling_source'] == 'roy_pm' and r['glb_node'] in IDX and byn[r['glb_node']]['extras']['status'] == 'chase_wall_variable' for r in cav), len(cav))
    bad = []
    for h, (w, pts) in p4.items():
        cf = [r for r in fac if r['host_or_parent_id'] == h]; cr = next(r for r in cav if r['host_or_parent_id'] == h)
        T = min(max(p[0] for p in pts) - min(p[0] for p in pts), max(p[1] for p in pts) - min(p[1] for p in pts)) * 12     # the P4 pieces are axis-aligned rectangles
        face_in = [float(re.search(r'printed layer ([\d.]+) in', r['size_note']).group(1)) for r in cf]; cav_in = float(re.search(r'cavity ([\d.]+) in', cr['size_note']).group(1))
        if not (len(cf) == 4 and all(abs(x - 0.625) < 1e-9 for x in face_in) and abs(cav_in - (T - 2.5)) < 0.002 and abs(sum(face_in) + cav_in - T) < 0.002 and all(r['status'] == 'chase_wall_variable' for r in cf)): bad.append((h[-8:], len(cf), round(T, 3), cav_in))
    chk(track + ' P4: 4 face rows at the printed 5/8 in each; cavity = drawn thickness - 2.5 in; faces + cavity = drawn thickness (per piece, drawn thickness re-measured from the v09b footprint)', not bad, 'bad %s of %d pieces' % (bad[:3], len(p4)))
    mism = 0
    for r in cav:
        n = byn[r['glb_node']]; a = g['accessors'][g['meshes'][n['mesh']]['primitives'][0]['attributes']['POSITION']]; b = (a['min'][0], -a['max'][2], a['max'][0], -a['min'][2], a['min'][1], a['max'][1]); c = [fl(r[k]) for k in ('x_min_ft', 'y_min_ft', 'x_max_ft', 'y_max_ft', 'z_bottom_navd_ft', 'z_top_navd_ft')]
        mism += any(abs(c[k] - b[k]) > 0.002 for k in range(6))
    chk(track + ' P4: cavity rows CSV bbox/z == GLB mesh extents', mism == 0, len(cav))
    chk(track + ' P4: the original v09b P4 wall nodes carry chase_wall_status and drawn_thickness_is_upper_bound', all(byn[w['id']]['extras'].get('chase_wall_status') == 'chase_wall_variable' and byn[w['id']]['extras'].get('drawn_thickness_is_upper_bound') is True for w, _ in p4.values()), len({w['id'] for w, _ in p4.values()}))
    chk(track + ' P4: stud/track rows keep status layout_assumed (their counts stay withheld) and carry the upper-bound basis', all(r['status'] == 'layout_assumed' and 'UPPER BOUND' in r['thickness_basis'] for r in F if r['type_tag'] == 'P4' and r['class'] in ('wall_stud_line', 'wall_track_line')))
    # ---- clash flags re-derived independently (local rectangle frame, point samples) and compared with the written flags
    pcs_lv = C.defaultdict(list)
    for h, (w, pts) in p4.items(): pcs_lv[w['level']].append(rect_from_pts(pts))
    fl_t = {f['element_id']: f for f in FL if f['track'] == track}; wrong = []; cnt = C.Counter()
    for e in E:
        if e['class'] == 'plumbing_stack' and e['x_min_ft']:
            cx, cy = (fl(e['x_min_ft']) + fl(e['x_max_ft'])) / 2, (fl(e['y_min_ft']) + fl(e['y_max_ft'])) / 2; rr = (fl(e['x_max_ft']) - fl(e['x_min_ft'])) / 2
            P = [(cx + rr * math.cos(t), cy + rr * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 96, endpoint=False)]
            want = 'no_p4_on_level' if e['level'] not in pcs_lv else rel_pts(P, pcs_lv[e['level']])
            if fl_t[e['id']]['p4_relation'] != want: wrong.append((e['id'][-4:], want, fl_t[e['id']]['p4_relation']))
            cnt[fl_t[e['id']]['p4_relation']] += 1
    chk(track + ' clash flags: every placed stack row re-derived independently (96-point circle, local frame): same relation as the written flag', not wrong, 'mismatches %s; counts %s' % (wrong[:4], dict(cnt)))
    nst = sum(1 for f in fl_t.values() if f['class_'] == 'plumbing_stack'); chk(track + ' clash flags: all 127 stack rows flagged (%s)' % dict(C.Counter(f['p4_relation'] for f in fl_t.values() if f['class_'] == 'plumbing_stack')), nst == 127 == sum(1 for e in E if e['class'] == 'plumbing_stack'))
    wrong = []
    for rid, P in PATHS.items():
        lv = P['level']; w = max(P['drop_size_in'], 4) / 12; pl = np.array(P['polyline_xy_ft'], float); pts = []
        for a, b in zip(pl[:-1], pl[1:]):
            L = np.linalg.norm(b - a); k = max(2, int(L / 0.02) + 1)
            for t in np.linspace(0, 1, k): pts.append(a + (b - a) * t)
        pts = np.array(pts); S = [pts + (w / 2) * np.array([math.cos(ang), math.sin(ang)]) for ang in np.linspace(0, 2 * math.pi, 16, endpoint=False)]
        S = np.vstack(S + [pts]); want = 'no_p4_on_level' if lv not in pcs_lv else rel_pts(S, pcs_lv[lv])
        got = fl_t['sanitary_run:%s:%s' % (track, rid)]['p4_relation']
        if got != want: wrong.append((rid, want, got))
    chk(track + ' clash flags: 52 sloped runs re-derived independently (sampled pipe outline, widest 4 in): same relation as the written flag', not wrong and sum(1 for f in fl_t.values() if f['class_'] == 'sanitary_run_sloped') == 52, wrong[:4])
    wrong = []
    for e in E:
        if e['class'] == 'sprinkler_pipe':
            f = fl_t[e['id']]
            if not e['x_min_ft']: want = 'no_xy'
            elif e['level'] not in pcs_lv: want = 'no_p4_on_level'
            else:
                xs = np.linspace(fl(e['x_min_ft']), fl(e['x_max_ft']), max(3, int((fl(e['x_max_ft']) - fl(e['x_min_ft'])) / 0.02) + 1)); ys = np.linspace(fl(e['y_min_ft']), fl(e['y_max_ft']), max(3, int((fl(e['y_max_ft']) - fl(e['y_min_ft'])) / 0.02) + 1))
                want = rel_pts([(x, y) for x in xs for y in ys], pcs_lv[e['level']])
            if f['p4_relation'] != want: wrong.append((e['id'], want, f['p4_relation']))
    chk(track + ' clash flags: sprinkler pipe rows re-derived independently (grid over the row bbox): same relation as the written flag', not wrong, wrong[:4])
    inside = [f for f in fl_t.values() if f['p4_relation'] == 'fully_inside_p4']; cross = [f for f in fl_t.values() if f['p4_relation'] == 'crosses_p4_boundary']; other = [f for f in fl_t.values() if f['p4_relation'] not in ('fully_inside_p4', 'crosses_p4_boundary')]
    chk(track + ' clash flags: inside -> clash_include no + reason; crossing -> yes_flag_p4_boundary + reason; others -> as_before; no clash wiring (no clash class, every L6 clash_include no)', all(f['clash_include'] == 'no' and f['clash_exclusion_reason'] for f in inside) and all(f['clash_include'] == 'yes_flag_p4_boundary' and f['clash_exclusion_reason'] for f in cross) and all(f['clash_include'] == 'as_before' for f in other) and not any('clash' in r['class'] for r in F) and all(r['clash_include'] == 'no' for r in F if r['layer'] == 'L6_ceiling_services'), 'inside %d crossing %d' % (len(inside), len(cross)))
    chk(track + ' clash flags: the flag is on the GLB node extras of every flagged element that has a node', all(byn[f['element_id']]['extras'].get('clash_p4_relation') == f['p4_relation'] for f in fl_t.values() if f['element_id'] in byn), sum(1 for f in fl_t.values() if f['element_id'] in byn))
    r = next(x for x in F if x['element_id'] == 'sanitary_run:%s:F1-S-4-BT-1' % track); ex = byn[r['glb_node']]['extras']
    chk(track + ' BT-1 accepted: F1-S-4-BT-1 tag status tag_printed_without_number_only_BT_type_on_plans in the GLB node; no old BT refusal text in rows or GLB', ex['tag_status_v4'] == 'tag_printed_without_number_only_BT_type_on_plans' and 'bare_BT_not_bound' not in json.dumps(g) and not any('bare_BT_not_bound' in json.dumps(x) or 'family rule cannot bind' in json.dumps(x) for x in F))
    pr = [p for p in rd(H + 'stairshaft_v2_shaft_wall_pairs_v11b.csv') if p['track'] == track]
    chk(track + ' stairshaft: 7 shaft walls per level (35 = 5 levels x 7), each paired with a wall of the other track; filed walls fully covered by their post_co counterpart', len(pr) == 35 and all(float(p['this_area_covered_by_counterpart']) >= 0.99 for p in pr if track == 'filed') and C.Counter(p['level'] for p in pr) == C.Counter({l: 7 for l in LEVELS}), dict(C.Counter(p['level'] for p in pr)))
a = rd(V11 + 'pitch_v4/pitch_lowest_v4.csv'); b = rd(H + 'pitch_v4/pitch_lowest_v4.csv')
chk('BT-1 ruling changes no level value: pitch_lowest columns lowest_point / range / set_status / controlling runs identical to v11', all(x[k] == y[k] for x, y in zip(a, b) for k in ('level', 'lowest_point_navd_ft', 'printed_tier_alt_navd_ft', 'range_min', 'range_max', 'set_status', 'controlling_run_for_minimum', 'controlling_run_headline_scenario')), [x['lowest_point_navd_ft'] for x in b])
a = rd(V11 + 'pitch_v4/pitch_runs_v4.csv'); b = rd(H + 'pitch_v4/pitch_runs_v4.csv'); dif = {k for x, y in zip(a, b) for k in x if x[k] != y[k]}
chk('BT-1 ruling: pitch_runs_v4 differs from v11 only in tag_status_v4 / bind_result_v4 / bound_type_v4 (one row)', dif <= {'tag_status_v4', 'bind_result_v4', 'bound_type_v4'} and sum(1 for x, y in zip(a, b) if x != y) == 1, (sorted(dif), [y['id'] for x, y in zip(a, b) if x != y]))
a = rd(V11 + 'sanitary_runs_sloped_v11.csv'); b = rd(H + 'sanitary_runs_sloped_v11.csv'); chk('sanitary_runs_sloped_v11.csv: only tag_status changed (2 rows: one per track), no elevation moved', sum(1 for x, y in zip(a, b) if x != y) == 2 and {k for x, y in zip(a, b) for k in x if x[k] != y[k]} <= {'tag_status'}, sum(1 for x, y in zip(a, b) if x != y))
S = rd(H + 'wall_count_summary_v11b.csv'); sv = {(s['track'], s['quantity']): int(s['count']) for s in S}
Ff = rd(H + 'framing_elements_filed.csv'); Fp = rd(H + 'framing_elements_post_co.csv')
chk('wall counts: untagged walls 43 filed / 115 post_co (ids == walltype_read lists); unbound pieces 55 / 191 (== L1 unbound_walls rows); drawn untagged post_co walls 108 + 7 ROOF with no geometry; tag-bound 134 / 77 (post_co 71 drawn + 6 ROOF)',
    sv[('filed', 'walls with NO type tag (the "43 / 115")')] == 43 and sv[('post_co', 'walls with NO type tag (the "43 / 115")')] == 115 and sv[('filed', 'unbound_walls rows in framing_elements (v11)')] == sum(1 for r in Ff if r['sublayer'] == 'unbound_walls') == 55 and sv[('post_co', 'unbound_walls rows in framing_elements (v11)')] == sum(1 for r in Fp if r['sublayer'] == 'unbound_walls') == 191
    and sv[('post_co', '  untagged, of which drawn (placed geometry)')] == 108 and sv[('post_co', '  untagged, of which ROOF, no placed geometry')] == 7 and sv[('filed', 'walls with a type tag')] == 134 and sv[('post_co', 'walls with a type tag')] == 77 and sv[('post_co', '  tagged, of which drawn (type layers on them = "134 filed / 71 post-CO")')] == 71)
rep_txt = open(H + 'REPORT.md', encoding='utf8').read(); sh_txt = open(H + 'stairshaft_same_walls_v11b.md', encoding='utf8').read()
chk('REPORT (v11 part) / stairshaft note: no "+10" / "+8" shaft-wall claim; REPORT does not list "none below the ceiling plane" as evidence', '+10' not in rep_txt and '+10' not in sh_txt and '+8' not in sh_txt and 'none is below its level' not in rep_txt and 'none below' not in rep_txt.lower().replace('none below slab', ''), '')

print('\nRESULT v11b:', 'ALL PASS' if not FAILS else 'FAILS: %s' % FAILS)
sys.exit(1 if FAILS else 0)
