"""READ-ONLY diagnostic — trace ONE worker's check-in through the cert gate.

Answers, for a specific worker, whether the E-fix (gate falls back to ON-FILE
OSHA evidence) resolves HIS case, or whether he is a different failure (the card
he uploaded today never produced evidence — an OCR/crop problem).

It does NOT write, update, or delete anything. Pure reads.

Run it the same way as the other scripts/*.py (PowerShell). Pass ANY identifiers
you have — phone, name, and/or the SST/OSHA card number — it ORs them all:

    $env:MONGO_URL='<Atlas URI>'; $env:DB_NAME='blueview'
    python diag_worker_checkin.py "555-123-4567"
    python diag_worker_checkin.py "Alex German Travez" "xhhegshgm0"
    python diag_worker_checkin.py "Alex German Travez" "xhhegshgm0" "555-123-4567"

Each argument is auto-classified: mostly-digits -> phone match; otherwise it is
tried as BOTH a name regex AND an osha_number match. Reads MONGO_URL / DB_NAME
from env; never prints the connection string.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

try:
    from pymongo import MongoClient
except ImportError:
    print("pymongo not importable — run inside the backend venv.")
    sys.exit(1)


def digits_only(s):
    return "".join(c for c in str(s or "") if c.isdigit())


def present(v):
    """A human 'present/absent' with a size hint, never dumping the value."""
    if v is None or v == "":
        return "ABSENT"
    if isinstance(v, str) and len(v) > 40:  # base64 image etc.
        return f"present (len={len(v)})"
    return f"present ({v!r})" if not isinstance(v, str) else f"present ('{v}')"


def main():
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("Set MONGO_URL and DB_NAME in the environment first.")
        sys.exit(1)
    if len(sys.argv) < 2:
        print('Usage: python diag_worker_checkin.py "<phone|name|sst#>" [more ...]')
        sys.exit(1)

    terms = [t for t in sys.argv[1:] if t and t.strip()]

    client = MongoClient(mongo_url)
    db = client[db_name]

    # ---- 1. Find the worker — OR every identifier (phone / name / osha number) ----
    or_clauses = []
    for term in terms:
        d = digits_only(term)
        if len(d) >= 7:  # looks like a phone
            or_clauses.append({"phone": {"$in": list({term, d, d[-10:]})}})
            or_clauses.append({"phone": {"$regex": d[-10:]}})
        else:            # name or SST/OSHA card number — try both
            or_clauses.append({"name": {"$regex": term, "$options": "i"}})
            or_clauses.append({"osha_number": {"$regex": f"^{term}$", "$options": "i"}})
    matches = list(db.workers.find(
        {"$or": or_clauses, "is_deleted": {"$ne": True}}
    ).limit(10))
    if not matches:
        print(f"NO worker found for {terms!r}.")
        print("If he checked in as a NEW worker whose submit ERRORED, no worker row")
        print("was created — that itself points at the error/loop path, not a block.")
        return
    if len(matches) > 1:
        print(f"⚠ {len(matches)} workers matched — showing the first. Others:")
        for m in matches[1:]:
            print(f"    {m.get('name')!r} phone={m.get('phone')!r} id={m.get('_id')}")
    worker = matches[0]

    wid = str(worker.get("_id"))
    certs = worker.get("certifications") or []
    osha_number = str(worker.get("osha_number") or "").strip()
    osha_card_image = worker.get("osha_card_image")
    osha_data = worker.get("osha_data") or {}

    print("=" * 68)
    print("WORKER RECORD")
    print("=" * 68)
    print(f"  name            : {worker.get('name')}")
    print(f"  phone           : {worker.get('phone')}")
    print(f"  worker_id       : {wid}")
    print(f"  company         : {worker.get('company')!r}")
    print(f"  trade           : {worker.get('trade')!r}")
    print(f"  company_id      : {worker.get('company_id')!r}")
    print(f"  assigned_projects: {worker.get('assigned_projects')}")
    print(f"  osha_number     : {present(osha_number)}")
    print(f"  osha_card_image : {present(osha_card_image)}")
    print(f"  osha_data keys  : {list(osha_data.keys()) if isinstance(osha_data, dict) else osha_data}")
    print(f"  osha_data.expiration: {osha_data.get('expiration') if isinstance(osha_data, dict) else None!r}")
    print(f"  certifications  : {len(certs)} on file")
    for i, c in enumerate(certs):
        print(f"      [{i}] type={c.get('type')!r} card_number={present(c.get('card_number'))} "
              f"expiration_date={c.get('expiration_date')!r} needs_review={c.get('needs_review')}")
    orientations = worker.get("safety_orientations") or []
    print(f"  safety_orientations: {len(orientations)} (projects: "
          f"{[o.get('project_id') for o in orientations]})")

    # ---- 2. His check-in / block footprint (last 3 days) ----
    since = datetime.now(timezone.utc) - timedelta(days=3)
    checkins = list(db.checkins.find({"worker_id": wid}).sort("check_in_time", -1).limit(10))
    recent_checkins = [c for c in checkins if (c.get("check_in_time") or since) >= since]
    alerts = list(db.compliance_alerts.find(
        {"worker_id": wid, "alert_type": "CERT_BLOCK"}
    ).sort("created_at", -1).limit(10))
    recent_alerts = [a for a in alerts if (a.get("created_at") or since) >= since]

    print("=" * 68)
    print("CHECK-IN FOOTPRINT (last 3 days)")
    print("=" * 68)
    print(f"  checkins rows (any time): {len(checkins)}  |  in last 3d: {len(recent_checkins)}")
    for c in recent_checkins:
        print(f"      check_in_time={c.get('check_in_time')} status={c.get('status')!r} "
              f"project={c.get('project_id')} cert_cleared={c.get('cert_cleared')}")
    print(f"  CERT_BLOCK alerts (last 3d): {len(recent_alerts)}")
    for a in recent_alerts:
        print(f"      created_at={a.get('created_at')} blocks={[b.get('type') for b in (a.get('blocks') or [])]}")

    # ---- 3. Which path did he hit? (block vs loop, from the DB footprint) ----
    print("=" * 68)
    print("PATH HE HIT (server.py leaves these traces)")
    print("=" * 68)
    if recent_checkins:
        print("  → GOT IN at least once (checkins row exists). Any *later* failed")
        print("    attempts would be blocks/errors on top of a prior success.")
    elif recent_alerts:
        print("  → BLOCKED (red screen): a CERT_BLOCK alert exists but no checkin row.")
        print(f"    Block reason(s): {[b.get('type') for b in (recent_alerts[0].get('blocks') or [])]}")
    else:
        print("  → NO checkin AND NO CERT_BLOCK alert in 3d. He did NOT reach the")
        print("    cert gate cleanly — this is the ERROR/LOOP path (register_and_checkin")
        print("    threw 4xx/5xx: roster-400 / oversized-image-413 / 500), which the")
        print("    old 4s toast hid. (A block would have left an alert above.)")

    # ---- 4. Does the E-fix resolve HIM? (deterministic from his stored fields) ----
    has_cert = any(str(c.get("type", "")).startswith(("OSHA", "SST")) for c in certs)
    num_present = bool(osha_number)
    img_present = bool(osha_card_image)

    print("=" * 68)
    print("E-FIX VERDICT (resolved_kind logic — server.py:1758-1765 / has_osha 1903-1908)")
    print("=" * 68)
    print(f"  OSHA/SST cert on file : {has_cert}")
    print(f"  stored osha_number    : {num_present}")
    print(f"  stored osha_card_image: {img_present}")
    print("  " + "-" * 60)
    if has_cert:
        print("  NOT a MISSING_OSHA case — he already has an OSHA/SST cert on file,")
        print("  so has_osha is True pre- AND post-fix. If he failed, it was the")
        print("  ERROR/LOOP path (see footprint above), not the cert block.")
    elif num_present:
        print("  NOT blocked even PRE-fix — quick check-in already sends his stored")
        print("  osha_number, which resolves to SST (server.py:1762). MISSING_OSHA")
        print("  was not his block; his failure was the ERROR/LOOP path.")
    elif img_present:
        print("  ✅ E-FIX SOLVES HIM (definitive). PRE-fix the quick check-in carried")
        print("  no cert / no number / no image → MISSING_OSHA block. POST-fix the gate")
        print("  falls back to his ON-FILE osha_card_image → resolves SST → cleared.")
    else:
        print("  ❌ E-FIX DOES NOT HELP. No cert, no osha_number, no osha_card_image on")
        print("  file — nothing to fall back to. His real problem is that the card he")
        print("  uploaded today never produced evidence (OCR/crop failure). The fix is")
        print("  the CARD-FRAME capture, not the returning-worker gate.")

    client.close()


if __name__ == "__main__":
    main()
