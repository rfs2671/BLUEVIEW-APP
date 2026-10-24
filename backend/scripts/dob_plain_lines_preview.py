"""The Compliance card's plain one-liner for 10 real 588 Thomas S Boyland records,
with the production model and config -- READ ONLY: no writes, no sends.

    $env:PYTHONUTF8 = "1"
    railway run --service Blueview2 --environment production python backend/scripts/dob_plain_lines_preview.py

WHAT IT ANSWERS. For each of the ten records the PR description lists (BINs
3255362 and 3430621, plus the lot's 311 complaints): record id | DOB text | the
line (EN / ES) | source (code / llm / fallback) | the checker's verdict and
reason. A record with a specific code gets the table line and the model is NOT
asked; a free-text record is put to the model exactly as the background sweep
would put it (lib/dob_plain_lines.plan_line with server._dob_plain_line_llm),
and the checker's verdict is printed whether it passed or not, with the
refused line beside it.

WHERE THE RECORDS COME FROM. NYC Open Data, by id, with GETs (the datasets the
DOB sync and the 311 poll read: eabe-havv, 6bgk-3dad, erm2-nwe9). They are
turned into rows by the sync's own extractors. The database is never read.

THE GUARD, installed before the application is imported (the pattern of
backend/scripts/dot_phase1_dry_run.py on feat/dot-phase1-dry-run):
  * every send credential is blanked EXCEPT the model's: QWEN_API_KEY,
    QWEN_API_BASE and QWEN_MODEL are kept, everything else shaped like a key,
    token, secret or password is set to "";
  * MONGO_URL points at an address nothing listens on, AND every Mongo write
    method of motor and pymongo raises (the vision meter's one counter write
    is refused and listed below; the meter never raises, so the call goes on);
  * every HTTP request is refused except a GET to data.cityofnewyork.us and a
    POST to {QWEN_API_BASE}/chat/completions;
  * Resend, send_notification and the WhatsApp senders are refused.
Both refusals are shown working before anything is fetched. Every refused
call is printed under BLOCKED CALLS.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

NYC_HOST = "data.cityofnewyork.us"

# The ten records of the PR description, by dataset.
DOB_COMPLAINTS = ["3A41175", "3A42423", "3A67877", "3A78809"]      # eabe-havv
ECB_SUMMONSES = ["39189039M", "39558662P", "39558663R"]            # 6bgk-3dad
COMPLAINTS_311 = ["69457635", "68989980", "69454546"]              # erm2-nwe9

_MONGO_WRITES = ("insert_one", "insert_many", "update_one", "update_many", "replace_one",
                 "delete_one", "delete_many", "bulk_write", "find_one_and_update",
                 "find_one_and_replace", "find_one_and_delete", "create_index", "create_indexes",
                 "drop_index", "drop_indexes", "drop", "rename")
_MONGO_DB_WRITES = ("create_collection", "drop_collection", "rename_collection")
_MONGO_CLIENT_WRITES = ("drop_database",)
KEEP_ENV = ("QWEN_API_KEY", "QWEN_API_BASE", "QWEN_MODEL")
_CRED_PREFIXES = ("RESEND", "WAAPI_", "WHATSAPP_", "EXPO_", "PUSH", "FCM", "APNS", "TWILIO", "SMTP_",
                  "R2_", "S3_", "AWS_", "DEEPINFRA", "OPENAI", "GEMINI", "DM_BRAIN_API",
                  "DROPBOX_", "SENTRY_", "GOOGLE_", "OPENWEATHER", "SOCRATA_", "DASHSCOPE")
_CRED_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "DSN", "CREDENTIAL")


class PreviewBlocked(RuntimeError):
    """A write or send the preview refused (and recorded)."""


class Guard:
    """Installs the refusals and records every refused call."""

    def __init__(self, llm_url: str = ""):
        self.llm_url = llm_url.rstrip("/")
        self.blocked: List[Dict[str, str]] = []
        self.allowed: Dict[str, int] = {}
        self._undo: List[tuple] = []

    def record(self, target: str, method: str, where: Any, summary: str = "") -> None:
        self.blocked.append({"target": target, "method": method, "where": str(where),
                             "summary": summary[:160]})

    def _patch(self, owner, name, new):
        if not hasattr(owner, name):
            return
        self._undo.append((owner, name, owner.__dict__.get(name, getattr(owner, name))))
        setattr(owner, name, new)

    def uninstall(self):
        for owner, name, old in reversed(self._undo):
            setattr(owner, name, old)
        self._undo.clear()

    # Mongo
    def _refuser(self, kind, method):
        guard = self

        def refused(this, *a, **k):
            where = getattr(this, "full_name", None) or getattr(this, "name", None) or kind
            guard.record("mongo", method, where)
            raise PreviewBlocked(f"preview: {kind}.{method} on {where} is not allowed")
        return refused

    def lock_mongo(self) -> List[str]:
        done, classes = [], []
        try:
            from motor.motor_asyncio import (AsyncIOMotorClient, AsyncIOMotorCollection,
                                             AsyncIOMotorDatabase)
            classes += [(AsyncIOMotorCollection, _MONGO_WRITES, "collection"),
                        (AsyncIOMotorDatabase, _MONGO_DB_WRITES, "database"),
                        (AsyncIOMotorClient, _MONGO_CLIENT_WRITES, "client")]
        except Exception:
            pass
        try:
            from pymongo import MongoClient
            from pymongo.collection import Collection
            from pymongo.database import Database
            classes += [(Collection, _MONGO_WRITES, "collection"), (Database, _MONGO_DB_WRITES, "database"),
                        (MongoClient, _MONGO_CLIENT_WRITES, "client")]
        except Exception:
            pass
        for cls, names, kind in classes:
            for n in names:
                if hasattr(cls, n):
                    self._patch(cls, n, self._refuser(kind, n))
                    done.append(f"{cls.__module__}.{cls.__name__}.{n}")
        return done

    # HTTP
    def http_allowed(self, method: Any, url: Any) -> bool:
        m, u = str(method).upper(), str(url)
        host = (urlparse(u).hostname or "").lower()
        if m == "GET" and host == NYC_HOST:
            return True
        return bool(self.llm_url) and m == "POST" and u.split("?")[0] == f"{self.llm_url}/chat/completions"

    def _check(self, lib, method, url):
        if not self.http_allowed(method, url):
            self.record("http", f"{lib} {str(method).upper()}", url)
            raise PreviewBlocked(f"preview: {str(method).upper()} {url} is not allowed")
        host = (urlparse(str(url)).hostname or "").lower()
        self.allowed[host] = self.allowed.get(host, 0) + 1

    def lock_http(self) -> List[str]:
        guard, done = self, []
        try:
            import httpx
            sync_cls, async_cls = getattr(httpx, "Client"), getattr(httpx, "AsyncClient")
            sync_send, async_send = sync_cls.send, async_cls.send

            def send(this, request, *a, **k):
                guard._check("httpx", request.method, request.url)
                return sync_send(this, request, *a, **k)

            async def asend(this, request, *a, **k):
                guard._check("httpx", request.method, request.url)
                return await async_send(this, request, *a, **k)
            self._patch(sync_cls, "send", send)
            self._patch(async_cls, "send", asend)
            done.append("httpx sync + async send")
        except Exception:
            pass
        try:
            import requests
            req_send = requests.Session.send

            def rsend(this, request, *a, **k):
                guard._check("requests", request.method, request.url)
                return req_send(this, request, *a, **k)
            self._patch(requests.Session, "send", rsend)
            done.append("requests.Session.send")
        except Exception:
            pass
        try:
            import urllib.request as ur
            ur_open = ur.OpenerDirector.open

            def uopen(this, fullurl, data=None, *a, **k):
                if isinstance(fullurl, ur.Request):
                    method, url = fullurl.get_method(), fullurl.full_url
                else:
                    method, url = ("POST" if data is not None else "GET"), fullurl
                guard._check("urllib", method, url)
                return ur_open(this, fullurl, data, *a, **k)
            self._patch(ur.OpenerDirector, "open", uopen)
            done.append("urllib.request.OpenerDirector.open")
        except Exception:
            pass
        try:
            import aiohttp
            ai_request = aiohttp.ClientSession._request

            async def arequest(this, method, str_or_url, *a, **k):
                guard._check("aiohttp", method, str_or_url)
                return await ai_request(this, method, str_or_url, *a, **k)
            self._patch(aiohttp.ClientSession, "_request", arequest)
            done.append("aiohttp.ClientSession._request")
        except Exception:
            pass
        try:
            import http.client as hc
            hc_putrequest = hc.HTTPConnection.putrequest

            def putrequest(this, method, url, *a, **k):
                scheme = "https" if isinstance(this, hc.HTTPSConnection) else "http"
                path = url if str(url).startswith("/") else "/" + str(url)
                guard._check("http.client", method, f"{scheme}://{this.host}{path}")
                return hc_putrequest(this, method, url, *a, **k)
            self._patch(hc.HTTPConnection, "putrequest", putrequest)
            done.append("http.client.HTTPConnection.putrequest")
        except Exception:
            pass
        return done

    # email + WhatsApp
    def lock_sends(self) -> List[str]:
        guard, done = self, []
        try:
            import resend

            def resend_send(*a, **k):
                guard.record("email", "resend.Emails.send", "")
                raise PreviewBlocked("preview: resend.Emails.send is not allowed")
            self._patch(resend.Emails, "send", staticmethod(resend_send))
            done.append("resend.Emails.send")
        except Exception:
            pass
        try:
            import lib.notifications as notifications

            async def send_notification(db, **kw):
                guard.record("email", "send_notification", kw.get("recipient"))
                return {"status": "preview_blocked"}
            self._patch(notifications, "send_notification", send_notification)
            done.append("lib.notifications.send_notification")
        except Exception:
            pass
        return done

    def lock_app(self, server) -> List[str]:
        guard, done = self, []

        def refuse(name):
            async def f(*a, **k):
                guard.record("whatsapp", name, a[0] if a else "")
                raise PreviewBlocked(f"preview: {name} is not allowed")
            return f
        for name in ("send_whatsapp_message", "send_whatsapp_dm", "_waapi_post_raw",
                     "_waapi_post_once", "_waapi_send_dm_paced", "_group_post", "send_notification"):
            if hasattr(server, name):
                self._patch(server, name, refuse(name))
                done.append(f"server.{name}")
        return done

    async def self_check(self, server) -> List[str]:
        """One write on the application's database handle and one POST to a
        host that is not the model: both must be refused and recorded."""
        out, n = [], len(self.blocked)
        try:
            await server.db["dob_plain_lines_preview_guard_check"].insert_one({"_id": "preview"})
            raise SystemExit("GUARD FAILED: a Mongo write was not refused. Nothing was run.")
        except PreviewBlocked as e:
            out.append(f"guard OK: {e}")
        try:
            async with server.ServerHttpClient(timeout=5.0) as c:
                await c.post("https://example.invalid/preview-guard-check", json={})
            raise SystemExit("GUARD FAILED: an HTTP POST was not refused. Nothing was run.")
        except PreviewBlocked as e:
            out.append(f"guard OK: {e}")
        if len(self.blocked) - n != 2:
            raise SystemExit("GUARD FAILED: a refused call was not recorded. Nothing was run.")
        return out


def blank_send_credentials(env=None) -> List[str]:
    """Blank every send credential in `env` except KEEP_ENV. Names only."""
    env = os.environ if env is None else env
    blanked = []
    for k in list(env):
        if k in KEEP_ENV:
            continue
        u = k.upper()
        if u.startswith(_CRED_PREFIXES) or any(w in u for w in _CRED_WORDS):
            if env.get(k):
                blanked.append(k)
            env[k] = ""
    return sorted(blanked)


def configure_environment() -> None:
    if not (os.environ.get("QWEN_API_KEY") or "").strip():
        sys.exit("QWEN_API_KEY is not set: run this under `railway run` (production). Nothing was run.")
    blanked = blank_send_credentials()
    print(f"blanked {len(blanked)} send credentials (names only): {', '.join(blanked) or '(none set)'}")
    print("kept: QWEN_API_KEY (set), QWEN_API_BASE, QWEN_MODEL")
    # No database is read. An address nothing listens on, so the application
    # imports without a connection to production existing at all.
    os.environ["MONGO_URL"] = "mongodb://127.0.0.1:9/?serverSelectionTimeoutMS=200"
    os.environ["DB_NAME"] = "dob_plain_lines_preview"
    os.environ["JWT_SECRET"] = "preview-only"
    os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")


async def _socrata(server, dataset: str, field: str, ids: List[str]) -> List[dict]:
    quoted = ",".join("'" + i.replace("'", "") + "'" for i in ids)
    async with server.ServerHttpClient(timeout=60.0) as c:
        resp = await c.get(f"https://{NYC_HOST}/resource/{dataset}.json",
                           params={"$where": f"{field} in ({quoted})", "$limit": "50"})
    if resp.status_code != 200:
        raise SystemExit(f"{dataset}: HTTP {resp.status_code}. Nothing was invented; stopping.")
    rows = resp.json()
    found = {str(r.get(field)) for r in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        print(f"NOTE: {dataset} returned no row for {', '.join(missing)}")
    return rows


async def fetch_rows(server) -> List[dict]:
    rows: List[dict] = []
    now = datetime.now(timezone.utc)
    for rec in await _socrata(server, "eabe-havv", "complaint_number", DOB_COMPLAINTS):
        rec["_dataset"] = "eabe-havv"
        rows.append({"record_type": "complaint", "dataset": "eabe-havv",
                     "raw_dob_id": rec["complaint_number"], "bin": rec.get("bin"),
                     **server._extract_complaint_fields(rec)})
    for rec in await _socrata(server, "6bgk-3dad", "ecb_violation_number", ECB_SUMMONSES):
        rec["_dataset"] = "6bgk-3dad"
        rec["_record_type"] = "violation"
        rows.append({"record_type": "violation", "dataset": "6bgk-3dad",
                     "raw_dob_id": rec["ecb_violation_number"], "bin": rec.get("bin"),
                     **server._extract_violation_fields(rec)})
    project = {"_id": "preview", "company_id": "", "nyc_bin": "3255362"}
    for rec in await _socrata(server, "erm2-nwe9", "unique_key", COMPLAINTS_311):
        doc = server._build_311_doc(rec, project, now)
        doc["bin"] = "(311, BBL 3035400025)"
        rows.append(doc)
    return rows


async def preview(server) -> List[Dict[str, str]]:
    from lib import dob_plain_lines as L
    out = []
    for row in await fetch_rows(server):
        errors: List[str] = []

        async def llm(prompt, r):
            try:
                return await server._dob_plain_line_llm(prompt, r)
            except Exception as e:
                errors.append(f"{type(e).__name__}: {e}")
                raise
        asked = L.needs_model(row)
        fields, _called = await L.plan_line(row, llm=llm if asked else None, model=server.QWEN_MODEL)
        while asked and fields and set(fields) == {"plain_line_llm_tries"}:
            fields, _called = await L.plan_line({**row, **fields}, llm=llm, model=server.QWEN_MODEL)
        fields = fields or {}
        chk = fields.get("plain_line_check")
        if not asked:
            verdict = "n/a: code table, model not asked" if fields.get("plain_line_source") == "code" \
                else "n/a: no free text, model not asked"
        elif isinstance(chk, dict) and errors and not fields.get("plain_line_llm_raw"):
            verdict = "MODEL NOT REACHED (no line to check): " + "; ".join(errors)
        elif isinstance(chk, dict):
            verdict = ("PASS" if chk.get("ok") else "REJECT") + f": {chk.get('reason')}"
            raw = fields.get("plain_line_llm_raw")
            if not chk.get("ok") and raw:
                verdict += f" | refused line: {raw}"
        else:
            verdict = "model not reached: " + "; ".join(errors)
        line = fields.get("plain_line") or {}
        out.append({"id": str(row.get("raw_dob_id")), "bin": str(row.get("bin") or ""),
                    "text": L.dob_text(row), "en": line.get("en", ""), "es": line.get("es", ""),
                    "source": str(fields.get("plain_line_source") or ""), "verdict": verdict})
    return out


def print_table(rows: List[Dict[str, str]]) -> None:
    print("\nrecord id | DOB text | line (EN / ES) | source | checker verdict + reason")
    print("-" * 100)
    for r in rows:
        print(f"{r['id']} (BIN {r['bin']}) | {r['text']} | EN: {r['en']} / ES: {r['es']} | "
              f"{r['source']} | {r['verdict']}")


async def main() -> None:
    configure_environment()
    llm_base = (os.environ.get("QWEN_API_BASE") or "").strip()
    from lib.vision_model import vision_api_base
    guard = Guard(llm_url=vision_api_base() if not llm_base else llm_base.rstrip("/"))
    installed = guard.lock_mongo() + guard.lock_http() + guard.lock_sends()
    import server
    installed += guard.lock_app(server)
    guard.llm_url = server.QWEN_API_BASE.rstrip("/")
    print(f"guard installed on {len(installed)} methods; model {server.QWEN_MODEL} at "
          f"{urlparse(server.QWEN_API_BASE).hostname}")
    for line in await guard.self_check(server):
        print(line)
    rows = await preview(server)
    print_table(rows)
    print("\nBLOCKED CALLS (refused and recorded):")
    for b in guard.blocked:
        print(f"  {b['target']:8} {b['method']:28} {b['where']}")
    print("ALLOWED HOSTS: " + ", ".join(f"{h} x{n}" for h, n in sorted(guard.allowed.items())))
    print("Nothing was written and nothing was sent.")


if __name__ == "__main__":
    asyncio.run(main())
