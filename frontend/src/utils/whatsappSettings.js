/**
 * Project → WhatsApp settings: what the screen shows for the server's answer
 * (GET /api/projects/{id}/whatsapp-settings). Admins only.
 *
 * Only settings for features that are live: the GC group, and the two alerts
 * Levelog posts there. Nothing else, and no placeholders.
 */

export const ALERT_SWITCHES = [
  { key: 'violation_alerts', label: 'New DOB violations',
    line: 'Posts each new violation once, with its number and DOB link.' },
  { key: 'permit_reminders', label: 'Permit expiry reminders',
    line: 'Posts 30, 14, 7 and 1 days before a permit expires.' },
];

export const POST_HOURS_LINE = 'Levelog posts between 7 AM and 7 PM Eastern.';

export function whatsappSettingsView(data) {
  if (!data || typeof data !== 'object') return null;
  const groups = Array.isArray(data.groups) ? data.groups : [];
  const gc = data.gc_group && data.gc_group.confirmed ? data.gc_group : null;
  let gcLine;
  if (gc) {
    gcLine = `Levelog posts DOB alerts in '${gc.group_name}'.`;
  } else if (data.gc_pending_question) {
    gcLine = "Levelog asked the company's main admin on WhatsApp to confirm a group. Nothing is posted until a group is confirmed.";
  } else if (groups.length) {
    gcLine = 'No GC group yet. Nothing is posted until you pick one.';
  } else {
    gcLine = "No WhatsApp group is linked to this project yet. Add the Levelog number to the job's group first.";
  }
  return {
    gc: {
      name: gc ? gc.group_name : null,
      line: gcLine,
      action: groups.length ? (gc ? 'Change' : 'Pick group') : null,
    },
    choices: groups.map((g) => ({
      id: g.wa_group_id,
      name: g.group_name,
      current: !!gc && gc.wa_group_id === g.wa_group_id,
    })),
    // The switches only mean something once a group is confirmed.
    switches: gc
      ? ALERT_SWITCHES.map((s) => ({ ...s, value: data[s.key] !== false }))
      : [],
    hoursLine: gc ? POST_HOURS_LINE : null,
  };
}
