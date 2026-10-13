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

WHAT IT SHOWS. Only that assignee's items on that job and that company,
made for someone who has never used an app: "Hi Chris 👋 · 2 things to fix",
the job's address, a progress bar; their open items grouped by floor, each
one card -- a thumbnail (tap: full screen, pinch to zoom), what is wrong in
big words, where, "Due today" / "Overdue" only when it presses, and one big
green button, "✅ I fixed it", that opens the camera; the photo is sent at
once and the card turns green. "Skip photo" under it. A reopened item comes
back at the top with the GC's note. Done ones wait folded at the bottom,
then the closed ones. English or Spanish (their language on People, or the
switch at the top). Never anyone else's items, never a phone number; the
item's id only small at the bottom of its card.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import html
import json
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
#
# Made for someone who has never used an app (Oct 12: "a 70-year-old with no
# tech skills understands it in 5 seconds"): one big action per item, no
# jargon, no ids up front, 18px+ text, buttons 56px+ tall, light and high
# contrast. Their language (EN / ES), with a switch at the top.

LANGS = ("en", "es")

TEXT: Dict[str, Dict[str, str]] = {
    "en": {
        "hi": "Hi {name} 👋",
        "hi_anon": "Hi 👋",
        "left_1": "1 thing to fix",
        "left_n": "{n} things to fix",
        "left_0": "All done — thank you!",
        "progress": "{done} of {total} done",
        "fix": "✓ I fixed it",
        "fix_hint": "Take a photo of the fix",
        "skip": "Skip photo",
        "send": "Send",
        "sending": "Sending the photo…",
        "finishing": "Sending…",
        "done": "Done ✓ — thanks! The GC will check it.",
        "failed": "Couldn't send — tap to try again",
        "offline": "No signal. It will send by itself when you're back online.",
        "bad_photo": "That isn't a photo we can use. Please take it again.",
        "changed": "This item was changed. Loading the latest…",
        "waiting": "Done — waiting for the GC to check ({n})",
        "closed": "Checked and closed ({n})",
        "not_fixed": "Not fixed yet: {note}",
        "not_fixed_bare": "Not fixed yet — please look again.",
        "due_today": "Due today",
        "overdue": "Overdue",
        "asap": "As soon as possible",
        "no_photo": "No photo",
        "preview": "Small photo only — the original was lost",
        "photo_n": "Photo {i} of {n}",
        "close": "✕ Close",
        "next": "Next photo ›",
        "questions": "Questions? Reply on WhatsApp",
        "private": "This page is just for you.",
        "powered": "Powered by Levelog",
        "thanks_banner": "Thank you! The GC will check it.",
        "error_banner": "{msg}",
        "nothing": "Nothing to fix here right now.",
        "floor": "Floor {n}",
        "lobby": "Lobby", "basement": "Basement", "cellar": "Cellar", "ground": "Ground floor",
        "roof": "Roof", "bulkhead": "Bulkhead", "unknown_floor": "Other",
        "lang_name": "English",
    },
    "es": {
        "hi": "Hola {name} 👋",
        "hi_anon": "Hola 👋",
        "left_1": "1 cosa por arreglar",
        "left_n": "{n} cosas por arreglar",
        "left_0": "¡Todo listo — gracias!",
        "progress": "{done} de {total} listas",
        "fix": "✓ Ya lo arreglé",
        "fix_hint": "Tome una foto del arreglo",
        "skip": "Sin foto",
        "send": "Enviar",
        "sending": "Enviando la foto…",
        "finishing": "Enviando…",
        "done": "Listo ✓ — ¡gracias! El contratista lo revisará.",
        "failed": "No se pudo enviar — toque para intentar de nuevo",
        "offline": "Sin señal. Se enviará solo cuando vuelva la conexión.",
        "bad_photo": "Esa no es una foto que podamos usar. Tómela de nuevo, por favor.",
        "changed": "Esto cambió. Cargando lo más reciente…",
        "waiting": "Listo — esperando que el contratista lo revise ({n})",
        "closed": "Revisado y cerrado ({n})",
        "not_fixed": "Todavía no está arreglado: {note}",
        "not_fixed_bare": "Todavía no está arreglado — revíselo otra vez.",
        "due_today": "Vence hoy",
        "overdue": "Atrasado",
        "asap": "Lo antes posible",
        "no_photo": "Sin foto",
        "preview": "Solo foto pequeña — se perdió la original",
        "photo_n": "Foto {i} de {n}",
        "close": "✕ Cerrar",
        "next": "Siguiente foto ›",
        "questions": "¿Preguntas? Responda por WhatsApp",
        "private": "Esta página es solo para usted.",
        "powered": "Con la tecnología de Levelog",
        "thanks_banner": "¡Gracias! El contratista lo revisará.",
        "error_banner": "{msg}",
        "nothing": "No hay nada por arreglar ahora.",
        "floor": "Piso {n}",
        "lobby": "Vestíbulo", "basement": "Sótano", "cellar": "Sótano", "ground": "Planta baja",
        "roof": "Techo", "bulkhead": "Caseta del techo", "unknown_floor": "Otro",
        "lang_name": "Español",
    },
}


@functools.lru_cache(maxsize=1)
def wordmark() -> str:
    """The Levelog wordmark as a data: URL (lib/assets/levelog-wordmark.png,
    made from the app's logo by scripts/make_link_wordmark.py); "" if missing."""
    from pathlib import Path
    try:
        data = (Path(__file__).resolve().parent / "assets" / "levelog-wordmark.png").read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(data).decode()


#: The GC's name, as the app's header sizes it (utils/brandLabel.js): one
#: line, the largest size that fits a 360 px phone (the page less its 16 px
#: sides), never under 10 px; a name too long even then ends in "…" (CSS).
GC_MAX_PX, GC_MIN_PX, GC_ROOM_PX = 14, 10, 328
_GC_CHAR_EM = 0.68                 # a light uppercase geometric sans, per point


def gc_sizing(name: Any) -> Tuple[int, int]:
    """(font size, letter spacing) in px for the GC's name."""
    n = max(1, len(str(name or "").strip()))
    for size in range(GC_MAX_PX, GC_MIN_PX - 1, -1):
        spacing = 2 if size >= 13 else 1
        if n * (size * _GC_CHAR_EM + spacing) <= GC_ROOM_PX:
            return size, spacing
    return GC_MIN_PX, 1


def lang_of(*choices: Any) -> str:
    """The first of `choices` that is a page language ("en", "es"); else
    English (Yiddish comes later)."""
    for c in choices:
        c = str(c or "").strip().lower()[:2]
        if c in LANGS:
            return c
    return "en"


def t(lang: str, key: str, **kw: Any) -> str:
    s = TEXT.get(lang, TEXT["en"]).get(key) or TEXT["en"][key]
    return s.format(**kw) if kw else s


def _e(v: Any) -> str:
    return html.escape(str(v or ""), quote=True)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _floor_key(f: str) -> Tuple[int, str]:
    order = {"cellar": -2, "basement": -2, "lobby": 0, "ground": 0, "roof": 999, "bulkhead": 1000}
    f = str(f or "").strip().lower()
    if not f or f == "?":
        return (2000, "")
    if f.isdigit():
        return (int(f), "")
    return (order.get(f, 500), f)


_FLOOR_WORDS = ("lobby", "basement", "cellar", "ground", "roof", "bulkhead")


def place(r: Dict[str, Any], lang: str = "en") -> str:
    """The heading an item is listed under: its floor ("Floor 4", "Lobby")."""
    f = str(r.get("floor") or "").strip()
    if not f or f == "?":
        return t(lang, "unknown_floor")
    if f.isdigit():
        return t(lang, "floor", n=f)
    return t(lang, f.lower()) if f.lower() in _FLOOR_WORDS else _cap(f)


def spot(r: Dict[str, Any]) -> str:
    """Where on that floor, in grey under the words: "Apt 4C · Kitchen"."""
    parts = []
    for k in ("area", "room"):
        v = str(r.get(k) or "").strip()
        if v and v != "?" and v != str(r.get("floor") or ""):
            parts.append(_cap(v))
    return " · ".join(parts)


def due_flag(r: Dict[str, Any], today: Any, lang: str = "en") -> str:
    """Only when it presses: "Due today", "Overdue", "As soon as possible"."""
    d = r.get("due") or {}
    if (d.get("due_text") or "").upper() == "ASAP":
        return t(lang, "asap")
    at = str(d.get("due_at") or "")[:10]
    if not at or not today:
        return ""
    day = str(today)[:10]
    if at == day:
        return t(lang, "due_today")
    if at < day:
        return t(lang, "overdue")
    return ""


def first_name(name: str) -> str:
    return (str(name or "").strip().split() or [""])[0]


# The app's own look (frontend/src/styles/theme.js, the light palette, and
# components/HeaderBrand.js): navy text, Levelog blue for everything you can
# press or that moves, green ONLY for what is finished, the company's name in
# the header's thin uppercase Montserrat. White page.
NAVY = "#0A1929"          # theme light text.primary
BLUE = "#1565C0"          # theme light primary
GREEN = "#2E7D32"         # theme light success -- done, and nothing else
RED = "#C62828"           # theme light error
MUTED = "rgba(10,25,41,0.65)"   # theme light text.muted
EDGE = "rgba(191,219,254,0.9)"  # theme light border (blue-200)
BRAND_FONT = ('Montserrat,"Gotham","Futura","Avenir Next","Helvetica Neue",Helvetica,Arial,'
              'sans-serif')

_CSS = ("""
:root{color-scheme:light}
*{box-sizing:border-box}
body{font-family:-apple-system,system-ui,Roboto,sans-serif;margin:0;background:#fff;
color:NAVY;font-size:18px;line-height:1.4;-webkit-text-size-adjust:100%}
.top{background:#fff;padding:14px 16px 14px;border-bottom:2px solid EDGE}
.brand{display:flex;align-items:center;justify-content:space-between;gap:10px}
.logo{display:block;height:30px;width:auto}
.gc{font-family:BRAND_FONT;font-weight:300;text-transform:uppercase;letter-spacing:2px;
font-size:14px;color:MUTED;margin:6px 0 12px;line-height:1.5;white-space:nowrap;overflow:hidden;
text-overflow:ellipsis;max-width:100%}
.langs{display:flex;gap:6px;flex:0 0 auto}
.langs a{display:inline-flex;align-items:center;min-height:56px;padding:0 12px;border-radius:28px;
border:2px solid BLUE;color:BLUE;text-decoration:none;font-size:17px;font-weight:600}
.langs a.on{background:BLUE;color:#fff}
h1{font-size:28px;margin:0;line-height:1.2}
.left{font-size:22px;font-weight:700;margin:4px 0 0}
.addr{font-size:18px;color:MUTED;margin:4px 0 12px}
.bar{height:16px;border-radius:8px;background:#E3EAF5;overflow:hidden}
.bar i{display:block;height:100%;background:BLUE;border-radius:8px}
.count{font-size:18px;margin:6px 0 0}
main{padding:12px 16px 24px}
h2{font-size:22px;margin:22px 0 10px;color:NAVY}
.card{background:#fff;border:2px solid EDGE;border-radius:14px;padding:14px;margin-bottom:14px}
.row{display:flex;gap:14px;align-items:flex-start}
.thumb{flex:0 0 72px;width:72px;height:72px;border-radius:10px;overflow:hidden;background:#E3EAF5;
border:0;padding:0;position:relative;display:flex;align-items:center;justify-content:center;
font-size:14px;color:MUTED;text-align:center;text-decoration:none}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.thumb b{position:absolute;right:4px;bottom:4px;background:rgba(10,25,41,.75);color:#fff;font-size:14px;
padding:0 6px;border-radius:8px}
.what{font-size:22px;font-weight:700;margin:0;word-break:break-word}
.where{font-size:18px;color:MUTED;margin:4px 0 0}
.due{font-size:18px;color:RED;font-weight:700;margin:4px 0 0}
.note{font-size:18px;color:RED;font-weight:700;background:#FDECEA;border-radius:10px;
padding:10px 12px;margin:0 0 12px}
.small{font-size:16px;color:MUTED;margin:4px 0 0}
.fix{display:flex;flex-direction:column;align-items:center;justify-content:center;width:100%;
min-height:64px;margin-top:14px;border:0;border-radius:14px;background:BLUE;color:#fff;
font-size:22px;font-weight:700;cursor:pointer;padding:8px 12px;text-align:center}
.fix span{font-size:16px;font-weight:400;opacity:.95}
.fix input{position:absolute;width:1px;height:1px;opacity:0;overflow:hidden}
.skip{display:block;width:100%;min-height:56px;margin-top:6px;background:none;border:0;
color:BLUE;font-size:18px;text-decoration:underline;cursor:pointer}
.status{display:none;margin-top:14px;font-size:20px;font-weight:700;text-align:center}
.prog{height:12px;border-radius:6px;background:#E3EAF5;overflow:hidden;margin-top:8px}
.prog i{display:block;height:100%;width:0;background:BLUE}
.retry{display:none;width:100%;min-height:64px;margin-top:14px;border:3px solid RED;
border-radius:14px;background:#fff;color:RED;font-size:20px;font-weight:700}
.card[data-ui=sending] .fix,.card[data-ui=sending] .skip,.card[data-ui=failed] .fix,
.card[data-ui=failed] .skip,.card[data-ui=done] .fix,.card[data-ui=done] .skip{display:none}
.card[data-ui=sending] .status{display:block;color:NAVY}
.card[data-ui=failed] .retry{display:block}
.card[data-ui=failed] .status{display:block;color:RED;font-size:18px;font-weight:400}
.card[data-ui=done]{background:#E8F5E9;border-color:GREEN}
.card[data-ui=done] .status{display:block;color:GREEN}
.card[data-ui=done] .prog,.card[data-ui=failed] .prog{display:none}
.pid{font-size:13px;color:MUTED;margin:10px 0 0}
details{margin-top:22px}
summary{font-size:20px;font-weight:700;min-height:56px;display:flex;align-items:center;
cursor:pointer;color:GREEN}
details.closed summary{color:MUTED}
.mini{display:flex;gap:12px;align-items:center;background:#E8F5E9;border-radius:12px;padding:10px 12px;
margin-bottom:8px;border:2px solid #C8E6C9}
.mini .ok{font-size:26px;color:GREEN}
.mini p{margin:0}
.banner{font-size:20px;font-weight:700;border-radius:12px;padding:12px 14px;margin:12px 0 0}
.banner.good{background:#E8F5E9;color:GREEN}.banner.bad{background:#FDECEA;color:RED}
footer{padding:8px 16px 28px}
.wa{display:flex;align-items:center;justify-content:center;min-height:60px;border-radius:14px;
background:#fff;border:2px solid BLUE;color:BLUE;font-size:20px;font-weight:700;
text-decoration:none}
.private{font-size:16px;color:MUTED;text-align:center;margin:14px 0 0}
.powered{font-size:13px;color:MUTED;text-align:center;margin:18px 0 0;letter-spacing:.5px}
#viewer{position:fixed;inset:0;background:#000;display:none;z-index:9;touch-action:none}
#viewer.on{display:block}
#viewer img{position:absolute;left:0;top:0;width:100%;height:100%;object-fit:contain;
transform-origin:0 0;user-select:none;-webkit-user-drag:none}
#viewer .vbar{position:absolute;left:0;right:0;top:0;display:flex;justify-content:space-between;
padding:10px;gap:10px}
#viewer button{min-height:56px;padding:0 18px;border-radius:28px;border:0;background:#fff;
color:#111;font-size:20px;font-weight:700}
""")
for _k, _v in (("BRAND_FONT", BRAND_FONT), ("NAVY", NAVY), ("BLUE", BLUE), ("GREEN", GREEN),
               ("RED", RED), ("MUTED", MUTED), ("EDGE", EDGE)):
    _CSS = _CSS.replace(_k, _v)


# The page's own script, no library: the camera button sends the photo at
# once (made at most 2000 px, JPEG; a phone's HEIC that cannot be redrawn is
# sent as it is), "I fixed it" follows, the card turns green. A photo that
# cannot be sent is kept on the phone (IndexedDB) and sent again by itself
# when the signal is back, or by tapping the big red button.
_SCRIPT = r"""
(function () {
  var T = JSON.parse(document.getElementById('t').textContent);
  var MAX = 2000, DB = 'levelog-punch', ST = 'photos';
  function idb(fn) {
    return new Promise(function (ok) {
      try {
        var r = indexedDB.open(DB, 1);
        r.onupgradeneeded = function () { r.result.createObjectStore(ST); };
        r.onsuccess = function () {
          try { fn(r.result.transaction(ST, 'readwrite').objectStore(ST), ok); }
          catch (e) { ok(null); }
        };
        r.onerror = function () { ok(null); };
      } catch (e) { ok(null); }
    });
  }
  function keep(k, blob) { return idb(function (s, ok) { var q = s.put(blob, k); q.onsuccess = q.onerror = function () { ok(); }; }); }
  function kept(k) { return idb(function (s, ok) { var q = s.get(k); q.onsuccess = function () { ok(q.result || null); }; q.onerror = function () { ok(null); }; }); }
  function drop(k) { return idb(function (s, ok) { var q = s.delete(k); q.onsuccess = q.onerror = function () { ok(); }; }); }

  function shrink(file) {
    return new Promise(function (ok) {
      var url;
      try { url = URL.createObjectURL(file); } catch (e) { return ok(file); }
      var img = new Image();
      img.onload = function () {
        var w = img.naturalWidth, h = img.naturalHeight, s = Math.min(1, MAX / Math.max(w, h));
        if (s === 1 && /jpe?g$/i.test(file.type)) { URL.revokeObjectURL(url); return ok(file); }
        var c = document.createElement('canvas');
        c.width = Math.round(w * s); c.height = Math.round(h * s);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        c.toBlob(function (b) { ok(b || file); }, 'image/jpeg', 0.85);
      };
      img.onerror = function () { URL.revokeObjectURL(url); ok(file); };   // HEIC: as it is
      img.src = url;
    });
  }

  var total = +document.body.getAttribute('data-total');
  function tally() {
    var n = document.querySelectorAll('.card[data-state=open]:not([data-ui=done])').length;
    var d = total - n, bar = document.querySelector('.bar i');
    if (bar) bar.style.width = (total ? Math.round(100 * d / total) : 0) + '%';
    var c = document.querySelector('.count');
    if (c) c.textContent = T.progress.replace('{done}', d).replace('{total}', total);
    var l = document.querySelector('.left');
    if (l) l.textContent = n === 0 ? T.left_0 : n === 1 ? T.left_1 : T.left_n.replace('{n}', n);
  }

  // A finished card: green for a moment where it was, then down into
  // "Done — waiting for the GC to check (N)", folded; its floor heading goes
  // when nothing is left under it. Open and reopened ones stay on top.
  function settle(card) {
    setTimeout(function () {
      var box = document.querySelector('details.waiting');
      if (!box) return;
      var head = card.previousElementSibling;
      while (head && head.tagName !== 'H2') head = head.previousElementSibling;
      box.appendChild(card);
      box.hidden = false;
      var n = box.querySelectorAll('.card').length;
      box.querySelector('summary span').textContent = T.waiting.replace('{n}', n);
      if (head) {
        var next = head.nextElementSibling;
        if (!next || !next.classList.contains('card')) head.remove();
      }
    }, 1600);
  }

  function ui(card, state, msg) {
    card.setAttribute('data-ui', state);
    var s = card.querySelector('.status');
    if (s) s.firstChild.textContent = msg || '';
  }
  function bar(card, p) { var i = card.querySelector('.prog i'); if (i) i.style.width = p + '%'; }

  function send(card, blob) {
    var pid = card.getAttribute('data-done');
    ui(card, 'sending', blob ? T.sending : T.finishing);
    bar(card, blob ? 3 : 60);
    var up = blob ? new Promise(function (ok) {
      var x = new XMLHttpRequest();
      x.open('POST', card.getAttribute('data-up'));
      x.timeout = 120000;
      x.upload.onprogress = function (e) { if (e.lengthComputable) bar(card, 3 + 87 * e.loaded / e.total); };
      x.onload = function () { ok(x.status); };
      x.onerror = x.ontimeout = function () { ok(0); };
      var fd = new FormData(); fd.append('photo', blob, 'fix.jpg'); x.send(fd);
    }) : Promise.resolve(200);
    return up.then(function (st) {
      if (st !== 200) return st;
      bar(card, 92);
      return fetch(card.getAttribute('data-done'), { method: 'POST', body: new FormData(),
        headers: { 'Accept': 'application/json' } }).then(function (r) { return r.status; },
        function () { return 0; });
    }).then(function (st) {
      if (st === 200) {
        bar(card, 100); drop(pid); ui(card, 'done', T.done); tally(); settle(card); return;
      }
      if (st === 422) { drop(pid); ui(card, 'failed', T.bad_photo); card._blob = null; return; }
      if (st === 404 || st === 409) { drop(pid); ui(card, 'sending', T.changed); setTimeout(function () { location.reload(); }, 1500); return; }
      card._blob = blob;
      ui(card, 'failed', navigator.onLine === false ? T.offline : '');
    });
  }

  document.querySelectorAll('.card[data-state=open]').forEach(function (card) {
    var inp = card.querySelector('input[type=file]');
    // A photo kept on the phone is this link's, for this item (two jobs can
    // share an item's number; Codex review on #766): its key is the card's
    // own address, which names both.
    var pid = card.getAttribute('data-done');
    if (inp) inp.addEventListener('change', function () {
      var f = inp.files && inp.files[0];
      if (!f) return;
      ui(card, 'sending', T.sending); bar(card, 1);
      shrink(f).then(function (b) { inp.value = ''; return keep(pid, b).then(function () { return send(card, b); }); });
    });
    var sk = card.querySelector('.skip');
    if (sk) sk.addEventListener('click', function (e) { e.preventDefault(); card._skip = true; send(card, null); });
    var rt = card.querySelector('.retry');
    if (rt) rt.addEventListener('click', function () {
      if (card._blob || card._skip) return send(card, card._blob || null);
      inp && inp.click();                          // a photo we could not use: take it again
    });
    // A photo already on the server, not yet confirmed (the tab was closed
    // in between): finish it. A photo kept on the phone: send it again.
    if (card.getAttribute('data-pending') === '1') send(card, null);
    else kept(pid).then(function (b) { if (b) { card._blob = b; send(card, b); } });
  });
  window.addEventListener('online', function () {
    document.querySelectorAll('.card[data-ui=failed]').forEach(function (card) {
      if (card._blob || card._skip) send(card, card._blob || null);
    });
  });

  // The photo, full screen: pinch to zoom, drag, double-tap.
  var V = document.getElementById('viewer'), VI = V && V.querySelector('img'), list = [], at = 0;
  var sc = 1, tx = 0, ty = 0, pts = {}, start = null, lastTap = 0;
  function apply() { VI.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + sc + ')'; }
  function show(i) { at = i; sc = 1; tx = ty = 0; apply(); VI.src = list[i]; V.querySelector('.next').style.display = list.length > 1 ? '' : 'none'; }
  document.querySelectorAll('a.thumb[data-photos]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      if (!V) return;
      e.preventDefault();
      list = JSON.parse(a.getAttribute('data-photos'));
      V.classList.add('on'); show(0);
    });
  });
  if (V) {
    V.querySelector('.close').addEventListener('click', function () { V.classList.remove('on'); VI.src = ''; });
    V.querySelector('.next').addEventListener('click', function () { show((at + 1) % list.length); });
    VI.addEventListener('pointerdown', function (e) {
      VI.setPointerCapture(e.pointerId); pts[e.pointerId] = [e.clientX, e.clientY];
      var k = Object.keys(pts);
      if (k.length === 2) {
        var a = pts[k[0]], b = pts[k[1]];
        start = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), sc: sc, tx: tx, ty: ty,
                  cx: (a[0] + b[0]) / 2, cy: (a[1] + b[1]) / 2 };
      } else {
        var now = Date.now();
        if (now - lastTap < 300) { if (sc > 1) { sc = 1; tx = ty = 0; } else { sc = 2.5; tx = -1.5 * e.clientX; ty = -1.5 * e.clientY; } apply(); }
        lastTap = now; start = { x: e.clientX, y: e.clientY, tx: tx, ty: ty };
      }
    });
    VI.addEventListener('pointermove', function (e) {
      if (!pts[e.pointerId] || !start) return;
      pts[e.pointerId] = [e.clientX, e.clientY];
      var k = Object.keys(pts);
      if (k.length === 2 && start.d) {
        var a = pts[k[0]], b = pts[k[1]], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        var ns = Math.max(1, Math.min(6, start.sc * d / start.d)), r = ns / start.sc;
        tx = start.cx - (start.cx - start.tx) * r; ty = start.cy - (start.cy - start.ty) * r; sc = ns;
      } else if (k.length === 1 && sc > 1 && start.x != null) {
        tx = start.tx + e.clientX - start.x; ty = start.ty + e.clientY - start.y;
      }
      apply();
    });
    var up = function (e) { delete pts[e.pointerId]; start = null; if (sc <= 1) { sc = 1; tx = ty = 0; apply(); } };
    VI.addEventListener('pointerup', up); VI.addEventListener('pointercancel', up);
  }
})();
"""


def _thumb(r: Dict[str, Any], tok: str, lang: str) -> str:
    pid = _e(r.get("pid"))
    n = int(r.get("photos") or 0)
    if not n:
        return f'<div class="thumb">{_e(t(lang, "no_photo"))}</div>'
    full = [f"{tok}/photo/{r.get('pid')}/{i}" for i in range(1, n + 1)]
    more = f"<b>+{n - 1}</b>" if n > 1 else ""
    return (f'<a class="thumb" href="{_e(full[0])}" data-photos="{_e(json.dumps(full))}" '
            f'aria-label="{_e(t(lang, "photo_n", i=1, n=n))}">'
            f'<img alt="" loading="lazy" src="{_e(tok)}/photo/{pid}/1?thumb=1">{more}</a>')


def _open_card(r: Dict[str, Any], tok: str, lang: str, today: Any) -> str:
    pid = _e(r.get("pid"))
    note = ""
    if r.get("reopened"):
        rn = str(r.get("reopen_note") or "").strip()
        note = (f'<p class="note">{_e(t(lang, "not_fixed", note=rn))}</p>' if rn
                else f'<p class="note">{_e(t(lang, "not_fixed_bare"))}</p>')
    where = spot(r)
    due = due_flag(r, today, lang)
    preview = (f'<p class="small">{_e(t(lang, "preview"))}</p>'
               if int(r.get("photos") or 0)
               and "preview" in (r.get("qualities") or [r.get("photo_quality")]) else "")
    return (
        f'<section class="card" data-state="open" data-pid="{pid}" '
        f'data-pending="{1 if r.get("pending_photo") else 0}" '
        f'data-up="{_e(tok)}/upload/{pid}" data-done="{_e(tok)}/done/{pid}">{note}'
        f'<div class="row">{_thumb(r, tok, lang)}<div>'
        f'<p class="what">{_e(_cap(str(r.get("text") or "")))}</p>'
        + (f'<p class="where">{_e(where)}</p>' if where else "")
        + (f'<p class="due">{_e(due)}</p>' if due else "")
        + preview + '</div></div>'
        # One action: the label opens the camera; the file control itself is
        # never shown. Without the script, "Send" posts the form.
        f'<form method="post" enctype="multipart/form-data" action="{_e(tok)}/done/{pid}">'
        f'<label class="fix">{_e(t(lang, "fix"))}<span>{_e(t(lang, "fix_hint"))}</span>'
        f'<input type="file" name="photo" accept="image/*" capture="environment"></label>'
        f'<noscript><button class="fix" type="submit">{_e(t(lang, "send"))}</button></noscript>'
        f'<button class="skip" type="submit" name="skip" value="1">{_e(t(lang, "skip"))}</button>'
        f'</form>'
        f'<div class="status">​<div class="prog"><i></i></div></div>'
        f'<button class="retry" type="button">{_e(t(lang, "failed"))}</button>'
        f'<p class="pid">{pid}</p></section>')


def _mini(r: Dict[str, Any], tok: str, lang: str, mark: str) -> str:
    where = spot(r)
    return (f'<div class="mini card" data-state="{_e(r.get("status"))}" data-pid="{_e(r.get("pid"))}">'
            f'<span class="ok">{mark}</span><div><p class="what">{_e(_cap(str(r.get("text") or "")))}</p>'
            + (f'<p class="where">{_e(place(r, lang))}{" · " + _e(where) if where else ""}</p>')
            + f'<p class="pid">{_e(r.get("pid"))}</p></div></div>')


def page(*, name: str, job: str, items: Iterable[Dict[str, Any]], tok: str,
         done: Optional[str] = None, error: Optional[str] = None, lang: str = "en",
         today: Any = None, wa_url: Optional[str] = None, company: str = "") -> str:
    """The phone page, a Levelog page: the wordmark and the GC's name at the
    top, Levelog blue for what you press, green only for what is done. Their open items grouped by floor (the reopened ones
    first, with the GC's note), each one card with one big button; the ones
    done and waiting, then the closed ones, folded at the bottom."""
    lang = lang_of(lang)
    rows = list(items)
    open_ = [r for r in rows if r.get("status") == "open"]
    ready = [r for r in rows if r.get("status") == "ready_to_check"]
    closed = [r for r in rows if r.get("status") == "closed"]
    total, left = len(open_) + len(ready) + len(closed), len(open_)
    done_n = total - left
    pct = round(100 * done_n / total) if total else 0
    left_text = (t(lang, "left_0") if not left else t(lang, "left_1") if left == 1
                 else t(lang, "left_n", n=left))

    body = []
    again = [r for r in open_ if r.get("reopened")]
    rest = [r for r in open_ if not r.get("reopened")]
    body += [_open_card(r, tok, lang, today) for r in again]
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in sorted(rest, key=lambda r: (_floor_key(r.get("floor")), r.get("seq") or 0)):
        groups.setdefault(place(r, lang), []).append(r)
    for g, rs in groups.items():
        body.append(f"<h2>{_e(g)}</h2>")
        body += [_open_card(r, tok, lang, today) for r in rs]
    if not open_:
        body.append(f'<p class="left">{_e(t(lang, "nothing"))}</p>')
    # Always there (hidden while empty): a card marked done moves into it.
    body.append(f'<details class="waiting"{"" if ready else " hidden"}><summary>✅&nbsp;'
                f'<span>{_e(t(lang, "waiting", n=len(ready)))}</span></summary>'
                + "".join(_mini(r, tok, lang, "✓") for r in ready) + "</details>")
    if closed:
        body.append(f'<details class="closed"><summary>{_e(t(lang, "closed", n=len(closed)))}'
                    f'</summary>' + "".join(_mini(r, tok, lang, "✓") for r in closed) + "</details>")

    banner = ""
    if done:
        banner = f'<p class="banner good">{_e(t(lang, "thanks_banner"))}</p>'
    if error:
        banner = f'<p class="banner bad">{_e(error)}</p>'
    langs = "".join(
        f'<a href="?lang={code}" class="{"on" if code == lang else ""}" hreflang="{code}">'
        f'{_e(TEXT[code]["lang_name"])}</a>' for code in LANGS)
    hi = t(lang, "hi", name=first_name(name)) if first_name(name) else t(lang, "hi_anon")
    script_text = {k: t(lang, k) for k in ("sending", "finishing", "done", "failed", "offline",
                                             "bad_photo", "changed", "progress", "left_0",
                                             "left_1", "left_n", "waiting")}
    # "</" escaped so no string closes the <script> it sits in. Built here,
    # not inside the f-string: a backslash in an f-string expression is a
    # SyntaxError before Python 3.12.
    script_json = json.dumps(script_text).replace("</", "<\\/")
    foot = (f'<a class="wa" href="{_e(wa_url)}">{_e(t(lang, "questions"))}</a>' if wa_url else "")
    logo = (f'<img class="logo" src="{wordmark()}" alt="Levelog" width="88" height="30">'
            if wordmark() else "<b>Levelog</b>")
    gc = ""
    if str(company or "").strip():
        size, spacing = gc_sizing(company)
        gc = (f'<p class="gc" style="font-size:{size}px;letter-spacing:{spacing}px">'
              f'{_e(company)}</p>')
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">
<meta name="theme-color" content="#ffffff">
<title>{_e(job)} · Levelog</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300&display=swap">
<style>{_CSS}</style></head>
<body data-total="{total}">
<div class="top"><div class="brand">{logo}<nav class="langs">{langs}</nav></div>{gc}
<h1>{_e(hi)}</h1><p class="left">{_e(left_text)}</p><p class="addr">{_e(job)}</p>
<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="{total}" aria-valuenow="{done_n}">
<i style="width:{pct}%"></i></div><p class="count">{_e(t(lang, "progress", done=done_n, total=total))}</p>
{banner}</div>
<main>{"".join(body)}</main>
<footer>{foot}<p class="private">{_e(t(lang, "private"))}</p>
<p class="powered">{_e(t(lang, "powered"))}</p></footer>
<div id="viewer" role="dialog" aria-modal="true"><img alt="">
<div class="vbar"><button type="button" class="close">{_e(t(lang, "close"))}</button>
<button type="button" class="next">{_e(t(lang, "next"))}</button></div></div>
<script type="application/json" id="t">{script_json}</script>
<script>{_SCRIPT}</script></body></html>"""


def gone_page() -> str:
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta name='robots' content='noindex,nofollow'><title>Levelog</title></head>"
            f"<body style='font-family:system-ui;padding:24px'><p>{GONE_TEXT}</p></body></html>")
