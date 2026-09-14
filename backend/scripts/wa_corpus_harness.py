"""Measure the WhatsApp corpus offline, from an export file. Reads nothing else.

══ WHY THIS IS A FILE READER AND NOT A DATABASE CLIENT ══════════════════════

Every sibling of this script in this directory opens a connection. This one
cannot: it imports no driver, reads no connection string, and takes a path on
the command line. The only input is a JSONL file produced by mongoexport on
someone else's machine. That is deliberate and not a limitation to be fixed —
the corpus it measures is production data holding customers' statutory records,
and a measurement script is the last thing that should be able to write to it.

    mongoexport --uri "$MONGO_URI" \\
      --collection whatsapp_messages \\
      --fields group_id,sender,body,has_audio,timestamp,created_at,message_id \\
      --out wa_messages.jsonl

`body` is the only field that carries content. If the export must be scrubbed
before it leaves the operator's machine, scrub the phone numbers in `sender` —
nothing here reads them except to count distinct senders, and a stable hash in
that field works exactly as well.

══ WHAT IT ANSWERS, IN THE ORDER THE QUESTIONS WERE ASKED ═══════════════════

  1. What is actually in the 217. Human turns and bot turns live in the same
     collection — send_whatsapp_message writes replies with sender "bot" — so
     "217 messages" is not 217 things a person said, and every rate computed
     against the wrong denominator is wrong by that ratio.

  2. How many messages the material classifier actually fires on. The gate in
     _detect_material_request is a single length test: 15 characters. That is
     reproduced here exactly, including the strip().

  3. What a keyword prefilter would cost. Precision is not the interesting
     number — a prefilter that skips the model can only lose recall, never gain
     it, and a miss is silent. So the harness reports, per skipped message, the
     text it skipped, because that list is the thing a person has to read before
     trusting it.

RUNNING THE REAL CLASSIFIER IS OPT-IN AND COSTS MONEY. With --classify it
sends each gated message to gpt-4o-mini with the prompt from server.py, byte for
byte, so the baseline is the deployed behaviour and not an approximation of it.
Without it, the run is free and offline, and reports only what can be counted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

# The gate in server.py::_detect_material_request. One number, one strip().
MIN_BODY_CHARS = 15

# ── THE CANDIDATE PREFILTER ──────────────────────────────────────────────
#
# Drawn from the vocabulary classify_intent already carries in its string-match
# rules, plus the four phrasings the material-detection prompt gives as its own
# examples. Nothing here is invented: every term is one the deployed code or its
# prompt already treats as material language.
#
# WORD BOUNDARIES, BECAUSE "short" IS INSIDE "shortly" AND "ordered" IS INSIDE
# "reordered" BUT ALSO INSIDE "border". A substring test over site chatter
# matches things nobody meant, and a prefilter that fires on everything saves
# nothing while looking like it works.
_PREFILTER_TERMS = [
    # asking for material
    r"need", r"needs", r"needed", r"order", r"orders", r"ordered", r"ordering",
    r"bring", r"send", r"deliver", r"delivery", r"deliveries", r"delivered",
    r"drop\s*off", r"dropped\s*off", r"pick\s*up", r"restock", r"resupply",
    r"out\s*of", r"run(?:ning)?\s*out", r"low\s*on", r"more",
    # receiving material
    r"arrived", r"arriving", r"received", r"receipt", r"truck",
    r"on\s*site\s*now", r"here\s*now",
    # something is wrong with the quantity
    r"short", r"shortage", r"missing", r"only\s*got", r"not\s*enough",
    # the units a quantity is counted in
    r"sheets?", r"bags?", r"boxes", r"box", r"bundles?", r"pallets?",
    r"rolls?", r"yards?", r"loads?", r"pieces?", r"pcs",
]
_PREFILTER = re.compile(r"\b(?:" + "|".join(_PREFILTER_TERMS) + r")\b", re.I)

# A bare quantity is material language on its own: "200 drywall" carries no verb
# and no unit, and the deployed prompt would still call it a request.
_QUANTITY = re.compile(r"\b\d{1,5}\s*(?:x|×)?\s*\w", re.I)


def prefilter_passes(body: str) -> bool:
    """True when the message should still reach the model."""
    return bool(_PREFILTER.search(body) or _QUANTITY.search(body))


def load(path: str) -> list:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  ! line {n} is not JSON, skipped: {e}", file=sys.stderr)
    return rows


def _text(row) -> str:
    return (row.get("body") or "").strip()


def _is_bot(row) -> bool:
    return (row.get("sender") or "").strip().lower() == "bot"


def compose(rows) -> dict:
    """What the corpus is made of, before anything is measured against it."""
    groups = Counter()
    for r in rows:
        groups[r.get("group_id") or "(no group_id — direct message)"] += 1

    human = [r for r in rows if not _is_bot(r)]
    bot = [r for r in rows if _is_bot(r)]
    gated = [r for r in human if len(_text(r)) >= MIN_BODY_CHARS]

    return {
        "total": len(rows),
        "bot": len(bot),
        "human": len(human),
        "audio": sum(1 for r in rows if r.get("has_audio")),
        "empty_body": sum(1 for r in rows if not _text(r)),
        "groups": groups,
        "senders": len({r.get("sender") for r in human}),
        "gated": len(gated),
        "gated_rows": gated,
    }


def report_composition(c: dict) -> None:
    print("═══ WHAT IS IN THE EXPORT ═══")
    print(f"  rows                      {c['total']:>6}")
    print(f"  written by the bot        {c['bot']:>6}   sender == 'bot'")
    print(f"  written by a person       {c['human']:>6}   <- the real corpus")
    print(f"  distinct human senders    {c['senders']:>6}")
    print(f"  empty body                {c['empty_body']:>6}")
    print(f"  flagged has_audio         {c['audio']:>6}")
    print()
    print("  by group:")
    for gid, n in c["groups"].most_common():
        print(f"    {n:>5}  {gid}")
    print()
    print("═══ WHAT THE MATERIAL CLASSIFIER FIRES ON ═══")
    print(f"  human messages >= {MIN_BODY_CHARS} chars   {c['gated']:>6}")
    print("  (upper bound: messages addressed to the bot go to the agent")
    print("   instead, and that test needs session state the export omits)")
    print()


def report_prefilter(gated) -> None:
    kept = [r for r in gated if prefilter_passes(_text(r))]
    skipped = [r for r in gated if not prefilter_passes(_text(r))]
    n = len(gated) or 1

    print("═══ WHAT THE PREFILTER WOULD DO ═══")
    print(f"  still sent to the model   {len(kept):>6}   {100*len(kept)/n:5.1f}%")
    print(f"  skipped, costing nothing  {len(skipped):>6}   {100*len(skipped)/n:5.1f}%")
    print()
    print("  EVERY SKIPPED MESSAGE, because a miss here is silent and this list")
    print("  is the thing a person has to read before trusting the filter:")
    for r in skipped:
        print(f"    - {_text(r)[:150]!r}")
    print()
    return kept, skipped


async def classify(rows, api_key: str) -> dict:
    """Run the deployed prompt over each message. Costs money; opt-in."""
    # ServerHttpClient, NOT httpx.AsyncClient, AND CI IS RIGHT TO INSIST.
    #
    # The rule is in .github: nothing under backend/ may open a raw async httpx
    # client, because the wrapper is what refuses a request to an Akamai-
    # protected DOB host. This script talks to api.openai.com and would never
    # trip that guard, which is exactly the reasoning that makes a per-file
    # exemption worthless — the next script copies this one.
    #
    # It costs nothing here. lib/server_http.py imports stdlib and httpx and
    # nothing else, so the standing rule of this file — no server import, no
    # database driver — is intact.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from lib.server_http import ServerHttpClient

    SYSTEM = """You analyze construction site WhatsApp messages to detect material requests.
A material request is when someone asks for construction materials to be ordered or delivered.
Examples: "need 200 sheets of drywall", "order 50 bags of concrete", "we're out of 2x4s", "bring 10 boxes of screws tomorrow"
NOT material requests: status updates, questions, greetings, photos, scheduling.

If this is a material request, return JSON:
{"is_request": true, "items": [{"name": "material name", "quantity": number_or_null, "unit": "unit_or_null", "specs": "any specifications"}], "trade": "framing|plumbing|electrical|concrete|drywall|general", "needed_by": "date_mentioned_or_null"}

If NOT a material request, return: {"is_request": false}"""

    out = {}
    async with ServerHttpClient(timeout=30) as client:
        for i, r in enumerate(rows, 1):
            body = _text(r)
            try:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "gpt-4o-mini",
                        "temperature": 0,
                        "messages": [
                            {"role": "system", "content": SYSTEM},
                            {"role": "user", "content": body},
                        ],
                        "response_format": {"type": "json_object"},
                    },
                )
                verdict = bool(
                    json.loads(resp.json()["choices"][0]["message"]["content"])
                    .get("is_request")
                )
            except Exception as e:
                print(f"  ! message {i} failed: {e}", file=sys.stderr)
                verdict = None
            out[id(r)] = verdict
            if i % 25 == 0:
                print(f"    ... {i}/{len(rows)}", file=sys.stderr)
    return out


def report_agreement(gated, verdicts) -> None:
    """The only number that decides whether the prefilter is safe to ship."""
    tp = fp = fn = tn = unknown = 0
    missed = []
    for r in gated:
        v = verdicts.get(id(r))
        if v is None:
            unknown += 1
            continue
        keep = prefilter_passes(_text(r))
        if v and keep:
            tp += 1
        elif v and not keep:
            fn += 1
            missed.append(_text(r))
        elif not v and keep:
            fp += 1
        else:
            tn += 1

    print("═══ PREFILTER AGAINST THE DEPLOYED CLASSIFIER ═══")
    print(f"  model said request, filter kept it      {tp:>5}")
    print(f"  model said request, filter SKIPPED it   {fn:>5}   <- lost recall")
    print(f"  model said no,      filter kept it      {fp:>5}   <- wasted call")
    print(f"  model said no,      filter skipped it   {tn:>5}   <- the saving")
    if unknown:
        print(f"  classifier errored                      {unknown:>5}")
    print()
    total = tp + fn
    if total:
        print(f"  RECALL: {100*tp/total:.1f}% of real requests survive the filter.")
    print(f"  CALLS SAVED: {fn + tn} of {tp+fp+fn+tn}.")
    print()
    if missed:
        print("  THE REQUESTS THE FILTER WOULD HAVE LOST. Each one is a material")
        print("  request that silently never reaches the model. Read all of them")
        print("  before this ships:")
        for m in missed:
            print(f"    - {m[:150]!r}")
        print()
    else:
        print("  No request was lost on this corpus. That is one corpus of one")
        print("  group, and it is not a guarantee about phrasings it never used.")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("export", help="path to a mongoexport JSONL of whatsapp_messages")
    ap.add_argument("--classify", action="store_true",
                    help="run the deployed gpt-4o-mini prompt; costs money")
    args = ap.parse_args()

    if not os.path.exists(args.export):
        print(f"no such file: {args.export}", file=sys.stderr)
        return 2

    rows = load(args.export)
    if not rows:
        print("export is empty", file=sys.stderr)
        return 2

    c = compose(rows)
    report_composition(c)
    report_prefilter(c["gated_rows"])

    if args.classify:
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            print("--classify needs OPENAI_API_KEY in the environment",
                  file=sys.stderr)
            return 2
        import asyncio
        print(f"calling gpt-4o-mini on {c['gated']} messages ...", file=sys.stderr)
        verdicts = asyncio.run(classify(c["gated_rows"], key))
        report_agreement(c["gated_rows"], verdicts)
    else:
        print("Run again with --classify to measure the filter against the")
        print("deployed classifier. Until then the recall number does not exist,")
        print("and the filter should not ship on the saving alone.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
