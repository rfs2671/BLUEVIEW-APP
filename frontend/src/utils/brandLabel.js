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
// Room the header keeps beside the name: back button, gaps, padding and
// one icon button on the right.
export const BRAND_SIDE_ROOM = 140;
// A light uppercase geometric sans is about this wide per point of size.
const CHAR_EM = 0.68;

export function brandLabel(user) {
  const name = String(user?.gc_business_name || user?.company_name || '').trim();
  return name || BRAND_FALLBACK;
}

// The wide tracking at full size; tighter once the type is small, or a long
// name runs out of room.
function tracking(size) {
  return size >= 20 ? Math.round((6 * size) / BRAND_MAX_SIZE)
    : Math.max(1, Math.round(size * 0.12));
}

/**
 * {fontSize, letterSpacing, minimumFontScale, maxWidth} for this label on a
 * screen `screenWidth` wide: the largest size (27 down to 14) at which the
 * whole name fits one line. The phone's own shrink-to-fit refines it, and
 * stops at 14pt; only a name that does not fit even then is ellipsized.
 */
export function brandSizing(label, screenWidth = 390) {
  const n = Math.max(1, String(label || '').length);
  const maxWidth = Math.max(160, screenWidth - BRAND_SIDE_ROOM);
  let fontSize = BRAND_MIN_SIZE;
  for (let s = BRAND_MAX_SIZE; s >= BRAND_MIN_SIZE; s -= 1) {
    if (n * (s * CHAR_EM + tracking(s)) <= maxWidth) { fontSize = s; break; }
  }
  return {
    fontSize,
    letterSpacing: tracking(fontSize),
    minimumFontScale: BRAND_MIN_SIZE / fontSize,
    maxWidth,
  };
}
