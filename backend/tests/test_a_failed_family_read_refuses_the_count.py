"""A failed family read refuses the count (ruling 83, Roy 2026-10-29).

Ruling 51 routes a family's count to the count rule under every intent, and
the families are the project's (server.plan_count_families). That read
returned {} when it failed, and the gate then decided on the families of the
records in hand alone - the exact gap ruling 51 closed: a search for a ceiling
returns no fan schedule, and "exhaust fans: 13." went back to the union.

Now a failed read raises, gate_and_warrant turns it into `families_unread`,
and the gate refuses every clause that ANY family could make a count, with
the reason, under every intent but count. It never falls back.

Each test fails by assertion on main (75aa7d7a).
"""

import asyncio
import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_search as ps  # noqa: E402


def rec(**kw):
    base = {"page_id": "p1", "record_type": "text", "ordinal": 0, "tier": "text_layer",
            "source": "text_layer", "quote": "", "label": None, "subject_terms": [],
            "payload": {}, "sheet_number": "M-001.00", "file_id": "MH"}
    base.update(kw)
    return base


EF_SCHED = rec(sheet_number="M-200.00", record_type="schedule",
               subject_terms=["EXHAUST FAN SCHEDULE"],
               quote="EXHAUST FAN SCHEDULE TAG | QTY | CFM EF-1 | 20 | 50 EF-2 | 16 | 13",
               payload={"name": "EXHAUST FAN SCHEDULE",
                        "columns": [{"header": "TAG", "role": "identifier"},
                                    {"header": "QTY", "role": "quantity"},
                                    {"header": "CFM", "role": None}],
                        "rows": [["EF-1", "20", "50"], ["EF-2", "16", "13"]]})
EF_NOTE = rec(quote="EXHAUST FANS 13 TOTAL")
DIFFUSERS = rec(quote="DIFFUSERS 13")
EVERY = ("", "identify", "existence", "location", "geometry", "attribute")
WHY = "ServerSelectionTimeoutError('no primary')"


def gate(text, records, intent, unread=None):
    takes = "families_unread" in inspect.signature(ps.answer_is_grounded).parameters
    kw = {"families_unread": unread} if (unread is not None and takes) else {}
    return ps.answer_is_grounded(text, records, intent=intent, **kw)


class AFailedReadRefusesEveryCountAFamilyCouldMake(unittest.TestCase):

    def test_a_count_is_refused_with_the_reason(self):
        for it in EVERY:
            ok, bad = gate("exhaust fans: 13.", [EF_NOTE], it, unread=WHY)
            self.assertFalse(ok, it)
            self.assertTrue(any(WHY in b for b in bad), (it, bad))

    def test_it_never_falls_back_to_the_families_in_hand(self):
        # The schedule in hand would bind 20 EF-1 from its QTY cell; with the
        # project's families unread the count is refused all the same.
        self.assertTrue(gate("There are 20 EF-1.", [EF_SCHED], "count")[0])
        for it in EVERY:
            self.assertFalse(gate("There are 20 EF-1.", [EF_SCHED], it, unread=WHY)[0], it)
            self.assertFalse(gate("The building has 13 exhaust fans.", [EF_SCHED, EF_NOTE], it,
                                  unread=WHY)[0], it)
            # A plural no family in hand names - it might be the project's.
            self.assertFalse(gate("diffusers: 13.", [DIFFUSERS], it, unread=WHY)[0], it)

    def test_what_no_family_could_make_a_count_is_untouched(self):
        for it in ("", "identify", "attribute"):
            self.assertTrue(gate("EF-1: 50 CFM.", [EF_SCHED], it, unread=WHY)[0], it)
            self.assertTrue(gate("EF-2: 13.", [EF_SCHED], it, unread=WHY)[0], it)
        # A count question is the count rule's already; it reads no families.
        self.assertTrue(gate("There are 20 EF-1.", [EF_SCHED], "count", unread=WHY)[0])

    def test_a_read_that_succeeded_is_as_before(self):
        self.assertTrue(gate("There are 20 EF-1.", [EF_SCHED], "")[0])
        self.assertTrue(gate("diffusers: 13.", [DIFFUSERS], "")[0])


class ProductionRefusesWhenTheReadRaises(unittest.TestCase):

    def test_the_read_raises_and_the_gate_is_told_why(self):
        import server
        seen = {}

        def fake_gate(text, records, subject="", **kw):
            seen.clear()
            seen.update(kw)
            return text, "grounded"

        async def boom(_pid):
            raise RuntimeError("no primary")

        async def none(*_a, **_k):
            return {}

        with mock.patch.object(server, "gate_plan_answer", fake_gate), \
                mock.patch.object(server, "plan_count_families", boom), \
                mock.patch.object(server, "_plan_file_sources", none), \
                mock.patch.object(server, "plan_abbreviation_tables", none):
            for it in ("", "identify", "attribute"):
                try:
                    asyncio.run(server.gate_and_warrant("exhaust fans: 13.", [EF_NOTE], "x",
                                                        intent=it, project_id="p"))
                except Exception as e:  # the failed read must become a refusal
                    self.fail(f"the failed family read escaped the gate: {e!r}")
                self.assertIsNone(seen.get("families"), it)
                self.assertIn("no primary", seen.get("families_unread") or "", it)

    def test_the_hard_gate_refuses_it(self):
        import server
        kw = ({"families_unread": WHY} if "families_unread" in
              inspect.signature(server.gate_plan_answer).parameters else {})
        sent, outcome = server.gate_plan_answer("There are 20 EF-1.", [EF_SCHED], "exhaust fans",
                                                intent="", **kw)
        self.assertEqual(outcome, "ungrounded")

    def test_the_read_itself_raises_rather_than_answering_empty(self):
        import server

        async def broken(*_a, **_k):
            raise RuntimeError("no primary")

        with mock.patch.object(server, "_glyph_page_ids", broken):
            with self.assertRaises(RuntimeError):
                asyncio.run(server.plan_count_families("p"))


if __name__ == "__main__":
    unittest.main()
