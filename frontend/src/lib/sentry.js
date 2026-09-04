/**
 * Phase C1 — Sentry error tracking helper.
 *
 * Thin wrapper around @sentry/react with graceful degradation:
 * if EXPO_PUBLIC_SENTRY_DSN is unset (local dev, preview deploys
 * without Sentry plumbing), every helper here becomes a no-op.
 * No throws; no crashes.
 *
 * Why @sentry/react and not @sentry/react-native: this app is
 * deployed via `expo export --platform web` to Cloudflare Pages.
 * The bundle runs in the browser via react-native-web — pure
 * React DOM under the hood. @sentry/react-native carries native
 * (iOS/Android) build requirements we don't use. @sentry/browser
 * would also work; @sentry/react adds the ErrorBoundary helper
 * and React-specific integration.
 *
 * Tagging contract:
 *   • environment   — set on init from EXPO_PUBLIC_ENVIRONMENT
 *                      or 'development' fallback
 *   • user_email    — set after login via setSentryUser()
 *   • company_name  — set after login via setSentryUser()
 *
 * Sample rates (kept conservative for free tier):
 *   • tracesSampleRate     = 0.1   (10% transaction sampling)
 *   • replaysSessionRate   = 0     (replay disabled — bundle size)
 *   • replaysOnErrorRate   = 0
 *
 * PII discipline mirrors the backend's /api/auth/* + notification
 * preferences scrubbing: we never put plain-text passwords or
 * preference doc bodies into a Sentry event from the FE either —
 * @sentry/react default scrubbers cover obvious cases, and we
 * intentionally avoid pushing form state into breadcrumbs.
 */

import * as Sentry from '@sentry/react';

let _initialized = false;

// ── A TOTAL OUTAGE MUST NOT LOOK LIKE NOISE ────────────────────────────────
//
// `beforeSend` below used to `return null` for every "Network Error" /
// "Failed to fetch", with a comment naming "misconfigured CORS preflights" as
// the class being dropped. Axios raises precisely `Error: Network Error` when
// a preflight blocks the request. Between 2026-08-28 and 2026-09-04 the web
// build could not sign in — every request blocked before it was sent — and the
// only client channel that could have seen it discarded every event, on
// purpose, by a rule written by someone who had identified the category
// correctly.
//
// THE RULE WAS NOT WRONG ABOUT ONE EVENT. A single "Network Error" with no
// stack really does say nothing useful; a user in a tunnel produces them. It
// failed on VOLUME — and volume is exactly what a predicate over a single
// event cannot see. What separates an outage from the noise it resembles is
// rate, breadth and duration, none of which is a property of the event in hand.
//
// So the filter is kept, and stops being silent:
//
//   ONE ISSUE, NOT THOUSANDS. A fixed fingerprint collapses every one of these
//   into a single Sentry issue whose EVENT RATE is the signal. Alert on the
//   rate of that issue; never on an event.
//   LEVEL 'info', so it can never page anyone by existing. It is a graph to
//   read, not an error to triage.
//   SAMPLED, so the quota this file is careful about elsewhere
//   (tracesSampleRate 0.1, replays off) survives an outage that generates one
//   of these per request per user.
//   COUNTED PER SESSION, and the count rides on the sampled event. "the 412th
//   blocked request in this session" is not ambiguous the way one is.
//
// A breadcrumb was considered and rejected: a total blockade produces no other
// event to carry it. The app never gets far enough to throw anything else,
// which is why nothing surfaced for seven days.
const BLOCKED_REQUEST_SAMPLE_RATE = 0.01;
const BLOCKED_REQUEST_FINGERPRINT = 'client-request-blocked';
let _blockedThisSession = 0;

// Exported for the test, which executes this predicate rather than reading it.
export function _blockedRequestCount() { return _blockedThisSession; }

const ENV =
  (typeof process !== 'undefined' && process.env && (
    process.env.EXPO_PUBLIC_ENVIRONMENT ||
    process.env.NEXT_PUBLIC_ENVIRONMENT ||
    process.env.NODE_ENV
  )) || 'development';

const DSN =
  (typeof process !== 'undefined' && process.env &&
    process.env.EXPO_PUBLIC_SENTRY_DSN) || '';

// Phase C1.2 — release tag MUST match the release that
// scripts/build-with-sourcemaps.js uploads source maps under, so
// Sentry can resolve minified stack traces to readable file:line.
// Vercel auto-injects VERCEL_GIT_COMMIT_SHA at build time; the
// build wrapper copies it into the EXPO_PUBLIC_ namespace so
// metro inlines it into the runtime bundle. Falls back to
// 'development' when neither is set (local dev, forks, preview
// deploys without the build wrapper).
const RELEASE =
  (typeof process !== 'undefined' && process.env && (
    process.env.EXPO_PUBLIC_VERCEL_GIT_COMMIT_SHA ||
    process.env.EXPO_PUBLIC_SENTRY_RELEASE
  )) || 'development';

export function initSentry() {
  if (_initialized) return true;
  if (!DSN || !DSN.trim()) {
    // No DSN → graceful no-op. Don't print a noisy warning every
    // page-load in dev; one console.info on first call is plenty.
    if (typeof console !== 'undefined') {
      // eslint-disable-next-line no-console
      console.info(
        '[sentry] EXPO_PUBLIC_SENTRY_DSN not set; error tracking disabled',
      );
    }
    return false;
  }

  try {
    Sentry.init({
      dsn: DSN,
      environment: ENV,
      release: RELEASE,
      tracesSampleRate: 0.1,
      replaysSessionSampleRate: 0,
      replaysOnErrorSampleRate: 0,
      // We don't auto-attach user IP / cookies. We push user_email
      // and company_name explicitly via setSentryUser after login.
      sendDefaultPii: false,
      // Default integrations are fine; we're not using replay.
      // Don't override the default integrations list — Sentry's
      // own defaults already filter known browser-extension noise.
      beforeSend(event) {
        // A browser-blocked fetch — a refused CORS preflight, a dead network,
        // a tunnel. Individually useless; in volume it is the app being down.
        // See BLOCKED_REQUEST_SAMPLE_RATE above for why this is downgraded and
        // sampled rather than dropped.
        try {
          const exc = (event && event.exception && event.exception.values) || [];
          for (const v of exc) {
            const t = String(v && v.type || '').toLowerCase();
            const msg = String(v && v.value || '').toLowerCase();
            if (
              t === 'error' &&
              (msg === 'network error' || msg === 'failed to fetch')
            ) {
              _blockedThisSession += 1;
              if (Math.random() >= BLOCKED_REQUEST_SAMPLE_RATE) return null;
              // ONE ISSUE. The fingerprint is fixed, so every one of these
              // collapses into a single Sentry issue and the issue's event
              // rate — not any event — is what an alert reads.
              event.fingerprint = [BLOCKED_REQUEST_FINGERPRINT];
              event.level = 'info';
              event.tags = {
                ...(event.tags || {}),
                client_request_blocked: 'true',
              };
              event.extra = {
                ...(event.extra || {}),
                // THE NUMBER THAT SEPARATES AN OUTAGE FROM A TUNNEL. One
                // blocked request is a user with bad signal; four hundred in
                // one session is an app that cannot reach its API at all.
                blocked_this_session: _blockedThisSession,
                sample_rate: BLOCKED_REQUEST_SAMPLE_RATE,
              };
              return event;
            }
          }
        } catch (_e) { /* fall through with original event */ }
        return event;
      },
    });

    // Phase C1: capture unhandled promise rejections globally.
    // @sentry/react's default browser integration covers window
    // 'error' but not always 'unhandledrejection' across every
    // browser version, so we add an explicit listener as a
    // belt-and-suspenders fallback.
    if (typeof window !== 'undefined' && window.addEventListener) {
      window.addEventListener('unhandledrejection', (ev) => {
        try {
          Sentry.captureException(ev?.reason || new Error('Unhandled rejection'));
        } catch (_e) { /* noop */ }
      });
    }

    _initialized = true;
    return true;
  } catch (e) {
    // Sentry init failure must never crash the app shell.
    // eslint-disable-next-line no-console
    console.warn('[sentry] init failed:', e?.message || e);
    return false;
  }
}

export function setSentryUser({ email, company_name, role } = {}) {
  if (!_initialized) return;
  try {
    Sentry.setUser({
      // Email IS PII; we tag it because it's the unique-id our
      // ops folks actually use to find a user. The Sentry org's
      // PII setting controls visibility per-team.
      email: email || undefined,
    });
    if (company_name) Sentry.setTag('company_name', String(company_name));
    if (role) Sentry.setTag('role', String(role));
  } catch (_e) { /* noop */ }
}

export function clearSentryUser() {
  if (!_initialized) return;
  try {
    Sentry.setUser(null);
  } catch (_e) { /* noop */ }
}

export function captureException(err, context) {
  if (!_initialized) return;
  try {
    Sentry.captureException(err, context ? { contexts: { custom: context } } : undefined);
  } catch (_e) { /* noop */ }
}

export function isSentryInitialized() {
  return _initialized;
}

export default Sentry;
