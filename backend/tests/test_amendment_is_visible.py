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


class TheReportHeaderCarriesIt(unittest.TestCase):
    def test_the_combined_report_renders_the_sentence(self):
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index("def generate_combined_report")
        j = src.index("def get_report_preview")
        body = src[i:j]
        self.assertIn("amendment_sentence", body)
        self.assertIn("_amendment_html", body)

    def test_it_sits_in_the_DOCUMENT_header(self):
        """A fact about the record, not about one log section -- so it goes
        beside the date and address, above the content."""
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index("def generate_combined_report")
        body = src[i:src.index("def get_report_preview")]
        self.assertLess(body.index("{_amendment_html}"),
                        body.index("<!-- CONTENT -->"))


if __name__ == "__main__":
    unittest.main()
