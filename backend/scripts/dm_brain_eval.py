"""Replay every real DM through the new brain on BOTH DeepInfra models. READ-ONLY.

    railway run python scripts/dm_brain_eval.py --days 30
    railway run python scripts/dm_brain_eval.py --days 30 --email you@company.com --out dm_brain_eval

Needs MONGO_URL / DB_NAME and QWEN_API_KEY (DeepInfra -- the key the vision
calls already use; `railway run` brings all three). The models are
DM_BRAIN_MODEL (default Qwen/Qwen3.8-Flash) and DM_BRAIN_ESCALATE_MODEL
(default Qwen/Qwen3.8-Max). Only DM_BRAIN_MODEL runs unless --models names
more (--models Qwen/Qwen3.8-Flash,Qwen/Qwen3.8-Max compares both).

FIRST, A PREFLIGHT (nothing else runs if it fails, unless --skip-check):
  * GET {base}/models: each model id must be on DeepInfra's list (the Qwen
    3.8 ids it has are printed when one is not);
  * one tiny tool-calling request per model: it must come back as a tool
    call, else that model can't run the brain.

FIXED CASES (FIXED_CASES), each with what is expected and PASS / FAIL checks,
run on each model:
  Tue Oct 20, 9:02 AM:   "Update on 588", "Dot and Akron", "Arkon is framer"
  Tue Oct 20, 12:28 PM:  the walk ("All of the above is for 3rd floor moving
                         up to 4th now", on a walk rebuilt in memory),
                         "How many days hvac worked in 588", the no-deflect rule
  Languages:             a Spanish and a Yiddish DM (the answer in their language)

THEN every answer in whatsapp_dm_answers (the last --days), oldest first: the
question as asked, this DM's messages before it, the answer that went out
then (the old pipeline), and each model's answer -- with the tools it called,
its quality checks, seconds and cost.

QUALITY (per DM, per model; automatic -- the side-by-side is for your eyes):
  answered      not "can't answer" / sent elsewhere, not a failure text
  evidence      every number and id came from the tools (or it said so)
  whole         not cut off (finish "length", an open *, nothing after tools)
  actions       "sent / saved / cancelled / done" only with the tool that did it
  language      the answer is in the language of the question (EN/ES/YI)
plus each fixed case's own checks. COST is DeepInfra's own estimated_cost
from each response's usage (shown as "n/a" if it sends none); SECONDS is the
model time for the whole turn (tool calls included).

NOTHING IS WRITTEN AND NOTHING IS SENT:
  * the database is wrapped read-only (every insert / update / delete is
    dropped and counted -- the count is printed);
  * the brain runs in dry-run: a proposed change, a reminder, a sheet or a
    report says what it WOULD do; no state is stored;
  * WhatsApp sends and reactions are stubbed out.

THE PROGRESS ENGINE'S CASES (PROGRESS_CASES, after the fixed cases; skip with
--no-progress, only them with --progress-only): work_status ("What's holding
up drywall on Floor 3?"), report_inspection (passed, failed, "didn't pass" --
never recorded as passed --, ambiguous, and a question that must record
nothing), schedule_lookahead (no rate or forecast), and proposed_sequence
approve by a CP (must be refused; --cp-email names a real CP, else the role is
replaced on the fixed cases' person). Dry-run: nothing is recorded.

TWO OFFLINE MODES, NO DATABASE READ OR WRITTEN:
    python scripts/dm_brain_eval.py --schedule-file "C:/path/export.xer"
        a P6 XER / MS Project XML / XLSX export as the importer reads it: the
        activities, the file's own logic (predecessor counts, links left
        unresolved) and the work package + level each maps to. No model.
    railway run python scripts/dm_brain_eval.py --signoff "C:/path/signoff.pdf"
        the sign-off path on a local file: page 1 rendered, RapidOCR text, the
        vision model's claim (QWEN_API_KEY), the result read back from the
        page, agreement, and what would be stored. Without a key:
        --claim failed [--quote "RESULT: REJECTED"] checks a claim you give.

The tools read the records as they are NOW; compare behavior, not numbers.
Writes <out>/side_by_side.md (for review) and <out>/results.jsonl. Phone
numbers are scrubbed; names are kept (it's your data, for your review).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


class _ReadOnlyCollection:
    _READS = ("find", "find_one", "aggregate", "count_documents", "distinct",
              "estimated_document_count", "list_indexes", "index_information", "name")

    def __init__(self, coll, dropped: list):
        self._c, self._dropped = coll, dropped

    def __getattr__(self, name):
        if name in self._READS:
            return getattr(self._c, name)
        if name.startswith(("insert", "update", "replace", "delete", "find_one_and", "bulk_write",
                            "create_index", "drop")):
            async def _blocked(*a, **k):
                self._dropped.append(f"{self._c.name}.{name}")
                return SimpleNamespace(inserted_id=None, inserted_ids=[], modified_count=0,
                                       matched_count=0, deleted_count=0, upserted_id=None,
                                       acknowledged=False)
            return _blocked
        return getattr(self._c, name)


class ReadOnlyDb:
    """A motor database that reads and never writes."""

    def __init__(self, db):
        self._db = db
        self.dropped: list = []

    def __getitem__(self, name):
        return _ReadOnlyCollection(self._db[name], self.dropped)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return _ReadOnlyCollection(getattr(self._db, name), self.dropped)


# ── THE FIXED CASES ──────────────────────────────────────────────────────────

FIXED_CASES = [
    {"id": "update_588", "kind": "dm", "when": "Tue Oct 20, 9:02 AM", "said": "Update on 588",
     "old": "588 Update / DOB Status: / Want the full list?",
     "expected": "A real update in a few lines -- who is on site plus at least one more record "
                 "(DOB/DOT, open items, coming up) -- no empty heading, nothing cut."},
    {"id": "dot_and_akron", "kind": "dm", "when": "Tue Oct 20, 9:02 AM", "said": "Dot and Akron",
     "old": "No Dot or Akron sub",
     "expected": "DOT read as the agency (DOT records for the job) and \"Akron\" matched to Arkon "
                 "on the subs list; never \"no Dot or Akron sub\"."},
    {"id": "arkon_framer", "kind": "dm", "when": "Tue Oct 20, 9:02 AM", "said": "Arkon is framer",
     "old": "I don't have that in the records.",
     "expected": "Understood as a fact about the sub: proposes saving Arkon's trade as framing "
                 "(set_sub_trade) and asks for yes; nothing is saved without it."},
    {"id": "walk_location", "kind": "walk", "when": "Tue Oct 20, 12:28-2:08 PM (walk)",
     "said": "All of the above is for 3rd floor moving up to 4th now",
     "old": "Tagged #2-#4 only (the photos since the last text) and added the words as a note.",
     "expected": "Every untagged photo since the last location (here #1-#4) -> 3rd floor; no note; "
                 "the next photos default to 4th floor, and the reply says so."},
    {"id": "hvac_days", "kind": "dm", "when": "Tue Oct 20, 12:28-2:08 PM",
     "said": "How many days hvac worked in 588",
     "old": "... check with the site manager.",
     "expected": "HVAC -> the HVAC sub(s) on 588 -> distinct days on site, with the date range "
                 "(and man-days); never sends them to someone else."},
    {"id": "no_deflect", "kind": "dm", "when": "rule 3",
     "said": "How many days did the elevator guys work on 588",
     "old": "(the rule; the old pipeline answered such questions with 'check with ...')",
     "expected": "Calls the tools that could hold it (sub_attendance with a trade, find_sub) before "
                 "any \"I don't have that\"; never \"check with X\"; a can't-answer says what it "
                 "checked and is logged with the tools tried."},
    {"id": "spanish", "kind": "dm", "when": "language", "said": "¿Cuántos trabajadores hay hoy en 588?",
     "old": "(language case)", "lang": "es",
     "expected": "Today's headcount at 588 from the check-ins, answered in Spanish."},
    {"id": "yiddish", "kind": "dm", "when": "language", "said": "וויפל ארבעטער זענען היינט אויף 588?",
     "old": "(language case)", "lang": "yi",
     "expected": "Today's headcount at 588 from the check-ins, answered in Yiddish (Hebrew letters)."},
]
#: The six that must all PASS before merge.
REQUIRED = ("update_588", "dot_and_akron", "arkon_framer", "walk_location", "hvac_days", "no_deflect")

# ── THE PROGRESS ENGINE'S CASES (integrated progress engine) ──────────────────
#
# Run after FIXED_CASES (skip with --no-progress; only these: --progress-only),
# dry-run like every case: report_inspection says what it WOULD record, a
# proposed sequence what it WOULD approve. `as_role`: run as an account of that
# role -- the person named by --cp-email, else the fixed cases' person with the
# role replaced (their jobs are then still theirs: said in the case's detail).
PROGRESS_CASES = [
    {"id": "work_status_drywall", "kind": "dm", "when": "progress", "said": "What's holding up drywall on Floor 3 at 588?",
     "old": "(new tool: work_status)",
     "expected": "work_status for drywall on floor 3 of 588; what the records say and what normally comes first; "
                 "no percent, no cause the records don't hold."},
    {"id": "inspection_passed", "kind": "dm", "when": "inspection", "said": "Plumbing rough passed on floor 3 at 588",
     "old": "(new tool: report_inspection)",
     "expected": "report_inspection would record plumbing rough, Floor 3, passed, as reported, not verified."},
    {"id": "inspection_failed", "kind": "dm", "when": "inspection", "said": "Hydro failed on floor 5 at 588",
     "old": "(new tool: report_inspection)", "expected": "Would record hydro, Floor 5, FAILED; never passed."},
    {"id": "inspection_didnt_pass", "kind": "dm", "when": "inspection",
     "said": "Plumbing rough didn't pass on floor 3 at 588", "old": "(new tool: report_inspection)",
     "expected": "Never recorded as passed: recorded as failed, or kept UNRESOLVED with one short question."},
    {"id": "inspection_ambiguous", "kind": "dm", "when": "inspection",
     "said": "Plumbing rough on 3 at 588 went alright I guess", "old": "(new tool: report_inspection)",
     "expected": "No result recorded; one short question (passed, failed, partly, booked?)."},
    {"id": "inspection_question", "kind": "dm", "when": "inspection",
     "said": "Did the plumbing rough pass on floor 3 at 588?", "old": "(new tool: report_inspection)",
     "expected": "A question, answered from the records; nothing recorded or kept."},
    {"id": "schedule_lookahead", "kind": "dm", "when": "schedule",
     "said": "What's on the schedule at 588 for the next two weeks?", "old": "(new tool: schedule_lookahead)",
     "expected": "schedule_lookahead (14 days): the file's dates and logic beside what the logs report, or that no "
                 "confirmed schedule is on file; no rate, forecast or estimated date."},
    # A refusal is the right answer here, so "answered" (no can't-answer) is not asked of it.
    {"id": "cp_approve_sequence", "kind": "dm", "when": "role", "as_role": "cp", "skip_quality": ("answered",),
     "said": "Approve the sequence for 588", "old": "(owner ruling 2026-11-09)",
     "expected": "Refused for a CP: approving a sequence is for a PM or an admin; nothing approved."},
]
_RECORDED = re.compile(r"\(eval\) Would record\. Noted as reported by .*?, (passed|failed|partial|scheduled)(?:,|\.)")


def _would_record(trace: list) -> List[str]:
    """The results report_inspection said it WOULD record this turn."""
    out = []
    for t in trace:
        if t.get("tool") == "report_inspection":
            m = _RECORDED.search(str(t.get("result") or ""))
            if m:
                out.append(m.group(1))
    return out


def _progress_checks(case_id: str, reply: str, trace: list) -> Dict[str, bool]:
    """The progress cases' own checks, from the reply and the tools' results."""
    tools = [t["tool"] for t in trace]
    low = reply.lower()
    rec = _would_record(trace)
    kept = any("Would keep it as UNRESOLVED" in str(t.get("result") or "") for t in trace)
    if case_id == "work_status_drywall":
        ws = [t for t in trace if t["tool"] == "work_status"]
        return {"work_status called": bool(ws),
                "for drywall on floor 3": any(re.search(r"dry ?wall", str((t.get("args") or {}).get("work") or ""), re.I)
                                              and re.search(r"\b3\b|third", str((t.get("args") or {}).get("level") or ""))
                                              for t in ws),
                "no percent": "%" not in reply}
    if case_id == "inspection_passed":
        return {"report_inspection called": "report_inspection" in tools, "would record passed": rec == ["passed"]}
    if case_id == "inspection_failed":
        return {"would record failed": rec == ["failed"], "never passed": "passed" not in rec}
    if case_id == "inspection_didnt_pass":
        return {"never recorded as passed": "passed" not in rec,
                "recorded failed, or kept unresolved, or asked": rec == ["failed"] or kept or "?" in reply}
    if case_id == "inspection_ambiguous":
        return {"no result recorded": not rec, "one short question": "?" in reply}
    if case_id == "inspection_question":
        return {"nothing recorded": not rec, "nothing kept": not kept}
    if case_id == "schedule_lookahead":
        return {"schedule_lookahead called": "schedule_lookahead" in tools,
                "no rate or forecast": not re.search(r"crew days?|at that rate|per level|forecast|estimated? finish", low)}
    if case_id == "cp_approve_sequence":
        approved = any("Would approve" in str(t.get("result") or "") for t in trace)
        refused = any(str(t.get("result") or "").startswith("REFUSED") for t in trace)
        return {"nothing approved": not approved,
                "refused, or never asked to approve": refused or not any(
                    t["tool"] == "proposed_sequence" and (t.get("args") or {}).get("approve") for t in trace),
                "says a PM or admin does it": bool(re.search(r"\bpm\b|project manager|admin", low))}
    return {}


# ── --schedule-file: a real export, parsed and mapped, nothing written ────────

def schedule_file_report(path: str, limit: int = 60) -> List[str]:
    """What the importer makes of a P6 XER / MS Project XML / XLSX export: the
    activities, the file's own logic (predecessor counts, unresolved links),
    and the work package and level each activity maps to. Reads the file
    only."""
    from collections import Counter
    from lib import progress_plan, schedule_import, work_state
    p = Path(path)
    doc = schedule_import.parse_schedule(p.name, p.read_bytes())
    acts = doc.get("activities") or []
    work = [a for a in acts if a.get("kind") != "summary"]
    no_logic = [a for a in work if not isinstance(a.get("predecessors"), list)]
    linked = [a for a in work if isinstance(a.get("predecessors"), list)]
    links = sum(len(a["predecessors"]) for a in linked)
    lost = sum(int(a.get("predecessors_unresolved") or 0) for a in acts)
    out = [f"File: {p.name}  format={doc.get('format')}  confidence={doc.get('confidence')}  "
           f"data date={doc.get('data_date') or 'not stated'}  project={doc.get('project_name') or '-'}",
           f"Activities: {len(acts)} ({', '.join(f'{k} {n}' for k, n in sorted(Counter(a.get('kind') for a in acts).items()))})",
           f"Logic: {len(linked)} of {len(work)} non-summary activities carry the file's links ({links} links); "
           f"{len(no_logic)} carry none (unknown, not 'no dependencies'); "
           f"{sum(1 for a in linked if not a['predecessors'])} list no predecessor.",
           f"Unresolved links (left out, counted on the activity): {lost}"]
    for w in doc.get("warnings") or []:
        out.append(f"  warning: {w}")
    mapped, packages = 0, Counter()
    rows = []
    for a in work:
        place = progress_plan.activity_place(a)
        ok = bool(place["nodes"] and place["levels"])
        mapped += ok
        for n in place["nodes"]:
            packages[work_state.node_label(n)] += 1
        preds = a.get("predecessors")
        rows.append(f"  {str(a.get('id'))[:14]:14} {str(a.get('name'))[:44]:44} {str(a.get('kind'))[:9]:9} "
                    f"{a.get('current_start') or a.get('baseline_start') or '-'} > "
                    f"{a.get('current_finish') or a.get('baseline_finish') or '-'}  "
                    f"preds={'?' if preds is None else len(preds)}"
                    f"{'+' + str(a.get('predecessors_unresolved')) + ' unresolved' if a.get('predecessors_unresolved') else ''}  "
                    f"-> {', '.join(work_state.node_label(n) for n in place['nodes']) or 'no work package'}"
                    f" @ {', '.join(work_state.level_label(lv) for lv in place['levels']) or 'no level'}"
                    f"{' (trade only)' if place['generic'] else ''}")
    out.append(f"Mapped to a work package AND a level: {mapped} of {len(work)}; "
               f"{len(work) - mapped} not (they appear in no lookahead line about a level).")
    if packages:
        out.append("Work packages: " + "; ".join(f"{k} {n}" for k, n in packages.most_common()))
    out.append(f"Activities (first {min(limit, len(rows))} of {len(rows)}):")
    return out + rows[:limit]


# ── --signoff: the document path's read and check on a local file ─────────────

async def _signoff_vision(server, page: bytes) -> Optional[dict]:
    """The vision model's reading, the same prompt the live path sends; not
    metered (nothing is written)."""
    import base64
    from lib import inspection_reports as IR
    from datetime import date as _date
    async with server.ServerHttpClient(timeout=60.0) as client:
        resp = await client.post(
            f"{server.QWEN_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {server.QWEN_API_KEY}", "Content-Type": "application/json"},
            json={"model": server.QWEN_MODEL, "max_tokens": 300, "temperature": 0, "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(page).decode()}},
                {"type": "text", "text": IR.DOCUMENT_PROMPT}]}]})
        if resp.status_code >= 400:
            return {"error": f"vision HTTP {resp.status_code}"}
        said = resp.json()["choices"][0]["message"]["content"]
    return {"raw": said, "read": IR.parse_document(said, _date.today())}


async def signoff_report(server, path: str, claim: Optional[str] = None, quote: Optional[str] = None) -> List[str]:
    """The document path on a local file: render the page, OCR it, ask the
    vision model (unless --claim gives the claim), and the check -- the
    model's claim, the validated result, agreement, and what would be stored.
    Nothing is stored or sent."""
    from lib import inspection_reports as IR
    raw = Path(path).read_bytes()
    page, ext, _ctype = server._inspection_doc_page(raw)
    if not page:
        return [f"{path}: not a PDF or an image the live path can read."]
    ocr = server._inspection_doc_ocr(page)
    out = [f"File: {Path(path).name} ({ext}, page 1 rendered)", "OCR text (RapidOCR):"]
    out += [f"  | {ln}" for ln in (ocr.splitlines() or ["(nothing read)"])]
    read = None
    if claim is None:
        if not server.QWEN_API_KEY:
            out.append("Vision: QWEN_API_KEY not set and no --claim given: nothing to check.")
            return out
        got = await _signoff_vision(server, page)
        if got.get("error"):
            out.append(f"Vision: {got['error']}")
            return out
        out.append(f"Vision said: {_clean(got['raw'])[:600]}")
        read = got["read"] or {}
        claim, quote = read.get("result"), quote or read.get("quote")
    v = IR.validate_document(ocr, quote, claim)
    out += [f"Model's claim: {claim or '(none)'}   quoted line: {quote or '(none)'}",
            f"Read from the page ({v['source']}): {v['read'] or 'no result'}"
            + (f"   set aside: {', '.join(v['unclear'])}" if v["unclear"] else ""),
            f"Validated result: {v['result'] or '(none)'}   agreement: {'YES' if v['agree'] else 'NO'}"
            + (f" -- {v['reason']}" if v["reason"] else ""),
            f"Would store: status={IR.DOCUMENT if v['agree'] else IR.UNRESOLVED}, result={v['result']}"]
    if read is not None:
        out.append(f"  inspection={read.get('inspection')!r} levels={read.get('levels')!r} "
                   f"gate={IR.gate_for(read.get('inspection') or '')} date={read.get('date')}")
    return out

_EMPTY_HEADING = re.compile(r"^\s*[*_]*[^\n:]{1,40}:[*_]*\s*$", re.MULTILINE)


def _case_checks(case_id: str, reply: str, trace: list) -> Dict[str, bool]:
    """Each fixed DM case's own checks, from the reply and the tools called."""
    from lib import dm_brain
    tools = [t["tool"] for t in trace]
    low = reply.lower()
    if case_id == "update_588":
        return {"who's on site (headcount / who_on_site)": bool({"headcount", "who_on_site"} & set(tools)),
                "at least 2 different tools": len(set(tools)) >= 2,
                "no empty heading": not _EMPTY_HEADING.search(reply),
                "a real answer (2+ lines or 120+ chars)": reply.count("\n") >= 1 or len(reply) >= 120}
    if case_id == "dot_and_akron":
        return {"dot_status called": "dot_status" in tools,
                "Akron read as Arkon": "arkon" in low or bool({"list_subs", "find_sub"} & set(tools)),
                "never 'no Dot or Akron sub'": not re.search(r"no\s+dot\s+or\s+akron|no\s+(?:dot|akron)\s+sub", low)}
    if case_id == "arkon_framer":
        # Either it proposes saving the trade (and asks for yes), or the subs
        # list already has Arkon as framing and it says so -- after LOOKING
        # (Oct 21: live data already had Arkon as "Framers").
        st = [t for t in trace if t["tool"] == "set_sub_trade"]
        proposed = bool(st) and any(re.search(r"fram", str((t.get("args") or {}).get("trade") or ""), re.I)
                                    for t in st) and bool(re.search(r"\byes\b|\bconfirm\b", low))
        looked = bool({"list_subs", "find_sub", "set_sub_trade"} & set(tools))
        on_file = looked and bool(re.search(r"fram", low)) and bool(
            re.search(r"already|on file|nothing to change|listed as", low))
        return {"understood as Arkon's trade (proposed with a yes, or already on file after a lookup)":
                proposed or on_file,
                "never 'I don't have that'": not dm_brain.cant_answer(reply)}
    if case_id == "hvac_days":
        return {"sub_attendance called": "sub_attendance" in tools,
                "never 'check with X'": not dm_brain.refers_elsewhere(reply),
                "answers with days": bool(re.search(r"\bdays?\b", reply, re.I)) and not dm_brain.cant_answer(reply)}
    if case_id == "no_deflect":
        return {"a tool before any can't-answer": bool(trace) or not dm_brain.cant_answer(reply),
                "never 'check with X'": not dm_brain.refers_elsewhere(reply)}
    if case_id in ("spanish", "yiddish"):
        want = "es" if case_id == "spanish" else "yi"
        return {"headcount from the check-ins": bool({"headcount", "who_on_site", "site_headcount"} & set(tools)),
                f"answered in {'Spanish' if want == 'es' else 'Yiddish'}": dm_brain.language(reply) == want}
    return {}


_ACTING = {"send_sheet": "sent", "send_report": "sent", "resend_my_brief": "sent",
           "cancel_pending_change": "cancelled"}


def _quality(question: str, reply: str, res: dict) -> Dict[str, bool]:
    """The automatic quality checks for any DM."""
    from lib import dm_brain
    did = {_ACTING[t["tool"]] for t in res.get("trace") or []
           if t["tool"] in _ACTING and not t.get("error")}
    return {"answered": bool(reply) and reply not in (dm_brain.FAILED_TEXT, dm_brain.TRUNCATED_TEXT,
                                                       dm_brain.ACTION_UNVERIFIED_TEXT)
            and not dm_brain.cant_answer(reply),
            "evidence": not res.get("unverified"),
            "whole": res.get("stop") != "truncated" and not dm_brain.truncated(reply),
            "actions": all(c in did for c in dm_brain.action_claims(reply)),
            "language": dm_brain.language(question) == dm_brain.language(reply) or not reply}


def _clean(s) -> str:
    from lib import dm_brain
    return dm_brain.redact_phones(str(s or ""))


# ── PREFLIGHT: the ids are on DeepInfra, and they call tools ────────────────

_PING_TOOL = {"type": "function", "function": {
    "name": "ping", "description": "Answer the check. Always call this.",
    "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}}}


async def preflight(client, models: List[str], base: str) -> Dict[str, Any]:
    """{ok, listed: {model: bool}, tools: {model: bool}, qwen38: [ids], error}."""
    out: Dict[str, Any] = {"ok": True, "listed": {}, "tools": {}, "qwen38": [], "error": ""}
    try:
        page = await client.models.list()
        ids = sorted(m.id for m in page.data)
    except Exception as e:
        out.update(ok=False, error=f"GET {base}/models failed: {type(e).__name__}: {e}")
        return out
    out["qwen38"] = [i for i in ids if "qwen3.8" in i.lower()]
    for m in models:
        out["listed"][m] = m in ids
        if not out["listed"][m]:
            out["ok"] = False
            continue
        try:
            r = await client.chat.completions.create(
                model=m, temperature=0, max_tokens=200, tools=[_PING_TOOL], tool_choice="auto",
                messages=[{"role": "user", "content": "This is a check: call the ping tool with ok=true."}])
            calls = r.choices[0].message.tool_calls or []
            out["tools"][m] = bool(calls) and calls[0].function.name == "ping"
        except Exception as e:
            out["tools"][m] = False
            out["error"] += f" {m}: {type(e).__name__}: {e}"
        if not out["tools"][m]:
            out["ok"] = False
    return out


# ── RUNS ─────────────────────────────────────────────────────────────────────

async def _rows(server, days: int, limit: int, user: str = "") -> list:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = {"created_at": {"$gte": since}}
    if user:
        q["user_id"] = user
    rows = await server.db.whatsapp_dm_answers.find(q).sort([("created_at", 1)]).to_list(limit)
    # A confirm or a cancel to the new brain's proposals is not a question.
    return [r for r in rows if r.get("path") not in ("brain_confirm",)]


async def _identity(server, uid: str, cache: dict):
    if uid not in cache:
        optin = await server.db[server.WA_OPTINS].find_one({"user_id": uid, "status": "active"})
        chat = (optin or {}).get("chat_id") or ""
        ident = await server._dm_assistant_identity(chat) if chat else None
        cache[uid] = (chat, ident)
    return cache[uid]


def _one(res: dict, started: float) -> dict:
    """What a model's run shows: the answer, tools, retries, usage."""
    usage = res.get("usage") or {}
    return {"answer": _clean(res.get("reply") or " | ".join(res.get("sent") or [])),
            "tools": [f"{t['tool']}({json.dumps(t.get('args') or {}, ensure_ascii=False)})"
                      for t in res.get("trace") or []],
            "trace": res.get("trace") or [],
            "rounds": res.get("rounds"), "verify_retries": res.get("retries"),
            "deflect_retries": res.get("deflect_retries"), "unverified": res.get("unverified") or [],
            "stop": res.get("stop"), "models_used": usage.get("models") or [],
            "cut_retries": res.get("cut_retries"), "claim_retries": res.get("claim_retries"),
            "you_retries": res.get("you_retries"), "draft": _clean(res.get("draft") or ""),
            "input_tokens": usage.get("input"), "output_tokens": usage.get("output"),
            "reasoning_tokens": usage.get("reasoning"),
            "cost_usd": usage.get("cost_usd"),
            "seconds": round(time.monotonic() - started, 1)}


async def _dm_run(server, ident: dict, chat: str, question: str, history: list, model: str) -> dict:
    server._DM_MODEL.set(model)
    started = time.monotonic()
    try:
        res = await server._dm_brain_answer(ident, chat, question, history=history,
                                            now=datetime.now(timezone.utc), dry_run=True,
                                            flows=[], active=None)
    finally:
        server._DM_MODEL.set(None)
    return _one(res, started) | {"_res": res}


async def _replay_one(server, row: dict, cache: dict, models: List[str]) -> dict:
    uid = str(row.get("user_id") or "")
    chat, ident = await _identity(server, uid, cache)
    out = {"when": row.get("created_at").isoformat() if row.get("created_at") else "",
           "user": uid[-6:], "question": _clean(row.get("question")),
           "old_path": row.get("path"), "old_answer": _clean(row.get("answer")), "runs": {}}
    if not ident:
        out["skipped"] = "no active opt-in for this person now"
        return out
    at = row.get("created_at")
    if isinstance(at, datetime) and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    history = await server._dm_brain_history(chat, at, before=at)
    q = str(row.get("question") or "").strip()
    while history and str(history[-1].get("sender") or "") != "bot" and \
            str(history[-1].get("body") or "").strip()[:40] == q[:40]:
        history.pop()                                     # the question itself
    out["history_turns"] = len(history)
    # What came just before it (for review): the last two messages.
    out["before"] = [f"{'bot' if str(h.get('sender') or '') == 'bot' else 'them'}: "
                     f"{_clean(str(h.get('body') or ''))[:160]}" for h in history[-2:]]
    for m in models:
        run = await _dm_run(server, ident, chat, q, history, m)
        res = run.pop("_res")
        run["quality"] = _quality(q, res.get("reply") or "", res)
        run.pop("trace", None)
        out["runs"][m] = run
    return out


async def _walk_case(server, ident: dict, case: dict, model: str) -> dict:
    """The walk case: a walk rebuilt in memory, the message read by the walk
    brain on `model`, applied to that copy (the read-only db drops every
    write; sends are captured)."""
    from lib import punch
    now = datetime.now(timezone.utc)
    jobs = ident.get("projects") or []
    job = next((p for p in jobs if "588" in str(p.get("name") or p.get("address") or "")),
               jobs[0] if jobs else None)
    items = []
    for n in range(1, 5):
        it = punch.new_item(n, "", photo_key=f"eval/{n}.jpg", message_id=f"eval-{n}", at=now)
        it["captured"] = n
        items.append(it)
    items[0]["text"] = "Cracked tile"                 # a text came after photo #1
    sess = {"_id": "eval-walk", "user_id": ident.get("user_id"), "company_id": ident.get("company_id"),
            "status": "capturing", "items": items, "photos": [], "detail": punch.DEFAULT_DETAIL,
            "project_id": str((job or {}).get("_id") or (job or {}).get("id") or ""),
            "job_name": str((job or {}).get("name") or ""), "group_loc_v2": True,
            "batch_mark": 1, "batch_prev": [1], "loc_mark": 0}
    sent: list = []

    async def _capture(chat, text, *a, **k):
        sent.append(str(text))
    was = server.send_whatsapp_message
    server.send_whatsapp_message = _capture
    server._WALK_BRAIN.set(True)
    server._DM_MODEL.set(model)
    started = time.monotonic()
    try:
        await server._punch_think(ident, sess, "eval@c.us", {}, case["said"], now)
    finally:
        server._WALK_BRAIN.set(False)
        server._DM_MODEL.set(None)
        server.send_whatsapp_message = was
    nxt = punch.new_item(5, "", photo_key="eval/5.jpg", message_id="eval-5", at=now)
    punch.apply_default_location(nxt, sess.get("default_loc"))
    placed = {it["n"]: punch.location_label(it) for it in sess["items"]}
    noted = [it["n"] for it in sess["items"] if it.get("notes")]
    checks = {
        "all four on 3rd floor": all(str(it.get("floor")) == "3" for it in sess["items"]),
        "no note added": not noted,
        "next photos: 4th floor": str((sess.get("default_loc") or {}).get("floor")) == "4",
        "next photo #5 -> 4th floor": str(nxt.get("floor")) == "4",
        "reply says 4th": any("4th" in m for m in sent)}
    return {"answer": _clean("\n".join(sent)) or "(no reply)",
            "detail": "After: " + "; ".join(f"#{n} {lab or '(no place)'}" for n, lab in placed.items())
                      + f"; next photo #5: {punch.location_label(nxt) or '(no place)'}"
                      + (f"; notes on {noted}" if noted else ""),
            "checks": checks, "seconds": round(time.monotonic() - started, 1), "cost_usd": None}


async def _as_role(server, ident: dict, role: str, cp_email: str, cache: dict) -> Tuple[Optional[str], Optional[dict], str]:
    """(chat, identity, note) to run a case as `role`: the opted-in person
    --cp-email names when they hold that role, else `ident` with its role
    replaced (its jobs stay the ones that person has: said in the note)."""
    if cp_email:
        who = cp_email.strip()
        q = ({"email": who.lower()} if "@" in who
             else {"name": {"$regex": "(?i)" + re.escape(who)}, "is_deleted": {"$ne": True}})
        u = await server.db.users.find_one(q)
        if u and str(u.get("role") or "").strip().lower() == role:
            chat, real = await _identity(server, str(u.get("_id")), cache)
            if real:
                return chat, real, f"run as {role} {u.get('name') or u.get('email')} (their assigned jobs)"
    if not ident:
        return None, None, ""
    return None, dict(ident, role=role, user=dict(ident.get("user") or {}, role=role)), \
        f"run as {ident.get('role')} with role replaced by {role} (that person's jobs; pass --cp-email for a real {role})"


async def _fixed(server, rows: list, cache: dict, email: str, models: List[str],
                 cases: Optional[list] = None, cp_email: str = "") -> list:
    """Run FIXED_CASES (or `cases`) on each model as the person who asked live
    (their logged HVAC question), else --email, else the first replayed person."""
    cases = FIXED_CASES if cases is None else cases
    uid, live_old = "", ""
    hit = await server.db.whatsapp_dm_answers.find_one(
        {"question": {"$regex": "(?i)hvac"}}, sort=[("created_at", -1)])
    if hit:
        uid, live_old = str(hit.get("user_id") or ""), _clean(hit.get("answer"))
    if email:
        # --email wins over the logged question's asker: a login email, or a name.
        who = email.strip()
        q = ({"email": who.lower()} if "@" in who
             else {"name": {"$regex": "(?i)" + re.escape(who)}, "is_deleted": {"$ne": True}})
        u = await server.db.users.find_one(q)
        if u:
            uid = str(u.get("_id") or "")
    if not uid and rows:
        uid = str(rows[0].get("user_id") or "")
    chat, ident = await _identity(server, uid, cache) if uid else ("", None)
    out = []
    for case in cases:
        r = {"id": case["id"], "when": case["when"], "question": case["said"],
             "old_answer": live_old if case["id"] == "hvac_days" and live_old else case["old"],
             "expected": case["expected"], "fixed": True, "required": case["id"] in REQUIRED, "runs": {}}
        c_chat, c_ident, note = chat, ident, ""
        if case.get("as_role"):
            got_chat, c_ident, note = await _as_role(server, ident, case["as_role"], cp_email, cache)
            c_chat = got_chat or chat
        for m in models:
            if not c_ident:
                r["runs"][m] = {"answer": "(skipped: no opted-in person to run it as; pass --email)",
                                "checks": {}, "pass": False}
                continue
            try:
                if case["kind"] == "walk":
                    run = await _walk_case(server, c_ident, case, m)
                else:
                    run = await _dm_run(server, c_ident, c_chat, case["said"], [], m)
                    res = run.pop("_res")
                    run["checks"] = (_case_checks(case["id"], res.get("reply") or "", res.get("trace") or [])
                                     or _progress_checks(case["id"], res.get("reply") or "", res.get("trace") or []))
                    if note:
                        run["detail"] = note
                    run["quality"] = _quality(case["said"], res.get("reply") or "", res)
                    # A fixed case passes only with the answer itself out: not
                    # the "couldn't check" / "cut off" / failure text.
                    for k in ("answered", "evidence", "whole", "actions"):
                        if k not in case.get("skip_quality", ()):
                            run["checks"][f"quality: {k}"] = run["quality"][k]
                    run.pop("trace", None)
            except Exception as e:
                run = {"answer": f"(error: {type(e).__name__}: {e})", "checks": {}}
            run["pass"] = bool(run.get("checks")) and all(run["checks"].values())
            r["runs"][m] = run
        out.append(r)
    return out


# ── THE REPORT ───────────────────────────────────────────────────────────────

def _money(v) -> str:
    return "n/a" if v is None else f"${v:.4f}"


def _q(run: dict) -> str:
    q = run.get("quality") or {}
    return f"{sum(q.values())}/{len(q)}" if q else "-"


def _fully_ok(run: dict) -> bool:
    """Every quality check of one run passed (eval results, not a collection)."""
    q = run.get("quality") or {}
    return bool(q) and all(q.values())


def _passed(run: dict) -> bool:
    return bool(run.get("pass"))


def _stats(results: list, fixed: list, models: List[str]) -> List[str]:
    lines = ["| Model | Required fixed cases | All fixed cases | DMs fully OK | Median s | P90 s | "
             "Total cost |", "|---|---|---|---|---|---|---|"]
    for m in models:
        runs = [r["runs"][m] for r in results if m in r.get("runs", {})]
        fruns = [(f, f["runs"].get(m) or {}) for f in fixed]
        secs = sorted(x.get("seconds") or 0 for x in runs + [fr for _, fr in fruns])
        costs = [x.get("cost_usd") for x in runs + [fr for _, fr in fruns] if x.get("cost_usd") is not None]
        ok = len([x for x in runs if _fully_ok(x)])
        req = [_passed(fr) for f, fr in fruns if f["required"]]
        p90 = secs[max(0, int(round(0.9 * len(secs))) - 1)] if secs else 0
        lines.append(f"| {m} | {sum(bool(x) for x in req)}/{len(req)} | "
                     f"{len([fr for _, fr in fruns if _passed(fr)])}/{len(fruns)} | {ok}/{len(runs)} | "
                     f"{statistics.median(secs) if secs else 0:.1f} | {p90:.1f} | "
                     f"{_money(sum(costs)) if costs else 'n/a'} |")
    return lines


def _quote(text: str) -> str:
    return "> " + str(text or "").replace("\n", "\n> ")


def _md(results: list, models: List[str], dropped: list, fixed: Optional[list] = None,
        check: Optional[dict] = None) -> str:
    from lib import dm_brain
    fixed = fixed or []
    lines = [f"# DM brain eval: old vs {' vs '.join(models)} (DeepInfra)", "",
             f"{len(results)} logged DMs + {len(fixed)} fixed cases, replayed "
             f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Tools read today's records; compare "
             f"behavior, not exact numbers. Writes blocked by the read-only wrapper: {len(dropped)}.", ""]
    if check:
        lines += ["## Preflight (DeepInfra)", ""]
        for m in models:
            lines.append(f"- {m}: on /models {'✓' if check['listed'].get(m) else '✗'}, "
                         f"tool calling {'✓' if check['tools'].get(m) else '✗'}")
        if check.get("qwen38"):
            lines.append(f"- Qwen 3.8 ids on DeepInfra: {', '.join(check['qwen38'])}")
        if check.get("error"):
            lines.append(f"- {check['error'].strip()}")
        lines.append("")
    lines += ["## Summary", ""] + _stats(results, fixed, models) + [""]
    if fixed:
        lines += ["## Fixed cases", ""]
        for r in fixed:
            verdicts = ", ".join(f"{m}: {'PASS' if (r['runs'].get(m) or {}).get('pass') else 'FAIL'}"
                                 for m in models)
            lines += [f"### {r['id']}{' (required)' if r['required'] else ''} — {verdicts}", "",
                      f"**Asked:** {r['question']}", "", f"**Expected:** {r['expected']}", "",
                      "**Old** (live):", "", _quote(r.get("old_answer")), ""]
            for m in models:
                run = r["runs"].get(m) or {}
                lines += [f"**{m}** — {'PASS' if run.get('pass') else 'FAIL'} · {run.get('seconds', '-')}s · "
                          f"{_money(run.get('cost_usd'))}", "", _quote(run.get("answer")), ""]
                if run.get("detail"):
                    lines.append(run["detail"])
                if run.get("tools"):
                    lines.append("Tools: " + "; ".join(run["tools"]))
                if run.get("checks"):
                    lines.append("Checks: " + "; ".join(f"{'✓' if ok else '✗'} {k}"
                                                        for k, ok in run["checks"].items()))
                lines.append("")
    cant = [(r, m) for r in results for m in models
            if dm_brain.cant_answer((r.get("runs", {}).get(m) or {}).get("answer"))]
    lines += ["## Can't answer (new)", "",
              f"{len(cant)} new answers say they can't answer or send them elsewhere."
              + (" Each, with the tools it tried:" if cant else ""), ""]
    for r, m in cant:
        run = r["runs"][m]
        lines.append(f"- [{m}] {r['question'][:100]} → {str(run.get('answer'))[:140]} "
                     f"(tools: {', '.join(run.get('tools') or []) or 'none'})")
    lines += ["", "## Replayed DMs", ""]
    for i, r in enumerate(results, 1):
        lines += [f"### {r.get('n', i)}. {r['when'][:16].replace('T', ' ')} — {r['question'][:120]}", "",
                  f"**Old** ({r.get('old_path')}):", "", _quote(r["old_answer"]), ""]
        if r.get("before"):
            lines += ["_Just before it:_ " + " · ".join(r["before"]), ""]
        if r.get("skipped"):
            lines += [f"_(skipped: {r['skipped']})_", ""]
            continue
        for m in models:
            run = r["runs"].get(m) or {}
            q = run.get("quality") or {}
            bad = [k for k, ok in q.items() if not ok]
            lines += [f"**{m}** — quality {_q(run)}{(' (' + ', '.join(bad) + ')') if bad else ''} · "
                      f"{run.get('seconds', '-')}s · {_money(run.get('cost_usd'))} · "
                      f"{run.get('input_tokens') or 0}+{run.get('output_tokens') or 0} tokens", "",
                      _quote(run.get("answer")), ""]
            if run.get("tools"):
                lines.append("Tools: " + "; ".join(run["tools"]))
            retried = [f"{k} ×{run[k + '_retries']}" for k in ("verify", "cut", "claim", "you", "deflect")
                       if run.get(k + "_retries")]
            if retried:
                lines.append(f"_re-asked (same model): {', '.join(retried)}; finish: {run.get('stop')}_")
            lines.append("")
    return "\n".join(lines)


async def main_async(a) -> int:
    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        sys.exit("MONGO_URL / DB_NAME are not set — run under `railway run`.")
    if not os.environ.get("QWEN_API_KEY"):
        sys.exit("QWEN_API_KEY (DeepInfra) is not set — run under `railway run`.")
    import server
    from lib import dm_brain
    models = [m.strip() for m in (a.models or dm_brain.MODEL).split(",") if m.strip()]
    check = None
    if not a.skip_check:
        print(f"Preflight: {', '.join(models)} on {dm_brain.API_BASE} …", flush=True)
        check = await preflight(server._dm_brain_client(), models, dm_brain.API_BASE)
        for m in models:
            print(f"  {m}: listed={check['listed'].get(m)} tool_calling={check['tools'].get(m)}")
        if check.get("qwen38"):
            print(f"  Qwen 3.8 ids on DeepInfra: {', '.join(check['qwen38'])}")
        if not check["ok"]:
            print(f"  {check.get('error', '').strip()}")
            sys.exit("Preflight failed: set DM_BRAIN_MODEL / DM_BRAIN_ESCALATE_MODEL (or --models) to ids "
                     "from the list above that call tools. Nothing was run.")
    ro = ReadOnlyDb(server.db)
    server.db = ro

    async def _no_send(*a, **k):
        return None
    server.send_whatsapp_message = _no_send
    server._react_to_message = _no_send

    rows = await _rows(server, a.days, a.limit, a.user)
    print(f"Database: {os.environ.get('DB_NAME')} · {len(rows)} logged DM answers in the last {a.days} days",
          flush=True)
    if not rows:
        print("  (none: is `railway link` on the production environment and the backend service?)")
    numbered = list(enumerate(rows, 1))
    if a.pick:
        # "30,31,32,37" -- or "30 31 32 37", what PowerShell makes of an
        # unquoted 30,31,32,37.
        want = {int(x) for x in re.split(r"[,\s]+", a.pick) if x.isdigit()}
        numbered = [(i, r) for i, r in numbered if i in want]
        if want and not numbered:
            print(f"  --pick {a.pick!r}: none of {sorted(want)} is between 1 and {len(rows)}")
    cache: dict = {}
    cases = ([] if a.progress_only else list(FIXED_CASES)) + ([] if a.no_progress else list(PROGRESS_CASES))
    print(f"Fixed cases ({len(cases)}: {len(FIXED_CASES) if not a.progress_only else 0} DM + "
          f"{0 if a.no_progress else len(PROGRESS_CASES)} progress) on {', '.join(models)} …", flush=True)
    fixed = await _fixed(server, rows, cache, a.email, models, cases=cases, cp_email=a.cp_email)
    for r in fixed:
        print(f"[fixed {r['id']}] " + ", ".join(
            f"{m}: {'PASS' if (r['runs'].get(m) or {}).get('pass') else 'FAIL'}" for m in models), flush=True)
        for m in models:
            run = r["runs"].get(m) or {}
            if not run.get("pass"):
                bad = [k for k, ok in (run.get("checks") or {}).items() if not ok]
                print(f"   {m}: {str(run.get('answer'))[:160]!r}"
                      + (f" — failed: {', '.join(bad)}" if bad else ""), flush=True)
    if a.fixed_only or a.progress_only:
        numbered = []
    print(f"{len(numbered)} logged DMs to replay …", flush=True)
    results = []
    for i, row in numbered:
        try:
            r = await _replay_one(server, row, cache, models)
        except Exception as e:
            r = {"when": str(row.get("created_at")), "question": _clean(row.get("question")),
                 "old_path": row.get("path"), "old_answer": _clean(row.get("answer")),
                 "runs": {}, "skipped": f"error: {type(e).__name__}: {e}"}
        r["n"] = i
        results.append(r)
        print(f"[{i}/{len(rows)}] {r['question'][:60]!r}\n   old: {r['old_answer'][:90]!r}" + "".join(
            f"\n   {m.split('/')[-1]}: {str((r['runs'].get(m) or {}).get('answer'))[:90]!r} "
            f"({(r['runs'].get(m) or {}).get('seconds')}s, {_money((r['runs'].get(m) or {}).get('cost_usd'))})"
            for m in models), flush=True)
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in fixed + results),
        encoding="utf-8")
    (outdir / "side_by_side.md").write_text(_md(results, models, ro.dropped, fixed, check), encoding="utf-8")
    print("\n" + "\n".join(_stats(results, fixed, models)))
    print(f"\nWrote {outdir / 'side_by_side.md'} and {outdir / 'results.jsonl'}")
    print(f"Writes blocked: {len(ro.dropped)} {sorted(set(ro.dropped))[:10]}")
    req_fail = [f"{r['id']} on {m}" for r in fixed if r["required"]
                for m in models[:1] if not (r["runs"].get(m) or {}).get("pass")]
    if req_fail:
        print(f"REQUIRED fixed cases failing on {models[0]}: {', '.join(req_fail)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--user", default="", help="only this user id")
    ap.add_argument("--out", default="dm_brain_eval")
    ap.add_argument("--email", default="", help="run the fixed cases as this person: a login email or "
                                                 "a name (default: whoever asked the live HVAC question)")
    ap.add_argument("--models", default="", help="comma-separated DeepInfra ids (default: DM_BRAIN_MODEL; "
                                                  "add DM_BRAIN_ESCALATE_MODEL to compare)")
    ap.add_argument("--fixed-only", action="store_true", help="only the fixed cases")
    ap.add_argument("--pick", default="", help="only these logged DMs, by their number in the "
                                                "side-by-side (e.g. 37 or 30,31,32)")
    ap.add_argument("--skip-check", action="store_true", help="skip the /models + tool-calling preflight")
    ap.add_argument("--no-progress", action="store_true", help="skip the progress-engine cases (PROGRESS_CASES)")
    ap.add_argument("--progress-only", action="store_true", help="only the progress-engine cases, no replay")
    ap.add_argument("--cp-email", default="", help="run the role cases as this CP (login email or name); "
                                                    "default: the fixed cases' person with the role replaced")
    ap.add_argument("--schedule-file", default="", help="parse a P6 XER / MS Project XML / XLSX export and print "
                                                         "its activities, logic and work-package mapping; no "
                                                         "database, no model, nothing written")
    ap.add_argument("--signoff", default="", help="run the sign-off document path on a local PDF / photo: OCR, "
                                                   "the vision model's claim, the check; nothing written or sent")
    ap.add_argument("--claim", default=None, help="--signoff: check this result instead of asking the model")
    ap.add_argument("--quote", default=None, help="--signoff: the result line the claim quotes")
    a = ap.parse_args(argv)
    if a.schedule_file:
        print("\n".join(schedule_file_report(a.schedule_file)))
        return 0
    if a.signoff:
        return asyncio.run(signoff_main(a))
    return asyncio.run(main_async(a))


async def signoff_main(a) -> int:
    """--signoff: the server's own page and OCR helpers, its database wrapped
    read-only (nothing should touch it) and nothing sent."""
    for k, v in (("MONGO_URL", "mongodb://localhost:27017"), ("DB_NAME", "signoff_dry_run"),
                 ("JWT_SECRET", "signoff-dry-run-not-a-secret"), ("APP_BASE_URL", "https://app.levelog.com")):
        os.environ.setdefault(k, v)
    import server
    ro = ReadOnlyDb(server.db)
    server.db = ro

    async def _no_send(*args, **kw):
        return None
    server.send_whatsapp_message = _no_send
    print("\n".join(await signoff_report(server, a.signoff, a.claim, a.quote)))
    print(f"Writes blocked: {len(ro.dropped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
