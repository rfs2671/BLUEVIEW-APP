"""Run an attention fixture through the real model and compare with its labels.

Read-only: no database, nothing sent to any group. One gpt-4o-mini call per
line that passes the cheap filter, with the lines before it as context, then
the same code checks the worker applies (evidence, issue-names-a-problem,
stated severity). Prints one row per line and the agreement.

    OPENAI_API_KEY=... python scripts/attention_fixture_eval.py \\
        tests/fixtures/attention/pass1_2026_10.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import wa_attention as wa  # noqa: E402


def call(messages):
    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={"model": wa.MODEL, "temperature": 0, "max_tokens": 500,
              "messages": messages, "response_format": {"type": "json_object"}},
        timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def main(path: str) -> int:
    lines = json.loads(Path(path).read_text())["lines"]
    rows, agree = [], 0
    for i, ln in enumerate(lines):
        msg = {"body": ln["body"], "sender": f"1718555100{ln['from']}"}
        prev = [{"body": p["body"], "sender": f"1718555100{p['from']}"}
                for p in lines[max(0, i - wa.CONTEXT_MESSAGES):i]]
        quoted = None
        if ln.get("reply_to"):
            q = lines[ln["reply_to"] - 1]
            quoted = {"body": q["body"], "sender": f"1718555100{q['from']}"}
            msg["quoted_message_id"] = str(ln["reply_to"])
        got = []
        if wa.filter_reason(msg):
            for it in wa.parse_items(call(wa.build_messages(msg, prev, quoted))):
                if not wa.verify_quote(it["quote"], ln["body"]):
                    continue
                if it["type"] == "issue" and not wa.names_a_problem(ln["body"]):
                    continue
                imp = wa.importance(it["importance"], ln["body"])["importance"]
                got.append(f"{it['type']}/{imp}")
        e = ln["expect"]
        want = [f"{e['type']}/normal"] if e["kind"] == "item" else []
        ok = sorted(got) == want
        agree += ok
        rows.append(f"{'OK ' if ok else 'BAD'} {ln['n']:>2} {ln['from']}: "
                    f"{(ln['body'] or '[file]')[:50]:<50} want={want or '-'} got={got or '-'}")
    print("\n".join(rows))
    print(f"\n{agree}/{len(lines)} lines as labelled (prompt {wa.PROMPT_VERSION})")
    return 0 if agree == len(lines) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else "tests/fixtures/attention/pass1_2026_10.json"))
