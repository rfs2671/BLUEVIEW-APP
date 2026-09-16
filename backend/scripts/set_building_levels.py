"""SET A PROJECT'S BUILDING LEVELS. Audited, guarded, one document.

── THE CASE IT WAS WRITTEN FOR ─────────────────────────────────────────────

588 Thomas S Boyland Street, confirmed by the operator from its own indexed
sheets: four storeys, a mezzanine, a roof and a bulkhead, no cellar.

    1st Floor    A-100.00 / A-100.01   FIRST FLOOR PLAN
    2nd Floor    A-101.00              SECOND FLOOR PLAN
    3rd Floor    A-102.00              THIRD FLOOR PLAN
    4th Floor    A-103.00              FOURTH FLOOR PLAN
    Mezzanine    A-104.00              MEZZANINE PLAN
    Roof         A-105.00 / A-105.01   ROOF AND BULKHEAD PLAN
    Bulkhead     A-105.01, M-106.00, P-207.00

Foundation and Bulkhead are not stored fields: Foundation is a default chip and
Bulkhead rides `has_roof_bulkhead`, because a bulkhead without a roof is not a
building.

── IT RE-CLASSIFIES THE SAME WAY THE APP DOES, AND REFUSES IF THAT MOVES ───

`building_stories` is a §3310 input. `update_project` recomputes
`suggested_class`, `project_class`, `classification_source` and
`required_logbooks` whenever it changes; a script writing the field straight
into Mongo would leave all four stale, which is the "two models" defect this
codebase keeps closing.

So this calls the SAME `classify_project` and `get_required_logbooks` the
server does. And if the recomputed class differs from the stored one it STOPS
AND REPORTS rather than applying: on a live project that means adding or
REMOVING required daily logs, and no script gets to do that on its own. The
operator said to expect no change; this is what makes "expect" checkable.

── THE STORED CLASS IS AN OVERRIDE ON EVERY LIVE PROJECT ───────────────────

`classification_source` is None on all five, because the create form sends
`project_class` on every create and the server treats any client-supplied class
as an admin override. 8 Walworth is `major_b` with null storeys, null height
and null footprint. That is why this refuses rather than trusting the
recomputation: the stored answer is a person's, not a measurement's.
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

NAME = "set_building_levels"

FLAGS = ("has_sub_cellar", "has_cellar", "has_mezzanine", "has_roof_bulkhead")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--stories", type=int, default=None)
    for f in FLAGS:
        ap.add_argument(f"--{f.replace('_', '-')}",
                        choices=("true", "false"), default=None, dest=f)
    add_guard_args(ap)
    args = ap.parse_args()

    import server  # noqa: E402  -- the SAME classifier the app uses

    db = server.db
    project = await db.projects.find_one(
        {"_id": server.to_query_id(args.project)})
    if not project:
        print(f"project {args.project} not found")
        return 1

    patch = {}
    if args.stories is not None:
        patch["building_stories"] = args.stories
    for f in FLAGS:
        v = getattr(args, f)
        if v is not None:
            patch[f] = (v == "true")
    if not patch:
        print("nothing to set")
        return 1

    print(f"project : {project.get('name')!r}  [{args.project}]")
    print("before  :", {k: project.get(k) for k in
                        ("building_stories", *FLAGS)})
    print("after   :", {k: patch.get(k, project.get(k)) for k in
                        ("building_stories", *FLAGS)})

    merged = {**project, **patch}
    suggested = server.classify_project(
        merged.get("building_stories"),
        merged.get("footprint_sqft"),
        merged.get("has_full_demolition", False),
        merged.get("demolition_stories"),
        merged.get("building_height"),
    )
    stored = project.get("project_class")
    print(f"\n§3310  : stored={stored!r}  recomputed={suggested!r}")

    if suggested != stored:
        print(
            "\nSTOPPING. The recomputed class differs from the stored one.\n"
            "  On a live project that adds or REMOVES required daily logs "
            "(ssc_daily_safety_log,\n  concrete_operations are the only "
            "class-restricted types). A script does not make\n  that call. "
            "Report it and get a ruling."
        )
        return 3

    required_before = list(project.get("required_logbooks") or [])
    required_after = server.get_required_logbooks(stored, merged)
    print(f"required logbooks: {len(required_before)} -> {len(required_after)}")
    if set(required_before) != set(required_after):
        print(f"   added  : {sorted(set(required_after) - set(required_before))}")
        print(f"   removed: {sorted(set(required_before) - set(required_after))}")

    if not check_guard(args):
        report_dry_run(f"apply {patch} to project {args.project}")
        return 0

    # `suggested_class` and `required_logbooks` ride along because the app
    # writes them on this same field change. Leaving them stale is how a second
    # model appears. `project_class` is NOT touched: it is unchanged by
    # definition -- the branch above returned otherwise.
    write = dict(patch)
    write["suggested_class"] = suggested
    write["required_logbooks"] = required_after
    write["updated_at"] = server.datetime.now(server.timezone.utc)

    res = await db.projects.update_one(
        {"_id": server.to_query_id(args.project)}, {"$set": write})
    print(f"\nmatched={res.matched_count} modified={res.modified_count}")

    await script_audit(
        db, "project_levels_set", "project", args.project,
        {
            "name": project.get("name"),
            "old": {k: project.get(k) for k in ("building_stories", *FLAGS)},
            "new": {k: write.get(k, project.get(k))
                    for k in ("building_stories", *FLAGS)},
            "project_class": stored,
            "suggested_class": suggested,
            "required_logbooks_before": required_before,
            "required_logbooks_after": required_after,
        },
        args, name=NAME,
    )
    print(f"audit row written, actor script:{NAME}")

    after = await db.projects.find_one(
        {"_id": server.to_query_id(args.project)})
    print("\nread back:", {k: after.get(k) for k in
                           ("building_stories", *FLAGS, "project_class",
                            "suggested_class")})
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
