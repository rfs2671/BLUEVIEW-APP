"""What counts as a project a background scan may touch.

ONE DEFINITION, because the second one was wrong on live data. The compliance
detectors iterated

    {"status": "active", "is_deleted": {"$ne": True}}

which is not this filter and does not mean what it reads as. `projects.status`
is set to "active" by ProjectCreate's default and by every creation site, and
NOTHING in the product ever changes it — so that clause matches every project
that has ever existed while appearing to exclude something. What it actually
omitted was `marked_for_deletion`, and on 2026-08-28 the detector was still
writing compliance flags nightly for 587 Prescott Place, a project an admin had
already marked for deletion: 14 rows through the previous day, on a project the
rest of the product treats as invisible and inert.

The comment on the original definition in server.py already said this in as
many words — "must not be picked up by any background scan" — and a background
scan was picking it up, because it had its own filter.

`status` is deliberately NOT part of this. A field written once at creation and
never updated is not state; keeping it in a filter suggests a lifecycle that
does not exist, and the next person writing a scan copies the pair.
"""

from __future__ import annotations

from typing import Any, Dict

# A project that has been marked for deletion by an admin is invisible and
# inert everywhere except the owner's pending-deletion review list: it must not
# appear in listings, must not be readable by id, and must not be picked up by
# any background scan (DOB sync, report mailer, prediction sweeps, the
# compliance detectors). Spread this into a projects query.
ACTIVE_PROJECT_FILTER: Dict[str, Any] = {
    "is_deleted": {"$ne": True},
    "marked_for_deletion": {"$ne": True},
}


# ── FIXTURE TENANTS ─────────────────────────────────────────────────────────
#
# A company carrying `is_test` is fixture data. It lives here for the reason
# ACTIVE_PROJECT_FILTER does: the statistical engine builds its panels in
# lib/statistical_engine/ with its own `db` handle, and a definition that lived
# only in server.py would have to be copied there — which is exactly how the
# compliance detectors ended up with a filter of their own that was wrong.
#
# THE STATE THIS ENDS. A company literally named "test" holds two live projects
# and four approved accounts, and nothing in the code told it apart from a real
# general contractor. daily_panel.py and live_mutation.py both read
# `db.projects.find({})` — every project, every tenant, deleted or not — and
# feed the cross-project peer statistics that real projects are scored against.
#
# IT IS NOT A VISIBILITY RULE. A test account still sees its own projects and
# files its own logs. What this governs is the machinery that acts with NOBODY
# ASKING: alerting, emailing, and any statistic computed across tenants.

FIXTURE_COMPANY_QUERY: Dict[str, Any] = {"is_test": True}


async def fixture_company_ids(db) -> set:
    """Every company id marked `is_test`. Empty set on any failure.

    FAILS OPEN, DELIBERATELY. If this read breaks, the caller runs over
    everything exactly as it did before the flag existed. A missed exclusion is
    one wrong alert; a raise here would stop the nightly compliance check for
    every real project on the platform.
    """
    try:
        rows = await db.companies.find(
            dict(FIXTURE_COMPANY_QUERY), {"_id": 1}).to_list(200)
        return {str(r["_id"]) for r in rows}
    except Exception:
        return set()


def drop_fixture_rows(rows, ids, key: str = "company_id") -> list:
    """The rows a sweep should act on, given the fixture company ids.

    `key` is "company_id" for projects and "_id" for company rows themselves —
    one function rather than two, because the second one is where a copy would
    drift.
    """
    if not ids:
        return list(rows or [])
    return [r for r in (rows or []) if str((r or {}).get(key) or "") not in ids]
