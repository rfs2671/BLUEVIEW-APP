"""Replay the dm_eval failures through the real DM path, then score them.

    python scripts/dm_eval_replay.py            # transcript + dm_eval report
    python scripts/dm_eval_replay.py --json out.json

The dm_eval run of 2026-10-20 (30 days, 32 live answers) found five shapes
of failure. This sends THE SAME QUESTIONS, in the same order, through
server._process_whatsapp_message on a fake database (the 588 crew of
Mon 9:01 AM, the SSP-011.00 window-protection sheet), and scores what goes
out with lib/dm_eval -- so a fix can be measured before it ships: run it on
main and on the fix branch and compare.

THE MODEL IS REPLAYED, NOT CALLED. Where the live answer came from the model
(the job agent), the stub returns what the live one said for that question,
so the code around it -- routing, guards, the send -- is what is measured.
Nothing is sent: WaAPI is the test wire, and no database is touched.

Every line printed is scrubbed (lib/dm_eval.scrub); the crew names are the
test fixture's ("Arkon Worker 3"), not people.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
for k, v in (("MONGO_URL", "mongodb://localhost:27017"), ("DB_NAME", "dm_eval_replay"),
             ("JWT_SECRET", "dm_eval_replay"), ("APP_BASE_URL", "https://app.levelog.com")):
    os.environ.setdefault(k, v)

import server  # noqa: E402
from lib import dm_eval, wa_headcount  # noqa: E402
from tests.test_dm_show_sheet import MEDIA_URL, SHEETS, WINDOW  # noqa: E402
from tests.test_dm_short_answers import CHAT, _Site, _payload  # noqa: E402
from tests.test_dm_subs_on_site import _crew  # noqa: E402
from tests.test_whatsapp_dm_assistant import _db, _optin  # noqa: E402
from tests.test_whatsapp_phase1_foundations import ADMIN_PHONE, _Ctx, _run  # noqa: E402

# What the live job agent said, by question (dm_eval, Oct 20).
CHECKLIST_LIVE = "Checklist creation or cancellation is done in the app."
LIVE_AGENT = {
    "any info about window protection at ssp for 588?": WINDOW,
    "cancel checklist": CHECKLIST_LIVE,
    "done": CHECKLIST_LIVE,
}

# The conversations, in order. Each is one chat; turns follow one another.
SCENARIOS = {
    "subs": ["Update on workers 588", "How many subs on site?", "How many companies on site"],
    "show_me": ["Any info about window protection at ssp for 588?", "Show me", "Show me details",
                "send it", "the drawing", "picture"],
    "done": ["Cancel checklist", "Done"],
}


class _Replay(_Site):
    """The 588 crew, the SSP sheets, and the agent as it answered live."""

    def __init__(self):
        self.agent_calls, self.llm_calls, self.reactions = [], [], []
        self.db = _db()
        _optin(self.db, "u_admin", ADMIN_PHONE)
        _crew(self.db)
        self.n = 0

    def say(self, c, body, quoted=None, from_bot=False, llm=None, key=None):
        async def agent(**kw):
            self.agent_calls.append(kw)
            reply = LIVE_AGENT.get(" ".join(str(kw.get("body") or "").lower().split()), WINDOW)
            kw["tool_trace"].append({"tool": "replay", "result": reply})
            return reply

        async def find(project_id, sheet_q):
            row = SHEETS.get(sheet_q.upper())
            return [row] if row else []

        async def media(chat, page):
            return MEDIA_URL
        async def dm_llm(system, user_text):
            # The headcount rewording, replayed as a model that keeps the
            # fixed words: the check passes, nothing is a fallback that a
            # live model would not have caused.
            self.llm_calls.append((system, user_text))
            return user_text if system == wa_headcount.PHRASE_PROMPT else "general"

        async def react(*a, **k):
            return True

        async def scope(body):
            return "project"
        self.n += 1
        with patch.object(server, "_run_group_agent", agent), \
                patch.object(server, "_find_named_sheet", find), \
                patch.object(server, "_plan_media_url", media), \
                patch.object(server, "_dm_llm", dm_llm), \
                patch.object(server, "_react_to_message", react), \
                patch.object(server, "_dm_scope", scope), \
                patch.object(server, "LLM_API_KEY", "replay"):
            _run(server._process_whatsapp_message(_payload(CHAT, body, f"m{self.n}", quoted, from_bot)))


def _sent(c, before: int) -> str:
    """What this turn put on the wire: text, or "[image: caption]"; "" when
    nothing went out (which the replay test fails on)."""
    out = []
    for p in c.wire.calls[before:]:
        if "mediaUrl" in p:
            out.append(f"[image: {p.get('caption') or ''}]")
        elif "message" in p:
            out.append(p["message"])
    return " | ".join(out)


def replay() -> dict:
    transcript, rows = [], []
    for name, turns in SCENARIOS.items():
        r = _Replay()
        with _Ctx(db=r.db) as c:
            for q in turns:
                before = len(c.wire.calls)
                r.say(c, q)
                transcript.append({"scenario": name, "q": q, "a": dm_eval.scrub(_sent(c, before))})
        for row in r.db[server.DM_ANSWERS].rows:
            rows.append({**row, "user_id": f"{name}:{row.get('user_id')}"})
    return {"transcript": transcript, "report": dm_eval.score(rows)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", help="write transcript + report as JSON")
    a = ap.parse_args(argv)
    out = replay()
    for t in out["transcript"]:
        print(f"[{t['scenario']}] {t['q']}\n    -> {t['a'] or '(nothing sent)'}")
    print()
    print(dm_eval.render(out["report"]))
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str),
                                encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
