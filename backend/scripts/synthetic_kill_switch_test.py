import asyncio
import os
import sys
from datetime import datetime, timezone

CUSTOMER_DOMAIN_BLOCKLIST = {
    "blueviewbuilders.com",
    "blueview.com",
}

async def main():
    # 1. Defense-in-depth: kill switch must be on in our process too.
    raw = (os.environ.get("NOTIFICATIONS_KILL_SWITCH") or "").strip().lower()
    if raw not in ("1", "true", "yes", "on"):
        print("ABORT: NOTIFICATIONS_KILL_SWITCH is not on in this process.")
        print("Set NOTIFICATIONS_KILL_SWITCH=1 in your shell before running.")
        sys.exit(2)

    # 2. Operator email is required + must not be a customer domain.
    operator_email = (os.environ.get("OPERATOR_EMAIL") or "").strip().lower()
    if not operator_email or "@" not in operator_email:
        print("ABORT: set OPERATOR_EMAIL to your own address (no @ in input).")
        sys.exit(2)
    domain = operator_email.split("@", 1)[1]
    if domain in CUSTOMER_DOMAIN_BLOCKLIST:
        print(f"ABORT: {operator_email} is on the customer-domain blocklist.")
        sys.exit(2)

    # 3. Mongo handle.
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ABORT: MONGO_URL and DB_NAME required.")
        sys.exit(2)
    db = AsyncIOMotorClient(mongo_url)[db_name]

    # 4. Cross-check: the operator email must match a real user record
    #    on the production cluster. Belt-and-suspenders against typos.
    user = await db.users.find_one({"email": operator_email})
    if not user:
        print(f"ABORT: no user with email={operator_email!r} in production users collection.")
        sys.exit(2)
    if user.get("role") not in ("admin", "owner"):
        print(f"ABORT: user {operator_email} role={user.get('role')!r}; expected admin or owner.")
        sys.exit(2)

    # 5. Baseline count.
    before = await db.notification_log.count_documents({})
    print(f"notification_log count BEFORE: {before}")

    # 6. Synthetic send.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
    from lib.notifications import send_notification

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result = await send_notification(
        db,
        permit_renewal_id=f"synthetic_test_{ts}",
        trigger_type="annotation_note",
        recipient=operator_email,
        subject="MR.9 consolidation test - DO NOT REPLY",
        html="<p>Synthetic kill-switch test. If you received this, the kill switch FAILED.</p>",
        text="Synthetic kill-switch test. If you received this, the kill switch FAILED.",
        metadata={"synthetic_test": True, "test_run_at": ts},
    )
    print(f"send_notification returned status={result.get('status')!r}")

    # 7. Read back the row.
    after = await db.notification_log.count_documents({})
    print(f"notification_log count AFTER:  {after}")
    latest = await db.notification_log.find_one(
        {}, sort=[("sent_at", -1)],
    )
    if latest:
        print("Most recent notification_log row:")
        for k in ("sent_at", "trigger_type", "recipient", "status",
                  "permit_renewal_id", "subject"):
            print(f"  {k}: {latest.get(k)!r}")
    else:
        print("WARNING: no row found after send (insert may have failed).")

    # 8. Verdict.
    expected = "suppressed_kill_switch"
    actual = (latest or {}).get("status")
    if actual == expected:
        print(f"\n✓ PASS — status={expected} as expected. Kill switch halted at Step 0.")
        print("  MR.9 consolidation verified: send_notification ran, kill switch fired,")
        print("  notification_log captured the audit row, no Resend call was made.")
    else:
        print(f"\n✗ UNEXPECTED — status={actual!r} (expected {expected!r}).")
        print("  Investigate before removing the kill switch.")

if __name__ == "__main__":
    asyncio.run(main())