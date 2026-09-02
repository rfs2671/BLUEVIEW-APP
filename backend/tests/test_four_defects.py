"""Two backend halves of the four-defect batch.

E2 — THE SCOPE GATE WAS WRITTEN OUT FOUR TIMES AND REPOINTED ONCE.

#338 introduced `ROLES_SCOPED_TO_ASSIGNED_PROJECTS = ("cp", ROLE_SUPERINTENDENT)`
and pointed `create_logbook` at it. Three sibling gates in the same file were
already spelled `role == "cp"` and were not repointed, so a superintendent
could not CREATE a logbook on a project he was not assigned to and could still
UPDATE, AMEND and FINALIZE one there. Finalize is the sharp one: it is the act
that freezes a compliance record.

The constant's own comment says two rules that happen to coincide are still two
rules. The corollary is the one that bit: one rule written out four times will
drift, and it drifted at the three sites nobody edited.

C3 — `cp_name` HAD NO VALIDATION AT ANY LAYER.

Bare `Optional[str]`; no strip, no length, and neither the submit gate nor
finalize ever looked at it. The client's only bar is `signerName?.trim()`. So
"2" reached 25 signed documents and printed as the named Competent Person on
the per-logbook DOB PDF, the combined daily report, the emailed compliance
report, and as the CS-attribution fallback on the superintendent log.

The amplifier is the profile: the pad's field is bound to shared CP state and
saving persists it to `db.users.cp_name`, so one bad save becomes the signer's
default identity across all thirteen log types. That is why the profile write
is gated too — the submit gates only stop each individual filing, never the
spread.

The predicate is deliberately minimal and must stay so. A stricter rule refuses
a real person at the moment he is trying to sign, which is worse than the
defect it prevents.
"""

from __future__ import annotations

import inspect
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


class TheScopeGateIsOneRule(unittest.TestCase):
    """Asserted per FUNCTION, so a gate added later cannot quietly use a bare
    role string the way these three did."""

    GATED = ("create_logbook", "update_logbook", "amend_logbook", "finalize_logbook")

    def test_the_constant_admits_both_roles(self):
        self.assertIn("cp", server.ROLES_SCOPED_TO_ASSIGNED_PROJECTS)
        self.assertIn(
            server.ROLE_SUPERINTENDENT, server.ROLES_SCOPED_TO_ASSIGNED_PROJECTS
        )

    def test_every_write_gate_uses_the_constant(self):
        for name in self.GATED:
            src = inspect.getsource(getattr(server, name))
            self.assertIn(
                "ROLES_SCOPED_TO_ASSIGNED_PROJECTS", src,
                f"{name} does not use the shared scope constant",
            )

    def test_no_write_gate_tests_a_bare_cp_string(self):
        """The exact shape that drifted. Comments are stripped first — the new
        ones quote the old predicate to explain why it went."""
        block = re.compile(r"/\*.*?\*/", re.S)
        for name in self.GATED:
            src = inspect.getsource(getattr(server, name))
            code = re.sub(r"^\s*#.*$", "", src, flags=re.M)
            self.assertNotRegex(
                code, r'role"?\)?\s*==\s*"cp"',
                f"{name} still compares role to a bare \"cp\"",
            )

    def test_finalize_is_gated_at_all(self):
        """The sharpest instance — freezing a record on an unassigned project."""
        src = inspect.getsource(server.finalize_logbook)
        self.assertIn("assigned_projects", src)
        self.assertIn("Not assigned to this project", src)


class ACpNameHasToLookLikeAName(unittest.TestCase):

    def test_an_absent_name_is_not_refused_by_the_submit_gate(self):
        """SCOPE, stated as a test. The reported defect is that any non-blank
        string was accepted; absence is a DIFFERENT defect (it prints a blank
        CP on the same PDFs) and refusing it at submit would block a CP in the
        field on drafts created before this gate. It is left open deliberately.
        """
        for name in ("create_logbook", "update_logbook"):
            src = inspect.getsource(getattr(server, name))
            at = src.index("SUBMIT_INVALID_CP_NAME")
            guard = src[max(0, at - 400):at]
            self.assertIn(
                '.strip() and not _cp_name_looks_like_a_name', guard,
                f"{name} refuses an ABSENT name — that is wider than the "
                f"defect this change is for",
            )

    def test_it_refuses_what_reached_production(self):
        for bad in ("2", "", "   ", ".", "x", "1234", "-", "7.", None):
            self.assertFalse(
                server._cp_name_looks_like_a_name(bad),
                f"{bad!r} should not pass as a signer's name",
            )

    def test_it_admits_real_names(self):
        """Including short, accented, hyphenated and initialled ones. A rule
        that refuses these refuses a man at the moment he is trying to sign."""
        for good in (
            "Bo", "Al Ray", "J. O'Neill", "Maria-Jose", "María-José",
            "Nguyen Van A", "Michael Fishman", "O'Brien", "李 Wei",
        ):
            self.assertTrue(
                server._cp_name_looks_like_a_name(good),
                f"{good!r} is a real name and must pass",
            )

    def test_leading_and_trailing_space_is_not_a_name(self):
        self.assertFalse(server._cp_name_looks_like_a_name("  2  "))
        self.assertTrue(server._cp_name_looks_like_a_name("  Bo  "))

    def test_the_submit_gates_call_it(self):
        for name in ("create_logbook", "update_logbook"):
            src = inspect.getsource(getattr(server, name))
            self.assertIn(
                "_cp_name_looks_like_a_name", src,
                f"{name} does not gate the name that will print",
            )
            self.assertIn("SUBMIT_INVALID_CP_NAME", src)

    def test_the_profile_write_calls_it_too(self):
        """The amplifier. Without this, one bad save re-seeds every later log."""
        src = inspect.getsource(server.update_cp_profile)
        self.assertIn("_cp_name_looks_like_a_name", src)
        self.assertIn("INVALID_CP_NAME", src)

    def test_the_gate_is_only_on_submit(self):
        """A draft may hold anything. This refuses the FILING, not the typing."""
        src = inspect.getsource(server.create_logbook)
        at = src.index("_cp_name_looks_like_a_name")
        before = src[:at]
        self.assertIn('== "submitted"', before,
                      "the name gate must sit inside the submit branch")

    def test_the_name_gate_follows_the_signature_gate(self):
        """An unsigned submit is not a submit; that condition is reported first
        so the CP is not made to sign and then refused for a second reason."""
        for name in ("create_logbook", "update_logbook"):
            src = inspect.getsource(getattr(server, name))
            self.assertLess(
                src.index("SUBMIT_MISSING_CP_SIGNATURE"),
                src.index("SUBMIT_INVALID_CP_NAME"),
                f"{name} refuses the name before the missing signature",
            )


if __name__ == "__main__":
    unittest.main()
