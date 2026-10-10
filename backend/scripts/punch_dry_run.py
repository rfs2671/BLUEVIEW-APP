"""Walkthrough -> punch list -> chase DRY RUN: a scripted walkthrough in a
super's DM, then the closing words in the job's group, through the real
server code, with no real people, no real database and nothing sent.

macOS / Linux (from backend/):
    python scripts/punch_dry_run.py scripts/dry_run_punch/walk_588_2026_10.json

Windows (PowerShell, from backend\\):
    python scripts\\punch_dry_run.py scripts\\dry_run_punch\\walk_588_2026_10.json

No model is called: captions are read in code, voice notes come as a
"voice" {transcript, lang, confidence} (what transcription would hand over).

WHAT RUNS, AND HOW IT IS ISOLATED
  1. Each DM line goes through _punch_dm_turn exactly as the webhook calls
     it (a photo: has_image; a voice note: the transcript as `voice`).
  2. Each group line goes through _punch_group_message (the call the
     attention worker makes for a message naming a P-id).
  The database is tests/_fake_mongo.FakeDb swapped in for server.db; photo
  download / R2 upload are fakes; every send path is a recorder. DM replies
  are shown; a GROUP post fails the run while the job's punch sends are
  shadow.

SCENARIO (scripts/dry_run_punch/*.json)
  project {_id, name, address, trade_assignments}, walker {name, phone, role},
  people [{key, name, company, phone}],
  dm    [{text?, photo?: true, voice?: {transcript, lang, confidence?},
          expect?: {draft_items, need_trade, unassigned: [trade],
                    sent: "shadow"|"live", items, group_posts}}]
        "{n:words}" in a line -> the draft number of the item whose words
        contain `words` (as the walker would read it off the draft).
  group [{from: KEY|"walker", text}]   "{pid:words}" -> that item's P-id.
  dm_after [{text, contains: [..], not_contains: [..]}]   questions afterwards.
  expect {status, assignee, floor, due_weekday {words: 0-6}, pid_prefix,
          attention_items, closed_by {words: "walker"},
          ready_to_check_then_reopened [words]}

EXIT CODES  0 all as expected · 1 something not · 2 cannot run · 3 posted in shadow
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))
for _k, _v in {"APP_BASE_URL": "https://app.levelog.com", "DB_NAME": "dry_run",
               "MONGO_URL": "mongodb://localhost:27017",
               "JWT_SECRET": "dry-run-only"}.items():
    os.environ.setdefault(_k, _v)

COMPANY = "co_dry_run"
GROUP = "120363099999999902@g.us"
WALKER_ID = "u_walker"
FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 256
SEND_PATHS = ("send_whatsapp_message", "send_whatsapp_dm", "_waapi_post_raw",
              "_react_to_message", "_react_or_say", "_punch_send_photo")


class ScenarioError(Exception):
    pass


def load(path: str) -> dict:
    sc = json.loads(Path(path).read_text(encoding="utf-8"))
    if sc.get("placeholder"):
        raise ScenarioError(sc.get("about") or "placeholder scenario: nothing to run yet")
    keys = {p["key"] for p in sc.get("people") or []}
    for g in sc.get("group") or []:
        if g["from"] != "walker" and g["from"] not in keys:
            raise ScenarioError(f"group line: unknown sender {g['from']!r}")
    return sc


def world(sc: dict):
    from tests._fake_mongo import FakeDb
    from lib import wa_sender_map
    proj = {**sc["project"], "company_id": COMPANY}
    w = sc["walker"]
    db = FakeDb(
        projects=[proj],
        users=[{"_id": WALKER_ID, "company_id": COMPANY, "name": w["name"], "phone": w["phone"],
                "role": w.get("role", "admin"), "account_status": "approved"}],
        checkins=[],
        notification_preferences=[{
            "_id": "np_dry", "user_id": None, "project_id": str(proj["_id"]), "scope": "project",
            "whatsapp_project": {"gc_group_id": GROUP, "gc_group_confirmed": True,
                                 "punch_sends": sc.get("punch_sends") or "shadow"}}],
        attention_items=[],
    )
    db[wa_sender_map.COLLECTION].rows.extend(
        {"_id": f"m_{p['key'].lower()}", "company_id": COMPANY, "person_name": p["name"],
         "sub_company": p["company"], "sender_jid": f"{p['phone']}@c.us"}
        for p in sc.get("people") or [])
    return db, proj


def _ident(proj: dict, sc: dict) -> dict:
    return {"user": {"_id": WALKER_ID, "name": sc["walker"]["name"]}, "user_id": WALKER_ID,
            "company_id": COMPANY, "role": sc["walker"].get("role", "admin"), "projects": [proj]}


def _draft_number(draft: str, words: str) -> int:
    """The number the walker reads off the latest draft for an item."""
    for line in draft.splitlines():
        m = re.match(r"^(\d+)\. ", line)
        if m and words.lower() in line.lower():
            return int(m.group(1))
    raise ScenarioError(f"no draft line with {words!r} in:\n{draft}")


def _find(rows: List[dict], words: str) -> dict:
    hits = [r for r in rows if words.lower() in (r.get("text") or "").lower()]
    if len(hits) != 1:
        raise ScenarioError(f"{len(hits)} punch items match {words!r}")
    return hits[0]


async def run(sc: dict) -> dict:
    import server
    from lib import punch

    db, proj = world(sc)
    dm_out: List[str] = []
    group_out: List[tuple] = []
    reacts: List[str] = []
    walker_chat = f"{sc['walker']['phone']}@c.us"

    def recorder(name):
        async def _rec(*a, **k):
            chat = a[0] if a else k.get("chat_id") or k.get("to")
            text = a[1] if len(a) > 1 else k.get("message") or k.get("text") or ""
            if name == "_react_to_message":
                reacts.append(str(a[2] if len(a) > 2 else ""))
            elif str(chat) == walker_chat:
                dm_out.append(str(text))
            else:
                group_out.append((name, chat, text))
            return True
        return _rec

    async def fake_download(parsed):
        return FAKE_JPEG

    uploads: List[str] = []

    def fake_upload(data, key, ctype):
        uploads.append(key)
        return f"https://r2.invalid/{key}"

    patches = [patch.object(server, "db", db),
               patch.object(server, "download_image", fake_download),
               patch.object(server, "_upload_to_r2", fake_upload),
               patch.object(server, "_presign_r2_get", lambda key, ttl=900: f"https://r2.invalid/{key}?sig")]
    patches += [patch.object(server, n, recorder(n)) for n in SEND_PATHS if hasattr(server, n)]
    ident = _ident(proj, sc)
    checks: List[tuple] = []          # (ok, what)
    transcript: List[str] = []
    for p in patches:
        p.start()
    try:
        assert server.db is db, "not isolated"
        draft = ""
        for i, line in enumerate(sc["dm"], 1):
            exp = line.get("expect") or {}
            if "text" in line or line.get("photo") or line.get("voice"):
                text = line.get("text") or ""
                text = re.sub(r"\{n:([^}]+)\}", lambda m: str(_draft_number(draft, m.group(1))), text)
                voice = None
                if line.get("voice"):
                    v = line["voice"]
                    voice = {"transcript": v["transcript"], "english": v["transcript"],
                             "lang": v.get("lang") or "english",
                             "confidence": v.get("confidence", 0.9)}
                parsed = {"has_image": bool(line.get("photo")), "message_id": f"dm{i}",
                          "message_id_serialized": f"false_{walker_chat}_dm{i}"}
                before = len(dm_out)
                handled = await server._punch_dm_turn(ident, walker_chat, parsed, text, voice=voice)
                said = dm_out[before:]
                shown = text or ("🎤 " + voice["transcript"] if voice else "")
                transcript.append(f"> {'📷 ' if line.get('photo') else ''}{shown}")
                transcript.extend("  " + s.replace("\n", "\n  ") for s in said)
                if not handled:
                    transcript.append("  (not a walkthrough turn)")
                    checks.append((False, f"dm {i}: not handled: {shown!r}"))
                for s in said:
                    if "(draft)" in s:
                        draft = s
                if said and said[-1].startswith("Who gets what?"):
                    draft_assign = said[-1]
                    for t in exp.get("unassigned") or []:
                        checks.append((f"• {t} → ?" in draft_assign,
                                       f"dm {i}: {t} has no suggested assignee"))
            if "draft_items" in exp:
                m = re.search(r"· (\d+) items? \(draft\)", draft)
                checks.append((bool(m) and int(m.group(1)) == exp["draft_items"],
                               f"dm {i}: draft has {exp['draft_items']} items"))
            if "need_trade" in exp:
                m = re.search(r"(\d+) needs? a trade", draft)
                got = int(m.group(1)) if m else 0
                checks.append((got == exp["need_trade"], f"dm {i}: {exp['need_trade']} need a trade (got {got})"))
            if "sent" in exp:
                last = dm_out[-1] if dm_out else ""
                shadow = last.startswith("Punch sends are in shadow mode")
                checks.append((shadow == (exp["sent"] == "shadow"), f"dm {i}: sent in {exp['sent']}"))
            if "items" in exp:
                n = len(db[punch.COLLECTION].rows)
                checks.append((n == exp["items"], f"dm {i}: {exp['items']} punch items (got {n})"))
            if "group_posts" in exp:
                checks.append((len(group_out) == exp["group_posts"],
                               f"dm {i}: {exp['group_posts']} group posts (got {len(group_out)})"))

        rows = db[punch.COLLECTION].rows
        seen_ready: Dict[str, bool] = {}
        for j, g in enumerate(sc.get("group") or [], 1):
            text = re.sub(r"\{pid:([^}]+)\}", lambda m: _find(rows, m.group(1))["pid"], g["text"])
            if g["from"] == "walker":
                phone, name = sc["walker"]["phone"], sc["walker"]["name"]
            else:
                p = next(x for x in sc["people"] if x["key"] == g["from"])
                phone, name = p["phone"], p["name"]
            msg = {"body": text, "sender": phone, "sender_jid": f"{phone}@c.us",
                   "message_id": f"g{j}"}
            ctx = {"company_id": COMPANY, "project_id": str(proj["_id"]), "group_id": GROUP,
                   "cache": {}}
            handled = await server._punch_group_message(msg, ctx)
            transcript.append(f"[group] {name}: {text}" + ("" if handled else "   (not handled)"))
            checks.append((handled, f"group {j}: handled {text!r}"))
            for r in rows:
                if r.get("status") == "ready_to_check":
                    seen_ready[r["pid"]] = True
        # Questions in the DM afterwards.
        for k, q in enumerate(sc.get("dm_after") or [], 1):
            sub = lambda t: re.sub(r"\{pid:([^}]+)\}", lambda m: _find(rows, m.group(1))["pid"], t)
            text = sub(q["text"])
            before = len(dm_out)
            await server._punch_dm_turn(ident, walker_chat, {"has_image": False,
                                        "message_id": f"q{k}"}, text)
            said = "\n".join(dm_out[before:])
            transcript.append(f"> {text}")
            transcript.append("  " + said.replace("\n", "\n  "))
            for c in q.get("contains") or []:
                c = sub(c)
                checks.append((c in said, f"ask {k}: answer has {c!r}"))
            for c in q.get("not_contains") or []:
                c = sub(c)
                checks.append((not re.search(re.escape(c) + r"(?!\d)", said),
                               f"ask {k}: answer leaves out {c!r}"))
    except ScenarioError as e:
        raise ScenarioError(f"{e}\n\n" + "\n".join(transcript)) from None
    finally:
        for p in patches:
            p.stop()

    rows = db[punch.COLLECTION].rows
    exp = sc.get("expect") or {}
    for words, st in (exp.get("status") or {}).items():
        r = _find(rows, words)
        checks.append((r["status"] == st, f"{words}: status {st} (got {r['status']})"))
    for words, who in (exp.get("assignee") or {}).items():
        r = _find(rows, words)
        got = (r.get("assignee") or {}).get("name")
        checks.append((got == who, f"{words}: assigned to {who} (got {got})"))
    for words, f in (exp.get("floor") or {}).items():
        r = _find(rows, words)
        checks.append((r.get("floor") == f, f"{words}: floor {f} (got {r.get('floor')})"))
    from datetime import date
    for words, wd in (exp.get("due_weekday") or {}).items():
        r = _find(rows, words)
        d = (r.get("due") or {}).get("due_at")
        got = date.fromisoformat(d[:10]).weekday() if d else None
        checks.append((got == wd, f"{words}: due weekday {wd} (got {got}, {d})"))
    if exp.get("pid_prefix"):
        checks.append((all(r["pid"].startswith(exp["pid_prefix"]) for r in rows),
                       f"every id starts {exp['pid_prefix']}"))
    if "attention_items" in exp:
        att = [a for a in db.attention_items.rows if a.get("punch_id")]
        checks.append((len(att) == exp["attention_items"],
                       f"{exp['attention_items']} attention items (got {len(att)})"))
        ok = all(a["owner"].get("status") == "resolved" and a["owner"].get("jid")
                 and (a.get("due") or {}).get("due_at") for a in att)
        checks.append((ok, "every attention item has a resolved owner with a WhatsApp id and a due day"))
    for words, who in (exp.get("closed_by") or {}).items():
        r = _find(rows, words)
        want = WALKER_ID if who == "walker" else who
        checks.append((r.get("closed_by") == want and r.get("closed_at"),
                       f"{words}: closed by {who}"))
        checks.append((bool((r.get("completion") or {}).get("quote")),
                       f"{words}: completion evidence kept"))
    for words in exp.get("ready_to_check_then_reopened") or []:
        r = _find(rows, words)
        acts = [h.get("action") for h in r.get("history") or []]
        checks.append((acts[-2:] == ["ready_to_check", "open"],
                       f"{words}: ready to check, then reopened ({' → '.join(acts)})"))
        a = next(x for x in db.attention_items.rows if x.get("punch_id") == r["pid"])
        checks.append((a["status"] == "open", f"{words}: chase resumes (attention {a['status']})"))
    photos = sum(1 for r in rows if r.get("photo_key")) + sum(len(r.get("extra_photos") or []) for r in rows)
    return {"checks": checks, "transcript": transcript, "group_posts": group_out,
            "reacts": reacts, "uploads": uploads, "photos_on_items": photos,
            "rows": rows, "mode": sc.get("punch_sends") or "shadow"}


def report(res: dict) -> int:
    print("\n".join(res["transcript"]))
    print()
    print(f"👍 reactions: {len(res['reacts'])} · photos stored: {len(res['uploads'])} "
          f"· photos on sent items: {res['photos_on_items']}")
    print()
    print("Punch items:")
    for r in sorted(res["rows"], key=lambda r: r["seq"]):
        print(f"  {r['pid']:<10} {r['status']:<15} {r.get('trade') or '?':<11} "
              f"fl {r.get('floor')!s:<4} {(r.get('assignee') or {}).get('name') or '':<12} "
              f"due {(r.get('due') or {}).get('due_at') or '-':<10} {'🎤 ' if r.get('voice') else ''}{r['text']}")
    print()
    bad = [w for ok, w in res["checks"] if not ok]
    for ok, w in res["checks"]:
        print(f"  {'✓' if ok else '✗'} {w}")
    print(f"\n{len(res['checks']) - len(bad)}/{len(res['checks'])} as expected")
    if res["mode"] == "shadow" and res["group_posts"]:
        print(f"POSTED IN SHADOW: {res['group_posts']}")
        return 3
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    a = ap.parse_args(argv)
    try:
        sc = load(a.scenario)
    except ScenarioError as e:
        print(f"Cannot run: {e}")
        return 2
    try:
        res = asyncio.run(run(sc))
    except ScenarioError as e:
        print(f"Cannot run: {e}")
        return 2
    return report(res)


if __name__ == "__main__":
    sys.exit(main())
