"""Phase B2 — production data audit (operator-runnable).

Reads MONGO_URL + DB_NAME from environment variables; produces a
markdown report on stdout. Read-only by both convention AND code-
level guard: a wrapper around the Motor database object refuses any
write method (insert / update / delete / drop / index ops). Operators
should ALSO use a read-only Atlas connection string — but if they
forget, this script still won't write.

Usage:
    MONGO_URL='mongodb+srv://readonly_user:...@...' \
    DB_NAME='blueview' \
    python -m backend.scripts.audit_production \
      > docs/audits/production-data-audit-$(date +%%Y-%%m-%%d).md

Exit codes:
    0 — audit completed
    1 — Section 7 canary failed (filing_reps.credentials present)
    2 — bad invocation (missing env vars, etc.)

Section 7 (filing_reps credentials) is a hard canary: if any record
still carries a `credentials` field post-MR.14-4b, the script aborts
with a loud warning. Operator must run
migrate_clear_filing_rep_credentials before the audit can complete.

Section 11 (Atlas resource state — storage, connection count, replica
state) cannot be queried from Mongo alone. The script emits a
"MANUALLY FILL IN FROM ATLAS DASHBOARD" header with a checklist.

Performance:
  • Each query is timed; >5s triggers a warning to stderr.
  • Total runtime should be well under 30s on a healthy cluster.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

# Defer Motor import so the module can be imported in test contexts
# without the dep. The script needs Motor at runtime.
try:
    from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
except ImportError:
    AsyncIOMotorClient = None  # type: ignore
    AsyncIOMotorCollection = None  # type: ignore


# ── Read-only enforcement ─────────────────────────────────────────


# Methods on a Mongo collection that mutate data. The wrapper raises
# RuntimeError if any of these are accessed at all (even before
# they're called) — a fail-fast guard, not a try/except trap.
_BANNED_COLLECTION_METHODS = frozenset({
    # Inserts.
    'insert_one', 'insert_many',
    # Updates.
    'update_one', 'update_many', 'replace_one',
    # Deletes.
    'delete_one', 'delete_many',
    # Find-and-modify.
    'find_one_and_update', 'find_one_and_replace', 'find_one_and_delete',
    # Bulk.
    'bulk_write',
    # Schema / index ops.
    'create_index', 'create_indexes',
    'drop_index', 'drop_indexes',
    # Whole-collection ops.
    'rename', 'drop',
})


class ReadOnlyDatabase:
    """Wraps a Motor database; any collection access is wrapped in
    ReadOnlyCollection so write methods raise on lookup."""

    def __init__(self, motor_db):
        # Bypass our own __setattr__/__getattr__ to store the
        # underlying handle.
        object.__setattr__(self, '_db', motor_db)

    def __getattr__(self, name):
        attr = getattr(self._db, name)
        if AsyncIOMotorCollection is not None and isinstance(
            attr, AsyncIOMotorCollection
        ):
            return ReadOnlyCollection(attr)
        return attr

    def __getitem__(self, name):
        return ReadOnlyCollection(self._db[name])

    @property
    def name(self):
        return self._db.name

    @property
    def client(self):
        return self._db.client


class ReadOnlyCollection:
    """Wraps a Motor collection; raises on any banned method access."""

    def __init__(self, real_collection):
        object.__setattr__(self, '_coll', real_collection)

    def __getattr__(self, name):
        if name in _BANNED_COLLECTION_METHODS:
            raise RuntimeError(
                f"Read-only audit script attempted to call "
                f"{self._coll.name}.{name}() — refusing. "
                f"This script must never write to the database."
            )
        return getattr(self._coll, name)

    @property
    def name(self):
        return self._coll.name


# ── Concern model ─────────────────────────────────────────────────


SEVERITY_BLOCKER = "BLOCKER"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"

VALID_SEVERITIES = frozenset({
    SEVERITY_BLOCKER, SEVERITY_WARNING, SEVERITY_INFO,
})


@dataclass
class Concern:
    """A single anomaly the audit surfaces. Severity classification:

      • BLOCKER — prevents customer onboarding or indicates data
        integrity damage. Must be resolved before B3 ships.
      • WARNING — could trip the system in production. Should be
        addressed before significant onboarding scale.
      • INFO — notable but not actionable now.
    """
    severity: str
    section: str
    summary: str
    detail: str = ""
    fix_path: str = ""

    def __post_init__(self):
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(
                f"Invalid severity {self.severity!r}; must be one of "
                f"{sorted(VALID_SEVERITIES)}"
            )

    def to_markdown_row(self) -> str:
        return (
            f"- **[{self.severity}]** {self.summary}\n"
            f"  - {self.detail}\n"
            f"  - *Fix path:* {self.fix_path}\n"
            if (self.detail or self.fix_path)
            else f"- **[{self.severity}]** {self.summary}\n"
        )


# ── Timing helper ─────────────────────────────────────────────────


@asynccontextmanager
async def timed(name: str, slow_threshold_seconds: float = 5.0):
    """Context manager. Logs a warning to stderr if the wrapped
    operation exceeds slow_threshold_seconds."""
    start = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start
        if elapsed > slow_threshold_seconds:
            print(
                f"⚠️  [audit] slow query: {name} took {elapsed:.2f}s",
                file=sys.stderr,
            )


# ── Markdown helpers ──────────────────────────────────────────────


def md_table(headers: List[str], rows: List[List[Any]]) -> str:
    """Render a simple GitHub-flavored markdown table."""
    out = ["| " + " | ".join(headers) + " |"]
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def fmt_count(n: int) -> str:
    return f"{n:,}"


def fmt_dt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


# ── Preset detection — Python port of frontend/src/utils/notificationPresets.js ──


# Hard-coded constants kept in lockstep with the JS source. The
# accompanying test (test_audit_production.py::TestPythonPresetMatchesJS)
# parses notificationPresets.js and verifies these match exactly.
ALL_KINDS = (
    "permit_issued", "permit_expired", "permit_revoked", "permit_renewed",
    "filing_approved", "filing_disapproved", "filing_withdrawn", "filing_pending",
    "violation_dob", "violation_ecb", "violation_resolved",
    "stop_work_full", "stop_work_partial",
    "complaint_dob", "complaint_311",
    "inspection_scheduled", "inspection_passed", "inspection_failed",
    "final_signoff",
    "cofo_temporary", "cofo_final", "cofo_pending",
    "facade_fisp", "boiler_inspection", "elevator_inspection",
    "license_renewal_due",
)

CRITICAL_EMAIL_KINDS = (
    "violation_dob", "violation_ecb",
    "stop_work_full", "stop_work_partial",
    "inspection_failed", "filing_disapproved",
)

STANDARD_DIGEST_KINDS = (
    "permit_expired", "inspection_scheduled",
    "license_renewal_due", "complaint_dob",
)

# Compact JSON separators — matches JS JSON.stringify default
# (no spaces). Critical for byte-equal normalization.
_COMPACT_JSON = {"separators": (",", ":")}


def _normalize_override_entry(entry) -> str:
    """Mirror JS _normalizeOverrideEntry. Channels are sorted; keys
    appear in insertion order (channels, severity_threshold, delivery)
    to match the JS output byte-for-byte."""
    if not isinstance(entry, dict):
        return json.dumps(
            {"channels": [], "severity_threshold": "any", "delivery": "feed_only"},
            **_COMPACT_JSON,
        )
    channels_raw = entry.get("channels")
    channels = sorted(channels_raw) if isinstance(channels_raw, list) else []
    return json.dumps(
        {
            "channels": channels,
            "severity_threshold": entry.get("severity_threshold") or "any",
            "delivery": entry.get("delivery") or "feed_only",
        },
        **_COMPACT_JSON,
    )


def _normalize_override_map(map_) -> str:
    """Mirror JS _normalizeOverrideMap. Object keys are alphabetically
    sorted before serialization so insertion-order doesn't drift the
    hash."""
    if not isinstance(map_, dict):
        return "{}"
    sorted_keys = sorted(map_.keys())
    out = {k: _normalize_override_entry(map_[k]) for k in sorted_keys}
    return json.dumps(out, **_COMPACT_JSON)


def _normalize_routes(routes) -> str:
    """Mirror JS _normalizeRoutes. Channels in each severity bucket
    are sorted."""
    if not isinstance(routes, dict):
        return "{}"
    return json.dumps(
        {
            "critical": sorted(routes.get("critical") or [])
            if isinstance(routes.get("critical"), list) else [],
            "warning": sorted(routes.get("warning") or [])
            if isinstance(routes.get("warning"), list) else [],
            "info": sorted(routes.get("info") or [])
            if isinstance(routes.get("info"), list) else [],
        },
        **_COMPACT_JSON,
    )


def build_preset_overrides(preset_key: str) -> Optional[Dict[str, Dict[str, Any]]]:
    if preset_key == "critical_only":
        out = {}
        for k in CRITICAL_EMAIL_KINDS:
            out[k] = {
                "channels": ["email"],
                "severity_threshold": "any",
                "delivery": "immediate",
            }
        for k in ALL_KINDS:
            if k not in out:
                out[k] = {
                    "channels": [],
                    "severity_threshold": "any",
                    "delivery": "feed_only",
                }
        return out
    if preset_key == "standard":
        out = {}
        for k in CRITICAL_EMAIL_KINDS:
            out[k] = {
                "channels": ["email"],
                "severity_threshold": "any",
                "delivery": "immediate",
            }
        for k in STANDARD_DIGEST_KINDS:
            out[k] = {
                "channels": ["email"],
                "severity_threshold": "any",
                "delivery": "digest_daily",
            }
        for k in ALL_KINDS:
            if k not in out:
                out[k] = {
                    "channels": [],
                    "severity_threshold": "any",
                    "delivery": "feed_only",
                }
        return out
    if preset_key == "everything":
        return {
            k: {
                "channels": ["email"],
                "severity_threshold": "any",
                "delivery": "immediate",
            }
            for k in ALL_KINDS
        }
    return None


def build_preset_channel_routes(preset_key: str) -> Optional[Dict[str, List[str]]]:
    if preset_key == "critical_only":
        return {"critical": ["email"], "warning": [], "info": []}
    if preset_key == "standard":
        return {"critical": ["email"], "warning": ["email"], "info": []}
    if preset_key == "everything":
        return {"critical": ["email"], "warning": ["email"], "info": ["email"]}
    return None


def detect_active_preset(prefs: Optional[Dict[str, Any]]) -> str:
    """Returns 'critical_only' | 'standard' | 'everything' | 'custom'.
    Mirrors JS detectActivePreset exactly."""
    if not prefs:
        return "custom"
    actual_overrides_norm = _normalize_override_map(
        prefs.get("signal_kind_overrides") or {}
    )
    actual_routes_norm = _normalize_routes(
        prefs.get("channel_routes_default") or {}
    )
    for key in ("critical_only", "standard", "everything"):
        expected_overrides_norm = _normalize_override_map(build_preset_overrides(key))
        expected_routes_norm = _normalize_routes(build_preset_channel_routes(key))
        if (
            expected_overrides_norm == actual_overrides_norm
            and expected_routes_norm == actual_routes_norm
        ):
            return key
    return "custom"


# ── Section 1 — Projects ──────────────────────────────────────────


async def section_projects(db) -> Tuple[str, List[Concern]]:
    concerns: List[Concern] = []
    md: List[str] = ["## 1. Projects"]

    async with timed("projects.count_documents (active)"):
        active = await db.projects.count_documents({"is_deleted": {"$ne": True}})
    async with timed("projects.count_documents (deleted)"):
        deleted = await db.projects.count_documents({"is_deleted": True})

    md.append(f"- Active projects: **{fmt_count(active)}**")
    md.append(f"- Soft-deleted projects: **{fmt_count(deleted)}**")

    # track_dob_status distribution.
    md.append("\n### track_dob_status distribution")
    async with timed("projects track_dob_status agg"):
        cursor = db.projects.aggregate([
            {"$match": {"is_deleted": {"$ne": True}}},
            {"$group": {"_id": "$track_dob_status", "count": {"$sum": 1}}},
        ])
        rows = []
        async for row in cursor:
            label = row.get("_id")
            label_str = (
                "true" if label is True
                else "false" if label is False
                else "null" if label is None
                else f"missing/{label!r}"
            )
            rows.append([label_str, fmt_count(row.get("count") or 0)])
    md.append(md_table(["track_dob_status", "count"], rows))

    # BIN coverage.
    async with timed("projects.count_documents bin"):
        with_bin = await db.projects.count_documents({
            "is_deleted": {"$ne": True},
            "$and": [
                {"nyc_bin": {"$exists": True}},
                {"nyc_bin": {"$ne": None}},
                {"nyc_bin": {"$ne": ""}},
            ],
        })
    no_bin_with_addr = await db.projects.count_documents({
        "is_deleted": {"$ne": True},
        "$or": [
            {"nyc_bin": {"$exists": False}},
            {"nyc_bin": None},
            {"nyc_bin": ""},
        ],
        "$and": [
            {"address": {"$exists": True}},
            {"address": {"$ne": None}},
            {"address": {"$ne": ""}},
        ],
    })
    no_bin_no_addr = await db.projects.count_documents({
        "is_deleted": {"$ne": True},
        "$or": [
            {"nyc_bin": {"$exists": False}},
            {"nyc_bin": None},
            {"nyc_bin": ""},
        ],
        "$and": [
            {"$or": [
                {"address": {"$exists": False}},
                {"address": None},
                {"address": ""},
            ]},
        ],
    })

    md.append("\n### BIN coverage")
    md.append(md_table(
        ["category", "count"],
        [
            ["valid BIN", fmt_count(with_bin)],
            ["no BIN, has address fallback", fmt_count(no_bin_with_addr)],
            ["no BIN, no address (silent failure)", fmt_count(no_bin_no_addr)],
        ],
    ))

    # Silent-failure list.
    if no_bin_no_addr > 0:
        async with timed("projects silent-failure list"):
            cursor = db.projects.find(
                {
                    "is_deleted": {"$ne": True},
                    "$or": [
                        {"nyc_bin": {"$exists": False}},
                        {"nyc_bin": None},
                        {"nyc_bin": ""},
                    ],
                    "$and": [
                        {"$or": [
                            {"address": {"$exists": False}},
                            {"address": None},
                            {"address": ""},
                        ]},
                    ],
                },
                {"_id": 1, "name": 1, "company_id": 1, "track_dob_status": 1},
            ).limit(50)
            rows = []
            tracked_silent = 0
            async for r in cursor:
                rows.append([
                    str(r.get("_id")),
                    r.get("name") or "(unnamed)",
                    str(r.get("company_id") or "—"),
                    str(r.get("track_dob_status")),
                ])
                if r.get("track_dob_status") is True:
                    tracked_silent += 1
        md.append(
            "\n### Projects with no BIN AND no address fallback"
            " (top 50 listed)"
        )
        md.append(md_table(
            ["project_id", "name", "company_id", "track_dob_status"],
            rows,
        ))
        concerns.append(Concern(
            severity=SEVERITY_BLOCKER if tracked_silent > 0 else SEVERITY_WARNING,
            section="1. Projects",
            summary=(
                f"{no_bin_no_addr} project(s) lack BIN AND address — "
                "DOB monitoring cannot reach these projects."
            ),
            detail=(
                f"Of these, {tracked_silent} have track_dob_status=true "
                "and are silently failing (operator believes monitoring "
                "is on; nothing fires)."
            ),
            fix_path=(
                "Add address or BIN to each project, or set "
                "track_dob_status=false to surface the disabled state in "
                "the UI."
            ),
        ))

    # Top 10 companies by project count.
    md.append("\n### Top 10 companies by active project count")
    async with timed("projects top-companies agg"):
        cursor = db.projects.aggregate([
            {"$match": {"is_deleted": {"$ne": True}}},
            {"$group": {"_id": "$company_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "—"), fmt_count(r.get("count") or 0)])
    md.append(md_table(["company_id", "active project count"], rows))

    # Oldest + newest.
    async with timed("projects oldest"):
        oldest_doc = await db.projects.find_one(
            {"is_deleted": {"$ne": True}},
            {"created_at": 1, "name": 1},
            sort=[("created_at", 1)],
        )
    async with timed("projects newest"):
        newest_doc = await db.projects.find_one(
            {"is_deleted": {"$ne": True}},
            {"created_at": 1, "name": 1},
            sort=[("created_at", -1)],
        )
    md.append("\n### Date bounds")
    md.append(md_table(
        ["edge", "created_at", "name"],
        [
            ["oldest", fmt_dt((oldest_doc or {}).get("created_at")), (oldest_doc or {}).get("name") or "—"],
            ["newest", fmt_dt((newest_doc or {}).get("created_at")), (newest_doc or {}).get("name") or "—"],
        ],
    ))

    md.append(
        "\n```python\n# Aggregation: active project count by company\n"
        "[{'$match': {'is_deleted': {'$ne': True}}},\n"
        " {'$group': {'_id': '$company_id', 'count': {'$sum': 1}}},\n"
        " {'$sort': {'count': -1}}, {'$limit': 10}]\n```"
    )

    return "\n".join(md), concerns


# ── Section 2 — Companies ─────────────────────────────────────────


async def section_companies(db) -> Tuple[str, List[Concern]]:
    concerns: List[Concern] = []
    md: List[str] = ["## 2. Companies"]

    total = await db.companies.count_documents({"is_deleted": {"$ne": True}})
    md.append(f"- Total active companies: **{fmt_count(total)}**")

    # Per-company details: filing_reps count, has_insurance, project count, user count.
    async with timed("companies summary agg"):
        rows = []
        cursor = db.companies.find(
            {"is_deleted": {"$ne": True}},
            {"_id": 1, "name": 1, "filing_reps": 1, "gc_insurance_records": 1},
        )
        async for c in cursor:
            cid = c.get("_id")
            filing_reps = c.get("filing_reps") or []
            has_insurance = bool(c.get("gc_insurance_records"))
            project_count = await db.projects.count_documents({
                "company_id": cid, "is_deleted": {"$ne": True},
            })
            user_count = await db.users.count_documents({
                "company_id": cid,
            })
            rows.append({
                "company_id": str(cid),
                "name": c.get("name") or "(unnamed)",
                "filing_reps_count": len(filing_reps),
                "has_insurance": has_insurance,
                "active_projects": project_count,
                "users": user_count,
            })

    md.append("\n### Per-company summary")
    md.append(md_table(
        ["company_id", "name", "filing_reps", "insurance?", "projects", "users"],
        [[r["company_id"], r["name"], r["filing_reps_count"],
          "yes" if r["has_insurance"] else "no",
          r["active_projects"], r["users"]] for r in rows],
    ))

    # Anomalies.
    md.append("\n### Anomalies")
    no_reps = [r for r in rows if r["filing_reps_count"] == 0]
    no_proj = [r for r in rows if r["active_projects"] == 0]
    no_user = [r for r in rows if r["users"] == 0]

    md.append(md_table(
        ["anomaly", "count"],
        [
            ["companies with 0 filing reps", len(no_reps)],
            ["companies with 0 active projects", len(no_proj)],
            ["companies with 0 users", len(no_user)],
        ],
    ))

    if no_user:
        concerns.append(Concern(
            severity=SEVERITY_WARNING,
            section="2. Companies",
            summary=f"{len(no_user)} company doc(s) have 0 user accounts.",
            detail=(
                "Companies without any user account cannot self-serve "
                "the portal. May be staging/test docs OR onboarding "
                "rows that never completed."
            ),
            fix_path=(
                "Audit each: confirm intentional (test data) or "
                "complete onboarding by inviting at least one admin user."
            ),
        ))

    if no_reps:
        concerns.append(Concern(
            severity=SEVERITY_INFO,
            section="2. Companies",
            summary=(
                f"{len(no_reps)} company doc(s) have no filing_reps "
                "configured."
            ),
            detail=(
                "Filing reps are needed for the Start Renewal flow's "
                "applicant_* PW2 field mapping. Companies without one "
                "see 'No filing rep on company' on the Start Renewal "
                "readiness check."
            ),
            fix_path=(
                "Add a primary filing_rep via the Owner Portal before "
                "the company has renewable permits."
            ),
        ))

    # BlueView baseline.
    bv = next(
        (r for r in rows if "BLUEVIEW" in r["name"].upper()),
        None,
    )
    md.append("\n### BLUEVIEW CONSTRUCTION INC baseline")
    if bv:
        md.append(md_table(
            ["field", "value"],
            [
                ["company_id", bv["company_id"]],
                ["filing_reps", bv["filing_reps_count"]],
                ["has_insurance", "yes" if bv["has_insurance"] else "no"],
                ["active_projects", bv["active_projects"]],
                ["users", bv["users"]],
            ],
        ))
    else:
        md.append("- BLUEVIEW CONSTRUCTION INC not found in the company list.")
        concerns.append(Concern(
            severity=SEVERITY_WARNING,
            section="2. Companies",
            summary="BLUEVIEW CONSTRUCTION INC not found.",
            detail=(
                "The reference customer for the v1 monitoring product "
                "isn't in the companies collection. Either the name "
                "drifted (case / typo) or the record is missing."
            ),
            fix_path="Locate the canonical record and confirm its name field.",
        ))

    return "\n".join(md), concerns


# ── Section 3 — Users ─────────────────────────────────────────────


async def section_users(db) -> Tuple[str, List[Concern]]:
    concerns: List[Concern] = []
    md: List[str] = ["## 3. Users"]

    total = await db.users.count_documents({})
    md.append(f"- Total users: **{fmt_count(total)}**")

    # Role distribution.
    async with timed("users role agg"):
        cursor = db.users.aggregate([
            {"$group": {"_id": "$role", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "(none)"), fmt_count(r.get("count") or 0)])
    md.append("\n### Role distribution")
    md.append(md_table(["role", "count"], rows))

    # Top 10 by company.
    async with timed("users company agg"):
        cursor = db.users.aggregate([
            {"$group": {"_id": "$company_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "(none)"), fmt_count(r.get("count") or 0)])
    md.append("\n### Top 10 by company_id")
    md.append(md_table(["company_id", "count"], rows))

    # Orphaned users.
    orphaned = await db.users.count_documents({
        "$or": [
            {"company_id": {"$exists": False}},
            {"company_id": None},
            {"company_id": ""},
        ],
    })
    md.append(f"\n- Users without company association: **{fmt_count(orphaned)}**")
    if orphaned > 0:
        concerns.append(Concern(
            severity=SEVERITY_WARNING,
            section="3. Users",
            summary=f"{orphaned} user(s) without company_id.",
            detail=(
                "Orphaned users can't access company-scoped data. May "
                "be legacy from pre-multi-tenancy era, or onboarding "
                "rows that didn't complete."
            ),
            fix_path=(
                "Triage: assign to the right company OR delete if test "
                "data."
            ),
        ))

    # notification_preferences coverage.
    user_ids_cursor = db.users.find({}, {"_id": 1})
    user_ids = []
    async for u in user_ids_cursor:
        user_ids.append(str(u["_id"]))
    if user_ids:
        prefs_cursor = db.notification_preferences.find(
            {"user_id": {"$in": user_ids}, "project_id": None},
            {"user_id": 1},
        )
        users_with_prefs = set()
        async for p in prefs_cursor:
            users_with_prefs.add(str(p["user_id"]))
        prefs_count = len(users_with_prefs)
        no_prefs_count = total - prefs_count
        md.append(
            f"\n- Users with saved global notification_preferences: "
            f"**{fmt_count(prefs_count)}**"
        )
        md.append(
            f"- Users on synthesized defaults (no record): "
            f"**{fmt_count(no_prefs_count)}**"
        )

    return "\n".join(md), concerns


# ── Section 4 — dob_logs ──────────────────────────────────────────


async def section_dob_logs(db) -> Tuple[str, List[Concern]]:
    concerns: List[Concern] = []
    md: List[str] = ["## 4. dob_logs"]

    total = await db.dob_logs.count_documents({})
    md.append(f"- Total dob_log records: **{fmt_count(total)}**")

    # Top 20 by signal_kind.
    async with timed("dob_logs signal_kind agg"):
        cursor = db.dob_logs.aggregate([
            {"$group": {"_id": "$signal_kind", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "(none)"), fmt_count(r.get("count") or 0)])
    md.append("\n### Top 20 by signal_kind")
    md.append(md_table(["signal_kind", "count"], rows))

    # Record type distribution.
    async with timed("dob_logs record_type agg"):
        cursor = db.dob_logs.aggregate([
            {"$group": {"_id": "$record_type", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "(none)"), fmt_count(r.get("count") or 0)])
    md.append("\n### Record type distribution")
    md.append(md_table(["record_type", "count"], rows))

    # is_seed_transition split.
    async with timed("dob_logs seed_transition agg"):
        cursor = db.dob_logs.aggregate([
            {"$group": {"_id": "$is_seed_transition", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id")), fmt_count(r.get("count") or 0)])
    md.append("\n### is_seed_transition split")
    md.append(md_table(["is_seed_transition", "count"], rows))

    # Top 10 by company.
    async with timed("dob_logs company agg"):
        cursor = db.dob_logs.aggregate([
            {"$group": {"_id": "$company_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "(none)"), fmt_count(r.get("count") or 0)])
    md.append("\n### Top 10 by company_id")
    md.append(md_table(["company_id", "count"], rows))

    # Date bounds.
    oldest = await db.dob_logs.find_one(
        {}, {"detected_at": 1}, sort=[("detected_at", 1)],
    )
    newest = await db.dob_logs.find_one(
        {}, {"detected_at": 1}, sort=[("detected_at", -1)],
    )
    md.append("\n### Date bounds")
    md.append(md_table(
        ["edge", "detected_at"],
        [
            ["oldest", fmt_dt((oldest or {}).get("detected_at"))],
            ["newest", fmt_dt((newest or {}).get("detected_at"))],
        ],
    ))

    # >90d audit (TTL retention).
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    older = await db.dob_logs.count_documents({"detected_at": {"$lt": cutoff}})
    md.append(f"\n- Records older than 90 days: **{fmt_count(older)}**")
    if older > 0:
        concerns.append(Concern(
            severity=SEVERITY_INFO,
            section="4. dob_logs",
            summary=(
                f"{fmt_count(older)} record(s) older than 90 days "
                "remain in dob_logs."
            ),
            detail=(
                "TTL is 90d for most record_types and 365d for violations + "
                "swo. Some long retention is expected; flagging the "
                "absolute count for visibility."
            ),
            fix_path="Confirm TTL indexes are healthy (Section 10).",
        ))

    # severity field coverage.
    with_sev = await db.dob_logs.count_documents({
        "$and": [
            {"severity": {"$exists": True}},
            {"severity": {"$ne": None}},
        ],
    })
    md.append(f"- Records with severity field present: **{fmt_count(with_sev)}**")
    md.append(f"- Records without severity field: **{fmt_count(total - with_sev)}**")
    md.append(
        "\n*Note:* severity is computed at render time via "
        "lib.dob_signal_templates.render_signal — it is NOT stored on "
        "dob_log inserts as of v1. A non-zero with_sev count is "
        "unexpected and should be investigated."
    )
    if with_sev > 0:
        concerns.append(Concern(
            severity=SEVERITY_INFO,
            section="4. dob_logs",
            summary=(
                f"{fmt_count(with_sev)} record(s) have a severity field."
            ),
            detail=(
                "v1 schema doesn't write severity at insert time. May be "
                "legacy data from a pre-MR.14 era OR a code path we "
                "missed."
            ),
            fix_path=(
                "Audit which code path stamps severity; decide if this is "
                "worth deduplicating."
            ),
        ))

    return "\n".join(md), concerns


# ── Section 5 — notification_log ──────────────────────────────────


async def section_notification_log(db) -> Tuple[str, List[Concern]]:
    concerns: List[Concern] = []
    md: List[str] = ["## 5. notification_log"]

    total = await db.notification_log.count_documents({})
    md.append(f"- Total notification_log records: **{fmt_count(total)}**")

    # Status distribution.
    async with timed("notification_log status agg"):
        cursor = db.notification_log.aggregate([
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "(none)"), fmt_count(r.get("count") or 0)])
    md.append("\n### Status distribution")
    md.append(md_table(["status", "count"], rows))

    # trigger_type distribution.
    async with timed("notification_log trigger agg"):
        cursor = db.notification_log.aggregate([
            {"$group": {"_id": "$trigger_type", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "(none)"), fmt_count(r.get("count") or 0)])
    md.append("\n### Top 20 by trigger_type")
    md.append(md_table(["trigger_type", "count"], rows))

    # Last 7d hourly volume.
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    async with timed("notification_log hourly agg"):
        cursor = db.notification_log.aggregate([
            {"$match": {"sent_at": {"$gte": seven_days_ago}}},
            {"$group": {
                "_id": {
                    "$dateToString": {
                        "date": "$sent_at",
                        "format": "%Y-%m-%d %H:00",
                        "timezone": "UTC",
                    }
                },
                "count": {"$sum": 1},
            }},
            {"$sort": {"_id": 1}},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "(none)"), fmt_count(r.get("count") or 0)])
    md.append("\n### Last 7d hourly send volume")
    if rows:
        md.append(md_table(["hour (UTC)", "sends"], rows))
    else:
        md.append("- (no sends in last 7 days)")

    # Failed in last 7 days.
    failed_recent = await db.notification_log.count_documents({
        "status": "failed",
        "sent_at": {"$gte": seven_days_ago},
    })
    md.append(f"\n- Failed sends in last 7 days: **{fmt_count(failed_recent)}**")
    if failed_recent > 0:
        async with timed("notification_log recent failures sample"):
            cursor = db.notification_log.find(
                {"status": "failed", "sent_at": {"$gte": seven_days_ago}},
                {"trigger_type": 1, "recipient": 1, "error_detail": 1, "sent_at": 1},
            ).sort("sent_at", -1).limit(20)
            sample_rows = []
            async for r in cursor:
                sample_rows.append([
                    fmt_dt(r.get("sent_at")),
                    r.get("trigger_type") or "—",
                    r.get("recipient") or "—",
                    (r.get("error_detail") or "")[:80],
                ])
        md.append("\n#### Recent failures (top 20)")
        md.append(md_table(
            ["sent_at", "trigger_type", "recipient", "error (truncated)"],
            sample_rows,
        ))
        concerns.append(Concern(
            severity=SEVERITY_WARNING,
            section="5. notification_log",
            summary=(
                f"{failed_recent} failed send(s) in the last 7 days."
            ),
            detail=(
                "Failures may indicate Resend API issues, rate-limiting, "
                "or invalid recipient addresses. Sample table above lists "
                "recent failure error_detail."
            ),
            fix_path=(
                "Group by error_detail; if Resend-specific, check API key "
                "+ rate limits. If recipient-specific, audit user emails."
            ),
        ))

    # Top 10 recipients.
    async with timed("notification_log recipients agg"):
        cursor = db.notification_log.aggregate([
            {"$match": {"status": "sent"}},
            {"$group": {"_id": "$recipient", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "(none)"), fmt_count(r.get("count") or 0)])
    md.append("\n### Top 10 recipients (by sent count)")
    md.append(md_table(["recipient", "sent"], rows))

    return "\n".join(md), concerns


# ── Section 6 — permit_renewals ───────────────────────────────────


async def section_permit_renewals(db) -> Tuple[str, List[Concern]]:
    concerns: List[Concern] = []
    md: List[str] = ["## 6. permit_renewals"]

    total = await db.permit_renewals.count_documents({"is_deleted": {"$ne": True}})
    deleted = await db.permit_renewals.count_documents({"is_deleted": True})
    md.append(f"- Active permit_renewals: **{fmt_count(total)}**")
    md.append(f"- Soft-deleted (per MR.14 4b/5 cleanup): **{fmt_count(deleted)}**")

    # Status distribution.
    async with timed("permit_renewals status agg"):
        cursor = db.permit_renewals.aggregate([
            {"$match": {"is_deleted": {"$ne": True}}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "(none)"), fmt_count(r.get("count") or 0)])
    md.append("\n### Status distribution")
    md.append(md_table(["status", "count"], rows))

    # Stranded needs_insurance.
    async with timed("permit_renewals stranded agg"):
        cursor = db.permit_renewals.find(
            {
                "is_deleted": {"$ne": True},
                "status": "needs_insurance",
            },
            {"_id": 1, "company_id": 1, "job_number": 1,
             "current_expiration": 1, "days_until_expiry": 1, "created_at": 1},
        ).sort("created_at", 1).limit(20)
        rows = []
        async for r in cursor:
            rows.append([
                str(r.get("_id"))[-8:],
                str(r.get("company_id") or "—")[-6:],
                r.get("job_number") or "—",
                r.get("current_expiration") or "—",
                r.get("days_until_expiry"),
                fmt_dt(r.get("created_at")),
            ])
    md.append("\n### Top 20 stranded needs_insurance (oldest first)")
    if rows:
        md.append(md_table(
            ["id (last 8)", "co (last 6)", "job_number", "current_expiration", "days", "created_at"],
            rows,
        ))
    else:
        md.append("- (no stranded records — clean)")

    # Per-company distribution.
    async with timed("permit_renewals per-company agg"):
        cursor = db.permit_renewals.aggregate([
            {"$match": {"is_deleted": {"$ne": True}}},
            {"$group": {"_id": "$company_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "(none)"), fmt_count(r.get("count") or 0)])
    md.append("\n### Top 10 by company_id")
    md.append(md_table(["company_id", "count"], rows))

    return "\n".join(md), concerns


# ── Section 7 — filing_reps canary ────────────────────────────────


class CanaryFailed(Exception):
    """Raised when the filing_reps credentials canary detects orphan
    encrypted-credentials data — must abort the audit."""


async def section_filing_reps_canary(db) -> Tuple[str, List[Concern]]:
    """The B1a 4b cleanup REMOVED the credentials field from
    filing_reps. Any record still carrying it post-deploy is orphan
    encrypted data; the audit aborts (exit code 1) until the operator
    runs migrate_clear_filing_rep_credentials."""
    concerns: List[Concern] = []
    md: List[str] = ["## 7. filing_reps canary"]

    async with timed("filing_reps credentials canary"):
        with_creds = await db.companies.count_documents(
            {"filing_reps.credentials": {"$exists": True}}
        )

    if with_creds > 0:
        # Hard fail.
        raise CanaryFailed(
            f"filing_reps.credentials field present on {with_creds} "
            f"company doc(s). The MR.14 4b cleanup migration must run "
            f"before the audit can complete. Run: "
            f"`python -m backend.scripts.migrate_clear_filing_rep_credentials --execute`"
        )

    md.append(
        "✅ **CANARY CLEAN**: zero company docs carry the legacy "
        "`filing_reps.credentials` field. MR.14 4b cleanup verified."
    )

    # Distribution by company.
    async with timed("filing_reps per-company agg"):
        cursor = db.companies.aggregate([
            {"$match": {"is_deleted": {"$ne": True}}},
            {"$project": {
                "name": 1,
                "rep_count": {"$size": {"$ifNull": ["$filing_reps", []]}},
            }},
            {"$sort": {"rep_count": -1}},
            {"$limit": 20},
        ])
        rows = []
        async for r in cursor:
            rows.append([
                str(r.get("_id") or "—"),
                r.get("name") or "—",
                r.get("rep_count") or 0,
            ])
    md.append("\n### Top 20 companies by filing_reps count")
    md.append(md_table(["company_id", "name", "rep_count"], rows))

    # Filing reps without LeveLog user account.
    md.append("\n### Filing reps without LeveLog user account")
    cursor = db.companies.find(
        {"is_deleted": {"$ne": True}},
        {"filing_reps": 1},
    )
    rep_emails = set()
    async for c in cursor:
        for rep in (c.get("filing_reps") or []):
            email = (rep.get("email") or "").strip().lower()
            if email:
                rep_emails.add(email)
    if rep_emails:
        users_with_email_cursor = db.users.find(
            {"email": {"$in": list(rep_emails)}},
            {"email": 1},
        )
        users_with_email = set()
        async for u in users_with_email_cursor:
            users_with_email.add((u.get("email") or "").strip().lower())
        no_account = sorted(rep_emails - users_with_email)
    else:
        no_account = []
    md.append(
        f"- Filing rep emails without a LeveLog user account: "
        f"**{fmt_count(len(no_account))}** "
        f"(per-user notification preferences don't apply to these)"
    )
    if no_account:
        concerns.append(Concern(
            severity=SEVERITY_INFO,
            section="7. filing_reps",
            summary=(
                f"{len(no_account)} filing rep email(s) have no LeveLog "
                "user account."
            ),
            detail=(
                "These recipients receive notifications via the legacy "
                "non-preferences code path. Documented behavior — "
                "filing reps are licensed individuals, not necessarily "
                "app users."
            ),
            fix_path=(
                "No action required. Listed for audit completeness."
            ),
        ))

    return "\n".join(md), concerns


# ── Section 8 — notification_preferences ──────────────────────────


async def section_notification_preferences(db) -> Tuple[str, List[Concern]]:
    concerns: List[Concern] = []
    md: List[str] = ["## 8. notification_preferences"]

    total = await db.notification_preferences.count_documents({})
    user_global = await db.notification_preferences.count_documents(
        {"project_id": None}
    )
    project_scoped = await db.notification_preferences.count_documents(
        {"project_id": {"$ne": None}}
    )
    md.append(f"- Total records: **{fmt_count(total)}**")
    md.append(f"- User-global (project_id=null): **{fmt_count(user_global)}**")
    md.append(f"- Project-scoped: **{fmt_count(project_scoped)}**")

    # Preset distribution.
    async with timed("notification_preferences detection scan"):
        cursor = db.notification_preferences.find(
            {},
            {
                "signal_kind_overrides": 1,
                "channel_routes_default": 1,
                "project_id": 1,
                "created_at": 1,
            },
        )
        global_dist = {"critical_only": 0, "standard": 0, "everything": 0, "custom": 0}
        scoped_dist = {"critical_only": 0, "standard": 0, "everything": 0, "custom": 0}
        recent_count = 0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        async for doc in cursor:
            preset = detect_active_preset(doc)
            if doc.get("project_id") is None:
                global_dist[preset] = global_dist.get(preset, 0) + 1
            else:
                scoped_dist[preset] = scoped_dist.get(preset, 0) + 1
            created = doc.get("created_at")
            if isinstance(created, datetime):
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created >= cutoff:
                    recent_count += 1

    md.append("\n### Preset distribution — user-global records")
    md.append(md_table(
        ["preset", "count"],
        [[k, fmt_count(global_dist[k])]
         for k in ("critical_only", "standard", "everything", "custom")],
    ))
    md.append("\n### Preset distribution — project-scoped records")
    md.append(md_table(
        ["preset", "count"],
        [[k, fmt_count(scoped_dist[k])]
         for k in ("critical_only", "standard", "everything", "custom")],
    ))
    md.append(f"\n- Records created in the last 24h (early adoption): **{fmt_count(recent_count)}**")

    md.append(
        "\n```python\n# Preset detection — see backend/scripts/audit_production.py\n"
        "# detect_active_preset(prefs) is a Python port of\n"
        "# frontend/src/utils/notificationPresets.js detectActivePreset.\n"
        "# Verified byte-equal by test_audit_production.py.\n```"
    )

    return "\n".join(md), concerns


# ── Section 9 — digest_queue ──────────────────────────────────────


async def section_digest_queue(db) -> Tuple[str, List[Concern]]:
    concerns: List[Concern] = []
    md: List[str] = ["## 9. digest_queue"]

    total = await db.digest_queue.count_documents({})
    md.append(f"- Total queue records: **{fmt_count(total)}**")

    # Status distribution.
    async with timed("digest_queue status agg"):
        cursor = db.digest_queue.aggregate([
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ])
        rows = []
        async for r in cursor:
            rows.append([str(r.get("_id") or "(none)"), fmt_count(r.get("count") or 0)])
    md.append("\n### Status distribution")
    md.append(md_table(["status", "count"], rows))

    # Stale queued (>24h past scheduled_send_at).
    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    stale = await db.digest_queue.count_documents({
        "status": "queued",
        "scheduled_send_at": {"$lt": cutoff_24h},
    })
    md.append(
        f"\n- Stale queued (scheduled >24h ago, still 'queued'): "
        f"**{fmt_count(stale)}**"
    )
    if stale > 0:
        concerns.append(Concern(
            severity=SEVERITY_WARNING,
            section="9. digest_queue",
            summary=(
                f"{fmt_count(stale)} digest record(s) past their "
                "scheduled_send_at by >24h are still queued."
            ),
            detail=(
                "digest_dispatcher cron should drain ready items every "
                "15 min. A backlog suggests the cron is unhealthy or "
                "the kill switch is on."
            ),
            fix_path=(
                "Check Railway scheduler logs for digest_dispatcher; "
                "verify NOTIFICATIONS_KILL_SWITCH is unset; manually "
                "trigger dispatcher if needed."
            ),
        ))

    # Oldest queued.
    async with timed("digest_queue oldest queued"):
        oldest_queued = await db.digest_queue.find_one(
            {"status": "queued"},
            {"queued_at": 1, "scheduled_send_at": 1},
            sort=[("queued_at", 1)],
        )
    if oldest_queued:
        md.append(
            f"\n- Oldest queued record queued_at: "
            f"`{fmt_dt(oldest_queued.get('queued_at'))}`"
        )
        md.append(
            f"- Oldest queued record scheduled_send_at: "
            f"`{fmt_dt(oldest_queued.get('scheduled_send_at'))}`"
        )
    else:
        md.append("\n- (no queued records — dispatcher caught up)")

    return "\n".join(md), concerns


# ── Section 10 — Indexes ──────────────────────────────────────────


# Critical indexes the B1a setup creates. Missing any of these means
# either the startup index pass didn't run OR the collection is empty
# (Mongo creates indexes on first write, but our _ensure_index_resilient
# eagerly creates them at startup).
EXPECTED_INDEXES = {
    "notification_preferences": {
        "notification_preferences_user_project_unique",
        "notification_preferences_user",
    },
    "digest_queue": {
        "digest_queue_status_sched",
        "digest_queue_user_sched",
    },
    "dob_logs": {
        "dob_logs_ttl_short",
        "dob_logs_ttl_long",
    },
    "renewal_alert_sent": {
        "renewal_alert_sent_idem",
        "renewal_alert_sent_ttl",
    },
}


async def section_indexes(db) -> Tuple[str, List[Concern]]:
    concerns: List[Concern] = []
    md: List[str] = ["## 10. Indexes"]

    collections_to_audit = [
        "projects", "companies", "users",
        "dob_logs", "notification_log",
        "notification_preferences", "digest_queue",
        "permit_renewals", "renewal_alert_sent",
    ]

    for coll_name in collections_to_audit:
        md.append(f"\n### `{coll_name}`")
        try:
            info = await db[coll_name].index_information()
        except Exception as e:
            md.append(f"- (could not enumerate indexes: {e!r})")
            continue
        rows = []
        for name, spec in info.items():
            keys = spec.get("key", [])
            keys_str = ", ".join(f"{k}:{v}" for k, v in keys)
            unique = spec.get("unique", False)
            ttl = spec.get("expireAfterSeconds")
            partial = "yes" if spec.get("partialFilterExpression") else ""
            rows.append([
                name,
                keys_str,
                "yes" if unique else "",
                str(ttl) if ttl is not None else "",
                partial,
            ])
        md.append(md_table(
            ["index name", "keys", "unique", "TTL (sec)", "partial filter"],
            rows,
        ))

        # Missing-index check.
        expected = EXPECTED_INDEXES.get(coll_name, set())
        missing = expected - set(info.keys())
        if missing:
            md.append(f"\n⚠️  **Missing expected indexes:** {sorted(missing)}")
            concerns.append(Concern(
                severity=SEVERITY_WARNING,
                section="10. Indexes",
                summary=(
                    f"Missing index(es) on {coll_name}: {sorted(missing)}"
                ),
                detail=(
                    "Expected indexes are created at startup via "
                    "_ensure_index_resilient. Missing indexes suggest "
                    "the startup pass hit an error or a deploy lag."
                ),
                fix_path=(
                    "Restart the backend to re-run the startup index "
                    "pass; check logs for OperationFailure on "
                    "create_index."
                ),
            ))

    return "\n".join(md), concerns


# ── Section 11 — Atlas resource state (manual) ────────────────────


def section_atlas_manual() -> str:
    return """## 11. Atlas resource state (MANUALLY FILL IN FROM ATLAS DASHBOARD)

The audit script cannot query Atlas resource state from a Mongo
connection alone. The operator must look up the following from the
Atlas dashboard (Atlas → Cluster → Metrics) and paste the values
inline:

- [ ] **Plan tier**: e.g. M10, M20, Serverless. Value: `____`
- [ ] **Storage usage**: GB used vs plan limit. Value: `___ / ___ GB (___%)`
- [ ] **Connection count**: current active connections. Value: `____`
- [ ] **Connection limit**: from plan. Value: `____`
- [ ] **Replica state**: PRIMARY healthy / SECONDARY healthy / any in
      RECOVERING or DOWN? Value: `____`
- [ ] **Backup status**: continuous-backup enabled? Last snapshot
      timestamp? Value: `____`
- [ ] **Region**: current cluster region. Value: `____`

If any of the above shows a concerning value, surface as a CONCERN
in the executive summary at the top of this report (manually).
"""


# ── Executive summary builder ─────────────────────────────────────


def build_executive_summary(
    concerns: List[Concern], started_at: datetime, finished_at: datetime,
) -> str:
    blockers = [c for c in concerns if c.severity == SEVERITY_BLOCKER]
    warnings = [c for c in concerns if c.severity == SEVERITY_WARNING]
    infos = [c for c in concerns if c.severity == SEVERITY_INFO]

    md: List[str] = []
    md.append(f"# Production Data Audit — {finished_at.strftime('%Y-%m-%d %H:%M UTC')}")
    md.append("")
    md.append(
        f"_Generated by `backend/scripts/audit_production.py` in "
        f"{(finished_at - started_at).total_seconds():.1f}s. Read-only._"
    )
    md.append("")
    md.append("## Executive Summary")
    md.append("")
    md.append("| Severity | Count |")
    md.append("|---|---|")
    md.append(f"| BLOCKER | {len(blockers)} |")
    md.append(f"| WARNING | {len(warnings)} |")
    md.append(f"| INFO | {len(infos)} |")
    md.append("")
    if blockers:
        md.append("### Blockers (must resolve before B3 ships)")
        for c in blockers:
            md.append(c.to_markdown_row())
    if warnings:
        md.append("### Warnings")
        for c in warnings:
            md.append(c.to_markdown_row())
    if infos:
        md.append("### Info")
        for c in infos:
            md.append(c.to_markdown_row())
    if not concerns:
        md.append("✅ **No concerns surfaced.** The audit ran clean.")
    return "\n".join(md)


# ── main ──────────────────────────────────────────────────────────


SECTION_RUNNERS = [
    ("Projects", section_projects),
    ("Companies", section_companies),
    ("Users", section_users),
    ("dob_logs", section_dob_logs),
    ("notification_log", section_notification_log),
    ("permit_renewals", section_permit_renewals),
    ("filing_reps canary", section_filing_reps_canary),
    ("notification_preferences", section_notification_preferences),
    ("digest_queue", section_digest_queue),
    ("Indexes", section_indexes),
]


async def run_audit(mongo_url: str, db_name: str) -> int:
    if AsyncIOMotorClient is None:
        print("ERROR: motor package not available.", file=sys.stderr)
        return 2
    started_at = datetime.now(timezone.utc)
    print(f"# (audit running — {started_at.isoformat()})", file=sys.stderr)

    client = AsyncIOMotorClient(mongo_url)
    raw_db = client[db_name]
    db = ReadOnlyDatabase(raw_db)

    sections_md: List[str] = []
    all_concerns: List[Concern] = []

    for title, fn in SECTION_RUNNERS:
        print(f"  → running {title}…", file=sys.stderr)
        try:
            section_md, section_concerns = await fn(db)
        except CanaryFailed as e:
            # Section 7 canary aborts the entire audit. Print the failure
            # to stderr; print a partial markdown to stdout so the
            # operator has something to capture.
            print(f"\n⛔️  CANARY FAILED: {e}", file=sys.stderr)
            print(
                "BLOCKER: Section 7 canary failed — filing_reps.credentials "
                "field present.\n\n"
                f"{e}\n\n"
                "The audit aborted before completing. Run the migration "
                "and re-run this script.\n",
            )
            return 1
        sections_md.append(section_md)
        all_concerns.extend(section_concerns)

    finished_at = datetime.now(timezone.utc)

    # Assemble final markdown: summary at top + Atlas manual section + each section body.
    print(build_executive_summary(all_concerns, started_at, finished_at))
    print()
    print(section_atlas_manual())
    print()
    for md in sections_md:
        print(md)
        print()

    return 0


def _main_entry() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only production data audit (Phase B2).",
    )
    parser.add_argument(
        "--db-name", default=None,
        help="Database name. Defaults to env var DB_NAME.",
    )
    args = parser.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = args.db_name or os.environ.get("DB_NAME")
    if not mongo_url:
        print(
            "ERROR: MONGO_URL environment variable required.\n"
            "Recommended: use a READ-ONLY Atlas connection string.\n"
            "Example:\n"
            "  MONGO_URL='mongodb+srv://readonly:...' DB_NAME='blueview' "
            "python -m backend.scripts.audit_production",
            file=sys.stderr,
        )
        return 2
    if not db_name:
        print(
            "ERROR: DB_NAME environment variable (or --db-name) required.",
            file=sys.stderr,
        )
        return 2

    try:
        return asyncio.run(run_audit(mongo_url, db_name))
    except KeyboardInterrupt:
        print("\n(audit interrupted)", file=sys.stderr)
        return 130
    except Exception:
        print(
            "\nERROR: audit failed with unhandled exception:\n",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main_entry())
