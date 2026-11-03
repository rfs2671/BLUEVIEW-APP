# make_discrepancies_v10b.py: wall_thickness_measured_vs_printed.csv, p5_pieces.csv, box_beam_reconciliation.csv, w1_pairing_trace.csv, plan_discrepancies.csv/.md. Read-only on v09b/v10.
import csv, json, math, collections as C
R = 'C:/Users/asddd/bv-worktrees/'; V9 = R + 'model_export_v09b/'; H = R + 'model_export_v10b/'
rd = lambda p: list(csv.DictReader(open(p, encoding='utf8')))
fl = lambda x: float(x) if x not in ('', None) else None
def wcsv(name, rows):
    with open(H + name, 'w', newline='', encoding='utf8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
PRINTED = {'P1': 6.0, 'P2': 6.0, 'P3': 3.75, 'P4': None, 'P5': 3.75, 'P6': 7.25, 'W1': 9.25, 'W2': 10.75}
PARTS = {'P1': 6.0, 'P2': 6.0, 'P3': 3.75, 'P4': None, 'P5': 4.75, 'P6': 7.25, 'W1': 9.25, 'W2': 10.75}
# ---------------- every typed wall piece, both tracks
W = []
for track, f in (('filed', 'elements_filed.csv'), ('post_co', 'elements_postco.csv')):
    for e in rd(V9 + f):
        if e['class'] != 'wall' or not e['tag'] or not e['x_min_ft']: continue
        if e['footprint_pts_ft']: pcs = [[tuple(map(float, q.split(','))) for q in pc.split(';')] for pc in e['footprint_pts_ft'].split('|')]
        else:
            x0, y0, x1, y1 = [fl(e[k]) for k in ('x_min_ft', 'y_min_ft', 'x_max_ft', 'y_max_ft')]; pcs = [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]
        for k, p in enumerate(pcs):
            a, b = math.dist(p[0], p[1]), math.dist(p[1], p[2]); thick = min(a, b) * 12; length = max(a, b)
            pr = PRINTED.get(e['tag']); pt = PARTS.get(e['tag'])
            W.append(dict(track=track, wall_id=e['id'], piece=k, level=e['level'], type_tag=e['tag'], sheet=e['sheet'], measured_in=round(thick, 2), piece_length_ft=round(length, 2), printed_total_in=pr if pr is not None else 'VARIES/none',
                          sum_of_printed_parts_in=pt if pt is not None else 'none', delta_vs_printed_in=round(thick - pr, 2) if pr is not None else '', delta_vs_sum_of_parts_in=round(thick - pt, 2) if pt is not None else ''))
wcsv('wall_thickness_measured_vs_printed.csv', W)
P5 = [w for w in W if w['type_tag'] == 'P5']
for w in P5:
    w['delta_vs_3_3_4'] = round(w['measured_in'] - 3.75, 2); w['delta_vs_4_3_4'] = round(w['measured_in'] - 4.75, 2); w['closer_to'] = '3 3/4' if abs(w['delta_vs_3_3_4']) < abs(w['delta_vs_4_3_4']) else '4 3/4'
    w['matches_either_within_0_5_in'] = 'yes' if min(abs(w['delta_vs_3_3_4']), abs(w['delta_vs_4_3_4'])) <= 0.5 else 'NO'
wcsv('p5_pieces.csv', [{k: v for k, v in w.items() if k not in ('printed_total_in', 'sum_of_printed_parts_in', 'delta_vs_printed_in', 'delta_vs_sum_of_parts_in')} for w in P5])
p5s = C.Counter((w['track'], w['measured_in']) for w in P5)
# ---------------- type summary
T = C.defaultdict(list)
for w in W: T[w['type_tag']].append(w)
tsum = []
for t, v in sorted(T.items()):
    d = C.Counter((w['track'], w['measured_in']) for w in v)
    tsum.append((t, len(v), len({w['wall_id'] for w in v}), sorted({w['measured_in'] for w in v}), PRINTED.get(t), PARTS.get(t)))
# ---------------- box-beam reconciliation (per track, by row id)
BB = []
F = {tr: rd(H + fn) for tr, fn in (('filed', 'framing_elements_filed.csv'), ('post_co', 'framing_elements_post_co.csv'))}
for track, f in (('filed', 'elements_filed.csv'), ('post_co', 'elements_postco.csv')):
    E = rd(V9 + f); l2 = C.defaultdict(list)
    for r in F[track]:
        if r['layer'] == 'L2_box_beams': l2[r['host_or_parent_id']].append(r)
    nm = {r['element_or_item']: r for r in rd(H + 'not_modelled.csv') if r['track'] == track and r['kind'] in ('beam', 'header')}
    for e in E:
        if e['class'] not in ('struct_beam', 'struct_header'): continue
        i = e['id']
        if e['class'] == 'struct_header': disp = 'struct_header row (separate class; kept as a v09b original node; NOT among the 47 beam rows; not an L2 member)'; det = e['size_designation'] or 'no designation'
        elif i in l2:
            sub = l2[i][0]['sublayer']
            disp = 'L2 solid: 2 members (note-4 box beam)' if sub == 'box_beam_members' else 'L2 outline only: label-governed (2) nSWm, depth unknown'; det = l2[i][0]['designation_as_printed']
        elif i in nm: disp = 'refused: conflicting/ambiguous candidate labels' if 'refused' in nm[i]['reason'] else 'not drawn: roof level unregistered'; det = e['size_rule'] or e['size_designation']
        else: disp = 'UNACCOUNTED'; det = ''
        BB.append(dict(track=track, element_id=i, class_=e['class'], level=e['level'], sheet=e['sheet'], position_status=e['position_status'], disposition=disp, designation_or_label=det))
wcsv('box_beam_reconciliation.csv', BB)
bbc = {tr: C.Counter(r['disposition'].split(':')[0] + (':' + r['disposition'].split(':')[1][:20] if r['disposition'].startswith('L2') else '') for r in BB if r['track'] == tr and r['class_'] == 'struct_beam') for tr in ('filed', 'post_co')}
bbr = {tr: [r['element_id'] for r in BB if r['track'] == tr and r['disposition'].startswith('refused')] for tr in ('filed', 'post_co')}
# ---------------- W1 pairing trace csv
tr = json.load(open(H + 'w1_pairing_trace.json'))
for o in tr:
    nt = (o['near_tag'] or '').replace(' ', '').replace('-', ''); o['nearest_tag_equals_own_tag'] = nt == o['tag'].replace('-', ''); o['symbol_equals_type_width'] = bool(o['sched_in']) and abs(o['symbol_in'] - float(o['sched_in'])) < 1.5
    o['verdict'] = 'size_pairing_unverified'; o['symbol_center'] = '%s;%s' % tuple(o['symbol_center'])
wcsv('w1_pairing_trace.csv', tr)
pc = C.Counter((o['track'], o['tag'], o['symbol_equals_type_width'], o['nearest_tag_equals_own_tag']) for o in tr)
json.dump({str(k): v for k, v in pc.items()}, open(H + 'work/w1_pairing_summary.json', 'w'))
# ---------------- plan_discrepancies
D = []
def d(id_, topic, item, printed, quote, where, derived, measured, delta, status, ruling, note=''):
    D.append(dict(id=id_, topic=topic, item=item, printed_value=printed, printed_quote=quote, printed_sheet_page=where, derived_value=derived, measured_value=measured, delta=delta, status=status, ruling=ruling, ruling_source='roy_pm' if ruling else '', notes=note))
A500 = 'A-500.00, AR - 3.28.25.pdf p24 (sheet 24 of 31)'
p5m = sorted({w['measured_in'] for w in P5}); n5 = len({(w['track'], w['wall_id']) for w in P5})
d('D01', 'wall thickness: printed total vs sum of parts', 'P5', '3 3/4"', 'P5 dimension string "3 3/4"" (A-500 section P5); layers 5/8 + 5/8 gypsum (corridor side), 2 1/2" CH studs, 1" gypsum liner panel (shaft side)', A500,
  '4 3/4" = 5/8 + 5/8 + 2 1/2 + 1', 'measured on the plan, %d P5 pieces on %d walls (both tracks): %s in; see p5_pieces.csv' % (len(P5), n5, ', '.join('%s in x %d (%s)' % (k[1], v, k[0]) for k, v in sorted(p5s.items()))),
  'printed total vs parts +1.00 in; the two real P5 walls (4.00 in, 2.33 ft long each, per track) measure +0.25 vs 3 3/4 and -0.75 vs 4 3/4, i.e. nearer 3 3/4; the other 2 pieces per track are 0.67 and 0.83 ft stubs (8 in x 8 in and 8 in x 10 in) whose short side is not a wall thickness and match neither (+4.25 / +3.25)', 'plan-internal discrepancy, both values listed', 'PM: layers drawn as printed parts (4 3/4"); printed 3 3/4" logged as a discrepancy', 'the 4.00 in pieces sit 0.25 in from 3 3/4"; see thickness_offset_test.md for the +0.25 convention')
for t, n, nw, ms, pr, pt in tsum:
    pass
dn = 2
for t, n, nw, ms, pr, pt in tsum:
    if t == 'P5': continue
    dd = '; '.join('%s in' % m for m in ms)
    delta = ('%+.2f in' % (ms[0] - pr)) if (pr is not None and len(ms) == 1) else ('see wall_thickness_measured_vs_printed.csv' if pr is not None else 'no printed number')
    quote = {'P1': '"6"" (layers 5/8+5/8 + 3 1/2" stud + 5/8+5/8)', 'P2': '"6"" (same layers)', 'P3': '"3 3/4"" (5/8 + 2 1/2" stud + 5/8)', 'P4': '"VARIES" (each leaf 5/8+5/8+1 5/8 = 2 7/8")', 'P6': '"7 1/4""', 'W1': '"9 1/4"" (2" EPS/stucco + 5/8 + 6" stud + 5/8)', 'W2': '"10 3/4"" (2 1/4" EPS/stucco + 2 x 5/8 + 6" stud + 2 x 5/8)'}.get(t, '')
    d('D%02d' % dn, 'wall thickness: measured on plan vs printed', t, '%s' % (('%g"' % pr) if pr is not None else 'VARIES/none'), quote, A500, ('sum of parts %g"' % pt) if pt else 'none',
      'measured %s on %d pieces / %d walls (both tracks)' % (dd, n, nw), delta, 'measured over printed' if (pr is not None and ms[0] > pr) else ('matches' if pr is not None and len(ms) == 1 else 'varies'), '', 'drawn plan thickness is a whole number of inches in every type; test in thickness_offset_test.md' if t in ('P3', 'W1', 'W2') else '')
    dn += 1
d('D%02d' % dn, 'printed vs printed', 'BOX BEAM -54 vs -118', '(2) 800S162-54 on S-102, S-103, S-105, S-106; (2) 800S162-118 on S-104', 'S-102/103/105/106 note 4: "INDICATES (2) 800S162-54 BOX BEAM U.O.N."; S-104 note 4: "INDICATES (2) 800S162-118 BOX BEAM U.O.N."', 'ST - 7.29.26.pdf p6, p7, p9, p10 (-54); p8 (-118)', 'each beam takes its own sheet note (31 note-4 beams per track)', '', 'one sheet differs from four', 'resolved as per-sheet designation in the model; the -118 on S-104 is not confirmed by a schedule (none exists)', '', 'also S-104 header row prints (2) 800S162-118'); dn += 1
d('D%02d' % dn, 'printed vs printed', 'WC-1 drop 3 in vs 4 in', '3" SAN DROP (key note 1)', 'key note 1: "PROVIDE 3" SAN DROP, 2" VENT RISE PIPING ... TYPICAL FOR PRIVATE WATER CLOSETS (WC-1)"; P-301.00 prints 4" on the WC-1 horizontal branch', 'PL - 6.29.26.pdf p9-13 (P-201..P-205) key note 1; p17 (P-301.00)', 'both are "3 in or larger": slope tier 1/8 in/ft, no pitch number changes', '', '3 in vs 4 in', 'listed, both values kept', '', 'pitch_v2/pitch_runs_v2.csv cites key note 1 by coordinates'); dn += 1
d('D%02d' % dn, 'printed unresolved', 'Door G width', 'G.C. TO DECIDE', 'A-400 door type G INTERIOR CLOSED (pair): width VARIES x 6\'-8", SIZE "G.C. TO DECIDE"', 'A-400.00, AR - 3.28.25.pdf p23', 'no frame, head or fill drawn; marker layer door_G_undefined (15 per track placed)', '', 'no size printed', 'listed; marker drawn; not_modelled.csv', '', 'post-CO has 1 further G door unplaced'); dn += 1
d('D%02d' % dn, 'sheet vs sheet', 'Roof stair: gas change vs A-105.00', 'gas change A-105.01: stair pieces at x 42-50 ft (own frame), DN 16 at (43.8, 21.54) and (48.18, 5.03)', 'DN 16 labels', 'AR - 6.9.26 (Gas change).pdf p2 (A-105.01)', 'A-105.00 (AR - 3.28.25 p16, Owners set p6): DN 16 at core coordinates (30.63, 24.33) and (34.13, 11.14)', '', 'different stair location', 'listed once', 'PM: gas change governs over A-105.00', 'roof unregistered; no geometry changed'); dn += 1
d('D%02d' % dn, 'printed vs drawn', 'Door F width', '2\'-10" (A-400 SIZE row)', 'A-400 type F SIZE 2\'-10" x 6\'-8"', 'A-400.00, AR - 3.28.25.pdf p23', '', 'drawn leaf 2\'-6" on the plan', '-4 in', 'open (B2)', '', 'takeoff counts the printed 2\'-10"'); dn += 1
d('D%02d' % dn, 'printed vs printed', 'Building height', '45\'-0" (Z-001, Z-002) vs 50\'-0" (A-200..A-202)', '', 'Z-001/Z-002; A-200..A-202', 'levels agree with 50\'-0"', '', '5 ft', 'open (C2)', ''); dn += 1
d('D%02d' % dn, 'printed vs pipes', 'FLOOR_4 tags CW-2 / W-2 transposed on P-103', 'tag "CW 2" on the two DHW-120F circles; tag "W 2" on the DCW circle', 'P-102: "CW 2" leads to the DCW circle, "W 2" to the two DHW circles', 'PL - 6.29.26.pdf p4 (P-102) vs p5 (P-103)', 'stacks follow P-102', '', 'tags swapped vs pipes on one floor', 'label_corrected_by_pm', 'PM: FLOOR_4 stacks follow P-102 (CW-2 cold, W-2 hot); printed labels retained', 'geometry unchanged; 3 rows per track'); dn += 1
d('D%02d' % dn, 'printed vs printed', 'Floor build-up over 8J12 joists', '3/4" USG structural panel (S-102..S-106 note 3); metal deck with concrete (A-302); plywood at 12" o.c. (S-402 det 4-6)', 'S-102..S-106 note 3: "3/4" USG STRUCTURAL PANEL CONCRETE SUB-FLOOR ..."; A-302: "METAL DECK WITH CONCRETE"; S-402 note 2: "ATTACH PLYWOOD TO JOIST AT 12" O.C. IN FIELD OF BOARD AND 6" O.C. AT ENDS"', 'ST - 7.29.26.pdf p6-p10; A-302; S-402 p14', 'floor panel = note 3', '', 'three build-ups', 'RESOLVED', 'PM: floor = structural panel; metal deck + concrete = stair landing only; S-402 plywood applied nowhere (J1 closed)'); dn += 1
d('D%02d' % dn, 'sheet listed, not in set', 'A-600 ENLARGED STAIR DETAILS', 'listed on T-001', 'T-001: "A-600 ENLARGED STAIR DETAILS STAIR A / B"', 'T-001; AR - 3.28.25.pdf has 26 of 31 listed sheets', 'core stair basis = A-302 detail 11, labelled typical detail', '', 'sheet absent', 'RESOLVED', 'PM: listed on T-001, not in set, removed (design changed); no stair data taken from it (G1 closed)'); dn += 1
d('D%02d' % dn, 'printed vs printed', 'Passive recreation area / occupancy', '2112 SF / 11 persons (filed A-105.00 p16 and gas change) vs 1970 SF / 10 persons (AR 8.18.26 p7, ignored file; owner set A-105.00 p6 prints 1970 SF only)', '"PASSIVE RECREATION 1970 SQ. FT."', 'AR - 3.28.25 p16; AR - 6.9.26 p2; Owners set p6; AR - 8.18.26 p7', '', '', '142 SF', 'RESOLVED', 'PM: gas change = the amendment; 1970 SF is post-CO only; filed stays 2112 / 11 (H1 closed)'); dn += 1
d('D%02d' % dn, 'drawn vs printed count', 'Apartment stairs 4A-4D tread geometry', '16 risers printed (UP 16 / DN 16); 10 in step (A-302 det 11); run dimension 7\'-8"', '"UP 16", "7\'-8""', 'AR - 3.28.25 A-103 p14, A-104 p15; Owners set pp4-5', '15 treads at 10 in need 12.5 ft straight', 'drawn footprint 7.67 x 5.22 ft (F4), 8.33 ft union; 13 cells + 2 square pieces', '12.5 ft needed vs 7.67 ft drawn', 'RESOLVED (not a defect to model)', 'PM: apartment stairs = envelope, interior stair, field-measured; excluded from structure counts and clash; no treads (I1 closed)'); dn += 1
d('D%02d' % dn, 'plan-internal', 'Shear-wall panel box height vs 10\'-0" storey', 'storey 10\'-0" (level elevations 33.37 / 43.37 ...)', '', 'S-302 (ST - 7.29.26.pdf p12) X-brace boxes, scale 0.0741 ft/pt as used by v09b', 'see sw_panel_heights.csv', 'upper-storey X boxes 139.4 pt = 10.33 ft (6 of 6); lowest-storey X boxes 130.4-130.5 pt = 9.67 ft (5), SW 4&5 lower 130.0 pt = 9.63 ft; mid boxes 91.4 pt = 6.77 ft (7)', '-0.33 / +0.33 ft vs 10 ft', 'listed', '', 'the SW 4&5 lower box (9.63 ft) is 0.4 pt shorter than the other lowest-storey boxes: consistent'); dn += 1
d('D%02d' % dn, 'printed vs printed', 'Joist spacing: printed 16 in vs S-002', '8J12(800S200-97) JOISTS @16" O.C. (S-102..S-105 note 2)', 'S-002.00: "JOIST SPACING SHOWN ON PLAN IS MAXIMUM PERMISSIBLE. UNDER NO CIRCUMSTANCES SHALL THIS SPACING BE EXCEEDED."', 'ST - 7.29.26.pdf p3 (S-002.00); p6-p9 note 2', '358 joists = minimum count at the printed 16 in spacing', '', 'spacing is a maximum', 'labelled "at printed 16 in spacing, minimum" (PM)', 'PM: joist label', ''); dn += 1
d('D%02d' % dn, 'printed vs printed', 'Ten members: box-beam symbol vs label 10SW10 / 8SW10', 'symbol: (2) 800S162-54 (S-104: -118)', 'label "(2) 10SW10" / "(2) 8SW10"', 'S-102 p6, S-103 p7, S-104 p8, S-106 p10', 'rev 2 binds the label, keeps the symbol designation beside it', '', 'symbol vs label', 'open (D7)', '', 'ids in PM_OPEN_QUESTIONS D7'); dn += 1
d('D%02d' % dn, 'tag vs symbol', 'W1/W2 window tag-to-size pairing; W3', 'W1 60 in, W2 48 in (A-400 type widths)', '', 'A-400; symbols on A-100..A-105', 'symbol width equals the type width for 36/36 W1 and 5/5 W2 filed (36/37 W1 post-CO: one symbol 58 in); W3 symbols 45 in (filed) / 36 in (post-CO), no schedule width', '', 'tag text lies >45 pt from its symbol in every case and the nearest W tag differs from the row tag for 10 of 36 W1 and 3 of 5 W2 (filed)', 'size_pairing_unverified; sizes withheld from takeoff', '', 'w1_pairing_trace.csv'); dn += 1
d('D%02d' % dn, 'sheet number', 'Duplicate T-001.00 on the filed track', 'two pages print T-001.00', '', 'ST - 7.29.26.pdf p1; AR - 3.28.25.pdf p1', '', '', '', 'open (C7)', ''); dn += 1
d('D%02d' % dn, 'printed vs printed', 'W-5 absent from the P-300 domestic water riser diagram', 'plans P-100..P-104 tag W-5 "DHWR UP&DN"', 'riser diagram tags W/CW 1-4 only; central riser labelled 1" DHW', 'PL - 6.29.26.pdf p3-p7 vs p16', '', '', '', 'open (G5)', ''); dn += 1
wcsv('plan_discrepancies.csv', D)
with open(H + 'plan_discrepancies.md', 'w', encoding='utf8') as f:
    f.write('# Plan discrepancies (printed vs derived vs measured), model_export_v10b\n\nEach row: sheet/page and the printed quote. `ruling_source = roy_pm` means the resolution is a PM ruling, not plan-derived. CSV: plan_discrepancies.csv (%d rows). Measured thicknesses: wall_thickness_measured_vs_printed.csv (%d typed wall pieces, both tracks).\n\n' % (len(D), len(W)))
    for r in D:
        f.write('## %s  %s: %s\n- printed: %s | quote: %s | where: %s\n- derived: %s | measured: %s | delta: %s\n- status: %s | ruling: %s%s\n\n' % (r['id'], r['topic'], r['item'], r['printed_value'], r['printed_quote'], r['printed_sheet_page'], r['derived_value'], r['measured_value'], r['delta'], r['status'], r['ruling'] or 'none', ('| ' + r['notes']) if r['notes'] else ''))
print('typed wall pieces', len(W), 'P5 pieces', len(P5), dict(p5s)); print('type summary', tsum); print('box beams', dict(bbc['filed']), dict(bbc['post_co']), bbr); print('discrepancies', len(D))
