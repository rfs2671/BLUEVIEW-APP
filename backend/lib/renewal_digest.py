"""Daily renewal-digest computation.

Pure-function core: given a set of (project, permit, company) tuples
and today's date, return the list of alerts that crossed a threshold
TODAY. The cron in server.py groups results per company and sends one
email per company per day.

Cadences from spec §4 (locked, post-step-5 amendment):
  insurance:  T-30, T-14, T-7, T-5, T-0 (T-5 = "last call for auto-extension")
  gc_license: T-90, T-60, T-30, T-14
  permit_1yr: T-30, T-14, T-7
  shed_90d:   T-60, T-30, T-14, T-7  (PE/RA progress report required)

Boundary semantics: an alert fires on the day `effective_expiry -
today_days == threshold`. Crossing the threshold the day before
(yesterday) does NOT re-fire today. Crossing AT threshold (today)
fires exactly once. This means:
  - days_left == 14 today → fires
  - days_left == 14 yesterday → fired yesterday, not today
  - days_left == 13 today → does not fire (threshold was 14)

Single-event-per-day semantics. The cron schedules at 7am ET; running
twice on the same day produces an idempotency check via the
`renewal_alert_sent` collection (one row per (company, alert_kind,
expiry_date, threshold)).

Opt-out semantics:
  - Company admins: default opt-IN. They can disable in user settings.
  - Non-admin PMs: default opt-OUT. Admin invites them with a toggle.
  - Mailbox alias: a company can route digests to a shared inbox via
    `companies.renewal_digest_alias_email`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


# ── Cadences ─────────────────────────────────────────────────────────

class AlertKind(str, Enum):
    INSURANCE = "insurance"
    GC_LICENSE = "gc_license"
    PERMIT_1YR = "permit_1yr"
    SHED_90D = "shed_90d"


CADENCES: Dict[AlertKind, List[int]] = {
    AlertKind.INSURANCE:  [30, 14, 7, 5, 0],
    AlertKind.GC_LICENSE: [90, 60, 30, 14],
    AlertKind.PERMIT_1YR: [30, 14, 7],
    AlertKind.SHED_90D:   [60, 30, 14, 7],
}


# ── Result shapes ────────────────────────────────────────────────────

@dataclass
class RenewalAlert:
    """One row in a company's daily digest. The cron groups by
    company_id, sorts by urgency, formats the email."""
    company_id: str
    company_name: str
    kind: AlertKind
    threshold_days: int             # 30/14/7/5/0/etc.
    expiry_date: str                # ISO string for stable idempotency keys
    expiry_label: str               # human "GC License" / "Workers' Comp" / etc.
    permit_id: Optional[str] = None
    permit_job_number: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def idempotency_key(self) -> Dict[str, Any]:
        """One alert per (company, kind, expiry, threshold) per day.
        Sending again same-day is a no-op; sending tomorrow with a
        different threshold (T-7 after yesterday's T-14) is a new row."""
        return {
            "company_id": self.company_id,
            "kind": self.kind.value,
            "expiry_date": self.expiry_date,
            "threshold_days": self.threshold_days,
            "permit_id": self.permit_id,
        }


# ── Threshold logic ──────────────────────────────────────────────────

def _days_between(today: datetime, target: datetime) -> int:
    """Calendar-day difference, rounded by floor. UTC-aware on both
    sides; caller normalizes."""
    return (target.date() - today.date()).days


def _utc(dt) -> Optional[datetime]:
    """Coerce strings or naive datetimes to UTC-aware. None passes through.
    Mirrors the same helper in eligibility_v2 — kept local to avoid a
    cross-module import cycle."""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            from dateutil import parser as dp
            parsed = dp.parse(dt)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except Exception:
            return None
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return None


def _crossed_threshold_today(
    days_left: int,
    cadence: List[int],
) -> Optional[int]:
    """Returns the threshold value if today's days_left equals one of
    the cadence values, else None. Exact-equality semantics: T-14 fires
    only on the day days_left == 14, not 13 or 15. Avoids re-firing
    over a multi-day window."""
    if days_left in cadence:
        return days_left
    return None


# ── Per-company alert computation ────────────────────────────────────

def compute_company_alerts(
    *,
    company: dict,
    permits: List[dict],
    today: datetime,
) -> List[RenewalAlert]:
    """Given a company doc, its permits (with denormalized project info),
    and today's date, return all alerts that fire today.

    `permits` items must have at minimum:
      _id, project_id, project_name, job_number, issuance_date,
      permit_class, filing_system

    The function reads insurance + license dates straight off `company`
    and computes per-permit annual/shed dates inline. It does NOT call
    the eligibility evaluator — alerts are independent of the
    renewal-strategy resolution because the digest is informational,
    not a hard gate.
    """
    alerts: List[RenewalAlert] = []
    company_id = str(company.get("_id"))
    company_name = company.get("name") or "Your company"

    # ── Insurance alerts ──
    for ins_type, label in [
        ("general_liability", "General Liability"),
        ("workers_comp",      "Workers' Comp"),
        ("disability",        "Disability"),
    ]:
        rec = _find_insurance(company, ins_type)
        if not rec:
            continue
        exp = _utc(rec.get("expiration_date"))
        if not exp:
            continue
        days_left = _days_between(today, exp)
        threshold = _crossed_threshold_today(days_left, CADENCES[AlertKind.INSURANCE])
        if threshold is None:
            continue
        alerts.append(RenewalAlert(
            company_id=company_id,
            company_name=company_name,
            kind=AlertKind.INSURANCE,
            threshold_days=threshold,
            expiry_date=exp.date().isoformat(),
            expiry_label=label,
            extra={"insurance_type": ins_type},
        ))

    # ── GC License alert ──
    license_exp = _utc(company.get("gc_license_expiration"))
    if license_exp:
        days_left = _days_between(today, license_exp)
        threshold = _crossed_threshold_today(days_left, CADENCES[AlertKind.GC_LICENSE])
        if threshold is not None:
            alerts.append(RenewalAlert(
                company_id=company_id,
                company_name=company_name,
                kind=AlertKind.GC_LICENSE,
                threshold_days=threshold,
                expiry_date=license_exp.date().isoformat(),
                expiry_label="GC License",
            ))

    # ── Permit-side alerts (1yr ceiling, shed 90d) ──
    for permit in permits:
        # Skip permits where issuance_date is missing — eligibility
        # already flags those via blocking_reasons.
        issuance = _utc(permit.get("issuance_date"))
        if not issuance:
            continue

        permit_class = (permit.get("permit_class") or "standard").lower()

        if permit_class == "sidewalk_shed":
            shed_expiry = issuance + timedelta(days=90)
            days_left = _days_between(today, shed_expiry)
            threshold = _crossed_threshold_today(days_left, CADENCES[AlertKind.SHED_90D])
            if threshold is not None:
                alerts.append(RenewalAlert(
                    company_id=company_id,
                    company_name=company_name,
                    kind=AlertKind.SHED_90D,
                    threshold_days=threshold,
                    expiry_date=shed_expiry.date().isoformat(),
                    expiry_label="Sidewalk shed (90-day cap)",
                    permit_id=str(permit.get("_id")),
                    permit_job_number=permit.get("job_number"),
                    project_id=permit.get("project_id"),
                    project_name=permit.get("project_name"),
                ))
            continue

        # Standard permit — 1-year-since-issuance ceiling.
        ceiling = issuance + timedelta(days=365)
        days_left = _days_between(today, ceiling)
        threshold = _crossed_threshold_today(days_left, CADENCES[AlertKind.PERMIT_1YR])
        if threshold is not None:
            alerts.append(RenewalAlert(
                company_id=company_id,
                company_name=company_name,
                kind=AlertKind.PERMIT_1YR,
                threshold_days=threshold,
                expiry_date=ceiling.date().isoformat(),
                expiry_label="Permit 1-year ceiling",
                permit_id=str(permit.get("_id")),
                permit_job_number=permit.get("job_number"),
                project_id=permit.get("project_id"),
                project_name=permit.get("project_name"),
            ))

    return alerts


def _find_insurance(company: dict, ins_type: str) -> Optional[dict]:
    for r in company.get("gc_insurance_records") or []:
        if isinstance(r, dict) and r.get("insurance_type") == ins_type:
            return r
    return None


# ── Email body composition ──────────────────────────────────────────

# Subject template per priority (T-0 today is most urgent).
def digest_subject(alerts: List[RenewalAlert], company_name: str) -> str:
    if not alerts:
        return f"LeveLog renewal digest — {company_name}"
    most_urgent = min(alerts, key=lambda a: a.threshold_days)
    if most_urgent.threshold_days == 0:
        return f"⚠ {company_name}: action expired TODAY"
    if most_urgent.threshold_days <= 7:
        return f"⚠ {company_name}: renewal action in {most_urgent.threshold_days} days"
    return f"LeveLog renewal digest — {company_name} ({len(alerts)} item{'s' if len(alerts) != 1 else ''})"


def digest_html(alerts: List[RenewalAlert], company_name: str) -> str:
    """Single-column HTML digest. Sectioned by alert kind."""
    if not alerts:
        return ""

    by_kind: Dict[AlertKind, List[RenewalAlert]] = {}
    for a in alerts:
        by_kind.setdefault(a.kind, []).append(a)

    sections = []
    section_titles = {
        AlertKind.INSURANCE:  "📋 Insurance",
        AlertKind.GC_LICENSE: "🪪 GC License",
        AlertKind.PERMIT_1YR: "🏗️ Permit 1-year ceiling",
        AlertKind.SHED_90D:   "🛠️ Sidewalk Shed (LL48)",
    }

    for kind in [AlertKind.INSURANCE, AlertKind.GC_LICENSE,
                 AlertKind.PERMIT_1YR, AlertKind.SHED_90D]:
        rows = by_kind.get(kind) or []
        if not rows:
            continue
        rows.sort(key=lambda a: a.threshold_days)
        items_html = "\n".join(_alert_row_html(a) for a in rows)
        sections.append(
            f"<h3 style='margin:24px 0 8px;font-size:15px;color:#0A1929'>"
            f"{section_titles[kind]}</h3>\n"
            f"<ul style='padding-left:18px;margin:0'>{items_html}</ul>"
        )

    return (
        "<div style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;"
        "max-width:600px;color:#0A1929;line-height:1.5'>"
        f"<h2 style='margin:0 0 8px'>Daily renewal digest — {company_name}</h2>"
        "<p style='color:#666;margin:0 0 16px;font-size:14px'>"
        f"{len(alerts)} action{'s' if len(alerts) != 1 else ''} crossing threshold today. "
        "Update insurance/license at DOB NOW (use the licensee's NYC.ID) "
        "and the affected permits will auto-extend end-of-day.</p>"
        + "\n".join(sections)
        + "</div>"
    )


def _alert_row_html(a: RenewalAlert) -> str:
    days_phrase = (
        "EXPIRED TODAY" if a.threshold_days == 0
        else f"expires in {a.threshold_days} day{'s' if a.threshold_days != 1 else ''}"
    )
    color = "#dc2626" if a.threshold_days <= 7 else "#d97706" if a.threshold_days <= 14 else "#0A1929"
    permit_clause = ""
    if a.permit_job_number:
        permit_clause = f" — Job <code>{a.permit_job_number}</code>"
        if a.project_name:
            permit_clause += f" at {a.project_name}"
    return (
        f"<li style='margin:6px 0'>"
        f"<strong style='color:{color}'>{a.expiry_label}</strong>: "
        f"<span style='color:{color}'>{days_phrase}</span> ({a.expiry_date})"
        f"{permit_clause}</li>"
    )
