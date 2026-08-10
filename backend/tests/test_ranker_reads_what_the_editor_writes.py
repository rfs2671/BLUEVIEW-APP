"""The ranker must read the field the STEPPER writes, not the one the seed does.

THE DEFECT THIS EXISTS TO PREVENT, IN FULL.

`_activity_chip_ids` read `activity_chip_id` — one string per activity row. The
U1 stepper writes `activity_ids` — a list. Nothing bridged them, and a grep of
the whole repository found `activity_chip_id` written in exactly one place: the
seed script.

So every daily jobsite log a real Competent Person filed contributed ZERO
priors, and the chips fell back to cold start every single day, permanently.
The sequence engine had never once fired on data a person produced.

AND THE ENDPOINT'S OWN TESTS WERE GREEN THROUGHOUT, because they fed it
hand-written rows carrying the field it wanted. A test that supplies the input
under test cannot detect that nothing else supplies it.

So the tests below refuse to hand-write the field name. They read it out of the
SHIPPED EDITOR SOURCE — frontend/src/utils/dailyJobsiteModel.js, the module the
stepper actually builds its rows from — and assert the ranker reads whatever
that says. Rename the field in the editor and this fails, which is the whole
point: the two ends are pinned to each other rather than both to a constant
that only the seed satisfies.
"""

from __future__ import annotations

import ast
import os
import re
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
from app.scheduling.sequence_ranking import rank_activities  # noqa: E402

_FRONTEND = _BACKEND.parent / "frontend"
_MODEL = _FRONTEND / "src" / "utils" / "dailyJobsiteModel.js"
_SCREEN = _FRONTEND / "app" / "logbooks" / "daily_jobsite.jsx"
_SEED = _BACKEND / "scripts" / "seed_857_prescott.py"


def _empty_activity_keys():
    """The keys EMPTY_ACTIVITY declares, read from the shipped editor module."""
    src = _MODEL.read_text(encoding="utf-8")
    start = src.index("export const EMPTY_ACTIVITY = () => ({")
    end = src.index("});", start)
    body = src[start:end]
    # `key:` at the start of a line, ignoring comments.
    body = re.sub(r"//[^\n]*", "", body)
    return set(re.findall(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*):", body, re.M))


class TheFieldNamesAreNotHandWritten(unittest.TestCase):
    def test_the_editor_module_is_where_it_is_expected(self):
        self.assertTrue(_MODEL.exists(), f"{_MODEL} — the editor's row shape")

    def test_the_editor_declares_the_field_the_ranker_reads(self):
        keys = _empty_activity_keys()
        self.assertIn(
            server.ACTIVITY_IDS_FIELD, keys,
            f"the ranker reads {server.ACTIVITY_IDS_FIELD!r}; EMPTY_ACTIVITY "
            f"declares {sorted(keys)}. If the editor renamed it, the ranker "
            f"must follow — this is the mismatch that shipped.",
        )

    def test_the_editor_does_NOT_write_the_legacy_field(self):
        """Guards the reverse mistake: 'fixing' this by making the editor write
        the legacy name would leave the array shape unreachable."""
        src = re.sub(r"//[^\n]*", "", _MODEL.read_text(encoding="utf-8"))
        self.assertNotIn(f'{server.ACTIVITY_CHIP_ID_FIELD}:', src)

    def test_the_row_survives_the_save_payload_intact(self):
        """The chip ids only reach the server if the row is spread whole. If the
        payload builder ever enumerates fields, a new one silently vanishes."""
        screen = _SCREEN.read_text(encoding="utf-8")
        self.assertRegex(
            screen,
            r"\.\.\.act,\s*\n\s*photos: \(act\.photos \|\| \[\]\)\.map\(photoForPayload\)",
            "the payload must spread the whole activity row",
        )


class ALogFiledByTheStepperProducesPriors(unittest.TestCase):
    """End to end over the shape the editor really builds."""

    def _stepper_row(self, ids, **extra):
        """A row shaped like EMPTY_ACTIVITY, with the ids the CP tapped.

        Built from the editor's OWN key list, so a row here cannot carry a field
        the editor does not have.
        """
        keys = _empty_activity_keys()
        self.assertIn(server.ACTIVITY_IDS_FIELD, keys)
        row = {k: None for k in keys}
        row[server.ACTIVITY_IDS_FIELD] = list(ids)
        row.update(extra)
        return row

    def test_one_tapped_chip_becomes_one_prior(self):
        data = {"activities": [self._stepper_row(["excavation"])]}
        self.assertEqual(server._activity_chip_ids(data), ["excavation"])

    def test_a_row_with_three_activities_yields_THREE_priors(self):
        """ONE ROW PER CREW. A crew that did three things is one row carrying
        three ids — not three crews."""
        data = {"activities": [
            self._stepper_row(["excavation", "slab_rebar", "edge_forms"]),
        ]}
        self.assertEqual(
            server._activity_chip_ids(data),
            ["excavation", "slab_rebar", "edge_forms"],
        )

    def test_several_crews_each_with_several_activities(self):
        data = {"activities": [
            self._stepper_row(["excavation", "shoring"]),
            self._stepper_row(["slab_rebar"]),
        ]}
        self.assertEqual(
            server._activity_chip_ids(data),
            ["excavation", "shoring", "slab_rebar"],
        )

    def test_duplicates_across_crews_collapse(self):
        data = {"activities": [
            self._stepper_row(["excavation", "shoring"]),
            self._stepper_row(["excavation"]),
        ]}
        self.assertEqual(server._activity_chip_ids(data), ["excavation", "shoring"])

    def test_those_priors_actually_move_the_ranking(self):
        """The end of the chain: a stepper-shaped log changes the chips. This is
        the assertion the old suite could not make, because nothing it fed the
        ranker was ever produced by the editor."""
        data = {"activities": [self._stepper_row(["excavation"])]}
        priors = server._activity_chip_ids(data)
        ranked = rank_activities(project_id="p", prior_activity_ids=priors,
                                 structural_system="cast_in_place")
        suggested = [c.id for c in ranked.chips if c.band == "suggested"]
        self.assertIn("excavation", suggested, "the prior stays offered")
        self.assertIn("footings", suggested, "and opens its successors")

        cold = rank_activities(project_id="p", prior_activity_ids=[],
                               structural_system="cast_in_place")
        cold_suggested = [c.id for c in cold.chips if c.band == "suggested"]
        self.assertNotEqual(suggested, cold_suggested,
                            "a filed log must change the ranking, not fall to cold start")

    def test_a_free_text_entry_ranks_as_itself(self):
        data = {"activities": [self._stepper_row(["other:night pour"])]}
        self.assertEqual(server._activity_chip_ids(data), ["other:night pour"])
        self.assertEqual(server._other_labels_in(data), ["night pour"],
                         "and is remembered, so it comes back as its own chip")

    def test_an_untouched_row_contributes_nothing(self):
        data = {"activities": [self._stepper_row([])]}
        self.assertEqual(server._activity_chip_ids(data), [])


class ColdStartStillFires(unittest.TestCase):
    def test_no_prior_at_all_is_cold_start(self):
        cold = rank_activities(project_id="p", prior_activity_ids=[],
                               structural_system="cast_in_place")
        suggested = [c.id for c in cold.chips if c.band == "suggested"]
        self.assertIn("site_prep", suggested)
        self.assertIn("excavation", suggested)

    def test_a_log_with_no_activities_falls_to_cold_start(self):
        self.assertEqual(server._activity_chip_ids({"activities": []}), [])

    def test_unrecognized_priors_fall_to_cold_start_without_raising(self):
        ranked = rank_activities(project_id="p",
                                 prior_activity_ids=["no_such_node"],
                                 structural_system="cast_in_place")
        suggested = [c.id for c in ranked.chips if c.band == "suggested"]
        self.assertIn("site_prep", suggested)


class LegacyRowsStillRank(unittest.TestCase):
    """Filed records are never migrated. A string is a list of one."""

    def test_a_legacy_single_string_still_ranks(self):
        data = {"activities": [{"activity_chip_id": "excavation"}]}
        self.assertEqual(server._activity_chip_ids(data), ["excavation"])

    def test_a_legacy_other_row_still_ranks_and_is_remembered(self):
        data = {"activities": [
            {"activity_chip_id": "other", "activity_other_label": "window rig"},
        ]}
        self.assertEqual(server._activity_chip_ids(data), ["other:window rig"])
        self.assertEqual(server._other_labels_in(data), ["window rig"])

    def test_a_legacy_other_row_with_no_label_stays_the_bare_chip(self):
        data = {"activities": [
            {"activity_chip_id": "other", "activity_other_label": "  "},
        ]}
        self.assertEqual(server._activity_chip_ids(data), ["other"])
        self.assertEqual(server._other_labels_in(data), [])

    def test_a_row_carrying_BOTH_shapes_loses_neither(self):
        """Someone edited across a version boundary. Dropping half of what the
        row says would lose logged work."""
        data = {"activities": [{
            "activity_ids": ["excavation"],
            "activity_chip_id": "shoring",
        }]}
        self.assertEqual(server._activity_chip_ids(data), ["excavation", "shoring"])

    def test_junk_in_the_array_is_skipped_not_crashed(self):
        data = {"activities": [{"activity_ids": ["excavation", None, 7, "", "  "]}]}
        self.assertEqual(server._activity_chip_ids(data), ["excavation"])

    def test_a_non_list_activity_ids_does_not_crash(self):
        for junk in ("excavation", 7, {}, None):
            data = {"activities": [{"activity_ids": junk}]}
            self.assertEqual(server._activity_chip_ids(data), [], repr(junk))


class TheSeedWritesWhatTheEditorWrites(unittest.TestCase):
    """Otherwise the ranking test is the seed being tested against itself."""

    def test_the_seed_writes_the_array_field(self):
        seed = _SEED.read_text(encoding="utf-8")
        self.assertRegex(seed, rf'"{server.ACTIVITY_IDS_FIELD}":\s*\[')

    def test_the_seed_no_longer_writes_the_legacy_field(self):
        seed = re.sub(r"#[^\n]*", "", _SEED.read_text(encoding="utf-8"))
        self.assertNotIn(f'"{server.ACTIVITY_CHIP_ID_FIELD}"', seed)

    def test_the_seeds_prior_row_is_readable_by_the_ranker(self):
        """Parse the literal the seed posts and run the real extractor on it."""
        seed = _SEED.read_text(encoding="utf-8")
        m = re.search(r'"activity_ids":\s*(\[[^\]]*\])', seed)
        self.assertIsNotNone(m, "the seed's activity_ids literal")
        ids_src = m.group(1).replace("PRIOR_ACTIVITY", '"building_envelope_closed"')
        ids = ast.literal_eval(ids_src)
        data = {"activities": [{"activity_ids": ids}]}
        self.assertEqual(server._activity_chip_ids(data), ["building_envelope_closed"])
        ranked = rank_activities(project_id="p",
                                 prior_activity_ids=server._activity_chip_ids(data),
                                 structural_system="cast_in_place")
        suggested = [c.id for c in ranked.chips if c.band == "suggested"]
        self.assertEqual(
            suggested,
            ["building_envelope_closed", "insulation", "drywall"],
            "the three chips the operator is told to expect on his phone",
        )


if __name__ == "__main__":
    unittest.main()
