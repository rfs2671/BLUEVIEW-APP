"""Phase C1.2 — Sentry source-map upload pipeline.

Static-source pins for the production build wrapper that
uploads source maps to Sentry. The wrapper lives at
frontend/scripts/build-with-sourcemaps.js; package.json's
scripts.build invokes it.

Why these tests matter: source-map symbolication is the
difference between a Sentry event that says
`at MyComponent (frontend/app/some/file.jsx:42:10)` and one
that says `at t.j (chunk-abc.js:1:1234)`. The former is
debuggable; the latter is essentially noise. A future commit
that breaks the build wrapper or unlinks its invocation from
package.json would silently regress every production crash
we ship after that.

Hard rule pinned here: source maps must NEVER be served
publicly. The wrapper deletes them from dist/ AFTER upload.
A regression that drops the delete step means
www.levelog.com starts serving .map files — exposing
pre-mangled identifiers and (depending on bundler config)
embedded source code.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
_FRONTEND = _REPO / "frontend"


# ──────────────────────────────────────────────────────────────────
# package.json — devDep + scripts.build
# ──────────────────────────────────────────────────────────────────


class TestPackageJsonWiring(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _FRONTEND / "package.json"
        cls.text = cls.path.read_text(encoding="utf-8")
        cls.pkg = json.loads(cls.text)

    def test_sentry_cli_in_dev_dependencies(self):
        dev = self.pkg.get("devDependencies", {})
        self.assertIn(
            "@sentry/cli", dev,
            "Phase C1.2 requires @sentry/cli as a dev dependency for "
            "the source-map upload step in the build wrapper.",
        )

    def test_sentry_cli_pinned_to_v2(self):
        ver = self.pkg["devDependencies"]["@sentry/cli"]
        # Pin to ^2.x so we don't auto-upgrade past the v2 line on
        # `npm install`. The v2 line is what the build script's
        # `sourcemaps inject` + `sourcemaps upload` subcommand
        # surface targets — v3 (when it ships) may rework the CLI.
        self.assertTrue(
            ver.startswith("^2.") or ver.startswith("~2.") or ver.startswith("2."),
            f"@sentry/cli version {ver!r} should be pinned to the v2 line",
        )

    def test_build_script_invokes_wrapper(self):
        scripts = self.pkg.get("scripts", {})
        build = scripts.get("build", "")
        self.assertIn(
            "scripts/build-with-sourcemaps.js", build,
            "package.json scripts.build must invoke the C1.2 build "
            "wrapper. Without the wrapper, source maps don't upload "
            "and Sentry shows minified stacks.",
        )

    def test_expo_only_escape_hatch_present(self):
        """A `build:expo-only` script lets developers run the bare
        expo export without the Sentry pipeline (e.g. for fast local
        rebuilds or CI smoke tests). Pin its presence so the escape
        hatch survives future cleanups."""
        scripts = self.pkg.get("scripts", {})
        self.assertIn("build:expo-only", scripts)
        self.assertIn("expo export", scripts["build:expo-only"])


# ──────────────────────────────────────────────────────────────────
# build-with-sourcemaps.js — wrapper script content
# ──────────────────────────────────────────────────────────────────


class TestBuildWrapperContent(unittest.TestCase):
    """Static-source pins for the build wrapper. We don't execute
    it (would require a real Vercel build env + Sentry token);
    we pin the contract via source-level checks."""

    @classmethod
    def setUpClass(cls):
        cls.path = _FRONTEND / "scripts" / "build-with-sourcemaps.js"
        cls.text = cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""

    def test_file_present(self):
        self.assertTrue(self.path.exists(), str(self.path))

    def test_runs_expo_export(self):
        self.assertIn("expo", self.text)
        self.assertIn("'export'", self.text)
        self.assertIn("'--platform'", self.text)
        self.assertIn("'web'", self.text)

    def test_passes_source_maps_flag_to_expo_export(self):
        """Phase C1.2.1 — Expo's `expo export` command does NOT
        emit source maps by default. Without the --source-maps
        flag, the dist/ tree contains zero .map files and the
        Sentry CLI upload at the next step has nothing to ship.
        C1.2 was bitten by this: the upload ran but reached Sentry
        with zero artifacts, so events never resolved to readable
        stacks.

        The --source-maps flag has been part of @expo/cli's export
        command since SDK 50 (legacy alias --dump-sourcemap; -s
        shorthand). Pinning the long-form here so a future
        cleanup that "shortens" the args list doesn't silently
        regress the symbolication pipeline."""
        self.assertIn("'--source-maps'", self.text)

    def test_uses_sentry_cli_inject_and_upload(self):
        # Both subcommands MUST be present — inject without upload
        # leaves orphaned debug IDs in the bundle; upload without
        # inject means events never resolve to source.
        self.assertIn("'inject'", self.text)
        self.assertIn("'upload'", self.text)
        self.assertIn("'sourcemaps'", self.text)
        self.assertIn("@sentry/cli", self.text)

    def test_passes_release_flag(self):
        # The release flag is what links uploaded maps to runtime
        # events. Without it, Sentry can't symbolicate.
        self.assertIn("'--release'", self.text)

    def test_org_and_project_slugs_pinned(self):
        # Hard-coding the slugs in the script means a fork of the
        # repo can swap them with a single edit; ENV-var-driven
        # slugs would be needlessly indirect for a v1 setup.
        self.assertIn("'levelog'", self.text)            # SENTRY_ORG
        self.assertIn("'levelog-frontend'", self.text)   # SENTRY_PROJECT

    def test_handles_missing_auth_token_gracefully(self):
        """The build MUST complete when SENTRY_AUTH_TOKEN is unset
        (forks, preview deploys without secrets). Pin via static
        source check that the wrapper guards on the token."""
        self.assertIn("SENTRY_AUTH_TOKEN", self.text)
        # Look for the graceful no-op log line — proves the
        # codepath exists.
        self.assertIn("skipping source map upload", self.text)

    def test_copies_sha_to_expo_public_namespace(self):
        """Vercel's VERCEL_GIT_COMMIT_SHA is available to the
        build but NOT inlined into the browser bundle by Expo.
        The wrapper copies it into EXPO_PUBLIC_VERCEL_GIT_COMMIT_SHA
        BEFORE running expo export so metro can inline it. Without
        this step, the runtime Sentry.init() release tag falls
        back to "development" and source maps don't apply."""
        self.assertIn("EXPO_PUBLIC_VERCEL_GIT_COMMIT_SHA", self.text)
        self.assertIn("VERCEL_GIT_COMMIT_SHA", self.text)

    def test_deletes_map_files_from_dist(self):
        """Hard rule: source maps NEVER served publicly. The
        wrapper deletes every *.map under dist/ after the upload
        step. A regression here would let www.levelog.com serve
        the maps directly."""
        self.assertIn("'.map'", self.text)
        self.assertIn("unlinkSync", self.text)
        # Helper function that walks dist/.
        self.assertIn("deleteSourceMapsRecursive", self.text)

    def test_map_deletion_runs_unconditionally(self):
        """Even when SENTRY_AUTH_TOKEN is unset (no upload), the
        delete step must still run so we never serve maps. Pin
        via the comment that captures the invariant — checks for
        the explicit 'ALWAYS runs' phrasing."""
        self.assertIn("ALWAYS runs", self.text)


# ──────────────────────────────────────────────────────────────────
# sentry.js — release field threaded through Sentry.init()
# ──────────────────────────────────────────────────────────────────


class TestSentryReleaseTag(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _FRONTEND / "src" / "lib" / "sentry.js"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_release_constant_reads_expo_public_sha(self):
        # The runtime release MUST come from the same source that
        # the build wrapper uses, so the two agree.
        self.assertIn("EXPO_PUBLIC_VERCEL_GIT_COMMIT_SHA", self.text)
        self.assertIn("RELEASE", self.text)

    def test_init_passes_release(self):
        # Sentry.init() must receive the release. Without this,
        # source-map symbolication silently fails because Sentry
        # has no release ID to look up.
        # The pin checks for `release: RELEASE` in the init call.
        self.assertIn("release: RELEASE", self.text)

    def test_release_falls_back_to_development(self):
        """Local dev / forks / preview deploys without the build
        wrapper need a sane fallback so Sentry still groups events
        somehow (just won't symbolicate them)."""
        self.assertIn("'development'", self.text)


# ──────────────────────────────────────────────────────────────────
# Runbook coverage
# ──────────────────────────────────────────────────────────────────


class TestRunbookCoverage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = _REPO / "docs" / "operations" / "runbook.md"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_source_maps_section_present(self):
        # Required heading + verification steps so the next
        # operator on call can wire SENTRY_AUTH_TOKEN without
        # reverse-engineering the build wrapper.
        self.assertIn("## 10. Sentry source maps", self.text)
        self.assertIn("How to get a Sentry auth token", self.text)
        self.assertIn("How to set it on Vercel", self.text)
        self.assertIn("How to verify upload worked", self.text)

    def test_auth_token_in_env_inventory(self):
        self.assertIn("SENTRY_AUTH_TOKEN", self.text)
        self.assertIn("EXPO_PUBLIC_VERCEL_GIT_COMMIT_SHA", self.text)

    def test_security_invariant_noted(self):
        """Source maps must never be served publicly. The runbook
        should call this out so future operators don't accidentally
        bypass the delete step."""
        self.assertIn("must NEVER be served", self.text)


if __name__ == "__main__":
    unittest.main()
