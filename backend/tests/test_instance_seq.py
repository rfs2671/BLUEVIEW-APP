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
  * the count-then-insert is not atomic.

A THIRD WAS FOUND HERE AND IS NOW FIXED. Neither the count nor the dedupe
filtered on company_id, and create_logbook compared no company at all — so a
create could land on another company's unlocked logbook and $set over it. It
surfaced as a numbering result (the new filing was not numbered 2, because
there was no new filing). Fixed in #110; covered in full by
test_logbook_cross_tenant_write.py. The refusal is asserted below so this file
records how it was found rather than quietly dropping it.
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
        cp_signature=({"image": "data:image/png;base64,iVBOR",
                       "affirmed": True, "affirmedAt": "2026-08-09T12:00:00Z"}
                      if signed else None),
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
    decision on a filed record, which is the operator's to make.

    The third one this class used to hold — the cross-tenant clobber — is
    fixed, and its test now asserts the refusal."""

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

    def test_the_cross_tenant_clobber_this_file_found_CANNOT_HAPPEN(self):
        """WAS a defect, found here, fixed in #110.

        I went looking for two companies sharing a sequence — the count query
        has no company_id — and found something in front of it: the create did
        not get NUMBERED behind the other company's row, it MATCHED that row
        and $set over it, because the dedupe had no company_id either and
        create_logbook compared no company at all.

        This asserts the DEDUPE half, which is what this file can reach: the
        caller here is co1 acting on a co1 project, so the request is
        legitimate and must succeed — while a co2 row sharing (project, type,
        date) is neither matched nor touched. The 403 half, and the victim
        document field by field, are in test_logbook_cross_tenant_write.py."""
        stray = {
            "_id": "other_co", "project_id": PROJECT_ID, "company_id": "co2",
            "log_type": IMMEDIATE, "date": DATE, "is_deleted": False,
            "is_amendment": False, "instance_seq": 1,
            "data": {"note": "co2's record"},
        }
        self.db.logbooks.docs.append(dict(stray))

        self.create(_payload(status="submitted"))

        self.assertEqual(len(self.db.logbooks.docs), 2,
                         "co1's filing inserted its own row rather than landing on co2's")
        self.assertEqual(self.db.logbooks.docs[0], stray,
                         "co2's record is untouched, byte for byte")
        mine = self.db.logbooks.docs[1]
        self.assertEqual(mine["company_id"], "co1")

        # THE SURVIVING HALF, and it is now numbering only. #110 scoped the
        # DEDUPE, which is what could destroy a record; the count_documents
        # query above it still has no company_id, so another company's row on
        # the same project-day still advances the number. co1's first filing
        # is stamped 2. Nothing is overwritten and nothing is lost — the
        # number is just wrong. Recorded, not fixed: see
        # test_the_count_query_omits_company_id below.
        self.assertEqual(mine["instance_seq"], 2,
                         "co2's row still advances co1's count — numbering, not data loss")

    def test_DEFECT_the_count_query_still_omits_company_id(self):
        """The surviving half of the omission #110 fixed, and now numbering
        only: the DEDUPE is scoped, so nothing can be overwritten, but the
        count is not, so another company's row on the same project-day still
        advances the number. Reachable where two companies hold rows on one
        project — a legacy row, or a project whose company changed."""
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
        """CODE lines only. The tenant fix's comment names instance_seq while
        explaining what the clobber carried over, and a raw string count would
        read that prose as a second reader."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        code = [l for l in src.splitlines() if not l.strip().startswith("#")]
        hits = [l.strip() for l in code if "instance_seq" in l]
        self.assertEqual(len(hits), 1, f"one write, no renderer, no report: {hits}")
        self.assertTrue(hits[0].startswith('"instance_seq":'), hits[0])


if __name__ == "__main__":
    unittest.main()
