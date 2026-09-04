"""GET /workers projects, and the (company_id, name) index exists.

THE FAILURE THIS PINS, from the production traceback:

    GET /api/workers HTTP/1.1" 500 Internal Server Error
    pymongo.errors.OperationFailure: Executor error during find command:
    blueview.workers :: caused by :: Sort exceeded memory limit of 33554432
    bytes, but did not opt in to external sorting.
    code 292, QueryExceededMemoryLimitNoDiskUseAllowed

Three things compounded: the sort is on `name`, which had no index, so it is a
BLOCKING in-memory sort; there was no projection, so whole documents loaded;
and a worker document carries `osha_card_image` as base64 — one photograph per
worker, added by every gate registration. `.limit(50)` does not help, because
Mongo sorts the whole matched set before taking the first fifty.

That made it DATA-DEPENDENT rather than request-dependent. It began when one
company's roster crossed the limit and then failed on every load, for every
admin on that company, on every device — while `/api/checkins` in the same
batch, on the same token, succeeded throughout because check-in rows carry no
images.

Two guarantees:

  PROJECTION — the list never fetches an image-bearing field. Asserted by
  NAME on the excluded fields rather than by counting the included ones, so
  adding a new lightweight column does not fail this test but adding
  `osha_card_image` back does.

  INDEX — (company_id, name), in that order. By ESR: `company_id` is the
  equality prefix, `name` satisfies the sort. `is_deleted: {"$ne": True}` is
  deliberately absent from the key — a $ne is not selective and placing it
  before `name` would break the ordering the sort depends on.

The projection is the half that matters most: the platform-operator path
queries with NO company_id, so the index cannot serve its sort either, and only
the smaller documents rescue it.
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


# Fields that carry, or can carry, a base64 payload on a worker document.
# A list row has no use for any of them; each is served by its own endpoint.
HEAVY_FIELDS = (
    "osha_card_image",
    "signature",
    "osha_data",
    "certifications",
    "safety_orientations",
)

# What the three callers of workersAPI.getAll() actually read off a row.
#   app/index.jsx            workers.length
#   app/checkin/index.jsx    name, _id/id
#   useWorkers.searchWorkers name, company, trade
CONSUMER_FIELDS = ("name", "company", "trade")


class TheListIsProjected(unittest.TestCase):

    def setUp(self):
        self.src = inspect.getsource(server.get_workers)

    def test_the_query_passes_a_projection(self):
        self.assertIn(
            "projection=", self.src,
            "GET /workers must project — an unprojected sort over documents "
            "carrying base64 card images is what returned 500",
        )

    def test_no_image_bearing_field_is_projected_in(self):
        """By name, so a new lightweight column does not trip this."""
        # Only look at the projection dict, not the whole function.
        m = re.search(r"WORKER_LIST_FIELDS\s*=\s*\{(.*?)\}", self.src, re.S)
        self.assertIsNotNone(m, "WORKER_LIST_FIELDS not found")
        body = m.group(1)
        for field in HEAVY_FIELDS:
            self.assertNotIn(
                field, body,
                f"{field!r} is back in the worker list projection — that is "
                f"the payload the 32MB sort limit was measuring",
            )

    def test_every_field_a_consumer_reads_is_projected(self):
        """Anything omitted that a screen reads becomes a blank on an admin page."""
        m = re.search(r"WORKER_LIST_FIELDS\s*=\s*\{(.*?)\}", self.src, re.S)
        body = m.group(1)
        for field in CONSUMER_FIELDS:
            self.assertIn(
                f'"{field}"', body,
                f"{field!r} is read by a list consumer but is not projected",
            )

    def test_the_sort_is_unchanged(self):
        """The fix must not quietly reorder what the admin sees."""
        self.assertIn('sort_field="name"', self.src)
        self.assertIn("sort_dir=1", self.src)

    def test_the_tenant_filter_is_still_unconditional(self):
        """The projection must not disturb the scoping fix that precedes it.

        A falsy company_id yields `_id: None` — an unsatisfiable filter, so the
        honest answer is an empty list with the same response shape. That is
        also why a scoping problem here can never produce the 500 this file is
        about: it produces empty, never error.
        """
        self.assertIn('query["_id"] = None', self.src)
        self.assertIn("is_platform_operator", self.src)


class TheSortHasAnIndex(unittest.TestCase):

    def setUp(self):
        self.src = inspect.getsource(server)

    def test_a_company_id_name_index_is_created(self):
        self.assertIn(
            'name="workers_by_company_name"', self.src,
            "the (company_id, name) index is missing — the sort blocks in "
            "memory without it",
        )

    def test_the_key_order_is_company_then_name(self):
        """ESR: equality prefix first, then the sort key."""
        m = re.search(
            r'keys=\[\("company_id", 1\), \("name", 1\)\],\s*\n\s*name="workers_by_company_name"',
            self.src,
        )
        self.assertIsNotNone(
            m,
            "expected keys=[('company_id', 1), ('name', 1)] in that order — "
            "reversing them stops the index serving a company-scoped sort",
        )

    def test_is_deleted_is_not_in_the_index_key(self):
        """A $ne before the sort key breaks the ordering the sort relies on."""
        m = re.search(
            # TEMPERED, NOT LAZY. `(.*?)` with re.S still starts at the LEFTMOST
            # `keys=[` in the file and stretches to this name, so an index declared
            # ABOVE this one lands inside the capture and its keys read as though
            # they were these. That is how a test about one index fails because an
            # unrelated index was added earlier in the file -- three times in this
            # repo now. The tempered form cannot cross another `keys=[`.
            r'keys=\[((?:(?!keys=\[)[\s\S])*?)\],\s*\n\s*name="workers_by_company_name"',
            self.src, re.S,
        )
        self.assertIsNotNone(m)
        self.assertNotIn("is_deleted", m.group(1))


if __name__ == "__main__":
    unittest.main()
