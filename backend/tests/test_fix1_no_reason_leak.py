"""FIX 1 / TASK D — LEAK AUDIT.

Operator rule: persist NOTHING new on the logbook payload. The admitted-with-
warnings state already lives on the check-in row behind
/checkins/{id}/review and /checkins/{id}/assign-trade; copying a reason string
into a signed logbook would create a second, frozen copy that no later review
could ever correct.

So no reason string, sst_status or review_decision may reach ANY rendering of
logbooks.data.workers[]. This file proves it at the two ends that matter:

  1. The SERVER renderers are field-whitelisted, so even a client regression
     that smuggled a reason onto a worker row could not print it. Proven by
     rendering a DELIBERATELY POISONED logbook and asserting the poison is
     absent from the output:
        • generate_single_logbook_html, preshift branch
        • generate_combined_report, PRE-SHIFT SIGN-IN block
        • GET /reports/logbook/{id}/pdf — proven transitively: the endpoint
          renders generate_single_logbook_html's output (server.py:12191)
        • the emailed daily report — same: it renders
          generate_combined_report's output (server.py:21137)

  2. The two CLIENT surfaces that read data.workers[] never reference the flag
     fields at all:
        • frontend/app/site/logbooks.jsx renderPreshiftSignin (kiosk viewer)
        • frontend/app/logbooks/preshift_signin.jsx — the screen that BUILDS
          the payload; its worker rows and its POST body must be clean.

The poison values below are exactly what a leak would look like.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
_FRONTEND = _BACKEND.parent / "frontend"

import server  # noqa: E402


# Every string a leak could put on the page. If any of these renders, the
# reason has escaped component state into the permanent record.
POISON_VALUES = [
    "Expired SST card",
    "Unknown SST card",
    "No trade assigned",
    "EXPIRED_SST",
    "SST_UNKNOWN",
    "sent_home",
    # sst_status's bare VALUE. Without it a leak of w["sst_status"] renders
    # "expired" into the record and this suite passes — a hole in its own
    # purpose, found by mutation-checking the renderers.
    "expired",
    "chk_leaky_id",
]

# A worker row carrying every field the roster UI holds in component state.
POISONED_WORKER = {
    "name": "Bob Builder",
    "company": "Acme Co",
    "osha_number": "OSHA-1",
    "had_injury": "no",
    "inspected_ppe": "yes",
    # ── the poison ──
    "checkin_id": "chk_leaky_id",
    "sst_status": "expired",
    "review_decision": "sent_home",
    "needs_trade_assignment": True,
    "cert_warnings": [{"type": "EXPIRED_SST"}],
    "flag_reason": "Expired SST card",
    "flag_reasons": ["Expired SST card", "No trade assigned"],
    "warning_text": "Unknown SST card",
}

LOGBOOK = {
    "_id": "lb1",
    "project_id": "proj1",
    "date": "2026-03-04",
    "log_type": "preshift_signin",
    "status": "submitted",
    "cp_name": "Carl CP",
    "cp_signature": None,
    "data": {
        "company": "Acme Co",
        "project_location": "1 Test St",
        "total_count": 1,
        "workers": [POISONED_WORKER],
    },
}

PROJECT = {"_id": "proj1", "name": "Test Tower", "address": "1 Test St"}


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return list(self._docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


class _Coll:
    def __init__(self, docs=None, find_one=None):
        self.docs = list(docs or [])
        self._find_one = find_one

    def find(self, query=None, *a, **k):
        return _Cursor(self.docs)

    async def find_one(self, query=None, *a, **k):
        if callable(self._find_one):
            return self._find_one(query)
        return self._find_one

    async def count_documents(self, *a, **k):
        return len(self.docs)


class _Db:
    def __init__(self, **colls):
        self._c = dict(colls)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, _Coll())


def _assert_clean(case, html, where):
    for bad in POISON_VALUES:
        case.assertNotIn(
            bad, html,
            f"{where}: {bad!r} reached the rendered logbook. The reason a "
            f"worker is flagged must never be persisted on data.workers[] "
            f"nor rendered from it — it lives on the check-in row.",
        )
    # The row itself must still render: a renderer that prints nothing would
    # pass the assertions above for the wrong reason.
    case.assertIn("Bob Builder", html, f"{where}: the worker row vanished")


class TestSingleLogbookHtmlDropsFlagState(unittest.TestCase):
    """generate_single_logbook_html — preshift branch. Also covers the logbook
    PDF endpoint, which renders exactly this HTML (server.py:12191)."""

    def test_preshift_branch_renders_no_flag_state(self):
        db = _Db(projects=_Coll(find_one=lambda q: PROJECT))
        with patch.object(server, "db", db), \
                patch.object(server, "to_query_id", lambda v: v):
            html = asyncio.run(server.generate_single_logbook_html(LOGBOOK))
        _assert_clean(self, html, "generate_single_logbook_html")

    def test_pdf_endpoint_renders_that_same_html(self):
        """Pins the transitive claim: if the endpoint stopped delegating to
        generate_single_logbook_html, the test above would no longer cover it."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        block = src.split('@api_router.get("/reports/logbook/{logbook_id}/pdf")')[1]
        block = block.split("@api_router")[0]
        self.assertIn(
            "generate_single_logbook_html(logbook)", block,
            "the logbook PDF endpoint no longer renders "
            "generate_single_logbook_html — the leak proof above stops "
            "covering the PDF path",
        )


class TestCombinedReportDropsFlagState(unittest.TestCase):
    """generate_combined_report — PRE-SHIFT SIGN-IN block. Also covers the
    emailed daily report, which renders exactly this HTML (server.py:21137)."""

    def test_preshift_block_renders_no_flag_state(self):
        db = _Db(
            projects=_Coll(find_one=lambda q: PROJECT),
            logbooks=_Coll([LOGBOOK]),
            daily_logs=_Coll(find_one=lambda q: None),
            checkins=_Coll([]),
        )
        with patch.object(server, "db", db), \
                patch.object(server, "to_query_id", lambda v: v):
            html = asyncio.run(
                server.generate_combined_report("proj1", "2026-03-04"),
            )
        _assert_clean(self, html, "generate_combined_report")

    def test_emailed_report_renders_that_same_html(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertIn(
            "report_html = await generate_combined_report(project_id, today)", src,
            "the daily email no longer renders generate_combined_report — the "
            "leak proof above stops covering the emailed report path",
        )


class TestKioskRendererReadsNoFlagState(unittest.TestCase):
    """frontend/app/site/logbooks.jsx renderPreshiftSignin — the site-device
    viewer. Read-only file; this asserts what it does NOT read."""

    def _fn_source(self):
        src = (_FRONTEND / "app" / "site" / "logbooks.jsx").read_text(encoding="utf-8")
        start = src.index("const renderPreshiftSignin")
        end = src.index("const renderLogContent", start)
        return src[start:end]

    def test_renderer_never_reads_a_flag_field(self):
        body = self._fn_source()
        for field in (
            "sst_status", "review_decision", "cert_warnings", "checkin_id",
            "needs_trade_assignment", "flag_reason", "flag_reasons",
        ):
            self.assertNotIn(
                field, body,
                f"renderPreshiftSignin reads w.{field} — the kiosk would "
                f"print flag state out of the logbook payload",
            )

    def test_renderer_still_reads_the_real_worker_fields(self):
        """Guards against the assertions above passing because the function
        was renamed or gutted."""
        body = self._fn_source()
        for field in ("w.name", "w.company", "w.osha_number", "w.had_injury",
                      "w.inspected_ppe"):
            self.assertIn(field, body, f"{field} disappeared from the kiosk renderer")


class TestPreshiftScreenBuildsACleanPayload(unittest.TestCase):
    """frontend/app/logbooks/preshift_signin.jsx — the screen that POSTs the
    payload. The flag reasons may live in component state; they may not be
    written onto a worker row, because `workers` IS data.workers[]."""

    SRC = None

    @classmethod
    def setUpClass(cls):
        cls.SRC = (
            _FRONTEND / "app" / "logbooks" / "preshift_signin.jsx"
        ).read_text(encoding="utf-8")

    def _block(self, opener, closer):
        start = self.SRC.index(opener)
        end = self.SRC.index(closer, start)
        return self.SRC[start:end]

    def test_worker_rows_are_built_without_any_flag_field(self):
        # Bounded at the setWorkers call so the following function's comments
        # are not mistaken for the row literal.
        body = self._block("const buildWorkerList", "setWorkers(list);")
        for field in (
            "sst_status", "review_decision", "cert_warnings", "checkin_id",
            "needs_trade", "flag_reason", "Expired SST", "Unknown SST",
            "No trade assigned",
        ):
            self.assertNotIn(
                field, body,
                f"buildWorkerList writes {field} onto a worker row — that row "
                f"is posted verbatim as logbook data.workers[]",
            )

    def test_save_payload_holds_only_the_logbook_fields(self):
        body = self._block("const handleSave", "const YesNoToggle")
        self.assertNotIn(
            "flags", body,
            "handleSave references the flag map — the payload must be built "
            "from `workers` alone",
        )
        for field in ("sst_status", "review_decision", "cert_warnings",
                      "checkin_id", "needs_trade"):
            self.assertNotIn(field, body, f"handleSave puts {field} in the payload")
        # The payload's data object is still exactly the four logbook fields.
        self.assertIn("workers,", body)
        self.assertIn("total_count: filledWorkers.length", body)

    def test_flag_state_lives_outside_the_worker_rows(self):
        self.assertIn(
            "const [flags, setFlags] = useState({})", self.SRC,
            "the flag map must be its own state, separate from `workers`",
        )

    def test_no_updateWorker_call_writes_a_flag_field(self):
        """updateWorker(index, field, value) is the ONLY way a worker row is
        mutated. Enumerate every field name it is ever called with."""
        fields = set(re.findall(r"updateWorker\(\s*index,\s*'([a-z_]+)'", self.SRC))
        forbidden = fields & {
            "sst_status", "review_decision", "cert_warnings", "checkin_id",
            "needs_trade", "needs_trade_assignment", "flag_reason",
        }
        self.assertEqual(
            forbidden, set(),
            f"updateWorker writes flag state onto a worker row: {forbidden}",
        )
        # Sanity: the call sites we DO expect are all real logbook fields.
        self.assertTrue(fields <= {
            "name", "company", "osha_number", "had_injury", "inspected_ppe",
        }, f"unexpected worker-row field written: {fields}")


if __name__ == "__main__":
    unittest.main()
