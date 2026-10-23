r"""WIPE ONE COMPANY'S WHATSAPP TEST DATA -- history AND setup -- before real
deployment. Everything in WhatsApp so far was test data: the owner wipes it,
then adds real phone numbers to real projects and has people opt in fresh.

    # 1. Dry run (default). Prints, per collection, what would go, the R2
    #    object count, and the groups that would be unlinked.
    railway run python scripts\wipe_whatsapp_test_data.py --email you@company.com

    # 2. Execute.
    railway run python scripts\wipe_whatsapp_test_data.py --email you@company.com --i-know --reason "..." --session <id>

    Optional:  --company <id>          instead of --email
               --leave-groups          the bot also LEAVES the company's groups
               --include-global-debug  also wipe whatsapp_webhook_log /
                                       whatsapp_audio_probe / whatsapp_audio_diag
                                       ENTIRELY (they carry no company link)

── WHAT GOES (scoped to the one company) ──────────────────────────────────────

Whole rows, by the field each collection actually carries (verified in
server.py and lib/ -- see build_selectors):

  company_id / project_id of its projects / user_id of its users
      whatsapp_messages  whatsapp_groups  whatsapp_pending_groups
      whatsapp_link_codes  whatsapp_dm_answers  whatsapp_voice_events
      whatsapp_optins  whatsapp_notification_ledger  whatsapp_connect_codes
      whatsapp_dm_welcomes (_id = user id; absent collection = 0 rows)
      whatsapp_checklists  whatsapp_sender_map  whatsapp_lid_phone
      whatsapp_sender_language  voice_daily  wa_quiet_queue  attention_items
      attention_cursors  attention_metrics  chase_shadow  upcoming_cursors
      punch_items  punch_sessions  punch_links  punch_counters  punch_leases
      brief_log  outbound_failures
  group_id of its groups (linked, pending, or seen on its messages)
      whatsapp_send_log, plus the group-keyed rows above that carry no company
  DM chat of its people (opt-in phone / chat, profile phone)
      whatsapp_conversation_state  whatsapp_dm_reply_windows
      whatsapp_contact_card_log, and the bot's own DM rows in whatsapp_messages

Only the WhatsApp subset of three mixed collections:
  upcoming_events           source "chat" / "dm"  (city events are KEPT)
  project_memory            source "whatsapp" / "attention" (daily_report KEPT)
  notification_preferences  $unset whatsapp_project.{gc_group_id,
                            gc_group_confirmed, gc_proposal, gc_declined,
                            punch_to, punch_to_user, punch_contacts} on the
                            company's project rows. The alert switches, send
                            windows and every other preference stay; no
                            document is deleted.

R2: every object a wiped row names, BY KEY (voice audio, group photos per
lib/wa_photos.owned_keys, punch photos and their thumbnails) -- except a key a
row that is KEPT still names. Prefix sweeps are not used: in this deployment a
listing returns nothing (server._r2_delete_prefix).

── WHAT STAYS ─────────────────────────────────────────────────────────────────

  audit_logs (and this script adds to it), vision_calls, retention_ledger,
  whatsapp_config, whatsapp_company_settings, whatsapp_instance_monitor,
  whatsapp_contacts (rebuilt from users.phone), users / workers and their
  phone fields, every non-WhatsApp collection.
  project_memory_state is NOT reset: see MEMORY_STATE_NOTE.

── NEVER SHARED DATA ──────────────────────────────────────────────────────────

A group also bound to ANOTHER company, or a phone that is also another
company's, is "shared": its rows that carry this company_id still go, but rows
keyed only by that group / phone are left, and the bot never leaves it. The
dry run says how many.

── ORDER (the same as scripts/hard_delete_ghost_company_69e16add.py) ──────────

  1. --leave-groups: the bot leaves each group. Every leave is tried; any
     failure stops the run before anything is deleted.
  2. R2, one key at a time, each followed by a HEAD that must 404. R2 goes
     FIRST because the rows are the only record of which keys to delete: rows
     first and a failed R2 call would orphan objects nobody can find again.
     Any object still there, or any error, stops the run with NO row touched.
  3. Rows, through the audited handle (every write leaves an audit row).
  4. Every count again: anything left in scope, or a deleted count that is
     not what was counted, exits 4. Re-running is safe: it is idempotent.

Nothing prints a phone number, chat id or JID in full: at most the last 4.

Exit codes: 0 ok, 2 bad invocation / env, 3 refused, 4 failed (post-check).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import wa_dm, wa_photos  # noqa: E402
from scripts.prod_guard import (  # noqa: E402
    add_guard_args, audited, check_guard, refuse_legacy_flag, script_audit_sync,
)
# The R2 and WaAPI helpers the ghost-company delete was reviewed with: the same
# client and bucket the app writes with, per-key delete + HEAD-must-404, never
# a bucket-level call.
from scripts.hard_delete_ghost_company_69e16add import (  # noqa: E402
    _leave_group, _r2_target, any_id, id_values, r2_delete_verified, r2_probe,
)

NAME = "wipe_whatsapp_test_data"
OK, BAD, REFUSED, FAILED = 0, 2, 3, 4

#: Fields under notification_preferences.whatsapp_project that are WhatsApp
#: SETUP (which group, which people). Everything else there is a switch or a
#: window and stays.
PREF_FIELDS = ("gc_group_id", "gc_group_confirmed", "gc_proposal", "gc_declined",
               "punch_to", "punch_to_user", "punch_contacts")

#: No company link at all: wiped ENTIRELY, and only with --include-global-debug.
GLOBAL_DEBUG = ("whatsapp_webhook_log", "whatsapp_audio_probe", "whatsapp_audio_diag")

#: Printed so the operator sees what is deliberately left.
KEPT = ("audit_logs", "vision_calls", "retention_ledger", "whatsapp_config",
        "whatsapp_company_settings", "whatsapp_instance_monitor",
        "whatsapp_contacts", "project_memory_state", "users", "workers",
        "upcoming_events (source city)", "project_memory (source daily_report)",
        "notification_preferences (all but the setup fields)")

MEMORY_STATE_NOTE = (
    "project_memory_state: NOT reset. Its cursor is a POSITION -- (created_at, _id) "
    "of the last message and report read, and gc_after, an _id to continue the "
    "cleanup sweep after -- compared with $gt, never looked up. Rows deleted "
    "behind it change nothing; new messages sort after it. Resetting it would "
    "re-read every company's messages and filed reports from the start.")

UPCOMING_WA_SOURCES = ("chat", "dm")
MEMORY_WA_SOURCES = ("whatsapp", "attention")


# ── pure helpers ──────────────────────────────────────────────────────────────

def last4(value: Any) -> str:
    """At most the last four digits of a phone, chat id or JID."""
    d = re.sub(r"\D", "", str(value or ""))
    return f"…{d[-4:]}" if d else "…"


def safe_text(value: Any) -> str:
    """A name as printed: any run of 7+ digits (a number typed into a group
    subject) shown as its last four."""
    return re.sub(r"\d{7,}", lambda m: "…" + m.group()[-4:], str(value or "")).strip()


def digit_variants(raw: Any) -> List[str]:
    """Every digits-only spelling of one phone (server._contact_phone_variants,
    without the '+' forms): with and without the US country code."""
    d = wa_dm.phone_digits(raw) if "@" in str(raw or "") else re.sub(r"\D", "", str(raw or ""))
    if not d:
        return []
    out = [d]
    if len(d) == 11 and d.startswith("1"):
        out.append(d[1:])
    elif len(d) == 10:
        out.append("1" + d)
    return out


def dm_chat_ids(digits: Iterable[str]) -> List[str]:
    """The chat ids a DM with these digits is stored under (server._dm_chat_ids)."""
    out: List[str] = []
    for d in sorted(set(digits)):
        out += [f"{d}@c.us", f"{d}@lid", f"{d}@s.whatsapp.net"]
    return out


def punch_thumb_key(key: str) -> str:
    """server._punch_thumb_key."""
    return (key[:-4] if key.endswith(".jpg") else key) + "-thumb.jpg"


def message_keys(row: Dict[str, Any]) -> List[str]:
    """The R2 objects a whatsapp_messages row names: its voice note's audio,
    its own group photo (lib/wa_photos.owned_keys -- never a shared punch
    photo through `photo`), and a punch completion photo (`photo_key`, which
    the punch item also names: kept if a kept row still does)."""
    out = [(row.get("voice") or {}).get("audio_key"), row.get("photo_key")]
    out += wa_photos.owned_keys(row)
    return [k for k in out if isinstance(k, str) and k.strip()]


def punch_item_keys(row: Dict[str, Any]) -> List[str]:
    """server._punch_r2_keys for one item: the photos, their thumbnails, the
    done photo, a link photo not yet confirmed."""
    shown = [row.get("photo_key"), *(row.get("extra_photos") or [])]
    out = shown + [punch_thumb_key(k) for k in shown if isinstance(k, str) and k]
    out += [(row.get("completion") or {}).get("photo_key"),
            (row.get("link_photo_pending") or {}).get("key")]
    return [k for k in out if isinstance(k, str) and k.strip()]


def punch_session_keys(row: Dict[str, Any]) -> List[str]:
    """A walk's photos: server._punch_r2_keys reads items[].photo_key; the
    walk also keeps extra photos and the raw photos[] list."""
    out: List[str] = []
    for it in row.get("items") or []:
        if isinstance(it, dict):
            out += [it.get("photo_key"), *(it.get("extra_photos") or [])]
    for p in row.get("photos") or []:
        if isinstance(p, dict):
            out.append(p.get("key"))
    return [k for k in out if isinstance(k, str) and k.strip()]


#: (collection, key extractor, the fields a key sits in -- for the "is it
#: still named by a KEPT row" check).
KEY_SOURCES = (
    ("whatsapp_messages", message_keys, ("voice.audio_key", "photo.key", "photo_key")),
    ("punch_items", punch_item_keys, ("photo_key", "extra_photos", "completion.photo_key",
                                      "link_photo_pending.key")),
    ("punch_sessions", punch_session_keys, ("items.photo_key", "items.extra_photos",
                                            "photos.key")),
)


def _or(*clauses: Dict[str, Any]) -> Dict[str, Any]:
    """$or of the clauses that can match something (an empty $in cannot)."""
    keep = []
    for c in clauses:
        empty = any(isinstance(v, dict) and v.get("$in") == [] for v in c.values())
        if not empty:
            keep.append(c)
    return {"$or": keep} if keep else {"_id": {"$in": []}}


def build_selectors(s: SimpleNamespace, include_global: bool = False
                    ) -> List[Tuple[str, Dict[str, Any], str]]:
    """(collection, filter, scope) for every delete, in the order they run.
    ONE selector per collection, so a count and a delete are comparable.

    `s` is what discover() found: cvals (company id as stored), pvals (its
    projects), uids / uvals (its users), groups (its groups NOT shared with
    another company), dm_chats / dm_digits (its people's DM chats, not
    shared)."""
    co = {"company_id": {"$in": s.cvals}}
    proj = {"project_id": {"$in": s.pvals}}
    usr = {"user_id": {"$in": s.uvals}}
    grp = {"group_id": {"$in": s.groups}}
    dm_rows = {"is_dm": True, "group_id": {"$in": s.dm_chats}}
    cid = re.escape(str(s.company_id))
    sel: List[Tuple[str, Dict[str, Any], str]] = [
        # The bindings first: once they are gone no new row is stamped with
        # this company while the rest is deleted.
        ("whatsapp_groups", _or(co, proj, {"wa_group_id": {"$in": s.groups}}),
         "company_id / project_id / group"),
        ("whatsapp_pending_groups", _or(co, grp), "company_id / group_id"),
        ("whatsapp_link_codes", _or(co, proj, grp), "company_id / project_id / group_id"),
        ("whatsapp_messages", _or(co, proj, usr, grp, dm_rows),
         "company_id / project_id / user_id / group_id / DM chat"),
        ("whatsapp_conversation_state",
         _or(co, grp, {"group_id": {"$in": s.dm_chats + s.dm_digits}}),
         "company_id / group_id / DM chat"),
        ("whatsapp_dm_answers", _or(co, usr), "company_id / user_id"),
        ("whatsapp_voice_events", _or(co, grp), "company_id / group_id"),
        ("whatsapp_optins", _or(co, usr, {"user_id": None, "phone": {"$in": s.dm_digits}},
                                {"user_id": None, "chat_digits": {"$in": s.dm_digits}}),
         "company_id / user_id / STOP from its people's phones"),
        ("whatsapp_dm_reply_windows", {"_id": {"$in": s.dm_digits}}, "_id = its people's phones"),
        ("whatsapp_notification_ledger", _or(co, usr, proj), "company_id / user_id / project_id"),
        ("whatsapp_connect_codes", usr, "user_id"),
        # One row per user (_id = user id): wiped, so people get the DM
        # welcome again after the wipe. Written by a branch not yet on main:
        # a collection that does not exist counts 0 and deletes 0.
        ("whatsapp_dm_welcomes", _or(co, {"_id": {"$in": s.uids}}), "company_id / _id = user id"),
        ("whatsapp_send_log", grp, "group_id"),
        ("whatsapp_checklists", _or(co, proj, grp), "company_id / project_id / group_id"),
        ("whatsapp_sender_map", co, "company_id"),
        ("whatsapp_lid_phone", _or(co, {"_id": {"$regex": f"^{cid}\\|"}}),
         "company_id / _id '<company>|'"),
        ("whatsapp_sender_language", co, "company_id"),
        ("voice_daily", _or(co, {"_id": {"$regex": f"^{cid}\\|"}}),
         "company_id / _id '<company>|<day>'"),
        ("whatsapp_contact_card_log", {"_id": {"$in": s.dm_digits + s.dm_chats}},
         "_id = its people's DM chats"),
        ("wa_quiet_queue", _or(co, proj), "company_id / project_id"),
        ("attention_items", _or(co, proj, grp), "company_id / project_id / group_id"),
        ("attention_cursors", _or(co, proj, grp), "company_id / project_id / group_id"),
        ("attention_metrics", _or(co, proj, grp), "company_id / project_id / group_id"),
        ("chase_shadow", _or(co, proj, grp), "company_id / project_id / group_id"),
        ("upcoming_cursors", _or(co, proj, grp), "company_id / project_id / group_id"),
        ("upcoming_events", {**_or(co, proj), "source": {"$in": list(UPCOMING_WA_SOURCES)}},
         "company_id / project_id, source chat|dm"),
        ("project_memory", {**_or(co, proj), "source": {"$in": list(MEMORY_WA_SOURCES)}},
         "company_id / project_id, source whatsapp|attention"),
        ("punch_items", _or(co, proj), "company_id / project_id"),
        ("punch_sessions", _or(co, proj, usr), "company_id / project_id / user_id"),
        ("punch_links", _or(co, proj), "company_id / project_id"),
        ("punch_counters", {"_id": {"$in": s.pids}}, "_id = project id"),
        ("punch_leases", {"_id": {"$in": [f"walker:{u}" for u in s.uids]}},
         "_id = 'walker:<user>'"),
        ("brief_log", _or(co, usr), "company_id / user_id"),
        ("outbound_failures", _or(co, usr), "company_id / user_id"),
    ]
    if include_global:
        sel += [(c, {}, "ENTIRE collection (--include-global-debug)") for c in GLOBAL_DEBUG]
    return sel


def prefs_selector(s: SimpleNamespace) -> Dict[str, Any]:
    """The company's project-scope preference rows that hold any setup field."""
    return {"user_id": None, "scope": "project", "project_id": {"$in": s.pids},
            "$or": [{f"whatsapp_project.{f}": {"$exists": True}} for f in PREF_FIELDS]}


PREFS_UNSET = {"$unset": {f"whatsapp_project.{f}": "" for f in PREF_FIELDS}}


# ── reads ─────────────────────────────────────────────────────────────────────

def resolve_company(db, email: Optional[str], company: Optional[str]
                    ) -> Tuple[Optional[str], Dict[str, Any]]:
    """(refusal or None, facts) -- facts: company_id, name, how."""
    facts: Dict[str, Any] = {}
    if email:
        e = email.strip()
        user = db.users.find_one({"email": e.lower()}) or db.users.find_one(
            {"email": {"$regex": f"(?i)^{re.escape(e)}$"}})
        if not user:
            return f"no user with email {e!r}", facts
        if not str(user.get("company_id") or "").strip():
            return f"user {e!r} belongs to no company", facts
        company = str(user["company_id"])
        facts["how"] = f"--email {e}"
    else:
        facts["how"] = f"--company {company}"
    doc = db.companies.find_one(any_id("_id", [str(company)]))
    if not doc:
        return f"no companies document for {company!r}", facts
    facts["company_id"] = str(doc["_id"])
    facts["name"] = doc.get("name") or "(no name)"
    facts["is_test"] = bool(doc.get("is_test"))
    return None, facts


def discover(db, company_id: str) -> SimpleNamespace:
    """Everything that decides scope, read once before anything is written:
    the company's projects, users, groups and DM chats, and which of those
    groups and phones are ALSO another company's (shared -> left alone)."""
    s = SimpleNamespace(company_id=company_id, cvals=id_values(company_id))
    s.pids = [str(p["_id"]) for p in db.projects.find(
        {"company_id": {"$in": s.cvals}}, {"_id": 1})]
    s.pvals = [v for p in s.pids for v in id_values(p)]
    users = list(db.users.find({"company_id": {"$in": s.cvals}}, {"_id": 1, "phone": 1}))
    s.uids = [str(u["_id"]) for u in users]
    s.uvals = [v for u in s.uids for v in id_values(u)]
    ours = _or({"company_id": {"$in": s.cvals}}, {"project_id": {"$in": s.pvals}})

    # GROUPS: bound to it, pending with it, or seen on its group messages.
    s.group_rows = list(db.whatsapp_groups.find(
        ours, {"wa_group_id": 1, "group_name": 1, "project_id": 1, "company_id": 1}))
    # Pending groups with no company yet belong to whoever added the bot, by
    # phone (server._pending_visible_query) -- this company's when one of its
    # people added it, unless that phone is also another company's person.
    user_phones: Set[str] = {v for u in users for v in digit_variants(u.get("phone"))}
    if user_phones:
        for u in db.users.find({"phone": {"$exists": True, "$nin": [None, ""]},
                                "company_id": {"$nin": s.cvals}}, {"phone": 1}):
            user_phones -= set(digit_variants(u.get("phone")))
    added_by = sorted(user_phones | {"+" + p for p in user_phones})
    s.pending_rows = list(db.whatsapp_pending_groups.find(
        _or({"company_id": {"$in": s.cvals}},
            {"company_id": None, "added_by_phone": {"$in": added_by}}),
        {"group_id": 1, "group_name": 1}))
    wa: Set[str] = {str(g.get("wa_group_id")) for g in s.group_rows if g.get("wa_group_id")}
    wa |= {str(g.get("group_id")) for g in s.pending_rows if g.get("group_id")}
    for m in db.whatsapp_messages.find({"company_id": {"$in": s.cvals},
                                        "is_dm": {"$ne": True}}, {"group_id": 1}):
        if m.get("group_id"):
            wa.add(str(m["group_id"]))
    ours_ids = {str(g["_id"]) for g in s.group_rows}
    foreign: Set[str] = set()
    for g in db.whatsapp_groups.find({"wa_group_id": {"$in": sorted(wa)}},
                                     {"wa_group_id": 1, "company_id": 1}):
        if str(g["_id"]) not in ours_ids:
            foreign.add(str(g.get("wa_group_id")))
    for g in db.whatsapp_pending_groups.find({"group_id": {"$in": sorted(wa)}},
                                             {"group_id": 1, "company_id": 1}):
        if str(g.get("company_id") or "") not in ("", *map(str, s.cvals)):
            foreign.add(str(g.get("group_id")))
    for m in db.whatsapp_messages.find(
            {"group_id": {"$in": sorted(wa)},
             "company_id": {"$exists": True, "$nin": [*s.cvals, None, ""]}}, {"group_id": 1}):
        foreign.add(str(m.get("group_id")))
    s.groups = sorted(wa - foreign)
    s.shared_groups = sorted(wa & foreign)

    # DM CHATS: its opt-ins (phone, chat), its people's profile phones, and
    # the chats of its own DM rows.
    digits: Set[str] = set()
    chats: Set[str] = set()
    for o in db.whatsapp_optins.find(_or({"company_id": {"$in": s.cvals}},
                                         {"user_id": {"$in": s.uvals}}),
                                     {"phone": 1, "chat_digits": 1, "chat_id": 1}):
        for f in ("phone", "chat_digits"):
            digits.update(digit_variants(o.get(f)))
        if o.get("chat_id"):
            chats.add(str(o["chat_id"]))
    for u in users:
        digits.update(digit_variants(u.get("phone")))
    for m in db.whatsapp_messages.find(
            {"is_dm": True, **_or({"company_id": {"$in": s.cvals}},
                                  {"user_id": {"$in": s.uvals}})}, {"group_id": 1}):
        if m.get("group_id"):
            chats.add(str(m["group_id"]))
            digits.update(digit_variants(m["group_id"]))
    # A phone that is also another company's (its opt-in, or a user's profile)
    # is shared: rows keyed ONLY by that phone are left.
    shared: Set[str] = set()
    if digits:
        for o in db.whatsapp_optins.find(
                {"company_id": {"$exists": True, "$nin": [*s.cvals, None, ""]}},
                {"phone": 1, "chat_digits": 1}):
            for f in ("phone", "chat_digits"):
                shared.update(set(digit_variants(o.get(f))) & digits)
        for u in db.users.find({"phone": {"$exists": True, "$nin": [None, ""]},
                                "company_id": {"$nin": s.cvals}}, {"phone": 1}):
            shared.update(set(digit_variants(u.get("phone"))) & digits)
    s.dm_digits = sorted(digits - shared)
    s.shared_digits = sorted(shared)
    keep_chats = {c for c in chats if wa_dm.phone_digits(c) not in shared}
    s.dm_chats = sorted(set(dm_chat_ids(s.dm_digits)) | keep_chats)
    return s


def _count(db, coll: str, flt: Dict[str, Any]) -> int:
    try:
        return db[coll].count_documents(flt)
    except Exception as e:
        print(f"  !! count failed on {coll}: {type(e).__name__}")
        return -1


def r2_inventory(db, selectors) -> SimpleNamespace:
    """.delete: keys the wiped rows name that no KEPT row names; .kept: keys a
    kept row still names (never deleted)."""
    flts = {c: f for c, f, _ in selectors}
    named: Set[str] = set()
    wiped_ids: Dict[str, Set[str]] = {}
    for coll, extract, _fields in KEY_SOURCES:
        ids: Set[str] = set()
        for row in db[coll].find(flts[coll]):
            ids.add(str(row.get("_id")))
            named.update(extract(row))
        wiped_ids[coll] = ids
    kept: Set[str] = set()
    keys = sorted(named)
    for coll, extract, fields in KEY_SOURCES:
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            for row in db[coll].find({"$or": [{f: {"$in": chunk}} for f in fields]}):
                if str(row.get("_id")) in wiped_ids[coll]:
                    continue
                kept.update(set(extract(row)) & named)
    # A thumbnail goes with its photo: kept photo, kept thumbnail.
    kept |= named & {punch_thumb_key(b) for b in kept}
    return SimpleNamespace(delete=named - kept, kept=kept & named)


def _by_prefix(keys: Iterable[str]) -> str:
    out: Dict[str, int] = {}
    for k in keys:
        p = str(k).split("/", 1)[0]
        out[p] = out.get(p, 0) + 1
    return ", ".join(f"{p} {n}" for p, n in sorted(out.items())) or "none"


def _mask_key(key: str) -> str:
    """An R2 key as printed: its first segment and its last four characters
    (keys carry group ids and message ids)."""
    return f"{str(key).split('/', 1)[0]}/…{str(key)[-4:]}"


def _group_label(wa_id: str, names: Dict[str, str]) -> str:
    return f"\"{safe_text(names.get(wa_id)) or '(no name)'}\" ({last4(wa_id)})"


def _match_skip(groups: List[str], tails: List[str]) -> Tuple[Optional[str], Set[str]]:
    """--bot-not-in-group takes the last digits printed for a group. Each
    must name exactly one of the groups."""
    out: Set[str] = set()
    for t in tails:
        t = re.sub(r"\D", "", t)
        hits = [g for g in groups if t and re.sub(r"\D", "", g).endswith(t)]
        if len(hits) != 1:
            return (f"--bot-not-in-group {t!r} matches {len(hits)} groups; give more "
                    "of its last digits"), set()
        out.add(hits[0])
    return None, out


# ── the run ───────────────────────────────────────────────────────────────────

def run(db, write: bool, args) -> int:
    raw_db = db
    refusal, facts = resolve_company(raw_db, getattr(args, "email", None),
                                     getattr(args, "company", None))
    if refusal:
        print(f"REFUSED: {refusal}")
        return REFUSED
    cid = facts["company_id"]
    print(f"WhatsApp test-data wipe — {'EXECUTE' if write else 'DRY RUN'}")
    print(f"Company: {safe_text(facts['name'])} ({cid}){' [is_test]' if facts['is_test'] else ''}"
          f" — scoped by {facts['how']}")
    s = discover(raw_db, cid)
    print(f"  {len(s.pids)} project(s), {len(s.uids)} user(s), {len(s.groups)} group(s), "
          f"{len(s.dm_digits)} DM phone spelling(s) in scope")

    names = {str(g.get("wa_group_id")): g.get("group_name") or "" for g in s.group_rows}
    for g in s.pending_rows:
        names.setdefault(str(g.get("group_id")), g.get("group_name") or "")
    linked = sorted({str(g.get("wa_group_id")) for g in s.group_rows if g.get("wa_group_id")})
    print(f"\nGroups that would be unlinked ({len(s.group_rows)} binding row(s)):")
    for g in s.group_rows:
        gid = str(g.get("wa_group_id"))
        note = "  — this company's binding only (shared)" if gid in s.shared_groups else ""
        print(f"  {_group_label(gid, names)}{note}")
    pend = [str(g.get("group_id")) for g in s.pending_rows if g.get("group_id")]
    if pend:
        print(f"Pending groups that would be forgotten ({len(pend)}):")
        for g in pend:
            print(f"  {_group_label(g, names)}")
    other = [g for g in s.groups if g not in linked and g not in pend]
    if other:
        print(f"Groups seen only on its messages ({len(other)}): "
              + ", ".join(last4(g) for g in other))
    if s.shared_groups:
        print(f"SHARED with another company — rows keyed only by these groups are KEPT, "
              f"the bot never leaves them ({len(s.shared_groups)}): "
              + ", ".join(_group_label(g, names) for g in s.shared_groups))
    if s.shared_digits:
        print(f"SHARED phones (also another company's) — rows keyed only by them are KEPT: "
              f"{len(s.shared_digits)} spelling(s)")

    selectors = build_selectors(s, getattr(args, "include_global_debug", False))
    counted: Dict[str, int] = {}
    print("\nWould delete (collection: rows — scope):")
    for coll, flt, why in selectors:
        counted[coll] = _count(raw_db, coll, flt)
        print(f"  {coll:32s} {counted[coll]:6d}  {why}")
    pflt = prefs_selector(s)
    prefs_n = _count(raw_db, "notification_preferences", pflt)
    print(f"  {'notification_preferences':32s} {prefs_n:6d}  $unset whatsapp_project."
          f"{{{','.join(PREF_FIELDS)}}} (rows kept)")
    failed_counts = [c for c, n in counted.items() if n < 0] + (
        ["notification_preferences"] if prefs_n < 0 else [])
    if not getattr(args, "include_global_debug", False):
        dbg = ", ".join(f"{c} {_count(raw_db, c, {})}" for c in GLOBAL_DEBUG)
        print(f"\nGlobal debug logs, no company link — NOT wiped: {dbg}.\n"
              "  Pass --include-global-debug to wipe them ENTIRELY (every company's).")
    print("\nKept: " + ", ".join(KEPT))
    print(MEMORY_STATE_NOTE)

    inv = r2_inventory(raw_db, selectors)
    print(f"\nR2 objects named by those rows: {len(inv.delete)} to delete "
          f"({_by_prefix(inv.delete)}); {len(inv.kept)} kept (a kept row still names them)")
    r2_client, bucket_for = _r2_target()
    if inv.delete and r2_client and bucket_for:
        probe = r2_probe(r2_client, bucket_for, inv.delete)
        print(f"R2 HEAD (read-only): present {len(probe.present)}, absent "
              f"{len(probe.absent)}, error {len(probe.error)}")
    elif inv.delete:
        print("R2 is not configured here; the real run would stop before any row.")

    leave = [g for g in s.groups if g in linked or g in pend]
    if getattr(args, "leave_groups", False):
        print(f"\n--leave-groups: the bot would leave {len(leave)} group(s): "
              + (", ".join(_group_label(g, names) for g in leave) or "none"))
    else:
        print(f"\n--leave-groups not given: the bot stays in its {len(leave)} group(s); "
              "a message there after the wipe makes it a pending (unlinked) group again.")

    if not write:
        print("\nDRY RUN — nothing was written. Re-run with --i-know --reason \"...\" "
              "--session <id> to apply.")
        return OK

    # 0. A count that failed is an unknown scope: stop before anything is
    # left, deleted or unset (a dry run already printed it).
    if failed_counts:
        print(f"FAILED: could not count {', '.join(failed_counts)} — nothing was written. "
              "Re-run when the database answers.")
        return FAILED

    # 1. Leave the groups. Every leave is tried; any failure stops the run.
    if getattr(args, "leave_groups", False):
        problem, skip = _match_skip(leave, list(getattr(args, "bot_not_in_group", None) or []))
        if problem:
            print(f"BAD: {problem}")
            return BAD
        left, failed = [], []
        for g in leave:
            if g in skip:
                print(f"  leave {_group_label(g, names)}: skipped (--bot-not-in-group)")
                continue
            ok, detail = _leave_group(args.waapi_leave_action, g)
            detail = re.sub(r"\d{7,}", lambda m: "…" + m.group()[-4:], str(detail))
            print(f"  leave {_group_label(g, names)}: {'ok' if ok else 'FAILED'} ({detail})")
            (left if ok else failed).append(g)
        if failed:
            done = sorted(skip | set(left))
            print(f"\nREFUSED: the bot did not leave {len(failed)} group(s); nothing deleted.")
            print("Re-run with the groups already left skipped:"
                  + "".join(f" --bot-not-in-group {re.sub(r'[^0-9]', '', last4(g))}"
                            for g in done))
            print("If a FAILED group is one the bot is not in, add it too.")
            return REFUSED

    # 2. R2 first, while the rows that name the keys still exist.
    r2 = SimpleNamespace(deleted=[], absent_before=[], still_present=[], error=[])
    if inv.delete:
        r2_client, bucket_for = _r2_target()
        if not (r2_client and bucket_for):
            print("FAILED: R2 is not configured here; nothing deleted, rows kept.")
            return FAILED
        r2 = r2_delete_verified(r2_client, bucket_for, inv.delete)
    print(f"\nR2: deleted and verified gone {len(r2.deleted)}, already absent "
          f"{len(r2.absent_before)}, STILL PRESENT {len(r2.still_present)}, "
          f"errors {len(r2.error)}")
    if r2.still_present or r2.error:
        for k in (r2.still_present + r2.error)[:20]:
            print(f"  not deleted: {_mask_key(k)}")
        print("FAILED: some R2 objects were not deleted; NO rows were touched. "
              "Re-run — keys already deleted are skipped as absent.")
        return FAILED

    # 3. Rows, through the audited handle.
    deleted: Dict[str, int] = {}
    for coll, flt, _ in selectors:
        res = db[coll].delete_many(flt)
        deleted[coll] = int(getattr(res, "deleted_count", 0) or 0)
    res = db.notification_preferences.update_many(pflt, PREFS_UNSET)
    prefs_done = int(getattr(res, "modified_count", 0) or 0)

    # 4. Every count again.
    print("\nAfter (collection: counted / deleted / left):")
    bad = []
    for coll, flt, _ in selectors:
        left_n = _count(raw_db, coll, flt)
        flag = "" if (left_n == 0 and deleted[coll] == counted[coll]) else "   <- MISMATCH"
        if flag:
            bad.append(coll)
        print(f"  {coll:32s} {counted[coll]:6d} {deleted[coll]:6d} {left_n:6d}{flag}")
    prefs_left = _count(raw_db, "notification_preferences", pflt)
    flag = "" if (prefs_left == 0 and prefs_done == prefs_n) else "   <- MISMATCH"
    if flag:
        bad.append("notification_preferences")
    print(f"  {'notification_preferences':32s} {prefs_n:6d} {prefs_done:6d} {prefs_left:6d}{flag}")
    script_audit_sync(raw_db, "whatsapp_test_data_wipe", "company", cid, {
        "company_name": facts["name"], "scoped_by": facts["how"],
        "counted": counted, "deleted": deleted,
        "notification_preferences_unset": prefs_done,
        "groups": len(s.groups), "shared_groups": len(s.shared_groups),
        "r2_deleted": len(r2.deleted), "r2_absent_before": len(r2.absent_before),
        "r2_kept_still_named": len(inv.kept),
        "left_groups": bool(getattr(args, "leave_groups", False)),
        "include_global_debug": bool(getattr(args, "include_global_debug", False)),
        "mismatch": bad}, args, NAME)
    if bad:
        print(f"\nFAILED: counts do not match for {', '.join(bad)} (rows left in scope, or "
              "rows changed during the run). Re-run: it is idempotent.")
        return FAILED
    print("\nDone. Every count matches and nothing is left in scope.")
    return OK


def main(argv=None) -> int:
    refuse_legacy_flag(argv)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--email", help="email of any user of the company")
    who.add_argument("--company", help="the company id")
    ap.add_argument("--leave-groups", action="store_true",
                    help="the bot also leaves the company's WhatsApp groups (WaAPI)")
    ap.add_argument("--bot-not-in-group", action="append", default=[], metavar="LAST_DIGITS",
                    help="with --leave-groups: skip the group whose id ends in these "
                         "digits, as printed (repeatable)")
    ap.add_argument("--waapi-leave-action", default="leave-group",
                    help="WaAPI client/action used to leave a group")
    ap.add_argument("--include-global-debug", action="store_true",
                    help="also wipe " + ", ".join(GLOBAL_DEBUG) + " ENTIRELY")
    add_guard_args(ap)
    args = ap.parse_args(argv)
    write = check_guard(args)
    url = os.environ.get("MONGO_URL")
    if not url:
        print("MONGO_URL is not set. Run this under `railway run`.")
        return BAD
    os.environ.setdefault("JWT_SECRET", "migration")
    from pymongo import MongoClient
    client = MongoClient(url)
    db = audited(client[os.environ.get("DB_NAME", "test_database")], args, NAME)
    return run(db, write, args)


if __name__ == "__main__":
    sys.exit(main())
