"""A FIELD EDIT COULD RESURRECT A DELETED LOG AND FREEZE AN OPEN ONE.

`PUT /daily-logs/{log_id}` takes `update_data: dict` — untyped — and `$set`s
what survives a list of pops. Two lifecycle fields were not on that list:

  is_deleted   Every reader filters `{"is_deleted": {"$ne": True}}`. Sending
               `is_deleted: false` through this body brought a soft-deleted log
               back everywhere at once.
  is_locked    Sending `is_locked: true` froze somebody else's open log. The
               reverse happened not to work, but only because the 423 refusal
               fires on a locked log before the write — a guard written for a
               different reason, standing in for one nobody wrote.

Both were reachable by any caller with access to the project. Neither is
cross-tenant: `_assert_project_access` authorises against the STORED project id,
which is correct and untouched here.

WHY POPS AND NOT AN ALLOWLIST. An allowlist is the better long-term shape and it
is a contract change: the callers of this endpoint are not enumerated, and
`offlineQueue.js` replays `PUT /api/daily-logs/{id}` from the device, so a field
silently dropped from a queued edit is a worse failure than the two this closes.
Ruled: two pops today, allowlist later. The debt is recorded in the handler.
"""

import os
import sys
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from tests.source_text import code_of  # noqa: E402

SRC = code_of("server.py")
_I = SRC.index("async def update_daily_log(")
_J = SRC.index("async def ", _I + 10)
BODY = SRC[_I:_J]


class LifecycleFieldsAreNotEditable(unittest.TestCase):
    def test_is_deleted_is_popped(self):
        self.assertIn('update_data.pop("is_deleted", None)', BODY)

    def test_is_locked_is_popped(self):
        self.assertIn('update_data.pop("is_locked", None)', BODY)

    def test_both_pops_precede_the_write(self):
        """A pop after the $set is decoration."""
        write = BODY.index('"$set": update_data')
        for field in ("is_deleted", "is_locked"):
            self.assertLess(
                BODY.index(f'update_data.pop("{field}", None)'), write,
                f"{field} is popped after the write",
            )

    def test_the_ownership_pops_are_still_there(self):
        """The two this change sits beside, so a later edit cannot drop them
        while adding to this list."""
        for field in ("project_id", "company_id", "id", "_id",
                      "created_at", "created_by"):
            self.assertIn(f'update_data.pop("{field}", None)', BODY)

    def test_the_pop_list_is_exactly_these_eight(self):
        """COUNTED, not just checked for membership. A denylist is only as good
        as its completeness, and membership assertions pass happily while the
        list quietly grows a hole. Eight today; a ninth field needing protection
        should fail here and be argued for."""
        popped = set()
        i = 0
        while True:
            j = BODY.find("update_data.pop(", i)
            if j < 0:
                break
            popped.add(BODY[j:BODY.index(")", j)].split('"')[1])
            i = j + 1
        self.assertEqual(
            popped,
            {"id", "_id", "created_at", "created_by", "project_id",
             "company_id", "is_deleted", "is_locked"},
        )


class TheAuthorisationIsUnchanged(unittest.TestCase):
    """This change is about WHICH FIELDS a permitted caller may write, not about
    who is permitted. Asserted so the two are not conflated later."""

    def test_it_still_authorises_against_the_stored_project(self):
        self.assertIn("_assert_project_access(", BODY)
        self.assertIn('existing.get("project_id")', BODY)

    def test_a_locked_log_is_still_refused_before_any_write(self):
        self.assertIn("423", BODY)
        self.assertLess(BODY.index("423"), BODY.index('"$set": update_data'))


class TheStateItProtectsIsStillSetElsewhere(unittest.TestCase):
    """Popping a field is only correct if something legitimate still writes it,
    or the state becomes unreachable. Both are set by their own endpoints."""

    def test_something_still_soft_deletes_a_daily_log(self):
        self.assertIn("db.daily_logs", SRC)
        self.assertIn('"is_deleted": True', SRC)

    def test_locking_still_happens_on_its_own_path(self):
        self.assertIn('"is_locked": True', SRC)


if __name__ == "__main__":
    unittest.main(verbosity=2)
