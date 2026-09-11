"""THE ALLOW-LIST WAS ENFORCED ON THE WAY OUT AND NOT ON THE WAY BACK.

An admin ticks Dropbox subfolders per project, and that selection IS applied --
on the file listing and on the manifest a tablet syncs from, both through one
shared helper so the rule cannot drift into two copies. (The subfolder route is
the admin PICKER: it reads the stored selection to draw the checkboxes and
filters no files.)
What he ticks is what a device DOWNLOADS. That belief was correct and this file
does not disturb it.

RETRIEVAL NEVER ASKED. Three routes:

  GET /projects/{id}/files/{file_id}/content   company match only, no project
                                               access at all
  GET /projects/{id}/dropbox-file-url          project access, no allow-list,
                                               and a CALLER-SUPPLIED path
  GET /projects/{id}/document-index-status     project access, no allow-list --
                                               and it hands out the file ids

Together they were a loop: the index named every PDF on the project with its
id, and the stream served any of them by id. The path route was wider still --
when no indexed record matched, it sent the caller's raw string to
`dropbox_api_call(company_id, ...)`, which authenticates with the COMPANY's
Dropbox token, so the reach was anything that connection could see, including
folders never indexed and belonging to no project.

── WHY THE FALLTHROUGH IS DELETED RATHER THAN VALIDATED ──────────────────────

Nothing legitimate used it. Every caller passes `file.path` from a listing this
server produced. All 26 project_files rows in production carry an `r2_key`, so
the listing gives each of them a proxy URL and the screens skip the call
entirely when a file has one; the five rows without a `dropbox_path` are direct
uploads whose listed path is the empty string, which never matched the lookup
either. A path that misses the lookup is by definition not a file of this
project, so 404 is the whole answer.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

_SRC = Path(server.__file__).read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)


def _fn(name):
    for n in ast.walk(_TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} is not defined in server.py")


def _route_of(name):
    return " ".join(ast.unparse(d) for d in _fn(name).decorator_list)


class TheRetrievalPredicate(unittest.TestCase):
    """Executed. A predicate is the only thing the three routes now share, so
    its decisions are asserted on real inputs rather than read."""

    PROJECT = {
        "dropbox_folder_path": "/588 plans",
        "site_device_subfolders": ["approved plans"],
    }
    DEVICE = {"role": "site_device", "site_mode": True, "project_id": "P1"}
    HUMAN = {"role": "admin", "company_id": "co_a"}

    def test_a_human_is_never_filtered(self):
        """The allow-list is a DEVICE rule. Filtering an admin by it would hide
        a project's own files from the person who ticked the folders."""
        for path in ("/588 plans/approved plans/A-101.pdf",
                     "/588 plans/contracts/rate sheet.pdf",
                     "/somewhere else/x.pdf", ""):
            self.assertTrue(
                server._site_device_may_retrieve(self.PROJECT, self.HUMAN, path),
                f"an admin was refused {path!r}")

    def test_a_device_reaches_inside_the_ticked_folder(self):
        self.assertTrue(server._site_device_may_retrieve(
            self.PROJECT, self.DEVICE, "/588 plans/approved plans/A-101.pdf"))

    def test_a_device_is_REFUSED_outside_it(self):
        """THE DEFECT. This is the file the index named and the stream served."""
        self.assertFalse(server._site_device_may_retrieve(
            self.PROJECT, self.DEVICE, "/588 plans/contracts/rate sheet.pdf"))

    def test_an_EMPTY_allow_list_means_NOTHING_not_everything(self):
        """Three of the five provisioned devices have no folder ticked. The
        default has to be closed, and 'no restriction set' reads like 'no
        restriction' -- so it is asserted rather than assumed."""
        project = {"dropbox_folder_path": "/588 plans", "site_device_subfolders": []}
        self.assertFalse(server._site_device_may_retrieve(
            project, self.DEVICE, "/588 plans/approved plans/A-101.pdf"))

    def test_a_missing_project_refuses_a_device_and_admits_a_human(self):
        """The routes pass `{}` when the lookup returns nothing. A device must
        not be admitted by the absence of the document that restricts it."""
        self.assertFalse(server._site_device_may_retrieve({}, self.DEVICE, "/x.pdf"))
        self.assertTrue(server._site_device_may_retrieve({}, self.HUMAN, "/x.pdf"))

    def test_role_and_site_mode_are_BOTH_read(self):
        """A session carries one or the other depending on how it was built."""
        for u in ({"role": "site_device"}, {"site_mode": True}):
            self.assertFalse(server._site_device_may_retrieve(
                self.PROJECT, u, "/588 plans/contracts/x.pdf"), f"{u} slipped")


class TheThreeRoutesAsk(unittest.TestCase):

    def test_the_stream_route_now_requires_project_access(self):
        """A device carries its project's company_id, so the company check
        passed for any project in that company. The project confinement was
        never applied here."""
        self.assertIn("require_project_access", _route_of("stream_project_file"))

    def test_the_stream_route_consults_the_allow_list(self):
        body = ast.unparse(_fn("stream_project_file"))
        self.assertTrue("_site_device_may_retrieve" in body,
                        "the stream serves a file without asking whether this "
                        "caller may have it")

    def test_the_index_filters_before_it_names_anything(self):
        body = ast.unparse(_fn("get_document_index_status"))
        self.assertTrue("_site_device_may_retrieve" in body,
                        "the index still names every PDF and its file id")

    def test_the_path_route_REQUIRES_an_indexed_record(self):
        body = ast.unparse(_fn("get_dropbox_file_url"))
        self.assertTrue("if not file_rec" in body,
                        "a path matching no record still falls through")

    def test_the_CALLERS_string_never_reaches_dropbox(self):
        """THE ONE THAT MATTERS. `dropbox_api_call` authenticates with the
        company's token, so whatever path reaches it is addressable across the
        whole connected account. It must be the STORED path, read back from the
        record, never the request parameter."""
        fn = _fn("get_dropbox_file_url")
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "dropbox_api_call"):
                sent = " ".join(ast.unparse(k.value) for k in node.keywords)
                self.assertNotIn("file_path", sent,
                                 "the caller's own string is sent to Dropbox")
                self.assertIn("stored_path", sent,
                              "the path sent to Dropbox is not read off the "
                              "record")
                return
        # Deleting the call entirely is also a correct fix; say so rather than
        # failing on an absence that means the hole is gone.
        self.assertNotIn("dropbox_api_call", ast.unparse(fn))


class TheListingHalfIsUNCHANGED(unittest.TestCase):
    """The useful half. A reader who sees 'the allow-list was bypassed' must
    not conclude it does nothing -- three listing paths enforced it before this
    change and still do."""

    def test_both_filtering_paths_still_apply_it(self):
        """TWO, not three. The first draft of this file said three and named
        `list_dropbox_subfolders` among them -- that route is the ADMIN PICKER:
        it reads the stored selection to draw the checkboxes and filters no
        files at all. The test caught the claim; the claim was mine."""
        for name in ("get_project_dropbox_files", "get_project_manifest"):
            # assertTrue, not assertIn: the container is a whole unparsed
            # function and assertIn prints it.
            self.assertTrue(
                "_path_is_under_allowed_subfolder" in ast.unparse(_fn(name)),
                f"{name} stopped filtering files by the allow-list")

    def test_the_picker_still_reads_the_stored_selection(self):
        self.assertTrue(
            "_normalize_subfolder_names" in ast.unparse(_fn("list_dropbox_subfolders")),
            "the admin picker no longer shows which folders are ticked")

    def test_the_underlying_rule_is_still_ONE_function(self):
        """Both halves reach the same helper. Two spellings is how they drift,
        which is the argument the listing side already makes in its own
        comment."""
        self.assertIn("_path_is_under_allowed_subfolder",
                      ast.unparse(_fn("_site_device_may_retrieve")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
