# reconcile_walls_v11b.py (Roy task 1): reconcile the untyped-wall counts "43 filed / 115 post-CO" (walltype_read, takeoff: WALLS without a type tag)
# with the v10/v11 counts "55 / 191 unbound_type" (L1 unbound_walls: PIECES of untagged walls that have placed geometry in the model).
# Reads only v09b elements, walltype_read/untyped_*.csv and v11 framing CSVs. Writes wall_count_reconciliation_v11b.csv (one row per wall id, both tracks) + wall_count_summary_v11b.csv.
# Run: cd model_export_v11b ; PYTHONUTF8=1 python reconcile_walls_v11b.py
import csv, re, collections as C
R = 'C:/Users/asddd/bv-worktrees/'; V9 = R + 'model_export_v09b/'; H = R + 'model_export_v11b/'; V11 = R + 'model_export_v11/'
rd = lambda p: list(csv.DictReader(open(p, encoding='utf8')))
TR = {'filed': ('elements_filed.csv', 'framing_elements_filed.csv', 'untyped_filed.csv'), 'post_co': ('elements_postco.csv', 'framing_elements_post_co.csv', 'untyped_postco.csv')}
out = []; summ = []
def npieces(w): return len(w['footprint_pts_ft'].split('|')) if w['footprint_pts_ft'] else 1
for track, (efn, ffn, ufn) in TR.items():
    E = rd(V9 + efn); F = rd(V11 + ffn); U = rd(R + 'walltype_read/' + ufn)
    W = [e for e in E if e['class'] == 'wall']
    unb = C.Counter(re.sub(r'#\d+:solid$', '', r['element_id']) for r in F if r['sublayer'] == 'unbound_walls')
    lay = C.Counter(r['host_or_parent_id'].split('#')[0] for r in F if r['class'].startswith('wall_layer'))
    U_ids = {u['id'] for u in U}; untagged = {w['id'] for w in W if not w['tag']}
    assert U_ids == untagged, (track, len(U_ids), len(untagged))      # the 43 / 115 of walltype_read ARE the walls without a type tag, by id
    for w in W:
        geom = bool(w['x_min_ft']); n = npieces(w) if geom else 0
        if not w['tag']:
            cat = 'untagged, drawn: counted in 43/115 (walls) AND in 55/191 (pieces)' if geom else 'untagged, NO placed geometry (ROOF, unregistered): counted in 43/115 (walls) only; not a piece in 55/191'
        else:
            cat = 'tag-bound (%s), drawn: type layers (L1 printed assembly / P4 chase)' % w['tag'] if geom else 'tag-bound (%s), NO placed geometry (ROOF, unregistered): not in any L1 count' % w['tag']
        out.append(dict(track=track, wall_id=w['id'], level=w['level'], tag=w['tag'], has_geometry='yes' if geom else 'no', exclusion_reason=w['exclusion_reason'], pieces=n,
                        in_walltype_read_untyped_list='yes' if w['id'] in U_ids else 'no', unbound_pieces_in_L1=unb.get(w['id'], 0), L1_layer_rows=lay.get(w['id'], 0), category=cat))
    rows = [o for o in out if o['track'] == track]
    def S(f): return sum(1 for o in rows if f(o))
    summ += [dict(track=track, quantity=q, count=v, unit=u, collection_filter=c) for q, v, u, c in [
        ('all wall rows', len(W), 'walls', 'elements_%s.csv class == wall' % ('filed' if track == 'filed' else 'postco')),
        ('walls with NO type tag (the "43 / 115")', S(lambda o: o['tag'] == ''), 'walls', 'tag == "" (walltype_read/untyped_*.csv, same ids)'),
        ('  untagged, of which drawn (placed geometry)', S(lambda o: o['tag'] == '' and o['has_geometry'] == 'yes'), 'walls', 'x_min_ft present'),
        ('  untagged, of which ROOF, no placed geometry', S(lambda o: o['tag'] == '' and o['has_geometry'] == 'no'), 'walls', 'level ROOF, scale_status unscaled -> excluded'),
        ('PIECES of the drawn untagged walls (the "55 / 191")', sum(o['pieces'] for o in rows if o['tag'] == ''), 'pieces', 'footprint_pts_ft rectangles, one L1 unbound_walls row each'),
        ('unbound_walls rows in framing_elements (v11)', sum(o['unbound_pieces_in_L1'] for o in rows), 'pieces', 'L1_wall_assemblies | unbound_walls'),
        ('walls with a type tag', S(lambda o: o['tag'] != ''), 'walls', 'tag in P1..P5, W1, W2'),
        ('  tagged, of which drawn (type layers on them = "134 filed / 71 post-CO")', S(lambda o: o['tag'] != '' and o['has_geometry'] == 'yes'), 'walls', 'L1 printed-assembly / P4 layers'),
        ('  tagged, of which ROOF, no placed geometry', S(lambda o: o['tag'] != '' and o['has_geometry'] == 'no'), 'walls', 'ROOF unregistered'),
        ('P4 walls (tag-bound; chase wall)', S(lambda o: o['tag'] == 'P4'), 'walls', 'tag P4 (included in the tag-bound line)')]]
for fn, rows in (('wall_count_reconciliation_v11b.csv', out), ('wall_count_summary_v11b.csv', summ)):
    with open(H + fn, 'w', newline='', encoding='utf8') as f: w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
for s in summ: print('%-8s %-70s %5d %s' % (s['track'], s['quantity'], s['count'], s['unit']))
# by level (untagged drawn walls vs pieces)
for track in TR:
    lv = C.defaultdict(lambda: [0, 0])
    for o in out:
        if o['track'] == track and o['tag'] == '' and o['has_geometry'] == 'yes': lv[o['level']][0] += 1; lv[o['level']][1] += o['pieces']
    print(track, 'untagged drawn walls / pieces by level', dict(lv))
