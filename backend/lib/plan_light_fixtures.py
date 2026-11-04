"""Light fixtures counted by their TAGS: each tag, and the drawing beside it.

    count_sheet(page, vocab, ...) -> {"tags": [...], "counts": {...}, ...}

WHY TAGS, NOT A LEGEND. No RCP on 588 Thomas S Boyland prints a legend swatch
for a light fixture (lane T2, lib.plan_legend_symbols, refused every RCP):
RCP-001.00's LEGEND holds control devices only, the second set's A.3.1-A.3.5
print no legend, and A.3.0's LIGHTING SCHEDULE shows photographs. What every
RCP does print is a TAG beside each fixture - L1, L2, L4, L5, DS - in real
text. Operator ruling 74: count by the tag, with the drawing beside it.

THE TAGS A SHEET MAY CARRY come from its SET'S LIGHTING SCHEDULE, never from
a pattern: RCP-002.00's FIXTURE column (L1-L5, DS) for the filed set, A.3.0's
TAG column (L-1..L-5) for the second set. The two sets use the same letters
for different fixtures (the filed L1 is a CFL, the second set's L-1 a
downlight), so a vocabulary is per set and the caller hands in the set's own
(schedule_tags). EX, F1, A1 are control devices and area marks and are no
fixture's tag. A schedule entry is compared as letters and digits (L-1 = L1).

WHICH WORDS ARE TAGS. A vocabulary word in the page's text that is NOT a
schedule's or table's entry (in_table_row: a word with a long rule tight
above and below it is a table row) and is not in the title block.

THE DRAWING BESIDE A TAG (attach). Candidates are the sheet's small closed
drawings: paths no longer than CAP_PT, of one pen (colour and CAD layer),
joined when their boxes touch - concentric circles, a lens inside its
housing - with at least one closed path among them. A tag's drawing is the
candidate nearest the tag's box, at most REACH x the tag's own text height
away (RCP-001.00 prints L2 0.6pt under its fixture; A.3.1 prints L1 touching
its fixture's box). Then:

  * NO DRAWING within reach: the tag is REFUSED ("a tag with no fixture").
  * ONE DRAWING, TWO TAGS: both refused - which fixture is whose is not said.
  * THE TAG'S OWN DRAWING: every tag of one value sits beside the same block.
    A tag whose drawing is not the one most of its value's tags sit beside
    (same path kinds, sizes within SIG_TOL_PT, any right-angle turn) is
    refused, never counted as that value.
  * A FIXTURE WITH NO TAG: a drawing that IS one value's drawing and that no
    tag claims is listed, never counted (and never counted as that value:
    the count is of tagged fixtures).

WHERE A FIXTURE IS. Each tag belongs to the drawing whose printed title
("FIRST FLOOR RCP PLAN", "SECOND FLOOR - THIRD FLOOR REFLECTED CEILING
PLAN...") is below it in its column. The floor is that title's level -
every level it names, for a typical plan - and the sheet number is the
caller's. A tag under no title has no floor and is counted at sheet scope
only.

THE PRINTED TOTALS (cross_check). A set that prints fixture quantities -
RCP-002.00's TOTAL WATTAGE OF BUILDING (type x floor), RCP-001.00's
"<FLOOR> COMMON SPACE TYPE & LIGHT FIXTURES" tables - is compared floor by
floor and type by type, and over the building:

  * a total for NAMED SPACES (the row is STAIRS, CORRIDOR, ...; the table is
    a COMMON SPACE table) bounds the floor's count from below: equal agrees,
    more drawn is "not checked beyond those spaces", FEWER drawn disagrees;
  * a COUNT THAT DISAGREES WITH A PRINTED TOTAL STATES NEITHER - the row is a
    conflict with no count and no total, and goes to review;
  * two printed totals for one floor and type that disagree state neither.
A set with no printed quantity (A.3.0 has no QTY column) is "no printed
total", never a pass. A total is never compared across sets.

NOT A COUNTING SOURCE FOR THE CHAT GATE, AND NOT VERIFIED. The basis
`fixture_tag` is not in plan_search.COUNTING_BASES and plan_search never
names this module. Ruling 77 (T2's legend counts, applied here): a stored
count is a "not verified" takeoff line and a review item until Roy's sub-bid
benchmark has measured it (plan_takeoff_export._light_fixture_lines); ruling
78: no production pass before that. See fixture_rows; nothing here writes.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

Box = Tuple[float, float, float, float]

#: A path longer than this (pt, either way) is structure - a wall, a run, a
#: rule - and is never part of a fixture's drawing.
CAP_PT = 36.0
#: A path is closed when its pen ends within this (pt) of where it started.
CLOSE_PT = 0.3
#: A fixture's drawing is at least this big (pt): a dot is no fixture.
MIN_PT = 2.0
#: Paths of one pen whose boxes come this close (pt) are one drawing.
TOUCH_PT = 0.3
#: A tag's drawing is at most this many of the tag's own text heights away.
REACH = 1.0
#: Two drawings are the same block when every path's size agrees within this (pt).
SIG_TOL_PT = 0.35
#: A block inserted at another scale is the same block within this ratio.
BLOCK_SCALE = (0.75, 1.0 / 0.75)
#: A table row: a rule within this many text heights above and below a word,
#: each at least TABLE_RULE_W word-widths long.
TABLE_GAP_H, TABLE_RULE_W = 0.6, 3.0
#: Two words of one tag whose boxes agree within this (pt) are one tag printed twice.
TWICE_PT = 1.0

#: Rows a pass would store (its own collection: no plan record, so search
#: never returns them).
COLLECTION = "plan_light_fixture_counts"
RECORD_TYPE = "light_fixture_tag_count"
#: How the count was made. NOT in plan_search.COUNTING_BASES.
COUNT_BASIS = "fixture_tag"

NO_VOCAB = "the set prints no lighting schedule naming its fixture tags"
NO_TAGS = ("no light-fixture tag in the sheet's text (text drawn as vectors is not read here): "
           "no fixture is counted on it")
NO_DRAWING = "a tag with no fixture drawing beside it"
SHARED = "one drawing beside {n} tags: which fixture is whose is not said"
OTHER_DRAWING = ("the drawing beside it is not the drawing its other {n} {tag} tags "
                 "sit beside")
NOT_VERIFIED = ("light fixture tag count: not verified until the sub-bid benchmark "
                "(tagged fixtures, per drawing)")


def norm_tag(s: Any) -> str:
    """A tag compared as letters and digits: L-1 and L1 are one tag."""
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _gap(a: Box, b: Box) -> float:
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return (dx * dx + dy * dy) ** 0.5


# ══════════════════════════════════════════════════════════════════════════
# The vocabulary: the set's lighting schedule
# ══════════════════════════════════════════════════════════════════════════

_SCHED_HEADERS = ("TAG", "MARK", "FIXTURE", "TYPE")
_TAG_SHAPE = re.compile(r"^[A-Z]{1,3}-?\d{0,3}[A-Z]?$")


def schedule_tags(words: Sequence[Tuple[str, float, float, float, float, str]]) -> Dict[str, Any]:
    """{"tags": [as printed], "header": word, "box": (x0, y0, x1, y1)} - the
    identifier column of a table titled LIGHTING SCHEDULE, read off the
    page's text (`directed_word_boxes`); {"tags": [], "why": ...} when none.

    The column is the leftmost TAG / MARK / FIXTURE / TYPE header under the
    title ("# OF FIXTURE" is a count's header, not it), and runs down until
    the first word in it that is not shaped like a tag."""
    ws = [w for w in words if w[5] == "ltr"]
    titles = [w for w in ws if w[0].upper() == "SCHEDULE" and any(
        v[0].upper() == "LIGHTING" and abs(v[2] - w[2]) < 3 and 0 < w[1] - v[3] < 40 for v in ws)]
    for t in titles:
        tcx = (t[1] + t[3]) / 2
        heads = []
        for w in ws:
            if w[0].upper() not in _SCHED_HEADERS or not 0 < w[2] - t[4] < 90 or abs((w[1] + w[3]) / 2 - tcx) > 500:
                continue
            if any(v[0].upper() == "OF" and abs(v[2] - w[2]) < 3 and 0 <= w[1] - v[3] < 30 for v in ws):
                continue
            heads.append(w)
        if not heads:
            continue
        top = min(h[2] for h in heads)
        heads = [h for h in heads if h[2] - top < 4]
        h = min(heads, key=lambda h: h[1])
        hx = (h[1] + h[3]) / 2
        half = max((h[3] - h[1]) / 2, 12.0)
        col = sorted((w for w in ws if abs((w[1] + w[3]) / 2 - hx) <= half and 0 < w[2] - h[4] < 600),
                     key=lambda w: w[2])
        tags = []
        for w in col:
            if not _TAG_SHAPE.match(w[0]):
                break
            tags.append(w[0])
        if tags:
            got = col[:len(tags)]
            return {"tags": tags, "header": h[0],
                    "box": (min([t[1], h[1]] + [w[1] for w in got]), t[2],
                            max([t[3], h[3]] + [w[3] for w in got]), max(w[4] for w in got))}
    return {"tags": [], "why": NO_VOCAB}


# ══════════════════════════════════════════════════════════════════════════
# The tags on a plan
# ══════════════════════════════════════════════════════════════════════════

def _h_rules(drawings) -> List[Tuple[float, float, float]]:
    out = []
    for d in drawings:
        for it in d["items"]:
            if it[0] != "l":
                continue
            (x0, y0), (x1, y1) = it[1], it[2]
            if abs(y1 - y0) < 0.3 and abs(x1 - x0) >= 10:
                out.append((min(x0, x1), max(x0, x1), (y0 + y1) / 2))
    return out


def in_table_row(w: Tuple, rules: Sequence[Tuple[float, float, float]]) -> bool:
    """A word with a long rule tight above AND below it is a table's entry
    (RCP-001.00's per-floor COMMON SPACE tables, RCP-002.00's schedules),
    not a tag on the plan."""
    _t, x0, y0, x1, y1, _d = w
    h, wd = y1 - y0, x1 - x0
    need = TABLE_RULE_W * max(wd, h)
    above = below = False
    for a, b, y in rules:
        if b - a < need or a > x0 + 0.5 or b < x1 - 0.5:
            continue
        if 0 <= y0 - y <= TABLE_GAP_H * h + 0.5:
            above = True
        elif 0 <= y - y1 <= TABLE_GAP_H * h + 0.5:
            below = True
        if above and below:
            return True
    return False


def plan_tags(words, drawings, vocab: Iterable[str], title_edge: Optional[float] = None
              ) -> Tuple[List[Dict[str, Any]], int]:
    """([{tag, box, h, src}], table entries dropped). Every word of the page's
    text that is one of the set's tags, as letters and digits, outside any
    table row and left of the title block."""
    want = {norm_tag(v): norm_tag(v) for v in vocab if norm_tag(v)}
    rules = _h_rules(drawings)
    out, dropped = [], 0
    for w in words:
        k = norm_tag(w[0])
        if k not in want or w[0].strip() != w[0]:
            continue
        # ONE TAG PRINTED TWICE (an xref drawn twice, A.3.1) is one tag
        if any(o["tag"] == k and all(abs(a - b) <= TWICE_PT for a, b in zip(o["box"], w[1:5]))
               for o in out):
            continue
        if title_edge is not None and (w[1] + w[3]) / 2 > title_edge:
            continue
        if in_table_row(w, rules):
            dropped += 1
            continue
        out.append({"tag": k, "printed": w[0], "box": (w[1], w[2], w[3], w[4]),
                    "h": max(w[4] - w[2], w[3] - w[1]) if w[5] in ("ttb", "btt") else w[4] - w[2],
                    "dir": w[5], "src": "text"})
    return out, dropped


# ══════════════════════════════════════════════════════════════════════════
# The drawings a tag may sit beside
# ══════════════════════════════════════════════════════════════════════════

def _closed(d) -> bool:
    its = d["items"]
    if not its:
        return False
    p0 = its[0][1]
    p1 = its[-1][2] if its[-1][0] == "l" else its[-1][4]
    return abs(p0[0] - p1[0]) <= CLOSE_PT and abs(p0[1] - p1[1]) <= CLOSE_PT


def fixture_objects(drawings, keep=None) -> List[Dict[str, Any]]:
    """Small drawings: paths no longer than CAP_PT of one pen whose boxes
    touch, joined; only those holding a closed path of at least MIN_PT.
    {"box", "paths": [indices], "pen", "sig"}."""
    idx = [i for i, d in enumerate(drawings)
           if max(d["rect"][2] - d["rect"][0], d["rect"][3] - d["rect"][1]) <= CAP_PT
           and (keep is None or keep(d))]
    parent = {i: i for i in idx}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    cell = 8.0
    grid: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for i in idx:
        x0, y0, x1, y1 = drawings[i]["rect"]
        for gx in range(int((x0 - TOUCH_PT) // cell), int((x1 + TOUCH_PT) // cell) + 1):
            for gy in range(int((y0 - TOUCH_PT) // cell), int((y1 + TOUCH_PT) // cell) + 1):
                grid[(gx, gy)].append(i)
    for members in grid.values():
        for ai, a in enumerate(members):
            da = drawings[a]
            for b in members[ai + 1:]:
                db = drawings[b]
                if (da["colour"], da["layer"]) != (db["colour"], db["layer"]):
                    continue
                if _gap(da["rect"], db["rect"]) <= TOUCH_PT:
                    parent[find(b)] = find(a)
    comps: Dict[int, List[int]] = defaultdict(list)
    for i in idx:
        comps[find(i)].append(i)
    out = []
    for members in comps.values():
        ds = [drawings[i] for i in members]
        if not any(_closed(d) and max(d["rect"][2] - d["rect"][0], d["rect"][3] - d["rect"][1]) >= MIN_PT
                   for d in ds):
            continue
        box = (min(d["rect"][0] for d in ds), min(d["rect"][1] for d in ds),
               max(d["rect"][2] for d in ds), max(d["rect"][3] for d in ds))
        if max(box[2] - box[0], box[3] - box[1]) > CAP_PT:
            continue
        sig = signature(ds, box)
        # ONE DRAWING DRAWN TWICE (two pens, one place) is one drawing
        if any(all(abs(u - v) <= TWICE_PT for u, v in zip(o["box"], box)) and same_block(o["sig"], sig)
               for o in out):
            continue
        out.append({"box": box, "paths": sorted(members), "pen": (ds[0]["colour"], ds[0]["layer"]),
                    "sig": sig})
    return out


def signature(ds, box: Box) -> List[Tuple[str, float, float]]:
    """The block, turn-free: each path's kinds and size, the long side first
    when the drawing is taller than wide. A path drawn twice (the same kinds
    on the same box: A.3.1 draws two of its fixtures twice) is one path."""
    turn = (box[3] - box[1]) > (box[2] - box[0]) + SIG_TOL_PT
    out, seen = [], []
    for d in ds:
        k = ("".join(sorted(it[0] for it in d["items"])), d["rect"])
        if any(k[0] == s0 and all(abs(u - v) <= CLOSE_PT for u, v in zip(k[1], s1)) for s0, s1 in seen):
            continue
        seen.append(k)
        w, h = d["rect"][2] - d["rect"][0], d["rect"][3] - d["rect"][1]
        if turn:
            w, h = h, w
        out.append(("".join(sorted(it[0] for it in d["items"])), round(w, 2), round(h, 2)))
    return sorted(out)


def same_block(a, b) -> bool:
    """One block: the same paths, each the same size within SIG_TOL_PT once
    the second is brought to the first's size - a block inserted at another
    scale is the same block (RCP-001.00's roof L4 is 1.125x the floors'),
    within BLOCK_SCALE."""
    if len(a) != len(b) or not a:
        return False
    ea, eb = max(w for _k, w, _h in a), max(w for _k, w, _h in b)
    if ea <= 0 or eb <= 0 or not BLOCK_SCALE[0] <= ea / eb <= BLOCK_SCALE[1]:
        return False
    s = ea / eb
    return all(ka == kb and abs(wa - wb * s) <= SIG_TOL_PT and abs(ha - hb * s) <= SIG_TOL_PT
               for (ka, wa, ha), (kb, wb, hb) in zip(a, b))


# ══════════════════════════════════════════════════════════════════════════
# The drawings' titles: which floor a tag is on
# ══════════════════════════════════════════════════════════════════════════

_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
        "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
_LEVEL = re.compile(r"\b(?:(" + "|".join(_ORD) + r"|\d{1,2}(?:st|nd|rd|th))\s+(?:floor|level)"
                    r"|(roof|mezzanine|cellar|basement|bulkhead|penthouse)\b)", re.I)


def levels_named(title: str) -> List[Any]:
    """Every level a drawing title names, in order: SECOND FLOOR - THIRD FLOOR
    is [2, 3] (a typical plan); ROOF RCP PLAN is ["roof"]."""
    out = []
    for m in _LEVEL.finditer(title or ""):
        if m.group(1):
            w = m.group(1).lower()
            v = _ORD.get(w) or int(re.match(r"\d+", w).group(0))
        else:
            v = m.group(2).lower()
        if v not in out:
            out.append(v)
    return out


def drawing_titles(words) -> List[Dict[str, Any]]:
    """[{title, levels, x0, y}] - each RCP drawing's printed title: the line
    holding RCP PLAN or REFLECTED CEILING PLAN, with the line above it when
    that line starts where it does (A.3.1 prints FIRST FLOOR over REFLECTED
    CEILING PLAN AND LIGHTING PLAN)."""
    ws = [w for w in words if w[5] == "ltr"]
    lines: Dict[int, List] = defaultdict(list)
    for w in ws:
        lines[round(w[4])].append(w)
    rows = []
    for _y, line in lines.items():
        line.sort(key=lambda w: w[1])
        # split a printed line where words are far apart (two drawings' titles)
        cur = [line[0]]
        for w in line[1:]:
            if w[1] - cur[-1][3] > 3 * max(w[4] - w[2], 1.0):
                rows.append(cur)
                cur = [w]
            else:
                cur.append(w)
        rows.append(cur)
    out = []
    for r in rows:
        txt = " ".join(w[0] for w in r).upper()
        if not re.search(r"\bRCP PLAN\b|REFLECTED CEILING PLAN", txt):
            continue
        x0, y0, h = r[0][1], min(w[2] for w in r), r[0][4] - r[0][2]
        above = [q for q in rows if q is not r and abs(q[0][1] - x0) <= 2 * h
                 and 0 < y0 - max(w[4] for w in q) <= 1.2 * h]
        if above:
            txt = " ".join(w[0] for w in min(above, key=lambda q: y0 - q[0][4])).upper() + " " + txt
        lv = levels_named(txt)
        out.append({"title": txt, "levels": lv, "x0": x0, "y": y0})
    return out


def title_for(box: Box, titles: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The drawing a point belongs to: the title below it in its column - the
    column being the nearest title start at or left of it."""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    left = [t for t in titles if t["x0"] <= cx + 40]
    if not left:
        return None
    colx = max(t["x0"] for t in left)
    col = [t for t in left if abs(t["x0"] - colx) <= 120 and t["y"] > cy]
    return min(col, key=lambda t: t["y"] - cy) if col else None


# ══════════════════════════════════════════════════════════════════════════
# One sheet
# ══════════════════════════════════════════════════════════════════════════

def _within_reach(t: Dict[str, Any], objs, grid) -> List[int]:
    """The drawings within REACH x the tag's text height of its box, nearest
    first (box gap, then centre distance)."""
    reach = REACH * t["h"]
    b = t["box"]
    seen, got = set(), []
    for gx in range(int((b[0] - reach) // 24), int((b[2] + reach) // 24) + 1):
        for gy in range(int((b[1] - reach) // 24), int((b[3] + reach) // 24) + 1):
            for j in grid.get((gx, gy), ()):
                if j in seen:
                    continue
                seen.add(j)
                g = _gap(b, objs[j]["box"])
                if g <= reach:
                    c = objs[j]["box"]
                    d2 = ((b[0] + b[2] - c[0] - c[2]) ** 2 + (b[1] + b[3] - c[1] - c[3]) ** 2) / 4
                    got.append(((round(g, 2), d2), j))
    return [j for _k, j in sorted(got)]


def count_sheet(page, vocab: Iterable[str], *, title_edge: Optional[float] = None,
                exclude: Sequence[Box] = ()) -> Dict[str, Any]:
    """Every tag on `page` from the set's `vocab`, the drawing beside each,
    and the counts per tag per drawing (floor). `exclude`: boxes (the
    schedule) whose words and drawings are not the plan's.

    Returns {"tags": [{tag, box, drawing, status, why?, title, levels}],
             "untagged": [{box, could_be: [tags]}], "counts": {title:
             {tag: n}}, "titles": [...], "refused"?: NO_TAGS | NO_VOCAB}."""
    vocab = [v for v in (vocab or []) if norm_tag(v)]
    if not vocab:
        return {"refused": NO_VOCAB, "tags": [], "untagged": [], "counts": {}, "titles": []}
    drawings = page.drawings
    words = list(page.directed_word_boxes)
    if title_edge is None:
        from lib import plan_cells as pc
        from lib.plan_sheet import display_segments
        title_edge = pc.title_block_edge(display_segments(page), page.width, page.height)

    def outside(b):
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        return cx <= title_edge and not any(e[0] <= cx <= e[2] and e[1] <= cy <= e[3] for e in exclude)
    words = [w for w in words if outside((w[1], w[2], w[3], w[4]))]
    tags, in_tables = plan_tags(words, drawings, vocab, title_edge)
    titles = drawing_titles(words)
    res: Dict[str, Any] = {"tags": tags, "untagged": [], "counts": {}, "titles": titles,
                           "table_entries": in_tables}
    if not tags:
        res["refused"] = NO_TAGS
        return res
    objs = fixture_objects(drawings, keep=lambda d: outside(d["rect"]))
    grid: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for j, o in enumerate(objs):
        x0, y0, x1, y1 = o["box"]
        for gx in range(int(x0 // 24), int(x1 // 24) + 1):
            for gy in range(int(y0 // 24), int(y1 // 24) + 1):
                grid[(gx, gy)].append(j)
    for t in tags:
        t["near"] = _within_reach(t, objs, grid)
        tt = title_for(t["box"], titles)
        t["title"] = tt["title"] if tt else None
        t["levels"] = tt["levels"] if tt else []
    # PASS 1 - EACH VALUE'S OWN DRAWING: the block most of its tags have as
    # their nearest drawing (a drawing nearest to two tags votes for neither).
    first: Dict[int, List[int]] = defaultdict(list)
    for i, t in enumerate(tags):
        if t["near"]:
            first[t["near"][0]].append(i)
    own_sig: Dict[str, Any] = {}
    by_tag: Dict[str, List[int]] = defaultdict(list)
    for i, t in enumerate(tags):
        if t["near"] and len(first[t["near"][0]]) == 1:
            by_tag[t["tag"]].append(i)
    for k, ii in by_tag.items():
        groups: List[List[int]] = []
        for i in ii:
            sg = objs[tags[i]["near"][0]]["sig"]
            for g in groups:
                if same_block(objs[tags[g[0]]["near"][0]]["sig"], sg):
                    g.append(i)
                    break
            else:
                groups.append([i])
        groups.sort(key=len, reverse=True)
        if len(groups) == 1 or len(groups[0]) > len(groups[1]):
            own_sig[k] = (objs[tags[groups[0][0]]["near"][0]]["sig"], len(groups[0]))
    # PASS 2 - THE TAG'S DRAWING is the nearest drawing within reach that is
    # its value's own block; a nearer drawing of another block (a stair
    # nosing, an exhaust box) is passed over, never counted as the fixture.
    for t in tags:
        t["drawing"] = None
        if not t["near"]:
            t["why"] = NO_DRAWING
            continue
        if t["tag"] not in own_sig:
            t["why"] = f"its {t['tag']} tags sit beside different drawings, none most often"
            continue
        mine = [j for j in t["near"] if same_block(objs[j]["sig"], own_sig[t["tag"]][0])]
        if not mine:
            t["why"] = OTHER_DRAWING.format(n=own_sig[t["tag"]][1], tag=t["tag"])
            continue
        t["drawing"] = mine[0]
    claims: Dict[int, List[int]] = defaultdict(list)
    for i, t in enumerate(tags):
        if t["drawing"] is not None:
            claims[t["drawing"]].append(i)
    for t in tags:
        if t["drawing"] is None:
            t["status"] = "refused"
        elif len(claims[t["drawing"]]) > 1:
            t.update(status="refused", why=SHARED.format(n=len(claims[t["drawing"]])))
        else:
            t["status"] = "counted"
        t["drawing_box"] = None if t["drawing"] is None else [round(v, 1) for v in objs[t["drawing"]]["box"]]
        t.pop("near", None)
    claimed = set(claims)
    for j, o in enumerate(objs):
        if j in claimed:
            continue
        could = sorted(k for k, (s, _n) in own_sig.items() if same_block(o["sig"], s))
        if could:
            tt = title_for(o["box"], titles)
            res["untagged"].append({"box": [round(v, 1) for v in o["box"]], "could_be": could,
                                    "title": tt["title"] if tt else None})
    counts: Dict[str, Counter] = defaultdict(Counter)
    for t in tags:
        if t["status"] == "counted":
            counts[t["title"] or ""][t["tag"]] += 1
    res["counts"] = {k: dict(v) for k, v in counts.items()}
    res["objects"] = len(objs)
    return res


# ══════════════════════════════════════════════════════════════════════════
# The printed totals, and the cross-check
# ══════════════════════════════════════════════════════════════════════════

_LEVEL_HEAD = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5, "SIXTH": 6,
               "MEZZANINE": "mezzanine", "ROOF": "roof", "CELLAR": "cellar"}


def printed_totals(words, vocab: Iterable[str], source: str) -> List[Dict[str, Any]]:
    """[{level, tag, qty, space, source}] - fixture quantities a sheet prints.

    1. A TYPE x FLOOR table (RCP-002.00's TOTAL WATTAGE OF BUILDING): a TYPE
       header, level headers (FIRST, SECOND, ..., MEZZANINE, ROOF) on its
       row, and per row a tag under TYPE, an integer under each level, the
       space it covers under FLOOR (STAIRS, CORRIDOR, ...).
    2. A per-floor table titled "<LEVEL> ... LIGHT FIXTURES" with FIXTURE TYPE
       and QUANTITY columns (RCP-001.00's COMMON SPACE tables): the title's
       level, and "COMMON SPACE" when the title says so.
    Integers only; a cell that is not one is not a total."""
    want = {norm_tag(v) for v in vocab if norm_tag(v)}
    ws = [w for w in words if w[5] == "ltr"]
    out: List[Dict[str, Any]] = []
    cx = lambda w: (w[1] + w[3]) / 2
    cy = lambda w: (w[2] + w[4]) / 2
    # 1. TYPE x FLOOR
    for th in (w for w in ws if w[0].upper() == "TYPE"):
        h = th[4] - th[2]
        heads = [w for w in ws if w[0].upper() in _LEVEL_HEAD and abs(cy(w) - cy(th)) <= 1.2 * h
                 and 0 < w[1] - th[1] < 700]
        if len(heads) < 2:
            continue
        fl = [w for w in ws if w[0].upper() == "FLOOR" and abs(cy(w) - cy(th)) <= 1.2 * h and w[1] < th[1]]
        flx = cx(max(fl, key=lambda w: w[1])) if fl else None
        for tw in sorted((w for w in ws if abs(cx(w) - cx(th)) <= 14 and 0 < w[2] - th[4] < 300),
                         key=lambda w: w[2]):
            if norm_tag(tw[0]) not in want:
                continue
            space = None
            if flx is not None:
                # the space the row covers: the FLOOR-column label nearest the
                # row (a merged cell - CORRIDOR spans its L2 and L5 rows)
                labs = [w for w in ws if abs(cx(w) - flx) <= 45 and abs(cy(w) - cy(tw)) <= 1.6 * h
                        and w[0].isalpha()]
                if labs:
                    dy0 = min(abs(cy(w) - cy(tw)) for w in labs)
                    space = " ".join(w[0] for w in sorted(
                        (w for w in labs if abs(abs(cy(w) - cy(tw)) - dy0) <= 1.0), key=lambda w: w[1])).upper()
            for hd in heads:
                cell = [w for w in ws if abs(cy(w) - cy(tw)) <= 4 and abs(cx(w) - cx(hd)) <= 14]
                if len(cell) == 1 and re.fullmatch(r"\d+", cell[0][0]):
                    out.append({"level": _LEVEL_HEAD[hd[0].upper()], "tag": norm_tag(tw[0]),
                                "qty": int(cell[0][0]), "space": space or "named spaces",
                                "source": source, "table": "type x floor"})
    # 2. "<LEVEL> ... LIGHT FIXTURES" per-floor tables
    for fh in (w for w in ws if w[0].upper() == "FIXTURES"):
        h = fh[4] - fh[2]
        line = [fh]
        while True:
            prev = [w for w in ws if abs(cy(w) - cy(fh)) <= 2 and 0 <= line[0][1] - w[3] <= 1.5 * h]
            if not prev:
                break
            line.insert(0, max(prev, key=lambda w: w[3]))
        title = " ".join(w[0] for w in line).upper()
        if "LIGHT FIXTURES" not in title:
            continue
        lv = levels_named(title)
        if len(lv) != 1:
            continue
        x0, x1 = line[0][1] - 150, fh[3] + 150
        band = [w for w in ws if x0 <= cx(w) <= x1 and 0 < w[2] - fh[4] < 2.5 * h]
        ft = [w for w in band if w[0].upper() == "TYPE"
              and any(v[0].upper() == "FIXTURE" and abs(cy(v) - cy(w)) < 2 and 0 < w[1] - v[3] < 20 for v in band)]
        qh = [w for w in band if w[0].upper() == "QUANTITY"]
        if len(ft) != 1 or len(qh) != 1:
            continue
        ft, qh = ft[0], qh[0]
        fv = [v for v in band if v[0].upper() == "FIXTURE" and abs(cy(v) - cy(ft)) < 2][0]
        fcx = (fv[1] + ft[3]) / 2
        for tw in sorted((w for w in ws if abs(cx(w) - fcx) <= 30 and 0 < w[2] - ft[4] < 160),
                         key=lambda w: w[2]):
            if norm_tag(tw[0]) not in want:
                continue
            cell = [w for w in ws if abs(cy(w) - cy(tw)) <= 4 and abs(cx(w) - cx(qh)) <= 25]
            if len(cell) == 1 and re.fullmatch(r"\d+", cell[0][0]):
                out.append({"level": lv[0], "tag": norm_tag(tw[0]), "qty": int(cell[0][0]),
                            "space": "common space" if "COMMON" in title else "named spaces",
                            "source": source, "table": "per floor"})
    # one figure per (table, level, tag): a tag printed on two rows of one
    # table (two spaces) is summed for that table
    agg: Dict[Tuple, Dict[str, Any]] = {}
    for r in out:
        k = (r["source"], r["table"], r["level"], r["tag"])
        if k in agg:
            agg[k]["qty"] += r["qty"]
            agg[k]["space"] = f"{agg[k]['space']}, {r['space']}"
        else:
            agg[k] = dict(r)
    return list(agg.values())


def floor_counts(results: Dict[str, Dict[str, Any]]) -> Dict[Tuple[Any, str], Dict[str, Any]]:
    """{(level, tag): {count, sheets, typical}} over sheets of ONE set. A
    drawing that names several levels (a typical plan) counts on each."""
    out: Dict[Tuple[Any, str], Dict[str, Any]] = {}
    for sheet, res in results.items():
        for t in res.get("tags") or []:
            if t.get("status") != "counted":
                continue
            for lv in t.get("levels") or []:
                e = out.setdefault((lv, t["tag"]), {"count": 0, "sheets": set(),
                                                    "typical": len(t["levels"]) > 1})
                e["count"] += 1
                e["sheets"].add(sheet)
    return out


def cross_check(results: Dict[str, Dict[str, Any]], totals: Sequence[Dict[str, Any]]
                ) -> List[Dict[str, Any]]:
    """Each printed (level, tag) total against the drawn count of ONE set:
    agrees | not checked beyond its spaces | conflict (a count that
    disagrees with a printed total states neither), and two printed totals
    that disagree with each other are a conflict too. Building totals
    (the sum over the printed levels) are checked the same way."""
    drawn = floor_counts(results)
    by: Dict[Tuple[Any, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in totals:
        by[(r["level"], r["tag"])].append(r)
    out = []

    def judge(n, printed_list, where, tag):
        qs = sorted({p["qty"] for p in printed_list})
        rec = {"where": where, "tag": tag, "sources": sorted({f"{p['source']} ({p['table']})" for p in printed_list}),
               "space": "; ".join(sorted({p["space"] for p in printed_list}))}
        if len(qs) > 1:
            rec.update(status="conflict", count=None, printed=None,
                       why=f"the printed totals disagree with each other ({', '.join(map(str, qs))}): "
                           "neither is stated, nor the count", evidence={"drawn": n, "printed": qs})
            return rec
        q = qs[0]
        if n == q:
            rec.update(status="agrees", count=n, printed=q)
        elif n > q:
            rec.update(status="not checked beyond its spaces", count=n, printed=q,
                       why=f"the printed total covers {rec['space']} only; {n - q} more are drawn "
                           "elsewhere in the drawings")
        else:
            rec.update(status="conflict", count=None, printed=None,
                       why="the drawing places fewer than the printed total for those spaces: "
                           "neither is stated", evidence={"drawn": n, "printed": q})
        return rec
    for (lv, tag), pl in sorted(by.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        n = drawn.get((lv, tag), {}).get("count", 0)
        out.append(judge(n, pl, lv, tag))
    # the building: per source table, the sum of its printed levels
    tables = defaultdict(lambda: defaultdict(int))
    lvls = defaultdict(lambda: defaultdict(set))
    for r in totals:
        tables[(r["source"], r["table"])][r["tag"]] += r["qty"]
        lvls[(r["source"], r["table"])][r["tag"]].add(r["level"])
    bt: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for (src, tb), per in tables.items():
        for tag, q in per.items():
            bt[tag].append({"qty": q, "source": src, "table": tb, "space": "named spaces",
                            "levels": lvls[(src, tb)][tag]})
    for tag, pl in sorted(bt.items()):
        # only tables that print every level the drawings have for that tag
        # are building totals; a table missing a level is not one
        drawn_lv = {lv for (lv, t) in drawn if t == tag}
        full = [p for p in pl if drawn_lv <= p["levels"] or not drawn_lv]
        if not full:
            continue
        n = sum(e["count"] for (lv, t), e in drawn.items() if t == tag)
        out.append(judge(n, full, "building", tag))
    return out


# ══════════════════════════════════════════════════════════════════════════
# The rows a pass would store, and the takeoff lines (designed; NOT written)
# ══════════════════════════════════════════════════════════════════════════

def _lvl_name(lv: Any) -> str:
    if isinstance(lv, int):
        names = {v: k for k, v in _ORD.items()}
        return f"{names.get(lv, str(lv)).upper()} FLOOR"
    return str(lv or "").upper()


def fixture_rows(result: Dict[str, Any], page_meta: Dict[str, Any], *,
                 track: Optional[str] = None,
                 checks: Sequence[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """One row per (drawing, tag) on one sheet - the count and where every
    tagged fixture is - plus one row per refused tag and per untagged
    drawing, or one sheet row when the sheet is refused. `page_meta`: the
    citation fields. `checks`: cross_check's records for the set; a floor
    whose check is a conflict stores its rows as conflicts with no count
    (a count that disagrees with a printed total states neither).

    Every row is `verified: False` with `verification: NOT_VERIFIED` - it is
    a takeoff line's candidate, never a chat count (ruling 77)."""
    cite = {k: page_meta.get(k) for k in ("project_id", "file_id", "page_id",
                                          "page_number", "sheet_number", "file_name")}
    base = dict(cite, record_type=RECORD_TYPE, count_basis=COUNT_BASIS, track=track,
                verified=False, verification=NOT_VERIFIED)
    if result.get("refused"):
        return [dict(base, scope="sheet", status="refused", refused=result["refused"],
                     tag=None, count=None)]
    conflict = {(c["where"], c["tag"]): c for c in checks if c.get("status") == "conflict"}
    agreed = {(c["where"], c["tag"]): c for c in checks if c.get("status") != "conflict"}
    out = []
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for t in result.get("tags") or []:
        if t.get("status") == "counted":
            groups[(t.get("title") or "", t["tag"])].append(t)
        else:
            out.append(dict(base, scope="tag", status="refused", refused=t.get("why"), tag=t["tag"],
                            count=None, position=[round(v, 1) for v in t["box"]],
                            title=t.get("title"), levels=t.get("levels") or []))
    for (title, tag), ts in sorted(groups.items()):
        lv = ts[0].get("levels") or []
        rec = dict(base, scope="drawing" if title else "sheet", title=title or None, levels=lv,
                   level_names=[_lvl_name(v) for v in lv], tag=tag, typical=len(lv) > 1)
        bad = [conflict[(v, tag)] for v in lv if (v, tag) in conflict]
        if bad:
            rec.update(status="conflict", count=None, refused=bad[0]["why"])
        else:
            rec.update(status="counted", count=len(ts),
                       positions=[[round(v, 1) for v in t["box"]] for t in ts],
                       fixture_boxes=[t["drawing_box"] for t in ts],
                       printed_check=[{k: agreed[(v, tag)].get(k) for k in ("status", "printed", "space", "sources")}
                                      for v in lv if (v, tag) in agreed])
        out.append(rec)
    for u in result.get("untagged") or []:
        out.append(dict(base, scope="fixture", status="untagged", tag=None, count=None,
                        could_be=u["could_be"], position=u["box"], title=u.get("title"),
                        refused="a fixture drawing with no tag: not counted"))
    return out


#: The takeoff trade these rows are listed under (plan_takeoff_export's
#: _light_fixture_lines: every counted or conflicting row is one "Not
#: verified - refused" line with no quantity, and so one review item).
TRADE = "Light fixtures"


# ══════════════════════════════════════════════════════════════════════════
# Scoring against a benchmark: per sheet (and drawing), or per floor
# ══════════════════════════════════════════════════════════════════════════

def evaluate(results: Dict[str, Dict[str, Any]], benchmark: Dict[str, Any]) -> Dict[str, Any]:
    """P/R of `results` ({sheet: count_sheet result}, ONE set) against
    whichever benchmark is loaded, naming whose it is (`source`, `kind`).

    benchmark["sheets"]: {sheet: {tag: {"expected"[, "false_positive_boxes"]}}}
    (a sheet with several drawings may key "sheet|TITLE" per drawing);
    benchmark["floors"]: {level ("SECOND FLOOR", "roof"): {tag: {"expected"}}}
    - a sub bid's per-floor quantity, matched to the drawings whose printed
    title names that level. A refused sheet is reported refused, never
    scored as zero found."""
    out: List[Dict[str, Any]] = []

    def score(found, exp, fp_boxes):
        if fp_boxes is not None:
            fp = len(fp_boxes)
            tp, basis = found - fp, "per instance"
        else:
            tp = min(found, exp)
            fp, basis = found - tp, "per count (an upper bound)"
        fn = max(exp - tp, 0)
        return {"found": found, "expected": exp, "tp": tp, "fp": fp, "fn": fn, "basis": basis,
                "p": round(tp / found, 3) if found else None, "r": round(tp / exp, 3) if exp else None}
    for key, wants in sorted((benchmark.get("sheets") or {}).items()):
        sheet, _, title = key.partition("|")
        res = results.get(sheet)
        for tag, e in wants.items():
            rec = {"scope": "sheet" if not title else "drawing", "where": key, "tag": norm_tag(tag)}
            if res is None:
                rec["status"] = "sheet not measured"
            elif res.get("refused"):
                rec.update(status="refused", why=res["refused"])
            else:
                n = sum(1 for t in res["tags"] if t["status"] == "counted" and t["tag"] == norm_tag(tag)
                        and (not title or (t.get("title") or "") == title))
                rec.update(status="scored", **score(n, int(e["expected"]), e.get("false_positive_boxes")))
            out.append(rec)
    drawn = floor_counts(results)
    for label, wants in sorted((benchmark.get("floors") or {}).items()):
        lv = levels_named(label) or levels_named(f"{label} floor")
        for tag, e in wants.items():
            rec = {"scope": "floor", "where": label, "tag": norm_tag(tag)}
            if len(lv) != 1:
                rec.update(status="unresolved", why=f"{label!r} names no single level")
            else:
                n = drawn.get((lv[0], norm_tag(tag)), {}).get("count", 0)
                rec.update(status="scored", **score(n, int(e["expected"]), None))
            out.append(rec)
    sc = [r for r in out if r["status"] == "scored"]
    tp, fp, fn = (sum(r[k] for r in sc) for k in ("tp", "fp", "fn"))
    return {"source": benchmark.get("source"), "kind": benchmark.get("kind"), "rows": out,
            "totals": {"tp": tp, "fp": fp, "fn": fn,
                       "p": round(tp / (tp + fp), 3) if tp + fp else None,
                       "r": round(tp / (tp + fn), 3) if tp + fn else None}}


__all__ = [
    "CAP_PT", "REACH", "SIG_TOL_PT", "COLLECTION", "RECORD_TYPE", "COUNT_BASIS",
    "NO_VOCAB", "NO_TAGS", "NO_DRAWING", "NOT_VERIFIED", "TRADE",
    "norm_tag", "schedule_tags", "in_table_row", "plan_tags", "fixture_objects",
    "signature", "same_block", "levels_named", "drawing_titles", "title_for",
    "count_sheet", "printed_totals", "floor_counts", "cross_check", "fixture_rows",
    "evaluate",
]
