"""READ-ONLY: value claims '<type> <words>: <figure>' for EVERY panel tag of the A-400.00 grids - header tags AND the tags
body labels start (door types F, G) - for every figure of every cell, attribute intent. Same claim shapes as idless154/value_grid.py,
so its output diffs against that probe's. argv: tree out.json"""
import json, sys, re
sys.path.insert(0, "C:/Users/asddd/bv-worktrees/loc867_out")
from prod_common import *
tree, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, tree)
from lib import plan_search as S
memoize(S)
recs, rows = build(S)
base = [r for r in recs if r.get("record_type") != "schedule"]
sched = json.load(open(W + "census154/schedules_all.json", encoding="utf-8"))
res = []
for si, r in enumerate(sched):
    if str(r.get("sheet_number")).upper() != "A-400.00": continue
    p = r.get("payload") or {}
    tags = getattr(S, "_idless_tags", lambda _r: set())(r)
    if not tags: continue
    headers = [str((c.get("header") if isinstance(c, dict) else c) or "") for c in (p.get("columns") or [])]
    col_tags = [S._header_tags(h) for h in headers]
    owner = S._panel_tags(col_tags, p.get("rows") or []) if hasattr(S, "_panel_tags") else None
    cells = []
    for ri, row in enumerate(p.get("rows") or []):
        for ci, c in enumerate(row if isinstance(row, list) else []):
            c = str(c or "")
            fs = [f.text.strip() for f in S._dims.find(c)] + list(S._values(c))
            if not fs: continue
            m = re.search(r"\d", c)
            words = [w for w in re.findall(r"[A-Za-z]{4,}", c[:m.start()] if m else c)][:2]
            if not words: continue
            for f in dict.fromkeys(fs):
                cells.append((ri, ci, " ".join(words), f))
    for t in sorted(tags):
        for (ri, ci, words, f) in cells:
            subj = f"type {t} door" if len(t) == 1 else t
            claim = f"{subj} {words}: {f}."
            ok = S.answer_is_grounded(claim, base + [r], intent="attribute")[0]
            res.append({"sched": si, "sheet": r.get("sheet_number"), "name": p.get("name"), "tag": t, "fig": f, "claim": claim,
                        "cell": [ri, ci], "col_header": headers[ci] if ci < len(headers) else "",
                        "panel_of_cell": (owner[ri][ci] if owner and ri < len(owner) and ci < len(owner[ri]) else None), "bound": ok})
json.dump(res, open(out, "w"))
print(len(res), sum(x["bound"] for x in res))
