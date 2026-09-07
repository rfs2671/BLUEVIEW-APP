"""EVERY QUERY GET /workers CAN ISSUE HAS AN INDEX THAT SERVES ITS SORT.

`get_workers` returned 500 for the platform operator from 2026-09-03:

    OperationFailure: Executor error during find command: blueview.workers ::
    caused by :: Sort exceeded memory limit of 33554432 bytes, but did not opt
    in to external sorting.

THE SAME ERROR CLOSED ON 2026-09-01, AND THE FIX'S OWN COMMENT IS WHY IT CAME
BACK. It said:

    NOT A COMPLETE FIX ON ITS OWN. The platform-operator path queries with no
    company_id at all, so this index cannot serve that sort either. WHAT
    RESCUES THAT PATH IS THE PROJECTION -- with the images gone the sort fits
    in memory regardless of whether an index is used.

The clause in capitals is false, and the plan says so. Against production:

    stages: ['PROJECTION_SIMPLE', 'SORT', 'COLLSCAN']

PROJECTION_SIMPLE sits ABOVE SORT. Mongo sorts WHOLE DOCUMENTS and projects the
fifty that survive, so the images leave the RESPONSE and never leave the SORT.
The operator's path was never fixed; it merely stopped failing, because the
collection was under 32MB that week. It crossed back on 2026-09-03 11:45:01 --
measured by walking the rows in `updated_at` order and accumulating BSON size --
and every load by the operator has 500'd since.

    61 workers, 51,736,644 bytes, 848KB average
    osha_card_image  37.8 MB      selfie_image  12.9 MB

NOTHING IN THE CODE REINTRODUCED IT. Not the tenant-scope guards -- the
operator is the `is_platform_operator` carve-out, so neither branch of that
`if/elif` touches his query and its shape is unchanged. Not #446's roster work,
which added a different endpoint. Not the projection, which is still there and
still correct. THE DATA GREW, and the one path that was never index-served
started failing again. Sentry attributes a regression to the release it is SEEN
on, which is why it points at a commit containing one test file and a comment.

── WHAT THIS FILE ASSERTS, AND WHAT IT CANNOT ──────────────────────────────

It asserts the DECLARATIONS: that both query shapes have an index whose key
provides the sort order, and that the false sentence is gone. It cannot run
`explain()` -- there is no Mongo in CI -- so the plan itself was verified by
hand against production before this shipped, and must be verified again after
deploy. That limitation is stated rather than papered over with a test that
looks like a plan check and is a source grep.
"""

from __future__ import annotations

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

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")


def _index_block() -> str:
    """The startup routine's workers indexes."""
    i = _SRC.index('name="workers_active_by_company"')
    j = _SRC.index("db.checkins.create_index", i)
    return _SRC[i:j]


def _get_workers() -> str:
    i = _SRC.index("async def get_workers(")
    j = _SRC.index("\n# POST /workers/register IS DELETED", i)
    return _SRC[i:j]


class BothQueryShapesHaveAnIndex(unittest.TestCase):
    """GET /workers issues exactly two shapes, decided by the tenant branch.

        company_id truthy   -> {is_deleted, company_id}, sort name
        platform operator   -> {is_deleted},             sort name
        anyone else         -> {_id: None}, unsatisfiable, sorts nothing

    The third needs no index: an unsatisfiable filter matches zero documents,
    so there is nothing to sort.
    """

    def test_the_company_scoped_sort_has_its_index(self):
        block = _index_block()
        self.assertIn('name="workers_by_company_name"', block)
        self.assertIn('keys=[("company_id", 1), ("name", 1)]', block)

    def test_the_UNSCOPED_sort_has_one_too(self):
        """THE ONE THAT WAS MISSING. `(company_id, name)` provides ordering on
        `name` only once `company_id` is pinned by equality, so it cannot serve
        a query that does not mention company_id at all."""
        block = _index_block()
        self.assertIn('name="workers_by_name"', block)
        self.assertIn('keys=[("name", 1)]', block)

    def test_the_unscoped_index_is_NOT_partial(self):
        """A partial index on `is_deleted: {$eq: False}` cannot serve this
        query. The filter is `$ne: True`, which MATCHES DOCUMENTS WITH NO
        is_deleted FIELD, and such an index excludes exactly those -- so it
        would silently omit rows the query wants, which is worse than no index.
        """
        block = _index_block()
        i = block.index('keys=[("name", 1)]')
        j = block.index(")", block.index('name="workers_by_name"'))
        self.assertNotIn("partialFilterExpression", block[i:j])

    def test_the_sort_field_is_still_name(self):
        """The indexes above are worth nothing if the endpoint sorts on
        something else. This is the link between the two."""
        self.assertIn('sort_field="name"', _get_workers())

    def test_and_the_tenant_branch_still_has_the_three_shapes(self):
        """If the operator carve-out disappeared, the unscoped shape would stop
        existing and `workers_by_name` would become dead weight -- but silently.
        """
        code = _get_workers()
        self.assertIn('query["company_id"] = company_id', code)
        self.assertIn("elif not is_platform_operator(current_user)", code)
        self.assertIn('query["_id"] = None', code)


class TheFalseClaimIsGone(unittest.TestCase):
    """§8. Prose asserting a relationship, sitting where the next reader will
    trust it, with nothing that fails when the relationship stops holding. This
    one never held, and it is the reason the index was not added the first
    time."""

    def test_nothing_claims_the_projection_rescues_the_operator_path(self):
        """A CORRECTION MARKER, NOT A BAN -- AND THIS IS THE FOURTH TIME THAT
        DISTINCTION HAS BITTEN IN THIS CODEBASE.

        The first draft asserted the phrase "the sort fits in memory
        regardless" was ABSENT, and failed -- because the correction QUOTES the
        false sentence in order to retract it, which is the right thing for the
        correction to do. A reader who greps the claim they half-remember must
        land on the retraction, not on nothing: an empty grep reads as "no such
        problem" rather than "already handled".

        Same resolution as test_ledger_reach_is_stated_correctly.py and
        test_superintendent_model_parity.py. The question is whether an
        occurrence is MARKED AS RETRACTED, not whether it occurs.

        AND THE MESSAGE IS SHORT ON PURPOSE. The first draft's assertNotIn
        printed the whole 2.2MB of server.py on failure. A gate whose output
        has to be scrolled past is one the reader learns to skim.
        """
        markers = ("was false", "used to follow was false", "IT NEVER DID",
                   "THE PLAN SAYS OTHERWISE", "it said")
        flat = _SRC.replace("\n    #", "").replace("\n#", "")
        for m in re.finditer(re.escape("the sort fits in memory regardless"),
                             flat):
            window = flat[max(0, m.start() - 900):m.start() + 200]
            self.assertTrue(
                any(k in window for k in markers),
                "an UNRETRACTED claim that the projection rescues the "
                f"platform-operator sort remains near offset {m.start()}")

    def test_and_the_correction_names_the_plan(self):
        """A correction that merely deleted the sentence would leave the next
        reader to re-derive it, and they would reach the same wrong answer --
        the projection IS there and the images ARE gone from the response."""
        block = _index_block()
        self.assertIn("PROJECTION_SIMPLE", block)
        self.assertIn("SORT", block)
        self.assertIn("COLLSCAN", block)

    def test_the_correction_is_at_BOTH_sites(self):
        """The claim was made twice -- in the index declaration and in the
        endpoint's own comment. Correcting one would leave the other standing
        for the next reader who starts from the endpoint.

        `assertTrue` WITH A SHORT MESSAGE, not `assertIn`: the haystack is the
        whole 4KB function and printing it on failure buries the one line that
        matters."""
        self.assertTrue(
            "PROJECTION_SIMPLE" in _get_workers(),
            "get_workers still explains the 500 without saying the projection "
            "sits ABOVE the sort")

    def test_the_projection_is_kept_and_said_to_be_kept(self):
        """The correction must not read as "the projection was pointless". It
        is what stops a 51MB collection being serialised into a response; it is
        simply not what makes the sort possible."""
        code = _get_workers()
        self.assertTrue("projection=WORKER_LIST_FIELDS" in code,
                        "the projection was removed along with the false "
                        "claim about it")
        self.assertTrue("THE PROJECTION STAYS" in code,
                        "the correction does not say the projection is kept, "
                        "so the next reader may take it for dead weight")


class TheLimitOfThisFileIsStated(unittest.TestCase):
    """A test that LOOKS like a plan check and is a source grep is worse than
    no test: the next reader believes the plan is guarded."""

    def test_this_file_says_it_cannot_check_the_plan(self):
        """WHITESPACE-NORMALISED, because the first draft failed on a LINE
        WRAP: the docstring reads "It cannot run\\n`explain()`" and the literal
        it looked for was contiguous. An assertion about PROSE must not depend
        on where the paragraph happened to break -- reflowing a comment is not
        a change of meaning, and a check that says otherwise fails for a reason
        that teaches the next reader nothing."""
        doc = " ".join((sys.modules[__name__].__doc__ or "").split())
        self.assertIn("cannot run `explain()`", doc)
        self.assertIn("must be verified again after deploy", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
