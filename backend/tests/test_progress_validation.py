"""scripts/progress_validation.py's two guarantees, each shown able to fail.

1. READ-ONLY. `ReadOnlyDb` lets the reads through and RAISES on everything
   else: every write method of a collection, a database-level command, an
   aggregate that writes ($out / $merge), a name not on the read list, a
   sub-collection, and setting an attribute. Run against tests/_fake_mongo.FakeDb,
   which implements the writes, so a write that got through would land.
2. NOTHING PERSONAL IS PRINTED. `redact` takes out emails, phone numbers, the
   names it is given, "their words" quotes and who confirmed a photo;
   `redact_answer` replaces an inspection reporter with their role and
   withholds the inspector and the quote.

Plus the script's shape: the sections are a registry other lanes extend, a
count over a field no row carries says so instead of printing 0, and the
script passes tests/test_probe_field_discipline.py's audit.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import progress_validation as PVS  # noqa: E402  (scripts/progress_validation.py)
from audit_probe_field_discipline import audit_source  # noqa: E402
from lib import progress_validation as PV  # noqa: E402
from lib import work_state as W  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "progress_validation.py"


def _run(coro):
    return asyncio.run(coro)


def _db():
    return FakeDb(things=[{"_id": "a", "n": 1}, {"_id": "b", "n": 2}])


# ══ 1. READ-ONLY ═══════════════════════════════════════════════════════════

class ReadsGoThrough(unittest.TestCase):

    def test_find_find_one_count_distinct(self):
        ro = PVS.ReadOnlyDb(_db())
        self.assertEqual([r["_id"] for r in _run(ro.things.find({}).sort("_id", -1).to_list(10))], ["b", "a"])
        self.assertEqual(_run(ro["things"].find_one({"_id": "a"}))["n"], 1)
        self.assertEqual(_run(ro.things.count_documents({})), 2)
        self.assertEqual(_run(ro.things.distinct("n")), [1, 2])
        self.assertEqual(ro.things.name, "things")
        self.assertEqual(_run(ro.get_collection("things").count_documents({"n": 2})), 1)
        self.assertEqual(ro.attempts, [])


class EveryWriteRaises(unittest.TestCase):

    WRITES = {
        "insert_one": ({"_id": "c"},), "insert_many": ([{"_id": "c"}],),
        "update_one": ({"_id": "a"}, {"$set": {"n": 9}}), "update_many": ({}, {"$set": {"n": 9}}),
        "replace_one": ({"_id": "a"}, {"n": 9}), "delete_one": ({"_id": "a"},), "delete_many": ({},),
        "find_one_and_update": ({"_id": "a"}, {"$set": {"n": 9}}), "find_one_and_replace": ({"_id": "a"}, {}),
        "find_one_and_delete": ({"_id": "a"},), "bulk_write": ([],), "create_index": ([("n", 1)],),
        "create_indexes": ([],), "drop_index": ("n_1",), "drop_indexes": (), "drop": (), "rename": ("x",),
        "with_options": (), "watch": (), "database": None,
    }

    def test_each_collection_write_raises_and_nothing_changes(self):
        db = _db()
        ro = PVS.ReadOnlyDb(db)
        for name, args in self.WRITES.items():
            with self.subTest(name), self.assertRaises(PVS.ReadOnlyViolation):
                member = getattr(ro.things, name)
                if args is not None:
                    _run(member(*args)) if asyncio.iscoroutinefunction(member) else member(*args)
        self.assertEqual(db.things.rows, _db().things.rows)
        self.assertEqual(len(ro.attempts), len(self.WRITES))

    def test_through_the_item_spelling_too(self):
        db = _db()
        with self.assertRaises(PVS.ReadOnlyViolation):
            PVS.ReadOnlyDb(db)["things"].update_one({"_id": "a"}, {"$set": {"n": 9}})
        self.assertEqual(db.things.rows[0]["n"], 1)

    def test_an_aggregate_that_writes_raises(self):
        ro = PVS.ReadOnlyDb(_db())
        for stage in ({"$out": "copy"}, {"$merge": {"into": "copy"}}):
            with self.subTest(stage), self.assertRaises(PVS.ReadOnlyViolation):
                ro.things.aggregate([{"$match": {}}, stage])

    def test_a_reading_aggregate_is_passed_on(self):
        seen = []

        class Coll:
            name = "things"

            def aggregate(self, pipeline, *a, **k):
                seen.append(pipeline)
                return "cursor"
        ro = PVS.ReadOnlyCollection(Coll(), [])
        self.assertEqual(ro.aggregate([{"$match": {}}]), "cursor")
        self.assertEqual(seen, [[{"$match": {}}]])

    def test_database_level_writes_raise(self):
        ro = PVS.ReadOnlyDb(_db())
        # Named here, not read off DB_BLOCKED: a name dropped from that set
        # must fail this test (a mutation run caught the circular version).
        for name in ("command", "cursor_command", "create_collection", "drop_collection", "drop_database", "rename",
                     "aggregate", "watch", "with_options", "client", "validate_collection", "dereference"):
            with self.subTest(name), self.assertRaises(PVS.ReadOnlyViolation):
                getattr(ro, name)
        with self.assertRaises(PVS.ReadOnlyViolation):
            ro.get_collection("things", write_concern=None)

    def test_a_sub_collection_or_a_set_attribute_raises(self):
        ro = PVS.ReadOnlyDb(_db())
        with self.assertRaises(PVS.ReadOnlyViolation):
            ro.things["sub"]
        with self.assertRaises(PVS.ReadOnlyViolation):
            ro.things.rows = []
        with self.assertRaises(PVS.ReadOnlyViolation):
            ro.things = None
        with self.assertRaises(PVS.ReadOnlyViolation):
            ro.attempts = []

    def test_a_name_off_the_read_list_raises_even_if_it_sounds_harmless(self):
        with self.assertRaises(PVS.ReadOnlyViolation):
            PVS.ReadOnlyDb(_db()).things.map_reduce

    def test_the_read_list_holds_no_write(self):
        for name in PVS.COLLECTION_READS:
            self.assertFalse(name.startswith(("insert", "update", "replace", "delete", "find_one_and", "bulk",
                                              "create", "drop", "rename")), name)


class TheGuardsOnTheServer(unittest.TestCase):

    def test_installed_and_taken_off(self):
        class Srv:
            db = _db()
            QWEN_API_KEY = "live-key"
            LLM_API_KEY = "live-key"
            ServerHttpClient = object

            async def send_whatsapp_message(self, *a):
                return "sent"
        srv = Srv()
        before = (srv.db, Srv.ServerHttpClient)
        with PVS.read_only(srv) as ro:
            self.assertIsInstance(srv.db, PVS.ReadOnlyDb)
            self.assertIs(ro, srv.db)
            self.assertEqual((srv.QWEN_API_KEY, srv.LLM_API_KEY), ("", None))
            with self.assertRaises(PVS.ReadOnlyViolation):
                srv.ServerHttpClient(timeout=5)
            with self.assertRaises(PVS.ReadOnlyViolation):
                _run(srv.send_whatsapp_message("chat", "hi"))
            with self.assertRaises(PVS.ReadOnlyViolation):
                _run(srv.db.things.insert_one({"_id": "z"}))
        self.assertEqual((srv.db, srv.ServerHttpClient), before)
        self.assertEqual(srv.QWEN_API_KEY, "live-key")


# ══ 2. NOTHING PERSONAL ════════════════════════════════════════════════════

class Redaction(unittest.TestCase):

    def test_emails_phones_and_names(self):
        t = PV.redact("Call Pat PM at (718) 555-0142 or +1 646 555 0199, pat@gc.com; PAT PM agreed. Patch walls.",
                      ["Pat PM"])
        for gone in ("Pat PM", "PAT PM", "555-0142", "555 0199", "pat@gc.com"):
            self.assertNotIn(gone, t)
        self.assertIn("Patch walls", t)
        self.assertEqual(t.count("[person]"), 2)

    def test_the_longest_name_first(self):
        self.assertEqual(PV.redact("Ana Maria Lopez said so", ["Ana", "Ana Maria Lopez"]), "[person] said so")

    def test_quotes_and_confirmers(self):
        t = PV.redact('passed; their words: "plumbing rough passed on 3"\n(placed: confirmed by Sam Lee; x)')
        self.assertNotIn("plumbing rough passed on 3", t)
        self.assertNotIn("Sam Lee", t)
        self.assertIn("their words: [withheld]", t)

    def test_the_layout_is_kept(self):
        self.assertEqual(PV.redact("  a: 1\n    b  x2"), "  a: 1\n    b  x2")

    def test_dates_and_ids_are_not_phone_numbers(self):
        t = "2026-11-22  B00000001-I1  proj_588  4fa06e20"
        self.assertEqual(PV.redact(t), t)

    def test_an_answer_names_roles_not_people(self):
        ans = {"gates": [{"who": "Cal CP", "inspector": "J. Ruiz", "quote": "passed on 3", "status": "attested_passed"},
                         {"status": "unknown", "verified": None}],
               "other_inspections": [{"who": "Pat PM", "quote": "elevator ok", "inspector": None}]}
        out = PV.redact_answer(ans, {"Cal CP": "a CP"})
        self.assertEqual((out["gates"][0]["who"], out["gates"][0]["inspector"], out["gates"][0]["quote"]),
                         ("a CP", "[withheld]", None))
        self.assertNotIn("who", out["gates"][1])
        self.assertEqual((out["other_inspections"][0]["who"], out["other_inspections"][0]["quote"]), ("a person", None))
        self.assertEqual(ans["gates"][0]["who"], "Cal CP")                     # the input is not changed

    def test_role_words(self):
        self.assertEqual([PV.role_words(r) for r in ("admin", "PM", "cp", "superintendent", "worker", None)],
                         ["an admin", "a PM", "a CP", "a superintendent", "a person", "a person"])

    def test_render_redacts_every_line(self):
        sec = {"name": "x", "rows": [("who", "Pat PM")], "todo": ["ask Pat PM"], "lists": [("l", [("Pat PM's crew", 1)])],
               "raw": {}}
        out = PV.render([sec], [("cap", "ready", "Pat PM")], ["Pat PM"])
        self.assertNotIn("Pat PM", out)


# ══ 3. THE SHAPE ═══════════════════════════════════════════════════════════

TODAY = date(2026, 11, 10)


def _data(**over):
    d = {"job": {"project_id": "p", "company_id": "c", "building_stories": None},
         "window": {"start": date(2026, 8, 13), "today": TODAY, "days": 90},
         "logs": [], "acts": [], "index": [], "log_ids": set(), "spaces": {}, "confirmations": {}, "relations": 0,
         "inspections": [], "dob_rows": [], "schedule": None, "schedule_drafts": 0, "proposed": None, "samples": [],
         "prompt_v": 2, "reread_tries": 3}
    d.update(over)
    return d


class TheShape(unittest.TestCase):

    def test_the_sections_are_a_registry_in_order(self):
        self.assertEqual(PV.section_names()[:5], ["logs", "photos", "inspections", "schedule", "work state sample"])

    def test_a_new_section_is_one_function(self):
        @PV.section("_probe_lane")
        def _lane(d):
            return {"name": "_probe_lane", "rows": [("n", 1)], "todo": [], "lists": [], "raw": {}}
        try:
            names = [s["name"] for s in PV.run(_data())]
            self.assertEqual(names[-1], "_probe_lane")
        finally:
            PV._SECTIONS[:] = [s for s in PV._SECTIONS if s[0] != "_probe_lane"]

    def test_an_empty_job_is_said_not_crashed(self):
        secs = PV.run(_data())
        out = PV.render(secs, PV.readiness_for(secs, _data()))
        self.assertIn("work phrases: 0", out)
        self.assertIn("phrases naming any level: 0/0 (no rows)", out)
        self.assertIn("unknown: the project has no building_stories", out)
        self.assertIn("No filed daily log in the window", out)
        ready = {c: s for c, s, _w in PV.readiness_for(secs, _data())}
        self.assertEqual(ready["work_status by level"], PV.BLOCKED)
        self.assertEqual(ready["verified sign-off (DOB)"], PV.BLOCKED)
        self.assertEqual(ready["job's own logic"], PV.NEEDS_DATA)

    def test_a_field_no_row_stores_is_not_a_zero(self):
        idx = [{"kind": "photo", "photo_key": "k", "where": "3rd floor", "log_id": "L", "view": "interior"}]
        out = PV.render(PV.run(_data(index=idx, log_ids={"L"})), [])
        self.assertIn("index prompt version mix: field not stored on any row", out)
        dob = [{"record_type": "job_status", "filing_status": "Signed Off"}]
        out = PV.render(PV.run(_data(dob_rows=dob)), [])
        self.assertIn("sign-off dates: field not stored on any filing row of this job", out)

    def test_a_weak_metric_says_what_to_do(self):
        acts = [{"date": TODAY, "company": "Arkon", "trade": "Framers", "work": "Framing", "where": "floors 1-4",
                 "log_id": "L", "amended": False}]
        out = PV.render(PV.run(_data(acts=acts, logs=[{"_id": "L"}])), [])
        self.assertIn("WHAT TO DO: Few phrases name ONE level", out)

    def test_the_sample_levels(self):
        acts = [{"date": TODAY, "company": "A", "trade": "", "work": "Framing", "where": w, "log_id": "L", "amended": False}
                for w in ("5th floor", "5th floor", "roof", "3rd floor", "floors 1-4")]
        self.assertEqual(PV.sample_levels(acts), ["FLOOR_3", "FLOOR_5", "ROOF"])
        self.assertEqual(PV.sample_levels([]), ["FLOOR_3", "FLOOR_2", "FLOOR_4"])
        self.assertTrue(W)

    def test_signed_off_wording(self):
        for status, signed in (("Signed Off", True), ("SIGNED-OFF", True), ("LOC Issued", True), ("Approved", False),
                               ("Permit Issued", False)):
            self.assertEqual(bool(PV.SIGNED_OFF.search(status)), signed, status)


class TheScriptPassesTheFieldAudit(unittest.TestCase):

    def test_no_undeclared_counted_field(self):
        self.assertEqual(audit_source(SCRIPT.read_text(encoding="utf-8"), SCRIPT.name), [])

    def test_it_imports_no_server_at_import_time(self):
        """The guards must be on before server code runs a single read."""
        src = SCRIPT.read_text(encoding="utf-8")
        top = src[:src.index("class ReadOnlyViolation")]
        self.assertNotIn("import server", top)
        body = src[src.index("async def _main("):src.index("def main(")]
        self.assertLess(body.index("with read_only(server)"), body.index("job_report("))


class TheCommandLine(unittest.TestCase):

    def test_a_job_or_all_jobs_is_required(self):
        with self.assertRaises(SystemExit):
            PVS.main([])

    def test_an_unknown_job_is_exit_2_and_ids_only(self):
        class Srv:
            db = PVS.ReadOnlyDb(FakeDb(projects=[{"_id": "p1", "name": "Alpha", "address": "1 Main St"},
                                                 {"_id": "p2", "name": "Alpha Two", "address": "2 Main St"}]))
        code, out = _run(PVS.job_report(Srv(), "alpha", today=TODAY))
        self.assertEqual(code, 2)
        self.assertIn("2 live jobs match", out)
        self.assertNotIn("Main St", out)
        self.assertTrue(datetime.now(timezone.utc))


if __name__ == "__main__":
    unittest.main()
