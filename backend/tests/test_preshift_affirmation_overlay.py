"""The pre-shift sheet stops contradicting the gate log.

On 2026-08-28 a filed sheet printed NOT AFFIRMED against all sixteen workers.
Six of them had affirmed, with timestamps between 10:36 and 11:57, stored
correctly on their check-in rows.

IT WAS NOT STALENESS. `preshift_signin.jsx` builds each worker row from the
gate roster — name, company, osha_number, signin_id, worker_signature,
had_injury, inspected_ppe — and never writes an affirmation field at all;
`signature_affirmed` appears nowhere in that screen. So the signature column
read a key absent from every row of every filed sheet, and printed NOT AFFIRMED
for every worker on every sheet ever filed, whatever anyone did at the gate.

The same family as the rest of this session: a read of a field nothing writes.
#290's sweep does not catch it, because that scans Mongo query filters and this
is a `.get()` on a stored sub-document.

THE OVERLAY IS SCOPED TO ONE FIELD, and that is the whole safety of it. The
affirmation is resolved from the day's check-ins at render time; NAMES, INJURY
ANSWERS, PPE ANSWERS, COMPANY, OSHA NUMBER AND THE SIGNATURE IMAGE ITSELF still
come from the stored document and cannot change after filing. The tests below
assert that directly, because a rendered document that can drift from its
stored copy is the shape this repo has been bitten by.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _code_only(fn) -> str:
    """A function's CODE, with its docstring and comments removed.

    Three assertions in this session were written as text searches over
    `inspect.getsource` and matched the very prose that explains the thing they
    forbid — each time turning a correct implementation into a red test.
    `ast.unparse` drops comments; the docstring is dropped explicitly. What is
    left is only what runs.
    """
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)):
        node.body = node.body[1:]
    return ast.unparse(node)


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


def _db(rows):
    db = MagicMock()
    db.checkins = MagicMock()
    db.checkins.find = MagicMock(return_value=_Cursor(rows))
    return db


AFFIRMED_AT = datetime(2026, 8, 28, 15, 13, 12, tzinfo=timezone.utc)  # 11:13 ET

# A row as the filed sheet actually stores it: no affirmation field anywhere.
STORED = {
    "worker_id": "w1",
    "name": "Cristian B Rojas",
    "company": "Arkon Builders",
    "osha_number": "JH447TBBXG",
    "worker_signature": "iVBORw0KGgo=",
    "had_injury": "No",
    "inspected_ppe": "Yes",
}


class TheOverlayResolvesTheAffirmation(unittest.TestCase):
    def test_a_worker_who_affirmed_prints_affirmed_with_the_time(self):
        overlay = {"w1": {"affirmed": True, "at": AFFIRMED_AT}}
        cell = server._preshift_signature_cell(STORED, overlay)
        self.assertIn("Affirmed 11:13", cell)
        self.assertIn("<img", cell)

    def test_the_time_is_eastern_not_utc(self):
        """15:13 UTC is 11:13 in New York. A sheet printing 15:13 against a
        gate log reading 11:13 invites the reader to conclude the document is
        wrong about something else."""
        overlay = {"w1": {"affirmed": True, "at": AFFIRMED_AT}}
        cell = server._preshift_signature_cell(STORED, overlay)
        self.assertIn("11:13", cell)
        self.assertNotIn("15:13", cell)

    def test_a_worker_who_did_not_affirm_still_says_so(self):
        cell = server._preshift_signature_cell(STORED, {})
        self.assertIn("NOT AFFIRMED", cell)

    def test_no_signature_on_file_still_outranks_everything(self):
        """A different fact from not affirming, and the document says which."""
        row = {k: v for k, v in STORED.items() if k != "worker_signature"}
        cell = server._preshift_signature_cell(row, {"w1": {"affirmed": True, "at": AFFIRMED_AT}})
        self.assertIn("NO SIGNATURE ON FILE", cell)

    def test_an_affirmation_with_no_timestamp_still_prints_affirmed(self):
        cell = server._preshift_signature_cell(STORED, {"w1": {"affirmed": True, "at": None}})
        self.assertIn("Affirmed", cell)
        self.assertNotIn("NOT AFFIRMED", cell)

    def test_a_stored_affirmation_would_still_be_honoured(self):
        """Belt and braces: if a future sheet ever does persist the field, the
        overlay must not be the only way to be affirmed."""
        row = dict(STORED, signature_affirmed=True)
        cell = server._preshift_signature_cell(row, {})
        self.assertNotIn("NOT AFFIRMED", cell)

    def test_the_overlay_is_keyed_on_worker_id_never_on_name(self):
        """Two men can share a name on one jobsite. Nothing here matches on
        one."""
        overlay = {"Cristian B Rojas": {"affirmed": True, "at": AFFIRMED_AT}}
        self.assertIn("NOT AFFIRMED",
                      server._preshift_signature_cell(STORED, overlay))


class NothingElseCanChangeAfterFiling(unittest.TestCase):
    """The whole safety of this change, asserted rather than described."""

    def test_the_cell_reads_only_the_signature_and_the_affirmation(self):
        """It is handed the stored row and the overlay; it must not reach for
        a name, an injury answer or a PPE answer from anywhere."""
        code = _code_only(server._preshift_signature_cell)
        for frozen in ("name", "had_injury", "inspected_ppe", "company", "osha_number"):
            self.assertNotIn(f"'{frozen}'", code,
                             f"the signature cell reads {frozen} — it must not")

    def test_the_overlay_query_returns_only_affirmation_fields(self):
        """A projection wide enough to carry a name is a projection somebody
        will later render."""
        code = _code_only(server.preshift_affirmations)
        self.assertIn("'worker_id': 1", code)
        self.assertIn("'signature_affirmed_at': 1", code)
        for leaked in ("worker_name", "had_injury", "inspected_ppe"):
            self.assertNotIn(leaked, code)

    def test_the_renderers_still_read_every_other_cell_from_the_stored_row(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        for cell in ('w.get("name", "")', 'w.get("had_injury")',
                     'w.get("inspected_ppe")', 'w.get("osha_number", "")'):
            self.assertIn(cell, src, f"{cell} no longer comes from the stored row")

    def test_nothing_writes_to_the_filed_log(self):
        """Do not touch the stored document; do not write into a locked log.
        preshift_signin is an IMMEDIATE type — it freezes on submit."""
        code = _code_only(server.preshift_affirmations)
        for write in ("update_one", "insert_one", "update_many", "$set"):
            self.assertNotIn(write, code)


class TheResolver(unittest.TestCase):
    def test_it_reads_the_days_checkins_for_that_project(self):
        db = _db([{"worker_id": "w1", "signature_affirmed": True,
                   "signature_affirmed_at": AFFIRMED_AT}])
        out = _run(server.preshift_affirmations(db, "proj1", "2026-08-28"))
        self.assertEqual(out["w1"]["affirmed"], True)
        query = db.checkins.find.call_args[0][0]
        self.assertEqual(query["project_id"], "proj1")
        self.assertEqual(query["signature_affirmed"], True)
        self.assertIn("check_in_time", query)

    def test_it_is_resolved_against_the_sheets_date_not_the_filing_time(self):
        """Six men affirmed between 10:36 and 11:57 on a sheet filed before
        10:36. The date is the scope; the moment of filing is not."""
        db = _db([])
        _run(server.preshift_affirmations(db, "proj1", "2026-08-28"))
        clause = db.checkins.find.call_args[0][0]["check_in_time"]
        self.assertIn("$gte", clause)
        self.assertIn("$lt", clause)

    def test_a_failed_read_returns_an_empty_overlay_not_a_refusal(self):
        """It must never turn a read failure into a finding against a worker:
        an empty overlay leaves every row exactly as the document has it."""
        db = MagicMock()
        db.checkins = MagicMock()
        db.checkins.find = MagicMock(side_effect=RuntimeError("mongo down"))
        self.assertEqual(_run(server.preshift_affirmations(db, "p", "2026-08-28")), {})

    def test_a_missing_project_or_date_is_empty(self):
        self.assertEqual(_run(server.preshift_affirmations(_db([]), "", "")), {})

    def test_both_renderers_pass_the_overlay(self):
        """One sheet, two renderers. AFFIRMED in one and NOT AFFIRMED in the
        other is worse than wrong in both."""
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("_preshift_signature_cell(w, _affirm)"), 2)
        self.assertNotIn("_preshift_signature_cell(w)</td>", src)


if __name__ == "__main__":
    unittest.main()
