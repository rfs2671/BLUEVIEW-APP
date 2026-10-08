/**
 * The app header wordmark (components/HeaderBrand.js): the company's name,
 * "Levelog" only when the company has none.
 *
 * Pure, so it is tested under plain node (whatsappConnect.test.cjs).
 *
 * FIT, NOT CUT. A long name used to be capped at 280px and ellipsized
 * ("BLUEVIE…"). Now the type starts smaller for a long name (never under
 * BRAND_MIN_SIZE), the phone shrinks it further to fit one line, and only a
 * name that still does not fit at the minimum ends in an ellipsis.
 */

export const BRAND_FALLBACK = 'Levelog';
export const BRAND_MAX_SIZE = 27;
export const BRAND_MIN_SIZE = 14;
// Names up to this many characters keep the full size.
const FULL_SIZE_CHARS = 10;

export function brandLabel(user) {
  const name = String(user?.gc_business_name || user?.company_name || '').trim();
  return name || BRAND_FALLBACK;
}

/** {fontSize, letterSpacing, minimumFontScale} for this label. */
export function brandSizing(label) {
  const n = String(label || '').length;
  const fontSize = n <= FULL_SIZE_CHARS
    ? BRAND_MAX_SIZE
    : Math.max(BRAND_MIN_SIZE, Math.round((BRAND_MAX_SIZE * FULL_SIZE_CHARS) / n));
  return {
    fontSize,
    // The wide tracking scales with the type, or a long name runs out of room.
    letterSpacing: Math.round((6 * fontSize) / BRAND_MAX_SIZE),
    // Native shrink-to-fit stops at the minimum size; past that, the ellipsis.
    minimumFontScale: BRAND_MIN_SIZE / fontSize,
  };
}
