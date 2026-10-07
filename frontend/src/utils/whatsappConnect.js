/**
 * WHAT THE ONE WHATSAPP CARD ON INTEGRATIONS SAYS.
 *
 * Pure, so it is tested under plain node (whatsappConnect.test.cjs) and the
 * card renders only what this returns. Three sections:
 *
 *   header      the Levelog number and whether WhatsApp is set up for the
 *               company (GET /whatsapp/status), with Save to Contacts
 *   Your alerts this person's own updates (GET /whatsapp/me state, from
 *               backend lib/wa_dm.py::connect_state) — Admins and PMs
 *   Groups      linking job groups — Admins only
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
 * The "Your alerts" section for a GET /whatsapp/me reading, or null.
 * `connectUrl` is the single-use coded link from POST /whatsapp/connect-link;
 * the plain-START `me.connect_url` is the fallback when none could be had.
 */
export function alertsView(me, connectUrl = null) {
  const state = me && me.state;
  if (!me || !me.eligible || !state || state === 'not_eligible') return null;
  const onUrl = me.connect_url ? (connectUrl || me.connect_url) : null;
  const on = onUrl ? { label: 'Turn on alerts', url: onUrl } : null;
  switch (state) {
    case 'connected':
      return {
        chip: chip('On', 'ok'),
        line: `You'll get updates for your projects at ${formatWaPhone(me.phone)}.`,
        button: me.stop_url ? { label: 'Turn off', url: me.stop_url, quiet: true } : null,
      };
    case 'reconnect_needed':
      return {
        chip: chip('Reconnect needed', 'warn'),
        line: 'Your phone number changed. Turn alerts on again from your new number.',
        button: on,
      };
    case 'phone_missing':
      return {
        chip: chip('Phone missing', 'warn'),
        line: 'Add your mobile number in Settings, then turn alerts on.',
        button: null,
      };
    case 'phone_shared':
      return {
        chip: chip('Phone shared', 'warn'),
        line: 'This number is also on another Blueview account. Change your number in Settings, or ask Blueview support to remove it from the other account.',
        button: null,
      };
    case 'unavailable':
      return {
        chip: chip('Not available', 'warn'),
        line: "WhatsApp alerts aren't set up yet. Contact Blueview support.",
        button: null,
      };
    case 'not_connected':
    default:
      return {
        chip: chip('Off', 'idle'),
        line: 'Get updates for your projects on WhatsApp.',
        button: on,
      };
  }
}

/** The Groups section (Admins only), or null. */
export function groupsView({ status, pendingCount, isAdmin }) {
  if (!isAdmin || !status) return null;
  if (!status.platform_configured) {
    return { line: "WhatsApp isn't available yet. Contact Blueview support.", action: null };
  }
  if (!status.company_active) {
    return {
      line: 'Turn on WhatsApp for your company to link job groups.',
      action: { kind: 'activate', label: 'Turn on WhatsApp' },
    };
  }
  if (pendingCount > 0) {
    return { line: null, action: { kind: 'link', label: 'Link new groups', count: pendingCount } };
  }
  return { line: GROUPS_EMPTY_LINE, action: null };
}

/**
 * The whole card. `visible` is false when there is nothing for this person:
 * not an Admin, and the server says alerts are not for them.
 */
export function whatsappCardView({
  me, status, pendingCount = 0, isAdmin = false, connectUrl = null,
}) {
  const alerts = alertsView(me, connectUrl);
  const groups = groupsView({ status, pendingCount, isAdmin });
  if (!alerts && !isAdmin) return { visible: false };
  const number = (me && me.bot_number) || (status && status.whatsapp_number) || '';
  const header = {
    chip: !status ? null
      : status.company_active ? chip('Connected', 'ok')
        : status.platform_configured ? chip('Not set up', 'idle')
          : chip('Not available', 'warn'),
    number: number ? formatWaPhone(number) : '',
    // The contact card is served only to a company with WhatsApp set up.
    canSaveContact: !!(status && status.company_active && number),
  };
  return { visible: true, header, alerts, groups };
}
