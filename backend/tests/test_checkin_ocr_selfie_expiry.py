"""Coverage for the LIVE NFC check-in enhancements (checkin.html +
register_and_checkin):

  1. OCR autofill flow-through — a corrected expiration/card number sent on
     register_and_checkin flows into the SST certificate the backend builds.
  2. Selfie capture — the selfie goes to R2 under worker-selfies/{worker_id}/
     and the worker doc carries the KEY, not the bytes. A missing selfie never
     blocks the check-in, and neither does a failed upload: object storage is
     not allowed to be the thing that turns a man away at the gate.
  3. EXPIRY RELAX (the deliberate behavior change) — an expired SST no longer
     hard-blocks; the worker checks in normally, a compliance_alerts row is
     still written, and dispatch_notification fires to the project's admins +
     assigned CP with kind="expired_sst_checkin". A dispatch failure is
     isolated (check-in still succeeds), and a same-day re-tap does not
     double-alert.

These exercise the live path ONLY — register_and_checkin in server.py. The
shadowed card_audit / worker_enrollments / R2 flow is not touched.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


# ── Minimal async Mongo fakes ─────────────────────────────────────────────

class _Result:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id
        self.matched_count = 1
        self.modified_count = 1


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._i = 0

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._docs):
            raise StopAsyncIteration
        d = self._docs[self._i]
        self._i += 1
        return d

    async def to_list(self, length=None):
        return list(self._docs)


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self._find_one = None      # value or callable(query) -> doc | None
        self._find_docs = []
        self.inserted = []
        self.updated = []
        self.raise_on_insert = False
        self._seq = 0

    def set_find_one(self, v):
        self._find_one = v
        return self

    async def find_one(self, query=None, *a, **k):
        v = self._find_one
        return v(query) if callable(v) else v

    def find(self, query=None, *a, **k):
        return _FakeCursor(self._find_docs)

    async def insert_one(self, doc, *a, **k):
        if self.raise_on_insert:
            raise RuntimeError("simulated insert failure")
        self._seq += 1
        _id = doc.get("_id") or f"{self.name}_{self._seq}"
        rec = dict(doc)
        rec["_id"] = _id
        self.inserted.append(rec)
        return _Result(_id)

    async def update_one(self, q, u, *a, **k):
        self.updated.append((q, u))
        return _Result("upd")

    async def count_documents(self, *a, **k):
        return 0


class _FakeDb:
    def __init__(self):
        self._c = {}

    def _get(self, name):
        if name not in self._c:
            self._c[name] = _FakeCollection(name)
        return self._c[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._get(name)

    def __getitem__(self, name):
        return self._get(name)


# ── Shared fixture helpers ────────────────────────────────────────────────

_TRADE = "Carpenter"
_COMPANY = "Acme Co"


def _make_db(*, existing_checkin=None):
    db = _FakeDb()
    db.nfc_tags.set_find_one({
        "tag_id": "tag1", "project_id": "proj1", "status": "active",
    })
    db.projects.set_find_one({
        "_id": "proj1",
        "name": "Test Tower",
        "company_id": "co_a",
        "admin_id": "admin_a",
        "trade_assignments": [{"trade": _TRADE, "company": _COMPANY}],
    })
    db.workers.set_find_one(None)        # new worker
    db.logbooks.set_find_one(None)
    db.checkins.set_find_one(existing_checkin)
    return db


def _body(**overrides):
    body = {
        "project_id": "proj1",
        "tag_id": "tag1",
        "name": "Jane Worker",
        "phone": "5551234567",
        "trade": _TRADE,
        "company": _COMPANY,
        "osha_number": "SST12345678",
        "osha_data": {"sst_number": "SST12345678", "expiration": None},
        "osha_card_image": "data:image/jpeg;base64,CARDIMG",
    }
    body.update(overrides)
    return body


def _client():
    return TestClient(server.app)


# ── Tests ─────────────────────────────────────────────────────────────────

class ExpiredSstRelaxTest(unittest.TestCase):
    """The one deliberate behavior change: expired SST → allow + alert."""

    def test_validate_expired_sst_is_warning_not_block(self):
        """Pure-function assertion: an expired SST cert no longer produces a
        block; it is downgraded to a warning and cleared stays True."""
        worker = {
            "certifications": [{
                "type": "SST_LIMITED",
                "expiration_date": datetime(2020, 1, 1, tzinfo=timezone.utc),
            }],
        }
        result = server.validate_worker_certifications(worker, {})
        self.assertTrue(result["cleared"], "expired SST must NOT block anymore")
        self.assertFalse(
            any(b.get("type") == "EXPIRED_SST" for b in result["blocks"]),
            "EXPIRED_SST must not be in blocks",
        )
        self.assertTrue(
            any(w.get("type") == "EXPIRED_SST" for w in result["warnings"]),
            "EXPIRED_SST must be present as a warning",
        )

    def test_expired_sst_checks_in_and_dispatches(self):
        db = _make_db()
        with patch.object(server, "db", db), \
             patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
             ) as mock_dispatch:
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(osha_data={
                    "sst_number": "SST12345678", "expiration": "01/01/2020",
                }),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        # NOT blocked — worker checks in normally.
        self.assertNotEqual(data.get("blocked"), True)
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("is_new_worker"))
        # compliance_alerts row still written (admin screen stays populated).
        self.assertEqual(len(db.compliance_alerts.inserted), 1)
        # Notification dispatched to the project's recipients.
        self.assertEqual(mock_dispatch.await_count, 1)
        kwargs = mock_dispatch.await_args.kwargs
        self.assertEqual(kwargs["kind"], "expired_sst_checkin")
        self.assertEqual(kwargs["project"]["_id"], "proj1")
        self.assertEqual(kwargs["source_kind"], "checkin")
        # source_id is keyed on (worker, EST check-in day) for idempotency —
        # it is the check-in day, NOT the card's expiration date.
        source_id = str(kwargs["source_id"])
        self.assertIn(":", source_id)
        self.assertFalse(source_id.endswith(":2020-01-01"))

    def test_dispatch_failure_is_isolated(self):
        """If dispatch_notification raises, the check-in STILL succeeds."""
        db = _make_db()
        with patch.object(server, "db", db), \
             patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
                 side_effect=RuntimeError("inbox down"),
             ):
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(osha_data={
                    "sst_number": "SST12345678", "expiration": "01/01/2020",
                }),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertNotEqual(data.get("blocked"), True)
        # Check-in was written despite the dispatch failure.
        self.assertEqual(len(db.checkins.inserted), 1)

    def test_same_day_retap_does_not_double_alert(self):
        """A second tap the same day short-circuits on the existing check-in
        and never re-dispatches (idempotency)."""
        existing = {
            "check_in_time": datetime.now(timezone.utc),
            "status": "checked_in",
        }
        db = _make_db(existing_checkin=existing)
        with patch.object(server, "db", db), \
             patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
             ) as mock_dispatch:
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(osha_data={
                    "sst_number": "SST12345678", "expiration": "01/01/2020",
                }),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json().get("message"), "Already checked in")
        self.assertEqual(mock_dispatch.await_count, 0)
        # No second check-in row created.
        self.assertEqual(len(db.checkins.inserted), 0)


class SelfieStorageTest(unittest.TestCase):
    """The selfie now goes to R2 AND stays inline. Two rulings shape this.

    Q1 — A FAILED UPLOAD RECORDS NOTHING. No field, no empty string, no URL. A
    URL that 404s is a claim the app cannot support and an empty string is a
    value that reads as a fact. An earlier version wrote
    `selfie_store_failed: True`; that invented a sentinel to carry a
    distinction, and two absences meaning different things is the shape that has
    bitten this project before.

    Q2 — THE BASE64 STAYS IN THIS PR. `_upload_to_r2` returning a URL proves the
    PUT returned, not that the object is readable, and this project has produced
    an unreachable file that way before. Until something verifies the object,
    the inline copy is the only one known to exist. Dropping it is a separate PR
    gated on head_object.

    Together they make the sentinel unnecessary, which is the point: a row with
    `selfie_image` and no `selfie_r2_key` IS "took one, upload failed"; a row
    with neither is "declined". Real data, not a flag.

    Every test patches server._upload_to_r2 rather than boto3 — that function is
    the ONE place a bucket and key are chosen, so patching it asserts what this
    code asks object storage to do and lets each outcome be produced exactly.
    """

    _SELFIE = "data:image/jpeg;base64,U0VMRklFQllURVM="   # b"SELFIEBYTES"

    def _post(self, upload, body=None):
        """One register-and-checkin with `upload` standing in for R2.

        Returns (response, worker_doc, upload_calls).
        """
        db = _make_db()
        calls = []

        def _fake_upload(file_bytes, r2_key, content_type="application/octet-stream"):
            calls.append((file_bytes, r2_key, content_type))
            return upload(file_bytes, r2_key, content_type)

        with patch.object(server, "db", db), \
             patch.object(server, "_upload_to_r2", _fake_upload), \
             patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
             ):
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(**(body if body is not None else {"selfie_image": self._SELFIE})),
            )
        worker_doc = db.workers.inserted[0] if db.workers.inserted else None
        return resp, worker_doc, calls

    # ── the happy path ──────────────────────────────────────────────────────

    def test_selfie_goes_to_r2_and_the_inline_copy_is_kept(self):
        resp, worker_doc, calls = self._post(lambda b, k, c: "https://cdn.example/" + k)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNotNone(worker_doc)

        # ONE upload, carrying the DECODED bytes: not the data URL, not base64.
        self.assertEqual(len(calls), 1)
        sent_bytes, key, content_type = calls[0]
        self.assertEqual(sent_bytes, b"SELFIEBYTES")
        self.assertEqual(content_type, "image/jpeg")

        # THE PREFIX, and the worker id inside it. Built from the id the doc was
        # actually inserted under, so a key derived from anything else cannot pass.
        worker_id = str(worker_doc["_id"])
        self.assertTrue(worker_id)
        self.assertEqual(key, "worker-selfies/" + worker_id + "/selfie.jpg")

        # The document names the object AND still holds the image (Q2).
        self.assertEqual(worker_doc.get("selfie_r2_key"), key)
        self.assertEqual(worker_doc.get("selfie_r2_url"), "https://cdn.example/" + key)
        self.assertEqual(worker_doc.get("selfie_image"), self._SELFIE)

    def test_the_bucket_is_never_the_object_locked_card_audit_one(self):
        """One bucket, distinct prefix. The card-audit bucket is object-locked
        with 7-year retention because a credential photo is evidence; a selfie
        is a spot-check aid and must not be written under a retention lock."""
        _, _, calls = self._post(lambda b, k, c: "https://cdn.example/x")
        key = calls[0][1]
        self.assertTrue(key.startswith("worker-selfies/"))
        self.assertNotIn("card-audit", key)
        self.assertNotIn("card_audit", key)

    # ── every failure records NOTHING (Q1) ──────────────────────────────────

    def _assert_no_pointer_but_flagged(self, worker_doc, why):
        """NO POINTER, and the event recorded.

        The two halves are different claims and both are asserted: a key or url
        would assert an object that is not there (forbidden, including `""`),
        while the boolean asserts only that an upload was attempted and did not
        land — which is true and is about the event, not the image.
        """
        for field in ("selfie_r2_key", "selfie_r2_url"):
            self.assertNotIn(field, worker_doc,
                             f"{why}: {field} must be ABSENT, not empty")
        self.assertIs(worker_doc.get("selfie_upload_failed"), True,
                      f"{why}: the attempt is recorded")

    def test_a_raising_upload_does_not_fail_the_checkin_and_records_nothing(self):
        def _boom(b, k, c):
            raise RuntimeError("R2 is down")

        resp, worker_doc, calls = self._post(_boom)

        # THE GATE HOLDS. A man at the turnstile is not turned away because
        # object storage is unreachable.
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("success"))
        self.assertEqual(len(calls), 1)

        self._assert_no_pointer_but_flagged(worker_doc, "raising upload")
        # And the selfie is NOT lost: the inline copy is what makes silence safe.
        self.assertEqual(worker_doc.get("selfie_image"), self._SELFIE)

    def test_r2_unconfigured_records_nothing(self):
        """_upload_to_r2 returns "" when R2 is not set up. That is not an
        exception and is easy to read as success. It is not one, and `""` must
        never be stored: an empty string is a value."""
        resp, worker_doc, calls = self._post(lambda b, k, c: "")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(calls), 1)
        self._assert_no_pointer_but_flagged(worker_doc, "unconfigured R2")
        self.assertEqual(worker_doc.get("selfie_image"), self._SELFIE)

    def test_undecodable_payload_is_never_uploaded(self):
        junk = "data:image/jpeg;base64,"
        resp, worker_doc, calls = self._post(
            lambda b, k, c: "https://cdn.example/x", body={"selfie_image": junk})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(calls, [], "junk is not handed to R2 at all")
        self._assert_no_pointer_but_flagged(worker_doc, "undecodable payload")

    # ── the two absences stay distinguishable, WITHOUT a sentinel ───────────

    def test_the_five_states_are_all_distinguishable(self):
        """THE WHOLE JUSTIFICATION FOR THE BOOLEAN, as one table.

        Four states were already distinguishable from stored data. The fifth
        collapsed into "no selfie taken" with nothing to tell them apart, and a
        pointer could not be used to fix it because a pointer to a missing
        object is a claim the app cannot support. A boolean recording the EVENT
        can, because it says an upload was attempted and did not land rather
        than saying a photo is somewhere.

        Note the redundancy while Q2 holds: `selfie_image` currently separates
        4 from 5 on its own. It stops doing so when the strip PR lands, which
        is exactly why the flag is written now.
        """
        seen = {}

        # 1. declined
        body = _body(); body.pop("selfie_image", None)
        _, seen["declined"], _ = self._post(lambda b, k, c: "", body=body)
        # 2. stored
        _, seen["stored"], _ = self._post(lambda b, k, c: "https://cdn.example/" + k)
        # 3. R2 unconfigured
        _, seen["unconfigured"], _ = self._post(lambda b, k, c: "")
        # 4. upload raised
        def _boom(b, k, c):
            raise RuntimeError("down")
        _, seen["raised"], _ = self._post(_boom)
        # 5. payload junk
        _, seen["junk"], _ = self._post(lambda b, k, c: "https://cdn.example/x",
                                        body={"selfie_image": "data:image/jpeg;base64,"})

        def shape(d):
            return (
                bool(d.get("selfie_r2_key")),
                bool(d.get("selfie_upload_failed")),
                bool(d.get("selfie_image")),
            )

        self.assertEqual(shape(seen["declined"]), (False, False, False),
                         "declined: nothing at all")
        self.assertEqual(shape(seen["stored"]), (True, False, True),
                         "stored: a real key, no failure flag")
        for s_ in ("unconfigured", "raised", "junk"):
            self.assertEqual(shape(seen[s_])[:2], (False, True),
                             f"{s_}: no pointer, attempt recorded")

        # AND THE ONE THAT MATTERS: declined and a failed upload are no longer
        # the same row, by the flag alone — which is what survives the strip.
        self.assertNotEqual(
            (shape(seen["declined"])[0], shape(seen["declined"])[1]),
            (shape(seen["unconfigured"])[0], shape(seen["unconfigured"])[1]),
            "declined vs upload-failed must differ WITHOUT relying on the base64")

    def test_checkin_succeeds_without_selfie(self):
        body = _body()
        body.pop("selfie_image", None)
        resp, worker_doc, calls = self._post(
            lambda b, k, c: "https://cdn.example/x", body=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json().get("success"))
        self.assertEqual(calls, [], "nothing offered, so nothing uploaded")
        self.assertIsNone(worker_doc.get("selfie_image"))
        # NOTHING OFFERED IS NOT A FAILURE. The flag records an attempt that did
        # not land; a worker who declined made no attempt, so the field is
        # absent. This is the pair that makes the flag mean something.
        for field in ("selfie_r2_key", "selfie_r2_url", "selfie_upload_failed"):
            self.assertNotIn(field, worker_doc, f"declined: {field} must be ABSENT")

    def test_a_returning_worker_with_no_selfie_gets_BOTH_copies(self):
        """THE RETURNING PATH IS A SECOND WRITE SITE, and it was uncovered.

        A mutation that stripped the inline copy here survived the first run:
        the only existing-worker test covered a worker who ALREADY had a selfie,
        so nothing exercised the branch that actually writes one. Q2 applies to
        both write sites or to neither.
        """
        db = _make_db()
        db.workers.set_find_one({
            "_id": "worker_existing",
            "name": "Jane Worker",
            "phone": "5551234567",
            # no selfie of either kind
        })
        calls = []

        def _fake_upload(file_bytes, r2_key, content_type="application/octet-stream"):
            calls.append((file_bytes, r2_key, content_type))
            return "https://cdn.example/" + r2_key

        with patch.object(server, "db", db),              patch.object(server, "_upload_to_r2", _fake_upload),              patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
             ):
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(selfie_image=self._SELFIE),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(calls), 1, "the selfie IS uploaded for a worker who has none")
        self.assertEqual(calls[0][1], "worker-selfies/worker_existing/selfie.jpg")

        written = {}
        for _q, u in db.workers.updated:
            written.update(u.get("$set", {}))
        self.assertEqual(written.get("selfie_image"), self._SELFIE,
                         "Q2: the inline copy is written on the returning path too")
        self.assertEqual(written.get("selfie_r2_key"),
                         "worker-selfies/worker_existing/selfie.jpg")

    def test_a_returning_worker_records_nothing_when_the_upload_fails(self):
        """Q1 on the returning path: inline copy yes, R2 fields absent."""
        db = _make_db()
        db.workers.set_find_one({
            "_id": "worker_existing", "name": "Jane Worker", "phone": "5551234567",
        })
        with patch.object(server, "db", db),              patch.object(server, "_upload_to_r2", lambda *a, **k: ""),              patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
             ):
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(selfie_image=self._SELFIE),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        written = {}
        for _q, u in db.workers.updated:
            written.update(u.get("$set", {}))
        self.assertEqual(written.get("selfie_image"), self._SELFIE)
        for field in ("selfie_r2_key", "selfie_r2_url"):
            self.assertNotIn(field, written, f"{field} must be ABSENT on failure")
        self.assertIs(written.get("selfie_upload_failed"), True,
                      "the returning path records the attempt too")

    def test_existing_inline_base64_is_left_alone(self):
        """NOT BACKFILLED, by ruling. A worker whose row already carries the old
        inline copy keeps it and is not re-uploaded."""
        db = _make_db()
        db.workers.set_find_one({
            "_id": "worker_existing",
            "name": "Jane Worker",
            "phone": "5551234567",
            "selfie_image": "data:image/jpeg;base64,OLDINLINE",
        })
        calls = []

        def _fake_upload(*a, **k):
            calls.append(a)
            return "https://cdn.example/x"

        with patch.object(server, "db", db), \
             patch.object(server, "_upload_to_r2", _fake_upload), \
             patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
             ):
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(selfie_image=self._SELFIE),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(calls, [], "an existing inline selfie is not re-uploaded")
        self.assertTrue(db.workers.updated, "the returning-worker path did update the row")
        for _q, u in db.workers.updated:
            written = u.get("$set", {})
            for field in ("selfie_image", "selfie_r2_key", "selfie_r2_url"):
                self.assertNotIn(
                    field, written,
                    field + " must not be written over an existing inline selfie")


class OcrCorrectionFlowThroughTest(unittest.TestCase):

    def test_corrected_ocr_values_flow_through_and_are_stored(self):
        """The (possibly corrected) card number + expiration sent from the
        form flow through register_and_checkin — stored on the worker doc and
        fed to the cert logic. A corrected FUTURE expiration reads as a valid
        SST (not blocked, no expired-alert). The complementary proof that a
        corrected expiration reaches the cert logic is
        ExpiredSstRelaxTest.test_expired_sst_checks_in_and_dispatches, where a
        corrected past expiration drives the EXPIRED_SST alert."""
        db = _make_db()
        with patch.object(server, "db", db), \
             patch.object(
                 server._notifications_inbox, "dispatch_notification",
                 new_callable=AsyncMock,
             ) as mock_dispatch:
            resp = _client().post(
                "/api/checkin/register-and-checkin",
                json=_body(
                    osha_number="CORRECTED99",
                    osha_data={
                        "sst_number": "CORRECTED99",
                        "card_type": "SST",
                        # WORKER, not LIMITED — "Limited" ceased to be a valid SST card in
                        # August 2020 and is now treated as a dead scheme, not a class.
                        "card_class": "WORKER",
                        "expiration": "01/01/2030",
                    },
                ),
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotEqual(resp.json().get("blocked"), True)
        # Corrected values were sent and stored inline on the worker doc.
        worker_doc = db.workers.inserted[0]
        self.assertEqual(worker_doc.get("osha_number"), "CORRECTED99")
        self.assertEqual(worker_doc.get("osha_data", {}).get("expiration"), "01/01/2030")
        # A future expiration is a valid SST → no expired-SST alert fires.
        self.assertEqual(mock_dispatch.await_count, 0)


if __name__ == "__main__":
    unittest.main()
