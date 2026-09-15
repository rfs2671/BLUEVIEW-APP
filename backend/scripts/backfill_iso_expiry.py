"""Recover the expiry dates a narrow parser threw away. READ-ONLY BY DEFAULT.

WHY A BACKFILL AT ALL. `needs_review` and `review_reason` are written ONCE, in
`build_worker_certifications`, at check-in/registration. Nothing re-derives them
on read: `_sst_cert_state` and `validate_worker_certifications` never consult
`needs_review`. So widening `parse_cert_date` to accept ISO-8601 stops the NEXT
twelve men from being flagged and clears NOBODY already on the record.

WHY IT IS SAFE. The string the parser refused is preserved verbatim in
`expiration_raw_rejected`. This script re-runs the WIDENED parser over that
stored string and, where it resolves, writes `expiration_date`, clears
`expiration_raw_rejected`, and lets the gate decide the flag. It invents
nothing, and every input is still on the record afterwards.

RE-DERIVE, NEVER HAND-LOWER. The recovered date goes back through
`server.evaluate_cert_expiry` and `server.derive_cert_review` -- the SAME two
functions the scanner calls -- so the plausibility rules (`exp <= issue`, the
class-aware ceiling) and the completeness rules all get their say on it. A
recovered date CAN come back refused: a date past the 7-year ceiling leaves the
row flagged as EXPIRY_IMPLAUSIBLE instead of EXPIRY_UNPARSEABLE, and that is
the right answer. Assigning `needs_review = False` by hand is what made PR #530
look like a cure and got it parked;
tests/test_iso_expiry_backfill.py::test_the_planner_never_assigns_the_flag_by_hand
reads this planner's AST and fails if it ever happens again.

WHAT IT DOES TO THE CARD IMAGE, STATED PER ROW. `card_image_may_be_replaced`
reads `needs_review or expiration_date is None`. Every row this clears flips it
to False, which means a stored card photo can no longer be overwritten by a
later re-scan. The report prints that transition for every row. On production
as measured 2026-09-15 it moves NOTHING -- none of the twelve has a card image
on file, so the predicate already returns True on its no-image branch -- but it
is printed anyway, because inheriting that effect silently is the defect that
parked #530.

WHAT IT REFUSES TO TOUCH:
  * a VERIFIED row. `build_worker_certifications` will not let a re-scan modify
    one ("admin-confirmed"); a backfill has less standing than a re-scan.
  * `'illegible'`, `'null'`, `'05/35'`, `'10272029'`, `'062427'`. The parser
    refuses these by design -- see the comment at `server.parse_cert_date` --
    and they stay on the human correction path, which is Build 2.

USAGE. Report is the default. There is no way to write without asking.

    $env:MONGO_URL='<Atlas URI>'; $env:DB_NAME='<db>'
    python backfill_iso_expiry.py             # --report (default): writes nothing
    python backfill_iso_expiry.py --execute   # applies the plan above

Reads MONGO_URL / DB_NAME from env; never prints the connection string.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from server import (  # noqa: E402
    card_image_may_be_replaced,
    derive_cert_review,
    evaluate_cert_expiry,
    RECOGNIZED_SST_TYPES,
    SST_CLASS_TYPES,
    SST_DEAD_CLASSES,
)


def wants_execute(argv):
    """READ-ONLY UNLESS ASKED. `--report` is the default and also accepted
    explicitly, so an operator can say which one he means."""
    return "--execute" in list(argv or [])


def _aware(dt):
    if isinstance(dt, datetime):
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return None


def plan_for_worker(worker, now):
    """PURE. Returns one plan dict per certification carrying a rejected raw
    expiry. Mutates nothing -- the caller decides whether to write.

    Each plan:
      action      'recover' | 'leave' | 'skip-verified'
      set         the exact $set payload, or {} when nothing is written
      after       the row as it WOULD read, including the re-derived flag
      img_before / img_after / img_locks   the card_image_may_be_replaced move
    """
    certs = list(worker.get("certifications") or [])
    plans = []
    for idx, row in enumerate(certs):
        raw = row.get("expiration_raw_rejected")
        if not raw:
            continue

        base = {
            "worker": worker.get("name"),
            # `_id`, NOT `id`. Measured on production: every affected worker
            # document has `id: null`, and every write path in server.py keys
            # on `_id` (`to_query_id(worker_id)`). Filtering on `id` would have
            # matched nothing at best and an arbitrary `id: null` document at
            # worst.
            "worker_id": worker.get("_id"),
            "cert_index": idx,
            "type": str(row.get("type") or ""),
            "card_number": row.get("card_number"),
            "raw": raw,
            "before": {"needs_review": bool(row.get("needs_review")),
                       "review_reason": row.get("review_reason"),
                       "expiration_date": row.get("expiration_date")},
        }

        if row.get("verified"):
            plans.append(dict(base, action="skip-verified", recovered=None,
                              set={}, after=dict(base["before"]),
                              img_before=None, img_after=None, img_locks=False))
            continue

        issue_dt = _aware(row.get("issue_date"))
        sst_type = str(row.get("type") or "")
        stored_exp, suppressed, gate_reason = evaluate_cert_expiry(
            raw, issue_dt, sst_type, now)

        # The completeness inputs, reconstructed from the STORED row rather
        # than from `osha_data`. Deliberate: `osha_data` on the worker document
        # is the LATEST scan and need not be the scan this row came from, so
        # reading an issue date or a name out of it would be attributing one
        # card's data to another card's row. The row's own fields are the only
        # evidence tied to this certification.
        name_ok = bool(str(worker.get("name") or "").strip())
        number_ok = bool(str(row.get("card_number") or "").strip())
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
        after_row["expiration_date"] = stored_exp
        after_row["expiration_raw_rejected"] = None if not suppressed else raw
        after_row["needs_review"] = needs_review
        after_row["review_reason"] = reason
        after_row["extraction_completeness"] = completeness

        after_worker = dict(worker)
        after_worker["certifications"] = [
            after_row if i == idx else c for i, c in enumerate(certs)]

        recovered = stored_exp if not suppressed else None
        if recovered is not None:
            # The fields that would change on this row. `main()` turns these
            # into the dotted `certifications.{idx}.<field>` $set keys; keeping
            # them un-dotted here is what makes the plan readable in the report
            # and assertable in the tests. An EMPTY dict means NO WRITE, and
            # that is the only signal a caller needs to leave a row alone.
            payload = {
                "expiration_date": stored_exp,
                "expiration_raw_rejected": None,
                "needs_review": needs_review,
                "review_reason": reason,
                "extraction_completeness": completeness,
            }
            action = "recover"
        else:
            payload = {}
            action = "leave"

        img_before = card_image_may_be_replaced(worker, "probe")
        img_after = card_image_may_be_replaced(after_worker, "probe")
        plans.append(dict(
            base,
            action=action,
            recovered=recovered,
            set=payload,
            after={"needs_review": needs_review, "review_reason": reason,
                   "expiration_date": stored_exp,
                   "extraction_completeness": completeness,
                   "sst_state": server._sst_cert_state(after_row, now)},
            img_before=img_before, img_after=img_after,
            img_locks=bool(img_before and not img_after),
        ))
    return plans


def _fmt(dt):
    return dt.date().isoformat() if isinstance(dt, datetime) else "-"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    unknown = [a for a in argv if a not in ("--report", "--execute")]
    if unknown:
        print(f"unknown argument(s): {' '.join(unknown)}")
        return 2
    execute = wants_execute(argv)

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("Set MONGO_URL and DB_NAME in the environment first.")
        return 1
    try:
        from pymongo import MongoClient
    except ImportError:
        print("pymongo not importable -- run inside the backend venv.")
        return 1

    db = MongoClient(mongo_url)[db_name]
    now = datetime.now(timezone.utc)

    print("=" * 78)
    print(f"{'EXECUTE' if execute else 'REPORT (read-only, nothing is written)'}"
          f"  --  ISO expiry recovery  --  {now.isoformat()}")
    print("=" * 78)

    all_plans = []
    # $elemMatch, not a dotted $nin: a dotted path on an EMPTY certifications
    # array still came back as a match on production, dragging in workers with
    # no certification rows at all. $elemMatch asks the question about a row.
    for w in db.workers.find(
            {"certifications": {"$elemMatch":
                                {"expiration_raw_rejected": {"$nin": [None, ""]}}}},
            {"_id": 1, "name": 1, "certifications": 1,
             "osha_card_image": 1, "osha_card_r2_key": 1}):
        all_plans.extend(plan_for_worker(w, now))

    hdr = (f"{'worker':24} {'raw':12} {'recovered':11} {'needs_review':12} "
           f"{'review_reason':20} {'img replaceable':16} action")
    print(hdr)
    print("-" * len(hdr))
    for p in all_plans:
        print(f"{str(p['worker'])[:24]:24} {str(p['raw'])[:12]:12} "
              f"{_fmt(p['recovered']):11} "
              f"{str(p['before']['needs_review']) + '->' + str(p['after']['needs_review']):12} "
              f"{str(p['before']['review_reason']) + '->' + str(p['after']['review_reason']):20} "
              f"{str(p['img_before']) + '->' + str(p['img_after']):16} "
              f"{p['action']}"
              + ("   [IMAGE LOCKS]" if p["img_locks"] else ""))

    rec = [p for p in all_plans if p["action"] == "recover"]
    left = [p for p in all_plans if p["action"] == "leave"]
    skipped = [p for p in all_plans if p["action"] == "skip-verified"]
    locks = [p for p in rec if p["img_locks"]]
    print("-" * len(hdr))
    print(f"rows carrying a rejected raw expiry : {len(all_plans)}")
    print(f"  recovered by the widened parser   : {len(rec)}")
    print(f"  left for the human (Build 2)      : {len(left)}")
    print(f"  skipped, verified row             : {len(skipped)}")
    print(f"  card image becomes UNREPLACEABLE  : {len(locks)}")
    still_flagged = [p for p in rec if p["after"]["needs_review"]]
    if still_flagged:
        print(f"  recovered but STILL flagged       : {len(still_flagged)}"
              " (the gate refused the recovered date, or another reason stands)")

    if not execute:
        print("\nNothing was written. Re-run with --execute to apply the plan above.")
        return 0

    written = 0
    skipped_changed = 0
    for p in rec:
        idx = p["cert_index"]
        # THE RAW STRING IS PART OF THE FILTER. The plan was computed from a
        # read; if that row changed in between -- a re-scan cleared it, an
        # admin corrected it -- the write must miss rather than overwrite
        # somebody else's answer. It also makes a second run a no-op.
        res = db.workers.update_one(
            {"_id": p["worker_id"],
             f"certifications.{idx}.expiration_raw_rejected": p["raw"]},
            {"$set": {f"certifications.{idx}.{k}": v
                      for k, v in p["set"].items()}})
        if res.matched_count:
            written += 1
        else:
            skipped_changed += 1
            print(f"  SKIPPED {p['worker']}: the row changed since the report "
                  f"was computed. Re-run --report.")
    print(f"\nwrote {written} certification row(s); "
          f"{skipped_changed} skipped as changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
