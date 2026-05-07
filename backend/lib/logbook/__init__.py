"""Phase V2.0 — Compliance logbook system.

A v2-only feature that builds on the existing daily-log + workers
+ DOB-signal infrastructure to produce a single audit surface
for compliance reviewers (DOB inspectors, internal compliance
staff, the operator's lawyer when something goes sideways).

  • missing_detector.py  — fills logbook_entries with status=missing
                            for expected-but-absent daily-log days.
  • ll196.py             — generates monthly LL196 SST-card
                            attestation PDFs, uploads to R2,
                            records logbook_entry.
  • deficiency.py        — rules engine that flags daily logs
                            with missing fields / unmet
                            requirements.
  • schema.py            — canonical category / status / source
                            constants + indexes spec used at
                            startup.

Every consumer surface (endpoints, scheduler tick, FE) is gated by
the `v2_logbook` feature flag (E1 infra). Flag default OFF; v1
customers see nothing.
"""

from lib.logbook.schema import (  # noqa: F401
    CATEGORY_DAILY_LOG,
    CATEGORY_LL196,
    CATEGORY_INSPECTION,
    CATEGORY_DEFICIENCY,
    CATEGORY_MANPOWER,
    CATEGORY_MATERIAL_DELIVERY,
    VALID_CATEGORIES,
    STATUS_COMPLETE,
    STATUS_MISSING,
    STATUS_DEFICIENT,
    VALID_STATUSES,
    SOURCE_WHATSAPP,
    SOURCE_MANUAL,
    SOURCE_AUTO_DETECTED,
    VALID_SOURCES,
    LOGBOOK_ENTRIES_INDEXES,
    iter_expected_dates,
    is_expected_workday,
)
