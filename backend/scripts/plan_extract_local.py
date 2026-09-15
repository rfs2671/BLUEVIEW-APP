"""Run index-version-3 extraction against a PDF on disk. Reads nothing else.

WHY THIS EXISTS
===============

The extraction that production runs during indexing lives in
lib/plan_extract.py and takes its model call as an argument. This script
supplies one and points it at a local file, so a drawing set can be checked
BEFORE a merge and before a production re-index — the same prompts, the same
loop detection, the same caps, the same number verification, the same
chunking and the same count and existence answers.

It deliberately does NOT import server.py and does NOT open a database. The
only inputs are a PDF path and a model key in the environment.

WHAT DIFFERS FROM PRODUCTION, SAID PLAINLY
==========================================

  RENDERING. Production renders pages with pdf2image, which needs poppler on
  the machine. This script renders with PyMuPDF so it runs on a laptop without
  it. Same DPI rule: 250, or 300 for detail, enlarged and schedule sheets.

  QUESTION CLASSIFICATION. --ask uses a small local count-versus-existence
  test. The ANSWERING functions — answer_count, answer_existence and their
  formatters — are the exact ones production calls.

  THE MODEL. Whatever QWEN_API_BASE, QWEN_MODEL and QWEN_API_KEY are set to.
  The model id is printed at the start and written into every output file, so
  answers produced against one model are never mistaken for another's.

COST
====

Four vision calls per page (title block, schedules, notes, elements), plus one
Textract call per page with no usable text layer when --ocr is given. The plan
is printed before anything is sent; --dry-run stops there.

USAGE
=====

  set QWEN_API_KEY=...
  set QWEN_API_BASE=https://api.together.xyz/v1
  set QWEN_MODEL=Qwen/Qwen2.5-VL-7B-Instruct

  python backend/scripts/plan_extract_local.py plans/Arch.pdf plans/Struct.pdf ^
      --sheets S-001,S-100,A-500.00,P-100.00 --out plan-out ^
      --ask "how many piles" --ask "stucco thickness"
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from lib import plan_extract as pe  # noqa: E402

DPI = 250
DPI_DETAIL = 300


def _dpi_for(file_name: str) -> int:
    low = (file_name or "").lower()
    if any(tok in low for tok in ("detail", "enlarged", "schedule", "d-")):
        return DPI_DETAIL
    return DPI


def _page_texts(pdf_bytes: bytes) -> list:
    """The same call production's _pdf_page_texts makes."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [(p.extract_text() or "") for p in reader.pages]


def _render(pdf_path: str, page_index: int, dpi: int) -> bytes:
    import fitz  # PyMuPDF
    doc = fitz.open(pdf_path)
    try:
        pix = doc[page_index].get_pixmap(dpi=dpi)
        return pix.tobytes("jpeg", jpg_quality=85)
    finally:
        doc.close()


def _parse_pages(spec: str, total: int) -> set:
    out = set()
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return {p for p in out if 1 <= p <= total}


def _sheet_pattern(sheet: str) -> re.Pattern:
    """S-100 also finds S-100.00, the way the debug endpoint's filter does.

    pypdf joins a title block's cells without a separator, on both sides:
    'S-100.00LIGHT GAUGE', '2S-001.00GENERAL NOTES', 'A-500.0024 OF 31'. So a
    digit may precede, and the decimal suffix is exactly two digits with
    anything after it. A drawing list names every sheet, so text selection can
    also pick an index page — use --pick when the page is known."""
    base = re.escape(sheet.strip())
    if re.search(r"\.\d{2}$", sheet.strip()):
        return re.compile(r"(?<![A-Za-z])" + base, re.IGNORECASE)
    return re.compile(r"(?<![A-Za-z])" + base + r"(?:\.\d{2}|(?![\d.]))", re.IGNORECASE)


def _ocr(image_bytes: bytes):
    """Textract DetectDocumentText. None when boto3 has no credentials."""
    try:
        import boto3
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if max(img.size) > 9500:
            scale = 9500 / max(img.size)
            img = img.resize((int(img.width * scale), int(img.height * scale)))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=80)
        data = buf.getvalue()
        client = boto3.client("textract", region_name=os.environ.get("AWS_REGION") or "us-east-1")
        resp = client.detect_document_text(Document={"Bytes": data})
    except Exception as e:
        print(f"    OCR unavailable: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    return "\n".join(b["Text"] for b in resp.get("Blocks", []) if b.get("BlockType") == "LINE")


def _make_vlm_call(base: str, model: str, key: str, counter: dict):
    # ServerHttpClient, not httpx.AsyncClient: CI refuses a raw async client
    # anywhere under backend/, and this script is under backend/.
    from lib.server_http import ServerHttpClient

    async def call(image_b64: str, prompt: str, max_tokens: int):
        counter["calls"] += 1
        async with ServerHttpClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={
                    "model": model, "max_tokens": max_tokens, "temperature": 0,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                        {"type": "text", "text": prompt},
                    ]}],
                },
            )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        choice = resp.json()["choices"][0]
        return (choice["message"].get("content") or ""), choice.get("finish_reason")

    return call


VLM_FALLBACK = ("(no text answer - WhatsApp sends this to the vision model "
                "on the single best sheet)")


def _answers(asks, chunks, model, out_root: Path) -> str:
    """pe.answer_question is the function _answer_plan_from_chunks calls, so
    these are the answers WhatsApp would give from this extraction."""
    answers = []
    for q in asks:
        kind, attribute = pe.question_kind(q)
        ans = pe.answer_question(chunks, q, None)
        text = ans["text"] if ans else VLM_FALLBACK
        answers.append({"question": q, "kind": kind, "attribute": attribute,
                        "terms": pe.question_terms(q), "answer": text,
                        "outcome": ans["outcome"] if ans else "vlm_fallback",
                        "model": model})
        print(f"\nQ: {q}\n   [{kind or 'none'}{'/' + attribute if attribute else ''}]"
              f" terms={pe.question_terms(q)}\nA: {text}")
    out_root.mkdir(parents=True, exist_ok=True)
    apath = out_root / "answers.json"
    apath.write_text(json.dumps(answers, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(apath)


def _chunks_from_saved(folder: Path) -> list:
    chunks = []
    for f in sorted(folder.glob("*/*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        for c in pe.build_chunks(rec["fields"]):
            c["sheet_number"] = rec["fields"].get("sheet_number")
            c["page_number"] = rec.get("page_number")
            c["file"] = rec.get("file")
            chunks.append(c)
    return chunks


async def main_async(args) -> int:
    if args.answers_from:
        folder = Path(args.answers_from)
        chunks = _chunks_from_saved(folder)
        print(f"answering from saved extraction in {folder}: {len(chunks)} chunks, no model calls")
        print(_answers(args.ask, chunks, "(saved extraction)", folder))
        return 0

    base = os.environ.get("QWEN_API_BASE") or os.environ.get("QWEN_BASE_URL") or ""
    model = os.environ.get("QWEN_MODEL") or ""
    key = os.environ.get("QWEN_API_KEY") or ""

    out_root = Path(args.out)
    wanted = [s.strip() for s in (args.sheets or "").split(",") if s.strip()]

    plan = []
    for pdf in args.pdf:
        pdf_bytes = Path(pdf).read_bytes()
        texts = _page_texts(pdf_bytes)
        total = len(texts)
        selected = _parse_pages(args.pages, total) if args.pages else set()
        picked = False
        for spec in args.pick:
            name_part, _, pages = spec.rpartition(":")
            if name_part and name_part.lower() in Path(pdf).name.lower():
                selected |= _parse_pages(pages, total)
                picked = True
        if args.pick and not picked and not args.pages:
            plan.append((pdf, pdf_bytes, texts, []))
            continue
        if wanted and not args.pick:
            pats = [_sheet_pattern(s) for s in wanted]
            for i, t in enumerate(texts, start=1):
                if any(p.search(t or "") for p in pats):
                    selected.add(i)
        if not args.pages and not wanted and not args.pick:
            selected = set(range(1, total + 1))
        plan.append((pdf, pdf_bytes, texts, sorted(selected)))

    n_pages = sum(len(p[3]) for p in plan)
    print(f"model: {model or '(QWEN_MODEL unset)'}")
    print(f"endpoint: {base or '(QWEN_API_BASE unset)'}")
    for pdf, _b, texts, sel in plan:
        print(f"  {Path(pdf).name}: {len(sel)} of {len(texts)} page(s) selected: {sel}")
    print(f"vision calls planned: {n_pages * len(pe.SECTIONS)}"
          f"{'  (+ Textract for pages with no text layer)' if args.ocr else ''}")
    if wanted:
        found = set()
        for _pdf, _b, texts, _sel in plan:
            for s in wanted:
                if any(_sheet_pattern(s).search(t or "") for t in texts):
                    found.add(s)
        missing = [s for s in wanted if s not in found]
        if missing:
            print(f"NOT IN ANY TEXT LAYER: {missing} - on a scanned set, pass --pages instead")
    if args.dry_run:
        return 0
    if not (base and model and key):
        print("QWEN_API_BASE, QWEN_MODEL and QWEN_API_KEY must all be set.", file=sys.stderr)
        return 2

    counter = {"calls": 0}
    vlm_call = _make_vlm_call(base, model, key, counter)
    all_chunks = []
    written = []

    for pdf, pdf_bytes, texts, selected in plan:
        stem = Path(pdf).stem
        boiler = pe.boilerplate_lines(texts)
        dpi = _dpi_for(Path(pdf).name)
        folder = out_root / stem
        folder.mkdir(parents=True, exist_ok=True)
        for page_num in selected:
            t0 = time.perf_counter()
            text = texts[page_num - 1] if page_num - 1 < len(texts) else ""
            jpeg = _render(pdf, page_num - 1, dpi)
            source = pe.classify_text_source(text)
            if source == "sparse" and args.ocr:
                ocr = _ocr(jpeg)
                if ocr:
                    text, source = ocr, "ocr"
            if source == "sparse":
                source = "none" if not (text or "").strip() else "sparse"

            result = await pe.extract_page(
                image_b64=base64.b64encode(jpeg).decode("ascii"),
                page_text=text, vlm_call=vlm_call, boilerplate=boiler)
            fields = result["fields"]
            chunks = pe.build_chunks(fields, boiler)
            sheet = fields.get("sheet_number") or f"p{page_num:03d}"
            for c in chunks:
                c["sheet_number"] = fields.get("sheet_number")
                c["page_number"] = page_num
                c["file"] = Path(pdf).name
            all_chunks.extend(chunks)

            record = {
                "file": Path(pdf).name, "page_number": page_num,
                "model": model, "extraction_version": pe.EXTRACTION_VERSION,
                "text_source": source, "text_layer_chars": len(text or ""),
                "boilerplate_lines": len(boiler),
                "seconds": round(time.perf_counter() - t0, 1),
                "fields": fields, "flags": result["flags"],
                "number_flags": result["number_flags"],
                "prompt_text_chars": result["prompt_text_chars"],
                "prompt_text_truncated": result["prompt_text_truncated"],
                "chunks": [{k: v for k, v in c.items() if k != "payload"} for c in chunks],
                "legacy_fields": pe.legacy_fields(fields),
            }
            if args.raw:
                record["raw_vlm"] = result["raw_vlm"]
                record["raw_text"] = text
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", sheet)
            path = folder / f"{safe}__p{page_num:03d}.json"
            path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            written.append(str(path))
            bad = {k: v for k, v in result["flags"].items() if v}
            print(f"  p{page_num:>3} {sheet:<14} {source:<6} {record['seconds']:>5}s"
                  f"  flags={bad or 'none'}")

    if args.ask:
        written.append(_answers(args.ask, all_chunks, model, out_root))

    print(f"\nvision calls made: {counter['calls']}")
    print("written:")
    for w in written:
        print(f"  {w}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf", nargs="*", help="PDF file(s) of the drawing set")
    ap.add_argument("--answers-from", default="",
                    help="answer --ask from a previous --out folder; no PDFs, no model calls")
    ap.add_argument("--sheets", default="", help="comma list, e.g. S-001,S-100,A-500.00")
    ap.add_argument("--pages", default="", help="1-based page list, e.g. 1,3-5")
    ap.add_argument("--pick", action="append", default=[],
                    help='FILENAME_PART:PAGES, e.g. "AR - 3.28:24"; repeatable')
    ap.add_argument("--out", default="plan-out")
    ap.add_argument("--ask", action="append", default=[], help="question; repeatable")
    ap.add_argument("--ocr", action="store_true", help="Textract for pages with no text layer")
    ap.add_argument("--raw", action="store_true", help="include raw model output and page text")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, make no calls")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
