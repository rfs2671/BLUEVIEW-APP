"""THE ROLE WAS THE GATE, AND "owner" WALKED PAST IT.

Three report routes gated cross-company access on

    if role == "admin" and project.get("company_id") != current_user.get(...)

`role == "owner"` never reaches that comparison, and "owner" is not a rare
elevated role: `/auth/register` sets it on EVERY self-serve signup. So any
account that had merely registered could name another company's project id and
read its report preview, its send history and its submitted-log list.

── WHY test_tenant_scope_census DID NOT FIND THIS ──────────────────────────────

That census is SHAPE-SCOPED, not directory- or prefix-scoped, and its shape is
narrower than its subject. It matches

    if not (isinstance(node, ast.If) and isinstance(node.test, ast.Name))

-- an `if` whose test is a BARE IDENTIFIER, e.g. `if company_id:`. These three
express tenancy as `if <compare> and <compare>:`, an ast.BoolOp, which that
walk cannot see. Its own prose names the danger exactly -- "THE CARVE-OUT IS
THE FLAG, NEVER THE ROLE. `role == 'owner'` is what every self-serve signup
receives" -- and cites /admin/users as an instance. The knowledge was written
down; the detector could not reach it. §12 of docs/audits/check-harness.md.

SO THIS FILE IS A FAMILY GATE, NOT THREE ASSERTIONS. A fourth report route
added without the dependency fails here, which is the thing three hard-coded
names could not do.

AND IT LOOKS IN BOTH PLACES THE DEPENDENCY CAN LIVE. The first draft of this
check read only `fn.decorator_list` and reported three sibling routes as
ungated; all three carry `_proj = Depends(require_project_access)` in the
SIGNATURE instead. A gate that knows one spelling of the thing it requires
reports the other spelling as a violation -- the same shape-scoped mistake as
the census above, in the check written to cover for it.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from tests.source_text import code_of  # noqa: E402

_SRC = Path(server.__file__).read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)
#: Comments STRIPPED. The fix's own note quotes the line it removes, because a
#: correction that erases its subject leaves the next grep empty -- so a count
#: against the raw file would find the retraction and call it the defect.
_CODE = code_of("server.py")

_FAMILY = "/reports/project/{project_id}"


def _report_routes():
    """(name, guarded) for every route under the report family."""
    out = []
    for fn in ast.walk(_TREE):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        dec = " ".join(ast.unparse(d) for d in fn.decorator_list)
        if "api_router." not in dec or _FAMILY not in dec:
            continue
        sig = ast.unparse(fn.args)
        out.append((fn.name, "require_project_access" in dec
                    or "require_project_access" in sig))
    return out


class EveryReportRouteIsGated(unittest.TestCase):

    def test_the_walk_found_the_family(self):
        """The empty-set guard. A family of nothing passes every assertion
        below without examining a single route."""
        found = _report_routes()
        self.assertGreaterEqual(
            len(found), 6,
            f"only {len(found)} routes matched {_FAMILY} — the walk is broken, "
            "not the routes")
        names = {n for n, _ in found}
        for expected in ("get_report_preview", "get_report_history",
                         "get_submitted_logs"):
            self.assertIn(expected, names,
                          f"{expected} is no longer in the family this gate "
                          "covers")

    def test_every_one_of_them_requires_project_access(self):
        ungated = [n for n, ok in _report_routes() if not ok]
        self.assertEqual(
            ungated, [],
            "these report routes take a project id and never check whether the "
            f"caller may have it: {ungated}")


class TheRoleIsNoLongerTheGate(unittest.TestCase):

    def test_no_route_still_gates_tenancy_on_the_ADMIN_ROLE(self):
        """Counted on STRIPPED code: the fix quotes the line it deletes."""
        self.assertEqual(
            _CODE.count('role == "admin" and project.get("company_id")'), 0,
            "a route still lets an owner past the cross-company comparison")

    def test_the_correction_still_QUOTES_what_it_corrected(self):
        """The other half, and it is not decoration. An erased claim leaves the
        next grep empty, and empty reads as 'no such problem'."""
        self.assertIn('role == "admin" and project.get("company_id")', _SRC,
                      "the note no longer records the shape it removed")


class ThePredicateBehindTheGateRefusesAStranger(unittest.TestCase):
    """Executed, not read. A dependency is only worth what its predicate
    decides, so the decision itself is asserted on real inputs."""

    PROJECT = {"company_id": "COMPANY-A", "name": "588 Thomas"}

    def test_an_un_onboarded_owner_is_REFUSED(self):
        """THE DEFECT, as a fact about the predicate. `register` sets
        role=owner and company_id=None on every self-serve signup, so this is
        the ordinary state of a fresh account, not an edge case."""
        stranger = {"role": "owner", "company_id": None, "assigned_projects": []}
        self.assertFalse(
            server.project_access_ok(self.PROJECT, "P1", stranger),
            "a registered account with no company can still read another "
            "company's project")

    def test_an_owner_of_ANOTHER_company_is_REFUSED(self):
        other = {"role": "owner", "company_id": "COMPANY-B",
                 "assigned_projects": []}
        self.assertFalse(server.project_access_ok(self.PROJECT, "P1", other))

    def test_the_owner_of_THIS_company_is_admitted(self):
        """The other half. A gate that refuses everybody is not a gate."""
        mine = {"role": "owner", "company_id": "COMPANY-A",
                "assigned_projects": []}
        self.assertTrue(server.project_access_ok(self.PROJECT, "P1", mine))

    def test_an_ASSIGNED_user_is_admitted__this_is_the_widening(self):
        """NAMED, because the fix widens as well as closes and a silent
        widening is the worse half.

        The deleted line made company equality the whole rule for admins.
        `project_access_ok` also admits a user explicitly assigned to the
        project, deliberately, because historical assignments predate the
        same-company validation. These three routes now admit exactly whom
        every other project route admits -- which is the point of using the
        shared predicate rather than repairing a private one.
        """
        assigned = {"role": "admin", "company_id": "COMPANY-B",
                    "assigned_projects": ["P1"]}
        self.assertTrue(server.project_access_ok(self.PROJECT, "P1", assigned))

    def test_a_site_device_reaches_only_its_own_project(self):
        dev = {"role": "site_device", "site_mode": True, "project_id": "P1"}
        self.assertTrue(server.project_access_ok(self.PROJECT, "P1", dev))
        self.assertFalse(server.project_access_ok(self.PROJECT, "P2", dev))


if __name__ == "__main__":
    unittest.main(verbosity=2)
