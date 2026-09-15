"""A COUNT ON AN ABSENT FIELD MUST RAISE, NOT RETURN ZERO.

Three probes in one session reported a zero that came from asking for a field
the collection does not have. `scripts/probe_helpers.py` makes that an error.
This proves it does, including the empty-sample case, which is the one that
produced "0 pages indexed in 30 days" against a collection holding 149 rows.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from probe_helpers import (                                      # noqa: E402
    FieldNotInSample, counted, describe, require_fields, sample_keys,
)

# The real shape, from production.
INDEX_ROWS = [
    {"_id": 1, "file_id": "a", "page_number": 2, "indexed_at": "2026-04-17",
     "sheet_number": "A-500.00", "keywords": ["wall"], "sheet_title": "PARTITION"},
    {"_id": 2, "file_id": "a", "page_number": 3, "indexed_at": "2026-08-27",
     "sheet_number": None, "keywords": [], "sheet_title": "PLAN"},
]


class AFieldThatIsNotThereIsAnError(unittest.TestCase):
    def test_counting_a_missing_field_raises(self):
        """`created_at` does not exist here; the real field is `indexed_at`.
        The old probe reported 0 and it read as 'nothing was indexed'."""
        with self.assertRaises(FieldNotInSample):
            counted(INDEX_ROWS, "created_at")

    def test_the_message_names_the_keys_that_DO_exist(self):
        try:
            counted(INDEX_ROWS, "searchable_text")
        except FieldNotInSample as e:
            self.assertIn("sheet_number", str(e))
            self.assertIn("indexed_at", str(e))
        else:
            self.fail("expected FieldNotInSample")

    def test_an_empty_sample_raises_rather_than_counting_zero(self):
        """The worst case: a count across nothing looks identical to a count
        that found nothing."""
        with self.assertRaises(FieldNotInSample):
            counted([], "indexed_at")

    def test_a_field_that_exists_counts_normally(self):
        self.assertEqual(counted(INDEX_ROWS, "indexed_at"), 2)
        self.assertEqual(
            counted(INDEX_ROWS, "sheet_number", lambda v: v is None), 1)

    def test_require_fields_passes_when_present_on_any_document(self):
        require_fields(INDEX_ROWS, "indexed_at", "sheet_title")

    def test_sample_keys_is_the_union_not_the_first_document(self):
        rows = [{"a": 1}, {"b": 2}]
        self.assertEqual(sample_keys(rows), ["a", "b"])


class DescribeSaysWhichFieldsAreAbsent(unittest.TestCase):
    def test_absent_fields_are_named_and_not_counted(self):
        out = describe(INDEX_ROWS, "indexed_at", "searchable_text")
        self.assertIn("indexed_at: present", out)
        self.assertIn("searchable_text: ABSENT FROM SAMPLE", out)
        self.assertIn("keys:", out)


if __name__ == "__main__":
    unittest.main()
