"""THE DEMO DATA PROVIDER — invented records, and the functions that shape them
into each screen's response.

EVERYTHING BEHIND THIS PACKAGE IS FICTION, AND IT MUST NEVER REACH A NON-DEMO
PRINCIPAL. Sign-up is demo-only: a demo account is shown the real admin screens
of the app rendered from these canned payloads, nothing it does is saved, and
it must never see a row belonging to a real tenant. This package holds the
fiction and the shaping; it holds NO authorization. The `is_demo(user)` test
goes at the route, before the call, and it fails closed.

Two modules:

    dataset.py   the closed set — the project, the crew, the logbook plan, the
                 day at the gate, the DOB record, the plans list. Every date is
                 an offset; every id, company, phone and address is visibly
                 invented. Read its header before adding a record.
    shaping.py   one pure function per screen, each returning what the REAL
                 handler returns, derived from that handler. `today` is an
                 argument, never a clock.

No database, no network, no time-of-day, and a test asserts all three over the
modules' own syntax trees rather than over their prose.
"""

from .dataset import (
    DEMO_ANCHOR,
    DEMO_CLOSED_DAY_OFFSETS,
    DEMO_COMPANY_ID,
    DEMO_COMPANY_NAME,
    DEMO_OPEN_DAY_OFFSET,
    DEMO_PROJECT_ID,
    DEMO_REQUIRED_LOGBOOKS,
)
from .shaping import (
    demo_checkins,
    demo_dob_logs,
    demo_dob_summary,
    demo_files,
    demo_logbook_by_id,
    demo_logbooks,
    demo_project,
    demo_project_checkins,
    demo_project_list,
    demo_required_logbooks,
    demo_worker,
    demo_worker_certifications,
    demo_workers,
)

__all__ = [
    "DEMO_ANCHOR",
    "DEMO_CLOSED_DAY_OFFSETS",
    "DEMO_COMPANY_ID",
    "DEMO_COMPANY_NAME",
    "DEMO_OPEN_DAY_OFFSET",
    "DEMO_PROJECT_ID",
    "DEMO_REQUIRED_LOGBOOKS",
    "demo_checkins",
    "demo_dob_logs",
    "demo_dob_summary",
    "demo_files",
    "demo_logbook_by_id",
    "demo_logbooks",
    "demo_project",
    "demo_project_checkins",
    "demo_project_list",
    "demo_required_logbooks",
    "demo_worker",
    "demo_worker_certifications",
    "demo_workers",
]
