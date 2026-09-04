"""THE SYNC ROUTES ARE GONE, AND THE PATTERN THAT MADE THEM DANGEROUS IS PINNED.

`POST /sync/pull`, `POST /sync/push`, `GET /sync/timestamp` were the server half
of a client removed on 2026-08-05 (e8bf3962). Nothing called them.

`sync_push` took `changes: dict` — UNTYPED — and ran `{"$set": record}` against
workers, projects, checkins, daily_logs and nfc_tags for any authenticated
caller in the company, a site_mode kiosk token included, with no push-side field
allowlist and a caller-supplied `updated_at` deciding last-write-wins. It could
write `certifications` (a fabricated OSHA_30 clears validate_worker_certifications,
whose MISSING_OSHA is the gate's only hard block), `is_deleted: false`, and
`company_id`.

THE ROUTE WAS THE INSTANCE. THE PATTERN IS THE DEFECT — a handler that accepts an
untyped dict body and persists it wholesale. `SetsAnUntypedBodyWholesale` below
holds the census so a second one cannot arrive unnoticed.
"""

import ast
import os
import re
import sys
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from tests.source_text import code_of  # noqa: E402

SRC = code_of("server.py")
RAW = open(os.path.join(BACKEND, "server.py"), encoding="utf-8").read()
TREE = ast.parse(RAW)
LINES = RAW.split("\n")

#: Read at module level, not inside a method: an assertNotIn haystack has to be
#: PROVABLY a string or the absence auditor cannot classify it, and an assertion
#: it cannot classify is one it does not audit.
QUEUE_SRC = open(
    os.path.join(os.path.dirname(BACKEND), "frontend", "src", "utils",
                 "offlineQueue.js"), encoding="utf-8",
).read()


def _routes_of(fn):
    out = []
    for d in fn.decorator_list:
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and d.func.attr in ("get", "post", "put", "patch", "delete")
                and d.args and isinstance(d.args[0], ast.Constant)):
            out.append((d.func.attr.upper(), d.args[0].value))
    return out


def _handlers():
    for fn in ast.walk(TREE):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            r = _routes_of(fn)
            if r:
                yield fn, r


class TheRoutesAreGone(unittest.TestCase):
    def test_no_sync_route_is_registered(self):
        for _fn, routes in _handlers():
            for method, path in routes:
                self.assertFalse(
                    path.startswith("/sync"),
                    f"{method} {path} is a sync route and should not exist",
                )

    def test_the_helpers_went_with_them(self):
        for name in ("def sanitize_for_watermelon(", "WATERMELON_COLUMNS = ",
                     "async def get_table_changes(",
                     "def serialize_sync_record("):
            self.assertNotIn(name, SRC)

    def test_the_request_models_went_too(self):
        """A model nothing constructs is the same debt as a route nothing calls."""
        self.assertNotIn("class SyncPushRequest(", SRC)
        self.assertNotIn("class SyncPullRequest(", SRC)


class SetsAnUntypedBodyWholesale(unittest.TestCase):
    """THE CENSUS, NOT THE ROUTE.

    A handler whose body parameter is annotated `dict` and which then persists
    that same object. One such handler remains, and it is named here so that a
    second one fails this test rather than arriving quietly.

    WHAT THIS DOES NOT CATCH, STATED SO NOBODY READS IT AS COVERAGE IT DOES NOT
    HAVE: it would NOT have caught `sync_push`. That handler's annotated
    parameter was `request: SyncPushRequest` -- a MODEL -- whose single field was
    `changes: dict`; the wholesale write was `{"$set": record}` on an element
    iterated out of it. So a typed wrapper around an untyped dict defeats this
    check completely, and that is exactly the shape that shipped.

    A broader scan -- every `{"$set": <bare name>}` in a route handler -- finds
    28 sites, most of them building the dict from a literal in the same
    function, which is the safe form. Separating the four that do not from the
    24 that do is a real piece of work and is NOT done here. This class holds
    the narrow shape only.
    """

    #: handler name -> why it is tolerated today
    KNOWN = {
        # Denylist rather than allowlist: pops id/_id/created_at/created_by and
        # -- with a comment reasoning about re-parenting -- project_id and
        # company_id, then $sets the rest. Authorised against the STORED
        # project id, so it is scoped to a caller who already has access to
        # that log. `is_deleted` and `is_locked` are NOT popped, which is a
        # real gap and a separate ruling; it is nothing like sync_push's
        # reach, which had no list at all and could write credentials.
        "update_daily_log": "denylist + project-scoped",
    }

    def _wholesale(self):
        found = {}
        for fn, routes in _handlers():
            seg = "\n".join(LINES[fn.lineno - 1:(fn.end_lineno or fn.lineno)])
            args = fn.args
            defaults = ([None] * (len(args.args) - len(args.defaults))
                        + list(args.defaults))
            for a, dflt in zip(args.args, defaults):
                if a.annotation is None:
                    continue
                ann = ast.unparse(a.annotation)
                if not re.fullmatch(r"(dict|Dict|Dict\[str,\s*Any\]|dict\[str,\s*Any\])", ann):
                    continue
                # a Depends()/Body() default is not a raw request body
                if (isinstance(dflt, ast.Call) and isinstance(dflt.func, ast.Name)
                        and dflt.func.id in ("Depends", "Body", "Query")):
                    continue
                if re.search(r'"\$set":\s*' + re.escape(a.arg) + r'\b', seg):
                    found[fn.name] = routes
        return found

    def test_exactly_the_known_handlers_do_this(self):
        found = self._wholesale()
        self.assertEqual(
            sorted(found), sorted(self.KNOWN),
            "A handler now persists an untyped dict body wholesale. That is the "
            "shape sync_push had. Add an allowlist, or add it here with the "
            "reason it is safe.\nfound: " + repr(found),
        )

    def test_the_count_is_asserted_not_inferred(self):
        """A census that only checks membership passes when it finds nothing at
        all -- the empty-set failure. Pin the number."""
        self.assertEqual(len(self._wholesale()), 1)

    def test_the_survivor_still_refuses_to_reparent(self):
        i = SRC.index("async def update_daily_log(")
        body = SRC[i:i + 2000]
        self.assertIn('update_data.pop("project_id", None)', body)
        self.assertIn('update_data.pop("company_id", None)', body)


class TheOfflinePathIsUntouched(unittest.TestCase):
    """Deleting these routes must not be able to break offline use, and the
    reason it cannot is that offline never went through them."""

    def test_the_queue_replays_ordinary_rest_endpoints(self):
        for ep in ("'/api/workers'", "'/api/projects'", "'/api/checkins'",
                   "'/api/daily-logs'"):
            self.assertIn(ep, QUEUE_SRC)

    def test_and_names_no_sync_endpoint(self):
        self.assertNotIn("/sync", QUEUE_SRC)


if __name__ == "__main__":
    unittest.main(verbosity=2)
