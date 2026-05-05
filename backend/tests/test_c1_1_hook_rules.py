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


def _build_fn_depth_table(text):
    """Pre-compute *function-body* nesting depth at every character
    position. fn_depth_at[i] is the number of nested function bodies
    that enclose position i.

    Critical distinction: brace-depth tracks every `{`/`}` regardless
    of context — `if (...) { return; }` opens a new brace-depth even
    though it's still inside the same function body. fn-depth only
    increments when we enter a NEW function body, identified by
    one of:
      - `=>` immediately preceding `{`  (arrow function body)
      - `function ... )` immediately preceding `{` (function expression
        or declaration)
      - method shorthand `name(args) {` inside an object literal
        (rare in our codebase; would also count as a nested fn)

    This lets the early-return scanner see returns inside if-blocks
    at the OUTER component body (fn_depth==1) as the early-return
    pattern that blocks rules-of-hooks compliance, while filtering
    out returns inside `useEffect(() => { return; })` callbacks
    (fn_depth==2).

    Returns: list of length len(text)+1, where entry [i] is the
    function-body nesting depth IMMEDIATELY BEFORE the character
    at position i. Top-level (file scope) is fn_depth=0.
    """
    n = len(text)
    fn_at = [0] * (n + 1)
    fn_depth = 0
    # Stack of bools — True if the matching `{` opened a function
    # body, False if it opened a control-flow block.
    brace_stack = []

    for i in range(n):
        fn_at[i] = fn_depth
        ch = text[i]
        if ch == "{":
            # Decide whether this `{` opens a function body. Look
            # backward (skipping whitespace) at the immediately
            # preceding non-whitespace token.
            j = i - 1
            while j >= 0 and text[j] in " \t\n\r":
                j -= 1
            is_fn = False
            if j >= 1 and text[j - 1] == "=" and text[j] == ">":
                # Arrow function: `=>` directly before `{`.
                is_fn = True
            elif j >= 0 and text[j] == ")":
                # `(args)` directly before `{`. Walk back to the
                # matching `(`, then check what precedes the parens.
                pdepth = 1
                k = j - 1
                while k >= 0 and pdepth > 0:
                    if text[k] == ")":
                        pdepth += 1
                    elif text[k] == "(":
                        pdepth -= 1
                    k -= 1
                # Skip whitespace before `(`.
                while k >= 0 and text[k] in " \t\n\r":
                    k -= 1
                # Optional identifier (function name or method name).
                while k >= 0 and (text[k].isalnum() or text[k] == "_" or text[k] == "$"):
                    k -= 1
                # Skip whitespace before identifier.
                while k >= 0 and text[k] in " \t\n\r":
                    k -= 1
                # Was this `function`?
                if k >= 7 and text[k - 7: k + 1] == "function":
                    is_fn = True
                # Otherwise: control-flow keyword (if, for, while,
                # switch, catch) followed by parens → NOT a function
                # body. Object method shorthand (`{ name(args) {} }`)
                # would slip through as a "no preceding function
                # keyword" path — we don't claim full coverage of
                # that edge case but it's rare in the screens we pin.
            brace_stack.append(is_fn)
            if is_fn:
                fn_depth += 1
        elif ch == "}":
            if brace_stack:
                if brace_stack.pop():
                    fn_depth -= 1
    fn_at[n] = fn_depth
    return fn_at


def _build_depth_table(text):
    """Pre-compute brace depth at every character position.
    Kept for backward compat; the early-return + try-block scanners
    below now use _build_fn_depth_table for nested-callback awareness.
    """
    depth_at = [0] * (len(text) + 1)
    d = 0
    for i, ch in enumerate(text):
        depth_at[i] = d
        if ch == "{":
            d += 1
        elif ch == "}":
            d -= 1
    depth_at[-1] = d
    return depth_at


def _find_hooks_after_early_return(text):
    """Find hook calls that appear AFTER an early `return …;`
    statement at the OUTER component body level.

    "Outer component body level" means: same enclosing function body
    as the component declaration itself, NOT inside a nested callback
    like `useEffect(() => { if (x) return; … })`. We track this via
    function-body nesting depth (fn_depth from _build_fn_depth_table)
    rather than brace depth — `if (cond) { return; }` inside the
    component body still counts as an early return at fn_depth==1
    even though brace depth is 2 there.

    This is the (b) pattern from the C1.1 spec — and the actual
    pattern that crashed production in C1.3 (DashboardScreen had a
    useState at line 226, AFTER an early `if (authLoading) return …;`
    at line 148). When auth resolved, the hook count jumped from 12
    to 14 and React error #310 fired.
    """
    cleaned = _strip_comments_and_strings(text)
    fn_at = _build_fn_depth_table(cleaned)
    violations = []

    # Match component-named functions only (uppercase first letter).
    # Two forms:
    #   function Name(args) { … }
    #   const Name = (args) => { … }
    # Both must be at the file's top level (fn-depth 0 at the brace).
    func_pattern = re.compile(
        r"(function\s+([A-Z]\w*)\s*\([^)]*\)|"
        r"const\s+([A-Z]\w*)\s*=\s*\([^)]*\)\s*=>)\s*\{",
    )

    for m in func_pattern.finditer(cleaned):
        brace_pos = m.end() - 1  # position of opening `{`
        if fn_at[brace_pos] != 0:
            # Nested component declaration — outer scan will cover it.
            continue

        name = m.group(2) or m.group(3)
        body_start = m.end()  # one past the opening `{`

        # Walk to the matching close brace via brace-balanced scan.
        d = 1
        i = body_start
        while i < len(cleaned) and d > 0:
            ch = cleaned[i]
            if ch == "{":
                d += 1
            elif ch == "}":
                d -= 1
            i += 1
        body_end = i - 1  # position of the matching `}`

        # The body's expected fn-nesting (immediately INSIDE the
        # component body) is fn_at[body_start].
        outer_fn_depth = fn_at[body_start]

        # Find the FIRST `return …;` at fn-depth == outer_fn_depth
        # (i.e. directly inside the component body, NOT in a nested
        # callback) AND followed by more body content (= early
        # return, not the trailing one).
        first_early_return_end = None
        for ret in re.finditer(r"\breturn\b", cleaned[body_start:body_end]):
            absolute_ret = body_start + ret.start()
            if fn_at[absolute_ret] != outer_fn_depth:
                continue  # nested callback — not relevant
            # Find the terminating `;`. Walk forward, tracking brace
            # depth (so we don't pick up a `;` inside a nested
            # function expression).
            j = absolute_ret + len("return")
            d2 = 0
            while j < body_end:
                ch = cleaned[j]
                if ch == "{":
                    d2 += 1
                elif ch == "}":
                    d2 -= 1
                elif ch == ";" and d2 == 0:
                    break
                j += 1
            if j >= body_end:
                continue
            # Trailing return? Skip whitespace after `;` and check
            # whether anything substantive follows.
            tail = cleaned[j + 1: body_end].strip()
            if not tail:
                continue
            first_early_return_end = j + 1
            break

        if first_early_return_end is None:
            continue

        # Any hook call at fn-depth == outer_fn_depth AFTER the early
        # return is a violation.
        for hook_match in _HOOK_CALL_PATTERN.finditer(
            cleaned[first_early_return_end:body_end]
        ):
            absolute_pos = first_early_return_end + hook_match.start()
            if fn_at[absolute_pos] != outer_fn_depth:
                continue  # nested — fine
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


def _all_frontend_component_files():
    """Phase C1.3 — every JSX screen under frontend/app/ plus every
    JS/JSX file under frontend/src/context/. The C1 incident showed
    that the original C1.1 scope (just _layout.jsx and AuthContext.js)
    was too narrow: the actual rules-of-hooks bug lived in
    DashboardScreen (frontend/app/index.jsx). Expand the pin to the
    whole component surface so the next latent violation is caught
    at test time, not at next-deploy time."""
    files = []
    files.extend(sorted((_FRONTEND / "app").rglob("*.jsx")))
    ctx = _FRONTEND / "src" / "context"
    if ctx.exists():
        files.extend(sorted(ctx.rglob("*.js")))
        files.extend(sorted(ctx.rglob("*.jsx")))
    return files


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


class TestC13ExpandedScopeWholeFrontend(unittest.TestCase):
    """Phase C1.3 — scan EVERY component file under frontend/app/
    and every context module under frontend/src/context/. The C1
    incident proved the original two-file pin (_layout.jsx +
    AuthContext.js) was too narrow: the production crash lived in
    DashboardScreen (frontend/app/index.jsx) and went undetected
    until source maps were wired. From now on, any hook-after-early-
    return or hook-in-try-block pattern anywhere in the app shell
    fails at test time."""

    def test_no_hooks_in_try_catch_anywhere(self):
        violations = []
        for f in _all_frontend_component_files():
            text = f.read_text(encoding="utf-8")
            hits = _find_hook_calls_in_try_blocks(text)
            for line, hook in hits:
                rel = f.relative_to(_REPO)
                violations.append(f"  {rel}:{line}  {hook}")
        self.assertEqual(
            violations, [],
            "Found hook calls inside try/catch in component files:\n"
            + "\n".join(violations) +
            "\nMove the hook outside the try/catch — wrap only its USE, "
            "not its CALL.",
        )

    def test_no_hooks_after_early_return_anywhere(self):
        violations = []
        for f in _all_frontend_component_files():
            text = f.read_text(encoding="utf-8")
            hits = _find_hooks_after_early_return(text)
            for line, hook, fn in hits:
                rel = f.relative_to(_REPO)
                violations.append(f"  {rel}:{line}  in {fn}  {hook}")
        self.assertEqual(
            violations, [],
            "Found hook calls after early-return in component files:\n"
            + "\n".join(violations) +
            "\nHoist all hooks above the first early-return inside the "
            "component body. The C1.3 incident — DashboardScreen had a "
            "useState 80 lines below `if (authLoading) return …;` — is "
            "exactly the pattern this test catches.",
        )


class TestC13DashboardScreenFix(unittest.TestCase):
    """Pin the specific shape of the C1.3 fix to DashboardScreen."""

    @classmethod
    def setUpClass(cls):
        cls.path = _FRONTEND / "app" / "index.jsx"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_first_poll_hooks_hoisted_above_early_return(self):
        """The three hooks added in B3 (dismissedBanners useState +
        AsyncStorage hydration useEffect + firstPollBannerProject
        useMemo) must live ABOVE the `if (authLoading)` early return,
        not below it. Track via line numbers."""
        lines = self.text.splitlines()
        # Find the `if (authLoading) {` early return and the hoisted
        # `dismissedBanners` useState. The latter must come first.
        early_return_line = None
        dismissed_banners_line = None
        first_poll_memo_line = None
        async_storage_effect_line = None
        for i, line in enumerate(lines, start=1):
            if "if (authLoading) {" in line and early_return_line is None:
                early_return_line = i
            if "dismissedBanners, setDismissedBanners" in line and dismissed_banners_line is None:
                dismissed_banners_line = i
            if "firstPollBannerProject = useMemo" in line and first_poll_memo_line is None:
                first_poll_memo_line = i
            if "bv_first_poll_dismissed" in line and "AsyncStorage.getItem" in line and async_storage_effect_line is None:
                async_storage_effect_line = i

        self.assertIsNotNone(early_return_line, "early return missing")
        self.assertIsNotNone(dismissed_banners_line, "dismissedBanners hook missing")
        self.assertIsNotNone(first_poll_memo_line, "firstPollBannerProject memo missing")
        self.assertIsNotNone(async_storage_effect_line, "AsyncStorage hydration effect missing")

        self.assertLess(
            dismissed_banners_line, early_return_line,
            f"dismissedBanners useState (line {dismissed_banners_line}) "
            f"must be ABOVE the early return (line {early_return_line})",
        )
        self.assertLess(
            async_storage_effect_line, early_return_line,
            f"AsyncStorage hydration useEffect (line {async_storage_effect_line}) "
            f"must be ABOVE the early return (line {early_return_line})",
        )
        self.assertLess(
            first_poll_memo_line, early_return_line,
            f"firstPollBannerProject useMemo (line {first_poll_memo_line}) "
            f"must be ABOVE the early return (line {early_return_line})",
        )


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
