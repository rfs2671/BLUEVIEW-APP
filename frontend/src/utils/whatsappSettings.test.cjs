/**
 * PROJECT → WHATSAPP SETTINGS: only live settings, admin only, and the
 * GC group line for each state.
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
const G1 = { wa_group_id: '1@g.us', group_name: 'Main St Project' };
const G2 = { wa_group_id: '2@g.us', group_name: 'Main St Plumbing' };
const base = { groups: [G1, G2], violation_alerts: true, permit_reminders: false,
  gc_pending_question: false, gc_group: null };

console.log('the GC group');
{
  const v = W.whatsappSettingsView({ ...base, gc_group: { ...G1, confirmed: true } });
  ok(v.gc.name === 'Main St Project' && v.gc.action === 'Change', 'confirmed: name + Change');
  ok(v.choices.find((c) => c.current).id === '1@g.us', 'the current group is marked');
  ok(v.switches.length === 2, 'both switches once a group is confirmed');
  ok(v.switches[0].value === true && v.switches[1].value === false, 'switches carry the server values');
  ok(v.hoursLine.includes('7 AM and 7 PM'), 'says when it posts');
}
{
  const v = W.whatsappSettingsView(base);
  ok(v.gc.name === null && v.gc.action === 'Pick group', 'none yet: Pick group');
  ok(v.gc.line.includes('Nothing is posted'), 'none yet: says nothing is posted');
  ok(v.switches.length === 0, 'no switches before a group is confirmed');
}
{
  const v = W.whatsappSettingsView({ ...base, gc_pending_question: true });
  ok(v.gc.line.includes('main admin') && v.gc.action === 'Pick group',
     'question pending: says so, and the admin can still pick');
}
{
  const v = W.whatsappSettingsView({ ...base, groups: [] });
  ok(v.gc.action === null && v.gc.line.includes('Add the Levelog number'), 'no groups: no button, one line');
}
ok(W.whatsappSettingsView(null) === null, 'no data: nothing');
ok(W.whatsappSettingsView({ ...base, gc_group: { ...G1, confirmed: false } }).gc.name === null,
   'an unconfirmed group is not shown as the GC group');

console.log('\nonly live features');
const keys = W.ALERT_SWITCHES.map((s) => s.key).sort().join(',');
ok(keys === 'permit_reminders,violation_alerts', 'exactly the two live alerts');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');
const screen = read('app/project/[id]/whatsapp-settings.jsx');
const all = screen + read('src/utils/whatsappSettings.js');
ok(!/summar|reply alert|inspection|coming soon|Blueview/i.test(all),
   'no summaries, reply alerts, inspections, placeholders or Blueview');

console.log('\nadmins only');
ok(/isCompanyAdmin\(user\)/.test(screen), 'the screen checks for an admin');
const project = read('app/project/[id].jsx');
ok(/isAdmin \? \[\{ title: 'WhatsApp settings'/.test(project),
   'the quick action shows for admins only');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
