"""The BC 3301.13.13 sheet attributes the log to the ACCOUNT that submitted it.

THE DEFECT. The render path handed `cs_attribution_for` the log's presence
block as the signer. That block is `{printed_name, arrived_at, departed_at,
departed_next_day}` -- no id and no registration number -- so `attribute_signer`
could match neither branch and every sheet resolved to `not_registered_cs`,
linked registration or not. All 17 filed super logs on 588 Thomas printed:

    Signed by Michael Cespedes. The construction superintendent registered for
    this project is Michael Cespedes.

-- the sentence reserved for a signer who is NOT the registered CS, naming the
same man twice. The filing gate had matched his account all along.

THE RULING (operator, 2026-10-08):
  1. The signer is the submitting account (`signed_by`, falling back to
     `created_by`), never the typed `printed_name`.
  2. Filed sheets re-render with the corrected sentence. Nothing stored changes.
  3. DOB calls his number a REGISTRATION number, not a licence.

The exact sentence below is the one the operator approved for those 17 logs.
"""
from __future__ import annotations

import asyncio
import copy
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server as S  # noqa: E402
from lib.logbook import cs_attribution as CA  # noqa: E402
from tests.source_text import code_of  # noqa: E402

PROJECT = "6a5f63bc147407d3261df2c7"
MICHAEL = "6a68b16ebe9c27dedf5cf47f"

APPROVED = ("Signed by Michael Cespedes, the construction superintendent "
            "registered for this project (registration 32299). Matched by "
            "account.")

#: What every one of the 17 sheets printed before this change.
WAS = ("Signed by Michael Cespedes. The construction superintendent registered "
       "for this project is Michael Cespedes.")

REGISTRATION = {
    "_id": "r1", "project_id": PROJECT, "full_name": "Michael Cespedes",
    "license_number": "32299", "license_number_normalized": "32299",
    "user_id": MICHAEL, "is_active": True, "is_deleted": False,
    "created_at": "2026-09-01T12:13:32",
}
ACCOUNT = {"_id": MICHAEL, "name": "Michael Cespedes",
           "full_name": "Michael Cespedes", "role": "superintendent"}
PRESENCE = {"printed_name": "Michael Cespedes", "arrived_at": "07:00",
            "departed_at": "15:30", "departed_next_day": False}


def _log(**over):
    lb = {"project_id": PROJECT, "date": "2026-09-08",
          "log_type": "site_superintendent_log", "status": "submitted",
          "signed_by": MICHAEL, "created_by": MICHAEL,
          "data": {"presence": dict(PRESENCE)}}
    lb.update(over)
    return lb


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]


class _Coll:
    def __init__(self, docs=()):
        self.docs = list(docs)
        self.reads = []

    def _hit(self, q):
        out = []
        for d in self.docs:
            ok = True
            for k, v in (q or {}).items():
                if isinstance(v, dict):
                    if "$ne" in v and d.get(k) == v["$ne"]:
                        ok = False
                elif d.get(k) != v:
                    ok = False
            if ok:
                out.append(d)
        return out

    def find(self, q=None, *a, **k):
        self.reads.append(q)
        return _Cursor(self._hit(q))

    async def find_one(self, q=None, *a, **k):
        self.reads.append(q)
        hits = self._hit(q)
        return copy.deepcopy(hits[0]) if hits else None


class _DB:
    def __init__(self, users=(), regs=()):
        self.users = _Coll(users)
        self.cs_registrations = _Coll(regs)


def _run(coro, db):
    with patch.object(S, "db", db), \
         patch.object(S, "to_query_id", lambda x: x):
        return asyncio.run(coro)


def _sheet_sentence(logbook, db):
    """What the render path prints: the same two calls it makes, in order."""
    async def go():
        signer = await S._cs_signer_for(logbook)
        attr = await S.cs_attribution_for(
            db, logbook["project_id"], logbook["date"], signer)
        return CA.attribution_sentence(attr)
    return _run(go(), db)


class TheApprovedSentence(unittest.TestCase):
    """The 17 filed logs, as they are stored."""

    def test_a_log_carrying_signed_by(self):
        db = _DB([ACCOUNT], [REGISTRATION])
        self.assertEqual(_sheet_sentence(_log(), db), APPROVED)

    def test_the_one_log_from_before_signed_by_existed(self):
        """2026-09-04 carries only `created_by`."""
        lb = _log(date="2026-09-04")
        del lb["signed_by"]
        db = _DB([ACCOUNT], [REGISTRATION])
        self.assertEqual(_sheet_sentence(lb, db), APPROVED)

    def test_what_the_presence_block_produced_is_what_they_printed(self):
        """THE BEFORE, PINNED. Passing the presence block -- the old call --
        gives the mismatch sentence. If this ever stops being true the defect
        description above is wrong, not merely stale."""
        db = _DB([ACCOUNT], [REGISTRATION])
        attr = _run(S.cs_attribution_for(db, PROJECT, "2026-09-08", PRESENCE), db)
        self.assertEqual(attr["state"], CA.NOT_REGISTERED_CS)
        self.assertEqual(CA.attribution_sentence(attr), WAS)


class TheSignerIsTheAccount(unittest.TestCase):

    def test_signed_by_wins_over_created_by(self):
        """The draft's opener and the signer can differ on a shared device;
        `signed_by` is the one written where the signature arrived."""
        db = _DB([ACCOUNT, {"_id": "opener", "name": "Somebody Else"}])
        signer = _run(S._cs_signer_for(_log(created_by="opener")), db)
        self.assertEqual(signer["id"], MICHAEL)
        self.assertEqual(signer["name"], "Michael Cespedes")

    def test_printed_name_does_not_choose_the_signer(self):
        """Typed text can be anyone. A log signed by Michael's account with a
        different name typed is still Michael's -- matched by account."""
        lb = _log()
        lb["data"]["presence"]["printed_name"] = "A Stranger"
        db = _DB([ACCOUNT], [REGISTRATION])
        self.assertEqual(_sheet_sentence(lb, db), APPROVED)

    def test_another_account_is_not_matched(self):
        """The fix is a better signer, not a looser rule: a CP's account on
        Michael's project still gets the mismatch sentence."""
        cp = {"_id": "cp1", "name": "Wilson Cp"}
        db = _DB([ACCOUNT, cp], [REGISTRATION])
        s = _sheet_sentence(_log(signed_by="cp1", created_by="cp1"), db)
        self.assertEqual(
            s, "Signed by Wilson Cp. The construction superintendent "
               "registered for this project is Michael Cespedes.")

    def test_an_unreadable_account_keeps_the_match_and_a_name(self):
        """The match is by id and needs no document; the typed name is the
        name of last resort."""
        db = _DB([], [REGISTRATION])
        signer = _run(S._cs_signer_for(_log()), db)
        self.assertEqual(signer["id"], MICHAEL)
        self.assertEqual(_sheet_sentence(_log(), db), APPROVED)

    def test_no_id_at_all_is_the_presence_block_unchanged(self):
        lb = _log()
        del lb["signed_by"]
        del lb["created_by"]
        signer = _run(S._cs_signer_for(lb), _DB())
        self.assertEqual(signer, PRESENCE)


class ItIsTheRenderPathsCall(unittest.TestCase):
    """The tests above exercise the helper; this pins that the sheet uses it."""

    def test_the_render_path_passes_the_account(self):
        code = code_of("server.py")
        self.assertTrue(
            "await cs_attribution_for(\n                db, project_id, date, "
            "await _cs_signer_for(logbook))" in code,
            "the CS sheet no longer resolves its signer through "
            "_cs_signer_for; it may be passing the presence block again")

    def test_and_not_the_presence_block(self):
        code = code_of("server.py")
        self.assertFalse(
            'cs_attribution_for(\n                db, project_id, date, '
            '(data or {}).get("presence")' in code,
            "the render path hands cs_attribution_for the presence block, "
            "which carries no id and no registration number")


class RegistrationNotLicence(unittest.TestCase):
    """DOB issues a construction superintendent a REGISTRATION number."""

    def test_no_sentence_calls_it_a_licence(self):
        lic = {"registered_name": "M R", "registered_licence": "32299",
               "signer_name": "M R"}
        for state in (CA.MATCHED_ACCOUNT, CA.MATCHED_LICENCE,
                      CA.NOT_REGISTERED_CS, CA.NO_REGISTRATION,
                      CA.REGISTERED_LATER, CA.UNDETERMINED):
            with self.subTest(state):
                s = CA.attribution_sentence({**lic, "state": state})
                # THE WORD, ANCHORED, either spelling -- not the substring,
                # which test_absence_literals_are_specific rightly refuses.
                self.assertIsNone(
                    re.search(r"\blicen[cs]e\b", s, re.I),
                    f"{state}: the sentence calls a DOB registration a licence")

    def test_the_two_server_sentences_that_name_the_number(self):
        code = code_of("server.py", raw=True)
        self.assertTrue("checked on the registration number." in code,
                        "the no-number 422 names the number")
        self.assertFalse("checked on the licence number." in code,
                         "the no-number 422 still calls it a licence")
        self.assertTrue(
            'f"WARNING: DOB registration {license_clean} is already the active '
            'CS on: "' in code, "the one-job warning names the number")
        self.assertFalse('f"WARNING: License {license_clean}' in code,
                         "the one-job warning still calls it a License")


if __name__ == "__main__":
    unittest.main(verbosity=2)
