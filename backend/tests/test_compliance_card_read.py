"""What GET /api/projects/{id}/dob-logs serves a Compliance card, and that
serving it never asks the model.

Pins:
  * NO MODEL AT RENDER TIME: with the model caller, the HTTP client and the
    sweep all patched to raise, the read still answers 200 -- a stored model
    line is served as stored; an unswept coded row gets its code line; an
    unswept free-text row gets its deterministic line. Nothing raised, so
    nothing was called.
  * every row carries dob_text (what "Show DOB text" reveals);
  * the header's tracked_bins lists the project's own BIN AND each site BIN
    its records were filed under (588 Thomas S Boyland: 3255362, 3430621),
    not a BIN of records synced under a BIN the project was moved off;
  * the ECB hearing date AND time, and the penalty: an imposed amount, or
    "set at hearing" for $0 with the hearing pending;
  * the extractor stores the ECB fields from a real 6bgk-3dad record, and
    `penalty_imposed` -- not `amount_paid` -- is the penalty.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timezone
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

from async_fake_mongo import AsyncFakeDB  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# ECB 39558662P as NYC Open Data (6bgk-3dad) serves it, read 2026-10-24.
ECB_39558662P = {
    "isn_dob_bis_extract": "1842772", "ecb_violation_number": "39558662P",
    "ecb_violation_status": "ACTIVE", "bin": "3430621", "boro": "3", "block": "03540",
    "lot": "0025", "hearing_date": "20261118", "hearing_time": "930",
    "served_date": "20260902", "issue_date": "20260902", "severity": "CLASS - 2",
    "violation_type": "Construction", "respondent_name": "BLUEVIEW CONSTRUCTION INC",
    "violation_description": ("OBSERVED SIDEWALK SHED INSTALLED AT EXP# 1 UNDER APPLICATION "
                              "#B01409772-WITH LETTER OF INSTALLATION PROVIDED TO GC-CONTRARY TO PLANS"),
    "penality_imposed": "1250", "amount_paid": "0", "balance_due": "1250",
    "infraction_code1": "282",
    "section_law_description1": "28-105.12.2        WRK DOESN'T CONFORM TO APPROV DOCS AND/OR APPROV AMENDMENTS",
    "aggravated_level": "NO", "hearing_status": "PENDING",
    "_record_type": "violation", "_dataset": "6bgk-3dad",
}

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _row(rid, **kw):
    base = {"project_id": "proj1", "company_id": "co1", "nyc_bin": "3255362",
            "raw_dob_id": rid, "ai_summary": f"summary {rid}", "severity": "Action",
            "next_action": "", "detected_at": NOW, "is_deleted": False,
            "status_changed_at": NOW, "read_by_user": []}
    base.update(kw)
    return base


class _Explode(Exception):
    pass


def _boom(*a, **k):
    raise _Explode("the model was asked at render time")


async def _aboom(*a, **k):
    raise _Explode("the model was asked at render time")


class ReadServesStoredLinesOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.db = AsyncFakeDB()
        db = cls.db
        import asyncio
        rows = [
            # Stored model line (the sweep ran).
            _row("39558663R", record_type="violation", dataset="6bgk-3dad", ecb_status="RESOLVE",
                 infraction_code="2P7", description="I OBSERVED JERSEY BARRIERS AT STREET",
                 site_bin="3430621", hearing_date="20261118", hearing_time="1030",
                 penalty_imposed="2500", balance_due="2500",
                 plain_line={"en": "Jersey barriers at the street", "es": "Barreras Jersey en la calle"},
                 plain_line_source="llm", plain_line_version=1),
            # Unswept, coded ECB, $0 with the hearing pending.
            _row("39558662P", record_type="violation", dataset="6bgk-3dad", ecb_status="ACTIVE",
                 infraction_code="282", description="OBSERVED SIDEWALK SHED CONTRARY TO PLANS",
                 site_bin="3430621", hearing_date="20261118", hearing_time="930",
                 hearing_status="PENDING", penalty_imposed="0", balance_due="0"),
            # Unswept, coded DOB complaint on the project's own BIN.
            _row("3A41175", record_type="complaint", dataset="eabe-havv", complaint_type="05",
                 disposition_code="C2"),
            # Unswept free-text BIS violation, no code.
            _row("35000001", record_type="violation", dataset="3h2n-5cm9", violation_type="LL1198",
                 description="FAILURE TO MAINTAIN EXTERIOR WALL"),
            # A record synced while the project was on another BIN: its site
            # BIN must not reach the header.
            _row("OLD1", record_type="complaint", nyc_bin="3000001", site_bin="3999999",
                 complaint_type="05"),
        ]
        for r in rows:
            asyncio.run(db.dob_logs.insert_one(r))
        asyncio.run(db.projects.insert_one({"_id": "proj1", "name": "588 Thomas S Boyland",
                                            "company_id": "co1", "nyc_bin": "3255362",
                                            "is_deleted": False, "track_dob_status": True}))

    def _get(self):
        server = self.server
        user = {"_id": "u1", "id": "u1", "role": "admin", "company_id": "co1"}

        async def _user():
            return user
        server.app.dependency_overrides[server.get_current_user] = _user
        try:
            with ExitStack() as stack:
                stack.enter_context(patch.object(server, "db", self.db))
                # Everything that could reach the model raises if touched.
                stack.enter_context(patch.object(server, "_dob_plain_line_llm", _aboom, create=True))
                stack.enter_context(patch.object(server, "ServerHttpClient", _boom))
                lines = getattr(server, "_dob_plain_lines", None)
                if lines is not None:
                    stack.enter_context(patch.object(lines, "sweep", _aboom))
                    stack.enter_context(patch.object(lines, "plan_line", _aboom))
                resp = TestClient(server.app).get("/api/projects/proj1/dob-logs?date_range=all&limit=50")
        finally:
            server.app.dependency_overrides.pop(server.get_current_user, None)
        self.assertEqual(resp.status_code, 200, resp.text[:300])
        body = resp.json()
        return body, {l["raw_dob_id"]: l for l in body["logs"]}

    def test_no_model_call_and_the_stored_line_is_served(self):
        _, logs = self._get()
        self.assertEqual(logs["39558663R"]["plain_line"],
                         {"en": "Jersey barriers at the street", "es": "Barreras Jersey en la calle"})
        self.assertEqual(logs["39558663R"]["plain_line_source"], "llm")
        self.assertEqual(logs["39558662P"]["plain_line"]["en"], "Work does not match the approved plans")
        self.assertEqual(logs["39558662P"]["plain_line_source"], "code")
        self.assertEqual(logs["3A41175"]["plain_line"]["es"], "Trabajo sin permiso")
        self.assertEqual(logs["35000001"]["plain_line"]["en"], "DOB violation — see DOB text")
        self.assertEqual(logs["35000001"]["plain_line_source"], "fallback")

    def test_every_card_has_its_dob_text(self):
        _, logs = self._get()
        self.assertEqual(logs["35000001"]["dob_text"], "FAILURE TO MAINTAIN EXTERIOR WALL")
        self.assertIn("Permit — None", logs["3A41175"]["dob_text"])

    def test_header_lists_every_tracked_bin(self):
        body, _ = self._get()
        self.assertEqual(body["tracked_bins"], ["3255362", "3430621"])

    def test_ecb_hearing_and_penalty(self):
        _, logs = self._get()
        self.assertEqual(logs["39558662P"]["ecb_hearing"]["date"], "2026-11-18")
        self.assertEqual(logs["39558662P"]["ecb_hearing"]["time"], "09:30")
        self.assertEqual(logs["39558662P"]["ecb_penalty"], {"kind": "set_at_hearing"})
        self.assertEqual(logs["39558663R"]["ecb_hearing"]["time"], "10:30")
        self.assertEqual(logs["39558663R"]["ecb_penalty"],
                         {"kind": "amount", "amount": "2500", "balance_due": "2500"})
        self.assertIsNone(logs["3A41175"]["ecb_hearing"])
        self.assertIsNone(logs["3A41175"]["ecb_penalty"])


def _ecb_card():
    # Imported per test, so the read-path tests above still RUN (and fail on
    # their own assertions) against a tree without lib/ecb_card.
    from lib import ecb_card
    return ecb_card


class EcbCard(unittest.TestCase):
    TODAY = date(2026, 10, 24)

    def _ecb(self, **kw):
        return {"record_type": "violation", "dataset": "6bgk-3dad", "ecb_status": "ACTIVE",
                "hearing_date": "20261118", "hearing_time": "930", **kw}

    def test_clock(self):
        ecb_card = _ecb_card()
        self.assertEqual(ecb_card.hearing_clock("830"), "08:30")
        self.assertEqual(ecb_card.hearing_clock("1030"), "10:30")
        self.assertEqual(ecb_card.hearing_clock("09:30:00"), "09:30")
        self.assertIsNone(ecb_card.hearing_clock("2575"))
        self.assertIsNone(ecb_card.hearing_clock(""))

    def test_set_at_hearing_only_when_zero_and_pending(self):
        ecb_card = _ecb_card()
        self.assertEqual(ecb_card.penalty(self._ecb(penalty_imposed="0", hearing_status="PENDING"), self.TODAY),
                         {"kind": "set_at_hearing"})
        self.assertEqual(ecb_card.penalty(self._ecb(penalty_imposed=None), self.TODAY),
                         {"kind": "set_at_hearing"})        # no status, hearing ahead, unresolved
        self.assertIsNone(ecb_card.penalty(self._ecb(penalty_imposed="0", hearing_status="DISMISSED"),
                                           self.TODAY))
        self.assertIsNone(ecb_card.penalty(self._ecb(penalty_imposed="0", hearing_date="20260101"),
                                           self.TODAY))       # hearing passed
        self.assertEqual(ecb_card.penalty(self._ecb(penalty_imposed="1250", hearing_status="PENDING"),
                                          self.TODAY)["kind"], "amount")

    def test_not_an_ecb_row(self):
        ecb_card = _ecb_card()
        row = {"record_type": "violation", "dataset": "3h2n-5cm9", "hearing_date": "20261118"}
        self.assertIsNone(ecb_card.hearing(row, self.TODAY))
        self.assertIsNone(ecb_card.penalty(row, self.TODAY))


class Extractor(unittest.TestCase):
    def test_real_ecb_record(self):
        import server
        f = server._extract_violation_fields(dict(ECB_39558662P))
        self.assertEqual(f["penalty_imposed"], "1250")
        self.assertEqual(f["balance_due"], "1250")
        self.assertEqual(f["hearing_time"], "930")
        self.assertEqual(f["hearing_status"], "PENDING")
        self.assertEqual(f["ecb_status"], "ACTIVE")
        self.assertEqual(f["infraction_code"], "282")
        self.assertIn("WRK DOESN'T CONFORM", f["section_law_description"])
        # The field the card used to print as the penalty: amount_paid.
        self.assertEqual(f["penalty_amount"], "0")
        row = {"record_type": "violation", "dataset": "6bgk-3dad", **f}
        self.assertEqual(_ecb_card().penalty(row, date(2026, 10, 24))["amount"], "1250")


if __name__ == "__main__":
    unittest.main()
