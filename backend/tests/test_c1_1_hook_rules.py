"""Phase C1.1 — rules-of-hooks invariants for the app shell.

Pins the React rules-of-hooks compliance of the two files most
likely to break it: app/_layout.jsx (root layout, RouteGuard,
AppShell, ErrorBoundary) and src/context/AuthContext.js
(AuthProvider, useAuth).

Why static-source pins instead of running a JS test framework:
the repo runs Python pytest exclusively; a JS runner is
deliberately out-of-scope (see B0.1 design pin tests). Static
source checks catch the cheap regressions — a future commit
re-introducing a try/catch wrapper around a hook call, or moving
a hook below an early-return — before they reach production.

The bug C1.1 fixed: useToast() was called inside a try { } catch { }
block in RouteGuard. React error #310 ("Rendered fewer hooks than
expected") fired in production after C1's @sentry/react bundling
reorganized the module-load order enough to trip the latent
pattern. The test below pins the invariant going forward.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
_FRONTEND = _REPO / "frontend"


# Hook names we care about. Built-in React + the project's custom
# hooks (use* convention). The list is intentionally narrow —
# matching every "use*" identifier would catch utility functions
# like useStyles which aren't React hooks.
_REACT_HOOKS = (
    "useState",
    "useEffect",
    "useMemo",
    "useCallback",
    "useRef",
    "useContext",
    "useReducer",
    "useLayoutEffect",
    "useImperativeHandle",
    "useDebugValue",
    "useId",
    "useTransition",
    "useDeferredValue",
)

# Project-specific custom hooks that ALSO follow the rules.
# Adding a new custom hook? Append it here.
_PROJECT_HOOKS = (
    "useAuth",
    "useTheme",
    "useToast",
    "useRouter",
    "usePathname",
    "useLocalSearchParams",
    "useWindowDimensions",
    "useNavigation",
    "useFocusEffect",
)

_ALL_HOOK_NAMES = _REACT_HOOKS + _PROJECT_HOOKS

_HOOK_CALL_PATTERN = re.compile(
    r"\b(" + "|".join(_ALL_HOOK_NAMES) + r")\s*\("
)


def _strip_comments_and_strings(text):
    """Strip JS // and /* */ comments + string literals so the regex
    scan doesn't false-positive on hook-name mentions inside
    comments or strings (e.g. error messages that mention 'useToast').

    Not a full JS lexer — just enough to keep the invariant scan
    honest. Single-quoted, double-quoted, and template literals
    are replaced with placeholder spaces of equal length so line
    numbers (used in error messages) stay accurate.
    """
    # Block comments first.
    text = re.sub(
        r"/\*[\s\S]*?\*/",
        lambda m: " " * len(m.group(0)),
        text,
    )
    # Line comments.
    text = re.sub(
        r"//[^\n]*",
        lambda m: " " * len(m.group(0)),
        text,
    )
    # String literals (single, double, template). Replace contents
    # but keep line breaks for line-number stability inside
    # multi-line strings.
    def _blank(m):
        s = m.group(0)
        return "".join(" " if c != "\n" else "\n" for c in s)
    text = re.sub(r"'[^'\\\n]*(?:\\.[^'\\\n]*)*'", _blank, text)
    text = re.sub(r'"[^"\\\n]*(?:\\.[^"\\\n]*)*"', _blank, text)
    text = re.sub(r"`[\s\S]*?`", _blank, text)
    return text


def _find_hook_calls_in_try_blocks(text):
    """Return a list of (line_no, hook_name) for every hook call
    inside a try { ... } block. The check is balance-aware: it
    walks the source tracking brace depth from the `try` keyword
    until the matching close-brace.
    """
    cleaned = _strip_comments_and_strings(text)
    violations = []

    # Find every `try` keyword followed by `{`.
    for try_match in re.finditer(r"\btry\s*\{", cleaned):
        start = try_match.end()  # position right after the {
        depth = 1
        i = start
        while i < len(cleaned) and depth > 0:
            ch = cleaned[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        # Block body is cleaned[start:i-1].
        block = cleaned[start: i - 1]
        for hook_match in _HOOK_CALL_PATTERN.finditer(block):
            absolute_pos = start + hook_match.start()
            line_no = cleaned.count("\n", 0, absolute_pos) + 1
            violations.append((line_no, hook_match.group(1)))

    return violations


def _find_hooks_after_early_return(text):
    """Find component-level hook calls that appear after an early
    `return` statement INSIDE the same function body.

    Heuristic: walk each function body from `function Name(...) {`
    or `const Name = (...) => {` to its matching close brace, look
    for an early `return ...;` (not the trailing return), then any
    hook call after that point in the same function body is a
    violation.

    This is intentionally conservative — false-positive risk is
    higher than false-negative risk. We only care about the
    AppShell + RouteGuard + AuthProvider + useAuth surface area
    pinned by this test, and those are simple enough that the
    heuristic works.
    """
    cleaned = _strip_comments_and_strings(text)
    violations = []

    func_starts = []
    # Two function forms: classic `function Name(args) { ... }` and
    # arrow-with-component-name `const Name = (args) => { ... }`.
    # Both must be followed by `{` (allowing whitespace) before
    # the body starts.
    for m in re.finditer(
        r"(function\s+([A-Z]\w*)\s*\([^)]*\)|"
        r"const\s+([A-Z]\w*)\s*=\s*\([^)]*\)\s*=>)\s*\{",
        cleaned,
    ):
        name = m.group(2) or m.group(3)
        func_starts.append((m.end(), name))

    for start, name in func_starts:
        depth = 1
        i = start
        while i < len(cleaned) and depth > 0:
            ch = cleaned[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        body = cleaned[start: i - 1]

        # Find the FIRST `return ...;` that's followed by more
        # body content (i.e. it's not the trailing return).
        ret = re.search(r"\breturn\b[^;]*;", body)
        if not ret:
            continue
        after_first_return = body[ret.end():]
        # If everything after the first return is just whitespace
        # plus the function close, no early-return-then-hook
        # violation.
        if not after_first_return.strip():
            continue
        for hook_match in _HOOK_CALL_PATTERN.finditer(after_first_return):
            absolute_pos = start + ret.end() + hook_match.start()
            line_no = cleaned.count("\n", 0, absolute_pos) + 1
            violations.append((line_no, hook_match.group(1), name))

    return violations


# ──────────────────────────────────────────────────────────────────
# Pinned files
# ──────────────────────────────────────────────────────────────────


PINNED_FILES = [
    _FRONTEND / "app" / "_layout.jsx",
    _FRONTEND / "src" / "context" / "AuthContext.js",
]


class TestNoHooksInTryCatch(unittest.TestCase):
    """No useXxx() call may live inside a try { ... } block in
    the pinned files. This is the (d) pattern from the C1.1 spec —
    "Inside a try/catch where the hook only runs in one branch."
    """

    def test_layout_jsx_clean(self):
        text = (_FRONTEND / "app" / "_layout.jsx").read_text(encoding="utf-8")
        violations = _find_hook_calls_in_try_blocks(text)
        self.assertEqual(
            violations, [],
            f"Found hook calls inside try/catch in _layout.jsx: {violations}. "
            f"Move the hook outside the try/catch — wrap only its USE, "
            f"not its CALL.",
        )

    def test_auth_context_clean(self):
        text = (_FRONTEND / "src" / "context" / "AuthContext.js").read_text(
            encoding="utf-8"
        )
        violations = _find_hook_calls_in_try_blocks(text)
        self.assertEqual(
            violations, [],
            f"Found hook calls inside try/catch in AuthContext.js: "
            f"{violations}.",
        )


class TestNoHooksAfterEarlyReturn(unittest.TestCase):
    """No useXxx() call in the pinned files may live AFTER an early
    `return` statement inside the same function body. Pattern (b)
    from the spec.
    """

    def test_layout_jsx_clean(self):
        text = (_FRONTEND / "app" / "_layout.jsx").read_text(encoding="utf-8")
        violations = _find_hooks_after_early_return(text)
        self.assertEqual(
            violations, [],
            f"Found hook calls after early-return in _layout.jsx: "
            f"{violations}. Move all hook calls above the first "
            f"return statement inside the component body.",
        )

    def test_auth_context_clean(self):
        text = (_FRONTEND / "src" / "context" / "AuthContext.js").read_text(
            encoding="utf-8"
        )
        violations = _find_hooks_after_early_return(text)
        self.assertEqual(
            violations, [],
            f"Found hook calls after early-return in AuthContext.js: "
            f"{violations}.",
        )


# ──────────────────────────────────────────────────────────────────
# Sentinel checks — confirm the C1.1 fix landed as documented.
# ──────────────────────────────────────────────────────────────────


class TestC11FixSentinels(unittest.TestCase):
    """The C1.1 fix removed a try/catch wrapper around useToast()
    in RouteGuard AND made useToast() return null instead of
    throwing when ToastContext is missing. Pin both halves so a
    future revert doesn't silently re-introduce the bug."""

    def test_route_guard_calls_use_toast_unconditionally(self):
        text = (_FRONTEND / "app" / "_layout.jsx").read_text(encoding="utf-8")
        # The hook call must appear at top-of-component, not inside
        # try/catch. Easiest static-pin: assert the hook call is
        # present AND the C1-era try-wrapper is absent.
        self.assertIn("const toast = useToast();", text)
        self.assertNotIn("try {\n    toast = useToast();", text)
        # Also forbid the bare `toast = useToast()` assignment that
        # implies a let-binding inside try/catch.
        self.assertNotIn("    toast = useToast();", text)

    def test_use_toast_returns_null_instead_of_throwing(self):
        path = _FRONTEND / "src" / "components" / "Toast.js"
        text = path.read_text(encoding="utf-8")
        # The throwing branch must be gone. A regression that
        # re-adds it would force every consumer back into a
        # try/catch wrapper.
        self.assertNotIn(
            "throw new Error('useToast must be used within a ToastProvider')",
            text,
        )
        # The new shape: return useContext(ToastContext) || null.
        self.assertIn("useContext(ToastContext) || null", text)


# ──────────────────────────────────────────────────────────────────
# Unit-test the static-source helpers themselves.
# Without these, a regression in the regex would silently let bad
# code slip through future runs of the file-level invariants above.
# ──────────────────────────────────────────────────────────────────


class TestHelperHonesty(unittest.TestCase):

    def test_helper_detects_hook_in_try_block(self):
        sample = """
        function MyComponent() {
          let x = null;
          try {
            x = useState(0);
          } catch (_e) {}
          return null;
        }
        """
        violations = _find_hook_calls_in_try_blocks(sample)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][1], "useState")

    def test_helper_ignores_hook_in_string_literal(self):
        sample = """
        function MyComponent() {
          try {
            console.log("call useState");
          } catch (_e) {}
        }
        """
        violations = _find_hook_calls_in_try_blocks(sample)
        self.assertEqual(violations, [])

    def test_helper_ignores_hook_in_comment(self):
        sample = """
        function MyComponent() {
          try {
            // useState would be illegal here
            doStuff();
          } catch (_e) {}
        }
        """
        violations = _find_hook_calls_in_try_blocks(sample)
        self.assertEqual(violations, [])

    def test_helper_detects_hook_after_early_return(self):
        sample = """
        function MyComponent() {
          if (cond) return null;
          const [x, setX] = useState(0);
          return null;
        }
        """
        violations = _find_hooks_after_early_return(sample)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][1], "useState")

    def test_helper_allows_trailing_return_only(self):
        sample = """
        function MyComponent() {
          const [x, setX] = useState(0);
          return null;
        }
        """
        violations = _find_hooks_after_early_return(sample)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
