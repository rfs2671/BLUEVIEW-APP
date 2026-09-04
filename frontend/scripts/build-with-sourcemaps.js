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
  // EVERY HOST THIS REPO CLAIMS TO USE, because they do not agree and neither
  // does the repo. runbook.md says production is Cloudflare Pages; the only
  // checked-in host config is vercel.json; this file was written to read
  // VERCEL_GIT_COMMIT_SHA alone. On Cloudflare that variable is unset, the
  // release tag silently falls back to "development", and the source maps
  // uploaded under a real release match nothing that production ever sends.
  // Reading all three costs nothing and removes the release tag's dependence
  // on a question nobody in this repo answers the same way twice.
  const sha = process.env.VERCEL_GIT_COMMIT_SHA
    || process.env.CF_PAGES_COMMIT_SHA
    || process.env.GITHUB_SHA
    || '';
  if (sha) {
    process.env.EXPO_PUBLIC_VERCEL_GIT_COMMIT_SHA = sha;
    log(`release tag: ${sha}`);
  } else {
    log('no VERCEL_GIT_COMMIT_SHA / CF_PAGES_COMMIT_SHA / GITHUB_SHA — '
      + 'release tag falls back to "development" and version.json stamps empty');
  }

  // ── Step 2: the actual build ───────────────────────────────────
  // --source-maps tells Expo's CLI to pass serializerIncludeMaps +
  // includeSourceMaps through to Metro, which emits a `.map` file
  // alongside every `.js` chunk under dist/. Without this flag,
  // expo export defaults to map-less output (smaller dist, but
  // unsymbolicatable Sentry events).
  //
  // C1.2 shipped without this flag — the upload step ran and
  // hit Sentry successfully, but the build log said
  //   "could not determine a source map reference" and
  //   "removed 0 .map file(s)"
  // because there was nothing to upload.
  //
  // The flag has been part of the @expo/cli `export` command
  // since SDK 50 (legacy alias --dump-sourcemap; -s shorthand).
  run('npx', ['expo', 'export', '--platform', 'web', '--clear', '--source-maps']);

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
      'SENTRY_AUTH_TOKEN set but no commit SHA is available from any host; ' +
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

  // ── Step 6: say which commit this bundle IS ────────────────────
  //
  // THE BACKEND HAS HAD THIS ANSWER ALL ALONG. /api/version reports the
  // commit Railway is serving, which is how "the fix is deployed" gets
  // proved rather than assumed. The web build had no equivalent: nothing
  // in this repo could say when — or whether — a given commit reached
  // production, because the deploy runs through an external git
  // integration and no workflow observes it.
  //
  // That gap has a cost with a number on it. The CORS outage of
  // 2026-08-28 is recorded as "AT LEAST 6 days 22 hours" and cannot be
  // stated more precisely than that, because the commit date is all
  // anyone can read. This file is the counterpart:
  //
  //     curl https://www.levelog.com/version.json
  //
  // The SHA is the one already inlined into the bundle for the Sentry
  // release tag, so the file and the running code cannot disagree about
  // which build this is — a version stamp derived separately would be a
  // second source of truth and could be right while the bundle was old.
  writeVersionFile(sha);

  log('build complete');
}

function writeVersionFile(sha) {
  const payload = {
    // Empty, not "unknown", when the build had no SHA. A reader polling
    // for a specific commit must never match on a placeholder.
    commit: sha || '',
    short: sha ? sha.slice(0, 7) : '',
    built_at: new Date().toISOString(),
  };
  const dest = path.join(DIST, 'version.json');
  try {
    fs.mkdirSync(DIST, { recursive: true });
    fs.writeFileSync(dest, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
    log(`wrote ${dest} (${payload.short || 'no sha'})`);
  } catch (e) {
    // NOT FATAL. A deploy that ships without its stamp is worse observed,
    // not broken, and failing the build here would take the site down for
    // a diagnostic.
    log(`could not write version.json: ${e && e.message ? e.message : e}`);
  }
}

// Exported so writeVersionFile can be asserted without running a build; the
// build itself still runs on direct invocation exactly as before.
module.exports = { writeVersionFile, DIST };

if (require.main === module) {
  try {
    main();
  } catch (err) {
    log(`build failed: ${err && err.message ? err.message : err}`);
    process.exit(1);
  }
}
