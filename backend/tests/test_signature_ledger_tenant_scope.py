"""The signature ledger takes writes only from someone who may touch the record.

WHAT WAS OPEN (security audit B2, 2026-10-13):

  POST /signature-events/public  NO AUTH AT ALL. Any document_type except
      "logbook", any document_id, any `worker_id`. Its rows carried
      provenance written_by="gate" -- the same marker a real turnstile
      affirmation carries -- and the pre-shift sheet prints a COUNT of distinct
      signer ids under (project_id, date). So anyone holding a project id could
      raise the "N affirmations are on record" line on another company's filed
      sheet. Nothing called it: the gate writes its own rows server-side.

  POST /signature-events  any signed-in account, any document_type, any
      document_id. The logbook was read for its log type and never checked
      for existence, project or company. A row on a logbook also satisfies
      sweep_signature_ledger_gaps, so a stranger's row could hide a real gap.

Every app caller (13 editors, frontend/src/utils/signatureAudit.js) sends
document_type 'logbook'; that is now the only type the route accepts.
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import server  # noqa: E402

LOGBOOK_ID = "64b000000000000000000001"
PROJECT_A = "64a00000000000000000000a"

LOGBOOK = {"_id": LOGBOOK_ID, "log_type": "daily_jobsite",
           "project_id": PROJECT_A, "date": "2026-10-13"}
PROJECT = {"_id": PROJECT_A, "company_id": "company-A"}

OWNER = {"id": "u-a", "role": "cp", "company_id": "company-A"}
STRANGER = {"id": "u-b", "role": "admin", "company_id": "company-B"}


def _body(**over):
    d = dict(document_type="logbook", document_id=LOGBOOK_ID,
             event_type="cp_sign", signer_name="M Rivera", signer_role="cp",
             signature_data={"paths": ["M0 0"]}, content_snapshot={"x": 1})
    d.update(over)
    return server.SignatureEventCreate(**d)


def _request():
    r = MagicMock()
    r.client.host = "203.0.113.7"
    return r


def _fake_db(logbook=LOGBOOK, project=PROJECT):
    db = MagicMock()
    db.logbooks.find_one = AsyncMock(return_value=logbook)
    db.projects.find_one = AsyncMock(return_value=project)
    return db


def _post(user, body, db=None):
    """Returns (status, writes). status is 200 or the HTTPException code."""
    write = AsyncMock(return_value="evt1")
    with patch.object(server, "db", db or _fake_db()), \
            patch.object(server, "create_signature_event", write):
        try:
            asyncio.run(server.record_signature_event(body, _request(), user))
            status = 200
        except server.HTTPException as e:
            status = e.status_code
    return status, write.await_count


class TheOwningCompanyStillSigns(unittest.TestCase):
    def test_a_cp_of_the_logbooks_company_writes_its_row(self):
        self.assertEqual(_post(OWNER, _body()), (200, 1))


class AnotherCompanyCannotWrite(unittest.TestCase):
    def test_an_admin_of_another_company_is_refused_and_nothing_is_written(self):
        status, writes = _post(STRANGER, _body())
        self.assertIn(status, (403, 404))
        self.assertEqual(writes, 0)

    def test_a_signup_with_no_company_is_refused(self):
        status, writes = _post({"id": "u-c", "role": "cp", "company_id": None},
                               _body())
        self.assertIn(status, (403, 404))
        self.assertEqual(writes, 0)


class ARowNeedsARealLogbook(unittest.TestCase):
    def test_a_logbook_id_that_does_not_exist_is_refused(self):
        status, writes = _post(OWNER, _body(), db=_fake_db(logbook=None))
        self.assertEqual(status, 404)
        self.assertEqual(writes, 0)

    def test_a_logbook_whose_project_is_gone_is_refused(self):
        status, writes = _post(OWNER, _body(), db=_fake_db(project=None))
        self.assertEqual(status, 404)
        self.assertEqual(writes, 0)

    def test_any_other_document_type_is_refused(self):
        """The pre-shift affirmation ledger is keyed "{project}:{date}" and is
        printed as a count; the gate writes it server-side and nothing else
        may."""
        for doc_type in ("preshift_signature_affirmation", "worker_enrollment",
                         "Logbook_x", ""):
            status, writes = _post(
                OWNER, _body(document_type=doc_type,
                             document_id=f"{PROJECT_A}:2026-10-13"))
            self.assertIn(status, (400, 404), msg=doc_type)
            self.assertEqual(writes, 0, msg=doc_type)


class ThePublicEndpointIsGone(unittest.TestCase):
    def test_no_route_serves_it(self):
        paths = {getattr(r, "path", "") for r in server.app.routes}
        self.assertFalse("/api/signature-events/public" in paths)
        self.assertFalse(hasattr(server, "record_public_signature_event"))


if __name__ == "__main__":
    unittest.main()
