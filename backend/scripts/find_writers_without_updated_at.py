"""Find writers that mutate a synced document without stamping `updated_at`.

WHY THIS EXISTS. A gate tablet reconciles its offline cache against server
state using `updated_at` on `project_files`, `logbooks` and `projects` as the
change marker. A writer that mutates a document and does NOT stamp that field
makes the marker LIE: the tablet holds content that no longer matches the
server, and nothing ever tells it. The failure is silent on both ends — the
write succeeds, the sync succeeds, and the tablet is quietly wrong until a
person notices a photo or a required-log list that does not match the office.

The worst instance found so far, and the shape to keep in mind:

    _purge_finalized_photo_base64 rewrites the photo content of a FILED
    COMPLIANCE RECORD — swapping full-size base64 for a thumb — in a
    fire-and-forget background task that runs JUST AFTER finalize already
    bumped `updated_at`. A tablet syncing on that bump gets the pre-purge
    document, and the post-purge content never moves the marker again.

That is the whole class: a late, out-of-band write riding behind a timestamp
somebody else already moved.

HOW IT DECIDES. For every `db.<collection>.<method>(...)` on the three synced
collections it locates the argument that carries the mutation — the document
for `insert_one`/`replace_one`, the update for `update_one`/`update_many` —
and asks whether `updated_at` is provably among the fields it writes. Under
`$set`, `$setOnInsert` and `$currentDate` all count.

VERDICTS. Three, because "I cannot tell" is not the same as "it is missing"
and collapsing them would either hide a real one or cry wolf:

    MISSING   the mutation is fully readable and `updated_at` is not in it.
              This is the defect.
    OPAQUE    the mutation is built in a shape literal extraction cannot read
              — a comprehension, a spread of a variable, a name assigned in
              more than one place. It MAY stamp. It is reported because an
              unreadable write is exactly where the next silent one hides.
    STAMPED   provably carries the field. Not reported.

Both MISSING and OPAQUE are findings, and the ratchet test asserts on the
union. An OPAQUE write that genuinely stamps belongs on the allowlist with a
one-line note saying how — that note is the only thing separating it from a
real defect, and writing it down is the point.

NAME RESOLUTION IS THE LOAD-BEARING PART. Most writes here do not pass a dict
literal; they pass a name:

    sets = {f"dropbox_sync.{k}": v for k, v in summary.items()}
    await db.projects.update_one({...}, {"$set": sets})

so the pass resolves names within their own scope: the value assigned to a
name, the literal keys added to it by subscript, and one level of nesting
through the update operator. A name assigned twice, or assigned from anything
other than a dict literal, stays OPAQUE rather than being guessed at.

WHAT IS NOT A DEFECT, and why the allowlist is not optional. Some writes SHOULD
NOT stamp. The Dropbox "file unchanged" branch writes only `last_synced_at`
because nothing about the file changed; stamping there would make every sync
run look like every file changed and re-emit the entire project on every poll.
An allowlist entry without a written reason is how this check rots — the reason
is the deliverable, not the suppression.

LIMITS, stated because a sweep that looks exhaustive and is not is worse than
none:

  * Literal collection access only (`db.projects.update_one`). A collection
    reached through a variable is invisible. Verified at time of writing:
    every write to the three synced collections uses this shape.
  * A conditional stamp (`if x: doc["updated_at"] = now`) reads as stamped.
    The pass sees that the key can be set, not that it always is.
  * It says nothing about whether the stamped VALUE is correct, only that the
    field is written.
  * `bulk_write` is not decoded. None exists on these collections today; if
    one appears it reads as no write at all, not as a violation.

Run:  python backend/scripts/find_writers_without_updated_at.py [--json]
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

BACKEND = Path(__file__).resolve().parent.parent

# The three collections the gate tablet reconciles. `updated_at` is the change
# marker for these and only these; other collections are not this check's
# business.
SYNCED_COLLECTIONS = {"project_files", "logbooks", "projects"}

STAMP_FIELD = "updated_at"

# Methods that mutate a document. `find_one_and_update` is deliberately
# included for the same reason as the rest — it changes content.
WRITE_METHODS = {"insert_one", "update_one", "update_many", "replace_one",
                 "find_one_and_update"}
# The mutation rides in args[0] for these, args[1] for the others.
DOC_IN_FIRST_ARG = {"insert_one"}

# Operators whose payload keys are field names being written.
FIELD_OPERATORS = {"$set", "$setOnInsert", "$inc", "$push", "$addToSet",
                   "$unset", "$min", "$max", "$currentDate", "$pull",
                   "$pop", "$rename", "$mul", "$bit"}
# Of those, the ones that can actually deposit `updated_at`. `$unset` writing
# `updated_at` is the opposite of stamping, so it is not here.
STAMPING_OPERATORS = {"$set", "$setOnInsert", "$currentDate", "$max", "$min"}

SEARCH_ROOTS = ("server.py", "lib", "scripts")
SKIP_DIRS = {"tests", "__pycache__"}

DYNAMIC = "<dynamic>"


# ── scope resolution ────────────────────────────────────────────────────────

class Scope:
    """What is known about the names assigned inside one function or module.

    Only literal, statically-visible facts. A name this cannot pin down stays
    unresolved and its write is reported OPAQUE rather than assumed innocent.
    """

    def __init__(self, node: ast.AST, name: str):
        self.node = node
        self.name = name
        self.values: Dict[str, List[ast.AST]] = {}
        self.extra_keys: Dict[str, Set[str]] = {}
        self.dynamic_keys: Set[str] = set()
        self._collect(node, root=True)

    def _collect(self, node: ast.AST, root: bool = False) -> None:
        """Walk this scope's statements, NOT descending into nested functions.

        Descending would let a name in an unrelated inner function stand in for
        the one being written here, and the direction of that error is a false
        pass — the one direction a ratchet must not have.
        """
        for child in ast.iter_child_nodes(node):
            if not root and isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            ):
                continue
            if root and isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            ) and child is not node:
                continue
            self._note(child)
            self._collect(child)

    def _note(self, node: ast.AST) -> None:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                self._note_target(tgt, node.value)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            tgt = node.target
            self._note_target(tgt, getattr(node, "value", None) or ast.Constant(None))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "update"
                and isinstance(node.func.value, ast.Name) and node.args):
            # `doc.update({...})` adds keys to a name we may be tracking.
            arg = node.args[0]
            if isinstance(arg, ast.Dict) and not _has_spread(arg):
                self.extra_keys.setdefault(
                    node.func.value.id, set()).update(_dict_keys(arg))
            else:
                self.dynamic_keys.add(node.func.value.id)

    def _note_target(self, tgt: ast.AST, value: ast.AST) -> None:
        if isinstance(tgt, ast.Name):
            self.values.setdefault(tgt.id, []).append(value)
        elif isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name):
            var = tgt.value.id
            sl = tgt.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                self.extra_keys.setdefault(var, set()).add(sl.value)
            else:
                self.dynamic_keys.add(var)

    def resolve(self, name: str) -> Tuple[Optional[ast.Dict], Set[str], bool]:
        """(the dict literal this name holds, extra literal keys, opaque)."""
        extra = set(self.extra_keys.get(name, set()))
        opaque = name in self.dynamic_keys
        values = self.values.get(name, [])
        if len(values) != 1:
            # Never assigned here, or assigned in more than one place. Either
            # way this pass cannot say what it holds.
            return None, extra, True
        val = values[0]
        if isinstance(val, ast.Dict):
            return val, extra, opaque or _has_spread(val)
        return None, extra, True


def _scopes(tree: ast.Module) -> Dict[ast.AST, Scope]:
    """Every Call node in the module -> the Scope it is written in."""
    out: Dict[ast.AST, Scope] = {}

    def descend(node: ast.AST, scope: Scope) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = Scope(child, child.name)
                out[child] = inner
                descend(child, inner)
            else:
                out[child] = scope
                descend(child, scope)

    module_scope = Scope(tree, "<module>")
    out[tree] = module_scope
    descend(tree, module_scope)
    return out


# ── AST helpers ─────────────────────────────────────────────────────────────

def _has_spread(node: ast.AST) -> bool:
    return isinstance(node, ast.Dict) and any(k is None for k in node.keys)


def _dict_keys(node: ast.AST) -> Set[str]:
    if not isinstance(node, ast.Dict):
        return set()
    return {k.value for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _dict_has_dynamic_key(node: ast.AST) -> bool:
    if not isinstance(node, ast.Dict):
        return True
    return any(k is not None and not (isinstance(k, ast.Constant)
                                      and isinstance(k.value, str))
               for k in node.keys)


def _collection_of(func: ast.AST) -> str:
    """`db.logbooks.update_one` -> 'logbooks'; anything else -> ''."""
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Attribute):
        return ""
    owner = func.value
    base = owner.value
    base_name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
    return owner.attr if base_name in {"db", "database"} else ""


# ── the decision ────────────────────────────────────────────────────────────

def _payload_fields(node: ast.AST, scope: Scope) -> Tuple[Set[str], bool]:
    """Literal field names in an operator payload, and whether it is opaque."""
    if isinstance(node, ast.Name):
        inner, extra, opaque = scope.resolve(node.id)
        keys = _dict_keys(inner) | extra
        if inner is not None and _dict_has_dynamic_key(inner):
            opaque = True
        return keys, opaque
    if isinstance(node, ast.Dict):
        return _dict_keys(node), _has_spread(node) or _dict_has_dynamic_key(node)
    return set(), True


def _classify(doc: ast.AST, scope: Scope, is_update: bool):
    """(stamped, opaque, fields written) for one mutation argument."""
    extra: Set[str] = set()
    if isinstance(doc, ast.Name):
        inner, extra, opaque = scope.resolve(doc.id)
        if inner is None:
            return (STAMP_FIELD in extra), (opaque and STAMP_FIELD not in extra), \
                sorted(extra) or [DYNAMIC]
        stamped, deeper_opaque, fields = _classify(inner, scope, is_update)
        fields = sorted(set(fields) | extra)
        stamped = stamped or STAMP_FIELD in extra
        return stamped, (opaque or deeper_opaque) and not stamped, fields

    if not isinstance(doc, ast.Dict):
        # An aggregation-pipeline update (a list), a call, a comprehension —
        # nothing literal to read.
        return False, True, [DYNAMIC]

    fields: Set[str] = set()
    stamped = False
    opaque = _has_spread(doc)

    operator_keys = [k.value for k in doc.keys
                     if isinstance(k, ast.Constant) and isinstance(k.value, str)
                     and k.value.startswith("$")]

    if is_update and not operator_keys:
        # An update with no operators at all is a replacement document.
        is_update = False

    for k, v in zip(doc.keys, doc.values):
        if k is None:                       # `**something`
            continue
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            opaque = True
            continue
        name = k.value
        if is_update:
            if name in FIELD_OPERATORS:
                payload, payload_opaque = _payload_fields(v, scope)
                fields |= payload
                if payload_opaque:
                    opaque = True
                if name in STAMPING_OPERATORS and STAMP_FIELD in payload:
                    stamped = True
            elif name.startswith("$"):
                opaque = True               # an operator this pass does not model
        else:
            fields.add(name)
            if name == STAMP_FIELD:
                stamped = True

    if stamped:
        opaque = False
    return stamped, opaque, sorted(fields) or [DYNAMIC]


# ── the sweep ───────────────────────────────────────────────────────────────

def _source_files() -> Iterator[Tuple[Path, ast.Module]]:
    paths: List[Path] = []
    for root in SEARCH_ROOTS:
        target = BACKEND / root
        if target.is_file():
            paths.append(target)
        elif target.is_dir():
            paths.extend(sorted(target.rglob("*.py")))
    for path in paths:
        rel = path.relative_to(BACKEND)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        try:
            yield rel, ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue


def write_sites() -> List[dict]:
    """EVERY write to a synced collection, STAMPED ones included.

    Separate from `findings()` so the ratchet can assert the sweep still sees
    writes at all. A pass that has quietly stopped matching — a renamed db
    handle, a broken `_collection_of` — reports nothing and looks like a clean
    bill of health forever.
    """
    out: List[dict] = []
    for rel, tree in _source_files():
        scopes = _scopes(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)):
                continue
            coll = _collection_of(node.func)
            method = node.func.attr
            if coll not in SYNCED_COLLECTIONS or method not in WRITE_METHODS:
                continue
            idx = 0 if method in DOC_IN_FIRST_ARG else 1
            if len(node.args) <= idx:
                continue
            scope = scopes.get(node, scopes[tree])
            stamped, opaque, fields = _classify(
                node.args[idx], scope, is_update=(idx == 1 and method != "replace_one"),
            )
            out.append({
                "file": rel.as_posix(),
                "line": node.lineno,
                "collection": coll,
                "method": method,
                "function": scope.name,
                "verdict": ("STAMPED" if stamped
                            else "OPAQUE" if opaque else "MISSING"),
                "fields": fields,
            })
    out.sort(key=lambda r: (r["file"], r["line"]))
    return out


def findings() -> List[dict]:
    """Every write to a synced collection that does not provably stamp."""
    return [r for r in write_sites() if r["verdict"] != "STAMPED"]


def key_of(row: dict) -> Tuple[str, str, Tuple[str, ...]]:
    """The allowlist key: file, enclosing function, and the fields written.

    Scoped to the exact write that was blessed. Adding a field to an allowed
    `$set` stops the entry matching and the ratchet speaks up again — which is
    the intent: an allowance covers one write, not a function forever.
    """
    return (row["file"], row["function"], tuple(row["fields"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = findings()
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("Every write to a synced collection stamps updated_at.")
        return 0
    missing = [r for r in rows if r["verdict"] == "MISSING"]
    print(f"{len(rows)} writer(s) without a provable {STAMP_FIELD} "
          f"({len(missing)} MISSING, {len(rows) - len(missing)} OPAQUE):\n")
    for r in rows:
        print(f"  [{r['verdict']}] {r['collection']}.{r['method']} "
              f"in {r['function']}()")
        print(f"      {r['file']}:{r['line']}")
        print(f"      writes: {', '.join(r['fields'])}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
