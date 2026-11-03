# pitch_v2/sensitivity.py: re-runs the pitchmap method (pitchmap/runs.py + the build.py loop, copied, pitchmap NOT altered) under varied cluster parameters and slope assumptions.
# Run: cd pitch_v2 ; PYTHONUTF8=1 python sensitivity.py
import sys, math, csv, collections, heapq, json, itertools
sys.path.insert(0, 'C:/Users/asddd/bv-worktrees/pitchmap')
import runs as RU
UW = {'FLOOR_1': 42.6408, 'FLOOR_2': 52.6408, 'FLOOR_3': 62.6408, 'FLOOR_4': 72.6408, 'MEZZANINE': 82.4742}
LVL = {'P-201.00': 'FLOOR_1', 'P-202.00': 'FLOOR_2', 'P-203.00': 'FLOOR_3', 'P-204.00': 'FLOOR_4', 'P-205.00': 'MEZZANINE'}
DROPSZ = {'BT-1': 2, 'LAV-1': 2, 'KS-1': 2, 'WC-1': 3, 'FD-1': 3}
L4 = ['BT-1', 'LAV-1', 'WC-1', 'KS-1']
FIX = {('P-201.00', 'S-1'): L4, ('P-201.00', 'S-4'): ['BT-1', 'WC-1', 'KS-1']}
for s in ('S-1', 'S-2', 'S-3', 'S-4'):
    FIX[('P-202.00', s)] = L4; FIX[('P-204.00', s)] = ['BT-1', 'LAV-1', 'WC-1']
for s in ('S-1', 'S-2'): FIX[('P-203.00', s)] = ['KS-1', 'FD-1', 'BT-1', 'LAV-1', 'WC-1']
for s in ('S-3', 'S-4'): FIX[('P-203.00', s)] = ['BT-1', 'LAV-1', 'WC-1', None]
FIX[('P-205.00', 'S-3')] = ['FD-1']
D_END = 4.0
def preds(rec, start):
    adj = collections.defaultdict(list)
    for e in rec['edges']:
        adj[e['na']].append((e['nb'], e['L'])); adj[e['nb']].append((e['na'], e['L']))
    best = None
    for e in rec['edges']:
        d, c, t = RU.dist_pt_seg(start, e['a'], e['b'])
        if best is None or d < best[0]: best = (d, e, t)
    d, e, t = best; dist = {}; pr = {}
    h = [(t * e['L'], e['na'], -1), ((1 - t) * e['L'], e['nb'], -1)]
    while h:
        dd, u, p = heapq.heappop(h)
        if u in dist and dist[u] <= dd: continue
        dist[u] = dd; pr[u] = None if p == -1 else p
        for v, w in adj[u]:
            if v not in dist or dist[v] > dd + w: heapq.heappush(h, (dd + w, v, u))
    return dist, pr, adj
def legs(sheet, level):
    """-> list of (id, fixture, branch_len, trunk_len, L) for every mapped sanitary leaf at the current RU.GAP/RU.JOIN; and a count of unmapped components"""
    out = []; unmapped = 0
    for r in RU.run_sheet(sheet, ['sanitary']):
        if not r['leaves']: continue
        fx = FIX.get((sheet, r['stack']))
        if fx is None or len(fx) != len(r['leaves']): unmapped += 1; continue
        dist, pr, adj = preds(r, r['stack_xy'])
        for i, (n, L, pt) in enumerate(r['leaves']):
            f = fx[i]
            if f is None: continue
            bl = 0.0; cur = n; found = False
            while pr.get(cur) is not None:
                p = pr[cur]; bl += dist[cur] - dist[p]; cur = p
                if len(adj[cur]) >= 3: found = True; break
            if not found: bl = L
            bl = min(bl, L)
            out.append((level.replace('FLOOR_', 'F').replace('MEZZANINE', 'MZ') + '-' + r['stack'] + '-' + f, f, bl, L - bl, L))
    return out, unmapped
def slope(sz): return 0.125 if sz >= 3 else 0.25
TRUNK = {'trunk_4in(1/8)': 0.125, 'trunk_2in(1/4)': 0.25}
BRANCH = {'branch_as_printed': None, 'all_1/8': 0.125, 'all_1/4': 0.25}
PARAMS = [(0.45, 0.20), (0.35, 0.20), (0.40, 0.20), (0.50, 0.20), (0.55, 0.20), (0.45, 0.15), (0.45, 0.25), (0.35, 0.15), (0.55, 0.25)]
rows = []; nlegs = {}
for gap, join in PARAMS:
    RU.GAP = gap; RU.JOIN = join
    LG = {}; unm = 0
    for sheet, level in LVL.items():
        LG[level], u = legs(sheet, level); unm += u
    nlegs[(gap, join)] = (sum(len(v) for v in LG.values()), unm)
    for (tn, ts), (bn, bs) in itertools.product(TRUNK.items(), BRANCH.items()):
        for level, lst in LG.items():
            best = None
            for rid, f, bl, tl, L in lst:
                sb = bs if bs is not None else slope(DROPSZ[f])
                drop = sb * bl + ts * tl
                if best is None or drop > best[1]: best = (rid, drop, L)
            if best: rows.append(dict(gap_ft=gap, join_ft=join, trunk=tn, branch=bn, level=level, runs=len(lst), controlling_run=best[0], run_len_ft=round(best[2], 2), drop_in=round(best[1], 3), lowest_pt_navd_ft=round(UW[level] - D_END / 12 - best[1] / 12, 4)))
    print('gap', gap, 'join', join, 'legs', nlegs[(gap, join)], flush=True)
w = csv.DictWriter(open('sensitivity_lowest_point.csv', 'w', newline='', encoding='utf8'), fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
json.dump({str(k): v for k, v in nlegs.items()}, open('sensitivity_leg_counts.json', 'w'))
# pivot: lowest point per level per combination
piv = collections.defaultdict(dict)
for r in rows: piv[(r['gap_ft'], r['join_ft'], r['trunk'], r['branch'])][r['level']] = (r['lowest_pt_navd_ft'], r['controlling_run'], r['drop_in'])
lv = list(LVL.values())
with open('sensitivity_table.md', 'w', encoding='utf8') as f:
    f.write('# Pitch sensitivity: lowest point (NAVD ft) per level, drop in inches in brackets\n\n| gap | join | trunk | branch | legs (unmapped comps) | ' + ' | '.join(lv) + ' |\n|' + '---|' * (5 + len(lv)) + '\n')
    for k, v in piv.items():
        f.write('| %s | %s | %s | %s | %s (%s) | ' % (k + (nlegs[(k[0], k[1])][0], nlegs[(k[0], k[1])][1])) + ' | '.join(('%.4f (%.2f)' % (v[l][0], v[l][2])) if l in v else '-' for l in lv) + ' |\n')
spread = {l: (min(r['lowest_pt_navd_ft'] for r in rows if r['level'] == l), max(r['lowest_pt_navd_ft'] for r in rows if r['level'] == l)) for l in lv}
print(spread)
json.dump(spread, open('sensitivity_spread.json', 'w'))
