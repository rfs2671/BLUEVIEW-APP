"""Run an attention fixture through the real model and compare with its labels.

Read-only: no database, nothing sent to any group. For every line that
should not be handled before the model (state updates, merged parts), one
gpt-4o-mini call with the lines before it as context -- the replied-to
message, or the open ask just before it, shown as the worker shows them --
then the checks the worker applies (evidence, an issue names a problem,
severity only as stated). Prints one row per line and the agreement.

    OPENAI_API_KEY=... python scripts/attention_fixture_eval.py \\
        tests/fixtures/attention/pass2_2026_10.json
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import wa_attention as wa  # noqa: E402
from lib.server_http import ServerHttpClient  # noqa: E402

SKIP = ("state", "part_done", "follow_up", "flag", "merged")


async def _call(messages):
    async with ServerHttpClient(timeout=60) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={"model": wa.MODEL, "temperature": 0, "max_tokens": 500,
                  "messages": messages, "response_format": {"type": "json_object"}})
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def call(messages):
    return asyncio.run(_call(messages))


def _row(ln, body=None):
    return {"body": ln["body"] if body is None else body,
            "sender": f"1718555100{ord(ln['from'])}"}


def main(path: str) -> int:
    lines = json.loads(Path(path).read_text())["lines"]
    rows, agree, judged = [], 0, 0
    for i, ln in enumerate(lines):
        e = ln["expect"]
        if e["kind"] in SKIP or not ln["body"]:
            continue
        body = ln.get("model_match") or ln["body"]
        msg = _row(ln, body)
        prev = [_row(p) for p in lines[max(0, i - wa.CONTEXT_MESSAGES):i]]
        quoted = answers = None
        if ln.get("reply_to"):
            quoted = _row(lines[ln["reply_to"] - 1])
            msg["quoted_message_id"] = str(ln["reply_to"])
        elif i and lines[i - 1]["expect"].get("type") in ("question", "request") \
                and lines[i - 1]["from"] != ln["from"]:
            answers = _row(lines[i - 1])
        got = []
        if wa.filter_reason(msg):
            for it in wa.parse_items(call(wa.build_messages(msg, prev, quoted, answers))):
                if not wa.verify_quote(it["quote"], body):
                    continue
                if it["type"] == "issue" and not wa.names_a_problem(body):
                    continue
                imp = wa.importance(it["importance"], body)["importance"]
                got.append(f"{it['type']}/{imp}")
        want = [f"{e['type']}/{e.get('importance', 'normal')}"] if e["kind"] == "item" else []
        ok = sorted(got) == want
        agree += ok
        judged += 1
        rows.append(f"{'OK ' if ok else 'BAD'} {ln['n']:>2} {ln['from']}: "
                    f"{body.replace(chr(10), ' / ')[:50]:<50} want={want or '-'} got={got or '-'}")
    print("\n".join(rows))
    print(f"\n{agree}/{judged} lines as labelled (prompt {wa.PROMPT_VERSION}; "
          f"state updates are read by code, not here)")
    return 0 if agree == judged else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else "tests/fixtures/attention/pass1_2026_10.json"))
