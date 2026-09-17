"""Convert stored insurance dates from MM/DD/YYYY to ISO. READ-ONLY BY DEFAULT.

── IT CHANGES NOTHING TODAY, AND IT EXISTS ANYWAY ──────────────────────────

Measured 2026-09-17: production holds ZERO insurance records. Both live
companies carry an empty `gc_insurance_records` list, so this script's first
run will print a census of nothing and write nothing.

It is written now because the format changed now. `PUT /admin/company/
insurance/manual` stopped writing `%m/%d/%Y` and started writing
`YYYY-MM-DD` in the same commit as this file, and the COI confirm endpoint
began normalising to ISO instead of storing raw. Every record from here on is
ISO. The records this converts are the ones somebody enters BEFORE noticing
that an old deploy is still serving, or restores from a backup taken before
today, or that arrive from a path nobody has thought of yet. A migration
written six months after the format change is a migration written against a
database whose contents nobody remembers.

It is also the only way the conversion can happen at all under the operator
rule: a production write goes through the app, which is audited, or through a
file in this directory carrying the guard. There is no third option, and
"it was only two rows" is how the 19:07:45Z session started.

── WHY NO MIXED-FORMAT PERIOD IS REQUIRED ──────────────────────────────────

Every active reader accepts BOTH formats, which was checked and not assumed:

  lib/insurance_expiry.read_expiry     dateutil — the digest and the permit
                                       expiry both go through it
  permit_renewal.check_renewal_...     dateutil
  frontend parseStoredDate             ISO, and MMDDYYYY with optional slashes

So a half-converted collection reads correctly throughout, and this script can
be run whenever — or never, on a database that has no legacy rows. Nothing
waits on it.

── WHAT IT WILL NOT DO ─────────────────────────────────────────────────────

INVENT A DATE. The conversion is `normalise_stored_expiry`, the same strict
reader the COI confirm endpoint writes through: ISO, or eight digits in
MMDDYYYY order with the slashes optional, a real day, a year in 1900-2199.
'7/2/29' is REFUSED, not widened to 2029 — nothing here can tell a dropped
digit from a two-digit year, and a guess on a compliance record is worse than
a row left alone. Those are reported as `leave` and belong to a human, in
Settings, where the shared date field shows the stored string next to the
field that replaces it.

TOUCH A VALUE THAT IS ALREADY ISO. A record already in `YYYY-MM-DD` is
reported as `iso` and is not part of any `$set`. A second run is a no-op.

TOUCH ANYTHING BUT THE TWO DATE FIELDS. `source`, `is_current`,
`coi_pdf_url`, `ocr_confidence` and the rest are read and printed and never
written. In particular it does NOT repair a `source` outside the Literal —
that is permit_renewal's per-record validation to survive, not a value to
rewrite.

USAGE. The report is the default. There is no way to write without asking.

    $env:MONGO_URL='<Atlas URI>'; $env:DB_NAME='<db>'
    python backfill_insurance_expiry_iso.py               # writes nothing
    python backfill_insurance_expiry_iso.py --i-know \
        --reason '<why>' --session <id>                   # applies the plan

`--execute` NO LONGER APPLIES ANYTHING. It is refused by name, pointing at
`--i-know`, rather than honouring it (which would make the guard decoration)
or quietly doing nothing (which would tell an operator a migration ran when it
did not).

Reads MONGO_URL / DB_NAME from env; never prints the connection string.
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.insurance_expiry import normalise_stored_expiry, quote  # noqa: E402

# ── PRODUCTION WRITE GUARD ──────────────────────────────────────────────────
# Every write below goes through `audited(...)`, which records it in audit_logs
# with actor "script:backfill_insurance_expiry_iso", the session and the
# reason. Without --i-know the handle is unwrapped and nothing is written. See
# prod_guard.
#
# A PYMONGO HANDLE, like backfill_iso_expiry and backfill_deleted_at. `audited`
# decides sync-or-async from what the driver hands back, so the wrap reads the
# same as in the motor scripts.
from prod_guard import (  # noqa: E402
    add_guard_args, audited, check_guard, refuse_legacy_flag,
)

NAME = "backfill_insurance_expiry_iso"

#: The two fields on a record that hold a calendar day. NOT a wider sweep:
#: `dob_now_verified_at` is an instant and is stored as a BSON date.
DATE_FIELDS = ("expiration_date", "effective_date")


def plan_for_company(company):
    """PURE. One plan dict per (record, field) that holds a date, whatever
    shape it is in. Mutates nothing — the caller decides whether to write.

    Each plan:
      action   'convert' | 'iso' | 'leave' | 'blank'
      path     the dotted $set key, e.g. gc_insurance_records.0.expiration_date
      before   the stored string, quoted
      after    the ISO string, or None when nothing would be written
      why      for 'leave', the reader's own refusal sentence
    """
    plans = []
    company_id = company.get("_id")
    records = company.get("gc_insurance_records") or []
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            # A non-dict in the list is not a record and has no date to
            # convert. Reported so the census does not pretend it saw one.
            plans.append({
                "company_id": company_id,
                "company_name": company.get("name"),
                "insurance_type": "-", "field": "-",
                "path": f"gc_insurance_records.{idx}",
                "before": quote(rec), "after": None, "action": "leave",
                "why": "not a record — the list holds something that is not an object",
            })
            continue
        for field in DATE_FIELDS:
            raw = rec.get(field)
            base = {
                "company_id": company_id,
                "company_name": company.get("name"),
                "insurance_type": str(rec.get("insurance_type") or "-"),
                "field": field,
                "path": f"gc_insurance_records.{idx}.{field}",
                "before": quote(raw) if raw is not None else "",
            }
            if raw is None or not str(raw).strip():
                plans.append(dict(base, after=None, action="blank", why=""))
                continue
            try:
                iso = normalise_stored_expiry(raw)
            except ValueError as e:
                # THE HUMAN PATH. Reported with the reader's own sentence,
                # which is the same one the admin sees under the field in
                # Settings — so a report row and the screen say one thing.
                plans.append(dict(base, after=None, action="leave", why=str(e)))
                continue
            if iso == str(raw).strip():
                plans.append(dict(base, after=iso, action="iso", why=""))
            else:
                plans.append(dict(base, after=iso, action="convert", why=""))
    return plans


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    refuse_legacy_flag(argv)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", action="store_true",
                    help="report only; the default, accepted explicitly")
    add_guard_args(ap)
    args = ap.parse_args(argv)
    execute = check_guard(args)

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

    db = audited(MongoClient(mongo_url)[db_name], args, NAME)
    now = datetime.now(timezone.utc)

    print("=" * 78)
    print(f"{'EXECUTE' if execute else 'REPORT (read-only, nothing is written)'}"
          f"  --  insurance expiry -> ISO  --  {now.isoformat()}")
    print("=" * 78)

    all_plans = []
    # THE FILTER IS "HAS ANY RECORD AT ALL", not "has a non-ISO record. A
    # dotted `$not` on a regex over a subdocument array matches on ANY element,
    # so a company with one legacy and two ISO records comes back either way
    # and the narrower filter only buys a chance of being subtly wrong. The
    # collection is two live companies; reading all of them costs nothing and
    # the census then covers every record rather than the ones a query guessed.
    #
    # SOFT-DELETED COMPANIES ARE INCLUDED, deliberately. A restored company
    # must not come back holding a format nothing writes any more, and the
    # readers do not check `is_deleted` before parsing.
    for company in db.companies.find(
            {"gc_insurance_records": {"$exists": True, "$ne": []}},
            {"_id": 1, "name": 1, "is_deleted": 1, "gc_insurance_records": 1}):
        all_plans.extend(plan_for_company(company))

    hdr = (f"{'company':22} {'type':18} {'field':16} {'stored':14} "
           f"{'would become':12} action")
    print(hdr)
    print("-" * len(hdr))
    for p in all_plans:
        print(f"{str(p['company_name'])[:22]:22} {p['insurance_type'][:18]:18} "
              f"{p['field'][:16]:16} {p['before'][:14]:14} "
              f"{str(p['after'] or '-'):12} {p['action']}"
              + (f"   [{p['why']}]" if p["why"] else ""))

    convert = [p for p in all_plans if p["action"] == "convert"]
    already = [p for p in all_plans if p["action"] == "iso"]
    leave = [p for p in all_plans if p["action"] == "leave"]
    blank = [p for p in all_plans if p["action"] == "blank"]
    print("-" * len(hdr))
    print(f"date fields found                   : {len(all_plans)}")
    print(f"  would convert to ISO              : {len(convert)}")
    print(f"  already ISO, untouched            : {len(already)}")
    print(f"  left for the human (unreadable)   : {len(leave)}")
    print(f"  blank, nothing to convert         : {len(blank)}")
    if leave:
        print("\n  THE UNREADABLE ONES ARE NOT A FAILURE OF THIS SCRIPT. They are")
        print("  values no reader can turn into a day, which means the digest sends")
        print("  no reminder for them and permit expiry cannot use them. They are")
        print("  surfaced to the admin as \"insurance date unreadable\"; fix them in")
        print("  Settings -> Insurance, where the field shows the stored string.")

    if not execute:
        print("\nNothing was written. Re-run with "
              "--i-know --reason '<why>' --session <id> to apply the plan above.")
        return 0

    written = 0
    skipped_changed = 0
    for p in convert:
        # THE OLD STRING IS PART OF THE FILTER. The plan came from a read; if
        # that record changed in between -- an admin re-entered the date, the
        # COI flow replaced the record of that type -- the write must MISS
        # rather than overwrite somebody else's answer. It also makes a second
        # run a no-op, and it is what makes the positional path safe: if a
        # record were inserted ahead of this one, `gc_insurance_records.2.…`
        # would now name a different record and the filter would not match it.
        res = db.companies.update_one(
            {"_id": p["company_id"], p["path"]: p["before"]},
            {"$set": {p["path"]: p["after"]}})
        if res.matched_count:
            written += 1
        else:
            skipped_changed += 1
            print(f"  SKIPPED {p['company_name']} {p['path']}: the record "
                  f"changed since the report was computed. Re-run --report.")
    print(f"\nwrote {written} date field(s); {skipped_changed} skipped as changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
