"""Does reading file names and set labels as citations (plan_search.
strip_source_citations) change any binding but refusal -> correct bind?
READ-ONLY, no database. Main's gate against this branch's, on every stored
plan answer (eval/results/*.json: results[].render, that run's lead records
as the evidence), per claim set (negative_claims_bindings.SETS).

    python scripts/citation_bindings.py [--main PATH_TO_MAIN_plan_search.py]

Every stored record is given the file it would come from and its set
(FIXTURE: a #892-shaped name with digits in it), and each answer is gated
three ways, by main and by this branch:

  A  the answer as stored                      -> must not change at all
  B  the answer citing its file and set, two   -> may change ONLY refused ->
     ways ("[A-101 · 588 Boyland Arch 7.2.pdf,   passed, and only where A
     owner's post-CO set 7.2 6/9/26]" and        passes (the answer's own
     "(A-101 · 588 Boyland Arch 7.2,              figures bind: a correct bind)
     owner's set)")
  C  each digit run of the file name and label  -> must not change: a figure
     stated AS A FIGURE, citing the file          the file name carries still
     ("There are 588 <subject>. [...]")           binds only on the records

  D  names carrying a scope word (Codex,     -> must not change: such a name
     #910: "Apartment 4A.pdf", label            is never removed, so "4A"
     "Apt 4A set 6/9/26"), the answer as        never leaves a claim's scope
     stored, cited, and as "Apartment 4A has
     <n> <subject>." for each of its figures

Exit 1 on any A change, any B change other than refused -> passed with A
passing, or any C or D change.
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import re
import subprocess
import tempfile
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

from lib import plan_search as new  # noqa: E402
from scripts.negative_claims_bindings import SETS, set_of  # noqa: E402

#: FIXTURE names, #892-shaped: digits in both.
FILE = "588 Boyland Arch 7.2.pdf"
LABEL = "Owner's post-CO set 7.2 6/9/26"
SOURCES = [{"file_name": FILE, "track": "post_co", "label": LABEL}]
#: How a well-cited answer names them: the whole file name with the set's
#: label, and the name without ".pdf" with the set's own words.
CITES = (f" [{{sheet}} · {FILE}, {LABEL}]",
         f" ({{sheet}} · {FILE[:-4]}, owner's set)")
CITED = CITES[0]
#: D: names that carry a scope word, never removed.
SCOPED_FILE = "Apartment 4A.pdf"
SCOPED_SOURCES = [{"file_name": SCOPED_FILE, "track": "post_co", "label": "Apt 4A set 6/9/26"}]
#: The figures the fixture names carry, each stated as a count in C.
NAME_FIGURES = sorted(set(re.findall(r"\d+(?:\.\d+)?", FILE + " " + LABEL)))


def load_main(path: str = ""):
    if not path:
        src = subprocess.run(["git", "show", "origin/main:backend/lib/plan_search.py"],
                             cwd=BACKEND, capture_output=True, text=True, check=True).stdout
        path = str(Path(tempfile.mkdtemp()) / "plan_search_main.py")
        Path(path).write_text(src)
    spec = importlib.util.spec_from_file_location("lib._main_plan_search", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def records_of(lead) -> list:
    out = []
    for r in lead or []:
        if not isinstance(r, dict) or not r.get("sheet"):
            continue
        out.append({"sheet_number": r.get("sheet"), "quote": r.get("quote") or "",
                    "tier": r.get("tier"), "record_type": r.get("type"),
                    "label": r.get("label"), "file_name": FILE, "file_id": "f1"})
    return out


def gate(mod, text, recs, intent, new_side):
    if new_side:
        return mod.answer_is_grounded(text, recs, intent=intent, sources=SOURCES)[0]
    return mod.answer_is_grounded(text, recs, intent=intent)[0]


def probe(main) -> dict:
    per = {}
    for f in sorted(glob.glob(str(BACKEND / "eval" / "results" / "*.json"))):
        for r in json.loads(Path(f).read_text()).get("results") or []:
            text, recs = r.get("render"), records_of(r.get("lead"))
            if not isinstance(text, str) or not text.strip() or not recs:
                continue
            s = per.setdefault(set_of(r.get("id", "")), Counter())
            intent = r.get("intent") or ""
            sheet = recs[0]["sheet_number"]
            s["answers"] += 1
            a0, a1 = gate(main, text, recs, intent, False), gate(new, text, recs, intent, True)
            s["A_passed"] += a1
            s["A_changed"] += a0 != a1
            for form in CITES:
                cited = text.rstrip() + form.format(sheet=sheet)
                b0, b1 = gate(main, cited, recs, intent, False), gate(new, cited, recs, intent, True)
                s["B_cited"] += 1
                s["B_passed_before"] += b0
                s["B_passed_after"] += b1
                if b0 != b1:
                    if not b0 and b1 and a1:
                        s["B_refusal_to_correct_bind"] += 1
                    else:
                        s["B_bad_change"] += 1
            subj = r.get("subject") or "units"
            for n in NAME_FIGURES:
                bare = f"There are {n} {subj}."
                c_bare = gate(new, bare, recs, "count", True)
                c_cited = gate(new, bare + CITED.format(sheet=sheet), recs, "count", True)
                c_main = gate(main, bare, recs, "count", False)
                s["C_checked"] += 1
                s["C_changed"] += (c_cited != c_main) or (c_bare != c_main)
            srecs = [dict(x, file_name=SCOPED_FILE) for x in recs]
            figs = [v for v in new._values(text)][:4]
            for t, i in ([(text, intent), (text.rstrip() + f" [{sheet} · {SCOPED_FILE}, Apt 4A set 6/9/26]", intent)]
                         + [(f"Apartment 4A has {v} {subj}.", "count") for v in figs]):
                d0 = main.answer_is_grounded(t, srecs, intent=i)[0]
                d1 = new.answer_is_grounded(t, srecs, intent=i, sources=SCOPED_SOURCES)[0]
                s["D_checked"] += 1
                s["D_changed"] += d0 != d1
    return per


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", default="", help="main's plan_search.py (default: git origin/main)")
    args = ap.parse_args(argv)
    mod = load_main(args.main)
    per = probe(mod)
    cols = ("answers", "A_passed", "A_changed", "B_cited", "B_passed_before", "B_passed_after",
            "B_refusal_to_correct_bind", "B_bad_change", "C_checked", "C_changed",
            "D_checked", "D_changed")
    print(f"fixture file {FILE!r}, set label {LABEL!r}; name figures {NAME_FIGURES}\n")
    print("claim set      " + "  ".join(cols))
    tot = Counter()
    for name in list(SETS) + ["other"]:
        s = per.get(name, Counter())
        tot.update(s)
        print(f"{name:<14} " + "  ".join(f"{s[c]:>{len(c)}d}" for c in cols))
    print(f"{'TOTAL':<14} " + "  ".join(f"{tot[c]:>{len(c)}d}" for c in cols))
    bad = tot["A_changed"] or tot["B_bad_change"] or tot["C_changed"] or tot["D_changed"]
    print("\nzero wrong bindings: " + ("NO" if bad else "yes"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
