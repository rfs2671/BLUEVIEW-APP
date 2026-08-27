"""THE FILED LOG SAYS WHICH HEADCOUNT CAME FROM WHERE.

A daily 3301.2 log already carried two headcounts from two provenances: the
gate table, computed from check-ins by _headcount_by_sub, and the crew rows,
which print activities[].num_workers. The crew row never said which kind it
was, so a number a person typed and a number a turnstile counted printed
identically on a record somebody signs.

The CP can now correct a crew's headcount, so that stopped being cosmetic.
gate_num_workers is retained beside the override precisely so this renderer can
say `4 (CP) - gate recorded 6`; if the correction simply replaced the
turnstile's number, nothing downstream could tell that a person had changed a
gate count, or what it had been.

ABSENCE MEANS GATE. Drafts written before num_workers_source existed hold
numbers that came from the roster, and labelling those "(CP)" would put a false
attribution on records that are already filed.

    python -m pytest backend/tests/test_headcount_provenance_on_the_filed_log.py
"""

import ast
import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402

SRC = (BACKEND / "server.py").read_text(encoding="utf-8-sig")
TREE = ast.parse(SRC)

def cell(act, blank=""):
    """Resolved at CALL time, not import time.

    Binding server._headcount_cell at module scope made this file die during
    COLLECTION against a tree without the helper -- one opaque error instead of
    the named assertions that say what is missing. A test that cannot report
    which guarantee is absent is a worse regression signal than no test."""
    fn = getattr(server, "_headcount_cell", None)
    if fn is None:
        raise AssertionError("server._headcount_cell does not exist")
    return fn(act, blank)


class AGateCountPrintsPlain(unittest.TestCase):
    """Nothing changes for the rows nobody has touched."""

    def test_an_explicit_gate_row(self):
        self.assertEqual(
            cell({"num_workers": "6", "num_workers_source": "gate",
                  "gate_num_workers": "6"}),
            "6")

    def test_a_row_with_NO_marker_is_treated_as_gate(self):
        """Every draft written before this field existed. Labelling these "(CP)"
        would be a false attribution on an already-filed record."""
        self.assertEqual(cell({"num_workers": "6"}), "6")

    def test_a_legacy_row_with_a_gate_count_but_no_marker(self):
        self.assertEqual(cell({"num_workers": "6", "gate_num_workers": "6"}), "6")


class AnOverridePrintsBothNumbers(unittest.TestCase):
    """The whole reason gate_num_workers is retained."""

    def test_the_cp_number_and_what_the_gate_recorded(self):
        self.assertEqual(
            cell({"num_workers": "4", "num_workers_source": "cp",
                  "gate_num_workers": "6"}),
            "4 (CP) - gate recorded 6")

    def test_an_override_over_an_absent_crew(self):
        """The gate saw nobody, the CP says four were here. Both print."""
        self.assertEqual(
            cell({"num_workers": "4", "num_workers_source": "cp",
                  "gate_num_workers": "0"}),
            "4 (CP) - gate recorded 0")

    def test_a_cp_zero_over_a_gate_count(self):
        """He is asserting the turnstile was wrong the other way."""
        self.assertEqual(
            cell({"num_workers": "0", "num_workers_source": "cp",
                  "gate_num_workers": "6"}),
            "0 (CP) - gate recorded 6")

    def test_a_confirmation_still_says_a_person_supplied_it(self):
        """He typed the same number. That is a person having checked, and the
        record should say so rather than silently reading as gate data."""
        self.assertEqual(
            cell({"num_workers": "6", "num_workers_source": "cp",
                  "gate_num_workers": "6"}),
            "6 (CP) - gate recorded 6")


class AHandAddedCrewHasNoGateNumberToCite(unittest.TestCase):

    def test_it_is_still_attributed(self):
        self.assertEqual(
            cell({"num_workers": "3", "num_workers_source": "cp"}), "3 (CP)")

    def test_an_empty_gate_field_is_not_printed_as_a_count(self):
        self.assertEqual(
            cell({"num_workers": "3", "num_workers_source": "cp",
                  "gate_num_workers": ""}), "3 (CP)")


class ABlankCountUsesEachRenderersOwnDefault(unittest.TestCase):
    """The two callers disagreed before this change and still do: the combined
    report prints 0, the per-logbook PDF prints nothing. That was not this
    change's to reconcile."""

    def test_blank_with_no_default(self):
        self.assertEqual(cell({"num_workers": ""}), "")

    def test_blank_with_a_zero_default(self):
        self.assertEqual(cell({"num_workers": ""}, blank="0"), "0")

    def test_a_missing_key(self):
        self.assertEqual(cell({}, blank="0"), "0")

    def test_None_is_not_rendered_as_the_string_None(self):
        self.assertEqual(cell({"num_workers": None}, blank="0"), "0")


def _fn(name):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


class BothRenderersUseIt(unittest.TestCase):
    """READ AS CODE. The helper's docstring names num_workers,
    gate_num_workers and "(CP)", so a substring search of the file would match
    the explanation rather than the call."""

    def test_no_daily_jobsite_crew_row_prints_num_workers_raw(self):
        """THE CLASS: a daily-jobsite ACTIVITY row printing a bare count. A
        third renderer added later fails here.

        SCOPED TO `act`, WHICH IS THE ACTIVITY LOOP VARIABLE IN BOTH CREW-ROW
        RENDERERS, AND NOT TO EVERY num_workers IN THE FILE. The first draft of
        this assertion was file-wide and caught the SITE SUPERINTENDENT LOG's
        subcontractor cards (`card.get("num_workers", 0)`), which are a
        different logbook, a different document shape, and hand-typed by the
        superintendent. Those rows have exactly one provenance, so there is
        nothing for them to attribute and they carry neither
        num_workers_source nor gate_num_workers. Narrowed deliberately, and
        recorded here so it does not read as an oversight.
        """
        stray = []
        helper_lines = set(range(
            _fn("_headcount_cell").lineno,
            getattr(_fn("_headcount_cell"), "end_lineno", 0) + 1))
        for node in ast.walk(TREE):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
                continue
            if not (isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "act"):
                continue
            if not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and first.value == "num_workers"):
                continue
            if node.lineno in helper_lines:
                continue
            stray.append(node.lineno)
        self.assertEqual(stray, [], f"bare activity num_workers at {stray}")

    def test_the_superintendent_log_is_untouched(self):
        """The narrowing above is only honest if the row it excludes is still
        proven to be a different shape. A subcontractor card carrying a
        num_workers_source would mean the two logs had converged and this
        exclusion had gone stale."""
        # READ AS STRUCTURE. The first draft indexed the first TEXTUAL match of
        # "subcontractor_cards", which is a Pydantic field declaration, not a
        # renderer -- the same shape as a fixed-size text window running past
        # the construct it meant to read.
        loops = []
        for node in ast.walk(TREE):
            if not isinstance(node, ast.For):
                continue
            if not (isinstance(node.target, ast.Name) and node.target.id == "card"):
                continue
            if "subcontractor_cards" not in ast.unparse(node.iter):
                continue
            loops.append(node)

        self.assertTrue(loops, "the subcontractor-card renderers disappeared")
        for loop in loops:
            # THE EXACT KEYS THE LOOP READS, not a substring scan of its source.
            # `assertNotIn("num_workers_source", body)` is a bare substring ban
            # and test_absence_literals_are_specific rejects it -- rightly:
            # "num_workers" is a substring of "num_workers_source", so the two
            # assertions would have contradicted each other the moment one of
            # these rows gained a marker.
            keys = set()
            for node in ast.walk(loop):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "get"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "card"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)):
                    keys.add(node.args[0].value)
            with self.subTest(line=loop.lineno):
                self.assertIn("num_workers", keys)
                self.assertNotIn("num_workers_source", keys)
                self.assertNotIn("gate_num_workers", keys)

    def test_the_helper_is_called_at_least_twice(self):
        calls = [n.lineno for n in ast.walk(TREE)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "_headcount_cell"]
        self.assertGreaterEqual(len(calls), 2, "both crew-row renderers must use it")

    def test_the_marker_is_compared_to_the_literal_cp(self):
        """Truthiness would let any stray value claim CP authorship."""
        found = False
        for node in ast.walk(_fn("_headcount_cell")):
            if isinstance(node, ast.Compare) and "num_workers_source" in ast.unparse(node.left):
                if any(isinstance(c, ast.Constant) and c.value == "cp"
                       for c in node.comparators):
                    found = True
        self.assertTrue(found)


if __name__ == "__main__":
    unittest.main(verbosity=2)
