"""What keeps tile serving cheap.

A deep zoom asks for dozens of tiles at once. Each tile is immutable (its R2 key
names its build), so three things avoid doing the work twice:

  * the browser / app caches it for a year (Cache-Control: private, immutable) and
    revalidates with If-None-Match, answered 304 here without touching R2;
  * a small in-process LRU holds recently served tiles, so a second reader of the
    same drawing (or the same reader after clearing their cache) does not re-download
    from R2;
  * the per-request tenancy decision (project access + same company + device
    allow-list) is remembered for a few seconds per (user, project, file), so a
    burst of tile requests is one authorization, not forty.

The decision cache is deliberately short. Revoking someone's access takes effect
within AUTH_TTL_SECONDS on tile reads; the manifest, the index and every write
re-check from the database every time.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Hashable, Optional, Tuple

AUTH_TTL_SECONDS = 20.0
AUTH_MAX_ENTRIES = 4000
BYTES_BUDGET = 64 * 1024 * 1024
IMMUTABLE = "private, max-age=31536000, immutable"


def etag_for(*parts: Any) -> str:
    """A strong validator for an immutable object: its build and coordinates name it."""
    return '"' + "-".join(str(p) for p in parts) + '"'


def matches_etag(if_none_match: Optional[str], etag: str) -> bool:
    """Does an If-None-Match header (a list, possibly weak, possibly `*`) name `etag`?"""
    if not if_none_match:
        return False
    for token in if_none_match.split(","):
        t = token.strip()
        if t == "*" or t == etag or (t.startswith("W/") and t[2:] == etag):
            return True
    return False


class DecisionCache:
    """(user, project, file) -> the file record that passed the tenancy checks, for a few seconds."""

    def __init__(self, ttl: float = AUTH_TTL_SECONDS, max_entries: int = AUTH_MAX_ENTRIES,
                 clock: Callable[[], float] = time.monotonic):
        self.ttl, self.max_entries, self.clock = ttl, max_entries, clock
        self._d: "OrderedDict[Hashable, Tuple[float, Any]]" = OrderedDict()

    def get(self, key: Hashable) -> Any:
        hit = self._d.get(key)
        if not hit:
            return None
        if hit[0] <= self.clock():
            self._d.pop(key, None)
            return None
        return hit[1]

    def put(self, key: Hashable, value: Any) -> None:
        self._d[key] = (self.clock() + self.ttl, value)
        self._d.move_to_end(key)
        while len(self._d) > self.max_entries:
            self._d.popitem(last=False)

    def forget_file(self, file_id: str) -> None:
        for k in [k for k in self._d if isinstance(k, tuple) and len(k) == 3 and k[2] == file_id]:
            self._d.pop(k, None)


class ByteLru:
    """Recently served objects, bounded by total bytes."""

    def __init__(self, budget: int = BYTES_BUDGET):
        self.budget, self.used = budget, 0
        self._d: "OrderedDict[str, bytes]" = OrderedDict()

    def get(self, key: str) -> Optional[bytes]:
        v = self._d.get(key)
        if v is not None:
            self._d.move_to_end(key)
        return v

    def put(self, key: str, value: bytes) -> None:
        if len(value) > self.budget // 4:                      # one object never takes a quarter of the cache
            return
        old = self._d.pop(key, None)
        if old is not None:
            self.used -= len(old)
        self._d[key] = value
        self.used += len(value)
        while self.used > self.budget and self._d:
            _k, v = self._d.popitem(last=False)
            self.used -= len(v)

    def drop_prefix(self, prefix: str) -> None:
        for k in [k for k in self._d if k.startswith(prefix)]:
            self.used -= len(self._d.pop(k))
