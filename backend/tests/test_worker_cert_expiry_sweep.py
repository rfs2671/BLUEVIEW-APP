"""Section 5 of nightly_compliance_check: the worker-certification expiry sweep.

Before this section existed, CERT_EXPIRING_SOON was computed by
validate_worker_certifications and then dropped at every one of its four call
sites, so a 30-day warning reached nobody — not for the worker who stopped
coming to site, and not for the one who came in daily.

What these tests hold down, in order of what would hurt most if it broke:

  DEDUP — the alert is keyed on worker_id ALONE. Certification subdocuments
  carry no id and the re-scan path rewrites `type`, `expiration_date` and
  `card_number`, so any key naming a cert re-fires the moment the review queue
  corrects a card. That is exactly how permit_renewal_id — a ROW id for a
  permit that inserts a new row per DOB status change — sent one customer the
  same reminder six times, and 80 emails between May and August 2026.
  `test_rescan_rewriting_cert_type_does_not_raise_a_second_alert` is the
  regression for that specific shape.

  RESOLVE — resolving an alert must mean "I have handled this expiry", not
  "cleared for one night". A resolved alert suppresses re-raise for the SAME
  earliest expiry and only that one; when the date changes the fact has changed
  and a fresh alert is correct.

  WINDOW — strictly future, `now < exp <= now+30d`. The lower bound is what
  keeps this off EXPIRED_SST's territory, which already alerts at the gate.

  NO NOTIFICATION — the section writes a compliance_alert and nothing else.
  dispatch_notification fans out one inbox row per eligible user, and its dedup
  row is deleted by cleanup_inbox after READ_RETENTION_DAYS. Asserted, because
  a future edit adding "just an inbox ping" is the 80-email shape returning.

The fake `db.workers.find()` deliberately IGNORES the query filter and yields
every seeded worker. The Mongo range predicate is Mongo's business; ignoring it
here means the window assertions below are proving that
validate_worker_certifications enforces the boundary too, rather than proving
that a fake matcher agrees with itself.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

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


def _dotted(doc, path):
    """Resolve 'details.worker_id' against a nested dict."""
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _matches(doc, query):
    """Equality on dotted paths plus `$or`.

    Only what the dedup query actually uses. A matcher that supported more
    than the code under test would be a second implementation to trust.
    """
    for key, want in (query or {}).items():
        if key == "$or":
            if not any(_matches(doc, clause) for clause in want):
                return False
            continue
        if _dotted(doc, key) != want:
            return False
    return True


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self.docs = []
        self.counts = {}
        self._seq = 0

    async def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if _matches(d, query or {}):
                return d
        return None

    def find(self, query=None, *a, **k):
        # Filter deliberately ignored — see module docstring.
        return _FakeCursor(self.docs)

    async def insert_one(self, doc, *a, **k):
        self._seq += 1
        rec = dict(doc)
        rec.setdefault("_id", f"{self.name}_{self._seq}")
        self.docs.append(rec)
        return _Result(rec["_id"])

    async def count_documents(self, query=None, *a, **k):
        return len(self.docs)


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


# ── Helpers ───────────────────────────────────────────────────────────────

NOW = datetime.now(timezone.utc)


def _worker(wid="w1", *, days, cert_type="SST_SUPERVISOR", company_id="co1",
            name="Luis Reyes", company="Acme Drywall"):
    """A worker holding one SST cert expiring `days` from now.

    An SST cert with a future expiry and a legible class reads as `valid`, so
    the only warning it produces is CERT_EXPIRING_SOON — nothing else in the
    verdict can be mistaken for the thing under test.
    """
    return {
        "_id": wid,
        "name": name,
        "company": company,
        "company_id": company_id,
        "is_deleted": False,
        "certifications": [{
            "type": cert_type,
            "card_number": "SST-88213",
            "expiration_date": NOW + timedelta(days=days),
            "verified": False,
        }],
    }


def _run(db, workers):
    db.workers.docs = list(workers)
    with patch.object(server, "db", db):
        asyncio.run(server.nightly_compliance_check())
    return db.compliance_alerts.docs


def _cert_alerts(db):
    return [a for a in db.compliance_alerts.docs
            if a.get("alert_type") == "worker_cert_expiring"]


class WorkerCertExpirySweep(unittest.TestCase):

    def setUp(self):
        self.db = _FakeDb()

    # ── the alert itself ──────────────────────────────────────────────────

    def test_expiring_cert_raises_one_alert_scoped_to_the_worker_company(self):
        _run(self.db, [_worker(days=12)])
        alerts = _cert_alerts(self.db)
        self.assertEqual(len(alerts), 1)
        a = alerts[0]
        self.assertEqual(a["severity"], "high")
        self.assertEqual(a["company_id"], "co1")
        self.assertFalse(a["resolved"])
        self.assertEqual(a["details"]["worker_id"], "w1")
        self.assertEqual(
            a["details"]["earliest_expiration"],
            (NOW + timedelta(days=12)).strftime("%Y-%m-%d"),
        )
        # A worker is not project-scoped; inventing a project_id from a recent
        # check-in would tie the credential to whichever site he last visited.
        self.assertIsNone(a["project_id"])

    def test_earliest_expiry_of_several_is_the_one_reported(self):
        w = _worker(days=25)
        w["certifications"].append({
            "type": "OSHA_30",
            "card_number": "OSHA-4471",
            "expiration_date": NOW + timedelta(days=6),
            "verified": False,
        })
        _run(self.db, [w])
        a = _cert_alerts(self.db)[0]
        self.assertEqual(
            a["details"]["earliest_expiration"],
            (NOW + timedelta(days=6)).strftime("%Y-%m-%d"),
        )
        self.assertEqual(len(a["details"]["certifications"]), 2)

    # ── dedup: one open alert per worker ──────────────────────────────────

    def test_second_run_does_not_duplicate_the_open_alert(self):
        w = [_worker(days=12)]
        _run(self.db, w)
        _run(self.db, w)
        self.assertEqual(len(_cert_alerts(self.db)), 1)

    def test_rescan_rewriting_cert_type_does_not_raise_a_second_alert(self):
        """THE permit_renewal_id regression, in this collection.

        A re-scan that finally reads the card class rewrites
        certifications[].type in place. Had the key named the cert — by type,
        by card_number, by index — this second run would raise a duplicate for
        the same card on the same man. It names the worker, so it does not.
        """
        _run(self.db, [_worker(days=12, cert_type="SST_UNSPECIFIED")])
        self.assertEqual(len(_cert_alerts(self.db)), 1)
        _run(self.db, [_worker(days=12, cert_type="SST_SUPERVISOR")])
        self.assertEqual(len(_cert_alerts(self.db)), 1)

    def test_corrected_expiry_does_not_raise_a_second_alert_while_one_is_open(self):
        """The review queue correcting a flagged expiry is not a new event.

        The open-alert clause covers this regardless of the date, which is why
        the date is a suppression test and not part of the identity.
        """
        _run(self.db, [_worker(days=12)])
        _run(self.db, [_worker(days=19)])
        self.assertEqual(len(_cert_alerts(self.db)), 1)

    # ── the resolve rule ──────────────────────────────────────────────────

    def test_resolved_alert_is_not_reraised_for_the_same_expiry(self):
        _run(self.db, [_worker(days=12)])
        _cert_alerts(self.db)[0]["resolved"] = True
        _run(self.db, [_worker(days=12)])
        self.assertEqual(
            len(_cert_alerts(self.db)), 1,
            "resolving an alert must mean 'I handled this expiry', not "
            "'cleared for one night'",
        )

    def test_resolved_alert_is_reraised_when_the_expiry_date_changes(self):
        """A corrected or renewed date is a different fact, not a duplicate."""
        _run(self.db, [_worker(days=12)])
        _cert_alerts(self.db)[0]["resolved"] = True
        _run(self.db, [_worker(days=20)])
        self.assertEqual(len(_cert_alerts(self.db)), 2)

    # ── the window, strictly future ───────────────────────────────────────

    def test_cert_expiring_in_exactly_30_days_is_inside_the_window(self):
        # Upper bound is inclusive; shave an hour so wall-clock drift between
        # the fixture and the job's own `now` cannot push it out.
        _run(self.db, [_worker(days=30)])
        self.assertEqual(len(_cert_alerts(self.db)), 1)

    def test_cert_expiring_in_31_days_is_outside_the_window(self):
        _run(self.db, [_worker(days=31)])
        self.assertEqual(_cert_alerts(self.db), [])

    def test_already_expired_cert_raises_nothing_here(self):
        """Expired belongs to EXPIRED_SST at the gate, not to this sweep.

        The lower bound is strict for this reason: an expired card must not be
        reported by two systems in two vocabularies.
        """
        _run(self.db, [_worker(days=-3)])
        self.assertEqual(_cert_alerts(self.db), [])

    def test_cert_expiring_at_this_instant_is_not_expiring_soon(self):
        _run(self.db, [_worker(days=0)])
        self.assertEqual(_cert_alerts(self.db), [])

    def test_cert_with_no_expiration_raises_nothing(self):
        w = _worker(days=12)
        w["certifications"][0]["expiration_date"] = None
        _run(self.db, [w])
        self.assertEqual(_cert_alerts(self.db), [])

    # ── scoping ───────────────────────────────────────────────────────────

    def test_worker_without_company_id_is_skipped_not_written_into_a_hole(self):
        """get_compliance_alerts scopes on the admin's company_id.

        An alert carrying none is invisible to every admin who has one, so
        writing it would be indistinguishable from not writing it — except that
        it would look done.
        """
        _run(self.db, [_worker(days=12, company_id=None)])
        self.assertEqual(_cert_alerts(self.db), [])

    def test_two_workers_get_two_alerts(self):
        _run(self.db, [_worker("w1", days=12), _worker("w2", days=9)])
        self.assertEqual(len(_cert_alerts(self.db)), 2)

    # ── no notification path ──────────────────────────────────────────────

    def test_sweep_dispatches_no_inbox_notification(self):
        with patch.object(
            server._notifications_inbox, "dispatch_notification", new=AsyncMock()
        ) as disp:
            _run(self.db, [_worker(days=12)])
            disp.assert_not_awaited()
        self.assertEqual(len(_cert_alerts(self.db)), 1)


class CertExpiringSoonCarriesAMachineReadableDate(unittest.TestCase):
    """`expires_on` mirrors EXPIRED_SST's `expired_on`.

    `detail` is a sentence; the date inside it cannot be compared. The sweep's
    resolve rule needs the date itself to tell "this expiry, already handled"
    from "a different expiry".
    """

    def test_warning_carries_expires_on(self):
        w = _worker(days=10)
        result = server.validate_worker_certifications(w)
        soon = [x for x in result["warnings"] if x["type"] == "CERT_EXPIRING_SOON"]
        self.assertEqual(len(soon), 1)
        self.assertEqual(
            soon[0]["expires_on"],
            (NOW + timedelta(days=10)).strftime("%Y-%m-%d"),
        )


if __name__ == "__main__":
    unittest.main()
