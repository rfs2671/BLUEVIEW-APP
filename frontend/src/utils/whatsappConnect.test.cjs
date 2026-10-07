/**
 * INTEGRATIONS → YOUR WHATSAPP: what the card says for each server state, and
 * where the card lives.
 *
 * 1. Every state GET /whatsapp/me can return (backend wa_dm.connect_state) has
 *    a status and ONE plain line; the Connect button appears only when the
 *    server sent a connect_url, i.e. only where pressing it can work.
 * 2. The card is on the Integrations screen, reachable by a PM, and is no
 *    longer on Settings — the decision is that Connect lives in one place.
 *
 * Run:  node src/utils/whatsappConnect.test.cjs
 */

const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

let passed = 0;
let failed = 0;
const ok = (cond, label) => {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
};

const W = loadEsm('src/utils/whatsappConnect.js');
const view = W.whatsappConnectView;
const URL = 'https://wa.me/15550000000?text=START';
const me = (state, extra = {}) => ({
  eligible: state !== 'not_eligible', state, phone: '+15550001001',
  connect_url: ['not_connected', 'reconnect_needed'].includes(state) ? URL : null,
  ...extra,
});

console.log('the states');
{
  const v = view(me('not_connected'));
  ok(v.visible && v.status === 'Not connected', 'not connected');
  ok(v.button && v.button.url === URL && v.button.label === 'Connect WhatsApp',
     'not connected: Connect opens wa.me with START');
  ok(v.line.includes('+1 (555) 000-1001'), 'not connected: names the phone to send from');
}
{
  const v = view(me('connected'));
  ok(v.status === 'Connected (+1 (555) 000-1001)', 'connected shows the number');
  ok(v.button === null && v.tone === 'ok', 'connected: no button');
}
{
  const v = view(me('phone_missing', { phone: null }));
  ok(v.status === 'Phone missing' && v.button === null, 'phone missing: no button');
  ok(/Settings/.test(v.line), 'phone missing: says where to add it');
}
{
  const v = view(me('phone_shared'));
  ok(v.status === 'Phone shared' && v.button === null, 'phone shared: no button');
  ok(/another Blueview account/.test(v.line), 'phone shared: says why');
}
{
  const v = view(me('reconnect_needed'));
  ok(v.status === 'Reconnect needed (phone changed)', 'reconnect needed');
  ok(v.button && v.button.label === 'Reconnect WhatsApp', 'reconnect: button');
}
{
  const v = view(me('unavailable'));
  ok(v.status === 'Not available' && v.button === null, 'unavailable: no button');
}
ok(view(me('not_eligible')).visible === false, 'not eligible: card hidden');
ok(view(null).visible === false, 'no reading yet: card hidden');
ok(view({ eligible: true, state: 'not_connected', connect_url: null }).button === null,
   'no connect_url from the server: no button, whatever the state');

console.log('\nevery blocked state carries exactly one plain line');
for (const st of ['phone_missing', 'phone_shared', 'reconnect_needed', 'unavailable']) {
  const v = view(me(st));
  ok(typeof v.line === 'string' && v.line.length > 0 && !v.line.includes('\n'),
     `${st}: one line`);
}

console.log('\npolling');
ok(W.WA_POLLING_STATES.has('not_connected') && W.WA_POLLING_STATES.has('reconnect_needed'),
   'polls while a START may be on its way');
ok(!W.WA_POLLING_STATES.has('connected') && !W.WA_POLLING_STATES.has('phone_missing'),
   'does not poll when nothing can change it');
ok(W.WA_POLL_MS >= 2000 && W.WA_POLL_MS <= 10000, 'interval is a few seconds');

const card = fs.readFileSync(path.join(__dirname, '..', 'components', 'WhatsAppConnectCard.jsx'), 'utf8');
ok(/const shouldPoll = !me \|\| WA_POLLING_STATES\.has\(state\)/.test(card),
   'a failed first read is retried by the poll, not left blank');

console.log('\nphone formatting');
ok(W.formatWaPhone('+15551234567') === '+1 (555) 123-4567', '11-digit US');
ok(W.formatWaPhone('5551234567') === '+1 (555) 123-4567', '10-digit US');
ok(W.formatWaPhone('+447700900123') === '+447700900123', 'other: as digits');
ok(W.formatWaPhone('') === '', 'empty');

console.log('\nwhere the card lives');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');
const integrations = read('app/admin/integrations.jsx');
const settings = read('app/settings.jsx');
const dashboard = read('app/index.jsx');
ok((integrations.match(/<WhatsAppConnectCard \/>/g) || []).length === 2,
   'Integrations renders the card (admin view and PM view)');
ok(/!isAdmin && isPm \? \(\s*<WhatsAppConnectCard \/>/.test(integrations),
   'a PM reaches the card instead of "Admin Access Required"');
ok(!/whatsappAPI|Connect WhatsApp|waMe/.test(settings),
   'Settings no longer carries the Connect button');
ok(/const pmActions = \[[^\]]*'\/admin\/integrations'/.test(dashboard),
   'the dashboard links a PM to Integrations');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
