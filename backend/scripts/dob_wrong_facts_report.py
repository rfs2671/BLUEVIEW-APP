"""Which production DOB records showed a WRONG complaint label or ECB penalty,
and where each was shown -- READ ONLY (#869).

    railway run --service Blueview2 --environment production python backend/scripts/dob_wrong_facts_report.py [out_dir]

WHAT WAS WRONG (fixed in #869):
  1. COMPLAINT LABEL. Complaint summaries (dob_logs.ai_summary) came from a
     hand-written dict that was wrong for all 17 codes it listed (05 "Permit -
     None" read "work contrary to approved plans"). A row is affected when its
     category is one of those 17 AND its stored summary carries the old text.
  2. ECB PENALTY. penalty_amount was read from `amount_paid`, not the penalty
     imposed (ECB 6bgk-3dad `penality_imposed`). A row is affected when its
     stored penalty differs from DOB's `penality_imposed` for that summons
     (read live, read-only, from NYC Open Data).

WHERE IT WAS SHOWN, from what production records (nothing is inferred):
  * EMAIL: notification_log rows for the record (critical_dob_alert,
    permit_renewal_id "dob_log:<raw id>[:event]") -- date, recipient, status.
    The alert email quotes ai_summary, so a wrong label was in its text.
  * FEED: the row is live in dob_logs, so the Compliance screen / Activity
    feed showed it from detected_at until the next sync rewrites it.
  * WHATSAPP GROUP: whatsapp_notification_ledger rows "gc:<project>:<kind>:
    <raw id>..." -- status, date. That ledger has a TTL: older posts may be
    gone, which the report says rather than reporting "none".
  * WHATSAPP BRIEF (penalty only): the brief's text is not stored; brief_log
    rows with status sent for the project's company since the record was
    detected are listed as "a brief went while the stored penalty was wrong".

READ ONLY, enforced here: every pymongo write method raises (installed before
the client exists), and the only HTTP is GETs to data.cityofnewyork.us.
Nothing is sent. Output: printed tables + CSVs in out_dir (default
docs/samples/dob_wrong_facts/).
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)

from probe_helpers import counted, require_fields  # noqa: E402  (no app imports)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

#: The 17 codes the removed dict listed, and the wrong text it gave each.
OLD_DICT = {
    "01": "illegal work or work without a permit", "03": "failure to maintain building facade",
    "05": "work contrary to approved plans", "06": "unsafe construction condition",
    "09": "illegal conversion or occupancy", "12": "failure to maintain elevator",
    "14": "demolition without permit", "23": "working without a safety net",
    "28": "illegal curb cut or sidewalk damage", "30": "debris falling from building",
    "45": "unsafe scaffolding or sidewalk shed", "49": "construction noise outside allowed hours",
    "59": "work without required DOB inspection", "63": "illegal fence or retaining wall",
    "71": "crane or derrick safety violation", "83": "failure to safeguard persons or property",
    "91": "building under construction in unsafe condition",
}
NYC = "https://data.cityofnewyork.us/resource/6bgk-3dad.json"
_WRITES = ("insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one",
           "delete_many", "bulk_write", "find_one_and_update", "find_one_and_replace",
           "find_one_and_delete", "create_index", "create_indexes", "drop", "rename", "drop_index")


class ReadOnlyViolation(RuntimeError):
    pass


def lock_writes() -> int:
    """Every pymongo write method raises. Returns how many were replaced."""
    from pymongo.collection import Collection

    def refuse(name):
        def _r(self, *a, **k):
            raise ReadOnlyViolation(f"read-only report: {name} on {self.full_name} refused")
        _r.__readonly_refuser__ = True
        return _r
    n = 0
    for w in _WRITES:
        if hasattr(Collection, w):
            setattr(Collection, w, refuse(w))
            n += 1
    return n


def nyc_get(where: str) -> list:
    """GET only, to NYC Open Data only."""
    url = NYC + "?" + urllib.parse.urlencode({"$where": where, "$limit": "5000",
                                              "$select": "ecb_violation_number,penality_imposed,"
                                                         "amount_paid,balance_due,hearing_status"})
    assert urllib.parse.urlparse(url).hostname == "data.cityofnewyork.us"
    with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _num(v):
    try:
        return float(str(v).replace("$", "").replace(",", "")) if str(v or "").strip() else None
    except ValueError:
        return None


def main(out_dir: str) -> int:
    url = os.environ.get("DOB_REPORT_MONGO_URL") or os.environ.get("MONGO_URL")
    name = os.environ.get("DOB_REPORT_DB") or os.environ.get("DB_NAME")
    if not url or not name:
        sys.exit("No database: MONGO_URL/DB_NAME (railway run sets them) or DOB_REPORT_MONGO_URL/"
                 "DOB_REPORT_DB. Nothing was read.")
    n = lock_writes()
    from pymongo import MongoClient
    from pymongo.collection import Collection
    # Checked BEFORE anything is read: every write method IS the refuser (the
    # guard test makes the real write calls; this script makes none).
    unlocked = [w for w in _WRITES if hasattr(Collection, w)
                and not getattr(getattr(Collection, w), "__readonly_refuser__", False)]
    if unlocked:
        sys.exit(f"GUARD FAILED: {unlocked} not refused. Nothing was read.")
    print(f"read-only guard: {n} write methods refused")
    db = MongoClient(url, serverSelectionTimeoutMS=15000, tz_aware=True).get_database(name)
    print(f"database: {name} on {urllib.parse.urlparse(url).hostname}  (credentials not printed)")

    from dob_complaint_codes import get_category_label
    projects = {str(p["_id"]): p for p in db.projects.find({}, {"name": 1, "company_id": 1})}
    companies = {str(c["_id"]): c for c in db.companies.find({}, {"name": 1, "is_test": 1})}

    def where_shown(row, raw):
        pid = str(row.get("project_id") or "")
        emails = list(db.notification_log.find(
            {"permit_renewal_id": {"$regex": f"^dob_log:{raw}(:|$)"}},
            {"sent_at": 1, "recipient": 1, "status": 1, "trigger_type": 1}))
        wa = list(db.whatsapp_notification_ledger.find(
            {"_id": {"$regex": f"^gc:{pid}:[^:]+:{raw}"}}, {"status": 1, "created_at": 1, "kind": 1}))
        if emails:
            require_fields(emails, "status", "recipient")       # probe_helpers: no confident zero
        sent = [e for e in emails if e.get("status") == "sent"]
        return {
            "emails": "; ".join(f"{(e.get('sent_at') or '')!s:.10} {e.get('status')}" for e in emails),
            "email_count": counted(emails, "status", lambda v: v == "sent") if emails else 0,
            "email_recipients": len({e.get("recipient") for e in sent}),
            "feed": (f"live since {str(row.get('detected_at') or '')[:10]}"
                     if not row.get("is_deleted") else "deleted"),
            "whatsapp": ("; ".join(f"{w.get('kind')} {w.get('status')} {str(w.get('created_at') or '')[:10]}"
                                   for w in wa) or "none in the ledger (it has a TTL: older posts expire)"),
        }

    def who(row):
        p = projects.get(str(row.get("project_id") or "")) or {}
        c = companies.get(str(p.get("company_id") or "")) or {}
        return p.get("name") or row.get("project_id"), c.get("name") or p.get("company_id"), bool(c.get("is_test"))

    # 1. complaint labels
    label_rows = []
    for r in db.dob_logs.find({"record_type": "complaint",
                               "complaint_category": {"$in": list(OLD_DICT)}}):
        cat = str(r.get("complaint_category") or "")
        if OLD_DICT[cat] not in str(r.get("ai_summary") or "").lower():
            continue
        raw = str(r.get("raw_dob_id") or r.get("complaint_number") or "")
        proj, comp, test = who(r)
        label_rows.append({"company": comp, "test_company": test, "project": proj, "record": raw,
                           "category": cat, "shown_label": OLD_DICT[cat],
                           "correct_label": get_category_label(cat), **where_shown(r, raw)})

    # 2. ECB penalties (compared with DOB's own penality_imposed, read live)
    # An ECB summons number is 8 digits and a letter (39558662P).
    ecb_no = re.compile(r"^\d{8}[A-Z]$")
    ecb = [r for r in db.dob_logs.find({"record_type": "violation", "violation_number": {"$ne": None}})
           if str(r.get("violation_subtype") or "").upper() == "ECB"
           or ecb_no.match(str(r.get("violation_number") or "").upper())]
    nums = sorted({str(r.get("violation_number")) for r in ecb if r.get("violation_number")})
    truth = {}
    for i in range(0, len(nums), 150):
        chunk = ",".join("'" + n.replace("'", "") + "'" for n in nums[i:i + 150])
        for d in nyc_get(f"ecb_violation_number in ({chunk})"):
            truth[d.get("ecb_violation_number")] = d
    penalty_rows = []
    for r in ecb:
        t = truth.get(str(r.get("violation_number")))
        if not t:
            continue
        stored, imposed = _num(r.get("penalty_amount")), _num(t.get("penality_imposed"))
        if imposed is None or stored == imposed:
            continue
        raw = str(r.get("raw_dob_id") or r.get("violation_number"))
        proj, comp, test = who(r)
        cid = str((projects.get(str(r.get("project_id"))) or {}).get("company_id") or "")
        since = str(r.get("detected_at") or "")[:10]
        briefs = (db.brief_log.count_documents({"company_id": cid, "status": {"$in": ["sent", "resent"]}, "day": {"$gte": since}})
                  if "brief_log" in db.list_collection_names() else None)
        penalty_rows.append({"company": comp, "test_company": test, "project": proj, "record": raw,
                             "shown_penalty": r.get("penalty_amount"), "dob_penalty_imposed": t.get("penality_imposed"),
                             "amount_paid": t.get("amount_paid"), "hearing_status": t.get("hearing_status"),
                             "briefs_sent_to_company": briefs, **where_shown(r, raw)})

    os.makedirs(out_dir, exist_ok=True)
    for fname, rows in (("wrong_complaint_labels.csv", label_rows), ("wrong_ecb_penalties.csv", penalty_rows)):
        with open(os.path.join(out_dir, fname), "w", newline="", encoding="utf-8") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
    for title, rows, cols in (
            ("WRONG COMPLAINT LABELS", label_rows,
             ("company", "project", "record", "category", "shown_label", "correct_label",
              "email_count", "email_recipients", "emails", "feed", "whatsapp")),
            ("WRONG ECB PENALTIES", penalty_rows,
             ("company", "project", "record", "shown_penalty", "dob_penalty_imposed", "hearing_status",
              "email_count", "emails", "feed", "whatsapp", "briefs_sent_to_company"))):
        tests = counted(rows, "test_company", bool) if rows else 0
        print(f"\n=== {title}: {len(rows)} record(s) ({tests} in test companies) ===")
        for r in sorted(rows, key=lambda x: (x["test_company"], str(x["company"]), str(x["project"]))):
            print("  " + " | ".join(f"{c}={r.get(c)}" for c in cols))
    print(f"\nread at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC; wrote {os.path.abspath(out_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else os.path.join(BACKEND, "..", "docs", "samples", "dob_wrong_facts")))
