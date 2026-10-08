/**
 * INTEGRATIONS → THE ONE WHATSAPP CARD: what it says for each server state,
 * who sees which section, and where it lives.
 *
 *   header       Levelog number + one chip + Save to Contacts
 *   Levelog Assistant  one chip + one plain line per state; Turn on / Turn off only
 *                when the server sent the link
 *   Groups       Admins only; every group the number is in, or one line
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

console.log('\nLevelog Assistant: one chip, one line per state');
{
  const a = card(me('not_connected')).alerts;
  ok(a.chip.label === 'Assistant off', 'off');
  ok(a.line === 'Get updates for your projects on WhatsApp from Levelog Assistant.', 'off: the line');
  ok(a.button && a.button.label === 'Turn on Levelog Assistant' && a.button.url === ON,
     'off: Turn on Levelog Assistant opens wa.me with START and the code');
}
{
  const a = card(me('connected')).alerts;
  ok(a.chip.label === 'Assistant on' && a.chip.tone === 'ok', 'on');
  ok(a.button && a.button.label === 'Turn off Assistant' && a.button.url === OFF, 'on: Turn off opens wa.me STOP');
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
ok(card(me('reconnect_needed')).alerts.button.label === 'Turn on Levelog Assistant', 'reconnect: button to turn on again');
for (const st of ['phone_missing', 'phone_shared', 'unavailable']) {
  ok(card(me(st)).alerts.button === null, `${st}: no button`);
}
ok(card({ ...me('not_connected'), connect_url: null }).alerts.button === null,
   'no link from the server: no button, whatever the state');

console.log('\nthe single-use link');
{
  const coded = 'https://wa.me/15165494475?text=START%20ABC234';
  const a = W.whatsappCardView({ me: me('not_connected'), status: active, connectUrl: coded }).alerts;
  ok(a.button.url === coded, 'Turn on Levelog Assistant opens the fresh coded link when there is one');
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
  const list = [
    { group_id: 'a', group_name: '588 Thomas Project', project_id: 'p1',
      project_label: '588 Thomas S Boyland St', status: 'gc_confirmed' },
    { group_id: 'b', group_name: 'Thomas Plumbing', project_id: 'p1',
      project_label: '588 Thomas S Boyland St', status: 'trade' },
    { group_id: 'c', group_name: 'Walworth', project_id: 'p2',
      project_label: '8 Walworth St', status: 'gc_waiting' },
    { group_id: 'd', group_name: 'New Job Crew', project_id: null,
      project_label: null, status: 'not_linked' },
  ];
  const g = card(me('connected'), { isAdmin: true, groups: list }).groups;
  ok(g.line === null && g.rows.length === 4, 'every group is a row, no empty line');
  ok(g.rows[0].name === '588 Thomas Project' && g.rows[0].place === '588 Thomas S Boyland St',
     'linked: group name, then the job address');
  ok(g.rows[0].chip.label === 'GC group confirmed' && g.rows[0].chip.tone === 'ok', 'GC group confirmed');
  ok(g.rows[1].chip.label === 'Trade group', 'trade group');
  ok(g.rows[2].chip.label === 'Waiting for confirm' && g.rows[2].chip.tone === 'warn', 'waiting for confirm');
  ok(g.rows[3].place === 'Not linked' && g.rows[3].link === true && g.rows[3].chip === null,
     'not linked: says so, with a Link button');
  ok(g.rows.slice(0, 3).every((r) => r.link === false), 'linked groups have no Link button');
  const one = card(me('connected'), { isAdmin: true, groups: [list[0]] }).groups;
  ok(one.rows.length === 1 && one.line === null,
     'one linked group and nothing pending is NOT the empty state (the 588 Thomas bug)');
  const e = card(me('connected'), { isAdmin: true, groups: [] }).groups;
  ok(e.rows.length === 0 && e.line === W.GROUPS_EMPTY_LINE, 'in no group at all: the empty line');
  const loading = card(me('connected'), { isAdmin: true }).groups;
  ok(loading.rows.length === 0 && loading.line === null, 'not loaded yet: no empty line');
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
ok(/DOB\/DOT alert switches are in each project's WhatsApp tab\./.test(cardSrc)
   && /router\.push\('\/projects'\)/.test(cardSrc),
   'Levelog Assistant: where the DOB/DOT switches are, linking to the project list');
ok(/\{isAdmin \? \(\s*<Text style=\{s\.line\}>\s*DOB\/DOT alert switches/.test(cardSrc),
   'that line is for admins only (the project WhatsApp tab is admin-only)');
ok(/whatsappAPI\.getCompanyGroups\(\)/.test(cardSrc) && /groups\.rows\.map/.test(cardSrc),
   'Groups: every group from /whatsapp/company-groups, one row each');
ok(/g\.link \?[\s\S]{0,120}router\.push\('\/admin\/whatsapp-groups'\)/.test(cardSrc),
   'a group not linked yet has a Link button');
{
  const brand = read('src/components/HeaderBrand.js');
  ok(/export const BRAND_LABEL = 'Levelog';/.test(brand) && /\{BRAND_LABEL\}/.test(brand),
     'header says Levelog');
  ok(!/ellipsizeMode|maxWidth: 280|company_name|gc_business_name/.test(brand),
     'header is not truncated and no longer shows the company name');
}
ok(!/whatsappAPI|Connect WhatsApp|waMe/.test(read('app/settings.jsx')), 'nothing in Settings');
ok(/whatsappAPI\.connectLink\(\)/.test(cardSrc) && /connectUrl: link && link\.url/.test(cardSrc),
   'the card fetches the single-use link before the tap and uses it');
ok(!/setLink\(null\)/.test(cardSrc), 'a tap does not throw the link away (no race with the send)');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
