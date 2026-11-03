# Stairshaft merge: what the 2 extra post-CO walls are (post-CO +10 walls vs filed +8)

**They are not extra walls. They are the same east shaft wall, counted "ADDED" in post-CO and "kept" in filed.** Both tracks have exactly 7 shaft walls per level (stairs_shaft_v2.csv, n_walls = 7 at every level, F1..MEZZ, ST-A = ST-B = one core). The "+8 / +10" are counts of walls whose membership CHANGED versus the v09b shaft list, not counts of shaft walls.

| track | level | wall id (plan_walls:6ae49c0d0b73eb6c86645...) | tag | change | x ft | y ft (pieces) |
|---|---|---|---|---|---|---|
| filed | FLOOR_4 | ...b76 | P1 | kept (already in the v09b shaft list) | 35.996-36.496 | 9.939-25.606 (1 piece) |
| post_co | FLOOR_4 | ...c2d | none (untyped) | ADDED | 35.996-36.496 | 29.606-30.939 / 9.939-25.606 / 4.439-5.939 (3 pieces) |
| filed | MEZZANINE | ...b93 | P1 | kept | 35.996-36.496 | 6.439-29.106 (1 piece) |
| post_co | MEZZANINE | ...c4d | none (untyped) | ADDED | 35.996-36.496 | 29.606-34.606 / 6.439-29.106 / 0.772-5.939 (3 pieces) |

Why they exist only in post-CO as ADDED:
- The east wall of the core (x 35.996-36.496) on FLOOR_4 and MEZZANINE is drawn in the post-CO plan as ONE wall row of three pieces that runs past the shaft (north and south beyond the shaft window y 5.939-29.606); the filed plan draws only the middle piece as its own row.
- The middle piece of each post-CO row is identical to the filed row (F4 y 9.939-25.606, MEZZ y 6.439-29.106). The two outer pieces per row (F4 29.606-30.939 and 4.439-5.939; MEZZ 29.606-34.606 and 0.772-5.939) lie OUTSIDE the shaft window, but membership is by whole row, so they ride along (4 outer pieces in total, 2 per level).
- Per diff_vs_v09b.csv the v09b post-CO shaft list did not contain the post-CO row while the v09b filed list contained the filed row; the likely reason (INFERENCE, v09b rule not re-read) is containment: the filed single-piece row sits inside the window, the post-CO multi-piece row does not. Stairshaft v2 also admits a wall whose x lies in the window and whose y range spans the whole run (rule B in derive_shaft_v2.py), which admits the post-CO row; that is a change from v09b, hence ADDED. The same wall on F2 and F3 is a structural shear wall (kept in both tracks), which is why only F4 and MEZZ differ.
- Post-CO rows carry no wall-type tag (filed: P1); in v11 they are unbound_walls (plain solid, drawn thickness, rounded-up upper bound).

Status: INFERENCE from geometry (membership), ruling_source roy_pm; nothing was added or removed in the GLBs by this note.
