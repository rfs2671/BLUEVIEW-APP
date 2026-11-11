"""The BIS watch reads BIS through ServerHttpClient's ONE narrow allowance.

CI's no-sync-httpx-in-backend guard refuses a raw httpx.AsyncClient in
backend/ (the watch used one). ServerHttpClient refuses every Akamai-listed DOB
host, a810-bisweb included, and permit_renewal relies on that refusal to route
its license lookups through the worker. So the allowance is opt-in per client
(allow_bis_watch=True), GET only, and only the four read-only pages the watch
reads. Everything else stays refused.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.server_http import BIS_WATCH_PATHS, EgressViolation, ServerHttpClient  # noqa: E402

BIS = "https://a810-bisweb.nyc.gov"
WATCH_URLS = [
    f"{BIS}/bisweb/ComplaintsByAddressServlet?requestid=1&allbin=3255205",
    f"{BIS}/bisweb/OverviewForComplaintServlet?complaintno=3A88489&requestid=0",
    f"{BIS}/bisweb/PropertyProfileOverviewServlet?bin=3255205",
    f"{BIS}/bisweb/ECBQueryByLocationServlet?requestid=0&allbin=3255205",
]


def _call(client_kw, method, url, transport_status=200, location=None):
    def handler(request):
        if location and request.url.path != "/landing":
            return httpx.Response(302, headers={"location": location})
        return httpx.Response(transport_status, text="ok")

    async def go():
        async with ServerHttpClient(transport=httpx.MockTransport(handler), **client_kw) as c:
            return await c.request(method, url)
    return asyncio.run(go())


class TheAllowance(unittest.TestCase):
    def test_the_watch_reads_its_four_pages(self):
        self.assertEqual(len(BIS_WATCH_PATHS), 4)
        for u in WATCH_URLS:
            with self.subTest(url=u):
                self.assertEqual(_call({"allow_bis_watch": True}, "GET", u).status_code, 200)

    def test_every_other_caller_is_still_refused(self):
        for u in WATCH_URLS:
            with self.subTest(url=u), self.assertRaises(EgressViolation):
                _call({}, "GET", u)

    def test_only_get_and_only_those_pages(self):
        with self.assertRaises(EgressViolation):
            _call({"allow_bis_watch": True}, "POST", WATCH_URLS[0])
        # permit_renewal's license lookup: still the worker's.
        with self.assertRaises(EgressViolation):
            _call({"allow_bis_watch": True}, "GET", f"{BIS}/bisweb/LicenseQueryServlet?licensetype=G")
        with self.assertRaises(EgressViolation):
            _call({"allow_bis_watch": True}, "GET", "https://a810-dobnow.nyc.gov/publish/")

    def test_a_redirect_off_the_allowed_pages_is_refused(self):
        with self.assertRaises(EgressViolation):
            _call({"allow_bis_watch": True, "follow_redirects": True}, "GET", WATCH_URLS[0],
                  location=f"{BIS}/bisweb/LicenseQueryServlet")


class TheWatchUsesIt(unittest.TestCase):
    def test_the_tick_opens_server_http_client_with_the_allowance(self):
        src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
        start = src.index("async def bis_complaint_watch_tick")
        body = src[start:src.index("\n\n\n", start)]
        self.assertIn("ServerHttpClient(follow_redirects=True, allow_bis_watch=True)", body)
        self.assertNotIn("httpx.AsyncClient(", body)


if __name__ == "__main__":
    unittest.main()
