/**
 * INTEGRATIONS → THE ONE WHATSAPP CARD and its two screens: what each says
 * for each server state, who sees what, and where it lives.
 *
 *   the card     Connected chip, Levelog number, Save to Contacts, and the
 *                Project groups / Personal assistant buttons — nothing else
 *   Personal assistant  one chip + one plain line per state; Turn on / Turn
 *                off only when the server sent the link
 *   Project groups      every group the number is in, or one line; a row
 *                opens its project's WhatsApp tab; a PM reads only
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

console.log('the card');
{
  const v = card(me('not_connected'), { isAdmin: true });
  ok(v.header.number === '+1 (516) 549-4475', 'Levelog number formatted');
  ok(v.header.chip.label === 'Connected' && v.header.chip.tone === 'ok', 'company set up: Connected');
  ok(v.header.contactUrl === 'https://wa.me/15165494475?text=contact',
     'Save to Contacts opens WhatsApp with "contact" to the Levelog number');
  const notSetUp = W.whatsappCardView({ me: me('not_connected'),
    status: { platform_configured: true, company_active: false }, isAdmin: true });
  ok(notSetUp.header.chip.label === 'Not set up' && !notSetUp.header.contactUrl,
     'company not set up: chip says so, no Save to Contacts');
  ok(Object.keys(v).sort().join() === 'assistantButton,groupsButton,header,visible',
     'nothing else on the card: header and the two buttons');
  ok(v.groupsButton.label === 'Project groups' && v.groupsButton.path === '/whatsapp/groups',
     'Project groups button');
  ok(v.assistantButton.label === 'Personal assistant'
     && v.assistantButton.path === '/whatsapp/assistant'
     && v.assistantButton.chip.label === 'Assistant off', 'Personal assistant button, with its state');
}

console.log('\nLevelog Assistant: one chip, one line per state');
{
  const a = W.alertsView(me('not_connected'));
  ok(a.chip.label === 'Assistant off', 'off');
  ok(a.line === 'Get updates for your projects on WhatsApp from Levelog Assistant.', 'off: the line');
  ok(a.button && a.button.label === 'Turn on Levelog Assistant' && a.button.url === ON,
     'off: Turn on Levelog Assistant opens wa.me with START and the code');
}
{
  const a = W.alertsView(me('connected'));
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
  const a = W.alertsView(me(st));
  ok(a.chip.label === label && a.chip.tone === 'warn', `${st}: chip "${label}"`);
  ok(typeof a.line === 'string' && a.line.includes(fixWord) && !a.line.includes('\n'),
     `${st}: one line saying what to fix`);
}
ok(W.alertsView(me('reconnect_needed')).button.label === 'Turn on Levelog Assistant', 'reconnect: button to turn on again');
for (const st of ['phone_missing', 'phone_shared', 'unavailable']) {
  ok(W.alertsView(me(st)).button === null, `${st}: no button`);
}
ok(W.alertsView({ ...me('not_connected'), connect_url: null }).button === null,
   'no link from the server: no button, whatever the state');

console.log('\nthe single-use link');
{
  const coded = 'https://wa.me/15165494475?text=START%20ABC234';
  const a = W.alertsView(me('not_connected'), coded);
  ok(a.button.url === coded, 'Turn on Levelog Assistant opens the fresh coded link when there is one');
  const fb = W.alertsView({ ...me('not_connected'), connect_url: 'https://wa.me/15165494475?text=START' });
  ok(fb.button.url === 'https://wa.me/15165494475?text=START', 'falls back to plain START');
  const blocked = W.alertsView(me('phone_missing'), coded);
  ok(blocked.button === null, 'a coded link never shows where the server offers none');
  const now = Date.parse('2026-10-07T21:00:00Z');
  ok(W.needsFreshLink(null, now), 'no link: fetch one');
  ok(!W.needsFreshLink({ url: coded, expires_at: '2026-10-07T21:14:00Z' }, now), '14 min left: keep it');
  ok(W.needsFreshLink({ url: coded, expires_at: '2026-10-07T21:00:30Z' }, now), 'under a minute left: refresh');
}

console.log('\nwho sees what');
{
  const pm = card(me('not_connected'), { isAdmin: false });
  ok(pm.visible && pm.groupsButton && pm.assistantButton, 'PM: both buttons (groups read-only)');
  const admin = card(me('not_connected'), { isAdmin: true });
  ok(admin.groupsButton && admin.assistantButton, 'Admin: both buttons');
  const notForMe = card(me('not_eligible'), { isAdmin: true });
  ok(notForMe.visible && notForMe.assistantButton === null, 'assistant not for them: no Personal assistant button');
  ok(card(me('not_eligible'), { isAdmin: false }).visible === false, 'anyone else: no card');
}

console.log('\nProject groups');
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
  const view = (opts) => W.groupsView({ status: active, ...opts });
  const g = view({ groups: list, canLink: true });
  ok(g.line === null && g.rows.length === 4, 'every group is a row, no empty line');
  ok(g.rows[0].name === '588 Thomas Project' && g.rows[0].place === '588 Thomas S Boyland St',
     'linked: group name, then the job address');
  ok(g.rows[0].chip.label === 'GC group confirmed' && g.rows[0].chip.tone === 'ok', 'GC group confirmed');
  ok(g.rows[1].chip.label === 'Trade group', 'trade group');
  ok(g.rows[2].chip.label === 'Waiting for confirm' && g.rows[2].chip.tone === 'warn', 'waiting for confirm');
  ok(g.rows[3].place === 'Not linked' && g.rows[3].link === true && g.rows[3].chip === null,
     'not linked: says so, with a Link button');
  ok(g.rows.slice(0, 3).every((r) => r.link === false), 'linked groups have no Link button');
  ok(W.projectWhatsAppPath(g.rows[0].projectId) === '/projects/p1/whatsapp-groups'
     && g.rows[3].projectId === null,
     "a linked row opens its project's WhatsApp tab; an unlinked one goes nowhere");
  ok(W.projectWhatsAppPath('p1', { readOnly: true }) === '/projects/p1/whatsapp-groups?view=readonly',
     "a PM opens the project's WhatsApp tab view-only");
  const pm = view({ groups: list.slice(0, 3), canLink: false });
  ok(pm.rows.every((r) => r.link === false), 'PM: read-only, no Link button');
  const pmUnlinked = view({ groups: [list[3]], canLink: false });
  ok(pmUnlinked.rows[0].link === false, 'never a Link button without the right to link');
  const one = view({ groups: [list[0]], canLink: true });
  ok(one.rows.length === 1 && one.line === null,
     'one linked group and nothing pending is NOT the empty state (the 588 Thomas bug)');
  const e = view({ groups: [], canLink: true });
  ok(e.rows.length === 0 && e.line === W.GROUPS_EMPTY_LINE, 'in no group at all: the empty line');
  const loading = view({ canLink: true });
  ok(loading.rows.length === 0 && loading.line === null, 'not loaded yet: no empty line');
  ok(W.GROUPS_EMPTY_LINE ===
     "Add the Levelog number to a job's WhatsApp group. It will appear here to link.",
     'the empty line, word for word');
  const off = W.groupsView({ status: { platform_configured: true, company_active: false }, canLink: true });
  ok(off.action && off.action.kind === 'activate', 'company not set up: Turn on WhatsApp (admins)');
  const offPm = W.groupsView({ status: { platform_configured: true, company_active: false }, canLink: false });
  ok(offPm.action === null, 'a PM cannot turn WhatsApp on');
}

console.log('\npolling');
ok(W.WA_POLLING_STATES.has('not_connected') && W.WA_POLLING_STATES.has('reconnect_needed'),
   'polls while a START may be on its way');
ok(!W.WA_POLLING_STATES.has('connected'), 'not once on');
ok(W.formatWaPhone('5551234567') === '+1 (555) 123-4567', 'phone formatting');

console.log('\nwhere it lives');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');
const integrations = read('app/admin/integrations.jsx');
const cardSrc = read('src/components/WhatsAppCard.jsx');
const groupsSrc = read('src/components/WhatsAppGroupsPanel.jsx');
const assistantSrc = read('src/components/WhatsAppAssistantPanel.jsx');
ok((integrations.match(/<WhatsAppCard /g) || []).length === 2,
   'Integrations renders the one card (admin and PM views)');
ok(/<WhatsAppCard isAdmin \/>/.test(integrations) && /<WhatsAppCard isAdmin=\{false\} \/>/.test(integrations),
   'admin gets isAdmin, PM does not');
ok((cardSrc.match(/<MessageCircle /g) || []).length === 1, 'one WhatsApp icon in the card');
ok(!/Switch|briefRow|getCompanyGroups|groups\.rows|alerts\.line/.test(cardSrc),
   'the card holds no assistant settings and no group list');
ok(/Linking\.openURL\(header\.contactUrl\)/.test(cardSrc), 'Save to Contacts opens the wa.me "contact" link');
ok(/router\.push\(b\.path\)/.test(cardSrc), 'the two buttons open their screens');
ok(/<WhatsAppGroupsPanel canLink=\{canLink\} \/>/.test(read('app/whatsapp/groups.jsx')),
   'Project groups screen');
ok(/<WhatsAppAssistantPanel \/>/.test(read('app/whatsapp/assistant.jsx')), 'Personal assistant screen');
ok(/whatsappAPI\.getCompanyGroups\(\)/.test(groupsSrc) && /view\.rows\.map/.test(groupsSrc),
   'Project groups: every group from /whatsapp/company-groups, one row each');
ok(/projectWhatsAppPath\(g\.projectId, \{ readOnly: !canLink \}\)/.test(groupsSrc)
   && /router\.push\(path\)/.test(groupsSrc),
   "a row opens its project's WhatsApp tab (view-only for a PM)");
{
  const tab = read('app/projects/[id]/whatsapp-groups.jsx');
  ok(/const viewOnly = view === 'readonly';/.test(tab) && /\{canUnlink && !viewOnly \? \(/.test(tab),
     'view-only: no Unlink on the project tab');
}
ok(/g\.link \?[\s\S]{0,120}router\.push\('\/admin\/whatsapp-groups'\)/.test(groupsSrc),
   'a group not linked yet has a Link button');
ok(/const shouldPoll = !me \|\| WA_POLLING_STATES\.has\(state\)/.test(assistantSrc),
   'Personal assistant: live refresh kept, and a failed first read is retried');
ok(/whatsappAPI\.connectLink\(\)/.test(assistantSrc) && /alertsView\(me, link && link\.url\)/.test(assistantSrc),
   'the single-use link is fetched before the tap and used');
ok(!/setLink\(null\)/.test(assistantSrc), 'a tap does not throw the link away (no race with the send)');
{
  const pkg = read('package.json');
  const app = read('app.json');
  ok(!/expo-contacts/.test(pkg + app) && !/CONTACTS/.test(app),
     'expo-contacts and the Contacts permissions are gone');
  ok(!fs.existsSync(path.join(__dirname, 'saveContact.js')), 'the .vcf / share helper is gone');
}
{
  const brand = read('src/components/HeaderBrand.js');
  const B = loadEsm('src/utils/brandLabel.js');
  ok(B.brandLabel({ gc_business_name: 'BLUEVIEW CONSTRUCTION', company_name: 'x' })
     === 'BLUEVIEW CONSTRUCTION', 'header: the company (GC) name');
  ok(B.brandLabel({ company_name: 'Acme' }) === 'Acme', 'company_name when no GC name');
  ok(B.brandLabel({ company_name: '  ' }) === 'Levelog' && B.brandLabel(null) === 'Levelog',
     '"Levelog" only when the company name is empty');
  ok(B.brandSizing('ACME', 393).fontSize === 27, 'a short name keeps the full size');
  const long = B.brandSizing('BLUEVIEW CONSTRUCTION', 393);
  ok(long.fontSize < 27 && long.fontSize >= 14, 'a long name starts smaller');
  ok(21 * (long.fontSize * 0.68 + long.letterSpacing) <= long.maxWidth,
     'BLUEVIEW CONSTRUCTION fits a 393pt phone on one line, uncut');
  ok(B.brandSizing('BLUEVIEW CONSTRUCTION', 1200).fontSize === 27, 'wide screen: full size');
  ok(B.brandSizing('X'.repeat(80), 393).fontSize === 14, 'never below 14');
  ok(Math.abs(long.fontSize * long.minimumFontScale - 14) < 0.01,
     'shrink-to-fit stops at 14pt');
  ok(/numberOfLines=\{1\}/.test(brand) && /adjustsFontSizeToFit/.test(brand)
     && /ellipsizeMode="tail"/.test(brand) && /minimumFontScale=\{minimumFontScale\}/.test(brand),
     'one line, shrink to fit, ellipsis only past the minimum');
  ok(/brandLabel\(user\)/.test(brand) && !/maxWidth: 280/.test(brand),
     'header uses the company name; the fixed 280px cap is gone');
}
ok(!/whatsappAPI|Connect WhatsApp|waMe/.test(read('app/settings.jsx')), 'nothing in Settings');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
