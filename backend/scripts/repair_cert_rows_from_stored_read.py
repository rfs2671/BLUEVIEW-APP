"""Re-derive the certification rows whose own worker document already answers
them. DRY RUN BY DEFAULT.

── WHO THIS IS FOR: SIX ROWS, NAMED ────────────────────────────────────────

ONE row that says nothing at all. Worker 6a9576da611a543244a9ccac, registered
2026-08-31 12:43:06, carries a COMPLETE card read on his worker document --
name, number, class, colour, issue date and expiry -- and a 431358-byte card
image in R2. His `certifications[0]` holds `card_number: null`,
`expiration_date: null`, `expiration_raw_rejected: null`, `review_reason:
null`, `needs_review: false`, `extraction_completeness: 0.0`. The read worked
and the row lost it. He is the only worker in 79 with completeness 0.0 AND
needs_review false, and nothing in this repository can say what wrote that row:
both repair scripts have never run (0 audit rows), the code live at his
registration computed `needs_review` True for those inputs, and the builder's
dedup guard prevented any later rebuild. Most likely a hand edit in mongosh.

FIVE rows that DID say why, which is the correct behaviour. Each carries
`EXPIRY_UNPARSEABLE` with the refused string kept verbatim in
`expiration_raw_rejected`: `illegible`, `05/35`, `10272029` (Juan Lopez),
`null`, `062427`. They are in scope because the parser has since widened --
`10272029` is now read as 27 October 2029, see CERT_DATE_PADDED_US_RE -- so one
of the five has an answer today that it did not have when it was refused.

WHY THEY NEVER SELF-REPAIRED. `needs_review` and `review_reason` are written
ONCE, in `build_worker_certifications`, and nothing re-derives them on read.
Worker 6a9576da611a543244a9ccac has THIRTEEN check-ins, every one with
`osha_data_sent = False`, and the SST branch ends with a dedup guard -- `if
existing_sst is None: append` -- so an existing SST row is never revisited.
Thirteen chances, all skipped by design. The gate fix in this same change means
a FOURTEENTH tap would now repair him; this script exists because the other
five have no fourteenth tap coming, and because a man should not have to walk
back to a turnstile to fix a row a hand edit broke.

── RE-DERIVE, NEVER HAND-ASSIGN ────────────────────────────────────────────

Every recovered value goes back through `server.evaluate_cert_expiry` and
`server.derive_cert_review` -- the SAME two functions the scanner calls -- so
the plausibility rules (`exp <= issue`, the class-aware ceiling) and the
completeness rules all get their say. A recovered date CAN come back REFUSED: a
date past the 7-year ceiling leaves the row flagged EXPIRY_IMPLAUSIBLE instead
of EXPIRY_UNPARSEABLE, and that is the right answer, not a failure of this
script. Assigning `needs_review = False` by hand is what made PR #530 look like
a cure and got it parked, and `evaluate_cert_expiry`'s own docstring says so.
`test_repair_cert_rows_dry_run.py::test_the_planner_never_assigns_the_flag_by_hand`
reads this planner's AST and fails if it ever happens again.

── WHAT IT REFUSES TO TOUCH ────────────────────────────────────────────────

  * A VERIFIED row. `build_worker_certifications` will not let a RE-SCAN modify
    one ("admin-confirmed"); a backfill has less standing than a re-scan.
  * A row whose stored `card_number` NAMES A DIFFERENT CARD from the stored
    read's `sst_number`. `osha_data` on a worker document is the LATEST scan
    and need not be the scan this row came from, so reading an expiry out of it
    for a different card would attribute one card's life to another card's
    number -- on a §3301 compliance record. Compared through
    `normalize_card_number`, because a stored row may hold any case.
  * The row's TYPE and CLASS_SOURCE. This never re-runs `resolve_card_class`:
    the class on the row is the classification that was made from the image at
    the time, and re-deciding it from a possibly-later `osha_data` would be a
    second opinion about a card this script cannot see. Only the expiry, the
    issue date, the card number and the DERIVED verdict move.
  * `'illegible'`, `'null'`, `'062427'`, `'05/35'`. The parser refuses these by
    design -- see the comment at `server.parse_cert_date` -- and they stay on
    the human correction path. This script leaves them flagged, and says so per
    row.

── THE CARD IMAGE CONSEQUENCE, STATED PER ROW ──────────────────────────────

`card_image_may_be_replaced` reads `needs_review or expiration_date is None`.
Every row this CLEARS flips that predicate to False, so a stored card photo can
no longer be overwritten by a later re-scan. That matters here in a way it did
not for backfill_iso_expiry, whose report noted it moved nothing because none
of its twelve had an image: worker 6a9576da611a543244a9ccac HAS one, 431358
bytes in R2, so his image becomes unreplaceable by this run. The report prints
the transition for every row. It is the right outcome -- his row will describe
exactly that photograph -- and `DELETE /workers/{id}/osha-card-image` remains
the audited admin route for a correction. Inheriting that effect silently is
the defect that parked #530, so it is printed rather than assumed.

USAGE. The report is the default. There is no way to write without asking.

    $env:MONGO_URL='<Atlas URI>'; $env:DB_NAME='<db>'
    python backend/scripts/repair_cert_rows_from_stored_read.py          # dry run
    python backend/scripts/repair_cert_rows_from_stored_read.py --i-know \\
        --reason '<why>' --session <id>

`--execute` is REFUSED BY NAME, pointing at `--i-know`, rather than either
honouring it (which would make the guard decoration) or quietly doing nothing
(which would tell an operator a repair ran when it did not).

Reads MONGO_URL / DB_NAME from env; never prints the connection string.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def missing_env():
    """The environment names this script cannot run without."""
    return [n for n in ("MONGO_URL", "DB_NAME") if not os.environ.get(n)]


# ── THE REFUSALS RUN BEFORE ANYTHING ELSE CAN FAIL FOR ANOTHER REASON ───────
#
# MEASURED ON THIS FILE, BEFORE THIS BLOCK EXISTED:
#
#     $ python backend/scripts/repair_cert_rows_from_stored_read.py --execute
#     KeyError: 'MONGO_URL'
#
# `import server` reads MONGO_URL at MODULE level, so a documented command --
# and `--execute` is documented, in runbooks and in shell history -- died with a
# traceback about an environment variable instead of the sentence that says the
# flag no longer authorises a production write. An operator reading that fixes
# his environment and runs it again, which is the opposite of what the refusal
# is for. `refuse_legacy_flag`'s own docstring makes the case: the third
# outcome, the command stopping and saying what changed, is the only honest one
# -- and it was unreachable here.
#
# GUARDED ON __main__, so importing this module for its planner (which is how
# test_repair_cert_rows_dry_run.py drives it, with the env already set) is
# untouched. `retire_owner_accounts.py` gets the same property by importing
# server inside main(); this file cannot, because `plan_for_worker` is a
# module-level pure function the tests import directly.
#
# backend/scripts/backfill_iso_expiry.py has the identical defect and is NOT
# fixed here -- see the PR's "left alone" list. It is one line of the same
# shape and it belongs to that file's next change.
if __name__ == "__main__":
    from prod_guard import refuse_legacy_flag as _refuse_early
    _refuse_early()
    _absent = missing_env()
    if _absent:
        sys.stderr.write(
            "\nSet " + " and ".join(_absent) + " in the environment first.\n"
            "  Nothing was read and nothing was written.\n\n")
        raise SystemExit(1)

import server  # noqa: E402
from server import (  # noqa: E402
    card_image_may_be_replaced,
    cert_row_fault,
    derive_cert_review,
    evaluate_cert_expiry,
    normalize_card_number,
    parse_cert_date,
    RECOGNIZED_SST_TYPES,
    SST_CLASS_TYPES,
    SST_DEAD_CLASSES,
)
from lib.ocr_text import norm_ocr_str  # noqa: E402

# ── PRODUCTION WRITE GUARD ──────────────────────────────────────────────────
# Every write below goes through `audited(...)`, which records it in audit_logs
# with actor "script:repair_cert_rows_from_stored_read", the session and the
# reason. Without --i-know the handle is unwrapped and nothing is written. See
# prod_guard, and the 19:07:45Z incident its docstring opens with.
from prod_guard import (  # noqa: E402
    add_guard_args, audited, check_guard, refuse_legacy_flag, report_dry_run,
)

NAME = "repair_cert_rows_from_stored_read"


def _aware(dt):
    if isinstance(dt, datetime):
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return None


def row_is_in_scope(row, stored_od) -> bool:
    """Is there anything on this row a stored read could answer? PURE.

    THREE WAYS IN, and they are three different defects:

      * `cert_row_fault` names the row unsound -- no expiry and nothing saying
        why. That is worker 6a9576da611a543244a9ccac's row and the whole reason
        this file exists.
      * a rejected raw expiry is kept on the row. The parser has widened since
        it was refused, so it may read today.
      * the row holds NO card number while the stored read holds one. Angel
        again, and the cheapest half of his repair.

    DERIVED, NOT A LIST OF SIX IDS. A hand-kept list is a check with an expiry
    date nobody set: the seventh row is not on it and nothing says so.
    """
    if str(row.get("type") or "") not in RECOGNIZED_SST_TYPES:
        return False
    if cert_row_fault(row):
        return True
    # PLAIN TRUTHINESS, NOT `norm_ocr_str`, AND THE DIFFERENCE IS THE WORD
    # "null". On a STORED READ "null" means the model read nothing, so
    # norm_ocr_str is right to erase it. On `expiration_raw_rejected` the word
    # IS the value that was rejected -- one of the five refused strings on
    # production is literally `'null'` -- and it has to stay on the record.
    # Filtered here, that row silently left the report altogether.
    if str(row.get("expiration_raw_rejected") or "").strip():
        return True
    if not normalize_card_number(row.get("card_number")) and norm_ocr_str(
            (stored_od or {}).get("sst_number")):
        return True
    return False


def raw_expiry_for(row, stored_od):
    """Which string this row's expiry is recovered FROM, and whence.

    THE ROW'S OWN REFUSED VALUE FIRST, always. `expiration_raw_rejected` is
    tied to THIS certification -- it is the string that was read off this card
    and refused -- so it is better evidence about this row than anything on the
    worker document, which holds the LATEST scan.

    The stored read is consulted only when the row kept no raw value at all,
    and only when the two are about the same card (see `same_card`). That is
    the Angel case: a complete stored read and a row that recorded nothing.
    """
    # VERBATIM, not through `norm_ocr_str` -- see row_is_in_scope. The row kept
    # this string precisely because it was refused, so handing it back to the
    # gate unchanged is what makes the gate's verdict reproducible: `'null'`
    # comes back EXPIRY_UNPARSEABLE with `'null'` still on the row, which is
    # what the record should say. Erasing it first would turn "a value arrived
    # and we refused it" into "nothing arrived" — a strictly worse record.
    own = str(row.get("expiration_raw_rejected") or "").strip()
    if own:
        return own, "row.expiration_raw_rejected"
    if not same_card(row, stored_od):
        return None, "different-card"
    stored = norm_ocr_str((stored_od or {}).get("expiration"))
    if stored:
        return stored, "worker.osha_data.expiration"
    return None, "nothing-stored"


def same_card(row, stored_od) -> bool:
    """Do the row and the stored read name the same card?

    A row with NO number and a read WITH one counts as the same card: that is
    the state this script repairs, and refusing it would refuse the only case
    it was written for. TWO DIFFERENT numbers is the refusal -- and it is the
    one that matters, because merging them attributes one card's expiry to
    another card's number.
    """
    a = normalize_card_number(row.get("card_number"))
    b = normalize_card_number(norm_ocr_str((stored_od or {}).get("sst_number")))
    if a and b:
        return a == b
    return True


def plan_for_worker(worker, now):
    """PURE. One plan dict per in-scope certification. Mutates nothing.

    Each plan:
      action      'recover' | 'number-only' | 'leave' | 'skip-verified'
      set         the exact un-dotted $set payload, or {} when nothing is written
      before/after  what the row says now and what it would say
      fault_before / fault_after   `cert_row_fault`, so the report shows the
                                   invariant closing rather than claiming it
      img_before / img_after / img_locks   the card_image_may_be_replaced move
    """
    certs = list(worker.get("certifications") or [])
    stored_od = worker.get("osha_data") or {}
    plans = []
    for idx, row in enumerate(certs):
        if not row_is_in_scope(row, stored_od):
            continue

        base = {
            "worker": worker.get("name"),
            # `_id`, NOT `id`. Measured on production: every affected worker
            # document has `id: null`, and every write path in server.py keys
            # on `_id`. Filtering on `id` would match nothing at best and an
            # arbitrary `id: null` document at worst.
            "worker_id": worker.get("_id"),
            "cert_index": idx,
            "type": str(row.get("type") or ""),
            "before": {
                "card_number": row.get("card_number"),
                "expiration_date": row.get("expiration_date"),
                "needs_review": bool(row.get("needs_review")),
                "review_reason": row.get("review_reason"),
                "expiration_raw_rejected": row.get("expiration_raw_rejected"),
                "extraction_completeness": row.get("extraction_completeness"),
            },
            "fault_before": cert_row_fault(row),
        }

        if row.get("verified"):
            plans.append(dict(
                base, action="skip-verified", raw=None, raw_from="-",
                set={}, after=dict(base["before"]), fault_after=base["fault_before"],
                img_before=None, img_after=None, img_locks=False))
            continue

        raw, raw_from = raw_expiry_for(row, stored_od)

        # THE CARD NUMBER IS A BLANK-FILL, NEVER AN OVERWRITE. Same rule the
        # gate now applies: a field that holds NOTHING may be filled from
        # evidence, a field that holds a value is not displaced by a backfill.
        card_no = normalize_card_number(row.get("card_number"))
        if not card_no and same_card(row, stored_od):
            card_no = normalize_card_number(
                norm_ocr_str(stored_od.get("sst_number")))

        # The issue date: the row's own if it has one, else the stored read's,
        # and only under the same-card rule. It is not cosmetic -- it feeds the
        # `exp <= issue` sanity check and the SST_TEMPORARY ceiling.
        issue_dt = _aware(row.get("issue_date"))
        if issue_dt is None and same_card(row, stored_od):
            issue_dt = parse_cert_date(norm_ocr_str(stored_od.get("issued")))

        sst_type = str(row.get("type") or "")
        stored_exp, suppressed, gate_reason = evaluate_cert_expiry(
            raw, issue_dt, sst_type, now)

        # The completeness inputs, reconstructed from the ROW plus the recovered
        # number. Deliberately NOT from the stored read's `name`: a name on
        # `osha_data` is whatever the latest scan said, and the record's answer
        # to "whose card is this" is the worker document's own name field.
        name_ok = bool(str(worker.get("name") or "").strip())
        number_ok = bool(card_no)
        class_ok = (sst_type in SST_CLASS_TYPES
                    and sst_type not in SST_DEAD_CLASSES)

        needs_review, reason, completeness = derive_cert_review(
            name_ok, number_ok, class_ok, stored_exp,
            row.get("class_source"), gate_reason)

        # AMENDMENT C, HONOURED HERE TOO. Two unverified SST rows on one worker
        # are both flagged by the builder; clearing one of them in isolation
        # would quietly undo that. The builder's own wording: "two unverified
        # SST rows must never coexist quietly."
        unverified_sst = [c for c in certs
                          if str(c.get("type") or "") in RECOGNIZED_SST_TYPES
                          and not c.get("verified")]
        if len(unverified_sst) > 1:
            needs_review = True
            if not reason:
                reason = "DUPLICATE_SST"

        after_row = dict(row)
        after_row["card_number"] = card_no
        after_row["issue_date"] = issue_dt
        after_row["expiration_date"] = stored_exp
        after_row["expiration_raw_rejected"] = raw if suppressed else None
        after_row["needs_review"] = needs_review
        after_row["review_reason"] = reason
        after_row["extraction_completeness"] = completeness

        after_worker = dict(worker)
        after_worker["certifications"] = [
            after_row if i == idx else c for i, c in enumerate(certs)]

        recovered = stored_exp if not suppressed else None
        gained_number = bool(card_no) and not normalize_card_number(
            row.get("card_number"))
        if recovered is not None:
            payload = {
                "card_number": card_no,
                "issue_date": issue_dt,
                "expiration_date": stored_exp,
                "expiration_raw_rejected": None,
                "needs_review": needs_review,
                "review_reason": reason,
                "extraction_completeness": completeness,
            }
            action = "recover"
        elif gained_number or base["fault_before"]:
            # NO EXPIRY, BUT THE ROW STILL HAS TO SAY WHY -- and Angel's says
            # nothing. This is the branch that closes the invariant on a row
            # whose date cannot be recovered: the number is filled if there is
            # one, and the derived reason and flag are written so the row names
            # its own gap. An empty `set` would leave the record exactly as
            # unreadable as it is now.
            payload = {
                "card_number": card_no,
                "expiration_raw_rejected": raw if suppressed else None,
                "needs_review": needs_review,
                "review_reason": reason,
                "extraction_completeness": completeness,
            }
            action = "number-only" if gained_number else "reason-only"
        else:
            payload = {}
            action = "leave"

        img_before = card_image_may_be_replaced(worker, "probe")
        img_after = card_image_may_be_replaced(after_worker, "probe")
        plans.append(dict(
            base,
            action=action,
            raw=raw,
            raw_from=raw_from,
            recovered=recovered,
            set=payload,
            after={
                "card_number": card_no,
                "expiration_date": stored_exp,
                "needs_review": needs_review,
                "review_reason": reason,
                "expiration_raw_rejected": raw if suppressed else None,
                "extraction_completeness": completeness,
                "sst_state": server._sst_cert_state(after_row, now),
            },
            fault_after=cert_row_fault(after_row),
            img_before=img_before, img_after=img_after,
            img_locks=bool(img_before and not img_after),
        ))
    return plans


def _fmt(dt):
    return dt.date().isoformat() if isinstance(dt, datetime) else "-"


def print_report(all_plans, now, execute):
    print("=" * 78)
    print(f"{'EXECUTE' if execute else 'DRY RUN (read-only, nothing is written)'}"
          f"  --  cert rows re-derived from the stored read  --  {now.isoformat()}")
    print("=" * 78)
    for p in all_plans:
        b, a = p["before"], p["after"]
        print(f"\n{str(p['worker'])[:40]}  [{p['type']}]  cert[{p['cert_index']}]"
              f"   action={p['action']}")
        print(f"  raw expiry        : {p['raw']!r}  (from {p['raw_from']})")
        print(f"  card_number       : {b['card_number']!r} -> {a['card_number']!r}")
        print(f"  expiration_date   : {_fmt(b['expiration_date'])} -> "
              f"{_fmt(a['expiration_date'])}")
        print(f"  needs_review      : {b['needs_review']} -> {a['needs_review']}")
        print(f"  review_reason     : {b['review_reason']!r} -> {a['review_reason']!r}")
        print(f"  raw_rejected      : {b['expiration_raw_rejected']!r} -> "
              f"{a['expiration_raw_rejected']!r}")
        print(f"  completeness      : {b['extraction_completeness']} -> "
              f"{a['extraction_completeness']}")
        print(f"  sst_state (after) : {a.get('sst_state')}")
        print(f"  row fault         : {p['fault_before']!r}")
        print(f"                   -> {p['fault_after']!r}")
        print(f"  card image replaceable: {p['img_before']} -> {p['img_after']}"
              + ("   [IMAGE LOCKS]" if p["img_locks"] else ""))
    # NAMED LISTS, COUNTED AFTERWARDS -- the shape the four lines above already
    # use, and the three tallies below were the only ones spelled as an inline
    # `len([... p["field"] ...])`. That shape is what
    # scripts/audit_probe_field_discipline.py flags: it cannot tell a key this
    # module WROTE twenty lines up from a Mongo field name a probe guessed, and
    # a confident zero off a guessed field name is the class of bug that rule
    # exists for. Consistent with the rest of the function either way.
    rec = [p for p in all_plans if p["action"] == "recover"]
    num = [p for p in all_plans if p["action"] in ("number-only", "reason-only")]
    left = [p for p in all_plans if p["action"] == "leave"]
    skipped = [p for p in all_plans if p["action"] == "skip-verified"]
    unsound_before = [p for p in all_plans if p["fault_before"]]
    unsound_after = [p for p in all_plans if p["fault_after"]]
    locking = [p for p in all_plans if p["img_locks"]]
    print("\n" + "-" * 78)
    print(f"rows in scope                     : {len(all_plans)}")
    print(f"  expiry recovered                : {len(rec)}")
    print(f"  number / reason written only    : {len(num)}")
    print(f"  left for the human              : {len(left)}")
    print(f"  skipped, verified row           : {len(skipped)}")
    print(f"  unsound BEFORE                  : {len(unsound_before)}")
    print(f"  unsound AFTER                   : {len(unsound_after)}")
    print(f"  card image becomes UNREPLACEABLE: {len(locking)}")
    still = [p for p in rec if p["after"]["needs_review"]]
    if still:
        print(f"  recovered but STILL flagged     : {len(still)}"
              "  (the gate refused the recovered date, or another reason stands)")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    refuse_legacy_flag(argv)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", action="store_true",
                    help="report only; the default, accepted explicitly")
    add_guard_args(ap)
    args = ap.parse_args(argv)
    execute = check_guard(args)

    # THE SAME RULE, ONE FUNCTION, TWO CALL SITES. The copy above runs before
    # `import server` so a script invocation gets the sentence rather than a
    # KeyError; this one runs for a caller that imported the module and invoked
    # main() itself, where the import has already succeeded and the environment
    # can still be half-set.
    absent = missing_env()
    if absent:
        print("Set " + " and ".join(absent) + " in the environment first.")
        return 1
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    try:
        from pymongo import MongoClient
    except ImportError:
        print("pymongo not importable -- run inside the backend venv.")
        return 1

    db = audited(MongoClient(mongo_url)[db_name], args, NAME)
    now = datetime.now(timezone.utc)

    # $elemMatch, not a dotted $nin: a dotted path on an EMPTY certifications
    # array still came back as a match on production, dragging in workers with
    # no certification rows at all. $elemMatch asks the question about a ROW.
    #
    # DELIBERATELY WIDER THAN THE SCOPE. This selector fetches every worker with
    # an SST row that has no expiry OR a rejected raw value; `row_is_in_scope`
    # then decides, in one pure function the tests can drive. A narrow query
    # would put half the rule in Mongo where nothing can test it.
    selector = {"certifications": {"$elemMatch": {"$or": [
        {"expiration_date": None},
        {"expiration_raw_rejected": {"$nin": [None, ""]}},
    ]}}}
    all_plans = []
    for w in db.workers.find(
            selector,
            {"_id": 1, "name": 1, "certifications": 1, "osha_data": 1,
             "osha_number": 1, "osha_card_image": 1, "osha_card_r2_key": 1}):
        all_plans.extend(plan_for_worker(w, now))

    print_report(all_plans, now, execute)

    writable = [p for p in all_plans if p["set"]]
    if not execute:
        report_dry_run(
            f"re-derive {len(writable)} certification row(s) from the stored "
            f"read; {len(all_plans) - len(writable)} left untouched")
        return 0

    written = 0
    skipped_changed = 0
    for p in writable:
        idx = p["cert_index"]
        # THE ROW'S PRIOR STATE IS PART OF THE FILTER. The plan was computed
        # from a read; if that row changed in between -- a re-scan cleared it,
        # an admin corrected it -- the write must MISS rather than overwrite
        # somebody else's answer. It also makes a second run a no-op.
        res = db.workers.update_one(
            {"_id": p["worker_id"],
             f"certifications.{idx}.expiration_date": p["before"]["expiration_date"],
             f"certifications.{idx}.card_number": p["before"]["card_number"]},
            {"$set": {f"certifications.{idx}.{k}": v
                      for k, v in p["set"].items()}})
        if res.matched_count:
            written += 1
        else:
            skipped_changed += 1
            print(f"  SKIPPED {p['worker']}: the row changed since the report "
                  f"was computed. Re-run the dry run.")
    print(f"\nwrote {written} certification row(s); "
          f"{skipped_changed} skipped as changed.")
    print(f"audit rows written by the audited handle, actor script:{NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
