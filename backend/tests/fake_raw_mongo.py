"""A Mongo stand-in that stores BSON BYTES, for testing scripts offline.

Only the operations the plan-discipline migration and rollback use, each with
Mongo's semantics for them:

  find / find_one / count_documents   equality filters on top-level fields
  update_one / update_many            `$set`, dotted paths; an existing field
                                      keeps its position, as on the server
  delete_many, insert_one, insert_many, replace_one

Documents are kept as `bytes` and handed back as RawBSONDocument, so a type
that does not survive BSON, a changed field order or a lost `_id` shows up as
a byte difference — which is what "byte-identical" in the rollback means.

NOT A REAL SERVER. It does not model indexes, concurrency, or a write that
fails half way. The scripts' own post-write checks are what cover those.
"""
from __future__ import annotations

from types import SimpleNamespace

import bson
from bson.raw_bson import RawBSONDocument


def _encode(doc) -> bytes:
    if isinstance(doc, RawBSONDocument):
        return bytes(doc.raw)
    doc = dict(doc)
    if "_id" not in doc:
        doc = {"_id": bson.ObjectId(), **doc}
    return bson.encode(doc)


def _matches(raw: bytes, flt) -> bool:
    doc = bson.decode(raw)
    return all(doc.get(k) == v for k, v in (flt or {}).items())


def _set(doc: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


class FakeCollection:
    def __init__(self, name):
        self.name = name
        self.docs: list = []

    # reads
    def find(self, flt=None, projection=None):
        return [RawBSONDocument(d) for d in self.docs if _matches(d, flt)]

    def find_one(self, flt=None, projection=None):
        got = self.find(flt)
        return got[0] if got else None

    def count_documents(self, flt=None):
        return len(self.find(flt))

    # writes
    def _update(self, flt, update, many):
        if set(update) != {"$set"}:
            raise NotImplementedError(update)
        matched = 0
        for i, raw in enumerate(self.docs):
            if not _matches(raw, flt):
                continue
            doc = bson.decode(raw)
            for path, value in update["$set"].items():
                _set(doc, path, value)
            new = bson.encode(doc)
            self.docs[i] = new
            matched += 1
            if not many:
                break
        return SimpleNamespace(matched_count=matched, modified_count=matched)

    def update_one(self, flt, update):
        return self._update(flt, update, False)

    def update_many(self, flt, update):
        return self._update(flt, update, True)

    def delete_many(self, flt):
        keep = [d for d in self.docs if not _matches(d, flt)]
        n = len(self.docs) - len(keep)
        self.docs = keep
        return SimpleNamespace(deleted_count=n)

    def insert_one(self, doc):
        raw = _encode(doc)
        self.docs.append(raw)
        return SimpleNamespace(inserted_id=bson.decode(raw)["_id"])

    def insert_many(self, docs):
        ids = [self.insert_one(d).inserted_id for d in docs]
        return SimpleNamespace(inserted_ids=ids)

    def replace_one(self, flt, doc):
        for i, raw in enumerate(self.docs):
            if _matches(raw, flt):
                self.docs[i] = _encode(doc)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    # for assertions
    def raw_sorted(self):
        return sorted(self.docs, key=lambda b: bson.decode(b)["_id"])


class FakeDB:
    def __init__(self):
        self._c = {}

    def __getitem__(self, name):
        return self._c.setdefault(name, FakeCollection(name))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]


class FakeClient:
    def __init__(self):
        self._dbs = {}

    def __getitem__(self, name):
        return self._dbs.setdefault(name, FakeDB())
