# make_verify_v10b.py: builds verify_v10b.py from verify_v10.py (v10 folder, untouched) + verify_v10b_tail.py
R = 'C:/Users/asddd/bv-worktrees/'
s = open(R + 'model_export_v10/verify_v10.py', encoding='utf8').read()
s = s.replace('# verify_v10.py:', '# verify_v10b.py (adapted from verify_v10.py for v10.1):').replace('python verify_v10.py > verify_out.txt', 'python verify_v10b.py > verify_out.txt')
s = s.replace("H = R + 'model_export_v10/'", "H = R + 'model_export_v10b/'")
s = s.replace("if n.get('extras', {}).get('added_in') == 'v1.0' and 'mesh' in n:", "if n.get('extras', {}).get('added_in') in ('v1.0', 'v1.1') and 'mesh' in n:")
s = s.replace("if ex['class'] in ('wall_stud_line', 'sw_field_stud_line'): cnt_glb[k] += ex['stud_count']", "if ex['class'] in ('wall_stud_line', 'sw_field_stud_line'): cnt_glb[k] += g['accessors'][g['meshes'][n['mesh']]['primitives'][0]['attributes']['POSITION']]['count'] // 2   # lines read from the mesh; no stud_count is exported")
s = s.replace("'identified_visually', 'measured_from_drawing'}", "'identified_visually', 'measured_from_drawing', 'layout_assumed', 'door_G_undefined'}")
s = s.replace("chk(track + ' L4 joists status rule_from_continuity and WITHHELD', all(r['status'] == 'rule_from_continuity' and 'WITHHELD' in r['notes'] for r in j))",
              "chk(track + ' L4 joists status rule_from_continuity, WITHHELD, labelled at printed 16 in spacing, minimum, roy_pm', all(r['status'] == 'rule_from_continuity' and 'WITHHELD' in r['notes'] and r['quantity_label'] == 'at printed 16 in spacing, minimum' and r['ruling_source'] == 'roy_pm' for r in j))")
s = s.replace("for k in sorted(cnt_csv): print('   %-26s %-40s %d' % (k[0], k[1], cnt_csv[k]))", "for k in sorted(cnt_csv): print('   %-26s %-40s %s' % (k[0], k[1], 'layout_assumed, count WITHHELD' if k[1] in ('studs_track', 'field_studs') else cnt_csv[k]))")
i = s.rindex("print('\\nRESULT:'")
s = s[:i] + open(R + 'model_export_v10b/verify_v10b_tail.py', encoding='utf8').read()
open(R + 'model_export_v10b/verify_v10b.py', 'w', encoding='utf8').write(s)
