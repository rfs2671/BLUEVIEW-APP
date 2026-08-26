"""Phase V2.0 — LL196 (NYC Local Law 196 / SST card) attestation.

NYC LL196 requires GCs to maintain proof that every worker on
their job site holds a current Site Safety Training (SST) card.
LeveLog already tracks worker certifications (server.py
`validate_worker_certifications`); this module rolls that data
up into a monthly attestation PDF that's:

  • generated on demand or on the daily 3 AM ET tick (one per
    project per month),
  • uploaded to R2 at a deterministic key
    (`ll196/{company_id}/{project_id}/{year}-{month:02}.pdf`),
  • recorded in logbook_entries with category=ll196_attestation.

The PDF carries:
  • the attestation period (year + month),
  • the project + company,
  • a worker roster with each worker's SST status (current /
    expired / missing / not-required-for-trade),
  • a summary line ("All N workers in good standing" or
    "K workers with deficiencies — see roster"),
  • the operator's name + the generation timestamp.

Pure logic (compliance computation + HTML rendering) is split
from the I/O (R2 upload + Mongo write) so tests can exercise
each layer without external services.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from lib.cert_vocab import SST_CLASS_TYPES
from lib.logbook.schema import (
    CATEGORY_LL196,
    SOURCE_AUTO_DETECTED,
    STATUS_COMPLETE,
    STATUS_DEFICIENT,
)

logger = logging.getLogger(__name__)


# Cert types that count as a current SST card. Mirrors
# server.py::validate_worker_certifications.
# THE COPY IS GONE. This read
#
#     _SST_CERT_TYPES = ("SST_FULL", "SST_LIMITED", "SST_SUPERVISOR")
#
# three members against the canonical four, dropping SST_TEMPORARY. A worker
# holding a temporary card was admitted at the gate as a legible class and
# counted MISSING in the roster below -- a filed DOB attestation contradicting
# the gate about the same man.
_SST_CERT_TYPES = SST_CLASS_TYPES


def _worker_sst_status(
    worker: Dict[str, Any], *, now: Optional[datetime] = None,
) -> Tuple[str, Optional[str]]:
    """Classify one worker's SST standing. Returns
    (status, expiration_iso_or_none) where status is:

      "current"      — has at least one SST cert with a valid
                       (today < expiration) expiration date.
      "no_expiry"    — has an SST cert with NO expiration date
                       on file. We treat as current (operator
                       didn't enter expiration yet) but flag for
                       follow-up via a different rule.
      "expired"      — has SST cert(s) but every one's
                       expiration is in the past.
      "missing"      — no SST cert on file at all.

    Pure function — `now` injectable for tests.
    """
    cur_now = now or datetime.now(timezone.utc)
    certs = worker.get("certifications") or []
    sst_certs = [c for c in certs if (c.get("type") or "") in _SST_CERT_TYPES]
    if not sst_certs:
        return "missing", None

    best_expiry: Optional[datetime] = None
    has_no_expiry = False
    for c in sst_certs:
        exp_raw = c.get("expiration_date") or c.get("expires_at") or ""
        if not exp_raw:
            has_no_expiry = True
            continue
        try:
            # Accept either ISO date or datetime; trim to date.
            if isinstance(exp_raw, datetime):
                exp_dt = exp_raw if exp_raw.tzinfo else exp_raw.replace(tzinfo=timezone.utc)
            else:
                # str — allow with or without 'T' / 'Z'.
                s = str(exp_raw).replace("Z", "+00:00")
                exp_dt = datetime.fromisoformat(s[:19]) if len(s) >= 10 else None
                if exp_dt and exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if exp_dt and (best_expiry is None or exp_dt > best_expiry):
            best_expiry = exp_dt

    if best_expiry is not None and best_expiry > cur_now:
        return "current", best_expiry.strftime("%Y-%m-%d")
    if has_no_expiry:
        return "no_expiry", None
    return "expired", None


def build_attestation_data(
    *, project: Dict[str, Any], workers: List[Dict[str, Any]],
    year: int, month: int,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Pure: roll up worker SST status into the attestation_data
    dict that gets stored on the logbook_entries row.

    Test focus: the counts + roster shape are the contract this
    function promises. PDF rendering (below) consumes this dict
    verbatim, so testing this function locks the data contract."""
    cur_now = now or datetime.now(timezone.utc)
    roster: List[Dict[str, Any]] = []
    counts = {"current": 0, "no_expiry": 0, "expired": 0, "missing": 0}
    for w in workers:
        status, expiry = _worker_sst_status(w, now=cur_now)
        counts[status] = counts.get(status, 0) + 1
        roster.append({
            "name": w.get("name") or w.get("full_name") or "(unnamed)",
            "trade": w.get("trade") or "",
            "sst_status": status,
            "sst_expiration": expiry,
        })
    # Sort: deficiencies first (sorts attention to the top),
    # then by name.
    status_priority = {"missing": 0, "expired": 1, "no_expiry": 2, "current": 3}
    roster.sort(key=lambda r: (
        status_priority.get(r["sst_status"], 9),
        r["name"].lower(),
    ))

    deficient_count = counts["missing"] + counts["expired"]
    overall_status = STATUS_COMPLETE if deficient_count == 0 else STATUS_DEFICIENT
    summary = (
        f"All {len(workers)} workers in good standing"
        if deficient_count == 0
        else f"{deficient_count} of {len(workers)} workers with SST deficiencies"
    )

    return {
        "project_id": str(project.get("_id") or project.get("id") or ""),
        "project_name": project.get("name") or "",
        "company_id": str(project.get("company_id") or ""),
        "year": int(year),
        "month": int(month),
        "period_label": f"{year}-{month:02d}",
        "worker_count": len(workers),
        "counts": counts,
        "deficient_count": deficient_count,
        "overall_status": overall_status,
        "summary": summary,
        "roster": roster,
        "generated_at": cur_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def render_attestation_html(attestation: Dict[str, Any]) -> str:
    """Pure: build the HTML that weasyprint will turn into a PDF.
    Inline styles only (no external CSS); deterministic output so
    tests can assert on key strings.
    """
    def _esc(s: str) -> str:
        # Minimal HTML escape: &, <, > — enough for the project
        # name + summary fields that flow into the title and body.
        # No quotes (not used in attribute context here).
        return (
            (s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
    period = attestation.get("period_label", "")
    project_name = _esc(attestation.get("project_name"))
    summary = _esc(attestation.get("summary"))
    worker_count = attestation.get("worker_count", 0)
    counts = attestation.get("counts", {})
    rows_html = []
    status_color = {
        "current": "#16a34a",
        "no_expiry": "#ca8a04",
        "expired": "#b91c1c",
        "missing": "#b91c1c",
    }
    status_label = {
        "current": "Current",
        "no_expiry": "No expiration on file",
        "expired": "EXPIRED",
        "missing": "MISSING",
    }
    for r in attestation.get("roster", []):
        s = r.get("sst_status", "")
        expiry = r.get("sst_expiration") or "—"
        rows_html.append(
            f"<tr>"
            f"<td>{_esc(r.get('name'))}</td>"
            f"<td>{_esc(r.get('trade'))}</td>"
            f"<td style='color:{status_color.get(s, '#000')};font-weight:600'>"
            f"{status_label.get(s, s)}</td>"
            f"<td>{_esc(expiry)}</td>"
            f"</tr>"
        )
    return f"""<!doctype html>
<html><head><meta charset='utf-8'>
<title>LL196 Attestation — {project_name} — {period}</title>
<style>
  body {{ font-family: 'Helvetica', sans-serif; color: #111; padding: 32px; }}
  h1 {{ font-size: 22px; margin: 0 0 8px 0; }}
  .meta {{ color: #555; font-size: 12px; margin-bottom: 24px; }}
  .summary {{ font-size: 15px; padding: 12px 16px; background: #f3f4f6;
             border-left: 4px solid #2563eb; margin-bottom: 24px; }}
  .counts {{ display: flex; gap: 24px; margin-bottom: 24px; font-size: 13px; }}
  .counts span {{ display: inline-block; padding: 4px 10px; background: #f9fafb;
                  border-radius: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #e5e7eb; }}
  th {{ background: #f9fafb; }}
</style>
</head>
<body>
  <h1>NYC Local Law 196 — Site Safety Training Attestation</h1>
  <div class='meta'>
    Project: <strong>{project_name}</strong> &nbsp;·&nbsp;
    Period: <strong>{period}</strong> &nbsp;·&nbsp;
    Generated: {attestation.get('generated_at', '')}
  </div>
  <div class='summary'>{summary}</div>
  <div class='counts'>
    <span>Current: <strong>{counts.get('current', 0)}</strong></span>
    <span>No expiration on file: <strong>{counts.get('no_expiry', 0)}</strong></span>
    <span>Expired: <strong>{counts.get('expired', 0)}</strong></span>
    <span>Missing: <strong>{counts.get('missing', 0)}</strong></span>
    <span>Total workers: <strong>{worker_count}</strong></span>
  </div>
  <table>
    <thead><tr><th>Name</th><th>Trade</th><th>SST status</th><th>Expiration</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
</body></html>"""


def r2_key_for(attestation: Dict[str, Any]) -> str:
    """Canonical R2 storage key for an attestation. Deterministic
    so re-generating overwrites in place."""
    return (
        f"ll196/{attestation['company_id']}/"
        f"{attestation['project_id']}/{attestation['period_label']}.pdf"
    )


# ──────────────────────────────────────────────────────────────────
# Orchestrator (I/O)
# ──────────────────────────────────────────────────────────────────


async def generate_ll196_attestation(
    db,
    *,
    project_id: str,
    year: int,
    month: int,
    triggered_by_user_id: Optional[str] = None,
    r2_uploader: Optional[Callable[[bytes, str, str], str]] = None,
    pdf_renderer: Optional[Callable[[str], bytes]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Generate, upload, and record one monthly attestation.

    `r2_uploader` and `pdf_renderer` are injection points for
    tests — production passes the real `_upload_to_r2` and a
    weasyprint-backed renderer; tests pass stubs that capture the
    bytes without touching network or weasyprint's native deps.

    Returns the inserted/upserted logbook_entries row payload
    (without the _id, since upsert may not return it).
    """
    cur_now = now or datetime.now(timezone.utc)

    project = await db.projects.find_one({"_id": _to_object_id(project_id)})
    if project is None:
        # Fall back to string id (legacy projects sometimes have
        # str _ids).
        project = await db.projects.find_one({"_id": project_id})
    if project is None:
        raise ValueError(f"project not found: {project_id}")

    workers = await db.workers.find({
        "project_id": project_id,
        "is_deleted": {"$ne": True},
    }).to_list(2000)

    attestation_data = build_attestation_data(
        project=project, workers=workers,
        year=year, month=month, now=cur_now,
    )

    # PDF render (operator can supply stub renderer; default uses
    # weasyprint).
    html = render_attestation_html(attestation_data)
    if pdf_renderer is None:
        pdf_renderer = _default_pdf_renderer
    pdf_bytes = pdf_renderer(html)

    # R2 upload.
    key = r2_key_for(attestation_data)
    r2_url = ""
    try:
        if r2_uploader is None:
            r2_uploader = _default_r2_uploader
        r2_url = r2_uploader(pdf_bytes, key, "application/pdf") or ""
    except Exception as e:
        logger.warning(
            f"[ll196] R2 upload failed for {key}: {e!r}",
        )

    attestation_data["r2_key"] = key
    attestation_data["r2_url"] = r2_url
    attestation_data["pdf_size_bytes"] = len(pdf_bytes)

    # Upsert the logbook_entries row. Dedupe on
    # (project_id, entry_date, category) — same project + same
    # period regenerates in place (R2 overwrite is also in place).
    entry_date = f"{year:04d}-{month:02d}-01"
    entry = {
        "company_id": attestation_data["company_id"],
        "project_id": attestation_data["project_id"],
        "entry_date": entry_date,
        "category": CATEGORY_LL196,
        "status": attestation_data["overall_status"],
        "source": SOURCE_AUTO_DETECTED,
        "linked_dob_log_ids": [],
        "deficiency_reason": (
            attestation_data["summary"]
            if attestation_data["overall_status"] != STATUS_COMPLETE
            else None
        ),
        "attestation_data": attestation_data,
        "updated_at": cur_now,
    }
    await db.logbook_entries.update_one(
        {
            "project_id": attestation_data["project_id"],
            "entry_date": entry_date,
            "category": CATEGORY_LL196,
        },
        {
            "$set": entry,
            "$setOnInsert": {
                "created_at": cur_now,
                "created_by_user_id": triggered_by_user_id,
            },
        },
        upsert=True,
    )
    logger.info(
        f"[ll196] attestation generated project={project_id} "
        f"period={attestation_data['period_label']} "
        f"status={attestation_data['overall_status']} "
        f"r2={key}",
    )
    return entry


# ──────────────────────────────────────────────────────────────────
# Default I/O backends (production)
# ──────────────────────────────────────────────────────────────────


def _default_pdf_renderer(html: str) -> bytes:
    """Production: weasyprint. Imported lazily so tests that pass
    a stub don't need the native deps installed."""
    from weasyprint import HTML  # type: ignore
    return HTML(string=html).write_pdf()


def _default_r2_uploader(file_bytes: bytes, key: str, content_type: str) -> str:
    """Production: bridge to server.py's _upload_to_r2. Imported
    lazily so test code can inject a stub without booting the
    full server."""
    from server import _upload_to_r2  # type: ignore
    return _upload_to_r2(file_bytes, key, content_type) or ""


def _to_object_id(s: str):
    """Best-effort ObjectId parsing. Returns the original string
    on failure so callers can still query by string-id."""
    try:
        from bson import ObjectId
        return ObjectId(s)
    except Exception:
        return s
