"""A CACHE KEYED ON THE RECORD CANNOT SEE THE RENDERER CHANGE.

Two caches serve the legal per-logbook PDF and both keyed on the record alone:
the site device names its offline copy from the log's own timestamp, and
`_logbook_thumbnail_url` keys its R2 object on `updated_at`. A filed log never
changes -- that is what filed means -- so neither key would move when the
renderer is restyled, and the new design would be invisible on the tablet an
inspector reads from and on the project record's thumbnails. Every document.
For ever.

WHAT THIS FILE GUARDS, AND WHAT IT DOES NOT. The dangerous half of the change
lives on the client and is asserted where it can be executed, in
`frontend/src/utils/rendererVersionSurvivesTheSweep.test.cjs`: the sweep's
keep-set is built from the manifest's stored row, so changing `v` in place
would make an old client's files unnameable and the next sweep would delete
them. That test runs the real sweep. This one holds the server's half: one
function computing the version, and three consumers that are not allowed to
disagree with it.
"""

from __future__ import annotations

import ast
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

_SRC = Path(server.__file__).read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)


def _func(name):
    for n in ast.walk(_TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} is not defined in server.py")


class TheVersionIsOneFunction(unittest.TestCase):

    def test_the_constant_exists_and_is_an_int(self):
        self.assertIsInstance(server.LEGAL_RENDERER_VERSION, int)

    def test_the_version_moves_when_the_RENDERER_moves(self):
        rec = {"updated_at": "2026-09-10T12:40:15.999000"}
        before = server._logbook_cache_version(rec)
        with patch.object(server, "LEGAL_RENDERER_VERSION",
                          server.LEGAL_RENDERER_VERSION + 1):
            after = server._logbook_cache_version(rec)
        self.assertNotEqual(before, after,
                            "a restyle would not move the cache key")

    def test_and_does_NOT_move_when_nothing_moves(self):
        """The other half. A version that changed on every call would
        re-render every thumbnail on every report, which is the cost the cache
        exists to avoid."""
        rec = {"updated_at": "2026-09-10T12:40:15.999000"}
        self.assertEqual(server._logbook_cache_version(rec),
                         server._logbook_cache_version(dict(rec)))

    def test_the_record_half_moves_when_the_RECORD_moves(self):
        a = server._logbook_cache_version({"updated_at": "2026-09-10T12:40:15"})
        b = server._logbook_cache_version({"updated_at": "2026-09-11T09:00:00"})
        self.assertNotEqual(a, b, "an amended log would serve the old picture")

    def test_the_precedence_is_the_CLIENTS(self):
        """docCache keys on `updated_at || submitted_at || created_at`. A
        different precedence here names the same file twice and leaves both on
        the tablet for ever -- which is exactly what `_manifest_version`'s own
        docstring says it exists to prevent."""
        self.assertEqual(
            server._logbook_record_stamp(
                {"updated_at": "A1", "submitted_at": "B2", "created_at": "C3"}),
            "A1")
        self.assertEqual(
            server._logbook_record_stamp({"submitted_at": "B2", "created_at": "C3"}),
            "B2")
        self.assertEqual(server._logbook_record_stamp({"created_at": "C3"}), "C3")

    def test_it_never_returns_an_empty_version(self):
        """An empty half would collapse every logbook's key onto one name."""
        for rec in ({}, {"updated_at": None}, {"updated_at": ""},
                    {"updated_at": "!!!!"}):
            v = server._logbook_cache_version(rec)
            self.assertTrue(v and not v.startswith("r"),
                            f"{rec!r} produced a version with no record half: {v!r}")

    def test_the_version_is_filename_safe(self):
        """The client sanitises non-alphanumerics into `_`. A version that
        needed sanitising would be one more conversion that could disagree."""
        v = server._logbook_cache_version(
            {"updated_at": "2026-09-10T12:40:15.999000+00:00"})
        self.assertRegex(v, r"^[A-Za-z0-9]+$")


class TheThreeConsumersAgree(unittest.TestCase):

    def test_the_thumbnail_key_is_built_from_the_cache_version(self):
        key = server._logbook_thumb_r2_key("abc123", "STAMPr7")
        self.assertIn("STAMPr7", key)
        self.assertTrue(key.startswith("report-thumbs/abc123/"))

    def test_the_thumbnail_url_asks_the_ONE_function_for_it(self):
        """Anchored on the call, not on a recomputation. The old code inlined
        its own `re.sub` on `updated_at`; a second inlining would drift from
        the client silently."""
        body = ast.dump(_func("_logbook_thumbnail_url"))
        self.assertIn("_logbook_cache_version", body,
                      "the thumbnail rebuilt the version instead of asking")
        self.assertNotIn("report-thumbs", body,
                         "the key is spelled out here as well as in the helper")

    def test_the_manifest_sends_rv_AND_LEAVES_v_ALONE(self):
        """THE SAFETY PROPERTY OF THE WHOLE CHANGE, asserted on the dict the
        endpoint builds.

        The client's stored manifest row carries only `cache_version`, built
        from `v`, and the sweep's keep-set is built from that. Replacing `v`
        would hand an old client -- which still names its files from the
        timestamp, because the app ships over the air and the API does not -- a
        keep-set naming a file that does not exist, and the next sweep would
        delete every offline logbook on the tablet.
        """
        src = _SRC[_SRC.index("    log_rows = ["):]
        src = src[:src.index("]") + 1]
        keys = set(ast.literal_eval(
            "{" + src[src.index("{") + 1:src.rindex("}")].replace(
                "str(rec.get(\"_id\", \"\"))", "'x'").replace(
                "_manifest_version(rec)", "'v'").replace(
                "_logbook_cache_version(rec)", "'rv'") + "}"))
        self.assertEqual(keys, {"id", "v", "rv"},
                         "the manifest row is no longer {id, v, rv}")
        self.assertIn("_manifest_version(rec)", src,
                      "`v` no longer comes from _manifest_version -- an old "
                      "client's files just became unnameable")

    def test_the_submitted_row_carries_the_cache_version(self):
        """Executed, not read. The endpoint is called with a fake collection so
        the row that actually reaches the tablet is the thing asserted."""
        log = {"_id": "abc", "date": "2026-09-10", "log_type": "daily_jobsite",
               "updated_at": "2026-09-10T12:40:15.999000", "status": "submitted"}

        class _Cur:
            def __init__(self, rows): self._rows = rows
            def sort(self, *a, **k): return self
            def skip(self, *a, **k): return self
            def limit(self, *a, **k): return self
            async def to_list(self, *a, **k): return list(self._rows)

        class _Logbooks:
            def find(self, *a, **k): return _Cur([dict(log)])
            async def distinct(self, *a, **k): return ["2026-09-10"]
            async def count_documents(self, *a, **k): return 1
            def aggregate(self, *a, **k): return _Cur(
                [{"_id": "2026-09-10", "n": 1}])

        class _DB:
            logbooks = _Logbooks()
            def __getattr__(self, _n): return _Logbooks()

        with patch.object(server, "db", _DB()):
            out = asyncio.run(server.get_submitted_logbooks(
                project_id="p1", before=None, limit=30))

        rows = [r for bucket in out["dates"].values() for r in bucket]
        self.assertTrue(rows, "the endpoint returned no rows to assert on")
        for r in rows:
            self.assertEqual(r.get("cache_version"),
                             server._logbook_cache_version(log),
                             "the row the tablet names its file from disagrees "
                             "with the server's own version")
            self.assertIn("updated_at", r,
                          "the row lost its timestamp -- the keep-set needs it "
                          "to keep an old client's file too")


if __name__ == "__main__":
    unittest.main(verbosity=2)
