/**
 * INTEGRATIONS → LEVELOG ASSISTANT → MORNING BRIEF: one row, "Morning
 * brief: 7 AM ▾" + Saturday, only for an eligible, connected user.
 *
 * Run:  node src/utils/whatsappBrief.test.cjs
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

const B = loadEsm('src/utils/whatsappBrief.js');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');

console.log('options');
ok(B.BRIEF_OPTIONS.map((o) => o.label).join('|') === 'Off|7 AM|8 AM|9 AM', 'Off / 7 / 8 / 9 AM');
ok(B.BRIEF_OPTIONS.map((o) => o.value).join('|') === 'off|07:00|08:00|09:00', 'values the server takes');
ok(B.briefTimeLabel('08:00') === '8 AM' && B.briefTimeLabel('x') === '7 AM', 'labels, default 7 AM');

console.log('\nwhen it shows');
ok(B.briefRow(null) === null, 'nothing loaded: hidden');
ok(B.briefRow({ connected: false, brief: null }) === null, 'not connected: hidden');
ok(B.briefRow({ connected: true, brief: null }) === null, 'no brief from server: hidden');
{
  const r = B.briefRow({ connected: true, brief: { brief_time: '07:00', brief_saturday: false } });
  ok(r.label === 'Morning brief: 7 AM', 'row label');
  ok(r.saturday === false && r.saturdayDisabled === false, 'Saturday off, can be turned on');
}
{
  const r = B.briefRow({ connected: true, brief: { brief_time: 'off', brief_saturday: true } });
  ok(r.label === 'Morning brief: Off', 'off label');
  ok(r.saturdayDisabled === true, 'Saturday switch disabled while off');
}

console.log('\nwiring');
{
  const card = read('src/components/WhatsAppCard.jsx');
  ok(/const brief = briefRow\(me\);/.test(card), 'card reads the row from /whatsapp/me');
  ok(/saveBrief\(\{ brief_time: o\.value \}\)/.test(card), 'picking a time saves it');
  ok(/saveBrief\(\{ brief_saturday: v \}\)/.test(card), 'Saturday switch saves it');
  ok(/Also on Saturday/.test(card), 'Saturday label');
  const api = read('src/utils/api.js');
  ok(api.includes("apiClient.put('/api/whatsapp/brief', patch)"), 'PUT path');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
