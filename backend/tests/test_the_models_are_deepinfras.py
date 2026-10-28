"""Every model call goes to DeepInfra (operator decision 2026-10-26: OpenAI is
retired). The chat model is Qwen/Qwen3.8-Flash, Whisper is
openai/whisper-large-v3 (ruled 2026-10-27, over -turbo), embeddings are BAAI/bge-m3 (1024 dimensions),
all through lib/llm_provider, on the DeepInfra key the DM brain already uses.

Each test fails by assertion on the branch before this change.
"""

from __future__ import annotations

import ast
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for k, v in (("MONGO_URL", "mongodb://localhost:27017"), ("DB_NAME", "smoke_test"),
             ("JWT_SECRET", "smoke_test_secret"), ("APP_BASE_URL", "https://app.levelog.com")):
    os.environ.setdefault(k, v)

import server  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
OPENAI_MARKS = ("api.openai.com", "gpt-4o", "text-embedding-3", "whisper-1")


def _provider():
    assert hasattr(server, "llm_provider"), "no lib/llm_provider: the calls still go to OpenAI"
    return server.llm_provider


def _code_strings_and_names(path: Path):
    """String constants that are not docstrings, and names read, in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docs.add(id(body[0].value))
    strings = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
    names = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)]
    return strings, names


class NothingCallsOpenAI(unittest.TestCase):

    def test_no_production_code_names_openai(self):
        _provider()
        hits = []
        for path in [BACKEND / "server.py"] + sorted((BACKEND / "lib").glob("*.py")):
            strings, names = _code_strings_and_names(path)
            for s in strings:
                if any(m in s for m in OPENAI_MARKS):
                    hits.append(f"{path.name}: {s[:60]!r}")
            if "OPENAI_API_KEY" in names:
                hits.append(f"{path.name}: reads OPENAI_API_KEY")
        self.assertEqual(hits, [])

    def test_the_provider_is_deepinfra_with_the_chosen_models(self):
        p = _provider()
        self.assertEqual(p.API_BASE, "https://api.deepinfra.com/v1/openai")
        self.assertEqual(p.CHAT_MODEL, "Qwen/Qwen3.8-Flash")
        self.assertEqual(p.WHISPER_MODEL, "openai/whisper-large-v3")
        self.assertEqual((p.EMBED_MODEL, p.EMBED_DIMS), ("BAAI/bge-m3", 1024))
        self.assertEqual(server.LLM_API_KEY, p.API_KEY)


class _Capture:
    """A ServerHttpClient that records each request and answers it."""
    sent = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None, files=None, **k):
        _Capture.sent.append({"url": url, "json": json, "headers": headers, "files": files})

        class _R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                if url.endswith("/embeddings"):
                    n = len(json["input"]) if isinstance(json["input"], list) else 1
                    return {"data": [{"embedding": [0.1] * 1024} for _ in range(n)]}
                return {"choices": [{"message": {"content": "ok"}}]}
        return _R()


class TheRequestsGoToDeepInfra(unittest.TestCase):

    def setUp(self):
        _Capture.sent = []

    def _run(self, coro):
        p = _provider()
        with patch.object(server, "ServerHttpClient", _Capture), patch.object(server, "LLM_API_KEY", "di-key"):
            asyncio.run(coro)
        self.assertTrue(_Capture.sent)
        return p, _Capture.sent[0]

    def test_a_chat_call(self):
        p, req = self._run(server._dm_llm("system", "question"))
        self.assertEqual(req["url"], p.CHAT_URL)
        self.assertEqual(req["json"]["model"], "Qwen/Qwen3.8-Flash")
        self.assertEqual(req["headers"]["Authorization"], "Bearer di-key")

    def test_a_plan_embedding(self):
        p, req = self._run(server._generate_embedding("A-400.00 door schedule"))
        self.assertEqual(req["url"], p.EMBED_URL)
        self.assertEqual(req["json"]["model"], "BAAI/bge-m3")

    def test_a_memory_embedding(self):
        p, req = self._run(server._memory_embed_many(["poured the slab"]))
        self.assertEqual(req["url"], p.EMBED_URL)
        self.assertEqual(req["json"]["model"], "BAAI/bge-m3")


class MemoryVectorsFromAnotherModel(unittest.TestCase):

    def test_the_vector_index_is_redefined_at_the_new_size(self):
        _provider()
        commands = []
        listed = [{"name": "project_memory_text", "queryable": True},
                  {"name": "project_memory_vector", "queryable": True,
                   "latestDefinition": {"fields": [{"type": "vector", "path": "embedding",
                                                    "numDimensions": 1536, "similarity": "cosine"}]}}]

        class _Agg:
            async def to_list(self, n):
                return listed

        class _Coll:
            def aggregate(self, pipeline):
                return _Agg()

        class _Db:
            project_memory = _Coll()

            def __getitem__(self, k):
                return _Coll()

            async def command(self, cmd):
                commands.append(cmd)
                return {"ok": 1}

        with patch.object(server, "db", _Db()):
            asyncio.run(server._memory_atlas_check(create=True))
        upd = [c for c in commands if "updateSearchIndex" in c]
        self.assertEqual(len(upd), 1, commands)
        self.assertEqual(upd[0]["name"], "project_memory_vector")
        dims = [f["numDimensions"] for f in upd[0]["definition"]["fields"] if f.get("type") == "vector"]
        self.assertEqual(dims, [1024])

    def test_an_index_already_at_the_new_size_is_left_alone(self):
        _provider()
        self.assertEqual(server._vector_dims({"latestDefinition": {"fields": [
            {"type": "vector", "numDimensions": 1024}]}}), 1024)
        self.assertIsNone(server._vector_dims({"name": "x"}))

    def test_rows_embedded_by_another_model_are_embedded_again(self):
        _provider()
        import inspect
        src = inspect.getsource(server._memory_index_tick)
        self.assertIn('{"embed_model": {"$ne": project_memory.EMBED_MODEL}}', src)
        self.assertIn('"embed_model": project_memory.EMBED_MODEL', src)


class TheOutageAlertReadsDeepInfra(unittest.TestCase):

    def test_deepinfra_errors(self):
        _provider()
        from lib import model_outage as mo
        # Measured 2026-10-26 with a bad key:
        bad_key = {"error": {"message": "User is not authorized to access this resource",
                             "type": "invalid_request_error", "param": None, "code": "invalid_api_key"}}
        self.assertEqual(mo.classify(401, bad_key), mo.AUTH)
        self.assertEqual(mo.classify(402, {"detail": "Payment Required"}), mo.BILLING)
        self.assertEqual(mo.classify(400, {"error": {"message": "Insufficient balance on your account"}}), mo.BILLING)
        self.assertIsNone(mo.classify(429, {"error": {"message": "Rate limit exceeded, see billing tier"}}))
        self.assertIsNone(mo.classify(500, {"error": {"message": "internal"}}))
        text = mo.alert_text(mo.BILLING, 402, {}, "Qwen/Qwen3.8-Flash")
        self.assertIn("DeepInfra", text)
        self.assertNotIn("OpenAI", text)


if __name__ == "__main__":
    unittest.main()
