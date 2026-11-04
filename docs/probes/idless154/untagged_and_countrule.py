"""READ-ONLY. (1) untagged claims through multi-tag ID-less grids; (2) were the census flips decided by the count rule?
argv: tree out.json"""
import json, sys, re, collections
sys.path.insert(0, "C:/Users/asddd/bv-worktrees/loc867_out")
from prod_common import *
tree, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, tree)
from lib import plan_search as S
memoize(S)
recs, rows = build(S)
base = [r for r in recs if r.get("record_type") != "schedule"]
sched = json.load(open(W + "census154/schedules_all.json", encoding="utf-8"))
res = {"untagged": [], "countrule": []}
NOUN = {"WINDOW SCHEDULE": ["windows", "window"], "INTERIOR DOOR SCHEDULE": ["interior doors", "doors", "door"],
        "EXTERIOR DOOR SCHEDULE": ["exterior doors", "doors", "door"], "TABLE": ["walls", "wall types", "partitions", "partition types", "wall"]}
for si, r in enumerate(sched):
    p = r.get("payload") or {}; cols = p.get("columns") or []
    if any(isinstance(c, dict) and c.get("role") == "identifier" for c in cols): continue
    headers = [str(c.get("header") or "") for c in cols]
    tagsby = [S._header_tags(h) for h in headers]
    if len({t for ts in tagsby for t in ts}) < 2: continue
    nouns = NOUN.get(p.get("name"), [])
    # cells with figures, by (leading words)
    cells = []
    for ri, row in enumerate(p.get("rows") or []):
        for ci, c in enumerate(row if isinstance(row, list) else []):
            c = str(c or ""); fs = [f.text.strip() for f in S._dims.find(c)] + list(S._values(c))
            m = re.search(r"\d", c); words = re.findall(r"[A-Za-z]{4,}", c[:m.start()] if m else c)[:2]
            if fs and words:
                cells.append({"ri": ri, "ci": ci, "words": " ".join(words), "figs": set(fs), "tag": tagsby[ci][0] if len(tagsby[ci]) == 1 else None})
    bykey = collections.defaultdict(list)
    for c in cells: bykey[c["words"]].append(c)
    seen = set()
    for noun in nouns:
        for key, cs in bykey.items():
            for f in sorted({f for c in cs for f in c["figs"]}):
                claim = f"{noun} {key}: {f}."
                if claim in seen: continue
                seen.add(claim)
                if not S.answer_is_grounded(claim, base + [r], intent="attribute")[0]: continue
                cand = [c for c in cs if f in c["figs"]]            # cells printing the figure
                family = [c for c in cs]                             # all cells with those words
                tags_with = sorted({c["tag"] or "-" for c in cand}); tags_all = sorted({c["tag"] or "-" for c in family})
                agree = all(f in c["figs"] for c in family if c["tag"])   # every tagged candidate prints it
                res["untagged"].append({"sheet": r["sheet_number"], "name": p.get("name"), "claim": claim, "key": key,
                    "tags_printing": tags_with, "tags_with_these_words": tags_all, "n_cells": len(cand),
                    "all_candidates_agree": bool(agree), "exactly_one_candidate": len(cand) == 1})
# (2) the census flips: decided by the count rule?
M = json.load(open(W + "census154/census_main.json")); B = json.load(open(W + "census154/census_br2.json"))
for m, b in zip(M, B):
    fl = sorted(set(m.get("bound_through", [])) - set(b.get("bound_through", [])))
    if not fl: continue
    rec = next(x for x in sched if x["sheet_number"] == m["sheet"] and (x["payload"] or {}).get("name") == m["name"] and len((x["payload"] or {}).get("columns") or []) == m["ncols"])
    for c in fl:
        blank, bad = S._route_counts(c, base + [rec], True)
        routed = blank != c
        res["countrule"].append({"sheet": m["sheet"], "claim": c, "routed_to_count_rule": routed, "count_rule_refusals": bad,
                                 "bound_by_count_rule": routed and not bad})
json.dump(res, open(out, "w"), indent=1)
u = res["untagged"]
print("untagged bound:", len(u), "agree:", sum(x["all_candidates_agree"] for x in u), "exactly one:", sum(x["exactly_one_candidate"] for x in u))
c = res["countrule"]
print("census flips:", len(c), "routed to count rule:", sum(x["routed_to_count_rule"] for x in c), "bound by count rule:", sum(x["bound_by_count_rule"] for x in c))
