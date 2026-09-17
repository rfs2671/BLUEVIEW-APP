"""WHAT A HARD DELETE WOULD DESTROY, COUNTED BEFORE IT DESTROYS IT.

── WHY THIS EXISTS ─────────────────────────────────────────────────────────

`DELETE /projects/{id}/hard-delete` physically removes a project and every
document, storage object and config key it owns, and the R2 sweeps delete by
PREFIX -- those objects have no database rows to rebuild from. Until now the
operator pressed it and found out afterwards what had been in there.

And the reverse: `DELETE /owner/companies/{id}` deletes the company AND every
user under it, and LEAVES EVERY PROJECT BEHIND. Measured -- it ran four times,
and three of those four company ids still have projects in the database with no
company document to hang them on: 26 projects and 20 logbooks, sitting under a
tenant that does not exist. The operator's own project list showed one of them
under no card at all.

── THE ONE RULE THAT IS NOT A WARNING ──────────────────────────────────────

A FILED OR SIGNED LOGBOOK, OR ANY SIGNATURE EVENT, BLOCKS THE DELETE OUTRIGHT.
Not a confirmation, not a count on a screen -- a refusal. Those are statutory
records: BC 3301.13 logs, a man's signature and the affirmation taken at the
gate. A soft delete hides them and keeps them; nothing in this product may
destroy them, and the operator is not the party retention is owed to.

`blocking` below is what the caller refuses on. `counts` is what it shows.
Keeping them separate is deliberate: a count that grows should not silently
become a block, and a block must not be buried in a list of forty numbers.

PURE. Takes a database handle and reads; writes nothing, decides nothing about
authorisation. The endpoint owns the refusal so the refusal is testable
separately from the counting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: Collections keyed by `project_id` that a purge would remove. Mirrors
#: server._PROJECT_OWNED_COLLECTIONS; imported rather than copied at the call
#: site so the report cannot drift from what the delete actually sweeps.
PROJECT_KEY = "project_id"

#: A logbook in one of these states is a FILED RECORD. `status == "submitted"`
#: is the app's own word for filed, and `is_locked` is the seal.
FILED_LOGBOOK_QUERY: Dict[str, Any] = {
    "$or": [{"status": "submitted"}, {"is_locked": True}],
    "is_deleted": {"$ne": True},
}


async def _count(db, collection: str, query: Dict[str, Any]) -> int:
    try:
        return await db[collection].count_documents(query)
    except Exception:
        # A collection that does not exist on this deployment counts zero
        # rather than taking the whole report down. The report is a courtesy;
        # the BLOCK below is what must never fail open, and it reads
        # collections that certainly exist.
        return -1


async def project_dependencies(db, project_id: str,
                               collections: Optional[List[str]] = None) -> Dict:
    """Everything a purge of this project would take with it.

    Returns {counts, blocking, r2_prefixes, total}. `blocking` is empty when
    the delete may proceed.
    """
    pid = str(project_id)
    counts: Dict[str, int] = {}
    for name in (collections or []):
        n = await _count(db, name, {PROJECT_KEY: pid})
        if n:
            counts[name] = n

    # ── THE BLOCK ───────────────────────────────────────────────────────
    filed = await _count(db, "logbooks", {PROJECT_KEY: pid, **FILED_LOGBOOK_QUERY})
    signed = await _count(db, "signature_events",
                          {PROJECT_KEY: pid, "is_deleted": {"$ne": True}})
    blocking: List[Dict[str, Any]] = []
    if filed > 0:
        blocking.append({
            "kind": "filed_logbooks", "count": filed,
            "reason": "Filed or signed logbooks are statutory records. Soft "
                      "delete hides them and keeps them; nothing here may "
                      "destroy them.",
        })
    if signed > 0:
        blocking.append({
            "kind": "signature_events", "count": signed,
            "reason": "A signature event is a person's attestation, including "
                      "the affirmation taken from a worker at the gate.",
        })

    # Files are named because the R2 sweep is by PREFIX and those objects have
    # no rows to rebuild from -- the one part of a purge that is unrecoverable
    # even in principle.
    files = await _count(db, "project_files", {PROJECT_KEY: pid})
    pages = await _count(db, "document_page_index", {PROJECT_KEY: pid})

    return {
        "scope": "project",
        "id": pid,
        "counts": counts,
        "blocking": blocking,
        "unrecoverable": {"project_files": max(files, 0),
                          "indexed_pages": max(pages, 0)},
        "total": sum(v for v in counts.values() if v > 0),
    }


async def company_dependencies(db, company_id: str) -> Dict:
    """Everything under a company, and THE REVERSE CASCADE.

    ── THE BUG THIS EXISTS FOR ─────────────────────────────────────────────

    `hard_delete_company` checks for active ADMINS and nothing else. It deletes
    every user and the company row, and never looks at projects. Four companies
    went that way; three left projects behind. A company with projects is not
    deletable -- the projects have to be deleted or reparented FIRST, and that
    is a decision about compliance records, not a cascade to run silently.
    """
    cid = str(company_id)
    projects = await db.projects.find(
        {"company_id": cid}, {"_id": 1, "name": 1, "is_deleted": 1},
    ).to_list(500)
    live = [p for p in projects if p.get("is_deleted") is not True]
    users = await _count(db, "users", {"company_id": cid})
    workers = await _count(db, "workers", {"company_id": cid})
    logbooks = await _count(db, "logbooks", {"company_id": cid})

    blocking: List[Dict[str, Any]] = []
    if projects:
        blocking.append({
            "kind": "projects_would_be_orphaned",
            "count": len(projects),
            "live": len(live),
            "reason": "Deleting a company does not delete its projects. Delete "
                      "or reparent them first, or they become rows under a "
                      "tenant that does not exist.",
            "names": [str(p.get("name") or p["_id"])[:60] for p in projects[:12]],
        })

    return {
        "scope": "company",
        "id": cid,
        "counts": {k: v for k, v in (
            ("projects", len(projects)), ("live_projects", len(live)),
            ("users", users), ("workers", workers), ("logbooks", logbooks),
        ) if v},
        "blocking": blocking,
        "total": len(projects) + max(users, 0) + max(workers, 0),
    }


def confirm_matches(typed, expected) -> bool:
    """Did the operator type the name?

    CASE- AND SPACE-INSENSITIVE, and nothing cleverer. The control exists to
    make a destructive action deliberate, not to test transcription: an
    operator who types the address of the project he means, in the case his
    keyboard produced, has demonstrated the thing being asked for.

    AN EMPTY EXPECTED NAME MATCHES NOTHING. A project with no name would
    otherwise be deletable by sending "" -- an empty confirmation for the row
    least likely to be the one anybody meant.
    """
    want = " ".join(str(expected or "").split()).casefold()
    got = " ".join(str(typed or "").split()).casefold()
    return bool(want) and want == got
