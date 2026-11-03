# apply_v10b.py: v10 -> v10b (v10.1). Applies Roy's PM rulings (2026-11-03) + coordinator corrections to a COPY of v10 (this folder). v10 and v09b are never written.
# Run once, in a fresh copy of v10:  python apply_v10b.py   (idempotence is not claimed: it patches the files in this folder in place)
# Every row/node touched by a PM ruling carries ruling_source = roy_pm (NOT plan-derived).
import csv, json, struct, math, re, sys, collections as C
import numpy as np
R = 'C:/Users/asddd/bv-worktrees/'; V9 = R + 'model_export_v09b/'; H = R + 'model_export_v10b/'
rd = lambda p: list(csv.DictReader(open(p, encoding='utf8')))
fl = lambda x: float(x) if x not in ('', None) else None
src = open(R + 'model_export_v10/build_v10.py', encoding='utf8').read()
cls = src[src.index('class GLB:'):src.index('# ---------------------------------------------------------------- build one track')]
exec(cls)   # GLB helper (same loader/writer/box_mesh as build_v10.py)
RS = 'roy_pm'
TR = {'filed': ('elements_filed.csv', 'model_filed.glb', 'framing_elements_filed.csv'), 'post_co': ('elements_postco.csv', 'model_postco.glb', 'framing_elements_post_co.csv')}
NEWCOLS = ['ruling_source', 'ruling_note', 'size_pairing', 'quantity_label', 'count_release']
JOIST_LABEL = 'at printed 16 in spacing, minimum'
JOIST_NOTE = 'S-002.00 (ST - 7.29.26.pdf p3): "JOIST SPACING SHOWN ON PLAN IS MAXIMUM PERMISSIBLE. UNDER NO CIRCUMSTANCES SHALL THIS SPACING BE EXCEEDED." So 16 in o.c. is a maximum spacing and the count is a minimum.'
FLOOR_NOTE = 'PM ruling 2026-11-03: L4 floor panel = S-102..S-106 note 3 (3/4" USG structural panel). A-302 "METAL DECK WITH CONCRETE" = stair landing detail only (thickness used only if printed); S-402 plywood applied to no element. J1 resolved.'
STUD_NOTE = 'layout_assumed: stud/track layout origin (piece start) and spacing application are not printed; one row is one drawn layout line, NOT a stud count; count_release WITHHELD.'
P5_NOTE = 'PM ruling: P5 layers drawn as printed parts (4 3/4"); printed total 3 3/4" logged as a plan-internal discrepancy (plan_discrepancies.csv D01).'
STAIR_APT = 'interior stair, field-measured'
log = []
g_ids_removed = 0
ov = []   # v09b-row overrides log

def patch_extras(n, **kw):
    n.setdefault('extras', {}).update(kw)

summary = {}
for track, (efn, gfn, ffn) in TR.items():
    E = rd(V9 + efn); EB = {r['id']: r for r in E}
    G = GLB(H + gfn); N = G.g['nodes']; names = G.names
    F = rd(H + ffn)
    for r in F:
        for c in NEWCOLS: r[c] = ''
    win = {r['id'] for r in E if r['class'] == 'window'}
    nrow = collections = C.Counter()
    # ---------- row-level rules on framing rows
    for r in F:
        cl = r['class']
        if cl in ('wall_stud_line', 'wall_track_line', 'sw_field_stud_line'):
            r['status'] = 'layout_assumed'; r['ruling_source'] = RS; r['ruling_note'] = STUD_NOTE; r['count_release'] = 'WITHHELD'; nrow['studs_layout_assumed'] += 1
        if r['type_tag'] == 'P5' and cl.startswith('wall_layer'):
            r['ruling_source'] = RS; r['ruling_note'] = P5_NOTE; nrow['p5_layers'] += 1
        if cl == 'floor_panel':
            r['detail_ref'] = r['detail_ref'].replace('(governs; A-302 and S-402 conflict -> engineer question J1)', '(governs per PM ruling 2026-11-03; J1 resolved)')
            r['ruling_source'] = RS; r['ruling_note'] = FLOOR_NOTE; nrow['floor_panel'] += 1
        if cl == 'joist':
            r['quantity_label'] = JOIST_LABEL; r['ruling_source'] = RS; r['ruling_note'] = JOIST_NOTE; r['count_release'] = 'WITHHELD'; nrow['joists'] += 1
        if cl in ('opening_frame', 'opening_head_line', 'wall_fill_above_opening', 'wall_fill_below_sill'):
            oid = re.split(r':(frame|head|fill)', r['element_id'])[0]
            if oid in win:
                r['size_pairing'] = 'size_pairing_unverified'; r['count_release'] = 'WITHHELD'; r['ruling_note'] = (r['ruling_note'] + ' ' if r['ruling_note'] else '') + 'window tag-to-size pairing not provable from the plan (see w1_pairing_trace.csv); size not fed to takeoff inputs'; nrow['window_rows'] += 1
            else: r['size_pairing'] = 'n/a (door)'
    # ---------- SW 4&5 straps/plates: kept measured_from_drawing only on the stated conditions (see SW45_decision.md); rows untouched
    # ---------- door G marker layer (visible), placed G doors only
    gd = [r for r in E if r['class'].startswith('door') and r['tag'] == 'G']
    mat = G.material('door_G_undefined marker', (1.0, 0.0, 0.8, 0.85))
    G.open_layer('door_G_undefined', 'door_G_undefined | marker')
    add_rows = []; unplaced = []
    for r in gd:
        if r['position_status'] == 'unplaced' or r['id'] not in names: unplaced.append(r); continue
        x0, y0, x1, y1 = [fl(r[k]) for k in ('x_min_ft', 'y_min_ft', 'x_max_ft', 'y_max_ft')]
        z0 = fl(r['z_draw_bottom_navd_ft']); z1 = fl(r['z_draw_top_navd_ft'])
        nid = r['id'] + ':door_G_marker'
        m = G.box_mesh(nid, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1, mat)
        G.node(nid, m, dict(id=nid, track=track, level=r['level'], **{'class': 'door_G_marker'}, layer='door_G_undefined', sublayer='marker', status='door_G_undefined', position_status=r['position_status'],
                            source_sheet='A-400.00 (AR - 3.28.25.pdf p23)', detail_ref='door schedule type G: SIZE G.C. TO DECIDE', clash_include='no', derived=True, added_in='v1.1', ruling_source='not_a_ruling_marker_only',
                            note='marker only: door G size is printed as "G.C. TO DECIDE"; no frame, head or fill is drawn. Box = the v09b door footprint x v09b opening height (6\'-8", a v09b value, not printed for G).'),
               'door_G_undefined | marker')
        add_rows.append(dict(element_id=nid, track=track, layer='door_G_undefined', sublayer='marker', **{'class': 'door_G_marker'}, level=r['level'], source_sheet='A-400.00 (AR - 3.28.25.pdf p23)', detail_ref='door schedule type G: SIZE "G.C. TO DECIDE"',
                             status='door_G_undefined', position_status=r['position_status'], host_or_parent_id=r['id'], type_tag='G', designation_as_printed='G.C. TO DECIDE', x_min_ft=x0, y_min_ft=y0, x_max_ft=x1, y_max_ft=y1, z_bottom_navd_ft=z0, z_top_navd_ft=z1,
                             size_note='visible marker, not a door frame/head/fill', clash_include='no', glb_node=nid, notes='marker layer door_G_undefined (v10.1)', ruling_source='', ruling_note='', size_pairing='n/a', quantity_label='', count_release=''))
    F.extend(add_rows); summary[track + '_door_G_markers'] = len(add_rows); summary[track + '_door_G_unplaced'] = [u['id'] for u in unplaced]
    # ---------- node-level patches for every framing row that now carries a change
    byname = {n['name']: n for n in N if 'mesh' in n}
    for r in F:
        n = byname.get(r['glb_node'])
        if not n: continue
        ex = n['extras']; ex.pop('stud_count', None)
        if r['status'] == 'layout_assumed': ex['status'] = 'layout_assumed'
        for c in NEWCOLS:
            if r[c]: ex[c] = r[c]
    # ---------- v09b original nodes (rows live in v09b CSVs; v09b not edited, v10b GLB extras patched, override log written)
    for n in N:
        ex = n.get('extras', {})
        if not ex or ex.get('added_in'): continue
        c = ex.get('class'); i = ex.get('id', n['name'])
        if ex.get('kind') in ('apartment stair', 'core stair (runs A and B in one core)') or str(i).startswith('stair:'):
            ex['a600_answer'] = 'A-600 is listed on T-001, not in the set, removed (design changed). No stair data taken from A-600.'; ex['ruling_source'] = RS
            if 'apartment' in str(ex.get('kind')):
                ex.update(status=STAIR_APT, geometry_status=STAIR_APT, basis_label=STAIR_APT, structure_count_include='no', clash_include='no', treads_drawn='none', tread_in='')
                ex['ruling_note'] = 'PM ruling: apartment stairs 4A-4D = envelope, interior stair, field-measured; excluded from structure counts and clash; no treads; I1 closed.'
                ov.append(dict(track=track, id=i, what='apartment stair 4A-4D', change='status=interior stair, field-measured; structure_count_include=no; clash_include=no; no treads', ruling_source=RS))
            else:
                ex['basis_label'] = 'typical detail (A-302 detail 11): ' + str(ex.get('basis_label', ''))
                ex['ruling_note'] = 'PM ruling: core stair basis stays A-302 detail 11, labelled typical detail; A-600 gives no data.'
                if ex.get('to_level') == 'ROOF':
                    ex['roof_stair_note'] = 'PM ruling: gas-change roof stair (AR - 6.9.26 p2 A-105.01) governs over A-105.00; roof unregistered, geometry NOT changed here; difference recorded once (plan_discrepancies D11).'
                ov.append(dict(track=track, id=i, what='core stair flight', change='basis label typical detail; A-600 answer' + ('; roof stair note' if ex.get('to_level') == 'ROOF' else ''), ruling_source=RS))
        if c == 'plumbing_stack' and ex.get('level') == 'FLOOR_4' and ex.get('sheet') == 'P-103.00' and ex.get('tag') in ('CW-2', 'W-2'):
            printed = ex['tag']; corr = 'W-2' if printed == 'CW-2' else 'CW-2'
            ex.update(status='label_corrected_by_pm', printed_tag_retained=printed, pm_corrected_tag=corr, pm_corrected_system='hot water' if corr == 'W-2' else 'cold water', ruling_source=RS,
                      ruling_note='PM ruling: FLOOR_4 stacks follow P-102 (CW-2 cold, W-2 hot). On P-103 the printed tag CW 2 sits on the two DHW circles and W 2 on the DCW circle: printed labels retained; the corrected tag/system follow the pipe. No geometry change.')
            ov.append(dict(track=track, id=i, what='FLOOR_4 stack ' + printed, change='status=label_corrected_by_pm; pm_corrected_tag=' + corr, ruling_source=RS))
        if c == 'struct_hold_down' and not ex.get('size_designation'):
            ex.update(quantity_status='count not printed', status='count not printed', ruling_source=RS, ruling_note='PM ruling: unknown/track hold-downs labelled count not printed.')
            ov.append(dict(track=track, id=i, what='hold-down (no size/callout)', change='label: count not printed', ruling_source=RS))
    # ---------- write
    G.close(); G.write(H + gfn)
    cols = list(F[0].keys())
    with open(H + ffn, 'w', newline='', encoding='utf8') as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(F)
    summary[track + '_rows'] = len(F); summary[track + '_rowrules'] = dict(nrow)
# ---------- combined framing_elements.csv
Fa = rd(H + 'framing_elements_filed.csv') + rd(H + 'framing_elements_post_co.csv')
with open(H + 'framing_elements.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.DictWriter(f, fieldnames=list(Fa[0].keys())); w.writeheader(); w.writerows(Fa)
# ---------- not_modelled.csv
NM = rd(H + 'not_modelled.csv'); out = []
for r in NM:
    if r['kind'] == 'hold-down': r['reason'] = 'count not printed (PM label 2026-11-03); ' + r['reason']
    if r['kind'] == 'opening' and 'type G' in r['reason']: r['reason'] += ' | v10.1: a visible marker is drawn in layer door_G_undefined (not a frame/head/fill)'
    out.append(r)
for track in TR:
    E = rd(V9 + TR[track][0])
    for h in [e for e in E if e['class'] == 'struct_header']:
        out.append(dict(track=track, kind='header', element_or_item=h['id'], level=h['level'], count=1, reason='struct_header row kept as a v09b original node; not part of the 47 struct_beam rows and not drawn as an L2 member (v10 builds L2 from struct_beam only); designation "%s"' % (h['size_designation'] or 'none printed'), source_sheet=h['sheet'], detail_ref=''))
with open(H + 'not_modelled.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
# ---------- engineer questions: J1 resolved, J2 kept open
Q = rd(H + 'engineer_questions_v10.csv')
for q in Q:
    q['status'] = 'RESOLVED by Roy (PM) 2026-11-03' if q['question_id'] == 'J1' else 'OPEN'
    q['roy_answer'] = ('L4 floor panel = S-102..S-106 note 3 (3/4" USG structural panel). A-302 metal deck + concrete = stair landing detail only. S-402 plywood applied to no element. Removed from the engineer list.' if q['question_id'] == 'J1' else '')
    q['ruling_source'] = RS if q['question_id'] == 'J1' else ''
with open(H + 'engineer_questions_v10.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.DictWriter(f, fieldnames=list(Q[0].keys())); w.writeheader(); w.writerows(Q)
with open(H + 'v09b_rows_ruling_overrides.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.DictWriter(f, fieldnames=['track', 'id', 'what', 'change', 'ruling_source']); w.writeheader(); w.writerows(ov)
# ---------- joists_by_bay.csv carried forward with the quantity label (v09b file copied, not edited)
J = rd(V9 + 'joists_by_bay.csv')
for r in J: r['quantity_label'] = JOIST_LABEL
with open(H + 'joists_by_bay.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.DictWriter(f, fieldnames=list(J[0].keys())); w.writeheader(); w.writerows(J)
print(json.dumps(summary, indent=1)); print(C.Counter(o['what'] for o in ov))
