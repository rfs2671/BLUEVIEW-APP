/**
 * NYC DOB Building Identification Number (BIN) validity.
 *
 * Mirrors the backend `_is_placeholder_bin` (server.py): a real BIN is exactly
 * 7 digits, borough-prefixed (first digit 1–5), and NOT a X000000 placeholder
 * (e.g. 2000000 for the Bronx) — DOB returns zero records against placeholders.
 *
 * ONE exported predicate consumed by both the project-screen BIN tile and the
 * DOB tab, so the two can never disagree on what counts as a real BIN.
 */
export function isValidBin(bin) {
  const s = String(bin == null ? '' : bin).trim();
  return /^[1-5]\d{6}$/.test(s) && s.slice(1) !== '000000';
}
