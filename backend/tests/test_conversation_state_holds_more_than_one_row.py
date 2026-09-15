"""The unique index that silently ate every bot session.

REPORTED FROM THE LIVE TEST, 2026-09-14 21:02, group "588 Boyland tets": an
untagged follow-up twenty seconds after a tagged message got no reply. The
session window should have caught it.

IT HAD NEVER BEEN WRITTEN. `convo_state_by_group` was unique on `group_id`
ALONE, and whatsapp_conversation_state now holds three kinds of row keyed by
the same group — a checklist draft, a bot session, and a nudge cooldown. The
second writer's upsert filter did not match the existing row, so it fell
through to an insert, hit E11000, and was caught and logged at DEBUG.

The sequence in that group: the first untagged question wrote a nudge row; the
tagged message's _mark_bot_session then failed; and the follow-up found no
window. Two people in one group could never both hold a session either, and a
live checklist draft blocked sessions outright — both true long before the
nudge existed, which is why this is a fix and not a revert.

WHY A FAKE INDEX AND NOT A REAL MONGO. The defect is a property of the KEY, not
of Mongo: does the index's key set distinguish the rows the writers actually
distinguish? A fake that enforces uniqueness over a declared key set answers
exactly that, and answers it without a database.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402

SRC = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")


class DuplicateKey(Exception):
    pass


class FakeIndexedCollection:
    """A collection with one unique index over a declared key set."""

    def __init__(self, key_fields):
        self.key_fields = tuple(key_fields)
        self.rows = []

    def _key(self, doc):
        return tuple(doc.get(f) for f in self.key_fields)

    def _match(self, doc, query):
        return all(doc.get(k) == v for k, v in query.items())

    def upsert(self, query, doc):
        for r in self.rows:
            if self._match(r, query):
                r.update(doc)
                return "updated"
        key = self._key(doc)
        if any(self._key(r) == key for r in self.rows):
            raise DuplicateKey(f"E11000 duplicate key on {self.key_fields}")
        self.rows.append(dict(doc))
        return "inserted"

    def find_one(self, query):
        return next((r for r in self.rows if self._match(r, query)), None)

    def delete_one(self, query):
        for i, r in enumerate(self.rows):
            if self._match(r, query):
                return self.rows.pop(i)
        return None


GROUP = "120363@g.us"
ALICE = "19175551212"
BOB = "17185550000"

NUDGE = ({"kind": "nudge", "group_id": GROUP},
         {"kind": "nudge", "group_id": GROUP, "sender": None})
DRAFT = ({"kind": "checklist", "group_id": GROUP},
         {"kind": "checklist", "group_id": GROUP, "sender": None,
          "awaiting": "checklist_assignment"})
# The fourth kind, added with the "show me <element>" offer. It stores the
# sheet numbers the bot named so "yes" can be honoured, and it has to sit
# beside the other three rather than evict one of them.
OFFER = ({"kind": "plan_offer", "group_id": GROUP},
         {"kind": "plan_offer", "group_id": GROUP, "sender": None,
          "sheets": ["ST-201", "ST-202"]})


def session(sender):
    q = {"kind": "bot_session", "group_id": GROUP, "sender": sender}
    return q, dict(q, expires_at="+180s")


class TheOldKeyReproducesTheBug(unittest.TestCase):
    """Kept so the fix below is measured against the defect rather than
    asserted against itself."""

    def setUp(self):
        self.c = FakeIndexedCollection(["group_id"])

    def test_a_nudge_row_blocks_every_later_session(self):
        self.c.upsert(*NUDGE)
        with self.assertRaises(DuplicateKey):
            self.c.upsert(*session(ALICE))

    def test_and_the_follow_up_finds_no_window(self):
        self.c.upsert(*NUDGE)
        try:
            self.c.upsert(*session(ALICE))
        except DuplicateKey:
            pass  # swallowed at debug, exactly as production did
        q, _ = session(ALICE)
        self.assertIsNone(self.c.find_one(q),
                          "this is the reported defect: no window to ride")

    def test_a_checklist_draft_blocked_sessions_too(self):
        """True long before the nudge existed."""
        self.c.upsert(*DRAFT)
        with self.assertRaises(DuplicateKey):
            self.c.upsert(*session(ALICE))

    def test_two_senders_could_never_both_hold_one(self):
        self.c.upsert(*session(ALICE))
        with self.assertRaises(DuplicateKey):
            self.c.upsert(*session(BOB))


class TheNewKeyLetsThemCoexist(unittest.TestCase):

    def setUp(self):
        self.c = FakeIndexedCollection(["kind", "group_id", "sender"])

    def test_all_five_rows_live_in_one_group(self):
        """The whole point: a nudge, a draft, a plan offer, and a session for
        each of two people, in the same group, at the same time."""
        for q, doc in (NUDGE, DRAFT, OFFER, session(ALICE), session(BOB)):
            self.c.upsert(q, doc)
        self.assertEqual(len(self.c.rows), 5)

    def test_every_kind_has_its_own_slot(self):
        """Stated as key tuples, because that is what the index compares. Four
        distinct kinds against one group, three of them sender-less."""
        for q, doc in (NUDGE, DRAFT, OFFER, session(ALICE)):
            self.c.upsert(q, doc)
        keys = {self.c._key(r) for r in self.c.rows}
        self.assertEqual(keys, {
            ("nudge", GROUP, None),
            ("checklist", GROUP, None),
            ("plan_offer", GROUP, None),
            ("bot_session", GROUP, ALICE),
        })

    def test_an_offer_does_not_evict_a_live_session(self):
        """The sequence the live test would produce: somebody tags the bot,
        asks "show me the sprinkler riser", and the offer is stored while
        their window is still open."""
        self.c.upsert(*session(ALICE))
        self.c.upsert(*OFFER)
        q, _ = session(ALICE)
        self.assertIsNotNone(self.c.find_one(q))
        self.assertIsNotNone(self.c.find_one(OFFER[0]))

    def test_one_offer_per_group(self):
        """A second "show me <element>" replaces the first offer rather than
        stacking, so "yes" is never ambiguous about which sheets it means."""
        self.c.upsert(*OFFER)
        self.c.upsert({"kind": "plan_offer", "group_id": GROUP},
                      {"kind": "plan_offer", "group_id": GROUP, "sender": None,
                       "sheets": ["A-301"]})
        offers = [r for r in self.c.rows if r.get("kind") == "plan_offer"]
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["sheets"], ["A-301"])

    def test_the_reported_sequence_now_works(self):
        self.c.upsert(*NUDGE)          # first untagged question
        self.c.upsert(*session(ALICE))  # the tagged message
        q, _ = session(ALICE)
        self.assertIsNotNone(self.c.find_one(q),
                             "the follow-up has a window to ride")

    def test_one_draft_per_group_still_holds(self):
        """The constraint the original index was written for is NOT lost — a
        checklist row carries no sender, so the key admits exactly one."""
        self.c.upsert(*DRAFT)
        self.c.upsert(*DRAFT)
        drafts = [r for r in self.c.rows if r.get("kind") == "checklist"]
        self.assertEqual(len(drafts), 1)

    def test_one_session_per_person_not_per_group(self):
        self.c.upsert(*session(ALICE))
        self.c.upsert(*session(ALICE))
        self.c.upsert(*session(BOB))
        sessions = [r for r in self.c.rows if r.get("kind") == "bot_session"]
        self.assertEqual(len(sessions), 2)

    def test_one_nudge_per_group(self):
        self.c.upsert(*NUDGE)
        self.c.upsert(*NUDGE)
        self.assertEqual(len([r for r in self.c.rows
                              if r.get("kind") == "nudge"]), 1)

    def test_deleting_a_draft_leaves_the_session_alone(self):
        """A bare {group_id} delete was unambiguous only BECAUSE one row per
        group was all there was. With more than one it removes an arbitrary
        kind — which is why every call site had to be scoped."""
        self.c.upsert(*session(ALICE))
        self.c.upsert(*DRAFT)
        self.c.delete_one({"kind": "checklist", "group_id": GROUP})
        q, _ = session(ALICE)
        self.assertIsNotNone(self.c.find_one(q))


class TheCodeCarriesTheNewKey(unittest.TestCase):

    def test_the_index_is_declared_over_all_three_fields(self):
        i = SRC.index('name="convo_state_by_kind_group_sender"')
        block = SRC[i - 600:i]
        for field in ('("kind", 1)', '("group_id", 1)', '("sender", 1)'):
            with self.subTest(field=field):
                self.assertIn(field, block)
        self.assertIn("unique=True", block)

    def test_the_old_index_is_dropped_by_name(self):
        """_ensure_index_resilient only rebuilds an index whose NAME it is
        given. Leaving the old one in place would keep rejecting every write
        this change exists to allow."""
        self.assertIn(
            'drop_index("convo_state_by_group")', SRC,
            "the old unique-on-group_id index is no longer dropped by name, "
            "so it survives the deploy and keeps rejecting every session write")

    def test_no_call_site_still_filters_on_group_id_alone(self):
        """The other half of the fix. A bare filter reads or deletes an
        arbitrary row kind now that more than one can exist."""
        stray = []
        for m in re.finditer(
            r"whatsapp_conversation_state\.(find_one|update_one|delete_one)\(\s*"
            r"(\{[^}]*\})", SRC,
        ):
            flt = m.group(2)
            if '"kind"' not in flt:
                stray.append(SRC.count("\n", 0, m.start()) + 1)
        self.assertEqual(stray, [],
                         f"unscoped conversation_state filter at line(s) {stray}")


class ADuplicateKeyIsNoLongerWhispered(unittest.TestCase):
    """A session that fails to write is a bot that stops answering a
    conversation it is in the middle of. For months the only trace was a debug
    line nobody reads."""

    @staticmethod
    def _code_only(fn):
        """CODE LINES ONLY. The comment above the fix names logger.debug in
        order to say what it replaced, and a guard that trips on its own
        rationale is a guard nobody keeps."""
        return "\n".join(
            line for line in inspect.getsource(fn).split("\n")
            if not line.lstrip().startswith("#")
        )

    def test_the_handler_logs_at_warning(self):
        code = self._code_only(server._mark_bot_session)
        self.assertNotIn("logger.debug", code)
        self.assertIn("logger.warning", code)

    def test_it_names_the_filter_that_collided(self):
        """"duplicate key" on its own does not say which of the three row
        kinds lost."""
        src = inspect.getsource(server._mark_bot_session)
        self.assertIn("filter=", src)

    def test_it_says_what_the_user_will_experience(self):
        src = inspect.getsource(server._mark_bot_session)
        self.assertIn("E11000", src)
        self.assertIn("ignored", src.lower())

    def test_it_still_never_raises(self):
        """The caller is the addressing decision on an inbound message. A
        raise here would turn a lost window into a dropped message."""
        tree = ast.parse(inspect.getsource(server._mark_bot_session))
        handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
        self.assertTrue(handlers)
        for h in handlers:
            self.assertFalse([n for n in ast.walk(h) if isinstance(n, ast.Raise)])


if __name__ == "__main__":
    unittest.main()
