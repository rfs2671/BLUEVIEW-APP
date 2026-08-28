"""Find query filters that read a field nothing in the product writes.

FOUR INSTANCES IN ONE DAY is what this exists for:

  * `dropbox_enabled`   — read, never written.
  * `checklist_title`   — written once at creation, never propagated, read on
                          every screen. The mirror image, and NOT what this
                          finds — see LIMITS.
  * `daily_logs.phase`  — accepted by DailyLogCreate, dumped into the insert,
                          and sent by NO client. Four engines filter on it:
                          live_mutation, defcon, peer_cohort and the violation
                          baseline aggregator. All four have been reading an
                          always-empty field since the day they shipped.
  * `daily_logs` itself — 92 rows, all April test data, and `missing_detector`
                          calls it "the operator-recorded source of truth".

One shape: A READ WHOSE WRITER DOES NOT EXIST IN THE SHIPPED PRODUCT. Each was
found by a person noticing an empty screen, weeks or months late. None of them
fails a test today, because each one is valid code that returns nothing.

HOW IT DECIDES. For every `db.<collection>.<method>(...)` it separates the two
argument positions that mean different things — the filter (a read) and the
document or update (a write) — and reports fields read on a collection and
never written to it.

THE PYDANTIC LEG IS THE LOAD-BEARING ONE, and it is why this is not thirty
lines. Most writes here look like:

    async def create_daily_log(log_data: DailyLogCreate, ...):
        log_dict = log_data.model_dump()
        log_dict["created_at"] = now
        await db.daily_logs.insert_one(log_dict)

The inserted document is a NAME, so literal extraction sees nothing and every
field of that collection reads as unwritten. The opposite shortcut — "a model
accepts it, therefore something writes it" — is the exact hole `phase` sat in:
accepted, dumped into the insert, never sent by anybody. Being in a request
model is not evidence that a value is ever produced.

So `_bind_function` resolves it within one function: which local is inserted
into which collection, which keys are assigned onto that local, and which
request model it was dumped from. That last binding is what lets a candidate be
classed rather than guessed:

    UNWRITTEN   no server write, and the collection's own request model does
                not accept it either. Nothing anywhere can produce this value.
    UNSENT      the model accepts it, so the server would store it — but the
                field name appears nowhere in the frontend. Nobody sends it.
    CLIENT-FED  accepted and mentioned by the frontend. Shown only under --all.

A GLOBAL "any x[key] = ... suppresses key" RULE WAS TRIED FIRST AND IS WRONG.
It is quieter, and it deleted the one finding this exists to catch: `phase` is
assigned as a dict key somewhere unrelated, so the global rule swallowed it. A
suppression that cannot name the collection it is suppressing for will
eventually suppress the thing you are looking for.

LIMITS, stated because a sweep that looks exhaustive and is not is worse than
none:

  * Literal keys only. A filter built from a variable is invisible.
  * It cannot see the `checklist_title` shape — a field that IS written, once,
    and then goes stale. Different defect, different check.
  * It cannot see a collection that STOPPED being written (daily_logs since
    April). The writer exists and is idle. That needs a row count at runtime,
    not a static pass.
  * The frontend check is a text search for the key name, so a name used for
    two different things reads as client-fed and stays quiet. False negatives
    are the deliberate trade: this must not cry wolf, or it earns the same
    contempt as a health check that warns on every boot.

Run:  python backend/scripts/find_reads_without_writers.py [--all] [--json]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Set, Tuple

BACKEND = Path(__file__).resolve().parent.parent
FRONTEND = BACKEND.parent / "frontend"

READ_METHODS = {
    "find", "find_one", "count_documents", "distinct",
    "delete_one", "delete_many", "find_one_and_update",
    "update_one", "update_many", "replace_one",
}
WRITE_METHODS = {
    "insert_one", "insert_many", "update_one", "update_many",
    "replace_one", "find_one_and_update",
}
WRITE_OPERATORS = {"$set", "$setOnInsert", "$inc", "$push", "$addToSet",
                   "$unset", "$min", "$max"}
QUERY_OPERATORS = {"$and", "$or", "$nor", "$not", "$expr", "$text", "$where",
                   "$comment"}
IGNORED_FIELDS = {"_id"}
SKIP_DIRS = {"tests", "__pycache__", "scripts", "migrations", "docs"}


# ── AST helpers ─────────────────────────────────────────────────────────────

def _dict_keys(node: ast.AST) -> Set[str]:
    if not isinstance(node, ast.Dict):
        return set()
    return {k.value for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _has_spread(node: ast.AST) -> bool:
    return isinstance(node, ast.Dict) and any(k is None for k in node.keys)


def _filter_fields(node: ast.AST) -> Set[str]:
    """Field names a query filter reads, descending through $and/$or/$nor."""
    fields: Set[str] = set()
    if not isinstance(node, ast.Dict):
        return fields
    for k, v in zip(node.keys, node.values):
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            continue
        name = k.value
        if name in QUERY_OPERATORS:
            items = v.elts if isinstance(v, ast.List) else [v]
            for item in items:
                fields |= _filter_fields(item)
            continue
        if name.startswith("$"):
            continue
        fields.add(name)
    return fields


def _write_fields(node: ast.AST) -> Tuple[Set[str], bool]:
    fields: Set[str] = set()
    opaque = _has_spread(node) or not isinstance(node, ast.Dict)
    if not isinstance(node, ast.Dict):
        return fields, opaque
    for k, v in zip(node.keys, node.values):
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            opaque = True
            continue
        if k.value in WRITE_OPERATORS:
            fields |= _dict_keys(v)
            if _has_spread(v) or not isinstance(v, ast.Dict):
                opaque = True
        elif not k.value.startswith("$"):
            fields.add(k.value)
    return fields, opaque


def _collection_of(func: ast.AST) -> str:
    """`db.daily_logs.find` -> 'daily_logs'; anything else -> ''."""
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Attribute):
        return ""
    owner = func.value
    base = owner.value
    base_name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
    return owner.attr if base_name in {"db", "database"} else ""


def _annotation_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


# ── the two passes ──────────────────────────────────────────────────────────

def _source_files(writers: bool = False) -> Iterator[Tuple[Path, ast.Module]]:
    """Parsed backend sources.

    TWO DIFFERENT QUESTIONS, TWO DIFFERENT FILE SETS. "Does the running product
    READ this?" excludes scripts and migrations — a backfill is not a request
    path. "Does ANYTHING in this repo WRITE it?" includes them: a collection
    populated by a nightly backfill is written, and reporting it as unwritten
    is the crying-wolf failure this must not have. `socrata_permits_historical`
    is exactly that case — read by two engines, written only by
    scripts/socrata_3year_backfill.py.
    """
    skip = {"tests", "__pycache__"} if writers else SKIP_DIRS
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND)
        if any(part in skip for part in rel.parts):
            continue
        try:
            yield rel, ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue


def model_fields() -> Dict[str, Set[str]]:
    """Every BaseModel in the backend -> its declared field names."""
    out: Dict[str, Set[str]] = {}
    for _rel, tree in _source_files():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
                     for b in node.bases}
            if "BaseModel" not in bases:
                continue
            out[node.name] = {
                st.target.id for st in node.body
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)
            }
    return out


def _bind_function(fn: ast.AST, models: Dict[str, Set[str]]):
    """Yield (collection, keys assigned onto the inserted local, model fields
    that local was dumped from) for each insert in this function."""
    params = {a.arg: _annotation_name(a.annotation)
              for a in list(fn.args.args) + list(fn.args.kwonlyargs)
              if a.annotation is not None}

    dumped_from: Dict[str, str] = {}
    subscripts: Dict[str, Set[str]] = {}
    inserted: Dict[str, str] = {}

    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt, val = node.targets[0], node.value
            if (isinstance(tgt, ast.Name) and isinstance(val, ast.Call)
                    and isinstance(val.func, ast.Attribute)
                    and val.func.attr in {"model_dump", "dict"}
                    and isinstance(val.func.value, ast.Name)):
                model = params.get(val.func.value.id, "")
                if model:
                    dumped_from[tgt.id] = model
            if (isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name)
                    and isinstance(tgt.slice, ast.Constant)
                    and isinstance(tgt.slice.value, str)):
                subscripts.setdefault(tgt.value.id, set()).add(tgt.slice.value)
            # `doc = {...}` then `insert_one(doc)` — the other half of the same
            # shape, and the more common one. Without this every field of every
            # collection built that way reads as unwritten, which is eighty-odd
            # findings nobody will read past.
            if isinstance(tgt, ast.Name) and isinstance(val, ast.Dict):
                subscripts.setdefault(tgt.id, set()).update(_dict_keys(val))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            coll = _collection_of(node.func)
            if not coll or not node.args:
                continue
            if (node.func.attr in {"insert_one", "insert_many"}
                    and isinstance(node.args[0], ast.Name)):
                inserted[node.args[0].id] = coll
            if (node.func.attr in {"update_one", "update_many"}
                    and len(node.args) >= 2 and isinstance(node.args[1], ast.Dict)):
                for k, v in zip(node.args[1].keys, node.args[1].values):
                    if (isinstance(k, ast.Constant) and k.value in WRITE_OPERATORS
                            and isinstance(v, ast.Name)):
                        inserted[v.id] = coll

    for var, coll in inserted.items():
        yield coll, set(subscripts.get(var, set())), models.get(dumped_from.get(var, ""), set())


def scan():
    reads: Dict[str, Dict[str, Set[str]]] = {}
    writes: Dict[str, Set[str]] = {}
    accepts: Dict[str, Set[str]] = {}
    opaque: Dict[str, bool] = {}
    models = model_fields()

    # Reads from the shipped product only; writes from everything, including
    # the backfills. See _source_files.
    read_files = {rel for rel, _ in _source_files()}

    for rel, tree in _source_files(writers=True):
        is_product = rel in read_files
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                coll = _collection_of(node.func)
                if coll and node.args:
                    if is_product and node.func.attr in READ_METHODS:
                        for f in _filter_fields(node.args[0]) - IGNORED_FIELDS:
                            reads.setdefault(coll, {}).setdefault(f, set()).add(
                                f"{rel.as_posix()}:{node.lineno}")
                    if node.func.attr in WRITE_METHODS:
                        if node.func.attr in {"insert_one", "insert_many"}:
                            doc = node.args[0]
                            if isinstance(doc, ast.Dict):
                                writes.setdefault(coll, set()).update(_dict_keys(doc))
                                if _has_spread(doc):
                                    opaque[coll] = True
                            else:
                                opaque[coll] = True
                        elif len(node.args) >= 2:
                            fields, is_opaque = _write_fields(node.args[1])
                            writes.setdefault(coll, set()).update(fields)
                            if is_opaque:
                                opaque[coll] = True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for coll, keys, accepted in _bind_function(node, models):
                    writes.setdefault(coll, set()).update(keys)
                    if accepted:
                        accepts.setdefault(coll, set()).update(accepted)
    return reads, writes, accepts, opaque


def frontend_mentions(field: str) -> bool:
    """Does any frontend source name this key? Text search, deliberately."""
    pattern = re.compile(r"['\"]?\b" + re.escape(field) + r"\b['\"]?\s*[:=]")
    for path in FRONTEND.rglob("*.js*"):
        if "node_modules" in path.parts or "assets" in path.parts:
            continue
        try:
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                return True
        except OSError:
            continue
    return False


def findings(include_client_fed: bool = False) -> List[dict]:
    reads, writes, accepts, opaque = scan()
    out: List[dict] = []
    for coll in sorted(reads):
        written = writes.get(coll, set())
        accepted_fields = accepts.get(coll, set())
        for field in sorted(reads[coll]):
            if field in written:
                continue
            if "." in field and field.split(".", 1)[0] in (written | accepted_fields):
                continue
            if field in accepted_fields:
                if frontend_mentions(field):
                    if not include_client_fed:
                        continue
                    verdict = "CLIENT-FED"
                else:
                    verdict = "UNSENT"
            else:
                verdict = "UNWRITTEN"
            out.append({
                "collection": coll,
                "field": field,
                "verdict": verdict,
                "opaque_writes": bool(opaque.get(coll)),
                "read_at": sorted(reads[coll][field]),
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="include CLIENT-FED")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = findings(include_client_fed=args.all)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No reads without writers.")
        return 0
    print(f"{len(rows)} candidate(s):\n")
    for r in rows:
        flag = "  (some writes to this collection are opaque)" if r["opaque_writes"] else ""
        print(f"  [{r['verdict']}] {r['collection']}.{r['field']}{flag}")
        for site in r["read_at"][:6]:
            print(f"      read at {site}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
