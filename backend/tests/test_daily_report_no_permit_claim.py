"""The daily report email makes NO claim about permit expiry.

Why this test exists
────────────────────
The `project_daily_report` template used to carry a line reading
"N permits on this project expire within 30 days", sourced from
`_count_permits_expiring_soon`, which counted ROWS in `permit_renewals`.

Those rows are keyed on `permit_dob_log_id` — a `dob_logs` `_id`, not a
permit identity. `dob_logs` inserts a new document with a new `_id` on
every status change, and a reset-resync mints new `_id`s for everything,
so a single real permit accrues many rows and the count multiplied with
them. A customer's report asserted "3 permits expiring within 30 days"
off three rows for one permit, each carrying `job_number: null`.

Both the count function and every template site are removed.

What this pins, and how
───────────────────────
The assertions match on STRINGS in the rendered output, not on a
variable name or a ctx key. That is deliberate: a re-add fails here in
any spelling — a differently-named helper, a reworded sentence, a
detail row, or the plaintext part — because all of them have to say
some form of "permit" or "expir" to make the claim at all.

The ctx key is passed in several cases below precisely to prove the
renderer ignores it. A future caller that still supplies
`expiring_permits` must not be able to resurrect the line.

Zero is not an escape hatch. "0 permits expiring" is also an assertion
about permits, and it is one we cannot make — we do not know how many
permits are expiring, only that the number being printed was not it. So
`expiring_permits: 0` is asserted to render nothing, the same as 3.

See docs/audits/permit-expiry-claim-2026-08-27.md.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib.email_templates import render_for_trigger  # noqa: E402


# Substrings that would indicate a permit-expiry claim has come back.
# Matched case-insensitively against subject + html + text.
FORBIDDEN = ("permit", "expir", "30 days", "30d")

_BASE_CTX = {
    "recipient_name": "",
    "project_name": "588 Thomas S Boyland Street",
    "project_address": "588 Thomas S Boyland Street, Brooklyn, NY",
    "report_date": "2026-08-27",
    "logbook_count": 2,
    "worker_count": 7,
    "attached": True,
    "action_link": "https://www.levelog.com/reports",
}


def _render(**overrides):
    ctx = dict(_BASE_CTX)
    ctx.update(overrides)
    return render_for_trigger("project_daily_report", ctx)


class TestNoPermitClaimInDailyReport(unittest.TestCase):

    def _assert_clean(self, label: str, subject: str, html: str, text: str):
        for part_name, part in (
            ("subject", subject), ("html", html), ("text", text),
        ):
            lowered = part.lower()
            for needle in FORBIDDEN:
                self.assertNotIn(
                    needle, lowered,
                    f"{label}: {part_name} contains {needle!r} — the daily "
                    f"report must make no claim about permits. See "
                    f"docs/audits/permit-expiry-claim-2026-08-27.md.",
                )

    def test_no_claim_when_key_absent(self):
        """The current caller. No permit key is passed at all."""
        self._assert_clean("key absent", *_render())

    def test_no_claim_when_key_is_zero(self):
        """Zero is an assertion too. It must not render a line."""
        self._assert_clean("expiring_permits=0", *_render(expiring_permits=0))

    def test_no_claim_when_key_is_nonzero(self):
        """The regression proper: the exact shape that shipped the false
        '3 permits expiring within 30 days' to a customer."""
        self._assert_clean("expiring_permits=3", *_render(expiring_permits=3))

    def test_no_claim_when_key_is_one(self):
        """The singular branch had its own wording ('1 permit … expires'),
        so it needs its own case — a partial revert could restore only
        this path."""
        self._assert_clean("expiring_permits=1", *_render(expiring_permits=1))

    def test_no_claim_when_key_is_a_string(self):
        """Defensive: the removed code did int() coercion, so a caller
        passing a string used to work. Must still render nothing."""
        self._assert_clean("expiring_permits='3'", *_render(expiring_permits="3"))


class TestDailyReportStillReportsWhatItKnows(unittest.TestCase):
    """The removal must not take the rest of the email with it. These
    pin the content that IS sourced from data we hold."""

    def test_counts_and_identity_survive(self):
        subject, html, text = _render()

        self.assertIn("588 Thomas S Boyland Street", subject)
        self.assertIn("2026-08-27", subject)

        for part in (html, text):
            self.assertIn("588 Thomas S Boyland Street", part)
            self.assertIn("2026-08-27", part)
            # logbook_count=2, worker_count=7 — from logbooks/checkins,
            # not from permit_renewals.
            self.assertIn("2", part)
            self.assertIn("7", part)

    def test_pdf_delivery_line_survives(self):
        _s, html, text = _render(attached=True)
        self.assertIn("attached as a PDF", html)
        self.assertIn("attached as a PDF", text)

        _s, html, text = _render(attached=False)
        self.assertIn("available in LeveLog", html)
        self.assertIn("available in LeveLog", text)


if __name__ == "__main__":
    unittest.main()
