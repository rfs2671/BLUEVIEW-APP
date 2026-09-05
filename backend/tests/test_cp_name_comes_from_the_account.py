"""THE COMPETENT PERSON IS WHO HIS ACCOUNT SAYS HE IS, NOT WHAT HE TYPED.

`cp_name` came from a free-text box beside the signature pad. Across 313 filed
logbooks it holds EIGHT values for what is meant to be one identity:

    219  'michael'              typed
     33  None
     25  '2'                    typed
     15  'Roy Fishman'
     13  'michael Cespedes'     the server path, from user.cp_name
      8  'Test CP'              typed
      1  'roy fishman'
      1  'Michael Cespedes'

The account held `Michael Cespedes` in two fields the whole time. On a §3301.2
record the competent person is who the document says he is; a digit is not a
name and a lowercase first name is not an identification.

── THE ORIENTATION IS THE EXCEPTION, AND IT IS NOT AN OVERSIGHT ────────────

`cp_name` on a `subcontractor_orientation` is the TRAINER'S ATTESTATION — the
competent person who DELIVERED it, who on a real jobsite may not be the man
filing the paperwork. Forcing the account holder's name onto that would put the
wrong man's name on an attestation, which is worse than the defect being fixed.
That type keeps its per-row value; its screen now offers a picker over the
company's competent persons instead of a text box.

── FORWARD-ONLY ───────────────────────────────────────────────────────────

Nothing rewrites the 233 records already filed on a live jobsite. They say what
was captured. `michael` is what he typed and what he signed under, and
rewriting a filed compliance document to a nicer spelling is the thing this
product does not do. There is no migration in this change and this file
asserts none.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402
from tests.source_text import code_of  # noqa: E402

_CODE = code_of("server.py")
_RAW = (_BACKEND / "server.py").read_text(encoding="utf-8")

#: The account as production actually holds it: three name fields, two values.
USER = {"name": "Michael Cespedes", "full_name": "Michael Cespedes",
        "cp_name": "michael Cespedes"}

TEN = ("daily_jobsite", "toolbox_talk", "preshift_signin", "osha_log",
       "scaffold_maintenance", "hot_work", "concrete_operations",
       "crane_operations", "excavation_monitoring", "fall_protection",
       "ssc_daily_safety_log", "site_superintendent_log")


class TheTypedValueIsIgnoredOnEveryTypeButOne(unittest.TestCase):

    def test_the_typed_name_never_survives(self):
        for lt in TEN:
            for typed in ("michael", "2", "Test CP", "", None):
                with self.subTest(log_type=lt, typed=typed):
                    self.assertEqual(
                        server._resolved_cp_name(lt, typed, USER),
                        "michael Cespedes")

    def test_the_orientation_keeps_the_trainer(self):
        """The trainer may legitimately differ from the filer. Forcing the
        account holder's name here would put the wrong man on a §3301.2
        attestation."""
        self.assertEqual(
            server._resolved_cp_name(
                "subcontractor_orientation", "Ada Trainer", USER),
            "Ada Trainer")

    def test_and_an_orientation_with_no_name_stays_empty(self):
        """It is not silently backfilled with the filer either — that would be
        the same wrong claim by omission."""
        self.assertIsNone(
            server._resolved_cp_name("subcontractor_orientation", None, USER))

    def test_the_field_order_prefers_cp_name_then_full_name_then_name(self):
        self.assertEqual(
            server._resolved_cp_name("daily_jobsite", "x", USER),
            "michael Cespedes")
        self.assertEqual(
            server._resolved_cp_name(
                "daily_jobsite", "x", {"full_name": "F", "name": "N"}), "F")
        self.assertEqual(
            server._resolved_cp_name("daily_jobsite", "x", {"name": "N"}), "N")

    def test_an_account_with_NO_name_falls_back_to_what_was_sent(self):
        """The refusal that is NOT made. An account with no name at all is a
        real state, and dropping the typed value there would file a logbook
        with a blank Competent Person — worse than a badly spelled one."""
        self.assertEqual(
            server._resolved_cp_name("daily_jobsite", "michael", {}), "michael")


class NoWritePathReadsTheClientsValueForTheTen(unittest.TestCase):
    """The census. An assertion about the helper says nothing about a third
    write site added next month."""

    def _writes(self):
        tree = ast.parse(_RAW)
        out = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Dict):
                    continue
                for k, v in zip(node.keys, node.values):
                    if (isinstance(k, ast.Constant) and k.value == "cp_name"):
                        out.append((fn.name, node.lineno, ast.unparse(v)))
                if False:
                    pass
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign):
                    t = ast.unparse(node.targets[0])
                    if t.endswith('["cp_name"]') or t.endswith("['cp_name']"):
                        out.append((fn.name, node.lineno, ast.unparse(node.value)))
        return out

    def test_the_census_found_the_write_sites(self):
        w = self._writes()
        self.assertGreaterEqual(len(w), 3, f"only {len(w)} cp_name writes found")

    def test_none_of_them_stores_data_cp_name_directly(self):
        offenders = [f"server.py:{ln} {fn} -> {src}"
                     for fn, ln, src in self._writes()
                     if src.strip() in ("data.cp_name", "data.cp_name or ''")]
        self.assertEqual(
            offenders, [],
            "a write path still stores the typed value verbatim: "
            + "; ".join(offenders))

    def test_the_helper_is_what_they_go_through(self):
        srcs = [s for _f, _l, s in self._writes()]
        self.assertTrue(
            any("_resolved_cp_name" in s for s in srcs),
            f"no write path calls the helper: {srcs}")


class TheTwoDocumentsAgreeAboutTheSameRecord(unittest.TestCase):
    """The display half. A stored `michael` printed as `Michael` on seven of
    eight sites and raw on the eighth, so the per-logbook PDF and the combined
    report disagreed about one record."""

    def test_no_cp_line_prints_the_stored_value_raw(self):
        import re
        raw = re.findall(r'bold_para\("CP", (?!_capitalize_first)[^)]+\)', _CODE)
        self.assertEqual(raw, [], f"raw CP render sites remain: {raw}")

    def test_and_there_are_still_CP_lines_to_print(self):
        """The absence rule: deleting every CP line satisfies the test above."""
        self.assertGreater(_CODE.count('bold_para("CP"'), 3)


class NothingRewritesWhatIsAlreadyFiled(unittest.TestCase):
    def test_no_migration_ships_with_this(self):
        for bad in ("update_many", "$set': {'cp_name"):
            i = _CODE.find("def _resolved_cp_name")
            j = _CODE.find("\ndef ", i + 10)
            self.assertNotIn(bad, _CODE[i:j])


if __name__ == "__main__":
    unittest.main(verbosity=2)
