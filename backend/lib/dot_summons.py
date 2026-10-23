"""DOT summonses (DOT Phase 1 A) -- which alerts are due, and what they say.
Pure: no database, no HTTP. Matching is dot_sync.classify_summons.

THE RULES (operator rulings 2026-10-22, spec v3 A; `today` is a New York date):

  NEW SUMMONS      a summons matched by BBL, address or permit (OWN_MATCHES:
                   never a segment match, not even an accepted one), not
                   settled, NEW TO LEVELOG (first stored after the project's
                   first DOT summons pass) AND issued by DOT within the last
                   NEW_MAX_AGE_DAYS (2). Undated counts as old. The per-company
                   flag `dot_phase1` gates this email (and only this one).
                   Once per ticket.
  HEARING 14/7/1   a CONFIRMED summons (own match, or an accepted segment
                   match), not settled, hearing not completed: the smallest
                   threshold the days left have reached (14 from 14 days out,
                   7 from 7, 1 from 1 day out through the hearing day), so a
                   missed day still sends. Once per ticket x threshold window
                   x hearing date: a rescheduled hearing gets fresh reminders.
                   ONE DIGEST email per project per day lists every hearing
                   due, grouped by hearing date (ruling 2026-10-23), each
                   labelled with its TRUE days left -- a hearing caught up at
                   1 day says "1 day", and its ledger key and metadata say 1,
                   never the missed 7. Held over Shabbos / Yom Tov to the
                   window's end, like the pending-hearing email.
  PENDING HEARING  a segment match still PENDING review, not settled, hearing
                   within 14 days: ONE email per ticket x hearing date, "A DOT
                   summons on your block has a hearing on {date}. Confirm
                   whether it's yours."
  DEFAULT/DOCKETED a CONFIRMED summons whose hearing result (or status) CHANGES
                   to DEFAULTED or DOCKETED -- the sync stamps `default_event`
                   on the change; never at first sight. Once per ticket.

  Everything but NEW SUMMONS is date- or event-based and not flag-gated; all of
  it waits for the project's first DOT pass. The WhatsApp group posts follow
  the same rules (lib/wa_alerts kinds dot_violation / dot_hearing /
  dot_hearing_pending / dot_default).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from lib import dot_embargo, dot_sync

FLAG = "dot_phase1"
NEW_MAX_AGE_DAYS = 2
HEARING_THRESHOLDS = (14, 7, 1)
PENDING_HEARING_DAYS = 14

TRIGGER_NEW = "dot_summons_new"
TRIGGER_HEARING = "dot_hearing_reminder"
TRIGGER_PENDING = "dot_summons_pending_hearing"
TRIGGER_DEFAULT = "dot_summons_default"

_HEARING_DONE = re.compile(r"COMPLETED|DEFAULT|DOCKET|DISMISS|PAID|SETTL")


def _settled(row: Dict[str, Any]) -> bool:
    from lib import wa_alerts          # wa_alerts imports this module
    return wa_alerts.is_closed(row)


def summonses(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows or [] if isinstance(r, dict)
            and str(r.get("record_type") or "") == "dot_violation" and r.get("number")]


def how(row: Dict[str, Any]) -> str:
    m = row.get("match") if isinstance(row.get("match"), dict) else {}
    return str(m.get("how") or row.get("matched_by") or "")


def gc_flag_gated(item: Dict[str, Any]) -> bool:
    """A new-summons GROUP post that waits for the `dot_phase1` flag: only a
    permit-link match (operator ruling 2026-10-23). BBL and address matches
    keep today's behaviour and post with the flag off."""
    return (item.get("kind") == "dot_violation"
            and how(item.get("rec") or {}) == dot_sync.SUMMONS_PERMIT)


def issued_on(row: Dict[str, Any]) -> Optional[date]:
    return dot_embargo.parse_day(row.get("issued_on") or row.get("issue_date"))


def hearing_day(row: Dict[str, Any]) -> Optional[date]:
    return dot_embargo.parse_day(row.get("hearing_date"))


def recently_issued(row: Dict[str, Any], today: date) -> bool:
    """DOT's own date within NEW_MAX_AGE_DAYS of today; undated is old."""
    d = issued_on(row)
    return d is not None and 0 <= (today - d).days <= NEW_MAX_AGE_DAYS


def hearing_open(row: Dict[str, Any]) -> bool:
    return not _settled(row) and not _HEARING_DONE.search(str(row.get("hearing_status") or "").upper())


def hearing_threshold(days_left: Optional[int]) -> Optional[int]:
    if days_left is None or days_left < 0 or days_left > HEARING_THRESHOLDS[0]:
        return None
    due = None
    for t in HEARING_THRESHOLDS:
        if days_left <= max(t, 0):
            due = t
    return due


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        from datetime import timezone
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def new_due(rows: Iterable[Dict[str, Any]], today: date,
            first_pass_at: Optional[datetime]) -> List[Dict[str, Any]]:
    """The new-summons emails due: [{ticket, row}]. `first_pass_at`: when the
    project's first DOT summons pass finished (None = not yet: nothing). A row
    the first pass stored carries `first_pass` (the sync reads the state
    BEFORE the pass) and never emails; a row from before Phase 1 A carries no
    flag but is long past the 2-day window."""
    if first_pass_at is None:
        return []
    out = []
    for r in summonses(rows):
        if not dot_sync.record_confirmed(r) or how(r) not in dot_sync.OWN_MATCHES:
            continue
        if r.get("first_pass"):                    # stored by the first pass
            continue
        if _settled(r) or not recently_issued(r, today):
            continue
        out.append({"ticket": str(r["number"]), "row": r})
    return sorted(out, key=lambda d: d["ticket"])


def hearing_due(rows: Iterable[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """[{ticket, threshold, days, hearing, row}] for confirmed open summonses."""
    out = []
    for r in summonses(rows):
        if not dot_sync.record_confirmed(r) or not hearing_open(r):
            continue
        d = hearing_day(r)
        if d is None:
            continue
        t = hearing_threshold((d - today).days)
        if t is None:
            continue
        out.append({"ticket": str(r["number"]), "threshold": t, "days": (d - today).days,
                    "hearing": d, "row": r})
    return sorted(out, key=lambda x: (x["days"], x["ticket"]))


def pending_hearing_due(rows: Iterable[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """[{ticket, days, hearing, row}] for segment matches still pending review."""
    out = []
    for r in summonses(rows):
        if dot_sync.match_state(r) != dot_sync.STATE_NEEDS or not hearing_open(r):
            continue
        d = hearing_day(r)
        if d is None or not 0 <= (d - today).days <= PENDING_HEARING_DAYS:
            continue
        out.append({"ticket": str(r["number"]), "days": (d - today).days, "hearing": d, "row": r})
    return sorted(out, key=lambda x: (x["days"], x["ticket"]))


def default_due(rows: Iterable[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """[{ticket, result, row}]: a confirmed summons the sync saw CHANGE to
    DEFAULTED / DOCKETED within the last NEW_MAX_AGE_DAYS."""
    out = []
    for r in summonses(rows):
        ev = r.get("default_event") if isinstance(r.get("default_event"), dict) else None
        if not ev or not dot_sync.record_confirmed(r):
            continue
        d = dot_embargo.ny_date(ev.get("at"))
        if d is None or (today - d).days > NEW_MAX_AGE_DAYS:
            continue
        out.append({"ticket": str(r["number"]), "result": ev.get("result") or "DEFAULTED", "row": r})
    return sorted(out, key=lambda x: x["ticket"])


def hearing_ledger_id(project_id: str, ticket: str, days_left: int, hearing: date) -> str:
    """dot:<project>:hearing:<ticket>:<TRUE days left>d:<hearing date>."""
    return f"dot:{project_id}:hearing:{ticket}:{days_left}d:{hearing.isoformat()}"


def hearing_digest_text(project_name: str, items: List[Dict[str, Any]], today: date) -> Dict[str, Any]:
    """{subject, en: [lines], es: [lines]}: ONE email for every hearing
    reminder due today, grouped by hearing date. The subject says the count."""
    n = len(items)
    subj = (f"{n} DOT hearing{'s' if n != 1 else ''} coming up on {project_name} / "
            f"{n} audiencia{'s' if n != 1 else ''} del DOT {'próximas' if n != 1 else 'próxima'} "
            f"en {project_name}")
    groups: Dict[date, List[Dict[str, Any]]] = {}
    for it in items:
        groups.setdefault(it["hearing"], []).append(it)
    out: Dict[str, Any] = {"subject": subj}
    for lang in ("en", "es"):
        c = COPY[lang]
        lines = [(f"{n} DOT summons{'es' if n != 1 else ''} on {project_name} "
                  f"{'have hearings' if n != 1 else 'has a hearing'} coming up.") if lang == "en" else
                 (f"{n} citación{'es' if n != 1 else ''} del DOT de {project_name} "
                  f"{'tienen audiencias' if n != 1 else 'tiene una audiencia'} próximamente.")]
        for d in sorted(groups):
            days = (d - today).days
            lead = (f"Hearing {date_label(d, 'en')} ({'today' if days == 0 else 'in ' + days_label(days, 'en')}):"
                    if lang == "en" else
                    f"Audiencia el {date_label(d, 'es')} ({'hoy' if days == 0 else 'en ' + days_label(days, 'es')}):")
            lines.append(lead)
            for it in sorted(groups[d], key=lambda x: x["ticket"]):
                row = it["row"]
                m = row.get("match") if isinstance(row.get("match"), dict) else {}
                charges = "; ".join(" ".join(x for x in (str(g.get("code") or ""), str(g.get("description") or ""))
                                             if x) for g in row.get("charges") or []) \
                    or (row.get("description") or c["not_stated"])
                when = " ".join(x for x in (str(row.get("hearing_time") or "")[:5],
                                            str(row.get("hearing_location") or "")) if x)
                hw = c["how"].get(how(row), how(row) or c["not_stated"]).format(permit=m.get("permit_number") or "")
                lines.append(f"  {it['ticket']} · {charges}" + (f" · {when}" if when else "")
                             + f" · {c['balance']}: {money(row.get('balance_due'))} · {c['matched']}: {hw}")
        out[lang] = lines
    return out


def ledger_id(project_id: str, kind: str, ticket: str, threshold: Any = "-",
              anchor: Any = "-") -> str:
    """dot:<project>:<kind>:<record>:<threshold>:<anchor-date> (spec v3)."""
    a = anchor.isoformat() if isinstance(anchor, date) else str(anchor)
    return f"dot:{project_id}:{kind}:{ticket}:{threshold}:{a}"


# ── The screen ──────────────────────────────────────────────────────────────

def summons_view(row: Dict[str, Any], today: date) -> Dict[str, Any]:
    d = hearing_day(row)
    issued = issued_on(row)
    m = row.get("match") if isinstance(row.get("match"), dict) else {}
    seg = dot_sync.oath_segment(row.get("location"), row.get("house"))
    return {
        "id": str(row.get("_id") or ""),
        "number": row.get("number"),
        "charges": row.get("charges") or ([{"code": None, "description": row.get("description"),
                                             "amount": None}] if row.get("description") else []),
        "total_amount": row.get("total_amount"),
        "penalty_imposed": row.get("penalty_imposed"),
        "paid_amount": row.get("paid_amount"),
        "balance_due": row.get("balance_due"),
        "issued_on": issued.isoformat() if issued else None,
        "hearing_date": d.isoformat() if d else None,
        "hearing_time": row.get("hearing_time"),
        "hearing_location": row.get("hearing_location"),
        "hearing_status": row.get("hearing_status"),
        "hearing_result": row.get("hearing_result"),
        "status": row.get("status"),
        "days_to_hearing": (d - today).days if d else None,
        "settled": _settled(row),
        "how": how(row),
        "permit_number": m.get("permit_number"),
        "state": dot_sync.match_state(row),
        "location": row.get("location"),
        "segment": seg,
        "respondent": row.get("respondent"),
        "link": row.get("link"),
    }


def board(rows: Iterable[Dict[str, Any]], today: date) -> Dict[str, Any]:
    """GET /dot/summonses: the project's summonses (open, then settled), the
    segment matches waiting for "it's ours?", and the rejected ones (they can
    be re-accepted)."""
    mine, pending, rejected = [], [], []
    for r in summonses(rows):
        st = dot_sync.match_state(r)
        v = summons_view(r, today)
        (pending if st == dot_sync.STATE_NEEDS else rejected if st == dot_sync.STATE_REJECTED
         else mine).append(v)

    def _key(v):
        return (v["hearing_date"] or "9999-12-31", str(v["number"]))

    open_ = sorted([v for v in mine if not v["settled"]], key=_key)
    done = sorted([v for v in mine if v["settled"]], key=lambda v: (v["issued_on"] or ""), reverse=True)
    pending.sort(key=_key)
    rejected.sort(key=lambda v: (v["issued_on"] or ""), reverse=True)
    return {"summonses": open_ + done, "needs_confirmation": pending, "rejected": rejected,
            "counts": {"open": len(open_), "settled": len(done), "needs_confirmation": len(pending),
                       "rejected": len(rejected)}}


# ── The emails: EN / ES copy (beside lib/dob_alert_gate.COPY) ───────────────

_ES_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun",
              "jul", "ago", "sep", "oct", "nov", "dic")

COPY = {
    "en": {
        "subject_new": "New DOT summons on {project}",
        "intro_new": "Levelog picked up a new DOT summons on {project}.",
        "subject_hearing": "DOT hearing in {days} on {project}",
        "intro_hearing": "DOT summons {ticket} on {project} has a hearing in {days}, on {date}.",
        "subject_pending": "DOT summons on your block: hearing {date}",
        "intro_pending": "A DOT summons on your block has a hearing on {date}. Confirm whether it's yours.",
        "subject_default": "DOT summons {ticket} was marked {result} on {project}",
        "intro_default": "DOT summons {ticket} was marked {result} on {project}.",
        "record": "Issued by DOT: {date} · Status: {status}",
        "ticket": "Summons", "charges": "Charges", "total": "Total", "balance": "Balance due",
        "hearing": "Hearing", "matched": "Matched by", "location": "Location",
        "how": {"bbl": "block and lot", "address": "address", "permit": "permit {permit}",
                "segment": "your block (not confirmed)"},
        "pending_action": "Open the DOT tab in Levelog and answer \"It's ours\" or \"Not ours\".",
        "days_1": "1 day", "days_n": "{n} days", "days_0": "today",
        "not_stated": "not stated",
    },
    "es": {
        "subject_new": "Nueva citación del DOT en {project}",
        "intro_new": "Levelog encontró una citación nueva del DOT en {project}.",
        "subject_hearing": "Audiencia del DOT en {days} en {project}",
        "intro_hearing": "La citación del DOT {ticket} de {project} tiene audiencia en {days}, el {date}.",
        "subject_pending": "Citación del DOT en su cuadra: audiencia el {date}",
        "intro_pending": "Una citación del DOT en su cuadra tiene audiencia el {date}. Confirme si es suya.",
        "subject_default": "La citación del DOT {ticket} fue marcada como {result} en {project}",
        "intro_default": "La citación del DOT {ticket} fue marcada como {result} en {project}.",
        "record": "Emitido por el DOT: {date} · Estado: {status}",
        "ticket": "Citación", "charges": "Cargos", "total": "Total", "balance": "Saldo pendiente",
        "hearing": "Audiencia", "matched": "Vinculada por", "location": "Ubicación",
        "how": {"bbl": "bloque y lote", "address": "dirección", "permit": "el permiso {permit}",
                "segment": "su cuadra (sin confirmar)"},
        "pending_action": "Abra la pestaña del DOT en Levelog y responda \"Es nuestra\" o \"No es nuestra\".",
        "days_1": "1 día", "days_n": "{n} días", "days_0": "hoy",
        "not_stated": "no indicado",
    },
}

RESULT_ES = {"DEFAULTED": "EN REBELDÍA (DEFAULTED)", "DOCKETED": "REGISTRADA (DOCKETED)"}


def date_label(d: Optional[date], lang: str) -> str:
    if d is None:
        return COPY[lang]["not_stated"]
    if lang == "es":
        return f"{d.day} {_ES_MONTHS[d.month - 1]} {d.year}"
    return f"{d:%b} {d.day}, {d.year}"


def days_label(n: int, lang: str) -> str:
    c = COPY[lang]
    return c["days_0"] if n == 0 else c["days_1"] if n == 1 else c["days_n"].format(n=n)


def money(v: Any) -> str:
    if v is None or v == "":
        return "-"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"${n:,.0f}" if n == int(n) else f"${n:,.2f}"


def detail_lines(row: Dict[str, Any], lang: str) -> List[str]:
    c = COPY[lang]
    m = row.get("match") if isinstance(row.get("match"), dict) else {}
    hw = how(row)
    hd = hearing_day(row)
    charges = row.get("charges") or []
    ch = "; ".join(" ".join(x for x in (str(g.get("code") or ""), str(g.get("description") or ""),
                                        money(g.get("amount")) if g.get("amount") is not None else "")
                            if x) for g in charges) or (row.get("description") or c["not_stated"])
    hearing = date_label(hd, lang)
    extra = " ".join(x for x in (str(row.get("hearing_time") or "")[:5],
                                 str(row.get("hearing_location") or "")) if x)
    return [
        f"{c['ticket']}: {row.get('number')}",
        c["record"].format(date=date_label(issued_on(row), lang),
                           status=row.get("status") or c["not_stated"]),
        f"{c['charges']}: {ch}",
        f"{c['total']}: {money(row.get('total_amount'))} · {c['balance']}: {money(row.get('balance_due'))}",
        f"{c['hearing']}: {hearing}" + (f" {extra}" if extra else ""),
        f"{c['location']}: {row.get('location') or c['not_stated']}",
        f"{c['matched']}: " + c["how"].get(hw, hw or c["not_stated"]).format(
            permit=m.get("permit_number") or ""),
    ]


def email_text(kind: str, row: Dict[str, Any], project_name: str, today: date,
               result: Optional[str] = None) -> Dict[str, Any]:
    """{subject, en: [lines], es: [lines]} for one summons email."""
    hd = hearing_day(row)
    out: Dict[str, Any] = {}
    subj = []
    for lang in ("en", "es"):
        c = COPY[lang]
        days = days_label((hd - today).days, lang) if hd else c["not_stated"]
        res = (result or "DEFAULTED") if lang == "en" else RESULT_ES.get(result or "DEFAULTED", result)
        fmt = {"project": project_name, "ticket": row.get("number"), "days": days,
               "date": date_label(hd, lang), "result": res}
        subj.append(c[f"subject_{kind}"].format(**fmt))
        lines = [c[f"intro_{kind}"].format(**fmt)] + detail_lines(row, lang)
        if kind == "pending":
            lines.append(c["pending_action"])
        out[lang] = lines
    out["subject"] = " / ".join(subj)
    return out
