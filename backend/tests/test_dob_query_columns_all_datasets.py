"""Every DOB/Open Data request the poller builds must name real columns -- and a
pass in which every dataset answers must open EVERY source's first-sync gate.

THE DEFECT (measured 2026-11-10 on 546 Saratoga Ave). The stop-work-order
address fallback filtered 3usq-5cid on `upper(street_name)`. That dataset's
column is `street`; Socrata answered

    HTTP 400 query.soql.no-such-column; No such column: street_name

on every 15-minute pass. A stop-work order is counted under the violations
source (lib/source_sync.RECORD_SOURCE["swo"] = dob_violations), and a source is
marked synced only when EVERY request for it answered, so `dob_violations` was
never first-synced for any project first polled after 2026-10-08 (the legacy
stand-in covers older ones). lib/source_sync makes every GC alert of a source
wait for that first sync: violation, stop-work and order alerts for 546 were
held silently and forever. The CofO version of this bug (pkdm-hqz6, Sept) has
its own test; this one covers every dataset the poller reads.

The column lists are a fixture captured from the live API on 2026-11-10
(tests/fixtures/dob_dataset_columns_2026-11-10.json). No network here.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

COLUMNS = json.loads((_HERE / "fixtures" / "dob_dataset_columns_2026-11-10.json").read_text())["columns"]
SOQL_WORDS = {"upper", "lower", "like", "and", "or", "not", "null", "is", "in", "between", "desc", "asc",
              "starts_with", "date_trunc_ymd"}


def _dataset(url: str) -> str:
    m = re.search(r"resource/([a-z0-9]{4}-[a-z0-9]{4})", url)
    return m.group(1) if m else ""


def _named_columns(params: dict) -> set:
    cols = {k for k in params if not k.startswith("$")}
    for key in ("$where", "$order", "$select"):
        expr = re.sub(r"'[^']*'", " ", str(params.get(key) or ""))
        cols |= {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr) if w.lower() not in SOQL_WORDS}
    return cols


class _Resp:
    def __init__(self, code, payload):
        self.status_code, self._p = code, payload

    def json(self):
        return self._p


class _SchemaClient:
    """Answers like Socrata: 400 when a request names an unknown column."""
    def __init__(self):
        self.calls = []

    async def get(self, url, params=None, **kw):
        params = dict(params or {})
        ds = _dataset(url)
        bad = sorted(_named_columns(params) - set(COLUMNS.get(ds, [])))
        self.calls.append((ds, params, bad))
        if ds in COLUMNS and bad:
            return _Resp(400, {"message": f"query.soql.no-such-column; No such column: {bad[0]}"})
        return _Resp(200, [])


class _Ctx:
    def __init__(self, c):
        self.c = c

    async def __aenter__(self):
        return self.c

    async def __aexit__(self, *a):
        return False


def _run(nyc_bin: str, address: str):
    import server
    client, answered = _SchemaClient(), {}
    with patch("server.ServerHttpClient", lambda *a, **k: _Ctx(client)):
        asyncio.run(server._query_dob_apis(nyc_bin, address, answered))
    return client.calls, answered


class EveryRequestNamesRealColumns(unittest.TestCase):
    def test_546_saratoga_requests_name_only_real_columns(self):
        calls, _ = _run("3255205", "546 SARATOGA AVENUE, Brooklyn, NY, USA")
        self.assertTrue(calls)
        bad = [(ds, b) for ds, _, b in calls if ds in COLUMNS and b]
        self.assertEqual(bad, [], f"requests naming columns the dataset does not have: {bad}")

    def test_every_polled_dataset_is_in_the_fixture(self):
        calls, _ = _run("3255205", "546 SARATOGA AVENUE, Brooklyn, NY, USA")
        missing = sorted({ds for ds, _, _ in calls} - set(COLUMNS))
        self.assertEqual(missing, [], "a new dataset needs its live columns added to the fixture")


class EverySourceCanFirstSync(unittest.TestCase):
    def test_a_pass_where_every_dataset_answers_opens_the_violations_gate(self):
        from lib import source_sync
        _, answered = _run("3255205", "546 SARATOGA AVENUE, Brooklyn, NY, USA")
        synced = source_sync.answered_sources(answered) & set(source_sync.DOB_SOURCES)
        self.assertIn("dob_violations", synced,
                      f"violations never first-sync, so violation/SWO alerts wait forever; answered={answered}")
        self.assertIn("dob_complaints", synced)


if __name__ == "__main__":
    unittest.main()
