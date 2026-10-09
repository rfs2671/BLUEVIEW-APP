"""Run an attention fixture through the real model and compare with its labels.

Read-only: no database, nothing sent to any group. For every line that
should not be handled before the model (state updates, merged parts), one
gpt-4o-mini call with the lines before it as context -- the replied-to
message, or the open ask just before it, shown as the worker shows them --
then the checks the worker applies (evidence, a schedule update is no issue,
severity only as stated). Short acks ("Np", "will do", "👍 tmrw") are read
by code as the worker reads them, with no model call. Prints one row per
line, then the agreement two ways: hard (type as labelled) and soft
(trackable but the other of question / request).

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
from lib import wa_attention_state as was  # noqa: E402
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


def _at(ln):
    return ln.get("at", ln["n"] * 60)


def _is_ask(ln):
    return ln["expect"].get("kind") == "item" and ln["expect"].get("type") in (
        "question", "request")


def _ack_answers(lines, i) -> bool:
    """The worker's rule for a short yes, on the fixture: the ask it replies
    to; else the ask just before it from someone else; else the one ask put
    to this sender (@mention or name) in the last 30 minutes."""
    ln = lines[i]
    if ln.get("reply_to"):
        q = lines[ln["reply_to"] - 1]
        return _is_ask(q) and q["from"] != ln["from"]
    # Rule 2: an ask put to nobody, under 10 minutes old, with nobody but
    # who asked and who says yes writing in between.
    seen = set()
    for p in reversed(lines[:i]):
        if p["expect"].get("kind") == "merged":
            continue
        if _at(ln) - _at(p) > was.ACK_PREVIOUS_SECONDS:
            break
        if _is_ask(p) and p["from"] != ln["from"] and not p.get("mentions"):
            if seen <= {ln["from"], p["from"]}:
                return True
            break
        seen.add(p["from"])
    name = (ln.get("name") or "").split(" ")[0].lower()
    mine = [p for p in lines[:i] if _is_ask(p) and p["from"] != ln["from"]
            and _at(ln) - _at(p) <= was.ACK_WINDOW_SECONDS
            and (ln["from"] in (p.get("mentions") or [])
                 or (name and name in (p["expect"].get("owner_text") or "").lower()))]
    return len(mine) == 1


SOFT = {frozenset(("question", "request"))}


def _soft(want, got) -> bool:
    """Trackable but a different type (a question read as a request, or the
    other way): same count, and each pair equal or in SOFT."""
    if len(want) != len(got):
        return False
    for w, g in zip(sorted(want), sorted(got)):
        wt, gt = w.split("/")[0], g.split("/")[0]
        if w != g and frozenset((wt, gt)) not in SOFT:
            return False
    return True


def main(path: str) -> int:
    lines = json.loads(Path(path).read_text())["lines"]
    rows, hard, soft, judged = [], 0, 0, 0
    for i, ln in enumerate(lines):
        e = ln["expect"]
        if e["kind"] in SKIP or not ln["body"]:
            continue
        body = ln.get("model_match") or ln["body"]
        msg = _row(ln, body)
        got = []
        if was.ack(body) is not None:
            # Read by code, as the worker does: no model call.
            got = ["commitment/normal"] if _ack_answers(lines, i) else []
            how = "ack"
        else:
            how = "model"
            prev = [_row(p) for p in lines[max(0, i - wa.CONTEXT_MESSAGES):i]]
            quoted = answers = None
            if ln.get("reply_to"):
                quoted = _row(lines[ln["reply_to"] - 1])
                msg["quoted_message_id"] = str(ln["reply_to"])
            elif i and _is_ask(lines[i - 1]) and lines[i - 1]["from"] != ln["from"]:
                answers = _row(lines[i - 1])
            if wa.filter_reason(msg):
                for it in wa.parse_items(call(wa.build_messages(msg, prev, quoted, answers))):
                    if not wa.verify_quote(it["quote"], body):
                        continue
                    if it["type"] == "issue" and wa.is_schedule_update(body):
                        continue
                    imp = wa.importance(it["importance"], body)["importance"]
                    got.append(f"{it['type']}/{imp}")
        want = [f"{e['type']}/{e.get('importance', 'normal')}"] if e["kind"] == "item" else []
        h = sorted(got) == sorted(want)
        s = h or _soft(want, got)
        hard += h
        soft += s
        judged += 1
        mark = "OK  " if h else ("SOFT" if s else "BAD ")
        rows.append(f"{mark} {ln['n']:>2} {ln['from']}: "
                    f"{body.replace(chr(10), ' / ')[:48]:<48} [{how}] "
                    f"want={want or '-'} got={got or '-'}")
    print("\n".join(rows))
    print(f"\nhard {hard}/{judged}   soft {soft}/{judged}   (prompt {wa.PROMPT_VERSION}; "
          f"soft = trackable, question<->request; state updates are read by code, not here)")
    return 0 if hard == judged else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else "tests/fixtures/attention/pass1_2026_10.json"))
