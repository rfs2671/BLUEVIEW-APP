"""The assignee's private link: their open punch items on a phone page, no
login. Pure parts (no database, no network): the signed token, the lines a
punch message adds, and the page.

THE LINK. One per assignee per job, made when their items are first sent
(shadow mode too: the walker sees it in the shadow text, nothing is sent),
and the same link ever after: items given to them later show up on it. It
reads <PUBLIC_BASE_URL>/api/public/punch/<id>.<signature>: `id` names the
stored link (punch_links), `signature` is an HMAC of it with the server's
secret, so an id alone, or a guessed one, opens nothing. It works while any
of their items on that job is not closed (a reopened or newly assigned item
brings it back) and until 30 days after the last activity on it (a send, an
open, an upload, a "Mark done", a status change of one of their items); a
manual revoke ends it for good. Anything else wrong answers the same "This
link is no longer active."

WHAT IT SHOWS. Only that assignee's items on that job and that company: the
words, where, the due, every photo (full size). Ready to check first ("✓
Ready to check — waiting for review"), then open ones with "Mark done" and an
optional photo, then the closed ones, folded. A photo uploads as soon as it
is picked (kept on the item as pending, so a closed tab never loses it);
"Mark done" just confirms -> Ready to check (a GC admin or PM still closes
it). A reopened item is open again with the admin's note. Never anyone
else's items, never a phone number.
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
#: Statuses that keep the link working: open (Mark done) and ready to check.
LIVE = ("open", "ready_to_check")
#: The page's sections, in order (closed folded at the bottom).
SECTIONS = ("ready_to_check", "open", "closed")
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


def touched(now: datetime) -> Dict[str, Any]:
    """What an activity on the link sets: 30 more days from now."""
    return {"last_activity_at": now, "expires_at": expires_at(now)}


def live(link: Optional[Dict[str, Any]], now: datetime) -> bool:
    """Not revoked, not 30 days past its last activity (`expires_at` moves
    with every activity, see touched())."""
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


READY_TEXT = "✓ Ready to check — waiting for review"
#: The page's own script: a picked photo uploads at once, with a progress bar
#: and a retry; "Mark done" then only confirms. Without it the form still
#: posts the photo with "Mark done".
_SCRIPT = """
document.querySelectorAll('form.done').forEach(function (f) {
  var inp = f.querySelector('input[type=file]'), bar = f.querySelector('progress'),
      msg = f.querySelector('.up'), retry = f.querySelector('.retry'),
      btn = f.querySelector('button[type=submit]'), last = null;
  function fail(t) {
    bar.hidden = true; retry.hidden = false; btn.disabled = false;
    msg.textContent = t + ' Nothing was changed.';
  }
  function send() {
    if (!last) return;
    var x = new XMLHttpRequest(), fd = new FormData();
    fd.append('photo', last);
    bar.hidden = false; bar.value = 0; retry.hidden = true; btn.disabled = true;
    msg.textContent = 'Uploading the photo…';
    x.upload.onprogress = function (e) { if (e.lengthComputable) bar.value = 100 * e.loaded / e.total; };
    x.onload = function () {
      if (x.status === 200) {
        bar.value = 100; inp.value = ''; btn.disabled = false;
        msg.textContent = 'Photo saved. Tap “' + btn.textContent + '” to confirm.';
      } else if (x.status === 422) {
        fail('That file is not a photo we can use (a JPEG, PNG or HEIC under 15 MB).');
      } else {
        fail('The photo did not upload.');
      }
    };
    x.onerror = function () { fail('The photo did not upload (no signal?).'); };
    x.open('POST', f.getAttribute('data-up')); x.send(fd);
  }
  inp.addEventListener('change', function () { last = inp.files && inp.files[0]; send(); });
  retry.addEventListener('click', function (e) { e.preventDefault(); send(); });
});
"""


def _card(r: Dict[str, Any], tok: str) -> str:
    pid = _e(r.get("pid"))
    n = int(r.get("photos") or 0)
    # Each photo's own quality: the first, then any merged in.
    quals = list(r.get("qualities") or [r.get("photo_quality")] * n)
    photos = "".join(
        f'<a href="{_e(tok)}/photo/{pid}/{i}"><img loading="lazy" alt="Photo {i} of {pid}" '
        f'src="{_e(tok)}/photo/{pid}/{i}"></a>'
        + (f'<p class="meta">{_e(PREVIEW_LABEL)}</p>' if i <= len(quals) and quals[i - 1] == "preview"
           else "") for i in range(1, n + 1))
    if not n:
        photos = '<p class="meta">No photo.</p>'
    status = r.get("status")
    head = ""
    if status == "ready_to_check":
        head = f'<p class="wait">{_e(READY_TEXT)}</p>'
    elif status == "open" and r.get("reopened"):
        note = str(r.get("reopen_note") or "").strip()
        head = (f'<p class="reopen">Reopened: “{_e(note)}”</p>' if note
                else '<p class="reopen">Reopened — please check it again.</p>')
    act = ""
    if status == "open":
        saved = ('<p class="up">Photo saved. Tap “Mark done” to confirm '
                 '(or pick another to replace it).</p>' if r.get("pending_photo")
                 else '<p class="up"></p>')
        act = (f'<form class="done" method="post" enctype="multipart/form-data" '
               f'action="{_e(tok)}/done/{pid}" data-up="{_e(tok)}/upload/{pid}">'
               f'<label class="pick">Add a photo (optional)'
               f'<input type="file" name="photo" accept="image/*" capture="environment"></label>'
               f'<progress max="100" value="0" hidden></progress>{saved}'
               f'<a href="#" class="retry" hidden>Retry the upload</a>'
               f'<button type="submit">Mark {pid} done</button></form>')
    return (f'<section class="card {_e(status)}">{head}<h2>{pid}</h2>'
            f'<p class="words">“{_e(r.get("text"))}”</p>'
            f'<p class="meta">{_e(_where(r))}</p><p class="meta">{_e(_due(r))}</p>'
            f'<div class="photos">{photos}</div>{act}</section>')


def page(*, name: str, job: str, items: Iterable[Dict[str, Any]], tok: str,
         done: Optional[str] = None, error: Optional[str] = None) -> str:
    """The phone page: this person's items on this job -- ready to check,
    then open, then closed (folded)."""
    rows = list(items)
    by = {s: [r for r in rows if r.get("status") == s] for s in SECTIONS}
    body = "".join(_card(r, tok) for r in by["ready_to_check"] + by["open"])
    if not body:
        body = "<p>Nothing open for you here.</p>"
    if by["closed"]:
        body += (f'<details class="closed"><summary>Closed ({len(by["closed"])})</summary>'
                 + "".join(_card(r, tok) for r in by["closed"]) + "</details>")
    note = ""
    if done:
        note = f'<p class="ok">{_e(done)} marked done — ready to check. Thank you.</p>'
    if error:
        note = f'<p class="err">{_e(error)}</p>'
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
.pick input{{display:block;margin-top:4px}} progress{{width:100%}}
.up{{font-size:13px;color:#2e7d32;margin:4px 0}} .retry{{display:block;margin:4px 0 8px}}
button{{width:100%;padding:12px;font-size:16px;border:0;border-radius:8px;background:#1565c0;color:#fff}}
button:disabled{{opacity:.5}}
.wait{{color:#2e7d32;font-size:14px;font-weight:600;margin:0 0 6px}}
.reopen{{color:#b71c1c;font-size:14px;font-weight:600;margin:0 0 6px}}
.ok{{background:#e8f5e9;padding:10px;border-radius:8px}}
.err{{background:#ffebee;padding:10px;border-radius:8px}}
details.closed summary{{font-size:15px;padding:8px 0;cursor:pointer}}
details.closed .card{{opacity:.75}}
</style></head><body>
<header><h1>{_e(job)}</h1><p>{_e(name)} — your punch items</p></header>
<main>{note}{body}<p class="meta">This private link is only for you. It stays the same for new
items; it stops working once all your items here are closed, or {LIFETIME_DAYS} days after
the last activity.</p></main><script>{_SCRIPT}</script></body></html>"""


def gone_page() -> str:
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta name='robots' content='noindex,nofollow'><title>Levelog</title></head>"
            f"<body style='font-family:system-ui;padding:24px'><p>{GONE_TEXT}</p></body></html>")
