"""One person's DM chat with Levelog Assistant on one day, step by step. READ-ONLY.

    railway run python scripts/dm_thread_timeline.py --email roy@company.com --date 2026-10-27
    railway run python scripts/dm_thread_timeline.py --user-id 64f... --date 2026-10-27 \\
        --json /tmp/dm_2026-10-27.json --webhook-log

Built for Oct 27, 2026 (588 Thomas S Boyland): spray foam on the 5th floor
ceiling asked 10:36, answered 10:43 only after a "?". For every message they
sent that day (America/New_York) it prints:

  * when it was stored (and, with --webhook-log, when WaAPI delivered it and
    WhatsApp's own send time -- the webhook log is kept 30 days);
  * the answer row (whatsapp_dm_answers): path, model, rounds, stop,
    verify / deflect retries, usage (model calls, seconds, tokens), tools
    tried, the draft a check held back, the reply;
  * every model round and tool call with its args -- and, when the row has
    them, each one's t_ms (offset from the webhook's receipt) and ms
    (duration). Rows written before that timing existed have NO per-step
    times: the output says so, and only the row's own time and usage.seconds
    are there to go on;
  * what the plan tools found: sheet / file / page / set and the quote, cut
    short. Other tools' results are NOT printed (they can hold other people's
    words -- group messages, voice notes, names): only their length;
  * every message Levelog sent in the chat after it, with times, the reply
    ledger rows for the person (proactive sends and refusals), and the deltas
    received -> answer logged -> first message out.

Phone numbers are never printed: a chat is "…1234". Nothing is written.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import datefmt, wa_dm  # noqa: E402

NY = ZoneInfo("America/New_York")
ANSWERS = "whatsapp_dm_answers"          # server.DM_ANSWERS
OPTINS = "whatsapp_optins"               # server.WA_OPTINS
LEDGER = "whatsapp_notification_ledger"  # server.WA_LEDGER
WALKS = "punch_sessions"                 # lib/punch.SESSIONS
#: Tools whose results are the drawings / files themselves: printed (cut).
PLAN_TOOLS = ("search_plans", "query_plan", "check_drawing_set", "send_sheet", "send_report")
_PHONE_RUN = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def clean(v, n: int = 300) -> str:
    """A string as this script may print it: no phone runs, one line, cut."""
    s = _PHONE_RUN.sub("[number]", str(v if v is not None else ""))
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def last4(v) -> str:
    d = wa_dm.phone_digits(str(v or ""))
    return f"…{d[-4:]}" if d else "(none)"


def utc(v):
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def ny(v) -> str:
    v = utc(v)
    return datefmt.strftime(v.astimezone(NY), "%-I:%M:%S %p") if v else "?"


def span(a, b) -> str:
    a, b = utc(a), utc(b)
    if not a or not b:
        return "?"
    s = (b - a).total_seconds()
    sign = "-" if s < 0 else "+"
    s = abs(s)
    return f"{sign}{int(s // 60)}m{s % 60:04.1f}s" if s >= 60 else f"{sign}{s:.1f}s"


def ms(v) -> str:
    if v is None:
        return "?"
    v = int(v)
    return f"{v / 1000:.1f}s" if abs(v) < 60000 else f"{v // 60000}m{(v % 60000) / 1000:04.1f}s"


def day_range(day: str):
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=NY)
    return d.astimezone(timezone.utc), (d + timedelta(days=1)).astimezone(timezone.utc)


def chat_ids(digits_list) -> list:
    out = []
    for d in digits_list:
        if d:                                   # an empty phone matches nobody
            out += [f"{d}@c.us", f"{d}@lid", f"{d}@s.whatsapp.net"]
    return list(dict.fromkeys(out))


def jsonable(v):
    if isinstance(v, datetime):
        return utc(v).isoformat()
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def plan_lines(tool: dict, quote_chars: int) -> list:
    """What a plan tool found: the stored records when the row has them
    (sheet / file / page / set / quote), else the head of its result text."""
    recs = tool.get("records")
    if recs:
        return [" · ".join(x for x in (
            str(r.get("sheet") or ""), str(r.get("file") or ""),
            f"p{r.get('page')}" if r.get("page") is not None else "",
            f"set {r.get('set')}" if r.get("set") else "") if x)
            + f' · "{clean(r.get("quote"), quote_chars)}"' for r in recs]
    res = str(tool.get("result") or "")
    lines = [ln.strip() for ln in res.splitlines() if ln.strip()]
    return [clean(ln, quote_chars + 40) for ln in lines[:8]] + (
        [f"(+{len(lines) - 8} more lines)"] if len(lines) > 8 else [])


def describe_tool(tool: dict, quote_chars: int) -> list:
    name = str(tool.get("tool") or "?")
    args = clean(json.dumps(tool.get("args") or {}, ensure_ascii=False), 240)
    when = (f"r{tool.get('round')} at {ms(tool.get('t_ms'))} took {ms(tool.get('ms'))}"
            if "t_ms" in tool else "no per-step time")
    flags = " ".join(f for f, on in (("ERROR", tool.get("error")), ("DUPLICATE", tool.get("duplicate"))) if on)
    out = [f"    [{when}] {name} {args} {flags}".rstrip()]
    res = str(tool.get("result") or "")
    if name in PLAN_TOOLS:
        out += [f"        → {ln}" for ln in plan_lines(tool, quote_chars)]
    else:
        out.append(f"        → result not printed ({len(res)} chars; may hold other people's words)")
    return out


def describe_answer(a: dict, inbound_at, quote_chars: int) -> list:
    out = []
    usage = a.get("usage") or {}
    out.append(f"  answer row logged {ny(a.get('created_at'))} ({span(inbound_at, a.get('created_at'))} "
               f"after their message) · path {a.get('path')} · model {a.get('model') or '-'} · "
               f"rounds {a.get('rounds')} · stop {a.get('stop')} · fallback {a.get('fallback')} "
               f"({a.get('reason')})")
    out.append(f"  retries: verify {a.get('verify_retries') or 0} · deflect {a.get('deflect_retries') or 0}"
               f" · unverified {clean(a.get('unverified') or '-', 120)}")
    if usage:
        out.append(f"  usage: {usage.get('calls')} model call(s), {usage.get('seconds')} s in the model, "
                   f"{usage.get('input')} in / {usage.get('output')} out tokens"
                   + (f", {usage.get('reasoning')} reasoning" if usage.get("reasoning") else "")
                   + f", models {usage.get('models')}")
    timing = a.get("timing")
    if timing:
        out.append(f"  timing (offsets from the webhook's receipt at {ny(timing.get('received_at'))}): "
                   f"queue {ms(timing.get('queue_ms'))} · WhatsApp→webhook {ms(timing.get('wa_lag_ms'))} · "
                   f"brain start {ms(timing.get('brain_start_ms'))} · brain {ms(timing.get('brain_ms'))} · "
                   f"FIRST SEND {ms(timing.get('first_send_ms'))}")
        for r in timing.get("rounds") or []:
            out.append(f"    round {r.get('round')}: at {ms(r.get('t_ms'))} took {ms(r.get('ms'))} · "
                       f"finish {r.get('finish') or '-'} · tool calls {r.get('tools', '-')}"
                       + (f" · then re-asked ({r['then']})" if r.get("then") else "")
                       + (f" · ERROR {r['error']}" if r.get("error") else ""))
        for s in timing.get("sends") or []:
            out.append(f"    send {s.get('action')}: at {ms(s.get('t_ms'))} ok={s.get('ok')} "
                       f"waited {ms(s.get('wait_ms'))} for the DM send lock, tries {s.get('tries', '-')}"
                       + (f" · REFUSED {s['refused']}" if s.get("refused") else ""))
    else:
        out.append("  timing: NONE -- this row was logged before per-step timestamps existed. "
                   "Only the row's own time and usage.seconds (model time, summed) are known.")
    tools = a.get("tool_data") if isinstance(a.get("tool_data"), list) else []
    out.append(f"  tools ({len(tools)}): " + ("" if tools else "none"))
    for t in tools:
        if isinstance(t, dict):
            out += describe_tool(t, quote_chars)
    if a.get("draft"):
        out.append(f"  draft held back: \"{clean(a.get('draft'), 400)}\"")
    out.append(f"  reply logged: \"{clean(a.get('answer'), 500)}\"")
    return out


VOICE_MARK = "[voice note] "
REPLY_MARK = " (This is a reply to "


def asked_exactly(body: str, question) -> bool:
    """Is this answer row's question exactly this message? Their words, as
    the brain logs them: optionally "[voice note] " in front, optionally the
    reply-to context ("(This is a reply to …)") after. Never a substring:
    "?" or "yes" is inside many questions."""
    w, q = clean(body, 100000), clean(question, 100000)
    if q.startswith(VOICE_MARK):
        q = q[len(VOICE_MARK):]
    return bool(w) and (q == w or q.startswith(w + REPLY_MARK))


def pair_answers(inbound: list, answers: list) -> dict:
    """{message index: answer row index}. A message with no row stays
    unpaired -- an exact command (a reminder's "yes", "cancel") is stored
    and answered in code with no row, and must not take the next question's.

      1. Exact question matches first, for every message: the first unused
         row at or after it whose question is that message.
      2. A leftover message gets a row only when it is unambiguous: exactly
         one unused row logged after it and before their next message."""
    used, pairs = set(), {}
    for k, m in enumerate(inbound):
        at = utc(m.get("created_at"))
        for i, a in enumerate(answers):
            if i in used or not at or not utc(a.get("created_at")) or utc(a["created_at"]) < at:
                continue
            if asked_exactly(m.get("body") or "", a.get("question")):
                used.add(i)
                pairs[k] = i
                break
    for k, m in enumerate(inbound):
        if k in pairs:
            continue
        at = utc(m.get("created_at"))
        nxt = utc(inbound[k + 1].get("created_at")) if k + 1 < len(inbound) else None
        if not at:
            continue
        window = [i for i, a in enumerate(answers) if i not in used and utc(a.get("created_at"))
                  and at <= utc(a["created_at"]) and (nxt is None or utc(a["created_at"]) < nxt)]
        if len(window) == 1:
            used.add(window[0])
            pairs[k] = window[0]
    return pairs


def msg_tail(mid) -> str:
    """A message id without the chat in it: the last part of
    "{fromMe}_{chat}_{id}"."""
    return str(mid or "").split("_")[-1]


def safe_answer(a: dict) -> dict:
    """An answer row for the JSON file: no ids, and no tool result that can
    hold other people's words (only plan tools' results are kept)."""
    out = {k: v for k, v in (a or {}).items() if k not in ("_id", "user_id", "company_id")}
    tools = []
    for t in out.get("tool_data") if isinstance(out.get("tool_data"), list) else []:
        if not isinstance(t, dict):
            continue
        t = dict(t)
        res = str(t.get("result") or "")
        t["result"] = clean(res, 3000) if t.get("tool") in PLAN_TOOLS else f"(not kept: {len(res)} chars)"
        tools.append(t)
    if "tool_data" in out:
        out["tool_data"] = tools
    return out


def wa_log_event(row: dict, digits: set):
    """One webhook-log row as {at, wa_ts, from_me, type, event, mid}; None
    when it is not this chat. Never the body."""
    raw = str(row.get("raw_body_preview") or "")
    if not any(d in raw for d in digits):
        return None
    try:
        payload = json.loads(raw)
        data = payload.get("data") or {}
        msg = data.get("message") or {}
        inner = msg.get("_data") or {}
        frm = str(msg.get("from") or inner.get("from") or "")
        to = str(msg.get("to") or inner.get("to") or "")
        ident = msg.get("id") if isinstance(msg.get("id"), dict) else {}
        mid = str(ident.get("_serialized") or ident.get("id") or "")
        from_me = bool(msg.get("fromMe") or ident.get("fromMe"))
        ts = msg.get("timestamp") or inner.get("t") or 0
        ev = {"event": payload.get("event"), "from_me": from_me,
              "type": msg.get("type") or inner.get("type"), "wa_ts": int(ts or 0), "mid": mid,
              "chat": to if from_me else frm}
    except Exception:
        m_ts = re.search(r'"t"\s*:\s*(\d{9,})', raw)
        m_id = re.search(r'"_serialized"\s*:\s*"([^"]+)"', raw)
        m_ty = re.search(r'"type"\s*:\s*"(\w+)"', raw)
        ev = {"event": "?", "from_me": bool(re.search(r'"fromMe"\s*:\s*true', raw)),
              "type": m_ty.group(1) if m_ty else "?", "wa_ts": int(m_ts.group(1)) if m_ts else 0,
              "mid": m_id.group(1) if m_id else "", "chat": ""}
    if ev["chat"] and wa_dm.phone_digits(ev["chat"]) not in digits:
        return None
    # Nothing that holds the phone leaves here: the chat as its last 4, the
    # message id as its own last part (the serialized id embeds the chat).
    ev["chat"] = last4(ev["chat"])
    ev["mid"] = msg_tail(ev["mid"])
    ev["at"] = row.get("received_at")
    return ev


async def run(a) -> int:
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        sys.exit("MONGO_URL / DB_NAME are not set — run under `railway run`.")
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    if a.user_id:
        from bson import ObjectId
        q = {"_id": ObjectId(a.user_id) if ObjectId.is_valid(a.user_id) else a.user_id}
    else:
        q = {"email": a.email.strip().lower()}
    user = await db.users.find_one(q, {"name": 1, "email": 1, "phone": 1, "company_id": 1, "role": 1})
    if not user:
        sys.exit("No user with that email / id.")
    uid = str(user["_id"])
    start, end = day_range(a.date)
    rng = {"$gte": start, "$lt": end}

    optins = await db[OPTINS].find({"user_id": uid}).to_list(20)
    digits = {wa_dm.phone_digits(user.get("phone") or "")}
    for o in optins:
        digits |= {wa_dm.phone_digits(o.get("phone") or ""), wa_dm.phone_digits(o.get("chat_digits") or "")}
    digits.discard("")
    chats = chat_ids(sorted(digits))
    msgs = await db.whatsapp_messages.find(
        {"group_id": {"$in": chats}, "is_dm": True, "created_at": rng}
    ).sort([("created_at", 1)]).to_list(5000) if chats else []
    answers = await db[ANSWERS].find({"user_id": uid, "created_at": rng}).sort(
        [("created_at", 1)]).to_list(2000)
    ledger = sorted(await db[LEDGER].find({"user_id": uid, "created_at": rng}).to_list(2000),
                    key=lambda r: utc(r.get("created_at")) or start)
    # A walkthrough open that day takes every DM text first (_punch_dm_turn,
    # one turn at a time per walker): listed so that path is not guessed at.
    walks = [w for w in await db[WALKS].find({"user_id": uid}, {
        "status": 1, "job_name": 1, "created_at": 1, "updated_at": 1, "sent_at": 1}).to_list(500)
        if utc(w.get("created_at")) and utc(w["created_at"]) < end
        and (utc(w.get("updated_at")) or utc(w["created_at"])) >= start]
    hooks = []
    if a.webhook_log and digits:
        # The TTL index on received_at serves the day's range; ordered here.
        async for r in db.whatsapp_webhook_log.find({"received_at": rng},
                                                    {"received_at": 1, "raw_body_preview": 1}):
            ev = wa_log_event(r, digits)
            if ev:
                hooks.append(ev)
        hooks.sort(key=lambda e: utc(e["at"]) or start)

    print(f"{user.get('name')} (user …{uid[-6:]}, {user.get('role')}) · {a.date} America/New_York")
    print("Chats: " + (", ".join(sorted({last4(c) + '@' + c.split('@')[1] for c in chats})) or "none")
          + " · opt-ins: " + (", ".join(f"{o.get('status')} {last4(o.get('phone'))}" for o in optins) or "none"))
    inbound = [m for m in msgs if not m.get("from_me") and str(m.get("sender") or "") != "bot"]
    bot = [m for m in msgs if m.get("from_me") or str(m.get("sender") or "") == "bot"]
    print(f"{len(inbound)} message(s) from them, {len(bot)} from Levelog, {len(answers)} answer row(s), "
          f"{len(ledger)} ledger row(s)" + (f", {len(hooks)} webhook row(s)" if a.webhook_log else ""))
    for w in walks:
        print(f"WALKTHROUGH that day: {w.get('job_name') or '(no job)'} · status {w.get('status')} · "
              f"started {ny(w.get('created_at'))} · last change {ny(w.get('updated_at'))} -- while one "
              f"is open, their texts go to the walk first (one at a time per walker)")
    if not any(isinstance(x.get("timing"), dict) for x in answers):
        print("NOTE: no answer row this day has per-step timestamps (timing). Model-round and "
              "tool times below are NOT known; usage.seconds is the model's total only.")

    # Pair each message with its answer row first, so an outgoing message
    # can be named as the answer to WHICH message (two turns can overlap: a
    # "?" sent while the first answer is still being worked out).
    report = []
    paired = pair_answers(inbound, answers)
    used = set(paired.values())
    pairs = {k: answers[i] for k, i in paired.items()}

    def answers_idx(b):
        """Index of the message whose logged answer this outgoing message carries, or None."""
        body = clean(b.get("body"), 100000)
        for k2, ans in pairs.items():
            head = clean(ans.get("answer"), 100000)[:40]
            if head and head in body:
                return k2
        return None

    def answers_which(b) -> str:
        k2 = answers_idx(b)
        return "" if k2 is None else f" [= the answer to their {ny(inbound[k2].get('created_at'))} message]"

    for k, m in enumerate(inbound):
        at = m.get("created_at")
        nxt = inbound[k + 1].get("created_at") if k + 1 < len(inbound) else end
        print("\n" + "─" * 78)
        print(f"IN {ny(at)}  \"{clean(m.get('body'), 300)}\"  (msg …{msg_tail(m.get('message_id'))[-8:]})")
        hits = [h for h in hooks if not h["from_me"] and h["mid"] and m.get("message_id")
                and h["mid"] == msg_tail(m.get("message_id"))]
        for h in hits[:1]:
            sent = datetime.fromtimestamp(h["wa_ts"], timezone.utc) if h["wa_ts"] else None
            print(f"  WhatsApp sent {ny(sent)} → webhook {ny(h['at'])} ({span(sent, h['at'])}) → "
                  f"stored {ny(at)} ({span(h['at'], at)})")
        ans = pairs.get(k)
        if ans is not None:
            for line in describe_answer(ans, at, a.quote_chars):
                print(line)
        else:
            print("  answer row: NONE paired with this message -- no row asked exactly this, and "
                  "no single row before their next message (an exact command such as a reminder's "
                  "yes, a walkthrough turn, or a turn that never finished)")
        outs = [b for b in bot if utc(b.get("created_at")) and utc(at)
                and utc(at) <= utc(b["created_at"]) < (utc(nxt) or end)]
        tag = f"{ny(at)} message]"
        # What answered THIS message but went out after their next one: its
        # words match this answer row, or it went within 5 s of the row.
        late = [b for b in bot if ans is not None and utc(b.get("created_at")) and utc(nxt)
                and utc(b["created_at"]) >= utc(nxt)
                and (answers_which(b).endswith(tag)
                     or abs((utc(b["created_at"]) - utc(ans.get("created_at"))).total_seconds()) < 5)]
        print(f"  Levelog sent before their next message: {len(outs)}")
        for b in outs:
            print(f"    {ny(b.get('created_at'))} ({span(at, b.get('created_at'))}) "
                  f"\"{clean(b.get('body'), 300)}\"{answers_which(b)}")
        for b in late:
            print(f"    AFTER THEIR NEXT MESSAGE: {ny(b.get('created_at'))} ({span(at, b.get('created_at'))}) "
                  f"\"{clean(b.get('body'), 200)}\"{answers_which(b)}")
        mine = [b for b in outs + late if answers_which(b).endswith(tag)]
        first = (mine or outs or late or [None])[0]
        print(f"  DELTA received → first message out: {span(at, first.get('created_at')) if first else 'none'}"
              + (f" · → answer logged: {span(at, ans.get('created_at'))}" if ans is not None else ""))
        report.append({"inbound": {"at": at, "body": clean(m.get("body"), 1000),
                                   "message_id_tail": msg_tail(m.get("message_id"))[-8:],
                                   "webhook": hits[:1]},
                       "answer": safe_answer(ans) if ans is not None else None,
                       # answers_mine: True = carries THIS message's answer, False = carries
                       # another message's answer, None = can't tell. late: went out after
                       # their next message.
                       "outbound": [{"at": b.get("created_at"), "body": clean(b.get("body"), 1000),
                                     "answers_mine": (None if answers_idx(b) is None else answers_idx(b) == k),
                                     "late": b not in outs}
                                    for b in outs + [x for x in late if x not in outs]]})

    rest = [x for j, x in enumerate(answers) if j not in used]
    if rest:
        print("\n" + "─" * 78 + f"\nANSWER ROWS NOT MATCHED TO A STORED MESSAGE: {len(rest)}")
        for x in rest:
            print(f"  {ny(x.get('created_at'))} path {x.get('path')} question \"{clean(x.get('question'), 160)}\"")
    if ledger:
        print("\n" + "─" * 78 + "\nLEDGER (proactive DM sends and their outcome):")
        for r in ledger:
            print(f"  {ny(r.get('created_at'))} kind {r.get('kind')} status {r.get('status')} "
                  f"finished {ny(r.get('finished_at'))} {clean(r.get('error') or '', 120)}")
    if hooks:
        print("\n" + "─" * 78 + "\nWEBHOOK LOG for this chat (delivery times; no words):")
        for h in hooks:
            sent = datetime.fromtimestamp(h["wa_ts"], timezone.utc) if h["wa_ts"] else None
            print(f"  webhook {ny(h['at'])} · WhatsApp time {ny(sent)} ({span(sent, h['at'])}) · "
                  f"{'FROM LEVELOG' if h['from_me'] else 'from them'} · {h['type']} · {h['event']} "
                  f"· msg …{h['mid'][-8:]}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(jsonable({"user": {"name": user.get("name"), "id_tail": uid[-6:]}, "date": a.date,
                                "messages": report,
                                "unmatched_answers": [safe_answer(x) for x in rest],
                                "ledger": [{k2: r.get(k2) for k2 in ("created_at", "kind", "status",
                                                                     "finished_at", "error")} for r in ledger],
                                "webhook": hooks}), f, indent=2, ensure_ascii=False)
        print(f"\nWrote {a.json}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--email", help="their login email")
    who.add_argument("--user-id", help="their user id")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD, a New York day")
    ap.add_argument("--json", help="also write everything to this JSON file")
    ap.add_argument("--webhook-log", action="store_true",
                    help="also read whatsapp_webhook_log for the day (WaAPI delivery times)")
    ap.add_argument("--quote-chars", type=int, default=160)
    a = ap.parse_args(argv)
    try:
        datetime.strptime(a.date, "%Y-%m-%d")
    except ValueError:
        ap.error("--date must be YYYY-MM-DD")
    return asyncio.run(run(a))


if __name__ == "__main__":
    raise SystemExit(main())
