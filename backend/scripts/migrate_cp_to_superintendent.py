"""PROMOTE ONE `cp` ACCOUNT TO `superintendent`. Audited, guarded, one document.

── THE CASE IT WAS WRITTEN FOR ─────────────────────────────────────────────

Michael Cespedes, 6a68b16ebe9c27dedf5cf47f, michaelcespedes99@gmail.com. He
holds `role: cp` and he is the ONLY row in `cs_registrations` on the whole
platform, on 588 Thomas (6a5f63bc147407d3261df2c7). He files the construction
superintendent's log today, as a CP, because that is the account he was given
before the role existed.

Production, measured 2026-09-16: admin 4, owner 3, cp 3, superintendent 0. This
script makes the fourth number 1.

── THE THING THAT MUST NOT BREAK, AND WHY IT CANNOT ────────────────────────

HIS RIGHT TO FILE DOES NOT COME FROM HIS ROLE, so changing his role cannot take
it away. `lib/logbook/superintendent_log.py` states the rule and the reason:
the access gate keys on the CS REGISTRATION, never on `role`, because a
`role == "superintendent"` gate would have locked out exactly this man --
the dual-capacity user who is both the registered CS and the competent person
on his own job.

That is an argument, and an argument is not a test. backend/tests/
test_the_superintendent_migration_does_not_move_his_filing_right.py drives
`cs_filing_refused` with his registration and BOTH roles and asserts the answer
is identical. Read it before running this.

── WHAT ACTUALLY MOVES ─────────────────────────────────────────────────────

    role: "cp"  ->  "superintendent"

and nothing else. In particular:

  * `assigned_projects` IS UNTOUCHED. `ROLES_SCOPED_TO_ASSIGNED_PROJECTS`
    already holds both roles, so the restriction he is under does not change.
  * `company_id` IS UNTOUCHED, and is a PRECONDITION. Both roles are in
    `ROLES_REQUIRING_COMPANY`; a superintendent with no company 403s on every
    company-gated endpoint and his session merely looks broken. This refuses
    rather than creating that account.
  * `cs_registrations` IS UNTOUCHED. It is the filing gate. A script that
    "helpfully" wrote a registration would be inventing the very fact the gate
    exists to record.

── WHAT HE GAINS, AND IT IS NOT THE LOG ────────────────────────────────────

He can already see and file the superintendent's log. What the role gives him
is the licence fields on his own account -- DOB registration number, expiry,
card photograph -- and the 30-day expiry warning that reads them. Those are
BLANK after this runs: nobody has typed his registration number in yet, and
`superintendent_licence_state` returns "unknown" rather than "ok" for exactly
that reason. Filling them is an admin's job on the User Management screen, not
this script's -- a licence number invented by a migration is a false statement
about a credential.

── EMAIL, AND THIS IS THE ONE THING TO CHECK BEFORE RUNNING ────────────────

The ruling is that a CP and a superintendent receive NO EMAIL OF ANY KIND. The
send-time filter that implements it lives in backend/lib/notifications.py and
is owned by a separate change. IF THAT FILTER HAS NOT LANDED, check what the
recipient queries select for `superintendent` before running this: a role
change is also a change to who is on a mailing list.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prod_guard import (  # noqa: E402
    add_guard_args, check_guard, report_dry_run, script_audit,
)

NAME = "migrate_cp_to_superintendent"

#: The account this was written for. A DEFAULT AND NOT A HARD-CODING: the next
#: superintendent to be promoted is a different id and the same operation, and a
#: script that only works once gets copied rather than re-run.
MICHAEL = "6a68b16ebe9c27dedf5cf47f"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--user", default=MICHAEL,
                    help=f"user id to promote (default {MICHAEL}, Michael Cespedes)")
    add_guard_args(ap)
    args = ap.parse_args()

    import server  # noqa: E402  -- the SAME role vocabulary the app uses

    db = server.db
    user = await db.users.find_one({"_id": server.to_query_id(args.user)})
    if not user:
        print(f"user {args.user} not found")
        return 1

    name = user.get("name") or user.get("full_name") or user.get("email") or "?"
    role = str(user.get("role") or "").strip().lower()
    company_id = user.get("company_id")
    print(f"user    : {name!r}  <{user.get('email')}>  [{args.user}]")
    print(f"role    : {role!r} -> {server.ROLE_SUPERINTENDENT!r}")
    print(f"company : {company_id!r}")
    print(f"assigned: {user.get('assigned_projects') or []}")

    # ── THE REFUSALS ────────────────────────────────────────────────────────
    #
    # Each one is a state in which applying the change would leave a WORSE
    # account than not applying it, so each stops rather than warning.
    if role == server.ROLE_SUPERINTENDENT:
        print("\nAlready a superintendent. Nothing to do.")
        return 0
    if role != "cp":
        print(f"\nSTOPPING. This promotes a `cp`, and this account is {role!r}.\n"
              "  Promoting an admin or an owner would REMOVE powers, which is a\n"
              "  different operation and needs its own ruling.")
        return 3
    if not company_id:
        print("\nSTOPPING. The account has no company_id.\n"
              "  `superintendent` is in ROLES_REQUIRING_COMPANY: every\n"
              "  company-gated endpoint would 403 and his session would merely\n"
              "  look broken. Assign the company first.")
        return 3
    if user.get("is_deleted"):
        print("\nSTOPPING. The account is soft-deleted.")
        return 3

    # ── THE FILING RIGHT, READ OUT LOUD BEFORE AND AFTER ────────────────────
    #
    # NOT A PRECONDITION -- a superintendent who has not been registered on a
    # project yet is a perfectly ordinary state, and refusing here would make
    # the role unusable until an admin did the two steps in one order. It is
    # PRINTED because "he must still be able to file" is the operator's whole
    # question about this migration, and the answer belongs in the run's output
    # rather than in a paragraph somebody has to trust.
    regs = await db.cs_registrations.find({
        "is_deleted": {"$ne": True},
        "$or": [{"user_id": str(args.user)}, {"user_id": args.user}],
    }).to_list(50)
    print(f"\ncs_registrations naming this user: {len(regs)}")
    for r in regs:
        print(f"   project={r.get('project_id')!r} licence={r.get('license_number')!r} "
              f"active={r.get('is_active')!r}")
    if not regs:
        print("   none — his filing right, if any, is matched by LICENCE rather\n"
              "   than by account id. cs_attribution answers that; this script\n"
              "   does not, and does not change it either way.")

    print("\nThe filing gate reads cs_registrations, NOT `role`\n"
          "  (lib/logbook/superintendent_log.py). This change cannot move it.")

    if not check_guard(args):
        report_dry_run(
            f"set users[{args.user}].role = {server.ROLE_SUPERINTENDENT!r} "
            f"(was {role!r}); nothing else")
        return 0

    now = server.datetime.now(server.timezone.utc)
    res = await db.users.update_one(
        # THE OLD ROLE IS IN THE FILTER. Two sessions running this, or a rerun
        # after an admin already changed the role by hand, must not produce two
        # audit rows claiming to have made the same change. matched_count == 0
        # then says "it was not what I read", which is the truth.
        {"_id": server.to_query_id(args.user), "role": role},
        {"$set": {"role": server.ROLE_SUPERINTENDENT, "updated_at": now}},
    )
    print(f"\nmatched={res.matched_count} modified={res.modified_count}")
    if res.matched_count == 0:
        print("  The role was not what it was when this script read it. "
              "Nothing was written.")
        return 4

    await script_audit(
        db, "user_role_promoted", "user", args.user,
        {
            "name": name,
            "email": user.get("email"),
            "old": {"role": role},
            "new": {"role": server.ROLE_SUPERINTENDENT},
            "company_id": company_id,
            "assigned_projects": user.get("assigned_projects") or [],
            "cs_registrations": [str(r.get("project_id")) for r in regs],
        },
        args, name=NAME,
    )
    print(f"audit row written, actor script:{NAME}")

    after = await db.users.find_one({"_id": server.to_query_id(args.user)})
    print("\nread back:", {k: after.get(k) for k in
                           ("role", "company_id", "assigned_projects",
                            *server.SUPERINTENDENT_LICENCE_FIELDS)})
    print("\nHis licence fields are blank and that is correct: nobody has typed\n"
          "his DOB registration number in yet. superintendent_licence_state\n"
          "reads 'unknown', not 'ok'. Fill them on the User Management screen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
