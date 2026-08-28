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
