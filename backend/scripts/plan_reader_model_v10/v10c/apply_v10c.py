# apply_v10c.py: v10b -> v10c. Run ONCE in a fresh copy of v10b (this folder = copy of model_export_v10b; v10b, v10 and v09b are never written).  python apply_v10c.py
# Roy's v10c rulings applied here: (1) stairshaft v2 merge, (3) windows bound by symbol width, (7) roof water-heater room in not_modelled.csv.
# (2) thickness is a PROPOSAL only (nothing applied); (4)(5) are analyses; (6) pitch lives in pitch_v3/.
# Every row/node changed carries ruling_source = roy_pm (the rulings) and a v10c status; no geometry or mesh is touched, no node is added or removed.
import csv, json, re, sys, collections as C
sys.path.insert(0, '.')
R = 'C:/Users/asddd/bv-worktrees/'; V9 = R + 'model_export_v09b/'; H = R + 'model_export_v10c/'; SS = R + 'stairshaft/'
rd = lambda p: list(csv.DictReader(open(p, encoding='utf8')))
src = open(R + 'model_export_v10/build_v10.py', encoding='utf8').read()
exec(src[src.index('class GLB:'):src.index('# ---------------------------------------------------------------- build one track')])
import struct, numpy as np  # noqa  (used by the exec'd GLB helper)
RS = 'roy_pm'
TR = {'filed': ('elements_filed.csv', 'model_filed.glb', 'framing_elements_filed.csv'), 'post_co': ('elements_postco.csv', 'model_postco.glb', 'framing_elements_post_co.csv')}
SHAFT = rd(SS + 'stairs_shaft_v2.csv'); DIFF = rd(SS + 'diff_vs_v09b.csv'); TRACE = rd(H + 'w1_pairing_trace.csv')
WIN_BASIS = 'type_by_symbol_width'
summary = {}; merge_rows = []; win_rows = []; nm_add = []
for track, (efn, gfn, ffn) in TR.items():
    E = rd(V9 + efn); byid = {}
    for e in E: byid.setdefault(e['id'][-6:], []).append(e)
    def full(last6, cls=None):
        c = [e for e in byid.get(last6, []) if cls is None or e['class'] == cls]
        assert len(c) == 1, (track, last6, cls, [e['id'] for e in c]); return c[0]['id']
    G = GLB(H + gfn); N = G.g['nodes']; byname = {n['name']: n for n in N}
    F = rd(H + ffn); summary[track] = {}
    # ------------------------------------------------------------------ (1) stairshaft v2
    # membership of the core stair shaft (ST-A and ST-B share one core) from stairs_shaft_v2.csv; ADDED / REMOVED / kept versus the v09b stairs.csv shaft lists from diff_vs_v09b.csv
    stat = {}   # (level, id) -> status
    for d in DIFF:
        if d['track'] != track: continue
        cls = {'wall': None, 'door': None}[d['kind']]
        e = [x for x in byid[d['id']] if (x['class'] == d['cls'])]
        assert len(e) == 1, (track, d); stat[(d['level'], e[0]['id'])] = (d['status'], d['kind'], d['cls'])
    shaft_by_level = {}
    for s in SHAFT:
        if s['track'] != track or s['stair_id'] not in ('ST-A', 'ST-B') or s['level'] == 'ROOF': continue
        ids = []
        for tk in (s['shaft_walls'].split(';') + s['shaft_doors'].split(';')):
            m = re.match(r'(\w{6})\((\w+):', tk)
            if m: ids.append(full(m.group(1), m.group(2)))
        shaft_by_level.setdefault(s['level'], {})[s['stair_id']] = (s, ids)
    cnt = C.Counter()
    for (lv, eid), (st, kind, cls) in sorted(stat.items()):
        n = byname.get(eid); assert n is not None, ('node missing', eid)
        ex = n.setdefault('extras', {})
        ex.update(stair_shaft_v2=('member of the core stair shaft (ST-A and ST-B, one core) - stairshaft v2' if st != 'REMOVED' else 'NOT a shaft member in stairshaft v2 (outside the v2 shaft window); node and geometry kept'),
                  stair_shaft_v2_change=st, stair_shaft_v2_level=lv, stair_shaft_basis='INFERENCE from model geometry (window = wall rows around the printed stair run), not a printed fact', ruling_source=RS)
        cnt[(st, kind)] += 1; cnt[(st, kind, lv)] += 1
        merge_rows.append(dict(track=track, level=lv, kind=kind, element_id=eid, element_class=cls, change=st, applies_to='ST-A and ST-B (one core)', basis='INFERENCE (geometry)', ruling_source=RS))
    nst = 0
    for lv, per in shaft_by_level.items():
        for sid, (s, ids) in per.items():
            sn = byname.get('stair:%s:%s:%s' % (track, sid, lv)); assert sn is not None, (track, sid, lv)
            sn['extras'].update(shaft_v2_window_ft=[float(s['window_x0']), float(s['window_y0']), float(s['window_x1']), float(s['window_y1'])], shaft_v2_window_basis=s['window_basis'], shaft_v2_member_ids=ids,
                                shaft_v2_status='INFERENCE (geometry)', ruling_source=RS); nst += 1
    summary[track]['stairshaft'] = dict(added_walls=cnt[('ADDED', 'wall')], added_doors=cnt[('ADDED', 'door')], kept_walls=cnt[('kept', 'wall')], kept_doors=cnt[('kept', 'door')], removed_walls=cnt[('REMOVED', 'wall')],
                                        added_by_level={lv: cnt[('ADDED', 'wall', lv)] + cnt[('ADDED', 'door', lv)] for lv in shaft_by_level}, stair_nodes_annotated=nst)
    # ------------------------------------------------------------------ (3) windows: type by symbol width
    tr = {t['id']: t for t in TRACE if t['track'] == track}
    nb = nw = 0; per_type = C.Counter()
    for r in F:
        if r['size_pairing'] != 'size_pairing_unverified': continue
        oid = re.split(r':(frame|head|fill)', r['element_id'])[0]; t = tr[oid]; ok = t['symbol_equals_type_width'] == 'True'
        n = byname[r['glb_node']]; ex = n['extras']
        if ok:
            r['size_pairing'] = WIN_BASIS; r['count_release'] = 'RELEASED'
            r['ruling_note'] = ('window type bound by SYMBOL WIDTH (%s in drawn = A-400 type %s width %s in; widths are unique per type: W1 5\'-0", W2 4\'-0", W3 3\'-0"); the tag text is not near the symbol so the TAG is not what binds it. Released to takeoff inputs (Roy ruling v10c-3). INFERENCE from symbol geometry.' % (t['symbol_in'], t['tag'], t['sched_in']))
            nb += 1; per_type[t['tag']] += 1 if r['class'] == 'opening_frame' else 0
        else:
            r['size_pairing'] = 'size_pairing_unverified'; r['count_release'] = 'WITHHELD'
            r['ruling_note'] = ('window type NOT bound: drawn symbol width %s in does not equal the row type %s width %s in (mismatch); withheld from takeoff inputs' % (t['symbol_in'], t['tag'], t['sched_in'] or 'n/a'))
            nw += 1
        ex.update(size_pairing=r['size_pairing'], count_release=r['count_release'], ruling_note=r['ruling_note'], ruling_source=RS)
        if r['class'] == 'opening_frame': win_rows.append(dict(track=track, window_id=oid, level=t['level'], row_type=t['tag'], symbol_in=t['symbol_in'], type_width_in=t['sched_in'], status=r['size_pairing'], count_release=r['count_release']))
        r['ruling_source'] = RS
    summary[track]['windows'] = dict(rows_bound=nb, rows_withheld=nw, windows_bound_by_type=dict(per_type), windows_withheld=nw // 4)
    # ------------------------------------------------------------------ (7) roof water-heater room
    nm_add.append(dict(track=track, kind='roof structure', element_or_item='roof water-heater room (HWH ROOM, 78 SQ. FT.) enclosure and its roof/framing structure', level='ROOF', count=1,
                       reason='NOT MODELLED: the gas-change set has no structural sheet (AR - 6.9.26 (Gas change).pdf is 2 architectural pages: p1 A-100.00, p2 roof plan with no printed sheet number); the only roof/bulkhead framing is S-106.00 (ST - 7.29.26.pdf p10), which predates the gas change, so where the roof structure differs is NOT determinable. Roof is unregistered (ruling 140).',
                       source_sheet='gas-change roof plan (AR - 6.9.26 (Gas change).pdf p2; no sheet number printed on the page; the system label A-105.01 is a derived label)', detail_ref='HWH ROOM 78 SQ. FT.; ST - 7.29.26.pdf S-106.00 for the only roof framing'))
    G.close(); G.write(H + gfn)
    cols = list(F[0].keys())
    with open(H + ffn, 'w', newline='', encoding='utf8') as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(F)
Fa = rd(H + 'framing_elements_filed.csv') + rd(H + 'framing_elements_post_co.csv')
with open(H + 'framing_elements.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.DictWriter(f, fieldnames=list(Fa[0].keys())); w.writeheader(); w.writerows(Fa)
NM = rd(H + 'not_modelled.csv') + nm_add
with open(H + 'not_modelled.csv', 'w', newline='', encoding='utf8') as f:
    w = csv.DictWriter(f, fieldnames=list(NM[0].keys())); w.writeheader(); w.writerows(NM)
for fn, rows in (('stairshaft_v2_merge.csv', merge_rows), ('window_type_by_symbol_width.csv', win_rows)):
    with open(H + fn, 'w', newline='', encoding='utf8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
json.dump(summary, open(H + 'apply_v10c_summary.json', 'w'), indent=1); print(json.dumps(summary, indent=1))
