"""An amended record says it was amended, and why.

`amendment_reason` was WRITE-ONLY. amend_logbook stored it on the child
(server.py) and nothing read it back -- not the app, not the report. The
sentence justifying a change to a signed 3301.2 record existed only in Mongo.

THREE STATES, AND THE MIDDLE ONE IS NOT DECORATIVE:

  present            amended, and the reason is on the record
  no_reason_recorded amended, and no reason was recorded
  not_amended        an ordinary filed log

amend_logbook refuses a reasonless amendment with a 400, so nothing reaching
that endpoint lands in the middle state. A script, a migration or a direct
write can, and this codebase spent 2026-08-31 on exactly that class of row --
gate-seeded crews carrying counts with no recorded author, which two writers
each resolved by picking a side. Collapsing "amended, reason unknown" into
"not amended" hides a correction; collapsing it into "amended and explained"
prints an empty quotation as though somebody had written it.

IT READS THE RECORD, NEVER THE CLOCK. An amendment filed in September for an
August log must say the same thing in December, so every value here comes off
the document -- created_at, created_by_name, amendment_reason -- and nothing
is computed against today.
"""

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

FILED_AT = datetime(2026, 8, 31, 21, 40, tzinfo=timezone.utc)


def _child(**over):
    doc = {
        "log_type": "daily_jobsite", "date": "2026-08-31",
        "is_amendment": True,
        "amendment_reason": "This log listed every subcontractor twice.",
        "created_by_name": "Roy Fishman",
        "created_at": FILED_AT,
    }
    doc.update(over)
    return doc


class ThreeStates(unittest.TestCase):
    def test_amended_and_explained(self):
        out = server.amendment_state(_child())
        self.assertEqual(out["state"], server.AMENDMENT_PRESENT)
        self.assertIn("twice", out["reason"])
        self.assertEqual(out["by"], "Roy Fishman")
        self.assertEqual(out["at"], FILED_AT)

    def test_amended_with_NO_reason_recorded(self):
        for blank in (None, "", "   "):
            out = server.amendment_state(_child(amendment_reason=blank))
            self.assertEqual(out["state"], server.AMENDMENT_NO_REASON, repr(blank))
            self.assertIsNone(out["reason"])

    def test_an_ordinary_log_is_not_amended(self):
        for doc in ({"log_type": "daily_jobsite"},
                    {"is_amendment": False},
                    {"is_amendment": "yes"},          # not True: not an amendment
                    {}, None, "not a dict"):
            self.assertEqual(server.amendment_state(doc)["state"],
                             server.AMENDMENT_NONE)

    def test_the_middle_state_is_NEITHER_of_the_others(self):
        """The whole point of three."""
        states = {server.amendment_state(_child())["state"],
                  server.amendment_state(_child(amendment_reason=None))["state"],
                  server.amendment_state({})["state"]}
        self.assertEqual(len(states), 3)


class TheSentenceSaysWhoAndWhen(unittest.TestCase):
    def test_it_names_the_person_and_the_date(self):
        s = server.amendment_sentence(server.amendment_state(_child()))
        self.assertIn("Roy Fishman", s)
        self.assertIn("2026-08-31", s)
        self.assertIn("twice", s)

    def test_a_missing_reason_SAYS_SO(self):
        s = server.amendment_sentence(
            server.amendment_state(_child(amendment_reason="")))
        self.assertIn("no reason", s.lower())
        self.assertIn("Roy Fishman", s)

    def test_an_unknown_author_is_not_invented(self):
        s = server.amendment_sentence(
            server.amendment_state(_child(created_by_name=None)))
        self.assertNotIn("None", s)
        self.assertIn("2026-08-31", s)

    def test_an_unamended_record_says_nothing_at_all(self):
        self.assertEqual(server.amendment_sentence(server.amendment_state({})), "")

    def test_NOTHING_IS_RELATIVE_TO_TODAY(self):
        """"Amended yesterday" is false the day after. Every rendering is
        absolute so the record reads the same in December."""
        s = server.amendment_sentence(server.amendment_state(_child()))
        for relative in ("today", "yesterday", "ago", "recently", "just now"):
            self.assertNotIn(relative, s.lower())

    def test_a_string_created_at_still_renders_its_date(self):
        """Mongo hands back datetimes; a serialized doc hands back a string.
        Both are the record."""
        s = server.amendment_sentence(
            server.amendment_state(_child(created_at="2026-08-31T21:40:00Z")))
        self.assertIn("2026-08-31", s)

    def test_a_missing_date_does_not_fabricate_one(self):
        s = server.amendment_sentence(
            server.amendment_state(_child(created_at=None)))
        self.assertNotIn("None", s)
        self.assertIn("Roy Fishman", s)


class TheFiledDocumentCarriesIt(unittest.TestCase):
    """── THE READER MOVED, AND THE SENTENCE COVERS MORE THAN IT DID ───────

    This was asserted on `generate_combined_report`'s SOURCE: the name
    `amendment_sentence` appears in it, and `{_amendment_html}` appears before
    the `<!-- CONTENT -->` marker. The report indexes the filed documents now
    and prints no header of theirs, so both anchors are gone.

    THE CLAIM IS NOT. `amendment_reason` being write-only is the defect this
    whole file exists for, and with the report's header gone the sentence had
    no reader left anywhere -- the same state, reached a different way. It
    prints on the FILED DOCUMENT now, which is where the operator's standing
    ruling puts filing apparatus: the report points at the record, the record
    carries its own audit trail.

    AND IT REACHES EVERY TYPE. The report's header read `daily_jobsite` and
    only that, so an amended toolbox talk, OSHA register or pre-shift sheet
    announced itself nowhere. The document header has no such limit, and the
    case below proves it on a second type.

    ASSERTED ON RENDERED HTML rather than on source, because a variable name
    in a function body is not a sentence on a page.
    """

    @staticmethod
    def _render(doc):
        import asyncio
        from unittest.mock import patch

        class _C:
            def __init__(self, docs=None):
                self.docs = list(docs or [])

            async def find_one(self, *a, **k):
                return self.docs[0] if self.docs else None

            def find(self, *a, **k):
                return _Cur(self.docs)

        class _Cur:
            def __init__(self, docs):
                self._d = docs

            async def to_list(self, *a, **k):
                return list(self._d)

            def sort(self, *a, **k):
                return self

        class _DB:
            projects = _C([{"_id": "p1", "name": "588 Thomas S Boyland Street",
                            "address": "588 Thomas S Boyland St, Brooklyn"}])
            logbooks = _C()
            checkins = _C()

        with patch.object(server, "db", _DB()), \
                patch.object(server, "to_query_id", lambda x: x):
            return asyncio.run(server.generate_single_logbook_html(doc))

    def test_an_amended_record_says_so_on_its_own_face(self):
        html = self._render(_child())
        self.assertIn("AMENDED RECORD", html)
        self.assertIn("Roy Fishman", html)
        self.assertIn("twice", html)

    def test_it_sits_above_the_content(self):
        """A fact about the RECORD, not about one section of it, so it goes
        at the top of the page rather than beside whichever item it changed."""
        # A BRANCH-RENDERED TYPE, because this claim is about the BRANCH's
        # page. The daily jobsite log moved onto the declarative engine, which
        # builds a different document with no `<td>` content cell and no
        # "(NYC DOB 3301-02)" heading, so this assertion started reporting on
        # markup that no longer exists rather than on a placement that had
        # changed. The engine's own placement -- filing state, then this
        # banner, then section 1 -- is pinned in
        # test_the_sheet_keeps_its_banners.py, where the sibling half of this
        # rule lives.
        html = self._render(_child(log_type="toolbox_talk", data={}))
        # THE CONTENT CELL, isolated. The document names its type three
        # times -- the `<title>`, the dark header, the section heading -- and
        # the first two are always before anything. The claim is about the
        # order INSIDE the cell that holds the record.
        cell = html[html.index(
            '<td style="padding:24px 40px;background-color:#ffffff;"'):]
        cell = cell[:cell.index("</td>")]
        self.assertLess(
            cell.index("AMENDED RECORD"),
            cell.index("Tool Box Talk"),   # three words, as the type prints
            "the amendment notice is below the content it qualifies")

    def test_an_ORDINARY_log_carries_no_banner(self):
        """The absence half. A banner on every document says nothing."""
        html = self._render({"log_type": "daily_jobsite", "date": "2026-08-31",
                             "data": {}})
        self.assertNotIn("AMENDED RECORD", html)

    def test_a_type_the_old_placement_never_reached(self):
        """The report's header read the daily jobsite log and no other, so an
        amended toolbox talk announced itself nowhere at all."""
        html = self._render(_child(log_type="toolbox_talk", data={}))
        self.assertIn("AMENDED RECORD", html)
        self.assertIn("Roy Fishman", html)

    def test_the_reason_is_escaped(self):
        """Operator-supplied text on its way into an HTML document."""
        html = self._render(_child(
            amendment_reason='Duplicated <script>alert(1)</script> rows'))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_a_reasonless_amendment_still_announces_itself(self):
        """The middle state reaches paper. Collapsing it into "not amended"
        hides a correction to a signed record."""
        html = self._render(_child(amendment_reason=""))
        self.assertIn("AMENDED RECORD", html)
        self.assertIn("no reason", html.lower())


if __name__ == "__main__":
    unittest.main()
