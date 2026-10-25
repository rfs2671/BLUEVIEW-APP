"""Compiling a project PDF into its tile pyramid and spatial index, resumably.

THE SHAPE OF THE WORK
=====================

A file is queued (`sheet_tile_jobs`, one row per file, like `plan_index_jobs`) when a
PDF is uploaded, by a sweep for files that have none, or by the backfill script. A
single worker claims it on a lease and compiles in TWO PASSES so a 100 MB plan set
is usable in minutes, not hours:

  pass 1   every page: the text index, the preview and levels 0..2 (4096 px on the
           long side, enough to read a sheet). When it finishes the file is
           `ready` and the viewer switches to it.
  pass 2   every page: levels 3..z_max (up to 16384 px) for deep zoom. When it
           finishes the file is `complete`. The viewer already works at the deepest
           level a page has; deeper tiles appear as they land.

Per-page state lives in `sheet_pages` (levels built, index built), so a restart, a
lease that ran out or a retry resumes at the first thing not done and never
re-renders a finished level.

STORAGE
=======

R2, deterministic keys, versioned by a BUILD id (tile + index schema, the file's
cache_version and size) so a re-uploaded file never serves another file's tiles:

    projects/{pid}/files/{fid}/sheets/{build}/p{page}/z{z}/{x}_{y}.webp
    projects/{pid}/files/{fid}/sheets/{build}/p{page}/preview.webp
    projects/{pid}/files/{fid}/sheets/{build}/p{page}/index.json.gz

The raw PDF is untouched in R2: it stays the file people download and export.
Blank tiles are not stored (see sheet_tiles). Other builds of the same file are
deleted (by known key, see `purge`) once a build is complete.

EVERY EXTERNAL THING IS INJECTED (`Ctx`): the database, R2 put / delete, where the
PDF comes from, the render subprocess, the index builder and the clock. That is
what lets the tests run the real orchestration without R2, Mongo or a worker
process, and what lets the server give it the real ones.

Nothing here sends anything to anyone.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from pymongo import ReturnDocument

from lib import sheet_index, sheet_tiles

JOBS = "sheet_tile_jobs"
PAGES = "sheet_pages"
PASS1_MAX_Z = 2
MAX_PAGES = 600                 # a set larger than this keeps the legacy viewer
LEASE_SECONDS = 300
HEARTBEAT_SECONDS = 60
MAX_ATTEMPTS = 3
UPLOAD_AT_ONCE = 16
PAGE_TIMEOUT_SECONDS = 900      # one page, one pass: a render that takes longer is killed
STATUSES_ACTIVE = ("queued", "running")

log = logging.getLogger(__name__)


# ── keys (pure) ──────────────────────────────────────────────────────────────

def build_id(file_rec: Dict[str, Any]) -> str:
    """Names one version of one file's tiles. Changes when the file's bytes do
    (cache_version / size) or when the tile or index layout does."""
    return (f"t{sheet_tiles.SCHEMA}i{sheet_index.SCHEMA}"
            f"c{int(file_rec.get('cache_version') or 0)}s{int(file_rec.get('size') or 0)}")


def file_prefix(project_id: str, file_id: str) -> str:
    return f"projects/{project_id}/files/{file_id}/sheets/"


def build_prefix(project_id: str, file_id: str, build: str) -> str:
    return f"{file_prefix(project_id, file_id)}{build}"


def tile_key(project_id: str, file_id: str, build: str, page: int, z: int, x: int, y: int) -> str:
    return f"{build_prefix(project_id, file_id, build)}/p{page}/z{z}/{x}_{y}.webp"


def preview_key(project_id: str, file_id: str, build: str, page: int) -> str:
    return f"{build_prefix(project_id, file_id, build)}/p{page}/preview.webp"


def index_key(project_id: str, file_id: str, build: str, page: int) -> str:
    return f"{build_prefix(project_id, file_id, build)}/p{page}/index.json.gz"


def page_doc_id(file_id: str, build: str, page: int) -> str:
    return f"{file_id}:{build}:{page}"


def is_pdf_name(name: Any) -> bool:
    return str(name or "").strip().lower().endswith(".pdf")


# ── injected IO ──────────────────────────────────────────────────────────────

_render_gate: Optional[asyncio.Lock] = None


RENDER_NICE = 10


def _lower_priority() -> None:
    """Run in the child before exec: a compile is minutes of CPU, and it shares the container
    with the API. At a lower priority it uses what is idle and yields to requests, so a reader
    zooming a drawing is not slowed by one being compiled."""
    try:
        os.nice(RENDER_NICE)
    except OSError:
        pass


def _gate() -> asyncio.Lock:
    """One pdfium child at a time per process, however the compile was triggered
    (upload, open, sweep, manual): pdfium is not thread-safe, and two 16k renders at once
    are the memory spike this pipeline is built to avoid. Created on first use so it
    belongs to the running loop."""
    global _render_gate
    if _render_gate is None:
        _render_gate = asyncio.Lock()
    return _render_gate


async def _run_cli(args: Sequence[str], timeout: float, what: str) -> bytes:
    """Run `python -m lib.sheet_tiles <args>` in a child process and return its stdout.
    A pdfium crash or a memory spike kills the child, never the API."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    async with _gate():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "lib.sheet_tiles", *args,
            cwd=backend_dir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            preexec_fn=_lower_priority if os.name == "posix" else None)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"{what} took longer than {timeout:.0f}s")
        except BaseException:                                    # cancelled: do not leave the child running
            proc.kill()
            await proc.wait()
            raise
    if proc.returncode != 0:
        raise RuntimeError(f"{what} failed: {(err or b'').decode('utf-8', 'replace')[-300:]}")
    return out or b""


async def _default_page_info(pdf_path: str) -> List[Tuple[float, float]]:
    out = await _run_cli(["info", pdf_path], 120, "reading the page sizes")
    return [(float(p["width_pt"]), float(p["height_pt"])) for p in json.loads(out.decode("utf-8"))["pages"]]


async def _default_run_compile(pdf_path: str, page_index: int, out_dir: str, levels: Sequence[int]) -> Dict[str, Any]:
    """The render, in a child process. Returns the manifest the child wrote."""
    spec = ",".join(str(z) for z in levels)
    await _run_cli(["compile", pdf_path, str(page_index), out_dir, "--levels", spec], PAGE_TIMEOUT_SECONDS,
                   f"render of page {page_index + 1}")
    with open(os.path.join(out_dir, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


async def _default_build_index(pdf_path: str, page_index: int) -> Dict[str, Any]:
    return await asyncio.to_thread(sheet_index.build_page_index, pdf_path, page_index, None)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Ctx:
    db: Any
    put_object: Callable[[str, bytes, str, Optional[str]], Awaitable[None]]
    fetch_pdf: Callable[[Dict[str, Any], str], Awaitable[None]]
    delete_keys: Optional[Callable[[List[str]], Awaitable[int]]] = None         # R2 delete by KNOWN keys
    page_info: Callable[[str], Awaitable[List[Tuple[float, float]]]] = _default_page_info
    run_compile: Callable[[str, int, str, Sequence[int]], Awaitable[Dict[str, Any]]] = _default_run_compile
    build_index: Callable[[str, int], Awaitable[Dict[str, Any]]] = _default_build_index
    now: Callable[[], datetime] = _utcnow
    logger: logging.Logger = field(default_factory=lambda: log)


# ── the queue ────────────────────────────────────────────────────────────────

def _as_utc(ts: Any) -> Any:
    if isinstance(ts, datetime) and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


async def set_summary(db: Any, project_id: str, file_id: str, to_query_id: Callable[[str], Any], **fields: Any) -> None:
    """Merge `fields` into project_files.tiles (the one place a client reads status)."""
    await db.project_files.update_one(
        {"_id": to_query_id(file_id), "project_id": project_id},
        {"$set": {f"tiles.{k}": v for k, v in fields.items()}})


# Who is waiting decides the order. Someone has the drawing open (or an admin asked): first.
# An upload: next. The background sweep and the backfill: whenever nothing else is waiting.
PRIORITY = {"open": 3, "manual": 3, "upload": 2}


def priority_of(source: str) -> int:
    return PRIORITY.get(source, 1)


async def enqueue(db: Any, project_id: str, company_id: str, file_rec: Dict[str, Any], *, source: str,
                  to_query_id: Callable[[str], Any], skip: Optional[Callable[[str], bool]] = None,
                  force: bool = False, now: Optional[datetime] = None) -> str:
    """Queue one file. Idempotent. Returns "queued", "already" (built, or on its
    way), "skipped" (not a drawing PDF) or "no_file"."""
    file_id = str(file_rec.get("_id") or file_rec.get("id") or "")
    if not file_id or not file_rec.get("r2_key"):
        return "no_file"
    if not is_pdf_name(file_rec.get("name")) or (skip and skip(str(file_rec.get("name") or ""))):
        return "skipped"
    now = now or _utcnow()
    build = build_id(file_rec)
    tiles = file_rec.get("tiles") or {}
    prio = priority_of(source)
    if not force and tiles.get("build") == build and tiles.get("status") in ("queued", "compiling", "ready", "complete"):
        if tiles.get("status") == "queued":
            # already waiting (say, from the sweep) and now someone opened it: move it up the line
            await db[JOBS].update_one({"_id": file_id, "project_id": project_id, "status": "queued", "priority": {"$lt": prio}},
                                      {"$set": {"priority": prio, "source": source, "updated_at": now}})
        return "already"
    if force:
        # A forced build must REDO the work. The page records say which levels and indexes are
        # done (that is how a crashed compile resumes), and the build id is unchanged, so without
        # this the job would find everything "done" and rebuild nothing: the endpoint could not
        # repair a missing or corrupted object. The old objects are overwritten key for key.
        await db[PAGES].delete_many({"file_id": file_id, "build": build})
    jobs = db[JOBS]
    cur = await jobs.find_one({"_id": file_id, "project_id": project_id}, {"status": 1, "lease_until": 1})
    lease = _as_utc((cur or {}).get("lease_until"))
    if cur and cur.get("status") == "running" and lease and lease > now and not force:
        return "already"
    await jobs.update_one(
        {"_id": file_id, "project_id": project_id},
        {"$set": {"project_id": project_id, "company_id": company_id, "file_name": file_rec.get("name"),
                  "status": "queued", "source": source, "priority": prio, "build": build, "attempts": 0, "error": None,
                  "worker": None, "lease_until": None, "enqueued_at": now, "updated_at": now},
         "$setOnInsert": {"created_at": now}}, upsert=True)
    await set_summary(db, project_id, file_id, to_query_id, status="queued", build=build, error=None, updated_at=now)
    return "queued"


async def claim(db: Any, worker: str, *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The oldest runnable job, atomically: queued, or running on a lease nobody renewed."""
    now = now or _utcnow()
    return await db[JOBS].find_one_and_update(
        {"$or": [{"status": "queued"}, {"status": "running", "lease_until": {"$lt": now}}]},
        {"$set": {"status": "running", "worker": worker, "started_at": now, "updated_at": now,
                  "lease_until": now + timedelta(seconds=LEASE_SECONDS)},
         "$inc": {"attempts": 1}},
        sort=[("priority", -1), ("enqueued_at", 1)], return_document=ReturnDocument.AFTER)


async def _heartbeat(ctx: Ctx, file_id: str, project_id: str, worker: str) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        now = ctx.now()
        try:
            await ctx.db[JOBS].update_one(
                {"_id": file_id, "project_id": project_id, "worker": worker},
                {"$set": {"lease_until": now + timedelta(seconds=LEASE_SECONDS), "updated_at": now}})
        except Exception as e:                                    # a missed beat is not an error yet
            ctx.logger.warning("sheet tiles: lease renewal failed for %s: %r", file_id, e)


# ── the compile ──────────────────────────────────────────────────────────────

async def _upload_dir(ctx: Ctx, project_id: str, file_id: str, build: str, page: int, out_dir: str) -> int:
    """Upload every tile and the preview a render wrote. Returns the object count."""
    sem = asyncio.Semaphore(UPLOAD_AT_ONCE)
    uploads: List[Tuple[str, str]] = []
    for z_name in sorted(os.listdir(out_dir)):
        zdir = os.path.join(out_dir, z_name)
        m = re.fullmatch(r"z(\d+)", z_name)
        if not (m and os.path.isdir(zdir)):
            continue
        for name in os.listdir(zdir):
            t = re.fullmatch(r"(\d+)_(\d+)\.webp", name)
            if t:
                uploads.append((tile_key(project_id, file_id, build, page, int(m.group(1)), int(t.group(1)), int(t.group(2))),
                                os.path.join(zdir, name)))
    prev = os.path.join(out_dir, "preview.webp")
    if os.path.exists(prev):
        uploads.append((preview_key(project_id, file_id, build, page), prev))

    async def one(key: str, path: str) -> None:
        async with sem:
            with open(path, "rb") as f:
                data = f.read()
            await ctx.put_object(key, data, "image/webp", None)
    await asyncio.gather(*(one(k, p) for k, p in uploads))
    return len(uploads)


async def _page_state(ctx: Ctx, file_id: str, build: str, page: int) -> Dict[str, Any]:
    return (await ctx.db[PAGES].find_one({"_id": page_doc_id(file_id, build, page)})) or {}


async def compile_file(ctx: Ctx, job: Dict[str, Any], file_rec: Dict[str, Any],
                       to_query_id: Callable[[str], Any]) -> Dict[str, Any]:
    """Compile every page of one file, both passes. Returns {"outcome", "pages", "error"?}.
    Resumes: finished levels and indexes are skipped."""
    project_id = str(job["project_id"])
    company_id = str(job.get("company_id") or file_rec.get("company_id") or "")
    file_id = str(job["_id"])
    build = build_id(file_rec)
    tmp = tempfile.mkdtemp(prefix="sheettiles-")
    try:
        pdf_path = os.path.join(tmp, "file.pdf")
        await ctx.fetch_pdf(file_rec, pdf_path)
        sizes = await ctx.page_info(pdf_path)
        n = len(sizes)
        if n == 0:
            return {"outcome": "failed", "pages": 0, "error": "the PDF has no pages"}
        if n > MAX_PAGES:
            await set_summary(ctx.db, project_id, file_id, to_query_id, status="skipped", build=build, pages=n,
                              error=f"{n} pages is more than the {MAX_PAGES} the tile viewer takes; the PDF viewer is used",
                              updated_at=ctx.now())
            return {"outcome": "skipped", "pages": n}
        await set_summary(ctx.db, project_id, file_id, to_query_id, status="compiling", build=build, pages=n,
                          error=None, updated_at=ctx.now())
        for pass_no in (1, 2):
            done = 0
            for p in range(n):
                page = p + 1
                w_pt, h_pt = sizes[p]
                z_max = sheet_tiles.choose_max_z(w_pt, h_pt)
                levels = list(range(0, min(PASS1_MAX_Z, z_max) + 1)) if pass_no == 1 else \
                    list(range(PASS1_MAX_Z + 1, z_max + 1))
                state = await _page_state(ctx, file_id, build, page)
                ready = {int(z) for z in (state.get("levels_ready") or [])}
                todo = [z for z in levels if z not in ready]
                need_index = pass_no == 1 and not state.get("index_ready")
                if todo or need_index:
                    if not await ctx.db.project_files.find_one({"_id": to_query_id(file_id), "project_id": project_id}, {"_id": 1}):
                        return {"outcome": "cancelled", "pages": n, "error": "the file no longer exists"}
                    doc_id = page_doc_id(file_id, build, page)
                    sets: Dict[str, Any] = {"project_id": project_id, "company_id": company_id, "file_id": file_id,
                                            "build": build, "page": page, "width_pt": w_pt, "height_pt": h_pt,
                                            "z_max": z_max, "updated_at": ctx.now()}
                    if need_index:
                        index = await ctx.build_index(pdf_path, p)
                        blob = gzip.compress(json.dumps(index, separators=(",", ":")).encode("utf-8"))
                        await ctx.put_object(index_key(project_id, file_id, build, page), blob, "application/json", "gzip")
                        sets.update({"index_ready": True, "word_count": len(index.get("words") or []),
                                     "index_truncated": bool(index.get("truncated")), "index_bytes": len(blob),
                                     "callouts": index.get("callouts") or []})
                    adds: Dict[str, Any] = {}
                    if todo:
                        out_dir = os.path.join(tmp, f"p{page}z{todo[0]}")
                        os.makedirs(out_dir, exist_ok=True)
                        manifest = await ctx.run_compile(pdf_path, p, out_dir, todo)
                        await _upload_dir(ctx, project_id, file_id, build, page, out_dir)
                        for lv in manifest.get("levels") or []:
                            sets[f"levels.{lv['z']}"] = {k: lv[k] for k in ("z", "width", "height", "cols", "rows", "tiles", "present")}
                        if manifest.get("preview"):
                            sets["preview"] = manifest["preview"]
                        adds["levels_ready"] = {"$each": [int(lv["z"]) for lv in manifest.get("levels") or []]}
                        shutil.rmtree(out_dir, ignore_errors=True)
                    update: Dict[str, Any] = {"$set": sets}
                    if adds:
                        update["$addToSet"] = adds
                    await ctx.db[PAGES].update_one({"_id": doc_id}, update, upsert=True)
                done += 1
                await ctx.db[JOBS].update_one({"_id": file_id, "project_id": project_id},
                                              {"$set": {"pass": pass_no, "pages_done": done, "pages_total": n,
                                                        "updated_at": ctx.now()}})
            await set_summary(ctx.db, project_id, file_id, to_query_id,
                              status="ready" if pass_no == 1 else "complete", build=build, pages=n,
                              z_ready=PASS1_MAX_Z if pass_no == 1 else None, error=None, updated_at=ctx.now())
        if ctx.delete_keys:
            try:
                await purge(ctx.db, ctx.delete_keys, file_id, keep_build=build)
            except Exception as e:                               # garbage left behind is not a failed build
                ctx.logger.warning("sheet tiles: old builds of %s not deleted: %r", file_id, e)
        return {"outcome": "done", "pages": n}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def run_job(ctx: Ctx, job: Dict[str, Any], worker: str, to_query_id: Callable[[str], Any]) -> str:
    """Run one claimed job and record how it ended. Returns the job's status."""
    file_id = str(job["_id"])
    project_id = str(job["project_id"])
    key = {"_id": file_id, "project_id": project_id}
    jobs = ctx.db[JOBS]
    now = ctx.now()
    if int(job.get("attempts") or 0) > MAX_ATTEMPTS:
        err = f"stopped after {MAX_ATTEMPTS} attempts"
        await jobs.update_one(key, {"$set": {"status": "failed", "finished_at": now, "updated_at": now, "worker": None,
                                             "lease_until": None, "error": err}})
        await set_summary(ctx.db, project_id, file_id, to_query_id, status="failed", error=err, updated_at=now)
        return "failed"
    rec = await ctx.db.project_files.find_one({"_id": to_query_id(file_id), "project_id": project_id})
    if not rec or rec.get("is_deleted"):
        await jobs.update_one(key, {"$set": {"status": "cancelled", "finished_at": now, "updated_at": now,
                                             "worker": None, "lease_until": None, "error": "the file no longer exists"}})
        return "cancelled"
    beat = asyncio.create_task(_heartbeat(ctx, file_id, project_id, worker))
    try:
        result = await compile_file(ctx, job, rec, to_query_id)
    except Exception as e:
        ctx.logger.error("sheet tiles: %s raised %r", job.get("file_name"), e)
        result = {"outcome": "failed", "error": repr(e)[:300]}
    finally:
        beat.cancel()
    outcome = result.get("outcome")
    now = ctx.now()
    if outcome == "failed" and int(job.get("attempts") or 0) < MAX_ATTEMPTS:
        # a failure is retried (the finished pages are kept): back to the queue
        await jobs.update_one(key, {"$set": {"status": "queued", "worker": None, "lease_until": None,
                                             "updated_at": now, "error": result.get("error")}})
        return "queued"
    status = {"done": "done", "skipped": "skipped", "cancelled": "cancelled"}.get(outcome, "failed")
    await jobs.update_one(key, {"$set": {"status": status, "finished_at": now, "updated_at": now, "worker": None,
                                         "lease_until": None, "error": result.get("error")}})
    if status == "failed":
        await set_summary(ctx.db, project_id, file_id, to_query_id, status="failed", error=result.get("error"), updated_at=now)
    return status


# ── deleting what a build wrote ──────────────────────────────────────────────
#
# BY KNOWN KEY, NEVER BY LISTING. R2_ENDPOINT_URL ends in the bucket name, so a
# ListObjectsV2 against this deployment answers 200 with the bucket's CORS
# document and no keys: a prefix delete removes nothing and says so truthfully
# (see server._r2_delete_prefix). The page records name every tile exactly (each
# level's `present` bitmap), so the keys are DERIVED from them.

def page_object_keys(doc: Dict[str, Any]) -> List[str]:
    """Every R2 key a compiled page wrote, from its sheet_pages record."""
    pid, fid, build, page = str(doc.get("project_id")), str(doc.get("file_id")), str(doc.get("build")), int(doc.get("page") or 0)
    if not (pid and fid and build and page):
        return []
    keys: List[str] = []
    if doc.get("index_ready"):
        keys.append(index_key(pid, fid, build, page))
    if doc.get("preview"):
        keys.append(preview_key(pid, fid, build, page))
    for z_s, lv in (doc.get("levels") or {}).items():
        z, cols, rows = int(z_s), int(lv.get("cols") or 0), int(lv.get("rows") or 0)
        present = lv.get("present") or ""
        for y in range(rows):
            for x in range(cols):
                if sheet_tiles.bit_is_set(present, cols, x, y):
                    keys.append(tile_key(pid, fid, build, page, z, x, y))
    return keys


async def purge(db: Any, delete_keys: Callable[[List[str]], Awaitable[int]], file_id: str,
                keep_build: Optional[str] = None) -> int:
    """Delete the objects (and page records) of every build of `file_id` except
    `keep_build`. With no keep_build: all of them (the file is gone). Returns the
    number of objects deleted."""
    query: Dict[str, Any] = {"file_id": str(file_id)}
    if keep_build:
        query["build"] = {"$ne": keep_build}
    docs = await db[PAGES].find(query).to_list(MAX_PAGES * 4)
    keys = [k for d in docs for k in page_object_keys(d)]
    deleted = await delete_keys(keys) if keys else 0
    await db[PAGES].delete_many(query)
    return deleted


# ── what a client is told ────────────────────────────────────────────────────

async def manifest_for(db: Any, project_id: str, file_rec: Dict[str, Any]) -> Dict[str, Any]:
    """The viewer's manifest for a file: its status and, per page, size and the
    levels built. `status` is "none" when nothing has been queued; the client then
    keeps the PDF viewer."""
    tiles = file_rec.get("tiles") or {}
    status = tiles.get("status") or "none"
    build = tiles.get("build")
    out: Dict[str, Any] = {"status": status, "build": build, "tile": sheet_tiles.TILE, "pages": [],
                           "error": tiles.get("error"), "page_count": tiles.get("pages")}
    if status not in ("ready", "complete") or not build:
        return out
    file_id = str(file_rec.get("_id"))
    docs = await db[PAGES].find({"file_id": file_id, "build": build}).to_list(MAX_PAGES + 5)
    by_page = {int(d["page"]): d for d in docs}
    for page in range(1, int(tiles.get("pages") or 0) + 1):
        d = by_page.get(page)
        if not d:
            out["pages"].append({"page": page, "levels": [], "ready": False})
            continue
        out["pages"].append({
            "page": page, "ready": bool(d.get("levels_ready")), "width_pt": d.get("width_pt"),
            "height_pt": d.get("height_pt"), "z_max": d.get("z_max"),
            "levels": [d["levels"][str(z)] for z in sorted(int(k) for k in (d.get("levels") or {}))],
            "preview": d.get("preview"), "has_index": bool(d.get("index_ready")),
            "word_count": d.get("word_count", 0)})
    return out


async def registry_for(db: Any, project_id: str) -> List[Dict[str, Any]]:
    """The project's sheets: {sheet_number, file_id, page_number} from the plan index."""
    rows = await db.document_page_index.find(
        {"project_id": str(project_id)}, {"sheet_number": 1, "file_id": 1, "page_number": 1}).to_list(5000)
    return [r for r in rows if r.get("sheet_number")]


async def index_for(db: Any, fetch_object: Callable[[str], Awaitable[Optional[bytes]]], project_id: str,
                    file_rec: Dict[str, Any], page: int) -> Optional[Dict[str, Any]]:
    """The page's sheet_index: its words and callouts as stored, plus (from the
    project's sheet registry, read NOW) the page's own sheet number, its detail
    markers and every callout's resolved target. None when the page has no index yet."""
    tiles = file_rec.get("tiles") or {}
    build = tiles.get("build")
    file_id = str(file_rec.get("_id"))
    if not build:
        return None
    doc = await db[PAGES].find_one({"_id": page_doc_id(file_id, build, page)})
    if not doc or not doc.get("index_ready"):
        return None
    raw = await fetch_object(index_key(project_id, file_id, build, page))
    if not raw:
        return None
    try:
        index = json.loads(gzip.decompress(raw))
    except (OSError, ValueError):
        return None
    registry = await registry_for(db, project_id)
    own = next((r.get("sheet_number") for r in registry
                if str(r.get("file_id")) == file_id and int(r.get("page_number") or 0) == page), None)
    pages = await db[PAGES].find({"project_id": project_id, "build": {"$exists": True}},
                                 {"file_id": 1, "page": 1, "callouts": 1, "build": 1}).to_list(MAX_PAGES * 4)
    stored = {(str(d["file_id"]), int(d["page"])): d.get("callouts") or [] for d in pages}
    index["own_sheet"] = own
    index["detail_markers"] = sheet_index.approximate_crops(sheet_index.detail_markers_of(index.get("callouts") or [], own))
    index["callouts"] = sheet_index.resolve_callouts(index.get("callouts") or [], file_id, page, registry, stored)
    index["file_id"] = file_id
    return index


# ── finding files that have no tiles (sweep and backfill) ───────────────────

async def files_needing_tiles(db: Any, *, project_id: Optional[str] = None, file_id: Optional[str] = None,
                              limit: int = 200, skip: Optional[Callable[[str], bool]] = None,
                              to_query_id: Callable[[str], Any] = lambda x: x) -> List[Dict[str, Any]]:
    """PDFs whose tiles are missing, failed or built from an older version of the
    file. At most `limit`, oldest first."""
    query: Dict[str, Any] = {"is_deleted": {"$ne": True}, "r2_key": {"$nin": ["", None]}}
    if project_id:
        query["project_id"] = project_id
    if file_id:
        query["_id"] = to_query_id(file_id)
    rows = await db.project_files.find(query, {"name": 1, "project_id": 1, "company_id": 1, "r2_key": 1, "size": 1,
                                               "cache_version": 1, "tiles": 1, "created_at": 1}).to_list(20000)
    out = []
    for r in sorted(rows, key=lambda r: str(r.get("created_at") or "")):
        if not is_pdf_name(r.get("name")) or (skip and skip(str(r.get("name") or ""))):
            continue
        t = r.get("tiles") or {}
        if t.get("build") == build_id(r) and t.get("status") in ("queued", "compiling", "ready", "complete", "skipped"):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out
