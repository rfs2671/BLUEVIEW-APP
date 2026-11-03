# Stairshaft: the post-CO "extra" walls are the SAME shaft walls as filed (v11b correction)

**There are 7 shaft walls per level in BOTH tracks (35 per track).** `stairshaft_v2_merge.csv` column `change` (kept / ADDED / REMOVED) is a membership change versus the v09b shaft list; it is not a count of shaft walls and its per-track ADDED totals must not be read as "post-CO has more walls". The earlier note and the REPORT/README counts that compared those totals are withdrawn.

Evidence (stairshaft_v2_shaft_wall_pairs_v11b.csv, 70 rows = 35 per track): every shaft wall is paired with the wall of the other track with the largest overlap (the pairing is one-to-one on every level). Filed area covered by its post_co counterpart: 35 of 35 at 1.00. Post_co area covered by its filed counterpart: 33 of 35 at 1.00; the two exceptions are the rows below (one wall row of three pieces drawn past the shaft window).

| level | shaft walls filed | shaft walls post_co | pairs with full overlap |
|---|---|---|---|
| FLOOR_1 | 7 | 7 | 7 of 7 |
| FLOOR_2 | 7 | 7 | 7 of 7 |
| FLOOR_3 | 7 | 7 | 7 of 7 |
| FLOOR_4 | 7 | 7 | 7 of 7 |
| MEZZANINE | 7 | 7 | 7 of 7 |

The two post_co rows that are larger than their filed counterpart:

| level | post_co wall | type tag | counterpart (filed) | type tag | post_co area covered by filed |
|---|---|---|---|---|---|
| FLOOR_4 | ...45c2d | none (untyped) | ...45b76 | P1 | 0.847 |
| MEZZANINE | ...45c4d | none (untyped) | ...45b93 | P1 | 0.69 |

Why those two rows look "added": the east wall of the core (x 35.996-36.496) on FLOOR_4 and MEZZANINE is ONE post-CO row of three pieces; the middle piece equals the filed row (F4 y 9.939-25.606, MEZZ y 6.439-29.106) and the two outer pieces per row (F4 y 29.606-30.939 and 4.439-5.939; MEZZ y 29.606-34.606 and 0.772-5.939) lie outside the shaft window but ride along because membership is by whole row. The v09b post-CO shaft list did not contain that row, so the merge marked it ADDED. Not a new wall.

Also visible in the pairs: where the filed shaft walls carry type P1, the post-CO plan draws the same walls with NO type tag (post_co walls whose type tag differs from the filed counterpart: F1 0, F2 2, F3 4, F4 4, MEZZANINE 4 of 7), which is why post-CO has unbound pieces there (task 1).

Status: INFERENCE from geometry (membership), ruling_source roy_pm. Nothing was added to or removed from the GLB shaft membership; v11b only adds `stair_shaft_v2_counterpart_other_track` / `_counterpart_area_covered` / `_walls_per_level` to the extras of the 35 shaft wall nodes per track.