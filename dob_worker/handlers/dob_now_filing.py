"""dob_now_filing handler — STUB ONLY in MR.5.

The real implementation (Playwright form-fill against DOB NOW using
the GC's decrypted credentials, per-GC BrowserContext via storage_state)
ships in MR.6 alongside the credentials data model and audit log.

This stub satisfies the handler contract so dob_worker.py's dispatch
loop can route jobs without crashing, and so end-to-end tests of the
dispatcher → handler → /api/internal/job-result pipeline can run
before the full filing logic lands.
"""

from __future__ import annotations

import logging

from lib.handler_types import HandlerContext, HandlerResult


logger = logging.getLogger(__name__)


async def handle(payload: dict, context: "HandlerContext") -> "HandlerResult":
    """Stub: returns status='not_implemented' so the cloud-side
    /api/internal/job-result endpoint logs but doesn't transition
    state. Real implementation in MR.6.

    Expected payload (per MR.5 task 6):
      {
        "permit_renewal_id": str,
        "encrypted_credentials_b64": str,
        "filing_rep_id": str,
        "pw2_field_map": {...},  # MR.4 mapper output
      }
    """
    permit_renewal_id = payload.get("permit_renewal_id")
    logger.info(
        "[dob_now_filing] stub invoked for permit_renewal_id=%s; "
        "real implementation lands in MR.6",
        permit_renewal_id,
    )
    return HandlerResult(
        status="not_implemented",
        detail="dob_now_filing handler not yet implemented; see MR.6",
        metadata={"permit_renewal_id": permit_renewal_id},
    )
