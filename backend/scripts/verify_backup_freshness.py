"""Phase C3 — Atlas backup freshness check.

Operator-runnable script that hits the Atlas Admin API, finds the
most recent successful snapshot for the production cluster, and
warns (via Sentry) + exits non-zero if the backup is older than a
configured threshold.

Run weekly via cron OR as a monthly operator task — whichever the
team prefers. The Atlas Admin API doesn't push notifications when
backups stall (e.g. quota exhausted, cluster paused, billing
suspended); a freshness probe is the only way to surface that
state proactively.

──────────────────────────────────────────────────────────────────
Environment
──────────────────────────────────────────────────────────────────

  ATLAS_PUBLIC_KEY            Atlas Programmatic API key (public).
  ATLAS_PRIVATE_KEY           Atlas Programmatic API key (private).
  ATLAS_GROUP_ID              Atlas Project ID (24-char hex).
  ATLAS_CLUSTER_NAME          Cluster name, e.g. "Cluster0".
  ATLAS_BACKUP_MAX_AGE_HOURS  Optional. Default 24. Backup older
                              than this is considered stale.
  SENTRY_DSN                  Optional. When set, stale-backup
                              and API-failure events are
                              captured as warnings.

The Atlas API key needs the Project Read Only role minimum (the
endpoint we hit is the snapshots list — read-only).

──────────────────────────────────────────────────────────────────
Exit codes
──────────────────────────────────────────────────────────────────

  0 — backup is fresh; nothing to do.
  1 — backup is stale OR API call failed. Operator must
      investigate. Sentry warning fired (if configured).
  2 — bad invocation (missing required env var). Treat as
      operator error, not as a backup problem.

Soft-failure design: an API hiccup (transient 5xx, network blip)
should not page the operator at 3am if the cluster's actually
healthy. The script logs the failure as a Sentry warning rather
than an error, and exits 1 — the next run (an hour or day later)
will re-check. If the failures persist, Sentry's dedup makes the
recurring issue visible.

──────────────────────────────────────────────────────────────────
Usage
──────────────────────────────────────────────────────────────────

    python -m scripts.verify_backup_freshness

    # Or explicit:
    cd backend && \\
    ATLAS_PUBLIC_KEY=xxx ATLAS_PRIVATE_KEY=yyy \\
    ATLAS_GROUP_ID=abc123... ATLAS_CLUSTER_NAME=Cluster0 \\
    python scripts/verify_backup_freshness.py

──────────────────────────────────────────────────────────────────
Architecture
──────────────────────────────────────────────────────────────────

Splits I/O (Atlas HTTP call) from decision logic (age comparison)
so unit tests can pass a stub HTTP client and still exercise the
fresh / stale / no-snapshots / API-failure branches without
hitting the real Atlas. See TestVerifyBackupFreshness.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Atlas Admin API base. Versioned via Accept header (see _ATLAS_ACCEPT).
ATLAS_BASE_URL = "https://cloud.mongodb.com/api/atlas/v2"
# Atlas Admin API uses date-based versioning on a custom media type.
# Pin this so the script's behavior is stable across Atlas's own
# deprecation cycle. Bump only after re-reading the changelog.
_ATLAS_ACCEPT = "application/vnd.atlas.2024-08-05+json"

DEFAULT_MAX_AGE_HOURS = 24


# ──────────────────────────────────────────────────────────────────
# I/O
# ──────────────────────────────────────────────────────────────────


@dataclass
class _Snapshot:
    """Subset of the Atlas snapshot doc we actually care about."""
    id: str
    created_at: datetime
    status: str
    type: str

    @classmethod
    def from_atlas(cls, doc: Dict[str, Any]) -> "_Snapshot":
        # Atlas createdAt is ISO-8601 with 'Z'. Python's
        # fromisoformat doesn't handle 'Z' before 3.11; replace
        # with +00:00 to be safe across versions.
        raw_ts = doc.get("createdAt", "")
        ts = raw_ts.replace("Z", "+00:00") if raw_ts.endswith("Z") else raw_ts
        return cls(
            id=str(doc.get("id", "")),
            created_at=datetime.fromisoformat(ts),
            status=str(doc.get("status", "")),
            type=str(doc.get("type", "")),
        )


def fetch_latest_snapshot(
    *,
    public_key: str,
    private_key: str,
    group_id: str,
    cluster: str,
    http_client: Optional[Any] = None,
) -> Optional[_Snapshot]:
    """Hit the Atlas snapshots endpoint and return the most-recent
    successful snapshot (or None if there are no snapshots yet).

    `http_client` exists for tests — pass a stub that supports
    `.get(url, headers=..., auth=..., timeout=...)`. In production,
    a real `httpx.Client` is constructed.

    Raises any HTTP error or JSON parse error. The caller (main)
    decides how to surface those — we keep this function small
    and deterministic.
    """
    url = (
        f"{ATLAS_BASE_URL}/groups/{group_id}/clusters/{cluster}"
        f"/backup/snapshots"
    )
    headers = {"Accept": _ATLAS_ACCEPT}

    if http_client is None:
        # Real Atlas request. httpx is already a project dep —
        # imported lazily so tests that pass a stub don't pay for
        # the import (and don't need network).
        import httpx
        from httpx import DigestAuth
        with httpx.Client(timeout=30.0) as c:
            resp = c.get(url, headers=headers, auth=DigestAuth(public_key, private_key))
            resp.raise_for_status()
            payload = resp.json()
    else:
        resp = http_client.get(url, headers=headers,
                               auth=(public_key, private_key))
        # Stub clients in tests should expose .raise_for_status() +
        # .json() to mimic httpx.Response.
        resp.raise_for_status()
        payload = resp.json()

    results: List[Dict[str, Any]] = payload.get("results") or []
    if not results:
        return None

    completed = [
        d for d in results
        if (d.get("status") or "").lower() in ("completed", "succeeded")
    ]
    pool = completed or results
    pool.sort(key=lambda d: d.get("createdAt", ""), reverse=True)
    return _Snapshot.from_atlas(pool[0])


# ──────────────────────────────────────────────────────────────────
# Decision logic (pure, testable)
# ──────────────────────────────────────────────────────────────────


def evaluate_freshness(
    snapshot: Optional[_Snapshot],
    max_age_hours: float,
    *,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[float], str]:
    """Decide whether the supplied snapshot is fresh.

    Returns (is_fresh, age_hours, message).

      - snapshot is None → not fresh; age_hours None; message
        "no snapshots found" — happens for a brand-new cluster
        before its first scheduled backup runs.
      - snapshot newer than max_age_hours → fresh.
      - snapshot older → not fresh.

    `now` is injected for tests. Defaults to wall-clock UTC.
    """
    if snapshot is None:
        return False, None, "no snapshots found in Atlas API response"

    current = now or datetime.now(timezone.utc)
    if snapshot.created_at.tzinfo is None:
        # Defensive: assume UTC if Atlas returned a naive datetime
        # (shouldn't happen with from_atlas).
        snapshot_at = snapshot.created_at.replace(tzinfo=timezone.utc)
    else:
        snapshot_at = snapshot.created_at

    delta = current - snapshot_at
    age_hours = delta.total_seconds() / 3600.0
    if age_hours <= max_age_hours:
        return True, age_hours, (
            f"latest snapshot {snapshot.id} is {age_hours:.1f}h old "
            f"(within {max_age_hours}h threshold)"
        )
    return False, age_hours, (
        f"latest snapshot {snapshot.id} is {age_hours:.1f}h old "
        f"(threshold {max_age_hours}h)"
    )


# ──────────────────────────────────────────────────────────────────
# Sentry helper (graceful no-op without SDK)
# ──────────────────────────────────────────────────────────────────


def _default_sentry_capture(message: str, *, level: str = "warning") -> None:
    """Capture a message via Sentry if the SDK is installed AND
    a DSN is configured. No-op otherwise — local runs of the
    script (no DSN) shouldn't crash on import."""
    try:
        import sentry_sdk  # type: ignore
    except ImportError:
        return
    if not (os.environ.get("SENTRY_DSN") or "").strip():
        return
    try:
        # Best-effort init — scripts run outside the FastAPI
        # process so the long-lived `sentry_sdk.init` from
        # server.py hasn't fired here.
        sentry_sdk.init(
            dsn=os.environ["SENTRY_DSN"],
            traces_sample_rate=0.0,
        )
        sentry_sdk.capture_message(message, level=level)
    except Exception:
        # Never let Sentry errors mask the actual stale-backup
        # signal. Fall through silently.
        pass


# ──────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────


def main(
    argv: Optional[List[str]] = None,
    *,
    http_client: Optional[Any] = None,
    sentry_capture: Optional[Callable[..., None]] = None,
    env: Optional[Dict[str, str]] = None,
    exit_fn: Callable[[int], None] = sys.exit,
    now: Optional[datetime] = None,
    stdout=None,
) -> int:
    """Entry point. Wires env reads + Atlas call + freshness check
    + Sentry capture + stdout reporting.

    Every side-effect dependency is injectable for tests:
      env             — env-var dict (defaults to os.environ).
      http_client     — stub HTTP client (defaults to real httpx).
      sentry_capture  — function (defaults to _default_sentry_capture).
      exit_fn         — exit fn (defaults to sys.exit; tests pass
                        a no-op so they can read the return value).
      now             — clock injection for evaluate_freshness.
      stdout          — file-like for human-readable summary.
    """
    env = env if env is not None else os.environ
    sentry = sentry_capture or _default_sentry_capture
    out = stdout or sys.stdout

    # ── Env validation ────────────────────────────────────────────
    required = ("ATLAS_PUBLIC_KEY", "ATLAS_PRIVATE_KEY",
                "ATLAS_GROUP_ID", "ATLAS_CLUSTER_NAME")
    missing = [k for k in required if not (env.get(k) or "").strip()]
    if missing:
        msg = (
            f"verify_backup_freshness: missing required env vars: "
            f"{', '.join(missing)}"
        )
        print(msg, file=sys.stderr)
        # Exit code 2: bad invocation (operator config error,
        # NOT a backup problem). Don't fire Sentry — this is a
        # CLI usage error that pages would be noise.
        exit_fn(2)
        return 2

    public_key = env["ATLAS_PUBLIC_KEY"].strip()
    private_key = env["ATLAS_PRIVATE_KEY"].strip()
    group_id = env["ATLAS_GROUP_ID"].strip()
    cluster = env["ATLAS_CLUSTER_NAME"].strip()
    try:
        max_age_hours = float(
            env.get("ATLAS_BACKUP_MAX_AGE_HOURS")
            or DEFAULT_MAX_AGE_HOURS
        )
    except ValueError:
        max_age_hours = DEFAULT_MAX_AGE_HOURS

    # ── Atlas call ────────────────────────────────────────────────
    try:
        snapshot = fetch_latest_snapshot(
            public_key=public_key,
            private_key=private_key,
            group_id=group_id,
            cluster=cluster,
            http_client=http_client,
        )
    except Exception as e:
        msg = (
            f"verify_backup_freshness: Atlas API call failed for "
            f"cluster={cluster!r}: {e!r}"
        )
        print(msg, file=sys.stderr)
        # Soft-fail: warn (not error). A transient blip shouldn't
        # page; persistent blips will dedup-stack in Sentry.
        sentry(msg, level="warning")
        exit_fn(1)
        return 1

    # ── Freshness check ──────────────────────────────────────────
    is_fresh, age_hours, message = evaluate_freshness(
        snapshot, max_age_hours, now=now,
    )

    # Human-readable line for cron logs.
    print(f"verify_backup_freshness: {message}", file=out)

    if is_fresh:
        exit_fn(0)
        return 0

    # Stale or no snapshots → warn + exit 1.
    sentry(
        f"backup_stale cluster={cluster} {message}",
        level="warning",
    )
    exit_fn(1)
    return 1


if __name__ == "__main__":  # pragma: no cover
    main()
