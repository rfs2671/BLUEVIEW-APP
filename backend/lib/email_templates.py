"""MR.9 — Email templates for the renewal notification system.

Five trigger types ship in this module, each as a pure function that
returns {subject, html, text} given a context dict. Templates are
operator-friendly (plain language, no MR.X jargon) and follow the
visual conventions of the existing inline templates in
permit_renewal._send_health_check_alert and server._send_renewal_alert
(card-style HTML, gray-on-white, brand footer).

Why Python functions, not a templates/emails/ directory of .html files:
  • The existing code keeps email HTML as inline f-strings — no Jinja2,
    no template loader, no separate file format. Honoring that
    convention keeps the diff minimal and dodges a dependency add.
  • Pure functions are trivial to unit-test without a renderer or
    fixture filesystem.
  • The 5 templates share enough structure (header, body, action
    button, footer) to factor out a shared `_card(...)` helper. A
    Jinja directory would make that factoring awkward.

Each template takes a context dict with these standard keys:
  recipient_name        — string, "Hi <name>," opener
  project_name          — string
  project_address       — string
  permit_job_number     — string (e.g. "B00736930")
  permit_work_type      — string (e.g. "Plumbing")
  current_expiration    — string (formatted date, e.g. "Jun 15, 2026")
  action_link           — full URL to the renewal-detail page

Trigger-specific keys layered on top:
  T-30 / T-14 / T-7  — days_until_expiry: int
  stuck              — days_stuck: int
  completed          — new_expiration: string
"""

from __future__ import annotations

from typing import Any, Dict, Tuple


# ── Shared rendering ────────────────────────────────────────────────

_FONT_STACK = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,"
    "Ubuntu,Cantarell,sans-serif"
)


def _card(
    *,
    header_color: str,
    header_emoji: str,
    header_title: str,
    header_subtitle: str,
    body_html: str,
    action_label: str,
    action_url: str,
) -> str:
    """Shared HTML wrapper. All templates produce a card with a
    colored header, body content, primary action button, and the
    LeveLog footer. Renders well in Gmail/Outlook/iOS Mail (tested
    visually against the existing _send_health_check_alert template
    which uses the same shell)."""
    return f"""
<div style="font-family:{_FONT_STACK};max-width:600px;margin:0 auto;">
  <div style="background:{header_color};color:white;padding:20px 24px;border-radius:8px 8px 0 0;">
    <h1 style="margin:0;font-size:18px;">{header_emoji} {header_title}</h1>
    <p style="margin:4px 0 0;opacity:0.9;font-size:14px;">{header_subtitle}</p>
  </div>
  <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
    {body_html}
    <div style="text-align:center;margin-top:24px;">
      <a href="{action_url}"
         style="display:inline-block;background:#3b82f6;color:#fff;
                padding:12px 24px;border-radius:6px;text-decoration:none;
                font-size:14px;font-weight:600;">
        {action_label}
      </a>
    </div>
  </div>
  <p style="text-align:center;font-size:10px;color:#cbd5e1;margin-top:16px;letter-spacing:2px;">
    LEVELOG COMPLIANCE
  </p>
</div>
""".strip()


def _detail_row(label: str, value: str) -> str:
    return (
        f'<div style="display:flex;justify-content:space-between;'
        f'padding:8px 0;border-bottom:1px solid #f3f4f6;">'
        f'<span style="font-size:12px;color:#6b7280;">{label}</span>'
        f'<span style="font-size:13px;color:#111827;font-weight:500;">{value}</span>'
        f'</div>'
    )


def _common_details_block(ctx: Dict[str, Any]) -> str:
    """Shared "permit details" block — same across all 5 templates."""
    return (
        '<div style="background:#f9fafb;border-radius:6px;padding:16px;margin:16px 0;">'
        + _detail_row("Project", ctx.get("project_name") or "—")
        + _detail_row("Address", ctx.get("project_address") or "—")
        + _detail_row("Job Number", ctx.get("permit_job_number") or "—")
        + _detail_row("Work Type", ctx.get("permit_work_type") or "—")
        + _detail_row("Current Expiration", ctx.get("current_expiration") or "—")
        + '</div>'
    )


def _greeting(ctx: Dict[str, Any]) -> str:
    name = (ctx.get("recipient_name") or "").strip()
    return f"<p style=\"margin:0 0 16px;font-size:14px;color:#374151;\">Hi {name or 'there'},</p>"


# ── Trigger templates ──────────────────────────────────────────────
#
# Each function returns (subject, html, text). The text fallback is
# rendered for clients that don't support HTML; both are sent in the
# same Resend send call so the email client picks based on capabilities.

def render_t_minus_30(ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    project = ctx.get("project_name") or "—"
    job = ctx.get("permit_job_number") or "—"
    days = ctx.get("days_until_expiry", 30)
    subject = f"Renewal due in {days} days: {project} — {job}"
    body = (
        _greeting(ctx)
        + f'<p style="margin:0 0 16px;font-size:14px;color:#374151;line-height:1.5;">'
          f'A permit on <b>{project}</b> is due for renewal in <b>{days} days</b>. '
          f'No action is required yet — this is an early-warning notice so you '
          f'have time to plan the filing window.'
          f'</p>'
        + _common_details_block(ctx)
        + '<p style="margin:0;font-size:13px;color:#6b7280;line-height:1.5;">'
          'Click below to review the permit and start the renewal when ready.'
          '</p>'
    )
    html = _card(
        header_color="#3b82f6",
        header_emoji="📅",
        header_title="Renewal Due in 30 Days",
        header_subtitle="Early-warning notice",
        body_html=body,
        action_label="Review Permit",
        action_url=ctx.get("action_link") or "#",
    )
    text = (
        f"Hi {ctx.get('recipient_name') or 'there'},\n\n"
        f"A permit on {project} is due for renewal in {days} days.\n\n"
        f"Project: {project}\n"
        f"Address: {ctx.get('project_address') or '—'}\n"
        f"Job Number: {job}\n"
        f"Work Type: {ctx.get('permit_work_type') or '—'}\n"
        f"Current Expiration: {ctx.get('current_expiration') or '—'}\n\n"
        f"Review the permit: {ctx.get('action_link') or '(no link)'}\n\n"
        f"— LeveLog Compliance"
    )
    return subject, html, text


def render_t_minus_14(ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    project = ctx.get("project_name") or "—"
    job = ctx.get("permit_job_number") or "—"
    days = ctx.get("days_until_expiry", 14)
    subject = f"Renewal due in {days} days: {project} — {job}"
    body = (
        _greeting(ctx)
        + f'<p style="margin:0 0 16px;font-size:14px;color:#374151;line-height:1.5;">'
          f'A permit on <b>{project}</b> expires in <b>{days} days</b>. '
          f'If you have not started the renewal, now is a good time. '
          f'DOB processing typically takes 5–10 business days, so filing '
          f'today still gives a comfortable buffer.'
          f'</p>'
        + _common_details_block(ctx)
        + '<p style="margin:0;font-size:13px;color:#6b7280;line-height:1.5;">'
          'Click below to file the renewal through LeveLog — '
          'the agent will submit on DOB NOW under the licensee\'s credentials.'
          '</p>'
    )
    html = _card(
        header_color="#f59e0b",
        header_emoji="⚠️",
        header_title="Renewal Due in 14 Days",
        header_subtitle="Time to file",
        body_html=body,
        action_label="File Renewal",
        action_url=ctx.get("action_link") or "#",
    )
    text = (
        f"Hi {ctx.get('recipient_name') or 'there'},\n\n"
        f"A permit on {project} expires in {days} days. "
        f"DOB processing typically takes 5-10 business days, so filing "
        f"today still gives a comfortable buffer.\n\n"
        f"Project: {project}\n"
        f"Address: {ctx.get('project_address') or '—'}\n"
        f"Job Number: {job}\n"
        f"Work Type: {ctx.get('permit_work_type') or '—'}\n"
        f"Current Expiration: {ctx.get('current_expiration') or '—'}\n\n"
        f"File the renewal: {ctx.get('action_link') or '(no link)'}\n\n"
        f"— LeveLog Compliance"
    )
    return subject, html, text


def render_t_minus_7(ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    project = ctx.get("project_name") or "—"
    job = ctx.get("permit_job_number") or "—"
    days = ctx.get("days_until_expiry", 7)
    subject = f"URGENT: Renewal due in {days} days: {project} — {job}"
    body = (
        _greeting(ctx)
        + f'<div style="background:#fef2f2;border:1px solid #fecaca;'
          f'border-radius:6px;padding:12px 16px;margin-bottom:16px;">'
          f'<p style="margin:0;font-size:14px;color:#991b1b;font-weight:600;">'
          f'⚠️ This permit expires in {days} days.'
          f'</p>'
          f'<p style="margin:6px 0 0;font-size:13px;color:#7f1d1d;line-height:1.5;">'
          f'If the permit lapses before renewal, the project may incur '
          f'stop-work or fee penalties. File now to leave time for DOB '
          f'processing.'
          f'</p>'
          f'</div>'
        + _common_details_block(ctx)
        + '<p style="margin:0;font-size:13px;color:#374151;line-height:1.5;">'
          '<b>File today.</b> The LeveLog agent submits within minutes; '
          'DOB processing follows.'
          '</p>'
    )
    html = _card(
        header_color="#dc2626",
        header_emoji="🚨",
        header_title=f"URGENT: {days}-Day Renewal Window",
        header_subtitle="File today to avoid lapse",
        body_html=body,
        action_label="File Renewal Now",
        action_url=ctx.get("action_link") or "#",
    )
    text = (
        f"URGENT — {days}-day renewal window\n\n"
        f"Hi {ctx.get('recipient_name') or 'there'},\n\n"
        f"This permit expires in {days} days. If it lapses before renewal, "
        f"the project may incur stop-work or fee penalties.\n\n"
        f"Project: {project}\n"
        f"Address: {ctx.get('project_address') or '—'}\n"
        f"Job Number: {job}\n"
        f"Work Type: {ctx.get('permit_work_type') or '—'}\n"
        f"Current Expiration: {ctx.get('current_expiration') or '—'}\n\n"
        f"File now: {ctx.get('action_link') or '(no link)'}\n\n"
        f"— LeveLog Compliance"
    )
    return subject, html, text


def render_stuck(ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    project = ctx.get("project_name") or "—"
    job = ctx.get("permit_job_number") or "—"
    days_stuck = ctx.get("days_stuck", 14)
    subject = f"Filing stuck at DOB (>{days_stuck} days): {project} — {job}"
    body = (
        _greeting(ctx)
        + f'<p style="margin:0 0 16px;font-size:14px;color:#374151;line-height:1.5;">'
          f'A renewal you filed for <b>{project}</b> has been waiting on DOB for '
          f'<b>{days_stuck} days</b> — longer than the typical 5–10 business '
          f'day processing window. The LeveLog agent has done its part; this '
          f'delay is on DOB\'s side.'
          f'</p>'
        + _common_details_block(ctx)
        + '<p style="margin:0;font-size:13px;color:#6b7280;line-height:1.5;">'
          'Recommended action: log into DOB NOW directly and check the filing '
          'status. If DOB is requesting additional information, respond '
          'through their portal.'
          '</p>'
    )
    html = _card(
        header_color="#f59e0b",
        header_emoji="⏳",
        header_title="Filing Stuck at DOB",
        header_subtitle=f"{days_stuck} days awaiting approval",
        body_html=body,
        action_label="Open Filing Status",
        action_url=ctx.get("action_link") or "#",
    )
    text = (
        f"Hi {ctx.get('recipient_name') or 'there'},\n\n"
        f"A renewal you filed for {project} has been waiting on DOB for "
        f"{days_stuck} days — longer than the typical 5-10 business day "
        f"processing window.\n\n"
        f"Project: {project}\n"
        f"Address: {ctx.get('project_address') or '—'}\n"
        f"Job Number: {job}\n\n"
        f"Recommended action: log into DOB NOW directly and check the filing "
        f"status.\n\n"
        f"Open filing status: {ctx.get('action_link') or '(no link)'}\n\n"
        f"— LeveLog Compliance"
    )
    return subject, html, text


def render_completed(ctx: Dict[str, Any]) -> Tuple[str, str, str]:
    project = ctx.get("project_name") or "—"
    job = ctx.get("permit_job_number") or "—"
    new_exp = ctx.get("new_expiration") or "—"
    subject = f"Renewed: {project} — {job} now expires {new_exp}"
    body = (
        _greeting(ctx)
        + f'<div style="background:#ecfdf5;border:1px solid #a7f3d0;'
          f'border-radius:6px;padding:12px 16px;margin-bottom:16px;">'
          f'<p style="margin:0;font-size:14px;color:#065f46;font-weight:600;">'
          f'✅ Renewal confirmed by DOB.'
          f'</p>'
          f'<p style="margin:6px 0 0;font-size:13px;color:#047857;line-height:1.5;">'
          f'New expiration: <b>{new_exp}</b>. No further action required.'
          f'</p>'
          f'</div>'
        + _common_details_block(ctx)
        + f'<p style="margin:0;font-size:13px;color:#6b7280;line-height:1.5;">'
          f'The permit record has been updated automatically. You\'ll get '
          f'another reminder roughly 30 days before the next renewal window.'
          f'</p>'
    )
    html = _card(
        header_color="#10b981",
        header_emoji="✅",
        header_title="Permit Renewed",
        header_subtitle=f"New expiration: {new_exp}",
        body_html=body,
        action_label="View Permit",
        action_url=ctx.get("action_link") or "#",
    )
    text = (
        f"Hi {ctx.get('recipient_name') or 'there'},\n\n"
        f"Renewal confirmed by DOB.\n\n"
        f"Project: {project}\n"
        f"Address: {ctx.get('project_address') or '—'}\n"
        f"Job Number: {job}\n"
        f"New Expiration: {new_exp}\n\n"
        f"No further action required. The permit record has been updated "
        f"automatically.\n\n"
        f"View permit: {ctx.get('action_link') or '(no link)'}\n\n"
        f"— LeveLog Compliance"
    )
    return subject, html, text


# ── Trigger registry ───────────────────────────────────────────────

TRIGGER_RENDERERS = {
    "renewal_t_minus_30":  render_t_minus_30,
    "renewal_t_minus_14":  render_t_minus_14,
    "renewal_t_minus_7":   render_t_minus_7,
    "filing_stuck":        render_stuck,
    "renewal_completed":   render_completed,
}

VALID_TRIGGER_TYPES = frozenset(TRIGGER_RENDERERS.keys())


def render_for_trigger(trigger_type: str, context: Dict[str, Any]) -> Tuple[str, str, str]:
    """Dispatch entry point. Raises KeyError on unknown trigger_type
    so a typo'd caller gets a loud failure rather than silent skip."""
    return TRIGGER_RENDERERS[trigger_type](context)
