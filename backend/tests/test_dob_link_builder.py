"""DOB deeplink builder — `_build_dob_link` / `_bis_bin_overview_url`.

Regression under test: the BIN-scoped building-overview fallback used
`OverviewByBinServlet?requestid=2&allbin=<bin>&allinquirytype=BXS3OCV4`,
which BIS answers with "Page not found". `allinquirytype` was a hardcoded
opaque token — no record field was ever mapped into it — and the same file
already contained a working overview form (PropertyProfileOverviewServlet
with a plain `bin` param), which the frontend's own "verify your BIN" link
uses. The fallback now uses that proven-good form.

The violation DETAIL servlets (ECBQueryByNumberServlet,
ActionViolationDisplayServlet) are deliberately unchanged — they are correct
and are used whenever the record carries the identifiers. These tests pin
that the fallback fires ONLY for genuinely incomplete records.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402

_BIN = "3048298"
_OVERVIEW = (
    "https://a810-bisweb.nyc.gov/bisweb/PropertyProfileOverviewServlet"
    f"?bin={_BIN}"
)


class OverviewFallbackTest(unittest.TestCase):
    """The fixed building-overview form."""

    def test_helper_uses_property_profile_form(self):
        self.assertEqual(server._bis_bin_overview_url(_BIN), _OVERVIEW)

    def test_helper_no_longer_emits_broken_servlet(self):
        url = server._bis_bin_overview_url(_BIN)
        self.assertNotIn("OverviewByBinServlet", url)
        self.assertNotIn("allinquirytype", url)
        self.assertNotIn("allbin", url)

    def test_helper_empty_bin_returns_empty(self):
        """Behaviour preserved from the previous implementation."""
        self.assertEqual(server._bis_bin_overview_url(""), "")
        self.assertEqual(server._bis_bin_overview_url(None), "")


class ViolationLinkRoutingTest(unittest.TestCase):
    """Detail servlets win when identifiers exist; fallback only otherwise."""

    def test_ecb_number_builds_ecb_detail_url(self):
        rec = {"bin": _BIN, "ecb_violation_number": "35123456K"}
        url = server._build_dob_link(rec, "violation")
        self.assertIn("ECBQueryByNumberServlet", url)
        self.assertIn("ecbin=35123456K", url)
        # Must NOT have fallen through to the overview.
        self.assertNotIn("PropertyProfileOverviewServlet", url)

    def test_isn_bin_number_builds_bis_detail_url(self):
        rec = {
            "bin": _BIN,
            "isn_dob_bis_viol": "1234567",
            "number": "V051520CBXS30",
        }
        url = server._build_dob_link(rec, "violation")
        self.assertIn("ActionViolationDisplayServlet", url)
        self.assertIn(f"allbin={_BIN}", url)
        self.assertIn("allisn=1234567", url)
        self.assertIn("ppremise60=V051520CBXS30", url)
        self.assertNotIn("PropertyProfileOverviewServlet", url)

    def test_ecb_takes_precedence_over_isn(self):
        rec = {
            "bin": _BIN,
            "ecb_violation_number": "35123456K",
            "isn_dob_bis_viol": "1234567",
            "number": "V051520CBXS30",
        }
        url = server._build_dob_link(rec, "violation")
        self.assertIn("ECBQueryByNumberServlet", url)

    def test_bin_only_violation_uses_fixed_overview(self):
        """The reported bug: an incomplete violation must now produce the
        working overview URL, not the 404-ing OverviewByBinServlet form."""
        url = server._build_dob_link({"bin": _BIN}, "violation")
        self.assertEqual(url, _OVERVIEW)
        self.assertNotIn("OverviewByBinServlet", url)

    def test_incomplete_isn_without_number_falls_back(self):
        """isn + bin but no violation number is genuinely incomplete."""
        rec = {"bin": _BIN, "isn_dob_bis_viol": "1234567"}
        self.assertEqual(server._build_dob_link(rec, "violation"), _OVERVIEW)

    def test_violation_with_no_bin_returns_empty(self):
        self.assertEqual(server._build_dob_link({}, "violation"), "")


class OtherFallbacksFixedTest(unittest.TestCase):
    """permit / job_status / inspection share the same fallback helper."""

    def test_permit_without_job_uses_fixed_overview(self):
        self.assertEqual(
            server._build_dob_link({"bin": _BIN}, "permit"), _OVERVIEW,
        )

    def test_job_status_without_job_uses_fixed_overview(self):
        self.assertEqual(
            server._build_dob_link({"bin": _BIN}, "job_status"), _OVERVIEW,
        )

    def test_inspection_without_job_uses_fixed_overview(self):
        self.assertEqual(
            server._build_dob_link({"bin": _BIN}, "inspection"), _OVERVIEW,
        )

    def test_unknown_type_final_fallback_uses_same_form(self):
        self.assertEqual(
            server._build_dob_link({"bin": _BIN}, "cofo"), _OVERVIEW,
        )

    def test_unknown_type_no_bin_returns_empty(self):
        self.assertEqual(server._build_dob_link({}, "cofo"), "")


class UntouchedRoutesTest(unittest.TestCase):
    """Guard the paths this change must NOT have altered."""

    def test_dob_now_permit_still_routes_to_open_data(self):
        rec = {"bin": _BIN, "job_filing_number": "B00123456-I1"}
        url = server._build_dob_link(rec, "permit")
        self.assertIn("data.cityofnewyork.us/resource/w9ak-ipjd", url)

    def test_legacy_permit_still_routes_to_jobs_servlet(self):
        rec = {"bin": _BIN, "job__": "123456789", "doc__": "3"}
        url = server._build_dob_link(rec, "permit")
        self.assertIn("JobsQueryByNumberServlet", url)
        self.assertIn("passdocnumber=03", url)

    def test_swo_and_complaint_still_use_complaints_servlet(self):
        self.assertIn(
            "ComplaintsByAddressServlet",
            server._build_dob_link({"bin": _BIN}, "swo"),
        )
        self.assertIn(
            "ComplaintsByAddressServlet",
            server._build_dob_link({"bin": _BIN}, "complaint"),
        )


class SourceInvariantTest(unittest.TestCase):

    # Assertions target the URL LITERAL, not the bare servlet name — the
    # name still appears in the helper's docstring documenting what it
    # replaced, which is intentional. (Also keeps failures readable rather
    # than dumping the whole 25k-line source.)
    _BROKEN_URL = "https://a810-bisweb.nyc.gov/bisweb/OverviewByBinServlet"
    _GOOD_URL = "https://a810-bisweb.nyc.gov/bisweb/PropertyProfileOverviewServlet"

    def test_broken_servlet_url_gone_from_source(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertEqual(
            src.count(self._BROKEN_URL), 0,
            "the OverviewByBinServlet URL must no longer be constructed",
        )

    def test_single_building_overview_builder(self):
        """One overview URL construction for the whole file, so the two forms
        can't drift apart again — that drift produced the broken link."""
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertEqual(
            src.count(self._GOOD_URL), 1,
            "expected exactly one PropertyProfileOverviewServlet construction",
        )

    def test_detail_servlets_untouched(self):
        src = (_BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertIn("ECBQueryByNumberServlet", src)
        self.assertIn("ActionViolationDisplayServlet", src)


if __name__ == "__main__":
    unittest.main()
