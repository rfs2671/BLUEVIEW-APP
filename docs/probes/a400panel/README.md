Type-by-panel probes (read-only). Base: 5f7c2afb (#938).
- `panel_grid.py <backend tree> <out.json>`: value claims for every panel tag of A-400.00, header tags AND the tags body labels start (door types F, G). Same claim shapes as `../idless154/value_grid.py`; adds `panel_of_cell` (the tag whose panel holds the cell).
- `verify_flips.py <base.json> <new.json> <out.json>`: every refused->bound claim is checked against the crop-read word boxes (`crop_a400/words.json`, panel regions from `crop_a400/map.py`): the figure must be printed by a word inside the claim's OWN type's panel. Prints claim, type, source word box.
- `flips.json`: the full diff. 120 value-grid claims + 5 type F claims, all refused->bound, all verified; 0 bound->refused.
- `control.txt` (7 failed by AssertionError on #938's tree), `mutations.txt` (8 mutations, all killed).
Standing probes: `bash ../idless154/run.sh <tree> <out>` (value grid 186 / 120 bound, census, untagged); baselines in `../idless154/baselines.json` under "a400panel".
Limit: stored schedule records carry no per-cell word boxes (only the grid's bbox), so the panel is a rectangle of GRID CELLS (the extractor's reading of the page), not of word boxes; the word-box check lives in verify_flips.py. A re-index that stores cell boxes could replace the label rule with true geometry.
