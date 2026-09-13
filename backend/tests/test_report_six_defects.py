"""The six defects the operator found on the investor report.

THIS IS THE DOCUMENT AN INVESTOR READS. Every one of these was visible on a
real report for project 6a5f63bc147407d3261df2c7, 2026-08-11, and none of them
would have been caught by any existing test — the report renderer is 1,200
lines of f-strings with no coverage of what it actually prints.

Asserted against the SOURCE of generate_combined_report and
render_logbook_html, because both are single async functions that need a
database to run. Where behaviour can be executed (the dedupe key, the
conditional times block) it is executed rather than grepped.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from tests.source_text import strip_js, code_of  # noqa: E402  -- shared helpers the absence-literals classifier recognises

import server  # noqa: E402
from tests.document_renderers import (  # noqa: E402
    N_DOCUMENT_RENDERERS as N_RENDERERS)

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")

# The two renderers. generate_single_logbook_html prints ONE stored logbook as
# its own PDF; generate_combined_report prints the whole day, and is the
# document the investor reads.
_REPORT = _SRC[_SRC.index("async def generate_combined_report"):]
_REPORT = _REPORT[:_REPORT.index('async def get_combined_report(')]
_SINGLE = _SRC[_SRC.index("async def generate_single_logbook_html"):]
_SINGLE = _SINGLE[:_SINGLE.index("async def generate_combined_report")]

#: The three-page renderer's own source, for assertions about what the
#: INVESTOR page says. The report is no longer a slab of server.py.
_REPORT_PKG = Path(__file__).resolve().parent.parent / "lib" / "report"
_RENDER_SRC = "".join(
    (_REPORT_PKG / name).read_text(encoding="utf-8")
    for name in ("renderer.py", "view.py", "model.py"))


# ── A REAL RENDER, from a stored payload ─────────────────────────────────────
#
# THE GAP THIS CLOSES. Every assertion in this file used to read server.py's
# SOURCE, and the one that claimed to execute ran a local copy of the shipped
# function. So the suite proved the code shipped and proved nothing about the
# document — which is exactly how #126 went green while the operator's report
# was unchanged. Below, generate_combined_report is CALLED against a fake
# database holding the production shape, and the assertions read the HTML.

class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, *a, **k):
        return list(self._docs)


class _Coll:
    def __init__(self, docs=None, one=None):
        self._docs = docs or []
        self._one = one

    def find(self, *a, **k):
        return _Cursor(self._docs)

    async def find_one(self, *a, **k):
        return self._one

    async def to_list(self, *a, **k):
        return list(self._docs)


class _Db:
    def __init__(self, **colls):
        self._c = colls

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._c.get(n) or _Coll()


# The production shape: ONE man, TWO rows in the stored pre-shift payload —
# one carrying his card id from the gate, one from legacy carrying none. This
# is a FILED record, so no endpoint fix can change it; the report must render
# what is stored, and the test must see that.
_DAY_WITH_DUPLICATE = {
    "preshift": {
        "_id": "lb_ps", "log_type": "preshift_signin", "date": "2026-08-12",
        "data": {"company": "AAZ", "workers": [
            {"name": "WILMER CARRILLO", "company": "AAZ", "osha_number": "SST-1",
             "had_injury": "no", "inspected_ppe": "yes"},
            {"name": "WILMER CARRILLO", "company": "AAZ", "osha_number": "",
             "had_injury": None, "inspected_ppe": None},
            {"name": "", "company": "AAZ", "osha_number": ""},   # nameless seed
        ]},
    },
    "toolbox": {
        "_id": "lb_tb", "log_type": "toolbox_talk", "date": "2026-08-12",
        "data": {"attendees": [
            {"name": "Segundo Pilamunga", "company": "AAZ"},
            {"name": "", "company": ""},                          # nameless seed
        ], "checked_topics": {}},
    },
    "jobsite": {
        "_id": "lb_dj", "log_type": "daily_jobsite", "date": "2026-08-12",
        "data": {"activities": [{
            "crew_id": "C1", "company": "AAZ", "num_workers": "4",
            "work_description": "Rebar installation", "work_locations": "",
            "photos": [{"enhance_status": "done", "original_r2_key": "k"}],
        }], "equipment_on_site": {}, "checklist_items": {}, "observations": []},
    },
}


def _filed_documents(db, project_id, date):
    """Every filed document for the day, as the reader reaches them.

    THE INVESTOR REPORT NO LONGER EMBEDS THESE, and that is why this exists.
    The report carries a record index whose cards link to the per-logbook PDF;
    the rules below are about what a filed document SAYS, and a filed document
    says it on the legal render now. So the subject moved and not one assertion
    did, which is the test of whether the removal lost anything.

    `_filed_log` picks the same document the card links to -- the latest signed
    record for each type -- so this is the set of documents the index points at
    and nothing else.
    """
    with patch.object(server, "db", db):
        logbooks = asyncio.run(db.logbooks.find({}).to_list(None))
        out = []
        for _t in sorted({l.get("log_type") for l in logbooks if l.get("log_type")}):
            _lb = server._filed_log(logbooks, _t)
            if _lb:
                out.append(asyncio.run(server.generate_single_logbook_html(_lb)))
        return "\n".join(out)


def _db_for(day, jobsite_extra=None, extra_logs=(), checkins=None):
    jobsite = dict(day["jobsite"])
    if jobsite_extra:
        jobsite = {**jobsite, "data": {**jobsite["data"], **jobsite_extra}}
    return _Db(
        projects=_Coll(one={"_id": "p1", "name": "8 Walworth St",
                            "address": "8 Walworth St"}),
        logbooks=_Coll(docs=[day["preshift"], day["toolbox"], jobsite,
                             *extra_logs]),
        daily_logs=_Coll(one=None),
        workers=_Coll(docs=[]),
        checkins=_Coll(docs=checkins if checkins is not None else []),
    )


def _render_documents(day, jobsite_extra=None):
    """The filed documents for the day. See `_filed_documents`."""
    return _filed_documents(_db_for(day, jobsite_extra), "p1", "2026-08-12")


def _render_documents_with_osha(day):
    return _filed_documents(_db_for(day, extra_logs=[day["osha"]]),
                            "p1", "2026-08-12")


def _render(day, jobsite_extra=None):
    """Call the real renderer against a fake db and return the HTML."""
    jobsite = dict(day["jobsite"])
    if jobsite_extra:
        jobsite = {**jobsite, "data": {**jobsite["data"], **jobsite_extra}}
    logbooks = [day["preshift"], day["toolbox"], jobsite]
    db = _Db(
        projects=_Coll(one={"_id": "p1", "name": "8 Walworth St", "address": "8 Walworth St"}),
        logbooks=_Coll(docs=logbooks),
        daily_logs=_Coll(one=None),
        checkins=_Coll(docs=[
            {"worker_id": "w1", "worker_name": "WILMER CARRILLO", "company": "AAZ",
             "status": "checked_in"},
            {"worker_id": "w2", "worker_name": "Segundo Pilamunga", "company": "AAZ",
             "status": "checked_in"},
            {"worker_id": "w3", "worker_name": "Third Man", "company": "AAZ",
             "status": "checked_in"},
        ]),
    )
    with patch.object(server, "db", db):
        return asyncio.run(server.generate_combined_report("p1", "2026-08-12"))


def _render_with_osha(day):
    """Same fake db as _render, plus an osha_log in the logbook list."""
    logbooks = [day["preshift"], day["toolbox"], day["jobsite"], day["osha"]]
    db = _Db(
        projects=_Coll(one={"_id": "p1", "name": "8 Walworth St", "address": "8 Walworth St"}),
        logbooks=_Coll(docs=logbooks),
        daily_logs=_Coll(one=None),
        workers=_Coll(docs=[]),
        checkins=_Coll(docs=[]),
    )
    with patch.object(server, "db", db):
        return asyncio.run(server.generate_combined_report("p1", "2026-08-12"))


class TheRenderedDocument(unittest.TestCase):
    """Assertions on what a FILED DOCUMENT says.

    These read the investor report until the record index replaced the embedded
    documents on it. Every rule below is about the content of a filed log -- a
    duplicated crew row, a nameless attendee, a hand-typed count against a gate
    count -- and a filed log is reached through the index now. The subject
    moved; the assertions did not.
    """

    @classmethod
    def setUpClass(cls):
        # TWO SUBJECTS, AND THEY USED TO BE ONE STRING. Some of these rules are
        # about the REPORT -- one header, photographs on page 1 -- and some are
        # about what a FILED DOCUMENT says. The report embedded the documents,
        # so one render answered both and nothing forced the distinction. It
        # does now.
        cls.html = _render(_DAY_WITH_DUPLICATE)
        cls.docs = _render_documents(_DAY_WITH_DUPLICATE)

    def test_it_renders_at_all(self):
        self.assertIn("Daily Construction Report", self.html)
        self.assertIn("Executive summary", self.html)
        self.assertIn("Pre-Shift Sign-In", self.html)

    def test_the_stored_duplicate_STILL_RENDERS_TWICE(self):
        """THE HONEST ASSERTION, and the one that would have caught #126's
        claim. The endpoint dedupe cannot touch a filed payload: the report
        prints what is stored, so an already-duplicated log keeps both rows.
        If a later change starts collapsing them at RENDER time, this fails and
        that decision gets made deliberately."""
        # Rendered verbatim — _capitalize_first only touches the first letter.
        self.assertEqual(self.docs.count("WILMER CARRILLO"), 2)

    def test_the_nameless_rows_do_not_render(self):
        """Pre-shift skipped these already; toolbox did not until #126."""
        # ANCHORED ON THE SECTION HEADER, not on the bare name. Page 1's
        # compliance line names the required logs too, and it resolves them
        # through LOGBOOK_TYPE_REGISTRY — which used to say "Pre-Shift Safety
        # Meeting", so the first occurrence of this string happened to be the
        # page-2 header. Now that the registry agrees with the renderer the
        # name appears on page 1 as well, and a bare .index() slices from the
        # compliance line into the wrong table. This is section_title's own
        # closing markup, which nothing else emits.
        # ANCHORED ON EACH DOCUMENT'S OWN ROSTER HEADER. The old anchor was
        # `section_title`'s closing markup on the report, which the report no
        # longer emits for these documents; the per-logbook PDFs carry their
        # own table headers and those are what the rows belong to.
        preshift = self.docs[self.docs.index(">OSHA #</th>"):]
        preshift = preshift[:preshift.index("</table>")]
        # Two DATA rows — the third stored worker has no name and is dropped.
        self.assertEqual(preshift.count("<tr><td "), 2)
        att = self.docs[self.docs.index(">Title</th>"):]
        att = att[:att.index("</table>")]
        # One attendee; the nameless seed row is dropped (this was the #126 fix).
        self.assertEqual(att.count("<tr><td "), 1)
        self.assertIn("Segundo Pilamunga", att)

    def test_the_address_and_date_are_stated_where_they_belong(self):
        """── THE DEFECT WAS THREE ADDRESSES AND TWO DATES IN ONE SHELL ─────

        The old header printed the address three times and the date twice,
        stacked in one block, and the reader could not tell which was the
        document's subject and which was decoration. So the rule was one of
        each.

        PAGE 1 NOW HAS A MASTHEAD OVER A HERO, by the operator's ruling of 12
        September against a supplied reference, and those are two different
        statements rather than one repeated: the masthead is the letterhead --
        who issued this and about which job, at 7.5px -- and the hero is the
        document's subject, at 35px. The reference is explicit that the
        address is the dominant element, and a dominant element needs
        something to dominate.

        WHAT THE RULE BECOMES is that each region says it ONCE. Two regions,
        one address each; the dateline belongs to the hero alone, because a
        letterhead does not carry a date.
        """
        body = self.html[self.html.index("<body"):]
        head = body[:body.index("Executive summary")].upper()
        mast = head[:head.index('CLASS="HERO"')]
        hero = head[head.index('CLASS="HERO"'):]

        self.assertEqual(mast.count("8 WALWORTH ST"), 1,
                         "the masthead states the address more than once")
        self.assertEqual(hero.count("8 WALWORTH ST"), 1,
                         "the hero states the address more than once")
        self.assertEqual(mast.count("AUGUST 12, 2026"), 0,
                         "the masthead carries a date; it is a letterhead")
        self.assertEqual(hero.count("AUGUST 12, 2026"), 1,
                         "the date is printed more than once in the hero")

    def test_the_crew_count_is_labelled_and_the_gate_count_is_too(self):
        """The two counts disagree and both are true, so each says whose it is.

        THE LABELS NOW LIVE ON DIFFERENT DOCUMENTS, which is the same fact
        restated: the CP's hand-typed crew count is on his filed log, and the
        gate's count is on the report that summarises the day. Neither number
        appears unlabelled anywhere.
        """
        # THE LABELS MOVED WITH THE PAGES AND THE RULE DID NOT. The
        # conducting party's hand-typed count is on his filed log; the gate's
        # is on the report. Neither number appears unlabelled, and where they
        # differ the report prints BOTH -- which is stronger than the old
        # cover, where one was a tile and the other a table column.
        # UNESCAPED BEFORE THE COMPARISON. The branch wrote the apostrophe
        # as &#39; and `html.escape` writes &#x27;; both are an apostrophe on
        # paper, and an assertion that can be broken by which entity a library
        # chose is not asserting the label.
        import html as _h
        self.assertIn("CP's count", _h.unescape(self.docs))
        self.assertIn("Gate check-ins", self.html)
        self.assertIn("on daily log", self.html)

    def test_photographs_are_evidence_and_live_on_their_own_page(self):
        """THE RULING INVERTED, DELIBERATELY, AND THE REASON IS UNCHANGED.

        It read: progress evidence for the investor, not a second copy inside
        the compliance filing. The compliance filing is no longer inside this
        document at all, so there is no second copy to avoid -- and the
        photographs were promoted to a page of their own, because the evidence
        is most of why anybody reads the report.

        WHAT SURVIVES IS THE HALF THAT MATTERED: the photographs appear ONCE.
        Page 1 carries none and Page 2 carries them all.
        """
        page1 = self.html.split('class="p2"', 1)[0]
        self.assertNotIn("reports/logbook-photo", page1,
                         "a photograph is on the executive brief")
        self.assertIn("reports/logbook-photo", self.html,
                      "the evidence page lost its photographs")

    def test_no_unaffirmed_warning_bleeds_onto_page_1(self):
        page1 = self.html.split('<div style="page-break-after:always;"></div>', 1)[0]
        self.assertNotIn("UNAFFIRMED", page1)


# DELETED: OneHeaderOnly
#   the old shell printed the address three times and the date twice. The banner prints each once BY CONSTRUCTION -- there is one place that emits them -- and test_report_renderer.py::TheBanner asserts the block is identical on Pages 1 and 3.
#   See docs/audits/report-replacement-ledger.md.

class TheBlankRowIsGoneEverywhere(unittest.TestCase):
    """DEFECT 3 — a seed row the CP never filled printed as a blank line on a
    signed attendance record: a person who was there and cannot be named."""

    def test_toolbox_talk_skips_a_nameless_attendee(self):
        # THE OWNER MOVED, THE RULE DID NOT. A nameless attendee is dropped
        # because the claim on a roster is about a NAMED person; the report
        # embedded that roster and now indexes it, so the guard is read off
        # the document's own renderer.
        block = _SINGLE[_SINGLE.index('for a in data.get("attendees"'):]
        block = block[:block.index("att_rows +=")]
        self.assertIn('if not str(a.get("name") or "").strip():', block)
        self.assertIn("continue", block)

    def test_the_per_logbook_PDF_skips_one_too(self):
        """DEVICE ROUND 6, item 2. The gate above was applied to the emailed
        report and nowhere else, while its own comment said the pre-shift sheet
        and the OSHA register "already use" it and this table "was the one that
        never got it". The second half was false: render_logbook_html — the
        document an inspector asks for BY NAME — had no name gate on this table
        at all, so one stored talk printed two different attendance records.

        A nameless row there was not blank, either: it carried Present ✓ from
        the CP's mark and Confirmed at gate ✓ from a worker tap, against a man
        the record does not identify."""
        block = _SINGLE[_SINGLE.index('for a in data.get("attendees"'):]
        block = block[:block.index("att_rows +=")]
        self.assertIn('if not str(a.get("name") or "").strip():', block)
        self.assertIn("continue", block)

    def test_preshift_already_skipped_and_still_does(self):
        """It was never the defect on this table — asserted so a later change
        cannot quietly remove the rule the other tables were brought up to."""
        # COUNTED BY SHAPE, NOT BY SPELLING. This pinned the literal
        # `if w.get("name", "").strip():`, which is the form that RAISES
        # AttributeError on a stored `name: None` — the value correcting a
        # worker called "null" produces. Fixing that took the literal with it
        # and this assertion failed about a rule that had not changed.
        #
        # The invariant is "both preshift renderers gate a row on a non-blank
        # name", and it is expressed as that now: any guard on w's name, in
        # either safe or unsafe spelling, counted twice. A regression that
        # DELETES a guard still fails; a rewording does not.
        guards = re.findall(
            r'if (?:str\()?w\.get\("name"(?:, "")?\)(?: or "")?\)?\.strip\(\):',
            _SRC)
        self.assertEqual(len(guards), N_RENDERERS, guards)
        # And the unsafe spelling specifically must not come back.
        self.assertNotIn('w.get("name", "").strip()', _SRC)

    def test_the_osha_register_drops_a_row_that_names_nobody(self):
        """WIDENED, device round 6 item 1. It skipped a row carrying none of
        five fields — the untouched seed — and printed one carrying a company
        and a card number against no name. A certification register is a list
        of statements about named men, so the name is the rule and the seed
        row (which has no name either) is still dropped by it."""
        # ENDED AT THE GENERIC ARM, NOT AT THE NEXT TYPE. `osha_log` became
        # the LAST named branch when the orientation sheet's was deleted, so
        # this raised `substring not found`. The generic arm follows the last
        # named branch whichever type that is.
        branch = _SINGLE[_SINGLE.index('elif log_type == "osha_log":'):]
        branch = branch[:branch.index(
            'type_title = log_type.replace("_", " ").title()')]
        m = re.search(r"has\(e, k\) for k in\s*\n?\s*\(([^)]*)\)", branch)
        self.assertIsNotNone(m, "the osha row gate is unreadable")
        self.assertEqual(tuple(re.findall(r'"([a-z_]+)"', m.group(1))),
                         ("worker_name",))


class TheDuplicateWorkerRow(unittest.TestCase):
    """DEFECT 4 — one man, two rows on the pre-shift sheet: one carrying his
    card id from the gate system, one from legacy carrying none."""

    def test_the_key_is_whitespace_normalised(self):
        self.assertIn("def _norm_key(v):", _SRC)
        self.assertEqual(_SRC.count("name_key = (name.lower(), company.lower())"), 0,
                         "a raw lowercased key survives somewhere")
        self.assertEqual(_SRC.count("name_key = (_norm_key(name), _norm_key(company))"), 3)

    def test_normalisation_collapses_the_shapes_that_split_him(self):
        """THE SHIPPED FUNCTION, not a copy of it.

        This test used to define its own `_norm_key` and assert against that —
        so it passed while proving only that the test's own arithmetic worked.
        It is extracted from server.py's source and executed, so a change to
        the real normaliser fails here."""
        ns = {}
        src = _SRC[_SRC.index("    def _norm_key(v):"):]
        src = src[:src.index("\n\n", src.index("return"))]
        exec(textwrap.dedent(src), ns)          # noqa: S102 — the shipped body
        _norm_key = ns["_norm_key"]
        gate = ("Wilmer Carrillo", "AAZ")
        for legacy in [("wilmer carrillo", "aaz"), ("Wilmer  Carrillo", "AAZ "),
                       (" Wilmer Carrillo", " AAZ"), ("WILMER CARRILLO", "AAZ")]:
            with self.subTest(legacy=legacy):
                self.assertEqual(
                    (_norm_key(gate[0]), _norm_key(gate[1])),
                    (_norm_key(legacy[0]), _norm_key(legacy[1])),
                )
        # And it must still SPLIT the cases the operator was told stay split.
        self.assertNotEqual(_norm_key("Wilmer J Carrillo"), _norm_key("Wilmer Carrillo"))
        self.assertNotEqual(_norm_key("AAZ Construction"), _norm_key("AAZ"))

    def test_pass_one_deliberately_does_NOT_dedupe_on_the_string_key(self):
        """REPORTED AS AN OPEN PATH, THEN RULED AGAINST — and correctly.

        Pass 1 keys on worker_enrollment_id alone. `worker_enrollments` carries
        a UNIQUE INDEX on (project_id, card_id), so two enrollments are two
        distinct CARDS — two men, or one man with two credentials. Collapsing
        them on a lowercased (name, company) string would delete a worker from
        the roster to fix a duplicate, which is the wrong trade on a document
        that records who was on site.

        test_checkins_today_roster_envelope.py already asserts both men
        survive. This pins the reason on the other side of the fence too, so
        the "make pass 1 match pass 2" change cannot be made without both tests
        failing and the decision being taken again on purpose.
        """
        block = _SRC[_SRC.index("for eid in enrollment_ids:"):]
        block = block[:block.index("result.append(")]
        self.assertNotIn("if name_key in seen_name_keys:", block)
        self.assertIn("seen_name_keys.add(name_key)", block)

    def test_a_blank_company_falls_back_to_the_name(self):
        """The legacy row often has no company at all, and a blank company
        distinguishes nobody — it must not mint a second row."""
        block = _SRC[_SRC.index("seen_legacy_wids: set = set()"):]
        block = block[:2000]
        self.assertIn("not name_key[1] and name_key[0] in seen_names_only", block)

    def test_two_different_men_at_different_subs_stay_two_rows(self):
        """The fallback is blank-company ONLY. A legacy row that names a
        company keeps the pair, so the dedupe cannot over-collapse."""
        block = _SRC[_SRC.index("seen_legacy_wids: set = set()"):][:2000]
        self.assertIn("not name_key[1]", block)
        self.assertNotIn("name_key[0] in seen_names_only:", block.replace(
            "not name_key[1] and name_key[0] in seen_names_only", ""))

    def test_the_name_only_index_is_kept_in_step(self):
        self.assertEqual(_SRC.count("seen_names_only.add(name_key[0])"), 3)


class TheAlwaysNAFieldsAreNotPrinted(unittest.TestCase):
    """DEFECT 5 — Time In / Time Out / Areas Visited printed a permanent N/A
    because nothing in the app has ever written them."""

    def test_areas_visited_is_gone_from_the_screen_entirely(self):
        """IT WENT THE WHOLE WAY, LIKE THE TWO TIME FIELDS BEFORE IT.

        This asserted that `setAreasVisited` had exactly ONE call site -- the
        hydrate -- because the deal at the time was that the key kept
        travelling and only the display was suppressed. A sibling test pinned
        the payload key as untouched, with the note "the day a control is
        added the row reappears on its own".

        NO CONTROL WAS EVER ADDED. Measured before the ruling: the key is on
        50 of 59 records and non-empty on 0 of 360 including the deleted ones,
        so "Areas Visited: N/A" printed on every filed daily jobsite log there
        has ever been.

        AND THE FIELD WAS NEVER THE RIGHT ONE. The log does not record where a
        person visited; it records where the WORK is, and the crew rows carry
        that in `work_locations`. So the field was a duplicate of something
        the document already printed, under a label describing a different
        fact -- removed from the screen, the payload and the schema together.

        ASSERTED ON CODE, NOT ON TEXT. The comments above discuss the removal
        by name, and a prose mention of `setAreasVisited` must not keep this
        green or red on its own.
        """
        screen = (_BACKEND / ".." / "frontend" / "app" / "logbooks"
                  / "daily_jobsite.jsx").resolve().read_text(encoding="utf-8")
        code = strip_js(screen)
        for gone in ("areasVisited", "setAreasVisited", "areas_visited:",
                     "d.areas_visited"):
            self.assertNotIn(gone, code,
                             f"{gone} survived the deletion in daily_jobsite.jsx")

    def test_and_the_gate_tablet_stopped_reading_it_too(self):
        """THE READER NOBODY HAD LOOKED AT. `app/site/logbooks.jsx` rendered
        an Areas Visited row guarded on truthiness, so it never once appeared
        -- a second dead reader of the same dead field, found only by censusing
        every occurrence before removing it."""
        viewer = (_BACKEND / ".." / "frontend" / "app" / "site"
                  / "logbooks.jsx").resolve().read_text(encoding="utf-8")
        # ANCHORED, NOT BARE. `assertNotIn` against a string bans a SUBSTRING,
        # so a bare `areas_visited` is satisfied -- or broken -- by anything
        # that happens to contain those characters. The gate caught this one
        # in CI; the form the file actually held is the property read.
        self.assertNotIn("data.areas_visited", strip_js(viewer))

    def test_the_two_time_fields_are_gone_from_the_screen_entirely(self):
        """TIME IN / TIME OUT WENT FURTHER THAN THE ROW.

        This class used to assert that all THREE keys still travelled and only
        the display was suppressed. NOT ANY MORE, FOR ANY OF THEM: the times
        went first and `areas_visited` followed by ruling once the census
        showed no control had ever been added. For the two times: the state,
        the payload keys and the
        hydrate lines are DELETED, because a field with no control is not a
        field the log collects, and the CP's own hours belong to item 1 of the
        superintendent log (`presence.arrived_at` / `presence.departed_at`),
        where they are now chosen from a clock and required before it files.

        ASSERTED ON THE SCREEN, not on the renderer, because the renderer is
        allowed to keep reading them — see the class below."""
        screen = (_BACKEND / ".." / "frontend" / "app" / "logbooks"
                  / "daily_jobsite.jsx").resolve().read_text(encoding="utf-8")
        # Comments discuss the removal by name, so read CODE. A prose mention
        # of `setTimeIn` must not keep this green or red on its own.
        # strip_js, NOT a hand-rolled re.sub. source_text.strip_js is the
        # shared helper, and test_absence_literals_are_specific classifies an
        # assertNotIn by the CALL that produced its haystack -- a local
        # re.sub is opaque to it, so this assertion counted as unclassified
        # and pushed that guard one over its ceiling. Using the convention
        # the classifier already knows is the fix; raising the ceiling is not.
        code = strip_js(screen)
        for gone in ("timeIn", "setTimeIn", "timeOut", "setTimeOut",
                     "time_in:", "time_out:", "d.time_in", "d.time_out"):
            self.assertNotIn(gone, code,
                             f"{gone} survived the deletion in daily_jobsite.jsx")

    def test_the_report_prints_them_only_when_set(self):
        """THE PERMANENT "N/A" IS STILL BANNED, on the renderer that remains.

        This asserted the report's conditional block, which is gone with the
        report's copy of the daily log. The defect it guards -- `Time In: N/A`
        on every filed log ever rendered, for two keys nothing ever wrote --
        is banned from the whole file by the source assertion in this same
        class, and the legal renderer still prints the row only when the
        record carries a time.
        """
        self.assertIn("_times_line", _SINGLE)
        self.assertNotIn('data.get("time_in") or "N/A"', _SINGLE)

    def test_BOTH_renderers_print_the_times_only_when_set(self):
        """THE PAIR, ASKED THE SAME QUESTION.

        generate_single_logbook_html printed `Time In: N/A   Time Out: N/A`
        UNCONDITIONALLY on every daily jobsite log ever rendered, while the
        combined report already suppressed the row. With nothing left in the
        app that writes those keys, the single document would have carried a
        permanent N/A forever.

        SUPPRESSED, NOT DELETED, and the reason is the same one that governs
        every other decision on a filed record: a log filed before the U1
        rebuild may carry real times, and removing the row outright would
        change what an already-signed document shows. So both renderers now
        apply one rule — print it when a value is there, print nothing when it
        is not — which is what TheTwoRenderersAgreeOnAnEmptyRow below is about.
        """
        self.assertIn("_t_in = str(data.get(\"time_in\") or \"\").strip()", _SINGLE)
        self.assertIn("if (_t_in or _t_out) else \"\"", _SINGLE)
        # code_of(), NOT the module-level _SINGLE slice. _SINGLE is bound by
        # `_SRC[a:b]`, and test_absence_literals_are_specific classifies an
        # assertNotIn by the call that produced its haystack: it proves "a
        # slice of a string is a string" for a haystack expression but not for
        # a NAME bound to one, so these two counted as unclassified and pushed
        # that guard one over its ceiling. code_of is already in its
        # _STRING_CALLS. Scoping is not lost: this form must exist in NEITHER
        # renderer, so asserting it is absent from the file is the stronger claim.
        _single_src = code_of("server.py")
        self.assertNotIn('data.get("time_in") or "N/A"', _single_src)
        self.assertNotIn('data.get("time_out") or "N/A"', _single_src)

    def test_the_conditional_block_behaves(self):
        """Asserted on the RENDERED document — see TheRenderedDocument below,
        which builds a report from a stored payload and reads the HTML."""
        html = _render_documents(_DAY_WITH_DUPLICATE)
        self.assertNotIn("Time In:", html)
        # `Areas Visited:` IS NOT ASSERTED ABSENT HERE, and the difference is
        # real rather than an oversight. The report printed that row only when
        # the key was set; the filed log prints the label unconditionally and
        # says "not recorded" beside it, which is this product's rule for a
        # field that is on the form and was left empty. The permanent "N/A"
        # that this class exists to prevent is banned from both renderers by
        # the source assertion above.
        # `areas_visited` IS GONE FROM THE PRODUCT, not merely unprinted.
        # Carried on 50 of 59 records and non-empty on none of 360 including
        # the deleted ones, it printed "Areas Visited: N/A" on every filed
        # daily log ever rendered. Removed from the screen, the payload and
        # the schema together by operator ruling, so there is nothing left
        # here to assert -- the log records where the WORK is, and the crew
        # rows carry that.
        html2 = _render_documents(_DAY_WITH_DUPLICATE, jobsite_extra={
            "time_in": "07:00", "time_out": "15:30",
        })
        self.assertIn("Time In", html2)
        self.assertIn("07:00", html2)
        self.assertNotIn("Areas Visited", html2)


class TheTwoHeadcountsAreLabelled(unittest.TestCase):
    """DEFECT 6 — page 1 counts the gate, the activity row is the CP's own
    hand-typed number. Both true, about different things. Labelled, not
    reconciled."""

    def test_the_activity_table_says_whose_count_it_is(self):
        """ONE RENDERER PRINTS THE CREW TABLE NOW. The report has no crew
        table; it has an activity row that prints BOTH numbers and names each,
        which is the same rule stated more plainly."""
        self.assertIn("CP&#39;s count", _SINGLE)
        self.assertIn("on daily log", _RENDER_SRC)
        self.assertIn("gate check-ins", _RENDER_SRC)

    def test_the_crew_table_never_calls_it_just_Workers(self):
        i = _SINGLE.find("<th {TH}>Crew</th>")
        self.assertNotEqual(i, -1)
        self.assertNotIn("Workers", _SINGLE[i:i + 200])

    def test_page1_still_names_its_own_source(self):
        """THE LABEL SURVIVED THE REDESIGN AND GOT SHARPER.

        The cover said "Workers checked in at the gate" so its number could
        not be read as the conducting party's crew count. The new rail says
        GATE CHECK-INS and the workforce strip says GATE WORKFORCE -- the same
        guard against the same confusion, in fewer words, and now beside a row
        that prints BOTH numbers when they differ.
        """
        self.assertIn("Gate check-ins", _RENDER_SRC)
        self.assertIn("Gate workforce", _RENDER_SRC)

    def test_the_two_numbers_are_NOT_reconciled(self):
        """No arithmetic between them anywhere — they are different facts."""
        self.assertNotIn("num_workers) - ", _REPORT)
        self.assertNotIn("_sub_total - ", _REPORT)


class TheTwoRenderersAgreeOnAnEmptyRow(unittest.TestCase):
    """THE DIVERGENCE, closed. generate_single_logbook_html dropped a seed row;
    generate_combined_report printed it. Same stored register, two documents,
    and the combined one is what the operator emails.

    This pair has drifted TWICE before — weather, then drawings_on_site — so
    the fix is not a matching copy of the rule but the SAME rule: both now
    resolve through _SUBMIT_ROW_CONTENT_RULES, which #125 already enforces at
    submit."""

    def test_the_combined_report_skips_the_seed(self):
        # THE SEED GUARD IS THE DOCUMENT'S. Same rule, same shared
        # submit-time constant, read off the renderer that still prints the
        # register.
        # THE RULE, NOT THE SPELLING. The register drops an entry that
        # names nobody -- a certification belonging to no named worker -- and
        # the legal renderer states it as a `worker_name` guard rather than by
        # naming the shared submit-time constant. The claim is that the guard
        # EXISTS and gates the row, which is what is asserted.
        block = _SINGLE[_SINGLE.index('log_type == "osha_log"'):]
        block = block[:block.index("osha_rows +=")]
        self.assertIn("worker_name", block)
        self.assertIn("continue", block)

    @unittest.skip(
        "DELETED BY THE REPLACEMENT. The rule was that the REPORT's copy of "
        "the OSHA guard must reference the shared submit-time constant rather "
        "than retype its field list -- it had drifted twice. There is no "
        "report copy now: the register is printed by one renderer, which "
        "states the guard directly, and a third copy cannot exist because "
        "there is no second. The sibling test above asserts the guard itself. "
        "See docs/audits/report-replacement-ledger.md.")
    def test_it_does_not_write_a_THIRD_copy_of_the_rule(self):
        """A hand-typed field list here is how it drifts a third time."""
        # ONLY THE GUARD, not the row builder below it — that legitimately
        # names these fields in order to PRINT them.
        # The end anchor moved when the Review decision was extracted into
        # osha_review_cell: the guard is now followed by the call, not by the
        # inline `wid = ...` that used to open the branch. The CLAIM is
        # unchanged -- this region must reference the shared rule, never retype
        # its field list.
        guard = _SINGLE[_SINGLE.index('log_type == "osha_log"'):]
        guard = guard[:guard.index("osha_rows +=")]
        for f in ("worker_name", "certification_type", "card_number", "expiration"):
            self.assertNotIn(f'"{f}"', guard,
                             "the field list is re-typed instead of referenced")
        # And the rule it references is the one #125 enforces at submit.
        self.assertIn("worker_name", str(server._SUBMIT_ROW_CONTENT_RULES["osha_log"][1]))

    def test_both_renderers_now_drop_the_same_row(self):
        """Executed on the real document: a register of one seed row renders no
        certification row at all."""
        seed = {"worker_id": None, "worker_name": "", "company": "",
                "certification_type": "", "card_number": "", "expiration": "",
                "signed": False, "date": "2026-08-14"}
        day = {
            **_DAY_WITH_DUPLICATE,
            "osha": {"_id": "lb_osha", "log_type": "osha_log",
                     "date": "2026-08-12", "data": {"entries": [seed]}},
        }
        html = _render_documents_with_osha(day)
        self.assertIn("OSHA / SST Certification Log", html)
        # THE REGISTER PRINTS NO ROW, and on this renderer no table either. The
        # report said "No certifications recorded" in a spanning cell; the
        # filed document omits the table. Both drop the row, which is the rule
        # this test is named for -- so it is asserted as the absence of the
        # header the table would have carried, not as a phrase one renderer
        # happened to use.
        self.assertNotIn("Card #", html)

    def test_a_real_row_still_prints(self):
        real = {"worker_id": "w1", "worker_name": "WILMER CARRILLO",
                "company": "AAZ", "certification_type": "SST Supervisor",
                "card_number": "4YU1RY8KKM", "expiration": "2030-04-01",
                "signed": True, "date": "2026-08-12"}
        html = _render_documents_with_osha({**_DAY_WITH_DUPLICATE,
                                  "osha": {"_id": "lb_osha", "log_type": "osha_log",
                                           "date": "2026-08-12",
                                           "data": {"entries": [real]}}})
        self.assertIn("4YU1RY8KKM", html)
        # Reworded by finding 5: the register prints the class name the card
        # prints. No hours here -- this row joins to no live cert, so nothing
        # says colour determined the class.
        self.assertIn("SST Supervisor", html)


class TheAISentenceStillHasItsFallback(unittest.TestCase):
    """DEFECT 2 — the placeholder rendered instead of the generated line. The
    wiring is intact; what was missing was any way to tell WHY."""

    @unittest.skip(
        "DELETED BY THE REPLACEMENT, and the reason is a product fact worth "
        "reading: the per-subcontractor sentence generator is NOT WIRED to "
        "the new page. `lib.ai.sub_summary` verifies a sentence about one "
        "subcontractor; the executive summary is a paragraph, which is a "
        "different surface with a different failure mode. Standing one up "
        "quietly would put unverified prose on a document a lender relies "
        "on, so the page ships the deterministic fallback and the generator "
        "hook is left open. See docs/audits/report-replacement-ledger.md.")
    def test_the_wiring_is_still_there(self):
        # RE-POINTED, not dropped. The report now calls the TRACED variant so
        # it can name which of the four outcomes each row took; the sentence
        # half of the contract is unchanged.
        self.assertIn("from lib.ai.sub_summary import generate_sentence_traced", _REPORT)
        self.assertIn("_gen, _outcome = _gen_sub_sentence(_payload)", _REPORT)
        self.assertIn("_line = _sentence_case(_html.escape(_gen)) if _gen else _facts", _REPORT)

    def test_all_three_outcomes_now_leave_a_trace(self):
        """A missing key was the only one of the three that returned None in
        silence, so a report of plain facts was unreadable as evidence."""
        mod = (_BACKEND / "lib" / "ai" / "sub_summary.py").read_text(encoding="utf-8")
        # The one implementation is now generate_sentence_traced; the plain
        # generate_sentence is a thin wrapper over it, so the branches to check
        # are here.
        gen = mod[mod.index("def generate_sentence_traced("):]
        no_key = gen[:gen.index("try:")]
        self.assertIn("logger.warning", no_key)
        self.assertIn("GEMINI_API_KEY is not set", no_key)
        self.assertIn("logger.error", gen)   # the call failed
        self.assertIn("logger.info", gen)    # the sentence was refused


if __name__ == "__main__":
    unittest.main()


class TestAttendeeProvenanceIsPrinted(unittest.TestCase):
    """WHOSE CLAIM PUT EACH MAN ON THE SHEET — device round 4, ruling C.

    A toolbox talk is a WEEKLY obligation built from a DAILY roster, so the CP
    can now add men who worked earlier in the week. That is a genuinely weaker
    claim than a gate check-in: the gate SAW the first man, and the CP is
    ASSERTING the second. Recording the difference in the payload and then
    printing every row identically would defeat the reason for recording it —
    the stronger claim lending its authority to the weaker, on a signed record
    an inspector reads.

    Rendered, not grepped: this calls the real generate_combined_report.
    """

    def _html(self):
        day = {k: dict(v) for k, v in _DAY_WITH_DUPLICATE.items()}
        day["toolbox"] = {
            **day["toolbox"],
            "data": {"checked_topics": {}, "attendees": [
                {"name": "Gate Man", "company": "AAZ", "added_from": "gate"},
                {"name": "Week Man", "company": "AAZ", "added_from": "weekly_gap"},
                {"name": "Typed Man", "company": "AAZ", "added_from": "manual"},
                {"name": "Legacy Man", "company": "AAZ"},   # filed before the field
            ]},
        }
        return _render_documents(day)

    def test_the_column_exists(self):
        self.assertIn("Added by", self._html())

    def test_the_three_claims_render_differently(self):
        html = self._html()
        for label in ("Gate", "CP &mdash; this week", "CP &mdash; added"):
            self.assertIn(label, html, f"{label} is missing from the sheet")

    def test_a_cp_assertion_is_never_printed_as_a_gate_check_in(self):
        """The one substitution that would matter."""
        html = self._html()
        week_row = html[html.index("Week Man"):]
        week_row = week_row[:week_row.index("</tr>")]
        self.assertIn("this week", week_row)
        self.assertNotIn(">Gate<", week_row)

    def test_an_old_record_is_not_given_a_label_it_never_earned(self):
        """Every attendee filed before `added_from` existed came from the gate
        or from the CP's typing with no way to tell which. An em-dash says we
        do not know; anything else is a guess printed onto a legal record."""
        html = self._html()
        legacy = html[html.index("Legacy Man"):]
        legacy = legacy[:legacy.index("</tr>")]
        self.assertNotIn("Gate", legacy)
        self.assertNotIn("CP ", legacy)
        self.assertIn("&mdash;", legacy)

    def test_the_table_is_not_left_one_column_short(self):
        """A header row wider than its empty-state placeholder renders a
        ragged table on the one document nobody re-renders."""
        # NARROWED once (it was a global ban on colspan 6, which the pre-shift
        # sheet then legitimately needed), and now COMPUTED rather than pinned.
        #
        # It asserted the literal `colspan="7"`, which made it a test about the
        # NUMBER SEVEN and not about the invariant. Dropping the Confirmed and
        # Present columns is a correct change that left the placeholder and the
        # header agreeing at five, and this failed on it -- while the ragged
        # table it exists to catch is any header/placeholder MISMATCH, at any
        # width. So it counts both sides and compares them.
        # READ OFF THE DOCUMENT. The ragged-table invariant is about the
        # toolbox talk's own header and placeholder, which the legal renderer
        # prints; the report used to embed it.
        _tb = _SINGLE[_SINGLE.index('log_type == "toolbox_talk"'):]
        _tb = _tb[:_tb.index('elif log_type ==', 40)]
        header = next(l for l in _tb.splitlines() if "{TH}>Name</th>" in l)
        columns = header.count("<th {TH}>")
        self.assertGreater(columns, 0, header)
        self.assertIn(f'colspan="{columns}"', _tb,
                      f"the header carries {columns} columns; the empty-state "
                      f"placeholder does not span them")


class TestGroupThreeRendering(unittest.TestCase):
    """Device round 4, group 3 — the two halves that live in the renderer."""

    def _html(self, jobsite_data):
        day = {k: dict(v) for k, v in _DAY_WITH_DUPLICATE.items()}
        day["jobsite"] = {**day["jobsite"],
                          "data": {**day["jobsite"]["data"], **jobsite_data}}
        return _render_documents(day)

    # ── 14. AN EMPTY DESCRIPTION IS NOT A BLANK LABEL ────────────────────────
    def test_an_empty_description_says_it_was_not_recorded(self):
        """`data.get("general_description", "N/A")` returns "" for a stored
        empty string — the default only fires when the KEY is absent. So a log
        whose description was never written printed `Description:` with nothing
        after it: a labelled void on a filed 3301-02, which reads as a document
        that lost something rather than one that recorded nothing.

        The description only lands when the CP has been on the review step to
        see it — deliberately, since he is attesting to that sentence — so an
        empty one is a NORMAL state and the document has to be able to say so.
        """
        # THE DAILY LOG RENDERS THROUGH THE ENGINE NOW, so the sheet states
        # the same facts in the sheet's own shape: a label and its value in
        # two cells rather than "Label: value" in one line of prose. The CLAIM
        # is unchanged and is what is asserted; the punctuation of the old
        # branch is not the claim.
        html = self._html({"general_description": ""})
        i = html.index("Description")
        self.assertIn("Not recorded", html[i:i + 300])

    def test_BOTH_renderers_stopped_defaulting_to_a_key_that_is_present(self):
        """The single-log PDF and the combined report each print this line, and
        only one of them is reachable from _render. `.get(key, "N/A")` returns
        "" for a stored empty string — the default fires only when the KEY is
        ABSENT, which it never is once the screen has saved once. So the
        fallback that looked like it was there was doing nothing in both.
        """
        # ONE RENDERER PRINTS THIS LINE NOW. The ban on the useless default
        # is asserted across the WHOLE file, so a second copy reappearing
        # anywhere fails; the positive half is read off the renderer that
        # prints it.
        self.assertNotIn('general_description", "N/A"', _SRC)
        self.assertIn('general_description") or NOT_RECORDED', _SINGLE)

    def test_a_written_description_is_untouched(self):
        # THE DAILY LOG RENDERS THROUGH THE ENGINE NOW, so the sheet states
        # the same facts in the sheet's own shape: a label and its value in
        # two cells rather than "Label: value" in one line of prose. The CLAIM
        # is unchanged and is what is asserted; the punctuation of the old
        # branch is not the claim.
        html = self._html({"general_description": "Rebar and formwork on L4"})
        self.assertIn("Rebar and formwork on L4", html)
        i = html.index("Description")
        self.assertNotIn("Not recorded", html[i:i + 300])

    # ── 13. "OTHER" IS NOT A PASS/FAIL ITEM ──────────────────────────────────
    def test_other_prints_what_was_inspected_not_a_verdict(self):
        """The other eight name a specific thing, so pass and fail say
        something about it. "Other" names nothing — a green "Passed: Other" on
        a DOB document asserts an unnamed inspection was fine, a claim with no
        subject."""
        html = self._html({"checklist_items": {
            "fall_protections": {"result": "pass", "note": ""},
            "other_checklist": {"result": None, "note": "hoist gate latch"},
        }})
        # THE INSPECTION REGISTER IS A TABLE NOW -- item, result, note in
        # three cells -- so the note and its row label are no longer one
        # string. Every part of the claim is still asserted, and the last one
        # is the one that matters: "Other" gets no verdict of its own.
        self.assertIn("hoist gate latch", html)
        self.assertIn("Also inspected", html)
        self.assertIn("Fall Protections", html)
        self.assertIn("Passed", html)
        self.assertNotIn("Passed: Other", html)
        # It must not be listed as unwalked either — it WAS inspected.
        i = html.index("Also inspected")
        self.assertNotIn("Not inspected", html[i:i + 200])

    def test_an_empty_other_prints_nothing_at_all(self):
        """Nothing typed is nothing to report — not an unwalked item, because
        "Other" is not an item anybody walks."""
        html = self._html({"checklist_items": {
            "fall_protections": {"result": "pass", "note": ""},
            "other_checklist": {"result": None, "note": ""},
        }})
        self.assertNotIn("Also inspected", html)
        self.assertNotIn("Not inspected: Other", html)

    def test_a_pass_fail_STORED_ON_OTHER_still_renders(self):
        """An already-filed document does not change because the app later
        learned to record something better. A log filed while Other carried a
        verdict keeps printing that verdict."""
        html = self._html({"checklist_items": {
            "other_checklist": {"result": "fail", "note": "gate left open"},
        }})
        self.assertIn("FAILED", html)
        self.assertIn("gate left open", html)

    def test_the_note_is_escaped(self):
        html = self._html({"checklist_items": {
            "other_checklist": {"result": None, "note": "<script>x</script>"},
        }})
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class TestAmendmentSupersedesOnceSigned(unittest.TestCase):
    """DEVICE ROUND 5, FINDING 19 — the report half.

    `amend_logbook` creates the amendment as a SECOND document sharing
    (project_id, log_type, date). The renderer picked each type with
    `next((l for l in logbooks if ...))` over a query with NO sort, so it
    resolved to whatever Mongo returned first — insertion order, i.e. the
    original. Once a log was amended the correction was invisible on the one
    document that goes to investors and lenders.

    THE RULING: the latest SIGNED record. An unsigned amendment is not a
    correction, it is an intention to correct.
    """

    def _day(self, toolbox_docs):
        """THE DOCUMENT THE INDEX POINTS AT, which is the whole ruling now.

        The report used to embed the toolbox talk, so "the correction is
        invisible on the report" meant the wrong text was printed on it. The
        report carries an index of cards instead, and each card links to the
        document `_filed_log` selects -- so the selection now decides which
        document the reader OPENS, and printing the superseded one is the same
        defect one click further along.

        The rendered report is checked too, below, for the card itself.
        """
        day = {k: dict(v) for k, v in _DAY_WITH_DUPLICATE.items()}
        db = _Db(
            projects=_Coll(one={"_id": "p1", "name": "8 Walworth St",
                                "address": "8 Walworth St",
                                "project_class": "regular"}),
            logbooks=_Coll(docs=[day["preshift"], day["jobsite"], *toolbox_docs]),
            daily_logs=_Coll(one=None),
            checkins=_Coll(docs=[]),
        )
        with patch.object(server, "db", db):
            _chosen = server._filed_log(
                [day["preshift"], day["jobsite"], *toolbox_docs], "toolbox_talk")
            if not _chosen:
                # A day with no filed toolbox talk renders no toolbox document.
                # The report still renders, and a case about it says so itself.
                return asyncio.run(
                    server.generate_combined_report("p1", "2026-08-12"))
            return asyncio.run(server.generate_single_logbook_html(_chosen))

    def _tb(self, _id, *, text, locked, status, created):
        return {
            "_id": _id, "log_type": "toolbox_talk", "date": "2026-08-12",
            "is_locked": locked, "status": status,
            "created_at": datetime(2026, 8, 12, created, tzinfo=timezone.utc),
            "data": {"checked_topics": {}, "location": text,
                     "attendees": [{"name": "Gate Man", "added_from": "gate"}]},
        }

    def test_an_UNSIGNED_amendment_does_not_replace_the_signed_original(self):
        """The case that decided the ruling: a CP taps Amend at 4pm and has not
        finished. Nothing has been corrected yet, and the report must not assert
        that it has."""
        original = self._tb("orig", text="ORIGINAL", locked=True, status="submitted", created=9)
        child = self._tb("child", text="AMENDMENT", locked=False, status="draft", created=16)
        html = self._day([original, child])
        self.assertIn("ORIGINAL", html)
        self.assertNotIn("AMENDMENT", html)

    def test_a_SIGNED_amendment_supersedes_and_the_original_never_returns(self):
        original = self._tb("orig", text="ORIGINAL", locked=True, status="submitted", created=9)
        child = self._tb("child", text="AMENDMENT", locked=True, status="submitted", created=16)
        html = self._day([original, child])
        self.assertIn("AMENDMENT", html)
        self.assertNotIn("ORIGINAL", html)

    def test_insertion_order_does_not_decide_it(self):
        """The whole defect in one assertion: the query has no sort, so the
        renderer must not depend on which document comes back first."""
        original = self._tb("orig", text="ORIGINAL", locked=True, status="submitted", created=9)
        child = self._tb("child", text="AMENDMENT", locked=True, status="submitted", created=16)
        self.assertIn("AMENDMENT", self._day([original, child]))
        self.assertIn("AMENDMENT", self._day([child, original]))

    def test_a_day_with_only_an_unfiled_draft_still_renders_it(self):
        """Unchanged behaviour: nothing filed falls back to the first match
        rather than blanking the section."""
        draft = self._tb("d1", text="ONLY DRAFT", locked=False, status="draft", created=9)
        self.assertIn("ONLY DRAFT", self._day([draft]))

    def test_every_call_site_goes_through_the_resolver(self):
        """Ten hand-written picks is how this pair drifted twice. One resolver,
        and no `next(...)` survives to drift again."""
        # ELEVEN, not ten: the compliance line on page 1 now resolves the
        # project's REQUIRED set through the same resolver the sections below
        # print from (device round 6, item 3), so it cannot call a log missing
        # that page 2 goes on to render. That is one more call site and one
        # fewer place to drift.
        # TWELVE: the fall-protection section joined, and it resolves its
        # document through the same one resolver as every other section.
        # THIRTEEN since the superintendent log (BC 3301.13.13) gained its
        # own section. The count is the claim: EVERY section resolves its
        # document through _filed_log, so none can quietly reach past the
        # amendment resolver and render a superseded original.
        # 13 -> 14: the investor cover's SAFETY STATUS tile reads the
        # superintendent's log through the same resolver, so a tile and a
        # section cannot disagree about which link of an amended chain is the
        # record. The count moves with a reason rather than being lowered.
        # THE CLAIM IS THAT NOTHING PICKS A DOCUMENT BY HAND, and it was
        # expressed as a count of thirteen sections. There are no sections;
        # the report resolves the daily log, the superintendent log, the
        # pre-shift sheet and one per record card, all through the same
        # resolver. Counting them again would be re-pinning an implementation
        # detail, so the claim is asserted directly: every pick goes through
        # `_filed_log`, and no hand-written `next(...)` over `logbooks`
        # survives to drift a third time.
        self.assertGreater(_REPORT.count("_filed_log("), 0)
        self.assertNotIn("next((l for l in logbooks", _REPORT)
        self.assertNotIn("next(l for l in logbooks", _REPORT)
        self.assertNotIn('next((l for l in logbooks', _REPORT)


# DELETED: TestAiOutcomeIsVisibleToTheAdminOnly
#   the admin-only AI trace was a block on the old page 1. The new page carries no trace, `diagnostics` is accepted and unused, and a test in test_report_renderer.py pins that it changes nothing.
#   See docs/audits/report-replacement-ledger.md.

# DELETED: TestPageOneReadsLikeSomethingSentToALender
#   crew-trade disambiguation and the old type scale. The new page 1 has one row per activity keyed on company, and the five reconciliation states carry what the crew labels used to.
#   See docs/audits/report-replacement-ledger.md.