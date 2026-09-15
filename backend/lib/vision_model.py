"""ONE PLACE THAT DECIDES WHICH VISION MODEL, AT WHICH VENDOR.

WHY THIS FILE EXISTS. `QWEN_MODEL` and `QWEN_API_BASE` are Railway environment
variables read by FIVE call sites, and until this module there were TWO
different sets of defaults for the same two variables:

    backend/server.py   QWEN_API_BASE -> https://api.together.xyz/v1
                        QWEN_MODEL    -> Qwen/Qwen2.5-VL-7B-Instruct
    backend/lib/coi_ocr.py
                        QWEN_API_BASE -> https://api.deepinfra.com/v1/openai
                        QWEN_MODEL    -> Qwen/Qwen3-VL-30B-A3B-Instruct

Two different VENDORS for one variable, and two different models — so "what
does this code do if the variable is unset" had two answers depending on which
line of the product a worker happened to touch. Both answers were wrong:

  * `Qwen/Qwen2.5-VL-7B-Instruct` is 404 `does not exist` at the provider we
    actually call. Every upload would have failed instantly.
  * `Qwen/Qwen3-VL-30B-A3B-Instruct` IS the model that caused the four-day
    registration outage of 2026-09-11 -> 09-15: identical image and prompt,
    470 ms or never, with no upper bound on the tail. It was the default
    sitting in the code AND the value that had been set in Railway.

A DEFAULT IS NOT DOCUMENTATION, IT IS THE BEHAVIOUR ON THE DAY THE VARIABLE
GOES MISSING. So there is now exactly one, it is a model that has been measured
end to end, and every call site reads it from here.

MEASURED, 2026-09-15, full-size card, DeepInfra:
    Qwen/Qwen2.5-VL-32B-Instruct   6/6 successes, 3110-5391 ms
    Qwen/Qwen3-VL-30B-A3B-Instruct 470 ms or >240 s, not correlated with size
                                   (640/768/896/1024 px all ~500 ms;
                                    512 px and 1112 px both hung past 75 s)

THE ENVIRONMENT STILL WINS. Nothing here prevents an operator from pointing at
a different model or vendor; what it prevents is the code disagreeing with
itself about what happens when nobody does. `describe()` is what the startup
log and GET /api/health print, so the value in force is visible in the deploy
log instead of only in a variable panel.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# The verified id. See the module docstring for the measurement behind it.
VISION_MODEL_DEFAULT = "Qwen/Qwen2.5-VL-32B-Instruct"

# DeepInfra, not Together. THE MODEL AND THE VENDOR ARE ONE DECISION: the id
# above is a DeepInfra id and was measured against DeepInfra, and production
# has pointed at DeepInfra since the COI path was written. A default pairing a
# DeepInfra model id with Together's base URL is not a fallback, it is a 404
# with extra steps.
VISION_API_BASE_DEFAULT = "https://api.deepinfra.com/v1/openai"


def vision_model() -> str:
    """The model id every vision call site sends. Env overrides."""
    return (os.environ.get("QWEN_MODEL") or "").strip() or VISION_MODEL_DEFAULT


def vision_api_base() -> str:
    """The OpenAI-compatible base URL, without a trailing slash."""
    raw = (os.environ.get("QWEN_API_BASE") or "").strip() or VISION_API_BASE_DEFAULT
    return raw.rstrip("/")


def vision_api_key() -> str:
    return (os.environ.get("QWEN_API_KEY") or "").strip()


def describe() -> Dict[str, Any]:
    """What is in force, and WHERE EACH HALF CAME FROM.

    `*_source` is the part that could not be asked before. "We are on the code
    default" and "the operator set this deliberately" are different situations
    with the same printed value, and only one of them is a thing to go fix.
    """
    return {
        "model": vision_model(),
        "model_source": "env" if (os.environ.get("QWEN_MODEL") or "").strip() else "default",
        "base": vision_api_base(),
        "base_source": "env" if (os.environ.get("QWEN_API_BASE") or "").strip() else "default",
        "key_set": bool(vision_api_key()),
        "default_model": VISION_MODEL_DEFAULT,
        "default_base": VISION_API_BASE_DEFAULT,
    }


async def probe(http_client: Optional[Any] = None, timeout: float = 15.0) -> Dict[str, Any]:
    """Ask the provider whether the resolved model id exists AT ALL.

    A DEAD MODEL ID MUST NOT BE DISCOVERABLE ONLY BY A WORKER AT A TURNSTILE.
    That is exactly how the 7B default would have been found: the variable
    unset or misspelled, every card upload 500ing, and nothing anywhere saying
    the id we were sending does not resolve.

    THE CHEAPEST QUESTION THAT ANSWERS IT. One chat completion with a two-word
    text prompt and `max_tokens=1` — no image. A wrong id 404s on the request
    line, before any inference, so the answer costs a rounding error
    (<$0.000005 at $0.20/1M input) and is checked once at boot, not per
    health request.

    NEVER RAISES. Returns a dict; `ok` is None when the question could not be
    put (no API key, transport failure) and False only when the provider
    answered and said no. The difference matters: "we could not ask" must not
    read as "the model is dead", or a flaky network becomes a false alarm on
    every deploy.
    """
    cfg = describe()
    out: Dict[str, Any] = {
        "ok": None,
        "status": None,
        "reason": None,
        "model": cfg["model"],
        "base": cfg["base"],
    }

    if not cfg["key_set"]:
        out["reason"] = "QWEN_API_KEY not set"
        return out

    own = False
    try:
        if http_client is None:
            from lib.server_http import ServerHttpClient
            http_client = ServerHttpClient(timeout=timeout)
            own = True
        resp = await http_client.post(
            f"{cfg['base']}/chat/completions",
            headers={
                "Authorization": f"Bearer {vision_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": cfg["model"],
                "max_tokens": 1,
                "temperature": 0,
                "messages": [{"role": "user", "content": "ping"}],
            },
        )
        out["status"] = resp.status_code
        if resp.status_code == 200:
            out["ok"] = True
        elif resp.status_code in (400, 404):
            # THE 404 THIS EXISTS FOR. DeepInfra answers a bad id with
            # `does not exist`; some vendors use 400. Either way the provider
            # has answered and the answer is "not this model".
            body = (resp.text or "")[:300]
            out["ok"] = False
            out["reason"] = f"provider rejected model id: HTTP {resp.status_code} {body}"
        else:
            # 401/429/5xx say something about the account or the vendor's day,
            # not about whether the id resolves. Not a verdict on the model.
            out["reason"] = f"inconclusive: HTTP {resp.status_code}"
    except Exception as exc:                                   # noqa: BLE001
        # %r, never str(): `str(httpx.ReadTimeout())` IS THE EMPTY STRING, and
        # a probe whose failure line reads "vision probe failed: " is the same
        # defect this whole change exists to remove.
        out["reason"] = f"probe could not run: {exc!r}"
        logger.warning("vision model probe could not run: %r", exc)
    finally:
        if own and http_client is not None:
            try:
                await http_client.aclose()
            except Exception:                                  # noqa: BLE001
                pass

    return out
