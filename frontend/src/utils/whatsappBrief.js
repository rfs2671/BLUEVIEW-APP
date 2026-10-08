/**
 * Integrations → Levelog Assistant → "Morning brief: 7 AM ▾" + weekends.
 * Pure, so it is tested under plain node (whatsappBrief.test.cjs).
 *
 * Shown only to an eligible, connected user: GET /api/whatsapp/me returns
 * `brief` ({brief_time, brief_weekend}) only then. Saved with
 * PUT /api/whatsapp/brief.
 */

export const BRIEF_OPTIONS = [
  { value: 'off', label: 'Off' },
  { value: '07:00', label: '7 AM' },
  { value: '08:00', label: '8 AM' },
  { value: '09:00', label: '9 AM' },
];

export function briefTimeLabel(value) {
  const o = BRIEF_OPTIONS.find((x) => x.value === value);
  return o ? o.label : '7 AM';
}

/** The row, or null when it must not be shown. */
export function briefRow(me) {
  if (!me || !me.connected || !me.brief) return null;
  const time = me.brief.brief_time;
  // brief_saturday: what a server from before the weekend switch sends.
  const weekend = !!(me.brief.brief_weekend ?? me.brief.brief_saturday);
  return {
    label: `Morning brief: ${briefTimeLabel(time)}`,
    line: time === 'off'
      ? 'Off. Turn it on to get one message each weekday morning.'
      : `${weekend ? 'Every day' : 'Each weekday'}: what needs action on your jobs, and who is on site so far.`,
    weekend,
    weekendDisabled: time === 'off',
  };
}
