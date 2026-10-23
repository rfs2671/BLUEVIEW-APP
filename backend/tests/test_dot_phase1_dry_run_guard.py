"""The DOT Phase 1 dry run's guard: nothing reaches production, nothing is sent.

backend/scripts/dot_phase1_dry_run.py runs the real jobs against a copy of
production. The operator's requirements (2026-10-23): no Mongo write may reach
the production client, no send may leave the machine, the only network is a
GET to data.cityofnewyork.us -- and every refused call is RECORDED.

Each path below has a spy installed as its UNDERLYING implementation first;
the guard is installed over it. Every attempt must be refused, recorded, and
must never reach the spy.

CONTROL: run with DOT_DRY_RUN_GUARD_OFF=1 and the guard is not installed --
every test here fails (the writes and sends reach their spies, nothing is
refused or recorded).
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import httpx  # noqa: E402
import requests  # noqa: E402
import resend  # noqa: E402
import urllib.request  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection  # noqa: E402
from pymongo import MongoClient  # noqa: E402
from pymongo.collection import Collection  # noqa: E402

import lib.notifications as notifications  # noqa: E402
import server  # noqa: E402
from scripts import dot_phase1_dry_run as D  # noqa: E402

GUARD_OFF = os.environ.get("DOT_DRY_RUN_GUARD_OFF") == "1"
WRITES = ("insert_one", "update_one", "find_one_and_update", "bulk_write", "replace_one",
          "insert_many", "update_many", "delete_one", "delete_many", "find_one_and_replace",
          "find_one_and_delete", "create_index", "drop", "rename")


def _run(coro):
    return asyncio.run(coro)


class _Spied(unittest.TestCase):
    """Spies as the underlying implementations, then the guard over them."""

    def setUp(self):
        self.spies = {}
        self._patches = []

        def spy(owner, name, key=None, **kw):
            m = MagicMock(name=key or name, **kw)
            p = patch.object(owner, name, m)
            p.start()
            self._patches.append(p)
            self.spies[key or name] = m
            return m

        for w in WRITES:
            spy(Collection, w, f"pymongo.{w}")
        spy(AsyncIOMotorCollection, "insert_one", "motor.insert_one")
        spy(resend.Emails, "send", "resend.Emails.send")

        async def _async_none(*a, **k):
            self.spies["async_calls"].append((a, k))
        self.spies["async_calls"] = []
        for name in ("send_whatsapp_message", "send_whatsapp_dm", "_waapi_post_raw"):
            p = patch.object(server, name, _async_none)
            p.start()
            self._patches.append(p)
        p = patch.object(notifications, "send_notification", _async_none)
        p.start()
        self._patches.append(p)
        spy(requests.adapters.HTTPAdapter, "send", "requests.adapter.send")
        spy(urllib.request.HTTPSHandler, "https_open", "urllib.https_open")

        self.transport_calls = []

        def handler(request):
            self.transport_calls.append((request.method, str(request.url)))
            return httpx.Response(200, json=[])
        self.transport = httpx.MockTransport(handler)

        self.guard = D.Guard()
        if not GUARD_OFF:
            self.guard.install()
            self.guard.install_app(server)

    def tearDown(self):
        self.guard.uninstall()
        for p in reversed(self._patches):
            p.stop()

    def refused(self, fn, *a, **k):
        """fn(*a) must raise DryRunBlocked (sync or coroutine)."""
        with self.assertRaises(D.DryRunBlocked):
            res = fn(*a, **k)
            if asyncio.iscoroutine(res):
                _run(res)

    def recorded(self, method_part, where_part=""):
        hits = [e for e in self.guard.blocked if method_part in e["method"] and where_part in e["where"]]
        self.assertTrue(hits, f"nothing recorded for {method_part} {where_part}: {self.guard.blocked}")
        return hits[-1]


class NoWriteReachesProduction(_Spied):

    def _prod(self, name):
        client = MongoClient("mongodb://127.0.0.1:9", connect=False, serverSelectionTimeoutMS=50)
        return client["prod"][name]

    def test_every_write_method_is_refused_and_recorded(self):
        col = self._prod("dot_logs")
        args = {"insert_one": ({"_id": 1},), "update_one": ({"_id": 1}, {"$set": {"a": 1}}),
                "find_one_and_update": ({"_id": 1}, {"$set": {"a": 1}}), "bulk_write": ([],),
                "replace_one": ({"_id": 1}, {"a": 1}), "insert_many": ([{"a": 1}],),
                "update_many": ({}, {"$set": {"a": 1}}), "delete_one": ({},), "delete_many": ({},),
                "find_one_and_replace": ({}, {"a": 1}), "find_one_and_delete": ({},),
                "create_index": ("a",), "drop": (), "rename": ("dot_logs_old",)}
        for w in WRITES:
            with self.subTest(w):
                self.refused(getattr(col, w), *args[w])
                self.recorded(w, "prod.dot_logs")
                self.spies[f"pymongo.{w}"].assert_not_called()

    def test_the_ledgers_and_system_config_keys(self):
        for name, flt in (("whatsapp_notification_ledger", {"_id": "gc:p1:dot_violation:oath:1"}),
                          ("dot_alert_ledger", {"_id": "dot:p1:hearing:1:14:2026-12-24"}),
                          ("source_sync_state", {"_id": "p1"})):
            with self.subTest(name):
                self.refused(self._prod(name).update_one, flt, {"$set": {"x": 1}}, upsert=True)
                self.recorded("update_one", f"prod.{name}")
        self.refused(self._prod("system_config").update_one,
                     {"_id": "initial_scan_done:dot:p1"}, {"$set": {"value": True}}, upsert=True)
        e = self.recorded("update_one", "prod.system_config")
        self.assertIn("initial_scan_done:", e["summary"])
        self.spies["pymongo.update_one"].assert_not_called()

    def test_aggregate_out_and_merge_and_the_motor_path(self):
        col = self._prod("dob_logs")
        for stage in ({"$out": "x"}, {"$merge": {"into": "x"}}):
            with self.subTest(stage):
                self.refused(col.aggregate, [{"$match": {}}, stage])
                self.recorded("aggregate($out/$merge)", "prod.dob_logs")
        motor = AsyncIOMotorClient("mongodb://127.0.0.1:9", serverSelectionTimeoutMS=50)["prod"]["dot_logs"]
        self.refused(motor.insert_one, {"_id": "x"})
        self.recorded("insert_one", "dot_logs")
        self.spies["motor.insert_one"].assert_not_called()


class NoSendLeavesTheMachine(_Spied):

    def test_resend(self):
        self.refused(resend.Emails.send, {"to": ["a@b.test"], "subject": "hi"})
        self.recorded("resend.Emails.send", "a@b.test")
        self.spies["resend.Emails.send"].assert_not_called()

    def test_send_notification(self):
        got = _run(notifications.send_notification(
            None, permit_renewal_id="dot:p1:x", trigger_type="dot_hearing_reminder",
            recipient="admin@x.test", subject="DOT hearing", html="<p>", text="t", metadata={}))
        self.assertEqual(got, {"status": "dry_run_blocked"})
        e = self.recorded("send_notification", "admin@x.test")
        self.assertEqual(e["kwargs"]["trigger_type"], "dot_hearing_reminder")
        self.assertEqual(self.spies["async_calls"], [])

    def test_the_whatsapp_transports(self):
        _run(server.send_whatsapp_message("1203@g.us", "DOT hearing in 7 days"))
        self.recorded("send_whatsapp_message", "1203@g.us")
        _run(server.send_whatsapp_dm("u1", "hello", kind="x"))
        self.recorded("send_whatsapp_dm", "u1")
        _run(server._waapi_post_raw("https://waapi.app/api/v1/instances/1/client/action/send-message",
                                    {"chatId": "1@c.us"}, {}))
        self.recorded("_waapi_post_raw", "waapi.app")
        self.assertEqual(self.spies["async_calls"], [])

    def test_http_post_and_a_get_to_another_host(self):
        async def go():
            async with httpx.AsyncClient(transport=self.transport) as c:
                with self.assertRaises(D.DryRunBlocked):
                    await c.post("https://api.waapi.app/send", json={"m": 1})
                with self.assertRaises(D.DryRunBlocked):
                    await c.get("https://example.com/anything")
                await c.get("https://data.cityofnewyork.us/resource/jz4z-kudi.json")   # allowed
        _run(go())
        self.recorded("httpx POST", "api.waapi.app")
        self.recorded("httpx GET", "example.com")
        self.assertEqual(self.transport_calls,
                         [("GET", "https://data.cityofnewyork.us/resource/jz4z-kudi.json")])
        with httpx.Client(transport=self.transport) as c:
            self.refused(c.put, "https://example.com/x")
        self.refused(requests.post, "https://api.resend.com/emails", json={})
        self.recorded("requests POST", "api.resend.com")
        self.spies["requests.adapter.send"].assert_not_called()
        self.refused(urllib.request.urlopen, urllib.request.Request(
            "https://hooks.example.com/x", data=b"{}", method="POST"))
        self.recorded("urllib POST", "hooks.example.com")
        self.spies["urllib.https_open"].assert_not_called()
        self.assertFalse(any("data.cityofnewyork.us" in e["where"] for e in self.guard.blocked))

    def test_the_lower_layers_boto3_uses(self):
        # boto3 / botocore (R2 uploads) call urllib3 directly, below requests;
        # urllib3 and urllib end in http.client. A PUT through either is refused.
        import http.client
        import urllib3
        import urllib3.connectionpool
        made = MagicMock(name="urllib3._make_request")
        sent = MagicMock(name="http.client.send")
        for owner, name, m in ((urllib3.connectionpool.HTTPConnectionPool, "_make_request", made),
                               (http.client.HTTPConnection, "send", sent)):
            p = patch.object(owner, name, m)
            p.start()
            self._patches.append(p)
        pool =urllib3.HTTPSConnectionPool("r2.example.com", retries=False)
        self.refused(pool.urlopen, "PUT", "/bucket/report.pdf", body=b"%PDF")
        self.recorded("urllib3 PUT", "r2.example.com/bucket/report.pdf")
        made.assert_not_called()
        conn = http.client.HTTPSConnection("hooks.example.com", timeout=1)
        self.refused(conn.request, "POST", "/x", body="{}")
        self.recorded("http.client POST", "hooks.example.com/x")
        sent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
