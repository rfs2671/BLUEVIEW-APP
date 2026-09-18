"""Scoring a plan question against what search_plans actually returns.

WHAT THIS MEASURES, AND WHAT IT DOES NOT
========================================

The pipeline since #572 is: the agent names a subject, `search_plans` returns
typed records ranked tier-before-similarity, the agent composes, and a hard
gate refuses any number the returned records cannot vouch for.

This scores the DETERMINISTIC half: given the subject a person would type, do
the right records come back, from the right sheet, at a tier that can carry
the answer — and would the gate allow a correct answer and refuse an invented
one. It does not call the composing model. A model's paraphrase is not
reproducible run to run, and a score that moves when nothing changed is not a
measurement.

THE TRUTH IS NOT THE PIPELINE
=============================

Every case says how its expected answer was established, and none of them was
established by reading `plan_records`:

    text_layer      found in the source PDF's own text, read with a different
                    extractor from the one the indexer uses
    by_eye          read off a rendered crop of the sheet — the only way to
                    know what an outlined schedule says, since the text layer
                    has nothing there
    absent          on no current page's text layer

A harness that took its expectations from the records would only ever measure
whether the records agree with themselves.

KNOWN-STALE DATA IS MARKED, NOT SCORED
======================================

The corpus was indexed before #585. Three elements on M-200.00 — PTAC-1, -2
and -3 — sit at `schedule_cell` though the schedule they came from was read by
the vision model. That is the defect #585 fixes in code, and it is still in the
data. A case whose answer would lead with one of those records measures the
defect, not the retrieval, so it is reported as STALE and kept out of the rate.
Not dropped: listed, with the record that made it stale.

ONE PROJECT, AND THE SCHEMA DOES NOT KNOW WHICH
===============================================

The suite file names its project, its baseline and its cases. Nothing in this
module is specific to 588 Boyland. A second project is a second suite file —
the case vocabulary (`subject`, `intent`, `expect`, `truth`) is the same, and
no field here would change. That the eval is single-project is a known limit on
what it proves about generalisation, and the report says so.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import plan_search as ps
from lib.plan_extract import TIER_SCHEDULE_CELL
from lib.plan_records import TIER_ORDER, tier_rank

SCHEMA = 1
CASE_KINDS = ("answer", "absent")
TRUTH_KINDS = ("text_layer", "by_eye", "absent")

# How many returned records an answer is taken to lead with. render_records
# shows four; an agent reading more still opens with the first few.
CITE_K = 4

# A number no sheet on this project prints, used to prove the gate refuses an
# invented one. Checked against the returned records before use; see
# `_invented_number`.
_INVENTED_START = 7919


# ══════════════════════════════════════════════════════════════════════════
# Known-stale data
# ══════════════════════════════════════════════════════════════════════════

def record_key(r: Dict[str, Any]) -> Tuple[str, str, Any]:
    """What identifies a record in BOTH the stored corpus and a search result.

    search_plans projects `_id` out of what it returns, so the stored id is not
    available on the side that is being scored. A page yields each record type
    in its own ordinal sequence, so this triple is unique per record."""
    return (str(r.get("page_id")), str(r.get("record_type")), r.get("ordinal"))


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().upper()


def stale_elements_from_vision(records: Sequence[Dict[str, Any]]) -> set:
    """Ids of schedule_cell elements whose ONLY source schedule was read by the
    vision model.

    The stored element does not say which schedule it came from — before
    #585 every non-vision element was written with source `text_layer`, so
    `source` cannot tell a real table-finder count from a promoted vision one.
    Measured 2026-09-17: 16 elements are schedule_cell; 13 of them come from
    text-layer tables on RCP-001.00 and are CORRECT. So this joins each one
    back to the schedules on its own page, by schedule name and by the row
    that carries its mark and quantity, and flags it only when no schedule
    other than a vision-read one prints that row.
    """
    by_page: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        if r.get("record_type") == "schedule":
            by_page.setdefault(str(r.get("page_id")), []).append(r)
    out = set()
    for r in records:
        p = r.get("payload") or {}
        if not (r.get("record_type") == "element"
                and r.get("tier") == TIER_SCHEDULE_CELL
                and p.get("count_basis") == "schedule_qty"):
            continue
        tag = _norm(p.get("tag"))
        qty = str(p.get("count_if_stated"))
        hint = _norm(p.get("location_hint"))
        origins = set()
        for s in by_page.get(str(r.get("page_id")), []):
            sp = s.get("payload") or {}
            if _norm(sp.get("name"))[:120] != hint:
                continue
            for row in sp.get("rows") or []:
                cells = [_norm(c) for c in (row or [])]
                if cells and cells[0] == tag and qty in cells:
                    origins.add(s.get("source"))
        # A table-finder schedule printing the row makes the count honest,
        # whatever else also read it. OCR does not produce schedule_qty, so an
        # ocr_grid origin alongside vision does not rescue it.
        if origins and "table_finder" not in origins and "vision" in origins:
            out.add(record_key(r))
    return out


def _element_without_basis(r: Dict[str, Any]) -> bool:
    return (r.get("record_type") == "element"
            and not (r.get("payload") or {}).get("count_basis"))


def _tag_that_is_not_a_mark(r: Dict[str, Any]) -> bool:
    if r.get("record_type") != "tag":
        return False
    from lib.plan_text import looks_like_a_tag
    return not looks_like_a_tag(str((r.get("payload") or {}).get("tag") or ""))


# Classes defined once, applied to any project. The suite records how many of
# each it expects, so a count that moves is visible.
STALE_RULES: Dict[str, Callable[[Dict[str, Any]], bool]] = {
    "element_without_a_count_basis": _element_without_basis,
    "tag_that_is_not_a_mark": _tag_that_is_not_a_mark,
}
VISION_PROMOTED = "schedule_cell_count_from_a_vision_schedule"
STALE_CLASSES = (VISION_PROMOTED,) + tuple(STALE_RULES)


def stale_index(records: Sequence[Dict[str, Any]]) -> Dict[Any, str]:
    """{record _id: stale class} over the whole corpus."""
    out: Dict[Any, str] = {k: VISION_PROMOTED
                           for k in stale_elements_from_vision(records)}
    for r in records:
        k = record_key(r)
        if k in out:
            continue
        for name, rule in STALE_RULES.items():
            if rule(r):
                out[k] = name
                break
    return out


# ══════════════════════════════════════════════════════════════════════════
# The suite
# ══════════════════════════════════════════════════════════════════════════

class SuiteError(ValueError):
    pass


def load_suite(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        suite = json.load(fh)
    validate_suite(suite)
    return suite


def validate_suite(suite: Dict[str, Any]) -> None:
    """Refuse a suite that could score something it cannot justify."""
    if suite.get("schema") != SCHEMA:
        raise SuiteError(f"schema {suite.get('schema')!r}, expected {SCHEMA}")
    proj = suite.get("project") or {}
    if not proj.get("id") or not (proj.get("baseline") or {}).get("pages"):
        raise SuiteError("project needs an id and a baseline page count")
    seen = set()
    for c in suite.get("cases") or []:
        cid = c.get("id")
        if not cid or cid in seen:
            raise SuiteError(f"case id missing or repeated: {cid!r}")
        seen.add(cid)
        if c.get("kind") not in CASE_KINDS:
            raise SuiteError(f"{cid}: kind {c.get('kind')!r}")
        if not (c.get("subject") or "").strip():
            raise SuiteError(f"{cid}: no subject")
        truth = c.get("truth") or {}
        if truth.get("how") not in TRUTH_KINDS or not truth.get("evidence"):
            raise SuiteError(f"{cid}: truth must say how it was established, "
                             f"and what the evidence was")
        exp = c.get("expect") or {}
        if c["kind"] == "answer":
            if not exp.get("sheets"):
                raise SuiteError(f"{cid}: an answer case names its sheets")
            if not (exp.get("values") or exp.get("text")):
                raise SuiteError(f"{cid}: an answer case names what must be said")
            t = exp.get("tier_at_least")
            if t is not None and t not in TIER_ORDER:
                raise SuiteError(f"{cid}: unknown tier {t!r}")
        claims = exp.get("claims")
        if claims is not None:
            if not isinstance(claims, list) or not claims:
                raise SuiteError(f"{cid}: claims is a non-empty list or absent")
            for claim in claims:
                if not isinstance(claim, dict) or not claim.get("subject"):
                    raise SuiteError(f"{cid}: every claim names its subject")
                if "value" not in claim:
                    raise SuiteError(f"{cid}: every claim carries its value")
                if str(claim["value"]) not in [str(v) for v in exp.get("values") or []]:
                    raise SuiteError(
                        f"{cid}: claim value {claim['value']!r} is not among "
                        f"the case's expected values")
        if (c.get("intent") == "count" and exp.get("values") and not claims):
            # A count case whose numbers name no mark cannot exercise the rule
            # that binds a number to the thing it counts, and it is that rule
            # this suite exists to check.
            raise SuiteError(f"{cid}: a count case that states values says "
                             f"which mark each one belongs to")
        if c["kind"] == "absent" and truth.get("how") != "absent":
            raise SuiteError(f"{cid}: an absent case's truth is 'absent'")
        if exp.get("no_stated_count") and truth.get("how") != "absent":
            raise SuiteError(f"{cid}: 'no count is stated' is an absence, and "
                             f"its truth is established the way absences are")
    for k in suite.get("known_failures") or []:
        if not k.get("class") or not k.get("evidence"):
            raise SuiteError("a known failure names its class and its evidence")
        missing = [cid for cid in k.get("cases") or [] if cid not in seen]
        if missing:
            raise SuiteError(f"known failure {k['class']} names no such case: {missing}")


def known_failure_classes(suite: Dict[str, Any]) -> Dict[str, str]:
    """{case id: failure class} for failures the suite already understands.

    ── KNOWN IS NOT EXCUSED ───────────────────────────────────────────────
    #
    # A case listed here is still scored, and still counts against the rate.
    # The label says the failure is understood and not a regression; it does
    # not make it a pass. Taking known failures out of the rate is how a rate
    # stops moving while the answers stay wrong.
    """
    out: Dict[str, str] = {}
    for k in suite.get("known_failures") or []:
        for cid in k.get("cases") or []:
            out[cid] = k["class"]
    return out


# ══════════════════════════════════════════════════════════════════════════
# Scoring one case
# ══════════════════════════════════════════════════════════════════════════

def _quotes(records: Iterable[Dict[str, Any]]) -> List[str]:
    return [_norm(r.get("quote")) for r in records]


def _has_text(records: Sequence[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    want = _norm(text)
    return [r for r in records if want in _norm(r.get("quote"))]


def _claims(case: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [c for c in ((case.get("expect") or {}).get("claims") or [])
            if isinstance(c, dict) and c.get("subject")]


def _sentence(anchor: str, value: Any) -> str:
    """One claim, written the way an answer writes it.

    `anchor: value` and not `there are <value>`, because a bound gate checks a
    number against the thing its clause NAMES, and a sentence that names
    nothing is refused for naming nothing — which would make every check below
    pass or fail for the wrong reason."""
    return f"{anchor}: {value}." if anchor else f"There are {value}."


def _invented_number(records: Sequence[Dict[str, Any]], anchor: str = "",
                     intent: str = "") -> str:
    """A number none of the returned records can vouch for FOR THIS SUBJECT.

    ── WHY THE PROBE CARRIES A MARK ───────────────────────────────────────
    #
    # This probed with "There are {n}." — a clause naming nothing. Under the
    # bound rule a count that names nothing is refused whatever its value, so
    # the probe would have returned the first number it tried and
    # `gate_refuses_an_invented_number` would have been VACUOUSLY TRUE: the
    # refusal would be about the sentence's shape, never about the number.
    #
    # An assertion satisfied by the shape of a token rather than the truth of
    # a claim is the exact class this suite exists to catch, and it would have
    # been sitting inside the suite.
    """
    n = _INVENTED_START
    while True:
        ok, _bad = ps.answer_is_grounded(_sentence(anchor, n), records,
                                         intent=intent)
        if not ok:
            return str(n)
        n += 1


def _render_parts(render: str) -> Tuple[str, str]:
    """(header, body). render_records opens with `<subject> — on the drawings:`,
    which repeats the CALLER'S words. Checking that line for forbidden text
    reports the question back as a leak — measured on the first run, where
    'Solar panels — on the drawings:' failed a case whose records printed no
    such word."""
    head, _, body = (render or "").partition("\n")
    if not body and not head.rstrip().endswith(":"):
        return "", head
    return head, body


def _matches_without_label(r: Dict[str, Any], terms: Sequence[str]) -> bool:
    return ps.match_score(dict(r, label=None), terms) > 0


def _verdict(case: Dict[str, Any], returned: Sequence[Dict[str, Any]]
             ) -> Tuple[List[str], Dict[str, Any], str]:
    """(reasons, checks, render). Empty reasons is a pass."""
    exp = case.get("expect") or {}
    subject = case.get("subject") or ""
    terms = ps.search_terms(subject)
    lead = list(returned[:CITE_K])
    render = ps.render_records(list(returned), subject)
    head, body = _render_parts(render)
    checks: Dict[str, Any] = {"returned": len(returned)}
    reasons: List[str] = []

    # ── discipline every case is held to ─────────────────────────────────
    leaked = ps.contains_label(render, returned)
    checks["no_label_in_render"] = not leaked
    if leaked:
        reasons.append(f"a vision label reached the render: {leaked}")
    for bad in exp.get("forbid_text") or []:
        if _norm(bad) in _norm(body):
            checks[f"forbid:{bad}"] = False
            reasons.append(f"the render's records say {bad!r}")

    # THE LABEL NEVER PRINTS AND STILL SPEAKS. Measured on the first run:
    # 'kicker' returned two legend entries whose quotes are 'KE 1' and 'KE 2'
    # and which matched ONLY through the vision label 'KICKER EXHAUST 1'. The
    # render printed no label — and still read 'Kicker — on the drawings:
    # M-104.00 KE 1', which asserts the invented meaning outright.
    if lead:
        via_label = [r for r in lead if not _matches_without_label(r, terms)]
        checks["lead_matched_only_through_labels"] = len(via_label)
        if len(via_label) == len(lead):
            reasons.append(
                f"every leading record matched {subject!r} only through a "
                f"vision label ({len(lead)} of {len(lead)}); an answer would "
                f"rest on words the sheet does not print")

    # Informational: the header names the subject over records none of whose
    # quotes carry any of its words.
    if lead and head:
        checks["header_names_the_subject_over_unrelated_records"] = not any(
            any(t.upper() in _norm(r.get("quote")) for t in terms) for r in lead)

    # The mark the probe hangs on: a case's own first claim when it has one,
    # so the refusal is about the VALUE being unsupported and nothing else.
    claims = _claims(case)
    anchor = str(claims[0]["subject"]) if claims else ""
    intent = str(case.get("intent") or "")
    invented = _invented_number(returned, anchor, intent)
    allowed, _ = ps.answer_is_grounded(_sentence(anchor, invented), returned,
                                       intent=intent)
    checks["gate_refuses_an_invented_number"] = not allowed
    if allowed:
        reasons.append(f"the gate allowed {invented} for "
                       f"{anchor or 'no named subject'}, "
                       f"which nothing returned prints")

    # ── NOTHING MAY STATE A COUNT OF IT ───────────────────────────────────
    #
    # A DIFFERENT TRUTH FROM `absent`. An absent case says the subject is
    # printed nowhere. This says the subject IS on the drawings and no sheet
    # says HOW MANY — which is the ordinary state of most things a crew asks
    # about, and the state a fabricated count is most likely to appear in.
    #
    # Written for FA-001, whose fire-alarm matrix lists eight device types
    # against checkmark columns. The grid OCR merged the ROW NUMBER into the
    # description cell and produced '6 SPRK, TAMPER VALVE' on one render and
    # '9 SPRK, TAMPER VALVE' on another. Neither is a quantity of anything,
    # and a reader that turned that row into "6 sprinklers" would be inventing
    # a number from a list index. Measured 2026-09-18: of 26 fragments on the
    # current pages that put a digit near SPRINKLER, every one is a code
    # citation, and no element record states a sprinkler count.
    if exp.get("no_stated_count"):
        counted = [r for r in returned
                   if (r.get("payload") or {}).get("count_if_stated") is not None
                   and any(t.upper() in _norm(r.get("quote")) for t in terms)]
        checks["nothing_states_a_count"] = not counted
        if counted:
            first = counted[0]
            reasons.append(
                f"{len(counted)} returned record(s) state a count of "
                f"{subject!r} — first {(first.get('payload') or {}).get('count_if_stated')} "
                f"on {first.get('sheet_number')}, and no sheet states one")


    if case["kind"] == "absent":
        # WHICH absence is claimed. A case with `no_stated_count` says the
        # subject IS on the drawings and no sheet says how many — so the
        # subject appearing in a quote is the expected state, not the failure.
        if not exp.get("no_stated_count"):
            quoting = _has_text(returned, subject)
            checks["nothing_quotes_it"] = not quoting
            if quoting:
                reasons.append(
                    f"{len(quoting)} returned record(s) print {subject!r} — "
                    f"first on {quoting[0].get('sheet_number')}")
        return reasons, checks, render

    sheets = set(exp.get("sheets") or [])
    on_sheet = [r for r in lead if r.get("sheet_number") in sheets]
    checks["expected_sheet_in_lead"] = bool(on_sheet)
    checks["expected_sheet_anywhere"] = any(
        r.get("sheet_number") in sheets for r in returned)
    if not returned:
        reasons.append("search_plans returned nothing")
    elif not on_sheet:
        where = ("further down" if checks["expected_sheet_anywhere"]
                 else "nowhere in what came back")
        reasons.append(f"lead sheets {[r.get('sheet_number') for r in lead]}; "
                       f"the expected sheet is {where}")

    values = [str(v) for v in exp.get("values") or []]
    if values:
        # ── THE TRUE ANSWER, WRITTEN AS AN ANSWER IS WRITTEN ───────────────
        #
        # "The drawings show 21, 9, 11." names no subject, so under the bound
        # rule it is refused for naming nothing and the check reports a defect
        # that is not there. A case that states counts says which mark each one
        # belongs to, and the sentence is built from those.
        if claims:
            true_answer = " ".join(_sentence(str(c["subject"]), c["value"])
                                   for c in claims)
        else:
            true_answer = "The drawings show " + ", ".join(values) + "."
        ok, missing = ps.answer_is_grounded(true_answer, returned,
                                            intent=intent)
        checks["gate_allows_the_true_answer"] = ok
        if not ok:
            reasons.append(f"the gate would refuse the true answer; nothing "
                           f"returned prints {missing}")

    supporting: List[Dict[str, Any]] = []
    for t in exp.get("text") or []:
        hits = _has_text(returned, t)
        checks[f"text:{t}"] = bool(hits)
        if not hits:
            reasons.append(f"no returned record prints {t!r}")
        supporting += hits
    for r in returned:
        if values and set(ps._values(r.get("quote") or "")) & set(values):
            supporting.append(r)

    want = exp.get("tier_at_least")
    if want and supporting:
        best = min(supporting, key=lambda r: tier_rank(r.get("tier")))
        checks["best_supporting_tier"] = best.get("tier")
        if tier_rank(best.get("tier")) > tier_rank(want):
            reasons.append(f"best support is {best.get('tier')}, "
                           f"expected at least {want}")
    scope = exp.get("glyph_scope")
    if scope:
        scopes = sorted({(r.get("payload") or {}).get("glyph_scope")
                         for r in returned} - {None})
        checks["glyph_scope"] = scopes
        if scope not in scopes:
            reasons.append(f"no returned glyph count is {scope}-scoped")

    checks["render_carries_the_answer"] = all(
        _norm(v) in _norm(body) for v in values + list(exp.get("text") or []))
    return reasons, checks, render


def score_case(case: Dict[str, Any], returned: Sequence[Dict[str, Any]],
               stale: Dict[Any, str]) -> Dict[str, Any]:
    """PASS, FAIL or STALE, with every check that decided it.

    ── WHEN STALE DATA KEEPS A CASE OUT OF THE RATE ───────────────────────
    #
    # A case is STALE when a known-stale record is among the records an answer
    # would lead with — the rule as given: those records are not scored. With
    # one exception, and it only ever LOWERS the rate: if the case also fails
    # with every stale record taken out, the failure is not the stale data's
    # doing, and hiding it would hide a defect. The first run had exactly that:
    # 'wall electric unit heater' led with the stale PTAC elements (they share
    # the word 'unit'), and never returned WH-1 at all.
    #
    # A case never PASSES on the strength of a stale record.
    """
    reasons, checks, render = _verdict(case, returned)
    lead = list(returned[:CITE_K])
    stale_hits = [(r.get("sheet_number"),
                   (r.get("payload") or {}).get("tag") or (r.get("quote") or "")[:40],
                   stale[record_key(r)])
                  for r in lead if record_key(r) in stale]
    outcome = "pass" if not reasons else "fail"
    without = None
    if stale_hits:
        clean = [r for r in returned if record_key(r) not in stale]
        clean_reasons, _c, _r = _verdict(case, clean)
        without = "pass" if not clean_reasons else "fail"
        if not (outcome == "fail" and without == "fail"):
            outcome = "stale"
        else:
            reasons = reasons + [f"(still fails with the stale records removed: "
                                 f"{clean_reasons[0]})"]
    return {
        "id": case["id"], "kind": case["kind"], "question": case.get("question"),
        "subject": case["subject"], "intent": case.get("intent"),
        "outcome": outcome, "reasons": reasons, "stale": stale_hits,
        "without_stale": without,
        "checks": checks,
        "lead": [{"sheet": r.get("sheet_number"), "type": r.get("record_type"),
                  "tier": r.get("tier"), "source": r.get("source"),
                  "label": r.get("label"),
                  "quote": (r.get("quote") or "")[:100]} for r in lead],
        "render": render,
    }


def summarise(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    scored = [r for r in results if r["outcome"] != "stale"]
    passed = [r for r in scored if r["outcome"] == "pass"]
    by_kind = {}
    for k in CASE_KINDS:
        ks = [r for r in scored if r["kind"] == k]
        by_kind[k] = {"scored": len(ks),
                      "passed": sum(1 for r in ks if r["outcome"] == "pass")}
    return {
        "cases": len(results),
        "failed_in_known_classes": sum(1 for r in scored if r["outcome"] == "fail"
                                       and r.get("known_failure")),
        "scored": len(scored),
        "passed": len(passed),
        "failed": len(scored) - len(passed),
        "stale": len(results) - len(scored),
        "pass_rate": round(len(passed) / len(scored), 3) if scored else None,
        "by_kind": by_kind,
    }


def check_baseline(baseline: Dict[str, Any], observed: Dict[str, Any]
                   ) -> List[str]:
    """Every way the corpus differs from the one the suite was written for.
    Empty means it is the same corpus."""
    out = []
    for k in ("pages", "current_pages", "records",
              "newest_page_indexed_at", "newest_record_created_at"):
        if k in baseline and str(baseline[k]) != str(observed.get(k)):
            out.append(f"{k}: baseline {baseline[k]}, now {observed.get(k)}")
    return out


__all__ = ["SCHEMA", "CITE_K", "record_key", "STALE_CLASSES", "VISION_PROMOTED",
           "stale_elements_from_vision", "stale_index", "load_suite",
           "validate_suite", "SuiteError", "score_case", "summarise",
           "known_failure_classes",
           "check_baseline"]
