# verify_v10.py: measurement checks on the written v1.0 files (GLB re-parsed, CSV, v09b). Run: python verify_v10.py > verify_out.txt ; exit code 1 on any FAIL.
import struct, json, csv, array, collections as C, math, sys
from shapely.geometry import box as sb
from shapely.ops import unary_union
R = 'C:/Users/asddd/bv-worktrees/'; V9 = R + 'model_export_v09b/'; H = R + 'model_export_v10/'
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
for track, (efn, gfn, ffn) in {'filed': ('elements_filed.csv', 'model_filed.glb', 'framing_elements_filed.csv'), 'post_co': ('elements_postco.csv', 'model_postco.glb', 'framing_elements_post_co.csv')}.items():
    print('\n######## TRACK', track)
    g, binb = parse(H + gfn); g9, _ = parse(V9 + gfn); F = rd(H + ffn); E = {r['id']: r for r in rd(V9 + efn)}
    N = g['nodes']; names = C.Counter(n['name'] for n in N); IDX = {n['name']: i for i, n in enumerate(N) if 'mesh' in n}
    ref = C.Counter()
    for n in N: ref.update(n.get('children', []))
    for r in g['scenes'][0]['nodes']: ref[r] += 1
    chk(track + ' every node referenced exactly once', all(ref[i] == 1 for i in range(len(N))))
    bad = 0; badi = 0
    for i, m in enumerate(g['meshes']):
        for pr in m['primitives']:
            arr, nc, a, bv = acc(g, binb, pr['attributes']['POSITION']); assert bv['byteOffset'] + bv['byteLength'] <= len(binb)
            if 'min' in a:
                mn = [min(arr[k::3]) for k in range(3)]; mx = [max(arr[k::3]) for k in range(3)]
                if any(abs(a['min'][k] - mn[k]) > 1e-4 or abs(a['max'][k] - mx[k]) > 1e-4 for k in range(3)): bad += 1
            if 'indices' in pr:
                ia, _, _, _ = acc(g, binb, pr['indices']); badi += (max(ia) >= a['count'])
    chk(track + ' accessor min/max == data; index range ok', bad == 0 and badi == 0, 'bad=%d badidx=%d meshes=%d' % (bad, badi, len(g['meshes'])))
    dup9 = C.Counter(n['name'] for n in g9['nodes'] if 'mesh' in n)
    chk(track + ' every original (v09b) mesh-node name present in v10 the same number of times', all(names[k] == v for k, v in dup9.items()), 'v09b mesh nodes %d' % len(dup9))
    orig_ids = {n['name'] for n in g9['nodes'] if n.get('extras', {}).get('id') == n['name'] and not n['extras'].get('derived')}
    chk(track + ' original element ids (non-derived) present exactly once', all(names[i] == 1 for i in orig_ids), len(orig_ids))
    chk(track + ' v09b mesh index untouched for all original nodes', all(N[IDX[o['name']]].get('mesh') == o.get('mesh') for o in g9['nodes'] if 'mesh' in o and names[o['name']] == 1 and o['name'] in IDX and not (g9['meshes'][o['mesh']]['name'] != o['name'] and False)))
    def box(name):
        n = N[IDX[name]]; arr, nc, a, bv = acc(g, binb, g['meshes'][n['mesh']]['primitives'][0]['attributes']['POSITION']); return (a['min'][0], -a['max'][2], a['max'][0], -a['min'][2], a['min'][1], a['max'][1])
    LINES = ('wall_stud_line', 'wall_track_line', 'sw_field_stud_line', 'sw_diagonal_strap', 'opening_head_line', 'beam_member_outline')
    mism = 0; nchk = 0
    for r in F:
        if r['glb_node'] not in IDX: mism += 1; continue
        if r['class'] in LINES or r['class'] == 'gusset_plate': continue
        b = box(r['glb_node']); nchk += 1; c = [fl(r['x_min_ft']), fl(r['y_min_ft']), fl(r['x_max_ft']), fl(r['y_max_ft']), fl(r['z_bottom_navd_ft']), fl(r['z_top_navd_ft'])]
        tol = 0.051 if r['class'] == 'hold_down_bound' else 0.002   # v0.9b draws hold-downs 0.05 ft larger than the footprint (rendering aid, README v0.7 R4)
        if any(abs(c[k] - b[k]) > tol for k in range(6)): mism += 1
    chk(track + ' CSV bbox/z == GLB node extents (box nodes)', mism == 0, 'checked %d rows, mismatches %d' % (nchk, mism))
    cnt_csv = C.Counter((r['layer'], r['sublayer']) for r in F); cnt_glb = C.Counter()
    for n in N:
        if n.get('extras', {}).get('added_in') == 'v1.0' and 'mesh' in n:
            ex = n['extras']; k = (ex['layer'], ex['sublayer'])
            if ex['class'] in ('wall_stud_line', 'sw_field_stud_line'): cnt_glb[k] += ex['stud_count']
            elif ex['class'] == 'wall_track_line': cnt_glb[k] += 2
            else: cnt_glb[k] += 1
    chk(track + ' rows per sublayer == elements per sublayer in the GLB', cnt_csv == cnt_glb, '' if cnt_csv == cnt_glb else {k: (cnt_csv[k], cnt_glb[k]) for k in set(cnt_csv) | set(cnt_glb) if cnt_csv[k] != cnt_glb[k]})
    lg = {n['name']: len(n.get('children', [])) for n in N if n['name'].startswith('LAYER L')}
    print('GLB layer groups (children): ' + '; '.join('%s=%d' % kv for kv in sorted(lg.items())))
    print('counts per layer | sublayer (%s):' % track)
    for k in sorted(cnt_csv): print('   %-26s %-40s %d' % (k[0], k[1], cnt_csv[k]))
    print('counts per status (%s): %s' % (track, dict(C.Counter(r['status'] for r in F))))
    chk(track + ' every element has source sheet, detail ref, status', all(r['source_sheet'] and r['detail_ref'] and r['status'] for r in F))
    chk(track + ' status vocabulary', set(r['status'] for r in F) <= {'measured_from_plan', 'rule_from_printed_detail', 'rule_from_continuity', 'schedule_merged_cell', 'header_size_unknown', 'unbound_type', 'identified_visually', 'measured_from_drawing'}, sorted({r['status'] for r in F}))
    # ---- L1
    W = [e for e in E.values() if e['class'] == 'wall']; lay = [r for r in F if r['class'].startswith('wall_layer')]
    bound_walls = {r['host_or_parent_id'].split('#')[0] for r in lay}; tagged = {e['id'] for e in W if e['tag'] in ('P1', 'P2', 'P3', 'P4', 'P5', 'W1', 'W2') and e['id'] in names}
    chk(track + ' L1 type layers exist only on tag-bound walls, and on all of them', bound_walls == tagged, '%d walls layered; %d tag-bound drawn walls; %d wall rows in v09b' % (len(bound_walls), len(tagged), len(W)))
    unb = [r for r in F if r['sublayer'] == 'unbound_walls']; chk(track + ' unbound walls: solid, status unbound_type, empty tag', all(r['status'] == 'unbound_type' and E[r['host_or_parent_id'].split('#')[0]]['tag'] == '' for r in unb), '%d pieces on %d walls' % (len(unb), len({r['host_or_parent_id'].split('#')[0] for r in unb})))
    out_len = 0; out_thk = 0
    for r in lay + [r for r in F if r['class'] == 'wall_stud_line']:
        wid, k = r['host_or_parent_id'].split('#'); x0, y0, x1, y1 = bb(pcs_of(E[wid])[int(k)]); a = [fl(r['x_min_ft']), fl(r['y_min_ft']), fl(r['x_max_ft']), fl(r['y_max_ft'])]
        if (x1 - x0) >= (y1 - y0):
            out_len += (a[0] < x0 - 0.01 or a[2] > x1 + 0.01); out_thk += (a[1] < y0 - 0.1 or a[3] > y1 + 0.1)
        else:
            out_len += (a[1] < y0 - 0.01 or a[3] > y1 + 0.01); out_thk += (a[0] < x0 - 0.1 or a[2] > x1 + 0.1)
    chk(track + ' L1 elements inside host wall along its length (+-0.01 ft)', out_len == 0, out_len)
    print('INFO %s L1 layer/stud elements whose across-wall extent exceeds the measured wall by > 0.1 ft: %d (printed assembly vs measured thickness)' % (track, out_thk))
    byt = C.defaultdict(list)
    for e in W:
        if e['tag'] and e['id'] in names:
            for pts in pcs_of(e): byt[e['tag']].append(round(sorted([math.dist(pts[0], pts[1]), math.dist(pts[1], pts[2])])[0] * 12, 2))
    for t, v in sorted(byt.items()): print('INFO %s %s measured thickness in: min %.2f max %.2f pieces=%d' % (track, t, min(v), max(v), len(v)))
    # ---- L3
    frames = {r['glb_node'].split(':frame')[0]: r for r in F if r['sublayer'] == 'frames'}; fa = {r['glb_node'].split(':fill_above')[0]: r for r in F if r['sublayer'] == 'wall_fill_above_opening'}
    bad = []; badin = []; badw = []; DIST = []
    for oid, r in frames.items():
        e = E[oid]; wid, k = e['host_wall_id'].split('#'); w = E[wid]
        # the v0.9b wall geometry is already split into pieces with a GAP at each opening, so the opening sits in a gap of its host wall:
        # measured test = distance from the opening box to the union of the host wall's piece boxes (tolerance 0.3 ft = 3.6 in) AND the opening's thickness band lies on the wall's.
        U = unary_union([sb(*bb(p)) for p in pcs_of(w)]); ob = sb(fl(r['x_min_ft']), fl(r['y_min_ft']), fl(r['x_max_ft']), fl(r['y_max_ft'])); dist = ob.distance(U); DIST.append(dist)
        if dist > 0.3: badin.append(oid)
        if not (fl(w['z_draw_bottom_navd_ft']) - 1e-3 <= fl(r['z_bottom_navd_ft']) and fl(r['z_top_navd_ft']) <= fl(w['z_draw_top_navd_ft']) + 1e-3): badin.append(oid)
        wd = max(fl(r['x_max_ft']) - fl(r['x_min_ft']), fl(r['y_max_ft']) - fl(r['y_min_ft'])) * 12
        if e['opening_width_in'] and abs(wd - float(e['opening_width_in'])) > 0.6: badw.append((oid[-6:], round(wd, 2), e['opening_width_in']))
        if oid in fa:
            f = fa[oid]; same = all(abs(fl(f[c]) - fl(r[c])) < 1e-3 for c in ('x_min_ft', 'y_min_ft', 'x_max_ft', 'y_max_ft'))
            if not (same and fl(f['z_bottom_navd_ft']) >= fl(r['z_top_navd_ft']) - 1e-4 and fl(f['z_top_navd_ft']) <= fl(w['z_draw_top_navd_ft']) + 1e-4 and f['status'] == 'header_size_unknown'): bad.append(oid)
    chk(track + ' L3 opening sits in its host wall (gap distance <= 0.3 ft) and z inside the wall z range', not badin, '%d openings; max gap distance %.3f ft; bad %s' % (len(frames), max(DIST), badin[:5]))
    chk(track + ' L3 fill above opening: same width as opening, starts at/above head, below wall top, header_size_unknown', not bad, 'fills %d; bad %s' % (len(fa), bad[:5]))
    chk(track + ' L3 frame width == schedule opening width (+-0.6 in) where one exists', not badw, '%d off: %s' % (len(badw), badw[:5]))
    chk(track + ' L3 no header/king/trimmer/jamb member element exists', not any(x in r['class'] for r in F for x in ('king', 'trimmer', 'jamb', 'header_member')))
    # ---- L2
    env = {}
    for e in E.values():
        if e['class'] in ('wall', 'struct_joist_bay', 'struct_shear_wall') and e['id'] in names and e['x_min_ft']:
            b = [fl(e['x_min_ft']), fl(e['y_min_ft']), fl(e['x_max_ft']), fl(e['y_max_ft'])]; v = env.setdefault(e['level'], list(b)); v[0] = min(v[0], b[0]); v[1] = min(v[1], b[1]); v[2] = max(v[2], b[2]); v[3] = max(v[3], b[3])
    dd = {r['sheet']: r['designation'] for r in rd(H + 'box_beam_designations.csv') if r['kind'] == 'note4'}; bm = [r for r in F if r['layer'] == 'L2_box_beams']; outb = []
    for r in bm:
        v = env[r['level']]
        if fl(r['x_min_ft']) < v[0] - 0.5 or fl(r['y_min_ft']) < v[1] - 0.5 or fl(r['x_max_ft']) > v[2] + 0.5 or fl(r['y_max_ft']) > v[3] + 0.5: outb.append(r['element_id'][-20:])
    chk(track + ' L2 beam members within the level plan envelope (+0.5 ft)', not outb, '%d members; outside %s' % (len(bm), outb[:5]))
    sol = [r for r in bm if r['sublayer'] == 'box_beam_members']
    chk(track + ' L2 designation == own sheet note 4 (S-104 = -118, others -54)', all(r['designation_as_printed'] == '(2) ' + dd[r['source_sheet'].split(' ')[0]] for r in sol), dict(C.Counter(r['designation_as_printed'] + ' @ ' + r['source_sheet'].split(' ')[0] for r in sol)))
    chk(track + ' L2 box-beam member depth = 8 in', all(abs((fl(r['z_top_navd_ft']) - fl(r['z_bottom_navd_ft'])) * 12 - 8.0) < 0.05 for r in sol), 'members %d = 2 x %d beams' % (len(sol), len(sol) // 2))
    # ---- L4
    j = [r for r in F if r['class'] == 'joist']
    chk(track + ' L4 joists 358 = joists + over_stair_underlay_unconfirmed (28)', len(j) == 358 and sum(r['sublayer'] == 'over_stair_underlay_unconfirmed' for r in j) == 28, dict(C.Counter(r['sublayer'] for r in j)))
    chk(track + ' L4 joists status rule_from_continuity and WITHHELD', all(r['status'] == 'rule_from_continuity' and 'WITHHELD' in r['notes'] for r in j))
    pn = [r for r in F if r['class'] == 'floor_panel']
    chk(track + ' L4 panel 3/4 in thick', all(abs((fl(r['z_top_navd_ft']) - fl(r['z_bottom_navd_ft'])) * 12 - 0.75) < 0.01 for r in pn), '%d panel boxes' % len(pn))
    U = {lv: unary_union([sb(fl(r['x_min_ft']), fl(r['y_min_ft']), fl(r['x_max_ft']), fl(r['y_max_ft'])) for r in pn if r['level'] == lv]) for lv in {r['level'] for r in pn}}
    outj = [r['element_id'] for r in j if not U[r['level']].buffer(0.05).contains(sb(fl(r['x_min_ft']), fl(r['y_min_ft']), fl(r['x_max_ft']), fl(r['y_max_ft'])))]
    chk(track + ' L4 every joist lies inside the panel extent (+-0.05 ft)', not outj, len(outj))
    # ---- L5
    gu = [r for r in F if r['class'] == 'gusset_plate']; st = [r for r in F if r['class'] == 'sw_diagonal_strap']; hd = [r for r in F if r['class'] == 'hold_down_bound']; em = [r for r in F if r['class'] == 'sw_end_member']
    chk(track + ' L5 gussets 168, roof 8 clash_include=no', len(gu) == 168 and sum(r['clash_include'] == 'no' for r in gu) == 8, (len(gu), sum(r['clash_include'] == 'no' for r in gu)))
    chk(track + ' L5 hold-downs: 20 bound drawn', len(hd) == 20, len(hd))
    badst = 0
    for s in st:
        arr, nc, a, bv = acc(g, binb, g['meshes'][N[IDX[s['glb_node']]]['mesh']]['primitives'][0]['attributes']['POSITION']); pts = [(arr[0], -arr[2], arr[1]), (arr[3], -arr[5], arr[4])]; ok = 0
        for p in pts:
            if any(abs(fl(q['x_min_ft']) - p[0]) < 1e-3 and abs(fl(q['y_min_ft']) - p[1]) < 1e-3 and abs((fl(q['z_bottom_navd_ft']) + fl(q['z_top_navd_ft'])) / 2 - p[2]) < 1e-3 for q in gu): ok += 1
        badst += ok != 2
    chk(track + ' L5 straps: both endpoints coincide with a gusset centre; 84 = 2 per panel x 42', badst == 0 and len(st) == 84, (len(st), badst))
    inside = 0
    for r in em:
        e = E[r['host_or_parent_id']]; b = [fl(e['x_min_ft']), fl(e['y_min_ft']), fl(e['x_max_ft']), fl(e['y_max_ft'])]
        if not (fl(r['x_min_ft']) >= b[0] - 1e-3 and fl(r['y_min_ft']) >= b[1] - 1e-3 and fl(r['x_max_ft']) <= b[2] + 1e-3 and fl(r['y_max_ft']) <= b[3] + 1e-3): inside += 1
    chk(track + ' L5 end members inside their shear-wall footprint', inside == 0, '%d members, %d outside' % (len(em), inside))
    tb = [r for r in F if r['sublayer'] == 'top_bottom_members']; chk(track + ' L5 top/bottom members all schedule_merged_cell', all(r['status'] == 'schedule_merged_cell' for r in tb), len(tb))
    print('SW4&5 FLOOR_1>FLOOR_2 plate statuses (%s): %s' % (track, dict(C.Counter(r['status'] for r in gu if r['host_or_parent_id'].startswith(('SW 4 FLOOR_1', 'SW 5 FLOOR_1'))))))
print('\nRESULT:', 'ALL PASS' if not FAILS else 'FAILS: %s' % FAILS)
sys.exit(1 if FAILS else 0)
