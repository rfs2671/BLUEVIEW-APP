"""AN EMPTY PHONE MATCHED A REAL MAN, AND THEN RENAMED HIM.

`format_phone("")` returns `""`. Three call sites built the same lookup by
hand:

    {"phone": {"$in": [phone, raw_digits, formatted]}, "is_deleted": {"$ne": True}}

With no phone that is `{"$in": ["", "", ""]}` — a query matching any worker
whose stored phone is the empty string. Production holds exactly one such row
out of 61 live workers, a named man at AAZ.

AND RESOLVING HIM WAS NOT A READ. `submit_checkin` follows the lookup with

    if worker.get("name") != checkin_data.name:
        update_fields["name"] = checkin_data.name

so the wrong man's stored name is overwritten with whatever the submitter
typed, and the check-in is filed under his `worker_id`. One empty text field,
two corruptions: a check-in credited to someone who was not there, and a live
worker record renamed.

`register_and_checkin` guarded it (`if phone:`). `lookup_worker` 400s on a
falsy phone upstream. `submit_checkin` did neither — and `submit_checkin` is a
PUBLIC, unauthenticated endpoint.

NOT EXPLOITED, AND THAT IS STATED RATHER THAN ASSUMED. Queried before the fix:
that worker has 0 check-ins, 0 enrollments, and `updated_at == created_at` —
his row has never been written to since creation. The endpoint's only client is
the React check-in screen, which is not the live gate (the gate is
backend/checkin.html, which posts to register-and-checkin). The hole was
reachable by anyone with the URL and had not been reached.

THE FIX IS THE HELPER, NOT A THIRD GUARD. `_worker_by_phone` refuses to issue
the query at all without a digit to match on, so the guard cannot be forgotten
at a fourth call site — there is no longer a query to copy. An empty phone
falls through to worker CREATION, which is the right direction on a record of
who was on site: a duplicate row is visible and correctable; attaching one
man's check-in to another, while renaming that other, is neither. That is the
same principle the `_norm_key` regression guards encode.
"""

from __future__ import annotations

import ast
import asyncio
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
from tests.source_text import code_of  # noqa: E402

#: STRIPPED of comments and docstrings, for the census below: this change is
#: explained in prose that quotes the very query it removes.
_CODE = code_of("server.py")

#: THE RAW FILE, for the AST walks only. `code_of` blanks docstrings, and a
#: blanked docstring used as a dict VALUE leaves `{"content": },` behind --
#: `ast.parse` raises SyntaxError on the stripped text. Two readings of one
#: file, each for the thing it can actually answer.
_RAW = (_BACKEND / "server.py").read_text(encoding="utf-8")

#: The live row, as production actually stores it. Nothing about this worker is
#: malformed — an empty phone is a legal state a gate registration can produce.
_THE_MAN = {"_id": "w-real", "name": "Jose David Hernandez Pena",
            "company": "AAZ", "phone": "", "is_deleted": False}
_WITH_PHONE = {"_id": "w-phone", "name": "Ada Lovelace",
               "phone": "212-555-0134", "is_deleted": False}


def _matches(doc, query):
    """Mongo's `$in` and `$ne`, only as far as this query needs."""
    for k, cond in query.items():
        v = doc.get(k)
        if isinstance(cond, dict):
            if "$in" in cond and v not in cond["$in"]:
                return False
            if "$ne" in cond and v == cond["$ne"]:
                return False
        elif v != cond:
            return False
    return True


class _Workers:
    def __init__(self, docs):
        self.docs = docs
        self.queries = []

    async def find_one(self, query, projection=None):
        self.queries.append(query)
        for d in self.docs:
            if _matches(d, query):
                return dict(d)
        return None


class _DB:
    def __init__(self, workers):
        self.workers = workers


class _Base(unittest.TestCase):
    def setUp(self):
        self.workers = _Workers([_THE_MAN, _WITH_PHONE])
        self._orig = server.db
        server.db = _DB(self.workers)

    def tearDown(self):
        server.db = self._orig

    def call(self, phone, projection=None):
        return asyncio.run(server._worker_by_phone(phone, projection))


class ThePreconditionTheFixRemoves(_Base):
    """PROVE THE BUG WAS THERE. The helper did not exist before this change, so
    the old code cannot be run against these tests — which would leave every
    assertion below passing on a fix nobody demonstrated was needed. The old
    QUERY can be run, and it is reconstructed here exactly as the three call
    sites built it."""

    @staticmethod
    def _the_old_query(phone):
        raw_digits = "".join(c for c in phone if c.isdigit())
        formatted = server.format_phone(raw_digits)
        return {"phone": {"$in": [phone, raw_digits, formatted]},
                "is_deleted": {"$ne": True}}

    def test_format_phone_of_nothing_is_still_nothing(self):
        """The link in the chain that made an empty field into a query."""
        self.assertEqual(server.format_phone(""), "")

    def test_the_old_query_MATCHED_the_man_with_no_phone(self):
        self.assertTrue(_matches(_THE_MAN, self._the_old_query("")))

    def test_and_it_matched_him_FIRST(self):
        """Order matters: `find_one` returns whoever it reaches first, so a
        single empty-phone row is enough to capture every phone-less caller."""
        q = self._the_old_query("")
        hits = [d["name"] for d in (_THE_MAN, _WITH_PHONE) if _matches(d, q)]
        self.assertEqual(hits, ["Jose David Hernandez Pena"])

    def test_the_new_helper_does_not(self):
        """Same fixture, same man, the two behaviours side by side."""
        self.assertIsNone(self.call(""))


class NothingResolvesWithoutADigit(_Base):

    def test_the_empty_string_does_not_find_the_man_with_no_phone(self):
        """The defect, as the property rather than as the old query."""
        self.assertIsNone(self.call(""))

    def test_and_the_database_was_never_even_ASKED(self):
        """THE EFFECT, NOT THE RETURN VALUE. A guard that still issues
        `{"$in": ["", "", ""]}` and discards the answer would satisfy the test
        above while leaving the query in the log and one refactor away from
        being used again."""
        self.call("")
        self.assertEqual(self.workers.queries, [])

    def test_none_and_whitespace_and_letters_all_resolve_to_nobody(self):
        for phone in (None, "", "   ", "\t", "abc", "---", "()- "):
            with self.subTest(phone=phone):
                self.assertIsNone(self.call(phone))
        self.assertEqual(self.workers.queries, [])

    def test_a_REAL_phone_still_resolves(self):
        """The control on the other side. Refusing every lookup is the easy
        way to pass everything above."""
        found = self.call("212-555-0134")
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Ada Lovelace")

    def test_the_three_spellings_are_all_still_tried(self):
        """A returning worker types digits; the row may hold the formatted
        version, or the reverse. Narrowing that was never the goal."""
        self.call("2125550134")
        self.assertEqual(len(self.workers.queries), 1)
        variants = self.workers.queries[0]["phone"]["$in"]
        self.assertIn("2125550134", variants)
        self.assertIn("212-555-0134", variants)

    def test_no_empty_string_can_reach_the_IN_LIST(self):
        """The shape of the original defect, asserted directly: whatever the
        input, the candidate list never carries a value that matches a stored
        empty phone."""
        for phone in ("2125550134", "212-555-0134", " 212 555 0134 ", "+1 212 555 0134"):
            with self.subTest(phone=phone):
                self.workers.queries.clear()
                self.call(phone)
                for v in self.workers.queries[0]["phone"]["$in"]:
                    self.assertTrue(v, f"an empty candidate survived: {phone!r}")

    def test_deleted_workers_are_still_excluded(self):
        """Carried over from all three hand-written copies. Losing it here
        would lose it everywhere at once."""
        self.call("2125550134")
        self.assertEqual(self.workers.queries[0]["is_deleted"], {"$ne": True})

    def test_the_projection_is_still_honoured(self):
        """`lookup_worker` excludes the OSHA card image — a base64 blob it must
        not ship to a public caller."""
        seen = {}

        async def find_one(query, projection=None):
            seen["projection"] = projection
            return None

        self.workers.find_one = find_one
        self.call("2125550134", {"osha_card_image": 0})
        self.assertEqual(seen["projection"], {"osha_card_image": 0})


class EveryCallSiteGoesThroughIt(unittest.TestCase):
    """A helper that two of three sites use is not a fix; it is a fourth
    spelling."""

    def test_no_hand_rolled_phone_lookup_survives(self):
        hits = re.findall(r'"phone":\s*\{"\$in"', _CODE)
        self.assertEqual(len(hits), 1,
                         "a phone $in query outside the helper — the guard is "
                         "back to being something a call site must remember")

    def test_the_one_that_survives_is_the_helper(self):
        i = _CODE.index("async def _worker_by_phone")
        j = _CODE.index("\n@api_router", i)
        self.assertIn('"phone": {"$in"', _CODE[i:j])

    def test_all_three_endpoints_call_it(self):
        tree = ast.parse(_RAW)
        wanted = {"register_and_checkin", "lookup_worker", "submit_checkin"}
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted:
                if "_worker_by_phone" in ast.unparse(node):
                    found.add(node.name)
        self.assertEqual(found, wanted, f"not routed through the helper: "
                                        f"{sorted(wanted - found)}")

    def test_it_is_reached_before_the_name_is_written(self):
        """WHY THIS ONE MATTERS MOST. `submit_checkin` writes the submitter's
        name onto whatever worker the lookup returned. If the lookup is ever
        moved after that write, or a second lookup is added, the rename runs
        against an unguarded result again."""
        tree = ast.parse(_RAW)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "submit_checkin")
        body = ast.unparse(fn)
        self.assertEqual(body.count("_worker_by_phone"), 1)
        self.assertLess(body.index("_worker_by_phone"),
                        body.index("update_fields['name']"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
