# model_export_v10 — framing-detail model (Step 2). Saved by the coordinator from the lane's hand-back.

`verify_v10.py` passes every check on both tracks. v09b untouched. No merge, PR or production access. v10 copies the v09b GLB and appends new node groups; original nodes/ids unchanged, each once. Filed and post-CO are separate files, never summed. Every element row carries source sheet, detail ref, status and position status.

Files: model_filed.glb, model_postco.glb, framing_elements.csv (+ per-track), not_modelled.csv, box_beam_designations.csv/.md, engineer_questions_v10.csv, PM_OPEN_QUESTIONS_sectionJ.md (section J now appended to takeoff_v0/PM_OPEN_QUESTIONS.md; engineer_questions_v10.csv NOT merged into membersize_rev2/engineer_questions*.csv), build_v10.py, verify_v10.py, sw45_panel_check.py, make_box_beam_designations.py, verify_out.txt, glb_validation.txt, work/.

## GLB groups (toggleable)
- L1_wall_assemblies | sheetrock / finish_exterior / studs_track / unbound_walls (sheetrock is its own sub-layer: strip view = toggle the others off)
- L2_box_beams | box_beam_members / label_governed_beams_depth_unknown
- L3_openings | frames / heads / wall_fill_above_opening / wall_fill_below_sill
- L4_floor_panel_joists | floor_panel / joists / over_stair_underlay_unconfirmed
- L5_shear_walls | end_members / top_bottom_members / field_studs / straps / gusset_plates / hold_downs_bound

## S-401 / S-402 as rendered images
- S-401: all wall framing and built-up posts, N.T.S., no dimensions. 1-2 corner ties, 3-4 window load-bearing headers, 5 boxed header connection, 6 three-stud corner, 7 built-up post, 8 rigid clip connector, 9 partition intersection. Nothing floor or roof.
- S-402: 1-3 bearing-wall bridging; 4, 5, 6 floor joist-to-wall connections ("ATTACH PLYWOOD TO JOIST AT 12" O.C." is on these, so plywood is a floor detail); 7 box beam on double stud. No roof or shear-wall detail on either sheet.
- Conflicts with S-102..S-106 note 3 (USG structural panel) and A-302 (metal deck with concrete): engineer question J1.

## Box beams (-54 vs -118)
- -54: S-102 (p6), S-103 (p7), S-105 (p9), S-106 (p10) print "(2) 800S162-54 BOX BEAM U.O.N."
- -118: only S-104 (p8) prints "(2) 800S162-118 BOX BEAM U.O.N."
- Every model beam takes its own sheet's designation; all 31 per track checked. Labelled beams "(2) nSWm": SW undefined, no beam schedule, so outline at top datum only, no solid.
- L2: 31 note-4 beams x 2 = 62 solid members (8 in deep from "800"); 6 label-governed beams x 2 = 12 outlines.

## Counts per layer (filed / post-CO)
- L1: sheetrock 938 / 594; finish_exterior 75 / 83; studs_track 2563 / 1642 (lines). Unbound walls: 55 pieces on 43 walls filed, 191 pieces on 108 walls post-CO. Type layers on 134 filed and 71 post-CO tag-bound walls (every tag-bound drawn wall, none elsewhere).
- L2: 62 members + 12 outlines.
- L3: frames 109 / 106, heads 109 / 106, fill above opening 109 / 106 (header_size_unknown), fill below sill 41 / 42.
- L4: floor panel 30 boxes; joists 330 + 28 in over_stair_underlay_unconfirmed = 358, rule_from_continuity, withheld.
- L5: end members 70; top/bottom members 70 (schedule_merged_cell); field studs 249 lines; straps 84 (42 panels x 2 diagonals); gussets 168 (8 roof plates clash_include=no); hold-downs bound 20.

| status | filed | post-CO |
|---|---|---|
| rule_from_printed_detail | 4474 | 3212 |
| unbound_type | 55 | 191 |
| header_size_unknown | 109 | 106 |
| rule_from_continuity | 358 | 358 |
| schedule_merged_cell | 70 | 70 |
| measured_from_drawing | 56 | 56 |

Full per-sublayer table: verify_out.txt.

## What verify measured
- GLB re-parses, every node referenced once, accessor min/max match data, every v09b node present once with the same mesh.
- CSV bounds match GLB extents for 1937 filed and 1732 post-CO box nodes.
- L1 layers inside their host wall piece along its length (0 violations).
- L3 fill above an opening is the opening's width, starts at the head, ends below wall top; frame width matches schedule width within 0.6 in.
- L2 members inside the level envelope. L4 joists inside the panel extent. L5 straps end exactly on gusset centres; end members inside their shear-wall footprint.
- Openings sit in a gap, not inside a wall piece (v09b cuts walls with a gap at every opening), so "inside host wall" is a gap-distance test: openings within 0.169 ft (filed) and 0.249 ft (post-CO) of their host wall.

## SW 4&5 panel -> measured_from_drawing (CONDITIONAL, see caveats)
sw45_panel_check.py finds 2 X on the SW 4&5 elevation (S-302 p12): upper X x 1748.4-1868.3, y 150.8-290.2 pt; lower X x 1748.1-1868.6, y 493.5-623.4 pt. Overlay work/sw45_overlay.png shows the lower X is the lowest-storey X on the slab hatch = the v09b by-eye "lower X"; the 8 plates and straps were upgraded. Caveats: the by-eye identification had no recorded coordinates (comparison is visual on the overlay); strap box 9.63 ft tall vs printed 10'-0"; v09b is not a git repo, "committed" means kept in the folder. Roy's condition was a committed script whose coordinates match the visual one: matched only visually.

## Corrections to the Step 1 inventory
- A-500 layers were mis-assigned in the text dump (read from the render's dimension strings): P1, not P5, prints the impact-resistant face panel layer and "20 GAUGE MIN." (2 x 5/8 gypsum per side, 3 1/2" stud, 6" total). P5 is 2 x 5/8 on the corridor side, a 1" liner on the shaft side, 2 1/2" CH studs at 20 GA. **P5 prints 3 3/4" total but its printed parts sum to 4 3/4"**: drawn as printed, mismatch stated on every row.
- Measured plan thickness differs from printed: P3 4.00 in vs 3 3/4; W1 10.00 vs 9 1/4; W2 10.99 vs 10 3/4; P2 measures 6-8 in, P5 4-8, P4 8-12 (printed varies). Layers stacked at printed thickness, centred on the measured wall; none overflows the measured wall by more than 0.1 ft.
- Door type G prints "G.C. TO DECIDE". v09b gave it 6'-8"; v10 draws no frame, head or fill for the 15 filed / 16 post-CO G doors.

## Refused or not drawn (not_modelled.csv)
Unbound walls (plain solid only, never bound by thickness); 9 roof beams (unregistered) and 1 beam refused for ambiguous labels, per track; 56 unknown hold-downs (36 no callout at the level, 20 no level labels); 3 roof shear-wall rows not in the v09b model; G doors; 13 post-CO walls with no placed geometry. Not printed, never drawn: blocking, bridging, non-shear straps, stair framing, rim/band, rough opening, header sizes, jamb/king/trimmer/cripple, screws, W3-W6 concrete, EPS/batt thickness beyond the printed 2 in and 2 1/4 in block.

## Assumptions to confirm (flagged on the rows)
- Studs and track: lines only (flange/web not printed); stud layout origin = piece start (not printed); spacing 16 in as printed.
- W1/W2 exterior side = outward by footprint centroid; P5 corridor/shaft side not tied to the plan.
- Shear-wall: end members drawn as SW-thickness squares (member width not printed); top/bottom member depth 10 in read from "10J12" as "800" means 8 in; SW field studs start at the inner face of the end member (not printed).
- Box-beam members: each is half the measured 4 in plan band.
- W1 windows: tag-to-schedule-size pairing unverified (inventory c2).
- Floor panel extent: union of drawn joist-bay outlines (no floor outline otherwise printed).
- Straps: once per diagonal; printed "each side of panel" means 2 per diagonal.
- Engineer questions: J1 floor build-up conflict; J2 note 9 ("OPENING TO HAVE JOISTS ONEITHER SIDE OF IT."), 28 joists per track over the stair underlay.


---
# v10.1 (folder model_export_v10b): Roy's 9 PM rulings + coordinator corrections 1-11, applied to a COPY of v10 (v10 and v09b untouched)
Build: apply_v10b.py, make_discrepancies_v10b.py, verify_v10b.py (88 PASS, 0 FAIL; GLBs re-parse, every original v09b node and id once, mesh index of every original node unchanged). Scripts committed on branch feat/model-v10-scripts (backend/scripts/plan_reader_model_v10/), pushed, no PR. Every row/node changed by a PM ruling has `ruling_source = roy_pm` (columns ruling_source, ruling_note, size_pairing, quantity_label, count_release added to framing_elements*.csv; GLB extras carry the same keys; v09b-origin rows in v09b_rows_ruling_overrides.csv).

## Rulings
1. H1 closed (gas change = amendment; 1970 SF post-CO only; filed 2112/11): PM_OPEN_QUESTIONS.
2. A-600: answer on every stair node (`a600_answer`), core stair basis label "typical detail (A-302 detail 11)"; 20 core flights (10 per track) + 8 apartment.
3. Gas-change roof stair vs A-105.00: gas governs; note on the MEZZ>ROOF flight nodes; difference recorded once (plan_discrepancies D11); geometry unchanged (roof unregistered).
4. Floor panel = note 3 (3/4" USG): 30 panel boxes per track carry roy_pm; metal deck + concrete = stair landing only; S-402 plywood applied to nothing; J1 RESOLVED in engineer_questions_v10.csv (status column) and PM_OPEN_QUESTIONS.
5. P5: layers 4 3/4" (12 layer rows per track, roy_pm); printed 3 3/4" = discrepancy D01; measured per piece in p5_pieces.csv.
6. FLOOR_4 stacks (3 per track: tags CW-2 x2, W-2 x1 on P-103): status label_corrected_by_pm, printed tag retained, pm_corrected_tag/system stored (interpretation: the 2 circles printed CW-2 sit on the DHW pipes so their corrected tag is W-2/hot; the circle printed W-2 sits on the DCW pipe so its corrected tag is CW-2/cold, following P-102), no geometry change.
7. Apartment stairs 4A-4D: status "interior stair, field-measured", clash_include=no, structure_count_include=no, treads_drawn=none; I1 closed.
8. Hold-downs: 50 placed unknown nodes per track + 6 unplaced (56 in not_modelled) labelled "count not printed".
9. Joist sheets (title blocks read, ST - 7.29.26.pdf): S-102.00 p6 "2ND FLOOR FRAMING PLAN"; S-103.00 p7 "3RD FLOOR FRAMING PLAN"; S-104.00 p8 "4TH FLOOR FRAMING PLAN"; S-105.00 p9 "MEZZANINE FLOOR FRAMING PLAN" (yes, the mezzanine framing plan is S-105); S-106.00 p10 "ROOF FRAMING PLAN" and "BULKHEAD ROOF FRAMING PLAN". The 358 joists = S-102 104 + S-103 104 + S-104 106 + S-105 44 (per track). Roof/bulkhead (S-106) are not in the 358. The gas-change set has no structural sheet, so where roof/bulkhead structure differs from S-106 is NOT determinable (only the roof stair location differs, G2): flagged. J2 and G6 (first-joist position, stair hole) stay OPEN.

## Corrections
1. Thickness offsets: thickness_offset_test.md (stroke width explains 2 of 6 type groups only; finish layer does not; whole-inch rounding-up of the printed value fits all 5 typed groups). P5 measured: 2 walls per track at 4.00 in (+0.25 vs 3 3/4, -0.75 vs 4 3/4), 2 stub pieces per track (8 x 8, 8 x 10 in) matching neither.
2. Box beams 47 per track = 31 note-4 solid + 6 label-governed outlines + 9 roof (unplaced/unscaled, not drawn) + 1 refused for ambiguous labels (filed plan_structural:6ae49c0d0b73eb6c86645cdd, post-CO ...645ec2, S-102 FLOOR_2). The 2 headers per track (S-102 header, S-104 header "(2) 800S162-118") are class struct_header, NOT among the 47, not drawn as L2 members; listed in not_modelled.csv. By id: box_beam_reconciliation.csv.
3. J1 resolved, J2 open (above).
4. Door G: no frame/head/fill; visible marker layer `door_G_undefined` (15 markers per track = the placed G doors; post-CO has 1 further G door unplaced); listed in not_modelled.csv.
5. Studs/track/SW field studs: status layout_assumed, count_release WITHHELD, no stud_count in GLB extras or CSV (verify prints "count WITHHELD"); a CSV row is one drawn line, not a stud count.
6. Window tag-to-size pairing: size_pairing_unverified on all window opening rows (164 filed / 168 post-CO rows), WITHHELD from takeoff; w1_pairing_trace.csv. Symbol width equals the type width in 36/36 W1 and 5/5 W2 (filed), but tag text is >45 pt from every symbol and the nearest tag differs from the row tag for 10/36 W1 and 3/5 W2.
7. SW 4&5: measured_from_drawing kept; see SW45_decision.md.
8. Stairshaft: the 4 REMOVED bearing-wall rows per track (x 15.32-28.99, y 17.45, F2..MEZZ) are present as struct_bearing_wall nodes with geometry in both GLBs (8 of 8). NOTE: stairshaft v2's ADDED walls/doors are NOT applied in the v10b GLB (v10b is v10 plus rulings; the shaft derivation was not asked to be merged).
9. Joist label: all 358 per track "at printed 16 in spacing, minimum" (S-002.00 p3: spacing shown is maximum permissible); in framing CSV, GLB extras, joists_by_bay.csv.
10. plan_discrepancies.md/csv (24 rows) and wall_thickness_measured_vs_printed.csv (473 typed wall pieces, both tracks): P5 is the only assembly whose printed total differs from its printed parts (P1, P2, P3, P4 leaf, P6, W1, W2 sum correctly).
11. pitch_v2/ (see pitch_v2/README.md).

---
# v10c (folder model_export_v10c): Roy's v10c rulings 1-7 on a COPY of v10b (v10b untouched)
Build apply_v10c.py; check verify_v10c.py (98 PASS, 0 FAIL = 88 + 10 new; verify_out_v10c.txt, re-run after the session break). No node added/removed vs v10b, mesh indices equal, GLBs re-parse, every v09b id once. FACT = printed; INFERENCE = geometry/convention. Filed and post_co never summed.

## 1. Stairshaft v2 merged (stairshaft_v2_merge.csv; INFERENCE from geometry). Membership only; extras stair_shaft_v2*, roy_pm; 10 core stair nodes per track carry shaft_v2_member_ids.
Per core (ST-A+ST-B share it): **7 shaft walls per level in BOTH tracks** (35 per track = 5 levels x 7; stairshaft_v2_walls_per_level_v11b.csv; each post_co shaft wall pairs with a filed one, stairshaft_v2_shaft_wall_pairs_v11b.csv). The merge CSV `change` column (kept / ADDED / REMOVED) is a membership change versus the v09b shaft list, NOT a count of shaft walls, and the totals of that column are not reported as shaft-wall counts [v11b: the earlier per-track ADDED totals are withdrawn]; 6 doors added per track, 4 bearing-wall rows per track REMOVED from the list (kept as nodes).

## 2. Thickness round-up test, filed A-100..A-104 (thickness_roundup_test.py/.csv/.md; tol 0.02 in, rule = ceil(printed))
Per type fit/pieces: P1 35/35, P2 85/86, P3 70/70, W1 41/41, W2 34/34, P5 2/4. Per floor: F1 57/60, F2 58/58, F3 58/58, F4 56/56, MEZZ 38/38 (A-101..A-104: 210/210). 3 misses, all A-100 FLOOR_1: two P5 stubs (8.0 in) and one P2 piece (...645b09, 8.0 in). P1/P2 do not discriminate (whole inches); P3, W1, W2 do; nearest-inch fails W1. P5 body 4.00 = 3 3/4 rounded up; NOT corroboration of 4 3/4.
v10b P5 (build_v10.py 143-155): 4 layers at printed thickness (sum 4.75 in) centred on the measured centreline, not scaled to the 4.00 in host: 0.375 in overflow per face. PROPOSAL (not applied): printed assembly thickness centred on the drawn centreline for tag-bound walls; P5 needs 3.75 vs 4.75 from Roy.

## 3. Windows by symbol width (window_type_by_symbol_width.csv): type_by_symbol_width + RELEASED where symbol width = row type width (W1 60, W2 48, W3 36 in). INFERENCE.
Filed W1 36, W2 5 bound, W3 roof 45.1 in mismatch (no rows). Post_co W1 36, W2 5 bound; W3 roof 36.0 match but no rows; 1 W1 withheld (...645893, 58.0 vs 60) = 4 rows. 4 rows per window: filed 41x4 = 164 all released; post_co 42x4 = 168 (164 released, 4 withheld).

## 4. Gussets: 168 STANDS (gusset_mapping_v10c.csv). 20 boxes = 6 elevation columns x (top, cut middle storey, bottom) + 2 DETAIL A boxes. 12 boxes (top+bottom) cover the 16 panels (SW 6+7 and SW 4+5 share one elevation each); box 20 now vector-found. "Other 4" is 8: mid boxes 2,5,8,12,16,19 (cut typical storey X, 6.77 ft) and boxes 10, 14 (DETAIL A, 12.00 and 15.17 ft). 168 = 16 drawn + 26 schedule panels, x4. Caveat: 4 plates/panel is Roy's reading.

## 5. S-102 beam ...645cdd refused: one 32.44 ft row (x 36.585-69.028 ft, grid C, ST p6) with labels "(2) 8SW14" (left) and "(2) 16SW10" (right), SW 1 between; two designations, no printed split, SW undefined. INFERENCE: two beams meeting at SW 1.

## 6. Pitch (pitch_v3/): "clipped" wording corrected (pitch_v2, pitchmap/REPORT.md). Lowest points (MIN, derived_from_printed, provisional): F1 42.1515, F2 52.1612, F3 61.9758, F4 72.1568, MEZZ 81.9441 (all-1/4 assumption). BT-1 on P-301 (PL p17): displayed pt x 371.3-392.0, y 590.0-599.3. Offset (25.51, 66.04) CONFIRMED independently (2-D stroke overlap 75-80% vs 5-9% at the 1-D alias -143.5). KS-1 is the only KS type (key notes md5-identical on PL p8-p15; P-301; P-400 row KS): bare F3 KS bound as KS-1, status tag_printed_without_number_only_KS_type_in_key. Other bare leaf tags (OCR + eye on 9 crops, not all 52): F1 S-4 BT/KS/WC, F3 S-2 and S-1 FD, MEZZ S-3 FD.

## 7. Gas roof: not_modelled row per track. Gas p2 prints no sheet number (A-105.01 is a derived label); only AR - 8.18.26 p7 (ignored file) prints A-105.01: no live page does.

---
# v11 (folder model_export_v11): Roy's K1-K4 rulings + ceiling plane, sloped sanitary runs, heads at the ceiling plane, tops audit. Built on a COPY of v10c (v10c, v10b, v10, v09b untouched)
Build: apply_v11.py (reads v10c, writes v11; pitch_v4/make_pitch_v4.py for K3/K4). Check: verify_v11.py = **58 PASS, 0 FAIL** (verify_out_v11.txt): both GLBs re-parse from bytes, every node referenced once, accessor min/max == data, every v09b element id once, every v09b and v10c node keeps name/index/mesh (v11 only appends: 169 nodes filed, 63 post_co), CSV bbox/z == GLB extents for all new rows, 0 L1 geometry changes vs v10c. The first run of the checks FAILED 5 times (my K1 sum test left out the stud layer; the 3 in FD run was drawn 3 in deep at the stack end instead of the pitch convention 4 in; a head check counted the unplaced ROOF heads) and passed after those were fixed. Filed and post_co are never summed. No production access, no clash wiring (every new L6 row clash_include = no), no merge/PR. ruling_source = roy_pm on every row/node a ruling changed (all L1 rows, the K2 outlines, every L6 row).

## Per-item verdicts
- **K1 DONE.** Tag-bound walls: layers = printed assembly thickness centred on the drawn centreline, status `printed_assembly` (layer rows: filed 929, post_co 641; P1/P2/P3/W1/W2/P5; verified per host: sum of layers = printed total, union centre = wall piece centre within 0.01 ft). **P5 = 4.75 in (roy_pm)**; printed 3 3/4 stays logged plan discrepancy D01 (named on every P5 row). Unbound walls keep drawn thickness, label `drawn thickness, rounded-up upper bound` (filed 55 / post_co 191 pieces, status unbound_type unchanged). New column thickness_basis; the 120 / 65 original v09b typed wall nodes carry printed_assembly_in in extras (their solid keeps the measured plan thickness). **Exception at v11: P4** (printed assembly varies 8-12 in, no single printed value; 370 filed / 154 post_co rows kept the drawn thickness) [v11b: P4 = chase wall, status chase_wall_variable, see the v11b section]. No L1 geometry changed (v10 already drew the layers at printed thickness, centred; K1 is the rule plus status/labels). Table: wall_thickness_basis_v11.csv.
- **K2 DONE.** Beam ...645cdd (filed) / ...645ec2 (post_co), S-102 FLOOR_2, grid C: ONE whole-row outline (2 member outlines, x 36.585-69.028 ft) in the nSWm class `label_governed_beams_depth_unknown`, designation "(2) 8SW14 | (2) 16SW10", NO split; removed from not_modelled; label-governed outlines now 12 -> 14 per track. Engineer question **J3** (what does "SW" mean in 8SW14 / 16SW10, also 10SW10) added in engineer_questions_v11.csv, OPEN.
- **K3 DONE.** MEZZANINE lowest point 81.9441 (provisional, all-1/4 assumption); 82.0425 (printed tier) recorded beside it (pitch_lowest_v4.csv, ceiling-plane extras `printed_tier_alt_navd_ft`).
- **K4 DONE [BT rule changed in v11b, see the v11b section] (checked on all 52 leaves by eye on 4x crops, not 9; OCR alone missed 4 of the 9 bare tags).** Key notes read from the render (PL - 6.29.26.pdf p8-13; P-201..P-205 key-note block md5-identical, P-200 same text): note 1 WC-1 (3 in); note 2 KS-1, LAV-1, LAV-3, SH-1, SS-1, MS-1 (2 in); note 3 FD-1 (3 in); notes 4, 5 WMB-1, EDF-1. **KS: exactly one type (KS-1). WC: exactly one (WC-1). FD: exactly one (FD-1). BT: ZERO (BT-1 exists only on the P-301 riser diagram, not in any key note) -> not bindable by the rule.** Bare tags found, 9 of 52 (P displayed pt bbox; A-frame = + 25.51, 66.04; all in pitch_v4/leaf_tag_census_v4.csv):
  - F1 (P-201): S-1 KS (1120.4, 582.9)-(1127.5, 589.0) [numbered KS-1 also in the crop]; S-4 BT (1629.2, 760.0)-(1637.2, 767.5); S-4 WC (1642.1, 843.6)-(1650.0, 849.8); S-4 KS (1570.0, 846.9)-(1579.4, 855.0)
  - F3 (P-203): S-1 KS (1210.4, 411.6)-(1217.5, 418.0); S-1 FD (1089.6, 433.4)-(1097.6, 440.9); S-2 KS (1226.2, 1021.8)-(1235.9, 1029.8); S-2 FD (1089.3, 1005.7)-(1097.7, 1013.5)
  - MEZZANINE (P-205): S-3 FD (1464.9, 619.7)-(1471.8, 625.4)
  - FLOOR_2 and FLOOR_4: none. Also seen, NOT among the 52 leaves (no run mapped): two bare BT on P-201 at (1073.3, 743.9) and (1628.1, 694.5).
  - **Bound by family: 8** (KS x4, WC x1, FD x3; status `tag_printed_without_number_only_<KS|WC|FD>_type_in_key_notes`). **Refused: 1** at v11 (F1-S-4 BT, tag_status `bare_BT_not_bound_family_not_in_key_notes`) [v11b: ACCEPTED as BT-1 by Roy ruling L2, status `tag_printed_without_number_only_BT_type_on_plans`, drop size 2 in unchanged, no level value changed].
  - **Controlling run per level (minimum used) and its tag:** F1 F1-S-1-BT-1 numbered; F2 F2-S-3-BT-1 numbered; F3 F3-S-2-KS-1 **bare, bound as KS-1**; F4 F4-S-3-BT-1 numbered; MEZZ MZ-S-3-FD-1 **bare, bound as FD-1**. Headline-scenario controllers: F1 is F1-S-4-BT-1, a BARE BT (bound as BT-1 in v11b by ruling L2); its own minimum (42.163) is above the F1 level minimum 42.1515, so the F1 value does not depend on it. Levels: F1-F4 `settled_after_K4`; MEZZ stays `provisional` (K3). Lowest points unchanged: 42.1515 / 52.1612 / 61.9758 / 72.1568 / 81.9441.
- **Ceiling plane DONE:** 5 per track (L6_ceiling_services | ceiling_plane), z = the level lowest point (status derived_from_printed; MEZZ provisional), footprint = bbox of the level walls (extent not printed), thin 0.02 ft box.
- **52 sloped sanitary runs DONE (both tracks, same paths: P sheets identical, stack positions differ <= 0.001 ft):** toggleable `sanitary_runs_sloped`; top at structure underside at the high end (leaf; flag `convention_ceiling_drop`, not printed), slope 1/8 in/ft for 3 in and larger, 1/4 in/ft for 2 in and smaller (P-001 note A; branch by drop size, trunk 4 in at 1/8 per P-301), row status derived_from_printed; the trunk-1/4 bracket lowest point is stored per run. The segment reaching the stack is drawn at nominal 4 in so the lowest point equals pitch_v4; Path = stroke polyline (chords for arcs; F1-S-1-KS-1's polyline is 17% longer than its stroke length, the vertical profile is scaled to the stroke length). Per level 7/16/16/12/1. Tag status of the 52: numbered 43, bound by family 8, bare-unbound 1.
- **Sprinkler heads at the ceiling plane DONE (filed only: 106):** placement copies at z = level ceiling plane, status convention_ceiling_drop, clash no, quantity_label NOT_A_COUNT (the 112 original head rows stay the count basis and are untouched). REFUSED: 6 ROOF heads (roof unregistered, no ceiling). post_co: the v09b post-CO model has 0 sprinkler rows, nothing placed.
- **Duct/pipe tops at structure underside: ALREADY TRUE in v09b; audited, nothing added.** tops_at_structure_underside_v11.csv: sprinkler_pipe 106 filed, mech_exhaust_fan 36 per track, all with z top == structure underside and status convention_ceiling_drop, 0 mismatches. Not applied: 7 ROOF sprinkler pipes (unregistered). No duct class exists in the model (exhaust fan, PTAC, unit heater, fan are equipment), so no duct run was created (not_modelled row).
- **Stairshaft [corrected in v11b]: the post-CO "extra" walls are the SAME shaft walls as filed** (stairshaft_same_walls_v11b.md): 7 shaft walls per level in both tracks. post_co FLOOR_4 ...c2d and MEZZ ...c4d (untyped, three pieces) are the filed east shaft walls ...b76 (P1) and ...b93 (P1); the middle piece is identical, two outer pieces per row lie outside the shaft window and ride along because membership is by whole row. No wall is extra.

## Counts per layer / status (v11 additions; L1-L5 unchanged except as above)
| layer | sublayer | status | filed | post_co |
|---|---|---|---|---|
| L6_ceiling_services | ceiling_plane | derived_from_printed | 5 | 5 |
| L6_ceiling_services | sanitary_runs_sloped | derived_from_printed (high end z = convention_ceiling_drop) | 52 | 52 |
| L6_ceiling_services | sprinkler_heads_at_ceiling | convention_ceiling_drop | 106 | 0 |
| L2_box_beams | label_governed_beams_depth_unknown | rule_from_printed_detail | 14 (+2) | 14 (+2) |
| L1 | finish_exterior + sheetrock layers (non-P4) | printed_assembly | 929 | 641 |
| L1 | sheetrock layers (P4) | rule_from_printed_detail at v11; chase_wall_variable in v11b | 84 | 36 |
| L1 | unbound_walls | unbound_type | 55 | 191 |
Full per-sublayer table: verify_out_v11.txt (v11b: verify_out_v11b.txt).

## Refusals (with reason)
[v11b: BT bare tag F1-S-4 and P4 are no longer refusals, see the v11b section] BT bare tag F1-S-4 (not in any key note); P4 under K1 (no single printed thickness); 6 ROOF heads and 7 ROOF sprinkler pipes (roof unregistered); post_co heads (none in the model); duct runs (no duct class, none to create); storm/vent/below-slab/roof/bulkhead and 43 non-fixture stroke networks (pitchmap/refused.csv, one summary row per track in not_modelled.csv). None of the bare tags changes a level value.

## Files
pitch_v4/ (make_pitch_v4.py, bare_tag_locate.py, leaf_tag_census_v4.csv, key_note_families_v4.csv, pitch_runs_v4.csv, pitch_lowest_v4.csv, pitch_run_paths_v4.json, unmapped_bare_tags.json, keynotes/ renders, bare_tag_locate.json); ceiling_plane_v11.csv, sanitary_runs_sloped_v11.csv, sprinkler_heads_at_ceiling_v11.csv, tops_at_structure_underside_v11.csv, wall_thickness_basis_v11.csv, engineer_questions_v11.csv, stairshaft_postco_extra_walls.md, PM_OPEN_QUESTIONS_sectionL_v11.md, apply_v11_summary.json, framing_elements*.csv, not_modelled.csv, model_*.glb.
---
# v11b (folder model_export_v11b): Roy 2026-11-03 tasks 1-6 on a COPY of v11 (v11 untouched; only scripts are committed)
Build: pitch_v4/make_pitch_v4.py (BT rule, re-run) + apply_v11b.py (reads v11, writes v11b) + reconcile_walls_v11b.py + p4_chase_report_v11b.py. Check: verify_v11b.py = **91 PASS, 0 FAIL** (verify_out_v11b.txt): both GLBs re-parse from bytes, every node referenced once, accessor min/max == data, every v09b element id once, every v11 node keeps name/index/mesh (v11b only appends: 21 filed / 9 post_co chase_cavity nodes and one sublayer group per track), no pre-existing L1 row changed geometry, level values identical to v11. Control run: changing one P4 flag in p4_chase_clash_flags_v11b.csv made 3 checks FAIL (restored, 0 FAIL). Filed and post_co never summed; no production access; no clash wiring; no merge/PR. ruling_source = roy_pm on every changed row/node. Checks that were true by construction are dropped from the evidence (item 5).

## Item verdicts
- **1. Wall counts RECONCILED (wall_count_reconciliation_v11b.csv: one row per wall id, both tracks; wall_count_summary_v11b.csv).** The two pairs count different things.
  - "43 filed / 115 post-CO" = WALLS (class wall rows in elements_*.csv) whose `tag` is empty (no wall-type tag P1..P5 / W1 / W2). Source: walltype_read/untyped_filed.csv (43) and untyped_postco.csv (115); the id sets are IDENTICAL to the untagged walls of v09b (asserted in reconcile_walls_v11b.py).
  - "55 / 191" = PIECES (rectangles of `footprint_pts_ft`; one L1 `unbound_walls` row, status `unbound_type`, per piece) of the untagged walls that HAVE placed geometry. One wall can have several pieces.
  - "134 of 177 filed tag-bound" = 134 tag-bound of 177 filed wall rows (43 + 134 = 177). Post-CO has 192 wall rows = 115 untagged + 77 tag-bound.

| quantity | filed | post_co |
|---|---|---|
| wall rows (class wall) | 177 | 192 |
| walls with NO type tag (the 43 / 115) | 43 | 115 |
| of those drawn (placed geometry) | 43 | 108 |
| of those ROOF, no placed geometry (unscaled, excluded) | 0 | 7 |
| pieces of the drawn untagged walls = L1 unbound_walls rows (the 55 / 191) | 55 | 191 |
| walls with a type tag | 134 | 77 |
| of those drawn with type layers (the "134 / 71") | 134 | 71 |
| of those ROOF, no placed geometry | 0 | 6 |
| of the tagged: P4 (chase wall; tag-bound, never unbound) | 14 | 6 |

  Reconciliation: filed 43 walls -> 55 pieces (+12 from multi-piece walls); post-CO 115 walls - 7 ROOF walls with no geometry = 108 drawn walls -> 191 pieces (+83). By level, untagged drawn walls / pieces: filed F1 8/9, F2 10/12, F3 10/12, F4 10/14, MEZZ 5/8; post_co F1 8/9, F2 12/16, F3 32/60, F4 30/57, MEZZ 26/49. 13 post-CO wall rows are not drawn (7 untagged + 6 tagged, all ROOF). The P4 class makes no difference to either pair (it is tagged); no other class differs. The earlier phrase "wall pieces untyped by tag" mixed the two units: it is 43 / 115 walls and 55 / 191 pieces.
- **2. Why the post-CO model has NO sprinkler rows (facts; no proposal to merge tracks).**
  - The file `SP 4th floor after CO - 5.6.25.pdf` exists: 1 page, SP-003.00 "FOURTH FLOOR ALTERNATE SPRINKLER PLAN", DOB date 6/17/2024; the sheet prints 588 THOMAS S BOYLAND ST and the engineer block 128 Museum Village Rd, Monroe NY (note kept). C:/Users/asddd/boyland-pdfs/SP 4th floor after CO - 5.6.25.pdf (2592 x 1728 pt, 3543 vector drawings).
  - ROLE REGISTRY: inventory_roles/file_roles_v2.md first listed it QUARANTINED; Roy ruled 10-30 night "SP-003 = POST_CO sheet, belongs to 588" (HANDOFF_coordinator.md, "Roy rulings 10-30 (night)"); the correction note in file_roles_v2.md says POST_CO, not a replacement of SP-003.00. The filed sprinkler set is `SP - 6.24.26.pdf` = FILED_ORIGINAL (SP-001..004.00). The post-CO file is NOT ignored or excluded.
  - PLAN INDEX (role_prs/marks/dump.json, production dump of 2026-10-31): that page is indexed as SP-003.00 with `superseded_by` = the SP 6.24.26 file (a stale cross-track mark). The planned console step (PUT drawing_track = post_co, then the AR 8.18.26 ignore, which recomputes the marks) is in role_prs/SP003_EFFECT.md; whether Roy ran it is not visible from the files here (no production access in this lane). Pass 12's read-back (pass12/READBACK.md) lists "0 glyph rows from SP 4th floor".
  - POST-CO TRACK DEFINITION: backend/server.py `_glyph_track_pages` (~L64767): a non-filed track = its OWN current pages + the filed track's MECHANICAL (M) pages that pair with its A plans. No sprinkler page is added. SP003_EFFECT.md section (a) lists every pass stage selector (pair_plan_sheets A-/M-, run_stacks P-, structural S-, roof drains P-, door schedules, M-/A- schedule records): SP-003.00 is selected by none; expected row delta 0 in every collection, both tracks.
  - THE SPRINKLER ROWS NEVER CAME FROM THE PASS: the 228 filed sprinkler rows (112 heads, 113 pipes, 3 excluded head candidates) come from the offline extraction sprinkler_x/ (model_sprinkler_elements.json) that read ONLY `SP - 6.24.26.pdf` p2-4 (sprinkler_x/REPORT.md header), merged into the FILED export only (model_export_v05/levels_and_reconcile_v05.py: "Post-CO has no sprinkler rows (the sprinkler set SP 6.24.26 is filed-only)"; model_export_v09b/README.md: filed 1,308 = 1,080 + 228 sprinkler, post-CO 1,107). elements_postco.csv = model_c/model_postco.json (the pass's post_co track), 0 sprinkler rows.
  - The SP 5.6.25 page was never extracted by any lane (sprinkler_x names SP-003 only as a page of the 6.24.26 file, its FLOOR_3 / FLOOR_4 plans). So: sprinkler rows were extracted for the filed track only; the post-CO page is a registered POST_CO file that no pass stage reads and no extraction lane has read.
- **3. BT-1 ACCEPTED for bare BT tags (Roy L2).** pitch_v4/make_pitch_v4.py edited and re-run (pitch_run_paths_v4.json byte-identical to v11). F1-S-4-BT-1 (P-201, P displayed pt 1629.2, 760.0): tag_status_v4 `bare_BT_not_bound_family_not_in_key_notes` -> **`tag_printed_without_number_only_BT_type_on_plans`**; bind result "BOUND_by_ruling (roy_pm L2)"; bound type BT-1 (P-301.00 riser diagram, 2 in; drop size unchanged). Carried into pitch_runs_v4.csv, pitch_lowest_v4.csv (F1 headline-controller text), leaf_tag_census_v4.csv, sanitary_runs_sloped_v11.csv (2 rows, one per track), the framing rows (designation + F1 ceiling-plane note) and the GLB extras of sanitary_run:{filed,post_co}:F1-S-4-BT-1 (+ `bt_ruling_v11b`). Verified: pitch_runs_v4 differs from v11 in 1 row and only in tag_status_v4 / bind_result_v4 / bound_type_v4; the five level values 42.1515 / 52.1612 / 61.9758 / 72.1568 / 81.9441 and set_status (MEZZ still provisional) are identical to v11; no old BT refusal text is left in any CSV or GLB. Bare tags now: 9 of 52, all bound (KS 4, FD 3, WC 1 by family; BT 1 by ruling), 0 refused. Two further bare BT on P-201 at (1073.3, 743.9) and (1628.1, 694.5) have no run mapped, so no row changes (pitch_v4/unmapped_bare_tags.json).
- **4. Stairshaft reporting CORRECTED.** 7 shaft walls per level in BOTH tracks (35 per track). Pairing by footprint overlap (stairshaft_v2_shaft_wall_pairs_v11b.csv, 70 rows, one-to-one on every level): every filed shaft wall is covered 1.00 by its post_co counterpart (35 of 35); post_co F4 ...c2d and MEZZ ...c4d are the filed ...b76 / ...b93 (their outer pieces ride along; covered 0.85 / 0.69 by the filed row). The `change` column of stairshaft_v2_merge.csv is a membership change vs the v09b shaft list, not a wall count: added columns `change_means`, `counterpart_wall_id_other_track`, both overlap fractions and `shaft_walls_this_level_this_track` (= 7). New stairshaft_v2_walls_per_level_v11b.csv; stairshaft_same_walls_v11b.md replaces stairshaft_postco_extra_walls.md (deleted in v11b); the REPORT lines that compared per-track ADDED totals and spoke of "2 extra walls" are rewritten; the 35 shaft wall nodes per track carry `stair_shaft_v2_counterpart_other_track`. Side finding: in the post-CO plan the same shaft walls are untyped where filed has P1 (post_co tag differs from its filed counterpart: F2 2, F3 4, F4 4, MEZZ 4 of 7), which is part of why post-CO has unbound pieces (item 1).
- **5. DONE.** The statement that no sloped run falls below its level's ceiling plane is removed from the REPORT evidence and from the verify check (it holds by construction: the ceiling plane is the minimum over the runs; apply_v11.py keeps an assert as a build guard, not as evidence).
- **6. P4 CHASE WALL (roy_pm, L3).**
  - L1: each P4 piece keeps its drawn thickness (8.0 / 10.0 / 12.0 in; filed 21 pieces on 14 walls, post_co 9 pieces on 6 walls; geometry unchanged). The 4 face layers per piece keep the PRINTED 5/8 in (2 layers per face, A-500.00 p24, AR - 3.28.25.pdf) and take status **chase_wall_variable** (84 filed / 36 post_co rows; was rule_from_printed_detail) with the basis "drawn thickness is an UPPER BOUND; printed overall thickness VARIES". NEW explicit **chase_cavity** node and row per piece (21 filed / 9 post_co; sublayer `LAYER L1_wall_assemblies | chase_cavity`): cavity = drawn thickness - 2.5 in (5.5 / 7.5 / 9.5 in); faces + cavity = drawn thickness checked on every piece. The stud/track rows (286 filed / 118 post_co) keep layout_assumed (their counts stay withheld) and carry the basis text; the original v09b P4 wall nodes carry `chase_wall_status`. wall_thickness_basis_v11.csv P4 row updated. No single thickness value invented.
  - CLASH RULE (flags only, NOT wired): p4_chase_clash_flags_v11b.csv columns clash_include (`no` = fully inside, excluded; `yes_flag_p4_boundary` = crosses the chase boundary; `as_before` otherwise) + clash_exclusion_reason + p4_relation + p4_piece; new framing columns clash_p4_relation / clash_exclusion_reason on the sloped-run rows (their clash_include stays `no` = unwired); extras `clash_p4_relation`, `clash_include_p4_rule`, `clash_exclusion_reason` on the stack, sloped-run and sprinkler-pipe nodes. No duct class exists, so no duct row.
  - CHECK, 127 stacks per track (same-level plan footprint; p4_chase_check_v11b.md lists the stacks by level, p4_chase_summary_v11b.csv and the flags CSV list every id):

| stacks (127) | fully inside P4 | crosses boundary | outside P4 | no tag-bound P4 on level | no position |
|---|---|---|---|---|---|
| filed | **72** (F1 2, F2 16, F3 20, F4 19, MEZZ 15) | 2 (F4 V-2, MEZZ V-2) | 41 | 5 (BELOW_SLAB) | 7 (6 ROOF + 1 unplaced F1 S-4) |
| post_co | **18** (F1 2, F2 16) | 0 | 26 | 76 (5 BELOW_SLAB + F3 24, F4 24, MEZZ 23) | 7 |

  Post-CO caveat: the post-CO plan draws the F3, F4 and MEZZ shaft walls WITHOUT a type tag (item 4), so no P4 piece exists there and 71 stacks cannot be tested; 18 is a floor, not a comparison with filed.
  - Sloped sanitary runs (52 per track; pipe outline at its widest, 4 in): **0 fully inside** in either track. Filed: 49 cross a P4 boundary (F1 4, F2 16, F3 16, F4 12, MEZZ 1), 3 outside (F1). Post_co: 20 cross (F1 4, F2 16), 3 outside (F1), 29 on levels with no tagged P4 (F3 16, F4 12, MEZZ 1). Every run starts at a fixture outside the chase and ends at a stack inside it, so each one crosses.
  - Sprinkler pipes (filed only, 113 rows): **0 fully inside**, 10 cross a P4 piece (FLOOR_1:13, 17, 20; FLOOR_2:2, 3, 4; FLOOR_3:2, 3, 4; MEZZANINE:11), 96 outside, 7 ROOF with no position. Post_co has no sprinkler rows (item 2). The row bboxes are the extraction's piece rectangles (length UNVERIFIED, position provisional), so the 10 mean "touches a P4 piece", not a measured crossing.
  - L2 and L3 of PM_OPEN_QUESTIONS_sectionL_v11.md are resolved (section N appended to the copy in this folder; the shared takeoff_v0/PM_OPEN_QUESTIONS.md is not touched).

## Counts (v11b, framing rows)
filed 5323 rows (v11 5302 + 21 chase_cavity), post_co 4076 (4067 + 9). Status changes: chase_wall_variable 105 filed (84 faces + 21 cavities) / 45 post_co (36 + 9). Everything else as v11; withheld (layout_assumed) counts unchanged.

## Files (v11b additions)
apply_v11b.py (+ apply_v11b_stdout.txt, apply_v11b_summary.json), verify_v11b.py (+ verify_out_v11b.txt), reconcile_walls_v11b.py, p4_chase_report_v11b.py, wall_count_reconciliation_v11b.csv, wall_count_summary_v11b.csv, p4_chase_clash_flags_v11b.csv, p4_chase_pieces_v11b.csv, p4_chase_summary_v11b.csv, p4_chase_check_v11b.md, stairshaft_same_walls_v11b.md, stairshaft_v2_shaft_wall_pairs_v11b.csv, stairshaft_v2_walls_per_level_v11b.csv, pitch_v4/ (BT rule), model_filed.glb, model_postco.glb, framing_elements*.csv.
