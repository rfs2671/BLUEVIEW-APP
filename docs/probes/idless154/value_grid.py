"""READ-ONLY: value claims '<tag> <figure>' for every tag of every tag-headed ID-less schedule, every figure printed in it,
attribute intent, on the records the gate sees (base + that schedule). argv: tree out.json"""
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
MARK = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{1,5}-?\d{1,2}(?![A-Za-z0-9])")
res = []
for si, r in enumerate(sched):
    p = r.get("payload") or {}
    cols = p.get("columns") or []
    if any(isinstance(c, dict) and c.get("role") == "identifier" for c in cols): continue
    headers = [str((c.get("header") if isinstance(c, dict) else c) or "") for c in cols]
    tags = set()
    for h in headers:
        tags |= {m.upper() for m in MARK.findall(h)}
        tags |= {m.group(1) for m in re.finditer(r"\b(?:NUMBER|TYPE)\s+([A-G])\b", h)}
    if not tags: continue
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
            hdr = headers[ci] if ci < len(headers) else ""
            res.append({"sched": si, "sheet": r.get("sheet_number"), "name": p.get("name"), "tag": t, "fig": f, "claim": claim,
                        "cell": [ri, ci], "col_header": hdr, "bound": ok})
json.dump(res, open(out, "w"))
print(len(res), sum(x["bound"] for x in res))
