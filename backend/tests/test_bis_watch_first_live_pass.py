"""What the first live pass in production showed (2026-11-11 14:49 UTC).

546 Saratoga read cleanly. Two other projects did not:
  * 8 Walworth St: "BIN 3426220: unrecognized page" for complaints AND summonses
  * 588 Boyland:   "BIN 3255362: unrecognized page" for summonses

Two causes, both reproduced against BIS:
  1. BIS keeps a person's last search in a session cookie and can answer the
     next search of ANOTHER kind with the old page. Fetched from inside the
     production container, a complaints request for BIN 3426220 came back as the
     "OATH/ECB Violation Search by Location" page. The watch shared one client,
     so one cookie jar, across every project.
  2. A BIN with no complaints prints "NO COMPLAINT RECORDS FOUND" and an empty
     count; the parser took the LOT number (33) for the count: "33 complaints,
     0 rows", an incomplete read on every pass.

The pages here are BIS's own (tests/fixtures/bis_complaints/*_3426220_none.html,
fetched 2026-11-11).
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import httpx

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib import bis_complaints as bc, bis_violations as bv  # noqa: E402
from lib.server_http import ServerHttpClient  # noqa: E402

FIX = _HERE / "fixtures" / "bis_complaints"
NOW = datetime(2026, 11, 11, 14, 49, tzinfo=timezone.utc)
LIST_NONE = (FIX / "list_3426220_none.html").read_text(encoding="latin-1")
ECB_NONE = (FIX / "ecb_3426220_none.html").read_text(encoding="latin-1")


def _sessionful_bis():
    """BIS as it behaved: an ECB search stores itself in the session, and a
    complaints request carrying that session gets the ECB page back."""
    searches = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sid = request.headers.get("cookie", "")
        if "ECBQueryByLocationServlet" in request.url.path:
            searches["s1"] = "ecb"
            return httpx.Response(200, text=ECB_NONE, headers={"set-cookie": "JSESSIONID=s1; Path=/"})
        if "ComplaintsByAddressServlet" in request.url.path:
            if "JSESSIONID=s1" in sid and searches.get("s1") == "ecb":
                return httpx.Response(200, text=ECB_NONE)          # the old search
            return httpx.Response(200, text=LIST_NONE, headers={"set-cookie": "JSESSIONID=s2; Path=/"})
        return httpx.Response(404, text="")
    return handler


async def _ecb_then_complaints(wrap):
    async with ServerHttpClient(transport=httpx.MockTransport(_sessionful_bis()),
                                follow_redirects=True, allow_bis_watch=True) as raw:
        c = wrap(raw)
        await c.get(bv.ecb_list_url("3426220"))
        return await bc.read_bin(c, "3426220", now=NOW, known=set())


class NoSessionCarriedBetweenSearches(unittest.TestCase):
    def test_a_shared_session_gets_the_old_page_back(self):
        read = asyncio.run(_ecb_then_complaints(lambda c: c))
        self.assertFalse(read.ok)
        self.assertEqual(read.error, "unrecognized page")            # production's error

    def test_the_watch_sends_each_search_without_one(self):
        read = asyncio.run(_ecb_then_complaints(bc.StatelessBisClient))
        self.assertTrue(read.ok)
        self.assertTrue(read.complete)
        self.assertEqual((read.total, read.rows), (0, []))

    def test_a_complaints_list_continuation_keeps_its_session(self):
        jar = httpx.Cookies()
        jar.set("JSESSIONID", "s1")

        class _Fake:
            cookies = jar

            async def get(self, url, **kw):
                return dict(jar.items())
        c = bc.StatelessBisClient(_Fake())
        self.assertEqual(asyncio.run(c.get(bc.list_url("3255205", allcount="0019"))), {"JSESSIONID": "s1"})
        self.assertEqual(asyncio.run(c.get(bc.list_url("3255205"))), {})

    def test_the_tick_wraps_its_client(self):
        src = (_HERE.parent / "server.py").read_text(encoding="utf-8")
        start = src.index("async def bis_complaint_watch_tick")
        body = src[start:src.index("\n\n\n", start)]
        self.assertIn("bis_complaints.StatelessBisClient(client)", body)


class ABinWithNoComplaints(unittest.TestCase):
    def test_parses_as_zero_not_the_lot_number(self):
        page = bc.parse_complaint_list(LIST_NONE)
        self.assertEqual((page.bin, page.lot, page.total, page.rows), ("3426220", "33", 0, []))

    def test_reads_complete(self):
        class _One:
            async def get(self, url, **kw):
                return httpx.Response(200, text=LIST_NONE)
        read = asyncio.run(bc.read_bin(_One(), "3426220", now=NOW, known=set()))
        self.assertEqual((read.ok, read.complete, read.total, read.error), (True, True, 0, None))

    def test_pages_with_complaints_still_count_right(self):
        for f, total in (("list_3255205.html", 16), ("list_3423445.html", 1)):
            page = bc.parse_complaint_list((FIX / f).read_text(encoding="latin-1"))
            self.assertEqual((page.total, len(page.rows)), (total, total), f)

    def test_no_summonses_reads_complete(self):
        page = bv.parse_ecb_list(ECB_NONE)
        self.assertEqual((page["bin"], page["total_issued"], page["complete"], page["rows"]),
                         ("3426220", 0, True, []))


if __name__ == "__main__":
    unittest.main()
