/**
 * What a Compliance card (app/project/[id]/dob-logs.jsx) says, as pure
 * functions: the plain one-liner, the ECB hearing line, the penalty tone, the
 * renewal banner's count and the BIN header.
 *
 * DISPLAY ONLY. The plain line is decided and stored by the backend
 * (lib/dob_plain_lines: a code table first, then a model line that passed a
 * checker, else a neutral generic line) and served by GET /dob-logs. Nothing
 * here writes a line, and nothing here asks a model.
 *
 * No imports, so the node tests can evaluate this file as it ships
 * (complianceCard.test.cjs).
 */

/** The stored line in the reader's language, English when Spanish is missing. */
export function plainLineFor(log, locale) {
  const pl = log && log.plain_line;
  if (!pl || typeof pl !== 'object') return '';
  return String((locale && pl[locale]) || pl.en || '').trim();
}

/** '09:30' -> '9:30 AM' (en) / '9:30 a. m.' (es). '' for anything else. */
export function formatHearingTime(hhmm, locale) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm || '').trim());
  if (!m) return '';
  const h = Number(m[1]);
  const mi = m[2];
  if (h > 23 || Number(mi) > 59) return '';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  if (locale === 'es') return `${h12}:${mi} ${h < 12 ? 'a. m.' : 'p. m.'}`;
  return `${h12}:${mi} ${h < 12 ? 'AM' : 'PM'}`;
}

/** "Hearing Nov 18, 2026 at 9:30 AM" from the served ecb_hearing {date, time}. */
export function hearingText(hearing, locale, t, formatDate) {
  if (!hearing || !hearing.date) return '';
  const date = formatDate(hearing.date);
  const time = formatHearingTime(hearing.time, locale);
  return time
    ? t('hearingAt').replace('{date}', date).replace('{time}', time)
    : t('hearingOn').replace('{date}', date);
}

/**
 * How the served ecb_penalty is drawn: 'amount' (the imposed penalty, in the
 * card's penalty colour), 'neutral' ("Penalty set at hearing": $0 or blank
 * with the hearing still to come -- nothing has been imposed, so it is not
 * drawn as a debt), or null (nothing to show).
 */
export function penaltyTone(penalty) {
  if (!penalty) return null;
  if (penalty.kind === 'set_at_hearing') return 'neutral';
  if (penalty.kind === 'amount' && penalty.amount) return 'amount';
  return null;
}

/** '1250' -> '$1,250'. */
export function formatMoney(amount) {
  const n = Number(amount);
  if (!Number.isFinite(n)) return `$${amount}`;
  return `$${n.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
}

/** "1 Permit Needs Renewal" / "N Permits Need Renewal" (and Spanish). */
export function renewalTitle(n, t) {
  return n === 1 ? t('renewalOne') : t('renewalMany').replace('{n}', String(n));
}

/** "BIN: 3255362" or "BINs: 3255362 · 3430621" -- every BIN the records come from. */
export function binHeaderText(bins, t) {
  const list = (bins || []).filter(Boolean);
  if (list.length === 0) return '';
  if (list.length === 1) return t('binOne').replace('{bin}', list[0]);
  return t('binMany').replace('{list}', list.join(' · '));
}
