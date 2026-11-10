"""THE READ-ONLY PROJECT EXPORT (scripts/project_intel_export.py).

It runs against PRODUCTION with the operator's variables, so its contract is
proved here: a write is refused AND counted, a person is one stable pseudonym,
a phone number never survives, a vague selector refuses, and a collection over
the bound refuses the whole run.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from bson import ObjectId

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_intel_export as X  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402

PID = ObjectId()
OTHER = ObjectId()


def _run(coro):
    return asyncio.run(coro)


def _db() -> AsyncFakeDB:
    db = AsyncFakeDB()
    db.projects.docs += [
        {"_id": PID, "name": "588 Thomas S. Boyland St", "address": "588 Thomas S Boyland St", "company_id": "c1"},
        {"_id": OTHER, "name": "Another job", "address": "12 Elm St", "company_id": "c1"}]
    db.companies.docs.append({"_id": "c1", "name": "Blueview Construction Inc", "admin_password_hash": "x"})
    db.workers.docs.append({"_id": "w1", "name": "Jose Garcia", "phone": "+1 (718) 555-0142", "company": "ABC Drywall",
                            "trade": "drywall", "password_hash": "secret", "signature": "data:image/png;base64,AAAA",
                            "certifications": [{"type": "SST", "number": "SST-123", "expiration_date": "2027-01-01"}],
                            "safety_orientations": [{"project_id": str(PID), "completed_at": "2026-05-01"}]})
    db.checkins.docs += [
        {"_id": 1, "project_id": str(PID), "worker_id": "w1", "worker_name": "Jose Garcia", "worker_phone": "17185550142",
         "company": "ABC Drywall", "device_fingerprint": "fp", "source_ip": "1.2.3.4"},
        {"_id": 2, "project_id": str(OTHER), "worker_id": "w9", "worker_name": "Not Ours"}]
    db.whatsapp_groups.docs.append({"_id": "g", "project_id": str(PID), "wa_group_id": "120363@g.us"})
    db.whatsapp_messages.docs.append({"_id": "m", "group_id": "120363@g.us", "sender": "17185550142",
                                      "sender_name": "jose  garcia",
                                      "body": "call me 718-555-0142 or jose@abc.com, floors 1-4 board done",
                                      "created_at": datetime(2026, 10, 1, 12, tzinfo=timezone.utc)})
    db.logbooks.docs.append({"_id": "l", "project_id": str(PID), "log_type": "daily_jobsite", "date": "2026-10-01",
                             "data": {"foreman": "Jose Garcia", "photo": "data:image/jpeg;base64,/9j/AAAA"}})
    return db


class ReadOnlyGuard(unittest.TestCase):
    def test_a_write_is_refused_and_counted(self):
        db = _db()
        guard = X.ReadOnlyDB(db)
        before = len(db.workers.docs)
        with self.assertRaises(X.WriteAttempted):
            _run(guard.workers.insert_one({"name": "x"}))
        with self.assertRaises(X.WriteAttempted):
            _run(guard["workers"].delete_many({}))
        with self.assertRaises(X.WriteAttempted):
            _run(guard.workers.update_one({}, {"$set": {"a": 1}}))
        self.assertEqual(len(guard.attempts), 3)
        self.assertEqual(len(db.workers.docs), before)
        self.assertEqual(db.workers.writes, [], "nothing reached the database")

    def test_every_write_method_name_is_refused(self):
        guard = X.ReadOnlyDB(_db())
        for name in ("insert_many", "replace_one", "update_many", "delete_one", "bulk_write", "find_one_and_update",
                     "find_one_and_delete", "find_one_and_replace", "create_index", "drop", "drop_index",
                     "rename", "some_future_method"):
            with self.assertRaises(X.WriteAttempted, msg=name):
                getattr(guard.workers, name)
        self.assertEqual(len(guard.attempts), 13)

    def test_aggregate_with_out_or_merge_is_refused_but_a_plain_pipeline_is_not(self):
        db = _db()
        db.workers.aggregate = lambda pipeline, *a, **k: ["cursor"]
        guard = X.ReadOnlyDB(db)
        for stage in ({"$out": "x"}, {"$merge": {"into": "x"}}):
            with self.assertRaises(X.WriteAttempted):
                guard.workers.aggregate([{"$match": {}}, stage])
        self.assertEqual(len(guard.attempts), 2)
        self.assertEqual(guard.workers.aggregate([{"$match": {}}, {"$count": "n"}]), ["cursor"])
        self.assertEqual(len(guard.attempts), 2)

    def test_reads_pass_and_the_export_attempts_no_write(self):
        db = _db()
        guard = X.ReadOnlyDB(db)
        bundle = _run(X.export(guard, "588"))
        self.assertEqual(guard.attempts, [])
        self.assertEqual([w for c in db._c.values() for w in c.writes], [])
        self.assertEqual(bundle["manifest"]["counts"]["checkins"], 1, "the other job's check-in is not exported")
        self.assertEqual(bundle["manifest"]["counts"]["workers"], 1)
        self.assertEqual(bundle["manifest"]["counts"]["whatsapp_messages"], 1, "found through the linked group")


class Pii(unittest.TestCase):
    def test_pseudonym_is_stable_across_collections_and_spelling(self):
        out = _run(X.export(X.ReadOnlyDB(_db()), "588"))
        a = out["workers"][0]["name"]
        b = out["checkins"][0]["worker_name"]
        c = out["whatsapp_messages"][0]["sender_name"]
        d = out["logbooks"][0]["data"]["foreman"]
        self.assertTrue(a.startswith("worker_"), a)
        self.assertEqual({a, b, c, d}, {a}, "one person, one label, wherever and however spelled")
        self.assertTrue("Garcia" not in json.dumps(out, default=str), "no real name in a name field")

    def test_a_second_person_is_a_second_label_and_a_second_run_repeats(self):
        p = X.Pseudonyms()
        self.assertNotEqual(p.label("A One"), p.label("B Two"))
        self.assertEqual(p.label("a   one"), p.label("A One"))
        runs = []
        for _ in range(2):
            out = _run(X.export(X.ReadOnlyDB(_db()), "588"))
            out["manifest"].pop("exported_at")
            runs.append(json.dumps(out, default=str, sort_keys=True))
        self.assertEqual(runs[0], runs[1])

    def test_phone_numbers_and_emails_are_masked_in_fields_and_in_text(self):
        out = _run(X.export(X.ReadOnlyDB(_db()), "588"))
        blob = json.dumps(out, default=str)
        for raw in ("5550142", "555-0142", "17185550142", "jose@abc.com"):
            self.assertTrue(raw not in blob, f"{raw} survived in the bundle")
        msg = out["whatsapp_messages"][0]
        self.assertTrue("floors 1-4 board done" in msg["body"], "the words stay")
        self.assertEqual(msg["sender"], "[phone ***0142]")

    def test_dates_amounts_and_short_numbers_are_not_masked(self):
        for text in ("2026-10-01 14:30", "3,500,000 sf", "job 421234567", "BIN 3012345", "1-4"):
            self.assertEqual(X.mask_text(text), text)

    def test_secrets_signatures_devices_and_images_never_leave(self):
        out = _run(X.export(X.ReadOnlyDB(_db()), "588"))
        dropped = out["manifest"]["dropped_keys"]
        out.pop("manifest")          # the manifest names the DROPPED KEYS; the data must not hold them
        blob = json.dumps(out, default=str)
        for raw in ("secret", "password_hash", "device_fingerprint", "1.2.3.4", "base64", "SST-123"):
            self.assertTrue(raw not in blob, f"{raw} survived in the bundle")
        self.assertIn("admin_password_hash", dropped)
        self.assertEqual(out["workers"][0]["trade"], "drywall", "role and trade are kept")
        self.assertEqual(out["workers"][0]["company"], "ABC Drywall", "a business name is kept")
        self.assertEqual(out["companies"][0]["name"], "Blueview Construction Inc")


class Resolution(unittest.TestCase):
    def test_an_ambiguous_selector_is_refused(self):
        db = _db()
        db.projects.docs.append({"_id": ObjectId(), "name": "588 Thomas Boyland Annex", "address": "x", "company_id": "c1"})
        with self.assertRaises(X.ProjectNotResolved) as ctx:
            _run(X.resolve_project(X.ReadOnlyDB(db), "588"))
        self.assertIn("2 projects", str(ctx.exception))

    def test_no_match_is_refused_and_an_id_resolves(self):
        guard = X.ReadOnlyDB(_db())
        with self.assertRaises(X.ProjectNotResolved):
            _run(X.resolve_project(guard, "nowhere"))
        with self.assertRaises(X.ProjectNotResolved):
            _run(X.resolve_project(guard, ""))
        self.assertEqual(_run(X.resolve_project(guard, str(PID)))["_id"], PID)

    def test_a_regex_character_in_the_selector_is_literal(self):
        with self.assertRaises(X.ProjectNotResolved):
            _run(X.resolve_project(X.ReadOnlyDB(_db()), ".*"))


class Bounds(unittest.TestCase):
    def test_over_max_refuses_the_whole_run(self):
        with self.assertRaises(X.TooManyDocuments) as ctx:
            _run(X.export(X.ReadOnlyDB(_db()), "588", max_docs=0))
        self.assertIn("--max", str(ctx.exception))

    def test_skip_and_window(self):
        out = _run(X.export(X.ReadOnlyDB(_db()), "588", skip=["logbooks"]))
        self.assertNotIn("logbooks", out)
        self.assertEqual(out["manifest"]["skipped"]["logbooks"], "--skip")
        out = _run(X.export(X.ReadOnlyDB(_db()), "588", since=__import__("datetime").date(2026, 11, 1)))
        self.assertEqual(out["manifest"]["counts"]["logbooks"], 0, "the October log is before --since")
        self.assertIn("plan_records", out["manifest"]["skipped"])

    def test_main_prints_zero_writes_and_exits_clean(self):
        import io
        import contextlib
        import tempfile

        class _Client(dict):
            def __init__(self, *_a, **_k):
                super().__init__()
                self.db = _db()

            def __getitem__(self, name):
                return self.db

            def close(self):
                pass
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d, patch.dict("os.environ", {"MONGO_URL": "x", "DB_NAME": "y"}), \
                patch("motor.motor_asyncio.AsyncIOMotorClient", _Client), contextlib.redirect_stdout(buf):
            code = X.main(["588", "--out", str(Path(d) / "b.json")])
            self.assertTrue((Path(d) / "b.json").exists())
        self.assertEqual(code, 0)
        self.assertIn("Writes attempted: 0", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
