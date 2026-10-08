/**
 * INTEGRATIONS → THE ONE WHATSAPP CARD: what it says for each server state,
 * who sees which section, and where it lives.
 *
 *   header       Levelog number + one chip + Save to Contacts
 *   Your alerts  one chip + one plain line per state; Turn on / Turn off only
 *                when the server sent the link
 *   Groups       Admins only; "Link new groups" with a count, or one line
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
const ON = 'https://wa.me/15165494475?text=START%20K7Q2MX';
const OFF = 'https://wa.me/15165494475?text=STOP';
const me = (state, extra = {}) => ({
  eligible: state !== 'not_eligible', state,
  phone: '+15163018154', bot_number: '+15165494475',
  connect_url: ['not_connected', 'reconnect_needed'].includes(state) ? ON : null,
  stop_url: state === 'connected' ? OFF : null,
  ...extra,
});
const active = { platform_configured: true, company_active: true, whatsapp_number: '+15165494475' };
const card = (m, opts = {}) => W.whatsappCardView({ me: m, status: active, ...opts });

console.log('header');
{
  const v = card(me('not_connected'), { isAdmin: true });
  ok(v.header.number === '+1 (516) 549-4475', 'Levelog number formatted');
  ok(v.header.chip.label === 'Connected' && v.header.chip.tone === 'ok', 'company set up: Connected');
  ok(v.header.canSaveContact === true, 'Save to Contacts when set up');
  const notSetUp = W.whatsappCardView({ me: me('not_connected'),
    status: { platform_configured: true, company_active: false }, isAdmin: true });
  ok(notSetUp.header.chip.label === 'Not set up' && !notSetUp.header.canSaveContact,
     'company not set up: chip says so, no contact card');
}

console.log('\nyour alerts: one chip, one line per state');
{
  const a = card(me('not_connected')).alerts;
  ok(a.chip.label === 'Off', 'off');
  ok(a.line === 'Get updates for your projects on WhatsApp.', 'off: the line');
  ok(a.button && a.button.label === 'Turn on alerts' && a.button.url === ON,
     'off: Turn on alerts opens wa.me with START and the code');
}
{
  const a = card(me('connected')).alerts;
  ok(a.chip.label === 'On' && a.chip.tone === 'ok', 'on');
  ok(a.button && a.button.label === 'Turn off' && a.button.url === OFF, 'on: Turn off opens wa.me STOP');
  ok(a.line.includes('+1 (516) 301-8154'), 'on: names the phone');
}
for (const [st, label, fixWord] of [
  ['phone_missing', 'Phone missing', 'Settings'],
  ['phone_shared', 'Phone shared', 'another Levelog account'],
  ['reconnect_needed', 'Reconnect needed', 'new number'],
  ['unavailable', 'Not available', 'support'],
]) {
  const a = card(me(st)).alerts;
  ok(a.chip.label === label && a.chip.tone === 'warn', `${st}: chip "${label}"`);
  ok(typeof a.line === 'string' && a.line.includes(fixWord) && !a.line.includes('\n'),
     `${st}: one line saying what to fix`);
}
ok(card(me('reconnect_needed')).alerts.button.label === 'Turn on alerts', 'reconnect: button to turn on again');
for (const st of ['phone_missing', 'phone_shared', 'unavailable']) {
  ok(card(me(st)).alerts.button === null, `${st}: no button`);
}
ok(card({ ...me('not_connected'), connect_url: null }).alerts.button === null,
   'no link from the server: no button, whatever the state');

console.log('\nthe single-use link');
{
  const coded = 'https://wa.me/15165494475?text=START%20ABC234';
  const a = W.whatsappCardView({ me: me('not_connected'), status: active, connectUrl: coded }).alerts;
  ok(a.button.url === coded, 'Turn on alerts opens the fresh coded link when there is one');
  const fb = card({ ...me('not_connected'), connect_url: 'https://wa.me/15165494475?text=START' }).alerts;
  ok(fb.button.url === 'https://wa.me/15165494475?text=START', 'falls back to plain START');
  const blocked = W.whatsappCardView({ me: me('phone_missing'), status: active, connectUrl: coded }).alerts;
  ok(blocked.button === null, 'a coded link never shows where the server offers none');
  const now = Date.parse('2026-10-07T21:00:00Z');
  ok(W.needsFreshLink(null, now), 'no link: fetch one');
  ok(!W.needsFreshLink({ url: coded, expires_at: '2026-10-07T21:14:00Z' }, now), '14 min left: keep it');
  ok(W.needsFreshLink({ url: coded, expires_at: '2026-10-07T21:00:30Z' }, now), 'under a minute left: refresh');
}

console.log('\nwho sees what');
{
  const pm = card(me('not_connected'), { isAdmin: false });
  ok(pm.visible && pm.alerts && pm.groups === null, 'PM: header + alerts, no Groups');
  const admin = card(me('not_connected'), { isAdmin: true });
  ok(admin.alerts && admin.groups, 'Admin: all sections');
  ok(card(me('not_eligible'), { isAdmin: false }).visible === false, 'anyone else: no card');
}

console.log('\ngroups (admin)');
{
  const g = card(me('connected'), { isAdmin: true, pendingCount: 3 }).groups;
  ok(g.action && g.action.label === 'Link new groups' && g.action.count === 3 && g.line === null,
     'pending groups: Link new groups with count');
  const e = card(me('connected'), { isAdmin: true, pendingCount: 0 }).groups;
  ok(e.action === null && e.line === W.GROUPS_EMPTY_LINE, 'none pending: no button, one line');
  ok(W.GROUPS_EMPTY_LINE ===
     "Add the Levelog number to a job's WhatsApp group. It will appear here to link.",
     'the empty line, word for word');
  const off = W.whatsappCardView({ me: me('connected'),
    status: { platform_configured: true, company_active: false }, isAdmin: true }).groups;
  ok(off.action && off.action.kind === 'activate', 'company not set up: Turn on WhatsApp');
}

console.log('\npolling');
ok(W.WA_POLLING_STATES.has('not_connected') && W.WA_POLLING_STATES.has('reconnect_needed'),
   'polls while a START may be on its way');
ok(!W.WA_POLLING_STATES.has('connected'), 'not once on');
ok(W.formatWaPhone('5551234567') === '+1 (555) 123-4567', 'phone formatting');

console.log('\nwhere the card lives');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');
const integrations = read('app/admin/integrations.jsx');
const cardSrc = read('src/components/WhatsAppCard.jsx');
ok((integrations.match(/<WhatsAppCard /g) || []).length === 2,
   'Integrations renders the one card (admin and PM views)');
ok(/<WhatsAppCard isAdmin \/>/.test(integrations) && /<WhatsAppCard isAdmin=\{false\} \/>/.test(integrations),
   'admin gets isAdmin, PM does not');
ok(!/WhatsApp Integration Card|whatsappStatus|handleActivateWhatsapp|WhatsAppConnectCard/.test(integrations),
   'the old company card is gone (no second WhatsApp title or icon)');
ok((cardSrc.match(/<MessageCircle /g) || []).length === 1, 'one WhatsApp icon in the card');
ok(/const shouldPoll = !me \|\| WA_POLLING_STATES\.has\(state\)/.test(cardSrc),
   'live refresh kept, and a failed first read is retried');
ok(!/whatsappAPI|Connect WhatsApp|waMe/.test(read('app/settings.jsx')), 'nothing in Settings');
ok(/whatsappAPI\.connectLink\(\)/.test(cardSrc) && /connectUrl: link && link\.url/.test(cardSrc),
   'the card fetches the single-use link before the tap and uses it');
ok(!/setLink\(null\)/.test(cardSrc), 'a tap does not throw the link away (no race with the send)');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
