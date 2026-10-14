// Run: node src/utils/projectReports.test.cjs
const { loadEsm } = require('./esmHarness.cjs');
const M = loadEsm('src/utils/projectReports.js');

let pass = 0, fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log(`  PASS  ${label}`); } else { fail++; console.log(`  FAIL  ${label}`); }
}

ok(M.canSeeReports({ role: 'admin' }) && M.canSeeReports({ role: 'pm' }), 'admin and PM see Reports');
ok(!M.canSeeReports({ role: 'cp' }) && !M.canSeeReports(null), 'others do not');
ok(M.periodLabel('2026-10-01', '2026-10-14') === 'Oct 1 – Oct 14, 2026', 'period in one year');
ok(M.periodLabel('2026-12-21', '2027-01-03') === 'Dec 21, 2026 – Jan 3, 2027', 'period across years');
ok(M.periodLabel(null, '2026-10-14') === '', 'no dates, no label');
ok(M.scheduleLabel('biweekly') === 'Every 2 weeks (Monday 8am)', 'bi-weekly says when');
ok(M.scheduleLabel('monthly') === 'Monthly (1st of the month, 8am)', 'monthly says when');
ok(M.scheduleLabel('nonsense') === 'Off', 'unknown schedule reads as off');
ok(M.sourceLabel('schedule') === 'Scheduled' && M.sourceLabel('dm') === 'Asked in WhatsApp'
   && M.sourceLabel('app') === 'Made in the app', 'where a report came from');
ok(M.pdfName({ title: '588 Thomas S Boyland St — Oct 1–14' }) === '588-Thomas-S-Boyland-St-Oct-114.pdf',
   'a safe file name');
const body = M.scheduleBody('weekly', ['a', 'a', 7]);
ok(body.schedule === 'off' && body.pm_ids.join(',') === 'a,7', 'schedule body: known schedule, unique PMs');
ok(M.RANGE_CHOICES.map((r) => r.key).join('|') === 'last 2 weeks|this month|last month', 'generate periods');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
