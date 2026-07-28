/**
 * Shared expiry math for dated credentials and permits.
 *
 * `daysUntil` lived inline in app/project/[id]/dob-logs.jsx, where it drives
 * the DOB permit tiles. app/workers/[id].jsx had NO date comparison at all: it
 * rendered `cert.expiry` and `oshaData.expiration` as plain muted text, so an
 * SST or OSHA card that had ALREADY LAPSED looked exactly like a valid one.
 * That is a compliance gap, not a styling miss — a worker on site with an
 * expired card is a DOB violation waiting to be written, and the screen whose
 * job is to show credential state said nothing.
 *
 * Lifted here so both screens share one definition and one threshold rather
 * than drifting apart.
 */

// A credential inside this window is "expiring soon". 30 days is the practical
// renewal lead time for SST/OSHA cards.
export const EXPIRING_SOON_DAYS = 30;

/**
 * Whole days from now until `dateStr`. Negative once the date has passed.
 * Returns null for absent or unparseable input — callers must treat null as
 * "no claim", never as "fine".
 *
 * Moved verbatim from dob-logs.jsx so the DOB tiles keep their exact behaviour.
 */
export const daysUntil = (dateStr) => {
  if (!dateStr) return null;
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return null;
    return Math.ceil((d - new Date()) / (1000 * 60 * 60 * 24));
  } catch { return null; }
};

/**
 * 'expired' | 'soon' | 'ok' | null.
 *
 * null means the date is missing or unparseable. It is deliberately NOT 'ok':
 * an unreadable expiry date is an unknown, and colouring it green would assert
 * something the data does not support.
 */
export function expiryStatus(dateStr) {
  const d = daysUntil(dateStr);
  if (d === null) return null;
  if (d < 0) return 'expired';
  if (d <= EXPIRING_SOON_DAYS) return 'soon';
  return 'ok';
}

/**
 * Short suffix appended to the rendered date, e.g. "· EXPIRED" / "· 12d left".
 *
 * Colour alone is not an accessible signal — a red date and a grey date are the
 * same date to a colourblind operator, and this screen is read on a phone in
 * daylight. The text carries the warning; the token reinforces it.
 */
export function expirySuffix(dateStr) {
  const status = expiryStatus(dateStr);
  if (status === 'expired') return ' · EXPIRED';
  if (status === 'soon') {
    const d = daysUntil(dateStr);
    return d === 0 ? ' · expires today' : ` · ${d}d left`;
  }
  return '';
}
