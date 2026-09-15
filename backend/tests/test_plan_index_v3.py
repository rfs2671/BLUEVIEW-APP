"""Index version 3 as wired into server.py.

lib/plan_extract.py is tested on its own in test_plan_extract.py. This file
covers what server.py does with it: the page row it writes, the chunks beside
it, OCR only for a page with no text layer, one current row per sheet, the
text-first answers, and the WhatsApp vision cap no longer counting indexing.

The database is an in-memory stand-in with just enough of Mongo's filter
language for these queries ($in, $nin, $ne, $gte). No network, no model.
"""

import asyncio
import inspect
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402
from lib import plan_extract  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


_MISSING = object()


def _match_one(doc, key, cond):
    val = doc.get(key, _MISSING)
    if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
        for op, arg in cond.items():
            v = None if val is _MISSING else val
            if op == "$in" and v not in arg:
                return False
            if op == "$nin" and v in arg:
                return False
            if op == "$ne" and v == arg:
                return False
            if op == "$gte" and not (v is not None and v >= arg):
                return False
        return True
    return (None if val is _MISSING else val) == cond


def _matches(doc, q):
    return all(_match_one(doc, k, c) for k, c in (q or {}).items())


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    async def to_list(self, n):
        return [dict(r) for r in self.rows[:n]]


class _Res:
    def __init__(self, n=0):
        self.modified_count = n
        self.deleted_count = n


class _Coll:
    def __init__(self):
        self.rows = []
        self._n = 0

    def _id(self):
        self._n += 1
        return f"id{self._n}"

    def find(self, q=None, proj=None):
        return _Cursor([r for r in self.rows if _matches(r, q)])

    async def find_one(self, q=None, proj=None):
        for r in self.rows:
            if _matches(r, q):
                return dict(r)
        return None

    async def update_one(self, q, u, upsert=False):
        for r in self.rows:
            if _matches(r, q):
                r.update(u.get("$set", {}))
                return _Res(1)
        if upsert:
            row = dict(q)
            row.update(u.get("$set", {}))
            row.setdefault("_id", self._id())
            self.rows.append(row)
        return _Res(0)

    async def update_many(self, q, u):
        n = 0
        for r in self.rows:
            if _matches(r, q):
                r.update(u.get("$set", {}))
                n += 1
        return _Res(n)

    async def insert_many(self, docs):
        for d in docs:
            d = dict(d)
            d.setdefault("_id", self._id())
            self.rows.append(d)
        return _Res(len(docs))

    async def delete_many(self, q):
        before = len(self.rows)
        self.rows = [r for r in self.rows if not _matches(r, q)]
        return _Res(before - len(self.rows))

    async def count_documents(self, q):
        return len([r for r in self.rows if _matches(r, q)])


class _Db:
    def __init__(self):
        self._c = {}

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._c.setdefault(n, _Coll())

    def __getitem__(self, n):
        return self._c.setdefault(n, _Coll())


T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


class OneCurrentRowPerSheet(unittest.TestCase):

    def setUp(self):
        self.db = _Db()
        p = mock.patch.object(server, "db", self.db)
        p.start()
        self.addCleanup(p.stop)

    def _file(self, fid, days):
        self.db.project_files.rows.append(
            {"_id": fid, "project_id": "p1", "created_at": T0 + timedelta(days=days)})

    def _page(self, fid, page, sheet, file_hash):
        self.db.document_page_index.rows.append({
            "_id": f"{fid}-{page}", "project_id": "p1", "file_id": fid,
            "page_number": page, "sheet_number": sheet, "file_hash": file_hash,
            "superseded_by": None,
        })

    def _row(self, rid):
        return next(r for r in self.db.document_page_index.rows if r["_id"] == rid)

    def test_a_revised_set_supersedes_the_older_sheet(self):
        self._file("old", 0)
        self._file("new", 5)
        self._page("old", 1, "A-500.00", "h1")
        self._page("new", 1, "A-500.00", "h2")
        _run(server._supersede_plan_pages("p1"))
        self.assertEqual(self._row("old-1")["superseded_by"], "new")
        self.assertIsNone(self._row("new-1")["superseded_by"])

    def test_the_identical_pdf_uploaded_twice_is_one_row(self):
        """Same hash, no sheet number read — the case a null title block made
        invisible to a sheet-number rule."""
        self._file("first", 0)
        self._file("again", 1)
        self._page("first", 3, None, "same")
        self._page("again", 3, None, "same")
        _run(server._supersede_plan_pages("p1"))
        self.assertEqual(self._row("first-3")["superseded_by"], "again")
        self.assertIsNone(self._row("again-3")["superseded_by"])

    def test_two_pages_of_one_sheet_in_one_file_both_stay(self):
        self._file("f", 0)
        self._page("f", 1, "P-100.00", "h")
        self._page("f", 2, "P-100.00", "h")
        _run(server._supersede_plan_pages("p1"))
        self.assertIsNone(self._row("f-1")["superseded_by"])
        self.assertIsNone(self._row("f-2")["superseded_by"])

    def test_deleting_the_newer_upload_brings_the_older_sheet_back(self):
        """Readers hide a row only while its superseder is live — no re-run
        needed for the older sheet to reappear."""
        self._file("old", 0)
        self._file("new", 5)
        self._page("old", 1, "S-100", "h1")
        self._page("new", 1, "S-100", "h2")
        _run(server._supersede_plan_pages("p1"))
        live_now = ["old", "new"]
        live_after_delete = ["old"]
        visible = lambda live: [r["_id"] for r in self.db.document_page_index.rows
                                if _matches(r, server._current_page_filter(live))]
        self.assertEqual(visible(live_now), ["new-1"])
        self.assertEqual(visible(live_after_delete), ["old-1"])

    def test_a_verdict_that_no_longer_holds_is_cleared(self):
        self._file("a", 0)
        self._page("a", 1, "S-001", "h")
        self._row("a-1")["superseded_by"] = "gone"
        _run(server._supersede_plan_pages("p1"))
        self.assertIsNone(self._row("a-1")["superseded_by"])

    def test_a_failed_file_lookup_does_not_filter(self):
        self.assertEqual(server._current_page_filter(None), {})


class TheReadersExcludeSupersededRows(unittest.TestCase):

    def test_each_reader_applies_the_current_page_filter(self):
        for fn in (server._retrieve_plan_candidates, server._pages_with_element,
                   server._sheet_index_lines, server._current_v3_chunks):
            with self.subTest(fn=fn.__name__):
                self.assertIn("_current_page_filter(", inspect.getsource(fn),
                              f"{fn.__name__} does not exclude superseded rows")


CHUNKS = [
    {"chunk_type": "schedule", "sheet_number": "S-100.00", "text": "PILE SCHEDULE",
     "payload": {"name": "PILE SCHEDULE", "columns": ["MARK", "TYPE", "QTY"],
                 "rows": [["P1", "HP 12x53", "18"], ["P2", "HP 14x73", "6"]]}},
    {"chunk_type": "specs", "sheet_number": "A-500.00",
     "text": '7/8" CEMENT STUCCO ON LATH\nSTUCCO PER SPEC'},
    {"chunk_type": "notes", "sheet_number": "P-100.00",
     "text": "4. ROOF DRAINS SEE RISER DIAGRAM"},
]


class CountsAndAttributesComeFromTheText(unittest.TestCase):

    def _ask(self, text, keywords=None, chunks=CHUNKS):
        async def fake_chunks(pid):
            return chunks
        with mock.patch.object(server, "_current_v3_chunks", fake_chunks):
            return _run(server._answer_plan_from_chunks(
                "p1", text, {"keywords": keywords or []}))

    def test_how_many_piles_sums_the_schedule(self):
        has_v3, ans = self._ask("how many piles", ["piles"])
        self.assertTrue(has_v3)
        self.assertEqual(ans["outcome"], "chunk_count")
        self.assertIn("S-100.00: 24", ans["text"])

    def test_a_count_nobody_printed_is_not_stated_and_not_guessed(self):
        _, ans = self._ask("how many roof drains", ["roof drains"])
        self.assertEqual(ans["outcome"], "chunk_count_not_stated")
        self.assertEqual(ans["text"],
                         "Not stated on the indexed drawings. Mentioned on P-100.00.")

    def test_stucco_thickness_quotes_the_line_with_the_value(self):
        _, ans = self._ask("what's the stucco thickness")
        self.assertEqual(ans["outcome"], "chunk_attribute")
        self.assertIn('A-500.00: 7/8" CEMENT STUCCO ON LATH', ans["text"])
        self.assertNotIn("PER SPEC", ans["text"])

    def test_an_attribute_with_no_value_line_falls_to_the_vision_model(self):
        has_v3, ans = self._ask("post gauge")
        self.assertTrue(has_v3)
        self.assertIsNone(ans)

    def test_the_handler_asks_before_retrieving(self):
        src = inspect.getsource(server._handle_plan_query)
        self.assertLess(src.index("_answer_plan_from_chunks("),
                        src.index("_retrieve_plan_candidates("))

    def test_a_v3_spatial_question_goes_to_one_sheet(self):
        src = inspect.getsource(server._handle_plan_query)
        self.assertIn("candidates = candidates[:1]", src)


class ThePageRowAndItsChunks(unittest.TestCase):

    FIELDS = dict(plan_extract.EMPTY_FIELDS, **{
        "sheet_number": "S-100.00", "sheet_title": "FOUNDATION PLAN",
        "contents_summary": "Foundation plan and pile schedule.",
        "materials": ['7/8" STUCCO'],
        "schedules": [{"name": "PILE SCHEDULE", "columns": ["MARK", "QTY"],
                       "rows": [["P1", "18"]]}],
    })

    def _index(self, page_text):
        db = _Db()
        calls = {"ocr": 0, "extract": 0}

        async def fake_extract(**kw):
            calls["extract"] += 1
            calls["page_text"] = kw["page_text"]
            return {"fields": self.FIELDS, "flags": {s: [] for s in plan_extract.SECTIONS},
                    "number_flags": [], "raw_vlm": {}, "prompt_text_chars": 0,
                    "prompt_text_truncated": False}

        async def fake_ocr(pid, jpeg):
            calls["ocr"] += 1
            return "OCR TEXT " * 30, None

        async def noop(*a, **k):
            return "key"

        async def emb(text):
            return [0.1, 0.2]

        with mock.patch.object(server, "db", db), \
                mock.patch.object(server.plan_extract, "extract_page", fake_extract), \
                mock.patch.object(server, "_ocr_page_text", fake_ocr), \
                mock.patch.object(server, "_upload_page_jpeg_to_r2", noop), \
                mock.patch.object(server, "_upload_page_thumb_to_r2", noop), \
                mock.patch.object(server, "_upload_page_base_to_r2", noop), \
                mock.patch.object(server, "_generate_embedding", emb), \
                mock.patch.object(server, "record_vision_call", noop):
            _run(server._index_single_page(
                project_id="p1", company_id="c1", file_id="f1", file_name="S.pdf",
                file_hash="h", page_number=2, discipline="ST",
                page_text=page_text, page_image_bytes=b"jpeg"))
        return db, calls

    def test_a_vector_page_is_version_3_with_the_v2_fields_filled(self):
        db, calls = self._index("FOUNDATION PLAN PILE SCHEDULE " * 10)
        self.assertEqual(calls["ocr"], 0, "a page with a text layer was OCR'd")
        row = db.document_page_index.rows[0]
        self.assertEqual(row["index_version"], 3)
        self.assertEqual(row["text_source"], "vector")
        self.assertEqual(row["materials"], '7/8" STUCCO')
        self.assertEqual(row["sheet_number"], "S-100.00")
        self.assertIsNone(row["superseded_by"])
        self.assertEqual(row["extraction"]["schedules"][0]["name"], "PILE SCHEDULE")

    def test_its_chunks_point_at_the_page(self):
        db, _ = self._index("FOUNDATION PLAN PILE SCHEDULE " * 10)
        page_id = db.document_page_index.rows[0]["_id"]
        kinds = sorted(c["chunk_type"] for c in db.document_page_chunks.rows)
        self.assertEqual(kinds, ["schedule", "specs"])
        for c in db.document_page_chunks.rows:
            self.assertEqual(c["page_id"], page_id)
            self.assertEqual(c["sheet_number"], "S-100.00")

    def test_a_scanned_page_is_ocrd_and_the_ocr_text_is_what_extraction_reads(self):
        db, calls = self._index("S-100")
        self.assertEqual(calls["ocr"], 1)
        self.assertTrue(calls["page_text"].startswith("OCR TEXT"))
        self.assertEqual(db.document_page_index.rows[0]["text_source"], "ocr")


class TheSkipThresholdDidNotMove(unittest.TestCase):
    """Raising it re-indexes every customer's every plan on the next sync."""

    def test_writer_is_3_and_skip_accepts_2(self):
        self.assertEqual(server.PLAN_INDEX_VERSION, 3)
        self.assertEqual(server.PLAN_INDEX_SKIP_MIN_VERSION, 2)
        src = inspect.getsource(server._index_pdf_file)
        self.assertIn('"index_version": {"$gte": PLAN_INDEX_SKIP_MIN_VERSION}', src)


class IndexingDoesNotLockOutWhatsApp(unittest.TestCase):

    def test_the_daily_cap_counts_questions_only(self):
        src = inspect.getsource(server._vision_budget_exceeded)
        self.assertIn('"endpoint": {"$in": [VISION_WHATSAPP_VQA]}', src)


class ChunksAreDeletedWithTheirPages(unittest.TestCase):

    def test_every_page_delete_site_deletes_chunks_too(self):
        for fn in (server.hard_delete_project, server.delete_project_file,
                   server.reindex_project_document, server.reindex_all_project_files):
            with self.subTest(fn=fn.__name__):
                src = inspect.getsource(fn)
                self.assertIn("document_page_chunks.delete_many(", src,
                              f"{fn.__name__} leaves chunks behind")


class OcrIsOptionalAndMetered(unittest.TestCase):

    def test_no_aws_credentials_is_a_flag_not_an_error(self):
        with mock.patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "", "AWS_SECRET_ACCESS_KEY": ""}):
            text, flag = _run(server._ocr_page_text("p1", b"jpeg"))
        self.assertEqual((text, flag), ("", "ocr_not_configured"))

    def test_metered_under_its_own_name(self):
        src = inspect.getsource(server._ocr_page_text)
        self.assertIn("VISION_PLAN_INDEX_OCR", src)
        self.assertLess(src.index("record_vision_call("), src.index("_textract_lines"))


if __name__ == "__main__":
    unittest.main()
