"""A CLASS THE WORKER TYPED, AND A WAY BACK TO THE CARD SCAN.

Three defects meet on backend/checkin.html and its two public endpoints. All
three were measured on the live company on 2026-09-15, not supposed.

  (c) THERE WAS NO WAY BACK TO A CARD SCAN. The gate deliberately skipped the
      card step for a returning worker — "a returning worker already has a card
      on file" — so his tap posted no osha_data and no image,
      build_worker_certifications hit `if suppressed or stored_exp is None:
      pass`, and the row was left exactly as it was. The ONLY route to a fresh
      read was registering as a NEW worker. That is how one man (Jose David
      Hernandez Pena) ended up with two worker documents.

  (d) MANUAL ENTRY HAD NO CLASS FIELD. When OCR failed, checkin.html collapsed
      the card to three keys — sst_number, issued, expiration — so every manual
      entry resolved to SST_UNSPECIFIED and landed in review as
      CLASS_UNVERIFIED. Permanently, by construction. SIX of the twelve flagged
      certifications on the live company got there this way.

  AND THE HOLE THE FIX FOR (d) WOULD HAVE FALLEN INTO. A class picked off a
      dropdown reaches resolve_card_class as ordinary `card_class` text, comes
      back `text_only` with review_reason None, and mints a CLEAN certification
      row out of the worker's own say-so. A worker naming his own class is
      evidence, not proof: it is stored, and it NEVER clears review.

WHAT EACH TEST HERE FAILS AGAINST, before the fix:
  1. self-reported -> review_reason None                    (the headline)
  2. self-reported -> needs_review False
  3. self-reported -> _sst_cert_state 'valid'
  4. a second self-reported entry CLEARS a flagged row      (via old_flagged)
  5. worker_needs_card_scan does not exist
  6. lookup-worker returns no needs_card_scan / card_scan_reason
  7. gate_failures records no name and no waiting time

Run:  python -m pytest backend/tests/test_self_reported_class_and_rescan.py -q
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

NOW = datetime(2026, 9, 15, 13, 21, tzinfo=timezone.utc)
FUTURE = "06/01/2029"
PAST = "06/01/2024"


def ocr(**kw):
    """A card payload shaped exactly like the gate posts one."""
    d = {
        "name": "Luis Ramirez", "sst_number": "SST1", "card_type": "SST",
        "card_class": None, "issued": None, "expiration": FUTURE,
        "card_dominant_color": None, "card_color_confidence": None,
        "card_color_conditions": [],
    }
    d.update(kw)
    return d


def build(existing=None, **kw):
    certs, _ = server.build_worker_certifications(
        list(existing or []), ocr(**kw), "SST1", "img", NOW)
    return certs


def sst_row(certs):
    return next(c for c in certs
                if str(c.get("type") or "") in server.RECOGNIZED_SST_TYPES)


# ═══════════════════════════════════════════════════════════════════════════
# 1 + 2 + 3. THE INVARIANT: self_reported is EVIDENCE, NEVER PROOF.
# ═══════════════════════════════════════════════════════════════════════════

class SelfReportedIsNeverCleanTest(unittest.TestCase):
    """THE HEADLINE. A class the worker named must never produce a clean row.

    Without the demotion every assertion in this class inverts: the picked
    class maps through _map_sst_class, resolve_card_class answers `text_only`
    with review_reason None, and the gate mints a confirmed-looking credential
    from a dropdown.
    """

    def _row(self, card_class="Supervisor", **kw):
        return sst_row(build(card_class=card_class,
                             class_source="self_reported", **kw))

    def test_review_reason_is_never_None(self):
        """The rule, stated exactly as the ruling states it."""
        self.assertIsNotNone(self._row()["review_reason"])

    def test_the_reason_names_what_happened(self):
        """CLASS_UNVERIFIED would be a lie — something WAS answered. The
        reviewer is checking a claim, not reading an illegible field."""
        self.assertEqual(self._row()["review_reason"], "CLASS_SELF_REPORTED")

    def test_it_stays_in_review(self):
        self.assertTrue(self._row()["needs_review"])

    def test_the_provenance_is_stored_on_the_row(self):
        """A proposed class is indistinguishable from a read one the moment it
        lands in Mongo unless the source lands with it."""
        self.assertEqual(self._row()["class_source"], "self_reported")

    def test_it_can_never_make_a_credential_valid(self):
        """A future expiry and a known class would otherwise read 'valid'."""
        self.assertEqual(
            server._sst_cert_state(self._row(), NOW), "unknown")

    def test_every_class_on_the_picker_behaves_the_same(self):
        """Not one special-cased value — the whole dropdown."""
        for picked in ("Worker", "Supervisor", "Temporary"):
            with self.subTest(picked=picked):
                row = self._row(card_class=picked)
                self.assertIsNotNone(row["review_reason"], picked)
                self.assertTrue(row["needs_review"], picked)

    def test_a_class_OCR_read_is_untouched(self):
        """THE OTHER HALF, and it is what keeps this from being a regression.
        The demotion fires on the MARKER, not on the presence of a class, so a
        class read off the card keeps the verdict it has always had."""
        row = sst_row(build(card_class="Supervisor"))
        self.assertIsNone(row["review_reason"])
        self.assertFalse(row["needs_review"])
        self.assertEqual(row["class_source"], "text_only")

    def test_a_more_specific_reason_wins(self):
        """CLASS_CONFLICTED says something CLASS_SELF_REPORTED cannot: his
        answer contradicts the card's own colour. Same precedence rule
        derive_cert_review already uses, and it is still never None."""
        row = sst_row(build(
            card_class="Supervisor", class_source="self_reported",
            card_dominant_color="BLUE", card_color_confidence="high"))
        self.assertEqual(row["review_reason"], "CLASS_CONFLICTED")
        self.assertTrue(row["needs_review"])

    def test_the_demoter_never_mutates_the_resolvers_answer(self):
        """Pure. resolve_card_class is being changed concurrently for the
        unmapped-colour fall-through and must not acquire a caller that
        rewrites its return value in place."""
        res = server.resolve_card_class(ocr(card_class="Supervisor"))
        before = dict(res)
        out = server.demote_self_reported_class(
            {"class_source": "self_reported"}, res)
        self.assertEqual(res, before)
        self.assertIsNot(out, res)

    def test_the_two_forcing_rules_share_one_list(self):
        """derive_cert_review (does a human see this?) and _sst_cert_state (may
        this read as valid?) are two sides of one rule. They were written out
        as the same tuple twice, which is how they drift."""
        self.assertIn("self_reported", server.UNCONFIRMED_CLASS_SOURCES)
        self.assertIn("color_only", server.UNCONFIRMED_CLASS_SOURCES)
        self.assertIn("conflict", server.UNCONFIRMED_CLASS_SOURCES)
        # AND NOT text_only — until the client reports colour, text_only is
        # EVERY card, and sweeping it in flags every worker on every site.
        self.assertNotIn("text_only", server.UNCONFIRMED_CLASS_SOURCES)


# ═══════════════════════════════════════════════════════════════════════════
# 4. IT MUST NOT CLEAR ITSELF ON THE SECOND TRY.
# ═══════════════════════════════════════════════════════════════════════════

class SelfReportedNeverAutoClearsTest(unittest.TestCase):
    """THE ROUTE THAT BYPASSED THE FLAG ENTIRELY.

    build_worker_certifications' `old_flagged` branch updates a flagged row in
    place from a new scan. It wrote the type, the expiry, the flag and the
    reason — and NOT class_source. So the row kept the PREVIOUS scan's
    provenance (or, on a row that predates colour, none at all) while carrying
    the new scan's class, and `_sst_cert_state` — which reads class_source off
    the row — returned 'valid'. A self-reported class would have cleared itself
    through this branch on the worker's second try, without the review flag
    ever being consulted.
    """

    def _existing_flagged(self):
        return [{
            "type": "SST_UNSPECIFIED",
            "card_number": "SST1",
            "issue_date": None,
            "expiration_date": None,
            "verified": False,
            "needs_review": True,
            "review_reason": "CLASS_UNVERIFIED",
            "expiration_raw_rejected": None,
            "extraction_completeness": 0.5,
        }]

    def test_the_flagged_row_is_corrected_but_not_cleared(self):
        certs = build(self._existing_flagged(),
                      card_class="Supervisor", class_source="self_reported")
        row = sst_row(certs)
        self.assertEqual(row["type"], "SST_SUPERVISOR")     # the gap is filled
        self.assertTrue(row["needs_review"])                # and still flagged
        self.assertIsNotNone(row["review_reason"])

    def test_the_updated_row_carries_THIS_scans_provenance(self):
        certs = build(self._existing_flagged(),
                      card_class="Supervisor", class_source="self_reported")
        self.assertEqual(sst_row(certs)["class_source"], "self_reported")

    def test_and_so_it_still_cannot_read_as_valid(self):
        certs = build(self._existing_flagged(),
                      card_class="Supervisor", class_source="self_reported")
        self.assertEqual(server._sst_cert_state(sst_row(certs), NOW), "unknown")

    def test_a_verified_row_is_still_never_touched(self):
        """Somebody looked at that card and confirmed it. A worker's own
        statement does not get to overwrite a human's."""
        verified = [{
            "type": "SST_FULL", "card_number": "SST1",
            "expiration_date": NOW + timedelta(days=400),
            "verified": True, "needs_review": False, "review_reason": None,
        }]
        certs = build(verified, card_class="Supervisor",
                      class_source="self_reported")
        row = sst_row(certs)
        self.assertEqual(row["type"], "SST_FULL")
        self.assertFalse(row["needs_review"])


# ═══════════════════════════════════════════════════════════════════════════
# 5. THE RE-SCAN DECISION.
# ═══════════════════════════════════════════════════════════════════════════

def worker_with(**cert):
    base = {
        "type": "SST_FULL", "card_number": "SST1",
        "expiration_date": NOW + timedelta(days=400),
        "verified": False, "needs_review": False, "review_reason": None,
        "class_source": "color_and_text",
    }
    base.update(cert)
    return {"_id": "w1", "name": "Luis Ramirez", "certifications": [base]}


class NeedsCardScanTest(unittest.TestCase):
    """WHO GETS ASKED, AND — just as load-bearing — WHO DOES NOT.

    A man with a clean card must not be asked to photograph it every morning:
    that is the behaviour the skip was written for and it is why this cannot
    simply always be True.
    """

    def test_a_clean_card_is_not_asked_again(self):
        need, reason = server.worker_needs_card_scan(worker_with(), NOW)
        self.assertFalse(need)
        self.assertIsNone(reason)

    def test_no_certification_at_all_is_asked(self):
        need, reason = server.worker_needs_card_scan(
            {"_id": "w1", "certifications": []}, NOW)
        self.assertTrue(need)
        self.assertEqual(reason, "MISSING_SST")

    def test_a_worker_document_with_no_cert_key_is_asked(self):
        need, _ = server.worker_needs_card_scan({"_id": "w1"}, NOW)
        self.assertTrue(need)

    def test_an_expired_card_is_asked(self):
        need, reason = server.worker_needs_card_scan(
            worker_with(expiration_date=NOW - timedelta(days=5)), NOW)
        self.assertTrue(need)
        self.assertEqual(reason, "EXPIRED_SST")

    def test_an_unread_class_is_asked(self):
        need, reason = server.worker_needs_card_scan(
            worker_with(type="SST_UNSPECIFIED", class_source=None), NOW)
        self.assertTrue(need)
        self.assertEqual(reason, "CLASS_UNVERIFIED")

    def test_a_self_reported_class_is_asked(self):
        """Which is what keeps (d) honest at the gate as well as in the queue:
        a worker who typed his class is still asked for the photo."""
        need, reason = server.worker_needs_card_scan(
            worker_with(class_source="self_reported"), NOW)
        self.assertTrue(need)
        self.assertEqual(reason, "CLASS_UNVERIFIED")

    def test_a_colour_only_class_is_asked(self):
        need, _ = server.worker_needs_card_scan(
            worker_with(class_source="color_only"), NOW)
        self.assertTrue(need)

    def test_one_good_card_among_several_is_enough(self):
        w = worker_with()
        w["certifications"].append({
            "type": "SST_UNSPECIFIED", "card_number": "OLD",
            "expiration_date": None, "verified": False, "needs_review": True,
        })
        self.assertFalse(server.worker_needs_card_scan(w, NOW)[0])

    def test_it_agrees_with_the_gates_own_definition_of_valid(self):
        """DERIVED, NOT RESTATED. The thing that decides whether to ask is the
        SAME function that decides whether a credential may read as valid, so
        the two can never disagree about one row. Asserting the identity is the
        point; asserting both sides by hand is how they drift.
        """
        rows = [
            {},
            {"expiration_date": NOW - timedelta(days=5)},
            {"type": "SST_UNSPECIFIED", "class_source": None},
            {"class_source": "self_reported"},
            {"class_source": "color_only"},
            {"class_source": "conflict"},
            {"expiration_date": None},
        ]
        for patch_kw in rows:
            with self.subTest(row=patch_kw):
                w = worker_with(**patch_kw)
                need, _ = server.worker_needs_card_scan(w, NOW)
                gate_says_valid = server._sst_cert_state(
                    w["certifications"][0], NOW) == "valid"
                self.assertEqual(need, not gate_says_valid)


# ═══════════════════════════════════════════════════════════════════════════
# 6 + 7. THE TWO PUBLIC ENDPOINTS.
# ═══════════════════════════════════════════════════════════════════════════

class _Result:
    def __init__(self):
        self.inserted_id = "new_id"
        self.matched_count = 1
        self.modified_count = 1
        self.upserted_id = None


class _CannedCollection:
    def __init__(self, value=None):
        self._value = value

    async def find_one(self, query=None, *a, **k):
        return self._value

    async def insert_one(self, doc, *a, **k):
        return _Result()

    async def update_one(self, q, u, *a, **k):
        return _Result()


class _CapturingCollection(_CannedCollection):
    """Keeps what was written, because the whole question here is what the row
    ends up holding."""

    def __init__(self, value=None):
        super().__init__(value)
        self.inserted = []

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(dict(doc))
        return _Result()


class _FakeDb:
    def __init__(self):
        self._c = {}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _CannedCollection()
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


_PHONE = "5551234567"


class LookupWorkerAnswersTheCardQuestionTest(unittest.TestCase):
    """THE DECISION IS MADE WHERE THE WORKER IS FIRST NAMED.

    /checkin/{project_id}/{tag_id}/info is the page's first call and looks like
    the natural home for it. It cannot hold this: /info runs from init() before
    any identity exists — no phone typed, no saved-identity lookup run — so it
    would have to be told who the worker is, and at that point it IS this
    endpoint. lookup-worker is the first call that names him, on both of its
    paths, and it is already where the other per-worker, server-computed
    boolean (`oriented_on_this_project`) lives.
    """

    def _lookup(self, worker):
        db = _FakeDb()
        db._c["workers"] = _CannedCollection(worker)
        db._c[server.WORKER_PROJECT_TRADES_COLLECTION] = _CannedCollection(None)
        with patch.object(server, "db", db):
            return TestClient(server.app).post(
                "/api/checkin/lookup-worker",
                json={"phone": _PHONE, "project_id": "projA"},
            )

    def test_a_flagged_worker_is_told_to_scan(self):
        w = worker_with(type="SST_UNSPECIFIED", class_source=None)
        w["phone"] = _PHONE
        body = self._lookup(w).json()
        self.assertIs(body["needs_card_scan"], True)
        self.assertEqual(body["card_scan_reason"], "CLASS_UNVERIFIED")

    def test_a_clean_worker_is_not(self):
        w = worker_with()
        w["phone"] = _PHONE
        body = self._lookup(w).json()
        self.assertIs(body["needs_card_scan"], False)
        self.assertIsNone(body["card_scan_reason"])

    def test_no_certifications_are_shipped_to_the_page(self):
        """This endpoint is PUBLIC and keyed on a phone number. A boolean and a
        reason code answer the page's question; the cert rows would make one
        man's credential history enumerable by anyone who knows his number."""
        w = worker_with()
        w["phone"] = _PHONE
        body = self._lookup(w).json()
        self.assertNotIn("certifications", body)

    def test_the_reason_is_a_code_and_not_an_english_sentence(self):
        """The gate is EN/ES. Every English string the backend has handed it
        has had to be un-rendered again (see FIX 3 on the blocked screen)."""
        w = worker_with(expiration_date=NOW - timedelta(days=5))
        w["phone"] = _PHONE
        reason = self._lookup(w).json()["card_scan_reason"]
        self.assertEqual(reason, reason.upper())
        self.assertNotIn(" ", reason)


class GateFailureRecordsWhoAndHowLongTest(unittest.TestCase):
    """TWO MEN WERE TURNED AWAY AND NOBODY KNOWS THEIR NAMES.

    2026-09-15, 588 Thomas: fingerprints fc47338d687a0d (13:21, 13:23) and
    b1a3cd8c8b019c (13:23, 13:48). Every field the collection holds was
    recorded — kind, attempts, language, fingerprint, detail — and a CP cannot
    call back a fingerprint. "A device failed" is not an incident anyone can
    act on; "Luis failed at 13:21 after waiting 38 seconds" is.
    """

    def _post(self, body):
        db = _FakeDb()
        cap = _CapturingCollection()
        db._c["gate_failures"] = cap
        db._c["projects"] = _CannedCollection(None)
        with patch.object(server, "db", db):
            resp = TestClient(server.app).post(
                "/api/checkin/gate-failure", json=body)
        return resp, cap.inserted

    def _base(self, **kw):
        d = {
            "kind": "card_ocr_http_failed",
            "detail": "Request failed",
            "project_id": None,
            "fingerprint_id": "fc47338d687a0d",
            "ocr_attempts": 2,
            "lang": "es",
        }
        d.update(kw)
        return d

    def test_the_typed_name_is_recorded(self):
        resp, rows = self._post(self._base(name="Luis Ramirez"))
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(rows[0]["name"], "Luis Ramirez")

    def test_the_client_side_wait_is_recorded(self):
        _, rows = self._post(self._base(name="Luis Ramirez", waited_ms=38000))
        self.assertEqual(rows[0]["waited_ms"], 38000)

    def test_a_failure_before_he_typed_anything_still_records(self):
        """The name is taken only if it is already on the form. Nothing is
        looked up and nothing is inferred from the fingerprint."""
        _, rows = self._post(self._base())
        self.assertIsNone(rows[0]["name"])
        self.assertIsNone(rows[0]["waited_ms"])

    def test_a_nullish_name_is_not_stored_as_a_name(self):
        """The model's answer for "I could not read this" is sometimes the
        string "null", and it has reached filed compliance PDFs as a worker's
        name before. A diagnostic table is not an exception."""
        _, rows = self._post(self._base(name="null"))
        self.assertIsNone(rows[0]["name"])

    def test_an_absurd_wait_is_refused(self):
        """A client-reported duration is untrusted input. Ten minutes is far
        past any plausible wait at a turnstile — beyond it is a clock, not a
        worker."""
        for bad in (-1, 10 ** 9, "soon", None):
            with self.subTest(bad=bad):
                _, rows = self._post(self._base(waited_ms=bad))
                self.assertIsNone(rows[0]["waited_ms"])

    def test_no_other_personal_field_is_accepted(self):
        """SCOPED TO ONE FIELD. The reversal of "no PII" buys the name and
        nothing else: a phone number, a card number or a frame posted here is
        not written."""
        _, rows = self._post(self._base(
            phone="5551234567", osha_number="SST1",
            image="data:image/jpeg;base64,AAAA"))
        row = rows[0]
        for leaked in ("phone", "osha_number", "image"):
            self.assertNotIn(leaked, row, leaked)

    def test_it_still_never_raises_into_the_workers_flow(self):
        """A telemetry write must never become a gate incident."""
        resp, _ = self._post({"kind": "nonsense", "waited_ms": {"a": 1}})
        self.assertEqual(resp.status_code, 204)


# ═══════════════════════════════════════════════════════════════════════════
# 8. THE GATE PAGE. It ships with the BACKEND deploy, not an EAS OTA, so it is
#    asserted from this suite and not from the frontend one.
# ═══════════════════════════════════════════════════════════════════════════

CHECKIN_HTML = (_BACKEND / "checkin.html").read_text(encoding="utf-8")


class TheGatePageCarriesTheNewFieldsTest(unittest.TestCase):
    """NOTE THE assertTrue. `assertIn(needle, CHECKIN_HTML)` PRINTS THE
    HAYSTACK — 127KB of escaped markup with the one fact that matters buried
    inside it. Same rule test_an_assertion_may_not_print_a_source_file.py
    pins for server.py, and it was broken here once before this line existed.
    """

    def _has(self, needle, why):
        self.assertTrue(needle in CHECKIN_HTML, why)

    def test_the_manual_form_has_a_class_field_at_all(self):
        """(d), as one assertion. There was no class input on this page."""
        self._has('id="regCardClass"', 'no card-class control on the gate page')

    def test_the_picker_offers_the_three_live_classes(self):
        for value in ('value="Worker"', 'value="Supervisor"',
                      'value="Temporary"'):
            with self.subTest(value=value):
                self._has(value, f'the class picker does not offer {value}')

    def test_it_offers_an_honest_dont_know(self):
        """So a wrong pick is never the path of least resistance."""
        self._has('cardClassUnsure', 'no "I\'m not sure" option')

    def test_it_does_not_offer_the_dead_limited_class(self):
        """Limited SST died in August 2020. Offering it invites a pick the
        resolver then has to refuse."""
        self.assertFalse('value="Limited"' in CHECKIN_HTML,
                         'the picker offers the dead Limited class')

    def test_the_page_marks_a_picked_class_as_self_reported(self):
        self._has("class_source = 'self_reported'",
                  'a picked class is not marked as the worker\'s own')

    def test_the_returning_screen_has_a_card_rescan_control(self):
        """(c), as one assertion."""
        self._has('id="btnRetScanCard"', 'no card re-scan control')
        self._has('startCardRescan()', 'the re-scan control opens nothing')

    def test_the_rescan_offer_is_gated_on_the_servers_answer(self):
        self._has('needs_card_scan === true',
                  'the re-scan offer is not gated on the server\'s answer')

    def test_check_in_now_survives_beside_it(self):
        """A REQUEST, NOT A REFUSAL. The gate does not stop a man working, so
        the scan button must not replace the check-in button."""
        region = CHECKIN_HTML[CHECKIN_HTML.index('id="screenReturning"'):
                              CHECKIN_HTML.index('id="screenRegister"')]
        self.assertTrue('onclick="quickCheckIn()"' in region,
                        'Check In Now is gone from the returning screen')
        self.assertTrue('id="btnRetScanCard"' in region,
                        'the scan control is not on the returning screen')

    def test_both_new_telemetry_fields_are_posted(self):
        """Scoped to reportGateFailure's own body rather than to the file: a
        source assertion that scans the whole page breaks the next time
        anything earlier happens to use the same word."""
        at = CHECKIN_HTML.index('function reportGateFailure(')
        body = CHECKIN_HTML[at:CHECKIN_HTML.index('\n}', at)]
        self.assertTrue('name: typedName' in body,
                        'reportGateFailure posts no name')
        self.assertTrue('waited_ms: waitedMs()' in body,
                        'reportGateFailure posts no waiting time')

    def test_every_new_string_is_bilingual(self):
        """This gate is EN/ES and a Spanish-speaking worker is the majority
        user. An English-only key is a blank on his screen."""
        keys = [
            'cardClassLabel', 'cardClassUnsure', 'cardClassWorker',
            'cardClassSupervisor', 'cardClassTemporary', 'cardClassNote',
            'cardCheckMissing', 'cardCheckExpired', 'cardCheckUnverified',
            'retScanCard', 'cardRescanWhy', 'cardRescanSubmit',
        ]
        for key in keys:
            with self.subTest(key=key):
                hits = len(re.findall(r'^\s*' + key + r':', CHECKIN_HTML,
                                      re.MULTILINE))
                self.assertEqual(hits, 2, f'{key} defined {hits}x, expected 2')

    def test_every_reason_code_the_server_can_send_has_copy(self):
        """DERIVED FROM THE SERVER'S OWN ANSWERS, not from a hand-kept list. A
        reason the page has no wording for renders as a fallback nobody chose.
        """
        cases = [
            {"_id": "w"},                                       # MISSING_SST
            worker_with(expiration_date=NOW - timedelta(days=5)),
            worker_with(type="SST_UNSPECIFIED", class_source=None),
        ]
        at = CHECKIN_HTML.index('const CARD_SCAN_REASON_KEYS')
        block = CHECKIN_HTML[at:CHECKIN_HTML.index('};', at)]
        for w in cases:
            _, reason = server.worker_needs_card_scan(w, NOW)
            with self.subTest(reason=reason):
                self.assertTrue(reason + ':' in block,
                                f'{reason} has no bilingual copy on the page')


# ═══════════════════════════════════════════════════════════════════════════
# 9. THE NEW REASON HAS COPY EVERYWHERE THE OLD ONE DOES.
# ═══════════════════════════════════════════════════════════════════════════

_FRONTEND = _BACKEND.parent / "frontend"

#: THE CENSUS IS DERIVED, NOT LISTED. Every surface that renders
#: CLASS_UNVERIFIED is a surface that will be handed CLASS_SELF_REPORTED, so the
#: set of files to check is "wherever that code already appears" — found by
#: walking the tree, not by a hand-kept list that silently stops being complete
#: the next time somebody adds a review screen.
_COPY_ROOTS = (_FRONTEND / "src", _FRONTEND / "app")


def _copy_surfaces():
    """Files whose own text maps CLASS_UNVERIFIED to a sentence."""
    hits = []
    for root in _COPY_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in (".js", ".jsx") or ".test." in path.name:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "CLASS_UNVERIFIED:" in text:
                hits.append((path, text))
    return hits


class TheNewReasonIsNeverARawCodeOnScreenTest(unittest.TestCase):
    """A REVIEW REASON WITH NO COPY IS A ROW THAT SAYS NOTHING.

    logbooks/review.jsx renders t(`reason_${code}`) and HIDES the line when the
    key is missing, so a new code with no wording is not an ugly string on
    screen — it is a silently blank explanation on a flagged worker. That is
    the failure this pins, and it is why the list of places to check is
    derived from the tree rather than typed out here.
    """

    def test_the_surfaces_were_actually_found(self):
        """THE DENOMINATOR. A walk that stopped seeing these files would report
        zero gaps and pass every assertion below."""
        self.assertGreaterEqual(len(_copy_surfaces()), 2,
                                "the copy-surface walk found almost nothing")

    def test_every_surface_that_names_CLASS_UNVERIFIED_names_the_new_one(self):
        for path, text in _copy_surfaces():
            with self.subTest(path=path.name):
                self.assertTrue(
                    "CLASS_SELF_REPORTED" in text,
                    f"{path.name} renders CLASS_UNVERIFIED but not "
                    f"CLASS_SELF_REPORTED — a flagged worker gets a blank line")

    def test_the_osha_register_names_it_too(self):
        self.assertIn("CLASS_SELF_REPORTED", server.OSHA_REVIEW_LABELS)

    def test_and_it_does_not_reuse_the_unverified_wording(self):
        """Collapsing the two would destroy the one distinction the code
        exists to make: nothing failed to READ here, the worker ANSWERED."""
        self.assertNotEqual(server.OSHA_REVIEW_LABELS["CLASS_SELF_REPORTED"],
                            server.OSHA_REVIEW_LABELS["CLASS_UNVERIFIED"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
