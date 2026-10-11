"""'%-d' / '%-I' are glibc extensions: Windows strftime raises ValueError on
them, and the punch dry run crashed there (live eval, Oct 11). Every
unpadded date goes through lib/datefmt.strftime, which expands them itself.

`WinDatetime` behaves like Windows: any '%-' reaching strftime raises."""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from lib import datefmt  # noqa: E402


class WinDatetime(datetime):
    def strftime(self, fmt):
        if re.search(r"(?<!%)%-", fmt):
            raise ValueError("Invalid format string")
        return super().strftime(fmt)


# Fri Oct 9 2026, 3:04:05 PM New York.
AT = WinDatetime(2026, 10, 9, 19, 4, 5, tzinfo=timezone.utc)


class TheFormatter(unittest.TestCase):

    def test_windows_style_strftime_refuses_the_glibc_codes(self):
        with self.assertRaises(ValueError):
            AT.strftime("%b %-d")

    def test_unpadded_codes_without_the_c_library(self):
        d = WinDatetime(2026, 1, 5, 7, 8, 9)
        self.assertEqual(datefmt.strftime(d, "%b %-d, %-I:%M:%S %p"), "Jan 5, 7:08:09 AM")
        self.assertEqual(datefmt.strftime(d, "%-m/%-d %-H:%-M:%-S"), "1/5 7:8:9")
        self.assertEqual(datefmt.strftime(d, "%a %b %-d"), "Mon Jan 5")
        # Two digits stay two; a literal "%%-d" is not a code.
        d = WinDatetime(2026, 12, 25, 23, 0)
        self.assertEqual(datefmt.strftime(d, "%b %-d, %-I %p"), "Dec 25, 11 PM")
        self.assertEqual(datefmt.strftime(d, "100%%-d"), "100%-d")


class NoGlibcCodesInTheBackend(unittest.TestCase):

    def test_no_strftime_format_with_a_dash_code(self):
        rx = re.compile(r"""\.strftime\(\s*[rbuf]*(["'])[^"']*%-[a-zA-Z]""")
        bad = []
        for p in BACKEND.rglob("*.py"):
            if "tests" in p.parts or "__pycache__" in p.parts or "node_modules" in p.parts:
                continue
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if rx.search(line):
                    bad.append(f"{p.relative_to(BACKEND)}:{n}")
        self.assertEqual(bad, [], "use lib.datefmt.strftime(dt, fmt) for %-d / %-I")


class TheCallSites(unittest.TestCase):

    def test_punch_who_closed(self):
        import server
        from tests._fake_mongo import FakeDb
        db = FakeDb()
        row = {"pid": "P7", "status": "closed", "closed_by": "u1", "closed_at": AT}
        with patch.object(server, "db", db), \
                patch.object(server, "_punch_find", AsyncMock(return_value=row)):
            got = asyncio.run(server._punch_answer({"projects": [{"_id": "p1"}]},
                                                   {"q": "who_closed", "pid": "P7"}))
        self.assertEqual(got, "P7 was closed by an admin on Oct 9, 3:04 PM.")

    def test_legal_render_clock_and_dob_short_date(self):
        from lib import dob_signal_templates
        from lib.legal_render import formatters
        self.assertEqual(formatters.time_of_day("2026-10-09T15:04:05"), "3:04 PM")
        self.assertEqual(dob_signal_templates._date_short("2026-10-09T15:04:05"), "Fri Oct 9")


if __name__ == "__main__":
    unittest.main()
