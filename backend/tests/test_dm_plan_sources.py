"""A sheet says what file and set it is on, and the brain can send its PDF.

Oct 27, the owner on WhatsApp: asked about sheets EN-001 / EN-002, then
"what file is it on", then "send me the PDF". The evidence named sheets only,
nothing could send a PDF, and nothing stopped "I can't send files".

  A. every search_plans record shown to the model names its file and its
     drawing set (project_files.drawing_track: "filed" | "post_co");
  B. send_plan_file sends the drawing's PDF -- the whole file, a sheet's
     page, a page range -- through the DM gate; over the size limit it says
     the limit; the eval sends nothing; "sent you the PDF" only when it ran;
  C. "I can't send PDFs" is re-asked;
  D. a sheet's own title wins over the drawing list's; sheets the list names
     that were never uploaded are said to be just that;
  E. a sheet from a set other than the filed one is cited with its set:
     "A-302 (owner's set)".

The fixtures are made-up sheets and files; no customer drawing is in them.
"""

from __future__ import annotations

import io
import json
import re
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import server  # noqa: E402
from lib import dm_brain, plan_sources  # noqa: E402
from tests.test_dm_brain import FakeLLM, last_tool_results, resp, text, use  # noqa: E402
from tests.test_dm_plan_answer_crop import PAGES, _Plans, _rec  # noqa: E402
from tests.test_dm_short_answers import CHAT  # noqa: E402
from tests.test_whatsapp_dm_assistant import THOMAS, WALWORTH, _db, _run  # noqa: E402
from tests.test_whatsapp_phase1_foundations import CO_A, _Ctx  # noqa: E402

FILES = [
    {"_id": "f1", "project_id": THOMAS, "company_id": CO_A, "name": "A-set.pdf",
     "r2_key": "co/588/A-set.pdf", "size": 2 * 1024 * 1024},
    {"_id": "f2", "project_id": THOMAS, "company_id": CO_A, "name": "Owner set.pdf",
     "r2_key": "co/588/Owner set.pdf", "size": 3 * 1024 * 1024,
     "drawing_track": "post_co", "drawing_track_label": "the owner's post-CO set (Owner set.pdf)"},
    {"_id": "f3", "project_id": THOMAS, "company_id": CO_A, "name": "Energy.pdf",
     "r2_key": "co/588/Energy.pdf", "size": 40 * 1024 * 1024},
]
OWNER_PAGE = {"_id": "pgO", "project_id": THOMAS, "file_id": "f2", "file_name": "Owner set.pdf",
              "page_number": 2, "sheet_number": "A-302", "sheet_title": "Fourth Floor Plan",
              "page_jpeg_r2_key": "plans/o/page_2.jpg"}
EN_PAGES = [
    {"_id": "pgE1", "project_id": THOMAS, "file_id": "f3", "file_name": "Energy.pdf",
     "page_number": 1, "sheet_number": "EN-001", "sheet_title": "Energy Notes",
     "page_jpeg_r2_key": "plans/e/page_1.jpg"},
    {"_id": "pgE2", "project_id": THOMAS, "file_id": "f3", "file_name": "Energy.pdf",
     "page_number": 2, "sheet_number": "EN-002", "sheet_title": "Energy Details",
     "page_jpeg_r2_key": "plans/e/page_2.jpg"},
]
DRAWING_LIST = {
    "project_id": THOMAS, "page_id": "pgN", "sheet_number": "S-001", "record_type": "schedule",
    "quote": "DRAWING LIST", "payload": {"name": "DRAWING LIST", "rows": [
        ["EN-001", "ENERGY CODE COMPLIANCE"], ["EN-002", "ENERGY DETAILS"],
        ["EN-003", "ENERGY ENVELOPE"], ["EN-004", "ENERGY LIGHTING"], ["A-201", "MECHANICAL PLAN"]]}}

FAN = _rec("pgA", "A-201", "EF-3 EXHAUST FAN 800 CFM", [720, 432, 792, 468])
FAN = dict(FAN, file_id="f1")
OWNER_FAN = dict(_rec("pgO", "A-302", "EF-4 EXHAUST FAN 600 CFM", [720, 432, 792, 468]),
                 file_id="f2", file_name="Owner set.pdf", page_number=2)


def _pdf(n):
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(n):
        w.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


class _Sources(_Plans):
    def setUp(self):
        super().setUp()
        self.db.project_files.rows.extend(dict(f) for f in FILES)
        self.db.document_page_index.rows.extend(dict(p) for p in [OWNER_PAGE] + EN_PAGES)
        self.db[server.PLAN_RECORDS].rows.append(dict(DRAWING_LIST))
        self.fetched_pdfs = []

    def patches(self, records):
        ps = super().patches(records)

        async def named(project_id, sheet_q):
            want = plan_sources.sheet_key(sheet_q)
            return [dict(p) for p in self.db.document_page_index.rows
                    if plan_sources.sheet_key(p.get("sheet_number")) == want][:1]

        async def fetch_pdf(frec, dest):
            self.fetched_pdfs.append(frec["r2_key"])
            with open(dest, "wb") as fh:
                fh.write(_pdf(3))

        async def live(project_id):
            return ["f1", "f2", "f3"]
        return [p for p in ps if p.attribute != "_find_named_sheet"] + [
            patch.object(server, "_find_named_sheet", named),
            patch.object(server, "_sheet_fetch_pdf", fetch_pdf),
            patch.object(server, "_live_plan_file_ids", live)]

    def documents(self, c):
        return [p for p in c.wire.calls if p.get("mediaName")]


# ── A. THE EVIDENCE NAMES ITS FILE AND SET ──────────────────────────────────

class TheEvidenceNamesItsSource(unittest.TestCase):
    def test_each_record_names_its_file_and_set(self):
        srcs = {"f1": plan_sources.source_of(FILES[0]), "f2": plan_sources.source_of(FILES[1])}
        out = server._render_records_for_model([FAN, OWNER_FAN], "exhaust fan", srcs)
        self.assertIn("[A-201 · A-set.pdf p3 · filed set]", out)
        self.assertIn("[A-302 (owner's set) · Owner set.pdf p2]", out)

    def test_without_sources_the_render_is_as_it_was(self):
        out = server._render_records_for_model([FAN], "exhaust fan")
        self.assertIn("- EF-3 EXHAUST FAN 800 CFM [A-201]", out)

    def test_the_set_field_is_the_files_drawing_track(self):
        self.assertEqual(plan_sources.source_of(FILES[0])["set_name"], "filed set")
        self.assertEqual(plan_sources.source_of(FILES[1])["set_name"], "owner's set")
        self.assertEqual(plan_sources.source_of({"_id": "x", "name": "n.pdf",
                                                 "drawing_track": "filed"})["track"], "filed")


class TheBrainIsShownTheSource(_Sources):
    def test_search_plans_result_names_file_and_set(self):
        seen = []

        def check(kw):
            seen.append(last_tool_results(kw)[0])
            return resp(text("EF-3 is an 800 CFM exhaust fan on A-201; EF-4, 600 CFM, on A-302 (owner's set)."))
        llm = FakeLLM(resp(use("search_plans", {"job": "588", "subject": "exhaust fan"})), check)
        with _Ctx(db=self.db) as c:
            out = self.ask(c, "exhaust fans on 588", llm, [FAN, OWNER_FAN])
        self.assertIn("A-set.pdf p3 · filed set", seen[0])
        self.assertIn("A-302 (owner's set) · Owner set.pdf p2", seen[0])
        self.assertEqual(out[0], "EF-3 is an 800 CFM exhaust fan on A-201; EF-4, 600 CFM, on A-302 (owner's set).")


# ── B. send_plan_file ───────────────────────────────────────────────────────

class SendPlanFile(_Sources):
    def test_the_page_a_sheet_is_on_goes_as_a_pdf(self):
        llm = FakeLLM(resp(use("send_plan_file", {"job": "588", "sheet": "A-201"})),
                      resp(text("Sent you the PDF of A-201.")))
        with _Ctx(db=self.db) as c:
            out = self.ask(c, "send me the PDF of A-201", llm, [])
            docs = self.documents(c)
        self.assertEqual(out, ["Sent you the PDF of A-201."])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["mediaName"], "A-set - page 3.pdf")
        self.assertEqual(self.fetched_pdfs, ["co/588/A-set.pdf"])
        token = docs[0]["mediaUrl"].rsplit("/", 1)[-1]
        row = next(r for r in self.db.temp_media_tokens.rows if r["token"] == token)
        self.assertEqual(row["content_type"], "application/pdf")
        self.assertTrue(row["r2_key"].startswith("temp/whatsapp/dm/"))
        from pypdf import PdfReader
        self.assertEqual(len(PdfReader(io.BytesIO(self.uploads[row["r2_key"]])).pages), 1)
        res = json.loads(json.dumps(llm.calls[1]))
        self.assertIn("Sent A-201, page 3 of A-set.pdf (filed set) to them as a PDF.",
                      last_tool_results(res)[0])

    def test_whole_file_is_the_stored_file(self):
        llm = FakeLLM(resp(use("send_plan_file", {"job": "588", "sheet": "A-302", "whole_file": True})),
                      resp(text("Sent you the PDF.")))
        with _Ctx(db=self.db) as c:
            self.ask(c, "send me the whole file A-302 is in", llm, [])
            docs = self.documents(c)
        self.assertEqual([d["mediaName"] for d in docs], ["Owner set.pdf"])
        token = docs[0]["mediaUrl"].rsplit("/", 1)[-1]
        row = next(r for r in self.db.temp_media_tokens.rows if r["token"] == token)
        self.assertEqual(row["r2_key"], "co/588/Owner set.pdf")
        self.assertEqual(self.fetched_pdfs, [])                          # nothing cut
        self.assertEqual(docs[0]["caption"], "A-302 (owner's set), Owner set.pdf (owner's set)")

    def test_a_page_range_of_a_file_by_name(self):
        llm = FakeLLM(resp(use("send_plan_file", {"job": "588", "file": "a-set", "pages": "2-3"})),
                      resp(text("Sent you pages 2-3 of the PDF.")))
        with _Ctx(db=self.db) as c:
            self.ask(c, "send pages 2-3 of the A set", llm, [])
            docs = self.documents(c)
        self.assertEqual([d["mediaName"] for d in docs], ["A-set - pages 2-3.pdf"])
        from pypdf import PdfReader
        key = next(r["r2_key"] for r in self.db.temp_media_tokens.rows
                   if r["token"] == docs[0]["mediaUrl"].rsplit("/", 1)[-1])
        self.assertEqual(len(PdfReader(io.BytesIO(self.uploads[key])).pages), 2)

    def test_over_the_limit_says_the_limit_and_sends_nothing(self):
        seen = []

        def check(kw):
            seen.append(last_tool_results(kw)[0])
            return resp(text("I can't send the whole Energy.pdf file: it is over the 25 MB limit. Want just the sheet's page?"))
        llm = FakeLLM(resp(use("send_plan_file", {"job": "588", "sheet": "EN-001", "whole_file": True})),
                      check)
        with _Ctx(db=self.db) as c:
            self.ask(c, "send me the energy PDF", llm, [])
            docs = self.documents(c)
        self.assertEqual(docs, [])
        self.assertTrue(seen[0].startswith("Not sent: Energy.pdf is 40.0 MB, over the 25 MB limit"), seen[0])

    def test_out_of_scope_sends_nothing(self):
        async def no(company_id, project_id):
            return None
        llm = FakeLLM(resp(use("send_plan_file", {"job": "588", "sheet": "A-201"})),
                      resp(text("That job isn't one I can read.")))
        with _Ctx(db=self.db) as c, patch.object(server, "_bot_project_scope", no):
            self.ask(c, "send me A-201 pdf", llm, [])
            docs = self.documents(c)
        self.assertEqual(docs, [])
        self.assertEqual(last_tool_results(llm.calls[1])[0], server.wa_security.BOT_SCOPE_REFUSAL)

    def test_a_sheet_listed_but_not_uploaded(self):
        seen = []

        def check(kw):
            seen.append(last_tool_results(kw)[0])
            return resp(text("EN-003 is in the drawing list but wasn't uploaded, so there's no PDF of it."))
        llm = FakeLLM(resp(use("send_plan_file", {"job": "588", "sheet": "EN-003"})), check)
        with _Ctx(db=self.db) as c:
            self.ask(c, "send me EN-003", llm, [])
            docs = self.documents(c)
        self.assertEqual(docs, [])
        self.assertIn("no PDF of it to send", seen[0])
        self.assertIn('EN-003 ("ENERGY ENVELOPE") is listed in the drawing list but not uploaded', seen[0])
        self.assertIn("EN-004 is listed in the drawing list but not uploaded.", seen[0])


class TheSentClaim(_Sources):
    def test_a_picture_is_not_the_pdf(self):
        """send_sheet ran, the answer says "sent you the PDF": re-asked."""
        notes = []

        def second(kw):
            notes.append(kw["messages"][-1]["content"])
            return resp(text("Sent you the picture of A-201."))
        llm = FakeLLM(resp(use("send_sheet", {"job": "588", "sheet": "A-201"})),
                      resp(text("Sent you the PDF of A-201.")), second)
        with _Ctx(db=self.db) as c:
            out = self.ask(c, "send me A-201", llm, [])
        self.assertEqual(out, ["Sent you the picture of A-201."])
        self.assertIn("no tool this turn", notes[0])

    def test_the_rule_itself(self):
        self.assertTrue(dm_brain.claims_file_sent("Sent you the PDF."))
        self.assertTrue(dm_brain.claims_file_sent("I've sent the file over."))
        self.assertFalse(dm_brain.claims_file_sent("Sent the report PDF for 588."))
        self.assertFalse(dm_brain.claims_file_sent("Sent you A-201."))
        self.assertFalse(dm_brain.claims_file_sent("EN-001 is in Energy.pdf."))


class TheEvalSendsNoFile(unittest.TestCase):
    def test_dry_run_records_the_file_and_sends_nothing(self):
        db = _db()
        db.document_page_index.rows.extend(dict(p) for p in PAGES)
        db.project_files.rows.extend(dict(f) for f in FILES)
        ident = {"user": {"name": "Admin"}, "user_id": "u_admin", "company_id": CO_A,
                 "role": "admin", "projects": [p for p in db.projects.rows
                                               if p["_id"] in (THOMAS, WALWORTH)]}
        fetched, uploads = [], []

        async def named(project_id, sheet_q):
            return [dict(p) for p in PAGES if p["sheet_number"] == sheet_q.upper()]

        async def fetch_pdf(frec, dest):
            fetched.append(frec)
        llm = FakeLLM(resp(use("send_plan_file", {"job": "588", "sheet": "A-201"})),
                      resp(text("Sent you the PDF of A-201.")))
        with _Ctx(db=db) as c, patch.object(server, "_dm_brain_client", lambda: llm), \
                patch.object(server, "_find_named_sheet", named), \
                patch.object(server, "_sheet_fetch_pdf", fetch_pdf), \
                patch.object(server, "_upload_to_r2", lambda *a, **k: uploads.append(a)):
            out = _run(server._dm_brain_answer(ident, CHAT, "send me the pdf of A-201", history=[],
                                               now=datetime.now(timezone.utc), dry_run=True,
                                               flows=[], active=None))
        self.assertEqual(out["sent"], ["[file A-set.pdf]"])
        self.assertEqual(out["reply"], "Sent you the PDF of A-201.")
        self.assertEqual((c.wire.calls, uploads, fetched), ([], [], []))
        self.assertEqual(db.temp_media_tokens.rows, [])


# ── C. NEVER "I CAN'T SEND FILES" ───────────────────────────────────────────

class NoFalseCantSend(_Sources):
    def test_cant_send_a_pdf_is_re_asked(self):
        notes = []

        def second(kw):
            notes.append(kw["messages"][-1]["content"])
            return resp(text("I can send it. Which sheet or file do you want?"))
        llm = FakeLLM(resp(text("I can't send PDF files here, only text.")), second)
        with _Ctx(db=self.db) as c:
            out = self.ask(c, "send me the PDF", llm, [])
        self.assertEqual(out, ["I can send it. Which sheet or file do you want?"])
        self.assertIn("send_plan_file", notes[0])

    def test_the_shapes(self):
        for said in ("I can't send PDF files here.", "I'm not able to send documents in WhatsApp.",
                     "I can only send images of the sheets.", "Unfortunately I cannot attach the file.",
                     "PDFs can't be sent in this chat.", "I can’t share files."):
            self.assertTrue(dm_brain.denies_file_send(said), said)
        for said in ("Sent you the PDF.", "EN-001 is in Energy.pdf.", "I can't find EN-009.",
                     "Energy.pdf is over the 25 MB limit, so it wasn't sent."):
            self.assertFalse(dm_brain.denies_file_send(said), said)

    def test_the_prompt_says_it_can(self):
        self.assertIn("You CAN send PDFs, files and documents of the drawings", dm_brain.SYSTEM_PROMPT)
        names = [t["function"]["name"] for t in server._dm_brain_tools()]
        self.assertIn("send_plan_file", names)
        self.assertIn("sheet_info", names)


# ── D. THE DRAWING LIST AGAINST THE SHEETS ──────────────────────────────────

class TheDrawingList(_Sources):
    def test_what_file_is_it_on(self):
        seen = []

        def check(kw):
            seen.append(last_tool_results(kw)[0])
            return resp(text("EN-001 Energy Notes is page 1 of Energy.pdf."))
        llm = FakeLLM(resp(use("sheet_info", {"job": "588", "sheet": "EN-001"})), check)
        with _Ctx(db=self.db) as c:
            self.ask(c, "what file is EN-001 on", llm, [])
        got = seen[0]
        self.assertIn("EN-001 is page 1 of Energy.pdf (filed set).", got)
        self.assertIn('the sheet\'s own title block reads "Energy Notes" -- that is its title', got)
        self.assertIn('The drawing list calls EN-001 "ENERGY CODE COMPLIANCE"', got)
        self.assertIn("EN-003, EN-004 are listed in the drawing list but not uploaded.", got)

    def test_same_title_says_nothing_about_the_list(self):
        lines = plan_sources.list_notes(
            "EN-002", "Energy Details", plan_sources.drawing_list([DRAWING_LIST]),
            ["EN-001", "EN-002", "EN-003", "EN-004"])
        self.assertEqual(lines, [])

    def test_the_list_is_read_off_its_rows(self):
        listed = plan_sources.drawing_list([{"payload": {"rows": [
            ["1", "EN-001.00", "ENERGY CODE COMPLIANCE", "10/01/2026"],
            ["2", "EN 002", "ENERGY DETAILS"], ["", "not a sheet"]]}}])
        self.assertEqual({k: v["title"] for k, v in listed.items()},
                         {"EN-001": "ENERGY CODE COMPLIANCE", "EN-002": "ENERGY DETAILS"})


# ── E. A NON-FILED SET IS NAMED WHERE IT IS CITED ───────────────────────────

class TheOwnersSetIsNamed(_Sources):
    def test_the_picture_names_the_owners_set(self):
        answer = "EF-4 is a 600 CFM exhaust fan on A-302 (owner's set)."

        def check(kw):
            return resp(text(answer))
        llm = FakeLLM(resp(use("search_plans", {"job": "588", "subject": "exhaust fan"})), check)
        with _Ctx(db=self.db) as c:
            out = self.ask(c, "EF-4 on 588?", llm, [OWNER_FAN])
            imgs = self.images(c)
        self.assertEqual(out, [answer])
        self.assertEqual([cap for cap, _i in imgs], ["A-302 (owner's set) — where this comes from"])

    def test_send_sheet_names_the_set_and_file(self):
        seen = []

        def check(kw):
            seen.append(last_tool_results(kw)[0])
            return resp(text("Sent you A-302 (owner's set)."))
        llm = FakeLLM(resp(use("send_sheet", {"job": "588", "sheet": "A-302"})), check)
        with _Ctx(db=self.db) as c:
            self.ask(c, "show me A-302", llm, [])
        self.assertTrue(re.match(r"Sent the image of A-302 \(owner's set\) Fourth Floor Plan to them\. "
                                 r"A-302 \(owner's set\) is page 2 of Owner set\.pdf \(owner's set\)\.$",
                                 seen[0]), seen[0])

    def test_a_filed_sheet_is_cited_bare(self):
        self.assertEqual(plan_sources.cite_with_set("A-201", plan_sources.source_of(FILES[0])), "A-201")
        self.assertEqual(plan_sources.cite_with_set("A-302", plan_sources.source_of(FILES[1])),
                         "A-302 (owner's set)")


class PageRanges(unittest.TestCase):
    def test_ranges(self):
        self.assertEqual(plan_sources.parse_pages("3-5, 8"), ([3, 4, 5, 8], ""))
        self.assertEqual(plan_sources.parse_pages("pages 3 to 5")[0], [3, 4, 5])
        self.assertEqual(plan_sources.parse_pages("2-4", 3), ([], "the file has 3 pages"))
        self.assertEqual(plan_sources.parse_pages("x")[0], [])
        self.assertEqual(plan_sources.pages_label([3, 4, 5, 8]), "pages 3-5, 8")


if __name__ == "__main__":
    unittest.main()
