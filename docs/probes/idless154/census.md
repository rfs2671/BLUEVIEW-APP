# Ruling 154 census: identifier-less schedules, 588 Boyland (read-only, 2026-10-30)

147 schedule records project-wide; 118 have no column with role=identifier; 12 of those print a tag-like mark in their headers; 6 print two or more distinct tags (the case where every cell is named by every tag).

Bound claims are measured on the gate (attribute intent, answer_is_grounded) on the production-row record set (loc867_out/prod_snapshot.json) plus the one schedule; 'count-shaped' = '<tag>: <n>.' for n in 0..59, 'value' = '<tag> <cell words>: <figure>' for every figure printed in the schedule.

| sheet | schedule | cols x rows | tags in headers | count-shaped claims bound (main -> fix) | value claims bound (main -> fix, of tested) | right / wrong / unconfirmed |
|---|---|---|---|---|---|---|
| T-001.01 | APPLICATIONS TO BE FILED SEPARATELY | 3x3 | S1 | 10 -> 10 | 0 -> 0 of 0 | see notes |
| M-001.00 |  | 5x2 | FT2 | 10 -> 10 | 0 -> 0 of 0 | see notes |
| M-104.00 |  | 7x1 | PTAC-1 | 0 -> 0 | 0 -> 0 of 0 | see notes |
| P-400.00 | WATER BOOSTER SCHEDULE | 9x1 | WBP-1 | 14 -> 14 | 0 -> 0 of 0 | see notes |
| T-001.00 | APPLICATIONS TO BE FILED SEPARATELY | 3x3 | S1 | 10 -> 10 | 0 -> 0 of 0 | see notes |
| GN-001.00 | ENERGY CODE PROGRESS INSPECTION: TR-8 | 2x15 | IIA1 | 0 -> 0 | 0 -> 0 of 0 | see notes |
| A-400.00 | WINDOW SCHEDULE | 6x6 | W1, W2, W3 | 4 -> 4 | 93 -> 85 of 93 | W2: 5 and W3: 2 (count) right (filed set, 5 and 2); 8 value claims wrong (a figure printed under another tag) now refused; the rest bind on the tag's own column (OCR, unconfirmed) |
| A-400.00 | INTERIOR DOOR SCHEDULE | 10x10 | A, B, C, D, E | 56 -> 34 | 25 -> 10 of 55 | 22 count-shaped claims (B/C/E 2,6,7,8,10) wrong: no glyph/QTY source; 15 value claims wrong now refused; rest unconfirmed |
| A-400.00 | EXTERIOR DOOR SCHEDULE | 4x6 | D1, D2 | 0 -> 0 | 38 -> 35 of 38 | 3 value claims wrong (D2 figures printed under D1) now refused; D1/D2 count-shaped already refused by #934 |
| A-500.00 | TABLE | 6x1 | U4, U42, W1, W2, W3, W4, W5, W6 | 104 -> 76 | 0 -> 0 of 0 | see notes |
| A-500.00 | TABLE | 6x1 | P1, P2, P3, P4, P5, P6, U41 | 196 -> 106 | 0 -> 0 of 0 | see notes |
| RCP-001.00 | TABLE | 2x1 | D1, D2, L1, L2, L4, L5 | 0 -> 0 | 0 -> 0 of 0 | see notes |

Notes:
- A-500.00 (two 1-row wall/partition type tables): W1-W6 / P1-P6 are WALL and PARTITION types, not windows; 'W3: 2' binds through them as a wall-type figure. 28 + 90 count-shaped claims flip because the figure is printed under another type's column. Right/wrong not checkable (no counting source); unconfirmed.
- T-001.00/01 (S1 job suffix), M-001 (FT2 unit), P-400 WBP-1 (one tag, the pump's own symbol), M-104 PTAC-1, GN-001 (IIA1), RCP-001 (D1/D2/L1.. luminaire legend): print one tag or tags in a single header; unchanged by the fix (needs >= 2 distinct tags). RCP-001 TABLE prints six tags but bound nothing on the tested claims.
- Of the 118 ID-less schedules, 106 print no tag in their headers (title blocks, revision tables, code tables): no tag to mis-attribute; unchanged.
- Not covered by the 79,821-claim grid: it carries only count-shaped claims, which #934 already refuses; this value-claim census is the residual ruling-151 note (ii).
- Machine-readable: census.json (per-schedule counts, flipped claims). Raw: census_main.json / census_br2.json / schedules_all.json.