"""What one sheet SAYS: stored records and the PDF's own text layer. READ-ONLY.

    railway run python scripts/plan_sheet_text.py --project-name "Boyland" \\
        --sheet A-302.00 --contains "ROOF ASSEMBLY" --detail 4
    railway run python scripts/plan_sheet_text.py --project-id 6a5f... --sheet A-302.00

Built for Oct 27, 2026 (588 Thomas S Boyland): "do I need spray foam on 5th
floor ceiling". The 5th floor is the Mezzanine (A-104.00), its ceiling is the
roof assembly, and the answer has to quote A-302.00 detail 4 (ROOF ASSEMBLY
DETAIL) exactly. This prints that text so a person can copy it, never a
paraphrase of it.

For every indexed page whose sheet number is --sheet (exact, case-blind; else
the same letters and digits with the punctuation ignored, and it says so):

  * the page: file, page number, title, indexed_at, and whether it is CURRENT
    (its file is live and not superseded by a live file -- the same rule as
    server._current_page_filter / _live_plan_file_ids);
  * STORED PAGE TEXT (document_page_index.raw_text, what the indexer kept):
    the lines around each --contains hit;
  * STORED RECORDS (plan_records for that page): every record whose quote or
    label holds --contains (all of them without it) -- record type, ordinal,
    tier, source, bbox, label and the FULL quote;
  * THE PDF TEXT LAYER: the file's PDF from R2 (project_files.r2_key, the
    bucket R2_BUCKET_NAME -- what indexing downloads), read with
    lib/plan_text.page_layout_at (pdfplumber, the indexer's own text pass).
    Each text block holding --contains, and with --detail N each block that
    prints N on a line of its own or beside the --contains words (a detail
    bubble / title), with its bbox -- and every block within --near points of
    one of those, in reading order. --all-blocks prints the whole page.

Text is printed exactly as stored / extracted: no cutting, no rewording.
Nothing is written to the database; the PDF goes to a temp directory that is
removed afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: A file whose index_status.state is this is not searched (server.py).
COMBINED_SET_SKIPPED = "skipped_combined_set"
#: Points (1/72 inch) around a matched block that count as "around" it.
NEAR_PT = 72.0
#: Lines of stored page text printed either side of a hit.
CONTEXT_LINES = 6

Fetch = Callable[[str], Tuple[Optional[bytes], Optional[str]]]


def norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().upper()


def sheet_key(s: Any) -> str:
    """A sheet number with its punctuation ignored: A-302.00 -> A30200."""
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def holds(text: Any, term: str) -> bool:
    return bool(term) and norm(term) in norm(text)


def detail_line(text: Any, detail: str, term: str = "") -> bool:
    """A line that is the detail number alone (the bubble), or the number
    as its own token on a line that also holds the --contains words."""
    if not detail:
        return False
    tok = re.compile(rf"(?<![\w.]){re.escape(detail)}(?![\w.])")
    for line in str(text or "").splitlines():
        s = line.strip()
        if s == detail:
            return True
        if term and holds(s, term) and tok.search(s):
            return True
    return False


def fmt_bbox(b: Any) -> str:
    if not b:
        return "none"
    try:
        return "[" + ", ".join(f"{float(v):.1f}" for v in b) + "]"
    except (TypeError, ValueError):
        return str(b)


def around(text: str, term: str, n: int = CONTEXT_LINES) -> List[Tuple[int, int]]:
    """(start, end) line ranges around each hit of `term`, merged."""
    lines = str(text or "").splitlines()
    spans: List[Tuple[int, int]] = []
    for i, line in enumerate(lines):
        if holds(line, term):
            a, b = max(0, i - n), min(len(lines), i + n + 1)
            if spans and a <= spans[-1][1]:
                spans[-1] = (spans[-1][0], max(spans[-1][1], b))
            else:
                spans.append((a, b))
    return spans


def gap(a: Sequence[float], b: Sequence[float]) -> float:
    """Distance between two boxes (0 when they touch or overlap)."""
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return (dx * dx + dy * dy) ** 0.5


def pick_blocks(blocks: List[Dict[str, Any]], term: str, detail: str,
                near: float) -> Tuple[List[int], List[int]]:
    """(matched block indexes, nearby block indexes), each in reading order."""
    hit = [i for i, b in enumerate(blocks)
           if holds(b.get("text"), term) or detail_line(b.get("text"), detail, term)]
    hitset = set(hit)
    close = [i for i, b in enumerate(blocks) if i not in hitset and any(
        gap(b["bbox"], blocks[j]["bbox"]) <= near for j in hit)]

    def order(i):
        bb = blocks[i]["bbox"]
        return (round(bb[1]), bb[0])
    return sorted(hit, key=order), sorted(close, key=order)


def default_fetch(key: str) -> Tuple[Optional[bytes], Optional[str]]:
    """The object at `key` in R2_BUCKET_NAME, made the way server._get_r2_client
    makes its client. (bytes, None) or (None, why)."""
    need = ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT_URL", "R2_BUCKET_NAME")
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        return None, "R2 not configured (" + ", ".join(missing) + ")"
    try:
        import boto3
        from botocore.config import Config
        client = boto3.client(
            "s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            config=Config(signature_version="s3v4"), region_name="auto")
        return client.get_object(Bucket=os.environ["R2_BUCKET_NAME"], Key=key)["Body"].read(), None
    except Exception as e:  # shown, never swallowed
        code = (getattr(e, "response", None) or {}).get("Error", {}).get("Code")
        return None, f"{type(e).__name__}{(' ' + code) if code else ''}"


def page_layout(pdf_path: str, page_number: int) -> Dict[str, Any]:
    from lib import plan_text
    return plan_text.page_layout_at(pdf_path, page_number, with_tables=False)


async def find_project(db, name: str, pid: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    if pid:
        q: Dict[str, Any] = {"_id": pid}
        try:
            from bson import ObjectId
            if ObjectId.is_valid(pid):
                q = {"$or": [{"_id": ObjectId(pid)}, {"_id": pid}]}
        except ImportError:
            pass
        row = await db.projects.find_one(q, {"name": 1})
        return row, [row] if row else []
    rows = await db.projects.find(
        {"name": {"$regex": "(?i)" + re.escape(name)}, "is_deleted": {"$ne": True}},
        {"name": 1}).to_list(50)
    return (rows[0] if len(rows) == 1 else None), rows


async def run(db, a, out=print, fetch: Fetch = default_fetch, layout=page_layout) -> int:
    proj, cands = await find_project(db, a.project_name or "", a.project_id or "")
    if not proj:
        if not cands:
            out("No project matches.")
        else:
            out(f"{len(cands)} projects match -- pass --project-id:")
            for p in cands:
                out(f"  {p.get('_id')}  {p.get('name')}")
        return 2
    pid = str(proj["_id"])
    out(f"project {proj.get('name')}  {pid}")
    files = await db.project_files.find(
        {"project_id": pid}, {"name": 1, "r2_key": 1, "is_deleted": 1, "index_status": 1}).to_list(2000)
    by_id = {str(f["_id"]): f for f in files}
    live = {fid for fid, f in by_id.items() if not f.get("is_deleted")
            and (f.get("index_status") or {}).get("state") != COMBINED_SET_SKIPPED}

    want = a.sheet.strip()
    pages = await db.document_page_index.find(
        {"project_id": pid, "sheet_number": {"$regex": "(?i)^" + re.escape(want) + "$"}},
        {"embedding": 0}).to_list(500)
    if not pages:
        numbers = await db.document_page_index.distinct("sheet_number", {"project_id": pid})
        loose = sorted({str(s) for s in numbers if s and sheet_key(s) == sheet_key(want)})
        if loose:
            out(f"No page is numbered exactly {want}; the same letters and digits: {', '.join(loose)}")
            pages = await db.document_page_index.find(
                {"project_id": pid, "sheet_number": {"$in": loose}}, {"embedding": 0}).to_list(500)
    if not pages:
        out(f"No indexed page on this project is numbered {want}.")
        return 1
    pages.sort(key=lambda p: (str(p.get("file_name") or ""), int(p.get("page_number") or 0)))
    term, detail = (a.contains or "").strip(), (a.detail or "").strip()
    out(f"sheet {want} · {len(pages)} indexed page(s)"
        + (f" · contains {term!r}" if term else "") + (f" · detail {detail}" if detail else ""))

    pdf_cache: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    tmp = tempfile.mkdtemp(prefix="sheettext-")
    try:
        for p in pages:
            fid = str(p.get("file_id") or "")
            frow = by_id.get(fid) or {}
            current = fid in live and str(p.get("superseded_by") or "") not in live
            out("\n" + "=" * 78)
            out(f"PAGE {p.get('sheet_number')} · {p.get('file_name') or frow.get('name')} "
                f"p{p.get('page_number')} · {p.get('sheet_title') or '(no title)'}")
            out(f"  page id {p.get('_id')} · file id {fid} · indexed_at {p.get('indexed_at')} · "
                + ("CURRENT" if current else
                   "NOT CURRENT (" + ("file deleted or not searched" if fid not in live
                                      else f"superseded by {p.get('superseded_by')}") + ")"))

            raw = str(p.get("raw_text") or "")
            out(f"\n  STORED PAGE TEXT (document_page_index.raw_text, {len(raw)} chars)")
            if not raw:
                out("    (none stored)")
            elif not term:
                out("    (pass --contains to print the lines around it)")
            else:
                spans = around(raw, term)
                if not spans:
                    out(f"    {term!r} is not in the stored text")
                lines = raw.splitlines()
                for s, e in spans:
                    out(f"    --- lines {s + 1}-{e} ---")
                    for line in lines[s:e]:
                        out(f"    | {line}")

            recs = await db.plan_records.find(
                {"project_id": pid, "page_id": str(p["_id"])}, {"embedding": 0}).to_list(None)
            recs.sort(key=lambda r: (str(r.get("record_type")), int(r.get("ordinal") or 0)))
            shown = [r for r in recs if not term or holds(r.get("quote"), term)
                     or holds(r.get("label"), term)
                     or detail_line(r.get("quote"), detail, term)]
            out(f"\n  STORED RECORDS (plan_records): {len(shown)} of {len(recs)} on this page"
                + (" hold the term" if term else ""))
            for r in shown:
                out(f"  - {r.get('record_type')} #{r.get('ordinal')} · tier {r.get('tier')} · "
                    f"source {r.get('source')} · bbox {fmt_bbox(r.get('bbox'))}"
                    + (f" · label {r.get('label')!r}" if r.get("label") else ""))
                for line in str(r.get("quote") or "").splitlines() or [""]:
                    out(f"      | {line}")

            out("\n  PDF TEXT LAYER (R2 source, lib/plan_text.page_layout_at)")
            key = frow.get("r2_key")
            if not key:
                out("    no project_files row with an r2_key for this file -- cannot read the PDF")
                continue
            if fid not in pdf_cache:
                data, why = fetch(key)
                path = None
                if data:
                    path = os.path.join(tmp, f"{len(pdf_cache)}.pdf")
                    with open(path, "wb") as fh:
                        fh.write(data)
                pdf_cache[fid] = (path, why)
            path, why = pdf_cache[fid]
            if not path:
                out(f"    could not download {key}: {why or 'empty object'}")
                continue
            try:
                L = layout(path, int(p.get("page_number") or 0))
            except Exception as e:
                out(f"    could not read page {p.get('page_number')}: {type(e).__name__}: {e}")
                continue
            blocks = [b for b in L.get("blocks") or [] if b.get("bbox")]
            page_text = str(L.get("text") or "")
            out(f"    page {L.get('width')} x {L.get('height')} pt · {len(blocks)} text blocks · "
                f"{len(page_text)} chars")
            if a.all_blocks or not (term or detail):
                sel, close = list(range(len(blocks))), []
            else:
                sel, close = pick_blocks(blocks, term, detail, a.near)
            if not sel:
                out(f"    no block holds {term!r}" + (f" or detail {detail}" if detail else ""))
            for label, idx in (("MATCH", sel), (f"WITHIN {a.near:g}pt", close)):
                for i in idx:
                    b = blocks[i]
                    out(f"    [{label}] block {i} bbox {fmt_bbox(b['bbox'])}")
                    for line in b.get("lines") or str(b.get("text") or "").splitlines():
                        out(f"      | {line}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--project-name", help="a part of the project's name")
    who.add_argument("--project-id")
    ap.add_argument("--sheet", required=True, help="the sheet number, e.g. A-302.00")
    ap.add_argument("--contains", default="", help="text to find, e.g. 'ROOF ASSEMBLY'")
    ap.add_argument("--detail", default="", help="a detail number on the sheet, e.g. 4")
    ap.add_argument("--near", type=float, default=NEAR_PT,
                    help=f"points around a matched block to print too (default {NEAR_PT:g})")
    ap.add_argument("--all-blocks", action="store_true", help="print every text block on the page")
    a = ap.parse_args(argv)
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        sys.exit("MONGO_URL / DB_NAME are not set — run under `railway run`.")
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    return asyncio.run(run(db, a))


if __name__ == "__main__":
    raise SystemExit(main())
