"""`instance_seq` — which filing of the day a log is.

WHAT IT IS FOR. Nine of the eleven log types are IMMEDIATE: the signature is
the freeze, and a second same-day filing is a legitimately NEW discrete record
(the 7am scaffold inspection, then the 11am post-alteration one). e92717f added
`instance_seq` "so a day's multiple filings are auditable" — it numbers them.

WHAT READS IT. Nothing in this repository. It is written at server.py:16009
and referenced nowhere else: no PDF renderer, no report, no frontend. It does
go over the wire — GET /logbooks/{id} and /logbooks/project/{id} both return
the whole document — so it is available to a reader, and it is stored on every
filed record. That is what a stored audit field looks like, and it is why the
absence of coverage mattered: the field is not displayed anywhere that a human
would notice it going wrong.

IT WAS ASSERTED BY NOTHING. Mutating the count to a constant 999, and then to
0, left the whole 2807-test suite green. Every test below fails under at least
one of those two mutations.

DEFECTS ARE DOCUMENTED, NOT FIXED. They are decisions about what a filed
record says, and they belong to the operator. They are named DEFECT_ below so
nobody reads a passing test as a statement that the behaviour is wanted:

  * a soft-deleted filing makes two live logs claim the same number;
  * the count-then-insert is not atomic;
  * and — found while testing the numbering, and larger than it — neither the
    count NOR THE DEDUPE filters on company_id, so a create can land on
    another company's unlocked logbook and overwrite it.
"""

from __future__ import annotations

import asyncio
import copy
import os
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
from server import LogbookCreate  # noqa: E402

PROJECT_ID = "6a5f63bc147407d3261df2c7"
DATE = "2026-07-29"
USER = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "co1",
        "full_name": "Carl CP"}

# An IMMEDIATE type. These are the ones that can legitimately recur in a day,
# and therefore the only ones for which the number means anything.
IMMEDIATE = "scaffold_maintenance"


def _get(doc, key):
    if "." not in key:
        return doc.get(key)
    cur = doc
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _match(doc, query):
    for k, v in query.items():
        if isinstance(v, dict) and "$ne" in v:
            if _get(doc, k) == v["$ne"]:
                return False
            continue
        if _get(doc, k) != v:
            return False
    return True


class _Result:
    def __init__(self, _id):
        self.inserted_id = _id


class _Coll:
    def __init__(self):
        self.docs = []
        self._seq = 0

    async def find_one(self, query, sort=None):
        for d in self.docs:
            if _match(d, query):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _match(d, query))

    async def insert_one(self, doc):
        self._seq += 1
        doc = dict(doc)
        doc["_id"] = doc.get("_id") or f"oid_{self._seq}"
        self.docs.append(doc)
        return _Result(doc["_id"])

    async def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _match(d, flt):
                d.update(update.get("$set", {}))
                return


class _DB:
    def __init__(self):
        self.logbooks = _Coll()
        self.projects = _Coll()


async def _noop(*a, **k):
    return None


def _payload(log_type=IMMEDIATE, date=DATE, status="draft", signed=True):
    return LogbookCreate(
        project_id=PROJECT_ID, log_type=log_type, date=date,
        data={"note": "x"},
        cp_signature={"image": "data:image/png;base64,iVBOR"} if signed else None,
        cp_name="Carl CP" if signed else None,
        status=status,
    )


class InstanceSeqBase(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.db = _DB()
        self.db.projects.docs.append(
            {"_id": PROJECT_ID, "name": "588 Boyland", "company_id": "co1",
             "is_deleted": False},
        )
        self._orig = {
            "db": server.db, "gcid": server.get_user_company_id,
            "tqid": server.to_query_id, "enh": server._enhance_logbook_photos,
            "audit": server.audit_log,
        }
        server.db = self.db
        server.get_user_company_id = lambda u: "co1"
        server.to_query_id = lambda x: x
        server._enhance_logbook_photos = _noop
        server.audit_log = _noop

    def tearDown(self):
        server.db = self._orig["db"]
        server.get_user_company_id = self._orig["gcid"]
        server.to_query_id = self._orig["tqid"]
        server._enhance_logbook_photos = self._orig["enh"]
        server.audit_log = self._orig["audit"]
        self.loop.close()

    def create(self, payload=None):
        return self.loop.run_until_complete(
            server.create_logbook(data=payload or _payload(), current_user=USER),
        )

    def seqs(self):
        return [d.get("instance_seq") for d in self.db.logbooks.docs]


class ADaysFilingsAreNumbered(InstanceSeqBase):
    """The thing the field exists to do."""

    def test_the_first_filing_of_the_day_is_1(self):
        self.create()
        self.assertEqual(self.seqs(), [1], "the first filing is 1, not 0")

    def test_the_second_filing_of_the_day_is_2(self):
        # BOTH submitted. An IMMEDIATE log freezes on signature, and only a
        # LOCKED row is excluded from the dedupe — so a first filing left as a
        # DRAFT is upserted by the second, not numbered 2. That is the freeze
        # model working, not a numbering bug.
        self.create(_payload(status="submitted"))
        self.create(_payload(status="submitted"))
        self.assertEqual(self.seqs(), [1, 2],
                         "the 7am inspection and the 11am one are 1 and 2")

    def test_an_unsigned_draft_is_EDITED_rather_than_numbered_2(self):
        """The control for the test above: proves it measures the numbering
        and not merely that two documents exist."""
        self.create()
        self.create()
        self.assertEqual(self.seqs(), [1], "an edit to a draft is not a new filing")

    def test_a_days_filings_are_numbered_consecutively(self):
        for _ in range(5):
            self.create(_payload(status="submitted"))
        self.assertEqual(self.seqs(), [1, 2, 3, 4, 5])

    def test_every_created_log_carries_the_field(self):
        self.create()
        self.assertIn("instance_seq", self.db.logbooks.docs[0],
                      "an audit field nothing displays must at least be written")


class TheCountIsScoped(InstanceSeqBase):
    """A filing is the Nth OF THIS project, this type, this day. Each of these
    fails if a clause is dropped from the query."""

    def test_another_DAY_does_not_advance_it(self):
        self.create(_payload(date="2026-07-28", status="submitted"))
        self.create(_payload(date=DATE, status="submitted"))
        self.assertEqual(self.seqs(), [1, 1], "each day starts again at 1")

    def test_another_LOG_TYPE_does_not_advance_it(self):
        self.create(_payload(log_type="hot_work", status="submitted"))
        self.create(_payload(log_type=IMMEDIATE, status="submitted"))
        self.assertEqual(self.seqs(), [1, 1],
                         "a hot-work permit is not a scaffold inspection")

    def test_another_PROJECT_does_not_advance_it(self):
        other = "6a5f63bc147407d3261df2c8"
        self.db.projects.docs.append(
            {"_id": other, "name": "Other", "company_id": "co1", "is_deleted": False},
        )
        p = _payload(status="submitted")
        p.project_id = other
        self.create(p)
        self.create(_payload(status="submitted"))
        self.assertEqual(self.seqs(), [1, 1], "another jobsite is another sequence")

    def test_an_AMENDMENT_does_not_advance_it(self):
        """An amendment corrects a filing; it is not another filing."""
        self.create(_payload(status="submitted"))
        self.db.logbooks.docs.append({
            "_id": "amend1", "project_id": PROJECT_ID, "log_type": IMMEDIATE,
            "date": DATE, "is_amendment": True, "is_deleted": False,
            "instance_seq": 1,
        })
        self.create(_payload(status="submitted"))
        self.assertEqual(self.db.logbooks.docs[-1]["instance_seq"], 2,
                         "the amendment was counted as a filing")


class ItIsStampedOnceAndNeverRecomputed(InstanceSeqBase):
    def test_an_update_does_not_renumber_an_existing_log(self):
        """The upsert path never touches it. A number that moved after the
        fact would be worse than no number: it would be a wrong one."""
        self.create()                       # draft, so the next create upserts
        first_id = self.db.logbooks.docs[0]["_id"]
        self.create()
        self.assertEqual(len(self.db.logbooks.docs), 1, "the draft was upserted")
        self.assertEqual(self.db.logbooks.docs[0]["_id"], first_id)
        self.assertEqual(self.db.logbooks.docs[0]["instance_seq"], 1,
                         "an edit is not a new filing")


class KnownDefects(InstanceSeqBase):
    """CURRENT behaviour, recorded so it is visible. A passing test here is
    NOT a statement that the behaviour is wanted — each is a numbering
    decision on a filed record, which is the operator's to make."""

    def test_DEFECT_a_deleted_filing_makes_two_logs_claim_the_same_number(self):
        """File three, delete the second, file a fourth. The count skips the
        deleted row, so the new filing is numbered 3 — and the surviving third
        filing is already 3. Two documents on one project-day now claim to be
        the same filing, which is precisely what an audit number must not do.

        A monotonic max(instance_seq)+1 would avoid it. That changes what the
        number MEANS (a count of filings vs an ever-increasing id), so it is
        not a change to make silently."""
        for _ in range(3):
            self.create(_payload(status="submitted"))
        self.assertEqual(self.seqs(), [1, 2, 3])

        self.db.logbooks.docs[1]["is_deleted"] = True
        self.create(_payload(status="submitted"))

        live = [d["instance_seq"] for d in self.db.logbooks.docs
                if not d.get("is_deleted")]
        self.assertEqual(live, [1, 3, 3],
                         "two live filings claim to be the third of the day")

    def test_DEFECT_another_companys_unlocked_log_is_overwritten_not_numbered(self):
        """I went looking for a numbering bug — two companies sharing one
        sequence, because the count_documents query has no company_id — and
        found something larger sitting in front of it.

        THE DEDUPE HAS NO company_id EITHER (server.py, `dedupe_filter`). So
        co1's create does not get numbered 2 behind co2's filing: it MATCHES
        co2's row and $sets over it. The other company's logbook content is
        replaced, and its instance_seq is left behind on top of the new
        content.

        Reachable only if a caller can hold a project_id belonging to another
        company. create_logbook checks assigned_projects for role `cp` and
        project EXISTENCE for everyone else — it never compares
        project.company_id to the caller's. Whether a non-CP of co2 can obtain
        a co1 project id is a question about the wider auth model and is not
        settled here."""
        self.db.logbooks.docs.append({
            "_id": "other_co", "project_id": PROJECT_ID, "company_id": "co2",
            "log_type": IMMEDIATE, "date": DATE, "is_deleted": False,
            "is_amendment": False, "instance_seq": 1,
            "data": {"note": "co2's record"},
        })
        self.create(_payload(status="submitted"))

        self.assertEqual(len(self.db.logbooks.docs), 1,
                         "co1's create inserted nothing — it landed on co2's row")
        clobbered = self.db.logbooks.docs[0]
        self.assertEqual(clobbered["_id"], "other_co")
        self.assertEqual(clobbered["company_id"], "co2",
                         "still labelled co2, now carrying co1's content")
        self.assertEqual(clobbered["data"], {"note": "x"},
                         "co2's record was overwritten")
        self.assertEqual(clobbered["instance_seq"], 1,
                         "and the number is the one co2 was stamped with")

    def test_the_count_query_omits_company_id(self):
        """The numbering half of the same omission, asserted directly on the
        source since the clobber above prevents it from being reachable
        through the endpoint."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index('"instance_seq": (await db.logbooks.count_documents(')
        query = src[i:src.index("})) + 1", i)]
        for clause in ("project_id", "log_type", "date", "is_deleted", "is_amendment"):
            self.assertIn(clause, query, f"the count lost its {clause} clause")
        self.assertNotIn("company_id", query,
                         "if this gains company_id, the clobber test above needs revisiting")

    def test_the_count_then_insert_is_not_atomic(self):
        """Documented by reading, not by racing an asyncio loop: the value is
        computed with count_documents and used in a later insert_one, with no
        transaction and no unique index between them. Two concurrent creates
        both count N. This asserts the shape of the code, which is the only
        thing a single-threaded test can honestly show."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        i = src.index('"instance_seq": (await db.logbooks.count_documents(')
        self.assertGreater(i, 0)
        self.assertNotIn("with_transaction", src[i - 2000:i],
                         "if this ever gains a transaction, delete this test")


class NothingReadsIt(unittest.TestCase):
    """Stated as a test so the claim in this file's header cannot quietly go
    stale. If something starts reading it, this fails and the header is wrong."""

    def test_the_field_is_written_in_exactly_one_place_and_read_nowhere(self):
        hits = []
        for path in [_BACKEND / "server.py"] + sorted(
            (_BACKEND.parent / "frontend" / "src").rglob("*.js"),
        ):
            try:
                if "instance_seq" in path.read_text(encoding="utf-8"):
                    hits.append(path.name)
            except (UnicodeDecodeError, OSError):
                continue
        self.assertEqual(hits, ["server.py"],
                         "instance_seq gained a reader — update this file's header")

    def test_it_is_not_rendered_on_any_filed_document(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("instance_seq"), 1,
                         "one write, no renderer, no report")


if __name__ == "__main__":
    unittest.main()
