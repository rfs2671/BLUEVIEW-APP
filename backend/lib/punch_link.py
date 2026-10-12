"""The assignee's private link: their open punch items on a phone page, no
login. Pure parts (no database, no network): the signed token, the lines a
punch message adds, and the page.

THE LINK. One per assignee per job, made when their items are sent (shadow
mode too: the walker sees it in the shadow text, nothing is sent). It reads
<PUBLIC_BASE_URL>/api/public/punch/<id>.<signature>: `id` names the stored
link (punch_links), `signature` is an HMAC of it with the server's secret, so
an id alone, or a guessed one, opens nothing. The link stops working when
every one of their items on that job is closed, after 30 days, or when it is
revoked; all of these, and anything else wrong, answer the same "This link
is no longer active."

WHAT IT SHOWS. Only that assignee's items on that job and that company: the
words, where, the due, every photo (full size), and for an open item "Mark
done" with an optional photo -> Ready to check (a GC admin or PM still
closes it). Never anyone else's items, never a phone number.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

COLLECTION = "punch_links"
LIFETIME_DAYS = 30
#: Statuses the page shows: open (Mark done) and ready to check (waiting).
LIVE = ("open", "ready_to_check")
GONE_TEXT = "This link is no longer active."
#: Shown under a photo that is only WhatsApp's preview (server.PHOTO_PREVIEW_LABEL).
PREVIEW_LABEL = "Original unavailable — preview only"
_ID = re.compile(r"^[A-Za-z0-9_-]{12,40}$")
_SIG = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def signature(link_id: str, secret: str) -> str:
    mac = hmac.new(str(secret).encode(), f"punch-link:{link_id}".encode(), hashlib.sha256).digest()
    return _b64(mac)[:32]


def token(link_id: str, secret: str) -> str:
    return f"{link_id}.{signature(link_id, secret)}"


def verify(tok: Any, secret: str) -> Optional[str]:
    """The link id a token names, when its signature is right; else None."""
    parts = str(tok or "").split(".")
    if len(parts) != 2 or not _ID.match(parts[0]) or not _SIG.match(parts[1]):
        return None
    good = signature(parts[0], secret)
    return parts[0] if hmac.compare_digest(good, parts[1]) else None


def url(base: str, tok: str) -> str:
    return f"{str(base).rstrip('/')}/api/public/punch/{tok}"


def expires_at(created: datetime) -> datetime:
    return created + timedelta(days=LIFETIME_DAYS)


def person_key(a: Optional[Dict[str, Any]]) -> str:
    a = a or {}
    return f"{a.get('kind')}:{a.get('id')}" if a.get("kind") and a.get("id") else ""


def live(link: Optional[Dict[str, Any]], now: datetime) -> bool:
    """Not revoked, not past its 30 days."""
    if not link or link.get("revoked_at"):
        return False
    exp = link.get("expires_at")
    if isinstance(exp, datetime):
        exp = exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
        return now < exp
    return False


# ── What a punch message adds ───────────────────────────────────────────────

def link_lines(links: List[Tuple[str, str]]) -> str:
    """The lines a punch message ends with. One person: "Your items, with
    photos (private link, no login): <url>". Several (a whole list in the
    group): one line each."""
    links = [(n, u) for n, u in links if u]
    if not links:
        return ""
    if len(links) == 1:
        return f"Your items, with photos — mark them done there (private link, no login):\n{links[0][1]}"
    return "Each person's items, with photos (private link, no login):\n" + "\n".join(
        f"• {n or 'Assignee'}: {u}" for n, u in links)


# ── The page ────────────────────────────────────────────────────────────────

def _e(v: Any) -> str:
    return html.escape(str(v or ""), quote=True)


def _where(r: Dict[str, Any]) -> str:
    parts = []
    f = str(r.get("floor") or "")
    if f and f != "?":
        parts.append(f"Floor {f}" if f.isdigit() else f[:1].upper() + f[1:])
    a = str(r.get("area") or "")
    if a and a != "?" and a != f:
        parts.append(a)
    if r.get("room") and a and a != "?":
        parts.append(str(r["room"]))
    t = str(r.get("trade") or "")
    if t and t != "?":
        parts.append(t)
    return " · ".join(parts)


def _due(r: Dict[str, Any]) -> str:
    d = r.get("due") or {}
    if (d.get("due_text") or "").upper() == "ASAP":
        return "Due ASAP"
    if d.get("due_at"):
        try:
            day = datetime.fromisoformat(str(d["due_at"])[:10])
            return f"Due {day.strftime('%a %b')} {day.day}"
        except ValueError:
            pass
    return "No due date"


def page(*, name: str, job: str, items: Iterable[Dict[str, Any]], tok: str,
         done: Optional[str] = None, error: Optional[str] = None) -> str:
    """The phone page: this person's open items on this job."""
    rows = list(items)
    cards = []
    for r in rows:
        pid = _e(r.get("pid"))
        n = int(r.get("photos") or 0)
        photos = "".join(
            f'<a href="{_e(tok)}/photo/{pid}/{i}"><img loading="lazy" alt="Photo {i} of {pid}" '
            f'src="{_e(tok)}/photo/{pid}/{i}"></a>' for i in range(1, n + 1))
        if n and r.get("photo_quality") == "preview":
            photos += f'<p class="meta">{_e(PREVIEW_LABEL)}</p>'
        elif not n:
            photos = '<p class="meta">No photo.</p>'

        if r.get("status") == "open":
            act = (f'<form method="post" enctype="multipart/form-data" action="{_e(tok)}/done/{pid}">'
                   f'<label class="pick">Add a photo (optional)'
                   f'<input type="file" name="photo" accept="image/*" capture="environment"></label>'
                   f'<button type="submit">Mark {pid} done</button></form>')
        else:
            act = '<p class="wait">Marked done — waiting for the GC to check it.</p>'
        cards.append(
            f'<section class="card"><h2>{pid}</h2><p class="words">“{_e(r.get("text"))}”</p>'
            f'<p class="meta">{_e(_where(r))}</p><p class="meta">{_e(_due(r))}</p>'
            f'<div class="photos">{photos}</div>{act}</section>')
    note = ""
    if done:
        note = f'<p class="ok">{_e(done)} marked done — ready to check. Thank you.</p>'
    if error:
        note = f'<p class="err">{_e(error)}</p>'
    body = "".join(cards) or "<p>Nothing open for you here.</p>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">
<title>Punch items — {_e(job)}</title>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;margin:0;background:#f4f6fa;color:#111}}
header{{background:#1565c0;color:#fff;padding:16px}}
header h1{{font-size:18px;margin:0}} header p{{margin:4px 0 0;font-size:14px;opacity:.9}}
main{{padding:12px}} .card{{background:#fff;border-radius:10px;padding:12px;margin-bottom:12px;
box-shadow:0 1px 3px rgba(0,0,0,.1)}} h2{{font-size:16px;margin:0 0 4px}}
.words{{font-size:16px;margin:4px 0}} .meta{{font-size:13px;color:#555;margin:2px 0}}
.photos img{{width:100%;border-radius:8px;margin-top:8px;display:block}}
form{{margin-top:10px}} .pick{{display:block;font-size:14px;margin-bottom:8px}}
.pick input{{display:block;margin-top:4px}}
button{{width:100%;padding:12px;font-size:16px;border:0;border-radius:8px;background:#1565c0;color:#fff}}
.wait{{color:#2e7d32;font-size:14px}} .ok{{background:#e8f5e9;padding:10px;border-radius:8px}}
.err{{background:#ffebee;padding:10px;border-radius:8px}}
</style></head><body>
<header><h1>{_e(job)}</h1><p>{_e(name)} — your punch items</p></header>
<main>{note}{body}<p class="meta">This private link is only for you. It stops working when
your items are closed, or after {LIFETIME_DAYS} days.</p></main></body></html>"""


def gone_page() -> str:
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta name='robots' content='noindex,nofollow'><title>Levelog</title></head>"
            f"<body style='font-family:system-ui;padding:24px'><p>{GONE_TEXT}</p></body></html>")
