"""The merge rule for a log already filed with duplicate crews.

2026-08-31's daily jobsite log was submitted with EIGHT crews where four
worked: C1-C4 typed by the CP at 13:12 with his descriptions and photos, then
C5-C8 appended in one buildCrewsFromRoster call when the men badged in. The
reconcile short-circuited hand-added rows before its matcher, so a gate crew
for a company already on the log could never merge into it.

THE RECONCILE IS FIXED SEPARATELY. This is the repair for the record that was
already filed, and it is a DRY RUN: the script prints a payload for a human,
posts nothing, and the correction is filed through
POST /api/logbooks/{id}/amend because the log is `submitted` and
FILED_LOG_DATA_IMMUTABLE refuses an in-place write by design.

THE ASSERTION THAT MATTERS IS THE PHOTO COUNT. C5 is not an empty duplicate --
it holds two of the thirteen photos, the two whose R2 keys use the act_ shape.
Dropping C5 without moving them loses evidence off a compliance document, and
the script refuses to emit a payload that loses any.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "amend_duplicate_crews_dryrun",
    BACKEND / "scripts" / "amend_duplicate_crews_dryrun.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

merge_rows = _mod.merge_rows
pick_project = _mod.pick_project


def _photos(n, prefix):
    return [{"id": f"{prefix}_{i}", "original_r2_key": f"logbook-photos/p/{prefix}/{i}.jpg"}
            for i in range(n)]


def _hand(crew, company, n_photos, num_workers="4", source=None):
    """A row with NO gate_sourced flag. On 2026-08-31 these were NOT hand-typed
    -- they were gate-seeded by pre-2026-08-10 code, which set neither
    gate_sourced nor activity_id because neither field existed. `source` is
    left None to match: the number has no recorded author."""
    row = {"crew_id": crew, "company": company, "trade": "",
           "num_workers": num_workers, "photos": _photos(n_photos, f"cap{crew}"),
           "work_description": f"work by {company}", "work_locations": "cellar",
           "worker_ids": ["w9"], "worker_names": ["Z"],
           "check_in_time": "2026-08-31T11:00:00Z"}
    if source:
        row["num_workers_source"] = source
    return row


def _gate(crew, company, n_photos=0, num_workers="6"):
    return {"crew_id": crew, "company": company, "trade": "concrete",
            "num_workers": num_workers, "gate_num_workers": num_workers,
            "gate_sourced": True, "activity_id": f"act_1788191515625_{crew[1:]}",
            "worker_ids": ["w1"], "worker_names": ["A"],
            "photos": _photos(n_photos, f"act{crew}"),
            "work_description": "", "work_locations": ""}


# The shape read off the live document.
TODAY = [
    _hand("C1", "AAZ", 2),
    _hand("C2", "Arkon Builders", 3),
    _hand("C3", "Power Direct", 2),
    # THE ONE REAL ASSERTION: he typed 5 where the gate recorded 4.
    _hand("C4", "Quality Plumbing", 4, num_workers="5", source="cp"),
    _gate("C5", "AAZ", n_photos=2),
    _gate("C6", "Arkon Builders"),
    _gate("C7", "Power Direct"),
    _gate("C8", "Quality Plumbing"),
]


def _total(rows):
    return sum(len(r.get("photos") or []) for r in rows)


class TodaysLog(unittest.TestCase):
    def setUp(self):
        self.out, self.notes = merge_rows(TODAY)

    def test_eight_crews_become_four(self):
        self.assertEqual(len(self.out), 4)

    def test_NOT_ONE_PHOTO_IS_LOST(self):
        """C5 holds two of the thirteen. This is the assertion the whole
        repair exists to satisfy."""
        self.assertEqual(_total(TODAY), 13)
        self.assertEqual(_total(self.out), 13)

    def test_C5s_two_photos_land_on_AAZ(self):
        aaz = next(r for r in self.out if r["company"] == "AAZ")
        self.assertEqual(len(aaz["photos"]), 4)
        keys = [p["original_r2_key"] for p in aaz["photos"]]
        self.assertEqual(len(set(keys)), 4, "no photo duplicated in the move")

    def test_the_R2_keys_are_carried_unchanged(self):
        """A key is stored per photo and read back verbatim; moving a photo
        between rows must not rewrite it."""
        before = sorted(p["original_r2_key"] for r in TODAY for p in r["photos"])
        after = sorted(p["original_r2_key"] for r in self.out for p in r["photos"])
        self.assertEqual(before, after)

    def test_the_CPs_work_survives(self):
        for row in self.out:
            self.assertTrue(row["work_description"].startswith("work by"))
            self.assertEqual(row["work_locations"], "cellar")

    def test_AN_UNATTRIBUTED_NUMBER_IS_NOT_MADE_THE_CPs(self):
        """THE ASSERTION THIS FILE EXISTS FOR NOW. C1-C3 carry counts with no
        recorded author. The tool printed "(cp)" for all of them and was one
        approval away from filing a fabricated author onto a signed 3301.2."""
        for company in ("AAZ", "Arkon Builders", "Power Direct"):
            row = next(r for r in self.out if r["company"] == company)
            self.assertNotIn("num_workers_source", row,
                             f"{company}: an author was invented")
            self.assertEqual(row["num_workers"], "4",
                             f"{company}: the number itself must be kept")
            self.assertEqual(row["gate_num_workers"], "6")

    def test_THE_ONE_REAL_ASSERTION_SURVIVES(self):
        """C4 is genuine: he typed 5 where the gate recorded 4. That
        disagreement is the record and must not be flattened."""
        qp = next(r for r in self.out if r["company"] == "Quality Plumbing")
        self.assertEqual(qp["num_workers"], "5")
        self.assertEqual(qp["num_workers_source"], "cp")
        self.assertEqual(qp["gate_num_workers"], "6")

    def test_the_unset_state_is_printed_DIFFERENTLY(self):
        """It must not read as either party in the output a human reviews."""
        unset = _mod._source_label({})
        cp = _mod._source_label({"num_workers_source": "cp"})
        gate = _mod._source_label({"num_workers_source": "gate"})
        self.assertIn("NO RECORDED AUTHOR", unset)
        self.assertTrue(cp.startswith("cp"))
        self.assertEqual(gate, "gate")
        # Three labels, three distinct strings. The reviewer must not be able
        # to mistake the unset state for either party at a glance.
        self.assertEqual(len({unset, cp, gate}), 3)

    def test_the_gates_named_men_are_carried_across(self):
        aaz = next(r for r in self.out if r["company"] == "AAZ")
        self.assertEqual(aaz["worker_ids"], ["w1"])
        self.assertEqual(aaz["worker_names"], ["A"])

    def test_every_row_is_marked_confirmed(self):
        for row in self.out:
            self.assertIs(row["gate_sourced"], True)

    def test_the_four_companies_appear_once_each(self):
        names = sorted(r["company"] for r in self.out)
        self.assertEqual(names, ["AAZ", "Arkon Builders", "Power Direct",
                                 "Quality Plumbing"])

    def test_it_reports_what_it_did_for_every_row(self):
        self.assertEqual(len([n for n in self.notes if "MERGED" in n]), 4)


class ItRefusesToGuess(unittest.TestCase):
    def test_a_blank_count_adopts_the_gates(self):
        out, _ = merge_rows([_hand("C1", "AAZ", 0, num_workers=""),
                             _gate("C2", "AAZ")])
        self.assertEqual(out[0]["num_workers"], "6")
        self.assertEqual(out[0]["num_workers_source"], "gate")

    def test_a_number_with_no_author_keeps_the_number_and_no_label(self):
        out, _ = merge_rows([_hand("C1", "AAZ", 0, num_workers="3"),
                             _gate("C2", "AAZ")])
        self.assertEqual(out[0]["num_workers"], "3")
        self.assertNotIn("num_workers_source", out[0])

    def test_two_gate_rows_for_one_company_are_LEFT_ALONE(self):
        """Ambiguous. Merging into one of them would file the CP's description
        against a crew that may not have done the work."""
        rows = [_hand("C1", "AAZ", 1), _gate("C2", "AAZ"), _gate("C3", "AAZ")]
        out, notes = merge_rows(rows)
        self.assertEqual(len(out), 3)
        self.assertTrue(any("LEFT ALONE" in n for n in notes))

    def test_two_hand_rows_for_one_company_are_LEFT_ALONE(self):
        rows = [_hand("C1", "AAZ", 1), _hand("C2", "AAZ", 1), _gate("C3", "AAZ")]
        out, notes = merge_rows(rows)
        self.assertEqual(len(out), 3)

    def test_a_lone_gate_crew_is_KEPT_not_deleted(self):
        """It merges; it never removes a crew that stands on its own."""
        out, notes = merge_rows([_gate("C5", "Solo Co")])
        self.assertEqual(len(out), 1)
        self.assertTrue(any("KEPT" in n for n in notes))

    def test_a_lone_hand_crew_is_untouched(self):
        out, _ = merge_rows([_hand("C1", "AAZ", 2)])
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["photos"]), 2)

    def test_company_matching_ignores_case_and_spacing_only(self):
        out, _ = merge_rows([_hand("C1", "AAZ", 0), _gate("C2", "  aaz ")])
        self.assertEqual(len(out), 1)

    def test_it_never_mutates_the_input(self):
        snapshot = _total(TODAY)
        merge_rows(TODAY)
        self.assertEqual(_total(TODAY), snapshot)
        self.assertEqual(len(TODAY), 8)

    def test_an_empty_log_is_fine(self):
        self.assertEqual(merge_rows([])[0], [])
        self.assertEqual(merge_rows(None)[0], [])


class ResolvingTheProjectByName(unittest.TestCase):
    """It must never guess which project a compliance amendment belongs to."""

    ROWS = [
        {"_id": "p1", "name": "588 Thomas St", "address": "588 Thomas St, Bronx"},
        {"_id": "p2", "name": "857 Prescott", "address": "857 Prescott Ave"},
        {"_id": "p3", "name": "8 Walworth", "address": "8 Walworth St"},
    ]

    def test_a_partial_name_resolves(self):
        hit, _ = pick_project(self.ROWS, "588 Thomas")
        self.assertEqual(hit["_id"], "p1")

    def test_case_and_spacing_do_not_matter(self):
        hit, _ = pick_project(self.ROWS, "  588   THOMAS  ")
        self.assertEqual(hit["_id"], "p1")

    def test_it_matches_on_address_too(self):
        hit, _ = pick_project(self.ROWS, "Prescott Ave")
        self.assertEqual(hit["_id"], "p2")

    def test_an_exact_name_wins_over_a_substring_collision(self):
        rows = self.ROWS + [{"_id": "p4", "name": "588 Thomas St Annex",
                             "address": "588 Thomas St"}]
        hit, cands = pick_project(rows, "588 Thomas St")
        self.assertEqual(hit["_id"], "p1")
        self.assertGreater(len(cands), 1)

    def test_TWO_MATCHES_REFUSE(self):
        rows = [{"_id": "a", "name": "Thomas North", "address": ""},
                {"_id": "b", "name": "Thomas South", "address": ""}]
        hit, cands = pick_project(rows, "Thomas")
        self.assertIsNone(hit)
        self.assertEqual(len(cands), 2)

    def test_no_match_refuses(self):
        hit, cands = pick_project(self.ROWS, "Nowhere Rd")
        self.assertIsNone(hit)
        self.assertEqual(cands, [])

    def test_an_empty_needle_refuses(self):
        self.assertIsNone(pick_project(self.ROWS, "")[0])
        self.assertIsNone(pick_project(self.ROWS, None)[0])


class TheScriptWritesNothing(unittest.TestCase):
    def test_no_write_call_anywhere_in_it(self):
        src = (BACKEND / "scripts" / "amend_duplicate_crews_dryrun.py").read_text(
            encoding="utf-8")
        code = "\n".join(
            ln for ln in src.splitlines()
            if not ln.lstrip().startswith("#"))
        for forbidden in ("update_one", "update_many", "insert_one",
                          "replace_one", "delete_one", "delete_many",
                          "find_one_and_update", "bulk_write"):
            self.assertNotIn(forbidden, code, f"dry run must not {forbidden}")

    def test_it_only_reads(self):
        src = (BACKEND / "scripts" / "amend_duplicate_crews_dryrun.py").read_text(
            encoding="utf-8")
        self.assertIn("db.logbooks.find_one", src)


if __name__ == "__main__":
    unittest.main()
