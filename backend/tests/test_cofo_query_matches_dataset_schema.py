"""The CofO ingest path must only name columns that pkdm-hqz6 actually has.

WHY THIS TEST EXISTS
--------------------
The DOB NOW: Certificate of Occupancy ingest (dataset ``pkdm-hqz6``)
shipped with every column name wrong and nothing in the suite ever
executed the query, so the defect was invisible for the feature's whole
life. The endpoint config sorted on ``issuance_date``, a column that does
not exist; Socrata answers an unknown sort column with

    HTTP 400  query.soql.no-such-column; No such column: issuance_date

so *every* CofO fetch 400'd, 96 times a day, and zero CofO records were
ever ingested. ``_extract_cofo_fields`` read six more names that likewise
do not exist (``co_number``, ``co_type``, ``co_status``, ``issuance_date``,
``expiration_date``, ``job_filing_number``), and the address fallback
filtered on ``house_number`` where the real column is ``house_no``.

The suite could not have caught this, because a green unit test proves a
dict was built — not that Socrata would accept it. So this test compares
the request the code *builds* against the dataset's real schema:

  * every column the request sorts on,
  * every column it filters on (both simple ``col=value`` params and the
    identifiers inside ``$where``),
  * every column ``_extract_cofo_fields`` reads,

must be a real column of pkdm-hqz6.

It also pins three judgement calls that the raw "is it a real column"
check would not catch on its own: the sort column must be genuinely
sortable, null-issuance rows must be excluded, and the address fallback
must be borough-constrained and left-anchored.

THE FIXTURE
-----------
``PKDM_HQZ6_COLUMNS`` below was captured from the LIVE Socrata API on
2026-09-02 so this test runs offline and deterministically in CI. No
network call happens here — do not add one.

To refresh it (only when NYC changes the dataset's schema):

    curl -s "https://data.cityofnewyork.us/api/views/pkdm-hqz6.json" \
      | python -c "import json,sys; \
          print({c['fieldName']: c['dataTypeName'] \
                 for c in json.load(sys.stdin)['columns']})"

and paste the result below, updating the captured-on date in this
docstring and in the fixture's own comment.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

DATASET_SLUG = "pkdm-hqz6"

# ── FIXTURE ───────────────────────────────────────────────────────
# Captured from the live API on 2026-09-02 via
#   curl -s "https://data.cityofnewyork.us/api/views/pkdm-hqz6.json"
# (see module docstring for the refresh recipe). fieldName -> dataTypeName.
#
# Note the types, they are load-bearing for two of the assertions below:
#   • c_of_o_issuance_date is `text`, NOT a date. Its values look like
#     "12/02/24 10:07:53 AM", so ORDER BY on it sorts MM/DD/YY
#     lexicographically — "12/02/24" outranks "09/25/25". It is a real
#     column but a broken sort key.
#   • c_of_o_sequence is `number` and is never null (verified live:
#     0 of 81,264 rows), and tracks application_number
#     ("CO-000100309" ⇔ sequence 100309), so it is monotonic in filing
#     order and is the correct recency sort key.
PKDM_HQZ6_COLUMNS: Dict[str, str] = {
    "application_number": "text",
    "bbl": "text",
    "bin": "text",
    "block": "text",
    "borough": "text",
    "c_of_o_filing_type": "text",
    "c_of_o_issuance_date": "text",
    "c_of_o_number": "text",
    "c_of_o_sequence": "number",
    "c_of_o_status": "text",
    "censustract2010": "number",
    "citycouncildistrict": "text",
    "community_board": "number",
    "house_no": "text",
    "job_filing_name": "text",
    "job_type": "text",
    "latitude": "number",
    "longitude": "number",
    "lot": "text",
    "ntaname": "text",
    "number_of_dwelling_units": "text",
    "street_name": "text",
    "submitted_date": "calendar_date",
    "zip_code": "text",
}

# SoQL keywords / function names that appear as bare identifiers inside a
# $where clause and are NOT column references.
_SOQL_RESERVED = {
    "and", "or", "not", "is", "null", "like", "between", "in",
    "true", "false", "upper", "lower", "trim", "starts_with",
}


class _StubResponse:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _RecordingClient:
    """Captures (url, params) for every request _query_dob_apis builds.

    Returns an empty result list so no ingest happens — this test is
    about the SHAPE of the request, not its response.
    """

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def get(self, url, **kwargs):
        self.calls.append({"url": url, "params": kwargs.get("params") or {}})
        return _StubResponse([])


class _StubCtx:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *a):
        return None


def _cofo_requests(nyc_bin: str, project_address: str) -> List[Dict[str, Any]]:
    """Run _query_dob_apis with the network stubbed and return only the
    requests it built against the CofO dataset."""
    from server import _query_dob_apis

    client = _RecordingClient()
    with patch("server.ServerHttpClient", lambda *a, **k: _StubCtx(client)):
        asyncio.run(_query_dob_apis(
            nyc_bin=nyc_bin,
            project_address=project_address,
        ))
    return [c for c in client.calls if DATASET_SLUG in c["url"]]


def _identifiers_in_where(where: str) -> List[str]:
    """Bare identifiers in a $where clause, minus SoQL keywords and
    anything inside a string literal."""
    without_literals = re.sub(r"'[^']*'", " ", where)
    return [
        tok for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", without_literals)
        if tok.lower() not in _SOQL_RESERVED
    ]


def _identifiers_in_order(order: str) -> List[str]:
    """Column names in an $order clause ("col DESC, col2 ASC")."""
    cols = []
    for term in order.split(","):
        parts = term.strip().split()
        if parts:
            cols.append(parts[0])
    return cols


class _RecordingDict(dict):
    """A raw-record stand-in that remembers every key .get() asked for,
    so we can see exactly which source columns an extractor reads."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.read_keys: List[str] = []

    def get(self, key, default=None):
        self.read_keys.append(key)
        return super().get(key, default)


class TestCofoQueryMatchesDatasetSchema(unittest.TestCase):

    # A BIN whose leading digit (2) marks it as Bronx, plus a matching
    # address, so both the BIN endpoint and the address-fallback
    # endpoint are built.
    BIN = "2130855"
    ADDRESS = "2100 Bartow Ave, Bronx, NY 10475"

    def setUp(self):
        self.requests = _cofo_requests(self.BIN, self.ADDRESS)

    def test_cofo_endpoints_are_built_at_all(self):
        """Guard: if _query_dob_apis stops emitting CofO requests the
        rest of this file would vacuously pass."""
        self.assertGreaterEqual(
            len(self.requests), 2,
            f"expected a BIN endpoint and an address-fallback endpoint "
            f"for {DATASET_SLUG}, got {len(self.requests)}",
        )

    def test_every_column_the_request_names_is_a_real_column(self):
        """The defect that shipped: the request named columns Socrata
        does not have, so it 400'd on every call."""
        for req in self.requests:
            params = req["params"]
            named: List[str] = []

            # Simple filters: any non-$ param key is a column name.
            named += [k for k in params if not k.startswith("$")]

            if params.get("$order"):
                named += _identifiers_in_order(params["$order"])
            if params.get("$where"):
                named += _identifiers_in_where(params["$where"])
            if params.get("$select"):
                named += _identifiers_in_where(params["$select"])

            self.assertTrue(named, f"request names no columns at all: {params!r}")
            for col in named:
                self.assertIn(
                    col, PKDM_HQZ6_COLUMNS,
                    f"{DATASET_SLUG} has no column {col!r} — Socrata answers "
                    f"this request with HTTP 400 query.soql.no-such-column. "
                    f"Request params: {params!r}",
                )

    def test_sort_column_is_actually_sortable(self):
        """A real column is not enough: c_of_o_issuance_date is text-typed
        and holds MM/DD/YY strings, so DESC on it sorts "12/02/24" above
        "09/25/25". Sorting must use a genuinely ordered column."""
        for req in self.requests:
            order = req["params"].get("$order", "")
            self.assertTrue(order, f"CofO request has no $order: {req['params']!r}")
            for col in _identifiers_in_order(order):
                self.assertNotEqual(
                    col, "c_of_o_issuance_date",
                    "c_of_o_issuance_date is a TEXT column of MM/DD/YY "
                    "strings; ordering on it is lexicographic, not "
                    "chronological, so it does not return the most recent "
                    "certificates. Sort on c_of_o_sequence instead.",
                )
                self.assertIn(
                    PKDM_HQZ6_COLUMNS[col], ("number", "calendar_date"),
                    f"$order sorts on {col!r} of type "
                    f"{PKDM_HQZ6_COLUMNS[col]!r}; a text column does not "
                    f"sort chronologically.",
                )

    def test_null_issuance_rows_are_excluded(self):
        """A CofO with no issuance date is not evidence a building was
        completed, and it sorts FIRST under a DESC order (Socrata puts
        nulls first), so it silently consumes a slot in the $limit=50
        window. Filter it out server-side."""
        for req in self.requests:
            where = req["params"].get("$where", "")
            self.assertIn(
                "c_of_o_issuance_date", where,
                f"CofO request does not exclude null-issuance rows: "
                f"{req['params']!r}",
            )
            self.assertRegex(
                where.upper().replace("  ", " "),
                r"C_OF_O_ISSUANCE_DATE IS NOT NULL",
                f"expected an IS NOT NULL guard on c_of_o_issuance_date: "
                f"{where!r}",
            )

    def test_address_fallback_is_borough_constrained(self):
        """house_no + street_name matches in all five boroughs — 55 WATER
        STREET resolves to 48 rows across Manhattan and Brooklyn (verified
        live 2026-09-02). Without a borough constraint the fallback
        attributes another borough's certificates to this project."""
        fallback = [r for r in self.requests if "house_no" in r["params"]]
        self.assertTrue(
            fallback,
            "no address-fallback CofO request was built — if the fallback "
            "param was renamed, update this test.",
        )
        for req in fallback:
            where = req["params"].get("$where", "")
            self.assertIn(
                "borough", where,
                f"address fallback has no borough constraint, so it matches "
                f"the same house number and street in all five boroughs: "
                f"{req['params']!r}",
            )

    def test_borough_is_derivable_from_a_placeholder_bin(self):
        """The fallback matters most when bin_usable is False. A
        placeholder BIN (X000000) is unusable as a BIN but its leading
        digit still names the borough, so the constraint must still
        apply."""
        from server import _cofo_borough_label

        self.assertEqual(_cofo_borough_label("3000000", ""), "BROOKLYN")
        # And from the address tail when there is no BIN at all.
        self.assertEqual(
            _cofo_borough_label("", "100 Main St, Brooklyn, NY 11221"),
            "BROOKLYN",
        )
        self.assertEqual(
            _cofo_borough_label("", "1 Wall St, New York, NY 10005"),
            "MANHATTAN",
        )

    def test_undecidable_borough_degrades_openly(self):
        """When neither the BIN nor the address names a borough, the
        helper must say so rather than guess a default — a wrong
        borough is worse than an acknowledged ambiguity."""
        from server import _cofo_borough_label

        self.assertIsNone(_cofo_borough_label("", "100 Main St"))
        self.assertIsNone(_cofo_borough_label("", ""))

    def test_street_like_is_left_anchored(self):
        """'%BROADWAY%' also matches WEST BROADWAY (119 rows), EAST
        BROADWAY (49), E BROADWAY and W BROADWAY — different streets.
        Left-anchoring keeps suffix tolerance (ST/STREET) without the
        prefix bleed."""
        for req in self.requests:
            where = req["params"].get("$where", "")
            for literal in re.findall(r"like\s+'([^']*)'", where, re.I):
                self.assertFalse(
                    literal.startswith("%"),
                    f"street LIKE pattern {literal!r} is leading-wildcarded, "
                    f"so it matches streets that merely CONTAIN the name "
                    f"(WEST BROADWAY for BROADWAY).",
                )

    def test_where_clause_cannot_carry_soql_metacharacters(self):
        """The $where is f-string interpolated from the project address.
        _parse_address_components is the only thing standing between a
        user-supplied address and the query, so pin that it strips
        quotes, LIKE wildcards and comment syntax."""
        from server import _parse_address_components

        hostile = "100 MAIN' OR 1=1 --, Brooklyn, NY"
        house, street = _parse_address_components(hostile)
        for label, value in (("street", street), ("house number", house)):
            for ch in ("'", "%", "_", "-", "=", "(", ")", ";", "*"):
                self.assertNotIn(
                    ch, value,
                    f"_parse_address_components let {ch!r} through into the "
                    f"{label}; it is interpolated straight into $where. "
                    f"({ch!r} is a quote, a LIKE wildcard or comment syntax.)",
                )

        # And the sanitized value must survive into the built request
        # without reintroducing a quote.
        for req in _cofo_requests(self.BIN, hostile):
            self.assertEqual(
                req["params"].get("$where", "").count("'") % 2, 0,
                "unbalanced quotes in $where — a literal escaped the "
                "sanitizer.",
            )

    def test_extractor_only_reads_real_columns(self):
        """_extract_cofo_fields read six names that pkdm-hqz6 does not
        have, so every extracted field was None even if the query had
        succeeded."""
        from server import _extract_cofo_fields

        rec = _RecordingDict({c: f"<{c}>" for c in PKDM_HQZ6_COLUMNS})
        _extract_cofo_fields(rec)

        unknown = [k for k in rec.read_keys if k not in PKDM_HQZ6_COLUMNS]
        self.assertEqual(
            unknown, [],
            f"_extract_cofo_fields reads {unknown!r}, which {DATASET_SLUG} "
            f"does not have. These are dead reads that always yield None.",
        )

    def test_extractor_populates_every_field_it_declares(self):
        """Every key the extractor writes must be filled from a real
        column. A key that is structurally always None is a misleading
        absence, not a schema."""
        from server import _extract_cofo_fields

        out = _extract_cofo_fields({c: f"<{c}>" for c in PKDM_HQZ6_COLUMNS})
        empty = sorted(k for k, v in out.items() if v is None)
        self.assertEqual(
            empty, [],
            f"_extract_cofo_fields declares {empty!r} but cannot populate "
            f"them from any real column of {DATASET_SLUG}. Drop the key "
            f"rather than persisting a permanent None.",
        )

    def test_extracted_values_map_to_the_expected_columns(self):
        """Pin the actual mapping, not just that it is non-empty."""
        from server import _extract_cofo_fields

        out = _extract_cofo_fields({c: f"<{c}>" for c in PKDM_HQZ6_COLUMNS})
        self.assertEqual(out.get("co_number"), "<c_of_o_number>")
        self.assertEqual(out.get("cofo_type"), "<c_of_o_filing_type>")
        self.assertEqual(out.get("current_status"), "<c_of_o_status>")
        self.assertEqual(out.get("issuance_date"), "<c_of_o_issuance_date>")
        # job_filing_name holds the job filing NUMBER despite its name
        # (real value: '220480209').
        self.assertEqual(out.get("job_filing_number"), "<job_filing_name>")

    def test_no_expiration_date_key_is_persisted(self):
        """pkdm-hqz6 has no expiration column. Persisting
        expiration_date=None makes the dob-logs card read "no expiration"
        for a TCO that does in fact expire."""
        from server import _extract_cofo_fields

        out = _extract_cofo_fields({c: f"<{c}>" for c in PKDM_HQZ6_COLUMNS})
        # Pin the exact key set rather than banning one name: this fails
        # both if expiration_date comes back and if any other unsourceable
        # key is added.
        self.assertEqual(
            sorted(out),
            [
                "co_number",
                "cofo_type",
                "current_status",
                "issuance_date",
                "job_filing_number",
            ],
            "expiration_date cannot be sourced from pkdm-hqz6 (the dataset "
            "has no expiration column); writing it as a permanent None "
            "asserts an absence the data does not support — the dob-logs "
            "card would render a Temporary CofO, which really does expire, "
            "as having no expiration.",
        )

    def test_id_field_is_a_real_column(self):
        """id_field feeds dedup and the persisted raw_dob_id."""
        from server import _query_dob_apis  # noqa: F401  (import guard)

        client = _RecordingClient()
        captured: List[str] = []

        # _query_dob_apis does not expose its endpoint list, so read the
        # id_field off the module source region instead of guessing.
        import server as _server
        import inspect
        src = inspect.getsource(_server._query_dob_apis)
        for block in src.split("record_type")[1:]:
            if '"cofo"' in block.split("\n")[0]:
                m = re.search(r'"id_field":\s*"([a-z0-9_]+)"', block)
                if m:
                    captured.append(m.group(1))

        self.assertTrue(captured, "could not locate the cofo id_field")
        for field in captured:
            self.assertIn(
                field, PKDM_HQZ6_COLUMNS,
                f"cofo id_field {field!r} is not a column of "
                f"{DATASET_SLUG}; raw_dob_id would be the empty string and "
                f"every record would be dropped by the `if not raw_id` "
                f"guard in the dedup phase.",
            )


if __name__ == "__main__":
    unittest.main()
