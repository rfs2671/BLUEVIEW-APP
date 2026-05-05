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

const ENV =
  (typeof process !== 'undefined' && process.env && (
    process.env.EXPO_PUBLIC_ENVIRONMENT ||
    process.env.NEXT_PUBLIC_ENVIRONMENT ||
    process.env.NODE_ENV
  )) || 'development';

const DSN =
  (typeof process !== 'undefined' && process.env &&
    process.env.EXPO_PUBLIC_SENTRY_DSN) || '';

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
        // Drop CORS noise that comes through with a generic
        // "Network Error" message and no stack. These are almost
        // always misconfigured CORS preflights or browser-blocked
        // fetches that say nothing useful.
        try {
          const exc = (event && event.exception && event.exception.values) || [];
          for (const v of exc) {
            const t = String(v && v.type || '').toLowerCase();
            const msg = String(v && v.value || '').toLowerCase();
            if (
              t === 'error' &&
              (msg === 'network error' || msg === 'failed to fetch')
            ) {
              return null;
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
