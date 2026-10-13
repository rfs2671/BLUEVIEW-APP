/* eslint-disable */
// node src/utils/whatsappCompany.test.cjs
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const W = loadEsm('src/utils/whatsappCompany.js');

let pass = 0, fail = 0;
const ok = (c, msg) => { if (c) { pass++; console.log('  PASS ', msg); } else { fail++; console.log('  FAIL ', msg); } };

console.log('\ncompany settings');
ok(W.COMPANY_SWITCHES.map((s) => s.label).join('|') === 'Default: chase on Sundays|Shabbos / Yom Tov off|'
   + 'Still send critical DOB alerts on Shabbos (Stop Work Order, Vacate)', 'the labels, word for word');
ok(W.companyView({}).map((s) => s.value).join() === 'true,true,false',
   'defaults: Sundays chased, Shabbos off, critical alerts wait');
ok(W.companyView({ chase_sundays_default: false })[0].value === false, 'off when saved off');
ok(W.companyView({ shabbos_critical_alerts: true })[2].value === true, 'on when saved on');
ok(W.companyView(null)[0].key === 'chase_sundays_default', 'keyed for the PATCH');
console.log('\npunch list detail');
ok(W.choiceView({})[0].key === 'punch_detail' && W.choiceView({})[0].value === 'simple', 'Simple unless set');
ok(W.choiceView({ punch_detail: 'detailed' })[0].value === 'detailed', 'Detailed when saved');
ok(W.choiceView({ punch_detail: 'bogus' })[0].value === 'simple', 'an unknown value reads as the default');
ok(W.COMPANY_CHOICES[0].options.map((o) => o.label).join('|') === 'Simple|Detailed', 'the two options, word for word');
{
  const panel = fs.readFileSync(path.join(__dirname, '..', 'components', 'whatsapp', 'CompanyWhatsAppPanel.jsx'), 'utf8');
  ok(/whatsappAPI\.setCompanySettings\(\{ \[sw\.key\]: v \}\)/.test(panel), 'the panel saves each switch');
  ok(/onPress=\{\(\) => change\(c, o\.value\)\}/.test(panel), 'the panel saves the detail choice');
  ok(fs.existsSync(path.join(__dirname, '..', '..', 'app', 'whatsapp', 'company.jsx')), 'the screen exists');
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
