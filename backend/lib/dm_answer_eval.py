"""Scoring a DM ANSWER against what the owner said it must (and must not) say.

lib/plan_eval scores the deterministic half of a plans question -- what
search_plans returns. This scores the other half: the words the person got,
and the tools the turn ran, for questions the owner asked live and then said
what the right answer is. A suite is a JSON file (eval/boyland-dm-*.json);
its cases use the plans suite's vocabulary where it fits (`id`, `question`,
`expect`, `truth`) and add what an answer needs:

    expect.text       phrases the answer must contain (case-blind, spaces and
                      curly quotes normalised)
    expect.regex      patterns it must match (case-blind)
    expect.tools_any  at least one of these tools ran in the turn
    expect.quote      the exact sheet text it must quote. null = NOT KNOWN YET,
                      which requires `pending`
    forbid.text       phrases that fail the case wherever they appear
    forbid.regex      patterns that fail the case
    pending           what is still unknown about the right answer, and how to
                      find it out

── A PENDING CASE NEVER PASSES ─────────────────────────────────────────────
#
# A case whose expectation is not established yet is reported as
# FAILING-PENDING: every check it does have still runs, and a forbidden
# phrase or a missed check makes it a plain FAIL. What it cannot do is pass.
# Scoring it as a pass because nothing it knows about went wrong is how a
# suite reports 100% on questions nobody has the answer to.
#
# The pass rate counts it as not passed, and the report lists it with its
# `pending` text, so the gap is read every time the suite runs.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

SCHEMA = 1
SUITE_KIND = "dm_answers"
OUTCOMES = ("pass", "fail", "failing-pending", "not-asked")
_EXPECT_KEYS = {"text", "regex", "tools_any", "quote"}
_FORBID_KEYS = {"text", "regex"}


class SuiteError(ValueError):
    pass


def norm(s: Any) -> str:
    """Case, runs of space and curly quotes do not change what was said."""
    s = str(s or "")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def load_suite(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        suite = json.load(fh)
    validate_suite(suite)
    return suite


def validate_suite(suite: Dict[str, Any]) -> None:
    if suite.get("schema") != SCHEMA or suite.get("kind") != SUITE_KIND:
        raise SuiteError(f"schema {suite.get('schema')!r} kind {suite.get('kind')!r}, "
                         f"expected {SCHEMA} {SUITE_KIND!r}")
    seen = set()
    for c in suite.get("cases") or []:
        cid = c.get("id")
        if not cid or cid in seen:
            raise SuiteError(f"case id missing or repeated: {cid!r}")
        seen.add(cid)
        if not str(c.get("question") or "").strip() or not isinstance(c.get("question_verbatim"), bool):
            raise SuiteError(f"{cid}: a question, and whether it is the owner's exact words")
        try:
            re.compile(c.get("match") or "")
        except re.error as e:
            raise SuiteError(f"{cid}: match is not a pattern: {e}") from e
        if not c.get("match"):
            raise SuiteError(f"{cid}: match finds the question in a day's messages")
        exp, forbid = c.get("expect") or {}, c.get("forbid") or {}
        if set(exp) - _EXPECT_KEYS or set(forbid) - _FORBID_KEYS:
            raise SuiteError(f"{cid}: unknown expect/forbid key "
                             f"{sorted((set(exp) - _EXPECT_KEYS) | (set(forbid) - _FORBID_KEYS))}")
        for k in ("text", "regex", "tools_any"):
            v = exp.get(k)
            if v is not None and (not isinstance(v, list) or not all(isinstance(x, str) and x for x in v)):
                raise SuiteError(f"{cid}: expect.{k} is a list of non-empty strings")
        for k in ("text", "regex"):
            v = forbid.get(k)
            if v is not None and (not isinstance(v, list) or not all(isinstance(x, str) and x for x in v)):
                raise SuiteError(f"{cid}: forbid.{k} is a list of non-empty strings")
        for p in (exp.get("regex") or []) + (forbid.get("regex") or []):
            try:
                re.compile(p)
            except re.error as e:
                raise SuiteError(f"{cid}: bad pattern {p!r}: {e}") from e
        pending = c.get("pending")
        if pending is not None and not (isinstance(pending, str) and pending.strip()):
            raise SuiteError(f"{cid}: pending says what is unknown, or is absent")
        if "quote" in exp and exp["quote"] is None and not pending:
            raise SuiteError(f"{cid}: an unknown quote (null) is pending, and says how to find it")
        checks = any(exp.get(k) for k in ("text", "regex", "tools_any", "quote")) or any(forbid.values())
        if not checks and not pending:
            raise SuiteError(f"{cid}: a case checks something, or says what is pending")
        truth = c.get("truth") or {}
        if not truth.get("how") or not truth.get("evidence"):
            raise SuiteError(f"{cid}: truth says how the expectation was established, and on what")


def score_answer(case: Dict[str, Any], answer: Optional[str],
                 tools: Sequence[str] = ()) -> Dict[str, Any]:
    """One answer to one case: outcome, every check, and why it failed."""
    out = {"id": case["id"], "question": case["question"], "checks": {}, "reasons": [],
           "pending": case.get("pending")}
    if answer is None:
        out["outcome"] = "not-asked"
        out["reasons"].append("no answer to score: the question was not found")
        return out
    said = norm(answer)
    exp, forbid = case.get("expect") or {}, case.get("forbid") or {}
    checks, reasons = out["checks"], out["reasons"]
    for t in exp.get("text") or []:
        ok = norm(t) in said
        checks[f"text:{t}"] = ok
        if not ok:
            reasons.append(f"does not say {t!r}")
    for p in exp.get("regex") or []:
        ok = bool(re.search(p, said, re.I | re.S))
        checks[f"regex:{p}"] = ok
        if not ok:
            reasons.append(f"does not match /{p}/")
    if exp.get("quote"):
        ok = norm(exp["quote"]) in said
        checks["quote"] = ok
        if not ok:
            reasons.append("does not quote the sheet's text")
    if exp.get("tools_any"):
        ran = set(tools or ())
        ok = bool(ran & set(exp["tools_any"]))
        checks["tools_any:" + "|".join(exp["tools_any"])] = ok
        if not ok:
            reasons.append(f"none of {exp['tools_any']} ran (ran: {sorted(ran) or 'nothing'})")
    for t in forbid.get("text") or []:
        bad = norm(t) in said
        checks[f"forbid:{t}"] = not bad
        if bad:
            reasons.append(f"says the forbidden {t!r}")
    for p in forbid.get("regex") or []:
        bad = bool(re.search(p, said, re.I | re.S))
        checks[f"forbid_regex:{p}"] = not bad
        if bad:
            reasons.append(f"matches the forbidden /{p}/")
    if reasons:
        out["outcome"] = "fail"
    elif case.get("pending"):
        out["outcome"] = "failing-pending"
        reasons.append("PENDING: " + case["pending"])
    else:
        out["outcome"] = "pass"
    return out


def worst(results: Sequence[Dict[str, Any]]) -> str:
    """One case asked more than once is as good as its worst answer."""
    rank = {"fail": 0, "not-asked": 1, "failing-pending": 2, "pass": 3}
    return min((r["outcome"] for r in results), key=lambda o: rank[o]) if results else "not-asked"


def summarise(outcomes: Sequence[str]) -> Dict[str, Any]:
    counts = {o: sum(1 for x in outcomes if x == o) for o in OUTCOMES}
    n = len(outcomes)
    return {"cases": n, **counts,
            # failing-pending and not-asked are NOT passes, and count against it
            "pass_rate": round(counts["pass"] / n, 3) if n else None}


def find_turns(case: Dict[str, Any], timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Each message in a dm_thread_timeline --json file that asks this case:
    {answer, tools, at}. The answer is the logged reply plus every message
    Levelog sent for that turn -- what the person actually got. Outgoing
    messages the timeline attributes to a different message are left out."""
    rx = re.compile(case["match"], re.I)
    turns = []

    def mine(o: Dict[str, Any]) -> bool:
        # An outgoing message that carries ANOTHER message's answer is not
        # this turn's; one that went out after their next message counts only
        # when it is known to carry this answer.
        owner = o.get("answers_mine")
        if owner is False:
            return False
        return owner is True or not o.get("late")

    for m in timeline.get("messages") or []:
        body = str((m.get("inbound") or {}).get("body") or "")
        if not rx.search(body):
            continue
        a = m.get("answer") or {}
        parts = [str(a.get("answer") or "")] + [str(o.get("body") or "") for o in m.get("outbound") or []
                                                if mine(o)]
        tools = [str(t.get("tool")) for t in a.get("tool_data") or [] if isinstance(t, dict)]
        turns.append({"answer": "\n".join(p for p in parts if p), "tools": tools,
                      "at": (m.get("inbound") or {}).get("at"), "asked": body})
    return turns


__all__ = ["SCHEMA", "SUITE_KIND", "OUTCOMES", "SuiteError", "norm", "load_suite",
           "validate_suite", "score_answer", "worst", "summarise", "find_turns"]
