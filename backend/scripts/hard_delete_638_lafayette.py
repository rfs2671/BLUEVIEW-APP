"""HARD DELETE: 638 Lafayette Avenue (closed project) and its orphan company.

    # 1. Dry run (default). Prints what would go, per collection, plus R2.
    railway run python -m scripts.hard_delete_638_lafayette

    # 2. Execute. The two project ids must be typed out, exactly.
    railway run python -m scripts.hard_delete_638_lafayette --execute \\
        --project 69e16adf079abf2b78ee08d4 --project 69f8fb5e9429c5be4b2fcb66 \\
        --i-know --reason "638 Lafayette closed, operator hard delete" \\
        --session <id>

── WHAT THIS DELETES, AND IT IS A HARD DELETE ─────────────────────────────────

  projects      69e16adf079abf2b78ee08d4 (company 69e16add079abf2b78ee08ce)
                69f8fb5e9429c5be4b2fcb66 (no company_id)
  whatsapp_groups 69e1bee42bfc871b5d3db427 (wa_group_id
                120363424969499174@g.us) — the bot LEAVES the group first
  every row, in EVERY collection, whose project_id is one of those projects or
  whose company_id is 69e16add079abf2b78ee08ce; plus the rows keyed some other
  way (file_id, logbook_id, group_id, permit_renewal_id, system_config keys)
  that the app's own hard delete misses; plus every R2 object those rows name.

  KEPT: audit_logs. It is the compliance trail, and this script adds to it.

── WHY IT BYPASSES THE APP'S BRAKES, SAID OUT LOUD ────────────────────────────

`DELETE /projects/{id}/hard-delete` refuses a project with filed logbooks or
signature events, and `retention_refusal` refuses a completed project until
completion + 7 years. This script does not consult either. The dry run PRINTS
both counts so the operator sees exactly what record is being destroyed; the
execute path records them in the audit row.

── REFUSALS (nothing is written) ─────────────────────────────────────────────

  * --execute without both project ids, or with any other id
  * the company has a `companies` document (the premise is that it has none)
  * the company owns a project other than the two targets
  * the WhatsApp group is bound to any project or company other than these
  * a target project's company_id is not what this docstring says
  * the bot cannot leave the group (use --bot-not-in-group only if you have
    checked it is not a member)
  * any R2 delete fails — rows are kept so the run can be repeated

Exit codes: 0 ok, 2 bad invocation / env, 3 refused, 4 failed (post-check).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.prod_guard import (  # noqa: E402
    add_guard_args, audited, check_guard, refuse_legacy_flag, script_audit_sync,
    script_name,
)

OK, BAD, REFUSED, FAILED = 0, 2, 3, 4

TARGET_PROJECTS = ("69e16adf079abf2b78ee08d4", "69f8fb5e9429c5be4b2fcb66")
TARGET_COMPANY = "69e16add079abf2b78ee08ce"
EXPECTED_PROJECT_COMPANY = {
    "69e16adf079abf2b78ee08d4": TARGET_COMPANY,
    "69f8fb5e9429c5be4b2fcb66": None,
}
TARGET_GROUP_DOC = "69e1bee42bfc871b5d3db427"
TARGET_WA_GROUP = "120363424969499174@g.us"

KEEP_COLLECTIONS = frozenset({"audit_logs", "system.views", "system.profile"})


# ── pure helpers (tested in tests/test_hard_delete_638_lafayette.py) ────────

def id_values(raw: str) -> List[Any]:
    """An id as it may be stored: the string, and the ObjectId when valid."""
    out: List[Any] = [str(raw)]
    try:
        from bson import ObjectId
        out.append(ObjectId(str(raw)))
    except Exception:
        pass
    return out


def any_id(field: str, ids: Iterable[str]) -> Dict[str, Any]:
    vals: List[Any] = []
    for i in ids:
        vals.extend(id_values(i))
    return {field: {"$in": vals}}


def validate_execute_args(execute: bool, projects: List[str]) -> Optional[str]:
    """None when the invocation is acceptable, else why not."""
    if not execute:
        return None
    given = sorted(set(projects or []))
    if given != sorted(TARGET_PROJECTS):
        return ("--execute requires exactly --project "
                + " --project ".join(TARGET_PROJECTS) + f" (got {given})")
    return None


def collect_r2_keys(doc: Any, out: Set[str], depth: int = 0) -> None:
    """Every string stored under a key ending in `r2_key`, anywhere in a doc."""
    if depth > 12:
        return
    if isinstance(doc, dict):
        for k, v in doc.items():
            if isinstance(v, str) and str(k).endswith("r2_key") and v.strip():
                out.add(v.strip())
            else:
                collect_r2_keys(v, out, depth + 1)
    elif isinstance(doc, list):
        for v in doc:
            collect_r2_keys(v, out, depth + 1)


def system_config_filter(project_ids: Iterable[str]) -> Dict[str, Any]:
    ors: List[Dict[str, Any]] = []
    for pid in project_ids:
        rx = re.escape(pid)
        ors += [{"key": f"dob_sync_last:{pid}"},
                {"key": {"$regex": f"^initial_scan_done:.*:{rx}$"}},
                {"key": {"$regex": f"^dob_alert_sent:{rx}:"}},
                {"key": {"$regex": f"^daily_report:{rx}:"}}]
    return {"$or": ors}


def build_selectors(*, project_ids, company_id, file_ids, logbook_ids,
                    renewal_ids, wa_group, group_doc_id,
                    collection_names) -> List[Tuple[str, Dict[str, Any], str]]:
    """(collection, filter, why) for every delete. A collection may appear
    more than once; deletes are idempotent."""
    pids = list(project_ids)
    sel: List[Tuple[str, Dict[str, Any], str]] = []
    generic = {"$or": [any_id("project_id", pids),
                       any_id("company_id", [company_id])]}
    for name in sorted(collection_names):
        if name in KEEP_COLLECTIONS or name.startswith("system."):
            continue
        sel.append((name, generic, "project_id or company_id"))
    sel.append(("projects", any_id("_id", pids), "the target projects"))
    sel.append(("companies", any_id("_id", [company_id]), "company (expected 0)"))
    if file_ids:
        for c in ("document_page_index", "document_page_chunks", "plan_records"):
            sel.append((c, any_id("file_id", file_ids), "by file_id"))
        sel.append(("plan_index_jobs", any_id("_id", file_ids), "_id = file_id"))
    if logbook_ids:
        for c in ("logbook_thumbnails", "logbook_share_tokens", "logbook_share_reads"):
            sel.append((c, any_id("logbook_id", logbook_ids), "by logbook_id"))
    sel.append(("report_number_counters", any_id("_id", pids), "_id = project id"))
    sel.append(("system_config", system_config_filter(pids), "per-project keys"))
    for c in ("whatsapp_messages", "whatsapp_send_log",
              "whatsapp_conversation_state", "whatsapp_link_codes",
              "whatsapp_voice_events"):
        sel.append((c, {"group_id": wa_group}, "by group_id"))
    sel.append(("whatsapp_pending_groups", {"group_id": wa_group}, "by group_id"))
    sel.append(("whatsapp_groups", {"$or": [any_id("_id", [group_doc_id]),
                                            {"wa_group_id": wa_group}]},
                "the group binding"))
    meta = any_id("metadata.project_id", pids)
    sel.append(("notification_log", {"$or": [
        meta, {"permit_renewal_id": {"$in": [f"project:{p}" for p in pids]
                                     + list(renewal_ids)}}]}, "metadata / renewal"))
    sel.append(("digest_queue", meta, "metadata.project_id"))
    if renewal_ids:
        sel.append(("filing_jobs", {"permit_renewal_id": {"$in": list(renewal_ids)}},
                    "by permit_renewal_id"))
    return sel


# ── the run ────────────────────────────────────────────────────────────────

def _count(db, coll, flt) -> int:
    try:
        return db[coll].count_documents(flt)
    except Exception as e:
        print(f"  !! count failed on {coll}: {type(e).__name__}")
        return -1


def _preflight(db) -> Tuple[Optional[str], Dict[str, Any]]:
    """Facts, and a refusal reason when the premises do not hold."""
    facts: Dict[str, Any] = {}
    pids = list(TARGET_PROJECTS)
    projects = list(db.projects.find(any_id("_id", pids)))
    facts["projects"] = [{k: (str(v) if k in ("_id", "company_id") else v)
                          for k, v in p.items()
                          if k in ("_id", "name", "address", "company_id",
                                   "job_completion_date", "completion_source",
                                   "legal_hold", "marked_for_deletion",
                                   "is_deleted")} for p in projects]
    for p in projects:
        want = EXPECTED_PROJECT_COMPANY[str(p["_id"])]
        have = str(p.get("company_id") or "") or None
        if have != want:
            return (f"project {p['_id']} has company_id {have!r}, expected "
                    f"{want!r}"), facts
    if db.companies.count_documents(any_id("_id", [TARGET_COMPANY])):
        return (f"company {TARGET_COMPANY} HAS a companies document; this "
                "script assumes it does not"), facts
    others = [str(p["_id"]) for p in db.projects.find(
        {**any_id("company_id", [TARGET_COMPANY]),
         "_id": {"$nin": [v for i in pids for v in id_values(i)]}}, {"_id": 1})]
    facts["other_projects_of_company"] = others
    if others:
        return (f"company {TARGET_COMPANY} owns other projects {others}; "
                "refusing to delete them by company_id"), facts
    stray_groups = [
        {"_id": str(g.get("_id")), "company_id": g.get("company_id"),
         "project_id": g.get("project_id")}
        for g in db.whatsapp_groups.find({"wa_group_id": TARGET_WA_GROUP})
        if str(g.get("project_id") or "") not in pids
        or str(g.get("company_id") or "") not in ("", TARGET_COMPANY)]
    facts["group_rows_elsewhere"] = stray_groups
    if stray_groups:
        return (f"{TARGET_WA_GROUP} is bound elsewhere too: {stray_groups}"), facts
    facts["filed_logbooks"] = db.logbooks.count_documents({
        **any_id("project_id", pids),
        "$or": [{"status": "submitted"}, {"is_locked": True}]})
    facts["signature_events"] = db.signature_events.count_documents(
        any_id("project_id", pids))
    facts["audit_logs_kept"] = db.audit_logs.count_documents({"$or": [
        any_id("resource_id", pids), any_id("details.project_id", pids)]})
    return None, facts


def _related_ids(db) -> Tuple[List[str], List[str], List[str]]:
    pids = list(TARGET_PROJECTS)
    file_ids = [str(f["_id"]) for f in db.project_files.find(
        any_id("project_id", pids), {"_id": 1})]
    logbook_ids = [str(lb["_id"]) for lb in db.logbooks.find(
        any_id("project_id", pids), {"_id": 1})]
    renewal_ids = [str(r["_id"]) for r in db.permit_renewals.find(
        any_id("project_id", pids), {"_id": 1})]
    return file_ids, logbook_ids, renewal_ids


def _r2_inventory(db, selectors) -> Set[str]:
    keys: Set[str] = set()
    for coll, flt, _ in selectors:
        try:
            for doc in db[coll].find(flt):
                collect_r2_keys(doc, keys)
        except Exception:
            pass
    return keys


def _r2_listing(prefixes: List[str]) -> Dict[str, List[str]]:
    """What a prefix LISTING returns. In this deployment R2_ENDPOINT_URL ends
    in the bucket name, and server._r2_delete_prefix documents that a listing
    returns the bucket's CORS document instead of keys — so this is printed
    for completeness and the DELETE uses the keys the rows name."""
    out: Dict[str, List[str]] = {}
    try:
        import server
        client = server._get_r2_client()
        bucket = server.R2_BUCKET_NAME
    except Exception as e:
        return {"(r2 unavailable)": [type(e).__name__]}
    if not client or not bucket:
        return {"(r2 not configured)": []}
    for prefix in prefixes:
        try:
            resp = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1000)
            out[prefix] = [o.get("Key") for o in resp.get("Contents", []) or []]
        except Exception as e:
            out[prefix] = [f"(list failed: {type(e).__name__})"]
    return out


def _r2_delete(keys: Set[str]) -> List[str]:
    """Delete by explicit key. Returns the keys that failed."""
    import server
    client = server._get_r2_client()
    main_bucket = server.R2_BUCKET_NAME
    card_bucket = (os.environ.get("CARD_AUDIT_BUCKET_NAME", "").strip()
                   or main_bucket)
    if not client or not main_bucket:
        return sorted(keys)
    by_bucket: Dict[str, List[str]] = {}
    for k in sorted(keys):
        bucket = card_bucket if k.startswith("card-audit/") else main_bucket
        by_bucket.setdefault(bucket, []).append(k)
    failed: List[str] = []
    for bucket, ks in by_bucket.items():
        for i in range(0, len(ks), 1000):
            chunk = ks[i:i + 1000]
            try:
                resp = client.delete_objects(Bucket=bucket, Delete={
                    "Objects": [{"Key": k} for k in chunk], "Quiet": True})
                failed += [e.get("Key") for e in resp.get("Errors", []) or []]
            except Exception:
                failed += chunk
    return failed


def _leave_group(action: str) -> Tuple[bool, str]:
    base = os.environ.get("WAAPI_BASE_URL", "https://waapi.app/api/v1")
    inst = os.environ.get("WAAPI_INSTANCE_ID", "")
    token = os.environ.get("WAAPI_TOKEN", "")
    if not (inst and token):
        return False, "WAAPI_INSTANCE_ID / WAAPI_TOKEN not set"
    req = urllib.request.Request(
        f"{base}/instances/{inst}/client/action/{action}",
        data=json.dumps({"chatId": TARGET_WA_GROUP}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read(2000).decode("utf-8", "replace")
            return 200 <= resp.status < 300, f"http {resp.status} {body[:200]}"
    except urllib.error.HTTPError as e:
        return False, f"http {e.code}"
    except Exception as e:
        return False, type(e).__name__


def run(db, write: bool, args) -> int:
    # One handle. Through audited() every write below records an audit row
    # (without --i-know it is the bare handle and nothing writes anyway).
    raw_db = db
    print(f"Targets: projects {', '.join(TARGET_PROJECTS)}; company "
          f"{TARGET_COMPANY}; group {TARGET_GROUP_DOC} ({TARGET_WA_GROUP})\n")
    refusal, facts = _preflight(raw_db)
    print(json.dumps(facts, indent=2, default=str))
    if refusal:
        print(f"\nREFUSED: {refusal}")
        return REFUSED
    if facts.get("filed_logbooks") or facts.get("signature_events"):
        print(f"\n!! The app's hard delete would REFUSE this: "
              f"{facts['filed_logbooks']} filed/locked logbooks, "
              f"{facts['signature_events']} signature events. This script "
              f"deletes them anyway; the audit row records the counts.")

    file_ids, logbook_ids, renewal_ids = _related_ids(raw_db)
    names = raw_db.list_collection_names()
    selectors = build_selectors(
        project_ids=TARGET_PROJECTS, company_id=TARGET_COMPANY,
        file_ids=file_ids, logbook_ids=logbook_ids, renewal_ids=renewal_ids,
        wa_group=TARGET_WA_GROUP, group_doc_id=TARGET_GROUP_DOC,
        collection_names=names)

    try:
        import server
        owned = set(server._PROJECT_OWNED_COLLECTIONS)
    except Exception:
        owned = set()
    print("\nWould delete (collection: count — why):")
    totals: Dict[str, int] = {}
    for coll, flt, why in selectors:
        n = _count(raw_db, coll, flt)
        if n:
            note = "" if coll in owned or why != "project_id or company_id" \
                else "   <- not in _PROJECT_OWNED_COLLECTIONS"
            print(f"  {coll:34s} {n:6d}  {why}{note}")
            totals[coll] = totals.get(coll, 0) + n
    pull_users = _count(raw_db, "users", any_id("assigned_projects", TARGET_PROJECTS))
    pull_workers = _count(raw_db, "workers",
                          any_id("safety_orientations.project_id", TARGET_PROJECTS))
    print(f"  users.assigned_projects  $pull on {pull_users} user(s)")
    print(f"  workers.safety_orientations  $pull on {pull_workers} worker(s)")

    keys = _r2_inventory(raw_db, selectors)
    print(f"\nR2 objects named by those rows: {len(keys)}")
    for k in sorted(keys)[:200]:
        print(f"  {k}")
    if len(keys) > 200:
        print(f"  ... and {len(keys) - 200} more")
    prefixes = []
    for pid in TARGET_PROJECTS:
        prefixes += [f"{TARGET_COMPANY}/{pid}/", f"plans/{pid}/",
                     f"logbook-photos/{pid}/", f"card-audit/{pid}/"]
    print("\nR2 prefix listing (informational; see _r2_listing):")
    for prefix, found in _r2_listing(prefixes).items():
        print(f"  {prefix}: {len(found)}")

    if not write:
        print("\nDRY RUN — nothing was written. Re-run with --execute, both "
              "--project ids, --i-know --reason --session.")
        return OK

    # 1. The bot leaves the group BEFORE its binding row goes, so the next
    #    message cannot re-create a pending row and greet the chat.
    if args.bot_not_in_group:
        print("\nSkipping WhatsApp leave (--bot-not-in-group).")
    else:
        ok, detail = _leave_group(args.waapi_leave_action)
        print(f"\nWhatsApp leave {TARGET_WA_GROUP}: {'ok' if ok else 'FAILED'} "
              f"({detail})")
        if not ok:
            print("REFUSED: the bot did not leave the group; nothing deleted.")
            return REFUSED

    # 2. R2 first, while the rows that name the keys still exist.
    failed = _r2_delete(keys)
    if failed:
        print(f"FAILED: {len(failed)} R2 deletes failed; rows kept so this "
              f"can be re-run. First: {failed[:5]}")
        return FAILED

    # 3. Rows, through the audited handle.
    for coll, flt, _ in selectors:
        db[coll].delete_many(flt)
    db.users.update_many(any_id("assigned_projects", TARGET_PROJECTS),
                         {"$pull": {"assigned_projects": {
                             "$in": [v for p in TARGET_PROJECTS
                                     for v in id_values(p)]}}})
    db.workers.update_many(
        any_id("safety_orientations.project_id", TARGET_PROJECTS),
        {"$pull": {"safety_orientations": any_id("project_id", TARGET_PROJECTS)}})

    # 4. Everything again; all must be zero.
    left = {c: _count(raw_db, c, f) for c, f, _ in selectors}
    left = {c: n for c, n in left.items() if n}
    left_pull = (_count(raw_db, "users", any_id("assigned_projects", TARGET_PROJECTS))
                 + _count(raw_db, "workers",
                          any_id("safety_orientations.project_id", TARGET_PROJECTS)))
    print("\nAfter:")
    for coll, flt, _ in selectors:
        print(f"  {coll:34s} {_count(raw_db, coll, flt):6d}")
    print(f"  pulled references left       {left_pull:6d}")
    for pid in TARGET_PROJECTS:
        script_audit_sync(raw_db, "project_hard_delete", "project", pid,
                          {"facts": facts, "deleted": totals,
                           "r2_keys_deleted": len(keys)}, args, script_name())
    script_audit_sync(raw_db, "company_hard_delete", "company", TARGET_COMPANY,
                      {"deleted": totals}, args, script_name())
    if left or left_pull:
        print(f"FAILED: rows remain: {left} pulled={left_pull}")
        return FAILED
    print("\nDone. Every count is 0.")
    return OK


def main(argv=None) -> int:
    refuse_legacy_flag(argv)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true",
                    help="hard delete (also needs --i-know, --reason, --session)")
    ap.add_argument("--project", action="append", default=[],
                    help="each target project id, typed out; both are required")
    ap.add_argument("--waapi-leave-action", default="leave-group",
                    help="WaAPI client/action used to leave the group")
    ap.add_argument("--bot-not-in-group", action="store_true",
                    help="skip the leave call; only if you checked the bot is "
                         "not a member")
    add_guard_args(ap)
    args = ap.parse_args(argv)
    problem = validate_execute_args(args.execute, args.project)
    if problem:
        print(problem)
        return BAD
    write = check_guard(args) and args.execute
    if check_guard(args) and not args.execute:
        print("--i-know without --execute: running as a dry run.")
    url = os.environ.get("MONGO_URL")
    if not url:
        print("MONGO_URL is not set. Run this under `railway run`.")
        return BAD
    os.environ.setdefault("JWT_SECRET", "migration")
    from pymongo import MongoClient
    client = MongoClient(url)
    db = audited(client[os.environ.get("DB_NAME", "test_database")], args,
                 script_name())
    return run(db, write, args)


if __name__ == "__main__":
    sys.exit(main())
