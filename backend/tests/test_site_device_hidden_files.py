"""A ticked folder shows everything in it EXCEPT the files an admin switched off.

The operator asked to open a folder and switch single files on or off for the
gate tablet. The folder stays the unit of visibility; the hidden files are its
exceptions, stored on the project as `site_device_excluded_paths`, and every
site-device read applies them: the file list, the manifest the tablet syncs
from, and retrieval by path.
"""
import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

DEVICE = {"role": "site_device", "site_mode": True, "project_id": "p1"}
ADMIN = {"role": "admin", "company_id": "c1"}
PROJECT = {
    "dropbox_folder_path": "/588 plans",
    "site_device_subfolders": ["Architectural"],
    "site_device_excluded_paths": ["/588 plans/Architectural/A-101 OLD.pdf"],
}


class HiddenFiles(unittest.TestCase):
    def test_a_hidden_file_in_a_ticked_folder_is_refused_to_the_device(self):
        self.assertFalse(server._site_device_may_retrieve(
            PROJECT, DEVICE, "/588 plans/Architectural/A-101 OLD.pdf"))

    def test_the_match_ignores_case(self):
        self.assertFalse(server._site_device_may_retrieve(
            PROJECT, DEVICE, "/588 PLANS/architectural/a-101 old.pdf"))

    def test_the_rest_of_the_folder_is_still_shown(self):
        self.assertTrue(server._site_device_may_retrieve(
            PROJECT, DEVICE, "/588 plans/Architectural/A-102.pdf"))

    def test_people_are_not_affected(self):
        self.assertTrue(server._site_device_may_retrieve(
            PROJECT, ADMIN, "/588 plans/Architectural/A-101 OLD.pdf"))

    def test_no_exceptions_stored_means_none(self):
        self.assertEqual(server._site_excluded_paths({}), set())
        self.assertEqual(server._site_excluded_paths(
            {"site_device_excluded_paths": ["", None, " /A/B.pdf "]}), {"/a/b.pdf"})


if __name__ == "__main__":
    unittest.main()
