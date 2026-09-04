"""A PLAN ANSWER MUST NOT CITE A DRAWING THAT NO LONGER EXISTS.

THE GAP. `DELETE /projects/{id}/files/{file_id}` deletes the R2 source object
and HARD-deletes the `project_files` row, and touches `document_page_index` not
at all. Production carries 44 such rows across 8 files (measured 2026-09-04),
24 of them still pointing at R2 page images totalling 74.6 MB.

Those rows are not inert. `_retrieve_plan_candidates` searches the index, so
`_handle_plan_query` can name a sheet, offer its image, and tell a
superintendent to "open it in the Levelog app under Plans & Files" — where it
does not exist. A well-formed answer with nothing behind it, which is the same
failure class as an attestation over a roster nobody read.

THIS IS THE READ-SIDE HALF ONLY. It deletes nothing and does not stop new
orphans arriving; the delete endpoint still leaves rows behind. It holds even
if that sweep never runs, which is why it ships first.

WHAT THIS FILE HOLDS
  1. the retriever filters on the LIVE file set, on every path into it
  2. a lookup failure degrades to TODAY'S behaviour, never to "no sheets"
  3. it never raises — the handler is a fire-and-forget task and an exception
     there is silence, not an error message
  4. the omission is SILENT: no "unavailable" result is invented, because a
     result he cannot open is worse than no result
"""

import os
import sys
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from tests.source_text import code_of  # noqa: E402

SRC = code_of("server.py")


class TheRetrieverAsksWhichFilesStillExist(unittest.TestCase):
    def test_the_helper_exists_and_is_awaited_by_the_retriever(self):
        self.assertIn("async def _live_plan_file_ids(", SRC)
        i = SRC.index("async def _retrieve_plan_candidates(")
        body = SRC[i:i + 3000]
        self.assertIn("await _live_plan_file_ids(project_id)", body)

    def test_the_filter_is_on_the_base_filter_so_every_path_inherits_it(self):
        """The sheet-number exact match builds `fq = dict(base_filter)`, and the
        discipline-relaxed retry rebuilds from it too. Putting the constraint
        anywhere else would leave one of those three paths citing a dead file."""
        i = SRC.index("async def _retrieve_plan_candidates(")
        body = SRC[i:i + 3000]
        self.assertIn('base_filter["file_id"] = {"$in": live_ids}', body)
        # The three consumers of base_filter still derive from it.
        self.assertIn("fq = dict(base_filter)", SRC[i:i + 6000])
        self.assertIn("relaxed = {k: v for k, v in base_filter.items()", SRC[i:i + 8000])

    def test_it_reads_only_live_rows(self):
        i = SRC.index("async def _live_plan_file_ids(")
        body = SRC[i:i + 1200]
        self.assertIn('"is_deleted": {"$ne": True}', body)
        self.assertIn('"project_id": project_id', body)
        # Projected — the ids are all it wants, and a plan set is large.
        self.assertIn('{"_id": 1}', body)


class AFailedLookupDegradesToTodaysBehaviour(unittest.TestCase):
    """The three options are: don't filter, filter on nothing, or raise. Only
    the first is acceptable and the other two are actively harmful."""

    def test_it_returns_None_rather_than_an_empty_list(self):
        i = SRC.index("async def _live_plan_file_ids(")
        j = SRC.index("async def _retrieve_plan_candidates(")
        self.assertIn("return None", SRC[i:j])
        # An empty list would read as "every sheet in this project is deleted".
        self.assertNotIn("return []", SRC[i:j])

    def test_it_never_raises(self):
        """`_handle_plan_query` is launched with asyncio.create_task and nothing
        awaits it, so an exception is an unhandled task exception and the man
        who asked gets SILENCE."""
        i = SRC.index("async def _live_plan_file_ids(")
        j = SRC.index("async def _retrieve_plan_candidates(")
        self.assertIn("except Exception", SRC[i:j])
        # A STATEMENT, not the word. `raise` as a bare substring is also inside
        # "raises" and "_raised"; what this bans is a raise statement, which in
        # stripped source is the token at the start of an indented line.
        self.assertNotIn("\n        raise", SRC[i:j])

    def test_None_means_no_filter_at_all(self):
        i = SRC.index("async def _retrieve_plan_candidates(")
        body = SRC[i:i + 3000]
        self.assertIn("if live_ids is not None:", body)

    def test_the_handler_really_is_fire_and_forget(self):
        """The premise of the two assertions above, asserted rather than
        assumed — if this ever becomes awaited, raising becomes viable and the
        rule here should be revisited deliberately."""
        # EVERY call site, not the first match — the first is the `async def`
        # itself, and asserting against that would have passed for the wrong
        # reason if create_task ever appeared above the definition.
        sites = []
        start = 0
        while True:
            i = SRC.find("_handle_plan_query(", start)
            if i < 0:
                break
            start = i + 1
            if SRC[max(0, i - 10):i].rstrip().endswith("async def"):
                continue          # the definition
            sites.append(i)
        self.assertTrue(sites, "no call site for _handle_plan_query found")
        for i in sites:
            self.assertIn("asyncio.create_task(", SRC[max(0, i - 200):i],
                          "a call site that is awaited would make raising viable")


class TheOmissionIsSilent(unittest.TestCase):
    def test_no_unavailable_placeholder_is_invented(self):
        """A result he cannot open is worse than no result: 'no matching sheet'
        sends him to look properly, while 'A-301, unavailable' reads as a system
        fault and invites a retry that cannot succeed."""
        i = SRC.index("async def _retrieve_plan_candidates(")
        # THE CONSTRUCT, not the word: a placeholder result would have to be
        # built from a literal. `.lower()` also defeated the auditor's proof
        # that the haystack was source text, so the assertion went unaudited.
        self.assertNotIn('"unavailable"', SRC[i:i + 4000])
        self.assertNotIn("'unavailable'", SRC[i:i + 4000])

    def test_the_existing_empty_answer_still_covers_it(self):
        """The retriever already answers 'couldn't find a matching sheet' on an
        empty pool, and that sentence is true when the only matches were
        deleted."""
        self.assertIn("Couldn't find a matching sheet", SRC)


if __name__ == "__main__":
    unittest.main(verbosity=2)
