"""HARD DELETE: the ghost company 69e16add079abf2b78ee08ce and all five of its
projects. The company has no `companies` document; its projects are 638
Lafayette Avenue (closed), a 638 Lafayette duplicate with no company_id, and
three seed projects created 2026-04-16 and already soft-deleted.

    # 1. Dry run (default). Prints what would go, per collection, plus R2.
    railway run python -m scripts.hard_delete_ghost_company_69e16add

    # 2. Execute. All five project ids must be typed out, exactly.
    railway run python -m scripts.hard_delete_ghost_company_69e16add --execute \\
        --project 69e16adf079abf2b78ee08d4 --project 69e16adf079abf2b78ee08d6 \\
        --project 69e16ade079abf2b78ee08d0 --project 69e16ade079abf2b78ee08d2 \\
        --project 69f8fb5e9429c5be4b2fcb66 \\
        --i-know --reason "ghost company 69e16add, operator hard delete" \\
        --session <id>

── WHAT THIS DELETES, AND IT IS A HARD DELETE ─────────────────────────────────

  projects      69e16adf079abf2b78ee08d4  638 Lafayette Avenue
                69e16adf079abf2b78ee08d6  852 E 176th St
                69e16ade079abf2b78ee08d0  3846 Bailey Ave
                69e16ade079abf2b78ee08d2  533 Concord Ave
                69f8fb5e9429c5be4b2fcb66  638 Lafayette duplicate (no company_id)
  company       69e16add079abf2b78ee08ce  every row, in EVERY collection, with
                                          this company_id
  WhatsApp      69e1bee42bfc871b5d3db427 (120363424969499174@g.us) and every
                other group bound to this company or to these projects, or
                pending with this company — the bot LEAVES each one first
  plus the rows keyed some other way (file_id, logbook_id, group_id,
  permit_renewal_id, system_config keys) that the app's own hard delete
  misses; plus every R2 object those rows name.

  KEPT: audit_logs. It is the compliance trail, and this script adds to it.

── WHY IT BYPASSES THE APP'S BRAKES, SAID OUT LOUD ────────────────────────────

`DELETE /projects/{id}/hard-delete` refuses a project with filed logbooks or
signature events, and `retention_refusal` refuses a completed project until
completion + 7 years. This script does not consult either. The dry run PRINTS
both counts so the operator sees exactly what record is being destroyed; the
execute path records them in the audit rows.

── REFUSALS (nothing is written) ─────────────────────────────────────────────

  * --execute without all five project ids, or with any other id
  * the company has a `companies` document (the premise is that it has none)
  * the company owns any project not in the five
  * a listed project's company_id is anything but 69e16add... or empty
  * any active user (is_deleted is not true) still belongs to the company —
    they are listed
  * a group of this company is ALSO bound to another company or project
  * the bot cannot leave a group (name that group with --bot-not-in-group
    only if you have checked the bot is not a member)
  * any R2 object is still there after its delete (each key is deleted on its
    own, then HEAD must 404) or any R2 call errors — rows are kept so the run
    can be repeated; keys already gone are skipped as absent

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

TARGET_PROJECTS = (
    "69e16adf079abf2b78ee08d4",  # 638 Lafayette Avenue
    "69e16adf079abf2b78ee08d6",  # 852 E 176th St
    "69e16ade079abf2b78ee08d0",  # 3846 Bailey Ave
    "69e16ade079abf2b78ee08d2",  # 533 Concord Ave
    "69f8fb5e9429c5be4b2fcb66",  # 638 Lafayette duplicate, no company_id
)
TARGET_COMPANY = "69e16add079abf2b78ee08ce"
# A listed project may carry this company or none; anything else refuses.
ALLOWED_PROJECT_COMPANIES = (TARGET_COMPANY, None)
# The group known before the run. Others are discovered (_discover_groups).
TARGET_GROUP_DOC = "69e1bee42bfc871b5d3db427"
TARGET_WA_GROUP = "120363424969499174@g.us"

KEEP_COLLECTIONS = frozenset({"audit_logs", "system.views", "system.profile"})


# ── pure helpers (tested in tests/test_hard_delete_ghost_company_69e16add.py)

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
        return ("--execute requires exactly these five: --project "
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
                    renewal_ids, wa_groups, group_doc_ids,
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
    groups = sorted(set(wa_groups))
    for c in ("whatsapp_messages", "whatsapp_send_log",
              "whatsapp_conversation_state", "whatsapp_link_codes",
              "whatsapp_voice_events", "whatsapp_pending_groups"):
        sel.append((c, {"group_id": {"$in": groups}}, "by group_id"))
    sel.append(("whatsapp_groups", {"$or": [any_id("_id", group_doc_ids),
                                            {"wa_group_id": {"$in": groups}}]},
                "the group bindings"))
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


def _discover_groups(db) -> Tuple[List[str], List[str]]:
    """(group doc ids, wa group ids) of every WhatsApp group this deletion
    touches: the known group, every whatsapp_groups row bound to the company
    or to a target project, and every pending group recorded for the
    company."""
    pids = list(TARGET_PROJECTS)
    doc_ids: Set[str] = {TARGET_GROUP_DOC}
    wa_ids: Set[str] = {TARGET_WA_GROUP}
    for g in db.whatsapp_groups.find({"$or": [
            any_id("company_id", [TARGET_COMPANY]), any_id("project_id", pids),
            any_id("_id", [TARGET_GROUP_DOC]), {"wa_group_id": TARGET_WA_GROUP}]},
            {"_id": 1, "wa_group_id": 1}):
        doc_ids.add(str(g["_id"]))
        if g.get("wa_group_id"):
            wa_ids.add(str(g["wa_group_id"]))
    for g in db.whatsapp_pending_groups.find(
            any_id("company_id", [TARGET_COMPANY]), {"group_id": 1}):
        if g.get("group_id"):
            wa_ids.add(str(g["group_id"]))
    return sorted(doc_ids), sorted(wa_ids)


def _preflight(db) -> Tuple[Optional[str], Dict[str, Any]]:
    """Facts, and a refusal reason when the premises do not hold."""
    facts: Dict[str, Any] = {}
    pids = list(TARGET_PROJECTS)
    projects = list(db.projects.find(any_id("_id", pids)))
    facts["projects"] = [{k: (str(v) if k in ("_id", "company_id") else v)
                          for k, v in p.items()
                          if k in ("_id", "name", "address", "company_id",
                                   "created_at", "job_completion_date",
                                   "completion_source", "legal_hold",
                                   "marked_for_deletion", "is_deleted")}
                         for p in projects]
    found = {str(p["_id"]) for p in projects}
    facts["listed_projects_not_found"] = [p for p in pids if p not in found]
    for p in projects:
        have = str(p.get("company_id") or "") or None
        if have not in ALLOWED_PROJECT_COMPANIES:
            return (f"project {p['_id']} has company_id {have!r}; only "
                    f"{TARGET_COMPANY!r} or none is allowed"), facts
    if db.companies.count_documents(any_id("_id", [TARGET_COMPANY])):
        return (f"company {TARGET_COMPANY} HAS a companies document; this "
                "script assumes it does not"), facts
    others = [str(p["_id"]) for p in db.projects.find(
        {**any_id("company_id", [TARGET_COMPANY]),
         "_id": {"$nin": [v for i in pids for v in id_values(i)]}}, {"_id": 1})]
    facts["other_projects_of_company"] = others
    if others:
        return (f"company {TARGET_COMPANY} owns projects not in the list "
                f"{others}; refusing to delete them by company_id"), facts
    active_users = [
        {"_id": str(u.get("_id")), "name": u.get("name"),
         "email": u.get("email"), "role": u.get("role")}
        for u in db.users.find({**any_id("company_id", [TARGET_COMPANY]),
                                "is_deleted": {"$ne": True}},
                               {"name": 1, "email": 1, "role": 1})]
    facts["active_users_of_company"] = active_users
    if active_users:
        return (f"{len(active_users)} active user(s) still belong to company "
                f"{TARGET_COMPANY}: {active_users}"), facts
    group_doc_ids, wa_groups = _discover_groups(db)
    facts["whatsapp_group_docs"] = group_doc_ids
    facts["whatsapp_groups"] = wa_groups
    stray_groups = [
        {"_id": str(g.get("_id")), "wa_group_id": g.get("wa_group_id"),
         "company_id": str(g.get("company_id") or ""),
         "project_id": str(g.get("project_id") or "")}
        for g in db.whatsapp_groups.find({"wa_group_id": {"$in": wa_groups}})
        if str(g.get("project_id") or "") not in ["", *pids]
        or str(g.get("company_id") or "") not in ("", TARGET_COMPANY)]
    facts["group_rows_elsewhere"] = stray_groups
    if stray_groups:
        return (f"groups of this company are bound elsewhere too: "
                f"{stray_groups}"), facts
    facts["filed_logbooks"] = db.logbooks.count_documents({
        **any_id("project_id", pids),
        "$or": [{"status": "submitted"}, {"is_locked": True}]})
    facts["signature_events"] = db.signature_events.count_documents(
        any_id("project_id", pids))
    facts["audit_logs_kept"] = db.audit_logs.count_documents({"$or": [
        any_id("resource_id", pids + [TARGET_COMPANY]),
        any_id("details.project_id", pids)]})
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


def _r2_target():
    """(client, bucket_for) — the SAME client and bucket names the app writes
    with. R2_ENDPOINT_URL ends in the bucket name, so every object's real key
    carries a doubled `blueview/` segment; single-object calls (head, get,
    put, delete_object) made through this client land on it, consistently.
    Bucket-level calls (list_objects_v2, delete_objects) do NOT: they become
    a request on an object named `blueview` and come back empty or as a
    no-op. See server._r2_delete_prefix. So this script never uses them."""
    import server
    client = server._get_r2_client()
    main_bucket = server.R2_BUCKET_NAME
    card_bucket = (os.environ.get("CARD_AUDIT_BUCKET_NAME", "").strip()
                   or main_bucket)

    def bucket_for(key: str) -> str:
        return card_bucket if key.startswith("card-audit/") else main_bucket
    return client, (bucket_for if main_bucket else None)


def _r2_exists(client, bucket: str, key: str) -> Optional[bool]:
    """True if HEAD finds the object, False on 404, None on any other error."""
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as e:
        resp = getattr(e, "response", None) or {}
        code = str((resp.get("Error") or {}).get("Code") or "")
        status = (resp.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        if status == 404 or code in ("404", "NoSuchKey", "NotFound"):
            return False
        return None


def r2_probe(client, bucket_for, keys) -> Dict[str, List[str]]:
    """Read-only: HEAD every key. {present, absent, error}."""
    out: Dict[str, List[str]] = {"present": [], "absent": [], "error": []}
    for k in sorted(keys):
        state = _r2_exists(client, bucket_for(k), k)
        out["present" if state else "absent" if state is False else "error"].append(k)
    return out


def r2_delete_verified(client, bucket_for, keys) -> Dict[str, List[str]]:
    """Delete each key ONE AT A TIME and prove it is gone.

    Per key: HEAD (already absent → recorded, nothing to do), delete_object,
    then HEAD again, which must be 404. Returns {deleted, absent_before,
    still_present, error}; anything in still_present or error means the
    caller must not touch the rows (they are what names these keys)."""
    out: Dict[str, List[str]] = {"deleted": [], "absent_before": [],
                                 "still_present": [], "error": []}
    for k in sorted(keys):
        b = bucket_for(k)
        before = _r2_exists(client, b, k)
        if before is False:
            out["absent_before"].append(k)
            continue
        if before is None:
            out["error"].append(k)
            continue
        try:
            client.delete_object(Bucket=b, Key=k)
        except Exception:
            out["error"].append(k)
            continue
        after = _r2_exists(client, b, k)
        if after is False:
            out["deleted"].append(k)
        elif after is True:
            out["still_present"].append(k)
        else:
            out["error"].append(k)
    return out


def _leave_group(action: str, chat_id: str) -> Tuple[bool, str]:
    base = os.environ.get("WAAPI_BASE_URL", "https://waapi.app/api/v1")
    inst = os.environ.get("WAAPI_INSTANCE_ID", "")
    token = os.environ.get("WAAPI_TOKEN", "")
    if not (inst and token):
        return False, "WAAPI_INSTANCE_ID / WAAPI_TOKEN not set"
    req = urllib.request.Request(
        f"{base}/instances/{inst}/client/action/{action}",
        data=json.dumps({"chatId": chat_id}).encode(),
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



def _group_info(chat_id: str) -> Tuple[Optional[bool], str]:
    """Read-only: is the bot still in this group? (True / False / None when
    unknown) and a short note. Asks WaAPI get-group-info and looks for the
    bot's number (WAAPI_DISPLAY_NUMBER) among the participants. The response
    shape is not verified against WaAPI's docs, so the note carries what came
    back for the operator to read."""
    base = os.environ.get("WAAPI_BASE_URL", "https://waapi.app/api/v1")
    inst = os.environ.get("WAAPI_INSTANCE_ID", "")
    token = os.environ.get("WAAPI_TOKEN", "")
    bot = re.sub(r"\D", "", os.environ.get("WAAPI_DISPLAY_NUMBER", "") or "")
    if not (inst and token):
        return None, "WAAPI_INSTANCE_ID / WAAPI_TOKEN not set"
    req = urllib.request.Request(
        f"{base}/instances/{inst}/client/action/get-group-info",
        data=json.dumps({"chatId": chat_id}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return None, f"http {e.code}"
    except Exception as e:
        return None, type(e).__name__
    raw_clean = raw.replace(token, "<token>")
    if '"participants"' not in raw:
        return None, f"no participant list in reply: {raw_clean[:300]}"
    if not bot:
        return None, "WAAPI_DISPLAY_NUMBER not set; cannot look for the bot"
    return (bot in raw), (f"bot {'IS' if bot in raw else 'is NOT'} among the "
                          f"participants ({len(raw)} bytes of group info)")

def run(db, write: bool, args) -> int:
    # One handle. Through audited() every write below records an audit row
    # (without --i-know it is the bare handle and nothing writes anyway).
    raw_db = db
    print(f"Targets: company {TARGET_COMPANY}; projects "
          f"{', '.join(TARGET_PROJECTS)}; known group {TARGET_GROUP_DOC} "
          f"({TARGET_WA_GROUP}) plus any other group of the company\n")
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
        wa_groups=facts["whatsapp_groups"],
        group_doc_ids=facts["whatsapp_group_docs"],
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
    r2_client, bucket_for = _r2_target()
    if keys and r2_client and bucket_for:
        probe = r2_probe(r2_client, bucket_for, keys)
        print(f"R2 HEAD (read-only, the same call the delete is verified with): "
              f"present {len(probe['present'])}, absent {len(probe['absent'])}, "
              f"error {len(probe['error'])}")
        for k in probe["error"][:10]:
            print(f"  HEAD error: {k}")
    elif keys:
        print("R2 is not configured here; the delete would refuse.")
    if len(keys) > 200:
        print(f"  ... and {len(keys) - 200} more")
    prefixes = []
    for pid in TARGET_PROJECTS:
        prefixes += [f"{TARGET_COMPANY}/{pid}/", f"plans/{pid}/",
                     f"logbook-photos/{pid}/", f"card-audit/{pid}/"]
    print("\nR2 prefix listing (informational; see _r2_listing):")
    for prefix, found in _r2_listing(prefixes).items():
        print(f"  {prefix}: {len(found)}")
    print("  (A listing returns 0 in this deployment whatever is stored; the "
          "HEAD counts above are the real check.)")

    print("\nWhatsApp groups — is the bot still in them? (read-only)")
    for chat_id in facts["whatsapp_groups"]:
        member, note = _group_info(chat_id)
        print(f"  {chat_id}: {'member' if member else 'not a member' if member is False else 'unknown'} — {note}")

    if not write:
        print("\nDRY RUN — nothing was written. Re-run with --execute, all "
              "five --project ids, --i-know --reason --session.")
        return OK

    # 1. The bot leaves every group BEFORE its binding rows go, so the next
    #    message cannot re-create a pending row and greet the chat. A leave
    #    cannot be undone, so EVERY leave is attempted before deciding: one
    #    failure must not strand the run halfway with an unclear record of
    #    which groups the bot already left. If any failed, nothing is
    #    deleted and the exact re-run command is printed, naming the groups
    #    already left (a second leave of those would fail).
    print()
    skip = set(args.bot_not_in_group or [])
    left, leave_failed = [], []
    for chat_id in facts["whatsapp_groups"]:
        if chat_id in skip:
            print(f"WhatsApp leave {chat_id}: skipped (--bot-not-in-group)")
            continue
        ok, detail = _leave_group(args.waapi_leave_action, chat_id)
        print(f"WhatsApp leave {chat_id}: {'ok' if ok else 'FAILED'} ({detail})")
        (left if ok else leave_failed).append(chat_id)
    if leave_failed:
        done = sorted(skip | set(left))
        print(f"\nREFUSED: the bot did not leave {leave_failed}; nothing "
              f"deleted. It DID leave {left or 'none'}.")
        print("Re-run with the groups already left skipped:"
              + "".join(f" --bot-not-in-group {g}" for g in done))
        print("If a FAILED group is one the bot is not in, add it too.")
        return REFUSED

    # 2. R2 first, while the rows that name the keys still exist. One key at
    #    a time, each followed by a HEAD that must 404. Any object still
    #    there, or any call that errored, stops the run BEFORE the rows go:
    #    the rows are the only record of which keys to delete.
    r2 = {"deleted": [], "absent_before": [], "still_present": [], "error": []}
    if keys:
        r2_client, bucket_for = _r2_target()
        if not (r2_client and bucket_for):
            print("FAILED: R2 is not configured here; nothing deleted, rows kept.")
            return FAILED
        r2 = r2_delete_verified(r2_client, bucket_for, keys)
    print(f"\nR2: deleted and verified gone {len(r2['deleted'])}, already absent "
          f"{len(r2['absent_before'])}, STILL PRESENT {len(r2['still_present'])}, "
          f"errors {len(r2['error'])}")
    if r2["still_present"] or r2["error"]:
        for k in (r2["still_present"] + r2["error"])[:20]:
            print(f"  not deleted: {k}")
        print("FAILED: some R2 objects were not deleted; NO rows were touched. "
              "Fix and re-run — keys already deleted are skipped as absent.")
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
                           "r2_keys_deleted": len(r2["deleted"]),
                           "r2_keys_absent_before": len(r2["absent_before"])},
                          args, script_name())
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
                    help="each target project id, typed out; all five are "
                         "required")
    ap.add_argument("--waapi-leave-action", default="leave-group",
                    help="WaAPI client/action used to leave the group")
    ap.add_argument("--bot-not-in-group", action="append", default=[],
                    metavar="WA_GROUP_ID",
                    help="skip the leave call for this group (repeatable); "
                         "only if you checked the bot is not a member")
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
