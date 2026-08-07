// ─── i18n — one translation layer for the Expo app ───────────────────────────
//
// WHY
//   Three hand-rolled EN/ES string maps shipped independently:
//     backend/checkin.html:456-647          87 keys per locale (worker kiosk,
//                                           a standalone HTML page — NOT
//                                           served by this bundle, left alone)
//     app/logbooks/review.jsx               47 keys per locale
//     src/components/SignaturePad.js         5 keys per locale
//   Each had its own lookup, its own fallback rule and its own idea of which
//   locale is current. SignaturePad's was the worst case: it took the locale
//   as a `lang` prop, and all 13 screens that render it pass nothing, so its
//   Spanish was unreachable in the shipped app.
//
// NO NEW DEPENDENCY
//   Pure JS + React state. Deliberately NOT expo-localization / i18n-js /
//   react-i18next: expo-localization carries a native module, so adding it
//   would force a native rebuild for what is a string-lookup change. Device
//   locale detection is therefore NOT available here — the locale is whatever
//   the app sets, defaulting to English.
//
// THE STORE IS MODULE-LEVEL, NOT A CONTEXT PROVIDER
//   A React context would have to be mounted in app/_layout.jsx and consumed
//   by every screen. This module keeps the locale in module scope with a
//   subscriber set instead, so a component can read and follow the locale with
//   no provider above it and no prop threaded through its call sites. That is
//   what lets SignaturePad reach Spanish without touching the 13 screens that
//   render it.
//
//   Consequence to know about: the locale is process-global and in-memory. It
//   is not persisted (no AsyncStorage write) and it is not per-screen. Setting
//   it on one screen sets it for the whole session.

import { useCallback, useEffect, useState } from 'react';
import en from './en';
import es from './es';

export const CATALOGUES = { en, es };
export const LOCALES = Object.keys(CATALOGUES);
export const DEFAULT_LOCALE = 'en';

let _locale = DEFAULT_LOCALE;
const _subscribers = new Set();

export function getLocale() {
  return _locale;
}

/** Set the app-wide locale. Unknown values fall back to DEFAULT_LOCALE. */
export function setLocale(next) {
  const resolved = CATALOGUES[next] ? next : DEFAULT_LOCALE;
  if (resolved === _locale) return _locale;
  _locale = resolved;
  // A throwing subscriber must not stop the others from updating.
  for (const fn of [..._subscribers]) {
    try { fn(resolved); } catch (_) { /* ignore */ }
  }
  return _locale;
}

/** Subscribe to locale changes. Returns an unsubscribe function. */
export function subscribeLocale(fn) {
  _subscribers.add(fn);
  return () => { _subscribers.delete(fn); };
}

/**
 * Look up one key.
 *
 * Fallback order — active locale, then English, then the key itself. That is
 * exactly what review.jsx's `TRANSLATIONS[lang][key] || TRANSLATIONS.en[key]
 * || key` did, and SignaturePad's `SIG_STRINGS[lang] || SIG_STRINGS.en` is the
 * same rule one level up. Returning the KEY on a miss is load-bearing:
 * review.jsx detects an unmapped backend reason code by testing
 * `t('reason_X') !== 'reason_X'`.
 *
 * hasOwnProperty rather than `||` so an intentionally empty string survives
 * instead of falling through to English. No current value is empty, so this
 * changes nothing today.
 */
export function translate(namespace, key, locale) {
  const active = CATALOGUES[locale] ? locale : _locale;
  const pick = (loc) => {
    const table = CATALOGUES[loc] && CATALOGUES[loc][namespace];
    return table && Object.prototype.hasOwnProperty.call(table, key)
      ? table[key]
      : undefined;
  };
  const hit = pick(active);
  if (hit !== undefined) return hit;
  const fallback = pick(DEFAULT_LOCALE);
  return fallback !== undefined ? fallback : key;
}

/** Current locale, re-rendering the component when it changes. */
export function useLocale() {
  const [locale, setLocaleState] = useState(getLocale);
  useEffect(() => {
    // Between the initial render and this effect the locale may already have
    // moved; re-read so a late-mounting component cannot latch a stale value.
    setLocaleState(getLocale());
    return subscribeLocale(setLocaleState);
  }, []);
  return locale;
}

/**
 * Namespaced translator. `t('title')` instead of `t('review.title')`, so a
 * migrated component's call sites stay byte-identical.
 *
 * `override` pins the translator to one locale regardless of the app-wide
 * value. It exists for components that still accept a locale prop
 * (SignaturePad's `lang`); pass undefined to follow the app.
 */
export function useT(namespace, override) {
  const active = useLocale();
  const locale = CATALOGUES[override] ? override : active;
  return useCallback((key) => translate(namespace, key, locale), [namespace, locale]);
}

export default {
  CATALOGUES,
  LOCALES,
  DEFAULT_LOCALE,
  getLocale,
  setLocale,
  subscribeLocale,
  translate,
  useLocale,
  useT,
};
