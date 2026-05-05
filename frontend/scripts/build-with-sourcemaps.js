#!/usr/bin/env node
/**
 * Phase C1.2 — Production build wrapper that uploads source maps
 * to Sentry, then deletes them from the public dist/ tree.
 *
 * Why this exists: production stack traces are minified, so when
 * a React error fires (e.g. error #310 from the C1 / C1.1 deploys),
 * the Sentry event shows opaque single-letter function names and
 * unmapped column offsets. Source maps let Sentry resolve those
 * back to real file:line:column references. We upload them via
 * @sentry/cli at build time, then delete the .map files from
 * dist/ so they're never served from www.levelog.com.
 *
 * Build sequence:
 *   1. (Pre-step) Copy VERCEL_GIT_COMMIT_SHA → EXPO_PUBLIC_VERCEL_GIT_COMMIT_SHA
 *      so the bundle's runtime sentry.init() can stamp events with
 *      a release that matches what we upload below. The two MUST
 *      agree — Sentry won't surface source maps for an event whose
 *      `release` doesn't match an uploaded release.
 *   2. expo export --platform web --clear  (existing build)
 *   3. sentry-cli sourcemaps inject ./dist (only if SENTRY_AUTH_TOKEN
 *      is set — graceful no-op for forks / preview deploys)
 *   4. sentry-cli sourcemaps upload --org/project/release ./dist
 *   5. Delete every *.map file under ./dist (always, regardless of
 *      whether step 3-4 ran). Hard rule: source maps must NEVER be
 *      publicly served.
 *
 * Cross-platform: written in plain Node so it runs on the Linux
 * Vercel build container AND on a developer's Windows / macOS
 * machine when smoke-testing locally.
 */

'use strict';

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const FRONTEND_ROOT = path.resolve(__dirname, '..');
const DIST = path.join(FRONTEND_ROOT, 'dist');

// Sentry org + project slugs. Adjust if you create a new project.
// org slug appears in URLs like https://<org>.sentry.io/.
const SENTRY_ORG = 'levelog';
const SENTRY_PROJECT = 'levelog-frontend';

function log(msg) {
  // Prefix every log with a tag so the Vercel build log is easy
  // to grep when something goes wrong.
  console.log(`[c1.2-build] ${msg}`);
}

function run(cmd, args, opts = {}) {
  log(`$ ${cmd} ${args.join(' ')}`);
  const result = spawnSync(cmd, args, {
    stdio: 'inherit',
    cwd: FRONTEND_ROOT,
    shell: false,
    ...opts,
  });
  if (result.status !== 0) {
    throw new Error(
      `command failed (exit ${result.status}): ${cmd} ${args.join(' ')}`,
    );
  }
}

function runAllowFail(cmd, args) {
  log(`$ ${cmd} ${args.join(' ')}  (allow-fail)`);
  const result = spawnSync(cmd, args, {
    stdio: 'inherit',
    cwd: FRONTEND_ROOT,
    shell: false,
  });
  return result.status === 0;
}

function deleteSourceMapsRecursive(dir) {
  if (!fs.existsSync(dir)) return 0;
  let count = 0;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      count += deleteSourceMapsRecursive(full);
    } else if (entry.isFile() && entry.name.endsWith('.map')) {
      fs.unlinkSync(full);
      count += 1;
    }
  }
  return count;
}

function main() {
  // ── Step 1: env var copy ───────────────────────────────────────
  // Vercel's auto-injected VERCEL_GIT_COMMIT_SHA is available to
  // the build process but NOT to the runtime browser bundle.
  // Expo's metro bundler inlines process.env.EXPO_PUBLIC_* at build
  // time; we copy the SHA into that namespace BEFORE invoking
  // expo export so the resulting bundle has it baked in.
  const sha = process.env.VERCEL_GIT_COMMIT_SHA || '';
  if (sha) {
    process.env.EXPO_PUBLIC_VERCEL_GIT_COMMIT_SHA = sha;
    log(`release tag: ${sha}`);
  } else {
    log('VERCEL_GIT_COMMIT_SHA unset — release tag will fall back to "development"');
  }

  // ── Step 2: the actual build ───────────────────────────────────
  run('npx', ['expo', 'export', '--platform', 'web', '--clear']);

  // ── Steps 3-4: source map upload ───────────────────────────────
  // Conditional on SENTRY_AUTH_TOKEN — forks and preview deploys
  // without secrets still get a working build, just no upload.
  const authToken = (process.env.SENTRY_AUTH_TOKEN || '').trim();
  if (!authToken) {
    log(
      'SENTRY_AUTH_TOKEN not set — skipping source map upload ' +
      '(graceful: forks / previews without secrets still build)',
    );
  } else if (!sha) {
    // We have a token but no release identifier — uploading would
    // produce an "unreleased" upload that Sentry can't match to
    // events. Fail loud rather than ship orphan maps.
    log(
      'SENTRY_AUTH_TOKEN set but VERCEL_GIT_COMMIT_SHA is missing; ' +
      'refusing to upload source maps without a release tag',
    );
  } else {
    log(`uploading source maps to Sentry for release ${sha}`);
    // Inject release IDs into the bundled JS so Sentry can match
    // them at event-ingest time.
    run('npx', [
      '@sentry/cli', 'sourcemaps', 'inject',
      '--org', SENTRY_ORG,
      '--project', SENTRY_PROJECT,
      '--release', sha,
      DIST,
    ]);
    // Upload. Pass --release so the maps land under the same ID
    // the runtime sentry.init() will stamp on events.
    const uploaded = runAllowFail('npx', [
      '@sentry/cli', 'sourcemaps', 'upload',
      '--org', SENTRY_ORG,
      '--project', SENTRY_PROJECT,
      '--release', sha,
      DIST,
    ]);
    if (uploaded) {
      log(`Uploaded source maps for release ${sha}`);
    } else {
      // Soft-fail: the build itself shouldn't break because Sentry
      // returned a 4xx. We log the failure and continue so the
      // deploy still ships a working site (just without nicely
      // resolved stacks for the next ~hour until the next deploy).
      log('source map upload failed; continuing without symbolication');
    }
  }

  // ── Step 5: nuke source maps from dist ─────────────────────────
  // ALWAYS runs, regardless of whether upload happened. Source
  // maps must not be publicly served — they reveal pre-mangled
  // identifiers and (depending on bundler config) embedded source
  // code. Deleting after upload preserves the Sentry side without
  // exposing the public surface.
  const removed = deleteSourceMapsRecursive(DIST);
  log(`removed ${removed} .map file(s) from ${DIST}`);

  log('build complete');
}

try {
  main();
} catch (err) {
  log(`build failed: ${err && err.message ? err.message : err}`);
  process.exit(1);
}
