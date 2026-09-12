"""No filed record is demoted to a generic dump, and none is printed twice.

── WHAT THIS FILE USED TO ASSERT ──────────────────────────────────────────

`generate_combined_report` printed a dedicated section for each log type it
knew about, then swept everything ELSE into "Additional Logbooks", skipping any
type listed in a hand-maintained `handled_types` set. That set was the only
thing standing between a named section and a duplicate. Two types had already
fallen through it -- fall_protection, and site_superintendent_log, the
BC 3301.13.13 log -- so any day carrying either printed it once under its own
heading and again under Additional Logbooks.

── WHY IT IS AIMED SOMEWHERE ELSE NOW ─────────────────────────────────────

The report EMBEDS NOTHING. It carries no sections and no sweep, so there are no
longer two lists to disagree and `handled_types` does not exist. Deleting the
file would have been the easy reading of that.

THE DEFECT IT GUARDS DID NOT GO ANYWHERE. It was never really about a set
literal; it was about TWO HAND-MAINTAINED LISTS OF LOG TYPES that must agree,
where the failure is silent, plausible-looking and invisible to anyone who has
not counted. That shape survives exactly once in the product:

    LOGBOOK_TYPE_REGISTRY   -- every log type the app defines
    generate_single_logbook_html's per-type chain, plus legal_render.SCHEMAS
                            -- every log type the filed PDF knows how to print

A type in the first with no entry in the second falls to the renderer's final
`else`, whose whole body is:

    type_title = log_type.replace("_", " ").title()
    body_html  = bold_para("Status", logbook.get("status", "N/A"))

That is a document with a title and the word "Filed" on it. Not an error, not a
crash, and not obviously wrong to a reader who does not know what the form
contained -- which is the same failure mode, one renderer over, and now the
ONLY copy of the record rather than the second one.

── AND THE OTHER DIRECTION, WHICH IS NEW ──────────────────────────────────

The old file could only check that a type was not printed twice by two blocks
of one renderer. The index makes the stronger check possible: the report's
record cards are DERIVED from the registry rather than retyped, so the cards
and the filed documents cannot disagree about which types exist. That is
asserted here too, because it is what replaced `handled_types` -- and a list
that is derived is only safe while it stays derived.
"""

import ast
import io
import os
import re
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402

_SRC = io.open(BACKEND / "server.py", encoding="utf-8").read()
_TREE = ast.parse(_SRC)


def _body(name):
    node = next(n for n in ast.walk(_TREE)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == name)
    return "".join(_SRC.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])


_FILED = _body("generate_single_logbook_html")
_REPORT = _body("generate_combined_report")

#: Every log type the APP defines. The registry is the product's own list.
DEFINED = {t["key"] for t in server.LOGBOOK_TYPE_REGISTRY}

#: Every log type the FILED DOCUMENT knows how to print: one branch of the
#: per-type chain, or a schema in the declarative engine.
BRANCHED = set(re.findall(r'log_type == "([a-z_]+)"', _FILED))
SCHEMED = set(server.legal_render.CONVERTED_TYPES)
PRINTABLE = BRANCHED | SCHEMED


class TheParseFoundSomethingToCompare(unittest.TestCase):
    """THE VACUITY GUARD. Every assertion below is a set difference, and a
    regex that stops matching makes all of them pass on an empty set."""

    def test_the_registry_was_read(self):
        self.assertGreaterEqual(len(DEFINED), 12)

    def test_the_branch_chain_was_read(self):
        self.assertGreaterEqual(len(BRANCHED), 12)

    def test_the_schema_engine_was_read(self):
        self.assertGreaterEqual(len(SCHEMED), 1)

    def test_the_two_regression_pins_are_still_findable(self):
        """The two that fell through the old set. Both are still log types and
        both must still be printable, or this file has stopped describing the
        product it was written about."""
        self.assertIn("fall_protection", DEFINED)
        self.assertIn("site_superintendent_log", DEFINED)


class NoDefinedTypeFallsToTheGenericBranch(unittest.TestCase):

    def test_every_log_type_the_app_defines_can_be_printed(self):
        """THE ASSERTION. A type with no branch and no schema renders as its
        title and the word Status -- a statutory record demoted to a stub, on
        the only copy of it that exists."""
        demoted = sorted(DEFINED - PRINTABLE)
        self.assertEqual(
            demoted, [],
            "these log types have no renderer branch and no schema, so the "
            "filed PDF prints a title and a status line instead of the "
            f"record: {demoted}")

    def test_the_generic_branch_is_still_there_for_a_type_nobody_defined(self):
        """PASSES EITHER WAY. The fix must not be to delete the fallback --
        a record whose type was retired still has to render as something."""
        self.assertIn("type_title = log_type.replace", _FILED)
        self.assertIn('bold_para("Status"', _FILED)

    def test_and_it_really_is_a_stub(self):
        """The premise of the assertion above, asserted rather than asserted
        about. If the fallback ever learns to print a record's fields, the
        demotion stops being a demotion and this file should be re-read."""
        tail = _FILED[_FILED.rindex("type_title = log_type.replace"):]
        tail = tail[:tail.index("# Wrap in full HTML document")]
        self.assertNotIn(".items()", tail)
        self.assertNotIn("answer_label", tail)


class TheReportsIndexIsDerivedFromTheSameRegistry(unittest.TestCase):
    """WHAT REPLACED `handled_types`.

    The report used to carry its own list of which types it handled. It now
    reads the registry, so the index and the filed documents cannot disagree
    about which log types exist. That property is worth an assertion because
    it is the reason the old duplicate class is gone -- not a coincidence of
    the rewrite.
    """

    def test_the_labels_come_off_the_registry(self):
        self.assertIn("for t in LOGBOOK_TYPE_REGISTRY", _REPORT)

    #: The log types the report is allowed to name, and WHY each one. Naming
    #: a type to read a specific field out of it is not a list of handled
    #: types; an ENUMERATION is, and an enumeration is what drifts.
    BY_NAME = {
        "daily_jobsite":
            "the activities, the weather and the observations are fields of "
            "this log and of no other",
        "site_superintendent_log":
            "safety comes off this log and nowhere else -- when it is not "
            "filed the report states no conclusion",
        "preshift_signin":
            "the card's one-line summary counts the workers recorded on the "
            "sheet, which only this type has",
        "subcontractor_orientation":
            "the oriented-worker figure is read from these records",
    }

    def test_the_report_names_a_type_only_to_read_one_of_its_fields(self):
        """A LITERAL IS THE DRIFT, but only when it is part of a LIST.

        This asserted no type at all was named, which was wrong: four are, and
        each is a single read of a field that belongs to exactly that form.
        The thing that must not come back is an enumeration -- the shape
        `handled_types` had -- so the set is pinned exactly, with the reason
        for every member recorded beside it. A fifth name fails here and has
        to be justified in writing before it lands.
        """
        named = set(re.findall(r'"([a-z_]{4,})"', _REPORT)) & DEFINED
        self.assertEqual(sorted(named), sorted(self.BY_NAME),
                         "the report names a log type that has no recorded "
                         "reason to be named")

    def test_each_name_is_a_single_read_and_not_a_membership_test(self):
        """THE SHAPE, NOT THE COUNT. `in {...}` over log types is the
        enumeration; `_filed_log(logbooks, "x")` and `log_type == "x"` are
        reads of one form."""
        for name in self.BY_NAME:
            reads = (_REPORT.count(f'_filed_log(logbooks, "{name}")')
                     + _REPORT.count(f'log_type") == "{name}"')
                     + _REPORT.count(f'"{name}": '))
            self.assertGreater(reads, 0, f"{name} is named but not read")

    def test_the_sections_and_the_sweep_are_both_gone(self):
        """The other half of "derived": there is nothing left to duplicate."""
        self.assertNotIn("handled_types", _REPORT)
        self.assertNotIn("additional_logbooks_html", _REPORT)


if __name__ == "__main__":
    unittest.main()
