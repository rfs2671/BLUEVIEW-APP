"""Tests for the COI OCR module — Qwen response parser, confidence
gate, threshold semantics. The actual Qwen HTTP call is mocked.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

import httpx

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib import coi_ocr  # noqa: E402
from lib.coi_ocr import (  # noqa: E402
    OCR_AUTO_ACCEPT_THRESHOLD,
    CoiOcrResult,
    OcrConfigError,
    extract_coi_fields,
    _parse_qwen_response,
)


def _run(coro):
    return asyncio.run(coro)


# Sample of the JSON shape the prompt asks Qwen to return. Use json.dumps
# rather than f-string + repr — Python's repr produces single-quoted
# strings which aren't valid JSON, and the parser correctly rejects them.
def _qwen_json(
    carrier="ACME Insurance Co",
    carrier_conf=0.98,
    policy="GL12345678",
    policy_conf=0.97,
    insured="Blueview Construction Inc",
    insured_conf=0.99,
    eff="01/15/2026",
    eff_conf=0.98,
    exp="01/15/2027",
    exp_conf=0.99,
):
    return json.dumps({
        "carrier_name": carrier,
        "carrier_name_confidence": carrier_conf,
        "policy_number": policy,
        "policy_number_confidence": policy_conf,
        "named_insured": insured,
        "named_insured_confidence": insured_conf,
        "effective_date": eff,
        "effective_date_confidence": eff_conf,
        "expiration_date": exp,
        "expiration_date_confidence": exp_conf,
    })


class TestParser(unittest.TestCase):

    def test_clean_response_parses(self):
        result = _parse_qwen_response(_qwen_json())
        self.assertEqual(result.carrier_name, "ACME Insurance Co")
        self.assertEqual(result.policy_number, "GL12345678")
        self.assertEqual(result.named_insured, "Blueview Construction Inc")
        self.assertEqual(result.effective_date, "01/15/2026")
        self.assertEqual(result.expiration_date, "01/15/2027")
        self.assertGreaterEqual(result.min_confidence, 0.97)
        self.assertTrue(result.auto_accept())

    def test_min_confidence_gates_auto_accept(self):
        """Carrier 0.99, expiration 0.7 → min 0.7 → admin must
        confirm. The whole point of per-field confidence: one shaky
        field forces full review."""
        result = _parse_qwen_response(_qwen_json(exp_conf=0.7))
        self.assertAlmostEqual(result.min_confidence, 0.7, places=2)
        self.assertFalse(result.auto_accept())

    def test_threshold_boundary(self):
        result = _parse_qwen_response(
            _qwen_json(
                carrier_conf=0.95,
                policy_conf=0.95,
                insured_conf=0.95,
                eff_conf=0.95,
                exp_conf=0.95,
            )
        )
        self.assertAlmostEqual(result.min_confidence, 0.95, places=2)
        self.assertTrue(result.auto_accept(),
                        "0.95 == threshold MUST auto-accept")

        result_below = _parse_qwen_response(_qwen_json(exp_conf=0.949))
        self.assertFalse(result_below.auto_accept(),
                         "0.949 < threshold MUST NOT auto-accept")

    def test_null_field_excluded_from_min(self):
        """If Qwen confidently says it can't read named_insured (null
        + low confidence), that shouldn't tank min confidence on the
        OTHER fields. Some COI layouts genuinely don't have an
        insured-name field where we expect it."""
        # Build JSON with the named_insured field as a JSON null so
        # _norm_str returns None on the v2 side.
        payload = {
            "carrier_name": "ACME Insurance Co",
            "carrier_name_confidence": 0.98,
            "policy_number": "GL12345678",
            "policy_number_confidence": 0.97,
            "named_insured": None,
            "named_insured_confidence": 0.0,
            "effective_date": "01/15/2026",
            "effective_date_confidence": 0.98,
            "expiration_date": "01/15/2027",
            "expiration_date_confidence": 0.99,
        }
        result = _parse_qwen_response(json.dumps(payload))
        self.assertGreaterEqual(result.min_confidence, 0.97)
        self.assertIsNone(result.named_insured)

    def test_fenced_json_response_parses(self):
        """Qwen sometimes wraps JSON in ```json ... ``` despite our
        prompt. Tolerated."""
        fenced = "```json\n" + _qwen_json() + "\n```"
        result = _parse_qwen_response(fenced)
        self.assertEqual(result.carrier_name, "ACME Insurance Co")

    def test_garbage_response_returns_empty_result(self):
        """If Qwen responds with prose / unparseable text, we return
        an all-None result with min_confidence 0.0 — admin reviews
        from scratch. We do NOT crash the upload endpoint."""
        result = _parse_qwen_response("I cannot read this image.")
        self.assertIsNone(result.carrier_name)
        self.assertEqual(result.min_confidence, 0.0)
        self.assertFalse(result.auto_accept())

    def test_invalid_date_format_drops_confidence(self):
        """If Qwen returns '15-01-2026' (DD-MM-YYYY) instead of MM/DD/YYYY,
        we don't accept it as a clean date. Confidence on that field
        drops to 0 even if Qwen claimed 0.98."""
        bad_date = _qwen_json(exp="15-01-2026", exp_conf=0.98)
        result = _parse_qwen_response(bad_date)
        self.assertEqual(result.per_field_confidence["expiration_date"], 0.0)
        self.assertFalse(result.auto_accept())

    def test_empty_string_field_normalized_to_none(self):
        result = _parse_qwen_response(_qwen_json(carrier=""))
        self.assertIsNone(result.carrier_name)

    def test_admin_payload_excludes_raw_response(self):
        result = _parse_qwen_response(_qwen_json())
        payload = result.as_admin_payload()
        self.assertNotIn("raw_response", payload)
        self.assertIn("auto_accept", payload)
        self.assertIn("min_confidence", payload)
        self.assertIn("per_field_confidence", payload)


class TestExtractCoiFields(unittest.TestCase):
    """End-to-end test of the OCR call with a mocked HTTP client."""

    def test_unknown_insurance_type_rejected(self):
        async def go():
            with self.assertRaises(ValueError):
                await extract_coi_fields(
                    b"jpg", insurance_type="auto",
                )
        _run(go())

    def test_missing_qwen_key_raises(self):
        async def go():
            import os
            with patch.dict(os.environ, {"QWEN_API_KEY": ""}, clear=False):
                os.environ.pop("QWEN_API_KEY", None)
                with self.assertRaises(OcrConfigError):
                    await extract_coi_fields(
                        b"jpg", insurance_type="general_liability",
                    )
        _run(go())

    def test_successful_call_returns_parsed(self):
        # Capture observations from inside the stub for assertions
        # in the outer scope. `self` inside the stub class is the
        # stub instance, not the test case.
        observed = {}

        class _StubClient:
            async def post(self, url, **kwargs):
                observed["headers"] = dict(kwargs.get("headers") or {})
                observed["body"] = kwargs.get("json") or {}
                return httpx.Response(200, json={
                    "choices": [{"message": {"content": _qwen_json()}}]
                })

            async def aclose(self):
                pass

        async def go():
            import os
            with patch.dict(os.environ, {"QWEN_API_KEY": "test-key"}):
                return await extract_coi_fields(
                    b"\xff\xd8\xff\xe0fake-jpeg",
                    insurance_type="general_liability",
                    http_client=_StubClient(),
                )

        result = _run(go())

        # Call shape — auth header, JSON model field, image_url with
        # data URL prefix.
        self.assertTrue(observed["headers"].get("Authorization", "").startswith("Bearer "))
        self.assertIn("model", observed["body"])
        msg = observed["body"]["messages"][0]["content"]
        self.assertEqual(msg[0]["type"], "image_url")
        self.assertTrue(msg[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

        # Parsed result.
        self.assertEqual(result.carrier_name, "ACME Insurance Co")
        self.assertTrue(result.auto_accept())

    def test_qwen_500_raises_runtime(self):
        async def go():
            import os

            class _StubClient:
                async def post(self, url, **kwargs):
                    return httpx.Response(500, text="internal error")

                async def aclose(self):
                    pass

            with patch.dict(os.environ, {"QWEN_API_KEY": "test-key"}):
                with self.assertRaises(RuntimeError) as ctx:
                    await extract_coi_fields(
                        b"jpg",
                        insurance_type="general_liability",
                        http_client=_StubClient(),
                    )
                self.assertIn("HTTP 500", str(ctx.exception))

        _run(go())


if __name__ == "__main__":
    unittest.main()
