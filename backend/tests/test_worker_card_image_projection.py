"""F4 — `osha_card_image` is base64 on the worker document, so a multi-worker
read that does not project it out ships a photograph per worker into process
memory.

THIS IS THE SAME DEFECT GET /workers ALREADY FIXED, and the fix stopped at the
one endpoint that had produced a 500:

    pymongo.errors.OperationFailure: Sort exceeded memory limit of 33554432
    bytes

`WORKER_LIST_FIELDS` (server.py, get_workers) is the pattern. Every OTHER place
that reads MANY worker documents — the expiring-cert scan (5000 docs), the
nightly cert cron (an unbounded cursor over the collection), the three check-in
list endpoints' name backfill, the assistant's roster listing, the mention
search, the LL196 attestation roster, and the risk score's SST count — read
whole documents, base64 photographs included, and none of them returns the
image to anybody.

ONE READER LEGITIMATELY NEEDS IT and is allowlisted below:
`get_flagged_project_checkins` attaches the card inline so the CP reviewing a
flagged check-in can see the card he is judging (frontend/app/logbooks/
review.jsx renders it). That list is capped at 50 rows for exactly that reason.

THE AST SCAN IS THE DURABLE HALF. A behavioural test on one endpoint proves
today's fix; the scan is what makes a NEW `db.workers.find(...)` that forgets
the projection fail here rather than in production on the first tenant whose
roster crosses the sort limit.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

CARD_FIELD = "osha_card_image"

# The modules that read worker documents. lib/ cannot import server (server
# imports lib), which is why the projection constant lives under lib/ and is
# imported upward — the same arrangement, and for the same reason, as
# lib/cert_vocab.py.
_SCANNED = (
    _BACKEND / "server.py",
    _BACKEND / "lib" / "logbook" / "ll196.py",
    _BACKEND / "lib" / "statistical_engine" / "score.py",
)

# Functions permitted to read the card image out of a MULTI-worker query.
# One entry, and it is the review queue: the reviewer is looking at the card.
_IMAGE_ALLOWED = {"get_flagged_project_checkins"}

# Names that, used as a projection, are known to exclude the card image. The
# scan cannot evaluate a Name, so the ones it accepts are enumerated here and
# each is asserted to actually exclude the field by test_named_projections.
_SAFE_PROJECTION_NAMES = {"WORKER_NO_CARD_IMAGE"}


def _worker_find_calls(path: Path):
    """Every `<something>.workers.find(...)` call, with its enclosing def.

    Yields (function_name, lineno, projection_node_or_None).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []

    def walk(node, fname):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, child.name)
                continue
            if isinstance(child, ast.Call):
                f = child.func
                if (
                    isinstance(f, ast.Attribute)
                    and f.attr == "find"
                    and isinstance(f.value, ast.Attribute)
                    and f.value.attr == "workers"
                ):
                    proj = None
                    if len(child.args) >= 2:
                        proj = child.args[1]
                    for kw in child.keywords:
                        if kw.arg in ("projection", "fields"):
                            proj = kw.value
                    out.append((fname, child.lineno, proj))
            walk(child, fname)

    walk(tree, "<module>")
    return out


def _projection_excludes_card(node) -> bool:
    """True when this projection node provably keeps the card image out."""
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id in _SAFE_PROJECTION_NAMES
    if isinstance(node, ast.Dict):
        keys = [
            k.value for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        ]
        if not keys:
            return False
        # Exclusion projection: the field is named with a 0.
        for k, v in zip(node.keys, node.values):
            if (
                isinstance(k, ast.Constant)
                and k.value == CARD_FIELD
                and isinstance(v, ast.Constant)
                and v.value in (0, False)
            ):
                return True
        # Inclusion projection: the field is simply not among the keys.
        return CARD_FIELD not in keys
    return False


class WorkerFindProjections(unittest.TestCase):
    """No multi-worker read loads the base64 card image it never returns."""

    def test_every_workers_find_projects_the_card_image_out(self):
        offenders = []
        for path in _SCANNED:
            for fname, lineno, proj in _worker_find_calls(path):
                if fname in _IMAGE_ALLOWED:
                    continue
                if not _projection_excludes_card(proj):
                    offenders.append(
                        f"{path.relative_to(_BACKEND).as_posix()}:{lineno} "
                        f"in {fname}()"
                    )
        self.assertEqual(
            offenders, [],
            "these worker reads pull osha_card_image (base64) out of Mongo and "
            "never return it:\n  " + "\n  ".join(offenders),
        )

    def test_named_projections_really_exclude_it(self):
        """The names the scan trusts are checked, not taken on faith."""
        from lib.worker_projection import WORKER_NO_CARD_IMAGE
        self.assertEqual(WORKER_NO_CARD_IMAGE.get(CARD_FIELD), 0)
        self.assertEqual(
            set(WORKER_NO_CARD_IMAGE.values()), {0},
            "an exclusion projection may not mix in inclusions — Mongo "
            "rejects the mixed form",
        )

    def test_worker_list_fields_still_omits_it(self):
        """Regression guard on the fix that already shipped (get_workers)."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        block = src.split("WORKER_LIST_FIELDS = {", 1)[1].split("}", 1)[0]
        self.assertNotIn(CARD_FIELD, block)

    def test_the_review_queue_is_the_only_allowlisted_reader(self):
        """A second entry here is a product decision, not a refactor."""
        self.assertEqual(_IMAGE_ALLOWED, {"get_flagged_project_checkins"})


# ── The behavioural half ────────────────────────────────────────────────────
#
# POST /admin/certifications/scan-expiring is the worst of the offenders: it
# reads up to 5000 whole worker documents and returns a name, a company, a
# trade and a verdict. It is exercised end to end here so the projection is
# proven to reach Mongo AND to leave the verdict unchanged.

class _Result:
    def __init__(self):
        self.inserted_id = "x"
        self.matched_count = 1
        self.modified_count = 1


class _FakeFind:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *a, **k):
        return self

    def skip(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def to_list(self, length=None):
        return list(self._docs)

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self.docs = []
        self.last_projection = "<never called>"

    def find(self, query=None, projection=None, *a, **k):
        self.last_projection = projection
        docs = self.docs
        if isinstance(projection, dict) and set(projection.values()) == {0}:
            docs = [
                {k: v for k, v in d.items() if k not in projection}
                for d in docs
            ]
        elif isinstance(projection, dict) and projection:
            keep = set(projection) | {"_id"}
            docs = [{k: v for k, v in d.items() if k in keep} for d in docs]
        return _FakeFind(docs)

    async def find_one(self, *a, **k):
        return None

    async def insert_one(self, doc, *a, **k):
        return _Result()

    async def update_one(self, *a, **k):
        return _Result()

    async def count_documents(self, *a, **k):
        return 0


class _FakeDb:
    def __init__(self):
        self._c = {}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection(n)
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


# A stand-in for the base64 frame a gate registration writes. Small enough to
# keep the test fast, distinctive enough to find in a payload.
_BIG_IMAGE = "data:image/jpeg;base64," + ("A" * 4096)


class ScanExpiringDoesNotLoadTheImage(unittest.TestCase):
    def setUp(self):
        self.db = _FakeDb()
        self._real_db = server.db
        server.db = self.db
        self.db.workers.docs = [{
            "_id": "w1",
            "name": "Luis Ramirez",
            "company": "Acme Concrete",
            "trade": "Concrete",
            "company_id": "c1",
            "certifications": [],          # no cert at all -> MISSING_OSHA
            "osha_card_image": _BIG_IMAGE,
            "signature": "data:image/png;base64,SIG",
        }]
        server.app.dependency_overrides[server.get_admin_user] = lambda: {
            "id": "a1", "role": "admin", "company_id": "c1",
        }
        self.client = TestClient(server.app)

    def tearDown(self):
        server.db = self._real_db
        server.app.dependency_overrides.clear()

    def test_projection_keeps_the_card_image_out_of_the_scan(self):
        res = self.client.post("/api/admin/certifications/scan-expiring")
        self.assertEqual(res.status_code, 200, res.text)
        proj = self.db.workers.last_projection
        self.assertIsInstance(
            proj, dict,
            "scan-expiring read whole worker documents (projection=%r) — up to "
            "5000 base64 card photos into memory for a name-and-verdict "
            "report" % (proj,),
        )
        self.assertEqual(proj.get(CARD_FIELD), 0)

    def test_the_verdict_is_unchanged_by_the_projection(self):
        res = self.client.post("/api/admin/certifications/scan-expiring")
        body = res.json()
        self.assertEqual(body["total_scanned"], 1)
        self.assertEqual(body["blocked_count"], 1)
        blocked = body["blocked_workers"][0]
        self.assertEqual(blocked["name"], "Luis Ramirez")
        self.assertEqual(blocked["company"], "Acme Concrete")
        self.assertEqual(blocked["trade"], "Concrete")
        self.assertEqual(blocked["blocks"][0]["type"], "MISSING_OSHA")

    def test_no_card_bytes_reach_the_response(self):
        res = self.client.post("/api/admin/certifications/scan-expiring")
        self.assertNotIn("A" * 64, res.text)


if __name__ == "__main__":
    unittest.main()
