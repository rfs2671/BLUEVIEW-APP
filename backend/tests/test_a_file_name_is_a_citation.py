"""A FILE'S NAME AND A SET'S LABEL ARE CITATIONS, NEVER FIGURES.

#892 shows the model each record's file and drawing set, and a well-cited
answer repeats them: "21 PTAC-1 [M-200.00 · 588 Boyland Mech 7.2.pdf]". The
gate read "588" and "7.2" as figures no record vouched for and refused the
correct answer (spatial session, 2026-10-28). They are now removed as TEXT
before any figure is read (plan_search.strip_source_citations); a set label
is said as its set's bare name, so a claim naming a set still binds only on
that set's rows. Their digits are never whitelisted: a "588" stated as a
figure binds on the records or not at all.

scripts/citation_bindings.py probes every stored answer, main against this.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import plan_search as S  # noqa: E402
from tests.test_a_count_binds_only_from_a_counting_source import PTAC_SCHEDULE  # noqa: E402

FILE = "588 Boyland Mech 7.2.pdf"
PTAC = dict(PTAC_SCHEDULE, file_name=FILE, file_id="f1")
SRC = [{"file_name": FILE, "track": "post_co", "label": "Post-CO rev 7.2 6/9/26"}]


def ok(text, intent="count", records=(PTAC,), sources=SRC):
    return S.answer_is_grounded(text, list(records), intent=intent, sources=sources)


class FileNames(unittest.TestCase):
    def test_a_count_citing_its_file_binds(self):
        for t in ("There are 21 PTAC-1 units in the building [M-200.00, 588 Boyland Mech 7.2.pdf].",
                  "There are 21 PTAC-1 units in the building, per 588 Boyland Mech 7.2.PDF."):
            with self.subTest(t=t):
                self.assertEqual(ok(t), (True, []))

    def test_an_attribute_citing_its_file_binds(self):
        t = "PTAC-1 is AMANA PTH093G35AXXX, 9000 BTU cooling [M-200.00 · 588 Boyland Mech 7.2.pdf]."
        self.assertEqual(ok(t, intent=""), (True, []))

    def test_the_file_name_lends_no_figure(self):
        for n in ("588", "7.2", "7"):
            with self.subTest(n=n):
                g, bad = ok(f"There are {n} PTAC-1 units in the building [M-200.00, {FILE}].")
                self.assertFalse(g)
                self.assertIn(n, bad)

    def test_the_records_own_file_name_counts_without_sources(self):
        t = "There are 21 PTAC-1 units in the building [M-200.00, 588 Boyland Mech 7.2.pdf]."
        self.assertEqual(ok(t, sources=()), (True, []))

    def test_a_name_with_no_letter_is_never_removed(self):
        rec = dict(PTAC, file_name="588")
        g, bad = ok("There are 588 PTAC-1 units in the building.", records=(rec,), sources=())
        self.assertFalse(g)


    def test_only_what_cannot_be_prose_is_removed(self):
        """Never a bare stem: "4A" out of "4A has 9 WH-1" would make it a
        building figure. The whole name, ".pdf" and all, is the citation."""
        for name, kept in (("4B Mech.pdf", "4B Mech has"), ("filed.pdf", "in the filed set"),
                           ("Plans.pdf", "the Plans show")):
            with self.subTest(name=name):
                out = S.strip_source_citations(f"{kept} 3 (see {name})", [{"file_name": name}])
                self.assertIn(kept, out)
        self.assertEqual(ok("There are 21 PTAC-1 units in the building (M-200.00 · 588 Boyland Mech 7.2)."),
                         (False, ["588", "7.2"]), "a stem without .pdf is not removed: refused as before")

    def test_a_name_or_label_with_a_scope_word_is_never_removed(self):
        """Codex #910: with "Apartment 4A.pdf", stripping "Apartment 4A"
        made "Apartment 4A has 9 WH-1." a building figure that bound."""
        from tests.test_a_count_binds_only_from_a_counting_source import WH_SCHEDULE
        for name in ("Apartment 4A.pdf", "4A.pdf", "2nd Floor 7.2.pdf", "Unit 3 rev 2.pdf"):
            with self.subTest(name=name):
                rec = dict(WH_SCHEDULE, file_name=name)
                self.assertEqual(S.source_citations([rec]), ([], []))
                for t in ("Apartment 4A has 9 WH-1.", f"Apartment 4A has 9 WH-1 [{name}]."):
                    self.assertFalse(S.answer_is_grounded(t, [rec], intent="count")[0], t)
        lab = [{"file_name": "", "track": "post_co", "label": "Apt 4A set 6/9/26"}]
        self.assertEqual(S.source_citations([], lab), ([], []))


class SetLabels(unittest.TestCase):
    def test_a_set_label_is_no_figure(self):
        t = "PTAC-1 is 9000 BTU cooling per the Post-CO rev 7.2 6/9/26."
        self.assertEqual(ok(t, intent=""), (True, []))
        self.assertFalse(ok(t, intent="", sources=())[0], "without the label it reads 7.2, 6, 9, 26")

    def test_a_set_label_still_names_its_set(self):
        """Said as "owner's set" after the answer's own "per the": a count naming the set binds only on
        that set's located rows, never on a printed QTY, exactly as before."""
        self.assertEqual(S.strip_source_citations("21 PTAC-1 per the Post-CO rev 7.2 6/9/26", [], SRC).split(),
                         ["21", "PTAC-1", "per", "the", "owner's", "set"])
        named = ok("There are 21 PTAC-1 units in the building per the Post-CO rev 7.2 6/9/26.")
        plain = ok("There are 21 PTAC-1 units in the building per the owner's set.", sources=())
        self.assertEqual(named, plain)


if __name__ == "__main__":
    unittest.main()
