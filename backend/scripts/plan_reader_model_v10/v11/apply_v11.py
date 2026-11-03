# apply_v11.py: v10c -> v11. Reads model_export_v10c (never written) and writes model_export_v11. Run ONCE:  cd model_export_v11 ; PYTHONUTF8=1 python apply_v11.py
# Roy's rulings applied (ruling_source = roy_pm on every row/node a ruling changed): K1 wall thickness, K2 beam ...645cdd, K3 MEZZ lowest point, K4 bare leaf tags (pitch_v4/), then the ADD list:
# ceiling plane per level, 52 sloped sanitary runs, sprinkler heads at the ceiling plane, pipe/duct tops audit. Filed and post_co are never summed. No production access, no clash wiring.
import csv, json, math, re, sys, struct, collections as C
import numpy as np
R = 'C:/Users/asddd/bv-worktrees/'; V9 = R + 'model_export_v09b/'; SRC = R + 'model_export_v10c/'; H = R + 'model_export_v11/'
rd = lambda p: list(csv.DictReader(open(p, encoding='utf8')))
fl = lambda x: float(x) if x not in ('', None) else None
src = open(H + 'build_v10.py', encoding='utf8').read()
exec(src[src.index("A500 = "):src.index('# ---------------------------------------------------------------- build one track')])   # TYPES, geometry helpers, GLB class (as in apply_v10c)
RS = 'roy_pm'
TR = {'filed': ('elements_filed.csv', 'model_filed.glb', 'framing_elements_filed.csv', '645cdd'), 'post_co': ('elements_postco.csv', 'model_postco.glb', 'framing_elements_post_co.csv', '645ec2')}
LEVELS = ['FLOOR_1', 'FLOOR_2', 'FLOOR_3', 'FLOOR_4', 'MEZZANINE']
UW = {'FLOOR_1': 42.6408, 'FLOOR_2': 52.6408, 'FLOOR_3': 62.6408, 'FLOOR_4': 72.6408, 'MEZZANINE': 82.4742}   # structure underside (levels.csv)
ELEV = {'FLOOR_1': 33.37, 'FLOOR_2': 43.37, 'FLOOR_3': 53.37, 'FLOOR_4': 63.37, 'MEZZANINE': 73.37}
PIT = {r['level']: r for r in rd(H + 'pitch_v4/pitch_lowest_v4.csv')}; PRUN = {r['id']: r for r in rd(H + 'pitch_v4/pitch_runs_v4.csv')}; PATHS = json.load(open(H + 'pitch_v4/pitch_run_paths_v4.json'))
CEIL = {lv: float(PIT[lv]['lowest_point_navd_ft']) for lv in LEVELS}


class GLB2(GLB):
    def prism_mesh(s, name, segs, mat):
        """sloped square-section prisms: seg = (x0, y0, x1, y1, width, ztop0, ztop1, height); bottom = top - height."""
        V = []; N = []; I = []
        def quad(a, b, c, d):
            a, b, c, d = [np.array(q, float) for q in (a, b, c, d)]; nr = np.cross(b - a, d - a); ln = np.linalg.norm(nr) or 1.0; nr = tuple(float(v) for v in nr / ln)
            k = len(V); V.extend([tuple(map(float, q)) for q in (a, b, c, d)]); N.extend([nr] * 4); I.extend([k, k + 1, k + 2, k, k + 2, k + 3])
        for (x0, y0, x1, y1, w, zt0, zt1, h) in segs:
            dx, dy = x1 - x0, y1 - y0; L = math.hypot(dx, dy)
            if L < 1e-6: continue
            nx, ny = -dy / L, dx / L; hw = w / 2
            def P(x, y, z): return (x, z, -y)
            a0 = (x0 - nx * hw, y0 - ny * hw); b0 = (x0 + nx * hw, y0 + ny * hw); a1 = (x1 - nx * hw, y1 - ny * hw); b1 = (x1 + nx * hw, y1 + ny * hw)
            T = [P(*a0, zt0), P(*b0, zt0), P(*b1, zt1), P(*a1, zt1)]; B = [P(*a0, zt0 - h), P(*b0, zt0 - h), P(*b1, zt1 - h), P(*a1, zt1 - h)]
            quad(*T); quad(*B[::-1])
            for i in range(4): j = (i + 1) % 4; quad(B[i], B[j], T[j], T[i])
        A = np.array(V, np.float32); s.last_bbox = (float(A[:, 0].min()), float(-A[:, 2].max()), float(A[:, 0].max()), float(-A[:, 2].min()), float(A[:, 1].min()), float(A[:, 1].max()))   # x0, y0, x1, y1, zmin, zmax (model frame)
        pa = s._acc(A, 5126, 'VEC3', 34962); na = s._acc(np.array(N, np.float32), 5126, 'VEC3', 34962, False); ia = s._acc(np.array(I, np.uint32), 5125, 'SCALAR', 34963)
        s.g['meshes'].append(dict(name=name, primitives=[dict(attributes=dict(POSITION=pa, NORMAL=na), material=mat, mode=4, indices=ia)])); return len(s.g['meshes']) - 1
    def add_to_existing(s, layer_name, node_idx):
        for n in s.g['nodes']:
            if n.get('name') == layer_name: n['children'].append(node_idx); return
        raise KeyError(layer_name)


summary = {}; nm_add = []; nm_remove = set(); SL_ROWS = []; HEAD_ROWS = []; CEIL_ROWS = []; TOPS_ROWS = []; THK = []
FAM = 'L6_ceiling_services'; SUBS = ['ceiling_plane', 'sanitary_runs_sloped', 'sprinkler_heads_at_ceiling']
for track, (efn, gfn, ffn, beam6) in TR.items():
    E = rd(V9 + efn); Eid = {e['id']: e for e in E}; G = GLB2(SRC + gfn); N = G.g['nodes']; byname = {n['name']: n for n in N}; F = rd(SRC + ffn); COLS = list(F[0].keys()); summary[track] = {}
    newrow = lambda **kw: {c: kw.get(c, '') for c in COLS}
    for k in ('thickness_basis',):
        if k not in COLS: COLS.append(k)
    for r in F: r.setdefault('thickness_basis', '')
    # ================================================================== K1 walls: printed assembly thickness centred on the drawn centreline (tag-bound); drawn thickness labelled for unbound
    host_tot = {}
    for r in F:
        if r['class'].startswith('wall_layer'):
            m = re.search(r'sum of drawn layers ([\d.]+) in', r['size_note']); host_tot[r['host_or_parent_id']] = float(m.group(1))
    cnt = C.Counter(); K1_BASIS = {}
    for r in F:
        if r['layer'] != 'L1_wall_assemblies': continue
        n = byname[r['glb_node']]; ex = n['extras']; tag = r['type_tag']
        if r['sublayer'] == 'unbound_walls':
            tb = 'drawn thickness, rounded-up upper bound'; cnt['unbound_walls', 'status unchanged unbound_type'] += 1
        elif tag == 'P4':
            tb = 'drawn thickness (P4 printed assembly varies 8-12 in: no single printed value, so the K1 rule cannot be applied; cavity = measured, kept as in v10)'; cnt['P4', 'drawn'] += 1
        else:
            tot = host_tot[r['host_or_parent_id']]
            if tag == 'P5': tb = 'printed assembly thickness 4.75 in (sum of the printed parts, Roy ruling) centred on the drawn centreline; printed total 3 3/4 in stays a logged plan discrepancy (plan_discrepancies D01)'
            else: tb = 'printed assembly thickness %.4g in centred on the drawn centreline' % tot
            if tag == 'P5': assert abs(tot - 4.75) < 1e-9, (r['element_id'], tot)
            else: assert abs(tot - TYPES[tag]['printed_total']) < 1e-9, (r['element_id'], tag, tot, TYPES[tag]['printed_total'])
            if r['class'].startswith('wall_layer'): r['status'] = 'printed_assembly'; ex['status'] = 'printed_assembly'; cnt[tag, 'layer rows -> printed_assembly'] += 1
        r['thickness_basis'] = tb; r['ruling_source'] = RS
        r['ruling_note'] = (r['ruling_note'] + ' | ' if r['ruling_note'] else '') + 'v11 K1: ' + tb
        ex['thickness_basis'] = tb; ex['ruling_source'] = RS; ex['ruling_note'] = r['ruling_note']
        K1_BASIS[(tag, tb[:30])] = tb
    # original (v09b) wall nodes: record the printed assembly thickness beside the measured one
    nwo = 0
    for e in E:
        if e['class'] == 'wall' and e['tag'] in TYPES and e['id'] in byname and e['tag'] != 'P4':
            tot = 4.75 if e['tag'] == 'P5' else TYPES[e['tag']]['printed_total']
            byname[e['id']]['extras'].update(printed_assembly_in=tot, thickness_basis_v11='the v09b solid keeps the measured plan thickness; the L1 layers carry the printed assembly thickness %.4g in centred on the drawn centreline' % tot, ruling_source=RS); nwo += 1
    summary[track]['K1'] = dict(layer_rows_printed_assembly=sum(v for (t, k), v in cnt.items() if 'layer rows' in k), P5_layer_rows=cnt['P5', 'layer rows -> printed_assembly'], P4_rows_drawn_thickness=cnt['P4', 'drawn'], unbound_pieces=cnt['unbound_walls', 'status unchanged unbound_type'], original_wall_nodes_annotated=nwo)
    # ================================================================== K2 beam ...645cdd: whole-row outline in the nSWm class, BOTH labels, NO split
    bid = [e for e in E if e['class'] == 'struct_beam' and e['id'].endswith(beam6)]; assert len(bid) == 1; b = bid[0]; assert b['sheet'] == 'S-102.00' and b['level'] == 'FLOOR_2'
    bb = (fl(b['x_min_ft']), fl(b['y_min_ft']), fl(b['x_max_ft']), fl(b['y_max_ft'])); zt = [fl(r['z_top_navd_ft']) for r in F if r['sublayer'] == 'label_governed_beams_depth_unknown' and r['level'] == 'FLOOR_2'][0]; assert abs(zt - (43.37 - 0.0625)) < 1e-6
    LBL = '(2) 8SW14 | (2) 16SW10'; rc = rect_from_bbox(*bb); matb = G.material('L2 label governed (depth unknown) outline', (0.9, 0.7, 0.1, 1))
    for mi in (0, 1):
        d = (-1 if mi == 0 else 1) * rc['T'] / 4; sr = sub(rc, d, rc['T'] / 2); cs = corners(sr['c'], sr['u'], sr['L'], sr['T']); mid = '%s:member%d' % (b['id'], mi + 1)
        segs = [[(cs[i][0], cs[i][1], zt), (cs[(i + 1) % 4][0], cs[(i + 1) % 4][1], zt)] for i in range(4)]
        ex = dict(id=mid, track=track, level='FLOOR_2', **{'class': 'beam_member_outline'}, layer='L2_box_beams', sublayer='label_governed_beams_depth_unknown', status='rule_from_printed_detail', position_status='measured_from_plan', source_sheet='S-102.00 (ST - 7.29.26.pdf)',
                  detail_ref='whole-row outline, both printed labels listed, NO split (Roy K2); "SW" not defined on S-001; no beam schedule', designation_as_printed=LBL, derived=True, added_in='v11', clash_include='yes', ruling_source=RS,
                  ruling_note='K2: one 32.44 ft row (x 36.585-69.028 ft, grid C) carries two printed labels "(2) 8SW14" (left) and "(2) 16SW10" (right) with SW 1 between; kept as ONE whole-row outline in the nSWm class, both labels listed, not split at SW 1; engineer question J3', size_note='whole row %.3f x %.3f ft' % (rc['L'], rc['T']))
        idx = len(N); N.append(dict(name=mid, mesh=G.line_mesh(mid, segs, matb), extras=ex)); G.add_to_existing('LAYER L2_box_beams | label_governed_beams_depth_unknown', idx)
        x0_, y0_, x1_, y1_ = bbox_of(cs)
        F.append(newrow(element_id=mid, track=track, layer='L2_box_beams', sublayer='label_governed_beams_depth_unknown', **{'class': 'beam_member_outline'}, level='FLOOR_2', source_sheet='S-102.00 (ST - 7.29.26.pdf)', detail_ref=ex['detail_ref'], status='rule_from_printed_detail', position_status='measured_from_plan',
                        host_or_parent_id=b['id'], designation_as_printed=LBL, x_min_ft=round(x0_, 3), y_min_ft=round(y0_, 3), x_max_ft=round(x1_, 3), y_max_ft=round(y1_, 3), z_bottom_navd_ft=round(zt, 4), z_top_navd_ft=round(zt, 4), size_note=ex['size_note'], clash_include='yes', glb_node=mid,
                        notes='outline at the top datum only; depth NOT printed (label SW undefined) so no solid is drawn', ruling_source=RS, ruling_note=ex['ruling_note']))
    nm_remove.add((track, 'beam', b['id']))
    summary[track]['K2'] = dict(outline_members_added=2, labels=LBL, split='none', label_governed_outlines_now=sum(1 for r in F if r['sublayer'] == 'label_governed_beams_depth_unknown'))
    # ================================================================== K3/K4 + ADD list in the new family L6_ceiling_services
    for sn in SUBS: G.open_layer(FAM, FAM + ' | ' + sn)
    mat_c = G.material('L6 ceiling plane', (0.45, 0.7, 0.95, 0.30)); mat_r = G.material('L6 sanitary run (sloped)', (0.55, 0.33, 0.12, 1)); mat_h = G.material('L6 sprinkler head at ceiling plane', (0.9, 0.15, 0.15, 1))
    def emit(sub, cls, nid, level, sheet, ref, status, posst, host, desig, bbx, z0, z1, mesh, extras, note='', size_note='', clash='no', ruling_note='', qty=''):
        ex = dict(id=nid, track=track, level=level, **{'class': cls}, layer=FAM, sublayer=sub, status=status, position_status=posst, source_sheet=sheet, detail_ref=ref, designation_as_printed=desig, derived=True, added_in='v11', clash_include=clash, ruling_source=RS, ruling_note=ruling_note)
        if qty: ex['quantity_label'] = qty
        ex.update(extras); G.node(nid, mesh, ex, FAM + ' | ' + sub)
        F.append(newrow(element_id=nid, track=track, layer=FAM, sublayer=sub, **{'class': cls}, level=level, source_sheet=sheet, detail_ref=ref, status=status, position_status=posst, host_or_parent_id=host, designation_as_printed=desig,
                        x_min_ft=round(bbx[0], 3), y_min_ft=round(bbx[1], 3), x_max_ft=round(bbx[2], 3), y_max_ft=round(bbx[3], 3), z_bottom_navd_ft=round(z0, 4), z_top_navd_ft=round(z1, 4), size_note=size_note, clash_include=clash, glb_node=nid, notes=note, ruling_source=RS, ruling_note=ruling_note, quantity_label=qty))
    # ---- ceiling plane per level = the single lowest point of the level's pitch (pitch_v4)
    wl = {lv: [e for e in E if e['level'] == lv and e['class'] in ('wall', 'struct_bearing_wall', 'struct_shear_wall') and e['x_min_ft']] for lv in LEVELS}
    for lv in LEVELS:
        p = PIT[lv]; xs = [fl(e['x_min_ft']) for e in wl[lv]] + [fl(e['x_max_ft']) for e in wl[lv]]; ys = [fl(e['y_min_ft']) for e in wl[lv]] + [fl(e['y_max_ft']) for e in wl[lv]]
        bbx = (min(xs), min(ys), max(xs), max(ys)); cz = CEIL[lv]; nid = 'ceiling_plane:%s:%s' % (track, lv); poly = [(bbx[0], bbx[1]), (bbx[2], bbx[1]), (bbx[2], bbx[3]), (bbx[0], bbx[3])]
        alt = p['printed_tier_alt_navd_ft']
        note = 'ceiling plane = the single lowest point of the level (pitch minimum, pitch_v4/pitch_lowest_v4.csv); set_status %s: %s' % (p['set_status'], p['set_status_reason'])
        if alt: note += '; printed-tier alternative %s recorded beside it' % alt
        emit('ceiling_plane', 'ceiling_plane', nid, lv, 'P-201..P-205 (PL - 6.29.26.pdf p9-13) + P-001.00 note A + P-301.00', 'pitch_v4: lowest point of the level = minimum over the stable slope plateau; footprint = bounding box of the level wall rows (extent not printed)', 'derived_from_printed', 'footprint: bbox of drawn walls; z: derived', '', 'ceiling plane at the level lowest pipe point',
             bbx, cz - 0.02, cz, G.box_mesh(nid, poly, cz - 0.02, cz, mat_c), dict(ceiling_navd_ft=cz, ceiling_aff_in=round((cz - ELEV[lv]) * 12, 1), set_status=p['set_status'], printed_tier_alt_navd_ft=alt, controlling_run=p['controlling_run_for_minimum'], controlling_tag_bare=p['controlling_tag_bare'], controlling_tag_status=p['controlling_tag_status'],
                                                                                                                                                   headline_controlling_run=p['controlling_run_headline_scenario'], structure_underside_navd_ft=UW[lv]), note=note, size_note='thin slab 0.02 ft: plane drawn as a thin box', ruling_note='K3/K4 + ADD: ceiling plane per level = the single lowest point (pitch minimum)')
        CEIL_ROWS.append(dict(track=track, level=lv, ceiling_navd_ft=cz, ceiling_aff_in=round((cz - ELEV[lv]) * 12, 1), structure_underside_navd_ft=UW[lv], printed_tier_alt_navd_ft=alt, set_status=p['set_status'], controlling_run=p['controlling_run_for_minimum'], controlling_tag_bare=p['controlling_tag_bare'], controlling_tag_status=p['controlling_tag_status'],
                              headline_controlling_run=p['controlling_run_headline_scenario'], headline_tag_bare=p['headline_controlling_tag_bare'], status='derived_from_printed', ruling_source=RS))
    # ---- 52 sloped sanitary runs (top at structure underside at the high end; slope per P-001 note A tier)
    nr = 0; SLOPE_TRUNK = 0.125
    for rid, P in PATHS.items():
        lv = P['level']; run = PRUN[rid]; uw = UW[lv]; poly = P['polyline_xy_ft']; cum = [0.0]
        for k in range(len(poly) - 1): cum.append(cum[-1] + math.hypot(poly[k + 1][0] - poly[k][0], poly[k + 1][1] - poly[k][1]))
        scale = P['stroke_len_ft'] / cum[-1]; bl = P['branch_len_ft']; sz = P['drop_size_in']; sb = 0.125 if sz >= 3 else 0.25
        drop_in = lambda s: (sb * s if s <= bl else sb * bl + SLOPE_TRUNK * (s - bl))
        verts = []   # (x, y, s)
        for k in range(len(poly) - 1):
            s0, s1 = cum[k] * scale, cum[k + 1] * scale
            if not verts: verts.append((poly[k][0], poly[k][1], s0))
            if s0 < bl < s1:
                f = (bl - s0) / (s1 - s0); verts.append((poly[k][0] + f * (poly[k + 1][0] - poly[k][0]), poly[k][1] + f * (poly[k + 1][1] - poly[k][1]), bl))
            verts.append((poly[k + 1][0], poly[k + 1][1], s1))
        segs = []
        for (xa, ya, sa), (xb, yb, sb_) in zip(verts, verts[1:]):
            h = (sz if (sa + sb_) / 2 <= bl else 4.0) / 12
            if sb_ >= verts[-1][2] - 1e-9: h = 4.0 / 12   # the segment that reaches the stack is drawn at the nominal 4 in of the pitch convention (P-301), so the lowest point equals pitch_v4
            segs.append((xa, ya, xb, yb, h, uw - drop_in(sa) / 12, uw - drop_in(sb_) / 12, h))
        z_top_stack = uw - drop_in(verts[-1][2]) / 12; z_low = z_top_stack - 4.0 / 12; z_low_bracket = float(run['lowest_pt_navd_ft_trunk_bracket'])
        assert abs(z_low - float(run['lowest_pt_navd_ft'])) < 0.004, (rid, z_low, run['lowest_pt_navd_ft']); assert z_low >= CEIL[lv] - 1e-6, (rid, z_low, CEIL[lv])
        nid = 'sanitary_run:%s:%s' % (track, rid); mesh_ = G.prism_mesh(nid, segs, mat_r); lb = G.last_bbox
        note = ('branch %d in at %s in/ft for %.2f ft, trunk 4 in at 1/8 in/ft for %.2f ft (the segment reaching the stack is drawn at nominal 4 in; P-301 prints 4 in on the stack-adjacent horizontal; bracket to 1/4: lowest point %.4f); top of pipe at the structure underside %.4f at the high end (leaf) = convention_ceiling_drop, NOT printed; '
                'top at the stack end %.4f; bottom at the stack end (nominal 4 in) = lowest point %.4f; grades printed "at least" so each elevation is an upper bound; plan path = stroke polyline (chords for arcs), vertical profile scaled to the stroke length %.2f ft (polyline %.2f ft)') % (
                sz, '1/8' if sb == 0.125 else '1/4', bl, P['trunk_len_ft'], z_low_bracket, uw, z_top_stack, z_low, P['stroke_len_ft'], cum[-1])
        emit('sanitary_runs_sloped', 'sanitary_run_sloped', nid, lv, '%s (PL - 6.29.26.pdf; run strokes) + P-001.00 note A + %s' % (P['sheet'], run['source_sheet'].split(' + ')[-1]), 'slope tier: P-001.00 note A (3 in and larger at least 1/8 in/ft; 2 in and smaller at least 1/4 in/ft); drop size %s; high-end top at structure underside (convention)' % run['size_basis'],
             'derived_from_printed', 'measured_from_plan_strokes (registered; stroke polyline)', '', '%s: %s' % (rid, run['bound_type_v4']), (lb[0], lb[1], lb[2], lb[3]), lb[4], lb[5], mesh_,
             dict(run_id=rid, stack=P['stack'], fixture=P['fixture'], drop_size_in=sz, branch_slope_in_per_ft=sb, trunk_slope_in_per_ft=SLOPE_TRUNK, branch_len_ft=bl, trunk_len_ft=P['trunk_len_ft'], z_high_end_top_navd_ft=uw, z_high_end_status='convention_ceiling_drop', slope_status='derived_from_printed', z_top_stack_end_navd_ft=round(z_top_stack, 4), lowest_point_navd_ft=round(z_low, 4),
                  lowest_point_trunk_bracket_navd_ft=z_low_bracket, tag_status_v4=run['tag_status_v4'], bare_tag=run['bare_tag'], bind_result_v4=run['bind_result_v4']), note=note, size_note='top-of-pipe high end %.4f -> stack end %.4f' % (uw, z_top_stack), clash='no',
             ruling_note='ADD: 52 sloped sanitary runs; top at structure underside at the high end, slope per tier (1/8 in/ft for 3 in and larger, 1/4 in/ft for 2 in and smaller, P-001 note A)')
        SL_ROWS.append(dict(track=track, run_id=rid, level=lv, stack=P['stack'], fixture=P['fixture'], tag_status=run['tag_status_v4'], bare_tag=run['bare_tag'], drop_size_in=sz, branch_slope_in_per_ft=sb, branch_len_ft=bl, trunk_slope_in_per_ft=SLOPE_TRUNK, trunk_len_ft=P['trunk_len_ft'], stroke_len_ft=P['stroke_len_ft'], polyline_len_ft=round(cum[-1], 3),
                            z_high_end_top_navd_ft=uw, z_high_end_status='convention_ceiling_drop', z_top_stack_end_navd_ft=round(z_top_stack, 4), lowest_point_navd_ft=round(z_low, 4), lowest_point_trunk_bracket_navd_ft=z_low_bracket, ceiling_plane_navd_ft=CEIL[lv], status='derived_from_printed', ruling_source=RS)); nr += 1
    summary[track]['sloped_runs'] = nr
    # ---- sprinkler heads at the ceiling plane (filed track only: the post_co model has no sprinkler rows)
    heads = [e for e in E if e['class'] == 'sprinkler_head']; nh = 0; hroof = 0
    for e in heads:
        if e['level'] not in CEIL: hroof += 1; continue
        cz = CEIL[e['level']]; x = fl(e['x_min_ft']); y = fl(e['y_min_ft']); nid = 'sp_head_at_ceiling:%s' % e['id']; poly = [(x - .25, y - .25), (x + .25, y - .25), (x + .25, y + .25), (x - .25, y + .25)]
        emit('sprinkler_heads_at_ceiling', 'sprinkler_head_at_ceiling', nid, e['level'], e['sheet'] + ' (SP - 6.24.26.pdf)', 'head position from the sprinkler plan; z = ceiling plane of the level (convention, not printed)', 'convention_ceiling_drop', e['position_status'], e['id'], e['subclass'], (x - .25, y - .25, x + .25, y + .25), cz - 0.1, cz,
             G.box_mesh(nid, poly, cz - 0.1, cz, mat_h), dict(placed_from=e['id'], ceiling_navd_ft=cz, ceiling_set_status=PIT[e['level']]['set_status'], tag=e['tag'], head_marker_note='0.5 ft marker box, not to scale (as the v09b head)'), note='a placement copy of the original head %s at the ceiling plane, NOT a second head; the original node stays at its v09b z' % e['id'],
             size_note='marker 0.5 x 0.5 ft x 0.1 ft, top at the ceiling plane', clash='no', ruling_note='ADD: sprinkler heads at the ceiling plane (convention_ceiling_drop)', qty='NOT_A_COUNT: placement copy of the original head row (112 original head rows are the count basis)')
        HEAD_ROWS.append(dict(track=track, head_id=e['id'], level=e['level'], tag=e['tag'], subclass=e['subclass'], x_ft=x, y_ft=y, ceiling_navd_ft=cz, ceiling_set_status=PIT[e['level']]['set_status'], status='convention_ceiling_drop', ruling_source=RS)); nh += 1
    summary[track]['heads_at_ceiling'] = nh; summary[track]['heads_roof_not_placed'] = hroof
    if hroof: nm_add.append(dict(track=track, kind='sprinkler head', element_or_item='sprinkler heads on ROOF (original rows kept)', level='ROOF', count=hroof, reason='ROOF unregistered (ruling 140): no ceiling plane for ROOF (P-206 draws no sanitary run, no structure underside); no head copy placed', source_sheet='SP - 6.24.26.pdf', detail_ref='original sp_head ROOF rows'))
    if not heads: nm_add.append(dict(track=track, kind='sprinkler head', element_or_item='sprinkler heads at the ceiling plane', level='', count=0, reason='the post_co model (v09b elements_postco.csv) has 0 sprinkler_head and 0 sprinkler_pipe rows; nothing to place (not invented)', source_sheet='', detail_ref=''))
    # ---- tops at the structure underside: classes that already exist (audit only; nothing added)
    cl = C.Counter(); bad = 0
    for e in E:
        if e['class'] not in ('sprinkler_pipe', 'mech_exhaust_fan'): continue
        ok = e['z_top_status'] == 'convention_ceiling_drop'
        if ok:
            u = UW[e['level']]; d = fl(e['z_top_navd_ft']) - u; good = abs(d) < 0.0006; bad += (not good)
        else: u = ''; d = ''; good = False
        TOPS_ROWS.append(dict(track=track, id=e['id'], class_=e['class'], level=e['level'], z_top_status=e['z_top_status'], z_top_navd_ft=e['z_top_navd_ft'], structure_underside_navd_ft=u, delta_ft=round(d, 4) if d != '' else '', verdict='top at structure underside, convention_ceiling_drop (already in v09b)' if good else ('NOT APPLIED: level not registered (%s)' % e['level'] if not ok else 'MISMATCH'), ruling_source=''))
        cl[(e['class'], 'at_underside' if good else 'not_applied')] += 1
    summary[track]['tops_audit'] = {'%s|%s' % k: v for k, v in cl.items()}; summary[track]['tops_mismatch'] = bad
    nm_add.append(dict(track=track, kind='duct runs', element_or_item='duct runs', level='', count=0, reason='no duct class exists in the model (mechanical classes are equipment: exhaust fan, PTAC, unit heater, fan); no duct run was created (Roy: no new duct runs)', source_sheet='', detail_ref=''))
    # ---- close layers, fix added_in on the new LAYER groups
    G.close()
    for n in G.g['nodes']:
        if n.get('name', '').startswith('LAYER ' + FAM): n['extras']['added_in'] = 'v11'
    G.write(H + gfn)
    cols = list(COLS)
    with open(H + ffn, 'w', newline='', encoding='utf8') as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(F)
    summary[track]['rows_total'] = len(F); summary[track]['status_counts'] = dict(C.Counter(r['status'] for r in F))
Fa = rd(H + 'framing_elements_filed.csv') + rd(H + 'framing_elements_post_co.csv')
with open(H + 'framing_elements.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.DictWriter(f, fieldnames=list(Fa[0].keys())); w.writeheader(); w.writerows(Fa)
# ---- not_modelled: drop the refused beam rows (now modelled), add v11 rows
NM = [r for r in rd(SRC + 'not_modelled.csv') if (r['track'], r['kind'], r['element_or_item']) not in nm_remove]
rf = rd(R + 'pitchmap/refused.csv'); rfc = C.Counter(r['level'] for r in rf)
for track in TR: nm_add.append(dict(track=track, kind='sloped sanitary run', element_or_item='sanitary/storm stroke networks that are not fixture runs, storm horizontals, vent, below-slab, roof, bulkhead (pitchmap/refused.csv: %d rows)' % len(rf), level='', count=len(rf), reason='no slope drawn: not a mapped fixture run, or storm size not printed (tier cannot be chosen), vent not pitched by P-001 note A, below-slab has no elevation, roof/bulkhead unregistered; 52 fixture runs per track are drawn', source_sheet='P-201..P-207', detail_ref='pitchmap/refused.csv'))
NM += nm_add
with open(H + 'not_modelled.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.DictWriter(f, fieldnames=['track', 'kind', 'element_or_item', 'level', 'count', 'reason', 'source_sheet', 'detail_ref']); w.writeheader(); w.writerows(NM)
def wr(fn, rows):
    with open(H + fn, 'w', newline='', encoding='utf8') as f: w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
wr('ceiling_plane_v11.csv', CEIL_ROWS); wr('sanitary_runs_sloped_v11.csv', SL_ROWS); wr('sprinkler_heads_at_ceiling_v11.csv', HEAD_ROWS); wr('tops_at_structure_underside_v11.csv', TOPS_ROWS)
# ---- K1 table by type (both tracks): printed total, sum of printed parts, drawn
rows = []
for t, T in TYPES.items():
    tot = sum(l[1] for l in T['layers']) if T['layers'] else None
    rows.append(dict(type=t, printed_total_in=T['printed_total'], sum_of_printed_parts_in=tot if tot is not None else 'varies (cavity measured)', thickness_used_in=(4.75 if t == 'P5' else (T['printed_total'] if t != 'P4' else 'drawn')),
                     status='printed_assembly' if t != 'P4' else 'rule_from_printed_detail (P4: printed assembly varies, K1 not applicable)', ruling_source=RS, note='P5: Roy ruling 4.75 (parts); printed 3 3/4 stays plan discrepancy D01' if t == 'P5' else ''))
wr('wall_thickness_basis_v11.csv', rows)
# ---- engineer questions
EQ = rd(SRC + 'engineer_questions_v10.csv')
EQ.append(dict(track='both', question_id='J3', sheet='S-102.00 (ST - 7.29.26.pdf p6) and S-102..S-106 beam labels', level='FLOOR_2 (and every beam labelled nSWm)', kind='beam_label_SW_undefined', printed_text='"(2) 8SW14" and "(2) 16SW10" on one 32.44 ft beam row (grid C, x 36.585-69.028 ft); other labelled beams print "(2) 10SW10"',
               question='What does "SW" mean in 8SW14 / 16SW10 (and 10SW10)? It is not defined on S-001 and there is no beam schedule. Is the member a stud-wall header, a steel-wire/section code or something else, and what are the depth, gauge and flange? Also: is the C-grid row one beam or two spans, and where does the 8SW14 end and the 16SW10 begin?',
               status='OPEN', roy_answer='', ruling_source=''))
wr('engineer_questions_v11.csv', EQ)
json.dump(summary, open(H + 'apply_v11_summary.json', 'w'), indent=1); print(json.dumps(summary, indent=1))
