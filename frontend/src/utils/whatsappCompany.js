/**
 * Company settings (Integrations → WhatsApp → Company settings, Admins):
 * company-wide switches, GET/PATCH /api/company/whatsapp-settings.
 */

export const COMPANY_SWITCHES = [
  {
    key: 'chase_sundays_default',
    label: 'Default: chase on Sundays',
    line: 'New jobs chase subs on Sundays. Jobs you already have keep their own "Sundays off" switch.',
    byDefault: true,
  },
  {
    key: 'shabbos_off',
    label: 'Shabbos / Yom Tov off',
    line: 'No bot messages from an hour before candle-lighting until an hour after nightfall '
      + '(New York). They go out after, in order; the morning brief is skipped. '
      + 'Each job has its own switch for its messages.',
    byDefault: true,
  },
  {
    key: 'shabbos_critical_alerts',
    label: 'Still send critical DOB alerts on Shabbos (Stop Work Order, Vacate)',
    line: 'Every other DOB and DOT alert waits until after Shabbos / Yom Tov.',
    byDefault: false,
  },
];

/**
 * Company settings that are one of a few choices.
 * "Punch list detail": what a walkthrough asks and shows. Simple (default):
 * floor and description. Detailed: trades and locations too. A walk can
 * switch in plain words ("keep it simple", "add trades").
 */
export const COMPANY_CHOICES = [
  {
    key: 'punch_detail',
    label: 'Punch list detail',
    options: [
      { value: 'simple', label: 'Simple', line: 'Floor and description only. Nothing else is asked.' },
      { value: 'detailed', label: 'Detailed', line: 'Trades and locations too, each asked at most once.' },
    ],
    byDefault: 'simple',
  },
];

/** Each choice with its value (its default unless a known one is saved). */
export function choiceView(data) {
  const d = data || {};
  return COMPANY_CHOICES.map((c) => ({
    ...c,
    value: c.options.some((o) => o.value === d[c.key]) ? d[c.key] : c.byDefault,
  }));
}

/** The switches with their values (each its default unless saved). */
export function companyView(data) {
  const d = data || {};
  return COMPANY_SWITCHES.map((s) => ({
    ...s, value: typeof d[s.key] === 'boolean' ? d[s.key] : s.byDefault,
  }));
}
