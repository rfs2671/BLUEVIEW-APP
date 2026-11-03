# p4_chase_report_v11b.py: writes p4_chase_check_v11b.md from p4_chase_clash_flags_v11b.csv (the CHECK Roy asked for: stacks / sloped runs / sprinkler pipes vs P4 piece footprints, per track and level, with ids)
import csv, collections as C
H = 'C:/Users/asddd/bv-worktrees/model_export_v11b/'
rd = lambda p: list(csv.DictReader(open(H + p, encoding='utf8')))
FL = rd('p4_chase_clash_flags_v11b.csv'); PI = rd('p4_chase_pieces_v11b.csv'); LV = ['BELOW_SLAB', 'FLOOR_1', 'FLOOR_2', 'FLOOR_3', 'FLOOR_4', 'MEZZANINE', 'ROOF']
REL = ['fully_inside_p4', 'crosses_p4_boundary', 'outside_p4', 'no_p4_on_level', 'no_xy']
o = ['# P4 chase check (v11b, Roy ruling L3, roy_pm 2026-11-03)', '',
     'Footprint test in plan view on the SAME level: the P4 pieces are the tag-bound P4 wall pieces of that track (filed: 14 walls / 21 pieces; post_co: 6 walls / 9 pieces, F1 and F2 only: the post-CO plan draws the F3, F4 and MEZZ shaft walls WITHOUT a type tag, so they are not P4 here). '
     'Stack = its drawn circle (r from the v09b bbox, 0.126 ft); sloped run = centreline polyline + widest pipe (4 in); sprinkler pipe = its row bbox. `fully_inside_p4` = whole footprint inside the union of the level\'s P4 pieces (1e-6 ft); `crosses_p4_boundary` = touches but is not inside; '
     '`outside_p4`; `no_p4_on_level` (BELOW_SLAB, or a level with no tag-bound P4 piece); `no_xy` (no placed position: ROOF and the 1 unplaced F1 S-4 stack). Ids and per-row flags: p4_chase_clash_flags_v11b.csv. NOT wired into clash.', '']
for track in ('filed', 'post_co'):
    o += ['## %s' % track, '']
    for cls, label in (('plumbing_stack', 'Stacks (127 rows)'), ('sanitary_run_sloped', 'Sloped sanitary runs (52)'), ('sprinkler_pipe', 'Sprinkler pipe rows')):
        rows = [f for f in FL if f['track'] == track and f['class_'] == cls]
        if not rows: o += ['**%s**: none in this track (the post_co model has 0 sprinkler rows).' % label, '']; continue
        o += ['**%s**: total %d' % (label, len(rows)), '', '| level | ' + ' | '.join(REL) + ' |', '|---|' + '---|' * len(REL)]
        c = C.Counter((f['level'], f['p4_relation']) for f in rows)
        for lv in LV:
            if any(c[(lv, r)] for r in REL): o.append('| %s | ' % lv + ' | '.join(str(c[(lv, r)]) or '0' for r in REL) + ' |')
        o.append('| **all** | ' + ' | '.join(str(sum(c[(lv, r)] for lv in LV)) for r in REL) + ' |'); o.append('')
        ins = [f for f in rows if f['p4_relation'] in ('fully_inside_p4', 'crosses_p4_boundary')]
        if cls == 'plumbing_stack':
            for lv in LV:
                a = [f['tag_or_run'] + ('[' + f['element_id'][-4:] + ']') for f in ins if f['level'] == lv and f['p4_relation'] == 'fully_inside_p4']
                b = [f['tag_or_run'] + ('[' + f['element_id'][-4:] + ']') for f in ins if f['level'] == lv and f['p4_relation'] == 'crosses_p4_boundary']
                if a: o.append('- %s fully inside (%d): %s' % (lv, len(a), ', '.join(a)))
                if b: o.append('- %s CROSSING (%d): %s' % (lv, len(b), ', '.join(b)))
            o.append('  (stack tag[last 4 hex of plan_stacks id]; full ids in the CSV)')
        else:
            ids = [f['element_id'].split(':', 1)[-1] if cls == 'sprinkler_pipe' else f['tag_or_run'] for f in ins]
            o.append('- crossing (%d): %s' % (len(ids), ', '.join(ids)) if ids else '- none inside or crossing')
            o.append('- fully inside: %d' % sum(1 for f in rows if f['p4_relation'] == 'fully_inside_p4'))
        o.append('')
open(H + 'p4_chase_check_v11b.md', 'w', encoding='utf8').write('\n'.join(o))
print('\n'.join(o[:80]))
