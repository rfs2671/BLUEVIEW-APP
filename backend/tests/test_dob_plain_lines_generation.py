"""The plain-line sweep (lib/dob_plain_lines.sweep) with a FAKE model.

Pins:
  * the model is called once per free-text record and the answer is stored
    on the row: plain_line {en, es}, plain_line_source "llm", the model, a
    generated_at and the checker's verdict;
  * a second sweep calls the model again for nothing;
  * a refused line falls back to the record's code label (broad code), else
    to the generic line; the refusal is stored, and never re-asked;
  * a record with a specific code never reaches the model;
  * another row of the same record (a 311 status change inserts one) copies
    the stored answer instead of asking;
  * a failed CALL is retried on a later tick, at most MAX_TRIES times;
  * no key (llm=None): rows that need the model wait, the rest are decided;
  * an ECB row the DOB sync has not refreshed yet (no ecb_status) waits.
No real model is ever called.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("QWEN_API_KEY", "")
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

from async_fake_mongo import AsyncFakeDB  # noqa: E402
from lib import dob_plain_lines as P  # noqa: E402

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)

# The real DOB text of ECB 39558663R (infraction 2P7, "MISCELLANEOUS VIOLATIONS").
TEXT_2P7 = ("BC 3307.2- I OBSERVED JERSEY BARRIERS INSTALLED/OCCUPYING AT STREET AT EXP#1 "
            "-NO DOT PERMIT FOR LANE CLOSURE ON STREET -DOT PERMIT FOR FENCE EXTENSION EXP. "
            "8/26/26 , NO TEMPORARY TRAFFIC DEVICES PROVIDED AS P")
GOOD = {"en": "Jersey barriers in the street without a DOT permit",
        "es": "Barreras Jersey en la calle sin permiso del DOT"}
BAD = {"en": "Blueview Construction Inc left barriers without a permit",
       "es": "Blueview Construction Inc dejó barreras sin permiso"}


class FakeLLM:
    def __init__(self, reply=GOOD, fail=False):
        self.reply, self.fail, self.calls = reply, fail, []

    async def __call__(self, prompt, row):
        self.calls.append(row.get("raw_dob_id"))
        if self.fail:
            raise TimeoutError("fake timeout")
        return json.dumps(self.reply)


def _ecb(rid, code, text=TEXT_2P7, **kw):
    return {"project_id": "p1", "record_type": "violation", "dataset": "6bgk-3dad",
            "ecb_status": "ACTIVE", "raw_dob_id": rid, "infraction_code": code,
            "description": text, "is_deleted": False, **kw}


def _bis(rid, text="FAILURE TO OBTAIN DOT PERMIT FOR JERSEY BARRIERS IN STREET", **kw):
    return {"project_id": "p1", "record_type": "violation", "dataset": "3h2n-5cm9",
            "raw_dob_id": rid, "violation_type": "LL1198", "description": text,
            "is_deleted": False, **kw}


def _complaint(rid, cat="05"):
    return {"project_id": "p1", "record_type": "complaint", "dataset": "eabe-havv",
            "raw_dob_id": rid, "complaint_type": cat, "is_deleted": False}


def _db(*rows):
    db = AsyncFakeDB()
    for r in rows:
        asyncio.run(db.dob_logs.insert_one(dict(r)))
    return db


def _sweep(db, llm, **kw):
    return asyncio.run(P.sweep(db, project_ids=["p1"], llm=llm, model="Qwen/test-model", now=NOW, **kw))


def _row(db, rid):
    return next(d for d in db.dob_logs.docs if d["raw_dob_id"] == rid)


class OncePerRecordAndStored(unittest.TestCase):
    def test_called_once_per_record_and_stored(self):
        db = _db(_ecb("39558663R", "2P7"), _bis("35000001"))
        llm = FakeLLM()
        report = _sweep(db, llm)
        self.assertEqual(sorted(llm.calls), ["35000001", "39558663R"])
        self.assertEqual(report["calls"], 2)
        for rid in ("39558663R", "35000001"):
            row = _row(db, rid)
            self.assertEqual(row["plain_line"], GOOD)
            self.assertEqual(row["plain_line_source"], "llm")
            self.assertEqual(row["plain_line_model"], "Qwen/test-model")
            self.assertEqual(row["plain_line_generated_at"], NOW)
            self.assertEqual(row["plain_line_check"], {"ok": True, "reason": "ok"})
            self.assertEqual(row["plain_line_version"], P.PLAIN_LINE_VERSION)

    def test_a_second_sweep_does_not_call_the_model(self):
        db = _db(_ecb("39558663R", "2P7"), _bis("35000001"))
        _sweep(db, FakeLLM())
        again = FakeLLM()
        report = _sweep(db, again)
        self.assertEqual(again.calls, [])
        self.assertEqual(report["rows"], 0)

    def test_an_old_version_row_already_asked_is_not_asked_again(self):
        db = _db(_ecb("39558663R", "2P7"))
        _sweep(db, FakeLLM())
        _row(db, "39558663R")["plain_line_version"] = 0     # as after a version bump
        again = FakeLLM()
        _sweep(db, again)
        self.assertEqual(again.calls, [])
        self.assertEqual(_row(db, "39558663R")["plain_line"], GOOD)

    def test_another_row_of_the_same_record_copies(self):
        db = _db(_bis("311:1"))
        _sweep(db, FakeLLM())
        asyncio.run(db.dob_logs.insert_one(_bis("311:1")))
        again = FakeLLM()
        _sweep(db, again)
        self.assertEqual(again.calls, [])
        self.assertTrue(all(d["plain_line"] == GOOD for d in db.dob_logs.docs))


class Fallbacks(unittest.TestCase):
    def test_a_refused_line_falls_back_to_the_code_label(self):
        db = _db(_ecb("39558663R", "2P7"))
        llm = FakeLLM(reply=BAD)
        _sweep(db, llm)
        row = _row(db, "39558663R")
        self.assertEqual(llm.calls, ["39558663R"])
        self.assertEqual(row["plain_line_source"], "code")
        self.assertEqual(row["plain_line"], {"en": "Miscellaneous building code violation",
                                             "es": "Infracción variada del código de construcción"})
        self.assertFalse(row["plain_line_check"]["ok"])
        self.assertRegex(row["plain_line_check"]["reason"], r"'(inc|Blueview)'.* is not in the DOB text")
        self.assertEqual(row["plain_line_llm_raw"], BAD)
        # ...and is never asked again.
        again = FakeLLM()
        _sweep(db, again)
        self.assertEqual(again.calls, [])

    def test_a_refused_line_with_no_code_falls_back_to_the_generic_line(self):
        db = _db(_bis("35000001"))
        _sweep(db, FakeLLM(reply=BAD))
        row = _row(db, "35000001")
        self.assertEqual(row["plain_line_source"], "fallback")
        self.assertEqual(row["plain_line"]["en"], "DOB violation — see DOB text")

    def test_a_specific_code_never_reaches_the_model(self):
        db = _db(_ecb("39558662P", "282", text="OBSERVED SIDEWALK SHED CONTRARY TO PLANS"),
                 _complaint("3A41175"))
        llm = FakeLLM()
        _sweep(db, llm)
        self.assertEqual(llm.calls, [])
        self.assertEqual(_row(db, "39558662P")["plain_line"]["en"], "Work does not match the approved plans")
        self.assertEqual(_row(db, "3A41175")["plain_line"]["en"], "Work without a permit")
        self.assertTrue(all(d["plain_line_source"] == "code" for d in db.dob_logs.docs))

    def test_a_failed_call_is_retried_then_falls_back(self):
        db = _db(_ecb("39558663R", "2P7"))
        llm = FakeLLM(fail=True)
        for i in range(1, P.MAX_TRIES):
            _sweep(db, llm)
            row = _row(db, "39558663R")
            self.assertEqual(row.get("plain_line_llm_tries"), i)
            self.assertNotIn("plain_line_version", row)
        _sweep(db, llm)
        row = _row(db, "39558663R")
        self.assertEqual(len(llm.calls), P.MAX_TRIES)
        self.assertEqual(row["plain_line_source"], "code")
        self.assertIn("model call failed", row["plain_line_check"]["reason"])
        _sweep(db, llm)
        self.assertEqual(len(llm.calls), P.MAX_TRIES)


class Waiting(unittest.TestCase):
    def test_no_key_leaves_model_rows_undecided(self):
        db = _db(_ecb("39558663R", "2P7"), _complaint("3A41175"))
        report = _sweep(db, None)
        self.assertNotIn("plain_line_version", _row(db, "39558663R"))
        self.assertEqual(_row(db, "3A41175")["plain_line_source"], "code")
        self.assertEqual(report["waiting"], 1)

    def test_an_unrefreshed_ecb_row_waits(self):
        row = _ecb("39558662P", "282")
        del row["ecb_status"]
        db = _db(row)
        llm = FakeLLM()
        report = _sweep(db, llm)
        self.assertEqual(llm.calls, [])
        self.assertEqual(report["waiting"], 1)
        self.assertNotIn("plain_line", _row(db, "39558662P"))

    def test_the_budget_caps_calls_per_tick(self):
        db = _db(*[_bis(f"3500000{i}") for i in range(5)])
        llm = FakeLLM()
        _sweep(db, llm, budget=2)
        self.assertEqual(len(llm.calls), 2)
        _sweep(db, llm, budget=2)
        self.assertEqual(len(llm.calls), 4)


if __name__ == "__main__":
    unittest.main()
