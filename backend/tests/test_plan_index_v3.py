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


def _get_path(doc, key):
    cur = doc
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _match_one(doc, key, cond):
    val = _get_path(doc, key)
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
            if op == "$regex":
                import re as _re
                flags = _re.I if "i" in (cond.get("$options") or "") else 0
                if not (isinstance(v, str) and _re.search(arg, v, flags)):
                    return False
        return True
    return (None if val is _MISSING else val) == cond


def _matches(doc, q):
    for k, c in (q or {}).items():
        if k == "$or":
            if not any(_matches(doc, sub) for sub in c):
                return False
        elif not _match_one(doc, k, c):
            return False
    return True


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
                for k in u.get("$unset", {}):
                    r.pop(k, None)
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

    def _file(self, fid, days, name=None):
        self.db.project_files.rows.append(
            {"_id": fid, "project_id": "p1", "created_at": T0 + timedelta(days=days),
             "name": name})

    def _page(self, fid, page, sheet, file_hash, revision_date=None):
        self.db.document_page_index.rows.append({
            "_id": f"{fid}-{page}", "project_id": "p1", "file_id": fid,
            "page_number": page, "sheet_number": sheet, "file_hash": file_hash,
            "superseded_by": None, "revision_date": revision_date,
        })

    # ── 588 Thomas S Boyland St, as the first full re-index found it ──────

    def test_the_owners_set_is_not_hidden_by_a_re_synced_older_set(self):
        """Owners set - 6.9.26 vs AR - 3.28.25. AR was re-synced last, so by
        upload time it won and hid A-100…A-105. The title blocks say which is
        the later drawing."""
        self._file("owners", 0, "Owners set - 6.9.26.pdf")
        self._file("ar", 10, "AR - 3.28.25.pdf")
        for n, sn in enumerate(("A-100.00", "A-101.00"), start=1):
            self._page("owners", n, sn, "h-owners", revision_date="06/09/2026")
            self._page("ar", n + 10, sn, "h-ar", revision_date="03/28/2025")
        _run(server._supersede_plan_pages("p1"))
        self.assertIsNone(self._row("owners-1")["superseded_by"])
        self.assertEqual(self._row("ar-11")["superseded_by"], "owners")
        self.assertEqual(self._row("ar-12")["superseded_by"], "owners")

    def test_with_no_revision_date_the_file_names_date_decides(self):
        self._file("owners", 0, "Owners set - 6.9.26.pdf")
        self._file("ar", 10, "AR - 3.28.25.pdf")
        self._page("owners", 1, "A-100.00", "h-owners")
        self._page("ar", 11, "A-100.00", "h-ar")
        _run(server._supersede_plan_pages("p1"))
        self.assertIsNone(self._row("owners-1")["superseded_by"])
        self.assertEqual(self._row("ar-11")["superseded_by"], "owners")

    def test_sp_after_co_does_not_hide_the_later_sp_set(self):
        """'SP 4th floor after CO - 5.6.25.pdf' was uploaded after
        'SP - 6.24.26.pdf' and hid its SP-003.00. The June 2026 set is later."""
        self._file("sp", 0, "SP - 6.24.26.pdf")
        self._file("co", 5, "SP 4th floor after CO - 5.6.25.pdf")
        self._page("sp", 3, "SP-003.00", "h-sp")
        self._page("co", 1, "SP-003.00", "h-co")
        _run(server._supersede_plan_pages("p1"))
        self.assertIsNone(self._row("sp-3")["superseded_by"])
        self.assertEqual(self._row("co-1")["superseded_by"], "sp")

    def test_cover_energy_and_general_sheets_never_supersede_across_sets(self):
        """The structural set's T-001.00 was hidden by the architectural
        set's, and MH's EN-001.00 by PL's."""
        self._file("st", 0, "ST - 7.29.26.pdf")
        self._file("ar", 5, "AR - 8.18.26.pdf")
        self._file("mh", 0, "MH - 7.2.26.pdf")
        self._file("pl", 5, "PL - 8.1.26.pdf")
        self._page("st", 1, "T-001.00", "h-st")
        self._page("st", 2, "S-101.00", "h-st")
        self._page("ar", 1, "T-001.00", "h-ar")
        self._page("ar", 2, "A-100.00", "h-ar")
        self._page("ar", 3, "GN-001.00", "h-ar")
        self._page("mh", 12, "EN-001.00", "h-mh")
        self._page("mh", 1, "M-100.00", "h-mh")
        self._page("pl", 21, "EN-001.00", "h-pl")
        self._page("pl", 1, "P-100.00", "h-pl")
        self._file("ar2", 9, "AR - 9.1.26.pdf")
        self._page("ar2", 1, "GN-001.00", "h-ar2")
        self._page("ar2", 2, "A-101.00", "h-ar2")
        _run(server._supersede_plan_pages("p1"))
        superseded = [r["_id"] for r in self.db.document_page_index.rows if r["superseded_by"]]
        self.assertEqual(superseded, [])

    def test_the_same_number_in_another_discipline_is_not_a_revision(self):
        self._file("sp", 0, "SP - 6.24.26.pdf")
        self._file("ssp", 5, "SSP - 9.1.26.pdf")
        self._page("sp", 1, "SP-001.00", "h-sp")
        self._page("ssp", 1, "SSP-001.00", "h-ssp")
        self._page("ssp", 2, "SP-001.00", "h-ssp")
        _run(server._supersede_plan_pages("p1"))
        self.assertIsNone(self._row("sp-1")["superseded_by"])

    def test_dates_are_read_from_title_blocks_and_file_names(self):
        from datetime import date
        cases = {
            "03/28/2025": date(2025, 3, 28), "07-29-26": date(2026, 7, 29),
            "AR - 3.28.25.pdf": date(2025, 3, 28),
            "3540K25_588 THOMAS S BOYLAND STREET-AS BUILT 08-24-26.pdf": date(2026, 8, 24),
            "SD1-2 - 4.1.25.pdf": date(2025, 4, 1), "2026-06-09": date(2026, 6, 9),
            "B01141294-11": None, None: None,
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(server._parse_sheet_date(text), want)

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

    def test_a_v3_spatial_question_goes_to_at_most_two_sheets(self):
        # Was [:1]. Changed 2026-09-16: with one candidate a single timed-out
        # vision call was the whole answer — "Whats the helical piles" spent
        # 98 seconds to say "not found". Two sheets at
        # PLAN_VQA_TIMEOUT_SECONDS still cost less than the one call did, and
        # the point of the cap — not walking the whole set — is unchanged.
        src = inspect.getsource(server._handle_plan_query)
        self.assertIn("candidates = candidates[:2]", src)
        self.assertLessEqual(server.PLAN_VQA_TIMEOUT_SECONDS * 2, 90.0)


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


class ARestartResumesInsteadOfSkipping(unittest.TestCase):

    def _db(self, rows):
        db = _Db()
        db.document_page_index.rows.extend(rows)
        return db

    def test_only_complete_v3_pages_and_v2_pages_count_as_done(self):
        db = self._db([
            {"file_id": "f", "file_hash": "h", "page_number": 1, "index_version": 3, "page_complete": True},
            {"file_id": "f", "file_hash": "h", "page_number": 2, "index_version": 3, "page_complete": False},
            {"file_id": "f", "file_hash": "h", "page_number": 3, "index_version": 2},
            {"file_id": "f", "file_hash": "other", "page_number": 4, "index_version": 3, "page_complete": True},
        ])
        with mock.patch.object(server, "db", db):
            done = _run(server._pages_already_indexed("f", "h"))
        self.assertEqual(done, {1, 3})

    def test_a_failed_lookup_skips_the_file_as_before(self):
        class Boom:
            def find(self, *a, **k):
                raise RuntimeError("down")
        db = _Db()
        db._c["document_page_index"] = Boom()
        with mock.patch.object(server, "db", db):
            self.assertIsNone(_run(server._pages_already_indexed("f", "h")))

    def test_the_file_indexes_only_the_pages_left(self):
        src = inspect.getsource(server._index_pdf_file)
        self.assertIn("todo = [p for p in todo if p not in done]", src)
        self.assertIn("for n in batch", src)

    def test_the_endpoints_can_resume_without_deleting(self):
        for fn in (server.reindex_project_document, server.reindex_all_project_files):
            with self.subTest(fn=fn.__name__):
                self.assertIn("resume", inspect.signature(fn).parameters)
                self.assertIn("if not resume:", inspect.getsource(fn))


class AVectorPageIsOneCallAndItsSpecPageIsStillChunked(unittest.TestCase):

    LAYOUT = {
        "page_number": 2, "width": 2592, "height": 1728, "fractions_rebuilt": 0,
        "fractions_unverified": [], "tables": [],
        "blocks": [
            {"bbox": [100, 400, 900, 800], "lines": ["1.", "ALL PILES SHALL BE HELICAL PILES."],
             "text": "1.\nALL PILES SHALL BE HELICAL PILES."},
            {"bbox": [100, 1600, 900, 1700], "lines": ["S-001.00", "GENERAL NOTES"],
             "text": "S-001.00\nGENERAL NOTES"},
        ],
    }
    LAYOUT["text"] = "\n".join(b["text"] for b in LAYOUT["blocks"]) + (" FILLER TEXT" * 20)

    def _index(self, layout, page_text):
        db = _Db()
        calls = {"vlm": 0}

        class _Resp:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": '{"sheet_number": "2"}'},
                                     "finish_reason": "stop"}]}

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **k):
                calls["vlm"] += 1
                return _Resp()

        async def noop(*a, **k):
            return "key"

        async def emb(text):
            return [0.1]

        with mock.patch.object(server, "db", db), \
                mock.patch.object(server, "ServerHttpClient", _Client), \
                mock.patch.object(server, "_upload_page_jpeg_to_r2", noop), \
                mock.patch.object(server, "_upload_page_thumb_to_r2", noop), \
                mock.patch.object(server, "_upload_page_base_to_r2", noop), \
                mock.patch.object(server, "_generate_embedding", emb), \
                mock.patch.object(server, "record_vision_call", noop):
            _run(server._index_single_page(
                project_id="p1", company_id="c1", file_id="f1", file_name="ST.pdf",
                file_hash="h", page_number=2, discipline="ST", page_text=page_text,
                page_image_bytes=b"jpeg", layout=layout))
        return db, calls

    def test_one_model_call_and_the_row_is_complete(self):
        db, calls = self._index(self.LAYOUT, self.LAYOUT["text"])
        self.assertEqual(calls["vlm"], 1)
        row = db.document_page_index.rows[0]
        self.assertEqual(row["text_source"], "vector")
        self.assertEqual(row["vlm_calls"], 1)
        self.assertEqual(row["sheet_number"], "S-001.00")
        self.assertTrue(row["page_complete"])
        self.assertTrue(any(c["chunk_type"] == "notes" for c in db.document_page_chunks.rows))

    def test_a_spec_page_makes_no_call_and_its_notes_are_chunks(self):
        long_lines = "\n".join(["ALL STRUCTURAL WORK SHALL CONFORM TO THE BUILDING CODE OF NYC."] * 120)
        layout = dict(self.LAYOUT, text=long_lines)
        db, calls = self._index(layout, long_lines)
        self.assertEqual(calls["vlm"], 0)
        row = db.document_page_index.rows[0]
        self.assertTrue(row["is_spec_page"])
        self.assertEqual(row["sheet_number"], "S-001.00")
        self.assertTrue(row["page_complete"])
        self.assertTrue(db.document_page_chunks.rows)
        # Searchable like any sheet, and it has an image to send.
        self.assertIn("ALL PILES SHALL BE HELICAL PILES.", row["notes"])
        self.assertNotEqual(row["sheet_title"], "[SPECIFICATION PAGE]")
        self.assertEqual(row["page_jpeg_r2_key"], "key")

    def test_a_spec_page_is_found_by_its_sheet_number(self):
        db = _Db()
        db.project_files.rows.append({"_id": "f1", "project_id": "p1"})
        db.document_page_index.rows.append({
            "_id": "s1", "project_id": "p1", "file_id": "f1", "sheet_number": "S-001.00",
            "is_spec_page": True, "sheet_title": None, "superseded_by": None})
        with mock.patch.object(server, "db", db):
            hits = _run(server._retrieve_plan_candidates("p1", {"sheet_number": "S-001"},
                                                         "show me S-001"))
        self.assertEqual([h["_id"] for h in hits], ["s1"])


class ACombinedSetIsNotSentToVision(unittest.TestCase):

    PROFILE = {"vector_pages": 44, "title_id_pages": 6,
               "title_prefixes": ["A"], "text_prefixes": ["A"]}

    def setUp(self):
        self.db = _Db()
        p = mock.patch.object(server, "db", self.db)
        p.start()
        self.addCleanup(p.stop)
        self.db.project_files.rows.extend([
            {"_id": "combo", "project_id": "p1", "name": "588 THOMAS BOYLAND ST SET_UPDATED.pdf"},
            {"_id": "ar", "project_id": "p1", "name": "AR - 3.28.25.pdf"},
        ])

    def _gate(self, deferrals=0, can_defer=True):
        return _run(server._combined_set_gate(
            "p1", {"_id": "combo", "name": "588 THOMAS BOYLAND ST SET_UPDATED.pdf"},
            "combo", self.PROFILE, deferrals, can_defer))

    def test_covered_by_an_indexed_discipline_set_it_is_skipped_and_says_why(self):
        self.db.document_page_index.rows.extend([
            {"project_id": "p1", "file_id": "ar", "sheet_number": "A-100.00"},
            {"project_id": "p1", "file_id": "ar", "sheet_number": "A-101.00"},
        ])
        self.assertEqual(self._gate(), "skipped")
        status = self.db.project_files.rows[0]["index_status"]
        self.assertEqual(status["state"], "skipped_combined_set")
        self.assertEqual(status["covered_by"], ["AR - 3.28.25.pdf"])
        self.assertIn("no sheet number in the title block", status["reason"])

    def test_it_waits_while_the_projects_other_files_are_still_queued(self):
        self.db.plan_index_jobs.rows.append({"_id": "ar", "project_id": "p1", "status": "queued"})
        self.assertEqual(self._gate(), "deferred")
        self.assertNotIn("index_status", self.db.project_files.rows[0])

    def test_with_nothing_else_queued_an_uncovered_file_is_indexed(self):
        self.db.plan_index_jobs.rows.append({"_id": "ar", "project_id": "p1", "status": "done"})
        self.assertEqual(self._gate(), "index")

    def test_after_the_last_wait_it_is_indexed(self):
        self.db.plan_index_jobs.rows.append({"_id": "ar", "project_id": "p1", "status": "queued"})
        self.assertEqual(self._gate(deferrals=server.COMBINED_MAX_DEFERRALS), "index")

    def test_two_waiting_combined_files_do_not_wait_for_each_other(self):
        """As-built, cross connection and shed each waited for the other two
        and none of them was ever indexed."""
        self.db.plan_index_jobs.rows.append(
            {"_id": "ar", "project_id": "p1", "status": "queued", "deferrals": 1})
        self.assertEqual(self._gate(), "index")

    def test_a_running_job_still_counts_as_pending(self):
        self.db.plan_index_jobs.rows.append(
            {"_id": "ar", "project_id": "p1", "status": "running", "deferrals": 2})
        self.assertEqual(self._gate(), "deferred")

    def test_a_file_showing_no_discipline_is_indexed_without_waiting(self):
        self.db.plan_index_jobs.rows.append({"_id": "ar", "project_id": "p1", "status": "queued"})
        profile = dict(self.PROFILE, text_prefixes=[])
        verdict = _run(server._combined_set_gate(
            "p1", {"_id": "combo", "name": "cross connection - 6.13.25.pdf"},
            "combo", profile, 0, True))
        self.assertEqual(verdict, "index")

    def test_a_direct_call_with_no_job_never_defers(self):
        self.db.plan_index_jobs.rows.append({"_id": "ar", "project_id": "p1", "status": "queued"})
        self.assertEqual(self._gate(can_defer=False), "index")

    def test_a_skipped_file_is_not_live_for_retrieval(self):
        self.db.project_files.rows[0]["index_status"] = {"state": "skipped_combined_set"}
        self.assertEqual(_run(server._live_plan_file_ids("p1")), ["ar"])

    def test_both_file_listings_carry_the_status(self):
        for fn in (server.get_project_dropbox_files, server.get_document_index_status):
            with self.subTest(fn=fn.__name__):
                self.assertIn("_public_index_status(", inspect.getsource(fn))
        self.assertEqual(
            server._public_index_status({"state": "skipped_combined_set", "reason": "r",
                                         "title_id_pages": 6, "internal": 1}),
            {"state": "skipped_combined_set", "reason": "r", "disciplines": None,
             "covered_by": None, "at": None})

    def test_the_gate_runs_before_any_page_is_indexed(self):
        src = inspect.getsource(server._index_pdf_file)
        self.assertLess(src.index("_combined_set_gate("), src.index("_process_page(n)"))


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
