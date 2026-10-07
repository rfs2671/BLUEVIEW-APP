"""The 638 Lafayette hard-delete script: its guards and its selectors.

It is never run against a database here. What is tested is what decides
whether it may run and what it would touch."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from scripts import hard_delete_638_lafayette as h  # noqa: E402


class TheExecuteGuard(unittest.TestCase):

    def test_a_dry_run_needs_no_ids(self):
        self.assertIsNone(h.validate_execute_args(False, []))

    def test_execute_needs_both_ids_exactly(self):
        self.assertIsNotNone(h.validate_execute_args(True, []))
        self.assertIsNotNone(h.validate_execute_args(True, [h.TARGET_PROJECTS[0]]))
        self.assertIsNotNone(h.validate_execute_args(
            True, list(h.TARGET_PROJECTS) + ["69f90c3209947c4967c8074f"]))
        self.assertIsNone(h.validate_execute_args(True, list(h.TARGET_PROJECTS)))

    def test_the_legacy_flag_alone_is_refused(self):
        with self.assertRaises(SystemExit) as e:
            h.main(["--execute", "--project", h.TARGET_PROJECTS[0],
                    "--project", h.TARGET_PROJECTS[1]])
        self.assertEqual(e.exception.code, 2)

    def test_execute_without_mongo_is_a_bad_invocation(self):
        env = dict(os.environ)
        os.environ.pop("MONGO_URL", None)
        try:
            code = h.main(["--execute", "--project", h.TARGET_PROJECTS[0],
                           "--project", h.TARGET_PROJECTS[1], "--i-know",
                           "--reason", "r", "--session", "s"])
        finally:
            os.environ.clear()
            os.environ.update(env)
        self.assertEqual(code, h.BAD)


class WhatItWouldTouch(unittest.TestCase):

    def _sel(self, names=("checkins", "audit_logs", "users", "projects")):
        return h.build_selectors(
            project_ids=h.TARGET_PROJECTS, company_id=h.TARGET_COMPANY,
            file_ids=["f1"], logbook_ids=["l1"], renewal_ids=["r1"],
            wa_group=h.TARGET_WA_GROUP, group_doc_id=h.TARGET_GROUP_DOC,
            collection_names=names)

    def test_audit_logs_are_never_deleted(self):
        self.assertNotIn("audit_logs", {c for c, _, _ in self._sel()})

    def test_every_collection_gets_the_project_or_company_filter(self):
        generic = [f for c, f, why in self._sel() if c == "checkins"]
        self.assertEqual(len(generic), 1)
        ors = generic[0]["$or"]
        self.assertIn("project_id", ors[0])
        self.assertIn("company_id", ors[1])

    def test_ids_match_as_string_and_objectid(self):
        vals = h.any_id("project_id", [h.TARGET_PROJECTS[0]])["project_id"]["$in"]
        self.assertEqual(len(vals), 2)
        self.assertEqual(str(vals[1]), h.TARGET_PROJECTS[0])

    def test_the_rows_the_app_cascade_misses_are_covered(self):
        colls = {c for c, _, _ in self._sel()}
        for c in ("plan_records", "plan_index_jobs", "document_page_index",
                  "document_page_chunks", "logbook_thumbnails",
                  "report_number_counters", "system_config",
                  "whatsapp_pending_groups", "whatsapp_send_log",
                  "notification_log", "digest_queue", "filing_jobs"):
            self.assertIn(c, colls)

    def test_r2_keys_are_found_anywhere_in_a_row(self):
        keys = set()
        h.collect_r2_keys({"r2_key": "a/b.pdf", "data": {"activities": [
            {"photos": [{"original_r2_key": "lp/1.jpg", "thumb_r2_key": ""}]}]},
            "page_jpeg_r2_key": "plans/x/1.jpg", "other": "c"}, keys)
        self.assertEqual(keys, {"a/b.pdf", "lp/1.jpg", "plans/x/1.jpg"})


if __name__ == "__main__":
    unittest.main()
