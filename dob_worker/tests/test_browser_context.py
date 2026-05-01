"""Per-GC storage_state isolation + rotation."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DOB_WORKER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DOB_WORKER))


class TestStorageStateLifecycle(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["STORAGE_STATE_DIR"] = str(self.tmp)
        # Force module re-import to pick up env override.
        for k in list(sys.modules):
            if k.startswith("lib.browser_context"):
                del sys.modules[k]

    def test_per_gc_isolation(self):
        from lib import browser_context as bc
        # Same module-level constant reads at first import; reassign
        # for this test against the temp dir.
        bc.STORAGE_STATE_DIR = self.tmp

        # Two distinct GCs each get their own subdirectory.
        bc.save_meta("626198", {"request_count": 1, "license_number": "626198"})
        bc.save_meta("777777", {"request_count": 5, "license_number": "777777"})

        m1 = bc.load_meta("626198")
        m2 = bc.load_meta("777777")
        self.assertEqual(m1["request_count"], 1)
        self.assertEqual(m2["request_count"], 5)
        # Filesystem proves isolation.
        self.assertTrue((self.tmp / "626198" / "meta.json").exists())
        self.assertTrue((self.tmp / "777777" / "meta.json").exists())

    def test_increment_and_rotation_threshold(self):
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp
        bc.ROTATE_AFTER_REQUESTS = 5

        for _ in range(4):
            bc.increment_request_count("626198")
        self.assertFalse(bc.needs_rotation("626198"))
        bc.increment_request_count("626198")  # 5th
        self.assertTrue(bc.needs_rotation("626198"))

    def test_rotate_promotes_current_to_previous(self):
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp
        # Seed a current.json
        cur = self.tmp / "626198" / "current.json"
        cur.parent.mkdir(parents=True, exist_ok=True)
        cur.write_text('{"cookies": []}')
        bc.save_meta("626198", {"request_count": 200, "license_number": "626198"})

        bc.rotate("626198")
        # current.json gone, previous.json present with the same content.
        self.assertFalse(cur.exists())
        prev = self.tmp / "626198" / "previous.json"
        self.assertTrue(prev.exists())
        self.assertIn('"cookies"', prev.read_text())

        # Counter reset.
        meta = bc.load_meta("626198")
        self.assertEqual(meta["request_count"], 0)
        self.assertIsNotNone(meta["last_rotated_at"])

    def test_fall_back_to_previous(self):
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp
        prev = self.tmp / "626198" / "previous.json"
        prev.parent.mkdir(parents=True, exist_ok=True)
        prev.write_text('{"cookies": "prev-only"}')

        result = bc.fall_back_to_previous("626198")
        self.assertTrue(result)
        cur = self.tmp / "626198" / "current.json"
        self.assertTrue(cur.exists())
        self.assertIn("prev-only", cur.read_text())

    def test_fall_back_returns_false_when_no_previous(self):
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp
        self.assertFalse(bc.fall_back_to_previous("never-seen"))


# ── MR.11.1 — load-on-context-create + fallback path ──────────────

class TestWithBrowserContextLoadPath(unittest.TestCase):
    """Pins the contract that with_browser_context() loads
    storage_state when current.json exists and falls back to a
    fresh context (no storage_state kwarg) when it doesn't.
    Regression-evident: a future commit that flips the default
    direction (e.g. always loads, even when the file is missing
    — Playwright would raise) breaks these tests immediately."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["STORAGE_STATE_DIR"] = str(self.tmp)
        for k in list(sys.modules):
            if k.startswith("lib.browser_context"):
                del sys.modules[k]

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_loads_storage_state_when_file_exists(self):
        from unittest.mock import AsyncMock, MagicMock
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp

        # Pre-seed the storage_state file the way seed_storage_state.py
        # would (operator manual login).
        gc = "626198"
        gc_dir = self.tmp / gc
        gc_dir.mkdir(parents=True, exist_ok=True)
        seeded_file = gc_dir / "current.json"
        seeded_file.write_text(json.dumps({"cookies": [], "origins": []}))

        # Mock browser. new_context returns a mock context whose
        # storage_state(...) just records the save path call.
        ctx = MagicMock()
        ctx.storage_state = AsyncMock()
        ctx.close = AsyncMock()
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=ctx)

        async def fn(c):
            return "ok"

        result = self._run(bc.with_browser_context(browser, gc, fn))
        self.assertEqual(result, "ok")
        # new_context was called WITH storage_state kwarg pointing at
        # the seeded file — this is the load path the MR.11.1 seed
        # script populates.
        kwargs = browser.new_context.await_args.kwargs
        self.assertEqual(kwargs.get("storage_state"), str(seeded_file))

    def test_falls_back_to_fresh_when_file_missing(self):
        from unittest.mock import AsyncMock, MagicMock
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp

        # No file pre-seeded. Cold-start path.
        gc = "never-seeded"

        ctx = MagicMock()
        ctx.storage_state = AsyncMock()
        ctx.close = AsyncMock()
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=ctx)

        async def fn(c):
            return "ok"

        result = self._run(bc.with_browser_context(browser, gc, fn))
        self.assertEqual(result, "ok")
        # new_context was called WITHOUT storage_state kwarg (cold
        # start). Critical — passing storage_state=None or an empty
        # string to Playwright raises; the helper must just omit
        # the kwarg entirely.
        kwargs = browser.new_context.await_args.kwargs
        self.assertNotIn("storage_state", kwargs)

    def test_save_path_runs_after_fn_returns(self):
        """The handler depends on the save side-effect to
        propagate freshly-set login cookies forward to the next
        run. Confirm context.storage_state(path=...) is invoked
        with the expected target path after fn returns."""
        from unittest.mock import AsyncMock, MagicMock
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp

        gc = "save-target"
        ctx = MagicMock()
        ctx.storage_state = AsyncMock()
        ctx.close = AsyncMock()
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=ctx)

        async def fn(c):
            return "ok"

        self._run(bc.with_browser_context(browser, gc, fn))
        # The save call. Target path must be the per-GC current.json.
        ctx.storage_state.assert_awaited_once()
        kwargs = ctx.storage_state.await_args.kwargs
        self.assertEqual(
            kwargs.get("path"), str(self.tmp / gc / "current.json"),
        )


# ── MR.11.3 — preserve-on-failure save-gate ────────────────────────
#
# Background: the unconditional save in with_browser_context was
# overwriting the operator's hand-seeded session with whatever
# cookies a failed run left behind (typically Akamai block-page
# cookies on a 403). Today's MR.11.2 smoke run reduced a 26-cookie
# trusted seed to 21 cookies of post-block residue. These tests
# pin the new contract:
#
#   • status="failed" / "cancelled"  → DON'T call ctx.storage_state(path=...)
#   • status="filed" / "completed"   → DO call ctx.storage_state(path=...)
#   • non-HandlerResult return value → fall through to save (back-compat)


class TestSaveGateOnHandlerResult(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["STORAGE_STATE_DIR"] = str(self.tmp)
        for k in list(sys.modules):
            if k.startswith("lib.browser_context"):
                del sys.modules[k]

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def _make_ctx_browser(self):
        from unittest.mock import AsyncMock, MagicMock
        ctx = MagicMock()
        ctx.storage_state = AsyncMock()
        ctx.close = AsyncMock()
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=ctx)
        return ctx, browser

    def test_save_skipped_for_failed_handler_result(self):
        """The smoking gun: HandlerResult(status='failed') must NOT
        trigger the post-fn save. Otherwise the seed gets overwritten
        every time DOB NOW returns a 403 / login fails / cancellation
        fires."""
        from lib import browser_context as bc
        from lib.handler_types import HandlerResult
        bc.STORAGE_STATE_DIR = self.tmp
        ctx, browser = self._make_ctx_browser()

        async def fn(c):
            return HandlerResult(status="failed", detail="akamai_challenge")

        result = self._run(bc.with_browser_context(browser, "626198", fn))
        self.assertEqual(result.status, "failed")
        # The critical assertion: the save side-effect did NOT fire.
        ctx.storage_state.assert_not_awaited()

    def test_save_skipped_for_cancelled_handler_result(self):
        from lib import browser_context as bc
        from lib.handler_types import HandlerResult
        bc.STORAGE_STATE_DIR = self.tmp
        ctx, browser = self._make_ctx_browser()

        async def fn(c):
            return HandlerResult(status="cancelled", detail="cancelled_by_operator")

        self._run(bc.with_browser_context(browser, "626198", fn))
        ctx.storage_state.assert_not_awaited()

    def test_save_runs_for_filed_handler_result(self):
        """Successful runs DO save — that's how the next attempt
        gets cookies refreshed (CSRF tokens rotate, session
        timestamps advance, etc.)."""
        from lib import browser_context as bc
        from lib.handler_types import HandlerResult
        bc.STORAGE_STATE_DIR = self.tmp
        ctx, browser = self._make_ctx_browser()

        async def fn(c):
            return HandlerResult(
                status="filed",
                detail="DOB-9876543",
                metadata={"dob_confirmation_number": "DOB-9876543"},
            )

        self._run(bc.with_browser_context(browser, "626198", fn))
        ctx.storage_state.assert_awaited_once()
        kwargs = ctx.storage_state.await_args.kwargs
        self.assertEqual(
            kwargs.get("path"), str(self.tmp / "626198" / "current.json"),
        )

    def test_save_runs_for_completed_handler_result(self):
        from lib import browser_context as bc
        from lib.handler_types import HandlerResult
        bc.STORAGE_STATE_DIR = self.tmp
        ctx, browser = self._make_ctx_browser()

        async def fn(c):
            return HandlerResult(status="completed", detail="ok")

        self._run(bc.with_browser_context(browser, "626198", fn))
        ctx.storage_state.assert_awaited_once()

    def test_save_runs_for_non_handler_result_return(self):
        """Back-compat: tests + non-handler callers that return a
        plain string / dict-without-status don't get the save-gate.
        Default behavior preserved."""
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp
        ctx, browser = self._make_ctx_browser()

        async def fn(c):
            return "ok"

        self._run(bc.with_browser_context(browser, "626198", fn))
        ctx.storage_state.assert_awaited_once()

    def test_save_skipped_for_dict_with_failed_status(self):
        """Some legacy paths return a dict instead of HandlerResult.
        The gate should respect that shape too."""
        from lib import browser_context as bc
        bc.STORAGE_STATE_DIR = self.tmp
        ctx, browser = self._make_ctx_browser()

        async def fn(c):
            return {"status": "failed", "detail": "anything"}

        self._run(bc.with_browser_context(browser, "626198", fn))
        ctx.storage_state.assert_not_awaited()

    def test_request_count_increments_even_when_save_skipped(self):
        """Request count tracks ATTEMPTS, not successes — otherwise
        rotation cadence drifts when a worker hits a streak of
        failures."""
        from lib import browser_context as bc
        from lib.handler_types import HandlerResult
        bc.STORAGE_STATE_DIR = self.tmp
        ctx, browser = self._make_ctx_browser()

        async def fn(c):
            return HandlerResult(status="failed", detail="login_failed")

        before = bc.load_meta("626198").get("request_count", 0)
        self._run(bc.with_browser_context(browser, "626198", fn))
        after = bc.load_meta("626198").get("request_count", 0)
        self.assertEqual(after, before + 1)


class TestContextArgsApplied(unittest.TestCase):
    """MR.11.3 — every per-GC context inherits the shared
    fingerprint config so the seed script and the worker present
    identical browser identity to Akamai."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["STORAGE_STATE_DIR"] = str(self.tmp)
        for k in list(sys.modules):
            if k.startswith("lib.browser_context") or k.startswith("lib.browser_launch"):
                del sys.modules[k]

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_new_context_called_with_shared_user_agent_and_viewport(self):
        from unittest.mock import AsyncMock, MagicMock
        from lib import browser_context as bc
        from lib import browser_launch as bl
        bc.STORAGE_STATE_DIR = self.tmp

        ctx = MagicMock()
        ctx.storage_state = AsyncMock()
        ctx.close = AsyncMock()
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=ctx)

        async def fn(c):
            return "ok"

        self._run(bc.with_browser_context(browser, "626198", fn))
        kwargs = browser.new_context.await_args.kwargs
        # The same UA + viewport the seed script will use.
        self.assertEqual(kwargs.get("user_agent"), bl.USER_AGENT)
        self.assertEqual(kwargs.get("viewport"), bl.VIEWPORT)
        self.assertEqual(kwargs.get("locale"), bl.LOCALE)
        self.assertEqual(kwargs.get("timezone_id"), bl.TIMEZONE_ID)


if __name__ == "__main__":
    unittest.main()
