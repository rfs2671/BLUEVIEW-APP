"""PR A — per-document signature affirmation on the exported record.

render_signature_html must stamp an explicit AFFIRMED / UNAFFIRMED banner on
every rendered CP signature. A signature is affirmed ONLY when the CP took an
explicit affirmative action on THIS document (sig.affirmed is True); an
inherited/reused credential or a legacy string signature renders UNAFFIRMED —
never a VERIFIED stamp the signer never made for that record.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import server  # noqa: E402


class AffirmationBannerTest(unittest.TestCase):

    def test_affirmed_dict_renders_affirmed_not_unaffirmed(self):
        html = server.render_signature_html(
            {"paths": [[{"x": 1, "y": 2}]], "signerName": "Ada CP",
             "affirmed": True, "affirmedAt": "2026-07-29T13:45:06Z"},
            "CP Signature",
        )
        self.assertIn("AFFIRMED for this document", html)
        self.assertNotIn("UNAFFIRMED", html)
        # The affirmation time is surfaced, IN NEW YORK TIME and carrying its
        # zone. It used to print the stored UTC digits with " UTC" appended:
        # honest, but the only clock on a NYC compliance document a reader had
        # to convert in his head, sitting four hours from the roster times
        # beside it. 13:45:06Z on a July day is 9:45 AM EDT. `eastern_datetime`
        # owns the conversion (see test_eastern_clock.py).
        self.assertIn("July 29, 2026 at 9:45 AM EDT", html)
        self.assertNotIn("13:45", html)

    def test_inherited_dict_without_affirmed_renders_unaffirmed(self):
        html = server.render_signature_html(
            {"paths": [[{"x": 1, "y": 2}]], "signerName": "Ada CP",
             "timestamp": "2026-07-29T10:00:00Z"},
            "CP Signature",
        )
        self.assertIn("UNAFFIRMED", html)
        self.assertNotIn("AFFIRMED for this document", html)

    def test_affirmed_false_is_unaffirmed(self):
        html = server.render_signature_html({"signerName": "Ada", "affirmed": False})
        self.assertIn("UNAFFIRMED", html)

    def test_legacy_string_signature_is_unaffirmed(self):
        # A raw base64 string has no affirmation marker → honest UNAFFIRMED.
        html = server.render_signature_html("iVBORw0KGgoAAAANSU==", "CP Signature")
        self.assertIn("UNAFFIRMED", html)
        self.assertIn("data:image/png;base64,", html)

    def test_empty_signature_renders_nothing(self):
        self.assertEqual(server.render_signature_html(None), "")
        self.assertEqual(server.render_signature_html(""), "")

    def test_signer_name_camelcase_or_snake(self):
        # Frontend sends signerName; older data used signer_name — both render.
        h1 = server.render_signature_html({"data": "AAA", "signerName": "Bo", "affirmed": True})
        h2 = server.render_signature_html({"data": "AAA", "signer_name": "Bo", "affirmed": True})
        self.assertIn("Bo", h1)
        self.assertIn("Bo", h2)

    def test_helper_direct(self):
        self.assertIn("AFFIRMED", server._signature_affirmation_html({"affirmed": True}))
        self.assertIn("UNAFFIRMED", server._signature_affirmation_html({}))


class FinalizeCpSignatureTest(unittest.TestCase):
    """Server-side stamp + plausibility validation of the client affirmation."""

    NOW = datetime(2026, 7, 29, 18, 0, 0, tzinfo=timezone.utc)
    DOC_DATE = "2026-07-29"

    def _fin(self, sig, date=None):
        return server._finalize_cp_signature(sig, date or self.DOC_DATE, self.NOW)

    def test_non_affirmed_passes_through(self):
        sig = {"paths": [], "signerName": "x"}
        self.assertIs(self._fin(sig), sig)          # untouched, same object
        self.assertIsNone(self._fin(None))
        self.assertEqual(self._fin("rawstr"), "rawstr")

    def test_server_stamps_received_at(self):
        out = self._fin({"affirmed": True, "affirmedAt": "2026-07-29T17:30:00Z"})
        # Server-vouched instant recorded, regardless of the client claim.
        self.assertEqual(out["affirmed_received_at"], self.NOW.isoformat())
        self.assertNotIn("affirmation_flag", out)   # plausible claim → no flag

    def test_future_claim_flagged_not_suppressed(self):
        out = self._fin({"affirmed": True, "affirmedAt": "2026-07-30T09:00:00Z"})
        self.assertEqual(out["affirmation_flag"], "FUTURE")
        # NOT suppressed — the value is preserved, only annotated.
        self.assertEqual(out["affirmedAt"], "2026-07-30T09:00:00Z")
        self.assertIn("affirmed_received_at", out)

    def test_implausibly_old_claim_flagged(self):
        out = self._fin({"affirmed": True, "affirmedAt": "2026-07-01T09:00:00Z"})
        self.assertEqual(out["affirmation_flag"], "IMPLAUSIBLE_OLD")
        self.assertEqual(out["affirmedAt"], "2026-07-01T09:00:00Z")

    def test_unparseable_claim_flagged(self):
        out = self._fin({"affirmed": True, "affirmedAt": "not-a-date"})
        self.assertEqual(out["affirmation_flag"], "UNPARSEABLE")

    def test_same_day_claim_ok(self):
        out = self._fin({"affirmed": True, "affirmedAt": "2026-07-29T08:00:00Z"})
        self.assertNotIn("affirmation_flag", out)

    def test_within_backdate_grace_ok(self):
        # One day before the doc date is within the 2-day grace.
        out = self._fin({"affirmed": True, "affirmedAt": "2026-07-28T23:00:00Z"})
        self.assertNotIn("affirmation_flag", out)

    def test_reaffirm_clears_stale_flag(self):
        out = self._fin({"affirmed": True, "affirmedAt": "2026-07-29T08:00:00Z",
                         "affirmation_flag": "FUTURE"})
        self.assertNotIn("affirmation_flag", out)

    # ── export banner reflects validation ──
    def test_export_flagged_says_not_verified(self):
        out = self._fin({"affirmed": True, "affirmedAt": "2026-07-30T09:00:00Z"})
        html = server.render_signature_html(out, "CP Signature")
        self.assertIn("NOT VERIFIED", html)
        self.assertIn("FUTURE", html)
        self.assertIn("server-received", html)

    def test_export_valid_shows_claimed_and_received(self):
        out = self._fin({"affirmed": True, "affirmedAt": "2026-07-29T17:30:00Z"})
        html = server.render_signature_html(out, "CP Signature")
        self.assertIn("AFFIRMED for this document", html)
        # 17:30:00Z on a July day is 1:30 PM EDT -- see the note in
        # AffirmationBannerTest above.
        self.assertIn("claimed July 29, 2026 at 1:30 PM EDT", html)
        self.assertIn("server-received", html)
        self.assertNotIn("NOT VERIFIED", html)


if __name__ == "__main__":
    unittest.main()
