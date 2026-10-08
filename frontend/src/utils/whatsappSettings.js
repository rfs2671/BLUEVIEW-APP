/**
 * Project → WhatsApp tab: what it says for the server's answers. Pure, so it
 * is tested under plain node (whatsappSettings.test.cjs).
 *
 *   header              "WhatsApp · N groups linked"
 *   Groups              real names + message count (never a raw …@g.us id)
 *   Levelog Assistant   admins: GC group + Change, the two GC alerts, when
 *                       to send (GET /api/projects/{id}/whatsapp-settings)
 *   What the bot does   admins: per-group settings that work today, plain
 *                       names, one line each (GET /api/whatsapp/groups/{id})
 */

export const UNNAMED_GROUP = 'Unnamed group';

/** A group's name as people see it. Never a WhatsApp id. */
export function groupLabel(name) {
  const s = String(name || '').trim();
  if (!s || /@(g\.us|c\.us|lid|s\.whatsapp\.net)$/i.test(s) || /^[\d-]+$/.test(s)) {
    return UNNAMED_GROUP;
  }
  return s;
}

export function headerTitle(count) {
  const n = Number(count) || 0;
  return `WhatsApp · ${n} group${n === 1 ? '' : 's'} linked`;
}

export function messageCountLabel(n) {
  const c = Number(n) || 0;
  return `${c} message${c === 1 ? '' : 's'}`;
}

// ── Levelog Assistant (project-level, admins) ──────────────────────────────

export const ALERT_SWITCHES = [
  { key: 'violation_alerts', label: 'New DOB violations → GC group',
    line: 'Posts each new violation once, with its number and DOB link.' },
  { key: 'permit_reminders', label: 'Permit expiry reminders → GC group',
    line: 'Posts 30, 14, 7 and 1 days before a permit expires.' },
];

export const SEND_WINDOW_OPTIONS = [
  { mode: 'anytime', label: 'Anytime' },
  { mode: 'work_hours', label: 'Work hours (7 AM–7 PM)' },
  { mode: 'custom', label: 'Custom hours' },
];

export const DEFAULT_SEND_WINDOW = { mode: 'anytime', start: '07:00', end: '19:00' };

/** "07:00" -> "7:00 AM". */
export function formatHHMM(hhmm) {
  const m = /^(\d{2}):(\d{2})$/.exec(String(hhmm || ''));
  if (!m) return '';
  const h = parseInt(m[1], 10);
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${m[2]} ${h < 12 ? 'AM' : 'PM'}`;
}

/** One line saying when alerts go out. */
export function sendWindowLine(w) {
  const win = w && w.mode ? w : DEFAULT_SEND_WINDOW;
  if (win.mode === 'work_hours') {
    return 'Sent from 7 AM to 7 PM Eastern. Anything found outside those hours goes out at 7 AM.';
  }
  if (win.mode === 'custom') {
    return `Sent from ${formatHHMM(win.start)} to ${formatHHMM(win.end)} Eastern. Anything found outside those hours goes out at ${formatHHMM(win.start)}.`;
  }
  return 'Sent as soon as Levelog Assistant finds it, day or night.';
}

/** Valid to send to PATCH /whatsapp-alerts, or null. */
export function cleanSendWindow(w) {
  if (!w || !SEND_WINDOW_OPTIONS.some((o) => o.mode === w.mode)) return null;
  if (w.mode !== 'custom') return { mode: w.mode };
  const ok = (t) => /^([01]\d|2[0-3]):[0-5]\d$/.test(String(t || ''));
  if (!ok(w.start) || !ok(w.end) || w.start === w.end) return null;
  return { mode: 'custom', start: w.start, end: w.end };
}

export function assistantView(data) {
  if (!data || typeof data !== 'object') return null;
  const groups = Array.isArray(data.groups) ? data.groups : [];
  const gc = data.gc_group && data.gc_group.confirmed ? data.gc_group : null;
  let gcLine = null;
  if (!gc) {
    if (data.gc_pending_question) {
      gcLine = "Levelog Assistant asked the company's main admin on WhatsApp to confirm a group. Nothing is posted until a group is confirmed.";
    } else if (groups.length) {
      gcLine = 'No GC group yet. Nothing is posted until one is picked.';
    } else {
      gcLine = "No WhatsApp group is linked to this project yet.";
    }
  }
  return {
    gc: {
      name: gc ? groupLabel(gc.group_name) : null,
      line: gcLine,
      action: groups.length ? (gc ? 'Change' : 'Pick group') : null,
    },
    choices: groups.map((g) => ({
      id: g.wa_group_id,
      name: groupLabel(g.group_name),
      current: !!gc && gc.wa_group_id === g.wa_group_id,
    })),
    switches: ALERT_SWITCHES.map((s) => ({ ...s, value: data[s.key] !== false })),
    sendWindow: data.send_window && data.send_window.mode ? data.send_window : DEFAULT_SEND_WINDOW,
  };
}

// ── What the bot does in each group (admins) ──────────────────────────────
//
// Only settings the bot actually reads today. Each `get`/`set` addresses
// bot_config (PUT /api/whatsapp/groups/{id}/config).

export const BOT_SETTINGS = [
  { key: 'bot_enabled', label: 'Answer in this group',
    line: "When off, Levelog Assistant doesn't reply, summarize or post checklists here. DOB alerts to the GC group are set above." },
  { key: 'features.address_mode', label: 'Only answer when called by name',
    line: 'On: answers only when someone says "Levelog", @mentions it, or replies to it. Off: also answers questions it clearly can help with.',
    on: 'strict', off: 'loose' },
  { key: 'features.who_on_site', label: "Who's on site",
    line: "Answers who checked in today and on the last working day." },
  { key: 'features.dob_status', label: 'DOB and permit status',
    line: 'Answers questions about permits, violations and DOB records.' },
  { key: 'features.open_items', label: 'Open items and daily log',
    line: "Answers what's still open on today's daily log." },
  { key: 'features.plan_queries', label: 'Plan questions',
    line: 'Answers questions about the drawings and sends a sheet when asked.' },
  { key: 'features.material_detection', label: 'Material requests',
    line: 'Spots material requests in the chat, logs them, and answers delivery questions.' },
  { key: 'features.voice_notes', label: 'Voice notes',
    line: 'Transcribes voice notes so it can answer them like typed messages.' },
  { key: 'daily_summary_enabled', label: 'Daily summary',
    line: 'Posts a short summary of the day\'s chat at the time and days you pick.' },
  { key: 'checklist_extraction_enabled', label: 'Action items',
    line: 'Turns the chat into a numbered checklist. Reply "done 3" to close item 3.' },
];

/** Removed from the screen, and why (shown in the PR, asserted in tests). */
export const REMOVED_SETTINGS = {
  cross_project_summary: 'Stored, never read by the bot: it did nothing.',
  nickname: 'Job nickname: the bot never used it; groups and messages name the job by its address.',
};

function readKey(cfg, key) {
  return key.split('.').reduce((o, k) => (o == null ? undefined : o[k]), cfg);
}

/** The switch value of one BOT_SETTINGS row for a bot_config. */
export function botSettingValue(cfg, setting) {
  const v = readKey(cfg || {}, setting.key);
  if (setting.on !== undefined) return v === setting.on;
  return v !== false && v !== undefined ? !!v : false;
}

/** The bot_config with one setting changed (immutably). */
export function withBotSetting(cfg, setting, on) {
  const value = setting.on !== undefined ? (on ? setting.on : setting.off) : !!on;
  const parts = setting.key.split('.');
  if (parts.length === 1) return { ...cfg, [parts[0]]: value };
  return { ...cfg, [parts[0]]: { ...(cfg[parts[0]] || {}), [parts[1]]: value } };
}

/** What PUT /config gets: only keys the bot reads. */
export function configForSave(cfg) {
  const out = { ...(cfg || {}) };
  delete out.cross_project_summary;
  return out;
}
