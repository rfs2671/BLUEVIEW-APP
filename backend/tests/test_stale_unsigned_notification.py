"""THE CP SEES THE DAY HE NEVER SIGNED.

sweep_stale_end_of_day_logs freezes yesterday's SIGNED daily narratives and
deliberately leaves the unsigned ones open — sealing a record nobody attested to
is worse than leaving it open — and raises a compliance_alerts row so the ADMIN
sees it.

That is half a surface. The admin can see an unfinished obligation; the CP is
the only person who can finish it, and he has no admin login. So the same fact
reaches him through the notifications endpoint his logbook list already calls,
with refs so the card can deep-link to the log that needs signing.

THE PREDICATE MUST BE THE SWEEP'S OWN. A log this list shows as needing a
signature has to be exactly a log the sweep declined to freeze. If the two ever
disagreed, the CP would sign something and it would stay on his screen, or the
sweep would seal something the screen had told him was still his to finish.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server as S  # noqa: E402

AFFIRMED = {"affirmed": True, "affirmedAt": "2026-08-17T09:00:00Z"}
TODAY = "2026-08-18"
YESTERDAY = "2026-08-17"


def _log(_id, log_type="daily_jobsite", date=YESTERDAY, sig=None, **over):
    doc = {
        "_id": _id, "project_id": "p1", "log_type": log_type, "date": date,
        "is_locked": False, "is_deleted": False, "cp_signature": sig,
        "status": "draft",
    }
    doc.update(over)
    return doc


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return self._docs


class _Logbooks:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query=None, projection=None):
        q = query or {}

        def keep(d):
            for k, v in q.items():
                if isinstance(v, dict):
                    if "$in" in v and d.get(k) not in v["$in"]:
                        return False
                    if "$lt" in v and not (str(d.get(k, "")) < v["$lt"]):
                        return False
                    if "$ne" in v and d.get(k) == v["$ne"]:
                        return False
                elif d.get(k) != v:
                    return False
            return True
        return _Cursor([d for d in self.docs if keep(d)])

    async def find_one(self, *a, **k):
        return None

    async def count_documents(self, q=None):
        return 0


class _Empty:
    def find(self, *a, **k):
        return _Cursor([])

    async def find_one(self, *a, **k):
        return None

    async def count_documents(self, q=None):
        return 0


class _DB:
    def __init__(self, logs):
        self.logbooks = _Logbooks(logs)

    def __getattr__(self, name):
        return _Empty()


def _notifications(logs, now="2026-08-18"):
    db = _DB(logs)
    with patch.object(S, "db", db), \
         patch.object(S, "eastern_date", lambda *_a, **_k: now):
        return asyncio.run(S.get_logbook_notifications(
            "p1", current_user={"id": "u1", "role": "cp"}))


class TheCpIsToldAboutTheDayHeNeverSigned(unittest.TestCase):

    def test_an_unsigned_stale_log_is_counted(self):
        out = _notifications([_log("a", sig=None)])
        self.assertEqual(out["stale_unsigned_logbooks"], 1)
        self.assertEqual(out["stale_unsigned_logbook_refs"],
                         [{"log_type": "daily_jobsite", "date": YESTERDAY}])

    def test_a_SIGNED_stale_log_is_not(self):
        """The sweep froze it. Nothing is outstanding."""
        self.assertEqual(
            _notifications([_log("a", sig=AFFIRMED)])["stale_unsigned_logbooks"], 0)

    def test_an_EMPTY_signature_object_still_counts_as_unsigned(self):
        """`cp_signature: {}` is what production held. The sweep declines to
        freeze it, so the CP must be told it is still his to finish — the two
        have to agree or he signs something that stays on his screen."""
        self.assertEqual(
            _notifications([_log("a", sig={})])["stale_unsigned_logbooks"], 1)

    def test_TODAYS_unsigned_log_is_NOT_flagged(self):
        """He is still working on it. The card is for a day that is over."""
        self.assertEqual(
            _notifications([_log("a", date=TODAY, sig=None)])["stale_unsigned_logbooks"], 0)

    def test_an_already_locked_log_is_not_flagged(self):
        self.assertEqual(
            _notifications([_log("a", sig=None, is_locked=True)])["stale_unsigned_logbooks"], 0)

    def test_a_deleted_log_is_not_flagged(self):
        self.assertEqual(
            _notifications([_log("a", sig=None, is_deleted=True)])["stale_unsigned_logbooks"], 0)

    def test_an_IMMEDIATE_type_is_never_flagged(self):
        """An immediate log froze when it was signed, so an unsigned one is a
        draft nobody finished — not a day left open."""
        self.assertEqual(
            _notifications([_log("a", log_type="osha_log", sig=None)])["stale_unsigned_logbooks"], 0)

    def test_both_end_of_day_types_are_flagged(self):
        out = _notifications([
            _log("a", sig=None),
            _log("b", log_type="ssc_daily_safety_log", sig=None),
        ])
        self.assertEqual(out["stale_unsigned_logbooks"], 2)

    def test_the_refs_carry_what_the_deep_link_needs(self):
        out = _notifications([_log("a", sig=None)])
        ref = out["stale_unsigned_logbook_refs"][0]
        self.assertEqual(set(ref), {"log_type", "date"})


class ItAgreesWithTheSweep(unittest.TestCase):
    """The two must never disagree about one log."""

    SHAPES = [None, {}, "data:image/png;base64,iVBOR", {"affirmed": False},
              {"paths": [[{"x": 1}]]}, AFFIRMED]

    def test_flagged_here_iff_refused_by_the_sweep(self):
        for sig in self.SHAPES:
            with self.subTest(sig=sig):
                flagged = _notifications(
                    [_log("a", sig=sig)])["stale_unsigned_logbooks"] == 1
                frozen = S._is_affirmed_signature(sig)
                self.assertEqual(flagged, not frozen,
                                 "the card and the sweep disagree about this signature")

    def test_both_read_the_same_predicate(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        notif = src[src.index("stale_unsigned_docs = await db.logbooks.find"):]
        notif = notif[:notif.index("return {")]
        self.assertIn("_is_affirmed_signature(d.get(\"cp_signature\"))", notif)

    def test_both_read_the_same_type_list(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        notif = src[src.index("stale_unsigned_docs = await db.logbooks.find"):]
        notif = notif[:notif.index("return {")]
        self.assertIn("END_OF_DAY_LOG_TYPES", notif)


if __name__ == "__main__":
    unittest.main()
