"""Run index-version-3 extraction against a PDF on disk. Reads nothing else.

WHY THIS EXISTS
===============

The extraction that production runs during indexing lives in
lib/plan_extract.py and lib/plan_text.py and takes its model call as an
argument. This script supplies one and points it at a local file, so a drawing
set can be checked BEFORE a merge and before a production re-index — the same
text-layer rebuild, the same one-call vector path, the same scanned-page path,
the same chunking, and the same question dispatch WhatsApp uses.

It deliberately does NOT import server.py and does NOT open a database.

WHAT DIFFERS FROM PRODUCTION, SAID PLAINLY
==========================================

  RENDERING. Production renders the page image with pdf2image (poppler). This
  renders with pdfplumber (pypdfium2) so it runs without poppler. Same DPI rule. The TEXT
  LAYER is read the same way in both: plan_text.page_layouts.

  TAG VOCABULARY. Production builds it from every page of the file at full
  detail; this builds it from every page with tables off (fast) plus the
  selected pages with tables on. The same marks come out of both on a set
  whose schedules are on the selected pages.

  THE MODEL. Whatever QWEN_API_BASE, QWEN_MODEL and QWEN_API_KEY are set to,
  printed at the start and written into every output file.

USAGE
=====

  railway run -- python backend/scripts/plan_extract_local.py plans/ST.pdf plans/AR.pdf ^
      --pick "PL - 6.29:2" --pages-all ST --pages-all AR --out plan-out ^
      --ask "how many piles" --ask "stucco thickness"

  python backend/scripts/plan_extract_local.py --answers-from plan-out --ask "..."
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
from lib import plan_text as pt  # noqa: E402

DPI = 250
DPI_DETAIL = 300
VLM_TIMEOUT = 240.0


def _dpi_for(file_name: str) -> int:
    low = (file_name or "").lower()
    if any(tok in low for tok in ("detail", "enlarged", "schedule", "d-")):
        return DPI_DETAIL
    return DPI


def _render(pdf_path: str, page_index: int, dpi: int) -> bytes:
    import pdfplumber  # renders through pypdfium2, which pdfplumber installs
    with pdfplumber.open(pdf_path) as pdf:
        img = pdf.pages[page_index].to_image(resolution=dpi).original
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        return buf.getvalue()


def _parse_pages(spec: str, total: int) -> set:
    out = set()
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if part.lower() == "all":
            out.update(range(1, total + 1))
        elif "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return {p for p in out if 1 <= p <= total}


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
        client = boto3.client("textract", region_name=os.environ.get("AWS_REGION") or "us-east-1")
        resp = client.detect_document_text(Document={"Bytes": buf.getvalue()})
    except Exception as e:
        print(f"    OCR unavailable: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    return "\n".join(b["Text"] for b in resp.get("Blocks", []) if b.get("BlockType") == "LINE")


def _make_vlm_call(base: str, model: str, key: str, counter: dict):
    # ServerHttpClient, not a raw async client: CI refuses one under backend/.
    from lib.server_http import ServerHttpClient

    async def call(image_b64: str, prompt: str, max_tokens: int):
        counter["calls"] += 1
        async with ServerHttpClient(timeout=VLM_TIMEOUT) as client:
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


def _selection(args, pdf: str, total: int) -> set:
    name = Path(pdf).name.lower()
    selected = _parse_pages(args.pages, total) if args.pages else set()
    for spec in args.pick:
        name_part, _, pages = spec.rpartition(":")
        if name_part and name_part.lower() in name:
            selected |= _parse_pages(pages, total)
    for part in args.pages_all:
        if part.lower() in name:
            selected |= set(range(1, total + 1))
    if not (args.pages or args.pick or args.pages_all):
        selected = set(range(1, total + 1))
    return selected


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

    plan = []
    for pdf in args.pdf:
        pdf_bytes = Path(pdf).read_bytes()
        # ONE PASS, tables included, as production does. Text parsing is the
        # slow part with pdfplumber, so it is not done twice.
        t_layout = time.perf_counter()
        fast = await asyncio.to_thread(pt.page_layouts, pdf_bytes)
        print(f"  {Path(pdf).name}: text layer + tables for {len(fast)} pages in "
              f"{time.perf_counter() - t_layout:.1f}s", flush=True)
        selected = sorted(_selection(args, pdf, len(fast)))
        if selected:
            plan.append((pdf, pdf_bytes, fast, selected))

    n_pages = sum(len(p[3]) for p in plan)
    vector = sum(1 for _pdf, _b, fast, sel in plan for p in sel
                 if pe.classify_text_source(fast[p - 1]["text"]) == "vector")
    print(f"model: {model or '(QWEN_MODEL unset)'}")
    print(f"endpoint: {base or '(QWEN_API_BASE unset)'}")
    for pdf, _b, fast, sel in plan:
        print(f"  {Path(pdf).name}: {len(sel)} of {len(fast)} page(s)")
    print(f"pages: {n_pages} ({vector} vector x1 call, {n_pages - vector} scanned "
          f"x{len(pe.SECTIONS)} calls) -> vision calls planned: "
          f"{vector + (n_pages - vector) * len(pe.SECTIONS)}")
    if args.dry_run:
        return 0
    if not (base and model and key):
        print("QWEN_API_BASE, QWEN_MODEL and QWEN_API_KEY must all be set.", file=sys.stderr)
        return 2

    counter = {"calls": 0}
    vlm_call = _make_vlm_call(base, model, key, counter)
    all_chunks: list = []
    written: list = []
    sem = asyncio.Semaphore(max(1, args.concurrency))

    for pdf, pdf_bytes, fast, selected in plan:
        full = fast
        vocab = pt.tag_vocabulary(fast)
        drawing_index = pt.drawing_list_index(fast)
        boiler = pe.boilerplate_lines([(L or {}).get("text", "") for L in fast])
        print(f"  {Path(pdf).name}: {len(vocab)} tags in vocabulary, "
              f"{len(drawing_index)} sheets in drawing list, {len(boiler)} boilerplate lines")
        folder = out_root / Path(pdf).stem
        folder.mkdir(parents=True, exist_ok=True)
        dpi = _dpi_for(Path(pdf).name)

        async def one(page_num: int):
            async with sem:
                t0 = time.perf_counter()
                layout = full[page_num - 1]
                jpeg = await asyncio.to_thread(_render, pdf, page_num - 1, dpi)
                b64 = base64.b64encode(jpeg).decode("ascii")
                if layout and pe.classify_text_source(layout["text"]) == "vector":
                    source, text = "vector", layout["text"]
                    result = await pe.extract_vector_page(
                        image_b64=b64, layout=layout, vlm_call=vlm_call,
                        boilerplate=boiler, tag_vocab=vocab, drawing_index=drawing_index)
                else:
                    text = (layout or {}).get("text", "")
                    source = "sparse"
                    if args.ocr:
                        ocr = await asyncio.to_thread(_ocr, jpeg)
                        if ocr:
                            text, source = ocr, "ocr"
                    if source == "sparse" and not text.strip():
                        source = "none"
                    result = await pe.extract_page(
                        image_b64=b64, page_text=text, vlm_call=vlm_call, boilerplate=boiler)
                fields = result["fields"]
                chunks = pe.build_chunks(fields, boiler)
                for c in chunks:
                    c["sheet_number"] = fields.get("sheet_number")
                    c["page_number"] = page_num
                    c["file"] = Path(pdf).name
                all_chunks.extend(chunks)
                sheet = fields.get("sheet_number") or f"p{page_num:03d}"
                record = {
                    "file": Path(pdf).name, "page_number": page_num,
                    "model": model, "extraction_version": pe.EXTRACTION_VERSION,
                    "text_source": source, "text_layer_chars": len(text or ""),
                    "vlm_calls": result.get("vlm_calls", len(pe.SECTIONS)),
                    "fractions_rebuilt": (layout or {}).get("fractions_rebuilt", 0),
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
                print(f"  p{page_num:>3} {sheet:<14} {source:<6} calls={record['vlm_calls']} "
                      f"{record['seconds']:>5}s flags={bad or 'none'}", flush=True)

        await asyncio.gather(*[one(p) for p in selected])

    if args.ask:
        written.append(_answers(args.ask, all_chunks, model, out_root))

    print(f"\nvision calls made: {counter['calls']}")
    print(f"written: {len(written)} files under {out_root}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf", nargs="*", help="PDF file(s) of the drawing set")
    ap.add_argument("--answers-from", default="",
                    help="answer --ask from a previous --out folder; no PDFs, no model calls")
    ap.add_argument("--pages", default="", help="1-based page list for every PDF, e.g. 1,3-5")
    ap.add_argument("--pick", action="append", default=[],
                    help='FILENAME_PART:PAGES, e.g. "AR - 3.28:24"; repeatable')
    ap.add_argument("--pages-all", action="append", default=[],
                    help="FILENAME_PART: every page of matching PDFs; repeatable")
    ap.add_argument("--concurrency", type=int, default=3,
                    help="pages in flight at once (production uses 3 per file)")
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
