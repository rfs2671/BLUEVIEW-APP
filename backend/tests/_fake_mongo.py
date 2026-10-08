"""A small in-memory Mongo for WhatsApp tests. Enough operators, no more.

Supports: equality (incl. a scalar against an array field), $in, $nin, $ne,
$gt, $gte, $lt, $lte, $exists, $regex, $or; updates $set, $setOnInsert, $inc,
$unset; unique `_id` and optional unique single fields; find / find_one /
find_one_and_update / insert_one / update_one / update_many / replace_one /
count_documents / delete_one / create_index (recorded, not enforced except
`unique` on a single field)."""

from __future__ import annotations

import copy
import itertools

from pymongo.errors import DuplicateKeyError

_ids = itertools.count(1)


def _cmp(val, cond):
    if isinstance(cond, dict) and any(str(k).startswith("$") for k in cond):
        for op, arg in cond.items():
            if op == "$in":
                vals = val if isinstance(val, list) else [val]
                if not any(v in arg for v in vals):
                    return False
            elif op == "$nin":
                vals = val if isinstance(val, list) else [val]
                if any(v in arg for v in vals):
                    return False
            elif op == "$ne":
                if val == arg:
                    return False
            elif op == "$regex":
                import re as _re
                if not isinstance(val, str) or not _re.search(arg, val):
                    return False
            elif op == "$exists":
                if (val is not _MISSING) != bool(arg):
                    return False
            elif op in ("$gt", "$gte", "$lt", "$lte"):
                if val is _MISSING or val is None:
                    return False
                try:
                    ok = {"$gt": val > arg, "$gte": val >= arg,
                          "$lt": val < arg, "$lte": val <= arg}[op]
                except TypeError:
                    return False
                if not ok:
                    return False
            else:
                raise NotImplementedError(op)
        return True
    if val is _MISSING:
        return cond is None
    if isinstance(val, list) and not isinstance(cond, list):
        return cond in val
    return val == cond


class _Missing:
    pass


_MISSING = _Missing()


def _get(doc, dotted):
    """A dotted path, traversing arrays of documents the way Mongo does:
    `a.b` on {"a": [{"b": 1}, {"b": 2}]} yields [1, 2]."""
    cur = doc
    parts = dotted.split(".")
    for i, part in enumerate(parts):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and not part.isdigit():
            rest = ".".join(parts[i:])
            vals = [_get(x, rest) for x in cur if isinstance(x, dict)]
            vals = [v for v in vals if v is not _MISSING]
            return vals if vals else _MISSING
        else:
            return _MISSING
    return cur


def matches(doc, query):
    for key, cond in (query or {}).items():
        if key == "$or":
            if not any(matches(doc, c) for c in cond):
                return False
            continue
        if not _cmp(_get(doc, key), cond):
            return False
    return True


def _set(doc, dotted, value):
    parts = dotted.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


class _Res:
    def __init__(self, matched=0, modified=0, inserted_id=None, upserted_id=None):
        self.matched_count = matched
        self.modified_count = modified
        self.inserted_id = inserted_id
        self.upserted_id = upserted_id
        self.deleted_count = matched


def _sortable(v):
    """Dates compare as dates, everything else as its string."""
    if hasattr(v, "isoformat") and not isinstance(v, str):
        return (0, v.isoformat())
    return (1, str(v))


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key=None, direction=None, *a, **k):
        if isinstance(key, str):
            self.rows.sort(key=lambda r: (_get(r, key) is _MISSING, str(_get(r, key))),
                           reverse=(direction == -1))
        elif isinstance(key, list):
            # [(field, dir), ...]: stable sorts from the last key to the first.
            for field, d in reversed(key):
                self.rows.sort(key=lambda r, f=field: (
                    _get(r, f) is _MISSING, _sortable(_get(r, f))), reverse=(d == -1))
        return self

    def limit(self, n):
        self.rows = self.rows[:n] if n else self.rows
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(r) for r in (self.rows[:n] if n else self.rows)]

    def __aiter__(self):
        self._it = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return copy.deepcopy(next(self._it))
        except StopIteration:
            raise StopAsyncIteration


class Coll:
    def __init__(self, name, rows=None, unique=()):
        self.name = name
        self.rows = [dict(r) for r in (rows or [])]
        self.unique = set(unique)
        self.indexes = []

    def _check_unique(self, doc, skip=None):
        for r in self.rows:
            if r is skip:
                continue
            if "_id" in doc and r.get("_id") == doc.get("_id"):
                raise DuplicateKeyError("E11000 duplicate key _id")
            for f in self.unique:
                if f in doc and r.get(f) == doc.get(f):
                    raise DuplicateKeyError(f"E11000 duplicate key {f}")

    async def insert_one(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", f"oid{next(_ids)}")
        self._check_unique(doc)
        self.rows.append(doc)
        return _Res(inserted_id=doc["_id"])

    async def find_one(self, query=None, projection=None, sort=None, *a, **k):
        rows = [r for r in self.rows if matches(r, query)]
        if sort:
            key, direction = sort[0]
            rows.sort(key=lambda r: str(_get(r, key)), reverse=(direction == -1))
        return copy.deepcopy(rows[0]) if rows else None

    def find(self, query=None, projection=None, *a, **k):
        return _Cursor([r for r in self.rows if matches(r, query)])

    async def count_documents(self, query=None, *a, **k):
        return sum(1 for r in self.rows if matches(r, query))

    def _apply(self, doc, update, inserting=False):
        for k, v in (update.get("$set") or {}).items():
            _set(doc, k, v)
        if inserting:
            for k, v in (update.get("$setOnInsert") or {}).items():
                _set(doc, k, v)
        for k, v in (update.get("$inc") or {}).items():
            _set(doc, k, (_get(doc, k) if _get(doc, k) is not _MISSING else 0) + v)
        for k in (update.get("$unset") or {}):
            doc.pop(k, None)
        for k, v in (update.get("$addToSet") or {}).items():
            cur = _get(doc, k)
            cur = list(cur) if isinstance(cur, list) else []
            if v not in cur:
                cur.append(v)
            _set(doc, k, cur)

    async def update_one(self, query, update, upsert=False, **k):
        for r in self.rows:
            if matches(r, query):
                before = copy.deepcopy(r)
                self._apply(r, update)
                self._check_unique(r, skip=r)
                return _Res(1, int(before != r))
        if upsert:
            new = {k2: v for k2, v in (query or {}).items()
                   if not k2.startswith("$") and not isinstance(v, dict)}
            self._apply(new, update, inserting=True)
            res = await self.insert_one(new)
            return _Res(0, 0, upserted_id=res.inserted_id)
        return _Res(0, 0)

    async def update_many(self, query, update, **k):
        n = 0
        for r in self.rows:
            if matches(r, query):
                self._apply(r, update)
                n += 1
        return _Res(n, n)

    async def replace_one(self, query, doc, upsert=False):
        for i, r in enumerate(self.rows):
            if matches(r, query):
                self.rows[i] = dict(doc)
                return _Res(1, 1)
        if upsert:
            await self.insert_one(doc)
        return _Res(0, 0)

    async def find_one_and_update(self, query, update, upsert=False, **k):
        for r in self.rows:
            if matches(r, query):
                before = copy.deepcopy(r)
                self._apply(r, update)
                # pymongo's ReturnDocument.AFTER is True.
                return copy.deepcopy(r) if k.get("return_document") is True else before
        return None

    async def delete_one(self, query):
        for i, r in enumerate(self.rows):
            if matches(r, query):
                del self.rows[i]
                return _Res(1)
        return _Res(0)

    async def create_index(self, keys, name=None, **opts):
        self.indexes.append({"keys": keys, "name": name, **opts})
        if opts.get("unique") and isinstance(keys, list) and len(keys) == 1:
            self.unique.add(keys[0][0])
        return name


class FakeDb:
    def __init__(self, unique=None, **collections):
        self.__dict__["_c"] = {}
        self.__dict__["_unique"] = unique or {}
        for name, rows in collections.items():
            self[name].rows = [dict(r) for r in rows]

    def __getitem__(self, name):
        c = self._c.get(name)
        if c is None:
            c = self._c[name] = Coll(name, unique=self._unique.get(name, ()))
        return c

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]
