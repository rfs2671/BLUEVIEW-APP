/**
 * WHAT THE INTEGRATIONS → WHATSAPP CARD SAYS, for each state GET /whatsapp/me
 * returns (backend/lib/wa_dm.py::connect_state).
 *
 * Pure, so it is tested under plain node (whatsappConnect.test.cjs) and the
 * card only renders what this returns. Every blocked state carries ONE plain
 * line naming the thing to fix; the Connect button appears only in the states
 * where pressing it can work, because the server sends `connect_url` only
 * then.
 */

export const WA_POLL_MS = 4000;
// Stop polling an idle screen after this long; focus, returning to the app,
// or pressing Connect starts it again.
export const WA_POLL_MAX_MS = 10 * 60 * 1000;

// States in which a START may be on its way, so the card polls.
export const WA_POLLING_STATES = new Set(['not_connected', 'reconnect_needed']);

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

/**
 * { visible, status, tone, line, button } for the card.
 *   tone: 'ok' | 'warn' | 'idle'
 *   button: null, or { label, url }
 */
export function whatsappConnectView(me) {
  const state = me && me.state;
  if (!me || !me.eligible || !state || state === 'not_eligible') {
    return { visible: false };
  }
  const url = me.connect_url || null;
  const button = (label) => (url ? { label, url } : null);
  switch (state) {
    case 'connected':
      return {
        visible: true,
        status: `Connected (${formatWaPhone(me.phone)})`,
        tone: 'ok',
        line: 'Reply STOP in WhatsApp to turn updates off.',
        button: null,
      };
    case 'phone_missing':
      return {
        visible: true,
        status: 'Phone missing',
        tone: 'warn',
        line: 'Add your mobile number in Settings, then come back here to connect.',
        button: null,
      };
    case 'phone_shared':
      return {
        visible: true,
        status: 'Phone shared',
        tone: 'warn',
        line: 'This number is also on another Blueview account. Change your number in Settings, or ask Blueview support to remove it from the other account.',
        button: null,
      };
    case 'reconnect_needed':
      return {
        visible: true,
        status: 'Reconnect needed (phone changed)',
        tone: 'warn',
        line: `Your phone number changed. Tap Connect and send START from ${formatWaPhone(me.phone)}.`,
        button: button('Reconnect WhatsApp'),
      };
    case 'unavailable':
      return {
        visible: true,
        status: 'Not available',
        tone: 'warn',
        line: 'WhatsApp updates are not set up yet. Contact Blueview support.',
        button: null,
      };
    case 'not_connected':
    default:
      return {
        visible: true,
        status: 'Not connected',
        tone: 'idle',
        line: `Tap Connect, then send the START message from ${formatWaPhone(me.phone)}.`,
        button: button('Connect WhatsApp'),
      };
  }
}
