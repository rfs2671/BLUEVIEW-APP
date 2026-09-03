"""A LEDGER WRITE THAT FAILS SILENTLY IS WORSE THAN ONE THAT FAILS LOUDLY.

Thirty-three signatures on the live project carry no `signature_events` row.
An auditor querying the ledger for those documents gets nothing back, and
NOTHING IN THE SYSTEM CAN TELL HIM WHICH OF TWO THINGS HE IS LOOKING AT:

    a signature that was made and whose ledger write failed, or
    a signature that was never made at all.

That indistinguishability is the defect. It is not a missing retry queue —
a retry queue would have shortened the list and left the same ambiguity for
whatever it could not deliver. What was missing is that no failure of a ledger
write left ANY trace at the moment it happened:

  * recordSignatureEvent (frontend/src/utils/signatureAudit.js) catches its own
    error, console.errors a bare message with no document identity, and returns
    null — so it never rejects, and the `.catch(...)` at every one of its
    thirteen call sites is dead code;
  * create_signature_event let an insert failure propagate with no log of its
    own, into callers that swallow;
  * the gate affirmation logged at WARNING, without the project or the date,
    so the one line that did exist could not be reconciled to a record;
  * and nothing anywhere ASKED whether a filed, signed logbook had a ledger
    row — which is the only question that finds a gap the client never
    reported because the client was offline, or crashed, or (the `if (docId)`
    guard) skipped the call entirely for want of a server id.

WHAT THIS ASSERTS, in the order a signature travels:

  1. the insert fails            -> an ERROR naming the document
  2. the endpoint fails          -> an ERROR naming the document AND the actor
  3. the gate affirmation fails  -> an ERROR naming project, date and worker
  4. the record is sealed        -> the ledger is asked, and a gap is an ERROR
  5. the night after it is filed -> the sweep asks the same question of every
                                    signed log it can still usefully name

Run:  python -m pytest tests/test_signature_ledger_observability.py -q
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
from tests.source_text import code_of  # noqa: E402

_CODE = code_of("server.py")

# 3am ET on the 18th — the hour the nightly tick runs.
NOW = datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc)

INK = {"paths": [[{"x": 1, "y": 2}]], "affirmed": True}
NO_INK = {}


def _errors(mock) -> str:
    """Every ERROR line this run emitted, joined — assertions read the text a
    person grepping Railway would read, not an argument tuple."""
    out = []
    for call in mock.call_args_list:
        out.append(" ".join(str(a) for a in call.args))
        out.append(str(call.kwargs))
    return "\n".join(out)


# ── fakes ───────────────────────────────────────────────────────────────────

class _EventsColl:
    """signature_events. `existing` is what count_documents answers with."""

    def __init__(self, existing=0, insert_raises=None, count_raises=None):
        self.existing = existing
        self.insert_raises = insert_raises
        self.count_raises = count_raises
        self.inserted = []
        self.counted = []

    async def count_documents(self, query):
        self.counted.append(query)
        if self.count_raises:
            raise self.count_raises
        if callable(self.existing):
            return self.existing(query)
        return self.existing

    async def insert_one(self, doc):
        if self.insert_raises:
            raise self.insert_raises
        self.inserted.append(doc)

        class _R:
            inserted_id = "evt1"
        return _R()


class _LogbooksColl:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, projection=None):
        q = query or {}

        def keep(d):
            for k, v in q.items():
                if isinstance(v, dict):
                    if "$in" in v and d.get(k) not in v["$in"]:
                        return False
                    if "$lt" in v and not (str(d.get(k, "")) < v["$lt"]):
                        return False
                    if "$gte" in v and not (str(d.get(k, "")) >= v["$gte"]):
                        return False
                    if "$ne" in v and d.get(k) == v["$ne"]:
                        return False
                elif d.get(k) != v:
                    return False
            return True

        rows = [d for d in self.docs if keep(d)]

        class _Cur:
            async def to_list(self, n=None):
                return rows
        return _Cur()

    async def find_one(self, q=None, projection=None):
        for d in self.docs:
            if str(d.get("_id")) == str((q or {}).get("_id")):
                return d
        return None


class _DB:
    def __init__(self, events=None, logs=None):
        self.signature_events = events or _EventsColl()
        self.logbooks = _LogbooksColl(logs)


# ── 1. the insert fails ─────────────────────────────────────────────────────

class TheInsertFailureIsNamed(unittest.TestCase):
    """create_signature_event is the ONLY place that knows the write failed.

    Both of its callers swallow — the endpoint hands a 500 to a client that
    catches it, and the gate catches it on purpose so a ledger write can never
    cost a man his check-in. If the failure is not recorded HERE it is recorded
    nowhere.
    """

    def _run(self, db):
        with patch.object(S, "db", db), \
                patch.object(S.logger, "error") as err:
            with self.assertRaises(RuntimeError):
                asyncio.run(S.create_signature_event(
                    document_type="logbook",
                    document_id="LB123",
                    event_type="cp_sign",
                    signer_name="R. Ruiz",
                    signer_role="cp",
                    signer_user_id="u9",
                    signature_data=INK,
                    content_snapshot={"log_type": "preshift_signin"},
                ))
            return _errors(err)

    def test_a_failed_insert_logs_an_error(self):
        db = _DB(_EventsColl(insert_raises=RuntimeError("mongo down")))
        self.assertTrue(self._run(db).strip(),
                        "a ledger insert that raised logged NOTHING — the "
                        "signature is on the document and the ledger row is "
                        "absent, with no record that it was ever attempted")

    def test_the_error_carries_the_document_identity(self):
        db = _DB(_EventsColl(insert_raises=RuntimeError("mongo down")))
        text = self._run(db)
        for token in ("LB123", "cp_sign", "logbook"):
            self.assertIn(token, text,
                          f"the failure log does not name {token!r}; without it "
                          "the line cannot be reconciled to a record")

    def test_the_error_carries_the_signer(self):
        db = _DB(_EventsColl(insert_raises=RuntimeError("mongo down")))
        self.assertIn("R. Ruiz", self._run(db),
                      "the failure log does not name the signer — 'a ledger "
                      "write failed' with no actor is not reconcilable")

    def test_it_is_tagged_for_grep(self):
        db = _DB(_EventsColl(insert_raises=RuntimeError("mongo down")))
        self.assertIn("[signature-ledger]", self._run(db),
                      "no stable tag: the operator has to know the sentence to "
                      "find the line")


# ── 2. the endpoint fails ───────────────────────────────────────────────────

class TheEndpointFailureNamesTheActor(unittest.TestCase):
    """POST /api/signature-events knows one thing create_signature_event does
    not: WHO was authenticated. A ledger gap is reconciled against a person."""

    def _run(self):
        payload = S.SignatureEventCreate(
            document_type="logbook",
            document_id="LB777",
            event_type="cp_sign",
            signer_name="R. Ruiz",
            signer_role="cp",
            signature_data=INK,
            content_snapshot={"date": "2026-08-17"},
        )

        class _Req:
            client = None

        db = _DB(
            _EventsColl(insert_raises=RuntimeError("mongo down")),
            [{"_id": "LB777", "log_type": "preshift_signin",
              "project_id": "PRJ42", "date": "2026-08-17"}],
        )
        with patch.object(S, "db", db), patch.object(S.logger, "error") as err:
            with self.assertRaises(Exception):
                asyncio.run(S.record_signature_event(
                    payload, _Req(),
                    {"id": "u9", "role": "cp", "full_name": "R. Ruiz"},
                ))
            return _errors(err)

    def test_the_endpoint_logs_the_failure(self):
        self.assertIn("[signature-ledger]", self._run(),
                      "the endpoint let the failure out with no tagged log")

    def test_it_names_the_authenticated_actor(self):
        self.assertIn("u9", self._run(),
                      "the endpoint knows the authenticated user id and did not "
                      "record it — the one identity the client cannot forge")

    def test_it_names_the_project_and_the_date(self):
        text = self._run()
        for token in ("PRJ42", "2026-08-17"):
            self.assertIn(token, text,
                          f"the endpoint already reads the logbook to resolve "
                          f"its log type; it must carry {token!r} into the "
                          "failure so the gap is reconcilable without a second "
                          "query")


# ── 3. the gate affirmation ─────────────────────────────────────────────────

class TheGateAffirmationFailureIsAnError(unittest.TestCase):
    """The pre-shift affirmation is the only signature event the SERVER writes
    on its own. It is deliberately fail-soft — a ledger write must never cost a
    man his check-in — which makes the log line the entire record of the gap."""

    # NOTE ON WHAT IS ASSERTED. `code_of` strips comments and docstrings, so
    # these read the executable text and the string literals in it — which is
    # exactly the log line an operator would grep for.
    ANCHOR = "[signature-ledger] AFFIRMATION NOT RECORDED"

    def test_it_logs_at_error_not_warning(self):
        self.assertNotIn(
            '[gate] affirmation signature event failed for ', _CODE,
            "the gate's affirmation failure is still the old WARNING: an "
            "affirmation that did not reach the ledger is a missing signed "
            "record, not a degraded nicety")
        i = _CODE.find(self.ANCHOR)
        self.assertGreater(i, 0, "the gate's affirmation failure is not "
                                 "reported under the ledger tag")
        self.assertIn("logger.error", _CODE[i - 200:i],
                      "the gate's affirmation failure is not at ERROR level")

    def test_the_gate_failure_carries_project_and_date(self):
        i = _CODE.find(self.ANCHOR)
        self.assertGreater(i, 0, "the gate's affirmation failure log is gone")
        window = _CODE[i:i + 900]
        for token in ("project_id", "eastern_date", "worker"):
            self.assertIn(token, window,
                          f"the gate's failure log does not carry {token!r} — "
                          "the ledger is queried by document, and an "
                          "affirmation's document id IS (project, eastern "
                          "date), so a line without them names nothing "
                          "queryable")


# ── 4. sealing the record asks the ledger ───────────────────────────────────

class FinalizeAsksTheLedger(unittest.TestCase):
    """Finalize is the act that makes a log IMMUTABLE. Its completeness gate has
    already refused a log with no cp_signature, so by the line after the lock
    the document is signed by definition — and if the ledger holds nothing for
    it, that is the 33 happening again, observed at the only moment anything
    could still be reconstructed."""

    def test_finalize_counts_the_ledger_rows_for_the_document(self):
        i = _CODE.find("async def finalize_logbook")
        self.assertGreater(i, 0)
        body = _CODE[i:i + 6000]
        self.assertIn("signature_event_count(db,", body,
                      "finalize_logbook seals a signed record without ever "
                      "asking whether the ledger has a row for it")

    def test_finalize_logs_the_gap_under_the_ledger_tag(self):
        i = _CODE.find("async def finalize_logbook")
        body = _CODE[i:i + 6000]
        self.assertIn("[signature-ledger]", body,
                      "finalize_logbook does not report a ledger gap under the "
                      "one grepable tag")


# ── 5. the nightly reconciliation ───────────────────────────────────────────

def _gap_sweep(db, now=NOW):
    return asyncio.run(S.sweep_signature_ledger_gaps(db, now))


class TheSweepFindsGapsNobodyReported(unittest.TestCase):
    """THE ONLY DETECTOR THAT SEES THE OFFLINE GAP.

    A CP signs with no signal. The draft drains later through draftSync, which
    pushes cp_signature and status:'submitted' and has never called
    recordSignatureEvent — so the log is filed, signed, and the ledger never
    hears about it, on a device that reported nothing because nothing failed
    there. No client-side log exists to find. Only a server-side question about
    the filed record can find it, and it must be asked after the client has had
    its chance, not during the request that races it.
    """

    def _filed(self, _id="LB1", date="2026-08-17", sig=INK, **over):
        doc = {"_id": _id, "project_id": "PRJ42", "company_id": "c1",
               "log_type": "daily_jobsite", "date": date, "status": "submitted",
               "is_deleted": False, "cp_signature": sig, "cp_name": "R. Ruiz",
               "created_by": "u9"}
        doc.update(over)
        return doc

    def test_a_signed_filed_log_with_no_ledger_row_is_reported(self):
        db = _DB(_EventsColl(existing=0), [self._filed()])
        with patch.object(S.logger, "error") as err:
            out = _gap_sweep(db)
        self.assertEqual(out["gaps"], 1)
        text = _errors(err)
        for token in ("LB1", "PRJ42", "2026-08-17", "daily_jobsite", "R. Ruiz"):
            self.assertIn(token, text,
                          f"the gap report does not name {token!r} — an auditor "
                          "reconciling it has to go back to Mongo for the one "
                          "fact the detector already had in hand")

    def test_a_log_that_has_its_ledger_row_is_not_reported(self):
        db = _DB(_EventsColl(existing=1), [self._filed()])
        with patch.object(S.logger, "error") as err:
            out = _gap_sweep(db)
        self.assertEqual(out["gaps"], 0)
        self.assertEqual(_errors(err).strip(), "",
                         "a complete record was reported as a gap — a detector "
                         "that cries wolf is a detector nobody reads")

    def test_an_unsigned_log_is_not_a_gap(self):
        """No signature, no ledger row, nothing missing. Reporting it would
        bury the real gaps under every draft in the system."""
        db = _DB(_EventsColl(existing=0), [self._filed(sig=NO_INK)])
        out = _gap_sweep(db)
        self.assertEqual(out["gaps"], 0)

    def test_todays_log_is_not_swept(self):
        """The client posts its ledger event moments AFTER the save returns.
        Asking inside that window manufactures a gap that does not exist — the
        exact false positive that would make this detector useless."""
        db = _DB(_EventsColl(existing=0), [self._filed(date="2026-08-18")])
        out = _gap_sweep(db)
        self.assertEqual(out["gaps"], 0)

    def test_it_never_raises(self):
        """It shares the 3am tick with the freeze and both detectors; one that
        threw would take the others down with it."""
        db = _DB(_EventsColl(count_raises=RuntimeError("down")),
                 [self._filed()])
        with patch.object(S.logger, "error"):
            out = _gap_sweep(db)
        self.assertIn("gaps", out)

    def test_the_nightly_tick_runs_it(self):
        i = _CODE.find("async def _logbook_nightly_tick")
        self.assertGreater(i, 0)
        tick = _CODE[i:i + 2000]
        self.assertIn("sweep_signature_ledger_gaps", tick,
                      "the reconciliation exists and nothing calls it — a "
                      "detector nobody runs is the thing this change exists to "
                      "prevent")


if __name__ == "__main__":
    unittest.main()
