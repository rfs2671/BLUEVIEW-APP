# P4 chase check (v11b, Roy ruling L3, roy_pm 2026-11-03)

Footprint test in plan view on the SAME level: the P4 pieces are the tag-bound P4 wall pieces of that track (filed: 14 walls / 21 pieces; post_co: 6 walls / 9 pieces, F1 and F2 only: the post-CO plan draws the F3, F4 and MEZZ shaft walls WITHOUT a type tag, so they are not P4 here). Stack = its drawn circle (r from the v09b bbox, 0.126 ft); sloped run = centreline polyline + widest pipe (4 in); sprinkler pipe = its row bbox. `fully_inside_p4` = whole footprint inside the union of the level's P4 pieces (1e-6 ft); `crosses_p4_boundary` = touches but is not inside; `outside_p4`; `no_p4_on_level` (BELOW_SLAB, or a level with no tag-bound P4 piece); `no_xy` (no placed position: ROOF and the 1 unplaced F1 S-4 stack). Ids and per-row flags: p4_chase_clash_flags_v11b.csv. NOT wired into clash.

## filed

**Stacks (127 rows)**: total 127

| level | fully_inside_p4 | crosses_p4_boundary | outside_p4 | no_p4_on_level | no_xy |
|---|---|---|---|---|---|
| BELOW_SLAB | 0 | 0 | 0 | 5 | 0 |
| FLOOR_1 | 2 | 0 | 22 | 0 | 1 |
| FLOOR_2 | 16 | 0 | 4 | 0 | 0 |
| FLOOR_3 | 20 | 0 | 4 | 0 | 0 |
| FLOOR_4 | 19 | 1 | 4 | 0 | 0 |
| MEZZANINE | 15 | 1 | 7 | 0 | 0 |
| ROOF | 0 | 0 | 0 | 0 | 6 |
| **all** | 72 | 2 | 41 | 5 | 7 |

- FLOOR_1 fully inside (2): S-1[597e], S-3[5982]
- FLOOR_2 fully inside (16): CW-1[5931], W-1[5932], CW-2[5933], W-2[5934], CW-3[5935], W-3[5936], CW-4[5937], W-4[5938], S-3[599e], S-4[599f], V-3[59a0], V-4[59a1], S-2[59a2], V-2[59a3], S-1[59a4], V-1[59a5]
- FLOOR_3 fully inside (20): CW-1[5947], W-1[5948], W-1[5949], CW-2[594a], W-2[594b], W-2[594c], CW-3[594d], W-3[594e], W-3[594f], CW-4[5950], W-4[5951], W-4[5952], S-3[5993], S-4[5994], V-3[5995], V-4[5996], S-2[5997], V-2[5998], S-1[5999], V-1[599a]
- FLOOR_4 fully inside (19): CW-1[5964], W-1[5965], W-1[5966], CW-2[5967], CW-2[5968], W-2[5969], CW-3[596a], W-3[596b], W-3[596c], CW-4[596d], W-4[596e], W-4[596f], S-4[5988], V-4[5989], S-1[598a], S-2[598b], V-1[598c], S-3[598e], V-3[598f]
- FLOOR_4 CROSSING (1): V-2[598d]
- MEZZANINE fully inside (15): CW-1[5956], W-1[5957], CW-2[5958], CW-3[5959], W-3[595a], CW-4[595b], W-4[595c], W-2[595f], S-4[59ac], V-4[59ad], S-3[59ae], V-3-4[59af], S-1[59b0], S-2[59b1], V-1-2[59b2]
- MEZZANINE CROSSING (1): V-2[59b3]
  (stack tag[last 4 hex of plan_stacks id]; full ids in the CSV)

**Sloped sanitary runs (52)**: total 52

| level | fully_inside_p4 | crosses_p4_boundary | outside_p4 | no_p4_on_level | no_xy |
|---|---|---|---|---|---|
| FLOOR_1 | 0 | 4 | 3 | 0 | 0 |
| FLOOR_2 | 0 | 16 | 0 | 0 | 0 |
| FLOOR_3 | 0 | 16 | 0 | 0 | 0 |
| FLOOR_4 | 0 | 12 | 0 | 0 | 0 |
| MEZZANINE | 0 | 1 | 0 | 0 | 0 |
| **all** | 0 | 49 | 3 | 0 | 0 |

- crossing (49): F1-S-1-BT-1, F1-S-1-LAV-1, F1-S-1-WC-1, F1-S-1-KS-1, F2-S-2-BT-1, F2-S-2-LAV-1, F2-S-2-WC-1, F2-S-2-KS-1, F2-S-3-BT-1, F2-S-3-LAV-1, F2-S-3-WC-1, F2-S-3-KS-1, F2-S-1-BT-1, F2-S-1-LAV-1, F2-S-1-WC-1, F2-S-1-KS-1, F2-S-4-BT-1, F2-S-4-LAV-1, F2-S-4-WC-1, F2-S-4-KS-1, F3-S-2-KS-1, F3-S-2-FD-1, F3-S-2-BT-1, F3-S-2-LAV-1, F3-S-2-WC-1, F3-S-1-KS-1, F3-S-1-FD-1, F3-S-1-BT-1, F3-S-1-LAV-1, F3-S-1-WC-1, F3-S-4-BT-1, F3-S-4-LAV-1, F3-S-4-WC-1, F3-S-3-BT-1, F3-S-3-LAV-1, F3-S-3-WC-1, F4-S-3-BT-1, F4-S-3-LAV-1, F4-S-3-WC-1, F4-S-2-BT-1, F4-S-2-LAV-1, F4-S-2-WC-1, F4-S-1-BT-1, F4-S-1-LAV-1, F4-S-1-WC-1, F4-S-4-BT-1, F4-S-4-LAV-1, F4-S-4-WC-1, MZ-S-3-FD-1
- fully inside: 0

**Sprinkler pipe rows**: total 113

| level | fully_inside_p4 | crosses_p4_boundary | outside_p4 | no_p4_on_level | no_xy |
|---|---|---|---|---|---|
| FLOOR_1 | 0 | 3 | 26 | 0 | 0 |
| FLOOR_2 | 0 | 3 | 16 | 0 | 0 |
| FLOOR_3 | 0 | 3 | 16 | 0 | 0 |
| FLOOR_4 | 0 | 0 | 20 | 0 | 0 |
| MEZZANINE | 0 | 1 | 18 | 0 | 0 |
| ROOF | 0 | 0 | 0 | 0 | 7 |
| **all** | 0 | 10 | 96 | 0 | 7 |

- crossing (10): FLOOR_2:2, FLOOR_2:3, FLOOR_2:4, FLOOR_1:13, FLOOR_1:17, FLOOR_1:20, FLOOR_3:2, FLOOR_3:3, FLOOR_3:4, MEZZANINE:11
- fully inside: 0

## post_co

**Stacks (127 rows)**: total 127

| level | fully_inside_p4 | crosses_p4_boundary | outside_p4 | no_p4_on_level | no_xy |
|---|---|---|---|---|---|
| BELOW_SLAB | 0 | 0 | 0 | 5 | 0 |
| FLOOR_1 | 2 | 0 | 22 | 0 | 1 |
| FLOOR_2 | 16 | 0 | 4 | 0 | 0 |
| FLOOR_3 | 0 | 0 | 0 | 24 | 0 |
| FLOOR_4 | 0 | 0 | 0 | 24 | 0 |
| MEZZANINE | 0 | 0 | 0 | 23 | 0 |
| ROOF | 0 | 0 | 0 | 0 | 6 |
| **all** | 18 | 0 | 26 | 76 | 7 |

- FLOOR_1 fully inside (2): S-1[5a0c], S-3[5a10]
- FLOOR_2 fully inside (16): CW-1[59bf], W-1[59c0], CW-2[59c1], W-2[59c2], CW-3[59c3], W-3[59c4], CW-4[59c5], W-4[59c6], S-3[5a2c], S-4[5a2d], V-3[5a2e], V-4[5a2f], S-2[5a30], V-2[5a31], S-1[5a32], V-1[5a33]
  (stack tag[last 4 hex of plan_stacks id]; full ids in the CSV)

**Sloped sanitary runs (52)**: total 52

| level | fully_inside_p4 | crosses_p4_boundary | outside_p4 | no_p4_on_level | no_xy |
|---|---|---|---|---|---|
| FLOOR_1 | 0 | 4 | 3 | 0 | 0 |
| FLOOR_2 | 0 | 16 | 0 | 0 | 0 |
| FLOOR_3 | 0 | 0 | 0 | 16 | 0 |
| FLOOR_4 | 0 | 0 | 0 | 12 | 0 |
| MEZZANINE | 0 | 0 | 0 | 1 | 0 |
| **all** | 0 | 20 | 3 | 29 | 0 |

- crossing (20): F1-S-1-BT-1, F1-S-1-LAV-1, F1-S-1-WC-1, F1-S-1-KS-1, F2-S-2-BT-1, F2-S-2-LAV-1, F2-S-2-WC-1, F2-S-2-KS-1, F2-S-3-BT-1, F2-S-3-LAV-1, F2-S-3-WC-1, F2-S-3-KS-1, F2-S-1-BT-1, F2-S-1-LAV-1, F2-S-1-WC-1, F2-S-1-KS-1, F2-S-4-BT-1, F2-S-4-LAV-1, F2-S-4-WC-1, F2-S-4-KS-1
- fully inside: 0

**Sprinkler pipe rows**: none in this track (the post_co model has 0 sprinkler rows).
