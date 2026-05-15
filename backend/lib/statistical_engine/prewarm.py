"""Phase V2.3 Commit 4 — Async pre-warm of peer_stats_cache on project creation.

When server.py creates a new project (POST /api/projects or
POST /api/onboarding/project), it spawns ``prewarm_peer_stats``
as a fire-and-forget ``asyncio.create_task``. The task:

  1. Re-fetches the project doc (the spawn site can't always pass a
     dict; we resolve from project_id to avoid stale data races).
  2. Dedups: if an in-flight or completed cache already exists
     (status ∈ {"pending", "ready"}), logs and returns. This makes
     duplicate spawns + idempotent retries safe.
  3. Stamps ``peer_stats_cache.status = "pending"`` with
     ``started_at = now()`` BEFORE the compute kicks off, so a
     concurrent ``compare_project_to_peers`` call observes the
     pending marker and doesn't race the background task.
  4. Runs ``compute_peer_stats_full`` inside a wait_for with a
     30-second hard cap (generous vs. the 5s sync-fallback timeout,
     since we're not blocking a user response).
  5. Categorizes exceptions explicitly:
       • asyncio.TimeoutError       → error_kind="timeout"
       • SocrataQueryError          → error_kind="socrata_error"
       • bare Exception (catch-all) → error_kind="unexpected"
     The outer task body has its own catch-all so nothing escapes
     into the asyncio loop's unhandled-exception logger.
  6. On success, persists the full cache and logs duration +
     peer-sample-size.
  7. On failure, writes ``status="failed"`` + ``failed_at = now``
     + ``error_kind`` + ``error_message`` so:
       (a) the admin diagnostics endpoint (later) can render the
           reason, and
       (b) the 24-hour retry escape hatch in
           ``compare_project_to_peers`` can decide whether to fall
           through to a sync retry.

NOT INSTANTIATED IN PRODUCTION OUTSIDE server.py. The pre-warm is
triggered exclusively by user-facing project creation. The test
data seed at server.py:24107 is intentionally NOT wired (per
Commit 4 spec).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from lib.server_http import ServerHttpClient
from lib.statistical_engine.baselines import compute_peer_stats_full
from lib.statistical_engine.socrata_client import (
    SocrataClient,
    SocrataQueryError,
)

try:
    from bson import ObjectId  # type: ignore
except ImportError:  # pragma: no cover — bson always available in prod
    ObjectId = None  # type: ignore


logger = logging.getLogger(__name__)


# ── Tunables ──────────────────────────────────────────────────────

# Background compute is allowed to run up to 60s before being
# cancelled. This is intentionally generous compared to the
# sync-path timeout because we're not blocking a user; we'd rather
# succeed slowly than fail fast.
#
# PR #14D Fix 4: bumped 30→60s alongside
# PEER_STATS_COMPUTE_TIMEOUT_SECONDS. Background prewarm runs
# the same cohort-aware path that surfaced the Menahan timeout
# — same defensive headroom applies.
PREWARM_TIMEOUT_SECONDS = 60.0


# ── Error kind labels ─────────────────────────────────────────────
#
# Stored verbatim in the failed cache doc's ``error_kind`` field so
# operators can grep for them in logs and the admin diagnostics
# endpoint can render distinct UI states (timeout vs. quota vs.
# code bug).

ERROR_KIND_TIMEOUT     = "timeout"
ERROR_KIND_SOCRATA     = "socrata_error"
ERROR_KIND_UNEXPECTED  = "unexpected"


# ── Project ID helpers ────────────────────────────────────────────


def _to_mongo_id(project_id: Any) -> Any:
    """Coerce a project_id into the form MongoDB stores. The
    create_project handlers in server.py pass the
    ``InsertOneResult.inserted_id`` directly (which is already an
    ObjectId from motor). But test harnesses sometimes pass the
    string form. This helper accepts both — if it looks like a
    24-char hex string, convert to ObjectId; otherwise leave as-is."""
    if ObjectId is None or isinstance(project_id, ObjectId):
        return project_id
    if isinstance(project_id, str) and len(project_id) == 24:
        try:
            return ObjectId(project_id)
        except Exception:
            return project_id
    return project_id


async def _resolve_project(db, project_id: Any) -> Optional[Dict[str, Any]]:
    """Look up the project doc by _id. Tolerant of both ObjectId
    and string forms (handlers pass ObjectId; tests sometimes
    pass strings). Returns None if not found (the prewarm task
    treats that as "log and exit", not an error).
    """
    try:
        return await db.projects.find_one({"_id": _to_mongo_id(project_id)})
    except Exception as e:
        logger.warning(
            "[prewarm] project lookup failed for %s: %r",
            project_id, e,
        )
        return None


async def _patch_cache_status(
    db,
    project_id: Any,
    *,
    status: str,
    started_at: Optional[datetime] = None,
    failed_at: Optional[datetime] = None,
    error_kind: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Partial-update the project's ``peer_stats_cache`` with a
    status marker. Uses dotted ``$set`` keys so any pre-existing
    full cache structure (e.g. from a previous successful compute
    that's now being re-warmed) is preserved field-by-field — we
    only overwrite the status-related fields explicitly.

    Errors here are logged + swallowed (the alternative is killing
    the background task on a transient Mongo blip; the cache will
    be re-derived on the next score recompute via the sync path).
    """
    update_fields: Dict[str, Any] = {"peer_stats_cache.status": status}
    if started_at is not None:
        update_fields["peer_stats_cache.started_at"] = started_at
    if failed_at is not None:
        update_fields["peer_stats_cache.failed_at"] = failed_at
    if error_kind is not None:
        update_fields["peer_stats_cache.error_kind"] = error_kind
    if error_message is not None:
        update_fields["peer_stats_cache.error_message"] = error_message
    try:
        await db.projects.update_one(
            {"_id": _to_mongo_id(project_id)},
            {"$set": update_fields},
        )
    except Exception as e:
        logger.error(
            "[prewarm] cache-status patch failed for %s (status=%s): %r",
            project_id, status, e,
        )


async def _persist_full_cache(
    db, project_id: Any, cache: Dict[str, Any],
) -> bool:
    """Replace the project's ``peer_stats_cache`` with a freshly-
    computed cache doc. Returns True on success.

    Uses a full ``$set: {peer_stats_cache: ...}`` rather than dotted
    field updates because the cache is structurally different on
    success vs. failure (the full cache carries per-BBL counts,
    peer_bbl_list, etc. that the failed marker doesn't). A clean
    overwrite ensures stale failed-state fields don't bleed
    through into the success doc.
    """
    try:
        await db.projects.update_one(
            {"_id": _to_mongo_id(project_id)},
            {"$set": {"peer_stats_cache": cache}},
        )
        return True
    except Exception as e:
        logger.exception(
            "[prewarm] full-cache persist failed for %s: %r",
            project_id, e,
        )
        return False


# ── The task entry point ──────────────────────────────────────────


async def prewarm_peer_stats(db, project_id: Any) -> None:
    """Background task: compute and persist peer_stats_cache for a
    newly-created project. Designed to be fire-and-forget — the
    entire body is wrapped in a catch-all so nothing escapes to
    the asyncio loop.

    Caller pattern (server.py):

        asyncio.create_task(
            prewarm_peer_stats(db, result.inserted_id),
            name=f"prewarm_peer_stats:{result.inserted_id}",
        )

    The task is intentionally silent on success at WARN+ levels —
    a one-line INFO log when ready is the only positive-path log
    so operators can spot the prewarm flowing without log noise on
    every project creation.
    """
    log_id = str(project_id)
    started_at = datetime.now(timezone.utc)

    try:
        # ── Step 1: resolve project doc ─────────────────────────
        project = await _resolve_project(db, project_id)
        if project is None:
            logger.warning(
                "[prewarm] project %s not found in db.projects; "
                "skipping (creation may have rolled back, or test "
                "harness handed us a bad id)",
                log_id,
            )
            return

        # ── Step 2: dedup on existing status ────────────────────
        existing_cache = project.get("peer_stats_cache") or {}
        existing_status = existing_cache.get("status")
        if existing_status in ("pending", "ready"):
            logger.info(
                "[prewarm] %s already %r; skipping re-warm "
                "(concurrent spawn or pre-existing cache)",
                log_id, existing_status,
            )
            return

        # ── Step 3: mark pending BEFORE compute starts ──────────
        # Critical for race-prevention: a concurrent
        # compare_project_to_peers call must see this marker so it
        # returns the pending zero-marker instead of racing us with
        # its own sync compute. This update happens before we even
        # construct the SocrataClient.
        await _patch_cache_status(
            db, project_id,
            status="pending",
            started_at=started_at,
            # Defensive: clear any leftover error fields from a
            # previous failed attempt that's now being retried.
            error_kind="",
            error_message="",
            failed_at=None,
        )

        # ── Step 4: run compute with categorized error handling ─
        # ServerHttpClient is per-task (matches the 40+ existing
        # call-site convention in server.py — see Stage 1 inventory).
        async with ServerHttpClient(timeout=10.0) as http:
            socrata = SocrataClient(http)
            try:
                cache = await asyncio.wait_for(
                    # PR #14C §6.1 — db threaded as required arg so
                    # the new internal classify + lazy-PLUTO refresh
                    # branches inside compute_peer_stats_full can
                    # persist their results.
                    compute_peer_stats_full(socrata, project, db),
                    timeout=PREWARM_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "[prewarm] %s timed out after %.1fs (kind=%s)",
                    log_id, PREWARM_TIMEOUT_SECONDS,
                    ERROR_KIND_TIMEOUT,
                )
                await _patch_cache_status(
                    db, project_id,
                    status="failed",
                    failed_at=datetime.now(timezone.utc),
                    error_kind=ERROR_KIND_TIMEOUT,
                    error_message=(
                        f"compute exceeded {PREWARM_TIMEOUT_SECONDS:.0f}s"
                    ),
                )
                return
            except SocrataQueryError as e:
                logger.error(
                    "[prewarm] %s Socrata failure: dataset=%s "
                    "status=%s repr=%r (kind=%s)",
                    log_id, e.dataset_id, e.status_code, e,
                    ERROR_KIND_SOCRATA,
                )
                # Cap error_message to a sensible length so we
                # don't blow up the project doc with a multi-KB
                # exception repr.
                err_summary = (
                    f"{e.dataset_id or '?'}:"
                    f"{e.status_code if e.status_code else 'transport'}"
                )
                await _patch_cache_status(
                    db, project_id,
                    status="failed",
                    failed_at=datetime.now(timezone.utc),
                    error_kind=ERROR_KIND_SOCRATA,
                    error_message=err_summary[:500],
                )
                return
            except Exception as e:
                # Catch-all for compute-path unexpected exceptions
                # (e.g. a bug in compute_peer_stats_full, a Mongo
                # blip inside it, etc.). Uses logger.exception so
                # the traceback hits the log — important because
                # this is the only signal an operator gets that a
                # code bug fired.
                logger.exception(
                    "[prewarm] %s unexpected exception during "
                    "compute (kind=%s)",
                    log_id, ERROR_KIND_UNEXPECTED,
                )
                await _patch_cache_status(
                    db, project_id,
                    status="failed",
                    failed_at=datetime.now(timezone.utc),
                    error_kind=ERROR_KIND_UNEXPECTED,
                    error_message=repr(e)[:500],
                )
                return

        # ── Step 5: persist full successful cache ───────────────
        persisted = await _persist_full_cache(db, project_id, cache)
        if not persisted:
            # The persist helper already logged; leave the cache
            # in whatever state Mongo's in. Next sync recompute
            # will re-derive.
            return

        duration_s = (
            datetime.now(timezone.utc) - started_at
        ).total_seconds()
        sample_size = (
            (cache.get("peer_criteria") or {}).get("sample_size", 0)
        )
        logger.info(
            "[prewarm] %s ready in %.2fs (peer_sample=%d, tier=%s)",
            log_id, duration_s, sample_size,
            (cache.get("peer_criteria") or {}).get("tier"),
        )

    except Exception as e:
        # ── Outer catch-all ──────────────────────────────────────
        # Last line of defense. Guards against anything the inner
        # try/except blocks miss: db.projects itself raising, an
        # asyncio cancellation propagating, an import-time bug in
        # one of the helpers, etc. The task signature is
        # ``async def ... -> None`` — anything that escapes here
        # would land in asyncio's unhandled-exception logger as
        # a noisy "Task exception was never retrieved" trace.
        logger.exception(
            "[prewarm] %s top-level exception swallowed: %r",
            log_id, e,
        )


# ──────────────────────────────────────────────────────────────────
# PR #14B — auto-classification trigger
# ──────────────────────────────────────────────────────────────────


async def maybe_classify_project_dob_type(
    socrata,
    project: Dict[str, Any],
    db,
    *,
    force: bool = False,
) -> None:
    """PR #14B — lazy auto-classification of ``dob_project_type``.

    Per Stage 2.A T7.c lock: fires the DOB classifier when:

      • ``nyc_bin`` is populated on the project doc, AND
      • ``dob_project_type`` is missing OR ``force=True``.

    The function short-circuits to a no-op when either guard
    fails — no Socrata query, no DB write. The ``force=True``
    branch is the entry point for the admin
    ``POST /api/admin/projects/{id}/classify-dob`` endpoint
    (T7.c hybrid: lazy default + manual override).

    Errors from the classifier are caught and logged — the
    trigger fires on the compliance-sync path and a transient
    Socrata failure must not block the sync.
    """
    if not project.get("nyc_bin"):
        # No BIN — classifier would short-circuit anyway, but
        # bailing here saves the Socrata call AND keeps test 54's
        # ``socrata.calls`` assertion clean (no query attempted).
        return

    if not force and project.get("dob_project_type"):
        # Idempotent: already classified.
        return

    try:
        # Lazy import to avoid a top-of-module circular: dob_classifier
        # imports from cohort_config / dob_now_parser / socrata_client
        # which are stable, but importing it at module top-level would
        # couple prewarm.py to its load order.
        from lib.statistical_engine.dob_classifier import (
            fetch_project_dob_classification,
        )
        proj_type, snapshot = await fetch_project_dob_classification(
            socrata, project, db,
        )
        # PR #14C: mirror the persisted result back onto the
        # in-memory project dict so the caller (typically
        # compute_peer_stats_full) sees the classification without
        # re-reading from db. The classifier persists to db.projects
        # via update_one, but does NOT mutate the in-memory dict —
        # so without this mirror, compute_peer_stats_full's
        # downstream cohort builder would still see
        # project["dob_project_type"] == None and short-circuit to
        # lifecycle_skip_reason="no_spec" with cohort_filter_spec={}.
        project["dob_project_type"]    = proj_type
        project["dob_job_snapshot"]    = snapshot
        # PR #14E: also mirror dob_extracted_scope so the cohort
        # builder's Q5 hybrid target_state derivation can read the
        # parser-extracted story_count without re-reading from db.
        # The classifier persists this in db.projects.update_one;
        # re-read via find_one keeps the in-memory dict in sync.
        try:
            project_id = project.get("_id") or project.get("id")
            if project_id is not None and getattr(db, "projects", None):
                fresh = await db.projects.find_one({"_id": project_id})
                if fresh and "dob_extracted_scope" in fresh:
                    project["dob_extracted_scope"] = fresh.get(
                        "dob_extracted_scope",
                    )
        except Exception:  # pragma: no cover — defensive
            pass
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[prewarm] maybe_classify_project_dob_type failed for "
            "project=%r bin=%r: %r",
            project.get("_id"), project.get("nyc_bin"), e,
        )
