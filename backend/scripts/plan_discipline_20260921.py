"""SHARED, AND WRITES NOTHING: what the 2026-09-21 discipline migration and its
rollback agree on.

The migration (`migrate_plan_discipline_20260921`) and the rollback
(`rollback_plan_discipline_20260921`) both work from two things kept OUTSIDE
the repository, in one folder the operator names with `--snapshot-dir`:

    snapshot/records.bson   every plan_records row of the project, raw BSON,
    snapshot/pages.bson     every document_page_index row, raw BSON, read
                            2026-09-21 23:17Z and proven identical in content
                            to the 19:46Z snapshot the dry run was built on
    plan.json               per page: what changes (Extended JSON, so ObjectIds
                            and dates keep their types), and the SHA-256 of
                            both snapshot files

A page is in exactly one of four states, decided by comparing the rows now
stored against the snapshot and against the plan's target:

    snapshot   untouched since the dry run      -> migrate writes it
    target     already migrated                 -> skipped (idempotent)
    partial    a run of EITHER script was cut   -> whichever script runs next
               off on this page: the row is in     finishes the page
               its snapshot or target version and
               every stored record is one of its
               known snapshot or target versions
    other      changed by something else        -> BOTH scripts refuse to
                                                   write anything at all

`partial` exists because a page is several writes. `update_many` is not
atomic across documents, and a replace page is a delete then an insert; a
dropped connection between them must be resumable, not a refusal that needs
hand repair. It is recognised only when nothing on the page is anything but a
version this plan itself wrote or read.

`other` is a re-index since 19:46Z, a partial write by a third party, or a
page whose rows moved for any reason. Neither script guesses what to do with
that: the plan was computed from the snapshot and is only valid against it.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from bson import decode, decode_all, json_util
from bson.raw_bson import RawBSONDocument

from scripts.probe_helpers import require_fields

SNAPSHOT, TARGET, PARTIAL, OTHER = "snapshot", "target", "partial", "other"
RECORDS, PAGES = "plan_records", "document_page_index"

#: What every plan.json page entry must carry, and what a replace entry adds.
#: plan.json is INPUT: a missing key must stop the run, not count as zero.
ENTRY_FIELDS = ("page_id", "file_id", "page_number", "file_name", "kind",
                "discipline_from", "discipline_to")
REPLACE_FIELDS = ("records", "page_set")


@dataclass
class PageRow:
    """One plan page as surveyed. A class, not a dict: these are the script's
    own values, not document fields, and attribute access says so."""
    entry: dict
    snap_page: Any
    snap_recs: list
    target: tuple
    state: str
    records_now: int
    discipline_now: Any


class SnapshotMismatch(SystemExit):
    pass


def sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _raw_docs(path: str) -> List[RawBSONDocument]:
    blob = open(path, "rb").read()
    out, i = [], 0
    while i < len(blob):
        n = int.from_bytes(blob[i:i + 4], "little")
        out.append(RawBSONDocument(blob[i:i + n]))
        i += n
    return out


def load(snapshot_dir: str, plan_path: str = "") -> Tuple[dict, dict, dict]:
    """(plan, snapshot page by page_id, snapshot records by page_id).

    Refuses if either snapshot file is not the one the plan was built from."""
    plan_path = plan_path or os.path.join(snapshot_dir, "plan.json")
    plan = json_util.loads(open(plan_path, encoding="utf-8").read())
    for name in ("records.bson", "pages.bson"):
        path = os.path.join(snapshot_dir, "snapshot", name)
        want = plan["inputs"][f"snapshot/{name}"]
        got = sha256(path)
        if got != want:
            raise SnapshotMismatch(
                f"\n{path}\n  sha256 {got}\n  plan  {want}\n"
                "The snapshot is not the one this plan was built from. "
                "Nothing was changed.\n")
    require_fields([plan], "project_id", "inputs", "pages")
    require_fields(plan["pages"], *ENTRY_FIELDS)
    replaces = [e for e in plan["pages"] if e["kind"] == "replace"]
    if replaces:
        require_fields(replaces, *REPLACE_FIELDS)
    pages = {str(d["_id"]): d for d in _raw_docs(
        os.path.join(snapshot_dir, "snapshot", "pages.bson"))}
    recs: Dict[str, List[RawBSONDocument]] = {}
    for d in _raw_docs(os.path.join(snapshot_dir, "snapshot", "records.bson")):
        recs.setdefault(str(d["page_id"]), []).append(d)
    return plan, pages, recs


def plain(doc: Any) -> dict:
    """A document as ordinary dicts, whatever the driver handed back."""
    if isinstance(doc, RawBSONDocument):
        return decode(doc.raw)
    return dict(doc)


def key(doc: Any) -> str:
    """A comparison key that keeps BSON types (an ObjectId is not its string,
    an int is not a double) and ignores field order."""
    return json_util.dumps(plain(doc), sort_keys=True,
                           json_options=json_util.CANONICAL_JSON_OPTIONS)


def record_selector(entry: dict) -> dict:
    return {"project_id": _project_of(entry), "file_id": entry["file_id"],
            "page_number": entry["page_number"]}


def _project_of(entry: dict) -> str:
    return entry["_project_id"]


def with_project(plan: dict) -> dict:
    for e in plan["pages"]:
        e["_project_id"] = plan["project_id"]
    return plan


def _set_path(doc: dict, dotted: str, value: Any) -> None:
    """`$set` semantics for one path: an existing field keeps its position."""
    parts = dotted.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def target_state(entry: dict, snap_page, snap_recs) -> Tuple[dict, List[dict]]:
    """The page row and records this page must hold once migrated."""
    page = copy.deepcopy(plain(snap_page))
    if entry["kind"] == "discipline":
        page["discipline"] = entry["discipline_to"]
        recs = []
        for r in snap_recs:
            r = copy.deepcopy(plain(r))
            r["discipline"] = entry["discipline_to"]
            recs.append(r)
        return page, recs
    for path, value in entry["page_set"].items():
        _set_path(page, path, value)
    return page, [copy.deepcopy(plain(r)) for r in entry["records"]]


def state_of(current_page, current_recs, snap_page, snap_recs, target) -> str:
    cur_p = key(current_page) if current_page is not None else None
    cur_r = sorted(key(r) for r in current_recs)
    snap_r = sorted(key(r) for r in snap_recs)
    t_page, t_recs = target
    tgt_r = sorted(key(r) for r in t_recs)
    if cur_p == key(snap_page) and cur_r == snap_r:
        return SNAPSHOT
    if cur_p == key(t_page) and cur_r == tgt_r:
        return TARGET
    known = set(snap_r) | set(tgt_r)
    ids = [plain(r)["_id"] for r in current_recs]
    if (cur_p in (key(snap_page), key(t_page))
            and len(ids) == len(set(ids))
            and all(k in known for k in cur_r)):
        return PARTIAL
    return OTHER


def read_page(db, entry: dict):
    """(page row, records) as stored now. Reads only."""
    page = db[PAGES].find_one({"_id": entry["page_id"]})
    recs = list(db[RECORDS].find(record_selector(entry)))
    return page, recs


def survey(db, plan: dict, pages: dict, recs: dict) -> List[PageRow]:
    """Every plan page, with its state and counts. Reads only."""
    rows = []
    for e in plan["pages"]:
        pid = str(e["page_id"])
        sp, sr = pages[pid], recs.get(pid, [])
        cur_p, cur_r = read_page(db, e)
        tgt = target_state(e, sp, sr)
        rows.append(PageRow(
            entry=e, snap_page=sp, snap_recs=sr, target=tgt,
            state=state_of(cur_p, cur_r, sp, sr, tgt),
            records_now=len(cur_r),
            discipline_now=plain(cur_p).get("discipline") if cur_p else None,
        ))
    return rows


def print_table(rows: List[PageRow], title: str) -> None:
    print(f"\n{title}")
    print(f"  {'sheet':12} {'file':26} {'pg':>3} {'kind':10} "
          f"{'discipline':16} {'records':>9}  state")
    for r in rows:
        e = r.entry
        disc = f"{e['discipline_from']}->{e['discipline_to']}"
        print(f"  {str(e.get('sheet_number'))[:12]:12} {e['file_name'][:26]:26} "
              f"{e['page_number']:>3} {e['kind']:10} {disc:16} "
              f"{r.records_now:>9}  {r.state}  (now {r.discipline_now})")


def collection_counts(db, plan: dict) -> Dict[str, int]:
    pid = plan["project_id"]
    return {
        f"{RECORDS} (project)": db[RECORDS].count_documents({"project_id": pid}),
        f"{PAGES} (project)": db[PAGES].count_documents({"project_id": pid}),
        f"{RECORDS} (plan pages)": sum(
            db[RECORDS].count_documents(record_selector(e)) for e in plan["pages"]),
    }


def summary(rows: List[PageRow]) -> Dict[str, int]:
    out = {SNAPSHOT: 0, TARGET: 0, PARTIAL: 0, OTHER: 0}
    for r in rows:
        out[r.state] += 1
    return out


__all__ = ["SNAPSHOT", "TARGET", "PARTIAL", "OTHER", "RECORDS", "PAGES", "load", "plain",
           "key", "record_selector", "with_project", "target_state", "state_of",
           "survey", "print_table", "collection_counts", "summary", "sha256",
           "SnapshotMismatch", "decode_all"]
