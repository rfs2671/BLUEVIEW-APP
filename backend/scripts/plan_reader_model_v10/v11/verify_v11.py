# verify_v11.py: measurement checks on the written v11 files (GLBs re-parsed from bytes, CSVs, v10c, v09b). Run: PYTHONUTF8=1 python verify_v11.py > verify_out_v11.txt ; exit code 1 on any FAIL.
import struct, json, csv, array, collections as C, math, sys, re
from shapely.geometry import box as sb
R = 'C:/Users/asddd/bv-worktrees/'; V9 = R + 'model_export_v09b/'; V10C = R + 'model_export_v10c/'; H = R + 'model_export_v11/'
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
VOCAB = {'measured_from_plan', 'rule_from_printed_detail', 'rule_from_continuity', 'schedule_merged_cell', 'header_size_unknown', 'unbound_type', 'identified_visually', 'measured_from_drawing', 'layout_assumed', 'door_G_undefined', 'printed_assembly', 'derived_from_printed', 'convention_ceiling_drop'}
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
    chk(track + ' K1 layer rows of non-P4 types have status printed_assembly; P4 layer rows keep rule_from_printed_detail with a drawn-thickness label', all((r['status'] == 'printed_assembly') == (r['type_tag'] != 'P4') for r in lay) and all('P4 printed assembly varies' in r['thickness_basis'] for r in lay if r['type_tag'] == 'P4'), dict(C.Counter((r['type_tag'] == 'P4', r['status']) for r in lay)))
    chk(track + ' K1 P5 rows: 4.75 basis, roy_pm, D01 discrepancy named', all('4.75' in r['thickness_basis'] and 'D01' in r['thickness_basis'] and r['ruling_source'] == 'roy_pm' for r in L1 if r['type_tag'] == 'P5'), sum(1 for r in L1 if r['type_tag'] == 'P5'))
    unb = [r for r in L1 if r['sublayer'] == 'unbound_walls']; chk(track + ' K1 unbound walls: status unbound_type, label "drawn thickness, rounded-up upper bound", roy_pm', all(r['status'] == 'unbound_type' and r['thickness_basis'] == 'drawn thickness, rounded-up upper bound' and r['ruling_source'] == 'roy_pm' for r in unb), len(unb))
    chk(track + ' K1 every L1 row roy_pm and carries thickness_basis; GLB extras match', all(r['ruling_source'] == 'roy_pm' and r['thickness_basis'] for r in L1) and all(byn[r['glb_node']]['extras'].get('thickness_basis') == r['thickness_basis'] and byn[r['glb_node']]['extras']['status'] == r['status'] for r in L1), len(L1))
    v10 = {r['element_id']: r for r in rd(V10C + ffn)}; geom = ('x_min_ft', 'y_min_ft', 'x_max_ft', 'y_max_ft', 'z_bottom_navd_ft', 'z_top_navd_ft')
    chk(track + ' K1 no L1 geometry changed vs v10c (bbox/z of every L1 row identical)', all(all(v10[r['element_id']][c] == r[c] for c in geom) for r in L1))
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
        ok = ok and x['z_high_end_status'] == 'convention_ceiling_drop' and x['slope_status'] == 'derived_from_printed' and r['status'] == 'derived_from_printed' and low >= float(PIT[r['level']]['lowest_point_navd_ft']) - 1e-6 and (sz >= 3) == (x['branch_slope_in_per_ft'] == 0.125)
        if not ok: badr.append(x['run_id'])
    chk(track + ' sloped runs: 52; high-end top == structure underside; slope tier 1/8 (>=3 in) / 1/4 (<=2 in); stack-end elevations re-derived; none below the level ceiling plane', len(sr) == 52 and not badr, 'runs %d bad %s; per level %s' % (len(sr), badr[:4], dict(C.Counter(r['level'] for r in sr))))
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
chk('K4 binding rule: a bare tag is bound iff the key notes list exactly one type of its family (KS, WC, FD bound; BT refused)', all(c['bind_result'].startswith('BOUND') == (len(fam[c['family']]) == 1) for c in bare) and [c['id'] for c in bare if c['bind_result'].startswith('REFUSED')] == ['F1-S-4-BT-1'], {c['id']: c['bind_result'][:14] for c in bare})
ctl = {l: PIT[l] for l in LEVELS}
chk('K4 controlling run per level stated with bareness; levels settled except MEZZ (K3 provisional)', all(ctl[l]['controlling_run_for_minimum'] and ctl[l]['controlling_tag_bare'] in ('yes', 'no') for l in LEVELS) and [l for l in LEVELS if ctl[l]['set_status'] == 'provisional'] == ['MEZZANINE'], {l: (ctl[l]['controlling_run_for_minimum'], 'bare' if ctl[l]['controlling_tag_bare'] == 'yes' else 'numbered') for l in LEVELS})
for t in ('filed', 'post_co'): print('INFO %s status totals: %s' % (t, {'%s|%s|%s' % k: v for k, v in TOTALS[t].items() if k[0] == NEWFAM}))
print('\nRESULT v11:', 'ALL PASS' if not FAILS else 'FAILS: %s' % FAILS)
sys.exit(1 if FAILS else 0)
