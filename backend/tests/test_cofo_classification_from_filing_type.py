"""A CofO renewal is not a completion.

WHY THIS TEST EXISTS
--------------------
`_classify_cofo` (lib/dob_signal_classifier.py) classified a certificate
of occupancy from ``c_of_o_status``. On the live dataset that column is
the CONSTANT string ``'CO Issued'`` — 81,264 rows out of 81,264, no
other value. The first branch that matched was ``"ISSUED" in status``,
so EVERY certificate classified as ``cofo_final``: "this project is
officially complete."

46,842 of those rows are ``Renewal Without Change`` — a temporary CO
being renewed for another cycle, which is the opposite of complete. The
defect could not be observed before 7c4f983 because the CofO query named
six columns the dataset does not have and answered HTTP 400 on every
call since the feature shipped, so no cofo row was ever ingested. The
moment that fix lands, ingest starts and starts writing this.

The real distinction lives in ``c_of_o_filing_type``.

WHAT MAKES A FILING TYPE "TEMPORARY", VERIFIED NOT ASSUMED
----------------------------------------------------------
The dataset contains no column that says "temporary" and no literal
"TCO" anywhere. The lifecycle is nevertheless unambiguous in the data:

  • BIN 2092338, ordered by c_of_o_sequence, reads
    ``Initial > Renewal Without Change > Final``. A certificate that is
    renewed and then superseded by one labelled "Final" was not final.
  • BIN 3335884 carries 64 rows, every one of them a renewal, spanning
    2021-04 to 2026-08 at a roughly 30-90 day cadence, with no Final.
    That is the TCO renewal treadmill. A final CO is not renewed 64
    times.

So ``Final`` is the completion milestone and ``Initial`` /
``Renewal With Change`` / ``Renewal Without Change`` are all stages of a
certificate that is not final. That is what ``cofo_temporary`` means
here, and it is now reachable for the first time.

``cofo_pending`` is NOT reachable from this dataset and this test says
so explicitly rather than leaving a branch that pretends to handle it:
pkdm-hqz6 only ever publishes certificates that have been ISSUED
(``c_of_o_status`` has exactly one distinct value), so there is no
"filed but not yet issued" row to classify. The kind is kept in
KNOWN_SIGNAL_KINDS — it has a template and a notification policy, and
another dataset could legitimately feed it — but nothing in pkdm-hqz6
can produce it.

THE FIXTURE
-----------
``PKDM_HQZ6_FILING_TYPES`` was captured from the LIVE Socrata API on
2026-09-02 so this test runs offline and deterministically in CI. No
network call happens here — do not add one.

To refresh it (only when the distribution matters again):

    curl -s "https://data.cityofnewyork.us/resource/pkdm-hqz6.json\
?\\$select=c_of_o_filing_type,count(1)&\\$group=c_of_o_filing_type"
    curl -s "https://data.cityofnewyork.us/resource/pkdm-hqz6.json\
?\\$select=c_of_o_status,count(1)&\\$group=c_of_o_status"

Note the group with NO ``c_of_o_filing_type`` key in that first
response: 24 rows have the column absent entirely. They are ordinary
issued certificates with real numbers and dates (e.g. BIN 4220272,
``4220272-0000007``), not junk. The fallback branch is therefore
REACHABLE, and ``test_fixture_counts_reconcile_with_total`` exists so a
refresh that silently drops those 24 rows fails instead of passing.
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
import textwrap
import unittest
from pathlib import Path
from typing import Dict, Optional

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))


# ── FIXTURE ───────────────────────────────────────────────────────
# Captured live 2026-09-02. `None` is the key for rows where the column
# is absent from the record entirely (Socrata omits empty text columns).
PKDM_HQZ6_FILING_TYPES: Dict[Optional[str], int] = {
    "Renewal Without Change": 46842,
    "Final": 18922,
    "Initial": 8869,
    "Renewal With Change": 6607,
    None: 24,
}

PKDM_HQZ6_TOTAL_ROWS = 81264

# `c_of_o_status` has exactly ONE distinct value across the whole
# dataset. This is the fact that made the old classifier's first branch
# swallow every row.
PKDM_HQZ6_STATUS_VALUES: Dict[str, int] = {"CO Issued": 81264}

# The signal_kind that asserts "the project is officially complete".
COMPLETION_KIND = "cofo_final"

# What each live filing type must classify as.
EXPECTED_KIND_BY_FILING_TYPE: Dict[Optional[str], str] = {
    "Final": "cofo_final",
    "Initial": "cofo_temporary",
    "Renewal With Change": "cofo_temporary",
    "Renewal Without Change": "cofo_temporary",
    # Column absent: a real issued certificate whose filing type the
    # dataset does not state. We do not know whether it is final, so we
    # must not claim either way — the generic `cofo` fallback.
    None: "cofo",
}


# ── Production-shape helpers ──────────────────────────────────────
# These build the doc the INGEST PATH builds, by calling the real
# extractor, so this test cannot drift into asserting against a shape
# production never produces.


def _raw_cofo_record(filing_type: Optional[str]) -> dict:
    """A raw pkdm-hqz6 row. Real column names, real values, copied from
    BIN 3335884 sequence 99077 (a genuine Renewal Without Change row).
    """
    rec = {
        "bin": "3335884",
        "c_of_o_number": "3335884-0000064",
        # Constant across all 81,264 rows. Load-bearing: this is the
        # value the old classifier keyed on.
        "c_of_o_status": "CO Issued",
        "c_of_o_issuance_date": "08/13/26  3:13:12 PM",
        "c_of_o_sequence": "99077",
        "job_filing_name": "321234567",
        "job_type": "ALTERATION TYPE 1",
        "house_no": "626",
        "street_name": "FLATBUSH AVENUE",
        "borough": "Brooklyn",
    }
    if filing_type is not None:
        rec["c_of_o_filing_type"] = filing_type
    return rec


def _dob_log_for(filing_type: Optional[str]) -> dict:
    """Build the dob_log for a cofo row exactly as the ingest path does
    (server.py ~30300-30341): extras from `_extract_cofo_fields`, then
    `current_status` overwritten by `_extract_dob_log_status`.

    That overwrite is why the bug bit: it uppercases `'CO Issued'` to
    `'CO ISSUED'`, and `'ISSUED' in 'CO ISSUED'` is True.
    """
    from server import _extract_cofo_fields, _extract_dob_log_status

    log = {
        "record_type": "cofo",
        **_extract_cofo_fields(_raw_cofo_record(filing_type)),
    }
    log["current_status"] = _extract_dob_log_status(log)
    return log


def _rows_classified_as_completion() -> int:
    """How many of the 81,264 live rows the classifier would label
    `cofo_final` — 'the project is officially complete'."""
    from server import _signal_kind_for

    total = 0
    for filing_type, n in PKDM_HQZ6_FILING_TYPES.items():
        if _signal_kind_for(_dob_log_for(filing_type)) == COMPLETION_KIND:
            total += n
    return total


# ── Positive controls on the harness itself ───────────────────────


class TestHarnessReachesItsSubject(unittest.TestCase):
    """A check that runs, returns a well-formed answer and never reaches
    its subject is this codebase's signature failure. These tests fail
    loudly if the helpers above stop describing production."""

    def test_fixture_counts_reconcile_with_total(self):
        self.assertEqual(
            sum(PKDM_HQZ6_FILING_TYPES.values()), PKDM_HQZ6_TOTAL_ROWS,
            "filing-type counts do not sum to the row count. The live "
            "$group response omits a key for the 24 rows that have no "
            "c_of_o_filing_type at all; a refresh that drops them would "
            "hide a reachable branch.",
        )
        self.assertEqual(
            sum(PKDM_HQZ6_STATUS_VALUES.values()), PKDM_HQZ6_TOTAL_ROWS,
        )

    def test_status_column_is_constant_so_it_cannot_discriminate(self):
        self.assertEqual(
            len(PKDM_HQZ6_STATUS_VALUES), 1,
            "c_of_o_status is expected to be a single constant value; "
            "if that changed, the classifier's inputs changed too.",
        )

    def test_helper_reproduces_the_real_ingest_shape(self):
        """If `_extract_cofo_fields` renames a key, every classification
        test below would silently exercise an empty dict and pass. This
        is the guard."""
        log = _dob_log_for("Final")
        self.assertEqual(log["record_type"], "cofo")
        self.assertEqual(
            log.get("cofo_type"), "Final",
            "the extractor must carry c_of_o_filing_type through as "
            "`cofo_type`; the classifier reads that key",
        )
        self.assertEqual(
            log.get("current_status"), "CO ISSUED",
            "the ingest path uppercases the status; this is the exact "
            "string the old classifier matched 'ISSUED' against",
        )
        self.assertEqual(log.get("co_number"), "3335884-0000064")

    def test_absent_filing_type_really_is_absent(self):
        log = _dob_log_for(None)
        self.assertIsNone(log.get("cofo_type"))
        self.assertEqual(log.get("current_status"), "CO ISSUED")


# ── The defect ────────────────────────────────────────────────────


class TestRenewalIsNotACompletion(unittest.TestCase):

    def test_renewal_without_change_is_not_a_completion(self):
        """46,842 live rows — the single largest group in the dataset."""
        kind = __import__("server")._signal_kind_for(
            _dob_log_for("Renewal Without Change")
        )
        self.assertNotEqual(
            kind, COMPLETION_KIND,
            "a temporary CO renewed for another cycle is the opposite "
            "of a completed project; 46,842 live rows say this",
        )
        self.assertEqual(kind, "cofo_temporary")

    def test_renewal_with_change_is_not_a_completion(self):
        """6,607 live rows."""
        from server import _signal_kind_for
        kind = _signal_kind_for(_dob_log_for("Renewal With Change"))
        self.assertNotEqual(kind, COMPLETION_KIND)
        self.assertEqual(kind, "cofo_temporary")

    def test_initial_is_not_a_completion(self):
        """8,869 live rows. The first TCO in the chain — see BIN 2092338,
        Initial > Renewal Without Change > Final."""
        from server import _signal_kind_for
        kind = _signal_kind_for(_dob_log_for("Initial"))
        self.assertNotEqual(kind, COMPLETION_KIND)
        self.assertEqual(kind, "cofo_temporary")

    def test_final_is_a_completion(self):
        """18,922 live rows. The only filing type that means done."""
        from server import _signal_kind_for
        self.assertEqual(
            _signal_kind_for(_dob_log_for("Final")), COMPLETION_KIND,
        )

    def test_absent_filing_type_claims_nothing(self):
        """24 live rows have no c_of_o_filing_type. They are real issued
        certificates, so we must not discard them — but we cannot call
        them complete either."""
        from server import _signal_kind_for
        kind = _signal_kind_for(_dob_log_for(None))
        self.assertNotEqual(kind, COMPLETION_KIND)
        self.assertEqual(kind, "cofo")

    def test_every_live_filing_type_maps_as_expected(self):
        from server import _signal_kind_for
        for filing_type, expected in EXPECTED_KIND_BY_FILING_TYPE.items():
            with self.subTest(filing_type=filing_type):
                self.assertEqual(
                    _signal_kind_for(_dob_log_for(filing_type)), expected,
                )

    def test_only_final_rows_are_classified_as_completions(self):
        """The whole defect in one number.

        Before: 81,264 of 81,264 rows classify as `cofo_final`, because
        the classifier read the constant status column.
        After:  18,922 — exactly the `Final` rows.
        """
        self.assertEqual(
            _rows_classified_as_completion(),
            PKDM_HQZ6_FILING_TYPES["Final"],
            "rows classified 'the project is officially complete' must "
            "be exactly the Final ones",
        )

    def test_classification_ignores_the_constant_status_column(self):
        """The regression guard. Every row carries `CO Issued`, so if the
        classifier consults status at all, one of these must break."""
        from lib.dob_signal_classifier import classify_signal_kind
        for filing_type, expected in EXPECTED_KIND_BY_FILING_TYPE.items():
            for status in ("CO ISSUED", "ISSUED", "", None):
                with self.subTest(filing_type=filing_type, status=status):
                    log = _dob_log_for(filing_type)
                    log["current_status"] = status
                    self.assertEqual(
                        classify_signal_kind(log), expected,
                        "c_of_o_status is constant across the dataset and "
                        "must not influence the classification",
                    )


class TestCofoPendingIsUnreachableFromThisDataset(unittest.TestCase):
    """Said plainly rather than left as code pretending to handle it."""

    def test_no_live_row_can_produce_cofo_pending(self):
        from server import _signal_kind_for
        for filing_type in PKDM_HQZ6_FILING_TYPES:
            for status in PKDM_HQZ6_STATUS_VALUES:
                with self.subTest(filing_type=filing_type, status=status):
                    log = _dob_log_for(filing_type)
                    log["current_status"] = status.upper()
                    self.assertNotEqual(
                        _signal_kind_for(log), "cofo_pending",
                        "pkdm-hqz6 publishes only issued certificates; "
                        "there is no pending row to classify",
                    )

    def test_cofo_pending_is_still_a_known_kind(self):
        """Kept in the canonical set: it has a template and a
        notification policy, and a future dataset could feed it. This
        test exists so removing the unreachable classifier branch is not
        mistaken for retiring the kind."""
        from lib.dob_signal_classifier import KNOWN_SIGNAL_KINDS
        self.assertIn("cofo_pending", KNOWN_SIGNAL_KINDS)


# ── Severity ──────────────────────────────────────────────────────


class TestCofoSeverity(unittest.TestCase):
    """`_determine_severity` is a strict binary: "Action" or "Good".
    "Action" is the ONLY input to `_send_critical_dob_alert_throttled`
    (server.py:30376, :30403) and renders as a red "Action Needed" dot
    (frontend/app/project/[id]/dob-logs.jsx:55-59). There is no
    "notable but not urgent" value to reach for.

    No row in pkdm-hqz6 is actionable: every one of the 81,264 is a
    certificate that WAS issued. Nothing is pending, expired or revoked.
    The one genuinely actionable CofO event — a temporary CO about to
    lapse — cannot be detected here, because the dataset has no
    expiration column at all (which is why 7c4f983 dropped
    `expiration_date` rather than storing a permanent None).

    So a completion is reported through `signal_kind`, which is built
    for saying what happened, and not through `severity`, which is built
    for waking someone up.
    """

    def test_no_live_filing_type_reaches_the_critical_alert_path(self):
        from server import _determine_severity
        for filing_type in PKDM_HQZ6_FILING_TYPES:
            with self.subTest(filing_type=filing_type):
                self.assertNotEqual(
                    _determine_severity(
                        _raw_cofo_record(filing_type), "cofo",
                    ),
                    "Action",
                    "a certificate of occupancy is not an alert. "
                    "'Action' pages the operator and labels the card "
                    "'Action Needed', and there is nothing to do.",
                )

    def test_a_final_co_is_good_news(self):
        from server import _determine_severity
        self.assertEqual(
            _determine_severity(_raw_cofo_record("Final"), "cofo"), "Good",
        )

    def test_severity_decision_is_explicit_not_a_fallthrough(self):
        """Today `cofo` reaches `return "Good"` only because it matches
        none of the branches above it — the same way an unknown
        record_type does. That is the right answer for the wrong reason,
        and it does not survive someone reordering the function.

        This asserts the decision is written down: a branch on
        record_type == "cofo" whose every return is "Good".
        """
        from server import _determine_severity

        tree = ast.parse(
            textwrap.dedent(inspect.getsource(_determine_severity))
        )
        fn = tree.body[0]

        cofo_branches = [
            node for node in ast.walk(fn)
            if isinstance(node, ast.If)
            and any(
                isinstance(c, ast.Constant) and c.value == "cofo"
                for c in ast.walk(node.test)
            )
        ]
        self.assertTrue(
            cofo_branches,
            "_determine_severity has no cofo branch; a cofo record "
            "falls through to the terminal `return \"Good\"` by "
            "accident. Record the decision explicitly.",
        )

        returns = [
            n for b in cofo_branches for n in ast.walk(b)
            if isinstance(n, ast.Return)
        ]
        self.assertTrue(returns, "cofo branch returns nothing")
        for r in returns:
            self.assertIsInstance(r.value, ast.Constant)
            self.assertEqual(
                r.value.value, "Good",
                "every pkdm-hqz6 row is an already-issued certificate; "
                "none of them is actionable, and the dataset has no "
                "expiration column with which to detect the one case "
                "that would be (a lapsing temporary CO).",
            )


if __name__ == "__main__":
    unittest.main()
