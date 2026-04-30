"""Shared types for the handler dispatch contract.

Every handler in dob_worker/handlers/ must conform to:

    async def handle(payload: dict, context: HandlerContext) -> HandlerResult

dob_worker.py's dispatcher passes the same context to every handler;
each handler returns a HandlerResult that the dispatcher forwards to
/api/internal/job-result for state transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional


@dataclass
class HandlerContext:
    """Shared infrastructure passed into every handler call.

    browser:        Playwright Browser instance shared across handlers.
                    None during the v1 boot before Playwright initializes
                    (the bis_scrape handler creates its own browser);
                    populated for dob_now_filing once that handler runs.
    heartbeat_push: callable to push interim status outside the standard
                    60s heartbeat (e.g., on long-running form-fills).
    worker_id:      stable identifier for this worker process.
    http_client:    preconfigured httpx.AsyncClient with X-Worker-Secret
                    header pre-applied. Use for any cloud HTTP call —
                    the dispatcher won't pass anything else.
    """
    worker_id: str
    http_client: Any  # httpx.AsyncClient; Any to avoid hard import
    heartbeat_push: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
    browser: Any = None  # Playwright Browser; None until initialized


@dataclass
class HandlerResult:
    """Return shape for every handler.

    status: one of:
      "filed"           — successfully submitted to DOB NOW (transitions
                          renewal to AWAITING_DOB_APPROVAL on the cloud)
      "completed"       — DOB has confirmed the renewal (rare for
                          dob_now_filing handler; more common for
                          subsequent status-poll handlers in MR.8)
      "failed"          — terminal failure; cloud sets renewal.status =
                          FAILED and persists the failure_reason
      "not_implemented" — handler stub returned without doing work; cloud
                          logs but does not transition state
    detail:   human-readable explanation. Surfaces in audit logs and
              optionally in operator UI.
    metadata: free-form dict for handler-specific result data
              (e.g., DOB confirmation number, screenshot reference).
    """
    status: str
    detail: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "detail": self.detail,
            "metadata": self.metadata,
        }
