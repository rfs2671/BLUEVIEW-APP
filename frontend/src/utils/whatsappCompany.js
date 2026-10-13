/**
 * Company settings (Integrations → WhatsApp → Company settings, Admins):
 * company-wide switches, GET/PATCH /api/company/whatsapp-settings.
 */

export const COMPANY_SWITCHES = [
  {
    key: 'chase_sundays_default',
    label: 'Default: chase on Sundays',
    line: 'New jobs chase subs on Sundays. Jobs you already have keep their own "Sundays off" switch.',
  },
];

/** The switches with their values (each on unless saved off). */
export function companyView(data) {
  const d = data || {};
  return COMPANY_SWITCHES.map((s) => ({ ...s, value: d[s.key] !== false }));
}
