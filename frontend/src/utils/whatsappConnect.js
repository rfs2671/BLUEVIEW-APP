/**
 * WHAT THE ONE WHATSAPP CARD ON INTEGRATIONS SAYS.
 *
 * Pure, so it is tested under plain node (whatsappConnect.test.cjs) and the
 * card and its two screens render only what this returns.
 *
 *   the card    Connected status, the Levelog number, Save to Contacts, and
 *               two buttons — nothing else:
 *   Project groups      (app/whatsapp/groups.jsx) every group the Levelog
 *               number is in (GET /whatsapp/company-groups): name, job
 *               address, status; a row opens that project's WhatsApp tab.
 *               Admins (and CPs) also see groups not linked yet; a PM sees
 *               their own projects' groups, read-only.
 *   Personal assistant  (app/whatsapp/assistant.jsx) this person's own
 *               Levelog Assistant: on/off, morning brief time, weekends
 *               (GET /whatsapp/me, from backend lib/wa_dm.py::connect_state).
 *
 * One status chip and one plain line per state. A button appears only where
 * pressing it can work: the server sends `connect_url` / `stop_url` only then.
 */

export const WA_POLL_MS = 4000;
// Stop polling an idle screen after this long; focus, returning to the app,
// or pressing a button starts it again.
export const WA_POLL_MAX_MS = 10 * 60 * 1000;

// States in which a START may be on its way, so the card polls.
export const WA_POLLING_STATES = new Set(['not_connected', 'reconnect_needed']);

export const GROUPS_EMPTY_LINE =
  "Add the Levelog number to a job's WhatsApp group. It will appear here to link.";

/** "+15551234567" -> "+1 (555) 123-4567"; anything else as given. */
export function formatWaPhone(phone) {
  const d = String(phone || '').replace(/\D/g, '');
  if (d.length === 11 && d[0] === '1') {
    return `+1 (${d.slice(1, 4)}) ${d.slice(4, 7)}-${d.slice(7)}`;
  }
  if (d.length === 10) {
    return `+1 (${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}`;
  }
  return d ? `+${d}` : '';
}

const chip = (label, tone) => ({ label, tone }); // tone: 'ok' | 'warn' | 'idle'

// Ask for a new single-use link this long before the current one expires.
export const WA_LINK_REFRESH_MS = 60 * 1000;

/** True when the card should ask for a fresh connect link now. */
export function needsFreshLink(link, now = Date.now()) {
  if (!link || !link.url) return true;
  const exp = Date.parse(link.expires_at || '');
  return !Number.isFinite(exp) || exp - now < WA_LINK_REFRESH_MS;
}

/**
 * The "Levelog Assistant" section for a GET /whatsapp/me reading, or null.
 * `connectUrl` is the single-use coded link from POST /whatsapp/connect-link;
 * the plain-START `me.connect_url` is the fallback when none could be had.
 */
export function alertsView(me, connectUrl = null) {
  const state = me && me.state;
  if (!me || !me.eligible || !state || state === 'not_eligible') return null;
  const onUrl = me.connect_url ? (connectUrl || me.connect_url) : null;
  const on = onUrl ? { label: 'Turn on Levelog Assistant', url: onUrl } : null;
  switch (state) {
    case 'connected':
      return {
        chip: chip('Assistant on', 'ok'),
        line: `You'll get updates for your projects at ${formatWaPhone(me.phone)}.`,
        button: me.stop_url ? { label: 'Turn off Assistant', url: me.stop_url, quiet: true } : null,
      };
    case 'reconnect_needed':
      return {
        chip: chip('Reconnect needed', 'warn'),
        line: 'Your phone number changed. Turn on Levelog Assistant again from your new number.',
        button: on,
      };
    case 'phone_missing':
      return {
        chip: chip('Phone missing', 'warn'),
        line: 'Add your mobile number in Settings, then turn on Levelog Assistant.',
        button: null,
      };
    case 'phone_shared':
      return {
        chip: chip('Phone shared', 'warn'),
        line: 'This number is also on another Levelog account. Change your number in Settings, or ask Levelog support to remove it from the other account.',
        button: null,
      };
    case 'unavailable':
      return {
        chip: chip('Not available', 'warn'),
        line: "Levelog Assistant isn't set up yet. Contact Levelog support.",
        button: null,
      };
    case 'not_connected':
    default:
      return {
        chip: chip('Assistant off', 'idle'),
        line: 'Get updates for your projects on WhatsApp from Levelog Assistant.',
        button: on,
      };
  }
}

// What a group is to its job (server: GROUP_* in server.py).
export const GROUP_STATUS = {
  gc_confirmed: chip('GC group confirmed', 'ok'),
  gc_waiting: chip('Waiting for confirm', 'warn'),
  trade: chip('Trade group', 'idle'),
};

/**
 * One row per group: its WhatsApp name, then the job or "Not linked". A
 * linked row opens its project's WhatsApp tab (`projectId`); a group not
 * linked yet has a Link button only for someone who may link (`canLink`).
 */
export function groupRows(groups, { canLink = true } = {}) {
  return (Array.isArray(groups) ? groups : []).map((g) => {
    const linked = g.status !== 'not_linked' && !!g.project_label;
    return {
      key: g.group_id,
      name: g.group_name || 'WhatsApp group',
      place: linked ? g.project_label : 'Not linked',
      chip: linked ? (GROUP_STATUS[g.status] || GROUP_STATUS.trade) : null,
      link: !linked && canLink,
      projectId: linked ? g.project_id : null,
    };
  });
}

/** Where a group row goes: its project's WhatsApp tab. */
export function projectWhatsAppPath(projectId) {
  return projectId ? `/projects/${projectId}/whatsapp-groups` : null;
}

/**
 * Save to Contacts: WhatsApp, with "contact" typed to the Levelog number
 * (as "Turn on Levelog Assistant" types START). The bot answers with its
 * contact card, which WhatsApp saves in one tap.
 */
export function contactCardUrl(number) {
  const d = String(number || '').replace(/\D/g, '');
  return d ? `https://wa.me/${d}?text=contact` : null;
}

/**
 * The Project groups screen, or null. `groups` is the
 * /whatsapp/company-groups list, or null while it has not loaded. `canLink`:
 * Admins (and CPs) link groups and turn WhatsApp on; a PM reads only.
 */
export function groupsView({ status, groups = null, canLink = false }) {
  if (!status) return null;
  if (!status.platform_configured) {
    return { line: "WhatsApp isn't available yet. Contact Levelog support.", action: null, rows: [] };
  }
  if (!status.company_active) {
    return canLink ? {
      line: 'Turn on WhatsApp for your company to link job groups.',
      action: { kind: 'activate', label: 'Turn on WhatsApp' },
      rows: [],
    } : { line: "WhatsApp isn't set up for your company yet.", action: null, rows: [] };
  }
  if (groups === null) return { line: null, action: null, rows: [] };
  const rows = groupRows(groups, { canLink });
  // The empty line only when the number is in no group at all.
  return { line: rows.length ? null : GROUPS_EMPTY_LINE, action: null, rows };
}

/**
 * The card. `visible` is false when there is nothing for this person: not
 * an Admin, and the server says the assistant is not for them.
 */
export function whatsappCardView({ me, status, isAdmin = false }) {
  const assistant = alertsView(me);
  if (!assistant && !isAdmin) return { visible: false };
  const number = (me && me.bot_number) || (status && status.whatsapp_number) || '';
  const header = {
    chip: !status ? null
      : status.company_active ? chip('Connected', 'ok')
        : status.platform_configured ? chip('Not set up', 'idle')
          : chip('Not available', 'warn'),
    number: number ? formatWaPhone(number) : '',
    contactUrl: status && status.company_active ? contactCardUrl(number) : null,
  };
  return {
    visible: true,
    header,
    // Admins and PMs both see the groups (a PM read-only).
    groupsButton: { label: 'Project groups', path: '/whatsapp/groups' },
    assistantButton: assistant
      ? { label: 'Personal assistant', path: '/whatsapp/assistant', chip: assistant.chip }
      : null,
  };
}
