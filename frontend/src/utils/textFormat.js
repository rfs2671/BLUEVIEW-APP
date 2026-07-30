/**
 * Display-time capitalization for report professionalism. NEVER mutates stored
 * data — apply only when RENDERING a value, never before saving. Mirrors the
 * backend _capitalize_first / _sentence_case in server.py, so a field reads the
 * same in the app and on the exported PDF.
 *
 * Two rules, not one:
 *   capitalizeFirst — short entry fields (company, trade, name, location,
 *     equipment): capitalize the first letter, preserve everything after exactly.
 *   sentenceCase — prose fields (activities, observations, notes, any
 *     multi-sentence textarea): capital after every terminal punctuation
 *     (. ! ?), rest preserved.
 *
 * Excluded (never pass through these): login username/password, emails,
 * card / OSHA / SST numbers, BIN, BBL, permit numbers, tag ids — any identifier
 * or code.
 */

export function capitalizeFirst(text) {
  const s = text == null ? '' : String(text);
  const i = s.search(/\S/);
  if (i < 0) return s;
  return s.slice(0, i) + s[i].toUpperCase() + s.slice(i + 1);
}

export function sentenceCase(text) {
  const s = text == null ? '' : String(text);
  let out = '';
  let capNext = true;
  for (const ch of s) {
    if (capNext && /[A-Za-z]/.test(ch)) {
      out += ch.toUpperCase();
      capNext = false;
    } else {
      out += ch;
      if (ch === '.' || ch === '!' || ch === '?') capNext = true;
    }
  }
  return out;
}
