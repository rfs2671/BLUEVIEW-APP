"""only_absence_changed must still FLAG (return False) a change that is not
just an absence clause replaced: a dropped number, an altered number, a
rewritten non-absence clause. The positive case (kept clause accepted) is
the control that the helper is not simply always-False."""

from __future__ import annotations

import unittest

from scripts import negative_claims_bindings as nb

ABSENCE = 'Ceiling height not shown; floor-to-floor 10\'-0" (A-300.00).'
NF = "Not found in the sheets I searched: A-300.00."
KEPT = 'Floor-to-floor 10\'-0" (A-300.00).'
OTHER = "The PTAC count is 12 (M-101)."


class OnlyAbsenceChangedStillFlags(unittest.TestCase):
    def test_control_kept_clause_accepted(self):
        before = ABSENCE + " " + OTHER
        after = NF + "\n" + KEPT + " " + OTHER
        self.assertTrue(nb.only_absence_changed(before, after))

    def test_dropped_number_outside_absence_clause_flagged(self):
        before = ABSENCE + " " + OTHER
        after = NF + "\n" + KEPT + " The PTAC count is (M-101)."
        self.assertFalse(nb.only_absence_changed(before, after))
        # the number really is gone, so the bindings' own count sees it too
        self.assertNotEqual(nb.numbers(before), nb.numbers(after, drop_gate_lines=True))

    def test_dropped_whole_non_absence_sentence_flagged(self):
        before = ABSENCE + " " + OTHER
        after = NF + "\n" + KEPT
        self.assertFalse(nb.only_absence_changed(before, after))

    def test_altered_number_in_kept_clause_flagged(self):
        before = ABSENCE
        after = NF + "\n" + 'Floor-to-floor 12\'-0" (A-300.00).'
        self.assertFalse(nb.only_absence_changed(before, after))

    def test_rewritten_non_absence_clause_flagged(self):
        before = ABSENCE + " The door is 3'-0\" wide (A-601)."
        after = NF + "\n" + KEPT + " The door is 3'-6\" wide (A-601)."
        self.assertFalse(nb.only_absence_changed(before, after))
        after2 = NF + "\n" + KEPT + " The door is wide (A-601)."
        self.assertFalse(nb.only_absence_changed(before, after2))


if __name__ == "__main__":
    unittest.main()
