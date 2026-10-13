"""An in-memory, ASYNC Mongo stand-in for driving the real app over HTTP.

For tests that send real requests through server.app -- every middleware, every
dependency, the real JWT -- where the only thing replaced is the database.

Supports the filter operators the auth and record paths use: equality (incl.
dotted paths), $ne, $in, $nin, $exists, $gt/$gte/$lt/$lte, $regex, $or, $and.
AN OPERATOR IT DOES NOT KNOW RAISES rather than matching or not matching: a
fake that silently answers "no match" to a filter it cannot read is how a
security test goes green on a query that never ran.

NOT A REAL SERVER: no indexes, no projections beyond pass-through, no
concurrency. Use it to prove who REACHES a handler, not how Mongo behaves.
"""
from __future__ import annotations

import copy
import re

from bson import ObjectId

_MISSING = object()


def _get(doc, path):
    cur = doc
    for p in path.split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return _MISSING
    return cur


def _eq(a, b):
    if isinstance(a, ObjectId) or isinstance(b, ObjectId):
        return str(a) == str(b)
    return a == b


def _cmp(val, op, arg):
    if op == "$ne":
        return not _eq(None if val is _MISSING else val, arg)
    if op == "$in":
        v = None if val is _MISSING else val
        if isinstance(v, list):
            return any(_eq(x, a) for x in v for a in arg)
        return any(_eq(v, a) for a in arg)
    if op == "$nin":
        return not _cmp(val, "$in", arg)
    if op == "$exists":
        return (val is not _MISSING) == bool(arg)
    if op in ("$gt", "$gte", "$lt", "$lte"):
        if val is _MISSING or val is None:
            return False
        return {"$gt": val > arg, "$gte": val >= arg,
                "$lt": val < arg, "$lte": val <= arg}[op]
    if op == "$regex":
        return val is not _MISSING and isinstance(val, str) and re.search(arg, val) is not None
    if op == "$options":
        return True
    raise NotImplementedError(f"async_fake_mongo: operator {op!r}")


def matches(doc, flt) -> bool:
    for k, v in (flt or {}).items():
        if k == "$or":
            if not any(matches(doc, f) for f in v):
                return False
            continue
        if k == "$and":
            if not all(matches(doc, f) for f in v):
                return False
            continue
        if k.startswith("$"):
            raise NotImplementedError(f"async_fake_mongo: top-level {k!r}")
        val = _get(doc, k)
        if isinstance(v, dict) and v and all(str(x).startswith("$") for x in v):
            if "$regex" in v and "i" in str(v.get("$options", "")):
                v = dict(v, **{"$regex": "(?i)" + v["$regex"]})
            if not all(_cmp(val, op, arg) for op, arg in v.items()):
                return False
        else:
            if val is _MISSING:
                if v is not None:
                    return False
            elif isinstance(val, list) and not isinstance(v, list):
                if not any(_eq(x, v) for x in val):
                    return False
            elif not _eq(val, v):
                return False
    return True


class _Result:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        self._docs = self._docs[:n] if n else self._docs
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self._docs]

    def __aiter__(self):
        self._it = iter([copy.deepcopy(d) for d in self._docs])
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class AsyncFakeCollection:
    def __init__(self, name):
        self.name = name
        self.docs: list = []
        self.writes: list = []

    def find(self, flt=None, projection=None, **kw):
        return _Cursor([d for d in self.docs if matches(d, flt)])

    async def find_one(self, flt=None, projection=None, **kw):
        for d in self.docs:
            if matches(d, flt):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, flt=None, **kw):
        return sum(1 for d in self.docs if matches(d, flt))

    async def insert_one(self, doc, **kw):
        doc.setdefault("_id", ObjectId())
        self.docs.append(copy.deepcopy(doc))
        self.writes.append(("insert", doc["_id"]))
        return _Result(inserted_id=doc["_id"])

    async def update_one(self, flt, update, upsert=False, **kw):
        for d in self.docs:
            if matches(d, flt):
                for k, v in (update.get("$set") or {}).items():
                    cur = d
                    parts = k.split(".")
                    for p in parts[:-1]:
                        cur = cur.setdefault(p, {})
                    cur[parts[-1]] = v
                for k in (update.get("$unset") or {}):
                    d.pop(k, None)
                self.writes.append(("update", d.get("_id")))
                return _Result(matched_count=1, modified_count=1, upserted_id=None)
        return _Result(matched_count=0, modified_count=0, upserted_id=None)

    async def update_many(self, flt, update, **kw):
        n = 0
        for d in self.docs:
            if matches(d, flt):
                await self.update_one({"_id": d["_id"]}, update)
                n += 1
        return _Result(matched_count=n, modified_count=n)

    async def create_index(self, *a, **k):
        return None


class AsyncFakeDB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def __getitem__(self, name):
        if name not in self._c:
            self._c[name] = AsyncFakeCollection(name)
        return self._c[name]

    async def list_collection_names(self):
        return list(self._c)
