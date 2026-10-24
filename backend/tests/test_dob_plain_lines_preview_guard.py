"""The operator preview (scripts/dob_plain_lines_preview.py) writes nothing and
sends nothing: its guard, exercised without running the script.

Pins:
  * every send credential is blanked except the model's QWEN_* trio;
  * HTTP: only a GET to data.cityofnewyork.us and a POST to
    {QWEN_API_BASE}/chat/completions pass; every other method, host or path
    is refused;
  * a Mongo write on a motor collection raises and is recorded.
"""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "dob_plain_lines_preview.py"


def _load():
    spec = importlib.util.spec_from_file_location("dob_plain_lines_preview_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PreviewGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def test_credentials_blanked_except_the_model(self):
        env = {"QWEN_API_KEY": "k", "QWEN_API_BASE": "https://api.deepinfra.com/v1/openai",
               "QWEN_MODEL": "Qwen/x", "RESEND_API_KEY": "r", "WAAPI_TOKEN": "w",
               "OPENAI_API_KEY": "o", "R2_SECRET_ACCESS_KEY": "s", "SOMETHING_TOKEN": "t",
               "PATH": "/bin"}
        blanked = self.m.blank_send_credentials(env)
        self.assertEqual(env["QWEN_API_KEY"], "k")
        self.assertEqual(env["QWEN_MODEL"], "Qwen/x")
        for k in ("RESEND_API_KEY", "WAAPI_TOKEN", "OPENAI_API_KEY", "R2_SECRET_ACCESS_KEY", "SOMETHING_TOKEN"):
            self.assertEqual(env[k], "", k)
            self.assertIn(k, blanked)
        self.assertEqual(env["PATH"], "/bin")

    def test_http_allow_list(self):
        g = self.m.Guard(llm_url="https://api.deepinfra.com/v1/openai/")
        self.assertTrue(g.http_allowed("GET", "https://data.cityofnewyork.us/resource/6bgk-3dad.json?x=1"))
        self.assertTrue(g.http_allowed("POST", "https://api.deepinfra.com/v1/openai/chat/completions"))
        self.assertFalse(g.http_allowed("POST", "https://data.cityofnewyork.us/resource/x.json"))
        self.assertFalse(g.http_allowed("GET", "https://api.deepinfra.com/v1/openai/chat/completions"))
        self.assertFalse(g.http_allowed("POST", "https://api.deepinfra.com/v1/openai/embeddings"))
        self.assertFalse(g.http_allowed("POST", "https://api.resend.com/emails"))
        self.assertFalse(g.http_allowed("GET", "https://example.com/"))
        self.assertFalse(self.m.Guard(llm_url="").http_allowed(
            "POST", "https://api.deepinfra.com/v1/openai/chat/completions"))

    def test_a_mongo_write_is_refused_and_recorded(self):
        from motor.motor_asyncio import AsyncIOMotorClient
        g = self.m.Guard()
        try:
            self.assertTrue(g.lock_mongo())
            coll = AsyncIOMotorClient("mongodb://127.0.0.1:9", serverSelectionTimeoutMS=50)["preview"]["t"]
            with self.assertRaises(self.m.PreviewBlocked):
                coll.update_one({"_id": 1}, {"$set": {"a": 1}}, upsert=True)
            self.assertEqual(g.blocked[-1]["method"], "update_one")
        finally:
            g.uninstall()
        self.assertFalse(getattr(type(coll).update_one, "__name__", "") == "refused")


if __name__ == "__main__":
    unittest.main()
