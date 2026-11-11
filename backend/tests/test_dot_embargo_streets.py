"""The DOT holiday embargo covers DOT's LISTED streets, not the whole city.

Measured 2026-11-11 (read-only): production flagged 36 active, waiver-less DOT
permits -- 17 at 546 Saratoga Ave (Saratoga Ave, Pitkin Ave to Sutter Ave), 12
on Hopkinson Ave (Blake Ave to Sutter Ave), 7 on Walworth St (Flushing Ave to
Park Ave) -- and showed "Holiday embargo ... 17 active DOT permits have no
waiver" on 546's Compliance screen. DOT's own lists (NYC Open Data 4te8-9n3p
"Holiday Construction Embargo - Block" and jr6f-nsuv "- Intersection") name
none of those blocks. Pitkin Ave IS listed, and so is the Pitkin & Saratoga
intersection: 546's block ends there but is not itself on the list.

Rows are DOT's, recorded for these segments on 2026-11-11
(fixtures/dot_embargo/embargo_lists_2026-11-11.json).
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402
from lib import dot_embargo as E  # noqa: E402

LISTS = json.loads((Path(__file__).resolve().parent / "fixtures" / "dot_embargo"
                    / "embargo_lists_2026-11-11.json").read_text(encoding="utf-8"))
SARATOGA = LISTS["546 Saratoga"]
WEST_BROADWAY = LISTS["475 West Broadway (fixture)"]
B, I = E.EMBARGO_BLOCK_DATASET, E.EMBARGO_INTERSECTION_DATASET


def _listed(case, seg=None):
    seg = seg or case["segment"]
    return E.on_embargo_list(seg, case["rows"][B], case["rows"][I])


def _fetch(fail=False):
    async def fetch(dataset, params):
        if fail:
            return None
        for k, case in LISTS.items():
            if not k.startswith("_") and case["params"].get(dataset, {}).get("$where") == params.get("$where"):
                return copy.deepcopy(case["rows"][dataset])
        return []
    return fetch


def _permit(seg, street):
    """SYNTHETIC: an active, confirmed, waiver-less permit working through the
    season, on `seg`, with the street answer the sync stored."""
    r = {"record_type": "dot_permit", "number": "B022026244D99", "status": "ISSUED & PRINTED",
         "work_start": "2026-10-01T00:00:00.000", "expiration_date": "2026-12-31T23:59:59.000",
         "issue_date": "2026-09-01T00:00:00.000", "holiday_waiver": False, "segment": seg,
         "match": {"how": "address", "state": "confirmed"}}
    if street is not None:
        r["holiday_embargo_street"] = street
    return r


class DotsListDecides(unittest.TestCase):
    def test_546_saratogas_block_is_not_on_the_list(self):
        self.assertFalse(_listed(SARATOGA))

    def test_a_listed_block_is_on_it_in_either_direction(self):
        self.assertTrue(_listed(WEST_BROADWAY))
        seg = dict(WEST_BROADWAY["segment"])
        seg["from"], seg["to"] = seg["to"], seg["from"]
        self.assertTrue(_listed(WEST_BROADWAY, seg))

    def test_pitkin_between_legion_and_saratoga_is_listed(self):
        # The same recorded Saratoga rows include DOT's two Pitkin Ave blocks.
        seg = {"boro": "3", "on": "PITKIN AVE", "from": "SARATOGA AVE", "to": "LEGION ST"}
        self.assertTrue(_listed(SARATOGA, seg))

    def test_a_permit_at_the_listed_intersection_is_on_it_a_block_ending_there_is_not(self):
        at = {"boro": "3", "on": "SARATOGA AVE", "from": "PITKIN AVE", "to": "PITKIN AVE"}
        self.assertTrue(_listed(SARATOGA, at))
        self.assertFalse(_listed(SARATOGA))           # Saratoga, Pitkin -> Sutter

    def test_an_unusable_segment_cannot_be_checked(self):
        self.assertIsNone(E.embargo_list_params({"boro": "", "on": "SARATOGA AVE"}))
        self.assertIsNone(E.embargo_list_params({"boro": "3", "on": ""}))


class OnlyAListedStreetIsWarned(unittest.TestCase):
    TODAY = date(2026, 11, 11)

    def test_546s_permits_raise_no_banner_and_no_email(self):
        rows = [_permit(SARATOGA["segment"], False)]
        self.assertFalse(E.banner(rows, self.TODAY)["show"])
        self.assertEqual(E.due_sends(rows, date(2026, 11, 12)), [])

    def test_a_listed_streets_permit_still_does(self):
        rows = [_permit(WEST_BROADWAY["segment"], True)]
        self.assertTrue(E.banner(rows, self.TODAY)["show"])
        self.assertEqual(len(E.due_sends(rows, date(2026, 11, 12))), 1)

    def test_not_checked_is_never_a_warning(self):
        rows = [_permit(SARATOGA["segment"], None)]
        self.assertFalse(E.banner(rows, self.TODAY)["show"])


class TheSyncStoresDotsAnswer(unittest.TestCase):
    def _read(self, seg, fetch, stored=None):
        from tests.async_fake_mongo import AsyncFakeDB
        db = AsyncFakeDB()
        row = {"_id": "d1", "record_type": "dot_permit", "number": "B022026244D99", "segment": seg,
               **({"holiday_embargo_street": stored} if stored is not None else {})}
        db.dot_logs.docs.append(row)

        async def stips(dataset, params):
            if dataset == E.STIPULATION_DATASET:
                return [{"permitnumber": "B022026244D99", "stipulationid": "012", "stipulationfulltext": "x"}]
            return await fetch(dataset, params)
        with patch.object(server, "db", db):
            asyncio.run(server._dot_read_stipulations(row, stips, server.datetime.now(server.timezone.utc), {}))
        return db.dot_logs.docs[0]

    def test_546_is_stored_not_on_the_list(self):
        self.assertIs(self._read(SARATOGA["segment"], _fetch())["holiday_embargo_street"], False)

    def test_west_broadway_is_stored_on_it(self):
        self.assertIs(self._read(WEST_BROADWAY["segment"], _fetch())["holiday_embargo_street"], True)

    def test_a_failed_list_read_keeps_what_was_stored(self):
        self.assertIs(self._read(WEST_BROADWAY["segment"], _fetch(fail=True), stored=True)
                      ["holiday_embargo_street"], True)
        self.assertNotIn("holiday_embargo_street", self._read(SARATOGA["segment"], _fetch(fail=True)))


if __name__ == "__main__":
    unittest.main()
