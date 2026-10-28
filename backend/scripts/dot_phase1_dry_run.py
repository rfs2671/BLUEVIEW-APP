"""DOT Phase 1 (#852 + #853 + #855) against production data -- READ ONLY: no writes, no sends.

    railway run --service Blueview2 python backend/scripts/dot_phase1_dry_run.py [out_dir]
        [--days N] [--start 2026-10-28T06:00]

    e.g. the 21 days from Wednesday 06:00 New York (Nov 1 and Nov 12 inside):
    railway run --service Blueview2 python backend/scripts/dot_phase1_dry_run.py \
        docs/samples/dot_dry_run --days 21 --start 2026-10-28T06:00

--start is an ISO date-time (New York when it carries no offset; default now);
--days the window's length in days (default 7; any number, 21 for three
weeks). The window is printed.

(Blueview2 is the backend service the repo's other production scripts name;
add `--environment production` if the linked environment is not production.
If MONGO_URL is on Railway's private network it will not resolve from this
machine: set DOT_DRY_RUN_MONGO_URL (and DOT_DRY_RUN_DB) to the public URL.)

WHAT IT ANSWERS. For each project: every email and every WhatsApp group post
the window (--start, --days) would produce -- kind, record id (ticket /
permit number), DOT date, match tier, recipient count, flag state, and the rule
that fired. The holiday embargo, permit expiry and hearing reminders are ONE
DOT digest email per project per day, a section per kind (operator ruling
2026-10-28), and ONE DOT group post per project per day: the row is kind
"DOT digest", its `sections` column counts each section, and `why` lists every
permit / ticket in it by section with its TRUE days left. A reminder held over
Shabbos / Yom Tov says so and is listed on the day it is delivered; a
threshold the catch-up rule skips (dot_permits.catchup_skipped) sends nothing
and is counted in the job reports. Covered: the holiday embargo, permit expiry
14/3, hearing 14/7/1 (email digest + group post), summons new / pending
block-match / default-docketed, and everything else `_gc_alerts_tick` posts
(DOB kinds included, marked DOB).
DOB EMAILS are not covered: they are sent by the DOB sync, not by a scheduled
alert job, and the DOB sync is not run.

HOW. The REAL code paths, not a re-implementation:
  1. THE GUARD, installed before the application is imported (see Guard):
     every Mongo write method of motor and pymongo raises (collection,
     database and client; aggregate with $out/$merge; non-read commands);
     every outbound send is refused -- Resend, send_notification, the WhatsApp
     transports, and ANY HTTP request except a GET to data.cityofnewyork.us
     (httpx, requests, urllib, aiohttp). Every refusal is recorded and printed
     under BLOCKED CALLS; the emails and posts below are read from that record.
     The guard is shown working (a write and a POST are attempted and refused)
     before anything is read.
  2. The collections the jobs read are copied out of production on first use,
     into an in-memory database (tests/async_fake_mongo), and `server.db` is
     pointed at the copy. Every write the jobs make lands in the copy only.
  3. The AI wording is stubbed (the template is used). Nothing leaves the
     machine except the Mongo reads and GETs to NYC Open Data (public,
     read-only), cached so both runs see the same answers.
  4. The real `_dot_sync_tick` runs once, then the stipulation and NOV-link
     reads, then a clock steps through the window (America/New_York),
     running each job at its scheduled time: 07:00 the ONE DOT digest run
     (_dot_daily_digest_tick, what _dot_embargo_alert_job runs); every
     DOT_SYNC_HOURS (2 h) from the window's start, the DOT sync job as
     production runs it (_dot_sync_job: the sync, the summons record alerts,
     then the LATE check -- a permit or hearing <= 1 day away that missed
     today's digest is emailed at once, listed as "late item (<=1 day), sent
     at once"); and the GC group alerts (plus the Shabbos / Yom Tov queue)
     hourly 07:00-21:00 -- their own send windows and quiet hours still apply.
     A query a later sync repeats with only its date window moved is answered
     from the first read: the run cannot see future DOT data.
  5. Twice: with feature_flags as they are in production, and with
     dot_phase1 forced ON for every company (what turning it on would add).

The email kill switch, NOTIFICATIONS_ENABLED and RESEND_API_KEY are read from
the environment and PRINTED; the run lists what the jobs would hand to the
sender, and says so when production would currently drop it.

OUTPUT (out_dir, default docs/samples/dot_dry_run/): dry_run_rows.csv (one row
per email / post, both runs), dry_run_projects.csv (per project),
dry_run_blocked_calls.csv (every refused call), and dry_run_report.txt (the
same as printed tables). Test companies (is_test) are shown apart and not dropped:
the product leaves their projects out of every send. A project with no
confirmed DOT setup (frontages) is said to have none: its block-match and
Needs-confirmation counts are zero until someone confirms frontages.

Nothing is fabricated. A source that cannot be read stops the run and says
which; an in-memory operator the copy cannot evaluate is listed at the end.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import json
import os
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)

from probe_helpers import counted  # noqa: E402  (scripts/probe_helpers: no app imports)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── 1. THE GUARD (installed before `import server`) ─────────────────────────
#
# Operator requirements (2026-10-23), all enforced at the METHOD level:
#   * no Mongo write reaches the production client: every write method of
#     motor and pymongo (collection, database, client) raises, aggregate with
#     $out / $merge raises, a database command that is not a read raises;
#   * no outbound send: Resend, lib.notifications.send_notification, every
#     WhatsApp transport the GC / DM paths use, and ANY HTTP request other than
#     a GET to data.cityofnewyork.us (httpx sync + async, requests, urllib,
#     aiohttp). Any other host, even a GET, is refused;
#   * every refused call is RECORDED (target, method, collection or URL, a
#     short argument summary) and printed under BLOCKED CALLS. The emails and
#     posts in the report are read from that record.

NYC_HOST = "data.cityofnewyork.us"

_MONGO_WRITES = ("insert_one", "insert_many", "update_one", "update_many", "replace_one",
                 "delete_one", "delete_many", "bulk_write", "find_one_and_update",
                 "find_one_and_replace", "find_one_and_delete", "create_index", "create_indexes",
                 "create_search_index", "create_search_indexes", "drop_index", "drop_indexes",
                 "drop_search_index", "update_search_index", "drop", "rename")
_MONGO_DB_WRITES = ("create_collection", "drop_collection", "rename_collection")
_MONGO_CLIENT_WRITES = ("drop_database",)
#: Database commands that only read; any other command is refused.
_READ_COMMANDS = {"ping", "hello", "ismaster", "isMaster", "buildinfo", "buildInfo",
                  "listCollections", "listIndexes", "listDatabases", "count", "distinct",
                  "dbStats", "collStats", "serverStatus", "connectionStatus", "endSessions",
                  "killCursors", "getMore", "find"}


class DryRunBlocked(RuntimeError):
    """A write or send the dry run refused (and recorded)."""


DryRunWriteRefused = DryRunBlocked      # the name the first version used


def _summary(args, kwargs, n=140) -> str:
    try:
        s = ", ".join(repr(a)[:n] for a in args)
        if kwargs:
            s += (", " if s else "") + ", ".join(f"{k}={repr(v)[:n]}" for k, v in kwargs.items())
        return s[:3 * n]
    except Exception:
        return "?"


class Guard:
    """Installs the refusals, records every refused call, and can be removed
    (the tests install and remove it; the script never removes it)."""

    def __init__(self):
        self.blocked: List[dict] = []
        self.allowed: Dict[str, int] = {}
        self.now: Optional[datetime] = None
        self.run: str = "setup"
        self._undo: List[tuple] = []

    # bookkeeping
    def record(self, target, method, where, summary, **extra) -> dict:
        e = {"run": self.run, "at": self.now, "target": target, "method": method,
             "where": str(where), "summary": summary, **extra}
        self.blocked.append(e)
        return e

    def _patch(self, owner, name, new):
        if not hasattr(owner, name):
            return
        own = isinstance(owner, type) and name in owner.__dict__
        old = owner.__dict__[name] if own else getattr(owner, name)
        self._undo.append((owner, name, old, own or not isinstance(owner, type)))
        setattr(owner, name, new)

    def uninstall(self):
        for owner, name, old, restore in reversed(self._undo):
            if restore:
                setattr(owner, name, old)
            else:
                try:
                    delattr(owner, name)
                except AttributeError:
                    setattr(owner, name, old)
        self._undo.clear()

    # Mongo
    def _refuser(self, kind, method):
        guard = self

        def refused(this, *a, **k):
            where = getattr(this, "full_name", None) or getattr(this, "name", None) or kind
            guard.record("mongo", method, where, _summary(a, k))
            raise DryRunBlocked(f"dry run: {kind}.{method} on {where} is not allowed")
        refused.__dry_run_guard__ = True
        return refused

    def _aggregate(self, kind, original):
        guard = self

        def aggregate(this, pipeline=None, *a, **k):
            stages = [next(iter(s)) for s in (pipeline or []) if isinstance(s, dict) and s]
            if "$out" in stages or "$merge" in stages:
                where = getattr(this, "full_name", None) or getattr(this, "name", None) or kind
                guard.record("mongo", "aggregate($out/$merge)", where, _summary((pipeline,), k))
                raise DryRunBlocked(f"dry run: aggregate with $out/$merge on {where} is not allowed")
            return original(this, pipeline, *a, **k)
        aggregate.__dry_run_guard__ = True
        return aggregate

    def _command(self, kind, original):
        guard = self

        def command(this, command, *a, **k):
            name = command if isinstance(command, str) else (next(iter(command)) if command else "")
            if name not in _READ_COMMANDS:
                guard.record("mongo", f"command({name})", getattr(this, "name", kind), _summary((command,), k))
                raise DryRunBlocked(f"dry run: database command {name!r} is not allowed")
            return original(this, command, *a, **k)
        command.__dry_run_guard__ = True
        return command

    def lock_mongo(self) -> List[str]:
        done = []
        classes = []
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
            self._patch(Collection, "aggregate", self._aggregate("collection", Collection.aggregate))
            self._patch(Database, "aggregate", self._aggregate("database", Database.aggregate))
            self._patch(Database, "command", self._command("database", Database.command))
            done += ["pymongo Collection.aggregate($out/$merge)", "pymongo Database.aggregate($out/$merge)",
                     "pymongo Database.command(non-read)"]
        except Exception:
            pass
        for cls, names, kind in classes:
            for n in names:
                if hasattr(cls, n):
                    self._patch(cls, n, self._refuser(kind, n))
                    done.append(f"{cls.__module__}.{cls.__name__}.{n}")
        return done

    # HTTP
    def http_allowed(self, method, url) -> bool:
        from urllib.parse import urlparse
        host = (urlparse(str(url)).hostname or "").lower()
        return str(method).upper() == "GET" and host == NYC_HOST

    def _http_refuse(self, lib, method, url, body=None):
        self.record("http", f"{lib} {str(method).upper()}", url, (str(body)[:160] if body else ""))
        raise DryRunBlocked(f"dry run: {str(method).upper()} {url} is not allowed (only GET to {NYC_HOST})")

    def _allow(self, url):
        from urllib.parse import urlparse
        h = (urlparse(str(url)).hostname or "").lower()
        self.allowed[h] = self.allowed.get(h, 0) + 1

    def lock_http(self) -> List[str]:
        guard, done = self, []
        try:
            import httpx
            sync_send, async_send = httpx.Client.send, httpx.AsyncClient.send

            def send(this, request, *a, **k):
                if not guard.http_allowed(request.method, request.url):
                    guard._http_refuse("httpx", request.method, request.url, _body(request))
                guard._allow(request.url)
                return sync_send(this, request, *a, **k)

            async def asend(this, request, *a, **k):
                if not guard.http_allowed(request.method, request.url):
                    guard._http_refuse("httpx", request.method, request.url, _body(request))
                guard._allow(request.url)
                return await async_send(this, request, *a, **k)
            self._patch(httpx.Client, "send", send)
            self._patch(httpx.AsyncClient, "send", asend)
            done += ["httpx.Client.send", "httpx.AsyncClient.send (covers httpx.post/put/patch/delete/request)"]
        except Exception:
            pass
        try:
            import requests
            req_send = requests.Session.send

            def rsend(this, request, *a, **k):
                if not guard.http_allowed(request.method, request.url):
                    guard._http_refuse("requests", request.method, request.url, getattr(request, "body", None))
                guard._allow(request.url)
                return req_send(this, request, *a, **k)
            self._patch(requests.Session, "send", rsend)
            done.append("requests.Session.send (covers requests.post/put/patch/delete/request)")
        except Exception:
            pass
        try:
            import urllib.request as ur
            ur_open = ur.OpenerDirector.open

            def uopen(this, fullurl, data=None, *a, **k):
                if isinstance(fullurl, ur.Request):
                    method, url, body = fullurl.get_method(), fullurl.full_url, fullurl.data
                else:
                    method, url, body = ("POST" if data is not None else "GET"), fullurl, data
                if not guard.http_allowed(method, url):
                    guard._http_refuse("urllib", method, url, body)
                guard._allow(url)
                return ur_open(this, fullurl, data, *a, **k)
            self._patch(ur.OpenerDirector, "open", uopen)
            done.append("urllib.request.OpenerDirector.open (covers urlopen)")
        except Exception:
            pass
        try:
            import aiohttp
            ai_request = aiohttp.ClientSession._request

            async def arequest(this, method, str_or_url, *a, **k):
                if not guard.http_allowed(method, str_or_url):
                    guard._http_refuse("aiohttp", method, str_or_url, k.get("json") or k.get("data"))
                guard._allow(str_or_url)
                return await ai_request(this, method, str_or_url, *a, **k)
            self._patch(aiohttp.ClientSession, "_request", arequest)
            done.append("aiohttp.ClientSession._request")
        except Exception:
            pass
        # THE LOWER LAYERS, for any client that skips the ones above: boto3 /
        # botocore (R2) call urllib3 directly, and urllib3, requests and urllib
        # all end in http.client. Same rule: GET to NYC Open Data only.
        try:
            import urllib3.connectionpool as u3
            u3_urlopen = u3.HTTPConnectionPool.urlopen

            def u3open(this, method, url, *a, **k):
                full = f"{this.scheme}://{this.host}{url if str(url).startswith('/') else '/' + str(url)}"
                if not guard.http_allowed(method, full):
                    guard._http_refuse("urllib3", method, full, k.get("body") or (a[0] if a else None))
                return u3_urlopen(this, method, url, *a, **k)
            self._patch(u3.HTTPConnectionPool, "urlopen", u3open)
            done.append("urllib3.HTTPConnectionPool.urlopen (covers boto3 / botocore)")
        except Exception:
            pass
        try:
            import http.client as hc
            hc_putrequest = hc.HTTPConnection.putrequest

            def putrequest(this, method, url, *a, **k):
                scheme = "https" if isinstance(this, hc.HTTPSConnection) else "http"
                full = f"{scheme}://{this.host}{url if str(url).startswith('/') else '/' + str(url)}"
                if not guard.http_allowed(method, full):
                    guard._http_refuse("http.client", method, full)
                return hc_putrequest(this, method, url, *a, **k)
            self._patch(hc.HTTPConnection, "putrequest", putrequest)
            done.append("http.client.HTTPConnection.putrequest (every client built on it)")
        except Exception:
            pass
        return done

    # email
    def lock_email(self) -> List[str]:
        guard, done = self, []
        try:
            import resend

            def resend_send(*a, **k):
                params = a[-1] if a else k.get("params")
                to = (params or {}).get("to") if isinstance(params, dict) else None
                subj = (params or {}).get("subject") if isinstance(params, dict) else None
                guard.record("email", "resend.Emails.send", to, f"subject={subj!r}")
                raise DryRunBlocked("dry run: resend.Emails.send is not allowed")
            self._patch(resend.Emails, "send", staticmethod(resend_send))
            done.append("resend.Emails.send")
        except Exception:
            pass
        try:
            import lib.notifications as notifications

            async def send_notification(db, **kw):
                guard.record("email", "send_notification", kw.get("recipient"),
                             f"{kw.get('trigger_type')} | {str(kw.get('subject') or '')[:120]}",
                             kwargs={k: v for k, v in kw.items() if k not in ("html", "text")})
                return {"status": "dry_run_blocked"}
            self._patch(notifications, "send_notification", send_notification)
            done.append("lib.notifications.send_notification")
        except Exception:
            pass
        return done

    def install(self) -> List[str]:
        """Everything that can be locked before the application is imported."""
        return self.lock_mongo() + self.lock_http() + self.lock_email()

    # the application's own senders (after `import server`)
    def install_app(self, server) -> List[str]:
        guard, done = self, []

        def rec_async(name, ret):
            async def f(*a, **k):
                where = a[0] if a else (k.get("chat_id") or k.get("user_id") or k.get("group_id"))
                msg = a[1] if len(a) > 1 else (k.get("message") or k.get("caption") or "")
                guard.record("whatsapp", name, where, str(msg)[:140], message=msg if isinstance(msg, str) else None)
                return ret() if callable(ret) else ret
            f.__dry_run_guard__ = True
            return f
        senders = {
            "send_whatsapp_message": lambda: {"dry_run_blocked": True},
            "send_whatsapp_dm": None,
            "_waapi_post_raw": lambda: (None, None, DryRunBlocked("dry run")),
            "_waapi_post_once": lambda: (False, None, "dry run: blocked"),
            "_waapi_send_dm_paced": lambda: (False, None, "dry run: blocked"),
            "_group_post": None, "_punch_send_photo": None, "_report_deliver": None,
        }
        for name, ret in senders.items():
            if hasattr(server, name):
                self._patch(server, name, rec_async(name, ret))
                done.append(f"server.{name}")
        if hasattr(server, "send_notification"):
            import lib.notifications as notifications
            self._patch(server, "send_notification", notifications.send_notification)
            done.append("server.send_notification")

        async def no_ai(*a, **k):        # the AI wording: the template is used
            return None
        if hasattr(server, "_gc_ai_line"):
            self._patch(server, "_gc_ai_line", no_ai)
            done.append("server._gc_ai_line (stub: template wording)")
        return done

    async def self_check(self, real_db) -> List[str]:
        """Attempt one write on the PRODUCTION handle and one non-allowed HTTP
        request; both must be refused and recorded before anything is read."""
        out = []
        n = len(self.blocked)
        cfg = real_db["system_config"]
        writes = (
            ("insert_one", lambda: real_db["dot_dry_run_guard_check"].insert_one({"_id": "dry-run"})),
            ("update_one(upsert)", lambda: cfg.update_one(
                {"_id": "initial_scan_done:dot:dry-run"}, {"$set": {"value": True}}, upsert=True)),
            ("find_one_and_update", lambda: cfg.find_one_and_update(
                {"_id": "initial_scan_done:dot:dry-run"}, {"$set": {"value": True}}, upsert=True)),
        )
        for what, attempt in writes:
            try:
                res = attempt()
                if asyncio.iscoroutine(res) or isinstance(res, asyncio.Future):
                    await res
                raise SystemExit(f"GUARD FAILED: {what} on the production handle was not refused. "
                                 "Nothing was run.")
            except DryRunBlocked as e:
                out.append(f"guard OK: {e}")
        try:
            import httpx
            async with httpx.AsyncClient() as c:
                await c.post("https://example.invalid/dry-run-guard-check", json={})
            raise SystemExit("GUARD FAILED: an HTTP POST was not refused. Nothing was run.")
        except DryRunBlocked as e:
            out.append(f"guard OK: {e}")
        if len(self.blocked) - n != 4:
            raise SystemExit("GUARD FAILED: a refused call was not recorded. Nothing was run.")
        for e in self.blocked[n:]:
            e["run"] = "self-check"
        return out


def _body(request):
    try:
        return request.content[:160]
    except Exception:
        return ""


GUARD = Guard()


def lock_database() -> List[str]:
    """Kept for the first version's callers: the Mongo part of the guard."""
    return GUARD.lock_mongo()


#: Kept through the credential blanking: the database read and its overrides.
KEEP_ENV = ("MONGO_URL", "DB_NAME", "DOT_DRY_RUN_MONGO_URL", "DOT_DRY_RUN_DB")
#: Blanked by name: every send / outbound credential the backend reads (operator
#: ruling 2026-10-23) -- email, WhatsApp, push, SMS, SMTP, storage, AI, error
#: reporting -- plus anything shaped like a credential, so a key added later
#: is blanked without anyone remembering to list it here.
_CRED_PREFIXES = ("RESEND", "WAAPI_", "WHATSAPP_", "EXPO_", "PUSH", "FCM", "APNS", "TWILIO", "SMTP_",
                  "R2_", "S3_", "AWS_", "QWEN", "DEEPINFRA", "OPENAI", "GEMINI", "DM_BRAIN_API",
                  "DROPBOX_", "SENTRY_", "GOOGLE_", "OPENWEATHER", "SOCRATA_")
_CRED_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "DSN", "CREDENTIAL")
#: What production had, read BEFORE blanking (presence only, never a value).
PROD_ENV_FACTS: Dict[str, Any] = {}


def blank_send_credentials(env=None) -> List[str]:
    """Blank (set to "") every send credential in `env`, keeping KEEP_ENV.
    Returns the blanked NAMES, sorted (values are never printed)."""
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


def configure_environment() -> str:
    # DOT_DRY_RUN_MONGO_URL / DOT_DRY_RUN_DB win when set: `railway run` runs
    # on the operator's machine, and a MONGO_URL on Railway's private network
    # does not resolve there (same override as real_report_dry_run.py).
    url = os.environ.get("DOT_DRY_RUN_MONGO_URL") or os.environ.get("MONGO_URL")
    name = os.environ.get("DOT_DRY_RUN_DB") or os.environ.get("DB_NAME")
    if not url or not name:
        sys.exit("No database: MONGO_URL and DB_NAME are not set (railway run sets them), nor "
                 "DOT_DRY_RUN_MONGO_URL and DOT_DRY_RUN_DB. Nothing was read or written.")
    os.environ["MONGO_URL"], os.environ["DB_NAME"] = url, name
    from urllib.parse import urlparse
    print(f"database: {name} on {urlparse(url).hostname or '?'}  (credentials not printed)")
    PROD_ENV_FACTS["resend_key_set"] = bool(os.environ.get("RESEND_API_KEY"))
    PROD_ENV_FACTS["kill_switch"] = os.environ.get("NOTIFICATIONS_KILL_SWITCH", "")
    # BEFORE `import server`: no send credential reaches the application, so
    # even a path the guard missed has nothing to authenticate with.
    blanked = blank_send_credentials()
    print(f"blanked {len(blanked)} send credentials (names only): {', '.join(blanked) or '(none set)'}")
    os.environ["JWT_SECRET"] = "dry-run-only"          # the app needs one to import; signs nothing real
    os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
    return name


# ── 2. THE IN-MEMORY COPY ───────────────────────────────────────────────────

LIMITS: List[str] = []           # operators the copy could not evaluate
READ_ERRORS: List[str] = []      # production reads that failed (the run stops)

#: Read before any job runs, so a database that cannot be read stops the run
#: at once, before anything is reported.
CORE_COLLECTIONS = ("projects", "companies", "users", "dot_logs", "source_sync_state", "feature_flags",
                    "notification_preferences", "whatsapp_groups", "system_config")


class SourceUnreadable(SystemExit):
    pass


def _naive(v):
    """Store datetimes as Mongo returns them without tz_aware: naive UTC."""
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.astimezone(timezone.utc).replace(tzinfo=None)
    if isinstance(v, dict):
        return {k: _naive(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_naive(x) for x in v]
    return v


def _cmpable(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return v


def _matches(doc, flt) -> bool:
    from tests import async_fake_mongo as F
    flt = flt or {}
    try:
        return F.matches(_wrap_dt(doc), _wrap_dt(flt))
    except NotImplementedError as e:
        LIMITS.append(f"{e} in {json.dumps(flt, default=str)[:160]}")
        raise
    except TypeError as e:
        LIMITS.append(f"TypeError {e} in {json.dumps(flt, default=str)[:160]}")
        return False


def _wrap_dt(v):
    if isinstance(v, datetime):
        return _cmpable(v)
    if isinstance(v, dict):
        return {k: _wrap_dt(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_wrap_dt(x) for x in v]
    return v


def _set_path(doc, path, value):
    cur = doc
    parts = path.split(".")
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _get_path(doc, path, default=None):
    cur = doc
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def _apply(doc, update, inserting=False):
    update = _naive(copy.deepcopy(update))
    if not any(str(k).startswith("$") for k in update):
        keep = doc.get("_id")
        doc.clear()
        doc.update(update)
        if keep is not None:
            doc["_id"] = keep
        return
    for op, fields in update.items():
        if op == "$set":
            for k, v in fields.items():
                _set_path(doc, k, v)
        elif op == "$setOnInsert":
            if inserting:
                for k, v in fields.items():
                    _set_path(doc, k, v)
        elif op == "$unset":
            for k in fields:
                parent = _get_path(doc, k.rsplit(".", 1)[0]) if "." in k else doc
                if isinstance(parent, dict):
                    parent.pop(k.rsplit(".", 1)[-1], None)
        elif op == "$inc":
            for k, v in fields.items():
                _set_path(doc, k, (_get_path(doc, k) or 0) + v)
        elif op in ("$push", "$addToSet"):
            for k, v in fields.items():
                cur = list(_get_path(doc, k) or [])
                vals = v["$each"] if isinstance(v, dict) and "$each" in v else [v]
                for x in vals:
                    if op == "$push" or x not in cur:
                        cur.append(x)
                _set_path(doc, k, cur)
        elif op == "$pull":
            for k, v in fields.items():
                _set_path(doc, k, [x for x in (_get_path(doc, k) or []) if x != v])
        elif op in ("$max", "$min"):
            for k, v in fields.items():
                cur = _get_path(doc, k)
                if cur is None or (op == "$max" and _cmpable(v) > _cmpable(cur)) \
                        or (op == "$min" and _cmpable(v) < _cmpable(cur)):
                    _set_path(doc, k, v)
        elif op == "$currentDate":
            for k in fields:
                _set_path(doc, k, datetime.utcnow())
        else:
            LIMITS.append(f"update operator {op}")
            raise NotImplementedError(f"dry-run copy: update operator {op}")


class _Res:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class CopyCursor:
    def __init__(self, col, flt):
        self._col, self._flt = col, flt
        self._sort: List[tuple] = []
        self._skip, self._limit = 0, 0

    def sort(self, key, direction=None):
        if isinstance(key, (list, tuple)):
            self._sort = [(k, d) for k, d in key]
        else:
            self._sort = [(key, direction or 1)]
        return self

    def limit(self, n):
        self._limit = n or 0
        return self

    def skip(self, n):
        self._skip = n or 0
        return self

    async def _docs(self):
        await self._col._ensure()
        docs = [d for d in self._col.docs if _matches(d, self._flt)]
        for k, d in reversed(self._sort):
            def key(x, k=k):
                v = _cmpable(_get_path(x, k))
                return (v is None, str(type(v)), v if v is not None else 0)
            try:
                docs.sort(key=key, reverse=(d == -1))
            except TypeError:
                docs.sort(key=lambda x, k=k: str(_get_path(x, k)), reverse=(d == -1))
        docs = docs[self._skip:]
        if self._limit:
            docs = docs[:self._limit]
        return [copy.deepcopy(d) for d in docs]

    async def to_list(self, length=None, *a, **k):
        docs = await self._docs()
        return docs[:length] if length else docs

    def __aiter__(self):
        self._it = None
        return self

    async def __anext__(self):
        if self._it is None:
            self._it = iter(await self._docs())
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class CopyCollection:
    """One collection: copied from the source on first use, then in memory."""

    def __init__(self, name, source, record):
        self.name, self._source, self._record = name, source, record
        self.docs: List[dict] = []
        self.loaded = source is None
        self.writes = 0

    async def _ensure(self):
        if self.loaded:
            return
        try:
            rows = await self._source[self.name].find({}).to_list(None)
        except Exception as e:
            # A job catches its own read errors and carries on with nothing --
            # which would print a clean, EMPTY report. So the failure is kept,
            # and the run stops on it (simulate -> SourceUnreadable).
            READ_ERRORS.append(f"{self.name}: {type(e).__name__}: {str(e)[:200]}")
            raise
        self.loaded = True
        self.docs = [dict(r) for r in rows]
        self._record(self.name, len(self.docs))

    def find(self, flt=None, projection=None, **kw):
        return CopyCursor(self, flt)

    async def find_one(self, flt=None, projection=None, sort=None, **kw):
        cur = self.find(flt)
        if sort:
            cur.sort(sort)
        rows = await cur.limit(1).to_list(1)
        return rows[0] if rows else None

    async def count_documents(self, flt=None, **kw):
        return len(await self.find(flt).to_list(None))

    async def estimated_document_count(self, **kw):
        await self._ensure()
        return len(self.docs)

    async def distinct(self, key, flt=None, **kw):
        out = []
        for d in await self.find(flt).to_list(None):
            v = _get_path(d, key)
            for x in (v if isinstance(v, list) else [v]):
                if x is not None and x not in out:
                    out.append(x)
        return out

    def aggregate(self, *a, **k):
        LIMITS.append(f"aggregate on {self.name}")
        raise NotImplementedError(f"dry-run copy: aggregate on {self.name}")

    async def insert_one(self, doc, **kw):
        from bson import ObjectId
        from pymongo.errors import DuplicateKeyError
        if "_id" in doc:
            await self._ensure()
            if any(str(d.get("_id")) == str(doc["_id"]) for d in self.docs):
                raise DuplicateKeyError(f"E11000 duplicate key {doc['_id']}")
        doc.setdefault("_id", ObjectId())
        self.docs.append(_naive(copy.deepcopy(doc)))
        self.writes += 1
        return _Res(inserted_id=doc["_id"], acknowledged=True)

    async def insert_many(self, docs, **kw):
        ids = [(await self.insert_one(d)).inserted_id for d in docs]
        return _Res(inserted_ids=ids, acknowledged=True)

    async def update_one(self, flt, update, upsert=False, **kw):
        await self._ensure()
        for d in self.docs:
            if _matches(d, flt):
                _apply(d, update)
                self.writes += 1
                return _Res(matched_count=1, modified_count=1, upserted_id=None, acknowledged=True)
        if not upsert:
            return _Res(matched_count=0, modified_count=0, upserted_id=None, acknowledged=True)
        from bson import ObjectId
        doc = {k: v for k, v in (flt or {}).items() if not str(k).startswith("$") and not isinstance(v, dict)}
        doc.setdefault("_id", ObjectId())
        _apply(doc, update, inserting=True)
        self.docs.append(_naive(doc))
        self.writes += 1
        return _Res(matched_count=0, modified_count=0, upserted_id=doc["_id"], acknowledged=True)

    async def update_many(self, flt, update, upsert=False, **kw):
        await self._ensure()
        n = 0
        for d in self.docs:
            if _matches(d, flt):
                _apply(d, update)
                n += 1
        self.writes += n
        return _Res(matched_count=n, modified_count=n, upserted_id=None, acknowledged=True)

    async def replace_one(self, flt, doc, upsert=False, **kw):
        return await self.update_one(flt, doc, upsert=upsert)

    async def find_one_and_update(self, flt, update, upsert=False, return_document=None, **kw):
        before = await self.find_one(flt)
        await self.update_one(flt, update, upsert=upsert)
        if return_document:      # ReturnDocument.AFTER is truthy
            return await self.find_one({"_id": before["_id"]} if before else flt)
        return before

    async def delete_one(self, flt, **kw):
        await self._ensure()
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                self.docs.pop(i)
                self.writes += 1
                return _Res(deleted_count=1, acknowledged=True)
        return _Res(deleted_count=0, acknowledged=True)

    async def delete_many(self, flt, **kw):
        await self._ensure()
        keep = [d for d in self.docs if not _matches(d, flt)]
        n = len(self.docs) - len(keep)
        self.docs = keep
        self.writes += n
        return _Res(deleted_count=n, acknowledged=True)

    async def create_index(self, *a, **k):
        return None

    async def create_indexes(self, *a, **k):
        return []


def _fake_db_base():
    from tests.async_fake_mongo import AsyncFakeDB
    return AsyncFakeDB


class CopyDB(_fake_db_base()):
    """tests/async_fake_mongo's AsyncFakeDB, whose collections are copied from
    `source` (a read-only motor database, or anything with the same
    find().to_list()) the first time a job touches them. `source=None`: an
    empty database."""

    def __init__(self, source):
        super().__init__()
        self._source, self._c = source, {}
        self.read_log: Dict[str, int] = {}

    def _record(self, name, n):
        self.read_log[name] = n

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def __getitem__(self, name):
        if name not in self._c:
            self._c[name] = CopyCollection(name, self._source, self._record)
        return self._c[name]

    def get_collection(self, name, *a, **k):
        return self[name]

    async def list_collection_names(self, *a, **k):
        if self._source is None:
            return list(self._c)
        return await self._source.list_collection_names()


# ── 3. THE SIMULATION ───────────────────────────────────────────────────────

NY = None


def ny_tz():
    global NY
    if NY is None:
        from zoneinfo import ZoneInfo
        NY = ZoneInfo("America/New_York")
    return NY


def slots(start: datetime, days: int = 7, sync_hours: int = 2):
    """(when, [jobs]) in (start, start + days], New York wall times: the GC
    alerts hourly 07:00-21:00, the daily 07:00 run, and the DOT sync job every
    `sync_hours` from `start` (an IntervalTrigger, as production's
    DOT_SYNC_HOURS). At one instant: daily_07, then sync, then gc."""
    tz = ny_tz()
    first = start.astimezone(tz).date()
    end = start + timedelta(days=days)
    events: Dict[datetime, List[str]] = {}
    for i in range(days + 1):
        d = first + timedelta(days=i)
        for hh in range(7, 22):
            at = datetime.combine(d, time(hh, 0), tz).astimezone(timezone.utc)
            if not (start < at <= end):
                continue
            events[at] = (["daily_07"] if hh == 7 else []) + ["gc"]
    k = 1
    while start + timedelta(hours=k * sync_hours) <= end:
        at = start + timedelta(hours=k * sync_hours)
        jobs = events.setdefault(at, [])
        jobs.insert(1 if "daily_07" in jobs else 0, "sync")
        k += 1
    return sorted(events.items())


_DATE_LITERAL = re.compile(r"'\d{4}-\d{2}-\d{2}(?:T[0-9:.]+)?'")


def cached(fetch):
    cache: Dict[str, Any] = {}
    stats = {"requests": 0, "failed": 0, "cached": 0}

    async def run(dataset, params):
        # The DOT queries carry a date window ("issued since <24 months ago>")
        # that moves with the simulated day; the answer cannot (the run reads
        # today's data), so the key leaves the dates out.
        key = dataset + _DATE_LITERAL.sub("'<date>'", json.dumps(params, sort_keys=True))
        if key in cache:
            stats["cached"] += 1
            return copy.deepcopy(cache[key])
        stats["requests"] += 1
        got = await fetch(dataset, params)
        if got is None:
            stats["failed"] += 1
        cache[key] = got
        return copy.deepcopy(got)
    run.stats = stats
    return run


#: The row reason for what the post-sync late check sent (_dot_sync_job).
LATE_REASON = "late item (<=1 day), sent at once"

#: Every digest email (one kind or several) is this kind; its `sections`
#: column says what is in it.
DIGEST_ROW_KIND = "DOT digest"
SECTION_NAME = {"embargo": "Holiday embargo", "expiry": "Permit expiring", "hearing": "Hearing reminders"}

EMAIL_KIND = {
    "dot_daily_digest": DIGEST_ROW_KIND,
    "dot_embargo_waiver_missing": "embargo (no waiver)",
    "dot_permit_expiring": "permit expiry",
    "dot_hearing_reminder": "hearing reminder",
    "dot_summons_pending_hearing": "block match: confirm (hearing near)",
    "dot_summons_new": "new summons",
    "dot_summons_default": "summons default/docketed",
}


def _section_of(item: dict) -> str:
    """The digest section an email item is in (lib/dot_permits.DIGEST_KINDS)."""
    if "embargo" in item:
        return "embargo"
    return "hearing" if "hearing_date" in item else "expiry"


def _item_detail(num: str, item: dict) -> str:
    sec = _section_of(item)
    if sec == "embargo":
        return (f"{num} ({item.get('embargo')}, sent for {item.get('send_date')}; "
                f"embargo from {item.get('embargo_start')})")
    until = "hearing" if sec == "hearing" else "work end"
    return f"{num} {item.get('days_left')} day(s) to {until} {item.get('hearing_date') or item.get('work_end')}"


def _tier(row: Optional[dict]) -> str:
    if not row:
        return "n/a"
    m = row.get("match") if isinstance(row.get("match"), dict) else {}
    return str(m.get("how") or row.get("matched_by") or "n/a")


def _dot_date(row: Optional[dict], kind: str) -> str:
    if not row:
        return ""
    if row.get("record_type") == "dot_permit":
        return f"issued {str(row.get('issue_date') or '')[:10]} · work {str(row.get('work_start') or '')[:10]} - " \
               f"{str(row.get('work_end') or row.get('expiration_date') or '')[:10]}"
    if row.get("record_type") == "dot_violation":
        return f"issued {str(row.get('issued_on') or row.get('issue_date') or '')[:10]} · hearing " \
               f"{str(row.get('hearing_date') or '')[:10]}"
    return str(row.get("violation_date") or row.get("issuance_date") or row.get("expiration_date") or "")[:10]


async def simulate(server, source, *, label: str, force_flag: bool, start: datetime,
                   fetch, days: int = 7, guard: Optional["Guard"] = None) -> dict:
    """One run over a fresh in-memory copy. Returns rows (read from the
    guard's record of refused sends), per-project facts and the job reports."""
    import lib.feature_flags as feature_flags
    from lib import dot_sync, wa_alerts

    guard = guard or GUARD
    guard.run = label
    copydb = CopyDB(source)
    saved = {k: getattr(server, k) for k in ("db", "RESEND_API_KEY", "_gc_alert_text", "_quiet_enqueue",
                                             "_dot_held_release")}
    saved_env = os.environ.get("NOTIFICATIONS_KILL_SWITCH")
    real_text, real_enqueue = server._gc_alert_text, server._quiet_enqueue
    real_release = server._dot_held_release
    items_by_text: Dict[str, dict] = {}       # the group post's text -> the alert item it says
    held: Dict[str, Any] = {}                 # text -> when a Shabbos / Yom Tov hold ends
    released: Dict[int, dict] = {}            # id(guard record entry) -> the held DOT reminder it delivers
    late_sent: set = set()                    # id(guard record entry) of what a LATE check sent
    first_record = len(guard.blocked)

    async def text_and_capture(item, address, today):
        text = await real_text(item, address, today)
        items_by_text[text] = item
        return text

    async def enqueue_and_mark(spec, **kw):
        if spec.get("message"):
            held[spec["message"]] = kw.get("until")
        return await real_enqueue(spec, **kw)

    async def release_and_mark(spec, now=None):
        n = len(guard.blocked)
        try:
            return await real_release(spec, now=now)
        finally:
            for e in guard.blocked[n:]:
                released[id(e)] = spec

    reports: List[tuple] = []
    try:
        server.db = copydb
        # The ticks exit early with no key; the real key was blanked before
        # import, and send_notification / Resend are refused regardless.
        server.RESEND_API_KEY = "dry-run"
        server._gc_alert_text = text_and_capture
        server._quiet_enqueue = enqueue_and_mark
        server._dot_held_release = release_and_mark
        os.environ["NOTIFICATIONS_KILL_SWITCH"] = ""
        feature_flags.cache_invalidate()
        if force_flag:
            flags = copydb["feature_flags"]
            await flags._ensure()
            flags.docs = [d for d in flags.docs if d.get("flag") != "dot_phase1"]
            flags.docs.append({"_id": "dry-run-dot_phase1", "flag": "dot_phase1", "enabled_globally": True})
        feature_flags.cache_invalidate()

        n_err = len(READ_ERRORS)
        for name in CORE_COLLECTIONS:
            try:
                await copydb[name]._ensure()
            except Exception:
                pass
        if len(READ_ERRORS) > n_err:
            raise SourceUnreadable("Could not read production; nothing is reported:\n  "
                                   + "\n  ".join(READ_ERRORS[n_err:]))

        async def sync_job(at, first=False):
            """_dot_sync_job: the sync, the record alerts, the late checks."""
            reports.append(("sync", await server._dot_sync_tick(now=at, fetch=fetch)))
            if first:
                reports.append(("stipulations", await server._dot_stipulations_tick(now=at, fetch=fetch)))
                reports.append(("nov_links", await server._dot_nov_links_tick(now=at, fetch=fetch)))
            reports.append(("record", await server._dot_summons_record_alert_tick(now=at)))
            # The LATE check, as _dot_sync_job runs it: one email per project
            # for its items <= 1 day away, once today's digest has gone.
            n = len(guard.blocked)
            reports.append(("late", await server._dot_daily_digest_tick(now=at, late_only=True)))
            late_sent.update(id(e) for e in guard.blocked[n:])

        guard.now = start
        await sync_job(start, first=True)
        for at, jobs in slots(start, days, getattr(server, "DOT_SYNC_HOURS", 2)):
            guard.now = at
            feature_flags.cache_invalidate()
            if "daily_07" in jobs:
                # The 07:00 job (_dot_embargo_alert_job) as it now runs: ONE
                # digest per project per day, every kind in it.
                reports.append(("digest", await server._dot_daily_digest_tick(now=at)))
            if "sync" in jobs:
                await sync_job(at)
            if "gc" in jobs:
                reports.append(("gc", await server._gc_alerts_tick(now=at)))
                reports.append(("quiet_queue", await server._quiet_queue_tick(now=at)))

        if len(READ_ERRORS) > n_err:
            raise SourceUnreadable("A production read failed during the run; its answer would be incomplete, "
                                   "so nothing is reported:\n  " + "\n  ".join(READ_ERRORS[n_err:]))

        # ── rows: from the guard's record of refused sends ──────────────────
        record = guard.blocked[first_record:]
        dot_rows = await copydb.dot_logs.find({}).to_list(None)
        by_num = {(str(r.get("project_id")), str(r.get("number"))): r for r in dot_rows}
        by_raw = {(str(r.get("project_id")), str(r.get("raw_id"))): r for r in dot_rows}
        projects = {str(p["_id"]): p for p in await copydb.projects.find({}).to_list(None)}
        companies = {str(c["_id"]): c for c in await copydb.companies.find({}).to_list(None)}
        flags_on: Dict[str, bool] = {}

        async def flag_state(cid):
            if cid not in flags_on:
                feature_flags.cache_invalidate()
                flags_on[cid] = await feature_flags.is_feature_enabled(copydb, "dot_phase1", company_id=cid or None)
            return "on" if flags_on[cid] else "off"

        def company_of(cid):
            c = companies.get(cid) or {}
            return c.get("name") or cid, bool(c.get("is_test"))

        rows: List[dict] = []
        grouped: Dict[str, dict] = {}
        for e in record:
            if e["method"] != "send_notification":
                continue
            kw = e.get("kwargs") or {}
            g = grouped.setdefault(kw.get("permit_renewal_id"), {"kw": kw, "at": e["at"], "n": 0, "e": e})
            g["n"] += 1
        for lid, g in grouped.items():
            kw = g["kw"]
            md, trig = kw.get("metadata") or {}, kw.get("trigger_type")
            pid = str(md.get("project_id") or "")
            cid = str((projects.get(pid) or {}).get("company_id") or "")
            cname, is_test = company_of(cid)
            items = md.get("items")
            sections = ""
            if isinstance(items, list):          # a DIGEST: every item, by section, TRUE days left
                nums = [str(i.get("ticket") or i.get("permit") or "") for i in items]
                found = [by_num.get((pid, n)) for n in nums]
                num = " ".join(nums)
                dot_date = "; ".join(dict.fromkeys(_dot_date(r, trig) for r in found if r))
                tier = ", ".join(sorted({_tier(r) for r in found}))
                by_sec: Dict[str, List[str]] = {}
                for n, i in zip(nums, items):
                    by_sec.setdefault(_section_of(i), []).append(_item_detail(n, i))
                sections = ", ".join(f"{k} {len(v)}" for k, v in by_sec.items())
                detail = " | ".join(f"{SECTION_NAME.get(k, k)}: {'; '.join(v)}" for k, v in by_sec.items())
                why = detail if id(g["e"]) in late_sent else f"digest of {len(items)}: {detail}"
                trig_kind = DIGEST_ROW_KIND
            else:
                num = str(md.get("ticket") or md.get("permit") or "")
                row = by_num.get((pid, num))
                dot_date, tier = _dot_date(row, trig), _tier(row)
                why = {"dot_embargo_waiver_missing": f"exposed to Nov 15 - Jan 2, no stipulation 410 ({md.get('kind')})",
                       "dot_summons_pending_hearing": f"pending block match, hearing {md.get('hearing_date')} within 14 days",
                       "dot_summons_new": "own match, new to Levelog, issued by DOT within 2 days (flag dot_phase1)",
                       "dot_summons_default": f"confirmed summons changed to {md.get('result')}"}.get(trig, str(trig))
                trig_kind = EMAIL_KIND.get(trig, trig)
            if id(g["e"]) in late_sent:
                why = f"{LATE_REASON}: {why}"
            if id(g["e"]) in released:
                why += f" -- held for Shabbos/Yom Tov ({released[id(g['e'])].get('kind')}), delivered at its end"
            rows.append({"run": label, "project": (projects.get(pid) or {}).get("name") or pid, "project_id": pid,
                         "company": cname, "company_id": cid, "test_company": is_test,
                         "day": g["at"].astimezone(ny_tz()).date().isoformat(), "channel": "email",
                         "area": "DOT", "kind": trig_kind, "record": num,
                         "items": len(items) if isinstance(items, list) else 1, "sections": sections,
                         "dot_date": dot_date, "tier": tier, "recipients": g["n"],
                         "flag": await flag_state(cid), "why": why, "ledger_id": lid})
        for e in record:
            if e["method"] != "send_whatsapp_message":
                continue
            it = items_by_text.get(e.get("message") or "")
            if it is None:
                continue        # not a GC alert (a queued DM etc.): listed under BLOCKED CALLS only
            k, rec = it["kind"], it.get("rec") or {}
            pid = str(rec.get("project_id") or "")
            cid = str((projects.get(pid) or {}).get("company_id") or rec.get("company_id") or "")
            cname, is_test = company_of(cid)
            area = "DOT" if k.startswith("dot_") else "DOB"
            members = it.get("members") or [it]

            def _num(r):
                return wa_alerts.record_number(r) or str(r.get("number") or r.get("site_bin") or "")

            def _why(m):
                mk = m.get("kind") or k
                days = f", {m.get('days')} day(s) left" if m.get("days") is not None else ""
                return {"dot_violation": "new summons: own match, issued within 2 days",
                        "dot_permit": f"permit threshold ({str(m.get('item', '')).rsplit(':', 1)[-1]}){days}",
                        "dot_embargo": "embargo: exposed, no waiver",
                        "dot_hearing": f"hearing threshold ({str(m.get('item', '')).split(':hearing:')[-1]}){days}",
                        "dot_hearing_pending": "pending block match, hearing within 14 days",
                        "dot_default": f"changed to {m.get('result')}"}.get(mk, f"{mk} (existing GC alert)")
            num = " ".join(_num(m.get("rec") or {}) for m in members)
            dot_row = by_raw.get((pid, str(rec.get("raw_id")))) if area == "DOT" else None
            post_sections: Dict[str, int] = {}
            for m in members:
                post_sections[m.get("kind") or k] = post_sections.get(m.get("kind") or k, 0) + 1
            why = _why(members[0]) if len(members) == 1 else \
                f"digest of {len(members)}: " + "; ".join(f"{_num(m.get('rec') or dict())} {_why(m)}" for m in members)
            if e.get("message") in held:
                why += f" -- held for Shabbos/Yom Tov, delivered after {held[e['message']]}"
            rows.append({"run": label, "project": (projects.get(pid) or {}).get("name") or pid, "project_id": pid,
                         "company": cname, "company_id": cid, "test_company": is_test,
                         "day": e["at"].astimezone(ny_tz()).date().isoformat(), "channel": "whatsapp",
                         "area": area, "kind": k, "record": num, "items": len(members),
                         "sections": ", ".join(f"{x} {n}" for x, n in post_sections.items())
                         if it.get("members") else "",
                         "dot_date": _dot_date(dot_row or rec, k),
                         "tier": _tier(dot_row) if area == "DOT" else "n/a",
                         "recipients": 1, "flag": await flag_state(cid), "why": why,
                         "ledger_id": f"gc:{pid}:{k}:{it.get('item')}"})
        rows.sort(key=lambda r: (r["company"], r["project"], r["day"], r["channel"], r["kind"], r["record"]))

        # ── per project ─────────────────────────────────────────────────────
        facts: List[dict] = []
        for pid, p in projects.items():
            if p.get("is_deleted") or p.get("marked_for_deletion"):
                continue
            cid = str(p.get("company_id") or "")
            cname, is_test = company_of(cid)
            setup = p.get("dot_setup") if isinstance(p.get("dot_setup"), dict) else {}
            fronts = dot_sync.confirmed_frontages(setup)
            mine = [r for r in dot_rows if str(r.get("project_id")) == pid]
            try:
                n_rec = len(await server._critical_dob_alert_recipients(p))
            except Exception:
                n_rec = None
            pr = [r for r in rows if r["project_id"] == pid]
            kinds: Dict[str, int] = {}
            for r in pr:
                kinds[f"{r['channel']}/{r['kind']}"] = kinds.get(f"{r['channel']}/{r['kind']}", 0) + 1
            facts.append({
                "run": label, "company": cname, "company_id": cid, "test_company": is_test,
                "project": p.get("name") or pid, "project_id": pid,
                "dot_setup": (f"confirmed, {len(fronts)} frontage(s)" if fronts else
                              f"none confirmed (status {setup.get('status') or 'unset'}): block matches and "
                              f"Needs confirmation are zero until frontages are confirmed"),
                # Counted through scripts/probe_helpers: a field the rows do not
                # carry raises instead of reading as a confident zero.
                "summonses": counted(mine, "record_type", lambda v: v == "dot_violation") if mine else 0,
                "permits": counted(mine, "record_type", lambda v: v == "dot_permit") if mine else 0,
                "pending": sum(1 for r in mine if dot_sync.match_state(r) == dot_sync.STATE_NEEDS),
                "rejected": sum(1 for r in mine if dot_sync.match_state(r) == dot_sync.STATE_REJECTED),
                "email_recipients": n_rec, "flag": await flag_state(cid),
                "emails": counted(pr, "channel", lambda v: v == "email") if pr else 0,
                "posts": counted(pr, "channel", lambda v: v == "whatsapp") if pr else 0,
                "by_kind": "; ".join(f"{k}: {n}" for k, n in sorted(kinds.items())),
            })
        facts.sort(key=lambda f: (f["test_company"], f["company"], f["project"]))
        return {"rows": rows, "projects": facts, "reports": reports, "read": dict(copydb.read_log),
                "record": record}
    finally:
        for k, v in saved.items():
            setattr(server, k, v)
        if saved_env is None:
            os.environ.pop("NOTIFICATIONS_KILL_SWITCH", None)
        else:
            os.environ["NOTIFICATIONS_KILL_SWITCH"] = saved_env
        feature_flags.cache_invalidate()


ROW_FIELDS = ["run", "company", "test_company", "project", "day", "channel", "area", "kind", "items", "sections",
              "record",
              "dot_date", "tier", "recipients", "flag", "why", "project_id", "company_id", "ledger_id"]
PROJECT_FIELDS = ["run", "company", "test_company", "project", "dot_setup", "summonses", "permits",
                  "pending", "rejected", "email_recipients", "flag", "emails", "posts", "by_kind",
                  "project_id", "company_id"]


def write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def table(rows, fields) -> str:
    if not rows:
        return "  (none)\n"
    widths = {f: min(max(len(f), *(len(str(r.get(f, ""))) for r in rows)), 60) for f in fields}
    line = "  " + " | ".join(f.ljust(widths[f]) for f in fields)
    out = [line, "  " + "-+-".join("-" * widths[f] for f in fields)]
    for r in rows:
        out.append("  " + " | ".join(str(r.get(f, ""))[:60].ljust(widths[f]) for f in fields))
    return "\n".join(out) + "\n"


def render(runs: List[dict], env_notes: List[str]) -> str:
    out = ["DOT PHASE 1 DRY RUN (#852 + #853 + #855, one DOT digest a day) -- read only; nothing was "
           "written or sent", ""]
    out += env_notes + [""]
    for run in runs:
        label = run["label"]
        rows, facts = run["rows"], run["projects"]
        out.append(f"=== RUN: {label} ===")
        out.append(f"read from production (collection: documents): "
                   + ", ".join(f"{k}: {v}" for k, v in sorted(run["read"].items())))
        out.append(f"NYC Open Data: {run['fetch']}")
        sync = next((r for n, r in run["reports"] if n == "sync"), {})
        out.append(f"sync: {json.dumps(sync, default=str)}")
        out.append("")
        for test in (False, True):
            part = [r for r in rows if r["test_company"] == test]
            pf = [f for f in facts if f["test_company"] == test]
            head = ("REAL COMPANIES" if not test else
                    "TEST COMPANIES (is_test): the product sends nothing for these projects; shown, not dropped")
            out.append(f"--- {head} ---")
            companies = sorted({f["company"] for f in pf} | {r["company"] for r in part})
            for c in companies:
                out.append(f"company: {c}")
                out.append(table([f for f in pf if f["company"] == c],
                                 ["project", "dot_setup", "summonses", "permits", "pending", "email_recipients",
                                  "flag", "emails", "posts"]))
                cr = [r for r in part if r["company"] == c]
                out.append(table(cr, ["project", "day", "channel", "area", "kind", "items", "sections", "record",
                                      "dot_date", "tier", "recipients", "flag", "why"]))
            out.append("")
        n_mail = counted(rows, "channel", lambda v: v == "email") if rows else 0
        n_post = counted(rows, "channel", lambda v: v == "whatsapp") if rows else 0
        out.append(f"total: {n_mail} emails, {n_post} WhatsApp posts")
        out.append("")
    if LIMITS:
        out.append("THE IN-MEMORY COPY COULD NOT EVALUATE (the job saw an error there; its answer may be "
                   "incomplete):")
        out += [f"  {x}" for x in sorted(set(LIMITS))]
    return "\n".join(out) + "\n"


def blocked_calls(record: List[dict]) -> List[str]:
    """Every refused call, one line each: when, run, target, method, where,
    a short summary."""
    out = []
    for e in record:
        at = e["at"].astimezone(ny_tz()).strftime("%Y-%m-%d %H:%M") if isinstance(e.get("at"), datetime) else "-"
        summary = " / ".join(str(e.get("summary") or "").split("\n"))
        out.append(f"  {at} | {e.get('run')} | {e['target']} | {e['method']} | {e['where']} | "
                   f"{summary[:140]}")
    return out


async def run_all(server, source, out_dir: str, *, fetch, start: Optional[datetime] = None,
                  days: int = 7, env_notes: Optional[List[str]] = None,
                  guard: Optional["Guard"] = None) -> dict:
    guard = guard or GUARD
    start = start or datetime.now(timezone.utc)
    fetch = cached(fetch)
    runs = []
    for label, force in (("flags as in production", False), ("dot_phase1 forced ON for every company", True)):
        got = await simulate(server, source, label=label, force_flag=force, start=start, fetch=fetch,
                             days=days, guard=guard)
        got["label"] = label
        got["fetch"] = dict(fetch.stats)
        runs.append(got)
    os.makedirs(out_dir, exist_ok=True)
    write_csv(os.path.join(out_dir, "dry_run_rows.csv"), ROW_FIELDS, [r for x in runs for r in x["rows"]])
    write_csv(os.path.join(out_dir, "dry_run_projects.csv"), PROJECT_FIELDS, [r for x in runs for r in x["projects"]])
    notes = list(env_notes or []) + [
        window_line(start, days) + "; jobs at their scheduled hours",
        f"network allowed (GET only): {json.dumps(guard.allowed)}"]
    text = render(runs, notes)
    text += "\nBLOCKED CALLS (refused and recorded; none was executed)\n"
    text += "\n".join(blocked_calls(guard.blocked)) + "\n"
    text += f"  total refused: {len(guard.blocked)}\n"
    with open(os.path.join(out_dir, "dry_run_report.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    write_csv(os.path.join(out_dir, "dry_run_blocked_calls.csv"),
              ["run", "at", "target", "method", "where", "summary"], guard.blocked)
    return {"runs": runs, "text": text}


def window_line(start: datetime, days: int) -> str:
    tz = ny_tz()
    end = start + timedelta(days=days)
    return (f"window: {start.astimezone(tz):%a %Y-%m-%d %H:%M} -> {end.astimezone(tz):%a %Y-%m-%d %H:%M} "
            f"New York ({days} days)")


def parse_start(value: Optional[str]) -> datetime:
    """--start: an ISO date-time; New York when it carries no offset; now when
    not given. Returned in UTC."""
    if not value:
        return datetime.now(timezone.utc)
    v = value.strip()
    if v.endswith(("Z", "z")):
        v = v[:-1] + "+00:00"
    try:
        at = datetime.fromisoformat(v)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--start {value!r}: not an ISO date-time (e.g. 2026-10-28T06:00 or 2026-10-28T06:00-04:00)")
    if at.tzinfo is None:
        at = at.replace(tzinfo=ny_tz())
    return at.astimezone(timezone.utc)


def env_notes() -> List[str]:
    from lib import notifications
    # Read before the credentials were blanked (configure_environment).
    ks = PROD_ENV_FACTS.get("kill_switch", os.environ.get("NOTIFICATIONS_KILL_SWITCH", ""))
    return [f"RESEND_API_KEY set in production's environment: {PROD_ENV_FACTS.get('resend_key_set')}"
            f" (blanked for this run)",
            f"NOTIFICATIONS_KILL_SWITCH in production's environment: {ks!r}"
            f" (on means production would send NO email right now)",
            f"NOTIFICATIONS_ENABLED in this environment: {getattr(notifications, 'NOTIFICATIONS_ENABLED', None)}",
            "The run lists what the jobs hand to the sender with the kill switch off."]


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Read-only dry run of DOT Phase 1 alerts against production.")
    ap.add_argument("out_dir", nargs="?",
                    default=os.path.join(BACKEND, "..", "docs", "samples", "dot_dry_run"))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--start", type=parse_start, default=None,
                    help="ISO date-time the window starts at; New York when no offset is given; default now")
    args = ap.parse_args(argv)
    if args.start is None:
        args.start = parse_start(None)
    return args


async def main(args):
    configure_environment()
    print(window_line(args.start, args.days))
    locked = GUARD.install()                       # BEFORE the application is imported
    import server                                  # noqa: E402  (after the guard, on purpose)
    import logging
    # The jobs log a line per run per slot; the report below carries their
    # results. Warnings and errors still print.
    logging.getLogger("server").setLevel(logging.WARNING)
    locked += GUARD.install_app(server)
    print(f"guard: {len(locked)} methods replaced:")
    print("  " + "\n  ".join(locked))
    for line in await GUARD.self_check(server.db):
        print(line)
    prod = server.db                               # the READ handle

    async def live_fetch(dataset, params):
        return await server._dot_fetch(dataset, params)

    got = await run_all(server, prod, os.path.abspath(args.out_dir), fetch=live_fetch,
                        start=args.start, days=args.days, env_notes=env_notes())
    print(got["text"])
    print(f"wrote {os.path.abspath(args.out_dir)}: dry_run_rows.csv, dry_run_projects.csv, "
          f"dry_run_blocked_calls.csv, dry_run_report.txt")


if __name__ == "__main__":
    asyncio.run(main(parse_args(sys.argv[1:])))
