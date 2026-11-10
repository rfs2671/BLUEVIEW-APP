"""READ-ONLY. What the progress engine can stand on, for one job or for every job.

    railway run --service Blueview2 --environment production \
        python backend/scripts/progress_validation.py "588"

    railway run --service Blueview2 --environment production \
        python backend/scripts/progress_validation.py --all-jobs

One command for the owner, in place of three: the 588 work-state probe
(scripts/work_state_probe.py), photo-location coverage and inspection /
schedule availability. Sections, each weak metric with one line of what to do,
then a readiness table (lib/progress_validation.py). --all-jobs prints one line
of counts per live job.

NOTHING IS WRITTEN, NOTHING IS PAID FOR, NOTHING PERSONAL IS PRINTED:
  * `server.db` is wrapped in `ReadOnlyDb` before anything reads: every method
    that is not a read RAISES (insert / update / delete / replace / bulk_write /
    find_one_and_* / index / drop / rename / command / an aggregate with $out or
    $merge, and any name not on the read list). A write is an error, never a
    silent drop.
  * The vision / language keys are blanked and `ServerHttpClient` and the
    WhatsApp send are replaced by stubs that raise: no paid call, no message.
  * Output is counts, ids, dates, shares and level tokens, plus work phrases and
    location strings (site words). The work-state sample's reporters are
    replaced by their role, inspectors and quotes are withheld, and every line
    goes through `progress_validation.redact` (emails, phone numbers, the names
    of the company's users, reporters and confirmers).
  * Nothing is written to disk.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── THE READ-ONLY HANDLE ───────────────────────────────────────────────────

class ReadOnlyViolation(RuntimeError):
    """Something tried to write (or to reach past the read list)."""


#: Collection members that only read. Everything else raises.
COLLECTION_READS = frozenset({"find", "find_one", "count_documents", "estimated_document_count", "distinct",
                              "aggregate", "list_indexes", "index_information", "name", "full_name"})
#: Database members that only read.
DB_READS = frozenset({"list_collection_names", "list_collections", "name"})
#: Database members that can write or hand out an unwrapped handle.
DB_BLOCKED = frozenset({"command", "cursor_command", "create_collection", "drop_collection", "rename",
                        "validate_collection", "aggregate", "watch", "dereference", "with_options", "client",
                        "drop_database"})
_WRITE_STAGES = ("$out", "$merge")


class ReadOnlyCollection:
    def __init__(self, coll: Any, attempts: list):
        object.__setattr__(self, "_c", coll)
        object.__setattr__(self, "_attempts", attempts)

    def _refuse(self, what: str):
        self._attempts.append(what)
        raise ReadOnlyViolation(f"read-only: {what} is not a read")

    def __getattr__(self, name: str):
        if name == "aggregate":
            return self._aggregate
        if name in COLLECTION_READS:
            return getattr(self._c, name)
        self._refuse(f"{getattr(self._c, 'name', '?')}.{name}")

    def __getitem__(self, name: str):
        self._refuse(f"{getattr(self._c, 'name', '?')}[{name!r}] (a sub-collection)")

    def __setattr__(self, name: str, value: Any):
        self._refuse(f"setting {name}")

    def _aggregate(self, pipeline=None, *a, **k):
        for stage in pipeline or []:
            if isinstance(stage, dict) and set(stage) & set(_WRITE_STAGES):
                self._refuse(f"{getattr(self._c, 'name', '?')}.aggregate with {sorted(set(stage) & set(_WRITE_STAGES))}")
        return self._c.aggregate(pipeline, *a, **k)


class ReadOnlyDb:
    """A database handle that reads and raises on everything else."""

    def __init__(self, db: Any):
        object.__setattr__(self, "_db", db)
        object.__setattr__(self, "attempts", [])

    def __getitem__(self, name: str) -> ReadOnlyCollection:
        return ReadOnlyCollection(self._db[name], self.attempts)

    def get_collection(self, name: str, *a, **k) -> ReadOnlyCollection:
        if a or k:
            self.attempts.append(f"get_collection({name!r}) with options")
            raise ReadOnlyViolation("read-only: get_collection with options")
        return self[name]

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in DB_BLOCKED:
            self.attempts.append(f"db.{name}")
            raise ReadOnlyViolation(f"read-only: db.{name} is not a read")
        if name in DB_READS:
            return getattr(self._db, name)
        return self[name]

    def __setattr__(self, name: str, value: Any):
        self.attempts.append(f"setting db.{name}")
        raise ReadOnlyViolation(f"read-only: setting db.{name}")


class _NoNetwork:
    """ServerHttpClient's stand-in: any outbound call is an error."""

    calls: List[str] = []

    def __init__(self, *a, **k):
        _NoNetwork.calls.append("ServerHttpClient")
        raise ReadOnlyViolation("no network: an outbound HTTP client was opened")


async def _no_send(*a, **k):
    raise ReadOnlyViolation("no message: a WhatsApp send was attempted")


@contextlib.contextmanager
def read_only(server):
    """The guards, installed on the server module and taken off on the way out:
    the db wrapped, the paid keys blank, no HTTP client and no send."""
    ro = ReadOnlyDb(server.db)
    saved = {k: getattr(server, k) for k in ("db", "QWEN_API_KEY", "LLM_API_KEY", "ServerHttpClient",
                                             "send_whatsapp_message") if hasattr(server, k)}
    try:
        server.db = ro
        server.QWEN_API_KEY = ""
        server.LLM_API_KEY = None
        server.ServerHttpClient = _NoNetwork
        server.send_whatsapp_message = _no_send
        yield ro
    finally:
        for k, v in saved.items():
            setattr(server, k, v)


# ── LOADING ONE JOB ────────────────────────────────────────────────────────

def _today() -> date:
    return datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date()


async def _live_projects(server) -> list:
    return await server.db.projects.find({"is_deleted": {"$ne": True}}).to_list(5000)


def _matches(project: dict, job: str) -> bool:
    words = " ".join(str(project.get(k) or "") for k in ("name", "address")).lower()
    return job.lower().strip() in words or str(project.get("_id")) == job.strip()


async def _people(server, company_id: str, inspections: list, confirmations: dict) -> Tuple[List[str], Dict[str, str]]:
    """(every person name to redact, {reporter name: role words})."""
    from lib import progress_validation as PV
    users = await server.db.users.find({"company_id": server._company_id_filter(company_id)}).to_list(5000)
    role_of = {str(u.get("_id")): u.get("role") for u in users}
    names = [str(u.get(k)) for u in users for k in ("name", "full_name", "email") if u.get(k)]
    roles: Dict[str, str] = {}
    for r in inspections:
        who = str(r.get("reporter_name") or "")
        if who:
            names.append(who)
            role = PV.role_words(role_of.get(str(r.get("reporter_user_id") or "")))
            roles[who] = role if roles.get(who, role) == role else "a person"
        if r.get("inspector_as_said"):
            names.append(str(r["inspector_as_said"]))
    for answers in confirmations.values():
        names += [str(c.get("by_name")) for c in answers if c.get("by_name")]
    return names, roles


async def load_job(server, project: dict, *, today: date, days: int, samples: bool = True) -> Tuple[dict, List[str]]:
    """(the data lib/progress_validation reads, the names to redact). Reads only."""
    from lib import photo_relations, photo_search, progress_report
    from lib import progress_validation as PV
    from lib import work_state as W
    pid, cid = str(project["_id"]), str(project.get("company_id") or "")
    cf = server._company_id_filter(cid)
    start = today - timedelta(days=days - 1)
    now = datetime.now(timezone.utc)
    src = await server._report_rows(project, cid, start, today, now)
    logs = src["logbooks"]
    acts = progress_report._log_activities(logs, start, today)
    db = server.db
    index = await db[server.PHOTO_INDEX].find({"project_id": pid, "kind": "photo"}).to_list(20000)
    spaces, confirmed = await server._photo_place_context(pid)
    inspections = await db[server.INSPECTION_REPORTS].find({"project_id": pid, "company_id": cid}).to_list(5000)
    names, roles = await _people(server, cid, inspections, confirmed)
    data = {
        "job": {"project_id": pid, "company_id": cid, "building_stories": project.get("building_stories")},
        "window": {"start": start, "today": today, "days": days},
        "logs": logs, "acts": acts, "index": index, "log_ids": {str(lg.get("_id")) for lg in logs},
        "spaces": spaces, "confirmations": confirmed,
        "relations": await db[server.PHOTO_RELATIONS].count_documents({"project_id": pid}),
        "relations_enabled": os.environ.get("PHOTO_RELATIONS_ENABLED") == "1",
        "relations_ready": photo_relations.automatic_ready(),
        "inspections": inspections, "dob_rows": src["dob_rows"],
        "schedule": src.get("schedule"),
        "schedule_drafts": await db[server.PROJECT_SCHEDULES].count_documents(
            {"company_id": cf, "project_id": pid, "status": "draft"}),
        "proposed": await db[server.PROPOSED_SEQUENCES].find_one({"_id": f"{cid}:{pid}", "company_id": cf}),
        "prompt_v": photo_search.PROMPT_V, "reread_tries": server.PHOTO_INDEX_TRIES, "samples": [],
    }
    if samples:
        for level in PV.sample_levels(acts):
            got = await server._work_state_answer(project, cid, "drywall", W.level_label(level), today=today)
            text = W.as_text(PV.redact_answer(got["answer"], roles)) if got["ok"] else got["why"]
            data["samples"].append({"work": "drywall", "level": level, "text": PV.redact(text, names)})
    return data, names


# ── THE REPORTS ────────────────────────────────────────────────────────────

async def job_report(server, job: str, *, today: Optional[date] = None, days: int = 90) -> Tuple[int, str]:
    """(exit code, the report). 2: the job did not resolve to exactly one."""
    from lib import progress_validation as PV
    today = today or _today()
    hits = [p for p in await _live_projects(server) if _matches(p, job)]
    if len(hits) != 1:
        return 2, f"{len(hits)} live jobs match {job!r}: ids {[str(p.get('_id')) for p in hits][:20]}"
    data, names = await load_job(server, hits[0], today=today, days=days)
    secs = PV.run(data)
    head = f"PROGRESS VALIDATION  job {data['job']['project_id']}  company {data['job']['company_id']}  today {today}"
    return 0, head + "\n" + PV.render(secs, PV.readiness_for(secs, data), names)


async def all_jobs_report(server, *, today: Optional[date] = None, days: int = 90) -> str:
    """One line of counts per live job, grouped by company, fixture tenants marked."""
    from lib import progress_validation as PV
    today = today or _today()
    lines = []
    for p in await _live_projects(server):
        if not p.get("company_id"):
            continue
        try:
            data, _names = await load_job(server, p, today=today, days=days, samples=False)
        except server.ReportSourceUnavailable:
            continue
        lines.append(PV.coverage_line(data))
    fixtures = await server.test_company_ids()
    return f"PROGRESS COVERAGE  {len(lines)} live jobs  today {today}  (* fixture tenant)\n" + \
        PV.render_coverage(lines, fixtures)


async def _main(a) -> int:
    import server
    with read_only(server) as ro:
        today = date.fromisoformat(a.today) if a.today else None
        if a.all_jobs:
            print(await all_jobs_report(server, today=today, days=a.days))
            code = 0
        else:
            code, text = await job_report(server, a.job, today=today, days=a.days)
            print(text)
        print(f"Writes attempted: {len(ro.attempts)}   outbound calls attempted: {len(_NoNetwork.calls)}")
    return code


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job", nargs="?", default="", help="a job's name, address or id (one live job)")
    ap.add_argument("--all-jobs", action="store_true", help="one line of counts for every live job")
    ap.add_argument("--days", type=int, default=90, help="the window of filed logs read (default 90)")
    ap.add_argument("--today", default="", help="YYYY-MM-DD, for a reproducible run")
    a = ap.parse_args(list(argv) if argv is not None else None)
    if not a.all_jobs and not a.job:
        ap.error('name a job ("588") or pass --all-jobs')
    return asyncio.run(_main(a))


if __name__ == "__main__":
    raise SystemExit(main())
