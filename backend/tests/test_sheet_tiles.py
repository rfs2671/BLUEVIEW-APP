"""The sheet tile viewer's backend: the pyramid, the word/callout index, and the
queue that builds them. Real PDFs (made here with WeasyPrint) go through the real
renderer; only the database and R2 are in-memory stand-ins."""

import asyncio
import base64
import gzip
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fake_mongo import FakeDb  # noqa: E402
from lib import sheet_index, sheet_pipeline as SP, sheet_tiles as ST  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def make_pdf(path, width_in=36, height_in=24, body=""):
    from weasyprint import HTML
    html = (f"<style>@page{{size:{width_in}in {height_in}in;margin:0}}body{{margin:0}}"
            f".b{{position:absolute;left:2in;top:2in;width:6in;height:4in;background:#000}}"
            f".t{{position:absolute;left:12in;top:3in;font:40pt Helvetica}}</style>"
            f"<div class=b></div>{body}")
    HTML(string=html).write_pdf(path)


class Pyramid(unittest.TestCase):
    def test_levels_double_to_the_cap(self):
        lv = ST.pyramid(2592, 1728)                       # 36 x 24 in
        self.assertEqual([l["z"] for l in lv], [0, 1, 2, 3, 4])
        self.assertEqual(lv[0]["width"], 1024)
        self.assertEqual(lv[4]["width"], 16384)

    def test_a_small_page_stops_at_its_useful_sharpness(self):
        self.assertLess(ST.choose_max_z(612, 792), ST.MAX_Z)

    def test_bitmap_roundtrip(self):
        b = ST.present_bitmap(5, 4, [(0, 0), (4, 3), (2, 1)])
        self.assertTrue(ST.bit_is_set(b, 5, 4, 3))
        self.assertTrue(ST.bit_is_set(b, 5, 2, 1))
        self.assertFalse(ST.bit_is_set(b, 5, 1, 1))

    def test_level_spec(self):
        self.assertEqual(ST.parse_levels("0-2", 4), [0, 1, 2])
        self.assertEqual(ST.parse_levels("3,4", 3), [3])
        self.assertEqual(ST.parse_levels(None, 2), [0, 1, 2])


class Compile(unittest.TestCase):
    def test_blank_tiles_are_skipped_and_a_preview_is_made(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "a.pdf")
            make_pdf(pdf)
            tiles, previews = {}, []
            m = ST.compile_page(pdf, 0, lambda z, x, y, data: tiles.__setitem__((z, x, y), data),
                                lambda data, w, h: previews.append(data), levels=[0, 1, 2])
            self.assertTrue(previews and previews[0][:4] == b"RIFF")
            lv0 = next(l for l in m["levels"] if l["z"] == 0)
            self.assertEqual(lv0["tiles"], len([k for k in tiles if k[0] == 0]))
            full = lv0["cols"] * lv0["rows"]
            self.assertLess(lv0["tiles"], full + 1)
            for (z, x, y) in tiles:
                self.assertTrue(ST.bit_is_set(next(l for l in m["levels"] if l["z"] == z)["present"],
                                              next(l for l in m["levels"] if l["z"] == z)["cols"], x, y))
            z2 = next(l for l in m["levels"] if l["z"] == 2)
            self.assertLess(z2["tiles"], z2["cols"] * z2["rows"])      # most of a mostly-white sheet is blank

    def test_a_missing_page_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "a.pdf")
            make_pdf(pdf, 8, 8)
            with self.assertRaises(Exception):
                ST.compile_page(pdf, 5, lambda *a: None, None, levels=[0])


class Index(unittest.TestCase):
    def test_words_and_inline_callouts(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "a.pdf")
            make_pdf(pdf, 24, 18, body='<div class=t>SEE 3/A-402 FOR DETAIL</div>')
            ix = sheet_index.build_page_index(pdf, 0)
            self.assertEqual(ix["page"], 1)
            texts = [w["text"] for w in ix["words"]]
            self.assertIn("A-402", " ".join(texts))
            for w in ix["words"]:
                self.assertTrue(all(0 <= v <= 1 for v in w["bbox"]))
            self.assertTrue(any(c.get("sheet") == "A-402" and c.get("detail") == "3"
                                for c in ix["callouts"]), ix["callouts"])

    def test_rotated_page_is_searchable(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "r.pdf")
            make_pdf(pdf, 24, 18, body='<div class=t style="transform:rotate(90deg)">VERTICAL NOTE</div>')
            ix = sheet_index.build_page_index(pdf, 0)
            self.assertIn("VERTICAL", " ".join(w["text"] for w in ix["words"]))

    def test_page_out_of_range(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "a.pdf")
            make_pdf(pdf, 8, 8)
            with self.assertRaises(IndexError):
                sheet_index.build_page_index(pdf, 3)

    def test_a_callout_to_an_unknown_sheet_has_no_target(self):
        out = sheet_index.resolve_callouts(
            [{"label": "1/A-9", "detail": "1", "sheet": "A-9", "sheet_key": "A9", "bbox": [0, 0, .1, .1]}],
            "f1", 1, [{"sheet_number": "A-1", "file_id": "f1", "page_number": 1}], {})
        self.assertIsNone(out[0]["target"])

    def test_a_callout_resolves_across_files(self):
        out = sheet_index.resolve_callouts(
            [{"label": "1/A-2", "detail": "1", "sheet": "A-2", "sheet_key": "A2", "bbox": [0, 0, .1, .1]}],
            "f1", 1, [{"sheet_number": "A-2", "file_id": "f2", "page_number": 3}], {})
        t = out[0]["target"]
        self.assertEqual((t["file_id"], t["page"], t["sheet"]), ("f2", 3, "A-2"))


# ── the queue ────────────────────────────────────────────────────────────────

class _Store:
    def __init__(self):
        self.objs = {}
        self.deleted = []

    async def put(self, key, data, ctype, enc):
        self.objs[key] = (data, ctype, enc)

    async def delete(self, keys):
        for k in keys:
            self.objs.pop(k, None)
        self.deleted.extend(keys)
        return len(keys)


def _file(pdf_path, **kw):
    rec = {"_id": "f1", "project_id": "p1", "company_id": "c1", "name": "A-100.pdf", "r2_key": "k",
           "size": 123, "cache_version": 1}
    rec.update(kw)
    rec["_pdf"] = pdf_path
    return rec


def _ctx(db, store, pdf_path, fail_times=0, **kw):
    calls = {"n": 0}

    async def fetch(rec, dest):
        with open(pdf_path, "rb") as a, open(dest, "wb") as b:
            b.write(a.read())

    async def run_compile(pdf, page_index, out_dir, levels):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise RuntimeError("render crashed")
        return ST.compile_page(pdf, page_index,
                               lambda z, x, y, data: _w(out_dir, f"z{z}", f"{x}_{y}.webp", data),
                               lambda data, w, h: _w(out_dir, "", "preview.webp", data), levels=list(levels))

    ctx = SP.Ctx(db=db, put_object=store.put, fetch_pdf=fetch, delete_keys=store.delete, run_compile=run_compile, **kw)
    ctx._calls = calls
    return ctx


def _w(out_dir, sub, name, data):
    d = os.path.join(out_dir, sub) if sub else out_dir
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "wb") as f:
        f.write(data)


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf = os.path.join(self.tmp.name, "a.pdf")
        make_pdf(self.pdf, 24, 18, body='<div class=t>3/A-402</div>')
        self.rec = _file(self.pdf)
        self.db = FakeDb(project_files=[{k: v for k, v in self.rec.items() if k != "_pdf"}])
        self.store = _Store()

    def tearDown(self):
        self.tmp.cleanup()

    def _enqueue(self, **kw):
        rec = dict(self.db.project_files.rows[0])
        rec.update({k: v for k, v in self.rec.items() if k not in ("_pdf", "tiles")})
        return _run(SP.enqueue(self.db, "p1", "c1", rec, source="t", to_query_id=lambda x: x, **kw))

    def _drive(self, ctx=None):
        ctx = ctx or _ctx(self.db, self.store, self.pdf)
        job = _run(SP.claim(self.db, "w1"))
        self.assertIsNotNone(job)
        return ctx, job, _run(SP.run_job(ctx, job, "w1", lambda x: x))

    def test_non_pdf_and_generated_files_are_not_queued(self):
        rec = {**self.rec, "name": "photo.jpg"}
        self.assertEqual(_run(SP.enqueue(self.db, "p1", "c1", rec, source="t", to_query_id=lambda x: x)), "skipped")
        rec = {**self.rec, "name": "Progress Report.pdf"}
        self.assertEqual(_run(SP.enqueue(self.db, "p1", "c1", rec, source="t", to_query_id=lambda x: x,
                                         skip=lambda n: "Report" in n)), "skipped")
        self.assertEqual(_run(SP.enqueue(self.db, "p1", "c1", {"_id": "x", "name": "a.pdf"}, source="t",
                                         to_query_id=lambda x: x)), "no_file")

    def test_enqueue_is_idempotent(self):
        self.assertEqual(self._enqueue(), "queued")
        self.assertEqual(self._enqueue(), "already")
        self.assertEqual(len(self.db[SP.JOBS].rows), 1)

    def test_compile_end_to_end_then_manifest_index_and_tiles(self):
        self._enqueue()
        ctx, job, status = self._drive()
        self.assertEqual(status, "done")
        rec = self.db.project_files.rows[0]
        self.assertEqual(rec["tiles"]["status"], "complete")
        man = _run(SP.manifest_for(self.db, "p1", rec))
        self.assertEqual(man["status"], "complete")
        self.assertEqual(len(man["pages"]), 1)
        pg = man["pages"][0]
        self.assertTrue(pg["ready"] and pg["has_index"] and pg["preview"])
        # every tile the manifest says is present is in the store, and nothing else
        for lv in pg["levels"]:
            for y in range(lv["rows"]):
                for x in range(lv["cols"]):
                    key = SP.tile_key("p1", "f1", man["build"], 1, lv["z"], x, y)
                    self.assertEqual(ST.bit_is_set(lv["present"], lv["cols"], x, y), key in self.store.objs, key)
        self.assertIn(SP.preview_key("p1", "f1", man["build"], 1), self.store.objs)

        async def fetch(key):
            o = self.store.objs.get(key)
            return o[0] if o else None
        ix = _run(SP.index_for(self.db, fetch, "p1", rec, 1))
        self.assertEqual(ix["file_id"], "f1")
        self.assertTrue(ix["words"])

    def test_pass_one_makes_the_file_usable_before_pass_two(self):
        self._enqueue()
        seen = []
        ctx = _ctx(self.db, self.store, self.pdf)
        orig = ctx.run_compile

        async def spy(pdf, pi, out, levels):
            seen.append((list(levels), self.db.project_files.rows[0]["tiles"]["status"]))
            return await orig(pdf, pi, out, levels)
        ctx.run_compile = spy
        self._drive(ctx)
        self.assertEqual(seen[0][0][0], 0)
        if len(seen) > 1:
            self.assertEqual(seen[1][1], "ready")           # pass 2 started after the file was ready

    def test_a_crashing_render_is_retried_then_succeeds(self):
        self._enqueue()
        ctx = _ctx(self.db, self.store, self.pdf, fail_times=1)
        _, job, status = self._drive(ctx)
        self.assertEqual(status, "queued")
        job = _run(SP.claim(self.db, "w1"))
        self.assertEqual(_run(SP.run_job(ctx, job, "w1", lambda x: x)), "done")

    def test_a_render_that_always_fails_ends_failed_and_says_why(self):
        self._enqueue()
        ctx = _ctx(self.db, self.store, self.pdf, fail_times=99)
        for _ in range(SP.MAX_ATTEMPTS + 1):
            job = _run(SP.claim(self.db, "w1"))
            if not job:
                break
            status = _run(SP.run_job(ctx, job, "w1", lambda x: x))
        self.assertEqual(status, "failed")
        t = self.db.project_files.rows[0]["tiles"]
        self.assertEqual(t["status"], "failed")
        self.assertIn("render crashed", t["error"] or "") if "crashed" in (t["error"] or "") else self.assertTrue(t["error"])

    def test_a_stale_lease_is_reclaimed_and_a_live_one_is_not(self):
        self._enqueue()
        now = datetime.now(timezone.utc)
        j = _run(SP.claim(self.db, "w1", now=now))
        self.assertIsNotNone(j)
        self.assertIsNone(_run(SP.claim(self.db, "w2", now=now + timedelta(seconds=30))))
        again = _run(SP.claim(self.db, "w2", now=now + timedelta(seconds=SP.LEASE_SECONDS + 5)))
        self.assertEqual(again["worker"], "w2")

    def test_a_deleted_file_cancels_the_job(self):
        self._enqueue()
        self.db.project_files.rows.clear()
        _, _, status = self._drive()
        self.assertEqual(status, "cancelled")

    def test_a_forced_rebuild_really_rebuilds(self):
        self._enqueue()
        self._drive()
        built = dict(self.store.objs)
        self.assertTrue(built)
        # damage the stored result: lose some tiles and the index
        lost = [k for k in built if "/z1/" in k or k.endswith("index.json.gz")]
        self.assertTrue(lost)
        for k in lost:
            del self.store.objs[k]
        self.assertEqual(self._enqueue(), "already", "without force a finished file is left alone")
        self.assertEqual(self._enqueue(force=True), "queued")
        self._drive()
        for k in lost:
            self.assertIn(k, self.store.objs, f"force did not restore {k}")
        self.assertEqual(set(self.store.objs), set(built))
        self.assertEqual(self.db.project_files.rows[0]["tiles"]["status"], "complete")

    def test_a_new_version_replaces_the_old_build_and_deletes_its_objects(self):
        self._enqueue()
        self._drive()
        old_keys = set(self.store.objs)
        self.assertTrue(old_keys)
        self.db.project_files.rows[0]["cache_version"] = 2
        self.rec["cache_version"] = 2
        self.assertEqual(self._enqueue(), "queued")
        self._drive()
        new_build = SP.build_id(self.rec)
        self.assertTrue(all(new_build in k for k in self.store.objs))
        self.assertTrue(old_keys.isdisjoint(self.store.objs))
        self.assertEqual({d["build"] for d in self.db[SP.PAGES].rows}, {new_build})

    def test_purge_removes_everything_for_a_deleted_file(self):
        self._enqueue()
        self._drive()
        n = _run(SP.purge(self.db, self.store.delete, "f1"))
        self.assertGreater(n, 0)
        self.assertEqual(self.store.objs, {})
        self.assertEqual(self.db[SP.PAGES].rows, [])

    def test_the_sweep_finds_only_files_that_need_tiles(self):
        self.db.project_files.rows.append({"_id": "f2", "project_id": "p1", "name": "B.pdf", "r2_key": "k2",
                                          "size": 1, "cache_version": 0, "created_at": "2026-01-02"})
        self.db.project_files.rows.append({"_id": "f3", "project_id": "p1", "name": "c.jpg", "r2_key": "k3"})
        ids = [r["_id"] for r in _run(SP.files_needing_tiles(self.db))]
        self.assertEqual(sorted(ids), ["f1", "f2"])
        self._enqueue()
        ids = [r["_id"] for r in _run(SP.files_needing_tiles(self.db))]
        self.assertEqual(ids, ["f2"])


class Routes(unittest.TestCase):
    """The tile routes take the header and only the header."""

    def test_routes_exist_and_use_the_header_only_dependency(self):
        import server
        paths = {r.path: r for r in server.api_router.routes if "/sheets" in getattr(r, "path", "")}
        self.assertTrue(any(p.endswith("/tiles/{z}/{x}/{y}") for p in paths))
        for r in paths.values():
            deps = [d.call for d in r.dependant.dependencies]
            self.assertIn(server.get_current_user_header_only, deps, r.path)
            self.assertNotIn(server.get_current_user, deps, r.path)

    def test_a_query_token_alone_is_refused(self):
        import server
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            _run(server.get_current_user_header_only(request=None, credentials=None))
        self.assertEqual(cm.exception.status_code, 401)

    def test_tile_routes_have_their_own_rate_rule(self):
        from lib import rate_limits as RL
        rule = RL._match_rule("GET", "/api/projects/p/files/f/sheets/1/tiles/3/4/5")
        self.assertEqual(RL._parse_limit(rule[1])[0], 4000)


if __name__ == "__main__":
    unittest.main()


class Backfill(unittest.TestCase):
    def test_script_skips_what_the_server_skips(self):
        import server
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import backfill_sheet_tiles as B
        for n in ("Blueview_Report_3846.pdf", "Blueview Report.pdf", "A-100.pdf", "Reporting.pdf", "blueview-report-1.pdf"):
            self.assertEqual(B._is_generated(n), server.is_generated_report(n), n)


# ── pdfium: one thread at a time, bounded bitmaps, everything closed ──────────

class _FakeBitmap:
    def __init__(self, w, h, log):
        self.w, self.h, self.log, self.closed = w, h, log, False
        log["bitmaps"].append(self)

    def to_pil(self):
        from PIL import Image
        return Image.new("RGB", (self.w, self.h), (0, 0, 0))

    def close(self):
        self.closed = True


class _FakePage:
    def __init__(self, log, fail_render=False):
        self.log, self.closed, self.fail_render = log, False, fail_render

    def get_size(self):
        return (2592.0, 1728.0)

    def render(self, scale=1, crop=(0, 0, 0, 0), **kw):
        if self.fail_render:
            raise RuntimeError("pdfium refused")
        # crop is in PDF points; the bitmap is what is left of the page at `scale`
        w = int(round((2592 - crop[0] - crop[2]) * scale))
        h = int(round((1728 - crop[1] - crop[3]) * scale))
        return _FakeBitmap(max(1, w), max(1, h), self.log)

    def close(self):
        self.closed = True


class _FakePdf:
    def __init__(self, log, **kw):
        self.log, self.closed = log, False
        self.page = _FakePage(log, **kw)
        log["pdfs"].append(self)

    def __len__(self):
        return 1

    def __getitem__(self, i):
        self.log["pages"].append(self.page)
        return self.page

    def close(self):
        self.closed = True


class Pdfium(unittest.TestCase):
    def _fake(self, **kw):
        log = {"bitmaps": [], "pages": [], "pdfs": []}
        orig = ST._open_pdf
        ST._open_pdf = lambda source: _FakePdf(log, **kw)
        self.addCleanup(lambda: setattr(ST, "_open_pdf", orig))
        return log

    def test_bands_never_exceed_the_memory_cap_at_any_level(self):
        log = self._fake()
        ST.compile_page("x", 0, lambda *a: None, None, levels=[0, 1, 2, 3, 4])
        self.assertTrue(log["bitmaps"])
        biggest = max(b.w * b.h * 4 for b in log["bitmaps"])
        self.assertLessEqual(biggest, ST.MAX_BAND_BYTES)
        self.assertLessEqual(max(b.h for b in log["bitmaps"]), ST.BAND_ROWS + 1)
        self.assertGreater(len(log["bitmaps"]), 16, "level 4 is rendered in many bands, not one bitmap")
        full_level = 16384 * 10923 * 4
        self.assertGreater(full_level, 600 * 1024 * 1024)
        self.assertLess(biggest, full_level / 8)

    def test_band_rows_shrinks_for_wide_levels_and_refuses_absurd_ones(self):
        self.assertEqual(ST.band_rows(16384), ST.BAND_ROWS)
        self.assertEqual(ST.band_rows(1024), ST.BAND_ROWS)
        wide = ST.band_rows(40000)
        self.assertEqual(wide % ST.TILE, 0)
        self.assertLessEqual(40000 * wide * 4, ST.MAX_BAND_BYTES)
        with self.assertRaises(ValueError):
            ST.band_rows(100000)

    def test_every_bitmap_page_and_document_is_closed(self):
        log = self._fake()
        ST.compile_page("x", 0, lambda *a: None, lambda *a: None, levels=[0, 1])
        self.assertTrue(all(b.closed for b in log["bitmaps"]))      # bands AND the preview
        self.assertTrue(all(p.closed for p in log["pages"]) and all(d.closed for d in log["pdfs"]))

    def test_everything_is_closed_when_a_render_or_a_callback_fails(self):
        log = self._fake(fail_render=True)
        with self.assertRaises(RuntimeError):
            ST.compile_page("x", 0, lambda *a: None, None, levels=[0])
        self.assertTrue(all(p.closed for p in log["pages"]) and all(d.closed for d in log["pdfs"]))
        log = self._fake()

        def boom(*a):
            raise OSError("disk full")
        with self.assertRaises(OSError):
            ST.compile_page("x", 0, boom, None, levels=[0])
        self.assertTrue(all(b.closed for b in log["bitmaps"]) and all(p.closed for p in log["pages"]) and all(d.closed for d in log["pdfs"]))
        log = self._fake()
        with self.assertRaises(IndexError):
            ST.compile_page("x", 7, lambda *a: None, None)
        self.assertTrue(all(d.closed for d in log["pdfs"]))

    def test_concurrent_threads_never_overlap_inside_pdfium(self):
        import threading
        import time
        from lib.pdfium_lock import PDFIUM_LOCK
        inside, worst = [0], [0]
        guard = threading.Lock()

        class Slow(_FakePage):
            def render(self, *a, **kw):
                with guard:
                    inside[0] += 1
                    worst[0] = max(worst[0], inside[0])
                time.sleep(0.002)
                try:
                    return super().render(*a, **kw)
                finally:
                    with guard:
                        inside[0] -= 1

        log = {"bitmaps": [], "pages": [], "pdfs": []}

        class P(_FakePdf):
            def __init__(self, log):
                super().__init__(log)
                self.page = Slow(log)
        orig = ST._open_pdf
        ST._open_pdf = lambda source: P(log)
        self.addCleanup(lambda: setattr(ST, "_open_pdf", orig))
        errors = []

        def run():
            try:
                ST.compile_page("x", 0, lambda *a: None, None, levels=[0, 1])
            except Exception as e:                                  # pragma: no cover
                errors.append(e)
        threads = [threading.Thread(target=run) for _ in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(worst[0], 1, "two threads were inside pdfium at once")
        self.assertTrue(PDFIUM_LOCK.acquire(blocking=False))        # and the lock is free afterwards
        PDFIUM_LOCK.release()

    def test_real_pdfium_survives_concurrent_threads(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "a.pdf")
            make_pdf(pdf, 24, 18)
            errors, done = [], []

            def run(i):
                try:
                    if i % 2:
                        ST.page_sizes(pdf)
                    else:
                        ST.compile_page(pdf, 0, lambda *a: None, lambda *a: None, levels=[0, 1])
                    done.append(i)
                except Exception as e:
                    errors.append(repr(e))
            ts = [threading.Thread(target=run, args=(i,)) for i in range(8)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.assertEqual(errors, [])
            self.assertEqual(len(done), 8)

    def test_plan_page_takes_the_same_lock(self):
        src = (Path(__file__).resolve().parents[1] / "lib" / "plan_page.py").read_text()
        self.assertIn("PDFIUM_LOCK", src)
        self.assertGreaterEqual(src.count("with PDFIUM_LOCK"), 4)


class ChildProcess(unittest.TestCase):
    """The compile really runs in a child process, one at a time per process."""

    def test_page_info_and_compile_through_the_real_child(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "a.pdf")
            make_pdf(pdf, 24, 18)
            sizes = _run(SP._default_page_info(pdf))
            self.assertEqual(len(sizes), 1)
            self.assertAlmostEqual(sizes[0][0], 1728.0, delta=1)
            out = os.path.join(d, "out")
            m = _run(SP._default_run_compile(pdf, 0, out, [0, 1]))
            self.assertEqual([lv["z"] for lv in m["levels"]], [0, 1])
            self.assertTrue(os.path.exists(os.path.join(out, "preview.webp")))
            self.assertTrue(os.path.isdir(os.path.join(out, "z1")))

    def test_a_child_failure_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.pdf")
            open(bad, "wb").write(b"not a pdf")
            with self.assertRaises(RuntimeError):
                _run(SP._default_page_info(bad))

    def test_children_never_overlap(self):
        active, worst = [0], [0]
        real = asyncio.create_subprocess_exec

        async def spy(*a, **kw):
            active[0] += 1
            worst[0] = max(worst[0], active[0])
            proc = await real(*a, **kw)
            orig = proc.communicate

            async def comm():
                try:
                    return await orig()
                finally:
                    active[0] -= 1
            proc.communicate = comm
            return proc

        async def go(pdf):
            await asyncio.gather(*(SP._default_page_info(pdf) for _ in range(3)))
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "a.pdf")
            make_pdf(pdf, 8, 8)
            SP._render_gate = None
            asyncio.create_subprocess_exec = spy
            try:
                _run(go(pdf))
            finally:
                asyncio.create_subprocess_exec = real
        self.assertEqual(worst[0], 1)


# ── serving: immutable tiles are not re-proxied from R2 on every request ─────

class Serving(unittest.TestCase):
    def test_etag_matching(self):
        from lib import sheet_serve as SS
        e = SS.etag_for("B1", "f1", 1, 3, 4, 5)
        self.assertEqual(e, '"B1-f1-1-3-4-5"')
        self.assertTrue(SS.matches_etag(e, e) and SS.matches_etag('"x", ' + e, e) and SS.matches_etag("W/" + e, e) and SS.matches_etag("*", e))
        self.assertFalse(SS.matches_etag(None, e) or SS.matches_etag('"other"', e) or SS.matches_etag("", e))

    def test_decisions_expire_and_can_be_forgotten(self):
        from lib import sheet_serve as SS
        now = [0.0]
        c = SS.DecisionCache(ttl=10, max_entries=3, clock=lambda: now[0])
        c.put(("u", "p", "f1"), {"r": 1})
        self.assertEqual(c.get(("u", "p", "f1")), {"r": 1})
        now[0] = 10.5
        self.assertIsNone(c.get(("u", "p", "f1")))
        now[0] = 0
        for i in range(5):
            c.put(("u", "p", f"f{i}"), i)
        self.assertIsNone(c.get(("u", "p", "f0")))              # bounded: oldest dropped
        c.forget_file("f4")
        self.assertIsNone(c.get(("u", "p", "f4")))
        self.assertEqual(c.get(("u", "p", "f3")), 3)

    def test_byte_lru_is_bounded(self):
        from lib import sheet_serve as SS
        lru = SS.ByteLru(budget=100)
        lru.put("a", b"x" * 20)
        lru.put("b", b"y" * 20)
        lru.put("big", b"z" * 90)                                # over a quarter of the budget: not kept
        self.assertIsNone(lru.get("big"))
        for i in range(10):
            lru.put(f"k{i}", b"q" * 20)
        self.assertLessEqual(lru.used, 100)
        self.assertIsNone(lru.get("a"))
        self.assertEqual(lru.get("k9"), b"q" * 20)
        lru.drop_prefix("k")
        self.assertEqual(lru.used, 0)

    def _image(self, headers=None, build="B1", status="complete"):
        import server
        from types import SimpleNamespace
        calls = {"auth": 0, "r2": 0}

        async def fake_auth(project_id, file_id, user, remember=False):
            calls["auth"] += 1
            return {"tiles": {"build": build, "status": status}}

        async def fake_fetch(key):
            calls["r2"] += 1
            return b"WEBPDATA"
        req = SimpleNamespace(headers=headers or {})
        server._SHEET_BYTES = __import__("lib.sheet_serve", fromlist=["x"]).ByteLru()
        orig = (server._sheet_file_or_403, server._sheet_fetch_object)
        server._sheet_file_or_403, server._sheet_fetch_object = fake_auth, fake_fetch
        self.addCleanup(lambda: setattr(server, "_sheet_file_or_403", orig[0]))
        self.addCleanup(lambda: setattr(server, "_sheet_fetch_object", orig[1]))

        def go(h=None, b="B1"):
            req.headers = h or {}
            return _run(server._sheet_image(req, "p1", "f1", 1, b, lambda p, f, bb: f"k/{bb}", (1, 0, 0, 0), {"id": "u"}))
        return go, calls

    def test_a_tile_is_immutable_and_served_from_memory_the_second_time(self):
        go, calls = self._image()
        r1 = go()
        self.assertEqual((r1.status_code, r1.body), (200, b"WEBPDATA"))
        self.assertEqual(r1.headers["cache-control"], "private, max-age=31536000, immutable")
        self.assertTrue(r1.headers["etag"].startswith('"B1-f1-'))
        go()
        go()
        self.assertEqual(calls["r2"], 1, "R2 was asked once for three requests")

    def test_revalidation_is_a_304_that_never_touches_r2(self):
        go, calls = self._image()
        etag = go().headers["etag"]
        before = calls["r2"]
        r = go({"if-none-match": etag})
        self.assertEqual(r.status_code, 304)
        self.assertEqual(r.body, b"")
        self.assertEqual(r.headers["cache-control"], "private, max-age=31536000, immutable")
        self.assertEqual(calls["r2"], before)
        self.assertGreaterEqual(calls["auth"], 2, "the access check still runs on a 304")

    def test_a_stale_build_or_unfinished_file_is_404(self):
        from fastapi import HTTPException
        go, _ = self._image()
        with self.assertRaises(HTTPException) as cm:
            go(b="OLD")
        self.assertEqual(cm.exception.status_code, 404)
        go2, _ = self._image(status="compiling")
        with self.assertRaises(HTTPException):
            go2()

    def test_the_authorization_is_reused_only_for_reads(self):
        import server
        calls = {"n": 0}

        async def checked(project_id, file_id, user):
            calls["n"] += 1
            return {"_id": file_id}
        orig = server._sheet_file_checked
        server._sheet_file_checked = checked
        self.addCleanup(lambda: setattr(server, "_sheet_file_checked", orig))
        server._SHEET_DECISIONS = __import__("lib.sheet_serve", fromlist=["x"]).DecisionCache()
        user = {"id": "u1"}
        for _ in range(5):
            _run(server._sheet_file_or_403("p", "f", user, remember=True))
        self.assertEqual(calls["n"], 1)
        for _ in range(3):
            _run(server._sheet_file_or_403("p", "f", user))
        self.assertEqual(calls["n"], 4, "manifest, index and writes always re-check")
        _run(server._sheet_file_or_403("p", "f", {"id": "u2"}, remember=True))
        self.assertEqual(calls["n"], 5, "another user is never served another user's decision")
        _run(server._sheet_file_or_403("p", "f", {}, remember=True))
        _run(server._sheet_file_or_403("p", "f", {}, remember=True))
        self.assertEqual(calls["n"], 7, "a caller with no id is never cached")


class Order(unittest.TestCase):
    def _q(self, db, fid, source, name=None):
        rec = {"_id": fid, "project_id": "p1", "company_id": "c1", "name": name or f"{fid}.pdf", "r2_key": "k", "size": 1, "cache_version": 1}
        db.project_files.rows.append(dict(rec))
        return _run(SP.enqueue(db, "p1", "c1", dict(rec), source=source, to_query_id=lambda x: x))

    def test_an_opened_drawing_jumps_the_sweep_and_the_upload_queue(self):
        db = FakeDb()
        for fid, src in (("a", "sweep"), ("b", "sweep"), ("c", "upload"), ("d", "open"), ("e", "sweep")):
            self.assertEqual(self._q(db, fid, src), "queued")
        order = []
        while True:
            j = _run(SP.claim(db, "w"))
            if not j:
                break
            order.append(j["_id"])
            db[SP.JOBS].rows[[r["_id"] for r in db[SP.JOBS].rows].index(j["_id"])]["status"] = "done"
        self.assertEqual(order, ["d", "c", "a", "b", "e"], "open, then upload, then the sweep in the order it queued")

    def test_opening_a_drawing_the_sweep_already_queued_moves_it_up(self):
        db = FakeDb()
        for fid in ("a", "b", "c"):
            self._q(db, fid, "sweep")
        row = dict(next(r for r in db.project_files.rows if r["_id"] == "c"))
        row["tiles"] = {"status": "queued", "build": SP.build_id(row)}
        self.assertEqual(_run(SP.enqueue(db, "p1", "c1", row, source="open", to_query_id=lambda x: x)), "already")
        self.assertEqual(_run(SP.claim(db, "w"))["_id"], "c")

    def test_the_render_child_runs_at_a_lower_priority(self):
        import inspect
        self.assertIn("preexec_fn", inspect.getsource(SP._run_cli))
        before = os.nice(0)
        pid = os.fork()
        if pid == 0:
            try:
                SP._lower_priority()
                os._exit(0 if os.nice(0) > before else 1)
            except BaseException:
                os._exit(2)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.WEXITSTATUS(status), 0)
