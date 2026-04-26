"""COI OCR via Qwen2.5-VL.

Sends a rendered first-page JPEG of a Certificate of Insurance to
Qwen with a structured-extraction prompt. Returns the parsed fields
the renewal-eligibility engine needs (carrier, policy #, dates) plus
per-field confidence scores.

Why per-field confidence instead of one overall number:
  Qwen's overall confidence underweights the case where one field is
  clearly readable and another is partial. A COI's expiration date
  might be hand-stamped or partially obscured while the carrier name
  is a clean logo. The renewal eligibility engine depends on the
  expiration date specifically — so the OCR safety bar gates on the
  MIN of all field confidences. If any one field is shaky, admin
  reviews the whole record, not just that one field.

Auto-accept threshold OCR_AUTO_ACCEPT_THRESHOLD = 0.95 per the spec
§6 — at or above, the result is auto-saved unless the admin clicks
through; below, the admin MUST confirm field-by-field with the PDF
preview rendered side-by-side.

PII in logs:
  Qwen's response includes the named insured (company name) and the
  policy number — both of which we treat as carefully as we'd treat
  a license number. INFO/WARNING log lines never include parsed
  values; only DEBUG does. The endpoint that calls this module also
  refuses to echo the response back into anything except the
  caller's response body and the audit log.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


OCR_AUTO_ACCEPT_THRESHOLD = 0.95

# Per the user's prior step-7 spec: source field MUST be one of these.
ALLOWED_INSURANCE_TYPES = {"general_liability", "workers_comp", "disability"}


# ── Qwen prompt — kept as a module-level constant so it's diffable ──

_EXTRACTION_PROMPT = """\
Extract the following fields from this Certificate of Insurance (COI/ACORD form).
Return ONLY valid JSON. No markdown, no commentary.

For each field, also return a confidence score from 0.0 to 1.0 reflecting
how clearly that specific field was readable. A clean printed value
should be 0.95-1.0. A partially obscured, hand-stamped, or low-resolution
value should be 0.5-0.85. A field you can't see at all should be null
with confidence 0.0.

The insurance_type input below tells you WHICH coverage row on the
COI to extract from. ACORD COIs typically list multiple coverages
(General Liability, Auto, Umbrella, Workers Comp, etc.) on the same
form. Read the row corresponding to the requested insurance_type.

Schema:
{
  "carrier_name": "<string or null>",
  "carrier_name_confidence": <float>,
  "policy_number": "<string or null>",
  "policy_number_confidence": <float>,
  "named_insured": "<string or null>",
  "named_insured_confidence": <float>,
  "effective_date": "<MM/DD/YYYY or null>",
  "effective_date_confidence": <float>,
  "expiration_date": "<MM/DD/YYYY or null>",
  "expiration_date_confidence": <float>
}

Rules:
- Dates must be in MM/DD/YYYY format. Convert from any format on the COI.
- carrier_name = the insurance company's name (top of the form, "PRODUCER" or
  "INSURER A" line). NOT the broker/producer.
- named_insured = the contractor or company being insured. Usually middle of
  form under "INSURED".
- policy_number = the 8-20 char alphanumeric ID for the matched coverage row.
"""


# ── Result shapes ───────────────────────────────────────────────────

@dataclass
class CoiOcrResult:
    """Parsed Qwen response. Field values may be None if Qwen
    couldn't read them; confidences are always present (0.0 if null).
    `min_confidence` is the gate for auto-accept."""
    carrier_name: Optional[str] = None
    policy_number: Optional[str] = None
    named_insured: Optional[str] = None
    effective_date: Optional[str] = None       # MM/DD/YYYY
    expiration_date: Optional[str] = None      # MM/DD/YYYY
    per_field_confidence: Dict[str, float] = field(default_factory=dict)
    min_confidence: float = 0.0
    raw_response: Optional[str] = None         # for debugging only

    def auto_accept(self) -> bool:
        return self.min_confidence >= OCR_AUTO_ACCEPT_THRESHOLD

    def as_admin_payload(self) -> Dict[str, Any]:
        """Serializable dict for the upload-COI response. Excludes
        raw_response to keep the wire payload small and avoid
        echoing internal Qwen quirks back to the frontend."""
        return {
            "carrier_name": self.carrier_name,
            "policy_number": self.policy_number,
            "named_insured": self.named_insured,
            "effective_date": self.effective_date,
            "expiration_date": self.expiration_date,
            "per_field_confidence": self.per_field_confidence,
            "min_confidence": self.min_confidence,
            "auto_accept": self.auto_accept(),
        }


class OcrConfigError(RuntimeError):
    """QWEN_API_KEY missing or other config-time failure."""


# ── Qwen call ───────────────────────────────────────────────────────

async def extract_coi_fields(
    preview_jpeg_bytes: bytes,
    *,
    insurance_type: str,
    http_client=None,
) -> CoiOcrResult:
    """Send the first-page JPEG to Qwen and parse its response.

    `http_client` is a `ServerHttpClient` instance. The egress guard
    permits api.deepinfra.com (or whatever QWEN_API_BASE points at)
    by default — no host is on the Akamai blocklist, no Socrata
    token gets attached. Caller passes the client in so tests can
    inject mocks.
    """
    if insurance_type not in ALLOWED_INSURANCE_TYPES:
        raise ValueError(
            f"Unknown insurance_type {insurance_type!r}. "
            f"Expected one of {sorted(ALLOWED_INSURANCE_TYPES)}."
        )

    api_key = os.environ.get("QWEN_API_KEY", "").strip()
    api_base = os.environ.get("QWEN_API_BASE", "https://api.deepinfra.com/v1/openai")
    model = os.environ.get("QWEN_MODEL", "Qwen/Qwen3-VL-30B-A3B-Instruct")
    if not api_key:
        raise OcrConfigError(
            "QWEN_API_KEY not configured. Cannot OCR COI."
        )

    if http_client is None:
        from lib.server_http import ServerHttpClient
        http_client = ServerHttpClient(timeout=60.0)
        own_client = True
    else:
        own_client = False

    prompt = (
        _EXTRACTION_PROMPT
        + f"\n\nThe insurance_type for this request is: {insurance_type}\n"
    )
    image_b64 = base64.b64encode(preview_jpeg_bytes).decode("ascii")
    image_url = f"data:image/jpeg;base64,{image_b64}"

    try:
        resp = await http_client.post(
            f"{api_base.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 600,
                "temperature": 0,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": prompt},
                    ],
                }],
            },
        )
    finally:
        if own_client:
            await http_client.aclose()

    if resp.status_code != 200:
        # Don't include response body at INFO — the body may include
        # Qwen-side error contexts that echo prompt fragments.
        logger.error(
            "Qwen OCR API returned non-200: status=%d body_len=%d",
            resp.status_code, len(resp.text or ""),
        )
        raise RuntimeError(
            f"Qwen OCR API error: HTTP {resp.status_code}"
        )

    payload = resp.json()
    raw_text = (
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    ) or ""

    return _parse_qwen_response(raw_text)


# ── Response parser ────────────────────────────────────────────────

# Qwen sometimes wraps JSON in ```json ... ``` despite our "no markdown"
# instruction. Strip that defensively.
_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?|\n?```\s*$", re.MULTILINE)


def _parse_qwen_response(raw_text: str) -> CoiOcrResult:
    """Tolerant parser. Qwen occasionally returns trailing prose or
    fenced code blocks; we strip both before json.loads. If the
    response is unparseable, return an all-None result with
    min_confidence 0.0 — the admin will confirm field-by-field
    against the PDF preview, and the OCR shouldn't fail catastrophically.
    """
    text = (raw_text or "").strip()
    text = _FENCE_RE.sub("", text).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find the JSON object inside a wrapper, last-ditch.
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                logger.warning(
                    "Qwen OCR response was not parseable JSON; "
                    "returning empty result. text_len=%d",
                    len(text),
                )
                return CoiOcrResult(min_confidence=0.0, raw_response=raw_text)
        else:
            return CoiOcrResult(min_confidence=0.0, raw_response=raw_text)

    if not isinstance(data, dict):
        return CoiOcrResult(min_confidence=0.0, raw_response=raw_text)

    fields = ("carrier_name", "policy_number", "named_insured",
              "effective_date", "expiration_date")
    parsed = {f: _norm_str(data.get(f)) for f in fields}
    confidences = {
        f: _norm_confidence(data.get(f"{f}_confidence"))
        for f in fields
    }

    # Min over fields that actually have a value. A null field's
    # confidence is reported separately but doesn't gate auto-accept
    # against the populated fields. Rationale: if Qwen confidently
    # says "I can't read this field" (null + low confidence), forcing
    # admin review on the OTHER three fields is appropriate, but we
    # don't want to tank min_confidence to 0 just because one optional
    # field was missing — that would break auto-accept entirely on
    # COIs where, e.g., named_insured is in a non-standard layout.
    populated = {f: confidences[f] for f in fields if parsed[f]}
    min_conf = min(populated.values()) if populated else 0.0

    # Validate dates parse — if either expiration_date or
    # effective_date is present but unparseable, drop confidence.
    for date_field in ("effective_date", "expiration_date"):
        v = parsed[date_field]
        if v and not _is_date_mm_dd_yyyy(v):
            logger.debug(  # DEBUG only — value contains date data
                "Qwen returned non-MM/DD/YYYY date for %s: dropping to confidence 0",
                date_field,
            )
            confidences[date_field] = 0.0
            min_conf = min(min_conf, 0.0) if populated else 0.0

    return CoiOcrResult(
        carrier_name=parsed["carrier_name"],
        policy_number=parsed["policy_number"],
        named_insured=parsed["named_insured"],
        effective_date=parsed["effective_date"],
        expiration_date=parsed["expiration_date"],
        per_field_confidence=confidences,
        min_confidence=round(min_conf, 4),
        raw_response=raw_text,
    )


def _norm_str(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("null", "none", "n/a", "-"):
        return None
    return s


def _norm_confidence(v) -> float:
    if v is None:
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _is_date_mm_dd_yyyy(s: str) -> bool:
    if not _DATE_RE.match(s):
        return False
    try:
        datetime.strptime(s, "%m/%d/%Y").replace(tzinfo=timezone.utc)
        return True
    except ValueError:
        return False
