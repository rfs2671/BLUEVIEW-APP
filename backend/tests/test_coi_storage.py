"""Tests for COI storage helpers — validation, idempotent keying,
preview rendering. R2 upload itself is exercised via mocks since
unit-testing real boto3 calls would be either slow or fragile.
"""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from lib import coi_storage  # noqa: E402
from lib.coi_storage import (  # noqa: E402
    CoiValidationError,
    MAX_COI_BYTES,
    PDF_MAGIC,
    coi_pdf_key,
    coi_preview_key,
    validate_pdf_bytes,
)


def _minimal_pdf_bytes() -> bytes:
    """A real-but-minimal PDF that pypdf can parse (one blank page)."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f\n"
        b"0000000009 00000 n\n"
        b"0000000052 00000 n\n"
        b"0000000098 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n149\n%%EOF\n"
    )


class TestValidatePdfBytes(unittest.TestCase):

    def test_valid_pdf_passes(self):
        result = validate_pdf_bytes(_minimal_pdf_bytes())
        self.assertEqual(result.page_count, 1)
        self.assertEqual(result.size_bytes, len(_minimal_pdf_bytes()))
        self.assertEqual(
            result.sha256_hex,
            hashlib.sha256(_minimal_pdf_bytes()).hexdigest(),
        )

    def test_empty_file_rejected(self):
        with self.assertRaises(CoiValidationError) as ctx:
            validate_pdf_bytes(b"")
        self.assertIn("Empty", str(ctx.exception))

    def test_oversize_rejected(self):
        big = b"%PDF" + b"X" * (MAX_COI_BYTES + 100)
        with self.assertRaises(CoiValidationError) as ctx:
            validate_pdf_bytes(big)
        self.assertIn("too large", str(ctx.exception).lower())

    def test_non_pdf_magic_rejected(self):
        """The most likely attack/footgun: someone uploads a JPEG.
        Magic-byte check catches it before R2 or Qwen sees it."""
        jpeg = b"\xff\xd8\xff\xe0" + b"X" * 100
        with self.assertRaises(CoiValidationError) as ctx:
            validate_pdf_bytes(jpeg)
        self.assertIn("not a valid PDF", str(ctx.exception))

    def test_wrong_content_type_rejected(self):
        with self.assertRaises(CoiValidationError) as ctx:
            validate_pdf_bytes(
                _minimal_pdf_bytes(),
                expected_content_type="image/jpeg",
            )
        self.assertIn("content type", str(ctx.exception).lower())

    def test_pdf_content_type_with_charset_accepted(self):
        """Real-world content-type headers sometimes include charset
        suffixes. application/pdf;charset=utf-8 should still pass."""
        result = validate_pdf_bytes(
            _minimal_pdf_bytes(),
            expected_content_type="application/pdf; charset=utf-8",
        )
        self.assertEqual(result.page_count, 1)

    def test_corrupted_pdf_rejected(self):
        """Magic bytes present but body unparseable. pypdf raises;
        we surface a clean error."""
        garbage = PDF_MAGIC + b"this is not actually a PDF body"
        with self.assertRaises(CoiValidationError) as ctx:
            validate_pdf_bytes(garbage)
        msg = str(ctx.exception).lower()
        self.assertTrue(
            "parse failed" in msg or "encrypted" in msg or "corrupted" in msg,
            f"unexpected error: {ctx.exception}",
        )


class TestCoiKeys(unittest.TestCase):

    def test_idempotent_key(self):
        """Same (company_id, type, sha) → same key. The whole point
        of the sha-based key derivation."""
        sha = "a" * 64
        k1 = coi_pdf_key("co123", "general_liability", sha)
        k2 = coi_pdf_key("co123", "general_liability", sha)
        self.assertEqual(k1, k2)
        self.assertEqual(k1, "coi/co123/general_liability/aaaaaaaaaaaaaaaa.pdf")

    def test_different_types_get_different_keys(self):
        sha = "a" * 64
        gl = coi_pdf_key("co123", "general_liability", sha)
        wc = coi_pdf_key("co123", "workers_comp", sha)
        self.assertNotEqual(gl, wc)

    def test_invalid_insurance_type_rejected(self):
        with self.assertRaises(CoiValidationError):
            coi_pdf_key("co123", "auto", "a" * 64)

    def test_preview_key_paired(self):
        sha = "b" * 64
        pdf = coi_pdf_key("co1", "disability", sha)
        prev = coi_preview_key("co1", "disability", sha)
        # Same directory + filename stem (sha prefix), different
        # extensions. Defends a future cleanup pass that wants to
        # delete both objects via a common prefix.
        pdf_stem = pdf.rsplit("/", 1)[1].split(".", 1)[0]
        prev_stem = prev.rsplit("/", 1)[1].split(".", 1)[0]
        self.assertEqual(pdf_stem, prev_stem)
        self.assertTrue(prev.endswith(".preview.jpg"))
        self.assertTrue(pdf.endswith(".pdf"))


class TestUploadCoiObjects(unittest.TestCase):
    """Exercises the R2 upload via a mocked boto3 client. Real R2
    auth lives outside unit-test scope."""

    def test_uploads_both_objects_with_metadata(self):
        mock_client = MagicMock()
        with patch.object(coi_storage, "__name__", "lib.coi_storage"):
            # Lazy-imported globals; patch at the module path the
            # function reads from.
            with patch.dict("sys.modules", {}):
                pass

        # Direct module patching (the function does `from server import _r2_client`)
        import sys as _sys
        fake_server = MagicMock()
        fake_server._r2_client = mock_client
        fake_server.R2_BUCKET_NAME = "test-bucket"
        fake_server.R2_PUBLIC_URL = "https://r2.example.com"
        fake_server.R2_ENDPOINT_URL = "https://endpoint.r2.example.com"
        _sys.modules["server"] = fake_server
        try:
            result = coi_storage.upload_coi_objects(
                pdf_bytes=b"PDFBODY",
                preview_bytes=b"JPGBODY",
                pdf_key="coi/co1/general_liability/abc.pdf",
                preview_key="coi/co1/general_liability/abc.preview.jpg",
                sha256_hex="abc",
                insurance_type="general_liability",
                company_id="co1",
            )
        finally:
            del _sys.modules["server"]

        self.assertEqual(mock_client.put_object.call_count, 2)
        calls = mock_client.put_object.call_args_list

        # PDF upload
        pdf_call = calls[0].kwargs
        self.assertEqual(pdf_call["Bucket"], "test-bucket")
        self.assertEqual(pdf_call["ContentType"], "application/pdf")
        self.assertEqual(pdf_call["Body"], b"PDFBODY")
        self.assertEqual(pdf_call["Metadata"]["sha256"], "abc")
        self.assertEqual(pdf_call["Metadata"]["retention-years"], "7")
        self.assertEqual(pdf_call["Metadata"]["insurance-type"], "general_liability")

        # Preview upload
        prev_call = calls[1].kwargs
        self.assertEqual(prev_call["ContentType"], "image/jpeg")
        self.assertEqual(prev_call["Body"], b"JPGBODY")
        # Same retention metadata applied to both.
        self.assertEqual(prev_call["Metadata"]["retention-years"], "7")

        # URL construction uses R2_PUBLIC_URL when present.
        self.assertTrue(
            result["pdf_url"].startswith("https://r2.example.com/coi/")
        )
        self.assertTrue(result["preview_url"].endswith(".preview.jpg"))


if __name__ == "__main__":
    unittest.main()
