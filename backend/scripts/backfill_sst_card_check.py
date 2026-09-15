"""THE FIVE NAMED WORKERS ARE NOT FIXED BY SHIPPING THE CARD CHECK, and this
script is what it would take to move them -- written so the decision is in front
of an operator, NOT so it can be run casually.

IT DEFAULTS TO --dry-run AND IT HAS NEVER BEEN RUN AGAINST PRODUCTION.

── WHY A BACKFILL IS EVEN IN QUESTION ───────────────────────────────────────

`POST /checkins/{id}/card-check` only ever fires when a competent person stands
at a gate and presses the control. It is forward-only by construction. Every
worker flagged before it ships stays flagged until a CP happens to see that man
again and press it -- 25 flagged certs in production as of 2026-09-14, among
them the five the defect report names.

── WHY THE OBVIOUS BACKFILL IS REFUSED ──────────────────────────────────────

The obvious move is to read the 43 check-ins carrying `review_decision:
'approved'` and write a `card_check` from each. THIS SCRIPT WILL NOT DO THAT,
and the refusal is the point:

  A card check attests that a HUMAN LOOKED AT A PHYSICAL CARD and that its
  name, number and class match the record. An approval says THIS WORKER MAY
  WORK TODAY. They are different claims, made under different rules, and the
  endpoint's own docstring separates them deliberately.

Synthesising an attestation from an approval would put a named competent
person's id and name against a statement he never made, on a compliance record,
retroactively. That is a fabricated attestation. If it were ever wrong -- if one
of those cards was in fact never examined -- the record would say a specific man
had examined it. No cleared flag is worth that, and an investigator reading the
`checked_by` field would be reading a forgery.

So `--from-approvals` exists, is documented here, and RAISES. It is present to
answer the question "why didn't you just do that", not to be used.

── WHAT THIS SCRIPT DOES INSTEAD ────────────────────────────────────────────

`--report` only. It prints the census an operator needs to decide:

  * which flagged certs a CP could clear today (they hold a card number the
    endpoint would accept), and
  * which ones NO CP action can clear, and why -- so those are routed to a
    re-scan or a data correction instead of sitting in a queue forever.

MEASURED ON PRODUCTION 2026-09-14, the five named workers split like this:

  Angel Lopez        card_number is NULL. The endpoint refuses (400) and
                     `card_check_covers` returns False in both positions. NO
                     CP ACTION CLEARS HIM. His row needs a card number, which
                     is a re-scan or an admin correction.
  Hector Ramirez     card `SST7F6308A7`, ELEVEN characters.
  Dmitri Volkov      card `SST072F2336`, ELEVEN characters.
                     `_CARD_NUMBER_RE` is `^[A-Z0-9]{10}$`, so the moment the
                     card check lowers `needs_review` the register's
                     `card_number_finding` re-flags the row as
                     `CARD_NUMBER_FORMAT`. A CP CAN press the control and the
                     man STAYS ON THE ROSTER under a new reason. Either the
                     card numbers are wrong (a correction) or the ten-character
                     rule is too tight (a product ruling). Not a backfill.
  Jose David Hernandez Pena   card `XCAS2DYB8G`, ten characters.
  WILMER CARRILLO             card `4YU1RY8KKM`, ten characters.
                     THESE TWO, and only these two, are cleared end-to-end by a
                     CP pressing the control. They need no backfill -- they need
                     the CP to see them at the gate once.

AND EVEN FOR THOSE TWO, TWO SURFACES DO NOT MOVE:
  * `frontend/app/workers/[id].jsx` filters `needs_review || review_reason`,
    and `review_reason` survives the card check by design, so "Credential needs
    review" keeps painting on the worker screen.
  * The filed OSHA register's "UNVERIFIED - card could not be read" comes from
    `unverified: c.sst_status === 'unknown'`, frozen onto the check-in row at
    gate time. Already-filed documents are never rewritten, and `sst_status`
    would not move for these rows anyway: `card_check_covers` is wired only to
    the `class_source in ("color_only", "conflict")` demotion, and
    `class_source` is null on all 25 flagged certs.

So the honest summary for the operator: SHIPPING THIS CLEARS NOBODY BY ITSELF.
It gives the CP the control the design always assumed existed. Two of the five
named workers clear once he uses it; three need a data correction first; and no
already-filed PDF changes for any of them.
"""

import argparse
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

RECOGNIZED_SST_PREFIX = "SST"
CARD_NUMBER_LEN = 10


def _classify(cert):
    """Why this flagged cert can or cannot be cleared by a CP card check."""
    number = str(cert.get("card_number") or "").strip()
    if not number:
        return "no_card_number__needs_rescan_or_correction"
    if not (len(number) == CARD_NUMBER_LEN and number.isalnum()
            and number.upper() == number and any(c.isdigit() for c in number)):
        return "card_number_fails_format_rule__will_re_flag"
    return "clearable_by_a_cp_card_check"


async def report():
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "blueview")]

    buckets = Counter()
    rows = []
    async for w in db.workers.find({"certifications.needs_review": True,
                                    "is_deleted": {"$ne": True}}):
        for cert in (w.get("certifications") or []):
            if not (isinstance(cert, dict) and cert.get("needs_review")):
                continue
            if not str(cert.get("type") or "").startswith(RECOGNIZED_SST_PREFIX):
                continue
            verdict = _classify(cert)
            buckets[verdict] += 1
            rows.append((w.get("name"), cert.get("card_number"),
                         cert.get("review_reason"), verdict))

    print(f"flagged SST certs: {sum(buckets.values())}")
    for k, n in buckets.most_common():
        print(f"  {n:>3}  {k}")
    print()
    for name, number, reason, verdict in sorted(rows, key=lambda r: str(r[0])):
        print(f"  {str(name)[:32]:<32} {str(number):<14} {str(reason):<20} {verdict}")

    print("\nNOTHING WAS WRITTEN. This command only reads.")


def from_approvals():
    raise SystemExit(
        "REFUSED. Writing a `card_check` from a `review_decision` would put a "
        "named competent person's id against an attestation he never made, on "
        "a compliance record, retroactively. An approval says the worker may "
        "work today; a card check says a human examined the physical card. "
        "Read the module docstring: the two flagged workers who can be cleared "
        "need the CP to press the control once, and the other three need a "
        "data correction, not a synthesised attestation."
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true",
                    help="read-only census of every flagged SST cert")
    ap.add_argument("--from-approvals", action="store_true",
                    help="documented and REFUSED -- see the module docstring")
    args = ap.parse_args()

    if args.from_approvals:
        from_approvals()
    if args.report:
        asyncio.run(report())
        return
    ap.print_help()


if __name__ == "__main__":
    main()
