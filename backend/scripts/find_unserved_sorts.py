"""Find Mongo sorts that no index in this repo can serve.

TWO PRODUCTION 500s IN ONE DAY is what this exists for. Both were the same
shape, and neither had a code change to blame:

  * `GET /api/workers` — sorted `workers` by `name` inside a company. No index
    led with (company_id, name), so Mongo pulled the matched set into memory to
    sort it. Worker documents carry `osha_card_image` and `selfie_image` as
    inline base64, so the matched set crossed 32MB and the endpoint began
    returning `OperationFailure ... Sort exceeded memory limit of 33554432
    bytes, but did not opt in to external sorting` (code 292).
  * `GET /api/logbooks/project/{id}/submitted` — sorted `logbooks` by `date`
    under an equality match on (project_id, status). The nearest index was
    (project_id, log_type, date), whose second key `log_type` is not pinned by
    that filter, so the index could not deliver `date` in order. Logbook
    documents carry photo base64 under `data.activities[].photos[]`. It failed
    in front of a DOB inspector.

THE SHAPE, which is the search pattern:

  (a) a sort on a field that no index can deliver in order after the query's
      equality predicates — the Equality-Sort-Range rule: an index serves the
      sort only if every key BEFORE the sort key is pinned by an equality
      predicate in that query's filter;
  (b) on a collection whose documents can carry inline base64;
  (c) so the matched set grows past 32MB with ordinary data accumulation and
      the endpoint dies. Silently fine for months, then fatal.

(a) alone is a slow query. (a) AND (b) is an outage waiting on a row count.
That is why findings are ranked by (b) and not by (a).

HOW EQUALITY IS DECIDED, and it is deliberately strict:

  * a bare constant (`{"project_id": project_id}`) or `{"$eq": ...}` pins a key.
  * EVERYTHING ELSE DOES NOT — `$ne`, `$in`, `$gte`, `$exists`, `$regex`, and
    any field that only appears inside `$or`. `$ne` is the one that matters
    here: `is_deleted: {"$ne": True}` reads like a filter and is not one. It is
    a range scan over a two-valued field, and an index key placed between the
    equality prefix and the sort key destroys the very ordering the sort needs.
    This is why `workers_by_company_name` deliberately omits it (server.py
    ~38452), and the same reasoning applies to every index this sweep proposes.
  * A FIELD ADDED CONDITIONALLY IS NOT AN EQUALITY PIN. `query["status"] = s`
    inside an `if` means the endpoint also runs WITHOUT it, and the unfiltered
    call is the one that matches enough documents to blow the 32MB budget. The
    verdict is computed from the unconditional filter only; the conditional
    fields are reported beside it so a reader can see the narrower shape too.

WHAT IT READS. `backend/server.py`, `backend/lib/`, `backend/scripts/`. Index
declarations come from the same sources — `db.<coll>.create_index(...)`,
`_ensure_index_resilient(...)` (server.py ~38380-38492 and the blocks after
it), and the `*_INDEXES` spec tuples in `lib/logbook/schema.py` and
`lib/statistical_engine/schema.py` that server.py loops over at startup.

INDEXES CREATED BY HAND IN ATLAS ARE INVISIBLE TO THIS, AND THAT IS THE POINT.
The logbooks index that stopped the second outage was created in the Atlas UI
with no deploy. It exists on exactly one cluster, is not in version control,
and will not exist on the next environment anyone builds. If this sweep reports
a sort that someone "already fixed", the fix is not in the repo.

LIMITS, stated because a sweep that looks exhaustive and is not is worse than
none:

  * Cursor `.sort()` only. `$sort` inside an aggregate pipeline is COUNTED and
    reported as out of scope, never silently dropped.
  * Filters must be resolvable to literal keys within the enclosing function. A
    filter assembled somewhere this pass cannot follow is reported as SKIPPED,
    with the file and line. It is never assumed safe.
  * `paginated_query` (server.py ~1366) takes the sort from its CALLER, so the
    helper body itself is skipped by name and every call site is resolved
    instead.
  * It reasons about index KEYS, not about whether Mongo's planner would in
    fact pick that index. An index it says can serve the sort might still lose
    to a different plan. The direction it is wrong in is the safe one: it
    reports too much, not too little.

Run:  python backend/scripts/find_unserved_sorts.py [--all] [--json]

  --all   include collections that cannot hold base64 (slow-query candidates,
          not outage candidates).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

BACKEND = Path(__file__).resolve().parent.parent

# The paths this sweep is responsible for.
SCAN_ROOTS = ("server.py", "lib", "scripts")
SKIP_DIRS = {"__pycache__", "tests", "migrations", "docs"}

# Names bound to the Motor database handle. `db_` is the parameter name the
# lib-style helpers take (latest_esra_consent, superintendent_projects_for);
# leaving it out silently dropped every sort in those functions.
DB_NAMES = {"db", "database", "db_", "_db", "mongo_db"}

# The fields that make a collection dangerous. A document holding any of these
# is measured in hundreds of kilobytes, so a few hundred of them is the 32MB
# in-memory sort budget. Sources: the photo pipeline (server.py ~290-460), the
# worker card/selfie writes (~13100), the CP signature block, and the document
# annotation screenshot (~30635, a full JPEG data URL written straight onto the
# document).
BASE64_FIELDS = {
    "base64",
    "thumb_base64",
    "worker_signature",
    "cp_signature",
    "osha_card_image",
    "signature",
    "selfie_image",
    "screenshot",
}

# Collections whose base64 arrives through a write this pass cannot read.
# Each entry must say which writer, and why it is invisible.
BASE64_BY_HAND = {
    # Photos live at data.activities[<i>].photos[<j>].base64 — an f-string
    # path built at runtime in _purge_finalized_photo_base64 / _enhance_one,
    # so no literal key names it. The detected top-level `cp_signature` write
    # would catch logbooks anyway; this entry records the bigger payload.
    "logbooks": "data.activities[].photos[].base64 via runtime f-string paths",
}

# A sort argument that is one of these is a Python list sort, not a cursor.
PYTHON_SORT_KWARGS = {"key", "reverse"}

# Functions whose sort is chosen by the caller, so the body is not a finding.
SORT_HELPERS = {"paginated_query"}


# ── AST helpers ─────────────────────────────────────────────────────────────

def _const_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _const_int(node: ast.AST) -> Optional[int]:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant)):
        return -node.operand.value
    return None


# Every module-level `NAME = "literal"` in the scanned tree, so `db[X.CONST]`
# resolves across modules. Filled by _load_globals() before the first sweep.
GLOBAL_CONSTS: Dict[str, str] = {}
# Every module-level `NAME = {"a", "b"}` (set/frozenset/tuple/list of strings),
# used to expand a client-chosen sort field into the values it may take.
GLOBAL_STR_SETS: Dict[str, List[str]] = {}
# Module-level dict literals, so `query = dict(ACTIVE_PROJECT_FILTER)` resolves.
GLOBAL_DICTS: Dict[str, ast.Dict] = {}
# Module-level functions whose only job is to return a filter dict, so
# `query = _build_eligibility_query(now)` resolves.
GLOBAL_FILTER_FNS: Dict[str, ast.Dict] = {}
# `coll = db.dob_logs` / `getattr(db, "daily_logs", None)` aliases, per file.
COLLECTION_ALIASES: Dict[str, str] = {}


def _base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def collection_of(node: ast.AST, consts: Dict[str, str]) -> str:
    """`db.workers` / `db["workers"]` / `db[SOME_CONST]` -> 'workers'."""
    if isinstance(node, ast.Attribute) and _base_name(node.value) in DB_NAMES:
        return node.attr
    if isinstance(node, ast.Subscript) and _base_name(node.value) in DB_NAMES:
        lit = _const_str(node.slice)
        if lit:
            return lit
        # `db[SOME_CONST]` and `db[other_module.SOME_CONST]`. The cross-module
        # form is how the notifications inbox and the statistical-engine
        # collections are named, so without it those sorts vanish.
        key = _base_name(node.slice)
        return consts.get(key) or GLOBAL_CONSTS.get(key, "")
    if isinstance(node, ast.Name):
        return COLLECTION_ALIASES.get(node.id, "")
    return ""


def _tuple_pair(node: ast.AST) -> Optional[Tuple[str, int]]:
    if not isinstance(node, (ast.Tuple, ast.List)) or len(node.elts) != 2:
        return None
    field, direction = _const_str(node.elts[0]), _const_int(node.elts[1])
    if field is None or direction is None:
        return None
    return field, direction


def key_list(node: ast.AST) -> Optional[List[Tuple[str, int]]]:
    """A Mongo key spec: "field" | [("a", 1), ("b", -1)] -> pairs, or None."""
    lit = _const_str(node)
    if lit is not None:
        return [(lit, 1)]
    if isinstance(node, (ast.List, ast.Tuple)):
        pair = _tuple_pair(node)
        if pair and not isinstance(node.elts[0], (ast.Tuple, ast.List)):
            return [pair]
        out: List[Tuple[str, int]] = []
        for elt in node.elts:
            pair = _tuple_pair(elt)
            if pair is None:
                return None
            out.append(pair)
        return out or None
    return None


# ── filters: which fields are pinned by equality ────────────────────────────

def _is_equality_value(node: ast.AST) -> bool:
    """True when the value pins the field to one value.

    A dict value is an operator expression. Only `$eq` pins; `$ne`, `$in`,
    `$gt(e)`, `$lt(e)`, `$exists`, `$regex`, `$nin` are ranges or negations and
    leave the key unusable as an index prefix ahead of a sort.
    """
    if not isinstance(node, ast.Dict):
        return True
    keys = [_const_str(k) for k in node.keys]
    if any(k is None for k in keys):
        return False
    return all(k == "$eq" for k in keys)


def filter_fields(node: ast.AST,
                  locals_: Optional[Dict[str, ast.Dict]] = None
                  ) -> Tuple[Set[str], Set[str], bool]:
    """(equality fields, non-equality fields, fully_parsed) for a filter dict.

    `$and` merges — every branch applies at once. `$or` does NOT: a field that
    only appears inside `$or` is not pinned, because the other branch does not
    pin it, and Mongo cannot walk one index in order across both.
    """
    eq: Set[str] = set()
    other: Set[str] = set()
    ok = True
    if not isinstance(node, ast.Dict):
        return eq, other, False
    for k, v in zip(node.keys, node.values):
        if k is None:                      # {**spread}
            spread = (locals_ or {}).get(_base_name(v))                 or GLOBAL_DICTS.get(_base_name(v))
            if spread is None:
                ok = False
                continue
            s_eq, s_other, s_ok = filter_fields(spread, locals_)
            eq |= s_eq
            other |= s_other
            ok = ok and s_ok
            continue
        name = _const_str(k)
        if name is None:
            ok = False
            continue
        if name == "$and":
            branches = v.elts if isinstance(v, ast.List) else [v]
            for b in branches:
                b_eq, b_other, b_ok = filter_fields(b, locals_)
                eq |= b_eq
                other |= b_other
                ok = ok and b_ok
            continue
        if name in {"$or", "$nor"}:
            # A BRANCH THIS PASS CANNOT READ DOES NOT MAKE THE FILTER
            # UNREADABLE. `$or` never contributes an equality pin — no single
            # index prefix satisfies every branch at once — so an opaque `$or`
            # (`"$or": _SIGNATURE_HAS_INK_CLAUSES`) leaves the equality set,
            # and therefore the verdict, exactly where it was. Marking these
            # unparsed hid four real logbooks/checkins findings behind
            # "could not parse", which is the failure mode this file exists to
            # avoid.
            branches = v.elts if isinstance(v, ast.List) else [v]
            for b in branches:
                b_eq, b_other, _b_ok = filter_fields(b, locals_)
                other |= b_eq | b_other
            continue
        if name.startswith("$"):
            other.add(name)
            continue
        (eq if _is_equality_value(v) else other).add(name)
    return eq, other, ok


def _as_dict(node: Optional[ast.AST]) -> Optional[ast.Dict]:
    """See through the three ways a filter dict is handed around.

        query = dict(ACTIVE_PROJECT_FILTER)      # copy of a module constant
        query = {**ACTIVE_PROJECT_FILTER}        # same, spread form
        query = _build_eligibility_query(now)    # a builder that returns one

    Each of these read as "never assigned a dict literal" and took a whole
    endpoint out of the sweep.
    """
    if node is None or isinstance(node, ast.Dict):
        return node
    if isinstance(node, ast.Call):
        fn = _base_name(node.func)
        if fn in {"dict", "copy", "deepcopy"} and node.args:
            return GLOBAL_DICTS.get(_base_name(node.args[0]))
        if fn == "copy" and isinstance(node.func, ast.Attribute):
            return GLOBAL_DICTS.get(_base_name(node.func.value))
        return GLOBAL_FILTER_FNS.get(fn)
    return None


class FilterResolver:
    """Resolves a filter argument to field sets within one function body.

    Most call sites pass a NAME, not a literal:

        query = {"project_id": pid, "is_deleted": {"$ne": True}}
        if status:
            query["status"] = status
        rows = await db.logbooks.find(query).sort("date", -1)

    The base dict is the UNCONDITIONAL filter and is what the verdict uses. The
    subscript assignments are collected separately, because a field added under
    an `if` is absent on the call that matches the most documents — which is
    the call that runs out of sort memory.
    """

    def __init__(self, fn: ast.AST):
        self.base_eq: Dict[str, Set[str]] = {}
        self.base_other: Dict[str, Set[str]] = {}
        self.base_ok: Dict[str, bool] = {}
        self.conditional: Dict[str, Set[str]] = {}
        self.reassigned: Set[str] = set()
        # The raw dict nodes, so `{**match, "project_id": pid}` can resolve
        # `match` when it is a local rather than a module constant.
        self.dicts: Dict[str, ast.Dict] = {}
        for node in ast.walk(fn):
            tgt = val = None
            if isinstance(node, ast.AnnAssign) and node.value is not None:
                tgt, val = node.target, node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt, val = node.targets[0], node.value
            val = _as_dict(val) if val is not None else None
            if isinstance(tgt, ast.Name) and isinstance(val, ast.Dict):
                self.dicts.setdefault(tgt.id, val)
        for node in ast.walk(fn):
            # `query: Dict[str, Any] = {}` is an AnnAssign, not an Assign, and
            # it is the house style for every filter built incrementally. Six
            # endpoints read as "filter name never assigned a dict literal"
            # until this was added.
            if isinstance(node, ast.AnnAssign) and node.value is not None:
                tgt, val = node.target, node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt, val = node.targets[0], node.value
            else:
                continue
            val = _as_dict(val) or val
            if isinstance(tgt, ast.Name) and isinstance(val, ast.Dict):
                if tgt.id in self.base_eq:
                    self.reassigned.add(tgt.id)
                eq, other, ok = filter_fields(val, self.dicts)
                self.base_eq.setdefault(tgt.id, set()).update(eq)
                self.base_other.setdefault(tgt.id, set()).update(other)
                self.base_ok[tgt.id] = self.base_ok.get(tgt.id, True) and ok
            elif isinstance(tgt, ast.Name) and not isinstance(val, ast.Dict):
                # Rebound to something we cannot read (a call, a comprehension).
                if tgt.id in self.base_eq:
                    self.base_ok[tgt.id] = False
            elif isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name):
                name = _const_str(tgt.slice)
                if name is None:
                    self.base_ok[tgt.value.id] = False
                elif not name.startswith("$"):
                    cond = self.conditional.setdefault(tgt.value.id, set())
                    if _is_equality_value(val):
                        cond.add(name)
                    else:
                        cond.add(name + " (non-equality)")

    def resolve(self, node: Optional[ast.AST]):
        """-> (equality, non-equality, conditional, parsed, how)"""
        if node is None:
            return set(), set(), set(), True, "no filter (full scan)"
        resolved = _as_dict(node)
        if isinstance(resolved, ast.Dict):
            eq, other, ok = filter_fields(resolved, self.dicts)
            how = "inline literal" if isinstance(node, ast.Dict) else "resolved builder/constant"
            return eq, other, set(), ok, how
        if isinstance(node, ast.Name):
            if node.id not in self.base_eq:
                return set(), set(), set(), False, f"filter name `{node.id}` never assigned a dict literal here"
            return (
                set(self.base_eq[node.id]),
                set(self.base_other.get(node.id, set())),
                set(self.conditional.get(node.id, set())),
                self.base_ok.get(node.id, True),
                f"local `{node.id}`",
            )
        return set(), set(), set(), False, f"filter is {type(node).__name__}, not a literal or local"


# ── index declarations ──────────────────────────────────────────────────────

def _module_consts(tree: ast.Module) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            lit = _const_str(node.value)
            if lit is not None:
                out[node.targets[0].id] = lit
    return out


def _spec_tuples(tree: ast.Module) -> Dict[str, List[List[Tuple[str, int]]]]:
    """Module-level `X_INDEXES = ({"keys": [...], "name": ...}, ...)`."""
    out: Dict[str, List[List[Tuple[str, int]]]] = {}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            continue
        specs: List[List[Tuple[str, int]]] = []
        for elt in node.value.elts:
            if isinstance(elt, ast.Dict):
                for k, v in zip(elt.keys, elt.values):
                    if _const_str(k) == "keys":
                        keys = key_list(v)
                        if keys:
                            specs.append(keys)
            # The other shape in this repo: `("index_name", [("a", 1), ...])`,
            # used by FILING_JOBS_INDEXES. Missing it made every filing_jobs
            # index invisible, which would have reported four served sorts as
            # unserved — a ratchet's false positives are how it loses its
            # readers.
            elif isinstance(elt, (ast.Tuple, ast.List)) and len(elt.elts) == 2:
                if _const_str(elt.elts[0]) is not None:
                    keys = key_list(elt.elts[1])
                    if keys:
                        specs.append(keys)
        if specs:
            out[node.targets[0].id] = specs
    return out


def _spec_bundles(tree: ast.Module, consts: Dict[str, str],
                  specs: Dict[str, List[List[Tuple[str, int]]]]):
    """`ALL_X_SPECS = ((COLL_CONST, X_INDEXES), ...)` -> (collection, keys)."""
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, (ast.Tuple, ast.List))):
            continue
        for elt in node.value.elts:
            if not (isinstance(elt, (ast.Tuple, ast.List)) and len(elt.elts) == 2):
                continue
            coll_node, specs_node = elt.elts
            coll = _const_str(coll_node) or consts.get(_base_name(coll_node), "")
            spec_name = _base_name(specs_node)
            if coll and spec_name in specs:
                for keys in specs[spec_name]:
                    yield coll, keys


def declared_indexes() -> Tuple[Dict[str, List[List[Tuple[str, int]]]], List[str]]:
    """Every index key spec this repo declares, plus what could not be read."""
    out: Dict[str, List[List[Tuple[str, int]]]] = {}
    unparsed: List[str] = []
    loop_resolved: Set[str] = set()

    # Pass 0: collect EVERY module's index spec tuples before looking at any
    # loop. server.py is scanned first and loops over
    # `_logbook.LOGBOOK_ENTRIES_INDEXES`, which is defined in a file scanned
    # later — resolving loops in file order silently lost those four indexes.
    all_specs: Dict[str, List[List[Tuple[str, int]]]] = {}
    parsed: List[Tuple[Path, ast.Module, Dict[str, str],
                       Dict[str, List[List[Tuple[str, int]]]]]] = []
    for rel, tree in source_files():
        consts = _module_consts(tree)
        specs = _spec_tuples(tree)
        all_specs.update(specs)
        parsed.append((rel, tree, consts, specs))

    # Pass 1: spec tuples and the loops that create them.
    for rel, tree, consts, specs in parsed:
        for coll, keys in _spec_bundles(tree, consts, specs):
            out.setdefault(coll, []).append(keys)
        # `for s in LOGBOOK_ENTRIES_INDEXES: _ensure(db.logbook_entries, ...)`
        # and `for name, keys in FILING_JOBS_INDEXES: db.x.create_index(keys)`.
        for node in ast.walk(tree):
            if not isinstance(node, ast.For):
                continue
            it_name = _base_name(node.iter)
            spec_keys = all_specs.get(it_name)
            if not spec_keys:
                continue
            colls: Set[str] = set()
            for c in ast.walk(node):
                if not isinstance(c, ast.Call):
                    continue
                if isinstance(c.func, ast.Attribute):
                    colls.add(collection_of(c.func.value, consts))
                colls |= {collection_of(a, consts) for a in c.args}
                if (isinstance(c.func, ast.Attribute) and c.func.attr == "create_index") \
                        or _base_name(c.func) == "_ensure_index_resilient":
                    # Its key spec is the loop variable; pass 2 must not report
                    # it as unreadable when pass 1 has already resolved it.
                    loop_resolved.add(f"{rel.as_posix()}:{c.lineno}")
            for coll in colls - {""}:
                for keys in spec_keys:
                    out.setdefault(coll, []).append(keys)

    # Pass 2: direct declarations.
    for rel, tree, consts, _specs in parsed:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            where = f"{rel.as_posix()}:{node.lineno}"
            if where in loop_resolved:
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "create_index":
                coll = collection_of(node.func.value, consts)
                if not coll:
                    continue
                keys = key_list(node.args[0]) if node.args else None
                if keys is None:
                    unparsed.append(f"create_index at {where}: key spec not literal")
                    continue
                out.setdefault(coll, []).append(keys)
            elif _base_name(node.func) == "_ensure_index_resilient":
                coll = collection_of(node.args[0], consts) if node.args else ""
                keys_node = next((kw.value for kw in node.keywords
                                  if kw.arg == "keys"), None)
                if not coll:
                    # The loop form; already handled in pass 1.
                    continue
                keys = key_list(keys_node) if keys_node is not None else None
                if keys is None:
                    unparsed.append(f"_ensure_index_resilient at {where}: key spec not literal")
                    continue
                out.setdefault(coll, []).append(keys)

    # Mongo's implicit _id index serves an _id sort on any collection.
    for coll in list(out):
        out[coll].append([("_id", 1)])
    return out, unparsed


# ── base64 detection ────────────────────────────────────────────────────────

def _nested_keys(node: ast.AST, depth: int = 0) -> Set[str]:
    """Every literal string key in a dict literal, at any nesting depth."""
    out: Set[str] = set()
    if depth > 6 or not isinstance(node, ast.Dict):
        return out
    for k, v in zip(node.keys, node.values):
        name = _const_str(k)
        if name:
            out.add(name)
            out.add(name.rsplit(".", 1)[-1])
        out |= _nested_keys(v, depth + 1)
        if isinstance(v, ast.List):
            for elt in v.elts:
                out |= _nested_keys(elt, depth + 1)
    return out


def _local_doc_keys(fn: ast.AST) -> Dict[str, Set[str]]:
    """local name -> every key ever put into that dict, however it was put.

    THE WRITE IS ALMOST NEVER AN INLINE DICT. The worker registration path is

        worker_doc = {..., "osha_card_image": osha_card_image, ...}
        await db.workers.insert_one(worker_doc)

    and the update path is `update_fields["osha_card_image"] = ...` followed by
    `{"$set": update_fields}`. Reading only inline literals classified `workers`
    as carrying no base64 — the collection that produced the FIRST of the two
    outages. A base64 check that misses the case it was built from is worse
    than none, so this resolves the local first.
    """
    out: Dict[str, Set[str]] = {}
    for node in ast.walk(fn):
        tgt = val = None
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            tgt, val = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt, val = node.targets[0], node.value
        else:
            continue
        if isinstance(tgt, ast.Name) and isinstance(val, ast.Dict):
            out.setdefault(tgt.id, set()).update(_nested_keys(val))
        elif isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name):
            name = _const_str(tgt.slice)
            if name:
                keys = out.setdefault(tgt.value.id, set())
                keys.add(name)
                keys.add(name.rsplit(".", 1)[-1])
                keys |= _nested_keys(val)
    return out


def base64_collections() -> Dict[str, Set[str]]:
    """collection -> the base64-ish fields something in this repo writes to it."""
    hits: Dict[str, Set[str]] = {c: {note} for c, note in BASE64_BY_HAND.items()}
    write_methods = {"insert_one", "insert_many", "update_one", "update_many",
                     "replace_one", "find_one_and_update"}
    for rel, tree in source_files():
        consts = _module_consts(tree)
        owner: Dict[int, ast.AST] = {}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(fn):
                    owner.setdefault(id(child), fn)
        local_keys: Dict[int, Dict[str, Set[str]]] = {}

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in write_methods):
                continue
            coll = collection_of(node.func.value, consts)
            if not coll:
                continue
            fn = owner.get(id(node))
            if fn is not None and id(fn) not in local_keys:
                local_keys[id(fn)] = _local_doc_keys(fn)
            names = local_keys.get(id(fn), {}) if fn is not None else {}

            keys: Set[str] = set()
            for arg in node.args:
                keys |= _nested_keys(arg)
                # `insert_one(worker_doc)` and `{"$set": update_fields}`.
                for ref in ast.walk(arg):
                    if isinstance(ref, ast.Name):
                        keys |= names.get(ref.id, set())
            found = keys & BASE64_FIELDS
            if found:
                hits.setdefault(coll, set()).update(
                    f"{f} ({rel.as_posix()}:{node.lineno})" for f in sorted(found)
                )
    return hits


# ── the sweep ───────────────────────────────────────────────────────────────

def source_files() -> Iterator[Tuple[Path, ast.Module]]:
    seen: Set[Path] = set()
    for root in SCAN_ROOTS:
        target = BACKEND / root
        paths = [target] if target.is_file() else sorted(target.rglob("*.py"))
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            rel = path.relative_to(BACKEND)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            try:
                yield rel, ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue


def _unwrap_cursor(node: ast.AST, consts: Dict[str, str]):
    """Walk a cursor chain back to its `find`.

    -> (collection, filter, projection, ok). `db.x.find(q, proj).skip(n)` gives
    ('x', q, proj, True). A chain that does not bottom out in a
    `db.<coll>.find(...)` returns ok=False rather than being treated as a
    Python list sort — the caller decides.
    """
    cur = node
    hops = 0
    while hops < 8:
        hops += 1
        if not isinstance(cur, ast.Call) or not isinstance(cur.func, ast.Attribute):
            return "", None, None, False
        attr = cur.func.attr
        if attr == "find":
            coll = collection_of(cur.func.value, consts)
            if not coll:
                return "", None, None, False
            proj = cur.args[1] if len(cur.args) > 1 else next(
                (kw.value for kw in cur.keywords if kw.arg == "projection"), None)
            return coll, (cur.args[0] if cur.args else None), proj, True
        if attr in {"skip", "limit", "sort", "batch_size", "max_time_ms",
                    "allow_disk_use", "hint", "collation", "to_list"}:
            cur = cur.func.value
            continue
        return "", None, None, False
    return "", None, None, False


def _param_default(fn: ast.AST, name: str) -> Optional[str]:
    """The literal default of a function parameter, through `Query("x")`."""
    args = fn.args
    pairs = list(zip(args.args[len(args.args) - len(args.defaults):], args.defaults))
    pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None]
    for arg, default in pairs:
        if arg.arg != name:
            continue
        lit = _const_str(default)
        if lit is not None:
            return lit
        if isinstance(default, ast.Call) and default.args:
            return _const_str(default.args[0])
    return None


def _resolve_sort_field(name: str, fn: ast.AST) -> List[str]:
    """The field names a variable sort field can actually take.

    `GET /admin/filing-jobs` sorts by whatever `sort_by` the CLIENT sent,
    validated against a module-level allowlist:

        if sort_by not in VALID_FILING_JOB_SORT_FIELDS: raise 400

    So the endpoint has three sort shapes, not one, and each needs its own
    index check. This finds the allowlist by the membership test that gates it,
    falling back to the parameter's own default.
    """
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name):
            continue
        if node.left.id != name:
            continue
        for op, cmp_node in zip(node.ops, node.comparators):
            if not isinstance(op, (ast.In, ast.NotIn)):
                continue
            values = GLOBAL_STR_SETS.get(_base_name(cmp_node))
            if values:
                return values
    default = _param_default(fn, name)
    return [default] if default else []


def _sort_spec(call: ast.Call, fn: Optional[ast.AST]):
    """(list of candidate key specs, is_python_list_sort, why_unreadable)."""
    if any(kw.arg in PYTHON_SORT_KWARGS for kw in call.keywords):
        return None, True, ""
    if not call.args:
        return None, True, ""                   # bare list.sort()

    arg = call.args[0]
    lit = _const_str(arg)
    fields: List[str] = []
    if lit is not None:
        fields = [lit]
    elif isinstance(arg, ast.Name) and fn is not None:
        fields = _resolve_sort_field(arg.id, fn)
        if not fields:
            return None, False, f"sort field `{arg.id}` is a variable this pass cannot resolve"
    else:
        keys = key_list(arg)
        if keys is None:
            return None, False, "key spec is not a literal"
        return [keys], False, ""

    # A SINGLE-KEY SORT IS DIRECTION-AGNOSTIC. Mongo walks an index backwards
    # as happily as forwards, so `.sort("sent_at", sort_dir)` with a runtime
    # direction is fully analysable — the same index serves both. Only a
    # multi-key sort cares, and those are written as literal tuple lists.
    direction = _const_int(call.args[1]) if len(call.args) >= 2 else 1
    if direction is None:
        direction = 1
    return [[(f, direction)] for f in fields], False, ""


def projection_verdict(node: Optional[ast.AST], base64_fields: Set[str]) -> str:
    """Does this find()'s projection already keep base64 out of the sort?

    THIS IS HALF OF THE `GET /workers` FIX and it is why it is measured here.
    MongoDB pushes a simple INCLUSION projection below the SORT stage, so the
    documents the in-memory sort holds are the projected ones. An inclusion
    projection that does not name a base64 field caps the sort at a few hundred
    bytes per document and the 32MB ceiling stops being reachable — index or
    no index.

    An EXCLUSION projection (`{"password": 0}`) does not have that property in
    general: it still carries every field it did not name, base64 included.
    """
    if node is None:
        return "none"
    if not isinstance(node, ast.Dict):
        return "unreadable"
    return _projection_of_dict(node, base64_fields)


def _projection_of_dict(node: ast.Dict, base64_fields: Set[str]) -> str:
    pairs = [(_const_str(k), _const_int(v)) for k, v in zip(node.keys, node.values)]
    if any(k is None for k, _ in pairs):
        return "unreadable"
    included = {k for k, v in pairs if v == 1 and k != "_id"}
    excluded = {k for k, v in pairs if v == 0}
    if included:
        leaked = {f for f in included if f.split(".")[0] in base64_fields}
        return ("inclusion, base64 excluded" if not leaked
                else f"inclusion, still carries {sorted(leaked)}")
    if excluded:
        covered = base64_fields & {e.split(".")[0] for e in excluded}
        return (f"exclusion of {sorted(excluded)} — base64 still carried"
                if not covered or covered != base64_fields
                else "exclusion covers every base64 field")
    return "none"


def _enclosing(tree: ast.Module) -> Dict[int, ast.AST]:
    """node id -> the function that contains it."""
    owner: Dict[int, ast.AST] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(fn):
                owner.setdefault(id(child), fn)
    return owner


def index_serves(keys: List[Tuple[str, int]],
                 sort_keys: List[Tuple[str, int]],
                 equality: Set[str]) -> bool:
    """ESR. Every index key before the sort keys must be pinned by equality,
    and the sort keys must then follow in order, in matching or exactly
    reversed direction (Mongo can walk an index backwards, but only wholesale).
    """
    n = len(sort_keys)
    for start in range(len(keys) - n + 1):
        if not all(k in equality for k, _ in keys[:start]):
            break                                # an unpinned key blocks everything after
        window = keys[start:start + n]
        if [f for f, _ in window] != [f for f, _ in sort_keys]:
            continue
        same = all(a == b for (_, a), (_, b) in zip(window, sort_keys))
        flipped = all(a == -b for (_, a), (_, b) in zip(window, sort_keys))
        if same or flipped:
            return True
    return False


def _load_globals() -> None:
    """Module-level constants, filter dicts, collection aliases, across files."""
    if GLOBAL_CONSTS:
        return
    for _rel, tree in source_files():
        for node in tree.body:
            # A function that exists only to build a filter dict.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                returns = [n.value for n in ast.walk(node)
                           if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
                if len(returns) == 1:
                    GLOBAL_FILTER_FNS[node.name] = returns[0]
                continue
            # `ACTIVE_PROJECT_FILTER: Dict[str, Any] = {...}` is an
            # AnnAssign. Two project-list endpoints copy it as their whole
            # filter, so missing it dropped both from the sweep.
            if isinstance(node, ast.AnnAssign) and node.value is not None                     and isinstance(node.target, ast.Name):
                name, value_node = node.target.id, node.value
            elif (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                name, value_node = node.targets[0].id, node.value
            else:
                continue
            lit = _const_str(value_node)
            if lit is not None:
                GLOBAL_CONSTS[name] = lit
                continue
            value = value_node
            if isinstance(value, ast.Dict):
                GLOBAL_DICTS[name] = value
                continue
            if (isinstance(value, ast.Call) and _base_name(value.func) == "frozenset"
                    and value.args):
                value = value.args[0]
            if isinstance(value, (ast.Set, ast.Tuple, ast.List)):
                strs = [_const_str(e) for e in value.elts]
                if strs and all(s is not None for s in strs):
                    GLOBAL_STR_SETS[name] = sorted(strs)

    # Collection aliases at any scope. `daily_logs_coll = getattr(db,
    # "daily_logs", None)` is how the statistical engine reaches Mongo, and
    # without this every sort in peer_cohort / the baseline aggregator reads as
    # "receiver cannot be traced to db.<collection>.find()".
    for _rel, tree in source_files():
        consts = _module_consts(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                continue
            name, value = node.targets[0].id, node.value
            coll = collection_of(value, consts)
            if (not coll and isinstance(value, ast.Call)
                    and _base_name(value.func) == "getattr"
                    and len(value.args) >= 2
                    and _base_name(value.args[0]) in DB_NAMES):
                coll = _const_str(value.args[1]) or ""
            if coll:
                COLLECTION_ALIASES[name] = coll


def findings() -> Tuple[List[dict], List[str], int, int]:
    """-> (rows, skipped, python_sorts, aggregate_sorts)"""
    _load_globals()
    indexes, unparsed = declared_indexes()
    b64 = base64_collections()
    rows: List[dict] = []
    skipped: List[str] = list(unparsed)
    python_sorts = 0
    aggregate_sorts = 0

    for rel, tree in source_files():
        consts = _module_consts(tree)
        owner = _enclosing(tree)
        resolvers: Dict[int, FilterResolver] = {}

        def resolver_for(node) -> Optional[FilterResolver]:
            fn = owner.get(id(node))
            if fn is None:
                return None
            if id(fn) not in resolvers:
                resolvers[id(fn)] = FilterResolver(fn)
            return resolvers[id(fn)]

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            where = f"{rel.as_posix()}:{node.lineno}"
            fn = owner.get(id(node))
            fn_name = getattr(fn, "name", "<module>")

            # $sort inside an aggregate pipeline — out of scope, but counted.
            if isinstance(node.func, ast.Attribute) and node.func.attr == "aggregate":
                for stage in ast.walk(node):
                    if isinstance(stage, ast.Dict) and "$sort" in {
                            _const_str(k) for k in stage.keys}:
                        aggregate_sorts += 1
                continue

            collection = ""
            variants: List[List[Tuple[str, int]]] = []
            filt_node = proj_node = None
            source = ""

            if isinstance(node.func, ast.Attribute) and node.func.attr == "sort":
                if fn_name in SORT_HELPERS:
                    skipped.append(
                        f"{where}: inside `{fn_name}`, whose sort comes from its "
                        f"callers — the call sites are resolved instead")
                    continue
                # Resolve the RECEIVER first. A `.sort()` that is not a cursor
                # is a Python list sort and must not be argued about.
                collection, filt_node, proj_node, ok = _unwrap_cursor(
                    node.func.value, consts)
                if not ok:
                    if isinstance(node.func.value, (ast.Name, ast.Attribute,
                                                    ast.Subscript)):
                        python_sorts += 1
                        continue
                    skipped.append(f"{where}: `.sort(...)` on a receiver this pass "
                                   f"cannot trace back to db.<collection>.find()")
                    continue
                variants, is_python, why = _sort_spec(node, fn)
                if is_python:
                    python_sorts += 1
                    continue
                if variants is None:
                    skipped.append(f"{where}: sort on `{collection}` — {why}")
                    continue
                source = "cursor .sort()"

            elif _base_name(node.func) in SORT_HELPERS and fn_name not in SORT_HELPERS:
                collection = collection_of(node.args[0], consts) if node.args else ""
                if not collection:
                    skipped.append(f"{where}: paginated_query on a collection "
                                   f"expression this pass cannot resolve")
                    continue
                filt_node = node.args[1] if len(node.args) > 1 else next(
                    (kw.value for kw in node.keywords if kw.arg == "query"), None)
                field = next((_const_str(kw.value) for kw in node.keywords
                              if kw.arg == "sort_field"), None)
                direction = next((_const_int(kw.value) for kw in node.keywords
                                  if kw.arg == "sort_dir"), None)
                # paginated_query's own defaults, server.py ~1353.
                variants = [[(field or "created_at",
                              -1 if direction is None else direction)]]
                proj_node = next((kw.value for kw in node.keywords
                                  if kw.arg == "projection"), None)
                source = "paginated_query()"
            else:
                continue

            res = resolver_for(node)
            if res is None:
                skipped.append(f"{where}: sort on `{collection}` outside any function")
                continue
            if isinstance(proj_node, ast.Name):
                # `projection=WORKER_LIST_FIELDS` — the projection half of the
                # GET /workers fix is a named local, and reading only inline
                # dicts reported the endpoint it repaired as still at risk.
                proj_node = res.dicts.get(proj_node.id, proj_node)
            eq, other, cond, parsed, how = res.resolve(filt_node)
            if not parsed:
                skipped.append(f"{where}: sort on `{collection}` — filter not "
                               f"fully readable ({how})")
                continue

            candidates = indexes.get(collection, [])
            b64_fields = {f.split(" ")[0] for f in b64.get(collection, set())}
            proj = projection_verdict(proj_node, b64_fields & BASE64_FIELDS)
            # A projection that keeps base64 out of the sort defuses this row
            # even with no index — the documents are then small.
            defused = proj.startswith("inclusion, base64 excluded")
            narrowed = eq | {c for c in cond if not c.endswith("(non-equality)")}
            for sort_keys in variants:
                served_by = [keys for keys in candidates
                             if index_serves(keys, sort_keys, eq)]
                served_narrow = any(index_serves(keys, sort_keys, narrowed)
                                    for keys in candidates)
                rows.append({
                    "collection": collection,
                    "where": where,
                    "function": fn_name,
                    "source": source
                    + (" [client-chosen sort field]" if len(variants) > 1 else ""),
                    "sort": sort_keys,
                    "equality": sorted(eq),
                    "non_equality": sorted(other),
                    "conditional": sorted(cond),
                    "filter_from": how,
                    "served": bool(served_by),
                    "served_by": [list(map(list, k)) for k in served_by],
                    "served_when_narrowed": served_narrow,
                    "projection": proj,
                    "defused_by_projection": defused,
                    "base64": collection in b64 and not defused,
                    "base64_collection": collection in b64,
                    "base64_evidence": sorted(b64.get(collection, set())),
                    "indexes_declared": len(candidates),
                })
    return rows, skipped, python_sorts, aggregate_sorts


def unserved(include_safe: bool = False) -> List[dict]:
    """The findings that matter: a sort no declared index can serve.

    Default is base64-bearing collections only — the ones that turn into a 500
    rather than a slow page.
    """
    rows, _, _, _ = findings()
    out = [r for r in rows if not r["served"]]
    if not include_safe:
        out = [r for r in out if r["base64"]]
    return sorted(out, key=lambda r: (not r["base64"], r["collection"], r["where"]))


def _fmt_keys(keys) -> str:
    return "{" + ", ".join(f"{f}: {d}" for f, d in keys) + "}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="include collections that cannot hold base64")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows, skipped, python_sorts, agg = findings()
    if args.json:
        print(json.dumps({
            "rows": rows, "skipped": skipped,
            "python_list_sorts": python_sorts, "aggregate_sorts": agg,
        }, indent=2))
        return 0

    bad = [r for r in rows if not r["served"]]
    hot = [r for r in bad if r["base64"]]
    cold = [r for r in bad if not r["base64"]]
    defused = [r for r in bad if r["base64_collection"] and r["defused_by_projection"]]

    print(f"{len(rows)} Mongo cursor/paginated sorts analysed "
          f"across server.py, lib/ and scripts/.")
    print(f"{len(rows) - len(bad)} are served by a declared index; "
          f"{len(bad)} are not.\n")

    def show(title, group, note):
        print("=" * 78)
        print(title)
        print(note)
        print("=" * 78)
        if not group:
            print("  (none)\n")
            return
        for r in group:
            print(f"\n  {r['collection']}  sort {_fmt_keys(r['sort'])}")
            print(f"      {r['where']}  {r['function']}()  [{r['source']}]")
            print(f"      equality:      {r['equality'] or '(none — full scan)'}")
            if r["non_equality"]:
                print(f"      NOT equality:  {r['non_equality']}"
                      f"   <- cannot pin an index key")
            if r["conditional"]:
                print(f"      conditional:   {r['conditional']}"
                      f"   <- absent on the broad call")
            print(f"      filter read from: {r['filter_from']}")
            print(f"      projection:    {r['projection']}")
            print(f"      {r['indexes_declared']} index(es) declared on "
                  f"`{r['collection']}`, none serves this sort")
            if r["served_when_narrowed"]:
                print("      NOTE: a declared index DOES serve this once the "
                      "conditional field(s) are supplied —")
                print("            only the broad call is unserved, and the "
                      "broad call is the big one.")
            if r["base64_evidence"]:
                print(f"      base64: {r['base64_evidence'][0]}")
        print()

    show("AT RISK — unserved sort on a collection that holds inline base64",
         hot, "These are the shape that produced two 500s. Index them.")
    if args.all:
        show("SLOW ONLY — unserved sort, no base64 on the collection",
             cold, "A blocking in-memory sort, but the documents are small.")
    else:
        print(f"{len(cold)} further unserved sort(s) on collections with no "
              f"base64 — slow, not fatal. Re-run with --all to list them.\n")

    print("=" * 78)
    print("NOT ANALYSED — counted, never silently dropped")
    print("=" * 78)
    print(f"  {python_sorts} Python list.sort() call(s) — not Mongo.")
    print(f"  {agg} $sort stage(s) inside aggregate() pipelines — out of scope; "
          f"an aggregate sort has the same 32MB ceiling and deserves its own pass.")
    print(f"  {len(defused)} unserved sort(s) on a base64 collection that an "
          f"INCLUSION PROJECTION already defuses —")
    print(f"      the sort holds projected documents, so 32MB is out of reach. "
          f"Listed here so they are")
    print(f"      visible rather than absent; if the projection is ever widened "
          f"they become findings:")
    for r in defused:
        print(f"      {r['where']}  {r['collection']} sort {_fmt_keys(r['sort'])}"
              f"  ({r['projection']})")
    if not defused:
        print("      (none)")
    print(f"  {len(skipped)} cursor sort(s) this pass could not fully parse:")
    for s in skipped:
        print(f"      {s}")
    if not skipped:
        print("      (none)")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
