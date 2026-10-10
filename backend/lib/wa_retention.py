"""How long WhatsApp messages and attention items are kept. Pure rules: no
database handle. The nightly job that applies them is `_retention_job` in
server.py.

THE RULE (operator decision 2026-10-10; it replaced a 24-month TTL index on
whatsapp_messages.created_at):

  Linked to a project   kept for RETENTION_YEARS (7) after the project's
                        `job_completion_date` -- the same clock, the same
                        function, as the compliance brake in
                        lib/project_retention.py. Every record of the project
                        goes on the same day.
                        No completion date on record: NEVER expires. Absence
                        is not a date (see the dob_logs TTL incident in
                        project_retention.py); nothing here infers one.
                        Clearing the date cancels the expiry: nothing is
                        stored, it is recomputed on every run.
                        A legal hold keeps everything, whatever the date.
  Not linked            (a group never linked, or a project that no longer
                        exists): UNLINKED_DAYS (24 months) after the record's
                        own `created_at`. A record with no date is never
                        expired.

Daily reports are not covered: filed daily_jobsite logbooks are BC 3301.13
statutory records that nothing in this product may destroy.

SAFE ON DEPLOY. The job only COUNTS until RETENTION_PURGE_ENABLED is set: what
would expire, per company and collection, in the log and in the ledger. Even
then it removes at most MAX_DELETES_PER_RUN rows a night, so turning it on
never means a mass delete. Fixture companies (`is_test`) are skipped.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

from lib import project_retention

# The collections the rule covers. attention_items carry their history
# inside the document; chase_shadow rows quote attention items, so they go
# with them.
COLLECTIONS = ("whatsapp_messages", "attention_items", "chase_shadow")
LEDGER = "retention_ledger"

RETENTION_YEARS = project_retention.RETENTION_YEARS
UNLINKED_DAYS = 730          # 24 months: the TTL this replaces
MAX_DELETES_PER_RUN = 5000   # across all collections and companies, per night
BATCH = 500


def purge_enabled() -> bool:
    """Deletes only when RETENTION_PURGE_ENABLED is on; otherwise a dry run."""
    return str(os.environ.get("RETENTION_PURGE_ENABLED", "")).strip().lower() in (
        "1", "true", "yes", "on")


def project_expires_on(project: Dict[str, Any]) -> Optional[date]:
    """The day a linked project's records expire, or None: never (no
    completion on record, or a legal hold)."""
    if not project or project.get("legal_hold"):
        return None
    completed = project_retention.parse_calendar_date(project.get("job_completion_date"))
    if completed is None:
        return None
    return project_retention.add_retention_years(completed)


def project_expired(project: Dict[str, Any], today: str) -> bool:
    """`today`: the New York calendar day, "YYYY-MM-DD". A missing day never
    expires anything."""
    on = project_expires_on(project)
    return bool(on and today and today >= on.isoformat())


def unlinked_cutoff(now: datetime) -> datetime:
    """Records not linked to a project, created before this, have expired."""
    return now - timedelta(days=UNLINKED_DAYS)


def is_unlinked(project_id: Any) -> bool:
    return project_id in (None, "")
