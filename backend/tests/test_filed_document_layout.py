"""TWO RULES RESCUED FROM `test_report_document_layout.py` BEFORE IT WAS DELETED.

That file described the investor report as a document: its sections, its
banners, its columns, its type. All of that is gone -- the report indexes the
filings now and embeds none of them -- and the file went with the design.

THESE TWO CLASSES WERE NEVER ABOUT THE REPORT. They read the per-logbook legal
render, which is untouched by the replacement, and they were only living in
that file because the report used to embed the same builders. Deleting them
with their neighbours would have lost two rules that still hold, on a document
an inspector still asks for by name.

See `docs/audits/report-replacement-ledger.md`, the row for
`test_report_document_layout.py`.
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

DATE = "2026-08-12"
PROJECT = "p1"

_SIG = {"data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
                "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
        "affirmed": True, "affirmedAt": "2026-08-12T12:00:00Z",
        "affirmed_received_at": "2026-08-12T12:00:01Z"}

TOOLBOX = {
    "_id": "lb_tb", "project_id": PROJECT, "date": DATE,
    "log_type": "toolbox_talk", "status": "submitted", "cp_name": "Carl CP",
    "cp_signature": copy.deepcopy(_SIG),
    "data": {
        "location": "8 Walworth St", "performed_by": "Carl CP",
        "checked_topics": {"ppe": True},
        "attendees": [{"name": "Gate Man", "title": "Labourer",
                       "company": "Acme", "time_in": "07:00",
                       "added_from": "gate", "signed": True,
                       "gate_confirmed": True}],
    },
}


class _Cursor:
    def __init__(self, docs): self.docs = docs
    def sort(self, *a, **k): return self
    def limit(self, *a, **k): return self
    async def to_list(self, n=None): return [copy.deepcopy(d) for d in self.docs]


class _Coll:
    def __init__(self, docs=None): self.docs = docs or []
    def find(self, *a, **k): return _Cursor(self.docs)
    def aggregate(self, *a, **k): return _Cursor([])
    async def find_one(self, *a, **k):
        return copy.deepcopy(self.docs[0]) if self.docs else None
    async def count_documents(self, *a, **k): return len(self.docs)


class _DB:
    def __init__(self, logbooks): self.logbooks = _Coll(logbooks)
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return _Coll()


class Base(unittest.TestCase):

    def setUp(self):
        self.db = _DB([copy.deepcopy(TOOLBOX)])
        self._orig = (server.db, server.to_query_id)
        server.db = self.db
        server.to_query_id = lambda x: x

    def tearDown(self):
        server.db, server.to_query_id = self._orig

    def rendered_single(self, logbook):
        return asyncio.run(server.generate_single_logbook_html(logbook))


class TheToolboxRosterHasNoTickColumns(Base):
    """THE ROSTER IS ON THE TOOLBOX TALK, which is where it always was.

    It was read off the investor report because the report embedded the
    document. It indexes it now, so the roster is read off the document: the
    same table, the same builder, one click further along.
    """

    def _rendered_roster(self):
        c = self.rendered_single(copy.deepcopy(TOOLBOX))
        c = c[c.index("Tool Box Talk"):]
        return c[:c.index("</table>", c.index("Added by"))]

    def test_neither_column_is_in_the_header(self):
        head = self._rendered_roster()
        self.assertNotIn(">Confirmed<", head)
        self.assertNotIn(">Present<", head)

    def test_and_no_row_carries_a_tick(self):
        self.assertNotIn("&#10003;", self._rendered_roster())

    def test_the_columns_that_remain(self):
        head = self._rendered_roster()
        for col in (">Name<", ">Title<", ">Company<", ">In<", ">Added by<"):
            self.assertIn(col, head)

    def test_added_by_STAYS_because_provenance_is_the_real_question(self):
        self.assertIn("Gate", self._rendered_roster())

    def test_the_FIELDS_are_untouched_in_storage(self):
        """A rendering change, not a data change. Both flags are still on the
        stored document after a render, and toolboxTalkModel.js still writes
        and defaults them.

        THE RENDER THAT TRIGGERS THIS WAS THE COMBINED REPORT'S and is now the
        document's own, which is the only edit this class needed.
        """
        self.rendered_single(copy.deepcopy(TOOLBOX))
        stored = self.db.logbooks.docs[0]["data"]["attendees"][0]
        self.assertTrue(stored["signed"])
        self.assertTrue(stored["gate_confirmed"])
        model = (_BACKEND.parent / "frontend" / "src" / "utils"
                 / "toolboxTalkModel.js").read_text(encoding="utf-8")
        self.assertIn("gate_confirmed", model)
        self.assertIn("signed", model)


class ItemOneDoesNotPrintTheSignatureAsText(unittest.TestCase):
    """The Construction Superintendent Log printed the signature OBJECT into
    item 1's Record cell.

    superintendentLogModel.js lists `signature` among the presence FIELDS, so
    `_cs_item_body` reached it like any other field and fell through to
    `str(value)`. SignaturePad stores strokes, so a filed BC 3301.13.13 log
    rendered a Python dict repr as the superintendent's record of his own
    presence. A legacy base64 signature is a STRING, so that branch pasted the
    whole blob in as body text instead.

    Found by rendering the document and looking at it. Nothing about the code
    looked wrong.
    """

    def _rendered_item_one(self, signature):
        html = server._superintendent_log_html({
            "date": DATE, "cp_name": "Carl",
            "data": {"presence": {
                "printed_name": "Michael Cespedes",
                "arrived_at": "06:45", "departed_at": "16:30",
                "signature": signature,
            }},
        })
        i = html.index("Superintendent presence")
        return html[i:html.index("</tr>", i)]

    STROKES = {"paths": [[{"x": 1, "y": 2}, {"x": 3, "y": 4}]],
               "signerName": "Michael Cespedes"}

    def test_the_stroke_object_is_not_printed(self):
        cell = self._rendered_item_one(self.STROKES)
        # ANCHORED AS THEY PRINT. `str()` of the stroke dict renders the keys
        # quoted, so the quotes are part of the thing being banned and a
        # legitimate future word "paths" in this cell's prose is not.
        self.assertNotIn("'paths'", cell)
        self.assertNotIn("'x'", cell)

    def test_a_legacy_base64_signature_is_not_printed_either(self):
        """The branch a type check would have missed."""
        cell = self._rendered_item_one("iVBORw0KGgoAAAANSUhEUgAAA" * 40)
        self.assertNotIn("iVBORw0KGgo", cell)

    def test_the_REST_of_item_one_still_renders(self):
        """The control. Skipping the field must not empty the item."""
        cell = self._rendered_item_one(self.STROKES)
        self.assertIn("Michael Cespedes", cell)
        self.assertIn("06:45", cell)
        self.assertIn("16:30", cell)

    def test_and_the_signature_is_STILL_on_the_document(self):
        """It has a renderer of its own at the foot of the same section, which
        is why removing this copy loses nothing.

        AND THE BANNER IS STILL HERE, which is the half the replacement makes
        sharper: the investor report carries no signature and no affirmation at
        all now, while the document an inspector reads carries both.
        """
        html = server._superintendent_log_html({
            "date": DATE, "cp_name": "Carl",
            "data": {"presence": {"printed_name": "Michael Cespedes",
                                  "signature": copy.deepcopy(_SIG)}},
        })
        self.assertIn("Superintendent Signature", html)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("AFFIRMED for this document", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
