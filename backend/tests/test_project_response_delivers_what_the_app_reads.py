"""A FIELD THE APP READS MUST SURVIVE THE RESPONSE MODEL.

`GET /projects/{project_id}` carries response_model=ProjectResponse, and a
pydantic response model is an ALLOW-LIST: it silently drops every field it does
not declare. No error, no warning, no log line. The document has grown for
months; the model is hand-maintained.

WHAT THAT COST. dropbox_folder_path, dropbox_last_synced and dropbox_sync were
all written by the server and none were declared, so the endpoint reported every
project as having no Dropbox folder no matter what the database held.
Construction Plans renders its sync control as

    project?.dropbox_folder_path ? <Sync Dropbox> : <Link Dropbox Folder>

so the sync button was UNREACHABLE on every project that had ever been linked,
and Dropbox Settings showed a linked project as unlinked. The admin integrations
screen looked right only because it reads the LIST endpoint, which has no
response model -- two endpoints giving opposite answers about one project.

WHY THIS DIRECTION AND NOT THE OTHER. The obvious test is "every field written
to a project document must be declared". That test cannot be written honestly:

  1. Not every written field SHOULD be delivered. is_deleted,
     marked_for_deletion, marked_by, admin_id, created_by and updated_at are
     internal bookkeeping; declaring them would ship deletion state to every
     client. So it would need an exemption list of "fields that are deliberately
     private" -- hand-maintained, exactly like the model, which moves the
     maintenance rather than removing it.

  2. It would under-report and go green while wrong. Writes with computed keys
     are invisible to static analysis -- #252's own summary is written as
     f"dropbox_sync.{k}" inside a dict comprehension, so a scan of $set literals
     does not see it at all.

This asserts the direction that has no exemption problem and is the actual
defect: if a screen READS a field off a project it fetched from this endpoint,
the endpoint must deliver it.

    python -m pytest backend/tests/test_project_response_delivers_what_the_app_reads.py
"""

import os
import re
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
FRONTEND = BACKEND.parent / "frontend"
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402

# `<something>project<something>` . `field`  — the way every screen here reads a
# project. Deliberately case-tolerant so `projectData`, `cachedProject` and the
# bare `project` all match.
#
# THE PREFIX IS OPTIONAL, AND THAT IS NOT COSMETIC. The first version of this
# pattern required at least one character before "project", so the bare
# `project` variable -- the commonest one in the codebase -- never matched, and
# the sweep silently missed dropbox_folder_path, the very field that caused the
# outage. A pattern that quietly skips the common case is worse than no sweep.
READ = re.compile(r"\b([\w$]*[Pp]roject[\w$]*)\s*\??\.\s*([a-z_][a-z0-9_]*)\b")

# Receivers that are NOT a project document, excluded structurally rather than
# by blacklisting the member names they happen to use.
NOT_A_PROJECT = re.compile(
    r"^(projectsAPI"          # the API client: .create/.update/.delete
    r"|proj\w*Res"            # settleFetch envelope: .data/.error/.status
    r"|projects)$"            # the plural: an array, so .map/.length/.filter
)

# Read but never written to a project document anywhere in server.py. Declaring
# it would be a lie; the read is the head of an explicit fallback chain
# (projectData?.company -> user?.company_name -> user?.name) that works without
# it. Listed with the reason so it is a decision rather than an oversight.
KNOWN_DEAD_READS = {"company"}


def _sources():
    for pattern in ("app/**/*.jsx", "app/**/*.js", "src/**/*.jsx", "src/**/*.js"):
        for path in FRONTEND.glob(pattern):
            if ".test." in path.name:
                continue
            yield path


def _undeclared_reads():
    declared = set(server.ProjectResponse.model_fields)
    found = {}
    for path in _sources():
        src = path.read_text(encoding="utf-8", errors="replace")
        # Only files that actually fetch a project from THIS endpoint. A screen
        # reading a project out of the list endpoint is not constrained by the
        # model, and index.jsx legitimately reads first_poll_summary that way.
        if "projectsAPI.getById" not in src:
            continue
        for m in READ.finditer(src):
            receiver, field = m.group(1), m.group(2)
            if NOT_A_PROJECT.match(receiver):
                continue
            if field in declared or field in KNOWN_DEAD_READS:
                continue
            found.setdefault(field, set()).add(path.name)
    return found


class TheAppCanReadWhatItAsksFor(unittest.TestCase):

    def test_no_screen_reads_a_field_the_endpoint_strips(self):
        found = _undeclared_reads()
        self.assertEqual(
            {}, found,
            "these fields are read off a project fetched from "
            "GET /projects/{id}, which strips them silently:\n"
            + "\n".join(f"  {k} -- {sorted(v)}" for k, v in sorted(found.items())),
        )

    def test_the_three_dropbox_fields_are_declared(self):
        """Named individually as well as swept. The sweep is a pattern over
        source and could be defeated by an unusual variable name; these three
        caused a live outage and are pinned by name."""
        for field in ("dropbox_folder_path", "dropbox_last_synced", "dropbox_sync"):
            with self.subTest(field=field):
                self.assertIn(field, server.ProjectResponse.model_fields)

    def test_they_are_optional(self):
        """A required field would 500 every project written before it existed --
        the WorkerResponse incident, which is why this is asserted rather than
        assumed."""
        for field in ("dropbox_folder_path", "dropbox_last_synced", "dropbox_sync"):
            with self.subTest(field=field):
                self.assertFalse(server.ProjectResponse.model_fields[field].is_required())

    def test_a_project_with_no_dropbox_data_still_serialises(self):
        p = server.ProjectResponse(id="p1", name="588 Thomas")
        self.assertIsNone(p.dropbox_folder_path)
        self.assertIsNone(p.dropbox_sync)

    def test_a_linked_project_round_trips(self):
        p = server.ProjectResponse(
            id="p1", name="588 Thomas",
            dropbox_folder_path="/588 plans",
            dropbox_sync={"status": "complete", "expected": 15,
                          "synced": 15, "failed": 0},
        )
        self.assertEqual(p.dropbox_folder_path, "/588 plans")
        self.assertEqual(p.dropbox_sync["synced"], 15)

    def test_the_dead_fields_are_still_declared_but_nothing_reads_them_now(self):
        """dropbox_enabled and dropbox_folder are dead on both sides now.

        They were always dead as DATA -- create_project writes false and null
        once and nothing writes either again. What kept them in the model was
        that screens still READ them: project/[id].jsx gated its whole Dropbox
        block on `dropbox_enabled && dropbox_folder`, and documents.jsx
        filtered its project list on the same pair, which is why that screen
        was empty for every user on every project. The redesign deleted the
        block and repointed the filter, so the last reader is gone.

        They stay declared because removing them is a server.py change and the
        frontend half shipped first. This assertion is now the pin for that
        removal rather than for their retention: when the backend half lands,
        this test is what it deletes."""
        self.assertIn("dropbox_enabled", server.ProjectResponse.model_fields)
        self.assertIn("dropbox_folder", server.ProjectResponse.model_fields)

    def test_no_screen_reads_the_dead_fields_any_more(self):
        """The half of the above that is enforceable today.

        A field nothing writes, read by a screen, is a control that renders
        its empty state for ever -- and, on project/[id].jsx, a Disconnect
        button that could never fire while still holding a live root-link
        trap behind it.
        """
        pattern = re.compile(r"[?.]\s*(dropbox_enabled|dropbox_folder)(?![_a-zA-Z])")
        # COMMENTS ARE STRIPPED FIRST, not filtered line by line. The screens
        # now carry multi-line explanations of why these fields are dead, and
        # those explanations name them -- a per-line "starts with //" test
        # passes the opening line of such a block and then trips on its
        # continuation lines.
        block = re.compile(r"/\*.*?\*/", re.S)
        line_comment = re.compile(r"^\s*//.*$", re.M)
        blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))

        offenders = []
        for path in _sources():
            raw = path.read_text(encoding="utf-8", errors="replace")
            # Blanked, not deleted, so offsets stay true to the file and the
            # reported line is the real one.
            src = line_comment.sub(blank, block.sub(blank, raw))
            for m in pattern.finditer(src):
                nl = raw.rfind("\n", 0, m.start()) + 1
                end = raw.find("\n", m.start())
                line = raw[nl:end if end != -1 else len(raw)]
                offenders.append("%s: %s" % (path.name, line.strip()[:90]))
        self.assertEqual(
            offenders, [],
            "a screen still reads a field nothing writes:\n" + "\n".join(offenders),
        )


class TheSweepItselfWorks(unittest.TestCase):
    """A sweep that matches nothing passes for the wrong reason."""

    def test_it_looks_at_the_screens_that_matter(self):
        files = [p for p in _sources()
                 if "projectsAPI.getById" in p.read_text(encoding="utf-8", errors="replace")]
        self.assertGreaterEqual(len(files), 5, "the getById sweep found almost nothing")
        names = {p.name for p in files}
        # ONE screen owns the Dropbox tree now. construction-plans.jsx and
        # dropbox-settings.jsx were plans and documents split across two
        # screens for one field; both are files.jsx.
        self.assertIn("files.jsx", names)
        self.assertNotIn("dropbox-settings.jsx", names)
        self.assertNotIn("construction-plans.jsx", names)

    def test_the_pattern_matches_a_bare_project_variable(self):
        """The regression that made the first version of this file useless."""
        m = READ.search("if (project?.dropbox_folder_path) {")
        self.assertIsNotNone(m, "the bare `project` receiver is not matched")
        self.assertEqual(m.group(1), "project")
        self.assertEqual(m.group(2), "dropbox_folder_path")

    def test_the_pattern_matches_the_other_receiver_shapes(self):
        for text, var, field in (
            ("projectData?.dropbox_folder_path", "projectData", "dropbox_folder_path"),
            ("cachedProject?.dropbox_last_synced", "cachedProject", "dropbox_last_synced"),
            ("effectiveProject?.dropbox_sync", "effectiveProject", "dropbox_sync"),
        ):
            with self.subTest(text=text):
                m = READ.search(text)
                self.assertIsNotNone(m)
                self.assertEqual((m.group(1), m.group(2)), (var, field))

    def test_non_project_receivers_are_excluded(self):
        for receiver in ("projectsAPI", "projectRes", "projRes", "projects"):
            with self.subTest(receiver=receiver):
                self.assertTrue(NOT_A_PROJECT.match(receiver))

    def test_a_real_project_receiver_is_NOT_excluded(self):
        for receiver in ("project", "projectData", "cachedProject", "effectiveProject"):
            with self.subTest(receiver=receiver):
                self.assertFalse(NOT_A_PROJECT.match(receiver))


if __name__ == "__main__":
    unittest.main(verbosity=2)
