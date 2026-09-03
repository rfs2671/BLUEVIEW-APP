"""A SIGNATURE MADE WITH NO SIGNAL MUST STILL REACH THE LEDGER.

THE DEFECT. Every one of recordSignatureEvent's thirteen call sites guards on
`if (docId)`. Offline there is no server id, so the ledger call is SKIPPED --
not attempted, not failed, skipped -- and nothing on the device or the server
records that it was. draftSync drains the log hours later carrying
`cp_signature` and `status: 'submitted'` and has never written a signature
event. subcontractor_orientation.jsx:556 says in a comment that "an offline
sign is audited when it syncs". It was not. Thirty-three signatures on the live
project are in exactly that state.

THE SHAPE THIS ASSERTS. The row is DERIVED from the accepted document rather
than queued on the device, because a device queue is lost with the device and
the document is already durable through logbookDrafts + draftSync:

  1. offline -> drained -> EXACTLY ONE row, marked derived, carrying the
     CLIENT'S signing timestamp (SignaturePad stamps `affirmedAt` inside the
     signature object, so the signing instant survives the sync);
  2. the online client already wrote a row -> the derivation adds NOTHING, and
     the contemporaneous row keeps its genuine device and IP;
  3. the derived row never claims the SYNC device or IP as the signer's -- the
     one thing deriving really does cost is written down, not inferred;
  4. the idempotency key is the SIGNING ACT, not the arrival order: the server's
     own stamping of the signature must not change it, and a genuine re-sign
     must produce a second row;
  5. nothing is backfilled -- an unsigned document derives nothing;
  6. sweep_signature_ledger_gaps still reports the gaps that remain. A detector
     made vacuous by its own fix is worse than no fix.

Run:  python -m pytest tests/test_signature_ledger_offline_durability.py -q
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
from lib.logbook import signature_provenance as P  # noqa: E402

# The CP signed at 09:14 local, in a basement with no signal.
SIGNED_AT = "2026-08-17T13:14:05.000Z"
# The drain reached the server at 18:02 UTC, nearly five hours later.
SYNCED_AT = datetime(2026, 8, 17, 18, 2, 0, tzinfo=timezone.utc)

# What SignaturePad.handleConfirm actually emits (SignaturePad.js:245-252).
OFFLINE_SIG = {
    "paths": [[{"x": 1, "y": 2}, {"x": 3, "y": 4}]],
    "signerName": "R. Ruiz",
    "timestamp": SIGNED_AT,
    "affirmed": True,
    "affirmedAt": SIGNED_AT,
    "affirmedLang": "es",
}

LOG_DOC = {
    "_id": "LB_OFFLINE_1",
    "project_id": "P1",
    "company_id": "C1",
    "log_type": "preshift_signin",
    "date": "2026-08-17",
    "data": {"workers": [{"name": "J. Diaz", "had_injury": False,
                          "inspected_ppe": True}]},
    "cp_signature": OFFLINE_SIG,
    "cp_name": "R. Ruiz",
    "status": "submitted",
    "is_locked": True,
}

USER = {"id": "u9", "role": "cp", "full_name": "R. Ruiz",
        "assigned_projects": ["P1"], "company_id": "C1"}


# ── fakes ───────────────────────────────────────────────────────────────────

class _EventsColl:
    """signature_events, with enough query support for the ledger's selectors."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self._n = 0

    @staticmethod
    def _match(doc, q):
        for k, v in (q or {}).items():
            if isinstance(v, dict):
                if "$ne" in v and doc.get(k) == v["$ne"]:
                    return False
                if "$exists" in v and (k in doc) != v["$exists"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True

    def _live(self, q):
        return [d for d in self.rows if self._match(d, q)]

    async def count_documents(self, query):
        return len(self._live(query))

    async def find_one(self, query, projection=None):
        rows = self._live(query)
        return rows[0] if rows else None

    async def insert_one(self, doc):
        self._n += 1
        doc = dict(doc)
        doc["_id"] = f"evt{self._n}"
        self.rows.append(doc)

        class _R:
            inserted_id = doc["_id"]
        return _R()

    def find(self, query=None, projection=None):
        rows = self._live(query or {})

        class _Cur:
            def sort(self, *a, **k):
                return self

            async def to_list(self, n=None):
                return rows
        return _Cur()


class _LogbooksColl:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]
        self._n = 0

    @staticmethod
    def _match(d, q):
        for k, v in (q or {}).items():
            cur = d
            for part in k.split("."):
                cur = (cur or {}).get(part) if isinstance(cur, dict) else None
            if k == "_id":
                # serialize_id pops `_id` and writes `id` IN PLACE on the row
                # it returns, so a document the endpoint has already serialized
                # is still findable by the id it was created with.
                cur = d.get("_id") if "_id" in d else d.get("id")
                if str(cur) != str(v):
                    return False
                continue
            if isinstance(v, dict):
                if "$ne" in v and cur == v["$ne"]:
                    return False
                if "$lt" in v and not (str(cur or "") < v["$lt"]):
                    return False
                if "$gte" in v and not (str(cur or "") >= v["$gte"]):
                    return False
                if "$exists" in v and (cur is not None) != v["$exists"]:
                    return False
            elif cur != v:
                return False
        return True

    async def find_one(self, q=None, projection=None):
        # A COPY, like Mongo. serialize_id pops `_id` off whatever dict it is
        # handed, and a fake that returned the stored row would let that
        # mutation land on the collection itself — a test artifact that makes
        # every later lookup for the same document fail.
        for d in self.docs:
            if self._match(d, q or {}):
                return dict(d)
        return None

    def find(self, q=None, projection=None):
        rows = [dict(d) for d in self.docs if self._match(d, q or {})]

        class _Cur:
            async def to_list(self, n=None):
                return rows
        return _Cur()

    async def count_documents(self, q=None):
        return len([d for d in self.docs if self._match(d, q or {})])

    async def insert_one(self, doc):
        self._n += 1
        doc = dict(doc)
        doc["_id"] = doc.get("_id") or f"LB{self._n}"
        self.docs.append(doc)

        class _R:
            inserted_id = doc["_id"]
        return _R()

    async def update_one(self, q, update):
        for d in self.docs:
            if self._match(d, q or {}):
                d.update((update or {}).get("$set", {}))

                class _R:
                    matched_count = 1
                return _R()

        class _R0:
            matched_count = 0
        return _R0()


class _ProjectsColl:
    def __init__(self, docs=None):
        self.docs = docs or [{"_id": "P1", "name": "588 Thomas",
                              "company_id": "C1"}]

    async def find_one(self, q=None, projection=None):
        for d in self.docs:
            if str(d.get("_id")) == str((q or {}).get("_id")):
                return d
        return None


class _DB:
    def __init__(self, events=None, logs=None):
        self.signature_events = events if events is not None else _EventsColl()
        self.logbooks = _LogbooksColl(logs)
        self.projects = _ProjectsColl()


def _quiet(db):
    """Patch out everything a logbook write does that is not the ledger."""
    async def _noop(*a, **k):
        return None

    return [
        patch.object(S, "db", db),
        patch.object(S, "audit_log", _noop),
        patch.object(S, "_remember_other_activities", _noop),
        patch.object(S, "_enhance_logbook_photos", _noop),
        patch.object(S, "_purge_finalized_photo_base64", _noop),
        patch.object(S.asyncio, "create_task", lambda coro: coro.close()),
    ]


def _run(db, coro_factory):
    ctxs = _quiet(db)
    for c in ctxs:
        c.start()
    try:
        return asyncio.run(coro_factory())
    finally:
        for c in reversed(ctxs):
            c.stop()


def _rows(db):
    return [r for r in db.signature_events.rows if not r.get("is_deleted")]


# ── 1. the offline signature, drained ───────────────────────────────────────

class TheOfflineSignatureReachesTheLedger(unittest.TestCase):
    """THE ESSENTIAL CASE. Signed with no signal, drained hours later.

    draftSync pushes the content (create/update) and then re-applies the freeze
    (/finalize) for every locally-finalized draft -- which is every signed one,
    since freezeIfImmediate calls markFinalized for the ten immediate types and
    the two end-of-day editors call it directly. So the drain always touches
    the server twice, and the second touch is where the client's own window has
    demonstrably closed.
    """

    def _drain(self, db=None):
        db = db if db is not None else _DB()

        async def go():
            await S.create_logbook(
                S.LogbookCreate(
                    project_id="P1", log_type="preshift_signin",
                    date="2026-08-17", data=LOG_DOC["data"],
                    cp_signature=OFFLINE_SIG, cp_name="R. Ruiz",
                    status="submitted",
                ),
                current_user=USER,
            )
            # serialize_id mutates the stored doc in place (_id -> id), so the
            # id is read back off the row rather than off the create response.
            lb = db.logbooks.docs[-1]
            lb_id = str(lb.get("_id") or lb.get("id"))
            await S.finalize_logbook(lb_id, current_user=USER)
            return dict(lb, _id=lb_id)

        with patch.object(S, "datetime", S.datetime):
            lb = _run(db, go)
        return db, lb

    def test_the_drained_signature_has_a_ledger_row(self):
        db, _ = self._drain()
        self.assertEqual(
            len(_rows(db)), 1,
            "a logbook signed offline and drained later carries a CP signature "
            "and the ledger holds nothing for it — this is the 33 happening "
            "again, and nothing failed anywhere to report it")

    def test_there_is_exactly_one_row_not_two(self):
        db, _ = self._drain()
        self.assertEqual(
            len(_rows(db)), 1,
            "the drain touches the server twice (content push, then freeze) and "
            "produced more than one ledger row for a single signing act")

    def test_the_row_is_marked_derived(self):
        db, _ = self._drain()
        prov = P.provenance_of(_rows(db)[0])
        self.assertEqual(
            prov["state"], P.DERIVED,
            "a row the server derived from the document is indistinguishable "
            "from one the signing device wrote — an auditor would read the "
            "sync-time facts on it as the signer's")

    def test_the_row_carries_the_clients_signing_timestamp(self):
        db, _ = self._drain()
        row = _rows(db)[0]
        self.assertIn(
            "13:14", str(row.get("timestamp")),
            "the derived row is stamped with the SYNC time, not the time the "
            "person signed — SignaturePad stamps affirmedAt inside the "
            "signature object precisely so the signing instant survives")

    def test_the_signing_time_source_is_named(self):
        db, _ = self._drain()
        prov = P.provenance_of(_rows(db)[0])
        self.assertEqual(prov["signed_at_source"], P.SIGNED_AT_AFFIRMED_AT,
                         "the row does not say where its signing time came "
                         "from, so a fallback cannot be told from a real stamp")

    def test_the_row_names_the_document(self):
        db, lb = self._drain()
        row = _rows(db)[0]
        self.assertEqual(row.get("document_type"), "logbook")
        self.assertEqual(str(row.get("document_id")), str(lb["_id"]))

    def test_the_row_carries_the_signature_itself(self):
        db, _ = self._drain()
        self.assertTrue(
            S._has_signature_ink(_rows(db)[0].get("signature_data")),
            "the derived row records no ink — a ledger row that does not "
            "carry the mark it describes is not evidence of it")

    def test_the_snapshot_carries_the_servers_attestation(self):
        db, _ = self._drain()
        att = S.attestation_of(_rows(db)[0])
        self.assertEqual(
            att["state"], S.ATTESTATION_PRESENT,
            "the derived row records no attestation, so it reads as "
            "PREDATES_CAPTURE — the marker reserved for events written before "
            "attestation capture existed, quietly lying about a 2026 row")


# ── 2. the device and the IP are the thing that IS lost ─────────────────────

class TheLossIsRecordedNotInferred(unittest.TestCase):

    def _row(self):
        db = _DB()

        async def go():
            await S.create_logbook(
                S.LogbookCreate(
                    project_id="P1", log_type="preshift_signin",
                    date="2026-08-17", data=LOG_DOC["data"],
                    cp_signature=OFFLINE_SIG, cp_name="R. Ruiz",
                    status="submitted"),
                current_user=USER)
            _d = db.logbooks.docs[-1]
            await S.finalize_logbook(str(_d.get("_id") or _d.get("id")),
                                     current_user=USER)
        _run(db, go)
        return _rows(db)[0]

    def test_no_sync_time_device_is_recorded_as_the_signers(self):
        self.assertFalse(
            self._row().get("device"),
            "the derived row carries a device — but the only device available "
            "at derivation is the one that had signal LATER, which is not the "
            "device the signature was made on")

    def test_no_sync_time_ip_is_recorded_as_the_signers(self):
        self.assertIsNone(
            self._row().get("ip_address"),
            "the derived row carries an IP address belonging to the sync, not "
            "to the signing")

    def test_the_row_says_the_device_is_not_recorded(self):
        prov = P.provenance_of(self._row())
        self.assertEqual(
            prov["device_fidelity"], P.FIDELITY_NOT_RECORDED,
            "an EMPTY device field is indistinguishable from a device the "
            "capture failed to read — the loss must be stated, not left to be "
            "inferred from an absence")

    def test_the_row_says_the_ip_is_not_recorded(self):
        self.assertEqual(P.provenance_of(self._row())["ip_fidelity"],
                         P.FIDELITY_NOT_RECORDED)

    def test_the_derivation_names_the_server_path_that_wrote_it(self):
        self.assertTrue(
            P.provenance_of(self._row())["written_by"],
            "the row does not name the code that derived it, so it cannot be "
            "traced back to a path without deploy archaeology")


# ── 3. the online path keeps its genuine row ────────────────────────────────

class TheOnlineRowIsNotDuplicated(unittest.TestCase):
    """The client's own row is the PRIMARY. It has the real device and IP."""

    def _seeded(self):
        """A ledger row exactly as POST /signature-events would have left it."""
        key = S.signature_ledger_key("logbook", "LB_OFFLINE_1", "cp_sign",
                                     OFFLINE_SIG)
        return _EventsColl([{
            "document_type": "logbook",
            "document_id": "LB_OFFLINE_1",
            "event_type": "cp_sign",
            "version": 1,
            "signature_key": key,
            "signature_data": OFFLINE_SIG,
            "device": {"hardware_fingerprint": "Pixel|8|Android|14|android"},
            "ip_address": "72.229.14.8",
            P.EVENT_KEY: P.contemporaneous_provenance(),
            "is_deleted": False,
        }])

    def test_the_derivation_adds_nothing(self):
        db = _DB(events=self._seeded(), logs=[dict(LOG_DOC)])

        async def go():
            await S.finalize_logbook("LB_OFFLINE_1", current_user=USER)
        _run(db, go)
        self.assertEqual(
            len(_rows(db)), 1,
            "the server derived a SECOND row for a signature the online client "
            "had already recorded — one signing act, two ledger rows")

    def test_the_contemporaneous_row_is_untouched(self):
        db = _DB(events=self._seeded(), logs=[dict(LOG_DOC)])

        async def go():
            await S.finalize_logbook("LB_OFFLINE_1", current_user=USER)
        _run(db, go)
        row = _rows(db)[0]
        self.assertEqual(P.provenance_of(row)["state"], P.CONTEMPORANEOUS)
        self.assertEqual(row.get("ip_address"), "72.229.14.8",
                         "the genuine signing IP was overwritten or lost")

    def test_a_late_client_post_does_not_add_a_second_row(self):
        """The reverse race: the derivation won, then the client's POST lands.

        daily_jobsite fires recordSignatureEvent without awaiting it and then
        calls /finalize, so this ordering is reachable in the field.
        """
        db = _DB(logs=[dict(LOG_DOC)])

        async def go():
            await S.finalize_logbook("LB_OFFLINE_1", current_user=USER)
            # ...and now the client's own POST arrives for the same signature.
            await S.create_signature_event(
                document_type="logbook", document_id="LB_OFFLINE_1",
                event_type="cp_sign", signer_name="R. Ruiz", signer_role="cp",
                signer_user_id="u9", signature_data=OFFLINE_SIG,
                content_snapshot={"log_type": "preshift_signin"},
                device_info={"hardware_fingerprint": "Pixel|8"},
                ip_address="72.229.14.8",
                signature_key=S.signature_ledger_key(
                    "logbook", "LB_OFFLINE_1", "cp_sign", OFFLINE_SIG),
            )
        _run(db, go)
        self.assertEqual(
            len(_rows(db)), 1,
            "the client's post-save write landed on top of a derived row and "
            "made a duplicate — the ledger now shows one signature signed twice")


# ── 4. the idempotency key is the signing act ───────────────────────────────

class TheKeyIsTheSigningActNotTheArrivalOrder(unittest.TestCase):
    """Keyed on something real. Not on a counter, and not on who got there first."""

    def test_the_servers_own_stamping_does_not_change_the_key(self):
        """_finalize_cp_signature adds affirmed_received_at (and sometimes
        affirmation_flag) to the stored signature. The client posts the
        UNSTAMPED object. If those server fields entered the key, the two
        paths would compute different keys for one signature and every online
        signature would be recorded twice."""
        stamped = S._finalize_cp_signature(OFFLINE_SIG, "2026-08-17", SYNCED_AT)
        self.assertIn("affirmed_received_at", stamped,
                      "test premise broken: the server no longer stamps")
        self.assertEqual(
            S.signature_ledger_key("logbook", "LB1", "cp_sign", OFFLINE_SIG),
            S.signature_ledger_key("logbook", "LB1", "cp_sign", stamped),
            "the server's own stamp changed the idempotency key, so the "
            "client's row and the derived row describe the same signature "
            "under two different identities")

    def test_a_different_document_is_a_different_key(self):
        self.assertNotEqual(
            S.signature_ledger_key("logbook", "LB1", "cp_sign", OFFLINE_SIG),
            S.signature_ledger_key("logbook", "LB2", "cp_sign", OFFLINE_SIG))

    def test_a_genuine_re_sign_is_a_different_key(self):
        """The unaffirmed-signature repair re-affirms an existing log. That is a
        NEW signing act and it must produce its own row."""
        again = dict(OFFLINE_SIG, affirmedAt="2026-08-18T12:00:00.000Z",
                     timestamp="2026-08-18T12:00:00.000Z")
        self.assertNotEqual(
            S.signature_ledger_key("logbook", "LB1", "cp_sign", OFFLINE_SIG),
            S.signature_ledger_key("logbook", "LB1", "cp_sign", again),
            "re-signing a document collapsed onto the first signature's row, "
            "so the second attestation is not in the ledger at all")

    def test_a_different_mark_is_a_different_key(self):
        other = dict(OFFLINE_SIG, paths=[[{"x": 9, "y": 9}]])
        self.assertNotEqual(
            S.signature_ledger_key("logbook", "LB1", "cp_sign", OFFLINE_SIG),
            S.signature_ledger_key("logbook", "LB1", "cp_sign", other))

    def test_the_gate_affirmations_shape_gets_no_key(self):
        """THE ONE SHAPE A KEY WOULD DESTROY.

        The gate writes one affirmation event per worker, and every one of them
        shares a document id of (project, eastern date). Its signature_data is
        a REFERENCE to the stroke on the worker document — no ink, no client
        timestamp — so a key computed over what is left would be byte-identical
        for every worker who affirmed that day, and the first row inserted
        would swallow all the rest as duplicates.
        """
        affirmation = {"affirmed_signature_of": "worker1",
                       "affirmed_at": SYNCED_AT}
        self.assertIsNone(
            S.signature_ledger_key(
                "preshift_affirmation", "P1:2026-08-17", "worker_sign",
                affirmation),
            "a signature with no ink and no client stamp was given an "
            "idempotency key — on the gate's shared document id that key is "
            "the same for every worker, so one man's affirmation would be "
            "recorded and the rest dropped as duplicates of it")

    def test_two_workers_affirming_the_same_day_both_get_rows(self):
        db = _DB()

        async def go():
            for w in ("worker1", "worker2"):
                await S.create_signature_event(
                    document_type="preshift_affirmation",
                    document_id="P1:2026-08-17", event_type="worker_sign",
                    signer_name=w, signer_role="worker", signer_user_id=w,
                    signature_data={"affirmed_signature_of": w,
                                    "affirmed_at": SYNCED_AT},
                    content_snapshot={"project_id": "P1"},
                    signature_key=S.signature_ledger_key(
                        "preshift_affirmation", "P1:2026-08-17", "worker_sign",
                        {"affirmed_signature_of": w, "affirmed_at": SYNCED_AT}),
                )
        _run(db, go)
        self.assertEqual(len(_rows(db)), 2,
                         "two workers affirmed at the gate and the ledger "
                         "holds one row")


class ARowWrittenTodayCannotClaimToBeOld(unittest.TestCase):
    """An ABSENT provenance key means PREDATES_MARKING. A caller that simply
    did not say must therefore not be allowed to leave the key off."""

    def test_a_caller_that_says_nothing_is_recorded_as_undetermined(self):
        db = _DB()

        async def go():
            await S.create_signature_event(
                document_type="logbook", document_id="LB9",
                event_type="cp_sign", signer_name="R. Ruiz", signer_role="cp",
                signer_user_id="u9", signature_data=OFFLINE_SIG,
                content_snapshot={"log_type": "preshift_signin"})
        _run(db, go)
        self.assertEqual(
            P.provenance_of(_rows(db)[0])["state"], P.UNDETERMINED,
            "a row written today with no provenance reads as PREDATES_MARKING "
            "— the state reserved for rows written before provenance marking "
            "existed, so a new record would be claiming to be an old one")


# ── 5. nothing is fabricated ────────────────────────────────────────────────

class NothingIsBackfilled(unittest.TestCase):

    def test_an_unsigned_document_derives_no_row(self):
        doc = dict(LOG_DOC, cp_signature=None, status="submitted",
                   is_locked=True)
        db = _DB(logs=[doc])

        async def go():
            await S.ensure_signature_ledger_row(doc, written_by="test")
        _run(db, go)
        self.assertEqual(
            len(_rows(db)), 0,
            "a row was derived for a document nobody signed — that is a "
            "fabricated attestation, which is worse than a missing one")

    def test_an_inkless_signature_derives_no_row(self):
        doc = dict(LOG_DOC, cp_signature={})
        db = _DB(logs=[doc])

        async def go():
            await S.ensure_signature_ledger_row(doc, written_by="test")
        _run(db, go)
        self.assertEqual(len(_rows(db)), 0)

    def test_an_amendment_child_derives_no_row(self):
        """amend_logbook resets cp_signature to None: the child MUST be
        re-signed. So an amendment can never derive a row, and if that ever
        changes this fails rather than quietly minting an attestation the CP
        never made on the child."""
        db = _DB(logs=[dict(LOG_DOC)])

        async def go():
            await S.amend_logbook(
                "LB_OFFLINE_1",
                {"reason": "The 07:00 headcount was transcribed wrong."},
                current_user=USER)
        _run(db, go)
        self.assertEqual(len(_rows(db)), 0)


# ── 6. a row written before this existed says so ────────────────────────────

class TheOldRowsAreLabelledNotRewritten(unittest.TestCase):

    def test_an_unmarked_row_reads_as_predating_the_marking(self):
        self.assertEqual(
            P.provenance_of({"document_id": "LB1"})["state"],
            P.PREDATES_MARKING)

    def test_the_sentence_refuses_to_guess(self):
        s = P.provenance_sentence(P.provenance_of({}))
        self.assertIn("not evidence", s,
                      "the absence of provenance is reported as a fact about "
                      "the signature rather than about the record")

    def test_the_verify_endpoint_reports_provenance(self):
        db = _DB(events=_EventsColl([{
            "_id": "e1", "document_type": "logbook", "document_id": "LB1",
            "version": 1, "content_snapshot": {}, "signer": {},
            "content_hash": S.compute_content_hash({}), "is_deleted": False,
        }]))

        async def go():
            return await S.verify_signature_integrity("logbook", "LB1",
                                                      current_user=USER)
        out = _run(db, go)
        self.assertIn(
            "provenance", out["events"][0],
            "an auditor calling /signature-events/verify cannot tell a derived "
            "row from a contemporaneous one")


# ── 7. the detector is not made vacuous by its own fix ──────────────────────

class TheSweepStillFindsWhatRemains(unittest.TestCase):
    """The 33 are NOT backfilled, and an online client whose post-save write
    fails on an immediate type still leaves a gap. The nightly sweep must keep
    finding those."""

    def test_a_signed_filed_log_with_no_row_is_still_reported(self):
        db = _DB(logs=[{
            "_id": "LB_OLD", "project_id": "P1", "company_id": "C1",
            "log_type": "preshift_signin", "date": "2026-08-17",
            "status": "submitted", "cp_signature": OFFLINE_SIG,
            "cp_name": "R. Ruiz", "is_deleted": False,
        }])
        with patch.object(S.logger, "error") as err:
            out = asyncio.run(S.sweep_signature_ledger_gaps(
                db, now=datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc)))
        self.assertEqual(out["gaps"], 1,
                         "the sweep no longer reports a signed, filed log with "
                         "no ledger row — the new writer made the only "
                         "detector that can see the 33 vacuous")
        self.assertTrue(err.called)

    def test_a_log_the_server_derived_a_row_for_is_not_reported(self):
        key = S.signature_ledger_key("logbook", "LB_NEW", "cp_sign",
                                     OFFLINE_SIG)
        db = _DB(
            events=_EventsColl([{
                "document_type": "logbook", "document_id": "LB_NEW",
                "signature_key": key, "is_deleted": False,
                P.EVENT_KEY: P.derived_provenance(
                    written_by="finalize_logbook", derived_at=SYNCED_AT,
                    signed_at=SYNCED_AT,
                    signed_at_source=P.SIGNED_AT_AFFIRMED_AT),
            }]),
            logs=[{
                "_id": "LB_NEW", "project_id": "P1", "company_id": "C1",
                "log_type": "preshift_signin", "date": "2026-08-17",
                "status": "submitted", "cp_signature": OFFLINE_SIG,
                "cp_name": "R. Ruiz", "is_deleted": False,
            }])
        out = asyncio.run(S.sweep_signature_ledger_gaps(
            db, now=datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc)))
        self.assertEqual(out["checked"], 1)
        self.assertEqual(out["gaps"], 0,
                         "a derived row does not satisfy the sweep, so every "
                         "offline signature is reported as a gap forever")


if __name__ == "__main__":
    unittest.main(verbosity=2)
