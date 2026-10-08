/**
 * PROJECT → WHATSAPP TAB: one screen. Header with the group count, groups by
 * their real names (never a raw …@g.us id), Levelog Assistant (admins), and
 * what the bot does in each group (admins) — only settings that work.
 *
 * Run:  node src/utils/whatsappSettings.test.cjs
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

const W = loadEsm('src/utils/whatsappSettings.js');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');

console.log('names, never ids');
ok(W.groupLabel('Main St Project') === 'Main St Project', 'a real name is shown');
ok(W.groupLabel('123') === '123' && W.groupLabel('100-102') === '100-102', 'a numeric subject is a name');
for (const raw of ['120363424969499174@g.us', '', null, undefined, '120363424969499174',
  '15551234567-1600000000', '  ']) {
  ok(W.groupLabel(raw) === 'Unnamed group', `"${raw}" shows as Unnamed group`);
}
ok(W.headerTitle(0) === 'WhatsApp · 0 groups linked', 'header, none');
ok(W.headerTitle(1) === 'WhatsApp · 1 group linked', 'header, one');
ok(W.headerTitle(3) === 'WhatsApp · 3 groups linked', 'header, three');
ok(W.messageCountLabel(1) === '1 message' && W.messageCountLabel(12) === '12 messages', 'message count');

console.log('\nLevelog Assistant');
const G1 = { wa_group_id: '1@g.us', group_name: 'Main St Project' };
const G2 = { wa_group_id: '2@g.us', group_name: '2@g.us' };
const base = { groups: [G1, G2], violation_alerts: true, permit_reminders: false,
  gc_pending_question: false, gc_group: null, send_window: { mode: 'anytime' } };
{
  const v = W.assistantView({ ...base, gc_group: { ...G1, confirmed: true } });
  ok(v.gc.name === 'Main St Project' && v.gc.action === 'Change', 'GC group: name + Change');
  ok(v.choices.find((c) => c.current).id === '1@g.us', 'current group marked');
  ok(v.choices.find((c) => c.id === '2@g.us').name === 'Unnamed group', 'an unnamed choice is not shown as its id');
  ok(v.switches.map((s) => s.label).join('|')
     === ['New DOB violations → GC group', 'Permit expiry reminders → GC group',
       'New DOB complaints → GC group', 'Stop-work orders → GC group',
       'Violation status changes → GC group', 'Permit status changes → GC group',
       'New DOT summonses → GC group', 'DOT permit expiry → GC group'].join('|'),
     'every alert switch, by name');
  ok(v.switches.map((s) => s.key).join('|')
     === 'violation_alerts|permit_reminders|complaint_alerts|swo_alerts|'
       + 'violation_status_alerts|permit_status_alerts|dot_violation_alerts|dot_permit_alerts',
     'switch keys match the server (wa_alerts.SWITCHES)');
  ok(v.switches.slice(2).every((s) => s.value === true), 'a switch the server did not send reads on (default on)');
  ok(v.switches[0].value === true && v.switches[1].value === false, 'switches carry the server values');
}
{
  const v = W.assistantView(base);
  ok(v.gc.name === null && v.gc.action === 'Pick group', 'none yet: Pick group');
  ok(/Nothing is posted/.test(v.gc.line), 'none yet: says nothing is posted');
}
ok(W.assistantView({ ...base, gc_pending_question: true }).gc.line.includes('main admin'),
   'question pending: says so');
ok(W.assistantView({ ...base, gc_group: { ...G1, confirmed: false } }).gc.name === null,
   'an unconfirmed group is not the GC group');

console.log('\nwhen to send');
ok(W.SEND_WINDOW_OPTIONS.map((o) => o.label).join('|')
   === 'Anytime|Work hours (7 AM–7 PM)|Custom hours', 'the three choices, word for word');
ok(W.assistantView({ ...base, send_window: undefined }).sendWindow.mode === 'anytime', 'default Anytime');
ok(/as soon as/.test(W.sendWindowLine({ mode: 'anytime' })), 'anytime line');
ok(/7 AM to 7 PM.*goes out at 7 AM/.test(W.sendWindowLine({ mode: 'work_hours' })), 'work hours: held to 7 AM');
ok(/6:30 AM to 3:00 PM.*goes out at 6:30 AM/.test(
  W.sendWindowLine({ mode: 'custom', start: '06:30', end: '15:00' })), 'custom: held to its start');
ok(JSON.stringify(W.cleanSendWindow({ mode: 'custom', start: '22:00', end: '06:00' }))
   === '{"mode":"custom","start":"22:00","end":"06:00"}', 'overnight custom is valid');
ok(W.cleanSendWindow({ mode: 'custom', start: '07:00', end: '07:00' }) === null, 'same start and end refused');
ok(W.cleanSendWindow({ mode: 'custom', start: '7', end: '19:00' }) === null, 'bad time refused');
ok(W.cleanSendWindow({ mode: 'nightly' }) === null, 'unknown mode refused');

console.log('\nwhat the bot does: only settings that work');
const keys = W.BOT_SETTINGS.map((s) => s.key);
for (const k of ['bot_enabled', 'features.who_on_site', 'features.dob_status', 'features.open_items',
  'features.plan_queries', 'features.material_detection', 'features.voice_notes',
  'features.address_mode', 'daily_summary_enabled', 'checklist_extraction_enabled']) {
  ok(keys.includes(k), `kept: ${k}`);
}
ok(!keys.some((k) => /cross_project|nickname/.test(k)), 'removed: cross_project_summary, nickname');
ok(W.BOT_SETTINGS.every((s) => s.label && s.line && !s.line.includes('\n')), 'each has a plain name and one line');
const strict = W.BOT_SETTINGS.find((s) => s.key === 'features.address_mode');
ok(W.botSettingValue({ features: { address_mode: 'strict' } }, strict) === true
   && W.botSettingValue({ features: { address_mode: 'loose' } }, strict) === false, 'name-only maps to strict');
ok(W.withBotSetting({ features: { address_mode: 'loose', voice_notes: true } }, strict, true).features.address_mode === 'strict'
   && W.withBotSetting({ features: { address_mode: 'loose', voice_notes: true } }, strict, true).features.voice_notes === true,
   'changing one feature keeps the others');
ok(!('cross_project_summary' in W.configForSave({ bot_enabled: true, cross_project_summary: false })),
   'the dead key is never sent');

console.log('\nthe screen');
const tab = read('app/projects/[id]/whatsapp-groups.jsx');
const card = read('src/components/whatsapp/LevelogAssistantCard.jsx');
const panel = read('src/components/whatsapp/GroupConfigPanel.jsx');
const all = tab + card + panel;
ok(/headerTitle\(/.test(tab), 'header: WhatsApp · N groups linked');
ok(!/Groups waiting|Open groups waiting/.test(tab), 'no Groups waiting on this tab');
ok(!/nickname/i.test(tab) && !/nickname/i.test(read('app/admin/whatsapp-groups.jsx')),
   'no Job nickname in the WhatsApp UI');
ok(!/Plan Query Index|getIndexStatus|Requires Qwen/.test(all), 'no plan-index card, no false Qwen badge');
ok(!/group_name \|\| group\.name|row\.group_name \|\| row\.group_id|\|\| gid/.test(all
   + read('app/admin/whatsapp-groups.jsx') + read('app/projects/[id]/whatsapp-checklists.jsx')),
   'no fallback that could show a raw id');
ok(/isAdmin && !readOnly \? \(\s*<LevelogAssistantCard/.test(tab), 'Levelog Assistant: admins only');
ok(/What the bot does in groups/.test(tab) && /isAdmin && !readOnly && groups.length > 0/.test(tab),
   'What the bot does: admins only');
ok(/BOT_SETTINGS\.map/.test(panel), 'the group panel renders exactly BOT_SETTINGS');
ok(/const canUnlink = \['admin', 'pm'\]\.includes\(role\)/.test(tab) && /\{canUnlink \? \(/.test(tab),
   'unlink: admin and PM only (never CP, superintendent or owner)');
ok(/DOB alerts/.test(W.BOT_SETTINGS.find((s) => s.key === 'bot_enabled').line),
   'Answer in this group: off silences DOB alerts too');
const integrationsCard = read('src/components/WhatsAppCard.jsx') + read('src/utils/whatsappConnect.js');
ok(!/Turn on alerts|Your alerts|'Off'|'On'/.test(integrationsCard), 'the Integrations card says Levelog Assistant, never alerts');
ok(/<Redirect href=\{`\/projects\/\$\{id\}\/whatsapp-groups`\}/.test(read('app/project/[id]/whatsapp-settings.jsx')),
   'the old settings route lands on the tab');
ok(!/summar(y|ies) to|reply alert|coming soon|Blueview/i.test(card), 'no placeholders in Levelog Assistant');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
