"""A PLAN ANSWER MUST NOT CITE A DRAWING THAT NO LONGER EXISTS.

THE GAP. `DELETE /projects/{id}/files/{file_id}` deletes the R2 source object
and HARD-deletes the `project_files` row, and touches `document_page_index` not
at all. Production carries 44 such rows across 8 files (measured 2026-09-04),
24 of them still pointing at R2 page images totalling 74.6 MB.

Those rows are not inert. A search reads the index, so an answer can name a
sheet, offer its image, and tell a superintendent to "open it in the Levelog
app under Plans & Files" -- where it does not exist. A well-formed answer with
nothing behind it, which is the same failure class as an attestation over a
roster nobody read.

THIS IS THE READ-SIDE HALF ONLY. It deletes nothing and does not stop new
orphans arriving; the delete endpoint still leaves rows behind. It holds even
if that sweep never runs, which is why it ships first.

WHERE THE RULE LIVES NOW
========================

`_retrieve_plan_candidates` is deleted with the rest of the matcher. Both
things that read the drawings -- `search_plans`, which answers, and
`_pages_for_records`, which picks the sheet to send -- go through
`_current_record_page_ids`, so the live-file constraint is applied ONCE, in one
place, instead of on three paths into one retriever.

WHAT THIS FILE HOLDS
  1. every read filters on the LIVE file set, through one helper
  2. a lookup failure degrades to TODAY'S behaviour, never to "no sheets"
  3. it never raises -- the image handler is a fire-and-forget task and an
     exception there is silence, not an error message
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


def _body_of(signature: str) -> str:
    """One function's source, from its `def` to the next one at column 0."""
    i = SRC.index(signature)
    j = min((k for k in (SRC.find("\ndef ", i + 1),
                         SRC.find("\nasync def ", i + 1)) if k > 0),
            default=len(SRC))
    return SRC[i:j]


class EveryReadAsksWhichFilesStillExist(unittest.TestCase):

    def test_the_answer_path_filters_through_the_one_helper(self):
        i = SRC.index("async def search_plans(")
        self.assertIn("await _current_record_page_ids(", SRC[i:i + 1200])

    def test_so_does_the_path_that_picks_the_sheet_to_send(self):
        """The picture and the answer come from the same records now, and the
        records were already filtered. What this holds is that the page lookup
        behind them adds no second, unfiltered search of the index."""
        i = SRC.index("async def _pages_for_records(")
        body = SRC[i:i + 1600]
        self.assertIn("document_page_index.find(", body)
        self.assertIn("[to_query_id(p) for p in seen]", body)

    def test_the_helper_applies_both_constraints_in_one_statement(self):
        """A deleted file and a superseded reissue are the same class of dead
        row, and splitting them is how one path kept citing one of them."""
        i = SRC.index("async def _current_record_page_ids(")
        body = SRC[i:i + 1200]
        self.assertIn("await _live_plan_file_ids(", body)
        self.assertIn("**_current_page_filter(live_ids)", body)
        h = SRC.index("def _current_page_filter(")
        self.assertIn('"file_id": {"$in": live_ids}', SRC[h:h + 600])
        self.assertIn('"superseded_by": {"$nin": live_ids}', SRC[h:h + 600])

    def test_the_answering_read_never_touches_the_page_index_itself(self):
        """Any other query against the page index inside search_plans would be
        a path that never learned the rule."""
        i = SRC.index("async def search_plans(")
        j = SRC.index("\nasync def ", i + 10)
        self.assertEqual(SRC[i:j].count("document_page_index.find("), 0)

    def test_it_reads_only_live_rows(self):
        i = SRC.index("async def _live_plan_file_ids(")
        body = SRC[i:i + 1200]
        self.assertIn('"is_deleted": {"$ne": True}', body)
        self.assertIn('"project_id": project_id', body)
        # Projected -- the ids are all it wants, and a plan set is large.
        self.assertIn('{"_id": 1}', body)


class AFailedLookupDegradesToTodaysBehaviour(unittest.TestCase):
    """The three options are: don't filter, filter on nothing, or raise. Only
    the first is acceptable and the other two are actively harmful."""

    def test_it_returns_None_rather_than_an_empty_list(self):
        body = _body_of("async def _live_plan_file_ids(")
        self.assertIn("return None", body)
        # An empty list would read as "every sheet in this project is deleted".
        self.assertNotIn("return []", body)

    def test_it_never_raises(self):
        """The image handler is launched with asyncio.create_task and nothing
        awaits it, so an exception is an unhandled task exception and the man
        who asked gets SILENCE."""
        body = _body_of("async def _live_plan_file_ids(")
        self.assertIn("except Exception", body)
        # A STATEMENT, not the word. `raise` as a bare substring is also inside
        # "raises" and "_raised"; what this bans is a raise statement, which in
        # stripped source is the token at the start of an indented line.
        self.assertNotIn("\n        raise", body)

    def test_None_means_no_filter_at_all(self):
        import server
        self.assertEqual(server._current_page_filter(None), {})

    def test_the_image_handler_really_is_fire_and_forget(self):
        """The premise of the two assertions above, asserted rather than
        assumed -- if this ever becomes awaited, raising becomes viable and the
        rule here should be revisited deliberately."""
        # EVERY call site, not the first match -- the first is the `async def`
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
        """A result he cannot open is worse than no result: an honest empty
        answer sends him to look properly, while 'A-301, unavailable' reads as
        a system fault and invites a retry that cannot succeed."""
        i = SRC.index("async def search_plans(")
        j = SRC.index("async def _handle_plan_query(")
        span = SRC[min(i, j):max(i, j) + 4000]
        # THE CONSTRUCT, not the word: a placeholder result would have to be
        # built from a literal.
        self.assertNotIn('"unavailable"', span)
        self.assertNotIn("'unavailable'", span)

    def test_an_honest_empty_answer_still_exists_on_both_paths(self):
        """THE WORDING MOVED AND THE CLAIM DID NOT. This pinned "Couldn't find
        a matching sheet", whose full copy continued "Try a sheet number
        (A-301, ME-401)" -- which the agent stance forbids outright: it hands
        the problem back to a superintendent who does not carry the drawing
        list in his head. So it is anchored on the replacements."""
        self.assertIn("Nothing to show for that", SRC,
                      "the sheet path has no honest empty answer -- an omitted "
                      "deleted file would send nothing with nothing said")
        # MOVED AGAIN, 2026-09-20, for the reason this test already records:
        # the old copy told the model "nothing on the current drawings
        # mentions X", which is a claim about the building that a search
        # returning nothing cannot support. Anchored on the replacement.
        self.assertIn("returned no records. That means ", SRC,
                      "the answer path has no honest empty answer -- the model "
                      "would be handed silence and would fill it")
        # And it still must not invite a retry that cannot succeed.
        # CODE LINES ONLY: the remaining occurrences are comments explaining
        # why the copy went, and a guard that trips on its own rationale is a
        # guard nobody keeps.
        code = "\n".join(
            l for l in SRC.split("\n") if not l.lstrip().startswith("#"))
        self.assertNotIn("Try a sheet number", code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
