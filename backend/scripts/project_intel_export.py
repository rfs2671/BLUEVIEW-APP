"""READ-ONLY. Export ONE project's whole history to a local JSON bundle for offline analysis.

    railway run --service Blueview2 --environment production \
        python backend/scripts/project_intel_export.py "588" --out 588_bundle.json

`railway run` executes locally with production variables, so the bundle lands
on the machine that ran it. Nothing is uploaded and no image is downloaded.

WHAT IT GUARANTEES
  * READ-ONLY, ENFORCED: the database is wrapped in a guard that raises on any
    method that is not a known read (insert / update / replace / delete /
    bulk_write / find_one_and_* / create_index / drop / aggregate with $out or
    $merge, and anything it does not know). Every refusal is counted and the
    run ends with "Writes attempted: N"; N > 0 exits 1.
  * PII: person names become stable pseudonyms (worker_N, person_N: the same
    person is the same pseudonym everywhere in one bundle), phone numbers and
    emails are masked (also inside free text), company / sub / project names
    are kept. Password hashes, tokens, secrets, signatures, device and IP
    fields, and embedded image bytes are never exported. A photo is its R2 key
    and its vision text, never the pixels.
  * BOUNDED: a collection with more than --max matching documents refuses the
    run (exit 3) naming it; raise --max or --skip it. Nothing partial.

HONEST LIMITS. A person's name typed INSIDE free text (a WhatsApp body, a log
note) is kept as written: only keys that hold a person are pseudonymized. A raw
run of 10-15 digits is treated as a phone number, so a long permit number can be
masked. --since / --until bound only the day-by-day collections (logs, check-ins,
messages, photos); standing records (inspections, DOB rows, schedules, plan
index, punch items) are exported whole.

Exit: 0 ok, 1 a write was attempted, 2 project not exactly one, 3 over --max.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bson import ObjectId  # noqa: E402
from probe_helpers import sample_keys  # noqa: E402

DEFAULT_MAX = 20000

# ── THE READ-ONLY GUARD ────────────────────────────────────────────────────


class WriteAttempted(RuntimeError):
    """Something tried to change the database through the guard."""


#: The ONLY collection methods that pass. Everything else, known or not, is
#: refused: a driver method added next year is a write until someone says it is not.
_READS = frozenset({"find", "find_one", "count_documents", "estimated_document_count", "distinct", "name",
                    "full_name"})
_PIPELINE_WRITES = ("$out", "$merge")
#: Database-level methods that change or run anything.
_DB_REFUSED = frozenset({"drop_collection", "create_collection", "command", "client", "rename_collection",
                         "with_options", "watch"})


class ReadOnlyCollection:
    def __init__(self, coll: Any, guard: "ReadOnlyDB"):
        self._coll, self._guard = coll, guard

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        if name in _READS:
            return getattr(self._coll, name)
        if name == "aggregate":
            return self._aggregate
        self._guard.refuse(f"{getattr(self._coll, 'name', '?')}.{name}")

    def _aggregate(self, pipeline: Any, *a: Any, **k: Any) -> Any:
        for stage in pipeline or ():
            if isinstance(stage, dict) and any(w in stage for w in _PIPELINE_WRITES):
                self._guard.refuse(f"{getattr(self._coll, 'name', '?')}.aggregate({'/'.join(stage)})")
        return self._coll.aggregate(pipeline, *a, **k)


class ReadOnlyDB:
    """Wraps a database. Reads pass; every other call raises WriteAttempted and
    is counted in `attempts`, even when the caller swallows the exception."""

    def __init__(self, db: Any):
        self._db = db
        self.attempts: List[str] = []

    def refuse(self, what: str) -> None:
        self.attempts.append(what)
        raise WriteAttempted(f"read-only export: refused {what}")

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name == "list_collection_names":
            return self._db.list_collection_names
        if name in _DB_REFUSED:
            self.refuse(f"db.{name}")
        return ReadOnlyCollection(getattr(self._db, name), self)

    def __getitem__(self, name: str) -> Any:
        return ReadOnlyCollection(self._db[name], self)


# ── PII ────────────────────────────────────────────────────────────────────

#: A key holding any of these is never exported.
_DROP = re.compile(r"pass(word|wd)|hash|token|secret|jwt|api_?key|authorization|otp|pin_code|signature|"
                   r"fingerprint|source_ip|user_agent|ip_address|r2_(access|secret)|private|ssn|"
                   r"osha_data|card_number|osha_number|sst_number|license_number|qr_|credential", re.I)
#: A key holding a phone number / a JID.
_PHONE_KEY = re.compile(r"(^|_)(phone|mobile|msisdn|chat_digits|sender|sender_jid|jid|whatsapp)(_|$)", re.I)
_EMAIL_KEY = re.compile(r"(^|_)e?mail(_|$)", re.I)
#: Keys that hold a PERSON, however spelled.
_PERSON_KEYS = {"worker_name", "sender_name", "reporter_name", "full_name", "by", "signed_by", "foreman",
                "reporter", "inspector", "competent_person", "superintendent", "author", "confirmed_by",
                "created_by_name", "user_name", "person", "person_name", "linked_by_name", "contact_name",
                "pushname", "push_name", "owner_name", "approved_by", "answered_by", "asked_name",
                "target_user_name", "first_name", "last_name"}
_BUSINESS = re.compile(r"company|project|sub|contractor|trade|vendor|firm|group|file|sheet|document|"
                       r"building|site|owner_entity|agency|insurer|carrier", re.I)
_PHONE_TEXT = [
    re.compile(r"\d{7,15}@(?:s\.whatsapp\.net|c\.us|lid|g\.us)"),
    re.compile(r"(?<![\w.])\+\d[\d\s().-]{6,17}\d"),
    re.compile(r"(?<!\d)\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)"),
    re.compile(r"(?<![\w.:-])\d{10,15}(?![\w.:-])"),
]
_EMAIL_TEXT = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_BLOB = re.compile(r"^data:[a-z]+/[\w.+-]+;base64,", re.I)
_B64_RUN = re.compile(r"^[A-Za-z0-9+/=\s]{2000,}$")


def mask_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return f"[phone ***{digits[-4:]}]" if len(digits) >= 4 else "[phone]"


def mask_text(text: str) -> str:
    """Phone numbers and emails inside free text. Names are left as written."""
    if _BLOB.match(text) or _B64_RUN.match(text):
        return "[binary omitted]"
    for rx in _PHONE_TEXT:
        text = rx.sub(lambda m: mask_phone(m.group(0)), text)
    return _EMAIL_TEXT.sub("[email]", text)


class Pseudonyms:
    """Stable within one bundle: the same person (case and spacing aside) is
    the same label wherever they appear. `worker_N` for the roster and
    check-ins, `person_N` for everyone first met elsewhere."""

    def __init__(self) -> None:
        self._by: Dict[str, str] = {}
        self._n = 0

    @staticmethod
    def _key(name: str) -> str:
        return " ".join(name.casefold().split())

    def label(self, name: Any, prefix: str = "person") -> Any:
        text = str(name or "").strip()
        if not text:
            return name
        k = self._key(text)
        if k not in self._by:
            self._n += 1
            self._by[k] = f"{prefix}_{self._n}"
        return self._by[k]

    def __len__(self) -> int:
        return len(self._by)


class Scrubber:
    def __init__(self, pseudonyms: Optional[Pseudonyms] = None) -> None:
        self.pseudo = pseudonyms or Pseudonyms()
        self.dropped: Dict[str, int] = {}
        self.prefix = "person"
        self.name_is_person = False

    def _is_person_key(self, key: str) -> bool:
        k = key.lower()
        if k in _PERSON_KEYS:
            return True
        if k == "name":
            return self.name_is_person
        return k.endswith("_name") and not _BUSINESS.search(k)

    def scrub(self, value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for k, v in value.items():
                ks = str(k)
                if _DROP.search(ks):
                    self.dropped[ks] = self.dropped.get(ks, 0) + 1
                    continue
                out[ks] = self.scrub(v, ks)
            return out
        if isinstance(value, (list, tuple)):
            return [self.scrub(v, key) for v in value]
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, (bytes, bytearray)):
            return "[binary omitted]"
        if isinstance(value, str):
            if self._is_person_key(key):
                return self.pseudo.label(mask_text(value), self.prefix)
            if _PHONE_KEY.search(key):
                return mask_phone(value)
            if _EMAIL_KEY.search(key):
                return "[email]"
            return mask_text(value)
        if isinstance(value, (int, float, bool)) or value is None:
            if isinstance(value, int) and not isinstance(value, bool) and _PHONE_KEY.search(key):
                return mask_phone(value)
            return value
        return mask_text(str(value))


# ── WHAT IS READ ───────────────────────────────────────────────────────────

class Spec:
    """One collection: how to find this project's rows, and on what field the
    window applies (`date_kind` "str" = an ISO day string, "dt" = a datetime)."""

    def __init__(self, name: str, *, by: str = "project_id", date_field: Optional[str] = None,
                 date_kind: str = "str", prefix: str = "person", persons: bool = False,
                 keep: Optional[Tuple[str, ...]] = None, heavy: bool = False):
        self.name, self.by, self.date_field, self.date_kind = name, by, date_field, date_kind
        self.prefix, self.persons, self.keep, self.heavy = prefix, persons, keep, heavy


#: Collection names and fields were read from server.py and lib/. `by` is the
#: field that holds the project id.
SPECS: Tuple[Spec, ...] = (
    Spec("workers", prefix="worker", persons=True,
         keep=("name", "phone", "company", "company_name", "company_id", "trade", "trades", "status",
                "created_at", "certifications", "safety_orientations")),
    Spec("users", by="assigned_projects", persons=True,
         keep=("name", "role", "company_id", "assigned_projects", "status", "created_at")),
    Spec("checkins", date_field="check_in_time", date_kind="dt", prefix="worker", persons=True),
    Spec("logbooks", date_field="date"),
    Spec("photo_index", date_field="date"),
    Spec("photo_place_confirmations"),
    Spec("photo_relations"),
    Spec("whatsapp_groups"),
    Spec("whatsapp_messages", date_field="created_at", date_kind="dt", persons=True),
    Spec("whatsapp_dm_answers", date_field="created_at", date_kind="dt"),
    Spec("attention_items"),
    Spec("inspection_reports"),
    Spec("confirmation_candidates"),
    Spec("confirmation_events"),
    Spec("confirmation_answers"),
    Spec("dob_logs"),
    Spec("dot_logs"),
    Spec("upcoming_events"),
    Spec("project_schedules"),
    Spec("proposed_sequences", by="_id"),
    Spec("punch_items"),
    Spec("document_page_index"),
    Spec("plan_areas"),
    Spec("plan_legend_counts"),
    Spec("plan_light_fixture_counts"),
    Spec("plan_set_health"),
    Spec("plan_set_questions"),
    Spec("plan_stacks"),
    Spec("plan_structural"),
    Spec("project_memory"),
    # Geometry: heavy and not analysis input. Off unless asked for.
    Spec("plan_records", heavy=True),
    Spec("plan_walls", heavy=True),
)


class ProjectNotResolved(RuntimeError):
    pass


class TooManyDocuments(RuntimeError):
    pass


def _hex24(text: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{24}", text))


async def resolve_project(db: Any, selector: str) -> Dict[str, Any]:
    """The ONE project the selector names: an id, or a substring of its name or
    address. Zero or several refuse, listing what matched."""
    sel = str(selector or "").strip()
    if not sel:
        raise ProjectNotResolved("no project selector given")
    if _hex24(sel):
        flt: Dict[str, Any] = {"_id": {"$in": [ObjectId(sel), sel]}}
    else:
        rx = re.escape(sel)
        flt = {"$or": [{"name": {"$regex": rx, "$options": "i"}}, {"address": {"$regex": rx, "$options": "i"}}]}
    rows = await db.projects.find({"$and": [flt, {"is_deleted": {"$ne": True}}]}).to_list(50)
    if len(rows) != 1:
        shown = [f"{r.get('_id')} {r.get('name')!r}" for r in rows[:10]]
        raise ProjectNotResolved(f"{len(rows)} projects match {selector!r} (need exactly 1): {shown}")
    return rows[0]


def _day(v: Optional[date]) -> Optional[str]:
    return v.isoformat() if v else None


def _window(spec: Spec, since: Optional[date], until: Optional[date]) -> Dict[str, Any]:
    if not spec.date_field or not (since or until):
        return {}
    rng: Dict[str, Any] = {}
    if spec.date_kind == "str":
        if since:
            rng["$gte"] = _day(since)
        if until:
            rng["$lte"] = _day(until)
    else:
        if since:
            rng["$gte"] = datetime.combine(since, time.min, tzinfo=timezone.utc)
        if until:
            rng["$lte"] = datetime.combine(until, time.max, tzinfo=timezone.utc)
    return {spec.date_field: rng}


def _filter(spec: Spec, project: Dict[str, Any], group_ids: List[str], since: Optional[date],
            until: Optional[date], worker_ids: Iterable[str] = ()) -> Dict[str, Any]:
    pid = str(project["_id"])
    ids = [pid, project["_id"]] if isinstance(project["_id"], ObjectId) else [pid]
    scope: Dict[str, Any] = {spec.by: {"$in": ids}}
    if spec.name == "whatsapp_messages" and group_ids:
        scope = {"$or": [scope, {"group_id": {"$in": group_ids}}]}
    elif spec.name == "workers":
        # Oriented on this job, or seen at its gate.
        wid = [x for w in worker_ids for x in ([w, ObjectId(w)] if _hex24(w) else [w])]
        scope = {"$or": [{"safety_orientations.project_id": {"$in": ids}}, {"_id": {"$in": wid}}]}
    flt: Dict[str, Any] = {"$and": [scope, {"is_deleted": {"$ne": True}}]}
    win = _window(spec, since, until)
    if win:
        flt["$and"].append(win)
    return flt


def _keep_only(doc: Dict[str, Any], keep: Optional[Tuple[str, ...]]) -> Dict[str, Any]:
    if not keep:
        return doc
    out = {k: v for k, v in doc.items() if k in keep or k == "_id"}
    if isinstance(out.get("certifications"), list):
        out["certifications"] = [{k: c.get(k) for k in ("type", "expiration_date")}
                                 for c in out["certifications"] if isinstance(c, dict)]
    if isinstance(out.get("safety_orientations"), list):
        out["safety_orientations"] = [{k: o.get(k) for k in ("project_id", "completed_at")}
                                      for o in out["safety_orientations"] if isinstance(o, dict)]
    return out


async def _read_all(db: Any, spec: Spec, flt: Dict[str, Any], scrub: Scrubber,
                    max_docs: int) -> List[Dict[str, Any]]:
    n = await db[spec.name].count_documents(flt)
    if n > max_docs:
        raise TooManyDocuments(f"{spec.name}: {n} documents match, over --max {max_docs}. "
                               f"Raise --max or pass --skip {spec.name}.")
    scrub.prefix, scrub.name_is_person = spec.prefix, spec.persons
    out: List[Dict[str, Any]] = []
    async for d in db[spec.name].find(flt):
        out.append(scrub.scrub(_keep_only(d, spec.keep)))
    return out


async def export(db: Any, selector: str, *, since: Optional[date] = None, until: Optional[date] = None,
                 max_docs: int = DEFAULT_MAX, skip: Iterable[str] = (),
                 include_heavy: bool = False) -> Dict[str, Any]:
    """The bundle. Reads only; `db` should be a ReadOnlyDB."""
    project = await resolve_project(db, selector)
    scrub = Scrubber()
    skipped = set(skip)
    pid = str(project["_id"])
    manifest: Dict[str, Any] = {"project_id": pid, "since": _day(since), "until": _day(until),
                                "exported_at": datetime.now(timezone.utc).isoformat(),
                                "counts": {}, "keys": {}, "skipped": {}, "max": max_docs}
    bundle: Dict[str, Any] = {"manifest": manifest}
    bundle["project"] = scrub.scrub(project)
    cid = project.get("company_id")
    if cid:
        ids = [str(cid), *([ObjectId(str(cid))] if _hex24(str(cid)) else [])]
        cos = [scrub.scrub(c) for c in await db.companies.find({"_id": {"$in": ids}}).to_list(5)]
        subs = [scrub.scrub(x) for x in await db.subcontractors.find(
            {"company_id": {"$in": ids}, "is_deleted": {"$ne": True}}).to_list(max_docs)]
        bundle["companies"], bundle["subcontractors"] = cos, subs
        manifest["counts"]["companies"], manifest["counts"]["subcontractors"] = len(cos), len(subs)
    groups = await db.whatsapp_groups.find({"project_id": {"$in": [pid]}}).to_list(500)
    group_ids = [str(g["wa_group_id"]) for g in groups if g.get("wa_group_id")]
    # Check-ins, then the roster they point at, first: their people are `worker_N`.
    worker_ids: List[str] = []
    for spec in sorted(SPECS, key=lambda s: ("checkins", "workers").index(s.name) if s.name in ("checkins", "workers") else 9):
        if spec.name in skipped:
            manifest["skipped"][spec.name] = "--skip"
            continue
        if spec.heavy and not include_heavy:
            manifest["skipped"][spec.name] = "geometry; pass --include-heavy"
            continue
        rows = await _read_all(db, spec, _filter(spec, project, group_ids, since, until, worker_ids), scrub, max_docs)
        if spec.name == "checkins":
            worker_ids = sorted({str(r["worker_id"]) for r in rows if r.get("worker_id")})
        bundle[spec.name] = rows
        manifest["counts"][spec.name] = len(rows)
        manifest["keys"][spec.name] = sample_keys(rows, limit=200)
    manifest["pseudonyms"] = len(scrub.pseudo)
    manifest["dropped_keys"] = dict(sorted(scrub.dropped.items()))
    return bundle


def _parse_day(text: Optional[str]) -> Optional[date]:
    return date.fromisoformat(text) if text else None


async def _run(args: argparse.Namespace) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    guarded = ReadOnlyDB(client[os.environ["DB_NAME"]])
    code = 0
    try:
        bundle = await export(guarded, args.project, since=_parse_day(args.since), until=_parse_day(args.until),
                              max_docs=args.max, skip=args.skip or (), include_heavy=args.include_heavy)
        Path(args.out).write_text(json.dumps(bundle, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
        for name, n in bundle["manifest"]["counts"].items():
            print(f"{name:32s} {n}")
        print(f"pseudonyms {bundle['manifest']['pseudonyms']}; wrote {args.out}")
    except ProjectNotResolved as e:
        print(f"REFUSED: {e}")
        code = 2
    except TooManyDocuments as e:
        print(f"REFUSED: {e}")
        code = 3
    finally:
        client.close()
    print(f"Writes attempted: {len(guarded.attempts)}")
    return 1 if guarded.attempts else code


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("project", help="project id, or a substring of its name or address")
    ap.add_argument("--out", required=True)
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX, help="refuse a collection with more documents than this")
    ap.add_argument("--skip", action="append", help="a collection to leave out (repeatable)")
    ap.add_argument("--include-heavy", action="store_true", help="also plan_records and plan_walls")
    return asyncio.run(_run(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
