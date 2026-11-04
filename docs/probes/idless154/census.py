"""READ-ONLY census: ID-less schedules (no column role=identifier) and the attribute claims binding through each.
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
def idless(r):
    p = r.get("payload") or {}
    cols = p.get("columns") or []
    return not any(isinstance(c, dict) and c.get("role") == "identifier" for c in cols)
MARK = re.compile(r"\b[A-Za-z]{1,5}-?\d{1,2}\b")
def tags_of(headers):
    t = set()
    for h in headers:
        t |= {m.upper() for m in MARK.findall(h)}
        for m in re.finditer(r"\b(?:NUMBER|TYPE)\s+([A-G])\b", h): t.add(m.group(1))
    return sorted(t)
SUBJ = ["exhaust fans","EF-1","EF-2","PTAC units","PTAC-1","PTAC-2","PTAC-3","WH-1","wall electric unit heaters","SAF-1","supply fans","RD-1","RD-2","roof drains","DH-1","duct electric heaters","floor drains","piles"] + [f"type {c} doors" for c in "ABCDEFG"] + ["D1","D2","W1","W2","W3","D1 exterior doors","D2 exterior doors","W1 windows","W2 windows","W3 windows","interior doors","exterior doors","windows","doors"]
res = []
for r in sched:
    p = r.get("payload") or {}
    cols = p.get("columns") or []
    headers = [str((c.get("header") if isinstance(c, dict) else c) or "") for c in cols]
    rws = [x for x in (p.get("rows") or []) if isinstance(x, list)]
    ent = {"sheet": r.get("sheet_number"), "tier": r.get("tier"), "name": p.get("name"), "ncols": len(cols),
           "nrows": len(rws), "idless": idless(r), "header_tags": tags_of(headers), "headers": headers[:14]}
    if ent["idless"] and rws:
        parts = S.value_parts(r)
        subs = list(SUBJ) + ent["header_tags"] + [t + " units" for t in ent["header_tags"]]
        subs = list(dict.fromkeys(subs))
        bound = []
        for s in subs:
            terms = S.search_terms(s)
            if not terms or not any(S.names_subject(n, terms) for _t, n in parts[1:] + parts[:1]): continue
            for v in range(0, 60):
                for txt in (f"{s}: {v}.", f"{s} {v}."):
                    if S.answer_is_grounded(txt, base, intent="attribute")[0]: continue
                    if S.answer_is_grounded(txt, base + [r], intent="attribute")[0]:
                        bound.append(txt)
        ent["bound_through"] = bound
    res.append(ent)
json.dump(res, open(out, "w"), indent=1)
for e in res:
    if e["idless"]: print(e["sheet"], e["name"], e["ncols"], e["nrows"], e["header_tags"], len(e.get("bound_through", [])))
