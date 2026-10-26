"""Where every model call goes: DeepInfra's OpenAI-compatible API.

── OPENAI IS RETIRED (operator decision, 2026-10-26) ──────────────────────
#
# The OpenAI account ran out of credits on 2026-10-26 and every agent call
# answered 429 credit_balance_exhausted. The DM brain was already on
# DeepInfra (lib/dm_brain, QWEN_API_KEY); every other caller now is too,
# through the same OpenAI-compatible endpoint, so the request and response
# shapes the callers parse do not change.
#
# Benchmarked 2026-10-26 on the 32 eval and 16 real production questions
# (typos as typed) and the seven other user-facing callers, against Kimi-K2.5,
# GLM-5.1, Qwen3-Max and DeepSeek-V4-Flash: Qwen/Qwen3.8-Flash passed every
# caller check, with the best p95 latency, at about $0.09 per 100 questions.
# The operator chose it for every agent and user-facing caller.
#
# Each value can be overridden by environment for an eval or a rollback
# without a deploy. OPENAI_API_KEY stays in Railway until the switch is
# confirmed in production; nothing reads it.
"""

from __future__ import annotations

import os

API_BASE = (os.environ.get("LLM_API_BASE") or "https://api.deepinfra.com/v1/openai").rstrip("/")
#: The DeepInfra key the DM brain already uses (QWEN_API_KEY), unless set.
API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("QWEN_API_KEY", "")
CHAT_MODEL = os.environ.get("LLM_MODEL") or "Qwen/Qwen3.8-Flash"
WHISPER_MODEL = os.environ.get("WHISPER_MODEL") or "openai/whisper-large-v3-turbo"
#: BAAI/bge-m3: 1024 dimensions. Vectors from the old model (OpenAI
#: text-embedding-3-small, 1536) are not comparable and are re-embedded
#: (project memory) or left unread (plan pages and chunks).
EMBED_MODEL = os.environ.get("EMBED_MODEL") or "BAAI/bge-m3"
EMBED_DIMS = 1024

CHAT_URL = f"{API_BASE}/chat/completions"
EMBED_URL = f"{API_BASE}/embeddings"
TRANSCRIBE_URL = f"{API_BASE}/audio/transcriptions"
TRANSLATE_URL = f"{API_BASE}/audio/translations"

#: Qwen/Qwen3.8-Flash on DeepInfra, USD per million tokens (models/list,
#: 2026-10-26). Used only for cost log lines.
PRICE_IN_PER_M = 0.113
PRICE_OUT_PER_M = 0.382

__all__ = ["API_BASE", "API_KEY", "CHAT_MODEL", "WHISPER_MODEL", "EMBED_MODEL", "EMBED_DIMS",
           "CHAT_URL", "EMBED_URL", "TRANSCRIBE_URL", "TRANSLATE_URL", "PRICE_IN_PER_M", "PRICE_OUT_PER_M"]
