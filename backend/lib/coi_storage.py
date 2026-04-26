"""COI (Certificate of Insurance) storage + validation helpers.

Lives between the FastAPI endpoint and Cloudflare R2. All bytes-level
operations live here so the endpoint can stay thin and the units are
independently testable. R2 client + bucket are read off the existing
server.py globals via lazy import — no duplicate wiring.

Design constraints from the step-7 spec:
  - PDF only. Magic-byte check (first 4 bytes == b"%PDF") rejects
    images, docx, anything-else uploaded by mistake or malice.
  - 5MB hard cap. COI PDFs are typically 100-500 KB; anything larger
    is either not a COI or someone uploaded their phone gallery.
    Capping server-side prevents Qwen input-limit cascades.
  - SHA-256 idempotency. Same file bytes → same R2 key → same OCR
    cache hit. Admin double-clicking "Upload" never produces two
    R2 objects or two Qwen API charges.
  - 7-year retention metadata on every R2 PUT. NYC construction-
    related statute of limitations varies; 7 is the safe ceiling.

Nothing in this module is async — R2 / boto3 / pypdf / pdf2image are
all synchronous. Endpoint awaits these via run_in_executor so the
event loop doesn't block on a 300KB upload.
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from typing import Optional


logger = logging.getLogger(__name__)


# ── Validation constants ────────────────────────────────────────────

PDF_MAGIC = b"%PDF"
MAX_COI_BYTES = 5 * 1024 * 1024  # 5MB
ALLOWED_INSURANCE_TYPES = {"general_liability", "workers_comp", "disability"}
RETENTION_YEARS = 7


class CoiValidationError(ValueError):
    """Raised when uploaded bytes fail format or size checks. The
    endpoint translates this into an HTTP 4xx response."""


@dataclass
class ValidatedCoi:
    """Output of validate_pdf_bytes — the inputs the rest of the
    pipeline (R2 upload, OCR) needs in normalized form."""
    sha256_hex: str
    size_bytes: int
    page_count: int


# ── Validation ──────────────────────────────────────────────────────

def validate_pdf_bytes(content: bytes, *, expected_content_type: Optional[str] = None) -> ValidatedCoi:
    """Strict PDF + size validation. Raises CoiValidationError on
    failure with a human-readable message the endpoint can surface
    to the admin verbatim.
    """
    n = len(content or b"")
    if n == 0:
        raise CoiValidationError("Empty file.")
    if n > MAX_COI_BYTES:
        raise CoiValidationError(
            f"File too large ({n / 1024 / 1024:.1f} MB). "
            f"Max is {MAX_COI_BYTES // 1024 // 1024} MB."
        )

    if expected_content_type:
        ct = expected_content_type.split(";")[0].strip().lower()
        if ct not in ("application/pdf", "application/x-pdf"):
            raise CoiValidationError(
                f"Wrong content type {expected_content_type!r}. "
                f"Expected application/pdf."
            )

    if content[:4] != PDF_MAGIC:
        raise CoiValidationError(
            "File is not a valid PDF (missing %PDF header). "
            "Convert to PDF before uploading."
        )

    sha = hashlib.sha256(content).hexdigest()

    # Count pages defensively. A malformed PDF that survives the
    # magic-byte check is still allowed to fail here — that's the
    # right moment, before we spend Qwen API budget on bad input.
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        page_count = len(reader.pages)
    except Exception as e:
        raise CoiValidationError(
            f"PDF parse failed: {type(e).__name__}. The file may be "
            f"encrypted, corrupted, or not a real PDF."
        ) from e

    if page_count < 1:
        raise CoiValidationError("PDF has zero pages.")

    return ValidatedCoi(sha256_hex=sha, size_bytes=n, page_count=page_count)


# ── R2 keys ─────────────────────────────────────────────────────────

def coi_pdf_key(company_id: str, insurance_type: str, sha256_hex: str) -> str:
    """Same SHA-256 → same key. Idempotent uploads. The 16-char prefix
    is enough to avoid collisions across the practical universe of
    COIs a single company will ever upload (2^64 namespace)."""
    if insurance_type not in ALLOWED_INSURANCE_TYPES:
        raise CoiValidationError(
            f"Unknown insurance_type {insurance_type!r}. "
            f"Expected one of {sorted(ALLOWED_INSURANCE_TYPES)}."
        )
    return f"coi/{company_id}/{insurance_type}/{sha256_hex[:16]}.pdf"


def coi_preview_key(company_id: str, insurance_type: str, sha256_hex: str) -> str:
    """Companion JPEG of the first page, rendered for admin review."""
    return f"coi/{company_id}/{insurance_type}/{sha256_hex[:16]}.preview.jpg"


# ── First-page rendering ────────────────────────────────────────────

def render_first_page_jpeg(pdf_bytes: bytes, *, max_width: int = 1280) -> bytes:
    """Render PDF page 1 to JPEG bytes for admin side-by-side review.
    Uses pdf2image (poppler) which is already in the Dockerfile.

    JPEG quality 85 / max width 1280 keeps the preview under ~250 KB
    while remaining legible for OCR-cross-check by eye. Anything
    larger and the Settings page paint stalls on slow connections.
    """
    from pdf2image import convert_from_bytes
    from PIL import Image

    images = convert_from_bytes(
        pdf_bytes,
        dpi=150,
        first_page=1,
        last_page=1,
        fmt="jpeg",
    )
    if not images:
        raise CoiValidationError("Could not render first page of PDF.")

    img = images[0]
    if img.width > max_width:
        ratio = max_width / img.width
        new_size = (max_width, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


# ── R2 upload (sync; endpoint runs in executor) ─────────────────────

def upload_coi_objects(
    pdf_bytes: bytes,
    preview_bytes: bytes,
    pdf_key: str,
    preview_key: str,
    *,
    sha256_hex: str,
    insurance_type: str,
    company_id: str,
) -> dict:
    """Upload both the PDF and its first-page preview to R2 with
    7-year retention metadata. Returns {pdf_url, preview_url} or
    raises if R2 isn't configured / the upload fails.

    The R2 client + bucket name come from server.py module globals,
    same path the existing OSHA-card upload uses. Lazy import keeps
    this module decoupled from the FastAPI app.
    """
    from server import _r2_client, R2_BUCKET_NAME, R2_PUBLIC_URL, R2_ENDPOINT_URL

    if not _r2_client or not R2_BUCKET_NAME:
        raise RuntimeError(
            "R2 storage is not configured. Set R2_ACCOUNT_ID, "
            "R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME."
        )

    common_metadata = {
        "sha256": sha256_hex,
        "insurance-type": insurance_type,
        "company-id": str(company_id),
        "retention-years": str(RETENTION_YEARS),
    }

    _r2_client.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=pdf_key,
        Body=pdf_bytes,
        ContentType="application/pdf",
        Metadata=common_metadata,
    )
    _r2_client.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=preview_key,
        Body=preview_bytes,
        ContentType="image/jpeg",
        Metadata=common_metadata,
    )

    base = (R2_PUBLIC_URL or f"{R2_ENDPOINT_URL}/{R2_BUCKET_NAME}").rstrip("/")
    return {
        "pdf_url": f"{base}/{pdf_key}",
        "preview_url": f"{base}/{preview_key}",
        "pdf_key": pdf_key,
        "preview_key": preview_key,
    }
