"""CLASH v1 report: the flag list and one overlay crop per flag, from local PDFs. LOCAL, READ-ONLY.

    python scripts/clash_report.py --pdfs C:/Users/asddd/boyland-pdfs \\
        --tracks prod_tracks.json --out C:/Users/asddd/bv-worktrees/C1/flags
    python scripts/clash_report.py --pdfs ... --tracks ... --structural structural.json \\
        --stacks stacks.json --out ...

`--tracks` is the glyph pass's tracks as JSON, {track: [index row, ...]} (sheet_number,
sheet_title, file_name, page_number, page_id) - what server._glyph_pages returns, read
find()-only. Without `--structural` / `--stacks` the two inputs are computed here, exactly
as the glyph pass would (lib.plan_structural.run_tracks, lib.plan_stacks.run_stacks); with
them, their saved output is read ({"result": ...} as this script saves them, or the bare
result).

Writes, in --out:
  flags.json          lib.plan_clash.check: flags, not_checked, skipped, summary
  review_items.json   one review_queue.from_clash item per flag (BUILT, NOT ENQUEUED)
  <nn>_<kind>_....png one overlay crop per flag, labelled "flag for engineer review"
  index.png           a contact sheet of every crop

Nothing is written anywhere else: no database, no network. Every flag says
plan_clash.FLAG_LABEL; nothing here says pass, fail or clear.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import plan_clash as C  # noqa: E402

DPI = 216                   # 3x display pt
PAD_PT = 60.0               # 40 in of context around the flagged geometry
MIN_W_PT = 420.0            # a narrow wall still gets a crop wide enough to read the room
SYSTEM_RGB = {"sanitary": (0, 70, 230), "vent": (0, 160, 190), "storm": (0, 140, 60),
              "cold water": (40, 90, 255), "hot water": (220, 60, 0), "hot water return": (200, 90, 40),
              "gas": (200, 160, 0)}


def _pdf(pdfs: Path, name: str) -> Path:
    p = pdfs / name
    if p.exists():
        return p
    want = re.sub(r"\s+", " ", re.sub(r"\s+\.pdf$", ".pdf", name)).strip().lower()
    for q in pdfs.iterdir():
        if re.sub(r"\s+", " ", q.name).strip().lower() == want:
            return q
    raise FileNotFoundError(name)


def _font(size):
    from PIL import ImageFont
    for f in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _flag_geometry(f):
    out = [tuple(p) for p in f["frame"]["polygon_a"]]
    for p in f.get("pieces") or []:
        out += [tuple(q) for q in p["points"]]
    for s in f.get("stacks") or []:
        out += [(s["x"] - s["r"], s["y"] - s["r"]), (s["x"] + s["r"], s["y"] + s["r"])]
    if f["kind"] == C.KIND_INCONSISTENCY:
        for s in (f["stack"], f["agreed"]):
            out += [(s["x"] - s["r"], s["y"] - s["r"]), (s["x"] + s["r"], s["y"] + s["r"])]
        for p in f.get("reclassified_pieces") or []:
            out += [tuple(q) for q in p["points"]]
    return out


def render_flag(f, pdfs: Path, plumbing_rows, out_png: Path):
    """One crop: the A plan, the frame polygon (red), its hold-down zones
    (purple) and their 2 in tolerance (dashed), every pipe of the plumbing
    sheet nearby (pale), the flagged pieces or stacks highlighted, and a
    header that says FLAG_LABEL with sheets, tags, track and both margins."""
    from PIL import Image, ImageDraw
    from lib.plan_page import PlanPage
    a = f["a_sheet"]
    pg = PlanPage(str(_pdf(pdfs, a["file_name"])), int(a["page_number"]))
    try:
        x0, y0, x1, y1 = C.bbox(_flag_geometry(f))
        grow = max(0.0, (MIN_W_PT - (x1 - x0)) / 2 - PAD_PT)
        x0, y0 = max(0.0, x0 - PAD_PT - grow), max(0.0, y0 - PAD_PT)
        x1, y1 = min(pg.width, x1 + PAD_PT + grow), min(pg.height, y1 + PAD_PT)
        base = pg.render((x0, y0, x1, y1), DPI)
    finally:
        pg.close()
    s = DPI / 72.0
    g = base.convert("L").point(lambda v: 255 - (255 - v) * 0.45).convert("RGBA")
    ov = Image.new("RGBA", g.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    T = lambda x, y: ((x - x0) * s, (y - y0) * s)        # noqa: E731
    # context: every pipe of the flagged plumbing sheet(s) in the crop, pale
    sheets = {x.strip() for x in str(f["plumbing"].get("sheet_number") or "").split(",")}
    for prow in plumbing_rows:
        if (prow.get("record_type") != "pipe_segments" or prow.get("track") != f["track"]
                or prow.get("plumbing_sheet") not in sheets
                or str((prow.get("a_sheet") or {}).get("page_id")) != str(a.get("page_id"))):
            continue
        for sg in prow.get("segments") or []:
            if x0 <= sg[0] <= x1 and y0 <= sg[1] <= y1:
                c = SYSTEM_RGB.get(sg[4], (90, 90, 90))
                d.line([T(sg[0], sg[1]), T(sg[2], sg[3])], fill=c + (90,), width=2)
        for cv, sy in prow.get("curves") or []:
            if cv and x0 <= cv[0][0] <= x1 and y0 <= cv[0][1] <= y1:
                c = SYSTEM_RGB.get(sy, (90, 90, 90))
                d.line([T(*p) for p in cv], fill=c + (90,), width=2)
    fr = f["frame"]
    d.polygon([T(*p) for p in fr["polygon_a"]], fill=(220, 20, 60, 55), outline=(220, 20, 60, 255),
              width=3)
    tol = C.pts(f["tolerance_in"])
    for z in fr["hold_down_zones"]:
        d.polygon([T(*p) for p in z["polygon_a"]], fill=(150, 0, 200, 70), outline=(150, 0, 200, 255),
                  width=3)
        zx0, zy0, zx1, zy1 = C.bbox(z["polygon_a"])
        _dashed_rect(d, T(zx0 - tol, zy0 - tol), T(zx1 + tol, zy1 + tol), (150, 0, 200, 255))
    for p in f.get("pieces") or []:
        c = SYSTEM_RGB.get(f.get("system"), (0, 0, 0))
        hot = p.get("hold_down_end") is not None
        col = (255, 120, 0, 255) if hot else c + (255,)
        d.line([T(*q) for q in p["points"]], fill=col, width=5 if hot else 4)
    for st in f.get("stacks") or []:
        cx, cy = T(st["x"], st["y"])
        rr = max(st["r"] * s, 6)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(230, 0, 160, 255), width=4)
        if f["kind"] == C.KIND_STACK:
            _dashed_circle(d, cx, cy, (st["r"] + tol) * s, (230, 0, 160, 255))
    if f["kind"] == C.KIND_INCONSISTENCY:
        for p in f.get("reclassified_pieces") or []:
            d.line([T(*q) for q in p["points"]], fill=(150, 150, 150, 255), width=5)
        st, ag = f["stack"], f["agreed"]
        (cx, cy), (ax, ay) = T(st["x"], st["y"]), T(ag["x"], ag["y"])
        rr = max(st["r"] * s, 6)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(230, 0, 160, 255), width=4)
        _dashed_circle(d, ax, ay, rr, (0, 150, 90, 255))
        d.line([(ax, ay), (cx, cy)], fill=(0, 150, 90, 255), width=2)
    img = Image.alpha_composite(g, ov)
    dr = ImageDraw.Draw(img)
    if f["kind"] == C.KIND_INCONSISTENCY:
        st, ag = f["stack"], f["agreed"]
        cx, cy = T(st["x"], st["y"])
        dr.text((cx + 14, cy - 10), f"{st['tag_id']} as drawn ({st['plumbing_sheet']})",
                fill=(180, 0, 120, 255), font=_font(18))
        ax, ay = T(ag["x"], ag["y"])
        dr.text((ax + 14, ay - 10), f"{st['tag_id']} where {', '.join(ag['sheets'])} agree",
                fill=(0, 110, 60, 255), font=_font(18))
    for st in f.get("stacks") or []:
        cx, cy = T(st["x"], st["y"])
        dr.text((cx + 14, cy - 10), f"{st['tag_id']} ({st['plumbing_sheet']})", fill=(180, 0, 120, 255),
                font=_font(18))
    head = [w for line in _header(f) for w in (textwrap.wrap(line, 150) or [line])]
    F = _font(17)
    hh = 24 * len(head) + 12
    canvas = Image.new("RGB", (max(img.width, 1300), img.height + hh), (255, 255, 255))
    canvas.paste(img.convert("RGB"), (0, hh))
    cd = ImageDraw.Draw(canvas)
    cd.rectangle([0, 0, canvas.width, 30], fill=(255, 230, 0))
    for k, line in enumerate(head):
        cd.text((8, 6 + 24 * k), line, fill=(0, 0, 0), font=_font(19) if k == 0 else F)
    canvas.save(out_png)
    return canvas.size


def _dashed_rect(d, p0, p1, col, dash=8):
    (ax, ay), (bx, by) = p0, p1
    for (sx, sy), (ex, ey) in (((ax, ay), (bx, ay)), ((bx, ay), (bx, by)), ((bx, by), (ax, by)),
                               ((ax, by), (ax, ay))):
        L = math.hypot(ex - sx, ey - sy)
        n = max(1, int(L // dash))
        for i in range(0, n, 2):
            t0, t1 = i / n, min(1.0, (i + 1) / n)
            d.line([(sx + (ex - sx) * t0, sy + (ey - sy) * t0), (sx + (ex - sx) * t1, sy + (ey - sy) * t1)],
                   fill=col, width=2)


def _dashed_circle(d, cx, cy, r, col):
    for i in range(0, 36, 2):
        d.arc([cx - r, cy - r, cx + r, cy + r], i * 10, i * 10 + 10, fill=col, width=2)


def _header_inconsistency(f):
    fr, a = f["frame"], f["a_sheet"]
    c = f["counts"]
    lines = [f"{C.FLAG_LABEL.upper()}  -  drawing inconsistency (not a clash): {f['message']}",
             f"track {f['track']}  |  level {f['level']}  |  frame {fr['label']}  |  "
             f"A {a['sheet_number']} ({a['file_name']} p{a['page_number']})  |  "
             f"S {fr['s_sheet']['sheet_number']}  |  P {f['plumbing']['sheet_number']}",
             f"registration margins (best / second peak): {C.margins_text(f)}",
             f["detail"],
             f"{c['reclassified_pieces']} drawn pipe pieces on the offset stack are listed here instead of "
             f"as pipe flags ({c['straight']} straight, {c['curved']} curved; grey)"]
    if f.get("structure_note"):
        lines.append(f["structure_note"])
    lines.append("magenta: stack as drawn  |  green dashed: where the other floors agree  |  red: frame polygon")
    return lines


def _header(f):
    if f["kind"] == C.KIND_INCONSISTENCY:
        return _header_inconsistency(f)
    fr, a = f["frame"], f["a_sheet"]
    kind = {C.KIND_PIPE: "pipe pieces inside a shear wall / braced frame",
            C.KIND_HOLD_DOWN: f"pipe pieces within {f['tolerance_in']:g} in of a hold-down end post",
            C.KIND_STACK: f"stacks inside or within {f['tolerance_in']:g} in of a frame"}[f["kind"]]
    c = f.get("counts") or {}
    lines = [f"{C.FLAG_LABEL.upper()}  -  {kind}",
             f"track {f['track']}  |  level {f['level']}  |  frame {fr['label']}  |  "
             f"A {a['sheet_number']} ({a['file_name']} p{a['page_number']})  |  S {fr['s_sheet']['sheet_number']}"
             f"  |  P {f['plumbing']['sheet_number']}" + (f"  |  system {f['system']}" if f.get("system") else ""),
             f"registration margins (best / second peak): {C.margins_text(f)}"]
    if f["kind"] == C.KIND_STACK:
        lines.append("stacks: " + "; ".join(
            f"{s['tag_id']} {s['relation']}" + (f", rim {s['edge_clearance_in']} in from the face"
                                                if s.get("edge_clearance_in") is not None else "")
            + f", gap {s['distance_in']} in" for s in f["stacks"]))
    else:
        lines.append(f"pieces {c.get('pieces')} ({c.get('straight')} straight, {c.get('curved')} curved)  |  "
                     f"within {f['tolerance_in']:g} in of an end post: {c.get('in_hold_down_zone')}  |  "
                     f"touching an end post as drawn: {c.get('touching_end_post')}  (orange = in the zone)")
    if f.get("structure_note"):
        lines.append(f["structure_note"])
    lines.append("red: frame polygon  |  purple: hold-down zone (end post), dashed: +2 in  |  pale: the sheet's other pipes")
    return lines


def one_per_group(items):
    """The crops the rulings need: one per distinct place (frame tag, kind, system) - the filed
    track's FLOOR_4 when it has the place, else the first - and every inconsistency item of the
    filed track. The other floors and the owner's set repeat the same wall."""
    prefer = {"FLOOR_4": 0, "MEZZANINE": 1}
    best = {}
    for k, f in enumerate(items):
        place = (f["frame"].get("tag") or f["frame"]["label"], f["kind"], f.get("system"),
                 f["stack"]["tag_id"] if f["kind"] == C.KIND_INCONSISTENCY else None)
        rank = (f["track"] != "filed", prefer.get(f["level"], 9), k)
        if place not in best or rank < best[place][0]:
            best[place] = (rank, f)
    return [f for _r, f in sorted(best.values(), key=lambda t: t[0][2])]


def contact_sheet(pngs, out_png: Path, cols=4, w=480):
    from PIL import Image, ImageDraw
    thumbs = []
    for p in pngs:
        im = Image.open(p).convert("RGB")
        im.thumbnail((w, w * 2))
        thumbs.append((p, im))
    if not thumbs:
        return None
    rows = math.ceil(len(thumbs) / cols)
    hmax = max(im.height for _p, im in thumbs) + 22
    sheet = Image.new("RGB", (cols * (w + 8), rows * hmax + 40), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    d.text((8, 8), f"{C.FLAG_LABEL.upper()} - {len(thumbs)} crops (flags and drawing inconsistencies)", fill=(0, 0, 0), font=_font(22))
    for k, (p, im) in enumerate(thumbs):
        x, y = (k % cols) * (w + 8), 40 + (k // cols) * hmax
        sheet.paste(im, (x, y + 20))
        d.text((x + 2, y + 2), Path(p).stem[:60], fill=(0, 0, 0), font=_font(13))
    sheet.save(out_png)
    return sheet.size


def _result(path):
    got = json.load(open(path, encoding="utf-8"))
    return got.get("result", got)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdfs", required=True)
    ap.add_argument("--tracks", help="{track: [index rows]} (needed unless both inputs are given)")
    ap.add_argument("--structural", help="saved plan_structural.run_tracks output")
    ap.add_argument("--stacks", help="saved plan_stacks.run_stacks output")
    ap.add_argument("--out", required=True)
    ap.add_argument("--company-id", default="(company)")
    ap.add_argument("--project-id", default="(project)")
    ap.add_argument("--no-crops", action="store_true")
    ap.add_argument("--all-crops", action="store_true",
                    help="a crop for every flag and inconsistency (default: one per distinct place)")
    args = ap.parse_args(argv)
    pdfs, out = Path(args.pdfs), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tracks = None
    if args.tracks:
        tracks = [(t, list(ps)) for t, ps in json.load(open(args.tracks, encoding="utf-8")).items()
                  if not t.startswith("_")]

    def open_page(p):
        from lib.plan_page import PlanPage
        return PlanPage(str(_pdf(pdfs, p["file_name"])), int(p["page_number"]))

    if args.structural:
        st = _result(args.structural)
    else:
        from lib import plan_structural
        st = plan_structural.run_tracks(tracks, open_page)
    structure = [r for t in st.values() for r in t["rows"]] if isinstance(st, dict) and "rows" not in st \
        else st["rows"]
    if args.stacks:
        plumbing = _result(args.stacks)["rows"]
    else:
        from lib import plan_stacks
        plumbing = plan_stacks.run_stacks(tracks, open_page, None, 56.0)["rows"]
    res = C.check(structure, plumbing)
    json.dump(res, open(out / "flags.json", "w", encoding="utf-8"), indent=1, default=str)
    items = C.review_items(res["flags"], args.company_id, args.project_id,
                           now=datetime.now(timezone.utc))
    json.dump(items, open(out / "review_items.json", "w", encoding="utf-8"), indent=1, default=str)
    pngs = []
    if not args.no_crops:
        items = res["flags"] + res["inconsistencies"]
        for k, f in enumerate(items if args.all_crops else one_per_group(items), 1):
            name = re.sub(r"[^A-Za-z0-9_.-]+", "_", "_".join(str(x) for x in (
                f"{k:02d}", f["track"], f["level"], f["frame"]["label"].split(" (")[0],
                f["plumbing"]["sheet_number"],
                f.get("system") or ("stacks" if f["kind"] == C.KIND_STACK else f["stack"]["tag_id"]),
                f["kind"])))
            png = out / f"{name}.png"
            render_flag(f, pdfs, plumbing, png)
            f["crop"] = str(png)
            pngs.append(png)
        contact_sheet(pngs, out / "index.png")
        json.dump(res, open(out / "flags.json", "w", encoding="utf-8"), indent=1, default=str)
    s = res["summary"]
    print(f"{s['flags']} flags ({C.FLAG_LABEL}), {s['inconsistencies']} drawing inconsistencies "
          f"({s['reclassified_pieces']} pipe pieces reclassified), {s['not_checked']} not checked, "
          f"{s['skipped']} skipped")
    for k, v in s["by_track_kind"].items():
        print(f"  {k}: {v}")
    return res


if __name__ == "__main__":
    main()
