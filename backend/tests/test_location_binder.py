"""lib/location_binder: a location string held against THIS project's levels
and plan tags, abstaining rather than guessing.

The seed set at the bottom is the real 588 strings visible in its reports and
DOB data, labeled by hand. ITS FRAME IS AN ASSUMPTION, stated: 588's levels are
the ones its sheets name (level_suggestion's docstring: first to fourth floor,
mezzanine, roof, bulkhead), plus what every building has (roof, foundation); the
plan tag 3B is assumed to exist with no sheet titled for one level. The DOB
strings are as the brief gave them, truncated with "...": the full format of
work_on_floor was not read from DOB here.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))
sys.path.insert(0, str(_BACKEND / "tests"))

from lib import location_binder as B  # noqa: E402
from lib import photo_place as PP  # noqa: E402
from lib import work_state as W  # noqa: E402

F4 = ["FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4", "MEZZANINE", "ROOF", "BULKHEAD", "FOUNDATION"]
TAGS = ["3B", "4A", "STAIR A", "BIKE ROOM"]
FRAME = {"levels": F4, "spaces": {k: {"levels": []} for k in TAGS}}


def bind(text, source=B.LOG_ROW, levels=F4, spaces=TAGS):
    return B.bind(text, levels, spaces, source=source)


class ALevelTheProjectLacksAbstains(unittest.TestCase):
    def test_a_floor_above_the_building(self):
        r = bind("floor 9")
        self.assertEqual((r["certainty"], r["reason"], r["levels"]), (B.NONE, B.R_NOT_IN_PROJECT, []))
        self.assertEqual(r["candidates"], ["FLOOR_9"])

    def test_a_cellar_on_a_building_with_none(self):
        for text in ("cellar", "basement", "sótano"):
            self.assertEqual(bind(text)["reason"], B.R_NOT_IN_PROJECT, text)

    def test_a_span_partly_outside_is_not_cut_down_to_the_part_inside(self):
        r = bind("floors 1-6")
        self.assertEqual((r["certainty"], r["levels"]), (B.NONE, []))

    def test_ground_is_not_floor_one(self):
        r = bind("Ground Floor")
        self.assertEqual((r["certainty"], r["candidates"]), (B.NONE, ["GROUND"]))
        self.assertEqual(bind("Ground Floor", levels=F4 + ["GROUND"])["levels"], ["GROUND"])

    def test_no_frame_is_no_answer(self):
        self.assertEqual(bind("floor 3", levels=[])["reason"], B.R_NO_FRAME)


class SeveralFloorsAreConstrainedNeverOne(unittest.TestCase):
    def test_spans(self):
        for text in ("floors 1-4", "floors 1–4", "1st-4th", "Floor Number(s) 1 thru 4", "1st thru 4th floor"):
            r = bind(text, B.DOB_WORK_ON_FLOOR if "Number" in text else B.LOG_ROW)
            self.assertEqual((r["certainty"], r["levels"]), (B.CONSTRAINED, F4[:4]), text)

    def test_lists(self):
        for text, want in (("fl 2&3", ["FLOOR_2", "FLOOR_3"]), ("1st and 2nd floor", ["FLOOR_1", "FLOOR_2"]),
                           ("3rd Floor, 4th Floor", ["FLOOR_3", "FLOOR_4"]), ("roof/bulkhead", ["ROOF", "BULKHEAD"])):
            r = bind(text)
            self.assertEqual((r["certainty"], r["levels"]), (B.CONSTRAINED, want), text)

    def test_a_choice_is_not_a_place(self):
        for text in ("3 or 4", "floor 3 or 4", "piso 3 o 4"):
            r = bind(text)
            self.assertEqual((r["certainty"], r["reason"]), (B.NONE, B.R_CHOICE), text)

    def test_one_floor_is_exact(self):
        for text, want in (("floor 3", "FLOOR_3"), ("2nd flr", "FLOOR_2"), ("mezz", "MEZZANINE"), ("Roof", "ROOF"),
                           ("piso 3", "FLOOR_3"), ("3er piso", "FLOOR_3"), ("segundo piso", "FLOOR_2"), ("techo", "ROOF")):
            r = bind(text)
            self.assertEqual((r["certainty"], r["levels"]), (B.EXACT, [want]), text)


class UnitTagsMatchOnWordBoundariesOnly(unittest.TestCase):
    def test_spellings_of_one_tag(self):
        for text in ("3B", "Apt 3B", "apt. 3-B", "3-B", "unit #3B", "Apt 3 B", "kitchen in 3B."):
            r = bind(text)
            self.assertEqual((r["space"], r["certainty"]), ("3B", B.EXACT), text)

    def test_not_inside_another_word(self):
        for text in ("13B", "3BR", "A3B", "3B2", "33B"):
            self.assertIsNone(bind(text)["space"], text)

    def test_a_named_tag_by_whole_words(self):
        self.assertEqual(bind("stair A")["space"], "STAIR A")
        self.assertIsNone(bind("stairA")["space"])
        self.assertEqual(bind("bike room")["space"], "BIKE ROOM")
        self.assertIsNone(bind("bike roomy")["space"])

    def test_a_unit_never_implies_its_floor(self):
        r = bind("3B")
        self.assertEqual(r["levels"], [])

    def test_a_tag_on_a_sheet_titled_for_one_level_places_it(self):
        spaces = {"3B": {"levels": ["FLOOR_3"]}}
        self.assertEqual(bind("3B", spaces=spaces)["levels"], ["FLOOR_3"])
        r = bind("floor 2 apt 3B", spaces=spaces)
        self.assertEqual((r["certainty"], r["reason"]), (B.NONE, B.R_DISAGREE))

    def test_a_unit_the_plans_do_not_hold(self):
        self.assertEqual(bind("5Z")["reason"], B.R_UNIT_UNKNOWN)
        self.assertEqual(bind("3B", spaces=[])["reason"], B.R_TAGS_UNKNOWN)

    def test_two_tags_abstain(self):
        self.assertEqual(bind("3B and 4A")["reason"], B.R_SPACES)


class OtherPlaces(unittest.TestCase):
    def test_exterior_has_no_level(self):
        for text in ("Outer bldg", "Facade", "exterior", "fachada", "sidewalk"):
            r = bind(text)
            self.assertEqual((r["levels"], r["area"], r["certainty"]), ([], B.EXTERIOR, B.EXACT), text)
        self.assertEqual(bind("Open Space", B.DOB_WORK_ON_FLOOR)["area"], B.EXTERIOR)

    def test_a_corridor_number_is_not_a_floor(self):
        r = bind("corridor 3")
        self.assertEqual((r["certainty"], r["reason"], r["candidates"]), (B.NONE, B.R_CORRIDOR, ["FLOOR_3"]))
        self.assertEqual(bind("corridor floor 3")["levels"], ["FLOOR_3"])

    def test_below_grade_words_are_not_settled(self):
        self.assertEqual(bind("underground")["reason"], B.R_BELOW)

    def test_a_punch_floor_field_is_a_level(self):
        self.assertEqual(bind("4", B.PUNCH_FLOOR)["levels"], ["FLOOR_4"])
        self.assertEqual(bind("4", B.LOG_ROW)["levels"], [])

    def test_legible_text_is_read_whole(self):
        self.assertEqual(bind("FLOOR 3", B.PHOTO_VISIBLE_TEXT)["levels"], ["FLOOR_3"])
        r = bind("5TH FLOOR EXIT THIS WAY", B.PHOTO_VISIBLE_TEXT)
        self.assertEqual((r["certainty"], r["reason"]), (B.NONE, B.R_NOTHING))
        self.assertEqual(bind("APT 3B", B.PHOTO_VISIBLE_TEXT)["space"], "3B")


class DobWorkOnFloor(unittest.TestCase):
    def test_the_floor_is_read_and_the_job_references_are_not(self):
        self.assertEqual(B.dob_text("Floor Number(s)-1-SO-5912-B011..."), "floor 1")
        r = bind("Floor Number(s)-1-SO-5912-B011...", B.DOB_WORK_ON_FLOOR)
        self.assertEqual((r["levels"], r["space"], r["certainty"]), (["FLOOR_1"], None, B.EXACT))

    def test_the_number_after_a_named_level_is_not_a_floor(self):
        r = bind("Mezzanine-4-SO-...", B.DOB_WORK_ON_FLOOR)
        self.assertEqual(r["levels"], ["MEZZANINE"])

    def test_a_list(self):
        r = bind("Floor Number(s)-2-SO-1-B1, Roof-1-SO-2", B.DOB_WORK_ON_FLOOR)
        self.assertEqual((r["levels"], r["certainty"]), (["FLOOR_2", "ROOF"], B.CONSTRAINED))


class TheFrame(unittest.TestCase):
    def test_from_the_project_fields(self):
        f = B.frame_from({"building_stories": 3, "has_cellar": True, "has_mezzanine": None})
        self.assertEqual(f["levels"], ["CELLAR", "FOUNDATION", "FLOOR_1", "FLOOR_2", "FLOOR_3", "ROOF"])
        self.assertTrue(f["known"])
        self.assertEqual(f["basis"]["ROOF"], ["every_building"])

    def test_nothing_known_is_empty(self):
        f = B.frame_from({}, [], [["floor 3"]])
        self.assertEqual((f["levels"], f["known"]), ([], False))

    def test_plan_sheets_and_logs(self):
        pages = [{"sheet_number": "A-101", "sheet_title": "SECOND FLOOR PLAN"}, {"sheet_number": "A-105", "floor": "Mezzanine"}]
        logs = [["cellar"], ["Cellar, floor 2"], ["floor 7"]]
        f = B.frame_from({}, pages, logs)
        self.assertIn("plan_sheets", f["basis"]["FLOOR_2"])
        self.assertEqual(f["basis"]["CELLAR"], ["logs:2"])
        self.assertNotIn("FLOOR_7", f["levels"])          # one log is not a storey

    def test_a_floor_above_the_stated_count_is_excluded(self):
        logs = [["floor 6"], ["floor 6"]]
        f = B.frame_from({"building_stories": 4}, [{"sheet_title": "FIFTH FLOOR PLAN"}], logs)
        self.assertNotIn("FLOOR_5", f["levels"])
        self.assertNotIn("FLOOR_6", f["levels"])
        self.assertEqual(sorted(f["excluded"]), ["FLOOR_5", "FLOOR_6"])


class WiredIn(unittest.TestCase):
    """work_state.places_in and photo_place.infer bind when the frame holds
    levels, and read as before when it does not."""

    def test_places_in_without_a_frame_is_unchanged(self):
        self.assertEqual(W.places_in("floor 9")["levels"], ["FLOOR_9"])
        self.assertEqual(W.places_in("3B"), {"levels": ["FLOOR_3"], "space": "3B"})
        self.assertEqual(W.places_in("floor 9", {"levels": []})["levels"], ["FLOOR_9"])

    def test_places_in_with_a_frame(self):
        self.assertEqual(W.places_in("floor 9", FRAME), {"levels": [], "space": None})
        self.assertEqual(W.places_in("3B", FRAME), {"levels": [], "space": "3B"})
        self.assertEqual(W.places_in("floors 1-4", FRAME)["levels"], F4[:4])

    def test_a_frame_with_no_tags_keeps_the_old_space(self):
        self.assertEqual(W.places_in("Apt 3B, floor 3", {"levels": F4})["space"], "3B")

    def test_evidence_rows(self):
        acts = [{"date": "2026-10-01", "company": "X", "work": "Framing", "where": "floor 9"}]
        self.assertEqual(W.evidence_rows(acts)[0]["levels"], ["FLOOR_9"])
        self.assertEqual(W.evidence_rows(acts, FRAME)[0]["levels"], [])

    def test_photo_place(self):
        photo = {"where": "floor 9", "visible_text": []}
        self.assertEqual(PP.infer(photo)["level"], "FLOOR_9")
        self.assertEqual(PP.infer(photo, frame=FRAME)["certainty"], PP.UNKNOWN)
        marked = {"where": "floors 1-4", "visible_text": ["FLOOR 9"]}
        self.assertEqual(PP.infer(marked)["certainty"], PP.CONFLICT)
        self.assertEqual(PP.infer(marked, frame=FRAME)["certainty"], PP.CONSTRAINED)

    def test_photo_rows_and_what_holds_carry_it(self):
        rows = W.photo_rows([{"where": "floor 9", "photo_key": "k", "log_id": "1"}], frame=FRAME)
        self.assertEqual(rows[0]["levels"], [])
        from datetime import date
        acts = [{"date": date(2026, 10, 1), "company": "X", "work": "Drywall", "where": "floor 9"}]
        ans = W.what_holds("drywall", "FLOOR_9", acts, [], today=date(2026, 10, 2), frame=FRAME)
        self.assertEqual(ans["counts"]["on_this_level"], 0)
        self.assertEqual(W.what_holds("drywall", "FLOOR_9", acts, [], today=date(2026, 10, 2))["counts"]["on_this_level"], 1)


class TheServerHelper(unittest.TestCase):
    """_project_place_frame reads and never writes, and lives in its one block."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
        os.environ.setdefault("DB_NAME", "smoke_test")
        os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
        os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
        import server
        cls.server = server

    def test_it_reads_the_project_plans_tags_and_logs(self):
        from async_fake_mongo import AsyncFakeDB
        from bson import ObjectId
        db = AsyncFakeDB()
        pid = ObjectId()
        db.projects.docs.append({"_id": pid, "building_stories": 2, "has_roof_bulkhead": True})
        db.document_page_index.docs.append({"project_id": str(pid), "sheet_number": "A-100", "sheet_title": "CELLAR PLAN"})
        db.plan_records.docs.append({"project_id": str(pid), "unit": "2A", "sheet_title": "SECOND FLOOR PLAN"})
        for i in range(2):
            db.logbooks.docs.append({"project_id": str(pid), "log_type": "daily_jobsite",
                                     "data": {"activities": [{"work_locations": "Mezzanine"}]}})
        with patch.object(self.server, "db", db):
            f = asyncio.run(self.server._project_place_frame(str(pid)))
        self.assertEqual(f["levels"], ["CELLAR", "FOUNDATION", "FLOOR_1", "FLOOR_2", "MEZZANINE", "ROOF", "BULKHEAD"])
        self.assertEqual(f["spaces"]["2A"]["levels"], ["FLOOR_2"])
        self.assertEqual(sum(len(c.writes) for c in db._c.values()), 0)
        self.assertEqual(W.places_in("2A", f), {"levels": ["FLOOR_2"], "space": "2A"})

    def test_a_failed_read_is_an_empty_frame(self):
        class Broken:
            def __getattr__(self, name):
                raise RuntimeError("down")
        with patch.object(self.server, "db", Broken()):
            f = asyncio.run(self.server._project_place_frame("p"))
        self.assertEqual((f["levels"], f["known"]), ([], False))

    def test_one_block_directly_above_the_photos_block(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        head = "# ── LOCATION BINDER (lib/location_binder.py)"
        nxt = "# ── PHOTOS POSTED IN A JOB GROUP (lib/wa_photos.py)"
        self.assertEqual(src.count(head), 1)
        block = src[src.index(head):src.index(nxt)]
        self.assertIn("async def _project_place_frame(", block)
        for write in (".insert_one(", ".insert_many(", ".update_one(", ".update_many(", ".delete_one(",
                      ".delete_many(", ".replace_one(", ".bulk_write(", ".find_one_and_"):
            self.assertNotIn(write, block)


# ── THE SEED SET: real 588 strings, labeled by hand ─────────────────────────
#: (source, text, true_levels, true_space). "-" "-": no place can be read.
SEED = [
    (B.LOG_ROW, "floors 1-4", "1|2|3|4", ""),
    (B.LOG_ROW, "floors 1–4", "1|2|3|4", ""),
    (B.LOG_ROW, "Roof", "ROOF", ""),
    (B.LOG_ROW, "Outer bldg", "", "EXTERIOR"),
    (B.DOB_WORK_ON_FLOOR, "Floor Number(s)-1-SO-5912-B011...", "1", ""),
    # Ground or first: 588 has no ruling on whether they are one storey.
    (B.DOB_WORK_ON_FLOOR, "Ground Floor", "-", "-"),
    (B.DOB_WORK_ON_FLOOR, "Mezzanine-4-SO-...", "MEZZANINE", ""),
    (B.DOB_WORK_ON_FLOOR, "Open Space", "", "EXTERIOR"),
    (B.LOG_ROW, "Facade", "", "EXTERIOR"),
    (B.LOG_ROW, "floor 1", "1", ""),
    (B.LOG_ROW, "floors 2-4", "2|3|4", ""),
    (B.LOG_ROW, "floor 3", "3", ""),
    # The string names the unit, not its floor.
    (B.LOG_ROW, "3B", "", "3B"),
]
SEED_FRAME = {"levels": ["FLOOR_1", "FLOOR_2", "FLOOR_3", "FLOOR_4", "MEZZANINE", "ROOF", "BULKHEAD", "FOUNDATION"],
              "spaces": {"3B": {"levels": []}}}


class TheSeedSet(unittest.TestCase):
    def _score(self):
        import location_binder_eval as E
        rows = [{"source": s, "text": t, "count": 1, "true_levels": tl, "true_space": ts} for s, t, tl, ts in SEED]
        return E.score(rows, SEED_FRAME), E

    def test_precision_coverage_abstain(self):
        tally, E = self._score()
        a = tally["ALL"]
        print("\nSEED SET (588)\n" + E.report(tally))
        self.assertEqual((a["labeled"], a["right"], a["wrong"], a["abstain"]), (13, 12, 0, 1))
        self.assertEqual((a["coverage"]["k"], a["coverage"]["n"]), (12, 12))

    def test_the_old_reader_on_the_same_set(self):
        """places_in with no frame, judged the same way: what the binder fixes."""
        wrong = []
        for s, t, tl, ts in SEED:
            old = W.places_in(B.dob_text(t) if s == B.DOB_WORK_ON_FLOOR else t)
            res = {"levels": old["levels"], "space": old["space"], "area": None,
                   "certainty": B.EXACT if (old["levels"] or old["space"]) else B.NONE}
            if B.judge(res, tl, ts) == B.WRONG:
                wrong.append(t)
        self.assertEqual(wrong, ["Ground Floor", "3B"])


class TheEvalScript(unittest.TestCase):
    def test_no_phone_number_or_email_in_the_dump(self):
        import location_binder_eval as E
        counts, dropped = E.collect([{"data": {"activities": [{"work_locations": "floor 3 call 718-555-0100"}]}}],
                                    [], [{"floor": "4", "area": "mail me a@b.co"}],
                                    [{"where": "floor 2", "visible_text": ["ACME", "FLOOR 2", "CALL 212 555 0199"]}], [])
        texts = " ".join(t for _s, t in counts)
        for leak in ("718-555-0100", "a@b.co", "212 555 0199", "ACME"):
            self.assertNotIn(leak, texts)
        self.assertEqual(dropped, 1)

    def test_unlabeled_rows_are_not_scored(self):
        import location_binder_eval as E
        t = E.score([{"source": B.LOG_ROW, "text": "floor 3", "count": 4, "true_levels": "", "true_space": ""}], SEED_FRAME)
        self.assertEqual(t, {})

    def test_it_passes_the_probe_field_audit(self):
        from audit_probe_field_discipline import audit_source
        src = (_BACKEND / "scripts" / "location_binder_eval.py").read_text(encoding="utf-8")
        self.assertEqual(audit_source(src, "location_binder_eval.py"), [])


if __name__ == "__main__":
    unittest.main()
