"""A sort no index can serve, on a collection that holds base64, is an outage.

TWICE IN ONE DAY, with no deploy to blame either time:

  * `GET /api/workers` sorted `workers` by `name` with nothing leading
    (company_id, name). Worker documents carry `osha_card_image` and
    `selfie_image` inline, the matched set crossed 32MB, and the endpoint
    started returning `OperationFailure ... Sort exceeded memory limit of
    33554432 bytes, but did not opt in to external sorting` (code 292).
  * `GET /api/logbooks/project/{id}/submitted` sorted `logbooks` by `date`
    under an equality match on (project_id, status). The closest index was
    (project_id, log_type, date) — `log_type` is not pinned by that filter, so
    it could not deliver `date` in order. It failed in front of a DOB
    inspector.

Neither had a code change to blame. Both were correct code that worked for
months and then stopped, because the only thing that changed was the number of
rows. NOTHING IN THIS REPO FAILED WHEN EITHER ONE BROKE, and nothing would have
failed the day before.

WHAT THIS TEST IS, AND IS NOT. It is a RATCHET, not a verdict, in the same
shape as test_reads_without_writers.py. The sweep reasons about index KEYS, not
about the plan Mongo actually chooses, and it cannot see an index someone
created by hand in the Atlas UI — deliberately, because such an index exists on
one cluster and in no environment anyone builds next. So the list below is
CANDIDATES. The property being enforced is narrow and worth having on its own:

    a new unserved sort on a base64-bearing collection cannot enter silently

Adding one fails here. Removing one fails here too, and that is deliberate: the
allowlist shrinking is the good outcome and should be recorded rather than
drift unnoticed.

WHEN THIS FAILS, do not reach for the allowlist first. Add the index. ESR:
equality fields first, then the sort field in the sort's direction, and
`$ne` predicates stay OUT of the key — a low-cardinality range key between the
equality prefix and the sort key destroys the ordering the sort needs. That
reasoning is written out on `workers_by_company_name` (server.py ~38452) and
every index this change added follows it.

An entry only belongs in the allowlist with a REASON that says why an index is
not the answer for that call.
"""

import os
import sys
import ast
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import find_unserved_sorts as sweep  # noqa: E402


def _key(row) -> tuple:
    """(collection, function, sort). Line numbers are not part of the key —
    server.py is 39k lines and moves constantly; a ratchet keyed on line
    numbers fails on every unrelated edit and is switched off within a week."""
    return (
        row["collection"],
        row["function"],
        ",".join(f"{f}:{d}" for f, d in row["sort"]),
    )


# Every unserved sort on a base64-bearing collection as of 2026-09-02, AFTER
# the indexes this change added. Each entry states why an index is not the
# answer, because an allowlist without reasons is just a suppression list.
    # EMPTY, AND THAT IS THE STATE TO DEFEND. Its one entry was
    # ("users", "get_admin_users", "name:1"), carrying the note "the actual fix
    # is a projection ... Remove this line when it lands." It landed:
    # get_admin_users now passes USER_LIST_FIELDS, an inclusion projection, so
    # the sort buffer holds a few hundred bytes per user instead of every CP's
    # cp_signature. The sweep reports AT RISK (none).
    #
    # An entry added here needs the same thing that one had: not "this is
    # known" but WHY an index is not the answer, and what is.
# `set()`, not `{}` -- an empty brace pair is a DICT, and `keys - {}` is a
# TypeError rather than a passing ratchet.
ALLOWLIST: set = set()



class TheRatchet(unittest.TestCase):
    def setUp(self):
        self.rows = sweep.unserved()
        self.keys = {_key(r) for r in self.rows}

    def test_no_new_unserved_sort_on_a_base64_collection(self):
        new = sorted(self.keys - ALLOWLIST)
        self.assertEqual(new, [], (
            "a sort on a collection that holds inline base64 has no index that "
            "can deliver it in order. This is the shape that returned 500 "
            "twice. Add the index (equality fields first, then the sort field, "
            f"$ne predicates excluded) before touching the allowlist: {new}"
        ))

    def test_the_allowlist_has_not_silently_shrunk(self):
        gone = sorted(ALLOWLIST - self.keys)
        self.assertEqual(gone, [], (
            "these are no longer reported — good, if an index or a projection "
            f"was added. Record it by removing the line: {gone}"
        ))


class TheSweepStillWorks(unittest.TestCase):
    """A ratchet that has quietly stopped detecting anything passes forever.

    These assert the MECHANISM rather than the findings. The failure they guard
    against is the sweep being broken by a refactor while the suite stays
    green — which is the same shape as everything else in this file.
    """

    def setUp(self):
        self.rows, self.skipped, self.python_sorts, self.agg = sweep.findings()
        self.by_where = {r["where"]: r for r in self.rows}

    def test_esr_is_enforced_not_bare_prefix_matching(self):
        """THE RULE THE SECOND OUTAGE BROKE, asserted directly.

        (project_id, log_type, date) looks like it covers a `date` sort under
        a project_id match, and it does not: `log_type` sits between the
        pinned key and the sort key, so the index cannot walk `date` in order.
        A sweep that matched on "the sort field appears in the index" would
        have called the failing endpoint healthy.
        """
        idx = [("project_id", 1), ("log_type", 1), ("date", -1)]
        sort = [("date", -1)]
        self.assertFalse(
            sweep.index_serves(idx, sort, {"project_id", "status"}),
            "log_type is unpinned, so this index cannot serve the sort",
        )
        self.assertTrue(
            sweep.index_serves(idx, sort, {"project_id", "log_type"}),
            "with log_type pinned by equality the same index does serve it",
        )

    def test_a_ne_predicate_does_not_pin_an_index_key(self):
        """`is_deleted: {"$ne": True}` reads like a filter and is not one."""
        eq, other, ok = sweep.filter_fields(
            __import__("ast").parse(
                '{"project_id": pid, "is_deleted": {"$ne": True}}'
            ).body[0].value
        )
        self.assertTrue(ok)
        self.assertEqual(eq, {"project_id"})
        self.assertEqual(other, {"is_deleted"})

    def test_it_knows_which_collections_carry_base64(self):
        """If this shrinks, findings stop being ranked and the outage-shaped
        ones sink into the slow-query noise."""
        b64 = sweep.base64_collections()
        for coll in ("workers", "logbooks", "users", "document_annotations"):
            self.assertIn(coll, b64, f"{coll} no longer detected as base64-bearing")

    def test_it_sees_base64_written_through_a_local_not_an_inline_dict(self):
        """`workers` is the collection of the FIRST outage and none of its
        base64 is written as an inline dict literal — worker_doc is built as a
        local and then inserted. Reading only literals classified it as
        carrying no base64, which would have hidden the case this exists for.
        """
        evidence = " ".join(sorted(sweep.base64_collections()["workers"]))
        self.assertIn("osha_card_image", evidence)

    def test_the_logbooks_incident_is_now_served(self):
        """GET /logbooks/project/{id}/submitted — the endpoint that failed in
        front of a DOB inspector. The index that rescued it was created by hand
        in Atlas with no deploy, so it existed on exactly one cluster; this
        asserts the repo now declares it. Deleting
        `logbooks_project_status_date` fails here."""
        hit = next((r for r in self.rows
                    if r["function"] == "get_submitted_logbooks"), None)
        self.assertIsNotNone(hit, "the endpoint's sort is no longer analysed")
        self.assertTrue(hit["served"], (
            "no declared index serves the sort that took this endpoint down. "
            f"equality={hit['equality']} sort={hit['sort']}"
        ))

    def test_the_workers_incident_reads_as_defused_by_its_projection(self):
        """GET /workers is still an unserved sort on the broad
        platform-operator call — what saves it is WORKER_LIST_FIELDS, an
        inclusion projection that keeps osha_card_image out of the sort. That
        projection is passed by NAME, so if projection resolution regresses
        this endpoint reappears as a finding and the real ones get lost in it.
        """
        hit = next((r for r in self.rows if r["function"] == "get_workers"), None)
        self.assertIsNotNone(hit, "GET /workers sort is no longer analysed")
        self.assertTrue(hit["base64_collection"])
        self.assertTrue(hit["defused_by_projection"], (
            "WORKER_LIST_FIELDS is no longer recognised as keeping base64 out "
            f"of the sort: projection={hit['projection']!r}"
        ))

    def test_an_exclusion_projection_is_not_treated_as_protection(self):
        """`{"password": 0}` hides one field and ships every other, base64
        included. Counting it as protection would clear an endpoint that is
        still one document away from a 500.

        ITS FIXTURE WAS THE BUG. This read the live `get_admin_users` row, so
        the moment that endpoint was fixed the test lost its specimen and
        failed -- not because the sweep regressed, but because the last example
        of the shape it checks for stopped existing. A check whose subject is
        production code stops working the day production is correct, which is
        the day you most want it still working.

        It is driven on a SYNTHETIC projection now. The rule survives having no
        live instance left, which is the whole point of a rule.
        """
        b64 = {"cp_signature"}
        verdict = sweep.projection_verdict(
            ast.parse('{"password": 0}', mode="eval").body, b64,
        )
        self.assertIn("base64 still carried", verdict)

        # And the positive half, so this cannot pass by rejecting everything.
        ok = sweep.projection_verdict(
            ast.parse('{"name": 1, "email": 1}', mode="eval").body, b64,
        )
        self.assertEqual(ok, "inclusion, base64 excluded")

        # An inclusion that names a blob is NOT protection either.
        leaky = sweep.projection_verdict(
            ast.parse('{"name": 1, "cp_signature": 1}', mode="eval").body, b64,
        )
        self.assertIn("still carries", leaky)

    def test_it_resolves_paginated_query_at_the_call_site(self):
        """The helper takes sort_field from its caller, so analysing the body
        would find one sort where there are ten. Its call sites must appear
        with the CALLER's sort field, not the helper's `created_at` default."""
        via_helper = [r for r in self.rows if "paginated_query" in r["source"]]
        self.assertGreaterEqual(len(via_helper), 8,
                                "paginated_query call sites are not being resolved")
        fields = {f for r in via_helper for f, _ in r["sort"]}
        self.assertTrue({"name", "date"} <= fields,
                        f"caller-chosen sort fields are being lost: {fields}")

    def test_nothing_is_skipped_except_the_one_documented_case(self):
        """A SWEEP THAT QUIETLY SKIPS IS HOW THIS CLASS SURVIVED. Every call it
        cannot parse must be visible; the only acceptable one is the
        paginated_query body itself, whose ten call sites are resolved instead.
        """
        unexpected = [s for s in self.skipped if "paginated_query" not in s]
        self.assertEqual(unexpected, [], (
            "the sweep can no longer read these sorts, so it is not covering "
            f"them. Teach it the shape rather than accepting the gap: {unexpected}"
        ))

    def test_it_still_covers_the_whole_surface(self):
        """A refactor that makes the sweep return two rows would pass every
        assertion above. This is the floor."""
        self.assertGreaterEqual(len(self.rows), 70,
                                "the sweep is analysing far fewer sorts than it did")
        self.assertGreaterEqual(self.agg, 10, (
            "aggregate $sort stages are no longer being counted — they are out "
            "of scope, but they must stay VISIBLE as out of scope"
        ))


if __name__ == "__main__":
    unittest.main()
