# v1.0 exporter: v0.9b GLB + CSVs (read-only, copied forward) + ADDED toggleable layers L1..L5. Nothing in v09b is edited; original nodes/ids are kept exactly once.
# Run: python build_v10.py   (writes into this folder). Filed and post-CO are separate tracks, never summed.
# Rule: every element carries source sheet, detail ref, status. No typical values from outside the plans. Not-printed items -> not_modelled.csv, never drawn.
import sys, os, csv, json, math, struct, collections as C
import numpy as np
R = 'C:/Users/asddd/bv-worktrees/'; V9 = R + 'model_export_v09b/'; H = R + 'model_export_v10/'
rd = lambda p: list(csv.DictReader(open(p, encoding='utf8')))
fl = lambda x: float(x) if x not in ('', None) else None
TR = {'filed': ('elements_filed.csv', 'model_filed.glb'), 'post_co': ('elements_postco.csv', 'model_postco.glb')}
PANEL_FT = 0.75 / 12
# ---------------------------------------------------------------- printed wall assemblies (A-500.00, AR - 3.28.25.pdf p24; read from the RENDER, dimension strings at the foot of each section)
# layers listed from "side A" to "side B" (inches). kind: gyp = sheetrock family, stud = metal stud/channel (cavity), fin = non-sheetrock finish
A500 = 'A-500.00 (AR - 3.28.25.pdf p24)'
TYPES = {
    'P1': dict(printed_total=6.0, gauge='20 GAUGE MIN.', stud='3 1/2" METAL STUD 16" O.C.', oc=16, layers=[('gyp', 0.625, '5/8" gypsum (printed: 5/8 + 5/8)'), ('gyp', 0.625, '5/8" gypsum'), ('stud', 3.5, '3 1/2" METAL STUD'), ('gyp', 0.625, '5/8" gypsum'), ('gyp', 0.625, '5/8" gypsum')],
               note='leader on the section: FACE PANEL LAYER IMPACT RESISTANT WALL BOARD + 2 LAYERS 5/8" GYPSUM BOARD STAGGERED; only 2 x 5/8 per side are dimensioned, so the face panel is not given its own thickness'),
    'P2': dict(printed_total=6.0, gauge='not printed', stud='3 1/2" METAL STUD 16" O.C.', oc=16, layers=[('gyp', 0.625, '5/8" gypsum'), ('gyp', 0.625, '5/8" gypsum'), ('stud', 3.5, '3 1/2" METAL STUD'), ('gyp', 0.625, '5/8" gypsum'), ('gyp', 0.625, '5/8" gypsum')], note=''),
    'P3': dict(printed_total=3.75, gauge='not printed', stud='2 1/2" METAL STUD 16" O.C.', oc=16, layers=[('gyp', 0.625, '5/8" gypsum'), ('stud', 2.5, '2 1/2" METAL STUD'), ('gyp', 0.625, '5/8" gypsum')], note=''),
    'P4': dict(printed_total=None, gauge='not printed', stud='1 5/8" METAL STUDS 16" O.C.', oc=16, layers=None, note='thickness VARIES (printed); 2 x 5/8" gypsum on each face, 1 5/8" studs each side of the mechanical shaft; cavity = measured thickness minus the printed layers'),
    'P5': dict(printed_total=3.75, gauge='20 GA.', stud='2 1/2" CH STUDS 16" O.C.', oc=16, layers=[('gyp', 0.625, '5/8" gypsum (corridor side)'), ('gyp', 0.625, '5/8" gypsum (corridor side)'), ('stud', 2.5, '2 1/2" CH STUDS'), ('gyp', 1.0, '1" gypsum liner panel (shaft side)')],
               note='printed total 3 3/4" but the printed parts (5/8+5/8+2 1/2+1) sum to 4 3/4"; layers drawn as printed, orientation corridor/shaft not tied to the plan'),
    'P6': dict(printed_total=7.25, gauge='not printed', stud='3 1/2" METAL STUD 16" O.C.', oc=16, layers=[('gyp', 0.625, '5/8" gypsum')] * 3 + [('stud', 3.5, '3 1/2" METAL STUD')] + [('gyp', 0.625, '5/8" gypsum')] * 3, note=''),
    'W1': dict(printed_total=9.25, gauge='not printed', stud='6" METAL STUD 16" O.C.', oc=16, layers=[('fin', 2.0, 'R-11.5 EPS INSULATION WITH STUCCO FINISH (2" printed)'), ('gyp', 0.625, '5/8" EXTERIOR DENS GLASS BOARD'), ('stud', 6.0, '6" METAL STUD'), ('gyp', 0.625, '5/8" gypsum (interior)')], note='side A = EXTERIOR (printed); assigned to the outward side by footprint centroid'),
    'W2': dict(printed_total=10.75, gauge='not printed', stud='6" METAL STUD 16" O.C.', oc=16, layers=[('fin', 2.25, 'R-11.5 EPS INSULATION WITH STUCCO FINISH (2 1/4" printed)'), ('gyp', 0.625, '5/8" EXTERIOR DENS GLASS BOARD'), ('gyp', 0.625, '5/8" EXTERIOR DENS GLASS BOARD'), ('stud', 6.0, '6" METAL STUD'), ('gyp', 0.625, '5/8" gypsum (interior)'), ('gyp', 0.625, '5/8" gypsum (interior)')], note='side A = EXTERIOR (printed); assigned to the outward side by footprint centroid'),
}
OUTWARD = ('W1', 'W2')
# ---------------------------------------------------------------- geometry
def rect_from_pts(pts):
    p = np.array(pts, float); e1 = p[1] - p[0]; e2 = p[2] - p[1]
    if np.linalg.norm(e1) >= np.linalg.norm(e2): u = e1 / np.linalg.norm(e1); L = np.linalg.norm(e1); T = np.linalg.norm(e2)
    else: u = e2 / np.linalg.norm(e2); L = np.linalg.norm(e2); T = np.linalg.norm(e1)
    return dict(c=p.mean(axis=0), u=u, L=float(L), T=float(T))
def rect_from_bbox(x0, y0, x1, y1):
    if (x1 - x0) >= (y1 - y0): return dict(c=np.array([(x0 + x1) / 2, (y0 + y1) / 2]), u=np.array([1.0, 0.0]), L=x1 - x0, T=y1 - y0)
    return dict(c=np.array([(x0 + x1) / 2, (y0 + y1) / 2]), u=np.array([0.0, 1.0]), L=y1 - y0, T=x1 - x0)
def corners(c, u, L, T):
    n = np.array([-u[1], u[0]]); return [c - u * L / 2 - n * T / 2, c + u * L / 2 - n * T / 2, c + u * L / 2 + n * T / 2, c - u * L / 2 + n * T / 2]
def sub(rc, d, t, s0=None, s1=None):
    """sub-rectangle of rect rc: offset d (ft) along the normal, thickness t, optional [s0,s1] range along u measured from the piece start."""
    n = np.array([-rc['u'][1], rc['u'][0]]); L = rc['L']; a = 0 if s0 is None else s0; b = L if s1 is None else s1
    c = rc['c'] + n * d + rc['u'] * ((a + b) / 2 - L / 2); return dict(c=c, u=rc['u'], L=b - a, T=t)
def bbox_of(cs): a = np.array(cs); return a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max()
class GLB:
    def __init__(s, path):
        b = open(path, 'rb').read(); jl, _ = struct.unpack_from('<I4s', b, 12); s.g = json.loads(b[20:20 + jl]); off = 20 + jl
        bl, _ = struct.unpack_from('<I4s', b, off); s.bin = bytearray(b[off + 8: off + 8 + bl]); s.names = {n['name']: i for i, n in enumerate(s.g['nodes'])}
        s.mats = {}; s.fam = {}; s.sub = {}
    def _pad(s):
        while len(s.bin) % 4: s.bin.append(0)
    def _acc(s, arr, ct, typ, target, mm=True):
        s._pad(); off = len(s.bin); s.bin += arr.tobytes()
        s.g['bufferViews'].append(dict(buffer=0, byteOffset=off, byteLength=len(arr.tobytes()), target=target))
        a = dict(bufferView=len(s.g['bufferViews']) - 1, componentType=ct, count=int(arr.shape[0]), type=typ)
        if mm: a['min'] = [float(v) for v in (arr.min(axis=0) if arr.ndim > 1 else [arr.min()])]; a['max'] = [float(v) for v in (arr.max(axis=0) if arr.ndim > 1 else [arr.max()])]
        s.g['accessors'].append(a); return len(s.g['accessors']) - 1
    def material(s, name, rgba):
        if name not in s.mats:
            s.g['materials'].append({'name': name, 'pbrMetallicRoughness': {'baseColorFactor': list(rgba), 'metallicFactor': 0.0, 'roughnessFactor': 0.9}, 'doubleSided': True, **({'alphaMode': 'BLEND'} if rgba[3] < 1 else {})}); s.mats[name] = len(s.g['materials']) - 1
        return s.mats[name]
    def box_mesh(s, name, poly4, z0, z1, mat):
        P = [(float(p[0]), float(p[1])) for p in poly4]; V = []; N = []; I = []
        def quad(a, b, c, d, nrm):
            k = len(V); V.extend([a, b, c, d]); N.extend([nrm] * 4); I.extend([k, k + 1, k + 2, k, k + 2, k + 3])
        top = [(x, z1, -y) for x, y in P]; bot = [(x, z0, -y) for x, y in P]
        quad(*top[::-1], (0, 1, 0)); quad(*bot, (0, -1, 0))
        for i in range(4):
            j = (i + 1) % 4; ex, ey = P[j][0] - P[i][0], P[j][1] - P[i][1]; ln = math.hypot(ex, ey) or 1.0; nrm = (ey / ln, 0, ex / ln)
            quad(bot[i], bot[j], top[j], top[i], nrm)
        pa = s._acc(np.array(V, np.float32), 5126, 'VEC3', 34962); na = s._acc(np.array(N, np.float32), 5126, 'VEC3', 34962, False); ia = s._acc(np.array(I, np.uint32), 5125, 'SCALAR', 34963)
        s.g['meshes'].append(dict(name=name, primitives=[dict(attributes=dict(POSITION=pa, NORMAL=na), material=mat, mode=4, indices=ia)])); return len(s.g['meshes']) - 1
    def line_mesh(s, name, segs, mat):
        A = np.array([[x, z, -y] for seg in segs for (x, y, z) in seg], np.float32)
        pa = s._acc(A, 5126, 'VEC3', 34962); s.g['meshes'].append(dict(name=name, primitives=[dict(attributes=dict(POSITION=pa), material=mat, mode=1)])); return len(s.g['meshes']) - 1
    def node(s, name, mesh, extras, sublayer):
        s.g['nodes'].append(dict(name=name, mesh=mesh, extras=extras)); i = len(s.g['nodes']) - 1; s.sub[sublayer].append(i); return i
    def open_layer(s, fam, subname):
        if fam not in s.fam: s.fam[fam] = []
        s.sub[subname] = []; s.fam[fam].append(subname)
    def close(s):
        for fam, subs in s.fam.items():
            kids = []
            for sn in subs:
                s.g['nodes'].append(dict(name='LAYER ' + sn, children=s.sub[sn], extras=dict(layer='class', family=fam, class_layer=sn, z_unknown=False, added_in='v1.0'))); kids.append(len(s.g['nodes']) - 1)
            s.g['nodes'].append(dict(name='LAYER ' + fam, children=kids, extras=dict(layer='family', family=fam, added_in='v1.0')))
            s.g['scenes'][0]['nodes'].append(len(s.g['nodes']) - 1)
    def write(s, path):
        s._pad(); s.g['buffers'][0]['byteLength'] = len(s.bin); js = json.dumps(s.g, separators=(',', ':')).encode('utf8')
        while len(js) % 4: js += b' '
        tot = 12 + 8 + len(js) + 8 + len(s.bin)
        with open(path, 'wb') as f: f.write(struct.pack('<4sII', b'glTF', 2, tot)); f.write(struct.pack('<I4s', len(js), b'JSON')); f.write(js); f.write(struct.pack('<I4s', len(s.bin), b'BIN\x00')); f.write(s.bin)
# ---------------------------------------------------------------- build one track
COLS = ['element_id', 'track', 'layer', 'sublayer', 'class', 'level', 'source_sheet', 'detail_ref', 'status', 'position_status', 'host_or_parent_id', 'type_tag', 'designation_as_printed', 'x_min_ft', 'y_min_ft', 'x_max_ft', 'y_max_ft', 'z_bottom_navd_ft', 'z_top_navd_ft', 'size_note', 'clash_include', 'glb_node', 'notes']
def build(track):
    efn, gfn = TR[track]; E = rd(V9 + efn); G = GLB(V9 + gfn); ROWS = []; NM = []   # NM = not modelled
    byid = {r['id']: r for r in E}; names = G.names
    def emit(layer, sub, cls, r, nid, sheet, ref, status, posst, host, tag, desig, bb, z0, z1, note='', size_note='', clash='yes', mesh=None, mesh_from=None, extras=None):
        ex = dict(id=nid, track=track, level=r['level'] if isinstance(r, dict) else r, **{'class': cls}, layer=layer, sublayer=sub, status=status, position_status=posst, source_sheet=sheet, detail_ref=ref, designation_as_printed=desig, derived=True, added_in='v1.0', clash_include=clash)
        if extras: ex.update(extras)
        if mesh is None: mesh = G.g['nodes'][names[mesh_from]]['mesh']
        G.node(nid, mesh, ex, layer + ' | ' + sub if False else sub_name(layer, sub))
        ROWS.append(dict(zip(COLS, [nid, track, layer, sub, cls, ex['level'], sheet, ref, status, posst, host, tag, desig, round(bb[0], 3), round(bb[1], 3), round(bb[2], 3), round(bb[3], 3), round(z0, 4), round(z1, 4), size_note, clash, nid, note])))
    def sub_name(layer, sub): return layer + ' | ' + sub
    def nm(kind, ident, reason, sheet='', ref='', level='', n=1): NM.append(dict(track=track, kind=kind, element_or_item=ident, level=level, count=n, reason=reason, source_sheet=sheet, detail_ref=ref))
    LAYERS = {'L1_wall_assemblies': ['sheetrock', 'finish_exterior', 'studs_track', 'unbound_walls'], 'L2_box_beams': ['box_beam_members', 'label_governed_beams_depth_unknown'],
              'L3_openings': ['frames', 'heads', 'wall_fill_above_opening', 'wall_fill_below_sill'], 'L4_floor_panel_joists': ['floor_panel', 'joists', 'over_stair_underlay_unconfirmed'],
              'L5_shear_walls': ['end_members', 'top_bottom_members', 'field_studs', 'straps', 'gusset_plates', 'hold_downs_bound']}
    for fam, subs in LAYERS.items():
        for sn in subs: G.open_layer(fam, fam + ' | ' + sn)
    mats = {'sheetrock': G.material('L1 sheetrock', (0.93, 0.93, 0.85, 1)), 'finish': G.material('L1 exterior finish', (0.75, 0.6, 0.5, 1)), 'studs': G.material('L1 studs/track lines', (0.2, 0.4, 0.8, 1)), 'unbound': G.material('L1 unbound_type solid', (0.6, 0.6, 0.6, 1)),
            'beam': G.material('L2 box beam member', (0.85, 0.35, 0.1, 1)), 'beamlbl': G.material('L2 label governed (depth unknown) outline', (0.9, 0.7, 0.1, 1)),
            'frame': G.material('L3 frame', (0.2, 0.7, 0.3, 0.6)), 'head': G.material('L3 head', (0.1, 0.5, 0.2, 1)), 'fill': G.material('L3 wall fill', (0.7, 0.5, 0.9, 0.6)),
            'panel': G.material('L4 floor panel', (0.85, 0.8, 0.5, 0.8)), 'joist': G.material('L4 joists', (0.4, 0.6, 0.9, 1)), 'stairj': G.material('L4 over stair underlay (unconfirmed)', (0.9, 0.2, 0.6, 1)),
            'sw': G.material('L5 members', (0.8, 0.15, 0.15, 1)), 'strap': G.material('L5 straps', (0.1, 0.1, 0.1, 1)), 'gus': G.material('L5 gussets', (0.9, 0.5, 0.1, 1)), 'hd': G.material('L5 hold-downs bound', (0.5, 0.1, 0.5, 1))}
    # ======================================================= L1 walls
    walls = []
    for r in E:
        if r['class'] != 'wall': continue
        if r['id'] not in names or not r['x_min_ft']: nm('wall', r['id'], 'not drawn in v0.9b (no placed geometry / excluded)', r['sheet'], '', r['level']); continue
        walls.append(r)
    ctr = {}
    pcs_all = {}
    for w in walls:
        pcs = []
        if w['footprint_pts_ft']:
            for pc in w['footprint_pts_ft'].split('|'): pcs.append(rect_from_pts([tuple(map(float, q.split(','))) for q in pc.split(';')]))
        else: pcs.append(rect_from_bbox(fl(w['x_min_ft']), fl(w['y_min_ft']), fl(w['x_max_ft']), fl(w['y_max_ft'])))
        pcs_all[w['id']] = pcs
    for lv in {w['level'] for w in walls}:
        cs = [p['c'] for w in walls if w['level'] == lv for p in pcs_all[w['id']]]; ctr[lv] = np.mean(cs, axis=0)
    n_bound = n_unb = 0
    for w in walls:
        lv = w['level']; tag = w['tag']; z0 = fl(w['z_draw_bottom_navd_ft']); z1 = fl(w['z_draw_top_navd_ft']); T = TYPES.get(tag)
        for k, pc in enumerate(pcs_all[w['id']]):
            host = '%s#%d' % (w['id'], k); meas_in = pc['T'] * 12; bb = bbox_of(corners(pc['c'], pc['u'], pc['L'], pc['T']))
            if T is None:
                n_unb += 1; emit('L1_wall_assemblies', 'unbound_walls', 'wall_unbound_solid', w, host + ':solid', w['sheet'], 'plan wall piece; no type tag bound (a type is never bound by thickness)', 'unbound_type', 'measured_from_plan', w['id'], '', '', bb, z0, z1,
                                 note='plain solid at measured thickness %.2f in' % meas_in, size_note='measured thickness %.3f in' % meas_in, mesh=G.box_mesh(host + ':solid', corners(pc['c'], pc['u'], pc['L'], pc['T']), z0, z1, mats['unbound']))
                continue
            n_bound += 1
            n = np.array([-pc['u'][1], pc['u'][0]])
            flip = 1
            if tag in OUTWARD and np.dot(n, pc['c'] - ctr[lv]) < 0: flip = -1   # side A (exterior) toward +n*flip
            layers = T['layers']
            if layers is None:   # P4
                g = [('gyp', 0.625, '5/8" gypsum')] * 2; cav = meas_in - 2 * (2 * 0.625 + 1.625)
                layers = g + [('stud', 1.625, '1 5/8" METAL STUD (side A)'), ('cav', max(cav, 0), 'shaft cavity (VARIES; measured)'), ('stud', 1.625, '1 5/8" METAL STUD (side B)')] + g
            tot = sum(l[1] for l in layers); pos = -tot / 2; cnt = 0; studs_d = []
            for i, (kind, t, lbl) in enumerate(layers):
                d = (pos + t / 2) / 12 * (-flip if True else 1)   # offset along n; flip chooses which face is A
                pos += t
                if kind == 'stud': studs_d.append((d, t, lbl)); continue
                if kind == 'cav' or t <= 0: continue
                rc = sub(pc, d, t / 12); sublayer = 'finish_exterior' if kind == 'fin' else 'sheetrock'
                emit('L1_wall_assemblies', sublayer, 'wall_layer_' + kind, w, '%s:layer%d' % (host, i), A500, 'section of ' + tag + ' (dimension strings at the foot of the section)', 'rule_from_printed_detail', 'measured_from_plan (footprint); layer thickness printed', host, tag, lbl, bbox_of(corners(rc['c'], rc['u'], rc['L'], rc['T'])), z0, z1,
                     note=T['note'], size_note='printed layer %.4f in; wall measured %.3f in; printed total %s in; sum of drawn layers %.3f in' % (t, meas_in, T['printed_total'], tot), mesh=G.box_mesh('%s:layer%d' % (host, i), corners(rc['c'], rc['u'], rc['L'], rc['T']), z0, z1, mats['finish' if kind == 'fin' else 'sheetrock']))
            # studs (vertical lines) at the printed 16 in o.c.; track (lines) along base and head. No cross-section drawn: flange/web not printed.
            for (d, t, lbl) in (studs_d or [(0.0, 0, '')]):
                segs = []; sc = 0; s = 0.0
                while s <= pc['L'] + 1e-9:
                    p = pc['c'] + pc['u'] * (s - pc['L'] / 2) + n * d; segs.append([(p[0], p[1], z0), (p[0], p[1], z1)]); s += T['oc'] / 12; sc += 1
                sid = '%s:studs:%s' % (host, 'A' if d * -flip <= 0 else 'B') if len(studs_d) > 1 else '%s:studs' % host
                m = G.line_mesh(sid, segs, mats['studs'])
                for q in range(sc):
                    s_ = q * T['oc'] / 12; p = pc['c'] + pc['u'] * (s_ - pc['L'] / 2) + n * d
                    ROWS.append(dict(zip(COLS, ['%s:stud%d' % (sid, q), track, 'L1_wall_assemblies', 'studs_track', 'wall_stud_line', lv, A500, 'section of %s: %s' % (tag, T['stud']), 'rule_from_printed_detail', 'measured_from_plan (wall piece); stud origin at piece start (layout origin not printed)', host, tag, T['stud'] + '; gauge ' + T['gauge'], round(p[0], 3), round(p[1], 3), round(p[0], 3), round(p[1], 3), z0, z1, 'line only, no section: flange/web/size of the stud member not drawn', 'yes', sid, ''])))
                G.node(sid, m, dict(id=sid, track=track, level=lv, **{'class': 'wall_stud_line'}, layer='L1_wall_assemblies', sublayer='studs_track', status='rule_from_printed_detail', source_sheet=A500, detail_ref='section of ' + tag, designation_as_printed=T['stud'], stud_count=sc, derived=True, added_in='v1.0'), sub_name('L1_wall_assemblies', 'studs_track'))
            segs = []
            for z in (z0, z1):
                a = pc['c'] - pc['u'] * pc['L'] / 2; b = pc['c'] + pc['u'] * pc['L'] / 2; segs.append([(a[0], a[1], z), (b[0], b[1], z)])
            tid = host + ':track'; m = G.line_mesh(tid, segs, mats['studs'])
            G.node(tid, m, dict(id=tid, track=track, level=lv, **{'class': 'wall_track_line'}, layer='L1_wall_assemblies', sublayer='studs_track', status='rule_from_printed_detail', source_sheet=A500, detail_ref='A-500 P5 "RUNNERS SHALL BE SECURELY ATTACHED AT THE FLOOR AND CEILING" / S-401 TOP TRACK, BASE TRACK', designation_as_printed='runner/track: size and gauge not printed', derived=True, added_in='v1.0'), sub_name('L1_wall_assemblies', 'studs_track'))
            for z, nme in ((z0, 'base'), (z1, 'head')):
                ROWS.append(dict(zip(COLS, ['%s:track_%s' % (host, nme), track, 'L1_wall_assemblies', 'studs_track', 'wall_track_line', lv, A500, 'runner/track (A-500 note; S-401 TOP TRACK, BASE TRACK)', 'rule_from_printed_detail', 'measured_from_plan', host, tag, 'track size/gauge not printed', round(bb[0], 3), round(bb[1], 3), round(bb[2], 3), round(bb[3], 3), z, z, 'line only', 'yes', tid, ''])))
    nm('wall assemblies', 'sheetrock/studs on unbound walls', 'no wall-type tag bound; plain solid only (status unbound_type). A type is never bound by thickness (0 of 158 untyped walls match one type)', A500, 'a-bind', n=n_unb)
    # ======================================================= L2 box beams
    desig_by_sheet = {r['sheet']: r['designation'] for r in rd(H + 'box_beam_designations.csv') if r['kind'] == 'note4'}
    beams = [r for r in E if r['class'] == 'struct_beam']
    for r in beams:
        if r['id'] not in names: nm('beam', r['id'], 'not drawn in the v0.9b model (excluded: roof level unregistered)', r['sheet'], '', r['level']); continue
        bb = (fl(r['x_min_ft']), fl(r['y_min_ft']), fl(r['x_max_ft']), fl(r['y_max_ft'])); z0 = fl(r['z_draw_bottom_navd_ft']); z1 = fl(r['z_draw_top_navd_ft'])
        if r['size_rule'] == 'sheet_note' and r['z_bottom_status'] == 'derived_from_printed':
            dn = desig_by_sheet[r['sheet']]; assert dn == r['size_designation'].replace('(2) ', ''), (r['id'], dn, r['size_designation'])
            rc = rect_from_bbox(*bb)
            for mi in (0, 1):
                d = (-1 if mi == 0 else 1) * rc['T'] / 4; sr = sub(rc, d, rc['T'] / 2); mid = '%s:member%d' % (r['id'], mi + 1)
                emit('L2_box_beams', 'box_beam_members', 'box_beam_member', r, mid, r['sheet'] + ' (ST - 7.29.26.pdf)', 'note 4 + S-402 det. 7; depth = the 800 of the printed designation', 'rule_from_printed_detail', 'measured_from_plan (band split into the 2 printed members)', r['id'], '', '(2) ' + dn, bbox_of(corners(sr['c'], sr['u'], sr['L'], sr['T'])), z0, z1,
                     note='depth 8 in from "800" (Roy ruling); member width = half of the measured plan band (flange not used); top = level - 3/4 in panel', size_note='band %.3f x %.3f ft' % (rc['L'], rc['T']), mesh=G.box_mesh(mid, corners(sr['c'], sr['u'], sr['L'], sr['T']), z0, z1, mats['beam']))
        elif r['size_rule'] == 'label_governs':
            rc = rect_from_bbox(*bb); zt = z1
            for mi in (0, 1):
                d = (-1 if mi == 0 else 1) * rc['T'] / 4; sr = sub(rc, d, rc['T'] / 2); cs = corners(sr['c'], sr['u'], sr['L'], sr['T']); mid = '%s:member%d' % (r['id'], mi + 1)
                segs = [[(cs[i][0], cs[i][1], zt), (cs[(i + 1) % 4][0], cs[(i + 1) % 4][1], zt)] for i in range(4)]
                emit('L2_box_beams', 'label_governed_beams_depth_unknown', 'beam_member_outline', r, mid, r['sheet'] + ' (ST - 7.29.26.pdf)', 'label as printed; "SW" not defined on S-001; no beam schedule', 'rule_from_printed_detail', 'measured_from_plan', r['id'], '', r['size_designation'], bbox_of(cs), zt, zt, note='outline at the top datum only; depth NOT printed (label SW undefined) so no solid is drawn', mesh=G.line_mesh(mid, segs, mats['beamlbl']))
        else: nm('beam', r['id'], 'refused in v0.9b (conflicting/ambiguous candidate labels): designation not resolvable', r['sheet'], '', r['level'])
    # ======================================================= L3 openings
    OP = [r for r in E if r['class'] in ('door_interior', 'door_exterior', 'window')]
    A400 = 'A-400.00 (AR - 3.28.25.pdf p23)'
    wallrect = {}
    for w in walls:
        for k, pc in enumerate(pcs_all[w['id']]): wallrect['%s#%d' % (w['id'], k)] = (pc, w)
    for r in OP:
        if r['id'] not in names: continue
        bb = (fl(r['x_min_ft']), fl(r['y_min_ft']), fl(r['x_max_ft']), fl(r['y_max_ft'])); z0 = fl(r['z_draw_bottom_navd_ft']); z1 = fl(r['z_draw_top_navd_ft']); isw = r['class'] == 'window'
        if r['attach_status'] != 'attached': nm('opening', r['id'], 'not attached to a host wall (roof level not evaluated); no frame/head/fill drawn', r['sheet'], '', r['level']); continue
        if r['tag'] == 'G' and not isw: nm('opening', r['id'], 'door type G: size printed as "G.C. TO DECIDE" (A-400); no schedule height or width, so no frame/head/fill at schedule size', A400, 'door schedule G', r['level']); continue
        if not r['opening_height_ft'] or r['z_top_status'] == 'unknown': nm('opening', r['id'], 'no printed schedule height for this type tag', A400, '', r['level']); continue
        host = r['host_wall_id']; pc, w = wallrect[host]; wz1 = fl(w['z_draw_top_navd_ft'])
        cs = [np.array([bb[0], bb[1]]), np.array([bb[2], bb[1]]), np.array([bb[2], bb[3]]), np.array([bb[0], bb[3]])]
        ref = 'door schedule %s' % r['tag'] if not isw else 'window schedule %s' % r['tag']
        base = dict(sheet=A400, host=host, tag=r['tag'], desig='%s x %s in (schedule); opening_width_in=%s' % ('H %.4f ft' % fl(r['opening_height_ft']), '', r['opening_width_in']))
        note_w = 'W1 pairing of tag to schedule size unverified (inventory c2)' if (isw and r['tag'] == 'W1') else ''
        emit('L3_openings', 'frames', 'opening_frame', r, r['id'] + ':frame', A400, ref, 'rule_from_printed_detail', 'measured_from_plan (x,y); schedule height; no rough opening printed', host, r['tag'], 'opening height %.4f ft; width %s in' % (fl(r['opening_height_ft']), r['opening_width_in'] or 'from plan'), bb, z0, z1, note=note_w, mesh_from=r['id'])
        segs = [[(bb[0], (bb[1] + bb[3]) / 2, z1), (bb[2], (bb[1] + bb[3]) / 2, z1)]] if (bb[2] - bb[0]) > (bb[3] - bb[1]) else [[((bb[0] + bb[2]) / 2, bb[1], z1), ((bb[0] + bb[2]) / 2, bb[3], z1)]]
        emit('L3_openings', 'heads', 'opening_head_line', r, r['id'] + ':head', A400, ref, 'rule_from_printed_detail', 'measured_from_plan', host, r['tag'], 'head at schedule height; head member size not printed', bb, z1, z1, note=note_w, mesh=G.line_mesh(r['id'] + ':head', segs, mats['head']))
        if z1 < wz1 - 1e-4:
            emit('L3_openings', 'wall_fill_above_opening', 'wall_fill_above_opening', r, r['id'] + ':fill_above', A400 + ' + A-500 (host wall)', 'wall fill; S-401 det. 3-5 header size NOT printed', 'header_size_unknown', 'measured_from_plan', host, r['tag'], 'no header/king/trimmer drawn', bb, z1, wz1, note='plain wall fill from the opening head to the wall top; not a header', mesh=G.box_mesh(r['id'] + ':fill_above', cs, z1, wz1, mats['fill']))
        else: nm('opening', r['id'], 'opening head at or above host wall top: no fill above', A400, '', r['level'])
        if isw and z0 > fl(w['z_draw_bottom_navd_ft']) + 1e-4:
            emit('L3_openings', 'wall_fill_below_sill', 'wall_fill_below_sill', r, r['id'] + ':fill_below', A400 + ' (sill 2\'-6")', 'sill printed 2\'-6"', 'rule_from_printed_detail', 'measured_from_plan', host, r['tag'], 'sill framing size not printed', bb, fl(w['z_draw_bottom_navd_ft']), z0, note='wall solid from the level to the printed sill', mesh=G.box_mesh(r['id'] + ':fill_below', cs, fl(w['z_draw_bottom_navd_ft']), z0, mats['fill']))
    # ======================================================= L4 floor panel + joists
    ST = 'S-102..S-106.00 (ST - 7.29.26.pdf)'
    bays = [r for r in E if r['class'] == 'struct_joist_bay' and r['id'] in names]
    from shapely.geometry import box as sbox
    from shapely.ops import unary_union
    for lv in ('FLOOR_2', 'FLOOR_3', 'FLOOR_4', 'MEZZANINE'):
        bs = [r for r in bays if r['level'] == lv]
        if not bs: continue
        U = unary_union([sbox(fl(r['x_min_ft']), fl(r['y_min_ft']), fl(r['x_max_ft']), fl(r['y_max_ft'])) for r in bs])
        xs = sorted({round(c[0], 3) for g in ([U] if U.geom_type == 'Polygon' else U.geoms) for c in g.exterior.coords}); ys = sorted({round(c[1], 3) for g in ([U] if U.geom_type == 'Polygon' else U.geoms) for c in g.exterior.coords})
        cells = [(xs[i], ys[j], xs[i + 1], ys[j + 1]) for i in range(len(xs) - 1) for j in range(len(ys) - 1) if U.contains(sbox(xs[i], ys[j], xs[i + 1], ys[j + 1]).centroid)]
        # merge cells along x within a row
        rows_ = C.defaultdict(list)
        for c in cells: rows_[(c[1], c[3])].append(c)
        k = 0; lvl = {'FLOOR_2': 43.37, 'FLOOR_3': 53.37, 'FLOOR_4': 63.37, 'MEZZANINE': 73.37}[lv]
        for (y0_, y1_), cl in sorted(rows_.items()):
            cl.sort(); cur = list(cl[0])
            for c in cl[1:] + [None]:
                if c is not None and abs(c[0] - cur[2]) < 1e-6: cur[2] = c[2]; continue
                pid = 'L4:panel:%s:%s:%d' % (track, lv, k); k += 1; poly = [np.array(p) for p in ((cur[0], cur[1]), (cur[2], cur[1]), (cur[2], cur[3]), (cur[0], cur[3]))]
                emit('L4_floor_panel_joists', 'floor_panel', 'floor_panel', lv, pid, ST, 'note 3: 3/4" USG STRUCTURAL PANEL CONCRETE SUB-FLOOR (governs; A-302 and S-402 conflict -> engineer question J1)', 'rule_from_printed_detail', 'measured_from_plan (union of the drawn joist-bay outlines)', ';'.join(r['id'].split(':')[-1][-6:] for r in bs), '', '3/4" USG STRUCTURAL PANEL CONCRETE SUB-FLOOR', (cur[0], cur[1], cur[2], cur[3]), lvl - PANEL_FT, lvl,
                     note='extent = union of joist-bay outlines (floor outline not otherwise printed); panel edges inside the stair underlay not confirmed', mesh=G.box_mesh(pid, poly, lvl - PANEL_FT, lvl, mats['panel']))
                if c is not None: cur = list(c)
    flagged = {(x['track'], x['joist']) for x in rd(V9 + 'joists_stair_core_flag.csv')}
    for n_ in [n for n in G.g['nodes'] if n['name'].startswith('joist:') and n['extras'].get('track') == track and 'derived' in n['extras'] and n['extras'].get('class') == 'joist']:
        a = G.g['accessors'][G.g['meshes'][n_['mesh']]['primitives'][0]['attributes']['POSITION']]; mn, mx = a['min'], a['max']; fl_ = (track, n_['name']) in flagged
        sub_ = 'over_stair_underlay_unconfirmed' if fl_ else 'joists'
        emit('L4_floor_panel_joists', sub_, 'joist', n_['extras']['level'], 'L4:' + n_['name'], ST, 'note 2: 8J12(800S200-97) JOISTS @16" O.C.; strip assignment by continuity (joists_status.md)', 'rule_from_continuity', 'derived (spacing printed; bay edge anchor by continuity)', n_['extras']['bay'], '', '8J12(800S200-97) @16" O.C.', (mn[0], -mx[2], mx[0], -mn[2]), mn[1], mx[1],
             note='WITHHELD from takeoff' + ('; lies over the stair underlay where no floor opening is drawn (note 9: "OPENING TO HAVE JOISTS ONEITHER SIDE OF IT.") - engineer question J2' if fl_ else ''), mesh_from=n_['name'], clash='yes' if not fl_ else 'unconfirmed', extras=dict(takeoff_release='withheld'))
    # ======================================================= L5 shear walls
    S301 = 'S-301.00 (ST - 7.29.26.pdf p11)'
    gus = [x for x in rd(V9 + 'gusset_plates.csv') if x['track'] == track]
    upgrade = json.load(open(H + 'work/sw45_upgrade.json'))['upgrade']
    for r in [r for r in E if r['class'] == 'struct_shear_wall']:
        if r['id'] not in names: nm('shear wall', r['id'], 'not drawn in the v0.9b model (roof level unregistered)', S301, '', r['level']); continue
        bb = (fl(r['x_min_ft']), fl(r['y_min_ft']), fl(r['x_max_ft']), fl(r['y_max_ft'])); z0 = fl(r['z_draw_bottom_navd_ft']); z1 = fl(r['z_draw_top_navd_ft']); rc = rect_from_bbox(*bb); L, Tm = rc['L'], rc['T']
        ds = r['size_designation']; em = ds.split('END MEMBERS ')[1].split(';')[0]; ty = ds.split('TOP AND BOTTOM MEMBERS ')[1].split(';')[0]
        for e in (0, 1):
            s0 = 0 if e == 0 else L - Tm; sr = sub(rc, 0, Tm, s0, s0 + Tm); eid = '%s:endmember%d' % (r['id'], e + 1); cs = corners(sr['c'], sr['u'], sr['L'], sr['T'])
            emit('L5_shear_walls', 'end_members', 'sw_end_member', r, eid, S301, 'CFS shear wall schedule, END MEMBERS, ' + r['level'] + ' (per floor cell)', 'rule_from_printed_detail', 'measured_from_plan (SW footprint ends)', r['id'], r['tag'], em, bbox_of(cs), z0, z1, note='plan footprint = SW thickness squared (measured); member count/size as printed', mesh=G.box_mesh(eid, cs, z0, z1, mats['sw']))
        dep = 10 / 12   # "10J12" = 10 in depth by the same designation reading as 800 = 8 in (Roy ruling for box beams); recorded in size_note
        for pos_, (zb, zt_) in (('bottom', (z0, z0 + dep)), ('top', (z1 - dep, z1))):
            sr = sub(rc, 0, Tm, Tm, L - Tm); mid = '%s:%s_member' % (r['id'], pos_); cs = corners(sr['c'], sr['u'], sr['L'], sr['T'])
            emit('L5_shear_walls', 'top_bottom_members', 'sw_top_bottom_member', r, mid, S301, 'CFS shear wall schedule, TOP AND BOTTOM MEMBERS (merged cell spanning the floors)', 'schedule_merged_cell', 'measured_from_plan', r['id'], r['tag'], ty, bbox_of(cs), zb, zt_, note='merged schedule cell: one entry covers 1ST..MEZZANINE (SW 3 also ROOF); depth 10 in from the "10J12" designation', size_note='depth 10 in from designation', mesh=G.box_mesh(mid, cs, zb, zt_, mats['sw']))
        segs = []; s = Tm + 16 / 12; q = 0; fid = r['id'] + ':fieldstuds'
        while s < L - Tm - 1e-9:
            p = rc['c'] + rc['u'] * (s - L / 2); segs.append([(p[0], p[1], z0 + dep), (p[0], p[1], z1 - dep)])
            ROWS.append(dict(zip(COLS, ['%s:stud%d' % (fid, q), track, 'L5_shear_walls', 'field_studs', 'sw_field_stud_line', r['level'], S301, 'CFS shear wall schedule STUDS: 6J12 @ 16" O.C.', 'rule_from_printed_detail', 'measured_from_plan (SW footprint); spacing printed; origin at inner face of end member (not printed)', r['id'], r['tag'], '6J12 @ 16" O.C.', round(p[0], 3), round(p[1], 3), round(p[0], 3), round(p[1], 3), z0 + dep, z1 - dep, 'line only', 'yes', fid, '']))); s += 16 / 12; q += 1
        if segs:
            G.node(fid, G.line_mesh(fid, segs, mats['sw']), dict(id=fid, track=track, level=r['level'], **{'class': 'sw_field_stud_line'}, layer='L5_shear_walls', sublayer='field_studs', status='rule_from_printed_detail', source_sheet=S301, designation_as_printed='6J12 @ 16" O.C.', stud_count=q, derived=True, added_in='v1.0'), sub_name('L5_shear_walls', 'field_studs'))
    # gussets + straps
    P = C.defaultdict(list)
    for x in gus: P[(x['sw_tag'], x['storey_panel'], x['bay'])].append(x)
    def gstat(x):
        pst = x['panel_status']
        if x['clash_include'] == 'no': return 'rule_from_printed_detail', 'position borrowed from the mezzanine (roof unregistered); clash_include=no'
        if pst.startswith('identified_visually'):
            return ('measured_from_drawing', 'upgraded from identified_visually: quad-aware recount coordinates match the by-eye panel (sw45_panel_check.json)') if upgrade else ('identified_visually', '')
        if pst.startswith('drawn X'): return 'measured_from_drawing', ''
        return 'rule_from_printed_detail', 'panel from the S-301 schedule (middle storeys not drawn)'
    for x in gus:
        nid = 'L5:' + x['id']
        if x['id'] not in names: raise SystemExit('gusset node missing ' + x['id'])
        st, nt = gstat(x); xx, yy = fl(x['x_ft']), fl(x['y_ft'])
        emit('L5_shear_walls', 'gusset_plates', 'gusset_plate', x['joint_level'], nid, 'S-301 typical / S-302 detail A', '10 GA GUSSET PLATE TYPICAL; %s' % x['callout_as_printed'], st, 'nominal (face of wall not printed)', x['sw_tag'] + ' ' + x['storey_panel'], x['sw_tag'], x['callout_as_printed'], (xx, yy, xx, yy), fl(x['z0']), fl(x['z1']), note=nt, clash=x['clash_include'], mesh_from=x['id'], extras=dict(panel_status_v09b=x['panel_status']))
    ns = 0
    for (sw, sp, bay), pl in P.items():
        assert len(pl) == 4, (sw, sp, bay, len(pl))
        top = {('lo' if 'post_lo' in p['post_end'] else 'hi'): p for p in pl if p['plate_side'].startswith('below')}; bot = {('lo' if 'post_lo' in p['post_end'] else 'hi'): p for p in pl if p['plate_side'].startswith('above')}
        pt = lambda p: (fl(p['x_ft']), fl(p['y_ft']), (fl(p['z0']) + fl(p['z1'])) / 2)
        for a, b in (('lo', 'hi'), ('hi', 'lo')):
            pa, pb = bot[a], top[b]; sid = 'L5:strap:%s:%s:%s:b%s:%s_to_%s' % (track, sw.replace(' ', ''), sp.replace(' ', ''), bay, a, b); st, nt = gstat(pa); clash = 'no' if 'no' in (pa['clash_include'], pb['clash_include']) else 'yes'
            ax, ay, az = pt(pa); bx, by, bz = pt(pb); ns += 1
            emit('L5_shear_walls', 'straps', 'sw_diagonal_strap', pa['joint_level'], sid, S301, 'DIAGONALS: 12 GA 6" WIDE STRAP EACH SIDE OF PANEL (merged cell); line between gusset points', 'rule_from_printed_detail' if st != 'measured_from_drawing' else 'rule_from_printed_detail', 'endpoints = gusset plate centres (nominal); panel position basis: ' + st, sw + ' ' + sp, sw, '12 GA 6" WIDE STRAP EACH SIDE OF PANEL', (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)), min(az, bz), max(az, bz), note='drawn once per diagonal; the printed "each side of panel" means 2 straps per diagonal (face not printed); panel_status=' + st + ' ' + nt, clash=clash, mesh=G.line_mesh(sid, [[(ax, ay, az), (bx, by, bz)]], mats['strap']), extras=dict(panel_status=st, straps_per_diagonal=2))
    for r in [r for r in E if r['class'] == 'struct_hold_down']:
        if r['size_rule'] == 's302_detail_callout' and r['id'] in names:
            emit('L5_shear_walls', 'hold_downs_bound', 'hold_down_bound', r, 'L5:' + r['id'], 'S-302.00 (ST - 7.29.26.pdf p12)', 'detail ' + ('B' if r['size_designation'] == 'S/HD8S' else 'A') + ' callout', 'rule_from_printed_detail', 'measured_from_plan (post/end footprint)', r['id'], r['tag'], r['size_designation'], (fl(r['x_min_ft']), fl(r['y_min_ft']), fl(r['x_max_ft']), fl(r['y_max_ft'])), fl(r['z_draw_bottom_navd_ft']), fl(r['z_draw_top_navd_ft']), note='bound to a printed callout at this level (r7)', mesh_from=r['id'])
        else: nm('hold-down', r['id'], 'level unknown / no printed callout at this level (%s): not drawn in L5' % r['size_rule'], 'S-302.00', '', r['level'])
    G.close(); G.write(H + gfn)
    return ROWS, NM, G, dict(upgrade=upgrade, n_bound=n_bound, n_unb=n_unb, straps=ns)
if __name__ == '__main__':
    NOTMOD = []; ALL = {}
    for t in TR:
        rows, nmr, G, info = build(t); ALL[t] = rows; NOTMOD += nmr; print(t, len(rows), info)
        with open(H + 'framing_elements_%s.csv' % t, 'w', encoding='utf8', newline='') as f: w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(rows)
    # items never drawn (not printed)
    ITEMS = [('blocking', 'S-002 construction note 4 "PROVIDE SOLID BLOCKING AT ALL JOIST SUPPORTS"; S-402 "TRACK BLOCK PIECE TO MATCH WALL STUD"', 'rule text only: no count, no location, no size'),
             ('bridging', 'S-101..S-106 CFS notes 3,4; S-402 det. 1-3', 'rule text only (7\'-0" / 48" / 4\'-0" max spacings); not located on any plan, no member size'),
             ('non-shear straps', 'S-402 det. 1, 2 (double flat strap with blocking)', 'no width or gauge printed; not located'),
             ('stair framing', 'S sheets', 'not printed: 0 hits for STAIR on all 14 ST pages (stringers, landings, stair opening framing)'),
             ('rim / band joist', 'S-402 det. 4, 5 (TRACK, FLOOR JOIST); S-002 note 14', 'no size or location printed'),
             ('rough opening', 'A-400 note 1', 'not printed (manufacturer to verify)'),
             ('header sizes', 'S-401 det. 3-5; S-001', '"HEADER MEMBERS"/"HEADER TRACKS"/"HEAD TRACK (SPEC.)" with no size; no lintel schedule; wall fill above openings is drawn as header_size_unknown'),
             ('jamb / king / trimmer / cripple', 'S-401 det. 3-5', 'jamb and cripple "BY DESIGN" (shop drawing); king and trimmer not printed'),
             ('screws', 'S-301 "SCREWS SEE SCHED."; S-302 det. B "SCREWS??(SPECIFY)??"', 'schedule has no screw column; no count, no size'),
             ('W3-W6 / P4 shaft thickness', 'A-500', 'W3-W6 are poured concrete (see structural); no frame wall of these types is tag-bound in the model'),
             ('EPS insulation / stucco beyond printed 2 in', 'A-500 W1/W2', 'drawn only as the printed 2 in / 2 1/4 in block; insulation batt/blanket thickness not itemised, not drawn'),
             ('stair-core wall studs (unbound)', 'A-500 a-bind', 'no studs on unbound walls (type unknown, a type is never bound by thickness)')]
    for k, ref, why in ITEMS:
        for t in TR: NOTMOD.append(dict(track=t, kind='NOT PRINTED / rule only', element_or_item=k, level='all', count='', reason=why, source_sheet='', detail_ref=ref))
    with open(H + 'not_modelled.csv', 'w', encoding='utf8', newline='') as f: w = csv.DictWriter(f, fieldnames=['track', 'kind', 'element_or_item', 'level', 'count', 'reason', 'source_sheet', 'detail_ref']); w.writeheader(); w.writerows(NOTMOD)
    json.dump({t: dict(rows=len(r)) for t, r in ALL.items()}, open(H + 'work/build_summary.json', 'w'))
