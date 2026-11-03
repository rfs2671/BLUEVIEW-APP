
# ---------------- v10.1 additions
for track, (efn, gfn, ffn) in {'filed': ('elements_filed.csv', 'model_filed.glb', 'framing_elements_filed.csv'), 'post_co': ('elements_postco.csv', 'model_postco.glb', 'framing_elements_post_co.csv')}.items():
    print('\n######## v10.1 checks', track)
    g, binb = parse(H + gfn); N = g['nodes']; F = rd(H + ffn); E = {r['id']: r for r in rd(V9 + efn)}; byn = {n['name']: n for n in N}
    chk(track + ' no stud_count exported in any node extras', not any('stud_count' in n.get('extras', {}) for n in N))
    chk(track + ' no stud-count column in framing CSV', not any('stud_count' in k for k in F[0]))
    SL = ('wall_stud_line', 'wall_track_line', 'sw_field_stud_line')
    chk(track + ' every stud/track/field-stud row has status layout_assumed, ruling_source roy_pm, count_release WITHHELD', all(r['status'] == 'layout_assumed' and r['ruling_source'] == 'roy_pm' and r['count_release'] == 'WITHHELD' for r in F if r['class'] in SL), sum(r['class'] in SL for r in F))
    gm = [n for n in N if n.get('extras', {}).get('class') == 'door_G_marker']; gl = [r for r in F if r['class'] == 'door_G_marker']
    chk(track + ' door_G_undefined marker layer: nodes == rows, in a LAYER group, status door_G_undefined', len(gm) == len(gl) and len(gm) > 0 and any(n['name'] == 'LAYER door_G_undefined' for n in N) and all(n['extras']['status'] == 'door_G_undefined' for n in gm), '%d markers' % len(gm))
    gdoors = [e for e in E.values() if e['class'].startswith('door') and e['tag'] == 'G']; placed = [e for e in gdoors if e['position_status'] != 'unplaced']
    chk(track + ' marker per placed G door (%d of %d G doors); no frame/head/fill row for any G door' % (len(placed), len(gdoors)), len(gm) == len(placed) and not any(r['element_id'].startswith(e['id'] + ':') and r['class'] != 'door_G_marker' for e in gdoors for r in F))
    apt = [n for n in N if n.get('extras', {}).get('kind') == 'apartment stair']
    chk(track + ' apartment stairs 4A-4D: interior stair, field-measured; clash no; structure_count no; no treads; roy_pm', len(apt) == 4 and all(n['extras']['status'] == 'interior stair, field-measured' and n['extras']['clash_include'] == 'no' and n['extras']['structure_count_include'] == 'no' and n['extras']['treads_drawn'] == 'none' and n['extras']['ruling_source'] == 'roy_pm' for n in apt), len(apt))
    core = [n for n in N if str(n.get('extras', {}).get('id', '')).startswith('stair:') and n['extras'].get('kind') != 'apartment stair']
    chk(track + ' core stairs: typical detail label + A-600 answer, roy_pm', len(core) > 0 and all('typical detail' in n['extras']['basis_label'] and 'A-600' in n['extras']['a600_answer'] and n['extras']['ruling_source'] == 'roy_pm' for n in core), len(core))
    f4 = [n for n in N if n.get('extras', {}).get('level') == 'FLOOR_4' and n['extras'].get('class') == 'plumbing_stack' and n['extras'].get('sheet') == 'P-103.00' and n['extras'].get('tag') in ('CW-2', 'W-2')]
    chk(track + ' FLOOR_4 stacks CW-2/W-2: label_corrected_by_pm, printed tag retained', len(f4) == 3 and all(n['extras']['status'] == 'label_corrected_by_pm' and n['extras']['printed_tag_retained'] == n['extras']['tag'] for n in f4), len(f4))
    g9, _ = parse(V9 + gfn); m9 = {n['name']: n.get('mesh') for n in g9['nodes']}
    chk(track + ' FLOOR_4 stacks, stairs: mesh index identical to v09b (no geometry change)', all(byn[n['name']].get('mesh') == m9[n['name']] for n in f4 + apt + core))
    hdn = [n for n in N if n.get('extras', {}).get('class') == 'struct_hold_down' and not n['extras'].get('size_designation')]
    chk(track + ' unknown hold-downs placed in GLB labelled count not printed (50 placed + 6 unplaced = 56 in not_modelled)', len(hdn) == 50 and all(n['extras']['quantity_status'] == 'count not printed' for n in hdn) and sum(r['kind'] == 'hold-down' and r['track'] == track and r['reason'].startswith('count not printed') for r in rd(H + 'not_modelled.csv')) == 56, '%d nodes' % len(hdn))
    fp = [r for r in F if r['class'] == 'floor_panel']; chk(track + ' floor panel rows: ruling roy_pm, J1 resolved text', all(r['ruling_source'] == 'roy_pm' and 'J1 resolved' in r['detail_ref'] for r in fp), len(fp))
    p5 = [r for r in F if r['type_tag'] == 'P5' and r['class'].startswith('wall_layer')]; chk(track + ' P5 layer rows: sum 4 3/4 and carry roy_pm', len(p5) > 0 and all(r['ruling_source'] == 'roy_pm' and 'sum of drawn layers 4.750' in r['size_note'] for r in p5), len(p5))
    wr = [r for r in F if r['size_pairing'] == 'size_pairing_unverified']; chk(track + ' window opening rows marked size_pairing_unverified and WITHHELD', len(wr) > 0 and all(r['count_release'] == 'WITHHELD' for r in wr), len(wr))
    rm = {'filed': ['645ca4', '645cfa', '645d4d', '645da6'], 'post_co': ['645e89', '645edf', '645f32', '645f8b']}[track]; P = 'plan_structural:6ae49c0d0b73eb6c86645'
    chk(track + ' stairshaft v2 REMOVED rows (bearing wall x 15.32-28.99, y 17.45, F2..MEZZ) still present as struct_bearing_wall nodes with geometry', all((P + i[3:]) in byn and byn[P + i[3:]]['extras']['class'] == 'struct_bearing_wall' and 'mesh' in byn[P + i[3:]] for i in rm), len(rm))
    bb = [r for r in rd(H + 'box_beam_reconciliation.csv') if r['track'] == track and r['class_'] == 'struct_beam']
    chk(track + ' box beams: 47 rows all accounted (31 solid + 6 outline + 9 roof + 1 refused)', len(bb) == 47 and C.Counter(r['disposition'][:8] for r in bb) == C.Counter({'L2 solid': 31, 'L2 outli': 6, 'not draw': 9, 'refused:': 1}), dict(C.Counter(r['disposition'][:30] for r in bb)))
    chk(track + ' ruling_source column present', 'ruling_source' in F[0])
print('\nRESULT v10.1:', 'ALL PASS' if not FAILS else 'FAILS: %s' % FAILS)
sys.exit(1 if FAILS else 0)
